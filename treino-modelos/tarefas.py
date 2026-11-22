"""Adaptadores por tarefa: carregar o modelo, calcular a perda e prever.

Tarefas: ``classificacao`` (texto [+ par] → rótulo), ``tokens`` (BIO por palavra),
``biencoder`` (embeddings, InfoNCE com negativos do lote), ``seq2seq`` (entrada → saída)
e ``mlm`` (máscara). Na fumaça cada uma usa um modelo minúsculo com vocabulário dos
próprios dados: roda em CPU sem baixar nada.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterator
from typing import Any

import torch
from torch.nn import functional as F  # noqa: N812

FUMACA = "fumaca:minusculo"


# ---------------------------------------------------------------------- tokenizador minúsculo
def tokenizador_minusculo(textos: Iterator[str], estilo: str = "bert") -> Any:
    from tokenizers import Tokenizer, models, pre_tokenizers, processors, trainers
    from transformers import PreTrainedTokenizerFast

    if estilo == "t5":
        esp = ["<pad>", "</s>", "<unk>"]
        tk = Tokenizer(models.WordLevel(unk_token="<unk>"))
        tk.pre_tokenizer = pre_tokenizers.Whitespace()
        tk.train_from_iterator(textos, trainers.WordLevelTrainer(special_tokens=esp))
        tk.post_processor = processors.TemplateProcessing(
            single="$A </s>",
            pair="$A </s> $B </s>",
            special_tokens=[("</s>", tk.token_to_id("</s>"))],
        )
        return PreTrainedTokenizerFast(
            tokenizer_object=tk,
            pad_token="<pad>",
            eos_token="</s>",
            unk_token="<unk>",
            model_input_names=["input_ids", "attention_mask"],
        )
    esp = ["[PAD]", "[UNK]", "[CLS]", "[SEP]", "[MASK]"]
    tk = Tokenizer(models.WordLevel(unk_token="[UNK]"))
    tk.pre_tokenizer = pre_tokenizers.Whitespace()
    tk.train_from_iterator(textos, trainers.WordLevelTrainer(special_tokens=esp))
    tk.post_processor = processors.TemplateProcessing(
        single="[CLS] $A [SEP]",
        pair="[CLS] $A [SEP] $B [SEP]",
        special_tokens=[("[CLS]", tk.token_to_id("[CLS]")), ("[SEP]", tk.token_to_id("[SEP]"))],
    )
    return PreTrainedTokenizerFast(
        tokenizer_object=tk,
        unk_token="[UNK]",
        pad_token="[PAD]",
        cls_token="[CLS]",
        sep_token="[SEP]",
        mask_token="[MASK]",
    )


def bert_minusculo(vocab: int, **extra: Any) -> Any:
    from transformers import BertConfig

    return BertConfig(
        vocab_size=vocab,
        hidden_size=32,
        num_hidden_layers=2,
        num_attention_heads=2,
        intermediate_size=64,
        max_position_embeddings=128,
        **extra,
    )


# ---------------------------------------------------------------------- base
class Tarefa:
    nome = ""

    def __init__(self, h: dict[str, Any], labels: list[str] | None, info: dict[str, Any]) -> None:
        self.h, self.labels, self.info = h, labels or [], info
        self.L = int(h["max_len"])
        self.dev = torch.device("cpu")
        self.bf16 = False

    # vocabulário do modelo minúsculo
    def textos(self, rows: list[dict[str, Any]]) -> Iterator[str]:
        raise NotImplementedError

    def minusculo(self, rows: list[dict[str, Any]]) -> tuple[Any, Any]:
        raise NotImplementedError

    def classe_auto(self) -> Any:
        raise NotImplementedError

    def kwargs_modelo(self) -> dict[str, Any]:
        return {}

    def carregar(self, origem: str, rows: list[dict[str, Any]] | None = None) -> tuple[Any, Any]:
        if origem == FUMACA:
            return self.minusculo(rows or [])
        from transformers import AutoTokenizer

        tok = AutoTokenizer.from_pretrained(origem)
        model = self.classe_auto().from_pretrained(origem, **self.kwargs_modelo())
        if self.h.get("gradient_checkpointing"):
            model.gradient_checkpointing_enable()
        return tok, model

    def preparar(self, rows: list[dict[str, Any]], dev: Any, bf16: bool) -> None:
        self.dev, self.bf16 = dev, bf16

    def autocast(self) -> Any:
        return torch.autocast(self.dev.type, dtype=torch.bfloat16, enabled=self.bf16)

    def perda(self, tok: Any, model: Any, chunk: list[dict[str, Any]], fixo: bool = False) -> Any:
        raise NotImplementedError

    def descricao(self) -> dict[str, Any]:
        """Vai para errei_tarefa.json: o que o errei precisa saber para usar o modelo."""
        return {"tarefa": self.nome, "max_len": self.L}

    def pad(self, fixo: bool) -> Any:
        return "max_length" if fixo else True


# ---------------------------------------------------------------------- classificação
class Classificacao(Tarefa):
    nome = "classificacao"

    def __init__(self, h: dict[str, Any], labels: list[str] | None, info: dict[str, Any]) -> None:
        super().__init__(h, labels, info)
        self.par = bool(info.get("par"))
        self.id = {lb: i for i, lb in enumerate(self.labels)}
        self.pesos: Any = None

    def textos(self, rows: list[dict[str, Any]]) -> Iterator[str]:
        for r in rows:
            yield r["texto"]
            if r.get("par"):
                yield r["par"]

    def minusculo(self, rows: list[dict[str, Any]]) -> tuple[Any, Any]:
        from transformers import BertForSequenceClassification

        tok = tokenizador_minusculo(self.textos(rows))
        cfg = bert_minusculo(
            tok.vocab_size,
            num_labels=len(self.labels),
            id2label=dict(enumerate(self.labels)),
            label2id=self.id,
        )
        return tok, BertForSequenceClassification(cfg)

    def classe_auto(self) -> Any:
        from transformers import AutoModelForSequenceClassification

        return AutoModelForSequenceClassification

    def kwargs_modelo(self) -> dict[str, Any]:
        return {
            "num_labels": len(self.labels),
            "id2label": dict(enumerate(self.labels)),
            "label2id": self.id,
            "ignore_mismatched_sizes": True,
        }

    def preparar(self, rows: list[dict[str, Any]], dev: Any, bf16: bool) -> None:
        super().preparar(rows, dev, bf16)
        if self.h.get("pesos_classes", True):
            c = Counter(r["label"] for r in rows)
            n = max(1, len(rows))
            # raiz do inverso da frequência: corrige o desbalanceio sem exagerar nas classes raras
            w = [math.sqrt(n / (len(self.labels) * max(1, c[lb]))) for lb in self.labels]
            self.pesos = torch.tensor(w, dtype=torch.float32, device=dev)

    def codificar(self, tok: Any, chunk: list[dict[str, Any]], fixo: bool = False) -> Any:
        a = [r["texto"] for r in chunk]
        b = [r.get("par") or "—" for r in chunk] if self.par else None
        return tok(
            a, b, truncation=True, max_length=self.L, padding=self.pad(fixo), return_tensors="pt"
        ).to(self.dev)

    def perda(self, tok: Any, model: Any, chunk: list[dict[str, Any]], fixo: bool = False) -> Any:
        enc = self.codificar(tok, chunk, fixo)
        y = torch.tensor([self.id[r["label"]] for r in chunk], device=self.dev)
        with self.autocast():
            logits = model(**enc).logits
        return F.cross_entropy(logits.float(), y, weight=self.pesos)

    @torch.no_grad()
    def probabilidades(
        self, tok: Any, model: Any, rows: list[dict[str, Any]], lote: int = 64
    ) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(rows), lote):
            enc = self.codificar(tok, rows[i : i + lote])
            with self.autocast():
                logits = model(**enc).logits
            out += torch.softmax(logits.float(), -1).cpu().tolist()
        return out

    def descricao(self) -> dict[str, Any]:
        return {**super().descricao(), "labels": self.labels, "par": self.par}


# ---------------------------------------------------------------------- tokens (BIO)
class Tokens(Tarefa):
    nome = "tokens"

    def __init__(self, h: dict[str, Any], labels: list[str] | None, info: dict[str, Any]) -> None:
        super().__init__(h, labels, info)
        self.id = {lb: i for i, lb in enumerate(self.labels)}

    def textos(self, rows: list[dict[str, Any]]) -> Iterator[str]:
        for r in rows:
            yield " ".join(r["tokens"])

    def minusculo(self, rows: list[dict[str, Any]]) -> tuple[Any, Any]:
        from transformers import BertForTokenClassification

        tok = tokenizador_minusculo(self.textos(rows))
        cfg = bert_minusculo(
            tok.vocab_size,
            num_labels=len(self.labels),
            id2label=dict(enumerate(self.labels)),
            label2id=self.id,
        )
        return tok, BertForTokenClassification(cfg)

    def classe_auto(self) -> Any:
        from transformers import AutoModelForTokenClassification

        return AutoModelForTokenClassification

    def kwargs_modelo(self) -> dict[str, Any]:
        return {
            "num_labels": len(self.labels),
            "id2label": dict(enumerate(self.labels)),
            "label2id": self.id,
            "ignore_mismatched_sizes": True,
        }

    def codificar(self, tok: Any, chunk: list[dict[str, Any]], fixo: bool = False) -> Any:
        return tok(
            [r["tokens"] for r in chunk],
            is_split_into_words=True,
            truncation=True,
            max_length=self.L,
            padding=self.pad(fixo),
            return_tensors="pt",
        )

    def perda(self, tok: Any, model: Any, chunk: list[dict[str, Any]], fixo: bool = False) -> Any:
        enc = self.codificar(tok, chunk, fixo)
        y = torch.full(enc["input_ids"].shape, -100, dtype=torch.long)
        for i, r in enumerate(chunk):
            ant = None
            for j, w in enumerate(enc.word_ids(i)):
                if w is not None and w != ant:
                    y[i, j] = self.id.get(r["tags"][w], 0)
                ant = w
        enc = enc.to(self.dev)
        with self.autocast():
            logits = model(**enc).logits
        return F.cross_entropy(
            logits.float().view(-1, logits.shape[-1]), y.to(self.dev).view(-1), ignore_index=-100
        )

    @torch.no_grad()
    def prever(
        self, tok: Any, model: Any, rows: list[dict[str, Any]], lote: int = 64
    ) -> list[list[str]]:
        out: list[list[str]] = []
        for i in range(0, len(rows), lote):
            chunk = rows[i : i + lote]
            enc = self.codificar(tok, chunk)
            wids = [enc.word_ids(k) for k in range(len(chunk))]
            with self.autocast():
                pred = model(**enc.to(self.dev)).logits.argmax(-1).cpu().tolist()
            for k, r in enumerate(chunk):
                tags = ["O"] * len(r["tokens"])  # palavras cortadas pelo max_len ficam O
                ant = None
                for j, w in enumerate(wids[k]):
                    if w is not None and w != ant:
                        tags[w] = self.labels[pred[k][j]]
                    ant = w
                out.append(tags)
        return out

    def descricao(self) -> dict[str, Any]:
        return {
            **super().descricao(),
            "labels": self.labels,
            "token_regex": self.info.get("token_regex"),
        }


# ---------------------------------------------------------------------- bi-encoder
class Biencoder(Tarefa):
    nome = "biencoder"

    def __init__(self, h: dict[str, Any], labels: list[str] | None, info: dict[str, Any]) -> None:
        super().__init__(h, labels, info)
        self.pq = str(info.get("prefixo_consulta", "query: "))
        self.pp = str(info.get("prefixo_passagem", "passage: "))
        self.temp = float(h.get("temperatura", 0.05))

    def textos(self, rows: list[dict[str, Any]]) -> Iterator[str]:
        for r in rows:
            yield f"{self.pq}{r['consulta']}"
            yield f"{self.pp}{r['passagem']}"
            if r.get("negativo"):
                yield f"{self.pp}{r['negativo']}"

    def minusculo(self, rows: list[dict[str, Any]]) -> tuple[Any, Any]:
        from transformers import BertModel

        tok = tokenizador_minusculo(self.textos(rows))
        return tok, BertModel(bert_minusculo(tok.vocab_size))

    def classe_auto(self) -> Any:
        from transformers import AutoModel

        return AutoModel

    def vetores(self, tok: Any, model: Any, textos: list[str], fixo: bool = False) -> Any:
        enc = tok(
            textos, truncation=True, max_length=self.L, padding=self.pad(fixo), return_tensors="pt"
        ).to(self.dev)
        with self.autocast():
            out = model(**enc).last_hidden_state
        m = enc["attention_mask"].unsqueeze(-1).to(out.dtype)
        v = (out * m).sum(1) / m.sum(1).clamp(min=1e-6)
        return F.normalize(v.float(), dim=-1)

    def perda(self, tok: Any, model: Any, chunk: list[dict[str, Any]], fixo: bool = False) -> Any:
        n = len(chunk)
        q = self.vetores(tok, model, [self.pq + r["consulta"] for r in chunk], fixo)
        negs = [r["negativo"] for r in chunk if r.get("negativo")]
        p = self.vetores(
            tok, model, [self.pp + x for x in [r["passagem"] for r in chunk] + negs], fixo
        )
        s = q @ p.T / self.temp
        # outra passagem da mesma obra não é negativo (ex.: resumo pt e resumo en da mesma obra)
        g = [r.get("grupo") for r in chunk]
        mesma = torch.tensor(
            [[g[i] == g[j] and i != j for j in range(n)] for i in range(n)], device=self.dev
        )
        if negs:
            mesma = torch.cat(
                [mesma, torch.zeros(n, len(negs), dtype=torch.bool, device=self.dev)], 1
            )
        s = s.masked_fill(mesma, -1e4)
        alvo = torch.arange(n, device=self.dev)
        volta = (p[:n] @ q.T / self.temp).masked_fill(mesma[:, :n].T, -1e4)
        return (F.cross_entropy(s, alvo) + F.cross_entropy(volta, alvo)) / 2

    @torch.no_grad()
    def codificar_textos(self, tok: Any, model: Any, textos: list[str], lote: int = 128) -> Any:
        return torch.cat(
            [self.vetores(tok, model, textos[i : i + lote]) for i in range(0, len(textos), lote)]
        )

    def descricao(self) -> dict[str, Any]:
        return {
            **super().descricao(),
            "pooling": "mean",
            "normalizar": True,
            "prefixo_consulta": self.pq,
            "prefixo_passagem": self.pp,
            "temperatura": self.temp,
        }


# ---------------------------------------------------------------------- seq2seq
class Seq2seq(Tarefa):
    nome = "seq2seq"

    def __init__(self, h: dict[str, Any], labels: list[str] | None, info: dict[str, Any]) -> None:
        super().__init__(h, labels, info)
        self.Ls = int(h.get("max_len_saida", 128))

    def textos(self, rows: list[dict[str, Any]]) -> Iterator[str]:
        for r in rows:
            yield r["entrada"]
            yield r["saida"]

    def minusculo(self, rows: list[dict[str, Any]]) -> tuple[Any, Any]:
        from transformers import T5Config, T5ForConditionalGeneration

        tok = tokenizador_minusculo(self.textos(rows), "t5")
        cfg = T5Config(
            vocab_size=tok.vocab_size,
            d_model=32,
            d_kv=8,
            d_ff=64,
            num_layers=1,
            num_decoder_layers=1,
            num_heads=2,
            pad_token_id=tok.pad_token_id,
            eos_token_id=tok.eos_token_id,
            decoder_start_token_id=tok.pad_token_id,
        )
        return tok, T5ForConditionalGeneration(cfg)

    def classe_auto(self) -> Any:
        from transformers import AutoModelForSeq2SeqLM

        return AutoModelForSeq2SeqLM

    def perda(self, tok: Any, model: Any, chunk: list[dict[str, Any]], fixo: bool = False) -> Any:
        enc = tok(
            [r["entrada"] for r in chunk],
            truncation=True,
            max_length=self.L,
            padding=self.pad(fixo),
            return_tensors="pt",
        )
        lab = tok(
            text_target=[r["saida"] for r in chunk],
            truncation=True,
            max_length=self.Ls,
            padding="max_length" if fixo else True,
            return_tensors="pt",
        )["input_ids"]
        lab[lab == tok.pad_token_id] = -100
        enc.pop("token_type_ids", None)
        enc = enc.to(self.dev)
        with self.autocast():
            out = model(**enc, labels=lab.to(self.dev))
        return out.loss.float()

    @torch.no_grad()
    def gerar(
        self, tok: Any, model: Any, rows: list[dict[str, Any]], lote: int = 32, feixes: int = 4
    ) -> list[str]:
        out: list[str] = []
        for i in range(0, len(rows), lote):
            enc = tok(
                [r["entrada"] for r in rows[i : i + lote]],
                truncation=True,
                max_length=self.L,
                padding=True,
                return_tensors="pt",
            )
            enc.pop("token_type_ids", None)
            enc = enc.to(self.dev)
            with self.autocast():
                ger = model.generate(**enc, max_new_tokens=self.Ls, num_beams=feixes)
            out += [t.strip() for t in tok.batch_decode(ger, skip_special_tokens=True)]
        return out

    def descricao(self) -> dict[str, Any]:
        return {
            **super().descricao(),
            "max_len_saida": self.Ls,
            **{k: v for k, v in self.info.items() if k in {"prefixo", "separador", "direcoes"}},
        }


# ---------------------------------------------------------------------- MLM
class Mlm(Tarefa):
    nome = "mlm"

    def textos(self, rows: list[dict[str, Any]]) -> Iterator[str]:
        for r in rows:
            yield r["texto"]

    def minusculo(self, rows: list[dict[str, Any]]) -> tuple[Any, Any]:
        from transformers import BertForMaskedLM

        tok = tokenizador_minusculo(self.textos(rows))
        return tok, BertForMaskedLM(bert_minusculo(tok.vocab_size))

    def classe_auto(self) -> Any:
        from transformers import AutoModelForMaskedLM

        return AutoModelForMaskedLM

    def mascarar(self, tok: Any, enc: Any, gerador: Any = None) -> tuple[Any, Any]:
        p = float(self.h.get("prob_mascara", 0.15))
        ids = enc["input_ids"].clone()
        rot = ids.clone()
        esp = torch.tensor(
            [[int(t in tok.all_special_ids) for t in linha] for linha in ids.tolist()],
            dtype=torch.bool,
        )
        prob = torch.full(ids.shape, p).masked_fill(esp | (enc["attention_mask"] == 0), 0.0)
        mask = torch.bernoulli(prob, generator=gerador).bool()
        if not mask.any():  # lote minúsculo sem nenhuma máscara: mascara o primeiro token comum
            livres = (~esp & (enc["attention_mask"] == 1)).nonzero()
            if len(livres):
                mask[livres[0, 0], livres[0, 1]] = True
        rot[~mask] = -100
        troca = torch.bernoulli(torch.full(ids.shape, 0.8), generator=gerador).bool() & mask
        ids[troca] = tok.mask_token_id
        aleat = (
            torch.bernoulli(torch.full(ids.shape, 0.5), generator=gerador).bool() & mask & ~troca
        )
        ids[aleat] = torch.randint(len(tok), ids.shape, generator=gerador)[aleat]
        return ids, rot

    def perda(
        self,
        tok: Any,
        model: Any,
        chunk: list[dict[str, Any]],
        fixo: bool = False,
        gerador: Any = None,
    ) -> Any:
        enc = tok(
            [r["texto"] for r in chunk],
            truncation=True,
            max_length=self.L,
            padding=self.pad(fixo),
            return_tensors="pt",
        )
        ids, rot = self.mascarar(tok, enc, gerador)
        with self.autocast():
            out = model(
                input_ids=ids.to(self.dev),
                attention_mask=enc["attention_mask"].to(self.dev),
                labels=rot.to(self.dev),
            )
        return out.loss.float()

    @torch.no_grad()
    def perda_media(
        self, tok: Any, model: Any, rows: list[dict[str, Any]], lote: int = 32
    ) -> float:
        g = torch.Generator().manual_seed(0)  # mesmas máscaras em toda avaliação
        tot, n = 0.0, 0
        for i in range(0, len(rows), lote):
            chunk = rows[i : i + lote]
            tot += float(self.perda(tok, model, chunk, gerador=g)) * len(chunk)
            n += len(chunk)
        return tot / max(1, n)

    def descricao(self) -> dict[str, Any]:
        return {**super().descricao(), "prob_mascara": float(self.h.get("prob_mascara", 0.15))}


TAREFAS: dict[str, type[Tarefa]] = {
    "classificacao": Classificacao,
    "tokens": Tokens,
    "biencoder": Biencoder,
    "seq2seq": Seq2seq,
    "mlm": Mlm,
}


def tarefa(nome: str, h: dict[str, Any], labels: list[str] | None, info: dict[str, Any]) -> Tarefa:
    return TAREFAS[nome](h, labels, info)
