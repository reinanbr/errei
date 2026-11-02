"""Verificador ``nacionais``: sugere obras brasileiras (artigos e livros) para citações
que hoje apontam para obras estrangeiras.

Só roda com ``--online``. Para cada referência estrangeira citada no texto:

1. pega a frase do artigo que a cita (a afirmação);
2. monta consultas em português com as palavras-chave da frase (e, com
   ``--ia-online``, com consultas sugeridas pelo Gemini);
3. busca no OpenAlex (autoria com vínculo brasileiro) e no Google Books (livros em
   português);
4. referências sugeridas pela IA só entram se forem LOCALIZADAS em uma base aberta
   (título conferido); as demais são descartadas e contadas;
5. ordena os candidatos pelo modelo errei-cita (o resumo sustenta a afirmação?) ou,
   sem o modelo, por sobreposição de termos.

Saída: sugestões no relatório. Nada é inserido no ``.bib`` nem no texto: o autor
avalia, lê a obra e decide.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from errei.checkers.base import BaseChecker, RunContext
from errei.model import Finding, Metric, MetricGroup, Rule
from errei.model import Severity as S
from errei.text.segment import STOPWORDS, strip_accents

if TYPE_CHECKING:
    from errei.bib.parser import BibEntry
    from errei.net.sources import Candidate
    from errei.project import Project

EN = frozenset(
    [
        "the",
        "of",
        "and",
        "for",
        "in",
        "on",
        "with",
        "to",
        "from",
        "using",
        "by",
        "is",
        "are",
        "an",
        "a",
        "its",
        "their",
        "this",
        "that",
        "into",
        "toward",
        "towards",
        "via",
        "based",
        "learning",
        "analysis",
        "study",
    ]
)
PT = frozenset(
    [
        "de",
        "da",
        "do",
        "das",
        "dos",
        "e",
        "em",
        "para",
        "com",
        "uma",
        "um",
        "no",
        "na",
        "nos",
        "nas",
        "sobre",
        "os",
        "as",
        "ao",
        "aos",
        "pela",
        "pelo",
        "entre",
        "como",
        "estudo",
        "análise",
        "analise",
    ]
)


BR_MARK = re.compile(
    r"\b(brasil|brazil|brazilian|brasileir[ao]s?|sao paulo|rio de janeiro|sao carlos|"
    r"campinas|belo horizonte|porto alegre|curitiba|florianopolis|recife|salvador|brasilia|"
    r"fortaleza|universidade|usp|unicamp|unesp|ufrj|ufmg|ufrgs|ufsc|ufpr|ufpe|ufba|unb|"
    r"ufc|ufscar|puc|fiocruz|embrapa|ipea|ibge|scielo)\b"
)


def _norm(s: str) -> str:
    s = strip_accents(s.lower())
    s = re.sub(r"<[^>]+>", " ", s)
    return " ".join(re.sub(r"[^\w\s]", " ", s).split())


def is_foreign(e: BibEntry) -> bool:
    """Obra estrangeira? Usa ``language``/``langid`` e, sem eles, as palavras do título."""
    where = _norm(
        " ".join(
            e.get(k)
            for k in (
                "institution",
                "school",
                "address",
                "publisher",
                "journal",
                "booktitle",
                "organization",
                "location",
                "title",
            )
        )
    )
    if BR_MARK.search(where) or e.get("doi").startswith("10.1590/"):
        return False  # autoria/edição brasileira, mesmo com título em inglês
    lang = _norm(e.get("language") or e.get("langid") or e.get("idioma"))
    if lang:
        return not lang.startswith(("pt", "portug", "brazil", "brasil"))
    words = _norm(e.get("title")).split()
    en = sum(w in EN for w in words)
    pt = sum(w in PT for w in words)
    return en > pt


def keywords(claim: str, n: int = 7) -> str:
    seen: list[str] = []
    for w in re.findall(r"[^\W\d_]{4,}", claim):
        lw = w.lower()
        if lw in STOPWORDS or strip_accents(lw) in STOPWORDS or lw in seen:
            continue
        seen.append(lw)
    seen.sort(key=len, reverse=True)
    return " ".join(seen[:n])


MIN_TERMOS = 0.25


@dataclass(slots=True)
class Sugestao:
    cand: Candidate
    score: float
    metodo: str  # "modelo" | "termos"
    origem: str  # "busca" | "IA (verificada)"
    queries: list[str] = field(default_factory=list)
    lex: float = 0.0


class NacionaisChecker(BaseChecker):
    name = "nacionais"
    title = "Sugestões de obras nacionais para citações estrangeiras"
    phase = 1
    uses_network = True
    rules = (
        Rule(
            "NAC-SUG-001",
            S.SUGESTAO,
            "Obra brasileira para a mesma afirmação",
            "A afirmação cita uma obra estrangeira; foram localizadas obras brasileiras "
            "(OpenAlex: autoria com vínculo no Brasil; Open Library/Google Books: livros "
            "em português) "
            "sobre o mesmo tema. Todas existem nas bases consultadas, mas só a leitura "
            "confirma se sustentam a afirmação. Avalie, leia e, se adotar, cite com suas "
            "próprias palavras; a obra estrangeira pode continuar sendo a melhor fonte.",
            heuristic=True,
        ),
        Rule(
            "NAC-IA-001",
            S.INFO,
            "Sugestões da IA descartadas",
            "Referências sugeridas pelo Gemini (--ia-online) que não foram localizadas em "
            "nenhuma base aberta. Não aparecem como sugestão: podem não existir.",
        ),
    )

    def run(self, project: Project, ctx: RunContext) -> list[Finding]:
        if ctx.http is None:
            return []
        from errei.checkers.refs import cite_context

        cfg = ctx.config.section("nacionais")
        if cfg.get("enabled", True) is False:
            return []
        max_refs = int(cfg.get("max_refs", 8))
        max_sug = int(cfg.get("max_sugestoes", 3))
        uses = project.cite_uses()
        cited = {u.key for u in uses}
        bib_titles = [_norm(e.get("title")) for e in project.bib_entries if e.get("title")]
        foreign = [e for e in project.bib_entries if e.key in cited and is_foreign(e)]
        foreign = list({e.key: e for e in reversed(foreign)}.values())[::-1]
        clf = self._model(ctx)
        gem = ctx.shared.get("gemini")
        out: list[Finding] = []
        n_sug = n_desc = n_sem = 0
        for i, e in enumerate(foreign[:max_refs], 1):
            ctxs = [c for c in (cite_context(project, u) for u in uses if u.key == e.key) if c]
            ctxs = [c for c in ctxs if len(c.claim.split()) >= 5]
            if not ctxs:
                continue
            c = ctxs[0]
            ctx.progress(f"obras nacionais {i}/{min(len(foreign), max_refs)}: {e.key}")
            queries = [q for q in [keywords(c.claim)] if q]
            ia_refs: list[dict[str, Any]] = []
            if gem is not None:
                from errei.net.gemini import SCHEMA_NACIONAIS

                data = gem.ask(
                    f"Afirmação de um trabalho acadêmico brasileiro: “{c.claim[:600]}”\n"
                    f"Obra estrangeira citada: {e.get('title')[:300]} ({e.get('year')})\n"
                    "Sugira consultas em português e, se tiver certeza de que existem, "
                    "artigos ou livros de autores brasileiros que sustentem a mesma afirmação.",
                    SCHEMA_NACIONAIS,
                    what="frases que citam obras estrangeiras e os títulos dessas obras",
                )
                if data:
                    queries += [str(q) for q in data.get("consultas") or [] if str(q).strip()]
                    ia_refs = [r for r in data.get("referencias") or [] if isinstance(r, dict)]
            cands = self._search(ctx, queries[:3])
            verified, discarded = self._verify_ia(ctx, ia_refs)
            n_desc += discarded
            sugs = self._rank(c.claim, cands, verified, clf, bib_titles, e)
            if not sugs:
                n_sem += 1
                if discarded:
                    out.append(self._discarded(e, c, discarded))
                continue
            n_sug += 1
            top = sugs[:max_sug]
            ev = [self._fmt(s) for s in top]
            if discarded:
                ev.append(
                    f"{discarded} sugestão(ões) da IA descartada(s): não localizadas em bases "
                    "abertas"
                )
            out.append(
                self.finding(
                    "NAC-SUG-001",
                    f"'{e.key}' é obra estrangeira; {len(top)} obra(s) brasileira(s) sobre o "
                    "mesmo tema localizada(s)",
                    src=c.source,
                    start=c.src_offset,
                    excerpt=c.claim,
                    confidence=round(top[0].score, 2),
                    evidence=tuple(ev),
                    links=tuple(s.cand.url for s in top if s.cand.url),
                    suggestion="leia as obras; se alguma sustentar a afirmação, cite-a (com "
                    "suas palavras) junto ou no lugar da estrangeira",
                )
            )
        g = MetricGroup(self.name, "Sugestões de obras nacionais")
        g.metrics += [
            Metric(
                "Referências estrangeiras citadas",
                len(foreign),
                None,
                "—",
                "pelo campo language/langid ou pelas palavras do título",
            ),
            Metric(
                "Com sugestão nacional",
                n_sug,
                None,
                "—",
                "OpenAlex (BR), Open Library e Google Books (pt)",
            ),
            Metric("Sem candidato relevante", n_sem, None, "—", "nenhuma obra nacional próxima"),
        ]
        if gem is not None:
            g.metrics.append(
                Metric(
                    "Sugestões da IA descartadas",
                    n_desc,
                    None,
                    "0",
                    "não localizadas em bases abertas; nunca são exibidas como sugestão",
                )
            )
        if len(foreign) > max_refs:
            g.notes.append(f"limitado às {max_refs} primeiras ([nacionais].max_refs)")
        g.notes.append(
            "Ordenação: "
            + (
                "modelo errei-cita sobre o resumo/descrição"
                if clf
                else "sobreposição de termos com a frase (modelo indisponível)"
            )
        )
        ctx.add_metrics(g)
        return out

    # ------------------------------------------------------------------
    @staticmethod
    def _model(ctx: RunContext) -> Any:
        from errei import citecheck

        if citecheck.unavailable_reason() is not None:
            return None
        try:
            return citecheck.carregar()
        except Exception:
            return None

    def _search(self, ctx: RunContext, queries: list[str]) -> list[Candidate]:
        from errei.net import sources as srcs

        out: list[Candidate] = []
        for i, q in enumerate(queries):
            out += srcs.openalex_br_search(ctx.http, q, 5) or []
            if i < 2:
                # livros: a busca da Open Library exige todos os termos; use os 3 principais
                short = " ".join(keywords(q, 3).split()) or q
                out += srcs.openlibrary_search(ctx.http, short, 3) or []
                if i == 0:
                    out += srcs.google_books_search(ctx.http, q, 3) or []
        return out

    def _verify_ia(
        self, ctx: RunContext, refs: list[dict[str, Any]]
    ) -> tuple[list[Candidate], int]:
        """Só aceita referência da IA que exista numa base aberta, com título conferido."""
        from rapidfuzz import fuzz

        from errei.net import sources as srcs

        ok: list[Candidate] = []
        bad = 0
        for r in refs[:3]:
            titulo = str(r.get("titulo") or "").strip().rstrip("…")
            if len(titulo) < 8:
                bad += 1
                continue
            autores = _norm(str(r.get("autores") or ""))
            found = None
            pools = [
                srcs.openalex_search(ctx.http, titulo, 3),
                srcs.openlibrary_search(ctx.http, titulo, 3),
                srcs.google_books_search(ctx.http, f"intitle:{titulo}", 3),
                srcs.crossref_search(ctx.http, titulo, 3),
            ]
            for pool in pools:
                for cand in pool or []:
                    t1, t2 = _norm(titulo), _norm(cand.title)
                    if not t2:
                        continue
                    sim = max(
                        fuzz.ratio(t1, t2),
                        fuzz.partial_ratio(t1, t2) if min(len(t1), len(t2)) > 25 else 0,
                    )
                    if sim < 88:
                        continue
                    if (
                        autores
                        and cand.authors
                        and not any(_norm(a) and _norm(a) in autores for a in cand.authors)
                    ):
                        continue
                    found = cand
                    break
                if found:
                    break
            if found is None:
                bad += 1
                continue
            found.extra.setdefault("tipo", str(r.get("tipo") or ""))
            found.extra["via_ia"] = True
            ok.append(found)
        return ok, bad

    def _rank(
        self,
        claim: str,
        cands: list[Candidate],
        verified: list[Candidate],
        clf: Any,
        bib_titles: list[str],
        e: BibEntry,
    ) -> list[Sugestao]:
        from rapidfuzz import fuzz

        own = _norm(e.get("title"))
        seen: set[str] = set()
        out: list[Sugestao] = []
        kw = keywords(claim, 12)
        for cand in verified + cands:
            t = _norm(cand.title)
            if not t or t in seen or len(t) < 8:
                continue
            seen.add(t)
            if fuzz.ratio(t, own) > 85 or any(fuzz.ratio(t, b) > 90 for b in bib_titles):
                continue  # é a própria obra ou já está nas referências
            text = f"{cand.title}. {cand.abstract}".strip()
            via_ia = bool(cand.extra.get("via_ia"))
            lex = self._lexical(kw, text)
            if lex < MIN_TERMOS and not via_ia:
                continue  # sem termos em comum: o modelo sozinho superestima a afinidade
            if clf is not None and cand.abstract:
                j = clf.julgar(claim, text)
                if j.veredito == "contradiz":
                    continue
                score, met = 0.6 * float(j.sustenta) + 0.4 * lex, "modelo"
            else:
                score, met = lex, "termos"
            if score < 0.3 and not via_ia:
                continue
            sug = Sugestao(cand, score, met, "IA (verificada)" if via_ia else "busca")
            sug.lex = lex
            out.append(sug)
        out.sort(key=lambda s: s.score, reverse=True)
        return out

    @staticmethod
    def _lexical(kw: str, text: str) -> float:
        """Fração dos termos da afirmação (radicais de 5 letras) presentes na obra."""
        terms = {t[:5] for t in _norm(kw).split() if len(t) >= 4}
        if not terms:
            return 0.0
        body = {t[:5] for t in _norm(text).split()}
        return len(terms & body) / len(terms)

    @staticmethod
    def _fmt(s: Sugestao) -> str:
        c = s.cand
        autores = c.extra.get("authors_full") or c.authors
        aut = "; ".join(autores[:3]) + (" et al." if len(autores) > 3 else "")
        tipo = c.extra.get("tipo") or "obra"
        ident = (
            f"DOI {c.doi}"
            if c.doi
            else (f"ISBN {c.extra['isbn']}" if c.extra.get("isbn") else c.url)
        )
        score = (
            f"P(sustenta) {s.score:.0%}"
            if s.metodo == "modelo"
            else f"afinidade de termos {s.score:.0%}"
        )
        return (
            f"[{tipo}] {aut or 's/ autor'} ({c.year or 's.d.'}). {c.title}. "
            f"{c.venue or ''} — {ident} — localizada em {c.source}"
            f"{'; sugerida pela IA' if s.origem != 'busca' else ''}; {score}"
        ).replace(". . ", ". ")

    def _discarded(self, e: BibEntry, c: Any, n: int) -> Finding:
        return self.finding(
            "NAC-IA-001",
            f"'{e.key}': {n} sugestão(ões) da IA descartada(s) por não existirem nas bases "
            "abertas; nenhuma obra nacional próxima encontrada",
            src=c.source,
            start=c.src_offset,
        )
