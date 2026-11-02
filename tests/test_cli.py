from __future__ import annotations

import json
from pathlib import Path

from conftest import ARTIGO
from helpers import MINIMAL_MAIN, cli, make_project


def test_json_output_schema() -> None:
    res = cli(str(ARTIGO), "--format", "json", "--no-user-config", "--only", "latex")
    assert res.exit_code == 1
    data = json.loads(res.stdout)
    assert data["schema"] == 1
    assert data["meta"]["version"] and data["meta"]["project_hash"]
    assert data["meta"]["online"] is False
    assert data["limitations"]
    f = data["findings"][0]
    assert {"code", "severity", "file", "line", "column", "message", "suggestion"} <= set(f)


def test_markdown_has_limitations(tmp_path: Path) -> None:
    out = tmp_path / "r.md"
    res = cli(str(ARTIGO), "--format", "md", "--out", str(out), "--no-user-config")
    assert res.exit_code == 1
    text = out.read_text()
    assert "## Limitações" in text and "# Relatório do errei" in text


def test_term_output(tmp_path: Path) -> None:
    res = cli(str(ARTIGO), "--no-user-config", "--only", "latex")
    assert "Limitações" in res.stdout and "LATEX-REF-001" in res.stdout


def test_exit_codes(tmp_path: Path) -> None:
    clean = make_project(tmp_path / "ok", {"main.tex": MINIMAL_MAIN % "Texto."})
    assert cli(str(clean), "--no-user-config", "--only", "latex").exit_code == 0
    assert (
        cli(str(ARTIGO), "--no-user-config", "--only", "latex", "--fail-on", "never").exit_code == 0
    )
    assert cli(str(tmp_path / "inexistente")).exit_code == 2
    assert cli(str(ARTIGO), "--only", "naoexiste").exit_code == 2
    assert cli(str(ARTIGO), "--format", "xml").exit_code == 2


def test_fail_on_warning(tmp_path: Path) -> None:
    root = make_project(tmp_path, {"main.tex": MINIMAL_MAIN % "% TODO algo\nTexto."})
    assert cli(str(root), "--only", "latex").exit_code == 0
    assert cli(str(root), "--only", "latex", "--fail-on", "warning").exit_code == 1


def test_init_and_explain(tmp_path: Path) -> None:
    res = cli("init", str(tmp_path))
    assert res.exit_code == 0 and (tmp_path / ".errei.toml").is_file()
    assert cli("init", str(tmp_path)).exit_code == 2
    res = cli("explain", "LATEX-REF-001")
    assert res.exit_code == 0 and "rótulo inexistente" in res.stdout.lower()
    assert cli("explain", "NAO-EXISTE-999").exit_code == 2
    assert "LATEX-ENV-001" in cli("explain", "--list").stdout


def test_ignore_comments_and_config(tmp_path: Path) -> None:
    body = (
        "\\ref{a} % errei: ignore LATEX-REF-001\n% errei: ignore LATEX-REF-*\n\\ref{b}\n\\ref{c}\n"
    )
    root = make_project(tmp_path, {"main.tex": MINIMAL_MAIN % body})
    data = json.loads(cli(str(root), "-f", "json", "--only", "latex").stdout)
    refs = [f for f in data["findings"] if f["code"] == "LATEX-REF-001"]
    assert [f["line"] for f in refs] == [6]
    assert data["summary"]["suppressed"] == 2
    (root / ".errei.toml").write_text('[ignore]\ncodes = ["LATEX-*"]\n')
    data = json.loads(cli(str(root), "-f", "json", "--only", "latex").stdout)
    assert data["findings"] == []


def test_version() -> None:
    assert "errei" in cli("--version").stdout


def test_modelo_info_and_install(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("ERREI_MODEL_DIR", str(tmp_path / "dest"))
    res = cli("modelo", "info")
    assert res.exit_code == 0 and "errei-cita-v1" in res.stdout
    src = tmp_path / "src"
    src.mkdir()
    (src / "config.json").write_text("{}")
    assert cli("modelo", "instalar", str(src)).exit_code == 0
    assert (tmp_path / "dest" / "config.json").is_file()
    assert cli("modelo", "instalar", str(src)).exit_code == 2  # já existe
    assert cli("modelo", "instalar", str(tmp_path)).exit_code == 2  # não é modelo


def _tarball(members: dict[str, bytes]) -> bytes:
    import io
    import tarfile

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_modelo_baixar(tmp_path: Path, monkeypatch, respx_mock) -> None:  # type: ignore[no-untyped-def]
    import hashlib

    import httpx

    monkeypatch.setenv("ERREI_MODEL_DIR", str(tmp_path / "m"))
    monkeypatch.setenv("ERREI_RELEASE_URL", "https://rel.example.org/v9")
    good = _tarball({"errei-cita-v1/config.json": b"{}", "errei-cita-v1/README.md": b"x"})
    sha = hashlib.sha256(good).hexdigest()
    respx_mock.get("https://rel.example.org/v9/errei-cita-v1.tar.gz").mock(
        return_value=httpx.Response(200, content=good)
    )
    respx_mock.get("https://rel.example.org/v9/sha256sums-modelo.txt").mock(
        return_value=httpx.Response(200, text=f"{sha}  errei-cita-v1.tar.gz\n")
    )
    respx_mock.get("https://rel.example.org/v9/sha256sums.txt").mock(
        return_value=httpx.Response(404)
    )
    assert cli("modelo", "baixar").exit_code == 0
    assert (tmp_path / "m" / "config.json").is_file()
    assert cli("modelo", "baixar").exit_code == 2  # já instalado


def test_modelo_baixar_rejects_bad_archives(tmp_path: Path, monkeypatch, respx_mock) -> None:  # type: ignore[no-untyped-def]
    import httpx

    monkeypatch.setenv("ERREI_MODEL_DIR", str(tmp_path / "m"))
    monkeypatch.setenv("ERREI_RELEASE_URL", "https://rel.example.org/v9")
    evil = _tarball({"../../fora.txt": b"x", "config.json": b"{}"})
    route = respx_mock.get("https://rel.example.org/v9/errei-cita-v1.tar.gz")
    route.mock(return_value=httpx.Response(200, content=evil))
    respx_mock.get("https://rel.example.org/v9/sha256sums.txt").mock(
        return_value=httpx.Response(404)
    )
    respx_mock.get("https://rel.example.org/v9/sha256sums-modelo.txt").mock(
        return_value=httpx.Response(404)
    )
    res = cli("modelo", "baixar")
    assert res.exit_code == 2 and not (tmp_path.parent / "fora.txt").exists()
    ok = _tarball({"config.json": b"{}"})
    route.mock(return_value=httpx.Response(200, content=ok))
    respx_mock.get("https://rel.example.org/v9/sha256sums.txt").mock(
        return_value=httpx.Response(200, text="0" * 64 + "  errei-cita-v1.tar.gz\n")
    )
    assert cli("modelo", "baixar").exit_code == 2  # checksum não confere
