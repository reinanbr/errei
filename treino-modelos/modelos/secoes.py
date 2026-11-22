"""errei-secoes: de que elemento é cada parágrafo (introdução, objetivo, participantes...).

Segunda metade do item 6. Rótulo fraco: o título da seção ou subseção no texto completo
JATS (CC BY/CC0), lido por ``comum.jats`` (tipo da seção e, quando o título diz, a parte:
``metodo:participantes``, ``introducao:objetivo``, ``discussao:limitacoes``...). O título
fica fora da entrada por padrão (``com_titulo = false``): o modelo aprende pelo conteúdo,
que é o que o ``completude`` precisa quando o autor não pôs título.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from banco.banco import Banco
from comum.util import cortar

from modelos import Conjunto, balancear, exemplo, fonte_banco, limitar, lotes, obras

NOME = "errei-secoes"
TAREFA = "classificacao"

CARTAO = """---
license: {licenca}
language: [pt, en, es]
tags: [errei, text-classification, imrad, rhetorical-moves]
---

# errei-secoes

Diz de que elemento do trabalho é um parágrafo: introdução (e, dentro dela, objetivo ou
problema), revisão, método (participantes, instrumentos, procedimentos, análise, ética,
local), resultados, discussão (limitações, implicações) ou conclusão. Serve ao
`completude` do errei no lugar do Gemini (`COMP-IA-001`): sem gerar texto, aponta o que
falta e o que artigos abertos da mesma área costumam trazer.

Entrada: o parágrafo (sem o título da seção). Rótulos fracos, tirados dos títulos das
seções de artigos em CC BY/CC0.
"""


def construir(b: Banco, m: dict[str, Any], fumaca: bool) -> Conjunto:
    com_titulo = bool(m.get("com_titulo", False))
    alvo = str(m.get("alvo", "parte"))  # "parte" (tipo ou tipo:parte) ou "tipo"
    min_chars = 20 if fumaca else int(m.get("min_chars", 80))
    max_par = int(m.get("max_paragrafos_secao", 4))
    incluir_outro = bool(m.get("incluir_outro", False))
    rows: list[dict[str, Any]] = []
    licc: Counter[str] = Counter()
    for lote in lotes(obras(b, m)):
        ids = [r["id"] for r in lote]
        secs = b.por_lingua("secoes", ids)
        for r in lote:
            usou = False
            for lg, ss in (secs.get(r["id"]) or {}).items():
                for s in ss:
                    rot = (s["parte"] or s["tipo"]) if alvo == "parte" else s["tipo"]
                    if not rot or (rot == "outro" and not incluir_outro):
                        continue
                    paras = [
                        p for p in (s["texto"] or "").split("\n") if len(p.strip()) >= min_chars
                    ]
                    for p in paras[:max_par]:
                        ex = exemplo(r, texto=cortar(p, 1200), label=rot, lingua=lg)
                        if com_titulo:
                            ex["par"] = s["titulo"] or ""
                        rows.append(ex)
                        usou = True
            if usou:
                licc[r["licenca"]] += 1
    cont = Counter(r["label"] for r in rows)
    minimo = 1 if fumaca else int(m.get("min_por_classe", 300))
    poucas = {k: v for k, v in cont.items() if v < minimo}
    rows = [r for r in rows if r["label"] not in poucas]
    rows = balancear(rows, "label", int(m.get("max_por_classe", 0)), int(m.get("semente", 42)))
    rows = limitar(rows, int(m.get("max_exemplos", 0)), int(m.get("semente", 42)))
    labels = sorted({r["label"] for r in rows})
    recusados = {
        f"classe {k}": f"só {v} exemplos (mínimo {minimo})" for k, v in sorted(poucas.items())
    }
    info = {"alvo": alvo, "par": com_titulo, "por_classe": dict(Counter(r["label"] for r in rows))}
    return Conjunto(
        rows,
        [fonte_banco(len(rows), licc, "parágrafos de textos completos (JATS)")],
        recusados,
        labels,
        info,
        licc,
    )
