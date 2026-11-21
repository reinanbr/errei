"""Leitura de trabalhos em ``.docx`` e ``.pdf``.

O documento vira um projeto equivalente ao de LaTeX (texto em parágrafos, títulos,
resumo, citações e uma lista de referências como entradas bibliográficas), para que os
verificadores de texto, ABNT, referências e literatura funcionem sem mudança. Cada achado
aponta para o parágrafo (``.docx``) ou a página (``.pdf``) do arquivo original, que nunca
é alterado.
"""

from __future__ import annotations

from errei.documento.modelo import FORMATOS, Bloco, Documento, DocumentoError

__all__ = ["FORMATOS", "Bloco", "Documento", "DocumentoError"]
