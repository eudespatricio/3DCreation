"""Orientacao, facetamento organico, pivo e sockets de QC (G1/G2)."""

from __future__ import annotations

import math
from typing import Any

from .errors import erro_qc
from .profiles import FRACAO_EMPUNHADURA
from .qc_glb import (
    _accessor,
    _mat4_de_no,
    _mat4_det3,
    _matrizes_mundo_nos,
    malha,
)
from .qc_glb_mat import _eh_int, _ler_indices_int, _lista_nums

LIMIAR_SCORE_FRENTE = 0.035

_TIPOS_ORGANICOS = frozenset(
    {
        "personagem_humanoide",
        "criatura",
        "criatura_quadrupede",
        "criatura_alada",
        "montaria",
    }
)


def _desvio_pivo(regra: str, minimo_y: float, maximo_y: float) -> float | None:
    """Quanto o pivo aplicado desvia da regra declarada, em metros (D58)."""
    altura = maximo_y - minimo_y
    if regra == "base":
        return abs(minimo_y)
    if regra == "centro":
        return abs((minimo_y + maximo_y) / 2.0)
    if regra == "topo":
        return abs(maximo_y)
    if regra == "empunhadura":
        return abs(minimo_y + FRACAO_EMPUNHADURA * altura)
    return None


def _vec3_norm(v: tuple[float, float, float]) -> tuple[float, float, float]:
    if not all(math.isfinite(c) for c in v):
        return (0.0, 0.0, 0.0)
    n = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    return (v[0] / n, v[1] / n, v[2] / n) if math.isfinite(n) and n > 1e-12 else (0.0, 0.0, 0.0)


def _normals_finitas(gltf: dict, binario: bytes) -> bool:
    raw_acc, raw_meshes = gltf.get("accessors"), gltf.get("meshes")
    acessores = raw_acc if isinstance(raw_acc, list) else []
    meshes = raw_meshes if isinstance(raw_meshes, list) else []
    if not binario or not meshes:
        return True
    vistos: set[int] = set()
    for m in [x for x in meshes if isinstance(x, dict)]:
        for prim in [p for p in (m.get("primitives") or []) if isinstance(p, dict)]:
            raw_attrs = prim.get("attributes")
            attrs = raw_attrs if isinstance(raw_attrs, dict) else {}
            n_idx = attrs.get("NORMAL")
            if not _eh_int(n_idx) or n_idx in vistos or not (0 <= n_idx < len(acessores)):
                continue
            acc = acessores[n_idx]
            if not isinstance(acc, dict) or not _eh_int(acc.get("bufferView")):
                continue
            vistos.add(n_idx)
            if any(not math.isfinite(float(c)) for nv in _accessor(gltf, binario, n_idx) for c in nv):
                return False
    return True


def _vec3_cross(
    a: tuple[float, float, float], b: tuple[float, float, float]
) -> tuple[float, float, float]:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _vec3_dot(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _inspecionar_facetamento_organico(gltf: dict, binario: bytes) -> dict:
    """Detecta malhas organicas 100% facetadas (normais quebradas em arestas suaves < 30 graus)."""
    raw_acc = gltf.get("accessors", [])
    acessores = raw_acc if isinstance(raw_acc, list) else []
    raw_meshes = gltf.get("meshes", [])
    meshes = raw_meshes if isinstance(raw_meshes, list) else []
    cos_30 = math.cos(math.radians(30.0))
    cos_meio_grau = math.cos(math.radians(0.5))

    arestas_adj: dict[
        tuple[tuple[float, float, float], tuple[float, float, float]],
        list[tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]],
    ] = {}
    sem_normal_accessor = False
    total_tris = 0

    for malha_gltf in meshes:
        if not isinstance(malha_gltf, dict):
            continue
        prims = malha_gltf.get("primitives", [])
        if not isinstance(prims, list):
            continue
        for prim in prims:
            if not isinstance(prim, dict):
                continue
            modo = prim.get("mode", 4)
            if not _eh_int(modo) or modo != 4:
                continue
            raw_attrs = prim.get("attributes")
            attrs = raw_attrs if isinstance(raw_attrs, dict) else {}
            pos_idx = attrs.get("POSITION")
            norm_idx = attrs.get("NORMAL")
            if not _eh_int(pos_idx) or pos_idx < 0 or pos_idx >= len(acessores) or not isinstance(acessores[pos_idx], dict):
                continue
            pos = [(float(p[0]), float(p[1]), float(p[2])) for p in _accessor(gltf, binario, pos_idx) if len(p) >= 3]
            if not pos:
                continue
            idx_acc = prim.get("indices")
            if _eh_int(idx_acc) and 0 <= idx_acc < len(acessores) and isinstance(acessores[idx_acc], dict):
                ids = _ler_indices_int(_accessor(gltf, binario, idx_acc))
                if any(i < 0 or i >= len(pos) for i in ids):
                    raise erro_qc(f"indice fora do intervalo no facetamento: {idx_acc}")
            else:
                ids = list(range(len(pos)))
            n_tris_prim = len(ids) // 3
            total_tris += n_tris_prim
            if not _eh_int(norm_idx) or norm_idx < 0 or norm_idx >= len(acessores) or not isinstance(acessores[norm_idx], dict):
                sem_normal_accessor = True
                continue
            raw_norms = [n for n in _accessor(gltf, binario, norm_idx) if len(n) >= 3]
            if any(not math.isfinite(float(c)) for n in raw_norms for c in n[:3]):
                raise erro_qc(f"normal nao finita no accessor: {norm_idx}")
            norms = [
                _vec3_norm((float(n[0]), float(n[1]), float(n[2])))
                for n in raw_norms
            ]
            if len(norms) < len(pos):
                sem_normal_accessor = True
                continue

            solda_p = [(round(p[0], 5), round(p[1], 5), round(p[2], 5)) for p in pos]
            for k in range(0, len(ids) - 2, 3):
                i0, i1, i2 = ids[k], ids[k + 1], ids[k + 2]
                if (
                    i0 < 0
                    or i1 < 0
                    or i2 < 0
                    or i0 >= len(pos)
                    or i1 >= len(pos)
                    or i2 >= len(pos)
                ):
                    continue
                p0, p1, p2 = pos[i0], pos[i1], pos[i2]
                ux, uy, uz = p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]
                vx, vy, vz = p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2]
                fn = _vec3_norm((uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx))
                if fn == (0.0, 0.0, 0.0):
                    continue
                for a, b in ((i0, i1), (i1, i2), (i2, i0)):
                    ka, kb = solda_p[a], solda_p[b]
                    if ka == kb:
                        continue
                    if ka < kb:
                        chave = (ka, kb)
                        na, nb = norms[a], norms[b]
                    else:
                        chave = (kb, ka)
                        na, nb = norms[b], norms[a]
                    arestas_adj.setdefault(chave, []).append((fn, na, nb))

    if sem_normal_accessor and total_tris >= 200:
        return {
            "facetada": True,
            "fracao_facetada": 1.0,
            "arestas_suaves": total_tris,
            "arestas_facetadas": total_tris,
            "motivo": "malha_organica_facetada",
        }

    arestas_suaves = 0
    arestas_facetadas = 0
    for faces in arestas_adj.values():
        if len(faces) != 2:
            continue
        (fn1, n1a, n1b), (fn2, n2a, n2b) = faces[0], faces[1]
        cos_dih = _vec3_dot(fn1, fn2)
        if cos_30 < cos_dih < cos_meio_grau:
            arestas_suaves += 1
            split_a = _vec3_dot(n1a, n2a) < 0.9995
            split_b = _vec3_dot(n1b, n2b) < 0.9995
            colado_face = (
                _vec3_dot(n1a, fn1) > 0.9995
                and _vec3_dot(n2a, fn2) > 0.9995
                and _vec3_dot(n1b, fn1) > 0.9995
                and _vec3_dot(n2b, fn2) > 0.9995
            )
            if (split_a and split_b) or colado_face:
                arestas_facetadas += 1

    fracao = (arestas_facetadas / float(arestas_suaves)) if arestas_suaves > 0 else 0.0
    facetada = total_tris >= 200 and arestas_suaves >= 8 and fracao > 0.85
    return {
        "facetada": facetada,
        "fracao_facetada": round(fracao, 4),
        "arestas_suaves": arestas_suaves,
        "arestas_facetadas": arestas_facetadas,
        "motivo": "malha_organica_facetada" if facetada else None,
    }


def _g2_orientacao(
    gltf: dict, binario: bytes, item: dict, perfil: dict, info: dict
) -> tuple[bool, dict]:
    """Valida determinante, transformacao residual, frente -Z, roll de ossos e equipaveis em G2."""
    motivos: list[str] = []
    avisos: list[str] = []

    def _marcar(motivo: str) -> None:
        if motivo not in motivos:
            motivos.append(motivo)

    def _avisar(aviso: str) -> None:
        if aviso not in avisos:
            avisos.append(aviso)

    raw_nodes = gltf.get("nodes", [])
    nodes = raw_nodes if isinstance(raw_nodes, list) else []
    raw_skins = gltf.get("skins", [])
    skins = raw_skins if isinstance(raw_skins, list) else []
    mundos = _matrizes_mundo_nos(gltf)
    joints = {
        j
        for s in skins
        if isinstance(s, dict) and isinstance(s.get("joints"), list)
        for j in s["joints"]
        if _eh_int(j) and 0 <= j < len(nodes) and isinstance(nodes[j], dict)
    }

    if not _normals_finitas(gltf, binario):
        _marcar("normal_nao_finita")

    if any(_mat4_det3(m) <= 1e-12 for m in mundos.values()):
        _marcar("det_negativo")

    for s in skins:
        if not isinstance(s, dict):
            continue
        ibm_idx = s.get("inverseBindMatrices")
        if not _eh_int(ibm_idx):
            continue
        for mat in _accessor(gltf, binario, ibm_idx):
            if len(mat) != 16:
                continue
            rm = [
                float(mat[0]), float(mat[4]), float(mat[8]), 0.0,
                float(mat[1]), float(mat[5]), float(mat[9]), 0.0,
                float(mat[2]), float(mat[6]), float(mat[10]), 0.0,
                0.0, 0.0, 0.0, 1.0,
            ]
            if _mat4_det3(rm) <= 1e-12:
                _marcar("ibm_det_negativo")
                break

    if perfil.get("aplicar_transforms", True):
        for idx, no in enumerate(nodes):
            if idx in joints or not isinstance(no, dict):
                continue
            rot = _lista_nums(no.get("rotation"), 4)
            if rot is not None:
                qx, qy, qz, qw = rot
                qn = math.sqrt(qx * qx + qy * qy + qz * qz + qw * qw)
                if qn > 1e-12 and abs(qw / qn) < 0.999:
                    _marcar("rotacao_residual_no")
                    break
            mat_no = _lista_nums(no.get("matrix"), 16)
            if mat_no is not None:
                m = _mat4_de_no(no)
                cols = (
                    _vec3_norm((m[0], m[4], m[8])),
                    _vec3_norm((m[1], m[5], m[9])),
                    _vec3_norm((m[2], m[6], m[10])),
                )
                if any(cols[i][i] < 0.999 for i in range(3)):
                    _marcar("rotacao_residual_no")
                    break

    frente_perfil = (perfil.get("eixos") or {}).get("frente", "-Z")
    tem_esq_pos = bool(joints) and any(
        "translation" in nodes[j] or "rotation" in nodes[j] or "matrix" in nodes[j]
        for j in joints
    )
    ossos_desalinhados: list[str] = []
    if frente_perfil == "-Z" and tem_esq_pos:
        por_nome = {
            nodes[j]["name"]: mundos[j]
            for j in joints
            if isinstance(nodes[j].get("name"), str) and j in mundos
        }
        for foot_n, toe_n in (("Foot.L", "Toe.L"), ("Foot.R", "Toe.R")):
            if foot_n in por_nome and toe_n in por_nome:
                if por_nome[toe_n][11] > por_nome[foot_n][11] + 0.01:
                    _marcar("rig_de_costas")

        eh_criatura_ou_montaria = (
            str(item.get("esqueleto") or "") in ("quadruped@1", "winged_mount@1")
            or str(item.get("tipo") or "")
            in ("criatura", "criatura_quadrupede", "criatura_alada", "montaria")
        )
        if eh_criatura_ou_montaria:
            ossos_frente = [por_nome[n][11] for n in ("Jaw", "Head", "Neck1") if n in por_nome]
            ossos_tras = [
                por_nome[n][11] for n in ("Tail3", "Tail2", "Tail1", "Hips") if n in por_nome
            ]
            if ossos_frente and ossos_tras and min(ossos_frente) > max(ossos_tras) + 0.01:
                _marcar("rig_de_costas")
                _marcar("criatura_de_costas")

        esq_perfil = str(
            (perfil.get("rig") or {}).get("esqueleto_padrao")
            or (perfil.get("rig") or {}).get("padrao")
            or ""
        )
        esq_item = str(item.get("esqueleto") or "")
        eh_humanoid_godot = (
            esq_item.startswith("godot-humanoid")
            or (not esq_item and esq_perfil.startswith("godot-humanoid"))
        ) and not eh_criatura_ou_montaria
        if eh_humanoid_godot:
            cos5 = math.cos(math.radians(5.0))
            alvos_braco: dict[str, tuple[float, float, float]] = {}
            planos_lado: dict[str, tuple[float, float, float]] = {}

            def _proj_eixo_perp(alvo_v: tuple[float, float, float], c1_v: tuple[float, float, float]) -> tuple[float, float, float] | None:
                cr = _vec3_cross(alvo_v, c1_v)
                return _vec3_norm(_vec3_cross(c1_v, _vec3_norm(cr))) if math.sqrt(_vec3_dot(cr, cr)) > 1e-4 else None

            for sup_n, inf_n in (("UpperArm.L", "LowerArm.L"), ("UpperArm.R", "LowerArm.R")):
                if sup_n in por_nome and inf_n in por_nome:
                    ms, mi = por_nome[sup_n], por_nome[inf_n]
                    cruz = _vec3_cross(_vec3_norm((ms[1], ms[5], ms[9])), _vec3_norm((mi[1], mi[5], mi[9])))
                    if math.sqrt(_vec3_dot(cruz, cruz)) > 0.08:
                        n_ref = _vec3_norm(cruz)
                        if abs(n_ref[0]) >= 0.82 and abs(n_ref[2]) <= 0.30:
                            n_ref = (-n_ref[0], -n_ref[1], -n_ref[2]) if n_ref[0] < 0.0 else n_ref
                            planos_lado[sup_n] = alvos_braco[sup_n] = alvos_braco[inf_n] = n_ref
            for sup_n, inf_n, op_sup in (("UpperArm.L", "LowerArm.L", "UpperArm.R"), ("UpperArm.R", "LowerArm.R", "UpperArm.L")):
                if sup_n not in planos_lado and op_sup in planos_lado:
                    nr = planos_lado[op_sup]
                    for bn in (sup_n, inf_n):
                        if bn in por_nome:
                            mb_op = por_nome[bn]
                            p = _proj_eixo_perp((nr[0], -nr[1], -nr[2]), _vec3_norm((mb_op[1], mb_op[5], mb_op[9])))
                            if p is not None:
                                alvos_braco[bn] = p

            ossos_check = ("Shoulder.L", "Shoulder.R", "UpperArm.L", "LowerArm.L", "UpperArm.R", "LowerArm.R",
                           "UpperLeg.L", "LowerLeg.L", "UpperLeg.R", "LowerLeg.R", "Foot.L", "Foot.R")
            for bnome in ossos_check:
                if bnome not in por_nome:
                    continue
                mb = por_nome[bnome]
                c0, c1 = _vec3_norm((mb[0], mb[4], mb[8])), _vec3_norm((mb[1], mb[5], mb[9]))
                c0_sag = None
                if bnome in alvos_braco:
                    c0_ref = alvos_braco[bnome]
                else:
                    alvo_z = (0.0, 1.0, 0.0) if abs(c1[2]) > 0.92 else (0.0, 0.0, -1.0)
                    cruz_cz = _vec3_cross(c1, alvo_z)
                    if math.sqrt(_vec3_dot(cruz_cz, cruz_cz)) <= 1e-4:
                        continue
                    c0_ref = _vec3_norm(cruz_cz)
                    if bnome in ("UpperArm.L", "LowerArm.L", "UpperArm.R", "LowerArm.R") and c1[1] < -0.1:
                        c0_sag = _proj_eixo_perp((1.0, 0.0, 0.0), c1)
                if _vec3_dot(c0, c0_ref) < cos5 and (c0_sag is None or _vec3_dot(c0, c0_sag) < cos5):
                    _marcar("roll_osso_desalinhado")
                    if bnome not in ossos_desalinhados:
                        ossos_desalinhados.append(bnome)

            for nome_l, nome_r in (("UpperArm.L", "UpperArm.R"), ("LowerArm.L", "LowerArm.R")):
                if nome_l in por_nome and nome_r in por_nome:
                    ml, mr = por_nome[nome_l], por_nome[nome_r]
                    c0_l = _vec3_norm((ml[0], ml[4], ml[8]))
                    c0_r = _vec3_norm((mr[0], mr[4], mr[8]))
                    c0_l_esp = (c0_l[0], -c0_l[1], -c0_l[2])
                    if _vec3_dot(c0_r, c0_l_esp) < 0.5:
                        _marcar("roll_osso_desalinhado")
                        if nome_r not in ossos_desalinhados:
                            ossos_desalinhados.append(nome_r)

    eh_criatura_tipo = (
        str(item.get("esqueleto") or "") in ("quadruped@1", "winged_mount@1")
        or str(item.get("tipo") or "")
        in ("criatura", "criatura_quadrupede", "criatura_alada", "montaria")
    )
    if frente_perfil == "-Z" and eh_criatura_tipo and gltf.get("meshes"):
        verts, _ = malha(gltf, binario)
        y_min = info["min"][1]
        alt = info["bbox_m"][1]
        z_min, z_max = info["min"][2], info["max"][2]
        dz = z_max - z_min
        if verts and alt > 1e-6 and dz > 1e-6:
            z_mid = 0.5 * (z_min + z_max)
            topo_zs = [v[2] for v in verts if v[1] >= y_min + 0.72 * alt]
            if topo_zs and (sum(topo_zs) / len(topo_zs)) > z_mid + 0.08 * dz:
                _marcar("malha_de_costas")
                _marcar("criatura_de_costas")

    raw_sockets = info.get("_sockets")
    if raw_sockets is None:
        cand_sock = item.get("sockets_manifest") or item.get("sockets")
        if isinstance(cand_sock, dict) or (
            isinstance(cand_sock, list) and cand_sock and not isinstance(cand_sock[0], str)
        ):
            raw_sockets = cand_sock
    entradas_sockets: list[Any] = []
    if isinstance(raw_sockets, dict) and raw_sockets:
        entradas_sockets = list(raw_sockets.values())
    elif isinstance(raw_sockets, list) and raw_sockets:
        entradas_sockets = [s for s in raw_sockets if not isinstance(s, str)]
    if entradas_sockets:
        nomes_ossos_validos = set(info.get("nomes_ossos") or [])
        if not nomes_ossos_validos:
            nomes_ossos_validos = {str(n.get("name")) for n in nodes if isinstance(n, dict) and isinstance(n.get("name"), str)}
        for sk_cfg in entradas_sockets:
            if not isinstance(sk_cfg, dict):
                _marcar("socket_invalido")
                continue
            osso_sk = str(sk_cfg.get("osso") or "").strip()
            if not osso_sk or (nomes_ossos_validos and osso_sk not in nomes_ossos_validos):
                _marcar("socket_invalido")
            q_sk = sk_cfg.get("rotacao_quat_wxyz")
            if q_sk is not None:
                if not isinstance(q_sk, (list, tuple)) or len(q_sk) != 4:
                    _marcar("socket_invalido")
                else:
                    try:
                        qf = [float(c) for c in q_sk]
                        q_norm = math.sqrt(sum(c * c for c in qf))
                        if not all(math.isfinite(c) for c in qf) or abs(q_norm - 1.0) > 0.02:
                            _marcar("socket_invalido")
                    except (TypeError, ValueError):
                        _marcar("socket_invalido")

    sockets_pedidos = item.get("sockets")
    if isinstance(sockets_pedidos, (list, tuple)) and sockets_pedidos:
        nomes_sockets_extraidos = {
            str(s.get("nome")) for s in entradas_sockets if isinstance(s, dict)
        }
        for nome_pedido in sockets_pedidos:
            if str(nome_pedido) not in nomes_sockets_extraidos:
                _marcar("socket_ausente")

    if frente_perfil == "-Z" and item.get("tipo") == "personagem_humanoide" and gltf.get("meshes"):
        verts, _ = malha(gltf, binario)
        y_min, alt = info["min"][1], info["bbox_m"][1]
        if verts and alt > 1e-6:
            pes_zs = [v[2] for v in verts if v[1] <= y_min + 0.06 * alt]
            can_zs = [v[2] for v in verts if y_min + 0.12 * alt <= v[1] <= y_min + 0.30 * alt]
            if pes_zs and not can_zs:
                can_zs = [
                    v[2] for v in verts if y_min + 0.10 * alt <= v[1] <= y_min + 0.82 * alt
                ]
            if pes_zs and can_zs:
                pes_mean = sum(pes_zs) / len(pes_zs)
                pes_mid = 0.5 * (min(pes_zs) + max(pes_zs))
                can_mean = sum(can_zs) / len(can_zs)
                can_mid = 0.5 * (min(can_zs) + max(can_zs))
                score_z = 0.5 * ((pes_mean - can_mean) + (pes_mid - can_mid)) / alt
                if score_z > LIMIAR_SCORE_FRENTE:
                    _marcar("malha_de_costas")
                elif abs(score_z) < LIMIAR_SCORE_FRENTE and not skins:
                    _avisar("orientacao_frente_ambigua")

    if gltf.get("meshes"):
        if item.get("parte") == "arma" and item.get("pivot") == "empunhadura":
            if abs(info["min"][1]) > info["max"][1] + 0.02:
                _marcar("equipavel_invertido")
        elif item.get("parte") == "escudo":
            bm = info["bbox_m"]
            if max(bm) > 1e-6 and bm[1] < 0.4 * max(bm):
                _marcar("equipavel_invertido")

    ok = len(motivos) == 0
    detalhes: dict = {"ok": ok, "motivos": motivos}
    if avisos:
        detalhes["avisos"] = avisos
    if ossos_desalinhados:
        detalhes["ossos_desalinhados"] = ossos_desalinhados
    return ok, detalhes
