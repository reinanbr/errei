"""Parser BibTeX/BibLaTeX tolerante, com posição de cada entrada e campo.

Trata o ``.bib`` como entrada não confiável: sem execução, limite de
entradas e de expansão de ``@string``.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from errei.latex.source import SourceFile

MAX_ENTRIES = 20_000
MONTHS = {
    m: m
    for m in ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
}


@dataclass(frozen=True, slots=True)
class BibField:
    name: str  # minúsculo
    value: str  # conteúdo sem delimitadores externos, @string expandido
    raw: str
    offset: int  # offset do nome do campo no arquivo


@dataclass(slots=True)
class BibEntry:
    source: SourceFile
    type: str  # minúsculo
    key: str
    start: int  # offset do '@'
    key_offset: int
    end: int
    fields: dict[str, BibField] = field(default_factory=dict)
    duplicate_fields: list[BibField] = field(default_factory=list)

    def get(self, name: str, default: str = "") -> str:
        f = self.fields.get(name)
        return f.value if f else default

    def has(self, name: str) -> bool:
        f = self.fields.get(name)
        return bool(f and f.value.strip())

    @property
    def line(self) -> int:
        return self.source.line_col(self.start)[0]

    def field_offset(self, name: str) -> int:
        f = self.fields.get(name)
        return f.offset if f else self.start


@dataclass(slots=True)
class BibProblem:
    message: str
    offset: int


@dataclass(slots=True)
class BibFile:
    source: SourceFile
    entries: list[BibEntry] = field(default_factory=list)
    problems: list[BibProblem] = field(default_factory=list)
    strings: dict[str, str] = field(default_factory=dict)


_AT_RE = re.compile(r"@\s*([A-Za-z]+)\s*([{(])")
_KEY_RE = re.compile(r"\s*([^,\s{}()\"#%'=]+)\s*,")
_NAME_RE = re.compile(r"\s*([A-Za-z][\w:.+-]*)\s*=\s*")


def _find_close(text: str, i: int, open_ch: str) -> int:
    """Índice do delimitador que fecha a entrada aberta em ``text[i]``; -1 se não houver."""
    depth = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if open_ch == "{" and depth == 0:
                return i
        elif c == ")" and open_ch == "(" and depth == 0:
            return i
        i += 1
    return -1


def _read_value(body: str, i: int, strings: dict[str, str]) -> tuple[str, str, int]:
    """Lê um valor (com concatenação ``#``). Retorna (valor, bruto, próximo índice)."""
    parts: list[str] = []
    start = i
    n = len(body)
    while i < n:
        while i < n and body[i] in " \t\r\n":
            i += 1
        if i >= n:
            break
        c = body[i]
        if c == "{":
            depth = 0
            j = i
            while j < n:
                if body[j] == "\\":
                    j += 2
                    continue
                if body[j] == "{":
                    depth += 1
                elif body[j] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            parts.append(body[i + 1 : j])
            i = j + 1
        elif c == '"':
            j = i + 1
            depth = 0
            while j < n:
                if body[j] == "\\":
                    j += 2
                    continue
                if body[j] == "{":
                    depth += 1
                elif body[j] == "}":
                    depth -= 1
                elif body[j] == '"' and depth == 0:
                    break
                j += 1
            parts.append(body[i + 1 : j])
            i = j + 1
        else:
            m = re.match(r"[^\s,#}]+", body[i:])
            if not m:
                break
            tok = m.group(0)
            low = tok.lower()
            parts.append(strings.get(low, MONTHS.get(low, tok)))
            i += len(tok)
        while i < n and body[i] in " \t\r\n":
            i += 1
        if i < n and body[i] == "#":
            i += 1
            continue
        break
    value = "".join(parts)[:10_000]
    return value, body[start:i], i


def parse_bib(src: SourceFile) -> BibFile:
    bib = BibFile(src)
    text = src.text
    pos = 0
    seen = 0
    while True:
        m = _AT_RE.search(text, pos)
        if not m:
            break
        seen += 1
        if seen > MAX_ENTRIES:
            bib.problems.append(
                BibProblem("número de entradas excede o limite; restante ignorado", m.start())
            )
            break
        etype = m.group(1).lower()
        open_ch = m.group(2)
        close = _find_close(text, m.end() - 1, open_ch)
        if close == -1:
            bib.problems.append(BibProblem(f"entrada @{etype} sem fechamento", m.start()))
            pos = m.end()
            continue
        body_start = m.end()
        body = text[body_start:close]
        pos = close + 1
        if etype == "comment" or etype == "preamble":
            continue
        if etype == "string":
            nm = _NAME_RE.match(body)
            if nm:
                val, _, _ = _read_value(body, nm.end(), bib.strings)
                bib.strings[nm.group(1).lower()] = val
            continue
        km = _KEY_RE.match(body)
        if not km:
            bib.problems.append(BibProblem(f"entrada @{etype} sem chave", m.start()))
            continue
        entry = BibEntry(src, etype, km.group(1), m.start(), body_start + km.start(1), close + 1)
        i = km.end()
        while i < len(body):
            fm = _NAME_RE.match(body, i)
            if not fm:
                # pula até a próxima vírgula de nível 0
                nxt = body.find(",", i)
                if nxt == -1:
                    break
                if body[i:nxt].strip():
                    bib.problems.append(BibProblem("campo malformado", body_start + i))
                i = nxt + 1
                continue
            name = fm.group(1).lower()
            val, raw, j = _read_value(body, fm.end(), bib.strings)
            fobj = BibField(name, val.strip(), raw, body_start + fm.start(1))
            if name in entry.fields:
                entry.duplicate_fields.append(fobj)
            else:
                entry.fields[name] = fobj
            i = j
            while i < len(body) and body[i] in " \t\r\n":
                i += 1
            if i < len(body) and body[i] == ",":
                i += 1
            elif i < len(body):
                bib.problems.append(
                    BibProblem(f"vírgula ausente após o campo '{name}'", body_start + i)
                )
                nxt = body.find(",", i)
                if nxt == -1:
                    break
                i = nxt + 1
        bib.entries.append(entry)
    return bib


_COMBINING = {
    "'": "\u0301",
    "`": "\u0300",
    "^": "\u0302",
    "~": "\u0303",
    '"': "\u0308",
    "=": "\u0304",
    ".": "\u0307",
    "c": "\u0327",
    "u": "\u0306",
    "v": "\u030c",
    "H": "\u030b",
    "k": "\u0328",
    "r": "\u030a",
}
_ACC_SYM = re.compile(r"\\([`'^~\"=.])\s*(?:\{\s*)?\\?([A-Za-z])(?:\s*\})?")
_ACC_LET = re.compile(r"\\([cuvHkr])(?:\s+|\s*\{\s*)\\?([A-Za-z])(?:\s*\})?")


def _accent(m: re.Match[str]) -> str:
    return unicodedata.normalize("NFC", m.group(2) + _COMBINING[m.group(1)])


def plain(value: str) -> str:
    """Converte um valor BibTeX em texto simples (acentos, chaves, comandos)."""
    s = _ACC_SYM.sub(_accent, value)
    s = _ACC_LET.sub(_accent, s)
    s = s.replace("\\&", "&").replace("\\%", "%").replace("\\_", "_")
    s = re.sub(r"\\[A-Za-z]+\s*", "", s)
    s = s.replace("{", "").replace("}", "").replace("~", " ")
    s = s.replace("---", "—").replace("--", "–")
    return " ".join(s.split())
