import json

from ermis_voz.chave import tirar_palavra, variantes
from ermis_voz.config import Config
from ermis_voz.pensamento import candidatos, em_ingles, primeira_frase


def linha(blocos, stop="tool_use", sidechain=False):
    return json.dumps({"type": "assistant", "isSidechain": sidechain,
                       "message": {"id": "m1", "stop_reason": stop, "content": blocos}})


def test_candidatos():
    assert candidatos(linha([{"type": "thinking", "thinking": "Vou olhar o log."}])) == [("pensamento", "Vou olhar o log.")]
    assert candidatos(linha([{"type": "thinking", "thinking": ""}])) == []  # o thinking vazio dos modelos atuais
    assert candidatos(linha([{"type": "text", "text": "Rodo os testes."}])) == [("progresso", "Rodo os testes.")]
    assert candidatos(linha([{"type": "text", "text": "Pronto, terminei."}], stop="end_turn")) == []  # o Stop fala
    assert candidatos(linha([{"type": "thinking", "thinking": "x"}], sidechain=True)) == []  # subagente
    assert candidatos(linha([{"type": "thinking", "thinking": "Vou olhar."}]), pensamento=False) == []
    assert candidatos(json.dumps({"type": "user", "message": {"content": "oi"}})) == []
    assert candidatos("não é json") == []


def test_primeira_frase():
    texto = ("Vou verificar o relatório e o **formato** dos dados gravados por ligação. Depois comparo.\n\n```\nx\n```")
    assert primeira_frase(texto) == "Vou verificar o relatório e o formato dos dados gravados por ligação."
    longa = "A bateria já tem cerca de nove mil arquivos de ligações estéreo com eventos, transcrições e um juiz, " \
            "mas os dois lados são sintéticos, o que pesa para um artigo de dataset e para treinar modelos full-duplex."
    curta = primeira_frase(longa, 120)
    assert len(curta) <= 121 and curta.endswith(".") and not curta.endswith(",.")


def test_em_ingles():
    assert em_ingles("Let me check the test output first and then I will fix the import.")
    assert not em_ingles("Vou olhar o resultado dos testes e depois corrijo o import.")


def test_palavra_personalizada():
    cfg = Config(palavra_chave="Jarvis")
    assert cfg.variantes()[0] == "Jarvis"
    assert "hermes" not in cfg.variantes()  # as grafias de "Ermis" não valem para outra palavra
    assert tirar_palavra("Jarvis, roda os testes", cfg.variantes()) == "Roda os testes"
    assert tirar_palavra("Jarbis, abre o arquivo", cfg.variantes()) == "Abre o arquivo"  # aproximada, com vírgula
    assert tirar_palavra("Já vi isso", cfg.variantes()) is None
    assert tirar_palavra("Hermes, roda", cfg.variantes()) is None
    assert tirar_palavra("Jarbas roda", variantes("Jarvis", ["jarbas"])) == "Roda"  # grafia extra, sem vírgula
    assert tirar_palavra("Atrás da porta", variantes("Atlas")) is None
