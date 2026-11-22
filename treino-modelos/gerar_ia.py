"""Gera os textos "de IA" do errei-ia com modelos abertos, na própria GPU.

Uso (da raiz do repositório; a RTX PRO 6000 é a indicada para modelos de 7B):
    python treino-modelos/gerar_ia.py                                  # geradores de [ia.gerar]
    python treino-modelos/gerar_ia.py --gerador Qwen/Qwen2.5-7B-Instruct --n 5000
    python treino-modelos/gerar_ia.py --motor vllm                     # bem mais rápido (pip install vllm)
    python treino-modelos/gerar_ia.py --fumaca --banco /tmp/b.sqlite   # modelo minúsculo, CPU

Para cada obra humana (licença aberta, publicada até ``ano_humano_max``) escolhe um modo:
``do_zero`` (resumo a partir do título e das palavras-chave), ``reescrita`` (parafrasear
o resumo), ``continuacao`` (continuar as primeiras frases; guarda só a continuação) ou
``secao`` (um parágrafo de introdução, método, resultados ou discussão). Grava em
``textos_ia`` com o nome e a licença do gerador. Retomável: pula obra × gerador × modo já
feitos. Só aceita geradores Apache-2.0 ou MIT e recusa serviços comerciais.
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from banco.banco import Banco, abrir, config_banco
from comum import licencas
from comum.util import CONFIG_MODELOS, carregar_toml, cortar, fracao, frases
from modelos.ia import LICENCAS_GERADOR, PROIBIDOS

FUMACA = "fumaca:minusculo"
SECOES = {
    "pt": ["introdução", "método", "resultados", "discussão"],
    "en": ["introduction", "methods", "results", "discussion"],
}
PROMPTS = {
    "pt": {
        "do_zero": "Escreva o resumo de um artigo científico intitulado “{titulo}”. Palavras-chave: {chaves}. "
        "Escreva um único parágrafo de 150 a 250 palavras, em português, sem título e sem tópicos. "
        "Responda só com o resumo.",
        "reescrita": "Reescreva o resumo abaixo com outras palavras, mantendo o sentido, em um único parágrafo "
        "em português. Responda só com o texto reescrito.\n\n{resumo}",
        "continuacao": "Continue o texto acadêmico abaixo, em português, por mais 120 a 200 palavras, mantendo o "
        "estilo. Responda só com a continuação.\n\n{inicio}",
        "secao": "Escreva um parágrafo da seção de {secao} de um artigo científico intitulado “{titulo}”, em "
        "português, com 120 a 200 palavras. Responda só com o parágrafo.",
    },
    "en": {
        "do_zero": "Write the abstract of a scientific paper titled “{titulo}”. Keywords: {chaves}. Write a single "
        "paragraph of 150 to 250 words, in English, with no title and no bullet points. Reply with the "
        "abstract only.",
        "reescrita": "Rewrite the abstract below in your own words, keeping its meaning, as a single paragraph in "
        "English. Reply with the rewritten text only.\n\n{resumo}",
        "continuacao": "Continue the academic text below, in English, for another 120 to 200 words, keeping the "
        "style. Reply with the continuation only.\n\n{inicio}",
        "secao": "Write one paragraph of the {secao} section of a scientific paper titled “{titulo}”, in English, "
        "with 120 to 200 words. Reply with the paragraph only.",
    },
}


def candidatos(
    b: Banco,
    ano_max: int,
    linguas: list[str],
    gerador: str,
    modos: list[str],
    n: int,
    aceitar_sa: bool,
    min_resumo: int = 300,
) -> list[dict[str, Any]]:
    where, args = b.filtros_sql(
        {"aceitar_sa": aceitar_sa, "ano_max": ano_max, "idiomas": None}, texto=True
    )
    feitos = {
        (r[0], r[1])
        for r in b.con.execute("SELECT obra_id, modo FROM textos_ia WHERE modelo = ?", (gerador,))
    }
    sql = (
        f"SELECT o.id, o.titulo FROM obras o LEFT JOIN fontes_classe c ON c.fonte_id = o.fonte_id{where} "
        "ORDER BY o.id"
    )
    out: list[dict[str, Any]] = []
    for lote_ids in _lotes(b.con.execute(sql, args), 2000):
        ids = [r[0] for r in lote_ids]
        res = b.por_lingua("resumos", ids)
        tit = b.por_lingua("titulos", ids)
        kws = b.por_lingua("palavras_chave", ids)
        for oid, titulo in lote_ids:
            rs = {
                lg: t
                for lg, t in (res.get(oid) or {}).items()
                if lg in linguas and len(t) >= min_resumo
            }
            if not rs:
                continue
            lg = sorted(rs)[int(fracao(oid, 1) * len(rs))]
            modo = modos[int(fracao(oid + gerador, 2) * len(modos))]
            if (oid, modo) in feitos:
                continue
            out.append(
                {
                    "obra_id": oid,
                    "lingua": lg,
                    "modo": modo,
                    "resumo": rs[lg],
                    "titulo": (tit.get(oid) or {}).get(lg) or titulo or "",
                    "chaves": "; ".join(((kws.get(oid) or {}).get(lg) or [])[:6]),
                }
            )
            if len(out) >= n:
                return out
    return out


def _lotes(cur: Any, n: int) -> Any:
    while True:
        lote = cur.fetchmany(n)
        if not lote:
            return
        yield lote


def prompt(c: dict[str, Any], rnd: random.Random) -> tuple[str, str]:
    lg, modo = c["lingua"], c["modo"]
    p = PROMPTS[lg][modo]
    if modo == "continuacao":
        fs = frases(c["resumo"])
        return p.format(inicio=" ".join(fs[: max(1, min(2, len(fs) // 3))])), "resumo"
    if modo == "secao":
        return p.format(secao=rnd.choice(SECOES[lg]), titulo=c["titulo"]), "secao"
    return p.format(
        titulo=c["titulo"], chaves=c["chaves"] or "—", resumo=cortar(c["resumo"], 2500)
    ), "resumo"


class Gerador:
    def __init__(
        self, nome: str, motor: str, lote: int, fumaca_textos: list[str] | None = None
    ) -> None:
        import torch

        self.nome, self.motor, self.lote = nome, motor, lote
        if nome == FUMACA:
            from tarefas import tokenizador_minusculo
            from transformers import GPT2Config, GPT2LMHeadModel

            self.tok = tokenizador_minusculo(iter(fumaca_textos or ["texto"]))
            self.tok.eos_token = "[SEP]"
            eos = self.tok.convert_tokens_to_ids("[SEP]")
            self.model = GPT2LMHeadModel(
                GPT2Config(
                    vocab_size=self.tok.vocab_size,
                    n_layer=1,
                    n_embd=32,
                    n_head=2,
                    n_positions=256,
                    bos_token_id=eos,
                    eos_token_id=eos,
                )
            )
            self.dev = torch.device("cpu")
            self.motor = "transformers"
        elif motor == "vllm":
            from vllm import LLM

            self.llm = LLM(
                model=nome, dtype="bfloat16", max_model_len=4096, gpu_memory_utilization=0.9
            )
        else:
            import transformers
            from transformers import AutoModelForCausalLM, AutoTokenizer

            self.tok = AutoTokenizer.from_pretrained(nome)
            kw = "dtype" if int(transformers.__version__.split(".")[0]) >= 5 else "torch_dtype"
            self.dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            self.model = AutoModelForCausalLM.from_pretrained(nome, **{kw: torch.bfloat16}).to(
                self.dev
            )
        if self.motor == "transformers":
            self.tok.padding_side = "left"
            self.tok.truncation_side = "left"
            if self.tok.pad_token is None:
                self.tok.pad_token = self.tok.eos_token
            self.model.eval()

    def gerar(
        self, prompts: list[str], temperatura: float, top_p: float, max_novos: int
    ) -> list[str]:
        if self.motor == "vllm":
            from vllm import SamplingParams

            sp = SamplingParams(temperature=temperatura, top_p=top_p, max_tokens=max_novos)
            outs = self.llm.chat(
                [[{"role": "user", "content": p}] for p in prompts], sp, use_tqdm=False
            )
            return [o.outputs[0].text for o in outs]
        import torch

        if getattr(self.tok, "chat_template", None):
            textos = [
                self.tok.apply_chat_template(
                    [{"role": "user", "content": p}], tokenize=False, add_generation_prompt=True
                )
                for p in prompts
            ]
        else:
            textos = [p + "\n\n" for p in prompts]
        enc = self.tok(
            textos,
            return_tensors="pt",
            padding=True,
            truncation=True,
            max_length=150 if self.nome == FUMACA else 3000,
            add_special_tokens=False,
        )
        enc.pop("token_type_ids", None)
        enc = enc.to(self.dev)
        with torch.no_grad():
            out = self.model.generate(
                **enc,
                do_sample=True,
                temperature=temperatura,
                top_p=top_p,
                max_new_tokens=max_novos,
                pad_token_id=self.tok.pad_token_id,
            )
        return self.tok.batch_decode(out[:, enc["input_ids"].shape[1] :], skip_special_tokens=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="gera textos de IA (modelos abertos) para o errei-ia")
    ap.add_argument("--config")
    ap.add_argument("--config-banco")
    ap.add_argument("--banco")
    ap.add_argument(
        "--gerador", help="nome no Hugging Face (precisa estar em [[ia.gerar.modelos]])"
    )
    ap.add_argument("--n", type=int, help="textos por gerador")
    ap.add_argument("--motor", choices=["transformers", "vllm"])
    ap.add_argument("--fumaca", action="store_true")
    a = ap.parse_args(argv)
    cfg = carregar_toml(a.config, CONFIG_MODELOS)
    ia = cfg.get("ia", {})
    g = ia.get("gerar", {})
    cb = config_banco(a.config_banco)
    aceitar_sa = bool(cb["banco"].get("aceitar_sa"))
    geradores = [(m["nome"], m["licenca"]) for m in g.get("modelos", [])]
    if a.gerador:
        geradores = [x for x in geradores if x[0] == a.gerador]
        if not geradores:
            print(
                f"erro: {a.gerador} não está em [[ia.gerar.modelos]] (com a licença conferida)",
                file=sys.stderr,
            )
            return 1
    if a.fumaca:
        geradores = [(FUMACA, "Apache-2.0")]
    for nome, lic in geradores:
        if PROIBIDOS.search(nome) or licencas.normalizar(lic) not in LICENCAS_GERADOR:
            print(
                f"erro: gerador {nome} ({lic}) recusado: só modelos abertos Apache-2.0/MIT, "
                "nunca serviços comerciais",
                file=sys.stderr,
            )
            return 1
    n = a.n or (40 if a.fumaca else int(g.get("n_por_gerador", 20000)))
    lote = 8 if a.fumaca else int(g.get("lote", 16))
    max_novos = 30 if a.fumaca else int(g.get("max_novos", 450))
    temps = [float(t) for t in g.get("temperaturas", [0.7, 0.9, 1.1])]
    top_p = float(g.get("top_p", 0.95))
    modos = list(g.get("modos", ["do_zero", "reescrita", "continuacao", "secao"]))
    linguas = list(g.get("linguas", ["pt", "en"]))
    motor = a.motor or str(g.get("motor", "transformers"))
    rnd = random.Random(int(cfg.get("geral", {}).get("semente", 42)))
    min_chars = 10 if a.fumaca else 150
    with abrir(a.banco, cb) as b:
        for nome, lic in geradores:
            cands = candidatos(
                b,
                int(ia.get("ano_humano_max", 2021)),
                linguas,
                nome,
                modos,
                n,
                aceitar_sa,
                0 if a.fumaca else 300,
            )
            print(f"{nome} ({lic}): {len(cands)} textos a gerar · motor {motor}")
            if not cands:
                continue
            ger = Gerador(nome, motor, lote, [c["resumo"] for c in cands] if a.fumaca else None)
            t0, feitos = time.time(), 0
            for i in range(0, len(cands), lote):
                bloco = cands[i : i + lote]
                temp = temps[(i // lote) % len(temps)]
                ps = [prompt(c, rnd) for c in bloco]
                saidas = ger.gerar([p for p, _ in ps], temp, top_p, max_novos)
                with b.lote():
                    for c, (_, tipo), texto in zip(bloco, ps, saidas, strict=False):
                        texto = " ".join(texto.split())
                        if len(texto) < min_chars:
                            continue
                        b.texto_ia(
                            {
                                "obra_id": c["obra_id"],
                                "lingua": c["lingua"],
                                "tipo": tipo,
                                "modo": c["modo"],
                                "modelo": nome,
                                "modelo_licenca": lic,
                                "temperatura": temp,
                                "texto": texto,
                            }
                        )
                        feitos += 1
                if (i // lote) % 20 == 0:
                    vel = feitos / max(1e-6, time.time() - t0)
                    print(f"  {feitos}/{len(cands)} · {vel:.2f} textos/s", flush=True)
            print(f"[OK] {nome}: {feitos} textos gravados")
            del ger
        total = b.contar("SELECT COUNT(*) FROM textos_ia")
    print(f"textos_ia no banco: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
