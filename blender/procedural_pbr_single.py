"""Construtor de material PBR procedural 3D unico e helpers de saida para bake Cycles."""

from __future__ import annotations

import os
import sys

try:
    import bpy
except ImportError:  # pragma: no cover - permite import puro em testes fora do Blender
    bpy = None  # type: ignore[assignment]

if __package__:
    from .procedural_pbr_presets import MATERIAIS_PROCEDURAIS, PRESETS_PBR
else:
    _BLENDER_DIR = os.path.dirname(os.path.abspath(__file__))
    if _BLENDER_DIR not in sys.path:
        sys.path.insert(0, _BLENDER_DIR)
    from procedural_pbr_presets import MATERIAIS_PROCEDURAIS, PRESETS_PBR


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
