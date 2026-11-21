# errei

**errei** audita um artigo científico escrito em LaTeX (arquivos `.tex` e `.bib` de uma
pasta), no Word/LibreOffice (`.docx`) ou já em PDF, e aponta problemas de **estrutura LaTeX, citações e referências, normas ABNT,
ortografia/gramática/estilo em pt-BR, qualidade textual, similaridade, indícios de texto
gerado por IA e prontidão para periódicos**. Mostra o **nível de qualidade** que o trabalho
já atinge (TCC, Mestrado, Doutorado ou Excelência) e gera uma **lista de afazeres** em
Markdown com o que fazer para subir de nível.

Princípios:

- **Honestidade epistêmica.** Nenhum achado é veredito. Similaridade, indícios de IA e Qualis
  são *indicadores* com confiança e justificativa. Todo relatório traz a seção **Limitações**.
- **Offline por padrão.** Nada sai da máquina sem `--online`. O LanguageTool roda localmente.
- **Somente leitura.** Os arquivos do artigo nunca são alterados; não há autofix.
- **Rastreável.** Cada achado tem arquivo, linha, coluna, trecho, código da regra,
  severidade, mensagem e sugestão (no `.docx`, o nº do parágrafo; no PDF, a página).

## Instalação

Instalador rápido (Linux/macOS; requer Python ≥ 3.10 e curl):

```bash
curl -fsSL https://raw.githubusercontent.com/reinanbr/errei/main/install.sh | sh
# com o modelo de citações (torch CPU):  ... | sh -s -- --modelo
# desinstalar:                           ... | sh -s -- uninstall
```

A partir do código-fonte:

```bash
pipx install '.[all]'          # ou: pip install -e '.[all]'
errei doctor --download        # verifica Java/hunspell e baixa o LanguageTool (~250 MB)
```

Extras opcionais (instale só o que precisar):

| extra | o que habilita |
|---|---|
| `errei[online]` | `httpx` + `rapidfuzz`: verificação de referências, busca de frases, OpenAlex |
| `errei[ptbr]` | `language-tool-python` + `pyspellchecker`: gramática (LanguageTool local, requer Java ≥ 17) e ortografia de fallback |
| `errei[plagio]` | `pypdf`: PDFs no corpus local de comparação |
| `errei[documentos]` | `pypdf`: auditar um trabalho em `.pdf` (o `.docx` não precisa de extra) |
| `errei[pdf]` | `reportlab`: relatório em PDF (`--pdf`, `--format pdf`) |
| `errei[modelo]` | `torch` + `transformers`: modelo **errei-cita** de validação de citações |
| `errei[traducao]` | `torch` + `transformers` + `sentencepiece`: tradutor local pt→en (`Helsinki-NLP/opus-mt-ROMANCE-en`, Apache-2.0) para a consulta em inglês do verificador `literatura` |
| `errei[all]` | online, ptbr, plagio, pdf e documentos (o modelo é separado por ser grande) |

Sem um extra, o verificador correspondente é pulado em parte, e o relatório informa isso
com a regra `CORE-DEP-001`.

## Uso

```bash
errei .                              # audita a pasta atual
errei caminho/artigo                 # audita outra pasta
errei trabalho.docx                  # audita um .docx (Word, LibreOffice, Google Docs)
errei artigo.pdf                     # audita um PDF com texto (não digitalizado)
errei . --online                     # habilita checagens que usam rede
errei . --only abnt,refs             # roda só alguns verificadores (--skip para pular)
errei . --format md --out relatorio.md
errei . --format json --out relatorio.json
errei . --qualis-csv ~/qualis.csv --periodico "ISSN 1234-5678" --qualis-data 2025-07-01
errei . --fail-on warning            # código 1 também com avisos (útil em CI)
errei . --pdf relatorio.pdf          # mostra na tela E grava o relatório em PDF
errei . --resumo                     # na tela, só o nível de qualidade, problemas e melhorias
errei . --todo afazeres.md --nivel mestrado  # lista de tarefas para chegar ao nível
errei . --format pdf --out rel.pdf   # PDF como saída principal (resumo na tela)
errei . --online --texto-completo    # lê o texto completo (acesso livre) para validar as citações
errei . --online --ia-claude         # confere também cada apud com o Claude Code (opcional)
errei modelo info                    # estado e métricas do modelo de citações errei-cita
errei init                           # cria .errei.toml comentado na pasta
errei doctor                         # verifica dependências (java, LanguageTool, hunspell)
errei cache info                     # tamanho e conteúdo do cache das consultas online
errei cache limpar                   # apaga o cache (--vencidos: só o que venceu)
errei . --online --sem-cache         # consulta as fontes de novo, ignorando o cache
errei explain PTBR-CRASE-001         # explica uma regra; --list lista todas
```

### Códigos de saída

| código | quando |
|---|---|
| 0 | sem achados no nível de `--fail-on` (padrão: `error`) |
| 1 | há erros (ou avisos, com `--fail-on warning`) |
| 2 | falha de uso/ambiente: pasta inexistente, `.tex` principal não encontrado, CSV/config inválidos |

### Severidades

`erro` (corrija), `aviso` (provável problema), `sugestão` (estilo/melhoria) e `info`
(contexto, indicadores).

### Saídas

- **term** (padrão): via `rich`, com resumo e nível de qualidade no topo, contagem por verificador e achados
  agrupados por arquivo e ordenados por severidade. Respeita `NO_COLOR` e saída não-TTY.
- **md**: relatório completo com versão, data, hash do projeto, flags, métricas e Limitações.
- **json**: o mesmo conteúdo, estruturado (`"schema": 1`), para integração; o nível de
  qualidade fica em `meta.qualidade`.

- **pdf**: relatório completo para ler, imprimir ou enviar. Traz capa com resumo, **nível de
  qualidade do trabalho**, **principais
  problemas (onde corrigir)**, **possíveis melhorias**, **referências verificadas** (obra
  encontrada, resumo e validação de cada frase que a cita), métricas, todos os achados por
  arquivo e limitações. Com `--pdf ARQ` a saída de tela continua normal.

Na tela, o topo do relatório mostra sempre o **nível de qualidade**, os **principais
problemas** e as **possíveis melhorias** com `arquivo:linha` e a sugestão de correção. Com
`--resumo` aparece só isso.

```
╭──────────────────────── Nível de qualidade ────────────────────────╮
│ Nível atingido: TCC (graduação)                                    │
│ ✔ TCC (graduação)            ████████████████████ 11/11 (100%)     │
│ · Mestrado                   █████████████░░░░░░░ 10/15 (67%)      │
│ · Doutorado                  ██████████░░░░░░░░░░ 8/16 (50%)       │
│ · Excelência (Scopus ≥ 92…)  ███████░░░░░░░░░░░░░ 7/19 (37%)       │
│ Para chegar a Mestrado, falta:                                     │
│   • Referências citadas: 18 (meta ≥ 25)                            │
│   • Limitações do estudo: ausente (meta presente) …                │
╰────────────────────────────────────────────────────────────────────╯
```

O quadro usa as metas da [lista de afazeres](#lista-de-afazeres-por-nível); é uma
referência objetiva e não prevê aprovação nem aceite.

## Trabalhos em .docx e .pdf

Além do projeto LaTeX, o errei audita um arquivo `.docx` (Word, LibreOffice, Google Docs
exportado) ou um `.pdf` com texto. O arquivo é lido e convertido em memória, sem ser
alterado, e passa pelos mesmos verificadores: escrita, pt-BR, ABNT, citações e referências,
apud, similaridade, indícios de IA, completude e prontidão (o `latex` é pulado).

```bash
errei trabalho.docx
errei artigo.pdf --online --pdf relatorio.pdf
errei pasta/                 # sem .tex na pasta e com um único .docx/.pdf: audita esse
```

O que é reconhecido:

- **Estrutura.** Títulos pelos estilos do Word (Título 1, 2…, "Heading N", nível de tópico)
  ou, no PDF, pela numeração ("2.1 Método"), por maiúsculas e pelos nomes usuais (Resumo,
  Abstract, Introdução, Referências…); listas, citações recuadas, legendas e "Fonte:".
- **Citações** digitadas: `(SILVA, 2020, p. 3)`, `Silva (2020)`, `Silva et al. (2020)`,
  `(SILVA, 2020 apud SOUZA, 2021)`, `Silva (2020 apud SOUZA, 2021)`, APA
  (`(Silva & Souza, 2020)`) e numéricas (`[1]`, `[2-4]`) quando a lista é numerada.
- **Lista de referências** em ABNT (NBR 6023), APA, Chicago autor-data, IEEE e Vancouver,
  inclusive entidades ("BRASIL. Ministério…") e "______." para autor repetido. Cada
  citação é ligada à sua referência por autor e ano.
- **Formatação** (só `.docx`): papel, margens e fonte padrão.

Os achados se adaptam: a localização é `trabalho.docx, § 12` (nº do parágrafo, sem contar
os vazios) ou `artigo.pdf, p. 3`; as obras aparecem como são citadas ("SILVA, 2020"), não
como chaves do `.bib`; não há sugestões em LaTeX; e regras que só fazem sentido no `.bib`
(campos obrigatórios, sintaxe) não se aplicam, porque os campos de uma referência digitada
nem sempre podem ser separados com segurança. Regras próprias: `DOC-LEITURA-001` (o que foi
lido e o que não é analisado), `DOC-LEITURA-002` (limitações da extração do PDF),
`DOC-REF-001` (referência sem autor, título ou ano reconhecíveis), `DOC-REF-002` (lista
autor-data fora da ordem alfabética) e `DOC-CIT-001` (`??` no PDF: citação ou referência
cruzada que o LaTeX não resolveu).

Não são analisados: notas de rodapé, caixas de texto, tabelas, equações, comentários,
cabeçalhos e rodapés (no PDF, os repetidos e os números de página são removidos). PDFs
digitalizados (imagem) não têm texto e são recusados com uma explicação (não há OCR).
Sempre que possível, prefira o `.docx` ou o fonte LaTeX ao PDF: a extração do PDF pode colar
palavras de linhas justificadas ou misturar colunas.

## Validação de citações

Com `--online`, para cada obra citada o errei:

1. **verifica se ela existe** (Crossref, OpenAlex, arXiv), classificando-a como `confirmada`,
   `divergente` ou `não encontrada`;
2. **traz a obra da internet**: título, autores, ano, periódico, DOI, resumo (OpenAlex /
   Semantic Scholar) e link para o PDF de acesso aberto, quando houver;
3. **verifica cada atribuição**. A frase do artigo que cita a obra (sem os marcadores de
   citação) é comparada com cada frase do resumo da fonte pelo modelo **errei-cita**, que
   indica se a fonte *sustenta* (`REFS-ATRIB-001`), *parece contradizer* (`REFS-ATRIB-002`)
   ou *não permite confirmar* (`REFS-ATRIB-003`) a afirmação, mostrando o trecho da fonte;
4. com `--texto-completo`, **procura o texto completo** da obra em fontes de acesso livre
   (veja [Texto completo](#texto-completo)) e:
   - julga a frase também contra o **corpo da obra**, não só contra o resumo, mostrando o
     trecho e a página (`REFS-ATRIB-*`). Assim, "o resumo não permite confirmar" vira
     "o texto sustenta (p. 7)" quando a obra de fato afirma aquilo;
   - procura as **citações diretas** (trechos entre aspas) e confere a página indicada em
     `\cite[p.~N]{...}` (`REFS-QUOTE-*`).

### Texto completo

Com `--online --texto-completo`, o errei tenta, nesta ordem, até conseguir um texto legível:

1. todas as cópias de acesso livre listadas pelo OpenAlex (`oa_locations`);
2. Unpaywall (requer `--email` ou `email` no config);
3. Europe PMC / PubMed Central (XML do texto completo);
4. arXiv;
5. CORE, se houver `CORE_API_KEY` no ambiente ou `[core] api_key` no config do usuário;
6. a página do DOI na editora, no SciELO ou no repositório: o link `citation_pdf_url`.

Vale qualquer texto de **acesso livre**, com ou sem licença aberta (CC BY etc.). O relatório
mostra no máximo 300 caracteres de cada trecho, sempre com a obra e o link, como citação.
O errei **respeita o `robots.txt`** de cada site (inclusive o `Crawl-delay`), se identifica
pelo User-Agent, obedece ao limite de requisições e **não contorna** bloqueios, captchas ou
paywalls. Não usa sites que distribuem cópias sem autorização. Os PDFs ficam no cache por 90
dias (`errei cache info`).

Durante a verificação online o terminal mostra o andamento ("verificando referência 3/7
online: lecun2015", "validando 2 citação(ões)…"). Ele não aparece quando a saída é
redirecionada, com `--quiet` ou com `ERREI_NO_PROGRESS=1`.

"Não permite confirmar" é o resultado normal quando o ponto citado está no corpo da obra e
não no resumo; não significa que a citação esteja errada.

### O modelo errei-cita

É um cross-encoder multilíngue (6 camadas, 107 M de parâmetros, roda em CPU) **treinado para
o errei**. Partiu de `MoritzLaurer/multilingual-MiniLMv2-L6-mnli-xnli` e passou por
fine-tuning no SciFact, afirmações científicas pareadas com resumos, com as afirmações
traduzidas para pt-BR para aprender o caso real (frase em português × fonte em inglês). As
métricas no conjunto de teste reservado estão em `errei modelo info` e no cartão do modelo.

Para treinar e instalar (CPU, ~1–2 h):

```bash
uv pip install -e '.[modelo]' --extra-index-url https://download.pytorch.org/whl/cpu
treino/rodar_tudo.sh          # baixa dados, traduz, treina, avalia e instala
errei modelo info
```

Para acompanhar a avaliação em outro terminal:

```bash
tail -f treino/dados/progresso.txt     # "avaliando …: 120/408 (29%) ~3.1 min restantes"
tail -f treino/dados/treino.log        # passos e F1 por época do treino
```

Os pesos ficam em `~/.local/share/errei/modelos/errei-cita-v1` (ou `$ERREI_MODEL_DIR`).
**Licença dos pesos: CC BY-NC 2.0** (herdada do SciFact), ou seja, uso não comercial. O
código do errei continua MIT. Sem o modelo, a existência das obras continua sendo verificada
e o relatório informa que a validação das atribuições foi pulada.

**errei-cita-v2 (sem restrição NC).** A pasta [`treino-gpu/`](treino-gpu/LEIAME.md) tem o
código para treinar o v2 numa GPU alugada, só com dados e modelo-base de licença que permite
uso comercial (PUBHEALTH, MIT; anotações próprias, CC BY 4.0; `microsoft/mdeberta-v3-base`,
MIT). `cita/dados.py` recusa CC BY-NC. Quando `errei-cita-v2` está instalado
(`errei modelo instalar <pasta> --nome errei-cita-v2`), o errei passa a usá-lo no lugar do
v1.

### O modelo errei-resumo

A NBR 6028:2021 pede que o resumo ressalte **objetivo, método, resultados e conclusões**. A
regra `ABNT-RESUMO-005` classifica o papel de cada frase do resumo e do abstract e aponta o
que falta, listando cada frase com o papel estimado.

- Com o modelo **errei-resumo-v1** instalado, o papel vem dele. É um classificador
  multilíngue de 6 camadas, treinado para o errei sobre o CSAbstruct (AllenAI, Apache-2.0)
  com tradução para pt-BR. Os pesos têm **licença Apache-2.0**.
- Sem o modelo, o papel é estimado por palavras-chave e posição, e o achado sai só como
  sugestão.
- O CSAbstruct não separa conclusão de resultado, por isso a conclusão é detectada por
  marcadores ("conclui-se", "portanto", "os resultados indicam").

Para treinar (CPU, ~3 h com a tradução):

```bash
sh treino/resumo/rodar.sh              # baixa o CSAbstruct, traduz, treina, avalia e instala
cat treino/dados/csabstruct/progresso.txt
```

### Baixar os modelos

```bash
errei modelo baixar                    # todos (errei-cita-v1 e errei-resumo-v1)
errei modelo baixar --nome errei-resumo-v1
errei modelo info                      # onde estão e métricas de teste
```

Os pacotes ficam na release fixa `modelos` do GitHub, com sha256 conferido. Nenhum modelo é
obrigatório: sem eles o errei roda normalmente e informa o que foi pulado.

### Ignorando achados

```latex
Texto com a idéia antiga. % errei: ignore PTBR-ORTO-001
% errei: ignore LATEX-REF-*        (comentário sozinho: vale para a linha seguinte)
% errei: ignore-file IA-*          (vale para o arquivo inteiro)
```

Ou em `.errei.toml`:

```toml
[ignore]
codes = ["PTBR-PASSIVA-001", "IA-*"]
paths = ["apendices/*.tex"]
```

Termos técnicos vão em `.errei-dict.txt` (um por linha), que vale para ortografia e
anglicismos.

## Referência empírica por área

As metas da lista de afazeres são genéricas. Para comparar o trabalho com **como escrevem
os trabalhos de maior impacto da sua área**, construa uma referência (usa a rede, uma vez)
e use-a offline em todas as auditorias:

```bash
errei referencia listar                                         # áreas e referências instaladas
errei referencia construir --area educacao --escopo brasil      # ~300 obras, alguns minutos
errei . --area educacao --referencia brasil                     # compara (offline)
```

- **Seleção:** artigos de acesso aberto no **top 10% de citações normalizadas** por ano e
  subárea no OpenAlex (`--anos 2015-2023`), na área escolhida; com `--escopo brasil`, só os
  que têm instituição brasileira na autoria. Amostra aleatória reprodutível (`--n`,
  `--seed`).
- **Medidas por obra:** nº de referências (no OpenAlex e contadas no PDF), % dos 5 anos
  anteriores, % de periódicos, % com DOI, idade mediana das referências, extensão, resumo,
  frase média, Flesch, MATTR, conectivos, passiva, citações por 1000 palavras, declarações
  (dados, conflito, CRediT, financiamento, ética) e papéis retóricos do resumo.
- **O que é gravado:** só quantis (p10, p25, p50, p75, p90) ou frequências, por idioma, com
  a procedência (filtro, data, n, licenças dos textos) em
  `~/.local/share/errei/referencias/<area>.json`. Os PDFs são lidos em memória e
  descartados; nenhum texto ou título é guardado.
- **No relatório:** cada dimensão aparece como "seu valor × p10–p90 e mediana (n=…)", sem
  nota única. Fora de p10–p90 vira sugestão `REF-DIM-001`; amostra pequena (n < 30) vira
  `REF-AREA-002`.

Áreas: `educacao`, `saude-coletiva`, `computacao`, `psicologia`, `administracao`. O
`--area` aceita o slug ou o nome CAPES (`"EDUCAÇÃO"`), o mesmo usado no Qualis.

O OpenAlex limita o uso diário sem chave (orçamento compartilhado por IP). Para ter o seu,
crie uma chave gratuita e use `OPENALEX_API_KEY` ou `[openalex] api_key` em
`~/.config/errei/config.toml`. A chave vai em cabeçalho e nunca é gravada no cache.

## Cache das consultas online

Com `--online`, as respostas das bases (Crossref, OpenAlex, Semantic Scholar, arXiv, Open
Library, Google Books, Gemini, Claude Code) ficam guardadas em `~/.cache/errei` (ou
`$XDG_CACHE_HOME/errei`). Assim a segunda auditoria do mesmo artigo é rápida, não estoura
os limites de requisição das APIs e dá o mesmo resultado para a mesma referência.

| o que | arquivo | validade |
|---|---|---|
| respostas encontradas | `http.sqlite` | 30 dias |
| "não encontrada" (404) | `http.sqlite` | 2 dias: um DOI recém-registrado ou uma recusa momentânea da base é consultado de novo logo |
| PDFs de acesso aberto (`--texto-completo`) | `pdf/` | 90 dias, até 500 MB (os mais antigos saem primeiro) |

O que venceu é apagado sozinho ao abrir o cache. Cabeçalhos com chaves de API nunca são
gravados.

```bash
errei cache info               # pasta, nº de respostas, "não encontradas", vencidas, por fonte, PDFs
errei cache limpar             # apaga o cache inteiro (não mexe nos modelos nem no LanguageTool)
errei cache limpar --vencidos  # apaga só o que venceu
errei . --online --sem-cache   # ignora o cache nesta execução e grava as respostas novas
```

## Configuração

Ordem de precedência: padrões ← `~/.config/errei/config.toml` ← `<artigo>/.errei.toml` ←
flags da linha de comando. Rode `errei init` para gerar um arquivo comentado.

> Segurança: opções que carregam código ou enviam o texto para fora (como `[ia].detector`,
> `[ia_online]` e `[ia_claude]`) só são aceitas do config do usuário ou da linha de comando, **nunca** do `.errei.toml` da pasta do artigo, que pode vir
> de terceiros. O conteúdo do artigo nunca é executado nem passado a `latex` ou ao shell.

## Lista de afazeres por nível

Além do relatório, o errei gera um **checklist em Markdown** com o que corrigir e
aperfeiçoar, calibrado pelo nível que o trabalho deve alcançar:

```bash
errei . --pdf relatorio.pdf                    # gera também relatorio-afazeres.md
errei . --todo afazeres.md --nivel mestrado    # só a lista
```

| `--nivel` | meta | referências (artigo/monografia) | últimos 5 anos | DOI | prontidão | avisos |
|---|---|---|---|---|---|---|
| `tcc` | TCC aprovado pela banca | ≥ 15 / 20 | ≥ 30% | ≥ 30% | ≥ 50 | ≤ 20 |
| `mestrado` | dissertação ou artigo Qualis B1–A4 | ≥ 25 / 50 | ≥ 40% | ≥ 50% | ≥ 65 | ≤ 10 |
| `doutorado` | tese ou artigo Qualis A2–A1 | ≥ 35 / 100 | ≥ 50% | ≥ 70% | ≥ 75 | ≤ 5 |
| `a1` (padrão) | Scopus percentil ≥ 92 ou Qualis A1–A2 | ≥ 40 / 100 | ≥ 50% | ≥ 85% | ≥ 85 | 0 |

A lista traz:

- **Nível de qualidade do trabalho**: o nível que o trabalho já atinge (TCC, Mestrado,
  Doutorado ou Excelência), o progresso em cada um (metas cumpridas/medidas) e o que falta
  para o próximo. Um nível só é atingido quando todas as metas medidas dele e dos
  anteriores são cumpridas. O mesmo quadro aparece na tela, no PDF, no Markdown e em
  `meta.qualidade` no JSON.
- **Metas do nível**: tabela ✅/❌ com referências, extensão do texto, erros e avisos,
  índice de prontidão, elementos obrigatórios, abstract e elementos de conteúdo (objetivo,
  pergunta de pesquisa, limitações, contribuição, trabalhos futuros). Nos níveis altos
  entram também as declarações que os periódicos exigem: disponibilidade de dados, conflito
  de interesses, contribuição dos autores (CRediT), financiamento, uso de IA e aprovação
  ética (esta só quando há participantes humanos).
- **Itens priorizados** em `- [ ]`, por área, cada um com arquivo:linha, como resolver,
  trecho e código da regra:
  - **P0** bloqueia a entrega;
  - **P1** é necessário para o nível (em doutorado e a1, as sugestões de escrita, ABNT e
    referências sobem para P1);
  - **P2** é aperfeiçoamento.

  Ocorrências repetidas do mesmo problema viram um item só, com a lista de locais.
- **Revisão humana**: o que o errei não verifica, como alinhamento objetivo ↔ método ↔
  conclusão, escolha do periódico, template e carta ao editor.

Ao rodar de novo sobre o mesmo arquivo e no mesmo nível, os itens que sumiram aparecem em
**Resolvidos**. As metas são referências usuais de cada nível, não garantia de aprovação
ou aceite. A lista é um relatório: o errei nunca altera o trabalho, e se recusa a gravá-la
sobre `.tex`/`.bib`.

## Base do relatório

Todo relatório informa em que se apoiou:

- no **rodapé de cada página do PDF**: versão, normas e fontes consultadas;
- numa seção final **"Base do relatório"** (PDF, Markdown, lista de afazeres e `meta.base`
  no JSON), com estes itens:
  - versão e data;
  - arquivo principal e hash do projeto analisado;
  - verificadores executados;
  - normas ABNT usadas;
  - fontes consultadas de fato ("nenhuma" quando a execução é offline);
  - modelos (errei-cita, errei-resumo e, se usados, o Gemini e o Claude Code; senão "IA
    online: não utilizada");
  - métodos, como o Flesch adaptado de Martins et al. (1996), MinHash e os pesos do índice;
  - o CSV do Qualis, quando houver.

## Completude do trabalho

O verificador `completude` diz **o que falta** para o trabalho estar completo, segundo a
norma do tipo de trabalho:

- **artigo**: NBR 6022:2018 (título, autoria, resumo e palavras-chave, introdução,
  desenvolvimento, considerações finais, referências; metodologia e resultados como
  recomendados);
- **monografia, TCC, dissertação, tese**: NBR 14724:2011 (capa, folha de rosto, ficha
  catalográfica, folha de aprovação, resumo, abstract, listas, sumário, introdução,
  desenvolvimento, conclusão, referências...) e os dados de capa/folha de rosto do abnTeX2
  (`\titulo`, `\autor`, `\orientador`, `\instituicao`, `\local`, `\data`, `\preambulo`).

O tipo é detectado pela classe e pelos comandos usados. Para fixá-lo, use
`--tipo artigo|monografia|tcc|dissertacao|tese`. O relatório traz o checklist completo
(presente/ausente, obrigatório/recomendado/opcional, item da norma) e, para cada elemento
ausente, o que ele deve conter.

## Obras nacionais no lugar de estrangeiras

Com `--online`, o verificador `nacionais` procura, para cada afirmação que cita uma obra
estrangeira, **artigos e livros brasileiros** sobre o mesmo tema:

- **artigos**: OpenAlex, filtrado para autoria com vínculo no Brasil;
- **livros**: Open Library, em português, e Google Books, só se houver
  `GOOGLE_BOOKS_API_KEY`, porque a cota anônima vive esgotada.

Cada sugestão traz autores, ano, título, veículo, DOI/ISBN/link e a base em que foi
localizada. A ordenação usa o modelo errei-cita sobre o resumo, combinado com os termos em
comum. Uma obra é tratada como nacional quando o `.bib` indica `language = {portuguese}`
ou instituição/editora/cidade brasileira, mesmo que o título esteja em inglês. Nada é
inserido no `.bib`: leia a obra antes de citá-la.

### IA online (Gemini), opcional

A IA online é **opcional**: fica desligada por padrão, não é necessária para nenhuma
verificação e nunca é o primeiro recurso. O errei faz tudo localmente e com bases
bibliográficas abertas. O Gemini só entra se você pedir com `--ia-online`.

```bash
export GEMINI_API_KEY=...        # ou ERREI_GEMINI_KEY / GEMINI_KEY / GOOGLE_API_KEY
errei . --online --ia-online     # modelo padrão: gemini-flash-lite-latest (--ia-modelo)
```

Com `--ia-online`, o Google Gemini:

- sugere **consultas** em português e **obras brasileiras** para cada afirmação;
- dá **orientações** do que escrever nos elementos ausentes.

Regras garantidas no código:

- **Nada é aceito sem verificação.** Uma referência sugerida pela IA só aparece se for
  localizada em OpenAlex, Open Library, Google Books ou Crossref, com título e autor
  conferidos. As demais são descartadas e contadas (`NAC-IA-001`).
- **A IA não escreve o trabalho.** As respostas seguem um esquema JSON fixo (palavras-chave,
  referências, orientações), e cada item é cortado em 25 palavras. Não há parágrafos prontos,
  e nada é gravado nos arquivos. O relatório traz a orientação e você redige com suas
  palavras.
- **O envio é explícito.** Liga só com `--online --ia-online` ou com `[ia_online] enabled =
  true` em `~/.config/errei/config.toml`. O `.errei.toml` do artigo **não** consegue ligar
  isso. São enviados só as frases que citam obras estrangeiras, os títulos dessas obras, o
  título do trabalho e os títulos das seções. O relatório registra o que foi enviado
  (`meta.ia_online`).
- **A chave fica em sigilo.** Ela vai no cabeçalho `x-goog-api-key` e nunca é gravada em
  cache, relatório ou log.

## Literatura que sustenta cada afirmação

Com `--online`, o verificador `literatura` procura, para cada afirmação que precisa de
apoio, obras **nacionais e internacionais** que **digam aquilo que a afirmação diz**, e
mostra o trecho da fonte que prova isso.

```bash
errei caminho/artigo --online --only literatura
errei caminho/artigo --online --only literatura --texto-completo
errei caminho/artigo --online --lit-max 2 --lit-ano-min 2015 --lit-idioma pt,en
```

| opção | efeito |
|---|---|
| `--lit-max N` | máximo de fontes por afirmação (padrão 3; `[literatura] max_fontes`) |
| `--lit-ano-min AAAA` | só fontes publicadas a partir desse ano |
| `--lit-idioma pt,en` | só fontes nesses idiomas (ISO 639-1; padrão: todos) |
| `--texto-completo` | compara também com o texto completo de acesso livre (veja [Texto completo](#texto-completo)); o trecho traz a página: `(p. 5)` |
| `--skip literatura` | desliga o verificador |

**Quais afirmações.** Frases que já citam uma obra e, na introdução/revisão, frases **sem
citação** com marcas de generalização ("estudos mostram", "é amplamente", "reduz",
percentuais). Limite: `[literatura] max_afirmacoes` (padrão 15).

**Como decide.**

1. Consulta em português **e** em inglês. A tradução da consulta usa o tradutor local
   opcional; sem ele, só português, e o relatório avisa. A busca não é restrita ao Brasil
   nem ao português. Para instalar o tradutor (~310 MB, Apache-2.0, revisão fixa e sha256
   conferido):

   ```bash
   pip install 'errei[traducao]'
   errei modelo baixar --nome opus-mt-ROMANCE-en
   ```
2. Bases: **OpenAlex** (primária) e Semantic Scholar. Toda fonte é **confirmada** pelo DOI
   (Crossref/OpenAlex, com título conferido), pelo id do arXiv ou pelo registro do
   OpenAlex. O que não for confirmado é descartado e contado ("Fontes descartadas").
3. Além da busca por termos, entram as obras da **rede de citações** das suas referências
   com DOI: o que cada uma cita e quem a cita, as mais citadas primeiro (OpenAlex;
   `[literatura] rede`, `rede_refs`). Elas passam pelos mesmos filtros e aparecem com
   `Via: rede de citações (cita 'chave')` ou `(citada por 'chave')`.
4. O modelo **errei-cita** compara a afirmação com cada frase (e janela de 2 frases) do
   resumo e, com `--texto-completo`, com trechos do texto completo.
5. Só vira `LIT-SUG-001` a fonte em que algum trecho foi classificado como **sustenta**.
   Fonte do mesmo tema sem esse trecho vira, no máximo, `LIT-REL-001`. Sem o modelo
   instalado, nada vira `LIT-SUG-001` (o relatório avisa com `CORE-DEP-001`).
6. Ordem: força do suporte, depois qualidade da fonte (Qualis do seu `--qualis-csv` e
   percentil de citações do OpenAlex), depois ano.

Saída (igual no terminal, em `md`, em `json`, no campo `bloco`, e em `pdf`):

```
LIT-SUG-001  sugestão  introducao.tex:42:1
Afirmação : "O uso de redes neurais reduz o tempo de diagnóstico."
Fonte     : Sobrenome et al. (2022). Título do artigo. Periódico. DOI: 10.xxxx/xxxx
Base      : OpenAlex     Idioma: en
Trecho    : "<até 300 caracteres copiados da fonte, no idioma original>"  (p. 5)
Relação   : sustenta     Confiança: média
Aviso     : indicador, não veredito. Leia a fonte antes de citar.

LIT-REL-001  info  introducao.tex:42:1
Fonte relacionada (NÃO sustenta a afirmação): Sobrenome (2020). Título. DOI: ...
Motivo: nenhum trecho do resumo ou do texto aberto afirma o que a frase afirma.

LIT-NONE-001  info  introducao.tex:42:1  nenhuma fonte encontrada para esta afirmação.
```

`LIT-LANG-001` avisa quando o trecho está em outro idioma: ele é mostrado no original, e
qualquer tradução é automática e não é citação. Sem `--online`, o verificador **não faz
nenhuma requisição** e o relatório diz que foi pulado (`CORE-NET-001`). Nada é escrito
no `.tex` nem no `.bib`.

## Citação de citação (apud)

A citação de citação (`apud`, "citado por") declara que você leu a obra **consultada** e
que ela cita a obra **original**, que você não leu (NBR 10520). O verificador `apud`
reconhece estas formas:

| forma | exemplo |
|---|---|
| abntex2cite | `\apud[p.~12]{flesch1948}{martins1996}`, `\apudonline{...}{...}` |
| biblatex-abnt | `\apud[p.~3]{flesch1948}[p.~12]{martins1996}`, `\textapud{...}{...}` |
| digitada | `\citeonline{flesch1948} apud \citeonline{martins1996}`, `Flesch (1948) apud \citeonline{martins1996}`, "citado por" |

Em todas, a obra que você **não** leu vem primeiro e a que você leu vem depois.

**Sem rede:**

| regra | o que aponta |
|---|---|
| `APUD-ORDEM-001` | a original é posterior à consultada: os argumentos provavelmente estão invertidos (sugere a ordem certa) |
| `APUD-MESMA-001` | a mesma chave como original e como consultada |
| `APUD-DIRETA-001` | a original também é citada diretamente em outro ponto, ou é a obra consultada (a que você leu) em outra citação de citação: ou você a leu, ou não leu. Vale também para a original e a consultada digitadas (ver abaixo) |
| `APUD-CONS-001` | a obra consultada está digitada, fora do `.bib` (com a chave na sugestão, quando a entrada é única pelo autor e ano) |
| `APUD-EXCESSO-001` | muitas obras citadas só por intermédio de outra (`[apud] max_proporcao`, padrão 15%, a partir de `min_ocorrencias` = 3) |
| `APUD-LISTA-001` | as originais vão para a lista de referências; confira se o seu programa pede só a consultada |

A métrica "Citação de citação (apud)" mostra quantas são e quantas obras são citadas só
por apud (nem diretamente nem como obra consultada em nenhum ponto; `\apud{x}{x}` fica fora
da conta).

**Obra digitada.** Em `Martins (1996) apud \citeonline{souza2020}` ou
`\citeonline{flesch1948} apud Martins (1996)`, a obra digitada é ligada à entrada do `.bib`
com o mesmo sobrenome do primeiro autor e o mesmo ano, e então conta como `martins1996` no
`APUD-DIRETA-001`, na métrica, na sugestão do `APUD-CONS-001` e, quando é a consultada, na
conferência com `--online` e com o Claude Code. Os achados dizem quando a ligação foi feita
assim. Não há ligação quando duas entradas têm o mesmo autor e ano (1996a, 1996b), quando o
ano traz letra, nem quando a entrada é a obra do outro lado do apud
(`Martins (1996) apud \citeonline{martins1996}` é, provavelmente, outra obra de Martins).

**Com `--online`**, sem IA, só com bases abertas:

| regra | o que aponta |
|---|---|
| `APUD-ACESSO-001` | a original tem cópia de acesso livre: leia-a e cite-a diretamente |
| `APUD-REDE-001` / `APUD-REDE-002` | a lista de referências da consultada inclui (ou não inclui) a original, e em qual base |
| `APUD-VERIF-001` | não deu para conferir (obra não localizada, base fora do ar ou lista de referências não indexada) |
| `APUD-TEXTO-001` / `002` / `003` | com `--texto-completo`: o texto aberto da consultada menciona a original (pelo sobrenome do primeiro autor) num trecho que sustenta a frase (errei-cita), menciona sem sustentar, ou não menciona |

A lista de referências da obra consultada é procurada em três bases, nesta ordem, e a busca
para na primeira em que a original aparece:

1. **OpenAlex** (`referenced_works`);
2. **Crossref**, quando a consultada tem DOI (as listas depositadas pelas editoras, abertas
   desde 2022);
3. **Semantic Scholar**, pelo DOI ou pela busca do título.

A original é reconhecida, nesta ordem de força, pelo registro do OpenAlex, pelo DOI, pelo
título (também dentro da referência como impressa) ou pelo sobrenome do primeiro autor e
ano. Uma referência do mesmo autor e ano com outro título não conta. O achado diz em que
base e por qual critério casou, e a confiança do `APUD-REDE-002` sobe quando mais de uma
lista foi conferida.

**Original só digitada**, como `Flesch (1948) apud \citeonline{martins1996}`: o errei a
procura pelo autor e ano na própria lista de referências da obra consultada. Achando, ela
fica identificada (título e DOI) e passa também pela conferência de acesso aberto. Fora das
listas, o errei recorre à obra mais citada desse autor nesse ano no OpenAlex, e só a aceita
quando ela tem pelo menos 10 vezes as citações da segunda: "Flesch 1948" são 12 obras no
OpenAlex, de dois autores. Essa identificação aparece marcada como "só por autor e ano".
A consultada digitada ligada ao `.bib` é conferida como as demais, pelos dados da entrada,
e os achados trazem a nota "conferida pela entrada ... do .bib".

O Semantic Scholar sem chave tem limite de requisições compartilhado e costuma responder
429. Quando isso acontece, o relatório diz que a base não respondeu, e não que a obra não
foi localizada.

Sem `--online`, nada sai da máquina e o relatório avisa que a conferência online foi
pulada (`CORE-NET-001`). A frase × obra original continua sendo validada pelo `refs`
(`REFS-ATRIB-*`), como em qualquer citação.

### Conferência com o Claude Code (opcional)

Se você usa o Claude Code (CLI `claude`), pode pedir que ele também confira cada citação
de citação na web:

```bash
errei . --online --ia-claude                            # modelo padrão: haiku
errei . --online --ia-claude --ia-claude-modelo sonnet
```

O Claude Code **não é a opção nativa**: fica desligado por padrão, não é necessário para
nenhuma verificação e nunca é o primeiro recurso. O errei faz tudo com o fonte e com bases
abertas, e o Claude Code só acrescenta o achado `APUD-IA-001`. Esse achado diz se a obra
consultada cita a original, se atribui a ela a ideia da frase e se a original está
acessível, com os links e os trechos que a IA diz ter lido.

Regras garantidas no código:

- **Ligar é explícito.** Só com `--online --ia-claude` ou com `[ia_claude] enabled = true`
  em `~/.config/errei/config.toml`. O `.errei.toml` do artigo não liga isso nem escolhe o
  executável.
- **Sessão isolada.** O `claude -p` roda numa pasta temporária vazia, sem ver os arquivos do
  trabalho, só com as ferramentas WebSearch e WebFetch. Não carrega servidores MCP, hooks,
  plugins, skills nem CLAUDE.md (`--safe-mode`) e não pede permissões: o que pediria é
  negado. A sessão não é gravada, e o tempo e o orçamento de cada consulta são limitados.
- **Envio mínimo.** São enviados a frase da citação de citação, os metadados das duas obras
  (autores, ano, título, veículo, DOI) e o que as bases abertas já mostraram. O relatório
  registra o que foi enviado, o número de chamadas e o custo (`meta.ia_claude`).
- **A IA não escreve o trabalho nem decide.** A resposta segue um esquema JSON fixo. A
  justificativa é cortada em 25 palavras, cada trecho em 300 caracteres, e só links
  `http(s)` são aceitos. Os trechos e links da IA **não são conferidos pelo errei** e
  aparecem marcados assim. O achado é sempre `info`.
- **Cache.** As respostas ficam no `http.sqlite` por 30 dias; `--sem-cache` pergunta de
  novo. Cada execução faz no máximo `max_consultas` consultas.

```toml
# ~/.config/errei/config.toml
[ia_claude]
enabled = false        # true liga sem --ia-claude (ainda exige --online)
modelo = "haiku"
comando = ""           # caminho do claude, se não estiver no PATH
max_consultas = 10
orcamento_usd = 0.5    # por consulta
timeout = 300          # segundos por consulta
```

O Claude Code é um programa da Anthropic, fechado e com uso cobrado na sua conta. Por isso
ele é só um complemento opcional e não uma dependência do errei. `errei doctor` mostra se
ele está instalado.

## Verificadores

Cada verificador é um plugin descoberto pelo grupo de entry points `errei.checkers`
(veja [Plugins](#plugins)).

| verificador | o que faz |
|---|---|
| `documento` | só em `.docx`/`.pdf`: o que foi lido, referências não reconhecidas, ordem alfabética da lista e `??` não resolvidos no PDF |
| `latex` | resolve `\input`/`\include`/`\subfile`/`\bibliography`/`\addbibresource`, acha o `.tex` principal, e aponta `\ref`/`\label` quebrados ou duplicados, ambientes e chaves desbalanceados, figuras/tabelas sem legenda ou nunca citadas, TODOs, blocos comentados, idioma pt-BR ausente e classe diferente de abnTeX2 |
| `refs` | `\cite` sem entrada, entradas nunca citadas, chaves duplicadas, campos obrigatórios por tipo, DOI/ISBN/arXiv. Com `--online`: existência via Crossref/OpenAlex (+arXiv), com classificação `confirmada` / `divergente` / `não encontrada (não verificada)` e score, e detecção de retratações |
| `abnt` | NBR 6022 (estrutura), 6023 (referências no `.bib`), 6028 (resumo e palavras-chave), 10520 (citações) e 14724 (o que está visível no fonte). Adapta-se a `abntex2cite`, `biblatex-abnt` e `natbib`. O que depende de renderização sai como "revisar manualmente" |
| `ptbr` | LanguageTool local (pt-BR) e regras próprias: Acordo Ortográfico, anglicismos, crase, regência, concordância, voz passiva, 1ª pessoa, parágrafos e frases longos, repetição e vícios acadêmicos. Ignora matemática, citações, referências, URLs e código |
| `escrita` | métricas explicadas por dimensão (sem nota única): Flesch adaptado (Martins et al., 1996), frases, parágrafos, passiva, MATTR, conectivos, citações por seção e equilíbrio entre seções; também siglas, consistência de termos, resumo × abstract e objetivo detectável |
| `plagio` | similaridade em camadas: (1) repetição interna, (2) corpus local opcional, (3) busca online de frases distintivas em metadados/resumos públicos |
| `ia` | indícios heurísticos e transparentes por parágrafo (burstiness, repetição, diversidade, conectivos, clichês de LLM, uniformidade, marcas autorais), com escore e motivos. Há um adapter opcional para detector externo |
| `periodico` | estrato Qualis **do periódico-alvo** (CSV), métricas abertas do OpenAlex e índice de prontidão 0–100 por componentes |
| `completude` | o que falta para o trabalho estar completo: checklist de elementos pré-textuais, textuais e pós-textuais da NBR 6022 (artigo) ou NBR 14724 (monografia, TCC, dissertação, tese), dados da capa/folha de rosto (abnTeX2) e o que escrever em cada elemento ausente |
| `nacionais` | com `--online`, sugere **artigos e livros brasileiros** para afirmações que citam obras estrangeiras (OpenAlex com autoria no Brasil, Open Library e Google Books em português), ordenados pelo modelo errei-cita |
| `apud` | citação de citação: ordem das obras, original também citada diretamente, consultada fora do `.bib`, excesso e lista de referências; com `--online`, acesso aberto da original e se a consultada a cita (listas de referências do OpenAlex, Crossref e Semantic Scholar e, com `--texto-completo`, o texto aberto), inclusive para original só digitada; com `--ia-claude`, a conferência opcional do Claude Code |
| `literatura` | com `--online`, para cada afirmação, fontes **nacionais e internacionais** (OpenAlex, Semantic Scholar; confirmadas por DOI/arXiv) em que o modelo errei-cita acha um trecho que **sustenta** a afirmação; as do mesmo tema que não sustentam aparecem como relacionadas |

## Tabela Qualis (CSV)

O Qualis classifica **periódicos**, não artigos. O errei não "dá Qualis ao artigo": ele
consulta o estrato do periódico-alvo numa tabela que **você** fornece, exportada da
Plataforma Sucupira (CAPES → Qualis Periódicos → exportar).

Formato esperado:

```text
ISSN;Título;Área de Avaliação;Estrato
1414-5685;REVISTA BRASILEIRA DE INFORMÁTICA NA EDUCAÇÃO;CIÊNCIA DA COMPUTAÇÃO;A3
1414-5685;REVISTA BRASILEIRA DE INFORMÁTICA NA EDUCAÇÃO;EDUCAÇÃO;A2
```

- Cabeçalho na primeira linha. Os nomes de coluna toleram acento e caixa e aceitam aliases:
  `ISSN`; `Título`/`Periódico`; `Área de Avaliação`/`Área`; `Estrato`/`Qualis`.
  São obrigatórias `Estrato` e (`ISSN` ou `Título`).
- Delimitador `;`, `,` ou tabulação. Codificação UTF-8 (com ou sem BOM) ou Latin-1/CP1252.
- Estratos válidos: A1–A4, B1–B5 e C. Outras linhas são ignoradas.
- Um periódico aparece uma vez por área de avaliação. Use `--area` para filtrar; sem ela,
  todas as áreas são listadas.
- **Informe a data de referência** com `--qualis-data AAAA-MM-DD` (ou `qualis_data` no
  config). Sem ela, o errei usa a data de modificação do arquivo e avisa. A data aparece no
  relatório, porque a CAPES vem reformulando o Qualis e o CSV é a fonte da verdade.

O **índice de prontidão** (0–100) soma componentes exibidos separadamente: estrutura IMRaD
(15), resumo/abstract/palavras-chave (15), qualidade das referências (25: DOI, idade mediana,
% de artigos de periódico, erros), tamanho (10; faixa configurável em `[periodico]`), normas
ABNT (15) e escrita (20). **Não prevê aceitação nem estrato.**

## Plugins

Um plugin é qualquer classe que implemente o protocolo `errei.checkers.base.Checker`
(`name`, `title`, `rules`, `phase`, `uses_network`, `run(project, ctx) -> list[Finding]`),
registrada no seu `pyproject.toml`:

```toml
[project.entry-points."errei.checkers"]
meu_checker = "meu_pacote.checker:MeuChecker"
```

Herdar de `errei.checkers.base.BaseChecker` registra as regras automaticamente (assim elas
aparecem em `errei explain`). O verificador recebe o `Project` já parseado (texto limpo com
mapa de posições, `.bib`, seções) e **não deve** escrever arquivos. Se ele lançar uma
exceção, o erro vira o achado `CORE-CHECKER-001` e os demais verificadores continuam.

## Limitações

- Num projeto LaTeX, o errei analisa o **fonte**, não o PDF. Macros próprias e pacotes
  incomuns podem gerar falsos positivos; a formatação final (margens, recuos, aparência das
  referências) precisa ser conferida no PDF.
- Num `.docx`/`.pdf`, títulos, citações e referências são reconhecidos por heurísticas
  (estilos, numeração, autor e ano). Citações em formatos incomuns podem não ser ligadas, e
  a extração do PDF pode colar palavras ou misturar colunas. Veja
  [Trabalhos em .docx e .pdf](#trabalhos-em-docx-e-pdf).
- **Similaridade ≠ plágio.** A comparação é com o próprio texto, com um corpus local que
  você indicar e (com `--online`) com metadados e resumos públicos. **Não substitui
  Turnitin/iThenticate**, que comparam com bases de texto completo.
- **Detecção de IA não é confiável.** Os indícios são heurísticas transparentes de baixa
  confiança: texto humano formal pode pontuar alto e texto de IA editado pode pontuar baixo.
  Nunca use como base única para acusação ou decisão.
- **Validação de atribuição é um indicador.** O modelo compara a frase com o *resumo* da
  fonte, foi treinado em biomedicina com português traduzido automaticamente e erra. Uma
  "contradição" é um convite a reler a fonte, não prova de má citação.
- **Referência "não encontrada" não é referência falsa.** Livros, relatórios e anais locais
  muitas vezes estão fora de Crossref/OpenAlex. É um convite à verificação manual.
- **Qualis é do periódico** e vem do CSV que você fornece. O índice de prontidão não prevê
  aceitação nem estrato.
- O LanguageTool e o dicionário de fallback podem marcar termos técnicos; use
  `.errei-dict.txt`. O dicionário `pyspellchecker` é majoritariamente europeu; o errei
  aceita as variantes brasileiras comuns, mas instale `hunspell-pt-br` se puder.
- A silabação usada no Flesch é heurística, e as faixas de referência das métricas são
  orientações gerais.

## Desenvolvimento

```bash
uv venv && uv pip install -e '.[all,dev]'
pytest                       # suíte padrão: sem rede e sem LanguageTool
pytest -m network            # inclui o teste com APIs reais
ERREI_TEST_LANGUAGETOOL=1 pytest -m languagetool
ruff check src tests && ruff format --check src tests && mypy
```

A fixture `tests/fixtures/artigo_exemplo/` é um artigo abnTeX2 com erros plantados.
`tests/test_acceptance.py` confere que cada um é detectado no arquivo e na linha corretos,
que nenhum arquivo é modificado (hash antes/depois) e que nenhuma conexão sai da máquina
sem `--online`.

## Regras

Gerada a partir do código (`errei explain --list`). "Heurística" significa aproximada, com
possíveis falsos positivos e negativos.

| Código | Severidade | Regra | Tipo |
|---|---|---|---|
| `ABNT-ABSTRACT-001` | aviso | Resumo em língua estrangeira ausente | determinística |
| `ABNT-CIT-001` | aviso | 'apud' digitado no texto | determinística |
| `ABNT-CIT-002` | aviso | Citação direta longa entre aspas | heurística |
| `ABNT-CIT-003` | sugestão | Forma de 'et al.' | determinística |
| `ABNT-CIT-004` | sugestão | Citação digitada manualmente | heurística |
| `ABNT-CIT-005` | aviso | Citação direta sem página | heurística |
| `ABNT-CIT-006` | info | Caixa do sobrenome na citação (NBR 10520:2023) | determinística |
| `ABNT-ESTR-001` | aviso | Introdução ausente | determinística |
| `ABNT-ESTR-002` | aviso | Conclusão/considerações finais ausente | determinística |
| `ABNT-ESTR-003` | erro | Lista de referências ausente | determinística |
| `ABNT-FMT-001` | info | Tamanho de fonte/papel | heurística |
| `ABNT-FMT-002` | info | Margens definidas no fonte | determinística |
| `ABNT-KW-001` | aviso | Palavras-chave ausentes | determinística |
| `ABNT-KW-002` | sugestão | Separador das palavras-chave | determinística |
| `ABNT-KW-003` | sugestão | Quantidade de palavras-chave | determinística |
| `ABNT-KW-004` | sugestão | Palavra-chave com inicial maiúscula | determinística |
| `ABNT-KW-005` | aviso | Palavras-chave sem ponto final | determinística |
| `ABNT-REF-001` | sugestão | Nome de autor digitado em maiúsculas | determinística |
| `ABNT-REF-002` | aviso | 'et al.' no campo author | determinística |
| `ABNT-REF-003` | aviso | Local de publicação ausente | determinística |
| `ABNT-REF-004` | aviso | Documento online sem data de acesso | determinística |
| `ABNT-REF-005` | aviso | Artigo sem volume ou páginas | determinística |
| `ABNT-RESUMO-001` | erro | Resumo ausente | determinística |
| `ABNT-RESUMO-002` | aviso | Resumo fora da extensão recomendada | determinística |
| `ABNT-RESUMO-003` | aviso | Resumo com mais de um parágrafo | determinística |
| `ABNT-RESUMO-004` | sugestão | Citação ou fórmula no resumo | determinística |
| `ABNT-RESUMO-005` | aviso | Resumo sem objetivo, método, resultados ou conclusões | heurística |
| `ABNT-STYLE-001` | info | Estilo de citação detectado | determinística |
| `ABNT-STYLE-002` | aviso | Estilo bibliográfico não ABNT | determinística |
| `APUD-ACESSO-001` | sugestão | Obra original disponível em acesso aberto | determinística |
| `APUD-CONS-001` | aviso | Obra consultada fora do .bib | determinística |
| `APUD-DIRETA-001` | aviso | Obra original também citada diretamente | determinística |
| `APUD-EXCESSO-001` | sugestão | Muitas citações de citação | heurística |
| `APUD-IA-001` | info | Avaliação do Claude Code (IA, opcional) | heurística |
| `APUD-LISTA-001` | info | Obra original na lista de referências | determinística |
| `APUD-MESMA-001` | erro | Mesma obra como original e consultada | determinística |
| `APUD-ORDEM-001` | aviso | Obra original posterior à obra consultada | heurística |
| `APUD-REDE-001` | info | A obra consultada cita a original | determinística |
| `APUD-REDE-002` | aviso | A obra consultada não cita a original nas bases | heurística |
| `APUD-TEXTO-001` | info | Original mencionada no texto aberto da consultada | heurística |
| `APUD-TEXTO-002` | sugestão | Trecho da consultada não sustenta a afirmação | heurística |
| `APUD-TEXTO-003` | aviso | Original não mencionada no texto aberto da consultada | heurística |
| `APUD-VERIF-001` | info | Citação de citação não verificável nas bases | determinística |
| `COMP-IA-001` | info | Orientações para completar (IA online) | heurística |
| `COMP-META-001` | aviso | Dado de identificação ausente | determinística |
| `COMP-OBRIG-001` | aviso | Elemento obrigatório ausente | determinística |
| `COMP-REC-001` | sugestão | Elemento recomendado ausente | heurística |
| `COMP-TIPO-001` | info | Tipo de trabalho | determinística |
| `CORE-CHECKER-001` | aviso | Verificador falhou | determinística |
| `CORE-DEP-001` | info | Dependência opcional ausente | determinística |
| `CORE-NET-001` | info | Fonte online indisponível | determinística |
| `CORE-PLUGIN-001` | info | Plugin não carregado | determinística |
| `CORE-PROJ-001` | info | Observação sobre o projeto | determinística |
| `DOC-CIT-001` | erro | Referência cruzada não resolvida | determinística |
| `DOC-LEITURA-001` | info | Documento lido | determinística |
| `DOC-LEITURA-002` | aviso | Leitura do PDF com limitações | heurística |
| `DOC-REF-001` | aviso | Referência não reconhecida | heurística |
| `DOC-REF-002` | aviso | Lista de referências fora da ordem alfabética | determinística |
| `ESCRITA-ABS-001` | aviso | Resumo e abstract inconsistentes | heurística |
| `ESCRITA-CIT-001` | sugestão | Seção de revisão sem citações | heurística |
| `ESCRITA-OBJ-001` | aviso | Objetivo não identificado | heurística |
| `ESCRITA-SEC-001` | sugestão | Seções desbalanceadas | heurística |
| `ESCRITA-SIGLA-001` | aviso | Sigla usada antes de ser definida | heurística |
| `ESCRITA-SIGLA-002` | sugestão | Sigla definida mais de uma vez | heurística |
| `ESCRITA-SIGLA-003` | sugestão | Sigla definida e não usada | heurística |
| `ESCRITA-TERMO-001` | sugestão | Termo com grafias diferentes | heurística |
| `IA-CLICHE-001` | sugestão | Frase-clichê | heurística |
| `IA-EXT-001` | info | Detector externo | determinística |
| `IA-IND-001` | info | Indícios de texto gerado por IA | heurística |
| `LATEX-BRACE-001` | erro | Chaves desbalanceadas | determinística |
| `LATEX-CLASS-001` | info | Classe diferente de abnTeX2 | determinística |
| `LATEX-COMMENT-001` | sugestão | Bloco grande de texto comentado | determinística |
| `LATEX-ENV-001` | erro | Ambiente não fechado ou descasado | determinística |
| `LATEX-FLOAT-001` | aviso | Figura/tabela sem legenda | determinística |
| `LATEX-FLOAT-002` | aviso | Figura/tabela não citada no texto | determinística |
| `LATEX-INPUT-001` | erro | Arquivo incluído não encontrado | determinística |
| `LATEX-INPUT-002` | erro | Inclusão fora da pasta do projeto | determinística |
| `LATEX-INPUT-003` | erro | Inclusão cíclica | determinística |
| `LATEX-LABEL-001` | erro | Rótulo duplicado | determinística |
| `LATEX-LABEL-002` | info | Rótulo nunca referenciado | determinística |
| `LATEX-LANG-001` | aviso | Idioma português não configurado | determinística |
| `LATEX-ORPHAN-001` | info | Arquivo .tex não incluído | determinística |
| `LATEX-PARSE-001` | info | Extração de texto aproximada | determinística |
| `LATEX-REF-001` | erro | Referência cruzada para rótulo inexistente | determinística |
| `LATEX-TODO-001` | aviso | Pendência esquecida | determinística |
| `LIT-LANG-001` | info | Trecho em outro idioma | determinística |
| `LIT-NONE-001` | info | Nenhuma fonte encontrada | determinística |
| `LIT-REL-001` | info | Fonte relacionada que NÃO sustenta a afirmação | heurística |
| `LIT-SUG-001` | sugestão | Fonte que sustenta a afirmação | heurística |
| `NAC-IA-001` | info | Sugestões da IA descartadas | determinística |
| `NAC-SUG-001` | sugestão | Obra brasileira para a mesma afirmação | heurística |
| `PERIOD-OA-001` | info | Métricas abertas do periódico (OpenAlex) | determinística |
| `PERIOD-QUALIS-001` | info | Estrato Qualis do periódico-alvo | determinística |
| `PERIOD-QUALIS-002` | aviso | Periódico não encontrado no CSV Qualis | determinística |
| `PERIOD-QUALIS-003` | info | Data do CSV Qualis não informada | determinística |
| `PERIOD-QUALIS-004` | info | Periódico-alvo não informado | determinística |
| `PERIOD-READY-001` | info | Índice de prontidão para submissão | heurística |
| `PERIOD-REFS-001` | info | Referências em periódicos do CSV Qualis | heurística |
| `PLAGIO-CORPUS-001` | aviso | Trecho semelhante no corpus local | heurística |
| `PLAGIO-CORPUS-002` | info | Problema ao ler o corpus local | determinística |
| `PLAGIO-INT-001` | aviso | Trecho repetido no próprio artigo | heurística |
| `PLAGIO-WEB-001` | aviso | Trecho semelhante a publicação indexada | heurística |
| `PTBR-ANGL-001` | sugestão | Anglicismo | heurística |
| `PTBR-CONC-001` | erro | Concordância | determinística |
| `PTBR-CRASE-001` | erro | Crase indevida | determinística |
| `PTBR-CRASE-002` | aviso | Crase ausente em locução | heurística |
| `PTBR-CRASE-003` | erro | Crase com demonstrativo | determinística |
| `PTBR-FRASE-001` | sugestão | Frase longa | determinística |
| `PTBR-LT-001` | aviso | Gramática (LanguageTool) | determinística |
| `PTBR-LT-002` | aviso | Ortografia (LanguageTool) | determinística |
| `PTBR-LT-003` | sugestão | Estilo/tipografia (LanguageTool) | determinística |
| `PTBR-ORTO-001` | aviso | Grafia anterior ao Acordo Ortográfico | determinística |
| `PTBR-PARAG-001` | sugestão | Parágrafo longo | determinística |
| `PTBR-PASSIVA-001` | sugestão | Voz passiva excessiva | heurística |
| `PTBR-PESSOA-001` | sugestão | Primeira pessoa do singular | heurística |
| `PTBR-REG-001` | sugestão | Regência verbal | heurística |
| `PTBR-REPET-001` | sugestão | Repetição de palavra | heurística |
| `PTBR-SPELL-001` | sugestão | Possível erro de ortografia | heurística |
| `PTBR-VICIO-001` | sugestão | Vício de linguagem acadêmica | determinística |
| `REFS-ARXIV-001` | aviso | Identificador arXiv inválido | determinística |
| `REFS-ATRIB-001` | info | Afirmação compatível com o resumo da fonte | heurística |
| `REFS-ATRIB-002` | aviso | Resumo da fonte parece contradizer a afirmação | heurística |
| `REFS-ATRIB-003` | sugestão | Atribuição não confirmada pelo resumo | heurística |
| `REFS-ATRIB-004` | info | Atribuição não verificável | determinística |
| `REFS-BIB-001` | sugestão | Entrada nunca citada | determinística |
| `REFS-BIB-002` | erro | Chave duplicada no .bib | determinística |
| `REFS-BIB-003` | aviso | Campo repetido na entrada | determinística |
| `REFS-BIB-004` | erro | Erro de sintaxe no .bib | determinística |
| `REFS-BIB-005` | aviso | Possível entrada duplicada | determinística |
| `REFS-CITE-001` | erro | Citação sem entrada na bibliografia | determinística |
| `REFS-DOI-001` | erro | DOI malformado | determinística |
| `REFS-DOI-002` | sugestão | Artigo sem DOI | determinística |
| `REFS-DOI-003` | sugestão | DOI com prefixo de URL | determinística |
| `REFS-EXIST-001` | info | Referência confirmada | heurística |
| `REFS-EXIST-002` | aviso | Referência com metadados divergentes | heurística |
| `REFS-EXIST-003` | aviso | Referência não encontrada (não verificada) | heurística |
| `REFS-FIELD-001` | aviso | Campos obrigatórios ausentes | determinística |
| `REFS-ISBN-001` | aviso | ISBN inválido | determinística |
| `REFS-NOBIB-001` | erro | Citações sem bibliografia | determinística |
| `REFS-QUOTE-001` | info | Citação direta localizada no texto aberto | heurística |
| `REFS-QUOTE-002` | aviso | Citação direta não localizada ou com página diferente | heurística |
| `REFS-RETRACT-001` | erro | Obra retratada | determinística |
| `REFS-YEAR-001` | aviso | Ano inválido | determinística |

## Licença

MIT. Veja [LICENSE](LICENSE). O errei é **inteiramente open source**, também nos modelos,
nos dados e nas dependências: nenhuma função exige serviço pago (o Gemini é opcional e
desligado por padrão, assim como o Claude Code em `--ia-claude`), e o teste `tests/test_licencas.py` falha se uma dependência
instalada declarar licença fora da lista aprovada pela OSI.

### Dependências e licenças

| pacote | extra | licença |
|---|---|---|
| typer, rich, pylatexenc | núcleo | MIT |
| tomli (Python < 3.11) | núcleo | MIT |
| httpx | online | BSD-3-Clause |
| rapidfuzz | online | MIT |
| language-tool-python | ptbr | GPL-3.0 (OSI; copyleft, só no extra opcional) |
| pyspellchecker | ptbr | MIT |
| pypdf | plagio | BSD-3-Clause |
| reportlab | pdf | BSD-3-Clause |
| torch | modelo, traducao | BSD-3-Clause |
| transformers | modelo, traducao | Apache-2.0 |
| sentencepiece | modelo, traducao | Apache-2.0 |

Programa externo opcional: o **Claude Code** (CLI `claude`, da Anthropic, fechado) só é
chamado com `--online --ia-claude`. Não é dependência Python, não é instalado pelo errei e
nenhuma função depende dele.

Modelos:

| modelo | licença | observação |
|---|---|---|
| `errei-cita-v1` | CC BY-NC 2.0 (herdada do SciFact) | será substituído pelo `errei-cita-v2` (ver `treino-gpu/`), treinado só com dados de uso comercial permitido |
| `errei-resumo-v1` | Apache-2.0 | |
| `opus-mt-ROMANCE-en` (tradutor opcional) | Apache-2.0 | Helsinki-NLP, usado só para montar a consulta em inglês |
