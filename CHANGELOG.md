# Changelog

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/); versões
seguem [SemVer](https://semver.org/lang/pt-BR/).

## [Não lançado]

### Adicionado

- Verificador `literatura` (com `--online`): para cada afirmação, fontes nacionais e
  internacionais (OpenAlex como base primária e Semantic Scholar; consulta em pt e en) que
  **sustentam** a afirmação segundo o errei-cita, com o trecho da fonte no idioma original
  (até 300 caracteres, com página quando vem do texto aberto). Regras `LIT-SUG-001`,
  `LIT-REL-001`, `LIT-NONE-001` e `LIT-LANG-001`. Toda fonte é confirmada por DOI, arXiv
  ou registro do OpenAlex; as não confirmadas são descartadas e contadas.
- Opções `--lit-max`, `--lit-ano-min` e `--lit-idioma`; seção `[literatura]` no config.
  `--texto-completo` também vale para o `literatura` (só PDFs com licença aberta).
- Extra opcional `errei[traducao]`: tradutor local pt→en `Helsinki-NLP/opus-mt-ROMANCE-en`
  (Apache-2.0), só para a consulta.
- `errei modelo baixar --nome opus-mt-ROMANCE-en`: baixa o tradutor do Hugging Face numa
  revisão fixa e confere o sha256 dos pesos; `errei modelo info` mostra o estado dele.
- JSON: achados `LIT-*` trazem o campo `bloco`, com o mesmo texto do terminal. PDF: seção
  "Literatura por afirmação".
- `tests/test_licencas.py`: falha se alguma dependência instalada tiver licença fora da
  lista OSI aprovada.
- `treino-gpu/`: código para treinar o `errei-cita-v2` em GPU alugada, só com dados de
  licença que permite uso comercial (recusa CC BY-NC, como o SciFact).

- Texto completo (`--texto-completo`): localizador em fontes de acesso livre (todas as
  `oa_locations` do OpenAlex, Unpaywall, Europe PMC, arXiv, CORE opcional e
  `citation_pdf_url` da página do DOI), respeitando `robots.txt` e `Crawl-delay`.
- `REFS-ATRIB-*` com `--texto-completo` julga a frase contra o resumo **e** o texto completo,
  com a página do trecho; sem resumo, mas com texto, a atribuição ainda é avaliada.
- `literatura`: sugestões da rede de citações das referências (obras que elas citam e que as
  citam, mais citadas primeiro; `[literatura] rede`, `rede_refs`, `rede_por_ref`).

### Alterado

- **Regra do texto completo:** antes só PDFs com licença aberta (CC BY, CC0) eram lidos.
  Agora vale qualquer texto de acesso livre; o relatório continua mostrando no máximo 300
  caracteres por trecho, sempre com a fonte (citação, Lei 9.610, art. 46, III).
- O idioma do trecho é detectado pelo próprio texto (antes vinha do idioma declarado da obra).

### Licenças

- Nenhuma troca de licença do errei (continua MIT). Registradas no README as licenças de
  todas as dependências; `language-tool-python` (extra `ptbr`) é GPL-3.0, aprovada pela OSI.
- O `errei-cita-v2` sai de modelo-base MIT (`microsoft/mdeberta-v3-base`) e de dados sem
  cláusula NC, para retirar a restrição CC BY-NC dos pesos do v1.

## [0.6.0] - 2026-11-03

### Adicionado

- Referência empírica por área (Fase 1): `errei referencia construir --area <slug> --escopo
  brasil|mundo` mede obras de acesso aberto no top 10% de citações normalizadas do OpenAlex
  e grava só quantis/frequências com procedência; `errei referencia listar`.
- `--referencia brasil|mundo` (com `--area`): verificador `referencia` compara cada dimensão
  do trabalho com p10–p90 da referência (`REF-DIM-001`, `REF-AREA-001..003`). Não muda nada
  sem a flag.
- Chave opcional do OpenAlex (`OPENALEX_API_KEY` ou `[openalex] api_key`), enviada em
  cabeçalho e fora do cache.

## [0.5.1] - 2026-11-02

### Adicionado

- `errei cache info` (pasta, respostas, "não encontradas", vencidas, por fonte, PDFs) e
  `errei cache limpar [--vencidos]`. O `errei doctor` mostra o tamanho do cache.
- `--sem-cache`: com `--online`, consulta as fontes de novo e grava as respostas novas.

### Alterado

- Respostas "não encontrada" (404) valem 2 dias no cache, não mais 30: um DOI recém-registrado
  ou uma recusa momentânea da base não fica marcado como inexistente por um mês.
- As entradas vencidas são apagadas ao abrir o cache (antes o arquivo só crescia).
- PDFs de acesso aberto em cache valem 90 dias e a pasta é limitada a 500 MB.

## [0.5.0] - 2026-11-02

### Adicionado

- "Nível de qualidade do trabalho" na tela, no PDF, no Markdown, na lista de afazeres e em
  `meta.qualidade` no JSON: nível atingido (TCC → Mestrado → Doutorado → Excelência),
  metas cumpridas por nível e o que falta para o próximo. Usa as mesmas metas da lista de
  afazeres; um nível só conta quando os anteriores também são cumpridos.
- "Base do relatório": rodapé em cada página do PDF (versão, normas, fontes) e seção final
  no PDF, no Markdown, na lista de afazeres e em `meta.base` no JSON. Lista normas ABNT,
  fontes realmente consultadas, modelos, métodos, Qualis e hash do projeto.
- Modelo **errei-resumo-v1** (Apache-2.0): papel retórico das frases do resumo (contexto,
  objetivo, método, resultado), treinado sobre o CSAbstruct com tradução pt-BR
  (`treino/resumo/`).
- Regra `ABNT-RESUMO-005` (NBR 6028:2021): o resumo e o abstract trazem objetivo, método,
  resultados e conclusões? Funciona sem o modelo (palavras-chave, como sugestão) e com ele
  (aviso).
- `errei modelo baixar|instalar --nome`, `errei modelo info` com todos os modelos. Os pacotes
  ficam na release fixa `modelos` e não são mais reenviados a cada versão.

### Alterado

- A declaração de uso de IA na lista de afazeres é opcional: aparece como informação (ℹ️) e
  não vira pendência. A IA online continua desligada por padrão e nunca é o primeiro recurso.

## [0.4.0] - 2026-11-02

### Adicionado

- Lista de afazeres em Markdown (`--todo ARQ.md`, gerada automaticamente ao lado do PDF
  como `<nome>-afazeres.md`): checklist priorizado (P0 bloqueadores, P1 necessários para o
  nível, P2 aperfeiçoamento), agrupado por área, com arquivo:linha, como resolver e código
  da regra.
- `--nivel tcc|mestrado|doutorado|a1` (padrão `a1`: Scopus percentil ≥ 92 / Qualis A1–A2),
  também `[todo] nivel` no config. Ajusta as metas (nº e atualidade das referências, DOI,
  extensão, índice de prontidão, avisos tolerados), a prioridade das sugestões e as
  declarações exigidas: dados, conflito de interesses, CRediT, financiamento, uso de IA e
  ética quando há participantes humanos.
- Ao regerar a lista no mesmo nível, os itens que deixaram de aparecer vão para
  "Resolvidos".

## [0.3.0] - 2026-11-02

### Adicionado

- Verificador `completude`: checklist do que falta para o trabalho estar completo, segundo a
  NBR 6022:2018 (artigo) ou a NBR 14724:2011 (monografia, TCC, dissertação, tese). Inclui
  elementos pré-textuais, textuais e pós-textuais, dados de capa/folha de rosto do abnTeX2
  (`COMP-META-001`) e orientação fixa do que escrever em cada elemento ausente. O tipo é
  detectado automaticamente ou informado com `--tipo`.
- Verificador `nacionais` (com `--online`): para afirmações que citam obras estrangeiras,
  sugere artigos brasileiros (OpenAlex, autoria com vínculo no Brasil) e livros em
  português (Open Library; Google Books com `GOOGLE_BOOKS_API_KEY`), ordenados pelo modelo
  errei-cita combinado com os termos em comum (`NAC-SUG-001`). Obras com instituição,
  editora ou cidade brasileira contam como nacionais mesmo com título em inglês.
- IA online opcional (`--ia-online`, Google Gemini, padrão `gemini-flash-lite-latest`,
  `--ia-modelo`): sugere consultas, obras nacionais e orientações para os elementos ausentes
  (`COMP-IA-001`).
  - Toda referência sugerida pela IA é conferida em bases abertas; as não localizadas são
    descartadas (`NAC-IA-001`).
  - As respostas têm esquema JSON fixo e itens de até 25 palavras: a IA não redige texto
    para o trabalho.
  - A IA só liga por flag ou pelo config do usuário, nunca pelo `.errei.toml` do artigo.
  - O relatório registra o que foi enviado, e a chave nunca é gravada.
- `HttpClient.post_json` e cabeçalhos em `get_json`, com cache que não inclui cabeçalhos
  (chaves de API).
- `errei doctor` mostra se há chave do Gemini e do Google Books.

## [0.2.0] - 2026-11-01

### Adicionado

- Relatório em PDF (`--pdf ARQ` junto da saída de tela, ou `--format pdf`), com principais
  problemas, possíveis melhorias, referências verificadas, métricas, todos os achados e
  limitações. Extra `errei[pdf]` (reportlab), com fonte Unicode embutida quando disponível.
- Painel "Principais problemas / Possíveis melhorias / Citações verificadas" no topo da saída
  de tela; `--resumo` mostra só os destaques.
- Validação de atribuição de citações (`REFS-ATRIB-001..004`): a obra é buscada online
  (metadados, resumo, PDF aberto) e cada frase que a cita é comparada com o resumo pelo
  modelo próprio **errei-cita-v1**.
- Conferência de citações diretas no texto completo aberto, com `--texto-completo`
  (`REFS-QUOTE-001/002`).
- Pipeline de treino reproduzível em `treino/` (tradução, pares, fine-tuning em CPU,
  calibração, avaliação, cartão do modelo) e comando `errei modelo info|instalar`.
- Seção `references` nos relatórios JSON e Markdown e campo `modelo_citacoes` nos metadados.
- Progresso ao vivo da verificação online (referências, citações, frases) no terminal.
- Progresso da avaliação do modelo em `treino/dados/progresso.txt`.
- Modelo **errei-cita-v1** treinado (fine-tuning em CPU, 43 min). No teste reservado (dev do
  SciFact), o F1 macro foi de 0,510 → 0,608 (afirmação em inglês) e de 0,461 → 0,566
  (afirmação em português), contra o modelo-base sem treino.
- `errei modelo baixar` (asset da release, sha256, extração segura) e
  `scripts/empacotar-modelo.sh`.
- CI no GitHub Actions (`.github/workflows/ci.yml`): testes em Python 3.10–3.13, build com
  teste de instalação e release em tags `v*` com wheel, sdist, `install.sh` e `sha256sums.txt`.
- Instalador `install.sh` (`curl … | sh`, `--modelo`, `--versao`, `uninstall`), com
  verificação de checksum e ambiente isolado sem sudo.

## [0.1.0] - 2026-11-01

### Adicionado

- CLI `errei` (typer) com os subcomandos `audit` (padrão), `init`, `doctor` e `explain`;
  saídas `term` (rich), `md` e `json` (schema 1); códigos de saída 0/1/2 e `--fail-on`.
- Arquitetura de plugins via entry points `errei.checkers`, com isolamento de falhas
  (`CORE-CHECKER-001`).
- Verificadores `latex`, `refs`, `abnt`, `ptbr`, `escrita`, `plagio`, `ia` e `periodico`
  (106 regras com códigos estáveis).
- Extração de texto limpo com mapa de offsets de volta ao fonte (pylatexenc, modo tolerante).
- Parser `.bib` próprio e tolerante, com linha por entrada e por campo.
- Camada de rede opt-in (`--online`): cache SQLite, rate limit por host, retry com backoff
  e `Retry-After`, polite pool com e-mail e degradação graciosa (`CORE-NET-001`).
- Integração com o LanguageTool local (nunca baixa sem `errei doctor --download`) e
  fallback ortográfico com hunspell pt_BR ou pyspellchecker.
- Leitura de CSV Qualis (Sucupira) com detecção de encoding/delimitador e data de referência.
- Supressão por `% errei: ignore CODIGO`, `ignore-file` e `[ignore]` no config.
- Fixture abnTeX2 com erros plantados e testes de aceite: detecção com arquivo/linha,
  somente leitura (hash) e zero rede sem `--online`.
