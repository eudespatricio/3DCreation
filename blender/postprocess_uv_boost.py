"""Boost de densidade texel UV para regiao superior/cabeca de personagens eretos (camada L2)."""

from __future__ import annotations

import math

import bmesh

_UV_GRID = 64


def _area_tri_2d(
    a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]
) -> float:
    return 0.5 * abs((b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1]))


def _clip_tri_2d(
    sujeito: tuple[tuple[float, float], tuple[float, float], tuple[float, float]],
    recorte: tuple[tuple[float, float], tuple[float, float], tuple[float, float]],
) -> float:
    """Area de intersecao 2D de dois triangulos via Sutherland-Hodgman."""
    def _ccw(t):
        a, b, c = t
        return (a, c, b) if ((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])) < 0.0 else t

    poly = list(_ccw(sujeito))
    clip = _ccw(recorte)
    for k in range(3):
        if not poly:
            return 0.0
        p, q = clip[k], clip[(k + 1) % 3]
        ex, ey = q[0] - p[0], q[1] - p[1]
        saida = []
        s_pt = poly[-1]
        for e_pt in poly:
            in_e = ex * (e_pt[1] - p[1]) - ey * (e_pt[0] - p[0]) >= -1e-11
            in_s = ex * (s_pt[1] - p[1]) - ey * (s_pt[0] - p[0]) >= -1e-11
            if in_e != in_s:
                dx, dy = e_pt[0] - s_pt[0], e_pt[1] - s_pt[1]
                denom = ex * dy - ey * dx
                if abs(denom) > 1e-15:
                    t = (ex * (p[1] - s_pt[1]) - ey * (p[0] - s_pt[0])) / denom
                    saida.append((s_pt[0] + t * dx, s_pt[1] + t * dy))
                else:
                    saida.append(s_pt)
            if in_e:
                saida.append(e_pt)
            s_pt = e_pt
        poly = saida
    n = len(poly)
    if n < 3:
        return 0.0
    return 0.5 * abs(sum(poly[i][0] * poly[(i + 1) % n][1] - poly[(i + 1) % n][0] * poly[i][1] for i in range(n)))


def tem_uv_sobreposta(obj) -> bool:
    """Detecta auto-sobreposicao de UV0 em OBJECT mode (espelha G3 com folga anti-quantizacao)."""
    if obj is None or getattr(obj, "type", None) != "MESH" or getattr(obj, "data", None) is None:
        return False
    me = obj.data
    if not me.uv_layers or not me.uv_layers.active or not me.polygons:
        return False
    me.calc_loop_triangles()
    uvl = me.uv_layers.active.data
    tris = []
    area_total = 0.0
    for lt in me.loop_triangles:
        a = (float(uvl[lt.loops[0]].uv[0]), float(uvl[lt.loops[0]].uv[1]))
        b = (float(uvl[lt.loops[1]].uv[0]), float(uvl[lt.loops[1]].uv[1]))
        c = (float(uvl[lt.loops[2]].uv[0]), float(uvl[lt.loops[2]].uv[1]))
        ar = _area_tri_2d(a, b, c)
        if ar > 1e-10:
            area_total += ar
            tris.append((a, b, c, ar, min(a[0], b[0], c[0]), min(a[1], b[1], c[1]), max(a[0], b[0], c[0]), max(a[1], b[1], c[1])))
    n = len(tris)
    if n < 2:
        return False
    limiar_ov = 0.0 if n <= 64 else max(8e-5, 0.0008 * area_total)
    area_ov = 0.0
    grade: dict[tuple[int, int], list[int]] = {}
    vistos: set[tuple[int, int]] = set()
    for idx, t in enumerate(tris):
        gx0 = max(0, min(_UV_GRID - 1, int(math.floor(t[4] * _UV_GRID))))
        gx1 = max(0, min(_UV_GRID - 1, int(math.floor(t[6] * _UV_GRID))))
        gy0 = max(0, min(_UV_GRID - 1, int(math.floor(t[5] * _UV_GRID))))
        gy1 = max(0, min(_UV_GRID - 1, int(math.floor(t[7] * _UV_GRID))))
        for gx in range(gx0, gx1 + 1):
            for gy in range(gy0, gy1 + 1):
                cel = grade.setdefault((gx, gy), [])
                for outro in cel:
                    par = (outro, idx)
                    if par in vistos:
                        continue
                    vistos.add(par)
                    o = tris[outro]
                    if max(o[4], t[4]) + 1e-6 >= min(o[6], t[6]) or max(o[5], t[5]) + 1e-6 >= min(o[7], t[7]):
                        continue
                    inter = _clip_tri_2d(o[:3], t[:3])
                    if inter > 1e-8 and inter > 1e-4 * min(o[3], t[3]):
                        area_ov += inter
                        if area_ov > limiar_ov:
                            return True
                cel.append(idx)
    return False


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
        bm.faces.ensure_lookup_table()
        uv_layer = bm.loops.layers.uv.active
        if uv_layer is None:
            return 0
        total_faces = len(bm.faces)
        if total_faces == 0:
            return 0
        f_uv = {f.index: {lp.vert.index: lp[uv_layer].uv for lp in f.loops} for f in bm.faces}
        visitadas: set[int] = set()
        total_escaladas = 0
        for f0 in bm.faces:
            if f0.index in visitadas:
                continue
            ilha, pilha = [f0], [f0]
            visitadas.add(f0.index)
            while pilha:
                fc = pilha.pop()
                uv_c = f_uv[fc.index]
                for e in fc.edges:
                    v0, v1 = e.verts[0].index, e.verts[1].index
                    ua0, ua1 = uv_c.get(v0), uv_c.get(v1)
                    if ua0 is None or ua1 is None:
                        continue
                    for fn in e.link_faces:
                        if fn.index in visitadas:
                            continue
                        uv_n = f_uv[fn.index]
                        ub0, ub1 = uv_n.get(v0), uv_n.get(v1)
                        if ub0 is not None and ub1 is not None and (ua0 - ub0).length < 1e-4 and (ua1 - ub1).length < 1e-4:
                            visitadas.add(fn.index)
                            ilha.append(fn)
                            pilha.append(fn)
            n_cabeca = sum(1 for f in ilha if f.calc_center_median().z >= z_corte)
            if (n_cabeca / float(len(ilha))) >= 0.60 and len(ilha) < 0.45 * float(total_faces):
                loops_ilha = [lp for f in ilha for lp in f.loops]
                if not loops_ilha:
                    continue
                inv_n = 1.0 / float(len(loops_ilha))
                uc = sum(lp[uv_layer].uv.x for lp in loops_ilha) * inv_n
                vc = sum(lp[uv_layer].uv.y for lp in loops_ilha) * inv_n
                for lp in loops_ilha:
                    uv = lp[uv_layer].uv
                    lp[uv_layer].uv = (uc + (uv.x - uc) * escala, vc + (uv.y - vc) * escala)
                total_escaladas += len(ilha)
        if total_escaladas > 0:
            bm.to_mesh(mesh)
            mesh.update()
        return total_escaladas
    finally:
        bm.free()
