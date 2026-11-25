"""Fronteiras espaciais anatomicas e metadados de ossos para skinning geodesico (camada L1)."""

from __future__ import annotations

import os
import sys

if __package__:
    from .autorig_const import (
        _OSSOS_BRACO_DISTAL, _OSSOS_CABECA, _OSSOS_CANELA, _OSSOS_COXA,
        _OSSOS_OMBROS, _OSSOS_PE, _OSSOS_PESCOCO, _lado_osso,
    )
else:
    _BLENDER_DIR = os.path.dirname(os.path.abspath(__file__))
    if _BLENDER_DIR not in sys.path:
        sys.path.insert(0, _BLENDER_DIR)
    from autorig_const import (
        _OSSOS_BRACO_DISTAL, _OSSOS_CABECA, _OSSOS_CANELA, _OSSOS_COXA,
        _OSSOS_OMBROS, _OSSOS_PE, _OSSOS_PESCOCO, _lado_osso,
    )


def _limites_anatomicos(m: dict, tem_neck: bool = True) -> dict[str, float]:
    """Pré-calcula fronteiras espaciais semânticas entre cabeça, pescoço, tórax, cintura, ombros e membros."""
    h = m["altura"]
    torso_hw = m.get("torso_hw", 0.12 * h)
    neck_hw = m.get("neck_hw", 0.038 * h)
    arm_z_cut = m["shoulder_z"] - 0.11 * h
    arm_z_cut_lo = arm_z_cut - 0.03 * h
    sh_x = 0.5 * (abs(m["shoulder_x_L"]) + abs(m["shoulder_x_R"]))
    arm_root_raw = max(torso_hw * 1.03, 0.075 * h)
    arm_root_x = min(arm_root_raw, sh_x * 0.96) if sh_x > 1e-6 else arm_root_raw
    arm_deltoid_x = max(arm_root_x + 0.032 * h, sh_x + 0.025 * h, 0.115 * h)
    ombro_min_raw = max(torso_hw * 0.82, 0.062 * h)
    ombro_min_x = min(ombro_min_raw, sh_x * 0.82) if sh_x > 1e-6 else ombro_min_raw
    ombro_max_x = max(abs(m["shoulder_x_L"]), abs(m["shoulder_x_R"]), arm_root_x) + 0.06 * h
    neck_max_x = min(max(neck_hw * 1.45, 0.052 * h), min(arm_root_x * 0.72, 0.095 * h))
    head_max_x = min(max(neck_max_x * 1.45, 0.14 * h), min(arm_root_x * 0.85, 0.115 * h))
    elbow_x = max(abs(float(m.get("elbow_x_L") or arm_deltoid_x)), abs(float(m.get("elbow_x_R") or arm_deltoid_x)), arm_deltoid_x)
    tronco_max_x_raw = max(abs(m["shoulder_x_L"]), abs(m["shoulder_x_R"]), arm_deltoid_x, 0.14 * h) * 1.12
    leg_x_min = min(abs(m["leg_x_L"]), abs(m["leg_x_R"]))
    leg_abs = max(abs(m["leg_x_L"]), abs(m["leg_x_R"]))
    x_tol_leg = min(0.015 * h, 0.25 * leg_x_min)
    perna_max_x = max(torso_hw * 1.02, leg_abs + 0.036 * h)
    el_xs = [abs(float(v)) for v in (m.get("elbow_x_L"), m.get("elbow_x_R")) if v is not None]
    min_elbow_x = min(el_xs) if el_xs else 0.0
    wr_xs = [abs(float(m[k]["wrist"][0])) for k in ("braco_L", "braco_R") if isinstance(m.get(k), dict) and "wrist" in m[k]]
    min_arm_low_x = min([min_elbow_x, *wr_xs]) if el_xs else 0.0
    arms_abducted = bool(el_xs and min_elbow_x > leg_abs + 0.06 * h)
    # Em A-pose parruda (cotovelo lateral ao ombro), trava tronco_max_x medial ao cotovelo sem encolher bosses estreitos.
    if arms_abducted and min_elbow_x > sh_x + 0.04 * h:
        tronco_max_x = min(tronco_max_x_raw, max(torso_hw * 1.05, 0.5 * (sh_x + min_elbow_x) + 0.02 * h))
    else:
        tronco_max_x = tronco_max_x_raw
    if arms_abducted:
        perna_max_x = min(perna_max_x, 0.5 * (leg_abs + min_elbow_x) + 0.02 * h)
    hips_max_x = perna_max_x + 0.03 * h
    if arms_abducted and min_arm_low_x > leg_abs + 0.06 * h:
        hips_max_x = max(hips_max_x, min(min_arm_low_x - 0.03 * h, 0.5 * (leg_abs + min_arm_low_x) + 0.04 * h))
    arm_pose_abduzida = bool(
        arms_abducted and el_xs and min_elbow_x > sh_x + 0.04 * h and min_arm_low_x > sh_x + 0.04 * h
    )
    if arm_pose_abduzida:
        perna_max_x = max(perna_max_x, hips_max_x - 0.02 * h)
    braco_baixo_min_x = max(torso_hw * 1.01, 0.04 * h)
    arm_z_hi = max(m["chest_top_z"] + 0.08 * h, m["shoulder_z"] + 0.12 * h)
    if not tem_neck:
        arm_z_hi = min(arm_z_hi, m["chest_top_z"] + 0.06 * h)
    arm_z_hi_medial = min(arm_z_hi, (m["neck_z"] + 0.02 * h) if tem_neck else (m["chest_top_z"] + 0.045 * h))
    el_zs = [float(m[k]["elbow"][2]) for k in ("braco_L", "braco_R") if isinstance(m.get(k), dict) and "elbow" in m[k]]
    min_elbow_z = min(el_zs) if el_zs else 0.0
    arm_hip_block_z = (
        min(m["hip_z"] + 0.06 * h, min_elbow_z - 0.08 * h)
        if (arm_pose_abduzida and el_zs and min_elbow_z > m["hip_z"] + 0.10 * h)
        else -1e9
    )
    tem_el_baixo = bool(el_zs and max(el_zs) < m["shoulder_z"] - 0.04 * h)
    arm_ext_z_soft = (max(el_zs) + 0.04 * h) if tem_el_baixo else arm_z_hi
    arm_ext_z_hi = (max(el_zs) + 0.14 * h) if tem_el_baixo else arm_z_hi
    return {
        "h": h, "x_tol": 0.03 * h, "x_tol_leg": x_tol_leg, "torso_hw": torso_hw,
        "arms_abducted": 1.0 if arms_abducted else 0.0,
        "neck_max_x": neck_max_x, "head_max_x": head_max_x,
        "ombro_min_x": ombro_min_x, "ombro_max_x": ombro_max_x, "ombro_z_hi": arm_z_hi,
        "arm_z_hi": arm_z_hi, "arm_z_hi_medial": arm_z_hi_medial,
        "arm_ext_z_soft": arm_ext_z_soft, "arm_ext_z_hi": arm_ext_z_hi,
        "arm_root_x": arm_root_x, "arm_deltoid_x": arm_deltoid_x,
        "arm_ext_z_max": m["shoulder_z"] - 0.02 * h, "arm_ext_x_min": 0.85 * elbow_x,
        "arm_z_cut": arm_z_cut, "arm_z_cut_lo": arm_z_cut_lo, "arm_z_min": m["z_min"] + 0.20 * h,
        "braco_baixo_min_x": braco_baixo_min_x, "arm_hip_block_z": arm_hip_block_z,
        "tronco_max_x": tronco_max_x, "perna_max_x": perna_max_x, "hips_max_x": hips_max_x,
        "head_z_min": (m["neck_z"] - 0.022 * h) if tem_neck else (m["chest_top_z"] - 0.008 * h),
        "neck_z_min": m["chest_top_z"] - 0.012 * h, "neck_z_max": m["neck_z"] + 0.045 * h,
        "chest_z_min": m["spine1_z"] - 0.015 * h, "upper_torso_z_min": m["hip_z"] - 0.01 * h,
        "chest_z_max": (m["neck_z"] + 0.02 * h) if tem_neck else (m["chest_top_z"] + 0.035 * h),
        "chest_z_max_collar": min(m["head_top_z"], max(m["chest_top_z"] + 0.08 * h, m["shoulder_z"] + 0.11 * h)),
        "spine1_z_min": m["hip_z"] - 0.01 * h, "spine1_z_max": m["chest_top_z"] - 0.02 * h,
        "spine_z_min": m["hip_z"] - 0.02 * h, "spine_z_max": m["chest_z"] + 0.02 * h,
        "hips_z_max": min(m["chest_z"] - 0.01 * h, m["spine1_z"] + 0.03 * h),
        "leg_z_max": m["hip_z"] + 0.04 * h, "upper_leg_z_min": m["knee_z"] - 0.05 * h,
        "lower_leg_z_max": m["knee_z"] + 0.35 * max(0.05 * h, m["hip_z"] - m["knee_z"]),
        "foot_z_max": m["knee_z"] - 0.03 * h, "z_min_floor": m["z_min"] - 0.01 * h,
    }


def _construir_meta(mapas: list[tuple[str, list[float]]]) -> list[tuple[str, list[float], int, int]]:
    """Classifica mapas de distancia geodesica por lado (-1/0/+1) e categoria anatomica (1..12)."""
    meta: list[tuple[str, list[float], int, int]] = []
    fixos = {"Chest": 8, "UpperTorso": 9, "Spine1": 10, "Spine": 11, "Hips": 12, "LowerTorso": 12}
    grupos = ((_OSSOS_COXA, 1), (_OSSOS_CANELA, 2), (_OSSOS_PE, 3), (_OSSOS_OMBROS, 4), (_OSSOS_BRACO_DISTAL, 5), (_OSSOS_CABECA, 6), (_OSSOS_PESCOCO, 7))
    for nome, dist_v in mapas:
        lado = _lado_osso(nome)
        lado_id = 1 if lado == "L" else (-1 if lado == "R" else 0)
        cat_id = fixos.get(nome, 0) or next((cid for grp, cid in grupos if nome in grp), 0)
        meta.append((nome, dist_v, lado_id, cat_id))
    return meta
