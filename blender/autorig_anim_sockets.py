"""Extracao de sockets e aplicacao de animacoes multi-clipe (camada L1, F18a)."""

from __future__ import annotations

import math
import os
import sys

import bpy
from mathutils import Matrix, Quaternion, Vector

if __package__:
    from .autorig_const import (
        _ALIAS_OSSO_CRIATURA,
        _MAT_BL_PARA_GLTF_LINHAS,
        _OSSOS_ASA,
        _OSSOS_PATA,
        _SOCKETS_ALIASES_PARTE,
        _SOCKETS_MAPA,
    )
    from .autorig_pose_natural import (
        _CLIPES_NO_CHAO,
        altura_rig_e_chao,
        aplicar_ground_clamp_fk,
        calcular_caimento_braco_rig,
        peso_gravidade_clipe,
    )
else:
    _BLENDER_DIR = os.path.dirname(os.path.abspath(__file__))
    if _BLENDER_DIR not in sys.path:
        sys.path.insert(0, _BLENDER_DIR)
    from autorig_const import (
        _ALIAS_OSSO_CRIATURA,
        _MAT_BL_PARA_GLTF_LINHAS,
        _OSSOS_ASA,
        _OSSOS_PATA,
        _SOCKETS_ALIASES_PARTE,
        _SOCKETS_MAPA,
    )
    from autorig_pose_natural import (
        _CLIPES_NO_CHAO,
        altura_rig_e_chao,
        aplicar_ground_clamp_fk,
        calcular_caimento_braco_rig,
        peso_gravidade_clipe,
    )


def extrair_ancoras(rig_obj) -> dict[str, list[float]]:
    """Extrai cabecas de todos os ossos em coordenadas Y-up (x, z, -y) no espaco do mundo."""
    if rig_obj is None or getattr(rig_obj, "type", None) != "ARMATURE":
        return {}
    mw = rig_obj.matrix_world
    ancoras: dict[str, list[float]] = {}
    for bone in rig_obj.data.bones:
        p = mw @ bone.head_local
        ancoras[bone.name] = [round(float(p.x), 5), round(float(p.z), 5), round(float(-p.y), 5)]
    return ancoras


def extrair_sockets(
    rig_obj,
    mesh_obj=None,
    solicitados: list[str] | tuple[str, ...] | None = None,
) -> list[dict]:
    """Extrai sockets locais em coordenadas glTF (+Y Up, -Z Frente, det=+1) para manifest@5."""
    if rig_obj is None or getattr(rig_obj, "type", None) != "ARMATURE":
        return []
    ossos = rig_obj.data.bones
    e_criatura = any(
        b.name in _OSSOS_ASA or b.name in _OSSOS_PATA or b.name == "MountSeat" for b in ossos
    )
    zs_rig = [z for b in ossos for z in (b.head_local.z, b.tail_local.z)]
    rig_height_z = (max(zs_rig) - min(zs_rig)) if zs_rig else 0.0
    s_rig = max(rig_height_z / 1.75, 1.0)

    if solicitados:
        ordem: list[str] = []
        for s in solicitados:
            chave = _SOCKETS_ALIASES_PARTE.get(str(s), str(s))
            if chave in _SOCKETS_MAPA and chave not in ordem:
                ordem.append(chave)
    else:
        ordem = ["Hand.R", "Hand.L", "Back", "Head", "Shoulder.L", "Shoulder.R"]
        if e_criatura or "MountSeat" in ossos:
            ordem.append("MountSeat")

    verts_mesh: list[Vector] = []
    if mesh_obj is not None and getattr(mesh_obj, "type", None) == "MESH":
        verts_mesh = [v.co.copy() for v in mesh_obj.data.vertices]

    mat_bl_gltf = Matrix(_MAT_BL_PARA_GLTF_LINHAS)
    saida: list[dict] = []
    for nome_socket in ordem:
        candidatos = _SOCKETS_MAPA.get(nome_socket, (nome_socket,))
        osso = next((ossos[c] for c in candidatos if c in ossos), None)
        if osso is None:
            continue

        m_bone_3x3 = osso.matrix_local.to_3x3().normalized()
        r_gltf = (mat_bl_gltf @ m_bone_3x3).to_quaternion().normalized().to_matrix()
        r_socket = r_gltf.inverted()
        quat = r_socket.to_quaternion().normalized()
        if quat.w < 0.0:
            quat = -quat

        delta_bl = Vector((0.0, 0.0, 0.0))
        if nome_socket == "Hand.R":
            vetor_mao = osso.tail_local - osso.head_local
            tem_dedos_r = "Thumb1.R" in ossos
            fator_r = 0.84 if tem_dedos_r else 0.42
            comp_ref_r = vetor_mao.length * (2.0 if tem_dedos_r else 1.0)
            escala_mao = max(comp_ref_r, 0.05) / 0.10
            delta_bl = vetor_mao * fator_r + (
                m_bone_3x3 @ Vector((0.004 * escala_mao, 0.0, 0.015 * escala_mao))
            )
        elif nome_socket == "Hand.L":
            vetor_mao = osso.tail_local - osso.head_local
            tem_dedos_l = "Thumb1.L" in ossos
            fator_l = 0.76 if tem_dedos_l else 0.38
            comp_ref_l = vetor_mao.length * (2.0 if tem_dedos_l else 1.0)
            escala_mao = max(comp_ref_l, 0.05) / 0.10
            delta_bl = vetor_mao * fator_l + (
                m_bone_3x3 @ Vector((-0.003 * escala_mao, 0.0, 0.014 * escala_mao))
            )
        elif nome_socket == "Back":
            meio_osso = (osso.head_local + osso.tail_local) * 0.5
            dorsal_y = -0.14 * s_rig
            if verts_mesh:
                faixa_z = [
                    v for v in verts_mesh
                    if abs(v.z - meio_osso.z) <= max(0.14 * s_rig, osso.length * 0.9) and abs(v.x) <= 0.18 * s_rig
                ]
                if faixa_z:
                    min_y = min(v.y for v in faixa_z)
                    if e_criatura:
                        max_z_dorso = max(v.z for v in faixa_z)
                        delta_bl = Vector((0.0, 0.0, max(0.06 * s_rig, max_z_dorso - meio_osso.z + 0.02 * s_rig)))
                    else:
                        dorsal_y = min(-0.08 * s_rig, min_y - meio_osso.y - 0.02 * s_rig)
                        delta_bl = (osso.tail_local - osso.head_local) * 0.5 + Vector((0.0, dorsal_y, 0.0))
                else:
                    delta_bl = (osso.tail_local - osso.head_local) * 0.5 + Vector((0.0, dorsal_y, 0.0))
            else:
                delta_bl = (osso.tail_local - osso.head_local) * 0.5 + Vector((0.0, dorsal_y, 0.0))

        pos_local_bl = m_bone_3x3.inverted() @ delta_bl
        saida.append(
            {
                "nome": nome_socket,
                "osso": osso.name,
                "posicao_local": [round(float(pos_local_bl.x), 5), round(float(pos_local_bl.y), 5), round(float(pos_local_bl.z), 5)],
                "rotacao_quat_wxyz": [round(float(quat.w), 6), round(float(quat.x), 6), round(float(quat.y), 6), round(float(quat.z), 6)],
                "frente_local": [0.0, 0.0, -1.0],
            }
        )
    return saida


def _quat_delta_local(pose: dict) -> Quaternion:
    quat_wxyz = pose.get("quat_wxyz")
    if isinstance(quat_wxyz, (list, tuple)) and len(quat_wxyz) == 4:
        return Quaternion(tuple(float(v) for v in quat_wxyz)).normalized()
    eixo = str(pose.get("eixo") or "X").upper()
    vetor = {
        "X": (1.0, 0.0, 0.0),
        "Y": (0.0, 1.0, 0.0),
        "Z": (0.0, 0.0, 1.0),
    }.get(eixo, (1.0, 0.0, 0.0))
    return Quaternion(vetor, math.radians(float(pose.get("graus", 0.0))))


def _aplicar_caimento_bracos_chave(
    rig_obj,
    poses_por_osso: dict[str, list[dict]],
    info_caimento: dict,
    peso: float,
    tocados_rot: list[str],
) -> set[str]:
    """Aplica caimento gravitacional (+Y_bl) em Shoulder/UpperArm antes da rotacao sagital (+X)."""
    tratados: set[str] = set()
    ombro_deg = float(info_caimento["ombro_graus"]) * peso
    braco_deg = float(info_caimento["braco_graus"]) * peso
    sh_total_arm: dict[str, Quaternion] = {}

    for lado, sgn in (("L", 1.0), ("R", -1.0)):
        sh_nome = f"Shoulder.{lado}"
        pb_sh = rig_obj.pose.bones.get(sh_nome)
        if pb_sh is None:
            continue
        tratados.add(sh_nome)
        q_kf_loc = Quaternion((1.0, 0.0, 0.0, 0.0))
        for pose in poses_por_osso.get(sh_nome, ()):
            q_kf_loc = (q_kf_loc @ _quat_delta_local(pose)).normalized()
        q_m_sh = pb_sh.bone.matrix_local.to_3x3().to_quaternion()
        q_kf_arm = (q_m_sh @ q_kf_loc @ q_m_sh.inverted()).normalized()
        q_drop_sh_arm = Quaternion((0.0, 1.0, 0.0), sgn * math.radians(ombro_deg))
        q_tot_arm = (q_kf_arm @ q_drop_sh_arm).normalized()
        pb_sh.rotation_quaternion = (q_m_sh.inverted() @ q_tot_arm @ q_m_sh).normalized()
        sh_total_arm[lado] = q_tot_arm
        if sh_nome in poses_por_osso or abs(ombro_deg) > 1e-6:
            if sh_nome not in tocados_rot:
                tocados_rot.append(sh_nome)

    for arm_nome, lado, sgn in (
        ("UpperArm.L", "L", 1.0),
        ("UpperArm.R", "R", -1.0),
        ("LeftUpperArm", "L", 1.0),
        ("RightUpperArm", "R", -1.0),
    ):
        pb_arm = rig_obj.pose.bones.get(arm_nome)
        if pb_arm is None:
            continue
        tratados.add(arm_nome)
        q_m_arm = pb_arm.bone.matrix_local.to_3x3().to_quaternion()
        q_drop_arm_arm = Quaternion((0.0, 1.0, 0.0), sgn * math.radians(braco_deg))
        if pb_arm.parent and pb_arm.parent.name == f"Shoulder.{lado}":
            q_sh_parent = sh_total_arm.get(lado, Quaternion((1.0, 0.0, 0.0, 0.0)))
        else:
            q_sh_parent = Quaternion((1.0, 0.0, 0.0, 0.0))

        q_clip_arm = Quaternion((1.0, 0.0, 0.0, 0.0))
        for pose in poses_por_osso.get(arm_nome, ()):
            quat_wxyz = pose.get("quat_wxyz")
            if isinstance(quat_wxyz, (list, tuple)) and len(quat_wxyz) == 4:
                q_d_arm = (q_m_arm @ _quat_delta_local(pose) @ q_m_arm.inverted()).normalized()
            elif str(pose.get("eixo") or "X").upper() == "X":
                q_d_arm = Quaternion((1.0, 0.0, 0.0), math.radians(float(pose.get("graus", 0.0))))
            else:
                q_d_arm = (q_m_arm @ _quat_delta_local(pose) @ q_m_arm.inverted()).normalized()
            q_clip_arm = (q_clip_arm @ q_d_arm).normalized()

        pb_arm.rotation_quaternion = (
            q_m_arm.inverted()
            @ q_sh_parent.inverted()
            @ q_clip_arm
            @ q_sh_parent
            @ q_drop_arm_arm
            @ q_m_arm
        ).normalized()
        if arm_nome in poses_por_osso or abs(braco_deg) > 1e-6:
            if arm_nome not in tocados_rot:
                tocados_rot.append(arm_nome)
    return tratados


def aplicar_animacoes_multi(
    rig_obj,
    clipes: list[dict],
    *,
    aplicar_caimento_natural: bool = True,
    aplicar_ground_clamp: bool = True,
) -> list[dict]:
    """Aplica múltiplos clipes em Actions distintas + NLA tracks mudas sem vazamento de pose."""
    if not clipes:
        return []
    cena = bpy.context.scene
    fps_orig = int(cena.render.fps)
    frame_orig = int(cena.frame_current)
    rig_obj.animation_data_create()
    while rig_obj.animation_data.nla_tracks:
        rig_obj.animation_data.nla_tracks.remove(rig_obj.animation_data.nla_tracks[0])

    e_criatura = any(pb.name in _OSSOS_ASA or pb.name in _OSSOS_PATA for pb in rig_obj.pose.bones)
    info_caimento = (
        calcular_caimento_braco_rig(rig_obj)
        if (aplicar_caimento_natural and not e_criatura)
        else {"aplicavel": False, "ombro_graus": 0.0, "braco_graus": 0.0, "tem_ombro": False}
    )
    eh_humanoide, rig_height, z_chao = (
        altura_rig_e_chao(rig_obj) if not e_criatura else (False, 1.75, 0.0)
    )
    caimento_ativo = bool(aplicar_caimento_natural and info_caimento.get("aplicavel"))
    escala_desl = max(0.5, min(3.0, rig_height / 1.75)) if eh_humanoide else 1.0
    clamp_ativo = bool(aplicar_ground_clamp and eh_humanoide and not e_criatura)
    pb_root = rig_obj.pose.bones.get("Hips") or rig_obj.pose.bones.get("LowerTorso")

    geradas: list[dict] = []
    max_frame_end = 1
    try:
        for clipe in clipes:
            nome = str(clipe["nome"])
            eh_idle = nome.strip().lower() == "idle"
            fps = int(clipe.get("fps") or 24)
            cena.render.fps = fps
            duracao_s = float(clipe.get("duracao_s") or 0.0)

            acao = bpy.data.actions.new(nome)
            if acao.name != nome and nome not in bpy.data.actions:
                acao.name = nome
            acao.use_fake_user = True
            rig_obj.animation_data.action = acao

            for pb in rig_obj.pose.bones:
                pb.rotation_mode = "QUATERNION"
                pb.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
                pb.location = (0.0, 0.0, 0.0)
                pb.scale = (1.0, 1.0, 1.0)

            chaves = clipe.get("chaves") or []
            usar_clamp_clipe = clamp_ativo and (nome.strip().lower() in _CLIPES_NO_CHAO) and pb_root is not None
            for idx_ch, chave in enumerate(chaves):
                frame = int(chave["frame"])
                if usar_clamp_clipe:
                    cena.frame_set(frame)
                for pb in rig_obj.pose.bones:
                    pb.rotation_quaternion = Quaternion((1.0, 0.0, 0.0, 0.0))
                    pb.location = Vector((0.0, 0.0, 0.0))
                tocados_rot: list[str] = []
                tocados_loc: list[str] = []
                poses_por_osso: dict[str, list[dict]] = {}
                for pose in chave.get("poses") or []:
                    osso = pose.get("osso")
                    if osso and osso not in rig_obj.pose.bones and e_criatura:
                        osso = next((c for c in _ALIAS_OSSO_CRIATURA.get(str(osso), ()) if c in rig_obj.pose.bones), osso)
                    if not osso or osso not in rig_obj.pose.bones:
                        continue
                    poses_por_osso.setdefault(str(osso), []).append(pose)
                    desloc = pose.get("deslocamento_m")
                    if isinstance(desloc, (list, tuple)) and len(desloc) == 3:
                        pb = rig_obj.pose.bones[str(osso)]
                        delta_arm = Vector((float(desloc[0]), float(desloc[1]), float(desloc[2]))) * escala_desl
                        delta_local = pb.bone.matrix_local.to_3x3().inverted_safe() @ delta_arm
                        pb.location = pb.location + delta_local
                        if osso not in tocados_loc:
                            tocados_loc.append(str(osso))

                tratados_arm: set[str] = set()
                if caimento_ativo:
                    if duracao_s > 0.0 and "segundos" in chave:
                        fracao = max(0.0, min(1.0, float(chave["segundos"]) / duracao_s))
                    elif len(chaves) > 1:
                        fracao = idx_ch / float(len(chaves) - 1)
                    else:
                        fracao = 0.0
                    peso = peso_gravidade_clipe(nome, fracao)
                    tratados_arm = _aplicar_caimento_bracos_chave(
                        rig_obj, poses_por_osso, info_caimento, peso, tocados_rot
                    )

                for osso, poses_osso in poses_por_osso.items():
                    if osso in tratados_arm:
                        continue
                    pb = rig_obj.pose.bones[osso]
                    for pose in poses_osso:
                        pb.rotation_quaternion = (pb.rotation_quaternion @ _quat_delta_local(pose)).normalized()
                    if osso not in tocados_rot:
                        tocados_rot.append(osso)

                for osso in tocados_rot:
                    rig_obj.pose.bones[osso].keyframe_insert("rotation_quaternion", frame=frame)
                for osso in tocados_loc:
                    rig_obj.pose.bones[osso].keyframe_insert("location", frame=frame)
                if usar_clamp_clipe and pb_root is not None:
                    if pb_root.name not in tocados_loc:
                        pb_root.keyframe_insert("location", frame=frame)
                    aplicar_ground_clamp_fk(rig_obj, nome, z_chao, frame=frame, evitar_flutuacao=eh_idle)

            frames = int(round(duracao_s * fps))
            for fc in acao.fcurves:
                for kp in fc.keyframe_points:
                    kp.interpolation = "BEZIER"
                    kp.handle_left_type = "AUTO_CLAMPED"
                    kp.handle_right_type = "AUTO_CLAMPED"
                fc.update()

            if usar_clamp_clipe and frames > 0:
                inseriu_clamp = False
                for fr in range(1, 2 + frames):
                    cena.frame_set(fr)
                    if abs(aplicar_ground_clamp_fk(rig_obj, nome, z_chao, frame=fr, tol=1e-3, evitar_flutuacao=eh_idle)) > 0.0:
                        inseriu_clamp = True
                if inseriu_clamp:
                    for fc in acao.fcurves:
                        for kp in fc.keyframe_points:
                            kp.interpolation = "BEZIER"
                            kp.handle_left_type = "AUTO_CLAMPED"
                            kp.handle_right_type = "AUTO_CLAMPED"
                        fc.update()

            track = rig_obj.animation_data.nla_tracks.new()
            track.name = nome
            inicio = int(acao.frame_range[0]) if acao.fcurves else 1
            strip = track.strips.new(nome, inicio, acao)
            strip.name = nome
            track.mute = True

            rig_obj.animation_data.action = None
            for pb in rig_obj.pose.bones:
                pb.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
                pb.location = (0.0, 0.0, 0.0)

            max_frame_end = max(max_frame_end, 1 + frames)
            geradas.append(
                {
                    "nome": nome,
                    "duracao_s": duracao_s,
                    "ossos": list(clipe.get("ossos") or []),
                    "frames": frames,
                }
            )

        cena.frame_start = 1
        cena.frame_end = max_frame_end
    finally:
        cena.render.fps = fps_orig
        cena.frame_set(frame_orig)
    return geradas
