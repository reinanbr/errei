#!/bin/sh
# Roda um modelo de ponta a ponta na GPU: dados (se faltarem), estimativa, treino (retoma
# se houver checkpoint), avaliação, pacote e envio para o VPS.
# Uso (da raiz do repositório, dentro do tmux):
#   sh treino-modelos/rodar.sh resumo
#   sh treino-modelos/rodar.sh ia          # gera os textos de IA antes (PULAR_GERAR=1 pula)
# Modelos: resumo busca chaves ref area secoes ia trad base
set -eu
cd "$(dirname "$0")/.."
M="${1:-}"
case "$M" in
  resumo|busca|chaves|ref|area|secoes|ia|trad|base) ;;
  *) echo "uso: sh treino-modelos/rodar.sh <resumo|busca|chaves|ref|area|secoes|ia|trad|base>" >&2; exit 2 ;;
esac
[ -f .venv-modelos/bin/activate ] && . .venv-modelos/bin/activate
PY="${PYTHON:-python}"
if [ -z "${DESTINO_VPS:-}" ]; then
  echo "AVISO: DESTINO_VPS não definido; nada será copiado para fora da GPU (disco efêmero)." >&2
fi
if [ "$M" = ia ] && [ "${PULAR_GERAR:-0}" != 1 ]; then
  "$PY" treino-modelos/gerar_ia.py
fi
if [ ! -s "treino-modelos/dados/$M/treino.jsonl" ]; then
  "$PY" treino-modelos/dados.py --modelo "$M"
fi
"$PY" treino-modelos/treinar.py --modelo "$M" --estimar
if ls treino-modelos/saida/"$M"/checkpoints/*/estado.pt >/dev/null 2>&1; then
  "$PY" treino-modelos/treinar.py --modelo "$M" --retomar
else
  "$PY" treino-modelos/treinar.py --modelo "$M"
fi
"$PY" treino-modelos/avaliar.py --modelo "$M"
"$PY" treino-modelos/empacotar.py --modelo "$M"
if [ -n "${DESTINO_VPS:-}" ]; then
  sh treino-modelos/enviar.sh
fi
echo "[OK] $M pronto: treino-modelos/saida/dist/"
