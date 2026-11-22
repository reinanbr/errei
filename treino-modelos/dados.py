"""Monta os dados de treino de um modelo a partir do banco.

Uso (da raiz do repositório):
    python treino-modelos/dados.py --modelo resumo
    python treino-modelos/dados.py --modelo ref --max 50000     # limita os exemplos
    python treino-modelos/dados.py --modelo area --fumaca --banco /tmp/b.sqlite --saida /tmp/d

Escreve ``dados/<modelo>/{treino,validacao,teste}.jsonl`` e ``manifesto.json`` (fontes,
licenças das obras, classes, filtros, classificação Qualis/Scopus/WoS das obras usadas).
A divisão é por obra (``grupo``) e estável: a mesma obra cai sempre na mesma parte.
Recusa o conjunto se alguma obra tiver licença NC ou ND.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from banco.banco import abrir, config_banco
from comum import licencas
from comum.util import CONFIG_MODELOS, caminho, carregar_toml, dividir, gravar_jsonl
from modelos import MODELOS, obter


def config_modelo(nome: str, arquivo: str | None) -> tuple[dict[str, Any], dict[str, Any]]:
    cfg = carregar_toml(arquivo, CONFIG_MODELOS)
    if nome not in cfg:
        raise SystemExit(f"erro: falta a seção [{nome}] em {cfg['_arquivo']}")
    return cfg, {**cfg.get("geral", {}), **cfg[nome]}


def resumo_classes(rows: list[dict[str, Any]]) -> dict[str, Any]:
    cs = [r["classe"] for r in rows if r.get("classe")]
    obras = {r["grupo"]: r["classe"] for r in rows if r.get("classe")}
    return {
        "exemplos_com_classe": len(cs),
        "obras": len(obras),
        "qualis_faixa": dict(Counter(c["qualis_faixa"] for c in obras.values())),
        "qualis_estrato": dict(
            sorted(Counter(c["qualis"] or "sem" for c in obras.values()).items())
        ),
        "scopus": sum(c["scopus"] for c in obras.values()),
        "wos": dict(Counter(c["wos"] or "fora" for c in obras.values())),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="monta os dados de treino de um modelo")
    ap.add_argument("--modelo", required=True, choices=MODELOS)
    ap.add_argument("--config")
    ap.add_argument("--config-banco")
    ap.add_argument("--banco", help="arquivo SQLite (padrão: config/banco.toml)")
    ap.add_argument("--saida", help="pasta (padrão: <geral.dados>/<modelo>)")
    ap.add_argument("--max", type=int, default=0, help="limite de exemplos")
    ap.add_argument("--fumaca", action="store_true", help="banco sintético, divisão 60/20/20")
    a = ap.parse_args(argv)
    _, m = config_modelo(a.modelo, a.config)
    mod = obter(a.modelo)
    saida = Path(a.saida) if a.saida else caminho(m["dados"]) / a.modelo
    cb = config_banco(a.config_banco)
    m["aceitar_sa"] = bool(cb["banco"].get("aceitar_sa"))
    if a.max:
        for k in ("max_exemplos", "max_pares", "max_textos"):
            m[k] = a.max
        m["max_obras"] = m["max_resumos"] = a.max
    with abrir(a.banco, cb) as b:
        if b.contar("SELECT COUNT(*) FROM fontes_classe") == 0 and b.contar(
            "SELECT COUNT(*) FROM fontes"
        ):
            b.atualizar_classes()
        conj = mod.construir(b, m, a.fumaca)
        stats = b.estatisticas()
    if not conj.rows:
        print(
            f"erro: nenhum exemplo para {a.modelo}; o banco tem os dados necessários? "
            "(veja: python treino-modelos/banco/consultar.py)",
            file=sys.stderr,
        )
        return 1
    ruins = {
        k: v
        for k, v in conj.licencas.items()
        if licencas.tem_nc(k) or "-nd" in licencas.normalizar(k)
    }
    if ruins:
        print(
            f"erro: obras com licença NC/ND entraram no conjunto: {ruins}; nada foi gravado",
            file=sys.stderr,
        )
        return 1
    val, tes = (0.2, 0.2) if a.fumaca else (float(m["validacao"]), float(m["teste"]))
    partes = dividir(conj.rows, int(m["semente"]), val, tes)
    if any(not v for v in partes.values()):
        print(
            f"erro: alguma parte ficou vazia ({ {k: len(v) for k, v in partes.items()} }); "
            "poucos exemplos",
            file=sys.stderr,
        )
        return 1
    for nome, rows in partes.items():
        gravar_jsonl(saida / f"{nome}.jsonl", rows)
    manifesto = {
        "modelo": a.modelo,
        "nome": mod.NOME,
        "tarefa": mod.TAREFA,
        "labels": conj.labels,
        "data": date.today().isoformat(),
        "semente": int(m["semente"]),
        "divisao": {k: len(v) for k, v in partes.items()},
        "aceitos": conj.aceitos,
        "recusados": conj.recusados,
        "licencas_obras": dict(conj.licencas),
        "info": conj.info,
        "filtros": m.get("filtros") or {},
        "classificacao": resumo_classes(conj.rows),
        "banco": {
            k: stats[k]
            for k in ("arquivo", "obras", "obras_texto_aberto", "fontes", "classificacoes")
        },
        "fumaca": a.fumaca,
    }
    (saida / "manifesto.json").write_text(
        json.dumps(manifesto, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"[OK] {mod.NOME}: {manifesto['divisao']} em {saida}")
    if conj.labels and mod.TAREFA == "classificacao":
        print(f"classes: {dict(Counter(r['label'] for r in conj.rows))}")
    print(
        f"classificação das obras usadas: {json.dumps(manifesto['classificacao'], ensure_ascii=False)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
