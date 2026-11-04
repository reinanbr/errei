#!/bin/sh
# Copia checkpoints, métricas e o pacote para o seu VPS (o disco da GPU é efêmero e a
# instância é destruída se os créditos acabarem).
#
# Uso (da raiz do repositório):
#   export DESTINO_VPS=usuario@meu-vps:/srv/errei-treino
#   sh treino-gpu/enviar.sh             # envia uma vez
#   sh treino-gpu/enviar.sh --loop 600  # envia a cada 10 min (deixe rodando em outro tmux)
#
# Usa rsync (incremental) e, sem rsync, scp. Chave SSH: a padrão ou SSH_CHAVE=/caminho.
set -eu
cd "$(dirname "$0")/.."

if [ -z "${DESTINO_VPS:-}" ]; then
  echo "ERRO: defina DESTINO_VPS=usuario@host:/caminho (destino no seu VPS)." >&2
  exit 1
fi
SAIDA="${SAIDA:-treino-gpu/saida}"
DADOS="${DADOS:-treino-gpu/dados}"
SSH="ssh -o StrictHostKeyChecking=accept-new${SSH_CHAVE:+ -i $SSH_CHAVE}"

enviar() {
  host="${DESTINO_VPS%%:*}"
  dir="${DESTINO_VPS#*:}"
  $SSH "$host" "mkdir -p '$dir'"
  itens=""
  for p in "$SAIDA" "$DADOS/manifesto.json" "treino-gpu/config"; do
    [ -e "$p" ] && itens="$itens $p"
  done
  if [ -z "$itens" ]; then
    echo "nada para enviar ainda ($SAIDA não existe)"
    return 0
  fi
  if command -v rsync >/dev/null 2>&1; then
    # --relative mantém treino-gpu/... no destino; checkpoints .tmp (pela metade) ficam fora
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
