"""Ajusta os achados a um trabalho em ``.docx``/``.pdf``.

Os verificadores falam de LaTeX e de ``.bib`` (chaves, comandos, campos). Num documento
digitado, isso não faz sentido para o autor: as chaves viram a forma como a obra é citada
("SILVA, 2020"), ".bib" vira "lista de referências", e as sugestões em LaTeX são trocadas
pelo equivalente no editor de texto ou removidas. Regras que só valem para o ``.bib``
gerado pelo errei (sintaxe, campos que o leitor não conseguiu separar) são descartadas.
"""

from __future__ import annotations

import dataclasses
import re
from typing import TYPE_CHECKING

from errei.model import Finding

if TYPE_CHECKING:
    from errei.project import Project

# não se aplicam ao documento: estilo do pacote, .bib gerado pelo errei, campos que o
# leitor de referências pode não ter separado, citação "digitada" (no .docx tudo é digitado)
DESCARTAR = {
    "ABNT-STYLE-001",
    "ABNT-STYLE-002",
    "ABNT-CIT-004",
    "ABNT-CIT-006",
    "ABNT-REF-001",
    "ABNT-REF-002",
    "ABNT-REF-003",
    "ABNT-REF-005",
    "REFS-FIELD-001",
    "REFS-DOI-003",
    "REFS-BIB-002",
    "REFS-BIB-003",
    "REFS-BIB-004",
    "COMP-META-001",
    "APUD-CONS-001",  # "consultada digitada fora do .bib": no documento, tudo é digitado
}
SUGESTAO = {
    "ABNT-RESUMO-001": "inclua uma seção 'Resumo' antes da introdução",
    "ABNT-CIT-002": "destaque a citação: recuo de 4 cm, fonte menor, espaço simples, sem aspas",
    "ABNT-CIT-005": "indique a página: (SOBRENOME, ano, p. N)",
    "ABNT-REF-004": "acrescente 'Acesso em: 1 jan. 2026.' depois do endereço",
    "ABNT-CIT-001": "escreva (SOBRENOME, ano apud SOBRENOME, ano), com a consultada na lista",
    "ABNT-ESTR-003": "inclua a seção 'Referências' no fim do trabalho",
}
MENSAGEM = {
    "REFS-NOBIB-001": "há citações, mas a lista de referências não foi encontrada (seção "
    "'Referências')",
    "ABNT-ESTR-003": "nenhuma lista de referências (seção 'Referências')",
}
_CITE = re.compile(r"\\(?:cite\w*|apud\w*|textapud)\*?(?:\[[^\]]*\])*\{([^}]*)\}(?:\{([^}]*)\})?")
_LATEX = re.compile(r"\\[A-Za-z]+")
_BIB = [
    (re.compile(r"\bno \.bib\b"), "na lista de referências"),
    (re.compile(r"\bdo \.bib\b"), "da lista de referências"),
    (re.compile(r"\bao \.bib\b"), "à lista de referências"),
    (re.compile(r"\bnum \.bib\b"), "na lista de referências"),
    (re.compile(r"\bentrada \.bib\b"), "referência"),
    (re.compile(r"(?<!\w)\.bib\b"), "lista de referências"),
    (re.compile(r"\bna classe\b"), "no documento"),
]


class _Rotulos:
    def __init__(self, project: Project) -> None:
        info = project.documento
        self.rot: dict[str, str] = dict(getattr(info, "rotulos", {}) or {})
        self.sem: dict[str, str] = dict(getattr(info, "sem_referencia", {}) or {})
        chaves = sorted({*self.rot, *self.sem}, key=len, reverse=True)
        self.re = (
            re.compile(r"'(" + "|".join(re.escape(k) for k in chaves) + r")'") if chaves else None
        )

    def de(self, chave: str) -> str:
        return self.rot.get(chave) or self.sem.get(chave) or chave

    def texto(self, s: str | None) -> str | None:
        if not s:
            return s

        def cite(m: re.Match[str]) -> str:
            chaves = [k.strip() for g in m.groups() if g for k in g.split(",") if k.strip()]
            return "(" + "; ".join(self.de(k) for k in chaves) + ")"

        s = _CITE.sub(cite, s)
        if self.re is not None:
            s = self.re.sub(lambda m: f"'{self.de(m.group(1))}'", s)
        for rx, novo in _BIB:
            s = rx.sub(novo, s)
        return s


def adaptar(findings: list[Finding], project: Project) -> list[Finding]:
    if project.documento is None:
        return findings
    r = _Rotulos(project)
    out: list[Finding] = []
    for f in findings:
        if f.code in DESCARTAR:
            continue
        msg = MENSAGEM.get(f.code) or r.texto(f.message) or f.message
        if f.code == "REFS-CITE-001":
            m = re.search(r"\{([^}]*)\}", f.message)
            chave = m.group(1) if m else ""
            msg = f"citação '{r.de(chave)}' sem entrada na lista de referências"
        elif f.code == "REFS-BIB-001":
            m = re.search(r"'([^']*)'", f.message)
            msg = f"referência '{r.de(m.group(1)) if m else ''}' nunca citada no texto"
        sug = SUGESTAO.get(f.code) or r.texto(f.suggestion)
        if f.code == "REFS-CITE-001" and f.suggestion:
            m = re.search(r"'([^']*)'", f.suggestion)
            sug = f"na lista há '{r.de(m.group(1))}'; confira autor e ano" if m else None
        if sug and _LATEX.search(sug):
            sug = None  # sugestão em LaTeX sem equivalente no editor de texto
        ev = tuple(x for x in (r.texto(e) for e in f.evidence) if x)
        out.append(dataclasses.replace(f, message=msg, suggestion=sug, evidence=ev))
    return out
