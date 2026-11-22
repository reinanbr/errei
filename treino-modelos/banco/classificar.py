"""Classifica as revistas do banco pelo Qualis CAPES, Scopus e Web of Science.

As listas oficiais não têm API aberta: baixe os arquivos (veja o LEIAME) e importe.
Tudo é casado pelo ISSN (impresso e eletrônico), que liga a lista às revistas do
OpenAlex (tabela ``issn_fonte``) e, por elas, às obras.

Uso (da raiz do repositório):
    python treino-modelos/banco/classificar.py --qualis classificacoes_publicadas.xlsx
    python treino-modelos/banco/classificar.py --scopus ext_list_October_2026.xlsx \
        --citescore CiteScore_2025.xlsx
    python treino-modelos/banco/classificar.py --wos wos-core_SCIE.csv --wos wos-core_ESCI.csv
    python treino-modelos/banco/classificar.py --openalex     # listas abertas já coletadas
    python treino-modelos/banco/classificar.py --resumo       # só mostra o que há

A coleção do WoS (SCIE, SSCI, AHCI, ESCI) sai do nome do arquivo da Master Journal List
ou de um sufixo: ``--wos lista.csv:SSCI``. Cada importação substitui a edição anterior do
mesmo sistema (use ``--edicao`` para guardar várias, ex.: Qualis 2017-2020 e 2021-2024).
As listas ficam só no seu banco: os termos da Elsevier e da Clarivate não permitem
redistribuí-las, e o errei não publica nada delas.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from comum.planilha import coluna, tabela
from comum.util import normalizar_issn

from banco.banco import ESTRATOS, Banco, abrir, config_banco

COLECOES_WOS = ("SCIE", "SSCI", "AHCI", "ESCI")


def _celula(ln: list[str], i: int | None) -> str:
    return ln[i].strip() if i is not None and i < len(ln) else ""


def _issns(*vals: str) -> list[str]:
    out = []
    for v in vals:
        for parte in re.split(r"[;,/\s]+", v or ""):
            n = normalizar_issn(parte)
            if n and n not in out:
                out.append(n)
    return out


def ler_qualis(p: Path, edicao: str) -> list[dict[str, Any]]:
    cab, linhas, aba = tabela(p, ("issn", "estrato"))
    ci = coluna(cab, "issn")
    ct = coluna(cab, "titulo", "title")
    ca = coluna(cab, "area de avaliacao", "area avaliacao", "area de conhecimento", "area")
    ce = coluna(cab, "estrato", "qualis", exata=False)
    rows = []
    for ln in linhas:
        est = _celula(ln, ce).upper().replace(" ", "")
        if est not in ESTRATOS:
            continue
        for issn in _issns(_celula(ln, ci)):
            rows.append(
                {
                    "issn": issn,
                    "sistema": "qualis",
                    "area": _celula(ln, ca).upper(),
                    "valor": est,
                    "edicao": edicao,
                    "titulo": _celula(ln, ct),
                }
            )
    print(f"Qualis: {len(rows)} linhas válidas (aba '{aba}')")
    return rows


def ler_scopus(p: Path, edicao: str) -> list[dict[str, Any]]:
    """Lista de fontes do Scopus (Source title list, xlsx da Elsevier)."""
    cab, linhas, aba = tabela(p, ("issn", "title"))
    cp = coluna(cab, "print issn", "issn")
    ce = coluna(cab, "e issn", "eissn")
    ct = coluna(cab, "source title", "title")
    cs = coluna(cab, "active or inactive", "status")
    ca = coluna(cab, "asjc", "subject")
    tipo = coluna(cab, "source type")
    rows = []
    for ln in linhas:
        t = _celula(ln, tipo).lower()
        if t and "journal" not in t:  # séries de livros e anais ficam de fora
            continue
        st = _celula(ln, cs).lower()
        valor = "inativa" if st.startswith("inactive") else "indexada"
        for issn in _issns(_celula(ln, cp), _celula(ln, ce)):
            rows.append(
                {
                    "issn": issn,
                    "sistema": "scopus",
                    "valor": valor,
                    "edicao": edicao,
                    "titulo": _celula(ln, ct),
                    "area": _celula(ln, ca)[:200],
                }
            )
    print(f"Scopus: {len(rows)} ISSNs (aba '{aba}')")
    return rows


def ler_citescore(p: Path, edicao: str) -> list[dict[str, Any]]:
    """Planilha do CiteScore (Scopus Sources com CiteScore, percentil e área)."""
    cab, linhas, aba = tabela(p, ("citescore", "issn"))
    cp = coluna(cab, "print issn", "issn")
    ce = coluna(cab, "e issn", "eissn")
    cc = coluna(cab, "citescore")
    cpct = coluna(cab, "highest percentile", "percentile")
    ca = coluna(cab, "scopus sub subject area", "subject area", "asjc")
    ct = coluna(cab, "source title", "title")
    melhor: dict[str, dict[str, Any]] = {}
    for ln in linhas:
        m = re.search(r"(\d+(?:[.,]\d+)?)", _celula(ln, cpct))
        pct = float(m.group(1).replace(",", ".")) if m else None
        try:
            cs = float(_celula(ln, cc).replace(",", "."))
        except ValueError:
            cs = None
        area = _celula(ln, ca)
        if not area and m:  # "95% 12/240 General Medicine"
            area = re.sub(r"^\s*\d+(?:[.,]\d+)?%?\s*(\d+/\d+)?\s*", "", _celula(ln, cpct))
        for issn in _issns(_celula(ln, cp), _celula(ln, ce)):
            r = {
                "issn": issn,
                "sistema": "scopus_citescore",
                "valor": cs,
                "nota": pct,
                "edicao": edicao,
                "titulo": _celula(ln, ct),
                "area": "",
            }
            # uma linha por ISSN: fica a área de maior percentil (a planilha repete por área)
            if issn not in melhor or (pct or 0) > (melhor[issn]["nota"] or 0):
                r["_area"] = area
                melhor[issn] = r
    rows = []
    for r in melhor.values():
        r["titulo"] = (r["titulo"] + " | " + r.pop("_area", "")).strip(" |")
        rows.append(r)
    print(f"CiteScore: {len(rows)} ISSNs (aba '{aba}')")
    return rows


def colecao_wos(nome: str) -> str:
    alto = nome.upper()
    for c in COLECOES_WOS:
        if re.search(rf"(^|[^A-Z]){c}([^A-Z]|$)", alto):
            return c
    return ""


def ler_wos(spec: str, edicao: str) -> list[dict[str, Any]]:
    """Master Journal List da Clarivate (CSV por coleção)."""
    arq, _, col = spec.rpartition(":") if re.search(r":[A-Za-z]{4}$", spec) else (spec, "", "")
    p = Path(arq)
    col = (col or colecao_wos(p.name)).upper()
    if col not in COLECOES_WOS:
        raise SystemExit(
            f"erro: não sei a coleção do WoS de {p.name}; use {p.name}:SCIE (ou SSCI, AHCI, ESCI)"
        )
    cab, linhas, aba = tabela(p, ("issn", "journal"))
    ci = coluna(cab, "issn", exata=True)
    if ci is None:
        ci = coluna(cab, "issn")
    ce = coluna(cab, "eissn", "e issn")
    ct = coluna(cab, "journal title", "journal")
    ck = coluna(cab, "web of science categories", "categories")
    rows = []
    for ln in linhas:
        for issn in _issns(_celula(ln, ci), _celula(ln, ce)):
            rows.append(
                {
                    "issn": issn,
                    "sistema": "wos",
                    "valor": col,
                    "area": col,
                    "edicao": edicao,
                    "titulo": (_celula(ln, ct) + " | " + _celula(ln, ck)).strip(" |"),
                }
            )
    print(f"WoS {col}: {len(rows)} ISSNs (aba '{aba}')")
    return rows


def resumo(b: Banco) -> dict[str, Any]:
    c = b.con
    out = {
        "classificacoes": dict(
            c.execute(
                "SELECT sistema, COUNT(DISTINCT issn) FROM classificacoes GROUP BY sistema"
            ).fetchall()
        ),
        "revistas_do_banco": b.contar("SELECT COUNT(*) FROM fontes_classe"),
        "revistas_qualis": b.contar(
            "SELECT COUNT(*) FROM fontes_classe WHERE qualis_melhor IS NOT NULL"
        ),
        "revistas_scopus": b.contar("SELECT COUNT(*) FROM fontes_classe WHERE scopus = 1"),
        "revistas_wos": b.contar(
            "SELECT COUNT(*) FROM fontes_classe WHERE wos_colecoes IS NOT NULL"
        ),
        "revistas_qualis_por_estrato": dict(
            c.execute(
                "SELECT qualis_melhor, COUNT(*) FROM fontes_classe WHERE qualis_melhor IS NOT NULL "
                "GROUP BY 1 ORDER BY 1"
            ).fetchall()
        ),
        "revistas_wos_por_colecao": dict(
            c.execute(
                "SELECT wos_colecoes, COUNT(*) FROM fontes_classe WHERE wos_colecoes IS NOT NULL "
                "GROUP BY 1 ORDER BY 2 DESC"
            ).fetchall()
        ),
    }
    out["obras"] = b.estatisticas()["obras_classificadas"]
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="classifica revistas e obras (Qualis, Scopus, WoS)")
    ap.add_argument("--config")
    ap.add_argument("--banco", help="arquivo SQLite (padrão: config/banco.toml)")
    ap.add_argument("--qualis", type=Path, help="planilha do Sucupira (CSV ou XLSX)")
    ap.add_argument("--scopus", type=Path, help="Scopus Source List (XLSX)")
    ap.add_argument("--citescore", type=Path, help="planilha do CiteScore (XLSX)")
    ap.add_argument(
        "--wos", action="append", default=[], help="CSV da Master Journal List (repetível)"
    )
    ap.add_argument("--edicao", default="", help="rótulo da edição (ex.: 2021-2024)")
    ap.add_argument(
        "--openalex", action="store_true", help="recalcula a partir das listas do OpenAlex"
    )
    ap.add_argument("--resumo", action="store_true", help="só mostra o que já está classificado")
    a = ap.parse_args(argv)
    cfg = config_banco(a.config)
    with abrir(a.banco, cfg) as b:
        if not a.resumo:
            fontes = [
                ("qualis", a.qualis, ler_qualis),
                ("scopus", a.scopus, ler_scopus),
                ("scopus_citescore", a.citescore, ler_citescore),
            ]
            for sistema, arq, ler in fontes:
                if arq is None:
                    continue
                if not arq.is_file():
                    print(f"erro: {arq} não existe", file=sys.stderr)
                    return 1
                rows = ler(arq, a.edicao)
                if not rows:
                    print(f"erro: nenhuma linha válida em {arq}", file=sys.stderr)
                    return 1
                with b.lote():
                    b.con.execute(
                        "DELETE FROM classificacoes WHERE sistema = ? AND edicao = ?",
                        (sistema, a.edicao),
                    )
                    b.classificacoes(rows, arq.name)
            wos = [ler_wos(s, a.edicao) for s in a.wos]
            if wos:
                with b.lote():
                    for rows in wos:
                        col = rows[0]["valor"] if rows else ""
                        b.con.execute(
                            "DELETE FROM classificacoes WHERE sistema = 'wos' AND valor = ? "
                            "AND edicao = ?",
                            (col, a.edicao),
                        )
                        b.classificacoes(rows, f"wos-{col}")
            if a.openalex:
                with b.lote():
                    b.con.execute("DELETE FROM classificacoes WHERE sistema = 'openalex_lista'")
                    rows = []
                    for r in b.con.execute(
                        "SELECT issns, listas FROM fontes WHERE listas IS NOT NULL"
                    ):
                        for issn in json.loads(r["issns"] or "[]"):
                            rows += [
                                {
                                    "issn": issn,
                                    "sistema": "openalex_lista",
                                    "area": lst,
                                    "valor": lst,
                                }
                                for lst in json.loads(r["listas"] or "[]")
                            ]
                    b.classificacoes(rows, "openalex")
            n = b.atualizar_classes()
            print(f"revistas classificadas recalculadas: {n}")
        print(json.dumps(resumo(b), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
