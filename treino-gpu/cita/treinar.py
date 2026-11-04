"""Treina o errei-cita-v2 (cross-encoder, 3 classes: sustenta, contradiz, neutro).

Uso (da raiz do repositório):
    python treino-gpu/cita/treinar.py --config treino-gpu/config/cita.toml
    python treino-gpu/cita/treinar.py --estimar          # tempo, preço/h e custo total
    python treino-gpu/cita/treinar.py --retomar          # continua do último checkpoint
    python treino-gpu/cita/treinar.py --fumaca ...       # modelo minúsculo em CPU, 1 passo

Opções que sobrepõem o config: --epocas --batch --lr --saida --dados --modelo-base.

Convenção (igual à inferência em errei.citecheck): premissa = trecho da fonte,
hipótese = afirmação do artigo. Checkpoint a cada ``checkpoint_passos`` e ao fim de cada
época em ``<saida>/checkpoints``; o modelo final vai para ``<saida>/final``. O disco da
GPU alugada é efêmero: rode ``treino-gpu/enviar.sh`` (de preferência com --loop).
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
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dados import LABEL_ID, LABELS, caminho, carregar_config, ler_jsonl  # noqa: E402


def args_cli(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="treina o errei-cita-v2")
    ap.add_argument("--config", default=None)
    ap.add_argument("--epocas", type=int)
    ap.add_argument("--batch", type=int)
    ap.add_argument("--lr", type=float)
    ap.add_argument("--saida")
    ap.add_argument("--dados")
    ap.add_argument("--modelo-base")
    ap.add_argument("--retomar", action="store_true", help="continua do último checkpoint")
    ap.add_argument("--estimar", action="store_true", help="só estima tempo e custo")
    ap.add_argument("--fumaca", action="store_true", help="modelo minúsculo, CPU, 1 passo")
    ap.add_argument("--max-passos", type=int, default=0, help="para depois de N atualizações")
    return ap.parse_args(argv)


def hiper(a: argparse.Namespace) -> dict[str, Any]:
    cfg = carregar_config(a.config)
    m, t = cfg["modelo"], cfg["treino"]
    h = {
        "nome": m["nome"],
        "base": a.modelo_base or m["base"],
        "base_licenca": m["base_licenca"],
        "max_len": int(m["max_len"]),
        "lora": bool(m.get("lora")),
        "lora_r": int(m.get("lora_r", 16)),
        "lora_alpha": int(m.get("lora_alpha", 32)),
        "epocas": a.epocas or int(t["epocas"]),
        "batch": a.batch or int(t["batch"]),
        "acumulacao": int(t["acumulacao"]),
        "lr": a.lr or float(t["lr"]),
        "warmup": float(t["warmup"]),
        "peso_decaimento": float(t["peso_decaimento"]),
        "semente": int(t["semente"]),
        "checkpoint_passos": int(t["checkpoint_passos"]),
        "bf16": t.get("bf16", "auto"),
        "saida": str(caminho(a.saida or t["saida"])),
        "dados": str(caminho(a.dados or cfg["dados"]["dir"])),
        "custo": cfg["custo"],
        "config": cfg["_arquivo"],
    }
    if a.fumaca:
        h.update(base="fumaca:minusculo", max_len=64, epocas=1, batch=4, acumulacao=1,
                 checkpoint_passos=1, bf16=False)
    return h


# ---------------------------------------------------------------------- estimativa
def estimar(h: dict[str, Any], n_treino: int, medido: float | None) -> dict[str, float]:
    passos = math.ceil(n_treino / h["batch"]) * h["epocas"]
    pps = medido or float(h["custo"]["passos_por_segundo"])
    horas = passos / pps / 3600
    preco = float(h["custo"]["preco_hora_usd"])
    # +15% para avaliação, checkpoints e envio
    return {"passos": passos, "passos_por_segundo": pps, "horas": horas * 1.15,
            "preco_hora_usd": preco, "custo_usd": horas * 1.15 * preco}


# ---------------------------------------------------------------------- modelo
def seed_all(s: int) -> None:
    import numpy as np
    import torch

    random.seed(s)
    np.random.seed(s)
    torch.manual_seed(s)
    torch.cuda.manual_seed_all(s)


def modelo_minusculo(pares: list[dict[str, Any]]) -> tuple[Any, Any]:
    """BERT de 2 camadas com vocabulário dos próprios dados: roda em CPU sem baixar nada."""
    from tokenizers import Tokenizer, models, pre_tokenizers, processors, trainers
    from transformers import BertConfig, BertForSequenceClassification, PreTrainedTokenizerFast

    tk = Tokenizer(models.WordLevel(unk_token="[UNK]"))
    tk.pre_tokenizer = pre_tokenizers.Whitespace()
    esp = ["[PAD]", "[UNK]", "[CLS]", "[SEP]"]
    tk.train_from_iterator(
        (p[k] for p in pares for k in ("a", "b")), trainers.WordLevelTrainer(special_tokens=esp)
    )
    tk.post_processor = processors.TemplateProcessing(
        single="[CLS] $A [SEP]", pair="[CLS] $A [SEP] $B [SEP]",
        special_tokens=[("[CLS]", tk.token_to_id("[CLS]")), ("[SEP]", tk.token_to_id("[SEP]"))],
    )
    tok = PreTrainedTokenizerFast(tokenizer_object=tk, unk_token="[UNK]", pad_token="[PAD]",
                                  cls_token="[CLS]", sep_token="[SEP]")
    cfg = BertConfig(vocab_size=tk.get_vocab_size(), hidden_size=32, num_hidden_layers=2,
                     num_attention_heads=2, intermediate_size=64, max_position_embeddings=128,
                     num_labels=3)
    return tok, BertForSequenceClassification(cfg)


def carregar_modelo(
    h: dict[str, Any], origem: str, pares: list[dict[str, Any]], checkpoint: Path | None = None
) -> tuple[Any, Any]:
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    id2 = dict(enumerate(LABELS))
    if checkpoint is not None and h["lora"]:
        from peft import PeftModel

        tok = AutoTokenizer.from_pretrained(str(checkpoint))
        base = AutoModelForSequenceClassification.from_pretrained(
            h["base"], num_labels=3, id2label=id2, label2id=LABEL_ID, ignore_mismatched_sizes=True
        )
        return tok, PeftModel.from_pretrained(base, str(checkpoint), is_trainable=True)
    if checkpoint is not None:
        origem = str(checkpoint)
    if origem == "fumaca:minusculo":
        tok, model = modelo_minusculo(pares)
    else:
        tok = AutoTokenizer.from_pretrained(origem)
        model = AutoModelForSequenceClassification.from_pretrained(
            origem, num_labels=3, id2label=id2, label2id=LABEL_ID, ignore_mismatched_sizes=True
        )
    model.config.id2label, model.config.label2id = id2, dict(LABEL_ID)
    if h["lora"] and not origem.startswith("fumaca"):
        from peft import LoraConfig, TaskType, get_peft_model

        model = get_peft_model(model, LoraConfig(task_type=TaskType.SEQ_CLS, r=h["lora_r"],
                                                 lora_alpha=h["lora_alpha"], lora_dropout=0.1))
    return tok, model


def ultimo_checkpoint(saida: Path) -> Path | None:
    cps = [p for p in (saida / "checkpoints").glob("*") if (p / "estado.pt").is_file()]
    return max(cps, key=lambda p: (p / "estado.pt").stat().st_mtime) if cps else None


def salvar(model: Any, tok: Any, pasta: Path, estado: dict[str, Any] | None = None) -> None:
    import torch

    tmp = pasta.with_name(pasta.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    model.save_pretrained(str(tmp))
    tok.save_pretrained(str(tmp))
    if estado is not None:
        torch.save(estado, tmp / "estado.pt")
    shutil.rmtree(pasta, ignore_errors=True)
    tmp.rename(pasta)  # troca atômica: um checkpoint pela metade nunca fica "válido"


def podar(saida: Path, manter: int = 2) -> None:
    cps = sorted((p for p in (saida / "checkpoints").glob("passo-*") if p.is_dir()),
                 key=lambda p: p.stat().st_mtime)
    for p in cps[:-manter]:
        shutil.rmtree(p, ignore_errors=True)


# ---------------------------------------------------------------------- treino
def main(argv: list[str] | None = None) -> int:
    a = args_cli(argv)
    h = hiper(a)
    saida, dados = Path(h["saida"]), Path(h["dados"])
    arq = dados / "treino.jsonl"
    if not arq.is_file():
        print(f"erro: {arq} não existe; rode antes: python treino-gpu/cita/dados.py",
              file=sys.stderr)
        return 1
    pares = list(ler_jsonl(arq))
    if a.estimar:
        return estimar_cli(h, pares)

    import torch
    from torch.nn import functional as F  # noqa: N812

    if a.fumaca:
        os.environ["CUDA_VISIBLE_DEVICES"] = ""
        torch.set_num_threads(2)
    dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if dev.type == "cpu" and not a.fumaca:
        print("aviso: sem GPU; o treino completo em CPU leva dias", file=sys.stderr)
    seed_all(h["semente"])

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
    tok, model = carregar_modelo(h, h["base"], pares, cp)
    model.to(dev)

    usar_bf16 = (h["bf16"] is True or (h["bf16"] == "auto" and dev.type == "cuda"
                 and torch.cuda.is_bf16_supported()))
    cont = Counter(p["label"] for p in pares)
    pesos = torch.tensor([len(pares) / (3 * max(1, cont[lb])) for lb in LABELS], device=dev)
    micro, acum = h["batch"], h["acumulacao"]
    efetivo = micro * acum
    passos_epoca = math.ceil(len(pares) / efetivo)
    total = passos_epoca * h["epocas"]
    if a.max_passos:
        total = min(total, a.max_passos)
    params = [p for p in model.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(params, lr=h["lr"], weight_decay=h["peso_decaimento"])
    aquec = max(1, int(total * h["warmup"]))
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt, lambda s: min(1.0, (s + 1) / aquec) * max(0.0, (total - s) / max(1, total - aquec))
    )
    passo, ep0, pos0 = 0, 0, 0
    if estado:
        opt.load_state_dict(estado["opt"])
        sched.load_state_dict(estado["sched"])
        passo, ep0, pos0 = estado["passo"], estado["epoca"], estado["pos"]
        micro, acum = estado["micro"], estado["acum"]
        random.setstate(estado["rng_py"])
        torch.set_rng_state(estado["rng_torch"])
    print(f"dispositivo {dev} · bf16 {usar_bf16} · {len(pares)} pares {dict(cont)} · "
          f"batch {micro}×{acum} · {total} atualizações")

    def lote_perda(chunk: list[dict[str, Any]]) -> Any:
        enc = tok([p["b"] for p in chunk], [p["a"] for p in chunk], truncation=True,
                  max_length=h["max_len"], padding=True, return_tensors="pt").to(dev)
        y = torch.tensor([LABEL_ID[p["label"]] for p in chunk], device=dev)
        with torch.autocast(dev.type, dtype=torch.bfloat16, enabled=usar_bf16):
            logits = model(**enc).logits
        return F.cross_entropy(logits.float(), y, weight=pesos) * len(chunk) / efetivo

    def checkpoint(nome: str, ep: int, pos: int) -> None:
        salvar(model, tok, saida / "checkpoints" / nome, {
            "hiper": h, "opt": opt.state_dict(), "sched": sched.state_dict(), "passo": passo,
            "epoca": ep, "pos": pos, "micro": micro, "acum": acum,
            "rng_py": random.getstate(), "rng_torch": torch.get_rng_state(),
        })
        podar(saida)

    t0 = time.time()
    model.train()
    fim = False
    for ep in range(ep0, h["epocas"]):
        ordem = list(range(len(pares)))
        random.Random(h["semente"] + ep).shuffle(ordem)  # mesma ordem ao retomar
        pos = pos0 if ep == ep0 else 0
        while pos < len(ordem):
            bloco = [pares[i] for i in ordem[pos : pos + efetivo]]
            try:
                opt.zero_grad(set_to_none=True)
                soma = 0.0
                for i in range(0, len(bloco), micro):
                    perda = lote_perda(bloco[i : i + micro])
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
                vel = passo / max(1e-6, time.time() - t0)
                print(f"época {ep + 1} · passo {passo}/{total} · perda {soma:.4f} · "
                      f"{vel:.2f} passos/s · lr {sched.get_last_lr()[0]:.2e}", flush=True)
            if passo % h["checkpoint_passos"] == 0:
                checkpoint(f"passo-{passo:07d}", ep, pos)
            if passo >= total:
                fim = True
                break
        if pos >= len(ordem):
            checkpoint(f"epoca-{ep + 1}", ep + 1, 0)
        else:  # parou no meio da época (--max-passos): retomar continua daqui
            checkpoint(f"passo-{passo:07d}", ep, pos)
        if fim:
            break

    final = saida / "final"
    if h["lora"] and hasattr(model, "merge_and_unload"):
        model = model.merge_and_unload()
    salvar(model, tok, final)
    info = {"modelo": h["nome"], "base": h["base"], "base_licenca": h["base_licenca"],
            "epocas": h["epocas"], "lote": efetivo, "lr": h["lr"], "max_len": h["max_len"],
            "lora": h["lora"], "semente": h["semente"], "passos": passo, "bf16": usar_bf16,
            "dispositivo": str(dev), "segundos": int(time.time() - t0),
            "pares_treino": len(pares), "classes": dict(cont)}
    (final / "treino.json").write_text(json.dumps(info, ensure_ascii=False, indent=1))
    print(f"[OK] modelo em {final}")
    return 0


def estimar_cli(h: dict[str, Any], pares: list[dict[str, Any]]) -> int:
    medido = None
    try:
        import torch

        if torch.cuda.is_available():
            medido = medir(h, pares)
    except ModuleNotFoundError:
        pass
    e = estimar(h, len(pares), medido)
    origem = "medido nesta GPU" if medido else "referência do config ([custo])"
    print(f"GPU: {h['custo']['gpu']}")
    print(f"pares de treino: {len(pares)} · épocas {h['epocas']} · batch {h['batch']}")
    print(f"atualizações: {e['passos']} · {e['passos_por_segundo']:.2f} passos/s ({origem})")
    print(f"tempo previsto: {e['horas']:.2f} h (inclui ~15% para avaliação e checkpoints)")
    print(f"preço por hora: US$ {e['preco_hora_usd']:.2f}")
    print(f"custo total estimado: US$ {e['custo_usd']:.2f}")
    print("confira o preço na Hostinger antes de contratar")
    return 0


def medir(h: dict[str, Any], pares: list[dict[str, Any]], n: int = 12) -> float:
    """Mede passos/s reais com o batch configurado (sem salvar nada)."""
    import torch
    from torch.nn import functional as F  # noqa: N812

    tok, model = carregar_modelo(h, h["base"], pares)
    dev = torch.device("cuda")
    model.to(dev).train()
    opt = torch.optim.AdamW(model.parameters(), lr=h["lr"])
    bf16 = torch.cuda.is_bf16_supported() and h["bf16"] != False  # noqa: E712
    amostra = pares[: h["batch"]]
    enc = tok([p["b"] for p in amostra], [p["a"] for p in amostra], truncation=True,
              max_length=h["max_len"], padding="max_length", return_tensors="pt").to(dev)
    y = torch.tensor([LABEL_ID[p["label"]] for p in amostra], device=dev)
    for i in range(n + 2):
        if i == 2:
            torch.cuda.synchronize()
            t0 = time.time()
        with torch.autocast("cuda", dtype=torch.bfloat16, enabled=bf16):
            perda = F.cross_entropy(model(**enc).logits.float(), y)
        perda.backward()
        opt.step()
        opt.zero_grad()
    torch.cuda.synchronize()
    return n / (time.time() - t0)


if __name__ == "__main__":
    raise SystemExit(main())
