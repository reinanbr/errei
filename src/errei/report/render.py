"""Renderizadores: terminal (rich), Markdown e JSON."""

from __future__ import annotations

import io
import json
import os
import sys
from collections import defaultdict
from typing import Any, TextIO

from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from errei.model import Finding, Severity
from errei.report.build import Report
from errei.report.literatura import bloco, is_lit

JSON_SCHEMA_VERSION = 1

SEV_STYLE = {
    Severity.ERRO: "bold red",
    Severity.AVISO: "yellow",
    Severity.SUGESTAO: "cyan",
    Severity.INFO: "dim",
}
SEV_LABEL = {
    Severity.ERRO: "erro",
    Severity.AVISO: "aviso",
    Severity.SUGESTAO: "sugestão",
    Severity.INFO: "info",
}


def _group_by_file(findings: list[Finding]) -> dict[str, list[Finding]]:
    groups: dict[str, list[Finding]] = defaultdict(list)
    for f in findings:
        groups[f.location.file.as_posix() if f.location else "(projeto)"].append(f)
    for items in groups.values():
        items.sort(
            key=lambda f: (
                f.severity.rank,
                f.location.line if f.location else 0,
                (f.location.column or 0) if f.location else 0,
            )
        )
    order = sorted(groups, key=lambda k: (k != "(projeto)", k))
    return {k: groups[k] for k in order}


def _conf(f: Finding) -> str:
    return f" (confiança {f.confidence:.0%})" if f.confidence is not None else ""


# ------------------------------------------------------------------ JSON
def to_json(report: Report) -> str:
    data: dict[str, Any] = {
        "schema": JSON_SCHEMA_VERSION,
        "meta": report.meta,
        "summary": {
            "by_severity": {s.value: n for s, n in report.by_severity().items()},
            "by_checker": {
                c: {s.value: n for s, n in counts.items()}
                for c, counts in report.by_checker().items()
            },
            "total": len(report.findings),
            "suppressed": report.suppressed,
        },
        "findings": [
            {**f.to_dict(), "bloco": "\n".join(bloco(f))} if is_lit(f) else f.to_dict()
            for f in report.findings
        ],
        "metrics": [
            {
                "checker": g.checker,
                "title": g.title,
                "notes": g.notes,
                "metrics": [
                    {
                        "name": m.name,
                        "value": m.value,
                        "score": m.score,
                        "reference": m.reference,
                        "explanation": m.explanation,
                    }
                    for m in g.metrics
                ],
            }
            for g in report.metrics
        ],
        "references": report.references,
        "limitations": report.limitations,
    }
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


# ------------------------------------------------------------------ Markdown
def _md_escape(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ")


def to_markdown(report: Report) -> str:
    m = report.meta
    out: list[str] = []
    out.append("# Relatório do errei\n")
    out.append(f"- **Versão:** errei {m.get('version')}")
    out.append(f"- **Data:** {m.get('date')}")
    out.append(f"- **Projeto:** `{m.get('root')}` (principal: `{m.get('main')}`)")
    out.append(f"- **Hash do projeto (sha256):** `{m.get('project_hash')}`")
    out.append(f"- **Online:** {'sim' if m.get('online') else 'não'}")
    out.append(f"- **Verificadores:** {', '.join(m.get('checkers', []))}")
    if m.get("flags"):
        flags = ", ".join(f"`{k}={v}`" for k, v in m["flags"].items() if v not in (None, "", []))
        out.append(f"- **Flags:** {flags or '—'}")
    if m.get("qualis_csv"):
        out.append(
            f"- **CSV Qualis:** `{m['qualis_csv']}` (data de referência: "
            f"{m.get('qualis_data') or 'não informada'})"
        )
    out.append("")
    out.append("## Resumo\n")
    sev = report.by_severity()
    out.append("| erro | aviso | sugestão | info | suprimidos |")
    out.append("|---:|---:|---:|---:|---:|")
    out.append(
        f"| {sev[Severity.ERRO]} | {sev[Severity.AVISO]} | {sev[Severity.SUGESTAO]} | "
        f"{sev[Severity.INFO]} | {report.suppressed} |\n"
    )
    out.append("| verificador | erro | aviso | sugestão | info |")
    out.append("|---|---:|---:|---:|---:|")
    for c, counts in report.by_checker().items():
        out.append(f"| {c} | " + " | ".join(str(counts[s]) for s in Severity) + " |")
    out.append("")
    from errei.report import qualidade

    q = qualidade.get(report)
    if q:
        out += qualidade.markdown(q)

    for g in report.metrics:
        out.append(f"## {g.title}\n")
        if g.metrics:
            out.append("| métrica | valor | nota (0–10) | referência | explicação |")
            out.append("|---|---|---:|---|---|")
            for mt in g.metrics:
                val = f"{mt.value:.2f}" if isinstance(mt.value, float) else str(mt.value)
                score = f"{mt.score:.1f}" if mt.score is not None else "—"
                out.append(
                    f"| {_md_escape(mt.name)} | {_md_escape(val)} | {score} | "
                    f"{_md_escape(mt.reference)} | {_md_escape(mt.explanation)} |"
                )
        for n in g.notes:
            out.append(f"\n> {n}")
        out.append("")

    if report.references:
        out.append("## Referências verificadas\n")
        for ref in report.references:
            out.append(
                f"### `{ref.get('key')}` — {ref.get('status')} ({ref.get('bib_location')})\n"
            )
            if ref.get("title"):
                parts = [", ".join(ref.get("authors", [])[:6]), ref.get("year"), ref.get("venue")]
                out.append(
                    f"- obra encontrada: **{_md_escape(str(ref['title']))}** — "
                    + _md_escape(" · ".join(str(x) for x in parts if x))
                    + (f" <{ref['url']}>" if ref.get("url") else "")
                )
            for d in ref.get("divergences", []):
                out.append(f"- divergência: {_md_escape(str(d))}")
            if ref.get("note"):
                out.append(f"- {ref['note']}")
            if ref.get("uses"):
                out.append("\n| onde | afirmação no artigo | fonte | trecho da fonte |")
                out.append("|---|---|---|---|")
                for u in ref["uses"]:
                    score = f" ({u['score']:.0%})" if u.get("score") is not None else ""
                    out.append(
                        f"| {u.get('location', '')} | {_md_escape(u.get('claim', ''))} | "
                        f"{u.get('verdict', '')}{score} | "
                        f"{_md_escape(u.get('evidence', '') or '—')} |"
                    )
            out.append("")
    out.append("## Achados\n")
    if not report.findings:
        out.append("Nenhum achado.\n")
    for file, items in _group_by_file(report.findings).items():
        out.append(f"### `{file}`\n")
        for f in items:
            if is_lit(f):
                out.append("\n```text")
                out += [ln.replace("```", "ʼʼʼ") for ln in bloco(f)]
                out.append("```\n")
                continue
            loc = ""
            if f.location:
                loc = f"L{f.location.line}"
                if f.location.column:
                    loc += f":{f.location.column}"
            head = f"- **{SEV_LABEL[f.severity]}** `{f.code}` {loc} — {f.message}{_conf(f)}"
            if f.manual_review:
                head += " _(revisar manualmente)_"
            out.append(head)
            if f.excerpt:
                out.append(f"  - trecho: `{f.excerpt.replace('`', 'ʼ')}`")
            if f.suggestion:
                out.append(f"  - sugestão: {f.suggestion}")
            for ev in f.evidence:
                out.append(f"  - motivo: {ev}")
            for link in f.links:
                out.append(f"  - link: <{link}>")
        out.append("")
    out.append("## Limitações\n")
    for lim in report.limitations:
        out.append(f"- {lim}")
    out.append("")
    out += base_markdown(report.meta)
    return "\n".join(out)


def base_markdown(meta: dict[str, Any]) -> list[str]:
    from errei.report.base import base_lines

    base = meta.get("base")
    if not base:
        return []
    out = ["---", "", "## Base do relatório", ""]
    for k, v in base_lines(base):
        out.append(f"- **{k}:** {v}")
    out.append("")
    return out


# ------------------------------------------------------------------ terminal
def make_console(file: TextIO | None = None, *, force_color: bool | None = None) -> Console:
    stream = file or sys.stdout
    no_color = bool(os.environ.get("NO_COLOR"))
    is_tty = hasattr(stream, "isatty") and stream.isatty()
    return Console(
        file=stream,
        no_color=no_color or (force_color is False),
        force_terminal=force_color if force_color is not None else None,
        highlight=False,
        width=None if is_tty else 120,
    )


def _highlight_line(f: Finding) -> Text:
    line = Text()
    where = "(projeto)"
    if f.location:
        where = f"{f.location.file.as_posix()}:{f.location.line}"
    line.append(f"  {where:<34} ", style="bold")
    line.append(f"{SEV_LABEL[f.severity]:<8} ", style=SEV_STYLE[f.severity])
    line.append(f.message + _conf(f))
    if f.suggestion:
        line.append(f"\n  {'':<34} → {f.suggestion}", style="green")
    return line


def render_highlights(report: Report, console: Console, n: int = 12) -> None:
    from errei.report.highlights import improvements, top_problems

    probs = top_problems(report, n)
    console.rule(Text("Principais problemas (onde corrigir)", style="bold"), align="left")
    if not probs:
        console.print("  nenhum erro ou aviso")
    for f in probs:
        console.print(_highlight_line(f))
    melh = improvements(report, max(6, n // 2))
    console.rule(Text("Possíveis melhorias", style="bold"), align="left")
    if not melh:
        console.print("  nenhuma sugestão")
    for f in melh:
        console.print(_highlight_line(f))
    refs = report.references
    if refs:
        console.rule(Text("Citações verificadas", style="bold"), align="left")
        for ref in refs:
            uses = ref.get("uses", [])
            verdicts: dict[str, int] = {}
            for u in uses:
                verdicts[u.get("verdict", "?")] = verdicts.get(u.get("verdict", "?"), 0) + 1
            vtxt = ", ".join(f"{k}: {v}" for k, v in verdicts.items()) or ref.get("note", "")
            style = {"confirmada": "green", "divergente": "yellow", "não encontrada": "red"}.get(
                ref.get("status", ""), "dim"
            )
            line = Text(f"  {ref.get('key', ''):<20} ")
            line.append(f"{ref.get('status', ''):<15}", style=style)
            line.append(f" {vtxt}")
            console.print(line)
    console.print()


def render_term(
    report: Report, console: Console, *, quiet: bool = False, summary_only: bool = False
) -> None:
    m = report.meta
    sev = report.by_severity()
    header = Text()
    header.append(f"errei {m.get('version')}  ", style="bold")
    header.append(f"{m.get('root')}  (principal: {m.get('main')})\n")
    header.append(f"{sev[Severity.ERRO]} erro(s)", style=SEV_STYLE[Severity.ERRO])
    header.append(" · ")
    header.append(f"{sev[Severity.AVISO]} aviso(s)", style=SEV_STYLE[Severity.AVISO])
    header.append(" · ")
    header.append(f"{sev[Severity.SUGESTAO]} sugestão(ões)", style=SEV_STYLE[Severity.SUGESTAO])
    header.append(" · ")
    header.append(f"{sev[Severity.INFO]} info", style=SEV_STYLE[Severity.INFO])
    if report.suppressed:
        header.append(f" · {report.suppressed} suprimido(s)", style="dim")
    header.append(f"\nonline: {'sim' if m.get('online') else 'não'}")
    console.print(Panel(header, title="Resumo", expand=False))
    _render_qualidade(report, console)

    table = Table(title="Por verificador", show_edge=False, pad_edge=False)
    table.add_column("verificador")
    for s in Severity:
        table.add_column(SEV_LABEL[s], justify="right", style=SEV_STYLE[s])
    for c, counts in report.by_checker().items():
        table.add_row(c, *(str(counts[s]) for s in Severity))
    console.print(table)
    console.print()
    render_highlights(report, console)
    if summary_only:
        console.print(Text("(use sem --resumo para ver todos os achados por arquivo)", style="dim"))
        _limitations(report, console)
        return

    for file, items in _group_by_file(report.findings).items():
        if quiet:
            items = [f for f in items if f.severity in (Severity.ERRO, Severity.AVISO)]
            if not items:
                continue
        console.rule(Text(file, style="bold"), align="left")
        for f in items:
            if is_lit(f):
                for i, ln in enumerate(bloco(f)):
                    console.print(Text(ln, style="" if i == 0 else "dim"), soft_wrap=True)
                console.print()
                continue
            line = Text()
            loc = ""
            if f.location:
                loc = f"{f.location.line}" + (f":{f.location.column}" if f.location.column else "")
            line.append(f"{loc:>8} ", style="dim")
            line.append(f"{SEV_LABEL[f.severity]:<8} ", style=SEV_STYLE[f.severity])
            line.append(f"{f.code:<20} ", style="magenta")
            line.append(f.message + _conf(f))
            if f.manual_review:
                line.append(" [revisar manualmente]", style="dim")
            console.print(line)
            if f.excerpt:
                console.print(Text(f"{'':>9}│ {f.excerpt}", style="dim"))
            if f.suggestion:
                console.print(Text(f"{'':>9}→ {f.suggestion}", style="green"))
            if not quiet:
                for ev in f.evidence:
                    console.print(Text(f"{'':>9}· {ev}", style="dim"))
                for link in f.links:
                    console.print(Text(f"{'':>9}🔗 {link}", style="blue"))
        console.print()

    for g in report.metrics:
        t = Table(title=g.title, show_lines=False, expand=False)
        t.add_column("métrica")
        t.add_column("valor", justify="right")
        t.add_column("nota", justify="right")
        t.add_column("referência", style="dim")
        if not quiet:
            t.add_column("explicação", style="dim", max_width=60)
        for mt in g.metrics:
            val = f"{mt.value:.2f}" if isinstance(mt.value, float) else str(mt.value)
            score = f"{mt.score:.1f}" if mt.score is not None else "—"
            row = [escape(mt.name), escape(val), score, escape(mt.reference)]
            if not quiet:
                row.append(escape(mt.explanation))
            t.add_row(*row)
        console.print(t)
        for n in g.notes:
            console.print(Text(f"  {n}", style="italic dim"))
        console.print()

    _limitations(report, console)


def _render_qualidade(report: Report, console: Console) -> None:
    from errei.report import qualidade

    q = qualidade.get(report)
    if not q:
        return
    body = Text()
    body.append(f"Nível atingido: {q['nome']}\n", style="bold")
    for n in q["niveis"]:
        style = "green" if n["atingido"] else "dim"
        mark = "✔" if n["atingido"] else "·"
        body.append(f"{mark} {n['nome']:<52} ", style=style)
        body.append(f"{qualidade.barra(n['pct'])} ", style=style)
        body.append(f"{n['cumpridas']}/{n['total']} ({n['pct']}%)\n", style=style)
    if q.get("proximo"):
        prox = next(n for n in q["niveis"] if n["nivel"] == q["proximo"])
        faltam = q["faltam_proximo"]
        body.append(f"Para chegar a {prox['nome']}, falta:\n", style="bold")
        for f in faltam[:8]:
            body.append(f"  • {f}\n")
        if len(faltam) > 8:
            body.append(f"  … e mais {len(faltam) - 8} (veja a lista de afazeres: --todo)\n")
    body.append(
        "referência por metas objetivas; não prevê aprovação nem aceite", style="italic dim"
    )
    console.print(Panel(body, title="Nível de qualidade", expand=False))
    console.print()


def _limitations(report: Report, console: Console) -> None:
    lim = Text()
    for item in report.limitations:
        lim.append(f"• {item}\n")
    console.print(Panel(lim, title="Limitações", border_style="dim"))
    base = report.meta.get("base")
    if base:
        from errei.report.base import footer_text

        console.print(Text(f"Base: {footer_text(base)}", style="dim"))


def to_term_string(report: Report, *, color: bool = False) -> str:
    buf = io.StringIO()
    render_term(report, make_console(buf, force_color=color))
    return buf.getvalue()
