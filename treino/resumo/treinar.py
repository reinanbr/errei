"""Treina e avalia o errei-resumo-v1 (papel retórico das frases do resumo), em CPU.

Dados: CSAbstruct (AllenAI, Apache-2.0): resumos de Ciência da Computação com cada
frase rotulada como background/method/objective/other/result, mais a tradução pt-BR
feita por traduzir.py. Base: MoritzLaurer/multilingual-MiniLMv2-L6-mnli-xnli (MIT).

Entrada do modelo (igual ao uso em errei.resumocheck.entrada):
    "[i/n] frase"  +  frase anterior (contexto)

Seleciona a melhor época pelo F1 macro na validação em português e avalia no teste
(inglês e português) contra a linha de base por palavras-chave do próprio errei.

Uso: python treinar.py [saida] [epocas]
"""

from __future__ import annotations

import json
import math
import os
import random
import sys
import time
from collections import Counter
from pathlib import Path

import pyarrow.parquet as pq
import torch
from torch.nn import functional as F
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from errei.resumocheck import PAPEIS, Papel, elementos, entrada, papel_lexical

DADOS = Path(__file__).resolve().parent.parent / "dados" / "csabstruct"
BASE_MODEL = "MoritzLaurer/multilingual-MiniLMv2-L6-mnli-xnli"
CSA = ["background", "method", "objective", "other", "result"]
MAP = {"background": "contexto", "method": "metodo", "objective": "objetivo",
       "other": "outro", "result": "resultado"}
SEED = 13


def carregar_split(split: str, trad: dict[str, str]) -> dict[str, list[dict]]:  # type: ignore[type-arg]
    """{'en': [resumos], 'pt': [resumos totalmente traduzidos]}"""
    out: dict[str, list[dict]] = {"en": [], "pt": []}  # type: ignore[type-arg]
    for r in pq.read_table(DADOS / f"{split}.parquet").to_pylist():
        frases = [s.strip() for s in r["sentences"]]
        rot = [MAP[CSA[x]] for x in r["labels"]]
        out["en"].append({"frases": frases, "rotulos": rot})
        if all(f in trad for f in frases):
            out["pt"].append({"frases": [trad[f] for f in frases], "rotulos": rot})
    return out


def exemplos(resumos: list[dict]) -> list[tuple[str, str, int]]:  # type: ignore[type-arg]
    ex = []
    for r in resumos:
        for i, rot in enumerate(r["rotulos"]):
            a, b = entrada(r["frases"], i)
            ex.append((a, b, PAPEIS.index(rot)))
    return ex


def f1s(gold: list[int], pred: list[int]) -> dict[str, float]:
    out = {}
    for c, nome in enumerate(PAPEIS):
        tp = sum(g == p == c for g, p in zip(gold, pred, strict=True))
        fp = sum(p == c != g for g, p in zip(gold, pred, strict=True))
        fn = sum(g == c != p for g, p in zip(gold, pred, strict=True))
        out[nome] = 2 * tp / (2 * tp + fp + fn) if tp else 0.0
    out["macro"] = sum(out[n] for n in PAPEIS) / len(PAPEIS)
    out["acuracia"] = sum(g == p for g, p in zip(gold, pred, strict=True)) / max(1, len(gold))
    return {k: round(v, 4) for k, v in out.items()}


def presenca(resumos: list[dict], preds: list[list[str]]) -> dict[str, float]:  # type: ignore[type-arg]
    """Acerto ao dizer se o resumo TEM objetivo/método/resultado (o que o errei usa)."""
    out = {}
    for el in ("objetivo", "metodo", "resultado"):
        ok = 0
        for r, pr in zip(resumos, preds, strict=True):
            gold = el in r["rotulos"]
            got = elementos([Papel(f, p, 1.0, "") for f, p in zip(r["frases"], pr, strict=True)])[el]
            ok += gold == got
        out[el] = round(ok / max(1, len(resumos)), 4)
    return out


def main() -> None:
    saida = Path(sys.argv[1] if len(sys.argv) > 1 else "../modelos/errei-resumo-v1")
    epocas = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    torch.manual_seed(SEED)
    random.seed(SEED)
    torch.set_num_threads(10)
    trad: dict[str, str] = {}
    with (DADOS / "traducoes.jsonl").open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                r = json.loads(line)
                trad[r["en"]] = r["pt"]
    tr, va, te = (carregar_split(s, trad) for s in ("train", "validation", "test"))
    if os.environ.get("SMOKE"):  # teste rápido do script
        for d in (tr, va, te):
            for k in d:
                d[k] = d[k][:12]
    treino = exemplos(tr["en"]) + exemplos(tr["pt"])
    val_pt = exemplos(va["pt"])
    print(f"treino: {len(tr['en'])} resumos EN + {len(tr['pt'])} PT = {len(treino)} frases; "
          f"val PT: {len(va['pt'])} resumos; teste: {len(te['en'])} EN / {len(te['pt'])} PT",
          flush=True)

    tok = AutoTokenizer.from_pretrained(BASE_MODEL)
    model = AutoModelForSequenceClassification.from_pretrained(
        BASE_MODEL, num_labels=len(PAPEIS), ignore_mismatched_sizes=True,
        id2label=dict(enumerate(PAPEIS)), label2id={p: i for i, p in enumerate(PAPEIS)},
    )
    cont = Counter(y for _, _, y in treino)
    pesos = torch.tensor([math.sqrt(len(treino) / (len(PAPEIS) * cont[i])) for i in
                          range(len(PAPEIS))], dtype=torch.float)
    print("classes:", {PAPEIS[k]: v for k, v in cont.items()}, "pesos:",
          [round(x, 2) for x in pesos.tolist()], flush=True)

    lote, max_len, lr = 16, 160, 4e-5
    passos = epocas * math.ceil(len(treino) / lote)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.01)
    aquec = int(0.06 * passos)
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt, lambda s: min(1.0, (s + 1) / max(1, aquec)) * max(0.0, (passos - s) / passos))

    def enc(rows: list[tuple[str, str, int]]) -> dict:  # type: ignore[type-arg]
        e = tok([a for a, _, _ in rows], [b for _, b, _ in rows], truncation=True,
                max_length=max_len, padding=True, return_tensors="pt")
        return dict(e)

    @torch.no_grad()
    def prever(rows: list[tuple[str, str, int]]) -> list[int]:
        model.eval()
        out: list[int] = []
        for i in range(0, len(rows), 64):
            out += model(**enc(rows[i : i + 64])).logits.argmax(-1).tolist()
        model.train()
        return out

    def f1_val() -> float:
        return f1s([y for _, _, y in val_pt], prever(val_pt))["macro"]

    progresso = DADOS / "progresso.txt"
    melhor, hist = -1.0, []
    model.train()
    passo, t0 = 0, time.time()
    for ep in range(epocas):
        random.shuffle(treino)
        for i in range(0, len(treino), lote):
            rows = treino[i : i + lote]
            y = torch.tensor([r[2] for r in rows])
            loss = F.cross_entropy(model(**enc(rows)).logits, y, weight=pesos)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            sched.step()
            opt.zero_grad()
            passo += 1
            if passo % 50 == 0:
                dt = time.time() - t0
                msg = (f"treino: época {ep + 1}/{epocas} passo {passo}/{passos} perda "
                       f"{loss.item():.3f} · faltam ~{(passos - passo) * dt / passo / 60:.0f} min")
                progresso.write_text(msg + "\n")
                print(msg, flush=True)
        f1 = f1_val()
        hist.append({"epoca": ep + 1, "f1_macro_val_pt": round(f1, 4)})
        print(f"== época {ep + 1}: F1 macro val PT {f1:.3f}", flush=True)
        if f1 > melhor:
            melhor = f1
            saida.mkdir(parents=True, exist_ok=True)
            model.save_pretrained(saida)
            tok.save_pretrained(saida)

    # ---------------------------------------------------------------- avaliação final
    model = AutoModelForSequenceClassification.from_pretrained(saida).eval()
    res: dict[str, dict] = {}  # type: ignore[type-arg]
    for lang in ("en", "pt"):
        rs = te[lang]
        rows = exemplos(rs)
        gold = [y for _, _, y in rows]
        pm = prever(rows)
        pl = [PAPEIS.index(papel_lexical(r["frases"], i)) for r in rs
              for i in range(len(r["frases"]))]

        def por_resumo(flat: list[int]) -> list[list[str]]:
            out, k = [], 0
            for r in rs:
                out.append([PAPEIS[x] for x in flat[k : k + len(r["frases"])]])
                k += len(r["frases"])
            return out

        res[lang] = {
            "resumos": len(rs),
            "frases": len(rows),
            "modelo": {"f1": f1s(gold, pm), "presenca": presenca(rs, por_resumo(pm))},
            "palavras_chave": {"f1": f1s(gold, pl), "presenca": presenca(rs, por_resumo(pl))},
        }
        print(lang, json.dumps(res[lang], ensure_ascii=False), flush=True)

    card = {
        "nome": "errei-resumo-v1",
        "tarefa": "papel retórico de frases de resumo científico (NBR 6028: objetivo, método, "
                  "resultados)",
        "base": BASE_MODEL,
        "dados": "CSAbstruct (Cohan et al., 2019; AllenAI, Apache-2.0) + tradução pt-BR "
                 "(Helsinki-NLP/opus-mt-tc-big-en-pt)",
        "rotulos": PAPEIS,
        "treino": {"resumos_en": len(tr["en"]), "resumos_pt": len(tr["pt"]),
                   "frases": len(treino), "epocas": epocas, "lote": lote, "lr": lr,
                   "historico": hist, "segundos": round(time.time() - t0)},
        "teste": res,
        "licenca": "Apache-2.0 (dados CSAbstruct Apache-2.0; base MIT)",
    }
    (saida / "errei_resumo.json").write_text(json.dumps(card, ensure_ascii=False, indent=1))
    (saida / "README.md").write_text(readme(card))
    progresso.write_text("treino concluído\n")
    print("salvo em", saida, flush=True)


def readme(c: dict) -> str:  # type: ignore[type-arg]
    def linha(lang: str, k: str) -> str:
        r = c["teste"][lang][k]
        f = r["f1"]
        p = r["presenca"]
        return (f"| {lang.upper()} | {'errei-resumo-v1' if k == 'modelo' else 'palavras-chave'} "
                f"| {f['macro']:.3f} | {f['acuracia']:.3f} | {f['objetivo']:.3f} | "
                f"{f['metodo']:.3f} | {f['resultado']:.3f} | {p['objetivo']:.0%} / "
                f"{p['metodo']:.0%} / {p['resultado']:.0%} |")

    rows = "\n".join(linha(lg, k) for lg in ("en", "pt") for k in ("palavras_chave", "modelo"))
    return f"""---
license: apache-2.0
language: [pt, en]
base_model: {c['base']}
datasets: [allenai/csabstruct]
---

# errei-resumo-v1

Classifica o papel retórico de cada frase de um resumo científico (contexto, objetivo,
método, resultado, outro), para o verificador `abnt` do errei conferir se o resumo
apresenta **objetivo, método, resultados e conclusões** (ABNT NBR 6028:2021).

- Base: `{c['base']}` (MIT), cabeça nova de 5 classes.
- Dados: {c['dados']}.
- Entrada: `"[i/n] frase"` + frase anterior.
- Treino: {c['treino']['resumos_en']} resumos em inglês + {c['treino']['resumos_pt']} traduzidos
  ({c['treino']['frases']} frases), {c['treino']['epocas']} épocas em CPU.

## Avaliação (teste do CSAbstruct; PT = tradução automática)

| língua | método | F1 macro | acurácia | F1 objetivo | F1 método | F1 resultado | presença obj/mét/res |
|---|---|---|---|---|---|---|---|
{rows}

"Presença" = acerto ao dizer se o resumo contém ao menos uma frase daquele papel, que é
o uso no errei.

## Limitações

- Domínio do treino: Ciência da Computação, em inglês; o português vem de tradução
  automática. Resumos de outras áreas e escritos originalmente em português podem ter
  desempenho menor.
- O CSAbstruct não separa conclusão de resultado: o errei detecta a conclusão por
  marcadores lexicais.
- Indicador para revisão, não verificação de conformidade.
"""


if __name__ == "__main__":
    main()
