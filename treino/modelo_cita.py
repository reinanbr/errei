"""Reexporta a inferência do pacote (treino e uso real compartilham o mesmo código)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from errei.citecheck import Classificador, frases  # noqa: E402

__all__ = ["Classificador", "frases"]
