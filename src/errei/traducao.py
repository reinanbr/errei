"""Tradução local pt→en das afirmações, só para montar a consulta em inglês.

Opcional (extra ``errei[traducao]``). Modelo: ``Helsinki-NLP/opus-mt-ROMANCE-en``
(Apache-2.0), instalado em ``$ERREI_TRADUCAO_DIR`` ou
``~/.local/share/errei/modelos/opus-mt-ROMANCE-en``. Nunca baixa nada sozinho e
nunca vai ao relatório como citação: serve só para buscar.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any, Protocol

MODEL_NAME = "opus-mt-ROMANCE-en"
MODEL_REPO = "Helsinki-NLP/opus-mt-ROMANCE-en"
MODEL_LICENSE = "Apache-2.0"
# revisão fixa no Hugging Face (2023-08-16) e sha256 dos pesos (LFS), conferidos no download
MODEL_REVISION = "e9ca9975e3972afd80732f08ce01d3a1339f47f8"
MODEL_FILES = (
    "config.json",
    "generation_config.json",
    "pytorch_model.bin",
    "source.spm",
    "target.spm",
    "tokenizer_config.json",
    "vocab.json",
    "README.md",
)
MODEL_SHA256 = {
    "pytorch_model.bin": "9d77bbbd43a214959e027ffc8713fbe31f8609d14827fba645f1361ca20a6f3a",
}
_lock = threading.Lock()
_cache: dict[str, Any] = {}


class Tradutor(Protocol):
    def traduzir(self, textos: list[str]) -> list[str]: ...


def model_dir() -> Path:
    env = os.environ.get("ERREI_TRADUCAO_DIR")
    if env:
        return Path(env).expanduser()
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "errei" / "modelos" / MODEL_NAME


def unavailable_reason() -> str | None:
    if os.environ.get("ERREI_NO_MODEL"):
        return "modelos desativados (ERREI_NO_MODEL)"
    try:
        import sentencepiece  # noqa: F401
        import transformers  # noqa: F401
    except ModuleNotFoundError:
        return "instale o extra: pip install 'errei[traducao]'"
    if not (model_dir() / "config.json").is_file():
        return (
            f"tradutor {MODEL_NAME} não instalado em {model_dir()} "
            f"(errei modelo baixar --nome {MODEL_NAME})"
        )
    return None


class Marian:
    def __init__(self, caminho: Path) -> None:
        import torch
        from transformers import MarianMTModel, MarianTokenizer

        self._torch = torch
        self.tok = MarianTokenizer.from_pretrained(str(caminho))
        self.model = MarianMTModel.from_pretrained(str(caminho)).eval()

    def traduzir(self, textos: list[str]) -> list[str]:
        if not textos:
            return []
        with self._torch.no_grad():
            enc = self.tok(textos, return_tensors="pt", padding=True, truncation=True)
            out = self.model.generate(**enc, max_new_tokens=160)
        return [self.tok.decode(o, skip_special_tokens=True) for o in out]


def carregar() -> Tradutor | None:
    """Tradutor compartilhado, ou ``None`` se indisponível (a busca segue só em pt)."""
    if unavailable_reason() is not None:
        return None
    with _lock:
        d = str(model_dir())
        if d not in _cache:
            try:
                _cache[d] = Marian(Path(d))
            except Exception:
                _cache[d] = None
        tr: Tradutor | None = _cache[d]
        return tr
