"""Papel retórico das frases do resumo (NBR 6028:2021): objetivo, método, resultado...

A NBR 6028 pede que o resumo ressalte **objetivo, método, resultados e conclusões**.
Este módulo classifica cada frase do resumo:

* com o modelo **errei-resumo-v1** (ajuste fino multilíngue sobre o CSAbstruct,
  Apache-2.0, com tradução para pt-BR), quando instalado; ou
* por palavras-chave e posição (fallback transparente, menos preciso).

O CSAbstruct não separa "conclusão" de "resultado"; a conclusão é detectada por
marcadores ("conclui-se", "portanto", "os resultados indicam"...) nas frases finais ou
classificadas como resultado. Tudo roda localmente.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

MODEL_NAME = "errei-resumo-v1"
PAPEIS = ["contexto", "metodo", "objetivo", "outro", "resultado"]
NOMES = {
    "contexto": "contexto",
    "objetivo": "objetivo",
    "metodo": "método",
    "resultado": "resultados",
    "conclusao": "conclusões",
    "outro": "outro",
}

RX = {
    "objetivo": re.compile(
        r"\b(objetiv\w*|prop[õo]e\w*|propomos|propor|apresenta(mos)?|investig\w+|"
        r"busca(-se|mos)?|buscou|pretende\w*|visa\w*|este (trabalho|artigo|estudo)|"
        r"(neste|nesta) (trabalho|artigo|estudo|pesquisa)|aims?|goal|we propose|"
        r"this (paper|work|study)|in this (paper|work)|we present|we investigate)\b",
        re.I,
    ),
    "metodo": re.compile(
        r"\b(metodolog\w+|m[ée]todos?|utiliz\w+|usando|empreg\w+|aplica\w*|coleta\w*|"
        r"amostra\w*|entrevist\w+|question[áa]rio\w*|experiment\w*|corpus|base de dados|"
        r"conjunto de dados|abordagem|procedimento\w*|an[áa]lise (de|do|da|dos|das)|"
        r"estudo de caso|revis[ãa]o sistem\w+|we use|using|dataset|approach|trained|"
        r"method\w*|sample|survey)\b",
        re.I,
    ),
    "resultado": re.compile(
        r"(\b(resultad\w+|mostr\w+|demonstr\w+|indic\w+|revel\w+|obtev\w*|obtid\w+|"
        r"alcan[çc]\w+|acur[áa]cia|precis[ãa]o|superior\w*|melhor\w*|redu[zç]\w*|"
        r"aument\w+|results?|shows?|showed|outperform\w*|achiev\w+|accuracy|"
        r"improv\w+)\b|\d+(,\d+)?\s?%)",
        re.I,
    ),
}
CONCL = re.compile(
    r"\b(conclu\w+|portanto|dessa forma|desse modo|em suma|em s[íi]ntese|sugere\w*|"
    r"implica\w*|contribui\w*|evidencia\w*|indicam que|apontam que|"
    r"conclude\w*|suggest\w*|implications?|we argue)\b",
    re.I,
)


@dataclass(frozen=True, slots=True)
class Papel:
    frase: str
    papel: str  # contexto | objetivo | metodo | resultado | outro
    prob: float
    fonte: str  # "modelo" | "palavras-chave"


def entrada(frases: list[str], i: int) -> tuple[str, str]:
    """Formato de entrada do modelo (igual no treino e no uso)."""
    return f"[{i + 1}/{len(frases)}] {frases[i]}", (frases[i - 1] if i else "—")


def papel_lexical(frases: list[str], i: int) -> str:
    s, n = frases[i], len(frases)
    pos = (i + 0.5) / n
    hits = {k for k, rx in RX.items() if rx.search(s)}
    if "objetivo" in hits and pos <= 0.7:
        return "objetivo"
    if "resultado" in hits and pos >= 0.4:
        return "resultado"
    if "metodo" in hits:
        return "metodo"
    if "objetivo" in hits:
        return "objetivo"
    if "resultado" in hits:
        return "resultado"
    if pos >= 0.8 and CONCL.search(s):
        return "resultado"
    return "contexto"


# ------------------------------------------------------------------ modelo
def model_dir() -> Path:
    env = os.environ.get("ERREI_RESUMO_MODEL_DIR")
    if env:
        return Path(env).expanduser()
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "errei" / "modelos" / MODEL_NAME


def unavailable_reason() -> str | None:
    if os.environ.get("ERREI_NO_MODEL"):
        return "modelos desativados (ERREI_NO_MODEL)"
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
    except ModuleNotFoundError:
        return "instale o extra: pip install 'errei[modelo]'"
    if not (model_dir() / "config.json").is_file():
        return f"modelo {MODEL_NAME} não instalado (errei modelo baixar --nome {MODEL_NAME})"
    return None


class Classificador:
    def __init__(self, path: Path) -> None:
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        self._torch = torch
        self.tok = AutoTokenizer.from_pretrained(str(path))
        self.model = AutoModelForSequenceClassification.from_pretrained(str(path)).eval()
        self.id2label = {int(k): str(v) for k, v in self.model.config.id2label.items()}

    def classificar(self, frases: list[str]) -> list[tuple[str, float]]:
        if not frases:
            return []
        pares = [entrada(frases, i) for i in range(len(frases))]
        enc = self.tok(
            [a for a, _ in pares],
            [b for _, b in pares],
            truncation=True,
            max_length=160,
            padding=True,
            return_tensors="pt",
        )
        with self._torch.no_grad():
            probs = self.model(**enc).logits.softmax(-1)
        out = []
        for row in probs.tolist():
            k = max(range(len(row)), key=row.__getitem__)
            out.append((self.id2label[k], float(row[k])))
        return out


@cache
def carregar() -> Classificador:
    return Classificador(model_dir())


def info() -> dict[str, Any]:
    p = model_dir() / "errei_resumo.json"
    try:
        return dict(json.loads(p.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return {}


def analisar(frases: list[str], *, usar_modelo: bool = True) -> list[Papel]:
    frases = [f for f in frases if f.strip()]
    if usar_modelo and unavailable_reason() is None:
        try:
            res = carregar().classificar(frases)
            return [Papel(f, p, pr, "modelo") for f, (p, pr) in zip(frases, res, strict=True)]
        except Exception:  # modelo corrompido/incompatível: cai no fallback
            pass
    return [Papel(f, papel_lexical(frases, i), 0.5, "palavras-chave") for i, f in enumerate(frases)]


def elementos(papeis: list[Papel]) -> dict[str, bool]:
    """Quais elementos da NBR 6028 aparecem no resumo."""
    n = len(papeis)
    tem = {k: any(p.papel == k for p in papeis) for k in ("objetivo", "metodo", "resultado")}
    tem["conclusao"] = any(
        CONCL.search(p.frase) and (p.papel == "resultado" or i >= n - 2)
        for i, p in enumerate(papeis)
    )
    return tem
