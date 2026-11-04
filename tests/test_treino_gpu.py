"""Regra de licenças do treino-gpu/cita/dados.py (sem torch, sem rede)."""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

RAIZ = Path(__file__).resolve().parents[1]


def _dados() -> ModuleType:
    spec = importlib.util.spec_from_file_location("dados_gpu", RAIZ / "treino-gpu/cita/dados.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["dados_gpu"] = mod  # dataclasses resolvem o módulo por nome
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def dados() -> ModuleType:
    return _dados()


@pytest.fixture
def cfg(dados: ModuleType) -> dict[str, Any]:
    return copy.deepcopy(dados.carregar_config())


def test_nc_recusado_sempre(dados: ModuleType, cfg: dict[str, Any]) -> None:
    cfg["dados"]["aceitar_sa"] = True
    cfg["dados"]["confirmadas"] = ["scifact", "xnli", "anli"]
    for nome in ("scifact", "xnli", "anli"):
        ok, motivo = dados.decisao(dados.REGISTRO[nome], cfg)
        assert not ok and "NC" in motivo


def test_padrao_so_permissivos(dados: ModuleType, cfg: dict[str, Any]) -> None:
    aceitos = [n for n in cfg["dados"]["conjuntos"] if dados.decisao(dados.REGISTRO[n], cfg)[0]]
    assert aceitos == ["pubhealth", "anotacoes"]
    assert cfg["modelo"]["base_licenca"] == "MIT"


def test_sa_e_a_confirmar_so_com_opt_in(dados: ModuleType, cfg: dict[str, Any]) -> None:
    assert not dados.decisao(dados.REGISTRO["snli"], cfg)[0]
    assert not dados.decisao(dados.REGISTRO["scitail"], cfg)[0]
    cfg["dados"]["aceitar_sa"] = True
    cfg["dados"]["confirmadas"] = ["scitail"]
    assert dados.decisao(dados.REGISTRO["snli"], cfg)[0]
    assert dados.decisao(dados.REGISTRO["scitail"], cfg)[0]


def test_anotacoes_recusam_trecho_sem_licenca_aberta(
    dados: ModuleType, cfg: dict[str, Any], tmp_path: Path
) -> None:
    arq = tmp_path / "a.jsonl"
    base = {"afirmacao": "A frase do artigo.", "trecho": "Trecho.", "relacao": "sustenta"}
    arq.write_text(
        "\n".join(json.dumps({**base, "fonte_licenca": lic}) for lic in ("cc-by", "cc-by-nc", ""))
    )
    pares = dados._anotacoes(cfg, [arq])
    assert len(pares) == 1 and pares[0]["label"] == "sustenta"


def test_exemplo_sintetico_fora_do_treino_real(dados: ModuleType, cfg: dict[str, Any]) -> None:
    assert dados._anotacoes(cfg) == []  # só exemplo.jsonl na pasta, e ele é da fumaça
    cfg["_fumaca"] = True
    assert len(dados._anotacoes(cfg)) == 21


def test_divisao_por_afirmacao(dados: ModuleType, cfg: dict[str, Any]) -> None:
    pares = [
        {"a": f"afirmação {i // 3}", "b": f"t{i}", "label": "neutro", "grupo": f"g{i // 3}"}
        for i in range(600)
    ]
    div = dados.dividir(pares, cfg)
    grupos = {k: {p["grupo"] for p in v} for k, v in div.items()}
    assert not grupos["treino"] & grupos["teste"] and not grupos["treino"] & grupos["validacao"]
    assert sum(len(v) for v in div.values()) == 600
