"""Texto para ser FALADO: frases inteiras e curtas, cada uma sintetizada de uma vez.

A voz sintética dá a cada pedaço a entonação de uma frase que termina. A síntese corta em 280
caracteres e, quando uma frase passa disso, corta numa vírgula ou num espaço: o pedaço sai "terminado" no meio da
oração ("frases meio cortadas", 04/11). Aqui:

1. ``estilo_falado`` (texto cru): parênteses viram um aparte entre vírgulas; uma frase longa vira frases completas,
   cortada onde a fala corta ("…, mas …" -> "… Mas …"; ";", ":" e "—" viram ponto; por último, uma vírgula), perto
   do meio;
2. ``frases_para_tts`` (texto já normalizado): uma frase inteira por pedaço (ou duas curtas juntas), nunca um pedaço
   de frase; só uma frase sem nenhum ponto de corte, enorme, é dividida (e então numa vírgula).
"""

from __future__ import annotations

import re

FRASE_MAX = 170  # caracteres do texto cru: ~10-12 s de fala, o que uma frase dita aguenta
PEDACO_ALVO = 220  # do texto normalizado: duas frases curtas juntas no mesmo pedaço
PEDACO_MAX = 300

_FIM = re.compile(r"(?<=[.!?…])\s+")
# onde uma frase longa pode virar duas, do corte mais natural para o menos: (padrão, o que entra no lugar)
_CORTES = [
    (re.compile(r"\s+[—–]\s+"), ". "),
    (re.compile(r";\s+"), ". "),
    (re.compile(r":\s+(?=\S+\s+\S+\s+\S+)"), ". "),  # ":" seguido de uma oração (não "Resultado: 3")
    (re.compile(r",\s+(?=(?:mas|porém|porque|pois|então|enquanto|embora|só que|já que)\s)", re.I), ". "),
    (re.compile(r",\s+(?=e\s)", re.I), ". "),
    # uma vírgula qualquer, mas não antes de uma oração que depende da anterior ("…, que agora recebe" viraria uma
    # frase começando com "Que")
    (re.compile(r",\s+(?!(?:que|o que|a que|onde|cujo|cuja|quando|como|qual|os quais|as quais|a qual|o qual)\b)",
                re.I), ". "),
]


def _maiuscula(s: str) -> str:
    return s[:1].upper() + s[1:] if s else s


def _fechar(s: str) -> str:
    s = s.strip().rstrip(",;:—– ")
    return s if not s or s[-1] in ".!?…" else s + "."


def _quebrar(frase: str, maximo: int) -> list[str]:
    if len(frase) <= maximo:
        return [frase]
    meio = len(frase) / 2
    for padrao, troca in _CORTES:
        candidatos = [m for m in padrao.finditer(frase) if 0.25 * len(frase) <= m.start() <= 0.8 * len(frase)]
        if candidatos:
            m = min(candidatos, key=lambda c: abs(c.start() - meio))
            antes = _fechar(frase[: m.start()])
            depois = _maiuscula(frase[m.end():].strip())
            return _quebrar(antes, maximo) + _quebrar(depois, maximo)
    return [frase]  # sem corte natural: fica inteira (o TTS aguenta; melhor que cortar no meio de uma oração)


def estilo_falado(texto: str, frase_max: int = FRASE_MAX) -> str:
    t = " ".join(texto.split())
    # (aparte) -> , aparte,  — e limpa a vírgula que sobra antes de pontuação
    t = re.sub(r"\s*\(([^()]{1,120})\)", r", \1,", t)
    t = re.sub(r"[,;:]\s*([,.;:!?])", r"\1", t)  # pontuação dupla (":," ",." ":.") fica a mais forte
    t = re.sub(r"(?:^|(?<=\s))[.,]\s+", "", t)  # ponto ou vírgula soltos no começo
    t = re.sub(r"\.{2,}(?!\.)", ".", t) if "..." not in t else t
    frases: list[str] = []
    for frase in _FIM.split(t):
        if frase.strip():
            frases += [_maiuscula(_fechar(f)) for f in _quebrar(frase.strip(), frase_max)]
    return " ".join(frases)


def frases_para_tts(texto: str, alvo: int = PEDACO_ALVO, maximo: int = PEDACO_MAX) -> list[str]:
    frases = [f.strip() for f in _FIM.split(" ".join(texto.split())) if f.strip()]
    pedacos: list[str] = []
    atual = ""
    for f in frases:
        if len(f) > maximo:  # uma frase enorme, sem ponto de corte: em vírgulas, como último recurso
            if atual:
                pedacos.append(atual)
                atual = ""
            pedacos += [_fechar(p) for p in _quebrar(f, maximo)]
            continue
        if atual and len(atual) + 1 + len(f) > alvo:
            pedacos.append(atual)
            atual = f
        else:
            atual = f"{atual} {f}".strip()
    if atual:
        pedacos.append(atual)
    return pedacos
