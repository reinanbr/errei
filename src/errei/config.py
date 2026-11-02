"""Configuração: padrões ← ~/.config/errei/config.toml ← <projeto>/.errei.toml ← flags."""

from __future__ import annotations

import copy
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

PROJECT_CONFIG = ".errei.toml"

DEFAULTS: dict[str, Any] = {
    "online": False,
    "email": "",
    "fail_on": "error",
    "main": "",
    "jobs": 0,
    "checkers": {"only": [], "skip": []},
    "ignore": {"codes": [], "paths": []},
    "latex": {"todo_markers": ["TODO", "FIXME", "XXX", "REVISAR"]},
    "refs": {"require_doi_types": ["article"], "match_threshold": 85},
    "abnt": {"resumo_min": 150, "resumo_max": 250, "keywords_min": 3, "keywords_max": 5},
    "ptbr": {
        "languagetool": True,
        "spellcheck": True,
        "dict": ".errei-dict.txt",
        "max_sentence_words": 40,
        "max_paragraph_words": 200,
        "repeat_window": 30,
        "genero": "artigo",
    },
    "escrita": {},
    "plagio": {
        "corpus": [],
        "shingle": 8,
        "threshold": 0.35,
        "online_queries": 8,
    },
    "ia": {"min_words": 60, "threshold": 0.6, "detector": ""},
    "periodico": {"qualis_csv": "", "qualis_data": "", "periodico": "", "area": ""},
    "completude": {"tipo": "auto"},
    "todo": {"nivel": "a1"},
    "nacionais": {"enabled": True, "max_refs": 8, "max_sugestoes": 3},
    # IA online (Gemini): só vale no config do USUÁRIO ou em flags, nunca no .errei.toml
    "ia_online": {"enabled": False, "modelo": "", "api_key": ""},
}

TEMPLATE = """\
# Configuração do errei para este artigo. Todas as chaves são opcionais.
# Documentação: errei explain --list

# Habilita checagens que usam rede (Crossref, OpenAlex, Semantic Scholar, arXiv).
online = false
# E-mail para o "polite pool" do Crossref/OpenAlex (opcional).
email = ""
# Quando sair com código 1: "error", "warning" ou "never".
fail_on = "error"
# Arquivo .tex principal (detectado automaticamente se vazio).
main = ""

[checkers]
only = []   # ex.: ["latex", "refs", "abnt"]
skip = []

[ignore]
codes = []  # ex.: ["PTBR-PASSIVA-001", "IA-*"]
paths = []  # globs relativos, ex.: ["apendices/*.tex"]

[abnt]
resumo_min = 150
resumo_max = 250

[ptbr]
languagetool = true
dict = ".errei-dict.txt"   # um termo por linha
max_sentence_words = 40

[plagio]
corpus = []   # pastas/arquivos com .txt, .tex, .md ou .pdf para comparação local
threshold = 0.35

[ia]
detector = ""  # adapter externo opcional "modulo:Classe" (desligado)

[periodico]
qualis_csv = ""    # CSV exportado da Plataforma Sucupira
qualis_data = ""   # data de referência do CSV, ex.: "2025-07-01"
periodico = ""     # "ISSN 1234-5678" ou título
area = ""          # área de avaliação, ex.: "CIÊNCIA DA COMPUTAÇÃO"

[completude]
tipo = "auto"      # artigo | monografia | tcc | dissertacao | tese

[todo]
nivel = "a1"       # lista de afazeres: tcc | mestrado | doutorado | a1 (Scopus ≥ p92 / A1–A2)

[nacionais]        # com --online: obras brasileiras para citações estrangeiras
enabled = true
max_refs = 8

# [ia_online] (Gemini) é ignorado aqui por segurança: configure em
# ~/.config/errei/config.toml ou use --ia-online com GEMINI_API_KEY no ambiente.
"""


class ConfigError(Exception):
    """Erro de configuração (leva a exit code 2)."""


def _deep_merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def user_config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "errei" / "config.toml"


def cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "errei"


def _load_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as fh:
            data: dict[str, Any] = tomllib.load(fh)
            return data
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"configuração inválida em {path}: {exc}") from exc


@dataclass(slots=True)
class Config:
    data: dict[str, Any] = field(default_factory=lambda: copy.deepcopy(DEFAULTS))
    sources: list[Path] = field(default_factory=list)
    # padrões + config do usuário + flags, SEM o .errei.toml do projeto (que pode vir de
    # terceiros). Use para opções que carregam código ou saem da máquina.
    trusted: dict[str, Any] = field(default_factory=lambda: copy.deepcopy(DEFAULTS))

    @classmethod
    def load(
        cls,
        root: Path,
        overrides: dict[str, Any] | None = None,
        *,
        use_user_config: bool = True,
    ) -> Config:
        data = copy.deepcopy(DEFAULTS)
        trusted = copy.deepcopy(DEFAULTS)
        sources: list[Path] = []
        user = user_config_path()
        if use_user_config and user.is_file():
            loaded = _load_toml(user)
            data = _deep_merge(data, loaded)
            trusted = _deep_merge(trusted, loaded)
            sources.append(user)
        project = root / PROJECT_CONFIG
        if project.is_file():
            data = _deep_merge(data, _load_toml(project))
            sources.append(project)
        if overrides:
            data = _deep_merge(data, overrides)
            trusted = _deep_merge(trusted, overrides)
        return cls(data=data, sources=sources, trusted=trusted)

    def trusted_get(self, section: str, key: str, default: Any = None) -> Any:
        value = self.trusted.get(section, {})
        return value.get(key, default) if isinstance(value, dict) else default

    def section(self, name: str) -> dict[str, Any]:
        value = self.data.get(name, {})
        return value if isinstance(value, dict) else {}

    def get(self, section: str, key: str, default: Any = None) -> Any:
        return self.section(section).get(key, default)

    @property
    def online(self) -> bool:
        return bool(self.data.get("online", False))

    @property
    def email(self) -> str:
        return str(self.data.get("email") or "")
