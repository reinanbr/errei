"""Converte um ``Documento`` num ``Project`` equivalente ao de LaTeX.

Cada bloco vira um parágrafo de um ``.tex`` sintético (títulos viram ``\\section``, o resumo
uma seção "Resumo", citações longas o ambiente ``citacao``, citações no texto ``\\cite``) e a
lista de referências vira um ``.bib`` sintético. Nada disso é gravado em disco.

Um mapa (``Conversao``) liga cada trecho do texto sintético ao bloco de origem: a
localização dos achados sai como parágrafo (``.docx``) ou página (``.pdf``) do arquivo
original, e o trecho citado no relatório é o texto original, sem os comandos inseridos.
"""

from __future__ import annotations

import re
import unicodedata
from bisect import bisect_right
from dataclasses import dataclass, field
from pathlib import Path

from errei.documento.modelo import Bloco, Documento
from errei.documento.referencias import Citacao, Indice, Referencia, analisar, citacoes
from errei.model import Location

# ------------------------------------------------------------------ mapa de posições


@dataclass(slots=True)
class Trecho:
    inicio: int  # offset no texto sintético
    fim: int
    bloco: Bloco | None  # None: preâmbulo/estrutura sem bloco de origem
    base: int = 0  # offset, no texto do bloco, onde este trecho começa
    trocas: list[tuple[int, int, str]] = field(default_factory=list)  # (ini, fim) → original
    texto: str = ""  # texto sintético do trecho


@dataclass(slots=True)
class Conversao:
    exibir: Path
    unidade: str  # "§" | "p."
    trechos: list[Trecho] = field(default_factory=list)
    _inicios: list[int] = field(default_factory=list, repr=False)

    def fechar(self) -> None:
        self._inicios = [t.inicio for t in self.trechos]

    def _achar(self, off: int) -> Trecho | None:
        if not self._inicios:
            self.fechar()
        i = bisect_right(self._inicios, off) - 1
        return self.trechos[i] if i >= 0 else None

    @staticmethod
    def _original(t: Trecho, rel: int) -> int:
        """Offset no texto do bloco correspondente ao offset ``rel`` do trecho."""
        delta = 0
        for a, b, orig in t.trocas:
            if rel < a:
                break
            if rel < b:
                return t.base + a - delta
            delta += (b - a) - len(orig)
        return t.base + rel - delta

    def unidade_de(self, off: int) -> int:
        t = self._achar(off)
        if t is None or t.bloco is None:
            return 0
        if not t.bloco.paginas:
            return t.bloco.unidade
        return t.bloco.pagina(self._original(t, off - t.inicio))

    def location(self, start: int, end: int | None = None) -> Location:
        u = self.unidade_de(start)
        if end is None:
            return Location(self.exibir, u, unit=self.unidade)
        ue = self.unidade_de(max(start, end - 1))
        return Location(self.exibir, u, None, ue if ue != u else None, None, unit=self.unidade)

    def trecho(self, start: int, end: int) -> str:
        """Texto original correspondente ao intervalo sintético (sem os comandos inseridos)."""
        out: list[str] = []
        i = start
        while i < end:
            t = self._achar(i)
            if t is None:
                break
            ate = min(end, t.fim)
            rel, rel_fim = i - t.inicio, ate - t.inicio
            pos = rel
            for a, b, orig in t.trocas:
                if b <= pos or a >= rel_fim:
                    continue
                out.append(t.texto[pos : max(pos, a)])
                out.append(orig)
                pos = max(pos, b)
            out.append(t.texto[pos:rel_fim])
            i = ate if ate > i else i + 1
        return "".join(out)


# ------------------------------------------------------------------ saída LaTeX

_ESC = {
    "\\": r"\textbackslash{}",
    "{": r"\{",
    "}": r"\}",
    "%": r"\%",
    "$": r"\$",
    "&": r"\&",
    "#": r"\#",
    "_": r"\_",
    "^": r"\^{}",
    "~": r"\~{}",
}
_ESC_RE = re.compile(r"[\\{}%$&#_^~]")
Peca = tuple[str, "str | None"]  # (LaTeX, texto original; None = igual)


def txt(s: str) -> list[Peca]:
    out: list[Peca] = []
    pos = 0
    for m in _ESC_RE.finditer(s):
        if m.start() > pos:
            out.append((s[pos : m.start()], None))
        out.append((_ESC[m.group(0)], m.group(0)))
        pos = m.end()
    if pos < len(s):
        out.append((s[pos:], None))
    return out


def est(s: str, orig: str = "") -> Peca:
    """Comando estrutural (não existe no original)."""
    return (s, orig)


class _Saida:
    def __init__(self, conv: Conversao) -> None:
        self.conv = conv
        self.partes: list[str] = []
        self.pos = 0

    def linha(self, pecas: list[Peca], bloco: Bloco | None, base: int = 0) -> None:
        trocas: list[tuple[int, int, str]] = []
        rel = 0
        textos: list[str] = []
        for latex, orig in pecas:
            if orig is not None:
                trocas.append((rel, rel + len(latex), orig))
            textos.append(latex)
            rel += len(latex)
        linha = "".join(textos) + "\n\n"
        t = Trecho(self.pos, self.pos + len(linha), bloco, base, trocas, linha)
        self.conv.trechos.append(t)
        self.partes.append(linha)
        self.pos += len(linha)

    def texto(self) -> str:
        self.conv.fechar()
        return "".join(self.partes)


# ------------------------------------------------------------------ classificação


def fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    return " ".join("".join(c for c in s if not unicodedata.combining(c)).split())


_NUM_TITULO = re.compile(
    r"^(?:(?:cap[ií]tulo|se[cç][aã]o|chapter|section)\s+)?"
    r"(?:(\d{1,2}(?:\.\d{1,2}){0,4})|([IVXLC]{1,6})(?=[.)\s–—-]))[.)]?\s*[–—-]?\s*",
    re.IGNORECASE,
)
_SECOES: list[tuple[str, str, str]] = [
    ("resumo", r"resumo", "pt"),
    ("resumo", r"abstract", "en"),
    ("resumo", r"resumen", "es"),
    ("resumo", r"resume", "fr"),
    ("sumario", r"sumario|indice|table of contents|contents", ""),
    ("lista_fig", r"lista de (?:figuras|ilustracoes|graficos|quadros|imagens)|list of figures", ""),
    ("lista_tab", r"lista de tabelas|list of tables", ""),
    (
        "lista_sig",
        r"lista de (?:abreviaturas|siglas|simbolos|acronimos)(?: e (?:siglas|abreviaturas|"
        r"simbolos))?|list of (?:abbreviations|acronyms|symbols)",
        "",
    ),
    (
        "refs",
        r"referencias(?: bibliograficas)?|bibliografia|references|bibliography|obras citadas|"
        r"literature cited",
        "",
    ),
    ("pre", r"dedicatoria|agradecimentos?|epigrafe|errata|acknowledg?ments?", ""),
    ("aprovacao", r"folha de aprovacao|banca examinadora", ""),
    ("pos", r"(?:apendices?|anexos?|appendix|appendices|annex)\b.*|glossario|glossary", ""),
    (
        "corpo",
        r"introducao|introduction|referencial teorico|fundamentacao teorica|"
        r"revisao (?:de|da) literatura|revisao bibliografica|marco teorico|metodologia|metodos?|"
        r"materiais e metodos|procedimentos metodologicos|methods?|methodology|"
        r"materials and methods|resultados(?: e discuss(?:ao|oes))?|discussao|"
        r"results(?: and discussion)?|discussion|conclus(?:ao|oes)|consideracoes finais|"
        r"conclusions?|final remarks|trabalhos? relacionados?|related works?|estado da arte|"
        r"desenvolvimento|estudo de caso|objetivos?|justificativa",
        "",
    ),
]
_SECOES_RE = [(k, re.compile(rf"^(?:{rx})$"), lang) for k, rx, lang in _SECOES]
_INLINE = re.compile(
    r"^(RESUMO|Resumo|ABSTRACT|Abstract|RESUMEN|Resumen|R[ÉE]SUM[ÉE]|Résumé)\s*[:.–—-]\s+",
)
_KW = re.compile(
    r"(?<=[.!?])\s+((?:PALAVRAS?|Palavras?)[- ](?:CHAVES?|chaves?)|KEYWORDS?|Keywords?|"
    r"Key words|Palabras clave)\s*[:.–—-]"
)
_LEGENDA = re.compile(
    r"^(Figura|Fig\.|Tabela|Quadro|Gr[aá]fico|Ilustra[cç][aã]o|Imagem|Mapa|Fotografia|Figure|"
    r"Table|Chart)\s+\d+",
    re.IGNORECASE,
)
_FONTE = re.compile(r"^(?:Fonte|Source|Elabora[cç][aã]o|Elaborado)\b", re.IGNORECASE)
_SUMARIO_ITEM = re.compile(r"(?:\.{3,}|…)\s*\d{1,4}$|\s\d{1,4}$")
_INSTITUICAO = re.compile(
    r"\b(?:universidade|university|universit[aéà]|instituto|institute|faculdade|faculty|"
    r"centro universit[aá]rio|escola|departamento|programa de p[oó]s|college|school|"
    r"department|laborat[oó]rio|campus)\b|"
    r"(?-i:\b(?:U[FE][A-Z]{1,4}|UTF[A-Z]{1,3}|USP|UnB|UNESP|UNICAMP|UNIFESP|IF[A-Z]{1,4}|"
    r"PUC[A-Za-z-]*|FGV|FIOCRUZ|EMBRAPA)\b)",
    re.IGNORECASE,
)
_MONOGRAFIA = re.compile(
    r"\b(?:trabalho de conclus[aã]o|monografia|disserta[cç][aã]o|tese)\b.*\b(?:apresentad|"
    r"submetid|requisito|obten[cç][aã]o)",
    re.IGNORECASE,
)
_FICHA = re.compile(r"dados internacionais de cataloga|ficha catalogr|\bCDD\b|\bCDU\b", re.I)
_APROVACAO = re.compile(r"banca examinadora|aprovad[oa] em|folha de aprova", re.IGNORECASE)
_NOME = re.compile(
    r"^(?:(?:[A-ZÀ-Ý][a-zà-ÿ'’.\-]+|[A-ZÀ-Ý]\.|[A-ZÀ-Ý]{2,}|d[aeo]s?|de|e)[\s,*¹²³⁴0-9]*){2,8}$"
)
_DATA = re.compile(r"^[\w\sÀ-ÿ,.\-–]{0,40}\b(?:1[5-9]|20)\d\d\.?$")
_MATEMATICA = re.compile(r"[=+−×÷∑∫√≤≥∞∂]")
_IDIOMA_LATEX = {"en": "english", "es": "spanish", "fr": "french"}


def _norm_titulo(t: str) -> str:
    t = _NUM_TITULO.sub("", t.strip(), count=1)
    return fold(t).strip(" :.–—-")


def _conhecida(t: str) -> tuple[str, str] | None:
    if len(t.split()) > 12:
        return None
    n = _norm_titulo(t)
    for k, rx, lang in _SECOES_RE:
        if rx.match(n):
            return k, lang
    return None


def _nivel_texto(b: Bloco, formato: str, estilos: bool) -> int:
    """Nível de título reconhecido pelo texto/formatação (sem estilo de título)."""
    t = b.texto.strip()
    ws = t.split()
    if not ws or len(ws) > 16 or len(t) > 160 or t.endswith((".", ",", ";", ":")):
        return 0
    if formato == "pdf" and len(b.linhas) > 2:
        return 0
    m = re.match(r"^(\d{1,2}(?:\.\d{1,2}){0,4})\.?\s+(?=[A-ZÀ-Ý])", t)
    if m and len(ws) <= 14:
        return m.group(1).count(".") + 1
    letras = re.sub(r"[^A-Za-zÀ-ÿ]", "", t)
    if len(letras) >= 4 and letras.isupper() and len(ws) <= 12:
        return 1
    if formato == "docx" and not estilos and b.destaque and len(ws) <= 12:
        return 1
    return 0


def _equacao(b: Bloco, formato: str) -> bool:
    """Linha de equação extraída do PDF ('F = 206,8 − 1,015 ASL (1)')."""
    t = b.texto.strip()
    if formato != "pdf" or len(b.linhas) > 3:
        return False
    numerada = re.search(r"\(\d{1,3}\)$", t) and _MATEMATICA.search(t)
    simbolos = len(_MATEMATICA.findall(t)) >= 3 and len(re.findall(r"[A-Za-zÀ-ÿ]{4,}", t)) <= 3
    return bool(numerada or simbolos)


def _idioma(texto: str) -> str:
    from errei.checkers.literatura import idioma

    return idioma(texto)


@dataclass(slots=True)
class Item:
    papel: str  # titulo autor afiliacao secao corpo item citacao legenda referencia
    bloco: Bloco
    texto: str = ""
    nivel: int = 1
    tipo: str = ""  # secao: resumo, refs, sumario, lista_fig, lista_tab, corpo, pre, pos...
    lang: str = ""
    estrela: bool = False
    base: int = 0  # offset do texto no bloco


@dataclass(slots=True)
class Info:
    """O que o conversor reconheceu (para o verificador 'documento' e o relatório)."""

    documento: Documento
    referencias: list[Referencia] = field(default_factory=list)
    citacoes: int = 0
    sem_referencia: dict[str, str] = field(default_factory=dict)  # chave inventada → texto
    rotulos: dict[str, str] = field(default_factory=dict)  # chave → 'SILVA, 2020'
    monografia: bool = False
    titulos: int = 0
    pulados: dict[str, int] = field(default_factory=dict)
    secao_refs: Bloco | None = None


def _dividir_referencias_pdf(b: Bloco) -> list[tuple[str, int]]:
    """Separa as entradas de um bloco de referências do PDF: (texto, offset no bloco)."""
    if len(b.linhas) <= 1:
        return [(b.texto, 0)]
    inicio = re.compile(
        r"^(?:[A-ZÀ-Ý][A-ZÀ-Ý'’\-]+(?:\s+[A-ZÀ-Ý'’\-]+)*,\s|\[\d{1,4}\]|\d{1,4}[.)]\s|_{3,}|—{2,})"
    )
    entradas: list[list[str]] = []
    for ln in b.linhas:
        if entradas and not (
            inicio.match(ln) and re.search(r"[.)]$|\d{4}[a-z]?\.?$", entradas[-1][-1])
        ):
            entradas[-1].append(ln)
        else:
            entradas.append([ln])
    if len(entradas) == 1:
        return [(b.texto, 0)]
    out: list[tuple[str, int]] = []
    pos = 0
    for e in entradas:
        primeira = e[0]
        achou = b.texto.find(primeira[:20], pos)
        off = achou if achou >= 0 else pos
        out.append(("", off))
        pos = off + 1
    # o texto de cada entrada é o trecho do bloco (já com a hifenização resolvida)
    final: list[tuple[str, int]] = []
    for i, (_, off) in enumerate(out):
        fim = out[i + 1][1] if i + 1 < len(out) else len(b.texto)
        final.append((b.texto[off:fim].strip(), off))
    return final


def classificar(doc: Documento) -> tuple[list[Item], list[tuple[str, Bloco, int]], Info]:
    """(itens do corpo, entradas de referência (texto, bloco, offset), info)."""
    info = Info(doc)
    estilos = any(b.nivel for b in doc.blocos)
    itens: list[Item] = []
    refs: list[tuple[str, Bloco, int]] = []
    estado = "pre"  # pre | corpo | resumo | sumario | lista | refs | tabela | aprovacao
    lang = "pt"
    pre: list[Bloco] = []
    tabela_restante = 0

    def pular(motivo: str) -> None:
        info.pulados[motivo] = info.pulados.get(motivo, 0) + 1

    for b in doc.blocos:
        t = b.texto.strip()
        if not t:
            continue
        if b.tabela:
            pular("tabelas")
            continue
        if b.equacao:
            pular("equações")
            continue
        if b.estilo == "sumario":
            pular("sumário")
            continue
        if _equacao(b, doc.formato):
            pular("equações")
            continue
        conhecida = _conhecida(t)
        nivel = b.nivel
        if not nivel and conhecida:
            nivel = max(1, _nivel_texto(b, doc.formato, estilos) or 1)
        elif not nivel and estado not in ("pre", "refs", "sumario", "lista"):
            nivel = _nivel_texto(b, doc.formato, estilos)
        elif not nivel and estado == "pre":
            n = _nivel_texto(b, doc.formato, estilos)
            if n and re.match(r"^\d", t):
                nivel = n  # "1 INTRODUÇÃO" encerra os elementos pré-textuais
        if estado in ("sumario", "lista") and _SUMARIO_ITEM.search(t) and len(t.split()) <= 30:
            pular("sumário")
            continue
        if estado == "refs" and nivel and not (conhecida or b.nivel):
            nivel = 0  # na lista de referências, só um título de verdade encerra a lista
        inline = _INLINE.match(t) if not nivel else None
        if b.estilo == "titulo" and estado == "pre":
            itens.append(Item("titulo", b, t))
            continue
        if nivel or inline:
            if estado == "pre":
                itens += _pre_textuais(pre, info)
                pre = []
            tipo, lang_sec = conhecida if conhecida else ("corpo", "")
            if inline:
                tipo, lang_sec = _conhecida(inline.group(1)) or ("resumo", "pt")
            lang = lang_sec or "pt"
            estado = {
                "resumo": "resumo",
                "sumario": "sumario",
                "lista_fig": "lista",
                "lista_tab": "lista",
                "lista_sig": "lista",
                "refs": "refs",
                "aprovacao": "aprovacao",
            }.get(tipo, "corpo")
            info.titulos += 1
            if tipo == "refs":
                info.secao_refs = b
            rotulo = inline.group(1) if inline else t
            itens.append(
                Item(
                    "secao",
                    b,
                    rotulo,
                    nivel=nivel or 1,
                    tipo=tipo,
                    lang=lang,
                    estrela=tipo not in ("corpo", "pos") or bool(inline),
                )
            )
            if inline:
                itens += _corpo(b, t[inline.end() :], inline.end(), lang, "resumo")
            continue
        if estado == "pre":
            pre.append(b)
            continue
        if estado in ("sumario", "lista", "aprovacao"):
            pular("sumário" if estado == "sumario" else "listas pré-textuais")
            continue
        if b.estilo == "bibliografia" and estado != "refs":  # Zotero/pandoc: sem título
            if estado == "pre":
                itens += _pre_textuais(pre, info)
                pre = []
            estado = "refs"
            info.secao_refs = b
            itens.append(Item("secao", b, "", tipo="refs", estrela=True, base=0, nivel=1))
        if estado == "refs":
            if doc.formato == "pdf":
                refs += [(x, b, off) for x, off in _dividir_referencias_pdf(b) if x]
            else:
                refs.append((t, b, 0))
            continue
        if b.estilo == "legenda" or (_LEGENDA.match(t) and len(t.split()) <= 60):
            tab = bool(re.match(r"^(Tabela|Quadro|Table)", t, re.IGNORECASE))
            itens.append(Item("legenda", b, t, tipo="table" if tab else "figure"))
            tabela_restante = 8 if tab and doc.formato == "pdf" else 0
            continue
        if _FONTE.match(t) and len(t.split()) <= 40:
            pular("fontes de figuras e tabelas")
            tabela_restante = 0
            continue
        if tabela_restante and len(t.split()) < 15 and not t.endswith("."):
            tabela_restante -= 1
            pular("tabelas")
            continue
        tabela_restante = 0
        if b.lista:
            from errei.documento.pdf import MARCADOR

            mk = MARCADOR.match(t) if doc.formato == "pdf" else None
            corte = mk.end() if mk else 0
            itens.append(Item("item", b, t[corte:], lang=lang, base=corte))
        elif b.estilo == "citacao" or b.recuado:
            itens.append(Item("citacao", b, t, lang=lang))
        else:
            itens += _corpo(b, t, 0, lang, estado)
    if estado == "pre":
        itens += _pre_textuais(pre, info)
    return itens, refs, info


def _corpo(b: Bloco, t: str, base: int, lang: str, estado: str) -> list[Item]:
    """Parágrafo do corpo; separa as palavras-chave grudadas no resumo."""
    out: list[Item] = []
    m = _KW.search(t) if estado == "resumo" else None
    partes = (
        [(t[: m.start()].rstrip(), base), (t[m.start(1) :], base + m.start(1))]
        if m
        else [(t, base)]
    )
    for texto, off in partes:
        if not texto:
            continue
        lg = lang
        if estado != "resumo" and len(texto.split()) >= 25 and lang == "pt":
            lg = "en" if _idioma(texto) == "en" else "pt"
        out.append(Item("corpo", b, texto, lang=lg, base=off))
    return out


def _pre_textuais(pre: list[Bloco], info: Info) -> list[Item]:
    """Título, autores e afiliações antes da primeira seção (e sinais de monografia)."""
    out: list[Item] = []
    curtos: list[Bloco] = []
    for b in pre:
        t = b.texto.strip()
        if _MONOGRAFIA.search(t) or _FICHA.search(t) or _APROVACAO.search(t):
            info.monografia = info.monografia or bool(_MONOGRAFIA.search(t))
            info.pulados["elementos pré-textuais"] = (
                info.pulados.get("elementos pré-textuais", 0) + 1
            )
            continue
        if len(t.split()) <= 40 and not t.endswith("."):
            curtos.append(b)
        else:
            out += _corpo(b, t, 0, "pt", "pre")
    titulo: Bloco | None = None
    candidatos = [
        b
        for b in curtos
        if not _INSTITUICAO.search(b.texto)
        and not _DATA.match(b.texto.strip())
        and "@" not in b.texto
        and len(b.texto.split()) >= 3
        and not (_NOME.match(b.texto.strip()) and len(b.texto.split()) <= 5)
    ]
    if candidatos:
        titulo = max(candidatos, key=lambda b: (len(b.texto.split()), -curtos.index(b)))
    for b in curtos:
        t = b.texto.strip()
        if b is titulo:
            out.append(Item("titulo", b, t))
        elif "@" in t or _INSTITUICAO.search(t):
            out.append(Item("afiliacao", b, t))
        elif _DATA.match(t):
            info.pulados["elementos pré-textuais"] = (
                info.pulados.get("elementos pré-textuais", 0) + 1
            )
        elif _NOME.match(t) or len(t.split()) <= 8:
            out.append(Item("autor", b, t))
        else:
            out.append(Item("corpo", b, t))
    # o título vem primeiro, mesmo quando a capa o põe depois da instituição e do autor
    out.sort(key=lambda it: it.papel != "titulo")
    return out


# ------------------------------------------------------------------ referências → .bib


def _valor(s: str) -> str:
    return " ".join(s.replace("{", "(").replace("}", ")").replace("\\", " ").split())


def _bib(
    refs: list[Referencia], blocos: list[tuple[Bloco, int]], exibir: Path, unidade: str
) -> tuple[str, Conversao]:
    conv = Conversao(exibir, unidade)
    partes: list[str] = []
    pos = 0
    for r, (b, off) in zip(refs, blocos, strict=True):
        campos: list[tuple[str, str]] = []
        if r.autores:
            nomes = [
                f"{{{_valor(s)}}}" if r.entidade or not p else f"{_valor(s)}, {_valor(p)}"
                for s, p in r.autores
            ]
            if r.et_al:
                nomes.append("others")
            campos.append(("author", " and ".join(nomes)))
        if r.titulo:
            campos.append(("title", r.titulo))
        if r.ano:
            campos.append(("year", r.ano[:4]))
        campos += sorted(r.campos.items())
        corpo = ",\n".join(f"  {k} = {{{_valor(v)}}}" for k, v in campos if v)
        entrada = f"@{r.tipo}{{{r.chave},\n{corpo}\n}}\n\n"
        t = Trecho(pos, pos + len(entrada), b, off, [(0, len(entrada), r.texto)], entrada)
        conv.trechos.append(t)
        partes.append(entrada)
        pos += len(entrada)
    conv.fechar()
    return "".join(partes), conv


# ------------------------------------------------------------------ montagem


def _pecas_citacoes(texto: str, cits: list[Citacao]) -> list[Peca]:
    out: list[Peca] = []
    pos = 0
    for c in cits:
        out += txt(texto[pos : c.inicio])
        paginas = {o.pagina for o in c.obras if o.pagina}
        if c.forma == "narr-apud":
            pag = f"[{c.obras[-1].pagina}]" if c.obras[-1].pagina else ""
            chaves = ",".join(o.chave for o in c.obras)
            if c.apud_obras:
                out.append(
                    (f"\\apudonline{pag}{{{c.apud_obras[0].chave}}}{{{chaves}}}", c.original)
                )
            else:  # "Flesch (1948 apud \citeonline{martins1996})": original fora da lista
                out += txt(c.apud_texto)
                out.append(
                    (f" apud \\citeonline{pag}{{{chaves}}})", c.original[len(c.apud_texto) :])
                )
        elif c.forma == "paren" and (c.apud_obras or c.apud_texto) and c.obras:
            pag = f"[{c.obras[-1].pagina}]" if c.obras[-1].pagina else ""
            if c.apud_obras and len(c.apud_obras) == 1 and len(c.obras) == 1:
                out.append(
                    (f"\\apud{pag}{{{c.apud_obras[0].chave}}}{{{c.obras[0].chave}}}", c.original)
                )
            else:  # original fora da lista: "(FLESCH, 1948 apud \citeonline{martins1996})"
                orig = c.apud_texto or c.original
                ini = c.original.find(orig)
                ini = ini if ini >= 0 else 1
                chaves = ",".join(o.chave for o in c.obras)
                out.append((c.original[:ini], None))
                out += txt(orig)
                out.append((f" apud \\citeonline{pag}{{{chaves}}})", c.original[ini + len(orig) :]))
        elif c.forma == "narr":
            pag = f"[{next(iter(paginas))}]" if len(paginas) == 1 else ""
            out.append((f"\\citeonline{pag}{{{','.join(o.chave for o in c.obras)}}}", c.original))
        elif len(paginas) > 1:
            out.append(
                (
                    " ".join(
                        f"\\cite[{o.pagina}]{{{o.chave}}}" if o.pagina else f"\\cite{{{o.chave}}}"
                        for o in c.obras
                    ),
                    c.original,
                )
            )
        else:
            pag = f"[{next(iter(paginas))}]" if paginas else ""
            out.append((f"\\cite{pag}{{{','.join(o.chave for o in c.obras)}}}", c.original))
        pos = c.fim
    out += txt(texto[pos:])
    return out


def converter(doc: Documento) -> tuple[str, Conversao, str, Conversao, Info]:
    itens, entradas, info = classificar(doc)
    refs: list[Referencia] = []
    origem: list[tuple[Bloco, int]] = []
    for texto, b, off in entradas:
        r = analisar(texto)
        if r.estilo == "abnt" and not r.autores and refs:  # "______. Título" (mesmo autor)
            r.autores = list(refs[-1].autores)
            r.entidade = refs[-1].entidade
        refs.append(r)
        origem.append((b, off))
    indice = Indice(refs)
    info.referencias = refs
    info.rotulos = {r.chave: r.rotulo() for r in refs}

    conv = Conversao(doc.caminho, doc.unidade)
    out = _Saida(conv)
    margens = doc.margens_cm
    opts = []
    if doc.fonte_pt:
        opts.append(f"{round(doc.fonte_pt):d}pt")
    if doc.papel in ("a4", "letter"):
        opts.append(f"{doc.papel}paper")
    classe = "report" if info.monografia else "article"
    out.linha([est(f"\\documentclass[{','.join(opts)}]{{{classe}}}")], None)
    if margens:
        geo = ",".join(f"{k}={round(v, 1):g}cm" for k, v in margens.items())
        out.linha([est(f"\\usepackage[{geo}]{{geometry}}")], None)
    for it in itens:
        if it.papel == "titulo":
            out.linha([est("\\title{"), *txt(it.texto), est("}")], it.bloco, it.base)
        elif it.papel == "autor":
            out.linha([est("\\author{"), *txt(it.texto), est("}")], it.bloco, it.base)
        elif it.papel == "afiliacao":
            out.linha([est("\\affil{"), *txt(it.texto), est("}")], it.bloco, it.base)
    out.linha([est("\\begin{document}")], None)
    cmd = (
        ["chapter", "section", "subsection", "subsubsection", "paragraph"]
        if info.monografia
        else ["section", "subsection", "subsubsection", "paragraph", "paragraph"]
    )
    aberto = ""  # otherlanguage* aberto
    n_cit = 0
    for it in itens:
        if it.papel in ("titulo", "autor", "afiliacao"):
            continue
        pecas: list[Peca] = []
        if it.papel == "secao" and aberto:
            pecas.append(est("\\end{otherlanguage*}"))
            aberto = ""
        if it.papel == "secao":
            if it.tipo == "refs":
                pecas.append(est("\\bibliography{referencias}", it.texto))
            elif it.tipo == "sumario":
                pecas.append(est("\\tableofcontents", it.texto))
            elif it.tipo == "lista_fig":
                pecas.append(est("\\listoffigures", it.texto))
            elif it.tipo == "lista_tab":
                pecas.append(est("\\listoftables", it.texto))
            else:
                if it.lang in _IDIOMA_LATEX:
                    pecas.append(est(f"\\begin{{otherlanguage*}}{{{_IDIOMA_LATEX[it.lang]}}}"))
                    aberto = it.lang
                nome = cmd[min(it.nivel, 5) - 1] + ("*" if it.estrela else "")
                num = _NUM_TITULO.match(it.texto)
                prefixo = num.group(0) if num and num.end() < len(it.texto) else ""
                pecas += [est(f"\\{nome}{{", prefixo), *txt(it.texto[len(prefixo) :]), est("}")]
            out.linha(pecas, it.bloco, it.base)
            continue
        cits = citacoes(it.texto, indice) if refs or it.papel != "legenda" else []
        n_cit += len(cits)
        corpo = _pecas_citacoes(it.texto, cits)
        if it.papel == "item":
            corpo = [est("\\begin{itemize}\\item "), *corpo, est("\\end{itemize}")]
        elif it.papel == "citacao":
            corpo = [est("\\begin{citacao}"), *corpo, est("\\end{citacao}")]
        elif it.papel == "legenda":
            corpo = [est(f"\\begin{{{it.tipo}}}\\caption{{"), *corpo, est(f"}}\\end{{{it.tipo}}}")]
        if it.lang in _IDIOMA_LATEX and not aberto:
            corpo = [
                est(f"\\begin{{otherlanguage*}}{{{_IDIOMA_LATEX[it.lang]}}}"),
                *corpo,
                est("\\end{otherlanguage*}"),
            ]
        out.linha(corpo, it.bloco, it.base)
    out.linha([est("\\end{otherlanguage*}" if aberto else ""), est("\\end{document}")], None)
    info.citacoes = n_cit
    info.sem_referencia = dict(indice.novas)
    tex = out.texto()
    bib, bconv = _bib(refs, origem, doc.caminho, doc.unidade)
    return tex, conv, bib, bconv, info
