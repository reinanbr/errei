# errei

**errei** audita um artigo científico escrito em LaTeX (arquivos `.tex` e `.bib` de uma
pasta) e aponta problemas de **estrutura LaTeX, citações e referências, normas ABNT,
ortografia/gramática/estilo em pt-BR, qualidade textual, similaridade, indícios de texto
gerado por IA e prontidão para periódicos**.

Princípios:

- **Honestidade epistêmica.** Nenhum achado é veredito. Similaridade, indícios de IA e Qualis
  são *indicadores* com confiança e justificativa. Todo relatório traz a seção **Limitações**.
- **Offline por padrão.** Nada sai da máquina sem `--online`. O LanguageTool roda localmente.
- **Somente leitura.** Os arquivos do artigo nunca são alterados; não há autofix.
- **Rastreável.** Cada achado tem arquivo, linha, coluna, trecho, código da regra,
  severidade, mensagem e sugestão.

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
| `errei[pdf]` | `reportlab`: relatório em PDF (`--pdf`, `--format pdf`) |
| `errei[modelo]` | `torch` + `transformers`: modelo **errei-cita** de validação de citações |
| `errei[all]` | online, ptbr, plagio e pdf (o modelo é separado por ser grande) |

Sem um extra, o verificador correspondente é pulado em parte, e o relatório informa isso
com a regra `CORE-DEP-001`.

## Uso

```bash
errei .                              # audita a pasta atual
errei caminho/artigo                 # audita outra pasta
errei . --online                     # habilita checagens que usam rede
errei . --only abnt,refs             # roda só alguns verificadores (--skip para pular)
errei . --format md --out relatorio.md
errei . --format json --out relatorio.json
errei . --qualis-csv ~/qualis.csv --periodico "ISSN 1234-5678" --qualis-data 2025-07-01
errei . --fail-on warning            # código 1 também com avisos (útil em CI)
errei . --pdf relatorio.pdf          # mostra na tela E grava o relatório em PDF
errei . --resumo                     # na tela, só os principais problemas e melhorias
errei . --format pdf --out rel.pdf   # PDF como saída principal (resumo na tela)
errei . --online --texto-completo    # baixa PDFs abertos das obras para conferir citações diretas
errei modelo info                    # estado e métricas do modelo de citações errei-cita
errei init                           # cria .errei.toml comentado na pasta
errei doctor                         # verifica dependências (java, LanguageTool, hunspell)
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

- **term** (padrão): via `rich`, com resumo no topo, contagem por verificador e achados
  agrupados por arquivo e ordenados por severidade. Respeita `NO_COLOR` e saída não-TTY.
- **md**: relatório completo com versão, data, hash do projeto, flags, métricas e Limitações.
- **json**: o mesmo conteúdo, estruturado (`"schema": 1`), para integração.

- **pdf**: relatório completo para ler, imprimir ou enviar. Traz capa com resumo, **principais
  problemas (onde corrigir)**, **possíveis melhorias**, **referências verificadas** (obra
  encontrada, resumo e validação de cada frase que a cita), métricas, todos os achados por
  arquivo e limitações. Com `--pdf ARQ` a saída de tela continua normal.

Na tela, o topo do relatório mostra sempre os **principais problemas** e as **possíveis
melhorias** com `arquivo:linha` e a sugestão de correção. Com `--resumo` aparece só isso.

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
4. com `--texto-completo`, **procura as citações diretas** (trechos entre aspas) no PDF aberto
   da obra e confere a página indicada em `\cite[p.~N]{...}` (`REFS-QUOTE-*`).

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

## Configuração

Ordem de precedência: padrões ← `~/.config/errei/config.toml` ← `<artigo>/.errei.toml` ←
flags da linha de comando. Rode `errei init` para gerar um arquivo comentado.

> Segurança: opções que carregam código (como `[ia].detector`) só são aceitas do config do
> usuário ou da linha de comando, **nunca** do `.errei.toml` da pasta do artigo, que pode vir
> de terceiros. O conteúdo do artigo nunca é executado nem passado a `latex` ou ao shell.

## Verificadores

Cada verificador é um plugin descoberto pelo grupo de entry points `errei.checkers`
(veja [Plugins](#plugins)).

| verificador | o que faz |
|---|---|
| `latex` | resolve `\input`/`\include`/`\subfile`/`\bibliography`/`\addbibresource`, acha o `.tex` principal, e aponta `\ref`/`\label` quebrados ou duplicados, ambientes e chaves desbalanceados, figuras/tabelas sem legenda ou nunca citadas, TODOs, blocos comentados, idioma pt-BR ausente e classe diferente de abnTeX2 |
| `refs` | `\cite` sem entrada, entradas nunca citadas, chaves duplicadas, campos obrigatórios por tipo, DOI/ISBN/arXiv. Com `--online`: existência via Crossref/OpenAlex (+arXiv), com classificação `confirmada` / `divergente` / `não encontrada (não verificada)` e score, e detecção de retratações |
| `abnt` | NBR 6022 (estrutura), 6023 (referências no `.bib`), 6028 (resumo e palavras-chave), 10520 (citações) e 14724 (o que está visível no fonte). Adapta-se a `abntex2cite`, `biblatex-abnt` e `natbib`. O que depende de renderização sai como "revisar manualmente" |
| `ptbr` | LanguageTool local (pt-BR) e regras próprias: Acordo Ortográfico, anglicismos, crase, regência, concordância, voz passiva, 1ª pessoa, parágrafos e frases longos, repetição e vícios acadêmicos. Ignora matemática, citações, referências, URLs e código |
| `escrita` | métricas explicadas por dimensão (sem nota única): Flesch adaptado (Martins et al., 1996), frases, parágrafos, passiva, MATTR, conectivos, citações por seção e equilíbrio entre seções; também siglas, consistência de termos, resumo × abstract e objetivo detectável |
| `plagio` | similaridade em camadas: (1) repetição interna, (2) corpus local opcional, (3) busca online de frases distintivas em metadados/resumos públicos |
| `ia` | indícios heurísticos e transparentes por parágrafo (burstiness, repetição, diversidade, conectivos, clichês de LLM, uniformidade, marcas autorais), com escore e motivos. Há um adapter opcional para detector externo |
| `periodico` | estrato Qualis **do periódico-alvo** (CSV), métricas abertas do OpenAlex e índice de prontidão 0–100 por componentes |

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

- O errei analisa o **fonte LaTeX**, não o PDF. Macros próprias e pacotes incomuns podem
  gerar falsos positivos; a formatação final (margens, recuos, aparência das referências)
  precisa ser conferida no PDF.
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
| `ABNT-STYLE-001` | info | Estilo de citação detectado | determinística |
| `ABNT-STYLE-002` | aviso | Estilo bibliográfico não ABNT | determinística |
| `CORE-CHECKER-001` | aviso | Verificador falhou | determinística |
| `CORE-DEP-001` | info | Dependência opcional ausente | determinística |
| `CORE-NET-001` | info | Fonte online indisponível | determinística |
| `CORE-PLUGIN-001` | info | Plugin não carregado | determinística |
| `CORE-PROJ-001` | info | Observação sobre o projeto | determinística |
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
| `REFS-RETRACT-001` | erro | Obra retratada | determinística |
| `REFS-YEAR-001` | aviso | Ano inválido | determinística |

## Licença

MIT. Veja [LICENSE](LICENSE).
