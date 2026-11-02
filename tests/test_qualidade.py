"""Nível de qualidade atingido (tela, Markdown, JSON, lista de afazeres)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from conftest import ARTIGO
from errei.report import qualidade, render, todo
from errei.report.build import Report
from helpers import audit


@pytest.fixture
def artigo(tmp_path: Path) -> Path:
    dst = tmp_path / "artigo"
    shutil.copytree(ARTIGO, dst)
    return dst


def test_fixture_level_and_outputs(artigo: Path) -> None:
    rep = audit(artigo)
    q = rep.meta["qualidade"]
    assert q["nivel"] is None and q["nome"] == "abaixo do nível TCC"
    assert [n["nivel"] for n in q["niveis"]] == ["tcc", "mestrado", "doutorado", "a1"]
    assert q["proximo"] == "tcc"
    assert any(f.startswith("Referências citadas: ") for f in q["faltam_proximo"])
    tcc, a1 = q["niveis"][0], q["niveis"][-1]
    assert 0 < tcc["pct"] < 100 and a1["pct"] <= tcc["pct"]
    assert a1["total"] > tcc["total"]  # nível mais alto tem mais metas

    assert json.loads(render.to_json(rep))["meta"]["qualidade"]["proximo"] == "tcc"
    md = render.to_markdown(rep)
    assert "## Nível de qualidade do trabalho" in md
    assert "**Nível atingido: abaixo do nível TCC**" in md
    term = render.to_term_string(rep)
    assert "Nível de qualidade" in term and "Para chegar a TCC" in term

    lista = todo.build(rep, "mestrado")
    sec = lista.split("## Nível de qualidade do trabalho")[1].split("## Metas do nível")[0]
    assert "🎯 | Mestrado" in sec  # nível-alvo da lista destacado


class _M:
    def __init__(self, nome: str, ok: bool | None, alvo: str = "x") -> None:
        self.nome, self.ok, self.alvo, self.atual = nome, ok, alvo, "y"


def _report() -> Report:
    return Report(findings=[], metrics=[], meta={"online": True}, limitations=[], checkers=[])


def _fake(passa: set[str]) -> Any:
    def metas(report: Any, nivel: Any, project: Any, mono: bool) -> list[_M]:
        return [
            _M("Erros", True),
            _M("Meta do nível", nivel.key in passa),
            _M("Opcional", None, "opcional"),  # não conta
        ]

    return metas


def test_level_is_cumulative(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(todo, "metas", _fake({"tcc", "mestrado", "a1"}))
    q = qualidade.avaliar(_report())
    assert q["nivel"] == "mestrado"  # a1 cumprido sem doutorado não conta
    assert q["proximo"] == "doutorado"
    assert q["faltam_proximo"] == ["Meta do nível: y (meta x)"]
    assert [n["atingido"] for n in q["niveis"]] == [True, True, False, False]
    assert q["niveis"][0]["total"] == 2 and q["niveis"][2]["pct"] == 50


def test_all_levels_reached(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(todo, "metas", _fake({"tcc", "mestrado", "doutorado", "a1"}))
    q = qualidade.avaliar(_report())
    assert q["nivel"] == "a1" and q["proximo"] is None and q["faltam_proximo"] == []
    assert "Para chegar" not in "\n".join(qualidade.markdown(q))


def test_report_without_quality_renders() -> None:
    rep = _report()
    assert "Nível de qualidade" not in render.to_markdown(rep)
    assert "Nível de qualidade" not in render.to_term_string(rep)
