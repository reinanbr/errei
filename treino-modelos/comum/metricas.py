"""Métricas sem dependências: F1 por classe, AUC, limiar por FPR, F1 de campos BIO, chrF."""

from __future__ import annotations

from collections import Counter
from typing import Any


def f1_classes(y: list[str], p: list[str], labels: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "n": len(y),
        "acuracia": sum(a == b for a, b in zip(y, p, strict=False)) / max(1, len(y)),
    }
    f1s = []
    for lb in labels:
        tp = sum(a == lb and b == lb for a, b in zip(y, p, strict=False))
        fp = sum(a != lb and b == lb for a, b in zip(y, p, strict=False))
        fn = sum(a == lb and b != lb for a, b in zip(y, p, strict=False))
        pr = tp / (tp + fp) if tp + fp else 0.0
        rc = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * pr * rc / (pr + rc) if pr + rc else 0.0
        out[lb] = {"precisao": pr, "revocacao": rc, "f1": f1, "n": tp + fn}
        if tp + fn:
            f1s.append(f1)
    out["f1_macro"] = sum(f1s) / max(1, len(f1s))
    out["confusao"] = {
        a: dict(Counter(b for x, b in zip(y, p, strict=False) if x == a)) for a in labels
    }
    return out


def auc(pos: list[float], neg: list[float]) -> float:
    """Área sob a curva ROC pela estatística de Mann-Whitney (empates valem meio)."""
    if not pos or not neg:
        return float("nan")
    todos = sorted([(s, 1) for s in pos] + [(s, 0) for s in neg])
    soma_pos, i, rank = 0.0, 0, 1
    while i < len(todos):
        j = i
        while j < len(todos) and todos[j][0] == todos[i][0]:
            j += 1
        medio = (rank + rank + (j - i) - 1) / 2
        soma_pos += medio * sum(1 for k in range(i, j) if todos[k][1])
        rank += j - i
        i = j
    return (soma_pos - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))


def limiar_fpr(neg: list[float], fpr: float) -> float:
    """Menor limiar que deixa no máximo ``fpr`` dos negativos acima dele (escore > limiar)."""
    if not neg:
        return 0.5
    s = sorted(neg, reverse=True)
    k = int(fpr * len(s))
    return s[k] if k < len(s) else s[-1]


def taxas(pos: list[float], neg: list[float], limiar: float) -> dict[str, float]:
    return {
        "tpr": sum(x > limiar for x in pos) / max(1, len(pos)),
        "fpr": sum(x > limiar for x in neg) / max(1, len(neg)),
    }


def spans(tags: list[str]) -> set[tuple[str, int, int]]:
    out, campo, ini = set(), None, 0
    for i, t in enumerate([*tags, "O"]):
        if t.startswith("I-") and campo == t[2:]:
            continue
        if campo is not None:
            out.add((campo, ini, i))
            campo = None
        if t.startswith(("B-", "I-")):  # I- solto abre campo novo
            campo, ini = t[2:], i
    return out


def f1_campos(ouro: list[list[str]], pred: list[list[str]]) -> dict[str, Any]:
    tp: Counter[str] = Counter()
    fp: Counter[str] = Counter()
    fn: Counter[str] = Counter()
    for g, p in zip(ouro, pred, strict=False):
        sg, sp = spans(g), spans(p)
        for s in sg & sp:
            tp[s[0]] += 1
        for s in sp - sg:
            fp[s[0]] += 1
        for s in sg - sp:
            fn[s[0]] += 1
    out: dict[str, Any] = {}
    for c in sorted(set(tp) | set(fp) | set(fn)):
        pr = tp[c] / (tp[c] + fp[c]) if tp[c] + fp[c] else 0.0
        rc = tp[c] / (tp[c] + fn[c]) if tp[c] + fn[c] else 0.0
        out[c] = {
            "precisao": pr,
            "revocacao": rc,
            "f1": 2 * pr * rc / (pr + rc) if pr + rc else 0.0,
            "n": tp[c] + fn[c],
        }
    vp, fp_, fn_ = sum(tp.values()), sum(fp.values()), sum(fn.values())
    pr = vp / (vp + fp_) if vp + fp_ else 0.0
    rc = vp / (vp + fn_) if vp + fn_ else 0.0
    out["micro"] = {
        "precisao": pr,
        "revocacao": rc,
        "f1": 2 * pr * rc / (pr + rc) if pr + rc else 0.0,
    }
    out["referencias_perfeitas"] = sum(
        spans(g) == spans(p) for g, p in zip(ouro, pred, strict=False)
    ) / max(1, len(ouro))
    return out


def f1_linha(g: list[str], p: list[str]) -> float:
    sg, sp = spans(g), spans(p)
    if not sg and not sp:
        return 1.0
    t = len(sg & sp)
    return 2 * t / (len(sg) + len(sp)) if sg or sp else 0.0


def _ngramas(s: str, n: int) -> Counter[str]:
    s = "".join(s.split())
    return Counter(s[i : i + n] for i in range(len(s) - n + 1))


def chrf(hyps: list[str], refs: list[str], n: int = 6, beta: float = 2.0) -> float:
    """chrF de corpus (caracteres, n = 1..6, beta = 2), em 0-100, como o sacrebleu."""
    ps, rs = [], []
    for k in range(1, n + 1):
        acerto = tot_h = tot_r = 0
        for h, r in zip(hyps, refs, strict=False):
            gh, gr = _ngramas(h, k), _ngramas(r, k)
            acerto += sum((gh & gr).values())
            tot_h += sum(gh.values())
            tot_r += sum(gr.values())
        if tot_h and tot_r:
            ps.append(acerto / tot_h)
            rs.append(acerto / tot_r)
    if not ps:
        return 0.0
    p, r = sum(ps) / len(ps), sum(rs) / len(rs)
    return 100 * (1 + beta**2) * p * r / (beta**2 * p + r) if p + r else 0.0


def f1_termos(hyp: str, ref: str, sep: str = ";") -> tuple[float, float, float]:
    from comum.util import norm

    h = {norm(t) for t in hyp.split(sep) if norm(t)}
    r = {norm(t) for t in ref.split(sep) if norm(t)}
    t = len(h & r)
    pr = t / len(h) if h else 0.0
    rc = t / len(r) if r else 0.0
    return pr, rc, (2 * pr * rc / (pr + rc) if pr + rc else 0.0)
