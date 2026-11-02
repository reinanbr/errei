"""``errei doctor``: verificação de dependências e ambiente."""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

from rich.console import Console
from rich.markup import escape
from rich.table import Table

from errei.config import cache_dir

HUNSPELL_DIRS = ("/usr/share/hunspell", "/usr/share/myspell", "/usr/share/myspell/dicts")


def _has(mod: str) -> bool:
    return importlib.util.find_spec(mod) is not None


def java_version() -> str | None:
    java = shutil.which("java")
    if not java:
        return None
    try:
        res = subprocess.run(
            [java, "-version"], capture_output=True, text=True, timeout=15, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    first = (res.stderr or res.stdout).splitlines()
    return first[0] if first else "java (versão desconhecida)"


def hunspell_ptbr() -> Path | None:
    for d in HUNSPELL_DIRS:
        p = Path(d) / "pt_BR.dic"
        if p.is_file():
            return p
    return None


def languagetool_cached() -> Path | None:
    from errei.text.languagetool import cached_server

    return cached_server()


def run_doctor(*, download: bool = False, online: bool = False) -> int:
    console = Console(stderr=False, highlight=False)
    t = Table(title="errei doctor", show_lines=False)
    t.add_column("item")
    t.add_column("estado")
    t.add_column("detalhe", style="dim")
    problems = 0

    def row(item: str, ok: bool | None, detail: str) -> None:
        nonlocal problems
        state = "[green]ok[/]" if ok else ("[yellow]opcional[/]" if ok is None else "[red]falta[/]")
        if ok is False:
            problems += 1
        t.add_row(item, state, detail)

    row("Python", sys.version_info >= (3, 10), sys.version.split()[0])
    for mod, extra, what in (
        ("httpx", "online", "checagens online"),
        ("rapidfuzz", "online", "comparação aproximada de títulos"),
        ("language_tool_python", "ptbr", "gramática via LanguageTool"),
        ("spellchecker", "ptbr", "ortografia (fallback)"),
        ("pypdf", "plagio", "PDFs no corpus local"),
    ):
        row(
            escape(f"extra [{extra}]: {mod}"),
            True if _has(mod) else None,
            what if _has(mod) else f"pip install 'errei[{extra}]'",
        )
    jv = java_version()
    row("Java (LanguageTool)", True if jv else None, jv or "instale um JRE ≥ 17")
    lt = languagetool_cached()
    if lt is None and download and jv and _has("language_tool_python"):
        console.print(
            "[yellow]Baixando o servidor LanguageTool (~250 MB) para "
            "~/.cache/language_tool_python …[/]"
        )
        try:
            import language_tool_python

            tool = language_tool_python.LanguageTool("pt-BR")
            tool.close()
            lt = languagetool_cached()
        except Exception as exc:  # pragma: no cover - depende de rede
            console.print(f"[red]falha ao baixar/iniciar o LanguageTool: {exc}[/]")
    row(
        "Servidor LanguageTool",
        True if lt else None,
        str(lt) if lt else "ausente — rode 'errei doctor --download' (requer rede)",
    )
    from errei import citecheck

    mreason = citecheck.unavailable_reason()
    row(
        "Modelo errei-cita (citações)",
        True if mreason is None else None,
        str(citecheck.model_dir()) if mreason is None else mreason,
    )
    try:
        import reportlab  # noqa: F401

        row("Relatório PDF (reportlab)", True, "ok")
    except ModuleNotFoundError:
        row("Relatório PDF (reportlab)", None, "pip install 'errei[pdf]'")
    from errei.net import gemini

    row(
        "IA online (Gemini, --ia-online)",
        True if gemini.api_key() else None,
        "chave encontrada" if gemini.api_key() else f"opcional: defina {gemini.KEY_ENVS[1]}",
    )
    row(
        "Google Books (livros nacionais)",
        True if os.environ.get("GOOGLE_BOOKS_API_KEY") else None,
        "chave encontrada"
        if os.environ.get("GOOGLE_BOOKS_API_KEY")
        else "opcional: GOOGLE_BOOKS_API_KEY (sem ela, usa a Open Library)",
    )
    hs = hunspell_ptbr()
    row(
        "hunspell pt_BR",
        True if hs else None,
        str(hs) if hs else "ausente (ex.: apt install hunspell-pt-br); usa pyspellchecker",
    )
    cd = cache_dir()
    row("Cache", True, str(cd))
    if online:
        try:
            import httpx

            r = httpx.get("https://api.crossref.org/works?rows=0", timeout=10)
            row("Rede: Crossref", r.status_code == 200, f"HTTP {r.status_code}")
            r = httpx.get("https://api.openalex.org/works?per-page=1", timeout=10)
            row("Rede: OpenAlex", r.status_code == 200, f"HTTP {r.status_code}")
        except Exception as exc:
            row("Rede", False, str(exc))
    console.print(t)
    return 2 if problems else 0
