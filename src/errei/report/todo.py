"""Lista de afazeres (Markdown) para corrigir e aperfeiçoar o trabalho.

Transforma o relatório em um checklist priorizado, calibrado pelo nível que o autor
quer alcançar:

* ``tcc`` — trabalho de conclusão de curso;
* ``mestrado`` — dissertação ou artigo de mestrado;
* ``doutorado`` — tese ou artigo de doutorado;
* ``a1`` — padrão mais exigente: periódico Scopus com percentil ≥ 92 ou Qualis A1/A2.

Prioridades: P0 (bloqueia a entrega), P1 (necessário para o nível), P2
(aperfeiçoamento). Cada item traz onde está, o que fazer e o código da regra. As metas
de cada nível são referências usuais, não garantia de aprovação ou aceite.

Ao regerar a lista sobre um arquivo existente, os itens que deixaram de aparecer são
listados como resolvidos. O arquivo é só um relatório: o errei nunca altera o trabalho.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from errei import rules as rules_registry
from errei.model import Finding, Severity
from errei.report.build import Report
from errei.text.segment import strip_accents


@dataclass(frozen=True, slots=True)
class Nivel:
    key: str
    nome: str
    descricao: str
    refs_artigo: int
    refs_mono: int
    recentes: float  # fração das referências dos últimos 5 anos
    doi: float  # fração de artigos de periódico com DOI
    periodicos: float  # fração das referências que são artigos de periódico
    palavras_artigo: int
    palavras_mono: int
    prontidao: int  # índice de prontidão (0–100)
    max_avisos: int
    rigor: int  # 0 tcc, 1 mestrado, 2 doutorado, 3 a1
    declaracoes: tuple[str, ...]
    manual: tuple[str, ...]


NIVEIS: dict[str, Nivel] = {
    "tcc": Nivel(
        "tcc",
        "TCC (graduação)",
        "trabalho de conclusão de curso aprovado pela banca",
        15,
        20,
        0.30,
        0.30,
        0.30,
        4000,
        8000,
        50,
        20,
        0,
        ("objetivo", "problema"),
        (
            "Revise com o orientador o alinhamento objetivo ↔ método ↔ conclusão.",
            "Confira a formatação no PDF compilado (margens, fonte, espaçamento, paginação).",
            "Leia o trabalho em voz alta uma vez inteira: frases longas e repetições aparecem.",
        ),
    ),
    "mestrado": Nivel(
        "mestrado",
        "Mestrado",
        "dissertação aprovada ou artigo em periódico Qualis B1–A4",
        25,
        50,
        0.40,
        0.50,
        0.50,
        5000,
        20000,
        65,
        10,
        1,
        ("objetivo", "problema", "limitacoes", "contribuicao", "futuros", "etica"),
        (
            "Revise com o orientador o alinhamento objetivo ↔ método ↔ conclusão.",
            "Garanta que a metodologia permita replicar o estudo (dados, instrumentos, "
            "procedimentos, análise).",
            "Discuta cada resultado à luz de pelo menos dois trabalhos recentes.",
            "Confira a formatação no PDF compilado (margens, fonte, espaçamento, paginação).",
        ),
    ),
    "doutorado": Nivel(
        "doutorado",
        "Doutorado",
        "tese aprovada ou artigo em periódico Qualis A2–A1",
        35,
        100,
        0.50,
        0.70,
        0.60,
        6000,
        40000,
        75,
        5,
        2,
        (
            "objetivo",
            "problema",
            "limitacoes",
            "contribuicao",
            "futuros",
            "etica",
            "dados",
        ),
        (
            "Explicite a tese (a afirmação original) e mostre como cada capítulo/seção a sustenta.",
            "Cubra o estado da arte internacional dos últimos 5 anos (Scopus, Web of "
            "Science) e mostre a lacuna que o trabalho preenche.",
            "Garanta que a metodologia permita replicar o estudo.",
            "Peça leitura crítica a dois pesquisadores da área antes do depósito/submissão.",
        ),
    ),
    "a1": Nivel(
        "a1",
        "Excelência (Scopus percentil ≥ 92 / Qualis A1–A2)",
        "artigo aceito em periódico de alto impacto",
        40,
        100,
        0.50,
        0.85,
        0.70,
        6000,
        40000,
        85,
        0,
        3,
        (
            "objetivo",
            "problema",
            "limitacoes",
            "contribuicao",
            "futuros",
            "etica",
            "dados",
            "conflito",
            "autoria",
            "financiamento",
            "ia",
        ),
        (
            "Escolha o periódico-alvo (Scopus percentil ≥ 92 ou Qualis A1/A2) e rode o errei "
            "com --periodico e --qualis-csv.",
            "Adapte ao template e às instruções aos autores: limite de palavras, estrutura e "
            "estilo de referência (muitos usam APA ou Vancouver, não ABNT).",
            "Considere submeter em inglês, com revisão profissional de idioma.",
            "Deixe a contribuição explícita no resumo, no fim da introdução e na conclusão.",
            "Disponibilize dados e código em repositório aberto (Zenodo, OSF, GitHub) com DOI.",
            "Prepare a carta ao editor: lacuna, contribuição e adequação ao escopo do periódico.",
            "Verifique a similaridade no iThenticate/Turnitin institucional (o errei não o "
            "substitui).",
            "Peça leitura crítica a dois pesquisadores da área antes de submeter.",
        ),
    ),
}

# elementos de conteúdo/declarações detectáveis no texto
DECLARACOES: dict[str, tuple[str, str, str]] = {
    # chave: (nome, regex sobre texto sem acento e minúsculo, como resolver)
    "objetivo": (
        "Objetivo explícito",
        r"\bobjetivo",
        "declare o objetivo geral no fim da introdução ('Este trabalho tem como objetivo...')",
    ),
    "problema": (
        "Problema/pergunta de pesquisa ou hipótese",
        r"(pergunta de pesquisa|questao de pesquisa|problema de pesquisa|hipotese|"
        r"questao norteadora|research question)",
        "formule a pergunta de pesquisa (ou hipótese) que o trabalho responde",
    ),
    "limitacoes": (
        "Limitações do estudo",
        r"limitac",
        "inclua um parágrafo com as limitações (amostra, método, generalização)",
    ),
    "contribuicao": (
        "Contribuição/lacuna explícita",
        r"(lacuna|contribui\w* (deste|desta|do presente|da presente|principal|original)|"
        r"ineditismo|originalidade|\bgap\b)",
        "diga qual lacuna da literatura o trabalho preenche e qual é a contribuição",
    ),
    "futuros": (
        "Trabalhos futuros",
        r"(trabalhos futuros|pesquisas futuras|estudos futuros|future work)",
        "aponte desdobramentos concretos na conclusão",
    ),
    "etica": (
        "Aprovação ética (pesquisa com pessoas)",
        r"(comite de etica|\bcep\b|caae|parecer consubstanciado|ethics committee|"
        r"consentimento livre)",
        "informe o parecer do Comitê de Ética (CAAE) e o TCLE",
    ),
    "dados": (
        "Disponibilidade de dados e código",
        r"(disponibilidade de dados|data availability|dados (estao|sao|serao|ficam) "
        r"disponiveis|zenodo|figshare|\bosf\b|github\.com|repositorio)",
        "adicione a seção 'Disponibilidade de dados' com link/DOI do repositório",
    ),
    "conflito": (
        "Declaração de conflito de interesses",
        r"(conflitos? de interesses?|conflicts? of interest|competing interests)",
        "adicione 'Os autores declaram não haver conflito de interesses' (ou declare-os)",
    ),
    "autoria": (
        "Contribuição dos autores (CRediT)",
        r"(contribuic\w+ dos autores|author contributions|credit)",
        "descreva o papel de cada autor pela taxonomia CRediT",
    ),
    "financiamento": (
        "Financiamento",
        r"(financiamento|fomento|\bcapes\b|\bcnpq\b|fapesp|\bfap[a-z]+\b|funding|"
        r"apoio financeiro|bolsa)",
        "informe agências de fomento e números de processo (ou 'sem financiamento')",
    ),
    "ia": (
        "Declaração de uso de IA (só se você usou IA)",
        r"(inteligencia artificial generativa|uso de (ia|inteligencia artificial)|"
        r"chatgpt|gemini|large language model|modelos? de linguagem)",
        "opcional: só declare se usou IA na escrita ou na análise e o periódico pedir",
    ),
}
# declarações que só se aplicam em alguns casos: aparecem como informação, nunca como pendência
OPCIONAIS = {"ia"}
HUMANOS = re.compile(
    r"(participantes|entrevistad|questionari|pacientes|voluntari|respondentes|"
    r"grupo focal|sujeitos da pesquisa)"
)

AREA = {
    "completude": "Completude do trabalho",
    "latex": "Estrutura LaTeX",
    "refs": "Referências e citações",
    "nacionais": "Referências e citações",
    "abnt": "Normas ABNT",
    "ptbr": "Língua portuguesa",
    "escrita": "Escrita e clareza",
    "plagio": "Originalidade e similaridade",
    "ia": "Voz autoral (indícios de IA)",
    "periodico": "Prontidão para periódico",
    "core": "Ambiente da verificação",
    "metas": "Metas do nível",
}
AREA_ORDER = list(dict.fromkeys(AREA.values()))

P0_CODES = {"REFS-ATRIB-002", "REFS-EXIST-003", "REFS-RETRACT-001", "COMP-OBRIG-001"}
P2_INFO = {
    "NAC-SUG-001",
    "IA-IND-001",
    "COMP-IA-001",
    "REFS-ATRIB-003",
    "REFS-ATRIB-004",
    "CORE-DEP-001",
}
PROMOTE_CHECKERS = {"abnt", "escrita", "refs", "completude", "ia", "plagio", "latex"}
GROUP_MIN = 4  # a partir de quantas ocorrências do mesmo código vira um item agrupado


@dataclass(slots=True)
class Item:
    id: str
    prioridade: str  # P0 | P1 | P2
    area: str
    titulo: str
    onde: list[str] = field(default_factory=list)
    como: str = ""
    detalhe: list[str] = field(default_factory=list)
    codigo: str = ""


def _norm(s: str) -> str:
    return " ".join(strip_accents(s.lower()).split())


def _hid(*parts: str) -> str:
    return hashlib.sha1("\x1f".join(parts).encode()).hexdigest()[:10]


def _where(f: Finding) -> str:
    if f.location is None:
        return ""
    return f"{f.location.file.as_posix()}:{f.location.line}"


def _priority(f: Finding, nivel: Nivel) -> str | None:
    if f.code in P0_CODES or f.severity is Severity.ERRO:
        return "P0"
    if f.severity is Severity.AVISO:
        return "P1"
    if f.severity is Severity.SUGESTAO:
        if f.code == "COMP-REC-001" and nivel.rigor >= 1:
            return "P1"
        if nivel.rigor >= 2 and f.checker in PROMOTE_CHECKERS:
            return "P1"
        return "P2"
    if f.code in P2_INFO:
        return "P2"
    return None


def items_from_findings(report: Report, nivel: Nivel) -> list[Item]:
    groups: dict[tuple[str, str], list[Finding]] = defaultdict(list)
    for f in report.findings:
        if f.code.startswith("CORE") and f.code not in P2_INFO:
            continue
        pr = _priority(f, nivel)
        if pr is None:
            continue
        groups[(pr, f.code)].append(f)
    out: list[Item] = []
    for (pr, code), fs in groups.items():
        area = AREA.get(fs[0].checker, fs[0].checker)
        rule = rules_registry.get(code)
        if len(fs) >= GROUP_MIN and rule is not None:
            onde = [w for w in dict.fromkeys(_where(f) for f in fs) if w]
            como = next((f.suggestion for f in fs if f.suggestion), "") or ""
            exemplos = [f"{_where(f) or '—'}: {f.message}" for f in fs[:3]]
            out.append(
                Item(
                    _hid(code, "grupo"),
                    pr,
                    area,
                    f"{rule.title} ({len(fs)} ocorrências)",
                    onde,
                    como,
                    ["exemplos:", *exemplos],
                    code,
                )
            )
            continue
        for f in fs:
            det: list[str] = []
            if f.excerpt and not f.code.startswith("COMP-"):
                det.append(f"trecho: “{f.excerpt}”")
            det += [e for e in f.evidence[:4]]
            out.append(
                Item(
                    _hid(code, _where(f).split(":")[0], f.message),
                    pr,
                    area,
                    f.message[0].upper() + f.message[1:] if f.message else code,
                    [w for w in [_where(f)] if w],
                    f.suggestion or "",
                    det,
                    code,
                )
            )
    return out


# ------------------------------------------------------------------ metas do nível
@dataclass(slots=True)
class Meta:
    nome: str
    alvo: str
    atual: str
    ok: bool | None  # None = não medido
    como: str


def _bib_stats(project: Any) -> dict[str, Any]:
    if project is None:
        return {}
    cited = {u.key for u in project.cite_uses()}
    entries = [e for e in project.bib_entries if e.key in cited] or []
    seen: dict[str, Any] = {}
    for e in entries:
        seen.setdefault(e.key, e)
    entries = list(seen.values())
    now = date.today().year
    years = []
    for e in entries:
        m = re.search(r"\d{4}", e.get("year") or e.get("date"))
        if m:
            years.append(int(m.group(0)))
    arts = [e for e in entries if e.type == "article"]
    return {
        "n": len(entries),
        "recentes": (sum(y >= now - 5 for y in years) / len(entries)) if entries else 0.0,
        "doi": (sum(e.has("doi") for e in arts) / len(arts)) if arts else None,
        "periodicos": (len(arts) / len(entries)) if entries else 0.0,
    }


def _text(project: Any) -> str:
    if project is None:
        return ""
    return _norm(" ".join(p.text for p in project.paragraphs()))


def _metric(report: Report, checker: str, name: str) -> Any:
    for g in report.metrics:
        if g.checker == checker:
            for m in g.metrics:
                if m.name == name:
                    return m.value
    return None


def metas(report: Report, nivel: Nivel, project: Any, mono: bool) -> list[Meta]:
    out: list[Meta] = []
    st = _bib_stats(project)
    if st:
        alvo_refs = nivel.refs_mono if mono else nivel.refs_artigo
        out.append(
            Meta(
                "Referências citadas",
                f"≥ {alvo_refs}",
                str(st["n"]),
                st["n"] >= alvo_refs,
                "amplie a revisão de literatura com estudos recentes e de periódicos indexados",
            )
        )
        out.append(
            Meta(
                "Referências dos últimos 5 anos",
                f"≥ {nivel.recentes:.0%}",
                f"{st['recentes']:.0%}",
                st["recentes"] >= nivel.recentes,
                "atualize o referencial com trabalhos dos últimos 5 anos",
            )
        )
        out.append(
            Meta(
                "Referências que são artigos de periódico",
                f"≥ {nivel.periodicos:.0%}",
                f"{st['periodicos']:.0%}",
                st["periodicos"] >= nivel.periodicos,
                "prefira artigos revisados por pares a sites, relatórios e livros-texto",
            )
        )
        if st["doi"] is not None:
            out.append(
                Meta(
                    "Artigos de periódico com DOI",
                    f"≥ {nivel.doi:.0%}",
                    f"{st['doi']:.0%}",
                    st["doi"] >= nivel.doi,
                    "complete o campo doi no .bib (rode com --online para conferir)",
                )
            )
    if project is not None:
        words = sum(p.word_count() for p in project.paragraphs(("body", "item", "quote")))
        alvo_w = nivel.palavras_mono if mono else nivel.palavras_artigo
        out.append(
            Meta(
                "Extensão do texto (palavras)",
                f"≥ {alvo_w}",
                str(words),
                words >= alvo_w,
                "aprofunde método, resultados e discussão (sem encher: cada parágrafo com "
                "uma ideia nova)",
            )
        )
    sev = report.by_severity()
    out.append(
        Meta(
            "Erros",
            "0",
            str(sev[Severity.ERRO]),
            sev[Severity.ERRO] == 0,
            "resolva todos os itens P0",
        )
    )
    out.append(
        Meta(
            "Avisos",
            f"≤ {nivel.max_avisos}",
            str(sev[Severity.AVISO]),
            sev[Severity.AVISO] <= nivel.max_avisos,
            "resolva os itens P1",
        )
    )
    tot = _metric(report, "periodico", "TOTAL")
    if tot is not None:
        val = int(str(tot).split("/")[0])
        out.append(
            Meta(
                "Índice de prontidão (errei)",
                f"≥ {nivel.prontidao}",
                str(tot),
                val >= nivel.prontidao,
                "veja os componentes do índice no relatório (IMRaD, resumos, referências, "
                "tamanho, normas, escrita)",
            )
        )
    comp = _metric(report, "completude", "Obrigatórios presentes")
    if comp is not None:
        a, b = (int(x) for x in str(comp).split("/"))
        out.append(
            Meta(
                "Elementos obrigatórios (norma)",
                f"{b}/{b}",
                str(comp),
                a == b,
                "veja 'Completude do trabalho' abaixo",
            )
        )
    abstract = _metric(report, "completude", "Resumo em língua estrangeira")
    if abstract is not None and nivel.rigor >= 1:
        out.append(
            Meta(
                "Abstract (resumo em inglês)",
                "presente",
                str(abstract),
                abstract == "presente",
                "inclua abstract e keywords",
            )
        )
    texto = _text(project)
    if texto:
        for key in nivel.declaracoes:
            nome, rx, como = DECLARACOES[key]
            if key == "etica" and not HUMANOS.search(texto):
                continue  # só se a pesquisa envolve pessoas
            found = bool(re.search(rx, texto))
            if key in OPCIONAIS:
                # não é exigência: só informa (sem ❌ e sem virar item da lista)
                out.append(
                    Meta(
                        nome,
                        "opcional",
                        "presente" if found else "ausente",
                        True if found else None,
                        como,
                    )
                )
                continue
            out.append(Meta(nome, "presente", "presente" if found else "ausente", found, como))
    if not report.meta.get("online"):
        out.append(
            Meta(
                "Existência e atribuição das referências",
                "verificadas",
                "não verificadas (offline)",
                None,
                "rode `errei . --online` para conferir se as obras existem e sustentam as "
                "afirmações",
            )
        )
    return out


# ------------------------------------------------------------------ render
ID_RE = re.compile(r"<!-- errei:id=(\w+) \| (.*?) -->")


NIVEL_RE = re.compile(r"<!-- errei:todo nivel=(\w+) -->")


def previous_ids(path: Path, nivel: str | None = None) -> dict[str, str]:
    """Itens da lista anterior (id → título); vazio se for de outro nível."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}
    m = NIVEL_RE.search(text)
    if nivel is not None and (m is None or m.group(1) != nivel):
        return {}
    return {m.group(1): m.group(2) for m in ID_RE.finditer(text)}


def _md(s: str) -> str:
    return s.replace("\n", " ").replace("-->", "—>")


def build(report: Report, nivel_key: str = "a1", previous: dict[str, str] | None = None) -> str:
    nivel = NIVEIS.get(nivel_key, NIVEIS["a1"])
    project = getattr(report, "project", None)
    tipo_f = next((f for f in report.findings if f.code == "COMP-TIPO-001"), None)
    mono = bool(tipo_f and re.search(r"(monografia|tcc|dissertacao|tese)", tipo_f.message))
    tipo = "monografia" if mono else "artigo"
    items = items_from_findings(report, nivel)
    ms = metas(report, nivel, project, mono)
    for m in ms:
        if m.ok is False and m.nome not in ("Erros", "Avisos"):  # já são as listas P0/P1
            items.append(
                Item(
                    _hid("meta", m.nome),
                    "P1" if m.nome not in ("Erros",) else "P0",
                    AREA["metas"],
                    f"{m.nome}: {m.atual} (meta {m.alvo})",
                    [],
                    m.como,
                    [],
                    "META",
                )
            )
    items = [i for i in items if i.titulo]
    counts = {p: sum(i.prioridade == p for i in items) for p in ("P0", "P1", "P2")}
    meta = report.meta
    titulo = Path(str(meta.get("root", "."))).name
    md: list[str] = []
    md.append(f"# Lista de afazeres — {titulo}")
    md.append(f"<!-- errei:todo nivel={nivel.key} -->")
    md.append("")
    md.append(
        f"**Meta:** {nivel.nome} — {nivel.descricao}. **Tipo:** {tipo}. "
        f"Gerada pelo errei {meta.get('version', '')} em {str(meta.get('date', ''))[:10]}"
        f"{' (com verificação online)' if meta.get('online') else ' (offline)'}."
    )
    md.append("")
    md.append(
        f"**{counts['P0']}** itens P0 (bloqueiam a entrega) · **{counts['P1']}** P1 "
        f"(necessários para o nível) · **{counts['P2']}** P2 (aperfeiçoamento)."
    )
    md.append("")
    md.append(
        "> Como usar: resolva na ordem P0 → P1 → P2, marque `[x]` e rode o errei de novo com "
        "`--todo` sobre este arquivo: o que deixar de aparecer vai para *Resolvidos*. "
        "Escreva as correções com suas palavras; o errei não altera o trabalho. "
        "As metas são referências usuais do nível, não garantia de aprovação ou aceite."
    )
    md.append("")
    if previous:
        current = {i.id for i in items}
        resolved = [(k, v) for k, v in previous.items() if k not in current]
        if resolved:
            md.append(f"## ✅ Resolvidos desde a última lista ({len(resolved)})")
            md.append("")
            for _k, v in resolved:
                md.append(f"- [x] ~~{v}~~")
            md.append("")

    md.append("## Metas do nível")
    md.append("")
    md.append("| | meta | alvo | atual | como chegar lá |")
    md.append("|---|---|---|---|---|")
    for m in ms:
        icon = "✅" if m.ok else ("❌" if m.ok is False else ("ℹ️" if m.alvo == "opcional" else "⚠️"))
        md.append(f"| {icon} | {m.nome} | {m.alvo} | {m.atual} | {m.como} |")
    md.append("")

    nomes = {
        "P0": "P0 — Bloqueadores (resolva antes de entregar/submeter)",
        "P1": f"P1 — Necessário para o nível {nivel.nome}",
        "P2": "P2 — Aperfeiçoamento",
    }
    for pr in ("P0", "P1", "P2"):
        sel = [i for i in items if i.prioridade == pr]
        if not sel:
            continue
        md.append(f"## {nomes[pr]} ({len(sel)})")
        md.append("")
        by_area: dict[str, list[Item]] = defaultdict(list)
        for i in sel:
            by_area[i.area].append(i)
        for area in sorted(by_area, key=lambda a: AREA_ORDER.index(a) if a in AREA_ORDER else 99):
            md.append(f"### {area}")
            md.append("")
            for i in sorted(by_area[area], key=lambda x: (x.codigo, x.onde[:1])):
                where = f" — `{i.onde[0]}`" if len(i.onde) == 1 else ""
                code = f" · `{i.codigo}`" if i.codigo and i.codigo != "META" else ""
                md.append(f"- [ ] **{_md(i.titulo)}**{where}{code}")
                if i.como:
                    md.append(f"  - Como: {_md(i.como)}")
                if len(i.onde) > 1:
                    shown = ", ".join(f"`{w}`" for w in i.onde[:12])
                    more = f" e mais {len(i.onde) - 12}" if len(i.onde) > 12 else ""
                    md.append(f"  - Onde: {shown}{more}")
                for d in i.detalhe:
                    md.append(f"  - {_md(d)}")
                md.append(f"  <!-- errei:id={i.id} | {_md(i.titulo)[:160]} -->")
            md.append("")

    md.append("## Revisão humana (o errei não verifica)")
    md.append("")
    for t in nivel.manual:
        md.append(f"- [ ] {t}")
    md.append("")
    md.append("---")
    md.append("")
    md.append(
        "Detalhes de cada regra: `errei explain CODIGO`. Indícios de similaridade e de IA "
        "não são vereditos; veja as Limitações no relatório completo."
    )
    md.append("")
    from errei.report.render import base_markdown

    md += base_markdown(report.meta)
    return "\n".join(md)


def write(report: Report, path: Path, nivel: str = "a1") -> Path:
    if path.suffix.lower() in (".tex", ".bib", ".sty", ".cls"):
        raise ValueError(f"recusado: {path} parece um arquivo do trabalho (use um .md)")
    prev = previous_ids(path, nivel) if path.is_file() else None
    path.write_text(build(report, nivel, prev), encoding="utf-8")
    return path
