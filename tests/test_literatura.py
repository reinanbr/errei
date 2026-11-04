"""Verificador ``literatura`` com respostas de API gravadas (sem rede)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, ClassVar

import httpx
import pytest
import respx

from errei.checkers import literatura
from errei.config import Config
from errei.net.client import HttpClient
from errei.pipeline import run
from errei.report.build import Report
from helpers import by_code, make_project

FIX = json.loads(
    (Path(__file__).parent / "fixtures" / "literatura" / "respostas.json").read_text("utf-8")
)

INTRO = (
    "\\section{Introdução}\n"
    "O uso de redes neurais reduz o tempo de diagnóstico em hospitais \\cite{silva}.\n\n"
    "Estudos mostram que a telemedicina aumenta a adesão ao tratamento em áreas rurais "
    "do país.\n\n"
    "A gamificação melhora o engajamento de estudantes em cursos de engenharia \\cite{lima}.\n"
)
BIB = (
    "@article{silva, author={Silva, João}, title={Redes neurais na saúde}, "
    "journal={Revista X}, year={2019}}\n"
    "@article{lima, author={Lima, Rita}, title={Jogos no ensino}, journal={Revista Y}, "
    "year={2018}}\n"
)


class FakeCita:
    """Classificador falso: 'sustenta' só quando o trecho diz o que a afirmação diz."""

    limiares: ClassVar[dict[str, float]] = {"sustenta": 0.5, "contradiz": 0.5}

    def probs(self, pares: list[tuple[str, str]]) -> list[dict[str, float]]:
        out = []
        for _, trecho in pares:
            if "reduces diagnostic time" in trecho:
                out.append({"sustenta": 0.78, "contradiz": 0.02, "neutro": 0.2})
            else:
                out.append({"sustenta": 0.1, "contradiz": 0.05, "neutro": 0.85})
        return out


class FakeTradutor:
    def traduzir(self, textos: list[str]) -> list[str]:
        tr = {
            "neurais": "The use of neural networks reduces diagnostic time in hospitals.",
            "gamificação": "Gamification improves the engagement of students in engineering "
            "courses.",
        }
        return [next((v for k, v in tr.items() if k in t), t) for t in textos]


def router(respx_mock: respx.MockRouter, calls: list[httpx.Request]) -> None:
    def openalex(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        path = request.url.path
        if path.startswith("/works/doi:"):
            doi = path.split("doi:", 1)[1]
            for works in FIX["openalex_busca"].values():
                for w in works:
                    if w["doi"].endswith(doi):
                        return httpx.Response(200, json=w)
            return httpx.Response(404, json={})
        q = request.url.params.get("search", "").lower()
        for termo, works in FIX["openalex_busca"].items():
            if termo in q or (termo == "neurais" and "neural" in q):
                return httpx.Response(200, json={"results": works})
        return httpx.Response(200, json={"results": []})

    def s2(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        q = request.url.params.get("query", "").lower()
        for termo, papers in FIX["s2_busca"].items():
            if termo in q:
                return httpx.Response(200, json={"data": papers})
        return httpx.Response(200, json={"data": []})

    def crossref(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        doi = request.url.path.split("/works/", 1)[1]
        item = FIX["crossref_doi"].get(doi)
        if item is None:
            return httpx.Response(404, text="Resource not found.")
        return httpx.Response(200, json={"message": item})

    respx_mock.get(url__startswith="https://api.openalex.org/").mock(side_effect=openalex)
    respx_mock.get(url__startswith="https://api.semanticscholar.org/").mock(side_effect=s2)
    respx_mock.get(url__startswith="https://api.crossref.org/").mock(side_effect=crossref)


def projeto(tmp: Path) -> Path:
    return make_project(
        tmp / "artigo",
        {
            "main.tex": "\\documentclass[brazil]{abntex2}\n\\begin{document}\n"
            "\\input{introducao}\n\\bibliography{r}\n\\end{document}\n",
            "introducao.tex": INTRO,
            "r.bib": BIB,
        },
    )


def rodar(root: Path, **over: Any) -> Report:
    cfg = Config.load(
        root,
        {"online": True, "checkers": {"only": ["literatura"]}, **over},
        use_user_config=False,
    )
    http = HttpClient(cache_dir=None, intervals={}, default_interval=0, backoff=0, retries=0)
    return run(root, cfg, http=http)


@pytest.fixture
def modelos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(literatura, "_classificador", lambda: FakeCita())
    monkeypatch.setattr(literatura, "_tradutor", lambda: FakeTradutor())


def test_fonte_em_ingles_sustenta(
    tmp_path: Path, respx_mock: respx.MockRouter, modelos: None
) -> None:
    calls: list[httpx.Request] = []
    router(respx_mock, calls)
    rep = rodar(projeto(tmp_path))
    sug = by_code(rep.findings, "LIT-SUG-001")
    assert len(sug) == 1
    f = sug[0]
    assert f.location is not None and f.location.file.as_posix() == "introducao.tex"
    assert f.location.line == 2
    ev = "\n".join(f.evidence)
    assert 'Afirmação : "O uso de redes neurais reduz o tempo de diagnóstico' in ev
    assert "Fonte     : Smith et al. (2022). Neural networks shorten diagnostic time" in ev
    assert "DOI: 10.1000/nn.2022" in ev
    assert "Base      : OpenAlex" in ev and "Idioma: en" in ev
    assert "The use of neural networks reduces diagnostic time in hospitals" in ev  # original
    assert "Relação   : sustenta     Confiança: média" in ev
    assert "Aviso     : indicador, não veredito. Leia a fonte antes de citar." in ev
    trecho = next(x for x in f.evidence if x.startswith("Trecho"))
    assert len(trecho.split('"')[1]) <= 300
    lang = by_code(rep.findings, "LIT-LANG-001")
    assert len(lang) == 1 and "'en'" in lang[0].message
    # consulta feita em português e em inglês
    buscas = [c.url.params.get("search", "") for c in calls if c.url.path == "/works"]
    assert any("neurais" in b for b in buscas) and any("neural" in b for b in buscas)


def test_mesmo_tema_sem_suporte_vira_rel(
    tmp_path: Path, respx_mock: respx.MockRouter, modelos: None
) -> None:
    router(respx_mock, [])
    rep = rodar(projeto(tmp_path))
    rel = by_code(rep.findings, "LIT-REL-001")
    assert len(rel) == 1
    assert rel[0].location is not None and rel[0].location.line == 4  # frase sem citação
    ev = "\n".join(rel[0].evidence)
    assert "Fonte relacionada (NÃO sustenta a afirmação): Souza (2020)" in ev
    assert "Motivo: nenhum trecho do resumo ou do texto aberto afirma" in ev
    assert not any(
        "Telemedicina" in " ".join(f.evidence) for f in by_code(rep.findings, "LIT-SUG-001")
    )


def test_fonte_inexistente_descartada_e_sem_resultado(
    tmp_path: Path, respx_mock: respx.MockRouter, modelos: None
) -> None:
    router(respx_mock, [])
    rep = rodar(projeto(tmp_path))
    todos = json.dumps([f.to_dict() for f in rep.findings], ensure_ascii=False)
    assert "naoexiste" not in todos and "Ghost" not in todos
    g = next(g for g in rep.metrics if g.checker == "literatura")
    desc = next(m for m in g.metrics if m.name.startswith("Fontes descartadas"))
    assert desc.value == 1
    none = by_code(rep.findings, "LIT-NONE-001")
    assert len(none) == 1 and none[0].location is not None and none[0].location.line == 6
    assert none[0].message == "nenhuma fonte encontrada para esta afirmação."


def test_sem_modelo_nunca_sugere(tmp_path: Path, respx_mock: respx.MockRouter) -> None:
    router(respx_mock, [])
    rep = rodar(projeto(tmp_path))  # ERREI_NO_MODEL=1 no conftest
    assert not by_code(rep.findings, "LIT-SUG-001")
    assert by_code(rep.findings, "LIT-REL-001")
    deps = by_code(rep.findings, "CORE-DEP-001")
    assert any("errei-cita indisponível" in f.message for f in deps)


def test_offline_nenhuma_requisicao(
    tmp_path: Path, respx_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch, modelos: None
) -> None:
    router(respx_mock, [])

    def proibido(*a: Any, **k: Any) -> Any:
        raise AssertionError("cliente HTTP criado sem --online")

    monkeypatch.setattr("errei.pipeline.make_http", proibido)
    monkeypatch.setattr(HttpClient, "__init__", proibido)
    root = projeto(tmp_path)
    cfg = Config.load(root, {"checkers": {"only": ["literatura"]}}, use_user_config=False)
    rep = run(root, cfg)
    assert respx_mock.calls.call_count == 0
    net = by_code(rep.findings, "CORE-NET-001")
    assert len(net) == 1 and "literatura" in net[0].message and "pulado" in net[0].message
    assert not [f for f in rep.findings if f.code.startswith("LIT-")]


def test_nao_altera_tex_nem_bib(
    tmp_path: Path, respx_mock: respx.MockRouter, modelos: None
) -> None:
    router(respx_mock, [])
    root = projeto(tmp_path)

    def hashes() -> dict[str, str]:
        return {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*"))
            if p.suffix in (".tex", ".bib")
        }

    antes = hashes()
    rodar(root)
    rodar(root, refs={"texto_completo": True})
    assert hashes() == antes and len(antes) == 3


def test_opcoes_max_ano_idioma(tmp_path: Path, respx_mock: respx.MockRouter, modelos: None) -> None:
    calls: list[httpx.Request] = []
    router(respx_mock, calls)
    rep = rodar(projeto(tmp_path), literatura={"ano_min": 2021, "idiomas": ["en"]})
    flt = [c.url.params.get("filter", "") for c in calls if c.url.path == "/works"]
    assert flt and all("from_publication_date:2021-01-01" in x and "language:en" in x for x in flt)
    # a fonte de 2020 (pt) sai pelo filtro de ano/idioma
    assert not any("Souza" in " ".join(f.evidence) for f in rep.findings)


def test_excecao_vira_core_checker(
    tmp_path: Path, respx_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    router(respx_mock, [])

    def boom() -> Any:
        raise RuntimeError("falha simulada")

    monkeypatch.setattr(literatura, "_classificador", boom)
    root = projeto(tmp_path)
    cfg = Config.load(
        root,
        {"online": True, "checkers": {"only": ["literatura", "latex"]}},
        use_user_config=False,
    )
    http = HttpClient(cache_dir=None, intervals={}, default_interval=0, backoff=0, retries=0)
    rep = run(root, cfg, http=http)
    core = by_code(rep.findings, "CORE-CHECKER-001")
    assert len(core) == 1 and "literatura" in core[0].message
    assert "latex" in rep.meta["checkers"]


def test_explain_lista_regras_lit() -> None:
    from helpers import cli

    out = cli("explain", "--list").output
    for code in ("LIT-SUG-001", "LIT-REL-001", "LIT-NONE-001", "LIT-LANG-001"):
        assert code in out


def test_saida_exata_terminal_md_json_pdf(
    tmp_path: Path, respx_mock: respx.MockRouter, modelos: None
) -> None:
    from errei.report import render
    from errei.report.pdf import write_pdf

    router(respx_mock, [])
    rep = rodar(projeto(tmp_path))
    term = render.to_term_string(rep)
    md = render.to_markdown(rep)
    data = json.loads(render.to_json(rep))
    esperado = [
        "LIT-SUG-001  sugestão  introducao.tex:2:1",
        'Afirmação : "O uso de redes neurais reduz o tempo de diagnóstico em hospitais."',
        "Fonte     : Smith et al. (2022). Neural networks shorten diagnostic time in emergency "
        "departments. Journal of Medical Systems. DOI: 10.1000/nn.2022",
        "Base      : OpenAlex     Idioma: en",
        'Trecho    : "The use of neural networks reduces diagnostic time in hospitals by 30 '
        'percent."  (resumo)',
        "Relação   : sustenta     Confiança: média",
        "Aviso     : indicador, não veredito. Leia a fonte antes de citar.",
    ]
    for ln in esperado:
        assert ln in term, ln
        assert ln in md, ln
    bloco = next(f["bloco"] for f in data["findings"] if f["code"] == "LIT-SUG-001")
    assert bloco.splitlines() == esperado
    assert "LIT-NONE-001  info  introducao.tex:6:1  nenhuma fonte encontrada" in term
    assert "LIT-REL-001  info  introducao.tex:4:1" in md
    assert "Fonte relacionada (NÃO sustenta a afirmação): Souza (2020)." in md
    assert "## Limitações" in md and any("errei-cita" in x for x in rep.limitations)
    pdf = tmp_path / "r.pdf"
    write_pdf(rep, pdf)
    from pypdf import PdfReader

    texto = " ".join(p.extract_text() or "" for p in PdfReader(str(pdf)).pages)
    assert "LIT-SUG-001" in texto and "Literatura por afirmação" in texto


def test_cli_opcoes_lit(tmp_path: Path) -> None:
    from helpers import cli

    root = projeto(tmp_path)
    res = cli(
        str(root),
        "--format",
        "json",
        "--no-user-config",
        "--only",
        "literatura",
        "--lit-max",
        "2",
        "--lit-ano-min",
        "2018",
        "--lit-idioma",
        "pt,en",
    )
    assert res.exit_code in (0, 1), res.output
    data = json.loads(res.stdout)
    assert data["meta"]["flags"]["lit_max"] == 2
    assert data["meta"]["checkers"] == ["literatura"]
    assert [f["code"] for f in data["findings"]] == ["CORE-NET-001"]  # offline: pulado
    assert cli(str(root), "--lit-idioma", "português").exit_code == 2
    assert cli(str(root), "--lit-ano-min", "18").exit_code == 2
    assert cli(str(root), "--skip", "literatura", "--format", "json").exit_code in (0, 1)


PDF = (Path(__file__).parent / "fixtures" / "literatura" / "texto_aberto.pdf").read_bytes()
PDF_URL = "https://oa.example.org/tele.pdf"


class FakeCitaTexto(FakeCita):
    def probs(self, pares: list[tuple[str, str]]) -> list[dict[str, float]]:
        out = super().probs(pares)
        for i, (_, trecho) in enumerate(pares):
            if "increased treatment adherence" in trecho:
                out[i] = {"sustenta": 0.9, "contradiz": 0.01, "neutro": 0.09}
        return out


def _tele_com_pdf(monkeypatch: pytest.MonkeyPatch, licenca: str) -> None:
    import copy

    fix = copy.deepcopy(FIX)
    w = fix["openalex_busca"]["telemedicina"][0]
    w["best_oa_location"] = {"license": licenca, "pdf_url": PDF_URL}
    monkeypatch.setitem(FIX, "openalex_busca", fix["openalex_busca"])
    monkeypatch.setattr(literatura, "_classificador", lambda: FakeCitaTexto())
    monkeypatch.setattr(literatura, "_tradutor", lambda: FakeTradutor())


@pytest.mark.parametrize("licenca", ["cc-by", "cc0"])
def test_texto_completo_aberto_sustenta_com_pagina(
    tmp_path: Path, respx_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch, licenca: str
) -> None:
    router(respx_mock, [])
    pdf = respx_mock.get(PDF_URL).mock(return_value=httpx.Response(200, content=PDF))
    _tele_com_pdf(monkeypatch, licenca)
    root = projeto(tmp_path)
    sem = rodar(root)  # sem --texto-completo: só o resumo (pt) -> relacionada
    assert pdf.call_count == 0
    assert any("Souza" in " ".join(f.evidence) for f in by_code(sem.findings, "LIT-REL-001"))
    rep = rodar(root, refs={"texto_completo": True})
    assert pdf.call_count == 1
    tele = [f for f in by_code(rep.findings, "LIT-SUG-001") if "Souza" in " ".join(f.evidence)]
    assert len(tele) == 1
    ev = "\n".join(tele[0].evidence)
    assert (
        'Trecho    : "Telemedicine increased treatment adherence in rural areas by 18 percent."'
        "  (p. 2)" in ev
    )
    assert "Confiança: alta" in ev
    # trecho em inglês para afirmação em português
    assert any("Souza" in f.message for f in by_code(rep.findings, "LIT-LANG-001"))


@pytest.mark.parametrize("licenca", ["", "other-oa", "cc-by-nc", "publisher-specific-oa"])
def test_texto_completo_sem_licenca_aberta_nao_baixa(
    tmp_path: Path, respx_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch, licenca: str
) -> None:
    router(respx_mock, [])
    pdf = respx_mock.get(PDF_URL).mock(return_value=httpx.Response(200, content=PDF))
    _tele_com_pdf(monkeypatch, licenca)
    rep = rodar(projeto(tmp_path), refs={"texto_completo": True})
    assert pdf.call_count == 0  # PDF de licença fechada nunca é baixado
    assert not any("Souza" in " ".join(f.evidence) for f in by_code(rep.findings, "LIT-SUG-001"))
    assert any("Souza" in " ".join(f.evidence) for f in by_code(rep.findings, "LIT-REL-001"))


def test_trecho_limitado_a_300_caracteres(
    tmp_path: Path, respx_mock: respx.MockRouter, monkeypatch: pytest.MonkeyPatch, modelos: None
) -> None:
    import copy

    fix = copy.deepcopy(FIX)
    w = fix["openalex_busca"]["neurais"][0]
    longa = "The use of neural networks reduces diagnostic time in hospitals " + "and " * 120
    inv: dict[str, list[int]] = {}
    for i, t in enumerate(longa.split()):
        inv.setdefault(t, []).append(i)
    w["abstract_inverted_index"] = inv
    monkeypatch.setitem(FIX, "openalex_busca", fix["openalex_busca"])
    router(respx_mock, [])
    rep = rodar(projeto(tmp_path))
    sug = by_code(rep.findings, "LIT-SUG-001")[0]
    trecho = next(x for x in sug.evidence if x.startswith("Trecho")).split('"')[1]
    assert len(trecho) <= 300 and trecho.endswith("…")
