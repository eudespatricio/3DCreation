"""Primitivas de mascara/silhueta e avaliador deterministico G15 (concept -> 3D; D26)."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from PIL import Image

LIMIAR_IOU_G15 = 0.55
LIMIAR_ASPECT_G15 = 0.60
MARGEM_CANVAS_G15 = 4

def _luminancia(r: int, g: int, b: int) -> float:
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0

def _mediana_int(vals: list[int]) -> int:
    s, n = sorted(vals), len(vals)
    return 0 if n == 0 else (s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) // 2)

def _media_rgb(pixels: list[tuple[int, int, int]]) -> tuple[float, float, float]:
    n = len(pixels)
    return (0.0, 0.0, 0.0) if n == 0 else (sum(p[0] for p in pixels) / (255.0 * n), sum(p[1] for p in pixels) / (255.0 * n), sum(p[2] for p in pixels) / (255.0 * n))

def _rgba_px(img: Image.Image) -> Any:
    px = img.load()
    if px is None:
        raise ValueError("imagem sem buffer de pixels")
    return px

def _mediana_rgb(pts: list[tuple[int, int, int]]) -> tuple[int, int, int]:
    return (_mediana_int([c[0] for c in pts]), _mediana_int([c[1] for c in pts]), _mediana_int([c[2] for c in pts]))

def _estimar_fundo_rgb(rgba: Image.Image) -> tuple[int, int, int]:
    w, h, px = *rgba.size, _rgba_px(rgba)
    if w <= 0 or h <= 0:
        return (0, 0, 0)
    ys = range(min(4, h))
    tl = [px[x, y][:3] for y in ys for x in range(min(4, w))]
    tr = [px[x, y][:3] for y in ys for x in range(max(0, w - 4), w)]
    c_tl, c_tr = _mediana_rgb(tl), _mediana_rgb(tr)
    top = [px[x, y][:3] for y in ys for x in range(0, w, max(1, w // 32))]
    if (dist := _rgb_dist(c_tl, c_tr)) <= 16:
        c_mid, top_med = _mediana_rgb(tl + tr), _mediana_rgb(top)
        if _rgb_dist(top_med, c_mid) > 20 and sum(1 for c in top if _rgb_dist(c, c_mid) <= 20) < len(top) // 2 and sum(1 for c in top if _rgb_dist(c, top_med) <= 20) > len(top) // 2:
            ys_s = min(h - 1, max(4, h // 3))
            c_side = _mediana_rgb([px[x, ys_s][:3] for x in list(range(min(4, w))) + list(range(max(0, w - 4), w))])
            if _rgb_dist(c_side, top_med) < _rgb_dist(c_side, c_mid):
                return top_med
        return c_mid
    s_tl = sum(1 for c in top if _rgb_dist(c, c_tl) <= 20)
    s_tr = sum(1 for c in top if _rgb_dist(c, c_tr) <= 20)
    inter = sum(1 for c in top if _rgb_dist(c, c_tl) > 4 and _rgb_dist(c, c_tr) > 4 and max(_rgb_dist(c, c_tl), _rgb_dist(c, c_tr)) < dist)
    if dist <= 36 and min(s_tl, s_tr) >= len(top) // 4 and inter >= len(top) // 8:
        return _mediana_rgb(tl + tr)
    if max(s_tl, s_tr) < len(top) // 4:
        return _mediana_rgb(top)
    t_tl = sum(1 for c in top if _rgb_dist(c, c_tl) <= 6)
    t_tr = sum(1 for c in top if _rgb_dist(c, c_tr) <= 6)
    return c_tl if (s_tl, t_tl) >= (s_tr, t_tr) else c_tr

def _tem_alfa_transparente(quad: Image.Image) -> bool:
    w, h, extrema = *(rgba := quad if quad.mode == "RGBA" else quad.convert("RGBA")).size, rgba.getextrema()
    if w <= 0 or h <= 0 or not (isinstance(extrema, tuple) and len(extrema) == 4 and extrema[3][0] < 245):
        return False
    px, sx, sy = _rgba_px(rgba), max(1, w // 64), max(1, h // 64)
    alphas = [int(px[x, 0][3]) for x in range(0, w, sx)] + ([int(px[x, h - 1][3]) for x in range(0, w, sx)] if h > 1 else [])
    alphas += [int(px[0, y][3]) for y in range(0, h, sy)] + ([int(px[w - 1, y][3]) for y in range(0, h, sy)] if w > 1 else [])
    return bool(alphas) and ((sum(1 for a in alphas if a <= 24) / float(len(alphas))) >= 0.10 or _mediana_int(alphas) < 245)

def _eh_foreground(rgba: tuple[int, int, int, int], bg_rgb: tuple[int, int, int], usar_alfa: bool) -> bool:
    return rgba[3] > 24 if usar_alfa else max(abs(rgba[c] - bg_rgb[c]) for c in range(3)) > 20

def _reduzir_para_analise(quad: Image.Image, max_lado: int = 400) -> Image.Image:
    w, h = (rgba := quad.convert("RGBA")).size
    if max(1, max(w, h)) <= max_lado:
        return rgba
    escala = max_lado / float(max(1, max(w, h)))
    return rgba.resize((max(16, int(round(w * escala))), max(16, int(round(h * escala)))), Image.Resampling.BILINEAR)

def _rgb_dist(a: tuple[int, int, int], b: tuple[int, int, int]) -> int:
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]), abs(a[2] - b[2]))

def _clamp_rgb(r: float, g: float, b: float) -> tuple[int, int, int]:
    return (max(0, min(255, int(round(r)))), max(0, min(255, int(round(g)))), max(0, min(255, int(round(b)))))

_AncoraBg = tuple[int, tuple[int, int, int], tuple[float, float, float]]

def _fit_ols(pts: list[tuple[int, tuple[int, int, int]]], fallback: tuple[int, int, int]) -> _AncoraBg:
    if not pts:
        return 0, fallback, (0.0, 0.0, 0.0)
    yl, rl = pts[-1]
    n = float(len(pts))
    my = sum(p[0] for p in pts) / n
    dv = sum((p[0] - my) ** 2 for p in pts)
    if len(pts) < 2 or dv <= 1e-6:
        return yl, rl, (0.0, 0.0, 0.0)
    mcs = tuple(sum(p[1][c] for p in pts) / n for c in range(3))
    sl = [max(-12.0, min(12.0, sum((p[0] - my) * (p[1][c] - mcs[c]) for p in pts) / dv)) for c in range(3)]
    dt = yl - my
    return yl, _clamp_rgb(mcs[0] + sl[0] * dt, mcs[1] + sl[1] * dt, mcs[2] + sl[2] * dt), (sl[0], sl[1], sl[2])

def _pred_anc(yt: int, anc: _AncoraBg) -> tuple[int, int, int]:
    ay, argb, sl = anc
    return _clamp_rgb(argb[0] + sl[0] * (yt - ay), argb[1] + sl[1] * (yt - ay), argb[2] + sl[2] * (yt - ay))

def _interp_seg(res: list[tuple[int, int, int]], ys: int, ye_incl: int, y0: int, rgb0: tuple[int, int, int], y1: int, rgb1: tuple[int, int, int]) -> None:
    span = max(1, y1 - y0)
    for r in range(ys, ye_incl + 1):
        t = (r - y0) / float(span)
        res[r] = _clamp_rgb(rgb0[0] + (rgb1[0] - rgb0[0]) * t, rgb0[1] + (rgb1[1] - rgb0[1]) * t, rgb0[2] + (rgb1[2] - rgb0[2]) * t)

def _aceitar_pts(pts: list[tuple[int, tuple[int, int, int]]], min_y: int, res: list[tuple[int, int, int]], trusted: list[tuple[int, tuple[int, int, int]]]) -> None:
    for py, pr in pts:
        if py >= min_y:
            res[py] = pr
            trusted.append((py, pr))

def _estimar_bg_cands(
    cands: list[tuple[int, int, int]], valid: list[bool], bg: tuple[int, int, int],
    ls_meds: list[tuple[int, int, int]] | None = None, rs_meds: list[tuple[int, int, int]] | None = None,
) -> list[tuple[int, int, int]]:
    h = len(cands)
    if h == 0:
        return []
    res, floor_start, bottom_reach, can_rewind = [bg] * h, int(h * 0.60), int(h * 0.95), [False] * h
    trusted: list[tuple[int, tuple[int, int, int]]] = []

    def _modelo(max_y: int | None = None) -> _AncoraBg:
        pts = trusted if max_y is None else [p for p in trusted if p[0] < max_y]
        if not pts:
            return 0, bg, (0.0, 0.0, 0.0)
        yl = pts[-1][0]
        win = [pt for pt in pts[-24:] if yl - pt[0] <= 32]
        return (yl, _mediana_rgb([p[1] for p in win]), (0.0, 0.0, 0.0)) if len(win) < 5 else _fit_ols(win, bg)

    def _pick(yi: int, ref: tuple[int, int, int]) -> tuple[tuple[int, int, int] | None, bool]:
        if ls_meds is None or rs_meds is None:
            return (cands[yi], True) if valid[yi] else (None, False)
        dl, dr = _rgb_dist(ls_meds[yi], ref), _rgb_dist(rs_meds[yi], ref)
        if valid[yi]:
            d_lr = _rgb_dist(ls_meds[yi], rs_meds[yi])
            if (dl <= 4 and dr > 6) or (d_lr > 12 and dl <= 8 and dr > 12):
                return ls_meds[yi], True
            if (dr <= 4 and dl > 6) or (d_lr > 12 and dr <= 8 and dl > 12):
                return rs_meds[yi], True
            return cands[yi], True
        return (ls_meds[yi], True) if (dl <= 12 and dr > 12) else ((rs_meds[yi], True) if (dr <= 12 and dl > 12) else (None, False))

    def _scan_linear(start_y: int, seed_pts: list[tuple[int, tuple[int, int, int]]]) -> tuple[list[tuple[int, tuple[int, int, int]]], int, _AncoraBg, int]:
        pts, prev, j_last, step_after = list(seed_pts), seed_pts[-1][1], seed_pts[-1][0], 0
        anc_cur: _AncoraBg | None = _fit_ols(pts[-24:], bg) if len(pts) >= 3 else None
        for r in range(start_y, h):
            ref = _pred_anc(r, anc_cur) if anc_cur is not None else prev
            cr, ok_r = _pick(r, ref)
            if not ok_r or cr is None:
                break
            if (st := _rgb_dist(cr, prev)) > 12:
                step_after = st
                break
            if anc_cur is not None and _rgb_dist(cr, ref) > 4:
                break
            pts.append((r, cr))
            prev, j_last = cr, r
            if len(pts) == 3 or (len(pts) > 3 and (len(pts) <= 12 or len(pts) % 4 == 0)):
                anc_l = _fit_ols(pts[-24:], bg)
                if (len(pts) <= 12 and max(_rgb_dist(pr, _pred_anc(py, anc_l)) for py, pr in pts) > 4) or (len(pts) > 12 and _rgb_dist(pts[0][1], _pred_anc(pts[0][0], anc_l)) > 8):
                    pts.pop()
                    return pts, pts[-1][0], _fit_ols(pts[-24:], bg), step_after
                anc_cur = anc_l
        return pts, j_last, _fit_ols(pts[-24:], bg), step_after

    def _rejoins(anc_l: _AncoraBg, from_y: int, min_run: int = 3) -> bool:
        run, r_first, steep = 0, None, max(abs(s) for s in anc_l[2]) > 0.35
        need = max(min_run, 6) if steep else min_run
        for r in range(from_y, h):
            cr, ok_r = _pick(r, pr := _pred_anc(r, anc_l))
            if ok_r and cr is not None and _rgb_dist(cr, pr) <= 4:
                r_first = cr if run == 0 else r_first
                run += 1
                if (not steep or (r_first is not None and _rgb_dist(r_first, cr) >= (3 if run >= need else 1))) and (run >= need or (run >= min_run and r == h - 1)):
                    return True
            else:
                run, r_first = 0, None
        return False

    def _sup_cnt(anc_l: _AncoraBg, from_y: int) -> int:
        return sum(1 for r in range(from_y, h) if (pk := _pick(r, pr := _pred_anc(r, anc_l)))[1] and pk[0] is not None and _rgb_dist(pk[0], pr) <= 4)

    def _find_dn(from_y: int, ref_y: int | None = None) -> tuple[int, list[tuple[int, tuple[int, int, int]]], _AncoraBg, int] | None:
        best, best_k, i, ry, min_t = None, None, from_y, (from_y if ref_y is None else ref_y), max(24, h // 4)
        ref_pre, y_pre = (res[ry - 1] if ry > 0 else bg), max(0, ry - 1)
        while i < h:
            c0, ok0 = (None, False) if (ls_meds is not None and rs_meds is not None and _rgb_dist(ls_meds[i], rs_meds[i]) > 12) else _pick(i, cands[i])
            if ok0 and c0 is not None:
                pts, j_end, anc_l, _ = _scan_linear(i + 1, [(i, c0)])
                if len(pts) >= 16 or (j_end == h - 1 and len(pts) >= 8):
                    cont = 1 if ((_rejoins(anc_l, j_end + 2) and _sup_cnt(anc_l, j_end + 2) >= min_t) or (j_end == h - 1 and len(pts) >= min_t)) else 0
                    key = (cont, 1 if _rgb_dist(ref_pre, _pred_anc(y_pre, anc_l)) <= 6 else 0, 1 if j_end >= floor_start else 0, len(pts))
                    if best_k is None or key > best_k:
                        best, best_k = (i, pts, anc_l, j_end), key
                i = max(i + 1, j_end + 1)
            else:
                i += 1
        return best

    def _dn_beats(ys: int, end_y: int, anc_c: _AncoraBg) -> bool:
        return ys < floor_start and max(abs(s) for s in anc_c[2]) <= 0.35 and (dn_c := _find_dn(end_y + 1, ys)) is not None and dn_c[0] <= end_y + 2 and (_rgb_dist(dn_c[1][0][1], _pred_anc(dn_c[0], anc_c)) > 6 or _rgb_dist(dn_c[1][-1][1], _pred_anc(dn_c[3], anc_c)) > 6) and _sup_cnt(dn_c[2], end_y + 2) > _sup_cnt(anc_c, end_y + 2)

    y = 0
    while y < h:
        pred_y = _pred_anc(y, anc := _modelo())
        cand_y, ok_y = _pick(y, pred_y)
        if not ok_y or cand_y is None:
            res[y] = pred_y
            y += 1
        elif _rgb_dist(cand_y, pred_y) <= 2 and (y >= floor_start or len(trusted) < 24 or trusted[-1][0] - trusted[-24][0] != 23 or _rgb_dist(cand_y, _pred_anc(y, _fit_ols(trusted[-24:-8], bg))) <= 2):
            res[y], can_rewind[y] = cand_y, True
            trusted.append((y, cand_y))
            y += 1
        else:
            y_start, anc_pre = y, anc
            anc_chk = _fit_ols(trusted[-24:-8], bg) if (len(trusted) >= 24 and trusted[-1][0] - trusted[-24][0] == 23) else None
            for yb in range(y - 1, max(-1, y - 9), -1):
                if not can_rewind[yb]:
                    break
                anc_try = _modelo(yb)
                p_yb = _pred_anc(yb, anc_chk if (anc_chk is not None and anc_chk[0] < yb and _rgb_dist(res[yb], _pred_anc(yb, anc_try)) < 2) else anc_try)
                if _rgb_dist(res[yb], p_yb) < 2 or sum((res[yb][c] - p_yb[c]) * (cand_y[c] - p_yb[c]) for c in range(3)) <= 0:
                    break
                y_start, anc_pre = yb, anc_try
            if y_start < y:
                trusted, anc = [p for p in trusted if p[0] < y_start], anc_pre
                cs, oks = _pick(y_start, _pred_anc(y_start, anc))
                cand_y = cs if (oks and cs is not None) else res[y_start]
            has_pre = y_start > 0 and bool(trusted) and trusted[-1][0] == y_start - 1
            seed = ([(y_start - 1, res[y_start - 1])] if has_pre else []) + [(y_start, cand_y)]
            p_pts, j_end, anc_lin, step_after = _scan_linear(y_start + 1, seed) if (y_start == 0 or _rgb_dist(cand_y, res[y_start - 1]) <= 12) else (seed, y_start, anc, 0)
            if j_end >= y and len(p_pts) >= 4:
                long_tail = len(p_pts) >= max(48, (h - y_start) // 2) and h - 1 - j_end < max(24, h // 4) and max(abs(s) for s in anc_lin[2]) > 0.05 and _rgb_dist(res[0] if y_start > 0 else bg, _pred_anc(0, anc_lin)) <= 6
                if j_end == h - 1 or long_tail or (not _dn_beats(y_start, j_end, anc_lin) and _rejoins(anc_lin, j_end + 2) and _sup_cnt(anc_lin, j_end + 2) > _sup_cnt(anc, j_end + 1)):
                    _aceitar_pts(p_pts, y_start, res, trusted)
                    y = max(y + 1, j_end + 1)
                    continue
                if y_start <= 1 and step_after <= 12 and not _rejoins(anc, j_end + 1):
                    cr_k, ok_k = _pick(j_end + 1, p_pts[-1][1])
                    if ok_k and cr_k is not None and _rgb_dist(cr_k, p_pts[-1][1]) <= 4:
                        f_pts, f_end, anc_f, _ = _scan_linear(j_end + 2, [(j_end + 1, cr_k)])
                        if f_end == h - 1 or (not _dn_beats(y_start, f_end, anc_f) and _rejoins(anc_f, f_end + 2) and _sup_cnt(anc_f, f_end + 2) > _sup_cnt(anc, f_end + 1)):
                            _aceitar_pts(p_pts, y_start, res, trusted)
                            if len(f_pts) >= 5:
                                trusted = [p for p in trusted if p[0] < y_start]
                            _aceitar_pts(f_pts, j_end + 1, res, trusted)
                            y = max(y + 1, f_end + 1)
                            continue
                anc_fl = (j_end, p_pts[-1][1], (0.0, 0.0, 0.0))
                if (y_start <= 1 or j_end >= floor_start) and not _rejoins(anc, j_end + 1) and not _dn_beats(y_start, j_end, anc_fl) and _rejoins(anc_fl, j_end + 2, 6) and _sup_cnt(anc_fl, j_end + 2) >= max(8, (h - j_end) // 2):
                    _aceitar_pts(p_pts, y_start, res, trusted)
                    trusted = [p for p in trusted if p[0] < j_end] + [(j_end, p_pts[-1][1])]
                    y = max(y + 1, j_end + 1)
                    continue
                knee_ok = y_start <= 1 and len(p_pts) >= 8 and _rgb_dist(p_pts[0][1], bg) <= 4 and _rgb_dist(p_pts[0][1], p_pts[-1][1]) > 12 and (len(p_pts) >= 16 or step_after <= 4) and not _rejoins((0, bg, (0.0, 0.0, 0.0)), j_end + 1)
                if knee_ok and _sup_cnt(anc_fl, j_end + 2) >= max(8, (h - j_end) // 3):
                    _aceitar_pts(p_pts, y_start, res, trusted)
                    y = max(y + 1, j_end + 1)
                    continue
            k, last_seen, pts_exc = y_start, cand_y, [(y_start, cand_y)]
            max_step = max_dev = _rgb_dist(cand_y, _pred_anc(y_start, anc))
            returned, exit_y, exit_rgb = False, h, _pred_anc(y_start, anc)
            while k + 1 < h:
                k += 1
                ck, ok_k = _pick(k, pk := _pred_anc(k, anc))
                if ok_k and ck is not None:
                    sk, dk = _rgb_dist(ck, last_seen), _rgb_dist(ck, pk)
                    if k >= y and (dk <= 2 or (dk <= 6 and dk < max_dev)):
                        bk, bc, bd = k, ck, dk
                        for kf in range(k + 1, min(h, k + 8)):
                            ckf, ok_kf = _pick(kf, _pred_anc(kf, anc))
                            if not ok_kf or ckf is None or _rgb_dist(ckf, _pred_anc(kf, anc)) >= bd:
                                break
                            bk, bc, bd = kf, ckf, _rgb_dist(ckf, _pred_anc(kf, anc))
                        if y_start < floor_start or all(_rgb_dist(cands[r], _pred_anc(r, anc)) <= 6 for r in range(bk + 1, min(h, bk + 5))):
                            b_pts, b_end, anc_b, _ = _scan_linear(bk + 1, [(bk, bc)])
                            dn_b = _find_dn(b_end + 1, y_start) if b_end < h - 1 else (_find_dn(y_start) if len(b_pts) < max(24, h // 4) and len(trusted) < 5 else None)
                            if dn_b is not None and _rgb_dist(res[0] if y_start > 0 else bg, _pred_anc(0, dn_b[2])) <= 6 and ((b_end < h - 1 and (dn_b[3] == h - 1 or _rejoins(dn_b[2], dn_b[3] + 2) or len(dn_b[1]) >= max(24, h // 4)) and (y_start == 0 or _rgb_dist(res[y_start - 1], _pred_anc(y_start - 1, dn_b[2])) <= 6) and _sup_cnt(dn_b[2], b_end + 1) > _sup_cnt(anc_b, b_end + 2)) or (b_end == h - 1 and dn_b[0] < bk and len(dn_b[1]) >= max(48, 2 * len(b_pts)))):
                                for py, pr in [(k, ck)] + [p for p in b_pts if p[0] > k]:
                                    pts_exc.append((py, pr))
                                    max_step, max_dev, last_seen = max(max_step, _rgb_dist(pr, last_seen)), max(max_dev, _rgb_dist(pr, _pred_anc(py, anc))), pr
                                k = b_end
                                continue
                            returned, exit_y, exit_rgb = True, bk, bc
                            break
                    pts_exc.append((k, ck))
                    max_step, max_dev, last_seen = max(max_step, sk), max(max_dev, dk), ck
            exc_end = (exit_y - 1) if returned else (h - 1)
            faixa_piso = y_start >= floor_start and exc_end >= bottom_reach and max_step <= 24
            grad_cont, sub_ripple = not returned and max_step <= 12 and (y_start <= 1 or y_start >= floor_start), returned and max_dev <= 20 and max_step <= 12
            if not returned and not faixa_piso:
                if (dn := _find_dn(y_start)) is not None:
                    s_dn, dn_pts, anc_dn, dn_end = dn
                    pre_ok = _rgb_dist(res[y_start - 1] if y_start > 0 else bg, _pred_anc(max(0, y_start - 1), anc_dn)) <= 6
                    before = [p for p in pts_exc if p[0] < s_dn]
                    dev_dn = max((_rgb_dist(cr, _pred_anc(r, anc_dn)) for r, cr in before), default=0)
                    dk_max = max((_rgb_dist(cr, _pred_anc(r, anc)) for r, cr in before), default=0)
                    anc_div = _rgb_dist(dn_pts[-1][1], _pred_anc(dn_pts[-1][0], anc)) > 12
                    top_ok = y_start == 0 and dev_dn > 12 and len(dn_pts) >= 24 and len(dn_pts) > s_dn
                    dn_tail = (dn_end == h - 1 and len(dn_pts) >= 24) or len(dn_pts) >= 48
                    win_t = trusted[-24:]
                    has_gap = len(win_t) >= 2 and (win_t[-1][0] - win_t[0][0] + 1 > len(win_t))
                    bg_rec = y_start > 0 and (dn_tail or (has_gap and (dn_end == h - 1 or _rejoins(anc_dn, dn_end + 2)))) and _rgb_dist(res[y_start - 1], _pred_anc(y_start - 1, anc_dn)) > (6 if dn_tail else 12) and _rgb_dist(res[0], _pred_anc(0, anc_dn)) <= 6
                    if top_ok or bg_rec or (pre_ok and (dev_dn > 12 or (dev_dn > 6 and anc_div))) or (dev_dn > 12 and dk_max >= 18 and _rgb_dist(dn_pts[0][1], _pred_anc(s_dn, anc)) <= dk_max - 10):
                        if y_start == 0:
                            for r in range(s_dn):
                                res[r] = _pred_anc(r, anc_dn)
                        elif s_dn > y_start:
                            _interp_seg(res, y_start, s_dn - 1, y_start - 1, res[y_start - 1], s_dn, dn_pts[0][1])
                        trusted = [p for p in trusted if _rgb_dist(p[1], _pred_anc(p[0], anc_dn)) <= 6]
                        _aceitar_pts(dn_pts[:24], s_dn, res, trusted)
                        y = max(y + 1, dn_pts[min(len(dn_pts), 24) - 1][0] + 1)
                        continue
                if y_start == 0 and j_end >= y and len(p_pts) >= 6 and step_after > 12:
                    _aceitar_pts(p_pts, y_start, res, trusted)
                    y = max(y + 1, j_end + 1)
                    continue
            if faixa_piso or grad_cont or sub_ripple:
                prev_c = _pred_anc(y_start, anc)
                for r in range(y_start, exc_end + 1):
                    cr, ok_r = _pick(r, prev_c)
                    res[r] = prev_c = cr if (ok_r and cr is not None) else prev_c
                    if grad_cont and ok_r and cr is not None:
                        trusted.append((r, cr))
            else:
                y0, y1 = y_start - 1, (exit_y if returned else exc_end)
                anc_e = _modelo(max(1, y_start - 12)) if not returned and y_start >= 13 and max(abs(s) for s in anc[2]) <= 0.35 else anc
                _interp_seg(res, y_start, exc_end, y0, res[y0] if y0 >= 0 else bg, y1, exit_rgb if returned else _pred_anc(y1, anc if _rgb_dist(_pred_anc(y1, anc), _pred_anc(y1, anc_e)) <= 6 else anc_e))
            if returned and exit_y <= y:
                _aceitar_pts([(exit_y, exit_rgb)], exit_y, res, trusted)
            y = max(y + 1, exc_end + 1)
    return res

def _extrair_bordas_linhas(px: Any, w: int, h: int, y_start: int = 0, y_end: int | None = None) -> tuple[list[tuple[int, int, int]], list[bool], list[tuple[int, int, int]], list[tuple[int, int, int]]]:
    y_hi, xs_l, xs_r = (h if y_end is None else min(h, y_end)), list(range(min(4, w))), list(range(max(0, w - 4), w))
    meds = [(_mediana_rgb(ls), _mediana_rgb(rs), _mediana_rgb(ls + rs)) for y in range(y_start, y_hi) for ls, rs in [([px[x, y][:3] for x in xs_l], [px[x, y][:3] for x in xs_r])]]
    return [m[2] for m in meds], [_rgb_dist(m[0], m[1]) <= 36 for m in meds], [m[0] for m in meds], [m[1] for m in meds]

def _estimar_bg_por_linha(px: Any, w: int, h: int, bg: tuple[int, int, int], y_start: int = 0, y_end: int | None = None) -> list[tuple[int, int, int]]:
    y_hi = h if y_end is None else min(h, y_end)
    if w <= 0 or y_hi <= y_start:
        return [bg] * max(0, y_hi - y_start)
    cands, valid, ls_meds, rs_meds = _extrair_bordas_linhas(px, w, h, y_start, y_hi)
    return _estimar_bg_cands(cands, valid, bg, ls_meds, rs_meds)

def _cons_rows(rows: list[tuple[int, int, int]], cands: list[tuple[int, int, int]], ls: list[tuple[int, int, int]], rs: list[tuple[int, int, int]], start: int = 0) -> int:
    return sum(1 for i in range(start, len(rows)) if _rgb_dist(ls[i], rs[i]) <= 8 and _rgb_dist(rows[i], cands[i]) <= 6)

def _estimar_bg_2x2(px: Any, w: int, h: int, bg: tuple[int, int, int]) -> list[tuple[int, int, int]]:
    hh = h // 2
    top_rows = _estimar_bg_por_linha(px, w, h, bg, 0, hh)
    if w <= 0 or h <= hh:
        return top_rows
    ys_m, xs_l, xs_r = range(hh, min(h, hh + 4)), list(range(min(4, w))), list(range(max(0, w - 4), w))
    ls_m, rs_m = _mediana_rgb([px[x, y][:3] for y in ys_m for x in xs_l]), _mediana_rgb([px[x, y][:3] for y in ys_m for x in xs_r])
    cands_b, valid_b, ls_b, rs_b = _extrair_bordas_linhas(px, w, h, hh, h)
    top_end = top_rows[-1] if top_rows else bg
    cands_try: list[tuple[int, int, int]] = [bg, top_end, ls_m, rs_m]
    if cons_idx := [i for i in range(len(cands_b)) if _rgb_dist(ls_b[i], rs_b[i]) <= 8]:
        cands_try.append(cands_b[cons_idx[0]])
        cands_try.extend([cands_b[i] for i in cons_idx[1:] if _rgb_dist(cands_b[i], cands_b[cons_idx[0]]) > 12][:1])
    best_key, bg_bot, bot_rows = None, bg, []
    for cand in dict.fromkeys(cands_try):
        rows = _estimar_bg_cands(cands_b, valid_b, cand, ls_b, rs_b)
        jumps = sum(1 for i in range(1, len(rows)) if _rgb_dist(rows[i], rows[i - 1]) > 6)
        key = (_cons_rows(rows, cands_b, ls_b, rs_b), -jumps, -min(_rgb_dist(cand, ls_m), _rgb_dist(cand, rs_m)), 1 if _rgb_dist(cand, top_end) <= 12 else 0, -_rgb_dist(cand, bg))
        if best_key is None or key > best_key:
            best_key, bg_bot, bot_rows = key, cand, rows
    if _rgb_dist(bg_bot, bg) > 20:
        cands_f, valid_f, ls_f, rs_f = _extrair_bordas_linhas(px, w, h, 0, h)
        bg_full = _estimar_bg_cands(cands_f, valid_f, bg, ls_f, rs_f)
        tail_ok = any(_rgb_dist(b, bg_full[i]) <= 20 for i in range(max(hh, h - 8), h) for b in (ls_f[i], rs_f[i]))
        if min(_rgb_dist(ls_m, bg_full[hh]), _rgb_dist(rs_m, bg_full[hh])) > 20 and tail_ok and _cons_rows(bg_full, cands_f, ls_f, rs_f, hh) > _cons_rows(bot_rows, cands_b, ls_b, rs_b):
            return bg_full
    return top_rows + bot_rows

def _analisar_mascara(quad_original: Image.Image) -> dict[str, Any]:
    ow, oh = (orig := quad_original.convert("RGBA")).size
    usar_alfa, bg_orig, px_orig = _tem_alfa_transparente(orig), _estimar_fundo_rgb(orig), _rgba_px(orig)
    bg_linhas_orig = None if usar_alfa else _estimar_bg_por_linha(px_orig, ow, oh, bg_orig)

    def _frac_borda(xs: range, ys: range) -> float:
        total = len(xs) * len(ys)
        return (sum(1 for y in ys for x in xs if _eh_foreground(px_orig[x, y], bg_linhas_orig[y] if bg_linhas_orig is not None else bg_orig, usar_alfa)) / float(total)) if total else 0.0

    borda, altura_sem_piso = 2, max(1, int(oh * 0.72))
    clip_top, clip_left, clip_right = _frac_borda(range(ow), range(min(borda, oh))), _frac_borda(range(min(borda, ow)), range(altura_sem_piso)), _frac_borda(range(max(0, ow - borda), ow), range(altura_sem_piso))
    w, h = (img := _reduzir_para_analise(orig)).size
    px, bg = _rgba_px(img), _estimar_fundo_rgb(img)
    bg_linhas = None if usar_alfa else _estimar_bg_por_linha(px, w, h, bg)
    fg_coords: list[tuple[int, int, tuple[int, int, int]]] = []
    fg_by_y: dict[int, list[tuple[int, tuple[int, int, int]]]] = {}
    min_x, min_y, max_x, max_y, total = w, h, -1, -1, w * h
    for y in range(h):
        bg_row, fg_row = (bg_linhas[y] if bg_linhas is not None else bg), []
        for x in range(w):
            r, g, b, a = px[x, y]
            if _eh_foreground((r, g, b, a), bg_row, usar_alfa):
                fg_coords.append((x, y, (r, g, b)))
                fg_row.append((x, (r, g, b)))
                min_x, max_x, min_y, max_y = min(min_x, x), max(max_x, x), min(min_y, y), max(max_y, y)
        if fg_row:
            fg_by_y[y] = fg_row
    return {"img": img, "w": w, "h": h, "cobertura": len(fg_coords) / float(total) if total else 0.0, "bbox": (min_x, min_y, max_x, max_y) if max_x >= min_x and max_y >= min_y else None, "fg_coords": fg_coords, "fg_by_y": fg_by_y, "clip_top": clip_top, "clip_left": clip_left, "clip_right": clip_right}

def _fg_by_y(info: dict[str, Any]) -> dict[int, list[tuple[int, tuple[int, int, int]]]]:
    if (fg_by_y_raw := info.get("fg_by_y")) is not None:
        return fg_by_y_raw
    mapa: dict[int, list[tuple[int, tuple[int, int, int]]]] = {}
    for x, y, rgb in info["fg_coords"]:
        mapa.setdefault(y, []).append((x, rgb))
    return mapa

def dividir_quadrantes(img: Image.Image, layout: str = "auto") -> tuple[str, dict[str, Image.Image]]:
    """Separa folha 2x2 (TL=front, TR=right, BL=back, BR=3/4) ou retorna render unico."""
    w, h = (rgba := img.convert("RGBA")).size
    if layout == "single" or w < 32 or h < 32:
        return "single", {"front": rgba}
    if layout == "auto":
        usar_alfa, bg, px = _tem_alfa_transparente(rgba), _estimar_fundo_rgb(rgba), _rgba_px(rgba)
        bg_linhas = None if usar_alfa else _estimar_bg_2x2(px, w, h, bg)
        def _bg_y(y: int) -> tuple[int, int, int]: return bg_linhas[y] if bg_linhas is not None else bg
        mid_x, mid_y = w // 2, h // 2
        h_sem_piso, band_x, band_y = max(1, int(mid_y * 0.72)), max(2, min(8, w // 40)), max(2, min(8, h // 40))
        ys_sem_piso, sx, sy = list(range(h_sem_piso)) + list(range(mid_y, min(h, mid_y + h_sem_piso))), max(1, mid_x // 64), max(1, mid_y // 64)
        q_ok = [
            (tot := len(range(*xs_r)) * len(range(*ys_r))) > 0 and sum(1 for y in range(*ys_r) for x in range(*xs_r) if _eh_foreground(px[x, y], _bg_y(y), usar_alfa)) >= max(4, int(0.006 * tot)) and any(px[x, y] != px[xs_r[0], ys_r[0]] for y in range(*ys_r) for x in range(*xs_r))
            for xs_r, ys_r in (((0, mid_x, sx), (0, mid_y, sy)), ((mid_x, w, sx), (0, mid_y, sy)), ((0, mid_x, sx), (mid_y, h, sy)), ((mid_x, w, sx), (mid_y, h, sy)))
        ]
        if not q_ok[0] or sum(q_ok) < 2:
            return "single", {"front": rgba}
        min_v = min(sum(1 for y in ys_sem_piso if _eh_foreground(px[x, y], _bg_y(y), usar_alfa)) / float(len(ys_sem_piso)) for x in range(max(0, mid_x - band_x), min(w, mid_x + band_x + 1)))
        min_h = min(sum(1 for x in range(w) if _eh_foreground(px[x, y], _bg_y(y), usar_alfa)) / float(w) for y in range(max(0, mid_y - band_y), min(h, mid_y + band_y + 1)))
        ponte_h = any(_eh_foreground(px[x, mid_y - 1], _bg_y(mid_y - 1), usar_alfa) and _eh_foreground(px[x, mid_y], _bg_y(mid_y), usar_alfa) for x in range(w))
        ponte_v = any(_eh_foreground(px[mid_x - 1, y], _bg_y(y), usar_alfa) and _eh_foreground(px[mid_x, y], _bg_y(y), usar_alfa) for y in ys_sem_piso)
        ponte_bot = not q_ok[1] and any(_eh_foreground(px[mid_x - 1, y], _bg_y(y), usar_alfa) and _eh_foreground(px[mid_x, y], _bg_y(y), usar_alfa) for y in range(mid_y, h))
        if min_v > 0.01 or min_h > 0.005 or ponte_h or ponte_v or ponte_bot:
            return "single", {"front": rgba}
    hw, hh = w // 2, h // 2
    return "turntable", {"front": rgba.crop((0, 0, hw, hh)), "right": rgba.crop((hw, 0, w, hh)), "back": rgba.crop((0, hh, hw, h)), "three_quarter": rgba.crop((hw, hh, w, h))}

def _checar_silhueta_e_enquadramento(nome: str, info: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    cov, clip_top, clip_left, clip_right = info["cobertura"], info["clip_top"], info["clip_left"], info["clip_right"]
    defeitos = ([f"silhouette_blank ({nome}): cobertura de primeiro plano {cov:.3f} < 0.015"] if cov < 0.015 else []) + ([f"silhouette_clipped ({nome}): recorte nas bordas (top={clip_top:.2f}, left={clip_left:.2f}, right={clip_right:.2f}, cov={cov:.2f})"] if max(clip_top, clip_left, clip_right) > 0.15 or cov > 0.92 else [])
    return defeitos, {"cobertura": round(cov, 4), "clip_top": round(clip_top, 4), "clip_left": round(clip_left, 4), "clip_right": round(clip_right, 4)}

def _extrair_silhueta_normalizada(info: dict[str, Any], tamanho: int = 64, margem: int = MARGEM_CANVAS_G15) -> tuple[list[int], list[int], tuple[float, float, float], float]:
    px = _rgba_px(mask_img := Image.new("L", (max(1, int(info["w"])), max(1, int(info["h"]))), 0))
    for x, y, _rgb in info["fg_coords"]:
        px[x, y] = 255
    mask_canvas = list(mask_img.resize((tamanho, tamanho), Image.Resampling.NEAREST).getdata())
    if (bbox := info["bbox"]) is None or not info["fg_coords"]:
        return [0] * (tamanho * tamanho), mask_canvas, (0.0, 0.0, 0.0), 1.0
    bw, bh = max(1, bbox[2] - bbox[0] + 1), max(1, bbox[3] - bbox[1] + 1)
    nw, nh = max(1, int(round(bw * (ef := max(1, tamanho - 2 * margem) / float(max(bw, bh)))))), max(1, int(round(bh * ef)))
    canvas = Image.new("L", (tamanho, tamanho), 0)
    canvas.paste(mask_img.crop((bbox[0], bbox[1], bbox[2] + 1, bbox[3] + 1)).resize((nw, nh), Image.Resampling.NEAREST), ((tamanho - nw) // 2, (tamanho - nh) // 2))
    return list(canvas.getdata()), mask_canvas, _media_rgb([rgb for _, _, rgb in info["fg_coords"]]), bw / float(bh)

def _iou_binario(m1: list[int], m2: list[int]) -> float:
    inter, uniao = sum(1 for a, b in zip(m1, m2) if a > 0 and b > 0), sum(1 for a, b in zip(m1, m2) if a > 0 or b > 0)
    return inter / float(uniao) if uniao > 0 else 0.0

def avaliar_fidelidade_concept_3d(concept_png: Path | str, render_png: Path | str, *, limiar_iou: float = LIMIAR_IOU_G15, limiar_aspect: float = LIMIAR_ASPECT_G15, limiar_score: float = 0.55) -> dict[str, Any]:
    """Compara silhueta/aspecto/cor entre concept 2D e render 3D (portao G15)."""
    c_path, r_path = Path(concept_png), Path(render_png)
    for p_chk, label in ((c_path, "concept"), (r_path, "render")):
        if not p_chk.is_file():
            raise FileNotFoundError(f"{label} nao encontrado: {p_chk}")
    with Image.open(c_path) as im_c, Image.open(r_path) as im_r:
        c_rgba, r_rgba = im_c.convert("RGBA"), im_r.convert("RGBA")
    layout_r, quads_r = dividir_quadrantes(r_rgba, layout="auto")
    r_view = quads_r["front"] if (layout_r == "turntable" and sum(1 for q in quads_r.values() if _analisar_mascara(q)["cobertura"] >= 0.005) >= 2) else r_rgba
    info_c, info_r = _analisar_mascara(c_rgba), _analisar_mascara(r_view)
    defeitos = (["concept_silhouette_blank: concept sem silhueta de primeiro plano"] if (info_c["cobertura"] < 0.005 or info_c["bbox"] is None) else []) + (["render_silhouette_blank: render sem silhueta de primeiro plano"] if (info_r["cobertura"] < 0.005 or info_r["bbox"] is None) else [])
    if defeitos:
        return {"ok": True, "aprovado": False, "concept": str(c_path), "render": str(r_path), "score": 0.0, "iou_silhueta": 0.0, "iou_canvas": 0.0, "aspect_sim": 0.0, "cor_sim": 0.0, "defeitos": defeitos, "metricas": {"cobertura_concept": round(info_c["cobertura"], 4), "cobertura_render": round(info_r["cobertura"], 4), "layout_render": layout_r}}
    norm_c, canvas_c, rgb_c, ar_c = _extrair_silhueta_normalizada(info_c)
    norm_r, canvas_r, rgb_r, ar_r = _extrair_silhueta_normalizada(info_r)
    iou_silhueta, iou_canvas = _iou_binario(norm_c, norm_r), _iou_binario(canvas_c, canvas_r)
    aspect_sim = min(ar_c, ar_r) / max(ar_c, ar_r) if max(ar_c, ar_r) > 0.0 else 0.0
    cor_sim = max(0.0, 1.0 - (chrom_delta := math.sqrt(sum((a - b) ** 2 for a, b in zip(rgb_c, rgb_r)))) / math.sqrt(3.0))
    score = 0.65 * iou_silhueta + 0.20 * aspect_sim + 0.15 * cor_sim
    defeitos = ([f"g15_silhouette_mismatch: iou={iou_silhueta:.3f} < {limiar_iou:.2f}"] if iou_silhueta < limiar_iou else []) + ([f"g15_aspect_mismatch: aspect_sim={aspect_sim:.3f} < {limiar_aspect:.2f} (concept={ar_c:.3f}, render={ar_r:.3f})"] if aspect_sim < limiar_aspect else []) + ([f"g15_low_fidelity_score: score={score:.3f} < {limiar_score:.2f}"] if score < limiar_score else [])
    return {"ok": True, "aprovado": len(defeitos) == 0, "concept": str(c_path), "render": str(r_path), "score": round(score, 4), "iou_silhueta": round(iou_silhueta, 4), "iou_canvas": round(iou_canvas, 4), "aspect_sim": round(aspect_sim, 4), "cor_sim": round(cor_sim, 4), "defeitos": defeitos, "metricas": {"cobertura_concept": round(info_c["cobertura"], 4), "cobertura_render": round(info_r["cobertura"], 4), "aspect_concept": round(ar_c, 4), "aspect_render": round(ar_r, 4), "chrom_delta": round(chrom_delta, 4), "layout_render": layout_r}}

avaliar_fidelidade_g15 = avaliar_fidelidade_concept_3d
