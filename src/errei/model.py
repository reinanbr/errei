"""Modelo de dados central: severidades, regras e achados."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class Severity(str, Enum):
    """Severidade de um achado. A ordem de declaração é a ordem de gravidade."""

    ERRO = "erro"
    AVISO = "aviso"
    SUGESTAO = "sugestão"
    INFO = "info"

    @property
    def rank(self) -> int:
        """0 = mais grave."""
        return _RANK[self]

    @classmethod
    def parse(cls, value: str) -> Severity:
        aliases = {
            "error": cls.ERRO,
            "erro": cls.ERRO,
            "warning": cls.AVISO,
            "aviso": cls.AVISO,
            "suggestion": cls.SUGESTAO,
            "sugestao": cls.SUGESTAO,
            "sugestão": cls.SUGESTAO,
            "info": cls.INFO,
        }
        try:
            return aliases[value.strip().lower()]
        except KeyError as exc:
            raise ValueError(f"severidade desconhecida: {value!r}") from exc


_RANK = {Severity.ERRO: 0, Severity.AVISO: 1, Severity.SUGESTAO: 2, Severity.INFO: 3}


@dataclass(frozen=True, slots=True)
class Location:
    file: Path
    line: int
    column: int | None = None
    end_line: int | None = None
    end_column: int | None = None

    def __str__(self) -> str:
        col = f":{self.column}" if self.column is not None else ""
        return f"{self.file.as_posix()}:{self.line}{col}"


@dataclass(frozen=True, slots=True)
class Rule:
    code: str
    severity: Severity
    title: str
    explanation: str
    reference: str | None = None
    heuristic: bool = False


@dataclass(frozen=True, slots=True)
class Finding:
    code: str
    severity: Severity
    message: str
    checker: str
    location: Location | None = None
    excerpt: str | None = None
    suggestion: str | None = None
    confidence: float | None = None
    evidence: tuple[str, ...] = ()
    links: tuple[str, ...] = ()
    manual_review: bool = False

    def sort_key(self) -> tuple[str, int, int, int, str]:
        loc = self.location
        return (
            loc.file.as_posix() if loc else "",
            self.severity.rank,
            loc.line if loc else 0,
            (loc.column or 0) if loc else 0,
            self.code,
        )

    def to_dict(self) -> dict[str, Any]:
        loc = self.location
        return {
            "code": self.code,
            "severity": self.severity.value,
            "message": self.message,
            "checker": self.checker,
            "file": loc.file.as_posix() if loc else None,
            "line": loc.line if loc else None,
            "column": loc.column if loc else None,
            "end_line": loc.end_line if loc else None,
            "end_column": loc.end_column if loc else None,
            "excerpt": self.excerpt,
            "suggestion": self.suggestion,
            "confidence": self.confidence,
            "evidence": list(self.evidence),
            "links": list(self.links),
            "manual_review": self.manual_review,
        }


@dataclass(slots=True)
class Metric:
    """Métrica explicada (sem nota única opaca)."""

    name: str
    value: float | str | None
    score: float | None  # 0..10 quando aplicável
    reference: str  # faixa de referência legível
    explanation: str


@dataclass(slots=True)
class MetricGroup:
    checker: str
    title: str
    metrics: list[Metric] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def clip(text: str, limit: int = 160) -> str:
    """Encurta um trecho para exibição, em uma linha."""
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"
