"""A palavra-chave do modo comando ("Ermis, roda os testes"): como o reconhecimento costuma escrevê-la.

A palavra é configurável (``ermis-voz palavra Jarvis``). Para ela valem, nesta ordem: as grafias listadas (para
"Ermis", as medidas; para outra, as que a pessoa acrescentar) e uma comparação aproximada da primeira palavra da fala
(até 1 letra de diferença a cada 5, sem contar um "h" no começo), nunca com palavras comuns do português.
"""

from __future__ import annotations

import re
import unicodedata

# Como o reconhecimento de fala escreve "Ermis" (medido com vozes sintéticas): quase sempre "Hermes", às vezes
# "Termes", "termis", "dermis", "érmes".
PALAVRAS_PADRAO = ["ermis", "ermes", "hermes", "hermis", "ermiz", "ermys", "irmis", "hermys", "er mis", "erms",
                   "herms", "érmis", "érmes", "êrmis", "elmis", "termes", "termis", "dermis", "dermes",
                   "herme", "herm"]  # 05/11: a Voice API escreve "Ermis." sozinho como "herme" ou "herm"
# O que a pessoa diz antes, chamando ("ei, Ermis", "ok Ermis")
_CHAMADAS = r"(?:(?:oh|ei|ey|hey|oi|ok|okay|alo|alô|e ai|e aí)[\s,!.]+)?"
# "Ô Ermis, ..." só com pontuação depois: sem o acento é "o", e "O Ermis falou" (falando dele) não é uma chamada
_CHAMADA_O = r"(?:[oó]\s+)"
# Nunca a palavra-chave por aproximação: palavras comuns que ficam a 1 letra de muitos nomes
_COMUNS = {"mesmo", "temos", "termos", "ermos", "vamos", "isso", "esse", "essa", "este", "esta", "entao", "agora",
           "depois", "porque", "quando", "onde", "como", "quero", "queria", "pode", "faz", "roda", "abre", "mostra",
           "olha", "tipo", "certo", "beleza", "obrigado", "obrigada", "nossa", "hoje", "ontem", "amanha", "tudo",
           "nada", "ainda", "sempre", "nunca", "muito", "pouco", "outro", "outra", "meses", "mesa", "missa", "masis"}


def _plain(texto: str) -> str:
    texto = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in texto if unicodedata.category(c) != "Mn")


def variantes(palavra: str, extras: list[str] | None = None) -> list[str]:
    """As grafias aceitas para ``palavra``: ela mesma, as medidas (se for "Ermis") e as que a pessoa acrescentou."""
    base = [palavra] if palavra else []
    if _plain(palavra or "ermis") == "ermis":
        base += PALAVRAS_PADRAO
    return list(dict.fromkeys(p for p in base + list(extras or []) if p and p.strip()))


def _padrao(palavras: list[str]) -> re.Pattern:
    alts = "|".join(sorted({re.escape(_plain(p)).replace(r"\ ", r"\s*") for p in palavras if p}, key=len, reverse=True))
    return re.compile(
        rf"^\W*(?:{_plain(_CHAMADAS)}({alts})\b[\s,.!:;?-]*|{_CHAMADA_O}({alts})(?:\s*[,!.:;]+\s*|\s*$))",
        re.IGNORECASE,
    )


def _distancia(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _parecida(candidata: str, palavra: str) -> bool:
    c, p = candidata.lstrip("h"), _plain(palavra).replace(" ", "").lstrip("h")
    if len(p) < 4 or candidata in _COMUNS or not c:
        return False
    return _distancia(c, p) <= max(1, len(p) // 5) and c[0] == p[0]


_INICIO = re.compile(rf"^\W*{_plain(_CHAMADAS)}([a-z]+)(\s+[a-z]+)?\b[\s,.!:;?-]*")


def tirar_palavra(texto: str, palavras: list[str] | None = None) -> str | None:
    """O pedido sem a palavra-chave ("Ermis, roda os testes." -> "roda os testes."), "" se só a chamaram, ou None se
    a fala não começa com ela."""
    if not texto:
        return None
    palavras = palavras or PALAVRAS_PADRAO
    texto = unicodedata.normalize("NFC", texto)
    plain = _plain(texto)  # em NFC, tirar os acentos mantém o comprimento: as posições valem no original
    fim = None
    m = _padrao(palavras).match(plain)
    if m:
        fim = m.end()
    else:
        # aproximada: a primeira palavra (ou as duas primeiras juntas) perto da palavra-chave principal, e só como
        # chamada, com pontuação depois ("Jarbis, abre ..."): "Atrás da porta" não é "Atlas"
        m2 = _INICIO.match(plain)
        if m2:
            primeira, segunda = m2.group(1), (m2.group(2) or "").strip()
            principal = palavras[0]
            if _parecida(primeira, principal) and _chamada(plain, m2.end(1)):
                fim = _depois_da_palavra(plain, m2.end(1))
            elif segunda and _parecida(primeira + segunda, principal) and _chamada(plain, m2.end(2)):
                fim = _depois_da_palavra(plain, m2.end(2))
    if fim is None:
        return None
    resto = (texto if len(plain) == len(texto) else plain)[fim:].strip()
    return resto[:1].upper() + resto[1:] if resto else ""


def _chamada(plain: str, pos: int) -> bool:
    """Depois da palavra vem pontuação (vocativo) ou nada mais."""
    return bool(re.compile(r"\s*(?:[,!.:;?]|$)").match(plain, pos))


def _depois_da_palavra(plain: str, pos: int) -> int:
    m = re.compile(r"[\s,.!:;?-]*").match(plain, pos)
    return m.end() if m else pos


def comeca_com_palavra(texto: str, palavras: list[str] | None = None) -> bool:
    return tirar_palavra(texto, palavras) is not None
