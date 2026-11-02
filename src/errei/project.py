"""Descoberta e modelo do projeto (somente leitura)."""

from __future__ import annotations

import hashlib
import os
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from errei.bib.parser import BibEntry, BibFile, parse_bib
from errei.latex.extract import CleanText, Paragraph, extract
from errei.latex.scanner import Command, find_commands, split_keys
from errei.latex.source import SourceFile, read_source

SKIP_DIRS = {"node_modules", "__pycache__", "build", "out", "dist", "venv", "_minted"}
MAX_FILES = 2000
MAIN_NAMES = ("main.tex", "artigo.tex", "article.tex", "paper.tex", "documento.tex")
INCLUDE_CMDS = ("input", "include", "subfile", "InputIfFileExists")
CITE_CMDS = (
    "cite",
    "citep",
    "citet",
    "citeonline",
    "citeauthor",
    "citeyear",
    "citeauthoronline",
    "parencite",
    "Parencite",
    "textcite",
    "Textcite",
    "autocite",
    "Autocite",
    "footcite",
    "citealp",
    "citealt",
    "citeyearpar",
    "Cite",
    "Citet",
    "Citeauthor",
    "nocite",
    "fullcite",
    "apud",
    "apudonline",
    "smartcite",
    "supercite",
)


class ProjectError(Exception):
    """Erro de ambiente (exit code 2)."""


@dataclass(frozen=True, slots=True)
class Include:
    source: SourceFile
    offset: int
    raw: str
    kind: str  # input|include|subfile|import|bibliography|addbibresource
    resolved: Path | None  # caminho absoluto quando existe e está dentro da raiz
    problem: str | None = None  # "inexistente" | "fora da raiz" | "ciclo"


@dataclass(frozen=True, slots=True)
class CiteUse:
    source: SourceFile
    command: Command
    key: str
    offset: int


@dataclass(slots=True)
class Project:
    root: Path
    main: SourceFile | None
    tex: list[SourceFile]  # ordem do documento (DFS a partir do principal)
    orphans: list[SourceFile]
    bibs: list[BibFile]
    includes: list[Include]
    notes: list[str] = field(default_factory=list)
    _clean: dict[Path, CleanText] = field(default_factory=dict, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    # -- texto limpo ------------------------------------------------------
    def clean(self, src: SourceFile) -> CleanText:
        with self._lock:
            ct = self._clean.get(src.path)
            if ct is None:
                ct = extract(src)
                self._clean[src.path] = ct
            return ct

    def paragraphs(self, kinds: tuple[str, ...] | None = None) -> Iterator[Paragraph]:
        for src in self.tex:
            for p in self.clean(src).paragraphs:
                if kinds is None or p.kind in kinds:
                    yield p

    # -- consultas --------------------------------------------------------
    def commands(
        self, names: tuple[str, ...] | list[str], mandatory: int = 1, include_orphans: bool = False
    ) -> Iterator[tuple[SourceFile, Command]]:
        files = self.tex + (self.orphans if include_orphans else [])
        for src in files:
            for cmd in find_commands(src.masked, names, mandatory=mandatory):
                yield src, cmd

    def cite_uses(self) -> list[CiteUse]:
        out: list[CiteUse] = []
        single = tuple(c for c in CITE_CMDS if c not in ("apud", "apudonline"))
        found = list(self.commands(single)) + list(self.commands(("apud", "apudonline"), 2))
        for src, cmd in found:
            for arg in cmd.mandatory:
                for key, off in split_keys(arg):
                    out.append(CiteUse(src, cmd, key, off))
        out.sort(key=lambda c: (self.tex.index(c.source) if c.source in self.tex else 0, c.offset))
        return out

    @property
    def bib_entries(self) -> list[BibEntry]:
        return [e for b in self.bibs for e in b.entries]

    def preamble_text(self) -> str:
        """Preâmbulo do principal (antes de \\begin{document}), mascarado."""
        if self.main is None:
            return ""
        m = self.main.masked
        idx = m.find("\\begin{document}")
        return m if idx == -1 else m[:idx]

    def packages(self) -> dict[str, tuple[str, SourceFile, int]]:
        """Pacotes carregados: nome -> (opções, arquivo, offset)."""
        out: dict[str, tuple[str, SourceFile, int]] = {}
        for src, cmd in self.commands(("usepackage", "RequirePackage")):
            opts = cmd.optional[0].text if cmd.optional else ""
            for a in cmd.mandatory[:1]:
                for name, off in split_keys(a):
                    out.setdefault(name, (opts, src, off))
        return out

    def documentclass(self) -> tuple[str, str, SourceFile, int] | None:
        if self.main is None:
            return None
        for cmd in find_commands(self.main.masked, ["documentclass"]):
            if cmd.mandatory:
                opts = cmd.optional[0].text if cmd.optional else ""
                return cmd.mandatory[0].text.strip(), opts, self.main, cmd.start
        return None

    def all_sources(self) -> list[SourceFile]:
        return self.tex + self.orphans + [b.source for b in self.bibs]

    def content_hash(self) -> str:
        h = hashlib.sha256()
        for src in sorted(self.all_sources(), key=lambda s: s.path.as_posix()):
            h.update(src.path.as_posix().encode())
            h.update(b"\0")
            h.update(src.text.encode("utf-8", "replace"))
        return h.hexdigest()

    def find_source(self, path: Path) -> SourceFile | None:
        for s in self.all_sources():
            if s.path == path:
                return s
        return None


# ------------------------------------------------------------------ descoberta
def _walk(root: Path) -> tuple[list[Path], list[Path]]:
    tex: list[Path] = []
    bib: list[Path] = []
    count = 0
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(
            d
            for d in dirnames
            if not d.startswith(".") and d not in SKIP_DIRS and not d.startswith("_minted")
        )
        for fn in sorted(filenames):
            p = Path(dirpath) / fn
            if p.is_symlink():
                continue
            if fn.endswith(".tex"):
                tex.append(p)
            elif fn.endswith(".bib"):
                bib.append(p)
            count += 1
            if count > MAX_FILES:
                return tex, bib
    return tex, bib


def _within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _is_main(src: SourceFile) -> bool:
    m = src.masked
    return "\\documentclass" in m and "\\begin{document}" in m


def _choose_main(cands: list[SourceFile], notes: list[str]) -> SourceFile | None:
    if not cands:
        return None
    if len(cands) == 1:
        return cands[0]
    for name in MAIN_NAMES:
        for c in cands:
            if c.path.name == name and len(c.path.parts) == 1:
                notes.append(f"vários .tex com \\documentclass; usando {c.path} (use --main)")
                return c
    best = max(cands, key=lambda c: len(list(find_commands(c.masked, INCLUDE_CMDS))))
    notes.append(f"vários .tex com \\documentclass; usando {best.path} (use --main)")
    return best


def load_project(root: Path, main: str | None = None) -> Project:
    root = root.expanduser()
    if not root.is_dir():
        raise ProjectError(f"pasta não encontrada: {root}")
    root = root.resolve()
    tex_paths, bib_paths = _walk(root)
    if not tex_paths:
        raise ProjectError(f"nenhum arquivo .tex encontrado em {root}")
    sources = {p.resolve(): read_source(p, p.relative_to(root)) for p in tex_paths}
    notes: list[str] = []
    for s in sources.values():
        if s.encoding != "utf-8":
            notes.append(f"{s.path}: lido como {s.encoding} (recomendado UTF-8)")

    main_src: SourceFile | None
    if main:
        mp = (root / main).resolve()
        if mp not in sources:
            raise ProjectError(f"arquivo principal indicado não existe: {main}")
        main_src = sources[mp]
    else:
        main_src = _choose_main([s for s in sources.values() if _is_main(s)], notes)
    if main_src is None:
        raise ProjectError("nenhum .tex principal (com \\documentclass e \\begin{document})")

    ordered: list[SourceFile] = []
    includes: list[Include] = []
    bib_targets: list[Path] = []
    visiting: set[Path] = set()
    base_dir = main_src.abspath.parent

    def resolve(raw: str, rel_dir: Path, exts: tuple[str, ...]) -> tuple[Path | None, str | None]:
        raw = raw.strip()
        if not raw:
            return None, "inexistente"
        cand = Path(raw)
        if cand.is_absolute():
            return None, "fora da raiz"
        for ext in exts:
            p = rel_dir / (raw + ext if ext and not raw.endswith(ext) else raw)
            if not _within(p, root):
                return None, "fora da raiz"
            if p.is_file():
                return p.resolve(), None
        return None, "inexistente"

    def visit(src: SourceFile) -> None:
        key = src.abspath.resolve()
        visiting.add(key)
        ordered.append(src)
        events: list[tuple[int, str, list[str], Path]] = []
        for cmd in find_commands(src.masked, INCLUDE_CMDS):
            if cmd.mandatory:
                d = src.abspath.parent if cmd.name == "subfile" else base_dir
                events.append((cmd.start, cmd.name, [cmd.mandatory[0].text], d))
        for cmd in find_commands(src.masked, ["import", "subimport"], mandatory=2):
            if len(cmd.mandatory) == 2:
                d = src.abspath.parent if cmd.name == "subimport" else base_dir
                d = d / cmd.mandatory[0].text.strip()
                events.append((cmd.start, cmd.name, [cmd.mandatory[1].text], d))
        for cmd in find_commands(src.masked, ["bibliography", "addbibresource"]):
            if cmd.mandatory:
                parts = [x for x, _ in split_keys(cmd.mandatory[0])]
                events.append((cmd.start, cmd.name, parts, base_dir))
        events.sort(key=lambda e: e[0])
        for offset, kind, raws, d in events:
            for raw in raws:
                if kind in ("bibliography", "addbibresource"):
                    p, prob = resolve(raw, d, (".bib", ""))
                    includes.append(Include(src, offset, raw, kind, p, prob))
                    if p is not None:
                        bib_targets.append(p)
                    continue
                p, prob = resolve(raw, d, (".tex", ""))
                if p is not None and p in visiting:
                    includes.append(Include(src, offset, raw, kind, None, "ciclo"))
                    continue
                includes.append(Include(src, offset, raw, kind, p, prob))
                if p is not None:
                    child = sources.get(p)
                    if child is None and p.suffix != ".tex":
                        child = read_source(p, p.relative_to(root))
                    if child is not None and child not in ordered:
                        visit(child)
        visiting.discard(key)

    visit(main_src)
    reached = {s.abspath.resolve() for s in ordered}
    orphans = [s for k, s in sources.items() if k not in reached]

    if not bib_targets and bib_paths:
        bib_targets = [p.resolve() for p in bib_paths]
        notes.append("nenhum \\bibliography/\\addbibresource encontrado; usando todos os .bib")
    seen: set[Path] = set()
    bibs: list[BibFile] = []
    for p in bib_targets:
        if p in seen:
            continue
        seen.add(p)
        bibs.append(parse_bib(read_source(p, p.relative_to(root))))
    return Project(root, main_src, ordered, orphans, bibs, includes, notes)
