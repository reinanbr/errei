"""Bloco de texto fixo dos achados ``LIT-*`` (igual no terminal, md, json e pdf)."""

from __future__ import annotations

from errei.model import Finding

# achados de uma linha: cabeçalho + mensagem
LINHA_UNICA = frozenset({"LIT-NONE-001", "LIT-LANG-001"})


def is_lit(f: Finding) -> bool:
    return f.code.startswith("LIT-")


def onde(f: Finding) -> str:
    loc = f.location
    if loc is None:
        return "(projeto)"
    col = loc.column if loc.column is not None else 1
    return f"{loc.file.as_posix()}:{loc.line}:{col}"


def bloco(f: Finding) -> list[str]:
    """Linhas do bloco, na forma ``LIT-SUG-001  sugestão  arquivo.tex:42:1`` + campos."""
    head = f"{f.code}  {f.severity.value}  {onde(f)}"
    if f.code in LINHA_UNICA or not f.evidence:
        return [f"{head}  {f.message}"]
    return [head, *f.evidence]
