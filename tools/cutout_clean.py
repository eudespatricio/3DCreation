"""Limpeza de halo semitransparente, bleed RGB 8-vizinhos e sessao rembg otimizada."""

from __future__ import annotations

import inspect
import math
import os
import statistics
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageFilter, ImageOps

try:  # noqa: SIM105 - opcional no nucleo .venv sem numpy/cv2
    import cv2  # type: ignore[import-not-found]
    import numpy as np  # type: ignore[import-not-found]

    _TEM_CV2 = True
except ImportError:
    cv2, np, _TEM_CV2 = None, None, False

_VIZINHOS_8 = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, 1), (1, -1), (-1, -1))


def onnx_tem_cuda() -> bool:
    """Retorna True se ``onnxruntime`` expuser ``CUDAExecutionProvider``."""
    try:
        import onnxruntime as ort  # type: ignore[import-not-found]

        return "CUDAExecutionProvider" in ort.get_available_providers()
    except ImportError:
        return False
    except (AttributeError, RuntimeError, OSError) as exc:
        sys.stderr.write(f"[cutout_clean] aviso ao sondar CUDA no onnxruntime: {exc}\n")
        return False


def modelo_rembg_padrao_cpu() -> str:
    """Escolhe modelo rembg respeitando env e evitando BiRefNet pesado em CPU."""
    env = os.environ.get("FORGE3D_REMBG_MODELO", "").strip()
    if env:
        return env
    dev = os.environ.get("FORGE3D_I23D_DEVICE", os.environ.get("FORGE3D_DEVICE", "")).strip().lower()
    if dev.startswith("cpu") or not onnx_tem_cuda():
        return "u2net"
    u2net_home = Path(os.environ.get("U2NET_HOME", str(Path.home() / ".u2net"))).expanduser()
    return "birefnet-general-lite" if (u2net_home / "birefnet-general-lite.onnx").is_file() else "birefnet-general"


def criar_sessao_rembg_otimizada(rembg_mod: Any, modelo: str) -> Any:
    """Cria sessao rembg injetando ``SessionOptions`` apenas quando aceito pela assinatura."""
    opts: Any = None
    try:
        import onnxruntime as ort  # type: ignore[import-not-found]

        opts = ort.SessionOptions()
        opts.intra_op_num_threads, opts.inter_op_num_threads = min(8, os.cpu_count() or 4), 1
        if hasattr(ort, "GraphOptimizationLevel"):
            opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    except ImportError:
        opts = None
    except (AttributeError, RuntimeError, OSError, ValueError) as exc:
        sys.stderr.write(f"[cutout_clean] aviso onnxruntime SessionOptions indisponivel: {exc}\n")
    if opts is not None:
        try:
            if "sess_opts" in inspect.signature(rembg_mod.new_session).parameters:
                return rembg_mod.new_session(modelo, sess_opts=opts)
        except (TypeError, ValueError) as exc:
            sys.stderr.write(f"[cutout_clean] aviso assinatura rembg.new_session: {exc}\n")
    return rembg_mod.new_session(modelo)


def estimar_cor_fundo_borda(rgba_orig: Image.Image) -> tuple[float, float, float]:
    """Estima RGB mediano do fundo pelas bordas (ou anel translucido quando borda tem alfa=0)."""
    rgba = rgba_orig.convert("RGBA")
    w, h = rgba.size
    if w <= 0 or h <= 0:
        return (128.0, 128.0, 128.0)
    raw = rgba.tobytes()
    bordas = (*(y * w + x for x in range(w) for y in (0, h - 1)), *(y * w + x for y in range(h) for x in (0, w - 1)))
    amostras = [(raw[i * 4], raw[i * 4 + 1], raw[i * 4 + 2]) for i in bordas if raw[i * 4 + 3] >= 16]
    if not amostras:
        amostras = [(raw[o], raw[o + 1], raw[o + 2]) for o in range(0, len(raw), 4) if 16 <= raw[o + 3] < 128]
    if not amostras:
        return (128.0, 128.0, 128.0)
    return tuple(float(statistics.median(p[c] for p in amostras)) for c in (0, 1, 2))  # type: ignore[return-value]


def _sangrar_rgb_alfa_zero(rgba: Image.Image, bleed_px: int) -> Image.Image:
    if bleed_px <= 0:
        return rgba
    if _TEM_CV2:
        arr = np.array(rgba.convert("RGBA"))
        alpha = arr[:, :, 3]
        valid = alpha > 0
        if not np.any(valid) or np.all(valid):
            return rgba
        rgb_f = np.where(valid[:, :, None], arr[:, :, :3].astype(np.float32), 0.0)
        valid_f = valid.astype(np.float32)
        for _ in range(bleed_px):
            w_sum = cv2.boxFilter(valid_f, -1, (3, 3), normalize=False, borderType=cv2.BORDER_CONSTANT)
            novos = (~valid) & (w_sum > 0.5)
            if not np.any(novos):
                break
            c_sum = cv2.boxFilter(rgb_f * valid_f[:, :, None], -1, (3, 3), normalize=False, borderType=cv2.BORDER_CONSTANT)
            rgb_f[novos] = np.rint(c_sum[novos] / w_sum[novos, None])
            valid[novos], valid_f[novos] = True, 1.0
        return Image.fromarray(np.dstack([np.clip(rgb_f, 0, 255).astype(np.uint8), alpha]), mode="RGBA")

    w, h = rgba.size
    r_ch, g_ch, b_ch, a_ch = rgba.convert("RGBA").split()
    cur_val = a_ch.point(lambda a: 255 if a > 0 else 0)
    if cur_val.getextrema() in ((0, 0), (255, 255)):
        return rgba
    cur_rgb = Image.composite(Image.merge("RGB", (r_ch, g_ch, b_ch)), Image.new("RGB", (w, h), (0, 0, 0)), cur_val)
    for _ in range(bleed_px):
        if cur_val.getextrema()[0] == 255:
            break
        base_rgb, base_val = cur_rgb.copy(), cur_val.copy()
        for dx, dy in _VIZINHOS_8:
            sh_val = Image.new("L", (w, h), 0)
            sh_val.paste(base_val, (dx, dy))
            sh_rgb = Image.new("RGB", (w, h), (0, 0, 0))
            sh_rgb.paste(base_rgb, (dx, dy))
            cur_rgb.paste(sh_rgb, (0, 0), ImageChops.darker(ImageOps.invert(cur_val), sh_val))
            cur_val = ImageChops.lighter(cur_val, sh_val)
    return Image.merge("RGBA", (*cur_rgb.split(), a_ch))


def limpar_halo_e_sangrar_rgb(
    recorte: Image.Image, bg_rgb: Sequence[float], *, usou_rembg: bool = False, alpha_corte: int = 160, bleed_px: int = 6,
) -> Image.Image:
    """Descontamina borda, binariza alfa em {0, 255}, erode 1px seguro e sangra RGB em alfa=0."""
    rgba = recorte.convert("RGBA")
    bg_r, bg_g, bg_b = float(bg_rgb[0]), float(bg_rgb[1]), float(bg_rgb[2])
    if _TEM_CV2:
        arr = np.array(rgba)
        rgb, a = arr[:, :, :3].astype(np.float32), arr[:, :, 3]
        semi = (a >= alpha_corte) & (a < 255)
        if np.any(semi):
            af = np.maximum(a[semi].astype(np.float32) / 255.0, 0.25)[:, None]
            rgb[semi] = np.clip(np.rint((rgb[semi] - (1.0 - af) * np.array([[bg_r, bg_g, bg_b]], dtype=np.float32)) / af), 0.0, 255.0)
        a_bin = np.where(a >= alpha_corte, np.uint8(255), np.uint8(0))
        ys, xs = np.nonzero(a_bin)
        if usou_rembg and len(xs) > 0 and min(int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)) >= 64:
            a_er = cv2.erode(a_bin, np.ones((3, 3), dtype=np.uint8), iterations=1)
            if int(np.count_nonzero(a_er)) >= 0.85 * int(np.count_nonzero(a_bin)):
                a_bin = a_er
        rgb[a_bin == 0] = 0.0
        limpo = Image.fromarray(np.dstack([rgb.astype(np.uint8), a_bin]), mode="RGBA")
    else:
        raw = bytearray(rgba.tobytes())
        for i in range(0, len(raw), 4):
            a_v = raw[i + 3]
            if a_v < alpha_corte:
                raw[i : i + 4] = b"\x00\x00\x00\x00"
            elif a_v < 255:
                af = max(a_v / 255.0, 0.25)
                raw[i] = max(0, min(255, round((raw[i] - (1.0 - af) * bg_r) / af)))
                raw[i + 1] = max(0, min(255, round((raw[i + 1] - (1.0 - af) * bg_g) / af)))
                raw[i + 2] = max(0, min(255, round((raw[i + 2] - (1.0 - af) * bg_b) / af)))
                raw[i + 3] = 255
        limpo = Image.frombytes("RGBA", rgba.size, bytes(raw))
        bbox = limpo.getchannel("A").getbbox()
        if usou_rembg and bbox and min(bbox[2] - bbox[0], bbox[3] - bbox[1]) >= 64:
            a_ch = limpo.getchannel("A")
            a_er = a_ch.filter(ImageFilter.MinFilter(3))
            if sum(1 for v in a_er.tobytes() if v >= 160) >= 0.85 * max(sum(1 for v in a_ch.tobytes() if v >= 160), 1):
                limpo.putalpha(a_er)
    return _sangrar_rgb_alfa_zero(limpo, bleed_px)


def recortar_com_margem_segura(recorte: Image.Image, *, margem_frac: float = 0.12) -> Image.Image:
    """Recorta com margem proporcional, expandindo canvas quando >= 256px para ``area_fg <= 0.65``."""
    bbox = recorte.getchannel("A").getbbox()
    if not bbox:
        return recorte
    x0, y0, x1, y1 = bbox
    bw, bh = x1 - x0, y1 - y0
    m_dim = max(bw, bh)
    if m_dim < 256:
        pad = max(2, min(8, int(round(m_dim * 0.06))))
        return recorte.crop((max(0, x0 - pad), max(0, y0 - pad), min(recorte.width, x1 + pad), min(recorte.height, y1 + pad)))
    pad = max(8, int(round(m_dim * margem_frac)))
    out_w, out_h = bw + 2 * pad, bh + 2 * pad
    area_min = math.ceil(sum(1 for a in recorte.getchannel("A").tobytes() if a >= 160) / 0.645)
    if out_w * out_h < area_min:
        esc = math.sqrt(area_min / float(max(out_w * out_h, 1)))
        ew, eh = max(2, int(math.ceil(out_w * (esc - 1.0)))), max(2, int(math.ceil(out_h * (esc - 1.0))))
        out_w, out_h = out_w + ew + (ew % 2), out_h + eh + (eh % 2)
    dx, dy = (out_w - bw) // 2, (out_h - bh) // 2
    sx0, sy0 = max(0, x0 - dx), max(0, y0 - dy)
    sx1, sy1 = min(recorte.width, x1 + (out_w - dx - bw)), min(recorte.height, y1 + (out_h - dy - bh))
    canvas = Image.new("RGBA", (out_w, out_h), (0, 0, 0, 0))
    canvas.paste(recorte.crop((sx0, sy0, sx1, sy1)), (dx - (x0 - sx0), dy - (y0 - sy0)))
    if x0 < 6 or y0 < 6 or x1 > recorte.width - 6 or y1 > recorte.height - 6:
        canvas = _sangrar_rgb_alfa_zero(canvas, 6)
    return canvas
