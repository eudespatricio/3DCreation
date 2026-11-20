"""Analise de UVs (colapso por triangulo, sobreposicao e densidade texel) para QC G3/G9."""

from __future__ import annotations

import math

from .qc_glb import _accessor
from .qc_glb_mat import _eh_int, _ler_indices_int

_UV_GRID = 64


def _area_tri_2d(
    a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]
) -> float:
    return 0.5 * abs((b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1]))


def _area_tri_3d(
    a: tuple[float, float, float],
    b: tuple[float, float, float],
    c: tuple[float, float, float],
) -> float:
    ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
    cx = uy * vz - uz * vy
    cy = uz * vx - ux * vz
    cz = ux * vy - uy * vx
    return 0.5 * math.sqrt(cx * cx + cy * cy + cz * cz)


def _orientar_ccw(
    tri: tuple[tuple[float, float], tuple[float, float], tuple[float, float]],
) -> tuple[tuple[float, float], tuple[float, float], tuple[float, float]]:
    a, b, c = tri
    cross = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    return (a, c, b) if cross < 0.0 else tri


def _dentro_semi_plano(
    pt: tuple[float, float], p: tuple[float, float], ex: float, ey: float
) -> bool:
    return ex * (pt[1] - p[1]) - ey * (pt[0] - p[0]) >= -1e-11


def _inter_semi_plano(
    s: tuple[float, float],
    e: tuple[float, float],
    p: tuple[float, float],
    ex: float,
    ey: float,
) -> tuple[float, float]:
    dx, dy = e[0] - s[0], e[1] - s[1]
    denom = ex * dy - ey * dx
    if abs(denom) <= 1e-15:
        return s
    t = (ex * (p[1] - s[1]) - ey * (p[0] - s[0])) / denom
    return (s[0] + t * dx, s[1] + t * dy)


def _clip_sutherland_hodgman(
    sujeito: tuple[tuple[float, float], tuple[float, float], tuple[float, float]],
    recorte: tuple[tuple[float, float], tuple[float, float], tuple[float, float]],
) -> float:
    """Area de intersecao de dois triangulos 2D via Sutherland-Hodgman."""
    poly: list[tuple[float, float]] = list(_orientar_ccw(sujeito))
    c_tri = _orientar_ccw(recorte)
    for k in range(3):
        if not poly:
            return 0.0
        p = c_tri[k]
        q = c_tri[(k + 1) % 3]
        ex, ey = q[0] - p[0], q[1] - p[1]
        saida: list[tuple[float, float]] = []
        s_pt = poly[-1]
        for e_pt in poly:
            if _dentro_semi_plano(e_pt, p, ex, ey):
                if not _dentro_semi_plano(s_pt, p, ex, ey):
                    saida.append(_inter_semi_plano(s_pt, e_pt, p, ex, ey))
                saida.append(e_pt)
            elif _dentro_semi_plano(s_pt, p, ex, ey):
                saida.append(_inter_semi_plano(s_pt, e_pt, p, ex, ey))
            s_pt = e_pt
        poly = saida

    if len(poly) < 3:
        return 0.0
    area2 = 0.0
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        area2 += x1 * y2 - x2 * y1
    return 0.5 * abs(area2)


def _grupo_tem_sobreposicao(
    tris_uv: list[
        tuple[
            tuple[float, float],
            tuple[float, float],
            tuple[float, float],
            float,
            float,
            float,
            float,
            float,
        ]
    ],
) -> bool:
    n = len(tris_uv)
    if n < 2:
        return False

    def _inter_area(i: int, j: int) -> float:
        a0, a1, a2, area_a, u0a, v0a, u1a, v1a = tris_uv[i]
        b0, b1, b2, area_b, u0b, v0b, u1b, v1b = tris_uv[j]
        if max(u0a, u0b) + 1e-6 >= min(u1a, u1b) or max(v0a, v0b) + 1e-6 >= min(v1a, v1b):
            return 0.0
        inter = _clip_sutherland_hodgman((a0, a1, a2), (b0, b1, b2))
        return inter if (inter > 1e-8 and inter > 1e-4 * min(area_a, area_b)) else 0.0

    if n <= 32:
        for i in range(n):
            for j in range(i + 1, n):
                if _inter_area(i, j) > 0.0:
                    return True
        return False

    limiar_ov = 0.0 if n <= 64 else max(1e-4, 0.001 * sum(t[3] for t in tris_uv))
    area_ov = 0.0
    grade: dict[tuple[int, int], list[int]] = {}
    vistos: set[tuple[int, int]] = set()
    for idx, item in enumerate(tris_uv):
        _, _, _, _, u0, v0, u1, v1 = item
        gx0 = max(0, min(_UV_GRID - 1, int(math.floor(u0 * _UV_GRID))))
        gx1 = max(0, min(_UV_GRID - 1, int(math.floor(u1 * _UV_GRID))))
        gy0 = max(0, min(_UV_GRID - 1, int(math.floor(v0 * _UV_GRID))))
        gy1 = max(0, min(_UV_GRID - 1, int(math.floor(v1 * _UV_GRID))))
        for gx in range(gx0, gx1 + 1):
            for gy in range(gy0, gy1 + 1):
                cel = grade.setdefault((gx, gy), [])
                for outro in cel:
                    par = (outro, idx)
                    if par in vistos:
                        continue
                    vistos.add(par)
                    inter = _inter_area(outro, idx)
                    if inter > 0.0:
                        area_ov += inter
                        if area_ov > limiar_ov:
                            return True
                cel.append(idx)
    return False


def _uv_status(
    gltf: dict,
    binario: bytes,
    *,
    permitir_tiling: bool = False,
    eh_blocky: bool = False,
    forcar_area: bool = False,
) -> dict:
    """Inspeciona intervalo, colapso por triangulo, sobreposicao UV0 e densidade texel."""
    fora = 0
    total = 0
    uv_colapsada = 0
    area_uv_total = 0.0
    tris_uv0_avaliados = 0
    uv_min = -16.0 - 1e-4 if permitir_tiling else -1e-4
    uv_max = 16.0 + 1e-4 if permitir_tiling else 1.0 + 1e-4
    raw_acc = gltf.get("accessors", [])
    acessores = raw_acc if isinstance(raw_acc, list) else []
    raw_mats = gltf.get("materials", [])
    materiais = raw_mats if isinstance(raw_mats, list) else []
    raw_meshes = gltf.get("meshes", [])
    meshes = raw_meshes if isinstance(raw_meshes, list) else []

    tris_uv0_por_mat: dict[str, list[tuple]] = {}
    ratios_por_mat: dict[str, list[float]] = {}
    prim_counter = 0

    for malha_gltf in meshes:
        if not isinstance(malha_gltf, dict):
            continue
        prims = malha_gltf.get("primitives", [])
        if not isinstance(prims, list):
            continue
        for prim in prims:
            if not isinstance(prim, dict):
                continue
            prim_counter += 1
            raw_atrib = prim.get("attributes")
            atributos_prim = raw_atrib if isinstance(raw_atrib, dict) else {}
            mat_idx = prim.get("material")
            mat_obj: dict | None = None
            mat_key = f"p:{prim_counter}"
            if _eh_int(mat_idx) and 0 <= mat_idx < len(materiais) and isinstance(materiais[mat_idx], dict):
                mat_obj = materiais[mat_idx]
                mat_key = f"m:{mat_idx}"
            elif len(materiais) == 1 and isinstance(materiais[0], dict):
                mat_obj = materiais[0]
                mat_key = "m:0"
            pbr_raw = mat_obj.get("pbrMetallicRoughness") if isinstance(mat_obj, dict) else None
            base_tex = pbr_raw.get("baseColorTexture") if isinstance(pbr_raw, dict) else None
            mr_tex = pbr_raw.get("metallicRoughnessTexture") if isinstance(pbr_raw, dict) else None
            norm_tex = mat_obj.get("normalTexture") if isinstance(mat_obj, dict) else None
            tem_tex_mat = isinstance(base_tex, dict) or isinstance(norm_tex, dict) or isinstance(mr_tex, dict)

            pos_verts: list[tuple[float, float, float]] | None = None
            pos_idx = atributos_prim.get("POSITION")
            if (
                _eh_int(pos_idx)
                and 0 <= pos_idx < len(acessores)
                and isinstance(acessores[pos_idx], dict)
                and _eh_int(acessores[pos_idx].get("bufferView"))
                and acessores[pos_idx].get("type") == "VEC3"
            ):
                pos_verts = [
                    (float(p[0]), float(p[1]), float(p[2]))
                    for p in _accessor(gltf, binario, pos_idx)
                    if len(p) >= 3
                ]

            for canal_uv in ("TEXCOORD_0", "TEXCOORD_1"):
                if canal_uv not in atributos_prim:
                    continue
                ti = atributos_prim[canal_uv]
                acc = acessores[ti] if _eh_int(ti) and 0 <= ti < len(acessores) else None
                if not isinstance(acc, dict) or not _eh_int(acc.get("bufferView")) or acc.get("type") != "VEC2":
                    fora += 1
                    continue
                comp_raw = acc.get("componentType", 5126)
                comp = comp_raw if _eh_int(comp_raw) else 5126
                norm = bool(acc.get("normalized", False))
                escala_uv = 1.0
                if norm and comp == 5121:
                    escala_uv = 1.0 / 255.0
                elif norm and comp == 5123:
                    escala_uv = 1.0 / 65535.0
                c_min = uv_min if canal_uv == "TEXCOORD_0" else -1e-4
                c_max = uv_max if canal_uv == "TEXCOORD_0" else 1.0 + 1e-4
                coords_uv: list[tuple[float, float]] = []
                for uv_par in _accessor(gltf, binario, ti):
                    if len(uv_par) < 2:
                        continue
                    u = float(uv_par[0]) * escala_uv
                    v = float(uv_par[1]) * escala_uv
                    coords_uv.append((u, v))
                    total += 1
                    if (
                        not math.isfinite(u)
                        or not math.isfinite(v)
                        or u < c_min
                        or u > c_max
                        or v < c_min
                        or v > c_max
                    ):
                        fora += 1

                modo = prim.get("mode", 4)
                checar_area = _eh_int(modo) and modo == 4 and bool(coords_uv) and (
                    tem_tex_mat or canal_uv == "TEXCOORD_1" or (forcar_area and canal_uv == "TEXCOORD_0")
                )
                if not checar_area:
                    continue
                idx_acc = prim.get("indices")
                if _eh_int(idx_acc) and 0 <= idx_acc < len(acessores) and isinstance(acessores[idx_acc], dict):
                    ids = _ler_indices_int(_accessor(gltf, binario, idx_acc))
                else:
                    ids = list(range(len(coords_uv)))
                if len(ids) < 3:
                    continue
                area_uv_prim = 0.0
                tri_colapsado = False
                mat_nome = str(mat_obj.get("name") or "") if isinstance(mat_obj, dict) else ""
                eh_atlas_paleta = mat_nome == "forge3d_atlas"
                eh_armadura_tinta = mat_nome.startswith("armor_")
                checar_uv0_extra = (
                    canal_uv == "TEXCOORD_0"
                    and tem_tex_mat
                    and not eh_blocky
                    and not permitir_tiling
                    and not eh_atlas_paleta
                )
                for k in range(0, len(ids) - 2, 3):
                    i0, i1, i2 = ids[k], ids[k + 1], ids[k + 2]
                    if not (0 <= i0 < len(coords_uv) and 0 <= i1 < len(coords_uv) and 0 <= i2 < len(coords_uv)):
                        continue
                    a_uv, b_uv, c_uv = coords_uv[i0], coords_uv[i1], coords_uv[i2]
                    area_uv_tri = _area_tri_2d(a_uv, b_uv, c_uv)
                    area_uv_prim += area_uv_tri
                    area_3d_tri: float | None = None
                    if pos_verts is not None and max(i0, i1, i2) < len(pos_verts):
                        area_3d_tri = _area_tri_3d(pos_verts[i0], pos_verts[i1], pos_verts[i2])
                    if area_uv_tri <= 1e-10 and (area_3d_tri is None or area_3d_tri > 1e-10):
                        tri_colapsado = True
                    if checar_uv0_extra and area_uv_tri > 1e-10:
                        area_uv_total += area_uv_tri
                        if not eh_armadura_tinta:
                            tris_uv0_avaliados += 1
                        tris_uv0_por_mat.setdefault(mat_key, []).append(
                            (
                                a_uv,
                                b_uv,
                                c_uv,
                                area_uv_tri,
                                min(a_uv[0], b_uv[0], c_uv[0]),
                                min(a_uv[1], b_uv[1], c_uv[1]),
                                max(a_uv[0], b_uv[0], c_uv[0]),
                                max(a_uv[1], b_uv[1], c_uv[1]),
                            )
                        )
                        if area_3d_tri is not None and area_3d_tri > 1e-6:
                            ratios_por_mat.setdefault(mat_key, []).append(area_uv_tri / area_3d_tri)
                if area_uv_prim < 1e-8 or tri_colapsado:
                    uv_colapsada += 1

    uv_sobreposta = sum(1 for grupo in tris_uv0_por_mat.values() if _grupo_tem_sobreposicao(grupo))
    densidade_extrema = 0
    for ratios in ratios_por_mat.values():
        if len(ratios) >= 2:
            r_min, r_max = min(ratios), max(ratios)
            if r_min > 0.0 and (r_max / r_min) > 1000.0:
                densidade_extrema += 1
    uv_baixa_cobertura = 1 if (tris_uv0_avaliados >= 200 and area_uv_total < 0.20) else 0
    return {
        "total_uv": total,
        "fora_intervalo": fora,
        "uv_colapsada": uv_colapsada,
        "uv_sobreposta": uv_sobreposta,
        "densidade_extrema": densidade_extrema,
        "uv_area_total": round(area_uv_total, 4),
        "uv_baixa_cobertura": uv_baixa_cobertura,
    }
