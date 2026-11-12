"""Servidor MCP (stdio): as ferramentas de voz que o Claude chama. Fala com o daemon (e o sobe, se preciso)."""

from __future__ import annotations

try:  # mcp 2.x
    from mcp.server.mcpserver import MCPServer as FastMCP
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP

import os

from ermis_voz.cli import garantir_daemon
from ermis_voz.daemon import pedir
from ermis_voz.formato import bloco_fala, resultado_conversar

INSTRUCOES = """\
Voz em português (Ermis Voz). A pessoa fala, e o que ela disse chega como [fala]. É reconhecimento de voz: termos
técnicos podem vir escritos como soam ("pai teste" = pytest, "ponto pai" = .py) e a pontuação é aproximada. Entenda
pelo contexto da conversa e pelos nomes que existem no projeto; [alternativas] e [incerto] aparecem quando o áudio
deixou dúvida de verdade. Quando você corrigir algo que mude o sentido, comece a resposta falada com
"Entendi: <o que entendeu>". Se a dúvida mexer numa ação destrutiva (apagar, push, migrar, deploy), confirme antes.
Fale curto: uma ou duas frases por vez, sem código, sem listas longas, sem ler caminhos inteiros; o detalhe fica na
tela. Uma pergunta por vez. Nunca invente uma resposta quando vier [silêncio].
"""

mcp = FastMCP("ermis-voz", instructions=INSTRUCOES)

# a janela do Claude que abriu este MCP: a fila do daemon não deixa uma janela cortar a fala de outra
ORIGEM = f"pid{os.getppid()}"


def _termos(correcoes: list[str] | None) -> list[tuple[str, str]]:
    pares = []
    for item in correcoes or []:
        if "=>" in item:
            ouvido, entendido = (p.strip() for p in item.split("=>", 1))
            if ouvido and entendido and len(ouvido) <= 60:
                pares.append((ouvido, entendido))
    return pares


async def _aprender(correcoes: list[str] | None) -> None:
    for ouvido, entendido in _termos(correcoes):
        await pedir({"cmd": "aprendido", "ouvido": ouvido, "entendido": entendido}, timeout=10)


@mcp.tool()
async def conversar(
    mensagem: str = "",
    esperar_resposta: bool = True,
    paciencia: str = "",
    correcoes: list[str] | None = None,
) -> str:
    """Fala ``mensagem`` em voz alta (curta, sem código) e escuta a resposta da pessoa, que volta como [fala].

    - ``esperar_resposta=False``: só fala (para narrar enquanto trabalha; use junto com as outras ferramentas).
    - ``paciencia``: "longa" quando a pessoa vai ditar ou explicar algo comprido; "rapida" para sim/não.
    - ``correcoes``: termos que você corrigiu na fala anterior, como "pai teste=>pytest"; o reconhecimento aprende.
    A pessoa pode interromper falando por cima: aí volta [interrompeu] e o que ela disse.
    """
    await garantir_daemon()
    await _aprender(correcoes)
    res = await pedir({"cmd": "conversar", "texto": mensagem, "esperar_resposta": esperar_resposta,
                       "paciencia": paciencia or None, "origem": ORIGEM}, timeout=1800)
    await pedir({"cmd": "nota", "kind": "mcp_conversar", "mensagem": mensagem, "correcoes": correcoes or [],
                 "resposta": res.get("fala")}, timeout=10)
    return resultado_conversar(res)


@mcp.tool()
async def falar(mensagem: str) -> str:
    """Fala ``mensagem`` sem esperar resposta e volta na hora (narração enquanto você trabalha)."""
    await garantir_daemon()
    res = await pedir({"cmd": "falar", "texto": mensagem, "esperar_fim": False, "origem": ORIGEM})
    if not res.get("ok"):
        return f"[erro de voz] {res.get('erro')}"
    if res.get("na_fila"):
        return f"[ok] na fila: outra janela do Claude está falando ({res['na_fila']} esperando)"
    return "[ok] falando"


@mcp.tool()
async def ouvir(segundos: int = 60) -> str:
    """Só escuta (sem falar) por até ``segundos``; devolve a [fala] ou [silêncio]."""
    await garantir_daemon()
    res = await pedir({"cmd": "ouvir", "timeout": segundos})
    if not res.get("ok"):
        return f"[erro de voz] {res.get('erro')}"
    return bloco_fala(res.get("fala")) or f"[silêncio] ninguém falou em {segundos} s. Não invente uma resposta."


@mcp.tool()
async def voz_status() -> str:
    """Estado da voz: conexão com a Voice API, cancelamento de eco, modo, fila e falas pendentes."""
    await garantir_daemon()
    res = await pedir({"cmd": "status"})
    return "\n".join(f"{k}: {v}" for k, v in res.items())


def main() -> None:
    mcp.run()
