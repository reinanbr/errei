"""Descoberta de verificadores via entry points ``errei.checkers``."""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from typing import Any

from errei.checkers.base import Checker

GROUP = "errei.checkers"
BUILTIN_ORDER = ("latex", "refs", "abnt", "ptbr", "escrita", "plagio", "ia", "periodico")
_BUILTIN = {
    "latex": "errei.checkers.latex:LatexChecker",
    "refs": "errei.checkers.refs:RefsChecker",
    "abnt": "errei.checkers.abnt:AbntChecker",
    "ptbr": "errei.checkers.ptbr:PtbrChecker",
    "escrita": "errei.checkers.escrita:EscritaChecker",
    "plagio": "errei.checkers.plagio:PlagioChecker",
    "ia": "errei.checkers.ia:IaChecker",
    "periodico": "errei.checkers.periodico:PeriodicoChecker",
    "referencia": "errei.checkers.referencia:ReferenciaChecker",
}


@dataclass(slots=True)
class Discovery:
    checkers: list[Checker] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)


def _load_target(target: str) -> Any:
    mod, _, attr = target.partition(":")
    obj = importlib.import_module(mod)
    for part in attr.split("."):
        obj = getattr(obj, part)
    return obj


def discover() -> Discovery:
    targets: dict[str, Any] = {}
    errors: list[tuple[str, str]] = []
    for ep in entry_points(group=GROUP):
        try:
            targets[ep.name] = ep.load()
        except ModuleNotFoundError as exc:
            if ep.value.startswith("errei.") and (exc.name or "").startswith("errei."):
                continue  # embutido ainda não disponível nesta instalação
            errors.append((ep.name, f"{type(exc).__name__}: {exc}"))
        except Exception as exc:  # plugin quebrado não derruba a execução
            errors.append((ep.name, f"{type(exc).__name__}: {exc}"))
    for name, target in _BUILTIN.items():
        if name not in targets and name not in {e[0] for e in errors}:
            try:
                targets[name] = _load_target(target)
            except ModuleNotFoundError:
                continue
    out = Discovery(errors=errors)
    for name, obj in targets.items():
        try:
            inst = obj() if isinstance(obj, type) else obj
        except Exception as exc:
            errors.append((name, f"{type(exc).__name__}: {exc}"))
            continue
        if not isinstance(inst, Checker):
            errors.append((name, "objeto não implementa a interface Checker"))
            continue
        out.checkers.append(inst)

    def order(c: Checker) -> tuple[int, int, str]:
        idx = BUILTIN_ORDER.index(c.name) if c.name in BUILTIN_ORDER else len(BUILTIN_ORDER)
        return (c.phase, idx, c.name)

    out.checkers.sort(key=order)
    return out


def select(checkers: list[Checker], only: list[str], skip: list[str]) -> list[Checker]:
    only_s = {o.strip().lower() for o in only if o.strip()}
    skip_s = {s.strip().lower() for s in skip if s.strip()}
    unknown = (only_s | skip_s) - {c.name for c in checkers}
    if unknown:
        raise ValueError("verificador(es) desconhecido(s): " + ", ".join(sorted(unknown)))
    return [c for c in checkers if (not only_s or c.name in only_s) and c.name not in skip_s]
