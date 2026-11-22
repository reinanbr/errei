"""Construtores de dados de cada modelo (itens 2 a 9 do gpu_train_list.md).

Cada módulo define ``NOME`` (nome do pacote), ``TAREFA`` (classificacao, tokens,
biencoder, seq2seq ou mlm), ``CARTAO`` (texto do README do modelo) e
``construir(banco, cfg, fumaca) -> Conjunto``. Todo exemplo leva ``grupo`` (a obra de
origem), para que nada de uma obra vaze entre treino, validação e teste, e ``classe``
(Qualis, Scopus e WoS da revista), para medir o modelo por estrato.
"""

from __future__ import annotations

import importlib
import random
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any

from banco.banco import Banco, classe
from comum import licencas

MODELOS = ("resumo", "busca", "chaves", "ref", "area", "secoes", "ia", "trad", "base")
MODULO = {"base": "pretreino"}
FONTE_BANCO = "banco errei: metadados do OpenAlex (CC0), SciELO ArticleMeta e Europe PMC"


def obter(nome: str) -> ModuleType:
    if nome not in MODELOS:
        raise SystemExit(f"erro: modelo '{nome}' desconhecido; use um de: {', '.join(MODELOS)}")
    return importlib.import_module(f"modelos.{MODULO.get(nome, nome)}")


@dataclass
class Conjunto:
    rows: list[dict[str, Any]]
    aceitos: list[dict[str, Any]]
    recusados: dict[str, str] = field(default_factory=dict)
    labels: list[str] | None = None
    info: dict[str, Any] = field(default_factory=dict)
    licencas: Counter[str] = field(default_factory=Counter)


def filtros(m: dict[str, Any]) -> dict[str, Any]:
    f = dict(m.get("filtros") or {})
    f["aceitar_sa"] = bool(m.get("aceitar_sa"))
    return f


def obras(b: Banco, m: dict[str, Any], texto: bool = True, limite: int = 0) -> Iterator[Any]:
    """Obras que passam nos filtros do modelo; com ``texto``, só licença aberta comercial."""
    sa = bool(m.get("aceitar_sa"))
    for r in b.obras(filtros(m), texto, limite):
        if texto and not licencas.aceita(r["licenca"], sa):
            continue  # o SQL já filtra; conferência dupla
        yield r


def lotes(it: Iterable[Any], n: int = 2000) -> Iterator[list[Any]]:
    lote: list[Any] = []
    for x in it:
        lote.append(x)
        if len(lote) >= n:
            yield lote
            lote = []
    if lote:
        yield lote


def exemplo(r: Any, **campos: Any) -> dict[str, Any]:
    """Exemplo vindo de uma obra do banco: guarda o grupo e a classificação da revista."""
    return {**campos, "grupo": r["id"], "classe": classe(r)}


def fonte_banco(n: int, licc: Counter[str], descricao: str) -> dict[str, Any]:
    return {
        "nome": descricao,
        "licenca": ", ".join(sorted(licc)) or "—",
        "fonte": FONTE_BANCO,
        "n": n,
    }


def balancear(
    rows: list[dict[str, Any]], chave: str, maximo: int, semente: int
) -> list[dict[str, Any]]:
    if not maximo:
        return rows
    rnd = random.Random(semente)
    por: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        por.setdefault(str(r[chave]), []).append(r)
    out: list[dict[str, Any]] = []
    for v in por.values():
        rnd.shuffle(v)
        out += v[:maximo]
    return out


def limitar(rows: list[dict[str, Any]], maximo: int, semente: int) -> list[dict[str, Any]]:
    if maximo and len(rows) > maximo:
        rows = list(rows)
        random.Random(semente).shuffle(rows)
        rows = rows[:maximo]
    return rows


def baixar(url: str, destino: Path) -> Path:
    """Baixa uma vez para o cache (sem rede na fumaça: o chamador não chega aqui)."""
    from comum.rede import cliente

    if destino.is_file() and destino.stat().st_size > 0:
        return destino
    destino.parent.mkdir(parents=True, exist_ok=True)
    r = cliente({}).get(url)
    if r is None or r.status != 200:
        raise SystemExit(f"erro: não consegui baixar {url} (status {getattr(r, 'status', None)})")
    tmp = destino.with_suffix(destino.suffix + ".tmp")
    tmp.write_bytes(r.corpo)
    tmp.rename(destino)
    return destino
