#!/bin/sh
# Teste de fumaça em CPU (sem GPU e sem rede): poucos exemplos locais, modelo minúsculo,
# 1 passo, avaliação e empacotamento. Deve terminar em menos de 2 minutos.
# Uso (da raiz do repositório): sh treino-gpu/fumaca.sh
set -eu
cd "$(dirname "$0")/.."
PY="${PYTHON:-python3}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
export CUDA_VISIBLE_DEVICES="" HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false
inicio=$(date +%s)

"$PY" treino-gpu/cita/dados.py --fumaca --saida "$TMP/dados"
"$PY" treino-gpu/cita/treinar.py --fumaca --dados "$TMP/dados" --saida "$TMP/saida" --max-passos 1
# retomar do checkpoint precisa funcionar
"$PY" treino-gpu/cita/treinar.py --fumaca --retomar --dados "$TMP/dados" --saida "$TMP/saida" --max-passos 1
"$PY" treino-gpu/cita/treinar.py --fumaca --estimar --dados "$TMP/dados" --saida "$TMP/saida"
"$PY" treino-gpu/cita/avaliar.py --dados "$TMP/dados" --saida "$TMP/saida"
"$PY" treino-gpu/cita/empacotar.py --dados "$TMP/dados" --saida "$TMP/saida" --dist "$TMP/dist"

test -s "$TMP/saida/metricas.json"
test -s "$TMP/dist/errei-cita-v2.tar.gz"
grep -q "errei-cita-v2.tar.gz" "$TMP/dist/sha256sums-modelo.txt"
(cd "$TMP/dist" && sha256sum -c sha256sums-modelo.txt)
tar -tzf "$TMP/dist/errei-cita-v2.tar.gz" | grep -q "^errei-cita-v2/config.json$"
tar -tzf "$TMP/dist/errei-cita-v2.tar.gz" | grep -q "^errei-cita-v2/README.md$"

dur=$(( $(date +%s) - inicio ))
echo "[OK] fumaça em ${dur}s"
if [ "$dur" -ge 120 ]; then
  echo "ERRO: a fumaça levou ${dur}s (limite: 120s)" >&2
  exit 1
fi
