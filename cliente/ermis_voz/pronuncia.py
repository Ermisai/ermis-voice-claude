"""O texto que vai para a voz: limpo para fala (sem código, markdown nem URLs), números e símbolos por extenso e
termos de programação com a pronúncia de um brasileiro. A Voice API recebe o texto já pronto."""

from __future__ import annotations

import re

from ermis_voz.fala import normalizar, soletrar_siglas
from ermis_voz.falavel import estilo_falado
from ermis_voz.pronuncia_motor import LEXICON_PT_BR, Lexicon

# Termos de programação para o TTS de 24 camadas. Não medidos como os do motor (scripts/bench/tts_wer.py): o
# modelo grande já diz muito termo em inglês certo e uma grafia pode piorar. Medir e podar.
LEXICO_DEV: dict[str, str] = {
    "json": "jêison",
    "api": "a pê í",
    "apis": "a pê ís",
    "readme": "ríd mi",
    "pytest": "pai teste",
    "github": "guit rób",
    "git": "guit",
    "npm": "ene pê eme",
    "typescript": "táipe script",
    "javascript": "java script",
    "kubectl": "cube control",
    "yaml": "iâmel",
    "url": "u érre éle",
    "cli": "cê éle í",
    "mcp": "ême cê pê",
    "ci": "cê í",
    "pr": "pê érre",
    "prs": "pê érres",
    "sql": "ésse quê éle",
    "deploy": "diplói",
    "commit": "comít",
    "commits": "comíts",
    "branch": "brêntch",
    "merge": "mêrdj",
    "push": "puch",
    "claude": "clód",
    "vcpu": "vê cê pê u",  # 04/11: "vCPUs" ia cru para o TTS
    "vcpus": "vê cê pê us",
    # ida e volta (tests/ida_e_volta.py): "megabytes" voltava "megabits", "gigabytes" voltava "gigates"
    "bytes": "báites", "byte": "báite", "quilobytes": "quilobáites", "quilobyte": "quilobáite",
    "megabytes": "megabáites", "megabyte": "megabáite", "gigabytes": "gigabáites", "gigabyte": "gigabáite",
    "terabytes": "terabáites", "terabyte": "terabáite",
    "ms": "ême ésse",  # o que sobra de "ms" (num identificador): depois de um número já é "milissegundos"
}

_FENCE = re.compile(r"```.*?(```|$)", re.DOTALL)
_INLINE = re.compile(r"`([^`]*)`")
_URL = re.compile(r"https?://\S+")
_MD = re.compile(r"[*_#>|~]+")
_EXT = re.compile(r"(?<=\w)\.(py|js|ts|tsx|jsx|json|md|yaml|yml|toml|txt|html|css|sh|sql|csv)\b", re.IGNORECASE)


def para_fala(texto: str) -> str:
    """O que o TTS deve ler: sem blocos de código, markdown nem URLs; números, unidades, símbolos e código
    por extenso (fala.normalizar); extensões ditas ("ponto py")."""
    texto = _FENCE.sub(". Tem código na tela. ", texto)
    texto = _INLINE.sub(r"\1", texto)
    texto = _URL.sub(" o link ", texto)
    # markdown: ênfase, títulos e citações no começo da linha, tabelas; ">=" e "->" ficam para o normalizador
    texto = re.sub(r"(?m)\*{1,3}|^\s*(?:#{1,6}|>+)\s*|(?<!\w)\|(?!\w)|(?<=\s)_(?=\S)|(?<=\S)_(?=\s)", " ", texto)
    texto = estilo_falado(texto)  # frases inteiras e curtas, apartes entre vírgulas (falavel.py)
    texto = _EXT.sub(lambda m: " ponto " + m.group(1).lower(), texto)
    texto = normalizar(texto)
    texto = re.sub(r"(?<=\w)/(?=\w)", " barra ", texto)
    return " ".join(texto.split())


_LEXICO = Lexicon.load(base={**LEXICON_PT_BR, **LEXICO_DEV})


def preparar(texto: str) -> str:
    """O que a voz deve dizer, pronto para o ``speak`` da Voice API."""
    return soletrar_siglas(_LEXICO(para_fala(texto)))
