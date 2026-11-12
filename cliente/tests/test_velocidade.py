"""A fala do agente mais rápida no cliente (WSOLA), quando a Voice API não faz isso."""

import numpy as np

from ermis_voz.audio_local import RATE, Acelerador, Reproducao


def _tom(hz: float, s: float) -> np.ndarray:
    t = np.arange(int(RATE * s)) / RATE
    return (0.5 * np.sin(2 * np.pi * hz * t)).astype(np.float32)


def _acelerar(x: np.ndarray, v: float, pedaco: int = 4800) -> np.ndarray:
    a = Acelerador(v)
    partes = [a.processar(x[i:i + pedaco]) for i in range(0, x.size, pedaco)]
    return np.concatenate([*partes, a.terminar()])


def _freq(x: np.ndarray) -> float:
    espectro = np.abs(np.fft.rfft(x * np.hanning(x.size)))
    return float(np.fft.rfftfreq(x.size, 1 / RATE)[np.argmax(espectro)])


def test_encurta_na_proporcao():
    x = _tom(220, 3.0)
    for v in (1.15, 1.25, 0.8):
        y = _acelerar(x, v)
        assert abs(y.size / x.size - 1 / v) < 0.03


def test_nao_muda_o_tom():
    y = _acelerar(_tom(220, 3.0), 1.2)
    assert abs(_freq(y[RATE // 2 : RATE // 2 + RATE]) - 220) < 3


def test_sem_estalos():
    y = _acelerar(_tom(220, 2.0), 1.2)
    # uma senoide a 220 Hz anda no máximo 2π·220/48000·0,5 por amostra; um estalo pula muito mais
    assert np.abs(np.diff(y[2000:-2000])).max() < 0.03


def test_pedacos_de_qualquer_tamanho_dao_o_mesmo():
    x = _tom(300, 1.5)
    a, b = _acelerar(x, 1.15, 4800), _acelerar(x, 1.15, 977)
    assert a.size == b.size and np.allclose(a, b, atol=1e-5)


def test_reproducao_so_acelera_quando_pedido():
    rep = Reproducao()
    pcm = (_tom(220, 1.0) * 32767).astype("<i2").tobytes()
    rep.adicionar_pcm48(pcm)
    assert abs(rep.pendente_ms - 1000) < 1
    rep.limpar()
    rep.velocidade = 1.25
    rep.nova_fala()
    rep.adicionar_pcm48(pcm)
    rep.fim_fala()
    assert abs(rep.pendente_ms - 800) < 25
