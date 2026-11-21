"""Verificação opcional com o Claude Code (CLI ``claude``), só para INDICADORES no relatório.

Regras de uso (garantidas aqui, não só no prompt):

* **Não é a opção nativa.** Fica desligado por padrão e nunca é o primeiro recurso: os
  verificadores fazem tudo localmente e com bases abertas, e o errei funciona por inteiro
  sem ele. Liga só com ``--online --ia-claude`` (ou ``[ia_claude] enabled = true`` no
  config do USUÁRIO). O ``.errei.toml`` do artigo é ignorado, porque ligar isso envia
  trechos do texto a um serviço externo e executa um programa.
* **Roda isolado.** O diretório de trabalho é uma pasta temporária vazia (o Claude Code não
  vê os arquivos do artigo), só as ferramentas ``WebSearch`` e ``WebFetch`` existem na
  sessão, nada pede permissão (o que pedir é negado), sem servidores MCP, sem hooks,
  plugins, skills ou CLAUDE.md (``--safe-mode``), sem gravar a sessão, com tempo e
  orçamento limitados.
* **Só o necessário é enviado**: a frase que faz a citação e os metadados das obras. O
  relatório registra o que foi enviado (``meta.ia_claude``).
* **A IA não escreve o trabalho.** A resposta segue um esquema JSON fixo; o verificador
  corta cada texto (justificativa em 25 palavras, trechos em 300 caracteres) e só aceita
  links ``http(s)``. Nada é aplicado aos arquivos.
* As respostas ficam no cache ``http.sqlite`` (30 dias), pela pergunta e pelo modelo, para
  que a mesma auditoria não pague duas vezes. ``--sem-cache`` pergunta de novo.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from errei.config import Config

COMANDO = "claude"
DEFAULT_MODEL = "haiku"  # o mais básico/barato da família
FERRAMENTAS = "WebSearch,WebFetch"
CACHE_PREFIX = "claude-code://claude-code/v1/"
MAX_STR = 600  # nenhum texto da resposta passa disso antes do corte de cada verificador
MAX_ITEMS = 6
# variáveis de uma sessão do Claude Code em andamento (quando o errei roda dentro dele):
# a sessão filha não deve se ligar à sessão mãe
_ENV_SESSAO = (
    "CLAUDECODE",
    "CLAUDE_PID",
    "CLAUDE_EFFORT",
    "CLAUDE_CODE_ENTRYPOINT",
    "CLAUDE_CODE_EXECPATH",
    "CLAUDE_CODE_SESSION_ID",
    "CLAUDE_CODE_SESSION_ATTENDED",
    "CLAUDE_CODE_CHILD_SESSION",
    "CLAUDE_CODE_CHILD_NOTES_DIR",
    "CLAUDE_CODE_MESSAGING_SOCKET",
    "CLAUDE_CODE_MESSAGING_TOKEN",
)


def enabled(config: Config) -> bool:
    """Só o config confiável (usuário/flags) liga o Claude Code, e só com ``--online``."""
    return bool(config.trusted_get("ia_claude", "enabled", False)) and config.online


def executavel(config: Config | None = None) -> str | None:
    """Caminho do ``claude``: ``[ia_claude] comando`` (config do usuário) ou o ``PATH``."""
    cmd = ""
    if config is not None:
        cmd = str(config.trusted_get("ia_claude", "comando", "") or "").strip()
    if cmd:
        return shutil.which(str(Path(cmd).expanduser()))
    return shutil.which(COMANDO)


def _limpar(value: Any, depth: int = 0) -> Any:
    """Limita a resposta: profundidade, nº de itens e tamanho de cada texto."""
    if depth > 4:
        return None
    if isinstance(value, str):
        flat = " ".join(value.split())
        return flat[:MAX_STR]
    if isinstance(value, list):
        return [_limpar(v, depth + 1) for v in value[:MAX_ITEMS]]
    if isinstance(value, dict):
        return {str(k)[:40]: _limpar(v, depth + 1) for k, v in list(value.items())[:20]}
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return None


def _env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in _ENV_SESSAO}


def link_valido(url: Any) -> str:
    """``url`` se for http(s) e de tamanho razoável; senão ``''``."""
    u = str(url or "").strip()
    if len(u) > 500 or any(c.isspace() for c in u):
        return ""
    return u if u.startswith(("https://", "http://")) else ""


@dataclass(slots=True)
class ClaudeCode:
    executavel: str
    model: str = DEFAULT_MODEL
    timeout: float = 300.0
    orcamento_usd: float = 0.5
    cache: Any = None  # errei.net.cache.HttpCache | None
    refresh: bool = False  # --sem-cache: não lê o cache, mas grava a resposta nova
    calls: int = 0
    cached: int = 0
    failures: int = 0
    cost_usd: float = 0.0
    last_error: str = ""
    sent: list[str] = field(default_factory=list)  # descrição do que foi enviado

    def argv(self, schema: dict[str, Any], system: str) -> list[str]:
        """Linha de comando da sessão isolada (a pergunta vai pela entrada padrão)."""
        return [
            self.executavel,
            "-p",
            "--output-format",
            "json",
            "--json-schema",
            json.dumps(schema, ensure_ascii=False),
            "--model",
            self.model,
            "--system-prompt",
            system,
            "--tools",
            FERRAMENTAS,
            "--allowedTools",
            FERRAMENTAS,
            "--permission-prompts",
            "none",
            "--strict-mcp-config",
            "--safe-mode",
            "--disable-slash-commands",
            "--no-session-persistence",
            "--max-budget-usd",
            f"{max(0.01, self.orcamento_usd):.2f}",
        ]

    def _chave(self, prompt: str, schema: dict[str, Any], system: str) -> str:
        blob = json.dumps([self.model, system, prompt, schema], ensure_ascii=False, sort_keys=True)
        return CACHE_PREFIX + hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def ask(
        self, prompt: str, schema: dict[str, Any], *, system: str, what: str
    ) -> dict[str, Any] | None:
        """Pede uma resposta JSON no ``schema``. ``None`` se o Claude Code falhar."""
        chave = self._chave(prompt, schema, system)
        if self.cache is not None and not self.refresh:
            hit = self.cache.get(chave)
            if hit is not None and hit[0] == 200:
                try:
                    data = json.loads(hit[1])
                except json.JSONDecodeError:
                    data = None
                if isinstance(data, dict):
                    self.cached += 1
                    return data
        self.calls += 1
        self.sent.append(what)
        try:
            with tempfile.TemporaryDirectory(prefix="errei-claude-") as vazio:
                res = subprocess.run(  # argv fixo, sem shell
                    self.argv(schema, system),
                    input=prompt[:8000],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=self.timeout,
                    cwd=vazio,
                    env=_env(),
                    check=False,
                )
        except subprocess.TimeoutExpired:
            return self._falha(f"tempo esgotado ({self.timeout:.0f} s)")
        except OSError as exc:
            return self._falha(f"não foi possível executar o claude: {exc}")
        try:
            out = json.loads(res.stdout or "")
        except json.JSONDecodeError:
            erro = (res.stderr or res.stdout or "").strip().splitlines()
            return self._falha(
                erro[0][:200] if erro else f"saída inválida (código {res.returncode})"
            )
        if not isinstance(out, dict):
            return self._falha("saída inválida")
        with contextlib.suppress(TypeError, ValueError):
            self.cost_usd += float(out.get("total_cost_usd") or 0.0)
        if out.get("is_error") or out.get("subtype") not in (None, "success"):
            motivo = str(out.get("result") or out.get("subtype") or "erro")
            return self._falha(" ".join(motivo.split())[:200])
        data = out.get("structured_output")
        if not isinstance(data, dict):
            try:
                data = json.loads(str(out.get("result") or ""))
            except json.JSONDecodeError:
                data = None
        cleaned = _limpar(data) if isinstance(data, dict) else None
        if not isinstance(cleaned, dict):
            return self._falha("resposta fora do esquema")
        if self.cache is not None:
            self.cache.put(chave, 200, json.dumps(cleaned, ensure_ascii=False))
        return cleaned

    def _falha(self, motivo: str) -> dict[str, Any] | None:
        self.failures += 1
        self.last_error = motivo
        return None


def make(config: Config, http: Any) -> tuple[ClaudeCode | None, str]:
    """(cliente, motivo). O cliente é ``None`` quando desligado ou indisponível."""
    if http is None or not enabled(config):
        return None, "requer --online"
    exe = executavel(config)
    if exe is None:
        return None, (
            "o comando 'claude' (Claude Code) não foi encontrado no PATH nem em "
            "[ia_claude] comando no config do usuário"
        )
    sec = config.trusted.get("ia_claude", {})
    sec = sec if isinstance(sec, dict) else {}
    model = str(sec.get("modelo") or "").strip() or DEFAULT_MODEL
    try:
        timeout = float(sec.get("timeout") or 300)
        orcamento = float(sec.get("orcamento_usd") or 0.5)
    except (TypeError, ValueError):
        timeout, orcamento = 300.0, 0.5
    return (
        ClaudeCode(
            exe,
            model,
            timeout=timeout,
            orcamento_usd=orcamento,
            cache=getattr(http, "cache", None),
            refresh=bool(getattr(http, "refresh", False) or config.data.get("sem_cache")),
        ),
        "",
    )
