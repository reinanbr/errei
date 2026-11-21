"""Modelo comum aos leitores: o documento como uma sequência de blocos (parágrafos)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

FORMATOS = {".docx": "docx", ".pdf": "pdf"}
UNIDADE = {"docx": "§", "pdf": "p."}  # como a localização aparece no relatório
MAX_BYTES = 80 * 1024 * 1024


class DocumentoError(Exception):
    """Documento ilegível (vira erro de ambiente, código de saída 2)."""


@dataclass(slots=True)
class Bloco:
    """Um parágrafo do documento, com as pistas de formatação que o leitor conseguiu."""

    texto: str
    unidade: int  # nº do parágrafo (.docx) ou página (.pdf) onde o bloco começa
    estilo: str = ""  # papel do estilo do .docx: titulo, legenda, citacao, sumario, lista...
    nivel: int = 0  # nível de título indicado pelo estilo/estrutura (0 = não é título)
    lista: bool = False
    centralizado: bool = False
    recuado: bool = False  # recuo grande à esquerda (citação longa, NBR 10520)
    destaque: bool = False  # todo em negrito
    tabela: bool = False
    equacao: bool = False
    # .pdf: linhas originais (para separar as referências) e páginas dentro do bloco
    linhas: list[str] = field(default_factory=list)
    paginas: list[tuple[int, int]] = field(default_factory=list)  # (offset no texto, página)

    def pagina(self, offset: int) -> int:
        """Página do caractere ``offset`` do texto (no .docx, o próprio parágrafo)."""
        atual = self.unidade
        for off, pag in self.paginas:
            if off > offset:
                break
            atual = pag
        return atual


@dataclass(slots=True)
class Documento:
    caminho: Path  # relativo à raiz do projeto
    abspath: Path
    formato: str  # docx | pdf
    blocos: list[Bloco] = field(default_factory=list)
    papel: str = ""  # a4 | letter | outro tamanho em cm | ''
    margens_cm: dict[str, float] = field(default_factory=dict)  # left/right/top/bottom
    fonte_pt: float | None = None
    titulo: str = ""  # metadados do arquivo
    autor: str = ""
    paginas: int = 0
    # o que o leitor não analisa (para o relatório): notas, tabelas, equações...
    ignorado: dict[str, int] = field(default_factory=dict)
    avisos: list[str] = field(default_factory=list)
    hash: str = ""

    @property
    def unidade(self) -> str:
        return UNIDADE[self.formato]


def ler_bytes(abspath: Path) -> bytes:
    try:
        size = abspath.stat().st_size
    except OSError as exc:
        raise DocumentoError(f"não foi possível ler {abspath.name}: {exc}") from exc
    if size > MAX_BYTES:
        raise DocumentoError(
            f"{abspath.name} tem {size / 1024 / 1024:.0f} MB (limite: {MAX_BYTES // 1024 // 1024})"
        )
    try:
        return abspath.read_bytes()
    except OSError as exc:
        raise DocumentoError(f"não foi possível ler {abspath.name}: {exc}") from exc


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def ler(abspath: Path, relpath: Path) -> Documento:
    """Lê um ``.docx`` ou ``.pdf``."""
    formato = FORMATOS.get(abspath.suffix.lower())
    if formato == "docx":
        from errei.documento.docx import ler_docx

        return ler_docx(abspath, relpath)
    if formato == "pdf":
        from errei.documento.pdf import ler_pdf

        return ler_pdf(abspath, relpath)
    raise DocumentoError(f"formato não suportado: {abspath.suffix or abspath.name}")
