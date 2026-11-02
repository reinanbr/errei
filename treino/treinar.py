"""Fine-tuning do errei-cita (cross-encoder multilíngue, 3 classes) em CPU.

Base: MoritzLaurer/multilingual-MiniLMv2-L6-mnli-xnli (MIT), já treinada em NLI
multilíngue; a cabeça entailment/neutral/contradiction é reaproveitada como
sustenta/neutro/contradiz e ajustada ao domínio científico (SciFact + pt-BR).

Uso: python treinar.py [saida] [epocas]
"""

from __future__ import annotations

import json
import math
import random
import sys
import time
from collections import Counter
from pathlib import Path

import torch
from torch.nn import functional as F
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from comum import DADOS, SEED, read_jsonl

BASE_MODEL = "MoritzLaurer/multilingual-MiniLMv2-L6-mnli-xnli"
ALIAS = {"entailment": "sustenta", "neutral": "neutro", "contradiction": "contradiz"}


def main() -> None:
    saida = Path(sys.argv[1] if len(sys.argv) > 1 else "modelos/errei-cita-v1")
    epocas = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    torch.manual_seed(SEED)
    random.seed(SEED)
    torch.set_num_threads(10)
    tok = AutoTokenizer.from_pretrained(BASE_MODEL)
    model = AutoModelForSequenceClassification.from_pretrained(BASE_MODEL)
    base_id2 = {int(k): v.lower() for k, v in model.config.id2label.items()}
    lab2id = {ALIAS[v]: k for k, v in base_id2.items()}
    model.config.id2label = {k: ALIAS[v] for k, v in base_id2.items()}
    model.config.label2id = {v: k for k, v in model.config.id2label.items()}

    treino = list(read_jsonl(DADOS / "pares_treino.jsonl"))
    val = list(read_jsonl(DADOS / "pares_val.jsonl"))
    cont = Counter(p["label"] for p in treino)
    pesos = torch.tensor([len(treino) / (3 * cont[model.config.id2label[i]])
                          for i in range(3)], dtype=torch.float)
    print("classes:", dict(cont), "pesos:", [round(x, 2) for x in pesos.tolist()], flush=True)

    lote, max_len, lr = 16, 192, 2e-5
    passos = epocas * math.ceil(len(treino) / lote)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.01)
    aquec = int(0.1 * passos)
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt, lambda s: min(1.0, (s + 1) / max(1, aquec)) * max(0.0, (passos - s) / passos))

    def batch(rows: list[dict]) -> dict:  # type: ignore[type-arg]
        enc = tok([r["b"] for r in rows], [r["a"] for r in rows], truncation=True,
                  max_length=max_len, padding=True, return_tensors="pt")
        enc["labels"] = torch.tensor([lab2id[r["label"]] for r in rows])
        return dict(enc)

    @torch.no_grad()
    def avaliar() -> float:
        model.eval()
        gold, pred = [], []
        for i in range(0, len(val), 64):
            b = batch(val[i : i + 64])
            y = b.pop("labels")
            pred += model(**b).logits.argmax(-1).tolist()
            gold += y.tolist()
        model.train()
        f1s = []
        for c in range(3):
            tp = sum(g == p == c for g, p in zip(gold, pred, strict=True))
            fp = sum(p == c != g for g, p in zip(gold, pred, strict=True))
            fn = sum(g == c != p for g, p in zip(gold, pred, strict=True))
            f1s.append(2 * tp / (2 * tp + fp + fn) if tp else 0.0)
        return sum(f1s) / 3

    print(f"F1 macro (pares de validação) antes do treino: {avaliar():.3f}", flush=True)
    melhor = -1.0
    historico = []
    model.train()
    passo = 0
    t0 = time.time()
    for ep in range(epocas):
        random.shuffle(treino)
        for i in range(0, len(treino), lote):
            b = batch(treino[i : i + lote])
            y = b.pop("labels")
            loss = F.cross_entropy(model(**b).logits, y, weight=pesos)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            sched.step()
            opt.zero_grad()
            passo += 1
            if passo % 50 == 0:
                print(f"época {ep + 1} passo {passo}/{passos} perda {loss.item():.3f} "
                      f"({time.time() - t0:.0f}s)", flush=True)
        f1 = avaliar()
        historico.append({"epoca": ep + 1, "f1_val": round(f1, 4)})
        print(f"== fim da época {ep + 1}: F1 macro val {f1:.3f}", flush=True)
        if f1 > melhor:
            melhor = f1
            saida.mkdir(parents=True, exist_ok=True)
            model.save_pretrained(saida)
            tok.save_pretrained(saida)
    (saida / "treino.json").write_text(json.dumps({
        "base": BASE_MODEL, "epocas": epocas, "lote": lote, "lr": lr, "max_len": max_len,
        "pares_treino": len(treino), "pares_val": len(val), "classes": dict(cont),
        "historico": historico, "melhor_f1_val_pares": round(melhor, 4),
        "segundos": round(time.time() - t0),
    }, ensure_ascii=False, indent=1))
    print("salvo em", saida, flush=True)


if __name__ == "__main__":
    main()
