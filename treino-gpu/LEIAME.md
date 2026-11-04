# treino-gpu: treinar o errei-cita-v2 numa GPU alugada

Código para retreinar o modelo de validação de citações (**errei-cita-v2**) com texto
completo e pares em português, **só com dados e modelo-base de licença aberta que permite
uso comercial**. O v2 substitui o v1, cujos pesos são CC BY-NC por causa do SciFact.

O pacote `errei` **não depende** desta pasta nem da Hostinger: ele só carrega os pesos
prontos (`errei modelo instalar` / `errei modelo baixar --nome errei-cita-v2`). Código,
dados e pesos continuam abertos. Treinar em GPU alugada não muda isso.

## Qual GPU contratar

Preços aproximados: **confira na Hostinger antes de contratar** e ajuste
`[custo] preco_hora_usd` em `config/cita.toml`.

| quando | GPU | aproximado |
|---|---|---|
| `errei-cita` e outros classificadores de ~100–300 M de parâmetros (padrão: mDeBERTa-v3-base) | **RTX 4090 (24 GB)** | US$ 0,42/h |
| LoRA em modelos de 7B a 13B (`[modelo] lora = true`) | **RTX PRO 6000** | US$ 0,65/h |
| só se faltar capacidade | A100 ou B200 | várias vezes mais caras |

Com os dados padrão (PUBHEALTH, cerca de 30 mil pares mais as traduções), 3 épocas numa
RTX 4090 levam por volta de 1 hora. Rode `treinar.py --estimar` para a conta exata, medida
na própria GPU.

## Antes de começar (no seu computador)

```sh
sh treino-gpu/fumaca.sh     # CPU, sem rede, < 2 min: confere que tudo roda
```

Tenha um VPS com acesso SSH por chave para receber os resultados, porque **o disco da
instância GPU é efêmero e a instância é destruída se os créditos acabarem**.

## Passo a passo na GPU, nesta ordem

```sh
git clone https://github.com/reinanbr/errei && cd errei
export DESTINO_VPS=usuario@meu-vps:/srv/errei-treino   # para onde vão os resultados

sh treino-gpu/preparar.sh                 # nvidia-smi, venv .venv-gpu, dependências; falha se o torch não vê a GPU
. .venv-gpu/bin/activate
python treino-gpu/cita/dados.py           # baixa, checa licenças, traduz e divide (treino/validação/teste)
python treino-gpu/cita/treinar.py --estimar   # tempo previsto, preço por hora e custo total
tmux new -s treino
python treino-gpu/cita/treinar.py --config treino-gpu/config/cita.toml
python treino-gpu/cita/avaliar.py         # limiares na validação, métricas no teste -> metricas.json
python treino-gpu/cita/empacotar.py       # errei-cita-v2.tar.gz + sha256sums-modelo.txt
sh treino-gpu/enviar.sh                   # copia tudo para o VPS (rsync; sem rsync, scp)
```

Para não perder nada se a instância cair, deixe o envio periódico rodando numa segunda
janela do tmux (`Ctrl-b c`):

```sh
sh treino-gpu/enviar.sh --loop 600        # a cada 10 minutos
```

**Se a máquina cair:** numa instância nova, traga de volta `treino-gpu/saida` e
`treino-gpu/dados` do VPS (rsync no sentido inverso) e rode

```sh
python treino-gpu/cita/treinar.py --retomar
```

Ele continua do último checkpoint (a cada `checkpoint_passos` e ao fim de cada época),
com o mesmo otimizador, a mesma posição nos dados e a mesma semente.

## O que cada arquivo faz

| arquivo | função |
|---|---|
| `requirements.txt` | versões fixas (torch CUDA 12.4, transformers, datasets, accelerate, peft) |
| `preparar.sh` | confere `nvidia-smi`, cria `.venv-gpu`, instala e **falha** se o PyTorch não enxergar a GPU |
| `config/cita.toml` | hiperparâmetros versionados, conjuntos de dados, preço por hora |
| `cita/dados.py` | baixa os conjuntos, **recusa** os de licença NC (e SA/"a confirmar", salvo se você liberar), traduz afirmações para pt, divide por afirmação e grava `manifesto.json` |
| `cita/treinar.py` | treino com semente fixa, bf16 quando a GPU suporta, acumulação de gradiente, batch que cai pela metade sozinho se faltar memória, checkpoints e `--retomar`; LoRA só com `[modelo] lora = true` |
| `cita/avaliar.py` | limiares na validação, métricas no teste por idioma da afirmação, no formato de `errei modelo info` |
| `cita/empacotar.py` | gera `errei-cita-v2.tar.gz` + `sha256sums-modelo.txt` com o cartão (`README.md`) e o manifesto de dados |
| `cita/CARTAO.md` | cartão do modelo: dados, licenças, limitações |
| `anotacoes/` | formato e licença (CC BY 4.0) dos pares anotados à mão |
| `enviar.sh` | rsync/scp de checkpoints, métricas e pacote para `DESTINO_VPS` |
| `fumaca.sh` | teste mínimo em CPU, sem rede, em menos de 2 minutos |

Opções do `treinar.py`: `--epocas`, `--batch`, `--lr`, `--saida`, `--dados`, `--modelo-base`,
`--retomar`, `--estimar`, `--max-passos`, `--fumaca`.

## Licenças: a regra

- Entram só dados com licença que permite **uso comercial**: CC0, CC BY, MIT, Apache-2.0.
  `dados.py --listar` mostra a decisão para cada conjunto e o motivo.
- **CC BY-NC é recusado sempre** (SciFact, XNLI, ANLI).
- **CC BY-SA** (SNLI) só com `aceitar_sa = true`. Nesse caso os pesos saem em CC BY-SA.
- Licença **a confirmar** (SciTail) só entra se você conferir na fonte e listar em
  `[dados] confirmadas`.
- O modelo-base `microsoft/mdeberta-v3-base` é MIT. Ao trocar de base (`--modelo-base`),
  confira a licença e atualize `[modelo] base_licenca` e o `CARTAO.md`.
- Dependências desta pasta: torch (BSD-3-Clause), transformers, tokenizers, datasets,
  accelerate, peft e sentencepiece (Apache-2.0), protobuf (BSD-3-Clause), sacremoses (MIT),
  pandas e numpy (BSD-3-Clause), pyarrow (Apache-2.0).

## Depois do treino

```sh
# no seu computador, com o pacote vindo do VPS
tar xzf errei-cita-v2.tar.gz
errei modelo instalar errei-cita-v2 --nome errei-cita-v2
errei modelo info          # mostra as métricas; o errei passa a preferir o v2 ao v1
# publicar (mantenedor)
gh release upload modelos errei-cita-v2.tar.gz sha256sums-modelo.txt --clobber
```
