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
    from . import bake_pbr_maps as _maps
    from . import bake_pbr_passes as _passes
    from . import bake_pbr_proj as _proj
else:
    _BLENDER_DIR = os.path.dirname(os.path.abspath(__file__))
    if _BLENDER_DIR not in sys.path:
        sys.path.insert(0, _BLENDER_DIR)
    import bake_pbr_config as _cfg
    import bake_pbr_maps as _maps
    import bake_pbr_passes as _passes
    import bake_pbr_proj as _proj


def _resolver_dimensoes_bake(px: int, px_sub: int | None, qualidade: str | None) -> tuple[int, int]:
    px_clamped = max(64, min(int(px), 4096))
    if px_sub is not None and int(px_sub) > 0:
        sub = max(64, min(int(px_sub), px_clamped))
        if px_clamped >= 1024 and sub < 1024:
            sub = 1024
        return px_clamped, sub
    q_low = str(qualidade or "").strip().lower()
    if px_clamped >= 4096:
        return px_clamped, (4096 if q_low == "ultra" else 2048)
    if px_clamped >= 2048:
        return px_clamped, (2048 if q_low == "ultra" else 1024)
    if px_clamped >= 1024:
        return px_clamped, 1024
    return px_clamped, px_clamped


def _executar_retorno_multimaterial(
    obj,
    px: int,
    px_sub: int,
    limite_triangulos: int,
    reparo_fn,
    decimar_fn,
    suavizar_fn,
    uv_fn,
    preset_proc: str,
) -> dict:
    tris_high = _cfg._contar_triangulos(obj)
    decimar_fn(obj, int(limite_triangulos))
    info_reparo = reparo_fn(obj)
    if _cfg._contar_triangulos(obj) > int(limite_triangulos):
        decimar_fn(obj, max(50, int(int(limite_triangulos) * 0.97)))
        info_reparo = reparo_fn(obj)
    info_smooth = suavizar_fn(obj)
    info_uv = uv_fn(obj)
    if not obj.data.uv_layers:
        raise RuntimeError("malha low-poly sem camada UV apos uv_fn")
    tris_low = _cfg._contar_triangulos(obj)
    bpy.context.view_layer.update()
    diag = _cfg._bbox_diag(obj)
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    return {
        "textura_px": px,
        "normal_px": px_sub,
        "orm_px": px_sub,
        "bake": {
            "textura_px": px,
            "normal_px": px_sub,
            "orm_px": px_sub,
            "cor_atributo": "multimaterial",
            "material_procedural": preset_proc or None,
            "dispositivo_cycles": "PRESERVADO_MULTIMATERIAL",
            "samples": 0,
            "bbox_diag": round(diag, 6),
            "cage_extrusion": 0.0,
            "triangulos_high": tris_high,
            "triangulos_low": tris_low,
            "reparo": info_reparo,
            "smooth": info_smooth,
            "uv": info_uv,
            "origem_textura_aplicada": False,
            "vistas_ortograficas_aplicadas": [],
            "metallic_hint_aplicado": False,
            "roughness_hint_aplicado": False,
            "multimaterial_preservado": True,
            "materiais": len(obj.data.materials),
            "png_bytes": 0,
            "baseColor_bytes": 0,
            "normal_bytes": 0,
            "orm_bytes": 0,
        },
        "arquivos_textura": [],
    }


def _calcular_parametros_cage(
    diag: float,
    proteger_superficie: bool,
    tem_detalhe_alto: bool,
    tem_zonas: bool,
    tem_cor_vertice: bool,
) -> tuple[float, float]:
    if proteger_superficie:
        return max(0.010, 0.014 * diag), max(0.025, 0.036 * diag)
    if (tem_detalhe_alto or tem_zonas) and not tem_cor_vertice:
        return max(0.004, min(0.012, 0.008 * diag)), max(0.012, min(0.030, 0.020 * diag))
    return max(0.02, 0.03 * diag), max(0.025, 0.06 * diag)


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
    criar_mat_pbr_fn=None,
) -> dict:
    """Executa bake PBR High->Low (BaseColor, Normal, ORM) e atribui material glTF PBR em ``obj``."""
    if criar_mat_pbr_fn is None:
        raise ValueError("criar_mat_pbr_fn obrigatorio")

    tem_cor_vertice = bool(obj is not None and obj.data is not None and len(obj.data.color_attributes) > 0)
    preset_proc = str(material_procedural or "").strip().lower()
    tem_procedural = bool(preset_proc)
    tem_zonas = bool(pbr_zonas)
    tem_detalhe_alto = bool(isinstance(detalhe_alto, dict) and detalhe_alto.get("ativo", True))
    vistas_norm = _proj._normalizar_vistas_ortograficas(vistas_ortograficas, origem_textura=origem_textura)
    tem_vistas_4v = bool(vistas_norm)
    tem_mat_uv = bool(
        (permitir_sem_cor_vertice or tem_zonas or tem_detalhe_alto)
        and obj is not None
        and obj.data is not None
        and (len(obj.data.uv_layers) > 0 or len(obj.data.materials) > 0 or tem_zonas or tem_detalhe_alto)
    )
    if obj is None or obj.data is None or (
        not tem_cor_vertice and not tem_procedural and not tem_zonas and not tem_mat_uv and not tem_vistas_4v
    ):
        raise RuntimeError("malha sem atributo de cor por vertice para assar PBR")

    os.makedirs(saida_dir, exist_ok=True)
    px, px_sub = _resolver_dimensoes_bake(px, px_sub, qualidade)

    if (
        len(obj.data.materials) > 1
        and not tem_cor_vertice
        and not tem_zonas
        and not tem_vistas_4v
        and not str(perfil_nome or "").startswith("roblox")
    ):
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
        nome_cor = "uv_material"

    tris_high = _cfg._contar_triangulos(obj)
    diag_original = _cfg._bbox_diag(obj)
    passo_zona_x = 6.0
    zonas_deslocadas = _passes._deslocar_zonas_uv(obj, pbr_zonas, passo_zona_x) if tem_zonas else False

    high_mesh = obj.data.copy()
    high_mesh.name = f"{nome_base}_high_mesh"
    high_obj = bpy.data.objects.new(f"{nome_base}_high", high_mesh)
    high_obj.matrix_world = obj.matrix_world.copy()
    colecao = obj.users_collection[0] if obj.users_collection else bpy.context.scene.collection
    colecao.objects.link(high_obj)

    high_mat = high_hints_mat = low_bake_mat = tex_bake = cam_obj = cam_data = None
    img_origem = img_met = img_rough = img_hints_tmp = None
    img_bc = img_nm = img_ao_tmp = img_orm_tmp = None
    imgs_vistas: dict[str, object] = {}
    info_detalhe_alto: dict = {"aplicado": False}
    cena = bpy.context.scene
    estado_anterior = _cfg._capturar_estado_cena(cena)

    try:
        if tem_detalhe_alto:
            info_detalhe_alto = _cfg.preparar_high_mesh_detalhe_alto(high_obj, detalhe_alto)
            tris_high = int(info_detalhe_alto.get("tris_high_enriquecido") or _cfg._contar_triangulos(high_obj))
        suavizar_fn(high_obj)

        if not tem_procedural:
            if vistas_norm:
                img_orig_pref = None
                if origem_textura and os.path.isfile(origem_textura):
                    img_cand = bpy.data.images.load(origem_textura, check_existing=False)
                    img_cand.colorspace_settings.name = "sRGB"
                    front_atual = vistas_norm.get("front")
                    diff_front = (
                        not front_atual
                        or os.path.abspath(origem_textura) != os.path.abspath(front_atual)
                    )
                    if (
                        img_cand.size[0] > 0
                        and img_cand.size[1] > 0
                        and (diff_front or _proj._imagem_tem_alpha_valido(img_cand))
                    ):
                        img_orig_pref = img_cand
                    else:
                        if img_cand.name in bpy.data.images and img_cand.users == 0:
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
            if metallic_hint_png and os.path.isfile(metallic_hint_png):
                img_met = bpy.data.images.load(metallic_hint_png, check_existing=False)
                img_met.colorspace_settings.name = "Non-Color"
            if roughness_hint_png and os.path.isfile(roughness_hint_png):
                img_rough = bpy.data.images.load(roughness_hint_png, check_existing=False)
                img_rough.colorspace_settings.name = "Non-Color"

        cam_obj, cam_data, nome_visivel, vistas_dados = _passes._preparar_projecao_high(
            high_obj, nome_base, colecao, tem_zonas, img_origem, img_met, img_rough, imgs_vistas
        )

        decimar_fn(obj, int(limite_triangulos))
        info_reparo = reparo_fn(obj)
        if _cfg._contar_triangulos(obj) > int(limite_triangulos):
            decimar_fn(obj, max(50, int(int(limite_triangulos) * 0.97)))
            info_reparo = reparo_fn(obj)
        info_smooth = suavizar_fn(obj)
        info_uv = uv_fn(obj)
        if not obj.data.uv_layers:
            raise RuntimeError("malha low-poly sem camada UV apos uv_fn")
        if tem_zonas and not high_obj.data.uv_layers:
            uv_fn(high_obj)
        tris_low = _cfg._contar_triangulos(obj)

        bpy.context.view_layer.update()
        diag = diag_original if zonas_deslocadas else _cfg._bbox_diag(obj)
        cage_extrusion, max_ray_dist = _calcular_parametros_cage(
            diag, proteger_superficie, tem_detalhe_alto, tem_zonas, tem_cor_vertice
        )

        high_mat, proc_mod, usar_emit_proc, met_escalar_orig, rough_escalar_orig = (
            _passes._configurar_high_material(
                high_obj, nome_base, nome_cor, tem_cor_vertice, tem_zonas, tem_procedural,
                preset_proc, pbr_zonas, detalhe_alto, proteger_superficie, img_origem, nome_visivel, vistas_dados,
            )
        )

        low_bake_mat, tex_bake = _maps._criar_material_alvo_bake(f"{nome_base}_low_bake_tmp")
        obj.data.materials.clear()
        obj.data.materials.append(low_bake_mat)

        dispositivo_cycles = _cfg._configurar_dispositivo_cycles(cena, preferir_gpu=True)
        samples_bake = 8 if (usar_emit_proc or permitir_sem_cor_vertice) else 1
        samples_ao = 8 if (usar_emit_proc or permitir_sem_cor_vertice) else 4

        nome_bc, path_bc, img_bc, nome_nm, path_nm, img_nm, img_ao_tmp, img_hints_tmp, high_hints_mat = (
            _passes._executar_passes_cycles(
                cena, obj, high_obj, high_mat, low_bake_mat, tex_bake, saida_dir, nome_base, px, px_sub,
                samples_bake, samples_ao, cage_extrusion, max_ray_dist, usar_emit_proc, proc_mod,
                img_met, img_rough, img_origem, nome_cor, tem_cor_vertice, nome_visivel,
            )
        )

        nome_orm = f"{nome_base}_orm.png"
        path_orm = os.path.join(saida_dir, nome_orm)
        img_orm_tmp = _maps._empacotar_orm(
            img_ao_tmp, f"{nome_base}_orm_tmp", px_sub, img_hints=img_hints_tmp,
            piso_dieletrico_rough=0.68 if (proteger_superficie and not usar_emit_proc) else 0.0,
            metallic_base=met_escalar_orig, roughness_base=rough_escalar_orig,
        )
        bpy.data.images.remove(img_ao_tmp)
        img_ao_tmp = None
        canais_separados = _maps._extrair_canais_roblox(img_orm_tmp, saida_dir, nome_base, px_sub, cena)
        extras_roblox = (
            canais_separados
            if (str(perfil_nome or "").startswith("roblox") or tem_zonas or tem_detalhe_alto)
            else []
        )
        img_orm = _maps._salvar_e_recarregar_png(img_orm_tmp, path_orm, "Non-Color", cena)
        img_orm_tmp = None

        for atributo in list(obj.data.color_attributes):
            obj.data.color_attributes.remove(atributo)

        obj.data.materials.clear()
        mat_final = criar_mat_pbr_fn(f"{nome_base}_pbr", img_bc, img_nm, img_orm)
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
        if zonas_deslocadas and obj is not None and getattr(obj, "data", None) is not None:
            for v_obj in obj.data.vertices:
                kz = int(round(v_obj.co.x / passo_zona_x))
                if kz > 0:
                    v_obj.co.x -= float(kz) * passo_zona_x
            obj.data.update()
        if cam_obj is not None and cam_obj.name in bpy.data.objects:
            bpy.data.objects.remove(cam_obj, do_unlink=True)
        if cam_data is not None and cam_data.name in bpy.data.cameras and cam_data.users == 0:
            bpy.data.cameras.remove(cam_data)
        if high_obj is not None and high_obj.name in bpy.data.objects:
            bpy.data.objects.remove(high_obj, do_unlink=True)
        if high_mesh is not None and high_mesh.name in bpy.data.meshes and high_mesh.users == 0:
            bpy.data.meshes.remove(high_mesh)
        if tex_bake is not None:
            tex_bake.image = None
        for mat_tmp in (high_mat, high_hints_mat, low_bake_mat):
            if mat_tmp is not None and mat_tmp.name in bpy.data.materials and mat_tmp.users == 0:
                bpy.data.materials.remove(mat_tmp)
        vistos_img_ids: set[int] = set()
        for img_tmp in (
            img_origem,
            img_met,
            img_rough,
            img_hints_tmp,
            img_ao_tmp,
            img_orm_tmp,
            img_bc,
            img_nm,
            *imgs_vistas.values(),
        ):
            if img_tmp is not None and id(img_tmp) not in vistos_img_ids:
                vistos_img_ids.add(id(img_tmp))
                if img_tmp.name in bpy.data.images and img_tmp.users == 0:
                    bpy.data.images.remove(img_tmp)
        _cfg._restaurar_estado_cena(cena, estado_anterior)

    bytes_bc, bytes_nm, bytes_orm = os.path.getsize(path_bc), os.path.getsize(path_nm), os.path.getsize(path_orm)
    vistas_aplicadas = list(imgs_vistas.keys())
    return {
        "textura_px": px,
        "normal_px": px_sub,
        "orm_px": px_sub,
        "bake": {
            "textura_px": px, "normal_px": px_sub, "orm_px": px_sub, "cor_atributo": nome_cor,
            "material_procedural": preset_proc or None, "pbr_zonas": len(pbr_zonas) if tem_zonas else 0,
            "detalhe_alto": info_detalhe_alto, "dispositivo_cycles": dispositivo_cycles, "samples": samples_bake,
            "bbox_diag": round(diag, 6), "cage_extrusion": round(cage_extrusion, 6),
            "triangulos_high": tris_high, "triangulos_low": tris_low,
            "reparo": info_reparo, "smooth": info_smooth, "uv": info_uv,
            "origem_textura_aplicada": bool(img_origem is not None or bool(vistas_aplicadas)),
            "vistas_ortograficas_aplicadas": vistas_aplicadas,
            "metallic_hint_aplicado": bool(img_met is not None or usar_emit_proc),
            "roughness_hint_aplicado": bool(img_rough is not None or usar_emit_proc),
            "png_bytes": bytes_bc, "baseColor_bytes": bytes_bc, "normal_bytes": bytes_nm, "orm_bytes": bytes_orm,
        },
        "arquivos_textura": [
            {"caminho": nome_bc, "papel": "textura", "bytes": bytes_bc},
            {"caminho": nome_nm, "papel": "normal", "bytes": bytes_nm},
            {"caminho": nome_orm, "papel": "orm", "bytes": bytes_orm},
            *extras_roblox,
        ],
    }
