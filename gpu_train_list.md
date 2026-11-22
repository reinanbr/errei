# O que treinar em GPU externa para tirar a dependência de outras IAs

Hoje o errei depende de IA de terceiros em dois níveis:

1. **Serviços online opcionais** (desligados por padrão):
   - **Gemini** (`--ia-online`, `src/errei/net/gemini.py`): consultas e obras brasileiras
     sugeridas no `nacionais` (`NAC-SUG-001`) e orientações do que escrever nos elementos
     ausentes no `completude` (`COMP-IA-001`);
   - **Claude Code** (`--ia-claude`, `src/errei/net/claudecode.py`): no `apud`
     (`APUD-IA-001`), ver se a obra consultada cita a original, se atribui a ela a ideia da
     frase e se a original está acessível.
2. **Modelos de terceiros rodando localmente:**
   - base `MoritzLaurer/multilingual-MiniLMv2-L6-mnli-xnli` do `errei-cita-v1` e do
     `errei-resumo-v1`. Ela foi ajustada com o XNLI, que é CC BY-NC;
   - tradutores Helsinki-NLP: `opus-mt-ROMANCE-en` na consulta do `literatura`, e
     `opus-mt-en-ROMANCE` e `opus-mt-tc-big-en-pt` na tradução dos dados de treino;
   - adaptador `ExternalDetector` do verificador `ia`, para um detector de texto de IA de
     terceiros.

Abaixo, o que dá para treinar para trocar cada uma dessas peças por modelo próprio do
errei, aberto e local.

## Regras para todos os itens

- **Dados:** só licença que permite uso comercial (CC0, CC BY, MIT, Apache-2.0). Nunca
  CC BY-NC (SciFact, XNLI, ANLI). Texto completo só entra no treino com CC BY ou CC0; o
  de acesso livre sem licença aberta serve só para comparar (regra 6 do `prompt.md`).
- **Modelo-base:** licença aberta com uso comercial. As licenças citadas aqui são as
  declaradas pelas fontes. **Confira cada uma antes de usar** e registre no cartão do
  modelo, como o `treino-gpu/cita/dados.py` já faz.
- **Nada de respostas do Gemini, do Claude ou do ChatGPT como dado de treino.** Os termos
  desses serviços restringem usar as respostas para desenvolver modelos. Além disso, o
  modelo herdaria os erros deles. Texto "gerado por IA" para treino só sai de modelos
  abertos (Apache-2.0) rodando na própria GPU.
- O pacote `errei` continua sem treinar nada. Ele só carrega pesos prontos
  (`errei modelo baixar`/`instalar`) e cai no comportamento atual quando o modelo não
  está instalado, como já fazem o `citecheck` e o `resumocheck`.

## Resumo

Preços da GPU vêm do `treino-gpu/LEIAME.md` (RTX 4090 ≈ US$ 0,42/h, RTX PRO 6000 ≈
US$ 0,65/h). Os tempos são ordem de grandeza: meça com `--estimar` na própria GPU.

| # | modelo | tira a dependência de | GPU | tempo aprox. | código |
|---|---|---|---|---|---|
| 1 | `errei-cita-v2` | base MoritzLaurer (XNLI) e SciFact NC do v1; parte do Claude Code no `apud` | RTX 4090 | ~1 h | **pronto** (`treino-gpu/`) |
| 2 | `errei-resumo-v2` | base MoritzLaurer (XNLI) do `errei-resumo-v1` | RTX 4090 | < 1 h | adaptar `treino/resumo` |
| 3 | `errei-busca` (bi-encoder pt↔en) | Gemini no `nacionais`; tradutor na consulta do `literatura` | RTX 4090 | 2–4 h | novo |
| 4 | `errei-chaves` (palavras-chave) | consultas do Gemini no `nacionais` | RTX 4090 | 2–3 h | novo |
| 5 | `errei-ref` (leitor de referências) | Claude Code lendo listas de referências; regex do `documento` | RTX 4090 | 1–2 h | novo |
| 6 | `errei-secoes` (área e partes das seções) | Gemini no `completude` | RTX 4090 | 4–8 h | novo |
| 7 | `errei-ia` (detector) | detector externo do verificador `ia` | RTX PRO 6000 + RTX 4090 | 6–12 h | novo |
| 8 | `errei-trad` (tradutor pt↔en) | tradutores Helsinki | RTX 4090 | horas (ajuste) a 1–2 dias (do zero) | novo |
| 9 | `errei-base` (pré-treino no domínio) | nenhuma diretamente; melhora todos os outros | RTX 4090 ou RTX PRO 6000 | ~1 dia | novo |

## 1. `errei-cita-v2`: atribuição de citações (pronto para rodar)

- **Tira:** a base MoritzLaurer e o SciFact, que deixam os pesos do v1 em CC BY-NC 2.0. É
  também a peça que substitui o Claude Code na pergunta "a consultada atribui à original
  a ideia da frase?". Com `--texto-completo`, o `apud` já usa o errei-cita nos
  `APUD-TEXTO-001`/`002`.
- **Tarefa:** frase do artigo × trecho da fonte → sustenta / contradiz / neutro.
- **Dados:** PUBHEALTH, SciTail e SNLI conforme a checagem de licença, mais as anotações
  CC BY 4.0 de `treino-gpu/anotacoes/`. Mais pares anotados em pt-BR é o que mais melhora
  o modelo.
- **Base:** `microsoft/mdeberta-v3-base` (MIT).
- **Como rodar:** o passo a passo está em `treino-gpu/LEIAME.md`.

## 2. `errei-resumo-v2`: papel das frases do resumo (NBR 6028)

- **Tira:** a base MoritzLaurer do `errei-resumo-v1`.
- **Tarefa:** classificar cada frase do resumo em contexto, objetivo, método, resultado ou
  **conclusão**. O CSAbstruct não tem a classe conclusão, e hoje ela sai de palavras-chave.
- **Dados:** CSAbstruct (Apache-2.0) com tradução pt-BR, mais resumos da SciELO em CC BY
  anotados à mão com a classe conclusão. Muitos resumos estruturados da SciELO
  ("Objetivo:", "Método:"...) dão rótulos fracos de graça.
- **Base:** `microsoft/mdeberta-v3-base` (MIT).
- **Código:** portar `treino/resumo/treinar.py` (CPU) para `treino-gpu/resumo/`, no padrão
  do `cita`: checagem de licença, semente fixa, checkpoints, `avaliar.py` e
  `empacotar.py`. O `cita/treinar.py` já serve quase sem mudança, porque também é
  classificação de sequência.

## 3. `errei-busca`: busca semântica bilíngue

- **Tira:**
  - o Gemini no `nacionais`: em vez de pedir à IA consultas e obras brasileiras, o errei
    busca no OpenAlex e reordena os candidatos pela proximidade de sentido com a frase;
  - o tradutor pt→en na consulta do `literatura`: frase em pt e resumo em en ficam no
    mesmo espaço, sem precisar traduzir.
- **Tarefa:** bi-encoder (embeddings) multilíngue, em que frase ou resumo em pt e resumo
  em en caem perto quando falam da mesma coisa. Quem decide se a fonte **sustenta** a
  frase continua sendo o errei-cita.
- **Dados:** pares bilíngues da SciELO (título e resumo em pt e em en do mesmo artigo;
  conferir a licença por revista, porque a maioria é CC BY), além de título ↔ resumo e
  palavras-chave ↔ resumo. Negativos difíceis vêm de artigos da mesma área. Os metadados
  do OpenAlex são CC0.
- **Base:** `intfloat/multilingual-e5-base` (MIT) ou `microsoft/mdeberta-v3-base` (MIT).
  Treino com `sentence-transformers` (Apache-2.0).
- **No errei:** módulo novo (`errei/busca.py`) no molde do `citecheck`, distribuído por
  `errei modelo baixar`. Sem o modelo, fica a busca atual por palavras-chave.

## 4. `errei-chaves`: palavras-chave e consultas

- **Tira:** as consultas que o Gemini sugere no `nacionais` e melhora a função
  `keywords()` heurística.
- **Tarefa:** frase ou resumo → 3 a 6 palavras-chave em pt. Pode ser seq2seq (gerar) ou
  extração por marcação de tokens, que é mais barata e nunca inventa termo.
- **Dados:** resumo → palavras-chave do autor, da SciELO (CC BY); palavras-chave e tópicos
  do OpenAlex (CC0).
- **Base:** `google/mt5-base` (Apache-2.0) para gerar, ou `mdeberta-v3-base` (MIT) para
  extrair.
- **Observação:** com o item 3 pronto, este perde importância. A busca pode partir das
  palavras do próprio texto e o bi-encoder reordena. Dá para fundir os dois.

## 5. `errei-ref`: leitor de referências

- **Tira:**
  - parte do Claude Code no `apud`: quando OpenAlex, Crossref e Semantic Scholar não têm a
    lista de referências da consultada, o errei lê a lista no PDF de acesso livre e acha a
    original pelos campos, não só pelo sobrenome;
  - as expressões regulares de `src/errei/documento/referencias.py`, que separam as
    referências de `.docx` e `.pdf` em ABNT, APA, Chicago, IEEE e Vancouver.
- **Tarefa:** marcação de tokens numa referência: autor, ano, título, periódico, volume,
  número, páginas, editora, DOI, URL.
- **Dados:** sintéticos e sem problema de licença. Metadados do OpenAlex e do Crossref (só
  os campos bibliográficos, não os resumos) são formatados com `citeproc-py` (BSD) nos
  estilos CSL ABNT, APA, Vancouver e IEEE. Depois entra ruído de PDF: hifenização,
  quebras de linha, campos faltando, erros de OCR. O rótulo de cada token sai de graça.
- **Base:** `microsoft/mdeberta-v3-base` (MIT).

## 6. `errei-secoes`: área e partes de cada seção

- **Tira:** o Gemini no `completude` (`COMP-IA-001`).
- **Proposta, sem gerar texto:** segue a regra de que a IA não escreve o trabalho. São dois
  classificadores:
  1. **área:** título + resumo → grande área do CNPq ou tópico do OpenAlex;
  2. **partes de cada seção:** frases da introdução (contexto, lacuna, objetivo), do método
     (participantes, instrumentos, procedimentos, análise) etc.

  A orientação para um elemento ausente junta o modelo fixo de cada elemento, que já existe,
  com "o que costuma aparecer neste elemento na sua área". Essa segunda parte vem de
  estatísticas de artigos CC BY da mesma área.
- **Dados:** textos completos CC BY da SciELO. Os títulos das seções dão rótulos fracos;
  uma amostra anotada à mão serve para validar.
- **Base:** `microsoft/mdeberta-v3-base` (MIT).
- **Alternativa não recomendada como primeira:** um LLM aberto de 7B (ex.: Mistral-7B ou
  Qwen2.5-7B, Apache-2.0) ajustado com LoRA na RTX PRO 6000 (`[modelo] lora = true` já
  existe). Ele gera texto livre, é mais difícil de controlar e precisaria de dados de
  instrução que não venham do Gemini nem do Claude.

## 7. `errei-ia`: detector próprio de texto gerado por IA

- **Tira:** o adaptador `ExternalDetector` (detector de terceiros) e complementa os pesos
  heurísticos de `data/ia_pesos.tsv`.
- **Tarefa:** parágrafo → probabilidade de ter sido gerado por IA.
- **Dados:**
  - **humanos:** textos CC BY da SciELO anteriores a 2022, antes do ChatGPT;
  - **IA:** texto gerado na própria GPU com modelos abertos Apache-2.0 (Qwen2.5-7B-Instruct,
    Mistral-7B-Instruct, OLMo 2), a partir dos mesmos títulos e seções, mais versões
    parafraseadas. A geração usa a RTX PRO 6000 por algumas horas e o classificador, a
    RTX 4090.
- **Base:** `microsoft/mdeberta-v3-base` (MIT).
- **Cuidado:** detectores erram muito, penalizam escrita formal e de quem não é nativo, e
  generalizam mal para modelos que não estavam no treino. O resultado continua sendo
  "indício", com confiança baixa e nunca veredito, como manda a regra do verificador.

## 8. `errei-trad`: tradutor pt↔en próprio

- **Tira:** os tradutores Helsinki: pt→en na consulta do `literatura` e en→pt nos dados de
  treino dos itens 1 e 2.
- **Dados:** resumos paralelos da SciELO (CC BY) e ParaCrawl pt-en (CC0; conferir).
- **Base:** treinar um Marian do zero (1 a 2 dias na RTX 4090) ou ajustar o `mt5-base`
  (Apache-2.0) por algumas horas.
- **Prioridade baixa:** os Helsinki são Apache-2.0 e rodam localmente, sem serviço externo.
  O item 3 já tira a necessidade de traduzir a consulta.

## 9. `errei-base`: pré-treino no domínio acadêmico em pt-BR

- **O que é:** continuar o pré-treino (MLM) do `mdeberta-v3-base` em texto acadêmico pt-BR
  CC BY (SciELO), para ter um modelo-base do errei.
- **Tira:** nenhuma dependência diretamente, porque a base da Microsoft continua sendo o
  ponto de partida. Melhora os itens 1 a 7, que passam a partir dele.
- **Do zero:** pré-treinar um modelo base sem o mDeBERTa é possível, mas custa dias em
  várias A100 ou B200. Só vale se a licença da base virar problema; hoje é MIT.

## O que não precisa de treino (ou não se resolve com treino)

- **"A original está acessível?"** (Claude Code): o errei já responde com OpenAlex,
  Unpaywall, Europe PMC, arXiv e CORE (`net/textocompleto.py`).
- **Busca livre na web** (Claude Code): nenhum modelo treinado substitui. O errei usa as
  bases abertas, e com os itens 3 e 5 elas cobrem a maior parte do que o Claude Code
  procura.
- **LanguageTool** (verificador `ptbr`): é baseado em regras, não em IA de terceiros.
- **Similaridade** (verificador `plagio`): é determinística (impressões digitais). Os
  embeddings do item 3 poderiam somar a detecção de paráfrase, mas é opcional.

## Ordem sugerida

1. **`errei-cita-v2` (item 1):** o código está pronto. Tira a restrição NC e é a base de
   tudo que julga "sustenta".
2. **`errei-busca` (item 3) e `errei-ref` (item 5):** juntos tiram o Gemini do `nacionais`,
   a tradução do `literatura` e a maior parte do papel do Claude Code no `apud`.
3. **`errei-resumo-v2` (item 2):** tira a última base MoritzLaurer.
4. **`errei-secoes` (item 6):** tira o Gemini do `completude`. Depois disso, `--ia-online`
   não faz mais falta.
5. **Itens 4, 7, 8 e 9:** quando houver tempo.

Os itens 1, 2, 3 e 5 cabem num fim de semana numa RTX 4090: algo como 5 a 8 h de GPU,
em torno de US$ 2 a 4 pelo preço do LEIAME, sem contar o preparo dos dados. O trabalho maior
não é a GPU, e sim escrever o `dados.py` de cada modelo (download, checagem de licença,
divisão) e anotar à mão uma amostra para validar.
