from __future__ import annotations

import sys
import time
from pathlib import Path

from conftest import ARTIGO
from helpers import audit, make_project


def test_twenty_files_under_five_seconds(tmp_path: Path) -> None:
    """Pasta típica (20 .tex + .bib) em poucos segundos offline (sem LanguageTool)."""
    para = " ".join((ARTIGO / "secoes" / "resultados.tex").read_text().split()[3:])
    files = {
        f"cap/s{i:02d}.tex": f"\\section{{Seção {i}}}\n" + (para + "\n\n") * 6 for i in range(19)
    }
    inputs = "\n".join(f"\\input{{cap/s{i:02d}}}" for i in range(19))
    files["main.tex"] = (
        "\\documentclass[brazil]{abntex2}\n\\usepackage[alf]{abntex2cite}\n"
        "\\begin{document}\n" + inputs + "\n\\bibliography{r}\n\\end{document}\n"
    )
    files["r.bib"] = (ARTIGO / "referencias.bib").read_text()
    root = make_project(tmp_path, files)
    t0 = time.perf_counter()
    rep = audit(root)
    elapsed = time.perf_counter() - t0
    assert rep.findings
    # com coverage (sys.settrace/monitoring) tudo fica ~4x mais lento; a meta real é 5 s
    traced = sys.gettrace() is not None or "coverage" in sys.modules
    limit = 20.0 if traced else 5.0
    assert elapsed < limit, f"{elapsed:.2f}s (limite {limit}s)"
