"""Construtores de grafos de shader Cycles para projecao 1-vista, 4-vistas e hints ORM."""

from __future__ import annotations

try:
    import bpy
except ImportError:  # pragma: no cover - permite import puro em testes fora do Blender
    bpy = None  # type: ignore[assignment]


def _criar_nodos_fator_vista(
    nt,
    dir_mundo: tuple[float, float, float],
    nome_uv: str,
    nome_visivel: str | None = None,
    geom=None,
    *,
    min_dot: float = 0.02,
    max_dot: float = 0.26,
    potencia: float = 1.0,
):
    """Cria nodos Dot-Product entre Normal de mundo e ``dir_mundo`` com oclusao BVH."""
    if geom is None:
        geom = nt.nodes.new("ShaderNodeNewGeometry")
    dot = nt.nodes.new("ShaderNodeVectorMath")
    dot.operation = "DOT_PRODUCT"
    dot.inputs[1].default_value = dir_mundo
    nt.links.new(geom.outputs["Normal"], dot.inputs[0])

    mr = nt.nodes.new("ShaderNodeMapRange")
    mr.clamp = True
    mr.inputs["From Min"].default_value = min_dot
    mr.inputs["From Max"].default_value = max_dot
    mr.inputs["To Min"].default_value = 0.0
    mr.inputs["To Max"].default_value = 1.0
    nt.links.new(dot.outputs["Value"], mr.inputs["Value"])

    fator_out = mr.outputs["Result"]
    if potencia != 1.0:
        pow_n = nt.nodes.new("ShaderNodeMath")
        pow_n.operation = "POWER"
        pow_n.use_clamp = True
        nt.links.new(fator_out, pow_n.inputs[0])
        pow_n.inputs[1].default_value = float(potencia)
        fator_out = pow_n.outputs["Value"]
    if nome_visivel:
        vis_node = nt.nodes.new("ShaderNodeVertexColor")
        vis_node.layer_name = nome_visivel
        mul_vis = nt.nodes.new("ShaderNodeMath")
        mul_vis.operation = "MULTIPLY"
        mul_vis.use_clamp = True
        nt.links.new(fator_out, mul_vis.inputs[0])
        nt.links.new(vis_node.outputs["Color"], mul_vis.inputs[1])
        fator_out = mul_vis.outputs["Value"]

    uv_node = nt.nodes.new("ShaderNodeUVMap")
    uv_node.uv_map = nome_uv
    return uv_node, fator_out


def _criar_nodos_fator_frontal(nt, nome_uv: str, nome_visivel: str | None = None):
    """Cria nodos Dot-Product entre Normal de mundo e direcao frontal (+Y) com oclusao BVH."""
    return _criar_nodos_fator_vista(nt, (0.0, 1.0, 0.0), nome_uv, nome_visivel=nome_visivel)


def _configurar_bsdf_vc_padrao(nt):
    bsdf = nt.nodes.get("Principled BSDF")
    if bsdf is not None:
        if "Roughness" in bsdf.inputs:
            bsdf.inputs["Roughness"].default_value = 0.78
        if "Metallic" in bsdf.inputs:
            bsdf.inputs["Metallic"].default_value = 0.0
        if "Specular IOR Level" in bsdf.inputs:
            bsdf.inputs["Specular IOR Level"].default_value = 0.18
    return bsdf


def _criar_saida_vc_fallback(nt, nome_cor: str, calibrar_vc: bool):
    vc = nt.nodes.new("ShaderNodeVertexColor")
    vc.layer_name = nome_cor
    vc_out = vc.outputs["Color"]
    if calibrar_vc:
        # TripoSR gera COLOR_0 desaturado/claro em flancos; gamma+leve ajuste evita anel palido nas bordas.
        gamma = nt.nodes.new("ShaderNodeGamma")
        gamma.inputs["Gamma"].default_value = 1.45
        nt.links.new(vc_out, gamma.inputs["Color"])
        hsv = nt.nodes.new("ShaderNodeHueSaturation")
        hsv.inputs["Saturation"].default_value = 1.15
        hsv.inputs["Value"].default_value = 0.88
        nt.links.new(gamma.outputs["Color"], hsv.inputs["Color"])
        vc_out = hsv.outputs["Color"]
    return vc_out


def _criar_material_high_vc(
    nome_mat: str,
    nome_cor: str,
    img_origem=None,
    nome_uv: str = "UV_Camera_Front",
    calibrar_vc: bool = False,
    nome_visivel: str | None = None,
):
    """Material temporario para transferir ``color_attributes`` (e blend frontal 2D) no bake DIFFUSE."""
    mat = bpy.data.materials.new(nome_mat)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = _configurar_bsdf_vc_padrao(nt)
    vc_out = _criar_saida_vc_fallback(nt, nome_cor, calibrar_vc and img_origem is not None)

    if img_origem is None:
        nt.links.new(vc_out, bsdf.inputs["Base Color"])
        return mat

    uv_node, fator_frente = _criar_nodos_fator_frontal(nt, nome_uv, nome_visivel=nome_visivel)
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = img_origem
    tex.extension = "EXTEND"
    nt.links.new(uv_node.outputs["UV"], tex.inputs["Vector"])

    mul_alpha = nt.nodes.new("ShaderNodeMath")
    mul_alpha.operation = "MULTIPLY"
    mul_alpha.use_clamp = True
    nt.links.new(fator_frente, mul_alpha.inputs[0])
    nt.links.new(tex.outputs["Alpha"], mul_alpha.inputs[1])

    mix = nt.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    nt.links.new(mul_alpha.outputs["Value"], mix.inputs[0])
    nt.links.new(vc_out, mix.inputs[6])
    nt.links.new(tex.outputs["Color"], mix.inputs[7])
    nt.links.new(mix.outputs[2], bsdf.inputs["Base Color"])
    return mat


def _criar_material_high_multivista(
    nome_mat: str,
    vistas_dados: list[tuple[str, object, str, str | None, tuple[float, float, float]]],
    nome_cor: str | None = None,
    calibrar_vc: bool = False,
):
    """Combina ate 4 vistas ortograficas por ``normal·dir * visivel * alpha`` com fallback ``VertexColor``."""
    mat = bpy.data.materials.new(nome_mat)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = _configurar_bsdf_vc_padrao(nt)
    fallback_out = _criar_saida_vc_fallback(nt, nome_cor, calibrar_vc) if nome_cor else None
    geom = nt.nodes.new("ShaderNodeNewGeometry")

    w_sum = None
    c_sum = None
    for _vista_key, img_v, nome_uv, nome_vis, dir_mundo in vistas_dados:
        uv_node, fator_v = _criar_nodos_fator_vista(
            nt,
            dir_mundo,
            nome_uv,
            nome_visivel=nome_vis,
            geom=geom,
            min_dot=0.08,
            max_dot=0.90,
            potencia=2.5,
        )
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = img_v
        tex.extension = "EXTEND"
        nt.links.new(uv_node.outputs["UV"], tex.inputs["Vector"])

        mul_w = nt.nodes.new("ShaderNodeMath")
        mul_w.operation = "MULTIPLY"
        mul_w.use_clamp = True
        nt.links.new(fator_v, mul_w.inputs[0])
        nt.links.new(tex.outputs["Alpha"], mul_w.inputs[1])

        scale_c = nt.nodes.new("ShaderNodeVectorMath")
        scale_c.operation = "SCALE"
        nt.links.new(tex.outputs["Color"], scale_c.inputs[0])
        nt.links.new(mul_w.outputs["Value"], scale_c.inputs["Scale"])

        if w_sum is None:
            w_sum = mul_w.outputs["Value"]
            c_sum = scale_c.outputs["Vector"]
        else:
            add_w = nt.nodes.new("ShaderNodeMath")
            add_w.operation = "ADD"
            nt.links.new(w_sum, add_w.inputs[0])
            nt.links.new(mul_w.outputs["Value"], add_w.inputs[1])
            w_sum = add_w.outputs["Value"]

            add_c = nt.nodes.new("ShaderNodeVectorMath")
            add_c.operation = "ADD"
            nt.links.new(c_sum, add_c.inputs[0])
            nt.links.new(scale_c.outputs["Vector"], add_c.inputs[1])
            c_sum = add_c.outputs["Vector"]

    if w_sum is None or c_sum is None:
        if fallback_out is not None:
            nt.links.new(fallback_out, bsdf.inputs["Base Color"])
        return mat

    w_safe = nt.nodes.new("ShaderNodeMath")
    w_safe.operation = "MAXIMUM"
    nt.links.new(w_sum, w_safe.inputs[0])
    w_safe.inputs[1].default_value = 1e-5

    inv_w = nt.nodes.new("ShaderNodeMath")
    inv_w.operation = "DIVIDE"
    inv_w.inputs[0].default_value = 1.0
    nt.links.new(w_safe.outputs["Value"], inv_w.inputs[1])

    c_proj = nt.nodes.new("ShaderNodeVectorMath")
    c_proj.operation = "SCALE"
    nt.links.new(c_sum, c_proj.inputs[0])
    nt.links.new(inv_w.outputs["Value"], c_proj.inputs["Scale"])

    cov = nt.nodes.new("ShaderNodeMapRange")
    cov.clamp = True
    cov.inputs["From Min"].default_value = 0.0
    cov.inputs["From Max"].default_value = 0.12
    cov.inputs["To Min"].default_value = 0.0
    cov.inputs["To Max"].default_value = 1.0
    nt.links.new(w_sum, cov.inputs["Value"])

    mix = nt.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.clamp_factor = True
    nt.links.new(cov.outputs["Result"], mix.inputs[0])
    if fallback_out is not None:
        nt.links.new(fallback_out, mix.inputs[6])
    else:
        mix.inputs[6].default_value = (0.5, 0.5, 0.5, 1.0)
    nt.links.new(c_proj.outputs["Vector"], mix.inputs[7])
    nt.links.new(mix.outputs[2], bsdf.inputs["Base Color"])
    return mat


def _criar_material_high_hints_emit(
    nome_mat: str,
    img_met,
    img_rough,
    nome_uv: str = "UV_Camera_Front",
    nome_cor: str | None = None,
    img_origem=None,
    nome_visivel: str | None = None,
):
    """Shader EMIT temporario que empacota R=metallic, G=roughness, B=peso_pbr."""
    mat = bpy.data.materials.new(nome_mat)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    if bsdf is not None:
        nt.nodes.remove(bsdf)
    out = nt.nodes.get("Material Output")

    uv_node, fator_frente = _criar_nodos_fator_frontal(nt, nome_uv, nome_visivel=nome_visivel)
    fator_pbr = fator_frente
    if nome_cor and img_origem is not None:
        # Propaga hints PBR para flancos/traseira apenas onde COLOR_0 combina com o concept frontal
        vc_hint = nt.nodes.new("ShaderNodeVertexColor")
        vc_hint.layer_name = nome_cor
        tex_orig = nt.nodes.new("ShaderNodeTexImage")
        tex_orig.image = img_origem
        tex_orig.extension = "EXTEND"
        nt.links.new(uv_node.outputs["UV"], tex_orig.inputs["Vector"])

        dist_cor = nt.nodes.new("ShaderNodeVectorMath")
        dist_cor.operation = "DISTANCE"
        nt.links.new(vc_hint.outputs["Color"], dist_cor.inputs[0])
        nt.links.new(tex_orig.outputs["Color"], dist_cor.inputs[1])

        mr_sim = nt.nodes.new("ShaderNodeMapRange")
        mr_sim.clamp = True
        mr_sim.inputs["From Min"].default_value = 0.22
        mr_sim.inputs["From Max"].default_value = 0.50
        mr_sim.inputs["To Min"].default_value = 1.0
        mr_sim.inputs["To Max"].default_value = 0.0
        nt.links.new(dist_cor.outputs["Value"], mr_sim.inputs["Value"])

        max_pbr = nt.nodes.new("ShaderNodeMath")
        max_pbr.operation = "MAXIMUM"
        max_pbr.use_clamp = True
        nt.links.new(fator_frente, max_pbr.inputs[0])
        nt.links.new(mr_sim.outputs["Result"], max_pbr.inputs[1])
        fator_pbr = max_pbr.outputs["Value"]

    comb = nt.nodes.new("ShaderNodeCombineColor")
    comb.mode = "RGB"

    if img_met is not None:
        tex_m = nt.nodes.new("ShaderNodeTexImage")
        tex_m.image = img_met
        tex_m.extension = "EXTEND"
        nt.links.new(uv_node.outputs["UV"], tex_m.inputs["Vector"])

        mul_fa = nt.nodes.new("ShaderNodeMath")
        mul_fa.operation = "MULTIPLY"
        mul_fa.use_clamp = True
        nt.links.new(fator_pbr, mul_fa.inputs[0])
        nt.links.new(tex_m.outputs["Alpha"], mul_fa.inputs[1])

        mul_m = nt.nodes.new("ShaderNodeMath")
        mul_m.operation = "MULTIPLY"
        mul_m.use_clamp = True
        nt.links.new(tex_m.outputs["Color"], mul_m.inputs[0])
        nt.links.new(mul_fa.outputs["Value"], mul_m.inputs[1])
        nt.links.new(mul_m.outputs["Value"], comb.inputs[0])
    else:
        comb.inputs[0].default_value = 0.0

    if img_rough is not None:
        tex_r = nt.nodes.new("ShaderNodeTexImage")
        tex_r.image = img_rough
        tex_r.extension = "EXTEND"
        nt.links.new(uv_node.outputs["UV"], tex_r.inputs["Vector"])
        nt.links.new(tex_r.outputs["Color"], comb.inputs[1])

        mul_r = nt.nodes.new("ShaderNodeMath")
        mul_r.operation = "MULTIPLY"
        mul_r.use_clamp = True
        nt.links.new(fator_pbr, mul_r.inputs[0])
        nt.links.new(tex_r.outputs["Alpha"], mul_r.inputs[1])
        nt.links.new(mul_r.outputs["Value"], comb.inputs[2])
    else:
        comb.inputs[1].default_value = 0.0
        comb.inputs[2].default_value = 0.0

    emit = nt.nodes.new("ShaderNodeEmission")
    emit.inputs["Strength"].default_value = 1.0
    nt.links.new(comb.outputs["Color"], emit.inputs["Color"])
    nt.links.new(emit.outputs["Emission"], out.inputs["Surface"])
    return mat
