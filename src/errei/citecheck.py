"""Modelo errei-cita: a fonte sustenta, contradiz ou não permite afirmar a frase que a cita?

Cross-encoder multilíngue (fine-tuning local; ver ``treino/``). A frase do artigo
(pt-BR) é comparada com cada frase e janela de 2 frases do resumo da fonte
(geralmente em inglês). O resultado é um indicador com o trecho da fonte que
mais sustenta ou contradiz a afirmação, nunca um veredito sobre a obra.

Requer o extra ``errei[modelo]`` (torch + transformers) e os pesos instalados em
``$ERREI_MODEL_DIR`` ou ``~/.local/share/errei/modelos/errei-cita-v1``.
"""

from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MODEL_NAME = "errei-cita-v1"
# v2 (treino-gpu/): sem dados NC; quando instalado, é preferido ao v1
MODEL_V2 = "errei-cita-v2"
_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(\[À-Ý])")
_lock = threading.Lock()
_cache: dict[str, Any] = {}


def dir_de(nome: str) -> Path:
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "errei" / "modelos" / nome


def model_dir() -> Path:
    """``$ERREI_MODEL_DIR``, senão o errei-cita-v2 instalado, senão o v1."""
    env = os.environ.get("ERREI_MODEL_DIR")
    if env:
        return Path(env).expanduser()
    v2 = dir_de(MODEL_V2)
    if (v2 / "config.json").is_file():
        return v2
    return dir_de(MODEL_NAME)


def unavailable_reason() -> str | None:
    if os.environ.get("ERREI_NO_MODEL"):
        return "modelo desativado (ERREI_NO_MODEL)"
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
    except ModuleNotFoundError:
        return "instale o extra: pip install 'errei[modelo]'"
    d = model_dir()
    if not (d / "config.json").is_file():
        return f"modelo {d.name} não instalado em {d} (veja 'errei modelo info')"
    return None


def frases(texto: str) -> list[str]:
    out = [s.strip() for s in _SPLIT.split(" ".join(texto.split())) if len(s.strip()) > 20]
    return out or ([texto.strip()] if texto.strip() else [])


@dataclass(frozen=True, slots=True)
class Julgamento:
    veredito: str  # sustenta | contradiz | neutro
    sustenta: float
    contradiz: float
    evidencia: str  # trecho da fonte mais relevante para o veredito

    @property
    def score(self) -> float:
        return {"sustenta": self.sustenta, "contradiz": self.contradiz}.get(
            self.veredito, 1 - max(self.sustenta, self.contradiz)
        )


class Classificador:
    """Carrega o cross-encoder e julga pares (afirmação, trecho da fonte)."""

    def __init__(self, caminho: str | Path, max_len: int = 192) -> None:
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        self._torch = torch
        self.caminho = Path(caminho)
        self.tok = AutoTokenizer.from_pretrained(str(caminho))
        self.model = AutoModelForSequenceClassification.from_pretrained(str(caminho)).eval()
        self.max_len = max_len
        id2 = {int(k): str(v).lower() for k, v in self.model.config.id2label.items()}
        alias = {"entailment": "sustenta", "contradiction": "contradiz", "neutral": "neutro"}
        self.labels = [alias.get(id2[i], id2[i]) for i in range(len(id2))]
        lim = self.caminho / "errei_limiares.json"
        self.limiares = {"sustenta": 0.5, "contradiz": 0.5}
        if lim.is_file():
            data = json.loads(lim.read_text(encoding="utf-8"))
            self.limiares = {
                "sustenta": float(data["sustenta"]),
                "contradiz": float(data["contradiz"]),
            }

    def probs(self, pares: list[tuple[str, str]], lote: int = 32) -> list[dict[str, float]]:
        torch = self._torch
        out: list[dict[str, float]] = []
        with torch.no_grad():
            for i in range(0, len(pares), lote):
                chunk = pares[i : i + lote]
                # convenção NLI: premissa = trecho da fonte; hipótese = afirmação do artigo
                enc = self.tok(
                    [b for _, b in chunk],
                    [a for a, _ in chunk],
                    truncation=True,
                    max_length=self.max_len,
                    padding=True,
                    return_tensors="pt",
                )
                p = torch.softmax(self.model(**enc).logits, dim=-1)
                for row in p.tolist():
                    out.append(dict(zip(self.labels, row, strict=True)))
        return out

    def julgar_resumo(self, afirmacao: str, resumo_frases: list[str]) -> dict[str, Any]:
        janelas = list(resumo_frases)
        janelas += [
            resumo_frases[i] + " " + resumo_frases[i + 1] for i in range(len(resumo_frases) - 1)
        ]
        if not janelas:
            return {"sustenta": 0.0, "contradiz": 0.0, "evid_s": "", "evid_c": ""}
        ps = self.probs([(afirmacao, j) for j in janelas])
        i_s = max(range(len(ps)), key=lambda i: ps[i]["sustenta"])
        i_c = max(range(len(ps)), key=lambda i: ps[i]["contradiz"])
        return {
            "sustenta": ps[i_s]["sustenta"],
            "contradiz": ps[i_c]["contradiz"],
            "evid_s": janelas[i_s],
            "evid_c": janelas[i_c],
        }

    def julgar(self, afirmacao: str, resumo: str) -> Julgamento:
        r = self.julgar_resumo(afirmacao, frases(resumo))
        s, c = r["sustenta"], r["contradiz"]
        if c >= self.limiares["contradiz"] and c >= s:
            return Julgamento("contradiz", s, c, r["evid_c"])
        if s >= self.limiares["sustenta"]:
            return Julgamento("sustenta", s, c, r["evid_s"])
        return Julgamento("neutro", s, c, r["evid_s"])


def carregar() -> Classificador:
    """Instância compartilhada (o modelo é carregado uma vez por processo)."""
    with _lock:
        d = str(model_dir())
        if d not in _cache:
            _cache[d] = Classificador(d)
        clf: Classificador = _cache[d]
        return clf
