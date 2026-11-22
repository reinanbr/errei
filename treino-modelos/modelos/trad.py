"""errei-trad: tradutor acadêmico pt ↔ en (seq2seq), no lugar dos tradutores Helsinki.

Pares paralelos da mesma obra: títulos e resumos em pt e en (SciELO e OpenAlex, obras em
CC BY/CC0). Quando os dois resumos têm o mesmo número de frases e comprimentos parecidos,
viram pares de 1 a 3 frases alinhadas pela posição; senão, o resumo inteiro (se couber).
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from banco.banco import Banco
from comum.util import frases

from modelos import Conjunto, exemplo, fonte_banco, limitar, lotes, obras

NOME = "errei-trad"
TAREFA = "seq2seq"
NOMES = {"pt": "português", "en": "inglês", "es": "espanhol"}

CARTAO = """---
license: {licenca}
language: [pt, en]
tags: [errei, translation, text2text-generation]
---

# errei-trad

Tradutor acadêmico português ↔ inglês, treinado com títulos e resumos paralelos de artigos
em CC BY/CC0. Substitui os tradutores Helsinki-NLP no errei (consulta do `literatura` e
preparação de dados).

Entrada: `traduza pt para en: <texto>` ou `traduza en para pt: <texto>`.
"""


def prefixo(a: str, b: str) -> str:
    return f"traduza {a} para {b}: "


def razao_ok(x: str, y: str) -> bool:
    return 0.5 <= (len(x) + 1) / (len(y) + 1) <= 2.0


def pares_resumo(a: str, b: str, max_chars: int) -> list[tuple[str, str]]:
    fa, fb = frases(a), frases(b)
    if len(fa) == len(fb) >= 2 and all(razao_ok(x, y) for x, y in zip(fa, fb, strict=False)):
        out = []
        i = 0
        while i < len(fa):
            n = 1 + (i % 3)  # blocos de 1, 2 e 3 frases
            out.append((" ".join(fa[i : i + n]), " ".join(fb[i : i + n])))
            i += n
        return out
    if len(a) <= max_chars and len(b) <= max_chars and razao_ok(a, b):
        return [(a, b)]
    return []


def construir(b: Banco, m: dict[str, Any], fumaca: bool) -> Conjunto:
    direcoes = [tuple(d.split("-")) for d in (m.get("direcoes") or ["pt-en", "en-pt"])]
    linguas = sorted({x for d in direcoes for x in d})
    max_chars = int(m.get("max_chars", 1200))
    rows: list[dict[str, Any]] = []
    licc: Counter[str] = Counter()
    maximo = int(m.get("max_pares", 0))
    for lote in lotes(obras(b, m)):
        ids = [r["id"] for r in lote]
        tit, res = b.por_lingua("titulos", ids), b.por_lingua("resumos", ids)
        for r in lote:
            ts, rs = tit.get(r["id"]) or {}, res.get(r["id"]) or {}
            if not any(lg in rs or lg in ts for lg in linguas):
                continue
            usou = False
            for x, y in direcoes:
                pares: list[tuple[str, str, str]] = []
                if (
                    m.get("com_titulos", True)
                    and ts.get(x)
                    and ts.get(y)
                    and razao_ok(ts[x], ts[y])
                ):
                    pares.append(("titulo", ts[x], ts[y]))
                if rs.get(x) and rs.get(y):
                    pares += [("resumo", a, c) for a, c in pares_resumo(rs[x], rs[y], max_chars)]
                for tipo, a, c in pares:
                    rows.append(
                        exemplo(r, entrada=prefixo(x, y) + a, saida=c, tipo=tipo, lingua=f"{x}-{y}")
                    )
                    usou = True
            if usou:
                licc[r["licenca"]] += 1
        if maximo and len(rows) >= maximo:
            break
    rows = limitar(rows, maximo, int(m.get("semente", 42)))
    info = {
        "direcoes": ["-".join(d) for d in direcoes],
        "por_direcao": dict(Counter(r["lingua"] for r in rows)),
        "por_tipo": dict(Counter(r["tipo"] for r in rows)),
        "prefixo": "traduza <a> para <b>: ",
    }
    return Conjunto(
        rows, [fonte_banco(len(rows), licc, "títulos e resumos paralelos")], {}, None, info, licc
    )
