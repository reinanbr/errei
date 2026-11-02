from __future__ import annotations

import json
import time
from pathlib import Path
from urllib.parse import urlencode

import httpx
import pytest
import respx

from conftest import ARTIGO, FIXTURES, line_of
from errei.config import Config
from errei.net.client import HttpClient
from errei.pipeline import run
from helpers import audit, by_code, make_project

RECORDED = json.loads((FIXTURES / "http" / "refs_artigo_exemplo.json").read_text())


def _key(request: httpx.Request) -> str:
    base = str(request.url.copy_with(query=None))
    items = sorted((k, v) for k, v in request.url.params.multi_items() if k != "mailto")
    return base + ("?" + urlencode(items) if items else "")


def replay(table: dict[str, tuple[int, object]]):  # type: ignore[no-untyped-def]
    def handler(request: httpx.Request) -> httpx.Response:
        key = _key(request)
        if key not in table:
            return httpx.Response(404, json={"status": "not-found", "key": key})
        status, body = table[key]
        if isinstance(body, str):
            return httpx.Response(status, text=body)
        return httpx.Response(status, json=body)

    return handler


def recorded_table() -> dict[str, tuple[int, object]]:
    return {r["key"]: (r["status"], r["body"]) for r in RECORDED}


def client(tmp_path: Path) -> HttpClient:
    return HttpClient(
        cache_dir=tmp_path / "c", intervals={}, default_interval=0, backoff=0.0, retries=2
    )


def online_report(root: Path, http: HttpClient):  # type: ignore[no-untyped-def]
    cfg = Config.load(root, {"online": True, "checkers": {"only": ["refs"]}}, use_user_config=False)
    return run(root, cfg, http=http)


def test_online_classifies_fixture(tmp_path: Path, respx_mock: respx.MockRouter) -> None:
    respx_mock.route().mock(side_effect=replay(recorded_table()))
    rep = online_report(ARTIGO, client(tmp_path))
    bib = ARTIGO / "referencias.bib"
    status = {}
    for f in rep.findings:
        if f.code.startswith("REFS-EXIST"):
            key = f.message.split("'")[1]
            status[key] = (f.code, f.location.line if f.location else None, f.severity.value)
    assert status["lecun2015"][0] == "REFS-EXIST-001"
    assert status["devlin2019"][0] == "REFS-EXIST-001"
    assert status["flesch1948"][0] == "REFS-EXIST-001"
    assert status["inventado2021"] == (
        "REFS-EXIST-003",
        line_of(bib, "@article{inventado2021"),
        "aviso",
    )
    # techreport sem DOI: pouco indexado → info, nunca "falsa"
    assert status["martins1996"][0] == "REFS-EXIST-003"
    assert status["martins1996"][2] == "info"
    inv = next(
        f for f in rep.findings if "inventado2021" in f.message and f.code == "REFS-EXIST-003"
    )
    assert any("10.9999/rbei.2021.0042" in e for e in inv.evidence)
    assert "falsa" not in inv.message and inv.confidence is not None


def _crossref(title: str, family: str, year: int, **extra: object) -> dict[str, object]:
    msg: dict[str, object] = {
        "DOI": "10.1234/x",
        "title": [title],
        "author": [{"family": family, "given": "A"}],
        "issued": {"date-parts": [[year]]},
        "container-title": ["Journal of Tests"],
    }
    msg.update(extra)
    return {"message": msg}


def _bib_project(tmp: Path, entry: str) -> Path:
    return make_project(
        tmp,
        {
            "main.tex": "\\documentclass{article}\\begin{document}\\cite{k}"
            "\\bibliography{r}\\end{document}",
            "r.bib": entry,
        },
    )


def test_divergent_and_retracted(tmp_path: Path, respx_mock: respx.MockRouter) -> None:
    root = _bib_project(
        tmp_path,
        "@article{k, author={Souza, A.}, title={Um estudo de caso "
        "sobre testes}, journal={Journal of Tests}, year={2018}, "
        "doi={10.1234/x}}",
    )
    respx_mock.get("https://api.crossref.org/works/10.1234/x").mock(
        return_value=httpx.Response(
            200,
            json=_crossref(
                "Um estudo de caso sobre testes",
                "Souza",
                2020,
                **{"updated-by": [{"type": "retraction", "DOI": "10.1234/r"}]},
            ),
        )
    )
    rep = online_report(root, client(tmp_path))
    div = by_code(rep.findings, "REFS-EXIST-002")
    assert div and any("ano: 2018 × 2020" in e for e in div[0].evidence)
    assert by_code(rep.findings, "REFS-RETRACT-001")


def test_doi_points_to_other_work(tmp_path: Path, respx_mock: respx.MockRouter) -> None:
    root = _bib_project(
        tmp_path,
        "@article{k, author={Souza, A.}, title={Redes neurais "
        "para revisão de textos}, journal={J}, year={2020}, doi={10.1234/x}}",
    )
    respx_mock.get("https://api.crossref.org/works/10.1234/x").mock(
        return_value=httpx.Response(
            200, json=_crossref("Cultivation of tomatoes in greenhouses", "Lee", 2001)
        )
    )
    respx_mock.get(url__startswith="https://api.crossref.org/works?").mock(
        return_value=httpx.Response(200, json={"message": {"items": []}})
    )
    respx_mock.get(url__startswith="https://api.openalex.org/works?").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    rep = online_report(root, client(tmp_path))
    nf = by_code(rep.findings, "REFS-EXIST-003")
    assert nf and any("pertence a outra obra" in e for e in nf[0].evidence)


def test_network_failure_degrades_gracefully(tmp_path: Path, respx_mock: respx.MockRouter) -> None:
    root = _bib_project(
        tmp_path,
        "@article{k, author={Souza, A.}, title={Um título "
        "qualquer de teste}, journal={J}, year={2020}, doi={10.1234/x}}",
    )
    respx_mock.route().mock(side_effect=httpx.ConnectError("sem rede"))
    rep = online_report(root, client(tmp_path))
    assert not by_code(rep.findings, "CORE-CHECKER-001")
    assert by_code(rep.findings, "CORE-NET-001")
    assert not by_code(rep.findings, "REFS-EXIST-003")  # sem resposta não há veredito


def test_retry_after_429_and_cache(tmp_path: Path, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get("https://api.crossref.org/works/10.1/a").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "0"}),
            httpx.Response(200, json={"message": {"title": ["T"]}}),
        ]
    )
    http = client(tmp_path)
    assert http.get_json("https://api.crossref.org/works/10.1/a") == (
        200,
        {"message": {"title": ["T"]}},
    )
    assert route.call_count == 2
    http2 = client(tmp_path)  # novo cliente, mesmo cache em disco
    assert http2.get_json("https://api.crossref.org/works/10.1/a") is not None
    assert route.call_count == 2


def test_user_agent_and_mailto(tmp_path: Path, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(url__startswith="https://api.openalex.org/").mock(
        return_value=httpx.Response(200, json={})
    )
    http = HttpClient(cache_dir=None, email="pessoa@exemplo.org", intervals={}, default_interval=0)
    http.get_json("https://api.openalex.org/works", {"search": "x"})
    req = route.calls[0].request
    assert "mailto:pessoa@exemplo.org" in req.headers["User-Agent"]
    assert req.url.params["mailto"] == "pessoa@exemplo.org"


def test_rate_limiter_spaces_requests() -> None:
    from errei.net.client import RateLimiter

    rl = RateLimiter({"h": 0.05})
    t0 = time.monotonic()
    for _ in range(3):
        rl.wait("h")
    assert time.monotonic() - t0 >= 0.09


def test_offline_refs_rules(tmp_path: Path) -> None:
    root = make_project(
        tmp_path,
        {
            "main.tex": "\\documentclass{article}\\begin{document}\\cite{a,b}\\citeonline{zz}"
            "\\bibliography{r}\\end{document}",
            "r.bib": "@article{a, author={X, Y}, title={T}, journal={J}, year={2020}, "
            "doi={https://doi.org/10.1000/abc}}\n"
            "@article{b, author={X, Y}, title={T2}, year={3020}, doi={11.2/x}}\n"
            "@misc{c, title={nunca}, eprint={99}, archiveprefix={arXiv}}\n",
        },
    )
    f = audit(root, checkers={"only": ["refs"]}).findings
    assert [x.message for x in by_code(f, "REFS-CITE-001")] == [
        "\\citeonline{zz}: chave inexistente no .bib"
    ]
    assert by_code(f, "REFS-DOI-003") and by_code(f, "REFS-DOI-001")
    assert by_code(f, "REFS-YEAR-001") and by_code(f, "REFS-ARXIV-001")
    assert "journal" in by_code(f, "REFS-FIELD-001")[0].message
    assert by_code(f, "REFS-BIB-001")[0].message == "entrada 'c' nunca citada"


@pytest.mark.network
def test_real_online_fixture() -> None:  # pragma: no cover - rede real, desligado por padrão
    cfg = Config.load(
        ARTIGO, {"online": True, "checkers": {"only": ["refs"]}}, use_user_config=False
    )
    rep = run(ARTIGO, cfg)
    codes = {
        f.message.split("'")[1]: f.code for f in rep.findings if f.code.startswith("REFS-EXIST")
    }
    assert codes["lecun2015"] == "REFS-EXIST-001"
    assert codes["inventado2021"] == "REFS-EXIST-003"
