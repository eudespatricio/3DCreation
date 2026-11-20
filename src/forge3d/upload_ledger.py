"""Resolucao de assetIds do Roblox a partir do ledger de uploads."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from . import paths
from .upload_glb import _SUFIXOS_PBR_CANAL

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
