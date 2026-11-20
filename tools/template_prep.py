"""Prepara foto frontal para o template MPFB2: recorte alfa, bleed amplo, delight e marcos faciais.

Executado na venv de imagem (`venv-i23d`) por subprocesso; nunca importado no nucleo/Blender.
"""
from __future__ import annotations

import argparse
import json
import sys
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

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import delight  # noqa: E402
import delight_pbr  # noqa: E402
import i23d_infer  # noqa: E402


def _bleed_telea_cv2(rgba: Image.Image) -> Image.Image:
    """Inpainting amplo fora do nucleo opaco via OpenCV TELEA."""
    arr = np.array(rgba.convert("RGBA"))
    alfa = arr[:, :, 3]
    bgr = cv2.cvtColor(arr[:, :, :3], cv2.COLOR_RGB2BGR)
    mask = ((alfa < 200).astype(np.uint8)) * 255
    mask = cv2.dilate(mask, np.ones((3, 3), np.uint8))
    peq_bgr = cv2.resize(bgr, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
    peq_m = cv2.resize(mask, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_NEAREST)
    inp = cv2.inpaint(peq_bgr, peq_m, 9, cv2.INPAINT_TELEA)
    cheio = cv2.resize(inp, (bgr.shape[1], bgr.shape[0]), interpolation=cv2.INTER_LINEAR)
    bgr[mask > 0] = cheio[mask > 0]
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    out = np.dstack([rgb, alfa])
    return Image.fromarray(out, mode="RGBA")


def _bleed_telea_pil(rgba: Image.Image) -> Image.Image:
    """Fallback Pillow puro para bleed fora do nucleo opaco."""
    conv = rgba.convert("RGBA")
    w, h = conv.size
    a_ch = conv.getchannel("A")
    a_min, a_max = a_ch.getextrema()
    if a_min >= 200 or a_max < 200:
        return conv

    core_orig = a_ch.point(lambda a: 255 if a >= 200 else 0)
    core_mask = core_orig.filter(ImageFilter.MinFilter(3))
    if core_mask.getextrema()[1] == 0:
        core_mask = core_orig

    pw, ph = max(1, w // 2), max(1, h // 2)
    rgb_orig = conv.convert("RGB")
    peq_rgb = rgb_orig.resize((pw, ph), Image.Resampling.BOX)
    peq_core = core_mask.resize((pw, ph), Image.Resampling.NEAREST)
    orig_bytes = peq_rgb.tobytes()
    core_bytes = peq_core.tobytes()
    n_peq = pw * ph

    core_idx = [i for i in range(n_peq) if core_bytes[i] > 0]
    if not core_idx:
        return conv
    mr = sum(orig_bytes[i * 3] for i in core_idx) // len(core_idx)
    mg = sum(orig_bytes[i * 3 + 1] for i in core_idx) // len(core_idx)
    mb = sum(orig_bytes[i * 3 + 2] for i in core_idx) // len(core_idx)

    work_r = bytearray(orig_bytes[i * 3] if core_bytes[i] > 0 else 0 for i in range(n_peq))
    work_g = bytearray(orig_bytes[i * 3 + 1] if core_bytes[i] > 0 else 0 for i in range(n_peq))
    work_b = bytearray(orig_bytes[i * 3 + 2] if core_bytes[i] > 0 else 0 for i in range(n_peq))
    work_w = bytearray(255 if core_bytes[i] > 0 else 0 for i in range(n_peq))

    for passo in range(3):
        br = Image.frombytes("L", (pw, ph), bytes(work_r)).filter(ImageFilter.BoxBlur(5)).tobytes()
        bg = Image.frombytes("L", (pw, ph), bytes(work_g)).filter(ImageFilter.BoxBlur(5)).tobytes()
        bb = Image.frombytes("L", (pw, ph), bytes(work_b)).filter(ImageFilter.BoxBlur(5)).tobytes()
        bw = Image.frombytes("L", (pw, ph), bytes(work_w)).filter(ImageFilter.BoxBlur(5)).tobytes()
        for i in range(n_peq):
            if core_bytes[i] > 0:
                work_r[i] = orig_bytes[i * 3]
                work_g[i] = orig_bytes[i * 3 + 1]
                work_b[i] = orig_bytes[i * 3 + 2]
                work_w[i] = 255
            elif bw[i] > 0:
                work_r[i] = min(255, round(br[i] * 255.0 / bw[i]))
                work_g[i] = min(255, round(bg[i] * 255.0 / bw[i]))
                work_b[i] = min(255, round(bb[i] * 255.0 / bw[i]))
                work_w[i] = 255
            elif passo == 2:
                work_r[i], work_g[i], work_b[i], work_w[i] = mr, mg, mb, 255

    bleed_peq = Image.merge(
        "RGB",
        (
            Image.frombytes("L", (pw, ph), bytes(work_r)),
            Image.frombytes("L", (pw, ph), bytes(work_g)),
            Image.frombytes("L", (pw, ph), bytes(work_b)),
        ),
    )
    cheia_rgb = bleed_peq.resize((w, h), Image.Resampling.BILINEAR)
    out_rgba = Image.composite(rgb_orig, cheia_rgb, core_mask).convert("RGBA")
    out_rgba.putalpha(a_ch)
    return out_rgba


def _bleed_telea(rgba: Image.Image) -> Image.Image:
    """Inpainting amplo fora do nucleo opaco para evitar borda cinza/preta na projecao UV."""
    if _TEM_CV2:
        return _bleed_telea_cv2(rgba)
    return _bleed_telea_pil(rgba)


def _detectar_marcos_faciais_cv2(rgba: Image.Image) -> dict[str, float]:
    arr = np.array(rgba.convert("RGBA"))
    fg = arr[:, :, 3] > 128
    ys, _ = np.where(fg)
    if len(ys) == 0:
        return {}
    y0, y1 = int(ys.min()), int(ys.max())
    altura = max(1, y1 - y0)
    cinza = cv2.cvtColor(arr[:, :, :3], cv2.COLOR_RGB2GRAY)

    # Faixa dos olhos: ~4.5%..9.5% abaixo do topo; boca: ~9%..13.5%
    r0_e, r1_e = y0 + int(0.045 * altura), y0 + int(0.095 * altura)
    r0_b, r1_b = y0 + int(0.090 * altura), y0 + int(0.138 * altura)
    cols_cab = np.where(fg[r0_e:r1_b, :].any(axis=0))[0]
    if len(cols_cab) == 0:
        return {}
    xc = int(cols_cab.mean())
    lx0, lx1 = max(0, xc - 28), min(arr.shape[1], xc + 28)

    band_e = cinza[r0_e:r1_e, lx0:lx1]
    eye_row = r0_e + int(band_e.mean(axis=1).argmin()) if band_e.size else r0_e

    # Boca tem R-G mais elevado no centro + sulco escuro dos labios
    sub_b = arr[r0_b:r1_b, max(0, xc - 20):min(arr.shape[1], xc + 20)]
    if sub_b.size:
        rg = sub_b[:, :, 0].astype(np.float32) - sub_b[:, :, 1].astype(np.float32)
        escuro = 255.0 - cinza[r0_b:r1_b, max(0, xc - 20):min(arr.shape[1], xc + 20)].astype(np.float32)
        score = rg.mean(axis=1) * 1.4 + escuro.mean(axis=1) * 0.4
        mouth_row = r0_b + int(score.argmax())
    else:
        mouth_row = r0_b

    olhos_frac = round(float(y1 - eye_row) / altura, 4)
    boca_frac = round(float(y1 - mouth_row) / altura, 4)
    if not (0.80 < boca_frac < olhos_frac < 0.98):
        return {}
    return {"olhos_frac": olhos_frac, "boca_frac": boca_frac}


def _detectar_marcos_faciais_pil(rgba: Image.Image) -> dict[str, float]:
    conv = rgba.convert("RGBA")
    w, h = conv.size
    raw = conv.tobytes()
    gray = conv.convert("L").tobytes()
    ys = [
        y
        for y in range(h)
        if any(raw[(y * w + x) * 4 + 3] > 128 for x in range(w))
    ]
    if not ys:
        return {}
    y0, y1 = ys[0], ys[-1]
    altura = max(1, y1 - y0)

    r0_e, r1_e = y0 + int(0.045 * altura), y0 + int(0.095 * altura)
    r0_b, r1_b = y0 + int(0.090 * altura), y0 + int(0.138 * altura)
    cols_cab = [
        x
        for x in range(w)
        if any(raw[(y * w + x) * 4 + 3] > 128 for y in range(max(0, r0_e), min(h, r1_b)))
    ]
    if not cols_cab:
        return {}
    xc = int(sum(cols_cab) / len(cols_cab))
    lx0, lx1 = max(0, xc - 28), min(w, xc + 28)

    if r1_e > r0_e and lx1 > lx0:
        row_means = [
            sum(gray[y * w + x] for x in range(lx0, lx1)) / float(lx1 - lx0)
            for y in range(max(0, r0_e), min(h, r1_e))
        ]
        eye_row = max(0, r0_e) + (min(range(len(row_means)), key=lambda i: row_means[i]) if row_means else 0)
    else:
        eye_row = r0_e

    bx0, bx1 = max(0, xc - 20), min(w, xc + 20)
    if r1_b > r0_b and bx1 > bx0:
        scores: list[float] = []
        span_x = float(bx1 - bx0)
        for y in range(max(0, r0_b), min(h, r1_b)):
            rg_sum = 0.0
            dark_sum = 0.0
            for x in range(bx0, bx1):
                off = (y * w + x) * 4
                rg_sum += float(raw[off] - raw[off + 1])
                dark_sum += 255.0 - float(gray[y * w + x])
            scores.append((rg_sum / span_x) * 1.4 + (dark_sum / span_x) * 0.4)
        mouth_row = max(0, r0_b) + (max(range(len(scores)), key=lambda i: scores[i]) if scores else 0)
    else:
        mouth_row = r0_b

    olhos_frac = round(float(y1 - eye_row) / altura, 4)
    boca_frac = round(float(y1 - mouth_row) / altura, 4)
    if not (0.80 < boca_frac < olhos_frac < 0.98):
        return {}
    return {"olhos_frac": olhos_frac, "boca_frac": boca_frac}


def detectar_marcos_faciais(rgba: Image.Image) -> dict[str, float]:
    """Estima fracoes verticais de olhos e boca medidas da base (0=pe, 1=topo) da silhueta."""
    if _TEM_CV2:
        return _detectar_marcos_faciais_cv2(rgba)
    return _detectar_marcos_faciais_pil(rgba)


def _resize_foreground_pil(rgba: Image.Image, ratio: float) -> Image.Image:
    bbox = rgba.getchannel("A").getbbox()
    if bbox is None:
        return rgba
    cropped = rgba.crop(bbox)
    cw, ch = cropped.size
    new_size = max(1, round(max(cw, ch) / max(0.05, float(ratio))))
    canvas = Image.new("RGBA", (new_size, new_size), (0, 0, 0, 0))
    canvas.paste(cropped, ((new_size - cw) // 2, (new_size - ch) // 2))
    return canvas


def _preparar_imagem_pil(
    caminho: str,
    remover_fundo: bool,
    foreground_ratio: float,
    rembg_info: dict[str, Any] | None = None,
) -> Image.Image:
    imagem = Image.open(caminho).convert("RGBA")
    if max(imagem.size) > 1024:
        fator = 1024.0 / float(max(imagem.size))
        novo_tam = (max(1, round(imagem.width * fator)), max(1, round(imagem.height * fator)))
        imagem = imagem.resize(novo_tam, Image.Resampling.LANCZOS)
    if remover_fundo:
        fg_mask = delight_pbr._mascara_foreground_pil(imagem)
        raw = bytearray(imagem.tobytes())
        for i, fg in enumerate(fg_mask):
            if not fg:
                raw[i * 4 + 3] = 0
        recortada = Image.frombytes("RGBA", imagem.size, bytes(raw))
        recortada = _resize_foreground_pil(recortada, foreground_ratio)
        if rembg_info is not None:
            rembg_info["rembg_modelo"] = "pil_fallback"
            rembg_info["rembg_fallback"] = True
        return i23d_infer._gerar_cutout_para_textura(recortada, desmultiplicar=False)
    if rembg_info is not None:
        rembg_info["rembg_modelo"] = None
        rembg_info["rembg_fallback"] = False
    return i23d_infer._gerar_cutout_para_textura(imagem, desmultiplicar=False)


def main() -> int:
    ap = argparse.ArgumentParser(description="Prepara foto frontal para MPFB2")
    ap.add_argument("--imagem", required=True)
    ap.add_argument("--saida-dir", required=True)
    ap.add_argument("--resultado", required=True)
    ap.add_argument("--remover-fundo", action="store_true")
    ap.add_argument("--rembg-modelo", default=None)
    ap.add_argument("--delight", action="store_true")
    args = ap.parse_args()

    saida = Path(args.saida_dir).expanduser().resolve()
    saida.mkdir(parents=True, exist_ok=True)

    rembg_info: dict[str, Any] = {}
    rgba_holder: list[Image.Image] = []
    try:
        i23d_infer._preparar_imagem(
            args.imagem,
            remover_fundo=args.remover_fundo,
            foreground_ratio=0.85,
            rembg_modelo=args.rembg_modelo,
            rembg_info=rembg_info,
            rgba_textura_out=rgba_holder,
        )
        rgba = rgba_holder[0]
    except (ImportError, OSError, RuntimeError, ValueError, LookupError) as exc:
        print(
            f"[template_prep] aviso fallback Pillow em _preparar_imagem: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        rgba = _preparar_imagem_pil(
            args.imagem,
            remover_fundo=args.remover_fundo,
            foreground_ratio=0.85,
            rembg_info=rembg_info,
        )
    rgba.save(saida / "input_rgba.png")

    foto_bleed = _bleed_telea(rgba)
    tex_path = saida / "input_template.png"
    delight_meta: dict = {"executado": False}
    if args.delight:
        dl = delight.delight_imagem(foto_bleed)
        dl.save(tex_path)
        met, rough = delight.estimar_mapas_pbr(dl)
        met.save(saida / "metallic_hint.png")
        rough.save(saida / "roughness_hint.png")
        delight_meta = {"executado": True}
    else:
        foto_bleed.save(tex_path)

    marcos = detectar_marcos_faciais(foto_bleed)
    res = {
        "ok": True,
        "foto_template": str(tex_path),
        "marcos": marcos,
        "delight": delight_meta,
        **rembg_info,
    }
    Path(args.resultado).write_text(json.dumps(res, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
