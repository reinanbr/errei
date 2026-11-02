#!/usr/bin/env bash
# Empacota o modelo treinado para anexar à release do GitHub.
# Uso: scripts/empacotar-modelo.sh [pasta-do-modelo] [tag]
#   ex.: scripts/empacotar-modelo.sh treino/modelos/errei-cita-v1 v0.2.0
# Depois: gh release upload <tag> dist/errei-cita-v1.tar.gz dist/sha256sums-modelo.txt
# (e acrescente a linha do modelo ao sha256sums.txt da release, se quiser verificação)
set -euo pipefail
SRC="${1:-treino/modelos/errei-cita-v1}"
TAG="${2:-}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
test -f "$SRC/config.json" || { echo "erro: $SRC não tem config.json" >&2; exit 1; }
test -f "$SRC/README.md" || echo "aviso: sem cartão do modelo (rode treino/finalizar.py)" >&2
mkdir -p dist
tar -C "$(dirname "$SRC")" -czf dist/errei-cita-v1.tar.gz \
  --exclude='*.log' "$(basename "$SRC")"
(cd dist && sha256sum errei-cita-v1.tar.gz > sha256sums-modelo.txt && cat sha256sums-modelo.txt)
echo "[OK] dist/errei-cita-v1.tar.gz ($(du -h dist/errei-cita-v1.tar.gz | cut -f1))"
if [ -n "$TAG" ]; then
  echo "publicar: gh release upload $TAG dist/errei-cita-v1.tar.gz dist/sha256sums-modelo.txt"
fi
