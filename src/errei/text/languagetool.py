"""Integração opcional com o LanguageTool local (``language_tool_python``).

Nunca dispara download implicitamente: só usa o servidor se ele já estiver no
cache (``errei doctor --download``). O servidor roda localmente (Java), em
loopback; nenhum texto sai da máquina.
"""

from __future__ import annotations

import os
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DISABLED_RULES = {
    "WHITESPACE_RULE",
    "COMMA_PARENTHESIS_WHITESPACE",
    "UPPERCASE_SENTENCE_START",
    "PUNCTUATION_PARAGRAPH_END",
    "DOUBLE_PUNCTUATION",
    "TYPOGRAPHY_QUOTES",
    "PT_UNPAIRED_BRACKETS",
    "UNPAIRED_BRACKETS",
    "PARENTHESIS_SPACE",
    "HYPHEN_TO_EN",
    "PT_WORDINESS_REPLACE_APUD",
}

_lock = threading.Lock()
_tool: Any = None
_error: str | None = None


@dataclass(frozen=True, slots=True)
class LTMatch:
    offset: int
    length: int
    rule_id: str
    category: str
    issue_type: str
    message: str
    replacements: tuple[str, ...]


def download_dir() -> Path:
    env = os.environ.get("LTP_PATH")
    if env:
        return Path(env)
    return Path.home() / ".cache" / "language_tool_python"


def cached_server() -> Path | None:
    base = download_dir()
    if base.is_dir():
        found = sorted(p for p in base.glob("LanguageTool-*") if p.is_dir())
        if found:
            return found[-1]
    return None


def unavailable_reason() -> str | None:
    """None se o LanguageTool pode ser usado; senão o motivo (pt-BR)."""
    if os.environ.get("ERREI_NO_LANGUAGETOOL"):
        return "LanguageTool desativado (ERREI_NO_LANGUAGETOOL)"
    try:
        import language_tool_python  # noqa: F401
    except ModuleNotFoundError:
        return "instale o extra: pip install 'errei[ptbr]'"
    if not shutil.which("java"):
        return "Java não encontrado (necessário para o LanguageTool)"
    if cached_server() is None:
        return "servidor LanguageTool não baixado; rode 'errei doctor --download'"
    return None


def get_tool() -> Any:
    """Instância compartilhada (inicia a JVM uma vez por processo)."""
    global _tool, _error
    with _lock:
        if _tool is not None or _error is not None:
            if _error:
                raise RuntimeError(_error)
            return _tool
        try:
            import language_tool_python

            _tool = language_tool_python.LanguageTool(
                "pt-BR", config={"cacheSize": 1000, "pipelineCaching": True}
            )
            _tool.disabled_rules = set(DISABLED_RULES)
        except Exception as exc:  # pragma: no cover - depende do ambiente
            _error = f"falha ao iniciar o LanguageTool: {exc}"
            raise RuntimeError(_error) from exc
        return _tool


def check(text: str) -> list[LTMatch]:
    tool = get_tool()
    out = []
    for m in tool.check(text):
        out.append(
            LTMatch(
                int(m.offset),
                int(getattr(m, "error_length", None) or getattr(m, "errorLength", None) or 0),
                str(getattr(m, "rule_id", None) or getattr(m, "ruleId", "")),
                str(getattr(m, "category", "")),
                str(getattr(m, "rule_issue_type", None) or getattr(m, "ruleIssueType", "")),
                str(m.message),
                tuple(str(r) for r in (m.replacements or [])[:3]),
            )
        )
    return out
