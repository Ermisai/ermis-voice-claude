import wave
from pathlib import Path

import numpy as np
import pytest

from ermis_voz.audio_local import BLOCK, RATE, Aec, Decimador, _resample

# Falas de teste (WAV mono): uma do agente e uma da pessoa. Não vêm no repositório; sem elas, os testes do AEC pulam.
DATA = Path(__file__).resolve().parent / "data"


def _load48(name: str) -> np.ndarray:
    if not (DATA / name).exists():
        pytest.skip(f"sem {DATA / name}")
    with wave.open(str(DATA / name)) as w:
        audio = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768.0
        return _resample(audio, w.getframerate(), RATE)


def _db(x: np.ndarray) -> float:
    return 10 * np.log10(np.mean(x.astype(np.float64) ** 2) + 1e-12)


def test_aec_remove_o_eco_do_alto_falante():
    far = _load48("agente.wav")
    rng = np.random.default_rng(0)
    n = int(RATE * 0.08)
    rir = rng.standard_normal(n) * np.exp(-np.arange(n) / (RATE * 0.02))
    rir[0] = 1.0
    rir /= np.sqrt(np.sum(rir**2))
    delay = int(RATE * 0.03)  # o que o driver informa, mais ~0: o AEC recebe o atraso certo
    echo = np.convolve(far, rir)[: far.size] * 0.3
    mic = np.concatenate([np.zeros(delay), echo])[: far.size].astype(np.float32)
    mic += rng.standard_normal(mic.size).astype(np.float32) * 1e-4
    aec = Aec(True)
    assert aec.ativo
    out = []
    for i in range(0, far.size - BLOCK, BLOCK):
        out.append(aec.processar(mic[i : i + BLOCK], far[i : i + BLOCK], delay_ms=30))
    out = np.concatenate(out)
    tail = slice(int(RATE * 2.5), out.size)  # depois de convergir
    erle = _db(mic[tail]) - _db(out[tail])
    assert erle > 15, erle


def test_aec_deixa_a_fala_da_pessoa():
    near = _load48("pessoa.wav")
    aec = Aec(True)
    out = []
    silence = np.zeros(BLOCK, dtype=np.float32)
    for i in range(0, near.size - BLOCK, BLOCK):
        out.append(aec.processar(near[i : i + BLOCK], silence, delay_ms=30))
    out = np.concatenate(out)
    # sem nada tocando, o AEC não pode comer a voz (a supressão de ruído tira um pouco)
    assert _db(out) > _db(near[: out.size]) - 6


def test_decimador_passa_voz_e_corta_alto():
    t = np.arange(RATE) / RATE
    dec = Decimador()
    low = np.concatenate([dec(x) for x in np.split(np.sin(2 * np.pi * 1000 * t).astype(np.float32), 100)])
    dec = Decimador()
    high = np.concatenate([dec(x) for x in np.split(np.sin(2 * np.pi * 12000 * t).astype(np.float32), 100)])
    assert low.size == 16000
    assert abs(_db(low[1000:]) - _db(np.sin(2 * np.pi * 1000 * t))) < 1
    assert _db(high[1000:]) < -30
