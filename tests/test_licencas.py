"""O errei é 100% open source: nenhuma dependência pode ter licença fora da lista OSI.

Percorre, pelos metadados instalados, o fechamento das dependências do errei (núcleo e
todos os extras de uso; ``dev`` fica de fora porque não é distribuído). Pacotes não
instalados são ignorados (ex.: torch sem o extra ``modelo``); os instalados precisam
declarar uma licença aprovada.
"""

from __future__ import annotations

import re
from importlib import metadata

import pytest
from packaging.requirements import Requirement

# licenças aprovadas pela OSI (SPDX) que permitem uso comercial e redistribuição
APROVADAS = {
    "MIT",
    "MIT-CMU",
    "APACHE-2.0",
    "BSD-2-CLAUSE",
    "BSD-3-CLAUSE",
    "ISC",
    "PSF-2.0",
    "PYTHON-2.0",
    "MPL-2.0",
    "LGPL-2.1",
    "LGPL-2.1-OR-LATER",
    "LGPL-3.0",
    "LGPL-3.0-OR-LATER",
    "UNLICENSE",
    "ZLIB",
    "HPND",
    "0BSD",
    "BSL-1.0",
    "CNRI-PYTHON",
    # dedicação ao domínio público; não passa pela OSI, mas é livre (FSF) e permite uso
    # comercial (aceita também para dados, regra D2.4); o numpy a usa em arquivos isolados
    "CC0-1.0",
    # copyleft, mas aprovadas pela OSI (livres e gratuitas); só em extras opcionais
    "GPL-3.0-ONLY",
    "GPL-3.0-OR-LATER",
    "GPL-3.0",
}
# nomes livres (classificadores "License :: OSI Approved :: ..." e campos License antigos)
NOMES = {
    "mit": "MIT",
    "mit license": "MIT",
    "apache 2.0": "APACHE-2.0",
    "apache-2.0": "APACHE-2.0",
    "apache 2.0 license": "APACHE-2.0",
    "apache software license": "APACHE-2.0",
    "apache license 2.0": "APACHE-2.0",
    "apache license, version 2.0": "APACHE-2.0",
    "bsd": "BSD-3-CLAUSE",
    "bsd license": "BSD-3-CLAUSE",
    "bsd-3-clause": "BSD-3-CLAUSE",
    "bsd 3-clause": "BSD-3-CLAUSE",
    "3-clause bsd license": "BSD-3-CLAUSE",
    "new bsd license": "BSD-3-CLAUSE",
    "bsd-2-clause": "BSD-2-CLAUSE",
    "isc license (iscl)": "ISC",
    "isc": "ISC",
    "python software foundation license": "PSF-2.0",
    "psf": "PSF-2.0",
    "mozilla public license 2.0 (mpl 2.0)": "MPL-2.0",
    "gnu lesser general public license v3 (lgplv3)": "LGPL-3.0",
    "gnu lesser general public license v3 or later (lgplv3+)": "LGPL-3.0-OR-LATER",
    "gnu lesser general public license v2 or later (lgplv2+)": "LGPL-2.1-OR-LATER",
    "the unlicense (unlicense)": "UNLICENSE",
}
EXTRAS_DISTRIBUIDOS = ("online", "ptbr", "plagio", "pdf", "modelo", "traducao")
# ReportLab declara "BSD license" só no texto longo do campo License
TEXTO_LONGO = re.compile(r"\b(BSD|MIT|Apache License)\b")


SPDX = re.compile(r"^[A-Za-z0-9.+-]+(?:\s+(?:OR|AND|WITH)\s+[A-Za-z0-9.+-]+)*$")


# "A WITH exceção": a exceção só acrescenta permissões; vale a licença A
WITH_EXCECAO = re.compile(r"\s+WITH\s+[A-Za-z0-9.+-]+")


def _spdx(expr: str) -> set[str]:
    expr = WITH_EXCECAO.sub("", expr)
    return {p.strip().upper() for p in re.split(r"\s+(?:OR|AND)\s+|[()]", expr) if p.strip()}


def _licencas(dist: metadata.Distribution) -> set[str]:
    """Licenças declaradas, normalizadas para SPDX em maiúsculas.

    Numa expressão ``A AND B`` todas precisam ser aprovadas; com ``OR`` basta uma.
    """
    md = dist.metadata
    out: set[str] = set()
    expr = (md.get("License-Expression") or "").strip()
    lic0 = (md.get("License") or "").strip()
    if not expr and lic0.lower() not in NOMES and SPDX.match(lic0) and " " in lic0:
        expr = lic0
    if expr:
        if " AND " in expr and " OR " not in expr:
            parts = _spdx(expr)
            return parts if parts <= APROVADAS else {"(" + expr.upper() + ")"}
        return _spdx(expr)
    for c in md.get_all("Classifier") or []:
        if c.startswith("License :: OSI Approved ::"):
            name = c.rsplit("::", 1)[1].strip().lower()
            out.add(NOMES.get(name, name.upper()))
    lic = (md.get("License") or "").strip()
    if not out and lic:
        key = lic.lower()
        if key in NOMES:
            out.add(NOMES[key])
        elif len(lic) > 40 and (m := TEXTO_LONGO.search(lic)):
            out.add(NOMES[m.group(1).lower() if m.group(1) != "Apache License" else "apache 2.0"])
        else:
            out.add(lic.upper())
    return out


def _fechamento() -> dict[str, metadata.Distribution]:
    root = metadata.distribution("errei")
    fila: list[tuple[Requirement, set[str]]] = []
    for raw in root.requires or []:
        req = Requirement(raw)
        envs = [{"extra": ""}] + [{"extra": e} for e in EXTRAS_DISTRIBUIDOS]
        wanted = req.marker is None or any(req.marker.evaluate(env) for env in envs)
        if wanted and req.name.lower() != "errei":
            fila.append((req, set(req.extras)))
    seen: dict[str, metadata.Distribution] = {}
    while fila:
        req, extras = fila.pop()
        name = req.name.lower().replace("_", "-")
        if name in seen:
            continue
        try:
            dist = metadata.distribution(req.name)
        except metadata.PackageNotFoundError:
            continue  # extra não instalado: nada é distribuído junto
        seen[name] = dist
        for raw in dist.requires or []:
            sub = Requirement(raw)
            envs = [{"extra": e} for e in ("", *extras)]
            if sub.marker is None or any(sub.marker.evaluate(env) for env in envs):
                fila.append((sub, set(sub.extras)))
    return seen


def test_dependencias_com_licenca_aprovada() -> None:
    deps = _fechamento()
    assert "typer" in deps and "rich" in deps  # o fechamento foi de fato percorrido
    ruins = {
        name: sorted(lics)
        for name, dist in deps.items()
        if not (lics := _licencas(dist)) or not lics & APROVADAS
    }
    assert not ruins, f"dependências com licença não aprovada (ou ausente): {ruins}"


def test_o_proprio_errei_e_mit() -> None:
    assert _licencas(metadata.distribution("errei")) == {"MIT"}


@pytest.mark.parametrize(
    ("expr", "ok"),
    [("MIT", True), ("Apache-2.0 OR BSD-3-Clause", True), ("CC-BY-NC-4.0", False)],
)
def test_normalizacao(expr: str, ok: bool) -> None:
    class D:
        def __init__(self) -> None:
            self.metadata = {"License-Expression": expr}

    lics = _licencas(D())  # type: ignore[arg-type]
    assert bool(lics & APROVADAS) is ok
