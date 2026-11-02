"""Scanner leve sobre o texto mascarado: comandos com argumentos e ambientes.

Usado pelas regras estruturais, que precisam de linha:coluna exatas e de
tolerância total a LaTeX malformado.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Arg:
    text: str
    start: int  # offset do conteúdo (após a chave/colchete de abertura)
    end: int
    optional: bool


@dataclass(frozen=True, slots=True)
class Command:
    name: str
    star: bool
    start: int  # offset da barra invertida
    end: int  # offset após o último argumento
    args: tuple[Arg, ...]

    @property
    def mandatory(self) -> list[Arg]:
        return [a for a in self.args if not a.optional]

    @property
    def optional(self) -> list[Arg]:
        return [a for a in self.args if a.optional]


def _match_group(text: str, i: int, open_ch: str, close_ch: str) -> int:
    """Retorna o índice do fechamento correspondente a ``text[i] == open_ch`` ou -1."""
    depth = 0
    n = len(text)
    j = i
    while j < n:
        c = text[j]
        if c == "\\":
            j += 2
            continue
        if c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                return j
        elif open_ch == "[" and c == "{":
            # colchetes podem conter grupos com ']' dentro
            k = _match_group(text, j, "{", "}")
            if k == -1:
                return -1
            j = k
        j += 1
    return -1


def _skip_ws(text: str, i: int) -> int:
    """Pula espaços, mas no máximo uma quebra de linha (linha em branco encerra args)."""
    newlines = 0
    n = len(text)
    while i < n and text[i] in " \t\n":
        if text[i] == "\n":
            newlines += 1
            if newlines > 1:
                break
        i += 1
    return i


def parse_args(
    text: str, pos: int, max_mandatory: int, max_optional: int = 3
) -> tuple[list[Arg], int]:
    """Lê argumentos ``[..]``/``{..}`` a partir de ``pos``."""
    args: list[Arg] = []
    mand = 0
    opt = 0
    i = pos
    while mand < max_mandatory:
        j = _skip_ws(text, i)
        if j >= len(text):
            break
        c = text[j]
        if c == "[" and opt < max_optional and mand == 0:
            k = _match_group(text, j, "[", "]")
            if k == -1:
                break
            args.append(Arg(text[j + 1 : k], j + 1, k, True))
            opt += 1
            i = k + 1
        elif c == "{":
            k = _match_group(text, j, "{", "}")
            if k == -1:
                break
            args.append(Arg(text[j + 1 : k], j + 1, k, False))
            mand += 1
            i = k + 1
        else:
            break
    return args, i


def find_commands(
    text: str, names: Iterable[str], *, mandatory: int = 1, optional: int = 3
) -> Iterator[Command]:
    names = sorted(set(names), key=len, reverse=True)
    if not names:
        return
    pattern = re.compile(r"\\(" + "|".join(re.escape(n) for n in names) + r")(?![A-Za-z@])(\*?)")
    for m in pattern.finditer(text):
        # ignora \\cite (barra escapada)
        bs = 0
        k = m.start() - 1
        while k >= 0 and text[k] == "\\":
            bs += 1
            k -= 1
        if bs % 2 == 1:
            continue
        args, end = parse_args(text, m.end(), mandatory, optional)
        yield Command(m.group(1), bool(m.group(2)), m.start(), end, tuple(args))


@dataclass(frozen=True, slots=True)
class EnvEvent:
    kind: str  # "begin" | "end"
    name: str
    start: int
    end: int


_ENV_RE = re.compile(r"\\(begin|end)\s*\{([^{}]+)\}")


def env_events(text: str) -> list[EnvEvent]:
    return [
        EnvEvent(m.group(1), m.group(2).strip(), m.start(), m.end()) for m in _ENV_RE.finditer(text)
    ]


@dataclass(frozen=True, slots=True)
class EnvBlock:
    name: str
    start: int  # offset do \begin
    body_start: int
    body_end: int
    end: int  # offset após \end{...}


def env_blocks(text: str, names: Iterable[str] | None = None) -> list[EnvBlock]:
    """Blocos de ambiente bem-formados (pareamento por pilha)."""
    wanted = set(names) if names is not None else None
    stack: list[EnvEvent] = []
    out: list[EnvBlock] = []
    for ev in env_events(text):
        if ev.kind == "begin":
            stack.append(ev)
            continue
        # procura o begin correspondente mais próximo
        for idx in range(len(stack) - 1, -1, -1):
            if stack[idx].name == ev.name:
                b = stack[idx]
                del stack[idx:]
                if wanted is None or b.name in wanted:
                    out.append(EnvBlock(b.name, b.start, b.end, ev.start, ev.end))
                break
    out.sort(key=lambda b: b.start)
    return out


def split_keys(arg: Arg) -> list[tuple[str, int]]:
    """Divide ``{a, b,c}`` em chaves com offsets."""
    out: list[tuple[str, int]] = []
    for m in re.finditer(r"[^,\s][^,]*", arg.text):
        key = m.group(0).strip()
        if key:
            out.append((key, arg.start + m.start()))
    return out
