"""Supressão de achados: ``% errei: ignore CODE`` e ``[ignore]`` no config."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from pathlib import Path

from errei.latex.source import SourceFile
from errei.model import Finding

_DIRECTIVE = re.compile(r"errei:\s*(ignore-file|ignore)\s+([A-Za-z0-9*_,\s-]+)")


def _codes(s: str) -> set[str]:
    return {c.strip().upper() for c in re.split(r"[,\s]+", s) if c.strip()}


def _match(code: str, patterns: set[str] | list[str]) -> bool:
    code = code.upper()
    return any(fnmatchcase(code, p.upper()) for p in patterns)


@dataclass(slots=True)
class IgnoreIndex:
    lines: dict[tuple[Path, int], set[str]] = field(default_factory=dict)
    files: dict[Path, set[str]] = field(default_factory=dict)
    codes: list[str] = field(default_factory=list)
    paths: list[str] = field(default_factory=list)

    @classmethod
    def build(cls, sources: list[SourceFile], codes: list[str], paths: list[str]) -> IgnoreIndex:
        idx = cls(codes=[c.upper() for c in codes], paths=list(paths))
        for src in sources:
            for c in src.comments:
                m = _DIRECTIVE.search(c.text)
                if not m:
                    continue
                kind, codes_s = m.group(1), _codes(m.group(2))
                if kind == "ignore-file":
                    idx.files.setdefault(src.path, set()).update(codes_s)
                    continue
                line, _ = src.line_col(c.offset)
                idx.lines.setdefault((src.path, line), set()).update(codes_s)
                # comentário sozinho na linha também vale para a linha seguinte
                if not src.line_text(line)[: src.line_col(c.offset)[1] - 1].strip():
                    idx.lines.setdefault((src.path, line + 1), set()).update(codes_s)
        return idx

    def suppressed(self, f: Finding) -> bool:
        if self.codes and _match(f.code, self.codes):
            return True
        loc = f.location
        if loc is None:
            return False
        posix = loc.file.as_posix()
        if any(fnmatchcase(posix, p) for p in self.paths):
            return True
        fcodes = self.files.get(loc.file)
        if fcodes and _match(f.code, fcodes):
            return True
        last = loc.end_line or loc.line
        for line in range(loc.line, min(last, loc.line + 50) + 1):
            lcodes = self.lines.get((loc.file, line))
            if lcodes and _match(f.code, lcodes):
                return True
        return False
