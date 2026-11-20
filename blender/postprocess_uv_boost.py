"""Boost de densidade texel UV para regiao superior/cabeca de personagens eretos (camada L2)."""

from __future__ import annotations

import bmesh


def aplicar_prioridade_uv_cabeca(
    obj,
    *,
    fator: float = 1.35,
    z_frac_inicio: float = 0.78,
    min_poligonos: int = 400,
    razao_ereto_min: float = 0.8,
) -> int:
    """Escala UVs de faces com centroide ``z >= z_min + z_frac_inicio * h`` em OBJECT mode.

    Deve ser chamada em ``OBJECT`` mode antes de ``bpy.ops.uv.pack_islands`` para preservar
    seguranca de ponteiros RNA e permitir que o empacotador encaixe tudo em ``[0, 1]^2``
    mantendo ~1.8x de densidade texel relativa na cabeca/rosto.
    """
    if obj is None or getattr(obj, "type", None) != "MESH" or getattr(obj, "data", None) is None:
        return 0
    mesh = obj.data
    if not mesh.uv_layers or len(mesh.polygons) < min_poligonos or not mesh.vertices:
        return 0

    xs = [v.co.x for v in mesh.vertices]
    ys = [v.co.y for v in mesh.vertices]
    zs = [v.co.z for v in mesh.vertices]
    w = max(xs) - min(xs)
    d = max(ys) - min(ys)
    z_min = min(zs)
    h = max(zs) - z_min
    if h <= 1e-6 or h < razao_ereto_min * max(w, d):
        return 0

    z_corte = z_min + float(z_frac_inicio) * h
    escala = float(fator)
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        uv_layer = bm.loops.layers.uv.active
        if uv_layer is None:
            return 0
        faces_cabeca = [f for f in bm.faces if f.calc_center_median().z >= z_corte]
        if not faces_cabeca:
            return 0
        loops_cabeca = [lp for f in faces_cabeca for lp in f.loops]
        if not loops_cabeca:
            return 0
        inv_n = 1.0 / float(len(loops_cabeca))
        uc = sum(lp[uv_layer].uv.x for lp in loops_cabeca) * inv_n
        vc = sum(lp[uv_layer].uv.y for lp in loops_cabeca) * inv_n
        for lp in loops_cabeca:
            uv = lp[uv_layer].uv
            lp[uv_layer].uv = (uc + (uv.x - uc) * escala, vc + (uv.y - vc) * escala)
        bm.to_mesh(mesh)
        mesh.update()
        return len(faces_cabeca)
    finally:
        bm.free()
