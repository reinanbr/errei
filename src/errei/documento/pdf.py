"""Leitura de ``.pdf`` com o pypdf (só o texto embutido; não faz OCR).

O pypdf extrai o texto de dois jeitos, e cada um erra num lugar:

* o modo simples preserva os espaços entre as palavras, mas perde o desenho da página;
* o modo "layout" mantém o recuo da primeira linha, as linhas em branco e a centralização
  (o que separa parágrafos e títulos), mas às vezes cola palavras de linhas justificadas.

As linhas dos dois modos são alinhadas pelo conteúdo sem espaços: o texto vem do modo
simples e a estrutura, do layout. Cabeçalhos e rodapés repetidos e números de página são
removidos; palavras hifenizadas no fim da linha são reunidas.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from errei.documento.modelo import Bloco, Documento, DocumentoError, ler_bytes, sha256

MAX_PAGINAS = 800
# título numerado ("2.1 Materiais e métodos") ou em maiúsculas, numa linha só
NUM_TITULO = re.compile(r"^(\d{1,2}(?:\.\d{1,2}){0,4})\.?\s+[A-ZÀ-Ý]")
# marcadores de lista (inclui os da fonte Symbol/Wingdings do Word, na área de uso privado)
MARCADOR = re.compile(r"^(?:[•●▪◦‣∙·–—\-\uf000-\uf0ff]|[a-z]\)|\d{1,2}\)|[ivx]{1,4}\))\s*")
NUM_PAGINA = re.compile(
    r"^(?:p[aá]g(?:ina)?\.?\s*)?\d{1,4}(?:\s*(?:/|de|of)\s*\d{1,4})?$", re.IGNORECASE
)


@dataclass(slots=True)
class _Linha:
    texto: str
    recuo: int  # colunas no modo layout
    brancos: int  # linhas em branco antes (modo layout)
    largura: int
    pagina: int


def _chave(s: str) -> str:
    return re.sub(r"\s+", "", s)


def _duas_colunas(layout: list[str]) -> bool:
    longas = [x.strip() for x in layout if len(x.strip()) >= 40]
    if len(longas) < 8:
        return False
    gap = sum(1 for x in longas if re.search(r"\S.{14,}?\S {5,}\S.{14,}", x))
    return gap >= 0.3 * len(longas)


def _linhas_pagina(page: object, n: int) -> tuple[list[_Linha], bool]:
    plain = page.extract_text() or ""  # type: ignore[attr-defined]
    try:
        layout = page.extract_text(extraction_mode="layout") or ""  # type: ignore[attr-defined]
    except Exception:  # modo layout falha em alguns PDFs: fica o simples
        layout = ""
    simples = [" ".join(x.split()) for x in plain.splitlines() if x.strip()]
    if not layout.strip():
        return [_Linha(t, 0, 0, len(t), n) for t in simples], False
    brutas: list[tuple[str, int]] = []
    branco = 0
    for raw in layout.splitlines():
        if not raw.strip():
            branco += 1
            continue
        brutas.append((raw.rstrip(), branco))
        branco = 0
    if _duas_colunas([r for r, _ in brutas]):
        # o layout põe as duas colunas lado a lado; o modo simples costuma seguir a coluna
        return [_Linha(t, 0, 0, len(t), n) for t in simples], True
    chaves = [_chave(t) for t in simples]
    out: list[_Linha] = []
    j = 0
    for raw, b in brutas:
        k = _chave(raw)
        texto = " ".join(raw.split())
        for jj in range(j, min(j + 6, len(simples))):
            if chaves[jj] == k:
                texto = simples[jj]
                j = jj + 1
                break
        out.append(_Linha(texto, len(raw) - len(raw.lstrip()), b, len(raw), n))
    return out, False


def _assinatura(s: str) -> str:
    return " ".join(re.sub(r"\d+", "#", s.lower()).split())


def _sem_cabecalhos(paginas: list[list[_Linha]]) -> int:
    """Remove cabeçalhos/rodapés repetidos e números de página. Devolve quantas linhas."""
    n = len(paginas)
    repetidas: set[str] = set()
    if n >= 2:  # com 2 páginas, só o que se repete nas duas
        cont: Counter[str] = Counter()
        for ls in paginas:
            cont.update({_assinatura(x.texto) for x in ls[:2] + ls[-2:]})
        repetidas = {k for k, v in cont.items() if v >= max(2, 0.4 * n) and len(k) >= 3}
    removidas = 0
    for ls in paginas:
        bordas = set(range(min(2, len(ls)))) | set(range(max(0, len(ls) - 2), len(ls)))
        manter = [
            x
            for i, x in enumerate(ls)
            if not (
                i in bordas
                and (_assinatura(x.texto) in repetidas or NUM_PAGINA.match(x.texto.strip()))
            )
        ]
        removidas += len(ls) - len(manter)
        ls[:] = manter
    return removidas


def _moda(vals: list[int], padrao: int = 0) -> int:
    return Counter(vals).most_common(1)[0][0] if vals else padrao


def _titulo_linha(t: str) -> bool:
    palavras = t.split()
    if not 1 <= len(palavras) <= 14 or len(t) < 3 or t.endswith((".", ",", ";")):
        return False
    if NUM_TITULO.match(t):
        return True
    letras = re.sub(r"[^A-Za-zÀ-ÿ]", "", t)
    return len(letras) >= 4 and letras.isupper()


_PALAVRA_FIM = re.compile(r"([A-Za-zÀ-ÿ]+)[-‐\xad]$")
_PALAVRA_INICIO = re.compile(r"[a-zà-ÿ]+")
COMPOSTA = re.compile(r"\b[A-Za-zÀ-ÿ]+-[a-zà-ÿ]+\b")


def _juntar(linhas: list[_Linha], compostas: set[str]) -> tuple[str, list[tuple[int, int]]]:
    """Une as linhas; no hífen de fim de linha, só mantém o hífen de palavra composta que
    aparece inteira em outro ponto do documento ("arquivos-fonte")."""
    texto = ""
    paginas: list[tuple[int, int]] = []
    for ln in linhas:
        t = ln.texto
        fim = _PALAVRA_FIM.search(texto) if texto else None
        ini = _PALAVRA_INICIO.match(t) if fim else None
        if fim and ini:
            if f"{fim.group(1)}-{ini.group(0)}".lower() not in compostas:
                texto = texto[:-1]  # hifenização de fim de linha
            inicio = len(texto)
            texto += t
        else:
            if texto:
                texto += " "
            inicio = len(texto)
            texto += t
        if not paginas or paginas[-1][1] != ln.pagina:
            paginas.append((inicio, ln.pagina))
    return texto, paginas


def _blocos(paginas: list[list[_Linha]]) -> list[Bloco]:
    todas = [x for ls in paginas for x in ls]
    if not todas:
        return []
    branco = _moda([x.brancos for x in todas if x.brancos < 4])
    # margem e largura de linha cheia por página (o layout é relativo a cada página)
    bases: dict[int, int] = {}
    cheias: dict[int, int] = {}
    for ls in paginas:
        if not ls:
            continue
        larg = sorted(x.largura for x in ls)
        cheia_p = larg[int(0.9 * (len(larg) - 1))] or 1
        plenas = [x.recuo for x in ls if x.largura >= 0.7 * cheia_p] or [x.recuo for x in ls]
        bases[ls[0].pagina] = _moda(plenas)
        cheias[ls[0].pagina] = cheia_p

    def centrada(x: _Linha) -> bool:
        base, cheia = bases[x.pagina], cheias[x.pagina]
        # a 1ª linha recuada de um parágrafo justificado também "sobra" dos dois lados:
        # centralizada exige margem de pelo menos 10% da linha
        if x.recuo < base + max(4, 0.1 * cheia) or x.largura >= 0.95 * cheia:
            return False
        meio = (x.recuo + x.largura) / 2
        return abs(meio - (base + cheia) / 2) <= max(4, 0.06 * cheia)

    def recuada(x: _Linha) -> bool:
        # citação longa: recuo de 4 cm (~25% da linha); o de primeira linha (1,25 cm) é menor
        limite = max(10, 0.15 * cheias[x.pagina])
        return x.recuo - bases[x.pagina] >= limite and not centrada(x)

    def maiuscula(t: str) -> bool:
        letras = re.sub(r"[^A-Za-zÀ-ÿ]", "", t)
        return len(letras) >= 4 and letras.isupper()

    grupos: list[list[_Linha]] = []
    for x in todas:
        atual = grupos[-1] if grupos else None
        prev = atual[-1] if atual else None
        novo = prev is None
        if prev is not None and not novo:
            fim_frase = bool(re.search(r"[.!?:;]$", prev.texto))
            if x.pagina != prev.pagina:
                novo = fim_frase and not x.texto[:1].islower()
            elif x.brancos > branco:
                novo = True
            elif _titulo_linha(x.texto) or _titulo_linha(prev.texto):
                # título em duas linhas: centrado, ou em maiúsculas sem pontuação no fim
                junta = (centrada(x) and centrada(prev)) or (
                    maiuscula(x.texto)
                    and maiuscula(prev.texto)
                    and not fim_frase
                    and not NUM_TITULO.match(x.texto)
                )
                novo = not junta
            elif MARCADOR.match(x.texto):
                novo = True
            elif centrada(x) != centrada(prev):
                novo = fim_frase or not x.texto[:1].islower()  # título em duas linhas
            elif recuada(x) != recuada(prev):
                novo = True
            elif x.recuo >= bases[x.pagina] + 2 and not recuada(x):
                novo = True  # recuo de primeira linha
            elif prev.largura < 0.8 * cheias[prev.pagina] and fim_frase:
                novo = True
        if novo:
            grupos.append([x])
        else:
            grupos[-1].append(x)
    compostas = {m.group(0).lower() for x in todas for m in COMPOSTA.finditer(x.texto)}
    out: list[Bloco] = []
    for g in grupos:
        texto, pags = _juntar(g, compostas)
        if not texto.strip():
            continue
        out.append(
            Bloco(
                texto,
                g[0].pagina,
                centralizado=all(centrada(x) for x in g),
                recuado=len(g) >= 2 and sum(recuada(x) for x in g) >= len(g) - 1,
                lista=bool(MARCADOR.match(texto)),
                linhas=[x.texto for x in g],
                paginas=pags if len(pags) > 1 else [],
            )
        )
    return out


def _papel(page: object) -> str:
    try:
        box = page.mediabox  # type: ignore[attr-defined]
        w, h = sorted((float(box.width), float(box.height)))
    except Exception:
        return ""
    if abs(w - 595.3) <= 4 and abs(h - 841.9) <= 4:
        return "a4"
    if abs(w - 612) <= 4 and abs(h - 792) <= 4:
        return "letter"
    return f"{w / 72 * 2.54:.1f} x {h / 72 * 2.54:.1f} cm"


def ler_pdf(abspath: Path, relpath: Path) -> Documento:
    try:
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError
    except ModuleNotFoundError as exc:
        raise DocumentoError(
            "ler .pdf requer o pypdf: pip install 'errei[documentos]' (ou 'errei[all]')"
        ) from exc
    import io
    import logging

    data = ler_bytes(abspath)
    logging.getLogger("pypdf").setLevel(logging.ERROR)  # PDFs reais geram muitos avisos
    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted and not reader.decrypt(""):
            raise DocumentoError(f"{relpath.as_posix()} está protegido por senha")
        pages = list(reader.pages[:MAX_PAGINAS])
    except DocumentoError:
        raise
    except (PdfReadError, ValueError, OSError, KeyError) as exc:
        raise DocumentoError(f"{relpath.as_posix()}: PDF ilegível ({exc})") from exc
    doc = Documento(relpath, abspath, "pdf", hash=sha256(data), paginas=len(reader.pages))
    try:
        meta: Any = reader.metadata or {}
        doc.titulo = " ".join(str(meta.get("/Title") or "").split())
        doc.autor = " ".join(str(meta.get("/Author") or "").split())
    except Exception:
        pass
    if pages:
        doc.papel = _papel(pages[0])
    por_pagina: list[list[_Linha]] = []
    sem_texto = 0
    colunas = 0
    for i, page in enumerate(pages, 1):
        try:
            linhas, duas = _linhas_pagina(page, i)
        except Exception:  # página corrompida: segue com as outras
            linhas, duas = [], False
        if not linhas:
            sem_texto += 1
        colunas += duas
        por_pagina.append(linhas)
    if sem_texto == len(pages):
        raise DocumentoError(
            f"{relpath.as_posix()} não tem texto extraível (é uma digitalização?); o errei não "
            "faz OCR: exporte o PDF do editor de texto ou audite o .docx"
        )
    _sem_cabecalhos(por_pagina)
    doc.blocos = _blocos(por_pagina)
    if sem_texto:
        doc.ignorado["páginas sem texto (imagem)"] = sem_texto
    if colunas:
        doc.avisos.append(
            f"{colunas} página(s) em duas colunas: a ordem do texto pode misturar as colunas"
        )
    if len(reader.pages) > MAX_PAGINAS:
        doc.avisos.append(f"só as primeiras {MAX_PAGINAS} páginas foram lidas")
    coladas = sum(1 for b in doc.blocos for w in b.texto.split() if len(re.sub(r"\W", "", w)) >= 28)
    if coladas >= 3:
        doc.avisos.append(
            f"{coladas} sequência(s) de palavras coladas na extração do PDF (linhas justificadas "
            "muito apertadas); a ortografia desses trechos não é confiável"
        )
    return doc
