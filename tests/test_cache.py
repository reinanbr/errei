"""Cache das consultas online: validade por status, limpeza, PDFs, --sem-cache e CLI."""

from __future__ import annotations

import os
import time
from pathlib import Path

import httpx
import pytest
import respx

from errei.net import cache as cache_mod
from errei.net.cache import HttpCache
from errei.net.client import HttpClient
from helpers import cli

DIA = 24 * 3600
URL = "https://api.crossref.org/works/10.1/a"


def _clock(monkeypatch: pytest.MonkeyPatch, t: float) -> None:
    monkeypatch.setattr(cache_mod.time, "time", lambda: t)


def test_not_found_expires_sooner_than_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "http.sqlite"
    _clock(monkeypatch, 1_000_000.0)
    c = HttpCache(db)
    c.put("ok", 200, "{}")
    c.put("nf", 404, "")
    _clock(monkeypatch, 1_000_000.0 + 3 * DIA)
    assert c.get("ok") == (200, "{}")
    assert c.get("nf") is None  # "não encontrado" vale 2 dias
    _clock(monkeypatch, 1_000_000.0 + 31 * DIA)
    assert c.get("ok") is None
    c.close()


def test_expired_entries_purged_on_open(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = tmp_path / "http.sqlite"
    _clock(monkeypatch, 1_000_000.0)
    c = HttpCache(db)
    c.put("ok", 200, "{}")
    c.put("nf", 404, "")
    c.close()
    _clock(monkeypatch, 1_000_000.0 + 3 * DIA)
    c = HttpCache(db)
    assert c.purged == 1
    c.close()
    assert cache_mod.stats(tmp_path)["respostas"] == 1


def _client(tmp_path: Path, refresh: bool = False) -> HttpClient:
    return HttpClient(
        cache_dir=tmp_path, intervals={}, default_interval=0, backoff=0, refresh=refresh
    )


def test_refresh_skips_cache_but_updates_it(tmp_path: Path, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(URL).mock(
        side_effect=[
            httpx.Response(404),
            httpx.Response(200, json={"message": {"title": ["T"]}}),
        ]
    )
    assert _client(tmp_path).get_json(URL) == (404, None)
    assert _client(tmp_path).get_json(URL) == (404, None)  # do cache
    assert route.call_count == 1
    assert _client(tmp_path, refresh=True).get_json(URL) == (200, {"message": {"title": ["T"]}})
    assert route.call_count == 2
    assert _client(tmp_path).get_json(URL) == (200, {"message": {"title": ["T"]}})
    assert route.call_count == 2  # resultado novo ficou gravado


def test_pdf_cache_ttl_and_size_limit(tmp_path: Path) -> None:
    cache_mod.pdf_put(tmp_path, "a.bin", b"x" * 100, max_bytes=250)
    cache_mod.pdf_put(tmp_path, "b.bin", b"y" * 100, max_bytes=250)
    old = time.time() - 10
    os.utime(tmp_path / "pdf" / "a.bin", (old, old))
    cache_mod.pdf_put(tmp_path, "c.bin", b"z" * 100, max_bytes=250)
    names = sorted(p.name for p in (tmp_path / "pdf").iterdir())
    assert names == ["b.bin", "c.bin"]  # o mais antigo saiu
    assert cache_mod.pdf_get(tmp_path, "b.bin") == b"y" * 100
    vencido = time.time() - cache_mod.PDF_TTL - 10
    os.utime(tmp_path / "pdf" / "b.bin", (vencido, vencido))
    assert cache_mod.pdf_get(tmp_path, "b.bin") is None
    assert not (tmp_path / "pdf" / "b.bin").exists()


def test_stats_and_clear(tmp_path: Path) -> None:
    c = HttpCache(tmp_path / "http.sqlite")
    c.put(URL, 200, "{}")
    c.put("POST https://generativelanguage.googleapis.com/x#h", 200, "{}")
    c.put("https://api.openalex.org/works/doi:10.1/x", 404, "")
    c.close()
    cache_mod.pdf_put(tmp_path, "a.bin", b"pdf")
    st = cache_mod.stats(tmp_path)
    assert st["respostas"] == 3 and st["nao_encontradas"] == 1 and st["pdfs"] == 1
    assert st["por_fonte"]["generativelanguage.googleapis.com"] == 1
    assert cache_mod.clear(tmp_path, somente_vencidos=True) == {"respostas": 0, "pdfs": 0}
    assert cache_mod.clear(tmp_path) == {"respostas": 3, "pdfs": 1}
    st = cache_mod.stats(tmp_path)
    assert st["respostas"] == 0 and st["pdfs"] == 0


def test_cli_cache_info_and_limpar(tmp_path: Path) -> None:
    cd = tmp_path / "cache" / "errei"  # XDG_CACHE_HOME isolado pelo conftest
    c = HttpCache(cd / "http.sqlite")
    c.put(URL, 200, "{}")
    c.close()
    res = cli("cache", "info")
    assert res.exit_code == 0, res.output
    assert "respostas:  1" in res.output and "api.crossref.org" in res.output
    res = cli("cache", "limpar")
    assert res.exit_code == 0 and "apagadas 1 resposta(s)" in res.output
    assert "respostas:  0" in cli("cache", "info").output


def test_sem_cache_flag_reaches_client(tmp_path: Path) -> None:
    from errei.config import Config
    from errei.pipeline import make_http

    assert make_http(Config.load(tmp_path, {}, use_user_config=False)).refresh is False
    cfg = Config.load(tmp_path, {"sem_cache": True}, use_user_config=False)
    assert make_http(cfg).refresh is True
    assert "--sem-cache" in cli("audit", "--help").output
