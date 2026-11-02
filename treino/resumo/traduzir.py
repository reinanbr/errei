"""Traduz o CSAbstruct (Apache-2.0) para pt-BR com Helsinki-NLP/opus-mt-tc-big-en-pt.

Ordem: teste e validação inteiros (para medir em português) e depois resumos do
treino até ``MAX_TREINO`` frases. Cache incremental em dados/csabstruct/traducoes.jsonl:
pode ser interrompido e retomado.

Uso: python traduzir.py [threads] [max_frases_treino]
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pyarrow.parquet as pq
import torch
from transformers import MarianMTModel, MarianTokenizer

DADOS = Path(__file__).resolve().parent.parent / "dados" / "csabstruct"
OUT = DADOS / "traducoes.jsonl"
MODEL = "Helsinki-NLP/opus-mt-tc-big-en-pt"
PROGRESSO = DADOS / "progresso.txt"


def resumos(split: str) -> list[dict]:  # type: ignore[type-arg]
    return list(pq.read_table(DADOS / f"{split}.parquet").to_pylist())


def main() -> None:
    torch.set_num_threads(int(sys.argv[1]) if len(sys.argv) > 1 else 10)
    max_treino = int(sys.argv[2]) if len(sys.argv) > 2 else 6000
    textos: list[str] = []
    for split in ("test", "validation"):
        textos += [s for r in resumos(split) for s in r["sentences"]]
    n = 0
    for r in resumos("train"):
        if n >= max_treino:
            break
        textos += r["sentences"]
        n += len(r["sentences"])
    textos = list(dict.fromkeys(t.strip() for t in textos if t.strip()))
    feitos: set[str] = set()
    if OUT.exists():
        with OUT.open(encoding="utf-8") as fh:
            feitos = {json.loads(line)["en"] for line in fh if line.strip()}
    todo = [t for t in textos if t not in feitos]
    print(f"{len(feitos)} já traduzidas; {len(todo)} a traduzir", flush=True)
    tok = MarianTokenizer.from_pretrained(MODEL)
    model = MarianMTModel.from_pretrained(MODEL).eval()
    t0 = time.time()
    with OUT.open("a", encoding="utf-8") as fh:
        for i in range(0, len(todo), 32):
            lote = todo[i : i + 32]
            enc = tok([">>por<< " + t for t in lote], return_tensors="pt", padding=True,
                      truncation=True, max_length=256)
            with torch.no_grad():
                ger = model.generate(**enc, num_beams=1, max_new_tokens=256)
            for en, pt in zip(lote, tok.batch_decode(ger, skip_special_tokens=True), strict=True):
                fh.write(json.dumps({"en": en, "pt": pt}, ensure_ascii=False) + "\n")
            fh.flush()
            feito = i + len(lote)
            dt = time.time() - t0
            resto = (len(todo) - feito) / max(feito / dt, 1e-6)
            msg = (f"tradução: {feito}/{len(todo)} frases · {feito / dt:.1f}/s · "
                   f"faltam ~{resto / 60:.0f} min")
            PROGRESSO.write_text(msg + "\n")
            if (i // 32) % 10 == 0:
                print(msg, flush=True)
    print("tradução concluída", flush=True)


if __name__ == "__main__":
    main()
