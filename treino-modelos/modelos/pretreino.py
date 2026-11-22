"""errei-base: pré-treino continuado (MLM) no texto acadêmico aberto do banco.

Adapta o encoder (mdeberta-v3-base por padrão) ao vocabulário acadêmico em pt, en e es.
Os outros modelos podem partir dele: ``base = "treino-modelos/saida/base/final"``.

Atenção: o checkpoint público do mDeBERTa-v3 foi pré-treinado como ELECTRA (RTD) e não
traz cabeça de MLM; ela começa aleatória e só o encoder interessa no fim. Com
``base = "xlm-roberta-base"`` (MIT) a cabeça de MLM já vem treinada.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from banco.banco import Banco
from comum.util import frases

from modelos import Conjunto, fonte_banco, limitar, lotes, obras

NOME = "errei-base"
TAREFA = "mlm"

CARTAO = """---
license: {licenca}
language: [pt, en, es]
tags: [errei, fill-mask, domain-adaptation]
---

# errei-base

Encoder adaptado ao texto acadêmico (pré-treino continuado com máscara, MLM) sobre resumos
e seções de artigos em CC BY/CC0. Não é usado diretamente pelo errei: é o ponto de partida
dos outros modelos (errei-cita, errei-resumo, errei-ref, errei-secoes, errei-ia).
"""


def trechos(texto: str, tamanho: int) -> list[str]:
    out, atual = [], ""
    for f in frases(texto, minimo=1):
        if atual and len(atual) + len(f) + 1 > tamanho:
            out.append(atual)
            atual = ""
        atual = f"{atual} {f}".strip()
    if atual:
        out.append(atual)
    return out


def construir(b: Banco, m: dict[str, Any], fumaca: bool) -> Conjunto:
    tamanho = int(m.get("tamanho_trecho", 2000))
    minimo = 20 if fumaca else int(m.get("min_chars", 200))
    rows: list[dict[str, Any]] = []
    licc: Counter[str] = Counter()
    maximo = int(m.get("max_textos", 0))
    for lote in lotes(obras(b, m)):
        ids = [r["id"] for r in lote]
        res = b.por_lingua("resumos", ids)
        secs = b.por_lingua("secoes", ids) if m.get("incluir_secoes", True) else {}
        for r in lote:
            textos = list((res.get(r["id"]) or {}).items())
            for lg, ss in (secs.get(r["id"]) or {}).items():
                textos.append((lg, "\n".join(s["texto"] or "" for s in ss)))
            n0 = len(rows)
            for lg, t in textos:
                rows += [
                    {"texto": x, "lingua": lg, "grupo": r["id"]}
                    for x in trechos(t, tamanho)
                    if len(x) >= minimo
                ]
            if len(rows) > n0:
                licc[r["licenca"]] += 1
        if maximo and len(rows) >= maximo:
            break
    rows = limitar(rows, maximo, int(m.get("semente", 42)))
    info = {"por_lingua": dict(Counter(r["lingua"] for r in rows)), "tamanho_trecho": tamanho}
    return Conjunto(
        rows,
        [fonte_banco(len(rows), licc, "resumos e seções (texto corrido)")],
        {},
        None,
        info,
        licc,
    )
