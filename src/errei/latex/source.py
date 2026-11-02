"""Arquivo-fonte com índice de linhas e versão mascarada (sem comentários/verbatim)."""

from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass, field
from pathlib import Path

from errei.model import Location

VERBATIM_ENVS = ("verbatim", "verbatim*", "lstlisting", "minted", "Verbatim", "comment")
_VERB_ENV_RE = re.compile(
    r"\\begin\{(" + "|".join(re.escape(e) for e in VERBATIM_ENVS) + r")\}(.*?)\\end\{\1\}",
    re.DOTALL,
)
_VERB_CMD_RE = re.compile(r"\\(?:verb|lstinline)\*?([^\w\s{])(.*?)\1")


@dataclass(frozen=True, slots=True)
class Comment:
    offset: int  # offset do caractere '%'
    text: str  # sem o '%'


def _blank(s: str) -> str:
    """Troca tudo exceto quebras de linha por espaços (preserva offsets)."""
    return re.sub(r"[^\n]", " ", s)


@dataclass(slots=True)
class SourceFile:
    """Um arquivo do projeto (``.tex`` ou ``.bib``) lido em memória."""

    path: Path  # relativo à raiz
    abspath: Path
    text: str
    encoding: str = "utf-8"
    _line_starts: list[int] = field(default_factory=list, repr=False)
    _masked: str | None = field(default=None, repr=False)
    _comments: list[Comment] | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        starts = [0]
        for m in re.finditer("\n", self.text):
            starts.append(m.end())
        self._line_starts = starts

    # -- posições ---------------------------------------------------------
    def line_col(self, offset: int) -> tuple[int, int]:
        offset = max(0, min(offset, len(self.text)))
        idx = bisect_right(self._line_starts, offset) - 1
        return idx + 1, offset - self._line_starts[idx] + 1

    def location(self, start: int, end: int | None = None) -> Location:
        line, col = self.line_col(start)
        if end is None:
            return Location(self.path, line, col)
        eline, ecol = self.line_col(max(start, end - 1))
        return Location(self.path, line, col, eline, ecol + 1)

    def line_text(self, line: int) -> str:
        if line < 1 or line > len(self._line_starts):
            return ""
        start = self._line_starts[line - 1]
        end = self._line_starts[line] - 1 if line < len(self._line_starts) else len(self.text)
        return self.text[start:end]

    @property
    def line_count(self) -> int:
        return len(self._line_starts)

    # -- máscara ----------------------------------------------------------
    def _build_mask(self) -> None:
        chars = list(self.text)
        comments: list[Comment] = []
        text = self.text
        # 1) verbatim
        for m in _VERB_ENV_RE.finditer(text):
            s, e = m.start(2), m.end(2)
            chars[s:e] = _blank(text[s:e])
        for m in _VERB_CMD_RE.finditer(text):
            s, e = m.start(2), m.end(2)
            chars[s:e] = _blank(text[s:e])
        # 2) comentários: '%' não escapado (número par de barras antes)
        masked_so_far = "".join(chars)
        i = 0
        n = len(masked_so_far)
        while i < n:
            ch = masked_so_far[i]
            if ch == "%":
                j = i - 1
                slashes = 0
                while j >= 0 and masked_so_far[j] == "\\":
                    slashes += 1
                    j -= 1
                if slashes % 2 == 0:
                    end = masked_so_far.find("\n", i)
                    end = n if end == -1 else end
                    comments.append(Comment(i, text[i + 1 : end]))
                    for k in range(i, end):
                        chars[k] = " "
                    i = end
                    continue
            i += 1
        self._masked = "".join(chars)
        self._comments = comments

    @property
    def masked(self) -> str:
        """Texto com comentários e conteúdo verbatim trocados por espaços."""
        if self._masked is None:
            self._build_mask()
        assert self._masked is not None
        return self._masked

    @property
    def comments(self) -> list[Comment]:
        if self._comments is None:
            self._build_mask()
        assert self._comments is not None
        return self._comments

    def excerpt(self, start: int, end: int, limit: int = 160) -> str:
        from errei.model import clip

        return clip(self.text[start:end], limit)


MAX_FILE_BYTES = 5 * 1024 * 1024


def read_source(abspath: Path, relpath: Path) -> SourceFile:
    raw = abspath.read_bytes()[:MAX_FILE_BYTES]
    try:
        return SourceFile(relpath, abspath, raw.decode("utf-8-sig"), "utf-8")
    except UnicodeDecodeError:
        return SourceFile(relpath, abspath, raw.decode("latin-1"), "latin-1")
