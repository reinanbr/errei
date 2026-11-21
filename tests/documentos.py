"""Geradores de .docx e .pdf para os testes (sem Word, LibreOffice ou LaTeX)."""

from __future__ import annotations

import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

STYLES = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="{W_NS}">
  <w:docDefaults><w:rPrDefault><w:rPr><w:sz w:val="24"/></w:rPr></w:rPrDefault></w:docDefaults>
  <w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
  <w:style w:type="paragraph" w:styleId="Ttulo"><w:name w:val="Title"/></w:style>
  <w:style w:type="paragraph" w:styleId="Ttulo1"><w:name w:val="heading 1"/>
    <w:basedOn w:val="Normal"/><w:pPr><w:outlineLvl w:val="0"/></w:pPr></w:style>
  <w:style w:type="paragraph" w:styleId="Ttulo2"><w:name w:val="heading 2"/>
    <w:basedOn w:val="Normal"/><w:pPr><w:outlineLvl w:val="1"/></w:pPr></w:style>
  <w:style w:type="paragraph" w:styleId="Citao"><w:name w:val="Quote"/>
    <w:pPr><w:ind w:left="2268"/></w:pPr></w:style>
  <w:style w:type="paragraph" w:styleId="Legenda"><w:name w:val="caption"/></w:style>
  <w:style w:type="paragraph" w:styleId="PargrafodaLista"><w:name w:val="List Paragraph"/></w:style>
</w:styles>"""

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="xml" ContentType="application/xml"/>
</Types>"""


def p(texto: str, estilo: str = "", *, negrito: bool = False, lista: bool = False) -> str:
    """Um parágrafo w:p (``texto`` pode ter runs extras já em XML com ``<r>...</r>``)."""
    ppr = ""
    if estilo or lista:
        ppr = "<w:pPr>"
        if estilo:
            ppr += f'<w:pStyle w:val="{estilo}"/>'
        if lista:
            ppr += '<w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr>'
        ppr += "</w:pPr>"
    rpr = "<w:rPr><w:b/></w:rPr>" if negrito else ""
    return f'<w:p>{ppr}<w:r>{rpr}<w:t xml:space="preserve">{escape(texto)}</w:t></w:r></w:p>'


def tabela(*linhas: tuple[str, ...]) -> str:
    rows = "".join(
        "<w:tr>" + "".join(f"<w:tc>{p(c)}</w:tc>" for c in ln) + "</w:tr>" for ln in linhas
    )
    return f"<w:tbl>{rows}</w:tbl>"


def docx(
    path: Path,
    corpo: list[str],
    *,
    # (superior, direita, inferior, esquerda) em twips; ABNT: 3/2/2/3 cm
    margens: tuple[int, int, int, int] = (1701, 1134, 1134, 1701),
    papel: tuple[int, int] = (11906, 16838),  # A4
    notas: int = 0,
    styles: str = STYLES,
    extra: dict[str, str] | None = None,
) -> Path:
    top, right, bottom, left = margens
    sect = (
        f'<w:sectPr><w:pgSz w:w="{papel[0]}" w:h="{papel[1]}"/>'
        f'<w:pgMar w:top="{top}" w:right="{right}" w:bottom="{bottom}" w:left="{left}"/>'
        "</w:sectPr>"
    )
    doc = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{W_NS}" '
        'xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math">'
        f"<w:body>{''.join(corpo)}{sect}</w:body></w:document>"
    )
    fn = "".join(
        f'<w:footnote w:id="{i}"><w:p><w:r><w:t>nota {i}</w:t></w:r></w:p></w:footnote>'
        for i in range(1, notas + 1)
    )
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("word/document.xml", doc)
        z.writestr("word/styles.xml", styles)
        z.writestr(
            "docProps/core.xml",
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/'
            'metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/">'
            "<dc:title>Artigo de teste</dc:title><dc:creator>Fulana</dc:creator>"
            "</cp:coreProperties>",
        )
        if notas:
            z.writestr("word/footnotes.xml", f'<w:footnotes xmlns:w="{W_NS}">{fn}</w:footnotes>')
        for k, v in (extra or {}).items():
            z.writestr(k, v)
    return path


# ------------------------------------------------------------------ PDF (reportlab)
def pdf(path: Path, paginas: list[list[tuple[str, str]]], *, cabecalho: str = "") -> Path:
    """PDF com texto real. Cada linha: (tipo, texto), tipo em
    'p' (1ª linha de parágrafo, recuada), 'l' (continuação), 't' (título),
    'c' (centralizada), 'q' (citação recuada 4 cm), 'b' (linha em branco)."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path), pagesize=A4)
    w, h = A4
    esq, dir_ = 85, w - 57
    for n, linhas in enumerate(paginas, 1):
        y = h - 85
        if cabecalho:
            c.setFont("Helvetica", 9)
            c.drawString(esq, h - 50, cabecalho)
        for tipo, texto in linhas:
            if tipo == "b":
                y -= 18
                continue
            c.setFont("Helvetica-Bold" if tipo == "t" else "Helvetica", 11)
            if tipo == "c":
                c.drawCentredString((esq + dir_) / 2, y, texto)
            elif tipo == "p":
                c.drawString(esq + 35, y, texto)
            elif tipo == "q":
                c.setFont("Helvetica", 10)
                c.drawString(esq + 113, y, texto)
            else:
                c.drawString(esq, y, texto)
            y -= 16 if tipo != "t" else 26
        c.setFont("Helvetica", 9)
        c.drawCentredString(w / 2, 40, str(n))
        c.showPage()
    c.save()
    return path


def pdf_vazio(path: Path) -> Path:
    """PDF só com um desenho (como uma digitalização: sem texto)."""
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path))
    c.rect(100, 100, 200, 200, fill=1)
    c.showPage()
    c.save()
    return path
