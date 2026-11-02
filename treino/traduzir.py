"""Traduz afirmações (e parte das frases de evidência) do SciFact para pt-BR.

Modelo: Helsinki-NLP/opus-mt-tc-big-en-pt (CC BY 4.0). Saída: dados/traducoes.jsonl
(texto em inglês -> tradução), com cache incremental.
"""

from __future__ import annotations

import json
import sys
import time

import torch
from transformers import MarianMTModel, MarianTokenizer

from comum import DADOS, SCIFACT, corpus, read_jsonl, rng

OUT = DADOS / "traducoes.jsonl"
MODEL = "Helsinki-NLP/opus-mt-tc-big-en-pt"


def textos() -> list[str]:
    docs = corpus()
    r = rng()
    out: list[str] = []
    # afirmações primeiro (são o mais importante); depois frases de evidência
    for split in ("claims_train.jsonl", "claims_dev.jsonl"):
        out += [c["claim"] for c in read_jsonl(SCIFACT / split)]
    for split in ("claims_train.jsonl",):
        for c in read_jsonl(SCIFACT / split):
            # frases de evidência + 1 frase não-evidência por documento (caso pt→pt)
            for doc_id in c.get("cited_doc_ids", []):
                d = docs.get(int(doc_id))
                if not d:
                    continue
                rat = {i for ev in c["evidence"].get(str(doc_id), []) for i in ev["sentences"]}
                for i in sorted(rat):
                    out.append(d["abstract"][i])
                outros = [i for i in range(len(d["abstract"])) if i not in rat]
                if outros:
                    out.append(d["abstract"][r.choice(outros)])
    return list(dict.fromkeys(t.strip() for t in out if t.strip()))


def main() -> None:
    torch.set_num_threads(int(sys.argv[1]) if len(sys.argv) > 1 else 6)
    feitos: dict[str, str] = {}
    if OUT.exists():
        feitos = {r["en"]: r["pt"] for r in read_jsonl(OUT)}
    todo = [t for t in textos() if t not in feitos]
    print(f"{len(feitos)} já traduzidos; {len(todo)} a traduzir", flush=True)
    tok = MarianTokenizer.from_pretrained(MODEL)
    model = MarianMTModel.from_pretrained(MODEL).eval()
    t0 = time.time()
    with OUT.open("a", encoding="utf-8") as fh:
        for i in range(0, len(todo), 16):
            lote = todo[i : i + 16]
            enc = tok([">>por<< " + t for t in lote], return_tensors="pt", padding=True,
                      truncation=True, max_length=256)
            with torch.no_grad():
                gen = model.generate(**enc, num_beams=1, max_new_tokens=200)
            for en, pt in zip(lote, tok.batch_decode(gen, skip_special_tokens=True)):
                fh.write(json.dumps({"en": en, "pt": pt}, ensure_ascii=False) + "\n")
            fh.flush()
            if (i // 16) % 10 == 0:
                print(f"{i + len(lote)}/{len(todo)} ({time.time() - t0:.0f}s)", flush=True)
    print("fim", flush=True)


if __name__ == "__main__":
    main()
