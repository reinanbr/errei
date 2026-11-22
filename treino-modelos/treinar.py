"""Treina um dos modelos (resumo, busca, chaves, ref, area, secoes, ia, trad, base).

Uso (da raiz do repositório):
    python treino-modelos/treinar.py --modelo resumo
    python treino-modelos/treinar.py --modelo resumo --estimar   # tempo, preço/h e custo
    python treino-modelos/treinar.py --modelo resumo --retomar   # continua do último checkpoint
    python treino-modelos/treinar.py --modelo ref --fumaca ...    # modelo minúsculo, CPU

Opções que sobrepõem o config: --epocas --batch --lr --saida --dados --modelo-base.

Checkpoint a cada ``checkpoint_passos`` e ao fim de cada época em
``<saida>/checkpoints`` (troca atômica, ficam os 2 últimos); o modelo final vai para
``<saida>/final`` com ``treino.json`` e ``errei_tarefa.json``. O disco da GPU alugada é
efêmero: deixe ``treino-modelos/enviar.sh --loop`` rodando.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import shutil
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from comum.util import CONFIG_MODELOS, caminho, carregar_toml, ler_jsonl
from modelos import MODELOS

FUMACA = "fumaca:minusculo"


def args_cli(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="treina um modelo do errei")
    ap.add_argument("--modelo", required=True, choices=MODELOS)
    ap.add_argument("--config")
    ap.add_argument("--epocas", type=int)
    ap.add_argument("--batch", type=int)
    ap.add_argument("--lr", type=float)
    ap.add_argument("--saida")
    ap.add_argument("--dados")
    ap.add_argument("--modelo-base")
    ap.add_argument("--gpu", help="nome da GPU em [custo.preco_hora_usd] para --estimar")
    ap.add_argument("--retomar", action="store_true", help="continua do último checkpoint")
    ap.add_argument("--estimar", action="store_true", help="só estima tempo e custo")
    ap.add_argument("--fumaca", action="store_true", help="modelo minúsculo, CPU")
    ap.add_argument("--max-passos", type=int, default=0, help="para depois de N atualizações")
    return ap.parse_args(argv)


def hiper(a: argparse.Namespace) -> dict[str, Any]:
    cfg = carregar_toml(a.config, CONFIG_MODELOS)
    g, m = cfg.get("geral", {}), cfg[a.modelo]
    h: dict[str, Any] = {
        "warmup": 0.06,
        "peso_decaimento": 0.01,
        "acumulacao": 1,
        "bf16": "auto",
        "checkpoint_passos": 1000,
        **g,
        **m,
    }
    h.update(
        modelo=a.modelo,
        base=a.modelo_base or m["base"],
        epocas=a.epocas or int(h["epocas"]),
        batch=a.batch or int(h["batch"]),
        lr=a.lr or float(h["lr"]),
        acumulacao=int(h["acumulacao"]),
        max_len=int(h["max_len"]),
        semente=int(h["semente"]),
        checkpoint_passos=int(h["checkpoint_passos"]),
        saida=str(Path(a.saida) if a.saida else caminho(g["saida"]) / a.modelo),
        dados=str(Path(a.dados) if a.dados else caminho(g["dados"]) / a.modelo),
        config=cfg["_arquivo"],
    )
    custo = cfg.get("custo", {})
    h["gpu"] = a.gpu or m.get("gpu") or custo.get("gpu", "RTX 4090")
    h["preco_hora_usd"] = float((custo.get("preco_hora_usd") or {}).get(h["gpu"], 0.0))
    if a.fumaca:
        h.update(
            base=FUMACA,
            max_len=64,
            max_len_saida=16,
            epocas=1,
            batch=4,
            acumulacao=1,
            checkpoint_passos=1,
            bf16=False,
            gradient_checkpointing=False,
        )
    return h


def manifesto(dados: Path) -> dict[str, Any]:
    p = dados / "manifesto.json"
    if not p.is_file():
        raise SystemExit(
            f"erro: {p} não existe; rode antes: python treino-modelos/dados.py --modelo ..."
        )
    return dict(json.loads(p.read_text(encoding="utf-8")))


def seed_all(s: int) -> None:
    import numpy as np
    import torch

    random.seed(s)
    np.random.seed(s)
    torch.manual_seed(s)
    torch.cuda.manual_seed_all(s)


def ultimo_checkpoint(saida: Path) -> Path | None:
    cps = [p for p in (saida / "checkpoints").glob("*") if (p / "estado.pt").is_file()]
    return max(cps, key=lambda p: (p / "estado.pt").stat().st_mtime) if cps else None


def salvar(
    model: Any,
    tok: Any,
    pasta: Path,
    estado: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    import torch

    tmp = pasta.with_name(pasta.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    model.save_pretrained(str(tmp))
    tok.save_pretrained(str(tmp))
    for nome, conteudo in (extra or {}).items():
        (tmp / nome).write_text(
            json.dumps(conteudo, ensure_ascii=False, indent=1), encoding="utf-8"
        )
    if estado is not None:
        torch.save(estado, tmp / "estado.pt")
    shutil.rmtree(pasta, ignore_errors=True)
    tmp.rename(pasta)  # troca atômica: um checkpoint pela metade nunca fica "válido"


def podar(saida: Path, manter: int = 2) -> None:
    cps = sorted(
        (p for p in (saida / "checkpoints").glob("passo-*") if p.is_dir()),
        key=lambda p: p.stat().st_mtime,
    )
    for p in cps[:-manter]:
        shutil.rmtree(p, ignore_errors=True)


def preparar(a: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    h = hiper(a)
    man = manifesto(Path(h["dados"]))
    arq = Path(h["dados"]) / "treino.jsonl"
    rows = list(ler_jsonl(arq))
    return h, man, rows


def main(argv: list[str] | None = None) -> int:
    a = args_cli(argv)
    h, man, rows = preparar(a)
    if a.estimar:
        return estimar_cli(h, man, rows)

    import torch
    from tarefas import tarefa

    if a.fumaca:
        os.environ["CUDA_VISIBLE_DEVICES"] = ""
        torch.set_num_threads(2)
    dev = torch.device("cuda" if torch.cuda.is_available() and not a.fumaca else "cpu")
    if dev.type == "cpu" and not a.fumaca:
        print("aviso: sem GPU; o treino completo em CPU leva dias", file=sys.stderr)
    seed_all(h["semente"])
    saida = Path(h["saida"])

    estado: dict[str, Any] = {}
    cp: Path | None = None
    if a.retomar:
        cp = ultimo_checkpoint(saida)
        if cp is None:
            print(f"erro: nenhum checkpoint em {saida / 'checkpoints'}", file=sys.stderr)
            return 1
        estado = torch.load(cp / "estado.pt", map_location="cpu", weights_only=False)
        h = {**h, **estado["hiper"], "saida": h["saida"], "dados": h["dados"]}
        print(f"retomando de {cp} (época {estado['epoca'] + 1}, exemplo {estado['pos']})")
    t = tarefa(man["tarefa"], h, man.get("labels"), man.get("info") or {})
    usar_bf16 = h["bf16"] is True or (
        h["bf16"] == "auto" and dev.type == "cuda" and torch.cuda.is_bf16_supported()
    )
    tok, model = t.carregar(str(cp) if cp else h["base"], rows)
    model.to(dev)
    t.preparar(rows, dev, usar_bf16)

    micro, acum = h["batch"], h["acumulacao"]
    efetivo = micro * acum
    total = (
        math.ceil(len(rows) / efetivo) * h["epocas"]
    )  # --max-passos só para antes; não muda o plano
    params = [p for p in model.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(params, lr=h["lr"], weight_decay=float(h["peso_decaimento"]))
    aquec = max(1, int(total * float(h["warmup"])))
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt, lambda s: min(1.0, (s + 1) / aquec) * max(0.0, (total - s) / max(1, total - aquec))
    )
    passo, ep0, pos0 = 0, 0, 0
    if estado:
        opt.load_state_dict(estado["opt"])
        sched.load_state_dict(estado["sched"])
        passo, ep0, pos0 = estado["passo"], estado["epoca"], estado["pos"]
        micro, acum = estado["micro"], estado["acum"]
        total = estado.get("total", total)
        random.setstate(estado["rng_py"])
        torch.set_rng_state(estado["rng_torch"])
    limite = (passo + a.max_passos) if a.max_passos else total
    print(
        f"{man['nome']} · tarefa {man['tarefa']} · base {h['base']} · dispositivo {dev} · bf16 {usar_bf16} · "
        f"{len(rows)} exemplos · batch {micro}×{acum} · {total} atualizações"
    )

    def checkpoint(nome: str, ep: int, pos: int) -> None:
        salvar(
            model,
            tok,
            saida / "checkpoints" / nome,
            {
                "hiper": h,
                "opt": opt.state_dict(),
                "sched": sched.state_dict(),
                "passo": passo,
                "epoca": ep,
                "pos": pos,
                "micro": micro,
                "acum": acum,
                "total": total,
                "rng_py": random.getstate(),
                "rng_torch": torch.get_rng_state(),
            },
        )
        podar(saida)

    t0 = time.time()
    p0 = passo
    model.train()
    parar = False
    for ep in range(ep0, h["epocas"]):
        ordem = list(range(len(rows)))
        random.Random(h["semente"] + ep).shuffle(ordem)  # mesma ordem ao retomar
        pos = pos0 if ep == ep0 else 0
        while pos < len(ordem):
            bloco = [rows[i] for i in ordem[pos : pos + efetivo]]
            try:
                opt.zero_grad(set_to_none=True)
                soma = 0.0
                for i in range(0, len(bloco), micro):
                    chunk = bloco[i : i + micro]
                    perda = t.perda(tok, model, chunk) * len(chunk) / len(bloco)
                    perda.backward()
                    soma += float(perda.detach())
                torch.nn.utils.clip_grad_norm_(params, 1.0)
                opt.step()
                sched.step()
            except torch.cuda.OutOfMemoryError:
                if micro == 1:
                    raise
                opt.zero_grad(set_to_none=True)
                torch.cuda.empty_cache()
                micro, acum = max(1, micro // 2), acum * 2
                print(f"memória insuficiente: batch {micro} × acumulação {acum} (mesmo efetivo)")
                continue
            pos += len(bloco)
            passo += 1
            if passo % 50 == 0 or a.fumaca:
                vel = (passo - p0) / max(1e-6, time.time() - t0)
                print(
                    f"época {ep + 1} · passo {passo}/{total} · perda {soma:.4f} · "
                    f"{vel:.2f} passos/s · lr {sched.get_last_lr()[0]:.2e}",
                    flush=True,
                )
            if passo % h["checkpoint_passos"] == 0:
                checkpoint(f"passo-{passo:07d}", ep, pos)
            if passo >= min(total, limite):
                parar = True
                break
        if pos >= len(ordem):
            checkpoint(f"epoca-{ep + 1}", ep + 1, 0)
        else:  # parou no meio da época (--max-passos): retomar continua daqui
            checkpoint(f"passo-{passo:07d}", ep, pos)
        if parar:
            break

    final = saida / "final"
    info = {
        "modelo": man["nome"],
        "chave": h["modelo"],
        "tarefa": man["tarefa"],
        "base": h["base"],
        "base_licenca": h.get("base_licenca", ""),
        "epocas": h["epocas"],
        "lote": efetivo,
        "lr": h["lr"],
        "max_len": h["max_len"],
        "semente": h["semente"],
        "passos": passo,
        "passos_previstos": total,
        "bf16": usar_bf16,
        "dispositivo": str(dev),
        "segundos": int(time.time() - t0),
        "exemplos_treino": len(rows),
    }
    salvar(model, tok, final, extra={"treino.json": info, "errei_tarefa.json": t.descricao()})
    print(f"[OK] modelo em {final}")
    return 0


# ---------------------------------------------------------------------- estimativa
def estimar(h: dict[str, Any], n: int, medido: float | None) -> dict[str, float]:
    passos = math.ceil(n / (h["batch"] * h["acumulacao"])) * h["epocas"]
    pps = medido or float(h.get("passos_por_segundo", 1.0))
    horas = passos / pps / 3600 * 1.15  # +15% para avaliação, checkpoints e envio
    return {
        "passos": passos,
        "passos_por_segundo": pps,
        "horas": horas,
        "preco_hora_usd": h["preco_hora_usd"],
        "custo_usd": horas * h["preco_hora_usd"],
    }


def medir(h: dict[str, Any], man: dict[str, Any], rows: list[dict[str, Any]], n: int = 10) -> float:
    """Passos/s reais com o lote do config, entrada no comprimento máximo (sem salvar nada)."""
    import torch
    from tarefas import tarefa

    dev = torch.device("cuda")
    t = tarefa(man["tarefa"], h, man.get("labels"), man.get("info") or {})
    tok, model = t.carregar(h["base"], rows)
    model.to(dev).train()
    bf16 = torch.cuda.is_bf16_supported() and h["bf16"] is not False
    t.preparar(rows, dev, bf16)
    opt = torch.optim.AdamW(model.parameters(), lr=h["lr"])
    amostra = rows[: h["batch"]]
    for i in range(n + 2):
        if i == 2:
            torch.cuda.synchronize()
            t0 = time.time()
        for _ in range(h["acumulacao"]):
            t.perda(tok, model, amostra, fixo=True).backward()
        opt.step()
        opt.zero_grad()
    torch.cuda.synchronize()
    return n / (time.time() - t0)


def estimar_cli(h: dict[str, Any], man: dict[str, Any], rows: list[dict[str, Any]]) -> int:
    medido = None
    try:
        import torch

        if torch.cuda.is_available() and h["base"] != FUMACA:
            medido = medir(h, man, rows)
    except ModuleNotFoundError:
        pass
    e = estimar(h, len(rows), medido)
    origem = "medido nesta GPU" if medido else "referência do config (passos_por_segundo)"
    print(f"modelo: {man['nome']} · GPU: {h['gpu']}")
    print(
        f"exemplos de treino: {len(rows)} · épocas {h['epocas']} · lote {h['batch']}×{h['acumulacao']}"
    )
    print(f"atualizações: {e['passos']} · {e['passos_por_segundo']:.2f} passos/s ({origem})")
    print(f"tempo previsto: {e['horas']:.2f} h (inclui ~15% para avaliação e checkpoints)")
    print(f"preço por hora: US$ {e['preco_hora_usd']:.2f}")
    print(f"custo total estimado: US$ {e['custo_usd']:.2f}")
    print("confira o preço na Hostinger antes de contratar")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
