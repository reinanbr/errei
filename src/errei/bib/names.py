"""Nomes de autores no formato BibTeX."""

from __future__ import annotations

import re
from dataclasses import dataclass

from errei.bib.parser import plain

VON = {
    "da",
    "de",
    "do",
    "das",
    "dos",
    "di",
    "du",
    "van",
    "von",
    "der",
    "den",
    "la",
    "le",
    "del",
    "della",
    "e",
    "y",
    "ten",
    "ter",
    "zu",
}
SUFFIX = {
    "jr",
    "jr.",
    "júnior",
    "junior",
    "filho",
    "neto",
    "sobrinho",
    "segundo",
    "ii",
    "iii",
    "iv",
}


@dataclass(frozen=True, slots=True)
class Name:
    first: str
    von: str
    last: str
    jr: str
    raw: str
    literal: bool  # nome protegido por chaves, p.ex. instituição {IBGE}

    @property
    def surname(self) -> str:
        return self.last


def _split_top(s: str, sep_re: str) -> list[str]:
    """Divide em ``sep_re`` apenas no nível 0 de chaves."""
    out: list[str] = []
    depth = 0
    last = 0
    i = 0
    pattern = re.compile(sep_re, re.IGNORECASE)
    while i < len(s):
        c = s[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        elif depth == 0:
            m = pattern.match(s, i)
            if m:
                out.append(s[last:i])
                i = m.end()
                last = i
                continue
        i += 1
    out.append(s[last:])
    return [p.strip() for p in out if p.strip()]


def split_authors(value: str) -> list[str]:
    return _split_top(value, r"\s+and\s+")


def parse_name(raw: str) -> Name:
    raw = raw.strip()
    if raw.startswith("{") and raw.endswith("}") and raw.count("{") == 1:
        return Name("", "", plain(raw), "", raw, True)
    parts = _split_top(raw, r",")
    if len(parts) >= 2:
        last_part = parts[0]
        first = plain(parts[-1])
        jr = plain(parts[1]) if len(parts) == 3 else ""
        words = last_part.split()
        von_words = []
        while len(words) > 1 and words[0].lower() in VON:
            von_words.append(words.pop(0))
        return Name(first, plain(" ".join(von_words)), plain(" ".join(words)), jr, raw, False)
    words = _split_top(raw, r"\s+")
    if len(words) == 1:
        return Name("", "", plain(words[0]), "", raw, False)
    jr = ""
    if words[-1].lower().strip(".") in {s.strip(".") for s in SUFFIX} and len(words) > 2:
        jr = words.pop()
    # sobrenome = última palavra (+ partículas imediatamente antes)
    last = [words.pop()]
    von: list[str] = []
    while len(words) > 1 and words[-1].lower() in VON:
        von.insert(0, words.pop())
    return Name(
        plain(" ".join(words)), plain(" ".join(von)), plain(" ".join(last)), plain(jr), raw, False
    )


def parse_authors(value: str) -> list[Name]:
    return [parse_name(a) for a in split_authors(value) if a.lower() != "others"]
