"""Leitura de ``.docx`` (Office Open XML) só com a biblioteca padrão.

O arquivo é entrada não confiável: só o XML do corpo, dos estilos e dos metadados é lido,
com limite de tamanho descompactado (zip bomb) e sem DTD/entidades. Macros, vínculos
externos e objetos embutidos não são abertos.

Não são analisados (e o relatório diz quantos havia): notas de rodapé, caixas de texto,
tabelas, equações, comentários e o texto apagado em alterações controladas (o texto
inserido é lido como se as alterações fossem aceitas).
"""

from __future__ import annotations

import contextlib
import io
import re
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from errei.documento.modelo import Bloco, Documento, DocumentoError, ler_bytes, sha256

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
M = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"
DC = "{http://purl.org/dc/elements/1.1/}"
MAX_XML = 60 * 1024 * 1024  # descompactado
TWIP_CM = 1440 / 2.54
# recuo esquerdo a partir do qual o parágrafo é tratado como citação longa (NBR 10520: 4 cm)
RECUO_CITACAO_CM = 3.0

_NIVEL = re.compile(r"^(?:heading|titulo|ttulo|uberschrift|titre|encabezado)\s*(\d)$")
_PULAR = {
    W + "txbxContent",  # caixas de texto
    W + "delText",
    W + "instrText",  # código dos campos (ex.: ADDIN ZOTERO_ITEM ...); o resultado é lido
    W + "footnoteReference",
    W + "endnoteReference",
    W + "commentReference",
    W + "pPr",
    W + "rPr",
    W + "fldData",
}


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    return " ".join("".join(c for c in s if not unicodedata.combining(c)).split())


def _ler(z: zipfile.ZipFile, nome: str) -> bytes | None:
    try:
        info = z.getinfo(nome)
    except KeyError:
        return None
    if info.file_size > MAX_XML:
        raise DocumentoError(f"{nome} descompactado passa de {MAX_XML // 1024 // 1024} MB")
    with z.open(info) as fh:
        data = fh.read(MAX_XML + 1)
    if len(data) > MAX_XML:
        raise DocumentoError(f"{nome} descompactado passa de {MAX_XML // 1024 // 1024} MB")
    return data


def _xml(data: bytes, nome: str) -> ET.Element:
    if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        raise DocumentoError(f"{nome}: XML com DTD/entidades (não é um .docx comum)")
    try:
        return ET.fromstring(data)
    except ET.ParseError as exc:
        raise DocumentoError(f"{nome}: XML inválido ({exc})") from exc


def _val(el: ET.Element | None, attr: str = "val") -> str | None:
    if el is None:
        return None
    return el.get(W + attr)


def _on(el: ET.Element | None) -> bool | None:
    """Propriedade liga/desliga do Word (``<w:b/>``, ``<w:b w:val="0"/>``)."""
    if el is None:
        return None
    return _val(el) not in ("0", "false", "off")


@dataclass(slots=True)
class _Estilo:
    papel: str = ""  # titulo, subtitulo, legenda, citacao, sumario, lista, bibliografia
    nivel: int | None = None
    base: str = ""
    centro: bool | None = None
    recuo_cm: float | None = None
    negrito: bool | None = None
    tamanho: float | None = None
    lista: bool | None = None


def _papel(nome: str) -> tuple[str, int | None]:
    n = _fold(nome)
    m = _NIVEL.match(n)
    if m:
        return "", int(m.group(1))
    if n in ("title", "titulo"):
        return "titulo", None
    if n in ("subtitle", "subtitulo"):
        return "subtitulo", None
    if n in ("caption", "legenda"):
        return "legenda", None
    if "quote" in n or "citac" in n or n == "block text":
        return "citacao", None
    if re.match(r"^(toc|sumario|indice)\s*\d", n) or n in (
        "table of figures",
        "indice de ilustracoes",
    ):
        return "sumario", None
    if n in ("toc heading", "cabecalho do sumario", "titulo do sumario"):
        return "", 1
    if n.startswith(("list ", "paragrafo da lista", "lista ")):
        return "lista", None
    if n in ("bibliography", "bibliografia", "referencias", "referencia"):
        return "bibliografia", None
    return "", None


def _ppr(ppr: ET.Element | None, st: _Estilo) -> None:
    if ppr is None:
        return
    lvl = _val(ppr.find(W + "outlineLvl"))
    if lvl is not None and lvl.isdigit():
        st.nivel = int(lvl) + 1 if int(lvl) < 9 else 0
    jc = _val(ppr.find(W + "jc"))
    if jc is not None:
        st.centro = jc == "center"
    ind = ppr.find(W + "ind")
    if ind is not None:
        left = ind.get(W + "left") or ind.get(W + "start")
        if left is not None:
            with contextlib.suppress(ValueError):
                st.recuo_cm = int(left) / TWIP_CM
    if ppr.find(W + "numPr") is not None:
        st.lista = True


def _rpr(rpr: ET.Element | None, st: _Estilo) -> None:
    if rpr is None:
        return
    b = _on(rpr.find(W + "b"))
    if b is not None:
        st.negrito = b
    sz = _val(rpr.find(W + "sz"))
    if sz and sz.isdigit():
        st.tamanho = int(sz) / 2


def _estilos(root: ET.Element | None) -> tuple[dict[str, _Estilo], str, float | None]:
    """Estilos de parágrafo por id, o id do estilo padrão e o tamanho de fonte padrão."""
    out: dict[str, _Estilo] = {}
    padrao = ""
    tamanho: float | None = None
    if root is None:
        return out, padrao, tamanho
    dd = root.find(f"{W}docDefaults/{W}rPrDefault/{W}rPr")
    if dd is not None:
        tmp = _Estilo()
        _rpr(dd, tmp)
        tamanho = tmp.tamanho
    for s in root.findall(W + "style"):
        if s.get(W + "type") not in ("paragraph", None):
            continue
        sid = s.get(W + "styleId") or ""
        nome = _val(s.find(W + "name")) or sid
        papel, nivel = _papel(nome)
        st = _Estilo(papel=papel, nivel=nivel, base=_val(s.find(W + "basedOn")) or "")
        nivel_nome = st.nivel
        _ppr(s.find(W + "pPr"), st)
        if nivel_nome is not None:
            st.nivel = nivel_nome  # "Heading 2" vale mais que o outlineLvl herdado
        _rpr(s.find(W + "rPr"), st)
        if s.get(W + "default") in ("1", "true"):
            padrao = sid
        out[sid] = st
    return out, padrao, tamanho


def _herdar(estilos: dict[str, _Estilo], sid: str, attr: str) -> object:
    seen: set[str] = set()
    while sid and sid not in seen and sid in estilos:
        seen.add(sid)
        v = getattr(estilos[sid], attr)
        if v not in (None, ""):
            return v
        sid = estilos[sid].base
    return None


def _paragrafos(cont: ET.Element, tabela: bool = False) -> Iterator[tuple[ET.Element, bool, str]]:
    """Parágrafos na ordem de leitura: (w:p, dentro de tabela?, papel do bloco sdt)."""
    for ch in cont:
        if ch.tag == W + "p":
            yield ch, tabela, ""
        elif ch.tag == W + "tbl":
            for tr in ch.findall(W + "tr"):
                for tc in tr.findall(W + "tc"):
                    yield from _paragrafos(tc, True)
        elif ch.tag == W + "sdt":
            gal = ch.find(f"{W}sdtPr/{W}docPartObj/{W}docPartGallery")
            kind = "sumario" if gal is not None and "content" in (_val(gal) or "").lower() else ""
            content = ch.find(W + "sdtContent")
            if content is not None:
                for p, t, k in _paragrafos(content, tabela):
                    yield p, t, kind or k
        elif ch.tag in (W + "customXml", W + "smartTag", W + "ins"):
            yield from _paragrafos(ch, tabela)


@dataclass(slots=True)
class _Texto:
    texto: str
    matematica: bool  # tem equação
    so_matematica: bool
    negrito: bool  # todo o texto em negrito
    quebra: bool  # quebra de página no parágrafo


def _texto(p: ET.Element, negrito_estilo: bool) -> _Texto:
    parts: list[str] = []
    mat = False
    quebra = False
    runs_texto = 0
    runs_negrito = 0

    def run_negrito(r: ET.Element) -> bool:
        b = _on(r.find(f"{W}rPr/{W}b"))
        return negrito_estilo if b is None else b

    def walk(el: ET.Element) -> None:
        nonlocal mat, quebra, runs_texto, runs_negrito
        for ch in el:
            tag = ch.tag
            if tag in _PULAR:
                continue
            if tag == W + "r":
                if _on(ch.find(f"{W}rPr/{W}vanish")):
                    continue  # texto oculto
                antes = len(parts)
                walk(ch)
                if "".join(parts[antes:]).strip():
                    runs_texto += 1
                    runs_negrito += run_negrito(ch)
            elif tag == W + "t":
                parts.append(ch.text or "")
            elif tag == W + "tab":
                parts.append("\t")
            elif tag in (W + "br", W + "cr"):
                if ch.get(W + "type") == "page":
                    quebra = True
                parts.append(" ")
            elif tag == W + "lastRenderedPageBreak":
                quebra = True
            elif tag == W + "noBreakHyphen":
                parts.append("-")
            elif tag in (M + "oMath", M + "oMathPara"):
                mat = True
                parts.append(" x ")  # como a matemática inline no LaTeX
            elif tag in (W + "softHyphen", W + "sym", W + "drawing", W + "pict", W + "object"):
                continue
            else:
                walk(ch)

    walk(p)
    texto = " ".join("".join(parts).replace("\xa0", " ").split())
    so_mat = mat and not re.sub(r"\bx\b", "", texto).strip(" .,;()")
    return _Texto(texto, mat, so_mat, runs_texto > 0 and runs_negrito == runs_texto, quebra)


def _papel_pagina(sect: ET.Element | None) -> tuple[str, dict[str, float]]:
    if sect is None:
        return "", {}
    papel = ""
    sz = sect.find(W + "pgSz")
    if sz is not None:
        try:
            w, h = sorted((int(sz.get(W + "w") or 0), int(sz.get(W + "h") or 0)))
        except ValueError:
            w = h = 0
        if abs(w - 11906) <= 60 and abs(h - 16838) <= 60:
            papel = "a4"
        elif abs(w - 12240) <= 60 and abs(h - 15840) <= 60:
            papel = "letter"
        elif w and h:
            papel = f"{w / TWIP_CM:.1f} x {h / TWIP_CM:.1f} cm"
    margens: dict[str, float] = {}
    mar = sect.find(W + "pgMar")
    if mar is not None:
        for k in ("left", "right", "top", "bottom"):
            v = mar.get(W + k)
            try:
                if v is not None:
                    margens[k] = abs(int(v)) / TWIP_CM
            except ValueError:
                continue
    return papel, margens


def ler_docx(abspath: Path, relpath: Path) -> Documento:
    data = ler_bytes(abspath)
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise DocumentoError(
            f"{relpath.as_posix()} não é um .docx válido (arquivo .doc antigo? salve como .docx)"
        ) from exc
    with z:
        corpo = _ler(z, "word/document.xml")
        if corpo is None:
            raise DocumentoError(f"{relpath.as_posix()}: falta word/document.xml")
        root = _xml(corpo, "word/document.xml")
        est_raw = _ler(z, "word/styles.xml")
        estilos, padrao, tamanho = _estilos(_xml(est_raw, "word/styles.xml") if est_raw else None)
        core = _ler(z, "docProps/core.xml")
        notas = _ler(z, "word/footnotes.xml")
        meta = _xml(core, "docProps/core.xml") if core else None
        n_notas = 0
        if notas:
            n_notas = sum(
                1
                for f in _xml(notas, "word/footnotes.xml").findall(W + "footnote")
                if (f.get(W + "id") or "0").lstrip("-").isdigit() and int(f.get(W + "id") or 0) > 0
            )

    body = root.find(W + "body")
    if body is None:
        raise DocumentoError(f"{relpath.as_posix()}: documento sem corpo")
    doc = Documento(relpath, abspath, "docx", hash=sha256(data))
    if meta is not None:
        doc.titulo = " ".join((meta.findtext(DC + "title") or "").split())
        doc.autor = " ".join((meta.findtext(DC + "creator") or "").split())
    sects = body.findall(W + "sectPr") or root.findall(f".//{W}sectPr")
    doc.papel, doc.margens_cm = _papel_pagina(sects[-1] if sects else None)
    pad = estilos.get(padrao)
    doc.fonte_pt = (pad.tamanho if pad and pad.tamanho else None) or tamanho

    ignorado = {"notas de rodapé": n_notas, "tabelas": 0, "equações": 0, "caixas de texto": 0}
    ignorado["caixas de texto"] = sum(1 for _ in root.iter(W + "txbxContent"))
    ignorado["comentários"] = sum(1 for _ in root.iter(W + "commentReference"))
    apagados = sum(1 for _ in root.iter(W + "del"))
    if apagados:
        doc.avisos.append(
            f"há {apagados} trecho(s) em alterações controladas: o texto foi lido como se elas "
            "fossem aceitas"
        )
    n = 0
    tabelas_vistas: set[int] = set()
    paginas = 1
    for p, tabela, sdt in _paragrafos(body):
        ppr = p.find(W + "pPr")
        sid = _val(ppr.find(W + "pStyle")) if ppr is not None else None
        sid = sid or padrao
        st = _Estilo()
        _ppr(ppr, st)
        if ppr is not None:
            _rpr(ppr.find(W + "rPr"), st)
        papel = str(_herdar(estilos, sid, "papel") or "")
        nivel_estilo = _herdar(estilos, sid, "nivel")
        nivel = st.nivel if st.nivel is not None else nivel_estilo
        centro = st.centro if st.centro is not None else _herdar(estilos, sid, "centro")
        recuo = st.recuo_cm if st.recuo_cm is not None else _herdar(estilos, sid, "recuo_cm")
        lista = bool(st.lista) or bool(_herdar(estilos, sid, "lista")) or papel == "lista"
        negrito_estilo = bool(_herdar(estilos, sid, "negrito"))
        t = _texto(p, negrito_estilo)
        if ppr is not None and _on(ppr.find(W + "pageBreakBefore")):
            t.quebra = True
        if t.quebra:
            paginas += 1
        if not t.texto:
            continue
        n += 1
        if tabela:
            tabelas_vistas.add(id(p))
        if t.so_matematica:
            ignorado["equações"] += 1
        nivel_i = int(nivel) if isinstance(nivel, int) else 0
        doc.blocos.append(
            Bloco(
                t.texto,
                n,
                estilo=sdt or papel,
                nivel=nivel_i if 0 < nivel_i <= 9 and not tabela else 0,
                lista=lista and not nivel_i,
                centralizado=bool(centro),
                recuado=isinstance(recuo, float) and recuo >= RECUO_CITACAO_CM and not lista,
                destaque=t.negrito,
                tabela=tabela,
                equacao=t.so_matematica,
            )
        )
    ignorado["tabelas"] = sum(1 for _ in body.iter(W + "tbl"))
    doc.ignorado = {k: v for k, v in ignorado.items() if v}
    doc.paginas = paginas
    if not doc.blocos:
        raise DocumentoError(f"{relpath.as_posix()}: nenhum texto encontrado")
    return doc
