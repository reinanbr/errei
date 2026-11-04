# Anotações para o errei-cita-v2

Pares **afirmação (pt-BR) × trecho de uma fonte** anotados à mão. Licença: **CC BY 4.0**
(veja `LICENSE`). Cada arquivo `*.jsonl` desta pasta entra no treino, exceto
`exemplo.jsonl`, que é sintético e só serve para a fumaça.

## Formato (uma linha JSON por par)

| campo | obrigatório | descrição |
|---|---|---|
| `afirmacao` | sim | frase do artigo, como escrita (sem o `\cite`) |
| `trecho` | sim | trecho **copiado** da fonte, no idioma original (até ~600 caracteres) |
| `relacao` | sim | `sustenta`, `contradiz` ou `neutro` (o trecho não permite afirmar) |
| `lingua` | sim | idioma da afirmação (`pt` ou `en`) |
| `fonte` | sim | referência da obra (autores, ano, título) |
| `fonte_doi` | se houver | DOI da obra |
| `fonte_licenca` | sim | `cc-by`, `cc0` ou `public-domain`. Outras licenças são recusadas por `dados.py` |
| `pagina` | se houver | página do trecho no PDF |
| `anotador` | sim | quem anotou (nome ou apelido público) |
| `data` | sim | AAAA-MM-DD |

Exemplo:

```json
{"afirmacao": "A telemedicina aumenta a adesão ao tratamento em áreas rurais.", "trecho": "Adherence was 18% higher in the telemedicine group.", "relacao": "sustenta", "lingua": "pt", "fonte": "Sobrenome et al. (2021). Título. Periódico.", "fonte_doi": "10.xxxx/xxxx", "fonte_licenca": "cc-by", "pagina": 4, "anotador": "fulana", "data": "2026-11-04"}
```

## Como anotar

1. Use só obras de **acesso aberto com licença aberta** (confira no OpenAlex o campo
   `best_oa_location.license` ou na página do periódico).
2. **sustenta**: o trecho, sozinho, permite afirmar a frase. **contradiz**: o trecho afirma o
   contrário. **neutro**: mesmo tema, mas não permite afirmar (é o caso mais comum, e
   importante).
3. Para cada afirmação, anote pelo menos um trecho neutro do mesmo artigo.
4. Não traduza o trecho: o modelo precisa aprender a comparar pt-BR com o original.
