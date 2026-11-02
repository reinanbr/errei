from __future__ import annotations

import hashlib
import os
import socket
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
ARTIGO = FIXTURES / "artigo_exemplo"


class NetworkBlockedError(RuntimeError):
    pass


LOOPBACK = {"127.0.0.1", "::1", "localhost"}


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    """Qualquer conexão para fora da máquina falha (exceto testes marcados 'network').

    Loopback é permitido: o LanguageTool local roda como servidor em 127.0.0.1.
    """
    if request.node.get_closest_marker("network"):
        return
    real_connect = socket.socket.connect
    real_gai = socket.getaddrinfo

    def connect(self: socket.socket, addr: object) -> None:
        host = addr[0] if isinstance(addr, tuple) else None
        if self.family == socket.AF_UNIX or host in LOOPBACK:
            return real_connect(self, addr)  # type: ignore[arg-type]
        raise NetworkBlockedError(f"tentativa de acesso à rede: {addr!r}")

    def getaddrinfo(host: object, *args: object, **kwargs: object) -> object:
        if host in LOOPBACK:
            return real_gai(host, *args, **kwargs)  # type: ignore[arg-type]
        raise NetworkBlockedError(f"tentativa de resolver nome: {host!r}")

    def blocked(*args: object, **kwargs: object) -> None:
        raise NetworkBlockedError(f"tentativa de acesso à rede: {args!r}")

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)


@pytest.fixture(autouse=True)
def isolated_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Cache e config do usuário isolados por teste."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("NO_COLOR", "1")
    if not os.environ.get("ERREI_TEST_MODEL"):
        monkeypatch.setenv("ERREI_NO_MODEL", "1")
    if not os.environ.get("ERREI_TEST_LANGUAGETOOL"):
        monkeypatch.setenv("ERREI_NO_LANGUAGETOOL", "1")


def tree_hashes(root: Path) -> dict[str, str]:
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


@pytest.fixture
def readonly_guard() -> Iterator[Callable[[Path], None]]:
    """Garante que as pastas registradas não mudam durante o teste."""
    watched: dict[Path, dict[str, str]] = {}

    def watch(root: Path) -> None:
        watched[root] = tree_hashes(root)

    yield watch
    for root, before in watched.items():
        assert tree_hashes(root) == before, f"arquivos modificados em {root}"


def line_of(path: Path, snippet: str, occurrence: int = 1) -> int:
    """Linha (1-based) da n-ésima ocorrência de ``snippet`` no arquivo."""
    text = path.read_text(encoding="utf-8")
    idx = -1
    for _ in range(occurrence):
        idx = text.find(snippet, idx + 1)
        assert idx != -1, f"trecho não encontrado em {path}: {snippet!r}"
    return text.count("\n", 0, idx) + 1
