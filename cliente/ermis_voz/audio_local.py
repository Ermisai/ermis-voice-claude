"""Microfone e alto-falante, com cancelamento de eco.

``Duplex``: um único stream do sounddevice, entrada e saída a 48 kHz, blocos de 10 ms. No callback, o que vai para
o alto-falante é a referência exata do AEC3 (``livekit.rtc.AudioProcessingModule``) e o atraso vem dos carimbos
de tempo do próprio driver, então ele fica pequeno e estável (o AEC3 cobre até ~500 ms). O microfone limpo sai a
16 kHz (voice_api.py o leva a 8 kHz para a Voice API).

``Arquivo``: para testar sem microfone. Lê falas de WAV, devolve o TTS como eco de sala opcional e grava o que
"tocou".
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
import time
import wave
from collections import deque
from collections.abc import Callable
from pathlib import Path

import numpy as np

log = logging.getLogger("ermis_voz.audio")

RATE = 48000
BLOCK = 480  # 10 ms
MIC_RATE = 16000
TTS_RATE = 24000
# o microfone dos últimos segundos, também mudo: segurar o espaço manda desde o aperto (o comando chega depois)
ANEL_S = 3.0

OnMic = Callable[[bytes], None]  # PCM16 16 kHz


def _resample(audio: np.ndarray, src: int, dst: int) -> np.ndarray:
    if src == dst or audio.size == 0:
        return audio.astype(np.float32, copy=False)
    n = int(round(audio.size * dst / src))
    x_old = np.linspace(0.0, 1.0, audio.size, endpoint=False)
    x_new = np.linspace(0.0, 1.0, n, endpoint=False)
    return np.interp(x_new, x_old, audio).astype(np.float32)


class Decimador:
    """48 kHz -> 16 kHz com um FIR passa-baixa (sem aliasing) e estado entre blocos."""

    def __init__(self) -> None:
        taps = 63
        n = np.arange(taps) - (taps - 1) / 2
        h = np.sinc(n / 3.0) / 3.0 * np.hamming(taps)
        self.h = (h / h.sum()).astype(np.float32)
        self.state = np.zeros(taps - 1, dtype=np.float32)
        self.phase = 0

    def __call__(self, x: np.ndarray) -> np.ndarray:
        buf = np.concatenate([self.state, x.astype(np.float32)])
        y = np.convolve(buf, self.h, mode="valid")
        self.state = buf[-(self.h.size - 1) :]
        out = y[self.phase :: 3]
        self.phase = (self.phase - y.size) % 3
        return out


class Reproducao:
    """Fila do que vai tocar (48 kHz), consumida pelo callback de áudio, com um ganho que muda em rampa.

    Ninguém corta seco: ``abaixar`` (a pessoa parece estar falando por cima) leva o ganho a ~30% em 60 ms,
    ``restaurar`` (era eco ou ruído) volta a 100% em 120 ms, e ``apagar`` (barge-in, parar) leva a zero em ~150 ms e
    só então descarta o resto. Um corte sem rampa soa como um clique e parece que o agente "engasgou".
    """

    DUCK = 0.3

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._buf = np.zeros(0, dtype=np.float32)
        self.volume = 1.0
        self._gain = 1.0
        self._alvo = 1.0
        self._passo = 1.0  # quanto o ganho anda por amostra
        self._limpar_no_zero = False

    def adicionar_pcm24(self, pcm: bytes) -> None:
        audio = np.frombuffer(pcm[: len(pcm) - len(pcm) % 2], dtype="<i2").astype(np.float32) / 32768.0
        self._adicionar(_resample(audio, TTS_RATE, RATE))

    def adicionar_pcm48(self, pcm: bytes) -> None:
        """O áudio da Voice API (PCM16 48 kHz): já na taxa do alto-falante."""
        self._adicionar(np.frombuffer(pcm[: len(pcm) - len(pcm) % 2], dtype="<i2").astype(np.float32) / 32768.0)

    def _adicionar(self, up: np.ndarray) -> None:
        with self._lock:
            if self._limpar_no_zero:  # o que chega enquanto apaga já foi cortado
                return
            if self._buf.size == 0 and self._alvo < 1.0 and self._gain <= 0.0:
                self._gain, self._alvo = 1.0, 1.0  # fala nova depois de um corte
            self._buf = np.concatenate([self._buf, up])

    def _rampa(self, alvo: float, ms: float, limpar: bool = False) -> None:
        with self._lock:
            self._alvo = alvo
            self._passo = max(abs(self._gain - alvo), 1e-3) / max(1.0, RATE * ms / 1000)
            self._limpar_no_zero = limpar

    def abaixar(self) -> None:
        self._rampa(self.DUCK, 60)

    def restaurar(self) -> None:
        self._rampa(1.0, 120)

    def apagar(self, ms: float = 150) -> None:
        if self.pendente_ms <= 0:
            self.limpar()
            return
        self._rampa(0.0, ms, limpar=True)

    def limpar(self) -> None:
        with self._lock:
            self._buf = np.zeros(0, dtype=np.float32)
            self._gain, self._alvo, self._limpar_no_zero = 1.0, 1.0, False

    def tirar(self, n: int) -> np.ndarray:
        with self._lock:
            out, self._buf = self._buf[:n], self._buf[n:]
            if out.size < n:
                out = np.concatenate([out, np.zeros(n - out.size, dtype=np.float32)])
            if self._gain == self._alvo:
                ganho = np.full(n, self._gain, dtype=np.float32)
            else:
                sentido = 1.0 if self._alvo > self._gain else -1.0
                ganho = self._gain + sentido * self._passo * np.arange(1, n + 1, dtype=np.float32)
                ganho = np.minimum(ganho, self._alvo) if sentido > 0 else np.maximum(ganho, self._alvo)
                self._gain = float(ganho[-1])
            if self._limpar_no_zero and self._gain <= 0.0:
                self._buf = np.zeros(0, dtype=np.float32)
                self._gain, self._alvo, self._limpar_no_zero = 1.0, 1.0, False
        return out * ganho * self.volume

    @property
    def pendente_ms(self) -> float:
        with self._lock:
            return self._buf.size * 1000 / RATE

    @property
    def apagando(self) -> bool:
        with self._lock:
            return self._limpar_no_zero


class Aec:
    """AEC3 do WebRTC em quadros de 10 ms a 48 kHz. Sem o livekit, passa o áudio direto."""

    def __init__(self, ativo: bool = True) -> None:
        self.apm = None
        self.rtc = None
        if ativo:
            try:
                from livekit import rtc

                self.rtc = rtc
                self.apm = rtc.AudioProcessingModule(
                    echo_cancellation=True, noise_suppression=True, high_pass_filter=True, auto_gain_control=False
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("AEC indisponível (%s): use fone de ouvido", exc)
        self.delay_ms = 40
        self._last_delay_set = 0.0

    @property
    def ativo(self) -> bool:
        return self.apm is not None

    def processar(self, mic: np.ndarray, saida: np.ndarray, delay_ms: float | None) -> np.ndarray:
        if self.apm is None:
            return mic
        rtc = self.rtc
        ref = (np.clip(saida, -1, 1) * 32767).astype("<i2")
        self.apm.process_reverse_stream(rtc.AudioFrame(ref.tobytes(), RATE, 1, BLOCK))
        now = time.monotonic()
        if delay_ms is not None and now - self._last_delay_set > 1.0:
            self.delay_ms = int(min(480, max(0, delay_ms)))
            self._last_delay_set = now
        try:
            self.apm.set_stream_delay_ms(self.delay_ms)
        except RuntimeError:
            pass
        frame = rtc.AudioFrame((np.clip(mic, -1, 1) * 32767).astype("<i2").tobytes(), RATE, 1, BLOCK)
        self.apm.process_stream(frame)
        return np.frombuffer(bytes(frame.data), dtype="<i2").astype(np.float32) / 32768.0


class Duplex:
    """Microfone e alto-falante num stream só. O stream pode morrer sem avisar: um fone Bluetooth que conecta ou
    desconecta, a saída trocada no macOS, um erro no callback (04/11: nenhum quadro de microfone por quase 2 horas, e
    nenhum som). Por isso o callback nunca levanta exceção, ``vivo()`` diz se ele está rodando e ``reabrir()`` abre de
    novo nos dispositivos padrão de agora; o daemon vigia (``Daemon._vigiar_audio``)."""

    def __init__(self, on_mic: OnMic, loop: asyncio.AbstractEventLoop, aec: bool = True,
                 entrada: str = "", saida: str = "") -> None:
        import sounddevice as sd

        self.sd = sd
        self.on_mic = on_mic
        self.loop = loop
        self.reproducao = Reproducao()
        self.aec = Aec(aec)
        self.decimador = Decimador()
        self.mudo = False
        self.anel: deque[tuple[float, bytes]] = deque(maxlen=int(ANEL_S * 100))  # (time.time(), 10 ms)
        self.entrada_cfg, self.saida_cfg = entrada, saida
        self.ultimo_callback = 0.0
        self.erros_callback = 0
        self.ultimo_erro = ""
        self.reaberturas = 0
        self.dispositivos = ("", "")
        self.stream = None
        self._abrir()

    def _abrir(self) -> None:
        sd = self.sd
        if self.entrada_cfg == "" and self.saida_cfg == "":
            with contextlib.suppress(Exception):
                sd._terminate()  # o PortAudio só vê dispositivos novos (um fone que conectou) depois de reiniciado
                sd._initialize()
        device = (self.entrada_cfg or None, self.saida_cfg or None)
        self.stream = sd.Stream(
            samplerate=RATE, blocksize=BLOCK, channels=1, dtype="float32", device=device,
            callback=self._callback, latency="low", finished_callback=self._acabou,
        )
        try:
            ent, sai = self.stream.device
            self.dispositivos = (sd.query_devices(ent)["name"], sd.query_devices(sai)["name"])
        except Exception:  # noqa: BLE001
            self.dispositivos = ("?", "?")
        log.info("áudio: microfone %r, alto-falante %r", *self.dispositivos)

    def _acabou(self) -> None:
        log.warning("o stream de áudio parou (dispositivo mudou ou foi desconectado?)")

    def _callback(self, indata, outdata, frames, time_info, status) -> None:  # noqa: ANN001 — thread de áudio
        self.ultimo_callback = time.monotonic()
        try:
            saida = self.reproducao.tirar(frames)
            outdata[:, 0] = saida
            delay = None
            try:
                delay = (time_info.outputBufferDacTime - time_info.inputBufferAdcTime) * 1000.0
            except Exception:  # noqa: BLE001
                pass
            mic = indata[:, 0].copy()
            if frames == BLOCK:
                try:
                    mic = self.aec.processar(mic, saida, delay)
                except Exception as exc:  # noqa: BLE001 — sem o AEC neste quadro, mas o áudio segue
                    self._erro(f"AEC: {exc}")
            pcm = (np.clip(self.decimador(mic), -1, 1) * 32767).astype("<i2").tobytes()
            self.anel.append((time.time(), pcm))
            if not self.mudo:
                self.loop.call_soon_threadsafe(self.on_mic, pcm)
        except Exception as exc:  # noqa: BLE001 — uma exceção aqui mata o stream: nunca deixa sair
            outdata.fill(0)
            self._erro(str(exc))

    def _erro(self, msg: str) -> None:
        self.erros_callback += 1
        if self.erros_callback <= 3 or self.erros_callback % 500 == 0:
            self.loop.call_soon_threadsafe(log.warning, "erro no callback de áudio (%d): %s", self.erros_callback, msg)
        self.ultimo_erro = msg

    def vivo(self) -> bool:
        """O stream está ativo e o callback rodou há menos de 2 s."""
        return bool(self.stream is not None and self.stream.active and time.monotonic() - self.ultimo_callback < 2.0)

    def padrao_mudou(self) -> bool:
        """O dispositivo padrão do sistema não é mais o que está aberto (só quando a config não fixou um)."""
        if self.entrada_cfg or self.saida_cfg:
            return False
        try:
            ent = self.sd.query_devices(kind="input")["name"]
            sai = self.sd.query_devices(kind="output")["name"]
        except Exception:  # noqa: BLE001
            return False
        return (ent, sai) != self.dispositivos

    def reabrir(self) -> None:
        with contextlib.suppress(Exception):
            self.stream.abort()
        with contextlib.suppress(Exception):
            self.stream.close()
        self.reaberturas += 1
        self._abrir()
        self.ultimo_callback = time.monotonic()
        self.stream.start()

    def iniciar(self) -> None:
        self.ultimo_callback = time.monotonic()
        self.stream.start()

    def parar(self) -> None:
        with contextlib.suppress(Exception):
            self.stream.stop()
        with contextlib.suppress(Exception):
            self.stream.close()


class Arquivo:
    """Áudio de teste: o "microfone" toca as falas da fila (16 kHz) mais o eco do que o "alto-falante" tocou."""

    def __init__(self, on_mic: OnMic, loop: asyncio.AbstractEventLoop, eco_db: float | None = None,
                 gravar_saida: Path | None = None) -> None:
        self.on_mic = on_mic
        self.loop = loop
        self.reproducao = Reproducao()
        self.aec = Aec(False)
        self.eco_ganho = 0.0 if eco_db is None else 10 ** (eco_db / 20)
        self.fala = np.zeros(0, dtype=np.float32)
        self.mudo = False
        self.anel: deque[tuple[float, bytes]] = deque(maxlen=int(ANEL_S * 50))  # (time.time(), 20 ms)
        self._task: asyncio.Task | None = None
        self._saida = wave.open(str(gravar_saida), "wb") if gravar_saida else None
        if self._saida:
            self._saida.setnchannels(1)
            self._saida.setsampwidth(2)
            self._saida.setframerate(MIC_RATE)
        self._eco_delay = np.zeros(int(MIC_RATE * 0.15), dtype=np.float32)

    def vivo(self) -> bool:
        return self._task is not None and not self._task.done()

    def padrao_mudou(self) -> bool:
        return False

    def reabrir(self) -> None:
        if not self.vivo():
            self.iniciar()

    def dizer(self, wav: Path) -> float:
        with wave.open(str(wav)) as w:
            audio = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768.0
            audio = _resample(audio, w.getframerate(), MIC_RATE)
        self.fala = np.concatenate([self.fala, audio])
        return audio.size / MIC_RATE

    def iniciar(self) -> None:
        self._task = self.loop.create_task(self._run())

    async def _run(self) -> None:
        n = MIC_RATE // 50  # 20 ms
        t0 = time.perf_counter()
        i = 0
        while True:
            tocou = _resample(self.reproducao.tirar(RATE // 50), RATE, MIC_RATE)[:n]
            if self._saida:
                self._saida.writeframes((np.clip(tocou, -1, 1) * 32767).astype("<i2").tobytes())
            buf = np.concatenate([self._eco_delay, tocou])
            eco, self._eco_delay = buf[:n] * self.eco_ganho, buf[n:]
            voz, self.fala = self.fala[:n], self.fala[n:]
            if voz.size < n:
                voz = np.concatenate([voz, np.zeros(n - voz.size, dtype=np.float32)])
            pcm = (np.clip(voz + eco, -1, 1) * 32767).astype("<i2").tobytes()
            self.anel.append((time.time(), pcm))
            if not self.mudo:
                self.on_mic(pcm)
            i += 1
            await asyncio.sleep(max(0.0, t0 + i * 0.02 - time.perf_counter()))

    def parar(self) -> None:
        if self._task:
            self._task.cancel()
        if self._saida:
            self._saida.close()
