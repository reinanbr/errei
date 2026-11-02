from __future__ import annotations

from pathlib import Path

from helpers import audit, by_code, codes, make_project

WORDS = " ".join(["palavra"] * 160) + "."


def doc(
    body: str,
    preamble: str = "\\usepackage[alf]{abntex2cite}\n",
    bib: str = "@article{a, author={Souza, Ana}, title={T}, journal={J}, year={2020}, "
    "volume={1}, pages={1--2}, doi={10.1000/x}}",
) -> dict[str, str]:
    return {
        "main.tex": "\\documentclass[12pt,a4paper,brazil]{abntex2}\n"
        + preamble
        + "\\begin{document}\n"
        + body
        + "\n\\bibliography{r}\n\\end{document}\n",
        "r.bib": bib,
    }


GOOD_ABS = (
    "\\begin{resumoumacoluna}\n" + WORDS + "\n\n\\textbf{Palavras-chave}: um; dois; três.\n"
    "\\end{resumoumacoluna}\n"
    "\\begin{otherlanguage*}{english}\n\\begin{resumoumacoluna}\n"
    + " ".join(["word"] * 160)
    + ".\n\n\\textbf{Keywords}: one; two; three.\n\\end{resumoumacoluna}\n\\end{otherlanguage*}\n"
    "\\section{Introdução}\nTexto \\cite{a}.\n\\section{Conclusão}\nFim.\n"
)


def run_abnt(tmp: Path, files: dict[str, str]):  # type: ignore[no-untyped-def]
    return audit(make_project(tmp, files), checkers={"only": ["abnt"]}).findings


def test_good_document_is_quiet(tmp_path: Path) -> None:
    f = run_abnt(tmp_path, doc(GOOD_ABS))
    assert {x.code for x in f} <= {"ABNT-STYLE-001", "ABNT-CIT-006"}, codes(f)


def test_missing_everything(tmp_path: Path) -> None:
    f = run_abnt(
        tmp_path,
        {"main.tex": "\\documentclass{article}\\begin{document}\\section{Métodos}x\\end{document}"},
    )
    for c in (
        "ABNT-RESUMO-001",
        "ABNT-ABSTRACT-001",
        "ABNT-ESTR-001",
        "ABNT-ESTR-002",
        "ABNT-ESTR-003",
    ):
        assert c in codes(f), c


def test_short_resumo_two_paragraphs_and_keywords(tmp_path: Path) -> None:
    body = (
        "\\begin{resumo}\nCurto demais \\cite{a}.\n\nSegundo parágrafo.\n\n"
        "Palavras-chave: Um. dois\n\\end{resumo}\n"
        + GOOD_ABS.split("\\begin{otherlanguage*}")[0]
        .replace("\\begin{resumoumacoluna}", "%")
        .replace("\\end{resumoumacoluna}", "%")
    )
    f = run_abnt(tmp_path, doc(body))
    r2 = by_code(f, "ABNT-RESUMO-002")
    assert r2 and "palavras" in r2[0].message and r2[0].location.line == 5  # type: ignore[union-attr]
    assert by_code(f, "ABNT-RESUMO-003") and by_code(f, "ABNT-RESUMO-004")
    assert by_code(f, "ABNT-KW-005") and by_code(f, "ABNT-KW-003") and by_code(f, "ABNT-KW-004")


def test_section_style_resumo(tmp_path: Path) -> None:
    body = (
        "\\section*{Resumo}\n" + WORDS + "\n\n\\textbf{Palavras-chave:} a; b; c.\n"
        "\\section*{Abstract}\n" + " ".join(["w"] * 160) + ".\n\nKeywords: a; b; c.\n"
        "\\section{Introdução}x\\section{Considerações finais}y"
    )
    f = run_abnt(tmp_path, doc(body))
    assert not {"ABNT-RESUMO-001", "ABNT-ABSTRACT-001", "ABNT-KW-001", "ABNT-ESTR-002"} & set(
        codes(f)
    )


def test_citations(tmp_path: Path) -> None:
    long_quote = "“" + " ".join(["palavra"] * 45) + "” \\cite{a}"
    body = (
        GOOD_ABS
        + "Segundo Fulano apud Beltrano, e Silva et al (2020) e (SILVA, 2020).\n\n"
        + long_quote
        + "\n\nOutro “trecho curto citado aqui” \\cite[p.~3]{a}.\n"
    )
    f = run_abnt(tmp_path, doc(body))
    assert by_code(f, "ABNT-CIT-001")[0].suggestion
    assert by_code(f, "ABNT-CIT-003")[0].message == "'et al' → 'et al.'"
    assert "(SILVA, 2020)" in by_code(f, "ABNT-CIT-004")[0].message
    long = by_code(f, "ABNT-CIT-002")
    assert long and long[0].manual_review
    nopage = by_code(f, "ABNT-CIT-005")
    assert len(nopage) == 1  # o trecho curto tem p.~3


def test_references(tmp_path: Path) -> None:
    bib = (
        "@book{b, author={SILVA, João and others}, title={L}, publisher={P}, year={2000}}\n"
        "@misc{s, title={Site}, url={https://x.org}, year={2020}}\n"
        "@article{a, author={Souza, Ana et al.}, title={T}, journal={J}, year={2020}}\n"
    )
    f = run_abnt(tmp_path, doc(GOOD_ABS + "\\nocite{*}", bib=bib))
    assert by_code(f, "ABNT-REF-001")[0].suggestion == "Silva"
    assert by_code(f, "ABNT-REF-002") and by_code(f, "ABNT-REF-003")
    assert "urlaccessdate" in (by_code(f, "ABNT-REF-004")[0].suggestion or "")
    assert "volume, pages" in by_code(f, "ABNT-REF-005")[0].message


def test_style_and_format(tmp_path: Path) -> None:
    files = doc(
        GOOD_ABS,
        preamble="\\usepackage{natbib}\n\\bibliographystyle{plainnat}\n"
        "\\usepackage[left=2cm,top=3cm]{geometry}\n",
    )
    files["main.tex"] = files["main.tex"].replace("12pt,a4paper", "10pt,letterpaper")
    f = run_abnt(tmp_path, files)
    assert len(by_code(f, "ABNT-STYLE-002")) >= 1
    assert "fonte 10pt" in by_code(f, "ABNT-FMT-001")[0].message
    assert "left=2cm" in by_code(f, "ABNT-FMT-002")[0].message
    assert "ABNT-CIT-006" not in codes(f)
