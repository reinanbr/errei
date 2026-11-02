from __future__ import annotations

from pathlib import Path

from errei.bib.fields import normalize_doi, valid_arxiv, valid_doi, valid_isbn
from errei.bib.names import parse_authors, parse_name
from errei.bib.parser import parse_bib, plain
from errei.latex.source import SourceFile

BIB = r"""@string{nat = "Nature"}
@comment{ignorado}
@article{a1,
  author = {da Silva, Jo{\~a}o and Maria Souza Filho},
  title = "Um {T}ítulo",
  journal = nat,
  year = 2020,
  month = jan,
  title = {duplicado}
}
@book(b2, title={Livro}, year={1999})
@misc{semfechar,
  title = {x}
"""


def bib():
    return parse_bib(SourceFile(Path("r.bib"), Path("r.bib"), BIB))


def test_entries_and_fields() -> None:
    b = bib()
    assert [e.key for e in b.entries] == ["a1", "b2"]
    a1 = b.entries[0]
    assert a1.line == 3
    assert a1.get("journal") == "Nature"
    assert a1.get("year") == "2020"
    assert a1.get("title") == "Um {T}ítulo"
    assert [f.name for f in a1.duplicate_fields] == ["title"]
    assert b.entries[1].type == "book"
    assert any("sem fechamento" in p.message for p in b.problems)


def test_field_offset_points_to_name() -> None:
    b = bib()
    e = b.entries[0]
    off = e.field_offset("journal")
    assert BIB[off : off + 7] == "journal"


def test_names() -> None:
    names = parse_authors(bib().entries[0].get("author"))
    assert names[0].last == "Silva" and names[0].von == "da" and names[0].first == "João"
    assert names[1].last == "Souza" and names[1].jr == "Filho"
    assert parse_name("{IBGE}").literal
    assert parse_name("Ludwig van Beethoven").von == "van"


def test_plain() -> None:
    assert plain(r"{\'A}gua e {\c{c}}\~ao --- \emph{x}") == "Água e ção — x"


def test_identifiers() -> None:
    assert valid_doi("https://doi.org/10.1038/nature14539")
    assert normalize_doi("doi: 10.1/x.") == "10.1/x"
    assert not valid_doi("10.12/abc")
    assert valid_isbn("978-85-7522-403-8")
    assert not valid_isbn("978-85-0000-000-1")
    assert valid_isbn("0-306-40615-2")
    assert valid_arxiv("2101.00001v2") and valid_arxiv("hep-th/9901001")
    assert not valid_arxiv("21.0001")
