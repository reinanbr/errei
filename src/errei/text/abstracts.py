"""Localiza resumo/abstract e palavras-chave no texto limpo."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from errei.latex.extract import Paragraph

if TYPE_CHECKING:
    from errei.project import Project

KW_RE = re.compile(
    r"(?P<label>palavras?[- ]chaves?|key[- ]?words?|palabras? clave)\s*[:.]\s*(?P<body>.*)",
    re.IGNORECASE | re.DOTALL,
)
HEADINGS = {
    "resumo": "pt",
    "abstract": "en",
    "resumen": "es",
    "résumé": "fr",
}


@dataclass(slots=True)
class AbstractBlock:
    lang: str
    paragraphs: list[Paragraph] = field(default_factory=list)  # sem a linha de palavras-chave
    keywords: Paragraph | None = None
    kw_body_start: int = 0  # offset (relativo ao parágrafo) do início das palavras-chave
    kw_label: str = ""

    @property
    def text(self) -> str:
        return "\n\n".join(p.text for p in self.paragraphs)

    @property
    def keywords_text(self) -> str:
        return self.keywords.text[self.kw_body_start :] if self.keywords else ""


def _attach(block: AbstractBlock, p: Paragraph) -> None:
    m = KW_RE.match(p.text)
    if m:
        block.keywords = p
        block.kw_body_start = m.start("body")
        block.kw_label = m.group("label")
    else:
        block.paragraphs.append(p)


def find_abstracts(project: Project) -> list[AbstractBlock]:
    blocks: list[AbstractBlock] = []
    current: AbstractBlock | None = None
    heading_mode = False
    for p in project.paragraphs():
        if p.kind == "abstract":
            heading_mode = False
            if (
                current is None
                or current.lang != p.lang
                or (current.paragraphs and current.paragraphs[-1].clean is not p.clean)
            ):
                current = AbstractBlock(p.lang)
                blocks.append(current)
            _attach(current, p)
            continue
        if p.kind == "heading":
            title = p.text.strip().strip(":").lower()
            if title in HEADINGS:
                current = AbstractBlock(HEADINGS[title])
                blocks.append(current)
                heading_mode = True
                continue
            current = None
            heading_mode = False
            continue
        if heading_mode and current is not None and p.kind == "body":
            _attach(current, p)
            continue
        if current is not None and current.keywords is None and KW_RE.match(p.text):
            # palavras-chave logo após o ambiente de resumo
            _attach(current, p)
            continue
        current = None
        heading_mode = False
    # blocos que só contêm o rótulo (p.ex. \section*{Resumo} vazio) são descartados
    return [b for b in blocks if b.paragraphs or b.keywords]


def split_keywords(body: str) -> tuple[list[str], str]:
    """Divide palavras-chave e devolve (itens, separador predominante)."""
    body = body.strip()
    if ";" in body:
        sep = ";"
    elif re.search(r"\.\s", body):
        sep = "."
    elif "," in body:
        sep = ","
    else:
        sep = ""
    raw = (
        re.split(r"\s*[;]\s*", body)
        if sep == ";"
        else (
            re.split(r"\.\s+", body)
            if sep == "."
            else re.split(r"\s*,\s*", body)
            if sep
            else [body]
        )
    )
    items = [i.strip().rstrip(".").strip() for i in raw if i.strip().rstrip(".").strip()]
    return items, sep
