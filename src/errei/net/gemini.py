"""Assistente de IA online opcional (Google Gemini), só para SUGESTÕES no relatório.

Regras de uso (garantidas aqui, não só no prompt):

* Desligado por padrão. Liga apenas com ``--online --ia-online`` (ou ``[ia_online]
  enabled = true`` no config do USUÁRIO; o ``.errei.toml`` do artigo é ignorado, porque
  ligar isso envia trechos do texto a um serviço externo).
* A chave vem do ambiente (``ERREI_GEMINI_KEY``, ``GEMINI_API_KEY``, ``GEMINI_KEY`` ou
  ``GOOGLE_API_KEY``) ou do config do usuário; nunca é gravada em cache, relatório ou log.
* A IA não escreve o artigo: as respostas são JSON com esquema fixo (palavras-chave,
  referências a verificar, orientações) e todo texto é cortado em poucas palavras.
  Nada é aplicado aos arquivos; o usuário lê a orientação e escreve com as próprias
  palavras.
* Referências sugeridas pela IA só aparecem no relatório depois de localizadas em uma
  base bibliográfica aberta (veja ``checkers/nacionais.py``).
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any

from errei.config import Config

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models"
DEFAULT_MODEL = "gemini-flash-lite-latest"  # o mais básico/barato da família
KEY_ENVS = ("ERREI_GEMINI_KEY", "GEMINI_API_KEY", "GEMINI_KEY", "GOOGLE_API_KEY")
MAX_ITEM_WORDS = 25
MAX_ITEMS = 6

SYSTEM = (
    "Você auxilia a revisão de trabalhos acadêmicos brasileiros. Regras obrigatórias: "
    "(1) NUNCA escreva texto para o trabalho: nada de parágrafos, frases prontas, "
    "reescritas ou exemplos de redação. (2) Responda SOMENTE no JSON do esquema, com itens "
    "curtos (no máximo 20 palavras), em forma de orientação ('descreva...', 'indique...') "
    "ou de palavras-chave. (3) Não invente referências: liste só obras que você tem "
    "segurança de que existem, com título exato; todas serão conferidas em bases "
    "bibliográficas e as não localizadas serão descartadas."
)


def api_key(config: Config | None = None) -> str:
    for name in KEY_ENVS:
        v = os.environ.get(name, "").strip()
        if v:
            return v
    if config is not None:
        return str(config.trusted_get("ia_online", "api_key", "") or "").strip()
    return ""


def enabled(config: Config) -> bool:
    """Só o config confiável (usuário/flags) liga a IA online."""
    return bool(config.trusted_get("ia_online", "enabled", False)) and config.online


def curto(text: Any, n: int = MAX_ITEM_WORDS) -> str:
    """Corta em ``n`` palavras; é a trava que impede a IA de entregar texto pronto."""
    words = " ".join(str(text or "").split()).split(" ")
    out = " ".join(words[:n]).strip()
    return out + "…" if len(words) > n else out


def _clean(value: Any, depth: int = 0) -> Any:
    if depth > 4:
        return None
    if isinstance(value, str):
        return curto(value)
    if isinstance(value, list):
        return [_clean(v, depth + 1) for v in value[:MAX_ITEMS]]
    if isinstance(value, dict):
        return {str(k): _clean(v, depth + 1) for k, v in value.items()}
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return None


@dataclass(slots=True)
class Gemini:
    http: Any
    key: str
    model: str = DEFAULT_MODEL
    calls: int = 0
    failures: int = 0
    sent: list[str] = field(default_factory=list)  # descrição do que foi enviado

    def ask(self, prompt: str, schema: dict[str, Any], *, what: str) -> dict[str, Any] | None:
        """Pede uma resposta JSON no ``schema``. ``None`` se a API falhar."""
        payload = {
            "systemInstruction": {"parts": [{"text": SYSTEM}]},
            "contents": [{"role": "user", "parts": [{"text": prompt[:6000]}]}],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 800,
                "responseMimeType": "application/json",
                "responseSchema": schema,
            },
        }
        model = re.sub(r"[^\w.\-]", "", self.model) or DEFAULT_MODEL
        self.calls += 1
        self.sent.append(what)
        res = self.http.post_json(
            f"{ENDPOINT}/{model}:generateContent",
            payload,
            headers={"x-goog-api-key": self.key},
        )
        if res is None or res[0] != 200 or not isinstance(res[1], dict):
            self.failures += 1
            return None
        try:
            text = res[1]["candidates"][0]["content"]["parts"][0]["text"]
            data = json.loads(text)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError):
            self.failures += 1
            return None
        cleaned = _clean(data)
        return cleaned if isinstance(cleaned, dict) else None


def make(config: Config, http: Any) -> Gemini | None:
    if http is None or not enabled(config):
        return None
    key = api_key(config)
    if not key:
        return None
    model = str(config.trusted_get("ia_online", "modelo", "") or DEFAULT_MODEL)
    return Gemini(http, key, model)


# ------------------------------------------------------------------ esquemas
SCHEMA_NACIONAIS = {
    "type": "OBJECT",
    "properties": {
        "consultas": {
            "type": "ARRAY",
            "description": "3 consultas curtas (3 a 6 palavras, em português) para achar "
            "artigos ou livros brasileiros que sustentem a mesma afirmação",
            "items": {"type": "STRING"},
        },
        "referencias": {
            "type": "ARRAY",
            "description": "até 3 obras brasileiras (artigo ou livro) que você tem certeza "
            "de que existem e tratam do tema; deixe vazio se não tiver certeza",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "titulo": {"type": "STRING"},
                    "autores": {"type": "STRING"},
                    "ano": {"type": "INTEGER"},
                    "tipo": {"type": "STRING", "enum": ["artigo", "livro"]},
                },
                "required": ["titulo"],
            },
        },
    },
    "required": ["consultas"],
}

SCHEMA_COMPLETUDE = {
    "type": "OBJECT",
    "properties": {
        "orientacoes": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "elemento": {"type": "STRING"},
                    "itens": {
                        "type": "ARRAY",
                        "description": "2 a 4 orientações curtas do que o autor deve "
                        "escrever nesse elemento, específicas para o tema; sem redigir",
                        "items": {"type": "STRING"},
                    },
                },
                "required": ["elemento", "itens"],
            },
        }
    },
    "required": ["orientacoes"],
}
