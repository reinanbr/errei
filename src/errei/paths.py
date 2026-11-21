"""Pastas do usuário (XDG): configuração, cache e dados."""

from __future__ import annotations

import os
from pathlib import Path


def _xdg(var: str, padrao: Path) -> Path:
    return Path(os.environ.get(var) or padrao) / "errei"


def config_dir() -> Path:
    """``~/.config/errei``, onde fica o ``config.toml`` do usuário."""
    return _xdg("XDG_CONFIG_HOME", Path.home() / ".config")


def cache_dir() -> Path:
    """``~/.cache/errei``: cache das consultas online."""
    return _xdg("XDG_CACHE_HOME", Path.home() / ".cache")


def data_dir() -> Path:
    """``~/.local/share/errei``: modelos locais e referências do usuário."""
    return _xdg("XDG_DATA_HOME", Path.home() / ".local" / "share")
