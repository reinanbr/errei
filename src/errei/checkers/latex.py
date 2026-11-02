"""Verificador ``latex``: estrutura do projeto e do documento."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import TYPE_CHECKING

from errei.checkers.base import BaseChecker, RunContext
from errei.latex.extract import FLOAT_ENVS, REF_MACROS
from errei.latex.scanner import env_blocks, env_events, find_commands, split_keys
from errei.latex.source import SourceFile
from errei.model import Finding, Rule
from errei.model import Severity as S

if TYPE_CHECKING:
    from errei.project import Project

ABNTEX_CLASSES = {"abntex2"}
# rótulos de seção raramente são todos referenciados; não geram ruído
SECTION_PREFIXES = ("sec:", "subsec:", "ssec:", "cap:", "chap:", "ch:", "part:", "app:", "apx:")


class LatexChecker(BaseChecker):
    name = "latex"
    title = "Projeto e estrutura LaTeX"
    rules = (
        Rule(
            "LATEX-REF-001",
            S.ERRO,
            "Referência cruzada para rótulo inexistente",
            "Um \\ref (ou \\eqref, \\autoref, \\cref…) aponta para um \\label que não existe "
            "no projeto. No PDF aparecerá '??'.",
        ),
        Rule(
            "LATEX-LABEL-001",
            S.ERRO,
            "Rótulo duplicado",
            "O mesmo \\label foi definido mais de uma vez; as referências ficam ambíguas.",
        ),
        Rule(
            "LATEX-LABEL-002",
            S.INFO,
            "Rótulo nunca referenciado",
            "Um \\label não é usado por nenhum \\ref. Não é erro, mas pode indicar figura, "
            "tabela ou seção esquecida no texto.",
        ),
        Rule(
            "LATEX-ENV-001",
            S.ERRO,
            "Ambiente não fechado ou descasado",
            "Um \\begin{...} não tem \\end{...} correspondente (ou vice-versa) no mesmo arquivo.",
        ),
        Rule(
            "LATEX-BRACE-001",
            S.ERRO,
            "Chaves desbalanceadas",
            "O número de '{' e '}' não confere no arquivo (desconsiderando \\{ \\} e comentários).",
        ),
        Rule(
            "LATEX-FLOAT-001",
            S.AVISO,
            "Figura/tabela sem legenda",
            "Figuras, tabelas e quadros devem ter \\caption (ABNT NBR 14724: identificação "
            "na parte superior).",
            "ABNT NBR 14724:2011, 5.8 e 5.9",
        ),
        Rule(
            "LATEX-FLOAT-002",
            S.AVISO,
            "Figura/tabela não citada no texto",
            "Toda ilustração ou tabela deve ser citada no texto, o mais próximo possível do "
            "trecho a que se refere. Sem \\label não é possível citá-la com \\ref.",
            "ABNT NBR 14724:2011, 5.8",
        ),
        Rule(
            "LATEX-TODO-001",
            S.AVISO,
            "Pendência esquecida",
            "Marcador de pendência (TODO, FIXME, XXX, \\todo…) encontrado no fonte.",
        ),
        Rule(
            "LATEX-COMMENT-001",
            S.SUGESTAO,
            "Bloco grande de texto comentado",
            "Várias linhas seguidas comentadas. Considere remover antes da submissão "
            "(fontes LaTeX costumam ser enviados aos periódicos).",
        ),
        Rule(
            "LATEX-LANG-001",
            S.AVISO,
            "Idioma português não configurado",
            "Sem babel/polyglossia com 'brazil'/'brazilian', hifenização e nomes automáticos "
            "(Figura, Tabela, Sumário) ficam em inglês.",
        ),
        Rule(
            "LATEX-CLASS-001",
            S.INFO,
            "Classe diferente de abnTeX2",
            "O documento não usa a classe abntex2. As regras ABNT continuam aplicáveis, mas a "
            "formatação depende do template do periódico.",
        ),
        Rule(
            "LATEX-INPUT-001",
            S.ERRO,
            "Arquivo incluído não encontrado",
            "\\input/\\include/\\bibliography aponta para um arquivo inexistente.",
        ),
        Rule(
            "LATEX-INPUT-002",
            S.ERRO,
            "Inclusão fora da pasta do projeto",
            "Inclusão com caminho absoluto ou que sai da pasta do artigo. Por segurança o "
            "arquivo não foi lido, e o projeto não é portável.",
        ),
        Rule(
            "LATEX-INPUT-003",
            S.ERRO,
            "Inclusão cíclica",
            "Um arquivo inclui (direta ou indiretamente) a si mesmo.",
        ),
        Rule(
            "LATEX-ORPHAN-001",
            S.INFO,
            "Arquivo .tex não incluído",
            "Arquivo .tex da pasta que não é alcançado a partir do principal; foi ignorado "
            "nas análises de texto.",
        ),
        Rule(
            "LATEX-PARSE-001",
            S.INFO,
            "Extração de texto aproximada",
            "O parser LaTeX não conseguiu estruturar o arquivo; a extração de texto usou um "
            "modo aproximado e as posições podem ficar imprecisas.",
        ),
    )

    def run(self, project: Project, ctx: RunContext) -> list[Finding]:
        out: list[Finding] = []
        out += self._includes(project)
        out += self._labels_refs(project)
        for src in project.tex:
            out += self._envs(src)
            out += self._braces(src)
            out += self._todos(src, ctx)
            out += self._comment_blocks(src)
            if project.clean(src).parse_error:
                out.append(
                    self.finding(
                        "LATEX-PARSE-001",
                        f"extração aproximada: {project.clean(src).parse_error}",
                        src=src,
                        start=0,
                    )
                )
        out += self._language_and_class(project)
        for o in project.orphans:
            out.append(
                self.finding(
                    "LATEX-ORPHAN-001",
                    f"{o.path.as_posix()} não é incluído pelo arquivo principal",
                    src=o,
                    start=0,
                    excerpt="",
                )
            )
        return out

    # ------------------------------------------------------------ inclusões
    def _includes(self, project: Project) -> list[Finding]:
        out: list[Finding] = []
        for inc in project.includes:
            if inc.problem is None:
                continue
            code = {
                "inexistente": "LATEX-INPUT-001",
                "fora da raiz": "LATEX-INPUT-002",
                "ciclo": "LATEX-INPUT-003",
            }[inc.problem]
            what = "arquivo .bib" if inc.kind in ("bibliography", "addbibresource") else "arquivo"
            out.append(
                self.finding(
                    code,
                    f"\\{inc.kind}: {what} '{inc.raw}' ({inc.problem})",
                    src=inc.source,
                    start=inc.offset,
                )
            )
        return out

    # ------------------------------------------------------------ rótulos
    def _labels_refs(self, project: Project) -> list[Finding]:
        out: list[Finding] = []
        labels: dict[str, list[tuple[SourceFile, int]]] = defaultdict(list)
        for src, cmd in project.commands(("label",)):
            if cmd.mandatory:
                key = cmd.mandatory[0].text.strip()
                if key and "#" not in key:  # ignora \label dentro de definições de macro
                    labels[key].append((src, cmd.mandatory[0].start))
        refs: dict[str, list[tuple[SourceFile, int]]] = defaultdict(list)
        for src, cmd in project.commands(tuple(REF_MACROS)):
            for arg in cmd.mandatory[:1]:
                for key, off in split_keys(arg):
                    if "#" not in key:
                        refs[key].append((src, off))

        for key, uses in refs.items():
            if key not in labels:
                for src, off in uses:
                    out.append(
                        self.finding(
                            "LATEX-REF-001",
                            f"\\ref{{{key}}} sem \\label correspondente",
                            src=src,
                            start=off,
                            end=off + len(key),
                            suggestion=_close_label(key, list(labels)),
                        )
                    )
        for key, defs in labels.items():
            if len(defs) > 1:
                first = defs[0][0].location(defs[0][1])
                for src, off in defs[1:]:
                    out.append(
                        self.finding(
                            "LATEX-LABEL-001",
                            f"\\label{{{key}}} duplicado (primeira definição em {first})",
                            src=src,
                            start=off,
                            end=off + len(key),
                        )
                    )

        float_labels: set[str] = set()
        for src in project.tex:
            for blk in env_blocks(src.masked, FLOAT_ENVS):
                body = src.masked[blk.body_start : blk.body_end]
                kind = (
                    "tabela"
                    if "table" in blk.name
                    else ("quadro" if blk.name == "quadro" else "figura")
                )
                if not list(find_commands(body, ["caption", "captionof"])):
                    out.append(
                        self.finding(
                            "LATEX-FLOAT-001",
                            f"{kind} sem \\caption",
                            src=src,
                            start=blk.start,
                            end=blk.body_start,
                            suggestion="adicione \\caption{...} antes do "
                            "conteúdo (ABNT: título na parte superior)",
                        )
                    )
                lbls = [
                    c.mandatory[0].text.strip()
                    for c in find_commands(body, ["label"])
                    if c.mandatory
                ]
                float_labels.update(lbls)
                if not lbls:
                    out.append(
                        self.finding(
                            "LATEX-FLOAT-002",
                            f"{kind} sem \\label: não pode ser citada no texto",
                            src=src,
                            start=blk.start,
                            end=blk.body_start,
                        )
                    )
                elif not any(lb in refs for lb in lbls):
                    out.append(
                        self.finding(
                            "LATEX-FLOAT-002",
                            f"{kind} '{lbls[0]}' nunca é citada no texto (\\ref)",
                            src=src,
                            start=blk.start,
                            end=blk.body_start,
                            suggestion=f"cite com \\ref{{{lbls[0]}}} no texto",
                        )
                    )
        for key, defs in labels.items():
            if key not in refs and key not in float_labels and not key.startswith(SECTION_PREFIXES):
                src, off = defs[0]
                out.append(
                    self.finding(
                        "LATEX-LABEL-002",
                        f"\\label{{{key}}} nunca referenciado",
                        src=src,
                        start=off,
                        end=off + len(key),
                    )
                )
        return out

    # ------------------------------------------------------------ ambientes
    def _envs(self, src: SourceFile) -> list[Finding]:
        out: list[Finding] = []
        stack: list[tuple[str, int]] = []
        for ev in env_events(src.masked):
            if ev.kind == "begin":
                stack.append((ev.name, ev.start))
                continue
            if stack and stack[-1][0] == ev.name:
                stack.pop()
                continue
            names = [n for n, _ in stack]
            if ev.name in names:
                while stack and stack[-1][0] != ev.name:
                    n, off = stack.pop()
                    out.append(
                        self.finding(
                            "LATEX-ENV-001",
                            f"\\begin{{{n}}} sem \\end{{{n}}} (fechado por \\end{{{ev.name}}})",
                            src=src,
                            start=off,
                            end=off + len(n) + 8,
                        )
                    )
                stack.pop()
            else:
                out.append(
                    self.finding(
                        "LATEX-ENV-001",
                        f"\\end{{{ev.name}}} sem \\begin{{{ev.name}}}",
                        src=src,
                        start=ev.start,
                        end=ev.end,
                    )
                )
        for n, off in stack:
            out.append(
                self.finding(
                    "LATEX-ENV-001",
                    f"\\begin{{{n}}} sem \\end{{{n}}}",
                    src=src,
                    start=off,
                    end=off + len(n) + 8,
                )
            )
        return out

    def _braces(self, src: SourceFile) -> list[Finding]:
        text = src.masked
        depth = 0
        opens: list[int] = []
        i = 0
        n = len(text)
        while i < n:
            c = text[i]
            if c == "\\":
                i += 2
                continue
            if c == "{":
                opens.append(i)
                depth += 1
            elif c == "}":
                if not opens:
                    return [
                        self.finding(
                            "LATEX-BRACE-001",
                            "'}' sem '{' correspondente",
                            src=src,
                            start=i,
                            end=i + 1,
                        )
                    ]
                opens.pop()
            i += 1
        if opens:
            return [
                self.finding(
                    "LATEX-BRACE-001",
                    "'{' sem '}' correspondente",
                    src=src,
                    start=opens[-1],
                    end=opens[-1] + 1,
                )
            ]
        return []

    # ------------------------------------------------------------ pendências
    def _todos(self, src: SourceFile, ctx: RunContext) -> list[Finding]:
        out: list[Finding] = []
        markers = [str(m) for m in ctx.config.get("latex", "todo_markers", ["TODO", "FIXME"])]
        rx = re.compile(r"\b(" + "|".join(re.escape(m) for m in markers) + r")\b")
        for c in src.comments:
            if "errei:" in c.text:
                continue
            m = rx.search(c.text)
            if m:
                start = c.offset + 1 + m.start()
                out.append(
                    self.finding(
                        "LATEX-TODO-001",
                        f"pendência em comentário: {c.text.strip()[:80]}",
                        src=src,
                        start=start,
                        end=c.offset + 1 + len(c.text),
                        excerpt="%" + c.text,
                    )
                )
        for cmd in find_commands(src.masked, ["todo", "missingfigure", "TODO", "fixme"]):
            what = cmd.mandatory[0].text.strip()[:80] if cmd.mandatory else ""
            out.append(
                self.finding(
                    "LATEX-TODO-001", f"\\{cmd.name}: {what}", src=src, start=cmd.start, end=cmd.end
                )
            )
        for m in rx.finditer(src.masked):
            if src.masked[max(0, m.start() - 1)] == "\\":
                continue
            out.append(
                self.finding(
                    "LATEX-TODO-001",
                    f"marcador '{m.group(1)}' no texto",
                    src=src,
                    start=m.start(),
                    end=m.end(),
                )
            )
        return out

    def _comment_blocks(self, src: SourceFile) -> list[Finding]:
        out: list[Finding] = []
        run_start: int | None = None
        run_len = 0
        prev_line = -10
        for c in src.comments:
            line, col = src.line_col(c.offset)
            whole_line = not src.line_text(line)[: col - 1].strip()
            substantive = len(c.text.strip()) > 3 and "errei:" not in c.text
            if whole_line and substantive and line == prev_line + 1 and run_start is not None:
                run_len += 1
            elif whole_line and substantive:
                if run_start is not None and run_len >= 5:
                    out.append(self._block(src, run_start, run_len))
                run_start, run_len = c.offset, 1
            else:
                if run_start is not None and run_len >= 5:
                    out.append(self._block(src, run_start, run_len))
                run_start, run_len = None, 0
            prev_line = line
        if run_start is not None and run_len >= 5:
            out.append(self._block(src, run_start, run_len))
        return out

    def _block(self, src: SourceFile, start: int, nlines: int) -> Finding:
        line, _ = src.line_col(start)
        return self.finding(
            "LATEX-COMMENT-001",
            f"{nlines} linhas seguidas comentadas",
            src=src,
            start=start,
            end=start + 1,
            excerpt=src.line_text(line).strip(),
        )

    # ------------------------------------------------------------ idioma/classe
    def _language_and_class(self, project: Project) -> list[Finding]:
        out: list[Finding] = []
        dc = project.documentclass()
        pkgs = project.packages()
        langs_ok = False
        cls_opts = dc[1] if dc else ""
        if re.search(r"\bbrazil(ian)?\b", cls_opts):
            langs_ok = True
        babel = pkgs.get("babel")
        if babel and re.search(r"\bbrazil(ian)?\b", babel[0]):
            langs_ok = True
        if "polyglossia" in pkgs:
            for src, cmd in project.commands(("setmainlanguage", "setdefaultlanguage")):
                full = src.masked[cmd.start : cmd.end]
                if "portuguese" in full or "brazil" in full:
                    langs_ok = True
        if not langs_ok and dc is not None:
            out.append(
                self.finding(
                    "LATEX-LANG-001",
                    "pacote de idioma pt-BR ausente",
                    src=dc[2],
                    start=dc[3],
                    suggestion="\\usepackage[brazil]{babel} (ou opção 'brazil' na classe abntex2)",
                )
            )
        if dc is not None and dc[0] not in ABNTEX_CLASSES:
            out.append(
                self.finding(
                    "LATEX-CLASS-001", f"classe '{dc[0]}' (não é abntex2)", src=dc[2], start=dc[3]
                )
            )
        return out


def _close_label(key: str, labels: list[str]) -> str | None:
    import difflib

    match = difflib.get_close_matches(key, labels, n=1, cutoff=0.75)
    return f"você quis dizer '{match[0]}'?" if match else None
