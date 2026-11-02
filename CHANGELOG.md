# Changelog

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/); versões
seguem [SemVer](https://semver.org/lang/pt-BR/).

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
