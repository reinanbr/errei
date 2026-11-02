"""Verificador ``abnt``: NBR 6022, 6023, 6028, 10520 e 14724 (o que é checável no fonte).

Regra de ouro: só apontar o que dá para verificar com segurança no LaTeX; o que
depende de renderização sai como "revisar manualmente".
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from errei.bib.names import split_authors
from errei.bib.parser import BibEntry
from errei.checkers.base import BaseChecker, RunContext
from errei.latex.scanner import find_commands, parse_args
from errei.model import Finding, Rule
from errei.model import Severity as S
from errei.text.abstracts import AbstractBlock, find_abstracts, split_keywords
from errei.text.segment import word_count

if TYPE_CHECKING:
    from errei.project import Project

R6022 = "ABNT NBR 6022:2018"
R6023 = "ABNT NBR 6023:2018"
R6028 = "ABNT NBR 6028:2021"
R10520 = "ABNT NBR 10520:2023"
R14724 = "ABNT NBR 14724:2011"

PLACE_TYPES = {
    "book",
    "inbook",
    "incollection",
    "techreport",
    "phdthesis",
    "mastersthesis",
    "thesis",
    "manual",
    "proceedings",
}
INTRO_RE = re.compile(r"^introdu[cç][aã]o\b", re.IGNORECASE)
CONCL_RE = re.compile(r"conclus|considera[cç][oõ]es finais|considera[cç][aã]o final", re.IGNORECASE)


def detect_style(project: Project) -> str:
    """abntex2cite | biblatex-abnt | biblatex | natbib | bibtex | nenhum."""
    pkgs = project.packages()
    if "abntex2cite" in pkgs:
        return "abntex2cite"
    if "biblatex" in pkgs:
        return "biblatex-abnt" if "abnt" in pkgs["biblatex"][0] else "biblatex"
    if "natbib" in pkgs:
        return "natbib"
    if any(True for _ in project.commands(("bibliographystyle",))):
        return "bibtex"
    return "nenhum"


class AbntChecker(BaseChecker):
    name = "abnt"
    title = "Normas ABNT"
    rules = (
        # --- NBR 6022 / 6028: estrutura, resumo e palavras-chave
        Rule(
            "ABNT-RESUMO-001",
            S.ERRO,
            "Resumo ausente",
            "Artigo científico deve ter resumo na língua do texto (elemento pré-textual "
            "obrigatório).",
            f"{R6022}, 5.1.3",
        ),
        Rule(
            "ABNT-RESUMO-002",
            S.AVISO,
            "Resumo fora da extensão recomendada",
            "Para artigos, o resumo deve ter de 100 a 250 palavras (NBR 6028:2021, 4.3.1); "
            "muitos periódicos pedem 150–250. A faixa é configurável em [abnt].",
            f"{R6028}, 4.3.1",
        ),
        Rule(
            "ABNT-RESUMO-003",
            S.AVISO,
            "Resumo com mais de um parágrafo",
            "O resumo deve ser redigido em parágrafo único.",
            f"{R6028}, 4.2",
        ),
        Rule(
            "ABNT-RESUMO-004",
            S.SUGESTAO,
            "Citação ou fórmula no resumo",
            "Deve-se evitar no resumo o uso de citações, símbolos, fórmulas e equações que "
            "não sejam de uso corrente.",
            f"{R6028}, 4.2",
        ),
        Rule(
            "ABNT-ABSTRACT-001",
            S.AVISO,
            "Resumo em língua estrangeira ausente",
            "Artigos devem ter resumo em língua estrangeira (abstract) após o resumo na "
            "língua do texto.",
            f"{R6022}, 5.1.4",
        ),
        Rule(
            "ABNT-KW-001",
            S.AVISO,
            "Palavras-chave ausentes",
            "O resumo deve ser seguido das palavras-chave, antecedidas da expressão "
            "'Palavras-chave:' (ou 'Keywords:' no abstract).",
            f"{R6028}, 4.4",
        ),
        Rule(
            "ABNT-KW-002",
            S.SUGESTAO,
            "Separador das palavras-chave",
            "A NBR 6028:2021 pede palavras-chave separadas por ponto e vírgula e finalizadas "
            "por ponto. A versão de 2003, usada por muitos templates (inclusive o abnTeX2), "
            "separava por ponto. Confira o que o periódico exige.",
            f"{R6028}, 4.4",
        ),
        Rule(
            "ABNT-KW-003",
            S.SUGESTAO,
            "Quantidade de palavras-chave",
            "A maioria dos periódicos pede de 3 a 5 palavras-chave (configurável).",
            R6022,
        ),
        Rule(
            "ABNT-KW-004",
            S.SUGESTAO,
            "Palavra-chave com inicial maiúscula",
            "As palavras-chave devem ser grafadas com inicial minúscula, exceto nomes "
            "próprios e científicos.",
            f"{R6028}, 4.4",
        ),
        Rule(
            "ABNT-KW-005",
            S.AVISO,
            "Palavras-chave sem ponto final",
            "As palavras-chave devem ser finalizadas por ponto.",
            f"{R6028}, 4.4",
        ),
        Rule(
            "ABNT-ESTR-001",
            S.AVISO,
            "Introdução ausente",
            "Os elementos textuais do artigo começam pela introdução.",
            f"{R6022}, 5.2.1",
        ),
        Rule(
            "ABNT-ESTR-002",
            S.AVISO,
            "Conclusão/considerações finais ausente",
            "Os elementos textuais terminam com a conclusão (considerações finais).",
            f"{R6022}, 5.2.3",
        ),
        Rule(
            "ABNT-ESTR-003",
            S.ERRO,
            "Lista de referências ausente",
            "Referências são elemento pós-textual obrigatório.",
            f"{R6022}, 5.3.1",
        ),
        # --- NBR 10520: citações
        Rule(
            "ABNT-STYLE-001",
            S.INFO,
            "Estilo de citação detectado",
            "Informa o pacote de citações detectado e como as regras foram adaptadas.",
        ),
        Rule(
            "ABNT-STYLE-002",
            S.AVISO,
            "Estilo bibliográfico não ABNT",
            "O estilo bibliográfico configurado não segue a ABNT; as referências não ficarão "
            "conforme a NBR 6023. Use abntex2cite (abntex2-alf) ou biblatex-abnt, se o "
            "periódico pedir ABNT.",
            R6023,
        ),
        Rule(
            "ABNT-CIT-001",
            S.AVISO,
            "'apud' digitado no texto",
            "Com abntex2cite, use \\apud{citado}{original} (ou \\apudonline) para que a "
            "citação de citação seja formatada e as duas obras entrem na lista corretamente.",
            f"{R10520}, 7.6",
        ),
        Rule(
            "ABNT-CIT-002",
            S.AVISO,
            "Citação direta longa entre aspas",
            "Citação direta com mais de três linhas deve ficar destacada com recuo de 4 cm, "
            "fonte menor e sem aspas (ambiente citacao no abnTeX2). O número de linhas "
            "depende da renderização; o errei estima pelo número de palavras.",
            f"{R10520}, 7.1.2",
            heuristic=True,
        ),
        Rule(
            "ABNT-CIT-003",
            S.SUGESTAO,
            "Forma de 'et al.'",
            "A expressão é 'et al.' (com ponto só no 'al.', em itálico conforme o estilo).",
            f"{R10520}",
        ),
        Rule(
            "ABNT-CIT-004",
            S.SUGESTAO,
            "Citação digitada manualmente",
            "Citação autor-data escrita à mão, como '(SILVA, 2020)', não fica ligada ao .bib; "
            "use \\cite para garantir consistência com a lista de referências.",
            R10520,
            heuristic=True,
        ),
        Rule(
            "ABNT-CIT-005",
            S.AVISO,
            "Citação direta sem página",
            "Citação direta (entre aspas) deve indicar a página, p.ex. \\cite[p.~12]{chave}.",
            f"{R10520}, 5.1",
            heuristic=True,
        ),
        Rule(
            "ABNT-CIT-006",
            S.INFO,
            "Caixa do sobrenome na citação (NBR 10520:2023)",
            "O abntex2cite segue a NBR 10520:2002 (sobrenome em MAIÚSCULAS dentro de "
            "parênteses). A NBR 10520:2023 passou a usar maiúsculas e minúsculas. Confira a "
            "versão exigida pelo periódico.",
            R10520,
        ),
        # --- NBR 6023: referências (no .bib)
        Rule(
            "ABNT-REF-001",
            S.SUGESTAO,
            "Nome de autor digitado em maiúsculas",
            "A caixa alta do sobrenome é aplicada pelo estilo (abntex2/biblatex-abnt). "
            "Digitar em maiúsculas no .bib impede a adaptação à NBR 10520:2023 e a outros "
            "estilos.",
            R6023,
        ),
        Rule(
            "ABNT-REF-002",
            S.AVISO,
            "'et al.' no campo author",
            "Use 'and others' no campo author; o estilo gera 'et al.' quando cabível.",
            f"{R6023}, 8.1.1.2",
        ),
        Rule(
            "ABNT-REF-003",
            S.AVISO,
            "Local de publicação ausente",
            "Livros, capítulos, relatórios e trabalhos acadêmicos devem indicar o local "
            "(campo address). Sem ele o estilo gera '[S. l.]'.",
            f"{R6023}, 8.6",
        ),
        Rule(
            "ABNT-REF-004",
            S.AVISO,
            "Documento online sem data de acesso",
            "Documentos consultados online devem indicar endereço eletrônico e data de "
            "acesso ('Acesso em:'): campo urlaccessdate (abntex2cite) ou urldate (biblatex).",
            f"{R6023}, 7.1.3",
        ),
        Rule(
            "ABNT-REF-005",
            S.AVISO,
            "Artigo sem volume ou páginas",
            "Referência de artigo deve trazer numeração (volume/número) e páginas inicial e "
            "final, quando houver.",
            f"{R6023}, 7.7.5",
        ),
        # --- NBR 14724: formatação (só o que aparece no fonte)
        Rule(
            "ABNT-FMT-001",
            S.INFO,
            "Tamanho de fonte/papel",
            "Para trabalhos acadêmicos a NBR 14724 pede papel A4 e fonte 12 no texto. "
            "Artigos seguem a NBR 6022 e o template do periódico; confira no PDF.",
            f"{R14724}, 5.1",
            heuristic=True,
        ),
        Rule(
            "ABNT-FMT-002",
            S.INFO,
            "Margens definidas no fonte",
            "A NBR 14724 pede margens de 3 cm (superior/esquerda) e 2 cm (inferior/direita) "
            "no anverso. Confira se o periódico exige outra configuração.",
            f"{R14724}, 5.1",
        ),
    )

    def run(self, project: Project, ctx: RunContext) -> list[Finding]:
        out: list[Finding] = []
        style = detect_style(project)
        out += self._style(project, style)
        out += self._structure(project, ctx)
        out += self._citations(project, style)
        for e in project.bib_entries:
            out += self._reference(e, style)
        out += self._format(project)
        return out

    # ------------------------------------------------------------ estilo
    def _style(self, project: Project, style: str) -> list[Finding]:
        out: list[Finding] = []
        names = {
            "abntex2cite": "abntex2cite (NBR 10520:2002/6023)",
            "biblatex-abnt": "biblatex-abnt",
            "biblatex": "biblatex (estilo não ABNT)",
            "natbib": "natbib",
            "bibtex": "BibTeX puro",
            "nenhum": "nenhum detectado",
        }
        out.append(self.finding("ABNT-STYLE-001", f"estilo de citação: {names[style]}"))
        for src, cmd in project.commands(("bibliographystyle",)):
            bst = cmd.mandatory[0].text.strip() if cmd.mandatory else ""
            if bst and "abnt" not in bst.lower():
                out.append(
                    self.finding(
                        "ABNT-STYLE-002",
                        f"\\bibliographystyle{{{bst}}} não segue a NBR 6023",
                        src=src,
                        start=cmd.start,
                        end=cmd.end,
                    )
                )
        if style in ("biblatex", "natbib") and not any(
            "abnt" in (cmd.mandatory[0].text if cmd.mandatory else "")
            for _, cmd in project.commands(("bibliographystyle",))
        ):
            pkg = project.packages().get(style)
            if pkg is not None:
                out.append(
                    self.finding(
                        "ABNT-STYLE-002",
                        f"pacote {style} sem estilo ABNT",
                        src=pkg[1],
                        start=pkg[2],
                    )
                )
        if style == "abntex2cite":
            out.append(
                self.finding(
                    "ABNT-CIT-006",
                    "abntex2cite usa SOBRENOME em maiúsculas nas citações "
                    "parentéticas (NBR 10520:2002); a edição de 2023 mudou isso",
                    manual_review=True,
                )
            )
        return out

    # ------------------------------------------------------------ estrutura
    def _structure(self, project: Project, ctx: RunContext) -> list[Finding]:
        out: list[Finding] = []
        cfg = ctx.config.section("abnt")
        rmin, rmax = int(cfg.get("resumo_min", 150)), int(cfg.get("resumo_max", 250))
        kmin, kmax = int(cfg.get("keywords_min", 3)), int(cfg.get("keywords_max", 5))
        blocks = find_abstracts(project)
        resumo = next((b for b in blocks if b.lang == "pt"), None)
        foreign = [b for b in blocks if b.lang != "pt"]
        main = project.main
        if resumo is None:
            out.append(
                self.finding(
                    "ABNT-RESUMO-001",
                    "resumo em português não encontrado",
                    src=main,
                    start=0 if main else None,
                    suggestion="use o ambiente resumo/resumoumacoluna",
                )
            )
        else:
            out += self._abstract_block(resumo, "resumo", rmin, rmax, kmin, kmax)
        if not foreign:
            out.append(
                self.finding(
                    "ABNT-ABSTRACT-001",
                    "resumo em língua estrangeira (abstract) não encontrado",
                    src=main,
                    start=0 if main else None,
                )
            )
        for b in foreign:
            out += self._abstract_block(b, "abstract", rmin, rmax, kmin, kmax)

        titles = [(p, p.text.strip()) for p in project.paragraphs(("heading",))]
        if titles and not any(INTRO_RE.search(t) for _, t in titles):
            p0 = titles[0][0]
            out.append(
                self.finding("ABNT-ESTR-001", "nenhuma seção 'Introdução'", location=p0.location(0))
            )
        if titles and not any(CONCL_RE.search(t) for _, t in titles):
            p1 = titles[-1][0]
            out.append(
                self.finding(
                    "ABNT-ESTR-002",
                    "nenhuma seção 'Conclusão' ou 'Considerações finais'",
                    location=p1.location(0),
                )
            )
        has_refs = any(
            True for _ in project.commands(("bibliography", "printbibliography"), mandatory=0)
        ) or any("\\begin{thebibliography}" in s.masked for s in project.tex)
        if not has_refs and main is not None:
            out.append(
                self.finding(
                    "ABNT-ESTR-003",
                    "nenhuma lista de referências (\\bibliography, "
                    "\\printbibliography ou thebibliography)",
                    src=main,
                    start=0,
                )
            )
        return out

    def _abstract_block(
        self, b: AbstractBlock, label: str, rmin: int, rmax: int, kmin: int, kmax: int
    ) -> list[Finding]:
        out: list[Finding] = []
        if not b.paragraphs:
            return out
        p0 = b.paragraphs[0]
        loc = p0.location(0)
        n = word_count(b.text)
        if n < rmin or n > rmax:
            out.append(
                self.finding(
                    "ABNT-RESUMO-002",
                    f"{label} com {n} palavras (recomendado: {rmin}–{rmax})",
                    location=loc,
                    excerpt=p0.text[:120],
                    suggestion="amplie com objetivo, método, resultados e conclusões"
                    if n < rmin
                    else "condense: foque em objetivo, método, resultados e conclusões",
                )
            )
        if len(b.paragraphs) > 1:
            out.append(
                self.finding(
                    "ABNT-RESUMO-003",
                    f"{label} com {len(b.paragraphs)} parágrafos",
                    location=b.paragraphs[1].location(0),
                    suggestion="una em um único parágrafo",
                )
            )
        for p in b.paragraphs:
            for cs in p.clean.cites:
                if p.start <= cs.start < p.end:
                    out.append(
                        self.finding(
                            "ABNT-RESUMO-004",
                            f"citação no {label}",
                            location=p.clean.location(cs.start, cs.end),
                        )
                    )
                    break
        if b.keywords is None:
            out.append(
                self.finding(
                    "ABNT-KW-001",
                    "palavras-chave ausentes"
                    if label == "resumo"
                    else "keywords ausentes no abstract",
                    location=b.paragraphs[-1].location(0),
                )
            )
            return out
        kp = b.keywords
        body = b.keywords_text
        kloc = kp.location(b.kw_body_start)
        items, sep = split_keywords(body)
        if sep and sep != ";" and len(items) > 1:
            shown = "ponto" if sep == "." else "vírgula"
            out.append(
                self.finding(
                    "ABNT-KW-002",
                    f"palavras-chave separadas por {shown} (NBR 6028:2021: ';')",
                    location=kloc,
                    excerpt=body,
                    suggestion="; ".join(items) + "." if items else None,
                )
            )
        if not body.rstrip().endswith("."):
            out.append(
                self.finding(
                    "ABNT-KW-005", "palavras-chave sem ponto final", location=kloc, excerpt=body
                )
            )
        if items and not kmin <= len(items) <= kmax:
            out.append(
                self.finding(
                    "ABNT-KW-003",
                    f"{len(items)} palavra(s)-chave (usual: {kmin}–{kmax})",
                    location=kloc,
                    excerpt=body,
                )
            )
        for it in items:
            first = it.split()[0] if it.split() else ""
            if first[:1].isupper() and not first.isupper() and len(first) > 1:
                out.append(
                    self.finding(
                        "ABNT-KW-004",
                        f"'{it}' com inicial maiúscula",
                        location=kloc,
                        excerpt=body,
                        suggestion=it[:1].lower() + it[1:],
                    )
                )
                break
        return out

    # ------------------------------------------------------------ citações
    def _citations(self, project: Project, style: str) -> list[Finding]:
        out: list[Finding] = []
        for src in project.tex:
            m = src.masked
            if style == "abntex2cite":
                for mt in re.finditer(r"(?<![\\\w])apud\b", m):
                    out.append(
                        self.finding(
                            "ABNT-CIT-001",
                            "'apud' digitado no texto",
                            src=src,
                            start=mt.start(),
                            end=mt.end(),
                            suggestion="\\apud{citado}{original} ou \\apudonline{citado}{original}",
                        )
                    )
            for mt in re.finditer(r"\bet\.?\s+al\b(?!\.)|\bet\.\s*al\.", m):
                out.append(
                    self.finding(
                        "ABNT-CIT-003",
                        f"'{mt.group(0)}' → 'et al.'",
                        src=src,
                        start=mt.start(),
                        end=mt.end(),
                        suggestion="et al.",
                    )
                )
            for mt in re.finditer(
                r"\((?:[A-ZÀ-Ý][A-ZÀ-Ý'-]+(?:\s+(?:et al\.|[A-ZÀ-Ý'-]+))*;?\s*)+,\s*"
                r"(?:1[5-9]|20)\d\d[a-z]?(?:,\s*p\.\s*[\d-]+)?\)",
                m,
            ):
                out.append(
                    self.finding(
                        "ABNT-CIT-004",
                        f"citação digitada: {mt.group(0)}",
                        src=src,
                        start=mt.start(),
                        end=mt.end(),
                        suggestion="use \\cite{chave}",
                    )
                )
        out += self._quotes(project)
        return out

    def _quotes(self, project: Project) -> list[Finding]:
        out: list[Finding] = []
        quote_re = re.compile(r"[“\"]([^”\"]{20,}?)[”\"]")
        for p in project.paragraphs(("body", "item")):
            text = p.text
            for q in quote_re.finditer(text):
                nwords = word_count(q.group(1))
                if nwords > 40:
                    out.append(
                        self.finding(
                            "ABNT-CIT-002",
                            f"citação direta entre aspas com {nwords} palavras (provavelmente "
                            "> 3 linhas)",
                            location=p.location(q.start(), q.end()),
                            excerpt=q.group(0)[:120],
                            manual_review=True,
                            suggestion="use \\begin{citacao} ... \\end{citacao} sem aspas",
                        )
                    )
                cite = next(
                    (
                        cs
                        for cs in p.clean.cites
                        if p.start + q.end() <= cs.start <= p.start + q.end() + 60
                    ),
                    None,
                )
                if cite is None:
                    continue
                src_off = p.clean.src(cite.start)
                masked = p.source.masked
                mm = re.match(r"\\[A-Za-z]+\*?", masked[src_off:])
                if not mm:
                    continue
                args, _ = parse_args(masked, src_off + mm.end(), 1, 2)
                opts = " ".join(a.text for a in args if a.optional)
                if not re.search(r"\d", opts):
                    out.append(
                        self.finding(
                            "ABNT-CIT-005",
                            "citação direta sem indicação de página",
                            location=p.clean.location(cite.start, cite.end),
                            excerpt=q.group(0)[:100],
                            suggestion="\\cite[p.~N]{chave}",
                        )
                    )
        return out

    # ------------------------------------------------------------ referências
    def _reference(self, e: BibEntry, style: str) -> list[Finding]:
        out: list[Finding] = []
        kw: dict[str, Any] = {
            "src": e.source,
            "start": e.key_offset,
            "end": e.key_offset + len(e.key),
        }
        author_raw = e.get("author")
        if author_raw:
            if re.search(r"\bet\.?\s*al\.?", author_raw):
                out.append(
                    self.finding(
                        "ABNT-REF-002",
                        f"'{e.key}': 'et al.' em author",
                        src=e.source,
                        start=e.field_offset("author"),
                        suggestion="... and others",
                    )
                )
            for a in split_authors(author_raw):
                last = a.split(",")[0].strip() if "," in a else (a.split()[-1] if a.split() else "")
                letters = re.sub(r"[^A-Za-zÀ-ÿ]", "", last)
                if len(letters) > 3 and letters.isupper() and not a.startswith("{"):
                    out.append(
                        self.finding(
                            "ABNT-REF-001",
                            f"'{e.key}': sobrenome '{last}' em maiúsculas no .bib",
                            src=e.source,
                            start=e.field_offset("author"),
                            suggestion=last.title(),
                        )
                    )
                    break
        if e.type in PLACE_TYPES and not e.has("address") and not e.has("location"):
            out.append(
                self.finding("ABNT-REF-003", f"'{e.key}' (@{e.type}) sem local (address)", **kw)
            )
        if e.has("url") and not (e.has("urlaccessdate") or e.has("urldate")):
            field = "urlaccessdate" if style == "abntex2cite" else "urldate"
            out.append(
                self.finding(
                    "ABNT-REF-004",
                    f"'{e.key}' tem URL mas não tem data de acesso",
                    src=e.source,
                    start=e.field_offset("url"),
                    suggestion=f"{field} = {{1 jan. 2026}}"
                    if field == "urlaccessdate"
                    else f"{field} = {{2026-01-01}}",
                )
            )
        if e.type == "article":
            missing = [f for f in ("volume", "pages") if not e.has(f)]
            if missing and e.has("journal"):
                out.append(
                    self.finding(
                        "ABNT-REF-005", f"'{e.key}': artigo sem {', '.join(missing)}", **kw
                    )
                )
        return out

    # ------------------------------------------------------------ formatação
    def _format(self, project: Project) -> list[Finding]:
        out: list[Finding] = []
        dc = project.documentclass()
        if dc is not None:
            _name, opts, src, off = dc
            size = re.search(r"\b(10|11|12)pt\b", opts)
            paper = re.search(r"\b(a4|letter|a5|b5)paper\b", opts)
            problems = []
            if size and size.group(1) != "12":
                problems.append(f"fonte {size.group(1)}pt")
            if paper and paper.group(1) != "a4":
                problems.append(f"papel {paper.group(1)}")
            if problems:
                out.append(
                    self.finding(
                        "ABNT-FMT-001",
                        ", ".join(problems) + " na classe",
                        src=src,
                        start=off,
                        manual_review=True,
                    )
                )
        for src in project.tex:
            for cmd in find_commands(src.masked, ["usepackage"]):
                if cmd.mandatory and cmd.mandatory[0].text.strip() == "geometry" and cmd.optional:
                    o = cmd.optional[0].text
                    vals = dict(re.findall(r"(left|right|top|bottom)\s*=\s*([\d.]+\s*\w+)", o))
                    expect = {"left": "3cm", "top": "3cm", "right": "2cm", "bottom": "2cm"}
                    diff = [f"{k}={v}" for k, v in vals.items() if v.replace(" ", "") != expect[k]]
                    if diff:
                        out.append(
                            self.finding(
                                "ABNT-FMT-002",
                                "margens diferentes de 3/2 cm: " + ", ".join(diff),
                                src=src,
                                start=cmd.start,
                                end=cmd.end,
                                manual_review=True,
                            )
                        )
        return out
