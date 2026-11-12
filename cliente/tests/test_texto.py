import importlib.util

import pytest
from ermis_voz.texto import Corretor
from ermis_voz.pronuncia import para_fala


def test_termos_e_extensoes():
    c = Corretor()
    texto, corr = c.corrigir("roda o pai teste no cliente ponto pai e faz o comit")
    assert texto == "roda o pytest no cliente.py e faz o commit"
    fontes = {x.fonte for x in corr}
    assert {"termo", "extensao"} <= fontes


def test_extensao_solta_do_stt_preciso():
    c = Corretor()
    assert c.corrigir("Roda o Pytest no cliente. py e depois")[0] == "Roda o Pytest no cliente.py e depois"
    assert c.corrigir("Fim da frase. Python é bom")[0] == "Fim da frase. Python é bom"


def test_palavra_comum_fica():
    c = Corretor()
    for frase in ("esse que ele fez ficou bom", "puxe a cadeira", "o comitê decidiu", "o cláudio ligou"):
        assert c.corrigir(frase)[0] == frase


@pytest.mark.skipif(importlib.util.find_spec("ermis_voice") is None,
                    reason="casamento por som do motor; no cliente, quem faz é o vocabulary da Voice API")
def test_termos_do_projeto_por_som():
    c = Corretor(termos_projeto=["sessao.py", "Gravador", "EchoGate"])
    texto, corr = c.corrigir("abre o gravadôr")
    assert "Gravador" in texto
    assert any(x.fonte == "projeto" for x in corr)


def test_aprendido_vem_primeiro():
    c = Corretor(extras={"eco gueite": "EchoGate"})
    assert c.corrigir("olha o eco gueite")[0] == "olha o EchoGate"


def test_para_fala_tira_codigo_e_markdown():
    texto = "Rodei o **pytest** em `cliente.py`:\n```\nFAILED x\n```\nveja https://exemplo.com/a"
    assert para_fala(texto) == "Rodei o pytest em cliente ponto py. Tem código na tela. Veja o link."


def test_extensao_ja_escrita_pelo_vocabulario_da_api():
    # 05/11: a Voice API trocou "daemon" por "daemon.py" e o "ponto py" dito virava "daemon.py.py"
    texto, _ = Corretor().corrigir("Roda o pytest no daemon.py ponto py, por favor.")
    assert texto == "Roda o pytest no daemon.py, por favor."
