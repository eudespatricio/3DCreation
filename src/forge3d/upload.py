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
from collections.abc import Mapping
from pathlib import Path

from . import paths
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

__all__ = [
    "asset_ids_do_ledger",
    "chave_api",
    "executar",
    "formatar_rbxassetid",
    "resolver_ledger",
]


_SUFIXOS_PBR_CANAL = (
    ("_basecolor", "ColorMap"),
    ("_albedo", "ColorMap"),
    ("_colormap", "ColorMap"),
    ("_normal", "NormalMap"),
    ("_normalmap", "NormalMap"),
    ("_roughness", "RoughnessMap"),
    ("_roughnessmap", "RoughnessMap"),
    ("_orm", "RoughnessMap"),
    ("_metalness", "MetalnessMap"),
    ("_metallic", "MetalnessMap"),
    ("_metalnessmap", "MetalnessMap"),
)


def formatar_rbxassetid(valor: str | int) -> str:
    """Normaliza um ID numerico ou URI para ``rbxassetid://<id>``."""
    limpo = str(valor).strip()
    if not limpo:
        return ""
    if limpo.startswith("rbxassetid://"):
        return limpo
    return f"rbxassetid://{limpo}"


def _inferir_role_e_base(rec: Mapping, logical_id: str, arquivo: str) -> tuple[str, str | None]:
    role = str(rec.get("role") or rec.get("papel") or rec.get("canal") or "").strip()
    base_id: str | None = None
    nome_arq = Path(arquivo).name.lower() if arquivo else ""
    id_low = logical_id.lower()

    for sufixo, canal in _SUFIXOS_PBR_CANAL:
        if id_low.endswith(sufixo) and len(logical_id) > len(sufixo):
            base_id = logical_id[: -len(sufixo)]
            if not role:
                role = canal
            break

    if not role and nome_arq:
        stem_arq = Path(nome_arq).stem
        for sufixo, canal in _SUFIXOS_PBR_CANAL:
            if stem_arq.endswith(sufixo) or stem_arq == sufixo.lstrip("_"):
                role = canal
                break
        if not role:
            ext = Path(nome_arq).suffix
            if ext in TIPOS_MODEL:
                role = "mesh"
            elif ext in TIPOS_IMAGEM:
                role = "textura"

    if not role:
        asset_type = str(rec.get("asset_type") or rec.get("assetType") or "").strip().lower()
        if asset_type == "model":
            role = "mesh"
        elif asset_type == "animation":
            role = "animacao"
        elif asset_type in ("image", "decal"):
            role = "textura"

    return role, base_id


def _extrair_entradas_ledger(rec: object) -> list[tuple[str, str, str]]:
    if not isinstance(rec, Mapping) or rec.get("evento") == "run":
        return []
    raw_rbx = (
        rec.get("rbxassetid")
        or rec.get("roblox_asset_id")
        or rec.get("asset_id")
        or rec.get("assetId")
        or (rec.get("roblox") or {}).get("asset_id")
        or (rec.get("roblox") or {}).get("assetId")
        or (rec.get("upload") or {}).get("asset_id")
        or (rec.get("upload") or {}).get("assetId")
    )
    if raw_rbx is None or not str(raw_rbx).strip():
        return []
    uri = formatar_rbxassetid(str(raw_rbx))

    arquivo = str(rec.get("arquivo") or "").strip()
    logical_id = str(
        rec.get("id")
        or rec.get("item_id")
        or rec.get("forge3d_id")
        or rec.get("nome")
        or rec.get("name")
        or rec.get("displayName")
        or ""
    ).strip()
    if not logical_id and arquivo:
        logical_id = Path(arquivo).stem
    if not logical_id:
        return []

    role, base_id = _inferir_role_e_base(rec, logical_id, arquivo)
    saidas = [(logical_id, role, uri)]
    if base_id and base_id != logical_id and role:
        saidas.append((base_id, role, uri))
    return saidas


def resolver_ledger(
    ledger: str | Path | None = None,
    *,
    asset_id: str | None = None,
) -> dict[tuple[str, str], str]:
    """Resolve mapeamentos ``(asset_id, role) -> rbxassetid://<id>`` a partir de ``ledger.jsonl``."""
    caminho = paths.arquivo_ledger() if ledger is None else Path(ledger).expanduser()
    if not caminho.is_file():
        return {}
    mapa: dict[tuple[str, str], str] = {}
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        texto = linha.strip()
        if not texto:
            continue
        try:
            rec = json.loads(texto)
        except ValueError:
            continue
        for lid, role, uri in _extrair_entradas_ledger(rec):
            if asset_id is not None and lid != asset_id:
                continue
            mapa[(lid, role)] = uri
    return mapa


def asset_ids_do_ledger(
    item_id: str,
    ledger: str | Path | None = None,
) -> dict[str, str]:
    """Retorna ``{role: rbxassetid://<id>}`` para ``item_id`` lido do ledger de uploads."""
    entradas = resolver_ledger(ledger, asset_id=item_id)
    return {role: uri for (_lid, role), uri in entradas.items() if role}


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


def _http(
    url: str,
    key: str,
    dados: bytes | None = None,
    content_type: str | None = None,
    *,
    tentativas: int = 3,
) -> dict:
    tentativas = max(1, int(tentativas))
    for tentativa in range(tentativas):
        req = urllib.request.Request(
            url, data=dados, method="POST" if dados is not None else "GET"
        )
        req.add_header("x-api-key", key)
        if content_type:
            req.add_header("Content-Type", content_type)
        try:
            with urllib.request.urlopen(req, timeout=90) as resposta:
                return json.loads(resposta.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            corpo = exc.read().decode("utf-8", "replace")[:600]
            if exc.code in (429, 500, 502, 503, 504) and tentativa + 1 < tentativas:
                espera = float(2**tentativa)
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                if retry_after:
                    try:
                        espera = min(10.0, max(0.1, float(retry_after)))
                    except ValueError:
                        pass
                time.sleep(espera)
                continue
            if exc.code == 429:
                raise erro_recurso(f"Open Cloud rate limit (HTTP 429): {corpo}") from exc
            raise erro_upload(f"Open Cloud HTTP {exc.code}: {corpo}", status=exc.code) from exc
        except urllib.error.URLError as exc:
            if tentativa + 1 < tentativas:
                time.sleep(float(2**tentativa))
                continue
            raise erro_upload(f"falha de rede no Open Cloud: {exc.reason}") from exc
    raise erro_upload("Open Cloud: tentativas esgotadas")


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
    assert key is not None
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
    mod_state = (asset.get("moderationResult") or {}).get("moderationState")
    if mod_state in ("MODERATION_STATE_REJECTED", "Rejected", "MODERATION_REJECTED"):
        raise erro_upload(f"asset rejeitado pela moderacao Roblox ({mod_state})")
    asset_id = asset.get("assetId")
    if not asset_id:
        raise erro_upload(f"operation sem assetId: {op}")
    return {
        "ok": True,
        "dry_run": False,
        "asset_id": str(asset_id),
        "operation": op_id,
        "moderation": mod_state,
        "bytes": caminho.stat().st_size,
        "asset_type": asset_type,
        "nome": nome,
        "creator": creator,
        "url": url,
    }
