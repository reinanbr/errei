#!/bin/sh
# Prepara a máquina GPU: confere a placa, cria o ambiente e instala as dependências.
# Uso (da raiz do repositório): sh treino-gpu/preparar.sh
set -eu
cd "$(dirname "$0")/.."

if ! command -v nvidia-smi >/dev/null 2>&1; then
  echo "ERRO: nvidia-smi não encontrado. Esta máquina não tem driver NVIDIA (ou não tem GPU)." >&2
  echo "      Contrate uma instância com GPU e o driver instalado." >&2
  exit 1
fi
nvidia-smi

PY="${PYTHON:-python3}"
"$PY" -c 'import sys; assert sys.version_info >= (3, 10), "requer Python >= 3.10"'
if [ ! -d .venv-gpu ]; then
  "$PY" -m venv .venv-gpu || { echo "ERRO: instale python3-venv (apt install python3-venv)" >&2; exit 1; }
fi
. .venv-gpu/bin/activate
pip install --upgrade pip
pip install -r treino-gpu/requirements.txt

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
echo "[OK] ambiente pronto. Ative com: . .venv-gpu/bin/activate"
if [ -z "${DESTINO_VPS:-}" ]; then
  echo "LEMBRETE: defina DESTINO_VPS=usuario@host:/caminho antes de treinar (disco efêmero)."
fi
