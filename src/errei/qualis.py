"""Leitura da tabela Qualis (CSV exportado da Plataforma Sucupira/CAPES).

Formato esperado (cabeçalho na 1ª linha; nomes tolerantes a acento/caixa):

    ISSN;Título;Área de Avaliação;Estrato
    0028-0836;NATURE;CIÊNCIA DA COMPUTAÇÃO;A1

Delimitador ``;``, ``,`` ou tabulação; codificação UTF-8 (com ou sem BOM) ou
Latin-1/CP1252 (comum nas exportações da Sucupira). O CSV é a fonte da verdade.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from errei.config import ConfigError
from errei.text.segment import strip_accents

ALIASES = {
    "issn": ("issn", "issn/eissn", "issn_eissn"),
    "title": ("titulo", "title", "periodico", "nome do periodico", "titulo do periodico"),
    "area": ("area de avaliacao", "area", "area avaliacao", "area de conhecimento"),
    "estrato": ("estrato", "qualis", "classificacao", "estrato qualis"),
}
VALID_ESTRATOS = {"A1", "A2", "A3", "A4", "B1", "B2", "B3", "B4", "B5", "C"}
MAX_BYTES = 50 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class QualisRow:
    issn: str  # normalizado: 8 caracteres sem hífen
    title: str
    area: str
    estrato: str


@dataclass(slots=True)
class QualisTable:
    path: Path
    rows: list[QualisRow]
    ref_date: str  # AAAA-MM-DD
    date_source: str  # "informada" | "data de modificação do arquivo"
    encoding: str

    def by_issn(self, issn: str) -> list[QualisRow]:
        n = norm_issn(issn)
        return [r for r in self.rows if r.issn == n]

    def by_title(self, title: str, cutoff: float = 0.9) -> list[QualisRow]:
        target = norm_title(title)
        if not target:
            return []
        exact = [r for r in self.rows if norm_title(r.title) == target]
        if exact:
            return exact
        try:
            from rapidfuzz import fuzz

            def score(a: str, b: str) -> float:
                return float(fuzz.ratio(a, b)) / 100
        except ModuleNotFoundError:  # pragma: no cover
            import difflib

            def score(a: str, b: str) -> float:
                return difflib.SequenceMatcher(None, a, b).ratio()

        best = 0.0
        hits: list[QualisRow] = []
        for r in self.rows:
            s = score(target, norm_title(r.title))
            if s > best + 1e-9:
                best, hits = s, [r]
            elif abs(s - best) < 1e-9:
                hits.append(r)
        if best < cutoff:
            return []
        # todas as linhas com o mesmo título (áreas diferentes)
        t = norm_title(hits[0].title)
        return [r for r in self.rows if norm_title(r.title) == t]


def norm_issn(s: str) -> str:
    return re.sub(r"[^0-9X]", "", s.upper())[:8]


def norm_title(s: str) -> str:
    s = strip_accents(s.lower())
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"^the\s+", "", s.strip())
    return " ".join(s.split())


def _header_key(h: str) -> str | None:
    k = " ".join(strip_accents(h.strip().lower().replace("_", " ")).split())
    for field, names in ALIASES.items():
        if k in names:
            return field
    return None


def parse_target(spec: str) -> tuple[str, str]:
    """``"ISSN 1234-5678"`` → ("issn", "12345678"); outro texto → ("title", texto)."""
    m = re.search(r"\b(\d{4})-?(\d{3}[\dXx])\b", spec)
    if m:
        return "issn", norm_issn(m.group(1) + m.group(2))
    return "title", spec.strip()


def load_qualis(path: Path, ref_date: str = "") -> QualisTable:
    path = path.expanduser()
    if not path.is_file():
        raise ConfigError(f"CSV Qualis não encontrado: {path}")
    raw = path.read_bytes()[:MAX_BYTES]
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,\t")
        delim = dialect.delimiter
    except csv.Error:
        delim = ";" if sample.count(";") >= sample.count(",") else ","
    reader = csv.reader(io.StringIO(text), delimiter=delim)
    try:
        header = next(reader)
    except StopIteration as exc:
        raise ConfigError(f"CSV Qualis vazio: {path}") from exc
    cols: dict[str, int] = {}
    for i, h in enumerate(header):
        key = _header_key(h)
        if key and key not in cols:
            cols[key] = i
    missing = [c for c in ("estrato",) if c not in cols]
    if missing or not ({"issn", "title"} & set(cols)):
        raise ConfigError(
            f"CSV Qualis inválido ({path}): cabeçalho precisa de 'Estrato' e de 'ISSN' ou "
            f"'Título'; encontrado: {header}"
        )
    rows: list[QualisRow] = []
    for rec in reader:
        if not rec or not any(c.strip() for c in rec):
            continue

        def get(field: str, rec: list[str] = rec) -> str:
            i = cols.get(field)
            return rec[i].strip() if i is not None and i < len(rec) else ""

        estrato = get("estrato").upper().replace(" ", "")
        if estrato not in VALID_ESTRATOS:
            continue
        rows.append(QualisRow(norm_issn(get("issn")), get("title"), get("area"), estrato))
    if not rows:
        raise ConfigError(f"CSV Qualis sem linhas válidas (estratos A1–C): {path}")
    if ref_date:
        try:
            datetime.strptime(ref_date, "%Y-%m-%d")
        except ValueError as exc:
            raise ConfigError(f"data do Qualis inválida (use AAAA-MM-DD): {ref_date}") from exc
        when, source = ref_date, "informada"
    else:
        when = date.fromtimestamp(path.stat().st_mtime).isoformat()
        source = "data de modificação do arquivo"
    return QualisTable(path, rows, when, source, enc)
