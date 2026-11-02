from __future__ import annotations

from pathlib import Path

from helpers import audit, by_code, codes, make_project


def run_latex(
    tmp: Path,
    body: str,
    extra: dict[str, str] | None = None,
    header: str = "\\documentclass[brazil]{abntex2}\n",
):
    files = {"main.tex": header + "\\begin{document}\n" + body + "\n\\end{document}\n"}
    files.update(extra or {})
    root = make_project(tmp, files)
    return audit(root, checkers={"only": ["latex"]}).findings


def test_refs_labels(tmp_path: Path) -> None:
    f = run_latex(tmp_path, "\\label{a}\\label{a}\\ref{a} \\ref{b} \\label{fig:solto}")
    assert len(by_code(f, "LATEX-REF-001")) == 1
    assert by_code(f, "LATEX-REF-001")[0].location.line == 3  # type: ignore[union-attr]
    assert len(by_code(f, "LATEX-LABEL-001")) == 1
    assert [x.message for x in by_code(f, "LATEX-LABEL-002")] == [
        "\\label{fig:solto} nunca referenciado"
    ]


def test_ref_suggestion(tmp_path: Path) -> None:
    f = run_latex(tmp_path, "\\label{fig:fluxo} \\ref{fig:flux}")
    assert "fig:fluxo" in (by_code(f, "LATEX-REF-001")[0].suggestion or "")


def test_envs(tmp_path: Path) -> None:
    f = run_latex(tmp_path, "\\begin{itemize}\n\\item a\n\\end{enumerate}\n\\begin{center}")
    msgs = [x.message for x in by_code(f, "LATEX-ENV-001")]
    assert "\\end{enumerate} sem \\begin{enumerate}" in msgs
    assert any(m.startswith("\\begin{itemize} sem \\end{itemize}") for m in msgs)
    assert any(m.startswith("\\begin{center} sem \\end{center}") for m in msgs)


def test_floats(tmp_path: Path) -> None:
    body = (
        "\\begin{figure}\\includegraphics{x}\\end{figure}\n"
        "\\begin{table}\\caption{T}\\label{tab:t}\\end{table}\n"
        "\\begin{table}\\caption{U}\\label{tab:u}\\end{table} ver \\ref{tab:u}"
    )
    f = run_latex(tmp_path, body)
    assert len(by_code(f, "LATEX-FLOAT-001")) == 1
    msgs = [x.message for x in by_code(f, "LATEX-FLOAT-002")]
    assert msgs == [
        "figura sem \\label: não pode ser citada no texto",
        "tabela 'tab:t' nunca é citada no texto (\\ref)",
    ]


def test_todos_and_comment_blocks(tmp_path: Path) -> None:
    body = "a % TODO: arrumar\n\\todo{ver isso}\n" + "% linha comentada aqui\n" * 6
    f = run_latex(tmp_path, body)
    assert len(by_code(f, "LATEX-TODO-001")) == 2
    assert len(by_code(f, "LATEX-COMMENT-001")) == 1


def test_language_and_class(tmp_path: Path) -> None:
    f = run_latex(tmp_path, "x", header="\\documentclass{article}\n")
    assert "LATEX-LANG-001" in codes(f) and "LATEX-CLASS-001" in codes(f)
    f = run_latex(
        tmp_path / "b",
        "x",
        header="\\documentclass{article}\n\\usepackage[english,brazilian]{babel}\n",
    )
    assert "LATEX-LANG-001" not in codes(f)


def test_braces(tmp_path: Path) -> None:
    f = run_latex(tmp_path, "\\textbf{a \\{ b")
    assert len(by_code(f, "LATEX-BRACE-001")) == 1


def test_missing_input_and_orphan(tmp_path: Path) -> None:
    f = run_latex(tmp_path, "\\input{nada}", {"orfao.tex": "x"})
    assert "LATEX-INPUT-001" in codes(f) and "LATEX-ORPHAN-001" in codes(f)
