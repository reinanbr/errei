"""Verificador ``escrita``: métricas de qualidade textual explicadas, por dimensão."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from statistics import mean
from typing import TYPE_CHECKING

from errei.checkers.base import BaseChecker, RunContext
from errei.checkers.ptbr import PASSIVE
from errei.latex.extract import Paragraph
from errei.model import Finding, Metric, MetricGroup, Rule
from errei.model import Severity as S
from errei.text.abstracts import find_abstracts
from errei.text.metrics import (
    band_score,
    connectives,
    cv,
    flesch_band,
    flesch_pt,
    mattr,
    norm_term,
)
from errei.text.segment import alpha_words, sentences, word_count

if TYPE_CHECKING:
    from errei.project import Project

SIGLA_RE = re.compile(r"\b([A-Z][A-Za-z0-9]{0,1}[A-Z0-9][A-Za-z0-9]{0,6}?)(s?)\b")
KNOWN_SIGLAS = {
    "ABNT",
    "NBR",
    "PDF",
    "URL",
    "DOI",
    "ISBN",
    "ISSN",
    "CAPES",
    "CNPQ",
    "CNPq",
    "FAPESP",
    "HTML",
    "HTTP",
    "HTTPS",
    "XML",
    "JSON",
    "CSV",
    "SQL",
    "API",
    "CPU",
    "GPU",
    "RAM",
    "USB",
    "EUA",
    "ONU",
    "OMS",
    "IBGE",
    "MEC",
    "SUS",
    "UFRJ",
    "USP",
    "UNICAMP",
    "UFMG",
    "BR",
    "PIB",
    "TCC",
    "OK",
    "TV",
    "PC",
    "II",
    "III",
    "IV",
    "VI",
    "VII",
    "VIII",
    "IX",
    "XI",
    "XII",
    "XIII",
    "XIV",
    "XV",
    "XVI",
    "XVII",
    "XVIII",
    "XIX",
    "XX",
    "XXI",
    "LATEX",
    "TEX",
    "UTF",
    "ASCII",
}
OBJ_RE = re.compile(
    r"\b(o objetivo (?:deste|do presente|geral|desta)|objetiva-se|tem (?:como|por) objetivo|"
    r"este (?:trabalho|artigo|estudo) (?:propõe|apresenta|investiga|analisa|busca|descreve|"
    r"avalia|discute)|o presente (?:trabalho|artigo|estudo)|busca-se|propõe-se|pretende-se)",
    re.IGNORECASE,
)
QUESTION_RE = re.compile(
    r"(pergunta de pesquisa|questão de pesquisa|questão norteadora|"
    r"problema de pesquisa|\?\s)",
    re.IGNORECASE,
)
HYPO_RE = re.compile(r"\bhipótese", re.IGNORECASE)
METHOD_RE = re.compile(r"\b(metodologia|método|materiais e métodos|procedimentos)\b", re.IGNORECASE)
RESULT_RE = re.compile(r"\b(resultados?|discussão)\b", re.IGNORECASE)
CONCL_RE = re.compile(r"\b(conclus|considerações finais|conclui-se)", re.IGNORECASE)
REVIEW_TITLES = re.compile(
    r"introdu|trabalhos relacionados|referencial|revisão|fundamenta|"
    r"estado da arte|related work",
    re.IGNORECASE,
)
NUM_RE = re.compile(r"\b\d+(?:[.,]\d+)?%?")


@dataclass(slots=True)
class SectionStats:
    title: str
    heading: Paragraph | None
    paragraphs: list[Paragraph] = field(default_factory=list)

    @property
    def words(self) -> int:
        return sum(word_count(p.text) for p in self.paragraphs)

    @property
    def cites(self) -> int:
        n = 0
        for p in self.paragraphs:
            n += sum(1 for c in p.clean.cites if p.start <= c.start < p.end)
        return n


def sections_of(project: Project) -> list[SectionStats]:
    out: list[SectionStats] = []
    current = SectionStats("(antes da 1ª seção)", None)
    for p in project.paragraphs(("heading", "body", "item", "quote")):
        if p.kind == "heading":
            sec = next((s for s in p.clean.sections if p.start <= s.clean_start <= p.end), None)
            if sec is not None and sec.level <= 1:
                if current.paragraphs or current.heading is not None:
                    out.append(current)
                current = SectionStats(sec.title, p)
            continue
        current.paragraphs.append(p)
    if current.paragraphs or current.heading is not None:
        out.append(current)
    return [s for s in out if s.heading is not None or s.words > 0]


class EscritaChecker(BaseChecker):
    name = "escrita"
    title = "Qualidade textual"
    rules = (
        Rule(
            "ESCRITA-SIGLA-001",
            S.AVISO,
            "Sigla usada antes de ser definida",
            "Na primeira ocorrência, a sigla deve vir após a forma completa: 'processamento "
            "de linguagem natural (PLN)'.",
            "ABNT NBR 6022:2018 / NBR 14724:2011, 5.6",
            heuristic=True,
        ),
        Rule(
            "ESCRITA-SIGLA-002",
            S.SUGESTAO,
            "Sigla definida mais de uma vez",
            "A sigla é definida novamente depois da primeira definição.",
            heuristic=True,
        ),
        Rule(
            "ESCRITA-SIGLA-003",
            S.SUGESTAO,
            "Sigla definida e não usada",
            "Sigla definida mas nunca reutilizada; a definição pode ser dispensável.",
            heuristic=True,
        ),
        Rule(
            "ESCRITA-TERMO-001",
            S.SUGESTAO,
            "Termo com grafias diferentes",
            "O mesmo termo aparece com grafias diferentes (hífen, espaço, maiúsculas). Escolha "
            "uma e mantenha-a.",
            heuristic=True,
        ),
        Rule(
            "ESCRITA-ABS-001",
            S.AVISO,
            "Resumo e abstract inconsistentes",
            "Resumo e abstract devem ter o mesmo conteúdo: extensão muito diferente ou "
            "números presentes em só um deles indicam divergência.",
            heuristic=True,
        ),
        Rule(
            "ESCRITA-SEC-001",
            S.SUGESTAO,
            "Seções desbalanceadas",
            "Seção muito curta ou muito longa em relação às demais.",
            heuristic=True,
        ),
        Rule(
            "ESCRITA-OBJ-001",
            S.AVISO,
            "Objetivo não identificado",
            "Não foi encontrada uma formulação explícita do objetivo ('O objetivo deste "
            "trabalho é…', 'Este artigo propõe…') na introdução ou no resumo.",
            heuristic=True,
        ),
        Rule(
            "ESCRITA-CIT-001",
            S.SUGESTAO,
            "Seção de revisão sem citações",
            "Introdução/revisão com texto considerável e nenhuma citação.",
            heuristic=True,
        ),
    )

    def run(self, project: Project, ctx: RunContext) -> list[Finding]:
        out: list[Finding] = []
        body = [p for p in project.paragraphs(("body", "item", "quote")) if p.lang == "pt"]
        out += self._siglas(project, ctx)
        out += self._terms(body)
        out += self._abstract_consistency(project)
        secs = sections_of(project)
        out += self._sections(secs)
        detected = self._elements(project, secs)
        if not detected["objetivo"]:
            loc = secs[0].heading.location(0) if secs and secs[0].heading else None
            out.append(
                self.finding(
                    "ESCRITA-OBJ-001",
                    "objetivo do trabalho não identificado",
                    location=loc,
                    suggestion="explicite: 'O objetivo deste trabalho é…'",
                )
            )
        ctx.add_metrics(self._metrics(body, secs, detected))
        return out

    # ------------------------------------------------------------ siglas
    def _siglas(self, project: Project, ctx: RunContext) -> list[Finding]:
        out: list[Finding] = []
        known = KNOWN_SIGLAS | {str(s) for s in ctx.config.get("escrita", "siglas_conhecidas", [])}
        defined: dict[str, Paragraph] = {}
        first_use: dict[str, tuple[Paragraph, int, int]] = {}
        uses: dict[str, int] = defaultdict(int)
        reported: set[str] = set()
        for p in project.paragraphs(("body", "item", "quote", "caption")):
            if p.lang != "pt":
                continue
            masked = _mask_cites(p)
            defs_list: list[tuple[str, int]] = []
            for m in re.finditer(r"\(([A-Z][A-Za-z0-9]{1,9})\)", masked):
                defs_list.append((_singular(m.group(1)), m.start(1)))
            for m in re.finditer(r"\b([A-Z][A-Z0-9]{1,9})\s+\((?:[a-zà-ú][^)]{5,})\)", masked):
                defs_list.append((_singular(m.group(1)), m.start(1)))
            defs_list.sort(key=lambda d: d[1])
            defs_here: dict[str, int] = {}
            for sig, off in defs_list:
                defs_here.setdefault(sig, off)
            for m in SIGLA_RE.finditer(masked):
                sig = m.group(1)
                if sum(1 for c in sig if c.isupper()) < 2 or sig.upper() in known or sig in known:
                    continue
                if not any(c.isupper() for c in sig[1:]):
                    continue
                uses[sig] += 1
                d_off = defs_here.get(sig)
                if sig in defined:
                    continue
                if d_off is not None and m.start() >= d_off - 1:
                    continue  # é a própria definição (ou depois dela, no mesmo parágrafo)
                if sig not in first_use and sig not in reported:
                    first_use[sig] = (p, m.start(), m.end())
            for sig, off in defs_list:
                if sig in known:
                    continue
                if sig in defined:
                    out.append(
                        self.finding(
                            "ESCRITA-SIGLA-002",
                            f"sigla '{sig}' definida novamente (primeira em "
                            f"{defined[sig].location(0)})",
                            location=p.location(off, off + len(sig)),
                        )
                    )
                    continue
                defined[sig] = p
                if sig in first_use:
                    fp, s, e = first_use.pop(sig)
                    reported.add(sig)
                    out.append(
                        self.finding(
                            "ESCRITA-SIGLA-001",
                            f"sigla '{sig}' usada antes da definição (definida em "
                            f"{p.location(off)})",
                            location=fp.location(s, e),
                            excerpt=_ctx(fp.text, s, e),
                            suggestion=f"defina na primeira ocorrência: 'forma completa ({sig})'",
                        )
                    )
        for sig, (p, s, e) in first_use.items():
            if uses[sig] >= 2 and sig not in defined:
                out.append(
                    self.finding(
                        "ESCRITA-SIGLA-001",
                        f"sigla '{sig}' usada {uses[sig]}× e nunca definida",
                        location=p.location(s, e),
                        excerpt=_ctx(p.text, s, e),
                        suggestion=f"'forma completa ({sig})' na 1ª ocorrência",
                    )
                )
        for sig, p in defined.items():
            if uses[sig] <= 1:
                out.append(
                    self.finding(
                        "ESCRITA-SIGLA-003",
                        f"sigla '{sig}' definida e não reutilizada",
                        location=p.location(0),
                    )
                )
        ctx.share("siglas", {"definidas": len(defined), "indefinidas": len(first_use)})
        return out

    # ------------------------------------------------------------ termos
    def _terms(self, body: list[Paragraph]) -> list[Finding]:
        variants: dict[str, dict[str, tuple[Paragraph, int, int]]] = defaultdict(dict)
        for p in body:
            for m in re.finditer(r"\b[^\W\d_]{2,}(?:-[^\W\d_]{2,})+\b", p.text):
                variants[norm_term(m.group(0))].setdefault(
                    m.group(0).lower(), (p, m.start(), m.end())
                )
        if not variants:
            return []
        out: list[Finding] = []
        for p in body:
            for key in list(variants):
                parts = variants[key]
                hyph = next(iter(parts))
                pieces = hyph.split("-")
                for form in (" ".join(pieces), "".join(pieces)):
                    for m in re.finditer(r"\b" + re.escape(form) + r"\b", p.text, re.IGNORECASE):
                        parts.setdefault(m.group(0).lower(), (p, m.start(), m.end()))
        for _key, forms in variants.items():
            if len(forms) >= 2:
                names = sorted(forms)
                p, s, e = sorted(forms.values(), key=lambda v: v[0].first_line)[-1]
                out.append(
                    self.finding(
                        "ESCRITA-TERMO-001",
                        "grafias diferentes: " + " / ".join(f"'{n}'" for n in names),
                        location=p.location(s, e),
                        excerpt=_ctx(p.text, s, e),
                    )
                )
        return out

    # ------------------------------------------------------------ resumo × abstract
    def _abstract_consistency(self, project: Project) -> list[Finding]:
        blocks = find_abstracts(project)
        pt = next((b for b in blocks if b.lang == "pt" and b.paragraphs), None)
        fo = next((b for b in blocks if b.lang != "pt" and b.paragraphs), None)
        if pt is None or fo is None:
            return []
        out: list[Finding] = []
        n_pt, n_fo = word_count(pt.text), word_count(fo.text)
        ratio = n_fo / n_pt if n_pt else 0
        if not 0.6 <= ratio <= 1.5:
            out.append(
                self.finding(
                    "ESCRITA-ABS-001",
                    f"abstract com {n_fo} palavras × resumo com {n_pt} (razão {ratio:.2f})",
                    location=fo.paragraphs[0].location(0),
                )
            )
        nums_pt = {n.replace(",", ".") for n in NUM_RE.findall(pt.text)}
        nums_fo = {n.replace(",", ".") for n in NUM_RE.findall(fo.text)}
        diff = sorted(nums_pt ^ nums_fo)
        if diff:
            out.append(
                self.finding(
                    "ESCRITA-ABS-001",
                    "números presentes em só um de resumo/abstract: " + ", ".join(diff[:8]),
                    location=fo.paragraphs[0].location(0),
                )
            )
        return out

    # ------------------------------------------------------------ seções
    def _sections(self, secs: list[SectionStats]) -> list[Finding]:
        out: list[Finding] = []
        real = [s for s in secs if s.heading is not None]
        if len(real) >= 3:
            counts = [s.words for s in real]
            avg = mean(counts)
            total = sum(counts)
            for s in real:
                if s.words < 0.2 * avg:
                    out.append(
                        self.finding(
                            "ESCRITA-SEC-001",
                            f"seção '{s.title}' muito curta ({s.words} palavras; média {avg:.0f})",
                            location=s.heading.location(0),  # type: ignore[union-attr]
                        )
                    )
                elif len(real) >= 4 and s.words > 0.5 * total:
                    out.append(
                        self.finding(
                            "ESCRITA-SEC-001",
                            f"seção '{s.title}' concentra {s.words / total:.0%} do texto",
                            location=s.heading.location(0),  # type: ignore[union-attr]
                        )
                    )
        for s in real:
            if REVIEW_TITLES.search(s.title) and s.words >= 150 and s.cites == 0:
                out.append(
                    self.finding(
                        "ESCRITA-CIT-001",
                        f"seção '{s.title}' com {s.words} palavras e nenhuma citação",
                        location=s.heading.location(0),  # type: ignore[union-attr]
                    )
                )
        return out

    def _elements(self, project: Project, secs: list[SectionStats]) -> dict[str, bool]:
        abstracts = " ".join(b.text for b in find_abstracts(project) if b.lang == "pt")
        intro = " ".join(p.text for s in secs[:2] for p in s.paragraphs)
        everything = " ".join(p.text for p in project.paragraphs(("body", "item", "abstract")))
        titles = " ".join(s.title for s in secs)
        return {
            "objetivo": bool(OBJ_RE.search(abstracts + " " + intro)),
            "pergunta de pesquisa": bool(QUESTION_RE.search(intro + " " + abstracts)),
            "hipótese": bool(HYPO_RE.search(everything)),
            "método": bool(METHOD_RE.search(titles + " " + abstracts)),
            "resultados": bool(RESULT_RE.search(titles + " " + abstracts)),
            "conclusão": bool(CONCL_RE.search(titles)),
        }

    # ------------------------------------------------------------ métricas
    def _metrics(
        self, body: list[Paragraph], secs: list[SectionStats], detected: dict[str, bool]
    ) -> MetricGroup:
        g = MetricGroup(self.name, "Qualidade textual (escrita)")
        text = "\n\n".join(p.text for p in body if p.kind == "body")
        all_sents = [s for p in body if p.kind == "body" for s in sentences(p.text)]
        nwords = len(alpha_words(text))
        if nwords < 50:
            g.notes.append("texto curto demais para métricas confiáveis")
            return g
        fl = flesch_pt(text)
        if fl is not None:
            idx, asl, asw = fl
            g.metrics.append(
                Metric(
                    "Legibilidade (Flesch, Martins et al. 1996)",
                    round(idx, 1),
                    band_score(idx, 25, 60, 30),
                    "25–50 é típico de texto acadêmico; 50–75 'fácil'",
                    f"{flesch_band(idx)}; {asl:.1f} palavras/frase, {asw:.2f} sílabas/palavra "
                    "(silabação heurística)",
                )
            )
        sent_lens = [len(alpha_words(s.text)) for s in all_sents if alpha_words(s.text)]
        if sent_lens:
            avg = mean(sent_lens)
            g.metrics.append(
                Metric(
                    "Comprimento médio de frase",
                    round(avg, 1),
                    band_score(avg, 15, 25, 15),
                    "15–25 palavras",
                    f"{len(sent_lens)} frases; maior com {max(sent_lens)} palavras",
                )
            )
        para_lens = [word_count(p.text) for p in body if p.kind == "body"]
        if para_lens:
            avgp = mean(para_lens)
            g.metrics.append(
                Metric(
                    "Comprimento médio de parágrafo",
                    round(avgp, 1),
                    band_score(avgp, 50, 150, 100),
                    "50–150 palavras",
                    f"{len(para_lens)} parágrafos; "
                    f"{sum(1 for x in para_lens if x < 25)} com < 25 palavras",
                )
            )
        if all_sents:
            passive = sum(1 for s in all_sents if PASSIVE.search(s.text))
            ratio = passive / len(all_sents)
            g.metrics.append(
                Metric(
                    "Frases com voz passiva",
                    round(ratio * 100, 1),
                    band_score(ratio * 100, 0, 30, 40),
                    "até ~30%",
                    f"{passive} de {len(all_sents)} frases (passiva analítica)",
                )
            )
        m = mattr(text)
        if m is not None:
            g.metrics.append(
                Metric(
                    "Diversidade lexical (MATTR-100)",
                    round(m, 3),
                    band_score(m, 0.65, 0.85, 0.2),
                    "0,65–0,85",
                    "razão tipo/ocorrência média em janelas de 100 palavras; "
                    "valores baixos indicam vocabulário repetitivo",
                )
            )
        conn = connectives(text)
        per100 = len(conn) / nwords * 100
        top = ", ".join(
            f"{w} ({n})"
            for w, n in sorted(((w, conn.count(w)) for w in set(conn)), key=lambda x: -x[1])[:4]
        )
        g.metrics.append(
            Metric(
                "Conectivos (coesão) por 100 palavras",
                round(per100, 2),
                band_score(per100, 1.5, 5, 3),
                "1,5–5",
                f"mais usados: {top}" if top else "nenhum conectivo encontrado",
            )
        )
        real = [s for s in secs if s.heading is not None]
        if real:
            dens = [f"{s.title[:25]}: {s.cites / max(1, s.words) * 1000:.1f}" for s in real]
            g.metrics.append(
                Metric(
                    "Citações por 1000 palavras (por seção)",
                    "; ".join(dens),
                    None,
                    "introdução/revisão costumam ter mais",
                    "densidade de \\cite por seção",
                )
            )
            counts = [float(s.words) for s in real]
            c = cv(counts)
            g.metrics.append(
                Metric(
                    "Equilíbrio entre seções (CV)",
                    round(c, 2),
                    band_score(c, 0, 0.8, 0.8),
                    "≤ 0,8",
                    "coeficiente de variação do nº de palavras por seção: "
                    + ", ".join(f"{s.title[:20]} {s.words}" for s in real),
                )
            )
        found = [k for k, v in detected.items() if v]
        missing = [k for k, v in detected.items() if not v]
        g.metrics.append(
            Metric(
                "Elementos detectáveis",
                f"{len(found)}/{len(detected)}",
                round(10 * len(found) / len(detected), 1),
                "objetivo, pergunta, hipótese, método, resultados, conclusão",
                ("presentes: " + ", ".join(found) if found else "nenhum")
                + ("; ausentes: " + ", ".join(missing) if missing else ""),
            )
        )
        g.notes.append(
            "Cada dimensão tem nota própria (0–10) com faixa de referência; não há "
            "nota única. Faixas são orientações gerais, não regras de periódico."
        )
        return g


def _mask_cites(p: Paragraph) -> str:
    """Troca os placeholders de citação por espaços (evita 'SILVA' como sigla)."""
    chars = list(p.text)
    for c in p.clean.cites:
        if p.start <= c.start < p.end:
            for i in range(c.start - p.start, min(c.end - p.start, len(chars))):
                chars[i] = " "
    return "".join(chars)


def _singular(sig: str) -> str:
    return sig[:-1] if len(sig) > 2 and sig.endswith("s") and sig[:-1].isupper() else sig


def _ctx(text: str, s: int, e: int) -> str:
    a, b = max(0, s - 30), min(len(text), e + 30)
    return ("…" if a else "") + " ".join(text[a:b].split()) + ("…" if b < len(text) else "")
