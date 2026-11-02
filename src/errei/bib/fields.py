"""Campos obrigatórios por tipo e validadores de identificadores."""

from __future__ import annotations

import re

# Alternativas separadas por "|": basta uma.
REQUIRED: dict[str, tuple[str, ...]] = {
    "article": ("author", "title", "journal|journaltitle", "year|date"),
    "book": ("author|editor", "title", "publisher", "year|date"),
    "inbook": ("author|editor", "title", "chapter|pages", "publisher", "year|date"),
    "incollection": ("author", "title", "booktitle", "publisher", "year|date"),
    "inproceedings": ("author", "title", "booktitle", "year|date"),
    "conference": ("author", "title", "booktitle", "year|date"),
    "phdthesis": ("author", "title", "school|institution", "year|date"),
    "mastersthesis": ("author", "title", "school|institution", "year|date"),
    "thesis": ("author", "title", "type", "institution|school", "year|date"),
    "techreport": ("author", "title", "institution", "year|date"),
    "manual": ("title",),
    "misc": (),
    "online": ("title", "url", "urldate|urlaccessdate"),
    "proceedings": ("title", "year|date"),
    "unpublished": ("author", "title", "note"),
    "booklet": ("title",),
}

DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")
_DOI_PREFIX = re.compile(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", re.IGNORECASE)
ARXIV_NEW = re.compile(r"^(?:arxiv:)?\d{4}\.\d{4,5}(?:v\d+)?$", re.IGNORECASE)
ARXIV_OLD = re.compile(r"^(?:arxiv:)?[a-z-]+(?:\.[A-Z]{2})?/\d{7}(?:v\d+)?$", re.IGNORECASE)


def normalize_doi(value: str) -> str:
    return _DOI_PREFIX.sub("", value.strip()).strip().rstrip(".")


def valid_doi(value: str) -> bool:
    return bool(DOI_RE.match(normalize_doi(value)))


def valid_arxiv(value: str) -> bool:
    v = value.strip()
    return bool(ARXIV_NEW.match(v) or ARXIV_OLD.match(v))


def valid_isbn(value: str) -> bool:
    digits = re.sub(r"[\s-]", "", value).upper()
    if len(digits) == 10 and re.fullmatch(r"\d{9}[\dX]", digits):
        total = sum((10 - i) * (10 if c == "X" else int(c)) for i, c in enumerate(digits))
        return total % 11 == 0
    if len(digits) == 13 and digits.isdigit():
        total = sum((1 if i % 2 == 0 else 3) * int(c) for i, c in enumerate(digits))
        return total % 10 == 0
    return False


def year_of(value: str) -> int | None:
    m = re.search(r"\b(1[5-9]\d\d|20\d\d)\b", value)
    return int(m.group(1)) if m else None
