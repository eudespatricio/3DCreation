"""Matematica pura do motor geometrico Smart-Fit (camada L0, sem bpy)."""

from __future__ import annotations

import math
from typing import Any, Sequence

FOLGA_CONTATO_PADRAO_M = 0.0015


def _as_vec3(p: Sequence[float] | Any) -> tuple[float, float, float]:
    return (float(p[0]), float(p[1]), float(p[2]))


def _sub(a: tuple[float, float, float], b: tuple[float, float, float]) -> tuple[float, float, float]:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a: tuple[float, float, float], b: tuple[float, float, float]) -> tuple[float, float, float]:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _scale(a: tuple[float, float, float], s: float) -> tuple[float, float, float]:
    return (a[0] * s, a[1] * s, a[2] * s)


def _dot(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _norm(a: tuple[float, float, float]) -> float:
    return math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2])


def _normalize(
    a: tuple[float, float, float], fallback: tuple[float, float, float] = (0.0, 0.0, 1.0)
) -> tuple[float, float, float]:
    n = _norm(a)
    if n <= 1e-12:
        return fallback
    return (a[0] / n, a[1] / n, a[2] / n)


def _canonicalizar_eixo(eixo: tuple[float, float, float]) -> tuple[float, float, float]:
    ax, ay, az = abs(eixo[0]), abs(eixo[1]), abs(eixo[2])
    if az >= ax and az >= ay:
        return eixo if eixo[2] >= 0.0 else (-eixo[0], -eixo[1], -eixo[2])
    if ay >= ax:
        return eixo if eixo[1] >= 0.0 else (-eixo[0], -eixo[1], -eixo[2])
    return eixo if eixo[0] >= 0.0 else (-eixo[0], -eixo[1], -eixo[2])


def _pca_3x3(pontos: list[tuple[float, float, float]]) -> tuple[list[float], list[tuple[float, float, float]]]:
    """Autovalores e autovetores ordenados (decrescente) da matriz de covariancia 3x3 via Jacobi."""
    n = len(pontos)
    if n == 0:
        return [0.0, 0.0, 0.0], [(0.0, 0.0, 1.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
    inv_n = 1.0 / float(n)
    cx = sum(p[0] for p in pontos) * inv_n
    cy = sum(p[1] for p in pontos) * inv_n
    cz = sum(p[2] for p in pontos) * inv_n

    a = [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]
    for px, py, pz in pontos:
        dx, dy, dz = px - cx, py - cy, pz - cz
        a[0][0] += dx * dx
        a[0][1] += dx * dy
        a[0][2] += dx * dz
        a[1][1] += dy * dy
        a[1][2] += dy * dz
        a[2][2] += dz * dz
    a[1][0] = a[0][1]
    a[2][0] = a[0][2]
    a[2][1] = a[1][2]
    for i in range(3):
        for j in range(3):
            a[i][j] *= inv_n

    v = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    for _ in range(24):
        p_idx, q_idx, max_val = 0, 1, abs(a[0][1])
        for i, j in ((0, 2), (1, 2)):
            if abs(a[i][j]) > max_val:
                p_idx, q_idx, max_val = i, j, abs(a[i][j])
        if max_val <= 1e-14:
            break
        app = a[p_idx][p_idx]
        aqq = a[q_idx][q_idx]
        apq = a[p_idx][q_idx]
        tau = (aqq - app) / (2.0 * apq)
        t = (1.0 / (tau + math.sqrt(1.0 + tau * tau))) if tau >= 0.0 else (-1.0 / (-tau + math.sqrt(1.0 + tau * tau)))
        c = 1.0 / math.sqrt(1.0 + t * t)
        s = t * c

        a[p_idx][p_idx] = app - t * apq
        a[q_idx][q_idx] = aqq + t * apq
        a[p_idx][q_idx] = 0.0
        a[q_idx][p_idx] = 0.0
        for r in range(3):
            if r == p_idx or r == q_idx:
                continue
            arp = a[r][p_idx]
            arq = a[r][q_idx]
            a[r][p_idx] = a[p_idx][r] = c * arp - s * arq
            a[r][q_idx] = a[q_idx][r] = s * arp + c * arq
        for r in range(3):
            vrp = v[r][p_idx]
            vrq = v[r][q_idx]
            v[r][p_idx] = c * vrp - s * vrq
            v[r][q_idx] = s * vrp + c * vrq

    pares = [
        (a[i][i], _normalize((v[0][i], v[1][i], v[2][i])))
        for i in range(3)
    ]
    pares.sort(key=lambda item: item[0], reverse=True)
    return [float(val) for val, _ in pares], [vec for _, vec in pares]


def calcular_pca_cilindro(
    pontos: Sequence[Sequence[float]],
    fracao_cabo: tuple[float, float] = (0.05, 0.35),
) -> dict[str, Any]:
    """Calcula eixo PCA, centro, raio e comprimento da regiao de empunhadura (cabo)."""
    pts = [_as_vec3(p) for p in pontos]
    if len(pts) < 3:
        centro = pts[0] if pts else (0.0, 0.0, 0.0)
        return {
            "centro": [round(centro[0], 6), round(centro[1], 6), round(centro[2], 6)],
            "eixo": [0.0, 0.0, 1.0],
            "raio_m": 0.015,
            "comprimento_m": 0.1,
            "socket_offset": [round(centro[0], 6), round(centro[1], 6), round(centro[2], 6)],
            "amostras": len(pts),
        }

    f0 = max(0.0, min(0.95, float(fracao_cabo[0])))
    f1 = max(f0 + 0.02, min(1.0, float(fracao_cabo[1])))

    inv_n = 1.0 / float(len(pts))
    c_all = (
        sum(p[0] for p in pts) * inv_n,
        sum(p[1] for p in pts) * inv_n,
        sum(p[2] for p in pts) * inv_n,
    )
    eigvals_g, eigvecs_g = _pca_3x3(pts)
    eixo_global = _canonicalizar_eixo(eigvecs_g[0]) if eigvals_g[0] > 1e-12 else (0.0, 0.0, 1.0)

    proj = [_dot(_sub(p, c_all), eixo_global) for p in pts]
    s_min = min(proj)
    s_max = max(proj)
    span = max(s_max - s_min, 1e-6)
    s_lo = s_min + f0 * span
    s_hi = s_min + f1 * span

    pts_cabo = [p for p, s in zip(pts, proj) if s_lo <= s <= s_hi]
    if len(pts_cabo) < 4:
        pts_cabo = list(pts)

    inv_c = 1.0 / float(len(pts_cabo))
    centro_cabo = (
        sum(p[0] for p in pts_cabo) * inv_c,
        sum(p[1] for p in pts_cabo) * inv_c,
        sum(p[2] for p in pts_cabo) * inv_c,
    )
    eigvals_c, eigvecs_c = _pca_3x3(pts_cabo)
    if eigvals_c[0] > 1.5 * max(eigvals_c[1], 1e-12):
        eixo = eigvecs_c[0]
        if _dot(eixo, eixo_global) < 0.0:
            eixo = (-eixo[0], -eixo[1], -eixo[2])
    else:
        eixo = eixo_global

    raios: list[float] = []
    s_cabo: list[float] = []
    for p in pts_cabo:
        rel = _sub(p, centro_cabo)
        s = _dot(rel, eixo)
        s_cabo.append(s)
        perp = _sub(rel, _scale(eixo, s))
        r = _norm(perp)
        if r > 1e-6:
            raios.append(r)

    if raios:
        raios.sort()
        raio_m = raios[len(raios) // 2]
    else:
        raio_m = 0.015

    comp_cabo = (max(s_cabo) - min(s_cabo)) if len(s_cabo) >= 2 else ((f1 - f0) * span)
    comp_cabo = max(comp_cabo, 1e-4)

    centro_l = [round(centro_cabo[0], 6), round(centro_cabo[1], 6), round(centro_cabo[2], 6)]
    return {
        "centro": centro_l,
        "eixo": [round(eixo[0], 6), round(eixo[1], 6), round(eixo[2], 6)],
        "raio_m": round(max(1e-5, float(raio_m)), 6),
        "comprimento_m": round(float(comp_cabo), 6),
        "socket_offset": list(centro_l),
        "amostras": len(pts_cabo),
    }


def calcular_angulos_punho_cilindrico(
    raio_m: float,
    comprimento_mao_m: float = 0.085,
) -> dict[str, Any]:
    """Calcula angulos de flexao (graus) das 3 falanges por dedo para envolver um cilindro."""
    r = max(0.006, min(0.080, float(raio_m)))
    comp = max(0.040, min(0.140, float(comprimento_mao_m)))
    # Arco total envolvido ao redor do cabo: menor raio -> maior fechamento
    total_deg = math.degrees(comp / r) * 0.52

    def _clamp(v: float, lo: float, hi: float) -> float:
        return round(max(lo, min(hi, v)), 3)

    b1 = _clamp(total_deg * 0.34, 6.0, 82.0)
    b2 = _clamp(total_deg * 0.38, 8.0, 92.0)
    b3 = _clamp(total_deg * 0.28, 5.0, 78.0)

    dedos = {
        "Index": (_clamp(b1 * 0.95, 5.0, 82.0), _clamp(b2 * 0.95, 7.0, 92.0), _clamp(b3 * 0.95, 5.0, 78.0)),
        "Middle": (b1, b2, b3),
        "Ring": (_clamp(b1 * 1.04, 6.0, 82.0), _clamp(b2 * 1.04, 8.0, 92.0), _clamp(b3 * 1.04, 5.0, 78.0)),
        "Little": (_clamp(b1 * 1.08, 6.0, 82.0), _clamp(b2 * 1.08, 8.0, 92.0), _clamp(b3 * 1.08, 5.0, 78.0)),
    }
    thumb = (
        (_clamp(b1 * 0.46, 5.0, 48.0), _clamp(b1 * 0.50, 4.0, 38.0)),
        (_clamp(b2 * 0.56, 6.0, 56.0), _clamp(b2 * 0.28, 3.0, 24.0)),
        (_clamp(b3 * 0.62, 5.0, 52.0), _clamp(b3 * 0.18, 2.0, 16.0)),
    )
    valores_curl = [ang for segs in dedos.values() for ang in segs] + [rx for rx, _rz in thumb]
    return {
        "raio_m": round(float(raio_m), 6),
        "dedos": dedos,
        "thumb": thumb,
        "media_graus": round(sum(valores_curl) / float(len(valores_curl)), 3),
        "soma_graus": round(sum(valores_curl), 3),
    }


def calcular_deslocamento_contato(
    pontos_peca: Sequence[Sequence[float]],
    amostras_alvo: Sequence[tuple[Sequence[float], Sequence[float]]],
    direcao: Sequence[float] | None = None,
    folga_m: float = FOLGA_CONTATO_PADRAO_M,
) -> dict[str, Any]:
    """Calcula translacao rigida para encostar a peca no alvo a exatos ``folga_m``."""
    if not pontos_peca or not amostras_alvo or len(pontos_peca) != len(amostras_alvo):
        return {
            "deslocamento": [0.0, 0.0, 0.0],
            "distancia_antes_m": 0.0,
            "folga_m": float(folga_m),
            "penetrando": False,
        }

    pares: list[tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float], float, float]] = []
    for p_raw, (a_raw, n_raw) in zip(pontos_peca, amostras_alvo):
        p = _as_vec3(p_raw)
        a = _as_vec3(a_raw)
        n = _normalize(_as_vec3(n_raw))
        diff = _sub(p, a)
        dist = _norm(diff)
        sd = _dot(diff, n)
        pares.append((p, a, n, dist, sd))

    pen_pares = [item for item in pares if item[4] < folga_m]
    if direcao is not None:
        d = _normalize(_as_vec3(direcao))
        shifts: list[float] = []
        for p, a, n, _dist, _sd in pares:
            denom = _dot(d, n)
            if abs(denom) > 1e-6:
                t = (folga_m - _dot(_sub(p, a), n)) / denom
                shifts.append(t)
        if shifts:
            t_final = min(shifts)
            desl = _scale(d, t_final)
        else:
            desl = (0.0, 0.0, 0.0)
        sd_min = min(item[4] for item in pares)
        return {
            "deslocamento": [round(desl[0], 6), round(desl[1], 6), round(desl[2], 6)],
            "distancia_antes_m": round(float(sd_min), 6),
            "folga_m": float(folga_m),
            "penetrando": sd_min < 0.0,
        }

    if pen_pares:
        _p_deep, _a_deep, n_deep, _dist_deep, sd_min = min(pen_pares, key=lambda x: x[4])
        delta = folga_m - sd_min
        desl = _scale(n_deep, delta)
        dist_antes = sd_min
    else:
        p_min, a_min, _n_min, dist_min, _sd = min(pares, key=lambda x: x[3])
        dir_aprox = _normalize(_sub(a_min, p_min))
        passo = max(0.0, dist_min - folga_m)
        desl = _scale(dir_aprox, passo)
        dist_antes = dist_min

    return {
        "deslocamento": [round(desl[0], 6), round(desl[1], 6), round(desl[2], 6)],
        "distancia_antes_m": round(float(dist_antes), 6),
        "folga_m": float(folga_m),
        "penetrando": bool(pen_pares and min(x[4] for x in pen_pares) < 0.0),
    }
