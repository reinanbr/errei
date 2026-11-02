from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from conftest import ARTIGO, FIXTURES
from errei.config import Config, ConfigError
from errei.net.client import HttpClient
from errei.pipeline import run
from errei.qualis import load_qualis, parse_target
from helpers import audit, by_code, cli

CSV = FIXTURES / "qualis.csv"


def test_load_qualis_latin1_semicolon() -> None:
    t = load_qualis(CSV, "2025-07-01")
    assert t.encoding in ("cp1252", "latin-1")
    assert len(t.rows) == 5  # linha com estrato inválido é descartada
    assert {r.estrato for r in t.by_issn("1414-5685")} == {"A2", "A3"}
    assert [
        r.estrato
        for r in t.by_title("Revista Brasileira de Informatica na Educacao")
        if r.area == "EDUCAÇÃO"
    ] == ["A2"]
    assert t.by_title("Nature")[0].issn == "00280836"
    assert t.by_title("Revista Totalmente Diferente") == []


def test_parse_target() -> None:
    assert parse_target("ISSN 1414-5685") == ("issn", "14145685")
    assert parse_target("1234-567x") == ("issn", "1234567X")
    assert parse_target("Nature") == ("title", "Nature")


def test_invalid_csv(tmp_path: Path) -> None:
    bad = tmp_path / "x.csv"
    bad.write_text("a,b\n1,2\n")
    with pytest.raises(ConfigError):
        load_qualis(bad)
    with pytest.raises(ConfigError):
        load_qualis(CSV, "01/07/2025")
    res = cli(str(ARTIGO), "--qualis-csv", str(bad), "--only", "periodico")
    assert res.exit_code == 2
    assert cli(str(ARTIGO), "--qualis-csv", str(tmp_path / "nao.csv")).exit_code == 2


def test_qualis_by_issn_and_area() -> None:
    rep = audit(
        ARTIGO,
        checkers={"only": ["periodico"]},
        periodico={
            "qualis_csv": str(CSV),
            "periodico": "ISSN 1414-5685",
            "area": "Educação",
            "qualis_data": "2025-07-01",
        },
    )
    q = by_code(rep.findings, "PERIOD-QUALIS-001")
    assert len(q) == 1 and "estrato A2" in q[0].message and "2025-07-01" in q[0].message
    assert "do periódico, não do artigo" in q[0].message
    assert not by_code(rep.findings, "PERIOD-QUALIS-003")
    assert rep.meta["qualis_data"] == "2025-07-01"


def test_qualis_all_areas_and_missing_date() -> None:
    rep = audit(
        ARTIGO,
        checkers={"only": ["periodico"]},
        periodico={
            "qualis_csv": str(CSV),
            "periodico": "Revista Brasileira de Informática na Educação",
        },
    )
    assert len(by_code(rep.findings, "PERIOD-QUALIS-001")) == 2
    assert by_code(rep.findings, "PERIOD-QUALIS-003")
    assert rep.meta["qualis_data_origem"] == "data de modificação do arquivo"


def test_qualis_not_found_and_wrong_area() -> None:
    rep = audit(
        ARTIGO,
        checkers={"only": ["periodico"]},
        periodico={"qualis_csv": str(CSV), "periodico": "ISSN 0000-0000"},
    )
    assert by_code(rep.findings, "PERIOD-QUALIS-002")
    rep = audit(
        ARTIGO,
        checkers={"only": ["periodico"]},
        periodico={"qualis_csv": str(CSV), "periodico": "Nature", "area": "Direito"},
    )
    assert "áreas:" in by_code(rep.findings, "PERIOD-QUALIS-002")[0].message


def test_refs_in_qualis() -> None:
    rep = audit(ARTIGO, checkers={"only": ["periodico"]}, periodico={"qualis_csv": str(CSV)})
    f = by_code(rep.findings, "PERIOD-REFS-001")[0]
    assert "A1: 3" in f.message
    assert by_code(rep.findings, "PERIOD-QUALIS-004")


def test_readiness_components_and_disclaimer() -> None:
    rep = audit(ARTIGO)
    ready = by_code(rep.findings, "PERIOD-READY-001")[0]
    assert "NÃO prevê aceitação nem estrato" in ready.message
    g = next(g for g in rep.metrics if g.checker == "periodico")
    names = [m.name for m in g.metrics]
    assert names == [
        "Estrutura IMRaD",
        "Resumo/abstract/palavras-chave",
        "Qualidade das referências",
        "Tamanho",
        "Normas ABNT",
        "Escrita e LaTeX",
        "TOTAL",
    ]
    total = float(str(g.metrics[-1].value).split("/")[0])
    parts = sum(float(str(m.value).split("/")[0]) for m in g.metrics[:-1])
    assert abs(total - parts) < 1 and 0 <= total <= 100


def test_openalex_enrichment(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(url__startswith="https://api.openalex.org/sources").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": "https://openalex.org/S1",
                        "display_name": "Revista X",
                        "summary_stats": {"h_index": 42, "2yr_mean_citedness": 1.5},
                        "works_count": 900,
                        "is_oa": True,
                        "is_in_doaj": True,
                    }
                ]
            },
        )
    )
    respx_mock.route().mock(return_value=httpx.Response(404, json={}))
    cfg = Config.load(
        ARTIGO,
        {
            "online": True,
            "checkers": {"only": ["periodico"]},
            "periodico": {"periodico": "ISSN 1414-5685"},
        },
        use_user_config=False,
    )
    rep = run(
        ARTIGO, cfg, http=HttpClient(cache_dir=None, intervals={}, default_interval=0, backoff=0)
    )
    oa = by_code(rep.findings, "PERIOD-OA-001")[0]
    assert "h-index 42" in oa.message and "DOAJ" in oa.message


def test_cli_qualis_flags_in_report(tmp_path: Path) -> None:
    out = tmp_path / "r.json"
    res = cli(
        str(ARTIGO),
        "-f",
        "json",
        "-o",
        str(out),
        "--qualis-csv",
        str(CSV),
        "--periodico",
        "ISSN 1414-5685",
        "--qualis-data",
        "2025-07-01",
    )
    assert res.exit_code in (0, 1)
    data = json.loads(out.read_text())
    assert data["meta"]["flags"]["periodico"] == "ISSN 1414-5685"
    assert data["meta"]["qualis_data"] == "2025-07-01"
    md = tmp_path / "r.md"
    cli(
        str(ARTIGO),
        "-f",
        "md",
        "-o",
        str(md),
        "--qualis-csv",
        str(CSV),
        "--qualis-data",
        "2025-07-01",
    )
    assert "CSV Qualis" in md.read_text() and "2025-07-01" in md.read_text()
