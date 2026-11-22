#!/bin/sh
# Teste de fumaça em CPU (sem GPU e sem rede): banco sintético, listas Qualis/Scopus/WoS
# falsas, textos de IA de um modelo minúsculo e, para os 9 modelos, dados, treino, retomar,
# estimativa, avaliação e pacote. Deve terminar em menos de 3 minutos.
# Uso (da raiz do repositório): sh treino-modelos/fumaca.sh [modelo ...]
set -eu
cd "$(dirname "$0")/.."
PY="${PYTHON:-python3}"
inicio=$(date +%s)
"$PY" treino-modelos/fumaca.py "$@"
dur=$(( $(date +%s) - inicio ))
if [ "$dur" -ge 180 ]; then
  echo "ERRO: a fumaça levou ${dur}s (limite: 180s)" >&2
  exit 1
fi
