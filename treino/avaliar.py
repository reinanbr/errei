"""Avalia um modelo no nível do documento: (afirmação, resumo citado) -> rótulo.

Uso: python avaliar.py <modelo> [val|teste] [limiar_s limiar_c]
Sem limiares, faz busca de limiares (use em 'val'); com limiares, só aplica (use em 'teste').
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import torch

from comum import DADOS, LABELS, corpus, read_jsonl
from modelo_cita import Classificador


def itens(nome: str) -> list[tuple[str, str, list[str], str]]:
    docs = corpus()
    out = []
    for c in read_jsonl(DADOS / f"afirmacoes_{nome}.jsonl"):
        for doc_id in c.get("cited_doc_ids", []):
            d = docs.get(int(doc_id))
            if not d:
                continue
            evs = c["evidence"].get(str(doc_id), [])
            gold = {"SUPPORT": "sustenta", "CONTRADICT": "contradiz"}[evs[0]["label"]] \
                if evs else "neutro"
            out.append((c["claim"], c.get("claim_pt", ""), d["abstract"], gold))
    return out


def decide(s: float, c: float, ts: float, tc: float) -> str:
    if c >= tc and c >= s:
        return "contradiz"
    if s >= ts:
        return "sustenta"
    return "neutro"


def metricas(gold: list[str], pred: list[str]) -> dict:  # type: ignore[type-arg]
    res: dict = {"acuracia": sum(g == p for g, p in zip(gold, pred, strict=True)) / len(gold)}  # type: ignore[type-arg]
    f1s = []
    for lab in LABELS:
        tp = sum(g == p == lab for g, p in zip(gold, pred, strict=True))
        fp = sum(p == lab != g for g, p in zip(gold, pred, strict=True))
        fn = sum(g == lab != p for g, p in zip(gold, pred, strict=True))
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        res[lab] = {"precisao": round(prec, 3), "revocacao": round(rec, 3), "f1": round(f1, 3),
                    "n": sum(g == lab for g in gold)}
        f1s.append(f1)
    res["f1_macro"] = sum(f1s) / len(f1s)
    return res


def main() -> None:
    torch.set_num_threads(8)
    caminho, nome = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "val")
    clf = Classificador(caminho)
    data = itens(nome)
    t0 = time.time()
    scores = {"en": [], "pt": []}
    progresso = DADOS / "progresso.txt"
    rotulo = f"{Path(caminho).name} em '{nome}'"
    for i, (claim_en, claim_pt, abstract, _gold) in enumerate(data, 1):
        scores["en"].append(clf.julgar_resumo(claim_en, abstract))
        scores["pt"].append(clf.julgar_resumo(claim_pt or claim_en, abstract))
        if i % 5 == 0 or i == len(data):
            gasto = time.time() - t0
            resta = gasto / i * (len(data) - i)
            linha = (f"{time.strftime('%H:%M:%S')}  avaliando {rotulo}: {i}/{len(data)} "
                     f"({i / len(data):.0%})  ~{resta / 60:.1f} min restantes\n")
            with progresso.open("a", encoding="utf-8") as fh:
                fh.write(linha)
    gold = [g for *_, g in data]
    if len(sys.argv) > 4:
        ts, tc = float(sys.argv[3]), float(sys.argv[4])
    else:
        best = (-1.0, 0.5, 0.5)
        for ts in [x / 20 for x in range(4, 20)]:
            for tc in [x / 20 for x in range(4, 20)]:
                f = sum(metricas(gold, [decide(s["sustenta"], s["contradiz"], ts, tc)
                                        for s in scores[lg]])["f1_macro"] for lg in ("en", "pt"))
                if f > best[0]:
                    best = (f, ts, tc)
        _, ts, tc = best
    rel = {"modelo": caminho, "conjunto": nome, "n": len(data), "limiar_sustenta": ts,
           "limiar_contradiz": tc, "segundos": round(time.time() - t0, 1)}
    for lg in ("en", "pt"):
        pred = [decide(s["sustenta"], s["contradiz"], ts, tc) for s in scores[lg]]
        rel[f"afirmacao_{lg}"] = metricas(gold, pred)
    with (DADOS / "progresso.txt").open("a", encoding="utf-8") as fh:
        r_en, r_pt = rel["afirmacao_en"], rel["afirmacao_pt"]
        fh.write(f"{time.strftime('%H:%M:%S')}  CONCLUÍDO {rotulo}: F1 macro "
                 f"en {r_en['f1_macro']:.3f} | pt {r_pt['f1_macro']:.3f}\n")
    print(json.dumps(rel, ensure_ascii=False, indent=1))
    saida = DADOS / f"avaliacao_{caminho.replace('/', '_')}_{nome}.json"
    saida.write_text(json.dumps(rel, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
