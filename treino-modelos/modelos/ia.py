"""errei-ia: detector de texto gerado por IA (humano × ia).

Humano: resumos (e, se ligado, parágrafos de seções) de obras publicadas até
``ano_humano_max`` (2021, antes dos LLMs populares). IA: textos de ``textos_ia``, gerados
por ``gerar_ia.py`` com modelos abertos (Apache-2.0/MIT) na própria GPU, a partir do título
e das palavras-chave da mesma obra, por reescrita do resumo ou continuando o começo dele.
Nada de Gemini, Claude ou ChatGPT: os termos desses serviços proíbem e o detector
aprenderia o estilo de um só fornecedor.

O texto humano e o de IA da mesma obra ficam na mesma divisão (``grupo``), para o modelo
não decorar o assunto.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from banco.banco import Banco, classe
from comum.util import cortar

from modelos import Conjunto, balancear, exemplo, fonte_banco, limitar, lotes, obras

NOME = "errei-ia"
TAREFA = "classificacao"
LABELS = ["humano", "ia"]
LICENCAS_GERADOR = {"apache-2.0", "mit"}
PROIBIDOS = re.compile(r"gemini|claude|gpt-?[345o]|chatgpt|openai|anthropic|bard|copilot", re.I)
_PREFIXO = re.compile(
    r"^\s*(?:(?:claro|certamente|aqui est[áa]|segue|sure|here is|here's|certainly)[^\n:]*[:\n]|"
    r"(?:resumo|abstract|resumen|t[íi]tulo|title)\s*[:.]\s*)+",
    re.I,
)

CARTAO = """---
license: {licenca}
language: [pt, en]
tags: [errei, ai-text-detection, text-classification]
---

# errei-ia

Estima se um trecho acadêmico foi escrito por IA. Substitui o detector externo do
verificador `ia` do errei. **É um indício, não prova**: a taxa de falso positivo foi
fixada na validação (veja `errei_limiares.json`) e deve ser informada junto do resultado.

Humano: textos de artigos em CC BY/CC0 publicados até {ano_max}. IA: textos gerados na
própria GPU por modelos abertos (licenças no manifesto), a partir do título e das
palavras-chave, por reescrita ou por continuação. Nenhum texto de serviços comerciais de
IA entrou no treino.
"""


def limpar(t: str) -> str:
    t = re.sub(r"[*_#`>]+", " ", t or "")
    t = _PREFIXO.sub("", t.strip())
    return " ".join(t.split())


def construir(b: Banco, m: dict[str, Any], fumaca: bool) -> Conjunto:
    ano_max = int(m.get("ano_humano_max", 2021))
    min_chars = 30 if fumaca else int(m.get("min_chars", 300))
    max_chars = int(m.get("max_chars", 2000))
    semente = int(m.get("semente", 42))
    recusados: dict[str, str] = {}
    geradores: Counter[str] = Counter()
    licenca_ger: dict[str, str] = {}
    ia: list[dict[str, Any]] = []
    sql = (
        "SELECT t.*, o.licenca, c.qualis_melhor AS c_qualis, c.scopus AS c_scopus, "
        "c.scopus_percentil AS c_scopus_pct, c.wos_colecoes AS c_wos FROM textos_ia t "
        "LEFT JOIN obras o ON o.id = t.obra_id LEFT JOIN fontes_classe c ON c.fonte_id = o.fonte_id"
    )
    for r in b.con.execute(sql):
        lic = str(r["modelo_licenca"] or "").lower()
        if PROIBIDOS.search(r["modelo"] or "") or lic not in LICENCAS_GERADOR:
            recusados[f"gerador {r['modelo']}"] = (
                f"licença '{r['modelo_licenca']}' ou fornecedor não permitido"
            )
            continue
        t = limpar(r["texto"])
        if len(t) < min_chars:
            continue
        geradores[r["modelo"]] += 1
        licenca_ger[r["modelo"]] = r["modelo_licenca"]
        ia.append(
            {
                "texto": cortar(t, max_chars),
                "label": "ia",
                "grupo": r["obra_id"] or f"ia:{r['id']}",
                "classe": classe(r),
                "lingua": r["lingua"],
                "tipo": r["tipo"],
                "modo": r["modo"],
            }
        )
    com_ia = {r["grupo"] for r in ia}
    hum_par: list[dict[str, Any]] = []
    hum: list[dict[str, Any]] = []
    licc: Counter[str] = Counter()
    m2 = {**m, "filtros": {**(m.get("filtros") or {}), "ano_max": ano_max}}
    for lote in lotes(obras(b, m2)):
        ids = [r["id"] for r in lote]
        res = b.por_lingua("resumos", ids)
        secs = b.por_lingua("secoes", ids) if m.get("incluir_secoes", True) else {}
        for r in lote:
            destino = hum_par if r["id"] in com_ia else hum
            n0 = len(destino)
            for lg, t in (res.get(r["id"]) or {}).items():
                t = limpar(t)
                if len(t) >= min_chars:
                    destino.append(
                        exemplo(
                            r,
                            texto=cortar(t, max_chars),
                            label="humano",
                            lingua=lg,
                            tipo="resumo",
                            modo="humano",
                        )
                    )
            for lg, ss in (secs.get(r["id"]) or {}).items():
                paras = [
                    p for s in ss for p in (s["texto"] or "").split("\n") if len(p) >= min_chars
                ]
                for p in paras[:2]:
                    destino.append(
                        exemplo(
                            r,
                            texto=cortar(p, max_chars),
                            label="humano",
                            lingua=lg,
                            tipo="secao",
                            modo="humano",
                        )
                    )
            if len(destino) > n0:
                licc[r["licenca"]] += 1
    if not ia:
        raise SystemExit(
            "erro: nenhum texto de IA utilizável (textos_ia vazia, curtos demais ou de gerador "
            f"recusado: {recusados or 'nenhum'}); rode antes: python treino-modelos/gerar_ia.py"
        )
    # pares da mesma obra primeiro (os mais informativos), depois humanos avulsos até a proporção
    alvo = int(len(ia) * float(m.get("proporcao_humano", 1.0)))
    humanos = limitar(hum_par, alvo, semente) if alvo else []
    falta = alvo - len(humanos)
    if falta > 0:
        humanos += limitar(hum, falta, semente)
    rows = balancear(ia + humanos, "label", int(m.get("max_por_classe", 0)), semente)
    aceitos = [fonte_banco(len(humanos), licc, f"textos humanos publicados até {ano_max}")]
    for g, n in geradores.most_common():
        aceitos.append(
            {
                "nome": f"textos gerados por {g}",
                "licenca": licenca_ger[g],
                "fonte": "gerar_ia.py (na própria GPU)",
                "n": n,
            }
        )
    info = {
        "par": False,
        "ano_humano_max": ano_max,
        "geradores": dict(geradores),
        "por_classe": dict(Counter(r["label"] for r in rows)),
        "por_modo": dict(Counter(r["modo"] for r in rows)),
        "fpr_alvo": float(m.get("fpr_alvo", 0.01)),
    }
    return Conjunto(rows, aceitos, recusados, LABELS, info, licc)
