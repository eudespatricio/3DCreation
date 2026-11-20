"""Inspecao barata de assets 3D e estimativas de textura/modular sem Blender ou GPU."""

from __future__ import annotations

import json
import logging
import math
import struct
from pathlib import Path
from typing import Any

from . import modular, qc
from .providers import blocky as blocky_provider

logger = logging.getLogger(__name__)

_EXTS_3D = {".glb", ".gltf", ".obj"}


def _tex_max_perfil(perfil: dict, qualidade: str) -> int:
    tex_max = int(
        (perfil.get("material") or {}).get("textura_max")
        or (perfil.get("validacao") or {}).get("textura_max")
        or 0
    )
    if qualidade in ("hero", "ultra") and tex_max > 0:
        tex_max = max(tex_max, 2048)
    return tex_max


def _px_bake_estimado(qualidade: str, perfil: dict) -> tuple[int, int]:
    """Espelha ``bake_pbr.px_bake_recomendado`` para estimar resolucao real sem Blender."""
    teto_perfil = _tex_max_perfil(perfil, qualidade)
    teto_max = 4096 if teto_perfil >= 4096 else 2048
    if teto_perfil > 0:
        teto_max = max(64, min(teto_max, teto_perfil))
    if qualidade == "ultra" and teto_perfil >= 4096:
        px = 4096
    elif qualidade in ("hero", "ultra"):
        px = min(2048, teto_max)
    else:
        px = min(1024, teto_max)

    if px >= 4096:
        px_sub = 4096 if qualidade == "ultra" else 2048
    elif px >= 2048:
        px_sub = 2048 if (qualidade == "ultra" or (qualidade == "hero" and teto_perfil >= 4096)) else 1024
    elif px >= 1024:
        px_sub = 1024
    else:
        px_sub = max(64, px)
    return px, px_sub


def _detalhe_alto_ativo(item: dict) -> bool:
    det = item.get("detalhe_alto")
    return isinstance(det, dict) and bool(det.get("ativo", True))


def _texturas_bake_pbr(iid: str, item: dict, perfil: dict, qualidade: str) -> list[dict]:
    """Lista mapas externos + embutidos emitidos por ``bake_pbr.executar_bake_high_low``."""
    px, px_sub = _px_bake_estimado(qualidade, perfil)
    perfil_nome = str(perfil.get("perfil") or perfil.get("_nome") or "").strip().lower()
    texturas = [
        {"id": f"{iid}:baseColor", "px": px, "canais": 4},
        {"id": f"{iid}:normal", "px": px_sub, "canais": 4},
        {"id": f"{iid}:orm", "px": px_sub, "canais": 4},
        {"id": f"{iid}:emb:0", "px": px, "canais": 4},
        {"id": f"{iid}:emb:1", "px": px_sub, "canais": 4},
        {"id": f"{iid}:emb:2", "px": px_sub, "canais": 4},
    ]
    if perfil_nome.startswith("roblox") or bool(item.get("pbr_zonas")) or _detalhe_alto_ativo(item):
        texturas.extend(
            [
                {"id": f"{iid}:roughness", "px": px_sub, "canais": 1},
                {"id": f"{iid}:metallic", "px": px_sub, "canais": 1},
            ]
        )
    return texturas


def _contar_tris_gltf_json(gltf: dict[str, Any]) -> int:
    accessors = gltf.get("accessors") or []
    tris = 0
    for mesh in gltf.get("meshes") or []:
        for prim in mesh.get("primitives") or []:
            mode = int(prim.get("mode", 4))
            count = 0
            if "indices" in prim:
                idx = int(prim["indices"])
                if 0 <= idx < len(accessors):
                    count = int(accessors[idx].get("count") or 0)
            else:
                pos_idx = (prim.get("attributes") or {}).get("POSITION")
                if pos_idx is not None and 0 <= int(pos_idx) < len(accessors):
                    count = int(accessors[int(pos_idx)].get("count") or 0)
            if mode == 4:
                tris += count // 3
            elif mode in (5, 6):
                tris += max(0, count - 2)
    return tris


def _inspecionar_gltf(
    gltf: dict[str, Any], bin_data: bytes = b"", base_dir: Path | None = None
) -> dict[str, Any]:
    meshes = gltf.get("meshes") or []
    tem_uv = any(
        "TEXCOORD_0" in (prim.get("attributes") or {})
        for mesh in meshes
        for prim in (mesh.get("primitives") or [])
    )
    tem_cor = any(
        "COLOR_0" in (prim.get("attributes") or {})
        for mesh in meshes
        for prim in (mesh.get("primitives") or [])
    )
    buffer_views = gltf.get("bufferViews") or []
    imagens_px: list[int] = []
    for img in gltf.get("images") or []:
        px = 1024
        if "bufferView" in img and bin_data:
            bv_idx = int(img["bufferView"])
            if 0 <= bv_idx < len(buffer_views):
                bv = buffer_views[bv_idx]
                off = int(bv.get("byteOffset") or 0)
                ln = int(bv.get("byteLength") or 0)
                dims = qc._validar_bytes_imagem(bin_data[off : off + ln])
                if dims:
                    px = max(dims)
        elif (
            isinstance(img.get("uri"), str)
            and base_dir is not None
            and not img["uri"].startswith("data:")
        ):
            p_img = base_dir / img["uri"]
            if p_img.is_file():
                dims = qc._validar_bytes_imagem(p_img.read_bytes())
                if dims:
                    px = max(dims)
        imagens_px.append(px)
    primitivas = max(1, sum(len(m.get("primitives") or []) for m in meshes))
    return {
        "tris": _contar_tris_gltf_json(gltf),
        "materiais": len(gltf.get("materials") or []),
        "primitivas": primitivas,
        "skinned": len(gltf.get("skins") or []) > 0,
        "tem_uv": tem_uv,
        "tem_cor_vertice": tem_cor,
        "imagens_px": imagens_px,
    }


def _inspecionar_arquivo_3d(caminho: Path) -> dict[str, Any] | None:
    """Le metadados baratos de GLB/GLTF/OBJ sem invocar Blender ou GPU."""
    if not caminho.is_file():
        return None
    suf = caminho.suffix.lower()
    try:
        if suf == ".glb":
            data = caminho.read_bytes()
            if len(data) < 20 or data[:4] != b"glTF":
                return None
            ljson = struct.unpack_from("<I", data, 12)[0]
            if 20 + ljson > len(data):
                return None
            gltf = json.loads(data[20 : 20 + ljson].decode("utf-8"))
            bin_data = b""
            pos = 20 + ljson
            if pos + 8 <= len(data):
                lbin, ctype = struct.unpack_from("<II", data, pos)
                if ctype == 0x004E4942:
                    bin_data = data[pos + 8 : pos + 8 + lbin]
            return {**_inspecionar_gltf(gltf, bin_data, caminho.parent), "formato": "glb"}
        if suf == ".gltf":
            gltf = json.loads(caminho.read_text(encoding="utf-8"))
            return {**_inspecionar_gltf(gltf, b"", caminho.parent), "formato": "gltf"}
        if suf == ".obj":
            tris = 0
            mats: set[str] = set()
            tem_uv = False
            with caminho.open("r", encoding="utf-8", errors="replace") as fh:
                for raw in fh:
                    line = raw.strip()
                    if line.startswith("f "):
                        verts = line.split()[1:]
                        if len(verts) >= 3:
                            tris += len(verts) - 2
                    elif line.startswith("vt "):
                        tem_uv = True
                    elif line.startswith("usemtl "):
                        mats.add(line[7:].strip())
            return {
                "tris": tris,
                "materiais": max(1, len(mats)),
                "primitivas": max(1, len(mats)),
                "skinned": False,
                "tem_uv": tem_uv,
                "tem_cor_vertice": False,
                "imagens_px": [],
                "formato": "obj",
            }
    except (OSError, ValueError, struct.error, KeyError, TypeError) as exc:
        logger.debug("inspecao 3d ignorada em %s: %s", caminho, exc)
        return None
    return None


def _atlas_px_blocky(caixas: list[dict]) -> int:
    pares: set[tuple[str, str]] = {(str(c.get("cor")), str(c.get("padrao"))) for c in caixas}
    celulas = max(1, len(pares) * 2)
    colunas = max(2, math.ceil(math.sqrt(celulas)))
    tam = 32
    while tam < min(256, colunas * blocky_provider.PX_CELULA):
        tam *= 2
    return tam


def _estimar_modular_tris(item: dict) -> tuple[int, str]:
    bloco = item.get("modular")
    if isinstance(bloco, dict):
        try:
            grade_lista = [int(v) for v in (bloco.get("grade") or [2, 2])]
            grade = (grade_lista[0], grade_lista[1])
            nomes = [str(m) for m in (bloco.get("modulos") or sorted(modular.CATALOGO))]
            setor = (
                int((bloco.get("setor") or [0, 0])[0]),
                int((bloco.get("setor") or [0, 0])[1]),
            )
            tamanho = float(bloco.get("tamanho_modulo") or 4.0)
            altura = float(item.get("altura_metros") or 2.4)
            seed = int(item.get("seed") or 0)
            if 0 <= setor[0] < grade[0] and 0 <= setor[1] < grade[1]:
                layout = modular.gerar_layout(grade, nomes, seed)
                caixas = modular.caixas_do_modulo(layout[setor[1]][setor[0]], tamanho, altura)
                return len(caixas) * 12, "modular_wfc"
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            logger.debug("modular_heuristica fallback: %s", exc)
    return 36, "modular_heuristica"
