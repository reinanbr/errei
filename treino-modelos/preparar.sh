#!/bin/sh
# Prepara a máquina GPU: confere a placa, cria o ambiente e instala as dependências.
# Uso (da raiz do repositório): sh treino-modelos/preparar.sh
set -eu
cd "$(dirname "$0")/.."

if ! command -v nvidia-smi >/dev/null 2>&1; then
  echo "ERRO: nvidia-smi não encontrado. Esta máquina não tem driver NVIDIA (ou não tem GPU)." >&2
  exit 1
fi
nvidia-smi

PY="${PYTHON:-python3}"
"$PY" -c 'import sys; assert sys.version_info >= (3, 10), "requer Python >= 3.10"'
if [ ! -d .venv-modelos ]; then
  "$PY" -m venv .venv-modelos || { echo "ERRO: instale python3-venv (apt install python3-venv)" >&2; exit 1; }
fi
. .venv-modelos/bin/activate
pip install --upgrade pip
pip install -r treino-modelos/requirements.txt

python - <<'PY'
import sys
import torch
if not torch.cuda.is_available():
    sys.exit(
        "ERRO: o PyTorch não enxerga a GPU (torch.cuda.is_available() == False).\n"
        f"      torch {torch.__version__}, CUDA do build: {torch.version.cuda}.\n"
        "      Confira se o driver (nvidia-smi) suporta CUDA 12.4 e se instalou o torch +cu124."
    )
nome = torch.cuda.get_device_name(0)
mem = torch.cuda.get_device_properties(0).total_memory / 2**30
print(f"[OK] GPU: {nome} ({mem:.0f} GB) · bf16: {torch.cuda.is_bf16_supported()} · torch {torch.__version__}")
PY
if [ ! -s treino-modelos/dados/banco.sqlite ]; then
  echo "LEMBRETE: traga o banco pronto do VPS: scp vps:/caminho/banco.sqlite treino-modelos/dados/"
fi
if [ -z "${DESTINO_VPS:-}" ]; then
  echo "LEMBRETE: defina DESTINO_VPS=usuario@host:/caminho antes de treinar (disco efêmero)."
fi
echo "[OK] ambiente pronto. Ative com: . .venv-modelos/bin/activate"
