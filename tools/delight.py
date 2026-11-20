"""Delighting leve (Retinex/Bilateral em LAB) e heuristicas PBR (Setup Onda 2).

Roda em CPU (0 VRAM, < 100 ms) via CLI (canal JSON em disco, I9) ou API Python.
Usa ``cv2`` + ``numpy`` + ``PIL`` nas venvs de inferencia, com fallback Pillow puro.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path
from typing import Any

from PIL import Image, ImageFilter

_TOOLS_DIR = str(Path(__file__).resolve().parent)
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

from delight_pbr import (  # noqa: E402
    _TEM_CV2,
    _emissive_cv2,
    _emissive_pil,
    _mapas_pbr_cv2,
    _mapas_pbr_pil,
    _mascara_foreground_cv2,
    _mascara_foreground_pil,
    cv2,
    estimar_mapas_pbr,
    extrair_emissive,
    np,
)

__all__ = [
    "_TEM_CV2",
    "_delight_cv2",
    "_delight_pil",
    "_emissive_cv2",
    "_emissive_pil",
    "_mapas_pbr_cv2",
    "_mapas_pbr_pil",
    "_mascara_foreground_cv2",
    "_mascara_foreground_pil",
    "delight_imagem",
    "estimar_mapas_pbr",
    "extrair_emissive",
    "main",
]


def _salvar(caminho: str | Path, obj: dict[str, Any]) -> None:
    destino = Path(caminho)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(
        json.dumps(obj, sort_keys=True, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


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


def _args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Forge3D Delight + PBR Hints — canal JSON")
    p.add_argument("--imagem", required=True)
    p.add_argument("--saida-albedo", default="")
    p.add_argument("--saida-metallic", default="")
    p.add_argument("--saida-roughness", default="")
    p.add_argument("--saida-emissive", default="")
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

        if args.saida_emissive:
            emissive = extrair_emissive(rgba)
            destino_e = Path(args.saida_emissive)
            destino_e.parent.mkdir(parents=True, exist_ok=True)
            emissive.save(destino_e, format="PNG")
            resultado["saida_emissive"] = str(destino_e)
            e_bytes = emissive.tobytes()
            resultado["emissive_ratio"] = round(
                sum(1 for v in e_bytes if v > 128) / max(len(e_bytes), 1), 4
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
        print(json.dumps(resultado, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    raise SystemExit(main())
