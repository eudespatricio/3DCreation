"""Contato BVH 1.5 mm e conformacao anatomica SURFACE_DEFORM + SHRINKWRAP (camada L1)."""

from __future__ import annotations

import os
import sys
from typing import Any, Sequence

if __package__:
    from .smart_fit_math import FOLGA_CONTATO_PADRAO_M, calcular_deslocamento_contato
else:
    _BLENDER_DIR = os.path.dirname(os.path.abspath(__file__))
    if _BLENDER_DIR not in sys.path:
        sys.path.insert(0, _BLENDER_DIR)
    from smart_fit_math import FOLGA_CONTATO_PADRAO_M, calcular_deslocamento_contato

try:
    import bmesh
    import bpy
    from mathutils import Euler, Matrix, Vector
    from mathutils.bvhtree import BVHTree

    HAS_BPY = True
except (ImportError, ModuleNotFoundError):
    bmesh = None  # type: ignore[assignment]
    bpy = None  # type: ignore[assignment]
    Euler = None  # type: ignore[assignment]
    Matrix = None  # type: ignore[assignment]
    Vector = None  # type: ignore[assignment]
    BVHTree = None  # type: ignore[assignment]
    HAS_BPY = False


def _exigir_bpy() -> None:
    if not HAS_BPY or BVHTree is None:
        raise RuntimeError("funcao requer Blender (bpy/bmesh/mathutils.bvhtree)")


def _bvh_mundo(alvo_obj) -> tuple[Any, Any]:
    bm = bmesh.new()
    bm.from_mesh(alvo_obj.data)
    bmesh.ops.transform(bm, matrix=alvo_obj.matrix_world, verts=bm.verts)
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    bm.normal_update()
    bvh = BVHTree.FromBMesh(bm)
    return bvh, bm


def _amostrar_vertices_mundo(obj, max_verts: int = 4000) -> list[Any]:
    mw = obj.matrix_world
    verts = obj.data.vertices
    n = len(verts)
    if n == 0:
        return []
    passo = max(1, n // max_verts)
    return [mw @ verts[i].co for i in range(0, n, passo)]


def _mover_objeto_mundo(obj, delta_mundo: Sequence[float]) -> None:
    dv = Vector((float(delta_mundo[0]), float(delta_mundo[1]), float(delta_mundo[2])))
    if obj.parent is not None:
        inv_p = obj.parent.matrix_world.to_3x3().inverted_safe()
        obj.location = obj.location + (inv_p @ dv)
    else:
        obj.location = obj.location + dv
    bpy.context.view_layer.update()


def encaixar_contato_bvh(
    peca_obj,
    alvo_obj,
    direcao: Sequence[float] | None = None,
    folga_m: float = FOLGA_CONTATO_PADRAO_M,
) -> dict[str, Any]:
    """Encaixa ``peca_obj`` contra a superficie de ``alvo_obj`` a exata ``folga_m`` via BVHTree."""
    _exigir_bpy()
    bpy.context.view_layer.update()
    if peca_obj is None or alvo_obj is None or not peca_obj.data.vertices or not alvo_obj.data.vertices:
        return {
            "deslocamento_m": [0.0, 0.0, 0.0],
            "distancia_min_antes_m": 0.0,
            "distancia_min_depois_m": 0.0,
            "folga_m": float(folga_m),
            "penetracao_resolvida": False,
        }

    bvh, bm_alvo = _bvh_mundo(alvo_obj)
    try:
        desl_acum = Vector((0.0, 0.0, 0.0))
        dist_antes_inicial: float | None = None
        penetracao_inicial = False
        dir_vec = Vector((float(direcao[0]), float(direcao[1]), float(direcao[2]))).normalized() if direcao is not None else None

        eps_ray = 1e-4
        for _ in range(4):
            pts = _amostrar_vertices_mundo(peca_obj)
            if not pts:
                break
            if dir_vec is not None:
                hits_t: list[float] = []
                dists_n: list[float] = []
                for p in pts:
                    loc, norm, _idx, _dist = bvh.ray_cast(p - dir_vec * eps_ray, dir_vec)
                    if loc is not None and norm is not None and norm.dot(dir_vec) < -1e-6:
                        hits_t.append(float((loc - p).dot(dir_vec)) - float(folga_m))
                        dists_n.append(float((p - loc).dot(norm)))
                        continue
                    orig = p + dir_vec * eps_ray
                    for _hop in range(4):
                        loc_b, norm_b, _idx_b, _dist_b = bvh.ray_cast(orig, -dir_vec)
                        if loc_b is None or norm_b is None:
                            break
                        if norm_b.dot(dir_vec) < -1e-6:
                            hits_t.append(float((loc_b - p).dot(dir_vec)) - float(folga_m))
                            dists_n.append(float((p - loc_b).dot(norm_b)))
                            break
                        orig = loc_b - dir_vec * eps_ray

                if hits_t:
                    t_step = min(hits_t)
                    if dist_antes_inicial is None:
                        dist_antes_inicial = min(dists_n) if dists_n else min(hits_t) + float(folga_m)
                        penetracao_inicial = any(d < 0.0 for d in dists_n)
                    if abs(t_step) < 1e-5:
                        break
                    delta = dir_vec * t_step
                    _mover_objeto_mundo(peca_obj, delta)
                    desl_acum += delta
                    continue

            amostras_n: list[tuple[tuple[float, float, float], tuple[float, float, float]]] = []
            pts_filtrados: list[tuple[float, float, float]] = []
            for p in pts:
                loc, norm, _idx, _dist = bvh.find_nearest(p)
                if loc is not None and norm is not None:
                    pts_filtrados.append((p.x, p.y, p.z))
                    amostras_n.append(((loc.x, loc.y, loc.z), (norm.x, norm.y, norm.z)))
            if not pts_filtrados:
                break
            calc = calcular_deslocamento_contato(
                pts_filtrados,
                amostras_n,
                direcao=(dir_vec.x, dir_vec.y, dir_vec.z) if dir_vec is not None else None,
                folga_m=folga_m,
            )
            if dist_antes_inicial is None:
                dist_antes_inicial = float(calc["distancia_antes_m"])
                penetracao_inicial = bool(calc["penetrando"])
            delta = Vector(calc["deslocamento"])
            if delta.length < 1e-5:
                break
            _mover_objeto_mundo(peca_obj, delta)
            desl_acum += delta

        pts_fim = _amostrar_vertices_mundo(peca_obj)
        dists_fim: list[float] = []
        sds_fim: list[float] = []
        for p in pts_fim:
            loc, norm, _idx, dist = bvh.find_nearest(p)
            if loc is not None and norm is not None:
                dists_fim.append(float(dist))
                sds_fim.append(float((p - loc).dot(norm)))
        dist_depois = min(sds_fim) if (sds_fim and min(sds_fim) < 0.0) else (min(dists_fim) if dists_fim else 0.0)
    finally:
        bm_alvo.free()

    return {
        "deslocamento_m": [round(desl_acum.x, 6), round(desl_acum.y, 6), round(desl_acum.z, 6)],
        "distancia_min_antes_m": round(float(dist_antes_inicial or 0.0), 6),
        "distancia_min_depois_m": round(float(dist_depois), 6),
        "folga_m": float(folga_m),
        "penetracao_resolvida": bool(penetracao_inicial and dist_depois >= -1e-4),
    }


def _nao_manifold_bmesh(obj) -> int:
    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        return sum(1 for e in bm.edges if len(e.link_faces) != 2)
    finally:
        bm.free()


def _limpar_topologia_smart_fit(obj) -> int:
    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        bmesh.ops.dissolve_degenerate(bm, dist=1e-6, edges=list(bm.edges))
        slivers = [f for f in bm.faces if f.calc_area() < 1e-10]
        if slivers:
            bmesh.ops.delete(bm, geom=slivers, context="FACES")
        soltas_e = [e for e in bm.edges if not e.link_faces]
        if soltas_e:
            bmesh.ops.delete(bm, geom=soltas_e, context="EDGES")
        soltos_v = [v for v in bm.verts if not v.link_faces]
        if soltos_v:
            bmesh.ops.delete(bm, geom=soltos_v, context="VERTS")
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        nao_manifold = sum(1 for e in bm.edges if len(e.link_faces) != 2)
        bm.to_mesh(obj.data)
        obj.data.update()
        return nao_manifold
    finally:
        bm.free()


def _peca_envolve_corpo_xy(peca_obj, corpo_obj) -> bool:
    """Retorna True se ``peca_obj`` envolve o centro XY de ``corpo_obj`` em ao menos 3 direcoes."""
    p_verts = _amostrar_vertices_mundo(peca_obj, max_verts=2000)
    c_verts = _amostrar_vertices_mundo(corpo_obj, max_verts=2000)
    if not p_verts or not c_verts:
        return False
    p_xs = [v.x for v in p_verts]
    p_ys = [v.y for v in p_verts]
    p_zs = [v.z for v in p_verts]
    c_xs = [v.x for v in c_verts]
    c_ys = [v.y for v in c_verts]
    c_cx = 0.5 * (min(c_xs) + max(c_xs))
    c_cy = 0.5 * (min(c_ys) + max(c_ys))
    if not (min(p_xs) < c_cx < max(p_xs) and min(p_ys) < c_cy < max(p_ys)):
        return False
    z_probe = 0.5 * (min(p_zs) + max(p_zs))
    span_xy = max(max(p_xs) - min(p_xs), max(p_ys) - min(p_ys)) + 0.1
    origem = Vector((c_cx, c_cy, z_probe))
    bvh_p, bm_p = _bvh_mundo(peca_obj)
    try:
        hits = 0
        for d in ((1.0, 0.0, 0.0), (-1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, -1.0, 0.0)):
            if bvh_p.ray_cast(origem, Vector(d), span_xy)[0] is not None:
                hits += 1
        return hits >= 3
    finally:
        bm_p.free()


def _aplicar_surface_deform_cage(peca_obj, corpo_obj, folga_m: float) -> tuple[bool, float, str | None]:
    """Cria gaiola adaptativa triangulada sobre ``corpo_obj`` e aplica SURFACE_DEFORM real."""
    bvh_p, bm_p = _bvh_mundo(peca_obj)
    try:
        p_coords = [v.co for v in bm_p.verts]
        if not p_coords:
            return False, 0.0, "peca_sem_vertices"
        p_min = Vector((min(p.x for p in p_coords), min(p.y for p in p_coords), min(p.z for p in p_coords)))
        p_max = Vector((max(p.x for p in p_coords), max(p.y for p in p_coords), max(p.z for p in p_coords)))
        p_diag = max((p_max - p_min).length, 0.05)
        margin = max(0.06, 0.35 * p_diag)
        box_min = p_min - Vector((margin, margin, margin))
        box_max = p_max + Vector((margin, margin, margin))

        bm_cage = bmesh.new()
        try:
            bm_cage.from_mesh(corpo_obj.data)
            bmesh.ops.transform(bm_cage, matrix=corpo_obj.matrix_world, verts=bm_cage.verts)
            bmesh.ops.recalc_face_normals(bm_cage, faces=list(bm_cage.faces))
            target_edge = max(0.015, min(0.035, p_diag * 0.15))
            for _ in range(5):
                if len(bm_cage.verts) >= 6000:
                    break
                long_edges = [
                    e for e in bm_cage.edges
                    if (e.verts[0].co - e.verts[1].co).length > target_edge
                    and any(
                        box_min.x <= v.co.x <= box_max.x
                        and box_min.y <= v.co.y <= box_max.y
                        and box_min.z <= v.co.z <= box_max.z
                        for v in e.verts
                    )
                ]
                if not long_edges:
                    break
                bmesh.ops.subdivide_edges(bm_cage, edges=long_edges, cuts=1, use_grid_fill=True)
            bmesh.ops.triangulate(bm_cage, faces=list(bm_cage.faces))
            bmesh.ops.recalc_face_normals(bm_cage, faces=list(bm_cage.faces))
            bm_cage.normal_update()
            bm_cage.verts.index_update()

            base_cos = [v.co.copy() for v in bm_cage.verts]
            normals = [v.normal.normalized() if v.normal.length > 1e-8 else Vector((0.0, 0.0, 1.0)) for v in bm_cage.verts]
            target_cos = [p + n * float(folga_m) for p, n in zip(base_cos, normals)]
            in_box = [
                box_min.x <= p.x <= box_max.x and box_min.y <= p.y <= box_max.y and box_min.z <= p.z <= box_max.z
                for p in base_cos
            ]
            offsets: list[float] = []
            for p0, n0, inside in zip(base_cos, normals, in_box):
                if not inside:
                    offsets.append(float(folga_m))
                    continue
                loc, _np, _idx, _d = bvh_p.ray_cast(p0 - n0 * 0.02, n0, p_diag * 2.0 + 0.2)
                if loc is not None:
                    offsets.append(float((loc - p0).dot(n0)))
                    continue
                loc_n, _np2, _idx2, d_n = bvh_p.find_nearest(p0, margin * 1.5)
                if loc_n is not None:
                    w = max(0.0, 1.0 - float(d_n) / (margin * 1.5))
                    offsets.append(float(folga_m) + w * (float((loc_n - p0).dot(n0)) - float(folga_m)))
                else:
                    offsets.append(float(folga_m))

            nbrs = [[e.other_vert(v).index for e in v.link_edges] for v in bm_cage.verts]
            for _ in range(3):
                novos = list(offsets)
                for idx, inside in enumerate(in_box):
                    if inside and nbrs[idx]:
                        novos[idx] = 0.5 * offsets[idx] + 0.5 * (sum(offsets[j] for j in nbrs[idx]) / len(nbrs[idx]))
                offsets = novos

            for i, v in enumerate(bm_cage.verts):
                v.co = base_cos[i] + normals[i] * offsets[i]

            me_cage = bpy.data.meshes.new("_SmartFitCageMesh")
            bm_cage.to_mesh(me_cage)
        finally:
            bm_cage.free()
    finally:
        bm_p.free()

    cage = bpy.data.objects.new("_SmartFitCage", me_cage)
    bpy.context.collection.objects.link(cage)
    try:
        bpy.context.view_layer.objects.active = peca_obj
        mod_sd = peca_obj.modifiers.new("SmartFitSurfaceDeform", "SURFACE_DEFORM")
        mod_sd.target = cage
        bpy.ops.object.surfacedeform_bind(modifier=mod_sd.name)
        if not mod_sd.is_bound:
            peca_obj.modifiers.remove(mod_sd)
            return False, 0.0, "surface_deform_nao_vinculado"
        for v, tco in zip(cage.data.vertices, target_cos):
            v.co = tco
        cage.data.update()
        bpy.context.view_layer.update()
        mw_p = peca_obj.matrix_world
        v_pre = [mw_p @ v.co for v in peca_obj.data.vertices]
        bpy.ops.object.modifier_apply(modifier=mod_sd.name)
        max_disp = max(((mw_p @ v.co - p).length for v, p in zip(peca_obj.data.vertices, v_pre)), default=0.0)
        return True, float(max_disp), None
    except (RuntimeError, ValueError, TypeError) as exc:
        print(f"[smart_fit] aviso SURFACE_DEFORM falhou: {exc}", file=sys.stderr)
        if "SmartFitSurfaceDeform" in peca_obj.modifiers:
            peca_obj.modifiers.remove(peca_obj.modifiers["SmartFitSurfaceDeform"])
        return False, 0.0, str(exc)
    finally:
        bpy.data.objects.remove(cage, do_unlink=True)
        if me_cage.users == 0:
            bpy.data.meshes.remove(me_cage)


def conformar_anatomico(
    peca_obj,
    corpo_obj,
    folga_m: float = FOLGA_CONTATO_PADRAO_M,
    usar_surface_deform: bool = True,
) -> dict[str, Any]:
    """Conforma ``peca_obj`` anatomicamente sobre ``corpo_obj`` com folga ``folga_m``."""
    _exigir_bpy()
    if peca_obj is None or corpo_obj is None or not peca_obj.data.vertices or not corpo_obj.data.vertices:
        return {"aplicado": False, "folga_m": float(folga_m), "nao_manifold": 0}

    bpy.context.view_layer.update()
    bvh, bm_corpo = _bvh_mundo(corpo_obj)
    try:
        pts_pre = _amostrar_vertices_mundo(peca_obj, max_verts=2000)
        min_pre = min(
            (bvh.find_nearest(p)[3] for p in pts_pre if bvh.find_nearest(p)[0] is not None),
            default=0.0,
        )
    finally:
        bm_corpo.free()

    if min_pre > float(folga_m) + 0.005 and not _peca_envolve_corpo_xy(peca_obj, corpo_obj):
        encaixar_contato_bvh(peca_obj, corpo_obj, folga_m=folga_m)

    bm_check = bmesh.new()
    try:
        bm_check.from_mesh(peca_obj.data)
        eh_aberta = any(e.is_boundary for e in bm_check.edges)
    finally:
        bm_check.free()

    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = peca_obj
    peca_obj.select_set(True)
    if peca_obj.parent is None:
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

    usou_sd, disp_sd, erro_sd = (
        _aplicar_surface_deform_cage(peca_obj, corpo_obj, folga_m)
        if usar_surface_deform
        else (False, 0.0, None)
    )

    if eh_aberta:
        mod_sw = peca_obj.modifiers.new("SmartFitShrinkwrap", "SHRINKWRAP")
        mod_sw.target = corpo_obj
        mod_sw.wrap_method = "TARGET_PROJECT"
        mod_sw.wrap_mode = "OUTSIDE_SURFACE"
        mod_sw.offset = float(folga_m)
        mod_sw.use_negative_direction = True
        mod_sw.use_positive_direction = True
        bpy.ops.object.modifier_apply(modifier=mod_sw.name)
        metodo = "shrinkwrap_plus_surface_deform" if usou_sd else "shrinkwrap_outside"
    else:
        vg_nome = "_smart_fit_inner"
        vg_inner = peca_obj.vertex_groups.get(vg_nome) or peca_obj.vertex_groups.new(name=vg_nome)
        bvh_c, bm_c = _bvh_mundo(corpo_obj)
        try:
            mw_p = peca_obj.matrix_world
            rot_p = mw_p.to_3x3()
            dists_v: list[tuple[int, float, Vector, Vector]] = []
            for v in peca_obj.data.vertices:
                pw = mw_p @ v.co
                nw = (rot_p @ v.normal).normalized()
                loc, norm, _idx, _dist = bvh_c.find_nearest(pw)
                if loc is not None and norm is not None:
                    dists_v.append((v.index, float((pw - loc).dot(norm)), nw, norm))
            if dists_v:
                sd_min = min(x[1] for x in dists_v)
                sd_max = max(x[1] for x in dists_v)
                corte_inner = sd_min + 0.45 * max(sd_max - sd_min, 0.004)
                for vi, sd, nw, norm in dists_v:
                    if sd <= corte_inner or nw.dot(norm) < -0.15:
                        vg_inner.add([vi], 1.0, "REPLACE")
        finally:
            bm_c.free()

        mod_sw = peca_obj.modifiers.new("SmartFitShrinkwrap", "SHRINKWRAP")
        mod_sw.target = corpo_obj
        mod_sw.wrap_method = "TARGET_PROJECT"
        mod_sw.wrap_mode = "OUTSIDE_SURFACE"
        mod_sw.offset = float(folga_m)
        mod_sw.vertex_group = vg_nome
        mod_sw.use_negative_direction = True
        mod_sw.use_positive_direction = True
        bpy.ops.object.modifier_apply(modifier=mod_sw.name)
        vg_rem = peca_obj.vertex_groups.get(vg_nome)
        if vg_rem is not None:
            peca_obj.vertex_groups.remove(vg_rem)
        metodo = "shrinkwrap_inner_group_surface_deform" if usou_sd else "shrinkwrap_inner_group"

        bvh_p, bm_p = _bvh_mundo(corpo_obj)
        try:
            mw_p = peca_obj.matrix_world
            mw_inv = mw_p.inverted_safe()
            alterou = False
            for v in peca_obj.data.vertices:
                pw = mw_p @ v.co
                loc, norm, _idx, _dist = bvh_p.find_nearest(pw)
                if loc is not None and norm is not None:
                    if float((pw - loc).dot(norm)) < float(folga_m):
                        v.co = mw_inv @ (loc + norm * float(folga_m))
                        alterou = True
            if alterou:
                peca_obj.data.update()
        finally:
            bm_p.free()

    nao_manifold = _limpar_topologia_smart_fit(peca_obj)
    bvh_f, bm_f = _bvh_mundo(corpo_obj)
    try:
        pts_pos = _amostrar_vertices_mundo(peca_obj, max_verts=2000)
        dist_final = min(
            (bvh_f.find_nearest(p)[3] for p in pts_pos if bvh_f.find_nearest(p)[0] is not None),
            default=0.0,
        )
    finally:
        bm_f.free()

    peca_obj.select_set(False)
    res: dict[str, Any] = {
        "aplicado": True,
        "metodo": metodo,
        "folga_m": float(folga_m),
        "usar_surface_deform": bool(usar_surface_deform),
        "surface_deform_aplicado": bool(usou_sd),
        "surface_deform_deslocamento_max_m": round(float(disp_sd), 6),
        "nao_manifold": int(nao_manifold),
        "distancia_min_m": round(float(dist_final), 6),
    }
    if erro_sd is not None:
        res["surface_deform_erro"] = erro_sd
    return res
