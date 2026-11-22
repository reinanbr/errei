"""Avalia o modelo treinado no conjunto de teste (e limiares na validação).

Uso (da raiz do repositório):
    python treino-modelos/avaliar.py --modelo resumo
    python treino-modelos/avaliar.py --modelo ia --max 20000

Métricas por tarefa: classificação (acurácia, F1 macro e por classe; no errei-ia, AUC e
taxa de acerto com o falso positivo fixado na validação), tokens (F1 por campo),
bi-encoder (R@1, R@10, MRR), seq2seq (chrF; F1 dos termos no errei-chaves) e MLM
(perplexidade, comparada com a da base). Tudo também por estrato da revista: faixa do
Qualis (A, B, C, sem), Scopus e Web of Science, e por língua/fonte/estilo.

Grava ``<saida>/final/errei_avaliacao.json``, ``errei_limiares.json`` e
``<saida>/metricas.json`` (este com exemplos de saída).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from comum import metricas
from comum.util import ler_jsonl
from modelos import MODELOS
from treinar import FUMACA, hiper, manifesto

GRUPOS_ROW = ("lingua", "fonte", "estilo", "tipo", "modo")


def por_grupo(rows: list[dict[str, Any]], valores: list[float]) -> dict[str, dict[str, Any]]:
    acc: dict[str, dict[str, list[float]]] = {}
    for r, v in zip(rows, valores, strict=False):
        c = r.get("classe") or {}
        chaves = {}
        if c:
            chaves["qualis_faixa"] = c.get("qualis_faixa") or "sem"
            chaves["scopus"] = "scopus" if c.get("scopus") else "fora"
            chaves["wos"] = c.get("wos") or "fora"
        for k in GRUPOS_ROW:
            if r.get(k):
                chaves[k] = str(r[k])
        for k, g in chaves.items():
            acc.setdefault(k, {}).setdefault(g, []).append(v)
    return {
        k: {g: {"n": len(vs), "media": sum(vs) / len(vs)} for g, vs in sorted(d.items())}
        for k, d in acc.items()
        if len(d) > 1 or k in {"qualis_faixa", "scopus", "wos"}
    }


def classificacao(
    t: Any,
    tok: Any,
    model: Any,
    va: list[dict[str, Any]],
    te: list[dict[str, Any]],
    man: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], list[float]]:
    labels = man["labels"]
    pv, pt = t.probabilidades(tok, model, va), t.probabilidades(tok, model, te)
    yv, yt = [r["label"] for r in va], [r["label"] for r in te]
    if labels == ["humano", "ia"]:
        fpr = float((man.get("info") or {}).get("fpr_alvo", 0.01))
        sv, st = [p[1] for p in pv], [p[1] for p in pt]
        lim = metricas.limiar_fpr([s for s, y in zip(sv, yv, strict=False) if y == "humano"], fpr)
        pred = ["ia" if s > lim else "humano" for s in st]
        pos = [s for s, y in zip(st, yt, strict=False) if y == "ia"]
        neg = [s for s, y in zip(st, yt, strict=False) if y == "humano"]
        m = metricas.f1_classes(yt, pred, labels)
        m.update(
            auc=metricas.auc(pos, neg), limiar=lim, fpr_alvo=fpr, **metricas.taxas(pos, neg, lim)
        )
        return (
            m,
            {"ia": lim, "fpr_alvo": fpr},
            [float(a == b) for a, b in zip(yt, pred, strict=False)],
        )
    pred = [labels[max(range(len(p)), key=p.__getitem__)] for p in pt]
    pred_v = [labels[max(range(len(p)), key=p.__getitem__)] for p in pv]
    m = metricas.f1_classes(yt, pred, labels)
    m["validacao"] = {
        k: v
        for k, v in metricas.f1_classes(yv, pred_v, labels).items()
        if k in {"acuracia", "f1_macro"}
    }
    return m, {}, [float(a == b) for a, b in zip(yt, pred, strict=False)]


def tokens(
    t: Any, tok: Any, model: Any, te: list[dict[str, Any]]
) -> tuple[dict[str, Any], list[float]]:
    pred = t.prever(tok, model, te)
    ouro = [r["tags"] for r in te]
    return metricas.f1_campos(ouro, pred), [
        metricas.f1_linha(g, p) for g, p in zip(ouro, pred, strict=False)
    ]


def biencoder(
    t: Any, tok: Any, model: Any, te: list[dict[str, Any]]
) -> tuple[dict[str, Any], list[float]]:
    import torch

    passagens = list(dict.fromkeys(r["passagem"] for r in te))
    idx = {p: i for i, p in enumerate(passagens)}
    grupo_p: dict[int, str] = {}
    for r in te:
        grupo_p.setdefault(idx[r["passagem"]], str(r["grupo"]))
    gp = [grupo_p[i] for i in range(len(passagens))]
    q = t.codificar_textos(tok, model, [t.pq + r["consulta"] for r in te])
    p = t.codificar_textos(tok, model, [t.pp + x for x in passagens])
    rr = []
    ranks = []
    for i, r in enumerate(te):
        s = (q[i : i + 1] @ p.T)[0]
        ouro = s[idx[r["passagem"]]]
        outros = torch.tensor([g != str(r["grupo"]) for g in gp], device=s.device)
        rank = 1 + int(((s > ouro) & outros).sum())  # passagens da mesma obra não contam como erro
        ranks.append(rank)
        rr.append(1.0 / rank)
    n = max(1, len(ranks))
    m = {
        "n": len(te),
        "passagens": len(passagens),
        "mrr": sum(rr) / n,
        "r@1": sum(k <= 1 for k in ranks) / n,
        "r@10": sum(k <= 10 for k in ranks) / n,
    }
    por_tipo: dict[str, list[float]] = {}
    for r, v in zip(te, rr, strict=False):
        por_tipo.setdefault(r.get("tipo", "?"), []).append(v)
    m["mrr_por_tipo"] = {k: sum(v) / len(v) for k, v in sorted(por_tipo.items())}
    return m, rr


def seq2seq(
    t: Any, tok: Any, model: Any, te: list[dict[str, Any]], h: dict[str, Any]
) -> tuple[dict[str, Any], list[float], list[dict[str, str]]]:
    ger = t.gerar(tok, model, te, feixes=int(h.get("feixes", 4)))
    refs = [r["saida"] for r in te]
    por = [metricas.chrf([g], [r]) for g, r in zip(ger, refs, strict=False)]
    m: dict[str, Any] = {"n": len(te), "chrf": metricas.chrf(ger, refs)}
    if h["modelo"] == "chaves":
        f = [metricas.f1_termos(g, r) for g, r in zip(ger, refs, strict=False)]
        n = max(1, len(f))
        m.update(
            termos_precisao=sum(x[0] for x in f) / n,
            termos_revocacao=sum(x[1] for x in f) / n,
            termos_f1=sum(x[2] for x in f) / n,
        )
    ex = [
        {"entrada": r["entrada"][:300], "referencia": r["saida"], "gerado": g}
        for r, g in list(zip(te, ger, strict=False))[:8]
    ]
    return m, por, ex


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="avalia um modelo do errei")
    ap.add_argument("--modelo", required=True, choices=MODELOS)
    ap.add_argument("--config")
    ap.add_argument("--saida")
    ap.add_argument("--dados")
    ap.add_argument("--pasta-modelo", help="padrão: <saida>/final")
    ap.add_argument("--max", type=int, default=0, help="limite de exemplos de teste")
    ap.add_argument("--fumaca", action="store_true")
    a = ap.parse_args(argv)
    ns = argparse.Namespace(
        modelo=a.modelo,
        config=a.config,
        epocas=None,
        batch=None,
        lr=None,
        saida=a.saida,
        dados=a.dados,
        modelo_base=None,
        gpu=None,
        fumaca=a.fumaca,
    )
    h = hiper(ns)
    saida, dados = Path(h["saida"]), Path(h["dados"])
    final = Path(a.pasta_modelo) if a.pasta_modelo else saida / "final"
    if not (final / "config.json").is_file():
        print(f"erro: {final} não tem modelo; rode treinar.py", file=sys.stderr)
        return 1
    man = manifesto(dados)
    desc = json.loads((final / "errei_tarefa.json").read_text(encoding="utf-8"))
    treino = json.loads((final / "treino.json").read_text(encoding="utf-8"))
    h["base"] = treino.get(
        "base", h["base"]
    )  # a base de fato usada (pode ter vindo de --modelo-base)
    h["max_len"] = int(desc.get("max_len", h["max_len"]))
    h["max_len_saida"] = int(desc.get("max_len_saida", h.get("max_len_saida", 128)))
    maximo = a.max or (0 if a.fumaca else int(h.get("max_avaliacao", 5000)))
    va = list(ler_jsonl(dados / "validacao.jsonl"))[: maximo or None]
    te = list(ler_jsonl(dados / "teste.jsonl"))[: maximo or None]

    import torch
    from tarefas import tarefa

    dev = torch.device("cuda" if torch.cuda.is_available() and not a.fumaca else "cpu")
    bf16 = dev.type == "cuda" and torch.cuda.is_bf16_supported() and h.get("bf16") is not False
    t = tarefa(man["tarefa"], h, man.get("labels"), man.get("info") or {})
    tok, model = t.carregar(str(final))
    model.to(dev).eval()
    t.dev, t.bf16 = dev, bf16
    limiares: dict[str, Any] = {}
    exemplos: list[dict[str, str]] = []
    if man["tarefa"] == "classificacao":
        m, limiares, por = classificacao(t, tok, model, va, te, man)
    elif man["tarefa"] == "tokens":
        m, por = tokens(t, tok, model, te)
    elif man["tarefa"] == "biencoder":
        m, por = biencoder(t, tok, model, te)
    elif man["tarefa"] == "seq2seq":
        m, por, exemplos = seq2seq(t, tok, model, te, h)
    else:
        perda = t.perda_media(tok, model, te)
        m = {"n": len(te), "perda": perda, "perplexidade": math.exp(min(perda, 50))}
        if h["base"] != FUMACA:
            tb, mb = t.carregar(h["base"])
            mb.to(dev).eval()
            pb = t.perda_media(tok, mb, te)
            m.update(perda_base=pb, perplexidade_base=math.exp(min(pb, 50)))
            del mb, tb
        por = []
    res = {
        "modelo": man["nome"],
        "tarefa": man["tarefa"],
        "teste": m,
        "limiares": limiares,
        "por_grupo": por_grupo(te, por) if por else {},
        "n_teste": len(te),
        "n_validacao": len(va),
    }
    (final / "errei_avaliacao.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    (final / "errei_limiares.json").write_text(
        json.dumps(limiares, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    (saida / "metricas.json").write_text(
        json.dumps({**res, "exemplos": exemplos}, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    resumo = {
        k: (round(v, 4) if isinstance(v, float) else v)
        for k, v in m.items()
        if not isinstance(v, dict)
    }
    print(f"[OK] {man['nome']} · teste: {json.dumps(resumo, ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
