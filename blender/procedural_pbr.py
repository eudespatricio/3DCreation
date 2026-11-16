"""Biblioteca de 10 materiais PBR procedurais 3D Object-Space/Triplanar no Cycles (Blender 4.2+).

Gera grafos de nodos 100% 3D (sem costuras de UV na origem) usando multi-oitavas de
``ShaderNodeTexNoise``, ``ShaderNodeTexVoronoi``, ``ShaderNodeNewGeometry`` (``Pointiness``/``Normal``),
``ShaderNodeAmbientOcclusion`` e ``ShaderNodeBump``, prontos para assar em BaseColor + Normal + ORM
via ``blender/bake_pbr.py``.
"""

from __future__ import annotations

try:
    import bpy
except ImportError:  # pragma: no cover - permite import puro em testes fora do Blender
    bpy = None  # type: ignore[assignment]

__all__ = [
    "MATERIAIS_PROCEDURAIS",
    "PRESETS_PBR",
    "configurar_saida_albedo_emit",
    "configurar_saida_orm_hints_emit",
    "configurar_saida_pbr_bsdf",
    "construir_shader_pbr_zonas_blender",
    "criar_material_procedural",
]

MATERIAIS_PROCEDURAIS: tuple[str, ...] = (
    "pele_humana",
    "escamas_dragao",
    "aco_forjado",
    "ouro_ornamentado",
    "couro_gasto",
    "cristal_arcano",
    "pedra_musgo",
    "tecido_nobre",
    "madeira_ancestral",
    "energia_espectral",
)

#: Parametros fisicos e de relevo multi-oitava em espaco 3D por preset.
PRESETS_PBR: dict[str, dict] = {
    "pele_humana": {
        "cor_base": (0.76, 0.54, 0.43, 1.0),
        "cor_secundaria": (0.64, 0.39, 0.31, 1.0),
        "cor_cavidade": (0.48, 0.29, 0.23, 1.0),
        "cor_crista": (0.85, 0.65, 0.54, 1.0),
        "escala_macro": 6.5,
        "escala_micro": 28.0,
        "escala_voronoi": 46.0,
        "voronoi_feature": "F1",
        "distorcao": 0.35,
        "escala_eixo": (1.0, 1.0, 1.0),
        "metallic_min": 0.0,
        "metallic_max": 0.0,
        "roughness_min": 0.46,
        "roughness_max": 0.66,
        "bump_strength": 0.18,
        "bump_distance": 0.004,
        "ao_distance": 0.18,
        "peso_crista": 0.28,
        "peso_musgo": 0.0,
    },
    "escamas_dragao": {
        "cor_base": (0.018, 0.088, 0.048, 1.0),
        "cor_secundaria": (0.036, 0.145, 0.068, 1.0),
        "cor_cavidade": (0.005, 0.015, 0.010, 1.0),
        "cor_crista": (0.12, 0.25, 0.11, 1.0),
        "escala_macro": 5.5,
        "escala_micro": 26.0,
        "escala_voronoi": 24.0,
        "voronoi_feature": "DISTANCE_TO_EDGE",
        "voronoi_map_range": (0.02, 0.18),
        "distorcao": 0.48,
        "escala_eixo": (1.0, 1.0, 1.18),
        "metallic_min": 0.06,
        "metallic_max": 0.34,
        "roughness_min": 0.24,
        "roughness_max": 0.68,
        "bump_strength": 0.78,
        "bump_distance": 0.018,
        "ao_distance": 0.24,
        "peso_crista": 0.56,
        "peso_musgo": 0.0,
    },
    "aco_forjado": {
        "cor_base": (0.54, 0.57, 0.61, 1.0),
        "cor_secundaria": (0.40, 0.43, 0.47, 1.0),
        "cor_cavidade": (0.20, 0.22, 0.25, 1.0),
        "cor_crista": (0.78, 0.81, 0.85, 1.0),
        "escala_macro": 8.0,
        "escala_micro": 36.0,
        "escala_voronoi": 14.0,
        "voronoi_feature": "F1",
        "distorcao": 0.40,
        "escala_eixo": (1.0, 1.0, 1.0),
        "metallic_min": 0.82,
        "metallic_max": 0.96,
        "roughness_min": 0.22,
        "roughness_max": 0.50,
        "bump_strength": 0.34,
        "bump_distance": 0.008,
        "ao_distance": 0.20,
        "peso_crista": 0.58,
        "peso_musgo": 0.0,
    },
    "ouro_ornamentado": {
        "cor_base": (0.92, 0.71, 0.22, 1.0),
        "cor_secundaria": (0.78, 0.55, 0.15, 1.0),
        "cor_cavidade": (0.46, 0.29, 0.08, 1.0),
        "cor_crista": (0.99, 0.86, 0.45, 1.0),
        "escala_macro": 7.0,
        "escala_micro": 30.0,
        "escala_voronoi": 16.0,
        "voronoi_feature": "DISTANCE_TO_EDGE",
        "distorcao": 0.65,
        "escala_eixo": (1.0, 1.0, 1.0),
        "metallic_min": 0.86,
        "metallic_max": 0.98,
        "roughness_min": 0.16,
        "roughness_max": 0.40,
        "bump_strength": 0.42,
        "bump_distance": 0.009,
        "ao_distance": 0.18,
        "peso_crista": 0.62,
        "peso_musgo": 0.0,
    },
    "couro_gasto": {
        "cor_base": (0.34, 0.19, 0.10, 1.0),
        "cor_secundaria": (0.25, 0.13, 0.07, 1.0),
        "cor_cavidade": (0.14, 0.07, 0.04, 1.0),
        "cor_crista": (0.54, 0.35, 0.20, 1.0),
        "escala_macro": 5.5,
        "escala_micro": 26.0,
        "escala_voronoi": 34.0,
        "voronoi_feature": "F1",
        "distorcao": 0.45,
        "escala_eixo": (1.0, 1.0, 1.0),
        "metallic_min": 0.0,
        "metallic_max": 0.02,
        "roughness_min": 0.46,
        "roughness_max": 0.78,
        "bump_strength": 0.32,
        "bump_distance": 0.007,
        "ao_distance": 0.20,
        "peso_crista": 0.48,
        "peso_musgo": 0.0,
    },
    "cristal_arcano": {
        "cor_base": (0.20, 0.60, 0.92, 1.0),
        "cor_secundaria": (0.36, 0.18, 0.72, 1.0),
        "cor_cavidade": (0.09, 0.12, 0.34, 1.0),
        "cor_crista": (0.68, 0.94, 1.00, 1.0),
        "escala_macro": 4.5,
        "escala_micro": 18.0,
        "escala_voronoi": 9.5,
        "voronoi_feature": "DISTANCE_TO_EDGE",
        "distorcao": 0.25,
        "escala_eixo": (1.0, 1.0, 1.3),
        "metallic_min": 0.0,
        "metallic_max": 0.0,
        "roughness_min": 0.04,
        "roughness_max": 0.08,
        "bump_strength": 0.35,
        "bump_distance": 0.008,
        "ao_distance": 0.24,
        "peso_crista": 0.68,
        "peso_musgo": 0.0,
        "transmission": 0.85,
        "ior": 1.52,
        "alpha": 0.35,
        "blend_method": "BLEND",
        "emission_color": (0.15, 0.85, 1.0, 1.0),
        "emission_strength": 2.0,
    },
    "pedra_musgo": {
        "cor_base": (0.38, 0.39, 0.36, 1.0),
        "cor_secundaria": (0.28, 0.29, 0.27, 1.0),
        "cor_cavidade": (0.15, 0.16, 0.14, 1.0),
        "cor_crista": (0.20, 0.46, 0.16, 1.0),
        "escala_macro": 4.2,
        "escala_micro": 24.0,
        "escala_voronoi": 11.0,
        "voronoi_feature": "F1",
        "distorcao": 0.75,
        "escala_eixo": (1.0, 1.0, 1.0),
        "metallic_min": 0.0,
        "metallic_max": 0.0,
        "roughness_min": 0.70,
        "roughness_max": 0.92,
        "bump_strength": 0.62,
        "bump_distance": 0.014,
        "ao_distance": 0.25,
        "peso_crista": 0.35,
        "peso_musgo": 0.65,
    },
    "tecido_nobre": {
        "cor_base": (0.50, 0.10, 0.16, 1.0),
        "cor_secundaria": (0.36, 0.07, 0.12, 1.0),
        "cor_cavidade": (0.18, 0.03, 0.06, 1.0),
        "cor_crista": (0.76, 0.56, 0.24, 1.0),
        "escala_macro": 6.0,
        "escala_micro": 52.0,
        "escala_voronoi": 44.0,
        "voronoi_feature": "F1",
        "distorcao": 0.30,
        "escala_eixo": (1.0, 1.0, 1.0),
        "metallic_min": 0.0,
        "metallic_max": 0.16,
        "roughness_min": 0.64,
        "roughness_max": 0.88,
        "bump_strength": 0.24,
        "bump_distance": 0.005,
        "ao_distance": 0.18,
        "peso_crista": 0.42,
        "peso_musgo": 0.0,
    },
    "madeira_ancestral": {
        "cor_base": (0.36, 0.22, 0.12, 1.0),
        "cor_secundaria": (0.24, 0.14, 0.07, 1.0),
        "cor_cavidade": (0.13, 0.07, 0.04, 1.0),
        "cor_crista": (0.48, 0.34, 0.21, 1.0),
        "escala_macro": 5.0,
        "escala_micro": 28.0,
        "escala_voronoi": 15.0,
        "voronoi_feature": "DISTANCE_TO_EDGE",
        "distorcao": 0.85,
        "escala_eixo": (2.4, 2.4, 0.45),
        "metallic_min": 0.0,
        "metallic_max": 0.0,
        "roughness_min": 0.56,
        "roughness_max": 0.84,
        "bump_strength": 0.46,
        "bump_distance": 0.010,
        "ao_distance": 0.22,
        "peso_crista": 0.40,
        "peso_musgo": 0.0,
    },
    "energia_espectral": {
        "cor_base": (0.12, 0.82, 0.76, 1.0),
        "cor_secundaria": (0.07, 0.32, 0.54, 1.0),
        "cor_cavidade": (0.04, 0.10, 0.20, 1.0),
        "cor_crista": (0.66, 0.98, 0.92, 1.0),
        "escala_macro": 4.8,
        "escala_micro": 20.0,
        "escala_voronoi": 10.5,
        "voronoi_feature": "DISTANCE_TO_EDGE",
        "distorcao": 1.65,
        "escala_eixo": (1.0, 1.0, 0.8),
        "metallic_min": 0.05,
        "metallic_max": 0.22,
        "roughness_min": 0.18,
        "roughness_max": 0.44,
        "bump_strength": 0.30,
        "bump_distance": 0.008,
        "ao_distance": 0.20,
        "peso_crista": 0.65,
        "peso_musgo": 0.0,
    },
}


def criar_material_procedural(preset: str, nome_mat: str | None = None):
    """Constroi um material Cycles 3D Object-Space completo para ``preset``."""
    chave = str(preset or "").strip().lower()
    if chave not in PRESETS_PBR:
        raise ValueError(
            f"material_procedural desconhecido: {preset!r} "
            f"(validos: {', '.join(MATERIAIS_PROCEDURAIS)})"
        )
    cfg = PRESETS_PBR[chave]
    mat = bpy.data.materials.new(nome_mat or f"forge3d_proc_{chave}")
    mat.use_nodes = True
    mat.use_backface_culling = True
    nt = mat.node_tree
    nt.nodes.clear()

    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.name = "Material Output"
    out.location = (640, 0)

    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.name = "Principled BSDF"
    bsdf.location = (300, 0)
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

    # Coordenadas 3D Object-Space + Mapping (anisotropia opcional para madeira/cristal/escamas)
    tex_coord = nt.nodes.new("ShaderNodeTexCoord")
    tex_coord.location = (-1200, 0)

    mapping = nt.nodes.new("ShaderNodeMapping")
    mapping.location = (-1000, 0)
    mapping.inputs["Scale"].default_value = cfg["escala_eixo"]
    nt.links.new(tex_coord.outputs["Object"], mapping.inputs["Vector"])

    # Geometria (Pointiness + Normal de mundo para mascara de musgo/crista)
    geom = nt.nodes.new("ShaderNodeNewGeometry")
    geom.location = (-1000, 320)

    # Ambient Occlusion 3D para escurecer cavidades
    ao_node = nt.nodes.new("ShaderNodeAmbientOcclusion")
    ao_node.samples = 8
    ao_node.inputs["Distance"].default_value = cfg["ao_distance"]
    ao_node.location = (-760, 420)

    # Oitava 1: Noise 3D macro
    noise_macro = nt.nodes.new("ShaderNodeTexNoise")
    noise_macro.noise_dimensions = "3D"
    noise_macro.inputs["Scale"].default_value = cfg["escala_macro"]
    noise_macro.inputs["Detail"].default_value = 5.0
    noise_macro.inputs["Roughness"].default_value = 0.58
    noise_macro.inputs["Distortion"].default_value = cfg["distorcao"]
    noise_macro.location = (-760, 120)
    nt.links.new(mapping.outputs["Vector"], noise_macro.inputs["Vector"])

    # Oitava 2: Noise 3D micro (alta frequencia)
    noise_micro = nt.nodes.new("ShaderNodeTexNoise")
    noise_micro.noise_dimensions = "3D"
    noise_micro.inputs["Scale"].default_value = cfg["escala_micro"]
    noise_micro.inputs["Detail"].default_value = 8.0
    noise_micro.inputs["Roughness"].default_value = 0.65
    noise_micro.inputs["Distortion"].default_value = 0.15
    noise_micro.location = (-760, -140)
    nt.links.new(mapping.outputs["Vector"], noise_micro.inputs["Vector"])

    # Celulas 3D: Voronoi (escamas, poros, cristais, martelado, fibras)
    voronoi = nt.nodes.new("ShaderNodeTexVoronoi")
    voronoi.voronoi_dimensions = "3D"
    voronoi.feature = cfg["voronoi_feature"]
    voronoi.inputs["Scale"].default_value = cfg["escala_voronoi"]
    voronoi.inputs["Randomness"].default_value = 0.85
    voronoi.location = (-760, -400)
    nt.links.new(mapping.outputs["Vector"], voronoi.inputs["Vector"])
    vor_out = (
        voronoi.outputs["Distance"]
        if "Distance" in voronoi.outputs
        else voronoi.outputs[0]
    )
    if "voronoi_map_range" in cfg:
        vmin, vmax = cfg["voronoi_map_range"]
        mr_vor = nt.nodes.new("ShaderNodeMapRange")
        mr_vor.clamp = True
        mr_vor.inputs["From Min"].default_value = float(vmin)
        mr_vor.inputs["From Max"].default_value = float(vmax)
        mr_vor.inputs["To Min"].default_value = 0.0
        mr_vor.inputs["To Max"].default_value = 1.0
        mr_vor.location = (-540, -380)
        nt.links.new(vor_out, mr_vor.inputs["Value"])
        vor_out = mr_vor.outputs["Result"]

    # Combina macro + micro + voronoi em campo de altura/mascara [0..1]
    mix_oct = nt.nodes.new("ShaderNodeMix")
    mix_oct.data_type = "FLOAT"
    mix_oct.inputs["Factor"].default_value = 0.38
    mix_oct.location = (-500, -40)
    nt.links.new(noise_macro.outputs["Fac"], mix_oct.inputs[2])
    nt.links.new(noise_micro.outputs["Fac"], mix_oct.inputs[3])

    mix_altura = nt.nodes.new("ShaderNodeMix")
    mix_altura.data_type = "FLOAT"
    mix_altura.inputs["Factor"].default_value = 0.62 if "voronoi_map_range" in cfg else 0.45
    mix_altura.name = "Forge3D_HeightField"
    mix_altura.location = (-300, -140)
    nt.links.new(mix_oct.outputs[0], mix_altura.inputs[2])
    nt.links.new(vor_out, mix_altura.inputs[3])

    # Mascara de Pointiness (desgaste de borda / brilho de crista)
    mr_point = nt.nodes.new("ShaderNodeMapRange")
    mr_point.clamp = True
    mr_point.inputs["From Min"].default_value = 0.47
    mr_point.inputs["From Max"].default_value = 0.58
    mr_point.inputs["To Min"].default_value = 0.0
    mr_point.inputs["To Max"].default_value = cfg["peso_crista"]
    mr_point.location = (-500, 260)
    nt.links.new(geom.outputs["Pointiness"], mr_point.inputs["Value"])

    fator_crista = mr_point.outputs["Result"]
    if cfg["peso_musgo"] > 0.0:
        # Em pedra_musgo, combina faces voltadas para +Z com noise macro
        sep_n = nt.nodes.new("ShaderNodeSeparateXYZ")
        sep_n.location = (-760, 620)
        nt.links.new(geom.outputs["Normal"], sep_n.inputs["Vector"])
        mr_z = nt.nodes.new("ShaderNodeMapRange")
        mr_z.clamp = True
        mr_z.inputs["From Min"].default_value = 0.15
        mr_z.inputs["From Max"].default_value = 0.65
        mr_z.inputs["To Min"].default_value = 0.0
        mr_z.inputs["To Max"].default_value = cfg["peso_musgo"]
        mr_z.location = (-500, 560)
        nt.links.new(sep_n.outputs["Z"], mr_z.inputs["Value"])
        mul_musgo = nt.nodes.new("ShaderNodeMath")
        mul_musgo.operation = "MULTIPLY"
        mul_musgo.use_clamp = True
        mul_musgo.location = (-300, 480)
        nt.links.new(mr_z.outputs["Result"], mul_musgo.inputs[0])
        nt.links.new(noise_macro.outputs["Fac"], mul_musgo.inputs[1])
        fator_crista = mul_musgo.outputs["Value"]

    # Base Color: blend cor_base <-> cor_secundaria pelo campo multi-oitava,
    # escurece cavidades via AO e aplica cor_crista nas bordas/topo.
    mix_cor1 = nt.nodes.new("ShaderNodeMix")
    mix_cor1.data_type = "RGBA"
    mix_cor1.clamp_factor = True
    mix_cor1.inputs[6].default_value = cfg["cor_base"]
    mix_cor1.inputs[7].default_value = cfg["cor_secundaria"]
    mix_cor1.location = (-100, 220)
    nt.links.new(mix_altura.outputs[0], mix_cor1.inputs[0])

    mix_ao = nt.nodes.new("ShaderNodeMix")
    mix_ao.data_type = "RGBA"
    mix_ao.clamp_factor = True
    mix_ao.inputs[6].default_value = cfg["cor_cavidade"]
    mix_ao.location = (60, 220)
    nt.links.new(ao_node.outputs["AO"], mix_ao.inputs[0])
    nt.links.new(mix_cor1.outputs[2], mix_ao.inputs[7])

    mix_final_cor = nt.nodes.new("ShaderNodeMix")
    mix_final_cor.data_type = "RGBA"
    mix_final_cor.clamp_factor = True
    mix_final_cor.name = "Forge3D_AlbedoOut"
    mix_final_cor.inputs[7].default_value = cfg["cor_crista"]
    mix_final_cor.location = (180, 220)
    nt.links.new(fator_crista, mix_final_cor.inputs[0])
    nt.links.new(mix_ao.outputs[2], mix_final_cor.inputs[6])
    nt.links.new(mix_final_cor.outputs[2], bsdf.inputs["Base Color"])

    # Metallic 3D espacialmente variavel
    mr_met = nt.nodes.new("ShaderNodeMapRange")
    mr_met.clamp = True
    mr_met.name = "Forge3D_MetallicOut"
    mr_met.inputs["From Min"].default_value = 0.0
    mr_met.inputs["From Max"].default_value = 1.0
    mr_met.inputs["To Min"].default_value = cfg["metallic_min"]
    mr_met.inputs["To Max"].default_value = cfg["metallic_max"]
    mr_met.location = (40, -40)
    nt.links.new(mix_altura.outputs[0], mr_met.inputs["Value"])
    nt.links.new(mr_met.outputs["Result"], bsdf.inputs["Metallic"])

    # Roughness 3D espacialmente variavel (inverso da crista + micro-relevo)
    mr_rough = nt.nodes.new("ShaderNodeMapRange")
    mr_rough.clamp = True
    mr_rough.name = "Forge3D_RoughnessOut"
    mr_rough.inputs["From Min"].default_value = 0.0
    mr_rough.inputs["From Max"].default_value = 1.0
    mr_rough.inputs["To Min"].default_value = cfg["roughness_min"]
    mr_rough.inputs["To Max"].default_value = cfg["roughness_max"]
    mr_rough.location = (40, -240)
    nt.links.new(mix_oct.outputs[0], mr_rough.inputs["Value"])
    nt.links.new(mr_rough.outputs["Result"], bsdf.inputs["Roughness"])

    if "Metallic" in bsdf.inputs:
        bsdf.inputs["Metallic"].default_value = float(
            0.5 * (cfg.get("metallic_min", 0.0) + cfg.get("metallic_max", 0.0))
        )
    if "Roughness" in bsdf.inputs:
        bsdf.inputs["Roughness"].default_value = float(
            0.5 * (cfg.get("roughness_min", 0.5) + cfg.get("roughness_max", 0.5))
        )
    if cfg.get("blend_method") and hasattr(mat, "blend_method"):
        mat.blend_method = str(cfg["blend_method"])
    if "transmission" in cfg and "Transmission Weight" in bsdf.inputs:
        bsdf.inputs["Transmission Weight"].default_value = float(cfg["transmission"])
    if "ior" in cfg and "IOR" in bsdf.inputs:
        bsdf.inputs["IOR"].default_value = float(cfg["ior"])
    if "alpha" in cfg and "Alpha" in bsdf.inputs:
        bsdf.inputs["Alpha"].default_value = float(cfg["alpha"])
    if "emission_color" in cfg and "Emission Color" in bsdf.inputs:
        bsdf.inputs["Emission Color"].default_value = tuple(cfg["emission_color"])
    if "emission_strength" in cfg and "Emission Strength" in bsdf.inputs:
        bsdf.inputs["Emission Strength"].default_value = float(cfg["emission_strength"])

    # Bump 3D tangente conectado ao Normal do Principled BSDF
    bump = nt.nodes.new("ShaderNodeBump")
    bump.name = "Forge3D_BumpOut"
    bump.inputs["Strength"].default_value = cfg["bump_strength"]
    bump.inputs["Distance"].default_value = cfg["bump_distance"]
    bump.location = (40, -440)
    nt.links.new(mix_altura.outputs[0], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])

    # Nodo Emission auxiliar para bake limpo de Albedo e ORM (evita atenuacao de metais no DIFFUSE)
    emit = nt.nodes.new("ShaderNodeEmission")
    emit.name = "Forge3D_BakeEmit"
    emit.inputs["Strength"].default_value = 1.0
    emit.location = (300, 320)

    comb_orm = nt.nodes.new("ShaderNodeCombineColor")
    comb_orm.mode = "RGB"
    comb_orm.name = "Forge3D_CombineHintsORM"
    comb_orm.inputs[2].default_value = 1.0
    comb_orm.location = (180, -140)
    nt.links.new(mr_met.outputs["Result"], comb_orm.inputs[0])
    nt.links.new(mr_rough.outputs["Result"], comb_orm.inputs[1])

    mat["forge3d_preset_procedural"] = chave
    return mat


def _hex_para_rgba_linear(cor_hex: str) -> tuple[float, float, float, float]:
    limpo = str(cor_hex).strip().lstrip("#")
    if len(limpo) != 6:
        return (0.5, 0.5, 0.5, 1.0)
    r = int(limpo[0:2], 16) / 255.0
    g = int(limpo[2:4], 16) / 255.0
    b = int(limpo[4:6], 16) / 255.0

    def _srgb_lin(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    return (_srgb_lin(r), _srgb_lin(g), _srgb_lin(b), 1.0)


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

        cor_base = (
            _hex_para_rgba_linear(str(z["cor_tinta"]))
            if z.get("cor_tinta")
            else tuple(p.get("cor_base", (0.5, 0.5, 0.5, 1.0)))
        )
        cor_sec = (
            _hex_para_rgba_linear(str(z["cor_tinta"]))
            if z.get("cor_tinta")
            else tuple(p.get("cor_secundaria", cor_base))
        )

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


def configurar_saida_albedo_emit(mat) -> None:
    """Conecta ``Forge3D_AlbedoOut`` via ``Emission`` ao ``Material Output`` para assar BaseColor."""
    nt = mat.node_tree
    albedo = nt.nodes.get("Forge3D_AlbedoOut")
    emit = nt.nodes.get("Forge3D_BakeEmit")
    out = nt.nodes.get("Material Output")
    if albedo is not None and emit is not None and out is not None:
        saida_cor = albedo.outputs["Result"] if "Result" in albedo.outputs else albedo.outputs[2]
        nt.links.new(saida_cor, emit.inputs["Color"])
        nt.links.new(emit.outputs["Emission"], out.inputs["Surface"])


def configurar_saida_orm_hints_emit(mat) -> None:
    """Conecta ``(R=Metallic, G=Roughness, B=1.0)`` via ``Emission`` ao ``Material Output``."""
    nt = mat.node_tree
    comb = nt.nodes.get("Forge3D_CombineHintsORM")
    emit = nt.nodes.get("Forge3D_BakeEmit")
    out = nt.nodes.get("Material Output")
    if comb is not None and emit is not None and out is not None:
        nt.links.new(comb.outputs["Color"], emit.inputs["Color"])
        nt.links.new(emit.outputs["Emission"], out.inputs["Surface"])


def configurar_saida_pbr_bsdf(mat) -> None:
    """Restaura ``Principled BSDF`` no ``Material Output`` (para bake de ``NORMAL`` e ``AO``)."""
    nt = mat.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    out = nt.nodes.get("Material Output")
    if bsdf is not None and out is not None:
        nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
