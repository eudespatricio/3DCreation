"""Fechamento manifold de olhos/camadas .mhclo, ajuste de traje e reparo G1 pos-join."""

from __future__ import annotations

import math
import os
import sys

import bmesh
import bpy
from mathutils import Vector

if __package__:
    from . import template_body_armor_3d as _armor
    from . import template_body_assets as _assets
    from . import template_body_hair as _hair
    from . import template_body_uv as _uv
else:
    _BLENDER_DIR = os.path.dirname(os.path.abspath(__file__))
    if _BLENDER_DIR not in sys.path:
        sys.path.insert(0, _BLENDER_DIR)
    import template_body_armor_3d as _armor
    import template_body_assets as _assets
    import template_body_hair as _hair
    import template_body_uv as _uv

_bvh_filtrado = _armor._bvh_filtrado
_centro_secao_horizontal = _armor._centro_secao_horizontal
_raio_inward_bvh = _armor._raio_inward_bvh
_limpar_nao_manifold_aberto = _assets._limpar_nao_manifold_aberto
_preparar_cabelo_manifold = _hair._preparar_cabelo_manifold


def _fechar_olhos_manifold(eyes_obj) -> dict:
    """Fecha os 2 aneis traseiros de eyes/low-poly em malha 2-manifold estanque (G1=0)."""
    bm = bmesh.new()
    bm.from_mesh(eyes_obj.data)
    bmesh.ops.triangulate(bm, faces=list(bm.faces))
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1e-5)
    uv_layer = bm.loops.layers.uv.active or bm.loops.layers.uv.new("UVMap")

    # Fecha cada loop de borda conectado com um vertice central e UVs em leque na esclera branca
    for comp_idx in range(8):
        b_edges = [e for e in bm.edges if len(e.link_faces) == 1]
        if not b_edges:
            break
        e0 = b_edges[0]
        comp_v = set(e0.verts)
        comp_e = {e0}
        mudou = True
        while mudou:
            mudou = False
            for e in b_edges:
                if e not in comp_e and (e.verts[0] in comp_v or e.verts[1] in comp_v):
                    comp_e.add(e)
                    comp_v.update(e.verts)
                    mudou = True
        centro = sum((v.co for v in comp_v), Vector((0.0, 0.0, 0.0))) / float(len(comp_v))
        vc = bm.verts.new(centro)
        _uv._atribuir_uv_tampa_olho(bm, uv_layer, comp_e, comp_v, vc, comp_idx)

    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    nao_manifold = sum(1 for e in bm.edges if len(e.link_faces) != 2)
    tris = len(bm.faces)
    bm.to_mesh(eyes_obj.data)
    bm.free()
    eyes_obj.data.update()
    if nao_manifold > 0:
        return _preparar_cabelo_manifold(eyes_obj, 400)
    return {"triangulos": tris, "nao_manifold": nao_manifold, "degeneradas": 0}


def _limpar_bmesh_manifold(bm, usar_remove_doubles: bool = True, mat_idx: int | None = None) -> tuple[int, int, int]:
    """Triangula, remove slivers/degeneradas, recalcula normais e retorna (tris, nm, deg)."""
    bmesh.ops.triangulate(bm, faces=list(bm.faces))
    if usar_remove_doubles:
        bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1e-5)
    bmesh.ops.dissolve_degenerate(bm, dist=1e-6, edges=list(bm.edges))
    slivers = [f for f in bm.faces if f.calc_area() < 1e-8]
    if slivers:
        bmesh.ops.delete(bm, geom=slivers, context="FACES")
    soltas_e = [e for e in bm.edges if not e.link_faces]
    if soltas_e:
        bmesh.ops.delete(bm, geom=soltas_e, context="EDGES")
    soltos = [v for v in bm.verts if not v.link_faces]
    if soltos:
        bmesh.ops.delete(bm, geom=soltos, context="VERTS")
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    if mat_idx is not None:
        for f in bm.faces:
            f.material_index = mat_idx
    return (
        len(bm.faces),
        sum(1 for e in bm.edges if len(e.link_faces) != 2),
        sum(1 for f in bm.faces if f.calc_area() < 1e-12),
    )


def _aplicar_mod(obj, mod_name: str) -> None:
    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.modifier_apply(modifier=mod_name)


def _juntar_no_ativo(alvo_obj, extra_obj) -> None:
    bpy.ops.object.select_all(action="DESELECT")
    alvo_obj.select_set(True)
    extra_obj.select_set(True)
    bpy.context.view_layer.objects.active = alvo_obj
    bpy.ops.object.join()


def _decimar_folha_simples(camada_obj, target_solid_tris: int) -> int:
    """Decima malha de folha unica ate o orcamento previsto pos-solidificacao."""
    _limpar_nao_manifold_aberto(camada_obj)
    est_solid = 0
    for _ in range(4):
        bm_d = bmesh.new()
        bm_d.from_mesh(camada_obj.data)
        tc, bc = len(bm_d.faces), sum(1 for e in bm_d.edges if len(e.link_faces) == 1)
        bm_d.free()
        est_solid = 2 * tc + 2 * bc
        if target_solid_tris <= 0 or est_solid <= target_solid_tris:
            break
        md = camada_obj.modifiers.new("pre_dec", "DECIMATE")
        md.ratio = max(0.06, min(0.90, (target_solid_tris * 0.88) / max(1, est_solid)))
        _aplicar_mod(camada_obj, md.name)
        _limpar_nao_manifold_aberto(camada_obj)
    return est_solid


def _solidificar_limpo(
    camada_obj,
    thickness: float,
    offset: float,
    mat_idx: int | None = None,
) -> tuple[int, int, int]:
    """Aplica SOLIDIFY com espessura/offset e limpa topologia triangulada."""
    mod = camada_obj.modifiers.new("Solidify", "SOLIDIFY")
    mod.thickness = max(0.0006, float(thickness))
    mod.offset = offset
    mod.use_rim = True
    mod.use_rim_only = False
    mod.use_even_offset = False
    _aplicar_mod(camada_obj, mod.name)
    bm = bmesh.new()
    bm.from_mesh(camada_obj.data)
    tris, nm, deg = _limpar_bmesh_manifold(bm, usar_remove_doubles=True, mat_idx=mat_idx)
    bm.to_mesh(camada_obj.data)
    bm.free()
    camada_obj.data.update()
    return tris, nm, deg


def _preparar_camada_mhclo_manifold(
    camada_obj,
    target_tris: int,
    thickness: float = 0.0045,
    offset_normal: float = 0.0024,
) -> dict:
    """Converte roupa/sobrancelha .mhclo em camada 3D estanque (espessura >= 4mm, separacao >= 2mm)."""
    _limpar_nao_manifold_aberto(camada_obj)
    bm0 = bmesh.new()
    bm0.from_mesh(camada_obj.data)
    bmesh.ops.recalc_face_normals(bm0, faces=list(bm0.faces))
    bm0.normal_update()
    for v in bm0.verts:
        n = v.normal if v.normal.length > 1e-6 else Vector((0.0, -1.0, 0.0))
        v.co += n * offset_normal
    bm0.to_mesh(camada_obj.data)
    bm0.free()
    camada_obj.data.update()

    _decimar_folha_simples(camada_obj, target_tris)
    tris, nao_manifold, degeneradas = _solidificar_limpo(camada_obj, thickness, offset=1.0)
    if nao_manifold > 0:
        _limpar_nao_manifold_aberto(camada_obj)
    return {"triangulos": tris, "nao_manifold": nao_manifold, "degeneradas": degeneradas}


def _garantir_g1_pos_join(obj) -> dict:
    """Garante 0 arestas nao-manifold mesmo apos soldagem G1 (1e-5 m) do qc.topologia."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.triangulate(bm, faces=list(bm.faces))
    bm.normal_update()

    # Desloca vertices de ilhas distintas que caiam na mesma celula de 1e-4 m
    celulas: dict[tuple[int, int, int], list] = {}
    for v in bm.verts:
        chave = (int(round(v.co.x * 20000.0)), int(round(v.co.y * 20000.0)), int(round(v.co.z * 20000.0)))
        celulas.setdefault(chave, []).append(v)
    for vs in celulas.values():
        if len(vs) > 1:
            for idx, v in enumerate(vs[1:], 1):
                n = v.normal if v.normal.length > 1e-6 else Vector((0.0, -1.0, 0.0))
                v.co += n * (0.00025 * idx)

    tris, nao_manifold, degeneradas = _limpar_bmesh_manifold(bm, usar_remove_doubles=False)
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
    if nao_manifold > 0:
        _limpar_nao_manifold_aberto(obj)
        bm2 = bmesh.new()
        bm2.from_mesh(obj.data)
        nao_manifold = sum(1 for e in bm2.edges if len(e.link_faces) != 2)
        degeneradas = sum(1 for f in bm2.faces if f.calc_area() < 1e-12)
        tris = len(bm2.faces)
        bm2.free()
    return {"triangulos": tris, "nao_manifold": nao_manifold, "degeneradas": degeneradas}


def _fatia_perna(
    pernas_pts_l: list[Vector],
    pernas_pts_r: list[Vector],
    bh: float,
    z_val: float,
    lado_pos: bool,
) -> tuple[float, float, float, float]:
    ref_leg = pernas_pts_l if lado_pos else pernas_pts_r
    fat = [p for p in ref_leg if abs(p.z - z_val) <= 0.012 * bh]
    if len(fat) < 4:
        fat = [p for p in ref_leg if abs(p.z - z_val) <= 0.024 * bh]
    if len(fat) >= 4:
        cxl = 0.5 * (min(p.x for p in fat) + max(p.x for p in fat))
        cyl = 0.5 * (min(p.y for p in fat) + max(p.y for p in fat))
        rxl = max(0.018, max(abs(p.x - cxl) for p in fat))
        ryl = max(0.018, max(abs(p.y - cyl) for p in fat))
        return cxl, cyl, rxl, ryl
    return ((0.068 * bh) if lado_pos else (-0.068 * bh)), 0.0, 0.048, 0.052


def _desdobrar_arestas_agudas(bm, dot_lim: float = 0.35, passes: int = 3) -> None:
    """Suaviza vertices adjacentes a dobras agudas (dot < dot_lim) antes de solidificar."""
    for _ in range(passes):
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        alvo = set()
        for e in bm.edges:
            if len(e.link_faces) == 2 and e.link_faces[0].normal.dot(e.link_faces[1].normal) < dot_lim:
                alvo.update(e.verts)
        if not alvo:
            break
        novos: dict = {}
        for v in alvo:
            nb = [e.other_vert(v) for e in v.link_edges]
            if not nb:
                continue
            avg = sum((u.co for u in nb), Vector((0.0, 0.0, 0.0))) / float(len(nb))
            if v.is_boundary:
                novos[v] = Vector((0.5 * v.co.x + 0.5 * avg.x, 0.5 * v.co.y + 0.5 * avg.y, v.co.z))
            else:
                novos[v] = v.co.lerp(avg, 0.5)
        for v, p in novos.items():
            v.co = p


def _separar_copia_material(suit_obj, keep_mi: int):
    """Separa `keep_mi` em copia vinculada removendo-o de `suit_obj` (preserva UVs/VGs)."""
    copia = suit_obj.copy()
    copia.data = suit_obj.data.copy()
    bpy.context.collection.objects.link(copia)
    bpy.context.view_layer.update()
    for o_p, k_mi in ((suit_obj, 1 - keep_mi), (copia, keep_mi)):
        bm_p = bmesh.new()
        bm_p.from_mesh(o_p.data)
        df = [f for f in bm_p.faces if f.material_index != k_mi]
        if df:
            bmesh.ops.delete(bm_p, geom=df, context="FACES")
        sv = [v for v in bm_p.verts if not v.link_faces]
        if sv:
            bmesh.ops.delete(bm_p, geom=sv, context="VERTS")
        bm_p.to_mesh(o_p.data)
        bm_p.free()
        o_p.data.update()
    return copia


def _ajustar_malha_suit(obj, suit_obj, mat_tunic, mat_trousers) -> dict:
    """Separa tunica/calca, solidifica tunica e mantem calca em folha unica ate confinacao final."""
    b_zs = [v.co.z for v in obj.data.vertices]
    bz_min = min(b_zs)
    bh = max(0.5, max(b_zs) - bz_min)
    z_trim_bota = bz_min + 0.165 * bh

    bm_suit = bmesh.new()
    bm_suit.from_mesh(suit_obj.data)
    uv_suit = bm_suit.loops.layers.uv.active or bm_suit.loops.layers.uv.new("UVMap")

    visitados_s: set = set()
    verts_tunica: set = set()
    verts_calca: set = set()
    for v0 in bm_suit.verts:
        if v0 in visitados_s:
            continue
        pilha, comp_v = [v0], []
        visitados_s.add(v0)
        while pilha:
            vc = pilha.pop()
            comp_v.append(vc)
            for ed in vc.link_edges:
                vn = ed.other_vert(vc)
                if vn not in visitados_s:
                    visitados_s.add(vn)
                    pilha.append(vn)
        (verts_tunica if min((v.co.z - bz_min) / bh for v in comp_v) > 0.35 else verts_calca).update(comp_v)

    if verts_tunica:
        zf_hem = min((v.co.z - bz_min) / bh for v in verts_tunica)
        zf_top_blend = 0.645
        if zf_hem > 0.495 and zf_top_blend > zf_hem + 0.02:
            for v_t in verts_tunica:
                zf_v = (v_t.co.z - bz_min) / bh
                if zf_v < zf_top_blend:
                    t_w = max(0.0, min(1.0, (zf_v - zf_hem) / (zf_top_blend - zf_hem)))
                    zf_novo = 0.490 + t_w * (zf_top_blend - 0.490)
                    dz_m = (zf_novo - zf_v) * bh
                    v_t.co.z = bz_min + zf_novo * bh
                    flare_t = 1.0 + 0.035 * (1.0 - t_w)
                    v_t.co.x *= flare_t
                    v_t.co.y *= flare_t
                    for lp in v_t.link_loops:
                        lp[uv_suit].uv.y += dz_m * 0.43

    faces_remover = [
        f
        for f in bm_suit.faces
        if any(v in verts_calca for v in f.verts)
        and (f.calc_center_median().z < z_trim_bota or f.calc_center_median().z > bz_min + 0.560 * bh)
    ]
    if faces_remover:
        bmesh.ops.delete(bm_suit, geom=faces_remover, context="FACES")
        soltos_s = [v for v in bm_suit.verts if not v.link_faces]
        if soltos_s:
            bmesh.ops.delete(bm_suit, geom=soltos_s, context="VERTS")
            verts_calca.difference_update(soltos_s)

    for sv in list(bm_suit.verts):
        if sv in verts_calca:
            zf_sv = (sv.co.z - bz_min) / bh
            if zf_sv > 0.485:
                sc_w = 1.0 - 0.12 * min(1.0, (zf_sv - 0.485) / 0.055)
                sv.co.x *= sc_w
                sv.co.y *= sc_w

    suit_obj.data.materials.clear()
    suit_obj.data.materials.append(mat_tunic)
    suit_obj.data.materials.append(mat_trousers)
    for f in bm_suit.faces:
        f.material_index = 0 if any(v in verts_tunica for v in f.verts) else 1
    bm_suit.to_mesh(suit_obj.data)
    bm_suit.free()
    suit_obj.data.update()

    tem_tunica = any(p.material_index == 0 for p in suit_obj.data.polygons)
    tem_calca = any(p.material_index == 1 for p in suit_obj.data.polygons)
    if tem_tunica and tem_calca:
        calca_obj = _separar_copia_material(suit_obj, 1)
        topo_tun = _preparar_camada_mhclo_manifold(suit_obj, target_tris=800, thickness=0.0040, offset_normal=0.0018)
        est_calca = _decimar_folha_simples(calca_obj, 680)
        for p in suit_obj.data.polygons:
            p.material_index = 0
        for p in calca_obj.data.polygons:
            p.material_index = 1
        _juntar_no_ativo(suit_obj, calca_obj)
        return {
            "triangulos": topo_tun["triangulos"] + est_calca,
            "nao_manifold": topo_tun["nao_manifold"],
            "degeneradas": topo_tun["degeneradas"],
        }
    if tem_calca:
        est_calca = _decimar_folha_simples(suit_obj, 680)
        for p in suit_obj.data.polygons:
            p.material_index = 1
        return {"triangulos": est_calca, "nao_manifold": 0, "degeneradas": 0}
    topo_tun = _preparar_camada_mhclo_manifold(suit_obj, target_tris=800, thickness=0.0040, offset_normal=0.0018)
    for p in suit_obj.data.polygons:
        p.material_index = 0
    return topo_tun


def _confinar_calca_pos_decimacao(obj, suit_obj, ov_obj=None) -> None:
    """Confina calca em folha unica contra skin/botas e solidifica para dentro (offset=-1.0)."""
    if suit_obj is None or getattr(suit_obj, "data", None) is None:
        return
    if not any(p.material_index == 1 for p in suit_obj.data.polygons):
        return
    zs = [v.co.z for v in obj.data.vertices]
    if not zs:
        return
    z_min, z_max = min(zs), max(zs)
    h = max(0.5, z_max - z_min)
    r_probe, r_max = max(0.15, 0.085 * h), max(0.13, 0.075 * h)

    bvhs, bvhs_boot, centros_z = {}, {}, {}
    for sx in (-1.0, 1.0):
        bvhs[sx] = _bvh_filtrado(
            [obj],
            lambda f, s=sx: all(v.co.x * s >= 0.005 * h for v in f.verts) and min(v.co.z for v in f.verts) <= z_min + 0.34 * h,
        )
        bvhs_boot[sx] = (
            _bvh_filtrado(
                [ov_obj],
                lambda f, s=sx: all(v.co.x * s >= 0.005 * h for v in f.verts) and max(v.co.z for v in f.verts) <= z_min + 0.28 * h,
            )
            if ov_obj is not None
            else None
        )
        _, cy_s = _centro_secao_horizontal([obj], z_min + 0.155 * h, lambda p, s=sx: p.x * s >= 0.005 * h, sx * 0.068 * h, 0.0, 0.020 * h)
        centros_z[sx] = [
            (
                z_min + (0.04 + idx * 0.01) * h,
                *_centro_secao_horizontal(
                    [obj], z_min + (0.04 + idx * 0.01) * h, lambda p, s=sx, cys=cy_s: p.x * s >= 0.005 * h and p.y >= cys - 0.065 * h, sx * 0.068 * h, cy_s, 0.018 * h
                ),
            )
            for idx in range(28)
        ]

    def _centro_interp(sx: float, zq: float) -> tuple[float, float]:
        tab = centros_z[sx]
        if zq <= tab[0][0]:
            return tab[0][1], tab[0][2]
        if zq >= tab[-1][0]:
            return tab[-1][1], tab[-1][2]
        pos = (zq - tab[0][0]) / max(1e-6, 0.01 * h)
        i0 = min(len(tab) - 2, max(0, int(pos)))
        t_i = pos - float(i0)
        return (
            tab[i0][1] * (1.0 - t_i) + tab[i0 + 1][1] * t_i,
            tab[i0][2] * (1.0 - t_i) + tab[i0 + 1][2] * t_i,
        )

    tem_tunica = any(p.material_index == 0 for p in suit_obj.data.polygons)
    calca_obj = _separar_copia_material(suit_obj, 1) if tem_tunica else suit_obj

    bm = bmesh.new()
    try:
        bm.from_mesh(calca_obj.data)
        _desdobrar_arestas_agudas(bm, dot_lim=0.35, passes=3)
        for vp in bm.verts:
            zf_vp = (vp.co.z - z_min) / h
            if zf_vp > 0.300:
                continue
            sx = 1.0 if vp.co.x >= 0.0 else -1.0
            cxl, cyl = _centro_interp(sx, vp.co.z)
            dx, dy = vp.co.x - cxl, vp.co.y - cyl
            r_v = math.hypot(dx, dy)
            if r_v <= 1e-4:
                continue
            dir_xy = Vector((dx / r_v, dy / r_v, 0.0))
            r_skin = _raio_inward_bvh(bvhs[sx], Vector((cxl, cyl, vp.co.z)), dir_xy, r_probe, 0.045, 0.012, r_max)
            r_base = max(0.012, r_skin + 0.0001)
            bvh_bt = bvhs_boot.get(sx)
            if bvh_bt is not None and zf_vp <= 0.252:
                loc_bt, _, _, _ = bvh_bt.ray_cast(Vector((cxl, cyl, vp.co.z)) + dir_xy * (r_probe + 0.03), -dir_xy, r_probe + 0.03)
                if loc_bt is not None:
                    r_bt_out = (loc_bt - Vector((cxl, cyl, vp.co.z))).dot(dir_xy)
                    if r_bt_out > 0.015:
                        r_base = min(r_base, max(0.012, r_bt_out - 0.0044))
            r_lim_out = r_base if zf_vp <= 0.256 else r_base * (1.0 - (zf_vp - 0.256) / 0.044) + (r_v + 0.025) * ((zf_vp - 0.256) / 0.044)
            if r_v > r_lim_out:
                vp.co.x = cxl + dir_xy.x * r_lim_out
                vp.co.y = cyl + dir_xy.y * r_lim_out
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        bm.to_mesh(calca_obj.data)
    finally:
        bm.free()
    calca_obj.data.update()

    _solidificar_limpo(calca_obj, 0.0024, offset=-1.0, mat_idx=1)
    if tem_tunica:
        for p in suit_obj.data.polygons:
            p.material_index = 0
        _juntar_no_ativo(suit_obj, calca_obj)
