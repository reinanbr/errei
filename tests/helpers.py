from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from errei.cli import _rewrite_argv, app
from errei.config import Config
from errei.model import Finding
from errei.pipeline import run
from errei.report.build import Report


def cli(*args: str) -> Any:
    return CliRunner().invoke(app, _rewrite_argv(list(args)), catch_exceptions=False)


def audit(root: Path, **overrides: Any) -> Report:
    cfg = Config.load(root, overrides, use_user_config=False)
    return run(root, cfg)


def audit_json(root: Path, *extra: str) -> dict[str, Any]:
    res = cli(str(root), "--format", "json", "--no-user-config", *extra)
    assert res.exit_code in (0, 1), res.output
    data: dict[str, Any] = json.loads(res.stdout)
    return data


def make_project(tmp: Path, files: dict[str, str]) -> Path:
    for name, content in files.items():
        p = tmp / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return tmp


def codes(findings: list[Finding]) -> list[str]:
    return [f.code for f in findings]


def by_code(findings: list[Finding], code: str) -> list[Finding]:
    return [f for f in findings if f.code == code]


MINIMAL_MAIN = r"""\documentclass[brazil]{abntex2}
\begin{document}
%s
\end{document}
"""
