#!/bin/sh
# Treina o errei-resumo-v1 do zero: baixa o CSAbstruct, traduz, treina, avalia e instala.
# Uso: sh rodar.sh [threads] [max_frases_treino_traduzidas]
set -e
cd "$(dirname "$0")"
PY=${PY:-../../.venv/bin/python}
D=../dados/csabstruct
mkdir -p "$D"
HF=https://huggingface.co/datasets/allenai/csabstruct/resolve/main/data
[ -f "$D/train.parquet" ] || curl -fsSL -o "$D/train.parquet" "$HF/train-00000-of-00001-e4ddac953345ce34.parquet"
[ -f "$D/validation.parquet" ] || curl -fsSL -o "$D/validation.parquet" "$HF/validation-00000-of-00001-6393d2add96db558.parquet"
[ -f "$D/test.parquet" ] || curl -fsSL -o "$D/test.parquet" "$HF/test-00000-of-00001-be7e891381aedbe0.parquet"
"$PY" traduzir.py "${1:-10}" "${2:-6000}"
"$PY" treinar.py ../modelos/errei-resumo-v1 4
../../.venv/bin/errei modelo instalar ../modelos/errei-resumo-v1 --nome errei-resumo-v1 --force
echo "pronto. acompanhe/veja: $D/progresso.txt e ../modelos/errei-resumo-v1/README.md"
