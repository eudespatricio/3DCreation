"""Orquestracao das camadas CC0 3D: carga .mhclo, retracao/decimacao e sobreposicoes."""

from __future__ import annotations

import os
import sys

import bmesh
import bpy

if __package__:
    from . import template_body_armor_3d as _armor
    from . import template_body_assets as _assets
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
    import template_body_hair as _hair
    import template_body_layers_mat as _lmat
    import template_body_suit as _suit
    import template_body_uv as _uv_mod

MACRO_PADRAO = _assets.MACRO_PADRAO
_assar_pose_em_malhas = _assets._assar_pose_em_malhas
_encontrar_ativo_mpfb = _assets._encontrar_ativo_mpfb
_garantir_pacote_mpfb_extraido = _assets._garantir_pacote_mpfb_extraido
_mpfb = _assets._mpfb
aplicar_pose_maos_mpfb = _assets.aplicar_pose_maos_mpfb
limpar_helpers = _assets.limpar_helpers

_construir_sobreposicoes_medievais_3d = _armor._construir_sobreposicoes_medievais_3d

_info_cabeca = _hair._info_cabeca
_info_cabelo = _hair._info_cabelo
_preparar_cabelo_manifold = _hair._preparar_cabelo_manifold
_preparar_textura_e_material_cabelo = _hair._preparar_textura_e_material_cabelo

_preparar_materiais_camadas = _lmat._preparar_materiais_camadas
_unificar_atlas_multicamadas = _lmat._unificar_atlas_multicamadas

_ajustar_malha_suit = _suit._ajustar_malha_suit
_confinar_calca_pos_decimacao = _suit._confinar_calca_pos_decimacao
_fatia_perna = _suit._fatia_perna
_fechar_olhos_manifold = _suit._fechar_olhos_manifold
_garantir_g1_pos_join = _suit._garantir_g1_pos_join
_preparar_camada_mhclo_manifold = _suit._preparar_camada_mhclo_manifold


def _carregar_camadas_mhclo(obj, HumanService, macro_ef: dict, corpo_nu: bool):
    """Carrega olhos, sobrancelhas, traje e sapatos .mhclo antes de limpar_helpers(obj)."""
    eyes_obj = None
    brow_obj = None
    brow_path = None
    suit_obj = None
    shoes_obj = None
    if len(obj.data.vertices) != 19158:
        return eyes_obj, brow_obj, brow_path, suit_obj, shoes_obj

    eyes_path = _encontrar_ativo_mpfb("eyes", "low-poly", ".mhclo")
    if eyes_path:
        try:
            eyes_obj = HumanService.add_mhclo_asset(
                eyes_path,
                obj,
                asset_type="Eyes",
                subdiv_levels=0,
                material_type="GAMEENGINE",
                set_up_rigging=True,
            )
        except (OSError, ValueError, RuntimeError, KeyError) as exc:
            print(f"[template_body] aviso ao carregar eyes ({eyes_path}): {exc}", file=sys.stderr)
            eyes_obj = None

    brow_path = _encontrar_ativo_mpfb("eyebrows", "eyebrow001", ".mhclo")
    if brow_path:
        try:
            brow_obj = HumanService.add_mhclo_asset(
                brow_path,
                obj,
                asset_type="Eyebrows",
                subdiv_levels=0,
                material_type="GAMEENGINE",
                set_up_rigging=True,
            )
        except (OSError, ValueError, RuntimeError, KeyError) as exc:
            print(f"[template_body] aviso ao carregar eyebrows ({brow_path}): {exc}", file=sys.stderr)
            brow_obj = None

    if not corpo_nu:
        eh_fem = float(macro_ef.get("gender", 0.0)) >= 0.5
        suit_nome = "female_casualsuit01" if eh_fem else "male_casualsuit04"
        suit_path = _encontrar_ativo_mpfb("clothes", suit_nome, ".mhclo")
        if suit_path:
            try:
                suit_obj = HumanService.add_mhclo_asset(
                    suit_path,
                    obj,
                    asset_type="Clothes",
                    subdiv_levels=0,
                    material_type="GAMEENGINE",
                    set_up_rigging=True,
                )
            except (OSError, ValueError, RuntimeError, KeyError) as exc:
                print(f"[template_body] aviso ao carregar suit ({suit_path}): {exc}", file=sys.stderr)
                suit_obj = None

        shoes_path = (
            _encontrar_ativo_mpfb("clothes", "shoes01", ".mhclo")
            or _encontrar_ativo_mpfb("clothes", "shoes03", ".mhclo")
        )
        if shoes_path:
            try:
                shoes_obj = HumanService.add_mhclo_asset(
                    shoes_path,
                    obj,
                    asset_type="Clothes",
                    subdiv_levels=0,
                    material_type="GAMEENGINE",
                    set_up_rigging=True,
                )
            except (OSError, ValueError, RuntimeError, KeyError) as exc:
                print(f"[template_body] aviso ao carregar shoes ({shoes_path}): {exc}", file=sys.stderr)
                shoes_obj = None

    for mod in list(obj.modifiers):
        if mod.type == "MASK":
            obj.modifiers.remove(mod)

    vg = {g.name: g.index for g in obj.vertex_groups}
    if eyes_obj is not None:
        bm_h = bmesh.new()
        bm_h.from_mesh(obj.data)
        dl_h = bm_h.verts.layers.deform.active
        ids_eye_h = {vg.get("helper-l-eye"), vg.get("helper-r-eye")} - {None}
        if dl_h is not None and ids_eye_h:
            v_eyes = [v for v in bm_h.verts if set(v[dl_h].keys()) & ids_eye_h]
            if v_eyes:
                bmesh.ops.delete(bm_h, geom=v_eyes, context="VERTS")
                bm_h.to_mesh(obj.data)
        bm_h.free()
    limpar_helpers(obj)
    return eyes_obj, brow_obj, brow_path, suit_obj, shoes_obj


def _destacar_para_metros(m_obj) -> None:
    if m_obj is None:
        return
    for mod in list(m_obj.modifiers):
        if mod.type == "ARMATURE":
            m_obj.modifiers.remove(mod)
    mw = m_obj.matrix_world.copy()
    m_obj.parent = None
    m_obj.matrix_world = mw
    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = m_obj
    m_obj.select_set(True)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)


def vestir_e_texturizar_camadas_cc0(
    obj,
    rig,
    saida: str,
    tam: int,
    macro: dict | None = None,
    job: dict | None = None,
    hair_obj=None,
    estilo_cabelo: str = "",
) -> tuple[str, dict]:
    """Aplica pele anatomica CC0, olhos/sobrancelhas 3D, roupas .mhclo e armadura leve 3D contornada."""
    macro_ef = dict(MACRO_PADRAO)
    if macro:
        macro_ef.update(macro)
    job_ef = job or {}
    esqueleto = str(job_ef.get("esqueleto") or "").strip()
    eh_aa = esqueleto == "godot-humanoid-aa@1"
    corpo_nu = bool(job_ef.get("corpo_nu") is True)
    limite_total = int(job_ef.get("limite_triangulos") or 12000)
    materiais_max = int(job_ef.get("materiais_max") or 8)
    pose_mao_r_default = "open" if eh_aa else "grip"
    pose_mao_l_default = "open" if eh_aa else "cupped"
    pose_mao_r = str(job_ef.get("pose_mao_r") or pose_mao_r_default).strip()
    pose_mao_l = str(job_ef.get("pose_mao_l") or pose_mao_l_default).strip()

    extraido_dir = _garantir_pacote_mpfb_extraido()
    HumanService, _ = _mpfb()

    eyes_obj, brow_obj, brow_path, suit_obj, shoes_obj = _carregar_camadas_mhclo(
        obj, HumanService, macro_ef, corpo_nu
    )

    info_maos = aplicar_pose_maos_mpfb(
        rig,
        pose_mao_r=pose_mao_r,
        pose_mao_l=pose_mao_l,
        compensar_rotacao_z=True,
    )
    malhas_rigadas = [m for m in (obj, eyes_obj, brow_obj, suit_obj, shoes_obj, hair_obj) if m is not None]
    if not bool(job_ef.get("rig", False)) or eh_aa:
        _assar_pose_em_malhas(malhas_rigadas, rig)

    for m_obj in (obj, eyes_obj, brow_obj, suit_obj, shoes_obj, hair_obj):
        _destacar_para_metros(m_obj)

    mats_info = _preparar_materiais_camadas(macro_ef, job_ef, saida, tam, eyes_obj)
    tex_base_path = mats_info["tex_base_path"]
    skin_origem = mats_info["skin_origem"]
    mat_skin = mats_info["mat_skin"]
    mat_tunic = mats_info["mat_tunic"]
    mat_trousers = mats_info["mat_trousers"]
    mat_leather = mats_info["mat_leather"]
    mat_metal = mats_info["mat_metal"]
    mat_eyes = mats_info["mat_eyes"]

    obj.data.materials.clear()
    obj.data.materials.append(mat_skin)
    for p in obj.data.polygons:
        p.material_index = 0

    camadas_join: list = []
    tris_extras = 0
    nomes_camadas: list[str] = ["skin"]

    if eyes_obj is not None:
        topo_e = _fechar_olhos_manifold(eyes_obj)
        eyes_obj.data.materials.clear()
        eyes_obj.data.materials.append(mat_eyes)
        for p in eyes_obj.data.polygons:
            p.material_index = 0
        camadas_join.append(eyes_obj)
        tris_extras += topo_e["triangulos"]
        nomes_camadas.append("eyes/low-poly")

    if brow_obj is not None:
        brow_png_fb = None
        if brow_path:
            cand_bp = os.path.join(os.path.dirname(brow_path), "eyebrow001.png")
            if os.path.isfile(cand_bp):
                brow_png_fb = cand_bp
        _suit._limpar_nao_manifold_aberto(brow_obj)
        _suit._decimar_folha_simples(brow_obj, 360)
        topo_b = _uv_mod.preparar_brow_manifold(brow_obj, thickness=0.0008, offset_normal=0.0009)
        _preparar_textura_e_material_cabelo(
            brow_obj,
            "eyebrow001",
            saida,
            min(tam, 512),
            cor_hex="#261810",
            material_modo="alpha_clip",
            png_nome="brow_baseColor.png",
            alpha_cutoff=0.45,
            fallback_tex_path=brow_png_fb,
            mat_nome="brow",
        )
        for p in brow_obj.data.polygons:
            p.material_index = 0
        camadas_join.append(brow_obj)
        tris_extras += topo_b["triangulos"]
        nomes_camadas.append("eyebrows/eyebrow001")

    if not corpo_nu:
        if suit_obj is not None:
            topo_s = _ajustar_malha_suit(obj, suit_obj, mat_tunic, mat_trousers)
            camadas_join.append(suit_obj)
            tris_extras += topo_s["triangulos"]
            nomes_camadas.append("clothes/suit")

        if shoes_obj is not None:
            topo_sh = _preparar_camada_mhclo_manifold(
                shoes_obj, target_tris=520, thickness=0.0045, offset_normal=0.0025
            )
            shoes_obj.data.materials.clear()
            shoes_obj.data.materials.append(mat_leather)
            for p in shoes_obj.data.polygons:
                p.material_index = 0
            camadas_join.append(shoes_obj)
            tris_extras += topo_sh["triangulos"]
            nomes_camadas.append("clothes/shoes")

    info_cabelo = {}
    if hair_obj is not None:
        cab_info = _info_cabeca(obj)
        info_cabelo = _info_cabelo(hair_obj, obj, cab_info)
        hair_budget = min(max(1400, limite_total // 4), 3200)
        topo_h = _preparar_cabelo_manifold(hair_obj, hair_budget)
        _preparar_textura_e_material_cabelo(
            hair_obj,
            estilo_cabelo or "hair",
            saida,
            tam,
            str(job_ef.get("cor_cabelo") or ""),
            str(job_ef.get("material_cabelo") or "alpha_clip"),
            png_nome="hair_baseColor.png",
        )
        _uv_mod.assar_textura_uv_limpa(
            hair_obj, hair_obj.data.materials[0], saida, tam, png_nome="hair_baseColor.png", com_alfa=True
        )
        camadas_join.append(hair_obj)
        tris_extras += topo_h["triangulos"]
        nomes_camadas.append(f"hair/{estilo_cabelo or 'hair'}")

    # Recolhe pele oculta e decima o corpo ANTES de construir as sobreposicoes 3D conformes.
    if not corpo_nu and suit_obj is not None:
        b_zs = [v.co.z for v in obj.data.vertices]
        bz_min = min(b_zs)
        bh = max(0.5, max(b_zs) - bz_min)
        z_corte_bota = bz_min + 0.285 * bh
        pernas_pts_l = [v.co.copy() for v in obj.data.vertices if v.co.x >= 0.01 * bh and v.co.z <= z_corte_bota + 0.12]
        pernas_pts_r = [v.co.copy() for v in obj.data.vertices if v.co.x <= -0.01 * bh and v.co.z <= z_corte_bota + 0.12]
        for vb in obj.data.vertices:
            zf_b = (vb.co.z - bz_min) / bh
            if 0.045 <= zf_b <= 0.745 and abs(vb.co.x) <= 0.138 * bh:
                if zf_b >= 0.44:
                    vb.co.x *= 0.90
                    vb.co.y *= 0.90
                else:
                    cxl_b, cyl_b, _, _ = _fatia_perna(
                        pernas_pts_l, pernas_pts_r, bh, vb.co.z, vb.co.x >= 0.0
                    )
                    vb.co.x = cxl_b + (vb.co.x - cxl_b) * 0.86
                    vb.co.y = cyl_b + (vb.co.y - cyl_b) * 0.86
        obj.data.update()

    tris_ov_est = (1104 if suit_obj is not None else 1424) if not corpo_nu else 0
    body_budget = max(2600, limite_total - tris_extras - tris_ov_est - 80)
    tris_body = sum(len(p.vertices) - 2 for p in obj.data.polygons)
    if tris_body > body_budget:
        _blender_dir = os.path.dirname(os.path.abspath(__file__))
        if _blender_dir not in sys.path:
            sys.path.insert(0, _blender_dir)
        import postprocess as _pp  # noqa: E402

        _pp.decimar(obj, body_budget, proteger_cabeca_maos=True)

    if not corpo_nu:
        ov_obj = _construir_sobreposicoes_medievais_3d(obj, 0, 1, 2, rig=rig, suit_obj=suit_obj)
        if suit_obj is not None:
            _confinar_calca_pos_decimacao(obj, suit_obj, ov_obj=ov_obj)
        mats_poly = [int(p.material_index) for p in ov_obj.data.polygons]
        ov_obj.data.materials.clear()
        ov_obj.data.materials.append(mat_tunic)
        ov_obj.data.materials.append(mat_leather)
        ov_obj.data.materials.append(mat_metal)
        for p, mi in zip(ov_obj.data.polygons, mats_poly):
            p.material_index = mi
        camadas_join.append(ov_obj)
        tris_extras += len(ov_obj.data.polygons)
        nomes_camadas.extend(["tunic_jerkin_3d", "leather_belt_bracers_boots_3d", "brass_buckle_3d"])

    uv_nome = obj.data.uv_layers[0].name if obj.data.uv_layers else "UVMap"
    for m_obj in [obj, *camadas_join]:
        if not m_obj.data.uv_layers:
            m_obj.data.uv_layers.new(name=uv_nome)
        else:
            m_obj.data.uv_layers[0].name = uv_nome
        while getattr(m_obj.data, "color_attributes", None) and len(m_obj.data.color_attributes) > 0:
            m_obj.data.color_attributes.remove(m_obj.data.color_attributes[0])

    oclusao_info: dict | None = None
    if camadas_join and (
        bool(job_ef.get("recortar_oclusao"))
        or bool((job_ef.get("smart_fit") or {}).get("recortar_oclusao"))
    ):
        _blender_dir = os.path.dirname(os.path.abspath(__file__))
        if _blender_dir not in sys.path:
            sys.path.insert(0, _blender_dir)
        import smart_fit as _sf  # noqa: E402

        coberturas = [c for c in camadas_join if c is not eyes_obj and c is not brow_obj and c is not hair_obj]
        if coberturas:
            try:
                oclusao_info = _sf.recortar_oclusao_interna(obj, coberturas)
            except (RuntimeError, ValueError, ZeroDivisionError) as exc:
                print(f"[template_body] aviso em recortar_oclusao_interna: {exc}", file=sys.stderr)
                oclusao_info = None

    _uv_mod.assar_textura_uv_limpa(obj, mat_skin, saida, min(tam, 1024), png_nome=None, com_alfa=False)

    if camadas_join:
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        for c_obj in camadas_join:
            c_obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.join()

    topo_final = _garantir_g1_pos_join(obj)
    _uv_mod.garantir_uv_materiais_tiled(obj, {"tunic", "trousers", "leather", "metal"})
    _uv_mod.validar_ou_reparar_uv_pos_join(obj)
    if materiais_max <= 1 and len(obj.data.materials) > 1:
        tex_base_path = _unificar_atlas_multicamadas(obj, saida, tam)

    rel_camadas = {
        "modo_textura": "camadas_cc0_3d",
        "projetar_foto_2d": False,
        "esqueleto": esqueleto or "godot-humanoid@1",
        "articulacao_dedos_5": bool(eh_aa or info_maos),
        "olhos_3d": eyes_obj is not None,
        "mandibula_pronta": True,
        "capa_pronta": True,
        "corpo_nu": corpo_nu,
        "skin_origem": skin_origem,
        "pacote_cc0_extraido": bool(extraido_dir),
        "camadas": nomes_camadas,
        "materiais": [m.name for m in obj.data.materials if m is not None],
        "maos": info_maos,
        "topologia": topo_final,
    }
    if oclusao_info is not None:
        rel_camadas["oclusao_cortada"] = oclusao_info
    if info_cabelo:
        rel_camadas["cabelo"] = {"estilo": estilo_cabelo, **info_cabelo}
    return tex_base_path, rel_camadas
