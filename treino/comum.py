"""Utilidades compartilhadas pelos scripts de treino do modelo errei-cita."""

from __future__ import annotations

import json
import random
from collections.abc import Iterator
from pathlib import Path

BASE = Path(__file__).parent
DADOS = BASE / "dados"
SCIFACT = DADOS / "scifact" / "data"
LABELS = ["sustenta", "contradiz", "neutro"]
LABEL_ID = {k: i for i, k in enumerate(LABELS)}
SEED = 13


def read_jsonl(path: Path) -> Iterator[dict]:  # type: ignore[type-arg]
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def write_jsonl(path: Path, rows: list[dict]) -> None:  # type: ignore[type-arg]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def corpus() -> dict[int, dict]:  # type: ignore[type-arg]
    return {d["doc_id"]: d for d in read_jsonl(SCIFACT / "corpus.jsonl")}


def rng() -> random.Random:
    return random.Random(SEED)
