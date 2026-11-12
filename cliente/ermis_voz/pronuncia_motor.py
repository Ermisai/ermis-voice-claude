"""Pronunciation lexicon for the TTS: foreign terms and acronyms respelled the way a Brazilian says them.

The TTS models read Portuguese spelling; "login" comes out as "lojinho" and "upgrade" as "Pradi".
Right before synthesis, whole words are replaced, case-insensitively and longest term first, with a
respelling. Only the audio changes: transcripts and history keep the original text. ``TTS_LEXICON_PATH`` (a JSON object ``{"term": "respelling"}``) adds or
overrides entries per deployment, e.g. product and brand names; an empty respelling removes a term.
The latency model (``TTS_LATENCY_MODEL``) gets extra entries (``LEXICON_FAST_PT_BR``).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# Respellings for the Portuguese TTS models, kept only where the 76-line test (scripts/bench/tts_wer.py)
# showed a gain: the 24-layer model already says most English terms right and a respelling can make it
# worse ("cashback", "app"), so LEXICON_PT_BR is for every model and LEXICON_FAST_PT_BR only for the
# latency model (TTS_LATENCY_MODEL, the faster one), which gets most of them wrong.
# Measured and dropped (no gain or worse on both): premium, zoom, check-in, bug, notebook, pdf.
LEXICON_PT_BR: dict[str, str] = {
    "login": "lóguin",
    "logout": "lógaut",
    "link": "linque",
    "links": "linques",
    "e-mail": "imeil",
    "e-mails": "imeils",
    "email": "imeil",
    "emails": "imeils",
    "online": "onláine",
    "offline": "ofláine",
    "streaming": "istrímin",
    "webinar": "uebinár",
    "wi-fi": "uaifai",
    "wifi": "uaifai",
    "bluetooth": "blutúfi",
    "whatsapp": "uótsap",
    "software": "sóftuer",
    "update": "âpdeite",
    "backup": "béquiâp",
    "reset": "rissét",
    "mesh": "méche",
    "delivery": "delíveri",
    "feedback": "fídibéque",
    "voucher": "váucher",
    "black friday": "bléque fráidei",
    "home office": "rôme ófis",
    "ticket": "tíquete",
    "tickets": "tíquetes",
    "status": "istátus",
    "tracking": "tréquin",
    "business": "bísnes",
    # Italian "zz" read as "z": "pizaria". Measured (TTS -> precise STT, 24 layers, 2 voices x 2): 4/4 right
    # respelled, 1/4 as written (2026-10-22)
    "pizza": "pítsa",
    "pizzas": "pítsas",
    "pizzaria": "pítsaria",
    "pizzarias": "pítsarias",
}

# Only for the latency model: it says these wrong, the 24-layer model says them right as written
LEXICON_FAST_PT_BR: dict[str, str] = {
    "app": "ép",
    "apps": "éps",
    "cashback": "quéchibéque",
    "upgrade": "âpgreide",
    "downgrade": "dáungreide",
    "check-out": "checáute",
    "qr code": "quiuár côudi",
    "google meet": "gúgou mít",
    "self-service": "sélfi sérvis",
    "smartphone": "ismártifone",
    "site": "sáite",
    "sites": "sáites",
    "download": "daunlôudi",
    "upload": "âplôudi",
    "chat": "chét",
    "chatbot": "chétbóti",
    "marketing": "márquetin",
    "design": "dizáine",
    "shopping": "chópin",
    "ok": "oquêi",
    # acronyms, letter by letter ("CPF" came out "pafé")
    "cpf": "cê pê éfe",
    "cnpj": "cê ene pê jota",
    "rg": "érre gê",
    "sms": "ésse ême ésse",
}


class Lexicon:
    """Whole-word, case-insensitive replacements, longest term first ("google meet" before "google")."""

    def __init__(self, entries: dict[str, str]) -> None:
        self.entries = {k.lower(): v for k, v in entries.items() if k.strip() and v.strip()}
        terms = sorted(self.entries, key=len, reverse=True)
        # A term is a whole word: no letter or digit right before or after it (hyphens count as inside)
        self._re = (
            re.compile(r"(?<![\w-])(" + "|".join(map(re.escape, terms)) + r")(?![\w-])", re.IGNORECASE)
            if terms
            else None
        )

    def __call__(self, text: str) -> str:
        if not self._re or not text:
            return text
        return self._re.sub(lambda m: self.entries[m.group(1).lower()], text)

    @classmethod
    def load(cls, path: str = "", base: dict[str, str] | None = None, fast: bool = False) -> Lexicon:
        """The built-in lexicon (``fast``: with the latency model's extra entries) plus ``path``
        (JSON ``{"term": "respelling"}``; ``""`` removes a term)."""
        entries = dict(LEXICON_PT_BR if base is None else base)
        if fast and base is None:
            entries.update(LEXICON_FAST_PT_BR)
        if path:
            extra = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
            if not isinstance(extra, dict):
                raise ValueError(f"TTS_LEXICON_PATH must hold a JSON object, got {type(extra).__name__}")
            for term, respelling in extra.items():
                entries[str(term).lower()] = str(respelling)
        return cls(entries)
