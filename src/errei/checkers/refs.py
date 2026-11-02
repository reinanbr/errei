"""Verificador ``refs``: citações, bibliografia e (online) existência das referências."""

from __future__ import annotations

import datetime as _dt
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from errei.bib.fields import (
    REQUIRED,
    normalize_doi,
    valid_arxiv,
    valid_doi,
    valid_isbn,
    year_of,
)
from errei.bib.names import parse_authors
from errei.bib.parser import BibEntry, plain
from errei.checkers.base import BaseChecker, RunContext
from errei.model import Finding, Rule
from errei.model import Severity as S

if TYPE_CHECKING:
    from errei.net.sources import Candidate
    from errei.project import Project

# tipos que costumam estar fora de Crossref/OpenAlex: "não encontrada" vira info
WEAKLY_INDEXED = {
    "book",
    "inbook",
    "techreport",
    "manual",
    "misc",
    "online",
    "phdthesis",
    "mastersthesis",
    "thesis",
    "unpublished",
    "booklet",
    "report",
}


def _ratio(a: str, b: str) -> float:
    from errei.net.sources import norm

    a, b = norm(a), norm(b)
    if not a or not b:
        return 0.0
    try:
        from rapidfuzz import fuzz

        return float(fuzz.token_set_ratio(a, b)) / 100.0
    except ModuleNotFoundError:  # pragma: no cover
        import difflib

        return difflib.SequenceMatcher(None, a, b).ratio()


@dataclass(slots=True)
class MatchResult:
    score: float
    title: float
    author: float
    year: float
    divergences: list[str]


def compare(entry: BibEntry, cand: Candidate) -> MatchResult:
    from errei.net.sources import norm

    title = _ratio(plain(entry.get("title")), cand.title)
    authors = parse_authors(entry.get("author") or entry.get("editor"))
    div: list[str] = []
    if authors and cand.authors:
        mine = norm(authors[0].last)
        theirs = [norm(a) for a in cand.authors]
        author = (
            1.0
            if mine in theirs[:1]
            else (0.8 if mine in theirs else max(_ratio(mine, t) for t in theirs[:3]) * 0.8)
        )
        if author < 0.8:
            div.append(f"primeiro autor: '{authors[0].last}' × '{cand.authors[0]}'")
    else:
        author = 0.5
    y = year_of(entry.get("year") or entry.get("date"))
    if y and cand.year:
        diff = abs(y - int(cand.year))
        year = 1.0 if diff == 0 else (0.7 if diff == 1 else 0.0)
        if diff >= 1:
            div.append(f"ano: {y} × {cand.year}")
    else:
        year = 0.5
    venue = plain(entry.get("journal") or entry.get("journaltitle") or "")
    if venue and cand.venue and _ratio(venue, cand.venue) < 0.6:
        div.append(f"periódico: '{venue}' × '{cand.venue}'")
    score = 0.6 * title + 0.25 * author + 0.15 * year
    return MatchResult(score, title, author, year, div)


class RefsChecker(BaseChecker):
    name = "refs"
    title = "Citações e bibliografia"
    uses_network = True
    rules = (
        Rule(
            "REFS-CITE-001",
            S.ERRO,
            "Citação sem entrada na bibliografia",
            "Uma chave usada em \\cite (ou variante) não existe em nenhum .bib do projeto. "
            "No PDF aparecerá '?' ou a chave em negrito.",
        ),
        Rule(
            "REFS-NOBIB-001",
            S.ERRO,
            "Citações sem bibliografia",
            "Há citações no texto, mas nenhum arquivo .bib foi encontrado ou ele está vazio.",
        ),
        Rule(
            "REFS-BIB-001",
            S.SUGESTAO,
            "Entrada nunca citada",
            "Entrada do .bib que não é citada. Pelas normas ABNT (NBR 6023/10520), a lista "
            "de referências deve conter apenas obras citadas no texto.",
        ),
        Rule(
            "REFS-BIB-002",
            S.ERRO,
            "Chave duplicada no .bib",
            "A mesma chave foi definida mais de uma vez; o BibTeX usa só uma delas.",
        ),
        Rule(
            "REFS-BIB-003",
            S.AVISO,
            "Campo repetido na entrada",
            "Um campo aparece duas vezes na mesma entrada; só o primeiro é considerado.",
        ),
        Rule(
            "REFS-BIB-004",
            S.ERRO,
            "Erro de sintaxe no .bib",
            "Entrada malformada (chave/vírgula/chave de fechamento ausente).",
        ),
        Rule(
            "REFS-BIB-005",
            S.AVISO,
            "Possível entrada duplicada",
            "Duas entradas com chaves diferentes parecem ser a mesma obra (mesmo título).",
        ),
        Rule(
            "REFS-FIELD-001",
            S.AVISO,
            "Campos obrigatórios ausentes",
            "Faltam campos obrigatórios para o tipo da entrada (BibTeX/BibLaTeX). A referência "
            "ficará incompleta segundo a NBR 6023.",
            "ABNT NBR 6023:2018",
        ),
        Rule(
            "REFS-YEAR-001",
            S.AVISO,
            "Ano inválido",
            "O campo year/date não contém um ano plausível.",
        ),
        Rule(
            "REFS-DOI-001",
            S.ERRO,
            "DOI malformado",
            "O DOI não segue o formato 10.<prefixo>/<sufixo>.",
        ),
        Rule(
            "REFS-DOI-002",
            S.SUGESTAO,
            "Artigo sem DOI",
            "Artigos de periódico geralmente têm DOI; incluí-lo facilita a verificação e é "
            "recomendado pela NBR 6023 para documentos online.",
            "ABNT NBR 6023:2018",
        ),
        Rule(
            "REFS-DOI-003",
            S.SUGESTAO,
            "DOI com prefixo de URL",
            "O campo doi deve conter só o identificador (10.xxxx/...), sem 'https://doi.org/'.",
        ),
        Rule(
            "REFS-ISBN-001", S.AVISO, "ISBN inválido", "O dígito verificador do ISBN não confere."
        ),
        Rule(
            "REFS-ARXIV-001",
            S.AVISO,
            "Identificador arXiv inválido",
            "O eprint arXiv não segue os formatos AAMM.NNNNN ou arquivo/NNNNNNN.",
        ),
        Rule(
            "REFS-EXIST-001",
            S.INFO,
            "Referência confirmada",
            "A referência foi encontrada em base aberta (Crossref/OpenAlex/Semantic Scholar) "
            "com título, autor e ano compatíveis.",
            heuristic=True,
        ),
        Rule(
            "REFS-EXIST-002",
            S.AVISO,
            "Referência com metadados divergentes",
            "A obra foi encontrada, mas ano, autor, periódico ou DOI diferem do .bib. Confira "
            "a referência.",
            heuristic=True,
        ),
        Rule(
            "REFS-EXIST-003",
            S.AVISO,
            "Referência não encontrada (não verificada)",
            "A obra não foi localizada nas bases abertas consultadas. Isso NÃO significa que "
            "ela não existe: pode estar fora dessas bases (livros, relatórios, anais locais) "
            "ou ter título diferente. Mas referências inexistentes (p.ex. inventadas por "
            "ferramentas de IA) aparecem assim; verifique manualmente.",
            heuristic=True,
        ),
        Rule(
            "REFS-RETRACT-001",
            S.ERRO,
            "Obra retratada",
            "A base consultada indica que a obra foi retratada (retraction). Citar trabalho "
            "retratado exige justificativa explícita no texto.",
        ),
        Rule(
            "REFS-ATRIB-001",
            S.INFO,
            "Afirmação compatível com o resumo da fonte",
            "O modelo errei-cita encontrou no resumo da obra citada um trecho que sustenta a "
            "frase do artigo. Indica compatibilidade com o RESUMO, não com a obra inteira.",
            heuristic=True,
        ),
        Rule(
            "REFS-ATRIB-002",
            S.AVISO,
            "Resumo da fonte parece contradizer a afirmação",
            "O modelo errei-cita encontrou no resumo da obra citada um trecho que parece "
            "contradizer a frase atribuída a ela. Confira se a citação representa a fonte "
            "corretamente (inversão de resultado, generalização, número divergente).",
            heuristic=True,
        ),
        Rule(
            "REFS-ATRIB-003",
            S.SUGESTAO,
            "Atribuição não confirmada pelo resumo",
            "O resumo da obra citada não permite confirmar a frase atribuída a ela. É comum e "
            "não indica erro: o ponto pode estar no texto completo. Confira na fonte se a "
            "afirmação for central para o argumento.",
            heuristic=True,
        ),
        Rule(
            "REFS-ATRIB-004",
            S.INFO,
            "Atribuição não verificável",
            "Não foi possível avaliar a frase: obra não localizada, resumo indisponível nas "
            "bases abertas ou modelo errei-cita não instalado.",
        ),
        Rule(
            "REFS-QUOTE-001",
            S.INFO,
            "Citação direta localizada no texto aberto",
            "O trecho entre aspas foi encontrado no PDF de acesso aberto da obra (--texto-"
            "completo), com a página onde aparece.",
            heuristic=True,
        ),
        Rule(
            "REFS-QUOTE-002",
            S.AVISO,
            "Citação direta não localizada ou com página diferente",
            "O trecho entre aspas não foi encontrado no PDF de acesso aberto da obra, ou "
            "aparece em página diferente da indicada. Pode haver tradução, paráfrase marcada "
            "como citação direta ou outra edição; confira.",
            heuristic=True,
        ),
    )

    def run(self, project: Project, ctx: RunContext) -> list[Finding]:
        out: list[Finding] = []
        entries = project.bib_entries
        uses = project.cite_uses()
        by_key: dict[str, list[BibEntry]] = defaultdict(list)
        for e in entries:
            by_key[e.key].append(e)

        real_uses = [u for u in uses if u.key != "*"]
        nocite_all = any(u.key == "*" for u in uses)
        if real_uses and not entries:
            u = real_uses[0]
            out.append(
                self.finding(
                    "REFS-NOBIB-001",
                    "há citações mas nenhuma entrada .bib",
                    src=u.source,
                    start=u.offset,
                )
            )
        elif entries:
            for u in real_uses:
                if u.key not in by_key:
                    out.append(
                        self.finding(
                            "REFS-CITE-001",
                            f"\\{u.command.name}{{{u.key}}}: chave inexistente no .bib",
                            src=u.source,
                            start=u.offset,
                            end=u.offset + len(u.key),
                            suggestion=_close_key(u.key, list(by_key)),
                        )
                    )

        cited = {u.key for u in real_uses}
        for b in project.bibs:
            for prob in b.problems:
                out.append(
                    self.finding("REFS-BIB-004", prob.message, src=b.source, start=prob.offset)
                )
        for key, dups in by_key.items():
            for d in dups[1:]:
                first = dups[0].source.location(dups[0].start)
                out.append(
                    self.finding(
                        "REFS-BIB-002",
                        f"chave '{key}' duplicada (primeira em {first})",
                        src=d.source,
                        start=d.key_offset,
                        end=d.key_offset + len(key),
                    )
                )
        seen_titles: dict[str, BibEntry] = {}
        for e in entries:
            if not nocite_all and e.key not in cited:
                out.append(
                    self.finding(
                        "REFS-BIB-001",
                        f"entrada '{e.key}' nunca citada",
                        src=e.source,
                        start=e.key_offset,
                        end=e.key_offset + len(e.key),
                    )
                )
            out += self._entry_checks(e)
            from errei.net.sources import norm

            t = norm(plain(e.get("title")))
            if len(t) > 15:
                prev = seen_titles.get(t)
                if prev is not None and prev.key != e.key:
                    out.append(
                        self.finding(
                            "REFS-BIB-005",
                            f"'{e.key}' parece duplicar '{prev.key}' (mesmo título)",
                            src=e.source,
                            start=e.key_offset,
                        )
                    )
                seen_titles.setdefault(t, e)

        if ctx.http is not None:
            targets = [e for e in entries if nocite_all or e.key in cited]
            unique = list(dict.fromkeys(e.key for e in targets))
            done: set[str] = set()
            for e in targets:
                if e.key in done:
                    continue
                done.add(e.key)
                ctx.progress(f"verificando referência {len(done)}/{len(unique)} online: {e.key}")
                rec: dict[str, Any] = {}
                out += self._verify_online(e, ctx, rec)
                try:
                    out += self._attribution(project, e, rec, uses, ctx)
                except Exception as exc:  # etapa extra: falha não derruba a verificação
                    out.append(
                        self.finding(
                            "REFS-ATRIB-004",
                            f"'{e.key}': atribuição não verificada ({type(exc).__name__})",
                            src=e.source,
                            start=e.key_offset,
                        )
                    )
            aviso = ctx.shared.pop("_modelo_aviso", None)
            if aviso:
                out.append(
                    self.finding(
                        "CORE-DEP-001",
                        f"validação das atribuições (frase × resumo da fonte) pulada: {aviso}",
                    )
                )
        return out

    # ------------------------------------------------------------ offline
    def _entry_checks(self, e: BibEntry) -> list[Finding]:
        out: list[Finding] = []
        for f in e.duplicate_fields:
            out.append(
                self.finding(
                    "REFS-BIB-003",
                    f"'{e.key}': campo '{f.name}' repetido",
                    src=e.source,
                    start=f.offset,
                )
            )
        req = REQUIRED.get(e.type)
        if req:
            missing = [
                alt.replace("|", " ou ") for alt in req if not any(e.has(a) for a in alt.split("|"))
            ]
            if missing:
                out.append(
                    self.finding(
                        "REFS-FIELD-001",
                        f"'{e.key}' (@{e.type}) sem: {', '.join(missing)}",
                        src=e.source,
                        start=e.key_offset,
                        end=e.key_offset + len(e.key),
                    )
                )
        yraw = e.get("year") or e.get("date")
        if yraw:
            y = year_of(yraw)
            this_year = _dt.date.today().year
            if y is None or y > this_year + 1:
                out.append(
                    self.finding(
                        "REFS-YEAR-001",
                        f"'{e.key}': ano '{yraw}' inválido",
                        src=e.source,
                        start=e.field_offset("year") if e.has("year") else e.field_offset("date"),
                    )
                )
        if e.has("doi"):
            raw = e.get("doi")
            if not valid_doi(raw):
                out.append(
                    self.finding(
                        "REFS-DOI-001",
                        f"'{e.key}': DOI malformado '{raw}'",
                        src=e.source,
                        start=e.field_offset("doi"),
                    )
                )
            elif normalize_doi(raw) != raw.strip():
                out.append(
                    self.finding(
                        "REFS-DOI-003",
                        f"'{e.key}': use só o identificador no campo doi",
                        src=e.source,
                        start=e.field_offset("doi"),
                        suggestion=f"doi = {{{normalize_doi(raw)}}}",
                    )
                )
        elif e.type == "article":
            out.append(
                self.finding(
                    "REFS-DOI-002",
                    f"'{e.key}': artigo sem DOI",
                    src=e.source,
                    start=e.key_offset,
                    end=e.key_offset + len(e.key),
                )
            )
        if e.has("isbn") and not valid_isbn(e.get("isbn")):
            out.append(
                self.finding(
                    "REFS-ISBN-001",
                    f"'{e.key}': ISBN '{e.get('isbn')}' com dígito verificador inválido",
                    src=e.source,
                    start=e.field_offset("isbn"),
                )
            )
        is_arxiv = (
            e.get("archiveprefix").lower() == "arxiv" or e.get("eprinttype").lower() == "arxiv"
        )
        if is_arxiv and e.has("eprint") and not valid_arxiv(e.get("eprint")):
            out.append(
                self.finding(
                    "REFS-ARXIV-001",
                    f"'{e.key}': eprint arXiv inválido '{e.get('eprint')}'",
                    src=e.source,
                    start=e.field_offset("eprint"),
                )
            )
        return out

    # ------------------------------------------------------------ online
    def _verify_online(
        self, e: BibEntry, ctx: RunContext, rec: dict[str, Any] | None = None
    ) -> list[Finding]:
        from errei.net import sources as srcs

        rec = rec if rec is not None else {}
        rec.setdefault("status", "não verificada")

        http = ctx.http
        threshold = float(ctx.config.get("refs", "match_threshold", 85)) / 100.0
        out: list[Finding] = []
        title = plain(e.get("title"))
        if not title:
            return out
        loc_kw: dict[str, Any] = {
            "src": e.source,
            "start": e.key_offset,
            "end": e.key_offset + len(e.key),
        }
        consulted: list[str] = []
        unavailable = False
        answered = 0
        doi = normalize_doi(e.get("doi")) if e.has("doi") and valid_doi(e.get("doi")) else ""

        best: tuple[MatchResult, Candidate] | None = None
        doi_problem = ""
        if doi:
            for name, fn in (
                ("Crossref", srcs.crossref_by_doi),
                ("OpenAlex", srcs.openalex_by_doi),
            ):
                look = fn(http, doi)
                consulted.append(name)
                if look.status == "unavailable":
                    unavailable = True
                    continue
                answered += 1
                if look.status == "found" and look.candidate is not None:
                    m = compare(e, look.candidate)
                    if m.title >= 0.8:
                        best = (m, look.candidate)
                    else:
                        doi_problem = f"o DOI {doi} pertence a outra obra: '{look.candidate.title}'"
                    break
            else:
                if answered:
                    doi_problem = f"o DOI {doi} não foi encontrado (Crossref/OpenAlex)"
        if e.has("eprint") and best is None and valid_arxiv(e.get("eprint")):
            look = srcs.arxiv_by_id(http, e.get("eprint"))
            consulted.append("arXiv")
            answered += look.status != "unavailable"
            if look.status == "found" and look.candidate is not None:
                m = compare(e, look.candidate)
                if m.title >= 0.8:
                    best = (m, look.candidate)
        if best is None:
            authors = parse_authors(e.get("author") or e.get("editor"))
            y = year_of(e.get("year") or e.get("date"))
            query = " ".join(
                filter(None, [title, authors[0].last if authors else "", str(y or "")])
            )
            for name, search in (
                ("Crossref", srcs.crossref_search),
                ("OpenAlex", srcs.openalex_search),
            ):
                cands = search(http, query)
                consulted.append(name)
                if cands is None:
                    unavailable = True
                    continue
                answered += 1
                for c in cands:
                    m = compare(e, c)
                    if best is None or m.score > best[0].score:
                        best = (m, c)
                if best is not None and best[0].score >= threshold and best[0].title >= 0.9:
                    break
        sources_txt = ", ".join(dict.fromkeys(consulted))

        if best is not None and best[0].title >= 0.9 and best[0].score >= threshold:
            m, c = best
            if c.retracted:
                out.append(
                    self.finding(
                        "REFS-RETRACT-001",
                        f"'{e.key}': a base {c.source} indica retratação",
                        links=(c.url,) if c.url else (),
                        **loc_kw,
                    )
                )
            divergences = list(m.divergences)
            if doi_problem:
                divergences.insert(0, doi_problem)
            if divergences:
                out.append(
                    self.finding(
                        "REFS-EXIST-002",
                        f"'{e.key}': encontrada em {c.source} com divergências",
                        confidence=round(m.score, 2),
                        evidence=tuple(divergences),
                        links=(c.url,) if c.url else (),
                        suggestion=f"confira: '{c.title}' ({c.year}) {c.venue}".strip(),
                        **loc_kw,
                    )
                )
            else:
                sugg = None
                if not doi and c.doi and e.type in ("article", "inproceedings"):
                    sugg = f"adicione doi = {{{c.doi}}}"
                out.append(
                    self.finding(
                        "REFS-EXIST-001",
                        f"'{e.key}': confirmada em {c.source}",
                        confidence=round(m.score, 2),
                        evidence=(f"título {m.title:.0%}, autor {m.author:.0%}, ano {m.year:.0%}",),
                        links=(c.url,) if c.url else (),
                        suggestion=sugg,
                        **loc_kw,
                    )
                )
            rec.update(
                status="divergente" if divergences else "confirmada",
                cand=c,
                divergences=divergences,
            )
            return out

        if best is not None and best[0].score >= 0.7 and best[0].title >= 0.75:
            m, c = best
            ev = [f"título {m.title:.0%}", *m.divergences]
            if doi_problem:
                ev.insert(0, doi_problem)
            out.append(
                self.finding(
                    "REFS-EXIST-002",
                    f"'{e.key}': só há correspondência parcial em {c.source}",
                    confidence=round(m.score, 2),
                    evidence=tuple(ev),
                    links=(c.url,) if c.url else (),
                    suggestion=f"obra mais próxima: '{c.title}' ({c.year})",
                    **loc_kw,
                )
            )
            rec.update(
                status="divergente",
                cand=c,
                divergences=ev,
                note="só há correspondência parcial; atribuição avaliada com cautela",
            )
            return out

        if not answered:
            rec.update(status="não verificada", note="nenhuma base respondeu")
            return out  # nenhuma base respondeu: CORE-NET-001 já informa
        ev = [f"bases consultadas: {sources_txt}"]
        if doi_problem:
            ev.append(doi_problem)
        if best is not None:
            ev.append(f"candidato mais próximo: '{best[1].title}' (semelhança {best[0].score:.0%})")
        if unavailable:
            ev.append("alguma base estava indisponível; resultado incompleto")
        weak = e.type in WEAKLY_INDEXED and not doi
        out.append(
            self.finding(
                "REFS-EXIST-003",
                f"'{e.key}': não encontrada nas bases consultadas — referência não verificada"
                + (" (tipo de obra pouco indexado)" if weak else ", possivelmente inexistente"),
                severity=S.INFO if weak else None,
                confidence=_notfound_confidence(best[0].score if best else 0.0, weak),
                evidence=tuple(ev),
                suggestion="confira na fonte original (DOI, site da editora, catálogo)",
                **loc_kw,
            )
        )
        rec.update(
            status="não encontrada",
            divergences=ev,
            note="obra não localizada; a atribuição não pode ser verificada",
        )
        return out

    # ------------------------------------------------------------ atribuição
    def _attribution(
        self,
        project: Project,
        e: BibEntry,
        rec: dict[str, Any],
        uses: list[Any],
        ctx: RunContext,
    ) -> list[Finding]:
        """Busca a obra (resumo, PDF aberto) e verifica cada frase que a cita."""
        from errei import citecheck
        from errei.net import sources as srcs

        out: list[Finding] = []
        cand = rec.get("cand")
        loc = e.source.location(e.key_offset)
        ref: dict[str, Any] = {
            "key": e.key,
            "status": rec.get("status", "não verificada"),
            "bib_location": f"{loc.file.as_posix()}:{loc.line}",
            "divergences": list(rec.get("divergences", [])),
            "note": rec.get("note", ""),
            "uses": [],
        }
        if cand is not None:
            cand = srcs.enrich(ctx.http, cand)
            ref.update(
                title=cand.title,
                authors=cand.extra.get("authors_full") or cand.authors,
                year=cand.year,
                venue=cand.venue,
                source=cand.source,
                url=cand.url,
                doi=cand.doi,
                abstract=cand.abstract,
                abstract_source=cand.extra.get("abstract_source", ""),
                pdf_url=cand.extra.get("pdf_url", ""),
            )
        contexts = [c for c in (cite_context(project, u) for u in uses if u.key == e.key) if c]
        if contexts and cand is not None:
            ctx.progress(f"validando {len(contexts)} citação(ões) de {e.key} contra o resumo")
        reason = citecheck.unavailable_reason()
        clf = None
        if cand is not None and cand.abstract and reason is None and contexts:
            try:
                clf = citecheck.carregar()
                ctx.extra_meta["modelo_citacoes"] = (
                    f"{citecheck.MODEL_NAME} ({citecheck.model_dir()})"
                )
            except Exception as exc:  # modelo corrompido/incompatível: degrada
                reason = f"falha ao carregar o modelo: {exc}"
        if reason is not None and contexts and cand is not None and cand.abstract:
            ctx.shared.setdefault("_modelo_aviso", reason)
        fulltext: list[str] | None = None
        if (
            ctx.config.get("refs", "texto_completo", False)
            and cand is not None
            and any(c.quote for c in contexts)
        ):
            fulltext = _fulltext_pages(ctx, str(cand.extra.get("pdf_url") or ""))
        for c in contexts:
            use_rec: dict[str, Any] = {"location": c.location, "claim": c.claim}
            kw: dict[str, Any] = {"src": c.source, "start": c.src_offset}
            if cand is None:
                use_rec["verdict"] = "obra não localizada"
            elif not cand.abstract:
                use_rec["verdict"] = "sem resumo"
                out.append(
                    self.finding(
                        "REFS-ATRIB-004",
                        f"'{e.key}': resumo indisponível nas bases abertas; "
                        "atribuição não verificada",
                        excerpt=c.claim,
                        **kw,
                    )
                )
            elif clf is None:
                use_rec["verdict"] = "não avaliada"
            elif len(c.claim.split()) < 4:
                use_rec["verdict"] = "frase curta demais"
            else:
                j = clf.julgar(c.claim, cand.abstract)
                use_rec.update(
                    verdict=j.veredito,
                    score=round(j.score, 3),
                    evidence=j.evidencia,
                    p_sustenta=round(j.sustenta, 3),
                    p_contradiz=round(j.contradiz, 3),
                )
                code, msg = {
                    "sustenta": (
                        "REFS-ATRIB-001",
                        f"'{e.key}': afirmação compatível com o resumo da fonte",
                    ),
                    "contradiz": (
                        "REFS-ATRIB-002",
                        f"'{e.key}': o resumo da fonte parece contradizer a afirmação",
                    ),
                    "neutro": (
                        "REFS-ATRIB-003",
                        f"'{e.key}': o resumo da fonte não permite confirmar a afirmação",
                    ),
                }[j.veredito]
                ev = (
                    f"trecho da fonte: “{j.evidencia[:300]}”",
                    f"P(sustenta) {j.sustenta:.0%} · P(contradiz) {j.contradiz:.0%} "
                    f"(modelo {citecheck.MODEL_NAME}, sobre o resumo)",
                )
                sugg = None
                if j.veredito == "contradiz":
                    sugg = "releia a fonte; corrija a afirmação ou a referência"
                elif j.veredito == "neutro":
                    sugg = "confira no texto completo se a obra afirma isso"
                out.append(
                    self.finding(
                        code,
                        msg,
                        excerpt=c.claim,
                        confidence=round(j.score, 2),
                        evidence=ev,
                        suggestion=sugg,
                        links=(cand.url,) if cand.url else (),
                        **kw,
                    )
                )
            if c.quote and fulltext:
                out += self._check_quote(e, c, fulltext, use_rec, kw)
            ref["uses"].append(use_rec)
        if not contexts and not ref["note"]:
            ref["note"] = "nenhuma citação no texto localizada"
        refs_list = ctx.shared.setdefault("referencias", [])
        refs_list.append(ref)
        return out

    def _check_quote(
        self,
        e: BibEntry,
        c: CiteContext,
        pages: list[str],
        use_rec: dict[str, Any],
        kw: dict[str, Any],
    ) -> list[Finding]:
        from errei.net.sources import norm

        try:
            from rapidfuzz import fuzz
        except ModuleNotFoundError:  # pragma: no cover
            return []
        q = norm(c.quote)
        best = (0.0, -1)
        for i, page in enumerate(pages):
            sc = float(fuzz.partial_ratio(q, norm(page))) / 100 if q else 0.0
            if sc > best[0]:
                best = (sc, i)
        score, idx = best
        use_rec["quote"] = c.quote
        if score >= 0.9:
            page_no = idx + 1
            use_rec["quote_page"] = page_no
            if c.pages and not (c.pages[0] <= page_no <= c.pages[1]):
                return [
                    self.finding(
                        "REFS-QUOTE-002",
                        f"'{e.key}': trecho citado aparece na página {page_no} do PDF aberto, "
                        f"não na p. {c.pages[0]} indicada",
                        excerpt=c.quote,
                        confidence=round(score, 2),
                        evidence=("a numeração do PDF pode diferir da paginação impressa",),
                        **kw,
                    )
                ]
            return [
                self.finding(
                    "REFS-QUOTE-001",
                    f"'{e.key}': citação direta localizada (página {page_no} do PDF aberto)",
                    excerpt=c.quote,
                    confidence=round(score, 2),
                    **kw,
                )
            ]
        return [
            self.finding(
                "REFS-QUOTE-002",
                f"'{e.key}': trecho entre aspas não localizado no PDF aberto da obra",
                excerpt=c.quote,
                confidence=round(1 - score, 2),
                evidence=(
                    f"maior semelhança encontrada: {score:.0%}",
                    "pode ser tradução, outra edição ou paráfrase marcada como citação",
                ),
                suggestion="confira o trecho e a página na fonte",
                **kw,
            )
        ]


QUOTE_RE = re.compile(r"[“\"]([^”\"]{15,}?)[”\"]")
PAGE_RE = re.compile(r"p\.?\s*~?\s*(\d+)(?:\s*[-–]+\s*(\d+))?", re.IGNORECASE)


@dataclass(slots=True)
class CiteContext:
    location: str
    claim: str  # frase do artigo sem os marcadores de citação
    quote: str  # trecho entre aspas próximo à citação (citação direta), se houver
    pages: tuple[int, int] | None  # páginas indicadas em \cite[p.~X]{}
    src_offset: int
    source: Any


def cite_context(project: Project, use: Any) -> CiteContext | None:
    """Frase do texto limpo que contém a citação, sem os placeholders de citação."""
    from errei.text.segment import sentences

    ct = project.clean(use.source)
    span = next((c for c in ct.cites if ct.src(c.start) == use.command.start), None)
    if span is None:
        return None
    para = next((p for p in ct.paragraphs if p.start <= span.start < p.end), None)
    if para is None:
        return None
    rel = span.start - para.start
    sent = next((x for x in sentences(para.text) if x.start <= rel < x.end + 1), None)
    if sent is None:
        return None
    chars = list(para.text)
    for c in ct.cites:
        if para.start <= c.start < para.end:
            for i in range(c.start - para.start, min(c.end - para.start, len(chars))):
                chars[i] = " "
    cleaned = "".join(chars)[sent.start : sent.end]
    cleaned = re.sub(r"\s+([,.;:)])", r"\1", " ".join(cleaned.split()))
    cleaned = re.sub(r"\(\s*\)", "", cleaned).strip(" ,;")
    quote = ""
    for q in QUOTE_RE.finditer(para.text):
        if (q.end() <= rel + 2 and rel - q.end() <= 80) or q.start() <= rel <= q.end():
            quote = q.group(1).strip()
    opts = " ".join(a.text for a in use.command.optional)
    pm = PAGE_RE.search(opts)
    pages = (int(pm.group(1)), int(pm.group(2) or pm.group(1))) if pm else None
    loc = use.source.location(use.offset)
    return CiteContext(
        f"{loc.file.as_posix()}:{loc.line}", cleaned, quote, pages, use.offset, use.source
    )


def _notfound_confidence(best_score: float, weak: bool) -> float:
    """Confiança no "não encontrada": alta quando nada parecido apareceu."""
    conf = min(0.95, max(0.3, 0.5 + (0.85 - best_score)))
    return round(conf * (0.5 if weak else 1.0), 2)


def _close_key(key: str, keys: list[str]) -> str | None:
    import difflib

    match = difflib.get_close_matches(key, keys, n=1, cutoff=0.7)
    return f"você quis dizer '{match[0]}'?" if match else None


def _fulltext_pages(ctx: RunContext, url: str) -> list[str] | None:
    """Baixa (com cache) o PDF de acesso aberto e devolve o texto por página."""
    if not url or ctx.http is None:
        return None
    data = ctx.http.get_bytes(url, max_bytes=30 * 1024 * 1024)
    if not data or not data.startswith(b"%PDF"):
        return None
    try:
        import io

        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        return [(p.extract_text() or "") for p in reader.pages[:400]]
    except Exception:  # PDF malformado/criptografado: não verificável
        return None
