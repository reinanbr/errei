from __future__ import annotations

from pathlib import Path

from errei.latex.extract import extract
from errei.latex.source import SourceFile

DOC = r"""\documentclass{abntex2}
\begin{document}
\section{Introdução}\label{sec:a}
Texto com \emph{ênfase}, $x^2$ e \cite[p.~3]{silva2020}. Segundo \citeonline{souza},
isso --- é~bom. % comentário

\begin{figure}
\caption{Uma legenda}
\end{figure}
\begin{otherlanguage*}{english}
\begin{resumoumacoluna}
This is it.
\end{resumoumacoluna}
\end{otherlanguage*}
\begin{itemize}
\item primeiro item
\end{itemize}
Acentos: \'e \c{c} \~ao.
\end{document}
"""


def ct():
    return extract(SourceFile(Path("m.tex"), Path("m.tex"), DOC))


def test_paragraph_kinds_and_langs() -> None:
    kinds = [(p.kind, p.lang) for p in ct().paragraphs]
    assert kinds == [
        ("heading", "pt"),
        ("body", "pt"),
        ("caption", "pt"),
        ("abstract", "en"),
        ("item", "pt"),
        ("body", "pt"),
    ]


def test_clean_text_content() -> None:
    body = ct().paragraphs[1].text
    assert "ênfase" in body and "x e (SILVA, 2020)" in body
    assert "Silva (2020)" in body and "— é bom" in body
    assert "comentário" not in body
    assert ct().paragraphs[-1].text == "Acentos: é ç ão."


def test_offsets_map_back_to_source_lines() -> None:
    c = ct()
    body = c.paragraphs[1]
    i = body.text.index("isso")
    assert body.location(i).line == 5
    assert DOC.splitlines()[4].startswith("isso")
    assert c.paragraphs[3].first_line == 12


def test_sections_and_cites() -> None:
    c = ct()
    assert [s.title for s in c.sections] == ["Introdução"]
    assert [cs.keys for cs in c.cites] == [("silva2020",), ("souza",)]
