"""Lista de afazeres (Markdown) por nível: tcc, mestrado, doutorado, a1."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from conftest import ARTIGO
from errei.report import todo
from helpers import audit, cli, make_project


@pytest.fixture
def artigo(tmp_path: Path) -> Path:
    dst = tmp_path / "artigo"
    shutil.copytree(ARTIGO, dst)
    return dst


def test_levels_change_targets_and_priorities(artigo: Path) -> None:
    rep = audit(artigo)
    a1 = todo.build(rep, "a1")
    tcc = todo.build(rep, "tcc")
    assert "<!-- errei:todo nivel=a1 -->" in a1
    assert "Scopus percentil ≥ 92" in a1 and "TCC (graduação)" in tcc
    # declarações de periódico só no nível mais alto
    assert "Declaração de conflito de interesses" in a1
    assert "conflito de interesses" not in tcc
    assert "| ≥ 40 |" in a1 and "| ≥ 15 |" in tcc  # nº de referências
    # sugestões de escrita/ABNT viram P1 no nível alto
    p1 = lambda t: int(t.split("** P1")[0].rsplit("**", 1)[1])  # noqa: E731
    assert p1(a1) > p1(tcc)


def test_items_have_location_code_and_checkbox(artigo: Path) -> None:
    md = todo.build(audit(artigo), "mestrado")
    p0 = md.split("## P0")[1].split("## P1")[0]
    assert "- [ ] **\\ref{fig:inexistente} sem \\label correspondente** — " in p0
    assert "`secoes/metodologia.tex:3` · `LATEX-REF-001`" in p0
    assert "REFS-CITE-001" in p0
    assert "## Revisão humana" in md
    assert "Erros: " not in md.split("## P0")[1]  # contagem não vira item duplicado


def test_regenerate_marks_resolved(artigo: Path, tmp_path: Path) -> None:
    out = tmp_path / "afazeres.md"
    todo.write(audit(artigo), out, "a1")
    assert "## ✅ Resolvidos" not in out.read_text()
    met = artigo / "secoes" / "metodologia.tex"
    met.write_text(met.read_text().replace("\\ref{fig:inexistente}", "a figura"))
    todo.write(audit(artigo), out, "a1")
    text = out.read_text()
    assert "## ✅ Resolvidos desde a última lista" in text
    resolved = text.split("## ✅ Resolvidos")[1].split("## Metas")[0]
    assert "fig:inexistente" in resolved
    # outro nível: não compara (evita falsos "resolvidos")
    todo.write(audit(artigo), out, "tcc")
    assert "## ✅ Resolvidos" not in out.read_text()


def test_ethics_only_with_human_participants(tmp_path: Path) -> None:
    base = "\\documentclass{article}\\begin{document}\n\\section{Introdução}\n%s\n\\end{document}\n"
    sem = make_project(tmp_path / "a", {"main.tex": base % "Analisamos dados públicos."})
    com = make_project(
        tmp_path / "b", {"main.tex": base % "Entrevistamos 30 participantes da pesquisa."}
    )
    assert "Aprovação ética" not in todo.build(audit(sem), "mestrado")
    assert "Aprovação ética" in todo.build(audit(com), "mestrado")


def test_refuses_article_files(artigo: Path) -> None:
    with pytest.raises(ValueError):
        todo.write(audit(artigo), artigo / "main.tex", "a1")


def test_cli_pdf_writes_todo_next_to_it(artigo: Path, tmp_path: Path, readonly_guard) -> None:  # type: ignore[no-untyped-def]
    pytest.importorskip("reportlab")
    readonly_guard(artigo)
    pdf = tmp_path / "out" / "relatorio.pdf"
    pdf.parent.mkdir()
    res = cli(str(artigo), "--pdf", str(pdf), "--nivel", "doutorado", "--no-user-config", "-q")
    assert res.exit_code in (0, 1), res.output
    md = (tmp_path / "out" / "relatorio-afazeres.md").read_text()
    assert "nivel=doutorado" in md


def test_cli_todo_explicit(artigo: Path, tmp_path: Path) -> None:
    out = tmp_path / "t.md"
    res = cli(str(artigo), "--todo", str(out), "--no-user-config", "-q")
    assert res.exit_code in (0, 1)
    assert out.read_text().startswith("# Lista de afazeres")
    bad = cli(str(artigo), "--todo", str(tmp_path / "x.md"), "--nivel", "pos", "-q")
    assert bad.exit_code == 2
