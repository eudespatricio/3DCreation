"""Pose Guard e decomposicao 2D de silhuetas (Setup Onda 2 / Onda 3).

Roda via CLI (canal JSON em disco, I9) dentro de ``venv-i23d`` ou ``venv-concept``
com ``cv2`` + ``numpy`` + ``PIL``, e tambem funciona com fallback Pillow puro em CPU.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import traceback
from collections import deque
from pathlib import Path
from typing import Any

from PIL import Image

_TOOLS_DIR = str(Path(__file__).resolve().parent)
if _TOOLS_DIR not in sys.path:
    sys.path.insert(0, _TOOLS_DIR)

from cutout_clean import (  # noqa: E402
    criar_sessao_rembg_otimizada,
    estimar_cor_fundo_borda,
    limpar_halo_e_sangrar_rgb,
    modelo_rembg_padrao_cpu,
    recortar_com_margem_segura,
)

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


def _limpar_mascara_cv2(mask_u8: Any) -> Any:
    """Remove componentes pequenos e preenche buracos minusculos na mascara binaria."""
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    limpa = cv2.morphologyEx(mask_u8, cv2.MORPH_CLOSE, kernel, iterations=1)
    n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(limpa, connectivity=8)
    if n_labels <= 1:
        return limpa
    areas = stats[1:, cv2.CC_STAT_AREA]
    maior = int(areas.max()) if len(areas) else 0
    if maior == 0:
        return np.zeros_like(limpa)
    min_area = max(16, int(maior * 0.015))
    saida = np.zeros_like(limpa)
    for idx in range(1, n_labels):
        if int(stats[idx, cv2.CC_STAT_AREA]) >= min_area:
            saida[labels == idx] = 255
    return saida


def _mascara_foreground_cv2(rgba_img: Image.Image) -> tuple[Any, str]:
    """Calcula mascara binaria uint8 (0 ou 255) com OpenCV + numpy."""
    arr = np.array(rgba_img.convert("RGBA"))
    alpha = arr[:, :, 3]
    if int(alpha.min()) < 250:
        return _limpar_mascara_cv2(np.where(alpha >= 24, np.uint8(255), np.uint8(0))), "alpha"

    rgb = arr[:, :, :3]
    h, w = rgb.shape[:2]
    borda = np.concatenate([rgb[0, :], rgb[-1, :], rgb[:, 0], rgb[:, -1]], axis=0).astype(np.float32)
    bg = np.median(borda, axis=0)
    limiar = max(20.0, float(np.percentile(np.linalg.norm(borda - bg, axis=1), 90)) + 12.0)
    mask = np.where(np.linalg.norm(rgb.astype(np.float32) - bg, axis=2) > limiar, np.uint8(255), np.uint8(0))

    # Se fundo complexo estourar o limiar simples, refina via GrabCut em retangulo interno.
    frac = float(np.count_nonzero(mask)) / max(h * w, 1)
    if (frac < 0.02 or frac > 0.88) and h >= 16 and w >= 16:
        gc_mask = np.zeros((h, w), dtype=np.uint8)
        bgd_model = np.zeros((1, 65), dtype=np.float64)
        fgd_model = np.zeros((1, 65), dtype=np.float64)
        rx0, ry0 = max(1, int(round(w * 0.05))), max(1, int(round(h * 0.03)))
        rw, rh = max(2, int(round(w * 0.90))), max(2, int(round(h * 0.94)))
        if rx0 + rw < w and ry0 + rh < h:
            cv2.grabCut(rgb, gc_mask, (rx0, ry0, rw, rh), bgd_model, fgd_model, 3, cv2.GC_INIT_WITH_RECT)
            gc_fg = np.where((gc_mask == cv2.GC_FGD) | (gc_mask == cv2.GC_PR_FGD), np.uint8(255), np.uint8(0))
            if 0.02 <= float(np.count_nonzero(gc_fg)) / max(h * w, 1) <= 0.92:
                return _limpar_mascara_cv2(gc_fg), "grabcut"

    return _limpar_mascara_cv2(mask), "border_dist"


def _mascara_foreground_pil(rgba_img: Image.Image) -> tuple[list[list[int]], int, int, str]:
    """Fallback em Pillow puro retornando grade 0/1 ``[y][x]``."""
    rgba = rgba_img.convert("RGBA")
    w, h = rgba.size
    px = rgba.tobytes()
    if min(px[3::4]) < 250:
        return [[1 if px[(y * w + x) * 4 + 3] >= 24 else 0 for x in range(w)] for y in range(h)], w, h, "alpha"

    bordas = (*(y * w + x for x in range(w) for y in (0, h - 1)), *(y * w + x for y in range(h) for x in (0, w - 1)))
    amostras = [(px[i * 4], px[i * 4 + 1], px[i * 4 + 2]) for i in bordas]
    bg_r, bg_g, bg_b = (statistics.median(c[k] for c in amostras) for k in (0, 1, 2))
    grade = [
        [
            1 if (px[(y * w + x) * 4] - bg_r) ** 2 + (px[(y * w + x) * 4 + 1] - bg_g) ** 2 + (px[(y * w + x) * 4 + 2] - bg_b) ** 2 > 676.0 else 0
            for x in range(w)
        ]
        for y in range(h)
    ]
    return grade, w, h, "border_dist_pil"


def _manter_maior_componente_pil(grade: list[list[int]], w: int, h: int) -> list[list[int]]:
    visitado = [[False] * w for _ in range(h)]
    componentes: list[list[tuple[int, int]]] = []
    for y in range(h):
        for x in range(w):
            if grade[y][x] and not visitado[y][x]:
                fila = deque([(x, y)])
                visitado[y][x] = True
                comp: list[tuple[int, int]] = []
                while fila:
                    cx, cy = fila.popleft()
                    comp.append((cx, cy))
                    for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
                        if 0 <= nx < w and 0 <= ny < h and grade[ny][nx] and not visitado[ny][nx]:
                            visitado[ny][nx] = True
                            fila.append((nx, ny))
                componentes.append(comp)
    if not componentes:
        return grade
    maior = max(len(c) for c in componentes)
    min_area = max(8, int(maior * 0.02))
    saida = [[0] * w for _ in range(h)]
    for comp in componentes:
        if len(comp) >= min_area:
            for cx, cy in comp:
                saida[cy][cx] = 1
    return saida


def _percentil(valores: list[float], p: float) -> float:
    if not valores:
        return 0.0
    ordenados = sorted(valores)
    pos = (len(ordenados) - 1) * max(0.0, min(1.0, p))
    lo = int(pos)
    hi = min(len(ordenados) - 1, lo + 1)
    frac = pos - lo
    return ordenados[lo] * (1.0 - frac) + ordenados[hi] * frac


def _analisar_perfil_silhueta(linhas_xs: list[list[int]], metodo: str) -> dict[str, Any]:
    """Analisa largura dos ombros e espaco negativo nos flancos (40%..75%)."""
    linhas_fg = [(y, xs) for y, xs in enumerate(linhas_xs) if xs]
    if not linhas_fg:
        return {
            "pose": "arms_down", "razao_flanco": 0.0, "largura_ombros": 0.0,
            "precisa_repose": True, "aspecto": 0.0, "waist_elbow_gap": 0.0,
            "cabeca_ok": False, "simetria_iou": 0.0, "leg_gap_ratio": 0.0,
            "pernas_separadas": False, "apto_rig": False, "score_pose": 0.0,
            "metodo_mascara": metodo,
        }

    y_min, y_max = linhas_fg[0][0], linhas_fg[-1][0]
    fg_h = max(1, y_max - y_min + 1)
    x_min, x_max = min(xs[0] for _, xs in linhas_fg), max(xs[-1] for _, xs in linhas_fg)
    fg_w = max(1, x_max - x_min + 1)
    aspecto = fg_w / fg_h

    upper_spans: list[float] = []
    upper_max_px = 0
    band_40_75_spans: list[float] = []
    band_40_75_fills: list[float] = []
    waist_gap_scores: list[float] = []
    gap_min_px = max(2, int(round(fg_h * 0.018)))

    for y in range(y_min, y_max + 1):
        xs = linhas_xs[y]
        norm_y = (y - y_min) / max(1, fg_h - 1) if fg_h > 1 else 0.5
        span_px, fill_px = (xs[-1] - xs[0] + 1, len(xs)) if xs else (0, 0)
        if 0.16 <= norm_y <= 0.38:
            upper_spans.append(span_px / fg_h)
            upper_max_px = max(upper_max_px, span_px)
        if 0.16 <= norm_y <= 0.60:
            upper_max_px = max(upper_max_px, span_px)
        if 0.40 <= norm_y <= 0.75:
            band_40_75_spans.append(span_px / fg_h)
            band_40_75_fills.append(fill_px / fg_h)
        # Banda cintura/cotovelo (acima da abertura entre pernas): detecta ar entre tronco e bracos.
        if 0.38 <= norm_y <= 0.64:
            tem_gap_real = len(xs) >= 2 and span_px > fill_px and any((b - a - 1) >= gap_min_px for a, b in zip(xs, xs[1:]))
            waist_gap_scores.append(((span_px - fill_px) / max(span_px, 1)) if tem_gap_real else 0.0)

    largura_ombros = _percentil(upper_spans, 0.90) if upper_spans else aspecto
    span_40_75 = _percentil(band_40_75_spans, 0.85) if band_40_75_spans else aspecto
    mean_fill_40_75 = sum(band_40_75_fills) / len(band_40_75_fills) if band_40_75_fills else aspecto
    upper_norm = max(upper_max_px / fg_h, largura_ombros, 1e-6)
    flank_vs_upper = max(0.0, 1.0 - (mean_fill_40_75 / upper_norm))
    waist_elbow_gap = sum(waist_gap_scores) / len(waist_gap_scores) if waist_gap_scores else 0.0
    razao_flanco = max(flank_vs_upper, waist_elbow_gap)

    eh_tpose = largura_ombros >= 0.54 and flank_vs_upper >= 0.30 and aspecto >= 0.50
    eh_apose = (largura_ombros >= 0.45 or span_40_75 >= 0.45) and aspecto >= 0.45 and (waist_elbow_gap >= 0.06 or flank_vs_upper >= 0.32)
    # Silhueta muito estreita ou zero espaco entre tronco e bracos (sem T-pose) => arms_down.
    pose = "arms_down" if (aspecto < 0.44 or (not eh_tpose and waist_elbow_gap < 0.05)) else ("tpose_apose" if (eh_tpose or eh_apose) else "arms_down")

    cabeca_spans: list[float] = []
    leg_total, leg_com_gap, sim_inter, sim_union = 0, 0, 0, 0
    x_mid = (x_min + x_max) / 2.0
    for y in range(y_min, y_max + 1):
        xs = linhas_xs[y]
        if not xs:
            continue
        norm_y = (y - y_min) / max(1, fg_h - 1) if fg_h > 1 else 0.5
        span_px = xs[-1] - xs[0] + 1
        if 0.0 <= norm_y <= 0.14:
            cabeca_spans.append(span_px / fg_h)
        if 0.62 <= norm_y <= 0.96:
            leg_total += 1
            if any((b - a - 1) >= gap_min_px for a, b in zip(xs, xs[1:])):
                leg_com_gap += 1
        orig_set = set(xs)
        mir_set = {round(2.0 * x_mid - x) for x in xs}
        sim_inter += len(orig_set & mir_set)
        sim_union += len(orig_set | mir_set)

    cabeca_w = _percentil(cabeca_spans, 0.90) if cabeca_spans else 0.0
    cabeca_ok = bool(cabeca_spans) and 0.03 <= cabeca_w <= 0.35
    simetria_iou = sim_inter / float(sim_union) if sim_union > 0 else 0.0
    leg_gap_ratio = leg_com_gap / float(leg_total) if leg_total > 0 else 0.0
    pernas_separadas = leg_gap_ratio >= 0.30
    apto_rig = bool(
        pose == "tpose_apose" and cabeca_ok and simetria_iou >= 0.60 and pernas_separadas
    )
    score_pose = (
        0.35 * (1.0 if pose == "tpose_apose" else 0.0)
        + 0.25 * min(1.0, simetria_iou)
        + 0.20 * min(1.0, leg_gap_ratio / 0.5)
        + 0.10 * min(1.0, razao_flanco / 0.35)
        + (0.10 if cabeca_ok else 0.0)
    )

    return {
        "pose": pose, "razao_flanco": round(float(razao_flanco), 4),
        "largura_ombros": round(float(largura_ombros), 4), "precisa_repose": pose == "arms_down",
        "aspecto": round(float(aspecto), 4), "waist_elbow_gap": round(float(waist_elbow_gap), 4),
        "cabeca_ok": cabeca_ok, "simetria_iou": round(float(simetria_iou), 4),
        "leg_gap_ratio": round(float(leg_gap_ratio), 4), "pernas_separadas": pernas_separadas,
        "apto_rig": apto_rig, "score_pose": round(float(score_pose), 4), "metodo_mascara": metodo,
    }


def detectar_pose_imagem(imagem_path: str | Path) -> dict[str, Any]:
    """Classifica imagem frontal em ``tpose_apose`` vs ``arms_down`` pela silhueta."""
    caminho = Path(imagem_path)
    if not caminho.is_file():
        raise FileNotFoundError(f"imagem nao encontrada: {caminho}")

    with Image.open(caminho) as img:
        rgba = img.convert("RGBA")

    if _TEM_CV2:
        mask_u8, metodo = _mascara_foreground_cv2(rgba)
        h, _w = mask_u8.shape
        linhas_xs = [np.flatnonzero(mask_u8[y]).tolist() for y in range(h)]
        return _analisar_perfil_silhueta(linhas_xs, metodo)

    grade, w, h, metodo = _mascara_foreground_pil(rgba)
    grade = _manter_maior_componente_pil(grade, w, h)
    linhas_xs = [[x for x, v in enumerate(grade[y]) if v] for y in range(h)]
    return _analisar_perfil_silhueta(linhas_xs, metodo)


def _recorte_rapido_estudio(rgba: Image.Image, bg_rgb: tuple[float, float, float]) -> Image.Image | None:
    """Flood-fill rapido pelas 4 bordas quando o fundo de estudio e uniforme (opt-in)."""
    if rgba.mode != "RGBA":
        rgba = rgba.convert("RGBA")
    w, h = rgba.size
    if w < 8 or h < 8:
        return None
    raw = bytearray(rgba.tobytes())
    br, bg_g, bb = bg_rgb
    bordas = [*(y * w + x for x in range(w) for y in (0, h - 1)), *(y * w + x for y in range(h) for x in (0, w - 1))]
    dists_b = [((raw[i * 4] - br) ** 2 + (raw[i * 4 + 1] - bg_g) ** 2 + (raw[i * 4 + 2] - bb) ** 2) ** 0.5 for i in bordas]
    p90 = _percentil(dists_b, 0.90)
    if p90 >= 16.0:
        return None
    if _TEM_CV2:
        arr = np.array(rgba)
        cand = (np.linalg.norm(arr[:, :, :3].astype(np.float32) - np.array(bg_rgb, dtype=np.float32), axis=2) < max(18.0, p90 + 8.0)).astype(np.uint8)
        n_lab, labels = cv2.connectedComponents(cand, connectivity=4)
        ids = np.unique(np.concatenate([labels[0, :], labels[-1, :], labels[:, 0], labels[:, -1]])) if n_lab > 1 else np.array([], dtype=np.int32)
        ids = ids[ids > 0]
        if len(ids) == 0:
            return None
        eh_bg = np.isin(labels, ids)
        if not (0.03 <= 1.0 - float(np.count_nonzero(eh_bg)) / float(w * h) <= 0.90):
            return None
        arr[eh_bg] = 0
        return Image.fromarray(arr, mode="RGBA")
    lim2 = max(18.0, p90 + 8.0) ** 2
    bg_m = bytearray(w * h)
    fila: deque[int] = deque()
    for idx in bordas:
        o = idx * 4
        if not bg_m[idx] and (raw[o] - br) ** 2 + (raw[o + 1] - bg_g) ** 2 + (raw[o + 2] - bb) ** 2 < lim2:
            bg_m[idx] = 1
            fila.append(idx)
    while fila:
        idx = fila.popleft()
        cx, cy = idx % w, idx // w
        for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
            if 0 <= nx < w and 0 <= ny < h:
                ni, no = ny * w + nx, (ny * w + nx) * 4
                if not bg_m[ni] and (raw[no] - br) ** 2 + (raw[no + 1] - bg_g) ** 2 + (raw[no + 2] - bb) ** 2 < lim2:
                    bg_m[ni] = 1
                    fila.append(ni)
    if not (0.03 <= 1.0 - sum(bg_m) / float(w * h) <= 0.90):
        return None
    for i, eh in enumerate(bg_m):
        if eh:
            raw[i * 4 : i * 4 + 4] = b"\x00\x00\x00\x00"
    return Image.frombytes("RGBA", (w, h), bytes(raw))


def _remover_ilhas_ruido(recorte: Image.Image) -> Image.Image:
    if _TEM_CV2:
        arr = np.array(recorte)
        lim_a = 160 if int(np.count_nonzero(arr[:, :, 3] >= 160)) > 0 else 24
        fg_limpo = _limpar_mascara_cv2(np.where(arr[:, :, 3] >= lim_a, np.uint8(255), np.uint8(0)))
        if int(np.count_nonzero(fg_limpo)) > 0:
            arr[fg_limpo == 0] = 0
            return Image.fromarray(arr, mode="RGBA")
        return recorte
    w, h = recorte.size
    raw = bytearray(recorte.tobytes())
    lim_a = 160 if any(a >= 160 for a in raw[3::4]) else 24
    grade = [[1 if raw[(y * w + x) * 4 + 3] >= lim_a else 0 for x in range(w)] for y in range(h)]
    grade = _manter_maior_componente_pil(grade, w, h)
    if any(any(row) for row in grade):
        for y in range(h):
            for x in range(w):
                if not grade[y][x]:
                    idx = (y * w + x) * 4
                    raw[idx : idx + 4] = b"\x00\x00\x00\x00"
        return Image.frombytes("RGBA", (w, h), bytes(raw))
    return recorte


def decompor_silhueta_arma(imagem_path: str | Path, saida_png: str | Path) -> dict[str, Any]:
    """Isola recorte RGBA limpo, sem halo semitransparente e com margem segura."""
    caminho = Path(imagem_path)
    if not caminho.is_file():
        raise FileNotFoundError(f"imagem nao encontrada: {caminho}")
    with Image.open(caminho) as img:
        rgba = img.convert("RGBA")

    bg_rgb = estimar_cor_fundo_borda(rgba)
    era_opaca = rgba.getchannel("A").getextrema()[0] >= 250
    metodo, recorte, usou_rembg = "alpha", rgba, False
    rembg_avisos: list[str] = []

    if era_opaca:
        usou_fast = False
        if os.environ.get("FORGE3D_CUTOUT_FAST_STUDIO", "").strip() == "1":
            fast_cut = _recorte_rapido_estudio(rgba, bg_rgb)
            if fast_cut is not None:
                recorte, metodo, usou_fast = fast_cut, "fast_studio", True
        if not usou_fast:
            try:
                import rembg  # type: ignore[import-not-found]

                rembg_modelo = modelo_rembg_padrao_cpu()
                try:
                    sessao = criar_sessao_rembg_otimizada(rembg, rembg_modelo)
                    metodo = f"rembg:{rembg_modelo}"
                except (OSError, RuntimeError, ImportError, LookupError, ValueError) as exc:
                    if rembg_modelo == "u2net" or "No session class found" in str(exc):
                        raise
                    msg_u2 = f"rembg '{rembg_modelo}' falhou ({type(exc).__name__}: {exc}); fallback u2net"
                    rembg_avisos.append(msg_u2)
                    print(f"[pose_guard] aviso {msg_u2}", file=sys.stderr)
                    sessao = criar_sessao_rembg_otimizada(rembg, "u2net")
                    metodo = "rembg:u2net"
                recorte = rembg.remove(rgba, session=sessao).convert("RGBA")
                usou_rembg = True
            except (ImportError, OSError, RuntimeError, LookupError, ValueError, AttributeError) as exc:
                usou_rembg = False
                msg_local = f"rembg indisponivel ({type(exc).__name__}: {exc}); fallback recorte local"
                rembg_avisos.append(msg_local)
                print(f"[pose_guard] aviso {msg_local}", file=sys.stderr)

            if not usou_rembg:
                if _TEM_CV2:
                    mask_u8, m_sub = _mascara_foreground_cv2(rgba)
                    arr = np.array(rgba)
                    arr[:, :, 3] = np.where(mask_u8 > 0, np.uint8(255), np.uint8(0))
                    recorte, metodo = Image.fromarray(arr, mode="RGBA"), m_sub
                else:
                    grade, w, h, m_sub = _mascara_foreground_pil(rgba)
                    grade = _manter_maior_componente_pil(grade, w, h)
                    raw = bytearray(rgba.tobytes())
                    for y in range(h):
                        for x in range(w):
                            if not grade[y][x]:
                                raw[(y * w + x) * 4 : (y * w + x) * 4 + 4] = b"\x00\x00\x00\x00"
                    recorte, metodo = Image.frombytes("RGBA", (w, h), bytes(raw)), m_sub

    recorte = _remover_ilhas_ruido(recorte)
    recorte = limpar_halo_e_sangrar_rgb(recorte, bg_rgb, usou_rembg=usou_rembg, alpha_corte=160, bleed_px=6)
    recorte = recortar_com_margem_segura(recorte, margem_frac=0.12)

    alfa_bytes = recorte.getchannel("A").tobytes()
    total = max(len(alfa_bytes), 1)
    opacos = sum(1 for a in alfa_bytes if a >= 160)
    halo_semi = sum(1 for a in alfa_bytes if 0 < a < 255) / total

    destino = Path(saida_png)
    destino.parent.mkdir(parents=True, exist_ok=True)
    recorte.save(destino, format="PNG")
    return {
        "ok": True,
        "imagem": str(destino),
        "largura": recorte.width,
        "altura": recorte.height,
        "area_fg": round(opacos / total, 4),
        "halo_semitransparente": round(halo_semi, 6),
        "metodo": metodo,
        **({"avisos": rembg_avisos} if rembg_avisos else {}),
    }


def _args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Pose Guard e decomposicao 2D — canal JSON")
    p.add_argument("--imagem", required=True)
    p.add_argument("--resultado", required=True)
    p.add_argument("--acao", default="detectar", choices=["detectar", "decompor"])
    p.add_argument("--saida-png", default="")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _args(argv)
    resultado: dict[str, Any] = {
        "ok": False,
        "acao": args.acao,
        "imagem": str(Path(args.imagem).expanduser()),
    }
    try:
        if args.acao == "decompor":
            if not args.saida_png:
                raise ValueError("--saida-png e obrigatorio com --acao decompor")
            info = decompor_silhueta_arma(args.imagem, args.saida_png)
            resultado.update(info)
        else:
            info = detectar_pose_imagem(args.imagem)
            resultado.update(info)
            resultado["ok"] = True
        return 0
    except Exception as exc:  # noqa: BLE001 - erro vira arquivo JSON (I9)
        resultado.update(
            {
                "ok": False,
                "erro": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(limit=8),
            }
        )
        return 1
    finally:
        _salvar(args.resultado, resultado)


if __name__ == "__main__":
    raise SystemExit(main())
