"""O canal com a Ermis Voice API (a API principal, ``https://voice-api.live.ermis.ai``), com a chave de quem usa.

Uma sessão com ``transport: "websocket"``: um único socket (``control_url``) leva o microfone (μ-law 8 kHz, quadros
de 20 ms), o áudio do agente (PCM16 48 kHz) e o controle em JSON. O daemon conversa com este canal no protocolo de
sempre (``falar``, ``parar``, ``tocado``... e ``fala``, ``audio_inicio``, ``barge_in``...); aqui vira o da API:

    daemon -> canal                        canal -> Voice API
    falar {id, texto, interromper}         interrupt (se pedido e há fala) + speak {id, text}
    parar                                  interrupt
    tocado {id}                            playback_finished {id}
    termos / aprendido                     set_vocabulary (e a correção local, texto.Corretor)
    fim                                    end

    Voice API -> canal                     canal -> daemon
    session.started                        pronto {sessao}
    speech.started                         falando
    transcript.partial                     parcial {texto}
    transcript                             fala {texto, cru, incerto, correcoes} (e done_processing de volta)
    speak.started / audio.end              audio_inicio / audio_fim {id}
    clear + barge_in {id}                  limpar + barge_in {id, tocado_ms}
    session.ended                          fim da iteração (o daemon abre outra sessão)

As frases de espera, a leitura e a fila entre sessões do Claude ficam no cliente: a API só recebe o que falar.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time

import numpy as np
import websockets

from ermis_voz import __version__
from ermis_voz.pronuncia import preparar
from ermis_voz.texto import Corretor

log = logging.getLogger("ermis_voz.voice_api")

API_PADRAO = "https://voice-api.live.ermis.ai"
PLATAFORMA = "https://app.ermis.ai"
MAX_SPEAK = 5000
MAX_VOCABULARIO = 200
QUADRO = 160  # 20 ms de μ-law 8 kHz
SILENCIO = b"\xff" * QUADRO
# a API encerra a sessão depois de 60 s sem áudio: com o microfone mudo (leitura), manda silêncio
KEEPALIVE_S = 2.0
# paciência -> silêncio que fecha o turno (o modelo de fim de turno da API fecha antes quando a pessoa terminou a ideia)
SILENCIO_MS = {"rapida": 500, "normal": 900, "longa": 1600}
DURACAO_MAX_S = 4 * 3600  # o teto da API; ao fim, o daemon abre outra sessão


class ErroApi(Exception):
    """Falha que a pessoa resolve (chave, créditos, canais) ou que passa sozinha (rede, erro interno)."""

    def __init__(self, mensagem: str, status: int | None = None, codigo: str = "", espera_s: float | None = None):
        super().__init__(mensagem)
        self.status = status
        self.codigo = codigo
        self.espera_s = espera_s  # quanto esperar antes de tentar de novo (None: o backoff normal)


_MOTIVOS = {
    401: ("chave de API inválida ou revogada: crie uma em {p} (Tokens API) e rode "
          "`ermis-voz config --token SUA_CHAVE`", 60.0),
    402: ("créditos insuficientes na sua conta da Ermis ({p})", 120.0),
    429: ("todos os canais do seu plano estão em uso (outra máquina com a voz ligada?)", 30.0),
}
_FECHAMENTOS = {4001: 401, 4002: 402, 4029: 429}


VELOCIDADE_MIN, VELOCIDADE_MAX = 0.75, 1.25  # o que a Voice API aceita em speech_speed


def limitar_velocidade(valor: object) -> float:
    try:
        v = float(valor)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 1.0
    return 1.0 if v != v else min(VELOCIDADE_MAX, max(VELOCIDADE_MIN, v))


def erro_http(status: int, corpo: str) -> ErroApi:
    try:
        dados = json.loads(corpo)
        err = dados.get("error") if isinstance(dados.get("error"), dict) else dados
        codigo, msg = str(err.get("code") or ""), str(err.get("message") or err.get("detail") or "")
    except (ValueError, AttributeError):
        codigo, msg = "", corpo[:200]
    if status == 429 and codigo == "rate_limited":
        return ErroApi("muitas requisições em pouco tempo", status, codigo, 10.0)
    if status in _MOTIVOS:
        texto, espera = _MOTIVOS[status]
        return ErroApi(texto.format(p=PLATAFORMA), status, codigo, espera)
    return ErroApi(f"Voice API respondeu {status}: {msg or codigo}", status, codigo)


def _erro_rede(exc: Exception) -> str:
    return str(exc) or type(exc).__name__  # o tempo esgotado do httpx vem sem mensagem


def _correcoes_api(itens) -> list[dict]:
    """As correções do vocabulary da Voice API ({heard, term, score}) no formato das nossas."""
    out = []
    for c in itens or []:
        if isinstance(c, dict) and c.get("heard") and c.get("term") and c["heard"] != c["term"]:
            out.append({"ouvido": c["heard"], "corrigido": c["term"], "fonte": "vocabulario"})
    return out


# ── áudio ────────────────────────────────────────────────────────────────
def mulaw(pcm: np.ndarray) -> bytes:
    """PCM16 (int) -> μ-law G.711."""
    s = pcm.astype(np.int32)
    sinal = np.where(s < 0, 0x80, 0)
    s = np.minimum(np.abs(s), 32635) + 0x84
    expoente = np.clip(np.floor(np.log2(s)).astype(np.int32) - 7, 0, 7)
    mantissa = (s >> (expoente + 3)) & 0x0F
    return (~(sinal | (expoente << 4) | mantissa) & 0xFF).astype(np.uint8).tobytes()


class Para8k:
    """PCM16 16 kHz -> 8 kHz com um FIR passa-baixa (sem aliasing) e estado entre blocos."""

    def __init__(self) -> None:
        taps = 31
        n = np.arange(taps) - (taps - 1) / 2
        h = np.sinc(n / 2.0) / 2.0 * np.hamming(taps)
        self.h = (h / h.sum()).astype(np.float32)
        self.estado = np.zeros(taps - 1, dtype=np.float32)
        self.fase = 0

    def __call__(self, pcm16: bytes) -> np.ndarray:
        x = np.frombuffer(pcm16[: len(pcm16) - len(pcm16) % 2], dtype="<i2").astype(np.float32)
        buf = np.concatenate([self.estado, x])
        y = np.convolve(buf, self.h, mode="valid")
        self.estado = buf[-(self.h.size - 1):]
        out = y[self.fase::2]
        self.fase = (self.fase - y.size) % 2
        return np.clip(np.round(out), -32768, 32767).astype(np.int16)


# ── o canal ──────────────────────────────────────────────────────────────
class VoiceApi:
    def __init__(self, url: str, chave: str, *, voz: str = "", velocidade: float = 1.0, paciencia: str = "normal",
                 barge_in: bool = True,
                 termos: list[str] | None = None, aprendidos: dict[str, str] | None = None, projeto: str = "",
                 connect=None, http=None) -> None:
        url = (url or API_PADRAO).rstrip("/")
        if url.startswith(("ws://", "wss://")):
            raise ErroApi(f"o servidor próprio ({url}) foi descontinuado na 0.5.0; a voz usa a Voice API da Ermis: "
                          f"rode `ermis-voz config --servidor {API_PADRAO} --token SUA_CHAVE`", espera_s=60.0)
        if not chave:
            raise ErroApi(f"falta a chave de API: crie uma em {PLATAFORMA} (Tokens API) e rode "
                          "`ermis-voz config --token SUA_CHAVE`", espera_s=60.0)
        self.url = url
        self.chave = chave
        self.voz = voz
        self.velocidade = limitar_velocidade(velocidade)
        self.paciencia = paciencia if paciencia in SILENCIO_MS else "normal"
        self.barge_in = barge_in
        self.projeto = projeto
        self.corretor = Corretor(termos_projeto=list(termos or []), extras=dict(aprendidos or {}))
        self._connect = connect or websockets.connect
        self._http = http  # httpx.AsyncClient (testes); None: um por sessão
        self.ws = None
        self.sessao: str | None = None
        self.creditos: dict = {}
        self.parciais = False
        self.so_palavra = False  # modo comando: falar por cima não corta (o daemon corta quando ouve a palavra)
        self._para8k = Para8k()
        self._resto = b""
        self._ultimo_audio = 0.0
        self._lock = asyncio.Lock()
        self._locais: asyncio.Queue[dict] = asyncio.Queue()  # eventos gerados aqui (falas cortadas por nós)
        self._pendentes: dict[str, float | None] = {}  # falas enviadas e ainda não terminadas: id -> início
        self._ignorar_clear_ate = 0.0
        self._keepalive: asyncio.Task | None = None

    # ── sessão ──
    def _opcoes(self) -> dict:
        corpo = {
            "transport": "websocket",
            "audio_format": "pcm16_48k",
            "language": "pt-BR",
            "auto_decide": False,  # quem decide é o Claude
            "partial_transcripts": True,
            "turn_detection": "smart_turn",
            "vad": {"min_silence_ms": SILENCIO_MS[self.paciencia]},
            "barge_in": {"enabled": self.barge_in, "min_speech_ms": 300},
            "max_duration_s": DURACAO_MAX_S,
            "vocabulary": self._vocabulario(),
            # as frases de espera são do cliente (config.frases_preenchimento), e o Claude pode levar minutos
            "waiting": {"filler_after_ms": None, "patience_after_ms": None, "timeout_ms": None,
                        "gap_after_ms": None},
            "metadata": {"cliente": "ermis-voz", "versao": __version__, "projeto": self.projeto},
        }
        if self.voz:
            corpo["voice"] = self.voz
        if abs(self.velocidade - 1.0) > 1e-3:
            corpo["speech_speed"] = self.velocidade
        return corpo

    def _vocabulario(self) -> list[str]:
        termos = list(dict.fromkeys([*self.corretor.extras.values(), *self.corretor.termos_projeto]))
        return [t for t in termos if t.strip()][:MAX_VOCABULARIO]

    async def _criar_sessao(self) -> dict:
        import httpx

        headers = {"Authorization": f"Bearer {self.chave}"}
        http = self._http or httpx.AsyncClient(timeout=15.0)
        try:
            for tentativa in (1, 2):  # uma falha de rede passageira não derruba a voz por um backoff inteiro
                try:
                    resp = await http.post(f"{self.url}/v1/voice/sessions", json=self._opcoes(), headers=headers)
                    break
                except httpx.HTTPError as exc:
                    if tentativa == 2:
                        raise ErroApi(f"sem conexão com a Voice API ({self.url}): {_erro_rede(exc)}") from exc
                    await asyncio.sleep(0.5)
        finally:
            if self._http is None:
                await http.aclose()
        if resp.status_code == 400 and "speech_speed" in resp.text and "speech_speed" in self._opcoes():
            # uma Voice API anterior à velocidade da fala: a voz funciona, na velocidade normal
            log.warning("esta Voice API ainda não aceita velocidade da fala; seguindo na velocidade normal")
            self.velocidade = 1.0
            return await self._criar_sessao()
        if resp.status_code >= 300:
            raise erro_http(resp.status_code, resp.text)
        return resp.json()

    async def __aenter__(self) -> VoiceApi:
        dados = await self._criar_sessao()
        self.sessao = dados.get("session_id")
        url = dados.get("control_url") or f"{self.url.replace('http', 'ws', 1)}/v1/voice/sessions/{self.sessao}/control"
        try:
            self.ws = await self._connect(url, additional_headers={"Authorization": f"Bearer {self.chave}"},
                                          max_size=None, ping_interval=20)
        except websockets.InvalidStatus as exc:
            raise erro_http(exc.response.status_code, (exc.response.body or b"").decode("utf-8", "replace")) from exc
        self._ultimo_audio = time.monotonic()
        self._keepalive = asyncio.create_task(self._manter_viva())
        log.info("sessão %s na Voice API (%s)", self.sessao, self.url)
        return self

    async def __aexit__(self, *exc) -> None:
        await self.fechar()

    async def fechar(self) -> None:
        if self._keepalive is not None:
            self._keepalive.cancel()
        if self.ws is not None:
            with contextlib.suppress(Exception):
                await self.ws.close()

    async def _manter_viva(self) -> None:
        while True:
            await asyncio.sleep(1.0)
            if time.monotonic() - self._ultimo_audio > KEEPALIVE_S:
                await self._mandar_bytes(SILENCIO)

    # ── envio ──
    async def _mandar(self, msg: dict) -> None:
        async with self._lock:
            await self.ws.send(json.dumps(msg, ensure_ascii=False))

    async def _mandar_bytes(self, data: bytes) -> None:
        self._ultimo_audio = time.monotonic()
        with contextlib.suppress(Exception):  # caiu: o laço do daemon reconecta
            await self.ws.send(data)

    async def enviar_audio(self, pcm16k: bytes) -> None:
        """O microfone (PCM16 16 kHz, já sem eco) em quadros de 20 ms de μ-law 8 kHz."""
        dados = self._resto + mulaw(self._para8k(pcm16k))
        corte = len(dados) - len(dados) % QUADRO
        self._resto = dados[corte:]
        for i in range(0, corte, QUADRO):
            await self._mandar_bytes(dados[i:i + QUADRO])

    async def _cortar_pendentes(self) -> None:
        """Pedimos para parar: as falas em curso terminam aqui (a API não avisa de cada uma)."""
        if not self._pendentes:
            return
        self._ignorar_clear_ate = time.monotonic() + 2.0
        await self._mandar({"type": "interrupt"})
        for fid in list(self._pendentes):
            self._locais.put_nowait({"type": "audio_cortado", "id": fid})
        self._pendentes.clear()

    async def enviar(self, msg: dict) -> None:
        kind = msg.get("type")
        if kind == "falar":
            fid = str(msg.get("id"))
            if msg.get("interromper"):
                await self._cortar_pendentes()
            texto = preparar(str(msg.get("texto") or ""))[:MAX_SPEAK].strip()
            if not texto:
                self._locais.put_nowait({"type": "audio_cortado", "id": fid})
                return
            self._pendentes[fid] = None
            # no modo comando, falar por cima não corta (a conversa da sala); o "Pode falar." depois de "Ermis." sim:
            # o que é dito sobre uma fala sem barge-in a Voice API descarta, e ali vem o pedido
            pode_cortar = not self.so_palavra or msg.get("tipo") == "chamada"
            await self._mandar({"type": "speak", "id": fid, "text": texto,
                                "allow_barge_in": self.barge_in and pode_cortar})
        elif kind == "parar":
            await self._cortar_pendentes()
        elif kind == "tocado":
            await self._mandar({"type": "playback_finished", "id": str(msg.get("id"))})
        elif kind == "opcoes":
            if "parciais" in msg:
                self.parciais = bool(msg["parciais"])
            if "barge_in_palavra" in msg:
                self.so_palavra = bool(msg["barge_in_palavra"])
            if msg.get("paciencia") and msg["paciencia"] != self.paciencia:
                # a API fixa o silêncio de fim de turno na criação da sessão; vale na próxima
                log.info("paciência %s pedida; a sessão segue com %s", msg["paciencia"], self.paciencia)
        elif kind == "termos":
            self.corretor.set_projeto(list(msg.get("termos") or []))
            await self._mandar({"type": "set_vocabulary", "vocabulary": self._vocabulario()})
        elif kind == "aprendido":
            extras = {**self.corretor.extras, str(msg.get("ouvido")): str(msg.get("entendido"))}
            self.corretor.set_extras(extras)
            await self._mandar({"type": "set_vocabulary", "vocabulary": self._vocabulario()})
        elif kind == "fim":
            await self._mandar({"type": "end"})
        elif kind == "nota":
            log.debug("nota: %s", json.dumps(msg, ensure_ascii=False)[:500])

    # ── recepção ──
    def __aiter__(self):
        return self._eventos()

    async def _eventos(self):
        recebe = asyncio.ensure_future(self.ws.recv())
        local = asyncio.ensure_future(self._locais.get())
        try:
            while True:
                feitos, _ = await asyncio.wait({recebe, local}, return_when=asyncio.FIRST_COMPLETED)
                if local in feitos:
                    yield local.result()
                    local = asyncio.ensure_future(self._locais.get())
                if recebe in feitos:
                    try:
                        raw = recebe.result()
                    except websockets.ConnectionClosed as exc:
                        codigo = exc.rcvd.code if exc.rcvd else None
                        if codigo in _FECHAMENTOS:
                            raise erro_http(_FECHAMENTOS[codigo], exc.rcvd.reason or "") from exc
                        log.info("sessão %s fechada (%s): %s", self.sessao, codigo, exc)
                        return
                    recebe = asyncio.ensure_future(self.ws.recv())
                    if isinstance(raw, bytes):
                        yield raw
                        continue
                    for evento in await self._traduzir(json.loads(raw)):
                        yield evento
                    if self._acabou:
                        return
        finally:
            recebe.cancel()
            local.cancel()

    _acabou = False

    async def _traduzir(self, ev: dict) -> list[dict]:
        kind = ev.get("type")
        if kind == "session.started":
            return [{"type": "pronto", "sessao": ev.get("session_id")}]
        if kind == "speech.started":
            return [{"type": "falando"}]
        if kind == "transcript.partial":
            return [{"type": "parcial", "texto": ev.get("text") or ""}] if self.parciais else []
        if kind == "transcript":
            return [await self._transcricao(ev)]
        if kind == "transcript.revised":
            log.info("revisão da fala %s: %r -> %r", ev.get("utterance_id"), ev.get("previous"), ev.get("text"))
            return []
        if kind == "speak.started":
            fid = str(ev.get("id"))
            if fid in self._pendentes:
                self._pendentes[fid] = time.monotonic()
            return [{"type": "audio_inicio", "id": fid}]
        if kind == "audio.end":
            return [{"type": "audio_fim", "id": str(ev.get("id"))}]
        if kind == "speak.done":
            self._pendentes.pop(str(ev.get("id")), None)
            return []
        if kind == "clear":
            if time.monotonic() < self._ignorar_clear_ate:
                return []  # o eco do nosso interrupt: o daemon já apagou
            return [{"type": "limpar"}]
        if kind == "barge_in":
            fid = str(ev.get("id"))
            inicio = self._pendentes.get(fid)
            out = [{"type": "barge_in", "id": fid,
                    "tocado_ms": round((time.monotonic() - inicio) * 1000) if inicio else 0}]
            out += [{"type": "audio_cortado", "id": f} for f in self._pendentes if f != fid]
            self._pendentes.clear()
            return out
        if kind == "usage":
            self.creditos = {k: ev.get(k) for k in ("billed_seconds", "credits", "balance")}
            return []
        if kind == "warning":
            log.warning("Voice API: %s %s", ev.get("code"), ev.get("message") or "")
            return []
        if kind == "error":
            log.warning("Voice API: erro %s: %s", ev.get("code"), ev.get("message"))
            return [{"type": "erro", "mensagem": ev.get("message"), "codigo": ev.get("code")}]
        if kind == "session.ended":
            log.info("sessão %s encerrada: %s (%s s cobrados)", self.sessao, ev.get("reason"), ev.get("billed_seconds"))
            self._acabou = True
            return []
        return []

    async def _transcricao(self, ev: dict) -> dict:
        # o Claude responde quando quiser (minutos): a API volta a ouvir já, sem esperar o speak
        with contextlib.suppress(Exception):
            await self._mandar({"type": "done_processing"})
        cru = str(ev.get("text") or "").strip()
        avaliacao = ev.get("assessment") or {}
        if not cru or avaliacao.get("ignore"):
            return {"type": "ruido", "texto": cru}
        texto, correcoes = self.corretor.corrigir(cru)
        incerto = []
        if ev.get("uncertain") or avaliacao.get("confirm"):
            incerto.append("o reconhecimento ficou em dúvida")
        if avaliacao.get("ask_to_repeat"):
            incerto.append("houve fala, mas o áudio não deu para entender bem")
        return {
            "type": "fala",
            "id": ev.get("utterance_id"),
            "texto": texto,
            "cru": cru if cru != texto else None,
            "alternativas": [],
            "incerto": incerto,
            "correcoes": [*_correcoes_api(ev.get("corrections")), *(c.as_dict() for c in correcoes)],
            "latencia_ms": ev.get("latency_ms"),
        }


async def _get(url: str, chave: str, caminho: str) -> dict:
    import httpx

    try:
        async with httpx.AsyncClient(timeout=15.0) as http:
            resp = await http.get(f"{(url or API_PADRAO).rstrip('/')}{caminho}",
                                  headers={"Authorization": f"Bearer {chave}"})
    except httpx.HTTPError as exc:
        raise ErroApi(f"sem conexão com a Voice API ({url}): {_erro_rede(exc)}") from exc
    if resp.status_code >= 300:
        raise erro_http(resp.status_code, resp.text)
    return resp.json()


async def conferir_chave(url: str, chave: str) -> dict:
    """A chave vale? Devolve o saldo da conta (``available_credits``); levanta ErroApi se não."""
    if not chave:
        raise ErroApi("a chave está vazia")
    return await _get(url, chave, "/v1/account/balance")


async def vozes(url: str, chave: str) -> list[dict]:
    return list((await _get(url, chave, "/v1/voice/voices")).get("voices") or [])
