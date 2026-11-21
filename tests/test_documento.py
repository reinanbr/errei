"""Auditoria de trabalhos em .docx e .pdf (leitura, referências, citações, relatório)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from documentos import docx, p, pdf, pdf_vazio, tabela
from errei.documento.converter import classificar
from errei.documento.modelo import DocumentoError, ler
from errei.documento.referencias import Indice, analisar, citacoes
from errei.model import Location
from errei.project import ProjectError, load_project
from helpers import audit, by_code, cli, codes

pytest.importorskip("pypdf")

REFS = [
    "MARTINS, T. B. F. et al. Readability formulas applied to textbooks in Brazilian "
    "Portuguese. São Carlos: ICMC-USP, 1996.",
    "FLESCH, R. A new readability yardstick. Journal of Applied Psychology, v. 32, n. 3, "
    "p. 221-233, 1948.",
    "DUBAY, W. H. The principles of readability. Costa Mesa: Impact Information, 2004. "
    "Disponível em: https://files.eric.ed.gov/fulltext/ED490073.pdf.",
]
RESUMO = (
    "Este artigo avalia a legibilidade de livros didáticos brasileiros com fórmulas clássicas "
    "adaptadas ao português. O objetivo é verificar se os textos estão adequados à faixa "
    "etária. Foram analisados vinte livros com o índice de Flesch adaptado. Os resultados "
    "indicam que metade dos textos é difícil. Conclui-se que a escolha dos materiais deve "
    "considerar a legibilidade."
)


def artigo_docx(tmp: Path, nome: str = "artigo.docx", **kw: object) -> Path:
    corpo = [
        p("Legibilidade de textos escolares", "Ttulo"),
        p("Resumo", negrito=True),
        p(RESUMO),
        p("Palavras-chave: legibilidade; livros didáticos; Flesch."),
        p("1 Introdução", "Ttulo1"),
        p(
            "A legibilidade é estudada há décadas (FLESCH, 1948). Segundo Martins et al. "
            "(1996), as fórmulas precisam ser adaptadas. Também se cita (SOUZA, 2030), que "
            "não está na lista."
        ),
        p(
            "A legibilidade é a facilidade com que um texto pode ser lido e compreendido por "
            "um leitor, e depende do vocabulário e da estrutura das frases (DUBAY, 2004, p. 3).",
            "Citao",
        ),
        p("2 Metodologia", "Ttulo1"),
        p("Os passos foram:"),
        p("selecionar vinte livros;", lista=True),
        p("calcular o índice.", lista=True),
        tabela(("Série", "Livros"), ("6º ano", "10")),
        p("2.1 Análise", "Ttulo2"),
        p("Os índices foram comparados com as faixas propostas para o português."),
        p("Referências", "Ttulo1"),
        *(p(r) for r in REFS),
    ]
    return docx(tmp / nome, corpo, **kw)  # type: ignore[arg-type]


# ---------------------------------------------------------------- leitura do .docx
def test_docx_le_estrutura(tmp_path: Path) -> None:
    arq = artigo_docx(tmp_path, notas=2)
    d = ler(arq, Path(arq.name))
    assert d.formato == "docx" and d.unidade == "§"
    assert d.papel == "a4" and d.fonte_pt == 12.0
    assert round(d.margens_cm["left"]) == 3 and round(d.margens_cm["right"]) == 2
    titulos = [(b.texto, b.nivel) for b in d.blocos if b.nivel]
    assert ("1 Introdução", 1) in titulos and ("2.1 Análise", 2) in titulos
    assert [b.texto for b in d.blocos if b.lista] == [
        "selecionar vinte livros;",
        "calcular o índice.",
    ]
    assert any(b.recuado for b in d.blocos if b.texto.startswith("A legibilidade é a"))
    assert all(b.tabela for b in d.blocos if b.texto in ("Série", "6º ano"))
    assert d.ignorado.get("notas de rodapé") == 2


def test_docx_classifica_secoes(tmp_path: Path) -> None:
    d = ler(artigo_docx(tmp_path), Path("artigo.docx"))
    itens, refs, info = classificar(d)
    papeis = [(i.papel, i.tipo) for i in itens]
    assert ("titulo", "") in papeis and ("secao", "resumo") in papeis
    assert ("citacao", "") in papeis and ("secao", "refs") in papeis
    assert len(refs) == 3 and info.pulados.get("tabelas", 0) >= 1


@pytest.mark.parametrize(
    "conteudo",
    [
        b"isto nao e um zip",
        None,  # zip sem word/document.xml
    ],
)
def test_docx_invalido(tmp_path: Path, conteudo: bytes | None) -> None:
    import zipfile

    arq = tmp_path / "x.docx"
    if conteudo is None:
        with zipfile.ZipFile(arq, "w") as z:
            z.writestr("outro.xml", "<a/>")
    else:
        arq.write_bytes(conteudo)
    with pytest.raises(DocumentoError):
        ler(arq, Path(arq.name))


def test_docx_rejeita_dtd(tmp_path: Path) -> None:
    """Entidades XML (XXE, 'billion laughs') nunca são expandidas."""
    arq = docx(tmp_path / "x.docx", [p("ok")])
    import zipfile

    mal = tmp_path / "mal.docx"
    with zipfile.ZipFile(arq) as src, zipfile.ZipFile(mal, "w") as z:
        for n in src.namelist():
            dados = src.read(n)
            if n == "word/document.xml":
                dados = dados.replace(
                    b"<w:document",
                    b'<!DOCTYPE d [<!ENTITY x SYSTEM "file:///etc/passwd">]><w:document',
                    1,
                )
            z.writestr(n, dados)
    with pytest.raises(DocumentoError):
        ler(mal, Path(mal.name))


# ---------------------------------------------------------------- referências e citações
@pytest.mark.parametrize(
    ("texto", "sobrenome", "ano", "estilo"),
    [
        (REFS[1], "Flesch", "1948", "abnt"),
        (
            "LeCun, Y., Bengio, Y., & Hinton, G. (2015). Deep learning. Nature, 521, 436-444.",
            "LeCun",
            "2015",
            "apa",
        ),
        (
            '[3] R. Flesch, "A new readability yardstick," J. Appl. Psychol., vol. 32, 1948.',
            "Flesch",
            "1948",
            "ieee",
        ),
        (
            "BRASIL. Ministério da Educação. Base Nacional Comum Curricular. Brasília: MEC, 2018.",
            "Brasil",
            "2018",
            "abnt",
        ),
    ],
)
def test_referencias_estilos(texto: str, sobrenome: str, ano: str, estilo: str) -> None:
    r = analisar(texto)
    assert r.sobrenome.lower() == sobrenome.lower()
    assert r.ano == ano and r.titulo and r.reconhecida
    assert r.estilo == estilo


def test_referencia_irreconhecivel() -> None:
    r = analisar("KANT, I. Isso não é uma referência no formato")
    assert not r.reconhecida and r.ano == ""


def test_citacoes_formas() -> None:
    idx = Indice([analisar(r) for r in REFS])
    t = (
        "Estudada há décadas (FLESCH, 1948; DUBAY, 2004, p. 3). Segundo Martins et al. (1996), "
        "o índice de Flesch (1948 apud MARTINS et al., 1996) foi adaptado (SOUZA, 2030)."
    )
    cs = citacoes(t, idx)
    formas = [c.forma for c in cs]
    assert formas == ["paren", "narr", "narr-apud", "paren"]
    assert [o.chave for o in cs[0].obras] == ["flesch1948", "dubay2004"]
    assert cs[0].obras[1].pagina == "p. 3"
    assert [o.chave for o in cs[2].apud_obras] == ["flesch1948"]
    assert not cs[3].obras[0].conhecida  # SOUZA, 2030 não está na lista


def test_citacoes_numericas() -> None:
    refs = [
        analisar(f'[{i}] A. Autor{i}, "Título {i}," Rev., vol. 1, 20{10 + i}.') for i in (1, 2, 3)
    ]
    idx = Indice(refs)
    k = [r.chave for r in refs]
    cs = citacoes("Como em [1], [2-3] e [9]; o intervalo [0, 500] não é citação.", idx)
    assert [[o.chave for o in c.obras] for c in cs] == [[k[0]], [k[1], k[2]], ["ref9"]]
    assert not cs[-1].obras[0].conhecida
    assert idx.novas == {"ref9": "[9]"}


# ---------------------------------------------------------------- auditoria completa
def test_auditoria_docx(tmp_path: Path, readonly_guard) -> None:  # type: ignore[no-untyped-def]
    arq = artigo_docx(tmp_path)
    readonly_guard(tmp_path)
    rep = audit(arq, only=["documento", "refs", "abnt", "apud"])
    fs = rep.findings
    cite = by_code(fs, "REFS-CITE-001")
    assert [f.message for f in cite] == [
        "citação 'SOUZA, 2030' sem entrada na lista de referências"
    ]
    loc = cite[0].location
    assert loc is not None and loc.unit == "§" and str(loc).startswith("artigo.docx, § ")
    assert cite[0].excerpt == "(SOUZA, 2030)"
    ordem = by_code(fs, "DOC-REF-002")
    assert ordem and "'FLESCH, 1948' está depois de 'MARTINS et al., 1996'" in ordem[0].message
    assert "DOC-LEITURA-001" in codes(fs)
    # nada fala de .bib nem sugere comandos LaTeX
    for f in fs:
        assert ".bib" not in f.message, f
        assert "\\" not in (f.suggestion or ""), f
    assert not {"ABNT-REF-001", "REFS-FIELD-001", "COMP-META-001"} & set(codes(fs))
    assert rep.meta["documento"]["formato"] == "docx"
    assert rep.meta["documento"]["citacoes_sem_referencia"] == 1


def test_auditoria_docx_margens(tmp_path: Path) -> None:
    arq = artigo_docx(tmp_path, margens=(567, 567, 567, 1134))  # 1/1/1/2 cm
    fs = audit(arq, only=["abnt"]).findings
    assert by_code(fs, "ABNT-FMT-002")


def pagina1() -> list[tuple[str, str]]:
    return [
        ("c", "LEGIBILIDADE DE TEXTOS ESCOLARES"),
        ("b", ""),
        ("c", "Maria Souza"),
        ("b", ""),
        ("t", "1 INTRODUÇÃO"),
        ("p", "A legibilidade é estudada há décadas (FLESCH, 1948). Segundo Martins et al."),
        ("l", "(1996), as fórmulas precisam ser adaptadas ao português, como visto na Seção"),
        ("l", "??, e o resultado se mantém."),
        ("b", ""),
        ("p", "Trabalhos recentes usam aprendizado de máquina, mas as fórmulas continuam"),
        ("l", "úteis pela simplicidade e pelo baixo custo."),
    ]


def test_pdf_le_paginas_e_cabecalho(tmp_path: Path) -> None:
    pytest.importorskip("reportlab")
    pg2 = [("t", "REFERÊNCIAS"), *(("l", r[:90]) for r in REFS[:2])]
    arq = pdf(tmp_path / "a.pdf", [pagina1(), pg2], cabecalho="Revista X, v. 1, 2024")
    d = ler(arq, Path(arq.name))
    assert d.formato == "pdf" and d.paginas == 2 and d.unidade == "p."
    textos = [b.texto for b in d.blocos]
    assert not any("Revista X" in t for t in textos)  # cabeçalho repetido removido
    assert not any(t.strip() in ("1", "2") for t in textos)  # número de página removido
    par = next(b for b in d.blocos if b.texto.startswith("A legibilidade"))
    assert "Martins et al. (1996)" in par.texto  # linhas do parágrafo juntas
    itens, _, _ = classificar(d)
    assert any(i.papel == "secao" and i.texto == "1 INTRODUÇÃO" for i in itens)


def test_auditoria_pdf(tmp_path: Path) -> None:
    pytest.importorskip("reportlab")
    pg2 = [("t", "REFERÊNCIAS"), ("l", REFS[1][:95]), ("b", ""), ("l", REFS[0][:95])]
    arq = pdf(tmp_path / "a.pdf", [pagina1(), pg2])
    fs = audit(arq, only=["documento", "refs"]).findings
    q = by_code(fs, "DOC-CIT-001")
    assert q and q[0].location is not None and q[0].location.rotulo == "p. 1"
    leitura = by_code(fs, "DOC-LEITURA-001")[0]
    assert "2 referência(s)" in leitura.message


def test_pdf_sem_texto(tmp_path: Path) -> None:
    pytest.importorskip("reportlab")
    arq = pdf_vazio(tmp_path / "scan.pdf")
    with pytest.raises(ProjectError, match="OCR"):
        load_project(arq)


# ---------------------------------------------------------------- pasta, CLI, localização
def test_pasta_com_um_documento(tmp_path: Path) -> None:
    artigo_docx(tmp_path)
    proj = load_project(tmp_path)
    assert proj.formato == "docx"
    assert any("auditando artigo.docx" in n for n in proj.notes)


def test_pasta_com_varios_documentos(tmp_path: Path) -> None:
    artigo_docx(tmp_path, "a.docx")
    artigo_docx(tmp_path, "b.docx")
    with pytest.raises(ProjectError, match="indique qual"):
        load_project(tmp_path)


def test_pasta_latex_ignora_docx(tmp_path: Path) -> None:
    artigo_docx(tmp_path)
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\\begin{document}Oi.\\end{document}", encoding="utf-8"
    )
    assert load_project(tmp_path).formato == "latex"


def test_formato_nao_suportado(tmp_path: Path) -> None:
    (tmp_path / "a.odt").write_bytes(b"x")
    with pytest.raises(ProjectError, match="formato não suportado"):
        load_project(tmp_path / "a.odt")


def test_cli_json_docx(tmp_path: Path) -> None:
    arq = artigo_docx(tmp_path)
    res = cli(str(arq), "--format", "json", "--no-user-config", "--only", "refs,documento")
    assert res.exit_code in (0, 1), res.output
    data = json.loads(res.stdout)
    f = next(x for x in data["findings"] if x["code"] == "REFS-CITE-001")
    assert f["unit"] == "§" and f["file"] == "artigo.docx"
    assert "latex" not in data["meta"]["checkers"]


def test_cli_markdown_docx(tmp_path: Path) -> None:
    arq = artigo_docx(tmp_path)
    res = cli(str(arq), "--format", "md", "--no-user-config", "--only", "refs")
    assert "### `artigo.docx`" in res.stdout and "`REFS-CITE-001` § " in res.stdout
    assert ".bib" not in res.stdout and "código-fonte LaTeX" not in res.stdout


def test_latex_checker_so_no_latex(tmp_path: Path) -> None:
    rep = audit(artigo_docx(tmp_path), only=["latex", "documento"])
    assert not [f for f in rep.findings if f.checker == "latex"]
    assert any("não se aplicam a .docx: latex" in f.message for f in rep.findings)


@pytest.mark.parametrize(
    ("loc", "esperado"),
    [
        (Location(Path("a.tex"), 12, 5), "a.tex:12:5"),
        (Location(Path("a.docx"), 7, unit="§"), "a.docx, § 7"),
        (Location(Path("a.pdf"), 3, end_line=4, unit="p."), "a.pdf, p. 3–4"),
        (Location(Path("a.pdf"), 0, unit="p."), "a.pdf"),
    ],
)
def test_location_rotulo(loc: Location, esperado: str) -> None:
    assert str(loc) == esperado
