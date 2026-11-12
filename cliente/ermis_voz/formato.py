"""Como a fala chega ao Claude: o bloco [fala], com as alternativas e a dúvida só quando há dúvida de verdade."""

from __future__ import annotations


def bloco_fala(fala: dict | None) -> str:
    if not fala:
        return ""
    linhas = [f"[fala] {fala.get('texto') or ''}".rstrip()]
    if fala.get("cru"):
        linhas.append(f"[ouvido cru] {fala['cru']}")
    if fala.get("alternativas"):
        linhas.append("[alternativas] " + " | ".join(f'"{a}"' for a in fala["alternativas"]))
    if fala.get("incerto"):
        linhas.append("[incerto] " + "; ".join(fala["incerto"]))
    return "\n".join(linhas)


def resultado_conversar(res: dict) -> str:
    if not res.get("ok"):
        return f"[erro de voz] {res.get('erro') or 'falhou'}"
    partes: list[str] = []
    for antes in res.get("antes") or []:
        partes.append("[dito antes, enquanto você trabalhava]\n" + bloco_fala(antes))
    barge = res.get("interrompido")
    if barge:
        segundos = (barge.get("tocado_ms") or 0) / 1000
        partes.append(f"[interrompeu] a pessoa falou por cima depois de ~{segundos:.1f} s da sua fala; "
                      "o resto não foi ouvido")
    if res.get("descartado"):
        partes.append("[não falado] a fila de voz estava cheia (outras janelas do Claude falando); a pessoa não ouviu")
    if "fala" in res:
        fala = res.get("fala")
        if fala:
            partes.append(bloco_fala(fala))
        else:
            partes.append(f"[silêncio] ninguém falou em {int(res.get('timeout_s') or 0)} s. Não invente uma resposta.")
    return "\n\n".join(partes) or "[ok] falado"


def contexto_pendentes(falas: list[dict]) -> str:
    if not falas:
        return ""
    corpo = "\n\n".join(bloco_fala(f) for f in falas)
    return (
        "[voz] Enquanto você trabalhava, a pessoa disse por voz (trate como mensagem dela; se ela pediu para parar, "
        "esperar ou mudar de rumo, faça isso agora):\n" + corpo
    )
