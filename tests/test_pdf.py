from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader

from conftest import ARTIGO
from errei.report.highlights import improvements, top_problems
from errei.report.pdf import write_pdf
from helpers import audit, cli


def pdf_text(path: Path) -> str:
    return "\n".join(p.extract_text() or "" for p in PdfReader(str(path)).pages)


def test_highlights_prioritize_and_diversify() -> None:
    rep = audit(ARTIGO)
    probs = top_problems(rep, 12)
    assert probs[0].severity.value == "erro"
    assert len({f.checker for f in probs}) >= 4
    assert all(f.severity.value in ("erro", "aviso") for f in probs)
    assert all(f.severity.value == "sugestão" for f in improvements(rep, 10))


def test_write_pdf(tmp_path: Path) -> None:
    rep = audit(ARTIGO)
    rep.references = [
        {
            "key": "burn",
            "status": "confirmada",
            "bib_location": "r.bib:1",
            "title": "Long-term effect of aspirin",
            "authors": ["John Burn"],
            "year": 2011,
            "venue": "The Lancet",
            "source": "Crossref",
            "url": "https://doi.org/10.1/x",
            "abstract": "Aspirin reduced cancer.",
            "divergences": [],
            "uses": [
                {
                    "location": "s.tex:3",
                    "claim": "A aspirina reduz o câncer → sim",
                    "verdict": "sustenta",
                    "score": 0.93,
                    "evidence": "Aspirin reduced cancer.",
                }
            ],
        }
    ]
    out = tmp_path / "r.pdf"
    write_pdf(rep, out)
    assert out.read_bytes().startswith(b"%PDF")
    text = pdf_text(out)
    for needle in (
        "Relatório do errei",
        "Principais problemas",
        "Possíveis melhorias",
        "Referências verificadas",
        "Long-term effect of aspirin",
        "sustenta",
        "Métricas",
        "Todos os achados",
        "Limitações",
        "secoes/metodologia.tex",
    ):
        assert needle in text, needle
    assert "→" in text  # fonte Unicode embutida
    assert len(PdfReader(str(out)).pages) >= 4


def test_cli_pdf_flag_keeps_terminal_output(tmp_path: Path) -> None:
    out = tmp_path / "rel.pdf"
    res = cli(str(ARTIGO), "--pdf", str(out), "--resumo", "--no-user-config")
    assert res.exit_code == 1
    assert out.is_file() and "Principais problemas" in res.stdout
    assert "Limitações" in res.stdout
    assert "secoes/metodologia.tex:3" in res.stdout


def test_cli_format_pdf(tmp_path: Path) -> None:
    out = tmp_path / "x.pdf"
    res = cli(str(ARTIGO), "--format", "pdf", "--out", str(out), "--no-user-config")
    assert res.exit_code == 1 and out.read_bytes().startswith(b"%PDF")
    assert "Principais problemas" in res.stdout
