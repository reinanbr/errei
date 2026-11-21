"""Verificador ``apud`` (citação de citação) e verificação opcional com o Claude Code."""

from __future__ import annotations

import json
import stat
import sys
from pathlib import Path
from typing import Any, ClassVar

import httpx
import pytest
import respx

from errei.checkers.apud import coletar, frase
from errei.config import Config
from errei.net.client import HttpClient
from errei.net.textocompleto import TextoCompleto
from errei.pipeline import run
from errei.project import load_project
from errei.report.build import Report
from helpers import by_code, cli, make_project

MAIN = (
    "\\documentclass[brazil]{abntex2}\n\\usepackage{abntex2cite}\n\\begin{document}\n"
    "\\input{texto}\n\\bibliography{r}\n\\end{document}\n"
)
BIB = (
    "@article{flesch1948, author={Flesch, Rudolf}, title={A new readability yardstick}, "
    "journal={Journal of Applied Psychology}, year={1948}, volume={32}, pages={221--233}, "
    "doi={10.1037/h0057532}}\n"
    "@techreport{martins1996, author={Martins, Teresa B. F. and Ghiraldelo, Claudete M.}, "
    "title={Readability formulas applied to textbooks in Brazilian Portuguese}, "
    "institution={ICMC-USP}, address={São Carlos}, year={1996}}\n"
    "@article{souza2020, author={Souza, Ana}, title={Leitura e legibilidade no ensino}, "
    "journal={Revista Z}, year={2020}, volume={1}, pages={1--9}}\n"
    "@article{lima2010, author={Lima, Rita}, title={Textos didáticos}, journal={Revista Y}, "
    "year={2010}, volume={2}, pages={3--9}}\n"
)
APUD_OK = (
    "A legibilidade de um texto pode ser estimada por fórmulas simples de contagem "
    "\\apud[p.~12]{flesch1948}{martins1996}.\n"
)


def projeto(tmp: Path, texto: str, bib: str = BIB, main: str = MAIN) -> Path:
    return make_project(tmp / "artigo", {"main.tex": main, "texto.tex": texto, "r.bib": bib})


def offline(root: Path) -> Report:
    cfg = Config.load(root, {"checkers": {"only": ["apud"]}}, use_user_config=False)
    return run(root, cfg)


def online(root: Path, cache: Path | None = None, **over: Any) -> Report:
    cfg = Config.load(
        root, {"online": True, "checkers": {"only": ["apud"]}, **over}, use_user_config=False
    )
    http = HttpClient(cache_dir=cache, intervals={}, default_interval=0, backoff=0, retries=0)
    return run(root, cfg, http=http)


# ------------------------------------------------------------------ coleta
def test_coleta_formas_abntex2cite_e_digitada(tmp_path: Path) -> None:
    root = projeto(
        tmp_path,
        APUD_OK
        + "Segundo \\apudonline{flesch1948}{martins1996}, a fórmula funciona.\n\n"
        + "O índice de \\citeonline{flesch1948} apud \\citeonline{martins1996} é usado.\n\n"
        + "O índice de Flesch (1948) apud \\citeonline{martins1996} também.\n\n"
        + "Como mostra \\citeonline{flesch1948} citado por Martins (1996), funciona.\n",
    )
    p = load_project(root)
    got = [(a.forma, a.original, a.consultada, a.original_texto) for a in coletar(p)]
    assert got == [
        ("apud", "flesch1948", "martins1996", ""),
        ("apudonline", "flesch1948", "martins1996", ""),
        ("digitado", "flesch1948", "martins1996", ""),
        ("digitado", "", "martins1996", "Flesch (1948)"),
        ("digitado", "flesch1948", "", ""),
    ]
    assert coletar(p)[0].pagina == "p.~12"
    # a frase sai sem os marcadores de citação e sem o "apud"
    assert frase(p, coletar(p)[2]) == "O índice de o estudo é usado."


def test_coleta_biblatex_abnt_com_opcional_entre_as_chaves(tmp_path: Path) -> None:
    main = MAIN.replace("\\usepackage{abntex2cite}", "\\usepackage[style=abnt]{biblatex}")
    root = projeto(
        tmp_path,
        "Ela é estimada \\apud[p.~12]{flesch1948}[p.~200]{martins1996}.\n\n"
        "Segundo \\textapud{flesch1948}{martins1996}, funciona.\n",
        main=main,
    )
    p = load_project(root)
    aps = coletar(p, "biblatex-abnt")
    assert [(a.original, a.consultada, a.pagina) for a in aps] == [
        ("flesch1948", "martins1996", "p.~200"),
        ("flesch1948", "martins1996", ""),
    ]
    # o \cite da obra consultada continua ligado ao .bib (sem "entrada nunca citada")
    assert {u.key for u in p.cite_uses()} >= {"flesch1948", "martins1996"}


# ------------------------------------------------------------------ offline
def test_ordem_invertida(tmp_path: Path) -> None:
    root = projeto(tmp_path, "Segundo \\apudonline{souza2020}{martins1996}, funciona.\n")
    f = by_code(offline(root).findings, "APUD-ORDEM-001")
    assert len(f) == 1
    assert "2020" in f[0].message and "1996" in f[0].message
    assert f[0].suggestion == "\\apudonline{martins1996}{souza2020}"
    assert f[0].location is not None and f[0].location.line == 1


def test_mesma_obra_nos_dois_lados(tmp_path: Path) -> None:
    root = projeto(tmp_path, "Funciona \\apud{martins1996}{martins1996}.\n")
    assert by_code(offline(root).findings, "APUD-MESMA-001")


def test_original_citada_diretamente_e_lista(tmp_path: Path) -> None:
    root = projeto(
        tmp_path,
        APUD_OK + "\nA fórmula foi revista depois \\cite{flesch1948}.\n\n"
        "Textos didáticos são difíceis \\apud{lima2010}{souza2020}.\n",
    )
    rep = offline(root)
    direta = by_code(rep.findings, "APUD-DIRETA-001")
    assert len(direta) == 1 and "flesch1948" in direta[0].message
    assert any("texto.tex:3" in e for e in direta[0].evidence)
    lista = by_code(rep.findings, "APUD-LISTA-001")
    # flesch1948 é citada diretamente: entra na lista de qualquer forma
    assert len(lista) == 1 and "'lima2010'" in lista[0].message
    assert "flesch1948" not in lista[0].message
    assert lista[0].manual_review


def test_consultada_digitada(tmp_path: Path) -> None:
    root = projeto(tmp_path, "Como mostra \\citeonline{flesch1948} apud Martins (1996), sim.\n")
    f = by_code(offline(root).findings, "APUD-CONS-001")
    assert len(f) == 1 and "Martins (1996)" in f[0].message


def test_excesso_de_apud(tmp_path: Path) -> None:
    root = projeto(
        tmp_path,
        "Um \\apud{flesch1948}{martins1996}.\n\nDois \\apud{lima2010}{souza2020}.\n\n"
        "Três \\apud{flesch1948}{souza2020}.\n",
    )
    rep = offline(root)
    f = by_code(rep.findings, "APUD-EXCESSO-001")
    assert len(f) == 1 and "2 obra(s)" in f[0].message
    grupo = next(g for g in rep.metrics if g.checker == "apud")
    assert grupo.metrics[0].value == 3


def test_offline_nao_usa_rede_e_avisa(tmp_path: Path) -> None:
    root = projeto(tmp_path, APUD_OK)
    rep = offline(root)
    net = [f for f in rep.findings if f.code == "CORE-NET-001" and f.checker == "apud"]
    assert net and "requer --online" in net[0].message
    assert not by_code(rep.findings, "APUD-ACESSO-001")
    assert "ia_claude" not in rep.meta


def test_sem_apud_sem_achados(tmp_path: Path) -> None:
    root = projeto(tmp_path, "Texto sem citação de citação \\cite{flesch1948}.\n")
    rep = offline(root)
    assert not [f for f in rep.findings if f.checker == "apud"]


# ------------------------------------------------------------------ online (respx)
W_FLESCH = {
    "id": "https://openalex.org/W1",
    "doi": "https://doi.org/10.1037/h0057532",
    "title": "A new readability yardstick",
    "publication_year": 1948,
    "cited_by_count": 6677,
    "authorships": [{"author": {"display_name": "Rudolf Flesch"}}],
    "primary_location": {"source": {"display_name": "Journal of Applied Psychology"}},
    "best_oa_location": {"pdf_url": "https://example.org/flesch.pdf", "license": "cc-by"},
    "referenced_works": [],
}
OUTRAS = {
    f"W9{i}": {
        "id": f"https://openalex.org/W9{i}",
        "doi": f"https://doi.org/10.9999/outra.{i}",
        "title": f"Outra obra sobre textos escolares número {i}",
        "publication_year": 1990,
        "authorships": [{"author": {"display_name": "Fulano Silva"}}],
    }
    for i in range(8)
}
OBRAS = {"W1": W_FLESCH, **OUTRAS}
W_MARTINS = {
    "id": "https://openalex.org/W2",
    "doi": None,
    "title": "Readability formulas applied to textbooks in Brazilian Portuguese",
    "publication_year": 1996,
    "authorships": [
        {"author": {"display_name": "Teresa Martins"}},
        {"author": {"display_name": "Claudete Ghiraldelo"}},
    ],
    "referenced_works": ["https://openalex.org/W1"]
    + [f"https://openalex.org/W9{i}" for i in range(6)],
}
SEM_FLESCH = dict(W_MARTINS, referenced_works=[f"https://openalex.org/W9{i}" for i in range(7)])


def rotas(
    respx_mock: respx.MockRouter,
    martins: dict[str, Any] | None = W_MARTINS,
    *,
    crossref: dict[str, list[dict[str, Any]]] | None = None,
    s2_busca: list[dict[str, Any]] | None = None,
    s2_refs: list[dict[str, Any]] | None = None,
    autor_ano: list[dict[str, Any]] | None = None,
) -> list[str]:
    """Simula OpenAlex, Crossref e Semantic Scholar; devolve as URLs pedidas."""
    pedidas: list[str] = []

    def openalex(request: httpx.Request) -> httpx.Response:
        pedidas.append(str(request.url))
        path = request.url.path
        flt = request.url.params.get("filter", "")
        if path.startswith("/works/doi:"):
            if path.lower().endswith("10.1037/h0057532"):
                return httpx.Response(200, json=W_FLESCH)
            return httpx.Response(404, json={})
        if flt.startswith("openalex_id:"):
            ids = flt.split(":", 1)[1].split("|")
            return httpx.Response(200, json={"results": [OBRAS[i] for i in ids if i in OBRAS]})
        if flt.startswith("raw_author_name.search:"):
            return httpx.Response(200, json={"results": autor_ano or []})
        q = request.url.params.get("search", "").lower()
        if "readability formulas" in q and martins is not None:
            return httpx.Response(200, json={"results": [martins]})
        return httpx.Response(200, json={"results": []})

    def cr(request: httpx.Request) -> httpx.Response:
        pedidas.append(str(request.url))
        doi = request.url.path.split("/works/", 1)[1].lower()
        if crossref and doi in crossref:
            return httpx.Response(200, json={"message": {"DOI": doi, "reference": crossref[doi]}})
        return httpx.Response(404, text="Resource not found.")

    def s2(request: httpx.Request) -> httpx.Response:
        pedidas.append(str(request.url))
        if request.url.path.endswith("/paper/search"):
            return httpx.Response(200, json={"data": s2_busca or []})
        if request.url.path.endswith("/references"):
            return httpx.Response(200, json={"data": s2_refs or []})
        return httpx.Response(404, json={})

    respx_mock.get(url__startswith="https://api.openalex.org/").mock(side_effect=openalex)
    respx_mock.get(url__startswith="https://api.crossref.org/").mock(side_effect=cr)
    respx_mock.get(url__startswith="https://api.semanticscholar.org/").mock(side_effect=s2)
    respx_mock.route().mock(return_value=httpx.Response(404, text=""))
    return pedidas


def test_online_acesso_aberto_e_rede_confirmada(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    pedidas = rotas(respx_mock)
    rep = online(projeto(tmp_path, APUD_OK))
    acesso = by_code(rep.findings, "APUD-ACESSO-001")
    assert len(acesso) == 1 and "https://example.org/flesch.pdf" in acesso[0].links
    assert acesso[0].suggestion == "depois de ler a original, troque o apud por \\cite{flesch1948}"
    rede = by_code(rep.findings, "APUD-REDE-001")
    assert len(rede) == 1 and "'martins1996' cita 'flesch1948'" in rede[0].message
    assert "OpenAlex, por registro do OpenAlex" in rede[0].message
    assert not [f for f in rep.findings if f.code == "CORE-NET-001" and f.checker == "apud"]
    # achou no OpenAlex: não consulta Crossref nem Semantic Scholar
    assert not [u for u in pedidas if "crossref" in u or "semanticscholar" in u]


def test_online_consultada_nao_cita_a_original(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    rotas(respx_mock, SEM_FLESCH)
    f = by_code(online(projeto(tmp_path, APUD_OK)).findings, "APUD-REDE-002")
    assert len(f) == 1 and "(OpenAlex: 7 obras)" in f[0].message and f[0].confidence == 0.5
    assert any("A new readability yardstick" in e for e in f[0].evidence)


BIB_DOI = BIB.replace("institution={ICMC-USP}", "institution={ICMC-USP}, doi={10.5555/martins}")
REF_FLESCH_CR = {
    "key": "ref_27",
    "DOI": "10.1037/H0057532",
    "article-title": "A new readability yardstick",
    "author": "Flesch, R.F.",
    "year": "1948",
    "unstructured": "Flesch RF. A new readability yardstick. J Appl Psychol 1948; 32:221–33.",
}
OUTRAS_CR = [
    {
        "key": f"r{i}",
        "unstructured": f"Silva F. Outra obra {i}. Rev X 1990;{i}:1-9.",
        "year": "1990",
    }
    for i in range(6)
]


def test_online_crossref_quando_o_openalex_nao_lista(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    rotas(respx_mock, SEM_FLESCH, crossref={"10.5555/martins": [*OUTRAS_CR, REF_FLESCH_CR]})
    rep = online(projeto(tmp_path, APUD_OK, bib=BIB_DOI))
    rede = by_code(rep.findings, "APUD-REDE-001")
    assert len(rede) == 1 and "Crossref, por DOI" in rede[0].message
    assert any("J Appl Psychol 1948" in e for e in rede[0].evidence)
    assert not by_code(rep.findings, "APUD-REDE-002")


def test_online_duas_bases_sem_a_original(tmp_path: Path, respx_mock: respx.MockRouter) -> None:
    rotas(respx_mock, SEM_FLESCH, crossref={"10.5555/martins": OUTRAS_CR})
    f = by_code(online(projeto(tmp_path, APUD_OK, bib=BIB_DOI)).findings, "APUD-REDE-002")
    assert len(f) == 1
    assert "OpenAlex: 7 obras; Crossref: 6 obras" in f[0].message
    assert f[0].confidence == 0.6  # duas listas conferidas: mais confiança


def test_online_semantic_scholar_pela_busca_de_titulo(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    s2 = {
        "paperId": "abc123",
        "title": "Readability formulas applied to textbooks in Brazilian Portuguese",
        "year": 1996,
        "authors": [{"name": "Teresa Martins"}],
        "externalIds": {},
    }
    refs = [
        {
            "citedPaper": {
                "title": "A New Readability Yardstick",
                "year": 1948,
                "authors": [{"name": "R. Flesch"}],
                "externalIds": {},
            }
        },
    ] + [
        {
            "citedPaper": {
                "title": f"Outra obra {i}",
                "year": 1990,
                "authors": [{"name": "F. Silva"}],
            }
        }
        for i in range(6)
    ]
    rotas(respx_mock, None, s2_busca=[s2], s2_refs=refs)
    rede = by_code(online(projeto(tmp_path, APUD_OK)).findings, "APUD-REDE-001")
    assert len(rede) == 1 and "Semantic Scholar, por título" in rede[0].message


def test_online_original_digitada_identificada_na_lista(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    rotas(respx_mock)
    texto = (
        "A legibilidade é estimada pelo índice de Flesch (1948) apud \\citeonline{martins1996}.\n"
    )
    rep = online(projeto(tmp_path, texto))
    rede = by_code(rep.findings, "APUD-REDE-001")
    assert len(rede) == 1
    assert (
        "cita Flesch (1948) (lista de referências no OpenAlex, por autor e ano)" in rede[0].message
    )
    assert any("identificada na lista de referências" in e for e in rede[0].evidence)
    # identificada, a original passa pela conferência de acesso aberto
    acesso = by_code(rep.findings, "APUD-ACESSO-001")
    assert len(acesso) == 1 and "cadastre-a no .bib" in (acesso[0].suggestion or "")


@pytest.mark.parametrize(("citacoes", "identifica"), [((6677, 40), True), ((90, 40), False)])
def test_online_original_digitada_fora_das_listas(
    tmp_path: Path,
    respx_mock: respx.MockRouter,
    citacoes: tuple[int, int],
    identifica: bool,
) -> None:
    outra = dict(
        W_FLESCH,
        id="https://openalex.org/W7",
        title="Outra obra de Flesch",
        cited_by_count=citacoes[1],
        best_oa_location={},
    )
    rotas(respx_mock, SEM_FLESCH, autor_ano=[dict(W_FLESCH, cited_by_count=citacoes[0]), outra])
    texto = (
        "A legibilidade é estimada pelo índice de Flesch (1948) apud \\citeonline{martins1996}.\n"
    )
    rep = online(projeto(tmp_path, texto))
    assert by_code(rep.findings, "APUD-REDE-002")
    acesso = by_code(rep.findings, "APUD-ACESSO-001")
    if identifica:
        assert len(acesso) == 1 and any("só por autor e ano" in e for e in acesso[0].evidence)
    else:  # homônimos/ambiguidade: não identifica
        assert not acesso


def test_online_consultada_nao_localizada(tmp_path: Path, respx_mock: respx.MockRouter) -> None:
    rotas(respx_mock, None)
    f = by_code(online(projeto(tmp_path, APUD_OK)).findings, "APUD-VERIF-001")
    assert len(f) == 1 and "não foi localizada" in f[0].message


def test_casa_referencia() -> None:
    from errei.checkers.apud import Alvo, casa
    from errei.net.sources import Referencia

    alvo = Alvo(
        "flesch1948", True, "Flesch", 1948, "A new readability yardstick", "10.1037/h0057532"
    )
    assert casa(Referencia(doi="10.1037/h0057532"), alvo) == "DOI"
    assert casa(Referencia(titulo="A new readability yardstick."), alvo) == "título"
    impressa = "FLESCH, R. A new readability yardstick. J Appl Psychol, 1948."
    assert casa(Referencia(texto=impressa), alvo) == "título (referência impressa)"
    assert casa(Referencia(autor="Flesch", ano=1948), alvo) == "autor e ano"
    # mesmo autor e ano, outro título: não é a original
    assert casa(Referencia(autor="Flesch", ano=1948, titulo="Marks of readable style"), alvo) == ""
    assert casa(Referencia(autor="Flesch", ano=1949), alvo) == ""
    digitada = Alvo("Flesch (1948)", False, "Flesch", 1948)
    assert casa(Referencia(texto="Flesch R. The art of plain talk. 1948."), digitada) == (
        "autor e ano (referência impressa)"
    )


# ------------------------------------------------------------------ texto completo
def _texto(paginas: list[str]) -> TextoCompleto:
    return TextoCompleto(paginas, True, "OpenAlex", "https://example.org/martins.pdf")


class FakeCita:
    limiares: ClassVar[dict[str, float]] = {"sustenta": 0.5, "contradiz": 0.5}

    def julgar_trechos(self, afirmacao: str, trechos: list[tuple[str, int | None]]) -> Any:
        from errei.citecheck import Julgamento

        for t, pg in trechos:
            if "simple counts" in t:
                return Julgamento("sustenta", 0.8, 0.05, t), pg
        return Julgamento("neutro", 0.1, 0.05, trechos[0][0]), trechos[0][1]


def _com_texto(monkeypatch: pytest.MonkeyPatch, paginas: list[str], modelo: bool) -> None:
    from errei import citecheck
    from errei.net import textocompleto

    monkeypatch.setattr(textocompleto, "texto_de", lambda ctx, cand: _texto(paginas))
    if modelo:
        monkeypatch.setattr(citecheck, "unavailable_reason", lambda: None)
        monkeypatch.setattr(citecheck, "carregar", lambda: FakeCita())


PAG1 = "Introduction of the report on Brazilian textbooks and their readability levels today."
PAG2 = (
    "As Flesch (1948) showed, readability can be estimated from simple counts of words "
    "and syllables in each sentence."
)


@pytest.mark.parametrize(
    ("paginas", "modelo", "code"),
    [
        ([PAG1, PAG2], True, "APUD-TEXTO-001"),
        (
            [PAG1, "Flesch is cited here only as a name in the bibliography of this report."],
            True,
            "APUD-TEXTO-002",
        ),
        ([PAG1, PAG2], False, "APUD-TEXTO-001"),
        (
            [PAG1, "Nothing about the original author on this page of the report at all."],
            True,
            "APUD-TEXTO-003",
        ),
    ],
)
def test_texto_completo_da_consultada(
    tmp_path: Path,
    respx_mock: respx.MockRouter,
    monkeypatch: pytest.MonkeyPatch,
    paginas: list[str],
    modelo: bool,
    code: str,
) -> None:
    rotas(respx_mock)
    _com_texto(monkeypatch, paginas, modelo)
    rep = online(projeto(tmp_path, APUD_OK), refs={"texto_completo": True})
    f = by_code(rep.findings, code)
    assert len(f) == 1, [(x.code, x.message) for x in rep.findings]
    if code != "APUD-TEXTO-003":
        assert any("(p. 2)" in e for e in f[0].evidence)
    if code == "APUD-TEXTO-001" and not modelo:
        assert any("sem o modelo errei-cita" in e for e in f[0].evidence)
    assert any("página indicada no apud: p.~12" in e for e in f[0].evidence)


# ------------------------------------------------------------------ Claude Code
RESPOSTA = {
    "cita_original": "sim",
    "atribuicao": "confirma",
    "original_acessivel": "sim",
    "url_original": "https://example.org/flesch.pdf",
    "evidencias": [
        {"url": "https://example.org/martins", "trecho": "Flesch (1948) proposed " + "x " * 400},
        {"url": "javascript:alert(1)", "trecho": "link inválido é descartado"},
    ],
    "justificativa": " ".join(["palavra"] * 60),
}


def fake_claude(tmp: Path, resposta: dict[str, Any] | None = None, erro: bool = False) -> Path:
    """Executável que imita ``claude -p --output-format json`` e registra cada chamada."""
    d = tmp / "fake"
    d.mkdir(exist_ok=True)
    (d / "resposta.json").write_text(json.dumps(resposta or RESPOSTA), encoding="utf-8")
    exe = d / "claude"
    exe.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        f"d = Path({str(d)!r})\n"
        "n = len(list(d.glob('chamada-*.json')))\n"
        "reg = {'argv': sys.argv[1:], 'cwd': os.getcwd(), 'stdin': sys.stdin.read(),\n"
        "       'env': sorted(k for k in os.environ if k.startswith('CLAUDE'))}\n"
        "(d / f'chamada-{n}.json').write_text(json.dumps(reg))\n"
        "r = json.loads((d / 'resposta.json').read_text())\n"
        f"erro = {erro!r}\n"
        "out = {'type': 'result', 'subtype': 'success', 'is_error': erro,\n"
        "       'result': 'falhou de propósito' if erro else json.dumps(r),\n"
        "       'structured_output': None if erro else r, 'total_cost_usd': 0.012}\n"
        "print(json.dumps(out))\n",
        encoding="utf-8",
    )
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    return exe


def chamadas(exe: Path) -> list[dict[str, Any]]:
    return [
        json.loads(p.read_text())
        for p in sorted(exe.parent.glob("chamada-*.json"), key=lambda p: p.stat().st_mtime)
    ]


def test_claude_code_isolado_e_rotulado(
    tmp_path: Path, respx_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    rotas(respx_mock)
    monkeypatch.setenv("CLAUDECODE", "1")  # errei rodando dentro de uma sessão do Claude Code
    exe = fake_claude(tmp_path)
    root = projeto(tmp_path, APUD_OK)
    rep = online(root, ia_claude={"enabled": True, "comando": str(exe)})
    ia = by_code(rep.findings, "APUD-IA-001")
    assert len(ia) == 1
    f = ia[0]
    assert "cita a original: sim" in f.message and "acessível: sim" in f.message
    assert "javascript:" not in " ".join(f.links)
    assert f.links[0] == "https://example.org/martins"
    trecho = next(e for e in f.evidence if e.startswith("trecho indicado pela IA (não conferido)"))
    assert len(trecho) < 300 + 80  # trecho cortado em 300 caracteres
    just = next(e for e in f.evidence if e.startswith("justificativa da IA"))
    assert just.endswith("…") and len(just.split()) <= 25 + 3
    assert any("o OpenAlex indica o mesmo link" in e for e in f.evidence)
    # isolamento: pasta vazia fora do artigo, só WebSearch/WebFetch, sem MCP/hooks/sessão
    (c,) = chamadas(exe)
    argv = c["argv"]
    assert argv[argv.index("--tools") + 1] == "WebSearch,WebFetch"
    assert argv[argv.index("--allowedTools") + 1] == "WebSearch,WebFetch"
    assert argv[argv.index("--permission-prompts") + 1] == "none"
    for flag in ("-p", "--safe-mode", "--strict-mcp-config", "--no-session-persistence"):
        assert flag in argv
    assert argv[argv.index("--model") + 1] == "haiku"
    assert not Path(c["cwd"]).resolve().is_relative_to(root.resolve())
    assert "errei-claude-" in c["cwd"]
    assert "CLAUDECODE" not in c["env"]
    assert "fórmulas simples de contagem" in c["stdin"]
    assert "A new readability yardstick" in c["stdin"]
    assert "acesso livre" in c["stdin"]  # o que as bases abertas acharam vai junto
    # transparência: meta, base e limitações
    meta = rep.meta["ia_claude"]
    assert meta["chamadas"] == 1 and meta["custo_usd"] == 0.012 and meta["enviado"]
    assert any("Claude Code" in m for m in rep.meta["base"]["modelos"])
    assert any("--ia-claude" in lim for lim in rep.limitations)


def test_claude_code_usa_o_cache(tmp_path: Path, respx_mock: respx.MockRouter) -> None:
    rotas(respx_mock)
    exe = fake_claude(tmp_path)
    root = projeto(tmp_path, APUD_OK)
    over = {"ia_claude": {"enabled": True, "comando": str(exe)}}
    online(root, tmp_path / "cache", **over)
    rep = online(root, tmp_path / "cache", **over)
    assert len(chamadas(exe)) == 1
    assert rep.meta["ia_claude"]["chamadas"] == 0 and rep.meta["ia_claude"]["do_cache"] == 1
    assert by_code(rep.findings, "APUD-IA-001")
    rep = online(root, tmp_path / "cache", sem_cache=True, **over)
    assert len(chamadas(exe)) == 2


def test_claude_code_falha_nao_derruba(tmp_path: Path, respx_mock: respx.MockRouter) -> None:
    rotas(respx_mock)
    exe = fake_claude(tmp_path, erro=True)
    rep = online(projeto(tmp_path, APUD_OK), ia_claude={"enabled": True, "comando": str(exe)})
    assert not by_code(rep.findings, "APUD-IA-001")
    assert by_code(rep.findings, "APUD-REDE-001")  # as bases abertas continuam valendo
    falha = [f for f in rep.findings if f.code == "CORE-NET-001" and "Claude Code" in f.message]
    assert falha and "falhou de propósito" in falha[0].message


def test_claude_code_limite_de_consultas(tmp_path: Path, respx_mock: respx.MockRouter) -> None:
    rotas(respx_mock)
    exe = fake_claude(tmp_path)
    texto = (
        APUD_OK + "\nOutra frase diferente sobre legibilidade \\apud{flesch1948}{martins1996}.\n"
    )
    rep = online(
        projeto(tmp_path, texto),
        ia_claude={"enabled": True, "comando": str(exe), "max_consultas": 1},
    )
    assert len(chamadas(exe)) == 1
    assert any("não enviadas" in f.message for f in by_code(rep.findings, "APUD-IA-001"))


def test_claude_code_ausente(tmp_path: Path, respx_mock: respx.MockRouter) -> None:
    rotas(respx_mock)
    rep = online(
        projeto(tmp_path, APUD_OK),
        ia_claude={"enabled": True, "comando": str(tmp_path / "nao-existe")},
    )
    dep = [f for f in rep.findings if f.code == "CORE-DEP-001" and "--ia-claude" in f.message]
    assert dep and "não foi encontrado" in dep[0].message
    assert by_code(rep.findings, "APUD-REDE-001")
    assert "ia_claude" not in rep.meta


def test_claude_code_nao_e_ligado_pelo_errei_toml(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    rotas(respx_mock)
    exe = fake_claude(tmp_path)
    root = projeto(tmp_path, APUD_OK)
    (root / ".errei.toml").write_text(
        f'[ia_claude]\nenabled = true\ncomando = "{exe}"\n', encoding="utf-8"
    )
    rep = online(root)
    assert not chamadas(exe)
    assert "ia_claude" not in rep.meta
    assert not by_code(rep.findings, "APUD-IA-001")


def test_cli_ia_claude_requer_online(tmp_path: Path) -> None:
    root = projeto(tmp_path, APUD_OK)
    res = cli(str(root), "--ia-claude", "--no-user-config")
    assert res.exit_code == 2
    assert "--ia-claude requer --online" in res.output


def test_excesso_conta_original_digitada_e_da_bib_uma_vez(tmp_path: Path) -> None:
    root = projeto(
        tmp_path,
        "Um \\apud{flesch1948}{martins1996}.\n\n"
        "Dois, segundo Flesch (1948) apud \\citeonline{souza2020}.\n\n"
        "Três \\apud{lima2010}{souza2020}.\n",
    )
    grupo = next(g for g in offline(root).metrics if g.checker == "apud")
    assert grupo.metrics[1].value == "2 de 4 (50%)"


def test_semantic_scholar_fora_do_ar_nao_vira_nao_localizada(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    rotas(respx_mock, None)
    respx_mock.get(url__startswith="https://api.semanticscholar.org/").mock(
        return_value=httpx.Response(429, json={"message": "Too Many Requests"})
    )
    f = by_code(online(projeto(tmp_path, APUD_OK)).findings, "APUD-VERIF-001")
    assert len(f) == 1 and "o Semantic Scholar não respondeu" in f[0].message
