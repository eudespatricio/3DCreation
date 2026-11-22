"""Modulacao estatistica e projecao de hints Delight sobre PBR nativo (TRELLIS.2)."""

from __future__ import annotations

import math
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


def assar_hints_delight_uv0(cena, obj, px_sub: int, nome_base: str, img_origem, img_met, img_rough):
    """Projeta ``metallic_hint`` e ``roughness_hint`` em UV0 sem tocar nos materiais de ``high_obj``."""
    if (img_met is None and img_rough is None) or obj is None or not obj.data.uv_layers:
        return None
    uv0_nome = str(obj.data.uv_layers[0].name)
    uv_tmp_nome, vis_tmp_nome = "_UV_Cam_Nat_Tmp", "_vis_nat_tmp"
    mats_ant = list(obj.data.materials)
    s2a_ant = bool(cena.render.bake.use_selected_to_active)
    samples_ant = int(cena.cycles.samples)
    margin_ant = int(cena.render.bake.margin)
    mat_dl = tex_dl = img_dl = None
    try:
        min_v, max_v = _cfg._calcular_bbox_mundo(obj)
        uv_bbox = _proj._detectar_bbox_uv_foreground(img_origem) if img_origem is not None else (0.0, 1.0, 0.0, 1.0)
        _proj._projetar_uv_frontal_bmesh(obj, min_v, max_v, uv_bbox, uv_tmp_nome)
        vis_attr = _proj._calcular_oclusao_direcao_bmesh(obj, (0.0, 1.0, 0.0), vis_tmp_nome)
        obj.data.uv_layers.active = obj.data.uv_layers[uv0_nome]
        obj.data.uv_layers[uv0_nome].active_render = True

        mat_dl, tex_dl = _maps._criar_material_alvo_bake(f"{nome_base}_nat_dl_mat_tmp")
        nt = mat_dl.node_tree
        bsdf = nt.nodes.get("Principled BSDF")
        if bsdf is not None:
            nt.nodes.remove(bsdf)
        out = nt.nodes.get("Material Output")
        uv_node, fator_frente = _sh._criar_nodos_fator_vista(nt, (0.0, 1.0, 0.0), uv_tmp_nome, nome_visivel=vis_attr)
        fator_w = fator_frente
        if img_origem is not None:
            tex_o = nt.nodes.new("ShaderNodeTexImage")
            tex_o.image = img_origem
            tex_o.extension = "EXTEND"
            nt.links.new(uv_node.outputs["UV"], tex_o.inputs["Vector"])
            mul_a = nt.nodes.new("ShaderNodeMath")
            mul_a.operation = "MULTIPLY"
            mul_a.use_clamp = True
            nt.links.new(fator_frente, mul_a.inputs[0])
            nt.links.new(tex_o.outputs["Alpha"], mul_a.inputs[1])
            fator_w = mul_a.outputs["Value"]

        comb = nt.nodes.new("ShaderNodeCombineColor")
        comb.mode = "RGB"
        for idx_c, im_h, padrao in ((0, img_met, 0.0), (1, img_rough, 0.78)):
            if im_h is not None:
                tx = nt.nodes.new("ShaderNodeTexImage")
                tx.image = im_h
                tx.extension = "EXTEND"
                nt.links.new(uv_node.outputs["UV"], tx.inputs["Vector"])
                nt.links.new(tx.outputs["Color"], comb.inputs[idx_c])
            else:
                comb.inputs[idx_c].default_value = padrao
        nt.links.new(fator_w, comb.inputs[2])
        emit = nt.nodes.new("ShaderNodeEmission")
        emit.inputs["Strength"].default_value = 1.0
        nt.links.new(comb.outputs["Color"], emit.inputs["Color"])
        nt.links.new(emit.outputs["Emission"], out.inputs["Surface"])

        img_dl = bpy.data.images.new(f"{nome_base}_nat_dl_tmp", width=px_sub, height=px_sub, alpha=False)
        img_dl.colorspace_settings.name = "Non-Color"
        tex_dl.image = img_dl
        tex_dl.select = True
        nt.nodes.active = tex_dl
        obj.data.materials.clear()
        obj.data.materials.append(mat_dl)
        cena.render.bake.use_selected_to_active = False
        cena.cycles.samples = 1
        cena.render.bake.margin = max(4, px_sub // 128)
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        _cfg._executar_bake_seguro(cena, type="EMIT")
        return img_dl
    finally:
        if tex_dl is not None:
            tex_dl.image = None
        obj.data.materials.clear()
        for m_ant in mats_ant:
            obj.data.materials.append(m_ant)
        uv_rm = obj.data.uv_layers.get(uv_tmp_nome)
        if uv_rm is not None:
            obj.data.uv_layers.remove(uv_rm)
        if uv0_nome in obj.data.uv_layers:
            obj.data.uv_layers.active = obj.data.uv_layers[uv0_nome]
            obj.data.uv_layers[uv0_nome].active_render = True
        ca_rm = obj.data.color_attributes.get(vis_tmp_nome)
        if ca_rm is not None:
            obj.data.color_attributes.remove(ca_rm)
        if mat_dl is not None and mat_dl.name in bpy.data.materials and mat_dl.users == 0:
            bpy.data.materials.remove(mat_dl)
        cena.render.bake.use_selected_to_active = s2a_ant
        cena.cycles.samples = samples_ant
        cena.render.bake.margin = margin_ant


def modular_hints_pbr_nativo(img_nat_hints, img_ao, px_sub: int, img_dl_hints=None, img_bc=None) -> dict:
    """Calibra ORM nativo (TRELLIS.2) com hints Delight projetados e acoplamento suave de AO."""
    total_f = px_sub * px_sub * 4
    nat_buf = array("f", [0.0]) * total_f
    ao_buf = array("f", [0.0]) * total_f
    img_nat_hints.pixels.foreach_get(nat_buf)
    img_ao.pixels.foreach_get(ao_buf)
    dl_buf = None
    if img_dl_hints is not None:
        dl_buf = array("f", [0.0]) * total_f
        img_dl_hints.pixels.foreach_get(dl_buf)

    validos = [i for i in range(0, total_f, 4) if nat_buf[i + 2] > 0.5] or list(range(0, total_f, 4))
    amostra = validos[:: max(1, len(validos) // 16384)]
    mets = sorted(max(0.0, min(1.0, nat_buf[i])) for i in amostra)
    roughs = [max(0.04, min(1.0, nat_buf[i + 1])) for i in amostra]
    p50_met = mets[len(mets) // 2]
    p90_met = mets[int(0.90 * (len(mets) - 1))]
    media_r = sum(roughs) / float(len(roughs))
    std_rough = math.sqrt(sum((r - media_r) ** 2 for r in roughs) / float(len(roughs)))

    dl_frente = [i for i in amostra if dl_buf is not None and dl_buf[i + 2] >= 0.25]
    frac_dl_met = (sum(1 for i in dl_frente if dl_buf[i] >= 0.50) / float(len(dl_frente))) if dl_frente else 0.0
    ferro_lamacento = (p50_met < 0.55) and (frac_dl_met >= 0.03 or p90_met >= 0.70)
    saturado_ou_plano = (p50_met > 0.85) or (std_rough < 0.03)

    if dl_buf is None and not ferro_lamacento:
        if std_rough < 0.03:
            for i in validos:
                ao_c = max(0.0, min(1.0, ao_buf[i]))
                nat_buf[i + 1] = max(0.04, min(1.0, nat_buf[i + 1] + 0.05 * (0.65 - ao_c)))
            img_nat_hints.pixels.foreach_set(nat_buf)
        return {"delight_hints_aplicados": False, "p50_met": round(p50_met, 4), "std_rough": round(std_rough, 4)}

    fb_met = 0.80 * frac_dl_met + 0.10 * (1.0 - frac_dl_met)
    fb_rough = 0.32 * frac_dl_met + 0.76 * (1.0 - frac_dl_met)
    for i in validos:
        nm = max(0.0, min(1.0, nat_buf[i]))
        nr = max(0.04, min(1.0, nat_buf[i + 1]))
        ao_c = max(0.0, min(1.0, ao_buf[i]))
        dm = max(0.0, min(1.0, dl_buf[i])) if dl_buf is not None else 0.0
        dr = max(0.04, min(1.0, dl_buf[i + 1])) if dl_buf is not None else 0.75
        dw = max(0.0, min(1.0, dl_buf[i + 2])) if dl_buf is not None else 0.0

        if ferro_lamacento:
            forca = max(0.0, min(1.0, max((nm - 0.35) / 0.45, dm * dw)))
            m_hi = min(0.895, max(nm, 0.755 + 0.140 * forca))
            r_hi = max(0.225, min(0.375, 0.35 - 0.11 * forca + 0.05 * (1.0 - ao_c)))
            m_lo = min(nm, 0.20)
            r_lo = max(0.56, min(0.92, nr * (1.0 - 0.5 * dw) + max(0.56, dr) * (0.5 * dw) + 0.08 * (1.0 - ao_c)))
            t_m = max(0.0, min(1.0, (forca - 0.22) / 0.18))
            m_out, r_out = m_lo + (m_hi - m_lo) * t_m, r_lo + (r_hi - r_lo) * t_m
        elif saturado_ou_plano:
            wf = min(1.0, dw * 1.25)
            tm, tr = dm * wf + fb_met * (1.0 - wf), dr * wf + fb_rough * (1.0 - wf)
            m_out = (0.18 * nm + 0.82 * tm) if p50_met > 0.85 else (nm * (1.0 - 0.55 * dw) + dm * (0.55 * dw))
            wr = 0.80 if std_rough < 0.03 else (0.55 * wf + 0.25)
            r_out = nr * (1.0 - wr) + tr * wr + 0.10 * (0.65 - ao_c)
        else:
            w = 0.30 * dw
            m_out = nm * (1.0 - w) + dm * w
            r_out = nr * (1.0 - w) + dr * w + 0.05 * (0.65 - ao_c)

        nat_buf[i] = max(0.0, min(1.0, m_out))
        nat_buf[i + 1] = max(0.04, min(1.0, r_out))
        nat_buf[i + 2] = 1.0

    img_nat_hints.pixels.foreach_set(nat_buf)
    return {"delight_hints_aplicados": bool(dl_buf is not None), "p50_met": round(p50_met, 4), "std_rough": round(std_rough, 4)}
