"""O que o Claude pensa e faz enquanto trabalha, para falar de forma resumida.

A transcrição da sessão (JSONL do Claude Code, uma linha por bloco) traz, enquanto o turno corre:
- blocos ``thinking`` com texto: o resumo do raciocínio (em ~1/3 deles; nos outros vem vazio);
- blocos ``text`` numa mensagem que termina em ``tool_use``: o que ele diz antes de usar uma ferramenta ("Vou rodar
  os testes").
O texto final (mensagem que termina em ``end_turn``) não entra: esse é falado pelo hook Stop.
"""

from __future__ import annotations

import json
import re

_EN = {"the", "and", "to", "is", "i", "let", "need", "will", "this", "that", "with", "of", "it", "should", "now",
       "we", "user", "wants", "check", "first", "then"}
_PT = {"o", "a", "e", "de", "que", "para", "vou", "é", "um", "uma", "com", "do", "da", "os", "as", "no", "na",
       "não", "isso", "agora", "depois", "ver", "preciso"}


def em_ingles(texto: str) -> bool:
    palavras = re.findall(r"[a-zA-Zà-ú']+", texto.lower())[:40]
    en = sum(p in _EN for p in palavras)
    pt = sum(p in _PT for p in palavras)
    return en > pt


def primeira_frase(texto: str, max_chars: int = 160) -> str:
    """A primeira frase, sem código nem markdown, cortada numa vírgula ou num espaço se passar de ``max_chars``."""
    t = re.sub(r"```.*?(```|$)", " ", texto, flags=re.DOTALL)
    t = re.sub(r"`([^`]*)`", r"\1", t)
    t = re.sub(r"(?m)^\s*(?:[-*#>]+|\d+\.)\s*", "", t)
    t = re.sub(r"\*{1,3}", "", t)
    t = " ".join(t.split())
    frase = re.split(r"(?<=[.!?…])\s+", t, maxsplit=1)[0] if t else ""
    if len(frase) > max_chars:
        corte = frase[:max_chars]
        pos = max(corte.rfind(", "), corte.rfind(" — "), corte.rfind("; "))
        frase = corte[:pos] if pos > max_chars // 2 else corte[: corte.rfind(" ")] if " " in corte else corte
        frase = frase.rstrip(",;: —-") + "."
    return frase.strip()


def candidatos(linha: str, pensamento: bool = True, progresso: bool = True) -> list[tuple[str, str]]:
    """Os trechos para narrar de uma linha da transcrição: [(tipo, texto)], tipo "pensamento" ou "progresso"."""
    try:
        item = json.loads(linha)
    except ValueError:
        return []
    if item.get("type") != "assistant" or item.get("isSidechain"):
        return []  # subagentes têm a própria conversa
    msg = item.get("message") or {}
    out: list[tuple[str, str]] = []
    for bloco in msg.get("content") or []:
        if not isinstance(bloco, dict):
            continue
        if bloco.get("type") == "thinking" and pensamento:
            texto = (bloco.get("thinking") or "").strip()
            if texto:
                out.append(("pensamento", texto))
        elif bloco.get("type") == "text" and progresso and msg.get("stop_reason") == "tool_use":
            texto = (bloco.get("text") or "").strip()
            if texto:
                out.append(("progresso", texto))
    return out
