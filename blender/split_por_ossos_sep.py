"""Separacao geometrica de pares sobrepostos no split por ossos (G12)."""

from __future__ import annotations

import bmesh
from mathutils import Vector


def bmesh_aabb(bm) -> tuple[Vector, Vector]:
    """Calcula a AABB minima e maxima dos vertices de um BMesh."""
    if not bm.verts:
        zero = Vector((0.0, 0.0, 0.0))
        return zero, zero.copy()
    cos = [v.co for v in bm.verts]
    return (
        Vector((min(c.x for c in cos), min(c.y for c in cos), min(c.z for c in cos))),
        Vector((max(c.x for c in cos), max(c.y for c in cos), max(c.z for c in cos))),
    )


def _eixo_separacao(
    mid_a: Vector,
    mid_b: Vector,
    amin: Vector,
    amax: Vector,
    bmin: Vector,
    bmax: Vector,
    ov: list[float],
) -> Vector:
    u = mid_b - mid_a
    if u.length >= 1e-6:
        return u.normalized()
    d_min = min(range(3), key=lambda d: ov[d])
    ca = 0.5 * (amin[d_min] + amax[d_min])
    cb = 0.5 * (bmin[d_min] + bmax[d_min])
    eixo = Vector((0.0, 0.0, 0.0))
    eixo[d_min] = 1.0 if cb >= ca else -1.0
    return eixo


def _tentar_bisectar_par(
    bms: list,
    aabbs: list[tuple[Vector, Vector]],
    idx_a: int,
    nome_a: str,
    mid_a: Vector,
    idx_b: int,
    nome_b: str,
    mid_b: Vector,
    p_cut: Vector,
    u: Vector,
    gap: float,
    limpar_orfaos_fn,
    fechar_fn,
) -> bool:
    bm_a = bms[idx_a].copy()
    bm_b = bms[idx_b].copy()
    ok = False
    try:
        for bm_t, co_p, out_f, in_f in (
            (bm_a, p_cut - u * gap, True, False),
            (bm_b, p_cut + u * gap, False, True),
        ):
            bmesh.ops.bisect_plane(
                bm_t,
                geom=list(bm_t.verts) + list(bm_t.edges) + list(bm_t.faces),
                plane_co=co_p,
                plane_no=u,
                clear_outer=out_f,
                clear_inner=in_f,
                dist=1e-5,
            )
            limpar_orfaos_fn(bm_t)
        if len(bm_a.faces) < 4 or len(bm_b.faces) < 4:
            return False
        if not fechar_fn(bm_a, nome_a, mid_a, 0.0, levantar_erro=False):
            return False
        if not fechar_fn(bm_b, nome_b, mid_b, 0.0, levantar_erro=False):
            return False
        bms[idx_a].free()
        bms[idx_a] = bm_a
        aabbs[idx_a] = bmesh_aabb(bm_a)
        bms[idx_b].free()
        bms[idx_b] = bm_b
        aabbs[idx_b] = bmesh_aabb(bm_b)
        ok = True
        return True
    finally:
        if not ok:
            bm_a.free()
            bm_b.free()


def bisectar_sobrepostos(
    bms: list,
    arm,
    segmentos: list[tuple[str, Vector, Vector]],
    retract_dist: float,
    limpar_orfaos_fn,
    fechar_fn,
    altura_w: float | None = None,
) -> None:
    """Separa todos os pares de partes com caixas sobrepostas (pai-filho e nao adjacentes)."""
    tol_ov = max(retract_dist * 2.5, 0.0015)
    gap_pc = max(retract_dist * 0.6, 0.0004)
    aabbs = [bmesh_aabb(bm) for bm in bms]

    for i in range(len(segmentos)):
        nome_i, seg_a_i, seg_b_i = segmentos[i]
        osso_i = arm.data.bones.get(nome_i)
        for j in range(i + 1, len(segmentos)):
            nome_j, seg_a_j, seg_b_j = segmentos[j]
            amin, amax = aabbs[i]
            bmin, bmax = aabbs[j]
            ov = [min(amax[d], bmax[d]) - max(amin[d], bmin[d]) for d in range(3)]
            if min(ov) <= tol_ov:
                continue

            osso_j = arm.data.bones.get(nome_j)
            eh_pai_ij = osso_j is not None and osso_j.parent is not None and osso_j.parent.name == nome_i
            eh_pai_ji = osso_i is not None and osso_i.parent is not None and osso_i.parent.name == nome_j

            c_ov = Vector(
                (0.5 * (max(amin[d], bmin[d]) + min(amax[d], bmax[d])) for d in range(3))
            )
            if eh_pai_ij or eh_pai_ji:
                if eh_pai_ij:
                    p_idx, p_nome, seg_a_p, seg_b_p, pmin, pmax = i, nome_i, seg_a_i, seg_b_i, amin, amax
                    c_idx, c_nome, seg_a_c, seg_b_c, cmin, cmax = j, nome_j, seg_a_j, seg_b_j, bmin, bmax
                else:
                    p_idx, p_nome, seg_a_p, seg_b_p, pmin, pmax = j, nome_j, seg_a_j, seg_b_j, bmin, bmax
                    c_idx, c_nome, seg_a_c, seg_b_c, cmin, cmax = i, nome_i, seg_a_i, seg_b_i, amin, amax
                mid_p, mid_c = 0.5 * (seg_a_p + seg_b_p), 0.5 * (seg_a_c + seg_b_c)
                u = mid_c - mid_p
                if u.length < 1e-6:
                    continue
                u.normalize()
                p_cut = (
                    seg_a_c
                    if all(max(pmin[d], cmin[d]) <= seg_a_c[d] <= min(pmax[d], cmax[d]) for d in range(3))
                    else c_ov
                )
                _tentar_bisectar_par(
                    bms, aabbs, p_idx, p_nome, mid_p, c_idx, c_nome, mid_c,
                    p_cut, u, gap_pc, limpar_orfaos_fn, fechar_fn,
                )
            else:
                mid_i, mid_j = 0.5 * (seg_a_i + seg_b_i), 0.5 * (seg_a_j + seg_b_j)
                u = _eixo_separacao(mid_i, mid_j, amin, amax, bmin, bmax, ov)
                h_ref = (
                    float(altura_w)
                    if altura_w is not None
                    else (max(amax.z, bmax.z) - min(amin.z, bmin.z))
                )
                gap_na = max(retract_dist * 1.5, 0.0015 * max(1.0, h_ref / 1.8))
                _tentar_bisectar_par(
                    bms, aabbs, i, nome_i, mid_i, j, nome_j, mid_j,
                    c_ov, u, gap_na, limpar_orfaos_fn, fechar_fn,
                )
