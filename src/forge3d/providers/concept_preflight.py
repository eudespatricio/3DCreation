"""Preflight geometrico 2D e auto-padding WDDM pre-GPU (stdlib + Pillow apenas, D26)."""

from __future__ import annotations

import math
import os
import statistics
from collections import deque
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageOps

from ..errors import erro_provider_run

MAX_FG_FILL_WDDM, TARGET_FG_FILL_WDDM, MIN_FG_FILL = 0.72, 0.60, 0.015
MIN_ASPECT_PREFLIGHT, MAX_ASPECT_PREFLIGHT, MIN_DIM_LINT_PADRAO = 0.25, 4.0, 128
_PARTES_ISENTAS_ASPECT = frozenset({"arma", "escudo", "lanca", "bastao", "cajado", "espada", "cabo"})
_VIZINHOS_4 = ((1, 0), (-1, 0), (0, 1), (0, -1))


def _carregar_rgba(imagem: str | Path | Image.Image) -> Image.Image:
    if isinstance(imagem, Image.Image):
        return imagem.convert("RGBA")
    with Image.open(Path(imagem)) as img:
        return img.convert("RGBA")


def _percentil(valores: list[float], p: float) -> float:
    if not valores:
        return 0.0
    ord_v = sorted(valores)
    pos = (len(ord_v) - 1) * max(0.0, min(1.0, p))
    lo, hi = int(pos), min(len(ord_v) - 1, int(pos) + 1)
    return ord_v[lo] * (1.0 - (pos - lo)) + ord_v[hi] * (pos - lo)


def _extrair_mascara_e_lum(rgba: Image.Image, min_dim_lint: int) -> tuple[list[bool], list[float], bytes, bool]:
    w, h = rgba.size
    n = w * h
    if n <= 0:
        return [], [], b"", False
    raw = rgba.tobytes()
    alphas = raw[3::4]
    lums = [(raw[i * 4] * 299 + raw[i * 4 + 1] * 587 + raw[i * 4 + 2] * 114) / 1000.0 for i in range(n)]
    if min(alphas) < 250:
        return [a >= 24 for a in alphas], lums, alphas, True

    bordas = [*(y * w + x for x in range(w) for y in (0, h - 1)), *(y * w + x for y in range(h) for x in (0, w - 1))]
    bg_r, bg_g, bg_b = (statistics.median(raw[i * 4 + c] for i in bordas) for c in (0, 1, 2))
    dists_b = [((raw[i * 4] - bg_r) ** 2 + (raw[i * 4 + 1] - bg_g) ** 2 + (raw[i * 4 + 2] - bg_b) ** 2) ** 0.5 for i in bordas]
    p90_b = _percentil(dists_b, 0.90)
    if p90_b >= 28.0:
        return [True] * n, lums, alphas, False

    lim2 = max(18.0, p90_b + 10.0) ** 2
    bg = bytearray(n)
    fila: deque[int] = deque()
    for idx in bordas:
        o = idx * 4
        if not bg[idx] and (raw[o] - bg_r) ** 2 + (raw[o + 1] - bg_g) ** 2 + (raw[o + 2] - bg_b) ** 2 < lim2:
            bg[idx] = 1
            fila.append(idx)
    while fila:
        idx = fila.popleft()
        cx, cy = idx % w, idx // w
        for dx, dy in _VIZINHOS_4:
            nx, ny = cx + dx, cy + dy
            if 0 <= nx < w and 0 <= ny < h:
                ni, no = ny * w + nx, (ny * w + nx) * 4
                if not bg[ni] and (raw[no] - bg_r) ** 2 + (raw[no + 1] - bg_g) ** 2 + (raw[no + 2] - bg_b) ** 2 < lim2:
                    bg[ni] = 1
                    fila.append(ni)

    fg = [not bool(bg[i]) for i in range(n)]
    if not any(fg) and min(w, h) < min_dim_lint:
        return [True] * n, lums, alphas, False
    return fg, lums, alphas, False


def avaliar_concept_2d(
    imagem: str | Path | Image.Image, *, item: dict[str, Any] | None = None, min_dim_lint: int = MIN_DIM_LINT_PADRAO,
) -> dict[str, Any]:
    """Avalia silhueta, aspecto, icone 2D chapado e vista 45-deg de topo suspeita."""
    rgba = _carregar_rgba(imagem)
    w, h = rgba.size
    fg, lums, alphas, tem_alfa = _extrair_mascara_e_lum(rgba, min_dim_lint)
    fg_idxs = [i for i, v in enumerate(fg) if v]
    fg_count = len(fg_idxs)
    fg_fill = fg_count / float(max(w * h, 1))
    lint_aplicado = min(w, h) >= int(min_dim_lint)

    item_d = item or {}
    parte = str(item_d.get("parte") or "").strip().lower()
    rota = str(item_d.get("rota") or "").strip().lower()
    isento_aspect = bool(item_d.get("extrudir_2d") is True) or rota == "extrude_2d" or parte in _PARTES_ISENTAS_ASPECT

    erros: list[str] = []
    avisos: list[str] = []
    if fg_count == 0 or w == 0 or h == 0 or (lint_aplicado and fg_fill < MIN_FG_FILL):
        erros.append("silhueta_vazia")

    if fg_count > 0:
        xs, ys = [i % w for i in fg_idxs], [i // w for i in fg_idxs]
        x0, x1, y0, y1 = min(xs), max(xs) + 1, min(ys), max(ys) + 1
        bw, bh = max(1, x1 - x0), max(1, y1 - y0)
        aspect, bbox_fill = bw / float(bh), fg_count / float(bw * bh)
    else:
        xs, ys = [], []
        x0 = y0 = x1 = y1 = bw = bh = 0
        aspect = bbox_fill = 0.0

    std_lum_fg, grad_interno_p90, com_y_eff, top_down_score = 0.0, 0.0, 0.5, 0.0
    if lint_aplicado and fg_count > 0 and not erros:
        if (aspect < MIN_ASPECT_PREFLIGHT or aspect > MAX_ASPECT_PREFLIGHT) and not isento_aspect:
            erros.append("aspecto_extremo")

        fg_lums = [lums[i] for i in fg_idxs]
        std_lum_fg = statistics.pstdev(fg_lums) if len(fg_lums) >= 2 else 0.0
        a_lim = 200 if (not tem_alfa or max(alphas) >= 220) else 24
        grads = [
            math.hypot(lums[idx + 1] - lums[idx], lums[idx + w] - lums[idx])
            for idx in fg_idxs
            if (idx % w) + 1 < w and (idx // w) + 1 < h and fg[idx + 1] and fg[idx + w]
            and alphas[idx] >= a_lim and alphas[idx + 1] >= a_lim and alphas[idx + w] >= a_lim
        ]
        grad_interno_p90 = _percentil(grads, 0.90)
        if bbox_fill >= 0.92 and std_lum_fg < 10.0 and grad_interno_p90 < 8.0:
            erros.append("icone_2d_plano")

        mean_y = sum(ys) / float(fg_count)
        com_y_eff = max((mean_y - y0) / float(max(bh - 1, 1)), mean_y / float(max(h - 1, 1)))
        topo_lums: list[float] = []
        base_lums: list[float] = []
        base_escuras = 0
        spans_topo: list[float] = []
        spans_base: list[float] = []
        for ry in range(y0, y1):
            r_xs = [rx for rx in range(x0, x1) if fg[ry * w + rx]]
            if not r_xs:
                continue
            norm_ry = (ry - y0) / float(max(bh - 1, 1))
            span_r = float(r_xs[-1] - r_xs[0] + 1)
            if norm_ry < 0.72:
                spans_topo.append(span_r)
                topo_lums.extend(lums[ry * w + rx] for rx in r_xs)
            elif norm_ry >= 0.76:
                spans_base.append(span_r)
                for rx in r_xs:
                    pi = ry * w + rx
                    lv = lums[pi]
                    base_lums.append(lv)
                    if lv < 85.0 or (tem_alfa and alphas[pi] < 220 and lv < 110.0):
                        base_escuras += 1

        lum_topo = (sum(topo_lums) / len(topo_lums)) if topo_lums else 128.0
        lum_base = (sum(base_lums) / len(base_lums)) if base_lums else lum_topo
        queda_lum = max(0.0, lum_topo - lum_base)
        frac_escura = base_escuras / float(max(len(base_lums), 1))
        tem_sombra = (queda_lum >= 20.0 and frac_escura >= 0.25) or (frac_escura >= 0.45 and lum_topo >= 80.0)
        s_com = max(0.0, min(1.0, (com_y_eff - 0.50) / 0.18))
        s_shd = max(min(1.0, queda_lum / 40.0), frac_escura)
        s_wide = min(1.0, (_percentil(spans_base, 0.85) / max(_percentil(spans_topo, 0.85), 1.0)) * 0.75)
        top_down_score = round(0.45 * s_com + 0.40 * s_shd + 0.15 * s_wide, 4)
        if tem_sombra and com_y_eff > 0.64 and top_down_score >= 0.72:
            avisos.append("vista_topo_45_suspeita")

    ok = len(erros) == 0
    return {
        "ok": ok, "aprovado": ok, "largura": w, "altura": h,
        "fg_fill": round(fg_fill, 4), "bbox_fill": round(bbox_fill, 4),
        "aspect": round(aspect, 4), "aspecto": round(aspect, 4),
        "std_lum_fg": round(std_lum_fg, 3), "grad_interno_p90": round(grad_interno_p90, 3),
        "com_y": round(com_y_eff, 4), "top_down_score": top_down_score,
        "lint_aplicado": lint_aplicado, "isento_aspect": isento_aspect,
        "erros": erros, "falhas": list(erros), "motivos": list(erros), "avisos": avisos,
    }


def aplicar_auto_pad_wddm(
    imagem: str | Path | Image.Image, destino_png: str | Path, *, fg_fill: float | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Expande o canvas transparente quando ``fg_fill > 0.72`` para ``fg_fill_pos <= 0.65``."""
    rgba = _carregar_rgba(imagem)
    w, h = rgba.size
    fg, _lums, _alphas, tem_alfa = _extrair_mascara_e_lum(rgba, MIN_DIM_LINT_PADRAO)
    fill_atual = float(fg_fill) if fg_fill is not None else (sum(1 for v in fg if v) / float(max(w * h, 1)))
    dst = Path(destino_png)
    if dst.is_dir() or dst.suffix.lower() != ".png":
        dst = dst / "input_preflight_pad.png"

    if fill_atual <= MAX_FG_FILL_WDDM or w <= 0 or h <= 0:
        if isinstance(imagem, Image.Image):
            dst.parent.mkdir(parents=True, exist_ok=True)
            rgba.save(dst, format="PNG")
        caminho_ret = dst if isinstance(imagem, Image.Image) else Path(imagem)
        return caminho_ret, {"auto_padded": False, "fg_fill_antes": round(fill_atual, 4), "fg_fill_pos": round(fill_atual, 4), "largura": w, "altura": h}

    if not tem_alfa and any(not v for v in fg):
        raw = bytearray(rgba.tobytes())
        for i, eh_fg in enumerate(fg):
            if not eh_fg:
                raw[i * 4 : i * 4 + 4] = b"\x00\x00\x00\x00"
        rgba = Image.frombytes("RGBA", (w, h), bytes(raw))

    esc = math.sqrt(fill_atual / TARGET_FG_FILL_WDDM)
    ew, eh = max(4, int(math.ceil(w * (esc - 1.0)))), max(4, int(math.ceil(h * (esc - 1.0))))
    new_w, new_h = w + ew + (ew % 2), h + eh + (eh % 2)
    canvas = Image.new("RGBA", (new_w, new_h), (0, 0, 0, 0))
    canvas.paste(rgba, ((new_w - w) // 2, (new_h - h) // 2))
    r_ch, g_ch, b_ch, a_ch = canvas.split()
    val = a_ch.point(lambda a: 255 if a >= 24 else 0)
    rgb_c = Image.composite(Image.merge("RGB", (r_ch, g_ch, b_ch)), Image.new("RGB", (new_w, new_h), (0, 0, 0)), val)
    for _ in range(2):
        b_rgb, b_val = rgb_c.copy(), val.copy()
        for dx, dy in _VIZINHOS_4:
            sv, sr = Image.new("L", (new_w, new_h), 0), Image.new("RGB", (new_w, new_h), (0, 0, 0))
            sv.paste(b_val, (dx, dy))
            sr.paste(b_rgb, (dx, dy))
            rgb_c.paste(sr, (0, 0), ImageChops.darker(ImageOps.invert(val), sv))
            val = ImageChops.lighter(val, sv)
    dst.parent.mkdir(parents=True, exist_ok=True)
    Image.merge("RGBA", (*rgb_c.split(), a_ch)).save(dst, format="PNG")
    fill_pos = (fill_atual * (w * h)) / float(max(new_w * new_h, 1))
    return dst, {"auto_padded": True, "fg_fill_antes": round(fill_atual, 4), "fg_fill_pos": round(fill_pos, 4), "largura": new_w, "altura": new_h}


def validar_e_preparar_concept_2d(
    imagem: str | Path | Image.Image, destino: str | Path, item: dict[str, Any] | None = None,
    *, env: dict[str, str] | None = None, min_dim_lint: int = MIN_DIM_LINT_PADRAO,
) -> tuple[Path, dict[str, Any]]:
    """Valida preflight 2D pre-GPU (fail-fast) e aplica auto-pad WDDM quando necessario."""
    env_map = env if env is not None else os.environ
    flag_env = str(env_map.get("FORGE3D_PREFLIGHT_2D", "1")).strip().lower()
    dst_base = Path(destino)
    dst_png = dst_base if dst_base.suffix.lower() == ".png" else (dst_base / "input_preflight_pad.png")
    if (item or {}).get("preflight_2d") is False or flag_env in ("0", "false", "nao", "off"):
        if isinstance(imagem, Image.Image):
            dst_png.parent.mkdir(parents=True, exist_ok=True)
            imagem.convert("RGBA").save(dst_png, format="PNG")
        return (dst_png if isinstance(imagem, Image.Image) else Path(imagem)), {"ok": True, "ativo": False, "auto_padded": False, "erros": [], "falhas": [], "avisos": []}
    rel = avaliar_concept_2d(imagem, item=item, min_dim_lint=min_dim_lint)
    rel["ativo"] = True
    if not rel["ok"]:
        raise erro_provider_run(f"preflight 2D reprovou concept ({', '.join(rel['erros'])})", id=(item or {}).get("id"), erros=rel["erros"], preflight_2d=rel)
    rgba = _carregar_rgba(imagem)
    if not rel["lint_aplicado"] and min(rgba.getchannel("A").tobytes()) >= 250:
        if isinstance(imagem, Image.Image):
            dst_png.parent.mkdir(parents=True, exist_ok=True)
            rgba.save(dst_png, format="PNG")
        return (dst_png if isinstance(imagem, Image.Image) else Path(imagem)), {**rel, "auto_padded": False, "fg_fill_antes": rel["fg_fill"], "fg_fill_pos": rel["fg_fill"]}
    out_path, pad_info = aplicar_auto_pad_wddm(imagem, dst_png, fg_fill=float(rel["fg_fill"]))
    return out_path, {**rel, **pad_info}
