"""Construtor de shader PBR multi-zona Cycles para bake em textura unica."""

from __future__ import annotations

import os
import sys

try:
    import bpy
except ImportError:  # pragma: no cover - permite import puro em testes fora do Blender
    bpy = None  # type: ignore[assignment]

if __package__:
    from .procedural_pbr_presets import PRESETS_PBR, _hex_para_rgba_linear, _resolver_cores_zona
else:
    _BLENDER_DIR = os.path.dirname(os.path.abspath(__file__))
    if _BLENDER_DIR not in sys.path:
        sys.path.insert(0, _BLENDER_DIR)
    from procedural_pbr_presets import PRESETS_PBR, _hex_para_rgba_linear, _resolver_cores_zona


def construir_shader_pbr_zonas_blender(
    nome_mat: str,
    zonas: list[dict],
    *,
    presets_pbr: dict | None = None,
    img_paleta=None,
    nome_cor_vertice: str | None = None,
    ao_cavidade_forca: float = 0.35,
):
    """Constroi um unico grafo Cycles combinando multiplos presets PBR por zona cromatica/UV.

    Resultado: o bake em Cycles gera um unico conjunto BaseColor/Normal/Roughness/Metalness
    para um unico SurfaceAppearance no Roblox (preserva ``materiais_max: 1`` e hardware instancing).
    """
    catalogo = presets_pbr if presets_pbr is not None else PRESETS_PBR
    lista_zonas = list(zonas) if zonas else [{"preset": "pedra_musgo"}]

    mat = bpy.data.materials.new(nome_mat)
    mat.use_nodes = True
    mat.use_backface_culling = True
    nt = mat.node_tree
    nt.nodes.clear()

    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.name = "Material Output"
    out.location = (900, 0)
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.name = "Principled BSDF"
    bsdf.location = (600, 0)
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

    # Fonte da mascara de zonas: imagem da paleta (UV) ou atributo Color
    src_node = None
    if img_paleta is not None:
        tex_src = nt.nodes.new("ShaderNodeTexImage")
        tex_src.image = img_paleta
        tex_src.interpolation = "Closest"
        tex_src.location = (-800, 300)
        src_node = tex_src.outputs["Color"]
    elif nome_cor_vertice:
        attr = nt.nodes.new("ShaderNodeAttribute")
        attr.attribute_name = nome_cor_vertice
        attr.location = (-800, 300)
        src_node = attr.outputs["Color"]

    tex_coord = nt.nodes.new("ShaderNodeTexCoord")
    tex_coord.location = (-950, -100)
    sep_uv = nt.nodes.new("ShaderNodeSeparateXYZ")
    sep_uv.location = (-800, -100)
    nt.links.new(tex_coord.outputs["UV"], sep_uv.inputs["Vector"])

    # AO / Cavidade global multiplicada sobre o albedo
    ao_node = nt.nodes.new("ShaderNodeAmbientOcclusion")
    ao_node.samples = 8
    ao_node.inputs["Distance"].default_value = 0.25
    ao_node.location = (100, 420)

    cor_acum = None
    rough_acum = None
    met_acum = None
    altura_acum = None
    n_zonas = max(1, len(lista_zonas))

    for idx, z in enumerate(lista_zonas):
        preset_nome = str(z.get("preset") or "pedra_musgo").strip().lower()
        p = catalogo.get(preset_nome) or next(iter(catalogo.values()))
        y_off = -idx * 320

        noise = nt.nodes.new("ShaderNodeTexNoise")
        noise.noise_dimensions = "3D"
        noise.location = (-500, y_off)
        noise.inputs["Scale"].default_value = float(p.get("escala_micro", 20.0))
        noise.inputs["Detail"].default_value = 6.0
        noise.inputs["Roughness"].default_value = 0.65
        nt.links.new(tex_coord.outputs["Object"], noise.inputs["Vector"])

        cor_base, cor_sec = _resolver_cores_zona(z, p)

        mix_c = nt.nodes.new("ShaderNodeMix")
        mix_c.data_type = "RGBA"
        mix_c.clamp_factor = True
        mix_c.location = (-250, y_off)
        mix_c.inputs["A"].default_value = cor_base
        mix_c.inputs["B"].default_value = cor_sec
        nt.links.new(noise.outputs["Fac"], mix_c.inputs["Factor"])

        escala_r = float(z.get("roughness_escala", 1.0))
        r_min = max(0.05, min(0.98, float(p.get("roughness_min", 0.35)) * escala_r))
        r_max = max(0.05, min(0.98, float(p.get("roughness_max", 0.75)) * escala_r))
        map_r = nt.nodes.new("ShaderNodeMapRange")
        map_r.clamp = True
        map_r.location = (-250, y_off - 140)
        map_r.inputs["To Min"].default_value = r_min
        map_r.inputs["To Max"].default_value = r_max
        nt.links.new(noise.outputs["Fac"], map_r.inputs["Value"])

        met_val = (
            max(0.0, min(1.0, float(z["metallic_override"])))
            if z.get("metallic_override") is not None
            else 0.5 * (float(p.get("metallic_min", 0.0)) + float(p.get("metallic_max", 0.0)))
        )
        normal_forca = max(0.0, min(2.0, float(z.get("normal_forca", 1.0))))
        peso_bump = max(0.0, min(2.0, float(p.get("bump_strength", 0.45)) * normal_forca))
        mul_h = nt.nodes.new("ShaderNodeMath")
        mul_h.operation = "MULTIPLY"
        mul_h.location = (-250, y_off - 240)
        nt.links.new(noise.outputs["Fac"], mul_h.inputs[0])
        mul_h.inputs[1].default_value = peso_bump

        # Mascara por cor_hex (distancia euclidiana linear/sRGB) e/ou uv_faixa [u_min, v_min, u_max, v_max]
        mask_cor = None
        if src_node is not None and z.get("cor_hex"):
            hex_limpo = str(z["cor_hex"]).strip().lstrip("#")
            c_target_lin = _hex_para_rgba_linear(str(z["cor_hex"]))[:3]
            if len(hex_limpo) == 6:
                c_target_srgb = (
                    int(hex_limpo[0:2], 16) / 255.0,
                    int(hex_limpo[2:4], 16) / 255.0,
                    int(hex_limpo[4:6], 16) / 255.0,
                )
            else:
                c_target_srgb = c_target_lin

            diff_lin = nt.nodes.new("ShaderNodeVectorMath")
            diff_lin.operation = "DISTANCE"
            diff_lin.location = (-500, y_off + 120)
            nt.links.new(src_node, diff_lin.inputs[0])
            diff_lin.inputs[1].default_value = c_target_lin

            diff_srgb = nt.nodes.new("ShaderNodeVectorMath")
            diff_srgb.operation = "DISTANCE"
            diff_srgb.location = (-500, y_off + 160)
            nt.links.new(src_node, diff_srgb.inputs[0])
            diff_srgb.inputs[1].default_value = c_target_srgb

            min_diff = nt.nodes.new("ShaderNodeMath")
            min_diff.operation = "MINIMUM"
            min_diff.location = (-400, y_off + 140)
            nt.links.new(diff_lin.outputs["Value"], min_diff.inputs[0])
            nt.links.new(diff_srgb.outputs["Value"], min_diff.inputs[1])

            ramp = nt.nodes.new("ShaderNodeMapRange")
            ramp.clamp = True
            ramp.location = (-280, y_off + 140)
            ramp.inputs["From Min"].default_value = 0.04
            ramp.inputs["From Max"].default_value = 0.28
            ramp.inputs["To Min"].default_value = 1.0
            ramp.inputs["To Max"].default_value = 0.0
            nt.links.new(min_diff.outputs["Value"], ramp.inputs["Value"])
            mask_cor = ramp.outputs["Result"]

        mask_uv = None
        uv_faixa = z.get("uv_faixa")
        if isinstance(uv_faixa, (list, tuple)) and len(uv_faixa) == 4:
            u0, v0, u1, v1 = (
                float(uv_faixa[0]),
                float(uv_faixa[1]),
                float(uv_faixa[2]),
                float(uv_faixa[3]),
            )
            cmp_u = nt.nodes.new("ShaderNodeMath")
            cmp_u.operation = "COMPARE"
            cmp_u.location = (-500, y_off + 200)
            nt.links.new(sep_uv.outputs["X"], cmp_u.inputs[0])
            cmp_u.inputs[1].default_value = 0.5 * (u0 + u1)
            cmp_u.inputs[2].default_value = max(1e-4, 0.5 * abs(u1 - u0))

            cmp_v = nt.nodes.new("ShaderNodeMath")
            cmp_v.operation = "COMPARE"
            cmp_v.location = (-500, y_off + 260)
            nt.links.new(sep_uv.outputs["Y"], cmp_v.inputs[0])
            cmp_v.inputs[1].default_value = 0.5 * (v0 + v1)
            cmp_v.inputs[2].default_value = max(1e-4, 0.5 * abs(v1 - v0))

            mul_uv = nt.nodes.new("ShaderNodeMath")
            mul_uv.operation = "MULTIPLY"
            mul_uv.use_clamp = True
            mul_uv.location = (-320, y_off + 220)
            nt.links.new(cmp_u.outputs["Value"], mul_uv.inputs[0])
            nt.links.new(cmp_v.outputs["Value"], mul_uv.inputs[1])
            mask_uv = mul_uv.outputs["Value"]

        if idx == 0:
            mask_node = nt.nodes.new("ShaderNodeValue")
            mask_node.outputs[0].default_value = 1.0
            mask_out = mask_node.outputs[0]
        elif mask_cor is not None and mask_uv is not None:
            mul_both = nt.nodes.new("ShaderNodeMath")
            mul_both.operation = "MULTIPLY"
            mul_both.use_clamp = True
            mul_both.location = (-160, y_off + 160)
            nt.links.new(mask_cor, mul_both.inputs[0])
            nt.links.new(mask_uv, mul_both.inputs[1])
            mask_out = mul_both.outputs["Value"]
        elif mask_cor is not None:
            mask_out = mask_cor
        elif mask_uv is not None:
            mask_out = mask_uv
        else:
            # Fallback por faixa de UV U quando a malha nao tem cor_vertice nem uv_faixa explicita
            u_ini = float(idx) / float(n_zonas)
            u_fim = float(idx + 1) / float(n_zonas)
            cmp_fb = nt.nodes.new("ShaderNodeMath")
            cmp_fb.operation = "COMPARE"
            cmp_fb.location = (-320, y_off + 120)
            nt.links.new(sep_uv.outputs["X"], cmp_fb.inputs[0])
            cmp_fb.inputs[1].default_value = 0.5 * (u_ini + u_fim)
            cmp_fb.inputs[2].default_value = max(1e-4, 0.5 * (u_fim - u_ini))
            mask_out = cmp_fb.outputs["Value"]

        if cor_acum is None:
            cor_acum = mix_c.outputs["Result"]
            rough_acum = map_r.outputs["Result"]
            met_val_node = nt.nodes.new("ShaderNodeValue")
            met_val_node.outputs[0].default_value = met_val
            met_acum = met_val_node.outputs[0]
            altura_acum = mul_h.outputs["Value"]
        else:
            blend_c = nt.nodes.new("ShaderNodeMix")
            blend_c.data_type = "RGBA"
            blend_c.clamp_factor = True
            blend_c.location = (50, y_off)
            nt.links.new(mask_out, blend_c.inputs["Factor"])
            nt.links.new(cor_acum, blend_c.inputs["A"])
            nt.links.new(mix_c.outputs["Result"], blend_c.inputs["B"])
            cor_acum = blend_c.outputs["Result"]

            blend_r = nt.nodes.new("ShaderNodeMix")
            blend_r.data_type = "FLOAT"
            blend_r.clamp_factor = True
            blend_r.location = (50, y_off - 110)
            nt.links.new(mask_out, blend_r.inputs["Factor"])
            nt.links.new(rough_acum, blend_r.inputs["A"])
            nt.links.new(map_r.outputs["Result"], blend_r.inputs["B"])
            rough_acum = blend_r.outputs["Result"]

            blend_m = nt.nodes.new("ShaderNodeMix")
            blend_m.data_type = "FLOAT"
            blend_m.clamp_factor = True
            blend_m.location = (50, y_off - 200)
            nt.links.new(mask_out, blend_m.inputs["Factor"])
            nt.links.new(met_acum, blend_m.inputs["A"])
            blend_m.inputs["B"].default_value = met_val
            met_acum = blend_m.outputs["Result"]

            blend_h = nt.nodes.new("ShaderNodeMix")
            blend_h.data_type = "FLOAT"
            blend_h.clamp_factor = True
            blend_h.location = (50, y_off - 280)
            nt.links.new(mask_out, blend_h.inputs["Factor"])
            nt.links.new(altura_acum, blend_h.inputs["A"])
            nt.links.new(mul_h.outputs["Value"], blend_h.inputs["B"])
            altura_acum = blend_h.outputs["Result"]

    if cor_acum is not None:
        ao_mix = nt.nodes.new("ShaderNodeMix")
        ao_mix.data_type = "RGBA"
        ao_mix.blend_type = "MULTIPLY"
        ao_mix.clamp_factor = True
        ao_mix.name = "Forge3D_AlbedoOut"
        ao_mix.location = (340, 120)
        ao_mix.inputs["Factor"].default_value = max(0.0, min(1.0, float(ao_cavidade_forca)))
        nt.links.new(cor_acum, ao_mix.inputs["A"])
        nt.links.new(ao_node.outputs["Color"], ao_mix.inputs["B"])
        nt.links.new(ao_mix.outputs["Result"], bsdf.inputs["Base Color"])
        nt.links.new(rough_acum, bsdf.inputs["Roughness"])
        nt.links.new(met_acum, bsdf.inputs["Metallic"])

    bump = nt.nodes.new("ShaderNodeBump")
    bump.name = "Forge3D_BumpOut"
    bump.location = (360, -160)
    bump.inputs["Strength"].default_value = 0.55
    bump.inputs["Distance"].default_value = 0.012
    if altura_acum is not None:
        nt.links.new(altura_acum, bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])

    emit = nt.nodes.new("ShaderNodeEmission")
    emit.name = "Forge3D_BakeEmit"
    emit.inputs["Strength"].default_value = 1.0
    emit.location = (600, 320)

    comb_orm = nt.nodes.new("ShaderNodeCombineColor")
    comb_orm.mode = "RGB"
    comb_orm.name = "Forge3D_CombineHintsORM"
    comb_orm.inputs[2].default_value = 1.0
    comb_orm.location = (340, -320)
    if met_acum is not None:
        nt.links.new(met_acum, comb_orm.inputs[0])
    if rough_acum is not None:
        nt.links.new(rough_acum, comb_orm.inputs[1])

    mat["forge3d_pbr_zonas"] = len(lista_zonas)
    return mat
