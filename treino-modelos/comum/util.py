"""Utilidades comuns: caminhos, config TOML, JSONL, frases e divisão por grupo."""

from __future__ import annotations

import hashlib
import json
import random
import re
import unicodedata
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]

RAIZ = Path(__file__).resolve().parents[2]  # raiz do repositório
PASTA = RAIZ / "treino-modelos"
CONFIG_MODELOS = PASTA / "config" / "modelos.toml"
CONFIG_BANCO = PASTA / "config" / "banco.toml"


def carregar_toml(p: str | Path | None, padrao: Path) -> dict[str, Any]:
    arq = Path(p) if p else padrao
    with arq.open("rb") as fh:
        cfg: dict[str, Any] = tomllib.load(fh)
    cfg["_arquivo"] = str(arq)
    return cfg


def caminho(rel: str | Path) -> Path:
    p = Path(rel)
    return p if p.is_absolute() else RAIZ / p


def ler_jsonl(p: Path) -> Iterator[dict[str, Any]]:
    with p.open(encoding="utf-8") as fh:
        for ln in fh:
            if ln.strip():
                yield json.loads(ln)


def gravar_jsonl(p: Path, rows: Iterable[dict[str, Any]]) -> int:
    p.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with p.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
            n += 1
    return n


_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(\[À-Ý])")


def frases(texto: str, minimo: int = 20) -> list[str]:
    """Mesma divisão de frases do errei (citecheck/resumocheck)."""
    t = " ".join(str(texto or "").split())
    out = [s.strip() for s in _SPLIT.split(t) if len(s.strip()) >= minimo]
    return out or ([t] if t else [])


def cortar(texto: str, n: int) -> str:
    t = " ".join(str(texto or "").split())
    if len(t) <= n:
        return t
    corte = t[:n]
    fim = max(corte.rfind(". "), corte.rfind("! "), corte.rfind("? "))
    return corte[: fim + 1] if fim > n // 3 else corte


def sem_acento(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def norm(s: str) -> str:
    """Minúsculas, sem acento e só letras/números separados por um espaço."""
    return " ".join(re.sub(r"[^\w]+", " ", sem_acento(str(s or "")).lower()).split())


def normalizar_issn(s: str) -> str:
    """'0028-0836' → '00280836'; '' se não parece ISSN."""
    t = re.sub(r"[^0-9Xx]", "", str(s or "")).upper()
    return t if len(t) == 8 else ""


def fracao(chave: str, semente: int) -> float:
    """Número estável em [0, 1) para a chave (mesma divisão em toda execução)."""
    h = hashlib.sha256(f"{semente}:{chave}".encode()).hexdigest()[:12]
    return int(h, 16) / float(16**12)


def dividir(
    rows: list[dict[str, Any]], semente: int, validacao: float, teste: float
) -> dict[str, list[dict[str, Any]]]:
    """Divide por ``grupo`` (a obra): nada de uma obra vaza entre treino, validação e teste."""
    out: dict[str, list[dict[str, Any]]] = {"treino": [], "validacao": [], "teste": []}
    for r in rows:
        f = fracao(str(r.get("grupo") or json.dumps(r, sort_keys=True)), semente)
        nome = "teste" if f < teste else ("validacao" if f < teste + validacao else "treino")
        out[nome].append(r)
    rnd = random.Random(semente)
    for v in out.values():
        rnd.shuffle(v)
    return out
