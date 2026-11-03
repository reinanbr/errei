"""Comparação do manuscrito com a referência empírica da área (offline).

Só roda com ``--referencia brasil|mundo`` e ``--area``. Lê os quantis instalados por
``errei referencia construir`` e mostra, por dimensão, o valor do manuscrito ao lado de
p10–p90 da referência, com n. Não há nota única: cada dimensão é um indicador.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

from errei.checkers.base import BaseChecker, RunContext
from errei.model import Finding, Metric, MetricGroup, Rule
from errei.model import Severity as S

if TYPE_CHECKING:
    from errei.project import Project

N_MIN = 30  # abaixo disso a referência é incerta
FREQ_COMUM = 0.6  # declaração presente em ≥ 60% da referência


def posicao(valor: float, q: dict[str, float]) -> str:
    if valor < q["p10"]:
        return "abaixo do p10"
    if valor < q["p25"]:
        return "entre p10 e p25"
    if valor <= q["p75"]:
        return "faixa central (p25–p75)"
    if valor <= q["p90"]:
        return "entre p75 e p90"
    return "acima do p90"


def _fmt(v: float, casas: int, unidade: str) -> str:
    s = f"{v:.{casas}f}".replace(".", ",")
    return s + ("%" if unidade == "%" else "")


class ReferenciaChecker(BaseChecker):
    name = "referencia"
    title = "Comparação com a referência da área"
    phase = 0
    rules = (
        Rule(
            "REF-AREA-001",
            S.INFO,
            "Referência da área não instalada",
            "Não há referência empírica instalada para a área/escopo pedidos; as metas da "
            "lista de afazeres continuam genéricas. Construa com 'errei referencia "
            "construir --area <slug> --escopo brasil|mundo' (requer rede).",
        ),
        Rule(
            "REF-AREA-002",
            S.INFO,
            "Referência com amostra pequena",
            f"Com menos de {N_MIN} obras medidas numa dimensão, os quantis são instáveis: "
            "use a comparação só como orientação.",
        ),
        Rule(
            "REF-AREA-003",
            S.AVISO,
            "Área desconhecida",
            "O --area informado não corresponde a nenhuma área com referência "
            "(veja 'errei referencia listar').",
        ),
        Rule(
            "REF-DIM-001",
            S.SUGESTAO,
            "Dimensão fora da faixa usual da área",
            "O valor do manuscrito está abaixo do p10 ou acima do p90 das obras mais citadas "
            "da área (ou a declaração aparece na maioria delas e falta aqui). É um contraste "
            "com o que é comum entre os trabalhos de alto impacto, não uma regra: verifique "
            "se faz sentido para o seu trabalho.",
            heuristic=True,
        ),
    )

    def run(self, project: Project, ctx: RunContext) -> list[Finding]:
        from errei.referencia import areas, medidas, store

        cfg = ctx.config
        escopo = str(cfg.get("referencia", "escopo", "") or "").strip().lower()
        if not escopo:
            return []
        nome_area = str(cfg.get("periodico", "area", "") or "")
        area = areas.resolve(nome_area)
        if area is None:
            return [
                self.finding(
                    "REF-AREA-003",
                    f"área '{nome_area or '(não informada)'}' sem referência; use --area com "
                    f"um de: {', '.join(areas.AREAS)}",
                )
            ]
        data = store.carregar(area.slug)
        esc = (data or {}).get("escopos", {}).get(escopo)
        if not esc:
            return [
                self.finding(
                    "REF-AREA-001",
                    f"referência '{area.slug}' ({escopo}) não instalada em {store.pasta()}",
                    suggestion=(
                        f"errei referencia construir --area {area.slug} --escopo {escopo} "
                        "(requer rede)"
                    ),
                )
            ]
        chave, grp = store.grupo(esc, "pt", N_MIN)
        usar_modelo = not bool(cfg.get("referencia", "sem_modelo", False))
        meu = medidas.medir_projeto(project, date.today().year, usar_modelo=usar_modelo)
        proc = esc.get("procedencia", {})
        out: list[Finding] = []
        g = MetricGroup(
            self.name,
            f"Comparação com a referência: {area.nome} ({escopo}; {chave.split('|')[1]}; "
            f"n={grp.get('n', 0)})",
        )
        pequenas: list[str] = []
        for m in medidas.MEDIDAS:
            ref = grp.get("medidas", {}).get(m.chave)
            v = meu.get(m.chave)
            if ref is None or v is None:
                continue
            n = int(ref["n"])
            if n < N_MIN:
                pequenas.append(f"{m.rotulo} (n={n})")
            if m.tipo == "bool":
                freq = float(ref["freq"])
                g.metrics.append(
                    Metric(
                        m.rotulo,
                        "presente" if v else "ausente",
                        None,
                        f"presente em {freq:.0%} das obras (n={n})",
                        m.nota,
                    )
                )
                if not v and freq >= FREQ_COMUM and n >= N_MIN:
                    out.append(
                        self.finding(
                            "REF-DIM-001",
                            f"{m.rotulo}: ausente aqui e presente em {freq:.0%} das obras "
                            f"mais citadas da área (n={n})",
                            suggestion="veja se o periódico-alvo pede essa declaração",
                            confidence=0.6,
                        )
                    )
                continue
            fv = float(v)
            pos = posicao(fv, ref)
            faixa = (
                f"p10–p90: {_fmt(ref['p10'], m.casas, m.unidade)}–"
                f"{_fmt(ref['p90'], m.casas, m.unidade)} · mediana "
                f"{_fmt(ref['p50'], m.casas, m.unidade)} (n={n})"
            )
            g.metrics.append(
                Metric(
                    m.rotulo,
                    _fmt(fv, m.casas, m.unidade),
                    None,
                    faixa,
                    pos + (f"; {m.nota}" if m.nota else ""),
                )
            )
            if pos in ("abaixo do p10", "acima do p90") and n >= N_MIN:
                out.append(
                    self.finding(
                        "REF-DIM-001",
                        f"{m.rotulo}: {_fmt(fv, m.casas, m.unidade)}, {pos} das obras mais "
                        f"citadas da área ({faixa})",
                        suggestion="compare com 2–3 artigos de referência do periódico-alvo",
                        confidence=0.5,
                        evidence=(m.nota,) if m.nota else (),
                    )
                )
        g.notes.append(
            f"Referência: {proc.get('criterio', '')}; {proc.get('obras_na_populacao', '?')} obras "
            f"na população, amostra de {proc.get('amostra', {}).get('n', '?')} "
            f"({proc.get('amostra', {}).get('anos', '')}), "
            f"{proc.get('com_texto_completo', 0)} com texto completo; consultado em "
            f"{proc.get('consultado_em', '?')} ({proc.get('fonte', '')})."
        )
        g.notes.append(
            "Sem nota única: cada linha compara uma dimensão com os quantis das obras de alto "
            "impacto. Estar fora da faixa não é erro; estar dentro não garante aceite."
        )
        if pequenas:
            out.append(
                self.finding(
                    "REF-AREA-002",
                    "amostra pequena em: " + "; ".join(pequenas[:6]),
                )
            )
        ctx.add_metrics(g)
        ctx.extra_meta["referencia"] = {
            "area": area.slug,
            "escopo": escopo,
            "grupo": chave,
            "n": grp.get("n", 0),
            "consultado_em": proc.get("consultado_em"),
            "manuscrito": {k: v for k, v in meu.items() if not k.startswith("_")},
        }
        return out


def resumo_procedencia(esc: dict[str, Any]) -> str:
    p = esc.get("procedencia", {})
    return (
        f"n={p.get('amostra', {}).get('n', '?')} de {p.get('obras_na_populacao', '?')}, "
        f"{p.get('com_texto_completo', 0)} com texto, consultado em {p.get('consultado_em')}"
    )
