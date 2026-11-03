"""Corpo e lista de referências de um PDF de acesso aberto, só em memória.

Remove cabeçalhos/rodapés repetidos, junta hifenização de fim de linha e separa a lista
de referências pelo último título "Referências"/"References". O texto nunca é gravado.
"""

from __future__ import annotations

import io
import re
from collections import Counter

REFS_HEAD = re.compile(
    r"^\s*(\d+\.?\s*)?(refer[eê]ncias( bibliogr[aá]ficas)?|references|bibliografia|"
    r"literature cited|works cited)\s*:?\s*$",
    re.IGNORECASE | re.MULTILINE,
)
# fim do corpo também em "Agradecimentos", mas eles contêm as declarações: ficam no corpo
ABNT_ENTRY = re.compile(r"^\s*[A-ZÀ-Ý][A-ZÀ-Ý'\-]+(?: [A-ZÀ-Ý'\-]+)*, [A-ZÀ-Ý]")
APA_ENTRY = re.compile(r"^\s*[A-ZÀ-Ý][a-zà-ÿ'\-]+(?: [A-ZÀ-Ý][a-zà-ÿ'\-]+)*, (?:[A-ZÀ-Ý]\.\s?)+")
NUM_ENTRY = re.compile(r"^\s*(?:\[\d{1,3}\]|\d{1,3}\.)\s+[A-ZÀ-Ý]")


def paginas(data: bytes, max_paginas: int = 80) -> list[str] | None:
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        return [(pg.extract_text() or "") for pg in reader.pages[:max_paginas]]
    except Exception:  # PDF corrompido/criptografado: a obra fica sem medidas de texto
        return None


def _limpar(pags: list[str]) -> list[str]:
    linhas_por_pag = [[ln.strip() for ln in p.splitlines()] for p in pags]
    freq: Counter[str] = Counter()
    for ls in linhas_por_pag:
        for ln in set(ls):
            k = re.sub(r"\d+", "#", ln)
            if 0 < len(k) <= 120:
                freq[k] += 1
    corte = max(3, int(0.3 * len(pags)))
    out: list[str] = []
    for ls in linhas_por_pag:
        for ln in ls:
            if freq.get(re.sub(r"\d+", "#", ln), 0) >= corte:
                continue  # cabeçalho/rodapé/numeração
            out.append(ln)
    return out


def separar(pags: list[str]) -> tuple[str, list[str]]:
    """(corpo como texto corrido, linhas da lista de referências)."""
    linhas = _limpar(pags)
    texto = "\n".join(linhas)
    heads = list(REFS_HEAD.finditer(texto))
    refs_txt = ""
    if heads:
        h = heads[-1]
        if h.start() > len(texto) * 0.4:  # título no fim do documento, não no sumário
            refs_txt = texto[h.end() :]
            texto = texto[: h.start()]
    corpo = re.sub(r"(\w)-\n(\w)", r"\1\2", texto)
    corpo = re.sub(r"\s*\n\s*", " ", corpo)
    return corpo, [ln for ln in refs_txt.splitlines() if ln.strip()]


def contar_referencias(linhas: list[str]) -> int | None:
    """Estimativa do nº de entradas (ABNT, APA ou numeradas); None se não der para contar."""
    if not linhas:
        return None
    n = max(
        sum(1 for ln in linhas if ABNT_ENTRY.match(ln)),
        sum(1 for ln in linhas if APA_ENTRY.match(ln)),
        sum(1 for ln in linhas if NUM_ENTRY.match(ln)),
    )
    return n if n >= 3 else None
