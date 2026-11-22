"""errei-resumo-v2: papel retórico de cada frase do resumo (NBR 6028), com a classe conclusão.

Rótulos fracos de graça: em resumos estruturados ("Objetivo: ... Métodos: ...") cada frase
herda o cabeçalho da sua parte. O cabeçalho é retirado do texto, porque no uso real (NBR
6028) o resumo é um parágrafo corrido. Soma-se o CSAbstruct (Apache-2.0) e, se existir, a
tradução pt-BR dele feita para o errei-resumo-v1.

Entrada igual à do errei (``errei.resumocheck.entrada``): ``[i/n] frase`` com a frase
anterior como par (``—`` na primeira).
"""

from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any

from banco.banco import Banco
from comum.util import PASTA, caminho, frases

from modelos import Conjunto, baixar, balancear, exemplo, fonte_banco, limitar, lotes, obras

NOME = "errei-resumo-v2"
TAREFA = "classificacao"
LABELS = ["contexto", "objetivo", "metodo", "resultado", "conclusao", "outro"]
CSA = ["background", "method", "objective", "other", "result"]
CSA_MAP = {
    "background": "contexto",
    "method": "metodo",
    "objective": "objetivo",
    "other": "outro",
    "result": "resultado",
}
HF = "https://huggingface.co/datasets/allenai/csabstruct/resolve/main/data/"
CSA_ARQS = {
    "train": "train-00000-of-00001-e4ddac953345ce34.parquet",
    "validation": "validation-00000-of-00001-6393d2add96db558.parquet",
    "test": "test-00000-of-00001-be7e891381aedbe0.parquet",
}
CABECALHOS = {
    "contexto": r"introdu[çc](?:ão|ao)|introduction|introducci[oó]n|background|contexto|context|"
    r"fundamentos?|justificativa|rationale|antecedentes",
    "objetivo": r"objetivos?|objectives?|aims?|purpose|prop[oó]sito|goals?|finalidade",
    "metodo": r"materiais? e m[eé]todos|materials? and methods|material y m[eé]todos?|m[eé]todos?|"
    r"methods?|metodologia|metodolog[ií]a|methodology|design|delineamento|setting|"
    r"participants|participantes|casu[ií]stica|local",
    "resultado": r"resultados?|results?|findings|achados",
    "conclusao": r"conclus(?:ão|ões|ao|oes|ion|ions|iones|ión)|considera[çc](?:ões|oes) finais|"
    r"final considerations|implica[çc](?:ões|oes)|implications",
}
_ALT = "|".join(f"(?P<{k}>{v})" for k, v in CABECALHOS.items())
CAB_RX = re.compile(rf"(?:^|(?<=[.!?;)\s]))\s*(?:{_ALT})\s*[:：]\s*", re.IGNORECASE)
OUTRO_CAB = re.compile(r"(?:^|(?<=[.!?]\s))[A-ZÀ-Ý][\wÀ-ÿ ]{2,30}:\s")

CARTAO = """---
license: {licenca}
language: [pt, en, es]
tags: [errei, nbr-6028, resumo, sequence-classification]
---

# errei-resumo-v2

Classifica cada frase de um resumo acadêmico em **contexto, objetivo, método, resultado,
conclusão ou outro** (elementos da NBR 6028:2021). Substitui o `errei-resumo-v1`, cuja base
(MoritzLaurer, ajustada no XNLI) é CC BY-NC.

Entrada: `[i/n] frase` com a frase anterior como segundo segmento (`—` na primeira), igual
a `errei.resumocheck.entrada`.

Dados: frases de resumos estruturados de artigos em CC BY/CC0 (o rótulo é o cabeçalho da
parte, retirado do texto) e o CSAbstruct (Apache-2.0). Rótulos fracos: confira a métrica
por fonte abaixo.
"""


def dividir_estruturado(texto: str) -> list[tuple[str, str]] | None:
    """[(frase, rótulo)] de um resumo estruturado; None se não der para rotular."""
    ms = list(CAB_RX.finditer(texto))
    if len(ms) < 2:
        return None
    out: list[tuple[str, str]] = []
    for i, m in enumerate(ms):
        rot = next(k for k, v in m.groupdict().items() if v)
        fim = ms[i + 1].start() if i + 1 < len(ms) else len(texto)
        trecho = texto[m.end() : fim].strip()
        if OUTRO_CAB.search(trecho):  # cabeçalho que não conhecemos no meio: parte ambígua
            return None
        out += [(f, rot) for f in frases(trecho)]
    if len(out) < 3 or len({r for _, r in out}) < 3:
        return None
    return out


def entrada(fs: list[str], i: int) -> tuple[str, str]:
    """Igual a errei.resumocheck.entrada (formato do treino = formato do uso)."""
    return f"[{i + 1}/{len(fs)}] {fs[i]}", (fs[i - 1] if i else "—")


def linhas_resumo(fs: list[str], rots: list[str], **extra: Any) -> list[dict[str, Any]]:
    out = []
    for i, rot in enumerate(rots):
        a, b = entrada(fs, i)
        out.append({"texto": a, "par": b, "label": rot, **extra})
    return out


def csabstruct(m: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any] | None, str]:
    import pyarrow.parquet as pq

    cache = PASTA / "dados" / "_cache" / "csabstruct"
    trad: dict[str, str] = {}
    arq_trad = caminho(m["csabstruct_traducoes"]) if m.get("csabstruct_traducoes") else None
    if arq_trad and arq_trad.is_file():
        for ln in arq_trad.open(encoding="utf-8"):
            if ln.strip():
                r = json.loads(ln)
                trad[r["en"]] = r["pt"]
    rows: list[dict[str, Any]] = []
    for nome in CSA_ARQS.values():
        p = baixar(HF + nome, cache / nome)
        for r in pq.read_table(p).to_pylist():
            fs = [s.strip() for s in r["sentences"]]
            rots = [CSA_MAP[CSA[x]] for x in r["labels"]]
            g = f"csabstruct:{r['abstract_id']}"
            rows += linhas_resumo(fs, rots, grupo=g, fonte="csabstruct", lingua="en")
            if fs and all(f in trad for f in fs):
                rows += linhas_resumo(
                    [trad[f] for f in fs], rots, grupo=g, fonte="csabstruct-pt", lingua="pt"
                )
    aceito = {
        "nome": "CSAbstruct",
        "licenca": "Apache-2.0",
        "fonte": "allenai/csabstruct (Hugging Face)",
        "n": len(rows),
    }
    nota = (
        f"tradução pt-BR do CSAbstruct: {arq_trad} (opus-mt, CC BY 4.0)"
        if trad
        else "sem tradução pt-BR do CSAbstruct"
    )
    return rows, aceito, nota


def construir(b: Banco, m: dict[str, Any], fumaca: bool) -> Conjunto:
    rows: list[dict[str, Any]] = []
    licc: Counter[str] = Counter()
    maximo = int(m.get("max_resumos", 0))
    n_res = 0
    for lote in lotes(obras(b, m)):
        idx = {r["id"]: r for r in lote}
        sql = (
            f"SELECT obra_id, lingua, texto FROM resumos WHERE estruturado = 1 AND obra_id IN "
            f"({', '.join('?' * len(idx))})"
        )
        for oid, lg, texto in b.con.execute(sql, list(idx)):
            par = dividir_estruturado(texto)
            if not par:
                continue
            r = idx[oid]
            fs, rots = [f for f, _ in par], [x for _, x in par]
            for ln in linhas_resumo(fs, rots, fonte="banco", lingua=lg):
                rows.append({**exemplo(r), **ln})
            licc[r["licenca"]] += 1
            n_res += 1
        if maximo and n_res >= maximo:
            break
    aceitos = [fonte_banco(len(rows), licc, f"resumos estruturados ({n_res} resumos)")]
    recusados: dict[str, str] = {}
    info: dict[str, Any] = {"par": True}
    if m.get("csabstruct", True) and not fumaca:
        cs, aceito, nota = csabstruct(m)
        rows += cs
        if aceito:
            aceitos.append(aceito)
        info["csabstruct"] = nota
    rows = balancear(rows, "label", int(m.get("max_por_classe", 0)), int(m.get("semente", 42)))
    rows = limitar(rows, int(m.get("max_exemplos", 0)), int(m.get("semente", 42)))
    info["por_classe"] = dict(Counter(r["label"] for r in rows))
    return Conjunto(rows, aceitos, recusados, LABELS, info, licc)
