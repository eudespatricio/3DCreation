"""Projecao e bake de textura Emissive embutida no GLB (sem poluir manifest@7)."""

from __future__ import annotations

import importlib
import os
import sys
import warnings
from array import array

try:
    import bpy
except ImportError:  # pragma: no cover - permite import puro em testes fora do Blender
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


def _resolver_emissive_hint_alias(
    emissive_hint: str | None, emissive_hint_png: str | None = None
) -> str | None:
    """Valida e normaliza ``emissive_hint`` vs alias legado ``emissive_hint_png``."""
    h1 = str(emissive_hint).strip() if emissive_hint is not None else ""
    h2 = str(emissive_hint_png).strip() if emissive_hint_png is not None else ""
    if h1 and h2:
        if h1 != h2:
            raise ValueError(f"emissive_hint ({h1!r}) e emissive_hint_png ({h2!r}) conflitantes")
        return h1
    if h1:
        return h1
    if h2:
        warnings.warn("emissive_hint_png esta obsoleto; use emissive_hint", DeprecationWarning, stacklevel=3)
        return h2
    return None


def tem_pixels_emissivos_ativos(img_em_hint, img_origem=None, limiar_frac: float = 0.0005) -> bool:
    """Retorna True se ``img_em_hint`` tiver fracao de pixels ativos ``> limiar_frac`` do foreground."""
    if img_em_hint is None or not getattr(img_em_hint, "size", None):
        return False
    w, h = int(img_em_hint.size[0]), int(img_em_hint.size[1])
    total_f = w * h * 4
    if w <= 0 or h <= 0:
        return False
    try:
        if len(getattr(img_em_hint, "pixels", ())) != total_f:
            return False
        em_buf = array("f", [0.0]) * total_f
        img_em_hint.pixels.foreach_get(em_buf)
    except (RuntimeError, ValueError, TypeError) as exc:
        sys.stderr.write(f"[bake_pbr_emissive] aviso ao ler emissive_hint: {exc}\n")
        return False

    if np is not None:
        em_arr = np.frombuffer(em_buf, dtype=np.float32).reshape(h, w, 4)
        ativos = int(np.count_nonzero(em_arr[:, :, 0] > 0.25))
    else:
        ativos = sum(1 for i in range(0, total_f, 4) if em_buf[i] > 0.25)
    if ativos <= 0:
        return False

    fg_total = w * h
    if img_origem is not None and tuple(getattr(img_origem, "size", (0, 0))) == (w, h):
        if len(getattr(img_origem, "pixels", ())) == total_f:
            obuf = array("f", [0.0]) * total_f
            img_origem.pixels.foreach_get(obuf)
            if np is not None:
                oa = np.frombuffer(obuf, dtype=np.float32).reshape(h, w, 4)[:, :, 3]
                if float(np.min(oa)) < 0.98:
                    fg_total = max(1, int(np.count_nonzero(oa >= 0.10)))
            elif min(obuf[3::4]) < 0.98:
                fg_total = max(1, sum(1 for a in obuf[3::4] if a >= 0.10))
    return (ativos / float(max(1, fg_total))) > limiar_frac


def _criar_nodos_fator_bilateral_y(nt, nome_uv: str):
    geom = nt.nodes.new("ShaderNodeNewGeometry")
    dot = nt.nodes.new("ShaderNodeVectorMath")
    dot.operation = "DOT_PRODUCT"
    dot.inputs[1].default_value = (0.0, 1.0, 0.0)
    nt.links.new(geom.outputs["Normal"], dot.inputs[0])

    abs_n = nt.nodes.new("ShaderNodeMath")
    abs_n.operation = "ABSOLUTE"
    nt.links.new(dot.outputs["Value"], abs_n.inputs[0])

    mr = nt.nodes.new("ShaderNodeMapRange")
    mr.clamp = True
    mr.inputs["From Min"].default_value, mr.inputs["From Max"].default_value = 0.02, 0.26
    mr.inputs["To Min"].default_value, mr.inputs["To Max"].default_value = 0.0, 1.0
    nt.links.new(abs_n.outputs["Value"], mr.inputs["Value"])

    uv_node = nt.nodes.new("ShaderNodeUVMap")
    uv_node.uv_map = nome_uv
    return uv_node, mr.outputs["Result"]


def _processar_emissive_e_bc_buffers(
    em_buf: array, bc_buf: array | None, px_sub: int, bw: int, bh: int, tem_origem: bool
) -> None:
    if np is not None:
        em_arr = np.frombuffer(em_buf, dtype=np.float32).reshape(px_sub, px_sub, 4)
        rgb = em_arr[:, :, :3].copy()
        pico = np.max(rgb, axis=2)
        ativo = pico > 0.02
        if not tem_origem:
            if bc_buf is not None and bw > 0 and bh > 0:
                bc_arr = np.frombuffer(bc_buf, dtype=np.float32).reshape(bh, bw, 4)
                by = np.minimum(bh - 1, (np.arange(px_sub) * bh) // px_sub)
                bx = np.minimum(bw - 1, (np.arange(px_sub) * bw) // px_sub)
                b_samp = bc_arr[by[:, None], bx[None, :], :3]
                bm_c = np.max(b_samp, axis=2)
                use_bc = ativo & (bm_c > 0.05)
                fb_cor = np.stack([pico, 0.72 * pico, 0.25 * pico], axis=2)
                rgb_cor = b_samp * (pico[:, :, None] / np.maximum(bm_c[:, :, None], 1e-6))
                rgb = np.where(ativo[:, :, None], np.where(use_bc[:, :, None], rgb_cor, fb_cor), rgb)
            else:
                fb_cor = np.stack([pico, 0.72 * pico, 0.25 * pico], axis=2)
                rgb = np.where(ativo[:, :, None], fb_cor, rgb)
        g_em = np.minimum(1.45, 1.0 / np.maximum(pico, 0.35))[:, :, None]
        em_arr[:, :, :3] = np.where(ativo[:, :, None], np.minimum(1.0, rgb * g_em), 0.0)
        em_arr[:, :, 3] = 1.0

        if bc_buf is not None and bw > 0 and bh > 0:
            bc_arr = np.frombuffer(bc_buf, dtype=np.float32).reshape(bh, bw, 4)
            ey = np.minimum(px_sub - 1, (np.arange(bh) * px_sub) // bh)
            ex = np.minimum(px_sub - 1, (np.arange(bw) * px_sub) // bw)
            em_up = em_arr[ey[:, None], ex[None, :], :3]
            up_at = np.max(em_up, axis=2) > 0.02
            bc_arr[:, :, :3] = np.where(
                up_at[:, :, None],
                np.minimum(1.0, np.maximum(bc_arr[:, :, :3] + 0.65 * em_up, 0.88 * em_up)),
                bc_arr[:, :, :3],
            )
        return

    for y in range(px_sub):
        by = min(bh - 1, (y * bh) // px_sub) if bh > 0 else 0
        for x in range(px_sub):
            ei = (y * px_sub + x) * 4
            er, eg, eb = em_buf[ei], em_buf[ei + 1], em_buf[ei + 2]
            pico = max(er, eg, eb)
            if pico <= 0.02:
                em_buf[ei], em_buf[ei + 1], em_buf[ei + 2], em_buf[ei + 3] = 0.0, 0.0, 0.0, 1.0
                continue
            if not tem_origem:
                if bc_buf is not None and bw > 0 and bh > 0:
                    bi = (by * bw + min(bw - 1, (x * bw) // px_sub)) * 4
                    br, bg_c, bb = bc_buf[bi], bc_buf[bi + 1], bc_buf[bi + 2]
                    bm_c = max(br, bg_c, bb)
                    er, eg, eb = ((br / bm_c) * pico, (bg_c / bm_c) * pico, (bb / bm_c) * pico) if bm_c > 0.05 else (pico, 0.72 * pico, 0.25 * pico)
                else:
                    er, eg, eb = pico, 0.72 * pico, 0.25 * pico
            g_em = min(1.45, 1.0 / max(pico, 0.35))
            em_buf[ei], em_buf[ei + 1], em_buf[ei + 2], em_buf[ei + 3] = min(1.0, er * g_em), min(1.0, eg * g_em), min(1.0, eb * g_em), 1.0

    if bc_buf is not None and bw > 0 and bh > 0:
        for by in range(bh):
            ey = min(px_sub - 1, (by * px_sub) // bh)
            for bx in range(bw):
                bi, ei = (by * bw + bx) * 4, (ey * px_sub + min(px_sub - 1, (bx * px_sub) // bw)) * 4
                if max(em_buf[ei], em_buf[ei + 1], em_buf[ei + 2]) > 0.02:
                    for c_k in range(3):
                        bc_buf[bi + c_k] = min(1.0, max(bc_buf[bi + c_k] + 0.65 * em_buf[ei + c_k], 0.88 * em_buf[ei + c_k]))


def assar_e_aplicar_emissive_uv0(
    cena, obj, saida_dir: str, nome_base: str, px: int, px_sub: int,
    img_em_hint, img_origem, img_bc, path_bc: str | None = None,
    *, bilateral: bool = False,
):
    """Assa emissive em UV0, realca ``_baseColor.png`` e empacota textura emissive apenas em memoria."""
    if not tem_pixels_emissivos_ativos(img_em_hint, img_origem) or obj is None or not obj.data.uv_layers:
        return None, img_bc, False

    uv0_nome = str(obj.data.uv_layers[0].name)
    uv_tmp_nome, vis_tmp_nome = "_UV_Cam_Em_Tmp", "_vis_em_tmp"
    mats_ant = list(obj.data.materials)
    poly_mat_indices = [int(p.material_index) for p in obj.data.polygons]
    engine_ant = str(cena.render.engine)
    s2a_ant, samples_ant, margin_ant = (
        bool(cena.render.bake.use_selected_to_active), int(cena.cycles.samples), int(cena.render.bake.margin)
    )
    estado_cena = _cfg._capturar_estado_cena(cena)
    mat_em = tex_em = img_em_raw = None
    tmp_pack_path = os.path.join(saida_dir, f".{nome_base}_emissive_pack_tmp.png")
    try:
        if cena.render.engine != "CYCLES":
            _cfg._configurar_dispositivo_cycles(cena, preferir_gpu=True)
        min_v, max_v = _cfg._calcular_bbox_mundo(obj)
        uv_bbox = _proj._detectar_bbox_uv_foreground(img_origem or img_em_hint)
        _proj._projetar_uv_frontal_bmesh(obj, min_v, max_v, uv_bbox, uv_tmp_nome)
        vis_attr = None if bilateral else _proj._calcular_oclusao_direcao_bmesh(obj, (0.0, 1.0, 0.0), vis_tmp_nome)
        obj.data.uv_layers.active = obj.data.uv_layers[uv0_nome]
        obj.data.uv_layers[uv0_nome].active_render = True

        mat_em, tex_em = _maps._criar_material_alvo_bake(f"{nome_base}_em_bake_tmp")
        nt = mat_em.node_tree
        bsdf = nt.nodes.get("Principled BSDF")
        if bsdf is not None:
            nt.nodes.remove(bsdf)
        out = nt.nodes.get("Material Output")
        if bilateral:
            uv_node, fator_frente = _criar_nodos_fator_bilateral_y(nt, uv_tmp_nome)
        else:
            uv_node, fator_frente = _sh._criar_nodos_fator_vista(nt, (0.0, 1.0, 0.0), uv_tmp_nome, nome_visivel=vis_attr)
        tx_mask = nt.nodes.new("ShaderNodeTexImage")
        tx_mask.image = img_em_hint
        tx_mask.extension = "EXTEND"
        nt.links.new(uv_node.outputs["UV"], tx_mask.inputs["Vector"])
        mul_m = nt.nodes.new("ShaderNodeMath")
        mul_m.operation, mul_m.use_clamp = "MULTIPLY", True
        nt.links.new(fator_frente, mul_m.inputs[0])
        nt.links.new(tx_mask.outputs["Color"], mul_m.inputs[1])

        emit = nt.nodes.new("ShaderNodeEmission")
        emit.inputs["Strength"].default_value = 1.0
        if img_origem is not None:
            tx_cor = nt.nodes.new("ShaderNodeTexImage")
            tx_cor.image = img_origem
            tx_cor.extension = "EXTEND"
            nt.links.new(uv_node.outputs["UV"], tx_cor.inputs["Vector"])
            mul_a = nt.nodes.new("ShaderNodeMath")
            mul_a.operation, mul_a.use_clamp = "MULTIPLY", True
            nt.links.new(mul_m.outputs["Value"], mul_a.inputs[0])
            nt.links.new(tx_cor.outputs["Alpha"], mul_a.inputs[1])
            vmul = nt.nodes.new("ShaderNodeVectorMath")
            vmul.operation = "SCALE"
            nt.links.new(tx_cor.outputs["Color"], vmul.inputs[0])
            nt.links.new(mul_a.outputs["Value"], vmul.inputs["Scale"])
            nt.links.new(vmul.outputs["Vector"], emit.inputs["Color"])
        else:
            nt.links.new(mul_m.outputs["Value"], emit.inputs["Color"])
        nt.links.new(emit.outputs["Emission"], out.inputs["Surface"])

        img_em_raw = bpy.data.images.new(f"{nome_base}_em_raw_tmp", width=px_sub, height=px_sub, alpha=False)
        img_em_raw.colorspace_settings.name = "sRGB"
        tex_em.image, tex_em.select, nt.nodes.active = img_em_raw, True, tex_em
        obj.data.materials.clear()
        obj.data.materials.append(mat_em)
        cena.render.bake.use_selected_to_active = False
        cena.cycles.samples = 1
        cena.render.bake.margin = max(4, min(16, int(px_sub) // 128))
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        _cfg._executar_bake_seguro(cena, type="EMIT")
    finally:
        if tex_em is not None:
            tex_em.image = None
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
        if mat_em is not None and mat_em.name in bpy.data.materials and mat_em.users == 0:
            bpy.data.materials.remove(mat_em)
        cena.render.bake.use_selected_to_active, cena.cycles.samples, cena.render.bake.margin = s2a_ant, samples_ant, margin_ant
        cena.render.engine = engine_ant

    em_buf = array("f", [0.0]) * (px_sub * px_sub * 4)
    img_em_raw.pixels.foreach_get(em_buf)
    bw, bh = (int(img_bc.size[0]), int(img_bc.size[1])) if (img_bc is not None and getattr(img_bc, "size", None)) else (0, 0)
    bc_buf = None
    if img_bc is not None and bw > 0 and bh > 0 and len(getattr(img_bc, "pixels", ())) == bw * bh * 4:
        bc_buf = array("f", [0.0]) * (bw * bh * 4)
        img_bc.pixels.foreach_get(bc_buf)
    _processar_emissive_e_bc_buffers(em_buf, bc_buf, px_sub, bw, bh, img_origem is not None)

    img_bc_nova = img_bc
    try:
        _cfg._configurar_render_png_linear(cena)
        cena.render.image_settings.compression = 90
        if bc_buf is not None and img_bc is not None:
            img_bc.pixels.foreach_set(bc_buf)
            if path_bc:
                img_bc_nova = _maps._salvar_e_recarregar_png(img_bc, path_bc, "sRGB", cena)
            else:
                img_bc.pack()
        img_em_raw.pixels.foreach_set(em_buf)
        img_em_raw.save_render(filepath=tmp_pack_path, scene=cena)
        bpy.data.images.remove(img_em_raw)
        img_em_raw = None
        img_em_final = bpy.data.images.load(tmp_pack_path, check_existing=False)
        img_em_final.name = f"{nome_base}_emissive"
        img_em_final.colorspace_settings.name = "sRGB"
        img_em_final.pack()
        img_em_final.filepath, img_em_final.filepath_raw = "", ""
    finally:
        _cfg._restaurar_estado_cena(cena, estado_cena)
        if os.path.isfile(tmp_pack_path):
            os.remove(tmp_pack_path)
    return img_em_final, img_bc_nova, True
