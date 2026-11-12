import pytest

from ermis_voz.pronuncia import preparar as _preparar
from ermis_voz.fala import normalizar, por_extenso, soletrar_siglas

from .frases_fala import FRASES


@pytest.mark.parametrize(
    "n,txt",
    [
        (0, "zero"), (1, "um"), (16, "dezesseis"), (21, "vinte e um"), (100, "cem"), (101, "cento e um"),
        (140, "cento e quarenta"), (541, "quinhentos e quarenta e um"), (1000, "mil"), (1005, "mil e cinco"),
        (1200, "mil e duzentos"), (1250, "mil duzentos e cinquenta"), (2026, "dois mil e vinte e seis"),
        (1_000_000, "um milhão"), (2_500_000, "dois milhões e quinhentos mil"), (-3, "menos três"),
    ],
)
def test_por_extenso(n, txt):
    assert por_extenso(n) == txt


def test_feminino():
    assert por_extenso(2, True) == "duas"
    assert por_extenso(1, True) == "uma"
    assert por_extenso(3200, True) == "três mil e duzentas"
    assert por_extenso(2_000_000, True) == "dois milhões"  # milhão é masculino


@pytest.mark.parametrize("frase,esperado", FRASES)
def test_frases_tecnicas(frase, esperado):
    prep = _preparar
    falado = prep(frase).lower()
    for parte in esperado:
        assert prep(parte).lower().rstrip(".") in falado, falado  # a parte com a mesma grafia de pronúncia
    assert not any(c.isdigit() for c in falado), falado  # nenhum dígito chega ao TTS


def test_nada_a_fazer_fica_igual():
    frase = "Pronto, terminei de revisar o arquivo."
    assert normalizar(frase) == frase


def test_siglas():
    assert soletrar_siglas("O STT e o OK") == "O ésse tê tê e o okei"
    assert soletrar_siglas("as CPUs") == "as cê pê us"
