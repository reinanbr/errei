"""Cliente HTTP educado: cache, rate limit por host, retry com backoff, degradação.

Só é instanciado com ``--online``. Nenhum outro módulo abre conexões.
"""

from __future__ import annotations

import contextlib
import json
import random
import threading
import time
from collections import defaultdict
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx

from errei import __version__
from errei.model import Finding, Severity
from errei.net.cache import HttpCache

# intervalo mínimo entre requisições por host (segundos)
HOST_INTERVAL = {
    "api.crossref.org": 0.2,
    "api.openalex.org": 0.2,
    "api.semanticscholar.org": 1.1,
    "export.arxiv.org": 3.0,
    "generativelanguage.googleapis.com": 1.0,
    "www.googleapis.com": 1.5,
    "openlibrary.org": 1.0,
}
DEFAULT_INTERVAL = 0.5
MAX_BODY = 5 * 1024 * 1024
FAILURES_TO_DISABLE = 3


class RateLimiter:
    def __init__(
        self, intervals: dict[str, float] | None = None, default: float = DEFAULT_INTERVAL
    ) -> None:
        self.intervals = intervals if intervals is not None else HOST_INTERVAL
        self.default = default
        self._next: dict[str, float] = defaultdict(float)
        self._lock = threading.Lock()

    def wait(self, host: str) -> None:
        interval = self.intervals.get(host, self.default)
        with self._lock:
            now = time.monotonic()
            at = max(now, self._next[host])
            self._next[host] = at + interval
        delay = at - now
        if delay > 0:
            time.sleep(delay)


class HttpClient:
    def __init__(
        self,
        *,
        cache_dir: Path | None,
        email: str = "",
        timeout: float = 10.0,
        retries: int = 3,
        transport: httpx.BaseTransport | None = None,
        intervals: dict[str, float] | None = None,
        default_interval: float = DEFAULT_INTERVAL,
        backoff: float = 1.0,
    ) -> None:
        self.email = email.strip()
        ua = f"errei/{__version__} (verificador de artigos; python-httpx)"
        if self.email:
            ua = f"errei/{__version__} (mailto:{self.email})"
        self._client = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": ua, "Accept": "application/json"},
            follow_redirects=True,
            transport=transport,
        )
        self.cache = HttpCache(cache_dir / "http.sqlite" if cache_dir else None)
        self.cache_dir = cache_dir
        self.limiter = RateLimiter(intervals, default_interval)
        self.retries = retries
        self.backoff = backoff
        self._fail: dict[str, int] = defaultdict(int)
        self._total_fail: dict[str, int] = defaultdict(int)
        self._last_err: dict[str, str] = {}
        self._disabled: dict[str, str] = {}
        self._lock = threading.Lock()
        self.requests_made = 0

    # ------------------------------------------------------------------
    def _key(self, url: str, params: dict[str, Any] | None) -> str:
        if params:
            items = sorted((k, str(v)) for k, v in params.items() if k != "mailto")
            return url + "?" + urlencode(items)
        return url

    def disabled(self, host: str) -> bool:
        return host in self._disabled

    def get_text(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        *,
        use_cache: bool = True,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, str] | None:
        """GET com cache. Retorna (status, corpo) ou ``None`` se a fonte falhou."""
        host = urlsplit(url).hostname or ""
        key = self._key(url, params)
        if use_cache:
            hit = self.cache.get(key)
            if hit is not None:
                return hit
        if self.disabled(host):
            return None
        params = dict(params or {})
        if self.email and host == "api.openalex.org":
            params.setdefault("mailto", self.email)
        last_err = ""
        for attempt in range(self.retries + 1):
            self.limiter.wait(host)
            try:
                with self._lock:
                    self.requests_made += 1
                resp = self._client.get(url, params=params or None, headers=headers)
            except httpx.HTTPError as exc:
                last_err = f"{type(exc).__name__}: {exc}"
                self._sleep(attempt, None)
                continue
            if resp.status_code == 429 or resp.status_code >= 500:
                last_err = f"HTTP {resp.status_code}"
                self._sleep(attempt, resp.headers.get("Retry-After"))
                continue
            body = resp.text[:MAX_BODY]
            with self._lock:
                self._fail[host] = 0
            if resp.status_code in (200, 404):
                self.cache.put(key, resp.status_code, body)
            return resp.status_code, body
        with self._lock:
            self._fail[host] += 1
            self._total_fail[host] += 1
            self._last_err[host] = last_err
            if self._fail[host] >= FAILURES_TO_DISABLE:
                self._disabled.setdefault(host, last_err)
        return None

    def get_bytes(self, url: str, *, max_bytes: int = 30 * 1024 * 1024) -> bytes | None:
        """GET binário (PDFs de acesso aberto) com cache em arquivo e limite de tamanho."""
        import hashlib

        host = urlsplit(url).hostname or ""
        if not url.startswith(("https://", "http://")) or self.disabled(host):
            return None
        cache_file = None
        if self.cache_dir is not None:
            cache_file = (
                self.cache_dir / "pdf" / (hashlib.sha256(url.encode()).hexdigest() + ".bin")
            )
            if cache_file.is_file():
                return cache_file.read_bytes()
        self.limiter.wait(host)
        try:
            with self._lock:
                self.requests_made += 1
            with self._client.stream("GET", url, headers={"Accept": "application/pdf"}) as r:
                if r.status_code != 200:
                    return None
                chunks: list[bytes] = []
                total = 0
                for chunk in r.iter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        return None
                    chunks.append(chunk)
        except httpx.HTTPError:
            with self._lock:
                self._total_fail[host] += 1
                self._last_err[host] = "download falhou"
            return None
        data = b"".join(chunks)
        if cache_file is not None:
            try:
                cache_file.parent.mkdir(parents=True, exist_ok=True)
                cache_file.write_bytes(data)
            except OSError:
                pass
        return data

    def get_json(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        *,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, Any] | None:
        """``headers`` não entram na chave do cache (use-os para chaves de API)."""
        res = self.get_text(url, params, headers=headers)
        if res is None:
            return None
        status, body = res
        if status != 200:
            return status, None
        try:
            return status, json.loads(body)
        except json.JSONDecodeError:
            return status, None

    def post_json(
        self,
        url: str,
        payload: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
        use_cache: bool = True,
    ) -> tuple[int, Any] | None:
        """POST JSON com cache (chave = URL + hash do corpo; cabeçalhos ficam de fora,
        para que segredos como chaves de API nunca sejam gravados no cache)."""
        import hashlib

        host = urlsplit(url).hostname or ""
        body = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        key = "POST " + url + "#" + hashlib.sha256(body.encode()).hexdigest()
        if use_cache:
            hit = self.cache.get(key)
            if hit is not None:
                try:
                    return hit[0], json.loads(hit[1])
                except json.JSONDecodeError:
                    pass
        if self.disabled(host):
            return None
        last_err = ""
        for attempt in range(self.retries + 1):
            self.limiter.wait(host)
            try:
                with self._lock:
                    self.requests_made += 1
                resp = self._client.post(
                    url,
                    content=body.encode(),
                    headers={"Content-Type": "application/json", **(headers or {})},
                )
            except httpx.HTTPError as exc:
                last_err = type(exc).__name__  # sem a mensagem: pode conter a URL/cabeçalhos
                self._sleep(attempt, None)
                continue
            if resp.status_code == 429 or resp.status_code >= 500:
                last_err = f"HTTP {resp.status_code}"
                self._sleep(attempt, resp.headers.get("Retry-After"))
                continue
            text = resp.text[:MAX_BODY]
            with self._lock:
                self._fail[host] = 0
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                data = None
            if resp.status_code == 200 and data is not None:
                self.cache.put(key, 200, text)
            return resp.status_code, data
        with self._lock:
            self._fail[host] += 1
            self._total_fail[host] += 1
            self._last_err[host] = last_err
            if self._fail[host] >= FAILURES_TO_DISABLE:
                self._disabled.setdefault(host, last_err)
        return None

    def _sleep(self, attempt: int, retry_after: str | None) -> None:
        if attempt >= self.retries:
            return
        delay = self.backoff * (2**attempt) + random.uniform(0, self.backoff / 2)
        if retry_after:
            try:
                delay = max(delay, float(retry_after))
            except ValueError:
                with contextlib.suppress(TypeError, ValueError):
                    when = parsedate_to_datetime(retry_after).timestamp()
                    delay = max(delay, when - time.time())
        time.sleep(min(delay, 30.0))

    def status_findings(self) -> list[Finding]:
        out = []
        for host, n in sorted(self._total_fail.items()):
            err = self._last_err.get(host, "")
            if host in self._disabled:
                msg = f"fonte online {host} desativada nesta execução após falhas ({err})"
            else:
                msg = f"fonte online {host} falhou {n} vez(es) ({err}); resultados incompletos"
            out.append(Finding("CORE-NET-001", Severity.INFO, msg, "core"))
        return out

    def close(self) -> None:
        self._client.close()
        self.cache.close()
