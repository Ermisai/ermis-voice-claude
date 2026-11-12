"""Leitura de uma resposta do Claude: inteira em partes quando é curta, resumida quando é longa, nunca mais que o teto.

Medido nas gravações (31/10 a 03/11): o TTS fala ~16,6 caracteres por segundo do texto normalizado (p10 12,9);
a conta usa 15/s. Padrão: até 45 s lê inteiro; acima, resume para ~60 s; teto de 120 s.

O resumo é do Claude Haiku 5.5 pela API (``ANTHROPIC_API_KEY``; ~1.500 tokens por resposta longa, ~US$ 0,0002) e
sai em português mesmo quando a resposta está em inglês. Sem a chave, um resumo extrativo: a primeira frase de cada
parte, até o tamanho. Partes de até ~450 caracteres, quebradas em parágrafo ou frase: o primeiro áudio sai logo e a
pessoa pode cortar entre elas.
"""

from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass, field

log = logging.getLogger("ermis_voz.leitura")

CARACTERES_POR_S = 15.0
PARTE_MAX = 450
FIM_RESUMO = "Os detalhes estão na tela."
FIM_CORTE = "O resto está na tela."

_PROMPT = (
    "Você resume, para ser OUVIDO em voz alta, a resposta que um assistente de programação acabou de dar. "
    "Escreva em português do Brasil, em texto corrido, frases curtas, sem markdown, sem listas, sem código, sem URLs "
    "e sem caminhos longos. Diga o resultado e o que importa para a pessoa decidir o próximo passo; mantenha números, "
    "nomes de arquivos curtos e decisões. Não comece com \"A resposta\" nem com \"O assistente\": fale como se fosse "
    "ele, na primeira pessoa. No máximo {palavras} palavras."
)


@dataclass
class Leitura:
    partes: list[str]
    info: dict = field(default_factory=dict)


def limpar(texto: str) -> str:
    """O que se lê de uma resposta: sem blocos de código e tabelas (ficam na tela), sem marcas de markdown."""
    t = texto.replace("\r\n", "\n")
    t, n_codigo = re.subn(r"```.*?(```|$)", "\n\n(Tem código na tela.)\n\n", t, flags=re.DOTALL)
    linhas, tabela = [], False
    for linha in t.split("\n"):
        if re.match(r"^\s*\|.*\|\s*$", linha):  # tabela markdown
            if not tabela:
                linhas.append("(Tem uma tabela na tela.)")
            tabela = True
            continue
        tabela = False
        if re.match(r"^\s*#{1,6}\s", linha):  # título: um parágrafo, terminado em ponto
            titulo = re.sub(r"^\s*#{1,6}\s*", "", linha).strip()
            linhas += ["", titulo if titulo.endswith((".", ":", "?", "!")) else f"{titulo}.", ""]
            continue
        if re.match(r"^\s*(?:[-*+]|\d+[.)])\s+", linha):  # item de lista: um parágrafo
            item = re.sub(r"^\s*(?:[-*+]|\d+[.)])\s+", "", linha).strip()
            linhas += ["", item]
            continue
        linhas.append(linha)
    t = "\n".join(linhas)
    t = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", t)  # [texto](link)
    t = re.sub(r"https?://\S+", "o link", t)
    t = re.sub(r"\*{1,3}|__", "", t)
    # vários avisos de código seguidos viram um só
    t = re.sub(r"(\(Tem código na tela\.\)\s*){2,}", "(Tem código na tela.)\n\n", t)
    return t.strip()


def _frases(texto: str) -> list[str]:
    return [f for f in re.split(r"(?<=[.!?…])\s+", " ".join(texto.split())) if f]


def partes(texto: str, maximo: int = PARTE_MAX) -> list[str]:
    """Quebra em parágrafos; junta os curtos e corta os longos em frases, até ``maximo`` caracteres por parte."""
    out: list[str] = []
    atual = ""
    for paragrafo in re.split(r"\n\s*\n", texto):
        paragrafo = " ".join(paragrafo.split())
        if not paragrafo:
            continue
        pedacos = [paragrafo] if len(paragrafo) <= maximo else _frases(paragrafo)
        for p in pedacos:
            if len(p) > maximo:  # frase enorme: corta no espaço
                while len(p) > maximo:
                    corte = p.rfind(" ", 0, maximo)
                    corte = corte if corte > maximo // 2 else maximo
                    out.append(p[:corte].strip())
                    p = p[corte:].strip()
            if atual and len(atual) + 1 + len(p) > maximo:
                out.append(atual)
                atual = p
            else:
                atual = f"{atual} {p}".strip()
    if atual:
        out.append(atual)
    return out


def extrativo(texto: str, alvo_chars: int) -> str:
    """Sem modelo: a primeira frase de cada parágrafo, até ``alvo_chars``."""
    escolhidas: list[str] = []
    total = 0
    for paragrafo in re.split(r"\n\s*\n", texto):
        frases = _frases(paragrafo)
        # a primeira frase que diz algo: não um aviso de código, não um título solto, não "Veja:" antes de uma lista
        f = next((x for x in frases if not x.startswith("(Tem ") and len(x) >= 30 and not x.rstrip().endswith(":")),
                 None)
        if f is None:
            continue
        if total + len(f) > alvo_chars and escolhidas:
            break
        escolhidas.append(f)
        total += len(f) + 1
    return " ".join(escolhidas)


def _abertura(limpo: str, resumo_s: float, falado) -> str | None:
    """O primeiro parágrafo, quando serve de resumo: frases inteiras, sem código, e cabe em ``resumo_s``. No modo
    leitura o Claude é instruído a abrir toda resposta assim (hooks.INSTRUCOES_LEITURA)."""
    primeiro = next((" ".join(p.split()) for p in re.split(r"\n\s*\n", limpo) if p.strip()), "")
    if not primeiro or primeiro.startswith("(Tem ") or len(primeiro) < 40:
        return None
    if not primeiro.rstrip().endswith((".", "!", "?")):
        return None  # título ou frase que continua numa lista
    if segundos(primeiro, falado) > resumo_s:
        return None
    return primeiro


def segundos(texto: str, falado=None) -> float:
    """Quanto o TTS leva para dizer ``texto`` (pelo texto já normalizado, quando ``falado`` é dado)."""
    return len(falado(texto) if falado else texto) / CARACTERES_POR_S


async def resumir_com_modelo(texto: str, alvo_s: float) -> tuple[str | None, dict]:
    """Resumo pelo Claude Haiku 5.5. ``None`` sem a chave ou se a chamada falhar."""
    chave = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("VOZ_ANTHROPIC_KEY")
    modelo = os.environ.get("VOZ_RESUMO_MODELO", "claude-haiku-5-5")
    if not chave:
        return None, {"resumo": "extrativo", "motivo": "sem ANTHROPIC_API_KEY"}
    palavras = max(30, int(alvo_s * 2.4))  # ~2,4 palavras por segundo de fala
    t0 = time.perf_counter()
    try:
        from anthropic import AsyncAnthropic

        cliente = AsyncAnthropic(api_key=chave, timeout=15.0, max_retries=1)
        resp = await cliente.messages.create(
            model=modelo,
            max_tokens=1024,
            thinking={"type": "disabled"},
            output_config={"effort": "low"},
            system=_PROMPT.format(palavras=palavras),
            messages=[{"role": "user", "content": texto[:60000]}],
        )
        if resp.stop_reason == "refusal":
            return None, {"resumo": "extrativo", "motivo": "recusa do modelo"}
        saida = "".join(b.text for b in resp.content if b.type == "text").strip()
        uso = {"entrada": resp.usage.input_tokens, "saida": resp.usage.output_tokens}
        return (saida or None), {"resumo": modelo, "ms": round((time.perf_counter() - t0) * 1000), "tokens": uso}
    except Exception as exc:  # noqa: BLE001 — sem o resumo do modelo, fica o extrativo
        log.warning("resumo pelo modelo falhou: %s", exc)
        return None, {"resumo": "extrativo", "motivo": f"erro: {type(exc).__name__}"}


async def preparar(texto: str, falado, inteiro_ate_s: float = 45.0, max_s: float = 120.0,
                   resumo_s: float = 60.0) -> Leitura:
    """As partes a falar. ``falado`` é a normalização do TTS (para medir o tempo do que de fato será dito)."""
    from ermis_voz.pensamento import em_ingles

    limpo = limpar(texto)
    total_s = segundos(limpo, falado)
    info: dict = {"chars": len(texto), "estimado_s": round(total_s, 1), "ingles": em_ingles(limpo)}
    if not limpo:
        return Leitura([], info | {"modo": "vazio"})
    abertura = _abertura(limpo, resumo_s, falado)
    if total_s <= inteiro_ate_s and not info["ingles"]:
        corpo = limpo
        info["modo"] = "inteiro"
    elif abertura and not info["ingles"]:
        # o próprio Claude abriu a resposta com o resumo (instruído no modo leitura): de graça e o melhor resumo
        corpo = f"{abertura}\n\n{FIM_RESUMO}"
        info["modo"] = "abertura"
    else:
        resumo, meta = await resumir_com_modelo(limpo, resumo_s)
        info.update(meta)
        if resumo:
            corpo = f"{resumo}\n\n{FIM_RESUMO}"
            info["modo"] = "resumo"
        elif info["ingles"]:
            corpo = "A resposta está em inglês. Está na tela."
            info["modo"] = "ingles_sem_resumo"
        else:
            corpo = f"{extrativo(limpo, int(resumo_s * CARACTERES_POR_S))}\n\n{FIM_RESUMO}"
            info["modo"] = "extrativo"
    lista = partes(corpo)
    # teto: corta nas partes e avisa
    out, acumulado = [], 0.0
    for p in lista:
        s = segundos(p, falado)
        if out and acumulado + s > max_s:
            out.append(FIM_CORTE)
            info["cortado"] = True
            break
        out.append(p)
        acumulado += s
    info["falado_s"] = round(sum(segundos(p, falado) for p in out), 1)
    info["partes"] = len(out)
    return Leitura(out, info)
