"""Dilatacao completa de fundo (anti-bleed #000000) e trava dielectrica (metallic=0) no rosto/pele."""

from __future__ import annotations

import colorsys
import importlib
import os
import sys
from typing import Any

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
    from . import bake_pbr_heal as _heal
    from . import bake_pbr_maps as _maps
else:
    _BLENDER_DIR = os.path.dirname(os.path.abspath(__file__))
    if _BLENDER_DIR not in sys.path:
        sys.path.insert(0, _BLENDER_DIR)
    import bake_pbr_config as _cfg
    import bake_pbr_heal as _heal
    import bake_pbr_maps as _maps


def _linear_para_srgb_np(arr):
    c = np.clip(arr, 0.0, 1.0)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * (np.maximum(c, 1e-12) ** (1.0 / 2.4)) - 0.055)


def _linear_para_srgb_val(v: float) -> float:
    c = 0.0 if v < 0.0 else (1.0 if v > 1.0 else float(v))
    return c * 12.92 if c <= 0.0031308 else 1.055 * (c ** (1.0 / 2.4)) - 0.055


def dilatar_fundo_rgba_buf(
    buf, valid_mask_bool, w: int, h: int, *, iters_suaves: int = 16
) -> tuple[Any, int]:
    """Preenche todo texel fora das ilhas UV (~valid) com cor vizinha (media suave + JFA Voronoi)."""
    if w <= 0 or h <= 0:
        return buf, 0
    total_px = w * h
    if np is None:
        v_bool = [bool(v) for v in valid_mask_bool]
        if not any(v_bool) or all(v_bool):
            return buf, 0
        return _heal.propagar_texels_validos_buf(
            buf, v_bool, [True] * total_px, w, h, canais=4, max_iters=max(32, int(iters_suaves))
        )

    valid = np.asarray(valid_mask_bool, dtype=bool).reshape(h, w).copy()
    if not np.any(valid) or np.all(valid):
        return buf, 0

    arr = np.asarray(buf, dtype=np.float32).reshape(h, w, 4).copy()
    n_filled = 0
    for _ in range(max(0, min(int(iters_suaves), max(w, h)))):
        pending = ~valid
        if not np.any(pending):
            break
        pad_v = np.pad(valid, 1, mode="constant", constant_values=False)
        pad_c = np.pad(arr[:, :, :3], ((1, 1), (1, 1), (0, 0)), mode="constant", constant_values=0.0)
        sum_c = np.zeros((h, w, 3), dtype=np.float32)
        cnt = np.zeros((h, w), dtype=np.int32)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                m_nb = pad_v[1 + dy : 1 + dy + h, 1 + dx : 1 + dx + w]
                cnt += m_nb
                sum_c += pad_c[1 + dy : 1 + dy + h, 1 + dx : 1 + dx + w] * m_nb[:, :, None]
        fill_now = pending & (cnt > 0)
        if not np.any(fill_now):
            break
        arr[fill_now, :3] = sum_c[fill_now] / cnt[fill_now, None].astype(np.float32)
        arr[fill_now, 3] = 1.0
        valid |= fill_now
        n_filled += int(np.count_nonzero(fill_now))

    rem = ~valid
    if np.any(rem):
        yy, xx = np.mgrid[0:h, 0:w]
        seed_y = np.where(valid, yy, -1).astype(np.int32)
        seed_x = np.where(valid, xx, -1).astype(np.int32)
        best_d2 = np.where(valid, 0, np.int64(1) << 60)
        step = 1 << max(0, (max(w, h) - 1).bit_length() - 1)
        while step >= 1:
            for dy in (-step, 0, step):
                y0_d, y1_d = max(0, -dy), min(h, h - dy)
                y0_s, y1_s = max(0, dy), min(h, h + dy)
                if y0_d >= y1_d:
                    continue
                for dx in (-step, 0, step):
                    if dx == 0 and dy == 0:
                        continue
                    x0_d, x1_d = max(0, -dx), min(w, w - dx)
                    x0_s, x1_s = max(0, dx), min(w, w + dx)
                    if x0_d >= x1_d:
                        continue
                    sy_nb = seed_y[y0_s:y1_s, x0_s:x1_s]
                    sx_nb = seed_x[y0_s:y1_s, x0_s:x1_s]
                    ok = sy_nb >= 0
                    if not np.any(ok):
                        continue
                    dy_v = yy[y0_d:y1_d, x0_d:x1_d] - sy_nb
                    dx_v = xx[y0_d:y1_d, x0_d:x1_d] - sx_nb
                    d2 = dy_v.astype(np.int64) ** 2 + dx_v.astype(np.int64) ** 2
                    melhor = ok & (d2 < best_d2[y0_d:y1_d, x0_d:x1_d])
                    if np.any(melhor):
                        best_d2[y0_d:y1_d, x0_d:x1_d][melhor] = d2[melhor]
                        seed_y[y0_d:y1_d, x0_d:x1_d][melhor] = sy_nb[melhor]
                        seed_x[y0_d:y1_d, x0_d:x1_d][melhor] = sx_nb[melhor]
            step //= 2
        ok_rem = rem & (seed_y >= 0)
        if np.any(ok_rem):
            arr[ok_rem, :3] = arr[seed_y[ok_rem], seed_x[ok_rem], :3]
            arr[ok_rem, 3] = 1.0
            n_filled += int(np.count_nonzero(ok_rem))

    if isinstance(buf, np.ndarray):
        buf[...] = arr.reshape(buf.shape).astype(buf.dtype, copy=False)
        return buf, n_filled
    return _heal._escrever_buf_saida(buf, arr), n_filled


def dilatar_fundo_basecolor(
    cena, obj, img_bc, path_bc: str, px: int, nome_base: str
) -> tuple[Any, dict]:
    """Substitui o fundo preto (#000000) fora das ilhas UV do ``_baseColor`` por dilatacao de borda."""
    if bpy is None or obj is None or img_bc is None or not getattr(obj.data, "uv_layers", None) or px <= 0:
        return img_bc, {"aplicado": False, "motivo": "precondicao_ausente"}
    total_f = px * px * 4
    if len(getattr(img_bc, "pixels", ())) != total_f:
        return img_bc, {"aplicado": False, "motivo": "tamanho_invalido"}

    img_mask = _heal.assar_mascara_ilhas_uv(cena, obj, px, f"{nome_base}_bleed_uv")
    if img_mask is None:
        return img_bc, {"aplicado": False, "motivo": "sem_uv_mask"}

    estado = _cfg._capturar_estado_cena(cena)
    try:
        mask_buf = _heal._ler_buf_imagem(img_mask, px, px)
        bc_buf = _heal._ler_buf_imagem(img_bc, px, px)
        valid_mask = [mask_buf[i] > 0.5 for i in range(0, total_f, 4)]
        bc_buf, n_filled = dilatar_fundo_rgba_buf(bc_buf, valid_mask, px, px)
        if n_filled > 0:
            img_bc.pixels.foreach_set(bc_buf)
            _cfg._configurar_render_png_linear(cena)
            img_bc = _maps._salvar_e_recarregar_png(img_bc, path_bc, "sRGB", cena)
        return img_bc, {"aplicado": n_filled > 0, "pixels_dilatados": int(n_filled)}
    finally:
        _cfg._restaurar_estado_cena(cena, estado)
        if img_mask is not None and img_mask.name in bpy.data.images and img_mask.users == 0:
            bpy.data.images.remove(img_mask)


def _eh_pele_srgb_np(rgb_srgb):
    r, g, b = rgb_srgb[:, :, 0], rgb_srgb[:, :, 1], rgb_srgb[:, :, 2]
    cmax = np.maximum(np.maximum(r, g), b)
    cmin = np.minimum(np.minimum(r, g), b)
    delta = cmax - cmin
    sat = np.where(cmax > 1e-4, delta / np.maximum(cmax, 1e-4), 0.0)
    d_safe = np.where(delta > 1e-6, delta, 1.0)
    hue = np.zeros_like(cmax)
    rm = (delta > 1e-6) & (cmax == r)
    gm = (delta > 1e-6) & (~rm) & (cmax == g)
    bm = (delta > 1e-6) & (~rm) & (~gm)
    hue = np.where(rm, 60.0 * (((g - b) / d_safe) % 6.0), hue)
    hue = np.where(gm, 60.0 * (((b - r) / d_safe) + 2.0), hue)
    hue = np.where(bm, 60.0 * (((r - g) / d_safe) + 4.0), hue)
    return (
        (r > g * 0.98) & (r > b) & ((r - b) >= 0.04)
        & (cmax >= 0.14) & (cmax <= 0.98)
        & (sat >= 0.07) & (sat <= 0.68)
        & ((hue <= 38.0) | (hue >= 345.0))
    )


def _eh_pele_srgb_py(r: float, g: float, b: float) -> bool:
    if not (r > g * 0.98 and r > b and (r - b) >= 0.04):
        return False
    h_u, s, v = colorsys.rgb_to_hsv(max(0.0, min(1.0, r)), max(0.0, min(1.0, g)), max(0.0, min(1.0, b)))
    h_deg = h_u * 360.0
    return (0.14 <= v <= 0.98) and (0.07 <= s <= 0.68) and (h_deg <= 38.0 or h_deg >= 345.0)


def aplicar_trava_metalico_rosto_buf(
    hints_buf,
    bc_buf,
    face_mask_sub,
    head_mask_sub,
    px_sub: int,
    bw: int,
    bh: int,
    *,
    bc_linear: bool = True,
    min_rough_pele: float = 0.52,
) -> dict:
    """Trava ``metallic = 0.0`` na regiao facial descoberta ou texels de pele da cabeca."""
    if px_sub <= 0 or bw <= 0 or bh <= 0:
        return {"aplicado": False, "rosto_descoberto": False, "skin_frac_rosto": 0.0, "pixels_travados": 0}

    if np is not None:
        h_arr = np.asarray(hints_buf, dtype=np.float32).reshape(px_sub, px_sub, 4).copy()
        bc_arr = np.asarray(bc_buf, dtype=np.float32).reshape(bh, bw, 4)
        sy = np.minimum(bh - 1, (np.arange(px_sub) * bh) // px_sub)
        sx = np.minimum(bw - 1, (np.arange(px_sub) * bw) // px_sub)
        rgb = bc_arr[sy[:, None], sx[None, :], :3]
        rgb_srgb = _linear_para_srgb_np(rgb) if bc_linear else np.clip(rgb, 0.0, 1.0)
        skin_mask = _eh_pele_srgb_np(rgb_srgb)
        f_mask = np.asarray(face_mask_sub, dtype=bool).reshape(px_sub, px_sub)
        hd_mask = np.asarray(head_mask_sub, dtype=bool).reshape(px_sub, px_sub)
        n_face = int(np.count_nonzero(f_mask))
        skin_frac = (float(np.count_nonzero(f_mask & skin_mask)) / float(n_face)) if n_face > 0 else 0.0
        rosto_descoberto = (n_face >= 16) and (skin_frac >= 0.15)
        lock_mask = (f_mask | (hd_mask & skin_mask)) if rosto_descoberto else (hd_mask & skin_mask)
        n_trav = int(np.count_nonzero(lock_mask))
        if n_trav > 0:
            h_arr[lock_mask, 0] = 0.0
            h_arr[lock_mask, 1] = np.maximum(h_arr[lock_mask, 1], float(min_rough_pele))
            h_arr[lock_mask, 2] = np.maximum(h_arr[lock_mask, 2], 1.0)
            if isinstance(hints_buf, np.ndarray):
                hints_buf[...] = h_arr.reshape(hints_buf.shape).astype(hints_buf.dtype, copy=False)
            else:
                _heal._escrever_buf_saida(hints_buf, h_arr)
        return {
            "aplicado": n_trav > 0,
            "rosto_descoberto": bool(rosto_descoberto),
            "skin_frac_rosto": round(skin_frac, 4),
            "pixels_travados": n_trav,
        }

    ys = [min(bh - 1, (y * bh) // px_sub) for y in range(px_sub)]
    xs = [min(bw - 1, (x * bw) // px_sub) for x in range(px_sub)]
    skin_mask_l = [False] * (px_sub * px_sub)
    n_face = n_skin_face = 0
    for py, by in enumerate(ys):
        for px_i, bx in enumerate(xs):
            p = py * px_sub + px_i
            bi = (by * bw + bx) * 4
            r, g, b = bc_buf[bi], bc_buf[bi + 1], bc_buf[bi + 2]
            if bc_linear:
                r, g, b = _linear_para_srgb_val(r), _linear_para_srgb_val(g), _linear_para_srgb_val(b)
            eh_skin = _eh_pele_srgb_py(r, g, b)
            skin_mask_l[p] = eh_skin
            if face_mask_sub[p]:
                n_face += 1
                if eh_skin:
                    n_skin_face += 1
    skin_frac = (n_skin_face / float(n_face)) if n_face > 0 else 0.0
    rosto_descoberto = (n_face >= 16) and (skin_frac >= 0.15)
    n_trav = 0
    for p in range(px_sub * px_sub):
        if (face_mask_sub[p] or (head_mask_sub[p] and skin_mask_l[p])) if rosto_descoberto else (head_mask_sub[p] and skin_mask_l[p]):
            off = p * 4
            hints_buf[off] = 0.0
            hints_buf[off + 1] = max(float(hints_buf[off + 1]), float(min_rough_pele))
            hints_buf[off + 2] = max(float(hints_buf[off + 2]), 1.0)
            n_trav += 1
    return {
        "aplicado": n_trav > 0,
        "rosto_descoberto": bool(rosto_descoberto),
        "skin_frac_rosto": round(skin_frac, 4),
        "pixels_travados": n_trav,
    }


def travar_metalico_rosto_pele(
    cena, obj, img_hints_tmp, img_bc, px_sub: int, nome_base: str, *, tipo_item: str | None = None
) -> dict:
    """Assa mascara geometrica da cabeca/rosto no humanoide ereto e trava ``metallic=0`` na pele."""
    skip = {"aplicado": False, "motivo": "nao_aplicavel"}
    if tipo_item and str(tipo_item).strip() != "personagem_humanoide":
        return skip
    if bpy is None or obj is None or getattr(obj, "data", None) is None or img_hints_tmp is None or img_bc is None:
        return skip
    if not obj.data.uv_layers or len(obj.data.polygons) < 400 or not obj.data.vertices or px_sub <= 0:
        return skip

    xs = [v.co.x for v in obj.data.vertices]
    ys = [v.co.y for v in obj.data.vertices]
    zs = [v.co.z for v in obj.data.vertices]
    w_m, d_m, z_min, h_m = max(xs) - min(xs), max(ys) - min(ys), min(zs), max(zs) - min(zs)
    if h_m <= 1e-6 or h_m < 0.80 * max(w_m, d_m) or d_m > 0.72 * h_m:
        return skip

    cx_mid = 0.5 * (min(xs) + max(xs))
    top_xs = [v.co.x for v in obj.data.vertices if v.co.z >= z_min + 0.86 * h_m and abs(v.co.x - cx_mid) <= 0.16 * h_m]
    cx_h = (sum(top_xs) / float(len(top_xs))) if top_xs else cx_mid

    uv0_nome = str(obj.data.uv_layers[0].name)
    attr_nome = "_f3d_face_mask_tmp"
    mats_ant = list(obj.data.materials)
    poly_mat_indices = [int(p.material_index) for p in obj.data.polygons]
    engine_ant = str(cena.render.engine)
    s2a_ant, clear_ant = bool(cena.render.bake.use_selected_to_active), bool(cena.render.bake.use_clear)
    margin_ant, samples_ant = int(cena.render.bake.margin), int(cena.cycles.samples)
    active_ant = bpy.context.view_layer.objects.active
    mat_m = tex_m = img_m = None
    try:
        if attr_nome in obj.data.color_attributes:
            obj.data.color_attributes.remove(obj.data.color_attributes[attr_nome])
        attr = obj.data.color_attributes.new(name=attr_nome, type="FLOAT_COLOR", domain="CORNER")
        for poly in obj.data.polygons:
            c, n = poly.center, poly.normal
            in_head = (c.z >= z_min + 0.78 * h_m) and (abs(c.x - cx_h) <= 0.14 * h_m) and (n.y > -0.15)
            in_face = (c.z >= z_min + 0.84 * h_m) and (abs(c.x - cx_h) <= 0.11 * h_m) and (n.y > 0.12)
            col = (1.0 if in_face else 0.0, 1.0 if in_head else 0.0, 0.0, 1.0)
            for li in poly.loop_indices:
                attr.data[li].color = col

        if cena.render.engine != "CYCLES":
            _cfg._configurar_dispositivo_cycles(cena, preferir_gpu=True)
        mat_m, tex_m = _maps._criar_material_alvo_bake(f"{nome_base}_face_mask_mat_tmp")
        nt = mat_m.node_tree
        if (bsdf := nt.nodes.get("Principled BSDF")) is not None:
            nt.nodes.remove(bsdf)
        out = nt.nodes.get("Material Output") or nt.nodes.new("ShaderNodeOutputMaterial")
        vc = nt.nodes.new("ShaderNodeVertexColor")
        vc.layer_name = attr_nome
        emit = nt.nodes.new("ShaderNodeEmission")
        emit.inputs["Strength"].default_value = 1.0
        nt.links.new(vc.outputs["Color"], emit.inputs["Color"])
        nt.links.new(emit.outputs["Emission"], out.inputs["Surface"])

        img_m = bpy.data.images.new(f"{nome_base}_face_mask_tmp", width=px_sub, height=px_sub, alpha=False)
        img_m.colorspace_settings.name = "Non-Color"
        tex_m.image, tex_m.select, nt.nodes.active = img_m, True, tex_m
        obj.data.materials.clear()
        obj.data.materials.append(mat_m)
        obj.data.uv_layers.active = obj.data.uv_layers[uv0_nome]
        obj.data.uv_layers[uv0_nome].active_render = True
        cena.render.bake.use_selected_to_active, cena.render.bake.use_clear = False, True
        cena.render.bake.margin, cena.cycles.samples = max(2, px_sub // 256), 1
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        _cfg._executar_bake_seguro(cena, type="EMIT")

        bw, bh = int(img_bc.size[0]), int(img_bc.size[1])
        m_buf = _heal._ler_buf_imagem(img_m, px_sub, px_sub)
        h_buf = _heal._ler_buf_imagem(img_hints_tmp, px_sub, px_sub)
        bc_buf = _heal._ler_buf_imagem(img_bc, bw, bh)
        face_mask = [m_buf[i] > 0.5 for i in range(0, px_sub * px_sub * 4, 4)]
        head_mask = [m_buf[i + 1] > 0.5 for i in range(0, px_sub * px_sub * 4, 4)]
        info = aplicar_trava_metalico_rosto_buf(h_buf, bc_buf, face_mask, head_mask, px_sub, bw, bh)
        if info.get("aplicado"):
            img_hints_tmp.pixels.foreach_set(h_buf)
        return info
    finally:
        if tex_m is not None:
            tex_m.image = None
        if img_m is not None and img_m.name in bpy.data.images and img_m.users == 0:
            bpy.data.images.remove(img_m)
        _heal._restaurar_materiais_e_indices(obj, mats_ant, poly_mat_indices)
        if attr_nome in obj.data.color_attributes:
            obj.data.color_attributes.remove(obj.data.color_attributes[attr_nome])
        if uv0_nome in obj.data.uv_layers:
            obj.data.uv_layers.active = obj.data.uv_layers[uv0_nome]
            obj.data.uv_layers[uv0_nome].active_render = True
        if mat_m is not None and mat_m.name in bpy.data.materials and mat_m.users == 0:
            bpy.data.materials.remove(mat_m)
        cena.render.bake.use_selected_to_active, cena.render.bake.use_clear = s2a_ant, clear_ant
        cena.render.bake.margin, cena.cycles.samples, cena.render.engine = margin_ant, samples_ant, engine_ant
        if active_ant is not None:
            bpy.context.view_layer.objects.active = active_ant
