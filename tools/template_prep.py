"""Prepara foto frontal para o template MPFB2: recorte alfa, bleed amplo, delight e marcos faciais.

Executado na venv de imagem (`venv-i23d`) por subprocesso; nunca importado no nucleo/Blender.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import delight  # noqa: E402
import i23d_infer  # noqa: E402


def _bleed_telea(rgba: Image.Image) -> Image.Image:
    """Inpainting amplo fora do nucleo opaco para evitar borda cinza/preta na projecao UV."""
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


def detectar_marcos_faciais(rgba: Image.Image) -> dict[str, float]:
    """Estima fracoes verticais de olhos e boca medidas da base (0=pe, 1=topo) da silhueta."""
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

    rembg_info: dict = {}
    rgba_holder: list[Image.Image] = []
    i23d_infer._preparar_imagem(
        args.imagem,
        remover_fundo=args.remover_fundo,
        foreground_ratio=0.85,
        rembg_modelo=args.rembg_modelo,
        rembg_info=rembg_info,
        rgba_textura_out=rgba_holder,
    )
    rgba = rgba_holder[0]
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
