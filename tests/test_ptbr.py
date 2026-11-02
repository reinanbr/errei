from __future__ import annotations

import os
import socket
from pathlib import Path

import pytest

from helpers import audit, by_code, codes, make_project


def run_pt(tmp: Path, body: str, extra: dict[str, str] | None = None, **cfg: object):  # type: ignore[no-untyped-def]
    files = {
        "main.tex": "\\documentclass[brazil]{abntex2}\n\\begin{document}\n"
        + body
        + "\n\\end{document}\n"
    }
    files.update(extra or {})
    over: dict[str, object] = {"checkers": {"only": ["ptbr"]}}
    if cfg:
        over["ptbr"] = cfg
    return audit(make_project(tmp, files), **over).findings


def msgs(f, code):  # type: ignore[no-untyped-def]
    return [x.message for x in by_code(f, code)]


def test_crase(tmp_path: Path) -> None:
    body = (
        "Devido à fatores externos, à partir de hoje, referente à ela e à cada um. "
        "Fomos à aquela reunião. Volto à vezes. Começou à fazer. "
        "Isso ocorre a medida que cresce. Fui à escola e à praia."
    )
    f = run_pt(tmp_path, body)
    m = msgs(f, "PTBR-CRASE-001")
    assert any("fatores" in x for x in m)
    assert any("à partir" in x for x in m)
    assert any("'ela'" in x for x in m) and any("'cada'" in x for x in m)
    assert any("'vezes'" in x for x in m) and any("fazer" in x for x in m)
    assert by_code(f, "PTBR-CRASE-003")[0].suggestion == "àquela"
    assert by_code(f, "PTBR-CRASE-002")[0].suggestion == "à medida que"
    assert not any("escola" in x or "praia" in x for x in m)  # crase correta


def test_location_maps_to_source_line(tmp_path: Path) -> None:
    f = run_pt(tmp_path, "Primeira linha correta.\nSegunda linha com idéia antiga.")
    orto = by_code(f, "PTBR-ORTO-001")[0]
    assert orto.location is not None and (orto.location.line, orto.location.column) == (4, 19)
    assert orto.suggestion == "ideia"


def test_orthography_regency_concordance_vices(tmp_path: Path) -> None:
    body = (
        "A freqüência é alta. Isso implica em custos e visa o lucro. Houveram falhas. "
        "Fazem dois anos que o estudo foi feito a nível de empresa, através de muitos "
        "testes, sendo que a coisa funcionou. Eu acredito na minha hipótese."
    )
    f = run_pt(tmp_path, body)
    assert by_code(f, "PTBR-ORTO-001")[0].suggestion == "frequência"
    assert len(by_code(f, "PTBR-REG-001")) == 2
    assert len(by_code(f, "PTBR-CONC-001")) == 2
    vic = " ".join(msgs(f, "PTBR-VICIO-001"))
    for w in ("a nível de", "através de", "muitos", "sendo que", "coisa"):
        assert w in vic, w
    assert len(by_code(f, "PTBR-PESSOA-001")) == 2


def test_anglicism_respects_italic_and_dict(tmp_path: Path) -> None:
    body = "A performance foi boa. A \\emph{performance} também. O dataset é público."
    f = run_pt(tmp_path, body)
    assert len(by_code(f, "PTBR-ANGL-001")) == 2
    f = run_pt(tmp_path / "b", body, {".errei-dict.txt": "dataset\n"})
    assert msgs(f, "PTBR-ANGL-001") == ["anglicismo 'performance'"]


def test_lengths_passive_repetition(tmp_path: Path) -> None:
    long_sentence = " ".join(["palavra"] * 45) + "."
    passive = (
        "Os dados foram coletados. As amostras foram analisadas. O modelo foi treinado. "
        "Os testes foram executados."
    )
    rep = "O modelo proposto supera o modelo base porque o modelo usa atenção."
    f = run_pt(tmp_path, long_sentence + "\n\n" + passive + "\n\n" + rep)
    assert "45 palavras" in msgs(f, "PTBR-FRASE-001")[0]
    assert by_code(f, "PTBR-PASSIVA-001")
    assert any("'modelo' repetida 3×" in m for m in msgs(f, "PTBR-REPET-001"))
    f = run_pt(tmp_path / "b", long_sentence, max_sentence_words=50)
    assert not by_code(f, "PTBR-FRASE-001")


def test_ignores_math_cites_urls_and_english(tmp_path: Path) -> None:
    body = (
        "O valor $à partir$ \\cite{à_fatores} \\url{http://idéia.org}.\n\n"
        "\\begin{verbatim}idéia\\end{verbatim}\n"
        "\\begin{otherlanguage*}{english}\\begin{resumoumacoluna}The idéia.\\end{resumoumacoluna}"
        "\\end{otherlanguage*}"
    )
    f = run_pt(tmp_path, body)
    assert not {c for c in codes(f) if c.startswith(("PTBR-CRASE", "PTBR-ORTO"))}


def test_spell_fallback(tmp_path: Path) -> None:
    f = run_pt(tmp_path, "A pesquiza teve excessão. A seção acadêmica tem gênero e Silva.")
    words = sorted(x.message.split("'")[1] for x in by_code(f, "PTBR-SPELL-001"))
    assert words == ["excessão", "pesquiza"]
    assert "LanguageTool" in by_code(f, "CORE-DEP-001")[0].message
    f = run_pt(tmp_path / "b", "A pesquiza.", {".errei-dict.txt": "pesquiza\n"})
    assert not by_code(f, "PTBR-SPELL-001")


def test_ignore_comment(tmp_path: Path) -> None:
    f = run_pt(tmp_path, "A idéia. % errei: ignore PTBR-ORTO-001\nOutra idéia.")
    assert [x.location.line for x in by_code(f, "PTBR-ORTO-001")] == [4]  # type: ignore[union-attr]


@pytest.mark.languagetool
def test_languagetool_real(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Requer Java + servidor baixado (errei doctor --download). Rode com -m languagetool."""
    monkeypatch.delenv("ERREI_NO_LANGUAGETOOL", raising=False)
    from errei.text import languagetool as lt

    if lt.unavailable_reason():
        pytest.skip(lt.unavailable_reason())
    peers: list[object] = []
    real = socket.socket.connect

    def spy(self: socket.socket, addr: object) -> None:
        peers.append(addr)
        real(self, addr)  # type: ignore[arg-type]

    monkeypatch.setattr(socket.socket, "connect", spy)
    f = run_pt(tmp_path, "Os resultado obtidos foram bons e vamos analizar depois.")
    assert by_code(f, "PTBR-LT-001") and by_code(f, "PTBR-LT-002")
    # o LanguageTool roda localmente: só conexões de loopback
    assert all(
        str(p[0]) in ("127.0.0.1", "::1", "localhost")
        for p in peers  # type: ignore[index]
        if isinstance(p, tuple)
    ), peers
    assert os.environ.get("ERREI_NO_LANGUAGETOOL") is None
