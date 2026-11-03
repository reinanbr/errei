"""Áreas com referência empírica: slug → filtro do OpenAlex e área de avaliação CAPES.

O filtro usa a classificação de tópicos do OpenAlex (campos e subcampos ASJC, atribuídos
por modelo; ver https://docs.openalex.org/api-entities/topics). O nome CAPES serve para
casar com ``--area`` do Qualis: ``--area educacao`` e ``--area "EDUCAÇÃO"`` são a mesma.
"""

from __future__ import annotations

from dataclasses import dataclass

from errei.text.segment import strip_accents


@dataclass(frozen=True, slots=True)
class Area:
    slug: str
    nome: str
    capes: str
    filtro: str  # filtro do OpenAlex (sem país, ano, tipo e OA)


AREAS: dict[str, Area] = {
    a.slug: a
    for a in (
        Area("educacao", "Educação", "EDUCAÇÃO", "primary_topic.subfield.id:3304"),
        Area(
            "saude-coletiva",
            "Saúde Coletiva",
            "SAÚDE COLETIVA",
            "primary_topic.subfield.id:2739",
        ),
        Area(
            "computacao",
            "Ciência da Computação",
            "CIÊNCIA DA COMPUTAÇÃO",
            "primary_topic.field.id:17",
        ),
        Area("psicologia", "Psicologia", "PSICOLOGIA", "primary_topic.field.id:32"),
        Area(
            "administracao",
            "Administração, Contabilidade e Turismo",
            "ADMINISTRAÇÃO PÚBLICA E DE EMPRESAS, CIÊNCIAS CONTÁBEIS E TURISMO",
            "primary_topic.field.id:14",
        ),
    )
}


def _key(s: str) -> str:
    return " ".join(strip_accents(s.lower()).replace("-", " ").split())


def resolve(nome: str | None) -> Area | None:
    """Aceita o slug (``saude-coletiva``) ou o nome CAPES (``SAÚDE COLETIVA``)."""
    if not nome:
        return None
    k = _key(nome)
    for a in AREAS.values():
        if k in (_key(a.slug), _key(a.capes), _key(a.nome)):
            return a
    return None
