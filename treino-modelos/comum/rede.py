"""Cliente HTTP educado, só com a biblioteca padrão.

* Intervalo mínimo entre requisições por host (config ``[rede]``) e ``Crawl-delay``.
* Novas tentativas com espera crescente em 429/5xx e falhas de rede, respeitando
  ``Retry-After``.
* ``robots.txt`` respeitado nas páginas de sites (``site=True``); as APIs documentadas
  (OpenAlex, ArticleMeta, Europe PMC, Hugging Face) são feitas para acesso por programa.
* Identificação: ``errei-treino/1.0``; e-mail só se você definir ``ERREI_EMAIL``.
* Chave do OpenAlex (``OPENALEX_API_KEY``) no cabeçalho ``Authorization``, nunca na URL.
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from dataclasses import dataclass, field
from typing import Any

UA_NOME = "errei-treino"
REPETIR = {429, 500, 502, 503, 504}


@dataclass
class Resposta:
    status: int
    corpo: bytes
    url: str  # URL final, depois dos redirecionamentos
    tipo: str = ""

    def json(self) -> Any:
        return json.loads(self.corpo.decode("utf-8"))

    def texto(self) -> str:
        return self.corpo.decode("utf-8", errors="replace")


@dataclass
class Cliente:
    intervalos: dict[str, float] = field(default_factory=dict)
    padrao: float = 1.0
    tentativas: int = 4
    timeout: float = 60.0
    espera_base: float = 2.0
    _ultimo: dict[str, float] = field(default_factory=dict)
    _trava: threading.Lock = field(default_factory=threading.Lock)
    _robots: dict[str, urllib.robotparser.RobotFileParser | None] = field(default_factory=dict)
    pedidos: int = 0
    falhas: int = 0

    def __post_init__(self) -> None:
        email = os.environ.get("ERREI_EMAIL", "").strip()
        self.ua = f"{UA_NOME}/1.0 (coleta de dados de treino; python-urllib)"
        if email:
            self.ua = f"{UA_NOME}/1.0 (mailto:{email})"
        self.openalex_key = os.environ.get("OPENALEX_API_KEY", "").strip()

    # ------------------------------------------------------------------ limites
    def _esperar(self, host: str, minimo: float = 0.0) -> None:
        intervalo = max(self.intervalos.get(host, self.padrao), minimo)
        with self._trava:
            agora = time.monotonic()
            falta = self._ultimo.get(host, 0.0) + intervalo - agora
            self._ultimo[host] = max(agora, self._ultimo.get(host, 0.0) + intervalo)
        if falta > 0:
            time.sleep(falta)

    def _robots_de(self, url: str) -> urllib.robotparser.RobotFileParser | None:
        p = urllib.parse.urlsplit(url)
        base = f"{p.scheme}://{p.netloc}"
        if base not in self._robots:
            rp: urllib.robotparser.RobotFileParser | None = urllib.robotparser.RobotFileParser()
            r = self._bruto(f"{base}/robots.txt", {}, site=False)
            if r is None or r.status >= 500:
                rp = None  # sem resposta: por prudência, bloqueia
            elif r.status >= 400:
                rp.parse([])  # sem robots.txt: liberado
            else:
                rp.parse(r.texto().splitlines())
            self._robots[base] = rp
        return self._robots[base]

    def permitido(self, url: str) -> tuple[bool, float]:
        rp = self._robots_de(url)
        if rp is None:
            return False, 0.0
        atraso = rp.crawl_delay(UA_NOME) or rp.crawl_delay("*") or 0.0
        return rp.can_fetch(UA_NOME, url), float(atraso)

    # ------------------------------------------------------------------ requisições
    def _bruto(
        self, url: str, headers: dict[str, str], site: bool, minimo: float = 0.0
    ) -> Resposta | None:
        host = urllib.parse.urlsplit(url).netloc
        cab = {"User-Agent": self.ua, "Accept": "*/*", **headers}
        if self.openalex_key and host == "api.openalex.org":
            cab["Authorization"] = f"Bearer {self.openalex_key}"
        for tentativa in range(self.tentativas + 1):
            self._esperar(host, minimo)
            self.pedidos += 1
            try:
                req = urllib.request.Request(url, headers=cab)
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    return Resposta(
                        r.status, r.read(), r.geturl(), r.headers.get("Content-Type", "")
                    )
            except urllib.error.HTTPError as e:
                if e.code not in REPETIR or tentativa == self.tentativas:
                    return Resposta(e.code, e.read() if e.fp else b"", url)
                espera = self.espera_base * 2**tentativa
                ra = e.headers.get("Retry-After") if e.headers else None
                if ra and ra.isdigit():
                    espera = max(espera, min(float(ra), 600.0))
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
                if tentativa == self.tentativas:
                    self.falhas += 1
                    return None
                espera = self.espera_base * 2**tentativa
            time.sleep(espera)
        return None

    def get(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        site: bool = False,
    ) -> Resposta | None:
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(
                {k: v for k, v in params.items() if v is not None}
            )
        minimo = 0.0
        if site:
            ok, atraso = self.permitido(url)
            if not ok:
                return Resposta(999, b"bloqueado pelo robots.txt", url)
            minimo = atraso
        r = self._bruto(url, headers or {}, site, minimo)
        if r is None or r.status >= 400:
            self.falhas += 1 if r is not None else 0
        return r

    def get_json(self, url: str, params: dict[str, Any] | None = None) -> Any | None:
        r = self.get(url, params, {"Accept": "application/json"})
        if r is None or r.status != 200:
            return None
        try:
            return r.json()
        except (ValueError, UnicodeDecodeError):
            return None


def cliente(cfg: dict[str, Any]) -> Cliente:
    rede = cfg.get("rede", {})
    return Cliente(
        intervalos={str(k): float(v) for k, v in (rede.get("intervalos") or {}).items()},
        padrao=float(rede.get("intervalo_padrao", 1.0)),
        tentativas=int(rede.get("tentativas", 4)),
        timeout=float(rede.get("timeout", 60)),
    )
