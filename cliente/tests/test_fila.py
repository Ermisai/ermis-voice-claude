"""A fila de falas do daemon: várias janelas do Claude falando ao mesmo tempo."""

import asyncio

import pytest

from ermis_voz import daemon as daemon_mod
from ermis_voz.audio_local import Aec, Reproducao
from ermis_voz.config import Config
from ermis_voz.daemon import Daemon


class Audio:
    def __init__(self) -> None:
        self.reproducao = Reproducao()
        self.aec = Aec(False)
        self.mudo = False


class Canal:
    """No lugar da Voice API: guarda o que o daemon mandou."""

    def __init__(self) -> None:
        self.enviadas: list[dict] = []
        self.creditos = {}

    async def enviar(self, msg: dict) -> None:
        self.enviadas.append(msg)

    async def enviar_audio(self, pcm: bytes) -> None:
        pass

    def faladas(self) -> list[str]:
        return [m["texto"] for m in self.enviadas if m["type"] == "falar"]


@pytest.fixture
def d(tmp_path, monkeypatch):
    monkeypatch.setattr(daemon_mod, "HOME", tmp_path)
    monkeypatch.setattr(daemon_mod, "ESTADO_PATH", tmp_path / "estado.json")
    monkeypatch.setattr(daemon_mod, "modo", lambda: "leitura")
    cfg = Config()
    cfg.preenchimento = False
    cfg.fila_max = 2
    dm = Daemon(cfg)
    dm.audio = Audio()
    dm.ws = Canal()
    dm.conectado.set()
    return dm


async def tocar_ate_o_fim(d: Daemon, bloco) -> None:
    for fala in bloco.falas:
        await d._mensagem({"type": "audio_inicio", "id": fala.id})
        await d._mensagem({"type": "audio_fim", "id": fala.id})
    await asyncio.sleep(0.15)


async def test_outra_janela_espera_a_vez(d):
    a = await d.falar("Janela A terminou os testes.", origem="A")
    b = await d.falar("Janela B fez o deploy.", origem="B")
    assert d.ws.faladas() == ["Janela A terminou os testes."]  # B não corta A
    assert [x.origem for x in d.fila] == ["B"]
    await tocar_ate_o_fim(d, a)
    assert d.ws.faladas() == ["Janela A terminou os testes.", "Janela B fez o deploy."]
    assert d.bloco_atual is b and not d.fila
    assert not any(m["type"] == "parar" for m in d.ws.enviadas)


async def test_a_mesma_janela_corta_a_propria_fala(d):
    a1 = await d.falar("Primeira.", origem="A")
    await d.falar("Segunda, mais nova.", origem="A")
    assert a1.falas[0].cortado
    assert [m["type"] for m in d.ws.enviadas] == ["falar", "parar", "falar"]
    assert d.ws.faladas() == ["Primeira.", "Segunda, mais nova."]


async def test_so_a_mais_nova_de_cada_janela_espera(d):
    await d.falar("A falando.", origem="A")
    b1 = await d.falar("B, versão velha.", origem="B")
    await d.falar("B, versão nova.", origem="B")
    assert b1.descartado
    assert [x.falas[0].texto for x in d.fila] == ["B, versão nova."]


async def test_fila_cheia_descarta_a_mais_antiga(d):
    await d.falar("A falando.", origem="A")
    b = await d.falar("B.", origem="B")
    c = await d.falar("C.", origem="C")
    e = await d.falar("E.", origem="E")  # fila_max = 2
    assert b.descartado and not c.descartado and not e.descartado
    assert [x.origem for x in d.fila] == ["C", "E"]
    assert d.descartadas == 1
    status = await d.comando({"cmd": "status"})
    assert [x["origem"] for x in status["fila"]] == ["C", "E"] and status["fila_max"] == 2


async def test_conversar_descartado_avisa_o_claude(d):
    await d.falar("A falando.", origem="A")
    d.cfg.fila_max = 1
    tarefa = asyncio.ensure_future(d.conversar("B pergunta.", False, 5, None, origem="B"))
    await asyncio.sleep(0.05)
    await d.falar("C.", origem="C")  # empurra B para fora
    res = await asyncio.wait_for(tarefa, 2)
    assert res["descartado"] is True


async def test_depois_do_barge_in_a_fila_espera_a_pessoa_terminar(d):
    a = await d.falar("A falando bastante.", origem="A")
    await d.falar("B na fila.", origem="B")
    await d._mensagem({"type": "audio_inicio", "id": a.id})
    await d._mensagem({"type": "falando"})
    await d._mensagem({"type": "barge_in", "id": a.id, "tocado_ms": 800})
    assert a.barge_in and d.bloco_atual is None
    assert d.ws.faladas() == ["A falando bastante."]  # a pessoa está falando: B espera
    await d._mensagem({"type": "fala", "id": "u1", "texto": "espera aí"})
    await asyncio.sleep(0.05)
    assert d.ws.faladas() == ["A falando bastante.", "B na fila."]


async def test_parar_esvazia_a_fila(d):
    await d.falar("A.", origem="A")
    b = await d.falar("B.", origem="B")
    await d.comando({"cmd": "parar"})
    assert b.descartado and not d.fila and d.bloco_atual is None


async def test_leitura_em_partes_e_um_bloco_so(d):
    texto = "\n\n".join(f"Parágrafo {i}: " + "uma frase que ocupa espaço na leitura. " * 7 for i in range(2))
    res = await d.comando({"cmd": "ler", "texto": texto, "origem": "A"})
    assert res["ok"]
    await asyncio.sleep(0.2)
    assert d.bloco_atual is not None and d.bloco_atual.tipo == "ler"
    assert len(d.bloco_atual.falas) > 1
    assert d.ws.faladas() == [f.texto for f in d.bloco_atual.falas]  # as partes vão juntas, em ordem


async def test_fala_que_nunca_chegou_nao_prende_a_fila(d, monkeypatch):
    monkeypatch.setattr(daemon_mod, "FALANDO_MAX_S", 0.0)
    a = await d.falar("A.", origem="A")
    await d.falar("B.", origem="B")
    await d._mensagem({"type": "falando"})
    await tocar_ate_o_fim(d, a)
    assert d.ws.faladas() == ["A."]  # a pessoa "está falando"
    pulso = asyncio.ensure_future(d._pulso())
    await asyncio.sleep(2.2)
    pulso.cancel()
    assert not d.pessoa_falando
    assert d.ws.faladas() == ["A.", "B."]


async def test_ocioso_no_modo_ferramenta_encerra_a_sessao(d, monkeypatch):
    monkeypatch.setattr(daemon_mod, "modo", lambda: "ferramenta")
    d.cfg.ocioso_s = 1
    d._ultima_atividade -= 5
    assert d._ocioso()
    monkeypatch.setattr(daemon_mod, "modo", lambda: "leitura")
    assert not d._ocioso()  # na leitura a pessoa conta com a voz ligada
    monkeypatch.setattr(daemon_mod, "modo", lambda: "ferramenta")
    await d.comando({"cmd": "falar", "texto": "Oi.", "origem": "A"})
    assert not d._ocioso()
