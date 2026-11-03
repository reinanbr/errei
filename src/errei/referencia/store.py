"""Onde ficam as referências instaladas (``~/.local/share/errei/referencias/<area>.json``)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

SCHEMA = 1


def pasta() -> Path:
    env = os.environ.get("ERREI_REFERENCIA_DIR")
    if env:
        return Path(env).expanduser()
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "errei" / "referencias"


def arquivo(slug: str) -> Path:
    return pasta() / f"{slug}.json"


def carregar(slug: str) -> dict[str, Any] | None:
    f = arquivo(slug)
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        return None
    return data


def salvar(slug: str, escopo: str, conteudo: dict[str, Any], nome: str) -> Path:
    """Grava/atualiza um escopo (brasil|mundo) da área, mantendo o outro."""
    data = carregar(slug) or {"schema": SCHEMA, "area": slug, "nome": nome, "escopos": {}}
    data["escopos"][escopo] = conteudo
    f = arquivo(slug)
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(f)
    return f


def instaladas() -> list[str]:
    d = pasta()
    return sorted(p.stem for p in d.glob("*.json")) if d.is_dir() else []


def grupo(escopo: dict[str, Any], idioma: str = "pt", minimo: int = 30) -> tuple[str, Any]:
    """Grupo usado na comparação: o do idioma, se tiver n suficiente; senão, todos."""
    grupos = escopo.get("grupos", {})
    chave = f"artigo|{idioma}"
    if chave in grupos and grupos[chave].get("n", 0) >= minimo:
        return chave, grupos[chave]
    if "artigo|todos" in grupos:
        return "artigo|todos", grupos["artigo|todos"]
    return chave, grupos.get(chave, {"n": 0, "medidas": {}})
