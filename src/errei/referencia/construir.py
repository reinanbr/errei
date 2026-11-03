"""Constrói a referência de uma área a partir do OpenAlex (somente com rede, por comando).

Seleção: artigos (``type:article``) de acesso aberto, publicados em ``anos``, no top 10%
de citações normalizadas por ano e subárea (``citation_normalized_percentile``), na área
escolhida; no escopo ``brasil``, com ao menos uma instituição brasileira na autoria.
Amostra aleatória reprodutível (``sample`` + ``seed`` do OpenAlex).

Por obra: referências (obras citadas localizadas no OpenAlex), resumo (OpenAlex) e, se
houver PDF aberto, o texto completo, lido em memória só para medir. Grava só quantis.
"""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Callable
from datetime import date
from typing import Any

from errei import __version__
from errei.net.sources import _openalex_abstract
from errei.referencia import medidas, pdftexto
from errei.referencia.areas import Area

API = "https://api.openalex.org/works"
SELECT = (
    "id,doi,publication_year,language,type,referenced_works,referenced_works_count,"
    "abstract_inverted_index,best_oa_location,locations"
)
LOTE_REFS = 100


def filtro(area: Area, escopo: str, anos: str) -> str:
    partes = [
        area.filtro,
        "type:article",
        "open_access.is_oa:true",
        f"publication_year:{anos}",
        "citation_normalized_percentile.is_in_top_10_percent:true",
    ]
    if escopo == "brasil":
        partes.append("authorships.institutions.country_code:BR")
    return ",".join(partes)


class ConstrucaoError(RuntimeError):
    pass


def _obras(http: Any, filt: str, n: int, seed: int) -> tuple[int, list[dict[str, Any]]]:
    res = http.get_json(API, {"filter": filt, "per-page": 1, "select": "id"})
    if res is None or res[0] != 200 or not res[1]:
        raise ConstrucaoError("OpenAlex não respondeu (limite diário ou rede); tente mais tarde")
    total = int(res[1]["meta"]["count"])
    obras: list[dict[str, Any]] = []
    page = 1
    while len(obras) < min(n, total):
        res = http.get_json(
            API,
            {
                "filter": filt,
                "sample": min(n, total),
                "seed": seed,
                "per-page": 200,
                "page": page,
                "select": SELECT,
            },
        )
        if res is None or res[0] != 200 or not res[1]:
            raise ConstrucaoError("OpenAlex interrompeu a listagem; rode de novo (há cache)")
        lote = res[1].get("results", [])
        if not lote:
            break
        obras += lote
        page += 1
    return total, obras[:n]


def _refs_meta(
    http: Any, ids: list[str], progress: Callable[[str], None]
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    uniq = sorted(set(ids))
    for i in range(0, len(uniq), LOTE_REFS):
        chunk = [x.rsplit("/", 1)[-1] for x in uniq[i : i + LOTE_REFS]]
        progress(f"obras citadas: {min(i + LOTE_REFS, len(uniq))}/{len(uniq)}")
        res = http.get_json(
            API,
            {
                "filter": "ids.openalex:" + "|".join(chunk),
                "per-page": LOTE_REFS,
                "select": "id,doi,publication_year,type,primary_location",
            },
        )
        if res is None or res[0] != 200 or not res[1]:
            continue  # lote perdido: as obras ficam com menos referências medidas
        for w in res[1].get("results", []):
            src = ((w.get("primary_location") or {}).get("source")) or {}
            out[w["id"]] = {
                "ano": w.get("publication_year"),
                "periodico": w.get("type") == "article" and src.get("type") == "journal",
                "doi": bool(w.get("doi")),
            }
    return out


def _pdf_urls(w: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for loc in [w.get("best_oa_location") or {}, *(w.get("locations") or [])]:
        u = (loc or {}).get("pdf_url")
        if u and u not in urls:
            urls.append(u)
    return urls[:3]


def _texto(http: Any, w: dict[str, Any]) -> tuple[str, list[str]] | None:
    for url in _pdf_urls(w):
        data = http.get_bytes(url, cache=False)  # nada do texto fica em disco
        if not data or not data.startswith(b"%PDF"):
            continue
        pags = pdftexto.paginas(data)
        if pags and sum(len(p) for p in pags) > 2000:
            return pdftexto.separar(pags)
    return None


def medir_obra(
    http: Any,
    w: dict[str, Any],
    refs: dict[str, dict[str, Any]],
    *,
    texto_completo: bool,
    usar_modelo: bool,
) -> dict[str, Any]:
    ano = int(w.get("publication_year") or date.today().year)
    lang = (w.get("language") or "").lower() or "?"
    m: dict[str, Any] = {"_lang": lang}
    rs = [refs[r] for r in w.get("referenced_works") or [] if r in refs]
    m.update(medidas.medir_refs(rs, ano))
    resumo = _openalex_abstract(w.get("abstract_inverted_index"))
    if resumo:
        m.update(medidas.medir_resumo(resumo, usar_modelo=usar_modelo))
    if texto_completo:
        t = _texto(http, w)
        if t is not None:
            corpo, linhas = t
            m["_texto"] = True
            m.update(medidas.medir_texto(corpo, "pt" if lang == "pt" else lang))
            n_pdf = pdftexto.contar_referencias(linhas)
            if n_pdf is not None:
                m["refs_n_pdf"] = n_pdf
    return m


def construir(
    http: Any,
    area: Area,
    escopo: str,
    *,
    n: int = 300,
    anos: str = "2015-2023",
    seed: int = 42,
    texto_completo: bool = True,
    usar_modelo: bool = True,
    progress: Callable[[str], None] = lambda _m: None,
) -> dict[str, Any]:
    t0 = time.time()
    filt = filtro(area, escopo, anos)
    progress(f"consultando o OpenAlex ({area.nome}, {escopo})")
    total, obras = _obras(http, filt, n, seed)
    if not obras:
        raise ConstrucaoError(f"nenhuma obra encontrada com o filtro {filt}")
    refs = _refs_meta(http, [r for w in obras for r in w.get("referenced_works") or []], progress)
    amostras: list[dict[str, Any]] = []
    licencas: Counter[str] = Counter()
    for i, w in enumerate(obras, 1):
        progress(f"medindo obra {i}/{len(obras)}")
        licencas[str((w.get("best_oa_location") or {}).get("license") or "não informada")] += 1
        amostras.append(
            medir_obra(http, w, refs, texto_completo=texto_completo, usar_modelo=usar_modelo)
        )
    grupos: dict[str, Any] = {
        "artigo|todos": {"n": len(amostras), "medidas": medidas.agregar(amostras)}
    }
    for lang, k in Counter(a["_lang"] for a in amostras).items():
        sel = [a for a in amostras if a["_lang"] == lang]
        grupos[f"artigo|{lang}"] = {"n": k, "medidas": medidas.agregar(sel)}
    from errei import resumocheck

    return {
        "procedencia": {
            "fonte": "OpenAlex (metadados CC0) + PDFs de acesso aberto lidos só em memória",
            "consultado_em": date.today().isoformat(),
            "filtro": filt,
            "criterio": "top 10% de citações normalizadas por ano e subárea, acesso aberto",
            "obras_na_populacao": total,
            "amostra": {"n": len(obras), "seed": seed, "anos": anos},
            "com_texto_completo": sum(1 for a in amostras if a.get("_texto")),
            "obras_citadas_localizadas": len(refs),
            "idiomas": dict(Counter(a["_lang"] for a in amostras).most_common()),
            "licencas_dos_textos": dict(licencas.most_common()),
            "papeis_do_resumo": (
                resumocheck.MODEL_NAME
                if usar_modelo and resumocheck.unavailable_reason() is None
                else "palavras-chave"
            ),
            "errei": __version__,
            "segundos": round(time.time() - t0),
            "armazenado": "apenas quantis/frequências agregados; nenhum texto ou título",
        },
        "grupos": grupos,
    }
