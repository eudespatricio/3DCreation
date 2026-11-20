"""Projecao ortografica 1-vista e 4-vistas (+Y/-Y/-X/+X) e oclusao BVH em high-mesh."""

from __future__ import annotations

import math
import os
import sys
from array import array

try:
    import bmesh
    import bpy
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
except ImportError:  # pragma: no cover - permite import puro em testes fora do Blender
    bmesh = None  # type: ignore[assignment]
    bpy = None  # type: ignore[assignment]
    Vector = None  # type: ignore[assignment,misc]
    BVHTree = None  # type: ignore[assignment,misc]

if __package__:
    from . import bake_pbr_shaders as _sh
else:
    _BLENDER_DIR = os.path.dirname(os.path.abspath(__file__))
    if _BLENDER_DIR not in sys.path:
        sys.path.insert(0, _BLENDER_DIR)
    import bake_pbr_shaders as _sh

_criar_nodos_fator_vista = _sh._criar_nodos_fator_vista
_criar_nodos_fator_frontal = _sh._criar_nodos_fator_frontal
_criar_material_high_vc = _sh._criar_material_high_vc
_criar_material_high_multivista = _sh._criar_material_high_multivista
_criar_material_high_hints_emit = _sh._criar_material_high_hints_emit

_VISTAS_ORTO_DEF: dict[str, dict] = {
    "front": {
        "aliases": ("front", "frente"),
        "dir": (0.0, 1.0, 0.0),
        "uv": "UV_Camera_Front",
        "vis": "visivel_frente",
    },
    "back": {
        "aliases": ("back", "costas", "traseira"),
        "dir": (0.0, -1.0, 0.0),
        "uv": "UV_Camera_Back",
        "vis": "visivel_back",
    },
    "right": {
        "aliases": ("right", "direita"),
        "dir": (-1.0, 0.0, 0.0),
        "uv": "UV_Camera_Right",
        "vis": "visivel_right",
    },
    "left": {
        "aliases": ("left", "esquerda"),
        "dir": (1.0, 0.0, 0.0),
        "uv": "UV_Camera_Left",
        "vis": "visivel_left",
    },
}


def _normalizar_vistas_ortograficas(
    vistas_ortograficas: dict[str, str] | None,
    origem_textura: str | None = None,
) -> dict[str, str]:
    """Normaliza chaves de vistas 4-ortograficas para ``front/back/right/left`` existentes."""
    if not isinstance(vistas_ortograficas, dict) or not vistas_ortograficas:
        return {}
    norm: dict[str, str] = {}
    for chave_raw, cam in vistas_ortograficas.items():
        if not cam:
            continue
        cam_str = str(cam)
        if not os.path.isfile(cam_str):
            continue
        k_low = str(chave_raw or "").strip().lower()
        for vista_canon, meta in _VISTAS_ORTO_DEF.items():
            if k_low in meta["aliases"]:
                norm[vista_canon] = cam_str
                break
    if norm and "front" not in norm and origem_textura and os.path.isfile(origem_textura):
        norm["front"] = str(origem_textura)
    return norm


def _podar_uv_layers_high(high_obj, uvs_necessarias: list[str]) -> None:
    """Remove UVs nao utilizadas apenas em ``high_obj`` para respeitar o limite de 8 UVs do Blender."""
    if high_obj is None or getattr(high_obj, "data", None) is None:
        return
    uvs = high_obj.data.uv_layers
    existentes = [uv.name for uv in uvs]
    faltantes = [n for n in uvs_necessarias if n not in existentes]
    if len(existentes) + len(faltantes) <= 8:
        return

    preservar = set(uvs_necessarias)
    if uvs.active is not None:
        preservar.add(uvs.active.name)
    for nome in [uv.name for uv in uvs if uv.name not in preservar]:
        if len(uvs) + len(faltantes) <= 8:
            break
        layer = uvs.get(nome)
        if layer is not None:
            uvs.remove(layer)
    if len(uvs) + len(faltantes) > 8:
        for nome in [uv.name for uv in uvs if uv.name not in uvs_necessarias]:
            if len(uvs) + len(faltantes) <= 8:
                break
            layer = uvs.get(nome)
            if layer is not None:
                uvs.remove(layer)


def _imagem_tem_alpha_valido(img) -> bool:
    """Retorna True se ``img`` possui canal alfa com mistura de transparencia e opacidade."""
    if img is None or not getattr(img, "size", None):
        return False
    w, h = int(img.size[0]), int(img.size[1])
    if w <= 0 or h <= 0:
        return False
    px_len = w * h * 4
    try:
        if len(getattr(img, "pixels", ())) != px_len:
            return False
        buf = array("f", [0.0]) * px_len
        img.pixels.foreach_get(buf)
    except (RuntimeError, ValueError, TypeError) as exc:
        sys.stderr.write(f"[bake_pbr_proj] aviso alpha indisponivel em imagem: {exc}\n")
        return False
    gw, gh = min(w, 64), min(h, 64)
    tem_transp = False
    tem_opaco = False
    for gy in range(gh):
        py = min(h - 1, int((gy + 0.5) * h / gh))
        row_off = py * w * 4
        for gx in range(gw):
            px_i = min(w - 1, int((gx + 0.5) * w / gw))
            a = buf[row_off + px_i * 4 + 3]
            if a < 0.98:
                tem_transp = True
            if a >= 0.45:
                tem_opaco = True
            if tem_transp and tem_opaco:
                return True
    return False


def _detectar_bbox_uv_foreground(img) -> tuple[float, float, float, float]:
    """Detecta bbox normalizado ``(u0, u1, v0, v1)`` do primeiro plano se houver margem uniforme."""
    if img is None or not getattr(img, "size", None):
        return (0.0, 1.0, 0.0, 1.0)
    w, h = int(img.size[0]), int(img.size[1])
    if w < 4 or h < 4:
        return (0.0, 1.0, 0.0, 1.0)
    buf = array("f", [0.0]) * (w * h * 4)
    img.pixels.foreach_get(buf)

    gw, gh = min(w, 128), min(h, 128)
    min_alpha = 1.0
    grade_rgb: list[tuple[float, float, float]] = []
    grade_a: list[float] = []
    for gy in range(gh):
        py = min(h - 1, int((gy + 0.5) * h / gh))
        row_off = py * w * 4
        for gx in range(gw):
            px_i = min(w - 1, int((gx + 0.5) * w / gw))
            idx = row_off + px_i * 4
            a = buf[idx + 3]
            if a < min_alpha:
                min_alpha = a
            grade_rgb.append((buf[idx], buf[idx + 1], buf[idx + 2]))
            grade_a.append(a)

    total = gw * gh
    if min_alpha < 0.98:
        min_x, max_x, min_y, max_y = gw, -1, gh, -1
        fg_a_count = 0
        for gy in range(gh):
            for gx in range(gw):
                if grade_a[gy * gw + gx] >= 0.45:
                    fg_a_count += 1
                    min_x, max_x = min(min_x, gx), max(max_x, gx)
                    min_y, max_y = min(min_y, gy), max(max_y, gy)
        if (
            fg_a_count >= max(4, int(0.005 * total))
            and max_x >= min_x
            and max_y >= min_y
            and (max_x - min_x + 1) / gw >= 0.02
            and (max_y - min_y + 1) / gh >= 0.02
        ):
            return (
                max(0.0, min_x / gw),
                min(1.0, (max_x + 1) / gw),
                max(0.0, min_y / gh),
                min(1.0, (max_y + 1) / gh),
            )
        return (0.0, 1.0, 0.0, 1.0)

    cantos = [grade_rgb[0], grade_rgb[gw - 1], grade_rgb[(gh - 1) * gw], grade_rgb[gh * gw - 1]]
    bg = tuple(sum(c[k] for c in cantos) * 0.25 for k in range(3))
    canto_spread = max(
        math.sqrt((c[0] - bg[0]) ** 2 + (c[1] - bg[1]) ** 2 + (c[2] - bg[2]) ** 2)
        for c in cantos
    )
    if canto_spread < 0.08:
        limiar_sq = 0.09 * 0.09
        fg_count, min_x, max_x, min_y, max_y = 0, gw, -1, gh, -1
        for gy in range(gh):
            for gx in range(gw):
                r, g, b = grade_rgb[gy * gw + gx]
                if (r - bg[0]) ** 2 + (g - bg[1]) ** 2 + (b - bg[2]) ** 2 > limiar_sq:
                    fg_count += 1
                    min_x, max_x = min(min_x, gx), max(max_x, gx)
                    min_y, max_y = min(min_y, gy), max(max_y, gy)
        if (
            0.05 * total <= fg_count <= 0.90 * total
            and max_x > min_x
            and max_y > min_y
            and (max_x - min_x + 1) / gw >= 0.05
            and (max_y - min_y + 1) / gh >= 0.05
        ):
            return (
                max(0.0, min_x / gw),
                min(1.0, (max_x + 1) / gw),
                max(0.0, min_y / gh),
                min(1.0, (max_y + 1) / gh),
            )

    return (0.0, 1.0, 0.0, 1.0)


def _criar_camera_ortografica_frontal(
    nome: str, min_v: Vector, max_v: Vector, colecao
):
    """Cria camera ortografica alinhada a frente ``+Y`` (convencao canonical/render_preview)."""
    cx = 0.5 * (min_v.x + max_v.x)
    cz = 0.5 * (min_v.z + max_v.z)
    dx = max(max_v.x - min_v.x, 1e-4)
    dy = max(max_v.y - min_v.y, 1e-4)
    dz = max(max_v.z - min_v.z, 1e-4)

    cam_data = bpy.data.cameras.new(nome)
    cam_data.type = "ORTHO"
    cam_data.sensor_fit = "HORIZONTAL" if dx >= dz else "VERTICAL"
    cam_data.ortho_scale = max(dx, dz)

    cam_obj = bpy.data.objects.new(nome, cam_data)
    colecao.objects.link(cam_obj)
    cam_obj.location = Vector((cx, max_v.y + max(dx, dy, dz) * 2.0 + 1.0, cz))
    cam_obj.rotation_euler = Vector((0.0, -1.0, 0.0)).to_track_quat("-Z", "Y").to_euler()
    return cam_obj, cam_data


def _projetar_uv_ortografica_bmesh(
    obj,
    vista_key: str,
    min_v: Vector,
    max_v: Vector,
    uv_bbox: tuple[float, float, float, float],
    nome_uv: str,
) -> None:
    """Projeta UVs ortograficas para ``front`` (+Y), ``back`` (-Y), ``right`` (-X) ou ``left`` (+X)."""
    u0, u1, v0, v1 = uv_bbox
    dx = max(max_v.x - min_v.x, 1e-6)
    dy = max(max_v.y - min_v.y, 1e-6)
    dz = max(max_v.z - min_v.z, 1e-6)
    mw = obj.matrix_world

    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        uv_layer = bm.loops.layers.uv.get(nome_uv) or bm.loops.layers.uv.new(nome_uv)
        for face in bm.faces:
            for loop in face.loops:
                co = mw @ loop.vert.co
                if vista_key == "back":
                    tx = (co.x - min_v.x) / dx
                elif vista_key == "right":
                    tx = (max_v.y - co.y) / dy
                elif vista_key == "left":
                    tx = (co.y - min_v.y) / dy
                else:
                    tx = (max_v.x - co.x) / dx
                tz = (co.z - min_v.z) / dz
                u = max(0.0, min(1.0, u0 + tx * (u1 - u0)))
                v = max(0.0, min(1.0, v0 + tz * (v1 - v0)))
                loop[uv_layer].uv = (u, v)
        bm.to_mesh(obj.data)
        obj.data.update()
    finally:
        bm.free()


def _projetar_uv_frontal_bmesh(
    obj,
    min_v: Vector,
    max_v: Vector,
    uv_bbox: tuple[float, float, float, float],
    nome_uv: str = "UV_Camera_Front",
) -> None:
    """Projeta UVs ortograficas frontais (+Y olhando -Y) diretamente em ``bmesh``."""
    _projetar_uv_ortografica_bmesh(obj, "front", min_v, max_v, uv_bbox, nome_uv)


def _calcular_oclusao_direcao_bmesh(
    obj,
    dir_mundo: tuple[float, float, float],
    nome_attr: str,
) -> str | None:
    """Marca vertices visiveis ao longo de ``dir_mundo`` via raycast BVHTree."""
    if obj is None or obj.type != "MESH" or not obj.data.vertices:
        return None
    mw = obj.matrix_world
    inv_rot = mw.to_3x3().inverted_safe()
    dir_local = (inv_rot @ Vector(dir_mundo)).normalized()
    xs = [v.co.x for v in obj.data.vertices]
    ys = [v.co.y for v in obj.data.vertices]
    zs = [v.co.z for v in obj.data.vertices]
    diag = math.sqrt((max(xs) - min(xs)) ** 2 + (max(ys) - min(ys)) ** 2 + (max(zs) - min(zs)) ** 2)
    eps = max(1e-4, diag * 0.004)
    if diag <= 1e-6:
        return None

    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        bm.verts.ensure_lookup_table()
        bvh = BVHTree.FromBMesh(bm)
        attr = obj.data.color_attributes.get(nome_attr)
        if attr is not None:
            obj.data.color_attributes.remove(attr)
        attr = obj.data.color_attributes.new(name=nome_attr, type="BYTE_COLOR", domain="POINT")
        for idx, v in enumerate(bm.verts):
            hit, _loc, _norm, _fidx = bvh.ray_cast(v.co + dir_local * eps, dir_local, diag * 2.0)
            val = 0.0 if hit is not None else 1.0
            attr.data[idx].color = (val, val, val, 1.0)
        obj.data.update()
        return nome_attr
    finally:
        bm.free()


def _calcular_oclusao_frontal_bmesh(obj, nome_attr: str = "visivel_frente") -> str | None:
    """Marca vertices visiveis ao longo da direcao frontal (+Y) via raycast BVHTree."""
    return _calcular_oclusao_direcao_bmesh(obj, (0.0, 1.0, 0.0), nome_attr)
