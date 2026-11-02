"""Sugestões de obras nacionais + IA online (Gemini) com rede simulada."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from errei.checkers.nacionais import is_foreign, keywords
from errei.config import Config
from errei.net import gemini
from errei.net.client import HttpClient
from errei.pipeline import run
from errei.project import load_project
from helpers import by_code, make_project

BODY = (
    "A legibilidade de textos técnicos pode ser medida por fórmulas baseadas no tamanho "
    "das frases e das palavras \\cite{flesch}.\n\n"
    "Fórmulas de legibilidade foram adaptadas ao português \\cite{martins}.\n"
)
BIB = (
    "@article{flesch, author={Flesch, Rudolf}, title={A new readability yardstick}, "
    "journal={Journal of Applied Psychology}, year={1948}}\n"
    "@techreport{martins, author={Martins, Teresa}, title={Readability formulas applied to "
    "textbooks}, institution={Universidade de São Paulo}, year={1996}}\n"
)

BR_WORK = {
    "title": "Legibilidade de textos técnicos: fórmulas baseadas no tamanho das frases",
    "publication_year": 2020,
    "type": "article",
    "language": "pt",
    "doi": "https://doi.org/10.1590/legib.2020",
    "authorships": [{"author": {"display_name": "Ana Souza"}}],
    "primary_location": {"source": {"display_name": "Revista Brasileira"}},
    "abstract_inverted_index": {
        w: [i]
        for i, w in enumerate(
            [
                "Avaliamos",
                "a",
                "legibilidade",
                "de",
                "textos",
                "técnicos",
                "com",
                "fórmulas",
                "baseadas",
                "no",
                "tamanho",
                "das",
                "frases",
                "e",
                "das",
                "palavras",
            ]
        )
    },
}
OFF_TOPIC = {
    "title": "Cultivo de soja no cerrado",
    "publication_year": 2019,
    "type": "article",
    "doi": "https://doi.org/10.1590/soja",
    "authorships": [{"author": {"display_name": "José Lima"}}],
}
IA_REAL = {
    "title": "Manual de legibilidade em português",
    "publication_year": 2015,
    "type": "book",
    "doi": "",
    "id": "https://openalex.org/W1",
    "authorships": [{"author": {"display_name": "Carla Mendes"}}],
}


def gemini_reply(data: dict[str, Any]) -> httpx.Response:
    return httpx.Response(
        200, json={"candidates": [{"content": {"parts": [{"text": json.dumps(data)}]}}]}
    )


def router(respx_mock: respx.MockRouter, calls: list[httpx.Request]) -> None:
    def openalex(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        q = request.url.params.get("search", "")
        flt = request.url.params.get("filter", "")
        if "countries:BR" in flt:
            return httpx.Response(200, json={"results": [BR_WORK, OFF_TOPIC]})
        if "Manual de legibilidade" in q:
            return httpx.Response(200, json={"results": [IA_REAL]})
        return httpx.Response(200, json={"results": []})

    respx_mock.get(url__startswith="https://api.openalex.org/works").mock(side_effect=openalex)
    respx_mock.get(url__startswith="https://openlibrary.org/").mock(
        return_value=httpx.Response(200, json={"docs": []})
    )
    respx_mock.get(url__startswith="https://api.crossref.org/").mock(
        return_value=httpx.Response(200, json={"message": {"items": []}})
    )

    def gem(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return gemini_reply(
            {
                "consultas": ["legibilidade textos técnicos"],
                "referencias": [
                    {"titulo": "Manual de legibilidade em português", "autores": "Carla Mendes"},
                    {"titulo": "Obra totalmente inventada sobre legibilidade", "autores": "X"},
                ],
            }
        )

    respx_mock.post(url__startswith="https://generativelanguage.googleapis.com/").mock(
        side_effect=gem
    )


def run_nac(root: Path, **over: Any):  # type: ignore[no-untyped-def]
    cfg = Config.load(
        root, {"online": True, "checkers": {"only": ["nacionais"]}, **over}, use_user_config=False
    )
    http = HttpClient(cache_dir=None, intervals={}, default_interval=0, backoff=0, retries=0)
    return run(root, cfg, http=http)


def project(tmp: Path, extra: dict[str, str] | None = None) -> Path:
    files = {
        "main.tex": "\\documentclass[brazil]{abntex2}\n\\begin{document}\n"
        + BODY
        + "\\bibliography{r}\n\\end{document}\n",
        "r.bib": BIB,
        **(extra or {}),
    }
    return make_project(tmp, files)


def test_foreign_detection(tmp_path: Path) -> None:
    p = load_project(project(tmp_path))
    by = {e.key: is_foreign(e) for e in p.bib_entries}
    assert by == {"flesch": True, "martins": False}  # USP: autoria brasileira
    assert "legibilidade" in keywords("A legibilidade de textos técnicos pode ser medida")


def test_suggests_brazilian_work_without_ai(tmp_path: Path, respx_mock: respx.MockRouter) -> None:
    calls: list[httpx.Request] = []
    router(respx_mock, calls)
    rep = run_nac(project(tmp_path))
    sug = by_code(rep.findings, "NAC-SUG-001")
    assert len(sug) == 1 and "'flesch'" in sug[0].message
    ev = " ".join(sug[0].evidence)
    assert "Legibilidade de textos técnicos" in ev and "10.1590/legib.2020" in ev
    assert "soja" not in ev  # fora do tema
    assert sug[0].location is not None and sug[0].location.line == 3
    assert not any("generativelanguage" in str(c.url) for c in calls)
    assert "ia_online" not in rep.meta


def test_offline_does_nothing(tmp_path: Path) -> None:
    cfg = Config.load(
        project(tmp_path), {"checkers": {"only": ["nacionais"]}}, use_user_config=False
    )
    rep = run(tmp_path, cfg)
    assert not by_code(rep.findings, "NAC-SUG-001")


def test_ai_suggestions_verified_and_hallucinations_discarded(
    tmp_path: Path, respx_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "segredo-de-teste")
    calls: list[httpx.Request] = []
    router(respx_mock, calls)
    rep = run_nac(project(tmp_path), ia_online={"enabled": True})
    sug = by_code(rep.findings, "NAC-SUG-001")[0]
    ev = " | ".join(sug.evidence)
    assert "Manual de legibilidade em português" in ev and "sugerida pela IA" in ev
    assert "inventada" not in ev
    assert "1 sugestão(ões) da IA descartada(s)" in ev
    assert rep.meta["ia_online"]["chamadas"] == 1
    assert any("Gemini" in lim for lim in rep.limitations)
    post = next(c for c in calls if "generativelanguage" in str(c.url))
    assert post.headers["x-goog-api-key"] == "segredo-de-teste"
    assert "segredo" not in str(post.url)
    assert "segredo" not in json.dumps(rep.meta)


def test_project_config_cannot_enable_ai(
    tmp_path: Path, respx_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    calls: list[httpx.Request] = []
    router(respx_mock, calls)
    root = project(tmp_path, {".errei.toml": "[ia_online]\nenabled = true\n"})
    rep = run_nac(root)
    assert not any("generativelanguage" in str(c.url) for c in calls)
    assert "ia_online" not in rep.meta


def test_ai_without_key_warns(tmp_path: Path, respx_mock: respx.MockRouter) -> None:
    router(respx_mock, [])
    rep = run_nac(project(tmp_path), ia_online={"enabled": True})
    assert any("chave do Gemini" in f.message for f in by_code(rep.findings, "CORE-DEP-001"))


def test_ai_output_is_truncated() -> None:
    long = " ".join(["palavra"] * 80)
    out = gemini._clean({"orientacoes": [{"elemento": "x", "itens": [long] * 20}]})
    itens = out["orientacoes"][0]["itens"]
    assert len(itens) == gemini.MAX_ITEMS
    assert len(itens[0].split()) == gemini.MAX_ITEM_WORDS and itens[0].endswith("…")


def test_completude_ai_guidance(
    tmp_path: Path, respx_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    respx_mock.post(url__startswith="https://generativelanguage.googleapis.com/").mock(
        return_value=gemini_reply(
            {"orientacoes": [{"elemento": "Metodologia", "itens": ["Descreva a amostra"]}]}
        )
    )
    cfg = Config.load(
        project(tmp_path),
        {"online": True, "checkers": {"only": ["completude"]}, "ia_online": {"enabled": True}},
        use_user_config=False,
    )
    http = HttpClient(cache_dir=None, intervals={}, default_interval=0, backoff=0, retries=0)
    rep = run(tmp_path, cfg, http=http)
    ia = by_code(rep.findings, "COMP-IA-001")
    assert ia and "Metodologia" in ia[0].message and "• Descreva a amostra" in ia[0].evidence


def test_cli_ia_online_requires_online(tmp_path: Path) -> None:
    from helpers import cli

    res = cli(str(project(tmp_path)), "--ia-online", "--no-user-config")
    assert res.exit_code == 2
