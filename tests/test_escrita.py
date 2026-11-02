from __future__ import annotations

from pathlib import Path

from errei.text.metrics import band_score, flesch_pt, mattr, syllables
from helpers import audit, by_code, make_project


def run_es(tmp: Path, body: str):  # type: ignore[no-untyped-def]
    files = {
        "main.tex": "\\documentclass[brazil]{abntex2}\n\\begin{document}\n"
        + body
        + "\n\\end{document}\n"
    }
    rep = audit(make_project(tmp, files), checkers={"only": ["escrita"]})
    return rep


def test_syllables_and_flesch() -> None:
    assert [syllables(w) for w in ("poeta", "pão", "país", "computador")] == [3, 1, 2, 4]
    easy = "O gato come. O cão late. A casa é bela. " * 10
    hard = (
        "A implementação computacional das metodologias epistemológicas contemporâneas "
        "exige considerações interdisciplinares extraordinariamente sofisticadas. "
    ) * 5
    fe, fh = flesch_pt(easy), flesch_pt(hard)
    assert fe is not None and fh is not None and fe[0] > 75 > 25 > fh[0]
    assert flesch_pt("curto.") is None


def test_mattr_and_band() -> None:
    rep = mattr("a b " * 100)
    div = mattr(" ".join("pal" + chr(97 + i // 26) + chr(97 + i % 26) for i in range(300)))
    assert rep is not None and rep < 0.1
    assert div is not None and div > 0.5
    assert band_score(20, 15, 25, 10) == 10.0 and band_score(30, 15, 25, 10) == 5.0


def test_siglas(tmp_path: Path) -> None:
    body = (
        "\\section{Introdução}\nUsamos PLN e IoT aqui \\cite{silva}. O processamento de "
        "linguagem natural (PLN) ajuda. A Internet das Coisas (IoT) também. "
        "O PLN segue. A rede neural convolucional (CNN) aparece só aqui. "
        "O SVM é usado. O SVM de novo. Normas ABNT e PDF. O PLN volta. "
        "Redefinindo processamento (PLN)."
    )
    f = run_es(tmp_path, body).findings
    s1 = sorted(x.message.split("'")[1] for x in by_code(f, "ESCRITA-SIGLA-001"))
    assert s1 == ["IoT", "PLN", "SVM"]
    assert "nunca definida" in next(
        x.message for x in by_code(f, "ESCRITA-SIGLA-001") if "SVM" in x.message
    )
    assert [x.message.split("'")[1] for x in by_code(f, "ESCRITA-SIGLA-003")] == ["CNN"]
    assert by_code(f, "ESCRITA-SIGLA-002")
    assert not any("SILVA" in x.message for x in f)


def test_terms_and_objective(tmp_path: Path) -> None:
    body = (
        "\\section{Introdução}\nO machine-learning é útil. Já o machine learning "
        "também. Nada de objetivo aqui."
    )
    f = run_es(tmp_path, body).findings
    assert "'machine learning' / 'machine-learning'" in by_code(f, "ESCRITA-TERMO-001")[0].message
    assert by_code(f, "ESCRITA-OBJ-001")


def test_abstract_consistency(tmp_path: Path) -> None:
    body = (
        "\\begin{resumo}O método atinge 95\\% de acurácia em 3 bases. "
        + "texto " * 40
        + "\\end{resumo}\n"
        "\\begin{otherlanguage*}{english}\\begin{resumo}[Abstract]The method reaches 90\\% "
        "accuracy.\\end{resumo}\\end{otherlanguage*}"
    )
    f = run_es(tmp_path, body).findings
    msgs = [x.message for x in by_code(f, "ESCRITA-ABS-001")]
    assert any("razão" in m for m in msgs)
    assert any("95%" in m and "90%" in m and "3" in m for m in msgs)


def test_sections_and_review_without_cites(tmp_path: Path) -> None:
    filler = "Texto de exemplo com várias palavras para encher a seção. " * 20
    body = (
        f"\\section{{Introdução}}\n{filler}\n\\section{{Métodos}}\n{filler}\n"
        f"\\section{{Resultados}}\n{filler}\n\\section{{Conclusão}}\nCurta."
    )
    rep = run_es(tmp_path, body)
    assert "Conclusão" in by_code(rep.findings, "ESCRITA-SEC-001")[0].message
    assert "Introdução" in by_code(rep.findings, "ESCRITA-CIT-001")[0].message
    g = rep.metrics[0]
    names = [m.name for m in g.metrics]
    assert "Legibilidade (Flesch, Martins et al. 1996)" in names
    assert all(m.explanation for m in g.metrics)
    assert all(m.score is None or 0 <= m.score <= 10 for m in g.metrics)
