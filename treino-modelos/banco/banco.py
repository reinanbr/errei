"""Acesso ao banco de treino (SQLite em modo WAL).

Uso típico::

    from banco.banco import abrir
    with abrir() as b:
        for r in b.obras(filtros, com_resumo="pt"):
            ...
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from comum import licencas
from comum.util import CONFIG_BANCO, caminho, carregar_toml, normalizar_issn

ESQUEMA = Path(__file__).with_name("esquema.sql")
VERSAO_ESQUEMA = "1"
ESTRATOS = ["A1", "A2", "A3", "A4", "B1", "B2", "B3", "B4", "B5", "C"]


def agora() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class Banco:
    def __init__(self, arquivo: str | Path) -> None:
        self.arquivo = Path(arquivo)
        self.arquivo.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(str(self.arquivo), timeout=60)
        self.con.row_factory = sqlite3.Row
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.execute("PRAGMA synchronous=NORMAL")
        self.con.execute("PRAGMA foreign_keys=OFF")
        self.con.executescript(ESQUEMA.read_text(encoding="utf-8"))
        self.con.execute(
            "INSERT OR IGNORE INTO meta (chave, valor) VALUES ('esquema', ?)", (VERSAO_ESQUEMA,)
        )
        self.con.commit()

    def __enter__(self) -> Banco:
        return self

    def __exit__(self, *exc: object) -> None:
        self.fechar()

    def fechar(self) -> None:
        self.con.commit()
        self.con.close()

    @contextmanager
    def lote(self) -> Iterator[None]:
        try:
            yield
            self.con.commit()
        except BaseException:
            self.con.rollback()
            raise

    # ------------------------------------------------------------------ progresso
    def progresso(self, chave: str, padrao: str = "") -> str:
        r = self.con.execute("SELECT valor FROM progresso WHERE chave = ?", (chave,)).fetchone()
        return str(r["valor"]) if r else padrao

    def marcar(self, chave: str, valor: str) -> None:
        self.con.execute(
            "INSERT INTO progresso (chave, valor, atualizado) VALUES (?, ?, ?) "
            "ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor, atualizado = excluded.atualizado",
            (chave, valor, agora()),
        )

    def coleta(self, fonte: str, parametros: dict[str, Any]) -> int:
        cur = self.con.execute(
            "INSERT INTO coletas (fonte, parametros, inicio, estado) VALUES (?, ?, ?, 'rodando')",
            (fonte, json.dumps(parametros, ensure_ascii=False), agora()),
        )
        self.con.commit()
        return int(cur.lastrowid or 0)

    def fim_coleta(self, cid: int, novos: int, estado: str = "ok") -> None:
        self.con.execute(
            "UPDATE coletas SET fim = ?, novos = ?, estado = ? WHERE id = ?",
            (agora(), novos, estado, cid),
        )
        self.con.commit()

    # ------------------------------------------------------------------ escrita
    def fonte(self, f: dict[str, Any]) -> None:
        issns = sorted({normalizar_issn(i) for i in f.get("issns") or [] if normalizar_issn(i)})
        self.con.execute(
            """INSERT INTO fontes (id, nome, issn_l, issns, editora, pais, tipo, is_oa, is_in_doaj,
                 is_in_scielo, is_core, listas, h_index, media_citacoes_2a, atualizado)
               VALUES (:id, :nome, :issn_l, :issns, :editora, :pais, :tipo, :is_oa, :is_in_doaj,
                 :is_in_scielo, :is_core, :listas, :h_index, :media, :atualizado)
               ON CONFLICT(id) DO UPDATE SET
                 nome = COALESCE(excluded.nome, nome), issn_l = COALESCE(excluded.issn_l, issn_l),
                 issns = CASE WHEN excluded.issns != '[]' THEN excluded.issns ELSE issns END,
                 editora = COALESCE(excluded.editora, editora), pais = COALESCE(excluded.pais, pais),
                 tipo = COALESCE(excluded.tipo, tipo), is_oa = COALESCE(excluded.is_oa, is_oa),
                 is_in_doaj = COALESCE(excluded.is_in_doaj, is_in_doaj),
                 is_in_scielo = COALESCE(excluded.is_in_scielo, is_in_scielo),
                 is_core = COALESCE(excluded.is_core, is_core),
                 listas = COALESCE(excluded.listas, listas),
                 h_index = COALESCE(excluded.h_index, h_index),
                 media_citacoes_2a = COALESCE(excluded.media_citacoes_2a, media_citacoes_2a),
                 atualizado = excluded.atualizado""",
            {
                "id": f["id"],
                "nome": f.get("nome"),
                "issn_l": normalizar_issn(f.get("issn_l") or "") or None,
                "issns": json.dumps(issns),
                "editora": f.get("editora"),
                "pais": f.get("pais"),
                "tipo": f.get("tipo"),
                "is_oa": f.get("is_oa"),
                "is_in_doaj": f.get("is_in_doaj"),
                "is_in_scielo": f.get("is_in_scielo"),
                "is_core": f.get("is_core"),
                "listas": json.dumps(f["listas"]) if f.get("listas") is not None else None,
                "h_index": f.get("h_index"),
                "media": f.get("media_citacoes_2a"),
                "atualizado": agora(),
            },
        )
        for i in issns:
            self.con.execute(
                "INSERT OR IGNORE INTO issn_fonte (issn, fonte_id) VALUES (?, ?)", (i, f["id"])
            )

    CAMPOS_OBRA = (
        "doi",
        "pid_scielo",
        "pmcid",
        "titulo",
        "idioma",
        "ano",
        "tipo",
        "fonte_id",
        "licenca",
        "url_oa",
        "pdf_url",
        "volume",
        "numero",
        "pagina_ini",
        "pagina_fim",
        "editora",
        "citacoes",
        "percentil_citacoes",
        "top10",
        "dominio",
        "campo",
        "subcampo",
        "topico",
        "origem",
    )

    def obra(self, o: dict[str, Any]) -> None:
        """Insere ou completa a obra (campos vazios não apagam o que já existe)."""
        v = {k: o.get(k) for k in self.CAMPOS_OBRA}
        v["licenca"] = licencas.normalizar(v["licenca"]) or None
        v["doi"] = (v["doi"] or "").lower().removeprefix("https://doi.org/") or None
        sets = ", ".join(f"{k} = COALESCE(excluded.{k}, {k})" for k in self.CAMPOS_OBRA)
        cols = ", ".join(("id", *self.CAMPOS_OBRA, "coletado"))
        marks = ", ".join(f":{k}" for k in ("id", *self.CAMPOS_OBRA, "coletado"))
        self.con.execute(
            f"INSERT INTO obras ({cols}) VALUES ({marks}) "
            f"ON CONFLICT(id) DO UPDATE SET {sets}, coletado = excluded.coletado",
            {"id": o["id"], **v, "coletado": agora()},
        )

    def obra_por_doi(self, doi: str) -> str | None:
        r = self.con.execute("SELECT id FROM obras WHERE doi = ?", (doi.lower(),)).fetchone()
        return str(r["id"]) if r else None

    def autores(self, obra_id: str, nomes: Iterable[str]) -> None:
        self.con.execute("DELETE FROM autores WHERE obra_id = ?", (obra_id,))
        self.con.executemany(
            "INSERT INTO autores (obra_id, ordem, nome) VALUES (?, ?, ?)",
            [(obra_id, i, n) for i, n in enumerate(nomes) if n],
        )

    def titulo(self, obra_id: str, lingua: str, texto: str, origem: str) -> None:
        if texto and lingua:
            self.con.execute(
                "INSERT INTO titulos (obra_id, lingua, texto, origem) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(obra_id, lingua) DO UPDATE SET texto = excluded.texto, origem = excluded.origem",
                (obra_id, lingua, texto, origem),
            )

    def resumo(self, obra_id: str, lingua: str, texto: str, estruturado: bool, origem: str) -> None:
        if texto and lingua:
            self.con.execute(
                "INSERT INTO resumos (obra_id, lingua, texto, estruturado, origem) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(obra_id, lingua) DO UPDATE SET texto = excluded.texto, "
                "estruturado = excluded.estruturado, origem = excluded.origem",
                (obra_id, lingua, texto, int(estruturado), origem),
            )

    def palavras(self, obra_id: str, lingua: str, termos: Iterable[str], origem: str) -> None:
        self.con.executemany(
            "INSERT OR IGNORE INTO palavras_chave (obra_id, lingua, termo, ordem, origem) VALUES (?, ?, ?, ?, ?)",
            [(obra_id, lingua, t.strip(), i, origem) for i, t in enumerate(termos) if t.strip()],
        )

    def secoes(self, obra_id: str, lingua: str, secoes: Iterable[Any], origem: str) -> None:
        self.con.execute("DELETE FROM secoes WHERE obra_id = ? AND lingua = ?", (obra_id, lingua))
        self.con.executemany(
            "INSERT INTO secoes (obra_id, lingua, ordem, nivel, titulo, tipo, parte, texto, origem) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (obra_id, lingua, s.ordem, s.nivel, s.titulo, s.tipo, s.parte, s.texto, origem)
                for s in secoes
            ],
        )

    def referencias(self, obra_id: str, refs: list[str]) -> None:
        self.con.execute("DELETE FROM referencias WHERE obra_id = ?", (obra_id,))
        self.con.executemany(
            "INSERT INTO referencias (obra_id, ordem, texto) VALUES (?, ?, ?)",
            [(obra_id, i, t) for i, t in enumerate(refs)],
        )

    def classificacoes(self, rows: list[dict[str, Any]], origem: str) -> int:
        n = 0
        for r in rows:
            issn = normalizar_issn(r.get("issn") or "")
            if not issn:
                continue
            self.con.execute(
                "INSERT INTO classificacoes (issn, sistema, area, valor, nota, edicao, titulo, origem, importado) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(issn, sistema, area, edicao) DO UPDATE SET "
                "valor = excluded.valor, nota = excluded.nota, titulo = excluded.titulo, "
                "origem = excluded.origem, importado = excluded.importado",
                (
                    issn,
                    r["sistema"],
                    r.get("area") or "",
                    r.get("valor"),
                    r.get("nota"),
                    r.get("edicao") or "",
                    r.get("titulo"),
                    origem,
                    agora(),
                ),
            )
            n += 1
        return n

    def texto_ia(self, r: dict[str, Any]) -> None:
        self.con.execute(
            "INSERT INTO textos_ia (obra_id, lingua, tipo, modo, modelo, modelo_licenca, temperatura, texto, gerado) "
            "VALUES (:obra_id, :lingua, :tipo, :modo, :modelo, :modelo_licenca, :temperatura, :texto, :gerado)",
            {**r, "gerado": agora()},
        )

    def atualizar_classes(self) -> int:
        """Recalcula fontes_classe a partir de v_classificacao_fonte."""
        with self.lote():
            self.con.execute("DELETE FROM fontes_classe")
            self.con.execute(
                "INSERT INTO fontes_classe SELECT fonte_id, nome, qualis_melhor, qualis_areas, scopus, "
                "scopus_percentil, wos_colecoes, doaj, scielo, cwts_core, listas FROM v_classificacao_fonte"
            )
        return int(self.con.execute("SELECT COUNT(*) FROM fontes_classe").fetchone()[0])

    # ------------------------------------------------------------------ leitura
    def filtros_sql(self, f: dict[str, Any] | None, texto: bool = True) -> tuple[str, list[Any]]:
        """WHERE para ``obras o LEFT JOIN fontes_classe c``. Com ``texto``, só licenças aceitas."""
        f = f or {}
        conds: list[str] = []
        args: list[Any] = []
        if texto:
            aceitas = sorted(licencas.ACEITAS | (licencas.SA if f.get("aceitar_sa") else set()))
            conds.append(f"o.licenca IN ({', '.join('?' * len(aceitas))})")
            args += aceitas
        if f.get("idiomas"):
            conds.append(f"o.idioma IN ({', '.join('?' * len(f['idiomas']))})")
            args += list(f["idiomas"])
        if f.get("ano_min"):
            conds.append("o.ano >= ?")
            args.append(int(f["ano_min"]))
        if f.get("ano_max"):
            conds.append("o.ano <= ?")
            args.append(int(f["ano_max"]))
        if f.get("campos"):
            conds.append(f"o.campo IN ({', '.join('?' * len(f['campos']))})")
            args += list(f["campos"])
        if f.get("qualis"):
            conds.append(f"c.qualis_melhor IN ({', '.join('?' * len(f['qualis']))})")
            args += list(f["qualis"])
        if f.get("scopus"):
            conds.append("c.scopus = 1")
        if f.get("scopus_percentil_min"):
            conds.append("c.scopus_percentil >= ?")
            args.append(float(f["scopus_percentil_min"]))
        wos = f.get("wos")
        if wos is True:
            conds.append("c.wos_colecoes IS NOT NULL")
        elif isinstance(wos, list) and wos:
            conds.append("(" + " OR ".join("c.wos_colecoes LIKE ?" for _ in wos) + ")")
            args += [f"%{w}%" for w in wos]
        if f.get("top10"):
            conds.append("o.top10 = 1")
        return (" WHERE " + " AND ".join(conds)) if conds else "", args

    def consulta(self, sql: str, args: Iterable[Any] = ()) -> Iterator[sqlite3.Row]:
        cur = self.con.execute(sql, list(args))
        while True:
            lote = cur.fetchmany(2000)
            if not lote:
                return
            yield from lote

    def obras(
        self, filtros: dict[str, Any] | None, texto: bool = True, limite: int = 0
    ) -> Iterator[sqlite3.Row]:
        where, args = self.filtros_sql(filtros, texto)
        sql = (
            "SELECT o.*, c.qualis_melhor AS c_qualis, c.scopus AS c_scopus, "
            "c.scopus_percentil AS c_scopus_pct, c.wos_colecoes AS c_wos "
            f"FROM obras o LEFT JOIN fontes_classe c ON c.fonte_id = o.fonte_id{where} ORDER BY o.id"
        )
        if limite:
            sql += f" LIMIT {int(limite)}"
        return self.consulta(sql, args)

    def mapa(self, tabela: str, obra_ids: list[str], lingua: str | None = None) -> dict[str, Any]:
        """{obra_id: texto} (titulos/resumos) ou {obra_id: [termos]} (palavras_chave)."""
        out: dict[str, Any] = {}
        for i in range(0, len(obra_ids), 900):
            ids = obra_ids[i : i + 900]
            marcas = ", ".join("?" * len(ids))
            extra, args = ("", list(ids))
            if lingua:
                extra, args = " AND lingua = ?", [*ids, lingua]
            if tabela == "palavras_chave":
                sql = f"SELECT obra_id, termo FROM palavras_chave WHERE obra_id IN ({marcas}){extra} ORDER BY obra_id, ordem"
                for r in self.con.execute(sql, args):
                    out.setdefault(r["obra_id"], []).append(r["termo"])
            elif tabela == "autores":
                sql = f"SELECT obra_id, nome FROM autores WHERE obra_id IN ({marcas}) ORDER BY obra_id, ordem"
                for r in self.con.execute(sql, ids):
                    out.setdefault(r["obra_id"], []).append(r["nome"])
            else:
                sql = f"SELECT obra_id, texto FROM {tabela} WHERE obra_id IN ({marcas}){extra}"
                for r in self.con.execute(sql, args):
                    out[r["obra_id"]] = r["texto"]
        return out

    def por_lingua(
        self, tabela: str, obra_ids: list[str], origens: list[str] | None = None
    ) -> dict[str, dict[str, Any]]:
        """{obra_id: {lingua: texto}} (titulos, resumos), {obra_id: {lingua: [termos]}}
        (palavras_chave) ou {obra_id: {lingua: [linhas de secoes]}} (secoes)."""
        if tabela not in {"titulos", "resumos", "palavras_chave", "secoes"}:
            raise ValueError(tabela)
        out: dict[str, dict[str, Any]] = {}
        for i in range(0, len(obra_ids), 900):
            ids = obra_ids[i : i + 900]
            marcas = ", ".join("?" * len(ids))
            args: list[Any] = list(ids)
            extra = ""
            if origens and tabela == "palavras_chave":
                extra = f" AND origem IN ({', '.join('?' * len(origens))})"
                args += origens
            if tabela == "palavras_chave":
                sql = (
                    f"SELECT obra_id, lingua, termo FROM palavras_chave WHERE obra_id IN ({marcas}){extra} "
                    "ORDER BY obra_id, lingua, ordem"
                )
                for r in self.con.execute(sql, args):
                    out.setdefault(r[0], {}).setdefault(r[1], []).append(r[2])
            elif tabela == "secoes":
                sql = f"SELECT * FROM secoes WHERE obra_id IN ({marcas}) ORDER BY obra_id, lingua, ordem"
                for r in self.con.execute(sql, args):
                    out.setdefault(r["obra_id"], {}).setdefault(r["lingua"], []).append(r)
            else:
                sql = f"SELECT obra_id, lingua, texto FROM {tabela} WHERE obra_id IN ({marcas})"
                for r in self.con.execute(sql, args):
                    if r[2]:
                        out.setdefault(r[0], {})[r[1]] = r[2]
        return out

    def contar(self, sql: str, args: Iterable[Any] = ()) -> int:
        return int(self.con.execute(sql, list(args)).fetchone()[0])

    def estatisticas(self) -> dict[str, Any]:
        c = self.contar
        e: dict[str, Any] = {
            "arquivo": str(self.arquivo),
            "tamanho_mb": round(self.arquivo.stat().st_size / 1e6, 1)
            if self.arquivo.exists()
            else 0,
            "obras": c("SELECT COUNT(*) FROM obras"),
            "obras_texto_aberto": c(
                f"SELECT COUNT(*) FROM obras WHERE licenca IN ({', '.join('?' * len(licencas.ACEITAS))})",
                sorted(licencas.ACEITAS),
            ),
            "fontes": c("SELECT COUNT(*) FROM fontes"),
            "resumos_por_lingua": dict(
                self.con.execute(
                    "SELECT lingua, COUNT(*) FROM resumos GROUP BY lingua ORDER BY 2 DESC LIMIT 8"
                ).fetchall()
            ),
            "resumos_estruturados": c("SELECT COUNT(*) FROM resumos WHERE estruturado = 1"),
            "obras_bilingues_pt_en": c(
                "SELECT COUNT(*) FROM resumos a JOIN resumos b ON a.obra_id = b.obra_id "
                "AND a.lingua = 'pt' AND b.lingua = 'en'"
            ),
            "palavras_chave": c("SELECT COUNT(*) FROM palavras_chave"),
            "obras_com_secoes": c("SELECT COUNT(DISTINCT obra_id) FROM secoes"),
            "secoes_por_tipo": dict(
                self.con.execute(
                    "SELECT tipo, COUNT(*) FROM secoes GROUP BY tipo ORDER BY 2 DESC"
                ).fetchall()
            ),
            "referencias": c("SELECT COUNT(*) FROM referencias"),
            "textos_ia": c("SELECT COUNT(*) FROM textos_ia"),
            "obras_por_campo": dict(
                self.con.execute(
                    "SELECT campo, COUNT(*) FROM obras WHERE campo IS NOT NULL GROUP BY campo ORDER BY 2 DESC LIMIT 30"
                ).fetchall()
            ),
            "classificacoes": dict(
                self.con.execute(
                    "SELECT sistema, COUNT(*) FROM classificacoes GROUP BY sistema"
                ).fetchall()
            ),
        }
        e["obras_classificadas"] = {
            "qualis": c(
                "SELECT COUNT(*) FROM v_classificacao_obra WHERE qualis_melhor IS NOT NULL"
            ),
            "scopus": c("SELECT COUNT(*) FROM v_classificacao_obra WHERE scopus = 1"),
            "wos": c("SELECT COUNT(*) FROM v_classificacao_obra WHERE wos_colecoes IS NOT NULL"),
            "qualis_por_estrato": dict(
                self.con.execute(
                    "SELECT qualis_melhor, COUNT(*) FROM v_classificacao_obra WHERE qualis_melhor IS NOT NULL "
                    "GROUP BY qualis_melhor ORDER BY 1"
                ).fetchall()
            ),
        }
        return e


def classe(r: Any) -> dict[str, Any]:
    """Classificação da revista de uma linha de ``Banco.obras`` (vai junto de cada exemplo)."""
    q = r["c_qualis"]
    return {
        "qualis": q or "",
        "qualis_faixa": (q[0] if q else "sem"),
        "scopus": int(r["c_scopus"] or 0),
        "wos": r["c_wos"] or "",
    }


def config_banco(p: str | Path | None = None) -> dict[str, Any]:
    return carregar_toml(p, CONFIG_BANCO)


def abrir(arquivo: str | Path | None = None, cfg: dict[str, Any] | None = None) -> Banco:
    if arquivo is None:
        cfg = cfg or config_banco()
        arquivo = caminho(cfg["banco"]["arquivo"])
    return Banco(arquivo)
