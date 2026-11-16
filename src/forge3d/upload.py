"""Upload de modelo via Open Cloud Assets API (free, API key).

O tipo ``Model`` aceita ``.glb`` e importa como package de MeshParts. A key nunca entra no repo:
o comando lê ``FORGE3D_ROBLOX_API_KEY``, ``FORGE3D_ROBLOX_API_KEY_FILE`` ou
``~/.config/forge3d/roblox.key``. ``--dry-run`` monta o request sem rede e sem key.
"""

from __future__ import annotations

import json
import os
import struct
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

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
    "inferir_papel_textura_roblox",
    "remover_imagens_embutidas_glb",
    "resolver_ledger",
]


_SUFIXOS_PBR_CANAL = (
    ("_basecolor", "ColorMap"),
    ("_albedo", "ColorMap"),
    ("_colormap", "ColorMap"),
    ("_normalmap", "NormalMap"),
    ("_normal", "NormalMap"),
    ("_roughnessmap", "RoughnessMap"),
    ("_roughness", "RoughnessMap"),
    ("_orm", "OrmPacked"),
    ("_metalnessmap", "MetalnessMap"),
    ("_metalness", "MetalnessMap"),
    ("_metallic", "MetalnessMap"),
)

_GLB_MAGIC = 0x46546C67
_CHUNK_JSON = 0x4E4F534A
_CHUNK_BIN = 0x004E4942


def inferir_papel_textura_roblox(
    caminho: str | Path,
    papel_manifesto: str | None = None,
) -> str | None:
    """Resolve o canal Roblox de uma textura PBR sem mapear ``_orm`` para ``RoughnessMap``."""
    p_low = str(papel_manifesto or "").strip().lower()
    if p_low in ("orm", "ormpacked"):
        return "OrmPacked"
    aliases_estritos = {
        "textura": "ColorMap",
        "basecolor": "ColorMap",
        "albedo": "ColorMap",
        "colormap": "ColorMap",
        "color_map": "ColorMap",
        "normal": "NormalMap",
        "normalmap": "NormalMap",
        "normal_map": "NormalMap",
        "roughness": "RoughnessMap",
        "roughnessmap": "RoughnessMap",
        "roughness_map": "RoughnessMap",
        "metallic": "MetalnessMap",
        "metalness": "MetalnessMap",
        "metalnessmap": "MetalnessMap",
        "metalness_map": "MetalnessMap",
    }
    if p_low in aliases_estritos and p_low != "textura":
        return aliases_estritos[p_low]

    nome = str(caminho or "").replace("\\", "/").rsplit("/", 1)[-1]
    stem = nome.rsplit(".", 1)[0].lower()
    if stem.endswith("_orm") or stem == "orm":
        return "OrmPacked"
    for sufixo, canal in _SUFIXOS_PBR_CANAL:
        if stem.endswith(sufixo) or stem == sufixo.lstrip("_"):
            return canal
    return aliases_estritos.get(p_low)


def remover_imagens_embutidas_glb(glb_bytes: bytes) -> tuple[bytes, dict[str, Any]]:
    """Remove imagens PNG/JPEG embutidas do GLB em memoria mantendo UVs, Tangents e geometria."""
    if len(glb_bytes) < 12:
        raise ValueError("GLB truncado (< 12 bytes)")
    magic, versao, _tam = struct.unpack_from("<III", glb_bytes, 0)
    if magic != _GLB_MAGIC:
        raise ValueError("Arquivo nao possui cabecalho glTF binary (GLB)")

    offset = 12
    json_raw: bytes | None = None
    bin_raw = b""
    outros_chunks: list[tuple[int, bytes]] = []
    while offset + 8 <= len(glb_bytes):
        tam_chunk, tipo_chunk = struct.unpack_from("<II", glb_bytes, offset)
        offset += 8
        dados = glb_bytes[offset : offset + tam_chunk]
        offset += tam_chunk
        if tipo_chunk == _CHUNK_JSON and json_raw is None:
            json_raw = dados
        elif tipo_chunk == _CHUNK_BIN and not bin_raw:
            bin_raw = dados
        else:
            outros_chunks.append((tipo_chunk, dados))

    if json_raw is None:
        raise ValueError("GLB sem chunk JSON")

    gltf = json.loads(json_raw.decode("utf-8"))
    imgs_removidas = len(gltf.get("images") or [])
    texs_removidas = len(gltf.get("textures") or [])
    gltf.pop("images", None)
    gltf.pop("textures", None)
    gltf.pop("samplers", None)

    for mat in gltf.get("materials") or []:
        pbr = mat.get("pbrMetallicRoughness")
        if isinstance(pbr, dict):
            pbr.pop("baseColorTexture", None)
            pbr.pop("metallicRoughnessTexture", None)
        for campo in ("normalTexture", "occlusionTexture", "emissiveTexture"):
            mat.pop(campo, None)

    json_bytes = json.dumps(gltf, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    pad_json = (4 - (len(json_bytes) % 4)) % 4
    json_bytes_padded = json_bytes + (b" " * pad_json)

    chunks: list[tuple[int, bytes]] = [(_CHUNK_JSON, json_bytes_padded)]
    if bin_raw:
        pad_bin = (4 - (len(bin_raw) % 4)) % 4
        chunks.append((_CHUNK_BIN, bin_raw + (b"\x00" * pad_bin)))
    for tc, dc in outros_chunks:
        pad_o = (4 - (len(dc) % 4)) % 4
        chunks.append((tc, dc + (b"\x00" * pad_o)))

    total_bytes = 12 + sum(8 + len(d) for _, d in chunks)
    saida = bytearray(struct.pack("<III", magic, versao, total_bytes))
    for tc, dc in chunks:
        saida.extend(struct.pack("<II", len(dc), tc))
        saida.extend(dc)

    return bytes(saida), {
        "imagens_removidas": imgs_removidas,
        "texturas_removidas": texs_removidas,
        "bytes_antes": len(glb_bytes),
        "bytes_depois": len(saida),
    }


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
    if role.lower() == "orm":
        role = "OrmPacked"
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
    if role == "OrmPacked":
        saidas.append((logical_id, "orm", uri))
    if base_id and base_id != logical_id and role:
        saidas.append((base_id, role, uri))
        if role == "OrmPacked":
            saidas.append((base_id, "orm", uri))
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


def _multipart(
    request_json: str,
    arquivo: Path,
    content_type: str,
    *,
    conteudo_bytes: bytes | None = None,
) -> tuple[str, bytes]:
    boundary = "----forge3d" + uuid.uuid4().hex
    payload = arquivo.read_bytes() if conteudo_bytes is None else conteudo_bytes
    partes = [
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"request\"\r\n\r\n".encode(),
        request_json.encode("utf-8"),
        b"\r\n",
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"fileContent\"; filename=\"{arquivo.name}\"\r\nContent-Type: {content_type}\r\n\r\n".encode(),
        payload,
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
    strip_embedded_textures: bool = False,
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

    payload_bytes: bytes | None = None
    strip_info: dict[str, Any] | None = None
    if strip_embedded_textures and asset_type == "Model" and caminho.suffix.lower() == ".glb":
        try:
            payload_bytes, strip_info = remover_imagens_embutidas_glb(caminho.read_bytes())
        except ValueError as exc:
            raise erro_upload(f"falha ao remover texturas embutidas do GLB: {exc}") from exc

    bytes_envio = len(payload_bytes) if payload_bytes is not None else caminho.stat().st_size
    creator = _criador(creator_id, creator_type)
    nome = nome or caminho.stem
    padrao = {
        "Model": "Modelo gerado pelo Forge3D (R15/blocky).",
        "Image": "Textura gerado pelo Forge3D.",
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
        res_dry: dict[str, Any] = {
            "ok": True,
            "dry_run": True,
            "url": url,
            "arquivo": str(caminho),
            "bytes": bytes_envio,
            "content_type": content_type,
            "asset_type": asset_type,
            "creator": creator,
            "nome": nome,
            "request": request,
            "key_presente": bool(chave_api(exigir=False)),
        }
        if strip_info is not None:
            res_dry["strip_embedded_textures"] = strip_info
        return res_dry

    key = key or chave_api()
    assert key is not None
    boundary, corpo = _multipart(
        request_json,
        caminho,
        content_type,
        conteudo_bytes=payload_bytes,
    )
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
    res_ok: dict[str, Any] = {
        "ok": True,
        "dry_run": False,
        "asset_id": str(asset_id),
        "operation": op_id,
        "moderation": mod_state,
        "bytes": bytes_envio,
        "asset_type": asset_type,
        "nome": nome,
        "creator": creator,
        "url": url,
    }
    if strip_info is not None:
        res_ok["strip_embedded_textures"] = strip_info
    return res_ok
