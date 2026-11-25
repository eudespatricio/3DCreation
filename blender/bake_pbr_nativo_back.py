"""Projecao ortografica de vistas Gemini (frontal e traseira) sobre BaseColor de PBR nativo (TRELLIS.2)."""

from __future__ import annotations

import importlib
import os
import sys
from array import array

try:
    import bpy
except ImportError:  # pragma: no cover - permite import puro fora do Blender
    bpy = None  # type: ignore[assignment]

try:
    np = importlib.import_module("numpy")
except ImportError:  # pragma: no cover - fallback puro fora do Blender
    np = None  # type: ignore[assignment]

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


def _srgb_to_linear_val(c: float) -> float:
    c = 0.0 if c < 0.0 else (1.0 if c > 1.0 else c)
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _linear_to_srgb_val(c: float) -> float:
    c = 0.0 if c < 0.0 else (1.0 if c > 1.0 else c)
    return c * 12.92 if c <= 0.0031308 else 1.055 * (c ** (1.0 / 2.4)) - 0.055


def _srgb_to_linear_np(arr):
    c = np.clip(arr, 0.0, 1.0)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def _linear_to_srgb_np(arr):
    c = np.clip(arr, 0.0, 1.0)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * (c ** (1.0 / 2.4)) - 0.055)


def _montar_mat_rgb_vista(nome_mat: str, uv_tmp_nome: str, img_vista):
    mat, tex_alvo = _maps._criar_material_alvo_bake(nome_mat)
    nt = mat.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    if bsdf is not None:
        nt.nodes.remove(bsdf)
    out = nt.nodes.get("Material Output") or nt.nodes.new("ShaderNodeOutputMaterial")
    uv_node = nt.nodes.new("ShaderNodeUVMap")
    uv_node.uv_map = uv_tmp_nome
    tex_src = nt.nodes.new("ShaderNodeTexImage")
    tex_src.image = img_vista
    tex_src.extension = "EXTEND"
    nt.links.new(uv_node.outputs["UV"], tex_src.inputs["Vector"])
    emit = nt.nodes.new("ShaderNodeEmission")
    emit.inputs["Strength"].default_value = 1.0
    nt.links.new(tex_src.outputs["Color"], emit.inputs["Color"])
    nt.links.new(emit.outputs["Emission"], out.inputs["Surface"])
    return mat, tex_alvo


def _montar_mat_peso_vista(
    nome_mat: str, uv_tmp_nome: str, vis_attr: str | None, img_vista, tem_alpha: bool,
    direcao: tuple[float, float, float], min_dot: float, max_dot: float, alpha_min: float, alpha_max: float,
):
    mat, tex_alvo = _maps._criar_material_alvo_bake(nome_mat)
    nt = mat.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    if bsdf is not None:
        nt.nodes.remove(bsdf)
    out = nt.nodes.get("Material Output") or nt.nodes.new("ShaderNodeOutputMaterial")
    uv_node, fator_w = _sh._criar_nodos_fator_vista(
        nt, direcao, uv_tmp_nome, nome_visivel=vis_attr, min_dot=min_dot, max_dot=max_dot,
    )
    if tem_alpha:
        tex_src = nt.nodes.new("ShaderNodeTexImage")
        tex_src.image = img_vista
        tex_src.extension = "EXTEND"
        nt.links.new(uv_node.outputs["UV"], tex_src.inputs["Vector"])
        mr_a = nt.nodes.new("ShaderNodeMapRange")
        mr_a.clamp = True
        mr_a.inputs["From Min"].default_value, mr_a.inputs["From Max"].default_value = alpha_min, alpha_max
        mr_a.inputs["To Min"].default_value, mr_a.inputs["To Max"].default_value = 0.0, 1.0
        nt.links.new(tex_src.outputs["Alpha"], mr_a.inputs["Value"])
        mul_a = nt.nodes.new("ShaderNodeMath")
        mul_a.operation, mul_a.use_clamp = "MULTIPLY", True
        nt.links.new(fator_w, mul_a.inputs[0])
        nt.links.new(mr_a.outputs["Result"], mul_a.inputs[1])
        fator_w = mul_a.outputs["Value"]
    comb = nt.nodes.new("ShaderNodeCombineColor")
    comb.mode = "RGB"
    for idx_c in range(3):
        nt.links.new(fator_w, comb.inputs[idx_c])
    emit = nt.nodes.new("ShaderNodeEmission")
    emit.inputs["Strength"].default_value = 1.0
    nt.links.new(comb.outputs["Color"], emit.inputs["Color"])
    nt.links.new(emit.outputs["Emission"], out.inputs["Surface"])
    return mat, tex_alvo


def _executar_bake_emit_simples(cena, obj, mat, tex_alvo, img_alvo, px: int) -> None:
    tex_alvo.image, tex_alvo.select = img_alvo, True
    mat.node_tree.nodes.active = tex_alvo
    obj.data.materials.clear()
    obj.data.materials.append(mat)
    cena.render.bake.use_selected_to_active, cena.render.bake.use_clear = False, True
    cena.cycles.samples = 1
    cena.render.bake.margin = max(6, min(16, int(px) // 128))
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    _cfg._executar_bake_seguro(cena, type="EMIT")


def _ler_mascara_hints_valid(img_hints_valid, px: int):
    if img_hints_valid is None or not getattr(img_hints_valid, "size", None):
        return None
    hw, hh = int(img_hints_valid.size[0]), int(img_hints_valid.size[1])
    total_h = hw * hh * 4
    if hw <= 0 or hh <= 0 or len(getattr(img_hints_valid, "pixels", ())) != total_h:
        return None
    hbuf = array("f", [0.0]) * total_h
    img_hints_valid.pixels.foreach_get(hbuf)
    if np is not None:
        hb = np.frombuffer(hbuf, dtype=np.float32).reshape(hh, hw, 4)[:, :, 2]
        if (hw, hh) != (px, px):
            sy = (np.arange(px) * hh) // px
            sx = (np.arange(px) * hw) // px
            hb = hb[sy[:, None], sx[None, :]]
        return hb >= 0.5
    if (hw, hh) == (px, px):
        return [hbuf[i + 2] >= 0.5 for i in range(0, total_h, 4)]
    ys = [min(hh - 1, (y * hh) // px) for y in range(px)]
    xs = [min(hw - 1, (x * hw) // px) for x in range(px)]
    return [hbuf[(sy * hw + sx) * 4 + 2] >= 0.5 for sy in ys for sx in xs]


def _mesclar_vista_buffers(bc_buf, vw_buf, w_buf, px: int, peso_max: float, valid_hints) -> tuple[float, int]:
    total_f = px * px * 4
    if np is not None:
        bc_arr = np.frombuffer(bc_buf, dtype=np.float32).reshape(px, px, 4)
        vw_arr = np.frombuffer(vw_buf, dtype=np.float32).reshape(px, px, 4)
        w_arr = np.frombuffer(w_buf, dtype=np.float32).reshape(px, px, 4)[:, :, 0]

        bc_lin = _srgb_to_linear_np(bc_arr[:, :, :3])
        vw_lin = _srgb_to_linear_np(vw_arr[:, :, :3])
        lum_nat = 0.2126 * bc_lin[:, :, 0] + 0.7152 * bc_lin[:, :, 1] + 0.0722 * bc_lin[:, :, 2]
        lum_vw = 0.2126 * vw_lin[:, :, 0] + 0.7152 * vw_lin[:, :, 1] + 0.0722 * vw_lin[:, :, 2]
        gain_mask = (w_arr >= 0.55) & (lum_nat > 0.01)
        if valid_hints is not None:
            gain_mask &= valid_hints
        cnt_ov = int(np.count_nonzero(gain_mask))
        soma_vw = float(np.sum(lum_vw[gain_mask])) if cnt_ov >= 16 else 0.0
        gain = max(0.80, min(1.25, float(np.sum(lum_nat[gain_mask])) / soma_vw)) if (cnt_ov >= 16 and soma_vw > 1e-4) else 1.0

        blend_mask = w_arr > 0.01
        n_blend = int(np.count_nonzero(blend_mask))
        if n_blend > 0:
            w_eff = np.minimum(w_arr[blend_mask], peso_max)[:, None]
            vw_sc = np.clip(vw_lin[blend_mask] * gain, 0.0, 1.0)
            out_lin = np.clip(bc_lin[blend_mask] * (1.0 - w_eff) + vw_sc * w_eff, 0.0, 1.0)
            bc_arr[blend_mask, :3] = _linear_to_srgb_np(out_lin)
        return gain, n_blend

    soma_nat = soma_vw = 0.0
    cnt_ov = 0
    for p_idx, i in enumerate(range(0, total_f, 4)):
        if w_buf[i] < 0.55 or (valid_hints is not None and not valid_hints[p_idx]):
            continue
        r_l, g_l, b_l = _srgb_to_linear_val(bc_buf[i]), _srgb_to_linear_val(bc_buf[i + 1]), _srgb_to_linear_val(bc_buf[i + 2])
        lum_nat = 0.2126 * r_l + 0.7152 * g_l + 0.0722 * b_l
        if lum_nat <= 0.01:
            continue
        vr_l, vg_l, vb_l = _srgb_to_linear_val(vw_buf[i]), _srgb_to_linear_val(vw_buf[i + 1]), _srgb_to_linear_val(vw_buf[i + 2])
        soma_nat += lum_nat
        soma_vw += 0.2126 * vr_l + 0.7152 * vg_l + 0.0722 * vb_l
        cnt_ov += 1
    gain = max(0.80, min(1.25, soma_nat / soma_vw)) if (cnt_ov >= 16 and soma_vw > 1e-4) else 1.0

    n_blend = 0
    for i in range(0, total_f, 4):
        w = w_buf[i]
        if w <= 0.01:
            continue
        w_eff = peso_max if w > peso_max else w
        inv_w = 1.0 - w_eff
        for c_k in range(3):
            b_lin = _srgb_to_linear_val(bc_buf[i + c_k])
            v_lin = min(1.0, _srgb_to_linear_val(vw_buf[i + c_k]) * gain)
            bc_buf[i + c_k] = _linear_to_srgb_val(min(1.0, max(0.0, b_lin * inv_w + v_lin * w_eff)))
        n_blend += 1
    return gain, n_blend


def _aplicar_vista_ortografica_pbr_nativo(
    cena, obj, img_bc, path_bc: str, px: int, nome_base: str, caminho_vista: str, *,
    vista: str, direcao: tuple[float, float, float], min_dot: float, max_dot: float,
    alpha_min: float, alpha_max: float, peso_max: float, exigir_alpha: bool, chave_ok: str,
    img_hints_valid=None,
) -> dict:
    """Projeta ``caminho_vista`` ortograficamente sobre ``img_bc`` respeitando normal, BVH e alpha."""
    if not caminho_vista or not os.path.isfile(caminho_vista):
        return {chave_ok: False, "motivo": "arquivo_ausente"}
    if obj is None or getattr(obj, "data", None) is None or not obj.data.uv_layers:
        return {chave_ok: False, "motivo": "sem_uv"}
    if img_bc is None or not getattr(img_bc, "size", None):
        return {chave_ok: False, "motivo": "sem_img_bc"}

    # Captura nome da UV0 antes de qualquer alteracao em bmesh/mode_set (pitfall RNA).
    uv0_nome = str(obj.data.uv_layers[0].name)
    uv_tmp_nome, vis_tmp_nome = f"_UV_Cam_{vista.title()}_Tmp", f"_vis_{vista}_tmp"
    mats_ant = list(obj.data.materials)
    poly_mat_indices = [int(p.material_index) for p in obj.data.polygons]
    engine_ant = str(cena.render.engine)
    s2a_ant, clear_ant = bool(cena.render.bake.use_selected_to_active), bool(cena.render.bake.use_clear)
    samples_ant, margin_ant = int(cena.cycles.samples), int(cena.render.bake.margin)
    active_ant = bpy.context.view_layer.objects.active
    estado_cena = _cfg._capturar_estado_cena(cena)

    img_vista = img_vista_rgb = img_vista_w = None
    mat_rgb = tex_rgb = mat_w = tex_w = None
    try:
        img_vista = bpy.data.images.load(caminho_vista, check_existing=False)
        img_vista.colorspace_settings.name = "sRGB"
        sz_v = getattr(img_vista, "size", ())
        if len(sz_v) < 2 or int(sz_v[0]) <= 0 or int(sz_v[1]) <= 0:
            return {chave_ok: False, "motivo": "imagem_vazia"}

        tem_alpha = _proj._imagem_tem_alpha_valido(img_vista)
        if exigir_alpha and not tem_alpha:
            return {chave_ok: False, "motivo": "sem_alpha_cutout"}

        min_v, max_v = _cfg._calcular_bbox_mundo(obj)
        uv_bbox = _proj._detectar_bbox_uv_foreground(img_vista)
        _proj._projetar_uv_ortografica_bmesh(obj, vista, min_v, max_v, uv_bbox, uv_tmp_nome)
        vis_attr = _proj._calcular_oclusao_direcao_bmesh(obj, direcao, vis_tmp_nome)
        if uv0_nome in obj.data.uv_layers:
            obj.data.uv_layers.active = obj.data.uv_layers[uv0_nome]
            obj.data.uv_layers[uv0_nome].active_render = True
        if cena.render.engine != "CYCLES":
            _cfg._configurar_dispositivo_cycles(cena, preferir_gpu=True)

        mat_rgb, tex_rgb = _montar_mat_rgb_vista(f"{nome_base}_{vista}_rgb_mat_tmp", uv_tmp_nome, img_vista)
        img_vista_rgb = bpy.data.images.new(f"{nome_base}_{vista}_rgb_tmp", width=px, height=px, alpha=False)
        img_vista_rgb.colorspace_settings.name = "sRGB"
        _executar_bake_emit_simples(cena, obj, mat_rgb, tex_rgb, img_vista_rgb, px)

        mat_w, tex_w = _montar_mat_peso_vista(
            f"{nome_base}_{vista}_w_mat_tmp", uv_tmp_nome, vis_attr, img_vista, tem_alpha,
            direcao, min_dot, max_dot, alpha_min, alpha_max,
        )
        img_vista_w = bpy.data.images.new(f"{nome_base}_{vista}_w_tmp", width=px, height=px, alpha=False)
        img_vista_w.colorspace_settings.name = "Non-Color"
        _executar_bake_emit_simples(cena, obj, mat_w, tex_w, img_vista_w, px)

        total_f = px * px * 4
        if (
            len(getattr(img_bc, "pixels", ())) != total_f
            or len(getattr(img_vista_rgb, "pixels", ())) != total_f
            or len(getattr(img_vista_w, "pixels", ())) != total_f
        ):
            return {chave_ok: False, "motivo": "buffer_tamanho_invalido"}

        bc_buf = array("f", [0.0]) * total_f
        vw_buf = array("f", [0.0]) * total_f
        w_buf = array("f", [0.0]) * total_f
        img_bc.pixels.foreach_get(bc_buf)
        img_vista_rgb.pixels.foreach_get(vw_buf)
        img_vista_w.pixels.foreach_get(w_buf)

        valid_hints = _ler_mascara_hints_valid(img_hints_valid, px)
        gain, n_blend = _mesclar_vista_buffers(bc_buf, vw_buf, w_buf, px, peso_max, valid_hints)
        if n_blend > 0:
            img_bc.pixels.foreach_set(bc_buf)
            _cfg._configurar_render_png_linear(cena)
            cena.render.image_settings.compression = 90
            img_bc.save_render(filepath=path_bc, scene=cena)
            img_bc.filepath = path_bc
            img_bc.filepath_raw = path_bc
            if getattr(img_bc, "source", "FILE") != "FILE":
                img_bc.source = "FILE"
            img_bc.reload()
            img_bc.colorspace_settings.name = "sRGB"
        return {chave_ok: n_blend > 0, "pixels_mesclados": n_blend, "ganho_luminancia": round(gain, 4)}
    finally:
        for tex_t in (tex_rgb, tex_w):
            if tex_t is not None:
                tex_t.image = None
        obj.data.materials.clear()
        for m_ant in mats_ant:
            obj.data.materials.append(m_ant)
        for poly, idx_mat in zip(obj.data.polygons, poly_mat_indices):
            poly.material_index = idx_mat
        if uv_tmp_nome in obj.data.uv_layers:
            obj.data.uv_layers.remove(obj.data.uv_layers[uv_tmp_nome])
        if uv0_nome in obj.data.uv_layers:
            obj.data.uv_layers.active = obj.data.uv_layers[uv0_nome]
            obj.data.uv_layers[uv0_nome].active_render = True
        if vis_tmp_nome in obj.data.color_attributes:
            obj.data.color_attributes.remove(obj.data.color_attributes[vis_tmp_nome])
        for mat_t in (mat_rgb, mat_w):
            if mat_t is not None and mat_t.name in bpy.data.materials and mat_t.users == 0:
                bpy.data.materials.remove(mat_t)
        for im_t in (img_vista, img_vista_rgb, img_vista_w):
            if im_t is not None and im_t.name in bpy.data.images and im_t.users == 0:
                bpy.data.images.remove(im_t)
        cena.render.bake.use_selected_to_active = s2a_ant
        cena.render.bake.use_clear = clear_ant
        cena.cycles.samples = samples_ant
        cena.render.bake.margin = margin_ant
        cena.render.engine = engine_ant
        _cfg._restaurar_estado_cena(cena, estado_cena)
        bpy.context.view_layer.objects.active = active_ant


def aplicar_vista_traseira_pbr_nativo(
    cena, obj, img_bc, path_bc: str, px: int, nome_base: str, caminho_back: str,
    img_hints_valid=None,
) -> dict:
    """Projeta ``caminho_back`` (-Y) sobre ``img_bc`` respeitando normal, BVH e alpha cutout."""
    return _aplicar_vista_ortografica_pbr_nativo(
        cena, obj, img_bc, path_bc, px, nome_base, caminho_back, vista="back", direcao=(0.0, -1.0, 0.0),
        min_dot=0.45, max_dot=0.85, alpha_min=0.88, alpha_max=0.98, peso_max=0.92,
        exigir_alpha=False, chave_ok="vista_back_aplicada", img_hints_valid=img_hints_valid,
    )


def aplicar_vista_frontal_pbr_nativo(
    cena, obj, img_bc, path_bc: str, px: int, nome_base: str, caminho_front: str,
    img_hints_valid=None,
) -> dict:
    """Projeta ``caminho_front`` (+Y, com alpha cutout) sobre ``img_bc`` para nitidez facial/frontal."""
    return _aplicar_vista_ortografica_pbr_nativo(
        cena, obj, img_bc, path_bc, px, nome_base, caminho_front, vista="front", direcao=(0.0, 1.0, 0.0),
        min_dot=0.35, max_dot=0.78, alpha_min=0.92, alpha_max=0.99, peso_max=0.95,
        exigir_alpha=True, chave_ok="vista_front_aplicada", img_hints_valid=img_hints_valid,
    )
