"""Orquestracao do bake Cycles High->Low (BaseColor, Normal, ORM) com suporte 1-vista e 4-vistas."""

from __future__ import annotations

import os
import sys

try:
    import bpy
except ImportError:  # pragma: no cover - permite import puro em testes fora do Blender
    bpy = None  # type: ignore[assignment]

if __package__:
    from . import bake_pbr_config as _cfg
    from . import bake_pbr_emissive as _emissive
    from . import bake_pbr_heal as _heal
    from . import bake_pbr_maps as _maps
    from . import bake_pbr_nativo as _nat
    from . import bake_pbr_nativo_back as _nat_back
    from . import bake_pbr_nativo_blend as _nat_blend
    from . import bake_pbr_passes as _passes
    from . import bake_pbr_proj as _proj
else:
    _BLENDER_DIR = os.path.dirname(os.path.abspath(__file__))
    if _BLENDER_DIR not in sys.path:
        sys.path.insert(0, _BLENDER_DIR)
    import bake_pbr_config as _cfg
    import bake_pbr_emissive as _emissive
    import bake_pbr_heal as _heal
    import bake_pbr_maps as _maps
    import bake_pbr_nativo as _nat
    import bake_pbr_nativo_back as _nat_back
    import bake_pbr_nativo_blend as _nat_blend
    import bake_pbr_passes as _passes
    import bake_pbr_proj as _proj

_TIPOS_PROJ_FRONTAL_NATIVO = frozenset({
    "personagem_humanoide", "criatura", "criatura_quadrupede", "criatura_alada", "montaria"
})


def _resolver_dimensoes_bake(px: int, px_sub: int | None, qualidade: str | None) -> tuple[int, int]:
    px_c = max(64, min(int(px), 4096))
    if px_sub is not None and int(px_sub) > 0:
        sub = max(64, min(int(px_sub), px_c))
        return px_c, (1024 if px_c >= 1024 and sub < 1024 else sub)
    q_low = str(qualidade or "").strip().lower()
    if px_c >= 4096:
        return px_c, (4096 if q_low == "ultra" else 2048)
    if px_c >= 2048:
        return px_c, (2048 if q_low == "ultra" else 1024)
    return px_c, (1024 if px_c >= 1024 else px_c)


def _descobrir_caminhos_hints_vistas(
    vistas_norm: dict[str, str],
    vistas_ortograficas: dict[str, str] | None,
    vistas_pbr_hints: dict | None,
    metallic_hint_png: str | None,
    roughness_hint_png: str | None,
) -> dict[str, tuple[str | None, str | None]]:
    """Resolve ``vista -> (metallic_png, roughness_png)`` por kwarg ou auto-descoberta em disco."""
    explicitos: dict[str, tuple[str | None, str | None]] = {}
    if isinstance(vistas_pbr_hints, dict):
        for k_raw, info_h in vistas_pbr_hints.items():
            k_low = str(k_raw or "").strip().lower()
            v_canon = next((vc for vc, meta in _proj._VISTAS_ORTO_DEF.items() if k_low in meta["aliases"]), None)
            if v_canon is None:
                continue
            if isinstance(info_h, dict):
                cm, cr = info_h.get("metallic") or info_h.get("metallic_hint"), info_h.get("roughness") or info_h.get("roughness_hint")
            elif isinstance(info_h, (tuple, list)) and len(info_h) >= 2:
                cm, cr = info_h[0], info_h[1]
            else:
                cm = cr = None
            m_ex = str(cm) if cm and os.path.isfile(str(cm)) else None
            r_ex = str(cr) if cr and os.path.isfile(str(cr)) else None
            if m_ex or r_ex:
                explicitos[v_canon] = (m_ex, r_ex)

    if not vistas_norm and not explicitos and not vistas_ortograficas:
        return {}

    dirs_por_vista: dict[str, list[str]] = {vk: [] for vk in _proj._VISTAS_ORTO_DEF}
    for vk, cam_n in vistas_norm.items():
        d_n = os.path.dirname(os.path.abspath(cam_n))
        if d_n not in dirs_por_vista[vk]:
            dirs_por_vista[vk].append(d_n)
    if isinstance(vistas_ortograficas, dict):
        for k_raw, cam_raw in vistas_ortograficas.items():
            if not cam_raw:
                continue
            k_low = str(k_raw or "").strip().lower()
            for vc, meta in _proj._VISTAS_ORTO_DEF.items():
                if k_low in meta["aliases"]:
                    d_r = os.path.dirname(os.path.abspath(str(cam_raw)))
                    if os.path.isdir(d_r) and d_r not in dirs_por_vista[vc]:
                        dirs_por_vista[vc].append(d_r)

    saida: dict[str, tuple[str | None, str | None]] = {}
    for vk in ("front", "back", "right", "left"):
        m_c, r_c = explicitos.get(vk, (None, None))
        for pasta in dirs_por_vista[vk]:
            p_m, p_r = os.path.join(pasta, f"vista_{vk}_metallic_hint.png"), os.path.join(pasta, f"vista_{vk}_roughness_hint.png")
            if m_c is None and os.path.isfile(p_m):
                m_c = p_m
            if r_c is None and os.path.isfile(p_r):
                r_c = p_r
        if vk == "front" and (vk in vistas_norm or vk in explicitos or dirs_por_vista["front"]):
            m_c = m_c or (metallic_hint_png if metallic_hint_png and os.path.isfile(metallic_hint_png) else None)
            r_c = r_c or (roughness_hint_png if roughness_hint_png and os.path.isfile(roughness_hint_png) else None)
            for pasta in dirs_por_vista["front"]:
                p_m, p_r = os.path.join(pasta, "metallic_hint.png"), os.path.join(pasta, "roughness_hint.png")
                m_c = m_c or (p_m if os.path.isfile(p_m) else None)
                r_c = r_c or (p_r if os.path.isfile(p_r) else None)
        if m_c is not None or r_c is not None:
            saida[vk] = (m_c, r_c)
    return saida


def _preparar_malha_low(obj, limite_triangulos: int, reparo_fn, decimar_fn, suavizar_fn, uv_fn) -> tuple[dict, dict, str, int]:
    decimar_fn(obj, int(limite_triangulos))
    info_reparo = reparo_fn(obj)
    if _cfg._contar_triangulos(obj) > int(limite_triangulos):
        decimar_fn(obj, max(50, int(int(limite_triangulos) * 0.97)))
        info_reparo = reparo_fn(obj)
    info_smooth = suavizar_fn(obj)
    info_uv = uv_fn(obj)
    if not obj.data.uv_layers:
        raise RuntimeError("malha low-poly sem camada UV apos uv_fn")
    return info_reparo, info_smooth, info_uv, _cfg._contar_triangulos(obj)


def _executar_retorno_multimaterial(
    obj, px: int, px_sub: int, limite_triangulos: int,
    reparo_fn, decimar_fn, suavizar_fn, uv_fn, preset_proc: str,
) -> dict:
    tris_high = _cfg._contar_triangulos(obj)
    info_reparo, info_smooth, info_uv, tris_low = _preparar_malha_low(
        obj, limite_triangulos, reparo_fn, decimar_fn, suavizar_fn, uv_fn
    )
    bpy.context.view_layer.update()
    diag = _cfg._bbox_diag(obj)
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    return {
        "textura_px": px, "normal_px": px_sub, "orm_px": px_sub,
        "bake": {
            "textura_px": px, "normal_px": px_sub, "orm_px": px_sub,
            "cor_atributo": "multimaterial", "material_procedural": preset_proc or None,
            "dispositivo_cycles": "PRESERVADO_MULTIMATERIAL", "samples": 0,
            "bbox_diag": round(diag, 6), "cage_extrusion": 0.0,
            "triangulos_high": tris_high, "triangulos_low": tris_low,
            "reparo": info_reparo, "smooth": info_smooth, "uv": info_uv,
            "origem_textura_aplicada": False, "vistas_ortograficas_aplicadas": [],
            "metallic_hint_aplicado": False, "roughness_hint_aplicado": False,
            "delight_hints_aplicados": False, "emissive_aplicado": False,
            "multimaterial_preservado": True, "materiais": len(obj.data.materials),
            "png_bytes": 0, "baseColor_bytes": 0, "normal_bytes": 0, "orm_bytes": 0,
        },
        "arquivos_textura": [],
    }


def _calcular_parametros_cage(
    diag: float, proteger_superficie: bool, tem_detalhe_alto: bool, tem_zonas: bool, tem_cor_vertice: bool,
    usar_pbr_nativo: bool = False,
) -> tuple[float, float]:
    if usar_pbr_nativo:
        return max(0.002, 0.004 * diag), max(0.008, 0.014 * diag)
    if proteger_superficie:
        return max(0.010, 0.014 * diag), max(0.025, 0.036 * diag)
    if (tem_detalhe_alto or tem_zonas) and not tem_cor_vertice:
        return max(0.004, min(0.012, 0.008 * diag)), max(0.012, min(0.030, 0.020 * diag))
    return max(0.02, 0.03 * diag), max(0.025, 0.06 * diag)


def executar_bake_high_low(
    obj, saida_dir: str, nome_base: str, px: int, limite_triangulos: int,
    reparo_fn, decimar_fn, suavizar_fn, uv_fn,
    origem_textura: str | None = None, metallic_hint_png: str | None = None,
    roughness_hint_png: str | None = None, emissive_hint: str | None = None,
    emissive_hint_png: str | None = None, proteger_superficie: bool = False,
    perfil_nome: str | None = None, material_procedural: str | None = None,
    permitir_sem_cor_vertice: bool = False, detalhe_alto: dict | None = None,
    pbr_zonas: list[dict] | None = None, px_sub: int | None = None,
    qualidade: str | None = None, vistas_ortograficas: dict[str, str] | None = None,
    vistas_pbr_hints: dict | None = None, criar_mat_pbr_fn=None, tipo_item: str | None = None,
) -> dict:
    """Executa bake PBR High->Low (BaseColor, Normal, ORM) e atribui material glTF PBR em ``obj``."""
    emissive_cam = _emissive._resolver_emissive_hint_alias(emissive_hint, emissive_hint_png)
    if criar_mat_pbr_fn is None:
        raise ValueError("criar_mat_pbr_fn obrigatorio")

    tem_cor_vertice = bool(obj is not None and obj.data is not None and len(obj.data.color_attributes) > 0)
    preset_proc = str(material_procedural or "").strip().lower()
    tem_procedural, tem_zonas = bool(preset_proc), bool(pbr_zonas)
    tem_detalhe_alto = bool(isinstance(detalhe_alto, dict) and detalhe_alto.get("ativo", True))
    vistas_norm = _proj._normalizar_vistas_ortograficas(vistas_ortograficas, origem_textura=origem_textura)
    tem_vistas_4v = bool(vistas_norm)
    tem_pbr_nativo = bool(not tem_procedural and not tem_zonas and _nat.objeto_tem_pbr_nativo(obj))
    tem_mat_uv = bool(
        (permitir_sem_cor_vertice or tem_zonas or tem_detalhe_alto or tem_pbr_nativo)
        and obj is not None and obj.data is not None
        and (len(obj.data.uv_layers) > 0 or len(obj.data.materials) > 0 or tem_zonas or tem_detalhe_alto)
    )
    if obj is None or obj.data is None or (
        not tem_cor_vertice and not tem_procedural and not tem_zonas and not tem_mat_uv and not tem_vistas_4v
    ):
        raise RuntimeError("malha sem atributo de cor por vertice para assar PBR")

    os.makedirs(saida_dir, exist_ok=True)
    px, px_sub = _resolver_dimensoes_bake(px, px_sub, qualidade)

    if len(obj.data.materials) > 1 and not (tem_cor_vertice or tem_zonas or tem_vistas_4v or str(perfil_nome or "").startswith("roblox")):
        return _executar_retorno_multimaterial(
            obj, px, px_sub, limite_triangulos, reparo_fn, decimar_fn, suavizar_fn, uv_fn, preset_proc
        )

    if tem_cor_vertice:
        ativo_cor = obj.data.color_attributes.active_color
        nome_cor = ativo_cor.name if ativo_cor is not None else obj.data.color_attributes[0].name
    elif tem_zonas:
        nome_cor = f"pbr_zonas:{len(pbr_zonas or [])}"
    elif tem_procedural:
        nome_cor = f"procedural:{preset_proc}"
    else:
        nome_cor = "pbr_nativo" if tem_pbr_nativo else "uv_material"

    passo_zona_x = _passes._calcular_passo_zona_x(obj.data)
    obj["forge3d_passo_zona_x"] = passo_zona_x
    zonas_deslocadas = _passes._deslocar_zonas_uv(obj, pbr_zonas, passo_zona_x) if tem_zonas else False
    info_casca = {"aplicado": False, "faces_removidas": 0, "faces_restantes": 0}
    if tem_pbr_nativo and not zonas_deslocadas:
        info_casca = _cfg.remover_espuma_interna_malha(obj, suavizar_fn=suavizar_fn)
    tris_high, diag_original = _cfg._contar_triangulos(obj), _cfg._bbox_diag(obj)

    high_mesh = obj.data.copy()
    high_mesh.name = f"{nome_base}_high_mesh"
    high_obj = bpy.data.objects.new(f"{nome_base}_high", high_mesh)
    high_obj.matrix_world = obj.matrix_world.copy()
    colecao = obj.users_collection[0] if obj.users_collection else bpy.context.scene.collection
    colecao.objects.link(high_obj)

    high_mat = high_hints_mat = low_bake_mat = tex_bake = cam_obj = cam_data = None
    high_mats_nativos: list = []
    usar_pbr_nativo = not tem_procedural and not tem_zonas and _nat.objeto_tem_pbr_nativo(high_obj)
    img_origem = img_met = img_rough = img_emissive_hint = img_hints_tmp = img_nat_dl_tmp = None
    img_bc = img_nm = img_ao_tmp = img_orm_tmp = img_emissive_final = img_em_nativo = None
    imgs_vistas: dict[str, object] = {}
    imgs_nc_cache: dict[str, object] = {}
    imgs_hints_vistas: dict[str, tuple[object | None, object | None]] = {}
    info_detalhe_alto, info_back, info_front = {"aplicado": False}, {}, {}
    info_heal, stats_cage = {"aplicado": False}, {"aplicado": False}
    delight_hints_aplicados = emissive_aplicado = False
    cena = bpy.context.scene
    estado_anterior = _cfg._capturar_estado_cena(cena)

    def _carregar_nc(cam_img: str | None):
        if not cam_img or not os.path.isfile(cam_img):
            return None
        chave = os.path.abspath(cam_img)
        if chave not in imgs_nc_cache:
            im = bpy.data.images.load(cam_img, check_existing=False)
            im.colorspace_settings.name = "Non-Color"
            imgs_nc_cache[chave] = im
        return imgs_nc_cache[chave]

    try:
        if tem_detalhe_alto and usar_pbr_nativo:
            info_detalhe_alto = {"aplicado": False, "motivo": "pbr_nativo_organico", "tris_high_inicial": tris_high}
        elif tem_detalhe_alto:
            info_detalhe_alto = _cfg.preparar_high_mesh_detalhe_alto(high_obj, detalhe_alto)
            tris_high = int(info_detalhe_alto.get("tris_high_enriquecido") or _cfg._contar_triangulos(high_obj))
        suavizar_fn(high_obj)

        if not tem_procedural:
            img_met = _carregar_nc(metallic_hint_png)
            img_rough = _carregar_nc(roughness_hint_png)
            img_emissive_hint = _carregar_nc(emissive_cam)
            if usar_pbr_nativo:
                if origem_textura and os.path.isfile(origem_textura):
                    img_origem = bpy.data.images.load(origem_textura, check_existing=False)
                    img_origem.colorspace_settings.name = "sRGB"
            else:
                if vistas_norm:
                    img_orig_pref = None
                    if origem_textura and os.path.isfile(origem_textura):
                        img_cand = bpy.data.images.load(origem_textura, check_existing=False)
                        img_cand.colorspace_settings.name = "sRGB"
                        front_atual = vistas_norm.get("front")
                        diff_front = not front_atual or os.path.abspath(origem_textura) != os.path.abspath(front_atual)
                        if img_cand.size[0] > 0 and img_cand.size[1] > 0 and (diff_front or _proj._imagem_tem_alpha_valido(img_cand)):
                            img_orig_pref = img_cand
                        elif img_cand.name in bpy.data.images and img_cand.users == 0:
                            bpy.data.images.remove(img_cand)
                    for vista_key, cam_v in vistas_norm.items():
                        if vista_key == "front" and img_orig_pref is not None:
                            imgs_vistas["front"] = img_orig_pref
                            continue
                        img_v = bpy.data.images.load(cam_v, check_existing=False)
                        img_v.colorspace_settings.name = "sRGB"
                        imgs_vistas[vista_key] = img_v
                    if "front" not in imgs_vistas and img_orig_pref is not None:
                        imgs_vistas["front"] = img_orig_pref
                    img_origem = imgs_vistas.get("front")
                elif origem_textura and os.path.isfile(origem_textura):
                    img_origem = bpy.data.images.load(origem_textura, check_existing=False)
                    img_origem.colorspace_settings.name = "sRGB"
                for vk_h, (cm_h, cr_h) in _descobrir_caminhos_hints_vistas(
                    vistas_norm, vistas_ortograficas, vistas_pbr_hints, metallic_hint_png, roughness_hint_png
                ).items():
                    im_m_h, im_r_h = _carregar_nc(cm_h), _carregar_nc(cr_h)
                    if im_m_h is not None or im_r_h is not None:
                        imgs_hints_vistas[vk_h] = (im_m_h, im_r_h)
                if "front" in imgs_hints_vistas:
                    img_met = img_met or imgs_hints_vistas["front"][0]
                    img_rough = img_rough or imgs_hints_vistas["front"][1]

        if usar_pbr_nativo:
            nome_visivel, vistas_dados, vistas_hints_dados = None, [], []
            if high_obj.data.uv_layers:
                high_obj.data.uv_layers.active = high_obj.data.uv_layers[0]
                high_obj.data.uv_layers[0].active_render = True
        else:
            cam_obj, cam_data, nome_visivel, vistas_dados = _passes._preparar_projecao_high(
                high_obj, nome_base, colecao, tem_zonas, img_origem, img_met, img_rough, imgs_vistas, imgs_hints_vistas
            )
            vistas_hints_dados = _passes._montar_vistas_hints_dados(high_obj, imgs_vistas, imgs_hints_vistas)

        info_reparo, info_smooth, info_uv, tris_low = _preparar_malha_low(
            obj, limite_triangulos, reparo_fn, decimar_fn, suavizar_fn, uv_fn
        )
        if tem_zonas and not high_obj.data.uv_layers:
            uv_fn(high_obj)

        bpy.context.view_layer.update()
        diag = diag_original if zonas_deslocadas else _cfg._bbox_diag(obj)
        if usar_pbr_nativo and not zonas_deslocadas and not info_casca.get("aplicado"):
            info_casca = _cfg.filtrar_casca_interna_high(high_obj, obj, suavizar_fn=suavizar_fn, eh_organico=bool(proteger_superficie))
        cage_base, max_ray_base = _calcular_parametros_cage(
            diag, proteger_superficie, tem_detalhe_alto, tem_zonas, tem_cor_vertice, usar_pbr_nativo=usar_pbr_nativo,
        )
        if not tem_procedural and not tem_zonas:
            eh_org_cage = (tipo_item in _TIPOS_PROJ_FRONTAL_NATIVO) if tipo_item is not None else bool(proteger_superficie)
            cage_extrusion, max_ray_dist, stats_cage = _heal.calcular_cage_adaptativo(
                obj, high_obj, diag, cage_base, max_ray_base, eh_organico=eh_org_cage
            )
        else:
            cage_extrusion, max_ray_dist = cage_base, max_ray_base

        if usar_pbr_nativo:
            high_mats_nativos = _nat.clonar_materiais_nativos(high_obj, nome_base)
            proc_mod, usar_emit_proc, met_escalar_orig, rough_escalar_orig = None, False, 0.0, None
        else:
            high_mat, proc_mod, usar_emit_proc, met_escalar_orig, rough_escalar_orig = _passes._configurar_high_material(
                high_obj, nome_base, nome_cor, tem_cor_vertice, tem_zonas, tem_procedural,
                preset_proc, pbr_zonas, detalhe_alto, proteger_superficie, img_origem, nome_visivel, vistas_dados,
            )

        low_bake_mat, tex_bake = _maps._criar_material_alvo_bake(f"{nome_base}_low_bake_tmp")
        obj.data.materials.clear()
        obj.data.materials.append(low_bake_mat)

        dispositivo_cycles = _cfg._configurar_dispositivo_cycles(cena, preferir_gpu=True)
        samples_bake = 8 if (usar_emit_proc or permitir_sem_cor_vertice) else 1
        samples_ao = 8 if (usar_emit_proc or permitir_sem_cor_vertice) else 4

        nome_bc, path_bc, img_bc, nome_nm, path_nm, img_nm, img_ao_tmp, img_hints_tmp, high_hints_mat, img_em_nativo = _passes._executar_passes_cycles(
            cena, obj, high_obj, high_mat, low_bake_mat, tex_bake, saida_dir, nome_base, px, px_sub,
            samples_bake, samples_ao, cage_extrusion, max_ray_dist, usar_emit_proc, proc_mod,
            img_met, img_rough, img_origem, nome_cor, tem_cor_vertice, nome_visivel, vistas_hints_dados,
            usar_pbr_nativo=usar_pbr_nativo, high_mats_nativos=high_mats_nativos,
        )
        if usar_pbr_nativo and img_bc is not None and img_hints_tmp is not None:
            img_bc, img_nm, info_heal = _heal.curar_ray_misses_pbr(
                cena, obj, high_obj, high_mats_nativos, low_bake_mat, tex_bake,
                img_bc, path_bc, img_nm, path_nm, img_ao_tmp, img_hints_tmp,
                px, px_sub, diag, cage_extrusion, max_ray_dist, stats_cage, samples_bake, samples_ao,
                _passes._margem_bake_px(px, submapa=False), _passes._margem_bake_px(px_sub, submapa=True),
            )
        if usar_pbr_nativo and img_bc is not None:
            if vistas_norm.get("back"):
                info_back = _nat_back.aplicar_vista_traseira_pbr_nativo(
                    cena, obj, img_bc, path_bc, px, nome_base, vistas_norm["back"], img_hints_valid=img_hints_tmp
                )
            cam_front_nat = origem_textura if (origem_textura and os.path.isfile(origem_textura)) else vistas_norm.get("front")
            if (tipo_item in _TIPOS_PROJ_FRONTAL_NATIVO) or (tipo_item is None and bool(proteger_superficie)):
                if cam_front_nat:
                    info_front = _nat_back.aplicar_vista_frontal_pbr_nativo(
                        cena, obj, img_bc, path_bc, px, nome_base, cam_front_nat, img_hints_valid=img_hints_tmp
                    )
            else:
                info_front = {"vista_front_aplicada": False, "motivo": "ignorado_hard_surface"}

        if usar_pbr_nativo and img_hints_tmp is not None:
            img_nat_dl_tmp = _nat_blend.assar_hints_delight_uv0(cena, obj, px_sub, nome_base, img_origem, img_met, img_rough)
            info_nat_mod = _nat_blend.modular_hints_pbr_nativo(img_hints_tmp, img_ao_tmp, px_sub, img_dl_hints=img_nat_dl_tmp, img_bc=img_bc)
            delight_hints_aplicados = bool(info_nat_mod.get("delight_hints_aplicados", False))
            if img_nat_dl_tmp is not None and img_nat_dl_tmp.name in bpy.data.images and img_nat_dl_tmp.users == 0:
                bpy.data.images.remove(img_nat_dl_tmp)
                img_nat_dl_tmp = None
        else:
            delight_hints_aplicados = bool(
                img_met is not None or img_rough is not None
                or any(m is not None or r is not None for m, r in imgs_hints_vistas.values())
            )

        nome_orm = f"{nome_base}_orm.png"
        path_orm = os.path.join(saida_dir, nome_orm)
        piso_rough = 0.0 if usar_pbr_nativo else (0.68 if (proteger_superficie and not usar_emit_proc) else 0.0)
        img_orm_tmp = _maps._empacotar_orm(
            img_ao_tmp, f"{nome_base}_orm_tmp", px_sub, img_hints=img_hints_tmp,
            piso_dieletrico_rough=piso_rough, metallic_base=met_escalar_orig, roughness_base=rough_escalar_orig,
        )
        bpy.data.images.remove(img_ao_tmp)
        img_ao_tmp = None
        extras_roblox = _maps._extrair_canais_roblox(img_orm_tmp, saida_dir, nome_base, px_sub, cena) if (str(perfil_nome or "").startswith("roblox") or tem_zonas or tem_detalhe_alto) else []
        img_orm = _maps._salvar_e_recarregar_png(img_orm_tmp, path_orm, "Non-Color", cena)
        img_orm_tmp = None

        img_emissive_final, img_bc, emissive_aplicado = _passes._assar_emissive_cycles(
            cena, obj, saida_dir, nome_base, px, px_sub, img_emissive_hint, img_origem, img_bc, path_bc,
            img_em_nativo=img_em_nativo,
        )
        img_em_nativo = None

        for atributo in list(obj.data.color_attributes):
            obj.data.color_attributes.remove(atributo)

        obj.data.materials.clear()
        mat_final = criar_mat_pbr_fn(f"{nome_base}_pbr", img_bc, img_nm, img_orm, **({"img_emissive": img_emissive_final} if img_emissive_final is not None else {}))
        if tem_procedural and proc_mod is not None:
            _maps._aplicar_opcoes_especiais_bsdf(mat_final, proc_mod.PRESETS_PBR.get(preset_proc, {}))
        elif met_escalar_orig > 0.0:
            bsdf_f = mat_final.node_tree.nodes.get("Principled BSDF")
            if bsdf_f is not None and "Metallic" in bsdf_f.inputs:
                bsdf_f.inputs["Metallic"].default_value = met_escalar_orig
        obj.data.materials.append(mat_final)
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
    finally:
        if obj is not None and "forge3d_passo_zona_x" in obj:
            del obj["forge3d_passo_zona_x"]
        if zonas_deslocadas and obj is not None and getattr(obj, "data", None) is not None:
            for v_obj in obj.data.vertices:
                if (kz := int(round(v_obj.co.x / passo_zona_x))) > 0:
                    v_obj.co.x -= float(kz) * passo_zona_x
            obj.data.update()
        for obj_t in (cam_obj, high_obj):
            if obj_t is not None and obj_t.name in bpy.data.objects:
                bpy.data.objects.remove(obj_t, do_unlink=True)
        for col, item_t in ((bpy.data.cameras, cam_data), (bpy.data.meshes, high_mesh)):
            if item_t is not None and item_t.name in col and item_t.users == 0:
                col.remove(item_t)
        if tex_bake is not None:
            tex_bake.image = None
        for mat_tmp in (high_mat, high_hints_mat, low_bake_mat, *high_mats_nativos):
            if mat_tmp is not None and mat_tmp.name in bpy.data.materials and mat_tmp.users == 0:
                bpy.data.materials.remove(mat_tmp)
        vistos_img_ids: set[int] = set()
        for img_tmp in (
            img_origem, img_met, img_rough, img_emissive_hint, img_hints_tmp, img_nat_dl_tmp,
            img_ao_tmp, img_orm_tmp, img_bc, img_nm, img_emissive_final, img_em_nativo,
            *imgs_vistas.values(), *imgs_nc_cache.values(),
        ):
            if img_tmp is not None and id(img_tmp) not in vistos_img_ids:
                vistos_img_ids.add(id(img_tmp))
                if img_tmp.name in bpy.data.images and img_tmp.users == 0:
                    bpy.data.images.remove(img_tmp)
        _cfg._restaurar_estado_cena(cena, estado_anterior)

    bytes_bc, bytes_nm, bytes_orm = os.path.getsize(path_bc), os.path.getsize(path_nm), os.path.getsize(path_orm)
    vistas_aplicadas = list(imgs_vistas.keys())
    tem_met_mv = any(m is not None for m, _ in imgs_hints_vistas.values())
    tem_rough_mv = any(r is not None for _, r in imgs_hints_vistas.values())
    return {
        "textura_px": px, "normal_px": px_sub, "orm_px": px_sub,
        "bake": {
            "textura_px": px, "normal_px": px_sub, "orm_px": px_sub, "cor_atributo": nome_cor,
            "material_procedural": preset_proc or None, "pbr_zonas": len(pbr_zonas) if tem_zonas else 0,
            "detalhe_alto": info_detalhe_alto, "dispositivo_cycles": dispositivo_cycles, "samples": samples_bake,
            "bbox_diag": round(diag, 6), "cage_extrusion": round(cage_extrusion, 6),
            "cage_adaptativo": stats_cage, "ray_miss_heal": info_heal, "triangulos_high": tris_high,
            "triangulos_low": tris_low, "reparo": info_reparo, "smooth": info_smooth, "uv": info_uv,
            "origem_textura_aplicada": bool((not usar_pbr_nativo and img_origem is not None) or bool(vistas_aplicadas)),
            "vistas_ortograficas_aplicadas": vistas_aplicadas, "pbr_nativo_preservado": bool(usar_pbr_nativo),
            "vista_back_nativo": info_back, "vista_front_nativo": info_front, "casca_interna_removida": info_casca,
            "metallic_hint_aplicado": bool(img_met is not None or tem_met_mv or usar_emit_proc or usar_pbr_nativo),
            "roughness_hint_aplicado": bool(img_rough is not None or tem_rough_mv or usar_emit_proc or usar_pbr_nativo),
            "delight_hints_aplicados": bool(delight_hints_aplicados), "emissive_aplicado": bool(emissive_aplicado),
            "png_bytes": bytes_bc, "baseColor_bytes": bytes_bc, "normal_bytes": bytes_nm, "orm_bytes": bytes_orm,
        },
        "arquivos_textura": [{"caminho": nome_bc, "papel": "textura", "bytes": bytes_bc}, {"caminho": nome_nm, "papel": "normal", "bytes": bytes_nm}, {"caminho": nome_orm, "papel": "orm", "bytes": bytes_orm}, *extras_roblox],
    }
