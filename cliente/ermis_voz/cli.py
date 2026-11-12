"""Linha de comando: ``ermis-voz <comando>``.

    ermis-voz chave                  cola a sua chave de API da Ermis (app.ermis.ai, Tokens API), confere e salva
    ermis-voz config --set fila_max=5    mostra ou muda a configuração (vale na hora)
    ermis-voz vozes                  as vozes da sua conta (para `ermis-voz config --voz NOME`)
    ermis-voz testar                 fala uma frase, escuta e mostra o que ouviu
    ermis-voz modo maos_livres       ferramenta | maos_livres | comando | leitura | espaco | desligado
    ermis-voz espaco segurar --t MS  segurar o espaço para falar (o painel chama: segurar, soltar, cancelar)
    ermis-voz palavra Jarvis         troca a palavra-chave do modo comando (--grafias "jarvis,jarbis")
    ermis-voz pensamento off         on | off | so-pensamento | so-progresso | leitura-on | leitura-off
    ermis-voz status | parar | sair
    ermis-voz daemon                 (o MCP e os hooks sobem sozinhos)
    ermis-voz mcp                    (o plugin chama)
    ermis-voz hook <evento>          (o plugin chama)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import subprocess
import sys
import time

from ermis_voz.config import HOME, LOG_PATH, Config, modo, set_modo
from ermis_voz.daemon import pedir, rodando

MODOS = ("ferramenta", "maos_livres", "comando", "leitura", "espaco", "desligado")


async def garantir_daemon(cwd: str | None = None) -> None:
    """Sobe o daemon em segundo plano se ele não está rodando, e espera o socket."""
    if rodando():
        return
    HOME.mkdir(parents=True, exist_ok=True)
    log = open(LOG_PATH, "a", encoding="utf-8")  # noqa: SIM115 — fica com o processo filho
    subprocess.Popen(
        [sys.executable, "-m", "ermis_voz.cli", "daemon"],
        cwd=cwd or os.getcwd(), stdout=log, stderr=log, stdin=subprocess.DEVNULL, start_new_session=True,
    )
    for _ in range(100):
        if rodando():
            return
        await asyncio.sleep(0.1)
    raise RuntimeError(f"o daemon de voz não subiu; veja {LOG_PATH}")


def _daemon(args) -> int:
    from ermis_voz.daemon import Daemon

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = Config.load()
    if not cfg.token:
        print("sem chave de API: crie uma em https://app.ermis.ai (Tokens API) e rode `ermis-voz chave`",
              file=sys.stderr)
        return 1
    factory = None
    if args.arquivo:
        from pathlib import Path

        from ermis_voz.audio_local import Arquivo

        def factory(on_mic, loop):  # noqa: ANN001
            return Arquivo(on_mic, loop, eco_db=args.eco_db, gravar_saida=Path(args.gravar_saida) if args.gravar_saida else None)
    asyncio.run(Daemon(cfg, audio_factory=factory).run())
    return 0


def _espaco(args) -> int:
    """Segurar o espaço para falar (o painel chama ao apertar e ao soltar). Segurar sobe o daemon se preciso e, fora
    dos modos de voz, liga o modo espaço: o microfone só vai para a Voice API enquanto o espaço está apertado."""
    if args.acao == "segurar":
        if modo() in ("ferramenta", "desligado"):
            set_modo("espaco")
        asyncio.run(garantir_daemon(os.getcwd()))
    elif not rodando():
        print(json.dumps({"ok": True, "rodando": False}))
        return 0
    res = asyncio.run(pedir({"cmd": "espaco", "acao": args.acao, "t": args.t}, timeout=10))
    print(json.dumps(res, ensure_ascii=False))
    return 0 if res.get("ok") else 1


def _config(args) -> int:
    """Mostra a configuração; com opções, muda e aplica no daemon na hora (abre uma sessão nova se o endereço ou a
    chave mudaram). Qualquer campo: --set campo=valor (listas separadas por |)."""
    from dataclasses import fields

    from ermis_voz.config import CONFIG_PATH, _cast

    cfg = Config.load()
    mudou = False
    for key in ("servidor", "token", "paciencia", "voz", "velocidade", "aec", "entrada", "saida"):
        value = getattr(args, key)
        if value is not None:
            setattr(cfg, key, value)
            mudou = True
    tipos = {f.name: f.type for f in fields(Config)}
    for item in args.set or []:
        if "=" not in item:
            print(f"--set precisa de campo=valor (recebi {item!r})", file=sys.stderr)
            return 2
        chave, valor = (p.strip() for p in item.split("=", 1))
        if chave not in tipos:
            print(f"campo desconhecido: {chave}. Campos: {', '.join(sorted(tipos))}", file=sys.stderr)
            return 2
        try:
            setattr(cfg, chave, _cast(valor, tipos[chave]))
        except ValueError:
            print(f"valor inválido para {chave}: {valor!r}", file=sys.stderr)
            return 2
        mudou = True
    if mudou:
        cfg.save()
        if rodando():
            res = asyncio.run(pedir({"cmd": "recarregar"}, timeout=10))
            print("aplicado no daemon" + (" (abrindo uma sessão nova)" if res.get("reconectando") else ""),
                  file=sys.stderr)
    shown = {**cfg.__dict__, "token": "***" if cfg.token else ""}
    print(json.dumps(shown, ensure_ascii=False, indent=2))
    print(f"(arquivo: {CONFIG_PATH})", file=sys.stderr)
    return 0


def _chave(args) -> int:
    """A chave de API de quem usa: colada aqui (sem eco, fora do histórico do shell) ou como argumento; conferida na
    Voice API antes de salvar."""
    import getpass

    from ermis_voz.voice_api import PLATAFORMA, ErroApi, conferir_chave

    cfg = Config.load()
    chave = (args.valor or "").strip()
    if not chave:
        if not sys.stdin.isatty():
            print("passe a chave: `ermis-voz chave SUA_CHAVE` (ou rode no terminal, para colar sem aparecer)",
                  file=sys.stderr)
            return 2
        print(f"Crie a chave em {PLATAFORMA} (menu Tokens API, com acesso ao Ermis Voice) e cole aqui.")
        chave = getpass.getpass("Chave de API: ").strip()
    try:
        saldo = asyncio.run(conferir_chave(cfg.servidor, chave))
    except ErroApi as exc:
        print(f"a chave não foi salva: {exc}", file=sys.stderr)
        return 1
    cfg.token = chave
    cfg.save()
    creditos = saldo.get("available_credits")
    print("chave conferida e salva" + (f" (créditos disponíveis: {creditos})" if creditos is not None else ""))
    if rodando():
        asyncio.run(pedir({"cmd": "recarregar"}, timeout=10))
        print("aplicada no daemon (abrindo uma sessão nova)", file=sys.stderr)
    return 0


def _vozes(args) -> int:
    from ermis_voz.voice_api import ErroApi, vozes

    cfg = Config.load()
    try:
        lista = asyncio.run(vozes(cfg.servidor, cfg.token))
    except ErroApi as exc:
        print(str(exc), file=sys.stderr)
        return 1
    for v in lista:
        marca = " (padrão)" if v.get("default") else ""
        teste = "" if v.get("production", True) else " [só testes]"
        print(f"{v.get('id')}{marca}{teste}: {v.get('description') or ''}")
    print("\nPara trocar: ermis-voz config --voz NOME", file=sys.stderr)
    return 0


def _recarregar() -> None:
    if rodando():
        asyncio.run(pedir({"cmd": "recarregar"}, timeout=10))


def _palavra(args) -> int:
    cfg = Config.load()
    if args.nova:
        cfg.palavra_chave = args.nova.strip()
        cfg.grafias_extras = [g.strip() for g in (args.grafias or "").split(",") if g.strip()]
        cfg.save()
        _recarregar()
    print(f"palavra-chave: {cfg.palavra_chave}")
    print("grafias aceitas: " + ", ".join(cfg.variantes()))
    print("(e, por aproximação, uma palavra parecida seguida de vírgula: \"" + cfg.palavra_chave + ", ...\")")
    return 0


def _pensamento(args) -> int:
    cfg = Config.load()
    if args.valor in ("leitura-on", "leitura-off"):
        cfg.pensamento_na_leitura = args.valor == "leitura-on"
        cfg.save()
        _recarregar()
    elif args.valor:
        cfg.falar_pensamento = args.valor in ("on", "so-pensamento")
        cfg.falar_progresso = args.valor in ("on", "so-progresso")
        cfg.save()
        _recarregar()
    print(f"falar o pensamento: {'sim' if cfg.falar_pensamento else 'não'}; "
          f"falar o que faz entre ferramentas: {'sim' if cfg.falar_progresso else 'não'}; "
          f"também no modo leitura: {'sim' if cfg.pensamento_na_leitura else 'não'}")
    return 0


def _simples(cmd: str) -> int:
    if not rodando():
        print("o daemon não está rodando")
        return 1
    print(json.dumps(asyncio.run(pedir({"cmd": cmd}, timeout=10)), ensure_ascii=False, indent=2))
    return 0


def _testar(args) -> int:
    async def run() -> dict:
        await garantir_daemon()
        t0 = time.monotonic()
        res = await pedir({"cmd": "conversar", "texto": "Oi! Diga alguma coisa para eu testar o microfone.",
                           "esperar_resposta": True, "timeout": 20})
        res["segundos"] = round(time.monotonic() - t0, 1)
        return res

    res = asyncio.run(run())
    from ermis_voz.formato import resultado_conversar

    print(resultado_conversar(res))
    return 0 if res.get("ok") else 1


def _dispositivos(_args) -> int:
    import sounddevice as sd

    print(sd.query_devices())
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="ermis-voz", description="Voz em português para o Claude Code (Ermis).")
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("daemon")
    d.add_argument("--arquivo", action="store_true", help="áudio de teste em vez do microfone (para testes)")
    d.add_argument("--eco-db", type=float, default=None)
    d.add_argument("--gravar-saida", default="")
    sub.add_parser("mcp")
    h = sub.add_parser("hook")
    h.add_argument("evento")
    c = sub.add_parser("config", help="mostra ou muda a configuração (vale na hora)")
    for key in ("servidor", "token", "paciencia", "voz", "aec", "entrada", "saida"):
        c.add_argument(f"--{key}")
    c.add_argument("--velocidade", type=float, help="da fala: 0.75 (mais devagar) a 1.25 (mais rápido); 1 é a normal")
    c.add_argument("--set", action="append", metavar="CAMPO=VALOR",
                   help="qualquer campo do config.json, ex.: --set preenchimento=false --set leitura_max_s=60")
    ch = sub.add_parser("chave", help="cola a sua chave de API da Ermis, confere e salva")
    ch.add_argument("valor", nargs="?", help="a chave (sem ela, pede sem mostrar na tela)")
    sub.add_parser("vozes", help="as vozes da sua conta")
    m = sub.add_parser("modo")
    m.add_argument("valor", nargs="?", choices=MODOS)
    es = sub.add_parser("espaco", help="segurar o espaço para falar (o painel chama)")
    es.add_argument("acao", choices=("segurar", "soltar", "cancelar"))
    es.add_argument("--t", type=float, default=None, help="quando apertou, ms desde a época")
    pc = sub.add_parser("palavra", help="mostra ou troca a palavra-chave do modo comando")
    pc.add_argument("nova", nargs="?")
    pc.add_argument("--grafias", help="como o STT escreve a palavra, separadas por vírgula")
    pe = sub.add_parser("pensamento", help="liga ou desliga a narração do que o Claude pensa e faz")
    pe.add_argument("valor", nargs="?",
                    choices=("on", "off", "so-pensamento", "so-progresso", "leitura-on", "leitura-off"))
    for name in ("status", "parar", "sair", "testar", "dispositivos"):
        sub.add_parser(name)
    args = p.parse_args(argv)

    if args.cmd == "daemon":
        return _daemon(args)
    if args.cmd == "mcp":
        from ermis_voz.mcp_servidor import main as mcp_main

        mcp_main()
        return 0
    if args.cmd == "hook":
        from ermis_voz.hooks import main as hook_main

        return hook_main(args.evento)
    if args.cmd == "config":
        return _config(args)
    if args.cmd == "chave":
        return _chave(args)
    if args.cmd == "vozes":
        return _vozes(args)
    if args.cmd == "modo":
        if args.valor:
            set_modo(args.valor)
        print(modo())
        return 0
    if args.cmd == "palavra":
        return _palavra(args)
    if args.cmd == "espaco":
        return _espaco(args)
    if args.cmd == "pensamento":
        return _pensamento(args)
    if args.cmd in ("status", "parar", "sair"):
        return _simples(args.cmd)
    if args.cmd == "testar":
        return _testar(args)
    if args.cmd == "dispositivos":
        return _dispositivos(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
