# Prompt para Claude Code: errei, busca de literatura por afirmação

Cole o texto abaixo no Claude Code, dentro da pasta do repositório `errei`.

---

## Objetivo em uma frase

Fazer o `errei` encontrar, para cada afirmação do artigo que precisa de apoio, artigos **nacionais e internacionais** que **digam diretamente aquilo que a afirmação diz**, mostrando o trecho da fonte que prova isso. E criar o código para eu treinar o modelo de validação numa GPU alugada da Hostinger.

## O que vai existir quando você terminar

### A. Um comando novo que funciona

```
errei caminho/artigo --online --only literatura
errei caminho/artigo --online --only literatura --texto-completo
```

- Sem `--online`, o verificador `literatura` **não faz nenhuma requisição** e o relatório diz que foi pulado (`CORE-NET-001`).
- Com `--online`, ele roda junto com os outros verificadores. `--skip literatura` o desliga.
- Opções novas: `--lit-max N` (máximo de fontes por afirmação, padrão 3), `--lit-ano-min AAAA`, `--lit-idioma pt,en` (padrão: todos).

### B. Esta saída exata no terminal e nos relatórios `md`, `json` e `pdf`

Para uma afirmação com fonte que **sustenta**:

```
LIT-SUG-001  sugestão  introducao.tex:42:1
Afirmação : "O uso de redes neurais reduz o tempo de diagnóstico."
Fonte     : Sobrenome et al. (2022). Título do artigo. Periódico. DOI: 10.xxxx/xxxx
Base      : OpenAlex     Idioma: en
Trecho    : "<até 300 caracteres copiados da fonte, no idioma original>"  (p. 5)
Relação   : sustenta     Confiança: média
Aviso     : indicador, não veredito. Leia a fonte antes de citar.
```

Para fonte do mesmo tema que **não** diz o que a afirmação diz:

```
LIT-REL-001  info  introducao.tex:42:1
Fonte relacionada (NÃO sustenta a afirmação): Sobrenome (2020). Título. DOI: ...
Motivo: nenhum trecho do resumo ou do texto aberto afirma o que a frase afirma.
```

Quando nada é encontrado: `LIT-NONE-001  info  introducao.tex:42:1  nenhuma fonte encontrada para esta afirmação.`
Quando o trecho está em outro idioma: `LIT-LANG-001  info` e o trecho aparece **no idioma original**. Se você traduzir para ajudar, rotule como "tradução automática, não é citação".

### C. Regra que decide o que aparece

1. Uma fonte só vira `LIT-SUG-001` se o modelo `errei-cita` classificar a relação frase × trecho como **sustenta**. A comparação é com cada frase do resumo e, com `--texto-completo`, com cada trecho do PDF aberto.
2. Se não houver trecho que sustente, a fonte **nunca** vira `LIT-SUG-001`. No máximo `LIT-REL-001`.
3. Toda fonte precisa ser **confirmada em OpenAlex, Crossref, Semantic Scholar ou arXiv**. O que não for confirmado é descartado e contado (como já faz o `NAC-IA-001`).
4. A busca **não** é restrita ao Brasil nem ao português. A consulta é feita em português **e** em inglês.
5. Ordem das sugestões: força do suporte direto, depois qualidade da fonte (Qualis do CSV do usuário e métricas do OpenAlex, que o errei já lê), depois ano.

### D. O que NUNCA pode acontecer

- Alterar qualquer `.tex` ou `.bib` do usuário. O teste de aceitação compara o hash antes e depois.
- Sair uma requisição de rede sem `--online`.
- Aparecer fonte inventada, ou chave de API em cache, relatório ou log.
- Uma exceção do verificador derrubar a execução: ela vira `CORE-CHECKER-001` e os outros verificadores continuam.
- Tratar o resultado como veredito. O relatório mantém a seção **Limitações**.

### D2. Regra inegociável: o projeto é 100% open source

O `errei` continua **inteiramente open source (MIT)**, também nos modelos, nos dados e nas dependências. Ser poderoso não justifica abrir exceção.

1. **Nenhuma dependência obrigatória pode ser proprietária ou paga.** Toda biblioteca nova precisa ter licença aprovada pela OSI (MIT, Apache-2.0, BSD etc.). Registre cada uma, com licença, no `README.md`.
2. **Nenhuma API paga é necessária** para nenhuma função. As bases usadas são abertas (OpenAlex, Crossref, Semantic Scholar, arXiv). O Gemini continua **opcional**, desligado por padrão, e o errei tem que funcionar por inteiro sem ele.
3. **Modelos:** o modelo-base e os pesos publicados precisam ter licença aberta que permita uso comercial e redistribuição (Apache-2.0, MIT ou equivalente). **Verifique a licença de cada modelo-base antes de usá-lo** e escreva o resultado no `CARTAO.md`.
4. **Dados de treino:** só use conjuntos com licença aberta que permita uso comercial (CC0, CC BY, Apache-2.0, MIT etc.). **Não use dados CC BY-NC**, como o SciFact, que é a licença que hoje restringe os pesos do `errei-cita`. O `errei-cita-v2` existe para **tirar essa restrição**. Verifique a licença de cada conjunto antes de usar e registre no cartão.
5. **Dados próprios:** os exemplos que eu anotar à mão serão publicados em CC BY ou CC0. Crie o formato de anotação e a licença no repositório.
6. **Texto completo de artigos:** vale qualquer texto de **acesso livre**, com ou sem licença aberta (CC BY etc.), obtido de forma legítima: respeitando o `robots.txt` (inclusive `Crawl-delay`) e o limite de requisições, com User-Agent identificado, sem contornar bloqueios, captchas ou paywalls e sem usar sites que distribuem cópias sem autorização. O texto serve só para comparar com a afirmação. Trechos mostrados no relatório têm no máximo 300 caracteres e sempre trazem a fonte e o link, como citação. Texto completo **não** entra nos dados de treino, a não ser que tenha licença aberta que permita uso comercial (regra 4).
7. **Treinar em GPU alugada não torna o projeto fechado.** O que importa é que código, dados e pesos fiquem abertos e que o errei rode sem a Hostinger.
8. **Teste obrigatório:** um teste que lê as dependências e falha se aparecer licença não aprovada. O `CHANGELOG.md` registra qualquer troca de licença.

### E. Arquivos criados ou alterados

| Arquivo | O que muda |
|---|---|
| `src/errei/checkers/literatura.py` | verificador novo, registrado em `errei.checkers` no `pyproject.toml` |
| `src/errei/` (cache e clientes de API existentes) | reaproveitar o cache `http.sqlite`; não criar outro |
| `tests/fixtures/literatura/` | respostas de API gravadas, para testar sem rede |
| `tests/test_literatura.py` | testes abaixo |
| `README.md`, `CHANGELOG.md` | documentar comando, flags e regras `LIT-*` |
| `errei explain --list` | incluir `LIT-SUG-001`, `LIT-REL-001`, `LIT-NONE-001`, `LIT-LANG-001` |
| `treino-gpu/` | código de treino separado (seção abaixo) |

### F. Testes que precisam passar (sem rede)

1. Fonte em inglês que sustenta a afirmação em português → `LIT-SUG-001`, com trecho em inglês e `LIT-LANG-001`.
2. Fonte do mesmo tema que não sustenta → `LIT-REL-001`, **nunca** `LIT-SUG-001`.
3. Referência que não existe em nenhuma base → descartada e contada.
4. Afirmação sem resultado → `LIT-NONE-001`.
5. Execução sem `--online` → zero conexões de rede.
6. Hash dos `.tex` e `.bib` idêntico antes e depois.
7. Verificação de licenças das dependências: falha se houver licença não aprovada.
8. `pytest`, `ruff check src tests`, `ruff format --check src tests` e `mypy` sem erros.

## Código de treino separado: `treino-gpu/`

Nesta tarefa, **crie** o código para eu retreinar o `errei-cita` (versão `errei-cita-v2`) **com texto completo e pares em português**. **Não rode o treino**: eu vou rodar na GPU da Hostinger. O pacote `errei` só carrega os pesos prontos.

### Estrutura exata

```
treino-gpu/
  LEIAME.md          passo-a-passo e recomendação de GPU
  requirements.txt   versões fixas (torch com CUDA, transformers, datasets, accelerate, peft)
  preparar.sh        prepara a máquina
  enviar.sh          copia checkpoints e resultados para o meu VPS
  config/cita.toml   hiperparâmetros versionados
  cita/dados.py      baixa e prepara os dados, salva a divisão treino/validação/teste
  cita/treinar.py    treina; aceita --epocas --batch --lr --saida --retomar
  cita/avaliar.py    avalia no teste e grava metricas.json
  cita/empacotar.py  gera errei-cita-v2.tar.gz + sha256 no formato de `errei modelo baixar`
  cita/CARTAO.md     cartão do modelo (dados, licença, métricas, limitações)
  fumaca.sh          teste mínimo em CPU (poucos exemplos, 1 passo)
```

### Comandos que eu vou executar na GPU, nesta ordem

```
sh treino-gpu/preparar.sh
python treino-gpu/cita/dados.py
tmux new -s treino
python treino-gpu/cita/treinar.py --config treino-gpu/config/cita.toml
python treino-gpu/cita/avaliar.py
python treino-gpu/cita/empacotar.py
sh treino-gpu/enviar.sh
```

Se a máquina cair: `python treino-gpu/cita/treinar.py --retomar` continua do último checkpoint.

### Comportamento obrigatório

- `preparar.sh` roda `nvidia-smi`, instala as dependências e **falha com mensagem clara** se o PyTorch não enxergar a GPU.
- Checkpoint a cada N passos e ao fim de cada época. O disco das instâncias GPU da Hostinger é **efêmero** e a instância **é destruída se os créditos acabarem**. Por isso `enviar.sh` precisa copiar por `rsync` ou `scp` para o destino da variável `DESTINO_VPS`.
- `bf16` quando a GPU suportar; acumulação de gradiente; batch que se ajusta à memória; LoRA (`peft`) só se eu pedir um modelo maior.
- Semente fixa. Métricas em JSON, no mesmo formato que `errei modelo info` mostra.
- Antes de eu iniciar, `treinar.py --estimar` imprime **tempo previsto, preço por hora e custo total**.
- `dados.py` **recusa** conjuntos cuja licença não permita uso comercial e imprime o motivo. O `CARTAO.md` lista, para cada dado e para o modelo-base, nome, licença e link da fonte.
- `fumaca.sh` roda em CPU, sem GPU, e termina em menos de 2 minutos.

### GPU a recomendar no `LEIAME.md` (preços a conferir na Hostinger antes de contratar)

| Quando | GPU | Aproximado |
|---|---|---|
| `errei-cita` e outros classificadores de ~100 M de parâmetros | **RTX 4090 (24 GB)** | US$ 0,42/h |
| LoRA em modelos de 7B a 13B | **RTX PRO 6000** | US$ 0,65/h |
| Só se faltar capacidade | A100 ou B200 | várias vezes mais caras |

## Forma de trabalhar (ordem obrigatória)

1. Leia `README.md`, `CHANGELOG.md`, `pyproject.toml`, `src/errei/` (verificadores `refs`, `nacionais` e `plagio`, o cache e o protocolo `Checker`), `tests/` e `.claude/skills/errei`.
2. **Pare e me mostre um plano curto**: arquivos que vai criar ou alterar e decisões de design. Espere minha aprovação.
3. Implemente em commits pequenos, rodando `pytest`, `ruff` e `mypy` a cada commit.
4. Se faltar dado ou houver dúvida (por exemplo, qual base usar como primária), **pergunte antes de supor**.
5. No fim, entregue um resumo de até 10 linhas: o que mudou, como rodar o comando novo, como rodar o treino e o que ficou de fora.

## Fora do escopo

Interface web, plugin de editor, Consensus Meter, Study Snapshot, e **rodar** qualquer treino.
