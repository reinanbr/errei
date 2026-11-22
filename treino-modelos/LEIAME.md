# treino-modelos: banco de treino e modelos 2 a 9 do gpu_train_list.md

O pacote `errei` não depende desta pasta. Ela monta um banco de treino aberto, classifica
as revistas (Qualis CAPES, Scopus, Web of Science) e treina numa GPU alugada (Hostinger)
os modelos que tiram do errei a dependência de outras IAs. O `errei-cita-v2` (item 1)
continua em `treino-gpu/`. A integração de cada modelo no errei é um passo separado.

| chave | pacote | tarefa | base (licença declarada) | GPU |
|---|---|---|---|---|
| `resumo` | errei-resumo-v2 | papel das frases do resumo | mdeberta-v3-base (MIT) | RTX 4090 |
| `busca` | errei-busca | embeddings pt↔en | multilingual-e5-base (MIT) | RTX 4090 |
| `chaves` | errei-chaves | palavras-chave (seq2seq) | mt5-base (Apache-2.0) | RTX 4090 |
| `ref` | errei-ref | campos da referência (BIO) | mdeberta-v3-base | RTX 4090 |
| `area` | errei-area | área do trabalho | mdeberta-v3-base | RTX 4090 |
| `secoes` | errei-secoes | elemento de cada parágrafo | mdeberta-v3-base | RTX 4090 |
| `ia` | errei-ia | humano × IA | mdeberta-v3-base; textos de Qwen2.5/Mistral (Apache-2.0) | RTX PRO 6000 (gerar) + 4090 |
| `trad` | errei-trad | tradutor pt↔en | mt5-base | RTX 4090 |
| `base` | errei-base | pré-treino MLM no domínio | mdeberta-v3-base | RTX PRO 6000 |

**Confira a licença de cada base no Hugging Face** antes de treinar e anote a data em
`config/modelos.toml`.

## 1. Banco (no VPS barato, sem GPU, leva dias)

A coleta usa só a biblioteca padrão (Python ≥ 3.10; `pip install tomli` no 3.10).

```sh
export OPENALEX_API_KEY=...          # chave gratuita da sua conta no openalex.org; sem ela o limite é bem menor
tmux new -s coleta
python treino-modelos/banco/coletar.py tudo        # openalex → fontes → scielo → textos; retomável
python treino-modelos/banco/consultar.py           # números do banco
```

- Texto (resumos, seções) só é guardado com licença CC BY, CC0 ou domínio público. NC e ND
  nunca entram. Metadados do OpenAlex são CC0.
- O que coletar fica em `config/banco.toml`: consultas do OpenAlex, coleções da SciELO e
  limites.
- **Não testado ao vivo:** os coletores de texto completo (Europe PMC e XML da SciELO)
  estavam fora do ar durante o desenvolvimento. Confira com `coletar.py textos --max 50`.

## 2. Classificar as revistas (Qualis, Scopus, WoS)

As listas não têm API aberta. Baixe os arquivos e importe; o casamento é pelo ISSN.

| sistema | onde baixar | comando |
|---|---|---|
| Qualis CAPES | Plataforma Sucupira → Qualis → classificações de periódicos (quadriênio), exportar planilha (`.xls` antigo: converta para `.xlsx`/`.csv`) | `--qualis arq.xlsx --edicao 2021-2024` |
| Scopus | lista de fontes do Scopus (Source title list, xlsx da Elsevier) | `--scopus arq.xlsx` |
| CiteScore | planilha do CiteScore (Scopus Sources, acesso institucional) | `--citescore arq.xlsx` |
| Web of Science | Master Journal List (mjl.clarivate.com, conta gratuita), um CSV por coleção | `--wos SCIE.csv --wos ESCI.csv` (ou `arq.csv:SSCI`) |

```sh
python treino-modelos/banco/classificar.py --qualis ... --scopus ... --citescore ... --wos ... --openalex
python treino-modelos/banco/consultar.py --amostra 5 --qualis A1 A2 --scopus
python treino-modelos/banco/consultar.py --exportar obras.csv --wos SCIE SSCI
```

Guarde as listas em `treino-modelos/listas/`, que fica fora do git. Os termos da Elsevier
e da Clarivate não permitem redistribuí-las, e os pacotes de modelo não as levam.

Para treinar só com revistas classificadas, use `[<modelo>.filtros]` no
`config/modelos.toml`, por exemplo `qualis = ["A1","A2","A3","A4"]`, `scopus = true` ou
`wos = ["SCIE","SSCI"]`. Cada exemplo leva a classe da sua revista. A avaliação mostra a
métrica por faixa do Qualis, Scopus e WoS, e o cartão do modelo resume as revistas usadas.

## 3. Treinar na GPU da Hostinger

Contrate a instância com driver NVIDIA. O disco é efêmero: tenha um VPS com SSH por chave
para receber os resultados.

```sh
git clone https://github.com/reinanbr/errei && cd errei
scp vps:/srv/errei/banco.sqlite treino-modelos/dados/    # o banco pronto
export DESTINO_VPS=usuario@meu-vps:/srv/errei-treino
sh treino-modelos/preparar.sh && . .venv-modelos/bin/activate
tmux new -s envio 'sh treino-modelos/enviar.sh --loop 600'
tmux new -s treino
sh treino-modelos/rodar.sh resumo       # dados → --estimar → treino (retoma) → avaliação → pacote → envio
```

O `rodar.sh` encadeia os scripts, que também rodam sozinhos:

- `dados.py --modelo X`: grava `dados/X/{treino,validacao,teste}.jsonl` e
  `manifesto.json`. A divisão é por obra e o script recusa obras NC/ND.
- `treinar.py --modelo X [--estimar|--retomar|--max-passos N]`:
  - checkpoints atômicos;
  - se faltar memória, divide o lote pela metade e dobra a acumulação;
  - bf16 automático.
- `avaliar.py --modelo X`: métricas no teste, limiares na validação e recortes por
  estrato.
- `empacotar.py --modelo X`: gera `saida/dist/<nome>.tar.gz`, `sha256sums-modelo.txt` e o
  cartão README.
- `gerar_ia.py`: textos de IA para o `errei-ia`.
  - Só modelos Apache-2.0/MIT rodando na própria GPU.
  - Recusa Gemini, Claude e GPT. Mistral exige aceitar os termos no Hugging Face.
  - `--motor vllm` é bem mais rápido.

Ordem sugerida: `resumo`, `ref`, `busca`, `area`, `secoes`, `chaves`, `ia`, `trad`. Rode
`base` antes, se quiser que os outros partam dele: ponha
`base = "treino-modelos/saida/base/final"` em cada seção.

## Fumaça (no seu computador, CPU, sem rede)

```sh
sh treino-modelos/fumaca.sh            # os 9 modelos, ~10 s
```

O que a fumaça faz:

1. Cria um banco sintético e importa listas Qualis/Scopus/CiteScore/WoS falsas.
2. Gera textos de IA com um modelo minúsculo.
3. Para cada modelo: dados, treino, retomada, estimativa, avaliação e pacote, conferindo o
   sha256.
