"""High->Low PBR bake no Cycles (BaseColor, Normal, ORM) para o pipeline Forge3D.

Roda dentro do Python embutido do Blender 4.2+ usando apenas ``bpy``, ``bmesh``, ``mathutils``
e a biblioteca padrao (sem Pillow nem numpy).
"""

from __future__ import annotations

import os
import sys

try:
    import bpy
except ImportError:  # pragma: no cover - permite import puro em testes fora do Blender
    bpy = None  # type: ignore[assignment]

if __package__:
    from . import bake_pbr_config as _cfg
    from . import bake_pbr_exec as _exec
    from . import bake_pbr_maps as _maps
    from . import bake_pbr_proj as _proj
else:
    _BLENDER_DIR = os.path.dirname(os.path.abspath(__file__))
    if _BLENDER_DIR not in sys.path:
        sys.path.insert(0, _BLENDER_DIR)
    import bake_pbr_config as _cfg
    import bake_pbr_exec as _exec
    import bake_pbr_maps as _maps
    import bake_pbr_proj as _proj

_SUBMODULOS_BPY = (_cfg, _proj, _proj._sh, _maps, _exec, _exec._passes)


def _sync_bpy() -> None:
    alvo = globals().get("bpy")
    for mod in _SUBMODULOS_BPY:
        mod.bpy = alvo


class _BakePbrModule(type(sys)):
    def __setattr__(self, nome: str, valor) -> None:
        super().__setattr__(nome, valor)
        if nome == "bpy":
            for mod in _SUBMODULOS_BPY:
                mod.bpy = valor


if __name__ in sys.modules:
    sys.modules[__name__].__class__ = _BakePbrModule

PISO_PX_ORCAMENTO = _maps.PISO_PX_ORCAMENTO
px_bake_recomendado = _cfg.px_bake_recomendado
deve_ativar_bake_high_low = _cfg.deve_ativar_bake_high_low
construir_shader_pbr_zonas_blender = _cfg.construir_shader_pbr_zonas_blender
_contar_triangulos = _cfg._contar_triangulos
_bbox_diag = _cfg._bbox_diag
_selecionar_high_para_low = _cfg._selecionar_high_para_low
_calcular_bbox_mundo = _cfg._calcular_bbox_mundo
_capturar_estado_cena = _cfg._capturar_estado_cena
_configurar_render_png_linear = _cfg._configurar_render_png_linear
_restaurar_estado_cena = _cfg._restaurar_estado_cena
_suavizar_high_taubin = _cfg._suavizar_high_taubin
_configurar_dispositivo_cycles = _cfg._configurar_dispositivo_cycles
_executar_bake_seguro = _cfg._executar_bake_seguro

_normalizar_vistas_ortograficas = _proj._normalizar_vistas_ortograficas
_detectar_bbox_uv_foreground = _proj._detectar_bbox_uv_foreground
_criar_camera_ortografica_frontal = _proj._criar_camera_ortografica_frontal
_projetar_uv_ortografica_bmesh = _proj._projetar_uv_ortografica_bmesh
_projetar_uv_frontal_bmesh = _proj._projetar_uv_frontal_bmesh
_calcular_oclusao_direcao_bmesh = _proj._calcular_oclusao_direcao_bmesh
_calcular_oclusao_frontal_bmesh = _proj._calcular_oclusao_frontal_bmesh
_criar_nodos_fator_vista = _proj._criar_nodos_fator_vista
_criar_nodos_fator_frontal = _proj._criar_nodos_fator_frontal
_criar_material_high_vc = _proj._criar_material_high_vc
_criar_material_high_multivista = _proj._criar_material_high_multivista
_criar_material_high_hints_emit = _proj._criar_material_high_hints_emit

_criar_material_alvo_bake = _maps._criar_material_alvo_bake
_salvar_e_recarregar_png = _maps._salvar_e_recarregar_png
_empacotar_orm = _maps._empacotar_orm
_extrair_canais_roblox = _maps._extrair_canais_roblox
_obter_grupo_gltf_occlusion = _maps._obter_grupo_gltf_occlusion
_corrigir_normais_invertidas = _maps._corrigir_normais_invertidas
_extrair_escalares_pbr_material = _maps._extrair_escalares_pbr_material
_aplicar_opcoes_especiais_bsdf = _maps._aplicar_opcoes_especiais_bsdf
_redimensionar_png_no_material = _maps._redimensionar_png_no_material


def preparar_high_mesh_detalhe_alto(high_obj, cfg: dict | None) -> dict:
    """Enriquece ``high_obj`` no Blender com crease + Bevel seguro + Subsurf antes do bake Cycles."""
    _sync_bpy()
    return _cfg.preparar_high_mesh_detalhe_alto(high_obj, cfg)


def _criar_material_pbr_gltf(nome_mat: str, img_bc, img_nm, img_orm):
    """Cria o material PBR final compativel com o exportador glTF 2.0 do Blender 4.2."""
    _sync_bpy()
    mat = bpy.data.materials.new(nome_mat)
    mat.use_nodes = True
    mat.use_backface_culling = True
    nt = mat.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    if bsdf is not None:
        if "Roughness" in bsdf.inputs:
            bsdf.inputs["Roughness"].default_value = 0.78
        if "Specular IOR Level" in bsdf.inputs:
            bsdf.inputs["Specular IOR Level"].default_value = 0.18

    tex_bc = nt.nodes.new("ShaderNodeTexImage")
    tex_bc.image = img_bc
    tex_bc.location = (-440, 300)
    nt.links.new(tex_bc.outputs["Color"], bsdf.inputs["Base Color"])

    tex_nm = nt.nodes.new("ShaderNodeTexImage")
    tex_nm.image = img_nm
    tex_nm.location = (-700, -300)
    normal_map = nt.nodes.new("ShaderNodeNormalMap")
    normal_map.space = "TANGENT"
    normal_map.location = (-380, -300)
    nt.links.new(tex_nm.outputs["Color"], normal_map.inputs["Color"])
    nt.links.new(normal_map.outputs["Normal"], bsdf.inputs["Normal"])

    tex_orm = nt.nodes.new("ShaderNodeTexImage")
    tex_orm.image = img_orm
    tex_orm.location = (-700, 0)
    sep = nt.nodes.new("ShaderNodeSeparateColor")
    sep.mode = "RGB"
    sep.location = (-380, 0)
    nt.links.new(tex_orm.outputs["Color"], sep.inputs["Color"])
    nt.links.new(sep.outputs["Green"], bsdf.inputs["Roughness"])
    nt.links.new(sep.outputs["Blue"], bsdf.inputs["Metallic"])

    ng = _maps._obter_grupo_gltf_occlusion()
    gltf_out = nt.nodes.new("ShaderNodeGroup")
    gltf_out.node_tree = ng
    gltf_out.location = (220, -160)
    nt.links.new(sep.outputs["Red"], gltf_out.inputs["Occlusion"])

    return mat


def executar_bake_high_low(
    obj,
    saida_dir: str,
    nome_base: str,
    px: int,
    limite_triangulos: int,
    reparo_fn,
    decimar_fn,
    suavizar_fn,
    uv_fn,
    origem_textura: str | None = None,
    metallic_hint_png: str | None = None,
    roughness_hint_png: str | None = None,
    proteger_superficie: bool = False,
    perfil_nome: str | None = None,
    material_procedural: str | None = None,
    permitir_sem_cor_vertice: bool = False,
    detalhe_alto: dict | None = None,
    pbr_zonas: list[dict] | None = None,
    px_sub: int | None = None,
    qualidade: str | None = None,
    vistas_ortograficas: dict[str, str] | None = None,
) -> dict:
    """Executa bake PBR High->Low (BaseColor, Normal, ORM) e atribui material glTF PBR em ``obj``."""
    _sync_bpy()
    return _exec.executar_bake_high_low(
        obj=obj,
        saida_dir=saida_dir,
        nome_base=nome_base,
        px=px,
        limite_triangulos=limite_triangulos,
        reparo_fn=reparo_fn,
        decimar_fn=decimar_fn,
        suavizar_fn=suavizar_fn,
        uv_fn=uv_fn,
        origem_textura=origem_textura,
        metallic_hint_png=metallic_hint_png,
        roughness_hint_png=roughness_hint_png,
        proteger_superficie=proteger_superficie,
        perfil_nome=perfil_nome,
        material_procedural=material_procedural,
        permitir_sem_cor_vertice=permitir_sem_cor_vertice,
        detalhe_alto=detalhe_alto,
        pbr_zonas=pbr_zonas,
        px_sub=px_sub,
        qualidade=qualidade,
        vistas_ortograficas=vistas_ortograficas,
        criar_mat_pbr_fn=_criar_material_pbr_gltf,
    )


def aplicar_hints_orm_em_material(
    obj,
    saida_dir: str,
    nome_base: str,
    px: int,
    metallic_hint_png: str | None = None,
    roughness_hint_png: str | None = None,
    perfil_nome: str | None = None,
) -> dict | None:
    """Assa hints opcionais de ORM em objeto que ja tem UVMap e material (ex.: extrude_2d)."""
    _sync_bpy()
    return _maps.aplicar_hints_orm_em_material(
        obj=obj,
        saida_dir=saida_dir,
        nome_base=nome_base,
        px=px,
        metallic_hint_png=metallic_hint_png,
        roughness_hint_png=roughness_hint_png,
        perfil_nome=perfil_nome,
    )


def ajustar_resolucao_orcamento(
    obj,
    saida_dir: str,
    texturas_geradas: list[dict],
    glb_caminho: str,
    limite_bytes: int,
    reexportar_fn,
) -> None:
    """Encolhe mapas acima de ``PISO_PX_ORCAMENTO`` (512px) ate caber no teto sem cair abaixo de 512px."""
    _sync_bpy()
    _maps.ajustar_resolucao_orcamento(
        obj=obj,
        saida_dir=saida_dir,
        texturas_geradas=texturas_geradas,
        glb_caminho=glb_caminho,
        limite_bytes=limite_bytes,
        reexportar_fn=reexportar_fn,
    )
