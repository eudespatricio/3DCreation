"""Gate QC G16: deformacao sob animacao (Blender, LBS glTF em Python puro e Motor6D rigido)."""

from __future__ import annotations

import bisect
import math
import struct
from pathlib import Path
from typing import Any

from .errors import ForgeError
from .qc_geom import topologia
from .qc_glb import _accessor, _aplicar_mat4, _mat4_de_no, _mat4_identidade, _mat4_mul, analisar, ler_glb_bin
from .qc_glb_mat import _eh_int, _ler_indices_int, _lista_nums, _num_finito
from .qc_skin import _ler_ibms_row_major

LIMIAR_G16_MAX_STRETCH = 8.5
LIMIAR_G16_FRAC_GT_2X = 0.01
LIMIAR_G16_FRAC_GT_3X = 0.0025
LIMIAR_G16_MIN_ARESTAS_FRAC = 500
LIMIAR_G16_RIGIDO_MAX = 1.05


def _trs_para_mat4(t: tuple[float, ...], r: tuple[float, ...], s: tuple[float, ...]) -> list[float]:
    qx, qy, qz, qw = r[0], r[1], r[2], r[3]
    norm = math.sqrt(qx * qx + qy * qy + qz * qz + qw * qw)
    qx, qy, qz, qw = (qx / norm, qy / norm, qz / norm, qw / norm) if norm > 1e-12 else (0.0, 0.0, 0.0, 1.0)
    return [
        (1.0 - 2.0 * (qy * qy + qz * qz)) * s[0], 2.0 * (qx * qy - qz * qw) * s[1], 2.0 * (qx * qz + qy * qw) * s[2], t[0],
        2.0 * (qx * qy + qz * qw) * s[0], (1.0 - 2.0 * (qx * qx + qz * qz)) * s[1], 2.0 * (qy * qz - qx * qw) * s[2], t[1],
        2.0 * (qx * qz - qy * qw) * s[0], 2.0 * (qy * qz + qx * qw) * s[1], (1.0 - 2.0 * (qx * qx + qy * qy)) * s[2], t[2],
        0.0, 0.0, 0.0, 1.0,
    ]


def _slerp_quat(a: tuple[float, ...], b: tuple[float, ...], alpha: float) -> tuple[float, float, float, float]:
    ax, ay, az, aw = a[0], a[1], a[2], a[3]
    bx, by, bz, bw = b[0], b[1], b[2], b[3]
    dot = ax * bx + ay * by + az * bz + aw * bw
    if dot < 0.0:
        bx, by, bz, bw, dot = -bx, -by, -bz, -bw, -dot
    if dot > 0.9995:
        rx, ry, rz, rw = ax + alpha * (bx - ax), ay + alpha * (by - ay), az + alpha * (bz - az), aw + alpha * (bw - aw)
    else:
        ang = math.acos(max(-1.0, min(1.0, dot)))
        sin_a = math.sin(ang)
        fa, fb = math.sin((1.0 - alpha) * ang) / sin_a, math.sin(alpha * ang) / sin_a
        rx, ry, rz, rw = fa * ax + fb * bx, fa * ay + fb * by, fa * az + fb * bz, fa * aw + fb * bw
    norm = math.sqrt(rx * rx + ry * ry + rz * rz + rw * rw)
    return (rx / norm, ry / norm, rz / norm, rw / norm) if norm > 1e-12 else (0.0, 0.0, 0.0, 1.0)


def _amostrar_canal(tempos: list[float], vals: list[tuple[float, ...]], interp: str, t: float, is_quat: bool) -> tuple[float, ...]:
    n = len(tempos)
    if n == 0 or not vals:
        return (0.0, 0.0, 0.0, 1.0) if is_quat else (0.0, 0.0, 0.0)
    if n == 1 or t <= tempos[0]:
        return vals[1] if interp == "CUBICSPLINE" and len(vals) >= 3 else vals[0]
    if t >= tempos[-1]:
        return vals[3 * (n - 1) + 1] if interp == "CUBICSPLINE" and len(vals) >= 3 * n else vals[n - 1]
    idx1 = min(n - 1, max(1, bisect.bisect_right(tempos, t)))
    idx0 = idx1 - 1
    dt = tempos[idx1] - tempos[idx0]
    alpha = (t - tempos[idx0]) / dt if dt > 1e-9 else 0.0
    if interp == "STEP":
        return vals[idx0]
    if interp == "CUBICSPLINE" and len(vals) >= 3 * n:
        s2 = alpha * alpha
        s3 = s2 * alpha
        h00, h10, h01, h11 = 2.0 * s3 - 3.0 * s2 + 1.0, s3 - 2.0 * s2 + alpha, -2.0 * s3 + 3.0 * s2, s3 - s2
        p0, m0, p1, m1 = vals[3 * idx0 + 1], vals[3 * idx0 + 2], vals[3 * idx1 + 1], vals[3 * idx1]
        out = tuple(h00 * p0[d] + h10 * dt * m0[d] + h01 * p1[d] + h11 * dt * m1[d] for d in range(len(p0)))
        if is_quat:
            norm = math.sqrt(sum(c * c for c in out))
            return tuple(c / norm for c in out) if norm > 1e-12 else (0.0, 0.0, 0.0, 1.0)
        return out
    if is_quat:
        return _slerp_quat(vals[idx0], vals[idx1], alpha)
    a, b = vals[idx0], vals[idx1]
    return tuple(a[d] + alpha * (b[d] - a[d]) for d in range(len(a)))


def _resumir_ratios(ratios: list[float]) -> dict[str, Any]:
    if not ratios:
        return {"max_stretch": 1.0, "p99_stretch": 1.0, "arestas_gt_15": 0, "arestas_gt_20": 0, "arestas_gt_30": 0, "frac_gt_20": 0.0, "frac_gt_30": 0.0}
    ord_r = sorted(ratios)
    p99_idx = min(len(ord_r) - 1, int(0.99 * (len(ord_r) - 1)))
    gt15 = sum(1 for r in ratios if r > 1.5)
    gt20 = sum(1 for r in ratios if r > 2.0)
    gt30 = sum(1 for r in ratios if r > 3.0)
    n = float(len(ratios))
    return {
        "max_stretch": round(float(ord_r[-1]), 4),
        "p99_stretch": round(float(ord_r[p99_idx]), 4),
        "arestas_gt_15": gt15,
        "arestas_gt_20": gt20,
        "arestas_gt_30": gt30,
        "frac_gt_20": round(gt20 / n, 6),
        "frac_gt_30": round(gt30 / n, 6),
    }


_CHAVES_PICO = ("max_stretch", "p99_stretch", "arestas_gt_15", "arestas_gt_20", "arestas_gt_30", "frac_gt_20", "frac_gt_30")


def _agregar_pico_clipes(clipes_res: list[dict[str, Any]]) -> dict[str, Any]:
    if not clipes_res:
        return {**_resumir_ratios([]), "clipe_pico": ""}
    clipe_pico = max(clipes_res, key=lambda c: float(c.get("max_stretch", 1.0)))["nome"]
    return {**{k: max(c[k] for c in clipes_res) for k in _CHAVES_PICO}, "clipe_pico": clipe_pico}


def _ler_output_anim(gltf: dict, binario: bytes, acc_idx: int) -> list[tuple[float, ...]]:
    acc = gltf["accessors"][acc_idx]
    comp, norm = acc.get("componentType", 5126), bool(acc.get("normalized", False))
    esc = {5120: 1.0 / 127.0, 5121: 1.0 / 255.0, 5122: 1.0 / 32767.0, 5123: 1.0 / 65535.0}.get(comp, 1.0) if norm else 1.0
    raw = _accessor(gltf, binario, acc_idx)
    return [tuple(max(-1.0, float(c) * esc) if norm and comp in (5120, 5122) else float(c) * esc for c in row) for row in raw]


def _extrair_geometria_skinned(
    gltf: dict, binario: bytes, num_joints: int
) -> tuple[list[tuple[float, float, float]], list[list[tuple[int, float]]], list[tuple[int, int, float]]]:
    nodes, meshes, accessors = gltf.get("nodes") or [], gltf.get("meshes") or [], gltf.get("accessors") or []
    mesh_idxs: list[int] = list(
        dict.fromkeys(
            int(n["mesh"])
            for n in nodes
            if isinstance(n, dict) and n.get("skin") == 0 and _eh_int(n.get("mesh")) and 0 <= int(n["mesh"]) < len(meshes)
        )
    ) or [i for i, m in enumerate(meshes) if isinstance(m, dict)]

    rest_pos: list[tuple[float, float, float]] = []
    vert_infs: list[list[tuple[int, float]]] = []
    edges_set: set[tuple[int, int]] = set()
    for m_idx in mesh_idxs:
        for prim in meshes[m_idx].get("primitives") or []:
            if not isinstance(prim, dict) or prim.get("mode", 4) != 4:
                continue
            attrs = prim.get("attributes") or {}
            p_idx, j_idx, w_idx = attrs.get("POSITION"), attrs.get("JOINTS_0"), attrs.get("WEIGHTS_0")
            if not (_eh_int(p_idx) and _eh_int(j_idx) and _eh_int(w_idx)):
                continue
            pos_raw, j_raw, w_raw = _accessor(gltf, binario, p_idx), _accessor(gltf, binario, j_idx), _accessor(gltf, binario, w_idx)
            acc_w = accessors[w_idx]
            comp_w, norm_w = acc_w.get("componentType", 5126), bool(acc_w.get("normalized", False))
            esc_w = (1.0 / 255.0) if (comp_w == 5121 and norm_w) else ((1.0 / 65535.0) if (comp_w == 5123 and norm_w) else 1.0)
            n_v, base = min(len(pos_raw), len(j_raw), len(w_raw)), len(rest_pos)
            for k in range(n_v):
                p = pos_raw[k]
                rest_pos.append((float(p[0]), float(p[1]), float(p[2])))
                vert_infs.append([(int(jv), float(wv) * esc_w) for jv, wv in zip(j_raw[k], w_raw[k]) if float(wv) * esc_w > 1e-6 and 0 <= int(jv) < num_joints])
            idx_acc = prim.get("indices")
            ids = _ler_indices_int(_accessor(gltf, binario, idx_acc)) if _eh_int(idx_acc) else list(range(n_v))
            for k in range(0, len(ids) - 2, 3):
                a, b, c = ids[k], ids[k + 1], ids[k + 2]
                if a < n_v and b < n_v and c < n_v:
                    for u, v in ((a, b), (b, c), (c, a)):
                        if u != v:
                            edges_set.add((base + u, base + v) if u < v else (base + v, base + u))

    if not rest_pos or not edges_set:
        return rest_pos, vert_infs, []
    ys, zs = [p[1] for p in rest_pos], [p[2] for p in rest_pos]
    min_len = max(0.005 * max(max(ys) - min(ys), max(zs) - min(zs), 1e-4), 1e-5)
    edges_validas = [(u, v, comp) for u, v in sorted(edges_set) if (comp := math.dist(rest_pos[u], rest_pos[v])) >= min_len]
    return rest_pos, vert_infs, edges_validas


def _ordem_nos(nodes: list) -> tuple[dict[int, int], list[int]]:
    pais: dict[int, int] = {}
    for p_idx, no in enumerate(nodes):
        if isinstance(no, dict) and isinstance(no.get("children"), list):
            for ch in no["children"]:
                if _eh_int(ch) and 0 <= ch < len(nodes) and ch not in pais:
                    pais[ch] = p_idx
    ordem, fila = [], [i for i in range(len(nodes)) if i not in pais]
    vistos = set(fila)
    pos_q = 0
    while pos_q < len(fila):
        u = fila[pos_q]
        pos_q += 1
        ordem.append(u)
        no = nodes[u] if isinstance(nodes[u], dict) else {}
        for ch in no.get("children") or []:
            if _eh_int(ch) and 0 <= ch < len(nodes) and ch not in vistos:
                vistos.add(ch)
                fila.append(ch)
    ordem.extend(i for i in range(len(nodes)) if i not in vistos)
    return pais, ordem


def _medir_deformacao_glb_lbs(gltf: dict, binario: bytes) -> dict[str, Any]:
    """Avalia esticamento de arestas via LBS puro em Python sobre skins[0] + animations."""
    anims, skins = gltf.get("animations"), gltf.get("skins")
    if not isinstance(anims, list) or not anims:
        return {"fonte": "glb_lbs", **_resumir_ratios([]), "arestas_avaliadas": 0, "clipe_pico": "", "clipes": []}
    if not isinstance(skins, list) or not skins or not isinstance(skins[0], dict):
        clipes_r = [{"nome": str(a.get("name") or f"anim_{i}"), **_resumir_ratios([])} for i, a in enumerate(anims) if isinstance(a, dict)]
        return {"fonte": "glb_rigido", **_resumir_ratios([]), "arestas_avaliadas": 0, "clipe_pico": (clipes_r[0]["nome"] if clipes_r else ""), "clipes": clipes_r}

    nodes: list = gltf["nodes"] if isinstance(gltf.get("nodes"), list) else []
    accessors: list = gltf["accessors"] if isinstance(gltf.get("accessors"), list) else []
    skin0 = skins[0]
    raw_joints = skin0.get("joints")
    joints_raw: list = raw_joints if isinstance(raw_joints, list) else []
    ibms = _ler_ibms_row_major(gltf, binario, skin0, accessors, max(1, len(joints_raw)))
    rest_pos, vert_infs, edges_validas = _extrair_geometria_skinned(gltf, binario, len(joints_raw))
    if not edges_validas:
        return {"fonte": "glb_lbs", **_resumir_ratios([]), "arestas_avaliadas": 0, "clipe_pico": "", "clipes": []}

    active_verts = sorted({vi for e in edges_validas for vi in (e[0], e[1])})
    pais, ordem_nos = _ordem_nos(nodes)
    base_trs: list[tuple[tuple[float, ...], tuple[float, ...], tuple[float, ...]] | None] = []
    base_mats: list[list[float]] = []
    for no in nodes:
        if isinstance(no, dict) and no.get("matrix") is None:
            trs = (tuple(_lista_nums(no.get("translation"), 3) or (0.0, 0.0, 0.0)), tuple(_lista_nums(no.get("rotation"), 4) or (0.0, 0.0, 0.0, 1.0)), tuple(_lista_nums(no.get("scale"), 3) or (1.0, 1.0, 1.0)))
            base_trs.append(trs)
            base_mats.append(_trs_para_mat4(*trs))
        else:
            base_trs.append(None)
            base_mats.append(_mat4_de_no(no))

    clipes_res: list[dict[str, Any]] = []
    for a_idx, anim in enumerate(anims):
        if not isinstance(anim, dict):
            continue
        nome, samplers, channels = str(anim.get("name") or f"anim_{a_idx}"), anim.get("samplers") or [], anim.get("channels") or []
        cache_in: dict[int, list[float]] = {}
        cache_out: dict[int, list[tuple[float, ...]]] = {}
        t_min, t_max = float("inf"), float("-inf")
        ch_ok: list[tuple[int, str, list[float], list[tuple[float, ...]], str]] = []
        for ch in channels:
            if not isinstance(ch, dict):
                continue
            tgt, s_idx = ch.get("target") or {}, ch.get("sampler")
            n_idx, path = tgt.get("node"), tgt.get("path")
            if not (_eh_int(n_idx) and 0 <= n_idx < len(nodes) and path in ("translation", "rotation", "scale") and _eh_int(s_idx) and 0 <= s_idx < len(samplers) and isinstance(samplers[s_idx], dict)):
                continue
            smp = samplers[s_idx]
            in_a, out_a = smp.get("input"), smp.get("output")
            if not (_eh_int(in_a) and _eh_int(out_a)):
                continue
            if in_a not in cache_in:
                cache_in[in_a] = [float(x[0]) for x in _accessor(gltf, binario, in_a)]
            if out_a not in cache_out:
                cache_out[out_a] = _ler_output_anim(gltf, binario, out_a)
            if cache_in[in_a]:
                t_min, t_max = min(t_min, cache_in[in_a][0]), max(t_max, cache_in[in_a][-1])
            ch_ok.append((n_idx, path, cache_in[in_a], cache_out[out_a], str(smp.get("interpolation") or "LINEAR")))

        if not ch_ok or t_min == float("inf"):
            clipes_res.append({"nome": nome, **_resumir_ratios([])})
            continue
        tempos = [t_min + (t_max - t_min) * k / 8.0 for k in range(9)] if t_max > t_min else [t_min]
        clip_max_e, posed = [1.0] * len(edges_validas), list(rest_pos)
        for t_cur in tempos:
            local_mats = list(base_mats)
            trs_frame: dict[int, list[tuple[float, ...]]] = {}
            for n_idx, path, ts, outs, interp in ch_ok:
                if n_idx not in trs_frame:
                    bt = base_trs[n_idx]
                    trs_frame[n_idx] = [bt[0], bt[1], bt[2]] if bt is not None else [(0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0), (1.0, 1.0, 1.0)]
                slot = 0 if path == "translation" else (1 if path == "rotation" else 2)
                trs_frame[n_idx][slot] = _amostrar_canal(ts, outs, interp, t_cur, is_quat=(slot == 1))
            for n_idx, (tv, rv, sv) in trs_frame.items():
                local_mats[n_idx] = _trs_para_mat4(tv, rv, sv)
            world_mats = [_mat4_identidade() for _ in range(len(nodes))]
            for n_idx in ordem_nos:
                p_idx = pais.get(n_idx)
                world_mats[n_idx] = local_mats[n_idx] if p_idx is None else _mat4_mul(world_mats[p_idx], local_mats[n_idx])
            skin_mats = [_mat4_mul(world_mats[jn], ibms[j]) if _eh_int(jn) and 0 <= jn < len(nodes) else _mat4_identidade() for j, jn in enumerate(joints_raw)]
            for vi in active_verts:
                infs = vert_infs[vi]
                if not infs:
                    posed[vi] = rest_pos[vi]
                    continue
                pv, px, py, pz = rest_pos[vi], 0.0, 0.0, 0.0
                for ji, wv in infs:
                    tx, ty, tz = _aplicar_mat4(skin_mats[ji], pv)
                    px, py, pz = px + wv * tx, py + wv * ty, pz + wv * tz
                posed[vi] = (px, py, pz)
            for e_idx, (u, v, r_len) in enumerate(edges_validas):
                ratio = math.dist(posed[u], posed[v]) / r_len
                if ratio > clip_max_e[e_idx]:
                    clip_max_e[e_idx] = ratio
        res_c = _resumir_ratios(clip_max_e)
        clipes_res.append({"nome": nome, **res_c})
    return {"fonte": "glb_lbs", **_agregar_pico_clipes(clipes_res), "arestas_avaliadas": len(edges_validas), "clipes": clipes_res}


def _topologia_por_parte(gltf_c: dict, bin_c: bytes, alpha_cards: bool) -> tuple[int, int, int]:
    """Mede topologia por no de malha isolado para evitar solda falsa entre partes rigidas vizinhas."""
    nodes_c = gltf_c.get("nodes") or []
    meshes_c = gltf_c.get("meshes") or []
    acessores_c = gltf_c.get("accessors") or []
    bvs_c = gltf_c.get("bufferViews") or []
    bufs_c = gltf_c.get("buffers") or []
    sub_nodes = [
        no
        for no in nodes_c
        if isinstance(no, dict) and _eh_int(no.get("mesh")) and 0 <= int(no["mesh"]) < len(meshes_c)
    ]
    alvos = [
        {
            "nodes": [{k: v for k, v in no.items() if k != "children"}],
            "meshes": meshes_c,
            "accessors": acessores_c,
            "bufferViews": bvs_c,
            "buffers": bufs_c,
        }
        for no in sub_nodes
    ] or [gltf_c]
    nm_total = deg_total = inv_total = 0
    for sub in alvos:
        tp = topologia(sub, bin_c)
        nm_total += int(tp.get("arestas_t", 0)) if alpha_cards else int(tp.get("nao_manifold", 0))
        deg_total += int(tp.get("degeneradas", 0))
        inv_total += int(tp.get("invertidas", 0))
    return nm_total, deg_total, inv_total


def _verificar_motor6d_rigido(item: dict, perfil: dict, pasta: Path, resultado: dict) -> dict[str, Any]:
    arquivos = resultado.get("arquivos") or []
    arq_comb = next((a.get("caminho") for a in arquivos if isinstance(a, dict) and a.get("papel") == "partes_combinadas"), None)
    nome_comb = str(resultado.get("partes_combinadas") or (resultado.get("rig") or {}).get("partes_combinadas") or arq_comb or "partes_combinadas.glb")
    partes_decl = resultado.get("partes") or item.get("partes") or []
    nomes_esp = [str(p.get("nome") or "") for p in partes_decl if isinstance(p, dict) and p.get("nome")]
    problemas: list[str] = [] if nomes_esp else ["partes_ausentes"]
    caminho_comb, tris_comb, nm_comb = pasta / nome_comb, 0, 0
    if not caminho_comb.is_file():
        problemas.append(f"partes_combinadas_ausente:{nome_comb}")
    else:
        try:
            gltf_c, bin_c = ler_glb_bin(caminho_comb)
            info_c = analisar(gltf_c, bin_c)
            if info_c.get("erros"):
                problemas.extend(f"partes_combinadas_erro:{e}" for e in info_c["erros"])
            tris_comb = int(info_c.get("triangulos", 0))
            if tris_comb <= 0:
                problemas.append("partes_combinadas_sem_triangulos")
            nos_malha = {str(n.get("name") or "") for n in (gltf_c.get("nodes") or []) if isinstance(n, dict) and _eh_int(n.get("mesh")) and n.get("name")}
            faltando = [n for n in nomes_esp if n not in nos_malha]
            if faltando:
                problemas.append(f"partes_ausentes_no_glb:{','.join(faltando)}")
            v = perfil.get("validacao") or {}
            nm_max, deg_max = int(v.get("nao_manifold_max", 0)), int(v.get("faces_degeneradas_max", 0))
            nm_comb, deg_comb, inv_comb = _topologia_por_parte(gltf_c, bin_c, bool(item.get("alpha_cards")))
            if nm_comb > nm_max:
                problemas.append(f"nao_manifold:{nm_comb}>{nm_max}")
            if deg_comb > deg_max:
                problemas.append(f"degeneradas:{deg_comb}>{deg_max}")
            if inv_comb != 0:
                problemas.append(f"invertidas:{inv_comb}")
        except (ForgeError, OSError, OverflowError, struct.error, ValueError) as exc:
            problemas.append(f"partes_combinadas_ilegivel:{exc}")

    ok = not problemas
    limite = {"max_stretch": LIMIAR_G16_RIGIDO_MAX, "frac_gt_20": 0.0, "frac_gt_30": 0.0}
    medido = (
        {"aplicavel": True, "modo": "motor6d_rigido", "max_stretch": 1.0, "frac_gt_20": 0.0, "frac_gt_30": 0.0, "partes_combinadas": nome_comb, "partes_validas": len(nomes_esp), "triangulos": tris_comb, "nao_manifold": nm_comb}
        if ok
        else {"aplicavel": True, "modo": "motor6d_rigido", "partes_combinadas": nome_comb, "problemas": problemas}
    )
    return {"id": "G16", "status": "ok" if ok else "falhou", "medido": medido, "limite": limite, **({} if ok else {"codigo": "FORGE-E-QC"})}


def verificar_g16_deformacao(
    gltf: dict, binario: bytes, item: dict, perfil: dict, pasta: Path, resultado: dict, medidas: dict
) -> dict[str, Any]:
    """Gate G16: valida integridade de deformacao sob animacao (skinned LBS/Blender ou Motor6D rigido)."""
    modo_rig = str((item.get("rig") or {}).get("modo") or (resultado.get("rig") or {}).get("modo") or "").strip()
    if modo_rig == "motor6d":
        return _verificar_motor6d_rigido(item, perfil, pasta, resultado)

    tem_rig = bool(item.get("auto_rig")) or bool(modo_rig) or bool((item.get("anexo") or {}).get("skinned"))
    deform_anim = medidas.get("deformacao_anim")
    tem_anims = bool(item.get("animacoes_base") or item.get("clipes") or item.get("animacoes") or gltf.get("animations") or deform_anim)
    if not tem_rig or not tem_anims:
        return {"id": "G16", "status": "ok", "medido": {"aplicavel": False}}

    if isinstance(deform_anim, dict) and "max_stretch" in deform_anim:
        med: dict[str, Any] = {
            **deform_anim,
            "fonte": deform_anim.get("fonte") or "blender",
            "frac_gt_20": deform_anim.get("frac_gt_20", deform_anim.get("frac_gt_2x", 0.0)),
            "frac_gt_30": deform_anim.get("frac_gt_30", deform_anim.get("frac_gt_3x", 0.0)),
        }
    else:
        med = _medir_deformacao_glb_lbs(gltf, binario)

    problemas: list[str] = []
    max_s, f20, f30 = med.get("max_stretch"), med.get("frac_gt_20"), med.get("frac_gt_30")
    if not (_num_finito(max_s) and _num_finito(f20) and _num_finito(f30)):
        problemas.append("metricas_nao_finitas")
    else:
        max_f = float(max_s)  # type: ignore[arg-type]
        f20_f = float(f20)  # type: ignore[arg-type]
        f30_f = float(f30)  # type: ignore[arg-type]
        n_arestas = med.get("arestas_avaliadas")
        checar_frac = not (_eh_int(n_arestas) and 0 < int(n_arestas) < LIMIAR_G16_MIN_ARESTAS_FRAC)
        if max_f < 0.0 or f20_f < 0.0 or f30_f < 0.0:
            problemas.append("metricas_negativas")
        if max_f > LIMIAR_G16_MAX_STRETCH:
            problemas.append(f"max_stretch_excedido:{max_f:.3f}>{LIMIAR_G16_MAX_STRETCH}")
        if checar_frac and f20_f > LIMIAR_G16_FRAC_GT_2X:
            problemas.append(f"frac_gt_20_excedida:{f20_f:.5f}>{LIMIAR_G16_FRAC_GT_2X}")
        if checar_frac and f30_f > LIMIAR_G16_FRAC_GT_3X:
            problemas.append(f"frac_gt_30_excedida:{f30_f:.5f}>{LIMIAR_G16_FRAC_GT_3X}")

    ok = not problemas
    limite = {"max_stretch": LIMIAR_G16_MAX_STRETCH, "frac_gt_20": LIMIAR_G16_FRAC_GT_2X, "frac_gt_30": LIMIAR_G16_FRAC_GT_3X}
    return {
        "id": "G16",
        "status": "ok" if ok else "falhou",
        "medido": {"aplicavel": True, **med, **({"problemas": problemas} if problemas else {})},
        "limite": limite,
        **({} if ok else {"codigo": "FORGE-E-QC"}),
    }
