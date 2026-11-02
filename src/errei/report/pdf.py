"""Relatório em PDF (reportlab, extra ``errei[pdf]``).

Estrutura: capa com resumo → principais problemas → possíveis melhorias →
referências verificadas (obra encontrada + validação da atribuição) → métricas →
todos os achados por arquivo → limitações.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from errei.model import Finding, Severity
from errei.report.build import Report
from errei.report.highlights import improvements, top_problems

FONT_DIRS = (
    "/usr/share/fonts/truetype/dejavu",
    "/usr/share/fonts/dejavu",
    "/usr/share/fonts/TTF",
    "/usr/local/share/fonts",
    "/Library/Fonts",
)
SEV_COLOR = {
    Severity.ERRO: "#b3261e",
    Severity.AVISO: "#a15c00",
    Severity.SUGESTAO: "#1f5fa8",
    Severity.INFO: "#666666",
}
SEV_LABEL = {
    Severity.ERRO: "erro",
    Severity.AVISO: "aviso",
    Severity.SUGESTAO: "sugestão",
    Severity.INFO: "info",
}
VERDICT_COLOR = {
    "sustenta": "#2e7d32",
    "contradiz": "#b3261e",
    "neutro": "#a15c00",
    "sem resumo": "#666666",
}
_FALLBACK_CHARS = {
    "→": "->",
    "≤": "<=",
    "≥": ">=",
    "≠": "!=",
    "×": "x",
    "…": "...",
    "│": "|",
    "·": "-",
    "–": "-",
    "—": "-",
    "“": '"',
    "”": '"',
    "‘": "'",
    "’": "'",
    "ʼ": "'",
}


class PdfUnavailableError(RuntimeError):
    pass


def _fonts() -> tuple[str, str]:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    for d in FONT_DIRS:
        reg, bold = Path(d) / "DejaVuSans.ttf", Path(d) / "DejaVuSans-Bold.ttf"
        if reg.is_file() and bold.is_file():
            try:
                pdfmetrics.registerFont(TTFont("ErreiSans", str(reg)))
                pdfmetrics.registerFont(TTFont("ErreiSans-Bold", str(bold)))
                return "ErreiSans", "ErreiSans-Bold"
            except Exception:  # pragma: no cover - fonte corrompida
                continue
    return "Helvetica", "Helvetica-Bold"


def write_pdf(report: Report, path: Path) -> None:
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_LEFT
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.platypus import (
            KeepTogether,
            PageBreak,
            Paragraph,
            SimpleDocTemplate,
            Spacer,
            Table,
            TableStyle,
        )
    except ModuleNotFoundError as exc:
        raise PdfUnavailableError(
            "o relatório PDF requer o extra: pip install 'errei[pdf]'"
        ) from exc

    font, bold = _fonts()
    unicode_ok = font != "Helvetica"

    def t(s: Any) -> str:
        text = "" if s is None else str(s)
        if not unicode_ok:
            for k, v in _FALLBACK_CHARS.items():
                text = text.replace(k, v)
            text = text.encode("latin-1", "replace").decode("latin-1")
        return escape(text)

    base = getSampleStyleSheet()
    st = {
        "title": ParagraphStyle(
            "t", parent=base["Title"], fontName=bold, fontSize=20, spaceAfter=6
        ),
        "h1": ParagraphStyle(
            "h1",
            parent=base["Heading1"],
            fontName=bold,
            fontSize=14,
            spaceBefore=12,
            spaceAfter=6,
            textColor=colors.HexColor("#1b2a41"),
        ),
        "h2": ParagraphStyle(
            "h2", parent=base["Heading2"], fontName=bold, fontSize=11, spaceBefore=8, spaceAfter=4
        ),
        "p": ParagraphStyle(
            "p", parent=base["BodyText"], fontName=font, fontSize=9, leading=12, alignment=TA_LEFT
        ),
        "small": ParagraphStyle(
            "s",
            parent=base["BodyText"],
            fontName=font,
            fontSize=7.5,
            leading=9.5,
            textColor=colors.HexColor("#444444"),
        ),
        "cell": ParagraphStyle(
            "c", parent=base["BodyText"], fontName=font, fontSize=7.8, leading=9.6
        ),
        "cellb": ParagraphStyle(
            "cb", parent=base["BodyText"], fontName=bold, fontSize=7.8, leading=9.6
        ),
        "note": ParagraphStyle(
            "n",
            parent=base["BodyText"],
            fontName=font,
            fontSize=8,
            leading=10.5,
            textColor=colors.HexColor("#555555"),
            backColor=colors.HexColor("#f4f4f4"),
            borderPadding=4,
        ),
    }
    grid = TableStyle(
        [
            ("FONTNAME", (0, 0), (-1, -1), font),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1b2a41")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), bold),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f6f7f9")]),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#c9ced6")),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ]
    )

    def P(text: str, style: str = "cell") -> Any:  # noqa: N802
        return Paragraph(text, st[style])

    def sev(s: Severity) -> str:
        return f'<font color="{SEV_COLOR[s]}"><b>{SEV_LABEL[s]}</b></font>'

    def loc(f: Finding) -> str:
        if not f.location:
            return "(projeto)"
        col = f":{f.location.column}" if f.location.column else ""
        return t(f"{f.location.file.as_posix()}:{f.location.line}{col}")

    def table(rows: list[list[Any]], widths: list[float], header: list[str]) -> Any:
        tb = Table(
            [[P(f'<font color="white"><b>{t(h)}</b></font>', "cell") for h in header], *rows],
            colWidths=widths,
            repeatRows=1,
        )
        tb.setStyle(grid)
        return tb

    m = report.meta
    W = A4[0] - 3.4 * cm  # noqa: N806
    story: list[Any] = []

    # ---------------------------------------------------------------- capa
    story.append(P("Relatório do errei", "title"))
    story.append(P(t(f"Auditoria do artigo em {m.get('root')}"), "p"))
    story.append(Spacer(1, 6))
    info: list[list[Any]] = [
        ["Arquivo principal", m.get("main")],
        ["Data", m.get("date")],
        ["Versão", f"errei {m.get('version')}"],
        ["Hash do projeto (sha256)", m.get("project_hash")],
        ["Online", "sim" if m.get("online") else "não"],
        ["Verificadores", ", ".join(m.get("checkers", []))],
    ]
    if m.get("qualis_csv"):
        info.append(["CSV Qualis", f"{m['qualis_csv']} (referência: {m.get('qualis_data')})"])
    if m.get("modelo_citacoes"):
        info.append(["Modelo de citações", m["modelo_citacoes"]])
    tb = Table(
        [[P(f"<b>{t(a)}</b>"), P(t(b))] for a, b in info], colWidths=[4.2 * cm, W - 4.2 * cm]
    )
    tb.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), font),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#dddddd")),
            ]
        )
    )
    story.append(tb)

    story.append(P("Resumo", "h1"))
    counts = report.by_severity()
    head = ["verificador", "erro", "aviso", "sugestão", "info"]
    rows = [[P(t(c)), *[P(str(v[s])) for s in Severity]] for c, v in report.by_checker().items()]
    rows.append([P("<b>total</b>"), *[P(f"<b>{counts[s]}</b>") for s in Severity]])
    story.append(table(rows, [W - 4 * 2.2 * cm, *[2.2 * cm] * 4], head))
    story.append(Spacer(1, 6))
    story.append(
        P(
            "Nenhum achado é um veredito: similaridade, indícios de IA, validação de "
            "citações e Qualis são indicadores com confiança e justificativa. Veja "
            "“Limitações” ao final.",
            "note",
        )
    )

    # ---------------------------------------------------------------- principais
    def finding_rows(items: list[Finding], with_sev: bool = True) -> list[list[Any]]:
        out = []
        for f in items:
            msg = f"<b>{t(f.code)}</b> — {t(f.message)}"
            if f.confidence is not None:
                msg += t(f" (confiança {f.confidence:.0%})")
            if f.excerpt:
                msg += f'<br/><font color="#666666">trecho: {t(f.excerpt)}</font>'
            if f.suggestion:
                msg += f'<br/><font color="#2e7d32">→ {t(f.suggestion)}</font>'
            for ev in f.evidence[:4]:
                msg += f'<br/><font color="#555555">· {t(ev)}</font>'
            row = [P(loc(f))]
            if with_sev:
                row.append(P(sev(f.severity)))
            row.append(P(msg))
            out.append(row)
        return out

    probs = top_problems(report, 25)
    story.append(P("Principais problemas (onde corrigir)", "h1"))
    if probs:
        story.append(
            table(
                finding_rows(probs),
                [4.3 * cm, 1.5 * cm, W - 5.8 * cm],
                ["onde", "sev.", "problema e sugestão"],
            )
        )
    else:
        story.append(P("Nenhum erro ou aviso.", "p"))
    melh = improvements(report, 25)
    story.append(P("Possíveis melhorias", "h1"))
    if melh:
        story.append(
            table(
                finding_rows(melh, with_sev=False), [4.3 * cm, W - 4.3 * cm], ["onde", "melhoria"]
            )
        )
    else:
        story.append(P("Nenhuma sugestão.", "p"))

    # ---------------------------------------------------------------- referências
    if report.references:
        story.append(PageBreak())
        story.append(P("Referências verificadas", "h1"))
        story.append(
            P(
                "Para cada obra citada: a situação da busca nas bases abertas, os dados "
                "da obra encontrada e, para cada trecho do artigo que a cita, se o resumo "
                "da fonte sustenta, contradiz ou não permite afirmar o que foi atribuído "
                "a ela.",
                "small",
            )
        )
        for ref in report.references:
            block: list[Any] = []
            status = ref.get("status", "")
            color = {
                "confirmada": "#2e7d32",
                "divergente": "#a15c00",
                "não encontrada": "#b3261e",
            }.get(status, "#666666")
            block.append(
                P(
                    f'{t(ref.get("key"))} — <font color="{color}">{t(status)}</font>'
                    + t(f"  ({ref.get('bib_location', '')})"),
                    "h2",
                )
            )
            if ref.get("title"):
                found = t(ref.get("title"))
                meta_parts = [
                    ", ".join(ref.get("authors", [])[:6]),
                    ref.get("year"),
                    ref.get("venue"),
                    ref.get("source"),
                ]
                found += "<br/>" + t(" · ".join(str(x) for x in meta_parts if x))
                if ref.get("url"):
                    found += f'<br/><font color="#1f5fa8">{t(ref["url"])}</font>'
                block.append(P("<b>Obra encontrada:</b> " + found, "cell"))
            for d in ref.get("divergences", []):
                block.append(P(f'<font color="#a15c00">divergência: {t(d)}</font>', "cell"))
            if ref.get("abstract"):
                ab = ref["abstract"]
                ab = ab if len(ab) <= 900 else ab[:899] + "…"
                block.append(P("<b>Resumo da fonte:</b> " + t(ab), "small"))
            uses = ref.get("uses", [])
            if uses:
                rows = []
                for u in uses:
                    v = u.get("verdict", "")
                    vc = VERDICT_COLOR.get(v, "#666666")
                    verdict = f'<font color="{vc}"><b>{t(v)}</b></font>'
                    if u.get("score") is not None:
                        verdict += t(f" ({u['score']:.0%})")
                    ev = t(u.get("evidence", "")) if u.get("evidence") else "—"
                    rows.append(
                        [
                            P(t(u.get("location", ""))),
                            P(t(u.get("claim", ""))),
                            P(verdict),
                            P(ev, "cell"),
                        ]
                    )
                block.append(Spacer(1, 3))
                block.append(
                    table(
                        rows,
                        [3.2 * cm, 5.6 * cm, 2.1 * cm, W - 10.9 * cm],
                        ["onde", "afirmação no artigo", "fonte", "trecho da fonte"],
                    )
                )
            elif ref.get("note"):
                block.append(P(t(ref["note"]), "small"))
            block.append(Spacer(1, 6))
            story.append(KeepTogether(block[:3]))
            story.extend(block[3:])

    # ---------------------------------------------------------------- métricas
    if report.metrics:
        story.append(PageBreak())
        story.append(P("Métricas", "h1"))
        for g in report.metrics:
            story.append(P(t(g.title), "h2"))
            if g.metrics:
                rows = []
                for mt in g.metrics:
                    val = f"{mt.value:.2f}" if isinstance(mt.value, float) else str(mt.value)
                    score = f"{mt.score:.1f}" if mt.score is not None else "—"
                    rows.append(
                        [
                            P(t(mt.name)),
                            P(t(val)),
                            P(score),
                            P(t(mt.reference)),
                            P(t(mt.explanation)),
                        ]
                    )
                story.append(
                    table(
                        rows,
                        [4 * cm, 2.6 * cm, 1.1 * cm, 3 * cm, W - 10.7 * cm],
                        ["métrica", "valor", "nota", "referência", "explicação"],
                    )
                )
            for n in g.notes:
                story.append(P(t(n), "small"))

    # ---------------------------------------------------------------- todos os achados
    story.append(PageBreak())
    story.append(P("Todos os achados, por arquivo", "h1"))
    by_file: dict[str, list[Finding]] = {}
    for f in report.findings:
        by_file.setdefault(f.location.file.as_posix() if f.location else "(projeto)", []).append(f)
    for file in sorted(by_file, key=lambda k: (k != "(projeto)", k)):
        items = sorted(
            by_file[file], key=lambda f: (f.severity.rank, f.location.line if f.location else 0)
        )
        story.append(P(t(file), "h2"))
        rows = []
        for f in items:
            line = str(f.location.line) if f.location else ""
            msg = f"<b>{t(f.code)}</b> — {t(f.message)}"
            if f.suggestion:
                msg += f'<br/><font color="#2e7d32">→ {t(f.suggestion)}</font>'
            rows.append([P(line), P(sev(f.severity)), P(msg)])
        story.append(table(rows, [1.2 * cm, 1.6 * cm, W - 2.8 * cm], ["linha", "sev.", "achado"]))

    # ---------------------------------------------------------------- limitações
    story.append(P("Limitações", "h1"))
    for lim in report.limitations:
        story.append(P("• " + t(lim), "p"))
        story.append(Spacer(1, 2))

    def footer(canvas: Any, doc: Any) -> None:
        canvas.saveState()
        canvas.setFont(font, 7)
        canvas.setFillColor(colors.HexColor("#777777"))
        canvas.drawString(1.7 * cm, 1.0 * cm, f"errei {m.get('version')} — {m.get('date')}")
        canvas.drawRightString(A4[0] - 1.7 * cm, 1.0 * cm, f"página {doc.page}")
        canvas.restoreState()

    path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=1.7 * cm,
        rightMargin=1.7 * cm,
        topMargin=1.6 * cm,
        bottomMargin=1.6 * cm,
        title="Relatório do errei",
        author="errei",
        subject=str(m.get("root")),
    )
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
