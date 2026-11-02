from __future__ import annotations

from pathlib import Path

import httpx
import respx

from conftest import ARTIGO, FIXTURES, line_of
from errei.config import Config
from errei.net.client import HttpClient
from errei.pipeline import run
from errei.text.similarity import containment, shared_span, shingles, tokens
from helpers import audit, by_code, make_project

METOD = ARTIGO / "secoes" / "metodologia.tex"


def test_shingles_and_span() -> None:
    a = tokens("um dois três quatro cinco seis sete oito nove dez")
    b = tokens("zero um dois três quatro cinco seis sete oito nove onze")
    sa, sb = shingles(a, 4), shingles(b, 4)
    assert containment(set(sa), set(sb)) > 0.6
    s, e, n = shared_span(sb, set(sa), b, 4)
    assert n == 9 and "um dois" in "zero um dois três quatro cinco seis sete oito nove onze"[s:e]
    assert shingles(tokens("Ação"), 1) == shingles(tokens("acao"), 1)  # normaliza acento/caixa


def test_internal_repetition_fixture() -> None:
    f = audit(ARTIGO, checkers={"only": ["plagio"]}).findings
    hit = by_code(f, "PLAGIO-INT-001")
    assert len(hit) == 1
    concl = ARTIGO / "secoes" / "conclusao.tex"
    assert hit[0].location is not None
    assert hit[0].location.file.as_posix() == "secoes/conclusao.tex"
    assert hit[0].location.line == line_of(concl, "O objetivo deste trabalho")
    assert "introducao.tex:14" in hit[0].message
    assert hit[0].confidence and hit[0].confidence > 0.9


def test_no_false_positive_on_distinct_text(tmp_path: Path) -> None:
    body = (
        "Primeiro parágrafo fala de redes neurais aplicadas à tradução automática de textos.\n\n"
        "Segundo parágrafo descreve solos tropicais e a fertilidade em regiões úmidas do país."
    )
    root = make_project(
        tmp_path,
        {"main.tex": "\\documentclass{article}\\begin{document}" + body + "\\end{document}"},
    )
    assert not audit(root, checkers={"only": ["plagio"]}).findings


def test_cited_repetition_has_lower_confidence(tmp_path: Path) -> None:
    rep = "um trecho reaproveitado com bastante palavras em sequência para gerar shingles comuns"
    body = f"{rep} aqui.\n\nOutra parte. {rep} \\cite{{x}}."
    root = make_project(
        tmp_path,
        {"main.tex": "\\documentclass{article}\\begin{document}" + body + "\\end{document}"},
    )
    hit = by_code(audit(root, checkers={"only": ["plagio"]}).findings, "PLAGIO-INT-001")[0]
    assert any("citação próxima" in e for e in hit.evidence)
    assert hit.confidence is not None and hit.confidence < 0.7


def test_local_corpus() -> None:
    rep = audit(
        ARTIGO,
        checkers={"only": ["plagio"]},
        plagio={"corpus": [str(FIXTURES / "corpus"), "nao/existe"]},
    )
    hit = by_code(rep.findings, "PLAGIO-CORPUS-001")
    assert len(hit) == 1 and "fonte_externa.txt" in hit[0].message
    assert hit[0].location is not None
    assert hit[0].location.line == line_of(METOD, "Primeiro, os")
    assert by_code(rep.findings, "PLAGIO-CORPUS-002")  # pasta inexistente reportada


def test_online_phrase_search(tmp_path: Path, respx_mock: respx.MockRouter) -> None:
    sentence = (
        "Os autovalores espectrais da matriz laplaciana normalizada revelam comunidades "
        "latentes em grafos heterogêneos esparsos"
    )
    root = make_project(
        tmp_path,
        {"main.tex": "\\documentclass{article}\\begin{document}" + sentence + ".\\end{document}"},
    )
    respx_mock.get(url__startswith="https://api.openalex.org/works").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "Spectral communities",
                        "publication_year": 2019,
                        "doi": "https://doi.org/10.1/abc",
                        "authorships": [],
                        "abstract_inverted_index": {
                            w: [i]
                            for i, w in enumerate(
                                ("Neste estudo " + sentence + " de grande porte.").split()
                            )
                        },
                    }
                ]
            },
        )
    )
    respx_mock.route().mock(return_value=httpx.Response(200, json={}))
    cfg = Config.load(
        root, {"online": True, "checkers": {"only": ["plagio"]}}, use_user_config=False
    )
    rep = run(
        root, cfg, http=HttpClient(cache_dir=None, intervals={}, default_interval=0, backoff=0)
    )
    hit = by_code(rep.findings, "PLAGIO-WEB-001")
    assert hit and "Spectral communities" in hit[0].message
    assert hit[0].links == ("https://doi.org/10.1/abc",)
    assert "plágio" not in hit[0].message.lower()
