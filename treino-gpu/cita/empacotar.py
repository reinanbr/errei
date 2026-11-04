"""Gera errei-cita-v2.tar.gz + sha256 no formato de ``errei modelo baixar``.

Uso: python treino-gpu/cita/empacotar.py [--modelo treino-gpu/saida/final] [--dist ...]

O pacote contém uma pasta ``errei-cita-v2/`` com os pesos, o tokenizador,
``errei_limiares.json``, ``errei_avaliacao.json``, ``treino.json``, ``manifesto.json``
(dados e licenças) e ``README.md`` (cartão do modelo: cita/CARTAO.md + métricas).
``sha256sums-modelo.txt`` acumula uma linha por modelo, como scripts/empacotar-modelo.sh.

Publicar: gh release upload modelos <dist>/errei-cita-v2.tar.gz <dist>/sha256sums-modelo.txt --clobber
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tarfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dados import caminho, carregar_config  # noqa: E402

AQUI = Path(__file__).resolve().parent
NECESSARIOS = ("config.json", "errei_limiares.json", "errei_avaliacao.json")


def tabela(m: dict[str, Any]) -> str:
    linhas = ["| conjunto de teste | n | acurácia | F1 macro | F1 sustenta | F1 contradiz | F1 neutro |",
              "|---|---:|---:|---:|---:|---:|---:|"]
    for k, nome in (("afirmacao_en", "afirmação em inglês"), ("afirmacao_pt", "afirmação em português"),
                    ("total", "total")):
        r = m.get(k)
        if r:
            linhas.append(f"| {nome} | {r['n']} | {r['acuracia']:.3f} | {r['f1_macro']:.3f} | "
                          f"{r['sustenta']['f1']:.3f} | {r['contradiz']['f1']:.3f} | "
                          f"{r['neutro']['f1']:.3f} |")
    return "\n".join(linhas)


def cartao(modelo: Path, manifesto: dict[str, Any], info: dict[str, Any], m: dict[str, Any]) -> str:
    base = (AQUI / "CARTAO.md").read_text(encoding="utf-8")
    dados = "\n".join(
        f"| {d['nome']} | {d['licenca']} | {d['fonte']} | {d.get('classes', {})} |"
        for d in manifesto.get("aceitos", [])
    )
    recus = "\n".join(f"- `{k}`: {v}" for k, v in manifesto.get("recusados", {}).items())
    tr = manifesto.get("traducao") or {}
    gerado = f"""

---

## Este pacote (gerado por empacotar.py)

- Modelo-base: `{info.get('base')}` ({info.get('base_licenca')})
- Treino: {info.get('epocas')} época(s), lote efetivo {info.get('lote')}, lr {info.get('lr')},
  max_len {info.get('max_len')}, LoRA {info.get('lora')}, bf16 {info.get('bf16')},
  semente {info.get('semente')}, {info.get('passos')} atualizações em
  {int(info.get('segundos', 0)) // 60} min ({info.get('dispositivo')}).
- Dados de {manifesto.get('data')} (semente {manifesto.get('semente')}), divisão
  {manifesto.get('divisao')}.

| conjunto aceito | licença | fonte | classes |
|---|---|---|---|
{dados}

Tradução automática da afirmação para o português: {tr.get('modelo', 'não usada')}
{('(' + tr.get('licenca', '') + ')') if tr else ''}.

Conjuntos recusados e motivo:

{recus or '- nenhum'}

### Métricas (teste, nível do par frase × trecho)

Limiares escolhidos na validação: sustenta ≥ {m['limiares']['sustenta']},
contradiz ≥ {m['limiares']['contradiz']}.

{tabela(m)}
"""
    return base + gerado


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="empacota o errei-cita-v2")
    ap.add_argument("--config")
    ap.add_argument("--modelo")
    ap.add_argument("--dist")
    ap.add_argument("--saida")
    ap.add_argument("--dados")
    a = ap.parse_args(argv)
    cfg = carregar_config(a.config)
    nome = cfg["modelo"]["nome"]
    saida = caminho(a.saida or cfg["treino"]["saida"])
    modelo = Path(a.modelo) if a.modelo else saida / "final"
    dist = Path(a.dist) if a.dist else saida / "dist"
    dados = caminho(a.dados or cfg["dados"]["dir"])
    falta = [f for f in NECESSARIOS if not (modelo / f).is_file()]
    if falta:
        print(f"erro: faltam {falta} em {modelo}; rode treinar.py e avaliar.py", file=sys.stderr)
        return 1
    manifesto = json.loads((dados / "manifesto.json").read_text())
    if manifesto.get("recusados") is None or any(
        "NC" in str(d.get("licenca", "")).upper().replace("-", " ").split()
        for d in manifesto.get("aceitos", [])
    ):
        print("erro: o manifesto tem conjunto NC entre os aceitos; pacote recusado", file=sys.stderr)
        return 1
    info = json.loads((modelo / "treino.json").read_text())
    metricas = json.loads((modelo / "errei_avaliacao.json").read_text())

    stage = dist / "_stage" / nome
    shutil.rmtree(stage.parent, ignore_errors=True)
    shutil.copytree(modelo, stage, ignore=shutil.ignore_patterns("*.log", "estado.pt", "*.tmp"))
    (stage / "manifesto.json").write_text(json.dumps(manifesto, ensure_ascii=False, indent=1))
    (stage / "README.md").write_text(cartao(modelo, manifesto, info, metricas), encoding="utf-8")
    dist.mkdir(parents=True, exist_ok=True)
    tar = dist / f"{nome}.tar.gz"
    with tarfile.open(tar, "w:gz") as t:
        t.add(stage, arcname=nome)
    shutil.rmtree(stage.parent, ignore_errors=True)
    dig = hashlib.sha256(tar.read_bytes()).hexdigest()
    sums = dist / "sha256sums-modelo.txt"
    linhas = [ln for ln in (sums.read_text().splitlines() if sums.is_file() else [])
              if not ln.endswith(f" {tar.name}")]
    linhas.append(f"{dig}  {tar.name}")
    sums.write_text("\n".join(sorted(linhas, key=lambda x: x.split()[-1])) + "\n")
    print(f"[OK] {tar} ({tar.stat().st_size / 1e6:.1f} MB)")
    print(f"sha256 {dig}")
    print(f"publicar: gh release upload modelos {tar} {sums} --clobber")
    print(f"instalar localmente: tar xzf {tar} && errei modelo instalar {nome} --nome {nome}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
