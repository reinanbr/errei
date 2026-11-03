"""Medidas comparáveis entre o manuscrito e as obras da referência.

As mesmas funções medem os dois lados, para que a comparação seja justa:

* ``medir_texto``: extensão e escrita sobre texto corrido (corpo do PDF da obra, ou
  parágrafos do LaTeX do manuscrito). As medidas que dependem do português (Flesch
  adaptado, conectivos, passiva) só são calculadas para ``lang="pt"``.
* ``medir_refs``: referências a partir de ano/tipo/DOI de cada uma (obras citadas no
  OpenAlex, ou entradas citadas do .bib).
* ``medir_resumo``: papéis retóricos do resumo (errei-resumo, ou palavras-chave).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from statistics import mean, median
from typing import Any

from errei.checkers.ptbr import PASSIVE  # mesma regra do verificador de escrita
from errei.text.metrics import connectives, flesch_pt, mattr
from errei.text.segment import alpha_words, sentences, strip_accents


@dataclass(frozen=True, slots=True)
class Medida:
    chave: str
    rotulo: str
    grupo: str
    tipo: str = "num"  # num | bool
    unidade: str = ""
    casas: int = 1
    nota: str = ""  # viés conhecido da medida


MEDIDAS: tuple[Medida, ...] = (
    Medida(
        "refs_n",
        "Referências (nº)",
        "Referências",
        casas=0,
        nota="na referência, só as obras citadas que o OpenAlex localizou (subestima)",
    ),
    Medida(
        "refs_n_pdf",
        "Referências (nº, contadas no PDF)",
        "Referências",
        casas=0,
        nota="entradas da lista de referências do PDF, por padrão de autoria (aproximado)",
    ),
    Medida("refs_recentes_pct", "Referências dos 5 anos anteriores", "Referências", unidade="%"),
    Medida(
        "refs_periodicos_pct",
        "Referências que são artigos de periódico",
        "Referências",
        unidade="%",
    ),
    Medida(
        "refs_doi_pct",
        "Artigos citados com DOI",
        "Referências",
        unidade="%",
        nota="na referência, só obras localizadas no OpenAlex (superestima)",
    ),
    Medida("refs_idade_mediana", "Idade mediana das referências (anos)", "Referências"),
    Medida("palavras", "Extensão (palavras no corpo)", "Extensão", casas=0),
    Medida("resumo_palavras", "Extensão do resumo (palavras)", "Extensão", casas=0),
    Medida("frase_media", "Comprimento médio de frase (palavras)", "Escrita"),
    Medida("flesch", "Legibilidade (Flesch, Martins et al. 1996)", "Escrita"),
    Medida("mattr", "Diversidade lexical (MATTR-100)", "Escrita", casas=3),
    Medida("conectivos_100", "Conectivos por 100 palavras", "Escrita", casas=2),
    Medida("passiva_pct", "Frases com voz passiva", "Escrita", unidade="%"),
    Medida("cites_1000", "Citações por 1000 palavras", "Escrita"),
    Medida("decl_dados", "Disponibilidade de dados/código", "Declarações", "bool"),
    Medida("decl_conflito", "Conflito de interesses", "Declarações", "bool"),
    Medida("decl_autoria", "Contribuição dos autores (CRediT)", "Declarações", "bool"),
    Medida("decl_financiamento", "Financiamento", "Declarações", "bool"),
    Medida("decl_etica", "Aprovação ética", "Declarações", "bool"),
    Medida("resumo_objetivo", "Resumo declara o objetivo", "Resumo (NBR 6028)", "bool"),
    Medida("resumo_metodo", "Resumo descreve o método", "Resumo (NBR 6028)", "bool"),
    Medida("resumo_resultado", "Resumo traz resultados", "Resumo (NBR 6028)", "bool"),
)
POR_CHAVE = {m.chave: m for m in MEDIDAS}

# regex sobre texto minúsculo e sem acentos; pt e en (a referência "mundo" é em inglês)
DECL_RX: dict[str, re.Pattern[str]] = {
    "decl_dados": re.compile(
        r"(disponibilidade de dados|data availability|availability of data|dados (estao|sao|"
        r"serao|ficam) disponiveis|zenodo|figshare|\bosf\.io|github\.com|data are available)"
    ),
    "decl_conflito": re.compile(
        r"(conflitos? de interesses?|conflicts? of interest|competing interests?)"
    ),
    "decl_autoria": re.compile(
        r"(contribuic\w+ dos autores|contribuicao de autoria|author contributions?|"
        r"credit author|authors? contributions?)"
    ),
    "decl_financiamento": re.compile(
        r"(financiamento|fomento|\bcapes\b|\bcnpq\b|fapesp|\bfap[a-z]{2,}\b|\bfunding\b|"
        r"apoio financeiro|financial support|\bgrant\b)"
    ),
    "decl_etica": re.compile(
        r"(comite de etica|\bcaae\b|parecer consubstanciado|ethics committee|"
        r"institutional review board|\birb\b|consentimento livre)"
    ),
}

# eventos de citação no texto corrido do PDF: (SILVA, 2020; SOUZA, 2019, p. 3), Silva (2020)
# e [12, 14–16]; cada grupo conta uma vez, como um \cite no LaTeX
CITE_PAREN = re.compile(
    r"\([^()]{0,200}?\b(?:1[89]|20)\d{2}[a-z]?\b[^()]{0,60}\)"
    r"|\b[A-ZÀ-Ý][\wÀ-ÿ'\-]+(?: et al\.?)? \((?:1[89]|20)\d{2}[a-z]?\)"
    r"|\[\d{1,3}(?:\s?[,–-]\s?\d{1,3})*\]"
)


def _norm(s: str) -> str:
    return " ".join(strip_accents(s.lower()).split())


def medir_texto(texto: str, lang: str = "pt", n_cites: int | None = None) -> dict[str, Any]:
    """Medidas de extensão, escrita e declarações sobre texto corrido."""
    out: dict[str, Any] = {}
    ws = alpha_words(texto)
    if len(ws) < 300:
        return out
    out["palavras"] = len(ws)
    sents = [s for s in sentences(texto) if 3 <= len(alpha_words(s.text)) <= 120]
    if sents:
        out["frase_media"] = mean(len(alpha_words(s.text)) for s in sents)
    m = mattr(texto)
    if m is not None:
        out["mattr"] = m
    if lang == "pt":
        fl = flesch_pt(texto)
        if fl is not None:
            out["flesch"] = fl[0]
        out["conectivos_100"] = len(connectives(texto)) / len(ws) * 100
        if sents:
            out["passiva_pct"] = 100 * sum(1 for s in sents if PASSIVE.search(s.text)) / len(sents)
    if n_cites is None:
        n_cites = len(CITE_PAREN.findall(texto))
    out["cites_1000"] = n_cites / len(ws) * 1000
    norm = _norm(texto)
    for k, rx in DECL_RX.items():
        out[k] = bool(rx.search(norm))
    return out


def medir_refs(refs: list[dict[str, Any]], ano: int) -> dict[str, Any]:
    """``refs``: dicts com ``ano`` (int|None), ``periodico`` (bool) e ``doi`` (bool)."""
    if not refs:
        return {}
    out: dict[str, Any] = {"refs_n": len(refs)}
    anos = [r["ano"] for r in refs if r.get("ano")]
    if anos:
        out["refs_recentes_pct"] = 100 * sum(ano - 5 <= a <= ano for a in anos) / len(refs)
        out["refs_idade_mediana"] = max(0.0, ano - median(anos))
    out["refs_periodicos_pct"] = 100 * sum(bool(r.get("periodico")) for r in refs) / len(refs)
    arts = [r for r in refs if r.get("periodico")]
    if arts:
        out["refs_doi_pct"] = 100 * sum(bool(r.get("doi")) for r in arts) / len(arts)
    return out


def medir_resumo(texto: str, *, usar_modelo: bool = True) -> dict[str, Any]:
    from errei import resumocheck

    frases = [s.text for s in sentences(texto) if len(alpha_words(s.text)) >= 3]
    if len(frases) < 2:
        return {}
    el = resumocheck.elementos(resumocheck.analisar(frases, usar_modelo=usar_modelo))
    return {
        "resumo_palavras": len(alpha_words(texto)),
        "resumo_objetivo": el["objetivo"],
        "resumo_metodo": el["metodo"],
        "resumo_resultado": el["resultado"],
    }


# ------------------------------------------------------------------ manuscrito
def _ano_bib(e: Any) -> int | None:
    m = re.search(r"\d{4}", e.get("year") or e.get("date") or "")
    return int(m.group(0)) if m else None


def medir_projeto(project: Any, ano: int, *, usar_modelo: bool = True) -> dict[str, Any]:
    """As mesmas medidas, calculadas sobre o manuscrito LaTeX."""
    from errei.text.abstracts import find_abstracts

    out: dict[str, Any] = {}
    body = [p for p in project.paragraphs(("body", "item", "quote"))]
    pt = [p for p in body if p.lang == "pt"]
    texto = "\n\n".join(p.text for p in pt)
    n_cites = sum(sum(1 for c in p.clean.cites if p.start <= c.start < p.end) for p in body)
    out.update(medir_texto(texto, "pt", n_cites=n_cites))
    if "palavras" not in out and texto:
        out["palavras"] = len(alpha_words(texto))
    # declarações também em agradecimentos e seções não numeradas
    tudo = _norm(" ".join(p.text for p in project.paragraphs()))
    for k, rx in DECL_RX.items():
        out[k] = bool(rx.search(tudo))
    cited = {u.key for u in project.cite_uses()}
    seen: dict[str, Any] = {}
    for e in project.bib_entries:
        if e.key in cited:
            seen.setdefault(e.key, e)
    refs = [
        {"ano": _ano_bib(e), "periodico": e.type == "article", "doi": e.has("doi")}
        for e in seen.values()
    ]
    out.update(medir_refs(refs, ano))
    resumo = " ".join(b.text for b in find_abstracts(project) if b.lang == "pt")
    if resumo:
        out.update(medir_resumo(resumo, usar_modelo=usar_modelo))
    if "refs_n" in out:
        out["refs_n_pdf"] = out["refs_n"]  # no manuscrito, o .bib é a contagem exata
    return out


# ------------------------------------------------------------------ agregação
QUANTIS = (10, 25, 50, 75, 90)


def _quantil(xs: list[float], q: float) -> float:
    s = sorted(xs)
    if len(s) == 1:
        return s[0]
    pos = (len(s) - 1) * q / 100
    lo = int(pos)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def agregar(amostras: list[dict[str, Any]]) -> dict[str, Any]:
    """Quantis (num) ou frequência (bool) de cada medida; só valores agregados."""
    out: dict[str, Any] = {}
    for m in MEDIDAS:
        vals = [a[m.chave] for a in amostras if a.get(m.chave) is not None]
        if not vals:
            continue
        if m.tipo == "bool":
            out[m.chave] = {"n": len(vals), "freq": round(sum(map(bool, vals)) / len(vals), 3)}
        else:
            xs = [float(v) for v in vals]
            out[m.chave] = {"n": len(xs), **{f"p{q}": round(_quantil(xs, q), 3) for q in QUANTIS}}
    return out
