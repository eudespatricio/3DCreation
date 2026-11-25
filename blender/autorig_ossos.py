"""Construcao de ossos humanoides e alinhamento de roll (camada L1, F20a)."""

from __future__ import annotations

import math
import os
import sys

import bpy
from mathutils import Vector

if __package__:
    from .autorig_const import (
        _DEDOS_NOMES,
        _OSSOS_ASA,
        _OSSOS_BRACO,
        _OSSOS_BRACO_DISTAL,
        _OSSOS_CAUDA,
        _OSSOS_PATA,
        _OSSOS_PERNA,
        _selecionar_unico,
    )
else:
    _BLENDER_DIR = os.path.dirname(os.path.abspath(__file__))
    if _BLENDER_DIR not in sys.path:
        sys.path.insert(0, _BLENDER_DIR)
    from autorig_const import (
        _DEDOS_NOMES,
        _OSSOS_ASA,
        _OSSOS_BRACO,
        _OSSOS_BRACO_DISTAL,
        _OSSOS_CAUDA,
        _OSSOS_PATA,
        _OSSOS_PERNA,
        _selecionar_unico,
    )


def _osso(nome: str, pai: str | None, cabeca, cauda, min_len: float) -> dict:
    h = Vector(cabeca)
    t = Vector(cauda)
    if (t - h).length < min_len:
        t = h + Vector((0.0, 0.0, min_len))
    return {"nome": nome, "pai": pai, "cabeca": tuple(h), "cauda": tuple(t)}


def _quadro_mao(wrist: Vector, tip: Vector, h: float, sinal: float) -> tuple[Vector, Vector, Vector, float]:
    """Calcula base ortonormal anatomica da mao: (u_hand, u_thumb, u_palm, len_hand)."""
    vec = Vector(tip) - Vector(wrist)
    len_hand = max(vec.length, 0.052 * h)
    u_hand = vec.normalized() if vec.length > 1e-4 else Vector((sinal, 0.0, -0.25)).normalized()
    frente_y = Vector((0.0, 1.0, 0.0))
    u_thumb = frente_y - u_hand * frente_y.dot(u_hand)
    if u_thumb.length < 1e-4:
        u_thumb = Vector((0.0, 0.0, 1.0)).cross(u_hand)
    u_thumb.normalize()
    u_palm = (-sinal * u_hand.cross(u_thumb)).normalized()
    return u_hand, u_thumb, u_palm, len_hand


def _ossos_dedos_mao(
    lado: str,
    wrist: Vector,
    tip: Vector,
    h: float,
    ml: float,
) -> list[dict]:
    """Constroi os 15 ossos de falanges (Thumb..Little x 1..3) para uma mao."""
    sinal = 1.0 if lado == "L" else -1.0
    u_hand, u_thumb, u_palm, len_hand = _quadro_mao(wrist, tip, h, sinal)
    palm_w = max(0.020 * h, 0.44 * len_hand)
    knuckle_t = 0.48 * len_hand
    finger_len_base = max(0.52 * len_hand, 0.032 * h)
    min_f = max(0.004 * h, ml * 0.4)

    ossos: list[dict] = []
    thumb_dir = (0.64 * u_hand + 0.66 * u_thumb + 0.28 * u_palm).normalized()
    t0 = Vector(wrist) + u_hand * (0.18 * len_hand) + u_thumb * (0.44 * palm_w) + u_palm * (0.12 * palm_w)
    thumb_segs = (0.28 * finger_len_base, 0.24 * finger_len_base, 0.20 * finger_len_base)
    pai_t = f"Hand.{lado}"
    cur_t = t0
    for idx, seg_len in enumerate(thumb_segs, 1):
        nxt_t = cur_t + thumb_dir * max(seg_len, min_f)
        nome_t = f"Thumb{idx}.{lado}"
        ossos.append(_osso(nome_t, pai_t, cur_t, nxt_t, min_f))
        pai_t = nome_t
        cur_t = nxt_t

    specs_dedos = (
        ("Index", 0.30, 0.94),
        ("Middle", 0.08, 1.00),
        ("Ring", -0.14, 0.92),
        ("Little", -0.36, 0.76),
    )
    fracs = (0.42, 0.32, 0.26)
    for nome_dedo, lat_f, esc_len in specs_dedos:
        base_d = Vector(wrist) + u_hand * knuckle_t + u_thumb * (lat_f * palm_w)
        comp_d = finger_len_base * esc_len
        pai_d = f"Hand.{lado}"
        cur_d = base_d
        for idx, f_seg in enumerate(fracs, 1):
            nxt_d = cur_d + u_hand * max(comp_d * f_seg, min_f)
            nome_f = f"{nome_dedo}{idx}.{lado}"
            ossos.append(_osso(nome_f, pai_d, cur_d, nxt_d, min_f))
            pai_d = nome_f
            cur_d = nxt_d
    return ossos


def _construir_ossos(esqueleto: str, m: dict) -> list[dict]:
    z0 = m["z_min"]
    h = m["altura"]
    cy = m["cy"]
    ml = max(0.01 * h, 1e-3)
    bL = m["braco_L"]
    bR = m["braco_R"]

    if esqueleto == "godot-humanoid@1":
        return [
            _osso("Root", None, (0.0, 0.0, z0), (0.0, 0.0, z0 + 0.05 * h), ml),
            _osso("Hips", "Root", (0.0, cy, m["hip_z"]), (0.0, cy, m["spine_z"]), ml),
            _osso("Spine", "Hips", (0.0, cy, m["spine_z"]), (0.0, cy, m["spine1_z"]), ml),
            _osso("Spine1", "Spine", (0.0, cy, m["spine1_z"]), (0.0, cy, m["chest_z"]), ml),
            _osso("Chest", "Spine1", (0.0, cy, m["chest_z"]), (0.0, cy, m["chest_top_z"]), ml),
            _osso("Neck", "Chest", (0.0, cy, m["chest_top_z"]), (0.0, cy, m["neck_z"]), ml),
            _osso("Head", "Neck", (0.0, cy, m["neck_z"]), (0.0, cy, m["head_top_z"]), ml),
            _osso("Shoulder.L", "Chest", (bL["clav_x"], cy, bL["shoulder"].z), bL["shoulder"], ml),
            _osso("UpperArm.L", "Shoulder.L", bL["shoulder"], bL["elbow"], ml),
            _osso("LowerArm.L", "UpperArm.L", bL["elbow"], bL["wrist"], ml),
            _osso("Hand.L", "LowerArm.L", bL["wrist"], bL["tip"], ml),
            _osso("Shoulder.R", "Chest", (bR["clav_x"], cy, bR["shoulder"].z), bR["shoulder"], ml),
            _osso("UpperArm.R", "Shoulder.R", bR["shoulder"], bR["elbow"], ml),
            _osso("LowerArm.R", "UpperArm.R", bR["elbow"], bR["wrist"], ml),
            _osso("Hand.R", "LowerArm.R", bR["wrist"], bR["tip"], ml),
            _osso("UpperLeg.L", "Hips", (m["leg_x_L"], cy, max(m["leg_top_z"] + 0.02 * h, m["hip_z"] - 0.015 * h)), (m["leg_x_L"], cy, m["knee_z"]), ml),
            _osso("LowerLeg.L", "UpperLeg.L", (m["leg_x_L"], cy, m["knee_z"]), (m["leg_x_L"], cy, m["ankle_z"]), ml),
            _osso("Foot.L", "LowerLeg.L", (m["leg_x_L"], cy, m["ankle_z"]), (m["leg_x_L"], cy + m["foot_y"], z0 + 0.02 * h), ml),
            _osso("Toe.L", "Foot.L", (m["leg_x_L"], cy + m["foot_y"], z0 + 0.02 * h), (m["leg_x_L"], cy + m["toe_y"], z0 + 0.012 * h), ml),
            _osso("UpperLeg.R", "Hips", (m["leg_x_R"], cy, max(m["leg_top_z"] + 0.02 * h, m["hip_z"] - 0.015 * h)), (m["leg_x_R"], cy, m["knee_z"]), ml),
            _osso("LowerLeg.R", "UpperLeg.R", (m["leg_x_R"], cy, m["knee_z"]), (m["leg_x_R"], cy, m["ankle_z"]), ml),
            _osso("Foot.R", "LowerLeg.R", (m["leg_x_R"], cy, m["ankle_z"]), (m["leg_x_R"], cy + m["foot_y"], z0 + 0.02 * h), ml),
            _osso("Toe.R", "Foot.R", (m["leg_x_R"], cy + m["foot_y"], z0 + 0.02 * h), (m["leg_x_R"], cy + m["toe_y"], z0 + 0.012 * h), ml),
        ]
    if esqueleto == "godot-humanoid-aa@1":
        head_h = max(m["head_top_z"] - m["neck_z"], 0.10 * h)
        torso_hw = float(m.get("torso_hw", 0.10 * h))
        cape_y_fb = cy - max(0.055 * h, 0.55 * torso_hw)
        has_back_y = m.get("torso_back_y") is not None
        cape_y_raw = float(m["torso_back_y"]) if has_back_y else cape_y_fb
        cape_y = max(cy - 0.16 * h, min(cy - 0.04 * h, cape_y_raw))
        cape_tail_y = max(cape_y_raw, cape_y - 0.015 * h) if has_back_y else (cape_y - 0.03 * h)
        u_h_l, _, _, len_h_l = _quadro_mao(bL["wrist"], bL["tip"], h, 1.0)
        u_h_r, _, _, len_h_r = _quadro_mao(bR["wrist"], bR["tip"], h, -1.0)
        hand_tail_l = Vector(bL["wrist"]) + u_h_l * (0.50 * len_h_l)
        hand_tail_r = Vector(bR["wrist"]) + u_h_r * (0.50 * len_h_r)
        ossos_aa = [
            _osso("Root", None, (0.0, 0.0, z0), (0.0, 0.0, z0 + 0.05 * h), ml),
            _osso("Hips", "Root", (0.0, cy, m["hip_z"]), (0.0, cy, m["spine_z"]), ml),
            _osso("Spine", "Hips", (0.0, cy, m["spine_z"]), (0.0, cy, m["chest_z"]), ml),
            _osso("Chest", "Spine", (0.0, cy, m["chest_z"]), (0.0, cy, m["chest_top_z"]), ml),
            _osso("Neck", "Chest", (0.0, cy, m["chest_top_z"]), (0.0, cy, m["neck_z"]), ml),
            _osso("Head", "Neck", (0.0, cy, m["neck_z"]), (0.0, cy, m["head_top_z"]), ml),
            _osso("Jaw", "Head", (0.0, cy + 0.022 * h, m["neck_z"] + 0.18 * head_h), (0.0, cy + 0.070 * h, m["neck_z"] + 0.06 * head_h), ml),
            _osso("Eye.L", "Head", (0.020 * h, cy + 0.052 * h, m["neck_z"] + 0.56 * head_h), (0.020 * h, cy + 0.082 * h, m["neck_z"] + 0.56 * head_h), ml),
            _osso("Eye.R", "Head", (-0.020 * h, cy + 0.052 * h, m["neck_z"] + 0.56 * head_h), (-0.020 * h, cy + 0.082 * h, m["neck_z"] + 0.56 * head_h), ml),
            _osso("Cape", "Chest", (0.0, cape_y, m["chest_top_z"] - 0.02 * h), (0.0, cape_tail_y, m["hip_z"] - 0.04 * h), ml),
            _osso("Shoulder.L", "Chest", (bL["clav_x"], cy, bL["shoulder"].z), bL["shoulder"], ml),
            _osso("UpperArm.L", "Shoulder.L", bL["shoulder"], bL["elbow"], ml),
            _osso("LowerArm.L", "UpperArm.L", bL["elbow"], bL["wrist"], ml),
            _osso("Hand.L", "LowerArm.L", bL["wrist"], hand_tail_l, ml),
            _osso("Shoulder.R", "Chest", (bR["clav_x"], cy, bR["shoulder"].z), bR["shoulder"], ml),
            _osso("UpperArm.R", "Shoulder.R", bR["shoulder"], bR["elbow"], ml),
            _osso("LowerArm.R", "UpperArm.R", bR["elbow"], bR["wrist"], ml),
            _osso("Hand.R", "LowerArm.R", bR["wrist"], hand_tail_r, ml),
        ]
        ossos_aa.extend(_ossos_dedos_mao("L", bL["wrist"], bL["tip"], h, ml))
        ossos_aa.extend(_ossos_dedos_mao("R", bR["wrist"], bR["tip"], h, ml))
        ossos_aa.extend([
            _osso("UpperLeg.L", "Hips", (m["leg_x_L"], cy, max(m["leg_top_z"] + 0.02 * h, m["hip_z"] - 0.015 * h)), (m["leg_x_L"], cy, m["knee_z"]), ml),
            _osso("LowerLeg.L", "UpperLeg.L", (m["leg_x_L"], cy, m["knee_z"]), (m["leg_x_L"], cy, m["ankle_z"]), ml),
            _osso("Foot.L", "LowerLeg.L", (m["leg_x_L"], cy, m["ankle_z"]), (m["leg_x_L"], cy + m["foot_y"], z0 + 0.02 * h), ml),
            _osso("Toe.L", "Foot.L", (m["leg_x_L"], cy + m["foot_y"], z0 + 0.02 * h), (m["leg_x_L"], cy + m["toe_y"], z0 + 0.012 * h), ml),
            _osso("UpperLeg.R", "Hips", (m["leg_x_R"], cy, max(m["leg_top_z"] + 0.02 * h, m["hip_z"] - 0.015 * h)), (m["leg_x_R"], cy, m["knee_z"]), ml),
            _osso("LowerLeg.R", "UpperLeg.R", (m["leg_x_R"], cy, m["knee_z"]), (m["leg_x_R"], cy, m["ankle_z"]), ml),
            _osso("Foot.R", "LowerLeg.R", (m["leg_x_R"], cy, m["ankle_z"]), (m["leg_x_R"], cy + m["foot_y"], z0 + 0.02 * h), ml),
            _osso("Toe.R", "Foot.R", (m["leg_x_R"], cy + m["foot_y"], z0 + 0.02 * h), (m["leg_x_R"], cy + m["toe_y"], z0 + 0.012 * h), ml),
        ])
        return ossos_aa
    if esqueleto == "r15@1":
        hip_leg_z = max(m["leg_top_z"] + 0.02 * h, m["hip_z"] - 0.015 * h)
        # r15@1 nao possui osso Shoulder clavicular: ancora cabeca na junta do ombro para nao girar de dentro do torax.
        sh_l_x = math.copysign(
            max(abs(float(bL["clav_x"])), 0.92 * abs(float(bL["shoulder"].x))),
            float(bL["clav_x"]) or 1.0,
        )
        sh_r_x = math.copysign(
            max(abs(float(bR["clav_x"])), 0.92 * abs(float(bR["shoulder"].x))),
            float(bR["clav_x"]) or -1.0,
        )
        return [
            _osso("HumanoidRootPart", None, (0.0, 0.0, z0), (0.0, 0.0, z0 + 0.05 * h), ml),
            _osso("LowerTorso", "HumanoidRootPart", (0.0, cy, m["leg_top_z"]), (0.0, cy, m["spine_z"]), ml),
            _osso("UpperTorso", "LowerTorso", (0.0, cy, m["spine_z"]), (0.0, cy, m["chest_top_z"]), ml),
            _osso("Head", "UpperTorso", (0.0, cy, m["chest_top_z"]), (0.0, cy, m["head_top_z"]), ml),
            _osso("LeftUpperArm", "UpperTorso", (sh_l_x, cy, bL["shoulder"].z), bL["elbow"], ml),
            _osso("LeftLowerArm", "LeftUpperArm", bL["elbow"], bL["wrist"], ml),
            _osso("LeftHand", "LeftLowerArm", bL["wrist"], bL["tip"], ml),
            _osso("RightUpperArm", "UpperTorso", (sh_r_x, cy, bR["shoulder"].z), bR["elbow"], ml),
            _osso("RightLowerArm", "RightUpperArm", bR["elbow"], bR["wrist"], ml),
            _osso("RightHand", "RightLowerArm", bR["wrist"], bR["tip"], ml),
            _osso("LeftUpperLeg", "LowerTorso", (m["leg_x_L"], cy, hip_leg_z), (m["leg_x_L"], cy, m["knee_z"]), ml),
            _osso("LeftLowerLeg", "LeftUpperLeg", (m["leg_x_L"], cy, m["knee_z"]), (m["leg_x_L"], cy, m["ankle_z"]), ml),
            _osso("LeftFoot", "LeftLowerLeg", (m["leg_x_L"], cy, m["ankle_z"]), (m["leg_x_L"], cy + m["foot_y"], z0 + 0.02 * h), ml),
            _osso("RightUpperLeg", "LowerTorso", (m["leg_x_R"], cy, hip_leg_z), (m["leg_x_R"], cy, m["knee_z"]), ml),
            _osso("RightLowerLeg", "RightUpperLeg", (m["leg_x_R"], cy, m["knee_z"]), (m["leg_x_R"], cy, m["ankle_z"]), ml),
            _osso("RightFoot", "RightLowerLeg", (m["leg_x_R"], cy, m["ankle_z"]), (m["leg_x_R"], cy + m["foot_y"], z0 + 0.02 * h), ml),
        ]
    raise ValueError(f"esqueleto nao suportado pelo auto-rig: {esqueleto}")


_definicoes_ossos = _construir_ossos


def _alinhar_roll_ossos(rig_obj) -> None:
    """Alinha o eixo local dos membros pelo plano de flexao (cotovelo/asa) com simetria L/R."""
    _selecionar_unico(rig_obj)
    bpy.ops.object.mode_set(mode="EDIT")
    frente = Vector((0.0, 1.0, 0.0))
    cima = Vector((0.0, 0.0, 1.0))
    edit_bones = rig_obj.data.edit_bones
    alvos_braco: dict[str, Vector] = {}
    planos_lado: dict[str, Vector] = {}
    pares_flexao = (
        ("UpperArm.L", "LowerArm.L", "UpperArm.R", "LowerArm.R"),
        ("LeftUpperArm", "LeftLowerArm", "RightUpperArm", "RightLowerArm"),
        ("WingArm.L", "WingForearm.L", "WingArm.R", "WingForearm.R"),
    )
    for par_l0, par_l1, par_r0, par_r1 in pares_flexao:
        for sup_n, inf_n in ((par_l0, par_l1), (par_r0, par_r1)):
            sup, inf = edit_bones.get(sup_n), edit_bones.get(inf_n)
            if sup is None or inf is None:
                continue
            plano_n = sup.y_axis.cross(inf.y_axis)
            if plano_n.length > 0.08:
                n = plano_n.normalized()
                if sup_n.startswith("Wing"):
                    n_canon = None
                    if sup_n == par_r0 and par_l0 in planos_lado:
                        n_ref = planos_lado[par_l0]
                        n_esp = Vector((n_ref.x, -n_ref.y, -n_ref.z))
                        if abs(n.dot(n_esp)) > 0.5:
                            n_canon = n if n.dot(n_esp) >= 0.0 else -n
                    if n_canon is None:
                        alvo_ref = n.cross(sup.y_axis)
                        if abs(alvo_ref.y) > 0.25:
                            n_canon = n if alvo_ref.y > 0.0 else -n
                        else:
                            sgn_x = 1.0 if sup_n.endswith(".L") else -1.0
                            n_canon = n if (n.y * sgn_x) >= 0.0 else -n
                    planos_lado[sup_n] = n_canon
                    for eb_arm in (sup, inf):
                        alvo = n_canon.cross(eb_arm.y_axis)
                        if alvo.length > 1e-4:
                            alvos_braco[eb_arm.name] = alvo.normalized()
                elif abs(n.x) >= 0.82 and abs(n.y) <= 0.30:
                    # Canoniza sinal lateral (+X) para simetria L/R e sem torcao de 180 deg
                    n_canon = n if n.x > 0.0 else -n
                    planos_lado[sup_n] = n_canon
                    for eb_arm in (sup, inf):
                        alvo = n_canon.cross(eb_arm.y_axis)
                        if alvo.length > 1e-4:
                            alvos_braco[eb_arm.name] = alvo.normalized()
        for sup_n, inf_n, op_sup_n in (
            (par_l0, par_l1, par_r0),
            (par_r0, par_r1, par_l0),
        ):
            if sup_n not in planos_lado and op_sup_n in planos_lado:
                n_ref = planos_lado[op_sup_n]
                n_esp = Vector((n_ref.x, -n_ref.y, -n_ref.z))
                sup_op, inf_op = edit_bones.get(sup_n), edit_bones.get(inf_n)
                for eb_arm in (sup_op, inf_op):
                    if eb_arm is None:
                        continue
                    alvo = n_esp.cross(eb_arm.y_axis)
                    if alvo.length > 1e-4:
                        alvos_braco[eb_arm.name] = alvo.normalized()

    ossos_eixo_criatura = _OSSOS_ASA | _OSSOS_PATA | _OSSOS_CAUDA
    e_rig_criatura = any(eb.name in ossos_eixo_criatura or eb.name == "MountSeat" for eb in edit_bones)
    alvos_aa: dict[str, Vector] = {}
    for lado, sinal in (("L", 1.0), ("R", -1.0)):
        hand_eb = edit_bones.get(f"Hand.{lado}")
        if hand_eb is not None:
            u_h = hand_eb.y_axis.normalized()
            frente_y = Vector((0.0, 1.0, 0.0))
            u_t = frente_y - u_h * frente_y.dot(u_h)
            if u_t.length < 1e-4:
                u_t = Vector((0.0, 0.0, 1.0)).cross(u_h)
            u_t.normalize()
            u_p = (-sinal * u_h.cross(u_t)).normalized()
            u_p_thumb = (0.55 * u_p - 0.80 * u_t).normalized()
            for dedo in _DEDOS_NOMES:
                alvo_d = u_p_thumb if dedo == "Thumb" else u_p
                for idx in (1, 2, 3):
                    alvos_aa[f"{dedo}{idx}.{lado}"] = alvo_d

    for eb in edit_bones:
        if eb.name in alvos_braco:
            eb.align_roll(alvos_braco[eb.name])
        elif eb.name in alvos_aa:
            eb.align_roll(alvos_aa[eb.name])
        elif eb.name in ("Eye.L", "Eye.R", "Jaw"):
            eb.align_roll(cima)
        elif eb.name == "Cape":
            eb.align_roll(Vector((0.0, -1.0, 0.0)))
        elif eb.name in _OSSOS_BRACO_DISTAL:
            alvo = Vector((1.0, 0.0, 0.0)).cross(eb.y_axis)
            eb.align_roll(alvo.normalized() if alvo.length > 1e-4 else frente)
        elif eb.name in _OSSOS_BRACO or eb.name in _OSSOS_PERNA or eb.name in ossos_eixo_criatura:
            alvo = cima if abs(eb.y_axis.y) > 0.85 else frente
            eb.align_roll(alvo)
        elif e_rig_criatura and eb.name in ("Spine", "Chest", "Neck", "Head", "Jaw"):
            alvo = cima if abs(eb.y_axis.y) > 0.65 else Vector((0.0, -1.0, 0.0))
            eb.align_roll(alvo)
    bpy.ops.object.mode_set(mode="OBJECT")
    rig_obj.select_set(False)
