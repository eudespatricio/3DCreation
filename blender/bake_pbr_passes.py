"""Passes Cycles (BaseColor, Normal, AO, Hints) e helpers de preparacao de cena para bake PBR."""

from __future__ import annotations

import os
import sys

try:
    import bmesh
    import bpy
except ImportError:  # pragma: no cover - permite import puro em testes fora do Blender
    bmesh = None  # type: ignore[assignment]
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


def _deslocar_zonas_uv(obj, pbr_zonas: list[dict] | None, passo_zona_x: float = 6.0) -> bool:
    if not pbr_zonas or not obj.data.uv_layers:
        return False
    bm_z = bmesh.new()
    zonas_deslocadas = False
    try:
        bm_z.from_mesh(obj.data)
        bm_z.verts.ensure_lookup_table()
        uv_z = bm_z.loops.layers.uv.active
        if uv_z is None:
            return False
        vis_z: set = set()
        comps_z: list[list] = []
        for v0 in bm_z.verts:
            if v0 in vis_z:
                continue
            pilha_z, comp_z = [v0], []
            vis_z.add(v0)
            while pilha_z:
                vc = pilha_z.pop()
                comp_z.append(vc)
                for ed in vc.link_edges:
                    vn = ed.other_vert(vc)
                    if vn not in vis_z:
                        vis_z.add(vn)
                        pilha_z.append(vn)
            comps_z.append(comp_z)
        if len(comps_z) <= 1:
            return False
        for comp_z in comps_z:
            us_c = [lp[uv_z].uv.x for v in comp_z for lp in v.link_loops]
            vs_c = [lp[uv_z].uv.y for v in comp_z for lp in v.link_loops]
            if not us_c:
                continue
            u_m = sum(us_c) / float(len(us_c))
            v_m = sum(vs_c) / float(len(vs_c))
            z_escolhida, melhor_dist = 0, 1e9
            for idx_z, z_cfg in enumerate(pbr_zonas):
                faixa = z_cfg.get("uv_faixa") if isinstance(z_cfg, dict) else None
                if isinstance(faixa, (list, tuple)) and len(faixa) == 4:
                    u0, v0_f, u1, v1_f = float(faixa[0]), float(faixa[1]), float(faixa[2]), float(faixa[3])
                    du = 0.0 if u0 <= u_m <= u1 else min(abs(u_m - u0), abs(u_m - u1))
                    dv = 0.0 if v0_f <= v_m <= v1_f else min(abs(v_m - v0_f), abs(v_m - v1_f))
                    if du + dv < melhor_dist:
                        melhor_dist = du + dv
                        z_escolhida = idx_z
            dx_z = float(z_escolhida) * passo_zona_x
            if abs(dx_z) > 1e-6:
                for v in comp_z:
                    v.co.x += dx_z
                zonas_deslocadas = True
        if zonas_deslocadas:
            bm_z.to_mesh(obj.data)
            obj.data.update()
        return zonas_deslocadas
    finally:
        bm_z.free()


def _preparar_projecao_high(
    high_obj,
    nome_base: str,
    colecao,
    tem_zonas: bool,
    img_origem,
    img_met,
    img_rough,
    imgs_vistas: dict[str, object],
):
    """Projeta UVs ortograficas 4-vistas ou 1-vista (fallback) + oclusao BVH em ``high_obj``."""
    cam_obj = cam_data = nome_visivel = None
    vistas_dados: list[tuple[str, object, str, str | None, tuple[float, float, float]]] = []
    if tem_zonas:
        return cam_obj, cam_data, nome_visivel, vistas_dados

    precisa_hints = img_met is not None or img_rough is not None
    if imgs_vistas:
        min_v, max_v = _cfg._calcular_bbox_mundo(high_obj)
        cam_obj, cam_data = _proj._criar_camera_ortografica_frontal(
            f"{nome_base}_cam_proj_tmp", min_v, max_v, colecao
        )
        uvs_necessarias = [_proj._VISTAS_ORTO_DEF[vk]["uv"] for vk in imgs_vistas]
        if precisa_hints and "UV_Camera_Front" not in uvs_necessarias:
            uvs_necessarias.append("UV_Camera_Front")
        _proj._podar_uv_layers_high(high_obj, uvs_necessarias)
        for vista_key, img_v in imgs_vistas.items():
            meta_v = _proj._VISTAS_ORTO_DEF[vista_key]
            uv_bbox = _proj._detectar_bbox_uv_foreground(img_v)
            _proj._projetar_uv_ortografica_bmesh(high_obj, vista_key, min_v, max_v, uv_bbox, meta_v["uv"])
            vis_attr = _proj._calcular_oclusao_direcao_bmesh(high_obj, meta_v["dir"], meta_v["vis"])
            if vista_key == "front":
                nome_visivel = vis_attr
            vistas_dados.append((vista_key, img_v, meta_v["uv"], vis_attr, meta_v["dir"]))
        if precisa_hints and "front" not in imgs_vistas:
            _proj._projetar_uv_frontal_bmesh(
                high_obj, min_v, max_v, (0.0, 1.0, 0.0, 1.0), "UV_Camera_Front"
            )
            nome_visivel = _proj._calcular_oclusao_frontal_bmesh(high_obj)
        return cam_obj, cam_data, nome_visivel, vistas_dados

    if img_origem is not None or precisa_hints:
        min_v, max_v = _cfg._calcular_bbox_mundo(high_obj)
        cam_obj, cam_data = _proj._criar_camera_ortografica_frontal(
            f"{nome_base}_cam_proj_tmp", min_v, max_v, colecao
        )
        _proj._podar_uv_layers_high(high_obj, ["UV_Camera_Front"])
        uv_bbox = (
            _proj._detectar_bbox_uv_foreground(img_origem)
            if img_origem is not None
            else (0.0, 1.0, 0.0, 1.0)
        )
        _proj._projetar_uv_frontal_bmesh(high_obj, min_v, max_v, uv_bbox, "UV_Camera_Front")
        nome_visivel = _proj._calcular_oclusao_frontal_bmesh(high_obj)
    return cam_obj, cam_data, nome_visivel, vistas_dados


def _configurar_high_material(
    high_obj,
    nome_base: str,
    nome_cor: str,
    tem_cor_vertice: bool,
    tem_zonas: bool,
    tem_procedural: bool,
    preset_proc: str,
    pbr_zonas: list[dict] | None,
    detalhe_alto: dict | None,
    proteger_superficie: bool,
    img_origem,
    nome_visivel: str | None,
    vistas_dados: list,
):
    proc_mod = None
    usar_emit_proc = False
    met_escalar_orig = 0.0
    rough_escalar_orig: float | None = None

    if tem_zonas:
        proc_mod = __import__("procedural_pbr")
        usar_emit_proc = True
        ao_forca = float((detalhe_alto or {}).get("ao_cavidade_forca", 0.35) if isinstance(detalhe_alto, dict) else 0.35)
        high_mat = proc_mod.construir_shader_pbr_zonas_blender(
            f"{nome_base}_high_zonas_tmp",
            list(pbr_zonas or []),
            presets_pbr=proc_mod.PRESETS_PBR,
            img_paleta=img_origem,
            nome_cor_vertice=nome_cor if tem_cor_vertice else None,
            ao_cavidade_forca=ao_forca,
        )
    elif tem_procedural:
        proc_mod = __import__("procedural_pbr")
        usar_emit_proc = True
        high_mat = proc_mod.criar_material_procedural(preset_proc, nome_mat=f"{nome_base}_high_proc_tmp")
    elif vistas_dados:
        mat_src = high_obj.data.materials[0] if high_obj.data.materials else None
        if not tem_cor_vertice and mat_src is not None:
            met_escalar_orig, rough_escalar_orig = _maps._extrair_escalares_pbr_material(mat_src)
        high_mat = _sh._criar_material_high_multivista(
            f"{nome_base}_high_4v_tmp",
            vistas_dados,
            nome_cor=nome_cor if tem_cor_vertice else None,
            calibrar_vc=proteger_superficie,
        )
    elif tem_cor_vertice:
        high_mat = _sh._criar_material_high_vc(
            f"{nome_base}_high_bake_tmp",
            nome_cor,
            img_origem=img_origem,
            nome_uv="UV_Camera_Front",
            calibrar_vc=proteger_superficie,
            nome_visivel=nome_visivel,
        )
    else:
        mat_src = high_obj.data.materials[0] if high_obj.data.materials else None
        met_escalar_orig, rough_escalar_orig = _maps._extrair_escalares_pbr_material(mat_src)
        if mat_src is not None:
            high_mat = mat_src.copy()
            high_mat.name = f"{nome_base}_high_mat_tmp"
        elif img_origem is not None:
            high_mat = bpy.data.materials.new(f"{nome_base}_high_tex_tmp")
            high_mat.use_nodes = True
            nt_h = high_mat.node_tree
            bsdf_h = nt_h.nodes.get("Principled BSDF")
            tex_h = nt_h.nodes.new("ShaderNodeTexImage")
            tex_h.image = img_origem
            nt_h.links.new(tex_h.outputs["Color"], bsdf_h.inputs["Base Color"])
        else:
            high_mat = bpy.data.materials.new(f"{nome_base}_high_def_tmp")
            high_mat.use_nodes = True

    high_obj.data.materials.clear()
    high_obj.data.materials.append(high_mat)
    return high_mat, proc_mod, usar_emit_proc, met_escalar_orig, rough_escalar_orig


def _executar_passes_cycles(
    cena,
    obj,
    high_obj,
    high_mat,
    low_bake_mat,
    tex_bake,
    saida_dir: str,
    nome_base: str,
    px: int,
    px_sub: int,
    samples_bake: int,
    samples_ao: int,
    cage_extrusion: float,
    max_ray_dist: float,
    usar_emit_proc: bool,
    proc_mod,
    img_met,
    img_rough,
    img_origem,
    nome_cor: str,
    tem_cor_vertice: bool,
    nome_visivel: str | None,
):
    cena.cycles.use_denoising = False
    cena.render.bake.use_selected_to_active = True
    cena.render.bake.use_cage = True
    cena.render.bake.cage_object = None
    cena.render.bake.cage_extrusion = cage_extrusion
    cena.render.bake.max_ray_distance = max_ray_dist
    cena.render.bake.use_clear = True
    _cfg._configurar_render_png_linear(cena)

    img_bc_tmp = img_bc = img_nm_tmp = img_nm = img_ao_tmp = img_hints_tmp = high_hints_mat = None
    try:
        # 1. BaseColor em `px`
        nome_bc = f"{nome_base}_baseColor.png"
        path_bc = os.path.join(saida_dir, nome_bc)
        img_bc_tmp = bpy.data.images.new(f"{nome_base}_bc_tmp", width=px, height=px, alpha=False)
        img_bc_tmp.colorspace_settings.name = "sRGB"
        tex_bake.image = img_bc_tmp
        tex_bake.select = True
        low_bake_mat.node_tree.nodes.active = tex_bake
        cena.cycles.samples = samples_bake
        cena.render.bake.margin = max(4, px // 128)
        _cfg._selecionar_high_para_low(high_obj, obj)
        if usar_emit_proc and proc_mod is not None:
            proc_mod.configurar_saida_albedo_emit(high_mat)
            _cfg._executar_bake_seguro(cena, type="EMIT")
            proc_mod.configurar_saida_pbr_bsdf(high_mat)
        else:
            bsdf_h = high_mat.node_tree.nodes.get("Principled BSDF") if high_mat else None
            met_ant = None
            if bsdf_h is not None and "Metallic" in bsdf_h.inputs:
                met_ant = float(bsdf_h.inputs["Metallic"].default_value)
                bsdf_h.inputs["Metallic"].default_value = 0.0
            cena.render.bake.use_pass_direct = False
            cena.render.bake.use_pass_indirect = False
            cena.render.bake.use_pass_color = True
            _cfg._executar_bake_seguro(cena, type="DIFFUSE")
            if bsdf_h is not None and met_ant is not None:
                bsdf_h.inputs["Metallic"].default_value = met_ant
        img_bc = _maps._salvar_e_recarregar_png(img_bc_tmp, path_bc, "sRGB", cena)
        img_bc_tmp = None

        # 2. Normal (TANGENT) em `px_sub` (sem contaminacao Sobel do BaseColor)
        nome_nm = f"{nome_base}_normal.png"
        path_nm = os.path.join(saida_dir, nome_nm)
        img_nm_tmp = bpy.data.images.new(f"{nome_base}_nm_tmp", width=px_sub, height=px_sub, alpha=False)
        img_nm_tmp.colorspace_settings.name = "Non-Color"
        tex_bake.image = img_nm_tmp
        tex_bake.select = True
        low_bake_mat.node_tree.nodes.active = tex_bake
        cena.cycles.samples = samples_bake
        cena.render.bake.normal_space = "TANGENT"
        cena.render.bake.normal_r = "POS_X"
        cena.render.bake.normal_g = "POS_Y"
        cena.render.bake.normal_b = "POS_Z"
        cena.render.bake.margin = max(4, px_sub // 128)
        _cfg._selecionar_high_para_low(high_obj, obj)
        _cfg._executar_bake_seguro(cena, type="NORMAL")
        _maps._corrigir_normais_invertidas(img_nm_tmp, px_sub)
        img_nm = _maps._salvar_e_recarregar_png(img_nm_tmp, path_nm, "Non-Color", cena)
        img_nm_tmp = None

        # 3. ORM via AO + hints opcionais/procedurais em `px_sub`
        img_ao_tmp = bpy.data.images.new(f"{nome_base}_ao_tmp", width=px_sub, height=px_sub, alpha=False)
        img_ao_tmp.colorspace_settings.name = "Non-Color"
        tex_bake.image = img_ao_tmp
        tex_bake.select = True
        low_bake_mat.node_tree.nodes.active = tex_bake
        cena.cycles.samples = samples_ao
        cena.render.bake.margin = max(4, px_sub // 128)
        _cfg._selecionar_high_para_low(high_obj, obj)
        _cfg._executar_bake_seguro(cena, type="AO")

        if usar_emit_proc and proc_mod is not None:
            proc_mod.configurar_saida_orm_hints_emit(high_mat)
            img_hints_tmp = bpy.data.images.new(f"{nome_base}_hints_tmp", width=px_sub, height=px_sub, alpha=False)
            img_hints_tmp.colorspace_settings.name = "Non-Color"
            tex_bake.image = img_hints_tmp
            tex_bake.select = True
            low_bake_mat.node_tree.nodes.active = tex_bake
            cena.cycles.samples = samples_bake
            cena.render.bake.margin = max(4, px_sub // 128)
            _cfg._selecionar_high_para_low(high_obj, obj)
            _cfg._executar_bake_seguro(cena, type="EMIT")
            proc_mod.configurar_saida_pbr_bsdf(high_mat)
        elif img_met is not None or img_rough is not None:
            high_hints_mat = _sh._criar_material_high_hints_emit(
                f"{nome_base}_high_hints_tmp",
                img_met,
                img_rough,
                nome_uv="UV_Camera_Front",
                nome_cor=nome_cor if tem_cor_vertice else None,
                img_origem=img_origem,
                nome_visivel=nome_visivel,
            )
            high_obj.data.materials.clear()
            high_obj.data.materials.append(high_hints_mat)
            img_hints_tmp = bpy.data.images.new(f"{nome_base}_hints_tmp", width=px_sub, height=px_sub, alpha=False)
            img_hints_tmp.colorspace_settings.name = "Non-Color"
            tex_bake.image = img_hints_tmp
            tex_bake.select = True
            low_bake_mat.node_tree.nodes.active = tex_bake
            cena.cycles.samples = 1
            cena.render.bake.margin = max(4, px_sub // 128)
            _cfg._selecionar_high_para_low(high_obj, obj)
            _cfg._executar_bake_seguro(cena, type="EMIT")
    except Exception:
        tex_bake.image = None
        if high_hints_mat is not None:
            high_obj.data.materials.clear()
            if high_hints_mat.name in bpy.data.materials and high_hints_mat.users == 0:
                bpy.data.materials.remove(high_hints_mat)
        for img_tmp in (img_bc_tmp, img_bc, img_nm_tmp, img_nm, img_ao_tmp, img_hints_tmp):
            if img_tmp is not None and img_tmp.name in bpy.data.images and img_tmp.users == 0:
                bpy.data.images.remove(img_tmp)
        raise

    return (
        nome_bc,
        path_bc,
        img_bc,
        nome_nm,
        path_nm,
        img_nm,
        img_ao_tmp,
        img_hints_tmp,
        high_hints_mat,
    )
