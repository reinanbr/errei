"""Verificador ``ptbr``: ortografia, gramática e estilo em português do Brasil."""

from __future__ import annotations

import re
import shutil
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from errei.checkers.base import BaseChecker, RunContext
from errei.latex.extract import Paragraph
from errei.model import Finding, Rule
from errei.model import Severity as S
from errei.text import languagetool as lt
from errei.text.segment import STOPWORDS, alpha_words, load_table, sentences, words

if TYPE_CHECKING:
    from errei.project import Project

CHECK_KINDS = ("body", "item", "abstract", "caption")
_I = re.IGNORECASE

# --- crase --------------------------------------------------------------
CRASE_A_PARTIR = re.compile(r"\bà\s+partir\b", _I)
CRASE_PRONOUNS = re.compile(
    r"\bà\s+(ela|elas|ele|eles|você|vocês|esta|este|estes|estas|essa|esse|esses|essas|"
    r"cada|todos|todas|todo|toda|quem|nenhum|nenhuma|alguém|ninguém|um|uns)\b",
    _I,
)
CRASE_DEMONSTR = re.compile(r"\bà\s+(aquel[ea]s?|aquilo)\b", _I)
CRASE_BEFORE = re.compile(r"\bà\s+([^\W\d_]+)", _I)
CRASE_PLURAL_EXCEPT = {
    "íris",
    "cútis",
    "pelvis",
    "pélvis",
    "tênis",
    "atlas",
    "lápis",
    "vírus",
    "bônus",
    "ônus",
    "pires",
    "tórax",
    "fênix",
    "crise",
    "tese",
    "análise",
    "base",
    "síntese",
    "hipótese",
    "classe",
    "fase",
    "frase",
}
CRASE_VERB_EXCEPT = {"mulher", "colher", "par", "mar", "lar", "bar", "dor", "flor", "cor", "valer"}
CRASE_MISSING = [
    (re.compile(r"(?<![\wà])a\s+medida\s+que\b", _I), "à medida que"),
    (re.compile(r"(?<![\wà])a\s+procura\s+de\b", _I), "à procura de"),
    (re.compile(r"(?<![\wà])a\s+beira\s+de\b", _I), "à beira de"),
    (re.compile(r"(?<![\wà])a\s+custa\s+de\b", _I), "à custa de"),
    (re.compile(r"(?<![\wà])a\s+mercê\s+de\b", _I), "à mercê de"),
    (re.compile(r"(?<![\wà])a\s+luz\s+d[aeo]s?\b", _I), "à luz de"),
    (re.compile(r"(?<![\wà])a\s+exceção\s+d[aeo]s?\b", _I), "à exceção de"),
    (re.compile(r"(?<![\wà])a\s+semelhança\s+d[aeo]s?\b", _I), "à semelhança de"),
    (re.compile(r"(?<![\wàá])as\s+vezes\b(?!\s+(?:em|que)\b)", _I), "às vezes"),
]

# --- concordância -------------------------------------------------------
CONC = [
    (re.compile(r"\bhouveram\b(?!-se)", _I), "'haver' (existir) é impessoal", "houve"),
    (
        re.compile(
            r"\bfazem\s+(?:\d+|dois|duas|três|quatro|cinco|muitos|vários|alguns)\s+"
            r"(?:anos|meses|dias|semanas|décadas|séculos)\b",
            _I,
        ),
        "'fazer' indicando tempo decorrido é impessoal",
        "faz",
    ),
    (re.compile(r"\bmenas\b", _I), "'menos' é invariável", "menos"),
    (re.compile(r"\btratam-se\s+de\b", _I), "'tratar-se de' fica no singular", "trata-se de"),
    (
        re.compile(r"\bprecisam-se\s+de\b", _I),
        "índice de indeterminação: verbo no singular",
        "precisa-se de",
    ),
]

# --- voz passiva / pessoa ----------------------------------------------
PASSIVE = re.compile(
    r"\b(?:é|são|foi|foram|será|serão|seria|seriam|era|eram|sendo|sido|ser)\s+"
    r"(?:\w+mente\s+)?[^\W\d_]{3,}(?:ado|ada|ados|adas|ido|ida|idos|idas|ito|ita|itos|itas|"
    r"osto|osta|ostos|ostas|eito|eita|eitos|eitas)\b",
    _I,
)
FIRST_SINGULAR = re.compile(r"\b(eu|meu|minha|meus|minhas|comigo)\b", _I)


@cache
def _tables() -> dict[str, list[tuple[re.Pattern[str], str, str]]]:
    def tsv(name: str, kind: str) -> list[tuple[re.Pattern[str], str, str]]:
        rows = []
        for row in load_table(name):
            if kind == "word":
                if len(row) >= 2:
                    rows.append(
                        (
                            re.compile(r"(?<![\w-])" + re.escape(row[0]) + r"(?![\w-])", _I),
                            row[0],
                            row[1],
                        )
                    )
            elif len(row) >= 3:
                rows.append((re.compile(row[0], _I), row[1], row[2]))
        return rows

    return {
        "orto": tsv("grafia_pre1990.tsv", "word"),
        "angl": tsv("anglicismos.tsv", "word"),
        "vicio": tsv("vicios.tsv", "regex"),
        "reg": tsv("regencia.tsv", "regex"),
    }


@dataclass(slots=True)
class _Hit:
    code: str
    start: int
    end: int
    message: str
    suggestion: str | None
    evidence: tuple[str, ...] = ()


def _in_italic(src_text: str, offset: int) -> bool:
    """O offset está dentro de \\emph{}/\\textit{} (estrangeirismo marcado)?"""
    window = src_text[max(0, offset - 300) : offset]
    depth = 0
    for i in range(len(window) - 1, -1, -1):
        c = window[i]
        if c == "}":
            depth += 1
        elif c == "{":
            if depth == 0:
                return bool(
                    re.search(
                        r"\\(?:emph|textit|textsl|foreignlanguage\{[^}]*\}|"
                        r"foreign\w*)\s*$",
                        window[:i],
                    )
                )
            depth -= 1
    return False


class PtbrChecker(BaseChecker):
    name = "ptbr"
    title = "Ortografia, gramática e estilo (pt-BR)"
    rules = (
        Rule(
            "PTBR-LT-001",
            S.AVISO,
            "Gramática (LanguageTool)",
            "Problema gramatical apontado pelo LanguageTool local. O código original da "
            "regra do LanguageTool aparece em 'motivo'.",
        ),
        Rule(
            "PTBR-LT-002",
            S.AVISO,
            "Ortografia (LanguageTool)",
            "Palavra não reconhecida pelo dicionário pt-BR do LanguageTool. Termos técnicos "
            "podem ser incluídos em .errei-dict.txt.",
        ),
        Rule(
            "PTBR-LT-003",
            S.SUGESTAO,
            "Estilo/tipografia (LanguageTool)",
            "Sugestão de estilo ou tipografia do LanguageTool.",
        ),
        Rule(
            "PTBR-SPELL-001",
            S.SUGESTAO,
            "Possível erro de ortografia",
            "Palavra ausente do dicionário de fallback (hunspell pt_BR ou pyspellchecker). "
            "Menos preciso que o LanguageTool; confira.",
            heuristic=True,
        ),
        Rule(
            "PTBR-ORTO-001",
            S.AVISO,
            "Grafia anterior ao Acordo Ortográfico",
            "Grafia abolida pelo Acordo Ortográfico de 1990 (obrigatório no Brasil desde "
            "2016): trema, acento em ditongos abertos de paroxítonas, 'vôo', hífen em "
            "prefixos etc.",
            "Acordo Ortográfico da Língua Portuguesa (1990)",
        ),
        Rule(
            "PTBR-ANGL-001",
            S.SUGESTAO,
            "Anglicismo",
            "Estrangeirismo com equivalente em português. Se for termo técnico consagrado, "
            "mantenha em itálico (\\emph{}) ou adicione ao .errei-dict.txt.",
            heuristic=True,
        ),
        Rule(
            "PTBR-CRASE-001",
            S.ERRO,
            "Crase indevida",
            "Não há crase antes de palavra masculina, verbo, pronome pessoal, indefinido ou "
            "demonstrativo (esta/essa), de 'cada', 'todos' e de palavras no plural quando o "
            "'a' está no singular.",
        ),
        Rule(
            "PTBR-CRASE-002",
            S.AVISO,
            "Crase ausente em locução",
            "Locuções adverbiais/prepositivas femininas levam crase: à medida que, às vezes, "
            "à luz de, à exceção de…",
            heuristic=True,
        ),
        Rule(
            "PTBR-CRASE-003",
            S.ERRO,
            "Crase com demonstrativo",
            "Antes de aquele/aquela/aquilo, a preposição 'a' se funde: àquele, àquela, àquilo.",
        ),
        Rule(
            "PTBR-REG-001",
            S.SUGESTAO,
            "Regência verbal",
            "Regência que a norma culta considera inadequada em textos acadêmicos.",
            heuristic=True,
        ),
        Rule(
            "PTBR-CONC-001",
            S.ERRO,
            "Concordância",
            "Erro de concordância de padrão inequívoco (p.ex. 'houveram', 'fazem dois anos').",
        ),
        Rule(
            "PTBR-PASSIVA-001",
            S.SUGESTAO,
            "Voz passiva excessiva",
            "Parágrafo com muitas construções na voz passiva analítica; a voz ativa costuma "
            "ser mais clara.",
            heuristic=True,
        ),
        Rule(
            "PTBR-PESSOA-001",
            S.SUGESTAO,
            "Primeira pessoa do singular",
            "A primeira pessoa do singular é pouco usual em artigos científicos em português "
            "(prefira impessoal ou 1ª do plural, conforme a área).",
            heuristic=True,
        ),
        Rule(
            "PTBR-PARAG-001",
            S.SUGESTAO,
            "Parágrafo longo",
            "Parágrafo muito extenso; considere dividi-lo (limite configurável).",
        ),
        Rule(
            "PTBR-FRASE-001",
            S.SUGESTAO,
            "Frase longa",
            "Frase com mais palavras que o limite configurado (padrão 40). Frases longas "
            "dificultam a leitura.",
        ),
        Rule(
            "PTBR-REPET-001",
            S.SUGESTAO,
            "Repetição de palavra",
            "A mesma palavra aparece várias vezes em um trecho curto.",
            heuristic=True,
        ),
        Rule(
            "PTBR-VICIO-001",
            S.SUGESTAO,
            "Vício de linguagem acadêmica",
            "Expressão vaga, coloquial ou desaconselhada em textos acadêmicos.",
        ),
    )

    def run(self, project: Project, ctx: RunContext) -> list[Finding]:
        cfg = ctx.config.section("ptbr")
        user_dict = self._user_dict(project, cfg)
        paragraphs = [p for p in project.paragraphs(CHECK_KINDS) if p.lang == "pt"]
        out: list[Finding] = []
        own: dict[int, list[_Hit]] = defaultdict(list)
        for p in paragraphs:
            hits = self._own_rules(p, cfg, user_dict)
            own[id(p)] = hits
            out += [self._to_finding(p, h) for h in hits]

        use_lt = bool(cfg.get("languagetool", True))
        reason = lt.unavailable_reason() if use_lt else "desativado em [ptbr].languagetool"
        if reason is None:
            try:
                out += self._languagetool(paragraphs, own, user_dict)
            except RuntimeError as exc:
                reason = str(exc)
        if reason is not None and cfg.get("spellcheck", True):
            if use_lt:
                out.append(
                    self.finding(
                        "CORE-DEP-001",
                        f"gramática via LanguageTool pulada: "
                        f"{reason}; usando só regras próprias e ortografia "
                        "básica",
                    )
                )
            out += self._spell_fallback(paragraphs, user_dict, project)
        return out

    # ------------------------------------------------------------ util
    def _user_dict(self, project: Project, cfg: dict[str, Any]) -> set[str]:
        words_set: set[str] = set()
        path = project.root / str(cfg.get("dict", ".errei-dict.txt"))
        try:
            if path.is_file() and path.resolve().is_relative_to(project.root):
                for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[:50000]:
                    w = line.strip()
                    if w and not w.startswith("#"):
                        words_set.add(w.lower())
        except OSError:
            pass
        for e in project.bib_entries:
            for f in ("author", "editor"):
                for w in re.findall(r"[^\W\d_]+", e.get(f)):
                    words_set.add(w.lower())
        return words_set

    def _to_finding(self, p: Paragraph, h: _Hit) -> Finding:
        return self.finding(
            h.code,
            h.message,
            location=p.location(h.start, h.end),
            excerpt=_context(p.text, h.start, h.end),
            suggestion=h.suggestion,
            evidence=h.evidence,
        )

    # ------------------------------------------------------------ regras próprias
    def _own_rules(self, p: Paragraph, cfg: dict[str, Any], user_dict: set[str]) -> list[_Hit]:
        text = p.text
        hits: list[_Hit] = []
        t = _tables()
        for rx, _wrong, right in t["orto"]:
            for m in rx.finditer(text):
                hits.append(
                    _Hit(
                        "PTBR-ORTO-001",
                        m.start(),
                        m.end(),
                        f"'{m.group(0)}' é grafia anterior ao Acordo de 1990",
                        _match_case(m.group(0), right),
                    )
                )
        for rx, word, sugg in t["angl"]:
            for m in rx.finditer(text):
                if word.lower() in user_dict or _in_italic(p.source.text, p.src(m.start())):
                    continue
                hits.append(
                    _Hit("PTBR-ANGL-001", m.start(), m.end(), f"anglicismo '{m.group(0)}'", sugg)
                )
        hits += self._crase(text)
        for rx, msg, sugg in t["reg"]:
            for m in rx.finditer(text):
                hits.append(_Hit("PTBR-REG-001", m.start(), m.end(), msg, sugg))
        for rx, msg, sugg in CONC:
            for m in rx.finditer(text):
                hits.append(
                    _Hit("PTBR-CONC-001", m.start(), m.end(), f"{msg}: '{m.group(0)}'", sugg)
                )
        for rx, msg, sugg in t["vicio"]:
            for m in rx.finditer(text):
                hits.append(
                    _Hit("PTBR-VICIO-001", m.start(), m.end(), f"{msg}: '{m.group(0)}'", sugg)
                )
        if p.kind != "caption":
            for m in FIRST_SINGULAR.finditer(text):
                hits.append(
                    _Hit(
                        "PTBR-PESSOA-001",
                        m.start(),
                        m.end(),
                        f"primeira pessoa do singular ('{m.group(0)}')",
                        "prefira construção impessoal ou 1ª pessoa do plural",
                    )
                )
        hits += self._lengths(p, cfg)
        hits += self._passive(text)
        hits += self._repetition(text, cfg, user_dict)
        return _dedupe(hits)

    def _crase(self, text: str) -> list[_Hit]:
        hits: list[_Hit] = []
        taken: set[int] = set()
        for m in CRASE_A_PARTIR.finditer(text):
            hits.append(
                _Hit(
                    "PTBR-CRASE-001",
                    m.start(),
                    m.end(),
                    "crase indevida em 'à partir' (verbo)",
                    "a partir",
                )
            )
            taken.add(m.start())
        for m in CRASE_DEMONSTR.finditer(text):
            fused = "à" + m.group(1)
            fused = "àquilo" if m.group(1).lower() == "aquilo" else "àq" + m.group(1)[2:]
            hits.append(
                _Hit(
                    "PTBR-CRASE-003",
                    m.start(),
                    m.end(),
                    f"'à {m.group(1)}' → contração com o demonstrativo",
                    fused,
                )
            )
            taken.add(m.start())
        for m in CRASE_PRONOUNS.finditer(text):
            if m.start() in taken:
                continue
            hits.append(
                _Hit(
                    "PTBR-CRASE-001",
                    m.start(),
                    m.end(),
                    f"crase indevida antes de '{m.group(1)}'",
                    f"a {m.group(1)}",
                )
            )
            taken.add(m.start())
        for m in CRASE_BEFORE.finditer(text):
            if m.start() in taken:
                continue
            w = m.group(1)
            wl = w.lower()
            if (
                wl.endswith(("os", "es", "is", "us"))
                and len(wl) > 3
                and wl not in CRASE_PLURAL_EXCEPT
            ):
                hits.append(
                    _Hit(
                        "PTBR-CRASE-001",
                        m.start(),
                        m.end(),
                        f"crase indevida: 'à' (singular) antes de '{w}' (plural)",
                        f"a {w}",
                    )
                )
            elif wl.endswith("as") and len(wl) > 3 and wl not in CRASE_PLURAL_EXCEPT:
                hits.append(
                    _Hit(
                        "PTBR-CRASE-001",
                        m.start(),
                        m.end(),
                        f"'à {w}': artigo no singular antes de palavra no plural",
                        f"às {w}",
                    )
                )
            elif re.fullmatch(r"[^\W\d_]{3,}(?:ar|er|ir)", wl) and wl not in CRASE_VERB_EXCEPT:
                hits.append(
                    _Hit(
                        "PTBR-CRASE-001",
                        m.start(),
                        m.end(),
                        f"crase indevida antes do verbo '{w}'",
                        f"a {w}",
                    )
                )
        for rx, right in CRASE_MISSING:
            for m in rx.finditer(text):
                hits.append(
                    _Hit(
                        "PTBR-CRASE-002",
                        m.start(),
                        m.end(),
                        f"falta crase em '{m.group(0)}'",
                        _match_case(m.group(0), right),
                    )
                )
        return hits

    def _lengths(self, p: Paragraph, cfg: dict[str, Any]) -> list[_Hit]:
        hits: list[_Hit] = []
        max_s = int(cfg.get("max_sentence_words", 40))
        max_p = int(cfg.get("max_paragraph_words", 200))
        n = len(words(p.text))
        if n > max_p and p.kind in ("body", "abstract"):
            hits.append(
                _Hit(
                    "PTBR-PARAG-001",
                    0,
                    min(len(p.text), 40),
                    f"parágrafo com {n} palavras (limite {max_p})",
                    "divida em parágrafos com uma ideia central cada",
                )
            )
        for s in sentences(p.text):
            k = len(words(s.text))
            if k > max_s:
                hits.append(
                    _Hit(
                        "PTBR-FRASE-001",
                        s.start,
                        s.end,
                        f"frase com {k} palavras (limite {max_s})",
                        "divida em frases menores",
                    )
                )
        return hits

    def _passive(self, text: str) -> list[_Hit]:
        ms = list(PASSIVE.finditer(text))
        n = len(words(text))
        if len(ms) >= 3 and n and len(ms) / n * 100 >= 4:
            first = ms[0]
            return [
                _Hit(
                    "PTBR-PASSIVA-001",
                    first.start(),
                    first.end(),
                    f"{len(ms)} construções na voz passiva em {n} palavras",
                    "prefira a voz ativa onde possível",
                    tuple(m.group(0) for m in ms[:5]),
                )
            ]
        return []

    def _repetition(self, text: str, cfg: dict[str, Any], user_dict: set[str]) -> list[_Hit]:
        window = int(cfg.get("repeat_window", 30))
        toks = [w for w in alpha_words(text)]
        hits: list[_Hit] = []
        reported: set[str] = set()
        for i, w in enumerate(toks):
            lw = w.text.lower()
            if (
                len(lw) < 5
                or lw in STOPWORDS
                or lw in reported
                or lw in user_dict
                or w.text[:1].isupper()
            ):
                continue
            same = [t for t in toks[i : i + window] if t.text.lower() == lw]
            if len(same) >= 3:
                reported.add(lw)
                hits.append(
                    _Hit(
                        "PTBR-REPET-001",
                        same[1].start,
                        same[1].end,
                        f"'{w.text}' repetida {len(same)}× em {window} palavras",
                        "use sinônimo, pronome ou reestruture",
                    )
                )
        return hits

    # ------------------------------------------------------------ LanguageTool
    def _languagetool(
        self, paragraphs: list[Paragraph], own: dict[int, list[_Hit]], user_dict: set[str]
    ) -> list[Finding]:
        out: list[Finding] = []
        for p in paragraphs:
            text = p.text.replace("\n", " ")
            for m in lt.check(text):
                start, end = m.offset, m.offset + m.length
                if any(h.start < end and start < h.end for h in own[id(p)]):
                    continue  # regra própria já cobre
                word = text[start:end]
                is_spell = (
                    m.issue_type == "misspelling"
                    or "MORFOLOGIK" in m.rule_id
                    or ("SPELL" in m.rule_id)
                )
                if is_spell and (
                    word.lower() in user_dict
                    or word.isupper()
                    or word.lower() in LATIN
                    or _looks_placeholder(word)
                ):
                    continue
                if is_spell:
                    code = "PTBR-LT-002"
                elif m.issue_type in ("style", "typographical", "whitespace", "locale-violation"):
                    code = "PTBR-LT-003"
                else:
                    code = "PTBR-LT-001"
                sugg = " | ".join(m.replacements) if m.replacements else None
                out.append(
                    self.finding(
                        code,
                        m.message,
                        location=p.location(start, end),
                        excerpt=_context(p.text, start, end),
                        suggestion=sugg,
                        evidence=(f"LanguageTool: {m.rule_id}",),
                    )
                )
        return out

    # ------------------------------------------------------------ ortografia fallback
    def _spell_fallback(
        self, paragraphs: list[Paragraph], user_dict: set[str], project: Project
    ) -> list[Finding]:
        candidates: dict[str, list[tuple[Paragraph, int, int]]] = defaultdict(list)
        for p in paragraphs:
            for w in alpha_words(p.text):
                t = w.text
                if (
                    len(t) < 3
                    or t[:1].isupper()
                    or t.lower() in user_dict
                    or _looks_placeholder(t)
                    or t.lower() in _orto_words()
                ):
                    continue
                candidates[t.lower()].append((p, w.start, w.end))
        if not candidates:
            return []
        unknown = _unknown_words(sorted(candidates))
        if unknown is None:
            return [
                self.finding(
                    "CORE-DEP-001",
                    "ortografia pulada: instale 'errei[ptbr]' (pyspellchecker) ou hunspell-pt-br",
                )
            ]
        out: list[Finding] = []
        for word in sorted(unknown):
            occ = candidates[word]
            p, s, e = occ[0]
            extra = f" ({len(occ)} ocorrências)" if len(occ) > 1 else ""
            out.append(
                self.finding(
                    "PTBR-SPELL-001",
                    f"'{p.text[s:e]}' não reconhecida{extra}",
                    location=p.location(s, e),
                    excerpt=_context(p.text, s, e),
                    suggestion="corrija ou adicione ao .errei-dict.txt",
                )
            )
        return out


def _unknown_words(ws: list[str]) -> set[str] | None:
    hs = shutil.which("hunspell")
    if hs and any(
        Path(d, "pt_BR.dic").is_file() for d in ("/usr/share/hunspell", "/usr/share/myspell")
    ):
        try:
            res = subprocess.run(
                [hs, "-d", "pt_BR", "-l"],
                input="\n".join(ws),
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            if res.returncode == 0:
                return {w.strip().lower() for w in res.stdout.splitlines() if w.strip()}
        except (OSError, subprocess.TimeoutExpired):
            pass
    try:
        from spellchecker import SpellChecker
    except ModuleNotFoundError:
        return None
    del SpellChecker
    sc = _spell("pt")
    return {w for w in sc.unknown(ws) if not _ok_variant(sc, w)}


@cache
def _spell(lang: str) -> Any:
    from spellchecker import SpellChecker

    return SpellChecker(language=lang, distance=1)


LATIN = {
    "apud",
    "et",
    "al",
    "ibidem",
    "idem",
    "passim",
    "sic",
    "op",
    "cit",
    "in",
    "vs",
    "versus",
    "via",
    "status",
    "quo",
    "priori",
    "posteriori",
    "per",
    "capita",
    "lato",
    "stricto",
    "sensu",
    "online",
    "software",
    "hardware",
    "corpus",
    "corpora",
}

# pt-BR → pt-PT (o dicionário de fallback é majoritariamente europeu)
_BR_PT = (
    ("ê", "é"),
    ("ô", "ó"),
    ("eção", "ecção"),
    ("ação", "acção"),
    ("ato", "acto"),
    ("ata", "acta"),
    ("ótim", "óptim"),
    ("eto", "ecto"),
    ("eta", "ecta"),
    ("tor", "ctor"),
    ("tora", "ctora"),
    ("ção", "pção"),
)


def _ok_variant(sc: Any, w: str) -> bool:
    """Aceita flexões simples, compostos e variantes pt-BR que o dicionário não lista."""
    if w in LATIN:
        return True
    if "-" in w:
        parts = [x for x in w.split("-") if x]
        return all(
            x in sc or x in {"se", "lo", "la", "los", "las", "lhe", "lhes"} or _ok_variant(sc, x)
            for x in parts
        )
    for br, pt in _BR_PT:
        if br in w and w.replace(br, pt) in sc:
            return True
    for suf, rep in (
        ("s", ""),
        ("es", ""),
        ("mente", ""),
        ("ção", "r"),
        ("ções", "r"),
        ("idade", "o"),
        ("ados", "ar"),
        ("adas", "ar"),
        ("ado", "ar"),
        ("ada", "ar"),
        ("idos", "er"),
        ("ido", "er"),
        ("ida", "er"),
    ):
        if w.endswith(suf) and len(w) > len(suf) + 3:
            base = w[: -len(suf)] + rep
            if base in sc:
                return True
    return False


@cache
def _orto_words() -> frozenset[str]:
    return frozenset(r[0].lower() for r in load_table("grafia_pre1990.tsv"))


def _looks_placeholder(t: str) -> bool:
    return t.lower() in {"silva", "souza", "x"} or any(c.isdigit() for c in t)


def _match_case(src: str, right: str) -> str:
    return right[:1].upper() + right[1:] if src[:1].isupper() else right


def _context(text: str, start: int, end: int, pad: int = 30) -> str:
    a = max(0, start - pad)
    b = min(len(text), end + pad)
    pre = "…" if a > 0 else ""
    post = "…" if b < len(text) else ""
    return pre + " ".join(text[a:b].split()) + post


def _dedupe(hits: list[_Hit]) -> list[_Hit]:
    """Remove achados idênticos (mesmo código e intervalo)."""
    seen: set[tuple[str, int, int]] = set()
    out = []
    for h in sorted(hits, key=lambda h: (h.start, h.code)):
        k = (h.code, h.start, h.end)
        if k not in seen:
            seen.add(k)
            out.append(h)
    return out
