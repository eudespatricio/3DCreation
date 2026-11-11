"""Upload de modelo via Open Cloud Assets API (free, API key).

O tipo ``Model`` aceita ``.glb`` e importa como package de MeshParts. A key nunca entra no repo:
o comando lê ``FORGE3D_ROBLOX_API_KEY``, ``FORGE3D_ROBLOX_API_KEY_FILE`` ou
``~/.config/forge3d/roblox.key``. ``--dry-run`` monta o request sem rede e sem key.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from .errors import erro_recurso, erro_upload

API_PADRAO = "https://apis.roblox.com"
TAMANHO_MAX = 20 * 1024 * 1024
TIPOS_MODEL = {
    ".glb": "model/gltf-binary",
    ".gltf": "model/gltf+json",
    ".fbx": "model/fbx",
    ".rbxm": "model/x-rbxm",
    ".rbxmx": "model/x-rbxm",
}
TIPOS_ANIMACAO = {
    ".rbxm": "model/x-rbxm",
    ".rbxmx": "model/x-rbxm",
}
TIPOS_IMAGEM = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".bmp": "image/bmp",
    ".tga": "image/tga",
}

__all__ = ["chave_api", "executar"]


def _arquivo_chave() -> Path | None:
    caminho = os.environ.get("FORGE3D_ROBLOX_API_KEY_FILE")
    if caminho:
        return Path(caminho).expanduser()
    padrao = Path.home() / ".config" / "forge3d" / "roblox.key"
    return padrao if padrao.is_file() else None


def chave_api(exigir: bool = True) -> str | None:
    valor = (os.environ.get("FORGE3D_ROBLOX_API_KEY") or "").strip()
    if valor:
        return valor
    caminho = _arquivo_chave()
    if caminho is not None:
        if not caminho.is_file():
            raise erro_upload(f"arquivo da key nao existe: {caminho}")
        if os.name == "posix" and (caminho.stat().st_mode & 0o077) != 0:
            raise erro_upload(
                f"permissao insegura em {caminho} (use chmod 600)", arquivo=str(caminho)
            )
        valor = caminho.read_text(encoding="utf-8").strip()
        if valor:
            return valor
    if exigir:
        raise erro_upload(
            "defina FORGE3D_ROBLOX_API_KEY, FORGE3D_ROBLOX_API_KEY_FILE "
            "ou ~/.config/forge3d/roblox.key"
        )
    return None


def _criador(creator_id: str | None, creator_type: str | None) -> dict:
    creator_id = creator_id or os.environ.get("FORGE3D_ROBLOX_CREATOR_ID")
    creator_type = creator_type or os.environ.get("FORGE3D_ROBLOX_CREATOR_TYPE") or "user"
    if not creator_id:
        raise erro_upload("defina FORGE3D_ROBLOX_CREATOR_ID ou --creator-id")
    creator_type = str(creator_type).lower()
    if creator_type not in ("user", "group"):
        raise erro_upload("creator-type precisa ser user ou group")
    chave = "userId" if creator_type == "user" else "groupId"
    return {chave: str(creator_id)}


def _multipart(request_json: str, arquivo: Path, content_type: str) -> tuple[str, bytes]:
    boundary = "----forge3d" + uuid.uuid4().hex
    partes = [
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"request\"\r\n\r\n".encode(),
        request_json.encode("utf-8"),
        b"\r\n",
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"fileContent\"; filename=\"{arquivo.name}\"\r\nContent-Type: {content_type}\r\n\r\n".encode(),
        arquivo.read_bytes(),
        f"\r\n--{boundary}--\r\n".encode(),
    ]
    return boundary, b"".join(partes)


def _http(url: str, key: str, dados: bytes | None = None, content_type: str | None = None) -> dict:
    req = urllib.request.Request(url, data=dados, method="POST" if dados is not None else "GET")
    req.add_header("x-api-key", key)
    if content_type:
        req.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(req, timeout=90) as resposta:
            return json.loads(resposta.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        corpo = exc.read().decode("utf-8", "replace")[:600]
        if exc.code == 429:
            raise erro_recurso(f"Open Cloud rate limit (HTTP 429): {corpo}") from exc
        raise erro_upload(f"Open Cloud HTTP {exc.code}: {corpo}", status=exc.code) from exc
    except urllib.error.URLError as exc:
        raise erro_upload(f"falha de rede no Open Cloud: {exc.reason}") from exc


def executar(
    arquivo: str | Path,
    *,
    asset_type: str = "Model",
    nome: str | None = None,
    descricao: str | None = None,
    creator_id: str | None = None,
    creator_type: str | None = None,
    api_url: str | None = None,
    key: str | None = None,
    dry_run: bool = False,
    intervalo: float = 2.0,
    max_espera: float = 300.0,
) -> dict:
    caminho = Path(arquivo).expanduser()
    if not caminho.is_file():
        raise erro_upload(f"GLB nao encontrado: {caminho}")
    if caminho.stat().st_size > TAMANHO_MAX:
        raise erro_upload(f"arquivo maior que 20 MB: {caminho.stat().st_size} B")
    if asset_type == "Model":
        content_type = TIPOS_MODEL.get(caminho.suffix.lower())
        if content_type is None:
            raise erro_upload(f"formato nao suportado para Model: {caminho.suffix}")
    elif asset_type in ("Image", "Decal"):
        content_type = TIPOS_IMAGEM.get(caminho.suffix.lower())
        if content_type is None:
            raise erro_upload(f"formato nao suportado para {asset_type}: {caminho.suffix}")
    elif asset_type == "Animation":
        content_type = TIPOS_ANIMACAO.get(caminho.suffix.lower())
        if content_type is None:
            raise erro_upload(f"formato nao suportado para Animation: {caminho.suffix}")
    else:
        raise erro_upload(f"asset_type nao suportado: {asset_type}")
    if intervalo <= 0 or max_espera <= 0:
        raise erro_upload("intervalo e max-espera precisam ser > 0")

    creator = _criador(creator_id, creator_type)
    nome = nome or caminho.stem
    padrao = {
        "Model": "Modelo gerado pelo Forge3D (R15/blocky).",
        "Image": "Textura gerada pelo Forge3D.",
        "Decal": "Textura gerada pelo Forge3D.",
        "Animation": "Animacao gerada pelo Forge3D (clipe base).",
    }
    descricao = descricao or padrao.get(asset_type, "Asset gerado pelo Forge3D.")
    request = {
        "assetType": asset_type,
        "displayName": nome,
        "description": descricao,
        "creationContext": {"creator": creator},
    }
    request_json = json.dumps(request, separators=(",", ":"))
    base = (api_url or os.environ.get("FORGE3D_ROBLOX_API_URL") or API_PADRAO).rstrip("/")
    partes_url = urllib.parse.urlsplit(base)
    if partes_url.scheme != "https" and not (
        partes_url.scheme == "http" and partes_url.hostname in ("127.0.0.1", "localhost", "::1")
    ):
        raise erro_upload(f"URL Open Cloud exige https:// (recebido: {base})")
    url = f"{base}/assets/v1/assets"
    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "url": url,
            "arquivo": str(caminho),
            "bytes": caminho.stat().st_size,
            "content_type": content_type,
            "asset_type": asset_type,
            "creator": creator,
            "nome": nome,
            "request": request,
            "key_presente": bool(chave_api(exigir=False)),
        }

    key = key or chave_api()
    boundary, corpo = _multipart(request_json, caminho, content_type)
    resposta = _http(url, key, corpo, f"multipart/form-data; boundary={boundary}")
    operacao = str(resposta.get("path") or "")
    if not operacao.startswith("operations/"):
        raise erro_upload(f"resposta sem operation: {resposta}")
    op_id = operacao.split("/", 1)[1]
    inicio = time.time()
    while True:
        op = _http(f"{base}/assets/v1/operations/{op_id}", key)
        if op.get("done"):
            break
        if time.time() - inicio > max_espera:
            raise erro_upload(f"upload nao terminou em {max_espera:.0f}s (operation {op_id})")
        time.sleep(intervalo)

    if op.get("error"):
        raise erro_upload(f"upload falhou: {op['error']}")
    asset = op.get("response") or {}
    asset_id = asset.get("assetId")
    if not asset_id:
        raise erro_upload(f"operation sem assetId: {op}")
    return {
        "ok": True,
        "dry_run": False,
        "asset_id": str(asset_id),
        "operation": op_id,
        "moderation": (asset.get("moderationResult") or {}).get("moderationState"),
        "bytes": caminho.stat().st_size,
        "asset_type": asset_type,
        "nome": nome,
        "creator": creator,
        "url": url,
    }
