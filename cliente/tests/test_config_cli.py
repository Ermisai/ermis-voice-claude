import importlib
import json


def _cli(tmp_path, monkeypatch):
    monkeypatch.setenv("ERMIS_VOZ_HOME", str(tmp_path))
    import ermis_voz.cli
    import ermis_voz.config

    importlib.reload(ermis_voz.config)
    return importlib.reload(ermis_voz.cli)


def test_config_set_qualquer_campo(tmp_path, monkeypatch, capsys):
    cli = _cli(tmp_path, monkeypatch)
    assert cli.main(["config", "--servidor", "ws://x:8300", "--token", "segredo",
                     "--set", "preenchimento=false", "--set", "leitura_max_s=60",
                     "--set", "frases_preenchimento=Um momento.|Deixa eu ver."]) == 0
    salvo = json.loads((tmp_path / "config.json").read_text())
    assert salvo["servidor"] == "ws://x:8300" and salvo["token"] == "segredo"
    assert salvo["preenchimento"] is False and salvo["leitura_max_s"] == 60.0
    assert salvo["frases_preenchimento"] == ["Um momento.", "Deixa eu ver."]
    assert "segredo" not in capsys.readouterr().out  # o token não aparece na tela


def test_config_campo_errado(tmp_path, monkeypatch, capsys):
    cli = _cli(tmp_path, monkeypatch)
    assert cli.main(["config", "--set", "nao_existe=1"]) == 2
    assert "campo desconhecido" in capsys.readouterr().err
    assert cli.main(["config", "--set", "leitura_max_s=muito"]) == 2


def test_config_sem_argumentos_so_mostra(tmp_path, monkeypatch, capsys):
    cli = _cli(tmp_path, monkeypatch)
    assert cli.main(["config"]) == 0
    assert '"servidor"' in capsys.readouterr().out
    assert not (tmp_path / "config.json").exists()
