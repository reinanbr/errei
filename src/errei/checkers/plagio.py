"""Verificador ``plagio``: indícios de similaridade em três camadas.

1. repetição interna (autoplágio/trechos repetidos entre seções e arquivos);
2. corpus local opcional (``[plagio].corpus``);
3. busca online opt-in de frases distintivas em metadados/resumos públicos.

Linguagem controlada: "trecho semelhante", "sobreposição", "indício". Nunca
"plágio" como afirmação.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from errei.checkers.base import BaseChecker, RunContext
from errei.latex.extract import Paragraph
from errei.model import Finding, Metric, MetricGroup, Rule
from errei.model import Severity as S
from errei.text.segment import STOPWORDS, alpha_words, sentences
from errei.text.similarity import (
    FingerprintIndex,
    Tok,
    containment,
    jaccard,
    shared_span,
    shingles,
    tokens,
)

if TYPE_CHECKING:
    from errei.project import Project

CORPUS_EXTS = {".txt", ".md", ".tex", ".pdf"}
MAX_CORPUS_FILES = 2000
MAX_CORPUS_BYTES = 30 * 1024 * 1024


@dataclass(slots=True)
class _Para:
    p: Paragraph
    toks: list[Tok]
    seq: list[int]
    set: frozenset[int]


def _cite_near(p: Paragraph, start: int, end: int, pad: int = 80) -> bool:
    for c in p.clean.cites:
        cs, ce = c.start - p.start, c.end - p.start
        if cs <= end + pad and ce >= start - pad:
            return True
    return False


def _snippet(text: str, s: int, e: int, limit: int = 140) -> str:
    frag = " ".join(text[s:e].split())
    return frag if len(frag) <= limit else frag[: limit - 1] + "…"


class PlagioChecker(BaseChecker):
    name = "plagio"
    title = "Similaridade (indícios)"
    uses_network = True
    rules = (
        Rule(
            "PLAGIO-INT-001",
            S.AVISO,
            "Trecho repetido no próprio artigo",
            "Sequência longa de palavras que aparece em mais de um lugar do artigo "
            "(entre seções ou arquivos). Pode ser repetição involuntária ou reaproveitamento "
            "de texto; revise. Comparação por shingles de k palavras com Jaccard/contenção.",
            heuristic=True,
        ),
        Rule(
            "PLAGIO-CORPUS-001",
            S.AVISO,
            "Trecho semelhante no corpus local",
            "Sequência de palavras coincide com um documento do corpus local indicado em "
            "[plagio].corpus. É um indicador; confira se há citação adequada.",
            heuristic=True,
        ),
        Rule(
            "PLAGIO-CORPUS-002",
            S.INFO,
            "Problema ao ler o corpus local",
            "Arquivo ou pasta do corpus não encontrado ou ilegível.",
        ),
        Rule(
            "PLAGIO-WEB-001",
            S.AVISO,
            "Trecho semelhante a publicação indexada",
            "Frase distintiva do artigo é muito parecida com trecho de título/resumo público "
            "(OpenAlex, Semantic Scholar, arXiv). Só metadados e resumos são consultados; "
            "não substitui Turnitin/iThenticate.",
            heuristic=True,
        ),
    )

    def run(self, project: Project, ctx: RunContext) -> list[Finding]:
        cfg = ctx.config.section("plagio")
        k = max(4, int(cfg.get("shingle", 8)))
        threshold = float(cfg.get("threshold", 0.35))
        paras = []
        for p in project.paragraphs(("body", "item", "quote")):
            toks = tokens(p.text)
            seq = shingles(toks, k)
            if len(seq) >= 3:
                paras.append(_Para(p, toks, seq, frozenset(seq)))
        out: list[Finding] = []
        covered_int: set[tuple[int, int]] = set()
        out += self._internal(paras, k, threshold, covered_int)
        corpus_paths = [str(c) for c in cfg.get("corpus", []) or []]
        covered_corpus = 0
        if corpus_paths:
            found, covered_corpus = self._corpus(project, paras, corpus_paths, k, threshold, ctx)
            out += found
        web_hits = 0
        if ctx.http is not None:
            found = self._online(paras, ctx, int(cfg.get("online_queries", 8)))
            web_hits = len(found)
            out += found
        total_words = sum(len(x.toks) for x in paras)
        g = MetricGroup(self.name, "Similaridade (indícios)")
        g.metrics.append(
            Metric(
                "Palavras em trechos repetidos internamente",
                len(covered_int),
                None,
                "idealmente 0",
                f"de {total_words} palavras analisadas (shingles de {k} palavras)",
            )
        )
        g.metrics.append(
            Metric(
                "Palavras semelhantes ao corpus local",
                covered_corpus if corpus_paths else "corpus não configurado",
                None,
                "—",
                "use [plagio].corpus para comparar com PDFs/textos",
            )
        )
        g.metrics.append(
            Metric(
                "Trechos semelhantes online",
                web_hits if ctx.http is not None else "busca online desligada",
                None,
                "—",
                "frases distintivas buscadas em OpenAlex, Semantic "
                "Scholar e arXiv (apenas metadados/resumos)",
            )
        )
        g.notes.append(
            "Indicadores de similaridade, não constatação de plágio. Não substitui "
            "Turnitin/iThenticate."
        )
        ctx.add_metrics(g)
        return out

    # ------------------------------------------------------------ camada 1
    def _internal(
        self, paras: list[_Para], k: int, threshold: float, covered: set[tuple[int, int]]
    ) -> list[Finding]:
        out: list[Finding] = []
        for j in range(len(paras)):
            b = paras[j]
            for i in range(j):
                a = paras[i]
                inter = a.set & b.set
                if len(inter) < 3:
                    continue
                cont = containment(a.set, b.set)
                s, e, nwords = shared_span(b.seq, set(a.set), b.toks, k)
                if cont < threshold and nwords < 25:
                    continue
                for t in b.toks:
                    if s <= t.start < e:
                        covered.add((id(b), t.start))
                conf = round(min(0.95, 0.5 + cont / 2), 2)
                ev = [
                    f"{nwords} palavras seguidas em comum; contenção {cont:.0%}, "
                    f"Jaccard {jaccard(set(a.set), set(b.set)):.0%}"
                ]
                if _cite_near(b.p, s, e):
                    conf = round(conf * 0.6, 2)
                    ev.append("há citação próxima (pode ser reaproveitamento citado)")
                out.append(
                    self.finding(
                        "PLAGIO-INT-001",
                        f"trecho semelhante a {a.p.location(0)} (sobreposição {cont:.0%})",
                        location=b.p.location(s, e),
                        excerpt=_snippet(b.p.text, s, e),
                        confidence=conf,
                        evidence=tuple(ev),
                        suggestion="remova a repetição ou reescreva um dos trechos",
                    )
                )
                break  # um achado por parágrafo repetido
        return out

    # ------------------------------------------------------------ camada 2
    def _corpus(
        self,
        project: Project,
        paras: list[_Para],
        paths: list[str],
        k: int,
        threshold: float,
        ctx: RunContext,
    ) -> tuple[list[Finding], int]:
        out: list[Finding] = []
        index = FingerprintIndex(k)
        files: list[Path] = []
        for raw in paths:
            p = Path(raw).expanduser()
            if not p.is_absolute():
                p = project.root / p
            if p.is_file():
                files.append(p)
            elif p.is_dir():
                files += sorted(
                    x
                    for x in p.rglob("*")
                    if x.suffix.lower() in CORPUS_EXTS and x.is_file() and not x.is_symlink()
                )
            else:
                out.append(self.finding("PLAGIO-CORPUS-002", f"corpus não encontrado: {raw}"))
        article = {s.abspath.resolve() for s in project.all_sources()}
        files = [f for f in files if f.resolve() not in article][:MAX_CORPUS_FILES]
        total = 0
        for f in files:
            try:
                size = f.stat().st_size
                if total + size > MAX_CORPUS_BYTES * 10:
                    break
                text = _read_corpus(str(f), f.stat().st_mtime, size)
            except Exception as exc:  # arquivo do usuário: nunca derruba
                out.append(self.finding("PLAGIO-CORPUS-002", f"{f.name}: {exc}"))
                continue
            if text is None:
                out.append(
                    self.finding(
                        "PLAGIO-CORPUS-002", f"{f.name}: PDF requer 'errei[plagio]' (pypdf)"
                    )
                )
                continue
            total += size
            index.add(str(f), text)
        covered = 0
        for a in paras:
            hits = index.query(a.seq, min_hits=1)
            best: tuple[float, int, tuple[int, int, int]] | None = None
            for doc_id in hits:
                dseq = index.doc_shingles(doc_id)
                dset = set(dseq)
                cont = len(a.set & dset) / len(a.set)
                span = shared_span(a.seq, dset, a.toks, k)
                if (cont >= threshold or span[2] >= max(12, k + 4)) and (
                    best is None or cont > best[0]
                ):
                    best = (cont, doc_id, span)
            if best is None:
                continue
            cont, doc_id, (s, e, nwords) = best
            covered += nwords
            name = Path(index.docs[doc_id][0])
            try:
                shown = name.relative_to(project.root).as_posix()
            except ValueError:
                shown = name.name
            conf = round(min(0.95, 0.5 + cont / 2), 2)
            ev = [f"{nwords} palavras seguidas em comum; {cont:.0%} do parágrafo"]
            if _cite_near(a.p, s, e):
                conf = round(conf * 0.6, 2)
                ev.append("há citação próxima ao trecho")
            out.append(
                self.finding(
                    "PLAGIO-CORPUS-001",
                    f"trecho semelhante a '{shown}' (corpus local)",
                    location=a.p.location(s, e),
                    excerpt=_snippet(a.p.text, s, e),
                    confidence=conf,
                    evidence=tuple(ev),
                    suggestion="se for texto de terceiros, use citação direta com aspas e página",
                )
            )
        return out, covered

    # ------------------------------------------------------------ camada 3
    def _online(self, paras: list[_Para], ctx: RunContext, max_queries: int) -> list[Finding]:
        from errei.net import sources as srcs

        try:
            from rapidfuzz import fuzz
        except ModuleNotFoundError:  # pragma: no cover
            return [
                self.finding(
                    "CORE-DEP-001",
                    "busca online de similaridade requer 'errei[online]' (rapidfuzz)",
                )
            ]
        out: list[Finding] = []
        phrases = distinctive_phrases(paras, max_queries)
        for n, (para, s, e, phrase) in enumerate(phrases, 1):
            ctx.progress(f"buscando frase distintiva {n}/{len(phrases)} online")
            best: tuple[float, Any] | None = None
            for search in (srcs.openalex_search, srcs.s2_search, srcs.arxiv_search):
                cands = search(
                    ctx.http, f'"{phrase}"' if search is srcs.openalex_search else phrase, 3
                )
                for c in cands or []:
                    hay = f"{c.title}. {c.abstract}"
                    score = float(fuzz.partial_ratio(phrase.lower(), hay.lower())) / 100
                    if best is None or score > best[0]:
                        best = (score, c)
                if best is not None and best[0] >= 0.95:
                    break
            if best is None or best[0] < 0.9:
                continue
            score, c = best
            conf = round(score * 0.8, 2)
            ev = [f"semelhança {score:.0%} com título/resumo ({c.source})"]
            if _cite_near(para.p, s, e):
                conf = round(conf * 0.6, 2)
                ev.append("há citação próxima ao trecho")
            out.append(
                self.finding(
                    "PLAGIO-WEB-001",
                    f"trecho semelhante a '{c.title[:90]}' ({c.year or 's.d.'}, {c.source})",
                    location=para.p.location(s, e),
                    excerpt=phrase,
                    confidence=conf,
                    evidence=tuple(ev),
                    links=(c.url,) if c.url else (),
                    suggestion="confira a fonte; se usar o texto, cite-a",
                )
            )
        return out


def distinctive_phrases(
    paras: list[_Para], n: int, size: int = 10
) -> list[tuple[_Para, int, int, str]]:
    """Escolhe até ``n`` janelas de ``size`` palavras com maior raridade estimada."""
    scored: list[tuple[float, _Para, int, int, str]] = []
    for para in paras:
        if para.p.kind == "quote":
            continue
        for sent in sentences(para.p.text):
            if _cite_near(para.p, sent.start, sent.end, pad=0):
                continue
            ws = alpha_words(sent.text)
            if len(ws) < size:
                continue
            for i in range(0, len(ws) - size + 1, max(1, size // 2)):
                win = ws[i : i + size]
                content = [w.text.lower() for w in win if w.text.lower() not in STOPWORDS]
                if len(content) < size * 0.5:
                    continue
                rarity = sum(_rarity(w) for w in content) / size
                s = sent.start + win[0].start
                e = sent.start + win[-1].end
                scored.append((rarity, para, s, e, para.p.text[s:e]))
    scored.sort(key=lambda x: -x[0])
    chosen: list[tuple[_Para, int, int, str]] = []
    used: set[int] = set()
    for _r, para, s, e, phrase in scored:
        if id(para) in used:
            continue
        used.add(id(para))
        chosen.append((para, s, e, " ".join(phrase.split())))
        if len(chosen) >= n:
            break
    return chosen


@cache
def _freq() -> Any:
    try:
        from spellchecker import SpellChecker

        return SpellChecker(language="pt", distance=1).word_frequency
    except Exception:  # pragma: no cover - extra ausente
        return None


def _rarity(word: str) -> float:
    """IDF aproximado: frequência do dicionário de frequências pt (pyspellchecker)."""
    wf = _freq()
    if wf is None:
        return min(1.0, len(word) / 12)
    count = int(wf.dictionary.get(word, 0))
    return 1.0 / (1.0 + math.log1p(count))


@cache
def _read_corpus(path: str, mtime: float, size: int) -> str | None:
    """Lê (com cache por mtime/tamanho) o texto de um arquivo do corpus."""
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ModuleNotFoundError:
            return None
        reader = PdfReader(str(p))
        return "\n".join((page.extract_text() or "") for page in reader.pages[:500])
    raw = p.read_bytes()[:MAX_CORPUS_BYTES]
    text = raw.decode("utf-8", errors="replace")
    if suffix == ".tex":
        from errei.latex.extract import extract
        from errei.latex.source import SourceFile

        return extract(SourceFile(Path(p.name), p, text)).text
    return text
