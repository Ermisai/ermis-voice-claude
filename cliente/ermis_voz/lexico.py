"""Termos do projeto para a correção do STT: nomes de arquivo, dependências e os identificadores mais usados."""

from __future__ import annotations

import json
import re
import subprocess
from collections import Counter
from pathlib import Path

MAX_TERMOS = 200
_IDENT = re.compile(r"\b([A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+|[a-z]+(?:[A-Z][a-z0-9]+)+|[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+)\b")
_CODE_EXT = {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".java", ".kt", ".rb", ".php", ".cs", ".swift"}


def _git_files(root: Path) -> list[str]:
    try:
        out = subprocess.run(["git", "-C", str(root), "ls-files"], capture_output=True, text=True, timeout=5)
        return [line for line in out.stdout.splitlines() if line] if out.returncode == 0 else []
    except (OSError, subprocess.SubprocessError):
        return []


def _deps(root: Path) -> list[str]:
    names: list[str] = []
    pkg = root / "package.json"
    if pkg.exists():
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
            for key in ("dependencies", "devDependencies"):
                names += list((data.get(key) or {}).keys())
        except ValueError:
            pass
    py = root / "pyproject.toml"
    if py.exists():
        text = py.read_text(encoding="utf-8", errors="ignore")
        names += re.findall(r'^\s*"([A-Za-z0-9_.\-]+)\s*[<>=~!\[;"]', text, flags=re.MULTILINE)
    return [n.split("/")[-1] for n in names]


def termos_do_projeto(root: str | Path = ".") -> list[str]:
    root = Path(root).resolve()
    files = _git_files(root)
    termos: list[str] = []
    seen: set[str] = set()

    def add(t: str) -> None:
        key = t.lower()
        if 3 <= len(t) <= 40 and key not in seen:
            seen.add(key)
            termos.append(t)

    # arquivos mais rasos primeiro (os que a pessoa mais cita)
    for f in sorted(files, key=lambda p: (p.count("/"), p))[:120]:
        name = Path(f).name
        add(name)
        if "." in name:
            add(name.rsplit(".", 1)[0])
    for dep in _deps(root)[:40]:
        add(dep)
    counts: Counter[str] = Counter()
    for f in files[:400]:
        p = root / f
        if p.suffix in _CODE_EXT and p.is_file() and p.stat().st_size < 400_000:
            try:
                counts.update(_IDENT.findall(p.read_text(encoding="utf-8", errors="ignore")))
            except OSError:
                continue
    for ident, _ in counts.most_common(150):
        add(ident)
    return termos[:MAX_TERMOS]
