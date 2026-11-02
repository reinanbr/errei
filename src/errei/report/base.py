"""Base do relatório: normas, fontes, modelos e ferramentas usados nesta execução.

Vai para o rodapé do PDF, para a seção final do PDF/Markdown/lista de afazeres e para
``meta.base`` no JSON, para que qualquer leitor saiba em que o relatório se apoiou.
"""

from __future__ import annotations

from typing import Any

NORMAS = {
    "abnt": [
        "ABNT NBR 6022:2018 (artigo em publicação periódica)",
        "ABNT NBR 6023:2018 (referências)",
        "ABNT NBR 6028:2021 (resumo)",
        "ABNT NBR 10520:2023 (citações)",
        "ABNT NBR 14724:2011 (trabalhos acadêmicos)",
    ],
    "completude": [
        "ABNT NBR 6022:2018 (artigo em publicação periódica)",
        "ABNT NBR 14724:2011 (trabalhos acadêmicos)",
    ],
    "ptbr": ["Acordo Ortográfico da Língua Portuguesa (1990), VOLP/ABL"],
}

HOSTS = {
    "api.crossref.org": "Crossref (metadados e DOI)",
    "api.openalex.org": "OpenAlex (obras, resumos, periódicos, autoria brasileira)",
    "api.semanticscholar.org": "Semantic Scholar (resumos e PDFs abertos)",
    "export.arxiv.org": "arXiv (preprints)",
    "openlibrary.org": "Open Library (livros em português)",
    "www.googleapis.com": "Google Books (livros em português)",
    "generativelanguage.googleapis.com": "Google Gemini (IA online, opcional)",
}

METODOS = {
    "escrita": "Legibilidade: Flesch adaptado ao português (Martins et al., 1996); "
    "diversidade lexical MATTR; métricas de frase, parágrafo, passiva e conectivos",
    "ia": "Indícios de IA: heurísticas transparentes com pesos em data/ia_pesos.tsv "
    "(sem modelo treinado; não é detecção)",
    "plagio": "Similaridade: shingles de 8 palavras com MinHash/Jaccard (interna e corpus "
    "local); online, frases distintivas em metadados/resumos públicos",
    "periodico": "Índice de prontidão: soma ponderada explícita (IMRaD 15, resumos 15, "
    "referências 25, tamanho 10, normas 15, escrita 20)",
    "ptbr": "Gramática: LanguageTool local (quando disponível) e regras próprias (data/*.tsv)",
}


def build_base(meta: dict[str, Any], checkers: list[str], hosts: set[str]) -> dict[str, Any]:
    normas: list[str] = []
    for c in checkers:
        for n in NORMAS.get(c, []):
            if n not in normas:
                normas.append(n)
    fontes = [HOSTS.get(h, h) for h in sorted(hosts) if h]
    if not meta.get("online"):
        fontes = ["nenhuma: execução offline (nada saiu da máquina)"]
    elif not fontes:
        fontes = ["nenhuma consulta foi necessária"]
    modelos: list[str] = []
    if meta.get("modelo_citacoes"):
        modelos.append(
            "errei-cita-v1 (atribuição de citações): ajuste fino de "
            "MoritzLaurer/multilingual-MiniLMv2-L6-mnli-xnli com SciFact (pesos CC BY-NC 2.0)"
        )
    if meta.get("modelo_resumo"):
        modelos.append(str(meta["modelo_resumo"]))
    ia = meta.get("ia_online")
    if ia:
        modelos.append(
            f"Google Gemini {ia.get('modelo')} (opcional, --ia-online): só sugestões e "
            "orientações, referências conferidas em bases abertas"
        )
    else:
        modelos.append("IA online: não utilizada (opcional, desligada por padrão)")
    metodos = [METODOS[c] for c in checkers if c in METODOS]
    outros: list[str] = []
    if meta.get("qualis_csv"):
        outros.append(
            f"Qualis: CSV {meta.get('qualis_csv')} (data de referência "
            f"{meta.get('qualis_data')}, {meta.get('qualis_data_origem')})"
        )
    return {
        "ferramenta": f"errei {meta.get('version')} — {meta.get('date')}",
        "projeto": f"{meta.get('main') or '?'} · sha256 {str(meta.get('project_hash', ''))[:16]}",
        "verificadores": ", ".join(checkers),
        "normas": normas,
        "fontes": fontes,
        "modelos": modelos,
        "metodos": metodos + outros,
    }


def base_lines(base: dict[str, Any]) -> list[tuple[str, str]]:
    """(rótulo, texto) para renderização."""
    out = [
        ("Ferramenta", str(base.get("ferramenta", ""))),
        ("Projeto analisado", str(base.get("projeto", ""))),
        ("Verificadores", str(base.get("verificadores", ""))),
    ]
    for label, key in (
        ("Normas", "normas"),
        ("Fontes consultadas", "fontes"),
        ("Modelos", "modelos"),
        ("Métodos", "metodos"),
    ):
        items = base.get(key) or []
        if items:
            out.append((label, "; ".join(str(i) for i in items)))
    return out


def footer_text(base: dict[str, Any]) -> str:
    """Linha curta para o rodapé de cada página."""
    normas = ", ".join(n.split(" (")[0].replace("ABNT ", "") for n in base.get("normas", []))
    fontes = base.get("fontes") or []
    on = (
        "offline"
        if fontes and str(fontes[0]).startswith("nenhuma: execução offline")
        else ", ".join(str(f).split(" (")[0] for f in fontes)
    )
    parts = [str(base.get("ferramenta", "")).split(" — ")[0]]
    if normas:
        parts.append(f"normas: {normas}")
    parts.append(f"fontes: {on}")
    return " · ".join(parts)
