"""Verificador ``literatura``: para cada afirmação que precisa de apoio, procura obras
nacionais e internacionais que DIGAM aquilo que a afirmação diz.

Só faz requisições com ``--online``. Para cada afirmação (frases que já citam algo e,
na introdução/revisão, frases sem citação com marcas de generalização):

1. monta consultas em português e, com o tradutor local opcional, em inglês;
2. busca no OpenAlex (base primária) e no Semantic Scholar, sem filtro de país;
3. confirma cada candidato pelo DOI (Crossref/OpenAlex) ou pelo id do arXiv; o que não
   for confirmado é descartado e contado;
4. compara a afirmação com cada frase (e janela de 2 frases) do resumo e, com
   ``--texto-completo``, com trechos do PDF aberto (só licença aberta, ex.: CC BY);
5. só vira ``LIT-SUG-001`` a fonte em que o modelo errei-cita classifica algum trecho
   como "sustenta". As demais do mesmo tema viram, no máximo, ``LIT-REL-001``.

Nada é escrito no ``.tex`` nem no ``.bib``: são indicadores para o autor ler.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from errei.checkers.base import BaseChecker, RunContext
from errei.model import Finding, Metric, MetricGroup, Rule, Severity
from errei.model import Severity as S
from errei.text.segment import STOPWORDS, sentences, strip_accents

if TYPE_CHECKING:
    from errei.latex.source import SourceFile
    from errei.net.sources import Candidate
    from errei.project import Project

AVISO = "indicador, não veredito. Leia a fonte antes de citar."
MAX_TRECHO = 300
REVIEW_TITLES = re.compile(
    r"introdu|trabalhos relacionados|referencial|revis[aã]o|fundamenta|"
    r"estado da arte|related work|background",
    re.IGNORECASE,
)
# frases sem citação que afirmam algo verificável (generalizações, efeitos, números)
CLAIM_RE = re.compile(
    r"\b(estudos|pesquisas|trabalhos|evid[eê]ncias?|literatura|autores)\s+"
    r"(mostram|indicam|apontam|demonstram|sugerem|revelam|confirmam)"
    r"|\b(é|são|foi|foram|tem sido|têm sido)\s+(amplamente|comumente|geralmente|frequentemente)"
    r"|\b(reduz|reduzem|aumenta|aumentam|melhora|melhoram|eleva|elevam|diminui|diminuem|"
    r"causa|causam|provoca|provocam|contribui|contribuem|está associad|estão associad)\w*"
    r"|\b\d+(?:[.,]\d+)?\s?%",
    re.IGNORECASE,
)
EN_STOP = frozenset(
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
        "by",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "an",
        "a",
        "its",
        "their",
        "this",
        "that",
        "these",
        "those",
        "into",
        "via",
        "as",
        "at",
        "or",
        "not",
        "can",
        "may",
        "also",
        "which",
        "has",
        "have",
        "had",
        "it",
        "than",
        "more",
        "most",
        "such",
        "use",
        "used",
        "using",
    ]
)
# palavras funcionais exclusivas de cada língua (sem "a", "do", "no", "as": ambíguas)
PT_MARK = frozenset(
    [
        "de",
        "da",
        "das",
        "dos",
        "que",
        "não",
        "nao",
        "uma",
        "um",
        "para",
        "com",
        "são",
        "sao",
        "pelo",
        "pela",
        "pelos",
        "pelas",
        "entre",
        "também",
        "tambem",
        "como",
        "mais",
        "em",
        "na",
        "nas",
        "os",
        "ao",
        "aos",
        "foi",
        "foram",
        "é",
        "e",
        "se",
        "seu",
        "sua",
        "seus",
        "suas",
        "este",
        "esta",
        "isso",
        "ou",
        "já",
        "ja",
        "quando",
        "sobre",
        "mas",
    ]
)
EN_MARK = frozenset(
    [
        "the",
        "of",
        "and",
        "that",
        "with",
        "for",
        "is",
        "are",
        "this",
        "from",
        "which",
        "were",
        "been",
        "was",
        "has",
        "have",
        "in",
        "on",
        "by",
        "to",
        "at",
        "it",
        "its",
        "their",
        "these",
        "those",
        "we",
        "our",
        "an",
        "or",
        "but",
        "not",
        "than",
        "also",
        "be",
    ]
)
MIN_TERMOS = 0.25


def keywords(text: str, n: int = 7, stop: frozenset[str] = STOPWORDS) -> str:
    seen: list[str] = []
    for w in re.findall(r"[^\W\d_]{4,}", text):
        lw = w.lower()
        if lw in stop or strip_accents(lw) in stop or lw in seen:
            continue
        seen.append(lw)
    seen.sort(key=len, reverse=True)
    return " ".join(seen[:n])


def _norm(s: str) -> str:
    s = strip_accents(s.lower())
    s = re.sub(r"<[^>]+>", " ", s)
    return " ".join(re.sub(r"[^\w\s]", " ", s).split())


def idioma(texto: str, declarado: str = "") -> str:
    """Código ISO 639-1 do trecho: o declarado pela base ou uma contagem de marcas."""
    if declarado:
        return declarado.lower()[:2]
    ws = _norm(texto).split()
    pt = sum(w in PT_MARK for w in ws) + 2 * len(re.findall(r"[ãõçâêô]", texto.lower()))
    en = sum(w in EN_MARK for w in ws)
    if not pt and not en:
        return ""
    return "pt" if pt >= en else "en"


def lexical(terms_text: str, text: str) -> float:
    """Fração dos termos (radicais de 5 letras) presentes no texto."""
    terms = {t[:5] for t in _norm(terms_text).split() if len(t) >= 4}
    if not terms:
        return 0.0
    body = {t[:5] for t in _norm(text).split()}
    return len(terms & body) / len(terms)


@dataclass(slots=True)
class Afirmacao:
    texto: str
    source: SourceFile
    offset: int
    citada: bool


@dataclass(slots=True)
class Trecho:
    texto: str
    pagina: int | None  # None = resumo


@dataclass(slots=True)
class Avaliacao:
    cand: Candidate
    relacao: str  # sustenta | contradiz | neutro | sem-modelo
    p_sustenta: float = 0.0
    p_contradiz: float = 0.0
    trecho: Trecho | None = None
    trecho_c: Trecho | None = None
    qualidade: float = 0.0
    qualis: str = ""
    lex: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def confianca(self) -> str:
        p = self.p_sustenta
        return "alta" if p >= 0.85 else ("média" if p >= 0.65 else "baixa")


QUALIS_PESO = {"A1": 8, "A2": 7, "A3": 6, "A4": 5, "B1": 4, "B2": 3, "B3": 2, "B4": 1}


class LiteraturaChecker(BaseChecker):
    name = "literatura"
    title = "Literatura que sustenta cada afirmação (nacional e internacional)"
    phase = 1
    uses_network = True
    rules = (
        Rule(
            "LIT-SUG-001",
            S.SUGESTAO,
            "Fonte que sustenta a afirmação",
            "Obra localizada e confirmada em base aberta (OpenAlex, Crossref, Semantic "
            "Scholar ou arXiv) em que o modelo errei-cita classificou um trecho (do resumo "
            "ou do texto aberto) como 'sustenta' a afirmação. O trecho aparece no idioma "
            "original. É indicador, não veredito: leia a fonte antes de citar.",
            heuristic=True,
        ),
        Rule(
            "LIT-REL-001",
            S.INFO,
            "Fonte relacionada que NÃO sustenta a afirmação",
            "Obra do mesmo tema (termos em comum) em que nenhum trecho do resumo ou do texto "
            "aberto afirma o que a frase afirma (ou o modelo errei-cita não estava "
            "disponível para avaliar). Não use como apoio sem ler.",
            heuristic=True,
        ),
        Rule(
            "LIT-NONE-001",
            S.INFO,
            "Nenhuma fonte encontrada",
            "A busca nas bases abertas não trouxe obra confirmada sobre a afirmação. Não "
            "significa que a afirmação esteja errada: tente outros termos ou bases.",
        ),
        Rule(
            "LIT-LANG-001",
            S.INFO,
            "Trecho em outro idioma",
            "O trecho que sustenta a afirmação está em idioma diferente do artigo e é "
            "mostrado no idioma original. Uma tradução, se houver, é automática e não é "
            "citação.",
        ),
    )

    # ------------------------------------------------------------------ execução
    def run(self, project: Project, ctx: RunContext) -> list[Finding]:
        if ctx.http is None:
            return [
                Finding(
                    "CORE-NET-001",
                    Severity.INFO,
                    "verificador 'literatura' pulado: requer --online (nenhuma requisição "
                    "foi feita)",
                    self.name,
                )
            ]
        cfg = ctx.config.section("literatura")
        if cfg.get("enabled", True) is False:
            return []
        max_fontes = max(1, int(cfg.get("max_fontes", 3)))
        max_afirm = max(1, int(cfg.get("max_afirmacoes", 15)))
        ano_min = int(cfg["ano_min"]) if cfg.get("ano_min") else None
        idiomas = tuple(str(x).strip().lower() for x in cfg.get("idiomas") or [] if str(x).strip())
        texto_completo = bool(
            cfg.get("texto_completo", ctx.config.get("refs", "texto_completo", False))
        )
        out: list[Finding] = []
        clf = _classificador()
        if clf is None:
            from errei import citecheck

            out.append(
                Finding(
                    "CORE-DEP-001",
                    Severity.INFO,
                    "literatura: modelo errei-cita indisponível "
                    f"({citecheck.unavailable_reason() or 'falha ao carregar'}); nenhuma fonte "
                    "pode ser marcada como 'sustenta', só como relacionada",
                    self.name,
                )
            )
        trad = _tradutor()
        qualis = self._qualis(ctx)
        bib_titles = [_norm(e.get("title")) for e in project.bib_entries if e.get("title")]
        afirm = coletar(project)
        n_total = len(afirm)
        afirm = afirm[:max_afirm]
        en_queries = trad.traduzir([a.texto for a in afirm]) if trad is not None and afirm else []
        n_sug = n_rel = n_none = n_desc = n_conf = 0
        for i, a in enumerate(afirm):
            ctx.progress(f"literatura {i + 1}/{len(afirm)}")
            q_pt = keywords(a.texto)
            q_en = keywords(en_queries[i], 7, EN_STOP) if i < len(en_queries) else ""
            termos = f"{q_pt} {q_en}"
            cands = self._buscar(ctx, [q for q in (q_pt, q_en) if q], ano_min, idiomas)
            cands = [c for c in cands if _norm(c.title) not in bib_titles]
            # pré-filtro por tema antes de gastar requisições de confirmação
            for c in cands:
                c.extra["lex"] = lexical(termos, f"{c.title}. {c.abstract}")
            cands = [c for c in cands if c.extra["lex"] >= MIN_TERMOS]
            cands.sort(key=lambda c: c.extra["lex"], reverse=True)
            confirmados: list[Candidate] = []
            for c in cands[:8]:
                if self._confirmar(ctx, c):
                    confirmados.append(c)
                else:
                    n_desc += 1
            n_conf += len(confirmados)
            avals = [
                self._avaliar(ctx, a, c, clf, termos, texto_completo, qualis) for c in confirmados
            ]
            sus = [v for v in avals if v.relacao == "sustenta"]
            sus.sort(key=lambda v: (-round(v.p_sustenta, 1), -v.qualidade, -(v.cand.year or 0)))
            rel = [v for v in avals if v.relacao != "sustenta"]
            rel.sort(key=lambda v: (-v.lex, -v.qualidade, -(v.cand.year or 0)))
            top_sus = sus[:max_fontes]
            top_rel = rel[: max_fontes - len(top_sus)]
            for v in top_sus:
                out += self._sug(a, v)
            for v in top_rel:
                out.append(self._rel(a, v))
            n_sug += bool(top_sus)
            n_rel += bool(top_rel and not top_sus)
            if not top_sus and not top_rel:
                n_none += 1
                out.append(
                    self.finding(
                        "LIT-NONE-001",
                        "nenhuma fonte encontrada para esta afirmação.",
                        src=a.source,
                        start=a.offset,
                        excerpt=a.texto,
                    )
                )
        g = MetricGroup(self.name, "Literatura por afirmação")
        g.metrics += [
            Metric(
                "Afirmações analisadas",
                len(afirm),
                None,
                "—",
                "frases que citam algo e generalizações sem citação na introdução/revisão",
            ),
            Metric("Com fonte que sustenta", n_sug, None, "—", "modelo errei-cita: 'sustenta'"),
            Metric(
                "Só com fontes relacionadas",
                n_rel,
                None,
                "—",
                "mesmo tema, sem trecho que sustente",
            ),
            Metric("Sem fonte", n_none, None, "—", "nenhuma obra confirmada"),
            Metric("Fontes confirmadas", n_conf, None, "—", "DOI/arXiv conferido em base aberta"),
            Metric(
                "Fontes descartadas (não confirmadas)",
                n_desc,
                None,
                "0",
                "não localizadas por DOI/id em OpenAlex, Crossref, Semantic Scholar ou "
                "arXiv; nunca são exibidas",
            ),
        ]
        if n_total > max_afirm:
            g.notes.append(f"limitado às {max_afirm} primeiras ([literatura].max_afirmacoes)")
        g.notes.append(
            "Consulta em português e em inglês (tradutor local)"
            if trad is not None
            else "Consulta só em português: tradutor local indisponível (errei[traducao])"
        )
        if clf is None:
            g.notes.append("Modelo errei-cita indisponível: nenhuma fonte marcada como 'sustenta'")
        ctx.add_metrics(g)
        return out

    # ------------------------------------------------------------------ busca
    def _buscar(
        self, ctx: RunContext, queries: list[str], ano_min: int | None, idiomas: tuple[str, ...]
    ) -> list[Candidate]:
        from errei.net import sources as srcs

        seen: set[str] = set()
        out: list[Candidate] = []
        for q in queries:
            pool = srcs.openalex_search_lit(ctx.http, q, 8, ano_min=ano_min, idiomas=idiomas)
            pool = (pool or []) + (srcs.s2_search(ctx.http, q, 5, ano_min=ano_min) or [])
            for c in pool:
                key = (c.doi or "").lower() or _norm(c.title)
                if not key or key in seen or len(_norm(c.title)) < 8:
                    continue
                if ano_min and c.year and c.year < ano_min:
                    continue
                lang = idioma(f"{c.title}. {c.abstract}", str(c.extra.get("lingua") or ""))
                c.extra["lingua"] = lang
                if idiomas and lang and lang not in idiomas:
                    continue
                seen.add(key)
                out.append(c)
        return out

    def _confirmar(self, ctx: RunContext, c: Candidate) -> bool:
        """A obra existe? DOI resolvido (Crossref/OpenAlex) com o mesmo título, ou arXiv."""
        from rapidfuzz import fuzz

        from errei.net import sources as srcs

        def same(other: Candidate | None) -> bool:
            if other is None or not other.title:
                return False
            return fuzz.token_set_ratio(_norm(c.title), _norm(other.title)) >= 88

        if c.doi:
            for fn in (srcs.crossref_by_doi, srcs.openalex_by_doi):
                look = fn(ctx.http, c.doi)
                if look.status == "found" and same(look.candidate):
                    c.extra["confirmada_em"] = look.candidate.source if look.candidate else ""
                    if not c.abstract and look.candidate and look.candidate.abstract:
                        c.abstract = look.candidate.abstract
                    return True
            return False
        if c.source == "OpenAlex" and str(c.extra.get("openalex_id") or "").startswith(
            "https://openalex.org/W"
        ):
            c.extra["confirmada_em"] = "OpenAlex"
            return True  # registro do próprio OpenAlex, sem DOI
        arx = str(c.extra.get("arxiv") or "")
        if not arx and "arxiv.org/abs/" in c.url:
            arx = c.url.rsplit("/abs/", 1)[1]
        if arx:
            look = srcs.arxiv_by_id(ctx.http, arx)
            if look.status == "found" and same(look.candidate):
                c.extra["confirmada_em"] = "arXiv"
                return True
        return False

    # ------------------------------------------------------------------ avaliação
    def _trechos(self, ctx: RunContext, c: Candidate, termos: str, completo: bool) -> list[Trecho]:
        from errei.citecheck import frases

        fr = frases(c.abstract) if c.abstract else []
        out = [Trecho(f, None) for f in fr]
        out += [Trecho(fr[i] + " " + fr[i + 1], None) for i in range(len(fr) - 1)]
        if completo:
            from errei.net.textocompleto import texto_de, trechos

            tc = texto_de(ctx, c)
            if tc is not None:
                # CPU: só os trechos com mais termos da afirmação
                out += [Trecho(t, pg) for t, pg in trechos(tc, termos)]
                c.extra["texto_completo"] = tc.descricao()
                c.extra["texto_url"] = tc.url
        return out

    def _avaliar(
        self,
        ctx: RunContext,
        a: Afirmacao,
        c: Candidate,
        clf: Any,
        termos: str,
        completo: bool,
        qualis: Any,
    ) -> Avaliacao:
        v = Avaliacao(c, "sem-modelo", lex=float(c.extra.get("lex") or 0.0))
        v.qualidade, v.qualis = _qualidade(c, qualis)
        trechos = self._trechos(ctx, c, termos, completo) if clf is not None else []
        if clf is None or not trechos:
            v.relacao = "sem-modelo" if clf is None else "neutro"
            return v
        ps = clf.probs([(a.texto, t.texto) for t in trechos])
        i_s = max(range(len(ps)), key=lambda i: ps[i]["sustenta"])
        i_c = max(range(len(ps)), key=lambda i: ps[i]["contradiz"])
        v.p_sustenta, v.p_contradiz = ps[i_s]["sustenta"], ps[i_c]["contradiz"]
        v.trecho, v.trecho_c = trechos[i_s], trechos[i_c]
        lim = getattr(clf, "limiares", {"sustenta": 0.5, "contradiz": 0.5})
        if v.p_contradiz >= lim["contradiz"] and v.p_contradiz >= v.p_sustenta:
            v.relacao = "contradiz"
        elif v.p_sustenta >= lim["sustenta"]:
            v.relacao = "sustenta"
        else:
            v.relacao = "neutro"
        return v

    # ------------------------------------------------------------------ achados
    def _sug(self, a: Afirmacao, v: Avaliacao) -> list[Finding]:
        c, t = v.cand, v.trecho
        assert t is not None
        # idioma do TRECHO (um PDF pode estar em outra língua que a declarada da obra)
        lang = idioma(t.texto) or idioma("", str(c.extra.get("lingua") or ""))
        onde = f"(p. {t.pagina})" if t.pagina else "(resumo)"
        evid = (
            f'Afirmação : "{a.texto}"',
            f"Fonte     : {fonte(c)}",
            f"Base      : {c.source:<12} Idioma: {lang or '?'}",
            f'Trecho    : "{trecho(t.texto)}"  {onde}',
            f"Relação   : sustenta     Confiança: {v.confianca}",
            f"Aviso     : {AVISO}",
        )
        out = [
            self.finding(
                "LIT-SUG-001",
                f"fonte que sustenta a afirmação: {autoria(c)} ({c.year or 's.d.'})",
                src=a.source,
                start=a.offset,
                excerpt=a.texto,
                confidence=round(v.p_sustenta, 2),
                evidence=evid,
                links=tuple(x for x in (_link(c), str(c.extra.get("texto_url") or "")) if x),
                suggestion="leia a fonte; se ela de fato sustentar a afirmação, cite-a com "
                "suas palavras",
            )
        ]
        if lang and lang != "pt":
            out.append(
                self.finding(
                    "LIT-LANG-001",
                    f"o trecho de {autoria(c)} ({c.year or 's.d.'}) está em '{lang}' e foi "
                    "mantido no idioma original; qualquer tradução é automática e não é "
                    "citação",
                    src=a.source,
                    start=a.offset,
                    excerpt=trecho(t.texto),
                )
            )
        return out

    def _rel(self, a: Afirmacao, v: Avaliacao) -> Finding:
        c = v.cand
        if v.relacao == "contradiz" and v.trecho_c is not None:
            motivo = (
                "um trecho da fonte parece contradizer a afirmação: "
                f'"{trecho(v.trecho_c.texto, 160)}"'
            )
        elif v.relacao == "sem-modelo":
            motivo = (
                "modelo errei-cita indisponível: não foi possível verificar se algum "
                "trecho afirma o que a frase afirma."
            )
        else:
            motivo = "nenhum trecho do resumo ou do texto aberto afirma o que a frase afirma."
        return self.finding(
            "LIT-REL-001",
            f"fonte relacionada que NÃO sustenta a afirmação: {autoria(c)} ({c.year or 's.d.'})",
            src=a.source,
            start=a.offset,
            excerpt=a.texto,
            evidence=(
                f"Fonte relacionada (NÃO sustenta a afirmação): {fonte(c, curta=True)}",
                f"Motivo: {motivo}",
            ),
            links=tuple(x for x in (_link(c),) if x),
        )

    @staticmethod
    def _qualis(ctx: RunContext) -> Any:
        table = ctx.shared.get("qualis")
        csv = str(ctx.config.get("periodico", "qualis_csv", "") or "")
        if table is None and csv:
            from errei.qualis import load_qualis

            try:
                table = load_qualis(Path(csv), str(ctx.config.get("periodico", "qualis_data", "")))
            except Exception:
                table = None
        return table


# ---------------------------------------------------------------------- funções
def coletar(project: Project) -> list[Afirmacao]:
    """Afirmações que precisam de apoio, na ordem do documento."""
    from errei.checkers.refs import cite_context

    out: list[Afirmacao] = []
    seen: set[tuple[str, str]] = set()
    for u in project.cite_uses():
        c = cite_context(project, u)
        if c is None or len(c.claim.split()) < 5:
            continue
        key = (u.source.path.as_posix(), c.claim)
        if key in seen:
            continue
        seen.add(key)
        out.append(Afirmacao(c.claim, u.source, _inicio_frase(project, u), True))
    for src in project.tex:
        ct = project.clean(src)
        secs = sorted(ct.sections, key=lambda s: s.clean_start)
        for p in ct.paragraphs:
            if p.kind != "body":
                continue
            title = ""
            for s in secs:
                if s.clean_start <= p.start:
                    title = s.title
            if not REVIEW_TITLES.search(title):
                continue
            for sent in sentences(p.text):
                a0, a1 = p.start + sent.start, p.start + sent.end
                if any(cs.start < a1 and cs.end > a0 for cs in ct.cites):
                    continue
                text = " ".join(sent.text.split())
                if len(text.split()) < 8 or not CLAIM_RE.search(text):
                    continue
                key = (src.path.as_posix(), text)
                if key in seen:
                    continue
                seen.add(key)
                out.append(Afirmacao(text, src, p.src(sent.start), False))
    order = {s.path: i for i, s in enumerate(project.tex)}
    out.sort(key=lambda a: (order.get(a.source.path, 0), a.offset))
    return out


def _inicio_frase(project: Project, use: Any) -> int:
    """Offset de fonte do início da frase que contém a citação."""
    ct = project.clean(use.source)
    span = next((c for c in ct.cites if ct.src(c.start) == use.command.start), None)
    para = next((p for p in ct.paragraphs if p.start <= span.start < p.end), None) if span else None
    if span is None or para is None:
        return int(use.offset)
    rel = span.start - para.start
    sent = next((x for x in sentences(para.text) if x.start <= rel < x.end + 1), None)
    return para.src(sent.start) if sent else int(use.offset)


def autoria(c: Candidate) -> str:
    sob = [a for a in c.authors if a]
    if not sob:
        return "s/ autor"
    if len(sob) == 1:
        return sob[0]
    if len(sob) == 2:
        return f"{sob[0]} e {sob[1]}"
    return f"{sob[0]} et al."


def fonte(c: Candidate, *, curta: bool = False) -> str:
    partes = [f"{autoria(c)} ({c.year or 's.d.'})", c.title.strip().rstrip(".")]
    if c.venue and not curta:
        partes.append(c.venue.strip().rstrip("."))
    ident = f"DOI: {c.doi}" if c.doi else (f"URL: {c.url}" if c.url else "")
    return ". ".join(partes) + (f". {ident}" if ident else "")


def trecho(texto: str, limite: int = MAX_TRECHO) -> str:
    flat = " ".join(texto.split())
    return flat if len(flat) <= limite else flat[: limite - 1] + "…"


def _link(c: Candidate) -> str:
    return f"https://doi.org/{c.doi}" if c.doi else c.url


def _qualidade(c: Candidate, qualis: Any) -> tuple[float, str]:
    """0..1: estrato Qualis (CSV do usuário) e percentil de citações do OpenAlex."""
    estrato = ""
    if qualis is not None:
        for issn in c.extra.get("issn") or []:
            rows = qualis.by_issn(str(issn))
            if rows:
                estrato = max((r.estrato for r in rows), key=lambda e: QUALIS_PESO.get(e, 0))
                break
    q = QUALIS_PESO.get(estrato, 0) / 8
    pct = float(c.extra.get("percentil") or 0.0)
    return 0.6 * q + 0.4 * pct, estrato


def _classificador() -> Any:
    from errei import citecheck

    if citecheck.unavailable_reason() is not None:
        return None
    try:
        return citecheck.carregar()
    except Exception:
        return None


def _tradutor() -> Any:
    from errei import traducao

    return traducao.carregar()
