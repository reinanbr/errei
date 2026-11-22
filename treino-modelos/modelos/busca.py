"""errei-busca: bi-encoder bilíngue (pt, en, es) para busca semântica de literatura.

Pares positivos da mesma obra: título ↔ resumo, título numa língua ↔ resumo na outra,
resumo pt ↔ resumo en, uma frase do resumo ↔ o resumo na outra língua (o caso do errei:
frase do artigo × resumo da fonte) e palavras-chave ↔ resumo. Negativo difícil: resumo de
outra obra do mesmo campo e da mesma língua. Treino contrastivo (InfoNCE) com os outros
exemplos do lote como negativos.
"""

from __future__ import annotations

import random
from collections import Counter
from typing import Any

from banco.banco import Banco
from comum.util import cortar, frases

from modelos import Conjunto, exemplo, fonte_banco, limitar, lotes, obras

NOME = "errei-busca"
TAREFA = "biencoder"
TIPOS = ("titulo_resumo", "titulo_resumo_x", "resumo_x", "frase_resumo_x", "chaves_resumo")

CARTAO = """---
license: {licenca}
language: [pt, en, es]
tags: [errei, sentence-embeddings, retrieval, bi-encoder]
pipeline_tag: sentence-similarity
---

# errei-busca

Embeddings multilíngues para achar literatura pelo sentido: uma frase em português e o
resumo de um artigo em inglês que falam da mesma coisa ficam próximos. Tira do errei a
dependência do Gemini (consultas do `nacionais`) e do tradutor na busca do `literatura`.
Quem decide se a fonte sustenta a frase continua sendo o errei-cita.

Uso: média dos vetores do último estado (mean pooling), normalizada; prefixos
`query: ` na consulta e `passage: ` no documento (convenção do E5). Veja
`errei_tarefa.json`.
"""


def construir(b: Banco, m: dict[str, Any], fumaca: bool) -> Conjunto:
    rnd = random.Random(int(m.get("semente", 42)))
    tipos = tuple(m.get("tipos") or TIPOS)
    por_obra = int(m.get("pares_por_obra", 3))
    max_pas = int(m.get("max_chars_passagem", 1500))
    negs = bool(m.get("negativos_dificeis", True))
    reserva: dict[tuple[str, str], list[str]] = {}
    rows: list[dict[str, Any]] = []
    licc: Counter[str] = Counter()
    maximo = int(m.get("max_pares", 0))
    for lote in lotes(obras(b, m)):
        ids = [r["id"] for r in lote]
        tit, res = b.por_lingua("titulos", ids), b.por_lingua("resumos", ids)
        kws = b.por_lingua("palavras_chave", ids, ["autor", "sintetico"])
        for r in lote:
            rs = {
                lg: cortar(t, max_pas) for lg, t in (res.get(r["id"]) or {}).items() if len(t) > 200
            }
            if not rs:
                continue
            ts = tit.get(r["id"]) or {}
            if not ts and r["titulo"] and r["idioma"]:
                ts = {r["idioma"]: r["titulo"]}
            ks = kws.get(r["id"]) or {}
            cands: list[
                tuple[str, str, str, str]
            ] = []  # (tipo, consulta, passagem, língua da passagem)
            for lg, p in rs.items():
                if "titulo_resumo" in tipos and ts.get(lg):
                    cands.append(("titulo_resumo", ts[lg], p, lg))
                if "chaves_resumo" in tipos and len(ks.get(lg) or []) >= 3:
                    cands.append(("chaves_resumo", "; ".join(ks[lg]), p, lg))
                for lg2, p2 in rs.items():
                    if lg2 == lg:
                        continue
                    if "titulo_resumo_x" in tipos and ts.get(lg):
                        cands.append(("titulo_resumo_x", ts[lg], p2, lg2))
                    if "resumo_x" in tipos and lg < lg2:
                        cands.append(("resumo_x", p, p2, lg2))
                    fs = [f for f in frases(p) if 40 <= len(f) <= 400]
                    if "frase_resumo_x" in tipos and fs:
                        cands.append(("frase_resumo_x", rnd.choice(fs), p2, lg2))
            rnd.shuffle(cands)
            campo = r["campo"] or "?"
            for tipo, q, p, lg in cands[:por_obra]:
                ex = exemplo(r, consulta=q, passagem=p, tipo=tipo, lingua=lg)
                pool = reserva.get((campo, lg)) or []
                if negs and pool:
                    ex["negativo"] = rnd.choice(pool)
                rows.append(ex)
            licc[r["licenca"]] += 1
            for (
                lg,
                p,
            ) in rs.items():  # entra na reserva depois de usada: o negativo é sempre de outra obra
                pool = reserva.setdefault((campo, lg), [])
                if len(pool) < 500:
                    pool.append(p)
                else:
                    pool[rnd.randrange(500)] = p
        if maximo and len(rows) >= maximo:
            break
    rows = limitar(rows, maximo, int(m.get("semente", 42)))
    info = {
        "por_tipo": dict(Counter(r["tipo"] for r in rows)),
        "prefixo_consulta": m.get("prefixo_consulta", "query: "),
        "prefixo_passagem": m.get("prefixo_passagem", "passage: "),
    }
    return Conjunto(
        rows,
        [fonte_banco(len(rows), licc, "títulos, resumos e palavras-chave (pares da mesma obra)")],
        {},
        None,
        info,
        licc,
    )
