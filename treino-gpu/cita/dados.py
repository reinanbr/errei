"""Baixa e prepara os dados do errei-cita-v2 e salva a divisão treino/validação/teste.

Regra inegociável: só entram conjuntos cuja licença permite uso comercial e
redistribuição (CC0, CC BY, MIT, Apache-2.0 etc.). CC BY-NC (ex.: SciFact) é recusado
sempre; CC BY-SA só com ``aceitar_sa = true``; licença "a confirmar" só se você
conferir na fonte e listar o conjunto em ``[dados] confirmadas``.

Uso (da raiz do repositório):
    python treino-gpu/cita/dados.py [--config treino-gpu/config/cita.toml]
    python treino-gpu/cita/dados.py --listar        # mostra a decisão de licença de cada um
    python treino-gpu/cita/dados.py --fumaca        # só os exemplos locais, sem rede

Saída em ``[dados] dir``: treino.jsonl, validacao.jsonl, teste.jsonl e manifesto.json
(conjuntos aceitos, recusados e o motivo, licenças, links, contagens e semente).
Cada linha: {"a": afirmação, "b": trecho da fonte, "label": sustenta|contradiz|neutro,
"fonte": conjunto, "lingua": idioma da afirmação, "tipo": origem do par}.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]

RAIZ = Path(__file__).resolve().parents[2]  # raiz do repositório
TREINO_GPU = RAIZ / "treino-gpu"
CONFIG_PADRAO = TREINO_GPU / "config" / "cita.toml"
LABELS = ["sustenta", "contradiz", "neutro"]
LABEL_ID = {k: i for i, k in enumerate(LABELS)}
HF = "https://huggingface.co/datasets"
LICENCAS_ABERTAS_TEXTO = {"cc-by", "cc0", "cc-by-4.0", "cc0-1.0", "public-domain", "mit"}


# ---------------------------------------------------------------------- utilidades comuns
def carregar_config(caminho: str | Path | None = None) -> dict[str, Any]:
    p = Path(caminho) if caminho else CONFIG_PADRAO
    with p.open("rb") as fh:
        cfg: dict[str, Any] = tomllib.load(fh)
    cfg["_arquivo"] = str(p)
    return cfg


def caminho(rel: str | Path) -> Path:
    p = Path(rel)
    return p if p.is_absolute() else RAIZ / p


def ler_jsonl(p: Path) -> Iterator[dict[str, Any]]:
    with p.open(encoding="utf-8") as fh:
        for ln in fh:
            if ln.strip():
                yield json.loads(ln)


def gravar_jsonl(p: Path, rows: Iterable[dict[str, Any]]) -> int:
    p.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with p.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
            n += 1
    return n


def frases(texto: str) -> list[str]:
    """Mesma divisão de frases da inferência (errei.citecheck.frases)."""
    split = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(\[À-Ý])")
    out = [s.strip() for s in split.split(" ".join(texto.split())) if len(s.strip()) > 20]
    return out or ([texto.strip()] if texto.strip() else [])


def cortar(texto: str, n: int) -> str:
    t = " ".join(texto.split())
    if len(t) <= n:
        return t
    corte = t[:n]
    fim = max(corte.rfind(". "), corte.rfind("! "), corte.rfind("? "))
    return corte[: fim + 1] if fim > n // 3 else corte


# ---------------------------------------------------------------------- registro de licenças
@dataclass(frozen=True)
class Conjunto:
    nome: str
    licenca: str
    estado: str  # permitida | sa | a-confirmar | nc
    fonte: str  # link da fonte
    link_licenca: str
    descricao: str
    carregar: Callable[[dict[str, Any]], list[dict[str, Any]]] | None = None


def _parquet(url: str) -> list[dict[str, Any]]:
    import pandas as pd

    df = pd.read_parquet(url)
    return [{str(k): v for k, v in r.items()} for r in df.to_dict(orient="records")]


def _hf_parquet(repo: str, config: str, split: str) -> list[dict[str, Any]]:
    return _parquet(f"{HF}/{repo}/resolve/refs%2Fconvert%2Fparquet/{config}/{split}/0000.parquet")


def _pubhealth(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """PUBHEALTH: afirmação de saúde × explicação do checador (e texto da matéria)."""
    d = cfg["dados"]
    r = random.Random(cfg["treino"]["semente"])
    rows: list[dict[str, Any]] = []
    for split in ("train", "validation", "test"):
        rows += _hf_parquet("ImperialCollegeLondon/health_fact", "default", split)
    names = ["false", "mixture", "true", "unproven"]
    mapa = {"true": "sustenta", "false": "contradiz"}
    out: list[dict[str, Any]] = []
    textos = [str(x.get("main_text") or "") for x in rows if x.get("main_text")]
    expl = [str(x.get("explanation") or "") for x in rows if x.get("explanation")]
    for x in rows:
        lab = x.get("label")
        lab = names[lab] if isinstance(lab, int) and 0 <= lab < 4 else str(lab)
        claim, ex = str(x.get("claim") or "").strip(), str(x.get("explanation") or "")
        if lab not in mapa or len(claim) < 15 or len(ex) < 40:
            continue
        out.append(_par(claim, cortar(ex, d["max_premissa"]), mapa[lab], "pubhealth", "evid"))
        for _ in range(d["neutros_por_exemplo"]):
            # texto completo de OUTRA matéria: mesmo domínio, não trata da afirmação
            fonte = r.choice(textos) if textos and r.random() < 0.5 else r.choice(expl)
            fr = frases(fonte)
            if fr:
                trecho = cortar(" ".join(fr[r.randrange(len(fr)) :][:2]), d["max_premissa"])
                out.append(_par(claim, trecho, "neutro", "pubhealth", "aleatorio-texto"))
    return out


def _scitail(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    mapa = {"entails": "sustenta", "neutral": "neutro"}
    out = []
    for split in ("train", "validation", "test"):
        for x in _hf_parquet("allenai/scitail", "tsv_format", split):
            lab = mapa.get(str(x.get("label")))
            if lab:
                out.append(_par(str(x["hypothesis"]), str(x["premise"]), lab, "scitail", "nli"))
    return out


def _snli(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    mapa = {0: "sustenta", 1: "neutro", 2: "contradiz"}
    out = []
    for split in ("train", "validation", "test"):
        for x in _hf_parquet("stanfordnlp/snli", "plain_text", split):
            lab = mapa.get(int(x.get("label", -1)))
            if lab:
                out.append(_par(str(x["hypothesis"]), str(x["premise"]), lab, "snli", "nli"))
    return out


def _anotacoes(cfg: dict[str, Any], arquivos: list[Path] | None = None) -> list[dict[str, Any]]:
    """Pares anotados à mão (CC BY 4.0). Trechos de texto completo só com licença aberta."""
    pasta = TREINO_GPU / "anotacoes"
    if arquivos is None:
        # exemplo.jsonl é sintético (formato e fumaça): nunca entra no treino real
        todos = sorted(pasta.glob("*.jsonl"))
        arquivos = [pasta / "exemplo.jsonl"] if cfg.get("_fumaca") else [
            a for a in todos if a.name != "exemplo.jsonl"
        ]
    out = []
    for arq in arquivos:
        for i, x in enumerate(ler_jsonl(arq), 1):
            lic = str(x.get("fonte_licenca") or "").lower()
            if lic not in LICENCAS_ABERTAS_TEXTO:
                print(f"  recusado {arq.name}:{i}: trecho com licença '{lic or '?'}' (só abertas)")
                continue
            rel = str(x.get("relacao"))
            if rel not in LABEL_ID:
                print(f"  recusado {arq.name}:{i}: relacao '{rel}' inválida")
                continue
            p = _par(str(x["afirmacao"]), str(x["trecho"]), rel, "anotacoes", "manual")
            p["lingua"] = str(x.get("lingua") or "pt")
            out.append(p)
    return out


REGISTRO: dict[str, Conjunto] = {
    c.nome: c
    for c in [
        Conjunto(
            "pubhealth",
            "MIT",
            "permitida",
            f"{HF}/ImperialCollegeLondon/health_fact",
            "https://github.com/neemakot/Health-Fact-Checking (LICENSE: MIT)",
            "PUBHEALTH (Kotonya e Toni, 2020): afirmações de saúde, explicações e texto "
            "completo das matérias",
            _pubhealth,
        ),
        Conjunto(
            "scitail",
            "a confirmar (sem licença no cartão do Hugging Face)",
            "a-confirmar",
            f"{HF}/allenai/scitail",
            "https://allenai.org/data/scitail",
            "SciTail (Khot et al., 2018): hipóteses científicas × frases da web",
            _scitail,
        ),
        Conjunto(
            "snli",
            "CC BY-SA 4.0",
            "sa",
            f"{HF}/stanfordnlp/snli",
            "https://creativecommons.org/licenses/by-sa/4.0/",
            "SNLI (Bowman et al., 2015): NLI geral em inglês",
            _snli,
        ),
        Conjunto(
            "anotacoes",
            "CC BY 4.0",
            "permitida",
            "treino-gpu/anotacoes/",
            "treino-gpu/anotacoes/LICENSE",
            "pares anotados à mão pelo projeto (afirmação pt-BR × trecho de fonte aberta)",
            _anotacoes,
        ),
        Conjunto(
            "scifact",
            "CC BY-NC 2.0",
            "nc",
            f"{HF}/allenai/scifact",
            "https://creativecommons.org/licenses/by-nc/2.0/",
            "SciFact: base do errei-cita-v1; NC impede uso comercial dos pesos",
        ),
        Conjunto(
            "xnli",
            "CC BY-NC 4.0",
            "nc",
            f"{HF}/facebook/xnli",
            "https://creativecommons.org/licenses/by-nc/4.0/",
            "XNLI: NLI multilíngue",
        ),
        Conjunto(
            "anli",
            "CC BY-NC 4.0",
            "nc",
            f"{HF}/facebook/anli",
            "https://creativecommons.org/licenses/by-nc/4.0/",
            "ANLI: NLI adversarial",
        ),
    ]
}


def decisao(c: Conjunto, cfg: dict[str, Any]) -> tuple[bool, str]:
    d = cfg["dados"]
    if c.estado == "nc":
        return False, f"{c.licenca} proíbe uso comercial (cláusula NC); recusado sempre"
    if c.estado == "sa" and not d.get("aceitar_sa"):
        return False, (
            f"{c.licenca}: permite uso comercial, mas obriga os pesos a sair em CC BY-SA; "
            "ligue [dados] aceitar_sa = true se aceitar"
        )
    if c.estado == "a-confirmar" and c.nome not in (d.get("confirmadas") or []):
        return False, (
            f"licença {c.licenca}; confira em {c.link_licenca} e, se permitir uso comercial, "
            f"adicione '{c.nome}' em [dados] confirmadas"
        )
    if c.carregar is None:
        return False, "sem carregador implementado"
    return True, c.licenca


# ---------------------------------------------------------------------- pares
def _par(a: str, b: str, label: str, fonte: str, tipo: str) -> dict[str, Any]:
    return {"a": " ".join(a.split()), "b": " ".join(b.split()), "label": label, "fonte": fonte,
            "lingua": "en", "tipo": tipo}


def traduzir(textos: list[str], cfg: dict[str, Any]) -> list[str]:
    """en -> pt com Marian (Apache-2.0), em lotes; usa GPU se houver."""
    import torch
    from transformers import MarianMTModel, MarianTokenizer

    nome = cfg["dados"]["tradutor"]
    tok = MarianTokenizer.from_pretrained(nome)
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    model = MarianMTModel.from_pretrained(nome).to(dev).eval()
    vocab = tok.get_vocab()
    alvo = next((t for t in (">>pt_BR<<", ">>pt_br<<", ">>pt<<") if t in vocab), "")
    if not alvo:
        raise SystemExit(f"o tradutor {nome} não tem o idioma português")
    out: list[str] = []
    with torch.no_grad():
        for i in range(0, len(textos), 64):
            lote = [f"{alvo} {t}" for t in textos[i : i + 64]]
            enc = tok(lote, return_tensors="pt", padding=True, truncation=True).to(dev)
            gen = model.generate(**enc, max_new_tokens=160)
            out += [tok.decode(g, skip_special_tokens=True) for g in gen]
            if i % 6400 == 0:
                print(f"  tradução {i}/{len(textos)}")
    return out


def dividir(pares: list[dict[str, Any]], cfg: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Divide por AFIRMAÇÃO (hash estável), para a mesma frase não vazar entre os conjuntos."""
    d, semente = cfg["dados"], cfg["treino"]["semente"]
    out: dict[str, list[dict[str, Any]]] = {"treino": [], "validacao": [], "teste": []}
    for p in pares:
        chave = p.get("grupo") or p["a"]
        h = int(hashlib.sha256(f"{semente}:{chave}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
        nome = "teste" if h < d["teste"] else ("validacao" if h < d["teste"] + d["validacao"]
                                                 else "treino")
        out[nome].append(p)
    r = random.Random(semente)
    for v in out.values():
        r.shuffle(v)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--config", default=str(CONFIG_PADRAO))
    ap.add_argument("--listar", action="store_true", help="só mostra a decisão de licença")
    ap.add_argument("--fumaca", action="store_true", help="só exemplos locais, sem rede")
    ap.add_argument("--sem-traducao", action="store_true")
    ap.add_argument("--saida", help="pasta de saída (padrão: [dados] dir)")
    args = ap.parse_args(argv)
    cfg = carregar_config(args.config)
    d = cfg["dados"]
    saida = caminho(args.saida or d["dir"])
    cfg["_fumaca"] = args.fumaca
    if args.fumaca:  # poucos exemplos: frações maiores para validação/teste não ficarem vazios
        d["validacao"], d["teste"] = 0.25, 0.25

    print("Licenças dos conjuntos:")
    aceitos: list[Conjunto] = []
    recusados: dict[str, str] = {}
    nomes = ["anotacoes"] if args.fumaca else list(d["conjuntos"])
    for nome in nomes:
        c = REGISTRO.get(nome)
        if c is None:
            print(f"  ✗ {nome}: desconhecido (opções: {', '.join(REGISTRO)})")
            recusados[nome] = "desconhecido"
            continue
        ok, motivo = decisao(c, cfg)
        print(f"  {'✓' if ok else '✗ RECUSADO'} {nome}: {motivo}")
        if ok:
            aceitos.append(c)
        else:
            recusados[nome] = motivo
    for nome, c in REGISTRO.items():
        if nome not in nomes and c.estado == "nc":
            recusados[nome] = decisao(c, cfg)[1]
    if args.listar:
        return 0
    if not aceitos:
        print("erro: nenhum conjunto com licença aceita", file=sys.stderr)
        return 1

    pares: list[dict[str, Any]] = []
    contagem: dict[str, dict[str, int]] = {}
    r = random.Random(cfg["treino"]["semente"])
    for c in aceitos:
        print(f"baixando/preparando {c.nome}…")
        assert c.carregar is not None
        rows = c.carregar(cfg)
        if len(rows) > d["max_por_conjunto"]:
            r.shuffle(rows)
            rows = rows[: d["max_por_conjunto"]]
        for p in rows:
            p["grupo"] = p["a"]
        contagem[c.nome] = dict(Counter(p["label"] for p in rows))
        pares += rows
    if d.get("traduzir_pt") and not args.sem_traducao and not args.fumaca:
        en = sorted({p["a"] for p in pares if p["lingua"] == "en"})
        r.shuffle(en)
        en = en[: int(len(en) * float(d["fracao_pt"]))]
        print(f"traduzindo {len(en)} afirmações para o português ({d['tradutor']})…")
        tr = dict(zip(en, traduzir(en, cfg), strict=True))
        novos = []
        for p in pares:
            if p["a"] in tr:
                novos.append({**p, "a": tr[p["a"]], "lingua": "pt", "tipo": p["tipo"] + "/pt-en"})
        pares += novos
        contagem["traducao_pt"] = {"pares": len(novos)}
    div = dividir(pares, cfg)
    for nome, rows in div.items():
        for p in rows:
            p.pop("grupo", None)
        n = gravar_jsonl(saida / f"{nome}.jsonl", rows)
        print(f"{nome}: {n} pares {dict(Counter(p['label'] for p in rows))}")
    manifesto = {
        "data": date.today().isoformat(),
        "semente": cfg["treino"]["semente"],
        "config": cfg["_arquivo"],
        "fumaca": args.fumaca,
        "aceitos": [
            {"nome": c.nome, "licenca": c.licenca, "fonte": c.fonte,
             "link_licenca": c.link_licenca, "descricao": c.descricao,
             "classes": contagem.get(c.nome, {})}
            for c in aceitos
        ],
        "recusados": recusados,
        "traducao": (
            {"modelo": d["tradutor"], "licenca": d["tradutor_licenca"],
             **contagem.get("traducao_pt", {})}
            if "traducao_pt" in contagem else None
        ),
        "divisao": {k: len(v) for k, v in div.items()},
    }
    (saida / "manifesto.json").write_text(json.dumps(manifesto, ensure_ascii=False, indent=1))
    print(f"[OK] dados em {saida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
