"""Adaptadores de metadados abertos: Crossref, OpenAlex, Semantic Scholar, arXiv.

Só metadados e resumos públicos. Todas as funções aceitam ``http`` (``HttpClient``)
e degradam para ``unavailable`` quando a fonte falha.
"""

from __future__ import annotations

import re
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

CROSSREF = "https://api.crossref.org"
OPENALEX = "https://api.openalex.org"
S2 = "https://api.semanticscholar.org/graph/v1"
ARXIV = "https://export.arxiv.org/api/query"


@dataclass(slots=True)
class Candidate:
    source: str
    title: str
    authors: list[str]  # sobrenomes
    year: int | None
    venue: str
    doi: str
    url: str
    retracted: bool | None = None
    abstract: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Lookup:
    status: str  # found | notfound | unavailable
    candidate: Candidate | None = None


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"<[^>]+>", " ", s)  # tags JATS/HTML nos títulos
    s = re.sub(r"[^\w\s]", " ", s.lower())
    return " ".join(s.split())


def _first(v: Any) -> str:
    if isinstance(v, list):
        return str(v[0]) if v else ""
    return str(v or "")


# ------------------------------------------------------------------ Crossref
def _crossref_item(it: dict[str, Any]) -> Candidate:
    year = None
    for k in ("issued", "published-print", "published-online", "created"):
        parts = (it.get(k) or {}).get("date-parts") or []
        if parts and parts[0] and parts[0][0]:
            year = int(parts[0][0])
            break
    authors = [str(a.get("family") or a.get("name") or "") for a in it.get("author") or []]
    full = [
        " ".join(
            x for x in (str(a.get("given") or ""), str(a.get("family") or a.get("name") or "")) if x
        )
        for a in it.get("author") or []
    ]
    retracted = None
    for upd in (it.get("updated-by") or []) + (it.get("update-to") or []):
        if str(upd.get("type", "")).lower() in ("retraction", "removal", "withdrawal"):
            retracted = True
    if str(it.get("type", "")) == "retraction":
        retracted = True
    doi = str(it.get("DOI") or "")
    return Candidate(
        "Crossref",
        _first(it.get("title")),
        [a for a in authors if a],
        year,
        _first(it.get("container-title")),
        doi,
        f"https://doi.org/{doi}" if doi else str(it.get("URL") or ""),
        retracted,
        " ".join(re.sub(r"<[^>]+>", " ", str(it.get("abstract") or "")).split()),
        {"authors_full": [f for f in full if f]},
    )


def crossref_by_doi(http: Any, doi: str) -> Lookup:
    res = http.get_json(f"{CROSSREF}/works/{quote(doi, safe='/:;()._-')}")
    if res is None:
        return Lookup("unavailable")
    status, data = res
    if status == 404:
        return Lookup("notfound")
    if not data or "message" not in data:
        return Lookup("unavailable")
    return Lookup("found", _crossref_item(data["message"]))


def crossref_search(http: Any, query: str, rows: int = 5) -> list[Candidate] | None:
    res = http.get_json(
        f"{CROSSREF}/works",
        {
            "query.bibliographic": query[:300],
            "rows": rows,
            "select": "DOI,title,author,issued,container-title,type,update-to,updated-by,URL",
        },
    )
    if res is None or res[1] is None:
        return None
    items = (res[1].get("message") or {}).get("items") or []
    return [_crossref_item(it) for it in items]


# ------------------------------------------------------------------ OpenAlex
def _openalex_abstract(inv: dict[str, list[int]] | None) -> str:
    if not inv:
        return ""
    pos: dict[int, str] = {}
    for word, idxs in inv.items():
        for i in idxs:
            pos[i] = word
    return " ".join(pos[i] for i in sorted(pos))


def _openalex_item(it: dict[str, Any]) -> Candidate:
    authors = []
    full = []
    for a in it.get("authorships") or []:
        name = str(((a.get("author") or {}).get("display_name")) or "")
        if name:
            authors.append(name.split()[-1])
            full.append(name)
    best = it.get("best_oa_location") or {}
    pdf_url = str(best.get("pdf_url") or (it.get("open_access") or {}).get("oa_url") or "")
    src = ((it.get("primary_location") or {}).get("source") or {}).get("display_name") or ""
    doi = str(it.get("doi") or "").replace("https://doi.org/", "")
    return Candidate(
        "OpenAlex",
        str(it.get("title") or it.get("display_name") or ""),
        authors,
        it.get("publication_year"),
        str(src),
        doi,
        f"https://doi.org/{doi}" if doi else str(it.get("id") or ""),
        bool(it.get("is_retracted")) if "is_retracted" in it else None,
        _openalex_abstract(it.get("abstract_inverted_index")),
        {"authors_full": full, "pdf_url": pdf_url},
    )


def openalex_by_doi(http: Any, doi: str) -> Lookup:
    res = http.get_json(f"{OPENALEX}/works/doi:{quote(doi, safe='/:;()._-')}")
    if res is None:
        return Lookup("unavailable")
    status, data = res
    if status == 404:
        return Lookup("notfound")
    if not data:
        return Lookup("unavailable")
    return Lookup("found", _openalex_item(data))


def openalex_search(http: Any, query: str, rows: int = 5) -> list[Candidate] | None:
    res = http.get_json(f"{OPENALEX}/works", {"search": query[:300], "per-page": rows})
    if res is None or res[1] is None:
        return None
    return [_openalex_item(it) for it in res[1].get("results") or []]


def openalex_source_by_issn(http: Any, issn: str) -> dict[str, Any] | None:
    res = http.get_json(f"{OPENALEX}/sources", {"filter": f"issn:{issn}", "per-page": 1})
    if res is None or res[1] is None:
        return None
    results = res[1].get("results") or []
    return dict(results[0]) if results else {}


def openalex_source_search(http: Any, title: str) -> dict[str, Any] | None:
    res = http.get_json(f"{OPENALEX}/sources", {"search": title[:200], "per-page": 1})
    if res is None or res[1] is None:
        return None
    results = res[1].get("results") or []
    return dict(results[0]) if results else {}


# ------------------------------------------------------------------ Semantic Scholar
def s2_search(http: Any, query: str, rows: int = 5) -> list[Candidate] | None:
    res = http.get_json(
        f"{S2}/paper/search",
        {
            "query": query[:300],
            "limit": rows,
            "fields": "title,year,authors,venue,externalIds,url,abstract",
        },
    )
    if res is None or res[1] is None:
        return None
    out = []
    for it in res[1].get("data") or []:
        ext = it.get("externalIds") or {}
        out.append(
            Candidate(
                "Semantic Scholar",
                str(it.get("title") or ""),
                [
                    str(a.get("name", "")).split()[-1]
                    for a in it.get("authors") or []
                    if a.get("name")
                ],
                it.get("year"),
                str(it.get("venue") or ""),
                str(ext.get("DOI") or ""),
                str(it.get("url") or ""),
                None,
                str(it.get("abstract") or ""),
            )
        )
    return out


def s2_by_doi(http: Any, doi: str) -> Lookup:
    res = http.get_json(
        f"{S2}/paper/DOI:{quote(doi, safe='/:;()._-')}",
        {"fields": "title,year,authors,venue,abstract,url,openAccessPdf"},
    )
    if res is None:
        return Lookup("unavailable")
    status, it = res
    if status == 404 or not it:
        return Lookup("notfound")
    oa = it.get("openAccessPdf") or {}
    return Lookup(
        "found",
        Candidate(
            "Semantic Scholar",
            str(it.get("title") or ""),
            [str(a.get("name", "")).split()[-1] for a in it.get("authors") or [] if a.get("name")],
            it.get("year"),
            str(it.get("venue") or ""),
            doi,
            str(it.get("url") or ""),
            None,
            str(it.get("abstract") or ""),
            {
                "authors_full": [
                    str(a.get("name")) for a in it.get("authors") or [] if a.get("name")
                ],
                "pdf_url": str(oa.get("url") or ""),
            },
        ),
    )


def enrich(http: Any, cand: Candidate) -> Candidate:
    """Completa resumo e link de PDF aberto consultando OpenAlex/Semantic Scholar pelo DOI."""
    if (cand.abstract and cand.extra.get("pdf_url")) or not cand.doi:
        return cand
    for fn in (openalex_by_doi, s2_by_doi):
        if cand.abstract and cand.extra.get("pdf_url"):
            break
        look = fn(http, cand.doi)
        if look.status == "found" and look.candidate is not None:
            other = look.candidate
            if not cand.abstract and other.abstract:
                cand.abstract = other.abstract
                cand.extra["abstract_source"] = other.source
            if not cand.extra.get("pdf_url") and other.extra.get("pdf_url"):
                cand.extra["pdf_url"] = other.extra["pdf_url"]
            if not cand.extra.get("authors_full") and other.extra.get("authors_full"):
                cand.extra["authors_full"] = other.extra["authors_full"]
    if cand.abstract and "abstract_source" not in cand.extra:
        cand.extra["abstract_source"] = cand.source
    return cand


# ------------------------------------------------------------------ arXiv
_ATOM = "{http://www.w3.org/2005/Atom}"


def _arxiv_parse(body: str) -> list[Candidate]:
    if "<!DOCTYPE" in body or "<!ENTITY" in body:  # não processa DTD (entrada não confiável)
        return []
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return []
    out = []
    for e in root.findall(f"{_ATOM}entry"):
        title = " ".join((e.findtext(f"{_ATOM}title") or "").split())
        if not title or title == "Error":
            continue
        authors = [
            (a.findtext(f"{_ATOM}name") or "").split()[-1]
            for a in e.findall(f"{_ATOM}author")
            if (a.findtext(f"{_ATOM}name") or "").strip()
        ]
        pub = e.findtext(f"{_ATOM}published") or ""
        out.append(
            Candidate(
                "arXiv",
                title,
                authors,
                int(pub[:4]) if pub[:4].isdigit() else None,
                "arXiv",
                "",
                (e.findtext(f"{_ATOM}id") or "").strip(),
                None,
                " ".join((e.findtext(f"{_ATOM}summary") or "").split()),
            )
        )
    return out


def arxiv_by_id(http: Any, arxiv_id: str) -> Lookup:
    res = http.get_text(ARXIV, {"id_list": arxiv_id.replace("arXiv:", "").strip()})
    if res is None:
        return Lookup("unavailable")
    items = _arxiv_parse(res[1]) if res[0] == 200 else []
    return Lookup("found", items[0]) if items else Lookup("notfound")


def arxiv_search(http: Any, phrase: str, rows: int = 3) -> list[Candidate] | None:
    res = http.get_text(ARXIV, {"search_query": f'abs:"{phrase}"', "max_results": rows})
    if res is None or res[0] != 200:
        return None
    return _arxiv_parse(res[1])


# ------------------------------------------------------------------ obras nacionais
GBOOKS = "https://www.googleapis.com/books/v1/volumes"


def openalex_br_search(http: Any, query: str, rows: int = 5) -> list[Candidate] | None:
    """Artigos/livros com autoria vinculada a instituição brasileira (OpenAlex)."""
    res = http.get_json(
        f"{OPENALEX}/works",
        {
            "search": query[:300],
            "filter": "authorships.countries:BR,type:article|book|book-chapter",
            "per-page": rows,
        },
    )
    if res is None or res[1] is None:
        return None
    out = []
    for it in res[1].get("results") or []:
        c = _openalex_item(it)
        c.extra["tipo"] = "livro" if str(it.get("type", "")).startswith("book") else "artigo"
        c.extra["lingua"] = str(it.get("language") or "")
        out.append(c)
    return out


def google_books_search(http: Any, query: str, rows: int = 3) -> list[Candidate] | None:
    """Livros em português (Google Books). Só com ``GOOGLE_BOOKS_API_KEY`` no ambiente."""
    import os

    key = os.environ.get("GOOGLE_BOOKS_API_KEY", "").strip()
    if not key:  # a cota anônima é compartilhada e vive esgotada
        return None
    res = http.get_json(
        GBOOKS,
        {"q": query[:300], "langRestrict": "pt", "printType": "books", "maxResults": rows},
        headers={"x-goog-api-key": key},
    )
    if res is None or res[1] is None:
        return None
    out = []
    for it in res[1].get("items") or []:
        v = it.get("volumeInfo") or {}
        authors_full = [str(a) for a in v.get("authors") or [] if a]
        date = str(v.get("publishedDate") or "")
        isbn = next(
            (
                str(i.get("identifier"))
                for i in v.get("industryIdentifiers") or []
                if str(i.get("type", "")).startswith("ISBN")
            ),
            "",
        )
        out.append(
            Candidate(
                "Google Books",
                " ".join(
                    x for x in (str(v.get("title") or ""), str(v.get("subtitle") or "")) if x
                ).strip(),
                [a.split()[-1] for a in authors_full],
                int(date[:4]) if date[:4].isdigit() else None,
                str(v.get("publisher") or ""),
                "",
                str(v.get("canonicalVolumeLink") or v.get("infoLink") or ""),
                None,
                " ".join(re.sub(r"<[^>]+>", " ", str(v.get("description") or "")).split()),
                {
                    "authors_full": authors_full,
                    "tipo": "livro",
                    "isbn": isbn,
                    "lingua": str(v.get("language") or ""),
                },
            )
        )
    return out


OPENLIBRARY = "https://openlibrary.org/search.json"


def openlibrary_search(http: Any, query: str, rows: int = 3) -> list[Candidate] | None:
    """Livros em português (Open Library, sem chave)."""
    res = http.get_json(
        OPENLIBRARY,
        {
            "q": query[:200],
            "language": "por",
            "limit": rows,
            "fields": "title,subtitle,author_name,first_publish_year,publisher,isbn,key",
        },
    )
    if res is None or res[1] is None:
        return None
    out = []
    for it in res[1].get("docs") or []:
        authors_full = [str(a) for a in it.get("author_name") or [] if a]
        isbns = [str(i) for i in it.get("isbn") or []]
        isbn = next((i for i in isbns if len(i) == 13), isbns[0] if isbns else "")
        key = str(it.get("key") or "")
        out.append(
            Candidate(
                "Open Library",
                ": ".join(
                    x for x in (str(it.get("title") or ""), str(it.get("subtitle") or "")) if x
                ),
                [a.split()[-1] for a in authors_full],
                it.get("first_publish_year"),
                _first(it.get("publisher")),
                "",
                f"https://openlibrary.org{key}" if key.startswith("/") else "",
                None,
                "",
                {"authors_full": authors_full, "tipo": "livro", "isbn": isbn, "lingua": "pt"},
            )
        )
    return out
