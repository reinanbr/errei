"""Estrutura do relatório agregado."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from errei.model import Finding, MetricGroup, Severity


@dataclass(slots=True)
class Report:
    findings: list[Finding]
    metrics: list[MetricGroup]
    meta: dict[str, Any]
    limitations: list[str]
    checkers: list[tuple[str, str]]  # (nome, título)
    notes: list[str] = field(default_factory=list)
    suppressed: int = 0
    # obras citadas buscadas online + validação de cada atribuição (ver checkers/refs.py)
    references: list[dict[str, Any]] = field(default_factory=list)
    # projeto analisado (para a lista de afazeres); não vai para JSON/MD
    project: Any = field(default=None, repr=False, compare=False)

    def by_severity(self) -> dict[Severity, int]:
        c = Counter(f.severity for f in self.findings)
        return {s: c.get(s, 0) for s in Severity}

    def by_checker(self) -> dict[str, dict[Severity, int]]:
        out: dict[str, dict[Severity, int]] = {
            name: {s: 0 for s in Severity} for name, _ in self.checkers
        }
        for f in self.findings:
            out.setdefault(f.checker, {s: 0 for s in Severity})[f.severity] += 1
        return out

    def exit_code(self, fail_on: str) -> int:
        fail_on = fail_on.lower()
        if fail_on == "never":
            return 0
        counts = self.by_severity()
        if fail_on in ("warning", "aviso"):
            return 1 if counts[Severity.ERRO] or counts[Severity.AVISO] else 0
        return 1 if counts[Severity.ERRO] else 0
