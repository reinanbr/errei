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
}


def limitations_for(checkers: list[str]) -> list[str]:
    return GENERAL + [BY_CHECKER[c] for c in checkers if c in BY_CHECKER]
