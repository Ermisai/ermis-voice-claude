import re

from ermis_voz.pronuncia import preparar as _preparar
from ermis_voz.fala import normalizar
from ermis_voz.falavel import FRASE_MAX, PEDACO_MAX, estilo_falado, frases_para_tts

FALADO = _preparar


def test_fracao_nao_e_data():
    assert "dois terços das falas" in normalizar("e 2/3 das falas vêm de comissões")
    assert "metade dos testes" in normalizar("1/2 dos testes")
    assert "três de cinco testes" in normalizar("3/5 testes passaram")
    assert "trinta e um de outubro de dois mil e vinte e seis" in normalizar("em 31/10/2026")
    assert "trinta e um de outubro" in normalizar("até dia 31/10")


def test_letra_com_numero():
    assert "bê zero" in normalizar("rodei o B0")
    assert "éfe um" in normalizar("o F1 subiu")


def test_frase_longa_vira_frases_completas():
    texto = ("Já terminaram as fases de quatro e duas máquinas, e falta a de oito; o resultado principal até aqui "
             "mostra que máquina pequena não compensa, mas a de quatro aguenta duas ligações sem atraso nenhum.")
    out = estilo_falado(texto)
    frases = re.split(r"(?<=[.!?])\s+", out)
    assert all(len(f) <= FRASE_MAX + 20 for f in frases)
    assert all(f[0].isupper() and f[-1] in ".!?" for f in frases)
    assert "Mas a de quatro" in out or "O resultado" in out


def test_nao_comeca_frase_com_que():
    texto = ("Mudei o envio para o serviço de voz, que agora recebe uma frase inteira por vez em vez de pedaços "
             "cortados numa vírgula qualquer, o que fazia a entonação cair no meio da oração toda vez.")
    assert ". Que " not in estilo_falado(texto) and ". O que " not in estilo_falado(texto)


def test_parenteses_viram_aparte():
    assert estilo_falado("Corrigi o normalizador (que tratava frações como datas) hoje.") == (
        "Corrigi o normalizador, que tratava frações como datas, hoje.")


def test_tts_recebe_frases_inteiras():
    texto = ("Refiz o PDF a partir da versão do zip e rodei o B0. O B0 não passa no critério de 80%: só 25,7% das "
             "2.000 falas têm o discurso oficial disponível pela API. O motivo é que a API só cobre o Plenário, e "
             "2/3 das falas vêm de comissões e outros eventos.")
    pedacos = frases_para_tts(FALADO(texto))
    assert all(p.rstrip()[-1] in ".!?…" for p in pedacos)  # nenhum pedaço termina no meio de uma frase
    assert all(len(p) <= PEDACO_MAX for p in pedacos)
    assert "dois terços das falas" in " ".join(pedacos)
