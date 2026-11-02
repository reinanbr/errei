"""Distribuição do modelo errei-cita como asset de release do GitHub.

O tarball ``errei-cita-v1.tar.gz`` (gerado por ``scripts/empacotar-modelo.sh``) é
anexado manualmente à release, já que os pesos são grandes e têm licença própria
(CC BY-NC 2.0). ``errei modelo baixar`` o busca, confere o sha256 e extrai com
proteção contra caminhos maliciosos.
"""

from __future__ import annotations

import hashlib
import io
import os
import shutil
import tarfile
import tempfile
from pathlib import Path

from errei.citecheck import MODEL_NAME, model_dir

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


def baixar(versao: str | None = None, *, force: bool = False) -> Path:
    try:
        import httpx
    except ModuleNotFoundError as exc:
        raise ModelDownloadError("requer o extra: pip install 'errei[online]'") from exc
    dest = model_dir()
    if (dest / "config.json").is_file() and not force:
        raise ModelDownloadError(f"já instalado em {dest} (use --force)")
    base = release_base(versao)
    with httpx.Client(follow_redirects=True, timeout=60) as client:
        r = client.get(f"{base}/{ASSET}")
        if r.status_code != 200:
            raise ModelDownloadError(f"{ASSET} não encontrado em {base} (HTTP {r.status_code})")
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
    if ASSET in expected and expected[ASSET] != digest:
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
