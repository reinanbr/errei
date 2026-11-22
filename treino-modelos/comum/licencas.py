"""Regra de licenças: o que pode entrar nos dados de treino.

Entram só textos com licença que permite uso comercial e redistribuição (CC BY, CC0,
domínio público; MIT e Apache-2.0 para conjuntos de dados). CC BY-NC e CC BY-ND nunca.
CC BY-SA só se ``aceitar_sa`` estiver ligado, e então os pesos saem em CC BY-SA.
Metadados do OpenAlex são CC0 e podem ser usados sem essa restrição.
"""

from __future__ import annotations

import re

ACEITAS = {"cc-by", "cc0", "public-domain", "mit", "apache-2.0"}
SA = {"cc-by-sa"}
# rótulos do OpenAlex aceitos no filtro da consulta (best_oa_location.license)
OPENALEX_ACEITAS = ("cc-by", "cc0", "public-domain")


def normalizar(lic: str | None) -> str:
    """'CC BY 4.0', 'by/4.0', 'http://creativecommons.org/licenses/by-nc/4.0/' → 'cc-by', 'cc-by-nc'..."""
    t = str(lic or "").strip().lower()
    if not t:
        return ""
    if "publicdomain/zero" in t or re.search(r"\bcc[\s_-]?0\b|cc-zero|cc0", t):
        return "cc0"
    if "publicdomain/mark" in t or "public domain" in t or t in {"public-domain", "pd"}:
        return "public-domain"
    if t == "mit" or t.startswith("mit "):
        return "mit"
    if "apache" in t:
        return "apache-2.0"
    m = re.search(r"licenses/([a-z-]+)/", t)
    partes = m.group(1) if m else t
    partes = partes.replace("cc ", "").replace("cc-", "").replace("_", "-").replace(" ", "-")
    partes = re.sub(r"[/-]?\d(\.\d)?.*$", "", partes).strip("-")
    tokens = set(partes.split("-"))
    if "by" not in tokens:
        return t  # desconhecida: fica como veio (e é recusada)
    nome = "cc-by"
    if "nc" in tokens:
        nome += "-nc"
    if "nd" in tokens:
        nome += "-nd"
    if "sa" in tokens:
        nome += "-sa"
    return nome


def tem_nc(lic: str | None) -> bool:
    n = normalizar(lic)
    return "-nc" in n or "noncommercial" in str(lic or "").lower()


def aceita(lic: str | None, aceitar_sa: bool = False) -> bool:
    n = normalizar(lic)
    return n in ACEITAS or (aceitar_sa and n in SA)


def motivo(lic: str | None, aceitar_sa: bool = False) -> str:
    n = normalizar(lic)
    if aceita(n, aceitar_sa):
        return f"{n}: permite uso comercial"
    if tem_nc(n):
        return f"{n or lic}: cláusula NC proíbe uso comercial; recusada sempre"
    if "-nd" in n:
        return f"{n}: cláusula ND proíbe obras derivadas; recusada"
    if n in SA:
        return f"{n}: só com aceitar_sa = true (os pesos saem em CC BY-SA)"
    return f"{n or 'sem licença'}: não é licença aberta reconhecida; recusada"
