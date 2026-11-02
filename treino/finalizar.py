"""Calibra limiares (validação), mede no teste e escreve o cartão do modelo.

Uso: python finalizar.py modelos/errei-cita-v1
Gera, dentro da pasta do modelo: errei_limiares.json, errei_avaliacao.json, README.md.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from comum import DADOS

BASE = "MoritzLaurer/multilingual-MiniLMv2-L6-mnli-xnli"
PY = sys.executable


def avaliar(modelo: str, conjunto: str, limiares: tuple[float, float] | None = None) -> dict:  # type: ignore[type-arg]
    args = [PY, "avaliar.py", modelo, conjunto]
    if limiares:
        args += [str(limiares[0]), str(limiares[1])]
    subprocess.run(args, check=True, capture_output=True, text=True)
    nome = f"avaliacao_{modelo.replace('/', '_')}_{conjunto}.json"
    data: dict = json.loads((DADOS / nome).read_text())  # type: ignore[type-arg]
    return data


def linha(r: dict) -> str:  # type: ignore[type-arg]
    return (f"| {r['acuracia']:.3f} | {r['f1_macro']:.3f} | {r['sustenta']['f1']:.3f} | "
            f"{r['contradiz']['f1']:.3f} | {r['neutro']['f1']:.3f} |")


def main() -> None:
    pasta = Path(sys.argv[1])
    treino = json.loads((pasta / "treino.json").read_text())
    val = avaliar(str(pasta), "val")
    lim = (val["limiar_sustenta"], val["limiar_contradiz"])
    teste = avaliar(str(pasta), "teste", lim)
    base_val = avaliar(BASE, "val")
    base = avaliar(BASE, "teste", (base_val["limiar_sustenta"], base_val["limiar_contradiz"]))
    (pasta / "errei_limiares.json").write_text(json.dumps(
        {"sustenta": lim[0], "contradiz": lim[1], "escolhidos_em": "validação (10% do treino)"},
        indent=1))
    (pasta / "errei_avaliacao.json").write_text(json.dumps(
        {**teste, "linha_de_base": base}, ensure_ascii=False, indent=1))
    n = teste["afirmacao_en"]
    card = f"""---
license: cc-by-nc-2.0
language: [pt, en]
base_model: {BASE}
tags: [nli, citation-verification, scientific-claims, cross-encoder, errei]
---

# errei-cita-v1

Cross-encoder multilíngue que estima se um **trecho de uma fonte** (geralmente o resumo, em
inglês) **sustenta**, **contradiz** ou **não permite afirmar** uma frase de artigo que a
cita (em pt-BR ou inglês). Usado pelo `errei` (regras `REFS-ATRIB-*`).

## Como foi feito

- **Base:** `{BASE}` (MIT), já treinada em NLI multilíngue (MNLI + XNLI).
- **Fine-tuning** em CPU, {treino['epocas']} épocas, lote {treino['lote']}, lr {treino['lr']},
  max_len {treino['max_len']}, perda com pesos por classe; {treino['segundos'] // 60} min.
- **Dados:** SciFact (Wadden et al., 2020; CC BY-NC 2.0): afirmações científicas no estilo
  de citação, com resumos e frases-evidência anotadas. Pares no nível da frase: evidência →
  sustenta/contradiz; outras frases do mesmo resumo e frases aleatórias → neutro.
- **Português:** afirmações (e parte das evidências) traduzidas automaticamente com
  `Helsinki-NLP/opus-mt-tc-big-en-pt` (CC BY 4.0), treinando pt→en e pt→pt.
- **Pares:** {treino['pares_treino']} de treino ({treino['classes']}),
  {treino['pares_val']} de validação.
- **Protocolo:** 90% das afirmações de treino para treinar e 10% para escolher os limiares
  (sustenta ≥ {lim[0]}, contradiz ≥ {lim[1]}); o **dev oficial do SciFact** ({n and teste['n']}
  pares afirmação–resumo) ficou reservado como teste e não foi usado em nenhuma decisão.

## Resultados (teste: dev do SciFact, nível do documento)

O modelo julga a afirmação contra cada frase e janela de 2 frases do resumo e decide pela
maior probabilidade, com os limiares acima.

| modelo | afirmação | acurácia | F1 macro | F1 sustenta | F1 contradiz | F1 neutro |
|---|---|---:|---:|---:|---:|---:|
| base (sem fine-tuning) | inglês {linha(base['afirmacao_en'])}
| base (sem fine-tuning) | português {linha(base['afirmacao_pt'])}
| **errei-cita-v1** | inglês {linha(teste['afirmacao_en'])}
| **errei-cita-v1** | português {linha(teste['afirmacao_pt'])}

## Limitações

- Julga contra o **resumo** (ou texto disponível), não contra a obra inteira: "neutro" é o
  resultado normal quando a afirmação está só no corpo do artigo citado.
- Treinado em biomedicina (SciFact); em outras áreas o desempenho tende a cair.
- O português de treino é tradução automática; frases acadêmicas reais em pt-BR podem ser
  mais longas e complexas.
- Um indicador estatístico, não um veredito: confira sempre na fonte.
- **Licença CC BY-NC 2.0** (herdada do SciFact): uso não comercial. O código do errei é MIT.
"""
    (pasta / "README.md").write_text(card)
    print(card)


if __name__ == "__main__":
    main()
