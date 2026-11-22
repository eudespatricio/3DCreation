"""Heuristicas PBR e extracao emissive do Forge3D Delight (CPU, 0 VRAM).

Suporta ``cv2`` + ``numpy`` nas venvs de inferencia e fallback Pillow puro.
"""

from __future__ import annotations

import colorsys
import statistics
from collections import deque
from typing import Any

from PIL import Image, ImageFilter

try:  # noqa: SIM105 - opcional no nucleo .venv sem numpy/cv2
    import cv2  # type: ignore[import-not-found]
    import numpy as np  # type: ignore[import-not-found]

    _TEM_CV2 = True
except ImportError:
    cv2 = None
    np = None
    _TEM_CV2 = False


def _mascara_foreground_cv2(arr: Any) -> Any:
    """Detecta foreground mesmo em imagem opaca sobre fundo neutro uniforme."""
    h, w = arr.shape[:2]
    if h <= 0 or w <= 0:
        raise ValueError(f"imagem invalida: {w}x{h}")
    alpha = arr[:, :, 3]
    fg = alpha >= 24
    if int(alpha.min()) < 250:
        return fg

    rgb = arr[:, :, :3]
    c = max(1, min(8, min(h, w) // 16))
    cantos = np.concatenate(
        [rgb[:c, :c].reshape(-1, 3), rgb[:c, -c:].reshape(-1, 3), rgb[-c:, :c].reshape(-1, 3), rgb[-c:, -c:].reshape(-1, 3)],
        axis=0,
    ).astype(np.float32)
    bordas = np.concatenate([rgb[0, :], rgb[-1, :], rgb[:, 0], rgb[:, -1]], axis=0).astype(np.float32)
    bg_rgb = np.median(np.concatenate([cantos, bordas], axis=0), axis=0)
    if float(np.percentile(np.linalg.norm(cantos - bg_rgb, axis=1), 90)) >= 20.0:
        return fg

    bg_cand = (np.linalg.norm(rgb.astype(np.float32) - bg_rgb, axis=2) < 14.0).astype(np.uint8)
    n_labels, labels = cv2.connectedComponents(bg_cand, connectivity=4)
    if n_labels <= 1:
        return fg

    borda_ids = np.unique(np.concatenate([labels[0, :], labels[-1, :], labels[:, 0], labels[:, -1]]))
    borda_ids = borda_ids[borda_ids > 0]
    if len(borda_ids) == 0:
        return fg
    eh_bg_borda = np.zeros(n_labels, dtype=bool)
    eh_bg_borda[borda_ids] = True
    return fg & (~eh_bg_borda[labels])


def _mascara_foreground_pil(rgba: Image.Image) -> list[int]:
    """Versao Pillow puro de deteccao de foreground (0=fundo, 1=objeto)."""
    w, h = rgba.size
    if w <= 0 or h <= 0:
        raise ValueError(f"imagem invalida: {w}x{h}")
    raw = rgba.tobytes()
    alphas = raw[3::4]
    if min(alphas) < 250:
        return [1 if a >= 24 else 0 for a in alphas]

    c = max(1, min(8, min(w, h) // 16))
    ys = list(range(min(c, h))) + list(range(max(0, h - c), h))
    xs = list(range(min(c, w))) + list(range(max(0, w - c), w))
    cantos = [(raw[(y * w + x) * 4], raw[(y * w + x) * 4 + 1], raw[(y * w + x) * 4 + 2]) for y in ys for x in xs]
    bg_r = statistics.median(p[0] for p in cantos)
    bg_g = statistics.median(p[1] for p in cantos)
    bg_b = statistics.median(p[2] for p in cantos)
    dists_cantos = sorted(((p[0] - bg_r) ** 2 + (p[1] - bg_g) ** 2 + (p[2] - bg_b) ** 2) ** 0.5 for p in cantos)
    if dists_cantos[min(len(dists_cantos) - 1, int(0.9 * (len(dists_cantos) - 1)))] >= 20.0:
        return [1] * (w * h)

    limiar2 = 14.0 * 14.0

    def _eh_bg(idx: int) -> bool:
        off = idx * 4
        return (raw[off] - bg_r) ** 2 + (raw[off + 1] - bg_g) ** 2 + (raw[off + 2] - bg_b) ** 2 < limiar2

    bg = bytearray(w * h)
    fila: deque[int] = deque()
    for idx in (*(y * w + x for x in range(w) for y in (0, h - 1)), *(y * w + x for y in range(h) for x in (0, w - 1))):
        if not bg[idx] and _eh_bg(idx):
            bg[idx] = 1
            fila.append(idx)

    while fila:
        idx = fila.popleft()
        cx, cy = idx % w, idx // w
        for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
            if 0 <= nx < w and 0 <= ny < h:
                n = ny * w + nx
                if not bg[n] and _eh_bg(n):
                    bg[n] = 1
                    fila.append(n)

    return [0 if bg[i] else 1 for i in range(w * h)]


def _rgb_para_hsv_f32_np(rgb: Any) -> tuple[Any, Any, Any]:
    """Converte RGB uint8 para HSV float32 identico a ``colorsys.rgb_to_hsv``."""
    rf = rgb[:, :, 0].astype(np.float32)
    gf = rgb[:, :, 1].astype(np.float32)
    bf = rgb[:, :, 2].astype(np.float32)
    cmax = np.maximum(np.maximum(rf, gf), bf)
    cmin = np.minimum(np.minimum(rf, gf), bf)
    delta = cmax - cmin
    h_deg = np.zeros_like(cmax)
    mask = delta > 0.0
    d_safe = np.where(mask, delta, 1.0)
    r_max = mask & (cmax == rf)
    g_max = mask & (~r_max) & (cmax == gf)
    b_max = mask & (~r_max) & (~g_max)
    h_deg = np.where(r_max, 60.0 * (((gf - bf) / d_safe) % 6.0), h_deg)
    h_deg = np.where(g_max, 60.0 * (((bf - rf) / d_safe) + 2.0), h_deg)
    h_deg = np.where(b_max, 60.0 * (((rf - gf) / d_safe) + 4.0), h_deg)
    s_u8 = np.where(cmax > 0.0, (delta / np.maximum(cmax, 1.0)) * 255.0, 0.0)
    return h_deg, s_u8, cmax


def _mapas_pbr_cv2(rgba: Image.Image) -> tuple[Image.Image, Image.Image]:
    arr = np.array(rgba.convert("RGBA"))
    rgb = arr[:, :, :3]
    fg = _mascara_foreground_cv2(arr)

    h_deg, s_u8, v_u8 = _rgb_para_hsv_f32_np(rgb)
    r_i = rgb[:, :, 0].astype(np.int32)
    g_i = rgb[:, :, 1].astype(np.int32)
    b_i = rgb[:, :, 2].astype(np.int32)
    l_u8 = ((r_i * 299 + g_i * 587 + b_i * 114 + 500) // 1000).astype(np.uint8)
    l_f32 = l_u8.astype(np.float32)
    cool_diff = b_i - r_i
    neutral_rg = np.abs(r_i - g_i)

    # Estende luminancia da borda do foreground para fora, evitando falso contraste contra fundo cinza.
    h, w = l_u8.shape
    k = max(5, min(11, (min(h, w) // 48) | 1))
    k_g = max(21, k)
    k_fe = max(15, min(21, (min(h, w) // 8) | 1))
    if np.any(fg) and not np.all(fg):
        r_ext = max(3, k)
        kb = 2 * r_ext + 1
        fg_f = fg.astype(np.float32)
        soma_l = cv2.boxFilter(
            l_f32 * fg_f, -1, (kb, kb), normalize=False, borderType=cv2.BORDER_REPLICATE
        )
        soma_w = cv2.boxFilter(
            fg_f, -1, (kb, kb), normalize=False, borderType=cv2.BORDER_REPLICATE
        )
        l_padrao = float(np.mean(l_f32[fg]))
        l_ext = np.where(soma_w > 1e-4, np.rint(soma_l / np.maximum(soma_w, 1e-4)), l_padrao)
        l_contraste_u8 = np.clip(np.where(fg, l_f32, l_ext), 0, 255).astype(np.uint8)
    else:
        l_contraste_u8 = l_u8

    kernel = np.ones((k, k), dtype=np.uint8)
    kernel_g = np.ones((k_g, k_g), dtype=np.uint8)
    kernel_fe = np.ones((k_fe, k_fe), dtype=np.uint8)
    local_max = cv2.dilate(l_contraste_u8, kernel, borderType=cv2.BORDER_REPLICATE).astype(np.float32)
    local_min = cv2.erode(l_contraste_u8, kernel, borderType=cv2.BORDER_REPLICATE).astype(np.float32)
    local_range = local_max - local_min
    local_range_g = cv2.dilate(
        l_contraste_u8, kernel_g, borderType=cv2.BORDER_REPLICATE
    ).astype(np.float32) - cv2.erode(
        l_contraste_u8, kernel_g, borderType=cv2.BORDER_REPLICATE
    ).astype(np.float32)
    l_max_fe = cv2.dilate(l_contraste_u8, kernel_fe, borderType=cv2.BORDER_REPLICATE).astype(np.float32)
    l_min_fe = cv2.erode(l_contraste_u8, kernel_fe, borderType=cv2.BORDER_REPLICATE).astype(np.float32)
    l_range_fe = l_max_fe - l_min_fe
    base_ferro_f = (
        (l_contraste_u8 >= 36) & (l_contraste_u8 <= 82) & (s_u8 < 58.0) & (cool_diff >= -3)
    ).astype(np.float32)
    frac_base_ferro = cv2.boxFilter(
        base_ferro_f, -1, (k_fe, k_fe), normalize=True, borderType=cv2.BORDER_REPLICATE
    )

    prata = (s_u8 < 42.0) & (local_min >= 52.0) & (
        ((l_f32 >= 95.0) & (l_f32 <= 240.0) & (local_range >= 42.0) & (local_max >= 175.0))
        | ((l_f32 >= 95.0) & (l_f32 <= 232.0) & (cool_diff >= 4) & (local_range_g >= 2.0))
        | ((s_u8 < 25.0) & (l_f32 >= 160.0) & (l_f32 <= 186.0) & (cool_diff >= 4) & (neutral_rg <= 2))
    )
    gunmetal = (s_u8 < 42.0) & (l_f32 >= 55.0) & (l_f32 < 95.0) & (local_min >= 48.0) & (
        ((local_max >= 115.0) & (local_range >= 32.0)) | ((cool_diff >= 4) & (local_range_g >= 2.0))
    )
    tem_espec_fe = ((cool_diff >= 2) & (l_max_fe >= 72.0) & (l_range_fe >= 24.0)) | (
        (l_max_fe >= 96.0) & (l_range_fe >= 40.0)
    )
    ferro_escuro = (cool_diff >= -3) & tem_espec_fe & (
        ((s_u8 < 62.0) & (l_f32 >= 26.0) & (l_f32 < 86.0) & (frac_base_ferro >= 0.20))
        | ((s_u8 < 52.0) & (l_f32 >= 86.0) & (l_f32 <= 215.0) & (local_min <= 62.0) & (frac_base_ferro >= 0.35))
    )
    ouro = (h_deg >= 34.0) & (h_deg <= 48.0) & (s_u8 >= 110.0) & (s_u8 <= 205.0) & (v_u8 >= 165.0) & (
        ((local_max >= 200.0) & (local_range >= 40.0))
        | (v_u8 >= 230.0)
        | (local_range >= 55.0)
        | ((s_u8 >= 160.0) & (s_u8 <= 192.0) & (v_u8 >= 208.0) & (local_range <= 8.0))
    )
    bronze = (h_deg >= 16.0) & (h_deg <= 33.5) & (s_u8 >= 105.0) & (s_u8 <= 190.0) & (v_u8 >= 135.0) & (
        (local_range >= 45.0)
        | ((v_u8 >= 230.0) & (local_range >= 28.0))
        | ((h_deg >= 28.0) & (s_u8 >= 155.0) & (s_u8 <= 176.0) & (v_u8 >= 160.0) & (local_range_g >= 2.0) & (local_range_g <= 18.0))
    )
    metal = (prata | gunmetal | ferro_escuro | ouro | bronze) & fg

    l_fe_clamped = np.clip(l_f32 - 30.0, 0.0, 56.0)
    metallic = np.zeros((h, w), dtype=np.uint8)
    metallic[metal] = np.clip(np.rint(205.0 + (l_f32 - 95.0) * 0.14), 198.0, 230.0).astype(np.uint8)[metal]
    metallic[ferro_escuro & fg] = np.clip(
        np.rint(188.0 + l_fe_clamped * 0.60), 188.0, 222.0
    ).astype(np.uint8)[ferro_escuro & fg]
    metallic[gunmetal & fg] = np.clip(np.rint(195.0 + (l_f32 - 50.0) * 0.35), 192.0, 218.0).astype(np.uint8)[gunmetal & fg]
    metallic[bronze & fg] = 208
    metallic[ouro & fg] = 218

    roughness = np.full((h, w), 209, dtype=np.uint8)
    roughness[fg] = np.clip(np.rint(218.0 - 0.12 * v_u8), 185.0, 224.0).astype(np.uint8)[fg]
    roughness[fg & (~metal) & (s_u8 < 55.0) & (v_u8 >= 160.0) & (local_min >= 145.0)] = 160
    roughness[fg & (~metal) & (s_u8 >= 65.0) & (v_u8 >= 55.0) & (local_range >= 22.0)] = 158
    roughness[fg & (~metal) & (h_deg >= 1.5) & (h_deg <= 42.0) & (s_u8 >= 30.0) & (s_u8 <= 195.0) & (v_u8 >= 30.0) & (v_u8 <= 240.0)] = 140
    roughness[metal] = np.clip(np.rint(95.0 - (l_f32 / 255.0) * 26.0), 64.0, 97.0).astype(np.uint8)[metal]
    roughness[gunmetal & fg] = np.clip(np.rint(96.0 - (l_f32 / 255.0) * 28.0), 68.0, 94.0).astype(np.uint8)[gunmetal & fg]
    roughness[ferro_escuro & fg] = np.clip(
        np.rint(94.0 - l_fe_clamped * 0.50), 66.0, 94.0
    ).astype(np.uint8)[ferro_escuro & fg]
    roughness[bronze & fg] = np.clip(np.rint(102.0 - (l_f32 / 255.0) * 28.0), 64.0, 105.0).astype(np.uint8)[bronze & fg]

    return Image.fromarray(metallic, mode="L"), Image.fromarray(roughness, mode="L")


def _mapas_pbr_pil(rgba: Image.Image) -> tuple[Image.Image, Image.Image]:
    rgba_conv = rgba.convert("RGBA")
    w, h = rgba_conv.size
    fg_mask = _mascara_foreground_pil(rgba_conv)
    l_img = rgba_conv.convert("L")
    l_bytes = l_img.tobytes()
    raw = rgba_conv.tobytes()

    k = max(5, min(11, (min(w, h) // 48) | 1))
    k_g = max(21, k)
    k_fe = max(15, min(21, (min(w, h) // 8) | 1))
    if any(fg_mask) and not all(fg_mask):
        r_ext = max(3, k)
        fg_u8 = Image.frombytes("L", (w, h), bytes(255 if f else 0 for f in fg_mask))
        lf_u8 = Image.frombytes("L", (w, h), bytes(l_bytes[i] if fg_mask[i] else 0 for i in range(w * h)))
        blur_w = fg_u8.filter(ImageFilter.BoxBlur(r_ext)).tobytes()
        blur_l = lf_u8.filter(ImageFilter.BoxBlur(r_ext)).tobytes()
        fg_vals = [l_bytes[i] for i, fg in enumerate(fg_mask) if fg]
        l_padrao = sum(fg_vals) // len(fg_vals)
        l_limpo = Image.frombytes(
            "L",
            (w, h),
            bytes(
                l_bytes[i]
                if fg_mask[i]
                else (min(255, round(blur_l[i] * 255.0 / blur_w[i])) if blur_w[i] > 0 else l_padrao)
                for i in range(w * h)
            ),
        )
    else:
        l_limpo = l_img

    l_max = l_limpo.filter(ImageFilter.MaxFilter(k)).tobytes()
    l_min = l_limpo.filter(ImageFilter.MinFilter(k)).tobytes()
    l_max_g = l_limpo.filter(ImageFilter.MaxFilter(k_g)).tobytes()
    l_min_g = l_limpo.filter(ImageFilter.MinFilter(k_g)).tobytes()
    l_max_fe = l_limpo.filter(ImageFilter.MaxFilter(k_fe)).tobytes()
    l_min_fe = l_limpo.filter(ImageFilter.MinFilter(k_fe)).tobytes()
    l_limpo_b = l_limpo.tobytes()
    base_fe_mask = bytearray(w * h)
    for i_fe in range(w * h):
        px_l = l_limpo_b[i_fe]
        if 36 <= px_l <= 82:
            off_fe = i_fe * 4
            rf_fe, gf_fe, bf_fe = raw[off_fe], raw[off_fe + 1], raw[off_fe + 2]
            cmax_fe = max(rf_fe, gf_fe, bf_fe)
            s_fe = ((cmax_fe - min(rf_fe, gf_fe, bf_fe)) * 255.0 / cmax_fe) if cmax_fe > 0 else 0.0
            if s_fe < 58.0 and (bf_fe - rf_fe) >= -3:
                base_fe_mask[i_fe] = 255
    blur_base_fe = Image.frombytes("L", (w, h), bytes(base_fe_mask)).filter(ImageFilter.BoxBlur(k_fe // 2)).tobytes()

    metallic = bytearray(w * h)
    roughness = bytearray([209] * (w * h))

    for idx in range(w * h):
        if not fg_mask[idx]:
            continue
        off = idx * 4
        r, g, b = raw[off], raw[off + 1], raw[off + 2]
        h_f, s_f, v_f = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
        h_deg, s_u8, v_u8 = h_f * 360.0, s_f * 255.0, v_f * 255.0
        l_u8, l_mx, l_mn = l_bytes[idx], l_max[idx], l_min[idx]
        l_range, l_range_g, cool_diff = l_mx - l_mn, l_max_g[idx] - l_min_g[idx], b - r
        l_mx_fe, l_rg_fe, frac_fe = l_max_fe[idx], l_max_fe[idx] - l_min_fe[idx], blur_base_fe[idx] / 255.0

        eh_ouro = (
            34.0 <= h_deg <= 48.0 and 110.0 <= s_u8 <= 205.0 and v_u8 >= 165.0
            and (
                (l_mx >= 200 and l_range >= 40) or v_u8 >= 230.0 or l_range >= 55
                or (160.0 <= s_u8 <= 192.0 and v_u8 >= 208.0 and l_range <= 8)
            )
        )
        eh_bronze = (
            16.0 <= h_deg <= 33.5 and 105.0 <= s_u8 <= 190.0 and v_u8 >= 135.0
            and (
                l_range >= 45 or (v_u8 >= 230.0 and l_range >= 28)
                or (28.0 <= h_deg <= 33.5 and 155.0 <= s_u8 <= 176.0 and v_u8 >= 160.0 and 2 <= l_range_g <= 18)
            )
        )
        eh_prata = (
            s_u8 < 42.0 and l_mn >= 52 and (
                (95 <= l_u8 <= 240 and l_range >= 42 and l_mx >= 175)
                or (95 <= l_u8 <= 232 and cool_diff >= 4 and l_range_g >= 2)
                or (160 <= l_u8 <= 186 and cool_diff >= 4 and abs(r - g) <= 2 and s_u8 < 25.0)
            )
        )
        eh_gunmetal = (
            s_u8 < 42.0 and 55 <= l_u8 < 95 and l_mn >= 48
            and ((l_mx >= 115 and l_range >= 32) or (cool_diff >= 4 and l_range_g >= 2))
        )
        tem_espec_fe = (cool_diff >= 2 and l_mx_fe >= 72 and l_rg_fe >= 24) or (l_mx_fe >= 96 and l_rg_fe >= 40)
        eh_ferro_escuro = cool_diff >= -3 and tem_espec_fe and (
            (s_u8 < 62.0 and 26 <= l_u8 < 86 and frac_fe >= 0.20)
            or (s_u8 < 52.0 and 86 <= l_u8 <= 215 and l_mn <= 62 and frac_fe >= 0.35)
        )
        if eh_ouro:
            metallic[idx] = 218
            roughness[idx] = max(64, min(97, round(95.0 - (l_u8 / 255.0) * 26.0)))
        elif eh_bronze:
            metallic[idx] = 208
            roughness[idx] = max(64, min(105, round(102.0 - (l_u8 / 255.0) * 28.0)))
        elif eh_prata:
            metallic[idx] = max(198, min(230, round(205.0 + (l_u8 - 95.0) * 0.14)))
            roughness[idx] = max(64, min(97, round(95.0 - (l_u8 / 255.0) * 26.0)))
        elif eh_ferro_escuro:
            l_fe_c = max(0.0, min(56.0, float(l_u8 - 30)))
            metallic[idx] = max(188, min(222, round(188.0 + l_fe_c * 0.60)))
            roughness[idx] = max(66, min(94, round(94.0 - l_fe_c * 0.50)))
        elif eh_gunmetal:
            metallic[idx] = max(192, min(218, round(195.0 + (l_u8 - 50.0) * 0.35)))
            roughness[idx] = max(68, min(94, round(96.0 - (l_u8 / 255.0) * 28.0)))
        elif 1.5 <= h_deg <= 42.0 and 30.0 <= s_u8 <= 195.0 and 30.0 <= v_u8 <= 240.0:
            roughness[idx] = 140
        elif s_u8 >= 65.0 and v_u8 >= 55.0 and l_range >= 22:
            roughness[idx] = 158
        elif s_u8 < 55.0 and v_u8 >= 160.0 and l_mn >= 145:
            roughness[idx] = 160
        else:
            roughness[idx] = max(185, min(224, round(218.0 - 0.12 * v_u8)))

    return (
        Image.frombytes("L", (w, h), bytes(metallic)),
        Image.frombytes("L", (w, h), bytes(roughness)),
    )


def estimar_mapas_pbr(img_rgba: Image.Image) -> tuple[Image.Image, Image.Image]:
    """Gera mascaras ``(metallic, roughness)`` em ``L`` para o bake Camera UV."""
    if _TEM_CV2:
        return _mapas_pbr_cv2(img_rgba)
    return _mapas_pbr_pil(img_rgba)


def _emissive_cv2(rgba: Image.Image) -> Image.Image:
    arr = np.array(rgba.convert("RGBA"))
    rgb = arr[:, :, :3]
    fg = _mascara_foreground_cv2(arr)
    h_deg, s_u8, v_u8 = _rgb_para_hsv_f32_np(rgb)
    fg_v_p75 = float(np.percentile(v_u8[fg], 75)) if np.any(fg) else 128.0
    v_rel_lim = max(180.0, fg_v_p75 + 45.0)

    v_warm_mod = max(195.0, fg_v_p75 + 65.0)
    warm_glow = (
        (h_deg >= 10.0)
        & (h_deg <= 48.0)
        & (s_u8 >= 150.0)
        & (v_u8 >= v_rel_lim)
        & ((s_u8 >= 206.0) | (v_u8 >= 238.0) | ((h_deg <= 37.5) & (v_u8 >= v_warm_mod)))
    )
    cool_glow = (h_deg >= 175.0) & (h_deg <= 260.0) & (s_u8 >= 145.0) & (v_u8 >= v_rel_lim)
    seed = fg & (
        ((v_u8 >= 250.0) & (s_u8 >= 140.0))
        | ((v_u8 >= 225.0) & (s_u8 >= 210.0) & ((h_deg < 20.0) | (h_deg > 50.0)))
        | warm_glow
        | cool_glow
    )
    cand_branco = fg & (v_u8 >= 248.0)
    ativo = seed.copy()
    if np.any(seed) and np.any(cand_branco & (~seed)):
        n_labels, labels = cv2.connectedComponents((seed | cand_branco).astype(np.uint8), connectivity=4)
        if n_labels > 1:
            seed_labels = np.unique(labels[seed])
            seed_labels = seed_labels[seed_labels > 0]
            if len(seed_labels) > 0:
                ativo = np.isin(labels, seed_labels)

    emissive = np.zeros(rgb.shape[:2], dtype=np.uint8)
    valores = np.clip(np.rint(180.0 + np.maximum(0.0, v_u8 - 180.0)), 180.0, 255.0).astype(np.uint8)
    emissive[ativo] = valores[ativo]
    return Image.fromarray(emissive, mode="L")


def _emissive_pil(rgba: Image.Image) -> Image.Image:
    rgba_conv = rgba.convert("RGBA")
    w, h = rgba_conv.size
    fg_mask = _mascara_foreground_pil(rgba_conv)
    raw = rgba_conv.tobytes()
    seed = bytearray(w * h)
    branco = bytearray(w * h)
    h_vals = [0.0] * (w * h)
    s_vals = [0.0] * (w * h)
    v_vals = [0.0] * (w * h)
    fg_vs: list[float] = []
    fila: deque[int] = deque()

    for idx in range(w * h):
        if not fg_mask[idx]:
            continue
        off = idx * 4
        h_f, s_f, v_f = colorsys.rgb_to_hsv(raw[off] / 255.0, raw[off + 1] / 255.0, raw[off + 2] / 255.0)
        h_vals[idx], s_vals[idx], v_vals[idx] = h_f * 360.0, s_f * 255.0, v_f * 255.0
        fg_vs.append(v_vals[idx])

    fg_vs.sort()
    fg_v_p75 = fg_vs[int(0.75 * (len(fg_vs) - 1))] if fg_vs else 128.0
    v_rel_lim = max(180.0, fg_v_p75 + 45.0)
    v_warm_mod = max(195.0, fg_v_p75 + 65.0)

    for idx in range(w * h):
        if not fg_mask[idx]:
            continue
        h_deg, s_u8, v_u8 = h_vals[idx], s_vals[idx], v_vals[idx]
        eh_warm = (
            10.0 <= h_deg <= 48.0 and s_u8 >= 150.0 and v_u8 >= v_rel_lim
            and (s_u8 >= 206.0 or v_u8 >= 238.0 or (h_deg <= 37.5 and v_u8 >= v_warm_mod))
        )
        eh_cool = 175.0 <= h_deg <= 260.0 and s_u8 >= 145.0 and v_u8 >= v_rel_lim
        if (
            (v_u8 >= 250.0 and s_u8 >= 140.0)
            or (v_u8 >= 225.0 and s_u8 >= 210.0 and (h_deg < 20.0 or h_deg > 50.0))
            or eh_warm
            or eh_cool
        ):
            seed[idx] = 1
            fila.append(idx)
        elif v_u8 >= 248.0:
            branco[idx] = 1

    ativo = bytearray(seed)
    while fila:
        idx = fila.popleft()
        cx, cy = idx % w, idx // w
        for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
            if 0 <= nx < w and 0 <= ny < h:
                n = ny * w + nx
                if branco[n] and not ativo[n]:
                    ativo[n] = 1
                    fila.append(n)

    out = bytearray(w * h)
    for idx in range(w * h):
        if ativo[idx]:
            out[idx] = max(180, min(255, round(180.0 + max(0.0, v_vals[idx] - 180.0))))
    return Image.frombytes("L", (w, h), bytes(out))


def extrair_emissive(img_rgba: Image.Image) -> Image.Image:
    """Extrai mascara ``emissive`` em ``L`` para regioes brilhantes e saturadas."""
    if _TEM_CV2:
        return _emissive_cv2(img_rgba)
    return _emissive_pil(img_rgba)
