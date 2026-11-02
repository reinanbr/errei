"""Cache das consultas online (``~/.cache/errei``).

* ``http.sqlite``: respostas das APIs. As válidas (200) valem 30 dias; as de "não
  encontrado" (404) valem só 2 dias, para que um DOI recém-registrado ou uma recusa
  momentânea da base não fique marcado como inexistente por um mês. As entradas vencidas
  são apagadas ao abrir o cache.
* ``pdf/``: PDFs de acesso aberto (``--texto-completo``). Valem 90 dias e a pasta é
  limitada a 500 MB (os mais antigos saem primeiro).

Cabeçalhos (chaves de API) nunca entram no cache. ``errei cache info`` mostra o uso e
``errei cache limpar`` apaga tudo (ou só o vencido).
"""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

DEFAULT_TTL = 30 * 24 * 3600
NEGATIVE_TTL = 2 * 24 * 3600  # 404: "não encontrado" é revisto logo
PDF_TTL = 90 * 24 * 3600
PDF_MAX_BYTES = 500 * 1024 * 1024
HTTP_DB = "http.sqlite"
PDF_DIR = "pdf"


class HttpCache:
    def __init__(
        self, path: Path | None, ttl: float = DEFAULT_TTL, negative_ttl: float = NEGATIVE_TTL
    ) -> None:
        self.ttl = ttl
        self.negative_ttl = negative_ttl
        self._lock = threading.Lock()
        self._db: sqlite3.Connection | None = None
        self.purged = 0  # entradas vencidas apagadas ao abrir
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._db = sqlite3.connect(str(path), check_same_thread=False, timeout=5)
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS http ("
                "key TEXT PRIMARY KEY, status INTEGER, body TEXT, ts REAL)"
            )
            self._db.commit()
            self.purged = self.purge()
        except (OSError, sqlite3.Error):
            self._db = None  # cache é opcional

    def _ttl(self, status: int) -> float:
        return self.ttl if status == 200 else self.negative_ttl

    def get(self, key: str) -> tuple[int, str] | None:
        if self._db is None:
            return None
        with self._lock:
            try:
                row = self._db.execute(
                    "SELECT status, body, ts FROM http WHERE key = ?", (key,)
                ).fetchone()
            except sqlite3.Error:
                return None
        if row is None or time.time() - float(row[2]) > self._ttl(int(row[0])):
            return None
        return int(row[0]), str(row[1])

    def put(self, key: str, status: int, body: str) -> None:
        if self._db is None:
            return
        with self._lock:
            try:
                self._db.execute(
                    "INSERT OR REPLACE INTO http (key, status, body, ts) VALUES (?, ?, ?, ?)",
                    (key, status, body, time.time()),
                )
                self._db.commit()
            except sqlite3.Error:
                pass

    def purge(self) -> int:
        """Apaga as entradas vencidas; devolve quantas saíram."""
        if self._db is None:
            return 0
        now = time.time()
        with self._lock:
            try:
                cur = self._db.execute(
                    "DELETE FROM http "
                    "WHERE (status = 200 AND ts < ?) OR (status != 200 AND ts < ?)",
                    (now - self.ttl, now - self.negative_ttl),
                )
                self._db.commit()
                return cur.rowcount
            except sqlite3.Error:
                return 0

    def close(self) -> None:
        if self._db is not None:
            with self._lock:
                self._db.close()
                self._db = None


# ------------------------------------------------------------------ PDFs
def pdf_get(cache_dir: Path, name: str, ttl: float = PDF_TTL) -> bytes | None:
    f = cache_dir / PDF_DIR / name
    try:
        if time.time() - f.stat().st_mtime > ttl:
            f.unlink(missing_ok=True)
            return None
        return f.read_bytes()
    except OSError:
        return None


def pdf_put(cache_dir: Path, name: str, data: bytes, max_bytes: int = PDF_MAX_BYTES) -> None:
    d = cache_dir / PDF_DIR
    try:
        d.mkdir(parents=True, exist_ok=True)
        (d / name).write_bytes(data)
        prune_pdfs(cache_dir, max_bytes)
    except OSError:
        pass


def _pdf_files(cache_dir: Path) -> list[tuple[Path, Any]]:
    d = cache_dir / PDF_DIR
    if not d.is_dir():
        return []
    out = []
    for f in d.glob("*.bin"):
        try:
            out.append((f, f.stat()))
        except OSError:
            continue
    return out


def prune_pdfs(cache_dir: Path, max_bytes: int = PDF_MAX_BYTES, ttl: float = PDF_TTL) -> int:
    """Remove PDFs vencidos e, se passar do limite, os mais antigos."""
    now = time.time()
    removed = 0
    files = []
    for f, st in _pdf_files(cache_dir):
        if now - st.st_mtime > ttl:
            f.unlink(missing_ok=True)
            removed += 1
        else:
            files.append((f, st))
    total = sum(st.st_size for _, st in files)
    for f, st in sorted(files, key=lambda x: x[1].st_mtime):
        if total <= max_bytes:
            break
        f.unlink(missing_ok=True)
        total -= st.st_size
        removed += 1
    return removed


# ------------------------------------------------------------------ gestão
def stats(cache_dir: Path) -> dict[str, Any]:
    """Uso do cache (para ``errei cache info`` e ``errei doctor``)."""
    db = cache_dir / HTTP_DB
    out: dict[str, Any] = {
        "pasta": str(cache_dir),
        "http_bytes": db.stat().st_size if db.is_file() else 0,
        "respostas": 0,
        "nao_encontradas": 0,
        "vencidas": 0,
        "mais_antiga": None,
        "mais_recente": None,
        "por_fonte": {},
    }
    if db.is_file():
        now = time.time()
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
            try:
                rows = con.execute("SELECT key, status, ts FROM http").fetchall()
            finally:
                con.close()
        except sqlite3.Error:
            rows = []
        fontes: dict[str, int] = {}
        for key, status, ts in rows:
            out["respostas"] += 1
            if status != 200:
                out["nao_encontradas"] += 1
            ttl = DEFAULT_TTL if status == 200 else NEGATIVE_TTL
            if now - ts > ttl:
                out["vencidas"] += 1
            url = str(key).removeprefix("POST ")
            host = url.split("://", 1)[-1].split("/", 1)[0]
            fontes[host] = fontes.get(host, 0) + 1
        if rows:
            out["mais_antiga"] = min(r[2] for r in rows)
            out["mais_recente"] = max(r[2] for r in rows)
        out["por_fonte"] = dict(sorted(fontes.items(), key=lambda kv: -kv[1]))
    pdfs = _pdf_files(cache_dir)
    out["pdfs"] = len(pdfs)
    out["pdf_bytes"] = sum(st.st_size for _, st in pdfs)
    return out


def clear(cache_dir: Path, *, somente_vencidos: bool = False) -> dict[str, int]:
    """Apaga o cache do errei (ou só o vencido). Não toca no LanguageTool nem nos modelos."""
    res = {"respostas": 0, "pdfs": 0}
    db = cache_dir / HTTP_DB
    if somente_vencidos:
        if db.is_file():
            c = HttpCache(db)
            res["respostas"] = c.purged
            c.close()
        res["pdfs"] = prune_pdfs(cache_dir)
        return res
    if db.is_file():
        try:
            con = sqlite3.connect(str(db), timeout=5)
            res["respostas"] = int(con.execute("SELECT COUNT(*) FROM http").fetchone()[0])
            con.close()
        except sqlite3.Error:
            pass
        for suffix in ("", "-journal", "-wal", "-shm"):
            Path(str(db) + suffix).unlink(missing_ok=True)
    for f, _ in _pdf_files(cache_dir):
        f.unlink(missing_ok=True)
        res["pdfs"] += 1
    return res
