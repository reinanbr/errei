"""errei-area: título + resumo → área do conhecimento (campo do OpenAlex, 26 classes).

Primeira metade do item 6 (errei-secoes): saber a área do trabalho para dizer "o que
costuma aparecer neste elemento na sua área". O rótulo vem do ``primary_topic`` do
OpenAlex (CC0); ``rotulo = "dominio"`` dá 4 classes e ``"subcampo"`` dá ~250.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from banco.banco import Banco
from comum.util import cortar

from modelos import Conjunto, balancear, exemplo, fonte_banco, limitar, lotes, obras

NOME = "errei-area"
TAREFA = "classificacao"

CARTAO = """---
license: {licenca}
language: [pt, en, es]
tags: [errei, text-classification, research-field]
---

# errei-area

Classifica um trabalho acadêmico (título + resumo) na área do conhecimento: campo do
OpenAlex (taxonomia de tópicos, CC0). Usado pelo errei para comparar cada seção com o que
artigos abertos da mesma área costumam trazer.

Entrada: `<título>. <resumo>` (um segmento só).
"""


def construir(b: Banco, m: dict[str, Any], fumaca: bool) -> Conjunto:
    rotulo = str(m.get("rotulo", "campo"))
    if rotulo not in {"dominio", "campo", "subcampo"}:
        raise SystemExit("erro: [area] rotulo deve ser dominio, campo ou subcampo")
    max_chars = int(m.get("max_chars", 1500))
    rows: list[dict[str, Any]] = []
    licc: Counter[str] = Counter()
    for lote in lotes(obras(b, m)):
        ids = [r["id"] for r in lote]
        tit, res = b.por_lingua("titulos", ids), b.por_lingua("resumos", ids)
        for r in lote:
            if not r[rotulo]:
                continue
            usou = False
            for lg, resumo in (res.get(r["id"]) or {}).items():
                t = (tit.get(r["id"]) or {}).get(lg) or (r["titulo"] if r["idioma"] == lg else "")
                if len(resumo) < 200:
                    continue
                rows.append(
                    exemplo(
                        r,
                        texto=cortar(f"{t}. {resumo}" if t else resumo, max_chars),
                        label=r[rotulo],
                        lingua=lg,
                    )
                )
                usou = True
            if usou:
                licc[r["licenca"]] += 1
    cont = Counter(r["label"] for r in rows)
    minimo = 1 if fumaca else int(m.get("min_por_classe", 200))
    poucas = {k: v for k, v in cont.items() if v < minimo}
    rows = [r for r in rows if r["label"] not in poucas]
    rows = balancear(rows, "label", int(m.get("max_por_classe", 0)), int(m.get("semente", 42)))
    rows = limitar(rows, int(m.get("max_exemplos", 0)), int(m.get("semente", 42)))
    labels = sorted({r["label"] for r in rows})
    recusados = {
        f"classe {k}": f"só {v} exemplos (mínimo {minimo})" for k, v in sorted(poucas.items())
    }
    info = {"rotulo": rotulo, "par": False, "por_classe": dict(Counter(r["label"] for r in rows))}
    return Conjunto(
        rows,
        [fonte_banco(len(rows), licc, f"título + resumo → {rotulo} (OpenAlex)")],
        recusados,
        labels,
        info,
        licc,
    )
