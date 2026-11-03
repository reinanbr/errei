"""Referência empírica por área: como escrevem os trabalhos mais citados.

``errei referencia construir --area educacao --escopo brasil`` seleciona no OpenAlex obras
de acesso aberto no top 10% de citações normalizadas da área (com autoria no Brasil, para
o escopo ``brasil``), mede cada uma (referências, extensão, escrita, declarações, papéis
do resumo) e guarda só **quantis agregados** em ``~/.local/share/errei/referencias``. Os
textos são lidos em memória e descartados: nada do conteúdo das obras é gravado.

Com ``errei . --area educacao --referencia brasil`` cada dimensão do manuscrito aparece ao
lado dos quantis da referência (p10–p90, com n), sem nota única.
"""
