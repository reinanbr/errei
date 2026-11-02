"""Extração de texto limpo com mapa de offsets de volta ao fonte.

Usa ``pylatexenc`` (parsing tolerante, nós com ``pos``/``len``). Cada caractere
emitido guarda o offset original; caracteres sintéticos (placeholders de
citação, ``x`` para matemática inline) apontam para o comando de origem.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from pylatexenc import latexwalker as lw
from pylatexenc import macrospec as ms
from pylatexenc.latex2text import LatexNodes2Text

from errei.latex.source import SourceFile
from errei.model import Location

# ---------------------------------------------------------------- vocabulário
SECTION_LEVELS = {
    "part": -1,
    "chapter": 0,
    "section": 1,
    "subsection": 2,
    "subsubsection": 3,
    "paragraph": 4,
}
CITE_PAREN = {
    "cite",
    "citep",
    "parencite",
    "Parencite",
    "autocite",
    "Autocite",
    "footcite",
    "citealp",
    "citeyearpar",
    "Cite",
}
CITE_TEXT = {"citeonline", "citet", "textcite", "Textcite", "citealt", "Citet", "citeauthoronline"}
CITE_AUTHOR = {"citeauthor", "Citeauthor"}
CITE_YEAR = {"citeyear"}
CITE_APUD = {"apud", "apudonline", "Idem", "Ibidem", "opcit", "passim", "cfcite"}
ALL_CITES = CITE_PAREN | CITE_TEXT | CITE_AUTHOR | CITE_YEAR | CITE_APUD | {"nocite"}
REF_MACROS = {"ref", "eqref", "autoref", "cref", "Cref", "pageref", "nameref", "vref"}
TEXT_MACROS = {
    "emph",
    "textbf",
    "textit",
    "textsl",
    "textsc",
    "underline",
    "textup",
    "textmd",
    "textnormal",
    "mbox",
    "hbox",
    "textrm",
    "textsf",
    "uline",
    "enquote",
    "textsuperscript",
    "textsubscript",
    "MakeUppercase",
    "MakeLowercase",
}
SKIP_MACROS = {
    "label",
    "includegraphics",
    "usepackage",
    "RequirePackage",
    "documentclass",
    "newcommand",
    "renewcommand",
    "providecommand",
    "DeclareMathOperator",
    "newenvironment",
    "renewenvironment",
    "setlength",
    "addtolength",
    "setcounter",
    "vspace",
    "hspace",
    "input",
    "include",
    "subfile",
    "import",
    "bibliography",
    "bibliographystyle",
    "addbibresource",
    "todo",
    "footnote",
    "footnotetext",
    "maketitle",
    "tableofcontents",
    "listoffigures",
    "listoftables",
    "printbibliography",
    "texttt",
    "verb",
    "lstinline",
    "graphicspath",
    "hypersetup",
    "geometry",
    "selectlanguage",
    "pagestyle",
    "thispagestyle",
    "newpage",
    "clearpage",
    "noindent",
    "centering",
    "small",
    "footnotesize",
    "large",
    "Large",
    "normalsize",
    "vfill",
    "hfill",
    "bigskip",
    "medskip",
    "smallskip",
    "onelineskip",
    "pretextual",
    "textual",
    "postextual",
    "imprimircapa",
    "imprimirfolhaderosto",
    "tocprintchapter",
    "titulo",
    "autor",
    "data",
    "instituicao",
    "local",
    "orientador",
    "tipotrabalho",
    "preambulo",
    "title",
    "author",
    "date",
    "thanks",
    "linespread",
    "doublespacing",
    "onehalfspacing",
    "singlespacing",
    "url",
    "nolinkurl",
    "SI",
    "si",
    "num",
    "ang",
    "newacronym",
    "glsadd",
    "makeatletter",
    "makeatother",
    "and",
    "appendix",
    "anexos",
    "apendices",
    "phantomsection",
    "addcontentsline",
    "bibitem",
}
FLOAT_ENVS = {
    "figure",
    "figure*",
    "table",
    "table*",
    "quadro",
    "wrapfigure",
    "wraptable",
    "sidewaysfigure",
    "sidewaystable",
    "algorithm",
}
MATH_ENVS = {
    "equation",
    "equation*",
    "align",
    "align*",
    "gather",
    "gather*",
    "multline",
    "multline*",
    "eqnarray",
    "eqnarray*",
    "displaymath",
    "math",
    "flalign",
    "flalign*",
    "alignat",
    "alignat*",
}
SKIP_ENVS = {
    "verbatim",
    "verbatim*",
    "lstlisting",
    "minted",
    "Verbatim",
    "comment",
    "tikzpicture",
    "tabular",
    "tabular*",
    "tabularx",
    "longtable",
    "thebibliography",
    "filecontents",
    "filecontents*",
    "algorithmic",
}
LIST_ENVS = {"itemize", "enumerate", "description", "alineas", "subalineas", "incisos"}
ABSTRACT_ENVS = {"resumo", "abstract", "resumoumacoluna", "resumoduascolunas"}
QUOTE_ENVS = {"citacao", "quote", "quotation"}

ACCENT_MACROS = {"'", "`", "^", "~", '"', "c", "H", "u", "v", ".", "=", "k", "r", "d", "b"}

_SPECIALS = {
    "~": " ",
    "--": "–",
    "---": "—",
    "``": "“",
    "''": "”",
    "`": "‘",
    "'": "’",
    "&": " ",
    "!`": "¡",
    "?`": "¿",
}


def _context_db() -> Any:
    db = lw.get_default_latex_context_db()
    m = ms.MacroSpec
    e = ms.EnvironmentSpec
    macros = [m(n, "*[[{") for n in (CITE_PAREN | CITE_TEXT | CITE_AUTHOR | CITE_YEAR)]
    macros += [m(n, "[[{{") for n in ("apud", "apudonline")]
    macros += [m(n, "{") for n in ("Idem", "Ibidem", "opcit", "passim", "cfcite", "nocite")]
    macros += [m(n, "*{") for n in REF_MACROS]
    macros += [
        m("caption", "*[{"),
        m("href", "{{"),
        m("todo", "[{"),
        m("url", "{"),
        m("subfile", "{"),
        m("addbibresource", "[{"),
        m("bibliography", "{"),
        m("bibliographystyle", "{"),
        m("includegraphics", "*[[{"),
        m("label", "{"),
        m("SI", "[{{"),
        m("si", "[{"),
        m("num", "[{"),
        m("foreignlanguage", "[{{"),
        m("titulo", "{"),
        m("autor", "{"),
        m("data", "{"),
        m("instituicao", "{"),
        m("local", "{"),
        m("orientador", "[{"),
        m("tipotrabalho", "{"),
        m("preambulo", "{"),
        m("graphicspath", "{"),
        m("hypersetup", "{"),
        m("geometry", "{"),
        m("selectlanguage", "{"),
        m("newacronym", "[{{{"),
        m("enquote", "*{"),
        m("textsuperscript", "{"),
        m("textsubscript", "{"),
        m("uline", "{"),
        m("import", "{{"),
        m("addcontentsline", "{{{"),
        m("bibitem", "[{"),
    ]
    envs = [
        e("otherlanguage", "{"),
        e("otherlanguage*", "{"),
        e("resumo", "["),
        e("resumoumacoluna", "["),
        e("minipage", "[[[{"),
        e("tabular", "[{"),
        e("tabularx", "{{"),
        e("figure", "["),
        e("table", "["),
        e("figure*", "["),
        e("table*", "["),
        e("quadro", "["),
        e("wrapfigure", "[{[{"),
        e("lstlisting", "["),
        e("minted", "[{"),
        e("citacao", "["),
    ]
    db.add_context_category("errei", macros=macros, environments=envs, prepend=True)
    return db


_DB: Any = None
_L2T: Any = None


def _db() -> Any:
    global _DB
    if _DB is None:
        _DB = _context_db()
    return _DB


def _l2t() -> Any:
    global _L2T
    if _L2T is None:
        _L2T = LatexNodes2Text(math_mode="text", strict_latex_spaces=False)
    return _L2T


# ---------------------------------------------------------------- estruturas
@dataclass(frozen=True, slots=True)
class Region:
    kind: str  # heading|caption|list|abstract|quote|env
    name: str
    start: int  # offsets no texto limpo
    end: int
    lang: str


@dataclass(frozen=True, slots=True)
class Section:
    level: int
    title: str
    starred: bool
    src_offset: int
    clean_start: int


@dataclass(frozen=True, slots=True)
class CiteSpan:
    start: int
    end: int
    keys: tuple[str, ...]
    macro: str


@dataclass(slots=True)
class Paragraph:
    source: SourceFile
    clean: CleanText
    start: int
    end: int
    kind: str  # body|heading|caption|item|abstract|quote
    lang: str
    region_name: str = ""

    @property
    def text(self) -> str:
        return self.clean.text[self.start : self.end]

    def src(self, rel: int) -> int:
        """Offset de fonte do caractere ``rel`` (relativo ao parágrafo)."""
        return self.clean.src(self.start + rel)

    def location(self, rel_start: int, rel_end: int | None = None) -> Location:
        s = self.src(rel_start)
        if rel_end is None:
            return self.source.location(s)
        e = self.src(max(rel_start, rel_end - 1)) + 1
        return self.source.location(s, e)

    @property
    def first_line(self) -> int:
        return self.source.line_col(self.src(0))[0]

    def word_count(self) -> int:
        return len(re.findall(r"\w+", self.text))


@dataclass(slots=True)
class CleanText:
    source: SourceFile
    text: str = ""
    offsets: list[int] = field(default_factory=list)
    regions: list[Region] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)
    cites: list[CiteSpan] = field(default_factory=list)
    paragraphs: list[Paragraph] = field(default_factory=list)
    parse_error: str | None = None

    def src(self, clean_idx: int) -> int:
        if not self.offsets:
            return 0
        clean_idx = max(0, min(clean_idx, len(self.offsets) - 1))
        return self.offsets[clean_idx]

    def location(self, start: int, end: int | None = None) -> Location:
        s = self.src(start)
        if end is None:
            return self.source.location(s)
        return self.source.location(s, self.src(max(start, end - 1)) + 1)


class _Emitter:
    def __init__(self, src: SourceFile) -> None:
        self.src = src
        self.buf: list[str] = []
        self.offs: list[int] = []
        self.regions: list[Region] = []
        self.sections: list[Section] = []
        self.cites: list[CiteSpan] = []
        self.lang_stack: list[str] = ["pt"]

    @property
    def pos(self) -> int:
        return len(self.buf)

    def put(self, s: str, offset: int, *, per_char: bool = False) -> None:
        for i, ch in enumerate(s):
            self.buf.append(ch)
            self.offs.append(offset + i if per_char else offset)

    def brk(self, offset: int) -> None:
        self.put("\n\n", offset)

    # -- nós -------------------------------------------------------------
    def nodes(self, nodelist: Any, ctx: str = "text") -> None:
        if not nodelist:
            return
        for node in nodelist:
            if node is not None:
                self.node(node, ctx)

    def node(self, node: Any, ctx: str) -> None:
        if isinstance(node, lw.LatexCharsNode):
            self.chars(node.chars, node.pos)
        elif isinstance(node, lw.LatexGroupNode):
            self.nodes(node.nodelist, ctx)
        elif isinstance(node, lw.LatexSpecialsNode):
            self.put(_SPECIALS.get(node.specials_chars, ""), node.pos)
        elif isinstance(node, lw.LatexMathNode):
            if node.displaytype == "inline":
                self.put("x", node.pos)
            else:
                self.put(" ", node.pos)
        elif isinstance(node, lw.LatexMacroNode):
            self.macro(node, ctx)
        elif isinstance(node, lw.LatexEnvironmentNode):
            self.env(node, ctx)
        # comentários: nada

    def chars(self, chars: str, pos: int) -> None:
        i = 0
        n = len(chars)
        while i < n:
            if chars.startswith("---", i):
                self.put("—", pos + i)
                i += 3
            elif chars.startswith("--", i):
                self.put("–", pos + i)
                i += 2
            elif chars.startswith("``", i) or chars.startswith("''", i):
                self.put("“" if chars[i] == "`" else "”", pos + i)
                i += 2
            else:
                self.buf.append(chars[i])
                self.offs.append(pos + i)
                i += 1

    def _args(self, node: Any) -> list[Any]:
        argd = getattr(node, "nodeargd", None)
        if argd is None or not getattr(argd, "argnlist", None):
            return []
        return list(argd.argnlist)

    @staticmethod
    def _is_brace(arg: Any) -> bool:
        return (
            isinstance(arg, lw.LatexGroupNode) and getattr(arg, "delimiters", ("{", "}"))[0] == "{"
        )

    def _arg_text(self, arg: Any) -> str:
        if arg is None:
            return ""
        return str(self.src.text[arg.pos : arg.pos + arg.len]).strip("{}[] ")

    def macro(self, node: Any, ctx: str) -> None:
        name: str = node.macroname
        args = self._args(node)
        if name in SECTION_LEVELS:
            starred = bool(args and args[0] is not None and getattr(args[0], "chars", "") == "*")
            title_arg = args[-1] if args else None
            self.brk(node.pos)
            start = self.pos
            if title_arg is not None:
                self.node(title_arg, "text")
            title = "".join(self.buf[start:]).strip()
            self.regions.append(Region("heading", name, start, self.pos, self.lang_stack[-1]))
            self.sections.append(Section(SECTION_LEVELS[name], title, starred, node.pos, start))
            self.brk(node.pos)
            return
        if name in ALL_CITES:
            self.cite(node, name, args)
            return
        if name in REF_MACROS:
            self.put("1", node.pos)
            return
        if name == "href":
            if len(args) >= 2 and args[1] is not None:
                self.node(args[1], ctx)
            return
        if name == "foreignlanguage":
            lang = self._arg_text(args[1]) if len(args) > 1 else ""
            self.lang_stack.append(_lang_code(lang))
            if args and args[-1] is not None:
                self.node(args[-1], ctx)
            self.lang_stack.pop()
            return
        if name == "caption":
            if ctx != "float":
                # legenda fora de float (p.ex. \captionof): trata como texto
                pass
            self.brk(node.pos)
            start = self.pos
            if args and args[-1] is not None:
                self.node(args[-1], "text")
            self.regions.append(Region("caption", name, start, self.pos, self.lang_stack[-1]))
            self.brk(node.pos)
            return
        if name in ("par",):
            self.brk(node.pos)
            return
        if name == "item":
            self.brk(node.pos)
            return
        if name == "\\":
            self.put(" ", node.pos)
            return
        if name in ACCENT_MACROS:
            try:
                txt = _l2t().nodelist_to_text([node])
            except Exception:  # pragma: no cover - defensivo
                txt = ""
            self.put(txt[:2], node.pos)
            return
        if name in TEXT_MACROS:
            for a in args:
                if self._is_brace(a):
                    self.node(a, ctx)
            return
        if name in SKIP_MACROS or name in ("begin", "end"):
            return
        if args:
            for a in args:
                if self._is_brace(a):
                    self.node(a, ctx)
            return
        try:
            txt = _l2t().nodelist_to_text([node])
        except Exception:  # pragma: no cover - defensivo
            txt = ""
        if txt and len(txt) <= 4 and not txt.isspace():
            self.put(txt, node.pos)
        elif txt and txt.isspace():
            self.put(" ", node.pos)
        if getattr(node, "macro_post_space", ""):
            self.put(" ", node.pos + node.len - 1)

    def cite(self, node: Any, name: str, args: list[Any]) -> None:
        keys: list[str] = []
        for a in args:
            if self._is_brace(a):
                keys += [k.strip() for k in self._arg_text(a).split(",") if k.strip()]
        if name == "nocite":
            return
        start = self.pos
        if name in CITE_TEXT:
            self.put("Silva (2020)", node.pos)
        elif name in CITE_AUTHOR:
            self.put("Silva", node.pos)
        elif name in CITE_YEAR:
            self.put("2020", node.pos)
        elif name in ("apud", "apudonline"):
            self.put("(SILVA, 2020 apud SOUZA, 2019)", node.pos)
        else:
            self.put("(SILVA, 2020)", node.pos)
        self.cites.append(CiteSpan(start, self.pos, tuple(keys), name))

    def env(self, node: Any, ctx: str) -> None:
        name: str = node.environmentname
        if name == "document":
            self.nodes(node.nodelist, ctx)
            return
        if name in SKIP_ENVS:
            self.put(" ", node.pos)
            return
        if name in MATH_ENVS:
            self.put(" ", node.pos)
            return
        if name in FLOAT_ENVS:
            self.brk(node.pos)
            self._walk_captions(node.nodelist)
            self.brk(node.pos)
            return
        pushed = False
        if name in ("otherlanguage", "otherlanguage*"):
            args = self._args(node)
            lang = self._arg_text(args[0]) if args else ""
            self.lang_stack.append(_lang_code(lang))
            pushed = True
        elif name in ABSTRACT_ENVS:
            args = self._args(node)
            opt = self._arg_text(args[0]) if args and args[0] is not None else ""
            if name == "abstract" or opt.lower() in ("abstract", "resumen", "résumé"):
                self.lang_stack.append("en" if opt.lower() != "resumen" else "es")
                pushed = True
        kind = (
            "abstract"
            if name in ABSTRACT_ENVS
            else "list"
            if name in LIST_ENVS
            else "quote"
            if name in QUOTE_ENVS
            else "env"
        )
        self.brk(node.pos)
        start = self.pos
        self.nodes(node.nodelist, ctx)
        self.regions.append(Region(kind, name, start, self.pos, self.lang_stack[-1]))
        self.brk(node.pos + max(0, node.len - 1))
        if pushed:
            self.lang_stack.pop()

    def _walk_captions(self, nodelist: Any) -> None:
        if not nodelist:
            return
        for n in nodelist:
            if isinstance(n, lw.LatexMacroNode) and n.macroname == "caption":
                self.macro(n, "float")
            elif isinstance(n, lw.LatexEnvironmentNode | lw.LatexGroupNode):
                self._walk_captions(n.nodelist)


def _lang_code(name: str) -> str:
    name = name.strip().lower()
    if name in ("english", "american", "british", "en", "UKenglish".lower(), "USenglish".lower()):
        return "en"
    if name in ("spanish", "es"):
        return "es"
    if name in ("brazil", "brazilian", "portuguese", "portuges", "pt", "pt-br"):
        return "pt"
    return name or "pt"


_PARA_SPLIT = re.compile(r"\n[ \t]*\n\s*")


def extract(src: SourceFile) -> CleanText:
    """Extrai texto limpo de um ``.tex`` (só o corpo, se houver ``document``)."""
    ct = CleanText(src)
    em = _Emitter(src)
    try:
        walker = lw.LatexWalker(src.text, latex_context=_db(), tolerant_parsing=True)
        nodes, _, _ = walker.get_latex_nodes()
        doc = [
            n
            for n in nodes
            if isinstance(n, lw.LatexEnvironmentNode) and n.environmentname == "document"
        ]
        if doc:
            em.nodes(doc[0].nodelist)
        elif re.search(r"\\documentclass", src.masked):
            pass  # preâmbulo sem corpo
        else:
            em.nodes(nodes)
    except Exception as exc:  # parsing realmente impossível: fallback grosseiro
        ct.parse_error = str(exc)
        em = _Emitter(src)
        _fallback(src, em)
    ct.text = "".join(em.buf)
    ct.offsets = em.offs
    ct.regions = em.regions
    ct.sections = em.sections
    ct.cites = em.cites
    ct.paragraphs = _paragraphs(ct)
    return ct


def _fallback(src: SourceFile, em: _Emitter) -> None:
    text = re.sub(r"\\[A-Za-z@]+\*?|[{}$]", lambda m: " " * len(m.group(0)), src.masked)
    em.put(text, 0, per_char=True)


def _paragraphs(ct: CleanText) -> list[Paragraph]:
    out: list[Paragraph] = []
    text = ct.text
    pos = 0
    bounds: list[tuple[int, int]] = []
    for m in _PARA_SPLIT.finditer(text):
        bounds.append((pos, m.start()))
        pos = m.end()
    bounds.append((pos, len(text)))
    for s, e in bounds:
        chunk = text[s:e]
        if not chunk.strip():
            continue
        lead = len(chunk) - len(chunk.lstrip())
        trail = len(chunk) - len(chunk.rstrip())
        s2, e2 = s + lead, e - trail
        kind, lang, rname = "body", "pt", ""
        best: Region | None = None
        for r in ct.regions:
            if r.start <= s2 and e2 <= r.end + 1 and (best is None or r.start >= best.start):
                best = r
        if best is not None:
            lang = best.lang
            rname = best.name
            kind = {
                "heading": "heading",
                "caption": "caption",
                "list": "item",
                "abstract": "abstract",
                "quote": "quote",
            }.get(best.kind, "body")
            # parágrafo comum dentro de ambiente genérico herda o tipo de um ancestral
            if best.kind == "env":
                for r in ct.regions:
                    if (
                        r.kind in ("abstract", "quote", "list")
                        and r.start <= s2
                        and e2 <= r.end + 1
                    ):
                        kind = {"abstract": "abstract", "quote": "quote", "list": "item"}[r.kind]
                        rname = r.name
        out.append(Paragraph(ct.source, ct, s2, e2, kind, lang, rname))
    return out
