"""Correção determinística do texto ouvido (camada 1): termos de programação, extensões faladas e o léxico do projeto.

Não decide nada: só reescreve o que tem uma leitura técnica quase certa. O resto (e a dúvida) fica com o Claude da
sessão, que recebe o texto cru quando ele foi mudado. O dicionário começa curado à mão; a ideia é crescer com os
pares (ouvido -> entendido) que o cliente manda no log (``nota`` do tipo ``entendido``).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

# Como o STT costuma escrever o termo quando um brasileiro o fala -> o termo. Sem acento e em minúsculas na chave
# (a comparação tira os acentos). Frases mais longas primeiro na aplicação.
TERMOS_DEV: dict[str, str] = {
    # ferramentas e linguagens
    "pai teste": "pytest", "pai test": "pytest", "paiteste": "pytest", "pitest": "pytest",
    "paiton": "Python", "paitom": "Python", "pyton": "Python", "python": "Python",
    "guit": "git", "guiti": "git", "guite": "git",
    "guit hub": "GitHub", "guiti hub": "GitHub", "guitirrabi": "GitHub", "guit rabi": "GitHub", "github": "GitHub",
    "guit lab": "GitLab", "gitlab": "GitLab",
    "doquer": "Docker", "docker": "Docker", "doker": "Docker",
    "cubernetes": "Kubernetes", "kubernetes": "Kubernetes", "cubernetis": "Kubernetes",
    "cube control": "kubectl", "cub control": "kubectl", "cube ctl": "kubectl",
    "node": "Node", "node js": "Node.js", "nodejs": "Node.js",
    "en pê eme": "npm", "ene pe eme": "npm", "npm": "npm",
    "pi pi": "pip", "pipi": "pip",
    "iu vi": "uv",
    "tipe script": "TypeScript", "taipe script": "TypeScript", "taip script": "TypeScript", "typescript": "TypeScript",
    "java script": "JavaScript", "javascript": "JavaScript",
    "react": "React", "riact": "React", "reacti": "React",
    "use efect": "useEffect", "iuz efect": "useEffect", "use effect": "useEffect", "useefect": "useEffect",
    "use state": "useState", "iuz steite": "useState", "use steite": "useState",
    "next js": "Next.js", "nexte js": "Next.js",
    "fast api": "FastAPI", "fest api": "FastAPI", "fastapi": "FastAPI",
    "jango": "Django", "django": "Django",
    "flasque": "Flask", "flask": "Flask",
    "postgres": "Postgres", "postigres": "Postgres", "postgre": "Postgres",
    "redis": "Redis", "rédis": "Redis",
    "mongo db": "MongoDB", "mongodb": "MongoDB",
    "sequel": "SQL",
    "json": "JSON", "jason": "JSON", "jeison": "JSON", "jeisom": "JSON", "jotason": "JSON",
    "iaml": "YAML", "iamel": "YAML", "yaml": "YAML",
    "api": "API", "a pi": "API", "apí": "API",
    "endpoint": "endpoint", "end point": "endpoint", "endi point": "endpoint",
    "back end": "backend", "front end": "frontend", "full stack": "full stack",
    "deploy": "deploy", "deplói": "deploy", "diploi": "deploy",
    "commit": "commit", "comit": "commit", "comiti": "commit",
    "push": "push", "puche": "push",
    "pull request": "pull request", "pul request": "pull request", "pull requeste": "pull request",
    "merge": "merge", "merdi": "merge", "merji": "merge",
    "rebase": "rebase", "ribeize": "rebase", "ri beize": "rebase",
    "branch": "branch", "branche": "branch", "brench": "branch",
    "checkout": "checkout", "chequeaute": "checkout", "chec aute": "checkout",
    "stash": "stash", "estache": "stash", "istache": "stash",
    "diff": "diff", "dife": "diff",
    "log": "log", "logue": "log",
    "bug": "bug", "bugue": "bug",
    "debug": "debug", "debugar": "debugar", "dibugar": "debugar",
    "refactor": "refactor", "refatorar": "refatorar",
    "linter": "linter", "lintar": "lintar", "rufe": "ruff", "ruff": "ruff",
    "type hint": "type hint", "taipe hint": "type hint",
    "async": "async", "assinque": "async", "eissinque": "async", "await": "await", "euait": "await",
    "string": "string", "estringue": "string", "istring": "string",
    "array": "array", "arrei": "array", "erray": "array",
    "boolean": "boolean", "buliano": "booleano", "booleano": "booleano",
    "null": "null",
    "trú": "true", "fólse": "false", "fouls": "false",
    "self": "self", "selfe": "self",
    "import": "import", "impórte": "import",
    "lambda": "lambda", "dict": "dict", "dicte": "dict",
    "web socket": "WebSocket", "websocket": "WebSocket", "uebi socket": "WebSocket",
    "localhost": "localhost", "local host": "localhost", "local roste": "localhost",
    "readme": "README", "ridmi": "README", "read me": "README",
    "claude": "Claude", "clode": "Claude",
    "claude code": "Claude Code", "cláudio code": "Claude Code", "claudio code": "Claude Code",
    "mcp": "MCP", "eme cê pê": "MCP", "eme ce pe": "MCP",
    "hook": "hook", "ruque": "hook", "hooks": "hooks", "ruques": "hooks",
    "prompt": "prompt", "prompte": "prompt",
    "token": "token", "toquem": "token", "tokens": "tokens", "toquens": "tokens",
    "cache": "cache", "queche": "cache", "cachê": "cache",
    "script": "script", "iscripte": "script", "escripte": "script",
    "terminal": "terminal", "shell": "shell", "xel": "shell", "bash": "bash", "béche": "bash",
}

# Extensões ditas depois de "ponto"
EXTENSOES: dict[str, str] = {
    "pai": "py", "py": "py", "pi": "py",
    "jota esse": "js", "js": "js", "jota s": "js",
    "te esse": "ts", "tê esse": "ts", "ts": "ts", "te s": "ts",
    "tsx": "tsx", "te esse xis": "tsx", "jsx": "jsx",
    "json": "json", "jason": "json", "jeison": "json", "jeisom": "json",
    "md": "md", "eme de": "md", "eme dê": "md",
    "yaml": "yaml", "iaml": "yaml", "iamel": "yaml", "yml": "yml",
    "toml": "toml", "tomel": "toml", "tômel": "toml",
    "txt": "txt", "te xis te": "txt",
    "html": "html", "agá te eme ele": "html", "css": "css", "ce esse esse": "css",
    "sh": "sh", "esse agá": "sh", "env": "env", "enve": "env",
    "sql": "sql", "csv": "csv", "ce esse ve": "csv", "lock": "lock", "go": "go", "rs": "rs",
}


def _plain(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def _phrase_pattern(keys) -> re.Pattern:
    alts = sorted({re.escape(_plain(k)) for k in keys}, key=len, reverse=True)
    return re.compile(r"(?<![\w])(" + "|".join(alts) + r")(?![\w])")


_TERMOS_PLAIN = {_plain(k): v for k, v in TERMOS_DEV.items()}
_TERMOS_RE = _phrase_pattern(TERMOS_DEV)
_EXT_PLAIN = {_plain(k): v for k, v in EXTENSOES.items()}
_EXT_RE = re.compile(
    r"(?<![\w])([\w\-/]+)\s+ponto\s+(" + "|".join(sorted((re.escape(k) for k in _EXT_PLAIN), key=len, reverse=True))
    + r")(?![\w])"
)
# O STT preciso escreve "cliente. py" (ponto final + extensão): junta quando a extensão é conhecida
_EXT_SOLTA = re.compile(
    r"(?<=\w)\. (py|js|ts|tsx|jsx|json|md|yaml|yml|toml|txt|html|css|sh|sql|csv|env|lock|go|rs)(?![\w])"
)

_EXT_REPETIDA = re.compile(r"(\.([a-z]{1,5}))\s+ponto\s+\2(?![\w])", re.IGNORECASE)


@dataclass
class Correcao:
    ouvido: str
    corrigido: str
    fonte: str  # termo | extensao | projeto

    def as_dict(self) -> dict:
        return {"ouvido": self.ouvido, "corrigido": self.corrigido, "fonte": self.fonte}


@dataclass
class Corretor:
    """Aplica as três correções. ``termos_projeto`` vêm do cliente (arquivos, símbolos, dependências)."""

    termos_projeto: list[str] = field(default_factory=list)
    extras: dict[str, str] = field(default_factory=dict)  # pares aprendidos (ouvido -> entendido)

    def __post_init__(self) -> None:
        self._vocab = None
        self.set_projeto(self.termos_projeto)
        self.set_extras(self.extras)

    def set_projeto(self, termos: list[str]) -> None:
        self.termos_projeto = [t for t in termos if isinstance(t, str) and 2 <= len(t) <= 60][:200]
        self._vocab = None
        if self.termos_projeto:
            try:
                from ermis_voice.vocabulary import Vocabulary

                self._vocab = Vocabulary(self.termos_projeto)
            except Exception:  # noqa: BLE001 — sem o motor, fica sem o casamento fonético
                self._vocab = None

    def set_extras(self, extras: dict[str, str]) -> None:
        self.extras = {_plain(k): v for k, v in extras.items() if k and v}
        self._extras_re = _phrase_pattern(self.extras) if self.extras else None

    def corrigir(self, texto: str) -> tuple[str, list[Correcao]]:
        if not texto:
            return texto, []
        correcoes: list[Correcao] = []
        out = texto
        if self._extras_re is not None:
            out = self._replace(out, self._extras_re, self.extras, "aprendido", correcoes)
        out = self._extensoes(out, correcoes)
        out = self._replace(out, _TERMOS_RE, _TERMOS_PLAIN, "termo", correcoes)
        if self._vocab is not None:
            fixed, found = self._vocab.correct(out)
            for c in found:
                if c.heard != c.term:
                    correcoes.append(Correcao(c.heard, c.term, "projeto"))
            out = fixed
        return out, correcoes

    @staticmethod
    def _replace(text: str, pattern: re.Pattern, table: dict[str, str], fonte: str, out: list[Correcao]) -> str:
        # casa sobre o texto sem acento, mas troca nas mesmas posições do original (mesmo comprimento em NFC)
        plain = _plain(text)
        if len(plain) != len(text):
            plain = text.lower()  # raro (caracteres compostos): casa direto, sem tirar acento
        pieces, last = [], 0
        for m in pattern.finditer(plain):
            heard = text[m.start() : m.end()]
            new = table.get(m.group(1))
            if new is None or new == heard:
                continue
            pieces.append(text[last : m.start()])
            pieces.append(new)
            last = m.end()
            if _plain(new) != _plain(heard):
                out.append(Correcao(heard, new, fonte))
        pieces.append(text[last:])
        return "".join(pieces)

    @staticmethod
    def _extensoes(text: str, out: list[Correcao]) -> str:
        def juntar(m: re.Match) -> str:
            out.append(Correcao(m.group(0), "." + m.group(1).lower(), "extensao"))
            return "." + m.group(1).lower()

        # o vocabulary da Voice API já escreveu "daemon.py" e sobrou o "ponto py" dito: não vira "daemon.py.py"
        text = _EXT_REPETIDA.sub(lambda m: (out.append(Correcao(m.group(0), m.group(1), "extensao")), m.group(1))[1],
                                 text)
        text = _EXT_SOLTA.sub(juntar, text)
        plain = _plain(text)
        if len(plain) != len(text):
            return text
        pieces, last = [], 0
        for m in _EXT_RE.finditer(plain):
            name = text[m.start(1) : m.end(1)]
            ext = _EXT_PLAIN.get(m.group(2))
            if not ext:
                continue
            heard = text[m.start() : m.end()]
            new = f"{name}.{ext}"
            pieces.append(text[last : m.start()])
            pieces.append(new)
            last = m.end()
            out.append(Correcao(heard, new, "extensao"))
        pieces.append(text[last:])
        return "".join(pieces)
