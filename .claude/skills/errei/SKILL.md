---
name: errei
description: Audita um artigo científico em LaTeX (pt-BR) com a CLI errei e resume o relatório (estrutura, referências, ABNT, escrita, similaridade, indícios de IA, prontidão). Use quando o usuário pedir para revisar/auditar um artigo LaTeX ou rodar /errei.
---

# /errei — auditoria de artigo LaTeX

Camada fina sobre a CLI `errei`. Não reimplemente verificações: rode a CLI e resuma o JSON.

## Passos

1. Pasta do artigo: o argumento do usuário (`/errei caminho`) ou o diretório atual.
2. Rode a CLI gravando o JSON em arquivo temporário (somente leitura no artigo):

   ```bash
   errei "<pasta>" --format json --out "<tmp>/errei.json"
   ```

   - Repasse flags que o usuário pedir: `--online`, `--only`, `--skip`, `--qualis-csv`,
     `--periodico`, `--qualis-data`, `--area`.
   - **Não** adicione `--online` por conta própria: ele envia títulos e frases a APIs
     públicas (Crossref, OpenAlex, Semantic Scholar, arXiv). Pergunte antes.
   - Se o usuário quiser o relatório em PDF, acrescente `--pdf "<pasta>/errei-relatorio.pdf"`
     (ou o caminho que ele indicar) e informe onde ficou.
   - Com `--online`, o JSON traz `references[]`: obra encontrada (título, autores, ano,
     resumo, link) e, em `uses[]`, cada frase do artigo que a cita com `verdict`
     (`sustenta` / `contradiz` / `neutro`) e o trecho da fonte (`evidence`).
   - Código de saída 1 = há erros (normal); 2 = problema de uso/ambiente (mostre a mensagem
     de stderr e sugira `errei doctor`).
3. Leia o JSON (`schema` 1): `summary.by_severity`, `summary.by_checker`, `findings[]`
   (`code`, `severity`, `file`, `line`, `column`, `message`, `suggestion`, `confidence`,
   `evidence`), `metrics[]` e `limitations[]`.
4. Responda em pt-BR, conciso:
   - uma linha de totais (erros/avisos/sugestões) e verificadores rodados (online sim/não);
   - **Erros** primeiro, como `arquivo:linha — mensagem → sugestão` (no máximo ~15; diga
     quantos ficaram de fora);
   - **Avisos** agrupados por verificador, com os mais relevantes;
   - métricas-chave: legibilidade, índice de prontidão (com seus componentes) e, se houver,
     estrato Qualis **do periódico** com a data do CSV;
   - similaridade e IA sempre como **indícios**, com a confiança e os motivos do JSON;
   - citações: liste primeiro as `contradiz` (frase do artigo × trecho da fonte); `neutro`
     significa "o resumo não permite confirmar", não "citação errada";
   - feche com 1–2 linhas da seção Limitações.
5. Nunca use linguagem de veredito ("é plágio", "foi escrito por IA", "referência falsa").
   Use "trecho semelhante", "indício", "não verificada".
6. Não edite os arquivos do artigo. Se o usuário pedir correções, proponha-as como diffs e
   só aplique com confirmação.

Para detalhar uma regra: `errei explain <CODIGO>`.
