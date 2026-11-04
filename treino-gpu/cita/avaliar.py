"""Avalia o errei-cita-v2: escolhe os limiares na validação e mede no teste.

Uso: python treino-gpu/cita/avaliar.py [--modelo treino-gpu/saida/final] [--dados ...]

Grava ``<saida>/metricas.json`` e, dentro da pasta do modelo, ``errei_limiares.json`` e
``errei_avaliacao.json`` no formato que ``errei modelo info`` mostra
(``afirmacao_en`` / ``afirmacao_pt`` com ``acuracia`` e ``f1_macro``).

A regra de decisão é a mesma da inferência (errei.citecheck.Classificador.julgar):
contradiz se P(contradiz) ≥ limiar e ≥ P(sustenta); senão sustenta se P(sustenta) ≥ limiar;
senão neutro.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dados import LABELS, caminho, carregar_config, ler_jsonl  # noqa: E402

GRADE = [round(0.3 + 0.05 * i, 2) for i in range(12)]  # 0.30 … 0.85


def probs(modelo: Path, pares: list[dict[str, Any]], max_len: int, lote: int = 64) -> list[list[float]]:
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    dev = "cuda" if torch.cuda.is_available() else "cpu"
    tok = AutoTokenizer.from_pretrained(str(modelo))
    model = AutoModelForSequenceClassification.from_pretrained(str(modelo)).to(dev).eval()
    id2 = {int(k): str(v) for k, v in model.config.id2label.items()}
    ordem = [id2[i] for i in range(len(id2))]
    out: list[list[float]] = []
    with torch.no_grad():
        for i in range(0, len(pares), lote):
            c = pares[i : i + lote]
            enc = tok([p["b"] for p in c], [p["a"] for p in c], truncation=True,
                      max_length=max_len, padding=True, return_tensors="pt").to(dev)
            p = torch.softmax(model(**enc).logits.float(), dim=-1).tolist()
            out += [[row[ordem.index(lb)] for lb in LABELS] for row in p]
    return out


def decidir(p: list[float], ls: float, lc: float) -> str:
    s, c = p[0], p[1]
    if c >= lc and c >= s:
        return "contradiz"
    if s >= ls:
        return "sustenta"
    return "neutro"


def medir(gold: list[str], pred: list[str]) -> dict[str, Any]:
    r: dict[str, Any] = {"n": len(gold)}
    f1s = []
    for lb in LABELS:
        tp = sum(g == lb and p == lb for g, p in zip(gold, pred, strict=True))
        fp = sum(g != lb and p == lb for g, p in zip(gold, pred, strict=True))
        fn = sum(g == lb and p != lb for g, p in zip(gold, pred, strict=True))
        prec = tp / (tp + fp) if tp + fp else 0.0
        rev = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * prec * rev / (prec + rev) if prec + rev else 0.0
        r[lb] = {"precisao": round(prec, 4), "revocacao": round(rev, 4), "f1": round(f1, 4),
                 "n": sum(g == lb for g in gold)}
        f1s.append(f1)
    r["acuracia"] = round(sum(g == p for g, p in zip(gold, pred, strict=True)) / max(1, len(gold)), 4)
    r["f1_macro"] = round(sum(f1s) / 3, 4)
    return r


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="avalia o errei-cita-v2")
    ap.add_argument("--config")
    ap.add_argument("--modelo")
    ap.add_argument("--dados")
    ap.add_argument("--saida")
    a = ap.parse_args(argv)
    cfg = carregar_config(a.config)
    saida = caminho(a.saida or cfg["treino"]["saida"])
    modelo = Path(a.modelo) if a.modelo else saida / "final"
    dados = caminho(a.dados or cfg["dados"]["dir"])
    if not (modelo / "config.json").is_file():
        print(f"erro: modelo não encontrado em {modelo}; rode treinar.py", file=sys.stderr)
        return 1
    info = json.loads((modelo / "treino.json").read_text()) if (modelo / "treino.json").is_file() else {}
    max_len = int(info.get("max_len") or cfg["modelo"]["max_len"])
    val = list(ler_jsonl(dados / "validacao.jsonl"))
    teste = list(ler_jsonl(dados / "teste.jsonl"))
    if not val or not teste:
        print("erro: validação ou teste vazio; refaça dados.py", file=sys.stderr)
        return 1

    pv = probs(modelo, val, max_len)
    gold_v = [p["label"] for p in val]
    melhor = (-1.0, 0.5, 0.5)
    for ls in GRADE:
        for lc in GRADE:
            f1 = medir(gold_v, [decidir(p, ls, lc) for p in pv])["f1_macro"]
            if f1 > melhor[0]:
                melhor = (f1, ls, lc)
    _, ls, lc = melhor
    pt = probs(modelo, teste, max_len)
    res: dict[str, Any] = {"modelo": info.get("modelo", modelo.name), "nivel": "par (frase × trecho)",
                           "limiares": {"sustenta": ls, "contradiz": lc,
                                        "escolhidos_em": "validação"},
                           "validacao_f1_macro": melhor[0]}
    for lg in ("en", "pt"):
        idx = [i for i, p in enumerate(teste) if p.get("lingua", "en") == lg]
        if idx:
            res[f"afirmacao_{lg}"] = medir([teste[i]["label"] for i in idx],
                                           [decidir(pt[i], ls, lc) for i in idx])
    res["total"] = medir([p["label"] for p in teste], [decidir(p, ls, lc) for p in pt])
    por_fonte: dict[str, Any] = {}
    for f in sorted({p["fonte"] for p in teste}):
        idx = [i for i, p in enumerate(teste) if p["fonte"] == f]
        por_fonte[f] = medir([teste[i]["label"] for i in idx], [decidir(pt[i], ls, lc) for i in idx])
    res["por_fonte"] = por_fonte

    saida.mkdir(parents=True, exist_ok=True)
    (saida / "metricas.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    (modelo / "errei_avaliacao.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    (modelo / "errei_limiares.json").write_text(json.dumps(res["limiares"], indent=1))
    for k in ("afirmacao_en", "afirmacao_pt", "total"):
        if k in res:
            print(f"{k}: acurácia {res[k]['acuracia']:.3f} · F1 macro {res[k]['f1_macro']:.3f} "
                  f"(n={res[k]['n']})")
    print(f"limiares: sustenta ≥ {ls}, contradiz ≥ {lc}")
    print(f"[OK] {saida / 'metricas.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
