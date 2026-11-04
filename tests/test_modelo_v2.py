"""O errei prefere o errei-cita-v2 quando instalado e cai para o v1."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from errei import citecheck
from errei.modelo_dist import MODELOS, PADRAO_BAIXAR
from helpers import cli


def test_prefere_v2_instalado(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.delenv("ERREI_MODEL_DIR", raising=False)
    assert citecheck.model_dir().name == "errei-cita-v1"
    v2 = tmp_path / "errei" / "modelos" / "errei-cita-v2"
    v2.mkdir(parents=True)
    (v2 / "config.json").write_text("{}")
    (v2 / "errei_avaliacao.json").write_text(
        json.dumps({"afirmacao_pt": {"acuracia": 0.8, "f1_macro": 0.7}})
    )
    assert citecheck.model_dir() == v2
    assert MODELOS["errei-cita-v1"]().name == "errei-cita-v1"  # instalar v1 não sobrescreve v2
    out = cli("modelo", "info").output
    assert "modelo: errei-cita-v2" in out and "F1 macro 0.700" in out


def test_baixar_padrao_nao_inclui_v2_ainda() -> None:
    assert "errei-cita-v2" not in PADRAO_BAIXAR and "errei-cita-v2" in MODELOS


def _hf(respx_mock: object, pesos: bytes) -> None:
    import httpx

    from errei import traducao

    base = f"https://hf.example.org/{traducao.MODEL_REPO}/resolve/{traducao.MODEL_REVISION}"
    for nome in traducao.MODEL_FILES:
        body = pesos if nome == "pytorch_model.bin" else b"{}"
        respx_mock.get(f"{base}/{nome}").mock(  # type: ignore[attr-defined]
            return_value=httpx.Response(200, content=body)
        )


def test_baixar_tradutor_confere_sha256(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, respx_mock: object
) -> None:
    import hashlib

    from errei import modelo_dist, traducao

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(modelo_dist, "HF_BASE", "https://hf.example.org")
    pesos = b"pesos-de-teste"
    monkeypatch.setitem(
        traducao.MODEL_SHA256, "pytorch_model.bin", hashlib.sha256(pesos).hexdigest()
    )
    _hf(respx_mock, pesos)
    res = cli("modelo", "baixar", "--nome", "opus-mt-ROMANCE-en")
    assert res.exit_code == 0, res.output
    d = tmp_path / "errei" / "modelos" / "opus-mt-ROMANCE-en"
    assert (d / "config.json").is_file() and (d / "pytorch_model.bin").read_bytes() == pesos
    assert cli("modelo", "baixar", "--nome", "opus-mt-ROMANCE-en").exit_code == 2  # já existe
    assert "opus-mt-ROMANCE-en" in cli("modelo", "info").output


def test_baixar_tradutor_recusa_checksum_errado(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, respx_mock: object
) -> None:
    from errei import modelo_dist

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(modelo_dist, "HF_BASE", "https://hf.example.org")
    _hf(respx_mock, b"pesos-adulterados")
    res = cli("modelo", "baixar", "--nome", "opus-mt-ROMANCE-en")
    assert res.exit_code == 2 and "checksum" in res.output
    assert not (tmp_path / "errei" / "modelos" / "opus-mt-ROMANCE-en").exists()
