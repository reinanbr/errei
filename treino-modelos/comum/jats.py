"""Leitura de artigos em JATS XML (Europe PMC, SciELO): seções, resumos, referências.

Também normaliza o título de cada seção num tipo (introdução, método, resultados...) e o
título das subseções numa "parte" (método: participantes, instrumentos, análise...). Esses
rótulos fracos treinam o ``errei-secoes``. XML com DOCTYPE/entidades é recusado.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from xml.etree import ElementTree as ET

XLINK = "{http://www.w3.org/1999/xlink}href"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"

TIPOS: list[tuple[str, re.Pattern[str]]] = [
    ("resultados_discussao", re.compile(r"resultados? (e|y|and) discuss|results? and discussion")),
    ("introducao", re.compile(r"^(\d+\W*)?(introdu|introduction|background|contexto|apresenta)")),
    (
        "revisao",
        re.compile(
            r"revis[aã]o (de|da|bibliogr)|referencial te[oó]rico|fundamenta[cç][aã]o te[oó]rica|"
            r"marco te[oó]rico|literature review|theoretical (framework|background)|estado da arte"
        ),
    ),
    (
        "metodo",
        re.compile(
            r"m[eé]todo|metodolog|materia(l|is) e m[eé]todo|material y m[eé]todo|methods?\b|"
            r"methodology|procedimentos? metodol|percurso metodol|delineamento|design do estudo"
        ),
    ),
    ("resultados", re.compile(r"^(\d+\W*)?(resultados?|results?|findings|achados)\b")),
    ("discussao", re.compile(r"^(\d+\W*)?(discuss|discusi)")),
    (
        "conclusao",
        re.compile(
            r"conclus|considera[cç](o|õ)es finais|concluding|final (remarks|considerations)|"
            r"consideraciones finales|considera[cç](o|õ)es"
        ),
    ),
]
PARTES: list[tuple[str, re.Pattern[str]]] = [
    (
        "metodo:participantes",
        re.compile(r"participantes|amostra|sujeitos|popula[cç][aã]o|participants|sample|muestra"),
    ),
    (
        "metodo:instrumentos",
        re.compile(
            r"instrumento|coleta de dados|data collection|measures|medidas|question[aá]rio|recolec"
        ),
    ),
    (
        "metodo:procedimentos",
        re.compile(
            r"procedimento|procedure|desenho|design|delineamento|tipo de estudo|study design"
        ),
    ),
    (
        "metodo:analise",
        re.compile(
            r"an[aá]lise (estat|dos dados|de dados)|statistical analys|data analys|tratamento dos dados"
        ),
    ),
    ("metodo:etica", re.compile(r"[eé]tic|ethic")),
    (
        "metodo:local",
        re.compile(r"local d|cen[aá]rio|setting|[aá]rea de estudo|study area|campo de pesquisa"),
    ),
    ("introducao:objetivo", re.compile(r"^objetivos?|^aims?\b|^objectives?|^prop[oó]sito")),
    (
        "introducao:problema",
        re.compile(r"justificativa|problema de pesquisa|research problem|hip[oó]tese"),
    ),
    ("discussao:limitacoes", re.compile(r"limita[cç]|limitations|limitaciones")),
    ("discussao:implicacoes", re.compile(r"implica[cç]|implications|contribui[cç]|recomenda[cç]")),
]


def _norm(s: str) -> str:
    return " ".join(re.sub(r"[^\w]+", " ", s.lower()).split())


def tipo_secao(titulo: str) -> str:
    t = _norm(titulo)
    for nome, rx in TIPOS:
        if rx.search(t):
            return nome
    return "outro"


def parte_secao(tipo: str, titulo: str) -> str:
    t = _norm(titulo)
    for nome, rx in PARTES:
        if rx.search(t) and (
            nome.split(":")[0] == tipo
            or tipo in {"outro", ""}
            or (tipo == "conclusao" and nome.startswith("discussao"))
        ):
            return nome
    return ""


@dataclass
class Secao:
    ordem: int
    nivel: int
    titulo: str
    tipo: str
    parte: str
    texto: str


@dataclass
class Artigo:
    lingua: str = ""
    licenca: str = ""
    titulo: str = ""
    resumos: dict[str, str] = field(default_factory=dict)
    palavras: dict[str, list[str]] = field(default_factory=dict)
    secoes: list[Secao] = field(default_factory=list)
    referencias: list[str] = field(default_factory=list)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _texto(
    el: ET.Element | None, pular: tuple[str, ...] = ("xref", "fn", "table-wrap", "fig")
) -> str:
    if el is None:
        return ""
    partes: list[str] = []

    def andar(e: ET.Element) -> None:
        if _local(e.tag) in pular:
            if e.tail:
                partes.append(e.tail)
            return
        if e.text:
            partes.append(e.text)
        for f in e:
            andar(f)
        if e.tail and e is not el:
            partes.append(e.tail)

    andar(el)
    return " ".join(html.unescape("".join(partes)).split())


def ler(dados: bytes) -> Artigo:
    if b"<!ENTITY" in dados:
        raise ValueError("JATS com entidades declaradas recusado")
    dados = re.sub(rb"<!DOCTYPE[^>]*>", b"", dados, count=1)
    raiz = ET.fromstring(dados)
    for e in raiz.iter():  # tira namespaces das tags (mantém atributos xlink/xml)
        e.tag = _local(e.tag)
    a = Artigo(lingua=(raiz.get(XML_LANG) or raiz.get("lang") or "").lower()[:2])
    lic = raiz.find(".//permissions/license")
    if lic is not None:
        a.licenca = lic.get(XLINK) or lic.get("license-type") or _texto(lic)
    a.titulo = _texto(raiz.find(".//front//article-title"))
    for ab in raiz.findall(".//front//abstract") + raiz.findall(".//front//trans-abstract"):
        if ab.get("abstract-type") in {"graphical", "teaser"}:
            continue
        lg = (ab.get(XML_LANG) or a.lingua or "").lower()[:2]
        partes = []
        for f in ab:
            if _local(f.tag) == "title":
                continue
            partes.append(_texto(f))
        txt = " ".join(p for p in partes if p) or _texto(ab)
        if txt and lg not in a.resumos:
            a.resumos[lg] = txt
    for kg in raiz.findall(".//front//kwd-group"):
        lg = (kg.get(XML_LANG) or a.lingua or "").lower()[:2]
        termos = [_texto(k) for k in kg.findall("kwd") if _texto(k)]
        if termos:
            a.palavras.setdefault(lg, []).extend(termos)
    body = raiz.find(".//body")
    if body is not None:
        ordem = 0

        def secoes(el: ET.Element, nivel: int, tipo_pai: str) -> None:
            nonlocal ordem
            for s in el.findall("sec"):
                titulo = _texto(s.find("title"))
                tipo = tipo_secao(titulo) if nivel == 1 else tipo_pai
                if nivel == 1 and tipo == "outro" and tipo_pai:
                    tipo = tipo_pai
                parte = parte_secao(tipo, titulo) if nivel > 1 else ""
                paras = [_texto(p) for p in s.findall("p")]
                texto = "\n".join(p for p in paras if p)
                if texto:
                    a.secoes.append(Secao(ordem, nivel, titulo, tipo, parte, texto))
                    ordem += 1
                secoes(s, nivel + 1, tipo)

        secoes(body, 1, "")
    for ref in raiz.findall(".//back//ref"):
        mc = ref.find(".//mixed-citation")
        if mc is None:
            mc = ref.find(".//element-citation")
        t = _texto(mc, pular=())
        if len(t) > 20:
            a.referencias.append(t)
    return a
