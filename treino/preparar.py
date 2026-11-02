"""Monta pares (afirmação, trecho da fonte) -> sustenta|contradiz|neutro a partir do SciFact.

Divisão: 90% das afirmações de treino para treino, 10% para validação (escolha de
limiares); o dev oficial do SciFact fica reservado como teste final.
Saída: dados/pares_treino.jsonl, dados/pares_val.jsonl e dados/afirmacoes_*.jsonl.
"""

from __future__ import annotations

from comum import DADOS, SCIFACT, corpus, read_jsonl, rng, write_jsonl

MAP = {"SUPPORT": "sustenta", "CONTRADICT": "contradiz"}


def traducoes() -> dict[str, str]:
    p = DADOS / "traducoes.jsonl"
    return {r["en"]: r["pt"] for r in read_jsonl(p)} if p.exists() else {}


def pares(claims: list[dict], docs: dict[int, dict], tr: dict[str, str],  # type: ignore[type-arg]
          *, pt: bool) -> list[dict]:  # type: ignore[type-arg]
    r = rng()
    out: list[dict] = []  # type: ignore[type-arg]
    all_ids = list(docs)

    def add(claim: str, premise: str, label: str, kind: str) -> None:
        out.append({"a": claim, "b": premise, "label": label, "tipo": kind})
        if pt and claim in tr:
            out.append({"a": tr[claim], "b": premise, "label": label, "tipo": kind + "/pt-en"})
            if premise in tr and r.random() < 0.5:
                out.append({"a": tr[claim], "b": tr[premise], "label": label,
                            "tipo": kind + "/pt-pt"})

    for c in claims:
        claim = c["claim"]
        for doc_id in c.get("cited_doc_ids", []):
            d = docs.get(int(doc_id))
            if not d:
                continue
            sents = d["abstract"]
            evs = c["evidence"].get(str(doc_id), [])
            rat: set[int] = set()
            for ev in evs:
                idx = sorted(ev["sentences"])
                rat.update(idx)
                lab = MAP[ev["label"]]
                add(claim, " ".join(sents[i] for i in idx), lab, "evid")
                if len(idx) > 1:
                    for i in idx:
                        add(claim, sents[i], lab, "evid1")
            outros = [i for i in range(len(sents)) if i not in rat]
            r.shuffle(outros)
            for i in outros[:3]:
                add(claim, sents[i], "neutro", "mesmo-doc")
        for _ in range(2):
            d = docs[r.choice(all_ids)]
            add(claim, r.choice(d["abstract"]), "neutro", "aleatorio")
    return out


def main() -> None:
    docs = corpus()
    tr = traducoes()
    train = list(read_jsonl(SCIFACT / "claims_train.jsonl"))
    r = rng()
    r.shuffle(train)
    n_val = len(train) // 10
    val, train = train[:n_val], train[n_val:]
    dev = list(read_jsonl(SCIFACT / "claims_dev.jsonl"))
    tr_pairs = pares(train, docs, tr, pt=True)
    val_pairs = pares(val, docs, tr, pt=True)
    write_jsonl(DADOS / "pares_treino.jsonl", tr_pairs)
    write_jsonl(DADOS / "pares_val.jsonl", val_pairs)
    for nome, cl in (("val", val), ("teste", dev)):
        rows = []
        for c in cl:
            rows.append({**c, "claim_pt": tr.get(c["claim"], "")})
        write_jsonl(DADOS / f"afirmacoes_{nome}.jsonl", rows)
    from collections import Counter
    print("traduções:", len(tr))
    print("treino:", len(tr_pairs), Counter(p["label"] for p in tr_pairs))
    print("val:", len(val_pairs), Counter(p["label"] for p in val_pairs))
    print("afirmações val/teste:", len(val), len(dev))


if __name__ == "__main__":
    main()
