"""Shingling, Jaccard/contenção e índice de fingerprints para similaridade."""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, field

from errei.text.segment import strip_accents

_TOKEN = re.compile(r"[^\W_]+")


@dataclass(frozen=True, slots=True)
class Tok:
    norm: str
    start: int
    end: int


def tokens(text: str) -> list[Tok]:
    return [
        Tok(strip_accents(m.group(0).lower()), m.start(), m.end()) for m in _TOKEN.finditer(text)
    ]


def h64(s: str) -> int:
    return int.from_bytes(hashlib.blake2b(s.encode("utf-8"), digest_size=8).digest(), "big")


def shingles(toks: list[Tok], k: int) -> list[int]:
    """Hash de cada k-grama de palavras, na ordem (posição i = tokens i..i+k-1)."""
    if len(toks) < k:
        return []
    return [h64(" ".join(t.norm for t in toks[i : i + k])) for i in range(len(toks) - k + 1)]


def jaccard(a: AbstractSet[int], b: AbstractSet[int]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def containment(a: AbstractSet[int], b: AbstractSet[int]) -> float:
    """Fração do menor conjunto contida no outro."""
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def shared_span(
    seq: list[int], other: AbstractSet[int], toks: list[Tok], k: int
) -> tuple[int, int, int]:
    """Maior trecho contínuo de ``seq`` coberto por shingles de ``other``.

    Retorna (início_char, fim_char, n_palavras) no texto de ``toks``.
    """
    best = (0, 0, 0)
    i = 0
    n = len(seq)
    while i < n:
        if seq[i] in other:
            j = i
            while j + 1 < n and seq[j + 1] in other:
                j += 1
            words = j - i + k
            if words > best[2]:
                best = (toks[i].start, toks[j + k - 1].end, words)
            i = j + 1
        else:
            i += 1
    return best


SAMPLE_MOD = 4  # guarda ~1/4 dos shingles no índice (fingerprints)


@dataclass(slots=True)
class FingerprintIndex:
    """Índice invertido de fingerprints amostrados (h % SAMPLE_MOD == 0)."""

    k: int
    postings: dict[int, list[tuple[int, int]]] = field(default_factory=lambda: defaultdict(list))
    docs: list[tuple[str, str]] = field(default_factory=list)  # (nome, texto)
    _doc_shingles: dict[int, list[int]] = field(default_factory=dict)
    _doc_tokens: dict[int, list[Tok]] = field(default_factory=dict)

    def add(self, name: str, text: str) -> None:
        doc_id = len(self.docs)
        self.docs.append((name, text))
        toks = tokens(text)
        sh = shingles(toks, self.k)
        self._doc_tokens[doc_id] = toks
        self._doc_shingles[doc_id] = sh
        for pos, h in enumerate(sh):
            if h % SAMPLE_MOD == 0:
                self.postings[h].append((doc_id, pos))

    def query(self, sh: list[int], min_hits: int = 2) -> dict[int, int]:
        hits: dict[int, int] = defaultdict(int)
        for h in set(sh):
            if h % SAMPLE_MOD == 0:
                for doc_id, _ in self.postings.get(h, ()):
                    hits[doc_id] += 1
        return {d: n for d, n in hits.items() if n >= min_hits}

    def doc_shingles(self, doc_id: int) -> list[int]:
        return self._doc_shingles[doc_id]

    def doc_tokens(self, doc_id: int) -> list[Tok]:
        return self._doc_tokens[doc_id]
