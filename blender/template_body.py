"""Corpo base por template MPFB2 (CC0) + textura projetada da foto frontal (bpy puro, I9).

Uso: blender -b --python blender/template_body.py -- <job.json>
job.json: {"foto": png RGBA (fundo sangrado), "saida": dir, "macro": {...} opcional,
           "auto_ajuste": true, "braco_graus": 7.0, "antebraco_graus": 1.0,
           "perna_graus": -2.0, "marcos": {"olhos_frac": float, "boca_frac": float} opcional,
           "textura": 1024, "rig": false}
Escreve <saida>/template_body.glb (A-pose, frente +Y), baseColor.png e relatorio.json.
"""

from __future__ import annotations

import json
import math
import os
import sys

import bpy
from mathutils import Matrix

if __package__:
    from . import template_body_armor_3d as _armor
    from . import template_body_assets as _assets
    from . import template_body_camadas as _camadas
    from . import template_body_foto as _foto
    from . import template_body_hair as _hair
    from . import template_body_layers_mat as _lmat
    from . import template_body_suit as _suit
    from . import template_body_uv as _uv_mod
else:
    _BLENDER_DIR = os.path.dirname(os.path.abspath(__file__))
    if _BLENDER_DIR not in sys.path:
        sys.path.insert(0, _BLENDER_DIR)
    import template_body_armor_3d as _armor
    import template_body_assets as _assets
    import template_body_camadas as _camadas
    import template_body_foto as _foto
    import template_body_hair as _hair
    import template_body_layers_mat as _lmat
    import template_body_suit as _suit
    import template_body_uv as _uv_mod

MACRO_PADRAO = _assets.MACRO_PADRAO
GRADE = _assets.GRADE
_OSSOS_BRACO_DISTAL = _assets._OSSOS_BRACO_DISTAL
_OSSOS_BRACO = _assets._OSSOS_BRACO
_OSSOS_TRONCO = _assets._OSSOS_TRONCO
_CATEGORIAS_MPFB_CC0 = _assets._CATEGORIAS_MPFB_CC0
_ANGULOS_DEDOS_POSE = _assets._ANGULOS_DEDOS_POSE

_srgb_to_linear = _assets._srgb_to_linear
_rgba_srgb_to_linear = _assets._rgba_srgb_to_linear
_hex_to_rgb_srgb = _assets._hex_to_rgb_srgb
_mpfb = _assets._mpfb
_garantir_pacote_mpfb_extraido = _assets._garantir_pacote_mpfb_extraido
_raizes_categoria_mpfb = _assets._raizes_categoria_mpfb
_encontrar_ativo_mpfb = _assets._encontrar_ativo_mpfb
_encontrar_mhclo_cabelo = _assets._encontrar_mhclo_cabelo
criar_humano = _assets.criar_humano
limpar_helpers = _assets.limpar_helpers
_limpar_nao_manifold_aberto = _assets._limpar_nao_manifold_aberto
aplicar_pose_maos_mpfb = _assets.aplicar_pose_maos_mpfb
_assar_pose_em_malhas = _assets._assar_pose_em_malhas

_apontar = _foto._apontar
posar = _foto.posar
coords_posadas = _foto.coords_posadas
Foto = _foto.Foto
_limites_xy = _foto._limites_xy
iou = _foto.iou
auto_ajuste = _foto.auto_ajuste
_mapear_t_z = _foto._mapear_t_z
_peso_grupo = _foto._peso_grupo
_centro_z_grupo = _foto._centro_z_grupo
projetar_e_assar = _foto.projetar_e_assar

_info_cabeca = _hair._info_cabeca
_info_cabelo = _hair._info_cabelo
_preparar_cabelo_manifold = _hair._preparar_cabelo_manifold
_preparar_textura_e_material_cabelo = _hair._preparar_textura_e_material_cabelo
_unificar_materiais_corpo_cabelo = _hair._unificar_materiais_corpo_cabelo

_selecionar_skin_cc0 = _lmat._selecionar_skin_cc0
_gerar_pele_procedural_limpa = _lmat._gerar_pele_procedural_limpa
_criar_material_pbr = _lmat._criar_material_pbr
_unificar_atlas_multicamadas = _lmat._unificar_atlas_multicamadas

_fechar_olhos_manifold = _suit._fechar_olhos_manifold
_preparar_camada_mhclo_manifold = _suit._preparar_camada_mhclo_manifold
_garantir_g1_pos_join = _suit._garantir_g1_pos_join

_adicionar_tubo_contornado_manifold = _armor._adicionar_tubo_contornado_manifold
_construir_sobreposicoes_medievais_3d = _armor._construir_sobreposicoes_medievais_3d

vestir_e_texturizar_camadas_cc0 = _camadas.vestir_e_texturizar_camadas_cc0


def exportar(
    obj,
    rig,
    saida: str,
    manter_rig: bool,
    nome_glb: str = "template_body.glb",
    ja_rotacionado: bool = False,
) -> str:
    if rig is not None:
        for pb in rig.pose.bones:
            pb.matrix_basis = Matrix.Identity(4)
        bpy.context.view_layer.update()
    bpy.ops.object.select_all(action="DESELECT")
    if manter_rig and rig is not None:
        if not ja_rotacionado:
            rig.rotation_euler.z = math.pi
        rig.select_set(True)
        obj.select_set(True)
        for filho in rig.children:
            filho.select_set(True)
        bpy.context.view_layer.objects.active = rig
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
        bpy.ops.object.select_all(action="DESELECT")
        rig.select_set(True)
    else:
        for mod in list(obj.modifiers):
            if mod.type == "ARMATURE":
                obj.modifiers.remove(mod)
        mw = obj.matrix_world.copy()
        obj.parent = None
        obj.matrix_world = mw
        obj.vertex_groups.clear()
        if rig is not None:
            bpy.data.objects.remove(rig, do_unlink=True)
        if not ja_rotacionado:
            obj.rotation_euler.z = math.pi
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    _blender_dir = os.path.dirname(os.path.abspath(__file__))
    if _blender_dir not in sys.path:
        sys.path.insert(0, _blender_dir)
    import postprocess as _pp  # noqa: E402

    if obj is not None and getattr(obj, "type", None) == "MESH":
        _pp.suavizar_por_angulo(obj, angulo_graus=65.0)
    if manter_rig and rig is not None:
        for filho in rig.children:
            if filho is not obj and getattr(filho, "type", None) == "MESH":
                _pp.suavizar_por_angulo(filho, angulo_graus=65.0)
    bpy.ops.object.select_all(action="DESELECT")
    if manter_rig and rig is not None:
        rig.select_set(True)
        for filho in rig.children:
            filho.select_set(True)
    obj.select_set(True)
    glb = os.path.join(saida, nome_glb)
    export_kw = {
        "filepath": glb,
        "use_selection": True,
        "export_format": "GLB",
        "export_animations": False,
        "export_normals": True,
        "export_tangents": True,
    }
    bpy.ops.export_scene.gltf(**export_kw)
    return glb


def main() -> int:
    with open(sys.argv[sys.argv.index("--") + 1], encoding="utf-8") as f_job:
        job = json.load(f_job)
    saida = job["saida"]
    os.makedirs(saida, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    macro = dict(MACRO_PADRAO)
    macro.update(job.get("macro") or {})
    alvos = {"nipple-point-decr": 1.0, "nipple-size-decr": 1.0}
    alvos.update(job.get("alvos") or {})

    modo = str(job.get("modo") or "corpo").strip().lower()
    mh_req = str(job.get("mhclo") or job.get("makehuman_cabelo") or "").strip()
    mhclo_path = _encontrar_mhclo_cabelo(mh_req) if mh_req else None
    estilo = str(job.get("estilo") or (os.path.splitext(os.path.basename(mhclo_path))[0] if mhclo_path else "")).strip()

    obj, rig, hair_obj = criar_humano(macro, alvos, mhclo_cabelo=mhclo_path)

    if modo == "cabelo":
        limpar_helpers(obj)
        info_cabeca = _info_cabeca(obj)
        if hair_obj is None:
            raise SystemExit("modo 'cabelo' exige 'mhclo' ou 'makehuman_cabelo'")
        info_cabelo = _info_cabelo(hair_obj, obj, info_cabeca)
        # Remove corpo/rig mantendo apenas o cabelo encaixado ao macro exato do personagem
        bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.objects.remove(rig, do_unlink=True)
        topo = _preparar_cabelo_manifold(hair_obj, int(job.get("limite_triangulos", 6000)))
        tex = _preparar_textura_e_material_cabelo(
            hair_obj,
            estilo or "hair",
            saida,
            int(job.get("textura", 1024)),
            str(job.get("cor_cabelo") or ""),
            str(job.get("material") or "alpha_clip"),
        )
        _uv_mod.assar_textura_uv_limpa(
            hair_obj, hair_obj.data.materials[0], saida, int(job.get("textura", 1024)), png_nome="baseColor.png", com_alfa=True
        )
        glb = exportar(hair_obj, None, saida, False, nome_glb="template_hair.glb")
        rel = {
            "glb": glb,
            "baseColor": tex,
            "modo": "cabelo",
            "estilo": estilo,
            "triangulos": topo["triangulos"],
            "nao_manifold": topo["nao_manifold"],
            "degeneradas": topo["degeneradas"],
            "template": "mpfb2 (CC0)",
            "macro": macro,
            "cabeca": info_cabeca,
            "encaixe_cabeca": info_cabelo,
        }
        with open(os.path.join(saida, "relatorio.json"), "w", encoding="utf-8") as f_rel:
            json.dump(rel, f_rel, indent=2)
        print("TEMPLATE_HAIR_OK", json.dumps({"estilo": estilo, **topo}))
        return 0

    if not bool(job.get("projetar_foto_2d") is True):
        tex, info_camadas = vestir_e_texturizar_camadas_cc0(
            obj,
            rig,
            saida,
            int(job.get("textura", 1024)),
            macro=macro,
            job=job,
            hair_obj=hair_obj,
            estilo_cabelo=estilo,
        )
        info_cabeca = _info_cabeca(obj)
        esqueleto_req = str(job.get("esqueleto") or "").strip()
        manter_rig = bool(job.get("rig", False))
        ossos_export = 0
        if manter_rig and esqueleto_req == "godot-humanoid-aa@1":
            for mod in list(obj.modifiers):
                if mod.type == "ARMATURE":
                    obj.modifiers.remove(mod)
            mw = obj.matrix_world.copy()
            obj.parent = None
            obj.matrix_world = mw
            obj.vertex_groups.clear()
            if rig is not None:
                bpy.data.objects.remove(rig, do_unlink=True)
            obj.rotation_euler.z = math.pi
            bpy.ops.object.select_all(action="DESELECT")
            bpy.context.view_layer.objects.active = obj
            obj.select_set(True)
            bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
            _blender_dir = os.path.dirname(os.path.abspath(__file__))
            if _blender_dir not in sys.path:
                sys.path.insert(0, _blender_dir)
            import autorig as _ar  # noqa: E402
            import postprocess as _pp  # noqa: E402

            rig_aa, _grupos_aa = _ar.auto_rigar_humanoide(obj, "godot-humanoid-aa@1", _pp.criar_armadura)
            ossos_export = len(rig_aa.data.bones)
            glb = exportar(obj, rig_aa, saida, True, ja_rotacionado=True)
        else:
            glb = exportar(obj, rig, saida, manter_rig)
        topo_rel = info_camadas.get("topologia") or {}
        rel = {
            "glb": glb,
            "baseColor": tex,
            "braco_graus": 35.0,
            "antebraco_graus": 0.0,
            "perna_graus": 0.0,
            "iou_silhueta": None,
            "triangulos": sum(len(p.vertices) - 2 for p in obj.data.polygons),
            "nao_manifold": int(topo_rel.get("nao_manifold", 0)),
            "degeneradas": int(topo_rel.get("degeneradas", 0)),
            "template": "mpfb2 (CC0)",
            "macro": macro,
            "cabeca": info_cabeca,
            "camadas_cc0": info_camadas,
            "maos": info_camadas.get("maos") or {},
        }
        if ossos_export:
            rel["esqueleto"] = esqueleto_req
            rel["ossos"] = ossos_export
        if info_camadas.get("cabelo"):
            rel["cabelo"] = info_camadas["cabelo"]
        with open(os.path.join(saida, "relatorio.json"), "w", encoding="utf-8") as f_rel:
            json.dump(rel, f_rel, indent=2)
        print(
            "TEMPLATE_OK",
            json.dumps(
                {
                    "modo_textura": "camadas_cc0_3d",
                    "triangulos": rel["triangulos"],
                    "nao_manifold": rel["nao_manifold"],
                }
            ),
        )
        return 0

    limpar_helpers(obj)
    info_cabeca = _info_cabeca(obj)
    foto = Foto(job["foto"])
    upper = float(job.get("braco_graus", 7.0))
    lower = float(job.get("antebraco_graus", 1.0))
    perna = float(job.get("perna_graus", -2.0))
    score = None
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="POSE")
    if job.get("auto_ajuste", True):
        score, upper, lower, perna = auto_ajuste(obj, rig, foto, upper, lower, perna)
    else:
        posar(rig, upper, lower, perna)
    bpy.ops.object.mode_set(mode="OBJECT")
    tex, info_proj = projetar_e_assar(obj, foto, saida, int(job.get("textura", 1024)), job.get("marcos"))
    info_maos = aplicar_pose_maos_mpfb(
        rig,
        pose_mao_r=str(job.get("pose_mao_r") or "grip"),
        pose_mao_l=str(job.get("pose_mao_l") or "cupped"),
        compensar_rotacao_z=True,
    )
    if not bool(job.get("rig", False)):
        _assar_pose_em_malhas([obj], rig)

    info_cabelo = {}
    if hair_obj is not None:
        info_cabelo = _info_cabelo(hair_obj, obj, info_cabeca)
        limite_total = int(job.get("limite_triangulos", 12000))
        hair_budget = min(max(1500, limite_total // 3), 4500)
        topo_hair = _preparar_cabelo_manifold(hair_obj, hair_budget)
        tex_cabelo = _preparar_textura_e_material_cabelo(
            hair_obj,
            estilo or "hair",
            saida,
            int(job.get("textura", 1024)),
            str(job.get("cor_cabelo") or ""),
            str(job.get("material_cabelo") or "alpha_clip"),
            png_nome="hair_baseColor.png",
        )
        _uv_mod.assar_textura_uv_limpa(
            hair_obj, hair_obj.data.materials[0], saida, int(job.get("textura", 1024)), png_nome="hair_baseColor.png", com_alfa=True
        )
        # Mantem o total corpo+cabelo dentro do teto protegendo cabeca/maos (nunca decimate cego no rosto)
        body_budget = max(2500, limite_total - topo_hair["triangulos"])
        tris_body = sum(len(p.vertices) - 2 for p in obj.data.polygons)
        if tris_body > body_budget:
            if not bool(job.get("rig", False)):
                for pb in rig.pose.bones:
                    pb.matrix_basis = Matrix.Identity(4)
                bpy.context.view_layer.update()
                for mod in list(obj.modifiers):
                    if mod.type == "ARMATURE":
                        obj.modifiers.remove(mod)
            _blender_dir = os.path.dirname(os.path.abspath(__file__))
            if _blender_dir not in sys.path:
                sys.path.insert(0, _blender_dir)
            import postprocess as _pp  # noqa: E402

            _pp.decimar(obj, body_budget, proteger_cabeca_maos=True)
        if hair_obj.data.uv_layers and obj.data.uv_layers:
            hair_obj.data.uv_layers[0].name = obj.data.uv_layers[0].name
        if int(job.get("materiais_max") or 8) <= 1:
            _unificar_materiais_corpo_cabelo(
                obj,
                hair_obj,
                tex,
                tex_cabelo,
                int(job.get("textura", 1024)),
            )
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        hair_obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.join()

    glb = exportar(obj, rig, saida, bool(job.get("rig", False)))
    rel = {
        "glb": glb,
        "baseColor": tex,
        "braco_graus": upper,
        "antebraco_graus": lower,
        "perna_graus": perna,
        "iou_silhueta": score,
        "triangulos": sum(len(p.vertices) - 2 for p in obj.data.polygons),
        "template": "mpfb2 (CC0)",
        "macro": macro,
        "cabeca": info_cabeca,
        "projecao": info_proj,
        "maos": info_maos,
    }
    if info_cabelo:
        rel["cabelo"] = {"estilo": estilo, **info_cabelo}
    with open(os.path.join(saida, "relatorio.json"), "w", encoding="utf-8") as f_rel:
        json.dump(rel, f_rel, indent=2)
    print(
        "TEMPLATE_OK",
        json.dumps({k: rel[k] for k in ("braco_graus", "antebraco_graus", "perna_graus", "iou_silhueta", "triangulos")}),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
