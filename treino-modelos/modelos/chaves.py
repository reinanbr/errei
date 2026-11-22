"""errei-chaves: título + resumo → palavras-chave (seq2seq, na língua do resumo).

Alvo: as palavras-chave que o próprio autor deu (SciELO ArticleMeta e JATS), não as
geradas pelo OpenAlex. Saída: termos separados por "; ".
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from banco.banco import Banco
from comum.util import cortar

from modelos import Conjunto, exemplo, fonte_banco, limitar, lotes, obras

NOME = "errei-chaves"
TAREFA = "seq2seq"
PREFIXO = "palavras-chave: "

CARTAO = """---
license: {licenca}
language: [pt, en, es]
tags: [errei, keyword-generation, text2text-generation]
---

# errei-chaves

Gera de 3 a 8 palavras-chave para um título e resumo, na língua do texto, separadas por
`; `. Serve para montar as consultas de busca do errei (no lugar das sugeridas pelo Gemini
no `nacionais`) e melhora a função `keywords()` heurística.

Entrada: `palavras-chave: <título>. <resumo>`. Treinado com as palavras-chave dadas pelos
autores de artigos em CC BY/CC0.
"""


def termo(t: str) -> str:
    t = " ".join(t.strip(" .;,").split())
    return " ".join(w if (w.isupper() and len(w) > 1) else w.lower() for w in t.split())


def construir(b: Banco, m: dict[str, Any], fumaca: bool) -> Conjunto:
    origens = list(m.get("origens") or ["autor"])
    if fumaca:
        origens.append("sintetico")
    minimo, maximo_t = int(m.get("min_termos", 3)), int(m.get("max_termos", 8))
    max_chars = int(m.get("max_chars", 2000))
    rows: list[dict[str, Any]] = []
    licc: Counter[str] = Counter()
    maximo = int(m.get("max_exemplos", 0))
    for lote in lotes(obras(b, m)):
        ids = [r["id"] for r in lote]
        tit, res = b.por_lingua("titulos", ids), b.por_lingua("resumos", ids)
        kws = b.por_lingua("palavras_chave", ids, origens)
        for r in lote:
            usou = False
            for lg, termos in (kws.get(r["id"]) or {}).items():
                resumo = (res.get(r["id"]) or {}).get(lg)
                termos = list(dict.fromkeys(termo(t) for t in termos if 1 < len(t) <= 80))
                if not resumo or not (minimo <= len(termos) <= maximo_t):
                    continue
                titulo = (tit.get(r["id"]) or {}).get(lg) or (
                    r["titulo"] if r["idioma"] == lg else ""
                )
                entrada = PREFIXO + cortar(f"{titulo}. {resumo}" if titulo else resumo, max_chars)
                rows.append(exemplo(r, entrada=entrada, saida="; ".join(termos), lingua=lg))
                usou = True
            if usou:
                licc[r["licenca"]] += 1
        if maximo and len(rows) >= maximo:
            break
    rows = limitar(rows, maximo, int(m.get("semente", 42)))
    info = {
        "prefixo": PREFIXO,
        "separador": "; ",
        "origens": origens,
        "por_lingua": dict(Counter(r["lingua"] for r in rows)),
    }
    return Conjunto(
        rows,
        [fonte_banco(len(rows), licc, "resumos e palavras-chave dos autores")],
        {},
        None,
        info,
        licc,
    )
