"""Analise de skinning, pesos nao-raiz e deformacao LBS sintetica para QC G6/G9."""

from __future__ import annotations

import math

from .qc_glb import _accessor, _aplicar_mat4, _mat4_identidade, _matrizes_mundo_nos
from .qc_glb_mat import _eh_int, _num_finito

_SIN_30 = 0.5
_COS_30_M1 = math.cos(math.radians(30.0)) - 1.0
_NOMES_RAIZ = frozenset({"Root", "HumanoidRootPart"})
_OSSOS_MEMBRO_CORE = frozenset(
    {
        "UpperArm.L", "UpperArm.R", "LowerArm.L", "LowerArm.R",
        "UpperLeg.L", "UpperLeg.R", "LowerLeg.L", "LowerLeg.R",
        "LeftUpperArm", "RightUpperArm", "LeftLowerArm", "RightLowerArm",
        "LeftUpperLeg", "RightUpperLeg", "LeftLowerLeg", "RightLowerLeg",
    }
)


def _pais_nos(nodes: list) -> dict[int, int]:
    pais: dict[int, int] = {}
    for p_idx, no in enumerate(nodes):
        if not isinstance(no, dict):
            continue
        filhos = no.get("children")
        if not isinstance(filhos, list):
            continue
        for filho in filhos:
            if _eh_int(filho) and filho not in pais:
                pais[filho] = p_idx
    return pais


def _slots_raiz(skin_obj: dict, nodes: list, pais: dict[int, int], num_joints: int) -> set[int]:
    if num_joints <= 1:
        return set()
    joints_raw = skin_obj.get("joints")
    joints = joints_raw if isinstance(joints_raw, list) else []
    valid_nodes = [j for j in joints if _eh_int(j) and 0 <= j < len(nodes)]
    nomeados = {
        idx
        for idx, j in enumerate(valid_nodes)
        if isinstance(nodes[j], dict) and nodes[j].get("name") in _NOMES_RAIZ
    }
    if nomeados:
        return nomeados
    joint_set = set(valid_nodes)
    raizes_hier = {idx for idx, j in enumerate(valid_nodes) if pais.get(j) not in joint_set}
    if 0 < len(raizes_hier) < len(valid_nodes):
        return raizes_hier
    return {0}


def _ler_ibms_row_major(
    gltf: dict, binario: bytes, skin_obj: dict, acessores: list, num_joints: int
) -> list[list[float]]:
    ident = _mat4_identidade()
    ibms = [ident for _ in range(max(1, num_joints))]
    ibm_idx = skin_obj.get("inverseBindMatrices")
    if not _eh_int(ibm_idx) or ibm_idx < 0 or ibm_idx >= len(acessores):
        return ibms
    acc = acessores[ibm_idx]
    if not isinstance(acc, dict) or not _eh_int(acc.get("bufferView")) or acc.get("type") != "MAT4":
        return ibms
    mats = _accessor(gltf, binario, ibm_idx)
    for j, cm in enumerate(mats[:num_joints]):
        if len(cm) == 16 and all(_num_finito(v) for v in cm):
            c = [float(v) for v in cm]
            ibms[j] = [
                c[0], c[4], c[8], c[12],
                c[1], c[5], c[9], c[13],
                c[2], c[6], c[10], c[14],
                c[3], c[7], c[11], c[15],
            ]
    return ibms


def _prim_deforma_por_rotacao(
    gltf: dict,
    binario: bytes,
    atributos: dict,
    acessores: list,
    skin_obj: dict,
    num_joints: int,
    root_slots: set[int],
    mundos: dict[int, list[float]],
    juntas: list[tuple],
    pesos: list[tuple],
    escala_w: float,
) -> bool:
    pos_idx = atributos.get("POSITION")
    if not _eh_int(pos_idx) or pos_idx < 0 or pos_idx >= len(acessores):
        return True
    pos_acc = acessores[pos_idx]
    if not isinstance(pos_acc, dict) or not _eh_int(pos_acc.get("bufferView")) or pos_acc.get("type") != "VEC3":
        return True
    pos_raw = _accessor(gltf, binario, pos_idx)
    total_v = min(len(pos_raw), len(juntas), len(pesos))
    if total_v == 0:
        return True
    pos_pts = [(float(p[0]), float(p[1]), float(p[2])) for p in pos_raw[:total_v] if len(p) >= 3]
    if len(pos_pts) < total_v:
        return True
    xs = [p[0] for p in pos_pts]
    ys = [p[1] for p in pos_pts]
    zs = [p[2] for p in pos_pts]
    diag = math.sqrt((max(xs) - min(xs)) ** 2 + (max(ys) - min(ys)) ** 2 + (max(zs) - min(zs)) ** 2)
    limiar = 1e-5 * max(1.0, diag)

    ibms = _ler_ibms_row_major(gltf, binario, skin_obj, acessores, num_joints)
    raw_joints = skin_obj.get("joints")
    joints_raw = raw_joints if isinstance(raw_joints, list) else []
    mats_j = [
        mundos.get(j_node, _mat4_identidade()) if _eh_int(j_node) else _mat4_identidade()
        for j_node in joints_raw[:num_joints]
    ]
    while len(mats_j) < num_joints:
        mats_j.append(_mat4_identidade())

    for vi in range(total_v):
        pv = pos_pts[vi]
        j_vec = juntas[vi]
        w_vec = pesos[vi]
        dxx = dxy = dxz = 0.0
        dyx = dyy = dyz = 0.0
        for jv, w_raw in zip(j_vec, w_vec):
            wv = float(w_raw) * escala_w
            if wv <= 1e-6 or not _num_finito(jv):
                continue
            ji = int(jv)
            if ji < 0 or ji >= num_joints or ji in root_slots:
                continue
            bx, by, bz = _aplicar_mat4(ibms[ji], pv)
            lx_y = _COS_30_M1 * by - _SIN_30 * bz
            lx_z = _SIN_30 * by + _COS_30_M1 * bz
            ly_x = _COS_30_M1 * bx + _SIN_30 * bz
            ly_z = -_SIN_30 * bx + _COS_30_M1 * bz
            m = mats_j[ji]
            dxx += wv * (m[1] * lx_y + m[2] * lx_z)
            dxy += wv * (m[5] * lx_y + m[6] * lx_z)
            dxz += wv * (m[9] * lx_y + m[10] * lx_z)
            dyx += wv * (m[0] * ly_x + m[2] * ly_z)
            dyy += wv * (m[4] * ly_x + m[6] * ly_z)
            dyz += wv * (m[8] * ly_x + m[10] * ly_z)
        if math.sqrt(dxx * dxx + dxy * dxy + dxz * dxz) > limiar:
            return True
        if math.sqrt(dyx * dyx + dyy * dyy + dyz * dyz) > limiar:
            return True
    return False


def _skin_status(gltf: dict, binario: bytes) -> dict:
    """Valida atributos JOINTS_0/WEIGHTS_0, pesos nao-raiz e deformacao LBS em pose."""
    raw_skins = gltf.get("skins", [])
    skins = raw_skins if isinstance(raw_skins, list) else []
    raw_meshes = gltf.get("meshes", [])
    meshes = raw_meshes if isinstance(raw_meshes, list) else []
    raw_acc = gltf.get("accessors", [])
    acessores = raw_acc if isinstance(raw_acc, list) else []
    raw_nodes = gltf.get("nodes", [])
    nodes = raw_nodes if isinstance(raw_nodes, list) else []
    if not skins or not meshes:
        return {
            "ok": True,
            "primitivas_skinned": 0,
            "sem_atributos": 0,
            "joints_invalidos": 0,
            "pesos_invalidos": 0,
            "somente_raiz": 0,
            "sem_deformacao": 0,
            "ossos_membro_vazios": [],
        }

    pares_skinned: list[tuple[dict, int, dict]] = []
    for no in nodes:
        if not isinstance(no, dict):
            continue
        s_idx = no.get("skin")
        m_idx = no.get("mesh")
        if _eh_int(s_idx) and _eh_int(m_idx) and 0 <= s_idx < len(skins) and 0 <= m_idx < len(meshes):
            skin_obj = skins[s_idx]
            mesh_obj = meshes[m_idx]
            if isinstance(skin_obj, dict) and isinstance(mesh_obj, dict):
                joints_raw = skin_obj.get("joints")
                pares_skinned.append(
                    (mesh_obj, len(joints_raw) if isinstance(joints_raw, list) else 0, skin_obj)
                )
    if not pares_skinned:
        skin0 = skins[0] if isinstance(skins[0], dict) else {}
        joints0 = skin0.get("joints")
        num_joints_0 = len(joints0) if isinstance(joints0, list) else 0
        pares_skinned = [(m, num_joints_0, skin0) for m in meshes if isinstance(m, dict)]

    pais = _pais_nos(nodes)
    mundos = _matrizes_mundo_nos(gltf)
    prims_skinned = sem_atributos = joints_invalidos = pesos_invalidos = somente_raiz = sem_deformacao = 0
    skin_dom_stats: dict[int, tuple[dict[int, str], list[int], dict[str, int]]] = {}

    for malha_gltf, num_joints, skin_obj in pares_skinned:
        prims = malha_gltf.get("primitives", [])
        if not isinstance(prims, list):
            continue
        root_slots = _slots_raiz(skin_obj, nodes, pais, num_joints)
        sid = id(skin_obj)
        if sid not in skin_dom_stats:
            j_raw = skin_obj.get("joints")
            j_list = j_raw if isinstance(j_raw, list) else []
            s_names = {
                slot: str(nodes[n_idx].get("name") or "")
                for slot, n_idx in enumerate(j_list[:num_joints])
                if _eh_int(n_idx) and 0 <= n_idx < len(nodes) and isinstance(nodes[n_idx], dict)
            }
            skin_dom_stats[sid] = (s_names, [0], {})
        slot_names, total_v_box, dom_counts = skin_dom_stats[sid]
        for prim in prims:
            if not isinstance(prim, dict):
                continue
            modo = prim.get("mode", 4)
            if not _eh_int(modo) or modo != 4:
                continue
            prims_skinned += 1
            raw_atrib = prim.get("attributes")
            atributos = raw_atrib if isinstance(raw_atrib, dict) else {}
            j_idx = atributos.get("JOINTS_0")
            w_idx = atributos.get("WEIGHTS_0")
            if (
                not _eh_int(j_idx)
                or not _eh_int(w_idx)
                or j_idx < 0
                or w_idx < 0
                or j_idx >= len(acessores)
                or w_idx >= len(acessores)
                or not isinstance(acessores[j_idx], dict)
                or not isinstance(acessores[w_idx], dict)
            ):
                sem_atributos += 1
                continue
            acc_w = acessores[w_idx]
            comp_raw = acc_w.get("componentType", 5126)
            comp_w = comp_raw if _eh_int(comp_raw) else 5126
            norm_w = bool(acc_w.get("normalized", False))
            escala_w = 1.0
            if norm_w and comp_w == 5121:
                escala_w = 1.0 / 255.0
            elif norm_w and comp_w == 5123:
                escala_w = 1.0 / 65535.0
            juntas = _accessor(gltf, binario, j_idx)
            pesos = _accessor(gltf, binario, w_idx)
            total_v = min(len(juntas), len(pesos))
            if total_v == 0:
                sem_atributos += 1
                continue
            total_v_box[0] += total_v
            validos = 0
            joint_ruim = False
            peso_nao_raiz = 0.0
            for j_vec, w_vec in zip(juntas[:total_v], pesos[:total_v]):
                wf = [float(x) * escala_w for x in w_vec]
                if any(not math.isfinite(x) or x < -1e-6 for x in wf):
                    continue
                if 0.98 <= sum(wf) <= 1.02:
                    validos += 1
                best_j = -1
                best_w = 1e-6
                for jv, wv in zip(j_vec, wf):
                    if wv > 1e-6:
                        if not _num_finito(jv) or int(jv) < 0 or int(jv) >= num_joints:
                            joint_ruim = True
                        else:
                            ji = int(jv)
                            if ji not in root_slots:
                                peso_nao_raiz += wv
                            if wv > best_w:
                                best_w = wv
                                best_j = ji
                if best_j >= 0:
                    bname = slot_names.get(best_j, "")
                    if bname:
                        dom_counts[bname] = dom_counts.get(bname, 0) + 1
            if joint_ruim:
                joints_invalidos += 1
            if validos / float(total_v) < 0.99:
                pesos_invalidos += 1
            prim_raiz = num_joints > 1 and peso_nao_raiz <= 1e-6
            if prim_raiz:
                somente_raiz += 1
            elif num_joints > 1 and not joint_ruim and (validos / float(total_v)) >= 0.99:
                if not _prim_deforma_por_rotacao(
                    gltf,
                    binario,
                    atributos,
                    acessores,
                    skin_obj,
                    num_joints,
                    root_slots,
                    mundos,
                    juntas,
                    pesos,
                    escala_w,
                ):
                    sem_deformacao += 1

    ossos_vazios_set: set[str] = set()
    for slot_names, total_v_box, dom_counts in skin_dom_stats.values():
        n_v_skin = total_v_box[0]
        if n_v_skin < 100:
            continue
        for bname in slot_names.values():
            if bname not in _OSSOS_MEMBRO_CORE:
                continue
            cnt = dom_counts.get(bname, 0)
            if cnt == 0 or (n_v_skin >= 500 and cnt < 0.005 * n_v_skin):
                ossos_vazios_set.add(bname)
    ossos_membro_vazios = sorted(ossos_vazios_set)

    ok = (
        sem_atributos == 0
        and joints_invalidos == 0
        and pesos_invalidos == 0
        and somente_raiz == 0
        and sem_deformacao == 0
        and not ossos_membro_vazios
    )
    return {
        "ok": ok,
        "primitivas_skinned": prims_skinned,
        "sem_atributos": sem_atributos,
        "joints_invalidos": joints_invalidos,
        "pesos_invalidos": pesos_invalidos,
        "somente_raiz": somente_raiz,
        "sem_deformacao": sem_deformacao,
        "ossos_membro_vazios": ossos_membro_vazios,
    }
