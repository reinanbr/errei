"""Completude: o que falta para artigo (NBR 6022) ou monografia (NBR 14724)."""

from __future__ import annotations

from pathlib import Path

from conftest import ARTIGO
from errei.checkers.completude import detect_tipo
from errei.project import load_project
from helpers import audit, by_code, make_project

MONO = r"""\documentclass[brazil]{abntex2}
\titulo{Um estudo}
\autor{Fulana}
\local{Recife}
\data{2026}
\begin{document}
\imprimircapa
\tableofcontents
\begin{resumo}
Este trabalho estuda algo importante para a área e apresenta resultados relevantes
sobre o tema investigado na pesquisa. Palavras-chave: estudo. teste.
\end{resumo}
\chapter{Introdução}
Texto.
\chapter{Conclusão}
Texto.
\begin{figure}\caption{x}\end{figure}
\bibliography{r}
\end{document}
"""


def test_artigo_fixture_complete() -> None:
    rep = audit(ARTIGO, checkers={"only": ["completude"]})
    tipo = by_code(rep.findings, "COMP-TIPO-001")
    assert tipo and "artigo" in tipo[0].message
    assert not by_code(rep.findings, "COMP-OBRIG-001")
    g = next(m for m in rep.metrics if m.checker == "completude")
    assert g.metrics[0].value == "8/8"


def test_monografia_missing_elements(tmp_path: Path) -> None:
    root = make_project(tmp_path, {"main.tex": MONO, "r.bib": ""})
    p = load_project(root)
    assert detect_tipo(p)[0] == "monografia"
    rep = audit(root, checkers={"only": ["completude"]})
    missing = " | ".join(f.message for f in by_code(rep.findings, "COMP-OBRIG-001"))
    for el in ("Folha de rosto", "Ficha catalográfica", "Folha de aprovação", "Desenvolvimento"):
        assert el in missing
    # sem o 'abnt' rodando, o resumo em língua estrangeira também é apontado
    assert "Resumo em língua estrangeira" in missing
    assert "Capa" not in missing and "Sumário" not in missing
    rec = " | ".join(f.message for f in by_code(rep.findings, "COMP-REC-001"))
    assert "Lista de ilustrações" in rec  # há figura
    meta = " | ".join(f.message for f in by_code(rep.findings, "COMP-META-001"))
    assert "orientador" in meta and "instituição" in meta and "título" not in meta


def test_tipo_forced_and_no_duplicate_with_abnt(tmp_path: Path) -> None:
    root = make_project(tmp_path, {"main.tex": MONO, "r.bib": ""})
    rep = audit(root, checkers={"only": ["completude", "abnt"]}, completude={"tipo": "artigo"})
    assert "informado" in by_code(rep.findings, "COMP-TIPO-001")[0].message
    msgs = " | ".join(f.message for f in by_code(rep.findings, "COMP-OBRIG-001"))
    assert "Resumo" not in msgs  # já coberto pelo verificador abnt
