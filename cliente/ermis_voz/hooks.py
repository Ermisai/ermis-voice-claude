"""Hooks do Claude Code (``ermis-voz hook <evento>``, JSON na entrada padrão).

- ``session-start``: no modo mãos livres ou leitura, sobe o daemon, manda o léxico do projeto e avisa o Claude.
- ``post-tool-use``: o que a pessoa disse enquanto o Claude trabalhava entra como contexto.
- ``stop``: modo ``leitura`` fala o resumo da resposta; modo ``maos_livres`` fala o resumo, escuta e, se a pessoa
  responder, devolve ``decision: block`` com a fala dela, e o Claude continua com isso (a conversa sem o Claude ter
  de chamar a ferramenta).
- ``notification``: fala o aviso (pedido de permissão, espera).

Um hook nunca quebra a sessão: qualquer falha sai em silêncio (código 0).
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys

from ermis_voz.config import modo, set_modo
from ermis_voz.daemon import pedir, rodando
from ermis_voz.formato import bloco_fala, contexto_pendentes

SAIR_DA_VOZ = re.compile(
    r"\b(pode parar de (me )?ouvir|para(r)? de ouvir|desliga(r)? a voz|encerra(r)? a voz|modo texto|tchau,? claude)\b",
    re.IGNORECASE,
)

# Como escrever o que vai ser falado: o TTS lê melhor frases inteiras e curtas, sem símbolos (04/11: frases longas
# saíam "meio cortadas", siglas e frações saíam erradas). Vale para o parágrafo de abertura de todos os modos.
ESTILO_FALADO = (
    "Esse trecho vai ser falado por um sintetizador de voz: escreva como se fala, em frases completas de até umas "
    "vinte palavras, sem parênteses, sem siglas desconhecidas, sem barras nem símbolos, números simples e "
    "arredondados quando der (\"dois terços\", \"uns trinta segundos\"), nomes de arquivo só quando importam."
)

INSTRUCOES_MAOS_LIVRES = (
    "[voz] Modo mãos livres: a pessoa ouve o começo da sua resposta em voz alta e responde falando; a fala dela chega "
    "como [fala] (reconhecimento de voz: entenda termos técnicos pelo contexto e pelos nomes do projeto; use "
    "[alternativas] e [incerto] quando aparecerem). Comece cada resposta com uma ou duas frases curtas, sem código e "
    "sem markdown, que digam o essencial; se corrigiu o que ela disse, comece com \"Entendi: ...\". O detalhe pode vir "
    "depois, na tela. Confirme antes de ação destrutiva quando houver dúvida no que foi ouvido. " + ESTILO_FALADO
)


INSTRUCOES_LEITURA = (
    "[voz] Modo leitura: a pessoa ouve suas respostas em voz alta (o microfone fica desligado; ela fala com você pelo "
    "teclado). Abra TODA resposta com um parágrafo de no máximo três frases curtas, em português, sem código, sem "
    "markdown e sem listas, que diga o essencial: o resultado, o que mudou, o que você precisa dela. Esse parágrafo é "
    "o que ela ouve quando a resposta é longa; o resto fica na tela. " + ESTILO_FALADO
)

INSTRUCOES_COMANDO = (
    "[voz] Modo comando: a pessoa fala com você começando por \"{p}\" (\"{p}, roda os testes\"); o pedido chega "
    "como [fala], sem a palavra-chave (reconhecimento de voz: entenda termos técnicos pelo contexto e pelos nomes do "
    "projeto; use [alternativas] e [incerto] quando aparecerem). O começo de cada resposta é falado em voz alta: "
    "abra com uma ou duas frases curtas, sem código e sem markdown, que digam o essencial; se corrigiu o que ela "
    "disse, comece com \"Entendi: ...\". Confirme antes de ação destrutiva quando houver dúvida no que foi ouvido. "
    + ESTILO_FALADO.replace("{", "{{").replace("}", "}}")
)


def _out(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False))


def _ultima_resposta(entrada: dict) -> str:
    texto = entrada.get("last_assistant_message")
    if isinstance(texto, str) and texto.strip():
        return texto
    path = entrada.get("transcript_path")
    if not path:
        return ""
    ultimo = ""
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    item = json.loads(line)
                except ValueError:
                    continue
                if item.get("type") != "assistant":
                    continue
                content = (item.get("message") or {}).get("content")
                if isinstance(content, list):
                    partes = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
                    if any(p.strip() for p in partes):
                        ultimo = "\n".join(partes)
                elif isinstance(content, str) and content.strip():
                    ultimo = content
    except OSError:
        return ""
    return ultimo


def resumo_falado(texto: str, limite: int = 360) -> str:
    """O começo da resposta, sem código, até ``limite`` caracteres, cortado no fim de uma frase."""
    texto = re.sub(r"```.*?(```|$)", " ", texto, flags=re.DOTALL)
    paragrafos = [p.strip() for p in re.split(r"\n\s*\n", texto) if p.strip()]
    paragrafos = [p for p in paragrafos if not p.lstrip().startswith(("|", "-", "*", "#", ">")) or len(paragrafos) == 1]
    if not paragrafos:
        return ""
    out = ""
    for p in paragrafos:
        p = " ".join(p.split())
        if out and len(out) + len(p) > limite:
            break
        out = f"{out} {p}".strip()
    if len(out) > limite:
        frases = re.split(r"(?<=[.!?])\s+", out)
        out = ""
        for fr in frases:
            if out and len(out) + len(fr) > limite:
                break
            out = f"{out} {fr}".strip()
        out = out[:limite]
    return out


def _origem(entrada: dict) -> str:
    """Quem pede a fala, para a fila do daemon (uma janela do Claude não corta a fala de outra)."""
    return str(entrada.get("session_id") or f"pid{os.getppid()}")


async def _session_start(entrada: dict) -> None:
    m = modo()
    if m not in ("maos_livres", "leitura", "comando"):
        return
    from ermis_voz.cli import garantir_daemon

    await garantir_daemon(entrada.get("cwd"))
    if entrada.get("cwd"):
        await pedir({"cmd": "projeto", "raiz": entrada["cwd"]}, timeout=15)
    await _passar_transcricao(entrada)
    from ermis_voz.config import Config

    palavra = Config.load().palavra_chave or "Ermis"
    instrucoes = {"maos_livres": INSTRUCOES_MAOS_LIVRES, "comando": INSTRUCOES_COMANDO.format(p=palavra),
                  "leitura": INSTRUCOES_LEITURA}.get(m)
    if instrucoes:
        _out({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": instrucoes}})


async def _passar_transcricao(entrada: dict) -> None:
    """O daemon acompanha a transcrição da sessão para narrar o que o Claude pensa e faz."""
    if entrada.get("transcript_path") and rodando():
        await pedir({"cmd": "transcricao", "caminho": entrada["transcript_path"]}, timeout=3)


async def _user_prompt_submit(entrada: dict) -> None:
    if modo() != "desligado":
        await _passar_transcricao(entrada)


async def _post_tool_use(entrada: dict) -> None:
    if modo() == "desligado" or not rodando():
        return
    if modo() == "leitura":  # só ouvir: nada do microfone chega ao Claude
        await _passar_transcricao(entrada)
        return
    res = await pedir({"cmd": "pendentes", "transcricao": entrada.get("transcript_path")}, timeout=3)
    ctx = contexto_pendentes(res.get("falas") or [])
    if ctx:
        _out({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": ctx}})


async def _stop(entrada: dict) -> None:
    m = modo()
    if m not in ("leitura", "maos_livres", "comando"):
        return
    from ermis_voz.cli import garantir_daemon

    await garantir_daemon(entrada.get("cwd"))
    resposta = _ultima_resposta(entrada)
    if m in ("leitura", "comando"):  # no comando, o próximo pedido vem com "Ermis, ..." (pelo painel)
        # a resposta inteira vai ao daemon, que lê inteira (curta) ou resumida, em partes, até 2 minutos
        if resposta.strip():
            await pedir({"cmd": "ler", "texto": resposta, "origem": _origem(entrada)}, timeout=10)
        return
    resumo = resumo_falado(resposta)
    res = await pedir({"cmd": "conversar", "texto": resumo, "esperar_resposta": True, "origem": _origem(entrada)},
                    timeout=900)
    await pedir({"cmd": "nota", "kind": "hook_stop", "falado": resumo, "resposta": res.get("fala")}, timeout=10)
    falas = list(res.get("antes") or [])
    if res.get("fala"):
        falas.append(res["fala"])
    if not falas:
        return  # silêncio: deixa o Claude parar
    texto = " ".join((f.get("texto") or "") for f in falas)
    if SAIR_DA_VOZ.search(texto):
        set_modo("ferramenta")
        await pedir({"cmd": "falar", "texto": "Tá bom, voz desligada. Pode continuar pelo teclado.",
                     "origem": _origem(entrada)}, timeout=10)
        return
    corpo = "\n\n".join(bloco_fala(f) for f in falas)
    barge = res.get("interrompido")
    if barge:
        corpo = "[interrompeu] a pessoa falou por cima da sua resposta falada\n\n" + corpo
    _out({"decision": "block", "reason": "A pessoa respondeu por voz:\n" + corpo})


async def _notification(entrada: dict) -> None:
    if modo() not in ("maos_livres", "leitura", "comando") or not rodando():
        return
    msg = aviso_em_portugues(str(entrada.get("message") or "").strip())
    if msg:
        await pedir({"cmd": "falar", "texto": msg, "esperar_fim": False, "origem": _origem(entrada)}, timeout=10)


# Os avisos do Claude Code vêm em inglês; o TTS fala português (04/11: "Claude is waiting for your input" lido em pt)
_AVISOS = [
    (re.compile(r"^Claude is waiting for your input\.?$", re.I), lambda m: "O Claude está esperando você."),
    (re.compile(r"^Claude needs your permission to use (.+?)\.?$", re.I),
     lambda m: f"O Claude precisa da sua permissão para usar {m.group(1)}."),
    (re.compile(r"^Claude needs your (?:attention|input)\.?$", re.I), lambda m: "O Claude precisa de você."),
    (re.compile(r"^Claude (?:has )?finished\.?$|^Task completed\.?$", re.I), lambda m: "O Claude terminou."),
]


def aviso_em_portugues(msg: str) -> str:
    """O aviso traduzido; um aviso em inglês desconhecido não é falado (sairia ininteligível)."""
    if not msg:
        return ""
    for padrao, traduz in _AVISOS:
        m = padrao.match(msg)
        if m:
            return traduz(m)
    from ermis_voz.pensamento import em_ingles

    return "" if em_ingles(msg) else msg


HOOKS = {
    "session-start": _session_start,
    "user-prompt-submit": _user_prompt_submit,
    "post-tool-use": _post_tool_use,
    "stop": _stop,
    "notification": _notification,
}


def main(evento: str) -> int:
    try:
        raw = sys.stdin.read()
        entrada = json.loads(raw) if raw.strip() else {}
    except ValueError:
        entrada = {}
    fn = HOOKS.get(evento)
    if fn is None:
        return 0
    try:
        asyncio.run(fn(entrada))
    except Exception as exc:  # noqa: BLE001 — um hook nunca quebra a sessão
        sys.stderr.write(f"ermis-voz hook {evento}: {exc}\n")
    return 0
