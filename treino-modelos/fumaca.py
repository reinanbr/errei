"""Teste de fumaça de ponta a ponta, em CPU, sem rede e sem baixar modelos.

Banco sintético → listas Qualis/Scopus/CiteScore/WoS falsas importadas → textos de IA
com um modelo minúsculo → para cada modelo: dados, 1 passo de treino, retomar do
checkpoint, estimativa, avaliação e pacote (tar.gz + sha256 conferidos).

Uso (da raiz do repositório): python treino-modelos/fumaca.py [resumo ref ...]
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import tarfile
import tempfile
import time
from contextlib import redirect_stdout
from pathlib import Path

os.environ.update(
    CUDA_VISIBLE_DEVICES="",
    HF_HUB_OFFLINE="1",
    TRANSFORMERS_OFFLINE="1",
    TOKENIZERS_PARALLELISM="false",
)
AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))

import avaliar  # noqa: E402
import dados  # noqa: E402
import empacotar  # noqa: E402
import gerar_ia  # noqa: E402
import treinar  # noqa: E402
from banco import classificar, consultar, sintetico  # noqa: E402
from modelos import MODELOS, obter  # noqa: E402


def rodar(nome: str, f: object, args: list[str], quieto: bool = True) -> str:
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = f.main(args)  # type: ignore[attr-defined]
    saida = buf.getvalue()
    if rc != 0:
        print(saida)
        raise SystemExit(f"FALHOU: {nome} {' '.join(args)} (código {rc})")
    if not quieto:
        print(saida.rstrip())
    return saida


def main(argv: list[str] | None = None) -> int:
    alvo = list(argv if argv is not None else sys.argv[1:]) or list(MODELOS)
    inicio = time.time()
    with tempfile.TemporaryDirectory(prefix="errei-fumaca-") as d:
        tmp = Path(d)
        banco = tmp / "banco.sqlite"
        sintetico.criar(banco)
        listas = sintetico.escrever_listas(tmp / "listas")
        out = rodar(
            "classificar",
            classificar,
            [
                "--banco",
                str(banco),
                "--edicao",
                "2021-2024",
                "--qualis",
                str(listas["qualis"]),
                "--scopus",
                str(listas["scopus"]),
                "--citescore",
                str(listas["citescore"]),
                "--wos",
                str(listas["wos"]),
                "--openalex",
            ],
        )
        res = json.loads(out[out.index("{") :])
        assert res["revistas_qualis"] == 6, res
        assert res["revistas_scopus"] == 2, res  # 2 das 4 estão inativas
        assert res["revistas_wos_por_colecao"] == {"SCIE": 2}, res
        assert res["obras"]["qualis"] > 0 and res["obras"]["wos"] > 0, res
        print(
            f"[ok] classificação: {res['revistas_qualis_por_estrato']} · scopus {res['revistas_scopus']} · "
            f"wos {res['revistas_wos_por_colecao']}"
        )
        out = rodar(
            "consultar", consultar, ["--banco", str(banco), "--qualis", "A1", "A2", "--wos"]
        )
        filtradas = json.loads(out)["filtradas"]
        assert 0 < filtradas < 150, filtradas
        rodar(
            "consultar",
            consultar,
            ["--banco", str(banco), "--exportar", str(tmp / "obras.csv"), "--scopus"],
        )
        assert (tmp / "obras.csv").read_text(encoding="utf-8").count("\n") > 1
        rodar("gerar_ia", gerar_ia, ["--fumaca", "--banco", str(banco)])
        print(f"[ok] banco, listas e textos de IA ({time.time() - inicio:.0f}s)")

        # filtro por classificação dentro de um construtor (config temporária)
        cfg = (AQUI / "config" / "modelos.toml").read_text(encoding="utf-8")
        cfg = cfg.replace(
            '[resumo.filtros]\nidiomas = ["pt", "en", "es"]',
            '[resumo.filtros]\nidiomas = ["pt", "en", "es"]\nqualis = ["A1", "A2", "A3", "A4"]\nscopus = true',
        )
        (tmp / "modelos.toml").write_text(cfg, encoding="utf-8")
        out = rodar(
            "dados(filtro)",
            dados,
            [
                "--modelo",
                "resumo",
                "--fumaca",
                "--banco",
                str(banco),
                "--config",
                str(tmp / "modelos.toml"),
                "--saida",
                str(tmp / "filtro"),
            ],
        )
        man = json.loads((tmp / "filtro" / "manifesto.json").read_text())
        assert set(man["classificacao"]["qualis_faixa"]) == {"A"}, man["classificacao"]
        assert man["classificacao"]["scopus"] == man["classificacao"]["obras"], man["classificacao"]

        dist = tmp / "dist"
        for m in alvo:
            t0 = time.time()
            dd, ss = str(tmp / "dados" / m), str(tmp / "saida" / m)
            rodar("dados", dados, ["--modelo", m, "--fumaca", "--banco", str(banco), "--saida", dd])
            comum = ["--modelo", m, "--fumaca", "--dados", dd, "--saida", ss]
            rodar("treinar", treinar, [*comum, "--max-passos", "1"])
            rodar("treinar --retomar", treinar, [*comum, "--retomar", "--max-passos", "1"])
            est = rodar("treinar --estimar", treinar, [*comum, "--estimar"])
            assert "custo total estimado" in est
            av = rodar(
                "avaliar", avaliar, ["--modelo", m, "--fumaca", "--dados", dd, "--saida", ss]
            )
            rodar(
                "empacotar",
                empacotar,
                ["--modelo", m, "--dados", dd, "--saida", ss, "--dist", str(dist)],
            )
            nome = obter(m).NOME
            tar = dist / f"{nome}.tar.gz"
            with tarfile.open(tar) as t:
                nomes = set(t.getnames())
            for f in (
                "config.json",
                "README.md",
                "manifesto.json",
                "errei_tarefa.json",
                "errei_avaliacao.json",
            ):
                assert f"{nome}/{f}" in nomes, (nome, f)
            assert not any(n.endswith("estado.pt") for n in nomes)
            print(
                f"[ok] {nome:16} {time.time() - t0:5.1f}s · {av.strip().splitlines()[-1][5:][:110]}"
            )
        for ln in (dist / "sha256sums-modelo.txt").read_text().splitlines():
            dig, arq = ln.split()
            assert hashlib.sha256((dist / arq).read_bytes()).hexdigest() == dig, arq
    dur = time.time() - inicio
    print(f"[OK] fumaça de {len(alvo)} modelo(s) em {dur:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
