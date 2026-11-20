"""Operacoes de matrizes 4x4 e validacao de transformacoes de nos glTF."""

from __future__ import annotations

import math
from typing import Any, TypeGuard


def _eh_int(val: object) -> TypeGuard[int]:
    return isinstance(val, int) and not isinstance(val, bool)


def _num_finito(val: Any) -> bool:
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        return False
    try:
        return math.isfinite(float(val))
    except OverflowError:
        return False


def _ler_indices_int(vals: list[tuple]) -> list[int]:
    out: list[int] = []
    for v in vals:
        if not v:
            continue
        x = v[0]
        if not _num_finito(x):
            raise ValueError(f"indice nao finito: {x}")
        out.append(int(x))
    return out


_ATRIBUTOS_PRIMITIVA = (
    "TEXCOORD_0",
    "TEXCOORD_1",
    "NORMAL",
    "TANGENT",
    "COLOR_0",
    "JOINTS_0",
    "WEIGHTS_0",
)


def _sparse_valido(sparse: object, buffer_views: list) -> bool:
    if not isinstance(sparse, dict):
        return False
    cnt = sparse.get("count")
    ind = sparse.get("indices")
    vals = sparse.get("values")
    if not _eh_int(cnt) or cnt <= 0 or not isinstance(ind, dict) or not isinstance(vals, dict):
        return False
    ibv = ind.get("bufferView")
    vbv = vals.get("bufferView")
    return (
        _eh_int(ibv)
        and 0 <= ibv < len(buffer_views)
        and isinstance(buffer_views[ibv], dict)
        and _eh_int(vbv)
        and 0 <= vbv < len(buffer_views)
        and isinstance(buffer_views[vbv], dict)
    )


def _validar_materiais_texturas(
    gltf: dict,
    materials: list,
    textures: list,
    imagens: list,
    erros_gltf: list[str],
) -> None:
    raw_tex = gltf.get("textures")
    if raw_tex is not None and not isinstance(raw_tex, list):
        erros_gltf.append("textures_invalido")
    for t_idx, tex in enumerate(textures):
        if not isinstance(tex, dict):
            erros_gltf.append(f"texture_invalida:{t_idx}")
            continue
        if "source" in tex and tex["source"] is not None:
            src = tex["source"]
            if not _eh_int(src) or src < 0 or src >= len(imagens) or not isinstance(imagens[src], dict):
                erros_gltf.append(f"texture_invalida:{t_idx}")
    for m_idx_e, mat_e in enumerate(materials):
        if not isinstance(mat_e, dict):
            erros_gltf.append(f"material_invalido:{m_idx_e}")
            continue
        pbr_e = mat_e.get("pbrMetallicRoughness")
        if pbr_e is not None and not isinstance(pbr_e, dict):
            erros_gltf.append(f"material_invalido:{m_idx_e}")
            continue
        tex_refs = [
            pbr_e.get("baseColorTexture") if isinstance(pbr_e, dict) else None,
            pbr_e.get("metallicRoughnessTexture") if isinstance(pbr_e, dict) else None,
            mat_e.get("normalTexture"),
            mat_e.get("occlusionTexture"),
            mat_e.get("emissiveTexture"),
        ]
        for ref in tex_refs:
            if ref is None:
                continue
            if not isinstance(ref, dict):
                erros_gltf.append(f"material_invalido:{m_idx_e}")
                continue
            ti = ref.get("index")
            if not _eh_int(ti) or ti < 0 or ti >= len(textures) or not isinstance(textures[ti], dict):
                erros_gltf.append(f"material_invalido:{m_idx_e}")


def _validar_refs_primitiva(
    prim: dict,
    p_idx: int,
    accessors: list,
    buffer_views: list,
    materials: list,
    erros_gltf: list[str],
    exigir_bv: bool = True,
) -> tuple[dict, dict | None, int | None, set[str]]:
    raw_atrib = prim.get("attributes")
    if not isinstance(raw_atrib, dict):
        erros_gltf.append(f"primitiva_invalida:{p_idx}")
        atributos: dict = {}
    else:
        atributos = raw_atrib

    attrs_validos: set[str] = set()
    for nome in _ATRIBUTOS_PRIMITIVA:
        if nome not in atributos:
            continue
        idx = atributos[nome]
        if not _eh_int(idx) or idx < 0 or idx >= len(accessors) or not isinstance(accessors[idx], dict):
            erros_gltf.append(f"accessor_invalido:{idx}")
            continue
        acc = accessors[idx]
        bv = acc.get("bufferView")
        bv_ok = _eh_int(bv) and 0 <= bv < len(buffer_views) and isinstance(buffer_views[bv], dict)
        if (bv is not None and not bv_ok) or (
            bv is None and exigir_bv and not _sparse_valido(acc.get("sparse"), buffer_views)
        ):
            erros_gltf.append(f"bufferView_invalido:{bv}")
            continue
        attrs_validos.add(nome)

    mat_idx = prim.get("material")
    mat_obj: dict | None = None
    mat_valido: int | None = None
    if mat_idx is not None:
        if _eh_int(mat_idx) and 0 <= mat_idx < len(materials) and isinstance(materials[mat_idx], dict):
            mat_obj = materials[mat_idx]
            mat_valido = mat_idx
        else:
            erros_gltf.append(f"material_invalido:{mat_idx}")
    elif len(materials) == 1 and isinstance(materials[0], dict):
        mat_obj = materials[0]
    return atributos, mat_obj, mat_valido, attrs_validos


def _lista_nums(val: Any, tamanho: int) -> list[float] | None:
    if not isinstance(val, list) or len(val) != tamanho:
        return None
    if not all(_num_finito(v) for v in val):
        return None
    return [float(v) for v in val]


def _no_transform_valida(no: dict) -> bool:
    for chave, tam in (("matrix", 16), ("translation", 3), ("rotation", 4), ("scale", 3)):
        if chave in no and no[chave] is not None and _lista_nums(no[chave], tam) is None:
            return False
    return True


def _mat4_identidade() -> list[float]:
    return [
        1.0, 0.0, 0.0, 0.0,
        0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
        0.0, 0.0, 0.0, 1.0,
    ]


def _mat4_mul(a: list[float], b: list[float]) -> list[float]:
    out = [0.0] * 16
    for r in range(4):
        r4 = r * 4
        for c in range(4):
            out[r4 + c] = (
                a[r4] * b[c]
                + a[r4 + 1] * b[4 + c]
                + a[r4 + 2] * b[8 + c]
                + a[r4 + 3] * b[12 + c]
            )
    return out


def _mat4_det3(m: list[float]) -> float:
    return (
        m[0] * (m[5] * m[10] - m[6] * m[9])
        - m[1] * (m[4] * m[10] - m[6] * m[8])
        + m[2] * (m[4] * m[9] - m[5] * m[8])
    )


def _mat4_de_no(no: dict) -> list[float]:
    if not isinstance(no, dict):
        return _mat4_identidade()
    cm = _lista_nums(no.get("matrix"), 16)
    if cm is not None:
        return [
            cm[0], cm[4], cm[8], cm[12],
            cm[1], cm[5], cm[9], cm[13],
            cm[2], cm[6], cm[10], cm[14],
            cm[3], cm[7], cm[11], cm[15],
        ]
    t = _lista_nums(no.get("translation"), 3) or [0.0, 0.0, 0.0]
    r = _lista_nums(no.get("rotation"), 4) or [0.0, 0.0, 0.0, 1.0]
    s = _lista_nums(no.get("scale"), 3) or [1.0, 1.0, 1.0]
    tx, ty, tz = t[0], t[1], t[2]
    qx, qy, qz, qw = r[0], r[1], r[2], r[3]
    sx, sy, sz = s[0], s[1], s[2]
    norm = math.sqrt(qx * qx + qy * qy + qz * qz + qw * qw)
    if norm > 1e-12:
        qx, qy, qz, qw = qx / norm, qy / norm, qz / norm, qw / norm
    else:
        qx, qy, qz, qw = 0.0, 0.0, 0.0, 1.0
    r00 = 1.0 - 2.0 * (qy * qy + qz * qz)
    r01 = 2.0 * (qx * qy - qz * qw)
    r02 = 2.0 * (qx * qz + qy * qw)
    r10 = 2.0 * (qx * qy + qz * qw)
    r11 = 1.0 - 2.0 * (qx * qx + qz * qz)
    r12 = 2.0 * (qy * qz - qx * qw)
    r20 = 2.0 * (qx * qz - qy * qw)
    r21 = 2.0 * (qy * qz + qx * qw)
    r22 = 1.0 - 2.0 * (qx * qx + qy * qy)
    return [
        r00 * sx, r01 * sy, r02 * sz, tx,
        r10 * sx, r11 * sy, r12 * sz, ty,
        r20 * sx, r21 * sy, r22 * sz, tz,
        0.0, 0.0, 0.0, 1.0,
    ]


def _matrizes_mundo_nos(gltf: dict) -> dict[int, list[float]]:
    if not isinstance(gltf, dict):
        return {}
    raw_nodes = gltf.get("nodes", [])
    nodes = raw_nodes if isinstance(raw_nodes, list) else []
    if not nodes:
        return {}
    mundos: dict[int, list[float]] = {}
    visitados: set[int] = set()

    def _descer(idx: int, pai_mat: list[float]) -> None:
        if idx in visitados or idx < 0 or idx >= len(nodes):
            return
        visitados.add(idx)
        no = nodes[idx]
        if not isinstance(no, dict):
            return
        mat = _mat4_mul(pai_mat, _mat4_de_no(no))
        mundos[idx] = mat
        filhos = no.get("children")
        if not isinstance(filhos, list):
            return
        for filho in filhos:
            if isinstance(filho, int) and not isinstance(filho, bool):
                _descer(filho, mat)

    ident = _mat4_identidade()
    scenes = gltf.get("scenes", [])
    if isinstance(scenes, list) and scenes:
        scene_idx = gltf.get("scene", 0)
        if (
            not isinstance(scene_idx, int)
            or isinstance(scene_idx, bool)
            or scene_idx < 0
            or scene_idx >= len(scenes)
        ):
            scene_idx = 0
        sc = scenes[scene_idx]
        if isinstance(sc, dict):
            raizes = sc.get("nodes")
            if isinstance(raizes, list):
                for raiz in raizes:
                    if isinstance(raiz, int) and not isinstance(raiz, bool):
                        _descer(raiz, ident)

    tem_pai = {
        filho
        for no in nodes
        if isinstance(no, dict) and isinstance(no.get("children"), list)
        for filho in no["children"]
        if isinstance(filho, int) and not isinstance(filho, bool)
    }
    for idx in range(len(nodes)):
        if idx not in tem_pai and idx not in visitados:
            _descer(idx, ident)
    for idx in range(len(nodes)):
        if idx not in visitados:
            _descer(idx, ident)
    return mundos


def _aplicar_mat4(m: list[float], p: tuple[float, float, float]) -> tuple[float, float, float]:
    x, y, z = p
    return (
        m[0] * x + m[1] * y + m[2] * z + m[3],
        m[4] * x + m[5] * y + m[6] * z + m[7],
        m[8] * x + m[9] * y + m[10] * z + m[11],
    )
