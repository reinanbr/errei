from __future__ import annotations

from pathlib import Path

from errei.latex.scanner import env_blocks, find_commands, split_keys
from errei.latex.source import SourceFile


def src(text: str) -> SourceFile:
    return SourceFile(Path("a.tex"), Path("a.tex"), text)


def test_line_col_and_location() -> None:
    s = src("ab\ncd\n\nef")
    assert s.line_col(0) == (1, 1)
    assert s.line_col(3) == (2, 1)
    assert s.line_col(7) == (4, 1)
    loc = s.location(3, 5)
    assert (loc.line, loc.column, loc.end_line, loc.end_column) == (2, 1, 2, 3)


def test_mask_comments_respects_escaped_percent() -> None:
    s = src("50\\% certo % comentário\nlinha\\\\% outro\n")
    assert "comentário" not in s.masked
    assert "50\\%" in s.masked
    assert [c.text.strip() for c in s.comments] == ["comentário", "outro"]
    assert len(s.masked) == len(s.text)


def test_mask_verbatim() -> None:
    s = src("a \\begin{verbatim}\\ref{x} % y\n\\end{verbatim} \\verb|\\cite{z}| b")
    assert "\\ref{x}" not in s.masked
    assert "\\cite{z}" not in s.masked
    assert s.comments == []


def test_find_commands_with_optional_and_nested() -> None:
    text = r"x \cite[p.~{3}][]{a, b} \citeonline{c} \\cite{no} \textbf{\cite{d}}"
    cmds = list(find_commands(text, ["cite", "citeonline"]))
    assert [c.name for c in cmds] == ["cite", "citeonline", "cite"]
    assert [k for k, _ in split_keys(cmds[0].mandatory[0])] == ["a", "b"]
    key, off = split_keys(cmds[0].mandatory[0])[1]
    assert text[off : off + len(key)] == "b"


def test_find_commands_stops_at_blank_line() -> None:
    cmds = list(find_commands("\\section\n\n{x}", ["section"]))
    assert cmds[0].mandatory == []


def test_env_blocks_nested() -> None:
    text = "\\begin{figure}\\begin{center}x\\end{center}\\end{figure}"
    blocks = env_blocks(text)
    assert [b.name for b in blocks] == ["figure", "center"]
