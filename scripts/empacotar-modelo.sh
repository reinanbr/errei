#!/usr/bin/env bash
# Empacota um modelo treinado para anexar à release fixa "modelos" do GitHub.
# Uso: scripts/empacotar-modelo.sh [pasta-do-modelo]
#   ex.: scripts/empacotar-modelo.sh treino/modelos/errei-resumo-v1
# Depois: gh release upload modelos dist/<nome>.tar.gz dist/sha256sums-modelo.txt --clobber
set -euo pipefail
SRC="${1:-treino/modelos/errei-cita-v1}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
NAME="$(basename "$SRC")"
test -f "$SRC/config.json" || { echo "erro: $SRC não tem config.json" >&2; exit 1; }
test -f "$SRC/README.md" || echo "aviso: sem cartão do modelo (README.md)" >&2
mkdir -p dist
tar -C "$(dirname "$SRC")" -czf "dist/$NAME.tar.gz" --exclude='*.log' "$NAME"
# sha256sums-modelo.txt acumula uma linha por modelo
touch dist/sha256sums-modelo.txt
grep -v " $NAME.tar.gz\$" dist/sha256sums-modelo.txt > dist/.sums.tmp || true
(cd dist && sha256sum "$NAME.tar.gz" >> .sums.tmp && sort -k2 .sums.tmp > sha256sums-modelo.txt \
  && rm .sums.tmp && cat sha256sums-modelo.txt)
echo "[OK] dist/$NAME.tar.gz ($(du -h "dist/$NAME.tar.gz" | cut -f1))"
echo "publicar: gh release upload modelos dist/$NAME.tar.gz dist/sha256sums-modelo.txt --clobber"
