"""Leitura de planilhas CSV e XLSX só com a biblioteca padrão.

Serve para as listas que você baixa: Qualis (Sucupira), Scopus (lista de fontes e
CiteScore) e Web of Science (Master Journal List). O XLSX é um zip de XML: lemos as
strings compartilhadas e as células de cada aba. Arquivos .xls antigos (BIFF) não são
lidos: converta para .xlsx ou .csv (LibreOffice: ``soffice --headless --convert-to csv``).
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
MAX_BYTES = 200 * 1024 * 1024


def _seguro(dados: bytes) -> bytes:
    if b"<!ENTITY" in dados or b"<!DOCTYPE" in dados:
        raise ValueError("XML com DOCTYPE/entidades recusado")
    return dados


def _coluna(ref: str) -> int:
    letras = re.match(r"[A-Z]+", ref or "A")
    n = 0
    for c in letras.group(0) if letras else "A":
        n = n * 26 + ord(c) - 64
    return n - 1


def ler_xlsx(p: Path) -> list[tuple[str, list[list[str]]]]:
    """[(nome da aba, linhas)] com todas as células como texto."""
    out: list[tuple[str, list[list[str]]]] = []
    with zipfile.ZipFile(p) as z:
        if sum(i.file_size for i in z.infolist()) > MAX_BYTES:
            raise ValueError(f"{p.name}: planilha grande demais")
        nomes = set(z.namelist())
        compartilhadas: list[str] = []
        if "xl/sharedStrings.xml" in nomes:
            raiz = ET.fromstring(_seguro(z.read("xl/sharedStrings.xml")))
            for si in raiz.findall("m:si", NS):
                compartilhadas.append("".join(t.text or "" for t in si.iter(f"{{{NS['m']}}}t")))
        wb = ET.fromstring(_seguro(z.read("xl/workbook.xml")))
        rels = ET.fromstring(_seguro(z.read("xl/_rels/workbook.xml.rels")))
        alvo = {r.get("Id"): r.get("Target", "") for r in rels}
        for sh in wb.findall("m:sheets/m:sheet", NS):
            t = alvo.get(sh.get(REL), "")
            arq = t.lstrip("/") if t.startswith("/") else f"xl/{t}"
            if arq not in nomes:
                continue
            raiz = ET.fromstring(_seguro(z.read(arq)))
            linhas: list[list[str]] = []
            for row in raiz.iter(f"{{{NS['m']}}}row"):
                cel: dict[int, str] = {}
                for c in row.findall("m:c", NS):
                    tipo, v = c.get("t"), c.find("m:v", NS)
                    if tipo == "s" and v is not None and v.text is not None:
                        val = compartilhadas[int(v.text)]
                    elif tipo == "inlineStr":
                        val = "".join(x.text or "" for x in c.iter(f"{{{NS['m']}}}t"))
                    else:
                        val = v.text if v is not None and v.text is not None else ""
                    cel[_coluna(c.get("r", ""))] = val.strip()
                if cel:
                    linhas.append([cel.get(i, "") for i in range(max(cel) + 1)])
            out.append((sh.get("name", ""), linhas))
    return out


def ler_csv(p: Path) -> list[list[str]]:
    dados = p.read_bytes()
    if len(dados) > MAX_BYTES:
        raise ValueError(f"{p.name}: arquivo grande demais")
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            texto = dados.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    amostra = texto[:20000]
    try:
        dialeto = csv.Sniffer().sniff(amostra, delimiters=";,\t")
        delim = dialeto.delimiter
    except csv.Error:
        delim = max(";,\t", key=amostra.count)
    return [[c.strip() for c in row] for row in csv.reader(io.StringIO(texto), delimiter=delim)]


def abas(p: Path) -> list[tuple[str, list[list[str]]]]:
    suf = p.suffix.lower()
    if suf in {".xlsx", ".xlsm"}:
        return ler_xlsx(p)
    if suf == ".xls":
        raise ValueError(f"{p.name}: .xls antigo não é lido; converta para .xlsx ou .csv")
    return [(p.stem, ler_csv(p))]


def tabela(p: Path, exige: tuple[str, ...]) -> tuple[list[str], list[list[str]], str]:
    """Primeira aba cujo cabeçalho (numa das 10 primeiras linhas) tem todas as palavras
    de ``exige``. Devolve (cabeçalho normalizado, linhas de dados, nome da aba)."""
    from comum.util import norm

    for nome, linhas in abas(p):
        for i, ln in enumerate(linhas[:10]):
            cab = [norm(c) for c in ln]
            junto = " | ".join(cab)
            if all(e in junto for e in exige):
                return cab, linhas[i + 1 :], nome
    raise ValueError(f"{p.name}: nenhuma aba com as colunas {exige}")


def coluna(cab: list[str], *opcoes: str, exata: bool = False) -> int | None:
    """Índice da primeira coluna que contém (ou é igual a) uma das opções, na ordem dada."""
    for o in opcoes:
        for i, c in enumerate(cab):
            if (c == o) if exata else (o in c):
                return i
    return None
