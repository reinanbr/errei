"""Registro global de regras (usado por ``errei explain`` e pela severidade padrão)."""

from __future__ import annotations

from errei.model import Rule, Severity

_RULES: dict[str, Rule] = {}


def register(*rules: Rule) -> None:
    for r in rules:
        _RULES[r.code] = r


def get(code: str) -> Rule | None:
    return _RULES.get(code.upper())


def all_rules() -> list[Rule]:
    return sorted(_RULES.values(), key=lambda r: r.code)


S = Severity

CORE_RULES = (
    Rule(
        "CORE-CHECKER-001",
        S.AVISO,
        "Verificador falhou",
        "Um verificador lançou uma exceção. Os demais continuaram; o resultado está incompleto.",
    ),
    Rule(
        "CORE-PLUGIN-001",
        S.INFO,
        "Plugin não carregado",
        "Um plugin registrado no grupo de entry points 'errei.checkers' não pôde ser carregado.",
    ),
    Rule(
        "CORE-DEP-001",
        S.INFO,
        "Dependência opcional ausente",
        "Parte de um verificador foi pulada porque falta um extra opcional ou um programa externo.",
    ),
    Rule(
        "CORE-NET-001",
        S.INFO,
        "Fonte online indisponível",
        "Uma fonte online falhou repetidamente e foi desativada nesta execução. "
        "Os resultados que dependiam dela estão incompletos.",
    ),
    Rule(
        "CORE-PROJ-001",
        S.INFO,
        "Observação sobre o projeto",
        "Observação da descoberta de arquivos (ex.: vários .tex principais, codificação).",
    ),
)
register(*CORE_RULES)
