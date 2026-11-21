"""Texto fixo da seção "Limitações" (sempre presente em todo relatório)."""

from __future__ import annotations

GENERAL = [
    "O errei é um auxílio à revisão, não um revisor. Nenhum achado é um veredito: "
    "cada item deve ser conferido por uma pessoa.",
    "A análise é feita sobre o código-fonte LaTeX, não sobre o PDF compilado. Macros "
    "próprias, pacotes incomuns e formatação dependente de renderização podem gerar "
    'falsos positivos ou passar despercebidos (itens marcados como "revisar manualmente").',
    "Os arquivos do artigo nunca são modificados; as sugestões aparecem só neste relatório.",
]

BY_CHECKER = {
    "refs": 'Referências marcadas como "não encontrada" não são falsas por definição: '
    "podem ser obras fora das bases consultadas (livros, relatórios, literatura cinzenta) "
    "ou ter metadados divergentes. A verificação de existência só ocorre com --online.",
    "abnt": "Só são apontadas regras ABNT verificáveis com segurança no fonte. Recuos, "
    "margens, fontes e a aparência final das referências dependem da classe e do estilo "
    "bibliográfico e precisam ser conferidos no PDF.",
    "ptbr": "Ortografia e gramática usam LanguageTool (quando disponível) e regras próprias. "
    "Termos técnicos, nomes próprios e estrangeirismos legítimos podem ser sinalizados; "
    "use .errei-dict.txt ou '% errei: ignore'.",
    "escrita": "As métricas de escrita (inclusive a legibilidade de Flesch adaptada por "
    "Martins et al.) são aproximações estatísticas e não medem qualidade científica.",
    "plagio": "Os resultados de similaridade são indicadores, não a constatação de plágio. "
    "A ferramenta compara o texto apenas consigo mesmo, com o corpus local que você indicar e, "
    "com --online, com metadados/resumos públicos (OpenAlex, Crossref, Semantic Scholar, "
    "arXiv). Ela NÃO substitui serviços com grandes bases de texto completo, como "
    "Turnitin ou iThenticate. Trechos citados corretamente também podem aparecer.",
    "ia": "Detectar texto gerado por IA não é confiável: não existe método robusto, e "
    "textos humanos formais (especialmente de não nativos ou muito revisados) podem ter "
    "escores altos, assim como textos de IA editados podem ter escores baixos. Os "
    "indícios aqui são heurísticas transparentes, com confiança baixa, e nunca devem "
    "servir de base única para acusação ou decisão.",
    "periodico": "Qualis é uma classificação de periódicos, não de artigos. O estrato "
    "exibido vem exclusivamente do CSV fornecido (e de sua data), e a CAPES vem "
    "reformulando o Qualis. O índice de prontidão resume sinais objetivos do manuscrito "
    "e NÃO prevê aceitação nem estrato.",
    "completude": "A completude é verificada pelo fonte (comandos, ambientes e títulos de "
    "seção). Elementos gerados por macros próprias, pelo template do periódico ou inseridos "
    "pela editora podem aparecer como ausentes; o tipo de trabalho é detectado por "
    "heurística (use --tipo para fixar).",
    "nacionais": "As obras nacionais sugeridas existem nas bases consultadas (OpenAlex, "
    "Open Library, Google Books), mas a afinidade com a afirmação é estimada pelo resumo ou pela "
    "descrição, não pelo texto completo. Leia antes de citar. A obra estrangeira pode "
    "continuar sendo a fonte mais adequada.",
    "literatura": "As fontes sugeridas por afirmação foram localizadas e confirmadas em bases "
    "abertas (OpenAlex, Crossref, Semantic Scholar, arXiv), mas 'sustenta' é a estimativa de "
    "um modelo local (errei-cita) sobre o resumo e, com --texto-completo, sobre trechos do "
    "texto completo de acesso livre: é indicador, não veredito. Sugestões da rede de "
    "citações são obras próximas às suas referências, não necessariamente as melhores do "
    "tema. Os trechos são mostrados no idioma "
    "original, com no máximo 300 caracteres e a fonte; leia a obra antes de citar. A busca "
    "não cobre bases fechadas, e a ausência de fonte não significa que a afirmação esteja "
    "errada.",
    "apud": "A conferência das citações de citação (apud) lê o fonte e, com --online, as "
    "bases abertas: a lista de referências do OpenAlex é incompleta (livros, capítulos e "
    "obras antigas costumam faltar), então 'não cita' é um convite a conferir, não prova. "
    "Com --texto-completo, a obra original é procurada pelo sobrenome do primeiro autor no "
    "texto de acesso livre da obra consultada, o que falha com PDFs mal extraídos e grafias "
    "diferentes. O errei não sabe se você leu a original: só aponta incoerências.",
    "referencia": "A referência por área compara o manuscrito com quantis de uma amostra "
    "de obras de acesso aberto no top 10% de citações normalizadas do OpenAlex (a "
    "procedência, o n e a data aparecem na tabela). Citação mede impacto, não qualidade; a "
    "classificação de área do OpenAlex é automática; o nº de referências da amostra só "
    "conta as obras que o OpenAlex localizou, e as medidas de texto vêm de PDFs (com "
    "legendas e tabelas), enquanto as do manuscrito vêm do texto analisado. Estar fora da "
    "faixa usual "
    "não é erro, e estar dentro não garante aceite.",
}

IA_ONLINE = (
    "Com --ia-online, trechos do trabalho (frases que citam obras estrangeiras, título e "
    "títulos de seção) foram enviados ao Google Gemini. As respostas da IA aparecem só como "
    "orientações curtas e referências já conferidas em bases abertas; nenhuma é texto para "
    "copiar, e o errei não escreve no trabalho. Redija com suas próprias palavras."
)

IA_CLAUDE = (
    "Com --ia-claude, a frase de cada citação de citação e os metadados das duas obras foram "
    "enviados ao Claude Code (Anthropic), que buscou e leu páginas na web numa sessão isolada, "
    "sem acesso aos arquivos do trabalho. As respostas da IA aparecem só como indicadores "
    "(APUD-IA-001), com os links e os trechos que ela diz ter lido, e não são conferidas pelo "
    "errei: confira-os. A IA não decide nada sozinha e o errei não escreve no trabalho."
)


DOCX = (
    "O .docx é lido sem o Word: o texto dos parágrafos, os estilos de título, o resumo e a "
    "lista de referências. Notas de rodapé, caixas de texto, tabelas, equações, comentários, "
    "cabeçalhos e rodapés não são analisados; o texto apagado em alterações controladas é "
    "ignorado. A localização é o número do parágrafo (sem contar os vazios)."
)
PDF = (
    "O texto do PDF é extraído sem OCR: PDFs digitalizados (imagem) não são lidos. Colunas, "
    "hifenização, cabeçalhos e rodapés são tratados por heurística e podem gerar falsos "
    "positivos (palavras coladas, ordem trocada em duas colunas). Títulos são reconhecidos "
    "pela numeração, por maiúsculas e pelos nomes usuais das seções. A localização é a página."
)
DOC_REFS = (
    "No .docx/.pdf, as citações (NBR 10520, APA, numéricas) e a lista de referências são "
    "texto digitado: o errei as reconhece por autor e ano (ou número). Citações em formato "
    "incomum podem não ser ligadas, e campos da referência (periódico, volume, páginas) podem "
    "não ser separados; por isso não há verificação de campos obrigatórios."
)


ABNT_DOC = (
    "No .docx/.pdf, a ABNT é verificada no texto lido (seções, resumo, palavras-chave, "
    "citações, lista de referências) e, no .docx, no tamanho do papel, nas margens e na "
    "fonte padrão. Recuos, espaçamento e a aparência final precisam ser conferidos no arquivo."
)


def limitations_for(checkers: list[str], formato: str = "latex") -> list[str]:
    if formato == "latex":
        return GENERAL + [BY_CHECKER[c] for c in checkers if c in BY_CHECKER]
    out = [GENERAL[0], GENERAL[2]]
    out += [ABNT_DOC if c == "abnt" else BY_CHECKER[c] for c in checkers if c in BY_CHECKER]
    if formato == "docx":
        out += [DOCX, DOC_REFS]
    elif formato == "pdf":
        out += [PDF, DOC_REFS]
    return out
