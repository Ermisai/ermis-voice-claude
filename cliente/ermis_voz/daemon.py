"""O daemon: guarda o microfone, o alto-falante e a sessão com a Voice API da Ermis (voice_api.py); atende o MCP e os
hooks por um socket.

Um daemon por máquina, para todas as janelas do Claude Code. O que elas mandam falar entra numa fila: uma fala por
vez, a mais nova de cada sessão no lugar da que ela tinha na fila, e no máximo ``fila_max`` esperando (as mais
antigas saem). A fala nova de uma sessão corta a fala em curso da mesma sessão, nunca a de outra.

Socket local (``~/.ermis-voz/daemon.sock``), uma requisição JSON por linha, uma resposta JSON por linha:

    {"cmd": "conversar", "texto": "...", "esperar_resposta": true, "timeout": 120, "paciencia": "longa"}
    {"cmd": "falar", "texto": "...", "esperar_fim": false}
    {"cmd": "ler", "texto": "..."}          a resposta inteira (curta) ou resumida, em partes
    (falar, conversar e ler levam "origem": a sessão do Claude que pede, para a fila)
    {"cmd": "ouvir", "timeout": 60}
    {"cmd": "pendentes"}                    falas que ninguém esperava (para o hook PostToolUse)
    {"cmd": "parar"}                        para a fala do agente
    {"cmd": "status"}
    {"cmd": "nota", ...}                    vai para o log (nível debug)
    {"cmd": "aprendido", "ouvido", "entendido"}
    {"cmd": "projeto", "raiz": "/caminho"}  manda o léxico do projeto
    {"cmd": "espaco", "acao": "segurar", "t": ms}   segurar o espaço (o painel): grava desde ``t``
    {"cmd": "espaco", "acao": "soltar" | "cancelar"} soltou: a fala vira um prompt; cancelar: foi só um toque
    {"cmd": "sair"}
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import random
import time
import uuid
from collections import deque
from pathlib import Path

import websockets

from ermis_voz import __version__

from ermis_voz.config import (
    ATIVA_MS,
    ATIVA_PATH,
    ESTADO_PATH,
    HOME,
    SOCKET_PATH,
    Config,
    aprendidos,
    guardar_aprendido,
    modo,
)
from ermis_voz.lexico import termos_do_projeto
from ermis_voz.voice_api import SILENCIO, ErroApi, VoiceApi

log = logging.getLogger("ermis_voz.daemon")

FALANDO_MAX_S = 30.0  # "a pessoa está falando" sem a fala chegar: depois disso, de volta a ouvir
# segurar o espaço: depois de soltar, quanto esperar a Voice API fechar o turno (senão vale a transcrição parcial)
ESPACO_ESPERA_S = 4.0
ESPACO_ANTES_S = 0.3  # do microfone guardado, um pouco antes do aperto (a tecla chega depois do começo da fala)


class Fala:
    """Uma fala do agente em andamento (do ponto de vista do cliente)."""

    def __init__(self, fid: str, texto: str) -> None:
        self.id = fid
        self.texto = texto
        self.recebido_fim = False
        self.cortado = False
        self.descartada = False  # saiu da fila sem tocar (fila cheia, ou a mesma sessão pediu outra)
        self.barge_in: dict | None = None
        self.terminou = asyncio.Event()
        self.t0 = time.monotonic()
        self.espera = False  # frase de espera (não é o Claude falando)
        self.bloco: Bloco | None = None


class Bloco:
    """O que uma sessão do Claude pediu de uma vez: uma fala, ou as partes de uma leitura. A fila é de blocos."""

    def __init__(self, origem: str, textos: list[str], tipo: str = "falar") -> None:
        self.origem = origem
        self.tipo = tipo
        self.falas = [Fala(uuid.uuid4().hex[:8], t) for t in textos]
        for f in self.falas:
            f.bloco = self
        self.t0 = time.monotonic()

    @property
    def id(self) -> str:
        return self.falas[0].id

    @property
    def acabou(self) -> bool:
        return all(f.terminou.is_set() for f in self.falas)

    @property
    def barge_in(self) -> dict | None:
        return next((f.barge_in for f in self.falas if f.barge_in), None)

    @property
    def descartado(self) -> bool:
        return any(f.descartada for f in self.falas)

    def resumo(self) -> dict:
        return {"origem": self.origem, "tipo": self.tipo, "partes": len(self.falas),
                "texto": self.falas[0].texto[:80], "espera_s": round(time.monotonic() - self.t0, 1)}


class Daemon:
    def __init__(self, cfg: Config, audio_factory=None, projeto: str | None = None) -> None:
        self.cfg = cfg
        self.audio_factory = audio_factory
        self.projeto = projeto or os.getcwd()
        self.ws = None
        self.conectado = asyncio.Event()
        self.sessao: str | None = None
        self.audio = None
        self.falas: dict[str, Fala] = {}
        self.fala_atual: Fala | None = None
        self.pendentes: list[dict] = []
        self.esperando: list[asyncio.Future] = []
        self.ultima_fala: dict | None = None
        self.parcial = ""
        self.pessoa_falando = False
        self._stop = asyncio.Event()
        self._send_lock = asyncio.Lock()
        # frases de espera: armadas quando uma fala chega a quem esperava; o Claude falar (ou a pessoa) desarma
        self._espera: asyncio.Task | None = None
        self._ultima_espera = ""
        self._ultima_fala_espera: Fala | None = None  # a última espera/narração pedida (pode não ter começado)
        self.esperas_faladas = 0
        self.audio_ok = True
        # o que o painel mostra (estado.json)
        self.estado = "desligado"
        self.estado_desde = time.time()
        self.fala_agente = ""
        # modo comando
        self.ultimo_comando: dict | None = None  # o último pedido "Ermis, ..." (o painel o manda como prompt)
        self._comando_n = 0
        self._janela_comando_ate = 0.0
        self._modo_enviado: str | None = None
        # segurar o espaço (painel): None | "segurando" | "soltou"
        self.espaco: str | None = None
        self._espaco_t0 = 0.0  # time.time() do aperto
        self._espaco_aperto: float | None = None  # o "t" que o painel mandou: a fala volta marcada com ele
        self._espaco_falas: list[dict] = []
        self._espaco_tarefa: asyncio.Task | None = None
        self._espaco_ignorar_ate = 0.0  # depois de um toque (cancelar), a fala que fechar é descartada
        self._parciais_enviadas: bool | None = None
        # narração do que o Claude pensa e faz (lida da transcrição da sessão, cujo caminho os hooks passam)
        self._transcricao: str | None = None
        self._transcricao_pos: int | None = None
        self._transcricao_resto = b""
        self._narracao: tuple[float, str, str] | None = None  # (quando, tipo, texto): só a mais recente
        self._ultima_narracao_t = 0.0
        self._ultima_narracao = ""
        self.narracoes = 0
        # fila das falas de todas as sessões do Claude (uma por vez)
        self.bloco_atual: Bloco | None = None
        self.fila: deque[Bloco] = deque()
        self.descartadas = 0
        self.ultimo_erro = ""
        self._falando_desde = 0.0
        self._ultima_atividade = time.monotonic()

    # ── áudio ─────────────────────────────────────────────────────────────
    def _on_mic(self, pcm: bytes) -> None:
        ws = self.ws
        if ws is not None and self.conectado.is_set():
            asyncio.ensure_future(self._send_bytes(pcm))

    async def _send_bytes(self, data: bytes) -> None:
        try:
            await self.ws.enviar_audio(data)
        except Exception:  # noqa: BLE001 — reconecta no laço principal
            pass

    async def enviar(self, msg: dict) -> None:
        await self.conectado.wait()
        await self.ws.enviar(msg)

    # ── conexão ───────────────────────────────────────────────────────────
    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        if self.audio_factory is not None:
            self.audio = self.audio_factory(self._on_mic, loop)
        else:
            from ermis_voz.audio_local import Duplex

            self.audio = Duplex(self._on_mic, loop, aec=self.cfg.aec == "webrtc", entrada=self.cfg.entrada,
                                saida=self.cfg.saida)
        self.audio.mudo = self._mudo()  # na leitura nada sai do microfone, desde o começo
        self.audio.iniciar()
        server = await self._serve_socket()
        pulso = asyncio.create_task(self._pulso())
        narrador = asyncio.create_task(self._seguir_transcricao())
        vigia = asyncio.create_task(self._vigiar_audio())
        backoff = 1.0
        try:
            while not self._stop.is_set():
                espera = None
                try:
                    await self._conectar_e_ler()
                    backoff = 1.0
                except ErroApi as exc:
                    self.ultimo_erro = str(exc)
                    espera = exc.espera_s
                    log.warning("Voice API: %s", exc)
                except (OSError, websockets.WebSocketException) as exc:
                    self.ultimo_erro = f"Voice API indisponível ({exc})"
                    log.warning("Voice API indisponível (%s); tentando de novo em %.0f s", exc, backoff)
                self.conectado.clear()
                self.ws = None
                self._liberar_esperas()
                self._mudar("desconectado")
                if self._stop.is_set():
                    break
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(self._stop.wait(), espera or backoff)
                backoff = min(backoff * 2, 30.0)
        finally:
            pulso.cancel()
            narrador.cancel()
            vigia.cancel()
            self._desarmar_espera()
            server.close()
            self.audio.parar()
            self._mudar("desligado")
            with contextlib.suppress(OSError):
                SOCKET_PATH.unlink()

    def _canal(self, termos: list[str]) -> VoiceApi:
        return VoiceApi(self.cfg.servidor, self.cfg.token, voz=self.cfg.voz, paciencia=self.cfg.paciencia,
                        barge_in=self.cfg.barge_in, termos=termos, aprendidos=aprendidos(),
                        projeto=Path(self.projeto).name)

    async def _conectar_e_ler(self) -> None:
        termos = await asyncio.to_thread(termos_do_projeto, self.projeto)
        async with self._canal(termos) as canal:
            self.ws = canal
            self.sessao = canal.sessao
            self.ultimo_erro = ""
            self.conectado.set()
            self._modo_enviado = None
            await self._sincronizar_modo()
            self._mudar("ouvindo")
            if self.espaco == "segurando":
                await self._mandar_anel(self._espaco_t0)  # apertou antes de a sessão abrir
            async for message in canal:
                if isinstance(message, bytes):
                    if self.fala_atual is not None and not self.fala_atual.cortado:
                        self.audio.reproducao.adicionar_pcm48(message)
                    continue
                await self._mensagem(message)

    async def _mensagem(self, msg: dict) -> None:
        kind = msg.get("type")
        if kind == "pronto":
            self.sessao = msg.get("sessao")
            log.info("sessão %s", self.sessao)
        elif kind == "audio_inicio":
            fala = self.falas.get(msg.get("id")) or Fala(str(msg.get("id")), "")
            self.falas[fala.id] = fala
            self.fala_atual = fala
            self.fala_agente = fala.texto
            rep = self.audio.reproducao
            if rep.apagando:
                rep.limpar()  # o fim da fala cortada não pode comer o começo desta
            else:
                rep.restaurar()  # nunca começar abafada
            self._mudar("claude_falando")
        elif kind == "audio_fim":
            fala = self.falas.get(msg.get("id"))
            if fala:
                fala.recebido_fim = True
                asyncio.ensure_future(self._esperar_tocar(fala))
        elif kind == "barge_provavel":
            self.audio.reproducao.abaixar()  # parece a pessoa falando por cima: abre espaço sem cortar
        elif kind == "barge_cancelado":
            self.audio.reproducao.restaurar()
        elif kind in ("audio_cortado", "barge_in"):
            fala = self.falas.get(msg.get("id"))
            if fala is not None and fala.terminou.is_set():
                return  # já cortada aqui (a fila passou para outra): não apaga a seguinte
            if fala is None or fala is self.fala_atual or kind == "barge_in":
                self.audio.reproducao.apagar()  # some em ~150 ms, sem clique
            if fala:
                fala.cortado = True
                if kind == "barge_in":
                    fala.barge_in = msg
                fala.terminou.set()
                self._fala_acabou(fala)
        elif kind == "limpar":
            self.audio.reproducao.apagar()  # a pessoa falou por cima (o barge_in vem logo depois)
        elif kind == "ruido":
            # a fala virou ruído (tosse, porta): ninguém falou
            self.pessoa_falando = False
            self.parcial = ""
            self._mudar("ouvindo")
            self._talvez_proximo()
        elif kind == "falando":
            self.pessoa_falando = True
            self._falando_desde = time.monotonic()
            if self._janela_comando_ate and self._falando_desde < self._janela_comando_ate:
                # depois de "Ermis." ela começou o pedido dentro da janela: vale até a fala fechar (a Voice API leva
                # ~1 s para fechar o turno, e um pedido comprido passava da janela)
                self._janela_comando_ate = self._falando_desde + 120
            self._desarmar_espera()  # a pessoa voltou a falar: nada de "um momento" por cima
            self._mudar("pessoa_falando")
        elif kind == "parcial":
            self.parcial = msg.get("texto") or ""
            self._escrever_estado()
        elif kind == "fala":
            self._ultima_atividade = time.monotonic()
            self.pessoa_falando = False
            self.parcial = ""
            self.ultima_fala = msg
            esperando = [f for f in self.esperando if not f.done()]
            if not esperando and self.espaco is not None:
                self._espaco_falas.append(msg)  # segurando o espaço: vira um prompt quando ela soltar
                if self.espaco == "soltou":
                    self._espaco_emitir()
                else:
                    self._mudar("pessoa_falando")
            elif not esperando and time.monotonic() < self._espaco_ignorar_ate:
                self._mudar("ouvindo")  # foi só um toque no espaço
            elif esperando:
                # o Claude perguntou e espera a resposta: vale sem a palavra-chave, em qualquer modo
                for fut in esperando:
                    fut.set_result(msg)
                self.esperando = []
                self._mudar("claude_pensando")
                self._armar_espera()
            elif modo() == "comando":
                await self._talvez_comando(msg)
            else:
                self.pendentes = (self.pendentes + [msg])[-20:]
                self._mudar("ouvindo")
            self._talvez_proximo()  # a pessoa terminou de falar: a fila pode seguir
        elif kind == "erro":
            log.warning("Voice API: %s", msg)

    async def _esperar_tocar(self, fala: Fala) -> None:
        while self.audio.reproducao.pendente_ms > 0 and not fala.cortado:
            await asyncio.sleep(0.05)
        if not fala.cortado:
            with contextlib.suppress(Exception):
                await self.enviar({"type": "tocado", "id": fala.id, "ms": round((time.monotonic() - fala.t0) * 1000)})
        fala.terminou.set()
        self._fala_acabou(fala)
        if self.estado == "claude_falando" and self.fala_atual is fala:
            # uma frase de espera terminou: o Claude continua pensando; senão, de volta a ouvir
            self._mudar("claude_pensando" if fala.espera and self._espera is not None else "ouvindo")

    # ── fila das falas (todas as sessões do Claude) ───────────────────────
    def _fala_acabou(self, fala: Fala) -> None:
        bloco = fala.bloco
        if bloco is not None and bloco is self.bloco_atual and bloco.acabou:
            self.bloco_atual = None
            self._talvez_proximo()

    def _proximo_bloco(self) -> Bloco | None:
        """Tira da fila o próximo bloco, se nada está falando e a pessoa não está falando."""
        if self.bloco_atual is not None or not self.fila or self.pessoa_falando or not self.conectado.is_set():
            return None
        self.bloco_atual = self.fila.popleft()
        return self.bloco_atual

    def _talvez_proximo(self) -> None:
        bloco = self._proximo_bloco()
        if bloco is not None:
            asyncio.ensure_future(self._tocar(bloco))

    async def _tocar(self, bloco: Bloco) -> None:
        """Manda as partes do bloco à Voice API (que as fala em ordem)."""
        try:
            for fala in bloco.falas:
                if fala.terminou.is_set():
                    continue
                await self.enviar({"type": "falar", "id": fala.id, "texto": fala.texto, "interromper": False})
        except Exception as exc:  # noqa: BLE001 — caiu no meio: o laço de conexão libera as falas
            log.warning("fila: não consegui mandar %s (%s)", bloco.id, exc)

    def _descartar(self, bloco: Bloco, motivo: str) -> None:
        for fala in bloco.falas:
            if not fala.terminou.is_set():
                fala.descartada = True
                fala.terminou.set()
        self.descartadas += 1
        log.info("fila: descartado %s de %s (%s): %r", bloco.tipo, bloco.origem or "?", motivo,
                 bloco.falas[0].texto[:60])

    async def _cortar_bloco_atual(self, motivo: dict | None = None) -> None:
        """Corta o bloco em curso; ``motivo`` (o modo comando: a pessoa disse a palavra) conta como barge-in."""
        bloco = self.bloco_atual
        if bloco is None:
            return
        self.bloco_atual = None
        for fala in bloco.falas:
            if not fala.terminou.is_set():
                fala.cortado = True
                if motivo is not None and fala is self.fala_atual:
                    fala.barge_in = {**motivo, "id": fala.id,
                                     "tocado_ms": round((time.monotonic() - fala.t0) * 1000)}
                fala.terminou.set()
        self.audio.reproducao.apagar()
        with contextlib.suppress(Exception):
            await self.enviar({"type": "parar"})

    async def _agendar(self, bloco: Bloco, interromper: bool) -> None:
        """A regra da fila: a mesma sessão corta a própria fala; outra sessão espera a vez, só a mais nova de cada uma
        espera, e no máximo ``fila_max`` blocos esperam (sai o mais antigo)."""
        atual = self.bloco_atual
        if interromper:
            for velho in [b for b in self.fila if b.origem == bloco.origem]:
                self.fila.remove(velho)
                self._descartar(velho, "a mesma sessão pediu outra")
        if atual is not None and interromper and atual.origem == bloco.origem:
            await self._cortar_bloco_atual()
            atual = None
        self.fila.append(bloco)
        maximo = max(1, int(self.cfg.fila_max))
        while len(self.fila) > maximo:
            self._descartar(self.fila.popleft(), f"fila cheia ({maximo})")
        if atual is not None:
            log.info("fila: %s de %s espera (%d na fila)", bloco.tipo, bloco.origem or "?", len(self.fila))
        proximo = self._proximo_bloco()
        if proximo is not None:
            await self._tocar(proximo)

    # ── modo comando ("Ermis, ...") ───────────────────────────────────────
    async def _talvez_comando(self, msg: dict) -> None:
        from ermis_voz.chave import tirar_palavra
        from ermis_voz.formato import bloco_fala

        texto = msg.get("texto") or ""
        pedido = tirar_palavra(texto, self.cfg.variantes())
        if pedido is None and time.monotonic() < self._janela_comando_ate:
            pedido = texto  # logo depois de "Ermis.": a próxima fala é o pedido
        self._janela_comando_ate = 0.0
        if pedido is not None:
            # no modo comando a fala por cima não corta o agente (allow_barge_in falso): quem corta é a palavra
            await self._cortar_bloco_atual({"type": "barge_in", "palavra": True})
        if pedido is None:
            self._mudar("ouvindo")
            with contextlib.suppress(Exception):
                await self.enviar({"type": "nota", "kind": "ignorada_sem_palavra", "texto": texto})
            return
        if not pedido:  # só chamaram: "Ermis."
            self._janela_comando_ate = time.monotonic() + self.cfg.janela_comando_s
            await self._falar_espera("Pode falar.", "chamada")
            return
        fala = {**msg, "texto": pedido, "cru": msg.get("cru") or texto}
        self._comando_n += 1
        self.ultimo_comando = {"id": f"{os.getpid()}-{self._comando_n}", "t": round(time.time() * 1000),
                        "texto": pedido, "bloco": bloco_fala(fala)}
        with contextlib.suppress(Exception):
            await self.enviar({"type": "nota", "kind": "comando", "texto": pedido, "ouvido": texto})
        self._mudar("claude_pensando")
        self._armar_espera()

    async def _sincronizar_modo(self) -> None:
        """Leva o modo à Voice API e ao microfone:
        - comando: a fala por cima do agente só o corta se começar com a palavra-chave;
        - leitura: só ouvir as respostas; o microfone fica mudo (nada é transcrito nem gravado);
        - transcrição ao vivo só quando alguém a vê: uma janela em uso com o painel, e fora da leitura."""
        atual = modo()
        if self.audio is not None:
            self.audio.mudo = self._mudo()
        parciais = atual not in ("leitura", "desligado") and self._janela_em_uso()
        if (atual, parciais) == (self._modo_enviado, self._parciais_enviadas) or not self.conectado.is_set():
            return
        mudou_modo = atual != self._modo_enviado
        self._modo_enviado, self._parciais_enviadas = atual, parciais
        palavras = self.cfg.variantes() if atual == "comando" else []
        with contextlib.suppress(Exception):
            await self.enviar({"type": "opcoes", "barge_in_palavra": palavras, "parciais": parciais})
            if mudou_modo:
                await self.enviar({"type": "nota", "kind": "modo", "modo": atual})

    def _mudo(self) -> bool:
        """O microfone não vai para a Voice API: na leitura e desligado; no modo espaço, fora do aperto (e de uma
        pergunta do Claude pela ferramenta conversar)."""
        if self.espaco == "segurando":
            return False
        atual = modo()
        if atual == "espaco":
            return not any(not f.done() for f in self.esperando)
        return atual in ("leitura", "desligado")

    # ── segurar o espaço ("aperte para falar", pelo painel) ───────────────
    async def _mandar_anel(self, desde: float) -> None:
        """O microfone guardado desde ``desde`` (time.time()): o começo da fala, antes de o comando chegar."""
        anel = getattr(self.audio, "anel", None)
        if not anel or self.ws is None or not self.conectado.is_set():
            return
        n = 0
        for t, pcm in list(anel):
            if t >= desde - ESPACO_ANTES_S:
                await self._send_bytes(pcm)
                n += 1
        log.info("espaço: %d quadros guardados mandados (aperto há %.0f ms)", n, (time.time() - desde) * 1000)

    async def espaco_acao(self, acao: str, t_ms: float | None = None) -> dict:
        if acao == "segurar":
            self._ultima_atividade = time.monotonic()
            if self._espaco_tarefa is not None:
                self._espaco_tarefa.cancel()
                self._espaco_tarefa = None
            era_mudo = bool(self.audio and self.audio.mudo)
            log.info("espaço: segurar (aperto há %.0f ms, mudo=%s, conectado=%s)",
                     (time.time() - ((t_ms / 1000) if t_ms else time.time())) * 1000, era_mudo, self.conectado.is_set())
            self.espaco = "segurando"
            self._espaco_t0 = (t_ms / 1000) if t_ms else time.time()
            self._espaco_aperto = t_ms
            self._espaco_falas = []
            self._espaco_ignorar_ate = 0.0
            if self.bloco_atual is not None and self.conectado.is_set():
                await self._cortar_bloco_atual({"type": "barge_in", "espaco": True})  # ela vai falar: o Claude cala
            if era_mudo:
                await self._mandar_anel(self._espaco_t0)
            if self.audio is not None:
                self.audio.mudo = False
            await self._sincronizar_modo()
            self._mudar("pessoa_falando")
            return {"ok": True, "conectado": self.conectado.is_set()}
        if acao == "soltar":
            if self.espaco != "segurando":
                return {"ok": True, "ignorado": True}
            self.espaco = "soltou"
            log.info("espaço: soltou")
            if self.audio is not None:
                self.audio.mudo = self._mudo()
            self._espaco_tarefa = asyncio.ensure_future(self._espaco_esperar())
            return {"ok": True}
        if acao == "cancelar":
            if self._espaco_tarefa is not None:
                self._espaco_tarefa.cancel()
                self._espaco_tarefa = None
            self.espaco = None
            self._espaco_falas = []
            self._espaco_ignorar_ate = time.monotonic() + 3.0
            if self.audio is not None:
                self.audio.mudo = self._mudo()
            self.parcial = ""
            self._mudar("ouvindo")
            return {"ok": True}
        return {"ok": False, "erro": f"ação desconhecida: {acao}"}

    async def _espaco_esperar(self) -> None:
        """Soltou: espera a Voice API fechar o turno; se não fechar a tempo, vale o que já estava transcrito. Com o
        microfone mudo, manda silêncio em tempo real: o fim de turno conta o tempo pelo áudio que chega (só o
        keepalive, um quadro a cada 2 s, levava segundos para fechar)."""
        try:
            fim = time.monotonic() + ESPACO_ESPERA_S
            while time.monotonic() < fim:
                if self._espaco_falas and not self.pessoa_falando:
                    break
                if self.audio is not None and self.audio.mudo and self.ws is not None and self.conectado.is_set():
                    await self.ws._mandar_bytes(SILENCIO)
                await asyncio.sleep(0.02)
            if self.espaco != "soltou":
                return
            if self.pessoa_falando and self.parcial.strip():
                self._espaco_falas.append({"type": "fala", "texto": self.parcial.strip(),
                                           "incerto": ["transcrição parcial: o turno não fechou a tempo"]})
            self._espaco_emitir()
        except asyncio.CancelledError:
            pass

    def _espaco_emitir(self) -> None:
        from ermis_voz.formato import bloco_fala

        falas = [f for f in self._espaco_falas if (f.get("texto") or "").strip()]
        self.espaco = None
        self._espaco_falas = []
        if self._espaco_tarefa is not None and self._espaco_tarefa is not asyncio.current_task():
            self._espaco_tarefa.cancel()
        self._espaco_tarefa = None
        # a fala do turno que ainda fechar depois disto (o fim do que já foi usado como parcial) é descartada
        self._espaco_ignorar_ate = time.monotonic() + 3.0
        self.pessoa_falando = False
        self.parcial = ""
        if self.audio is not None:
            self.audio.mudo = self._mudo()
        if not falas:
            self._mudar("ouvindo")
            return
        texto = " ".join(f["texto"].strip() for f in falas)
        self._comando_n += 1
        self.ultimo_comando = {"id": f"{os.getpid()}-{self._comando_n}", "t": round(time.time() * 1000),
                               "texto": texto, "bloco": "\n\n".join(bloco_fala(f) for f in falas),
                               "origem": "espaco", "aperto": self._espaco_aperto}
        self.ultima_fala = {"texto": texto}
        log.info("espaço: virou prompt (%d caracteres)", len(texto))
        asyncio.ensure_future(self._nota_espaco(texto))
        self._mudar("ouvindo")  # nenhum hook avisa quando o Claude acaba neste modo: o painel não fica "pensando"

    async def _nota_espaco(self, texto: str) -> None:
        with contextlib.suppress(Exception):
            await self.enviar({"type": "nota", "kind": "espaco", "texto": texto})

    def _janela_em_uso(self) -> bool:
        try:
            marca = json.loads(ATIVA_PATH.read_text(encoding="utf-8"))
            return time.time() * 1000 - float(marca.get("t", 0)) < ATIVA_MS
        except (OSError, ValueError, AttributeError):
            return False

    # ── frases de espera ──────────────────────────────────────────────────
    def _armar_espera(self) -> None:
        self._desarmar_espera()
        if self.cfg.preenchimento and self.cfg.frases_preenchimento:
            self._espera = asyncio.create_task(self._esperar_claude())

    def _desarmar_espera(self) -> None:
        if self._espera is not None and not self._espera.done() and self._espera is not asyncio.current_task():
            self._espera.cancel()
        self._espera = None

    def _escolher(self, frases: list[str]) -> str:
        opcoes = [f for f in frases if f != self._ultima_espera] or frases
        self._ultima_espera = random.choice(opcoes)
        return self._ultima_espera

    async def _esperar_claude(self) -> None:
        """Depois de uma fala entregue ao Claude: se ele não falar a tempo, uma frase de espera; bem depois, uma de
        paciência. Só uma de cada por fala."""
        try:
            await asyncio.sleep(self.cfg.preenchimento_ms / 1000)
            await self._falar_espera(self._escolher(self.cfg.frases_preenchimento), "preenchimento")
            if self.cfg.paciencia_ms and self.cfg.frases_paciencia:
                await asyncio.sleep(max(0, self.cfg.paciencia_ms - self.cfg.preenchimento_ms) / 1000)
                await self._falar_espera(self._escolher(self.cfg.frases_paciencia), "paciencia")
        except asyncio.CancelledError:
            pass

    async def _falar_espera(self, texto: str, tipo: str) -> None:
        if self.bloco_atual is not None or self.fila:
            return  # alguma sessão está falando ou esperando a vez: um "um momento" por cima só atrapalha
        fala = Fala(uuid.uuid4().hex[:8], texto)
        fala.espera = True
        self.falas[fala.id] = fala
        self._ultima_fala_espera = fala
        self.esperas_faladas += 1
        await self.enviar({"type": "falar", "id": fala.id, "texto": texto, "interromper": True, "tipo": tipo})

    # ── estado para o painel ──────────────────────────────────────────────
    def _mudar(self, estado: str) -> None:
        if estado != self.estado:
            self.estado = estado
            self.estado_desde = time.time()
        self._escrever_estado()

    def _escrever_estado(self) -> None:
        dados = {
            "versao": 1,
            "t": round(time.time() * 1000),
            "pid": os.getpid(),
            "estado": self.estado,  # ouvindo | pessoa_falando | claude_pensando | claude_falando | desconectado | desligado
            "desde": round(self.estado_desde * 1000),
            "parcial": self.parcial if self.estado == "pessoa_falando" else "",
            "ultima_fala": (self.ultima_fala or {}).get("texto") or "",
            "fala_agente": self.fala_agente if self.estado == "claude_falando" else "",
            "pendentes": len(self.pendentes),
            "fila": len(self.fila),
            "modo": modo(),
            "aec": bool(self.audio and self.audio.aec.ativo),
            "servidor": self.cfg.servidor,
            "projeto": self.projeto,
            "comando": self.ultimo_comando,  # {id, t, texto, bloco}: o painel manda como prompt uma vez
            "palavra": self.cfg.palavra_chave or "Ermis",
            "audio_ok": self.audio_ok,
            "espaco": self.espaco,  # segurando | soltou | None
        }
        try:
            HOME.mkdir(parents=True, exist_ok=True)
            tmp = ESTADO_PATH.with_suffix(".tmp")
            tmp.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, ESTADO_PATH)
        except OSError:
            pass

    async def _pulso(self) -> None:
        """Reescreve o estado a cada 2 s: o painel sabe que o daemon está vivo (e esconde a faixa se ele morrer)."""
        while True:
            await asyncio.sleep(2)
            if self._ocioso():
                # a sessão da Voice API é cobrada por segundo: sem uso no modo ferramenta, encerra (o MCP sobe o
                # daemon de novo na próxima chamada de voz)
                log.info("sem uso há %.0f s no modo %s: encerrando a sessão", self.cfg.ocioso_s, modo())
                await self.comando({"cmd": "sair"})
                return
            if self.pessoa_falando and time.monotonic() - self._falando_desde > FALANDO_MAX_S:
                # a Voice API avisou que ela começou a falar e a transcrição nunca veio: não segura a fila, a
                # narração e as frases de espera para sempre
                log.info("a fala começada há %.0f s não chegou; de volta a ouvir", FALANDO_MAX_S)
                self.pessoa_falando = False
                self.parcial = ""
                self._mudar("ouvindo")
                self._talvez_proximo()
            await self._sincronizar_modo()
            self._escrever_estado()

    def _ocioso(self) -> bool:
        if not self.cfg.ocioso_s or modo() not in ("ferramenta", "desligado", "espaco"):
            return False  # mãos livres, comando e leitura: a pessoa conta com a voz ligada
        if self.esperando or self.bloco_atual is not None or self.fila or self.pessoa_falando or self.espaco:
            return False
        return time.monotonic() - self._ultima_atividade > self.cfg.ocioso_s

    # ── narração do pensamento ────────────────────────────────────────────
    def _seguir(self, caminho) -> None:
        """Passa a acompanhar esta transcrição, a partir do fim (só o que vier daqui em diante é narrado)."""
        if caminho and caminho != self._transcricao:
            self._transcricao = str(caminho)
            self._transcricao_pos = None
            self._transcricao_resto = b""

    async def _seguir_transcricao(self) -> None:
        from ermis_voz.pensamento import candidatos

        while True:
            await asyncio.sleep(0.3)
            caminho = self._transcricao
            if not caminho or not (self.cfg.falar_pensamento or self.cfg.falar_progresso):
                continue
            try:
                tamanho = os.path.getsize(caminho)
                if self._transcricao_pos is None or tamanho < self._transcricao_pos:
                    self._transcricao_pos = tamanho  # começa do fim
                    continue
                if tamanho > self._transcricao_pos:
                    with open(caminho, "rb") as f:
                        f.seek(self._transcricao_pos)
                        novo = f.read(min(tamanho - self._transcricao_pos, 4 * 2**20))
                    self._transcricao_pos += len(novo)
                    dados = self._transcricao_resto + novo
                    *linhas, self._transcricao_resto = dados.split(b"\n")
                    for linha in linhas:
                        for tipo, texto in candidatos(linha.decode("utf-8", "replace"), self.cfg.falar_pensamento,
                                                      self.cfg.falar_progresso):
                            self._narracao = (time.monotonic(), tipo, texto)
            except OSError:
                continue
            await self._talvez_narrar()

    async def _talvez_narrar(self) -> None:
        """Fala a narração mais recente, se ninguém está falando e já passou o intervalo; velha demais, descarta."""
        from ermis_voz.pensamento import em_ingles, primeira_frase

        if self._narracao is None or not self.conectado.is_set() or modo() == "desligado":
            return
        if modo() == "leitura" and not self.cfg.pensamento_na_leitura:
            self._narracao = None
            return
        quando, tipo, texto = self._narracao
        agora = time.monotonic()
        if agora - quando > 10:
            self._narracao = None  # o Claude já está em outra
            return
        if (
            self.pessoa_falando
            or self.audio.reproducao.pendente_ms > 0
            or self.bloco_atual is not None
            or self.fila
            or self.esperando  # o Claude está esperando a pessoa, não pensando
            or agora - self._ultima_narracao_t < self.cfg.pensamento_intervalo_s
        ):
            return
        self._narracao = None
        if em_ingles(texto):
            return  # o TTS fala português: um pensamento em inglês sairia ininteligível
        frase = primeira_frase(texto, self.cfg.pensamento_max_chars)
        if len(frase) < 8 or frase == self._ultima_narracao:
            return
        self._desarmar_espera()  # já está dizendo o que faz: dispensa o "um momento"
        self._ultima_narracao_t, self._ultima_narracao = agora, frase
        self.narracoes += 1
        await self._falar_espera(frase, tipo)

    # ── vigia do áudio ────────────────────────────────────────────────────
    async def _vigiar_audio(self) -> None:
        """O stream de áudio parou (fone que conectou ou desconectou, saída trocada, erro no callback) ou o dispositivo
        padrão mudou: reabre. Sem isso o daemon segue conectado, mas mudo e surdo (04/11, quase 2 horas sem som)."""
        espera = 2.0
        while True:
            await asyncio.sleep(espera)
            audio = self.audio
            if audio is None or not hasattr(audio, "vivo"):
                continue
            morto = not audio.vivo()
            mudou = not morto and audio.padrao_mudou()
            self.audio_ok = not morto
            if not (morto or mudou):
                espera = 2.0
                continue
            motivo = "o stream parou" if morto else "o dispositivo padrão mudou"
            log.warning("áudio: %s; reabrindo", motivo)
            try:
                await asyncio.to_thread(audio.reabrir)
                self.audio_ok = True
                espera = 2.0
                with contextlib.suppress(Exception):
                    await self.enviar({"type": "nota", "kind": "audio_reaberto", "motivo": motivo,
                                       "dispositivos": list(getattr(audio, "dispositivos", ()))})
            except Exception as exc:  # noqa: BLE001 — sem dispositivo agora: tenta de novo, mais devagar
                log.warning("áudio: não reabriu (%s)", exc)
                self.audio_ok = False
                espera = min(espera * 2, 15.0)
            self._escrever_estado()

    def _liberar_esperas(self) -> None:
        for fut in self.esperando:
            if not fut.done():
                fut.set_result(None)
        self.esperando = []
        # a sessão caiu: o que estava na fila não toca depois, fora de hora
        while self.fila:
            self._descartar(self.fila.popleft(), "sem conexão")
        for fala in self.falas.values():
            fala.terminou.set()
        self.falas = {}
        self.bloco_atual = None
        # a pessoa falava quando caiu: o fim dessa fala nunca vai chegar (senão a fila e a narração ficam presas)
        self.pessoa_falando = False
        self.parcial = ""

    # ── comandos ──────────────────────────────────────────────────────────
    async def falar(self, texto: str, esperar_fim: bool = False, interromper: bool = True,
                    so_cortar: bool = False, origem: str = "", partes: list[str] | None = None,
                    tipo: str = "falar") -> Bloco | None:
        self._desarmar_espera()  # o Claude respondeu
        self._narracao = None
        atual = self.fala_atual
        pendente = self._ultima_fala_espera
        if (atual is not None and atual.espera and not atual.terminou.is_set()) or (
            pendente is not None and not pendente.terminou.is_set()
        ):
            # uma frase de espera ou uma narração está tocando, ou foi pedida e ainda não começou: a resposta de
            # verdade passa na frente
            self.audio.reproducao.apagar()
            if pendente is not None:
                pendente.cortado = True
                pendente.terminou.set()
            with contextlib.suppress(Exception):
                await self.enviar({"type": "parar"})
        if so_cortar:
            return None
        bloco = Bloco(origem, list(partes) if partes else [texto], tipo)
        for fala in bloco.falas:
            self.falas[fala.id] = fala
        await self._agendar(bloco, interromper)
        if esperar_fim:
            # espera a vez na fila e o fim desta fala (tocada, cortada ou descartada)
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(asyncio.gather(*(f.terminou.wait() for f in bloco.falas)), 900)
        return bloco

    async def _ler(self, bloco_id: str, texto: str, origem: str) -> None:
        """Uma resposta inteira do Claude: lida inteira (curta) ou resumida, em partes, até o teto."""
        from ermis_voz import leitura
        from ermis_voz.pronuncia import preparar

        try:
            lei = await leitura.preparar(texto, preparar, inteiro_ate_s=self.cfg.leitura_inteiro_ate_s,
                                         max_s=self.cfg.leitura_max_s, resumo_s=self.cfg.leitura_resumo_s)
        except Exception:  # noqa: BLE001
            log.exception("leitura falhou")
            return
        log.info("leitura %s de %s: %s, %s partes, %.0f s", bloco_id, origem or "?", lei.info.get("modo"),
                 lei.info.get("partes"), lei.info.get("falado_s") or 0)
        if lei.partes:
            await self.falar("", interromper=True, origem=origem, partes=lei.partes, tipo="ler")

    async def ouvir(self, timeout: float) -> dict | None:
        if self.pendentes:
            return self.pendentes.pop(0)
        fut = asyncio.get_running_loop().create_future()
        self.esperando.append(fut)
        if self.audio is not None:
            self.audio.mudo = self._mudo()  # no modo espaço, o microfone abre para a resposta à pergunta do Claude
        try:
            return await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            # alguém começou a falar perto do fim: espera a fala terminar
            if self.pessoa_falando:
                with contextlib.suppress(asyncio.TimeoutError):
                    return await asyncio.wait_for(fut, 60)
            return None
        finally:
            if fut in self.esperando:
                self.esperando.remove(fut)
            if self.audio is not None:
                self.audio.mudo = self._mudo()

    async def conversar(self, texto: str, esperar_resposta: bool, timeout: float, paciencia: str | None,
                        origem: str = "") -> dict:
        antes = list(self.pendentes) if texto else []
        if texto:
            self.pendentes = []
        if paciencia:
            await self.enviar({"type": "opcoes", "paciencia": paciencia})
        out: dict = {"antes": antes}
        if texto:
            bloco = await self.falar(texto, esperar_fim=True, origem=origem)
            out["interrompido"] = bloco.barge_in
            if bloco.descartado:
                out["descartado"] = True  # a fila estava cheia: a pessoa não ouviu
        if esperar_resposta:
            out["fala"] = await self.ouvir(timeout)
            out["timeout_s"] = timeout
        if paciencia and paciencia != self.cfg.paciencia:
            await self.enviar({"type": "opcoes", "paciencia": self.cfg.paciencia})
        return out

    async def comando(self, req: dict) -> dict:
        cmd = req.get("cmd")
        if cmd in ("conversar", "falar", "ouvir", "ler", "pendentes", "teste_dizer"):
            self._ultima_atividade = time.monotonic()
        if cmd == "status":
            return {
                "ok": True, "conectado": self.conectado.is_set(), "sessao": self.sessao, "servidor": self.cfg.servidor,
                "erro": self.ultimo_erro or None,
                "creditos": getattr(self.ws, "creditos", None) or None,
                "falando": self.bloco_atual.resumo() if self.bloco_atual else None,
                "fila": [b.resumo() for b in self.fila], "fila_max": self.cfg.fila_max,
                "descartadas": self.descartadas,
                "aec": self.audio.aec.ativo if self.audio else None, "modo": modo(),
                "pendentes": len(self.pendentes), "pessoa_falando": self.pessoa_falando, "parcial": self.parcial,
                "estado": self.estado, "preenchimento": self.cfg.preenchimento, "esperas_faladas": self.esperas_faladas,
                "projeto": self.projeto, "palavra": self.cfg.palavra_chave,
                "falar_pensamento": self.cfg.falar_pensamento, "falar_progresso": self.cfg.falar_progresso,
                "narracoes": self.narracoes, "transcricao": self._transcricao,
                "audio": {"ok": self.audio_ok, "dispositivos": list(getattr(self.audio, "dispositivos", ())),
                          "reaberturas": getattr(self.audio, "reaberturas", 0),
                          "erros": getattr(self.audio, "erros_callback", 0),
                          "ultimo_erro": getattr(self.audio, "ultimo_erro", "")},
                "versao": __version__,
            }
        if cmd == "sair":
            self._stop.set()
            if self.ws is not None:
                with contextlib.suppress(Exception):
                    await self.ws.enviar({"type": "fim"})  # encerra a sessão: a cobrança para aqui
                    await self.ws.fechar()
            return {"ok": True}
        if cmd == "recarregar":
            # a configuração mudou: vale já, sem reiniciar. Antes da checagem de conexão: é desconectado (servidor ou
            # token errados) que a pessoa mais precisa corrigir a configuração
            # a voz e a paciência são fixadas na criação da sessão: mudar qualquer um destes abre outra
            antigo = (self.cfg.servidor, self.cfg.token, self.cfg.voz, self.cfg.paciencia)
            self.cfg = Config.load()
            reconecta = (self.cfg.servidor, self.cfg.token, self.cfg.voz, self.cfg.paciencia) != antigo
            if reconecta and self.ws is not None:
                with contextlib.suppress(Exception):
                    await self.ws.enviar({"type": "fim"})
                    await self.ws.fechar()  # o laço de conexão abre outra sessão com o endereço e a chave novos
            self._modo_enviado = None
            await self._sincronizar_modo()
            self._escrever_estado()
            return {"ok": True, "reconectando": reconecta, "palavra": self.cfg.palavra_chave,
                    "falar_pensamento": self.cfg.falar_pensamento, "falar_progresso": self.cfg.falar_progresso}
        if cmd == "espaco":
            # antes da checagem de conexão: segurar enquanto a sessão abre grava no anel e manda quando abrir
            return await self.espaco_acao(str(req.get("acao") or ""), req.get("t"))
        if not self.conectado.is_set():
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self.conectado.wait(), 5)
            if not self.conectado.is_set():
                motivo = self.ultimo_erro or f"sem conexão com a Voice API ({self.cfg.servidor})"
                return {"ok": False, "erro": motivo}
        origem = str(req.get("origem") or "")
        if cmd == "conversar":
            res = await self.conversar(str(req.get("texto") or ""), bool(req.get("esperar_resposta", True)),
                                       float(req.get("timeout") or self.cfg.escuta_s), req.get("paciencia") or None,
                                       origem=origem)
            return {"ok": True, **res}
        if cmd == "falar":
            bloco = await self.falar(str(req.get("texto") or ""), bool(req.get("esperar_fim", False)),
                                     bool(req.get("interromper", True)), origem=origem)
            return {"ok": True, "id": bloco.id, "interrompido": bloco.barge_in, "descartado": bloco.descartado,
                    "na_fila": len(self.fila)}
        if cmd == "ouvir":
            return {"ok": True, "fala": await self.ouvir(float(req.get("timeout") or 60))}
        if cmd == "ler":
            # uma resposta inteira do Claude: lida inteira (curta) ou resumida (leitura.py), em partes, até o teto
            texto = str(req.get("texto") or "").strip()
            if not texto:
                return {"ok": True, "vazio": True}
            await self.falar("", interromper=True, so_cortar=True)  # corta espera/narração em curso
            lid = uuid.uuid4().hex[:8]
            asyncio.ensure_future(self._ler(lid, texto, origem))  # o resumo pode levar uns segundos
            return {"ok": True, "id": lid}
        if cmd == "pendentes":
            self._seguir(req.get("transcricao"))
            out, self.pendentes = self.pendentes, []
            return {"ok": True, "falas": out, "pessoa_falando": self.pessoa_falando}
        if cmd == "transcricao":
            self._seguir(req.get("caminho"))
            return {"ok": True}
        if cmd == "parar":
            # a pessoa pediu silêncio: a fala em curso e toda a fila
            self._desarmar_espera()
            while self.fila:
                self._descartar(self.fila.popleft(), "parar")
            await self._cortar_bloco_atual()
            self.audio.reproducao.apagar()
            await self.enviar({"type": "parar"})
            return {"ok": True}
        if cmd == "nota":
            await self.enviar({"type": "nota", **{k: v for k, v in req.items() if k != "cmd"}})
            return {"ok": True}
        if cmd == "aprendido":
            ouvido, entendido = str(req.get("ouvido") or ""), str(req.get("entendido") or "")
            if ouvido and entendido:
                guardar_aprendido(ouvido, entendido)
                await self.enviar({"type": "aprendido", "ouvido": ouvido, "entendido": entendido})
            return {"ok": True}
        if cmd == "projeto":
            self.projeto = str(req.get("raiz") or self.projeto)
            termos = await asyncio.to_thread(termos_do_projeto, self.projeto)
            await self.enviar({"type": "termos", "termos": termos})
            await self.enviar({"type": "nota", "kind": "projeto", "raiz": self.projeto, "termos": len(termos)})
            return {"ok": True, "termos": len(termos)}
        if cmd == "teste_dizer" and hasattr(self.audio, "dizer"):  # só com o áudio de arquivo (testes)
            from pathlib import Path as _P

            return {"ok": True, "segundos": self.audio.dizer(_P(str(req.get("wav"))))}
        return {"ok": False, "erro": f"comando desconhecido: {cmd}"}

    # ── socket local ──────────────────────────────────────────────────────
    async def _serve_socket(self):
        HOME.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(OSError):
            SOCKET_PATH.unlink()

        async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                while line := await reader.readline():
                    try:
                        req = json.loads(line)
                        res = await self.comando(req)
                    except Exception as exc:  # noqa: BLE001
                        log.exception("comando falhou")
                        res = {"ok": False, "erro": str(exc)}
                    writer.write((json.dumps(res, ensure_ascii=False) + "\n").encode())
                    await writer.drain()
            finally:
                writer.close()

        server = await asyncio.start_unix_server(handle, path=str(SOCKET_PATH), limit=2**20)
        os.chmod(SOCKET_PATH, 0o600)
        return server


async def pedir(req: dict, timeout: float = 600.0) -> dict:
    """Manda um comando ao daemon (para o MCP, os hooks e a linha de comando)."""
    reader, writer = await asyncio.wait_for(asyncio.open_unix_connection(str(SOCKET_PATH), limit=2**20), 3)
    try:
        writer.write((json.dumps(req, ensure_ascii=False) + "\n").encode())
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout)
        return json.loads(line) if line else {"ok": False, "erro": "daemon fechou a conexão"}
    finally:
        writer.close()


def rodando() -> bool:
    import socket

    if not SOCKET_PATH.exists():
        return False
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.settimeout(1)
        s.connect(str(SOCKET_PATH))
        return True
    except OSError:
        return False
    finally:
        s.close()
