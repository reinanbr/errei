"""Banco e listas sintéticos para a fumaça (sem rede). Nada daqui vai para treino real."""

from __future__ import annotations

import argparse
import random
import sys
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from comum.jats import Secao

from banco.banco import Banco

CAMPOS = {
    "Medicine": {
        "pt": [
            "pacientes",
            "tratamento",
            "hospital",
            "adesão",
            "terapia",
            "diagnóstico",
            "saúde",
            "risco",
        ],
        "en": [
            "patients",
            "treatment",
            "hospital",
            "adherence",
            "therapy",
            "diagnosis",
            "health",
            "risk",
        ],
    },
    "Computer Science": {
        "pt": [
            "algoritmo",
            "rede",
            "dados",
            "modelo",
            "aprendizado",
            "sistema",
            "desempenho",
            "código",
        ],
        "en": [
            "algorithm",
            "network",
            "data",
            "model",
            "learning",
            "system",
            "performance",
            "code",
        ],
    },
    "Social Sciences": {
        "pt": [
            "escola",
            "professores",
            "ensino",
            "alunos",
            "políticas",
            "comunidade",
            "currículo",
            "leitura",
        ],
        "en": [
            "school",
            "teachers",
            "teaching",
            "students",
            "policies",
            "community",
            "curriculum",
            "reading",
        ],
    },
}
CAB = {
    "pt": ["Objetivo:", "Métodos:", "Resultados:", "Conclusão:"],
    "en": ["Objective:", "Methods:", "Results:", "Conclusions:"],
}
FRASES = {
    "pt": {
        "contexto": "O tema de {a} e {b} tem recebido atenção crescente na literatura recente.",
        "objetivo": "Este estudo teve como objetivo analisar a relação entre {a} e {b}.",
        "metodo": "Foi realizado um estudo transversal com {n} casos sobre {a} e {b}.",
        "resultado": "Os resultados mostraram aumento de {n} por cento em {a} associado a {b}.",
        "conclusao": "Conclui-se que {a} contribui para melhorar {b} em diferentes contextos.",
    },
    "en": {
        "contexto": "The topic of {a} and {b} has received growing attention in recent literature.",
        "objetivo": "This study aimed to analyze the relationship between {a} and {b}.",
        "metodo": "A cross-sectional study with {n} cases on {a} and {b} was conducted.",
        "resultado": "The results showed a {n} percent increase in {a} associated with {b}.",
        "conclusao": "We conclude that {a} helps improve {b} in different settings.",
    },
}
SECOES = [
    (
        "Introdução",
        "introducao",
        "",
        "A literatura sobre {a} e {b} é ampla e ainda apresenta lacunas importantes.",
    ),
    (
        "Métodos",
        "metodo",
        "",
        "Trata-se de estudo descritivo sobre {a} e {b} conduzido em {n} etapas.",
    ),
    (
        "Participantes",
        "metodo",
        "metodo:participantes",
        "Participaram {n} pessoas recrutadas em serviços de {a}.",
    ),
    (
        "Análise estatística",
        "metodo",
        "metodo:analise",
        "Os dados de {a} foram analisados com testes de {b} e nível de significância de 5%.",
    ),
    (
        "Resultados",
        "resultados",
        "",
        "Observou-se que {a} variou {n} pontos entre os grupos de {b}.",
    ),
    (
        "Discussão",
        "discussao",
        "",
        "Esses achados sobre {a} concordam com estudos anteriores sobre {b}.",
    ),
    (
        "Limitações",
        "discussao",
        "discussao:limitacoes",
        "Entre as limitações estão o tamanho da amostra de {a} e a medida de {b}.",
    ),
    ("Conclusão", "conclusao", "", "Conclui-se que {a} deve ser considerado nas políticas de {b}."),
]
SOBRENOMES = [
    "Silva",
    "Souza",
    "Oliveira",
    "Santos",
    "Pereira",
    "Lima",
    "Costa",
    "Martins",
    "Almeida",
    "Ferreira",
]
NOMES = ["Ana", "Bruno", "Carla", "Diego", "Elisa", "Fábio", "Gabriela", "Hugo", "Iara", "João"]


def _frase(lingua: str, papel: str, voc: list[str], r: random.Random) -> str:
    a, b = r.sample(voc, 2)
    return FRASES[lingua][papel].format(a=a, b=b, n=r.randint(5, 900))


def criar(arquivo: Path, n: int = 150, semente: int = 7) -> None:
    arquivo.unlink(missing_ok=True)
    for suf in ("-wal", "-shm"):
        Path(str(arquivo) + suf).unlink(missing_ok=True)
    r = random.Random(semente)
    with Banco(arquivo) as b:
        fontes = []
        for i, campo in enumerate(CAMPOS):
            for j in range(2):
                fid = f"S{900 + i * 2 + j}"
                issn = f"{1000 + i * 2 + j:04d}-{2000 + j:04d}"
                b.fonte(
                    {
                        "id": fid,
                        "nome": f"Revista Sintética {campo} {j + 1}",
                        "issn_l": issn,
                        "issns": [issn],
                        "editora": "Editora Sintética",
                        "pais": "BR",
                        "tipo": "journal",
                        "is_oa": 1,
                        "is_in_doaj": 1,
                        "is_in_scielo": j,
                        "is_core": 1 - j,
                        "listas": ["doaj", "scielo"] if j else ["doaj", "cwts-core"],
                    }
                )
                fontes.append((fid, campo))
        for k in range(n):
            fid, campo = fontes[k % len(fontes)]
            voc = CAMPOS[campo]
            oid = f"W{100000 + k}"
            ano = 2014 + k % 11
            lic = "cc-by" if k % 10 else "cc-by-nc"  # 10% NC: não pode virar treino
            idioma = "pt" if k % 3 else "en"
            a1, a2 = r.sample(voc["pt"], 2)
            b.obra(
                {
                    "id": oid,
                    "doi": f"10.9999/sint.{k}",
                    "titulo": f"Relação entre {a1} e {a2}",
                    "idioma": idioma,
                    "ano": ano,
                    "tipo": "article",
                    "fonte_id": fid,
                    "licenca": lic,
                    "volume": str(1 + k % 30),
                    "numero": str(1 + k % 4),
                    "pagina_ini": str(10 + k),
                    "pagina_fim": str(25 + k),
                    "editora": "Editora Sintética",
                    "citacoes": k % 50,
                    "percentil_citacoes": (k % 100) / 100,
                    "top10": int(k % 10 == 0),
                    "dominio": "Sintético",
                    "campo": campo,
                    "subcampo": campo,
                    "topico": campo,
                    "origem": "sintetico",
                    "pid_scielo": f"S{1000 + k:04d}-0000{2020}{k:09d}"[:23],
                }
            )
            b.autores(oid, [f"{r.choice(NOMES)} {r.choice(SOBRENOMES)}" for _ in range(1 + k % 4)])
            for lg in ("pt", "en"):
                x, y = r.sample(voc[lg], 2)
                b.titulo(
                    oid,
                    lg,
                    (
                        f"Relação entre {x} e {y}"
                        if lg == "pt"
                        else f"Relationship between {x} and {y}"
                    ),
                    "sintetico",
                )
                papeis = ["contexto", "objetivo", "metodo", "resultado", "resultado", "conclusao"]
                if k % 2:  # estruturado
                    partes = [
                        CAB[lg][0] + " " + _frase(lg, "objetivo", voc[lg], r),
                        CAB[lg][1] + " " + _frase(lg, "metodo", voc[lg], r),
                        CAB[lg][2]
                        + " "
                        + _frase(lg, "resultado", voc[lg], r)
                        + " "
                        + _frase(lg, "resultado", voc[lg], r),
                        CAB[lg][3] + " " + _frase(lg, "conclusao", voc[lg], r),
                    ]
                    b.resumo(oid, lg, " ".join(partes), True, "sintetico")
                else:
                    b.resumo(
                        oid,
                        lg,
                        " ".join(_frase(lg, p, voc[lg], r) for p in papeis),
                        False,
                        "sintetico",
                    )
                b.palavras(oid, lg, r.sample(voc[lg], 3), "autor")
            if k % 2 == 0:
                secs = []
                for o, (tit, tipo, parte, modelo) in enumerate(SECOES):
                    paras = [
                        modelo.format(
                            a=r.choice(voc["pt"]), b=r.choice(voc["pt"]), n=r.randint(2, 99)
                        )
                        for _ in range(2)
                    ]
                    secs.append(Secao(o, 2 if parte else 1, tit, tipo, parte, "\n".join(paras)))
                b.secoes(oid, "pt", secs, "sintetico")
                b.referencias(oid, [f"SILVA, A. Título {k}. Revista X, v. 1, p. 1-9, 2020."])
        b.con.commit()


def _xlsx(caminho: Path, linhas: list[list[str]], aba: str = "Planilha1") -> None:
    def col(i: int) -> str:
        s = ""
        i += 1
        while i:
            i, rto = divmod(i - 1, 26)
            s = chr(65 + rto) + s
        return s

    rows = []
    for ri, ln in enumerate(linhas, 1):
        cels = "".join(
            f'<c r="{col(ci)}{ri}" t="inlineStr"><is><t>{escape(v)}</t></is></c>'
            for ci, v in enumerate(ln)
        )
        rows.append(f'<row r="{ri}">{cels}</row>')
    m = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    with zipfile.ZipFile(caminho, "w") as z:
        z.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="xml" ContentType="application/xml"/></Types>',
        )
        z.writestr(
            "xl/workbook.xml",
            f'<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="{m}" xmlns:r="{rel}">'
            f'<sheets><sheet name="{aba}" sheetId="1" r:id="rId1"/></sheets></workbook>',
        )
        z.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Target="worksheets/sheet1.xml" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"/></Relationships>',
        )
        z.writestr(
            "xl/worksheets/sheet1.xml",
            f'<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="{m}"><sheetData>{"".join(rows)}</sheetData></worksheet>',
        )


def escrever_listas(pasta: Path) -> dict[str, Path]:
    """Listas no formato das oficiais (Qualis CSV, Scopus XLSX, CiteScore XLSX, WoS CSV)."""
    pasta.mkdir(parents=True, exist_ok=True)
    issns = [f"{1000 + i:04d}-{2000 + i % 2:04d}" for i in range(6)]
    q = pasta / "qualis.csv"
    estratos = ["A1", "A2", "B1", "A4", "B3", "C"]
    q.write_text(
        "ISSN;Título;Área de Avaliação;Estrato\n"
        + "".join(
            f"{s};REVISTA {i};MEDICINA I;{e}\n{s};REVISTA {i};EDUCAÇÃO;{estratos[(i + 2) % 6]}\n"
            for i, (s, e) in enumerate(zip(issns, estratos, strict=False))
        ),
        encoding="cp1252",
    )
    sc = pasta / "scopus_sources.xlsx"
    _xlsx(
        sc,
        [
            [
                "Sourcerecord ID",
                "Source Title",
                "Print-ISSN",
                "E-ISSN",
                "Active or Inactive",
                "All Science Journal Classification Codes (ASJC)",
            ]
        ]
        + [
            [
                str(100 + i),
                f"Revista {i}",
                s.replace("-", ""),
                "",
                "Active" if i % 3 else "Inactive",
                "2700; 3304",
            ]
            for i, s in enumerate(issns[:4])
        ],
        aba="Scopus Sources Oct. 2026",
    )
    cs = pasta / "citescore_2025.xlsx"
    _xlsx(
        cs,
        [["Source title", "CiteScore", "Highest percentile", "Print ISSN", "E-ISSN"]]
        + [
            [
                f"Revista {i}",
                f"{2.5 + i}",
                f"{95 - 20 * i}% 12/240 General Medicine",
                s.replace("-", ""),
                "",
            ]
            for i, s in enumerate(issns[:4])
        ],
    )
    w = pasta / "wos-core_SCIE 2026-November-01.csv"
    w.write_text(
        '"Journal title","ISSN","eISSN","Publisher name","Publisher address","Languages","Web of Science Categories"\n'
        + "".join(
            f'"REVISTA {i}","{s}","","EDITORA","BRASIL","Portuguese","Medicine, General & Internal"\n'
            for i, s in enumerate(issns[:2])
        ),
        encoding="utf-8",
    )
    return {"qualis": q, "scopus": sc, "citescore": cs, "wos": w}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="banco e listas sintéticos (só para a fumaça)")
    ap.add_argument("--banco", type=Path, required=True)
    ap.add_argument(
        "--listas", type=Path, help="pasta onde escrever listas Qualis/Scopus/WoS falsas"
    )
    ap.add_argument("-n", type=int, default=150)
    a = ap.parse_args(argv)
    criar(a.banco, a.n)
    if a.listas:
        for k, v in escrever_listas(a.listas).items():
            print(f"{k}: {v}")
    print(f"[OK] banco sintético em {a.banco}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
