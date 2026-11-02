"""Seleção dos principais problemas e melhorias (tela e PDF)."""

from __future__ import annotations

from collections import defaultdict

from errei.model import Finding, Severity
from errei.report.build import Report


def _round_robin(items: list[Finding], n: int, per_code: int) -> list[Finding]:
    """Alterna entre verificadores e limita repetições do mesmo código."""
    by_checker: dict[str, list[Finding]] = defaultdict(list)
    for f in items:
        by_checker[f.checker].append(f)
    out: list[Finding] = []
    used: dict[str, int] = defaultdict(int)
    while len(out) < n and any(by_checker.values()):
        for checker in list(by_checker):
            queue = by_checker[checker]
            while queue:
                f = queue.pop(0)
                if used[f.code] < per_code:
                    used[f.code] += 1
                    out.append(f)
                    break
            if len(out) >= n:
                break
    return out


def top_problems(report: Report, n: int = 15) -> list[Finding]:
    out: list[Finding] = []
    for sev in (Severity.ERRO, Severity.AVISO):
        items = [f for f in report.findings if f.severity is sev and not f.code.startswith("CORE")]
        out += _round_robin(items, n - len(out), per_code=4)
        if len(out) >= n:
            break
    return out


def improvements(report: Report, n: int = 15) -> list[Finding]:
    items = [f for f in report.findings if f.severity is Severity.SUGESTAO]
    return _round_robin(items, n, per_code=2)
