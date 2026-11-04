"""Distribuição dos modelos locais do errei como assets de release do GitHub.

Modelos:

* ``errei-cita-v1``: atribuição de citações (pesos CC BY-NC 2.0, herdada do SciFact);
* ``errei-cita-v2``: idem, treinado só com dados de uso comercial permitido (treino-gpu/);
* ``errei-resumo-v1``: papel das frases do resumo, NBR 6028 (Apache-2.0).

Os tarballs (gerados por ``scripts/empacotar-modelo.sh``) ficam na release fixa
``modelos``, para não serem reenviados a cada versão do errei. Por compatibilidade,
também são procurados na release informada em ``--versao`` e na mais recente.
``errei modelo baixar`` confere o sha256 e extrai com proteção contra caminhos
maliciosos.
"""

from __future__ import annotations

import hashlib
import io
import os
import shutil
import tarfile
import tempfile
from collections.abc import Callable
from pathlib import Path

from errei import citecheck, resumocheck

MODELOS: dict[str, Callable[[], Path]] = {
    citecheck.MODEL_NAME: lambda: (
        citecheck.model_dir()
        if os.environ.get("ERREI_MODEL_DIR")
        else citecheck.dir_de(citecheck.MODEL_NAME)
    ),
    citecheck.MODEL_V2: lambda: citecheck.dir_de(citecheck.MODEL_V2),
    resumocheck.MODEL_NAME: resumocheck.model_dir,
}
# o que 'errei modelo baixar' sem --nome baixa (o v2 entra quando for publicado)
PADRAO_BAIXAR = (citecheck.MODEL_NAME, resumocheck.MODEL_NAME)
DESCRICAO = {
    citecheck.MODEL_NAME: "atribuição de citações (frase do artigo × resumo da obra)",
    citecheck.MODEL_V2: "atribuição de citações, v2 (sem dados NC; frase × trecho do texto)",
    resumocheck.MODEL_NAME: "papel das frases do resumo: objetivo, método, resultados (NBR 6028)",
}
MODELOS_TAG = os.environ.get("ERREI_MODELOS_TAG", "modelos")
MODEL_NAME = citecheck.MODEL_NAME  # compatibilidade
ASSET = f"{MODEL_NAME}.tar.gz"
MAX_BYTES = 2 * 1024 * 1024 * 1024


class ModelDownloadError(RuntimeError):
    pass


def release_base(versao: str | None) -> str:
    override = os.environ.get("ERREI_RELEASE_URL")
    if override:
        return override.rstrip("/")
    repo = os.environ.get("ERREI_REPO", "reinanbr/errei")
    if versao:
        return f"https://github.com/{repo}/releases/download/{versao}"
    return f"https://github.com/{repo}/releases/latest/download"


def _safe_extract(data: bytes, dest: Path) -> None:
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        root = dest.resolve()
        for m in tar.getmembers():
            target = (dest / m.name).resolve()
            if not (target == root or root in target.parents):
                raise ModelDownloadError(f"caminho inseguro no pacote: {m.name}")
            if m.issym() or m.islnk() or m.isdev():
                raise ModelDownloadError(f"tipo de arquivo não permitido no pacote: {m.name}")
        # membros validados acima; o filtro "data" (Python >= 3.12) é uma segunda barreira
        if hasattr(tarfile, "data_filter"):
            tar.extractall(dest, filter="data")
        else:  # pragma: no cover - Python < 3.12
            tar.extractall(dest)


def _bases(versao: str | None) -> list[str]:
    if os.environ.get("ERREI_RELEASE_URL"):
        return [release_base(None)]
    out = [release_base(MODELOS_TAG)]
    if versao:
        out.append(release_base(versao))
    out.append(release_base(None))
    return list(dict.fromkeys(out))


def baixar(versao: str | None = None, *, force: bool = False, nome: str = MODEL_NAME) -> Path:
    try:
        import httpx
    except ModuleNotFoundError as exc:
        raise ModelDownloadError("requer o extra: pip install 'errei[online]'") from exc
    if nome not in MODELOS:
        raise ModelDownloadError(f"modelo desconhecido: {nome} (opções: {', '.join(MODELOS)})")
    asset = f"{nome}.tar.gz"
    dest = MODELOS[nome]()
    if (dest / "config.json").is_file() and not force:
        raise ModelDownloadError(f"já instalado em {dest} (use --force)")
    with httpx.Client(follow_redirects=True, timeout=60) as client:
        base, r, tried = "", None, []
        for base in _bases(versao):
            r = client.get(f"{base}/{asset}")
            tried.append(f"{base} (HTTP {r.status_code})")
            if r.status_code == 200:
                break
        if r is None or r.status_code != 200:
            raise ModelDownloadError(f"{asset} não encontrado em: " + "; ".join(tried))
        data = r.content
        if len(data) > MAX_BYTES:
            raise ModelDownloadError("pacote do modelo grande demais")
        expected: dict[str, str] = {}
        for name in ("sha256sums-modelo.txt", "sha256sums.txt"):
            sums = client.get(f"{base}/{name}")
            if sums.status_code == 200:
                for ln in sums.text.splitlines():
                    parts = ln.split()
                    if len(parts) == 2:
                        expected.setdefault(parts[1], parts[0])
    digest = hashlib.sha256(data).hexdigest()
    if asset in expected and expected[asset] != digest:
        raise ModelDownloadError("checksum do modelo não confere")
    with tempfile.TemporaryDirectory() as tmp:
        _safe_extract(data, Path(tmp))
        found = next(Path(tmp).rglob("config.json"), None)
        if found is None:
            raise ModelDownloadError("pacote sem config.json")
        if dest.exists():
            shutil.rmtree(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(found.parent, dest)
    return dest
