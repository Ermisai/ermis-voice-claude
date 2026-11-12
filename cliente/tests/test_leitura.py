import pytest

from ermis_voz.pronuncia import preparar as _preparar
from ermis_voz.leitura import FIM_CORTE, FIM_RESUMO, PARTE_MAX, extrativo, limpar, partes, preparar, segundos

FALADO = _preparar

RESPOSTA = """## Resultado

Rodei os testes: **três falharam** no `cliente.py`.

```python
assert x == 1
```

| teste | erro |
|---|---|
| a | b |

- O primeiro é de importação.
- O segundo é um tempo esgotado.

Veja [o log](https://exemplo.com/log) para detalhes."""


def test_limpar_tira_codigo_tabela_e_markdown():
    t = limpar(RESPOSTA)
    assert "assert" not in t and "|" not in t and "**" not in t and "https" not in t and "##" not in t
    assert "(Tem código na tela.)" in t and "(Tem uma tabela na tela.)" in t
    assert "O primeiro é de importação." in t


def test_partes_respeitam_o_tamanho_e_nao_perdem_texto():
    longo = " ".join(f"Esta é a frase número {i} de um parágrafo comprido." for i in range(60))
    ps = partes(longo + "\n\nOutro parágrafo curto.")
    assert all(len(p) <= PARTE_MAX for p in ps)
    junto = " ".join(ps)
    assert "frase número 0 " in junto and "frase número 59 " in junto and "Outro parágrafo curto." in junto


def test_extrativo_pega_a_primeira_frase_de_cada_paragrafo():
    t = ("O primeiro ponto importante é este. Detalhe um.\n\nResultado:\n\nO segundo ponto importante é aquele. "
         "Detalhe dois.\n\n(Tem código na tela.)\n\nTítulo.\n\nO terceiro ponto importante fecha tudo. Mais.")
    assert extrativo(t, 1000) == ("O primeiro ponto importante é este. O segundo ponto importante é aquele. "
                                  "O terceiro ponto importante fecha tudo.")


@pytest.fixture(autouse=True)
def sem_chave(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("VOZ_ANTHROPIC_KEY", raising=False)


async def test_resposta_curta_e_lida_inteira():
    lei = await preparar(RESPOSTA, FALADO)
    assert lei.info["modo"] == "inteiro"
    assert "três falharam" in " ".join(lei.partes)


async def test_resposta_longa_vira_resumo_e_respeita_o_teto():
    longa = "\n\n".join(
        f"Na etapa {i}, o serviço {i} respondeu em tempo e os testes desse módulo passaram sem erro. "
        f"Depois conferi os logs da etapa {i} e não havia nada fora do comum." for i in range(80)
    )
    assert segundos(limpar(longa), FALADO) > 300  # mais de 5 minutos se fosse lida inteira
    lei = await preparar("Resultado:\n\n" + longa, FALADO, max_s=120, resumo_s=60)  # sem abertura que resuma
    assert lei.info["modo"] == "extrativo"  # sem chave da API
    assert lei.info["falado_s"] <= 125
    assert lei.partes[-1] in (FIM_RESUMO, FIM_CORTE) or lei.partes[-1].endswith(FIM_RESUMO)


async def test_resposta_longa_com_abertura_le_a_abertura():
    abertura = "Rodei tudo: os três serviços responderam e só o de eco falhou, por um limiar alto demais."
    longa = abertura + "\n\n" + "\n\n".join(f"Detalhe {i}: " + "texto comprido de verdade " * 10 for i in range(40))
    lei = await preparar(longa, FALADO)
    assert lei.info["modo"] == "abertura"
    assert lei.partes == [f"{abertura} {FIM_RESUMO}"]


async def test_teto_corta_e_avisa():
    longa = "\n\n".join(f"Parágrafo {i}: " + "texto comprido de verdade " * 12 for i in range(40))
    lei = await preparar(longa, FALADO, inteiro_ate_s=10_000, max_s=30)  # força "inteiro" com teto curto
    assert lei.info.get("cortado") and lei.partes[-1] == FIM_CORTE
    assert lei.info["falado_s"] <= 30 + 5


async def test_ingles_sem_chave_avisa():
    lei = await preparar("Let me check the test output first and then I will fix the import that is broken.", FALADO)
    assert lei.partes == ["A resposta está em inglês. Está na tela."]
