"""Extrusao 2D limpa de silhuetas PNG (armas e capas) em ``bpy``/``bmesh`` puro.

Roda dentro do Python embutido do Blender 4.2+ usando apenas ``bpy``, ``bmesh``, ``mathutils``
e a biblioteca padrao (sem Pillow nem numpy, invariante I9).
"""

from __future__ import annotations

import math
import os
from array import array

import bmesh
import bpy

_MOORE_DIRS = (
    (-1, 0),
    (-1, 1),
    (0, 1),
    (1, 1),
    (1, 0),
    (1, -1),
    (0, -1),
    (-1, -1),
)


def _prox_pot(n: int, minimo: int = 64, maximo: int = 1024) -> int:
    """Retorna potencia de 2 valida mais proxima/teto dentro de ``[minimo, maximo]``."""
    v = max(minimo, min(maximo, int(n)))
    if (v & (v - 1)) == 0:
        return v
    p = 1
    while p < v and p < maximo:
        p <<= 1
    return max(minimo, min(maximo, p))


def _amostrar_mascara(
    buf: array, w: int, h: int, max_dim: int = 128
) -> tuple[list[list[bool]], int, int, bool]:
    """Reduz a imagem para grade binaria ``[gh][gw]`` preservando proporcao."""
    escala = min(1.0, float(max_dim) / float(max(w, h)))
    gw = max(8, min(w, int(round(w * escala))))
    gh = max(8, min(h, int(round(h * escala))))

    passo_alfa = max(1, (w * h) // 65536)
    min_alpha = 1.0
    for idx in range(3, len(buf), 4 * passo_alfa):
        a = buf[idx]
        if a < min_alpha:
            min_alpha = a
            if min_alpha < 0.99:
                break
    usa_alfa = min_alpha < 0.99

    grade_rgb: list[list[tuple[float, float, float]]] = []
    grade_a: list[list[float]] = []

    for gy in range(gh):
        y0 = int(gy * h / gh)
        y1 = max(y0 + 1, int((gy + 1) * h / gh))
        sy = max(1, (y1 - y0) // 3)
        linha_rgb: list[tuple[float, float, float]] = []
        linha_a: list[float] = []
        for gx in range(gw):
            x0 = int(gx * w / gw)
            x1 = max(x0 + 1, int((gx + 1) * w / gw))
            sx = max(1, (x1 - x0) // 3)
            sr = sg = sb = sa = 0.0
            max_a = 0.0
            n = 0
            for py in range(y0, y1, sy):
                base_row = py * w * 4
                for px in range(x0, x1, sx):
                    idx = base_row + px * 4
                    sr += buf[idx]
                    sg += buf[idx + 1]
                    sb += buf[idx + 2]
                    a = buf[idx + 3]
                    sa += a
                    if a > max_a:
                        max_a = a
                    n += 1
            inv = 1.0 / max(n, 1)
            linha_rgb.append((sr * inv, sg * inv, sb * inv))
            linha_a.append(max(sa * inv, max_a * 0.85))
        grade_rgb.append(linha_rgb)
        grade_a.append(linha_a)

    mask = [[False] * gw for _ in range(gh)]
    if usa_alfa:
        for gy in range(gh):
            for gx in range(gw):
                mask[gy][gx] = grade_a[gy][gx] >= 0.45
    else:
        cantos = [
            grade_rgb[0][0],
            grade_rgb[0][gw - 1],
            grade_rgb[gh - 1][0],
            grade_rgb[gh - 1][gw - 1],
        ]
        bg = tuple((sorted(c[k] for c in cantos)[1] + sorted(c[k] for c in cantos)[2]) * 0.5 for k in range(3))
        limiar_sq = 0.12 * 0.12
        for gy in range(gh):
            for gx in range(gw):
                r, g, b = grade_rgb[gy][gx]
                dr = r - bg[0]
                dg = g - bg[1]
                db = b - bg[2]
                mask[gy][gx] = (dr * dr + dg * dg + db * db) > limiar_sq

    return mask, gw, gh, usa_alfa


def _maior_componente_8(mask: list[list[bool]], gw: int, gh: int) -> list[tuple[int, int]]:
    """Seleciona a maior componente 8-conexa de pixels ativos."""
    vistos = [[False] * gw for _ in range(gh)]
    melhor: list[tuple[int, int]] = []
    for sy in range(gh):
        for sx in range(gw):
            if not mask[sy][sx] or vistos[sy][sx]:
                continue
            pilha = [(sx, sy)]
            vistos[sy][sx] = True
            comp: list[tuple[int, int]] = []
            while pilha:
                cx, cy = pilha.pop()
                comp.append((cx, cy))
                for dx, dy in _MOORE_DIRS:
                    nx, ny = cx + dx, cy + dy
                    if 0 <= nx < gw and 0 <= ny < gh and mask[ny][nx] and not vistos[ny][nx]:
                        vistos[ny][nx] = True
                        pilha.append((nx, ny))
            if len(comp) > len(melhor):
                melhor = comp
    return melhor


def _filtrar_buracos_pequenos(
    grade: list[list[bool]], pw: int, ph: int, min_pixels: int | None = None
) -> list[list[tuple[int, int]]]:
    """Preenche micro-ruidos internos e extrai contornos de recortes reais >= min_pixels."""
    if min_pixels is None:
        min_pixels = max(12, int(pw * ph * 0.0012))
    ext = [[False] * pw for _ in range(ph)]
    pilha = [(0, 0)]
    ext[0][0] = True
    while pilha:
        cx, cy = pilha.pop()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = cx + dx, cy + dy
            if 0 <= nx < pw and 0 <= ny < ph and not ext[ny][nx] and not grade[ny][nx]:
                ext[ny][nx] = True
                pilha.append((nx, ny))

    visitado = [[False] * pw for _ in range(ph)]
    buracos_reais: list[list[tuple[int, int]]] = []
    for y in range(ph):
        for x in range(pw):
            if grade[y][x] or ext[y][x] or visitado[y][x]:
                continue
            comp: list[tuple[int, int]] = []
            q = [(x, y)]
            visitado[y][x] = True
            while q:
                px, py = q.pop()
                comp.append((px, py))
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = px + dx, py + dy
                    if (
                        0 <= nx < pw
                        and 0 <= ny < ph
                        and not visitado[ny][nx]
                        and not grade[ny][nx]
                        and not ext[ny][nx]
                    ):
                        visitado[ny][nx] = True
                        q.append((nx, ny))
            if len(comp) >= min_pixels:
                buraco_grade = [[False] * pw for _ in range(ph)]
                for hx, hy in comp:
                    buraco_grade[hy][hx] = True
                exp_b = _expandir_2x2(buraco_grade, pw, ph)
                contorno_b = _tracar_moore(exp_b, pw + 1, ph + 1)
                if len(contorno_b) >= 4:
                    buracos_reais.append(contorno_b)
            # Preenche o buraco na grade externa para tracado limpo do perimetro exterior
            for hx, hy in comp:
                grade[hy][hx] = True
    return buracos_reais


def _expandir_2x2(grade: list[list[bool]], pw: int, ph: int) -> list[list[bool]]:
    """Garante espessura minima de 2 celulas (evita espinhos de 1px no Moore-Neighbor)."""
    out = [[False] * (pw + 1) for _ in range(ph + 1)]
    for y in range(ph):
        for x in range(pw):
            if grade[y][x]:
                out[y][x] = True
                out[y][x + 1] = True
                out[y + 1][x] = True
                out[y + 1][x + 1] = True
    return out


def _tracar_moore(grade: list[list[bool]], pw: int, ph: int) -> list[tuple[int, int]]:
    """Extrai contorno externo usando Moore-Neighbor (criterio de parada por transicao)."""
    sx = sy = -1
    for y in range(ph):
        for x in range(pw):
            if grade[y][x]:
                sx, sy = x, y
                break
        if sx >= 0:
            break
    if sx < 0:
        return []

    contorno: list[tuple[int, int]] = [(sx, sy)]
    cx, cy = sx, sy
    back_dir = 0  # W=(sx-1, sy) e garantidamente fundo
    primeiro_passo: tuple[int, int, int] | None = None
    vistos: set[tuple[int, int, int]] = {(sx, sy, 0)}
    max_passos = pw * ph * 4 + 16

    for _ in range(max_passos):
        achou = False
        prev_bg_dir = back_dir
        for offset in range(1, 9):
            d = (back_dir + offset) % 8
            dx, dy = _MOORE_DIRS[d]
            nx, ny = cx + dx, cy + dy
            if 0 <= nx < pw and 0 <= ny < ph and grade[ny][nx]:
                bx = (cx + _MOORE_DIRS[prev_bg_dir][0]) - nx
                by = (cy + _MOORE_DIRS[prev_bg_dir][1]) - ny
                novo_back = 0
                for idx_d, (ddx, ddy) in enumerate(_MOORE_DIRS):
                    if ddx == bx and ddy == by:
                        novo_back = idx_d
                        break
                estado = (nx, ny, novo_back)
                if primeiro_passo is None:
                    primeiro_passo = estado
                elif estado == primeiro_passo or estado in vistos:
                    if len(contorno) > 1 and contorno[-1] == (sx, sy):
                        contorno.pop()
                    return contorno
                vistos.add(estado)
                cx, cy = nx, ny
                back_dir = novo_back
                achou = True
                if (cx, cy) != contorno[-1]:
                    contorno.append((cx, cy))
                break
            prev_bg_dir = d
        if not achou:
            break
    return contorno


def _dist_ponto_segmento(
    px: float, py: float, ax: float, ay: float, bx: float, by: float
) -> float:
    vx = bx - ax
    vy = by - ay
    denom = vx * vx + vy * vy
    if denom <= 1e-18:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * vx + (py - ay) * vy) / denom
    if t < 0.0:
        t = 0.0
    elif t > 1.0:
        t = 1.0
    dx = px - (ax + t * vx)
    dy = py - (ay + t * vy)
    return math.hypot(dx, dy)


def _rdp_aberto(pts: list[tuple[float, float]], eps: float) -> list[tuple[float, float]]:
    if len(pts) <= 2:
        return list(pts)
    ax, ay = pts[0]
    bx, by = pts[-1]
    max_d = -1.0
    idx_max = 0
    for i in range(1, len(pts) - 1):
        d = _dist_ponto_segmento(pts[i][0], pts[i][1], ax, ay, bx, by)
        if d > max_d:
            max_d = d
            idx_max = i
    if max_d > eps:
        esq = _rdp_aberto(pts[: idx_max + 1], eps)
        dir_ = _rdp_aberto(pts[idx_max:], eps)
        return esq[:-1] + dir_
    return [pts[0], pts[-1]]


def _rdp_fechado(pts: list[tuple[float, float]], eps: float) -> list[tuple[float, float]]:
    if len(pts) <= 4:
        return list(pts)
    p0 = pts[0]
    idx_far = max(range(1, len(pts)), key=lambda i: (pts[i][0] - p0[0]) ** 2 + (pts[i][1] - p0[1]) ** 2)
    c1 = _rdp_aberto(pts[: idx_far + 1], eps)
    c2 = _rdp_aberto(pts[idx_far:] + [pts[0]], eps)
    return c1[:-1] + c2[:-1]


def _seg_cruzam(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
    d: tuple[float, float],
) -> bool:
    def orient(p: tuple[float, float], q: tuple[float, float], r: tuple[float, float]) -> float:
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    if max(a[0], b[0]) < min(c[0], d[0]) - 1e-9 or max(c[0], d[0]) < min(a[0], b[0]) - 1e-9:
        return False
    if max(a[1], b[1]) < min(c[1], d[1]) - 1e-9 or max(c[1], d[1]) < min(a[1], b[1]) - 1e-9:
        return False
    o1 = orient(a, b, c)
    o2 = orient(a, b, d)
    o3 = orient(c, d, a)
    o4 = orient(c, d, b)
    if (o1 > 1e-9 and o2 < -1e-9 or o1 < -1e-9 and o2 > 1e-9) and (
        o3 > 1e-9 and o4 < -1e-9 or o3 < -1e-9 and o4 > 1e-9
    ):
        return True
    return False


def _tem_auto_intersecao(poly: list[tuple[float, float]]) -> bool:
    n = len(poly)
    if n < 4:
        return True
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        for j in range(i + 2, n):
            if i == 0 and j == n - 1:
                continue
            c, d = poly[j], poly[(j + 1) % n]
            if _seg_cruzam(a, b, c, d):
                return True
    return False


def _area_assinada(poly: list[tuple[float, float]]) -> float:
    s = 0.0
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return 0.5 * s


def _limpar_colineares_e_duplicados(
    poly: list[tuple[float, float]], min_dist: float = 1e-3, min_pts: int = 8
) -> list[tuple[float, float]]:
    if len(poly) <= min_pts:
        return list(poly)
    pts = [poly[0]]
    for p in poly[1:]:
        if math.hypot(p[0] - pts[-1][0], p[1] - pts[-1][1]) >= min_dist or len(pts) < min_pts:
            pts.append(p)
    while len(pts) > min_pts and math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) < min_dist:
        pts.pop()
    return pts


def _garantir_min_pontos(poly: list[tuple[float, float]], min_pts: int = 8) -> list[tuple[float, float]]:
    pts = list(poly)
    while len(pts) < min_pts:
        n = len(pts)
        idx_max = max(
            range(n),
            key=lambda i: (pts[(i + 1) % n][0] - pts[i][0]) ** 2 + (pts[(i + 1) % n][1] - pts[i][1]) ** 2,
        )
        a = pts[idx_max]
        b = pts[(idx_max + 1) % n]
        meio = (0.5 * (a[0] + b[0]), 0.5 * (a[1] + b[1]))
        pts.insert(idx_max + 1, meio)
    return pts


def _poligono_caixa_fallback() -> list[tuple[float, float]]:
    return [
        (-0.14, 0.0),
        (0.14, 0.0),
        (0.14, 0.33),
        (0.14, 0.67),
        (0.14, 1.0),
        (-0.14, 1.0),
        (-0.14, 0.67),
        (-0.14, 0.33),
    ]


def _simplificar_e_escalar(
    contorno: list[tuple[int, int]], gw: int, gh: int, pad: int = 2
) -> tuple[list[tuple[float, float]], tuple[float, float, float, float]]:
    """Simplifica contorno com RDP para ``[8, 48]`` vertices e normaliza Z em ``[0, 1]``."""
    if len(contorno) < 4:
        return _poligono_caixa_fallback(), (0.0, 1.0, 0.0, 1.0)

    pts_f = [(float(x), float(y)) for x, y in contorno]
    xs = [p[0] for p in pts_f]
    ys = [p[1] for p in pts_f]
    min_ex, max_ex = min(xs), max(xs)
    min_ey, max_ey = min(ys), max(ys)
    dx_g = max_ex - min_ex
    dy_g = max_ey - min_ey
    if dx_g < 1.0 or dy_g < 1.0:
        return _poligono_caixa_fallback(), (0.0, 1.0, 0.0, 1.0)

    eps = max(0.35, max(dx_g, dy_g) * 0.009)
    escolhido: list[tuple[float, float]] | None = None
    for _ in range(18):
        cand = _rdp_fechado(pts_f, eps)
        cand = _limpar_colineares_e_duplicados(cand, min_dist=0.25, min_pts=8)
        if len(cand) > 64:
            eps *= 1.35
            continue
        if len(cand) < 8:
            eps *= 0.6
            if eps < 0.05:
                cand = _garantir_min_pontos(cand, 8)
            else:
                continue
        if _tem_auto_intersecao(cand) or abs(_area_assinada(cand)) < 1.0:
            eps *= 0.55
            if eps < 0.05:
                break
            continue
        escolhido = cand
        break

    if escolhido is None:
        # Tenta contorno reduzido uniforme ou fallback seguro
        cand = _rdp_fechado(pts_f, max(0.25, max(dx_g, dy_g) * 0.015))
        cand = _garantir_min_pontos(_limpar_colineares_e_duplicados(cand, min_dist=0.25, min_pts=8), 8)
        if len(cand) > 96:
            passo = max(1, len(cand) // 64)
            cand = cand[::passo]
        if _tem_auto_intersecao(cand) or abs(_area_assinada(cand)) < 1.0:
            return _poligono_caixa_fallback(), (0.0, 1.0, 0.0, 1.0)
        escolhido = cand

    if _area_assinada(escolhido) < 0.0:
        escolhido.reverse()

    xs_e = [p[0] for p in escolhido]
    ys_e = [p[1] for p in escolhido]
    min_x_e, max_x_e = min(xs_e), max(xs_e)
    min_y_e, max_y_e = min(ys_e), max(ys_e)
    cx_e = 0.5 * (min_x_e + max_x_e)
    span_z = max(max_y_e - min_y_e, 1e-6)

    poly_3d = [(-((px - cx_e) / span_z), (py - min_y_e) / span_z) for px, py in escolhido]
    # Recalcula no espaco 3D e garante CCW + altura exata 1.0
    if _area_assinada(poly_3d) < 0.0:
        poly_3d.reverse()

    u_min = max(0.0, min(1.0, (min_x_e - pad) / float(gw)))
    u_max = max(0.0, min(1.0, (max_x_e - pad) / float(gw)))
    v_min = max(0.0, min(1.0, (min_y_e - pad) / float(gh)))
    v_max = max(0.0, min(1.0, (max_y_e - pad) / float(gh)))
    if u_max <= u_min + 1e-4 or v_max <= v_min + 1e-4:
        uv_bbox = (0.0, 1.0, 0.0, 1.0)
    else:
        uv_bbox = (u_min, u_max, v_min, v_max)
    return poly_3d, uv_bbox


def _largura_na_altura(poly: list[tuple[float, float]], z_alvo: float) -> float:
    """Largura horizontal (max_x - min_x) do poligono 2D na cota z_alvo."""
    xs: list[float] = []
    n = len(poly)
    for i in range(n):
        ax, az = poly[i]
        bx, bz = poly[(i + 1) % n]
        if (az <= z_alvo < bz) or (bz <= z_alvo < az):
            t = (z_alvo - az) / (bz - az)
            xs.append(ax + t * (bx - ax))
    if len(xs) < 2:
        return 0.0
    return max(xs) - min(xs)


def _normalizar_poly_3d(pts: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Centraliza X em 0 e normaliza Z para [0, 1] mantendo CCW."""
    xs = [p[0] for p in pts]
    zs = [p[1] for p in pts]
    cx = 0.5 * (min(xs) + max(xs))
    z0 = min(zs)
    span_z = max(max(zs) - z0, 1e-6)
    out = [((px - cx) / span_z, (pz - z0) / span_z) for px, pz in pts]
    if _area_assinada(out) < 0.0:
        out.reverse()
    return out


def _simplificar_buracos(
    buracos_raw: list[list[tuple[int, int]]],
    contorno_ext: list[tuple[int, int]],
) -> list[list[tuple[float, float]]]:
    """Simplifica e mapeia buracos no mesmo sistema normalizado do contorno externo."""
    if not buracos_raw or len(contorno_ext) < 4:
        return []
    xs_e = [float(x) for x, _y in contorno_ext]
    ys_e = [float(y) for _x, y in contorno_ext]
    cx_e = 0.5 * (min(xs_e) + max(xs_e))
    min_y_e = min(ys_e)
    span_z = max(max(ys_e) - min_y_e, 1e-6)
    out: list[list[tuple[float, float]]] = []
    for raw in buracos_raw:
        pts_f = [(float(x), float(y)) for x, y in raw]
        cand = _rdp_fechado(pts_f, max(0.35, span_z * 0.008))
        cand = _limpar_colineares_e_duplicados(cand, min_dist=0.25, min_pts=4)
        if len(cand) < 4:
            continue
        poly_b = [(-((px - cx_e) / span_z), (py - min_y_e) / span_z) for px, py in cand]
        if abs(_area_assinada(poly_b)) < 1e-4:
            continue
        if _area_assinada(poly_b) > 0.0:
            poly_b.reverse()  # buracos CW para tessellate_polygon
        out.append(poly_b)
    return out


def _transformar_lista_com_ref(
    pts: list[tuple[float, float]],
    cx: float,
    z0: float,
    span_z: float,
    inverter: bool = False,
) -> list[tuple[float, float]]:
    out = [((px - cx) / span_z, (pz - z0) / span_z) for px, pz in pts]
    if inverter:
        out.reverse()
    return out


def _orientar_arma_para_empunhadura(
    poly: list[tuple[float, float]],
    modo: str,
    pivot: str,
    holes: list[list[tuple[float, float]]] | None = None,
) -> tuple[list[tuple[float, float]], int, list[list[tuple[float, float]]]]:
    """Garante arma em pe com ponta para cima (+Z) quando pivot=='empunhadura'."""
    holes_out = [list(h) for h in (holes or [])]
    if modo != "arma" or len(poly) < 3:
        return poly, 0, holes_out

    pts = list(poly)
    rotacao = 0
    xs = [p[0] for p in pts]
    zs = [p[1] for p in pts]
    dx = max(xs) - min(xs)
    dz = max(zs) - min(zs)
    if dx > 1.5 * max(dz, 1e-6):
        pts_rot = [(-pz, px) for px, pz in pts]
        xs_r = [p[0] for p in pts_rot]
        zs_r = [p[1] for p in pts_rot]
        cx_r = 0.5 * (min(xs_r) + max(xs_r))
        z0_r = min(zs_r)
        span_r = max(max(zs_r) - z0_r, 1e-6)
        pts = _normalizar_poly_3d(pts_rot)
        holes_out = [
            _transformar_lista_com_ref([(-hz, hx) for hx, hz in h], cx_r, z0_r, span_r)
            for h in holes_out
        ]
        rotacao = 90

    if pivot == "empunhadura":
        w_03 = _largura_na_altura(pts, 0.03)
        w_10 = _largura_na_altura(pts, 0.10)
        w_20 = _largura_na_altura(pts, 0.20)
        melhor_z = 0.5
        melhor_w = -1.0
        for step in range(3, 48):
            z_q = step * 0.02
            wq = _largura_na_altura(pts, z_q)
            if wq > melhor_w:
                melhor_w = wq
                melhor_z = z_q
        ponta_embaixo = (
            w_20 > 1e-4
            and w_03 < 0.50 * w_20
            and w_10 <= 0.95 * w_20
            and melhor_z > 0.50
        )
        if ponta_embaixo:
            pts_rot = [(-px, 1.0 - pz) for px, pz in pts]
            xs_r = [p[0] for p in pts_rot]
            zs_r = [p[1] for p in pts_rot]
            cx_r = 0.5 * (min(xs_r) + max(xs_r))
            z0_r = min(zs_r)
            span_r = max(max(zs_r) - z0_r, 1e-6)
            pts = _normalizar_poly_3d(pts_rot)
            holes_out = [
                _transformar_lista_com_ref([(-hx, 1.0 - hz) for hx, hz in h], cx_r, z0_r, span_r)
                for h in holes_out
            ]
            rotacao = (rotacao + 180) % 360

    return pts, rotacao, holes_out


def _dist_borda(px: float, pz: float, poly: list[tuple[float, float]]) -> float:
    n = len(poly)
    melhor = float("inf")
    for i in range(n):
        ax, az = poly[i]
        bx, bz = poly[(i + 1) % n]
        d = _dist_ponto_segmento(px, pz, ax, az, bx, bz)
        if d < melhor:
            melhor = d
    return melhor


def _ciclos_borda_bmesh(bm: bmesh.types.BMesh) -> list[list[bmesh.types.BMVert]]:
    """Percorre todas as cadeias fechadas de borda (externa + recortes internos) em ``bmesh``."""
    usadas: set[bmesh.types.BMEdge] = set()
    ciclos: list[list[bmesh.types.BMVert]] = []
    for e_ini in bm.edges:
        if not e_ini.is_boundary or e_ini in usadas:
            continue
        usadas.add(e_ini)
        inicio = e_ini.verts[0]
        atual = e_ini.verts[1]
        aresta_ant = e_ini
        ciclo = [inicio]
        while atual != inicio and len(ciclo) <= len(bm.verts) + 2:
            ciclo.append(atual)
            prox_e = None
            for e in atual.link_edges:
                if e.is_boundary and e != aresta_ant and e not in usadas:
                    prox_e = e
                    break
            if prox_e is None:
                break
            usadas.add(prox_e)
            atual = prox_e.other_vert(atual)
            aresta_ant = prox_e
        if len(ciclo) >= 3:
            ciclos.append(ciclo)
    return ciclos


def _construir_malha_solida(
    poly: list[tuple[float, float]],
    modo: str,
    uv_bbox: tuple[float, float, float, float],
    nome: str,
    rotacao_graus: int = 0,
    holes: list[list[tuple[float, float]]] | None = None,
) -> bpy.types.Mesh:
    """Triangula ``poly`` 2D (com eventuais recortes) e constroi casca dupla fechada estanque."""
    bm_2d = bmesh.new()
    try:
        construido_com_buracos = False
        if holes:
            from mathutils import Vector
            from mathutils.geometry import tessellate_polygon

            outer_ccw = list(poly)
            if _area_assinada(outer_ccw) < 0.0:
                outer_ccw.reverse()
            loops_3d = [[Vector((px, pz, 0.0)) for px, pz in outer_ccw]]
            pts_flat = [bm_2d.verts.new((px, 0.0, pz)) for px, pz in outer_ccw]
            for h in holes:
                hcw = list(h)
                if _area_assinada(hcw) > 0.0:
                    hcw.reverse()
                loops_3d.append([Vector((hx, hz, 0.0)) for hx, hz in hcw])
                pts_flat.extend(bm_2d.verts.new((hx, 0.0, hz)) for hx, hz in hcw)
            tris = tessellate_polygon(loops_3d)
            if tris:
                for i0, i1, i2 in tris:
                    try:
                        bm_2d.faces.new((pts_flat[i0], pts_flat[i1], pts_flat[i2]))
                    except ValueError:
                        pass
                construido_com_buracos = len(bm_2d.faces) > 0
            if not construido_com_buracos:
                bm_2d.clear()
        if not construido_com_buracos:
            verts_2d = [bm_2d.verts.new((px, 0.0, pz)) for px, pz in poly]
            face_2d = bm_2d.faces.new(verts_2d)
            bmesh.ops.triangulate(
                bm_2d, faces=[face_2d], quad_method="BEAUTY", ngon_method="BEAUTY"
            )

        # Subdivide arestas internas (e de borda na capa) para espinha/curvatura suave
        if modo == "capa":
            arestas_sub = list(bm_2d.edges)
        else:
            arestas_sub = [e for e in bm_2d.edges if not e.is_boundary]
        if arestas_sub and len(bm_2d.faces) <= 180:
            bmesh.ops.subdivide_edges(bm_2d, edges=arestas_sub, cuts=1, use_grid_fill=False)
            n_gons = [f for f in bm_2d.faces if len(f.verts) > 3]
            if n_gons:
                bmesh.ops.triangulate(
                    bm_2d, faces=n_gons, quad_method="BEAUTY", ngon_method="BEAUTY"
                )

        bmesh.ops.dissolve_degenerate(bm_2d, dist=1e-5, edges=list(bm_2d.edges))
        n_gons = [f for f in bm_2d.faces if len(f.verts) > 3]
        if n_gons:
            bmesh.ops.triangulate(
                bm_2d, faces=n_gons, quad_method="BEAUTY", ngon_method="BEAUTY"
            )

        bm_2d.verts.ensure_lookup_table()
        bm_2d.faces.ensure_lookup_table()

        dists: dict[int, float] = {}
        d_max = 0.0
        for v in bm_2d.verts:
            d = 0.0 if v.is_boundary else _dist_borda(v.co.x, v.co.z, poly)
            dists[v.index] = d
            if d > d_max:
                d_max = d
        d_ref = max(0.035, 0.55 * d_max)

        bm = bmesh.new()
        try:
            frente_v: dict[int, bmesh.types.BMVert] = {}
            tras_v: dict[int, bmesh.types.BMVert] = {}
            for v in bm_2d.verts:
                px = v.co.x
                pz = v.co.z
                if modo == "capa":
                    y_wrap = -0.12 * (px * px)
                    t_half = 0.0125  # espessura ~ 0.025 m
                    y_f = y_wrap + t_half
                    y_b = y_wrap - t_half
                elif modo == "escudo":
                    # Curvatura convexa frontal de escudo + espessura solida ~ 0.028 m
                    y_wrap = -0.06 * (px * px)
                    t_half = 0.014
                    y_f = y_wrap + t_half
                    y_b = y_wrap - t_half
                else:
                    z_norm = max(0.0, min(1.0, pz))
                    if z_norm < 0.28:
                        z_factor = 1.25
                    elif z_norm > 0.80:
                        z_factor = max(0.35, 1.0 - (z_norm - 0.80) / 0.25)
                    else:
                        z_factor = 1.0
                    t_rim = 0.0045
                    t_ridge = 0.0175  # espessura centro ~ 0.035 m
                    ridge = min(1.0, dists[v.index] / d_ref)
                    half_y = (t_rim + (t_ridge - t_rim) * ridge) * z_factor
                    y_f = half_y
                    y_b = -half_y
                frente_v[v.index] = bm.verts.new((px, y_f, pz))
                tras_v[v.index] = bm.verts.new((px, y_b, pz))

            for f in bm_2d.faces:
                if len(f.verts) < 3 or f.calc_area() < 1e-9:
                    continue
                vf = [frente_v[v.index] for v in f.verts]
                vb = [tras_v[v.index] for v in reversed(f.verts)]
                try:
                    bm.faces.new(vf)
                except ValueError:
                    pass
                try:
                    bm.faces.new(vb)
                except ValueError:
                    pass

            for borda in _ciclos_borda_bmesh(bm_2d):
                n_b = len(borda)
                for i in range(n_b):
                    va = borda[i]
                    vb = borda[(i + 1) % n_b]
                    fa, fb = frente_v[va.index], frente_v[vb.index]
                    ba, bb = tras_v[va.index], tras_v[vb.index]
                    for tri in ((fa, ba, bb), (fa, bb, fb)):
                        try:
                            bm.faces.new(tri)
                        except ValueError:
                            pass

            bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1e-6)
            bmesh.ops.dissolve_degenerate(bm, dist=1e-6, edges=list(bm.edges))
            slivers = [f for f in bm.faces if f.calc_area() < 1e-8]
            if slivers:
                bmesh.ops.delete(bm, geom=slivers, context="FACES")
            bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))

            xs = [v.co.x for v in bm.verts]
            zs = [v.co.z for v in bm.verts]
            x_min = min(xs) if xs else -0.5
            x_max = max(xs) if xs else 0.5
            z_min = min(zs) if zs else 0.0
            z_max = max(zs) if zs else 1.0
            dx = max(x_max - x_min, 1e-6)
            dz = max(z_max - z_min, 1e-6)
            u0, u1, v0, v1 = uv_bbox

            uv_layer = bm.loops.layers.uv.new("UVMap")
            u_ctr = 0.5 * (u0 + u1)
            v_ctr = 0.5 * (v0 + v1)
            for f in bm.faces:
                f.normal_update()
                eh_borda_lateral = abs(f.normal.y) < 0.35
                for loop in f.loops:
                    co = loop.vert.co
                    nx = (x_max - co.x) / dx
                    nz = (co.z - z_min) / dz
                    if rotacao_graus == 180:
                        tx = (co.x - x_min) / dx
                        tz = (z_max - co.z) / dz
                    elif rotacao_graus == 90:
                        tx = (z_max - co.z) / dz
                        tz = (x_max - co.x) / dx
                    elif rotacao_graus == 270:
                        tx = (co.z - z_min) / dz
                        tz = (co.x - x_min) / dx
                    else:
                        tx = nx
                        tz = nz
                    u = max(0.0, min(1.0, u0 + tx * (u1 - u0)))
                    v_uv = max(0.0, min(1.0, v0 + tz * (v1 - v0)))
                    if eh_borda_lateral and co.y < 0.0:
                        u = max(0.0, min(1.0, u + (u_ctr - u) * 0.008))
                        v_uv = max(0.0, min(1.0, v_uv + (v_ctr - v_uv) * 0.008))
                    loop[uv_layer].uv = (u, v_uv)

            malha = bpy.data.meshes.new(nome)
            bm.to_mesh(malha)
            malha.update()
            return malha
        finally:
            bm.free()
    finally:
        bm_2d.free()


def _preparar_textura(img_orig, nome: str, usa_alfa: bool):
    """Prepara imagem POT RGB limpa (sangria de borda transparente removida) e empacota."""
    w, h = int(img_orig.size[0]), int(img_orig.size[1])
    pot_w = _prox_pot(w)
    pot_h = _prox_pot(h)
    if pot_w != w or pot_h != h:
        img_orig.scale(pot_w, pot_h)
        w, h = pot_w, pot_h

    total = w * h * 4
    buf = array("f", [0.0]) * total
    img_orig.pixels.foreach_get(buf)

    if usa_alfa:
        # Preenche pixels transparentes com a media opaca e dilata 3px para eliminar halo escuro
        sr = sg = sb = 0.0
        n_op = 0
        for i in range(0, total, 4):
            if buf[i + 3] >= 0.45:
                sr += buf[i]
                sg += buf[i + 1]
                sb += buf[i + 2]
                n_op += 1
        media = (sr / n_op, sg / n_op, sb / n_op) if n_op > 0 else (0.5, 0.5, 0.5)

        ativo = [buf[i + 3] >= 0.45 for i in range(0, total, 4)]
        # Coleta fronteira inicial (pixels transparentes com vizinho opaco)
        fronteira: set[int] = set()
        for p, ok in enumerate(ativo):
            if not ok:
                continue
            x = p % w
            y = p // w
            if x > 0 and not ativo[p - 1]:
                fronteira.add(p - 1)
            if x + 1 < w and not ativo[p + 1]:
                fronteira.add(p + 1)
            if y > 0 and not ativo[p - w]:
                fronteira.add(p - w)
            if y + 1 < h and not ativo[p + w]:
                fronteira.add(p + w)

        for _ in range(3):
            if not fronteira:
                break
            preenchidos: list[tuple[int, float, float, float]] = []
            prox_fronteira: set[int] = set()
            for p in fronteira:
                if ativo[p]:
                    continue
                x = p % w
                y = p // w
                acc_r = acc_g = acc_b = 0.0
                cnt = 0
                vizinhos = []
                if x > 0:
                    vizinhos.append(p - 1)
                if x + 1 < w:
                    vizinhos.append(p + 1)
                if y > 0:
                    vizinhos.append(p - w)
                if y + 1 < h:
                    vizinhos.append(p + w)
                for np in vizinhos:
                    if ativo[np]:
                        ni = np * 4
                        acc_r += buf[ni]
                        acc_g += buf[ni + 1]
                        acc_b += buf[ni + 2]
                        cnt += 1
                    else:
                        prox_fronteira.add(np)
                if cnt > 0:
                    inv_c = 1.0 / cnt
                    preenchidos.append((p, acc_r * inv_c, acc_g * inv_c, acc_b * inv_c))
            for p, cr, cg, cb in preenchidos:
                pi = p * 4
                buf[pi] = cr
                buf[pi + 1] = cg
                buf[pi + 2] = cb
                ativo[p] = True
            fronteira = prox_fronteira

        for p, ok in enumerate(ativo):
            pi = p * 4
            if not ok:
                buf[pi] = media[0]
                buf[pi + 1] = media[1]
                buf[pi + 2] = media[2]
            buf[pi + 3] = 1.0
    else:
        for i in range(3, total, 4):
            buf[i] = 1.0

    img_out = bpy.data.images.new(f"{nome}_tex", width=w, height=h, alpha=False)
    img_out.colorspace_settings.name = "sRGB"
    img_out.pixels.foreach_set(buf)
    img_out.pack()
    if img_orig.users == 0:
        bpy.data.images.remove(img_orig)
    return img_out


def construir_malha_2d(
    imagem_png: str,
    modo: str = "arma",
    nome: str = "extrude_2d",
    saida_dir: str | None = None,
    pivot: str = "empunhadura",
) -> "bpy.types.Object":
    """Extrude uma silhueta 2D PNG para malha 3D estanque com UV frontal/traseira e material PBR."""
    img_orig = bpy.data.images.load(imagem_png, check_existing=False)
    w, h = int(img_orig.size[0]), int(img_orig.size[1])
    if w <= 0 or h <= 0:
        bpy.data.images.remove(img_orig)
        raise RuntimeError(f"imagem invalida para extrude_2d: {imagem_png}")

    buf = array("f", [0.0]) * (w * h * 4)
    img_orig.pixels.foreach_get(buf)

    mask, gw, gh, usa_alfa = _amostrar_mascara(buf, w, h, max_dim=128)
    comp = _maior_componente_8(mask, gw, gh)

    holes_poly: list[list[tuple[float, float]]] = []
    if len(comp) < 4:
        poly = _poligono_caixa_fallback()
        uv_bbox = (0.0, 1.0, 0.0, 1.0)
    else:
        pad = 2
        pw, ph = gw + 2 * pad, gh + 2 * pad
        grade = [[False] * pw for _ in range(ph)]
        for gx, gy in comp:
            grade[gy + pad][gx + pad] = True
        buracos_raw = _filtrar_buracos_pequenos(grade, pw, ph)
        exp = _expandir_2x2(grade, pw, ph)
        contorno = _tracar_moore(exp, pw + 1, ph + 1)
        poly, uv_bbox = _simplificar_e_escalar(contorno, gw, gh, pad=pad)
        holes_poly = _simplificar_buracos(buracos_raw, contorno)

    modo_lower = str(modo).lower()
    if modo_lower == "capa":
        modo_norm = "capa"
    elif modo_lower == "escudo":
        modo_norm = "escudo"
    else:
        modo_norm = "arma"

    poly, rotacao_graus, holes_poly = _orientar_arma_para_empunhadura(
        poly, modo_norm, str(pivot or "empunhadura"), holes=holes_poly
    )
    malha = _construir_malha_solida(
        poly, modo_norm, uv_bbox, nome, rotacao_graus=rotacao_graus, holes=holes_poly
    )
    obj = bpy.data.objects.new(nome, malha)
    bpy.context.collection.objects.link(obj)

    img_tex = _preparar_textura(img_orig, nome, usa_alfa)
    if saida_dir:
        os.makedirs(saida_dir, exist_ok=True)
        out_png = os.path.join(saida_dir, f"{nome}_baseColor.png")
        img_tex.filepath_raw = out_png
        img_tex.file_format = "PNG"
        img_tex.save()
        img_tex.pack()
    mat = bpy.data.materials.new(f"{nome}_mat")
    mat.use_nodes = True
    mat.use_backface_culling = True
    nt = mat.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = img_tex
    tex.extension = "EXTEND"
    tex.location = (-360, 260)
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    if "Roughness" in bsdf.inputs:
        bsdf.inputs["Roughness"].default_value = (
            0.80 if modo_norm == "capa" else (0.35 if modo_norm == "escudo" else 0.45)
        )
    if "Metallic" in bsdf.inputs:
        bsdf.inputs["Metallic"].default_value = 0.25 if modo_norm == "escudo" else 0.0
    obj.data.materials.append(mat)

    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    return obj
