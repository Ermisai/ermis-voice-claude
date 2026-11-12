"""Segurar o espaço para falar: o painel avisa o aperto e a soltura; a fala vira um prompt."""

import time
from collections import deque

import pytest

from ermis_voz import daemon as daemon_mod
from ermis_voz.audio_local import Aec, Reproducao
from ermis_voz.config import Config
from ermis_voz.daemon import Daemon


class Audio:
    def __init__(self) -> None:
        self.reproducao = Reproducao()
        self.aec = Aec(False)
        self.mudo = True
        self.anel: deque = deque(maxlen=300)


class Canal:
    def __init__(self) -> None:
        self.enviadas: list[dict] = []
        self.audio: list[bytes] = []
        self.creditos = {}

    async def enviar(self, msg: dict) -> None:
        self.enviadas.append(msg)

    async def enviar_audio(self, pcm: bytes) -> None:
        self.audio.append(pcm)

    async def _mandar_bytes(self, data: bytes) -> None:
        self.audio.append(data)


@pytest.fixture
def d(tmp_path, monkeypatch):
    monkeypatch.setattr(daemon_mod, "HOME", tmp_path)
    monkeypatch.setattr(daemon_mod, "ESTADO_PATH", tmp_path / "estado.json")
    monkeypatch.setattr(daemon_mod, "modo", lambda: "espaco")
    monkeypatch.setattr(daemon_mod, "ESPACO_ESPERA_S", 0.3)
    cfg = Config()
    cfg.preenchimento = False
    dm = Daemon(cfg)
    dm.audio = Audio()
    dm.ws = Canal()
    dm.conectado.set()
    return dm


async def test_mudo_fora_do_aperto(d):
    assert d._mudo()
    await d.espaco_acao("segurar")
    assert not d.audio.mudo and d.espaco == "segurando"
    await d.espaco_acao("cancelar")
    assert d.audio.mudo and d.espaco is None


async def test_manda_o_comeco_guardado_antes_do_aperto(d):
    agora = time.time()
    d.audio.anel.extend([(agora - 2.0, b"velho"), (agora - 0.1, b"comeco")])
    await d.espaco_acao("segurar", t_ms=agora * 1000)
    assert d.ws.audio == [b"comeco"]


async def test_soltar_vira_prompt(d):
    import asyncio

    await d.espaco_acao("segurar")
    await d._mensagem({"type": "falando"})
    await d.espaco_acao("soltar")
    assert d.audio.mudo
    await asyncio.sleep(0.1)
    assert d.ws.audio  # o silêncio em tempo real que fecha o turno
    await d._mensagem({"type": "fala", "texto": "Roda os testes."})
    assert d.ultimo_comando["origem"] == "espaco"
    assert d.ultimo_comando["aperto"] is None  # sem "t" do painel
    assert d.ultimo_comando["bloco"] == "[fala] Roda os testes."
    assert d.espaco is None and not d.pendentes


async def test_duas_falas_no_mesmo_aperto(d):
    await d.espaco_acao("segurar")
    await d._mensagem({"type": "fala", "texto": "Abre o README."})
    await d._mensagem({"type": "falando"})
    await d.espaco_acao("soltar")
    await d._mensagem({"type": "fala", "texto": "E corrige o título."})
    assert d.ultimo_comando["texto"] == "Abre o README. E corrige o título."


async def test_turno_que_nao_fecha_usa_a_parcial(d):
    import asyncio

    await d.espaco_acao("segurar")
    await d._mensagem({"type": "falando"})
    await d._mensagem({"type": "parcial", "texto": "faz o commit"})
    await d.espaco_acao("soltar")
    await asyncio.sleep(0.5)
    assert d.ultimo_comando["texto"] == "faz o commit"
    # o turno que fecha depois não vira outra mensagem
    await d._mensagem({"type": "fala", "texto": "Faz o commit."})
    assert d.ultimo_comando["texto"] == "faz o commit" and not d.pendentes


async def test_toque_rapido_nao_manda_nada(d):
    await d.espaco_acao("segurar")
    await d.espaco_acao("cancelar")
    await d._mensagem({"type": "fala", "texto": "hum"})
    assert d.ultimo_comando is None and not d.pendentes


async def test_pergunta_do_claude_abre_o_microfone(d):
    import asyncio

    tarefa = asyncio.ensure_future(d.ouvir(5))
    await asyncio.sleep(0.01)
    assert not d.audio.mudo
    await d._mensagem({"type": "fala", "texto": "Sim."})
    assert (await tarefa)["texto"] == "Sim."
    assert d.audio.mudo
