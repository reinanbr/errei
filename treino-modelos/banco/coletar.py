"""Coleta o banco de treino: OpenAlex, revistas, SciELO (ArticleMeta) e textos completos.

Uso (da raiz do repositório):
    python treino-modelos/banco/coletar.py openalex          # consultas de [[openalex.consultas]]
    python treino-modelos/banco/coletar.py fontes            # revistas: ISSNs, listas (DOAJ, SciELO...)
    python treino-modelos/banco/coletar.py scielo            # títulos/resumos/palavras-chave pt+en
    python treino-modelos/banco/coletar.py textos            # texto completo JATS (seções, referências)
    python treino-modelos/banco/coletar.py tudo              # as quatro, nesta ordem
    python treino-modelos/banco/coletar.py --fumaca          # banco sintético, sem rede

Tudo é retomável: interrompa quando quiser e rode o mesmo comando de novo. Texto (resumos,
seções) só é guardado de obras com licença aberta que permite uso comercial (CC BY, CC0,
domínio público); a licença vem do OpenAlex ou do próprio artigo. Rode a coleta numa
máquina barata (o seu VPS) e leve o banco pronto para a GPU: ela cobra por hora.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from comum import jats, licencas
from comum.rede import Cliente, cliente
from comum.util import caminho, normalizar_issn

from banco.banco import Banco, abrir, agora, config_banco

OPENALEX = "https://api.openalex.org"
ARTICLEMETA = "https://articlemeta.scielo.org/api/v1"
EUROPEPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest"
SELECT_OBRAS = (
    "id,doi,title,display_name,language,publication_year,type,primary_location,best_oa_location,"
    "locations,biblio,primary_topic,cited_by_count,citation_normalized_percentile,authorships,"
    "abstract_inverted_index,ids,keywords"
)
PID_RX = re.compile(r"S\d{4}-\d{3}[\dXx]\d{13}")
CABECALHO_RX = re.compile(
    r"(?:^|[.\s])(objetivos?|objectives?|aims?|purpose|prop[oó]sito|m[eé]todos?|methods?|"
    r"metodolog[ií]a|materiais? e m[eé]todos|design|setting|resultados?|results?|findings|"
    r"conclus(?:ão|ões|ao|oes|ion|ions|iones|ión)|introdu[çc](?:ão|ao)|introduction|introducci[oó]n|"
    r"background|contexto|context|fundamentos?)\s*:",
    re.IGNORECASE,
)


def curto(u: str | None) -> str | None:
    return u.rsplit("/", 1)[-1] if u else None


def resumo_invertido(inv: dict[str, list[int]] | None) -> str:
    if not inv:
        return ""
    pos: dict[int, str] = {}
    for palavra, ps in inv.items():
        for p in ps:
            pos[p] = palavra
    return " ".join(pos[i] for i in sorted(pos))


def estruturado(texto: str) -> bool:
    return len(CABECALHO_RX.findall(texto or "")) >= 2


def limpar_resumo(t: str) -> str:
    t = html.unescape(re.sub(r"<[^>]+>", " ", t or ""))
    t = re.sub(r"^\s*(abstract|resumo|resumen|summary)\s*[:.]?\s*", "", t, flags=re.IGNORECASE)
    return " ".join(t.split())


# ---------------------------------------------------------------------- OpenAlex
def gravar_obra_openalex(b: Banco, w: dict[str, Any], aceitar_sa: bool = False) -> bool:
    """Grava obra, revista, autores, título e (se a licença permitir) o resumo."""
    loc = w.get("best_oa_location") or {}
    prim = w.get("primary_location") or {}
    src = prim.get("source") or loc.get("source") or {}
    biblio = w.get("biblio") or {}
    topico = w.get("primary_topic") or {}
    cnp = w.get("citation_normalized_percentile") or {}
    ids = w.get("ids") or {}
    pid = None
    for lc in [loc, prim, *(w.get("locations") or [])]:
        for k in ("landing_page_url", "pdf_url"):
            m = PID_RX.search(str((lc or {}).get(k) or ""))
            if m:
                pid = m.group(0).upper()
                break
        if pid:
            break
    oid = curto(w.get("id"))
    if not oid:
        return False
    if src.get("id"):
        b.fonte(
            {
                "id": curto(src["id"]),
                "nome": src.get("display_name"),
                "issn_l": src.get("issn_l"),
                "issns": src.get("issn") or [],
                "editora": src.get("host_organization_name"),
                "tipo": src.get("type"),
                "is_oa": src.get("is_oa"),
                "is_in_doaj": src.get("is_in_doaj"),
                "is_core": src.get("is_core"),
            }
        )
    lic = licencas.normalizar(loc.get("license"))
    b.obra(
        {
            "id": oid,
            "doi": w.get("doi"),
            "pid_scielo": pid,
            "pmcid": curto(ids.get("pmcid")),
            "titulo": w.get("title") or w.get("display_name"),
            "idioma": w.get("language"),
            "ano": w.get("publication_year"),
            "tipo": w.get("type"),
            "fonte_id": curto(src.get("id")),
            "licenca": lic or None,
            "url_oa": loc.get("landing_page_url"),
            "pdf_url": loc.get("pdf_url"),
            "volume": biblio.get("volume"),
            "numero": biblio.get("issue"),
            "pagina_ini": biblio.get("first_page"),
            "pagina_fim": biblio.get("last_page"),
            "editora": src.get("host_organization_name"),
            "citacoes": w.get("cited_by_count"),
            "percentil_citacoes": cnp.get("value"),
            "top10": int(bool(cnp.get("is_in_top_10_percent"))) if cnp else None,
            "dominio": (topico.get("domain") or {}).get("display_name"),
            "campo": (topico.get("field") or {}).get("display_name"),
            "subcampo": (topico.get("subfield") or {}).get("display_name"),
            "topico": topico.get("display_name"),
            "origem": "openalex",
        }
    )
    b.autores(
        oid,
        [
            (a.get("author") or {}).get("display_name") or a.get("raw_author_name") or ""
            for a in w.get("authorships") or []
        ],
    )
    lingua = (w.get("language") or "")[:2]
    titulo = w.get("title") or w.get("display_name") or ""
    if lingua:
        b.titulo(oid, lingua, titulo, "openalex")
    if licencas.aceita(lic, aceitar_sa) and lingua:
        res = limpar_resumo(resumo_invertido(w.get("abstract_inverted_index")))
        if len(res) > 200:
            b.resumo(oid, lingua, res, estruturado(res), "openalex")
        kws = [k.get("display_name", "") for k in w.get("keywords") or []]
        if kws:
            b.palavras(oid, "en", kws, "openalex")
    return True


def coletar_openalex(
    b: Banco, c: Cliente, cfg: dict[str, Any], so: str | None, maximo: int | None
) -> int:
    oa = cfg.get("openalex", {})
    total = 0
    for q in oa.get("consultas", []):
        nome = q["nome"]
        if so and nome != so:
            continue
        lim = maximo or int(q.get("max", 100000))
        chave = f"openalex:{nome}"
        cursor = b.progresso(f"{chave}:cursor", "*")
        feitos = int(b.progresso(f"{chave}:n", "0"))
        if cursor == "fim" or feitos >= lim:
            print(f"[{nome}] já completa ({feitos} obras)")
            continue
        cid = b.coleta("openalex", {"consulta": nome, "filtro": q["filtro"], "max": lim})
        print(f"[{nome}] filtro {q['filtro']} · retomando em {feitos} obras")
        novos = 0
        while feitos < lim:
            d = c.get_json(
                f"{OPENALEX}/works",
                {
                    "filter": q["filtro"],
                    "per_page": 200,
                    "cursor": cursor,
                    "select": SELECT_OBRAS
                    if q.get("texto", True)
                    else SELECT_OBRAS.replace(",abstract_inverted_index", ""),
                },
            )
            if d is None:
                print(
                    f"[{nome}] OpenAlex não respondeu; rode de novo para retomar", file=sys.stderr
                )
                b.fim_coleta(cid, novos, "interrompida")
                return total + novos
            res = d.get("results") or []
            with b.lote():
                for w in res:
                    if gravar_obra_openalex(b, w, bool(cfg["banco"].get("aceitar_sa"))):
                        novos += 1
                feitos += len(res)
                cursor = (d.get("meta") or {}).get("next_cursor") or "fim"
                b.marcar(f"{chave}:cursor", cursor)
                b.marcar(f"{chave}:n", str(feitos))
            if feitos % 5000 < 200:
                print(
                    f"[{nome}] {feitos} obras (total da consulta: {(d.get('meta') or {}).get('count')})",
                    flush=True,
                )
            if not res or cursor == "fim":
                break
        b.fim_coleta(cid, novos)
        total += novos
        print(f"[{nome}] {novos} obras gravadas nesta rodada")
    return total


def coletar_fontes(b: Banco, c: Cliente) -> int:
    ids = [
        r[0]
        for r in b.con.execute(
            "SELECT id FROM fontes WHERE id LIKE 'S%' AND listas IS NULL"
        ).fetchall()
    ]
    print(f"{len(ids)} revista(s) para completar no OpenAlex")
    n = 0
    for i in range(0, len(ids), 50):
        lote = ids[i : i + 50]
        d = c.get_json(
            f"{OPENALEX}/sources", {"filter": "openalex_id:" + "|".join(lote), "per_page": 50}
        )
        if d is None:
            print("OpenAlex não respondeu; rode de novo para retomar", file=sys.stderr)
            break
        with b.lote():
            for s in d.get("results") or []:
                st = s.get("summary_stats") or {}
                fid = curto(s.get("id")) or ""
                listas = sorted(set(s.get("listed_in") or []))
                b.fonte(
                    {
                        "id": fid,
                        "nome": s.get("display_name"),
                        "issn_l": s.get("issn_l"),
                        "issns": s.get("issn") or [],
                        "editora": s.get("host_organization_name"),
                        "pais": s.get("country_code"),
                        "tipo": s.get("type"),
                        "is_oa": s.get("is_oa"),
                        "is_in_doaj": s.get("is_in_doaj"),
                        "is_in_scielo": s.get("is_in_scielo"),
                        "is_core": s.get("is_core"),
                        "listas": listas,
                        "h_index": st.get("h_index"),
                        "media_citacoes_2a": st.get("2yr_mean_citedness"),
                    }
                )
                b.classificacoes(
                    [
                        {
                            "issn": issn,
                            "sistema": "openalex_lista",
                            "area": lst,
                            "valor": lst,
                            "titulo": s.get("display_name"),
                        }
                        for issn in (s.get("issn") or [])
                        for lst in listas
                    ],
                    "OpenAlex listed_in (CC0)",
                )
                n += 1
            # revistas que o OpenAlex não devolveu: marca para não pedir de novo
            b.con.executemany(
                "UPDATE fontes SET listas = COALESCE(listas, '[]') WHERE id = ?",
                [(x,) for x in lote],
            )
        if (i // 50) % 20 == 0:
            print(f"  {i + len(lote)}/{len(ids)} revistas", flush=True)
    print(
        f"[OK] {n} revista(s) completadas; classes atualizadas para {b.atualizar_classes()} revistas"
    )
    return n


# ---------------------------------------------------------------------- SciELO (ArticleMeta)
def _vals(lst: Any, k: str = "_") -> list[tuple[str, str]]:
    out = []
    for x in lst or []:
        if isinstance(x, dict):
            out.append((str(x.get(k) or ""), str(x.get("l") or "").lower()[:2]))
    return out


def gravar_articlemeta(
    b: Banco, d: dict[str, Any], obra_id: str | None, aceitar_sa: bool
) -> str | None:
    a = d.get("article") or {}
    t = d.get("title") or {}
    pid = str(d.get("code") or "").upper()
    lic_am = str(d.get("license") or "")
    if obra_id is None:  # sem OpenAlex: vale a licença declarada no ArticleMeta
        if not licencas.aceita(lic_am, aceitar_sa):
            return None
        obra_id = f"scielo:{pid}"
    issns = set()
    for k in ("v400", "v935", "v435"):
        for v, _ in _vals(t.get(k)):
            if normalizar_issn(v):
                issns.add(normalizar_issn(v))
    ct = d.get("code_title")
    for v in ct if isinstance(ct, list) else [ct]:
        if normalizar_issn(str(v or "")):
            issns.add(normalizar_issn(str(v)))
    fonte_id = None
    if issns:
        r = b.con.execute(
            f"SELECT fonte_id FROM issn_fonte WHERE issn IN ({', '.join('?' * len(issns))}) LIMIT 1",
            sorted(issns),
        ).fetchone()
        fonte_id = r[0] if r else f"scielo:{sorted(issns)[0]}"
        if not r:
            nome = (_vals(t.get("v100")) or [("", "")])[0][0]
            b.fonte({"id": fonte_id, "nome": nome, "issns": sorted(issns), "is_in_scielo": 1})
    lingua = ((_vals(a.get("v40")) or [("", "")])[0][0] or "").lower()[:2]
    doi = (_vals(a.get("v237")) or [("", "")])[0][0] or d.get("doi")
    titulos = [(html.unescape(x), lg) for x, lg in _vals(a.get("v12")) if x and lg]
    b.obra(
        {
            "id": obra_id,
            "doi": doi,
            "pid_scielo": pid,
            "titulo": next(
                (x for x, lg in titulos if lg == lingua), titulos[0][0] if titulos else None
            ),
            "idioma": lingua or None,
            "ano": int(d["publication_year"])
            if str(d.get("publication_year") or "").isdigit()
            else None,
            "tipo": (_vals(a.get("v71")) or [("", "")])[0][0] or None,
            "fonte_id": fonte_id,
            "licenca": lic_am or None if obra_id.startswith("scielo:") else None,
            "origem": "scielo",
        }
    )
    for x, lg in titulos:
        b.titulo(obra_id, lg, " ".join(x.split()), "scielo")
    for x in a.get("v83") or []:
        if isinstance(x, dict) and x.get("a") and x.get("l"):
            res = limpar_resumo(str(x["a"]))
            if len(res) > 150:
                b.resumo(obra_id, str(x["l"]).lower()[:2], res, estruturado(res), "scielo")
    por_lingua: dict[str, list[str]] = {}
    for x in a.get("v85") or []:
        if isinstance(x, dict) and x.get("k") and x.get("l"):
            por_lingua.setdefault(str(x["l"]).lower()[:2], []).append(html.unescape(str(x["k"])))
    for lg, termos in por_lingua.items():
        b.palavras(obra_id, lg, termos, "autor")
    return obra_id


def _openalex_por_doi(c: Cliente, dois: list[str]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for i in range(0, len(dois), 50):
        lote = [x for x in dois[i : i + 50] if x and "|" not in x and "," not in x]
        if not lote:
            continue
        d = c.get_json(
            f"{OPENALEX}/works",
            {"filter": "doi:" + "|".join(lote), "per_page": 50, "select": SELECT_OBRAS},
        )
        for w in (d or {}).get("results") or []:
            if w.get("doi"):
                out[w["doi"].lower().removeprefix("https://doi.org/")] = w
    return out


def coletar_scielo(b: Banco, c: Cliente, cfg: dict[str, Any], maximo: int | None) -> int:
    s = cfg.get("scielo", {})
    aceitar_sa = bool(cfg["banco"].get("aceitar_sa"))
    novos = 0
    for col in s.get("colecoes", ["scl"]):
        desde, ate = str(s.get("desde", "2000-01-01")), str(s.get("ate", ""))
        chave = f"scielo:{col}:{desde}:{ate}"
        offset = int(b.progresso(f"{chave}:offset", "0"))
        lim = maximo or int(s.get("max", 100000))
        cid = b.coleta("scielo", {"colecao": col, "desde": desde, "ate": ate, "max": lim})
        print(f"[scielo/{col}] retomando no identificador {offset}")
        while novos < lim:
            params = {"collection": col, "from": desde, "limit": 1000, "offset": offset}
            if ate:
                params["until"] = ate
            d = c.get_json(f"{ARTICLEMETA}/article/identifiers/", params)
            if d is None:
                print("ArticleMeta não respondeu; rode de novo para retomar", file=sys.stderr)
                break
            objs = d.get("objects") or []
            if not objs:
                b.marcar(f"{chave}:offset", str(offset))
                b.con.commit()
                break
            pids = [str(o.get("code") or "").upper() for o in objs]
            vistos = {
                r[0]
                for r in b.con.execute(
                    f"SELECT pid FROM scielo_vistos WHERE pid IN ({', '.join('?' * len(pids))})",
                    pids,
                )
            }
            pend = [o for o in objs if str(o.get("code") or "").upper() not in vistos]
            dois = [str(o.get("doi") or "").lower() for o in pend if o.get("doi")]
            oa = _openalex_por_doi(c, dois)
            for o in pend:
                pid = str(o.get("code") or "").upper()
                doi = str(o.get("doi") or "").lower()
                w = oa.get(doi)
                estado = "sem-licenca"
                obra_id = None
                with b.lote():
                    if w is not None:
                        gravar_obra_openalex(b, w, aceitar_sa)
                        obra_id = curto(w.get("id"))
                        lic = (w.get("best_oa_location") or {}).get("license")
                        if not licencas.aceita(lic, aceitar_sa):
                            estado = f"licenca:{licencas.normalizar(lic) or '?'}"
                            b.con.execute(
                                "INSERT OR REPLACE INTO scielo_vistos VALUES (?, ?, ?)",
                                (pid, estado, agora()),
                            )
                            continue
                    art = c.get_json(
                        f"{ARTICLEMETA}/article/",
                        {"collection": col, "code": pid, "format": "json"},
                    )
                    if art:
                        if gravar_articlemeta(b, art, obra_id, aceitar_sa):
                            estado = "ok"
                            novos += 1
                    else:
                        estado = "falha"
                    b.con.execute(
                        "INSERT OR REPLACE INTO scielo_vistos VALUES (?, ?, ?)",
                        (pid, estado, agora()),
                    )
            offset += len(objs)
            b.marcar(f"{chave}:offset", str(offset))
            b.con.commit()
            print(
                f"[scielo/{col}] {offset} identificadores vistos · {novos} artigos com texto aberto",
                flush=True,
            )
        b.fim_coleta(cid, novos)
    return novos


# ---------------------------------------------------------------------- textos completos (JATS)
def _jats_europepmc(c: Cliente, pmcid: str) -> bytes | None:
    r = c.get(f"{EUROPEPMC}/{pmcid}/fullTextXML", headers={"Accept": "application/xml"})
    return (
        r.corpo if r is not None and r.status == 200 and r.corpo.lstrip().startswith(b"<") else None
    )


def _jats_scielo(c: Cliente, pid: str) -> bytes | None:
    r = c.get("https://www.scielo.br/scielo.php", {"script": "sci_arttext", "pid": pid}, site=True)
    if r is None or r.status != 200 or "/a/" not in r.url:
        return None
    base = r.url.split("?", 1)[0]
    x = c.get(base, {"format": "xml"}, headers={"Accept": "application/xml"}, site=True)
    return x.corpo if x is not None and x.status == 200 and b"<article" in x.corpo[:5000] else None


def coletar_textos(b: Banco, c: Cliente, cfg: dict[str, Any], maximo: int | None) -> int:
    tcfg = cfg.get("textos", {})
    aceitar_sa = bool(cfg["banco"].get("aceitar_sa"))
    lim = maximo or int(tcfg.get("max", 20000))
    fontes = set(tcfg.get("fontes", ["europepmc", "scielo"]))
    where, args = b.filtros_sql(
        {"aceitar_sa": aceitar_sa, "idiomas": tcfg.get("idiomas")}, texto=True
    )
    sql = (
        f"SELECT o.id, o.pmcid, o.pid_scielo, o.idioma, o.licenca FROM obras o "
        f"LEFT JOIN fontes_classe c ON c.fonte_id = o.fonte_id{where} "
        f"{'AND' if where else 'WHERE'} (o.pmcid IS NOT NULL OR o.pid_scielo IS NOT NULL) "
        "AND o.id NOT IN (SELECT obra_id FROM textos_vistos) LIMIT ?"
    )
    pend = b.con.execute(sql, [*args, lim]).fetchall()
    print(f"{len(pend)} obra(s) com texto completo a buscar (fontes: {', '.join(sorted(fontes))})")
    ok = 0
    t0 = time.time()
    for i, r in enumerate(pend, 1):
        dados, fonte = None, ""
        if r["pmcid"] and "europepmc" in fontes:
            dados, fonte = _jats_europepmc(c, r["pmcid"]), "europepmc"
        if dados is None and r["pid_scielo"] and "scielo" in fontes:
            dados, fonte = _jats_scielo(c, r["pid_scielo"]), "scielo"
        estado = "sem-texto"
        if dados is not None:
            try:
                art = jats.ler(dados)
            except (ValueError, SyntaxError) as e:  # ET.ParseError herda de SyntaxError
                art, estado = None, f"xml-invalido: {str(e)[:60]}"
            if art is not None:
                # a licença do próprio XML, se houver, também precisa ser aberta
                if art.licenca and not licencas.aceita(art.licenca, aceitar_sa):
                    estado = f"licenca-xml:{licencas.normalizar(art.licenca)}"
                elif not art.secoes:
                    estado = "sem-secoes"
                else:
                    lingua = art.lingua or (r["idioma"] or "")[:2] or "xx"
                    with b.lote():
                        b.secoes(r["id"], lingua, art.secoes, fonte)
                        b.referencias(r["id"], art.referencias)
                        for lg, txt in art.resumos.items():
                            if (
                                lg
                                and len(txt) > 150
                                and not b.con.execute(
                                    "SELECT 1 FROM resumos WHERE obra_id = ? AND lingua = ?",
                                    (r["id"], lg),
                                ).fetchone()
                            ):
                                b.resumo(r["id"], lg, txt, estruturado(txt), fonte)
                        for lg, termos in art.palavras.items():
                            if lg:
                                b.palavras(r["id"], lg, termos, "autor")
                    estado = "ok"
                    ok += 1
        b.con.execute(
            "INSERT OR REPLACE INTO textos_vistos VALUES (?, ?, ?, ?)",
            (r["id"], estado, fonte, agora()),
        )
        if i % 50 == 0:
            b.con.commit()
            vel = i / max(1e-6, time.time() - t0)
            print(f"  {i}/{len(pend)} · {ok} com seções · {vel:.2f} obras/s", flush=True)
    b.con.commit()
    print(f"[OK] {ok} texto(s) completo(s) com seções")
    return ok


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("etapa", nargs="?", choices=["openalex", "fontes", "scielo", "textos", "tudo"])
    ap.add_argument("--config")
    ap.add_argument("--banco", help="arquivo do banco (padrão: [banco] arquivo)")
    ap.add_argument("--consulta", help="só esta consulta do OpenAlex")
    ap.add_argument("--max", type=int, help="limite desta rodada")
    ap.add_argument("--fumaca", action="store_true", help="cria um banco sintético, sem rede")
    a = ap.parse_args(argv)
    cfg = config_banco(a.config)
    arquivo = caminho(a.banco or cfg["banco"]["arquivo"])
    if a.fumaca:
        from banco.sintetico import criar

        criar(arquivo)
        print(f"[OK] banco sintético em {arquivo}")
        return 0
    if not a.etapa:
        ap.error("informe a etapa (openalex, fontes, scielo, textos ou tudo) ou --fumaca")
    c = cliente(cfg)
    if not c.openalex_key:
        print(
            "aviso: sem OPENALEX_API_KEY, o OpenAlex limita o orçamento diário compartilhado; "
            "crie uma chave gratuita em https://openalex.org/settings/api",
            file=sys.stderr,
        )
    with abrir(arquivo) as b:
        etapas = ["openalex", "fontes", "scielo", "textos"] if a.etapa == "tudo" else [a.etapa]
        for e in etapas:
            print(f"== {e}")
            if e == "openalex":
                coletar_openalex(b, c, cfg, a.consulta, a.max)
            elif e == "fontes":
                coletar_fontes(b, c)
            elif e == "scielo":
                coletar_scielo(b, c, cfg, a.max)
                coletar_fontes(b, c)  # revistas novas vindas da SciELO
            elif e == "textos":
                coletar_textos(b, c, cfg, a.max)
        e = b.estatisticas()
        print(
            json.dumps(
                {
                    k: e[k]
                    for k in (
                        "obras",
                        "obras_texto_aberto",
                        "fontes",
                        "resumos_por_lingua",
                        "obras_bilingues_pt_en",
                        "obras_com_secoes",
                    )
                },
                ensure_ascii=False,
            )
        )
        print(f"requisições: {c.pedidos} · falhas: {c.falhas}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
