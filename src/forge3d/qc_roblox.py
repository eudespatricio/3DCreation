"""Portoes QC G12 (separacao de partes), G13 (ancoras) e integracao G12-G14."""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import ForgeError
from .qc_geom import topologia
from .qc_glb import _matrizes_mundo_nos, ler_glb_bin, malha
from .qc_roblox_anim import LIMIAR_AMPLITUDE_G14_GRAUS, verificar_g14_animacao_roblox
from .rbx_xml import JOINT_R15

LIMIAR_SEPARACAO_MM = 2.0
LIMIAR_ANCORA_MM = 1.0
_TORSO_PARTES = frozenset({"LowerTorso", "UpperTorso"})

__all__ = [
    "LIMIAR_SEPARACAO_MM",
    "LIMIAR_ANCORA_MM",
    "LIMIAR_AMPLITUDE_G14_GRAUS",
    "verificar_g12_separacao",
    "verificar_g13_ancoras",
    "verificar_g14_animacao_roblox",
    "verificar_gates_roblox",
]


@dataclass
class _ParteMalha:
    nome: str
    arquivo: str
    pos: list[tuple[float, float, float]]
    tris_box: list[
        tuple[
            tuple[float, float, float],
            tuple[float, float, float],
            tuple[float, float, float],
            tuple[float, float, float],
            tuple[float, float, float],
        ]
    ]
    wmin: tuple[float, float, float]
    wmax: tuple[float, float, float]
    fechada: bool


def _aabb_verts(
    pos: list[tuple[float, float, float]],
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    xs = [p[0] for p in pos]
    ys = [p[1] for p in pos]
    zs = [p[2] for p in pos]
    return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))


def _dist_exit_eixo(
    pt: tuple[float, float, float],
    tris_box: list[
        tuple[
            tuple[float, float, float],
            tuple[float, float, float],
            tuple[float, float, float],
            tuple[float, float, float],
            tuple[float, float, float],
        ]
    ],
    ax: int,
) -> tuple[bool, float]:
    """Parity ray test along axis ``ax`` with slight off-axis jitter to avoid edge hits."""
    u_ax = (ax + 1) % 3
    v_ax = (ax + 2) % 3
    pu = pt[u_ax] + 1.37e-7
    pv = pt[v_ax] + 2.91e-7
    px = pt[ax]
    ts: list[float] = []
    for p0, p1, p2, fmin, fmax in tris_box:
        if pu < fmin[u_ax] - 1e-6 or pu > fmax[u_ax] + 1e-6:
            continue
        if pv < fmin[v_ax] - 1e-6 or pv > fmax[v_ax] + 1e-6:
            continue
        u0, v0 = p0[u_ax], p0[v_ax]
        u1, v1 = p1[u_ax], p1[v_ax]
        u2, v2 = p2[u_ax], p2[v_ax]
        det = (v1 - v2) * (u0 - u2) + (u2 - u1) * (v0 - v2)
        if abs(det) < 1e-14:
            continue
        l0 = ((v1 - v2) * (pu - u2) + (u2 - u1) * (pv - v2)) / det
        l1 = ((v2 - v0) * (pu - u2) + (u0 - u2) * (pv - v2)) / det
        l2 = 1.0 - l0 - l1
        if l0 >= -1e-9 and l1 >= -1e-9 and l2 >= -1e-9:
            hit_ax = l0 * p0[ax] + l1 * p1[ax] + l2 * p2[ax]
            ts.append(hit_ax - px)
    pos_t = [t for t in ts if t > 1e-6]
    neg_t = [-t for t in ts if t < -1e-6]
    dentro = (len(pos_t) % 2 == 1) and (len(neg_t) % 2 == 1)
    if not dentro or not pos_t or not neg_t:
        return False, 0.0
    return True, min(min(pos_t), min(neg_t))


def _seg_tri_u(
    p: tuple[float, float, float],
    q: tuple[float, float, float],
    t0: tuple[float, float, float],
    t1: tuple[float, float, float],
    t2: tuple[float, float, float],
) -> tuple[float, float] | None:
    d = (q[0] - p[0], q[1] - p[1], q[2] - p[2])
    e1 = (t1[0] - t0[0], t1[1] - t0[1], t1[2] - t0[2])
    e2 = (t2[0] - t0[0], t2[1] - t0[1], t2[2] - t0[2])
    h = (d[1] * e2[2] - d[2] * e2[1], d[2] * e2[0] - d[0] * e2[2], d[0] * e2[1] - d[1] * e2[0])
    det = e1[0] * h[0] + e1[1] * h[1] + e1[2] * h[2]
    if abs(det) < 1e-12:
        return None
    inv = 1.0 / det
    s = (p[0] - t0[0], p[1] - t0[1], p[2] - t0[2])
    b1 = inv * (s[0] * h[0] + s[1] * h[1] + s[2] * h[2])
    if b1 < -1e-6 or b1 > 1.0 + 1e-6:
        return None
    qv = (s[1] * e1[2] - s[2] * e1[1], s[2] * e1[0] - s[0] * e1[2], s[0] * e1[1] - s[1] * e1[0])
    b2 = inv * (d[0] * qv[0] + d[1] * qv[1] + d[2] * qv[2])
    if b2 < -1e-6 or b1 + b2 > 1.0 + 1e-6:
        return None
    u = inv * (e2[0] * qv[0] + e2[1] * qv[1] + e2[2] * qv[2])
    if 1e-4 < u < 1.0 - 1e-4:
        return u, min(b1, b2, 1.0 - b1 - b2)
    return None


def _penetracao_ponto(pt: tuple[float, float, float], dst: _ParteMalha) -> float:
    dentro_cnt = 0
    min_exit = float("inf")
    for ax in range(3):
        dentro, d_ax = _dist_exit_eixo(pt, dst.tris_box, ax)
        if dentro:
            dentro_cnt += 1
            min_exit = min(min_exit, d_ax)
    return min_exit if dentro_cnt >= 2 and min_exit < float("inf") else 0.0


def _penetracao_malhas(a: _ParteMalha, b: _ParteMalha, tol_export: float) -> float:
    """Mede penetracao entre duas malhas sobrepostas (0.0 se nao ha interpenetracao)."""
    max_pen = 0.0
    for src, dst in ((a, b), (b, a)):
        pts: list[tuple[float, float, float]] = []
        for p in src.pos:
            if all(dst.wmin[d] + tol_export < p[d] < dst.wmax[d] - tol_export for d in range(3)):
                pts.append(p)
        for p0, p1, p2, _fmin, _fmax in src.tris_box:
            c = (
                (p0[0] + p1[0] + p2[0]) / 3.0,
                (p0[1] + p1[1] + p2[1]) / 3.0,
                (p0[2] + p1[2] + p2[2]) / 3.0,
            )
            if all(dst.wmin[d] - tol_export <= c[d] <= dst.wmax[d] + tol_export for d in range(3)):
                pts.append(c)
        if len(pts) > 512:
            pts = pts[:: max(1, len(pts) // 512)]
        for pt in pts:
            max_pen = max(max_pen, _penetracao_ponto(pt, dst))

        arestas_vistas: set[tuple[tuple[float, float, float], tuple[float, float, float]]] = set()
        for p0, p1, p2, fmin, fmax in src.tris_box:
            if any(fmax[d] < dst.wmin[d] or fmin[d] > dst.wmax[d] for d in range(3)):
                continue
            for ea, eb in ((p0, p1), (p1, p2), (p2, p0)):
                key = (ea, eb) if ea <= eb else (eb, ea)
                if key in arestas_vistas:
                    continue
                arestas_vistas.add(key)
                emin = (min(ea[0], eb[0]), min(ea[1], eb[1]), min(ea[2], eb[2]))
                emax = (max(ea[0], eb[0]), max(ea[1], eb[1]), max(ea[2], eb[2]))
                if any(emax[d] < dst.wmin[d] or emin[d] > dst.wmax[d] for d in range(3)):
                    continue
                hits: list[tuple[float, float]] = []
                for t0, t1, t2, tmin, tmax in dst.tris_box:
                    if any(emax[d] < tmin[d] or emin[d] > tmax[d] for d in range(3)):
                        continue
                    hit = _seg_tri_u(ea, eb, t0, t1, t2)
                    if hit is not None:
                        hits.append(hit)
                if len(hits) >= 2:
                    hits.sort(key=lambda x: x[0])
                    for k in range(len(hits) - 1):
                        u0, b_m0 = hits[k]
                        u1, b_m1 = hits[k + 1]
                        if u1 - u0 > 1e-4 and max(b_m0, b_m1) > 1e-4:
                            um = 0.5 * (u0 + u1)
                            mid = (
                                ea[0] + um * (eb[0] - ea[0]),
                                ea[1] + um * (eb[1] - ea[1]),
                                ea[2] + um * (eb[2] - ea[2]),
                            )
                            max_pen = max(max_pen, _penetracao_ponto(mid, dst))
    return max_pen


def _carregar_parte_malha(
    p: dict, pasta: Path, tol_export: float
) -> tuple[_ParteMalha | None, str | None]:
    nome = str(p.get("nome") or "")
    rel = str(p.get("arquivo") or f"{nome}.glb")
    caminho = pasta / rel
    if not caminho.is_file():
        return None, f"parte_ausente:{rel}"
    try:
        gltf_p, bin_p = ler_glb_bin(caminho)
        if not (gltf_p.get("meshes") or []):
            return None, f"parte_sem_malha:{rel}"
        pos_loc, tris_loc = malha(gltf_p, bin_p)
        topo_p = topologia(gltf_p, bin_p)
    except (ForgeError, OSError, ValueError, struct.error, IndexError, KeyError, TypeError, AttributeError) as exc:
        return None, f"parte_ilegivel:{rel}:{exc}"
    if not pos_loc or not tris_loc:
        return None, f"parte_vazia:{rel}"

    lmin, lmax = _aabb_verts(pos_loc)
    diag = math.sqrt(sum((lmax[d] - lmin[d]) ** 2 for d in range(3)))
    if diag <= 1e-9:
        return None, f"parte_degenerada:{rel}"
    lcenter = ((lmin[0] + lmax[0]) * 0.5, (lmin[1] + lmax[1]) * 0.5, (lmin[2] + lmax[2]) * 0.5)
    anc_vec = _vec3_valido(p.get("ancora"))
    pivo_decl = p.get("pivo")
    if anc_vec is None:
        pivot_na_ancora = False
    elif pivo_decl in ("junta", "ancora", "local") or pivo_decl == [0.0, 0.0, 0.0]:
        pivot_na_ancora = True
    elif pivo_decl in ("mundo", "compartilhado", "global"):
        pivot_na_ancora = False
    else:
        d0_sq = sum(lcenter[d] ** 2 for d in range(3))
        da_sq = sum((lcenter[d] - anc_vec[d]) ** 2 for d in range(3))
        pivot_na_ancora = d0_sq <= da_sq + 1e-9
    if pivot_na_ancora and anc_vec is not None:
        ax, ay, az = anc_vec
        pos_w = [(v[0] + ax, v[1] + ay, v[2] + az) for v in pos_loc]
        wmin = (lmin[0] + ax, lmin[1] + ay, lmin[2] + az)
        wmax = (lmax[0] + ax, lmax[1] + ay, lmax[2] + az)
    else:
        pos_w = pos_loc
        wmin, wmax = lmin, lmax

    tris_box = []
    for i0, i1, i2 in tris_loc:
        p0, p1, p2 = pos_w[i0], pos_w[i1], pos_w[i2]
        fmin = (min(p0[0], p1[0], p2[0]), min(p0[1], p1[1], p2[1]), min(p0[2], p1[2], p2[2]))
        fmax = (max(p0[0], p1[0], p2[0]), max(p0[1], p1[1], p2[1]), max(p0[2], p1[2], p2[2]))
        tris_box.append((p0, p1, p2, fmin, fmax))

    return (
        _ParteMalha(
            nome=nome,
            arquivo=rel,
            pos=pos_w,
            tris_box=tris_box,
            wmin=wmin,
            wmax=wmax,
            fechada=int(topo_p.get("bordas_abertas", 0)) == 0,
        ),
        None,
    )


def verificar_g12_separacao(
    item: dict, pasta: Path, resultado: dict, escala: float
) -> dict:
    """Gate G12: partes articuladas distintas, sem fusao no torso e penetracao <= 2 mm."""
    partes = resultado.get("partes") or item.get("partes") or []
    modo_rig = str(
        (item.get("rig") or {}).get("modo") or (resultado.get("rig") or {}).get("modo") or ""
    )
    if not partes and modo_rig != "motor6d":
        return {"id": "G12", "status": "ok", "medido": {"aplicavel": False}}

    if not partes:
        return {
            "id": "G12",
            "status": "falhou",
            "medido": {"aplicavel": True, "partes": 0, "disjuntas": False, "problemas": ["partes_ausentes"]},
            "limite": {"penetracao_max_mm": LIMIAR_SEPARACAO_MM},
            "codigo": "FORGE-E-QC",
        }

    tol_export = (LIMIAR_SEPARACAO_MM / 1000.0) * escala
    problemas: list[str] = []
    vistas_arq: set[str] = set()
    malhas: list[_ParteMalha] = []
    for p in partes:
        nome = str(p.get("nome") or "")
        rel = str(p.get("arquivo") or f"{nome}.glb")
        if rel in vistas_arq:
            problemas.append(f"arquivo_duplicado:{rel}")
            continue
        vistas_arq.add(rel)
        pm, err = _carregar_parte_malha(p, pasta, tol_export)
        if err is not None:
            problemas.append(err)
        elif pm is not None:
            malhas.append(pm)

    max_pen_export = 0.0
    pares_overlap: list[dict[str, Any]] = []
    for i in range(len(malhas)):
        a = malhas[i]
        vol_a = max(0.0, (a.wmax[0] - a.wmin[0]) * (a.wmax[1] - a.wmin[1]) * (a.wmax[2] - a.wmin[2]))
        for j in range(i + 1, len(malhas)):
            b = malhas[j]
            ov = [min(a.wmax[d], b.wmax[d]) - max(a.wmin[d], b.wmin[d]) for d in range(3)]
            if min(ov) <= tol_export:
                continue
            vol_b = max(
                0.0, (b.wmax[0] - b.wmin[0]) * (b.wmax[1] - b.wmin[1]) * (b.wmax[2] - b.wmin[2])
            )
            vol_inter = ov[0] * ov[1] * ov[2]
            vol_min = min(vol_a, vol_b)
            pen = _penetracao_malhas(a, b, tol_export) if (a.fechada and b.fechada) else min(ov)
            if pen > tol_export:
                max_pen_export = max(max_pen_export, pen)
                pen_mm_par = round((pen / escala) * 1000.0, 3)
                pares_overlap.append({"par": [a.nome, b.nome], "penetracao_mm": pen_mm_par})
                problemas.append(f"interpenetracao:{a.nome}-{b.nome}:{pen_mm_par}mm")
                if (_TORSO_PARTES & {a.nome, b.nome}) and vol_min > 1e-12 and (vol_inter / vol_min) > 0.25:
                    problemas.append(f"parte_fundida_no_torso:{a.nome}-{b.nome}")

    pen_mm = round((max_pen_export / escala) * 1000.0, 3)
    ok = (not problemas) and (pen_mm <= LIMIAR_SEPARACAO_MM)
    return {
        "id": "G12",
        "status": "ok" if ok else "falhou",
        "medido": {
            "aplicavel": True,
            "partes": len(partes),
            "disjuntas": len(problemas) == 0,
            "penetracao_max_mm": pen_mm,
            **({"pares_sobrepostos": pares_overlap} if pares_overlap else {}),
            **({"problemas": problemas} if problemas else {}),
        },
        "limite": {"penetracao_max_mm": LIMIAR_SEPARACAO_MM},
        **({} if ok else {"codigo": "FORGE-E-QC"}),
    }


def _vec3_valido(val: Any) -> tuple[float, float, float] | None:
    if not isinstance(val, (list, tuple)) or len(val) != 3:
        return None
    if any(isinstance(c, bool) or not isinstance(c, (int, float)) for c in val):
        return None
    out = (float(val[0]), float(val[1]), float(val[2]))
    return out if all(math.isfinite(c) for c in out) else None


def verificar_g13_ancoras(
    item: dict, resultado: dict, escala: float, gltf: dict | None = None
) -> dict:
    """Gate G13: ``partes[].ancora`` bate com ``rig.ancoras[junta|nome]`` e ``skins`` dentro de <= 1 mm."""
    partes = resultado.get("partes") or item.get("partes") or []
    modo_rig = str(
        (item.get("rig") or {}).get("modo") or (resultado.get("rig") or {}).get("modo") or ""
    )
    if not partes and modo_rig != "motor6d":
        return {"id": "G13", "status": "ok", "medido": {"aplicavel": False}}

    rig_ancoras = (
        resultado.get("ancoras")
        or (resultado.get("rig") or {}).get("ancoras")
        or (item.get("rig") or {}).get("ancoras")
        or {}
    )
    problemas: list[str] = []
    if not partes:
        problemas.append("partes_ausentes")
    if not isinstance(rig_ancoras, dict) or not rig_ancoras:
        problemas.append("rig_ancoras_ausentes")

    max_erro_mm = 0.0
    if partes and isinstance(rig_ancoras, dict) and rig_ancoras:
        for p in partes:
            nome = str(p.get("nome") or "")
            junta = str(p.get("junta") or JOINT_R15.get(nome, ""))
            p_anc = _vec3_valido(p.get("ancora"))
            if p_anc is None:
                problemas.append(f"ancora_parte_invalida:{nome}")
                continue
            ref_raw = (
                rig_ancoras[junta]
                if (junta and junta in rig_ancoras)
                else rig_ancoras.get(nome)
            )
            ref = _vec3_valido(ref_raw)
            if ref is None:
                problemas.append(f"ancora_rig_ausente:{nome}")
                continue
            dist_exp = math.sqrt(sum((p_anc[d] - ref[d]) ** 2 for d in range(3)))
            erro_mm = (dist_exp / escala) * 1000.0
            max_erro_mm = max(max_erro_mm, erro_mm)
            if erro_mm > LIMIAR_ANCORA_MM:
                problemas.append(f"ancora_divergente:{nome}:{erro_mm:.3f}mm")

            if junta and junta in rig_ancoras and nome in rig_ancoras:
                ref_n = _vec3_valido(rig_ancoras[nome])
                if ref_n is not None:
                    d_jn = (
                        math.sqrt(sum((ref[d] - ref_n[d]) ** 2 for d in range(3))) / escala
                    ) * 1000.0
                    max_erro_mm = max(max_erro_mm, d_jn)
                    if d_jn > LIMIAR_ANCORA_MM:
                        problemas.append(f"ancora_junta_nome_divergente:{nome}:{d_jn:.3f}mm")

    if isinstance(gltf, dict) and gltf.get("skins") and partes:
        raw_nodes = gltf.get("nodes")
        nodes_gltf = raw_nodes if isinstance(raw_nodes, list) else []
        mundos = _matrizes_mundo_nos(gltf)
        joint_pos: dict[str, tuple[float, float, float]] = {}
        raw_skins = gltf.get("skins")
        skins_list = raw_skins if isinstance(raw_skins, list) else []
        if not isinstance(raw_skins, list):
            problemas.append("skins_invalido_no_gltf")
        for s_idx, skin in enumerate(skins_list):
            if not isinstance(skin, dict):
                problemas.append(f"skin_invalida_no_gltf:{s_idx}")
                continue
            joints = skin.get("joints")
            if not isinstance(joints, list):
                problemas.append(f"joints_invalidos_no_gltf:{s_idx}")
                continue
            for j_idx in joints:
                if (
                    not isinstance(j_idx, int)
                    or isinstance(j_idx, bool)
                    or j_idx < 0
                    or j_idx >= len(nodes_gltf)
                ):
                    problemas.append(f"joint_invalido_no_gltf:{j_idx}")
                    continue
                node_obj = nodes_gltf[j_idx]
                if not isinstance(node_obj, dict):
                    problemas.append(f"node_joint_invalido_no_gltf:{j_idx}")
                    continue
                if j_idx in mundos:
                    jname = str(node_obj.get("name") or "")
                    if jname:
                        m = mundos[j_idx]
                        joint_pos[jname] = (m[3], m[7], m[11])
        for p in partes:
            nome = str(p.get("nome") or "")
            junta = str(p.get("junta") or JOINT_R15.get(nome, ""))
            j_vec = joint_pos.get(nome) or (joint_pos.get(junta) if junta else None)
            if j_vec is None:
                continue
            alvo = _vec3_valido(p.get("ancora"))
            if alvo is None and isinstance(rig_ancoras, dict):
                alvo = _vec3_valido(rig_ancoras.get(junta) or rig_ancoras.get(nome))
            if alvo is None:
                continue
            drift_mm = (
                math.sqrt(sum((j_vec[d] - alvo[d]) ** 2 for d in range(3))) / escala
            ) * 1000.0
            max_erro_mm = max(max_erro_mm, drift_mm)
            if drift_mm > LIMIAR_ANCORA_MM:
                problemas.append(f"ancora_skin_divergente:{nome}:{drift_mm:.3f}mm")

    max_erro_mm = round(max_erro_mm, 3)
    ok = (not problemas) and (max_erro_mm <= LIMIAR_ANCORA_MM)
    return {
        "id": "G13",
        "status": "ok" if ok else "falhou",
        "medido": {
            "aplicavel": True,
            "partes": len(partes),
            "erro_ancora_max_mm": max_erro_mm,
            **({"problemas": problemas} if problemas else {}),
        },
        "limite": {"erro_ancora_max_mm": LIMIAR_ANCORA_MM},
        **({} if ok else {"codigo": "FORGE-E-QC"}),
    }


def verificar_gates_roblox(
    item: dict,
    perfil: dict,
    pasta: Path,
    resultado: dict,
    escala: float,
    gltf: dict | None = None,
) -> list[dict]:
    """Executa os portoes G12, G13 e G14 sobre o artefato Roblox/segmentado."""
    arquivos = resultado.get("arquivos", [])
    return [
        verificar_g12_separacao(item, pasta, resultado, escala),
        verificar_g13_ancoras(item, resultado, escala, gltf=gltf),
        verificar_g14_animacao_roblox(item, perfil, pasta, arquivos),
    ]
