"""Nível de qualidade atingido pelo trabalho (TCC → Mestrado → Doutorado → Excelência).

Reaproveita as metas de cada nível da lista de afazeres (``report/todo.py``): o trabalho
atinge um nível quando cumpre todas as metas medidas dele e dos níveis anteriores. Para
cada nível, informa quantas metas foram cumpridas e quais faltam.

É uma referência para orientar a revisão, calculada só com sinais objetivos do
manuscrito: não prevê aprovação, aceite nem estrato Qualis.
"""

from __future__ import annotations

import re
from typing import Any

from errei.report.build import Report

ORDEM = ("tcc", "mestrado", "doutorado", "a1")


def _mono(report: Report) -> bool:
    tipo_f = next((f for f in report.findings if f.code == "COMP-TIPO-001"), None)
    return bool(tipo_f and re.search(r"(monografia|tcc|dissertacao|tese)", tipo_f.message))


def avaliar(report: Report) -> dict[str, Any]:
    """Resumo do nível atingido (vai para ``meta.qualidade`` no JSON)."""
    from errei.report.todo import NIVEIS, metas

    project = getattr(report, "project", None)
    mono = _mono(report)
    niveis: list[dict[str, Any]] = []
    atingido: str | None = None
    continua = True
    for key in ORDEM:
        nivel = NIVEIS[key]
        medidas = [m for m in metas(report, nivel, project, mono) if m.ok is not None]
        medidas = [m for m in medidas if m.alvo != "opcional"]
        ok = [m for m in medidas if m.ok]
        faltam = [f"{m.nome}: {m.atual} (meta {m.alvo})" for m in medidas if not m.ok]
        cumpre = not faltam
        if continua and cumpre:
            atingido = key
        else:
            continua = False
        niveis.append(
            {
                "nivel": key,
                "nome": nivel.nome,
                "cumpridas": len(ok),
                "total": len(medidas),
                "pct": round(100 * len(ok) / len(medidas)) if medidas else 0,
                "atingido": False,  # preenchido abaixo
                "faltam": faltam,
            }
        )
    idx = ORDEM.index(atingido) if atingido else -1
    for i, n in enumerate(niveis):
        n["atingido"] = i <= idx
    proximo = niveis[idx + 1] if idx + 1 < len(niveis) else None
    return {
        "nivel": atingido,
        "nome": NIVEIS[atingido].nome if atingido else "abaixo do nível TCC",
        "proximo": proximo["nivel"] if proximo else None,
        "faltam_proximo": proximo["faltam"] if proximo else [],
        "niveis": niveis,
        "offline": not report.meta.get("online"),
        "nota": "referência calculada por metas objetivas; não prevê aprovação nem aceite",
    }


def get(report: Report) -> dict[str, Any] | None:
    q = report.meta.get("qualidade")
    return q if isinstance(q, dict) else None


def barra(pct: int, largura: int = 20) -> str:
    cheio = round(largura * pct / 100)
    return "█" * cheio + "░" * (largura - cheio)


def linhas_texto(q: dict[str, Any]) -> list[str]:
    """Texto curto usado na tela, no Markdown e no PDF."""
    out = [f"Nível atingido: {q['nome']}"]
    for n in q["niveis"]:
        mark = "✔" if n["atingido"] else "·"
        out.append(f"{mark} {n['nome']}: {n['cumpridas']}/{n['total']} metas ({n['pct']}%)")
    if q.get("proximo"):
        prox = next(n for n in q["niveis"] if n["nivel"] == q["proximo"])
        out.append(f"Para chegar a {prox['nome']}, falta: " + "; ".join(q["faltam_proximo"][:6]))
        if len(q["faltam_proximo"]) > 6:
            out[-1] += f" e mais {len(q['faltam_proximo']) - 6}"
    return out


def markdown(q: dict[str, Any], alvo: str | None = None) -> list[str]:
    md = ["## Nível de qualidade do trabalho", ""]
    md.append(f"**Nível atingido: {q['nome']}**")
    md.append("")
    md.append("| | nível | metas cumpridas | progresso |")
    md.append("|---|---|---:|---|")
    for n in q["niveis"]:
        icon = "✅" if n["atingido"] else ("🎯" if n["nivel"] == alvo else "⬜")
        md.append(
            f"| {icon} | {n['nome']} | {n['cumpridas']}/{n['total']} | "
            f"`{barra(n['pct'])}` {n['pct']}% |"
        )
    md.append("")
    if q.get("proximo"):
        prox = next(n for n in q["niveis"] if n["nivel"] == q["proximo"])
        md.append(f"Para chegar a **{prox['nome']}**, falta:")
        md.append("")
        for f in q["faltam_proximo"]:
            md.append(f"- {f}")
        md.append("")
    extra = " Rode com `--online` para conferir as referências." if q.get("offline") else ""
    md.append(
        "> O nível é atingido quando todas as metas medidas dele e dos anteriores são "
        f"cumpridas. É uma referência objetiva, não prevê aprovação nem aceite.{extra}"
    )
    md.append("")
    return md
