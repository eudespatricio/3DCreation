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


def aplicar_animacoes_multi(rig_obj, clipes: list[dict]) -> list[dict]:
    """Aplica múltiplos clipes em Actions distintas + NLA tracks mudas sem vazamento de pose."""
    if not clipes:
        return []
    cena = bpy.context.scene
    rig_obj.animation_data_create()
    while rig_obj.animation_data.nla_tracks:
        rig_obj.animation_data.nla_tracks.remove(rig_obj.animation_data.nla_tracks[0])

    e_criatura = any(pb.name in _OSSOS_ASA or pb.name in _OSSOS_PATA for pb in rig_obj.pose.bones)
    geradas: list[dict] = []
    max_frame_end = 1
    for clipe in clipes:
        nome = str(clipe["nome"])
        fps = int(clipe.get("fps") or 24)
        cena.render.fps = fps

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

        for chave in clipe.get("chaves") or []:
            frame = int(chave["frame"])
            for pb in rig_obj.pose.bones:
                pb.rotation_quaternion = Quaternion((1.0, 0.0, 0.0, 0.0))
                pb.location = Vector((0.0, 0.0, 0.0))
            tocados_rot: list[str] = []
            tocados_loc: list[str] = []
            for pose in chave.get("poses") or []:
                osso = pose.get("osso")
                if osso and osso not in rig_obj.pose.bones and e_criatura:
                    osso = next((c for c in _ALIAS_OSSO_CRIATURA.get(str(osso), ()) if c in rig_obj.pose.bones), osso)
                if not osso or osso not in rig_obj.pose.bones:
                    continue
                pb = rig_obj.pose.bones[osso]
                quat_wxyz = pose.get("quat_wxyz")
                if isinstance(quat_wxyz, (list, tuple)) and len(quat_wxyz) == 4:
                    q_delta = Quaternion(tuple(float(v) for v in quat_wxyz)).normalized()
                else:
                    eixo = str(pose.get("eixo") or "X").upper()
                    vetor = {
                        "X": (1.0, 0.0, 0.0),
                        "Y": (0.0, 1.0, 0.0),
                        "Z": (0.0, 0.0, 1.0),
                    }.get(eixo, (1.0, 0.0, 0.0))
                    q_delta = Quaternion(vetor, math.radians(float(pose.get("graus", 0.0))))
                pb.rotation_quaternion = (pb.rotation_quaternion @ q_delta).normalized()
                if osso not in tocados_rot:
                    tocados_rot.append(osso)
                desloc = pose.get("deslocamento_m")
                if isinstance(desloc, (list, tuple)) and len(desloc) == 3:
                    delta_arm = Vector((float(desloc[0]), float(desloc[1]), float(desloc[2])))
                    delta_local = pb.bone.matrix_local.to_3x3().inverted_safe() @ delta_arm
                    pb.location = pb.location + delta_local
                    if osso not in tocados_loc:
                        tocados_loc.append(osso)
            for osso in tocados_rot:
                rig_obj.pose.bones[osso].keyframe_insert("rotation_quaternion", frame=frame)
            for osso in tocados_loc:
                rig_obj.pose.bones[osso].keyframe_insert("location", frame=frame)

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

        duracao_s = float(clipe["duracao_s"])
        frames = int(round(duracao_s * fps))
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
    return geradas
