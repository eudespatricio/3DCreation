"""Utilitarios GLB e mapeamento de canais PBR para upload Open Cloud."""

from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Any

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


def _coletar_buffer_views_referenciados(obj: Any, encontrados: set[int]) -> None:
    if isinstance(obj, dict):
        for chave, valor in obj.items():
            if chave == "bufferView" and isinstance(valor, int) and not isinstance(valor, bool):
                encontrados.add(valor)
            else:
                _coletar_buffer_views_referenciados(valor, encontrados)
    elif isinstance(obj, list):
        for item in obj:
            _coletar_buffer_views_referenciados(item, encontrados)


def _reescrever_buffer_views(obj: Any, old_to_new: dict[int, int]) -> None:
    if isinstance(obj, dict):
        for chave, valor in obj.items():
            if (
                chave == "bufferView"
                and isinstance(valor, int)
                and not isinstance(valor, bool)
                and valor in old_to_new
            ):
                obj[chave] = old_to_new[valor]
            else:
                _reescrever_buffer_views(valor, old_to_new)
    elif isinstance(obj, list):
        for item in obj:
            _reescrever_buffer_views(item, old_to_new)


def _compactar_bin(gltf: dict[str, Any], bin_raw: bytes, img_bvs: set[int]) -> bytes:
    """Remove bufferViews exclusivos de imagens e compacta o chunk BIN mantendo alinhamento 4B."""
    bvs = gltf.get("bufferViews")
    if not isinstance(bvs, list) or not bvs:
        return bin_raw

    sobreviventes_refs: set[int] = set()
    for chave, valor in gltf.items():
        if chave not in ("bufferViews", "buffers"):
            _coletar_buffer_views_referenciados(valor, sobreviventes_refs)

    removiveis = {i for i in img_bvs if 0 <= i < len(bvs)} - sobreviventes_refs
    if not removiveis:
        for idx, bv in enumerate(bvs):
            if not isinstance(bv, dict) or bv.get("buffer", 0) != 0:
                continue
            raw_off = int(bv.get("byteOffset", 0) or 0)
            raw_len = int(bv.get("byteLength", 0) or 0)
            if raw_off < 0 or raw_len < 0 or raw_off + raw_len > len(bin_raw):
                raise ValueError(
                    f"bufferView {idx} fora dos limites do chunk BIN ({raw_off}+{raw_len} > {len(bin_raw)})"
                )
        return bin_raw

    old_to_new: dict[int, int] = {}
    new_bvs: list[Any] = []
    for old_idx, bv in enumerate(bvs):
        if old_idx in removiveis:
            continue
        old_to_new[old_idx] = len(new_bvs)
        new_bvs.append(dict(bv) if isinstance(bv, dict) else bv)

    intervalos: list[tuple[int, int, int]] = []
    for new_idx, bv in enumerate(new_bvs):
        if not isinstance(bv, dict) or bv.get("buffer", 0) != 0:
            continue
        raw_off = int(bv.get("byteOffset", 0) or 0)
        raw_len = int(bv.get("byteLength", 0) or 0)
        if raw_off < 0 or raw_len < 0 or raw_off + raw_len > len(bin_raw):
            raise ValueError(
                f"bufferView {new_idx} fora dos limites do chunk BIN ({raw_off}+{raw_len} > {len(bin_raw)})"
            )
        if raw_len == 0:
            bv["byteOffset"] = 0
        else:
            intervalos.append((raw_off, raw_off + raw_len, new_idx))

    intervalos.sort(key=lambda item: (item[0], item[1]))
    mesclados: list[tuple[int, int, list[int]]] = []
    for inicio, fim, bv_idx in intervalos:
        if mesclados and inicio < mesclados[-1][1]:
            m_ini, m_fim, m_bvs = mesclados[-1]
            m_bvs.append(bv_idx)
            if fim > m_fim:
                mesclados[-1] = (m_ini, fim, m_bvs)
        else:
            mesclados.append((inicio, fim, [bv_idx]))

    new_bin = bytearray()
    for m_ini, m_fim, m_bvs in mesclados:
        pad = (4 - (len(new_bin) % 4)) % 4
        if pad:
            new_bin.extend(b"\x00" * pad)
        if m_ini % 4:
            new_bin.extend(b"\x00" * (m_ini % 4))
        dest_inicio = len(new_bin)
        new_bin.extend(bin_raw[m_ini:m_fim])
        for bv_idx in m_bvs:
            bv = new_bvs[bv_idx]
            old_off = int(bv.get("byteOffset", 0) or 0)
            bv["byteOffset"] = dest_inicio + (old_off - m_ini)

    pad_final = (4 - (len(new_bin) % 4)) % 4
    if pad_final:
        new_bin.extend(b"\x00" * pad_final)

    if new_bvs:
        gltf["bufferViews"] = new_bvs
    else:
        gltf.pop("bufferViews", None)

    for chave, valor in gltf.items():
        if chave not in ("bufferViews", "buffers"):
            _reescrever_buffer_views(valor, old_to_new)

    buffers = gltf.get("buffers")
    if isinstance(buffers, list) and buffers and isinstance(buffers[0], dict):
        buffers[0]["byteLength"] = len(new_bin)

    return bytes(new_bin)


def remover_imagens_embutidas_glb(glb_bytes: bytes) -> tuple[bytes, dict[str, Any]]:
    """Remove imagens PNG/JPEG embutidas do GLB em memoria mantendo UVs, Tangents e geometria."""
    if len(glb_bytes) < 12:
        raise ValueError("GLB truncado (< 12 bytes)")
    magic, versao, tam_total = struct.unpack_from("<III", glb_bytes, 0)
    if magic != _GLB_MAGIC:
        raise ValueError("Arquivo nao possui cabecalho glTF binary (GLB)")
    if versao != 2:
        raise ValueError(f"Versao GLB nao suportada: {versao}")
    if tam_total < 12 or tam_total != len(glb_bytes):
        raise ValueError(
            f"GLB truncado ou tamanho inconsistente (header={tam_total}, real={len(glb_bytes)})"
        )

    offset = 12
    json_raw: bytes | None = None
    bin_raw = b""
    outros_chunks: list[tuple[int, bytes]] = []
    while offset < len(glb_bytes):
        if offset + 8 > len(glb_bytes):
            raise ValueError("GLB truncado no cabecalho de chunk")
        tam_chunk, tipo_chunk = struct.unpack_from("<II", glb_bytes, offset)
        offset += 8
        if offset + tam_chunk > len(glb_bytes):
            raise ValueError(
                f"Chunk GLB truncado ({offset}+{tam_chunk} > {len(glb_bytes)})"
            )
        dados = glb_bytes[offset : offset + tam_chunk]
        offset += tam_chunk
        if tipo_chunk == _CHUNK_JSON and json_raw is None:
            json_raw = dados
        elif tipo_chunk == _CHUNK_BIN and not bin_raw:
            bin_raw = dados
        else:
            outros_chunks.append((tipo_chunk, dados))

    if offset != len(glb_bytes):
        raise ValueError(f"GLB com tamanho inconsistente apos chunks ({offset} != {len(glb_bytes)})")

    if json_raw is None:
        raise ValueError("GLB sem chunk JSON")

    gltf = json.loads(json_raw.decode("utf-8"))
    if not isinstance(gltf, dict):
        raise ValueError("chunk JSON GLB deve ser objeto")
    img_bvs: set[int] = set()
    for img in gltf.get("images") or []:
        if isinstance(img, dict):
            bv_idx = img.get("bufferView")
            if isinstance(bv_idx, int) and not isinstance(bv_idx, bool):
                img_bvs.add(bv_idx)

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

    bin_compactado = _compactar_bin(gltf, bin_raw, img_bvs)

    json_bytes = json.dumps(gltf, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    pad_json = (4 - (len(json_bytes) % 4)) % 4
    json_bytes_padded = json_bytes + (b" " * pad_json)

    chunks: list[tuple[int, bytes]] = [(_CHUNK_JSON, json_bytes_padded)]
    if bin_compactado:
        pad_bin = (4 - (len(bin_compactado) % 4)) % 4
        chunks.append((_CHUNK_BIN, bin_compactado + (b"\x00" * pad_bin)))
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
