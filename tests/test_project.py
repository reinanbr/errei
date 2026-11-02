from __future__ import annotations

from pathlib import Path

import pytest

from errei.project import ProjectError, load_project
from helpers import MINIMAL_MAIN, make_project


def test_main_detection_and_order(tmp_path: Path) -> None:
    root = make_project(
        tmp_path,
        {
            "main.tex": MINIMAL_MAIN % "\\input{cap/a}\n\\include{cap/b}\n\\bibliography{refs}",
            "cap/a.tex": "A",
            "cap/b.tex": "B \\input{cap/c}",
            "cap/c.tex": "C",
            "solto.tex": "nada",
            "refs.bib": "@misc{x, title={t}}",
        },
    )
    p = load_project(root)
    assert p.main is not None and p.main.path == Path("main.tex")
    assert [s.path.as_posix() for s in p.tex] == ["main.tex", "cap/a.tex", "cap/b.tex", "cap/c.tex"]
    assert [s.path.as_posix() for s in p.orphans] == ["solto.tex"]
    assert [e.key for e in p.bib_entries] == ["x"]


def test_missing_outside_and_cycle(tmp_path: Path) -> None:
    outside = tmp_path / "fora.tex"
    outside.write_text("segredo")
    root = make_project(
        tmp_path / "proj",
        {
            "main.tex": MINIMAL_MAIN % "\\input{nao_existe}\\input{../fora}\\input{/etc/passwd}"
            "\\input{loop}",
            "loop.tex": "\\input{main}",
        },
    )
    p = load_project(root)
    probs = sorted((i.raw, i.problem) for i in p.includes if i.problem)
    assert probs == [
        ("../fora", "fora da raiz"),
        ("/etc/passwd", "fora da raiz"),
        ("main", "ciclo"),
        ("nao_existe", "inexistente"),
    ]
    assert all("segredo" not in s.text for s in p.tex)


def test_errors(tmp_path: Path) -> None:
    with pytest.raises(ProjectError):
        load_project(tmp_path / "nada")
    with pytest.raises(ProjectError):
        load_project(make_project(tmp_path / "vazio", {"x.txt": ""}))
    with pytest.raises(ProjectError):
        load_project(make_project(tmp_path / "semmain", {"a.tex": "texto"}))
