"""errei-ref: leitor de referências (marcação de tokens BIO).

Dados sintéticos e sem problema de licença: só os campos bibliográficos (CC0, OpenAlex) de
cada obra, formatados em ABNT, APA, Vancouver, IEEE e Chicago, com ruído de PDF
(hifenização, campos faltando, caixa alta, troca de caracteres do OCR, numeração). O
rótulo de cada token sai de graça, porque sabemos de que campo veio cada pedaço.

Tokens: ``TOKEN_RX`` (palavras e cada sinal de pontuação). O errei deve usar a mesma
expressão no uso (vai em ``errei_tarefa.json``).
"""

from __future__ import annotations

import random
import re
from collections import Counter
from typing import Any

from banco.banco import Banco

from modelos import Conjunto, lotes, obras

NOME = "errei-ref"
TAREFA = "tokens"
CAMPOS = [
    "AUTOR",
    "TITULO",
    "VEICULO",
    "ANO",
    "VOLUME",
    "NUMERO",
    "PAGINAS",
    "DOI",
    "URL",
    "EDITORA",
    "LOCAL",
    "ACESSO",
]
LABELS = ["O"] + [f"{p}-{c}" for c in CAMPOS for p in ("B", "I")]
ESTILOS = ("abnt", "apa", "vancouver", "ieee", "chicago")
TOKEN_RX = r"\w+|[^\w\s]"
_TOK = re.compile(TOKEN_RX)
PARTICULAS = {"de", "da", "do", "das", "dos", "e", "del", "van", "von", "der", "la", "le", "di"}
SUFIXOS = {"junior", "júnior", "jr", "filho", "neto", "sobrinho"}
CIDADES = [
    "São Paulo",
    "Rio de Janeiro",
    "Belo Horizonte",
    "Porto Alegre",
    "Curitiba",
    "Salvador",
    "Recife",
    "Brasília",
    "Campinas",
    "Florianópolis",
    "Fortaleza",
    "Lisboa",
    "Petrópolis",
]
EDITORAS = [
    "Atlas",
    "Vozes",
    "Cortez",
    "Saraiva",
    "Edusp",
    "Editora UFMG",
    "Zahar",
    "Artmed",
    "Springer",
    "Elsevier",
    "Routledge",
    "Editora Fiocruz",
    "Blucher",
    "Ática",
]
MESES = [
    "jan.",
    "fev.",
    "mar.",
    "abr.",
    "maio",
    "jun.",
    "jul.",
    "ago.",
    "set.",
    "out.",
    "nov.",
    "dez.",
]
OCR = [
    ("l", "1"),
    ("O", "0"),
    ("m", "rn"),
    ("é", "e"),
    ("ç", "c"),
    ("ã", "a"),
    ("i", "í"),
    ("S", "5"),
]

CARTAO = """---
license: {licenca}
language: [pt, en, es]
tags: [errei, token-classification, reference-parsing, abnt, apa, vancouver, ieee]
---

# errei-ref

Lê uma referência bibliográfica (ABNT, APA, Vancouver, IEEE, Chicago), mesmo com ruído
de PDF, e marca autor, título, veículo, ano, volume, número, páginas, DOI, URL, editora,
local e data de acesso. Substitui as expressões regulares de
`errei/documento/referencias.py` e a leitura de listas de referências pelo Claude Code
no `apud`.

Entrada: tokens de `re.findall(r"\\w+|[^\\w\\s]", referencia)`; rótulos BIO por token.
Treinado só com referências sintéticas montadas de metadados bibliográficos (CC0).
"""


# ---------------------------------------------------------------------- nomes
def partes_nome(nome: str) -> tuple[list[str], str]:
    """'Ana Maria da Silva Júnior' → (['Ana', 'Maria', 'da'], 'Silva Júnior').

    Como na NBR 6023 para nomes em português: a partícula fica com o prenome
    (SILVA JÚNIOR, Ana Maria da) e o sufixo de parentesco vai com o sobrenome."""
    ws = nome.replace(",", " ").split()
    if len(ws) == 1:
        return [], ws[0]
    fim = len(ws) - 1
    if ws[fim].lower().strip(".") in SUFIXOS and fim > 1:
        fim -= 1
    return ws[:fim], " ".join(ws[fim:])


def iniciais(prenomes: list[str], ponto: bool = True, espaco: bool = True) -> str:
    ps = [
        p[0].upper() + ("." if ponto else "")
        for p in prenomes
        if p.lower() not in PARTICULAS and p[:1].isalpha()
    ]
    return (" " if espaco else "").join(ps)


def nome_abnt(n: str, r: random.Random) -> str:
    pre, sob = partes_nome(n)
    ini = " ".join(pre) if r.random() < 0.4 else iniciais(pre)
    return f"{sob.upper()}, {ini}" if ini else sob.upper()


def nome_apa(n: str, r: random.Random) -> str:
    pre, sob = partes_nome(n)
    return f"{sob}, {iniciais(pre)}" if pre else sob


def nome_vanc(n: str, r: random.Random) -> str:
    pre, sob = partes_nome(n)
    return f"{sob} {iniciais(pre, ponto=False, espaco=False)}".strip()


def nome_ieee(n: str, r: random.Random) -> str:
    pre, sob = partes_nome(n)
    return f"{iniciais(pre)} {sob}".strip()


def nome_chicago(n: str, i: int) -> str:
    pre, sob = partes_nome(n)
    return (f"{sob}, {' '.join(pre)}" if pre else sob) if i == 0 else n


# ---------------------------------------------------------------------- estilos
Peca = tuple[str, str | None]


def _autores(ps: list[str], sep: str, ultimo: str, maxn: int, etal: str) -> list[Peca]:
    out: list[Peca] = []
    corta = len(ps) > maxn
    ps = ps[:1] if corta and maxn <= 3 else ps[:maxn]
    for i, a in enumerate(ps):
        if i:
            out.append((ultimo if (i == len(ps) - 1 and not corta) else sep, None))
        out.append((a, "AUTOR"))
    if corta:
        out.append((etal, None))
    return out


def _ponto(pecas: list[Peca]) -> Peca:
    """Separador depois dos autores: sem ponto duplo quando o último termina em inicial ("B.")."""
    return (" " if pecas and pecas[-1][0].endswith(".") else ". "), None


def _pags(o: dict[str, Any], traco: str) -> str:
    a, z = o.get("pagina_ini"), o.get("pagina_fim")
    return f"{a}{traco}{z}" if a and z and a != z else (a or "")


def abnt(o: dict[str, Any], r: random.Random) -> list[Peca]:
    ps = _autores([nome_abnt(a, r) for a in o["autores"]], "; ", "; ", 3, " et al.")
    out = [*ps, _ponto(ps), (o["titulo"], "TITULO"), (". ", None)]
    if o["livro"]:
        if r.random() < 0.3:
            out += [(f"{r.randint(2, 9)}. ed. ", None)]
        return [
            *out,
            (o["local"], "LOCAL"),
            (": ", None),
            (o["editora"], "EDITORA"),
            (", ", None),
            (o["ano"], "ANO"),
            (".", None),
            *_online_abnt(o, r),
        ]
    out += [(o["veiculo"], "VEICULO"), (", ", None)]
    if r.random() < 0.3:
        out += [(o["local"], "LOCAL"), (", ", None)]
    if o.get("volume"):
        out += [("v. ", None), (o["volume"], "VOLUME"), (", ", None)]
    if o.get("numero"):
        out += [("n. ", None), (o["numero"], "NUMERO"), (", ", None)]
    if o.get("paginas"):
        out += [("p. ", None), (o["paginas"], "PAGINAS"), (", ", None)]
    out += [(o["ano"], "ANO"), (".", None)]
    if o.get("doi") and r.random() < 0.6:
        out += [(" DOI: ", None), (o["doi"], "DOI"), (".", None)]
    return out + _online_abnt(o, r)


def _online_abnt(o: dict[str, Any], r: random.Random) -> list[Peca]:
    if not o.get("url") or r.random() < 0.5:
        return []
    return [
        (" Disponível em: ", None),
        (o["url"], "URL"),
        (". Acesso em: ", None),
        (o["acesso"], "ACESSO"),
        (".", None),
    ]


def apa(o: dict[str, Any], r: random.Random) -> list[Peca]:
    ps = _autores([nome_apa(a, r) for a in o["autores"]], ", ", ", & ", 20, ", et al.")
    out = [
        *ps,
        (" (", None),
        (o["ano"], "ANO"),
        (("). ", None)),
        (o["titulo"], "TITULO"),
        (". ", None),
    ]
    if o["livro"]:
        out += [(o["editora"], "EDITORA"), (".", None)]
    else:
        out += [(o["veiculo"], "VEICULO")]
        if o.get("volume"):
            out += [(", ", None), (o["volume"], "VOLUME")]
        if o.get("numero"):
            out += [("(", None), (o["numero"], "NUMERO"), (")", None)]
        if o.get("paginas"):
            out += [(", ", None), (o["paginas"].replace("-", "–"), "PAGINAS")]
        out += [(".", None)]
    if o.get("doi"):
        out += [(" ", None), ("https://doi.org/" + o["doi"], "DOI")]
    elif o.get("url"):
        out += [(" ", None), (o["url"], "URL")]
    return out


def vancouver(o: dict[str, Any], r: random.Random) -> list[Peca]:
    ps = _autores([nome_vanc(a, r) for a in o["autores"]], ", ", ", ", 6, ", et al.")
    out = [*ps, _ponto(ps), (o["titulo"], "TITULO"), (". ", None)]
    if o["livro"]:
        return [
            *out,
            (o["local"], "LOCAL"),
            (": ", None),
            (o["editora"], "EDITORA"),
            ("; ", None),
            (o["ano"], "ANO"),
            (".", None),
        ]
    out += [(re.sub(r"[^\w\s]", "", o["veiculo"]), "VEICULO"), (". ", None), (o["ano"], "ANO")]
    if o.get("volume"):
        out += [(";", None), (o["volume"], "VOLUME")]
    if o.get("numero"):
        out += [("(", None), (o["numero"], "NUMERO"), (")", None)]
    if o.get("paginas"):
        out += [(":", None), (o["paginas"], "PAGINAS")]
    out += [(".", None)]
    if o.get("doi") and r.random() < 0.6:
        out += [(" doi:", None), (o["doi"], "DOI")]
    return out


def ieee(o: dict[str, Any], r: random.Random) -> list[Peca]:
    ps = _autores(
        [nome_ieee(a, r) for a in o["autores"]],
        ", ",
        ", and " if len(o["autores"]) > 2 else " and ",
        6,
        " et al.",
    )
    out = [*ps, (", “", None), (o["titulo"], "TITULO"), (",” ", None)]
    if o["livro"]:
        return [
            *out,
            (o["local"], "LOCAL"),
            (": ", None),
            (o["editora"], "EDITORA"),
            (", ", None),
            (o["ano"], "ANO"),
            (".", None),
        ]
    out += [(o["veiculo"], "VEICULO")]
    if o.get("volume"):
        out += [(", vol. ", None), (o["volume"], "VOLUME")]
    if o.get("numero"):
        out += [(", no. ", None), (o["numero"], "NUMERO")]
    if o.get("paginas"):
        out += [(", pp. ", None), (o["paginas"].replace("-", "–"), "PAGINAS")]
    out += [(", ", None), (o["ano"], "ANO")]
    if o.get("doi") and r.random() < 0.6:
        out += [(", doi: ", None), (o["doi"], "DOI")]
    return [*out, (".", None)]


def chicago(o: dict[str, Any], r: random.Random) -> list[Peca]:
    ns = [nome_chicago(a, i) for i, a in enumerate(o["autores"][:10])]
    ps = _autores(ns, ", ", ", and " if len(ns) > 2 else " and ", 10, " et al.")
    out = [*ps, _ponto(ps), (o["ano"], "ANO"), (". ", None)]
    if o["livro"]:
        return [
            *out,
            (o["titulo"], "TITULO"),
            (". ", None),
            (o["local"], "LOCAL"),
            (": ", None),
            (o["editora"], "EDITORA"),
            (".", None),
        ]
    out += [("“", None), (o["titulo"], "TITULO"), (".” ", None), (o["veiculo"], "VEICULO")]
    if o.get("volume"):
        out += [(" ", None), (o["volume"], "VOLUME")]
    if o.get("numero"):
        out += [(" (", None), (o["numero"], "NUMERO"), (")", None)]
    if o.get("paginas"):
        out += [(": ", None), (o["paginas"].replace("-", "–"), "PAGINAS")]
    out += [(".", None)]
    if o.get("doi"):
        out += [(" https://doi.org/", None), (o["doi"], "DOI"), (".", None)]
    return out


FORMATOS = {"abnt": abnt, "apa": apa, "vancouver": vancouver, "ieee": ieee, "chicago": chicago}


# ---------------------------------------------------------------------- ruído e tokens
def ruido_obra(o: dict[str, Any], r: random.Random, p: float) -> dict[str, Any]:
    o = dict(o)
    for k in ("numero", "doi", "url", "paginas", "volume"):
        if r.random() < p * 0.4:
            o[k] = ""
    if r.random() < p * 0.3:
        o["titulo"] = o["titulo"].upper()
    if r.random() < p * 0.2:
        o["veiculo"] = o["veiculo"].upper()
    return o


def tokens_bio(pecas: list[Peca], r: random.Random, p: float) -> tuple[list[str], list[str]]:
    toks: list[str] = []
    tags: list[str] = []
    for texto, campo in pecas:
        ts = _TOK.findall(texto or "")
        if campo in {"TITULO", "VEICULO"} and r.random() < p * 0.5:  # hifenização de fim de linha
            longas = [i for i, t in enumerate(ts) if len(t) >= 8 and t.isalpha()]
            if longas:
                i = r.choice(longas)
                c = r.randint(3, len(ts[i]) - 3)
                ts = [*ts[:i], ts[i][:c], "-", ts[i][c:], *ts[i + 1 :]]
        for j, t in enumerate(ts):
            if r.random() < p * 0.02:
                a, z = r.choice(OCR)
                t = t.replace(a, z, 1) or t
            toks.append(t)
            tags.append("O" if not campo else f"{'B' if j == 0 else 'I'}-{campo}")
    return toks, tags


def numeracao(estilo: str, i: int) -> list[Peca]:
    if estilo == "ieee":
        return [(f"[{i}] ", None)]
    if estilo == "vancouver":
        return [(f"{i}. ", None)]
    return []


# ---------------------------------------------------------------------- construção
def dados_obra(
    r: Any, autores: list[str], veiculo: str, rnd: random.Random
) -> dict[str, Any] | None:
    if not (r["titulo"] and r["ano"] and autores):
        return None
    livro = (r["tipo"] in {"book", "book-chapter"}) or rnd.random() < 0.1
    if not veiculo and not livro:
        return None
    doi = r["doi"] or ""
    url = r["url_oa"] or (f"https://doi.org/{doi}" if doi and rnd.random() < 0.5 else "")
    d = rnd.randint(1, 28)
    return {
        "autores": autores,
        "titulo": " ".join(str(r["titulo"]).split()),
        "ano": str(r["ano"]),
        "veiculo": veiculo or "",
        "volume": r["volume"] or "",
        "numero": r["numero"] or "",
        "paginas": _pags(dict(r), "-"),
        "doi": doi,
        "url": url,
        "livro": livro,
        "editora": r["editora"] or rnd.choice(EDITORAS),
        "local": rnd.choice(CIDADES),
        "acesso": f"{d} {rnd.choice(MESES)} {rnd.randint(2015, 2026)}",
    }


def construir(b: Banco, m: dict[str, Any], fumaca: bool) -> Conjunto:
    rnd = random.Random(int(m.get("semente", 42)))
    estilos = tuple(m.get("estilos") or ESTILOS)
    var = int(m.get("variantes_por_obra", 2))
    p = float(m.get("ruido", 0.3))
    maximo = int(m.get("max_obras", 0))
    rows: list[dict[str, Any]] = []
    n_obras = 0
    for lote in lotes(obras(b, m, texto=False)):
        ids = [r["id"] for r in lote]
        aut = b.mapa("autores", ids)
        fids = sorted({r["fonte_id"] for r in lote if r["fonte_id"]})
        nomes = (
            dict(
                b.con.execute(
                    f"SELECT id, nome FROM fontes WHERE id IN ({', '.join('?' * len(fids))})",
                    fids,
                ).fetchall()
            )
            if fids
            else {}
        )
        for r in lote:
            o = dados_obra(
                r, [a for a in aut.get(r["id"], []) if a][:30], nomes.get(r["fonte_id"], ""), rnd
            )
            if o is None:
                continue
            n_obras += 1
            for k in rnd.sample(estilos, min(var, len(estilos))):
                ob = ruido_obra(o, rnd, p)
                pecas = (
                    numeracao(k, rnd.randint(1, 80)) + FORMATOS[k](ob, rnd)
                    if rnd.random() < p
                    else FORMATOS[k](ob, rnd)
                )
                toks, tags = tokens_bio(pecas, rnd, p)
                if len(toks) >= 5:
                    rows.append({"tokens": toks, "tags": tags, "estilo": k, "grupo": r["id"]})
        if maximo and n_obras >= maximo:
            break
    aceitos = [
        {
            "nome": f"referências sintéticas de {n_obras} obras (só campos bibliográficos)",
            "licenca": "CC0 (metadados OpenAlex)",
            "fonte": "banco errei (OpenAlex)",
            "n": len(rows),
        }
    ]
    info = {
        "token_regex": TOKEN_RX,
        "estilos": dict(Counter(r["estilo"] for r in rows)),
        "ruido": p,
    }
    return Conjunto(rows, aceitos, {}, LABELS, info, Counter({"cc0": n_obras}))
