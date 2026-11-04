"""Localizador de texto completo (net/textocompleto.py) com HTTP falso, sem rede."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from errei.net import textocompleto as tcm

PDF = (Path(__file__).parent / "fixtures" / "literatura" / "texto_aberto.pdf").read_bytes()
DOI = "10.1590/abc.2020"


class FakeHttp:
    def __init__(self, text: dict[str, tuple[int, str]], json: dict[str, Any], pdf: set[str]):
        self.text, self.json, self.pdf = text, json, pdf
        self.calls: list[str] = []
        self.delays: dict[str, float] = {}
        self.last_url: dict[str, str] = {}

    def get_text(self, url: str, params: Any = None, **_: Any) -> tuple[int, str] | None:
        self.calls.append(url)
        return self.text.get(url, (404, ""))

    def get_json(self, url: str, params: Any = None, **_: Any) -> tuple[int, Any] | None:
        self.calls.append(url)
        return (200, self.json[url]) if url in self.json else (404, None)

    def get_bytes(self, url: str, **_: Any) -> bytes | None:
        self.calls.append(url)
        return PDF if url in self.pdf else None

    def respeitar_crawl_delay(self, host: str, s: float) -> None:
        self.delays[host] = s


LANDING = (
    '<html><head><meta name="citation_title" content="x">'
    '<meta name="citation_pdf_url" content="https://www.scielo.br/j/abc/a/1/?format=pdf&amp;lang=pt">'
    "</head></html>"
)


def test_ordem_das_fontes_e_sem_repeticao() -> None:
    oa = "https://api.openalex.org/works/doi:10.1590/abc.2020"
    http = FakeHttp(
        {f"https://doi.org/{DOI}": (200, LANDING)},
        {
            oa: {"oa_locations": [{"pdf_url": "https://repo.example.org/a.pdf", "license": ""}]},
            f"{tcm.UNPAYWALL}/{DOI}": {
                "oa_locations": [
                    {"url_for_pdf": "https://repo.example.org/a.pdf", "license": "cc-by"},
                    {"url_for_pdf": "https://outro.example.org/b.pdf", "license": "cc-by"},
                ]
            },
        },
        set(),
    )
    locais = tcm.localizar(http, doi=DOI, email="x@example.org")
    assert [(loc.origem, loc.url) for loc in locais] == [
        ("OpenAlex", "https://repo.example.org/a.pdf"),
        ("Unpaywall", "https://outro.example.org/b.pdf"),
        ("página do DOI", "https://www.scielo.br/j/abc/a/1/?format=pdf&lang=pt"),
    ]


def test_sem_email_nao_consulta_unpaywall() -> None:
    http = FakeHttp({}, {}, set())
    tcm.localizar(http, doi=DOI)
    assert not any("unpaywall" in c for c in http.calls)


def test_meta_tag_com_atributos_invertidos_e_url_relativa() -> None:
    url = f"https://doi.org/{DOI}"
    html = '<meta content="/pdf/artigo.pdf" name="citation_pdf_url">'
    http = FakeHttp({url: (200, html)}, {}, set())
    http.last_url[url] = "https://revista.example.org/artigo/42"
    assert [loc.url for loc in tcm.locais_pagina_doi(http, DOI)] == [
        "https://revista.example.org/pdf/artigo.pdf"
    ]


def test_europe_pmc_xml() -> None:
    xml_url = f"{tcm.EUROPEPMC}/PMC123/fullTextXML"
    corpo = (
        "<article><front><p>resumo</p></front><body><sec><p>Telemedicine increased "
        "adherence by <italic>18</italic> percent.</p></sec></body><back><p>refs</p></back>"
        "</article>"
    )
    http = FakeHttp(
        {xml_url: (200, corpo)},
        {
            f"{tcm.EUROPEPMC}/search": {
                "resultList": {
                    "result": [{"pmcid": "PMC123", "isOpenAccess": "Y", "license": "cc by"}]
                }
            }
        },
        set(),
    )
    locais = tcm.localizar(http, doi=DOI)
    assert locais[0].tipo == "xml" and locais[0].origem == "Europe PMC"
    tc = tcm.obter(http, locais)
    assert tc is not None and not tc.paginado
    assert tc.paginas == ["Telemedicine increased adherence by 18 percent."]


def test_xml_com_entidade_e_recusado() -> None:
    assert tcm.texto_xml('<!DOCTYPE a [<!ENTITY x "y">]><a><body><p>&x;</p></body></a>') is None


@pytest.mark.parametrize(
    ("robots", "ok"),
    [
        ((404, ""), True),
        ((200, "User-agent: *\nDisallow: /privado/\n"), True),
        ((200, "User-agent: *\nDisallow: /\n"), False),
        ((200, "User-agent: errei\nDisallow: /\n"), False),
        ((503, ""), False),
    ],
)
def test_robots(robots: tuple[int, str], ok: bool) -> None:
    http = FakeHttp({"https://repo.example.org/robots.txt": robots}, {}, set())
    assert tcm.permitido(http, "https://repo.example.org/a.pdf") is ok


def test_crawl_delay_e_respeitado() -> None:
    http = FakeHttp(
        {"https://arxiv.org/robots.txt": (200, "User-agent: *\nCrawl-delay: 15\nAllow: /pdf\n")},
        {},
        set(),
    )
    assert tcm.permitido(http, "https://arxiv.org/pdf/2101.00001")
    assert http.delays == {"arxiv.org": 15.0}


def test_obter_pula_bloqueado_e_usa_o_proximo_com_paginas() -> None:
    http = FakeHttp(
        {"https://bloq.example.org/robots.txt": (200, "User-agent: *\nDisallow: /\n")},
        {},
        {"https://livre.example.org/a.pdf"},
    )
    locais = [
        tcm.Local("https://bloq.example.org/a.pdf", "OpenAlex"),
        tcm.Local("https://livre.example.org/a.pdf", "Unpaywall", "cc-by"),
    ]
    tc = tcm.obter(http, locais)
    assert tc is not None and tc.origem == "Unpaywall" and tc.paginado
    assert "https://bloq.example.org/a.pdf" not in http.calls  # nem tentou baixar
    assert "robots.txt" in tc.tentativas[0]
    tr = tcm.trechos(tc, "telemedicine treatment adherence rural")
    assert tr[0] == ("Telemedicine increased treatment adherence in rural areas by 18 percent.", 2)


def test_client_crawl_delay_limitado_e_isolado() -> None:
    from errei.net.client import HOST_INTERVAL, HttpClient

    a = HttpClient(cache_dir=None)
    a.respeitar_crawl_delay("lento.example.org", 120)
    assert a.limiter.intervals["lento.example.org"] == 30.0
    assert "lento.example.org" not in HOST_INTERVAL  # não vaza para outros clientes
    a.close()


def test_texto_de_memoriza_por_execucao() -> None:
    from errei.checkers.base import RunContext
    from errei.config import Config
    from errei.net.sources import Candidate

    http = FakeHttp({}, {}, {"https://livre.example.org/a.pdf"})
    ctx = RunContext(config=Config(), http=http)
    c = Candidate(
        "OpenAlex",
        "T",
        [],
        2020,
        "",
        DOI,
        "",
        extra={"oa_locais": [("https://livre.example.org/a.pdf", "cc-by")]},
    )
    t1 = tcm.texto_de(ctx, c)
    n = len(http.calls)
    t2 = tcm.texto_de(ctx, c)
    assert t1 is t2 and t1 is not None and len(http.calls) == n
