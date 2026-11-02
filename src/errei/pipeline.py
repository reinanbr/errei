"""Pipeline: descobrir → parsear → verificar → agregar."""

from __future__ import annotations

import os
import traceback
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from errei import __version__
from errei.checkers.base import Checker, RunContext
from errei.config import Config, cache_dir
from errei.ignore import IgnoreIndex
from errei.model import Finding, Severity
from errei.project import Project, load_project
from errei.registry import discover, select
from errei.report.build import Report
from errei.report.limitations import limitations_for


def _safe_run(checker: Checker, project: Project, ctx: RunContext) -> list[Finding]:
    try:
        return list(checker.run(project, ctx))
    except Exception as exc:
        tb = traceback.extract_tb(exc.__traceback__)
        where = f" ({tb[-1].filename.rsplit('/', 1)[-1]}:{tb[-1].lineno})" if tb else ""
        return [
            Finding(
                "CORE-CHECKER-001",
                Severity.AVISO,
                f"o verificador '{checker.name}' falhou: {type(exc).__name__}: {exc}{where}",
                "core",
            )
        ]


def make_http(config: Config) -> Any:
    from errei.net.client import HttpClient  # importa httpx só quando online

    return HttpClient(cache_dir=cache_dir(), email=config.email)


def run(
    root: Path,
    config: Config,
    *,
    flags: dict[str, Any] | None = None,
    http: Any = None,
    progress: Callable[[str], None] | None = None,
) -> Report:
    flags = flags or {}
    project = load_project(root, config.data.get("main") or None)
    disc = discover()
    only = list(config.get("checkers", "only", []) or [])
    skip = list(config.get("checkers", "skip", []) or [])
    checkers = select(disc.checkers, only, skip)

    pre: list[Finding] = [
        Finding("CORE-PLUGIN-001", Severity.INFO, f"plugin '{n}' não carregado: {err}", "core")
        for n, err in disc.errors
    ]
    pre += [Finding("CORE-PROJ-001", Severity.INFO, n, "core") for n in project.notes]

    if http is None and config.online and any(c.uses_network for c in checkers):
        try:
            http = make_http(config)
        except ModuleNotFoundError:
            pre.append(
                Finding(
                    "CORE-DEP-001",
                    Severity.AVISO,
                    "--online requer o extra 'online': pip install 'errei[online]'",
                    "core",
                )
            )
            http = None
    ctx = RunContext(
        config=config,
        http=http if config.online else None,
        cache_dir=cache_dir(),
        on_progress=progress,
    )
    qualis_csv = str(config.get("periodico", "qualis_csv", "") or "")
    if qualis_csv and any(c.name == "periodico" for c in checkers):
        from errei.qualis import load_qualis

        table = load_qualis(Path(qualis_csv), str(config.get("periodico", "qualis_data", "") or ""))
        ctx.shared["qualis"] = table
        ctx.extra_meta.update(
            {
                "qualis_csv": str(table.path),
                "qualis_data": table.ref_date,
                "qualis_data_origem": table.date_source,
            }
        )

    ctx.shared["checkers_ran"] = [c.name for c in checkers]
    findings: list[Finding] = list(pre)
    phase0 = [c for c in checkers if c.phase == 0]
    phase1 = [c for c in checkers if c.phase != 0]
    jobs = int(config.data.get("jobs") or 0) or min(8, (os.cpu_count() or 2))
    if len(phase0) > 1 and jobs > 1:
        with ThreadPoolExecutor(max_workers=jobs) as pool:
            for result in pool.map(lambda c: _safe_run(c, project, ctx), phase0):
                findings.extend(result)
    else:
        for c in phase0:
            findings.extend(_safe_run(c, project, ctx))
    for c in phase1:
        ctx.prior_findings = list(findings)
        findings.extend(_safe_run(c, project, ctx))

    if ctx.http is not None:
        findings.extend(ctx.http.status_findings())
        ctx.http.close()

    ign = IgnoreIndex.build(
        project.all_sources(),
        list(config.get("ignore", "codes", []) or []),
        list(config.get("ignore", "paths", []) or []),
    )
    kept: list[Finding] = []
    seen: set[tuple[Any, ...]] = set()
    suppressed = 0
    for f in findings:
        if ign.suppressed(f):
            suppressed += 1
            continue
        key = (f.code, f.location, f.message)
        if key in seen:
            continue
        seen.add(key)
        kept.append(f)
    kept.sort(key=Finding.sort_key)

    names = [c.name for c in checkers]
    meta: dict[str, Any] = {
        "tool": "errei",
        "version": __version__,
        "date": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "root": str(project.root),
        "main": project.main.path.as_posix() if project.main else None,
        "project_hash": project.content_hash(),
        "files": {
            "tex": [s.path.as_posix() for s in project.tex],
            "tex_orphans": [s.path.as_posix() for s in project.orphans],
            "bib": [b.source.path.as_posix() for b in project.bibs],
        },
        "online": ctx.online,
        "checkers": names,
        "flags": flags,
        "config_files": [str(p) for p in config.sources],
    }
    meta.update(ctx.extra_meta)
    return Report(
        findings=kept,
        metrics=ctx.metrics,
        meta=meta,
        limitations=limitations_for(names),
        checkers=[(c.name, c.title) for c in checkers],
        notes=project.notes,
        suppressed=suppressed,
        references=list(ctx.shared.get("referencias", [])),
    )
