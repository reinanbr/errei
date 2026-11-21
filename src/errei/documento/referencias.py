"""Referências digitadas e citações no texto de um ``.docx``/``.pdf``.

As referências da lista (NBR 6023, APA, Vancouver/IEEE e autor-data) viram entradas
bibliográficas com autor, título, ano, DOI, URL e periódico, o bastante para conferir nas
bases abertas. As citações no texto (NBR 10520: "(SILVA, 2020)", "Silva (2020)",
"(SILVA; SOUZA, 2020, p. 12)", "(FLESCH, 1948 apud MARTINS, 1996)" e numéricas "[1, 3–5]")
são ligadas às referências pelo sobrenome do primeiro autor e pelo ano (ou pelo número).

É heurística: a lista é texto livre. O que não é reconhecido fica como texto e é contado no
relatório (DOC-REF-001).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

ANO = r"(?:1[5-9]|20)\d\d"
_ANO_RE = re.compile(rf"(?<![\d/.])({ANO})([a-z])?(?![\d])")
_DOI_RE = re.compile(
    r"(?:https?://(?:dx\.)?doi\.org/|\bdoi:?\s*)?(10\.\d{4,9}/[^\s<>\"“”]+)", re.IGNORECASE
)
_URL_RE = re.compile(r"<?(https?://[^\s<>\"“”]+)>?", re.IGNORECASE)
_ACESSO_RE = re.compile(
    r"Acess(?:o|ado)\s+em:?\s*(\d{1,2}\s+[A-Za-zçÇ]{3,9}\.?\s+\d{4}|[^.]{3,40})", re.IGNORECASE
)
_ISBN_RE = re.compile(r"ISBN:?\s*([\dXx][\dXx\s-]{8,16}[\dXx])")
_NUMERO_RE = re.compile(r"^\s*(?:\[(\d{1,4})\]|(\d{1,4})[.)])\s+")
# fim do "corpo" da referência: daqui em diante só há localizadores
_CAUDA_RE = re.compile(r"\b(?:Dispon[ií]vel\s+em|Available\s+(?:at|from)|DOI\b|doi:|https?://)")

_UP = "A-ZÀ-ÖØ-Ý"
_LO = "a-zß-öø-ÿ"
SOBRENOME = (
    rf"[{_UP}][{_UP}'’\-]+(?:\s+(?:D[AEO]S?|DE|DI|DU|VAN|VON|DEL|LA|LE|[{_UP}][{_UP}'’\-]+))*"
)
_FULL = rf"(?:[{_UP}][{_LO}'’]+(?:-[{_UP}]?[{_LO}'’]+)?|d[aeo]s?|de|e)"
_INIT = rf"[{_UP}]\.(?:\s?-?\s?[{_UP}]\.)*"
PRENOMES = rf"(?:{_FULL}(?:\s+{_FULL})*(?:\s+{_INIT})?|{_INIT})"
_AUTOR_ABNT = rf"{SOBRENOME},\s*{PRENOMES}"
_BLOCO_ABNT = re.compile(
    rf"^(?P<a>{_AUTOR_ABNT}(?:\s*;\s*{_AUTOR_ABNT})*)(?P<etal>\s+et\s+al\.?)?"
    rf"(?:\.?\s+|(?<=\.)(?=[{_UP}]))"
)
# órgão subordinado de uma entidade: "BRASIL. Ministério da Saúde. Título"
_ORGAO = re.compile(
    r"^(?:Minist[eé]rio|Secretaria|Instituto|Conselho|Departamento|Ag[eê]ncia|Funda[cç][aã]o|"
    r"C[aâ]mara|Senado|Presid[eê]ncia|Tribunal|Coordena[cç][aã]o|Comiss[aã]o|Diretoria)\b"
    r"[^.]{0,80}\.\s+"
)
_ENTIDADE = re.compile(rf"^(?P<a>[{_UP}][{_UP}\s\-]{{2,60}}?)\.\s+(?=[{_UP}])")
_APA = re.compile(
    rf"^(?P<a>[^()]+?)\s*\((?P<y>{ANO}[a-z]?|s\.\s?d\.|n\.\s?d\.)(?:,[^)]*)?\)\.?\s*(?P<r>.+)$"
)
_AUTORDATA = re.compile(rf"^(?P<a>[^“\"()]+?)\.\s+(?P<y>{ANO}[a-z]?)\.\s+(?P<r>.+)$")
_VANCOUVER = re.compile(
    rf"^(?P<a>[{_UP}][\w'’\-]+(?:\s[{_UP}][\w'’\-]+)*\s[{_UP}]{{1,4}}"
    rf"(?:,\s*[{_UP}][\w'’\-]+(?:\s[{_UP}][\w'’\-]+)*\s[{_UP}]{{1,4}})*(?:,?\s+et\s+al)?)\.\s+(?P<r>.+)$"
)
_IEEE = re.compile(r"^(?P<a>[^“\"]+?),\s+[“\"](?P<t>[^”\"]{4,}?)[,.]?[”\"]\s*,?\s*(?P<r>.*)$")
# fim do título: ponto/interrogação seguido de espaço, ou ponto colado na palavra seguinte
_FIM_TITULO = re.compile(rf"(?<![{_UP}])[.?!](?=\s|$)|(?<=[{_LO}])\.(?=[{_UP}][{_LO}])")
_TESE = re.compile(
    r"(Tese|Disserta[cç][aã]o|Trabalho de Conclus[aã]o de Curso|Monografia)\s*\(([^)]*)\)",
    re.IGNORECASE,
)
_EVENTO = re.compile(
    r"\b(Anais|Proceedings|Congresso|Simp[oó]sio|Conference|Encontro|Semin[aá]rio|Workshop|"
    r"Symposium|Jornada)\b",
    re.IGNORECASE,
)
_EDITORA = re.compile(rf"(?P<l>[{_UP}][\w .\-]{{1,40}}):\s*(?P<p>[^,.:]{{2,60}}),\s*(?:c|\[)?{ANO}")


def fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    return re.sub(r"[^a-z0-9 ]", "", "".join(c for c in s if not unicodedata.combining(c)))


def _titulo_caso(s: str) -> str:
    """'PEREIRA DA SILVA' → 'Pereira da Silva'."""
    out = []
    for w in s.split():
        if w.isupper() and len(w) > 1:
            low = w.lower()
            w = (
                low
                if low in ("da", "de", "do", "das", "dos", "e", "van", "von", "del")
                else ("-".join(p.capitalize() for p in low.split("-")))
            )
        out.append(w)
    return " ".join(out)


@dataclass(slots=True)
class Referencia:
    texto: str
    numero: int | None = None
    autores: list[tuple[str, str]] = field(default_factory=list)  # (sobrenome, prenomes)
    entidade: bool = False
    et_al: bool = False
    titulo: str = ""
    ano: str = ""  # "2020" ou "2020a"
    tipo: str = "misc"
    campos: dict[str, str] = field(default_factory=dict)
    chave: str = ""
    estilo: str = ""  # abnt | apa | autor-data | vancouver | ieee | ?

    @property
    def sobrenome(self) -> str:
        return self.autores[0][0] if self.autores else ""

    @property
    def reconhecida(self) -> bool:
        return bool(self.autores and self.titulo and self.ano)

    def rotulo(self) -> str:
        """Como a obra aparece citada: 'SILVA, 2020' / 'SILVA et al., 2020'."""
        if not self.autores:
            return self.titulo[:60] or self.texto[:60]
        nomes = [s.upper() for s, _ in self.autores]
        who = f"{nomes[0]} et al." if len(nomes) > 3 or self.et_al else "; ".join(nomes)
        return f"{who}, {self.ano or 's.d.'}"


def _limpa(s: str) -> str:
    return " ".join(s.strip().strip(".,;:").split())


def _autores_lista(a: str, ordem: str) -> list[tuple[str, str]]:
    """Autores de APA ('Silva, J. A., & Souza, M.'), autor-data do Chicago ('Devlin, Jacob,
    Ming-Wei Chang, and Kenton Lee': só o primeiro invertido) ou IEEE ('J. Silva, M. Souza')."""
    a = re.sub(r"\s+et\s+al\.?", "", a)
    partes = [p.strip() for p in re.split(r",\s*(?:&|and|e)?\s*|\s+(?:&|and|e)\s+", a)]
    partes = [p for p in partes if p]
    out: list[tuple[str, str]] = []
    if ordem == "apa":
        i = 0
        while i < len(partes):
            sob, pren = partes[i], ""
            if i + 1 < len(partes) and re.fullmatch(rf"(?:{_INIT}\s*)+", partes[i + 1]):
                pren = partes[i + 1]
                i += 1
            out.append((sob, pren))
            i += 1
        return out
    if ordem == "chicago" and partes:
        out.append((partes[0], partes[1] if len(partes) > 1 else ""))
        partes = partes[2:]
    for p in partes:
        ws = p.split()
        if ws:
            out.append((ws[-1], " ".join(ws[:-1])))
    return out


def _titulo_e_resto(r: str) -> tuple[str, str]:
    r = r.strip()
    q = re.match(r"^[“\"]([^”\"]{3,}?)[.,]?[”\"]\.?\s*(.*)$", r)
    if q:
        return _limpa(q.group(1)), q.group(2)
    m = _FIM_TITULO.search(r)
    if not m:
        return _limpa(r), ""
    return _limpa(r[: m.start()]), r[m.end() :].strip()


def _fonte(ref: Referencia, resto: str, completo: str) -> None:
    """Periódico, livro, capítulo ou trabalho acadêmico a partir do que vem após o título."""
    c = ref.campos
    m = re.search(r"\bv(?:ol)?\.\s*(\d+)", completo)
    if m:
        c["volume"] = m.group(1)
    m = re.search(r"\bn(?:\.|º|°|úm\.)\s*(\d+)", completo)
    if m:
        c["number"] = m.group(1)
    m = re.search(r"\bpp?\.\s*(\d+)\s*[-–]\s*(\d+)", completo)
    if m:
        c["pages"] = f"{m.group(1)}--{m.group(2)}"
    apa = re.search(r"\b(\d+)\s*\((\d+)\),\s*(\d+)\s*[-–]\s*(\d+)", resto)
    van = re.search(r";\s*(\d+)\s*(?:\((\d+)\))?\s*:\s*(\d+)\s*[-–]?\s*(\d*)", resto)
    for mm in (apa, van):
        if mm:
            c.setdefault("volume", mm.group(1))
            if mm.group(2):
                c.setdefault("number", mm.group(2))
            if mm.group(4):
                c.setdefault("pages", f"{mm.group(3)}--{mm.group(4)}")
            break
    tese = _TESE.search(completo)
    em = re.match(r"^(?:In|Em)(?::\s*|\s+)(.*)$", resto, re.IGNORECASE)
    if tese:
        grau = tese.group(2).lower()
        ref.tipo = (
            "phdthesis"
            if "doutor" in grau or "tese" in tese.group(1).lower()
            else ("mastersthesis" if "mestr" in grau else "misc")
        )
        depois = completo[tese.end() :]
        inst = re.match(r"\s*[–—-]\s*([^,]+)", depois)
        if inst:
            c["school"] = _limpa(inst.group(1))
        return
    if em:
        corpo = re.sub(r"^.*?\((?:Orgs?|Eds?|Coords?|Org|Ed)\.?\)\.?\s*", "", em.group(1))
        livro, _ = _titulo_e_resto(corpo)
        c["booktitle"] = livro
        ref.tipo = "inproceedings" if _EVENTO.search(livro) else "incollection"
        return
    jm = re.match(r"^([^,;]{3,150}?),\s*(?:v\.|vol\.|n\.|p\.|\d+\s*\()", resto) or re.match(
        rf"^([^.;]{{3,150}}?)\.\s*{ANO}\s*;", resto
    )
    if jm or "volume" in c:
        if jm:
            c["journal"] = _limpa(jm.group(1))
        ref.tipo = "article"
        return
    ed = _EDITORA.search(resto)
    if ed:
        c["address"] = _limpa(ed.group("l"))
        c["publisher"] = _limpa(ed.group("p"))
        ref.tipo = "book"


def analisar(texto: str) -> Referencia:
    t = " ".join(texto.split())
    ref = Referencia(t)
    m = _NUMERO_RE.match(t)
    if m:
        ref.numero = int(m.group(1) or m.group(2))
        t = t[m.end() :]
    c = ref.campos
    doi = _DOI_RE.search(t)
    if doi:
        c["doi"] = doi.group(1).rstrip(".,;)]>").lower()
    for u in _URL_RE.finditer(t):
        url = u.group(1).rstrip(".,;)]>")
        if "doi.org/" not in url.lower():
            c["url"] = url
            break
    ac = _ACESSO_RE.search(t)
    if ac and ("url" in c or "doi" in c):
        c["urlaccessdate"] = _limpa(ac.group(1))
    isbn = _ISBN_RE.search(t)
    if isbn:
        c["isbn"] = isbn.group(1).replace(" ", "")
    cauda = _CAUDA_RE.search(t)
    corpo = t[: cauda.start()] if cauda else t

    resto = ""
    if t.startswith(("___", "——", "—")):  # NBR 6023: autor repetido (o chamador completa)
        ref.estilo = "abnt"
        ref.titulo, resto = _titulo_e_resto(re.sub(r"^[_—\s]+\.?\s*", "", corpo))
    elif m_apa := _APA.match(corpo):
        ref.estilo = "apa"
        ref.autores = _autores_lista(m_apa.group("a"), "apa")
        ref.et_al = "et al" in m_apa.group("a")
        y = m_apa.group("y")
        ref.ano = y if y[:1].isdigit() else ""
        ref.titulo, resto = _titulo_e_resto(m_apa.group("r"))
    elif m_abnt := _BLOCO_ABNT.match(corpo):
        ref.estilo = "abnt"
        for a in re.split(r"\s*;\s*", m_abnt.group("a")):
            sob, _, pren = a.partition(",")
            ref.autores.append((_titulo_caso(sob.strip()), pren.strip()))
        ref.et_al = bool(m_abnt.group("etal"))
        ref.titulo, resto = _titulo_e_resto(corpo[m_abnt.end() :])
    elif m_ad := _AUTORDATA.match(corpo):
        ref.estilo = "autor-data"
        ref.autores = _autores_lista(m_ad.group("a"), "chicago")
        ref.et_al = "et al" in m_ad.group("a")
        ref.ano = m_ad.group("y")
        ref.titulo, resto = _titulo_e_resto(m_ad.group("r"))
    elif m_ieee := _IEEE.match(corpo):
        ref.estilo = "ieee"
        ref.autores = _autores_lista(m_ieee.group("a"), "prenome-primeiro")
        ref.titulo, resto = _limpa(m_ieee.group("t")), m_ieee.group("r")
    elif m_van := _VANCOUVER.match(corpo):
        ref.estilo = "vancouver"
        for a in re.split(r",\s*", re.sub(r",?\s+et\s+al$", "", m_van.group("a"))):
            ws = a.split()
            ref.autores.append((" ".join(ws[:-1]), ws[-1]))
        ref.et_al = "et al" in m_van.group("a")
        ref.titulo, resto = _titulo_e_resto(m_van.group("r"))
    elif m_ent := _ENTIDADE.match(corpo):
        ref.estilo = "abnt"
        ref.entidade = True
        ref.autores = [(_titulo_caso(m_ent.group("a").strip()), "")]
        depois = corpo[m_ent.end() :]
        while (orgao := _ORGAO.match(depois)) is not None:
            depois = depois[orgao.end() :]
        ref.titulo, resto = _titulo_e_resto(depois)
    else:
        ref.estilo = "?"
        partes = [p for p in re.split(r"\.\s+", corpo) if p.strip()]
        if len(partes) >= 2:
            primeiro = partes[0].split(",")[0].strip()
            if primeiro:
                ref.autores = [(_titulo_caso(primeiro), "")]
            ref.titulo = _limpa(partes[1])
            resto = ". ".join(partes[2:])
    if not ref.ano:
        # NBR 6023/Vancouver/IEEE: o ano é o último da parte descritiva (antes de DOI/URL)
        anos = [(y.group(1) + (y.group(2) or "")) for y in _ANO_RE.finditer(corpo)]
        if anos:
            ref.ano = anos[-1]
    _fonte(ref, resto, corpo)
    for k in ("journal", "booktitle", "address", "publisher", "school"):
        if k in c and len(c[k]) > 200:
            del c[k]
    return ref


# ---------------------------------------------------------------- chaves e índice
def _slug(s: str) -> str:
    w = fold(s).split()
    return (w[-1] if w else "ref")[:20] or "ref"


class Indice:
    """Liga 'SILVA, 2020' (ou o número) à referência da lista."""

    def __init__(self, refs: list[Referencia]) -> None:
        self.refs = refs
        self.por_numero = {r.numero: r for r in refs if r.numero is not None}
        self.numerada = len(self.por_numero) >= max(2, len(refs) // 2)
        usados: set[str] = set()
        for r in refs:
            base = _slug(r.sobrenome) + (r.ano or "sd")
            if self.numerada and r.numero is not None and not r.sobrenome:
                base = f"ref{r.numero}"
            chave = base
            letra = ord("a")
            while chave in usados:
                chave = f"{base}{chr(letra)}"
                letra += 1
            r.chave = chave
            usados.add(chave)
        self.usados = usados
        self.novas: dict[str, str] = {}  # chave inventada -> texto citado (sem referência)

    @staticmethod
    def _formas(sobrenome: str) -> set[str]:
        f = fold(sobrenome).split()
        if not f:
            return set()
        return {" ".join(f), f[-1], f[0]}

    def achar(self, autores: list[str], ano: str) -> Referencia | None:
        if not autores:
            return None
        alvo = self._formas(autores[0])
        cands = [r for r in self.refs if r.ano == ano and alvo & self._formas(r.sobrenome)]
        if not cands and ano[-1:].isalpha():
            cands = [r for r in self.refs if r.ano == ano[:-1] and alvo & self._formas(r.sobrenome)]
        if not cands:
            cands = [
                r
                for r in self.refs
                if r.ano[:4] == ano[:4] and alvo & self._formas(r.sobrenome) and ano[-1:].isdigit()
            ]
        if len(cands) > 1 and len(autores) > 1:
            seg = self._formas(autores[1])
            melhor = [
                r for r in cands if len(r.autores) > 1 and seg & self._formas(r.autores[1][0])
            ]
            cands = melhor or cands
        return cands[0] if cands else None

    def chave_nova(self, autor: str, ano: str, texto: str) -> str:
        chave = _slug(autor) + ano
        if chave in self.usados and chave not in self.novas:
            chave += "x"
        self.novas.setdefault(chave, texto)
        return chave


# ---------------------------------------------------------------- citações no texto
@dataclass(slots=True)
class Obra:
    chave: str
    pagina: str = ""
    conhecida: bool = True


@dataclass(slots=True)
class Citacao:
    inicio: int
    fim: int
    forma: str  # paren | narr | narr-apud | num
    obras: list[Obra]
    original: str
    # "(FLESCH, 1948 apud MARTINS, 1996)": a original, quando não está na lista
    apud_texto: str = ""
    apud_obras: list[Obra] = field(default_factory=list)


_NOME = rf"[{_UP}][\w'’\-]*\.?"
_PART = r"(?:d[aeo]s?|de|di|van|von|del)"
_UM = rf"{_NOME}(?:\s+(?:{_PART}|{_NOME}))*"
# "SILVA", "Silva et al.", "Silva & Souza", "LeCun, Bengio, and Hinton" (autor-data/APA)
AUTOR_TXT = re.compile(rf"^{_UM}(?:(?:,\s*|\s+)(?:(?:&|e|and)\s+)?{_UM})*(?:,?\s+et\s+al\.?)?$")
_ITEM = re.compile(
    rf"^(?P<a>.+?)(?:,\s*|\s+)(?P<anos>\[?{ANO}[a-z]?\]?(?:\s*,\s*\[?{ANO}[a-z]?\]?)*)"
    r"(?:\s*,\s*(?P<p>(?:p|pp|f|fl|cap|v|t|s)\.\s*[\w\s,.–-]{1,30}))?$"
)
_PAREN = re.compile(r"\(([^()]{3,400})\)")
_NARR = re.compile(
    rf"(?P<a>[{_UP}][\w'’\-]+(?:\s+{_PART}\s+[{_UP}][\w'’\-]+)*"
    rf"(?:\s+et\s+al\.?|(?:,\s*[{_UP}][\w'’\-]+)*\s+(?:e|and|&)\s+[{_UP}][\w'’\-]+)?)"
    rf"\s*\((?P<anos>{ANO}[a-z]?(?:\s*,\s*{ANO}[a-z]?)*)(?:,\s*(?P<p>p\.\s*[\d\s–-]+))?\)"
)
_NUM = re.compile(r"\[(\d{1,4}(?:\s*[-–,]\s*\d{1,4})*)\]")
# "Flesch (1948 apud MARTINS et al., 1996)": original narrativa, consultada entre parênteses
_NARR_APUD = re.compile(
    rf"(?P<a>[{_UP}][\w'’\-]+(?:\s+et\s+al\.?)?)\s*\((?P<ano>{ANO}[a-z]?)"
    r"\s+(?:apud|citad[oa]s?\s+por)\s+(?P<c>[^()]{3,200})\)",
    re.IGNORECASE,
)
_APUD_SEP = re.compile(r"\s+(?:apud|citad[oa]s?\s+por)\s+", re.IGNORECASE)
_APUD_DEPOIS = re.compile(r"^\s*(?:apud|citad[oa]s?\s+por)\b", re.IGNORECASE)
NAO_AUTOR = {
    "figura", "tabela", "quadro", "grafico", "lei", "decreto", "resolucao", "portaria",
    "norma", "equacao", "secao", "capitulo", "anexo", "apendice", "ano", "artigo", "item",
    "fase", "etapa", "grupo", "periodo", "nota", "volume", "parte", "edicao", "em", "no",
    "na", "de", "do", "da", "entre", "desde", "ate", "apos", "durante", "segundo",
}  # fmt: skip


def _autores_cit(a: str) -> list[str] | None:
    a = re.sub(r",?\s+et\s+al\.?$", "", a.strip())
    nomes = [x.strip() for x in re.split(r",?\s+(?:&|e|and)\s+|,\s*", a) if x.strip()]
    return nomes or None


def _paren(conteudo: str, indice: Indice) -> tuple[list[Obra], list[Obra], str] | None:
    """Obras de '(SILVA; SOUZA, 2020; LIMA, 2019, p. 3)'; com apud, (consultadas, originais,
    texto da original). ``None`` se o parêntese não for só citação."""
    partes = _APUD_SEP.split(conteudo, maxsplit=1)
    grupos: list[list[tuple[list[str], str, str]]] = []
    for parte in partes:
        works: list[tuple[list[str], str, str]] = []
        pend: list[str] = []
        for it in (x.strip() for x in parte.split(";")):
            m = _ITEM.match(it)
            if m:
                a = m.group("a").strip()
                if not AUTOR_TXT.match(a):
                    return None
                nomes = pend + (_autores_cit(a) or [])
                pend = []
                for y in re.findall(rf"{ANO}[a-z]?", m.group("anos")):
                    works.append((nomes, y, (m.group("p") or "").strip()))
            elif it and AUTOR_TXT.match(it):
                pend.append(it)
            else:
                return None
        if pend or not works:
            return None
        grupos.append(works)

    def ligar(works: list[tuple[list[str], str, str]], inventar: bool) -> list[Obra]:
        out: list[Obra] = []
        for nomes, ano, pag in works:
            if fold(nomes[0]) in NAO_AUTOR:
                raise ValueError
            r = indice.achar(nomes, ano)
            if r is not None:
                out.append(Obra(r.chave, pag))
            elif inventar:
                txt = f"{nomes[0].upper()}{' et al.' if len(nomes) > 3 else ''}, {ano}"
                out.append(Obra(indice.chave_nova(nomes[0], ano, txt), pag, conhecida=False))
        return out

    try:
        if len(grupos) == 1:
            return ligar(grupos[0], True), [], ""
        originais = ligar(grupos[0], False)
        consultadas = ligar(grupos[1], True)
    except ValueError:
        return None
    if len(originais) < len(grupos[0]):
        return consultadas, [], partes[0].strip()
    return consultadas, originais, ""


def citacoes(texto: str, indice: Indice) -> list[Citacao]:
    """Citações reconhecidas no texto de um parágrafo, em ordem e sem sobreposição."""
    out: list[Citacao] = []
    ocupado: list[tuple[int, int]] = []

    def livre(a: int, b: int) -> bool:
        return all(b <= x or a >= y for x, y in ocupado)

    for m in _NARR_APUD.finditer(texto):
        cons = _paren(m.group("c"), indice)
        if cons is None or not cons[0]:
            continue
        nomes = _autores_cit(m.group("a")) or []
        r = indice.achar(nomes, m.group("ano")) if nomes else None
        c = Citacao(m.start(), m.end(), "narr-apud", cons[0], m.group(0))
        if r is not None:
            c.apud_obras = [Obra(r.chave)]
        else:
            c.apud_texto = texto[m.start() : m.start("ano") + len(m.group("ano"))]
        out.append(c)
        ocupado.append((m.start(), m.end()))
    for m in _PAREN.finditer(texto):
        if not livre(m.start(), m.end()):
            continue
        res = _paren(m.group(1), indice)
        if res is None:
            continue
        lidas, originais, orig_txt = res
        c = Citacao(m.start(), m.end(), "paren", lidas, m.group(0))
        if orig_txt:
            c.apud_texto = orig_txt
        c.apud_obras = originais
        out.append(c)
        ocupado.append((m.start(), m.end()))
    for m in _NARR.finditer(texto):
        if not livre(m.start(), m.end()):
            continue
        nomes = _autores_cit(m.group("a")) or []
        if not nomes or fold(nomes[0]) in NAO_AUTOR:
            continue
        pag = (m.group("p") or "").strip()
        obras: list[Obra] = []
        desconhecida = False
        for ano in re.findall(rf"{ANO}[a-z]?", m.group("anos")):
            r = indice.achar(nomes, ano)
            if r is not None:
                obras.append(Obra(r.chave, pag))
            else:
                desconhecida = True
                txt = f"{nomes[0]} ({ano})"
                obras.append(Obra(indice.chave_nova(nomes[0], ano, txt), pag, conhecida=False))
        # original de um apud fora da lista ("Flesch (1948) apud ..."): continua texto
        if desconhecida and _APUD_DEPOIS.match(texto[m.end() :]):
            continue
        if desconhecida and not indice.refs:
            continue
        out.append(Citacao(m.start(), m.end(), "narr", obras, m.group(0)))
        ocupado.append((m.start(), m.end()))
    if indice.numerada:
        for m in _NUM.finditer(texto):
            if not livre(m.start(), m.end()):
                continue
            nums: list[int] = []
            for parte in re.split(r"\s*,\s*", m.group(1)):
                a, _, b = parte.replace("–", "-").partition("-")
                ini = int(a.strip())
                fim = int(b.strip()) if b.strip() else ini
                if fim - ini > 50:
                    break
                nums += list(range(ini, fim + 1))
            # "[9]" numa lista de 3 é citação sem referência; "[0, 500]" não é citação
            if not nums or len(nums) != len(set(nums)):
                continue
            if any(not 1 <= n <= len(indice.refs) + 20 for n in nums):
                continue
            obras = []
            for n in nums:
                r = indice.por_numero.get(n)
                if r is not None:
                    obras.append(Obra(r.chave))
                else:
                    obras.append(Obra(indice.chave_nova("ref", str(n), f"[{n}]"), conhecida=False))
            out.append(Citacao(m.start(), m.end(), "num", obras, m.group(0)))
            ocupado.append((m.start(), m.end()))
    out.sort(key=lambda c: c.inicio)
    return out
