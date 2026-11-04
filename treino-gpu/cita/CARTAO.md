---
license: mit
language: [pt, en]
base_model: microsoft/mdeberta-v3-base
tags: [nli, citation-verification, scientific-claims, cross-encoder, errei]
---

# errei-cita-v2

Cross-encoder multilíngue que estima se um **trecho de uma fonte** (frase do resumo ou do
texto completo) **sustenta**, **contradiz** ou **não permite afirmar** uma frase de artigo
(pt-BR ou inglês). Usado pelo `errei` nos verificadores `refs` (`REFS-ATRIB-*`) e
`literatura` (`LIT-SUG-001` só sai quando este modelo diz "sustenta").

O v2 existe para **tirar a restrição CC BY-NC** dos pesos do `errei-cita-v1`, que vinha do
SciFact. Nenhum dado com cláusula NC é usado.

## Licenças (verificadas em 2026-11-04)

| item | nome | licença | fonte |
|---|---|---|---|
| modelo-base | `microsoft/mdeberta-v3-base` | MIT (tag `license:mit` no Hugging Face) | https://huggingface.co/microsoft/mdeberta-v3-base |
| dados | PUBHEALTH (Kotonya e Toni, 2020) | MIT (LICENSE do repositório dos autores) | https://github.com/neemakot/Health-Fact-Checking · https://huggingface.co/datasets/ImperialCollegeLondon/health_fact |
| dados | anotações do projeto errei | CC BY 4.0 | `treino-gpu/anotacoes/` |
| dados (opcional) | SciTail (Khot et al., 2018) | **a confirmar**: o cartão do Hugging Face não declara licença; só entra se listado em `[dados] confirmadas` | https://allenai.org/data/scitail |
| dados (opcional) | SNLI (Bowman et al., 2015) | CC BY-SA 4.0: só com `aceitar_sa = true`, e então os pesos saem em CC BY-SA 4.0 | https://huggingface.co/datasets/stanfordnlp/snli |
| tradução pt | `Helsinki-NLP/opus-mt-en-ROMANCE` | Apache-2.0 | https://huggingface.co/Helsinki-NLP/opus-mt-en-ROMANCE |
| **recusado** | SciFact | CC BY-NC 2.0 | https://huggingface.co/datasets/allenai/scifact |
| **recusado** | XNLI | CC BY-NC 4.0 | https://huggingface.co/datasets/facebook/xnli |
| **recusado** | ANLI | CC BY-NC 4.0 | https://huggingface.co/datasets/facebook/anli |

Licença dos pesos: **MIT** com os conjuntos padrão (PUBHEALTH + anotações). Se você ligar
`aceitar_sa` (SNLI), os pesos passam a ser **CC BY-SA 4.0**: ajuste o campo `license` acima
antes de publicar. A lista exata de conjuntos usados em cada pacote está em
`manifesto.json` e na seção gerada abaixo.

## Dados

- **PUBHEALTH**: afirmações de saúde pública × explicação do checador. `true` → sustenta,
  `false` → contradiz (`mixture` e `unproven` ficam de fora). Neutros: trechos do **texto
  completo** de outras matérias e explicações de outras afirmações.
- **Português**: metade das afirmações traduzida automaticamente para pt (Marian, Apache-2.0).
  O trecho da fonte fica no original, como no uso real (afirmação pt-BR × fonte em inglês).
- **Anotações próprias**: pares reais pt-BR × trecho de fonte com licença aberta.
- **Divisão**: por afirmação (hash estável com a semente), então a mesma frase nunca aparece
  em treino e teste; 90% treino, 5% validação (limiares), 5% teste.

## Limitações

- PUBHEALTH é de **saúde pública e checagem de fatos**, não de artigos científicos de todas
  as áreas. O desempenho em outras áreas tende a cair, e as anotações próprias existem para
  corrigir isso.
- O português da afirmação é, em grande parte, tradução automática.
- As métricas são no nível do par (frase × trecho), não do documento.
- Um indicador estatístico, não um veredito: confira sempre na fonte.
