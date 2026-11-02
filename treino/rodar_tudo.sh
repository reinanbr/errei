#!/usr/bin/env bash
# Reproduz o modelo errei-cita-v1 do zero (CPU; ~1–2 h numa máquina de 8–12 núcleos).
# Requer: pip install -e '.[modelo]' (torch CPU) e acesso à internet para baixar dados/modelos.
set -euo pipefail
cd "$(dirname "$0")"
PY=${PY:-../.venv/bin/python}
mkdir -p dados
if [ ! -d dados/scifact/data ]; then
  curl -sSL -o dados/scifact.tar.gz https://scifact.s3-us-west-2.amazonaws.com/release/latest/data.tar.gz
  mkdir -p dados/scifact && tar -xzf dados/scifact.tar.gz -C dados/scifact
fi
$PY traduzir.py            # afirmações e evidências em pt-BR (cache incremental)
$PY preparar.py            # pares sustenta/contradiz/neutro + divisões
$PY treinar.py modelos/errei-cita-v1 3
$PY finalizar.py modelos/errei-cita-v1
../.venv/bin/errei modelo instalar modelos/errei-cita-v1 --force
