"""Verificador ``completude``: o que falta para o trabalho estar completo.

Compara os elementos presentes no fonte com a estrutura exigida pela ABNT para o
tipo de trabalho:

* artigo — NBR 6022:2018 (elementos pré-textuais, textuais e pós-textuais);
* monografia/TCC/dissertação/tese — NBR 14724:2011.

O tipo é detectado (classe/opções, ``\\chapter``, ``\\imprimircapa``...) ou informado
com ``--tipo``. A saída é um checklist (métricas) e achados para o que falta. Com
``--online --ia-online``, o Gemini acrescenta orientações curtas e específicas do tema
para os elementos ausentes: orientações, nunca texto pronto.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from errei.checkers.base import BaseChecker, RunContext
from errei.model import Finding, Metric, MetricGroup, Rule
from errei.model import Severity as S
from errei.text.segment import strip_accents

if TYPE_CHECKING:
    from errei.project import Project

R6022 = "ABNT NBR 6022:2018"
R14724 = "ABNT NBR 14724:2011"
MONO_TIPOS = {"monografia", "tcc", "dissertacao", "tese"}
TIPOS = {"auto", "artigo"} | MONO_TIPOS

# elementos que o verificador ``abnt`` já aponta (evita achado duplicado)
COBERTOS_ABNT = {"resumo", "abstract", "palavras-chave", "introducao", "conclusao", "referencias"}

# o que cada seção deve conter (orientação fixa, sem IA)
GUIA = {
    "introducao": "apresente o tema, o problema/pergunta de pesquisa, a justificativa e o "
    "objetivo geral (e os específicos)",
    "referencial": "discuta os conceitos e estudos que fundamentam o trabalho, com citações",
    "metodologia": "descreva tipo de pesquisa, população/amostra ou corpus, instrumentos, "
    "procedimentos de coleta e de análise",
    "resultados": "apresente os dados obtidos (tabelas/figuras) e os interprete à luz do "
    "referencial",
    "conclusao": "retome o objetivo, responda à pergunta de pesquisa, aponte limitações e "
    "trabalhos futuros",
    "resumo": "objetivo, método, resultados e conclusões em parágrafo único",
    "abstract": "versão em língua estrangeira do resumo, com keywords",
    "palavras-chave": "3 a 5 termos separados por ponto, após o resumo",
    "referencias": "lista das obras citadas (\\bibliography ou \\printbibliography)",
    "titulo": "\\title{...} ou \\titulo{...}",
    "autor": "\\author{...} ou \\autor{...}, com afiliação e e-mail",
    "afiliacao": "instituição e e-mail do autor (\\thanks, \\footnote ou \\affil)",
    "datas": "datas de submissão e aprovação (em geral inseridas pelo periódico)",
    "capa": "\\imprimircapa (abnTeX2) ou ambiente titlepage",
    "folha-rosto": "\\imprimirfolhaderosto (abnTeX2)",
    "ficha": "ambiente fichacatalografica (ficha elaborada pela biblioteca)",
    "aprovacao": "ambiente folhadeaprovacao, com banca e data",
    "sumario": "\\tableofcontents ou \\sumario após as listas",
    "lista-figuras": "\\listoffigures (o trabalho tem figuras)",
    "lista-tabelas": "\\listoftables (o trabalho tem tabelas)",
    "siglas": "ambiente siglas com as abreviaturas usadas",
    "desenvolvimento": "pelo menos um capítulo entre a introdução e a conclusão",
}


@dataclass(frozen=True, slots=True)
class Elemento:
    key: str
    nome: str
    grupo: str  # pré-textual | textual | pós-textual | dados
    nivel: str  # obrigatório | recomendado | opcional
    ref: str


def _norm(s: str) -> str:
    return " ".join(strip_accents(s.lower()).split())


HEAD = {
    "introducao": re.compile(r"^introdu[cç]"),
    "referencial": re.compile(
        r"(referencial|fundamenta[cç]|revis[aã]o (da|de) literatura|estado da arte|"
        r"trabalhos relacionados|marco te[oó]rico)"
    ),
    "metodologia": re.compile(
        r"(metodolog|m[eé]todo|materiais e m|procedimentos metodol|percurso metodol)"
    ),
    "resultados": re.compile(r"(resultado|an[aá]lise d|discuss[aã]o)"),
    "conclusao": re.compile(r"(conclus|considera[cç][oõ]es finais)"),
    "agradecimentos": re.compile(r"^agradecimento"),
    "dedicatoria": re.compile(r"^dedicat"),
    "apendice": re.compile(r"^ap[eê]ndice"),
    "anexo": re.compile(r"^anexo"),
    "glossario": re.compile(r"^gloss[aá]rio"),
    "siglas": re.compile(r"(abreviatura|siglas)"),
    "aprovacao": re.compile(r"folha de aprova"),
}


def detect_tipo(project: Project, forced: str = "") -> tuple[str, str]:
    """Retorna (tipo, motivo)."""
    forced = _norm(forced).replace("ç", "c").replace("ã", "a")
    if forced and forced != "auto":
        return forced, "informado por --tipo/config"
    dc = project.documentclass()
    cls, opts = (dc[0], dc[1]) if dc else ("", "")
    masked = "\n".join(s.masked for s in project.tex)
    if "article" in opts.split(","):
        return "artigo", f"classe {cls} com a opção 'article'"
    if cls in ("article", "scrartcl", "abntex2-artigo", "elsarticle", "IEEEtran", "llncs"):
        return "artigo", f"classe {cls}"
    if re.search(r"\\(imprimircapa|imprimirfolhaderosto|chapter\*?\s*\{)", masked):
        return "monografia", "usa capa/folha de rosto ou \\chapter"
    if cls in ("report", "book", "memoir", "abntex2"):
        return "monografia", f"classe {cls} sem a opção 'article'"
    return "artigo", "padrão (nenhum sinal de monografia)"


class CompletudeChecker(BaseChecker):
    name = "completude"
    title = "Completude do trabalho (artigo/monografia)"
    phase = 1  # roda depois dos demais para não duplicar o que o 'abnt' já apontou
    uses_network = True  # só para as orientações opcionais via IA online
    rules = (
        Rule(
            "COMP-TIPO-001",
            S.INFO,
            "Tipo de trabalho",
            "Tipo detectado (ou informado com --tipo) e a norma usada como referência: "
            "artigo → NBR 6022; monografia/TCC/dissertação/tese → NBR 14724.",
        ),
        Rule(
            "COMP-OBRIG-001",
            S.AVISO,
            "Elemento obrigatório ausente",
            "Elemento que a norma exige para o tipo de trabalho não foi encontrado no fonte.",
            f"{R6022}; {R14724}",
        ),
        Rule(
            "COMP-REC-001",
            S.SUGESTAO,
            "Elemento recomendado ausente",
            "Elemento não exigido pela norma, mas esperado pela maioria das bancas e dos "
            "periódicos (p. ex. seção de metodologia, lista de figuras quando há figuras).",
            heuristic=True,
        ),
        Rule(
            "COMP-META-001",
            S.AVISO,
            "Dado de identificação ausente",
            "Dado exigido na capa/folha de rosto (abnTeX2) não foi definido: título, autor, "
            "instituição, local, data, orientador, natureza do trabalho (\\preambulo).",
            f"{R14724}, 4.2.1",
        ),
        Rule(
            "COMP-IA-001",
            S.INFO,
            "Orientações para completar (IA online)",
            "Orientações curtas, geradas pelo Gemini com --ia-online, sobre o que escrever "
            "nos elementos ausentes. São sugestões para o autor redigir com as próprias "
            "palavras; o errei nunca escreve no artigo.",
            heuristic=True,
        ),
    )

    # ------------------------------------------------------------------
    def run(self, project: Project, ctx: RunContext) -> list[Finding]:
        forced = str(ctx.config.get("completude", "tipo", "auto") or "auto")
        tipo, motivo = detect_tipo(project, forced)
        if tipo not in TIPOS:
            tipo, motivo = "artigo", f"tipo '{forced}' desconhecido; usando artigo"
        mono = tipo in MONO_TIPOS
        main = project.main
        out: list[Finding] = [
            self.finding(
                "COMP-TIPO-001",
                f"trabalho tratado como {tipo} ({motivo}); norma de referência: "
                f"{R14724 if mono else R6022}",
                suggestion="se estiver errado, use --tipo artigo|monografia|tcc|dissertacao|tese",
            )
        ]
        present = self._present(project, mono)
        elementos = self._elementos(project, mono, present)
        abnt_ran = "abnt" in ctx.shared.get("checkers_ran", [])
        missing: list[Elemento] = []
        rows: list[Metric] = []
        for el in elementos:
            ok = present.get(el.key, False)
            rows.append(
                Metric(
                    el.nome,
                    "presente" if ok else "ausente",
                    None,
                    el.nivel,
                    f"{el.grupo} · {el.ref}",
                )
            )
            if ok:
                continue
            missing.append(el)
            if abnt_ran and el.key in COBERTOS_ABNT:
                continue
            if el.nivel == "opcional":
                continue
            code = "COMP-OBRIG-001" if el.nivel == "obrigatório" else "COMP-REC-001"
            out.append(
                self.finding(
                    code,
                    f"{el.nome} ({el.grupo}, {el.nivel}) não encontrado",
                    src=main,
                    start=0 if main else None,
                    suggestion=GUIA.get(el.key),
                    links=(),
                    evidence=(f"referência: {el.ref}",),
                )
            )
        if mono:
            out += self._meta(project)
        out += self._ia(project, ctx, tipo, [m for m in missing if m.nivel != "opcional"])

        g = MetricGroup(self.name, f"Completude — {tipo} ({R14724 if mono else R6022})")
        obrig = [e for e in elementos if e.nivel == "obrigatório"]
        done = sum(present.get(e.key, False) for e in obrig)
        g.metrics.append(
            Metric(
                "Obrigatórios presentes",
                f"{done}/{len(obrig)}",
                None,
                "todos",
                "elementos exigidos pela norma para este tipo",
            )
        )
        g.metrics += rows
        g.notes.append(
            "Detecção pelo fonte (comandos, ambientes e títulos de seção). Elementos gerados "
            "por macros próprias ou inseridos pelo periódico podem aparecer como ausentes."
        )
        ctx.add_metrics(g)
        return out

    # ------------------------------------------------------------------
    def _present(self, project: Project, mono: bool) -> dict[str, bool]:
        masked = "\n".join(s.masked for s in project.tex)
        heads = [_norm(p.text) for p in project.paragraphs(("heading",))]
        regions = {
            r.name for s in project.tex for r in project.clean(s).regions if r.kind == "abstract"
        }
        langs = {p.lang for p in project.paragraphs(("abstract",)) if p.word_count() >= 10}

        def cmd(*names: str) -> bool:
            return any(True for _ in project.commands(names, mandatory=0))

        def env(*names: str) -> bool:
            return any(re.search(r"\\begin\s*\{" + n + r"\*?\}", masked) for n in names)

        def head(key: str) -> bool:
            rx = HEAD[key]
            return any(rx.search(h) for h in heads)

        p: dict[str, bool] = {}
        p["titulo"] = cmd("title", "titulo")
        p["autor"] = cmd("author", "autor")
        p["afiliacao"] = bool(
            re.search(r"\\(thanks|affil|affiliation|institution|instituicao)\b", masked)
        ) or bool(re.search(r"\\author\s*(\[[^\]]*\])?\s*\{[^}]*\\footnote", masked))
        p["datas"] = bool(
            re.search(
                r"(submetido em|recebido em|aprovado em|aceito em|data de submiss|"
                r"received:|accepted:|\\received|\\accepted)",
                masked,
                re.I,
            )
        )
        p["resumo"] = "pt" in langs or bool(regions & {"resumo", "resumoumacoluna"})
        p["abstract"] = any(lg != "pt" for lg in langs) or "abstract" in regions
        p["palavras-chave"] = bool(
            re.search(r"(palavras[- ]chave|\\palavraschave|\\textbf\{palavras)", masked, re.I)
        )
        for k in (
            "introducao",
            "referencial",
            "metodologia",
            "resultados",
            "conclusao",
            "agradecimentos",
            "dedicatoria",
            "apendice",
            "anexo",
            "glossario",
        ):
            p[k] = head(k)
        p["agradecimentos"] = p["agradecimentos"] or env("agradecimentos")
        p["dedicatoria"] = p["dedicatoria"] or env("dedicatoria")
        p["epigrafe"] = env("epigrafe")
        p["apendice"] = p["apendice"] or env("apendicesenv") or cmd("apendices")
        p["anexo"] = p["anexo"] or env("anexosenv") or cmd("anexos")
        p["referencias"] = cmd("bibliography", "printbibliography") or env("thebibliography")
        p["capa"] = cmd("imprimircapa") or env("titlepage", "capa")
        p["folha-rosto"] = cmd("imprimirfolhaderosto")
        p["ficha"] = env("fichacatalografica")
        p["aprovacao"] = env("folhadeaprovacao") or head("aprovacao")
        p["sumario"] = cmd("tableofcontents", "sumario")
        p["lista-figuras"] = cmd("listoffigures", "listadeilustracoes")
        p["lista-tabelas"] = cmd("listoftables")
        p["siglas"] = env("siglas") or head("siglas") or cmd("printacronyms", "printglossary")
        p["_figuras"] = env("figure")
        p["_tabelas"] = env("table")
        # desenvolvimento: há seções/capítulos além de introdução e conclusão
        body_heads = [
            h
            for h in heads
            if not any(
                HEAD[k].search(h)
                for k in (
                    "introducao",
                    "conclusao",
                    "agradecimentos",
                    "apendice",
                    "anexo",
                    "glossario",
                )
            )
            and not re.search(r"(refer[eê]ncias|resumo|abstract|sum[aá]rio)", h)
        ]
        p["desenvolvimento"] = bool(body_heads)
        return p

    def _elementos(self, project: Project, mono: bool, present: dict[str, bool]) -> list[Elemento]:
        def E(key: str, nome: str, grupo: str, nivel: str, ref: str) -> Elemento:  # noqa: N802
            return Elemento(key, nome, grupo, nivel, ref)

        pre, txt, pos = "pré-textual", "textual", "pós-textual"
        ob, rec, op = "obrigatório", "recomendado", "opcional"
        if not mono:
            r = R6022
            return [
                E("titulo", "Título", pre, ob, f"{r}, 5.1.1"),
                E("autor", "Autoria", pre, ob, f"{r}, 5.1.2"),
                E("afiliacao", "Afiliação e e-mail do autor", pre, rec, f"{r}, 5.1.2"),
                E("resumo", "Resumo no idioma do documento", pre, ob, f"{r}, 5.1.3"),
                E("palavras-chave", "Palavras-chave", pre, ob, f"{r}, 5.1.3"),
                E("abstract", "Resumo em língua estrangeira", pre, rec, f"{r}, 5.1.4"),
                E("datas", "Datas de submissão e aprovação", pre, op, f"{r}, 5.1.5"),
                E("introducao", "Introdução", txt, ob, f"{r}, 5.2.1"),
                E("metodologia", "Metodologia / métodos", txt, rec, "IMRaD"),
                E("resultados", "Resultados e discussão", txt, rec, "IMRaD"),
                E("desenvolvimento", "Desenvolvimento", txt, ob, f"{r}, 5.2.2"),
                E("conclusao", "Considerações finais / conclusão", txt, ob, f"{r}, 5.2.3"),
                E("referencias", "Referências", pos, ob, f"{r}, 5.3.1"),
                E("agradecimentos", "Agradecimentos", pos, op, f"{r}, 5.3.5"),
                E("apendice", "Apêndice", pos, op, f"{r}, 5.3.3"),
                E("anexo", "Anexo", pos, op, f"{r}, 5.3.4"),
            ]
        r = R14724
        lf = rec if present.get("_figuras") else op
        lt = rec if present.get("_tabelas") else op
        return [
            E("capa", "Capa", "externo", ob, f"{r}, 4.1"),
            E("folha-rosto", "Folha de rosto", pre, ob, f"{r}, 4.2.1.1"),
            E("ficha", "Ficha catalográfica (verso da folha de rosto)", pre, ob, f"{r}, 4.2.1.1.2"),
            E("aprovacao", "Folha de aprovação", pre, ob, f"{r}, 4.2.1.3"),
            E("dedicatoria", "Dedicatória", pre, op, f"{r}, 4.2.1.4"),
            E("agradecimentos", "Agradecimentos", pre, op, f"{r}, 4.2.1.5"),
            E("epigrafe", "Epígrafe", pre, op, f"{r}, 4.2.1.6"),
            E("resumo", "Resumo na língua vernácula", pre, ob, f"{r}, 4.2.1.7"),
            E("palavras-chave", "Palavras-chave", pre, ob, f"{r}, 4.2.1.7"),
            E("abstract", "Resumo em língua estrangeira", pre, ob, f"{r}, 4.2.1.8"),
            E("lista-figuras", "Lista de ilustrações", pre, lf, f"{r}, 4.2.1.9"),
            E("lista-tabelas", "Lista de tabelas", pre, lt, f"{r}, 4.2.1.10"),
            E("siglas", "Lista de abreviaturas e siglas", pre, op, f"{r}, 4.2.1.11"),
            E("sumario", "Sumário", pre, ob, f"{r}, 4.2.1.13"),
            E("introducao", "Introdução", txt, ob, f"{r}, 4.2.2"),
            E("referencial", "Referencial teórico", txt, rec, "estrutura usual"),
            E("metodologia", "Metodologia", txt, rec, "estrutura usual"),
            E("resultados", "Resultados e discussão", txt, rec, "estrutura usual"),
            E("desenvolvimento", "Desenvolvimento", txt, ob, f"{r}, 4.2.2"),
            E("conclusao", "Conclusão", txt, ob, f"{r}, 4.2.2"),
            E("referencias", "Referências", pos, ob, f"{r}, 4.2.3.1"),
            E("glossario", "Glossário", pos, op, f"{r}, 4.2.3.2"),
            E("apendice", "Apêndice", pos, op, f"{r}, 4.2.3.3"),
            E("anexo", "Anexo", pos, op, f"{r}, 4.2.3.4"),
        ]

    def _meta(self, project: Project) -> list[Finding]:
        """Dados da capa/folha de rosto do abnTeX2 (só se a classe for abntex2)."""
        dc = project.documentclass()
        if not dc or dc[0] != "abntex2":
            return []
        out: list[Finding] = []
        campos = {
            "titulo": "título",
            "autor": "autor",
            "local": "local",
            "data": "data",
            "instituicao": "instituição",
            "orientador": "orientador",
            "preambulo": "natureza do trabalho (\\preambulo)",
            "tipotrabalho": "tipo do trabalho (\\tipotrabalho)",
        }
        defined: dict[str, str] = {}
        for _src, c in project.commands(tuple(campos)):
            if c.mandatory:
                defined[c.name] = c.mandatory[0].text.strip()
        for macro, label in campos.items():
            if not defined.get(macro):
                out.append(
                    self.finding(
                        "COMP-META-001",
                        f"{label} não definido (\\{macro}{{...}} no preâmbulo)",
                        src=project.main,
                        start=0 if project.main else None,
                    )
                )
        return out

    def _ia(
        self, project: Project, ctx: RunContext, tipo: str, missing: list[Elemento]
    ) -> list[Finding]:
        gem = ctx.shared.get("gemini")
        if gem is None or not missing:
            return []
        from errei.net.gemini import SCHEMA_COMPLETUDE, curto

        title = ""
        for _src, c in project.commands(("title", "titulo")):
            if c.mandatory:
                title = curto(c.mandatory[0].text, 30)
                break
        heads = [p.text.strip() for p in project.paragraphs(("heading",))][:30]
        ctx.progress(f"pedindo orientações ao Gemini para {len(missing)} elemento(s) ausente(s)")
        prompt = (
            f"Tipo de trabalho: {tipo}.\nTítulo: {title or '(sem título)'}\n"
            f"Seções existentes: {'; '.join(heads) or '(nenhuma)'}\n"
            f"Elementos ausentes: {'; '.join(e.nome for e in missing)}\n"
            "Para cada elemento ausente, dê de 2 a 4 orientações curtas, específicas para "
            "este tema, sobre O QUE o autor deve escrever. Não redija o texto."
        )
        data = gem.ask(prompt, SCHEMA_COMPLETUDE, what="título e títulos de seção")
        if not data:
            return [
                self.finding(
                    "COMP-IA-001",
                    "IA online indisponível; use as orientações fixas acima",
                    severity=S.INFO,
                )
            ]
        out: list[Finding] = []
        for item in data.get("orientacoes") or []:
            if not isinstance(item, dict):
                continue
            itens = tuple(str(i) for i in item.get("itens") or [] if i)
            if not itens:
                continue
            out.append(
                self.finding(
                    "COMP-IA-001",
                    f"o que escrever em '{curto(item.get('elemento', ''), 8)}' "
                    "(orientação de IA; redija com suas palavras)",
                    src=project.main,
                    start=0 if project.main else None,
                    evidence=tuple(f"• {i}" for i in itens),
                    confidence=None,
                )
            )
        return out
