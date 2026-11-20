"""Geracao, validacao e bake de UVs limpos (G3) para camadas do template_body."""

from __future__ import annotations

import math
import os
import sys
import tempfile

import bmesh
import bpy
from mathutils import Vector

if __package__:
    from . import modular_armor as _ma
else:
    _BLENDER_DIR = os.path.dirname(os.path.abspath(__file__))
    if _BLENDER_DIR not in sys.path:
        sys.path.insert(0, _BLENDER_DIR)
    import modular_armor as _ma


def _uv_saudavel_grupo(
    obj,
    *,
    mat_indices: set[int] | None = None,
    uv_name: str | None = None,
    max_density_ratio: float = 200.0,
    grupo_unico: bool = False,
) -> bool:
    me = getattr(obj, "data", None)
    if me is None or not me.uv_layers or len(me.polygons) == 0:
        return bool(me is not None and len(me.polygons) == 0)
    bm = bmesh.new()
    try:
        bm.from_mesh(me)
        uv_lay = (bm.loops.layers.uv.get(uv_name) if uv_name else None) or bm.loops.layers.uv.active
        if uv_lay is None:
            return False
        grupos: dict[int, list] = {}
        ratios: dict[int, list[float]] = {}
        area_tot: dict[int, float] = {}
        for f in bm.faces:
            mi_orig = int(f.material_index)
            if mat_indices is not None and mi_orig not in mat_indices:
                continue
            mi = 0 if grupo_unico else mi_orig
            lps = list(f.loops)
            if len(lps) < 3:
                continue
            for lp in lps:
                u, v = float(lp[uv_lay].uv[0]), float(lp[uv_lay].uv[1])
                if not math.isfinite(u) or not math.isfinite(v) or u < -1e-4 or u > 1.0001 or v < -1e-4 or v > 1.0001:
                    return False
            g_list = grupos.setdefault(mi, [])
            r_list = ratios.setdefault(mi, [])
            for k in range(1, len(lps) - 1):
                a3 = _ma._area_tri_3d_vec(lps[0].vert.co, lps[k].vert.co, lps[k + 1].vert.co)
                a = (float(lps[0][uv_lay].uv[0]), float(lps[0][uv_lay].uv[1]))
                b = (float(lps[k][uv_lay].uv[0]), float(lps[k][uv_lay].uv[1]))
                c = (float(lps[k + 1][uv_lay].uv[0]), float(lps[k + 1][uv_lay].uv[1]))
                a2 = _ma._area_tri_2d_uv(a, b, c)
                if a3 > 1e-10 and a2 <= 1e-10:
                    return False
                area_tot[mi] = area_tot.get(mi, 0.0) + a2
                if a2 > 1e-10:
                    g_list.append((a, b, c, a2, min(a[0], b[0], c[0]), min(a[1], b[1], c[1]), max(a[0], b[0], c[0]), max(a[1], b[1], c[1])))
                    if a3 > 1e-6:
                        r_list.append(a2 / a3)
        for mi, a_sum in area_tot.items():
            if a_sum < 1e-8 or _ma._grupo_uv_sobreposto(grupos.get(mi, [])):
                return False
            rs = ratios.get(mi, [])
            if len(rs) >= 2 and min(rs) > 0.0 and (max(rs) / min(rs)) > max_density_ratio:
                return False
        return True
    finally:
        bm.free()


def _empacotar_shelves_bmesh(bm, uv_lay, faces: list, uv_box: tuple[float, float, float, float] = (0.02, 0.02, 0.98, 0.98)) -> None:
    if not faces:
        return
    u_lo, v_lo, u_hi, v_hi = uv_box
    scale_area = max(1e-4, ((u_hi - u_lo) * (v_hi - v_lo)) / (0.96 * 0.96))
    s_floor_min = 2.0e-4 / math.sqrt(scale_area)
    itens, soma_a = [], 0.0
    for idx, f in enumerate(faces):
        lps = list(f.loops)
        a3 = sum(_ma._area_tri_3d_vec(lps[0].vert.co, lps[k].vert.co, lps[k + 1].vert.co) for k in range(1, len(lps) - 1))
        a_ref = max(a3 / max(1, len(lps) - 2), 1e-10)
        itens.append((idx, a_ref, 0.5 if len(lps) == 3 else 0.35, s_floor_min))
        soma_a += a_ref

    rho_hi = min(1.0e6, 0.5 / max(soma_a, 1e-12))
    pos = _ma._empacotar_shelves_uv(itens, rho_hi, 0.02, 0.98, 2.0e-5, s_floor_min, 0.90)
    if pos is None:
        rho_lo = rho_hi
        for _ in range(28):
            rho_lo *= 0.5
            pos = _ma._empacotar_shelves_uv(itens, rho_lo, 0.02, 0.98, 2.0e-5, s_floor_min, 0.90)
            if pos is not None:
                break
        if pos is None:
            pos = _ma._empacotar_shelves_uv(itens, 0.0, 0.02, 0.98, 2.0e-5, s_floor_min, 0.90)
    if pos is None:
        cols = max(1, int(math.ceil(math.sqrt(len(faces)))))
        step = 0.96 / cols
        pos = [(0.02 + (i % cols) * step, 0.02 + (i // cols) * step, max(1e-6, step - 2.0e-5)) for i in range(len(faces))]

    sx, sy = (u_hi - u_lo) / 0.96, (v_hi - v_lo) / 0.96
    for idx, f in enumerate(faces):
        u0, v0, s_i = pos[idx]
        lps = list(f.loops)
        m = len(lps)
        if m == 3:
            raw_uv = ((u0, v0), (u0 + s_i, v0), (u0, v0 + s_i))
        else:
            cx, cy, rad = u0 + 0.5 * s_i, v0 + 0.5 * s_i, 0.48 * s_i
            raw_uv = tuple((cx + rad * math.cos(2.0 * math.pi * k / m), cy + rad * math.sin(2.0 * math.pi * k / m)) for k in range(m))
        for lp, (u_r, v_r) in zip(lps, raw_uv):
            lp[uv_lay].uv = (u_lo + (u_r - 0.02) * sx, v_lo + (v_r - 0.02) * sy)


def _atribuir_uv_tampa_olho(bm, uv_layer, comp_e: set, comp_v: set, vc, comp_idx: int) -> None:
    """Fecha anel de borda ocular como leque regular em regiao limpa da esclera branca."""
    adj: dict = {v: [] for v in comp_v}
    for e in comp_e:
        adj[e.verts[0]].append(e.verts[1])
        adj[e.verts[1]].append(e.verts[0])
    ordered: list = []
    if comp_v and all(len(nb) == 2 for nb in adj.values()):
        cur, prev = next(iter(comp_v)), None
        for _ in range(len(comp_v)):
            ordered.append(cur)
            nxt = [v for v in adj[cur] if v is not prev]
            if not nxt or nxt[0] is ordered[0]:
                break
            prev, cur = cur, nxt[0]
    if len(ordered) != len(comp_v):
        vs = list(comp_v)
        r0 = (vs[0].co - vc.co).normalized() if (vs[0].co - vc.co).length > 1e-6 else Vector((1.0, 0.0, 0.0))
        n_avg = sum(((vs[i].co - vc.co).cross(vs[(i + 1) % len(vs)].co - vc.co) for i in range(len(vs))), Vector((0.0, 0.0, 0.0)))
        nrm = n_avg.normalized() if n_avg.length > 1e-6 else Vector((0.0, 1.0, 0.0))
        t2 = nrm.cross(r0).normalized()
        t1 = t2.cross(nrm).normalized()
        ordered = sorted(vs, key=lambda v: math.atan2((v.co - vc.co).dot(t2), (v.co - vc.co).dot(t1)))

    if comp_idx < 2:
        cx, cy, rad = 0.07 + 0.10 * comp_idx, 0.92, 0.04
    else:
        col, row = (comp_idx - 2) % 4, (comp_idx - 2) // 4
        cx, cy, rad = 0.045 + col * 0.05, max(0.74, 0.83 - row * 0.05), 0.02

    n = max(1, len(ordered))
    uv_map = {v: (cx + rad * math.cos(2.0 * math.pi * k / n), cy + rad * math.sin(2.0 * math.pi * k / n)) for k, v in enumerate(ordered)}
    uv_map[vc] = (cx, cy)
    for k in range(n):
        try:
            f = bm.faces.new((ordered[k], ordered[(k + 1) % n], vc))
            for lp in f.loops:
                lp[uv_layer].uv = uv_map[lp.vert]
        except ValueError:
            pass


def preparar_brow_manifold(brow_obj, *, thickness: float = 0.0008, offset_normal: float = 0.0009) -> dict:
    """Solidifica sobrancelha em bmesh mantendo UVs frontais e empacotando verso/borda na faixa alfa=0."""
    bm = bmesh.new()
    try:
        bm.from_mesh(brow_obj.data)
        bmesh.ops.triangulate(bm, faces=list(bm.faces))
        bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1e-5)
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        bm.normal_update()
        uv_lay, dl = bm.loops.layers.uv.active or bm.loops.layers.uv.new("UVMap"), bm.verts.layers.deform.active
        orig_faces, orig_edges, v_in = list(bm.faces), list(bm.edges), {}
        for v in list(bm.verts):
            n = v.normal.copy() if v.normal.length > 1e-6 else Vector((0.0, -1.0, 0.0))
            base_co = v.co + n * offset_normal
            v.co = base_co + n * thickness
            vi = bm.verts.new(base_co)
            if dl is not None:
                for g_idx, w in v[dl].items():
                    vi[dl][g_idx] = w
            v_in[v] = vi
        back_rim = []
        for f in orig_faces:
            try:
                back_rim.append(bm.faces.new(tuple(v_in[v] for v in reversed(f.verts))))
            except ValueError:
                pass
        for e in orig_edges:
            if len(e.link_faces) != 1:
                continue
            vs_f = list(e.link_faces[0].verts)
            idx_a = vs_f.index(e.verts[0])
            va, vb = (e.verts[0], e.verts[1]) if vs_f[(idx_a + 1) % len(vs_f)] is e.verts[1] else (e.verts[1], e.verts[0])
            for tri in ((vb, va, v_in[va]), (vb, v_in[va], v_in[vb])):
                try:
                    back_rim.append(bm.faces.new(tri))
                except ValueError:
                    pass
        _empacotar_shelves_bmesh(bm, uv_lay, back_rim, (0.02, 0.02, 0.98, 0.20))
        bmesh.ops.dissolve_degenerate(bm, dist=1e-6, edges=list(bm.edges))
        slivers = [f for f in bm.faces if f.calc_area() < 1e-8]
        if slivers:
            bmesh.ops.delete(bm, geom=slivers, context="FACES")
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        nm, deg, tris = sum(1 for e in bm.edges if len(e.link_faces) != 2), sum(1 for f in bm.faces if f.calc_area() < 1e-12), len(bm.faces)
        bm.to_mesh(brow_obj.data)
    finally:
        bm.free()
    brow_obj.data.update()
    if not _uv_saudavel_grupo(brow_obj):
        _fallback_uv_disjunto_subset(brow_obj)
    return {"triangulos": tris, "nao_manifold": nm, "degeneradas": deg}


def _fallback_uv_disjunto_subset(obj, mat_indices: set[int] | None = None, uv_name: str | None = None) -> None:
    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        uv_lay = (bm.loops.layers.uv.get(uv_name) if uv_name else None) or bm.loops.layers.uv.active or bm.loops.layers.uv.new("UVMap")
        _empacotar_shelves_bmesh(bm, uv_lay, [f for f in bm.faces if mat_indices is None or int(f.material_index) in mat_indices])
        bm.to_mesh(obj.data)
    finally:
        bm.free()
    obj.data.update()


def _smart_project_subset(
    obj,
    mat_indices: set[int] | None = None,
    uv_name: str | None = None,
    *,
    grupo_unico: bool = False,
    max_density_ratio: float = 200.0,
) -> None:
    if not obj.data.uv_layers:
        obj.data.uv_layers.new(name=uv_name or "UVMap")
    if uv_name and uv_name in obj.data.uv_layers:
        obj.data.uv_layers.active = obj.data.uv_layers[uv_name]
    prev_mode = getattr(obj, "mode", "OBJECT") or "OBJECT"
    tentativas = (
        ((45.0, 0.003), (35.0, 0.003), (25.0, 0.004))
        if grupo_unico
        else ((30.0, 0.02), (15.0, 0.03), (5.0, 0.04))
    )
    try:
        for ang_deg, margin in tentativas:
            bpy.ops.object.select_all(action="DESELECT")
            bpy.context.view_layer.objects.active = obj
            obj.select_set(True)
            try:
                bpy.ops.object.mode_set(mode="EDIT")
                bpy.ops.mesh.select_mode(type="FACE")
                bm = bmesh.from_edit_mesh(obj.data)
                for f in bm.faces:
                    f.select = mat_indices is None or int(f.material_index) in mat_indices
                bmesh.update_edit_mesh(obj.data)
                bpy.ops.uv.smart_project(
                    angle_limit=math.radians(ang_deg),
                    island_margin=margin,
                    area_weight=0.5,
                    correct_aspect=True,
                    scale_to_bounds=False,
                )
            finally:
                if getattr(obj, "mode", "OBJECT") != "OBJECT":
                    bpy.ops.object.mode_set(mode="OBJECT")
            if _uv_saudavel_grupo(
                obj,
                mat_indices=mat_indices,
                uv_name=uv_name,
                max_density_ratio=max_density_ratio,
                grupo_unico=grupo_unico,
            ):
                return
        _fallback_uv_disjunto_subset(obj, mat_indices=mat_indices, uv_name=uv_name)
    finally:
        if prev_mode != "OBJECT" and getattr(obj, "mode", "OBJECT") != prev_mode:
            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.mode_set(mode=prev_mode)


def assar_textura_uv_limpa(obj, mat, saida: str, tex_px: int, *, png_nome: str | None = None, com_alfa: bool = False) -> str | None:
    """Re-desdobra malha para UV uniforme e assa baseColor (e alpha opcional) via Cycles EMIT."""
    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        bmesh.ops.triangulate(bm, faces=list(bm.faces))
        bmesh.ops.dissolve_degenerate(bm, dist=1e-6, edges=list(bm.edges))
        slivers = [f for f in bm.faces if f.calc_area() < 1e-8]
        if slivers:
            bmesh.ops.delete(bm, geom=slivers, context="FACES")
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        bm.to_mesh(obj.data)
    finally:
        bm.free()
    obj.data.update()
    if not obj.data.uv_layers:
        obj.data.uv_layers.new(name="UVMap")
    uv_orig_name = obj.data.uv_layers[0].name
    uv_clean = obj.data.uv_layers.new(name="UVMap_clean")
    obj.data.uv_layers.active = uv_clean
    _smart_project_subset(obj, uv_name=uv_clean.name)

    src_img, src_tex_node, fallback_col = None, None, (0.75, 0.55, 0.42, 1.0)
    if mat and mat.use_nodes:
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if bsdf and "Base Color" in bsdf.inputs:
            c = bsdf.inputs["Base Color"].default_value
            fallback_col = (float(c[0]), float(c[1]), float(c[2]), 1.0)
        for n in mat.node_tree.nodes:
            if n.type == "TEX_IMAGE" and n.image is not None:
                src_img, src_tex_node = n.image, n
                break

    sc = bpy.context.scene
    ant = (sc.render.engine, sc.cycles.samples, sc.cycles.device, sc.render.bake.margin, sc.render.image_settings.color_mode, list(obj.data.materials), [int(p.material_index) for p in obj.data.polygons])
    mat_bake = bpy.data.materials.new("_f3d_bake_uv")
    mat_bake.use_nodes = True
    nt = mat_bake.node_tree
    nt.nodes.clear()
    out_n, em_n = nt.nodes.new("ShaderNodeOutputMaterial"), nt.nodes.new("ShaderNodeEmission")
    nt.links.new(em_n.outputs["Emission"], out_n.inputs["Surface"])
    if src_img is not None:
        uv_n, ti_n = nt.nodes.new("ShaderNodeUVMap"), nt.nodes.new("ShaderNodeTexImage")
        uv_n.uv_map, ti_n.image = uv_orig_name, src_img
        nt.links.new(uv_n.outputs["UV"], ti_n.inputs["Vector"])
        nt.links.new(ti_n.outputs["Color"], em_n.inputs["Color"])
    else:
        em_n.inputs["Color"].default_value = fallback_col

    img_rgb = bpy.data.images.new("_f3d_bake_rgb", width=tex_px, height=tex_px, alpha=True)
    dst_n = nt.nodes.new("ShaderNodeTexImage")
    dst_n.image = img_rgb
    nt.nodes.active = dst_n
    img_a, out_path = None, os.path.join(saida, png_nome) if png_nome else None
    try:
        obj.hide_render = False
        obj.data.materials.clear()
        obj.data.materials.append(mat_bake)
        for p in obj.data.polygons:
            p.material_index = 0
        for lyr in obj.data.uv_layers:
            lyr.active_render = lyr.name == uv_clean.name
        obj.data.uv_layers.active = uv_clean
        sc.render.engine, sc.cycles.samples, sc.cycles.device, sc.render.bake.margin = "CYCLES", 1, "CPU", 8
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.bake(type="EMIT")
        if com_alfa and src_img is not None:
            nt.links.new(ti_n.outputs["Alpha"], em_n.inputs["Color"])
            img_a = bpy.data.images.new("_f3d_bake_a", width=tex_px, height=tex_px, alpha=False)
            dst_n.image = img_a
            bpy.ops.object.bake(type="EMIT")
            px_rgb, px_a = list(img_rgb.pixels), list(img_a.pixels)
            op = [k for k in range(0, len(px_rgb), 4) if px_a[k] >= 0.5]
            ar, ag, ab = sum(px_rgb[k] for k in op) / max(1, len(op)), sum(px_rgb[k + 1] for k in op) / max(1, len(op)), sum(px_rgb[k + 2] for k in op) / max(1, len(op))
            for k in range(0, len(px_rgb), 4):
                a_v = max(0.0, min(1.0, px_a[k]))
                px_rgb[k + 3] = a_v
                if a_v < 0.5:
                    px_rgb[k], px_rgb[k + 1], px_rgb[k + 2] = ar, ag, ab
            img_rgb.pixels[:] = px_rgb

        sc.render.image_settings.color_mode = "RGBA"
        if out_path is not None:
            img_rgb.filepath_raw, img_rgb.file_format = out_path, "PNG"
            img_rgb.save()
            img_rgb.pack()
            alvo_img = img_rgb
        else:
            fd_t, tmp_png = tempfile.mkstemp(prefix="f3d_uv_bake_", suffix=".png")
            os.close(fd_t)
            try:
                img_rgb.filepath_raw, img_rgb.file_format = tmp_png, "PNG"
                img_rgb.save()
                alvo_img = bpy.data.images.load(tmp_png)
                alvo_img.name = f"{mat.name}_baked" if mat else "baked_tex"
                try:
                    alvo_img.colorspace_settings.name = "sRGB"
                except (TypeError, ValueError, AttributeError, RuntimeError) as exc:
                    print(f"[template_body_uv] colorspace sRGB indisponivel: {exc}", file=sys.stderr)
                alvo_img.pack()
            finally:
                if os.path.exists(tmp_png):
                    os.unlink(tmp_png)
            bpy.data.images.remove(img_rgb)
        if src_tex_node is not None:
            src_tex_node.image = alvo_img
        elif mat and mat.use_nodes and mat.node_tree.nodes.get("Principled BSDF") is not None:
            tn = mat.node_tree.nodes.new("ShaderNodeTexImage")
            tn.image = alvo_img
            mat.node_tree.links.new(tn.outputs["Color"], mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"])
    finally:
        obj.data.materials.clear()
        for m in ant[5]:
            obj.data.materials.append(m)
        for p, mi in zip(obj.data.polygons, ant[6]):
            p.material_index = mi
        sc.render.engine, sc.cycles.samples, sc.cycles.device, sc.render.bake.margin, sc.render.image_settings.color_mode = ant[:5]
        bpy.data.materials.remove(mat_bake)
        if img_a is not None:
            bpy.data.images.remove(img_a)
    if uv_orig_name in obj.data.uv_layers:
        obj.data.uv_layers.remove(obj.data.uv_layers[uv_orig_name])
    uv_clean.name, obj.data.uv_layers.active, uv_clean.active_render = uv_orig_name, uv_clean, True
    return out_path


def garantir_uv_materiais_tiled(obj, mat_names: set[str]) -> None:
    """Garante UVs sem sobreposicao/colapso por material tileavel pos-join."""
    mats, presentes = list(obj.data.materials), {int(p.material_index) for p in obj.data.polygons}
    for mi in sorted(presentes):
        m = mats[mi] if 0 <= mi < len(mats) else None
        if m is not None and m.name in mat_names and not _uv_saudavel_grupo(obj, mat_indices={mi}):
            _smart_project_subset(obj, mat_indices={mi})


def validar_ou_reparar_uv_pos_join(obj) -> dict[str, bool]:
    """Rede de seguranca final G3 por material antes do export."""
    mats, presentes, rel = list(obj.data.materials), {int(p.material_index) for p in obj.data.polygons}, {}
    for mi in sorted(presentes):
        m = mats[mi] if 0 <= mi < len(mats) else None
        nome = m.name if m is not None else f"mat_{mi}"
        if not _uv_saudavel_grupo(obj, mat_indices={mi}):
            _smart_project_subset(obj, mat_indices={mi})
        rel[nome] = _uv_saudavel_grupo(obj, mat_indices={mi})
    return rel


def _preparar_mat_bake_emissao(mat, mi: int, uv_orig_name: str, img_alvo):
    """Clona material para bake Cycles EMIT preservando UV original e node graph Base Color."""
    if mat is None or not mat.use_nodes:
        bm_mat = bpy.data.materials.new(f"_f3d_atlas_b{mi}")
        bm_mat.use_nodes = True
        nt = bm_mat.node_tree
        nt.nodes.clear()
        out_n, em_n = nt.nodes.new("ShaderNodeOutputMaterial"), nt.nodes.new("ShaderNodeEmission")
        em_n.inputs["Color"].default_value = (0.75, 0.55, 0.42, 1.0)
        nt.links.new(em_n.outputs["Emission"], out_n.inputs["Surface"])
        dst_n = nt.nodes.new("ShaderNodeTexImage")
        dst_n.image = img_alvo
        nt.nodes.active = dst_n
        return bm_mat, em_n, dst_n, None

    bm_mat = mat.copy()
    nt = bm_mat.node_tree
    uv_src = nt.nodes.new("ShaderNodeUVMap")
    uv_src.uv_map = uv_orig_name
    for n in list(nt.nodes):
        if n.type == "TEX_COORD" and n.outputs.get("UV") is not None:
            for lk in list(n.outputs["UV"].links):
                to_s = lk.to_socket
                nt.links.remove(lk)
                nt.links.new(uv_src.outputs["UV"], to_s)
        elif n.type == "TEX_IMAGE":
            vec_in = n.inputs.get("Vector")
            if vec_in is not None and not vec_in.is_linked:
                nt.links.new(uv_src.outputs["UV"], vec_in)

    bsdf = nt.nodes.get("Principled BSDF") or next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
    out_n = next((n for n in nt.nodes if n.type == "OUTPUT_MATERIAL"), None) or nt.nodes.new("ShaderNodeOutputMaterial")
    em_n = nt.nodes.new("ShaderNodeEmission")
    if bsdf is not None and "Base Color" in bsdf.inputs:
        bc_in = bsdf.inputs["Base Color"]
        if bc_in.is_linked:
            nt.links.new(bc_in.links[0].from_socket, em_n.inputs["Color"])
        else:
            em_n.inputs["Color"].default_value = bc_in.default_value
    else:
        em_n.inputs["Color"].default_value = (0.75, 0.55, 0.42, 1.0)
    for lk in list(out_n.inputs["Surface"].links):
        nt.links.remove(lk)
    nt.links.new(em_n.outputs["Emission"], out_n.inputs["Surface"])
    dst_n = nt.nodes.new("ShaderNodeTexImage")
    dst_n.image = img_alvo
    nt.nodes.active = dst_n
    return bm_mat, em_n, dst_n, bsdf
