"""Pose Guard e decomposicao 2D de silhuetas (Setup Onda 2 / Onda 3).

Roda via CLI (canal JSON em disco, I9) dentro de ``venv-i23d`` ou ``venv-concept``
com ``cv2`` + ``numpy`` + ``PIL``, e tambem funciona com fallback Pillow puro em CPU.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import traceback
from collections import deque
from pathlib import Path
from typing import Any

from PIL import Image

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
        mask = np.where(alpha >= 24, np.uint8(255), np.uint8(0))
        return _limpar_mascara_cv2(mask), "alpha"

    rgb = arr[:, :, :3]
    h, w = rgb.shape[:2]
    borda = np.concatenate(
        [
            rgb[0, :],
            rgb[-1, :],
            rgb[:, 0],
            rgb[:, -1],
        ],
        axis=0,
    ).astype(np.float32)
    bg = np.median(borda, axis=0)
    dist_borda = np.linalg.norm(borda - bg, axis=1)
    limiar = max(20.0, float(np.percentile(dist_borda, 90)) + 12.0)

    dist = np.linalg.norm(rgb.astype(np.float32) - bg, axis=2)
    mask = np.where(dist > limiar, np.uint8(255), np.uint8(0))

    # Se fundo complexo estourar o limiar simples, refina via GrabCut em retangulo interno.
    frac = float(np.count_nonzero(mask)) / max(h * w, 1)
    if (frac < 0.02 or frac > 0.88) and h >= 16 and w >= 16:
        gc_mask = np.zeros((h, w), dtype=np.uint8)
        bgd_model = np.zeros((1, 65), dtype=np.float64)
        fgd_model = np.zeros((1, 65), dtype=np.float64)
        rx0 = max(1, int(round(w * 0.05)))
        ry0 = max(1, int(round(h * 0.03)))
        rw = max(2, int(round(w * 0.90)))
        rh = max(2, int(round(h * 0.94)))
        if rx0 + rw < w and ry0 + rh < h:
            cv2.grabCut(
                rgb,
                gc_mask,
                (rx0, ry0, rw, rh),
                bgd_model,
                fgd_model,
                3,
                cv2.GC_INIT_WITH_RECT,
            )
            gc_fg = np.where(
                (gc_mask == cv2.GC_FGD) | (gc_mask == cv2.GC_PR_FGD),
                np.uint8(255),
                np.uint8(0),
            )
            gc_frac = float(np.count_nonzero(gc_fg)) / max(h * w, 1)
            if 0.02 <= gc_frac <= 0.92:
                return _limpar_mascara_cv2(gc_fg), "grabcut"

    return _limpar_mascara_cv2(mask), "border_dist"


def _mascara_foreground_pil(rgba_img: Image.Image) -> tuple[list[list[int]], int, int, str]:
    """Fallback em Pillow puro retornando grade 0/1 ``[y][x]``."""
    rgba = rgba_img.convert("RGBA")
    w, h = rgba.size
    px = rgba.tobytes()
    alphas = px[3::4]
    if min(alphas) < 250:
        grade = [
            [1 if px[(y * w + x) * 4 + 3] >= 24 else 0 for x in range(w)]
            for y in range(h)
        ]
        return grade, w, h, "alpha"

    amostras: list[tuple[int, int, int]] = []
    for x in range(w):
        for y in (0, h - 1):
            i = (y * w + x) * 4
            amostras.append((px[i], px[i + 1], px[i + 2]))
    for y in range(h):
        for x in (0, w - 1):
            i = (y * w + x) * 4
            amostras.append((px[i], px[i + 1], px[i + 2]))
    bg_r = statistics.median(c[0] for c in amostras)
    bg_g = statistics.median(c[1] for c in amostras)
    bg_b = statistics.median(c[2] for c in amostras)
    grade = []
    for y in range(h):
        linha: list[int] = []
        base = y * w * 4
        for x in range(w):
            i = base + x * 4
            dr = px[i] - bg_r
            dg = px[i + 1] - bg_g
            db = px[i + 2] - bg_b
            linha.append(1 if (dr * dr + dg * dg + db * db) > 26.0 * 26.0 else 0)
        grade.append(linha)
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
            "pose": "arms_down",
            "razao_flanco": 0.0,
            "largura_ombros": 0.0,
            "precisa_repose": True,
            "aspecto": 0.0,
            "waist_elbow_gap": 0.0,
            "cabeca_ok": False,
            "simetria_iou": 0.0,
            "leg_gap_ratio": 0.0,
            "pernas_separadas": False,
            "apto_rig": False,
            "score_pose": 0.0,
            "metodo_mascara": metodo,
        }

    y_min = linhas_fg[0][0]
    y_max = linhas_fg[-1][0]
    fg_h = max(1, y_max - y_min + 1)
    x_min = min(xs[0] for _, xs in linhas_fg)
    x_max = max(xs[-1] for _, xs in linhas_fg)
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
        if xs:
            span_px = xs[-1] - xs[0] + 1
            fill_px = len(xs)
        else:
            span_px = 0
            fill_px = 0

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
            if len(xs) >= 2 and span_px > fill_px:
                # Conta intervalos internos de background >= gap_min_px
                tem_gap_real = False
                for a, b in zip(xs, xs[1:]):
                    if b - a - 1 >= gap_min_px:
                        tem_gap_real = True
                        break
                if tem_gap_real:
                    waist_gap_scores.append((span_px - fill_px) / max(span_px, 1))
                else:
                    waist_gap_scores.append(0.0)
            else:
                waist_gap_scores.append(0.0)

    largura_ombros = _percentil(upper_spans, 0.90) if upper_spans else aspecto
    span_40_75 = _percentil(band_40_75_spans, 0.85) if band_40_75_spans else aspecto
    mean_fill_40_75 = (
        sum(band_40_75_fills) / len(band_40_75_fills) if band_40_75_fills else aspecto
    )
    upper_norm = max(upper_max_px / fg_h, largura_ombros, 1e-6)
    flank_vs_upper = max(0.0, 1.0 - (mean_fill_40_75 / upper_norm))
    waist_elbow_gap = (
        sum(waist_gap_scores) / len(waist_gap_scores) if waist_gap_scores else 0.0
    )
    razao_flanco = max(flank_vs_upper, waist_elbow_gap)

    eh_tpose = largura_ombros >= 0.54 and flank_vs_upper >= 0.30 and aspecto >= 0.50
    eh_apose = (
        (largura_ombros >= 0.45 or span_40_75 >= 0.45)
        and aspecto >= 0.45
        and (waist_elbow_gap >= 0.06 or flank_vs_upper >= 0.32)
    )
    # Silhueta muito estreita ou zero espaco entre tronco e bracos (sem T-pose) => arms_down.
    if aspecto < 0.44 or (not eh_tpose and waist_elbow_gap < 0.05):
        pose = "arms_down"
    elif eh_tpose or eh_apose:
        pose = "tpose_apose"
    else:
        pose = "arms_down"

    cabeca_spans: list[float] = []
    leg_total = 0
    leg_com_gap = 0
    x_mid = (x_min + x_max) / 2.0
    sim_inter = 0
    sim_union = 0
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
        "pose": pose,
        "razao_flanco": round(float(razao_flanco), 4),
        "largura_ombros": round(float(largura_ombros), 4),
        "precisa_repose": pose == "arms_down",
        "aspecto": round(float(aspecto), 4),
        "waist_elbow_gap": round(float(waist_elbow_gap), 4),
        "cabeca_ok": cabeca_ok,
        "simetria_iou": round(float(simetria_iou), 4),
        "leg_gap_ratio": round(float(leg_gap_ratio), 4),
        "pernas_separadas": pernas_separadas,
        "apto_rig": apto_rig,
        "score_pose": round(float(score_pose), 4),
        "metodo_mascara": metodo,
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


def _desmultiplicar_rgba(
    rgba: Image.Image, alfa_minimo: int = 24, *, unpremul: bool = False
) -> Image.Image:
    raw = bytearray(rgba.convert("RGBA").tobytes())
    for i in range(0, len(raw), 4):
        a = raw[i + 3]
        if a < alfa_minimo:
            raw[i] = 0
            raw[i + 1] = 0
            raw[i + 2] = 0
            raw[i + 3] = 0
        elif unpremul and a < 255:
            raw[i] = min(255, round(raw[i] * 255 / a))
            raw[i + 1] = min(255, round(raw[i + 1] * 255 / a))
            raw[i + 2] = min(255, round(raw[i + 2] * 255 / a))
    return Image.frombytes("RGBA", rgba.size, bytes(raw))


def decompor_silhueta_arma(imagem_path: str | Path, saida_png: str | Path) -> dict[str, Any]:
    """Isola recorte RGBA limpo e recortado na bbox para extrusao 2D de arma/capa."""
    caminho = Path(imagem_path)
    if not caminho.is_file():
        raise FileNotFoundError(f"imagem nao encontrada: {caminho}")

    with Image.open(caminho) as img:
        rgba = img.convert("RGBA")

    era_opaca = rgba.getchannel("A").getextrema()[0] >= 250
    metodo = "alpha"
    recorte = rgba
    usou_rembg = False

    if era_opaca:
        try:
            import rembg  # type: ignore[import-not-found]

            rembg_modelo = os.environ.get("FORGE3D_REMBG_MODELO", "birefnet-general").strip() or "birefnet-general"
            try:
                sessao = rembg.new_session(rembg_modelo)
                metodo = f"rembg:{rembg_modelo}"
            except Exception:  # noqa: BLE001 - fallback offline para u2net em cache
                sessao = rembg.new_session("u2net")
                metodo = "rembg:u2net"
            recorte = rembg.remove(rgba, session=sessao).convert("RGBA")
            usou_rembg = True
        except Exception:  # noqa: BLE001 - ambiente sem rembg/rede cai no GrabCut/contraste
            usou_rembg = False

        if not usou_rembg:
            if _TEM_CV2:
                mask_u8, m_sub = _mascara_foreground_cv2(rgba)
                arr = np.array(rgba)
                arr[:, :, 3] = np.where(mask_u8 > 0, np.uint8(255), np.uint8(0))
                recorte = Image.fromarray(arr, mode="RGBA")
                metodo = m_sub
            else:
                grade, w, h, m_sub = _mascara_foreground_pil(rgba)
                grade = _manter_maior_componente_pil(grade, w, h)
                raw = bytearray(rgba.tobytes())
                for y in range(h):
                    for x in range(w):
                        if not grade[y][x]:
                            idx = (y * w + x) * 4
                            raw[idx : idx + 4] = b"\x00\x00\x00\x00"
                recorte = Image.frombytes("RGBA", (w, h), bytes(raw))
                metodo = m_sub

    recorte = _desmultiplicar_rgba(recorte, alfa_minimo=24, unpremul=usou_rembg)

    if _TEM_CV2:
        arr = np.array(recorte)
        fg_mask = np.where(arr[:, :, 3] >= 24, np.uint8(255), np.uint8(0))
        fg_limpo = _limpar_mascara_cv2(fg_mask)
        if int(np.count_nonzero(fg_limpo)) > 0:
            arr[fg_limpo == 0] = 0
            recorte = Image.fromarray(arr, mode="RGBA")
    else:
        w, h = recorte.size
        raw = bytearray(recorte.tobytes())
        grade = [
            [1 if raw[(y * w + x) * 4 + 3] >= 24 else 0 for x in range(w)]
            for y in range(h)
        ]
        grade = _manter_maior_componente_pil(grade, w, h)
        if any(any(row) for row in grade):
            for y in range(h):
                for x in range(w):
                    if not grade[y][x]:
                        idx = (y * w + x) * 4
                        raw[idx : idx + 4] = b"\x00\x00\x00\x00"
            recorte = Image.frombytes("RGBA", (w, h), bytes(raw))

    bbox = recorte.getchannel("A").getbbox()
    if bbox:
        x0, y0, x1, y1 = bbox
        pad = 2
        cx0 = max(0, x0 - pad)
        cy0 = max(0, y0 - pad)
        cx1 = min(recorte.width, x1 + pad)
        cy1 = min(recorte.height, y1 + pad)
        recorte = recorte.crop((cx0, cy0, cx1, cy1))

    alfa_bytes = recorte.getchannel("A").tobytes()
    total = max(len(alfa_bytes), 1)
    opacos = sum(1 for a in alfa_bytes if a >= 24)

    destino = Path(saida_png)
    destino.parent.mkdir(parents=True, exist_ok=True)
    recorte.save(destino, format="PNG")
    return {
        "ok": True,
        "imagem": str(destino),
        "largura": recorte.width,
        "altura": recorte.height,
        "area_fg": round(opacos / total, 4),
        "metodo": metodo,
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
