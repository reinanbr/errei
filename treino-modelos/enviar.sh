#!/bin/sh
# Copia checkpoints, métricas e pacotes para o seu VPS (o disco da GPU é efêmero e a
# instância é destruída se os créditos acabarem).
#
# Uso (da raiz do repositório):
#   export DESTINO_VPS=usuario@meu-vps:/srv/errei-treino
#   sh treino-modelos/enviar.sh             # envia uma vez
#   sh treino-modelos/enviar.sh --loop 600  # a cada 10 min (deixe rodando em outro tmux)
#   ENVIAR_BANCO=1 sh treino-modelos/enviar.sh   # também o banco (textos_ia gerados na GPU)
#
# Usa rsync (incremental) e, sem rsync, scp. Chave SSH: a padrão ou SSH_CHAVE=/caminho.
set -eu
cd "$(dirname "$0")/.."

if [ -z "${DESTINO_VPS:-}" ]; then
  echo "ERRO: defina DESTINO_VPS=usuario@host:/caminho (destino no seu VPS)." >&2
  exit 1
fi
SAIDA="${SAIDA:-treino-modelos/saida}"
DADOS="${DADOS:-treino-modelos/dados}"
SSH="ssh -o StrictHostKeyChecking=accept-new${SSH_CHAVE:+ -i $SSH_CHAVE}"

enviar() {
  host="${DESTINO_VPS%%:*}"
  dir="${DESTINO_VPS#*:}"
  $SSH "$host" "mkdir -p '$dir'"
  itens=""
  for p in "$SAIDA" "treino-modelos/config" "$DADOS"/*/manifesto.json; do
    [ -e "$p" ] && itens="$itens $p"
  done
  if [ "${ENVIAR_BANCO:-0}" = 1 ] && [ -e "$DADOS/banco.sqlite" ]; then
    itens="$itens $DADOS/banco.sqlite"
  fi
  if [ -z "$itens" ]; then
    echo "nada para enviar ainda ($SAIDA não existe)"
    return 0
  fi
  if command -v rsync >/dev/null 2>&1; then
    # --relative mantém treino-modelos/... no destino; checkpoints .tmp (pela metade) ficam fora
    # shellcheck disable=SC2086
    rsync -az --relative --partial --exclude '*.tmp/' -e "$SSH" $itens "$DESTINO_VPS/"
  else
    # shellcheck disable=SC2086
    scp -r ${SSH_CHAVE:+-i "$SSH_CHAVE"} -o StrictHostKeyChecking=accept-new $itens "$DESTINO_VPS/"
  fi
  echo "[OK] $(date '+%F %T') enviado para $DESTINO_VPS"
}

if [ "${1:-}" = "--loop" ]; then
  intervalo="${2:-600}"
  while :; do
    enviar || echo "falha no envio; tento de novo em ${intervalo}s" >&2
    sleep "$intervalo"
  done
else
  enviar
fi
