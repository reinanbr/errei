"""Verificador ``periodico``: Qualis do periódico-alvo e índice de prontidão.

Qualis é do PERIÓDICO, não do artigo. O estrato vem só do CSV fornecido. O
índice de prontidão (0–100) resume sinais objetivos do manuscrito e não prevê
aceitação nem estrato.
"""

from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path
from statistics import median
from typing import TYPE_CHECKING

from errei.bib.fields import valid_doi, year_of
from errei.bib.parser import plain
from errei.checkers.base import BaseChecker, RunContext
from errei.checkers.escrita import sections_of
from errei.config import ConfigError
from errei.model import Finding, Metric, MetricGroup, Rule, Severity
from errei.model import Severity as S
from errei.qualis import QualisTable, parse_target
from errei.text.abstracts import find_abstracts
from errei.text.segment import word_count

if TYPE_CHECKING:
    from errei.project import Project

IMRAD = {
    "introdução": re.compile(r"introdu", re.I),
    "método": re.compile(r"m[eé]todo|metodologia|materiais|procedimento", re.I),
    "resultados": re.compile(r"resultado|análise|experimento|avalia", re.I),
    "discussão/conclusão": re.compile(r"discuss|conclus|considera[cç][oõ]es finais", re.I),
}
DISCLAIMER = (
    "o índice resume sinais objetivos do manuscrito; NÃO prevê aceitação nem estrato Qualis"
)


def _lin(value: float, zero: float, full: float) -> float:
    """0 em ``zero``, 1 em ``full`` (linear, saturado)."""
    if full == zero:
        return 1.0
    return max(0.0, min(1.0, (value - zero) / (full - zero)))


class PeriodicoChecker(BaseChecker):
    name = "periodico"
    title = "Periódico-alvo e prontidão"
    phase = 1  # roda depois dos demais e usa seus achados
    uses_network = True
    rules = (
        Rule(
            "PERIOD-QUALIS-001",
            S.INFO,
            "Estrato Qualis do periódico-alvo",
            "Estrato do PERIÓDICO informado, segundo o CSV da CAPES fornecido. Qualis não "
            "se aplica a artigos individuais e vem sendo reformulado pela CAPES; o CSV e "
            "sua data são a fonte da verdade.",
        ),
        Rule(
            "PERIOD-QUALIS-002",
            S.AVISO,
            "Periódico não encontrado no CSV Qualis",
            "O periódico-alvo não aparece no CSV (confira ISSN impresso/eletrônico, título e "
            "área).",
        ),
        Rule(
            "PERIOD-QUALIS-003",
            S.INFO,
            "Data do CSV Qualis não informada",
            "Sem --qualis-data, a data de referência é a de modificação do arquivo, que pode "
            "não refletir a edição do Qualis.",
        ),
        Rule(
            "PERIOD-QUALIS-004",
            S.INFO,
            "Periódico-alvo não informado",
            "Use --periodico 'ISSN 1234-5678' (ou o título) com --qualis-csv para consultar o "
            "estrato.",
        ),
        Rule(
            "PERIOD-REFS-001",
            S.INFO,
            "Referências em periódicos do CSV Qualis",
            "Distribuição de estratos dos periódicos citados no .bib que constam do CSV "
            "(sinal da base de literatura, não da qualidade do artigo).",
            heuristic=True,
        ),
        Rule(
            "PERIOD-OA-001",
            S.INFO,
            "Métricas abertas do periódico (OpenAlex)",
            "Indicadores públicos do periódico no OpenAlex (h-index, média de citações em 2 "
            "anos, número de trabalhos, acesso aberto/DOAJ). Só com --online.",
        ),
        Rule(
            "PERIOD-READY-001",
            S.INFO,
            "Índice de prontidão para submissão",
            "Índice 0–100 calculado a partir de sinais objetivos: estrutura IMRaD, resumo/"
            "abstract/palavras-chave bilíngues, qualidade das referências (DOI, idade, % de "
            "periódicos), tamanho, normas e escrita. Cada componente é exibido. NÃO prevê "
            "aceitação nem estrato.",
            heuristic=True,
        ),
    )

    def run(self, project: Project, ctx: RunContext) -> list[Finding]:
        out: list[Finding] = []
        cfg = ctx.config.section("periodico")
        table: QualisTable | None = ctx.shared.get("qualis")
        if table is None and cfg.get("qualis_csv"):
            from errei.qualis import load_qualis

            try:
                table = load_qualis(Path(str(cfg["qualis_csv"])), str(cfg.get("qualis_data") or ""))
            except ConfigError as exc:
                out.append(self.finding("CORE-DEP-001", str(exc)))
        target = str(cfg.get("periodico") or "").strip()
        area = str(cfg.get("area") or "").strip()
        issn = ""
        if table is not None:
            if table.date_source != "informada":
                out.append(
                    self.finding(
                        "PERIOD-QUALIS-003",
                        f"CSV Qualis sem data informada; usando {table.ref_date} "
                        f"({table.date_source}). Use --qualis-data.",
                    )
                )
            out += self._qualis(table, target, area)
            out += self._refs_qualis(project, table, area)
        if target:
            kind, value = parse_target(target)
            issn = value if kind == "issn" else ""
        elif table is not None:
            out.append(
                self.finding("PERIOD-QUALIS-004", "periódico-alvo não informado (--periodico)")
            )
        if ctx.http is not None and target:
            out += self._openalex(ctx, target, issn)
        g, total = self._readiness(project, ctx)
        ctx.add_metrics(g)
        out.append(
            self.finding(
                "PERIOD-READY-001",
                f"índice de prontidão: {total:.0f}/100 — {DISCLAIMER}",
                evidence=tuple(f"{m.name}: {m.value}" for m in g.metrics[:-1]),
            )
        )
        return out

    # ------------------------------------------------------------ Qualis
    def _qualis(self, table: QualisTable, target: str, area: str) -> list[Finding]:
        if not target:
            return []
        kind, value = parse_target(target)
        rows = table.by_issn(value) if kind == "issn" else table.by_title(value)
        if area:
            from errei.qualis import norm_title

            rows_area = [r for r in rows if norm_title(r.area) == norm_title(area)]
            if rows and not rows_area:
                return [
                    self.finding(
                        "PERIOD-QUALIS-002",
                        f"'{target}' está no CSV, mas não na área '{area}' "
                        f"(áreas: {', '.join(sorted({r.area for r in rows}))})",
                    )
                ]
            rows = rows_area
        if not rows:
            return [
                self.finding(
                    "PERIOD-QUALIS-002",
                    f"periódico '{target}' não encontrado no CSV "
                    f"{table.path.name} ({len(table.rows)} linhas)",
                )
            ]
        out = []
        for r in sorted(rows, key=lambda r: (r.area, r.estrato)):
            out.append(
                self.finding(
                    "PERIOD-QUALIS-001",
                    f"periódico '{r.title}' (ISSN {r.issn[:4]}-{r.issn[4:]}): estrato {r.estrato} "
                    f"na área '{r.area or '—'}' — CSV de referência {table.ref_date}. O estrato é "
                    "do periódico, não do artigo.",
                    evidence=(
                        f"fonte: {table.path.name} ({table.date_source})",
                        "a CAPES vem reformulando o Qualis; confira a edição vigente",
                    ),
                )
            )
        return out

    def _refs_qualis(self, project: Project, table: QualisTable, area: str) -> list[Finding]:
        counts: dict[str, int] = {}
        total = 0
        for e in project.bib_entries:
            journal = plain(e.get("journal") or e.get("journaltitle"))
            if not journal:
                continue
            total += 1
            rows = table.by_issn(e.get("issn")) if e.has("issn") else []
            rows = rows or table.by_title(journal, cutoff=0.95)
            if area:
                from errei.qualis import norm_title

                rows = [r for r in rows if norm_title(r.area) == norm_title(area)] or rows
            if rows:
                best = min(r.estrato for r in rows)
                counts[best] = counts.get(best, 0) + 1
        if not total:
            return []
        found = sum(counts.values())
        dist = ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())) or "nenhum"
        return [
            self.finding(
                "PERIOD-REFS-001",
                f"{found} de {total} referências de periódico do .bib estão "
                f"em periódicos do CSV ({dist})",
            )
        ]

    # ------------------------------------------------------------ OpenAlex
    def _openalex(self, ctx: RunContext, target: str, issn: str) -> list[Finding]:
        from errei.net import sources as srcs

        src = (
            srcs.openalex_source_by_issn(ctx.http, f"{issn[:4]}-{issn[4:]}")
            if issn
            else srcs.openalex_source_search(ctx.http, target)
        )
        if not src:
            return []
        stats = src.get("summary_stats") or {}
        parts = [
            f"h-index {stats.get('h_index', '—')}",
            f"média de citações (2 anos) {stats.get('2yr_mean_citedness', 0):.2f}"
            if isinstance(stats.get("2yr_mean_citedness"), int | float)
            else "",
            f"{src.get('works_count', '—')} trabalhos",
            "acesso aberto" if src.get("is_oa") else "",
            "no DOAJ" if src.get("is_in_doaj") else "",
        ]
        return [
            self.finding(
                "PERIOD-OA-001",
                f"OpenAlex: '{src.get('display_name', target)}' — "
                + ", ".join(p for p in parts if p),
                links=(str(src.get("id")),) if src.get("id") else (),
            )
        ]

    # ------------------------------------------------------------ prontidão
    def _readiness(self, project: Project, ctx: RunContext) -> tuple[MetricGroup, float]:
        cfg = ctx.config.section("periodico")
        g = MetricGroup(self.name, "Índice de prontidão para submissão (0–100)")
        prior = ctx.prior_findings
        ran = set(ctx.shared.get("checkers_ran", []))
        comps: list[tuple[str, float, float, str]] = []  # nome, pontos, máximo, explicação

        secs = sections_of(project)
        titles = [s.title for s in secs if s.heading is not None]
        present = [k for k, rx in IMRAD.items() if any(rx.search(t) for t in titles)]
        comps.append(
            (
                "Estrutura IMRaD",
                15 * len(present) / 4,
                15,
                f"seções detectadas: {', '.join(present) or 'nenhuma'}",
            )
        )

        blocks = find_abstracts(project)
        pt = next((b for b in blocks if b.lang == "pt" and b.paragraphs), None)
        fo = next((b for b in blocks if b.lang != "pt" and b.paragraphs), None)
        pts = 0.0
        why = []
        if pt:
            pts += 4
            n = word_count(pt.text)
            lo = int(ctx.config.get("abnt", "resumo_min", 150))
            hi = int(ctx.config.get("abnt", "resumo_max", 250))
            if lo <= n <= hi:
                pts += 3
            why.append(f"resumo {n} palavras")
            if pt.keywords:
                pts += 2
                why.append("palavras-chave")
        if fo:
            pts += 4
            why.append("abstract")
            if fo.keywords:
                pts += 2
                why.append("keywords")
        comps.append(("Resumo/abstract/palavras-chave", pts, 15, ", ".join(why) or "ausentes"))

        entries = project.bib_entries
        cited = {u.key for u in project.cite_uses()}
        used = [e for e in entries if e.key in cited] or entries
        rq = 0.0
        why = []
        if used:
            doi_cands = [e for e in used if e.type in ("article", "inproceedings", "incollection")]
            if doi_cands:
                ratio = sum(1 for e in doi_cands if e.has("doi") and valid_doi(e.get("doi"))) / len(
                    doi_cands
                )
                rq += 10 * ratio
                why.append(f"{ratio:.0%} com DOI")
            years = [y for y in (year_of(e.get("year") or e.get("date")) for e in used) if y]
            if years:
                age = _dt.date.today().year - median(years)
                rq += 5 * (1 - _lin(age, 10, 25))
                why.append(f"idade mediana {age:.0f} anos")
            jratio = sum(1 for e in used if e.type == "article") / len(used)
            rq += 5 * _lin(jratio, 0, 0.5)
            why.append(f"{jratio:.0%} artigos de periódico")
            ref_err = sum(1 for f in prior if f.checker == "refs" and f.severity is Severity.ERRO)
            rq += max(0.0, 5 - ref_err)
            why.append(f"{ref_err} erro(s) de referência")
        comps.append(("Qualidade das referências", rq, 25, ", ".join(why) or "sem .bib"))

        words = sum(word_count(p.text) for p in project.paragraphs(("body", "item", "quote")))
        wmin = int(cfg.get("palavras_min", 3000))
        wmax = int(cfg.get("palavras_max", 9000))
        size = 10 * (
            _lin(words, wmin / 3, wmin) if words < wmin else 1 - _lin(words, wmax, wmax * 1.7)
        )
        comps.append(
            (
                "Tamanho",
                size,
                10,
                f"{words} palavras no corpo (faixa {wmin}–{wmax}, configurável em [periodico])",
            )
        )

        ab_e = sum(1 for f in prior if f.checker == "abnt" and f.severity is Severity.ERRO)
        ab_w = sum(1 for f in prior if f.checker == "abnt" and f.severity is Severity.AVISO)
        normas = max(0.0, 15 - 3 * ab_e - 1 * ab_w)
        note = "" if not ran or "abnt" in ran else " (verificador abnt não rodou)"
        comps.append(("Normas ABNT", normas, 15, f"{ab_e} erro(s), {ab_w} aviso(s){note}"))

        wr_e = sum(
            1
            for f in prior
            if f.checker in ("ptbr", "escrita", "latex") and f.severity is Severity.ERRO
        )
        wr_w = sum(
            1
            for f in prior
            if f.checker in ("ptbr", "escrita", "latex") and f.severity is Severity.AVISO
        )
        dens = (3 * wr_e + wr_w) / max(1, words) * 1000
        escrita = 20 * (1 - _lin(dens, 0, 15))
        comps.append(
            (
                "Escrita e LaTeX",
                escrita,
                20,
                f"{wr_e} erro(s), {wr_w} aviso(s); densidade ponderada {dens:.1f}/1000 palavras",
            )
        )

        total = sum(c[1] for c in comps)
        for name, value, mx, expl in comps:
            g.metrics.append(
                Metric(
                    name, f"{value:.1f}/{mx:.0f}", round(10 * value / mx, 1), f"máx. {mx:.0f}", expl
                )
            )
        g.metrics.append(
            Metric("TOTAL", f"{total:.0f}/100", round(total / 10, 1), "0–100", DISCLAIMER)
        )
        g.notes.append(
            DISCLAIMER[0].upper() + DISCLAIMER[1:] + ". Pesos: IMRaD 15, resumos 15, "
            "referências 25, tamanho 10, normas 15, escrita 20."
        )
        return g, total
