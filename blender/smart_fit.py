"""Motor geometrico Smart-Fit (BVH 1.5 mm, conformacao anatomica, corte de oclusao e auto-grip).

Contem helpers matematicos puros (testaveis sem ``bpy``) e operacoes Blender 4.2.x
baseadas em ``bmesh``, ``mathutils.bvhtree.BVHTree`` e modificadores ``SHRINKWRAP`` /
``SURFACE_DEFORM``.
"""

from __future__ import annotations

import math
from typing import Any, Sequence

try:
    import bmesh
    import bpy
    from mathutils import Euler, Matrix, Vector
    from mathutils.bvhtree import BVHTree

    HAS_BPY = True
except (ImportError, ModuleNotFoundError):
    bmesh = None  # type: ignore[assignment]
    bpy = None  # type: ignore[assignment]
    Euler = None  # type: ignore[assignment]
    Matrix = None  # type: ignore[assignment]
    Vector = None  # type: ignore[assignment]
    BVHTree = None  # type: ignore[assignment]
    HAS_BPY = False

__all__ = [
    "HAS_BPY",
    "FOLGA_CONTATO_PADRAO_M",
    "calcular_pca_cilindro",
    "calcular_angulos_punho_cilindrico",
    "calcular_deslocamento_contato",
    "encaixar_contato_bvh",
    "conformar_anatomico",
    "recortar_oclusao_interna",
    "auto_grip_cilindrico",
    "conformar_punho_ao_cabo",
    "aplicar_smart_fit_job",
]

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
            t_final = min(shifts) if not pen_pares else min(shifts)
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
        p_deep, _a_deep, n_deep, _dist_deep, sd_min = min(pen_pares, key=lambda x: x[4])
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


def _exigir_bpy() -> None:
    if not HAS_BPY or BVHTree is None:
        raise RuntimeError("funcao requer Blender (bpy/bmesh/mathutils.bvhtree)")


def _bvh_mundo(alvo_obj) -> tuple[Any, Any]:
    bm = bmesh.new()
    bm.from_mesh(alvo_obj.data)
    bmesh.ops.transform(bm, matrix=alvo_obj.matrix_world, verts=bm.verts)
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    bm.normal_update()
    bvh = BVHTree.FromBMesh(bm)
    return bvh, bm


def _amostrar_vertices_mundo(obj, max_verts: int = 4000) -> list[Any]:
    mw = obj.matrix_world
    verts = obj.data.vertices
    n = len(verts)
    if n == 0:
        return []
    passo = max(1, n // max_verts)
    return [mw @ verts[i].co for i in range(0, n, passo)]


def _mover_objeto_mundo(obj, delta_mundo: Sequence[float]) -> None:
    dv = Vector((float(delta_mundo[0]), float(delta_mundo[1]), float(delta_mundo[2])))
    if obj.parent is not None:
        inv_p = obj.parent.matrix_world.to_3x3().inverted_safe()
        obj.location = obj.location + (inv_p @ dv)
    else:
        obj.location = obj.location + dv
    bpy.context.view_layer.update()


def encaixar_contato_bvh(
    peca_obj,
    alvo_obj,
    direcao: Sequence[float] | None = None,
    folga_m: float = FOLGA_CONTATO_PADRAO_M,
) -> dict[str, Any]:
    """Encaixa ``peca_obj`` contra a superficie de ``alvo_obj`` a exata ``folga_m`` via BVHTree."""
    _exigir_bpy()
    bpy.context.view_layer.update()
    if peca_obj is None or alvo_obj is None or not peca_obj.data.vertices or not alvo_obj.data.vertices:
        return {
            "deslocamento_m": [0.0, 0.0, 0.0],
            "distancia_min_antes_m": 0.0,
            "distancia_min_depois_m": 0.0,
            "folga_m": float(folga_m),
            "penetracao_resolvida": False,
        }

    bvh, bm_alvo = _bvh_mundo(alvo_obj)
    try:
        desl_acum = Vector((0.0, 0.0, 0.0))
        dist_antes_inicial: float | None = None
        penetracao_inicial = False
        dir_vec = Vector((float(direcao[0]), float(direcao[1]), float(direcao[2]))).normalized() if direcao is not None else None

        for _ in range(4):
            pts = _amostrar_vertices_mundo(peca_obj)
            if not pts:
                break

            if dir_vec is not None:
                hits_t: list[float] = []
                dists_n: list[float] = []
                for p in pts:
                    loc, norm, _idx, dist = bvh.ray_cast(p, dir_vec)
                    if loc is not None and norm is not None:
                        hits_t.append(float(dist) - float(folga_m))
                        dists_n.append(float((p - loc).dot(norm)))
                        continue
                    # Se ja atravessou a superficie, procura na direcao oposta
                    loc_b, norm_b, _idx_b, dist_b = bvh.ray_cast(p, -dir_vec)
                    if loc_b is not None and norm_b is not None and norm_b.dot(dir_vec) < 0.0:
                        hits_t.append(-float(dist_b) - float(folga_m))
                        dists_n.append(float((p - loc_b).dot(norm_b)))

                if hits_t:
                    # Escolhe o deslocamento que aproxima sem penetrar (menor avanco / maior recuo)
                    t_step = min(hits_t)
                    if dist_antes_inicial is None:
                        dist_antes_inicial = min(dists_n) if dists_n else min(hits_t) + float(folga_m)
                        penetracao_inicial = any(d < 0.0 for d in dists_n)
                    if abs(t_step) < 1e-5:
                        break
                    delta = dir_vec * t_step
                    _mover_objeto_mundo(peca_obj, delta)
                    desl_acum += delta
                    continue

            amostras_n: list[tuple[tuple[float, float, float], tuple[float, float, float]]] = []
            pts_filtrados: list[tuple[float, float, float]] = []
            for p in pts:
                loc, norm, _idx, _dist = bvh.find_nearest(p)
                if loc is not None and norm is not None:
                    pts_filtrados.append((p.x, p.y, p.z))
                    amostras_n.append(((loc.x, loc.y, loc.z), (norm.x, norm.y, norm.z)))
            if not pts_filtrados:
                break
            calc = calcular_deslocamento_contato(
                pts_filtrados,
                amostras_n,
                direcao=(dir_vec.x, dir_vec.y, dir_vec.z) if dir_vec is not None else None,
                folga_m=folga_m,
            )
            if dist_antes_inicial is None:
                dist_antes_inicial = float(calc["distancia_antes_m"])
                penetracao_inicial = bool(calc["penetrando"])
            delta = Vector(calc["deslocamento"])
            if delta.length < 1e-5:
                break
            _mover_objeto_mundo(peca_obj, delta)
            desl_acum += delta

        # Medicao final de folga minima sobre toda a superficie
        pts_fim = _amostrar_vertices_mundo(peca_obj)
        dists_fim: list[float] = []
        sds_fim: list[float] = []
        for p in pts_fim:
            loc, norm, _idx, dist = bvh.find_nearest(p)
            if loc is not None and norm is not None:
                dists_fim.append(float(dist))
                sds_fim.append(float((p - loc).dot(norm)))
        dist_depois = min(sds_fim) if (sds_fim and min(sds_fim) < 0.0) else (min(dists_fim) if dists_fim else 0.0)
    finally:
        bm_alvo.free()

    return {
        "deslocamento_m": [round(desl_acum.x, 6), round(desl_acum.y, 6), round(desl_acum.z, 6)],
        "distancia_min_antes_m": round(float(dist_antes_inicial or 0.0), 6),
        "distancia_min_depois_m": round(float(dist_depois), 6),
        "folga_m": float(folga_m),
        "penetracao_resolvida": bool(penetracao_inicial and dist_depois >= -1e-4),
    }


def _nao_manifold_bmesh(obj) -> int:
    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        return sum(1 for e in bm.edges if len(e.link_faces) != 2)
    finally:
        bm.free()


def _limpar_topologia_smart_fit(obj) -> int:
    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        bmesh.ops.dissolve_degenerate(bm, dist=1e-6, edges=list(bm.edges))
        slivers = [f for f in bm.faces if f.calc_area() < 1e-10]
        if slivers:
            bmesh.ops.delete(bm, geom=slivers, context="FACES")
        soltas_e = [e for e in bm.edges if not e.link_faces]
        if soltas_e:
            bmesh.ops.delete(bm, geom=soltas_e, context="EDGES")
        soltos_v = [v for v in bm.verts if not v.link_faces]
        if soltos_v:
            bmesh.ops.delete(bm, geom=soltos_v, context="VERTS")
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        nao_manifold = sum(1 for e in bm.edges if len(e.link_faces) != 2)
        bm.to_mesh(obj.data)
        obj.data.update()
        return nao_manifold
    finally:
        bm.free()


def conformar_anatomico(
    peca_obj,
    corpo_obj,
    folga_m: float = FOLGA_CONTATO_PADRAO_M,
    usar_surface_deform: bool = True,
) -> dict[str, Any]:
    """Conforma ``peca_obj`` anatomicamente sobre ``corpo_obj`` com folga ``folga_m``."""
    _exigir_bpy()
    if peca_obj is None or corpo_obj is None or not peca_obj.data.vertices or not corpo_obj.data.vertices:
        return {"aplicado": False, "folga_m": float(folga_m), "nao_manifold": 0}

    bpy.context.view_layer.update()
    bvh, bm_corpo = _bvh_mundo(corpo_obj)
    try:
        pts_pre = _amostrar_vertices_mundo(peca_obj, max_verts=2000)
        min_pre = min(
            (bvh.find_nearest(p)[3] for p in pts_pre if bvh.find_nearest(p)[0] is not None),
            default=0.0,
        )
    finally:
        bm_corpo.free()

    if min_pre > float(folga_m) + 0.005:
        encaixar_contato_bvh(peca_obj, corpo_obj, folga_m=folga_m)

    bm_check = bmesh.new()
    try:
        bm_check.from_mesh(peca_obj.data)
        eh_aberta = any(e.is_boundary for e in bm_check.edges)
    finally:
        bm_check.free()

    metodo = "shrinkwrap_outside"
    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = peca_obj
    peca_obj.select_set(True)

    # Aplica transform de objeto se nao houver animacao/rig para o deformador operar em espaco limpo
    if peca_obj.parent is None:
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

    if eh_aberta:
        mod_sw = peca_obj.modifiers.new("SmartFitShrinkwrap", "SHRINKWRAP")
        mod_sw.target = corpo_obj
        mod_sw.wrap_method = "TARGET_PROJECT"
        mod_sw.wrap_mode = "OUTSIDE_SURFACE"
        mod_sw.offset = float(folga_m)
        mod_sw.use_negative_direction = True
        mod_sw.use_positive_direction = True
        bpy.ops.object.modifier_apply(modifier=mod_sw.name)

        if usar_surface_deform:
            cage = corpo_obj.copy()
            cage.data = corpo_obj.data.copy()
            bpy.context.collection.objects.link(cage)
            try:
                bpy.context.view_layer.objects.active = peca_obj
                mod_sd = peca_obj.modifiers.new("SmartFitSurfaceDeform", "SURFACE_DEFORM")
                mod_sd.target = cage
                bpy.ops.object.surfacedeform_bind(modifier=mod_sd.name)
                if mod_sd.is_bound:
                    bpy.ops.object.modifier_apply(modifier=mod_sd.name)
                    metodo = "shrinkwrap_plus_surface_deform"
                else:
                    peca_obj.modifiers.remove(mod_sd)
            except Exception:
                if "SmartFitSurfaceDeform" in peca_obj.modifiers:
                    peca_obj.modifiers.remove(peca_obj.modifiers["SmartFitSurfaceDeform"])
            finally:
                mesh_cage = cage.data
                bpy.data.objects.remove(cage, do_unlink=True)
                if mesh_cage.users == 0:
                    bpy.data.meshes.remove(mesh_cage)
    else:
        # Malha fechada com espessura: evita colapso de parede externa sobre parede interna
        vg_nome = "_smart_fit_inner"
        vg_inner = peca_obj.vertex_groups.get(vg_nome) or peca_obj.vertex_groups.new(name=vg_nome)
        bvh_c, bm_c = _bvh_mundo(corpo_obj)
        try:
            mw_p = peca_obj.matrix_world
            rot_p = mw_p.to_3x3()
            dists_v: list[tuple[int, float, Vector, Vector]] = []
            for v in peca_obj.data.vertices:
                pw = mw_p @ v.co
                nw = (rot_p @ v.normal).normalized()
                loc, norm, _idx, dist = bvh_c.find_nearest(pw)
                if loc is not None and norm is not None:
                    dists_v.append((v.index, float((pw - loc).dot(norm)), nw, norm))
            if dists_v:
                sd_min = min(x[1] for x in dists_v)
                sd_max = max(x[1] for x in dists_v)
                corte_inner = sd_min + 0.45 * max(sd_max - sd_min, 0.004)
                for vi, sd, nw, norm in dists_v:
                    if sd <= corte_inner or nw.dot(norm) < -0.15:
                        vg_inner.add([vi], 1.0, "REPLACE")
        finally:
            bm_c.free()

        usou_sd = False
        if usar_surface_deform:
            cage = corpo_obj.copy()
            cage.data = corpo_obj.data.copy()
            bpy.context.collection.objects.link(cage)
            try:
                bpy.context.view_layer.objects.active = peca_obj
                mod_sd = peca_obj.modifiers.new("SmartFitSurfaceDeform", "SURFACE_DEFORM")
                mod_sd.target = cage
                bpy.ops.object.surfacedeform_bind(modifier=mod_sd.name)
                if mod_sd.is_bound:
                    bpy.ops.object.modifier_apply(modifier=mod_sd.name)
                    usou_sd = True
                else:
                    peca_obj.modifiers.remove(mod_sd)
            except Exception:
                if "SmartFitSurfaceDeform" in peca_obj.modifiers:
                    peca_obj.modifiers.remove(peca_obj.modifiers["SmartFitSurfaceDeform"])
            finally:
                mesh_cage = cage.data
                bpy.data.objects.remove(cage, do_unlink=True)
                if mesh_cage.users == 0:
                    bpy.data.meshes.remove(mesh_cage)

        mod_sw = peca_obj.modifiers.new("SmartFitShrinkwrap", "SHRINKWRAP")
        mod_sw.target = corpo_obj
        mod_sw.wrap_method = "TARGET_PROJECT"
        mod_sw.wrap_mode = "OUTSIDE_SURFACE"
        mod_sw.offset = float(folga_m)
        mod_sw.vertex_group = vg_nome
        mod_sw.use_negative_direction = True
        mod_sw.use_positive_direction = True
        bpy.ops.object.modifier_apply(modifier=mod_sw.name)
        vg_rem = peca_obj.vertex_groups.get(vg_nome)
        if vg_rem is not None:
            peca_obj.vertex_groups.remove(vg_rem)
        metodo = "shrinkwrap_inner_group_surface_deform" if usou_sd else "shrinkwrap_inner_group"

        # Garante que nenhum vertice da peca fechada invada o corpo abaixo de folga_m
        bvh_p, bm_p = _bvh_mundo(corpo_obj)
        try:
            mw_p = peca_obj.matrix_world
            mw_inv = mw_p.inverted_safe()
            alterou = False
            for v in peca_obj.data.vertices:
                pw = mw_p @ v.co
                loc, norm, _idx, _dist = bvh_p.find_nearest(pw)
                if loc is not None and norm is not None:
                    sd = float((pw - loc).dot(norm))
                    if sd < float(folga_m):
                        pw_corr = loc + norm * float(folga_m)
                        v.co = mw_inv @ pw_corr
                        alterou = True
            if alterou:
                peca_obj.data.update()
        finally:
            bm_p.free()

    nao_manifold = _limpar_topologia_smart_fit(peca_obj)
    bvh_f, bm_f = _bvh_mundo(corpo_obj)
    try:
        pts_pos = _amostrar_vertices_mundo(peca_obj, max_verts=2000)
        dist_final = min(
            (bvh_f.find_nearest(p)[3] for p in pts_pos if bvh_f.find_nearest(p)[0] is not None),
            default=0.0,
        )
    finally:
        bm_f.free()

    peca_obj.select_set(False)
    return {
        "aplicado": True,
        "metodo": metodo,
        "folga_m": float(folga_m),
        "usar_surface_deform": bool(usar_surface_deform),
        "nao_manifold": int(nao_manifold),
        "distancia_min_m": round(float(dist_final), 6),
    }


def _extrair_loops_borda(bm) -> list[list[Any]]:
    """Agrupa arestas de borda em loops fechados ordenados."""
    arestas_borda = {e for e in bm.edges if e.is_boundary}
    loops: list[list[Any]] = []
    while arestas_borda:
        e_ini = min(arestas_borda, key=lambda e: e.index)
        arestas_borda.remove(e_ini)
        loop = [e_ini]
        v_atual = e_ini.verts[1]
        v_fim = e_ini.verts[0]
        guard = 0
        while v_atual != v_fim and guard < len(bm.edges) + 4:
            guard += 1
            prox = None
            for e in v_atual.link_edges:
                if e in arestas_borda:
                    prox = e
                    break
            if prox is None:
                break
            arestas_borda.remove(prox)
            loop.append(prox)
            v_atual = prox.other_vert(v_atual)
        loops.append(loop)
    return loops


def _preencher_loop_fan(bm, loop_edges: list[Any]) -> int:
    verts_loop: list[Any] = []
    seen = set()
    for e in loop_edges:
        for v in e.verts:
            if v not in seen:
                seen.add(v)
                verts_loop.append(v)
    if len(verts_loop) < 3:
        return 0
    centro_co = sum((v.co for v in verts_loop), Vector((0.0, 0.0, 0.0))) / float(len(verts_loop))
    v_centro = bm.verts.new(centro_co)
    criadas = 0
    for e in loop_edges:
        v0, v1 = e.verts[0], e.verts[1]
        try:
            bm.faces.new((v0, v1, v_centro))
            criadas += 1
        except ValueError:
            pass
    return criadas


def recortar_oclusao_interna(
    corpo_obj,
    pecas_cobertura,
    dist_max_m: float = 0.035,
    limiar_cobertura: float = 0.85,
) -> dict[str, Any]:
    """Remove poligonos internos do corpo ocluidos sob botas/luvas/armaduras e fecha bordas."""
    _exigir_bpy()
    if corpo_obj is None or not corpo_obj.data.vertices:
        return {"faces_antes": 0, "faces_removidas": 0, "faces_depois": 0, "loops_fechados": 0, "nao_manifold": 0}

    if isinstance(pecas_cobertura, (list, tuple)):
        coberturas = [p for p in pecas_cobertura if p is not None and p is not corpo_obj and getattr(p, "data", None)]
    elif pecas_cobertura is not None and pecas_cobertura is not corpo_obj:
        coberturas = [pecas_cobertura]
    else:
        coberturas = []

    if not coberturas:
        n_f = len(corpo_obj.data.polygons)
        return {
            "faces_antes": n_f,
            "faces_removidas": 0,
            "faces_depois": n_f,
            "loops_fechados": 0,
            "nao_manifold": _nao_manifold_bmesh(corpo_obj),
        }

    bpy.context.view_layer.update()
    bvhs: list[tuple[Any, Any]] = [_bvh_mundo(p) for p in coberturas]
    bm = bmesh.new()
    try:
        bm.from_mesh(corpo_obj.data)
        bmesh.ops.transform(bm, matrix=corpo_obj.matrix_world, verts=bm.verts)
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        bm.normal_update()

        faces_antes = len(bm.faces)
        faces_ocultas = []
        d_max = max(0.002, float(dist_max_m))
        limiar = max(0.0, min(1.0, float(limiar_cobertura)))

        for f in bm.faces:
            n = f.normal
            if n.length < 1e-8:
                continue
            n_dir = n.normalized()
            amostras = [f.calc_center_median()]
            amostras.extend(v.co for v in f.verts)
            amostras.extend((e.verts[0].co + e.verts[1].co) * 0.5 for e in f.edges)

            hits = 0
            for pt in amostras:
                ocluido = False
                for bvh, _bm_c in bvhs:
                    if bvh.ray_cast(pt + n_dir * 1e-4, n_dir, d_max)[0] is not None:
                        ocluido = True
                        break
                    if bvh.ray_cast(pt - n_dir * 0.002, n_dir, d_max + 0.002)[0] is not None:
                        ocluido = True
                        break
                if ocluido:
                    hits += 1
            if (hits / float(len(amostras))) >= limiar:
                faces_ocultas.append(f)

        # Nunca apaga 100% da malha para nao gerar objeto vazio
        if not faces_ocultas or len(faces_ocultas) >= len(bm.faces):
            bmesh.ops.transform(bm, matrix=corpo_obj.matrix_world.inverted_safe(), verts=bm.verts)
            nao_m = sum(1 for e in bm.edges if len(e.link_faces) != 2)
            return {
                "faces_antes": faces_antes,
                "faces_removidas": 0,
                "faces_depois": faces_antes,
                "loops_fechados": 0,
                "nao_manifold": nao_m,
            }

        bmesh.ops.delete(bm, geom=faces_ocultas, context="FACES")
        soltas_e = [e for e in bm.edges if not e.link_faces]
        if soltas_e:
            bmesh.ops.delete(bm, geom=soltas_e, context="EDGES")
        soltos_v = [v for v in bm.verts if not v.link_faces]
        if soltos_v:
            bmesh.ops.delete(bm, geom=soltos_v, context="VERTS")

        # Remove triangulos isolados com 3 arestas de borda e desfaz eventuais bow-ties antes do fill
        for _ in range(3):
            peninsulas = [f for f in bm.faces if sum(1 for e in f.edges if e.is_boundary) >= 2]
            if not peninsulas or len(peninsulas) >= len(bm.faces):
                break
            bmesh.ops.delete(bm, geom=peninsulas, context="FACES")
            soltas_e = [e for e in bm.edges if not e.link_faces]
            if soltas_e:
                bmesh.ops.delete(bm, geom=soltas_e, context="EDGES")
            soltos_v = [v for v in bm.verts if not v.link_faces]
            if soltos_v:
                bmesh.ops.delete(bm, geom=soltos_v, context="VERTS")

        loops_antes = _extrair_loops_borda(bm)
        loops_fechados = 0
        edges_borda = [e for e in bm.edges if e.is_boundary]
        if edges_borda:
            res_fill = bmesh.ops.holes_fill(bm, edges=edges_borda, sides=0)
            faces_novas = list(res_fill.get("faces", []))
            loops_fechados = len(loops_antes)
            restantes = _extrair_loops_borda(bm)
            for loop in restantes:
                try:
                    res_el = bmesh.ops.edgeloop_fill(bm, edges=loop)
                    novas_el = list(res_el.get("faces", []))
                    if novas_el:
                        faces_novas.extend(novas_el)
                        loops_fechados += 1
                    else:
                        if _preencher_loop_fan(bm, loop) > 0:
                            loops_fechados += 1
                except Exception:
                    if _preencher_loop_fan(bm, loop) > 0:
                        loops_fechados += 1
            ngons = [f for f in bm.faces if len(f.verts) > 3]
            if ngons:
                bmesh.ops.triangulate(bm, faces=ngons)

        bmesh.ops.dissolve_degenerate(bm, dist=1e-6, edges=list(bm.edges))
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        nao_manifold = sum(1 for e in bm.edges if len(e.link_faces) != 2)
        faces_depois = len(bm.faces)

        bmesh.ops.transform(bm, matrix=corpo_obj.matrix_world.inverted_safe(), verts=bm.verts)
        bm.to_mesh(corpo_obj.data)
        corpo_obj.data.update()
        return {
            "faces_antes": faces_antes,
            "faces_removidas": len(faces_ocultas),
            "faces_depois": faces_depois,
            "loops_fechados": loops_fechados,
            "nao_manifold": int(nao_manifold),
        }
    finally:
        bm.free()
        for _bvh, bm_c in bvhs:
            bm_c.free()


def auto_grip_cilindrico(
    arma_obj,
    fracao_cabo: tuple[float, float] = (0.05, 0.35),
) -> dict[str, Any]:
    """Detecta eixo PCA, centro e raio radial do cabo de uma arma para empunhadura."""
    _exigir_bpy()
    if arma_obj is None or not getattr(arma_obj, "data", None) or not arma_obj.data.vertices:
        return calcular_pca_cilindro([], fracao_cabo=fracao_cabo)
    mw = arma_obj.matrix_world
    pts = [tuple(mw @ v.co) for v in arma_obj.data.vertices]
    return calcular_pca_cilindro(pts, fracao_cabo=fracao_cabo)


def conformar_punho_ao_cabo(
    rig_obj,
    lado: str = "R",
    grip_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Aplica curvatura das falanges das maos no rig ao redor do raio de empunhadura."""
    _exigir_bpy()
    if rig_obj is None or getattr(rig_obj, "pose", None) is None:
        return {"lado": lado, "ossos_posados": 0, "raio_m": 0.016}

    raio_m = float((grip_info or {}).get("raio_m") or 0.016)
    lados_alvo = ("L", "R") if str(lado).strip().upper() == "BOTH" else (str(lado).strip().upper() or "R",)

    # Estima comprimento total do dedo medio quando existir no rig
    comp_mao = 0.085
    for ld in lados_alvo:
        segs = [rig_obj.data.bones.get(f"Middle{i}.{ld}") for i in (1, 2, 3)]
        if all(s is not None for s in segs):
            comp_mao = sum(float(s.length) for s in segs if s is not None)
            break

    angulos = calcular_angulos_punho_cilindrico(raio_m, comprimento_mao_m=comp_mao)
    pbones = rig_obj.pose.bones
    ossos_posados: list[str] = []

    bpy.context.view_layer.objects.active = rig_obj
    bpy.ops.object.mode_set(mode="POSE")
    try:
        for ld in lados_alvo:
            if ld not in ("L", "R"):
                continue
            sinal = 1.0 if ld == "R" else -1.0
            for dedo, graus_3 in angulos["dedos"].items():
                for idx, deg in enumerate(graus_3, 1):
                    for cand in (f"{dedo}{idx}.{ld}", f"{dedo.lower()}_0{idx}_{ld.lower()}"):
                        pb = pbones.get(cand)
                        if pb is not None:
                            pb.rotation_mode = "QUATERNION"
                            pb.rotation_quaternion = Matrix.Rotation(math.radians(deg), 4, "X").to_quaternion()
                            ossos_posados.append(pb.name)
                            break
            for idx, (rx, rz) in enumerate(angulos["thumb"], 1):
                for cand in (f"Thumb{idx}.{ld}", f"thumb_0{idx}_{ld.lower()}"):
                    pb = pbones.get(cand)
                    if pb is not None:
                        pb.rotation_mode = "QUATERNION"
                        pb.rotation_quaternion = Euler(
                            (math.radians(rx), 0.0, math.radians(rz * sinal)), "XYZ"
                        ).to_quaternion()
                        ossos_posados.append(pb.name)
                        break
    finally:
        bpy.ops.object.mode_set(mode="OBJECT")
        bpy.context.view_layer.update()

    return {
        "lado": str(lado),
        "raio_m": angulos["raio_m"],
        "media_graus": angulos["media_graus"],
        "soma_graus": angulos["soma_graus"],
        "ossos_posados": len(ossos_posados),
        "ossos": ossos_posados,
    }


def _resolver_objeto_cena(ref: Any):
    if ref is None:
        return None
    if not isinstance(ref, str):
        return ref
    return bpy.data.objects.get(ref)


def aplicar_smart_fit_job(
    obj,
    job: dict[str, Any],
    corpo_obj=None,
    rig_obj=None,
) -> dict[str, Any]:
    """Despachante JSON-driven para operacoes Smart-Fit no pipeline Blender."""
    _exigir_bpy()
    if not isinstance(job, dict):
        return {"aplicado": False, "motivo": "job_invalido"}

    cfg = job.get("smart_fit")
    if not isinstance(cfg, dict):
        item_cfg = job.get("item") if isinstance(job.get("item"), dict) else {}
        cfg = item_cfg.get("smart_fit") if isinstance(item_cfg.get("smart_fit"), dict) else None
    if cfg is None:
        cfg = job if any(
            k in job
            for k in (
                "encaixar_contato",
                "contato_bvh",
                "conformar_anatomico",
                "conformar",
                "recortar_oclusao",
                "recortar_oclusao_interna",
                "auto_grip",
                "auto_grip_cilindrico",
                "folga_m",
            )
        ) else {}

    if not cfg:
        return {"aplicado": False, "operacoes": []}

    folga_padrao = float(cfg.get("folga_m") or FOLGA_CONTATO_PADRAO_M)
    corpo_ref = corpo_obj or _resolver_objeto_cena(cfg.get("corpo") or cfg.get("alvo"))
    rig_ref = rig_obj or _resolver_objeto_cena(cfg.get("rig")) or (
        obj.parent if obj is not None and getattr(obj.parent, "type", None) == "ARMATURE" else None
    )

    resultados: dict[str, Any] = {"aplicado": False, "operacoes": []}

    contato_cfg = cfg.get("encaixar_contato") or cfg.get("contato_bvh")
    if contato_cfg and obj is not None:
        c_dict = contato_cfg if isinstance(contato_cfg, dict) else {}
        alvo = _resolver_objeto_cena(c_dict.get("alvo")) or corpo_ref
        if alvo is not None:
            res_c = encaixar_contato_bvh(
                obj,
                alvo,
                direcao=c_dict.get("direcao"),
                folga_m=float(c_dict.get("folga_m") or folga_padrao),
            )
            resultados["encaixar_contato"] = res_c
            resultados["operacoes"].append("encaixar_contato")
            resultados["aplicado"] = True

    conf_cfg = cfg.get("conformar_anatomico") or cfg.get("conformar")
    if conf_cfg and obj is not None and corpo_ref is not None:
        cf_dict = conf_cfg if isinstance(conf_cfg, dict) else {}
        res_cf = conformar_anatomico(
            obj,
            corpo_ref,
            folga_m=float(cf_dict.get("folga_m") or folga_padrao),
            usar_surface_deform=bool(cf_dict.get("usar_surface_deform", True)),
        )
        resultados["conformar_anatomico"] = res_cf
        resultados["operacoes"].append("conformar_anatomico")
        resultados["aplicado"] = True

    ocl_cfg = cfg.get("recortar_oclusao") or cfg.get("recortar_oclusao_interna")
    if ocl_cfg:
        oc_dict = ocl_cfg if isinstance(ocl_cfg, dict) else {}
        alvo_corpo = _resolver_objeto_cena(oc_dict.get("corpo")) or corpo_ref or obj
        raw_cob = oc_dict.get("pecas_cobertura") or oc_dict.get("coberturas") or []
        coberturas = [_resolver_objeto_cena(x) for x in (raw_cob if isinstance(raw_cob, (list, tuple)) else [raw_cob])]
        coberturas = [c for c in coberturas if c is not None]
        if not coberturas and corpo_ref is not None and obj is not None and obj is not corpo_ref:
            coberturas = [obj]
        if alvo_corpo is not None and coberturas:
            res_oc = recortar_oclusao_interna(
                alvo_corpo,
                coberturas,
                dist_max_m=float(oc_dict.get("dist_max_m", 0.035)),
                limiar_cobertura=float(oc_dict.get("limiar_cobertura", 0.85)),
            )
            resultados["recortar_oclusao"] = res_oc
            resultados["operacoes"].append("recortar_oclusao")
            resultados["aplicado"] = True

    grip_cfg = cfg.get("auto_grip") or cfg.get("auto_grip_cilindrico")
    if grip_cfg and obj is not None:
        g_dict = grip_cfg if isinstance(grip_cfg, dict) else {}
        frac = tuple(g_dict.get("fracao_cabo") or (0.05, 0.35))
        res_g = auto_grip_cilindrico(obj, fracao_cabo=(float(frac[0]), float(frac[1])))
        resultados["auto_grip"] = res_g
        resultados["operacoes"].append("auto_grip")
        resultados["aplicado"] = True
        if rig_ref is not None and bool(g_dict.get("aplicar_no_rig", True)):
            res_p = conformar_punho_ao_cabo(
                rig_ref,
                lado=str(g_dict.get("lado") or "R"),
                grip_info=res_g,
            )
            resultados["conformar_punho"] = res_p
            resultados["operacoes"].append("conformar_punho")

    return resultados
