"""Localiza e lê o texto completo de uma obra em fontes de acesso livre.

Ordem de tentativa (para na primeira que entregar texto legível):

1. todas as ``oa_locations`` do OpenAlex (não só a melhor);
2. Unpaywall (requer e-mail: ``--email`` ou ``email`` no config);
3. Europe PMC / PMC (XML do texto completo);
4. arXiv (PDF);
5. CORE (opcional: ``CORE_API_KEY`` ou ``[core] api_key`` no config do usuário);
6. página do DOI na editora/repositório: meta tag ``citation_pdf_url`` (inclui SciELO).

Regras: só acesso livre (nada de sites que distribuem cópias sem autorização), o
``robots.txt`` de cada site é respeitado, o cliente se identifica (User-Agent do errei) e
obedece ao limite por host. Nenhum bloqueio é contornado. O texto é usado para comparar
frases; o relatório mostra no máximo 300 caracteres de cada trecho, sempre com a fonte.
"""

from __future__ import annotations

import io
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote, urljoin, urlsplit
from urllib.robotparser import RobotFileParser

UNPAYWALL = "https://api.unpaywall.org/v2"
EUROPEPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest"
CORE = "https://api.core.ac.uk/v3"
ARXIV_PDF = "https://arxiv.org/pdf"
UA_ROBOTS = "errei"
MAX_PDF = 30 * 1024 * 1024
_META_PDF = re.compile(
    r"""<meta\s+[^>]*?(?:name|property)\s*=\s*["'](?:citation_pdf_url|eprints\.document_url)["']"""
    r"""[^>]*?content\s*=\s*["']([^"']+)["']"""
    r"""|<meta\s+[^>]*?content\s*=\s*["']([^"']+)["'][^>]*?(?:name|property)\s*=\s*"""
    r"""["']citation_pdf_url["']""",
    re.IGNORECASE,
)


@dataclass(slots=True)
class Local:
    url: str
    origem: str  # OpenAlex | Unpaywall | Europe PMC | arXiv | CORE | página do DOI
    licenca: str = ""
    tipo: str = "pdf"  # pdf | xml


@dataclass(slots=True)
class TextoCompleto:
    paginas: list[str]  # PDF: uma entrada por página; XML: um bloco só
    paginado: bool
    origem: str
    url: str
    licenca: str = ""
    tentativas: list[str] = field(default_factory=list)

    def descricao(self) -> str:
        lic = self.licenca or "licença não declarada"
        return f"texto completo via {self.origem} ({lic}): {self.url}"


# ---------------------------------------------------------------------- localizar
def _openalex_locais(it: dict[str, Any]) -> list[Local]:
    out = []
    for loc in it.get("oa_locations") or []:
        url = str(loc.get("pdf_url") or "")
        if url:
            out.append(Local(url, "OpenAlex", str(loc.get("license") or "")))
    return out


def locais_openalex(http: Any, doi: str) -> list[Local]:
    from errei.net.sources import OPENALEX

    res = http.get_json(f"{OPENALEX}/works/doi:{quote(doi, safe='/:;()._-')}")
    if res is None or res[0] != 200 or not res[1]:
        return []
    return _openalex_locais(res[1])


def locais_unpaywall(http: Any, doi: str, email: str) -> list[Local]:
    if not email:
        return []
    res = http.get_json(f"{UNPAYWALL}/{quote(doi, safe='/:;()._-')}", {"email": email})
    if res is None or res[0] != 200 or not res[1]:
        return []
    out = []
    for loc in res[1].get("oa_locations") or []:
        url = str(loc.get("url_for_pdf") or "")
        if url:
            out.append(Local(url, "Unpaywall", str(loc.get("license") or "")))
    return out


def locais_europepmc(http: Any, doi: str) -> list[Local]:
    res = http.get_json(
        f"{EUROPEPMC}/search",
        {"query": f'DOI:"{doi}"', "format": "json", "resultType": "lite", "pageSize": 1},
    )
    if res is None or res[0] != 200 or not res[1]:
        return []
    hits = ((res[1].get("resultList") or {}).get("result")) or []
    if not hits:
        return []
    h = hits[0]
    pmcid = str(h.get("pmcid") or "")
    if not pmcid or str(h.get("isOpenAccess") or "").upper() != "Y":
        return []
    return [
        Local(f"{EUROPEPMC}/{pmcid}/fullTextXML", "Europe PMC", str(h.get("license") or ""), "xml")
    ]


def locais_core(http: Any, doi: str, key: str) -> list[Local]:
    if not key:
        return []
    res = http.get_json(
        f"{CORE}/search/works",
        {"q": f'doi:"{doi}"', "limit": 3},
        headers={"Authorization": f"Bearer {key}"},
    )
    if res is None or res[0] != 200 or not res[1]:
        return []
    out = []
    for it in res[1].get("results") or []:
        url = str(it.get("downloadUrl") or "")
        if url:
            out.append(Local(url, "CORE", str(it.get("license") or "")))
    return out


def locais_pagina_doi(http: Any, doi: str) -> list[Local]:
    """Lê a página do DOI (editora, SciELO, repositório) e procura ``citation_pdf_url``."""
    url = f"https://doi.org/{quote(doi, safe='/:;()._-')}"
    res = http.get_text(url, headers={"Accept": "text/html,application/xhtml+xml"})
    if res is None or res[0] != 200:
        return []
    body = res[1][:400_000]
    final = str((getattr(http, "last_url", None) or {}).get(url, url))
    out = []
    for m in _META_PDF.finditer(body):
        pdf = (m.group(1) or m.group(2) or "").replace("&amp;", "&").strip()
        if pdf:
            out.append(Local(urljoin(final, pdf), "página do DOI"))
    return out[:2]


def localizar(
    http: Any,
    *,
    doi: str = "",
    arxiv: str = "",
    oa_locais: list[Local] | None = None,
    email: str = "",
    core_key: str = "",
) -> list[Local]:
    """Candidatos a texto completo, na ordem de preferência, sem repetição de URL."""
    out: list[Local] = list(oa_locais or [])
    if doi:
        if not out:
            out += locais_openalex(http, doi)
        out += locais_unpaywall(http, doi, email)
        out += locais_europepmc(http, doi)
    if arxiv:
        out.append(Local(f"{ARXIV_PDF}/{arxiv.replace('arXiv:', '').strip()}", "arXiv"))
    if doi:
        out += locais_core(http, doi, core_key)
        out += locais_pagina_doi(http, doi)
    seen: set[str] = set()
    uniq = []
    for loc in out:
        if loc.url not in seen and loc.url.startswith(("https://", "http://")):
            seen.add(loc.url)
            uniq.append(loc)
    return uniq


# ---------------------------------------------------------------------- ler
def permitido(http: Any, url: str) -> bool:
    """O ``robots.txt`` do site permite o errei buscar esta URL?

    404 (sem robots.txt) libera; falha de rede ou 5xx bloqueia (por prudência)."""
    parts = urlsplit(url)
    host = f"{parts.scheme}://{parts.netloc}"
    res = http.get_text(f"{host}/robots.txt", headers={"Accept": "text/plain"})
    if res is None:
        return False
    status, body = res
    if 400 <= status < 500:
        return True
    if status != 200:
        return False
    rp = RobotFileParser()
    rp.parse(body.splitlines())
    delay = rp.crawl_delay(UA_ROBOTS)
    if delay and hasattr(http, "respeitar_crawl_delay"):
        http.respeitar_crawl_delay(parts.hostname or "", float(delay))
    return rp.can_fetch(UA_ROBOTS, url)


def paginas_pdf(data: bytes) -> list[str] | None:
    if not data or not data.startswith(b"%PDF"):
        return None
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        return [(p.extract_text() or "") for p in reader.pages[:400]]
    except Exception:  # PDF malformado/criptografado: não legível
        return None


def texto_xml(body: str) -> str | None:
    """Corpo de um XML JATS (Europe PMC/PMC), sem referências nem tabelas."""
    if "<!DOCTYPE" in body or "<!ENTITY" in body:  # entrada não confiável: sem DTD
        body = re.sub(r"<!DOCTYPE[^>]*(\[.*?\])?>", "", body, flags=re.DOTALL)
        if "<!ENTITY" in body:
            return None
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return None
    corpo = root.find(".//body")
    if corpo is None:
        return None
    partes = [" ".join("".join(p.itertext()).split()) for p in corpo.iter("p")]
    texto = "\n".join(p for p in partes if p)
    return texto or None


def obter(http: Any, locais: list[Local], max_tentativas: int = 4) -> TextoCompleto | None:
    tentativas: list[str] = []
    for loc in locais[:max_tentativas]:
        if loc.origem != "Europe PMC" and not permitido(http, loc.url):
            tentativas.append(f"{loc.origem}: robots.txt não permite {loc.url}")
            continue
        if loc.tipo == "xml":
            res = http.get_text(loc.url, headers={"Accept": "application/xml"})
            texto = texto_xml(res[1]) if res is not None and res[0] == 200 else None
            if texto:
                return TextoCompleto([texto], False, loc.origem, loc.url, loc.licenca, tentativas)
            tentativas.append(f"{loc.origem}: XML indisponível")
            continue
        pags = paginas_pdf(http.get_bytes(loc.url, max_bytes=MAX_PDF) or b"")
        if pags and sum(len(p.strip()) for p in pags) >= 80:  # PDF escaneado não tem texto
            return TextoCompleto(pags, True, loc.origem, loc.url, loc.licenca, tentativas)
        tentativas.append(f"{loc.origem}: PDF indisponível ou sem texto ({loc.url})")
    return None


def texto_de(ctx: Any, cand: Any) -> TextoCompleto | None:
    """Texto completo de um ``Candidate`` (com cache por execução em ``ctx.shared``)."""
    if ctx.http is None:
        return None
    doi = str(getattr(cand, "doi", "") or "")
    extra = getattr(cand, "extra", {}) or {}
    arxiv = str(extra.get("arxiv") or "")
    url = str(getattr(cand, "url", "") or "")
    if not arxiv and "arxiv.org/abs/" in url:
        arxiv = url.rsplit("/abs/", 1)[1]
    chave = doi.lower() or arxiv or url
    if not chave:
        return None
    memo: dict[str, TextoCompleto | None] = ctx.shared.setdefault("_texto_completo", {})
    if chave in memo:
        return memo[chave]
    import os

    oa = [Local(str(x[0]), "OpenAlex", str(x[1])) for x in extra.get("oa_locais") or []]
    pdf_url = str(extra.get("pdf_url") or "")
    if pdf_url and all(o.url != pdf_url for o in oa):
        oa.insert(
            0,
            Local(
                pdf_url,
                str(getattr(cand, "source", "")) or "OpenAlex",
                str(extra.get("oa_licenca") or ""),
            ),
        )
    core_key = os.environ.get("CORE_API_KEY") or str(
        ctx.config.trusted_get("core", "api_key", "") or ""
    )
    locais = localizar(
        ctx.http,
        doi=doi,
        arxiv=arxiv,
        oa_locais=oa,
        email=str(ctx.config.email or ""),
        core_key=core_key,
    )
    tc = obter(ctx.http, locais)
    memo[chave] = tc
    return tc


def trechos(tc: TextoCompleto, termos: str, n: int = 60) -> list[tuple[str, int | None]]:
    """Frases do texto completo (com a página), as ``n`` com mais termos da afirmação."""
    from errei.checkers.literatura import lexical
    from errei.citecheck import frases

    out: list[tuple[str, int | None]] = []
    for i, pag in enumerate(tc.paginas, 1):
        fr = [f for f in frases(pag) if 40 <= len(f) <= 600]
        out += [(f, i if tc.paginado else None) for f in fr]
        out += [
            (fr[k] + " " + fr[k + 1], i if tc.paginado else None)
            for k in range(len(fr) - 1)
            if len(fr[k]) + len(fr[k + 1]) <= 600
        ]
    out.sort(key=lambda t: lexical(termos, t[0]), reverse=True)
    return out[:n]
