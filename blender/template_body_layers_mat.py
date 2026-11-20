"""Selecao de pele CC0, materiais Principled PBR e empacotamento de atlas multicamadas."""

from __future__ import annotations

import math
import os
import sys
import tempfile

import bpy

if __package__:
    from . import template_body_assets as _assets
    from . import template_body_uv as _uv_mod
else:
    _BLENDER_DIR = os.path.dirname(os.path.abspath(__file__))
    if _BLENDER_DIR not in sys.path:
        sys.path.insert(0, _BLENDER_DIR)
    import template_body_assets as _assets
    import template_body_uv as _uv_mod

_hex_to_rgb_srgb = _assets._hex_to_rgb_srgb
_raizes_categoria_mpfb = _assets._raizes_categoria_mpfb
_rgba_srgb_to_linear = _assets._rgba_srgb_to_linear


def _selecionar_skin_cc0(macro: dict) -> str | None:
    """Seleciona textura difusa anatomica CC0 de skins/ compativel com macro (genero/idade/etnia)."""
    gender = float(macro.get("gender", 0.0))
    age = float(macro.get("age", 0.45))
    race = macro.get("race") if isinstance(macro.get("race"), dict) else {}
    af = float(race.get("african", 0.0))
    as_ = float(race.get("asian", 0.0))
    eh_fem = gender >= 0.5
    eh_meia_idade = age >= 0.62

    if af >= 0.55:
        if eh_meia_idade:
            prefs = (
                ("middleage_african_female", "young_african_female")
                if eh_fem
                else ("middleage_african_male", "young_african_male")
            )
        else:
            prefs = (
                ("young_african_female", "middleage_african_female")
                if eh_fem
                else ("young_african_male", "middleage_african_male")
            )
    elif as_ >= 0.55:
        if eh_meia_idade:
            prefs = (
                ("middleage_asian_female", "young_asian_female")
                if eh_fem
                else ("middleage_asian_male", "young_asian_male")
            )
        else:
            prefs = (
                ("young_asian_female", "middleage_asian_female")
                if eh_fem
                else ("young_asian_male", "middleage_asian_male")
            )
    else:
        if eh_meia_idade:
            prefs = (
                ("middleage_caucasian_female", "young_caucasian_female2", "young_caucasian_female")
                if eh_fem
                else ("middleage_caucasian_male", "young_caucasian_male2", "young_caucasian_male")
            )
        else:
            prefs = (
                ("young_caucasian_female2", "young_caucasian_female", "middleage_caucasian_female")
                if eh_fem
                else ("young_caucasian_male2", "young_caucasian_male", "middleage_caucasian_male")
            )

    raizes = _raizes_categoria_mpfb("skins")
    for nome_pasta in prefs:
        for raiz in raizes:
            pasta = os.path.join(raiz, nome_pasta)
            if not os.path.isdir(pasta):
                continue
            for arq in sorted(os.listdir(pasta)):
                low = arq.lower()
                if low.endswith(".png") and ("diffuse" in low or low == f"{nome_pasta}.png"):
                    return os.path.join(pasta, arq)
    return None


def _gerar_pele_procedural_limpa(saida: str, tam: int, macro: dict, png_nome: str = "baseColor.png") -> str:
    """Fallback de pele anatomica limpa (sem franja preta na testa) quando pacote CC0 nao esta no disco."""
    race = macro.get("race") if isinstance(macro.get("race"), dict) else {}
    af = float(race.get("african", 0.35))
    as_ = float(race.get("asian", 0.15))
    r_base = max(0.32, min(0.86, 0.78 - 0.34 * af - 0.04 * as_))
    g_base = max(0.22, min(0.72, 0.58 - 0.28 * af - 0.02 * as_))
    b_base = max(0.16, min(0.62, 0.46 - 0.24 * af - 0.04 * as_))

    img = bpy.data.images.new("skin_procedural", width=tam, height=tam, alpha=True)
    buf = [1.0] * (tam * tam * 4)
    for y in range(tam):
        v = y / float(max(1, tam - 1))
        for x in range(tam):
            u = x / float(max(1, tam - 1))
            var = 0.018 * math.sin(u * 18.0) * math.cos(v * 18.0)
            r = max(0.15, min(0.95, r_base + var))
            g = max(0.12, min(0.88, g_base + var * 0.8))
            b = max(0.10, min(0.82, b_base + var * 0.6))
            # Leve rubor facial/labial suave sem escurecer testa
            if 0.38 <= u <= 0.62 and 0.66 <= v <= 0.76:
                r = min(0.95, r + 0.04)
                g = max(0.10, g - 0.01)
            idx = (y * tam + x) * 4
            buf[idx] = r
            buf[idx + 1] = g
            buf[idx + 2] = b
            buf[idx + 3] = 1.0
    img.pixels.foreach_set(buf)
    sc = bpy.context.scene
    ant_mode = sc.render.image_settings.color_mode
    sc.render.image_settings.color_mode = "RGBA"
    caminho = os.path.join(saida, png_nome)
    img.filepath_raw = caminho
    img.file_format = "PNG"
    img.save()
    sc.render.image_settings.color_mode = ant_mode
    img.pack()
    return caminho


def _criar_material_pbr(
    nome: str,
    cor_srgb: tuple[float, float, float],
    roughness: float = 0.62,
    metallic: float = 0.0,
    specular: float = 0.32,
    tex_path: str | None = None,
    tint_strength: float = 0.0,
    uv_scale: float = 1.0,
):
    """Cria material Principled BSDF com textura opcional (empacotada para glTF) e fallback limpo."""
    mat = bpy.data.materials.new(nome)
    mat.use_nodes = True
    mat.use_backface_culling = False
    nt = mat.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    if bsdf is None:
        bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Base Color"].default_value = _rgba_srgb_to_linear(cor_srgb)
    if "Roughness" in bsdf.inputs:
        bsdf.inputs["Roughness"].default_value = float(roughness)
    if "Metallic" in bsdf.inputs:
        bsdf.inputs["Metallic"].default_value = float(metallic)
    if "Specular IOR Level" in bsdf.inputs:
        bsdf.inputs["Specular IOR Level"].default_value = float(specular)

    if tex_path and os.path.isfile(tex_path):
        img = bpy.data.images.load(tex_path, check_existing=True)
        if tint_strength > 0.01:
            src_work = img.copy()
            if int(src_work.size[0]) > 512 or int(src_work.size[1]) > 512:
                src_work.scale(min(int(src_work.size[0]), 512), min(int(src_work.size[1]), 512))
            w_im, h_im = int(src_work.size[0]), int(src_work.size[1])
            px = list(src_work.pixels)
            bpy.data.images.remove(src_work)
            n_px = max(1, len(px) // 4)
            avg_lum = max(
                0.05,
                sum(0.2126 * px[i] + 0.7152 * px[i + 1] + 0.0722 * px[i + 2] for i in range(0, len(px), 4))
                / float(n_px),
            )
            tr, tg, tb = cor_srgb
            s = float(tint_strength)
            for k in range(0, len(px), 4):
                lum = 0.2126 * px[k] + 0.7152 * px[k + 1] + 0.0722 * px[k + 2]
                rel = max(0.35, min(1.55, lum / avg_lum))
                cr = min(1.0, tr * (0.28 + 0.72 * rel))
                cg = min(1.0, tg * (0.28 + 0.72 * rel))
                cb = min(1.0, tb * (0.28 + 0.72 * rel))
                px[k] = max(0.0, min(1.0, px[k] * (1.0 - s) + cr * s))
                px[k + 1] = max(0.0, min(1.0, px[k + 1] * (1.0 - s) + cg * s))
                px[k + 2] = max(0.0, min(1.0, px[k + 2] * (1.0 - s) + cb * s))
                px[k + 3] = 1.0
            novo_im = bpy.data.images.new(name=f"_tmp_{nome}_tex", width=w_im, height=h_im, alpha=True)
            novo_im.pixels.foreach_set(px)

            fd_t, tmp_png = tempfile.mkstemp(prefix="f3d_body_tint_", suffix=".png")
            os.close(fd_t)
            try:
                sc = bpy.context.scene
                ant_cm = sc.render.image_settings.color_mode
                sc.render.image_settings.color_mode = "RGBA"
                novo_im.filepath_raw = tmp_png
                novo_im.file_format = "PNG"
                novo_im.save()
                sc.render.image_settings.color_mode = ant_cm
                bpy.data.images.remove(novo_im)
                carregada = bpy.data.images.load(tmp_png)
                carregada.name = f"{nome}_tex"
                try:
                    carregada.colorspace_settings.name = "sRGB"
                except (TypeError, ValueError, AttributeError, RuntimeError) as exc:
                    print(f"[template_body] colorspace sRGB indisponivel ({nome}): {exc}", file=sys.stderr)
                carregada.pack()
                img = carregada
            finally:
                if os.path.exists(tmp_png):
                    os.unlink(tmp_png)
        else:
            try:
                img.pack()
            except RuntimeError as exc:
                print(f"[template_body] img.pack() ignorado ({nome}): {exc}", file=sys.stderr)
        tex_node = nt.nodes.new("ShaderNodeTexImage")
        tex_node.image = img
        if abs(float(uv_scale) - 1.0) > 1e-4:
            tc_node = nt.nodes.new("ShaderNodeTexCoord")
            mp_node = nt.nodes.new("ShaderNodeMapping")
            sc_v = float(uv_scale)
            mp_node.inputs["Scale"].default_value = (sc_v, sc_v, sc_v)
            nt.links.new(tc_node.outputs["UV"], mp_node.inputs["Vector"])
            nt.links.new(mp_node.outputs["Vector"], tex_node.inputs["Vector"])
        nt.links.new(tex_node.outputs["Color"], bsdf.inputs["Base Color"])
    return mat


def _unificar_atlas_multicamadas(obj, saida: str, tex_px: int) -> str:
    """Re-desdobra malha unificada em UV uniforme e assa baseColor.png (e alpha) via Cycles EMIT."""
    caminho = os.path.join(saida, "baseColor.png")
    mats = list(obj.data.materials)
    if not mats or len(obj.data.polygons) == 0:
        return caminho
    if not obj.data.uv_layers:
        obj.data.uv_layers.new(name="UVMap")
    uv_orig_name = (obj.data.uv_layers.active or obj.data.uv_layers[0]).name
    if "UVMap_atlas" in obj.data.uv_layers:
        obj.data.uv_layers.remove(obj.data.uv_layers["UVMap_atlas"])
    uv_atlas = obj.data.uv_layers.new(name="UVMap_atlas")
    obj.data.uv_layers.active = uv_atlas
    _uv_mod._smart_project_subset(
        obj, mat_indices=None, uv_name=uv_atlas.name, grupo_unico=True, max_density_ratio=500.0
    )

    any_clip = any(
        m is not None
        and (
            getattr(m, "blend_method", "OPAQUE") == "CLIP"
            or (
                m.use_nodes
                and any(
                    n.type == "BSDF_PRINCIPLED" and "Alpha" in n.inputs and n.inputs["Alpha"].is_linked
                    for n in m.node_tree.nodes
                )
            )
        )
        for m in mats
    )

    sc = bpy.context.scene
    ant = (
        sc.render.engine,
        sc.cycles.samples,
        sc.cycles.device,
        sc.render.bake.margin,
        sc.render.image_settings.color_mode,
        mats,
        [int(p.material_index) for p in obj.data.polygons],
        bool(obj.hide_render),
    )
    img_rgb = bpy.data.images.new("_f3d_atlas_rgb", width=tex_px, height=tex_px, alpha=True)
    img_a = None
    bake_entries = [_uv_mod._preparar_mat_bake_emissao(m, i, uv_orig_name, img_rgb) for i, m in enumerate(mats)]
    bake_ok = False
    try:
        obj.hide_render = False
        obj.data.materials.clear()
        for bm_mat, _em, _dst, _bsdf in bake_entries:
            obj.data.materials.append(bm_mat)
        for lyr in obj.data.uv_layers:
            lyr.active_render = lyr.name == uv_atlas.name
        obj.data.uv_layers.active = uv_atlas
        sc.render.engine, sc.cycles.samples, sc.cycles.device = "CYCLES", 1, "CPU"
        sc.render.bake.margin = max(2, min(4, tex_px // 256))
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.bake(type="EMIT")

        if any_clip:
            img_a = bpy.data.images.new("_f3d_atlas_a", width=tex_px, height=tex_px, alpha=False)
            for bm_mat, em_n, dst_n, bsdf in bake_entries:
                nt = bm_mat.node_tree
                for lk in list(em_n.inputs["Color"].links):
                    nt.links.remove(lk)
                if bsdf is not None and "Alpha" in bsdf.inputs and bsdf.inputs["Alpha"].is_linked:
                    nt.links.new(bsdf.inputs["Alpha"].links[0].from_socket, em_n.inputs["Color"])
                elif bsdf is not None and "Alpha" in bsdf.inputs:
                    av = float(bsdf.inputs["Alpha"].default_value)
                    em_n.inputs["Color"].default_value = (av, av, av, 1.0)
                else:
                    em_n.inputs["Color"].default_value = (1.0, 1.0, 1.0, 1.0)
                dst_n.image = img_a
            bpy.ops.object.bake(type="EMIT")
            px_rgb, px_a = list(img_rgb.pixels), list(img_a.pixels)
            for k in range(0, len(px_rgb), 4):
                px_rgb[k + 3] = max(0.0, min(1.0, px_a[k]))
            img_rgb.pixels.foreach_set(px_rgb)

        sc.render.image_settings.color_mode = "RGBA"
        img_rgb.filepath_raw, img_rgb.file_format = caminho, "PNG"
        img_rgb.save()
        bake_ok = True
    finally:
        obj.hide_render = ant[7]
        obj.data.materials.clear()
        for m in ant[5]:
            obj.data.materials.append(m)
        for p, mi in zip(obj.data.polygons, ant[6]):
            p.material_index = mi
        sc.render.engine, sc.cycles.samples, sc.cycles.device, sc.render.bake.margin, sc.render.image_settings.color_mode = ant[:5]
        for bm_mat, _em, _dst, _bsdf in bake_entries:
            bpy.data.materials.remove(bm_mat)
        bpy.data.images.remove(img_rgb)
        if img_a is not None:
            bpy.data.images.remove(img_a)

    if not bake_ok:
        raise RuntimeError("falha ao assar atlas multicamadas")
    if uv_orig_name in obj.data.uv_layers:
        obj.data.uv_layers.remove(obj.data.uv_layers[uv_orig_name])
    uv_atlas.name, obj.data.uv_layers.active, uv_atlas.active_render = uv_orig_name, uv_atlas, True

    mat_unif = _criar_material_pbr("skin", (0.78, 0.58, 0.46), roughness=0.62, specular=0.32, tex_path=None)
    img_atlas = bpy.data.images.load(caminho, check_existing=False)
    img_atlas.name = "atlas_multicamadas"
    try:
        img_atlas.colorspace_settings.name = "sRGB"
    except (TypeError, ValueError, AttributeError, RuntimeError) as exc:
        print(f"[template_body] colorspace sRGB indisponivel (atlas): {exc}", file=sys.stderr)
    img_atlas.pack()
    nt_u = mat_unif.node_tree
    bsdf_u, tex_u = nt_u.nodes.get("Principled BSDF"), nt_u.nodes.new("ShaderNodeTexImage")
    tex_u.image = img_atlas
    if bsdf_u is not None:
        nt_u.links.new(tex_u.outputs["Color"], bsdf_u.inputs["Base Color"])
    if any_clip and bsdf_u is not None and "Alpha" in bsdf_u.inputs:
        mat_unif.blend_method = "CLIP"
        if hasattr(mat_unif, "surface_render_method"):
            mat_unif.surface_render_method = "DITHERED"
        if hasattr(mat_unif, "alpha_threshold"):
            mat_unif.alpha_threshold = 0.45
        cut_u = nt_u.nodes.new("ShaderNodeMath")
        cut_u.operation, cut_u.inputs[1].default_value = "GREATER_THAN", 0.45
        nt_u.links.new(tex_u.outputs["Alpha"], cut_u.inputs[0])
        nt_u.links.new(cut_u.outputs["Value"], bsdf_u.inputs["Alpha"])

    obj.data.materials.clear()
    obj.data.materials.append(mat_unif)
    for poly in obj.data.polygons:
        poly.material_index = 0
    return caminho


def _preparar_materiais_camadas(macro_ef: dict, job_ef: dict, saida: str, tam: int, eyes_obj) -> dict:
    """Prepara baseColor de pele CC0 e materiais Principled BSDF para todas as camadas 3D."""
    skin_src = _selecionar_skin_cc0(macro_ef)
    tex_base_path = os.path.join(saida, "baseColor.png")
    if skin_src and os.path.isfile(skin_src):
        img_skin = bpy.data.images.load(skin_src, check_existing=True).copy()
        img_skin.name = "cc0_skin_baseColor"
        if int(img_skin.size[0]) != tam or int(img_skin.size[1]) != tam:
            img_skin.scale(tam, tam)
        sc = bpy.context.scene
        ant_mode = sc.render.image_settings.color_mode
        sc.render.image_settings.color_mode = "RGBA"
        img_skin.filepath_raw = tex_base_path
        img_skin.file_format = "PNG"
        img_skin.save()
        sc.render.image_settings.color_mode = ant_mode
        img_skin.pack()
        skin_origem = os.path.basename(os.path.dirname(skin_src))
    else:
        tex_base_path = _gerar_pele_procedural_limpa(saida, tam, macro_ef, png_nome="baseColor.png")
        skin_origem = "procedural_anatomica"

    dir_pbr = os.path.join(os.path.dirname(os.path.abspath(__file__)), "textures_pbr")
    tex_tunic = os.path.join(dir_pbr, "linen_tunic_albedo.png")
    tex_leather = os.path.join(dir_pbr, "leather_saddle_albedo.png")
    tex_metal = os.path.join(dir_pbr, "bronze_filigree_albedo.png")

    cor_tunica = _hex_to_rgb_srgb(str(job_ef.get("cor") or "")) or (
        _hex_to_rgb_srgb("#23334A") or (0.137, 0.200, 0.290)
    )
    cor_calca = _hex_to_rgb_srgb("#24211F") or (0.141, 0.129, 0.122)

    mat_skin = _criar_material_pbr(
        "skin", (0.78, 0.58, 0.46), roughness=0.62, metallic=0.0, specular=0.32, tex_path=tex_base_path
    )
    mat_tunic = _criar_material_pbr(
        "tunic",
        cor_tunica,
        roughness=0.78,
        metallic=0.0,
        specular=0.20,
        tex_path=tex_tunic if os.path.isfile(tex_tunic) else None,
        tint_strength=0.78,
        uv_scale=3.8,
    )
    mat_trousers = _criar_material_pbr(
        "trousers",
        cor_calca,
        roughness=0.85,
        metallic=0.0,
        specular=0.14,
        tex_path=tex_tunic if os.path.isfile(tex_tunic) else None,
        tint_strength=0.88,
        uv_scale=3.8,
    )
    mat_leather = _criar_material_pbr(
        "leather",
        (0.36, 0.21, 0.11),
        roughness=0.58,
        metallic=0.04,
        specular=0.28,
        tex_path=tex_leather if os.path.isfile(tex_leather) else None,
        tint_strength=0.35,
        uv_scale=2.4,
    )
    mat_metal = _criar_material_pbr(
        "metal",
        (0.78, 0.61, 0.28),
        roughness=0.28,
        metallic=0.88,
        specular=0.50,
        tex_path=tex_metal if os.path.isfile(tex_metal) else None,
        tint_strength=0.20,
    )

    tex_eyes = None
    if eyes_obj is not None:
        for m in eyes_obj.data.materials:
            if m and m.use_nodes:
                for n in m.node_tree.nodes:
                    if n.type == "TEX_IMAGE" and n.image is not None and n.image.filepath:
                        cand_e = bpy.path.abspath(n.image.filepath)
                        if os.path.isfile(cand_e):
                            tex_eyes = cand_e
                            break
    if not tex_eyes:
        for r_eye in _raizes_categoria_mpfb("eyes"):
            cand_b = os.path.join(r_eye, "materials", "brown_eye.png")
            if os.path.isfile(cand_b):
                tex_eyes = cand_b
                break
    mat_eyes = _criar_material_pbr(
        "eyes", (0.35, 0.52, 0.68), roughness=0.12, metallic=0.0, specular=0.55, tex_path=tex_eyes
    )
    return {
        "tex_base_path": tex_base_path,
        "skin_origem": skin_origem,
        "mat_skin": mat_skin,
        "mat_tunic": mat_tunic,
        "mat_trousers": mat_trousers,
        "mat_leather": mat_leather,
        "mat_metal": mat_metal,
        "mat_eyes": mat_eyes,
    }
