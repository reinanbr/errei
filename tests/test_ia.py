from __future__ import annotations

import json
from pathlib import Path

import pytest

import dummy_detector
from conftest import ARTIGO, line_of
from errei.config import Config
from errei.pipeline import run
from helpers import audit, by_code, make_project

HUMAN = (
    "Coletamos 1.240 artigos do SciELO entre 2015 e 2023 \\cite{a}. Destes, 312 tinham "
    "erros de crase; a maioria (71\\%) ocorria antes de verbos no infinitivo. Curiosamente, "
    "os artigos de Engenharia erravam menos. Não sabemos por quê. Uma hipótese, que "
    "testaremos na próxima etapa com dados de Medicina e Direito, envolve a revisão por "
    "pares mais rigorosa dessas áreas, algo que Ferreira e Lopes já haviam sugerido."
)
LLM = (
    "É importante ressaltar que a inteligência artificial desempenha um papel crucial no "
    "cenário atual da educação. Além disso, vale destacar que ela oferece uma abordagem "
    "abrangente e robusta para os desafios enfrentados pelos professores. Nesse sentido, é "
    "fundamental compreender que a tecnologia impacta diretamente o aprendizado dos alunos. "
    "Dessa forma, a ferramenta se mostra uma solução inovadora e eficaz para a escola. Em "
    "suma, a inteligência artificial representa um avanço significativo para o ensino."
)


def run_ia(tmp: Path, body: str, **cfg: object):  # type: ignore[no-untyped-def]
    root = make_project(
        tmp,
        {"main.tex": "\\documentclass{article}\\begin{document}\n" + body + "\n\\end{document}"},
    )
    over: dict[str, object] = {"checkers": {"only": ["ia"]}}
    if cfg:
        over["ia"] = cfg
    return audit(root, **over)


def test_llm_like_paragraph_flagged_human_not(tmp_path: Path) -> None:
    rep = run_ia(tmp_path, HUMAN + "\n\n" + LLM)
    ind = by_code(rep.findings, "IA-IND-001")
    assert len(ind) == 1 and ind[0].location is not None and ind[0].location.line == 4
    f = ind[0]
    assert f.confidence is not None and f.confidence <= 0.5
    assert any("clichê" in e for e in f.evidence)
    assert "não conclusivo" in f.message
    assert by_code(rep.findings, "IA-CLICHE-001")
    assert rep.metrics and rep.metrics[0].notes


def test_fixture_planted_paragraph() -> None:
    f = by_code(audit(ARTIGO, checkers={"only": ["ia"]}).findings, "IA-IND-001")
    res = ARTIGO / "secoes" / "resultados.tex"
    assert [x.location.line for x in f] == [line_of(res, "É importante ressaltar")]  # type: ignore[union-attr]


def test_threshold_configurable(tmp_path: Path) -> None:
    rep = run_ia(tmp_path, LLM, threshold=0.999)
    assert not by_code(rep.findings, "IA-IND-001")


def test_external_detector_only_from_trusted_config(tmp_path: Path) -> None:
    dummy_detector.LOADED.clear()
    root = make_project(
        tmp_path,
        {
            "main.tex": "\\documentclass{article}\\begin{document}\n" + LLM + "\n\\end{document}",
            ".errei.toml": '[ia]\ndetector = "dummy_detector:Detector"\n',
        },
    )
    rep = run(root, Config.load(root, {"checkers": {"only": ["ia"]}}, use_user_config=False))
    assert not by_code(rep.findings, "IA-EXT-001")
    assert dummy_detector.LOADED == []  # o .errei.toml do artigo não carrega código
    cfg = Config.load(
        root,
        {"checkers": {"only": ["ia"]}, "ia": {"detector": "dummy_detector:Detector"}},
        use_user_config=False,
    )
    rep = run(root, cfg)
    ext = by_code(rep.findings, "IA-EXT-001")
    assert ext and "0.42" in ext[0].message and dummy_detector.LOADED == ["ok"]


def test_bad_detector_degrades(tmp_path: Path) -> None:
    rep = run_ia(tmp_path, LLM, detector="nao_existe:X")
    assert by_code(rep.findings, "CORE-DEP-001")
    assert not by_code(rep.findings, "CORE-CHECKER-001")


FORBIDDEN = (
    "é plágio",
    "foi plagiado",
    "plagiou",
    "foi gerado por ia",
    "gerado por ia.",
    "texto de ia",
    "é ia",
    "referência falsa",
    "é falsa",
    "inventada",
)


@pytest.mark.parametrize("fmt", ["json", "md", "term"])
def test_no_verdict_language(fmt: str, tmp_path: Path) -> None:
    from helpers import cli

    out = tmp_path / f"r.{fmt}"
    res = cli(str(ARTIGO), "--format", fmt, "--out", str(out), "--no-user-config")
    assert res.exit_code in (0, 1)
    text = out.read_text().lower()
    if fmt == "json":
        data = json.loads(text)
        assert data["limitations"]
        data.pop("limitations")
        body = json.dumps(data, ensure_ascii=False)
    else:
        cut = text.rfind("## limitações" if fmt == "md" else "limitações")
        assert cut > 0
        body = text[:cut]
    for bad in FORBIDDEN:
        assert bad not in body, bad
