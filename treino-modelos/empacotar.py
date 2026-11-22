"""Gera ``<nome>.tar.gz`` + ``sha256sums-modelo.txt`` no formato de ``errei modelo baixar``.

Uso: python treino-modelos/empacotar.py --modelo resumo [--dist treino-modelos/saida/dist]

O pacote tem uma pasta ``<nome>/`` com os pesos, o tokenizador, ``errei_tarefa.json``,
``errei_limiares.json``, ``errei_avaliacao.json``, ``treino.json``, ``manifesto.json`` e
``README.md`` (cartão do modelo com dados, licenças, classificação das revistas e
métricas). Recusa se o manifesto tiver dado NC/ND.

Publicar: gh release upload modelos <dist>/<nome>.tar.gz <dist>/sha256sums-modelo.txt --clobber
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tarfile
from collections import defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from comum import licencas
from modelos import MODELOS, obter
from treinar import hiper, manifesto

NECESSARIOS = ("config.json", "errei_avaliacao.json", "errei_tarefa.json", "treino.json")


def licenca_pesos(h: dict[str, Any], man: dict[str, Any]) -> str:
    if any(licencas.normalizar(k) in licencas.SA for k in man.get("licencas_obras", {})):
        return "cc-by-sa-4.0"
    return str(h.get("licenca") or str(h.get("base_licenca", "mit")).lower())


def tem_nc_nd(man: dict[str, Any]) -> list[str]:
    ruins = [
        k
        for k in man.get("licencas_obras", {})
        if licencas.tem_nc(k) or "-nd" in licencas.normalizar(k)
    ]
    for d in man.get("aceitos", []):
        toks = str(d.get("licenca", "")).lower().replace("-", " ").replace(",", " ").split()
        if "nc" in toks or "nd" in toks or "noncommercial" in toks:
            ruins.append(f"{d.get('nome')}: {d.get('licenca')}")
    return ruins


def _fmt(v: Any) -> str:
    return f"{v:.3f}" if isinstance(v, float) else str(v)


def tabela_metricas(m: dict[str, Any]) -> str:
    linhas = ["| métrica | valor |", "|---|---:|"]
    sub = []
    for k, v in m.items():
        if isinstance(v, dict):
            if "f1" in v:  # classe ou campo
                sub.append((k, v))
            continue
        linhas.append(f"| {k} | {_fmt(v)} |")
    if sub:
        linhas += [
            "",
            "| classe/campo | precisão | revocação | F1 | n |",
            "|---|---:|---:|---:|---:|",
        ]
        for k, v in sub:
            linhas.append(
                f"| {k} | {_fmt(v.get('precisao', ''))} | {_fmt(v.get('revocacao', ''))} | "
                f"{_fmt(v['f1'])} | {v.get('n', '')} |"
            )
    return "\n".join(linhas)


def tabela_grupos(g: dict[str, Any]) -> str:
    if not g:
        return "(sem divisão por estrato nesta tarefa)"
    linhas = ["| recorte | grupo | n | média |", "|---|---|---:|---:|"]
    for k, d in g.items():
        for nome, v in d.items():
            linhas.append(f"| {k} | {nome} | {v['n']} | {v['media']:.3f} |")
    return "\n".join(linhas)


def cartao(
    mod: Any,
    h: dict[str, Any],
    man: dict[str, Any],
    info: dict[str, Any],
    av: dict[str, Any],
    lic: str,
) -> str:
    base = mod.CARTAO.format_map(
        defaultdict(str, licenca=lic, ano_max=(man.get("info") or {}).get("ano_humano_max", ""))
    )
    dados = "\n".join(
        f"| {d['nome']} | {d['licenca']} | {d['fonte']} | {d.get('n', '')} |"
        for d in man.get("aceitos", [])
    )
    recus = "\n".join(f"- `{k}`: {v}" for k, v in man.get("recusados", {}).items())
    cl = man.get("classificacao") or {}
    aviso = (
        "\n> **PACOTE DE FUMAÇA (dados sintéticos): não publique.**\n" if man.get("fumaca") else ""
    )
    return (
        base
        + f"""{aviso}
---

## Este pacote (gerado por empacotar.py)

- Modelo-base: `{info.get("base")}` ({info.get("base_licenca")})
- Tarefa: {info.get("tarefa")} · {info.get("epocas")} época(s), lote efetivo {info.get("lote")},
  lr {info.get("lr")}, max_len {info.get("max_len")}, bf16 {info.get("bf16")}, semente
  {info.get("semente")}, {info.get("passos")} atualizações em {int(info.get("segundos", 0)) // 60} min
  ({info.get("dispositivo")}).
- Dados de {man.get("data")} (semente {man.get("semente")}), divisão por obra {man.get("divisao")}.
- Filtros do banco: `{json.dumps(man.get("filtros") or {}, ensure_ascii=False)}`.

| conjunto | licença | fonte | exemplos |
|---|---|---|---:|
{dados}

Licenças das obras de onde saiu o texto: `{json.dumps(man.get("licencas_obras") or {}, ensure_ascii=False)}`.
Texto só entra no treino com CC BY, CC0 ou domínio público; NC e ND são recusadas sempre.

Recusados e motivo:

{recus or "- nenhum"}

### Revistas das obras usadas (Qualis CAPES, Scopus, Web of Science)

- obras: {cl.get("obras", 0)} · faixa Qualis: `{json.dumps(cl.get("qualis_faixa", {}), ensure_ascii=False)}`
- estrato Qualis: `{json.dumps(cl.get("qualis_estrato", {}), ensure_ascii=False)}`
- no Scopus: {cl.get("scopus", 0)} · Web of Science: `{json.dumps(cl.get("wos", {}), ensure_ascii=False)}`

As listas do Scopus e do WoS só serviram para classificar as revistas; elas não fazem
parte deste pacote.

### Métricas (teste: {av.get("n_teste")} exemplos)

{tabela_metricas(av.get("teste") or {})}

Limiares: `{json.dumps(av.get("limiares") or {}, ensure_ascii=False)}`

### Por estrato da revista e por recorte

{tabela_grupos(av.get("por_grupo") or {})}
"""
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="empacota um modelo do errei")
    ap.add_argument("--modelo", required=True, choices=MODELOS)
    ap.add_argument("--config")
    ap.add_argument("--pasta-modelo")
    ap.add_argument("--dist")
    ap.add_argument("--saida")
    ap.add_argument("--dados")
    a = ap.parse_args(argv)
    ns = argparse.Namespace(
        modelo=a.modelo,
        config=a.config,
        epocas=None,
        batch=None,
        lr=None,
        saida=a.saida,
        dados=a.dados,
        modelo_base=None,
        gpu=None,
        fumaca=False,
    )
    h = hiper(ns)
    mod = obter(a.modelo)
    saida, dados = Path(h["saida"]), Path(h["dados"])
    modelo = Path(a.pasta_modelo) if a.pasta_modelo else saida / "final"
    dist = Path(a.dist) if a.dist else saida.parent / "dist"
    falta = [f for f in NECESSARIOS if not (modelo / f).is_file()]
    if falta:
        print(f"erro: faltam {falta} em {modelo}; rode treinar.py e avaliar.py", file=sys.stderr)
        return 1
    man = manifesto(dados)
    ruins = tem_nc_nd(man)
    if ruins:
        print(f"erro: o manifesto tem dado NC/ND: {ruins}; pacote recusado", file=sys.stderr)
        return 1
    info = json.loads((modelo / "treino.json").read_text(encoding="utf-8"))
    av = json.loads((modelo / "errei_avaliacao.json").read_text(encoding="utf-8"))
    lic = licenca_pesos(h, man)
    nome = mod.NOME
    stage = dist / "_stage" / nome
    shutil.rmtree(stage.parent, ignore_errors=True)
    shutil.copytree(modelo, stage, ignore=shutil.ignore_patterns("*.log", "estado.pt", "*.tmp"))
    if not (stage / "errei_limiares.json").is_file():
        (stage / "errei_limiares.json").write_text("{}", encoding="utf-8")
    (stage / "manifesto.json").write_text(
        json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    (stage / "README.md").write_text(cartao(mod, h, man, info, av, lic), encoding="utf-8")
    dist.mkdir(parents=True, exist_ok=True)
    tar = dist / f"{nome}.tar.gz"
    with tarfile.open(tar, "w:gz") as t:
        t.add(stage, arcname=nome)
    shutil.rmtree(stage.parent, ignore_errors=True)
    dig = hashlib.sha256(tar.read_bytes()).hexdigest()
    sums = dist / "sha256sums-modelo.txt"
    linhas = [
        ln
        for ln in (sums.read_text().splitlines() if sums.is_file() else [])
        if not ln.endswith(f" {tar.name}")
    ]
    linhas.append(f"{dig}  {tar.name}")
    sums.write_text("\n".join(sorted(linhas, key=lambda x: x.split()[-1])) + "\n")
    print(f"[OK] {tar} ({tar.stat().st_size / 1e6:.1f} MB) · licença dos pesos: {lic}")
    print(f"sha256 {dig}")
    print(f"publicar: gh release upload modelos {tar} {sums} --clobber")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
