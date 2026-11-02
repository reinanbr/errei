"""Interface de verificadores (plugins) e contexto de execução."""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Protocol, runtime_checkable

from errei import rules as rules_registry
from errei.config import Config
from errei.latex.source import SourceFile
from errei.model import Finding, Location, MetricGroup, Rule, Severity, clip

if TYPE_CHECKING:
    from errei.project import Project


@dataclass(slots=True)
class RunContext:
    config: Config
    http: Any = None  # errei.net.client.HttpClient | None (None = offline)
    cache_dir: Path | None = None
    metrics: list[MetricGroup] = field(default_factory=list)
    prior_findings: list[Finding] = field(default_factory=list)  # visível na fase 1
    shared: dict[str, Any] = field(default_factory=dict)
    extra_meta: dict[str, Any] = field(default_factory=dict)
    # recebe mensagens de progresso (ex.: "referência 3/7: lecun2015"); None = silencioso
    on_progress: Callable[[str], None] | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def progress(self, message: str) -> None:
        if self.on_progress is not None:
            # progresso nunca derruba a verificação
            with contextlib.suppress(Exception):
                self.on_progress(message)

    @property
    def online(self) -> bool:
        return self.http is not None

    def add_metrics(self, group: MetricGroup) -> None:
        with self._lock:
            self.metrics.append(group)

    def share(self, key: str, value: Any) -> None:
        with self._lock:
            self.shared[key] = value


@runtime_checkable
class Checker(Protocol):
    """Contrato de um verificador.

    ``phase`` 0 roda em paralelo; ``phase`` 1 roda depois e enxerga
    ``ctx.prior_findings``. ``uses_network`` indica que o verificador pode usar
    ``ctx.http`` quando online.
    """

    name: str
    title: str
    rules: tuple[Rule, ...]
    phase: int
    uses_network: bool

    def run(self, project: Project, ctx: RunContext) -> list[Finding]: ...


class BaseChecker:
    """Base de conveniência para os verificadores embutidos."""

    name: ClassVar[str] = "base"
    title: ClassVar[str] = ""
    rules: ClassVar[tuple[Rule, ...]] = ()
    phase: ClassVar[int] = 0
    uses_network: ClassVar[bool] = False

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        rules_registry.register(*cls.rules)

    def run(self, project: Project, ctx: RunContext) -> list[Finding]:  # pragma: no cover
        raise NotImplementedError

    def finding(
        self,
        code: str,
        message: str,
        *,
        src: SourceFile | None = None,
        start: int | None = None,
        end: int | None = None,
        location: Location | None = None,
        severity: Severity | None = None,
        excerpt: str | None = None,
        **kw: Any,
    ) -> Finding:
        rule = rules_registry.get(code)
        sev = severity or (rule.severity if rule else Severity.INFO)
        loc = location
        if loc is None and src is not None:
            loc = src.location(start or 0, end)
        if excerpt is None and src is not None and start is not None:
            if end is None:
                eol = src.text.find("\n", start)
                end = min(start + 80, len(src.text) if eol == -1 else eol)
            excerpt = src.excerpt(start, end)
        elif excerpt is not None:
            excerpt = clip(excerpt)
        return Finding(
            code=code,
            severity=sev,
            message=message,
            checker=self.name,
            location=loc,
            excerpt=excerpt,
            **kw,
        )
