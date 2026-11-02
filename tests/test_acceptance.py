"""Critérios de aceite sobre a fixture ``artigo_exemplo``."""

from __future__ import annotations

import socket
from collections.abc import Callable
from pathlib import Path

import pytest

from conftest import ARTIGO, line_of
from errei.config import Config
from errei.pipeline import run
from helpers import audit_json, cli

INTRO = ARTIGO / "secoes" / "introducao.tex"
METOD = ARTIGO / "secoes" / "metodologia.tex"
RESULT = ARTIGO / "secoes" / "resultados.tex"
CONCL = ARTIGO / "secoes" / "conclusao.tex"
MAIN = ARTIGO / "main.tex"
BIB = ARTIGO / "referencias.bib"

# (código, arquivo, trecho que localiza a linha esperada)
PLANTED_OFFLINE: list[tuple[str, Path, str]] = [
    ("LATEX-REF-001", METOD, "\\ref{fig:inexistente}"),
    ("LATEX-FLOAT-001", METOD, "\\begin{figure}"),
    ("LATEX-TODO-001", INTRO, "% TODO revisar"),
    ("REFS-CITE-001", INTRO, "silva2099"),
    ("REFS-BIB-002", BIB, "@article{lecun2015,\n  author  = {LeCun, Y."),
    ("REFS-BIB-001", BIB, "@book{nuncacitado2010"),
    ("REFS-ISBN-001", BIB, "isbn   = {978-85-0000-000-1}"),
    ("ABNT-RESUMO-002", MAIN, "Este trabalho apresenta uma ferramenta"),
    ("ABNT-CIT-001", METOD, "apud"),
    ("PTBR-CRASE-001", INTRO, "devido à fatores"),
    ("PTBR-CRASE-001", INTRO, "À partir de 2020"),
    ("PTBR-ORTO-001", INTRO, "A idéia central"),
    ("PTBR-VICIO-001", INTRO, "a nível de parágrafo"),
    ("ESCRITA-SIGLA-001", INTRO, "Ferramentas de PLN"),
    ("PLAGIO-INT-001", CONCL, "O objetivo deste trabalho"),
    ("IA-IND-001", RESULT, "É importante ressaltar"),
]


@pytest.fixture(scope="module")
def offline_report() -> dict:  # type: ignore[type-arg]
    return audit_json(ARTIGO)


@pytest.mark.parametrize(
    ("code", "path", "snippet"), PLANTED_OFFLINE, ids=[p[0] for p in PLANTED_OFFLINE]
)
def test_offline_detects_planted(
    offline_report: dict,
    code: str,
    path: Path,  # type: ignore[type-arg]
    snippet: str,
) -> None:
    rel = path.relative_to(ARTIGO).as_posix()
    line = line_of(path, snippet)
    hits = [
        f
        for f in offline_report["findings"]
        if f["code"] == code and f["file"] == rel and f["line"] == line
    ]
    assert hits, (
        f"{code} não detectado em {rel}:{line}; achados com o código: "
        f"{[(f['file'], f['line']) for f in offline_report['findings'] if f['code'] == code]}"
    )


def test_report_has_limitations(offline_report: dict) -> None:  # type: ignore[type-arg]
    assert offline_report["limitations"]
    assert offline_report["meta"]["online"] is False


def test_never_modifies_article(readonly_guard: Callable[[Path], None], tmp_path: Path) -> None:
    readonly_guard(ARTIGO)
    for fmt in ("term", "md", "json"):
        res = cli(str(ARTIGO), "--format", fmt, "--out", str(tmp_path / f"r.{fmt}"))
        assert res.exit_code in (0, 1)
    cli(str(ARTIGO))


def test_offline_opens_no_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[object] = []
    real_init = socket.socket.__init__

    def spy(self: socket.socket, *a: object, **k: object) -> None:
        opened.append(a)
        real_init(self, *a, **k)  # type: ignore[arg-type]

    monkeypatch.setattr(socket.socket, "__init__", spy)
    report = run(ARTIGO, Config.load(ARTIGO, use_user_config=False))
    assert report.findings
    assert opened == [], f"sockets abertos sem --online: {opened}"


def test_cli_online_classifies_references(respx_mock) -> None:  # type: ignore[no-untyped-def]
    """``errei . --online``: reais → confirmadas; inventada → não encontrada."""
    from test_refs import recorded_table, replay

    respx_mock.route().mock(side_effect=replay(recorded_table()))
    data = audit_json(ARTIGO, "--online", "--only", "refs")
    assert data["meta"]["online"] is True
    exist = {
        f["message"].split("'")[1]: f
        for f in data["findings"]
        if f["code"].startswith("REFS-EXIST")
    }
    for key in ("lecun2015", "devlin2019", "flesch1948"):
        assert exist[key]["code"] == "REFS-EXIST-001", key
    inv = exist["inventado2021"]
    assert inv["code"] == "REFS-EXIST-003"
    assert inv["line"] == line_of(BIB, "@article{inventado2021")
    assert "não verificada" in inv["message"]
