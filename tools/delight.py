"""Delighting leve (Retinex/Bilateral em LAB) e heuristicas PBR (Setup Onda 2).

Roda em CPU (0 VRAM, < 100 ms) via CLI (canal JSON em disco, I9) ou API Python.
Usa ``cv2`` + ``numpy`` + ``PIL`` nas venvs de inferencia, com fallback Pillow puro.
"""

from __future__ import annotations

import argparse
import colorsys
import json
import statistics
import time
import traceback
from collections import deque
from pathlib import Path
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


def _salvar(caminho: str | Path, obj: dict[str, Any]) -> None:
    destino = Path(caminho)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(
        json.dumps(obj, sort_keys=True, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _mascara_foreground_cv2(arr: Any) -> Any:
    """Detecta foreground mesmo em imagem opaca sobre fundo neutro uniforme."""
    alpha = arr[:, :, 3]
    fg = alpha >= 24
    if int(alpha.min()) < 250:
        return fg

    rgb = arr[:, :, :3]
    h, w = rgb.shape[:2]
    c = max(2, min(8, min(h, w) // 16))
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
    raw = rgba.tobytes()
    alphas = raw[3::4]
    if min(alphas) < 250:
        return [1 if a >= 24 else 0 for a in alphas]

    c = max(2, min(8, min(w, h) // 16))
    cantos: list[tuple[int, int, int]] = []
    for y in list(range(c)) + list(range(max(0, h - c), h)):
        for x in list(range(c)) + list(range(max(0, w - c), w)):
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
        if cx > 0:
            n = idx - 1
            if not bg[n] and _eh_bg(n):
                bg[n] = 1
                fila.append(n)
        if cx + 1 < w:
            n = idx + 1
            if not bg[n] and _eh_bg(n):
                bg[n] = 1
                fila.append(n)
        if cy > 0:
            n = idx - w
            if not bg[n] and _eh_bg(n):
                bg[n] = 1
                fila.append(n)
        if cy + 1 < h:
            n = idx + w
            if not bg[n] and _eh_bg(n):
                bg[n] = 1
                fila.append(n)

    return [0 if bg[i] else 1 for i in range(w * h)]


def _delight_cv2(rgba: Image.Image) -> Image.Image:
    arr = np.array(rgba.convert("RGBA"))
    rgb = arr[:, :, :3].copy()
    alpha = arr[:, :, 3]
    fg_mask = _mascara_foreground_cv2(arr)

    # Preenche fundo com a cor media do objeto para nao vazar borda no blur.
    if np.any(fg_mask) and not np.all(fg_mask):
        media_rgb = np.mean(rgb[fg_mask], axis=0).astype(np.uint8)
        rgb_preenchido = rgb.copy()
        rgb_preenchido[~fg_mask] = media_rgb
    else:
        rgb_preenchido = rgb

    lab = cv2.cvtColor(rgb_preenchido, cv2.COLOR_RGB2LAB).astype(np.float32)
    l_chan = lab[:, :, 0]
    a_chan = lab[:, :, 1]
    b_chan = lab[:, :, 2]

    h, w = l_chan.shape
    sigma = max(6.0, min(h, w) * 0.08)
    l_u8 = np.clip(l_chan, 0, 255).astype(np.uint8)
    iluminacao_bilat = cv2.bilateralFilter(l_u8, d=11, sigmaColor=42, sigmaSpace=24).astype(
        np.float32
    )
    iluminacao_gauss = cv2.GaussianBlur(l_chan, (0, 0), sigmaX=sigma, sigmaY=sigma)
    iluminacao = 0.45 * iluminacao_bilat + 0.55 * iluminacao_gauss

    l_fg = l_chan[fg_mask] if np.any(fg_mask) else l_chan
    l_ref = float(np.clip(np.median(l_fg), 90.0, 170.0))

    razao = np.clip(l_ref / np.maximum(iluminacao, 12.0), 0.82, 1.55)
    l_retinex = l_chan * razao

    # Supressao de picos especulares sem lavar tons medios nem inventar brilho no tecido fosco.
    excesso = np.maximum(0.0, l_chan - 200.0)
    l_retinex = np.where(l_chan > 200.0, l_retinex - 0.65 * excesso, l_retinex)

    fator_blend = np.where(l_chan < l_ref, 0.62, 0.42)
    l_out = (1.0 - fator_blend) * l_chan + fator_blend * l_retinex
    l_out = np.where(l_chan > 200.0, np.minimum(l_out, l_chan - 0.65 * excesso), l_out)

    # Supressao leve de saturacao em zonas especulares muito claras (evita brilho colorido estourado).
    fator_croma = np.where(l_chan > 220.0, 0.88, 1.0)
    a_out = 128.0 + (a_chan - 128.0) * fator_croma
    b_out = 128.0 + (b_chan - 128.0) * fator_croma

    lab_out = np.stack(
        [
            np.clip(l_out, 0, 255),
            np.clip(a_out, 0, 255),
            np.clip(b_out, 0, 255),
        ],
        axis=2,
    ).astype(np.uint8)
    rgb_out = cv2.cvtColor(lab_out, cv2.COLOR_LAB2RGB)
    # Preserva RGB original fora do foreground quando transparente e mantem alfa intacto.
    if np.any(~fg_mask):
        rgb_out[~fg_mask] = rgb[~fg_mask]
    saida = np.dstack([rgb_out, alpha])
    return Image.fromarray(saida, mode="RGBA")


def _delight_pil(rgba: Image.Image) -> Image.Image:
    rgba_conv = rgba.convert("RGBA")
    w, h = rgba_conv.size
    alfa = rgba_conv.getchannel("A")
    fg_mask = _mascara_foreground_pil(rgba_conv)
    ycbcr = rgba_conv.convert("RGB").convert("YCbCr")
    y_img, cb_img, cr_img = ycbcr.split()

    raio = max(3, min(w, h) // 16)
    ilum_img = y_img.filter(ImageFilter.GaussianBlur(radius=raio))

    y_bytes = y_img.tobytes()
    ilum_bytes = ilum_img.tobytes()
    cb_bytes = cb_img.tobytes()
    cr_bytes = cr_img.tobytes()

    fg_ys = [y for y, fg in zip(y_bytes, fg_mask) if fg] or list(y_bytes)
    fg_ys_sorted = sorted(fg_ys)
    l_ref = max(90.0, min(170.0, float(fg_ys_sorted[len(fg_ys_sorted) // 2])))

    y_out = bytearray(len(y_bytes))
    cb_out = bytearray(cb_bytes)
    cr_out = bytearray(cr_bytes)
    for i, (yv, iv, fg) in enumerate(zip(y_bytes, ilum_bytes, fg_mask)):
        if not fg:
            y_out[i] = yv
            continue
        razao = max(0.82, min(1.55, l_ref / max(float(iv), 12.0)))
        l_ret = yv * razao
        excesso = max(0.0, yv - 190.0)
        if yv > 190:
            l_ret -= 0.70 * excesso
            cb_out[i] = max(0, min(255, round(128 + (cb_bytes[i] - 128) * 0.88)))
            cr_out[i] = max(0, min(255, round(128 + (cr_bytes[i] - 128) * 0.88)))
        peso = 0.62 if yv < l_ref else 0.42
        l_val = (1.0 - peso) * yv + peso * l_ret
        if yv > 190:
            l_val = min(l_val, yv - 0.70 * excesso)
        y_out[i] = max(0, min(255, round(l_val)))

    rgb_out = Image.merge(
        "YCbCr",
        (
            Image.frombytes("L", (w, h), bytes(y_out)),
            Image.frombytes("L", (w, h), bytes(cb_out)),
            Image.frombytes("L", (w, h), bytes(cr_out)),
        ),
    ).convert("RGB")
    r_ch, g_ch, b_ch = rgb_out.split()
    return Image.merge("RGBA", (r_ch, g_ch, b_ch, alfa))


def delight_imagem(img_rgba: Image.Image) -> Image.Image:
    """Suaviza luz/sombra assada em LAB preservando o canal alfa intacto."""
    if _TEM_CV2:
        return _delight_cv2(img_rgba)
    return _delight_pil(img_rgba)


def _mapas_pbr_cv2(rgba: Image.Image) -> tuple[Image.Image, Image.Image]:
    arr = np.array(rgba.convert("RGBA"))
    rgb = arr[:, :, :3]
    fg = _mascara_foreground_cv2(arr)

    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)
    h_deg = hsv[:, :, 0].astype(np.float32) * 2.0
    s_hsv = hsv[:, :, 1]
    v_hsv = hsv[:, :, 2]
    l_lab = lab[:, :, 0]

    # Estende luminancia da borda do foreground para fora, evitando falso contraste contra fundo cinza.
    h, w = l_lab.shape
    k = max(5, min(11, (min(h, w) // 48) | 1))
    l_f32 = l_lab.astype(np.float32)
    if np.any(fg) and not np.all(fg):
        fg_f = fg.astype(np.float32)
        soma_l = cv2.boxFilter(l_f32 * fg_f, -1, (k, k), normalize=False)
        soma_w = cv2.boxFilter(fg_f, -1, (k, k), normalize=False)
        l_ext = np.where(soma_w > 1e-4, soma_l / np.maximum(soma_w, 1e-4), l_f32)
        l_contraste = np.where(fg, l_f32, l_ext)
    else:
        l_contraste = l_f32
    l_contraste_u8 = np.clip(l_contraste, 0, 255).astype(np.uint8)

    gx = cv2.Sobel(l_contraste, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(l_contraste, cv2.CV_32F, 0, 1, ksize=3)
    grad = np.hypot(gx, gy)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    local_max = cv2.dilate(l_contraste_u8, kernel).astype(np.float32)
    local_min = cv2.erode(l_contraste_u8, kernel).astype(np.float32)
    local_range = local_max - local_min
    grad_local = cv2.dilate(grad, kernel)
    contraste_forte = ((local_range >= 42.0) & (local_max >= 180.0)) | (
        (grad_local >= 60.0) & (local_max >= 175.0)
    )

    prata = (
        (s_hsv < 45)
        & (l_lab >= 95)
        & (l_lab <= 240)
        & (local_min >= 80.0)
        & contraste_forte
    )
    gunmetal = (
        (s_hsv < 55)
        & (l_lab >= 50)
        & (l_lab < 95)
        & (local_min >= 45.0)
        & (local_max >= 95.0)
        & (local_range >= 18.0)
    )
    ouro = (h_deg >= 28.0) & (h_deg <= 52.0) & (s_hsv >= 75) & (s_hsv <= 210) & (v_hsv > 125)
    bronze = (
        (h_deg >= 12.0)
        & (h_deg < 28.0)
        & (s_hsv >= 85)
        & (s_hsv <= 230)
        & (v_hsv >= 100)
        & (local_range >= 18.0)
    )
    metal = (prata | gunmetal | ouro | bronze) & fg

    metallic = np.zeros((h, w), dtype=np.uint8)
    # 210..245 em metal; 0 no restante.
    metal_val = np.clip(222.0 + (l_f32 - 95.0) * 0.14, 220.0, 245.0).astype(np.uint8)
    metallic[metal] = metal_val[metal]
    gun_val = np.clip(212.0 + (l_f32 - 50.0) * 0.45, 210.0, 235.0).astype(np.uint8)
    metallic[gunmetal & fg] = gun_val[gunmetal & fg]
    metallic[bronze & fg] = 225
    metallic[ouro & fg] = 235

    # Roughness: metal ~0.25..0.42, pele/couro ~0.55, pano/cabelo ~0.82.
    roughness = np.full((h, w), 209, dtype=np.uint8)  # 0.82 * 255
    couro_pele = (
        fg
        & (~metal)
        & (h_deg >= 4.0)
        & (h_deg <= 42.0)
        & (s_hsv >= 30)
        & (s_hsv <= 195)
        & (v_hsv >= 45)
    )
    roughness[couro_pele] = 140  # ~0.55
    metal_rough = np.clip(95.0 - (l_f32 / 255.0) * 26.0, 64.0, 97.0).astype(np.uint8)
    roughness[metal] = metal_rough[metal]
    bronze_rough = np.clip(102.0 - (l_f32 / 255.0) * 28.0, 64.0, 105.0).astype(np.uint8)
    roughness[bronze & fg] = bronze_rough[bronze & fg]
    gun_rough = np.clip(112.0 - (l_f32 / 255.0) * 32.0, 72.0, 115.0).astype(np.uint8)
    roughness[gunmetal & fg] = gun_rough[gunmetal & fg]

    return Image.fromarray(metallic, mode="L"), Image.fromarray(roughness, mode="L")


def _mapas_pbr_pil(rgba: Image.Image) -> tuple[Image.Image, Image.Image]:
    rgba_conv = rgba.convert("RGBA")
    w, h = rgba_conv.size
    fg_mask = _mascara_foreground_pil(rgba_conv)
    l_img = rgba_conv.convert("L")
    l_bytes = l_img.tobytes()
    raw = rgba_conv.tobytes()

    k = max(5, min(11, (min(w, h) // 48) | 1))
    # Extende luminancia da borda do foreground para fora via BoxBlur normalizado (evita halo na borda).
    if any(fg_mask) and not all(fg_mask):
        r_ext = max(3, k)
        fg_u8 = Image.frombytes("L", (w, h), bytes(255 if f else 0 for f in fg_mask))
        lf_u8 = Image.frombytes(
            "L", (w, h), bytes(l_bytes[i] if fg_mask[i] else 0 for i in range(w * h))
        )
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

    metallic = bytearray(w * h)
    roughness = bytearray([209] * (w * h))

    for idx in range(w * h):
        if not fg_mask[idx]:
            continue
        off = idx * 4
        r, g, b = raw[off], raw[off + 1], raw[off + 2]
        h_f, s_f, v_f = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
        h_deg = h_f * 360.0
        s_u8 = s_f * 255.0
        v_u8 = v_f * 255.0
        l_u8 = l_bytes[idx]
        contraste = (l_max[idx] - l_min[idx]) >= 18

        eh_prata = s_u8 < 45 and 95 <= l_u8 <= 240 and l_min[idx] >= 80 and contraste
        eh_gunmetal = (
            s_u8 < 55 and 50 <= l_u8 < 95 and l_min[idx] >= 45 and l_max[idx] >= 95 and contraste
        )
        eh_ouro = 28.0 <= h_deg <= 52.0 and 75 <= s_u8 <= 210 and v_u8 > 125
        eh_bronze = 12.0 <= h_deg < 28.0 and 85 <= s_u8 <= 230 and v_u8 >= 100 and contraste
        if eh_ouro:
            metallic[idx] = 235
            roughness[idx] = max(64, min(97, round(95.0 - (l_u8 / 255.0) * 26.0)))
        elif eh_bronze:
            metallic[idx] = 225
            roughness[idx] = max(64, min(105, round(102.0 - (l_u8 / 255.0) * 28.0)))
        elif eh_prata:
            metallic[idx] = max(220, min(245, round(222.0 + (l_u8 - 95.0) * 0.14)))
            roughness[idx] = max(64, min(97, round(95.0 - (l_u8 / 255.0) * 26.0)))
        elif eh_gunmetal:
            metallic[idx] = max(210, min(235, round(212.0 + (l_u8 - 50.0) * 0.45)))
            roughness[idx] = max(72, min(115, round(112.0 - (l_u8 / 255.0) * 32.0)))
        elif 4.0 <= h_deg <= 42.0 and 30 <= s_u8 <= 195 and v_u8 >= 45:
            roughness[idx] = 140

    return (
        Image.frombytes("L", (w, h), bytes(metallic)),
        Image.frombytes("L", (w, h), bytes(roughness)),
    )


def estimar_mapas_pbr(img_rgba: Image.Image) -> tuple[Image.Image, Image.Image]:
    """Gera mascaras ``(metallic, roughness)`` em ``L`` para o bake Camera UV."""
    if _TEM_CV2:
        return _mapas_pbr_cv2(img_rgba)
    return _mapas_pbr_pil(img_rgba)


def _args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Forge3D Delight + PBR Hints — canal JSON")
    p.add_argument("--imagem", required=True)
    p.add_argument("--saida-albedo", default="")
    p.add_argument("--saida-metallic", default="")
    p.add_argument("--saida-roughness", default="")
    p.add_argument("--resultado", default="")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _args(argv)
    resultado: dict[str, Any] = {
        "ok": False,
        "imagem": str(Path(args.imagem).expanduser()),
        "backend": "cv2+numpy" if _TEM_CV2 else "pillow",
    }
    t0 = time.monotonic()
    try:
        caminho = Path(args.imagem)
        if not caminho.is_file():
            raise FileNotFoundError(f"imagem nao encontrada: {caminho}")
        with Image.open(caminho) as img:
            rgba = img.convert("RGBA")

        if args.saida_albedo:
            albedo = delight_imagem(rgba)
            destino_albedo = Path(args.saida_albedo)
            destino_albedo.parent.mkdir(parents=True, exist_ok=True)
            albedo.save(destino_albedo, format="PNG")
            resultado["saida_albedo"] = str(destino_albedo)

        if args.saida_metallic or args.saida_roughness:
            metallic, roughness = estimar_mapas_pbr(rgba)
            if args.saida_metallic:
                destino_m = Path(args.saida_metallic)
                destino_m.parent.mkdir(parents=True, exist_ok=True)
                metallic.save(destino_m, format="PNG")
                resultado["saida_metallic"] = str(destino_m)
            if args.saida_roughness:
                destino_r = Path(args.saida_roughness)
                destino_r.parent.mkdir(parents=True, exist_ok=True)
                roughness.save(destino_r, format="PNG")
                resultado["saida_roughness"] = str(destino_r)

            m_bytes = metallic.tobytes()
            resultado["metallic_ratio"] = round(
                sum(1 for v in m_bytes if v > 128) / max(len(m_bytes), 1), 4
            )

        resultado["ok"] = True
        resultado["tempo_ms"] = round((time.monotonic() - t0) * 1000.0, 2)
        return 0
    except Exception as exc:  # noqa: BLE001 - erro vai para JSON (I9)
        resultado.update(
            {
                "ok": False,
                "erro": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(limit=8),
            }
        )
        return 1
    finally:
        if args.resultado:
            _salvar(args.resultado, resultado)


if __name__ == "__main__":
    raise SystemExit(main())
