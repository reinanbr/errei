"""Validação de atribuição: obra buscada online + frase do artigo × resumo da fonte."""

from __future__ import annotations

import io
from pathlib import Path

import httpx
import pytest
import respx

from errei import citecheck
from errei.citecheck import Julgamento
from errei.config import Config
from errei.net.client import HttpClient
from errei.pipeline import run
from errei.project import load_project
from helpers import by_code, make_project

ABSTRACT = ("Aspirin was given to 861 patients with Lynch syndrome. Long-term aspirin use "
            "reduced the incidence of colorectal cancer. Adverse events were rare.")


class FakeClf:
    """Julga por palavras-chave, para testar o encanamento sem o modelo real."""

    def julgar(self, afirmacao: str, resumo: str) -> Julgamento:
        a = afirmacao.lower()
        if "aumenta" in a:
            return Julgamento("contradiz", 0.05, 0.91, "Long-term aspirin use reduced the "
                              "incidence of colorectal cancer.")
        if "reduz" in a:
            return Julgamento("sustenta", 0.93, 0.02, "Long-term aspirin use reduced the "
                              "incidence of colorectal cancer.")
        return Julgamento("neutro", 0.2, 0.1, "Adverse events were rare.")


BODY = (
    "A aspirina reduz o câncer colorretal em portadores de síndrome de Lynch \\cite{burn}.\n\n"
    "Por outro lado, a aspirina aumenta o risco de câncer colorretal \\citeonline{burn}.\n\n"
    "O estudo também discutiu custos hospitalares no Reino Unido \\cite[p.~5]{burn}.\n"
)
BIB = ("@article{burn, author={Burn, John}, title={Long-term effect of aspirin on cancer risk "
       "in carriers of hereditary colorectal cancer}, journal={The Lancet}, year={2011}, "
       "volume={378}, pages={2081--2087}, doi={10.1016/S0140-6736(11)61049-0}}")


def project(tmp: Path, body: str = BODY) -> Path:
    return make_project(tmp, {
        "main.tex": "\\documentclass[brazil]{abntex2}\\usepackage[alf]{abntex2cite}\n"
                    "\\begin{document}\n" + body + "\\bibliography{r}\n\\end{document}\n",
        "r.bib": BIB,
    })


def mock_sources(respx_mock: respx.MockRouter, pdf: bytes | None = None) -> None:
    respx_mock.get(url__startswith="https://api.crossref.org/works/10.1016").mock(
        return_value=httpx.Response(200, json={"message": {
            "DOI": "10.1016/S0140-6736(11)61049-0",
            "title": ["Long-term effect of aspirin on cancer risk in carriers of hereditary "
                      "colorectal cancer"],
            "author": [{"family": "Burn", "given": "John"}],
            "issued": {"date-parts": [[2011]]}, "container-title": ["The Lancet"]}}))
    respx_mock.get(url__startswith="https://api.openalex.org/works/doi:").mock(
        return_value=httpx.Response(200, json={
            "title": "Long-term effect of aspirin", "publication_year": 2011,
            "doi": "https://doi.org/10.1016/S0140-6736(11)61049-0",
            "authorships": [{"author": {"display_name": "John Burn"}}],
            "best_oa_location": {"pdf_url": "https://oa.example.org/burn.pdf"},
            "abstract_inverted_index": {w: [i] for i, w in enumerate(ABSTRACT.split())},
        }))
    if pdf is not None:
        respx_mock.get("https://oa.example.org/burn.pdf").mock(
            return_value=httpx.Response(200, content=pdf))
    respx_mock.route().mock(return_value=httpx.Response(404, json={}))


def run_online(root: Path, **refs_cfg: object):  # type: ignore[no-untyped-def]
    over: dict[str, object] = {"online": True, "checkers": {"only": ["refs"]}}
    if refs_cfg:
        over["refs"] = refs_cfg
    cfg = Config.load(root, over, use_user_config=False)
    return run(root, cfg, http=HttpClient(cache_dir=None, intervals={}, default_interval=0,
                                          backoff=0))


@pytest.fixture
def fake_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(citecheck, "unavailable_reason", lambda: None)
    monkeypatch.setattr(citecheck, "carregar", lambda: FakeClf())


def test_cite_context_strips_placeholders(tmp_path: Path) -> None:
    from errei.checkers.refs import cite_context

    p = load_project(project(tmp_path, "Texto “um trecho citado aqui” \\cite[p.~12--13]{burn}. "
                                      "Outra frase.\n"))
    use = next(u for u in p.cite_uses() if u.key == "burn")
    c = cite_context(p, use)
    assert c is not None
    assert c.claim == "Texto “um trecho citado aqui”."
    assert c.quote == "um trecho citado aqui"
    assert c.pages == (12, 13)
    assert c.location == "main.tex:3"


def test_attribution_verdicts(tmp_path: Path, respx_mock: respx.MockRouter,
                              fake_model: None) -> None:
    mock_sources(respx_mock)
    rep = run_online(project(tmp_path))
    ok = by_code(rep.findings, "REFS-ATRIB-001")
    bad = by_code(rep.findings, "REFS-ATRIB-002")
    meh = by_code(rep.findings, "REFS-ATRIB-003")
    assert len(ok) == len(bad) == len(meh) == 1
    assert ok[0].location is not None and ok[0].location.line == 3
    assert bad[0].location is not None and bad[0].location.line == 5
    assert "contradizer" in bad[0].message and any("reduced" in e for e in bad[0].evidence)
    assert "SILVA" not in (ok[0].excerpt or "")  # placeholders removidos
    ref = rep.references[0]
    assert ref["key"] == "burn" and ref["status"] == "confirmada"
    assert ref["abstract"].startswith("Aspirin was given")  # resumo trazido do OpenAlex
    assert ref["authors"] == ["John Burn"]
    assert [u["verdict"] for u in ref["uses"]] == ["sustenta", "contradiz", "neutro"]
    assert "falsa" not in " ".join(f.message for f in rep.findings)


def test_model_missing_degrades(tmp_path: Path, respx_mock: respx.MockRouter) -> None:
    mock_sources(respx_mock)
    rep = run_online(project(tmp_path))
    assert not by_code(rep.findings, "REFS-ATRIB-001")
    dep = [f for f in by_code(rep.findings, "CORE-DEP-001") if "atribuições" in f.message]
    assert dep and rep.references[0]["uses"][0]["verdict"] == "não avaliada"
    assert by_code(rep.findings, "REFS-EXIST-001")  # existência continua verificada


def test_offline_has_no_references(tmp_path: Path) -> None:
    cfg = Config.load(project(tmp_path), {"checkers": {"only": ["refs"]}},
                      use_user_config=False)
    rep = run(tmp_path, cfg)
    assert rep.references == []


def _pdf_with(text_by_page: list[str]) -> bytes:
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    for t in text_by_page:
        c.drawString(72, 720, t)
        c.showPage()
    c.save()
    return buf.getvalue()


def test_fulltext_quote_page_check(tmp_path: Path, respx_mock: respx.MockRouter,
                                   fake_model: None) -> None:
    pdf = _pdf_with(["Introduction page", "We found that aspirin reduced cancer by sixty "
                     "percent overall", "Methods"])
    mock_sources(respx_mock, pdf)
    body = ("Segundo o estudo, “aspirin reduced cancer by sixty percent overall” "
            "\\cite[p.~7]{burn}.\n\n"
            "Também afirma que “bananas cure every known disease forever” \\cite[p.~2]{burn}.\n")
    rep = run_online(project(tmp_path, body), texto_completo=True)
    q2 = by_code(rep.findings, "REFS-QUOTE-002")
    msgs = " | ".join(f.message for f in q2)
    assert "página 2" in msgs and "p. 7" in msgs
    assert "não localizado" in msgs


def test_fulltext_off_by_default(tmp_path: Path, respx_mock: respx.MockRouter,
                                 fake_model: None) -> None:
    mock_sources(respx_mock, _pdf_with(["x"]))
    body = "Diz “aspirin reduced cancer by sixty percent overall” \\cite[p.~7]{burn}.\n"
    rep = run_online(project(tmp_path, body))
    assert not [f for f in rep.findings if f.code.startswith("REFS-QUOTE")]
    assert not [c for c in respx_mock.calls if "oa.example.org" in str(c.request.url)]


def test_references_in_json_and_markdown(tmp_path: Path, respx_mock: respx.MockRouter,
                                          fake_model: None) -> None:
    import json

    from errei.report.render import to_json, to_markdown

    mock_sources(respx_mock)
    rep = run_online(project(tmp_path))
    data = json.loads(to_json(rep))
    ref = data["references"][0]
    assert ref["key"] == "burn" and ref["uses"][1]["verdict"] == "contradiz"
    assert ref["uses"][1]["evidence"].startswith("Long-term aspirin")
    md = to_markdown(rep)
    assert "## Referências verificadas" in md and "| contradiz" in md


def test_progress_messages(tmp_path: Path, respx_mock: respx.MockRouter,
                           fake_model: None) -> None:
    mock_sources(respx_mock)
    root = project(tmp_path)
    msgs: list[str] = []
    cfg = Config.load(root, {"online": True, "checkers": {"only": ["refs"]}},
                      use_user_config=False)
    run(root, cfg, http=HttpClient(cache_dir=None, intervals={}, default_interval=0, backoff=0),
        progress=msgs.append)
    assert "verificando referência 1/1 online: burn" in msgs
    assert any("validando 3 citação(ões) de burn" in m for m in msgs)
