"""Papel retórico do resumo (NBR 6028) e 'Base do relatório'."""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import ARTIGO
from errei import resumocheck
from errei.report import todo
from errei.report.base import footer_text
from errei.report.render import to_json, to_markdown
from helpers import audit, by_code, make_project

COMPLETO = (
    "A revisão de artigos científicos consome tempo de editores e de pareceristas no Brasil. "
    "Este trabalho tem como objetivo avaliar uma ferramenta automática de auditoria. "
    "Utilizamos um corpus de 120 artigos e aplicamos questionários a 30 revisores. "
    "Os resultados mostram redução de 40% no tempo de revisão. "
    "Conclui-se que a ferramenta apoia a revisão sem substituir o parecerista."
)
INCOMPLETO = (
    "A revisão de artigos científicos consome tempo de editores e pareceristas. "
    "Há muitas ferramentas e diversos estudos sobre o tema em várias áreas do conhecimento. "
    "A literatura discute o assunto há décadas, com abordagens distintas e complementares, "
    "e o tema segue relevante para a comunidade acadêmica brasileira e internacional."
)


def projeto(tmp: Path, resumo: str) -> Path:
    main = (
        "\\documentclass[article]{abntex2}\n\\begin{document}\n\\begin{resumo}\n"
        + resumo.replace("%", "\\%")
        + "\n\n\\textbf{Palavras-chave}: a; b; c.\n\\end{resumo}\n\\end{document}\n"
    )
    return make_project(tmp, {"main.tex": main})


def test_lexical_roles_complete_abstract() -> None:
    frases = [s.strip() + "." for s in COMPLETO.split(". ") if s.strip()]
    papeis = resumocheck.analisar(frases, usar_modelo=False)
    assert [p.papel for p in papeis][1:4] == ["objetivo", "metodo", "resultado"]
    assert resumocheck.elementos(papeis) == {
        "objetivo": True,
        "metodo": True,
        "resultado": True,
        "conclusao": True,
    }


def test_abnt_flags_missing_elements(tmp_path: Path) -> None:
    rep = audit(projeto(tmp_path, INCOMPLETO), checkers={"only": ["abnt"]})
    f = by_code(rep.findings, "ABNT-RESUMO-005")
    assert len(f) == 1
    assert "objetivo" in f[0].message and "método" in f[0].message
    assert f[0].severity.value == "sugestão"  # sem modelo: só sugestão
    assert any("palavras-chave" in e for e in f[0].evidence)


def test_abnt_complete_abstract_ok(tmp_path: Path) -> None:
    rep = audit(projeto(tmp_path, COMPLETO), checkers={"only": ["abnt"]})
    assert not by_code(rep.findings, "ABNT-RESUMO-005")


def test_model_path_used_when_available(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class Fake:
        def classificar(self, frases: list[str]) -> list[tuple[str, float]]:
            return [("contexto", 0.9)] * len(frases)

    monkeypatch.setattr(resumocheck, "unavailable_reason", lambda: None)
    monkeypatch.setattr(resumocheck, "carregar", lambda: Fake())
    rep = audit(projeto(tmp_path, COMPLETO), checkers={"only": ["abnt"]})
    f = by_code(rep.findings, "ABNT-RESUMO-005")[0]
    assert f.severity.value == "aviso"
    assert any("[contexto 90%]" in e for e in f.evidence)
    assert "errei-resumo-v1" in " ".join(rep.meta["base"]["modelos"])


def test_report_base_in_all_outputs() -> None:
    rep = audit(ARTIGO)
    base = rep.meta["base"]
    assert any("NBR 6023:2018" in n for n in base["normas"])
    assert base["fontes"][0].startswith("nenhuma: execução offline")
    assert any("IA online: não utilizada" in m for m in base["modelos"])
    assert "## Base do relatório" in to_markdown(rep)
    assert '"base"' in to_json(rep)
    assert "## Base do relatório" in todo.build(rep, "tcc")
    ft = footer_text(base)
    assert "normas: NBR 6022:2018" in ft and "fontes: offline" in ft


def test_ai_declaration_is_optional(tmp_path: Path) -> None:
    md = todo.build(audit(ARTIGO), "a1")
    linha = next(ln for ln in md.splitlines() if "Declaração de uso de IA" in ln)
    assert linha.startswith("| ℹ️ |") and "opcional" in linha
    assert "- [ ] **Declaração de uso de IA" not in md
