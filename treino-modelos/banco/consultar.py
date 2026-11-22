"""Consulta o banco de treino: números, amostras e exportação das obras classificadas.

Uso (da raiz do repositório):
    python treino-modelos/banco/consultar.py                       # estatísticas
    python treino-modelos/banco/consultar.py --amostra 5 --qualis A1 A2 --idioma pt
    python treino-modelos/banco/consultar.py --exportar obras.csv --scopus --wos SCIE SSCI
    python treino-modelos/banco/consultar.py --sql "SELECT campo, COUNT(*) FROM obras GROUP BY 1"

Os filtros (--qualis, --scopus, --wos, --idioma, --ano-min, --campo, --top10) são os
mesmos aceitos em ``[<modelo>.filtros]`` no config/modelos.toml.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from comum.util import cortar

from banco.banco import abrir, classe, config_banco


def filtros(a: argparse.Namespace) -> dict[str, Any]:
    f: dict[str, Any] = {}
    if a.qualis:
        f["qualis"] = [q.upper() for q in a.qualis]
    if a.scopus:
        f["scopus"] = True
    if a.wos is not None:
        f["wos"] = [w.upper() for w in a.wos] or True
    if a.idioma:
        f["idiomas"] = a.idioma
    if a.ano_min:
        f["ano_min"] = a.ano_min
    if a.campo:
        f["campos"] = a.campo
    if a.top10:
        f["top10"] = True
    return f


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="consulta o banco de treino")
    ap.add_argument("--config")
    ap.add_argument("--banco")
    ap.add_argument("--qualis", nargs="*", help="estratos (A1 A2 ...)")
    ap.add_argument("--scopus", action="store_true")
    ap.add_argument("--wos", nargs="*", help="sem valor: qualquer coleção; ou SCIE SSCI AHCI ESCI")
    ap.add_argument("--idioma", nargs="*")
    ap.add_argument("--ano-min", type=int)
    ap.add_argument("--campo", nargs="*")
    ap.add_argument("--top10", action="store_true")
    ap.add_argument(
        "--todas", action="store_true", help="inclui obras sem licença aberta (só metadados)"
    )
    ap.add_argument("--amostra", type=int, default=0, help="mostra N obras com resumo")
    ap.add_argument("--exportar", type=Path, help="CSV com as obras filtradas e a classificação")
    ap.add_argument("--sql", help="consulta SQL livre (só leitura)")
    a = ap.parse_args(argv)
    with abrir(a.banco, config_banco(a.config)) as b:
        if a.sql:
            if not a.sql.lstrip().lower().startswith(("select", "with")):
                print("erro: só SELECT/WITH", file=sys.stderr)
                return 1
            b.con.execute("PRAGMA query_only = ON")
            cur = b.con.execute(a.sql)
            print("\t".join(d[0] for d in cur.description or []))
            for r in cur.fetchmany(200):
                print("\t".join("" if v is None else str(v) for v in r))
            return 0
        f = filtros(a)
        texto = not a.todas
        if a.amostra:
            rows = list(b.obras(f, texto, a.amostra))
            res = b.mapa("resumos", [r["id"] for r in rows])
            for r in rows:
                print(
                    f"{r['id']} · {r['ano']} · {r['idioma']} · {r['licenca']} · {r['campo']} · "
                    f"{json.dumps(classe(r), ensure_ascii=False)}"
                )
                print(f"  {r['titulo']}")
                print(f"  {cortar(res.get(r['id'], '(sem resumo)'), 300)}\n")
        if a.exportar:
            cols = [
                "id",
                "doi",
                "titulo",
                "ano",
                "idioma",
                "licenca",
                "campo",
                "subcampo",
                "citacoes",
                "percentil_citacoes",
                "top10",
            ]
            n = 0
            with a.exportar.open("w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow([*cols, "revista", "qualis", "scopus", "scopus_percentil", "wos"])
                nomes = dict(b.con.execute("SELECT fonte_id, nome FROM fontes_classe").fetchall())
                for r in b.obras(f, texto):
                    w.writerow(
                        [r[c] for c in cols]
                        + [
                            nomes.get(r["fonte_id"], ""),
                            r["c_qualis"] or "",
                            r["c_scopus"] or 0,
                            r["c_scopus_pct"] or "",
                            r["c_wos"] or "",
                        ]
                    )
                    n += 1
            print(f"[OK] {n} obras em {a.exportar}")
        if not (a.amostra or a.exportar):
            e = b.estatisticas()
            if f:
                e["filtradas"] = sum(1 for _ in b.obras(f, texto))
            print(json.dumps(e, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
