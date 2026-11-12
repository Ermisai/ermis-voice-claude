import json

from ermis_voz.formato import bloco_fala, resultado_conversar
from ermis_voz.hooks import SAIR_DA_VOZ, _ultima_resposta, resumo_falado


def test_resumo_falado_pula_codigo_e_corta_na_frase():
    texto = (
        "Rodei os testes: três falharam no cliente.py. O primeiro é de importação.\n\n"
        "```\nFAILED tests/test_x.py::test_a\n```\n\n"
        "- item um\n- item dois\n\n"
        "Quer que eu corrija? " + "Mais texto longo. " * 40
    )
    r = resumo_falado(texto, limite=200)
    assert r.startswith("Rodei os testes")
    assert "FAILED" not in r and "item um" not in r
    assert len(r) <= 200


def test_ultima_resposta_da_transcricao(tmp_path):
    path = tmp_path / "t.jsonl"
    linhas = [
        {"type": "user", "message": {"content": "oi"}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "primeira"}]}},
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash"}]}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "a última resposta"}]}},
    ]
    path.write_text("\n".join(json.dumps(x) for x in linhas))
    assert _ultima_resposta({"transcript_path": str(path)}) == "a última resposta"
    assert _ultima_resposta({"last_assistant_message": "direto"}) == "direto"


def test_formato():
    fala = {"texto": "roda o pytest", "cru": "roda o pai teste", "alternativas": ["roda o pai teste"],
            "incerto": ["duas leituras próximas do áudio"]}
    b = bloco_fala(fala)
    assert b.splitlines()[0] == "[fala] roda o pytest"
    assert "[ouvido cru]" in b and "[alternativas]" in b and "[incerto]" in b
    assert "[silêncio]" in resultado_conversar({"ok": True, "fala": None, "timeout_s": 30})
    assert bloco_fala({"texto": "sim", "alternativas": [], "incerto": [], "cru": None}) == "[fala] sim"


def test_avisos_em_portugues():
    from ermis_voz.hooks import aviso_em_portugues

    assert aviso_em_portugues("Claude is waiting for your input") == "O Claude está esperando você."
    assert aviso_em_portugues("Claude needs your permission to use Bash") == (
        "O Claude precisa da sua permissão para usar Bash.")
    assert aviso_em_portugues("Something else happened and the user should check the output") == ""
    assert aviso_em_portugues("Terminei a tarefa.") == "Terminei a tarefa."


def test_sair_da_voz():
    assert SAIR_DA_VOZ.search("ok, pode parar de ouvir")
    assert SAIR_DA_VOZ.search("desliga a voz")
    assert not SAIR_DA_VOZ.search("para de rodar os testes")
