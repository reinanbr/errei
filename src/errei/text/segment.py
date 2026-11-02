"""Segmentação de texto pt-BR: palavras e frases com offsets."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass
from functools import cache
from importlib import resources

WORD_RE = re.compile(r"[^\W\d_](?:[^\W_]|[-'’](?=[^\W\d_]))*|\d+(?:[.,]\d+)*")
ALPHA_WORD_RE = re.compile(r"[^\W\d_](?:[^\W\d_]|[-'’](?=[^\W\d_]))*")

ABBREVIATIONS = {
    "et",
    "al",
    "p",
    "pp",
    "fig",
    "figs",
    "tab",
    "eq",
    "eqs",
    "dr",
    "dra",
    "sr",
    "sra",
    "prof",
    "profa",
    "ex",
    "etc",
    "v",
    "n",
    "vol",
    "ed",
    "eds",
    "cf",
    "op",
    "cit",
    "ib",
    "id",
    "ibid",
    "aprox",
    "séc",
    "nº",
    "no",
    "num",
    "cap",
    "sec",
    "seç",
    "art",
    "inc",
    "jr",
    "vs",
    "obs",
    "i.e",
    "e.g",
    "ie",
    "eg",
    "min",
    "máx",
    "mín",
    "max",
    "s",
    "l",
    "f",
    "fl",
    "ref",
    "refs",
    "apud",
    "lat",
    "pág",
    "págs",
    "trad",
    "org",
    "orgs",
    "coord",
    "coords",
    "mr",
    "mrs",
    "ms",
}

_SENT_END = re.compile(r"[.!?…]+[\"”’)\]]*(?=\s+|$)")


@dataclass(frozen=True, slots=True)
class Span:
    start: int
    end: int
    text: str


def words(text: str) -> list[Span]:
    return [Span(m.start(), m.end(), m.group(0)) for m in WORD_RE.finditer(text)]


def alpha_words(text: str) -> list[Span]:
    return [Span(m.start(), m.end(), m.group(0)) for m in ALPHA_WORD_RE.finditer(text)]


def word_count(text: str) -> int:
    return sum(1 for _ in WORD_RE.finditer(text))


def sentences(text: str) -> list[Span]:
    """Divide em frases, tolerando abreviações, iniciais e decimais."""
    out: list[Span] = []
    start = 0
    n = len(text)
    while start < n and text[start].isspace():
        start += 1
    for m in _SENT_END.finditer(text):
        end = m.end()
        punct = m.group(0)
        if punct.startswith("."):
            before = text[start : m.start()]
            last = re.search(r"([\w.]+)$", before)
            tok = last.group(1).lower() if last else ""
            if tok in ABBREVIATIONS or (len(tok) == 1 and tok.isalpha()):
                continue
            # próxima palavra começa com minúscula: provavelmente não é fim de frase
            nxt = re.match(r"\s+(\S)", text[end:])
            if nxt and nxt.group(1).islower():
                continue
        seg = text[start:end]
        if seg.strip():
            out.append(Span(start, end, seg))
        start = end
        while start < n and text[start].isspace():
            start += 1
    if start < n and text[start:].strip():
        out.append(Span(start, n, text[start:].rstrip()))
    return out


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


@cache
def load_list(name: str) -> tuple[str, ...]:
    """Linhas de ``errei/data/<name>``, sem comentários (#) e vazias."""
    text = resources.files("errei.data").joinpath(name).read_text(encoding="utf-8")
    return tuple(
        line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")
    )


@cache
def load_table(name: str) -> tuple[tuple[str, ...], ...]:
    """Tabela TSV de ``errei/data/<name>``."""
    return tuple(tuple(c.strip() for c in line.split("\t")) for line in load_list(name))


def iter_matches(rx: re.Pattern[str], text: str) -> Iterator[re.Match[str]]:
    yield from rx.finditer(text)


STOPWORDS = frozenset(load_list("stopwords_pt.txt"))
