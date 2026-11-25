"""Ajuste natural de pose (caimento gravitacional, bake de rest pose e ground clamp FK) para Blender 4.2."""

from __future__ import annotations

from array import array
import math
import os
import random
import sys

import bpy
from mathutils import Quaternion, Vector

if __package__:
    from .autorig_const import _OSSOS_ASA, _OSSOS_PATA
else:
    _BLENDER_DIR = os.path.dirname(os.path.abspath(__file__))
    if _BLENDER_DIR not in sys.path:
        sys.path.insert(0, _BLENDER_DIR)
    from autorig_const import _OSSOS_ASA, _OSSOS_PATA

PRESETS_POSTURA: tuple[str, ...] = (
    "neutro_relaxado",
    "guarda_atento",
    "descontraido",
    "confiante",
    "explorador",
)
_BASE_PRESETS_POSTURA: dict[str, tuple[float, float, float, float]] = {
    "neutro_relaxado": (0.0, 0.0, 0.0, 0.0),
    "guarda_atento": (0.8, 1.2, 6.5, 8.0),
    "descontraido": (-0.6, 0.4, 3.0, 4.5),
    "confiante": (1.5, 1.5, 4.0, 4.0),
    "explorador": (1.0, -0.4, 5.5, 3.0),
}

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


def calcular_aducao_perna_rig(rig_obj) -> dict:
    """Calcula aducao extra (graus) de UpperLeg.L/R proporcional a ``hip_dx / altura`` no rig Blender."""
    vazio = {
        "aplicavel": False,
        "extra_graus": 0.0,
        "hip_dx": 0.0,
        "foot_dx": 0.0,
        "hip_ratio": 0.0,
    }
    if rig_obj is None or getattr(rig_obj, "type", None) != "ARMATURE":
        return vazio
    bones = rig_obj.data.bones
    if any(b.name in _OSSOS_ASA or b.name in _OSSOS_PATA or b.name == "MountSeat" for b in bones):
        return vazio

    leg_l = bones.get("UpperLeg.L") or bones.get("LeftUpperLeg")
    leg_r = bones.get("UpperLeg.R") or bones.get("RightUpperLeg")
    foot_l = bones.get("Foot.L") or bones.get("LeftFoot")
    foot_r = bones.get("Foot.R") or bones.get("RightFoot")
    if leg_l is None or leg_r is None or foot_l is None or foot_r is None:
        return vazio

    hip_dx = abs(float(leg_l.head_local.x) - float(leg_r.head_local.x))
    foot_dx = abs(float(foot_l.head_local.x) - float(foot_r.head_local.x))
    leg_len = 0.5 * (
        max(float(leg_l.head_local.z - foot_l.head_local.z), 1e-4)
        + max(float(leg_r.head_local.z - foot_r.head_local.z), 1e-4)
    )
    z_foot = 0.5 * (float(foot_l.head_local.z) + float(foot_r.head_local.z))

    head = bones.get("Head")
    if head is not None:
        h_est = max((float(head.head_local.z) - z_foot) / 0.79, 1e-4)
    elif (neck := bones.get("Neck")) is not None:
        h_est = max((float(neck.head_local.z) - z_foot) / 0.72, 1e-4)
    else:
        h_est = max(altura_rig_e_chao(rig_obj)[1], 1e-4)

    hip_ratio = hip_dx / h_est
    foot_ratio = foot_dx / h_est
    if hip_ratio <= 0.15 and foot_ratio <= 0.16:
        extra_graus = 0.0
    else:
        alvo_ratio = max(0.090, min(0.145, 0.090 + 0.35 * max(0.0, hip_ratio - 0.20)))
        foot_dx_alvo = alvo_ratio * h_est
        if foot_dx <= foot_dx_alvo + 1e-4:
            extra_graus = 0.0
        else:
            sin_tot = max(0.0, min(0.85, (foot_dx - foot_dx_alvo) / max(2.0 * leg_len, 1e-4)))
            theta_tot = math.degrees(math.asin(sin_tot))
            extra_graus = round(max(0.0, min(10.0, theta_tot - 4.5)), 4)

    return {
        "aplicavel": extra_graus > 1e-4,
        "extra_graus": extra_graus,
        "hip_dx": round(hip_dx, 5),
        "foot_dx": round(foot_dx, 5),
        "altura_est": round(h_est, 5),
        "hip_ratio": round(hip_ratio, 4),
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


def resolver_postura_perfil(perfil: dict | None, item: dict | None = None) -> dict:
    """Resolve configuracao de postura rest-pose a partir do perfil e preset opcional do item."""
    rig_cfg = (perfil or {}).get("rig") if isinstance(perfil, dict) else None
    postura = rig_cfg.get("postura") if isinstance(rig_cfg, dict) else None
    p = postura if isinstance(postura, dict) else {}
    raw_modo = p.get("modo_rest")
    modo = str(raw_modo).strip() if isinstance(raw_modo, str) and raw_modo.strip() else "apose"
    ang_default = 14.0 if modo == "natural_relaxada" else 45.0
    raw_ang = p.get("angulo_braco_graus")
    ang = float(ang_default if raw_ang is None else raw_ang)
    fix_sil = True if p.get("fix_silhouette") is None else bool(p.get("fix_silhouette"))
    var_seed = True if p.get("variacao_seed") is None else bool(p.get("variacao_seed"))
    raw_preset = item.get("postura_preset") if isinstance(item, dict) else None
    preset = str(raw_preset).strip() if isinstance(raw_preset, str) and raw_preset.strip() else None
    return {
        "modo_rest": modo,
        "angulo_braco_graus": ang,
        "fix_silhouette": fix_sil,
        "variacao_seed": var_seed,
        "preset": preset,
    }


def microvariacao_postura_seed(
    seed: int | None = None, postura_preset: str | None = None
) -> dict:
    """Devolve offsets deterministicos de rest-pose para os 5 presets de postura."""
    if seed is None and postura_preset is None:
        return {
            "preset": "neutro_relaxado",
            "delta_braco_e_graus": 0.0,
            "delta_braco_d_graus": 0.0,
            "cotovelo_flex_e_graus": 0.0,
            "cotovelo_flex_d_graus": 0.0,
        }
    rng = random.Random(int(seed)) if seed is not None else None
    raw_p = str(postura_preset).strip() if isinstance(postura_preset, str) and postura_preset.strip() else None
    if raw_p in _BASE_PRESETS_POSTURA:
        preset = raw_p
    elif rng is not None:
        preset = rng.choice(PRESETS_POSTURA)
    else:
        preset = "neutro_relaxado"
    de, dd, fe, fd = _BASE_PRESETS_POSTURA[preset]
    if rng is not None:
        de += rng.uniform(-1.2, 1.2)
        dd += rng.uniform(-1.2, 1.2)
        fe = max(0.0, min(10.0, fe + rng.uniform(0.5, 2.5)))
        fd = max(0.0, min(10.0, fd + rng.uniform(0.5, 2.5)))
    return {
        "preset": preset,
        "delta_braco_e_graus": round(de, 4),
        "delta_braco_d_graus": round(dd, 4),
        "cotovelo_flex_e_graus": round(max(0.0, min(10.0, fe)), 4),
        "cotovelo_flex_d_graus": round(max(0.0, min(10.0, fd)), 4),
    }


def _medir_thetas_bracos(bones) -> tuple[float, float, float, float, float]:
    """Retorna (theta_medio, upper_l, upper_r, wrist_l, wrist_r) em graus no plano XZ."""
    arm_l, arm_r, low_l, low_r, _h, _ll, _lr = _resolver_bracos_e_pernas(bones)
    thetas: list[float] = []
    up_lados, wr_lados = [0.0, 0.0], [0.0, 0.0]
    for idx, (upper, lower) in enumerate(((arm_l, low_l), (arm_r, low_r))):
        if upper is None:
            continue
        p_mid = lower.head_local if lower is not None else upper.tail_local
        p_fim = lower.tail_local if lower is not None else upper.tail_local
        for dst, arr in ((p_mid, up_lados), (p_fim, wr_lados)):
            vec = dst - upper.head_local
            dx, dz = abs(float(vec.x)), float(-vec.z)
            if dx > 1e-6 or abs(dz) > 1e-6:
                arr[idx] = math.degrees(math.atan2(dx, dz))
        if up_lados[idx] > 0.0 or wr_lados[idx] > 0.0:
            thetas.append(max(up_lados[idx], wr_lados[idx]))
    media = sum(thetas) / len(thetas) if thetas else 0.0
    return media, up_lados[0], up_lados[1], wr_lados[0], wr_lados[1]


def assar_pose_rest_natural(
    obj,
    rig_obj,
    *,
    angulo_alvo_graus: float = 14.0,
    seed: int | None = None,
    postura_preset: str | None = None,
    autorig_ossos_mod=None,
) -> dict:
    """Assa pose rest natural relaxada (~14 deg) na malha e na armadura sem duplo caimento."""
    if obj is None or getattr(obj, "type", None) != "MESH" or rig_obj is None or getattr(rig_obj, "type", None) != "ARMATURE":
        return {"aplicado": False, "motivo": "objeto_invalido"}
    bones = rig_obj.data.bones
    if any(b.name in _OSSOS_ASA or b.name in _OSSOS_PATA or b.name == "MountSeat" for b in bones):
        return {"aplicado": False, "motivo": "criatura"}
    arm_l, arm_r, _low_l, _low_r, hips, leg_l, leg_r = _resolver_bracos_e_pernas(bones)
    if not (arm_l is not None and arm_r is not None and hips is not None and leg_l is not None):
        return {"aplicado": False, "motivo": "nao_humanoide"}
    theta_antes, up_l, up_r, wr_l, wr_r = _medir_thetas_bracos(bones)
    if theta_antes <= max(20.0, float(angulo_alvo_graus) + 6.0):
        return {"aplicado": False, "motivo": "braco_ja_relaxado", "theta_antes_graus": round(theta_antes, 4)}

    sh_half = 0.5 * (abs(float(arm_l.head_local.x)) + abs(float(arm_r.head_local.x)))
    hip_xs = [abs(float(b.head_local.x)) for b in (leg_l, leg_r) if b is not None]
    t_prop = max(0.0, min(1.0, ((sum(hip_xs) / len(hip_xs)) / max(sh_half, 1e-4) - 0.45) / 0.35))
    alvo_base = max(11.0, min(18.0, float(angulo_alvo_graus) + 2.5 * t_prop))
    var = microvariacao_postura_seed(seed=seed, postura_preset=postura_preset)
    alvo_l = max(11.0, min(18.5, alvo_base + float(var["delta_braco_e_graus"])))
    alvo_r = max(11.0, min(18.5, alvo_base + float(var["delta_braco_d_graus"])))
    delta_l = max(0.0, up_l - alvo_l) if up_l >= wr_l else min(max(0.0, up_l - 11.0), max(0.0, wr_l - alvo_l))
    delta_r = max(0.0, up_r - alvo_r) if up_r >= wr_r else min(max(0.0, up_r - 11.0), max(0.0, wr_r - alvo_r))
    flex_l = max(0.0, min(10.0, float(var["cotovelo_flex_e_graus"])))
    flex_r = max(0.0, min(10.0, float(var["cotovelo_flex_d_graus"])))

    if autorig_ossos_mod is None:
        if __package__:
            from . import autorig_ossos as autorig_ossos_mod  # type: ignore[no-redef]
        else:
            import autorig_ossos as autorig_ossos_mod  # type: ignore[no-redef]

    ativo_atual = getattr(bpy.context.view_layer.objects, "active", None)
    if ativo_atual is not None and getattr(ativo_atual, "mode", "OBJECT") != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")

    mod_estados: list[tuple[object, bool, bool | None]] = []
    temp_arm_mod = None
    if not any(m.type == "ARMATURE" and m.object is rig_obj for m in obj.modifiers):
        temp_arm_mod = obj.modifiers.new("_temp_postura_arm", "ARMATURE")
        temp_arm_mod.object = rig_obj
        temp_arm_mod.use_vertex_groups = True
        temp_arm_mod.use_deform_preserve_volume = True
    for mod in obj.modifiers:
        if mod is temp_arm_mod:
            continue
        pv = getattr(mod, "use_deform_preserve_volume", None) if mod.type == "ARMATURE" else None
        mod_estados.append((mod, bool(mod.show_viewport), pv))
        if mod.type == "ARMATURE":
            mod.show_viewport = True
            mod.use_deform_preserve_volume = True
        else:
            mod.show_viewport = False

    anim_data = getattr(rig_obj, "animation_data", None)
    orig_action = anim_data.action if anim_data is not None else None
    if anim_data is not None and orig_action is not None:
        anim_data.action = None

    def _restaurar_mods() -> None:
        for mod, sv, pv in mod_estados:
            mod.show_viewport = sv
            if pv is not None:
                mod.use_deform_preserve_volume = pv
        if temp_arm_mod is not None and temp_arm_mod.name in obj.modifiers:
            obj.modifiers.remove(temp_arm_mod)

    mods_restaurados = False
    try:
        bpy.ops.object.select_all(action="DESELECT")
        bpy.context.view_layer.objects.active = rig_obj
        rig_obj.select_set(True)
        bpy.ops.object.mode_set(mode="POSE")
        for pb in rig_obj.pose.bones:
            pb.rotation_mode = "QUATERNION"
            pb.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
            pb.location = (0.0, 0.0, 0.0)
            pb.scale = (1.0, 1.0, 1.0)

        tem_ombro = "Shoulder.L" in bones and "Shoulder.R" in bones
        frac_sh, frac_ua = (0.25, 0.75) if tem_ombro else (0.0, 1.0)
        for lado, sgn, d_tot, flex_deg in (("L", -1.0, delta_l, flex_l), ("R", 1.0, delta_r, flex_r)):
            if tem_ombro and (pb_sh := rig_obj.pose.bones.get(f"Shoulder.{lado}")) is not None:
                q_m = pb_sh.bone.matrix_local.to_3x3().to_quaternion()
                pb_sh.rotation_quaternion = (q_m.inverted() @ Quaternion((0.0, 1.0, 0.0), sgn * math.radians(d_tot * frac_sh)) @ q_m).normalized()
            ua_nome = f"UpperArm.{lado}" if f"UpperArm.{lado}" in rig_obj.pose.bones else ("LeftUpperArm" if lado == "L" else "RightUpperArm")
            if (pb_ua := rig_obj.pose.bones.get(ua_nome)) is not None:
                q_m = pb_ua.bone.matrix_local.to_3x3().to_quaternion()
                pb_ua.rotation_quaternion = (q_m.inverted() @ Quaternion((0.0, 1.0, 0.0), sgn * math.radians(d_tot * frac_ua)) @ q_m).normalized()
            la_nome = f"LowerArm.{lado}" if f"LowerArm.{lado}" in rig_obj.pose.bones else ("LeftLowerArm" if lado == "L" else "RightLowerArm")
            if flex_deg > 1e-6 and (pb_la := rig_obj.pose.bones.get(la_nome)) is not None:
                pb_la.rotation_quaternion = Quaternion((1.0, 0.0, 0.0), math.radians(flex_deg))

        bpy.context.view_layer.update()
        deps = bpy.context.evaluated_depsgraph_get()
        eval_obj = obj.evaluated_get(deps)
        eval_mesh = eval_obj.to_mesh()
        try:
            n_verts = len(obj.data.vertices)
            if len(eval_mesh.vertices) != n_verts:
                raise RuntimeError(f"contagem de vertices divergiu no bake natural: {len(eval_mesh.vertices)} != {n_verts}")
            buf = array("f", [0.0]) * (n_verts * 3)
            eval_mesh.vertices.foreach_get("co", buf)
            obj.data.vertices.foreach_set("co", buf)
            obj.data.update()
        finally:
            eval_obj.to_mesh_clear()

        _restaurar_mods()
        mods_restaurados = True
        bpy.ops.pose.armature_apply(selected=False)
        for pb in rig_obj.pose.bones:
            pb.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
            pb.location = (0.0, 0.0, 0.0)
            pb.scale = (1.0, 1.0, 1.0)
        bpy.ops.object.mode_set(mode="OBJECT")
        rig_obj.select_set(False)
        autorig_ossos_mod._alinhar_roll_ossos(rig_obj)
        bpy.context.view_layer.update()
    finally:
        if not mods_restaurados:
            _restaurar_mods()
        if anim_data is not None and orig_action is not None:
            anim_data.action = orig_action
        if getattr(rig_obj, "mode", "OBJECT") != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

    theta_depois = _medir_thetas_bracos(rig_obj.data.bones)[0]
    return {
        "aplicado": True,
        "modo_rest": "natural_relaxada",
        "preset": var["preset"],
        "theta_antes_graus": round(theta_antes, 4),
        "theta_depois_graus": round(theta_depois, 4),
        "angulo_alvo_graus": round(alvo_base, 4),
    }


def aplicar_ground_clamp_fk(
    rig_obj,
    nome_clipe: str,
    z_chao: float,
    *,
    frame: int | None = None,
    tol: float = 1e-4,
    evitar_flutuacao: bool = False,
) -> float:
    """Impede que pes/dedos afundem abaixo de ``z_chao`` (e evita flutuacao em idle)."""
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
    if evitar_flutuacao:
        if abs(min_z - float(z_chao)) <= tol:
            return 0.0
    elif min_z >= float(z_chao) - tol:
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
