"""Projecao e bake de textura Emissive embutida no GLB (sem poluir manifest@7)."""

from __future__ import annotations

import os
import sys
from array import array

try:
    import bpy
except ImportError:  # pragma: no cover - permite import puro fora do Blender
    bpy = None  # type: ignore[assignment]

if __package__:
    from . import bake_pbr_config as _cfg
    from . import bake_pbr_maps as _maps
    from . import bake_pbr_proj as _proj
    from . import bake_pbr_shaders as _sh
else:
    _BLENDER_DIR = os.path.dirname(os.path.abspath(__file__))
    if _BLENDER_DIR not in sys.path:
        sys.path.insert(0, _BLENDER_DIR)
    import bake_pbr_config as _cfg
    import bake_pbr_maps as _maps
    import bake_pbr_proj as _proj
    import bake_pbr_shaders as _sh


def tem_pixels_emissivos_ativos(img_em_hint, img_origem=None, limiar_frac: float = 0.0005) -> bool:
    """Retorna True se ``img_em_hint`` tiver fracao de pixels ativos ``> limiar_frac`` do foreground."""
    if img_em_hint is None or not getattr(img_em_hint, "size", None):
        return False
    w, h = int(img_em_hint.size[0]), int(img_em_hint.size[1])
    total_f = w * h * 4
    if w <= 0 or h <= 0:
        return False
    try:
        if len(getattr(img_em_hint, "pixels", ())) != total_f:
            return False
        em_buf = array("f", [0.0]) * total_f
        img_em_hint.pixels.foreach_get(em_buf)
    except (RuntimeError, ValueError, TypeError) as exc:
        sys.stderr.write(f"[bake_pbr_emissive] aviso ao ler emissive_hint: {exc}\n")
        return False

    ativos = sum(1 for i in range(0, total_f, 4) if em_buf[i] > 0.25)
    if ativos <= 0:
        return False
    fg_total = w * h
    if img_origem is not None and tuple(getattr(img_origem, "size", (0, 0))) == (w, h):
        if len(getattr(img_origem, "pixels", ())) == total_f:
            obuf = array("f", [0.0]) * total_f
            img_origem.pixels.foreach_get(obuf)
            if min(obuf[3::4]) < 0.98:
                fg_total = max(1, sum(1 for a in obuf[3::4] if a >= 0.10))
    return (ativos / float(max(1, fg_total))) > limiar_frac


def assar_e_aplicar_emissive_uv0(
    cena, obj, saida_dir: str, nome_base: str, px: int, px_sub: int,
    img_em_hint, img_origem, img_bc, path_bc: str,
):
    """Assa emissive em UV0, realca ``_baseColor.png`` e empacota textura emissive apenas em memoria."""
    if not tem_pixels_emissivos_ativos(img_em_hint, img_origem) or obj is None or not obj.data.uv_layers:
        return None, img_bc, False

    uv0_nome = str(obj.data.uv_layers[0].name)
    uv_tmp_nome, vis_tmp_nome = "_UV_Cam_Em_Tmp", "_vis_em_tmp"
    mats_ant = list(obj.data.materials)
    s2a_ant, samples_ant, margin_ant = (
        bool(cena.render.bake.use_selected_to_active), int(cena.cycles.samples), int(cena.render.bake.margin)
    )
    mat_em = tex_em = img_em_raw = None
    tmp_pack_path = os.path.join(saida_dir, f".{nome_base}_emissive_pack_tmp.png")
    try:
        min_v, max_v = _cfg._calcular_bbox_mundo(obj)
        uv_bbox = _proj._detectar_bbox_uv_foreground(img_origem or img_em_hint)
        _proj._projetar_uv_frontal_bmesh(obj, min_v, max_v, uv_bbox, uv_tmp_nome)
        vis_attr = _proj._calcular_oclusao_direcao_bmesh(obj, (0.0, 1.0, 0.0), vis_tmp_nome)
        obj.data.uv_layers.active = obj.data.uv_layers[uv0_nome]
        obj.data.uv_layers[uv0_nome].active_render = True

        mat_em, tex_em = _maps._criar_material_alvo_bake(f"{nome_base}_em_bake_tmp")
        nt = mat_em.node_tree
        bsdf = nt.nodes.get("Principled BSDF")
        if bsdf is not None:
            nt.nodes.remove(bsdf)
        out = nt.nodes.get("Material Output")
        uv_node, fator_frente = _sh._criar_nodos_fator_vista(nt, (0.0, 1.0, 0.0), uv_tmp_nome, nome_visivel=vis_attr)
        tx_mask = nt.nodes.new("ShaderNodeTexImage")
        tx_mask.image = img_em_hint
        tx_mask.extension = "EXTEND"
        nt.links.new(uv_node.outputs["UV"], tx_mask.inputs["Vector"])
        mul_m = nt.nodes.new("ShaderNodeMath")
        mul_m.operation = "MULTIPLY"
        mul_m.use_clamp = True
        nt.links.new(fator_frente, mul_m.inputs[0])
        nt.links.new(tx_mask.outputs["Color"], mul_m.inputs[1])

        emit = nt.nodes.new("ShaderNodeEmission")
        emit.inputs["Strength"].default_value = 1.0
        if img_origem is not None:
            tx_cor = nt.nodes.new("ShaderNodeTexImage")
            tx_cor.image = img_origem
            tx_cor.extension = "EXTEND"
            nt.links.new(uv_node.outputs["UV"], tx_cor.inputs["Vector"])
            mul_a = nt.nodes.new("ShaderNodeMath")
            mul_a.operation = "MULTIPLY"
            mul_a.use_clamp = True
            nt.links.new(mul_m.outputs["Value"], mul_a.inputs[0])
            nt.links.new(tx_cor.outputs["Alpha"], mul_a.inputs[1])
            vmul = nt.nodes.new("ShaderNodeVectorMath")
            vmul.operation = "SCALE"
            nt.links.new(tx_cor.outputs["Color"], vmul.inputs[0])
            nt.links.new(mul_a.outputs["Value"], vmul.inputs["Scale"])
            nt.links.new(vmul.outputs["Vector"], emit.inputs["Color"])
        else:
            nt.links.new(mul_m.outputs["Value"], emit.inputs["Color"])
        nt.links.new(emit.outputs["Emission"], out.inputs["Surface"])

        img_em_raw = bpy.data.images.new(f"{nome_base}_em_raw_tmp", width=px_sub, height=px_sub, alpha=False)
        img_em_raw.colorspace_settings.name = "sRGB"
        tex_em.image = img_em_raw
        tex_em.select = True
        nt.nodes.active = tex_em
        obj.data.materials.clear()
        obj.data.materials.append(mat_em)
        cena.render.bake.use_selected_to_active = False
        cena.cycles.samples = 1
        cena.render.bake.margin = max(4, px_sub // 128)
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        _cfg._executar_bake_seguro(cena, type="EMIT")
    finally:
        if tex_em is not None:
            tex_em.image = None
        obj.data.materials.clear()
        for m_ant in mats_ant:
            obj.data.materials.append(m_ant)
        if uv_tmp_nome in obj.data.uv_layers:
            obj.data.uv_layers.remove(obj.data.uv_layers[uv_tmp_nome])
        if uv0_nome in obj.data.uv_layers:
            obj.data.uv_layers.active = obj.data.uv_layers[uv0_nome]
            obj.data.uv_layers[uv0_nome].active_render = True
        if vis_tmp_nome in obj.data.color_attributes:
            obj.data.color_attributes.remove(obj.data.color_attributes[vis_tmp_nome])
        if mat_em is not None and mat_em.name in bpy.data.materials and mat_em.users == 0:
            bpy.data.materials.remove(mat_em)
        cena.render.bake.use_selected_to_active, cena.cycles.samples, cena.render.bake.margin = s2a_ant, samples_ant, margin_ant

    em_buf, bc_buf = array("f", [0.0]) * (px_sub * px_sub * 4), array("f", [0.0]) * (px * px * 4)
    img_em_raw.pixels.foreach_get(em_buf)
    img_bc.pixels.foreach_get(bc_buf)
    for y in range(px_sub):
        by = min(px - 1, (y * px) // px_sub)
        for x in range(px_sub):
            ei, bi = (y * px_sub + x) * 4, (by * px + min(px - 1, (x * px) // px_sub)) * 4
            er, eg, eb = em_buf[ei], em_buf[ei + 1], em_buf[ei + 2]
            pico = max(er, eg, eb)
            if pico <= 0.02:
                em_buf[ei], em_buf[ei + 1], em_buf[ei + 2], em_buf[ei + 3] = 0.0, 0.0, 0.0, 1.0
                continue
            if img_origem is None:
                br, bg_c, bb = bc_buf[bi], bc_buf[bi + 1], bc_buf[bi + 2]
                bm_c = max(br, bg_c, bb)
                er, eg, eb = ((br / bm_c) * pico, (bg_c / bm_c) * pico, (bb / bm_c) * pico) if bm_c > 0.05 else (pico, 0.72 * pico, 0.25 * pico)
            g_em = min(1.45, 1.0 / max(pico, 0.35))
            em_buf[ei], em_buf[ei + 1], em_buf[ei + 2], em_buf[ei + 3] = min(1.0, er * g_em), min(1.0, eg * g_em), min(1.0, eb * g_em), 1.0

    for by in range(px):
        ey = min(px_sub - 1, (by * px_sub) // px)
        for bx in range(px):
            bi, ei = (by * px + bx) * 4, (ey * px_sub + min(px_sub - 1, (bx * px_sub) // px)) * 4
            if max(em_buf[ei], em_buf[ei + 1], em_buf[ei + 2]) > 0.02:
                for c_k in range(3):
                    bc_buf[bi + c_k] = min(1.0, max(bc_buf[bi + c_k] + 0.65 * em_buf[ei + c_k], 0.88 * em_buf[ei + c_k]))

    img_bc.pixels.foreach_set(bc_buf)
    img_bc_nova = _maps._salvar_e_recarregar_png(img_bc, path_bc, "sRGB", cena)
    img_em_raw.pixels.foreach_set(em_buf)
    try:
        cena.render.image_settings.compression = 90
        img_em_raw.save_render(filepath=tmp_pack_path, scene=cena)
        bpy.data.images.remove(img_em_raw)
        img_em_final = bpy.data.images.load(tmp_pack_path, check_existing=False)
        img_em_final.name = f"{nome_base}_emissive"
        img_em_final.colorspace_settings.name = "sRGB"
        img_em_final.pack()
        img_em_final.filepath, img_em_final.filepath_raw = "", ""
    finally:
        if os.path.isfile(tmp_pack_path):
            os.remove(tmp_pack_path)
    return img_em_final, img_bc_nova, True
