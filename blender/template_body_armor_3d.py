"""Camadas 3D medievais conformes via raycast BVH (tunica, cinto, fivela, braceletes e botas)."""

from __future__ import annotations

import math

import bmesh
import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree


def _adicionar_tubo_contornado_manifold(
    bm,
    uv_layer,
    aneis_internos: list[list[Vector]],
    aneis_externos: list[list[Vector]],
    mat_index: int,
) -> None:
    """Cria casca tubular fechada 2-manifold (parede interna + externa + tampas superior/inferior)."""
    n_rings = len(aneis_internos)
    if n_rings < 2:
        return
    n_seg = len(aneis_internos[0])
    v_in = [[bm.verts.new(p) for p in ring] for ring in aneis_internos]
    v_out = [[bm.verts.new(p) for p in ring] for ring in aneis_externos]

    def _set_face_uv(face, uvs):
        face.material_index = mat_index
        for lp, uv_co in zip(face.loops, uvs):
            lp[uv_layer].uv = uv_co

    # Escala UV isotropica por comprimento de arco (~0.48 UV/m, compativel com suit_obj)
    uv_por_metro = 0.48
    ring0 = aneis_externos[0]
    perim_m = sum((ring0[(s + 1) % n_seg] - ring0[s]).length for s in range(n_seg))
    u_span = max(0.18, min(0.96, perim_m * uv_por_metro))
    v_cum = [0.0]
    for r in range(n_rings - 1):
        dz_m = sum((aneis_externos[r + 1][s] - aneis_externos[r][s]).length for s in range(n_seg)) / float(max(1, n_seg))
        v_cum.append(v_cum[-1] + dz_m * uv_por_metro)
    v_total = max(1e-4, v_cum[-1])
    if v_total > 0.40:
        v_cum = [v * (0.40 / v_total) for v in v_cum]

    for r in range(n_rings - 1):
        v0_o, v1_o = 0.52 + v_cum[r], 0.52 + v_cum[r + 1]
        v0_i, v1_i = 0.06 + v_cum[r], 0.06 + v_cum[r + 1]
        for s in range(n_seg):
            sn = (s + 1) % n_seg
            u0 = 0.02 + (s / float(n_seg)) * u_span
            u1 = 0.02 + ((s + 1) / float(n_seg)) * u_span
            f_out = bm.faces.new((v_out[r][s], v_out[r][sn], v_out[r + 1][sn], v_out[r + 1][s]))
            _set_face_uv(f_out, ((u0, v0_o), (u1, v0_o), (u1, v1_o), (u0, v1_o)))
            f_in = bm.faces.new((v_in[r][sn], v_in[r][s], v_in[r + 1][s], v_in[r + 1][sn]))
            _set_face_uv(f_in, ((u1, v0_i), (u0, v0_i), (u0, v1_i), (u1, v1_i)))

    for s in range(n_seg):
        sn = (s + 1) % n_seg
        u0 = 0.02 + (s / float(n_seg)) * u_span
        u1 = 0.02 + ((s + 1) / float(n_seg)) * u_span
        f_bot = bm.faces.new((v_in[0][s], v_in[0][sn], v_out[0][sn], v_out[0][s]))
        _set_face_uv(f_bot, ((u0, 0.01), (u1, 0.01), (u1, 0.04), (u0, 0.04)))
        top = n_rings - 1
        f_top = bm.faces.new((v_out[top][s], v_out[top][sn], v_in[top][sn], v_in[top][s]))
        _set_face_uv(f_top, ((u0, 0.94), (u1, 0.94), (u1, 0.98), (u0, 0.98)))


def _bvh_filtrado(objs: list, face_pred) -> BVHTree | None:
    """Constroi BVHTree apenas com triangulos que satisfazem `face_pred(face)`, liberando BMesh temporarios."""
    bm_dst = bmesh.new()
    try:
        for obj in objs:
            if obj is None or getattr(obj, "data", None) is None:
                continue
            bm_src = bmesh.new()
            try:
                bm_src.from_mesh(obj.data)
                bmesh.ops.triangulate(bm_src, faces=list(bm_src.faces))
                vmap: dict[int, bmesh.types.BMVert] = {}
                seen_f: set[tuple[int, ...]] = set()
                for f in bm_src.faces:
                    if not face_pred(f):
                        continue
                    chave = tuple(sorted(v.index for v in f.verts))
                    if len(chave) < 3 or chave in seen_f:
                        continue
                    seen_f.add(chave)
                    verts_dst = []
                    for v in f.verts:
                        vd = vmap.get(v.index)
                        if vd is None:
                            vd = bm_dst.verts.new(v.co)
                            vmap[v.index] = vd
                        verts_dst.append(vd)
                    bm_dst.faces.new(verts_dst)
            finally:
                bm_src.free()
        if len(bm_dst.faces) == 0:
            return None
        return BVHTree.FromBMesh(bm_dst)
    finally:
        bm_dst.free()


def _raio_inward_bvh(
    bvh: BVHTree | None,
    centro: Vector,
    dir_xy: Vector,
    r_probe: float,
    r_fallback: float,
    r_min: float,
    r_max: float,
) -> float:
    """Mede raio local da superficie por raycast de fora para dentro no BVHTree."""
    if bvh is None:
        return r_fallback
    d = dir_xy.normalized()
    loc, _nrm, _idx, _dist = bvh.ray_cast(centro + d * r_probe, -d, r_probe)
    if loc is not None:
        r_hit = (loc - centro).dot(d)
        if r_hit > 1e-4:
            return max(r_min, min(r_max, r_hit))
    loc_out, _nrm_o, _idx_o, _dist_o = bvh.ray_cast(centro, d, r_probe)
    if loc_out is not None:
        r_hit = (loc_out - centro).dot(d)
        if r_hit > 1e-4:
            return max(r_min, min(r_max, r_hit))
    loc_n, _nrm_n, _idx_n, _dist_n = bvh.find_nearest(centro + d * r_probe)
    if loc_n is not None:
        r_hit = (loc_n - centro).dot(d)
        if r_hit > 1e-4:
            return max(r_min, min(r_max, r_hit))
    return r_fallback


def _refinar_par_bvh(
    bvh: BVHTree | None,
    p_in: Vector,
    p_out: Vector,
    dir_xy: Vector,
    off_in: float,
    thick: float,
    max_gap: float,
) -> tuple[Vector, Vector]:
    """Garante que o vertice interno esteja dentro de `max_gap` da superficie real do BVH."""
    if bvh is None:
        return p_in, p_out
    loc_n, nrm_n, _idx_n, d_n = bvh.find_nearest(p_in)
    if loc_n is not None and d_n > max_gap:
        out_d = (
            nrm_n.normalized()
            if (nrm_n is not None and nrm_n.length > 1e-4 and nrm_n.dot(dir_xy) > 0.2)
            else dir_xy
        )
        p_in = loc_n + out_d * off_in
        p_out = p_in + out_d * thick
    return p_in, p_out


def _centro_secao_horizontal(
    objs: list,
    zc: float,
    pred_vert,
    fallback_cx: float,
    fallback_cy: float,
    tol_z: float,
) -> tuple[float, float]:
    """Calcula centro (cx, cy) da secao horizontal z=zc por intersecao de arestas (suporta cilindros esparsos)."""
    pts_sec: list[Vector] = []
    for obj in objs:
        if obj is None or getattr(obj, "data", None) is None:
            continue
        verts = obj.data.vertices
        for ed in obj.data.edges:
            p0 = verts[ed.vertices[0]].co
            p1 = verts[ed.vertices[1]].co
            dz0 = p0.z - zc
            dz1 = p1.z - zc
            if dz0 * dz1 <= 0.0:
                denom = p1.z - p0.z
                t = 0.5 if abs(denom) < 1e-7 else max(0.0, min(1.0, (zc - p0.z) / denom))
                pm = p0.lerp(p1, t)
                if pred_vert(pm):
                    pts_sec.append(pm)
        if len(pts_sec) < 4:
            for v in verts:
                if abs(v.co.z - zc) <= tol_z and pred_vert(v.co):
                    pts_sec.append(v.co)
    if len(pts_sec) >= 3:
        cx = 0.5 * (min(p.x for p in pts_sec) + max(p.x for p in pts_sec))
        cy = 0.5 * (min(p.y for p in pts_sec) + max(p.y for p in pts_sec))
        return cx, cy
    return fallback_cx, fallback_cy


def _y_frente_anel(ring_out: list[Vector], x_q: float, cy_b: float) -> float:
    """Amostra a coordenada Y frontal (-Y) do anel externo do cinto exatamente em x = x_q."""
    n_seg = len(ring_out)
    melhor_y: float | None = None
    for s in range(n_seg):
        p0 = ring_out[s]
        p1 = ring_out[(s + 1) % n_seg]
        if 0.5 * (p0.y + p1.y) > cy_b + 0.01:
            continue
        x_lo, x_hi = (p0.x, p1.x) if p0.x <= p1.x else (p1.x, p0.x)
        if x_lo - 1e-5 <= x_q <= x_hi + 1e-5:
            dx = p1.x - p0.x
            t = 0.5 if abs(dx) < 1e-7 else max(0.0, min(1.0, (x_q - p0.x) / dx))
            yq = p0.y + t * (p1.y - p0.y)
            if melhor_y is None or yq < melhor_y:
                melhor_y = yq
    if melhor_y is not None:
        return melhor_y
    return min(p.y for p in ring_out)


def _dist_ponto_segmento(p: Vector, a: Vector, b: Vector) -> float:
    ab = b - a
    ab_sq = ab.length_squared
    if ab_sq < 1e-12:
        return (p - a).length
    t = max(0.0, min(1.0, (p - a).dot(ab) / ab_sq))
    return (p - (a + ab * t)).length


def _centro_secao_braco(
    body_obj,
    centro_a: Vector,
    u_dir: Vector,
    v_dir: Vector,
    w_dir: Vector,
    pts: list[Vector],
    r_win: float = 0.11,
) -> Vector:
    """Refina centro da secao transversal do antebraco via intersecao aresta-plano."""
    verts = body_obj.data.vertices
    pts_sec: list[Vector] = []
    for ed in body_obj.data.edges:
        p0 = verts[ed.vertices[0]].co
        p1 = verts[ed.vertices[1]].co
        d0 = (p0 - centro_a).dot(u_dir)
        d1 = (p1 - centro_a).dot(u_dir)
        if d0 * d1 <= 0.0:
            denom = d1 - d0
            t = 0.5 if abs(denom) < 1e-7 else max(0.0, min(1.0, -d0 / denom))
            pm = p0.lerp(p1, t)
            if math.hypot((pm - centro_a).dot(v_dir), (pm - centro_a).dot(w_dir)) <= r_win:
                pts_sec.append(pm)
    if len(pts_sec) >= 4:
        dvs = [(p - centro_a).dot(v_dir) for p in pts_sec]
        dws = [(p - centro_a).dot(w_dir) for p in pts_sec]
        return centro_a + v_dir * (0.5 * (min(dvs) + max(dvs))) + w_dir * (0.5 * (min(dws) + max(dws)))
    perto = [
        p
        for p in pts
        if abs((p - centro_a).dot(u_dir)) <= 0.022
        and math.hypot((p - centro_a).dot(v_dir), (p - centro_a).dot(w_dir)) <= r_win
    ]
    if len(perto) >= 4:
        return sum(perto, Vector((0.0, 0.0, 0.0))) / float(len(perto))
    return centro_a


def _z_belt_lo_seguro(bvh_torso: BVHTree | None, objs_torso: list, z_min: float, h: float, suit_obj) -> float:
    """Seleciona z_belt_lo estritamente acima da virilha e da barra da tunica."""
    z_tunic_min = z_min + 0.490 * h
    if suit_obj is not None and getattr(suit_obj, "data", None) is not None:
        t_zs = [
            suit_obj.data.vertices[vi].co.z
            for p in suit_obj.data.polygons
            if p.material_index == 0
            for vi in p.vertices
        ]
        if t_zs:
            z_tunic_min = min(t_zs)
    for zf in (0.496, 0.500, 0.505, 0.510, 0.515, 0.520):
        zc = z_min + zf * h
        if suit_obj is not None and zc < z_tunic_min + 0.004 * h:
            continue
        cx, cy = _centro_secao_horizontal(objs_torso, zc, lambda p: abs(p.x) <= 0.160 * h, 0.0, 0.0, 0.025 * h)
        if bvh_torso is None:
            return zc
        hf = bvh_torso.ray_cast(Vector((cx, cy - 0.22 * h, zc)), Vector((0.0, 1.0, 0.0)), 0.22 * h)[0]
        hb = bvh_torso.ray_cast(Vector((cx, cy + 0.22 * h, zc)), Vector((0.0, -1.0, 0.0)), 0.22 * h)[0]
        if hf is not None and hb is not None and abs(hf.z - zc) <= 0.010 * h and abs(hb.z - zc) <= 0.010 * h:
            return zc
    return z_min + 0.505 * h


def _construir_sobreposicoes_medievais_3d(
    body_obj,
    mat_idx_tunic: int,
    mat_idx_leather: int,
    mat_idx_metal: int,
    rig=None,
    suit_obj=None,
):
    """Cria camadas 3D contornadas via BVH (tunica fallback, cinto, fivela, braceletes e botas)."""
    pts = [v.co.copy() for v in body_obj.data.vertices]
    z_min, z_max = min(p.z for p in pts), max(p.z for p in pts)
    h = max(0.5, z_max - z_min)

    bm = bmesh.new()
    try:
        uv_layer = bm.loops.layers.uv.new("UVMap")
        objs_torso = [body_obj, suit_obj] if suit_obj is not None else [body_obj]
        bvh_torso = _bvh_filtrado(
            objs_torso,
            lambda f: (
                all(abs(v.co.x) <= 0.160 * h for v in f.verts)
                and max(v.co.z for v in f.verts) >= z_min + 0.42 * h
                and min(v.co.z for v in f.verts) <= z_min + 0.74 * h
            ),
        )

        n_seg_t = 16
        if suit_obj is None:
            tun_in, tun_out = [], []
            for zf in (0.50, 0.54, 0.58, 0.63, 0.67):
                zc = z_min + zf * h
                cx, cy = _centro_secao_horizontal(objs_torso, zc, lambda p: abs(p.x) <= 0.160 * h, 0.0, 0.0, 0.025 * h)
                ring_i, ring_o = [], []
                for s in range(n_seg_t):
                    ang = (2.0 * math.pi * s) / float(n_seg_t)
                    dir_xy = Vector((math.cos(ang), math.sin(ang), 0.0))
                    r_surf = _raio_inward_bvh(bvh_torso, Vector((cx, cy, zc)), dir_xy, 0.22 * h, 0.095 * h, 0.035 * h, 0.165 * h)
                    cz = Vector((cx, cy, zc))
                    ring_i.append(cz + dir_xy * (r_surf + 0.0015))
                    ring_o.append(cz + dir_xy * (r_surf + 0.0050))
                tun_in.append(ring_i)
                tun_out.append(ring_o)
            _adicionar_tubo_contornado_manifold(bm, uv_layer, tun_in, tun_out, mat_idx_tunic)

        # 2. Cinto de couro ajustado rente ao torso acima da virilha/barra
        z_belt_lo = _z_belt_lo_seguro(bvh_torso, objs_torso, z_min, h, suit_obj)
        z_belt_hi = min(z_min + 0.550 * h, z_belt_lo + 0.048 * h)
        z_bm = 0.5 * (z_belt_lo + z_belt_hi)
        cx_b, cy_b = _centro_secao_horizontal(objs_torso, z_bm, lambda p: abs(p.x) <= 0.160 * h, 0.0, 0.0, 0.028 * h)
        belt_in, belt_out = [], []
        for zc in (z_belt_lo, z_bm, z_belt_hi):
            cx_z, cy_z = _centro_secao_horizontal(objs_torso, zc, lambda p: abs(p.x) <= 0.160 * h, cx_b, cy_b, 0.028 * h)
            ri, ro = [], []
            for s in range(n_seg_t):
                ang = (2.0 * math.pi * s) / float(n_seg_t)
                dir_xy = Vector((math.cos(ang), math.sin(ang), 0.0))
                r_surf = _raio_inward_bvh(bvh_torso, Vector((cx_z, cy_z, zc)), dir_xy, 0.22 * h, 0.095 * h, 0.035 * h, 0.175 * h)
                cz = Vector((cx_z, cy_z, zc))
                p_in, p_out = _refinar_par_bvh(
                    bvh_torso, cz + dir_xy * (r_surf + 0.0004), cz + dir_xy * (r_surf + 0.0074), dir_xy, 0.0004, 0.0070, 0.0012
                )
                ri.append(p_in)
                ro.append(p_out)
            belt_in.append(ri)
            belt_out.append(ro)
        _adicionar_tubo_contornado_manifold(bm, uv_layer, belt_in, belt_out, mat_idx_leather)

        # 3. Fivela frontal assentada no torso (belt_in) e saliente em belt_out
        belt_in_mid, belt_out_mid = belt_in[1], belt_out[1]
        f_in = [
            [Vector((xq, _y_frente_anel(belt_in_mid, xq, cy_b) + 0.0002, z_bm + dz)) for xq, dz in ((-0.018, -0.016), (0.018, -0.016), (0.018, 0.016), (-0.018, 0.016))],
            [Vector((xq, _y_frente_anel(belt_out_mid, xq, cy_b) - 0.002, z_bm + dz)) for xq, dz in ((-0.018, -0.016), (0.018, -0.016), (0.018, 0.016), (-0.018, 0.016))],
        ]
        f_out = [
            [Vector((xq, _y_frente_anel(belt_in_mid, xq, cy_b) + 0.0002, z_bm + dz)) for xq, dz in ((-0.032, -0.027), (0.032, -0.027), (0.032, 0.027), (-0.032, 0.027))],
            [Vector((xq, _y_frente_anel(belt_out_mid, xq, cy_b) - 0.005, z_bm + dz)) for xq, dz in ((-0.032, -0.027), (0.032, -0.027), (0.032, 0.027), (-0.032, 0.027))],
        ]
        _adicionar_tubo_contornado_manifold(bm, uv_layer, f_in, f_out, mat_idx_metal)

        # 4. Braceletes de couro rentes ao antebraco (<= 1.5 mm) sem teto artificial em bracos grossos
        n_seg_b = 10
        r_win_arm = max(0.11, 0.065 * h)
        d_arm_bvh = max(0.12, 0.070 * h)
        for lado_b, sinal_x in (("r", -1.0), ("l", 1.0)):
            p_elb = p_wri = None
            if rig is not None:
                for cand_b in (f"lowerarm_{lado_b}", f"LowerArm.{lado_b.upper()}"):
                    if cand_b in rig.pose.bones:
                        pb_la = rig.pose.bones[cand_b]
                        p_elb, p_wri = rig.matrix_world @ pb_la.head, rig.matrix_world @ pb_la.tail
                        break
            if p_elb is None or p_wri is None:
                faixa_fb = [p for p in pts if 0.16 * h <= p.x * sinal_x <= 0.27 * h and z_min + 0.60 * h <= p.z <= z_min + 0.74 * h]
                if len(faixa_fb) >= 10:
                    faixa_fb.sort(key=lambda p: p.x * sinal_x)
                    x_lo, x_hi = faixa_fb[0].x * sinal_x, faixa_fb[-1].x * sinal_x
                    dx_fb = max(1e-4, x_hi - x_lo)
                    band1 = [p for p in faixa_fb if 0.10 <= (p.x * sinal_x - x_lo) / dx_fb <= 0.30]
                    band2 = [p for p in faixa_fb if 0.72 <= (p.x * sinal_x - x_lo) / dx_fb <= 0.92]
                    p_elb = sum(band1, Vector((0.0, 0.0, 0.0))) / float(len(band1)) if band1 else faixa_fb[int(0.20 * len(faixa_fb))]
                    p_wri = sum(band2, Vector((0.0, 0.0, 0.0))) / float(len(band2)) if band2 else faixa_fb[int(0.82 * len(faixa_fb))]
            if p_elb is not None and p_wri is not None and (p_wri - p_elb).length > 0.04:
                u_dir = (p_wri - p_elb).normalized()
                v_dir = u_dir.cross(Vector((0.0, 1.0, 0.0)))
                if v_dir.length < 1e-4:
                    v_dir = u_dir.cross(Vector((0.0, 0.0, 1.0)))
                v_dir.normalize()
                w_dir = u_dir.cross(v_dir).normalized()
                bvh_arm = _bvh_filtrado(
                    [body_obj],
                    lambda f, pa=p_elb, pb=p_wri: _dist_ponto_segmento(sum((v.co for v in f.verts), Vector((0.0, 0.0, 0.0))) / float(len(f.verts)), pa, pb) <= d_arm_bvh,
                )
                br_in, br_out = [], []
                for t_frac, r_base in ((0.30, 0.040), (0.54, 0.036), (0.76, 0.033)):
                    centro_a = _centro_secao_braco(body_obj, p_elb.lerp(p_wri, t_frac), u_dir, v_dir, w_dir, pts, r_win=r_win_arm)
                    ri_ring, ro_ring = [], []
                    for s in range(n_seg_b):
                        ang = (2.0 * math.pi * s) / float(n_seg_b)
                        radial = v_dir * math.cos(ang) + w_dir * math.sin(ang)
                        r_surf = _raio_inward_bvh(bvh_arm, centro_a, radial, max(0.13, 0.075 * h), r_base, 0.014, r_win_arm)
                        p_in, p_out = _refinar_par_bvh(
                            bvh_arm, centro_a + radial * (r_surf + 0.0004), centro_a + radial * (r_surf + 0.0049), radial, 0.0004, 0.0045, 0.0010
                        )
                        ri_ring.append(p_in)
                        ro_ring.append(p_out)
                    br_in.append(ri_ring)
                    br_out.append(ro_ring)
                _adicionar_tubo_contornado_manifold(bm, uv_layer, br_in, br_out, mat_idx_leather)

        # 5. Canos de botas de couro rentes as canelas (<= 2.0 mm, excluindo outliers dos dedos)
        n_seg_leg = 16
        r_probe_leg, r_max_leg = max(0.15, 0.085 * h), max(0.13, 0.075 * h)
        for sinal_x in (-1.0, 1.0):
            bvh_leg = _bvh_filtrado(
                [body_obj],
                lambda f, sx=sinal_x: all(v.co.x * sx >= 0.005 * h for v in f.verts) and min(v.co.z for v in f.verts) <= z_min + 0.34 * h,
            )
            _, cy_shin = _centro_secao_horizontal([body_obj], z_min + 0.155 * h, lambda p, sx=sinal_x: p.x * sx >= 0.005 * h, 0.0, 0.0, 0.020 * h)
            boot_in, boot_out = [], []
            for zf in (0.055, 0.100, 0.155, 0.205, 0.250):
                zc = z_min + zf * h
                cxl, cyl = _centro_secao_horizontal(
                    [body_obj], zc, lambda p, sx=sinal_x, cys=cy_shin: p.x * sx >= 0.005 * h and p.y >= cys - 0.065 * h, sinal_x * 0.068 * h, cy_shin, 0.020 * h
                )
                ri_l, ro_l = [], []
                for s in range(n_seg_leg):
                    ang = (2.0 * math.pi * s) / float(n_seg_leg)
                    dir_xy = Vector((math.cos(ang), math.sin(ang), 0.0))
                    r_surf = _raio_inward_bvh(bvh_leg, Vector((cxl, cyl, zc)), dir_xy, r_probe_leg, 0.045, 0.012, r_max_leg)
                    cz = Vector((cxl, cyl, zc))
                    p_in, p_out = _refinar_par_bvh(
                        bvh_leg, cz + dir_xy * (r_surf + 0.0005), cz + dir_xy * (r_surf + 0.0073), dir_xy, 0.0005, 0.0068, 0.0010
                    )
                    ri_l.append(p_in)
                    ro_l.append(p_out)
                boot_in.append(ri_l)
                boot_out.append(ro_l)
            _adicionar_tubo_contornado_manifold(bm, uv_layer, boot_in, boot_out, mat_idx_leather)

        bmesh.ops.triangulate(bm, faces=list(bm.faces))
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        me_ov = bpy.data.meshes.new("camadas_medievais_3d")
        for _ in range(3):
            me_ov.materials.append(None)
        bm.to_mesh(me_ov)
    finally:
        bm.free()
    ov_obj = bpy.data.objects.new("camadas_medievais_3d", me_ov)
    bpy.context.collection.objects.link(ov_obj)
    return ov_obj
