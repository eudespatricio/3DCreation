"""Leitura binaria de GLB/glTF, transformacoes de nos e extracao de malha/atributos."""

from __future__ import annotations

import json
import struct
from pathlib import Path

from .errors import ForgeError, erro_qc
from .qc_glb_mat import (
    _aplicar_mat4,
    _eh_int,
    _ler_indices_int,
    _mat4_de_no,
    _mat4_det3,
    _mat4_identidade,
    _mat4_mul,
    _matrizes_mundo_nos,
    _no_transform_valida,
    _num_finito,
    _validar_materiais_texturas,
    _validar_refs_primitiva,
)

__all__ = [
    "_aplicar_mat4",
    "_mat4_de_no",
    "_mat4_det3",
    "_mat4_identidade",
    "_mat4_mul",
    "_matrizes_mundo_nos",
    "_accessor",
    "analisar",
    "ler_glb",
    "ler_glb_bin",
    "malha",
]

_MAGIC = 0x46546C67  # "glTF"
_CHUNK_JSON = 0x4E4F534A
_CHUNK_BIN = 0x004E4942  # "BIN\0"

_COMPONENTES = {
    5120: ("b", 1),
    5121: ("B", 1),
    5122: ("h", 2),
    5123: ("H", 2),
    5125: ("I", 4),
    5126: ("f", 4),
}
_TIPOS = {
    "SCALAR": 1,
    "VEC2": 2,
    "VEC3": 3,
    "VEC4": 4,
    "MAT2": 4,
    "MAT3": 9,
    "MAT4": 16,
}


def ler_glb_bin(caminho: Path | str | bytes | bytearray | memoryview) -> tuple[dict, bytes]:
    """Le o GLB e devolve (json, chunk binario). Aceita caminho ou bytes em memoria."""
    if isinstance(caminho, (bytes, bytearray, memoryview)):
        dados = bytes(caminho)
        origem = "<bytes>"
    else:
        dados = Path(caminho).read_bytes()
        origem = str(caminho)
    if len(dados) < 12:
        raise erro_qc(f"glb truncado: {origem}", arquivo=origem)
    magic, _versao, _tamanho = struct.unpack_from("<III", dados, 0)
    if magic != _MAGIC:
        raise erro_qc(f"nao e GLB valido: {origem}", arquivo=origem)
    offset = 12
    bloco_json = None
    bloco_bin = b""
    while offset < len(dados):
        if offset + 8 > len(dados):
            raise erro_qc(f"cabecalho de chunk GLB truncado: {origem}", arquivo=origem)
        tamanho, tipo = struct.unpack_from("<II", dados, offset)
        offset += 8
        if offset + tamanho > len(dados):
            raise erro_qc(f"chunk GLB truncado: {origem}", arquivo=origem)
        bloco = dados[offset : offset + tamanho]
        offset += tamanho
        if tipo == _CHUNK_JSON:
            bloco_json = bloco
        elif tipo == _CHUNK_BIN:
            bloco_bin = bloco
    if bloco_json is None:
        raise erro_qc(f"GLB sem chunk JSON: {origem}", arquivo=origem)
    try:
        gltf = json.loads(bloco_json.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise erro_qc(f"JSON invalido no GLB {origem}: {exc}", arquivo=origem) from exc
    if not isinstance(gltf, dict):
        raise erro_qc(f"JSON raiz do GLB nao e objeto: {origem}", arquivo=origem)
    return gltf, bloco_bin


def ler_glb(caminho: Path | str | bytes | bytearray | memoryview) -> dict:
    return ler_glb_bin(caminho)[0]


def _accessor(gltf: dict, binario: bytes, indice: int) -> list[tuple]:
    accessors = gltf.get("accessors")
    buffer_views = gltf.get("bufferViews")
    if not isinstance(accessors, list) or indice < 0 or indice >= len(accessors):
        raise erro_qc(f"accessor invalido: {indice}")
    acc = accessors[indice]
    if not isinstance(acc, dict):
        raise erro_qc(f"accessor malformado no indice {indice}")
    bv_idx = acc.get("bufferView")
    if (
        not isinstance(bv_idx, int)
        or isinstance(bv_idx, bool)
        or not isinstance(buffer_views, list)
        or bv_idx < 0
        or bv_idx >= len(buffer_views)
    ):
        raise erro_qc(f"bufferView invalido no accessor {indice}: {bv_idx}")
    bv = buffer_views[bv_idx]
    if not isinstance(bv, dict):
        raise erro_qc(f"bufferView malformado no indice {bv_idx}")
    comp_raw = acc.get("componentType")
    tipo_raw = acc.get("type")
    count_raw = acc.get("count")
    if not isinstance(comp_raw, int) or isinstance(comp_raw, bool) or comp_raw not in _COMPONENTES:
        raise erro_qc(f"componentType invalido no accessor {indice}: {comp_raw}")
    if not isinstance(tipo_raw, str) or tipo_raw not in _TIPOS:
        raise erro_qc(f"type invalido no accessor {indice}: {tipo_raw}")
    if not isinstance(count_raw, int) or isinstance(count_raw, bool) or count_raw < 0:
        raise erro_qc(f"count invalido no accessor {indice}: {count_raw}")
    bv_off = bv.get("byteOffset", 0)
    acc_off = acc.get("byteOffset", 0)
    if (
        not isinstance(bv_off, int)
        or isinstance(bv_off, bool)
        or bv_off < 0
        or not isinstance(acc_off, int)
        or isinstance(acc_off, bool)
        or acc_off < 0
    ):
        raise erro_qc(f"byteOffset invalido no accessor {indice}")
    componente, tamanho = _COMPONENTES[comp_raw]
    n = _TIPOS[tipo_raw]
    stride_raw = bv.get("byteStride")
    if stride_raw is None:
        passo = tamanho * n
    elif isinstance(stride_raw, int) and not isinstance(stride_raw, bool) and stride_raw > 0:
        passo = stride_raw
    else:
        raise erro_qc(f"byteStride invalido no bufferView {bv_idx}: {stride_raw}")
    base = bv_off + acc_off
    formato = "<" + componente * n
    if count_raw > 0 and base + (count_raw - 1) * passo + tamanho * n > len(binario):
        raise erro_qc(f"buffer BIN insuficiente para accessor {indice}")
    return [
        struct.unpack_from(formato, binario, base + i * passo)
        for i in range(count_raw)
    ]


def malha(gltf: dict, binario: bytes) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    """Posicoes e triangulos do GLB no espaco de mundo (inclui matriz dos nos)."""
    posicoes: list[tuple[float, float, float]] = []
    triangulos: list[tuple[int, int, int]] = []
    mats_mundo = _matrizes_mundo_nos(gltf)
    raw_meshes = gltf.get("meshes", [])
    malhas_gltf = raw_meshes if isinstance(raw_meshes, list) else []
    raw_nodes = gltf.get("nodes", [])
    nodes_gltf = raw_nodes if isinstance(raw_nodes, list) else []
    instancias: list[tuple[list[float], dict]] = []
    for idx_no, no in enumerate(nodes_gltf):
        if not isinstance(no, dict):
            continue
        m_idx = no.get("mesh")
        if isinstance(m_idx, int) and not isinstance(m_idx, bool) and 0 <= m_idx < len(malhas_gltf):
            m_obj = malhas_gltf[m_idx]
            if isinstance(m_obj, dict):
                instancias.append((mats_mundo.get(idx_no, _mat4_identidade()), m_obj))
    if not instancias:
        instancias = [(_mat4_identidade(), m) for m in malhas_gltf if isinstance(m, dict)]

    for mat_mundo, malha_gltf in instancias:
        inverter = _mat4_det3(mat_mundo) < 0.0
        prims = malha_gltf.get("primitives", [])
        if not isinstance(prims, list):
            continue
        for prim in prims:
            if not isinstance(prim, dict):
                continue
            atributos = prim.get("attributes", {})
            if not isinstance(atributos, dict):
                continue
            pos_idx = atributos.get("POSITION")
            modo = prim.get("mode", 4)
            if (
                not isinstance(pos_idx, int)
                or isinstance(pos_idx, bool)
                or not isinstance(modo, int)
                or isinstance(modo, bool)
                or modo != 4
            ):
                continue
            posicao = _accessor(gltf, binario, pos_idx)
            if any(len(p) < 3 for p in posicao):
                raise erro_qc(f"accessor POSITION invalido: {pos_idx}")
            base = len(posicoes)
            posicoes.extend(
                _aplicar_mat4(mat_mundo, (float(p[0]), float(p[1]), float(p[2]))) for p in posicao
            )
            idx = prim.get("indices")
            if isinstance(idx, int) and not isinstance(idx, bool):
                ids = _ler_indices_int(_accessor(gltf, binario, idx))
                if any(i < 0 or i >= len(posicao) for i in ids):
                    raise erro_qc(f"indice fora do intervalo na primitiva: {idx}")
            elif idx is not None:
                raise erro_qc(f"indices invalido na primitiva: {idx}")
            else:
                ids = list(range(len(posicao)))
            for k in range(0, len(ids) - 2, 3):
                if inverter:
                    triangulos.append((base + ids[k], base + ids[k + 2], base + ids[k + 1]))
                else:
                    triangulos.append((base + ids[k], base + ids[k + 1], base + ids[k + 2]))
    return posicoes, triangulos


def _lista(obj: dict, chave: str) -> list:
    val = obj.get(chave)
    return val if isinstance(val, list) else []


def analisar(gltf: dict, binario: bytes | None = None) -> dict:
    """Extrai o que o QC precisa sem confiar no produtor."""
    erros_gltf: list[str] = []
    for chave_l in (
        "accessors", "bufferViews", "nodes", "meshes", "materials", "images", "skins", "animations"
    ):
        val_l = gltf.get(chave_l)
        if val_l is not None and not isinstance(val_l, list):
            erros_gltf.append(f"{chave_l}_invalido")

    accessors = _lista(gltf, "accessors")
    buffer_views = _lista(gltf, "bufferViews")
    nodes = _lista(gltf, "nodes")
    meshes = _lista(gltf, "meshes")
    materials = _lista(gltf, "materials")
    textures = _lista(gltf, "textures")
    imagens = _lista(gltf, "images")
    skins = _lista(gltf, "skins")
    anims = _lista(gltf, "animations")

    for a_idx, acc_obj in enumerate(accessors):
        if not isinstance(acc_obj, dict):
            erros_gltf.append(f"accessor_invalido:{a_idx}")
    for bv_idx_e, bv_obj in enumerate(buffer_views):
        if not isinstance(bv_obj, dict):
            erros_gltf.append(f"bufferView_invalido:{bv_idx_e}")
    _validar_materiais_texturas(gltf, materials, textures, imagens, erros_gltf)
    for im_idx_e, im_e in enumerate(imagens):
        if not isinstance(im_e, dict):
            erros_gltf.append(f"image_invalida:{im_idx_e}")
        elif "bufferView" in im_e and im_e["bufferView"] is not None:
            bv_im = im_e["bufferView"]
            if (
                not _eh_int(bv_im)
                or bv_im < 0
                or bv_im >= len(buffer_views)
                or not isinstance(buffer_views[bv_im], dict)
            ):
                erros_gltf.append(f"image_invalida:{im_idx_e}")
    for an_idx_e, an_e in enumerate(anims):
        if not isinstance(an_e, dict):
            erros_gltf.append(f"animacao_invalida:{an_idx_e}")

    mundos = _matrizes_mundo_nos(gltf)
    mesh_instancias: list[tuple[dict, list[float]]] = []
    for idx, no in enumerate(nodes):
        if not isinstance(no, dict) or not _no_transform_valida(no):
            erros_gltf.append(f"node_invalido:{idx}")
            continue
        m_idx = no.get("mesh")
        if _eh_int(m_idx) and 0 <= m_idx < len(meshes):
            m_obj = meshes[m_idx]
            if isinstance(m_obj, dict):
                mesh_instancias.append((m_obj, mundos.get(idx, _mat4_identidade())))
            else:
                erros_gltf.append(f"mesh_invalida:{m_idx}")
        elif m_idx is not None:
            erros_gltf.append(f"node_invalido:{idx}")
    if not mesh_instancias:
        ident = _mat4_identidade()
        for m_idx, m in enumerate(meshes):
            if isinstance(m, dict):
                mesh_instancias.append((m, ident))
            else:
                erros_gltf.append(f"mesh_invalida:{m_idx}")

    triangulos = vertices = primitivas = sem_uv = com_tangent = com_uv1 = com_color_0 = sem_tangent_normal = 0
    materiais_com_color_0: set[int] = set()
    prim_tris: list[int] = []
    minimos = [float("inf")] * 3
    maximos = [float("-inf")] * 3

    for malha_obj, mat_mundo in mesh_instancias:
        prims = malha_obj.get("primitives", [])
        if not isinstance(prims, list):
            erros_gltf.append("primitives_invalido")
            continue
        for p_idx, prim in enumerate(prims):
            if not isinstance(prim, dict):
                erros_gltf.append(f"primitiva_invalida:{p_idx}")
                continue
            primitivas += 1
            modo = prim.get("mode", 4)
            if not _eh_int(modo):
                erros_gltf.append(f"primitiva_invalida:{p_idx}")
                continue
            atributos, mat_obj, mat_idx, attrs_validos = _validar_refs_primitiva(
                prim, p_idx, accessors, buffer_views, materials, erros_gltf, exigir_bv=(binario is not None)
            )
            if "TEXCOORD_0" not in attrs_validos:
                sem_uv += 1
            if "TANGENT" in attrs_validos:
                com_tangent += 1
            if "TEXCOORD_1" in attrs_validos:
                com_uv1 += 1
            if modo == 4 and mat_obj and mat_obj.get("normalTexture") and "TANGENT" not in attrs_validos:
                sem_tangent_normal += 1
            if "COLOR_0" in attrs_validos:
                com_color_0 += 1
                if mat_idx is not None:
                    materiais_com_color_0.add(mat_idx)
                elif len(materials) == 1:
                    materiais_com_color_0.add(0)
            pos = atributos.get("POSITION")
            pos_acc = (
                accessors[pos]
                if _eh_int(pos) and 0 <= pos < len(accessors)
                else None
            )
            if isinstance(pos_acc, dict):
                bv_idx = pos_acc.get("bufferView")
                if (
                    _eh_int(bv_idx)
                    and 0 <= bv_idx < len(buffer_views)
                    and not isinstance(buffer_views[bv_idx], dict)
                ):
                    erros_gltf.append(f"bufferView_invalido:{bv_idx}")
                cnt_pos = pos_acc.get("count", 0)
                if _eh_int(cnt_pos) and cnt_pos >= 0:
                    vertices += cnt_pos
                else:
                    erros_gltf.append(f"accessor_invalido:{pos}")
                mn_raw = pos_acc.get("min")
                mx_raw = pos_acc.get("max")
                if mn_raw is not None or mx_raw is not None:
                    if (
                        isinstance(mn_raw, list)
                        and isinstance(mx_raw, list)
                        and len(mn_raw) >= 3
                        and len(mx_raw) >= 3
                        and all(_num_finito(v) for v in mn_raw[:3])
                        and all(_num_finito(v) for v in mx_raw[:3])
                    ):
                        mn = [float(v) for v in mn_raw[:3]]
                        mx = [float(v) for v in mx_raw[:3]]
                        for cx in (mn[0], mx[0]):
                            for cy in (mn[1], mx[1]):
                                for cz in (mn[2], mx[2]):
                                    tx, ty, tz = _aplicar_mat4(mat_mundo, (cx, cy, cz))
                                    minimos = [min(minimos[0], tx), min(minimos[1], ty), min(minimos[2], tz)]
                                    maximos = [max(maximos[0], tx), max(maximos[1], ty), max(maximos[2], tz)]
                    else:
                        erros_gltf.append(f"accessor_invalido:{pos}")
            elif pos is not None:
                erros_gltf.append(f"accessor_invalido:{pos}")
            indices = prim.get("indices")
            if modo != 4:
                continue
            tris_prim = 0
            idx_acc = (
                accessors[indices]
                if _eh_int(indices) and 0 <= indices < len(accessors)
                else None
            )
            if isinstance(idx_acc, dict):
                cnt_idx = idx_acc.get("count", 0)
                if _eh_int(cnt_idx) and cnt_idx >= 0:
                    tris_prim = cnt_idx // 3
                else:
                    erros_gltf.append(f"accessor_invalido:{indices}")
            elif indices is not None:
                erros_gltf.append(f"accessor_invalido:{indices}")
            elif isinstance(pos_acc, dict):
                cnt_p = pos_acc.get("count", 0)
                if _eh_int(cnt_p) and cnt_p >= 0:
                    tris_prim = cnt_p // 3
            triangulos += tris_prim
            prim_tris.append(tris_prim)

    if binario is not None and meshes:
        try:
            pos_mundo, _ = malha(gltf, binario)
        except (
            ForgeError, KeyError, IndexError, OverflowError, struct.error, TypeError, ValueError, AttributeError
        ) as exc:
            pos_mundo = []
            erros_gltf.append(f"malha_invalida:{exc}")
        if pos_mundo:
            minimos = [min(p[i] for p in pos_mundo) for i in range(3)]
            maximos = [max(p[i] for p in pos_mundo) for i in range(3)]

    tem_bbox = minimos[0] != float("inf")
    bbox = [maximos[i] - minimos[i] for i in range(3)] if tem_bbox else [0.0, 0.0, 0.0]
    nomes_nos = [str(n.get("name", "")) for n in nodes if isinstance(n, dict)]
    nomes_ossos: list[str] = []
    for s_idx, sk in enumerate(skins):
        if not isinstance(sk, dict):
            erros_gltf.append(f"skin_invalida:{s_idx}")
            continue
        joints_raw = sk.get("joints")
        if joints_raw is not None and not isinstance(joints_raw, list):
            erros_gltf.append(f"joints_invalido:{s_idx}")
            continue
        if s_idx == 0:
            for indice in joints_raw or []:
                if _eh_int(indice) and 0 <= indice < len(nodes):
                    no_j = nodes[indice]
                    if isinstance(no_j, dict):
                        nomes_ossos.append(str(no_j.get("name", "")))
                    else:
                        erros_gltf.append(f"node_joint_invalido:{indice}")

    def _pbr(mat: object) -> dict:
        if not isinstance(mat, dict):
            return {}
        p = mat.get("pbrMetallicRoughness")
        return p if isinstance(p, dict) else {}

    com_textura = sum(1 for m in materials if _pbr(m).get("baseColorTexture"))
    materiais_validos = sum(
        1
        for idx, m in enumerate(materials)
        if isinstance(m, dict)
        and (
            _pbr(m).get("baseColorTexture")
            or "baseColorFactor" in _pbr(m)
            or idx in materiais_com_color_0
        )
    )
    erros_unicos = list(dict.fromkeys(erros_gltf))

    return {
        "triangulos": triangulos,
        "vertices": vertices,
        "primitivas": primitivas,
        "prim_tris": prim_tris,
        "sem_uv": sem_uv,
        "sem_tangent_normal": sem_tangent_normal,
        "com_color_0": com_color_0,
        "bbox_m": [round(v, 6) for v in bbox],
        "min": [round(v, 6) for v in minimos] if tem_bbox else [0, 0, 0],
        "max": [round(v, 6) for v in maximos] if tem_bbox else [0, 0, 0],
        "materiais": len(materials),
        "com_textura": com_textura,
        "materiais_validos": materiais_validos,
        "imagens": len(imagens),
        "imagens_externas": [i["uri"] for i in imagens if isinstance(i, dict) and i.get("uri")],
        "ossos": len(nomes_ossos),
        "nomes_ossos": nomes_ossos,
        "nos": nomes_nos,
        "colisores": [n for n in nomes_nos if n.startswith("UCX_")],
        "tangentes": primitivas > 0 and com_tangent == primitivas,
        "uv_lightmap": primitivas > 0 and com_uv1 == primitivas,
        **({"erros": erros_unicos} if erros_unicos else {}),
    }
