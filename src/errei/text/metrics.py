"""Métricas textuais aproximadas para o português."""

from __future__ import annotations

import re
from functools import cache
from statistics import mean, pstdev

from errei.text.segment import alpha_words, load_list, sentences, strip_accents

VOWELS = set("aeiouáéíóúâêôãõàüy")
STRONG = set("aeoáéóâêôãõà")


def syllables(word: str) -> int:
    """Contagem heurística de sílabas (núcleos vocálicos com regra de hiato simples)."""
    w = word.lower()
    count = 0
    prev = ""
    for ch in w:
        if ch in VOWELS:
            if not prev:
                count += 1
            elif ch in "íú":
                count += 1  # hiato com vogal fraca tônica (pa-ís, sa-ú-de)
            elif ch in STRONG and prev in STRONG and prev not in "ãõ":
                count += 1  # hiato entre vogais fortes (po-e-ta, le-em); não em "ão", "õe"
            prev = ch
        else:
            prev = ""
    return max(1, count)


def flesch_pt(text: str) -> tuple[float, float, float] | None:
    """Índice de Flesch adaptado (Martins et al., 1996).

    248,835 − 1,015·ASL − 84,6·ASW, com ASL = palavras/frase e ASW = sílabas/palavra.
    Retorna (índice, ASL, ASW) ou None para texto curto demais.
    """
    sents = [s for s in sentences(text) if alpha_words(s.text)]
    ws = alpha_words(text)
    if len(sents) < 2 or len(ws) < 30:
        return None
    asl = len(ws) / len(sents)
    asw = sum(syllables(w.text) for w in ws) / len(ws)
    return 248.835 - 1.015 * asl - 84.6 * asw, asl, asw


def flesch_band(score: float) -> str:
    if score >= 75:
        return "muito fácil"
    if score >= 50:
        return "fácil"
    if score >= 25:
        return "difícil"
    return "muito difícil"


def mattr(text: str, window: int = 100) -> float | None:
    """Moving-Average Type-Token Ratio (Covington & McFall, 2010)."""
    toks = [w.text.lower() for w in alpha_words(text)]
    if len(toks) < 20:
        return None
    if len(toks) <= window:
        return len(set(toks)) / len(toks)
    ratios = []
    counts: dict[str, int] = {}
    for t in toks[:window]:
        counts[t] = counts.get(t, 0) + 1
    ratios.append(len(counts) / window)
    for i in range(window, len(toks)):
        out = toks[i - window]
        counts[out] -= 1
        if counts[out] == 0:
            del counts[out]
        counts[toks[i]] = counts.get(toks[i], 0) + 1
        ratios.append(len(counts) / window)
    return mean(ratios)


@cache
def _connective_re() -> re.Pattern[str]:
    items = sorted(load_list("conectivos.txt"), key=len, reverse=True)
    return re.compile(r"\b(?:" + "|".join(re.escape(i) for i in items) + r")\b", re.IGNORECASE)


def connectives(text: str) -> list[str]:
    return [m.group(0).lower() for m in _connective_re().finditer(text)]


def cv(values: list[float]) -> float:
    """Coeficiente de variação."""
    if len(values) < 2 or mean(values) == 0:
        return 0.0
    return pstdev(values) / mean(values)


def band_score(value: float, lo: float, hi: float, tolerance: float) -> float:
    """10 dentro de [lo, hi]; cai linearmente até 0 a ``tolerance`` de distância."""
    if lo <= value <= hi:
        return 10.0
    dist = lo - value if value < lo else value - hi
    return max(0.0, round(10.0 * (1 - dist / tolerance), 1))


def norm_term(s: str) -> str:
    return strip_accents(s.lower()).replace("-", "").replace(" ", "")
