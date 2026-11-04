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
