"""Verificador ``ia``: indícios heurísticos e transparentes de texto gerado por IA.

Não treina modelos nem chama serviços. Cada parágrafo recebe um escore 0–1
(soma ponderada logística de indícios explícitos, pesos em ``data/ia_pesos.tsv``)
com os motivos. Saída sempre como "indício", com confiança baixa.
"""

from __future__ import annotations

import importlib
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from functools import cache
from statistics import mean
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from errei.checkers.base import BaseChecker, RunContext
from errei.latex.extract import Paragraph
from errei.model import Finding, Metric, MetricGroup, Rule
from errei.model import Severity as S
from errei.text.metrics import connectives, cv, mattr
from errei.text.segment import alpha_words, load_list, load_table, sentences, strip_accents

if TYPE_CHECKING:
    from errei.project import Project

FIRST_PLURAL = re.compile(r"\b(nós|nosso|nossa|nossos|nossas|\w+(?:amos|emos|imos))\b", re.I)
NUMBER = re.compile(r"\d")
TRANSITION_START = re.compile(
    r"^(além disso|nesse sentido|dessa forma|desse modo|em suma|em síntese|por fim|"
    r"por outro lado|diante disso|assim|portanto|ademais|no entanto|contudo)\b",
    re.I,
)


@runtime_checkable
class ExternalDetector(Protocol):
    """Adapter opcional para um detector externo (desligado por padrão).

    Configure em ``~/.config/errei/config.toml`` (nunca no .errei.toml do artigo)::

        [ia]
        detector = "meu_pacote.detector:MeuDetector"

    A classe precisa expor ``name``, ``uses_network`` e ``score(texto) -> float``
    (0..1). Se ``uses_network`` for verdadeiro, só roda com ``--online``.
    """

    name: str
    uses_network: bool

    def score(self, text: str) -> float: ...


@cache
def _weights() -> dict[str, float]:
    return {row[0]: float(row[1]) for row in load_table("ia_pesos.tsv") if len(row) >= 2}


@cache
def _cliche_res() -> list[re.Pattern[str]]:
    """Todos os padrões (fortes e fracos), usados no escore."""
    return [
        re.compile(r"\b" + c.lstrip("~") + r"\b", re.I) for c in load_list("cliches_llm_ptbr.txt")
    ]


@cache
def _strong_cliche_res() -> list[re.Pattern[str]]:
    """Só os clichês fortes, que geram achado individual."""
    return [
        re.compile(r"\b" + c + r"\b", re.I)
        for c in load_list("cliches_llm_ptbr.txt")
        if not c.startswith("~")
    ]


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


@dataclass(slots=True)
class ParaScore:
    p: Paragraph
    score: float
    features: dict[str, float]
    reasons: list[str]
    cliches: list[re.Match[str]] = field(default_factory=list)


def score_paragraph(
    p: Paragraph, neighbors: list[Paragraph], doc_trigrams: Counter[tuple[str, ...]]
) -> ParaScore:
    text = p.text
    sents = [s for s in sentences(text) if alpha_words(s.text)]
    lens = [len(alpha_words(s.text)) for s in sents]
    words = [strip_accents(w.text.lower()) for w in alpha_words(text)]
    n = len(words)
    reasons: list[str] = []
    f: dict[str, float] = {}

    c = cv([float(x) for x in lens]) if len(lens) >= 3 else 0.45
    f["burstiness"] = _clamp((0.45 - c) / 0.3)
    if f["burstiness"] > 0.3:
        reasons.append(
            f"pouca variação no tamanho das frases (CV {c:.2f}; texto humano costuma variar mais)"
        )

    tris = [tuple(words[i : i + 3]) for i in range(max(0, n - 2))]
    shared = sum(1 for t in tris if doc_trigrams[t] > 1) / len(tris) if tris else 0.0
    f["repeticao"] = _clamp((shared - 0.1) / 0.3)
    if f["repeticao"] > 0.3:
        reasons.append(f"{shared:.0%} dos trigramas se repetem em outros pontos do texto")

    ttr = mattr(text, window=50) or 0.75
    f["diversidade"] = _clamp((0.75 - ttr) / 0.15)
    if f["diversidade"] > 0.3:
        reasons.append(f"diversidade lexical baixa (MATTR {ttr:.2f})")

    conn = connectives(text)
    dens = len(conn) / n * 100 if n else 0
    f["conectivos"] = _clamp((dens - 3) / 4)
    if f["conectivos"] > 0.3:
        reasons.append(f"muitos conectivos ({dens:.1f} por 100 palavras)")

    cl = [m for rx in _cliche_res() for m in rx.finditer(text)]
    f["cliches"] = _clamp(len(cl) / 3)
    if cl:
        uniq = list(dict.fromkeys(m.group(0).lower() for m in cl))
        reasons.append(
            f"{len(cl)} frase(s)-clichê comuns em LLMs: " + ", ".join(f"'{u}'" for u in uniq[:5])
        )

    uni = 0.0
    if TRANSITION_START.match(text.strip()):
        uni += 0.5
    if neighbors and sents:
        sims = [abs(len(sentences(q.text)) - len(sents)) <= 1 for q in neighbors]
        uni += 0.5 * (sum(sims) / len(sims))
    f["uniformidade"] = _clamp(uni)
    if f["uniformidade"] >= 0.5:
        reasons.append(
            "estrutura uniforme (abre com conectivo de transição e/ou tem o mesmo "
            "formato dos parágrafos vizinhos)"
        )

    marks = 0
    if NUMBER.search(text):
        marks += 1
    if any(p.start <= cs.start < p.end for cs in p.clean.cites):
        marks += 1
    if FIRST_PLURAL.search(text):
        marks += 1
    if re.search(r"(?<=[a-zà-ú,;] )[A-Z][a-zà-ú]+", text):
        marks += 1
    f["sem_marcas"] = _clamp(1 - marks / 2)
    if f["sem_marcas"] >= 0.5:
        reasons.append("poucas marcas autorais (números, citações, 1ª pessoa, nomes próprios)")

    w = _weights()
    z = w.get("bias", -4.0) + sum(w.get(k, 0.0) * v for k, v in f.items())
    score = 1 / (1 + math.exp(-z))
    return ParaScore(p, score, f, reasons, cl)


class IaChecker(BaseChecker):
    name = "ia"
    title = "Indícios de texto gerado por IA"
    rules = (
        Rule(
            "IA-IND-001",
            S.INFO,
            "Indícios de texto gerado por IA",
            "Parágrafo com vários indícios estatísticos/estilísticos associados a texto "
            "gerado por modelos de linguagem. NÃO é detecção: textos humanos formais também "
            "pontuam alto, e textos de IA editados pontuam baixo. Use apenas como convite à "
            "revisão. Pesos em data/ia_pesos.tsv.",
            heuristic=True,
        ),
        Rule(
            "IA-CLICHE-001",
            S.SUGESTAO,
            "Frase-clichê",
            "Expressão genérica, muito comum em textos gerados por LLMs e em redação "
            "burocrática. Prefira afirmações específicas.",
            heuristic=True,
        ),
        Rule(
            "IA-EXT-001",
            S.INFO,
            "Detector externo",
            "Escore de um detector externo configurado pelo usuário (adapter opcional).",
        ),
    )

    def run(self, project: Project, ctx: RunContext) -> list[Finding]:
        min_words = int(ctx.config.get("ia", "min_words", 60))
        threshold = float(ctx.config.get("ia", "threshold", 0.6))
        paras = [p for p in project.paragraphs(("body",)) if p.lang == "pt"]
        trigrams: Counter[tuple[str, ...]] = Counter()
        for p in paras:
            ws = [strip_accents(w.text.lower()) for w in alpha_words(p.text)]
            trigrams.update({tuple(ws[i : i + 3]) for i in range(max(0, len(ws) - 2))})
        out: list[Finding] = []
        scores: list[ParaScore] = []
        for i, p in enumerate(paras):
            for rx in _strong_cliche_res():
                for m in rx.finditer(p.text):
                    out.append(
                        self.finding(
                            "IA-CLICHE-001",
                            f"frase-clichê: '{m.group(0)}'",
                            location=p.location(m.start(), m.end()),
                            suggestion="substitua por afirmação específica ou elimine",
                        )
                    )
            if p.word_count() < min_words:
                continue
            nb = [
                q
                for q in (paras[i - 1] if i else None, paras[i + 1] if i + 1 < len(paras) else None)
                if q is not None
            ]
            ps = score_paragraph(p, nb, trigrams)
            scores.append(ps)
            if ps.score >= threshold:
                conf = round(min(0.5, 0.2 + 0.3 * (ps.score - threshold) / (1 - threshold)), 2)
                out.append(
                    self.finding(
                        "IA-IND-001",
                        f"indícios de texto gerado por IA (escore {ps.score:.2f}; heurístico, "
                        "não conclusivo)",
                        severity=S.SUGESTAO if ps.score >= 0.8 else S.INFO,
                        location=p.location(0, min(len(p.text), 60)),
                        excerpt=p.text[:140],
                        confidence=conf,
                        evidence=tuple(ps.reasons),
                        suggestion="revise o parágrafo: dados concretos, citações e voz própria",
                    )
                )
        out += self._external(paras, ctx)
        ctx.add_metrics(self._metrics(scores, threshold))
        return out

    def _external(self, paras: list[Paragraph], ctx: RunContext) -> list[Finding]:
        spec = str(ctx.config.trusted_get("ia", "detector", "") or "")
        if not spec:
            return []
        mod, _, attr = spec.partition(":")
        try:
            obj: Any = getattr(importlib.import_module(mod), attr)
            det = obj() if isinstance(obj, type) else obj
        except Exception as exc:
            return [self.finding("CORE-DEP-001", f"detector externo '{spec}' não carregado: {exc}")]
        if not isinstance(det, ExternalDetector):
            return [self.finding("CORE-DEP-001", f"'{spec}' não implementa ExternalDetector")]
        if det.uses_network and not ctx.online:
            return [
                self.finding("CORE-DEP-001", f"detector '{det.name}' usa rede; rode com --online")
            ]
        out = []
        for p in paras:
            try:
                sc = float(det.score(p.text))
            except Exception as exc:
                out.append(self.finding("CORE-DEP-001", f"detector '{det.name}' falhou: {exc}"))
                break
            out.append(
                self.finding(
                    "IA-EXT-001",
                    f"detector externo '{det.name}': escore {sc:.2f} (indício)",
                    location=p.location(0),
                    confidence=None,
                )
            )
        return out

    def _metrics(self, scores: list[ParaScore], threshold: float) -> MetricGroup:
        g = MetricGroup(self.name, "Indícios de texto gerado por IA (heurísticos)")
        if not scores:
            g.notes.append("nenhum parágrafo longo o bastante para análise")
            return g
        vals = [s.score for s in scores]
        g.metrics.append(
            Metric(
                "Parágrafos analisados",
                len(scores),
                None,
                "≥ 60 palavras",
                "parágrafos curtos são ignorados",
            )
        )
        g.metrics.append(
            Metric(
                "Parágrafos acima do limiar",
                sum(v >= threshold for v in vals),
                None,
                f"limiar {threshold:.2f}",
                "indício ≠ prova; veja as Limitações",
            )
        )
        g.metrics.append(
            Metric(
                "Escore médio",
                round(mean(vals), 2),
                None,
                "0 (poucos indícios) – 1 (muitos)",
                "média dos escores por parágrafo",
            )
        )
        feats = Counter[str]()
        for s in scores:
            for k, v in s.features.items():
                if v >= 0.5:
                    feats[k] += 1
        if feats:
            g.metrics.append(
                Metric(
                    "Indícios mais frequentes",
                    ", ".join(f"{k} ({n})" for k, n in feats.most_common(4)),
                    None,
                    "—",
                    "nº de parágrafos em que cada indício é forte",
                )
            )
        g.notes.append(
            "Heurísticas transparentes, sem modelo treinado. Não use como prova de "
            "autoria; textos humanos formais também podem pontuar alto."
        )
        return g
