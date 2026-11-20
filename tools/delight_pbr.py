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
        [
            rgb[:c, :c].reshape(-1, 3),
            rgb[:c, -c:].reshape(-1, 3),
            rgb[-c:, :c].reshape(-1, 3),
            rgb[-c:, -c:].reshape(-1, 3),
        ],
        axis=0,
    ).astype(np.float32)
    bordas = np.concatenate([rgb[0, :], rgb[-1, :], rgb[:, 0], rgb[:, -1]], axis=0).astype(
        np.float32
    )
    bg_rgb = np.median(np.concatenate([cantos, bordas], axis=0), axis=0)
    spread = float(np.percentile(np.linalg.norm(cantos - bg_rgb, axis=1), 90))
    if spread >= 20.0:
        return fg

    dist = np.linalg.norm(rgb.astype(np.float32) - bg_rgb, axis=2)
    bg_cand = (dist < 14.0).astype(np.uint8)
    n_labels, labels = cv2.connectedComponents(bg_cand, connectivity=4)
    if n_labels <= 1:
        return fg

    borda_ids = np.unique(
        np.concatenate([labels[0, :], labels[-1, :], labels[:, 0], labels[:, -1]])
    )
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
    cantos: list[tuple[int, int, int]] = []
    ys = list(range(min(c, h))) + list(range(max(0, h - c), h))
    xs = list(range(min(c, w))) + list(range(max(0, w - c), w))
    for y in ys:
        for x in xs:
            off = (y * w + x) * 4
            cantos.append((raw[off], raw[off + 1], raw[off + 2]))
    bg_r = statistics.median(p[0] for p in cantos)
    bg_g = statistics.median(p[1] for p in cantos)
    bg_b = statistics.median(p[2] for p in cantos)
    dists_cantos = sorted(
        ((p[0] - bg_r) ** 2 + (p[1] - bg_g) ** 2 + (p[2] - bg_b) ** 2) ** 0.5
        for p in cantos
    )
    spread = dists_cantos[min(len(dists_cantos) - 1, int(0.9 * (len(dists_cantos) - 1)))]
    if spread >= 20.0:
        return [1] * (w * h)

    limiar2 = 14.0 * 14.0

    def _eh_bg(idx: int) -> bool:
        off = idx * 4
        dr = raw[off] - bg_r
        dg = raw[off + 1] - bg_g
        db = raw[off + 2] - bg_b
        return (dr * dr + dg * dg + db * db) < limiar2

    bg = bytearray(w * h)
    fila: deque[int] = deque()
    for x in range(w):
        for y in (0, h - 1):
            idx = y * w + x
            if not bg[idx] and _eh_bg(idx):
                bg[idx] = 1
                fila.append(idx)
    for y in range(h):
        for x in (0, w - 1):
            idx = y * w + x
            if not bg[idx] and _eh_bg(idx):
                bg[idx] = 1
                fila.append(idx)

    while fila:
        idx = fila.popleft()
        cx = idx % w
        cy = idx // w
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
    local_max = cv2.dilate(l_contraste_u8, kernel, borderType=cv2.BORDER_REPLICATE).astype(np.float32)
    local_min = cv2.erode(l_contraste_u8, kernel, borderType=cv2.BORDER_REPLICATE).astype(np.float32)
    local_range = local_max - local_min
    local_range_g = cv2.dilate(
        l_contraste_u8, kernel_g, borderType=cv2.BORDER_REPLICATE
    ).astype(np.float32) - cv2.erode(
        l_contraste_u8, kernel_g, borderType=cv2.BORDER_REPLICATE
    ).astype(np.float32)

    prata = (s_u8 < 42.0) & (local_min >= 52.0) & (
        ((l_f32 >= 95.0) & (l_f32 <= 240.0) & (local_range >= 42.0) & (local_max >= 175.0))
        | ((l_f32 >= 95.0) & (l_f32 <= 232.0) & (cool_diff >= 4) & (local_range_g >= 2.0))
        | ((s_u8 < 25.0) & (l_f32 >= 160.0) & (l_f32 <= 186.0) & (cool_diff >= 4) & (neutral_rg <= 2))
    )
    gunmetal = (s_u8 < 42.0) & (l_f32 >= 55.0) & (l_f32 < 95.0) & (local_min >= 48.0) & (
        ((local_max >= 115.0) & (local_range >= 32.0)) | ((cool_diff >= 4) & (local_range_g >= 2.0))
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
    metal = (prata | gunmetal | ouro | bronze) & fg

    metallic = np.zeros((h, w), dtype=np.uint8)
    metallic[metal] = np.clip(np.rint(205.0 + (l_f32 - 95.0) * 0.14), 198.0, 230.0).astype(np.uint8)[metal]
    metallic[gunmetal & fg] = np.clip(np.rint(195.0 + (l_f32 - 50.0) * 0.35), 192.0, 218.0).astype(np.uint8)[gunmetal & fg]
    metallic[bronze & fg] = 208
    metallic[ouro & fg] = 218

    roughness = np.full((h, w), 209, dtype=np.uint8)
    roughness[fg] = np.clip(np.rint(218.0 - 0.12 * v_u8), 185.0, 224.0).astype(np.uint8)[fg]
    roughness[fg & (~metal) & (s_u8 < 55.0) & (v_u8 >= 160.0) & (local_min >= 145.0)] = 160
    roughness[fg & (~metal) & (s_u8 >= 65.0) & (v_u8 >= 55.0) & (local_range >= 22.0)] = 158
    roughness[fg & (~metal) & (h_deg >= 1.5) & (h_deg <= 42.0) & (s_u8 >= 30.0) & (s_u8 <= 195.0) & (v_u8 >= 30.0) & (v_u8 <= 240.0)] = 140
    roughness[metal] = np.clip(np.rint(95.0 - (l_f32 / 255.0) * 26.0), 64.0, 97.0).astype(np.uint8)[metal]
    roughness[bronze & fg] = np.clip(np.rint(102.0 - (l_f32 / 255.0) * 28.0), 64.0, 105.0).astype(np.uint8)[bronze & fg]
    roughness[gunmetal & fg] = np.clip(np.rint(112.0 - (l_f32 / 255.0) * 32.0), 72.0, 115.0).astype(np.uint8)[gunmetal & fg]

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
        if eh_ouro:
            metallic[idx] = 218
            roughness[idx] = max(64, min(97, round(95.0 - (l_u8 / 255.0) * 26.0)))
        elif eh_bronze:
            metallic[idx] = 208
            roughness[idx] = max(64, min(105, round(102.0 - (l_u8 / 255.0) * 28.0)))
        elif eh_prata:
            metallic[idx] = max(198, min(230, round(205.0 + (l_u8 - 95.0) * 0.14)))
            roughness[idx] = max(64, min(97, round(95.0 - (l_u8 / 255.0) * 26.0)))
        elif eh_gunmetal:
            metallic[idx] = max(192, min(218, round(195.0 + (l_u8 - 50.0) * 0.35)))
            roughness[idx] = max(72, min(115, round(112.0 - (l_u8 / 255.0) * 32.0)))
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

    seed = fg & (
        ((v_u8 >= 250.0) & (s_u8 >= 140.0))
        | ((v_u8 >= 225.0) & (s_u8 >= 210.0) & ((h_deg < 20.0) | (h_deg > 50.0)))
    )
    cand_branco = fg & (v_u8 >= 250.0)
    ativo = seed.copy()
    if np.any(seed) and np.any(cand_branco & (~seed)):
        n_labels, labels = cv2.connectedComponents((seed | cand_branco).astype(np.uint8), connectivity=4)
        if n_labels > 1:
            seed_labels = np.unique(labels[seed])
            seed_labels = seed_labels[seed_labels > 0]
            if len(seed_labels) > 0:
                ativo = np.isin(labels, seed_labels)

    emissive = np.zeros(rgb.shape[:2], dtype=np.uint8)
    valores = np.clip(
        np.rint(180.0 + np.maximum(0.0, v_u8 - 235.0) * 3.75), 180.0, 255.0
    ).astype(np.uint8)
    emissive[ativo] = valores[ativo]
    return Image.fromarray(emissive, mode="L")


def _emissive_pil(rgba: Image.Image) -> Image.Image:
    rgba_conv = rgba.convert("RGBA")
    w, h = rgba_conv.size
    fg_mask = _mascara_foreground_pil(rgba_conv)
    raw = rgba_conv.tobytes()
    seed = bytearray(w * h)
    branco = bytearray(w * h)
    v_vals = [0.0] * (w * h)
    fila: deque[int] = deque()

    for idx in range(w * h):
        if not fg_mask[idx]:
            continue
        off = idx * 4
        r, g, b = raw[off], raw[off + 1], raw[off + 2]
        h_f, s_f, v_f = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
        h_deg = h_f * 360.0
        s_u8 = s_f * 255.0
        v_u8 = v_f * 255.0
        v_vals[idx] = v_u8
        if (v_u8 >= 250.0 and s_u8 >= 140.0) or (
            v_u8 >= 225.0 and s_u8 >= 210.0 and (h_deg < 20.0 or h_deg > 50.0)
        ):
            seed[idx] = 1
            fila.append(idx)
        elif v_u8 >= 250.0:
            branco[idx] = 1

    ativo = bytearray(seed)
    while fila:
        idx = fila.popleft()
        cx = idx % w
        cy = idx // w
        for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
            if 0 <= nx < w and 0 <= ny < h:
                n = ny * w + nx
                if branco[n] and not ativo[n]:
                    ativo[n] = 1
                    fila.append(n)

    out = bytearray(w * h)
    for idx in range(w * h):
        if ativo[idx]:
            out[idx] = max(180, min(255, round(180.0 + max(0.0, v_vals[idx] - 235.0) * 3.75)))
    return Image.frombytes("L", (w, h), bytes(out))


def extrair_emissive(img_rgba: Image.Image) -> Image.Image:
    """Extrai mascara ``emissive`` em ``L`` para regioes brilhantes e saturadas."""
    if _TEM_CV2:
        return _emissive_cv2(img_rgba)
    return _emissive_pil(img_rgba)
