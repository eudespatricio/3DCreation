"""Ajuste natural de pose (caimento gravitacional de bracos e ground clamp FK) para Blender 4.2."""

from __future__ import annotations

import math

import bpy
from mathutils import Vector

_CLIPES_NO_CHAO = frozenset(
    {
        "idle",
        "walk",
        "run",
        "attack",
        "slash_combo",
        "cast",
        "block",
        "hit",
        "death",
    }
)
_OSSOS_PE_CLAMP = ("Foot.L", "Foot.R", "Toe.L", "Toe.R", "LeftFoot", "RightFoot")


def _resolver_bracos_e_pernas(
    bones,
) -> tuple[
    object | None,
    object | None,
    object | None,
    object | None,
    object | None,
    object | None,
    object | None,
]:
    if "UpperArm.L" in bones and "UpperArm.R" in bones:
        arm_l, arm_r = bones["UpperArm.L"], bones["UpperArm.R"]
        low_l, low_r = bones.get("LowerArm.L"), bones.get("LowerArm.R")
    elif "LeftUpperArm" in bones and "RightUpperArm" in bones:
        arm_l, arm_r = bones["LeftUpperArm"], bones["RightUpperArm"]
        low_l, low_r = bones.get("LeftLowerArm"), bones.get("RightLowerArm")
    else:
        arm_l, arm_r, low_l, low_r = None, None, None, None
    hips = bones.get("Hips") or bones.get("LowerTorso")
    leg_l = bones.get("UpperLeg.L") or bones.get("LeftUpperLeg")
    leg_r = bones.get("UpperLeg.R") or bones.get("RightUpperLeg")
    return arm_l, arm_r, low_l, low_r, hips, leg_l, leg_r


def calcular_caimento_braco_rig(rig_obj) -> dict:
    """Calcula aducao gravitacional segura para bracos em A-pose/T-pose sem afetar rigs verticais/sinteticos."""
    if rig_obj is None or getattr(rig_obj, "type", None) != "ARMATURE":
        return {
            "aplicavel": False,
            "theta_rest_graus": 0.0,
            "delta_total_graus": 0.0,
            "ombro_graus": 0.0,
            "braco_graus": 0.0,
            "tem_ombro": False,
        }
    bones = rig_obj.data.bones
    tem_ombro = "Shoulder.L" in bones and "Shoulder.R" in bones
    arm_l, arm_r, low_l, low_r, hips, leg_l, leg_r = _resolver_bracos_e_pernas(bones)

    theta_arm_total = 0.0
    theta_lower = 0.0
    tem_lower = False
    if arm_l is not None and arm_r is not None:
        thetas: list[float] = []
        thetas_low: list[float] = []
        for upper, lower in ((arm_l, low_l), (arm_r, low_r)):
            p_fim = lower.tail_local if lower is not None else upper.tail_local
            vec = p_fim - upper.head_local
            dx = abs(float(vec.x))
            dz = float(-vec.z)
            if dx > 1e-6 or abs(dz) > 1e-6:
                thetas.append(math.degrees(math.atan2(dx, dz)))
            if lower is not None:
                v_low = lower.tail_local - lower.head_local
                dx_l = abs(float(v_low.x))
                dz_l = float(-v_low.z)
                if dx_l > 1e-6 or abs(dz_l) > 1e-6:
                    thetas_low.append(math.degrees(math.atan2(dx_l, dz_l)))
        theta_arm_total = sum(thetas) / len(thetas) if thetas else 0.0
        tem_lower = bool(thetas_low)
        theta_lower = sum(thetas_low) / len(thetas_low) if thetas_low else 0.0

    eh_humanoide = arm_l is not None and arm_r is not None and hips is not None and leg_l is not None
    braco_vertical = (theta_arm_total <= 22.0) or (
        tem_lower and theta_lower <= 14.0 and theta_arm_total <= 28.0
    )
    if not eh_humanoide or braco_vertical:
        return {
            "aplicavel": False,
            "theta_rest_graus": round(theta_arm_total, 4),
            "delta_total_graus": 0.0,
            "ombro_graus": 0.0,
            "braco_graus": 0.0,
            "tem_ombro": tem_ombro,
        }

    sh_half = 0.5 * (abs(float(arm_l.head_local.x)) + abs(float(arm_r.head_local.x)))
    hip_xs = [abs(float(b.head_local.x)) for b in (leg_l, leg_r) if b is not None]
    hip_half = sum(hip_xs) / len(hip_xs)
    hip_ratio = hip_half / max(sh_half, 1e-4)
    t_prop = max(0.0, min(1.0, (hip_ratio - 0.45) / 0.35))
    theta_target = 13.0 + 4.0 * t_prop

    delta_total = max(0.0, min(26.0, theta_arm_total - theta_target))
    if delta_total <= 1e-4:
        return {
            "aplicavel": False,
            "theta_rest_graus": round(theta_arm_total, 4),
            "delta_total_graus": 0.0,
            "ombro_graus": 0.0,
            "braco_graus": 0.0,
            "tem_ombro": tem_ombro,
        }

    if tem_ombro:
        ombro_graus = 0.30 * delta_total
        braco_graus = 0.70 * delta_total
    else:
        ombro_graus = 0.0
        braco_graus = min(25.0, delta_total)

    return {
        "aplicavel": True,
        "theta_rest_graus": round(theta_arm_total, 4),
        "delta_total_graus": round(delta_total, 4),
        "ombro_graus": round(ombro_graus, 4),
        "braco_graus": round(braco_graus, 4),
        "tem_ombro": tem_ombro,
    }


def peso_gravidade_clipe(nome_clipe: str, fracao: float) -> float:
    """Peso temporal [0..1] do caimento gravitacional conforme dinamica do clipe."""
    f = max(0.0, min(1.0, float(fracao)))
    nome = str(nome_clipe or "").strip().lower()
    if nome in ("idle", "walk", "run", "hit"):
        return 1.0
    if nome == "death":
        return 0.8
    if nome in ("ride_idle", "ride_fly"):
        return 0.4
    if nome == "jump":
        return 0.2 + 0.8 * (math.cos(math.pi * f) ** 2)
    if nome in ("attack", "slash_combo", "block", "cast"):
        return 1.0 - 0.35 * math.sin(math.pi * f)
    return 1.0


def altura_rig_e_chao(rig_obj) -> tuple[bool, float, float]:
    """Retorna (eh_humanoide_completo, altura_rig_m, z_chao_rest_world)."""
    if rig_obj is None or getattr(rig_obj, "type", None) != "ARMATURE":
        return False, 1.75, 0.0
    bones = rig_obj.data.bones
    arm_l, arm_r, _low_l, _low_r, hips, leg_l, _leg_r = _resolver_bracos_e_pernas(bones)
    eh_humanoide = arm_l is not None and arm_r is not None and hips is not None and leg_l is not None

    m_world = rig_obj.matrix_world
    zs_all = [
        float((m_world @ pt).z)
        for b in bones
        for pt in (b.head_local, b.tail_local)
    ]
    altura = (max(zs_all) - min(zs_all)) if zs_all else 1.75

    zs_pe: list[float] = []
    for nome_pe in _OSSOS_PE_CLAMP:
        bone = bones.get(nome_pe)
        if bone is not None:
            zs_pe.append(float((m_world @ bone.head_local).z))
            zs_pe.append(float((m_world @ bone.tail_local).z))
    z_chao = min(zs_pe) if zs_pe else (min(zs_all) if zs_all else 0.0)
    return eh_humanoide, altura, z_chao


def aplicar_ground_clamp_fk(
    rig_obj,
    nome_clipe: str,
    z_chao: float,
    *,
    frame: int | None = None,
    tol: float = 1e-4,
) -> float:
    """Impede que pes/dedos afundem abaixo de ``z_chao`` em clipes apoiados no solo."""
    nome = str(nome_clipe or "").strip().lower()
    if nome not in _CLIPES_NO_CHAO:
        return 0.0
    if rig_obj is None or getattr(rig_obj, "type", None) != "ARMATURE":
        return 0.0

    bpy.context.view_layer.update()
    zs_pe: list[float] = []
    rig_mw = rig_obj.matrix_world
    for nome_pe in _OSSOS_PE_CLAMP:
        pb = rig_obj.pose.bones.get(nome_pe)
        if pb is None:
            continue
        m_pose_w = rig_mw @ pb.matrix
        zs_pe.append(float(m_pose_w.translation.z))
        zs_pe.append(float((m_pose_w @ Vector((0.0, pb.bone.length, 0.0))).z))

    if not zs_pe:
        return 0.0
    min_z = min(zs_pe)
    if min_z >= float(z_chao) - tol:
        return 0.0

    shift = float(z_chao) - min_z
    pb_root = rig_obj.pose.bones.get("Hips") or rig_obj.pose.bones.get("LowerTorso")
    if pb_root is None:
        return 0.0

    shift_arm = rig_mw.to_3x3().inverted_safe() @ Vector((0.0, 0.0, shift))
    delta_local = pb_root.bone.matrix_local.to_3x3().inverted_safe() @ shift_arm
    pb_root.location = pb_root.location + delta_local
    frame_eff = int(bpy.context.scene.frame_current if frame is None else frame)
    pb_root.keyframe_insert("location", frame=frame_eff)
    return float(shift)
