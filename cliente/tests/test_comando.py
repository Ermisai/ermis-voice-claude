import numpy as np

from ermis_voz.audio_local import RATE, Reproducao
from ermis_voz.chave import tirar_palavra


def test_palavra_chave():
    assert tirar_palavra("Ermis, roda os testes.") == "Roda os testes."
    assert tirar_palavra("Hermes, faz o commit.") == "Faz o commit."  # como o reconhecimento costuma escrever
    assert tirar_palavra("Ô Hermes, abre o arquivo.") == "Abre o arquivo."
    assert tirar_palavra("ok ermis") == ""  # só chamaram
    assert tirar_palavra("O Ermis falou que sim") is None  # falando dele, não com ele
    assert tirar_palavra("Roda os testes.") is None
    assert tirar_palavra("Hermenegildo ligou") is None
    assert tirar_palavra("Jarvis, roda", ["jarvis"]) == "Roda"


def _tom(segundos: float) -> bytes:
    t = np.arange(int(24000 * segundos)) / 24000
    return (np.sin(2 * np.pi * 440 * t) * 0.5 * 32767).astype("<i2").tobytes()


def _tocar(rep: Reproducao, ms: float) -> np.ndarray:
    n = int(RATE * ms / 1000)
    return np.concatenate([rep.tirar(480) for _ in range(n // 480)])


def test_apagar_e_suave_e_rapido():
    rep = Reproducao()
    rep.adicionar_pcm24(_tom(2.0))
    antes = _tocar(rep, 200)
    rep.apagar()
    depois = _tocar(rep, 300)
    pico = np.abs(antes).max()
    # sem degrau: nenhuma amostra pula mais do que a própria senoide pula (sem clique)
    salto = np.abs(np.diff(np.concatenate([antes[-480:], depois]))).max()
    assert salto <= np.abs(np.diff(antes)).max() * 1.05
    # em ~150 ms está em silêncio, e o resto da fala foi descartado
    assert np.abs(depois[int(RATE * 0.16):]).max() < 1e-4
    assert rep.pendente_ms == 0
    # e a envoltória cai aos poucos: aos 75 ms ainda há som
    meio = depois[int(RATE * 0.07) : int(RATE * 0.08)]
    assert 0.2 * pico < np.abs(meio).max() < 0.8 * pico


def test_abaixar_e_restaurar():
    rep = Reproducao()
    rep.adicionar_pcm24(_tom(2.0))
    cheio = np.abs(_tocar(rep, 100)).max()
    rep.abaixar()
    _tocar(rep, 100)
    baixo = np.abs(_tocar(rep, 50)).max()
    assert abs(baixo / cheio - Reproducao.DUCK) < 0.05
    rep.restaurar()
    _tocar(rep, 200)
    assert abs(np.abs(_tocar(rep, 50)).max() / cheio - 1.0) < 0.05


def test_fala_nova_depois_de_apagar_toca_inteira():
    rep = Reproducao()
    rep.adicionar_pcm24(_tom(1.0))
    _tocar(rep, 50)
    rep.apagar()
    _tocar(rep, 300)
    rep.adicionar_pcm24(_tom(0.5))
    assert rep.pendente_ms > 400
    assert np.abs(_tocar(rep, 100)).max() > 0.4


async def test_pedido_depois_de_ermis_sozinho_vale_ate_a_fala_fechar(tmp_path, monkeypatch):
    # 05/11: com a Voice API o turno fecha ~1 s depois; um pedido começado na janela chegava depois dela
    import time

    from ermis_voz import daemon as daemon_mod
    from ermis_voz.config import Config
    from ermis_voz.daemon import Daemon

    monkeypatch.setattr(daemon_mod, "HOME", tmp_path)
    monkeypatch.setattr(daemon_mod, "ESTADO_PATH", tmp_path / "estado.json")
    d = Daemon(Config())
    d._janela_comando_ate = time.monotonic() + 0.5
    await d._mensagem({"type": "falando"})
    assert d._janela_comando_ate > time.monotonic() + 60
