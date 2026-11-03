"""Referência empírica por área: medidas, construção (HTTP simulado) e comparação offline."""

from __future__ import annotations

import io
import json
import shutil
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from conftest import ARTIGO
from errei.net.client import HttpClient
from errei.referencia import areas, medidas, pdftexto, store
from errei.referencia.construir import construir, filtro
from helpers import audit, by_code, cli

CORPO_PT = (
    "Este trabalho tem como objetivo analisar a evasão escolar no ensino médio. "
    "Os dados foram coletados em quarenta escolas públicas, e a análise foi conduzida por "
    "regressão logística (SILVA, 2020). Além disso, os resultados indicam que a defasagem "
    "idade-série aumenta a chance de evasão. Portanto, políticas de correção de fluxo são "
    "prioritárias. Os dados estão disponíveis no Zenodo. Os autores declaram não haver "
    "conflito de interesses. Este estudo contou com financiamento da CAPES. "
) * 12


def test_area_resolve_slug_and_capes_name() -> None:
    assert areas.resolve("educacao") is areas.AREAS["educacao"]
    assert areas.resolve("EDUCAÇÃO") is areas.AREAS["educacao"]
    assert areas.resolve("Saúde Coletiva") is areas.AREAS["saude-coletiva"]
    assert areas.resolve("astrologia") is None
    f = filtro(areas.AREAS["educacao"], "brasil", "2015-2023")
    assert "country_code:BR" in f and "is_in_top_10_percent:true" in f
    assert "country_code" not in filtro(areas.AREAS["educacao"], "mundo", "2015-2023")


def test_medir_texto_pt_and_en() -> None:
    m = medidas.medir_texto(CORPO_PT, "pt")
    assert m["palavras"] > 300 and 10 < m["frase_media"] < 40
    assert {"flesch", "conectivos_100", "passiva_pct"} <= m.keys()
    assert m["decl_dados"] and m["decl_conflito"] and m["decl_financiamento"]
    assert not m["decl_etica"]
    assert m["cites_1000"] > 0  # (SILVA, 2020)
    en = medidas.medir_texto("The data are available on request. " * 100, "en")
    assert "flesch" not in en and "passiva_pct" not in en  # medidas só do português
    assert en["decl_dados"]
    assert medidas.medir_texto("curto demais", "pt") == {}


def test_medir_refs_relative_to_publication_year() -> None:
    refs = [
        {"ano": 2018, "periodico": True, "doi": True},
        {"ano": 2010, "periodico": True, "doi": False},
        {"ano": 2019, "periodico": False, "doi": False},
        {"ano": None, "periodico": False, "doi": False},
    ]
    m = medidas.medir_refs(refs, 2020)
    assert m["refs_n"] == 4
    assert m["refs_recentes_pct"] == 50.0  # 2018 e 2019 (5 anos antes de 2020)
    assert m["refs_periodicos_pct"] == 50.0 and m["refs_doi_pct"] == 50.0
    assert m["refs_idade_mediana"] == 2.0  # 2020 − mediana(2010, 2018, 2019)


def test_agregar_only_aggregates() -> None:
    amostras = [{"palavras": float(i), "decl_dados": i % 2 == 0} for i in range(1, 11)]
    ag = medidas.agregar(amostras)
    assert ag["palavras"]["n"] == 10 and ag["palavras"]["p50"] == 5.5
    assert ag["palavras"]["p10"] == pytest.approx(1.9)
    assert ag["decl_dados"] == {"n": 10, "freq": 0.5}


def test_pdf_split_and_reference_count() -> None:
    cab = "Revista Brasileira de Educação, v. 1"
    pags = [
        f"{cab}\nTexto {'abcde'[i - 1]} da pági-\nna {'abcde'[i - 1]}.\n{i}" for i in range(1, 6)
    ]
    pags[-1] += (
        "\nREFERÊNCIAS\nSILVA, J. Título. Revista, 2020.\nSOUZA, M. Outro. Livro, 2019.\n"
        "COSTA, A. B. Mais um. 2018.\ncontinuação de linha\n"
    )
    corpo, linhas = pdftexto.separar(pags)
    assert cab not in corpo  # cabeçalho repetido removido
    assert "página" in corpo and "SILVA" not in corpo
    assert pdftexto.contar_referencias(linhas) == 3
    apa = ["Smith, J. (2020). Title.", "Doe, A. B. (2019). Other.", "Roe, C. (2018). X."]
    assert pdftexto.contar_referencias(apa) == 3
    assert pdftexto.contar_referencias(["texto"]) is None


def _pdf(texto: str) -> bytes:
    reportlab = pytest.importorskip("reportlab")
    del reportlab
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    palavras = texto.split()
    for p in range(0, len(palavras), 400):
        y = 800
        linha: list[str] = []
        for w in palavras[p : p + 400]:
            linha.append(w)
            if len(linha) == 12:
                c.drawString(40, y, " ".join(linha))
                y -= 14
                linha = []
        if linha:
            c.drawString(40, y, " ".join(linha))
        c.showPage()
    c.save()
    return buf.getvalue()


def _obra(i: int) -> dict[str, Any]:
    return {
        "id": f"https://openalex.org/W{i}",
        "doi": f"https://doi.org/10.1/{i}",
        "publication_year": 2020,
        "language": "pt",
        "type": "article",
        "referenced_works": ["https://openalex.org/W900", "https://openalex.org/W901"],
        "referenced_works_count": 2,
        "abstract_inverted_index": {
            w: [k]
            for k, w in enumerate(["Este", "estudo", "analisa", "a", "evasão", "escolar", "."])
        },
        "best_oa_location": {"pdf_url": f"https://www.scielo.br/pdf/{i}.pdf", "license": "cc-by"},
        "locations": [],
    }


def test_construir_with_simulated_openalex(tmp_path: Path, respx_mock: respx.MockRouter) -> None:
    obras = [_obra(i) for i in range(1, 4)]
    refs = [
        {"id": "https://openalex.org/W900", "doi": "x", "publication_year": 2018,
         "type": "article", "primary_location": {"source": {"type": "journal"}}},
        {"id": "https://openalex.org/W901", "doi": None, "publication_year": 2005,
         "type": "book", "primary_location": None},
    ]  # fmt: skip

    def openalex(request: httpx.Request) -> httpx.Response:
        q = dict(request.url.params)
        assert "Authorization" not in request.headers  # sem chave configurada
        if q.get("select") == "id":
            return httpx.Response(200, json={"meta": {"count": 1234}, "results": []})
        if q["filter"].startswith("ids.openalex:"):
            return httpx.Response(200, json={"results": refs})
        page = int(q.get("page", 1))
        return httpx.Response(200, json={"results": obras if page == 1 else []})

    respx_mock.get(url__startswith="https://api.openalex.org/works").mock(side_effect=openalex)
    pdf = _pdf(CORPO_PT)
    respx_mock.get(url__startswith="https://www.scielo.br/pdf/").mock(
        return_value=httpx.Response(200, content=pdf)
    )
    http = HttpClient(cache_dir=tmp_path / "c", intervals={}, default_interval=0, backoff=0)
    res = construir(http, areas.AREAS["educacao"], "brasil", n=3, usar_modelo=False)
    p = res["procedencia"]
    assert p["obras_na_populacao"] == 1234 and p["amostra"]["n"] == 3
    assert p["com_texto_completo"] == 3 and p["licencas_dos_textos"] == {"cc-by": 3}
    g = res["grupos"]["artigo|pt"]
    assert g["n"] == 3
    assert g["medidas"]["refs_n"]["p50"] == 2
    assert g["medidas"]["refs_recentes_pct"]["p50"] == 50.0
    assert g["medidas"]["decl_dados"]["freq"] == 1.0
    assert g["medidas"]["palavras"]["p50"] > 300
    # nada do texto das obras é guardado: nem no resultado, nem no cache de PDFs
    dump = json.dumps(res, ensure_ascii=False)
    assert "evasão" not in dump and "Zenodo" not in dump
    assert not (tmp_path / "c" / "pdf").exists()


def _instalar(n: int = 200) -> None:
    def q(p10: float, p25: float, p50: float, p75: float, p90: float) -> dict[str, float]:
        return {"n": n, "p10": p10, "p25": p25, "p50": p50, "p75": p75, "p90": p90}

    store.salvar(
        "educacao",
        "brasil",
        {
            "procedencia": {
                "criterio": "teste",
                "obras_na_populacao": 999,
                "amostra": {"n": n, "anos": "2015-2023"},
                "com_texto_completo": n,
                "consultado_em": "2026-11-02",
                "fonte": "simulada",
            },
            "grupos": {
                "artigo|pt": {
                    "n": n,
                    "medidas": {
                        "refs_n": q(20, 28, 38, 50, 65),
                        "frase_media": q(15, 18, 21, 25, 29),
                        "decl_conflito": {"n": n, "freq": 0.8},
                    },
                }
            },
        },
        "Educação",
    )


@pytest.fixture
def artigo(tmp_path: Path) -> Path:
    dst = tmp_path / "artigo"
    shutil.copytree(ARTIGO, dst)
    return dst


def test_compare_with_installed_reference(artigo: Path) -> None:
    _instalar()
    rep = audit(artigo, referencia={"escopo": "brasil"}, periodico={"area": "EDUCAÇÃO"})
    g = next(g for g in rep.metrics if g.checker == "referencia")
    assert "Educação (brasil; pt; n=200)" in g.title
    linhas = {m.name: m for m in g.metrics}
    assert linhas["Referências (nº)"].value == "5"
    assert "abaixo do p10" in linhas["Referências (nº)"].explanation
    assert "faixa central" in linhas["Comprimento médio de frase (palavras)"].explanation
    assert linhas["Conflito de interesses"].reference.startswith("presente em 80%")
    fs = by_code(rep.findings, "REF-DIM-001")
    assert any("Referências (nº): 5, abaixo do p10" in f.message for f in fs)
    assert any("Conflito de interesses: ausente" in f.message for f in fs)
    assert rep.meta["referencia"]["manuscrito"]["refs_n"] == 5
    assert any("referência por área" in lim for lim in rep.limitations)


def test_small_sample_warns(artigo: Path) -> None:
    _instalar(n=12)
    rep = audit(artigo, referencia={"escopo": "brasil"}, periodico={"area": "educacao"})
    assert by_code(rep.findings, "REF-AREA-002")
    assert not by_code(rep.findings, "REF-DIM-001")  # n pequeno: não aponta


def test_missing_reference_and_unknown_area(artigo: Path) -> None:
    rep = audit(artigo, referencia={"escopo": "mundo"}, periodico={"area": "educacao"})
    (f,) = by_code(rep.findings, "REF-AREA-001")
    assert "errei referencia construir --area educacao --escopo mundo" in (f.suggestion or "")
    rep = audit(artigo, referencia={"escopo": "brasil"}, periodico={"area": "astrologia"})
    assert by_code(rep.findings, "REF-AREA-003")


def test_default_behavior_unchanged(artigo: Path) -> None:
    _instalar()
    rep = audit(artigo, periodico={"area": "educacao"})  # sem --referencia
    assert not [f for f in rep.findings if f.code.startswith("REF-")]
    assert not [g for g in rep.metrics if g.checker == "referencia"]


def test_cli_listar_and_flag(artigo: Path) -> None:
    _instalar()
    res = cli("referencia", "listar")
    assert res.exit_code == 0 and "educacao" in res.output and "n=200 de 999" in res.output
    res = cli(str(artigo), "--area", "educacao", "--referencia", "brasil", "--no-user-config")
    assert res.exit_code in (0, 1), res.output
    assert "Comparação com a referência" in res.output
    assert cli(str(artigo), "--referencia", "marte").exit_code == 2


def test_openalex_key_goes_in_header_not_cache(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.get(url__startswith="https://api.openalex.org/works").mock(
        return_value=httpx.Response(200, json={"results": []})
    )
    http = HttpClient(
        cache_dir=tmp_path, intervals={}, default_interval=0, backoff=0, openalex_key="SEGREDO"
    )
    http.get_json("https://api.openalex.org/works", {"filter": "x"})
    req = route.calls[0].request
    assert req.headers["Authorization"] == "Bearer SEGREDO"
    assert "SEGREDO" not in str(req.url)
    assert b"SEGREDO" not in (tmp_path / "http.sqlite").read_bytes()
