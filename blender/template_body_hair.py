"""Cabeca, cabelo MakeHuman manifold, textura/tintura alfa e unificacao corpo+cabelo."""

from __future__ import annotations

import math
import os
import sys

import bmesh
import bpy
from mathutils import Vector

if __package__:
    from . import template_body_assets as _assets
else:
    _BLENDER_DIR = os.path.dirname(os.path.abspath(__file__))
    if _BLENDER_DIR not in sys.path:
        sys.path.insert(0, _BLENDER_DIR)
    import template_body_assets as _assets

_hex_to_rgb_srgb = _assets._hex_to_rgb_srgb
_limpar_nao_manifold_aberto = _assets._limpar_nao_manifold_aberto


def _info_cabeca(obj) -> dict:
    vg = {g.name: g.index for g in obj.vertex_groups}
    hid = vg.get("head")
    if hid is None:
        return {}
    pts = [
        obj.matrix_world @ v.co for v in obj.data.vertices
        if any(g.group == hid and g.weight > 0.5 for g in v.groups)
    ]
    if not pts:
        return {}
    return {
        "topo_z": round(max(p.z for p in pts), 4),
        "base_z": round(min(p.z for p in pts), 4),
        "centro_x": round(0.5 * (min(p.x for p in pts) + max(p.x for p in pts)), 4),
        "centro_y": round(-0.5 * (min(p.y for p in pts) + max(p.y for p in pts)), 4),
        "largura_x": round(max(p.x for p in pts) - min(p.x for p in pts), 4),
        "profundidade_y": round(max(p.y for p in pts) - min(p.y for p in pts), 4),
    }


def _info_cabelo(hair_obj, body_obj, info_cabeca: dict) -> dict:
    bpy.context.view_layer.update()
    pts_b = [body_obj.matrix_world @ v.co for v in body_obj.data.vertices]
    pts_h = [hair_obj.matrix_world @ v.co for v in hair_obj.data.vertices]
    if not pts_b or not pts_h:
        return {}
    body_h = max(p.z for p in pts_b) - min(p.z for p in pts_b)
    min_h = Vector((min(p.x for p in pts_h), min(p.y for p in pts_h), min(p.z for p in pts_h)))
    max_h = Vector((max(p.x for p in pts_h), max(p.y for p in pts_h), max(p.z for p in pts_h)))
    hair_h = max_h.z - min_h.z
    # Apos rotacao Z=pi, Y do MakeHuman inverte sinal para +Y=frente
    hair_cy_pos = -0.5 * (min_h.y + max_h.y)
    cab_cy_pos = float(info_cabeca.get("centro_y", 0.0))
    cab_topo = float(info_cabeca.get("topo_z", max_h.z))
    return {
        "altura_raw_m": round(hair_h, 4),
        "altura_corpo_raw_m": round(body_h, 4),
        "escala_relativa_corpo": round(hair_h / max(1e-5, body_h), 4),
        "offset_topo_cranio_z": round(max_h.z - cab_topo, 4),
        "offset_centro_y": round(hair_cy_pos - cab_cy_pos, 4),
    }


def _preparar_cabelo_manifold(hair_obj, target_tris: int) -> dict:
    """Converte tiras abertas .mhclo em malha fechada manifold (G1=0) respeitando target_tris."""
    _limpar_nao_manifold_aberto(hair_obj)
    for _ in range(4):
        bm = bmesh.new()
        bm.from_mesh(hair_obj.data)
        t_cur = len(bm.faces)
        b_cur = sum(1 for e in bm.edges if len(e.link_faces) == 1)
        bm.free()
        est_solid = 2 * t_cur + 2 * b_cur
        if target_tris <= 0 or est_solid <= target_tris:
            break
        ratio = max(0.05, min(0.92, (target_tris * 0.90) / max(1, est_solid)))
        mod_d = hair_obj.modifiers.new("pre_dec", "DECIMATE")
        mod_d.ratio = ratio
        bpy.ops.object.select_all(action="DESELECT")
        bpy.context.view_layer.objects.active = hair_obj
        hair_obj.select_set(True)
        bpy.ops.object.modifier_apply(modifier=mod_d.name)
        _limpar_nao_manifold_aberto(hair_obj)

    mod = hair_obj.modifiers.new("Solidify", "SOLIDIFY")
    mod.thickness = 0.0012
    mod.offset = 0.0
    mod.use_rim = True
    mod.use_rim_only = False
    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = hair_obj
    hair_obj.select_set(True)
    bpy.ops.object.modifier_apply(modifier=mod.name)

    bm = bmesh.new()
    bm.from_mesh(hair_obj.data)
    bmesh.ops.triangulate(bm, faces=list(bm.faces))
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
    nao_manifold = sum(1 for e in bm.edges if len(e.link_faces) != 2)
    degeneradas = sum(1 for f in bm.faces if f.calc_area() < 1e-12)
    tris = len(bm.faces)
    bm.to_mesh(hair_obj.data)
    bm.free()
    hair_obj.data.shade_smooth()
    hair_obj.data.set_sharp_from_angle(angle=math.radians(85.0))
    hair_obj.data.update()
    return {
        "triangulos": tris,
        "nao_manifold": nao_manifold,
        "degeneradas": degeneradas,
    }


def _preparar_textura_e_material_cabelo(
    hair_obj,
    estilo: str,
    saida: str,
    tex_px: int,
    cor_hex: str = "",
    material_modo: str = "alpha_clip",
    png_nome: str = "baseColor.png",
    alpha_cutoff: float = 0.5,
    fallback_tex_path: str | None = None,
    mat_nome: str | None = None,
) -> str:
    """Redimensiona difusa POT, aplica tintura/bleed sem halo branco e cria material glTF."""
    img_orig = None
    for mat in hair_obj.data.materials:
        if mat and mat.use_nodes:
            for node in mat.node_tree.nodes:
                if node.type == "TEX_IMAGE" and node.image is not None:
                    img_orig = node.image
                    break
        if img_orig is not None:
            break
    if img_orig is None and fallback_tex_path and os.path.isfile(fallback_tex_path):
        img_orig = bpy.data.images.load(fallback_tex_path, check_existing=True)
    if img_orig is None:
        raise RuntimeError(f"cabelo MakeHuman '{estilo}' sem textura difusa")

    img = img_orig.copy()
    img.name = f"mh_{estilo}_baseColor"
    if img.size[0] != tex_px or img.size[1] != tex_px:
        img.scale(tex_px, tex_px)

    px = list(img.pixels)
    n_px = len(px) // 4
    soma_r = soma_g = soma_b = soma_lum = 0.0
    qtd_opacos = 0
    tem_alfa = False
    for k in range(n_px):
        off = k * 4
        r, g, b, a = px[off], px[off + 1], px[off + 2], px[off + 3]
        if a < 0.98:
            tem_alfa = True
        if a > 0.60:
            soma_r += r
            soma_g += g
            soma_b += b
            soma_lum += 0.2126 * r + 0.7152 * g + 0.0722 * b
            qtd_opacos += 1

    avg_r = soma_r / max(1, qtd_opacos)
    avg_g = soma_g / max(1, qtd_opacos)
    avg_b = soma_b / max(1, qtd_opacos)
    avg_lum = max(0.05, soma_lum / max(1, qtd_opacos))

    alvo_tint = _hex_to_rgb_srgb(cor_hex)
    fill_r, fill_g, fill_b = alvo_tint if alvo_tint is not None else (avg_r, avg_g, avg_b)
    for k in range(n_px):
        off = k * 4
        r, g, b, a = px[off], px[off + 1], px[off + 2], px[off + 3]
        if alvo_tint is not None and a > 0.02:
            lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
            rel = min(1.35, lum / avg_lum)
            fator = 0.25 + 0.75 * rel
            r = min(1.0, alvo_tint[0] * fator)
            g = min(1.0, alvo_tint[1] * fator)
            b = min(1.0, alvo_tint[2] * fator)
        if a < 0.50:
            # Remove borda branca de alpha=0..0.5 nas pontas de mechas para evitar halo no Alpha Clip
            r, g, b = fill_r, fill_g, fill_b
        px[off], px[off + 1], px[off + 2] = r, g, b
    img.pixels[:] = px

    sc = bpy.context.scene
    ant_mode = sc.render.image_settings.color_mode
    sc.render.image_settings.color_mode = "RGBA"
    caminho = os.path.join(saida, png_nome)
    img.filepath_raw = caminho
    img.file_format = "PNG"
    img.save()
    sc.render.image_settings.color_mode = ant_mode
    img.pack()

    mat = bpy.data.materials.new(mat_nome or f"makehuman_cabelo_{estilo}")
    mat.use_nodes = True
    mat.use_backface_culling = True
    nt = mat.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = img
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    usar_clip = (material_modo == "alpha_clip") or (tem_alfa and material_modo != "opaque")
    if usar_clip:
        limiar_a = float(alpha_cutoff)
        mat.blend_method = "CLIP"
        if hasattr(mat, "surface_render_method"):
            mat.surface_render_method = "DITHERED"
        if hasattr(mat, "alpha_threshold"):
            mat.alpha_threshold = limiar_a
        cut = nt.nodes.new("ShaderNodeMath")
        cut.operation = "GREATER_THAN"
        cut.inputs[1].default_value = limiar_a
        nt.links.new(tex.outputs["Alpha"], cut.inputs[0])
        nt.links.new(cut.outputs["Value"], bsdf.inputs["Alpha"])
    if "Roughness" in bsdf.inputs:
        bsdf.inputs["Roughness"].default_value = 0.85
    if "Specular IOR Level" in bsdf.inputs:
        bsdf.inputs["Specular IOR Level"].default_value = 0.08
    if "Metallic" in bsdf.inputs:
        bsdf.inputs["Metallic"].default_value = 0.0
    hair_obj.data.materials.clear()
    hair_obj.data.materials.append(mat)
    return caminho


def _unificar_materiais_corpo_cabelo(
    body_obj,
    hair_obj,
    tex_corpo_path: str,
    tex_cabelo_path: str,
    tex_px: int,
) -> None:
    """Combina corpo e cabelo em 1 material e 1 atlas lado-a-lado (materiais_max=1)."""
    if not body_obj.data.uv_layers or not hair_obj.data.uv_layers:
        return
    if not body_obj.data.materials:
        return

    uv_b = body_obj.data.uv_layers[0].data
    for lp in uv_b:
        u = max(0.0, min(1.0, float(lp.uv[0])))
        v = max(0.0, min(1.0, float(lp.uv[1])))
        lp.uv = (0.002 + 0.496 * u, v)

    uv_h = hair_obj.data.uv_layers[0].data
    for lp in uv_h:
        u = max(0.0, min(1.0, float(lp.uv[0])))
        v = max(0.0, min(1.0, float(lp.uv[1])))
        lp.uv = (0.502 + 0.496 * u, v)

    img_c = bpy.data.images.load(tex_corpo_path, check_existing=True)
    img_h = bpy.data.images.load(tex_cabelo_path, check_existing=True)
    c_tmp = img_c.copy()
    h_tmp = img_h.copy()
    if int(c_tmp.size[0]) != tex_px or int(c_tmp.size[1]) != tex_px:
        c_tmp.scale(tex_px, tex_px)
    if int(h_tmp.size[0]) != tex_px or int(h_tmp.size[1]) != tex_px:
        h_tmp.scale(tex_px, tex_px)
    px_c = list(c_tmp.pixels)
    px_h = list(h_tmp.pixels)
    bpy.data.images.remove(c_tmp)
    bpy.data.images.remove(h_tmp)

    half = tex_px // 2
    buf = [1.0] * (tex_px * tex_px * 4)
    for y in range(tex_px):
        row_off = y * tex_px
        for x in range(half):
            sx = min(tex_px - 1, x * 2)
            src = (row_off + sx) * 4
            dst = (row_off + x) * 4
            buf[dst] = px_c[src]
            buf[dst + 1] = px_c[src + 1]
            buf[dst + 2] = px_c[src + 2]
            buf[dst + 3] = 1.0
        for x in range(half, tex_px):
            sx = min(tex_px - 1, (x - half) * 2)
            src = (row_off + sx) * 4
            dst = (row_off + x) * 4
            buf[dst] = px_h[src]
            buf[dst + 1] = px_h[src + 1]
            buf[dst + 2] = px_h[src + 2]
            buf[dst + 3] = px_h[src + 3]

    img_unif = bpy.data.images.new("unified_baseColor", width=tex_px, height=tex_px, alpha=True)
    img_unif.pixels.foreach_set(buf)
    sc = bpy.context.scene
    ant_mode = sc.render.image_settings.color_mode
    sc.render.image_settings.color_mode = "RGBA"
    img_unif.filepath_raw = tex_corpo_path
    img_unif.file_format = "PNG"
    img_unif.save()
    sc.render.image_settings.color_mode = ant_mode
    img_unif.pack()

    mat_corpo = body_obj.data.materials[0]
    nt = mat_corpo.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    tex_node = next((n for n in nt.nodes if n.type == "TEX_IMAGE"), None)
    if tex_node is not None:
        tex_node.image = img_unif
        if bsdf is not None and "Alpha" in bsdf.inputs:
            nt.links.new(tex_node.outputs["Alpha"], bsdf.inputs["Alpha"])
    hair_usa_clip = any(getattr(m, "blend_method", "OPAQUE") == "CLIP" for m in hair_obj.data.materials if m)
    if hair_usa_clip:
        mat_corpo.blend_method = "CLIP"
        if hasattr(mat_corpo, "alpha_threshold"):
            mat_corpo.alpha_threshold = 0.5

    hair_obj.data.materials.clear()
    hair_obj.data.materials.append(mat_corpo)
