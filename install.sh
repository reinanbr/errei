#!/bin/sh
# errei installer
# Uso:
#   Instalar:     curl -fsSL https://raw.githubusercontent.com/reinanbr/errei/main/install.sh | sh
#   Com o modelo: curl -fsSL https://raw.githubusercontent.com/reinanbr/errei/main/install.sh | sh -s -- --modelo
#   Versão fixa:  ... | sh -s -- --versao v0.6.0
#   Desinstalar:  curl -fsSL https://raw.githubusercontent.com/reinanbr/errei/main/install.sh | sh -s -- uninstall
#
# Instala num ambiente Python isolado (~/.local/share/errei/venv) e cria o comando
# ~/.local/bin/errei. Não usa sudo.

set -e

REPO="${ERREI_REPO:-reinanbr/errei}"
BINARY="errei"
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/errei"
VENV="${DATA_DIR}/venv"
BIN_DIR="${ERREI_BIN_DIR:-$HOME/.local/bin}"
TORCH_INDEX="https://download.pytorch.org/whl/cpu"

# ─── helpers ───────────────────────────────────────────────

info()  { printf '\033[1;34m::\033[0m %s\n' "$*"; }
ok()    { printf '\033[1;32m[OK]\033[0m %s\n' "$*"; }
warn()  { printf '\033[1;33m[AVISO]\033[0m %s\n' "$*"; }
die()   { printf '\033[1;31merro:\033[0m %s\n' "$*" >&2; exit 1; }

need() {
    command -v "$1" >/dev/null 2>&1 || die "'$1' é necessário e não foi encontrado no PATH"
}

ACTION="install"
WITH_MODEL=0
VERSION=""
while [ "$#" -gt 0 ]; do
    case "$1" in
        uninstall|--uninstall|remove) ACTION="uninstall" ;;
        --modelo|--model)             WITH_MODEL=1 ;;
        --versao|--version)           shift; VERSION="${1:-}" ;;
        --help|-h)
            cat <<EOF
errei installer

Instalar:
  curl -fsSL https://raw.githubusercontent.com/${REPO}/main/install.sh | sh
Instalar também os modelos locais errei-cita e errei-resumo (torch CPU, ~1,5 GB):
  curl -fsSL https://raw.githubusercontent.com/${REPO}/main/install.sh | sh -s -- --modelo
Versão específica:
  ... | sh -s -- --versao v0.6.0
Desinstalar:
  curl -fsSL https://raw.githubusercontent.com/${REPO}/main/install.sh | sh -s -- uninstall
EOF
            exit 0
            ;;
        *) die "opção desconhecida: $1 (use --help)" ;;
    esac
    shift
done

# ─── desinstalar ───────────────────────────────────────────

if [ "$ACTION" = "uninstall" ]; then
    info "Removendo ${BIN_DIR}/${BINARY} e ${VENV}..."
    rm -f "${BIN_DIR}/${BINARY}"
    rm -rf "${VENV}"
    ok "errei removido"
    printf '\n'
    info "Mantidos (apague se quiser):"
    printf '    %s   (modelo errei-cita)\n' "${DATA_DIR}/modelos"
    printf '    %s   (cache HTTP)\n' "${XDG_CACHE_HOME:-$HOME/.cache}/errei"
    printf '    %s   (LanguageTool)\n' "$HOME/.cache/language_tool_python"
    exit 0
fi

# ─── verificações ──────────────────────────────────────────

need curl
PY=""
for cand in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$cand" >/dev/null 2>&1 && \
       "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
        PY="$cand"
        break
    fi
done
[ -n "$PY" ] || die "Python >= 3.10 não encontrado (instale python3)"
ok "Python: $("$PY" --version 2>&1)"

case "$(uname -s)" in
    Linux|Darwin) ;;
    *) die "sistema não suportado: $(uname -s)" ;;
esac

# ─── versão ────────────────────────────────────────────────

if [ -z "$VERSION" ]; then
    info "Buscando a versão mais recente..."
    VERSION="$(
        curl -fsSL "https://api.github.com/repos/${REPO}/releases/latest" 2>/dev/null \
        | grep '"tag_name"' \
        | sed 's/.*"tag_name": *"\(.*\)".*/\1/'
    )" || true
    if [ -z "$VERSION" ] && command -v git >/dev/null 2>&1; then
        VERSION="$(
            git ls-remote --tags --sort=-v:refname "https://github.com/${REPO}.git" 2>/dev/null \
            | grep -oE 'refs/tags/v[0-9]+\.[0-9]+\.[0-9]+$' \
            | head -1 \
            | sed 's|refs/tags/||'
        )" || true
    fi
fi
[ -n "$VERSION" ] || die "não foi possível determinar a versão (há release em ${REPO}?)"
ok "Versão: $VERSION"

# ─── download + checksum ───────────────────────────────────

TMPDIR_E="$(mktemp -d)"
trap 'rm -rf "$TMPDIR_E"' EXIT

PKGVER="${VERSION#v}"
WHEEL="errei-${PKGVER}-py3-none-any.whl"
BASE_URL="${ERREI_RELEASE_URL:-https://github.com/${REPO}/releases/download/${VERSION}}"

info "Baixando ${WHEEL}..."
SOURCE=""
if curl -fsSL "${BASE_URL}/${WHEEL}" -o "${TMPDIR_E}/${WHEEL}"; then
    if curl -fsSL "${BASE_URL}/sha256sums.txt" -o "${TMPDIR_E}/sha256sums.txt" 2>/dev/null; then
        expected="$(grep " ${WHEEL}\$" "${TMPDIR_E}/sha256sums.txt" | awk '{print $1}')"
        if command -v sha256sum >/dev/null 2>&1; then
            actual="$(sha256sum "${TMPDIR_E}/${WHEEL}" | awk '{print $1}')"
        else
            actual="$(shasum -a 256 "${TMPDIR_E}/${WHEEL}" | awk '{print $1}')"
        fi
        [ -n "$expected" ] && [ "$expected" != "$actual" ] && die "checksum não confere para ${WHEEL}"
        [ -n "$expected" ] && ok "Checksum verificado"
    else
        warn "sha256sums.txt indisponível; checksum não verificado"
    fi
    SOURCE="file://${TMPDIR_E}/${WHEEL}"
else
    warn "Download do wheel falhou; instalando a partir do código-fonte da tag ${VERSION}"
    SOURCE="git+https://github.com/${REPO}.git@${VERSION}"
    need git
fi

# ─── instalação ────────────────────────────────────────────

EXTRAS="all"
[ "$WITH_MODEL" = "1" ] && EXTRAS="all,modelo"

info "Criando ambiente isolado em ${VENV}..."
rm -rf "${VENV}"
mkdir -p "${DATA_DIR}" "${BIN_DIR}"
if command -v uv >/dev/null 2>&1; then
    uv venv --quiet --python "$PY" "${VENV}"
    PIP="uv pip install --quiet --python ${VENV}/bin/python"
    TORCH_ARGS="--extra-index-url ${TORCH_INDEX} --index-strategy unsafe-best-match"
else
    "$PY" -m venv "${VENV}"
    "${VENV}/bin/python" -m pip install --quiet --upgrade pip
    PIP="${VENV}/bin/python -m pip install --quiet"
    TORCH_ARGS="--extra-index-url ${TORCH_INDEX}"
fi

if [ "$WITH_MODEL" = "1" ]; then
    info "Instalando errei[${EXTRAS}] (inclui torch CPU; pode levar alguns minutos)..."
    # shellcheck disable=SC2086
    $PIP $TORCH_ARGS "errei[${EXTRAS}] @ ${SOURCE}"
else
    info "Instalando errei[${EXTRAS}]..."
    # shellcheck disable=SC2086
    $PIP "errei[${EXTRAS}] @ ${SOURCE}"
fi

ln -sf "${VENV}/bin/errei" "${BIN_DIR}/${BINARY}"
ok "Comando: ${BIN_DIR}/${BINARY}"

if [ "$WITH_MODEL" = "1" ]; then
    info "Baixando os modelos locais (errei-cita, errei-resumo)..."
    if ERREI_REPO="${REPO}" "${VENV}/bin/errei" modelo baixar --versao "${VERSION}"; then
        ok "Modelos instalados"
    else
        warn "Algum modelo não foi baixado; o errei funciona sem eles (veja 'errei modelo info')"
    fi
fi

# ─── verificação ───────────────────────────────────────────

ok "Versão: $("${BIN_DIR}/${BINARY}" --version)"
case ":$PATH:" in
    *":${BIN_DIR}:"*) ;;
    *) warn "${BIN_DIR} não está no PATH. Adicione ao ~/.bashrc:"
       printf '    export PATH="%s:$PATH"\n' "${BIN_DIR}" ;;
esac

printf '\n'
info "Próximos passos:"
printf '    errei doctor --download     # Java/LanguageTool (gramática), hunspell, modelo\n'
printf '    cd /caminho/do/artigo\n'
printf '    errei .                     # auditoria offline\n'
printf '    errei . --online --pdf relatorio.pdf\n'
printf '\n'
