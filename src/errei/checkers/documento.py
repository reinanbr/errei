"""Verificador do documento ``.docx``/``.pdf``: o que foi lido e a lista de referências.

O LaTeX resolve sozinho a ordem e a formatação da lista de referências; num documento
digitado, isso fica com o autor. Aqui ficam as regras que só fazem sentido nesse caso:
entradas que não seguem um formato reconhecível, ordem alfabética (sistema autor-data) e,
no PDF, referências cruzadas não resolvidas ("??") e problemas de extração.
"""

from __future__ import annotations

import itertools
import re
from typing import TYPE_CHECKING, ClassVar

from errei.checkers.base import BaseChecker, RunContext
from errei.model import Finding, Location, Rule
from errei.model import Severity as S

if TYPE_CHECKING:
    from errei.project import Project

R6023 = "ABNT NBR 6023:2018"


def _chave_ordem(sobrenome: str) -> str:
    import unicodedata

    s = unicodedata.normalize("NFKD", sobrenome.lower())
    return "".join(c for c in s if c.isalpha() or c == " ").strip()


class DocumentoChecker(BaseChecker):
    name = "documento"
    title = "Leitura do documento (.docx/.pdf)"
    formatos: ClassVar[tuple[str, ...]] = ("docx", "pdf")
    rules = (
        Rule(
            "DOC-LEITURA-001",
            S.INFO,
            "Documento lido",
            "O .docx/.pdf foi convertido em texto para a auditoria, sem alterar o arquivo. "
            "Informa quantos parágrafos, títulos, referências e citações foram reconhecidos e "
            "o que não é analisado (tabelas, notas de rodapé, equações, caixas de texto).",
        ),
        Rule(
            "DOC-LEITURA-002",
            S.AVISO,
            "Leitura do PDF com limitações",
            "O texto extraído do PDF pode misturar colunas, colar palavras de linhas "
            "justificadas ou faltar em páginas que são imagem. Os achados desses trechos são "
            "menos confiáveis; se possível, audite o .docx ou o fonte LaTeX.",
            heuristic=True,
        ),
        Rule(
            "DOC-REF-001",
            S.AVISO,
            "Referência não reconhecida",
            "A entrada da lista de referências não traz, numa forma reconhecível, autor, "
            "título e ano. Confira se ela segue a NBR 6023 (SOBRENOME, Prenome. Título. "
            "Local: Editora, ano.) ou outro estilo consistente.",
            R6023,
            heuristic=True,
        ),
        Rule(
            "DOC-REF-002",
            S.AVISO,
            "Lista de referências fora da ordem alfabética",
            "No sistema autor-data, as referências são ordenadas alfabeticamente pelo "
            "sobrenome do primeiro autor (ou pela entidade ou título).",
            f"{R6023}, 9.1",
        ),
        Rule(
            "DOC-CIT-001",
            S.ERRO,
            "Referência cruzada não resolvida",
            "'??' no texto do PDF: o LaTeX não resolveu uma citação ou referência cruzada "
            "(\\cite, \\ref) quando o PDF foi gerado. Corrija a chave e compile de novo.",
        ),
    )

    def run(self, project: Project, ctx: RunContext) -> list[Finding]:
        info = project.documento
        if info is None:
            return []
        doc = info.documento
        geral = Location(doc.caminho, 0, unit=doc.unidade)
        out: list[Finding] = []
        refs = info.referencias
        reconhecidas = sum(1 for r in refs if r.reconhecida)
        ev = [
            f"{len(doc.blocos)} parágrafos lidos"
            + (f" em {doc.paginas} páginas" if doc.formato == "pdf" else ""),
            f"localização dos achados: {'página' if doc.formato == 'pdf' else 'nº do parágrafo'}",
        ]
        nao = {**doc.ignorado}
        for k, v in info.pulados.items():
            nao[k] = max(nao.get(k, 0), v)
        if nao:
            ev.append("não analisado: " + ", ".join(f"{v} {k}" for k, v in sorted(nao.items())))
        if doc.formato == "docx":
            ev.append(
                "comentários, cabeçalhos, rodapés e o texto apagado em alterações "
                "controladas não são lidos"
            )
        out.append(
            self.finding(
                "DOC-LEITURA-001",
                f"{doc.caminho.name}: {info.titulos} título(s), {len(refs)} referência(s) "
                f"({reconhecidas} reconhecida(s)), {info.citacoes} citação(ões) ligada(s)",
                location=geral,
                evidence=tuple(ev),
            )
        )
        for aviso in doc.avisos:
            if doc.formato == "pdf":
                out.append(self.finding("DOC-LEITURA-002", aviso, location=geral))
        out += self._referencias(project)
        if doc.formato == "pdf":
            out += self._interrogacoes(project)
        return out

    def _referencias(self, project: Project) -> list[Finding]:
        info = project.documento
        refs = info.referencias
        entradas = {e.key: e for b in project.bibs for e in b.entries}
        out: list[Finding] = []

        def loc(chave: str) -> Location | None:
            e = entradas.get(chave)
            return e.source.location(e.start) if e is not None else None

        for r in refs:
            if r.reconhecida:
                continue
            falta = [
                n
                for n, ok in (("autor", r.autores), ("título", r.titulo), ("ano", r.ano))
                if not ok
            ]
            out.append(
                self.finding(
                    "DOC-REF-001",
                    f"referência sem {', '.join(falta)} reconhecível",
                    location=loc(r.chave),
                    excerpt=r.texto[:160],
                    suggestion="SOBRENOME, Prenome. Título: subtítulo. Local: Editora, ano.",
                )
            )
        numerada = sum(1 for r in refs if r.numero is not None) >= max(2, len(refs) // 2)
        if numerada or len(refs) < 3:
            return out
        ordem = [r for r in refs if r.sobrenome and r.reconhecida]
        erros = 0
        for ant, r in itertools.pairwise(ordem):
            a, b = _chave_ordem(ant.sobrenome), _chave_ordem(r.sobrenome)
            if a and b and b < a:
                out.append(
                    self.finding(
                        "DOC-REF-002",
                        f"'{r.rotulo()}' está depois de '{ant.rotulo()}' (ordem alfabética: "
                        "sobrenome do primeiro autor)",
                        location=loc(r.chave),
                        excerpt=r.texto[:160],
                    )
                )
                erros += 1
                if erros >= 3:
                    break
        return out

    def _interrogacoes(self, project: Project) -> list[Finding]:
        out: list[Finding] = []
        for p in project.paragraphs(("body", "item", "caption", "quote")):
            for m in re.finditer(r"\?\?", p.text):
                out.append(
                    self.finding(
                        "DOC-CIT-001",
                        "'??' no texto: citação ou referência cruzada não resolvida",
                        location=p.location(m.start(), m.end()),
                        excerpt=p.text[max(0, m.start() - 50) : m.end() + 30],
                    )
                )
        return out[:20]
