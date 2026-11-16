"""Auto-rigging orgânico e animações multi-clipe para Blender 4.2 (Fase B).

Usa **apenas** ``bpy``, ``bmesh``, ``mathutils`` e stdlib (sem Pillow, sem numpy).
Convenção canônica da malha: +Z para cima, base em Z=0, frente +Y, X centrado em 0,
lado esquerdo (``.L`` / ``Left*``) em ``+X`` e lado direito (``.R`` / ``Right*``) em ``-X``
(idêntico a ``blocky.OSSOS_HUMANOIDE`` e ``blocky.OSSOS_R15``).
"""

from __future__ import annotations

import heapq
import math

import bmesh
import bpy
from mathutils import Matrix, Quaternion, Vector

__all__ = [
    "auto_rigar_humanoide",
    "auto_rigar_por_tipo",
    "extrair_sockets",
    "aplicar_animacoes_multi",
    "estimar_marcos",
]

ESQUELETOS_SUPORTADOS = ("godot-humanoid@1", "r15@1", "quadruped@1", "winged_mount@1")
_ESQUELETOS_HUMANOS = ("godot-humanoid@1", "r15@1")
_ESQUELETOS_CRIATURA = ("quadruped@1", "winged_mount@1")
_RAIZES = {"Root", "HumanoidRootPart"}
_OSSOS_ASA = {
    "WingShoulder.L",
    "WingArm.L",
    "WingForearm.L",
    "WingTip.L",
    "WingShoulder.R",
    "WingArm.R",
    "WingForearm.R",
    "WingTip.R",
}
_OSSOS_PATA = {
    "FrontUpperLeg.L",
    "FrontLowerLeg.L",
    "FrontFoot.L",
    "FrontUpperLeg.R",
    "FrontLowerLeg.R",
    "FrontFoot.R",
    "BackUpperLeg.L",
    "BackLowerLeg.L",
    "BackFoot.L",
    "BackUpperLeg.R",
    "BackLowerLeg.R",
    "BackFoot.R",
}
_OSSOS_CAUDA = {"Tail1", "Tail2", "Tail3"}
_OSSOS_PERNA = {
    "UpperLeg.L",
    "LowerLeg.L",
    "Foot.L",
    "Toe.L",
    "UpperLeg.R",
    "LowerLeg.R",
    "Foot.R",
    "Toe.R",
    "LeftUpperLeg",
    "LeftLowerLeg",
    "LeftFoot",
    "RightUpperLeg",
    "RightLowerLeg",
    "RightFoot",
}
_OSSOS_OMBROS = {"Shoulder.L", "Shoulder.R"}
_OSSOS_BRACO = {
    "Shoulder.L",
    "UpperArm.L",
    "LowerArm.L",
    "Hand.L",
    "Shoulder.R",
    "UpperArm.R",
    "LowerArm.R",
    "Hand.R",
    "LeftUpperArm",
    "LeftLowerArm",
    "LeftHand",
    "RightUpperArm",
    "RightLowerArm",
    "RightHand",
}
_OSSOS_BRACO_DISTAL = _OSSOS_BRACO - _OSSOS_OMBROS
_OSSOS_CABECA = {"Head"}
_OSSOS_PESCOCO = {"Neck"}
_OSSOS_TORAX = {"Chest", "UpperTorso"}
_OSSOS_TRONCO = {
    "Hips",
    "Spine",
    "Spine1",
    "Chest",
    "Neck",
    "Head",
    "LowerTorso",
    "UpperTorso",
}
_OSSOS_COXA = {"UpperLeg.L", "UpperLeg.R", "LeftUpperLeg", "RightUpperLeg"}
_OSSOS_CANELA = {"LowerLeg.L", "LowerLeg.R", "LeftLowerLeg", "RightLowerLeg"}
_OSSOS_PE = {"Foot.L", "Toe.L", "Foot.R", "Toe.R", "LeftFoot", "RightFoot"}


def _selecionar_unico(obj) -> None:
    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)


def _aplicar_identidade(obj) -> None:
    _selecionar_unico(obj)
    if obj.parent is not None:
        bpy.ops.object.parent_clear(type="CLEAR_KEEP_TRANSFORM")
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    obj.select_set(False)


def _garantir_modificador_armature(obj, rig_obj) -> None:
    for mod in list(obj.modifiers):
        if mod.type == "ARMATURE":
            obj.modifiers.remove(mod)
    obj.parent = rig_obj
    obj.matrix_parent_inverse = Matrix.Identity(4)
    mod = obj.modifiers.new("armature", "ARMATURE")
    mod.object = rig_obj
    mod.use_vertex_groups = True
    mod.use_deform_preserve_volume = True


def _clamped(valor: float, minimo: float, maximo: float) -> float:
    return max(minimo, min(maximo, valor))


def _mediana(valores: list[float], padrao: float) -> float:
    if not valores:
        return padrao
    ordenados = sorted(valores)
    meio = len(ordenados) // 2
    if len(ordenados) % 2 == 1:
        return ordenados[meio]
    return 0.5 * (ordenados[meio - 1] + ordenados[meio])


def _centroide(pontos: list[Vector], padrao: Vector) -> Vector:
    if not pontos:
        return padrao.copy()
    soma = Vector((0.0, 0.0, 0.0))
    for p in pontos:
        soma += p
    return soma / float(len(pontos))


def _estimar_lado_braco(
    coords: list[Vector],
    z0: float,
    altura: float,
    cy: float,
    chest_top_z: float,
    torso_hw: float,
    sinal: float,
    leg_top_z: float = 0.0,
    leg_x: float = 0.0,
    upper_torso_hw: float | None = None,
) -> dict:
    """Detecta ombro, cotovelo, pulso e ponta da mão para +X (L) ou -X (R)."""
    ref_hw = max(torso_hw, upper_torso_hw or torso_hw)
    shoulder_z_default = _clamped(chest_top_z - 0.02 * altura, z0 + 0.72 * altura, z0 + 0.79 * altura)
    shoulder_x_default = sinal * _clamped(ref_hw * 1.12, 0.08 * altura, 0.18 * altura)
    clav_x_default = sinal * min(0.10 * altura, 0.65 * abs(shoulder_x_default))

    ombro_verts = [
        v
        for v in coords
        if z0 + 0.70 * altura <= v.z <= z0 + 0.83 * altura
        and abs(shoulder_x_default) * 0.85 <= v.x * sinal <= abs(shoulder_x_default) * 1.35
    ]
    if ombro_verts:
        zs_ombro = sorted(v.z for v in ombro_verts)
        # Usa terco medio-superior do ombro para nao ser puxado para baixo pela axila
        z_acromio = zs_ombro[int(0.60 * (len(zs_ombro) - 1))]
        shoulder_z = _clamped(
            z_acromio,
            max(z0 + 0.70 * altura, chest_top_z - 0.055 * altura),
            min(z0 + 0.80 * altura, chest_top_z - 0.005 * altura),
        )
    else:
        shoulder_z = shoulder_z_default

    limiar_braco = max(ref_hw * 1.04, 0.075 * altura)
    limiar_coxa = max(ref_hw * 1.15, abs(leg_x) + 0.04 * altura)
    z_coxa_corte = leg_top_z + 0.02 * altura if leg_top_z > z0 else z0 + 0.44 * altura
    braco_verts = [
        v
        for v in coords
        if v.x * sinal > limiar_braco
        and z0 + 0.28 * altura <= v.z <= z0 + 0.86 * altura
        and (v.z > z_coxa_corte or v.x * sinal > limiar_coxa)
    ]
    if braco_verts:
        max_x_lado = max(v.x * sinal for v in braco_verts)
        if max_x_lado > max(abs(shoulder_x_default) * 1.45, 0.20 * altura):
            filtrados = [
                v
                for v in braco_verts
                if not (v.z < z0 + 0.58 * altura and v.x * sinal < max_x_lado * 0.62)
            ]
            if len(filtrados) >= 6:
                braco_verts = filtrados
    shoulder_pos = Vector((shoulder_x_default, cy, shoulder_z))

    if len(braco_verts) < 6:
        elbow = Vector((sinal * 0.17 * altura, cy, z0 + 0.60 * altura))
        wrist = Vector((sinal * 0.17 * altura, cy, z0 + 0.44 * altura))
        tip = Vector((sinal * 0.17 * altura, cy, z0 + 0.36 * altura))
        return {
            "clav_x": clav_x_default,
            "shoulder": shoulder_pos,
            "elbow": elbow,
            "wrist": wrist,
            "tip": tip,
        }

    # Ponta da mão: centróide dos 5% vértices mais distantes do ombro (funciona em T-pose, A-pose e braços baixos)
    ordenados = sorted(braco_verts, key=lambda v: (v - shoulder_pos).length, reverse=True)
    n_ponta = max(3, min(20, len(ordenados) // 20))
    tip = _centroide(ordenados[:n_ponta], Vector((sinal * 0.17 * altura, cy, z0 + 0.36 * altura)))
    if tip.x * sinal < abs(shoulder_x_default) * 0.9:
        tip.x = sinal * max(0.11 * altura, abs(shoulder_x_default) * 1.05)

    arm_vec = tip - shoulder_pos
    arm_len = arm_vec.length
    if arm_len < 0.14 * altura:
        elbow = Vector((sinal * 0.17 * altura, cy, z0 + 0.60 * altura))
        wrist = Vector((sinal * 0.17 * altura, cy, z0 + 0.44 * altura))
        tip = Vector((sinal * 0.17 * altura, cy, z0 + 0.36 * altura))
        return {
            "clav_x": clav_x_default,
            "shoulder": shoulder_pos,
            "elbow": elbow,
            "wrist": wrist,
            "tip": tip,
        }

    eixo = arm_vec / arm_len
    faixa_cotovelo = [v for v in braco_verts if 0.32 <= (v - shoulder_pos).dot(eixo) / arm_len <= 0.48]
    faixa_pulso = [v for v in braco_verts if 0.72 <= (v - shoulder_pos).dot(eixo) / arm_len <= 0.86]

    elbow_padrao = shoulder_pos + arm_vec * 0.40
    wrist_padrao = shoulder_pos + arm_vec * 0.80
    elbow = _centroide(faixa_cotovelo, elbow_padrao)
    wrist = _centroide(faixa_pulso, wrist_padrao)
    if elbow.x * sinal < limiar_braco * 0.85:
        elbow.x = elbow_padrao.x
    if wrist.x * sinal < limiar_braco * 0.85:
        wrist.x = wrist_padrao.x

    return {
        "clav_x": clav_x_default,
        "shoulder": shoulder_pos,
        "elbow": elbow,
        "wrist": wrist,
        "tip": tip,
    }


def _torso_meia_largura(
    obj,
    coords: list[Vector],
    z_min: float,
    altura: float,
    ignorar: set[int] | None = None,
    z_lo_fracs: tuple[float, ...] = (0.55, 0.48),
    z_hi_frac: float = 0.66,
    x_cap_frac: float = 0.15,
) -> float:
    """Estima meia-largura do tronco por componente conexo sem invadir braços pendurados ou ilhas soltas."""
    n = len(coords)
    ign = ignorar or set()
    arestas = getattr(obj.data, "edges", None)
    if arestas and n > 0:
        for z_lo_frac in z_lo_fracs:
            z_lo = z_min + z_lo_frac * altura
            z_hi = z_min + z_hi_frac * altura
            dentro = bytearray(n)
            for i, v in enumerate(coords):
                if i not in ign and z_lo <= v.z <= z_hi:
                    dentro[i] = 1
            sementes = [i for i, v in enumerate(coords) if dentro[i] and abs(v.x) <= 0.08 * altura]
            if not sementes:
                continue
            adj_cintura: dict[int, list[int]] = {}
            for e in arestas:
                a, b = e.vertices[0], e.vertices[1]
                if dentro[a] and dentro[b]:
                    adj_cintura.setdefault(a, []).append(b)
                    adj_cintura.setdefault(b, []).append(a)
            visitado = bytearray(n)
            fila: list[int] = []
            for s in sementes:
                if not visitado[s]:
                    visitado[s] = 1
                    fila.append(s)
            pos = 0
            while pos < len(fila):
                u = fila[pos]
                pos += 1
                for w in adj_cintura.get(u, ()):
                    if not visitado[w]:
                        visitado[w] = 1
                        fila.append(w)
            xs = sorted(abs(coords[i].x) for i in fila)
            if len(xs) >= 4:
                return _clamped(xs[int(0.9 * (len(xs) - 1))], 0.065 * altura, x_cap_frac * altura)

    cintura_x = sorted(
        abs(v.x)
        for i, v in enumerate(coords)
        if i not in ign and z_min + z_lo_fracs[0] * altura <= v.z <= z_min + z_hi_frac * altura and abs(v.x) <= 0.12 * altura
    )
    torso_hw = cintura_x[int(0.9 * (len(cintura_x) - 1))] if cintura_x else 0.12 * altura
    return _clamped(torso_hw, 0.065 * altura, x_cap_frac * altura)


def estimar_marcos(obj) -> dict:
    """Estima marcos anatômicos a partir da nuvem de vértices canônica (+Z cima, X=0 centro)."""
    cabelo_slots = {
        idx
        for idx, mat in enumerate(obj.data.materials)
        if mat is not None and str(mat.name).startswith("makehuman_cabelo")
    }
    verts_cabelo = (
        {
            vi
            for poly in obj.data.polygons
            if poly.material_index in cabelo_slots
            for vi in poly.vertices
        }
        if cabelo_slots
        else set()
    )
    all_coords = [obj.matrix_world @ v.co for v in obj.data.vertices]
    coords = [
        all_coords[i]
        for i in range(len(all_coords))
        if i not in verts_cabelo
    ]
    if not coords:
        coords = all_coords
        verts_cabelo = set()
    if not coords:
        raise RuntimeError("malha sem vertices para auto-rig")

    z_min = min(v.z for v in coords)
    z_max = max(v.z for v in coords)
    altura = z_max - z_min
    if altura <= 1e-6:
        raise RuntimeError("malha com altura zero para auto-rig")

    cy = _clamped(
        _mediana(
            [v.y for v in coords if z_min + 0.45 * altura <= v.z <= z_min + 0.78 * altura and abs(v.x) <= 0.12 * altura],
            0.0,
        ),
        -0.04 * altura,
        0.04 * altura,
    )

    # Pescoço: menor largura central (|x| <= 0.15*H) entre 0.74*H e 0.88*H
    fatias_pescoco: list[tuple[float, float]] = []
    for i in range(15):
        za = z_min + (0.74 + 0.01 * i) * altura
        zb = za + 0.025 * altura
        xs = [v.x for v in coords if za <= v.z <= zb and abs(v.x) <= 0.15 * altura]
        if len(xs) >= 3:
            fatias_pescoco.append((0.5 * (za + zb), max(xs) - min(xs)))

    if fatias_pescoco:
        idx_min = max(
            range(len(fatias_pescoco)),
            key=lambda idx: (-round(fatias_pescoco[idx][1], 5), fatias_pescoco[idx][0]),
        )
        melhor_z, melhor_largura = fatias_pescoco[idx_min]
        j = idx_min
        while j > 0 and fatias_pescoco[j - 1][1] <= melhor_largura * 1.45:
            j -= 1
        z_colarinho = fatias_pescoco[j][0]
        if j > 0 and fatias_pescoco[j - 1][1] >= melhor_largura * 1.65:
            # Degrau nítido entre colarinho e tronco vs. trapézio inclinado anatômico
            razao_salto = (fatias_pescoco[j - 1][1] - fatias_pescoco[j][1]) / max(melhor_largura, 1e-4)
            if razao_salto >= 0.75:
                est_chest_top = 0.5 * (fatias_pescoco[j - 1][0] + z_colarinho)
            else:
                est_chest_top = fatias_pescoco[j - 1][0] - 0.035 * altura
        else:
            est_chest_top = melhor_z - 0.055 * altura
    else:
        melhor_z = z_min + 0.80 * altura
        melhor_largura = float("inf")
        est_chest_top = melhor_z - 0.055 * altura

    neck_hw = _clamped(0.5 * melhor_largura if melhor_largura < float("inf") else 0.038 * altura, 0.025 * altura, 0.075 * altura)
    chest_top_z = _clamped(est_chest_top, z_min + 0.74 * altura, z_min + 0.79 * altura)
    neck_z = _clamped(chest_top_z + 0.065 * altura, z_min + 0.805 * altura, z_min + 0.86 * altura)
    head_top_z = z_max

    # Quadril / bifurcação das pernas: primeira fatia de baixo para cima onde |x| < 0.025*H preenche
    leg_top_z = z_min + 0.44 * altura
    for i in range(14):
        za = z_min + (0.36 + 0.012 * i) * altura
        zb = za + 0.02 * altura
        fatia = [v for v in coords if za <= v.z <= zb and abs(v.x) <= 0.14 * altura]
        if len(fatia) >= 4:
            centro = sum(1 for v in fatia if abs(v.x) <= 0.022 * altura)
            esq = any(v.x > 0.03 * altura for v in fatia)
            dir_ = any(v.x < -0.03 * altura for v in fatia)
            if centro >= 2 and esq and dir_:
                leg_top_z = _clamped(0.5 * (za + zb), z_min + 0.40 * altura, z_min + 0.48 * altura)
                break

    hip_z = _clamped(leg_top_z + 0.04 * altura, z_min + 0.465 * altura, z_min + 0.52 * altura)
    spine_z = hip_z + 0.05 * altura
    spine1_z = _clamped(spine_z + 0.05 * altura, z_min + 0.56 * altura, chest_top_z - 0.16 * altura)
    chest_z = _clamped(spine1_z + 0.075 * altura, z_min + 0.64 * altura, chest_top_z - 0.085 * altura)

    ankle_z = z_min + 0.065 * altura
    knee_z = _clamped(0.5 * (ankle_z + leg_top_z), z_min + 0.21 * altura, z_min + 0.28 * altura)

    leg_x_L = _clamped(
        _mediana(
            [v.x for v in coords if z_min + 0.10 * altura <= v.z <= leg_top_z - 0.03 * altura and v.x > 0.01 * altura],
            0.065 * altura,
        ),
        0.045 * altura,
        0.13 * altura,
    )
    leg_x_R = _clamped(
        _mediana(
            [v.x for v in coords if z_min + 0.10 * altura <= v.z <= leg_top_z - 0.03 * altura and v.x < -0.01 * altura],
            -0.065 * altura,
        ),
        -0.13 * altura,
        -0.045 * altura,
    )

    pes_y = sorted(v.y for v in coords if v.z <= ankle_z + 0.01 * altura and v.y > 0.0)
    max_foot_y = pes_y[int(0.9 * (len(pes_y) - 1))] if pes_y else 0.12 * altura
    foot_y = _clamped(max_foot_y * 0.85, 0.08 * altura, 0.15 * altura)
    toe_y = foot_y + 0.04 * altura

    torso_hw = _torso_meia_largura(obj, all_coords, z_min, altura, ignorar=verts_cabelo)

    braco_L = _estimar_lado_braco(
        coords,
        z_min,
        altura,
        cy,
        chest_top_z,
        torso_hw,
        1.0,
        leg_top_z=leg_top_z,
        leg_x=leg_x_L,
    )
    braco_R = _estimar_lado_braco(
        coords,
        z_min,
        altura,
        cy,
        chest_top_z,
        torso_hw,
        -1.0,
        leg_top_z=leg_top_z,
        leg_x=leg_x_R,
    )
    if abs(abs(braco_L["elbow"].x) - abs(braco_R["elbow"].x)) <= 0.06 * altura:
        clav_sym = 0.5 * (abs(braco_L["clav_x"]) + abs(braco_R["clav_x"]))
        braco_L["clav_x"] = clav_sym
        braco_R["clav_x"] = -clav_sym
        for chave in ("shoulder", "elbow", "wrist", "tip"):
            pL = braco_L[chave]
            pR = braco_R[chave]
            sx = 0.5 * (abs(pL.x) + abs(pR.x))
            sy = 0.5 * (pL.y + pR.y)
            sz = 0.5 * (pL.z + pR.z)
            braco_L[chave] = Vector((sx, sy, sz))
            braco_R[chave] = Vector((-sx, sy, sz))

    return {
        "z_min": z_min,
        "z_max": z_max,
        "altura": altura,
        "cy": cy,
        "torso_hw": torso_hw,
        "neck_hw": neck_hw,
        "leg_top_z": leg_top_z,
        "hip_z": hip_z,
        "spine_z": spine_z,
        "spine1_z": spine1_z,
        "chest_z": chest_z,
        "chest_top_z": chest_top_z,
        "neck_z": neck_z,
        "head_top_z": head_top_z,
        "knee_z": knee_z,
        "ankle_z": ankle_z,
        "leg_x_L": leg_x_L,
        "leg_x_R": leg_x_R,
        "foot_y": foot_y,
        "toe_y": toe_y,
        "braco_L": braco_L,
        "braco_R": braco_R,
        "shoulder_z": 0.5 * (braco_L["shoulder"].z + braco_R["shoulder"].z),
        "shoulder_x_L": braco_L["shoulder"].x,
        "shoulder_x_R": braco_R["shoulder"].x,
        "elbow_x_L": braco_L["elbow"].x,
        "elbow_x_R": braco_R["elbow"].x,
        "wrist_x_L": braco_L["wrist"].x,
        "wrist_x_R": braco_R["wrist"].x,
    }


def _osso(nome: str, pai: str | None, cabeca, cauda, min_len: float) -> dict:
    h = Vector(cabeca)
    t = Vector(cauda)
    if (t - h).length < min_len:
        t = h + Vector((0.0, 0.0, min_len))
    return {"nome": nome, "pai": pai, "cabeca": tuple(h), "cauda": tuple(t)}


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
    if esqueleto == "r15@1":
        hip_leg_z = max(m["leg_top_z"] + 0.02 * h, m["hip_z"] - 0.015 * h)
        return [
            _osso("HumanoidRootPart", None, (0.0, 0.0, z0), (0.0, 0.0, z0 + 0.05 * h), ml),
            _osso("LowerTorso", "HumanoidRootPart", (0.0, cy, m["leg_top_z"]), (0.0, cy, m["spine_z"]), ml),
            _osso("UpperTorso", "LowerTorso", (0.0, cy, m["spine_z"]), (0.0, cy, m["chest_top_z"]), ml),
            _osso("Head", "UpperTorso", (0.0, cy, m["chest_top_z"]), (0.0, cy, m["head_top_z"]), ml),
            _osso("LeftUpperArm", "UpperTorso", (bL["clav_x"], cy, bL["shoulder"].z), bL["elbow"], ml),
            _osso("LeftLowerArm", "LeftUpperArm", bL["elbow"], bL["wrist"], ml),
            _osso("LeftHand", "LeftLowerArm", bL["wrist"], bL["tip"], ml),
            _osso("RightUpperArm", "UpperTorso", (bR["clav_x"], cy, bR["shoulder"].z), bR["elbow"], ml),
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
                if abs(n.x) > 0.5:
                    # Canoniza sinal lateral (+X) para simetria L/R e sem torcao de 180 deg
                    n_canon = n if n.x > 0.0 else -n
                    planos_lado[sup_n] = n_canon
                    for eb_arm in (sup, inf):
                        alvo = n_canon.cross(eb_arm.y_axis)
                        if alvo.length > 1e-4:
                            alvos_braco[eb_arm.name] = alvo.normalized()
        # Espelha plano do lado dobrado se o lado oposto estiver quase reto
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
    for eb in edit_bones:
        if eb.name in alvos_braco:
            eb.align_roll(alvos_braco[eb.name])
        elif eb.name in _OSSOS_BRACO or eb.name in _OSSOS_PERNA or eb.name in ossos_eixo_criatura:
            alvo = cima if abs(eb.y_axis.y) > 0.85 else frente
            eb.align_roll(alvo)
        elif e_rig_criatura and eb.name in ("Spine", "Chest", "Neck", "Head", "Jaw"):
            alvo = cima if abs(eb.y_axis.y) > 0.65 else Vector((0.0, -1.0, 0.0))
            eb.align_roll(alvo)
    bpy.ops.object.mode_set(mode="OBJECT")
    rig_obj.select_set(False)


def _dist_ponto_segmento(p: Vector, a: Vector, b: Vector) -> float:
    ab = b - a
    comp2 = ab.length_squared
    if comp2 <= 1e-12:
        return (p - a).length
    t = max(0.0, min(1.0, (p - a).dot(ab) / comp2))
    proj = a + ab * t
    return (p - proj).length


def _lado_osso(nome: str) -> str:
    if nome.endswith(".L") or nome.startswith("Left"):
        return "L"
    if nome.endswith(".R") or nome.startswith("Right"):
        return "R"
    return "C"


def _limites_anatomicos(m: dict, tem_neck: bool = True) -> dict[str, float]:
    """Pré-calcula fronteiras espaciais semânticas entre cabeça, pescoço, tórax, cintura, ombros e membros."""
    h = m["altura"]
    torso_hw = m.get("torso_hw", 0.12 * h)
    neck_hw = m.get("neck_hw", 0.038 * h)
    arm_z_cut = m["shoulder_z"] - 0.11 * h
    arm_z_cut_lo = arm_z_cut - 0.03 * h
    arm_root_x = max(torso_hw * 1.06, 0.082 * h)
    arm_deltoid_x = max(arm_root_x + 0.038 * h, torso_hw * 1.55, 0.118 * h)
    ombro_min_x = max(torso_hw * 0.85, 0.066 * h)
    ombro_max_x = max(abs(m["shoulder_x_L"]), abs(m["shoulder_x_R"]), arm_root_x) + 0.06 * h
    neck_max_x = max(neck_hw * 1.45, 0.052 * h)
    tronco_max_x = max(abs(m["shoulder_x_L"]), abs(m["shoulder_x_R"]), arm_deltoid_x, 0.14 * h) * 1.12
    leg_x_min = min(abs(m["leg_x_L"]), abs(m["leg_x_R"]))
    x_tol_leg = min(0.015 * h, 0.25 * leg_x_min)
    perna_max_x = max(torso_hw * 1.02, max(abs(m["leg_x_L"]), abs(m["leg_x_R"])) + 0.036 * h)
    return {
        "h": h,
        "x_tol": 0.03 * h,
        "x_tol_leg": x_tol_leg,
        "torso_hw": torso_hw,
        "neck_max_x": neck_max_x,
        "ombro_min_x": ombro_min_x,
        "ombro_max_x": ombro_max_x,
        "arm_root_x": arm_root_x,
        "arm_deltoid_x": arm_deltoid_x,
        "arm_z_cut": arm_z_cut,
        "arm_z_cut_lo": arm_z_cut_lo,
        "arm_z_min": m["z_min"] + 0.20 * h,
        "braco_baixo_min_x": max(torso_hw * 1.01, 0.04 * h),
        "tronco_max_x": tronco_max_x,
        "perna_max_x": perna_max_x,
        "head_z_min": (m["neck_z"] - 0.022 * h) if tem_neck else (m["chest_top_z"] - 0.008 * h),
        "neck_z_min": m["chest_top_z"] - 0.012 * h,
        "neck_z_max": m["neck_z"] + 0.045 * h,
        "chest_z_min": m["spine1_z"] - 0.015 * h,
        "upper_torso_z_min": m["hip_z"] - 0.01 * h,
        "chest_z_max": (m["neck_z"] + 0.02 * h) if tem_neck else (m["chest_top_z"] + 0.035 * h),
        "spine1_z_min": m["hip_z"] - 0.01 * h,
        "spine1_z_max": m["chest_top_z"] - 0.02 * h,
        "spine_z_min": m["hip_z"] - 0.02 * h,
        "spine_z_max": m["chest_z"] + 0.02 * h,
        "hips_z_max": m["chest_z"] + 0.03 * h,
        "leg_z_max": m["hip_z"] + 0.04 * h,
        "upper_leg_z_min": m["knee_z"] - 0.05 * h,
        "lower_leg_z_max": m["hip_z"] - 0.02 * h,
        "foot_z_max": m["knee_z"] - 0.03 * h,
        "z_min_floor": m["z_min"] - 0.01 * h,
    }


def _osso_permitido(
    nome: str,
    v: Vector,
    m: dict,
    bracos_baixos: bool,
    tem_neck: bool = True,
    lim: dict[str, float] | None = None,
) -> bool:
    if nome in _RAIZES:
        return False
    b = lim if lim is not None else _limites_anatomicos(m, tem_neck=tem_neck)
    lado = _lado_osso(nome)
    vx, vz = v.x, v.z
    abs_x = vx if vx >= 0.0 else -vx
    x_tol = b["x_tol_leg"] if nome in _OSSOS_PERNA else b["x_tol"]
    if vx > x_tol and lado == "R":
        return False
    if vx < -x_tol and lado == "L":
        return False
    if abs_x <= b["x_tol"] and nome in _OSSOS_BRACO:
        return False

    if nome in _OSSOS_PE:
        return vz <= b["foot_z_max"]
    if nome in _OSSOS_CANELA:
        return b["z_min_floor"] <= vz <= b["lower_leg_z_max"]
    if nome in _OSSOS_COXA:
        return b["upper_leg_z_min"] <= vz <= b["leg_z_max"]
    if nome in _OSSOS_OMBROS:
        return b["arm_z_cut_lo"] <= vz <= m["chest_top_z"] + 0.025 * b["h"] and abs_x >= b["ombro_min_x"]
    if nome in _OSSOS_BRACO_DISTAL:
        if vz >= b["arm_z_cut"] and abs_x >= b["arm_root_x"]:
            return True
        return bracos_baixos and abs_x > b["braco_baixo_min_x"] and vz >= b["arm_z_min"]
    if nome in _OSSOS_CABECA:
        return vz >= b["head_z_min"]
    if nome in _OSSOS_PESCOCO:
        return b["neck_z_min"] <= vz <= b["neck_z_max"] and abs_x <= b["neck_max_x"]
    if nome in _OSSOS_TRONCO:
        if abs_x > b["tronco_max_x"] and vz >= b["arm_z_cut_lo"]:
            return False
        if nome == "Chest":
            return b["chest_z_min"] <= vz <= b["chest_z_max"]
        if nome == "UpperTorso":
            return b["upper_torso_z_min"] <= vz <= b["chest_z_max"]
        if nome == "Spine1":
            return b["spine1_z_min"] <= vz <= b["spine1_z_max"]
        if nome == "Spine":
            return b["spine_z_min"] <= vz <= b["spine_z_max"]
        if nome in ("Hips", "LowerTorso"):
            return vz <= b["hips_z_max"]
    return True


def _osso_permitido_semente(
    nome: str,
    v: Vector,
    m: dict,
    bracos_baixos: bool,
    tem_neck: bool = True,
    lim: dict[str, float] | None = None,
) -> bool:
    """Filtro anatômico estrito para impedir sementes geodésicas de cruzar vão aéreo."""
    b = lim if lim is not None else _limites_anatomicos(m, tem_neck=tem_neck)
    if not _osso_permitido(nome, v, m, bracos_baixos, tem_neck=tem_neck, lim=b):
        return False
    h = b["h"]
    abs_x = abs(v.x)

    if nome in _OSSOS_PERNA:
        if v.z > m["leg_top_z"] + 0.02 * h or abs_x > b["perna_max_x"]:
            return False
        if nome in _OSSOS_PE:
            return v.z <= m["ankle_z"] + 0.06 * h
        if nome in _OSSOS_CANELA:
            return v.z <= m["knee_z"] + 0.04 * h
        return True

    if nome in _OSSOS_OMBROS:
        return v.z >= m["shoulder_z"] - 0.08 * h and b["ombro_min_x"] <= abs_x <= b["ombro_max_x"]
    if nome in _OSSOS_BRACO_DISTAL:
        return abs_x >= b["arm_root_x"]

    if nome in _OSSOS_CABECA:
        return abs_x <= max(b["neck_max_x"], 0.12 * h)
    if nome in _OSSOS_PESCOCO:
        return abs_x <= b["neck_max_x"]
    if nome in _OSSOS_TRONCO:
        if abs_x > max(b["torso_hw"] * 1.25, 0.12 * h):
            return False
        return m["leg_top_z"] - 0.02 * h <= v.z <= m["chest_top_z"] + 0.03 * h

    return True


def _ilhas_vertices(bm) -> list[list[int]]:
    """Particiona vértices da malha em ilhas conexas via travessia de arestas bmesh."""
    bm.verts.index_update()
    bm.verts.ensure_lookup_table()
    n = len(bm.verts)
    visitado = bytearray(n)
    ilhas: list[list[int]] = []
    for i in range(n):
        if visitado[i]:
            continue
        visitado[i] = 1
        ilha = [i]
        fila = [i]
        pos = 0
        while pos < len(fila):
            vi = fila[pos]
            pos += 1
            v = bm.verts[vi]
            for e in v.link_edges:
                vj = e.other_vert(v).index
                if not visitado[vj]:
                    visitado[vj] = 1
                    fila.append(vj)
                    ilha.append(vj)
        ilhas.append(ilha)
    ilhas.sort(key=len, reverse=True)
    return ilhas


def _grafo_superficie(bm) -> list[list[tuple[int, float]]]:
    """Constrói grafo de adjacência de superfície em espaço de objeto: adj[vi] = [(vj, comp), ...]."""
    bm.verts.index_update()
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    adj: list[list[tuple[int, float]]] = [[] for _ in range(len(bm.verts))]
    for e in bm.edges:
        v0, v1 = e.verts[0], e.verts[1]
        i, j = v0.index, v1.index
        if i == j:
            continue
        comp = (v0.co - v1.co).length
        adj[i].append((j, comp))
        adj[j].append((i, comp))
    return adj


def _projecao_segmento(p: Vector, a: Vector, b: Vector) -> tuple[float, float]:
    ab = b - a
    comp2 = ab.length_squared
    if comp2 <= 1e-12:
        return (p - a).length, 0.5
    t = max(0.0, min(1.0, (p - a).dot(ab) / comp2))
    return (p - (a + ab * t)).length, t


def _sementes_osso_ilha(
    ilha: list[int],
    adj: list[list[tuple[int, float]]],
    coords: list[Vector],
    coords_xyz: list[tuple[float, float, float]],
    o: dict,
    m: dict,
    bracos_baixos: bool,
    e_ilha_central: bool,
    tem_lado_l: bool,
    tem_lado_r: bool,
    d_global_min: float | None = None,
    tem_neck: bool = True,
    lim: dict[str, float] | None = None,
) -> dict[int, float]:
    """Seleciona sementes anatômicas multi-quadrante na superfície da ilha para um osso."""
    nome = o["nome"]
    if nome in _RAIZES:
        return {}
    if nome in _OSSOS_TRONCO and not e_ilha_central:
        return {}
    lado = _lado_osso(nome)
    if lado == "L" and not tem_lado_l:
        return {}
    if lado == "R" and not tem_lado_r:
        return {}

    b = lim if lim is not None else _limites_anatomicos(m, tem_neck=tem_neck)
    h = b["h"]
    x_tol = b["x_tol_leg"] if nome in _OSSOS_PERNA else b["x_tol"]
    arm_z_cut = b["arm_z_cut"]
    arm_z_min = b["arm_z_min"]
    leg_top_lim = m["leg_top_z"] + 0.02 * h
    perna_max_x = b["perna_max_x"]
    braco_min_x = b["arm_root_x"]
    ombro_min_x = b["ombro_min_x"]
    ombro_max_x = b["ombro_max_x"]
    ombro_z_lo = max(b["arm_z_cut_lo"], m["shoulder_z"] - 0.08 * h)
    ombro_z_hi = m["chest_top_z"] + 0.025 * h
    tronco_seed_max_x = max(b["torso_hw"] * 1.25, 0.12 * h)
    neck_max_x = b["neck_max_x"]

    # Classifica osso para filtro escalar rápido por vértice
    if nome in _OSSOS_PERNA:
        cat = 1
        if nome in _OSSOS_PE:
            z_lim_perna = min(leg_top_lim, m["ankle_z"] + 0.06 * h)
            z_lo_perna = b["z_min_floor"]
        elif nome in _OSSOS_CANELA:
            z_lim_perna = min(leg_top_lim, m["knee_z"] + 0.04 * h)
            z_lo_perna = b["z_min_floor"]
        else:
            z_lim_perna = leg_top_lim
            z_lo_perna = m["knee_z"] - 0.04 * h
    elif nome in _OSSOS_OMBROS:
        cat = 2
        z_lim_perna = z_lo_perna = 0.0
    elif nome in _OSSOS_BRACO_DISTAL:
        cat = 3
        z_lim_perna = z_lo_perna = 0.0
    elif nome in _OSSOS_CABECA:
        cat = 5
        z_tr_lo, z_tr_hi = b["head_z_min"], m["z_max"] + 0.01 * h
        z_lim_perna = z_lo_perna = 0.0
    elif nome in _OSSOS_PESCOCO:
        cat = 6
        z_tr_lo, z_tr_hi = b["neck_z_min"], b["neck_z_max"]
        z_lim_perna = z_lo_perna = 0.0
    elif nome in _OSSOS_TRONCO:
        cat = 4
        z_lim_perna = z_lo_perna = 0.0
        if nome == "Chest":
            z_tr_lo, z_tr_hi = b["chest_z_min"], m["chest_top_z"] + 0.03 * h
        elif nome == "UpperTorso":
            z_tr_lo, z_tr_hi = b["upper_torso_z_min"], m["chest_top_z"] + 0.03 * h
        elif nome == "Spine1":
            z_tr_lo, z_tr_hi = b["spine1_z_min"], b["spine1_z_max"]
        elif nome == "Spine":
            z_tr_lo, z_tr_hi = b["spine_z_min"], b["spine_z_max"]
        else:
            z_tr_lo, z_tr_hi = m["leg_top_z"] - 0.02 * h, b["hips_z_max"]
    else:
        cat = 0
        z_lim_perna = z_lo_perna = 0.0

    ax, ay, az = o["cabeca"]
    bx, by, bz = o["cauda"]
    abx, aby, abz = bx - ax, by - ay, bz - az
    comp2 = abx * abx + aby * aby + abz * abz
    inv_comp2 = (1.0 / comp2) if comp2 > 1e-12 else 0.0
    lado_id = 1 if lado == "L" else (-1 if lado == "R" else 0)

    cands: list[tuple[float, float, int, int]] = []
    for vi in ilha:
        vx, vy, vz = coords_xyz[vi]
        if vx > x_tol and lado_id == -1:
            continue
        if vx < -x_tol and lado_id == 1:
            continue
        abs_x = vx if vx >= 0.0 else -vx
        if cat == 1:
            if vz < z_lo_perna or vz > z_lim_perna or abs_x > perna_max_x:
                continue
        elif cat == 2:
            if vz < ombro_z_lo or vz > ombro_z_hi or abs_x < ombro_min_x or abs_x > ombro_max_x:
                continue
        elif cat == 3:
            if abs_x < braco_min_x:
                continue
            if vz < arm_z_cut and not (bracos_baixos and vz >= arm_z_min):
                continue
        elif cat == 4:
            if abs_x > tronco_seed_max_x or vz < z_tr_lo or vz > z_tr_hi:
                continue
        elif cat == 5:
            if vz < z_tr_lo or vz > z_tr_hi or abs_x > max(neck_max_x, 0.12 * h):
                continue
        elif cat == 6:
            if vz < z_tr_lo or vz > z_tr_hi or abs_x > neck_max_x:
                continue

        if inv_comp2 > 0.0:
            t_proj = ((vx - ax) * abx + (vy - ay) * aby + (vz - az) * abz) * inv_comp2
            if t_proj < 0.0:
                t_proj = 0.0
            elif t_proj > 1.0:
                t_proj = 1.0
        else:
            t_proj = 0.5
        px = ax + abx * t_proj
        py = ay + aby * t_proj
        pz = az + abz * t_proj
        dx, dy, dz = vx - px, vy - py, vz - pz
        d2 = dx * dx + dy * dy + dz * dz
        # Quadrante ao redor do osso: 0=+X, 1=-X, 2=+Y, 3=-Y (evita semear só um lado em malhas simétricas)
        adx = dx if dx >= 0.0 else -dx
        ady = dy if dy >= 0.0 else -dy
        if adx >= ady:
            quad = 0 if dx >= 0.0 else 1
        else:
            quad = 2 if dy >= 0.0 else 3
        cands.append((d2, t_proj, quad, vi))

    if not cands:
        return {}

    d2_min, _, _, vi_best = min(cands)
    d_min = math.sqrt(d2_min)
    max_seed_d = 0.25 * h
    if d_min > max_seed_d:
        return {}
    if d_global_min is not None and d_min > max(d_global_min * 1.45, d_global_min + 0.02 * h):
        return {}

    n_fatias = 5
    melhores_quad: list[list[tuple[float, int] | None]] = [[None, None, None, None] for _ in range(n_fatias)]
    for d2, t_proj, quad, vi in cands:
        k = min(n_fatias - 1, int(t_proj * n_fatias))
        atual = melhores_quad[k][quad]
        if atual is None or d2 < atual[0]:
            melhores_quad[k][quad] = (d2, vi)

    escolhidos: list[tuple[float, int]] = []
    limite_fatia = min(max_seed_d, max(d_min * 1.9 + 0.02 * h, d_min + 0.09 * h))
    limite_fatia2 = limite_fatia * limite_fatia
    for fatia in melhores_quad:
        for item in fatia:
            if item is not None and item[0] <= limite_fatia2:
                escolhidos.append((math.sqrt(item[0]), item[1]))
    if not escolhidos:
        escolhidos.append((d_min, vi_best))

    a = Vector(o["cabeca"])
    b = Vector(o["cauda"])
    sementes: dict[int, float] = {}
    for d_s, vi_s in escolhidos:
        if vi_s not in sementes or d_s < sementes[vi_s]:
            sementes[vi_s] = d_s
        limite_anel = d_s * 1.45 + 0.025 * h
        for vj, _comp in adj[vi_s]:
            vj_co = coords[vj]
            if not _osso_permitido(nome, vj_co, m, bracos_baixos):
                continue
            d_j = _dist_ponto_segmento(vj_co, a, b)
            if d_j <= limite_anel and (vj not in sementes or d_j < sementes[vj]):
                sementes[vj] = d_j
    return sementes


def _dijkstra_osso(
    n_verts: int,
    adj: list[list[tuple[int, float]]],
    sementes: dict[int, float],
    limite_dist: float,
) -> list[float]:
    """Executa Dijkstra multi-semente em grafo de superfície com teto opcional de distância."""
    inf = float("inf")
    dist = [inf] * n_verts
    pq: list[tuple[float, int]] = []
    heappush = heapq.heappush
    heappop = heapq.heappop

    for vi, d0 in sementes.items():
        if d0 < dist[vi]:
            dist[vi] = d0
            heappush(pq, (d0, vi))

    while pq:
        d, u = heappop(pq)
        if d > dist[u]:
            continue
        for v, w in adj[u]:
            nd = d + w
            if nd <= limite_dist and nd < dist[v]:
                dist[v] = nd
                heappush(pq, (nd, v))
    return dist


def _normalizar_top4(brutos_wn: list[tuple[float, str]]) -> list[tuple[str, float]]:
    if len(brutos_wn) > 4:
        brutos_wn.sort(reverse=True)
        top = brutos_wn[:4]
    else:
        brutos_wn.sort(reverse=True)
        top = brutos_wn
    soma = sum(w for w, _ in top)
    if soma <= 0.0:
        return [(top[0][1], 1.0)]
    norm = [(n, w / soma) for w, n in top if w / soma >= 1e-4]
    if not norm:
        return [(top[0][1], 1.0)]
    total = sum(w for _, w in norm)
    if abs(total - 1.0) <= 1e-9:
        return norm
    return [(n, w / total) for n, w in norm]


def _pesos_vertice_inverso(
    v: Vector,
    ossos: list[dict],
    m: dict,
    bracos_baixos: bool,
    tem_neck: bool = True,
    lim: dict[str, float] | None = None,
) -> list[tuple[str, float]]:
    b = lim if lim is not None else _limites_anatomicos(m, tem_neck=tem_neck)
    h = b["h"]
    eps = max(0.015 * h, 1e-4)
    brutos_wn: list[tuple[float, str]] = []
    for o in ossos:
        nome = o["nome"]
        if not _osso_permitido(nome, v, m, bracos_baixos, tem_neck=tem_neck, lim=b):
            continue
        d = _dist_ponto_segmento(v, Vector(o["cabeca"]), Vector(o["cauda"]))
        if nome in _OSSOS_OMBROS and abs(v.x) < b["arm_root_x"]:
            d += (b["arm_root_x"] - abs(v.x)) * 1.8
        brutos_wn.append((1.0 / ((d + eps) ** 4), nome))

    if not brutos_wn:
        # Fallback absoluto: osso deformador mais próximo sem máscara
        melhor = min(
            (o for o in ossos if o["nome"] not in _RAIZES),
            key=lambda o: _dist_ponto_segmento(v, Vector(o["cabeca"]), Vector(o["cauda"])),
        )
        return [(melhor["nome"], 1.0)]

    return _normalizar_top4(brutos_wn)


def _pesos_ilha_geodesicos(
    ilha: list[int],
    adj: list[list[tuple[int, float]]],
    coords: list[Vector],
    coords_xyz: list[tuple[float, float, float]],
    ossos: list[dict],
    m: dict,
    bracos_baixos: bool,
    globais_min: dict[str, float] | None = None,
) -> dict[int, list[tuple[str, float]]] | None:
    """Calcula pesos geodésicos intra-ilha via Dijkstra; devolve None se nenhum osso existir na ilha."""
    tem_neck = any(o["nome"] == "Neck" for o in ossos)
    b = _limites_anatomicos(m, tem_neck=tem_neck)
    h = b["h"]
    x_tol = b["x_tol"]
    x_tol_leg = b["x_tol_leg"]
    e_ilha_central = any(abs(coords[vi].x) <= 0.05 * h for vi in ilha)
    tem_lado_l = any(coords[vi].x > x_tol for vi in ilha)
    tem_lado_r = any(coords[vi].x < -x_tol for vi in ilha)

    sementes_por_osso: list[tuple[str, dict[int, float]]] = []
    for o in ossos:
        nome = o["nome"]
        sem = _sementes_osso_ilha(
            ilha,
            adj,
            coords,
            coords_xyz,
            o,
            m,
            bracos_baixos,
            e_ilha_central,
            tem_lado_l,
            tem_lado_r,
            d_global_min=globais_min.get(nome) if globais_min else None,
            tem_neck=tem_neck,
            lim=b,
        )
        if sem:
            sementes_por_osso.append((nome, sem))

    if not sementes_por_osso:
        return None

    n_verts = len(coords)
    limite = 0.48 * h
    dist_mapas: list[tuple[str, list[float]]] = [
        (nome, _dijkstra_osso(n_verts, adj, sem, limite))
        for nome, sem in sementes_por_osso
    ]

    inf = float("inf")
    arm_z_cut = b["arm_z_cut"]
    arm_z_cut_lo = b["arm_z_cut_lo"]
    arm_z_min = b["arm_z_min"]
    ombro_min_x = b["ombro_min_x"]
    ombro_z_hi = m["chest_top_z"] + 0.025 * h
    arm_root_x = b["arm_root_x"]
    arm_deltoid_x = b["arm_deltoid_x"]
    braco_baixo_min_x = b["braco_baixo_min_x"]
    tronco_max_x = b["tronco_max_x"]
    neck_max_x = b["neck_max_x"]
    head_z_min = b["head_z_min"]
    neck_z_min = b["neck_z_min"]
    neck_z_max = b["neck_z_max"]
    chest_z_min = b["chest_z_min"]
    upper_torso_z_min = b["upper_torso_z_min"]
    chest_z_max = b["chest_z_max"]
    spine1_z_min = b["spine1_z_min"]
    spine1_z_max = b["spine1_z_max"]
    spine_z_min = b["spine_z_min"]
    spine_z_max = b["spine_z_max"]
    hips_z_max = b["hips_z_max"]
    leg_z_max = b["leg_z_max"]
    upper_leg_z_min = b["upper_leg_z_min"]
    lower_leg_z_max = b["lower_leg_z_max"]
    foot_z_max = b["foot_z_max"]
    z_min_floor = b["z_min_floor"]

    def _construir_meta(mapas: list[tuple[str, list[float]]]) -> list[tuple[str, list[float], int, int]]:
        meta: list[tuple[str, list[float], int, int]] = []
        # lado_id: 0=C, 1=L, -1=R
        # cat_id: 0=outro, 1=coxa, 2=canela, 3=pe, 4=ombro, 5=braco_distal,
        #         6=cabeca, 7=pescoco, 8=chest, 9=upper_torso, 10=spine1, 11=spine, 12=hips
        for nome, dist_v in mapas:
            lado = _lado_osso(nome)
            lado_id = 1 if lado == "L" else (-1 if lado == "R" else 0)
            if nome in _OSSOS_COXA:
                cat_id = 1
            elif nome in _OSSOS_CANELA:
                cat_id = 2
            elif nome in _OSSOS_PE:
                cat_id = 3
            elif nome in _OSSOS_OMBROS:
                cat_id = 4
            elif nome in _OSSOS_BRACO_DISTAL:
                cat_id = 5
            elif nome in _OSSOS_CABECA:
                cat_id = 6
            elif nome in _OSSOS_PESCOCO:
                cat_id = 7
            elif nome == "Chest":
                cat_id = 8
            elif nome == "UpperTorso":
                cat_id = 9
            elif nome == "Spine1":
                cat_id = 10
            elif nome == "Spine":
                cat_id = 11
            elif nome in ("Hips", "LowerTorso"):
                cat_id = 12
            else:
                cat_id = 0
            meta.append((nome, dist_v, lado_id, cat_id))
        return meta

    bones_meta = _construir_meta(dist_mapas)
    eps = max(0.015 * h, 1e-4)
    saida: dict[int, list[tuple[str, float]]] = {}
    sem_alcance: list[int] = []

    for vi in ilha:
        vx, _vy, vz = coords_xyz[vi]
        abs_x = vx if vx >= 0.0 else -vx
        brutos_wn: list[tuple[float, str]] = []
        for nome, dist_v, lado_id, cat_id in bones_meta:
            d = dist_v[vi]
            if d >= inf:
                continue
            lat_tol = x_tol_leg if 1 <= cat_id <= 3 else x_tol
            if vx > lat_tol and lado_id == -1:
                continue
            if vx < -lat_tol and lado_id == 1:
                continue
            if cat_id == 1:
                if vz < upper_leg_z_min or vz > leg_z_max:
                    continue
            elif cat_id == 2:
                if vz < z_min_floor or vz > lower_leg_z_max:
                    continue
            elif cat_id == 3:
                if vz > foot_z_max:
                    continue
            elif cat_id == 4:
                if vz < arm_z_cut_lo or vz > ombro_z_hi or abs_x < ombro_min_x:
                    continue
                if e_ilha_central and abs_x < arm_deltoid_x:
                    d += (arm_deltoid_x - abs_x) * 3.0
            elif cat_id == 5:
                if abs_x <= x_tol:
                    continue
                if vz >= arm_z_cut:
                    if abs_x < arm_root_x:
                        continue
                    if e_ilha_central and abs_x < arm_deltoid_x:
                        d += (arm_deltoid_x - abs_x) * 4.5
                elif not (bracos_baixos and abs_x > braco_baixo_min_x and vz >= arm_z_min):
                    continue
            elif cat_id == 6:
                if vz < head_z_min:
                    continue
            elif cat_id == 7:
                if vz < neck_z_min or vz > neck_z_max or abs_x > neck_max_x:
                    continue
            elif cat_id >= 8:
                if abs_x > tronco_max_x and vz >= arm_z_cut_lo:
                    continue
                if cat_id == 8 and (vz < chest_z_min or vz > chest_z_max):
                    continue
                if cat_id == 9 and (vz < upper_torso_z_min or vz > chest_z_max):
                    continue
                if cat_id == 10 and (vz < spine1_z_min or vz > spine1_z_max):
                    continue
                if cat_id == 11 and (vz < spine_z_min or vz > spine_z_max):
                    continue
                if cat_id == 12 and vz > hips_z_max:
                    continue
            de = d + eps
            de2 = de * de
            brutos_wn.append((1.0 / (de2 * de2), nome))
        if brutos_wn:
            saida[vi] = _normalizar_top4(brutos_wn)
        else:
            sem_alcance.append(vi)

    if sem_alcance:
        sem_map = dict(sementes_por_osso)
        fronteira: set[int] = set()
        for vi in sem_alcance:
            for vj, _comp in adj[vi]:
                fronteira.add(vj)
        ossos_tronco_base = {"Hips", "LowerTorso", "Spine", "Spine1", "Chest", "UpperTorso"}
        recalcular = {
            nome
            for nome, dist_v, _lado_id, _cat_id in bones_meta
            if (
                nome in ossos_tronco_base
                or any(dist_v[vj] < inf for vj in fronteira)
            )
            and any(_osso_permitido(nome, coords[vi], m, bracos_baixos, tem_neck=tem_neck, lim=b) for vi in sem_alcance)
        }
        # Não deixar perna/braço cruzar tronco inteiro até capas/saias quando algum osso de tronco alcança
        tronco_recalc = recalcular & ossos_tronco_base
        if tronco_recalc:
            recalcular = {
                nome
                for nome in recalcular
                if nome in ossos_tronco_base
                or any(
                    _osso_permitido(nome, coords[vi], m, bracos_baixos, tem_neck=tem_neck, lim=b)
                    and not any(
                        _osso_permitido(tb, coords[vi], m, bracos_baixos, tem_neck=tem_neck, lim=b)
                        for tb in tronco_recalc
                    )
                    for vi in sem_alcance
                )
            }
        if recalcular:
            dist_mapas = [
                (
                    nome,
                    _dijkstra_osso(n_verts, adj, sem_map[nome], inf)
                    if nome in recalcular
                    else dist_v,
                )
                for nome, dist_v in dist_mapas
            ]
            bones_meta = _construir_meta(dist_mapas)

        for vi in sem_alcance:
            vx, _vy, _vz = coords_xyz[vi]
            abs_x = vx if vx >= 0.0 else -vx
            brutos_wn = []
            for nome, dist_v, _lado_id, cat_id in bones_meta:
                d = dist_v[vi]
                if d >= inf or not _osso_permitido(nome, coords[vi], m, bracos_baixos, tem_neck=tem_neck, lim=b):
                    continue
                if cat_id in (4, 5) and e_ilha_central and abs_x < arm_deltoid_x:
                    fator_att = 3.0 if cat_id == 4 else 4.5
                    d += (arm_deltoid_x - abs_x) * fator_att
                de = d + eps
                de2 = de * de
                brutos_wn.append((1.0 / (de2 * de2), nome))
            if brutos_wn:
                saida[vi] = _normalizar_top4(brutos_wn)
            else:
                saida[vi] = _pesos_vertice_inverso(coords[vi], ossos, m, bracos_baixos, tem_neck=tem_neck, lim=b)

    return saida


def _osso_acessorio_ilha(
    ilha: list[int],
    coords: list[Vector],
    coords_xyz: list[tuple[float, float, float]],
    ossos: list[dict],
    m: dict,
    bracos_baixos: bool,
    ilha_principal: list[int] | None,
    pesos_principais: dict[int, list[tuple[str, float]]],
) -> str:
    """Escolhe um único osso coerente para ilha desconexa pequena (armadura/pouch/acessório)."""
    c = _centroide([coords[vi] for vi in ilha], Vector((0.0, 0.0, 0.0)))
    cx, cy, cz = c.x, c.y, c.z
    tem_neck = any(o["nome"] == "Neck" for o in ossos)
    b = _limites_anatomicos(m, tem_neck=tem_neck)
    h = b["h"]
    if ilha_principal and pesos_principais:
        d2_min = float("inf")
        vi_main = ilha_principal[0]
        for vj in ilha_principal:
            vx, vy, vz = coords_xyz[vj]
            dx, dy, dz = vx - cx, vy - cy, vz - cz
            d2 = dx * dx + dy * dy + dz * dz
            if d2 < d2_min:
                d2_min = d2
                vi_main = vj
        if d2_min <= (0.12 * h) ** 2:
            for nome, _peso in pesos_principais.get(vi_main, ()):
                if _osso_permitido(nome, c, m, bracos_baixos, tem_neck=tem_neck, lim=b):
                    return nome

    validos = [o for o in ossos if o["nome"] not in _RAIZES and _osso_permitido(o["nome"], c, m, bracos_baixos, tem_neck=tem_neck, lim=b)]
    if not validos:
        validos = [o for o in ossos if o["nome"] not in _RAIZES]
    melhor = min(validos, key=lambda o: _dist_ponto_segmento(c, Vector(o["cabeca"]), Vector(o["cauda"])))
    return melhor["nome"]


def _atribuir_pesos_inverso(
    obj,
    ossos: list[dict],
    m: dict,
    indices: list[int] | None = None,
) -> None:
    bracos_baixos = (
        m["braco_L"]["tip"].z < m["shoulder_z"] - 0.12 * m["altura"]
        or m["braco_R"]["tip"].z < m["shoulder_z"] - 0.12 * m["altura"]
    )
    grupos_obj = {}
    for o in ossos:
        if o["nome"] in _RAIZES:
            continue
        vg = obj.vertex_groups.get(o["nome"]) or obj.vertex_groups.new(name=o["nome"])
        grupos_obj[o["nome"]] = vg

    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        bm.verts.index_update()
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        coords = [v.co.copy() for v in bm.verts]
        ilhas = _ilhas_vertices(bm)
        adj = _grafo_superficie(bm)
    finally:
        bm.free()

    n_total = len(coords)
    if n_total == 0:
        return
    coords_xyz = [(v.x, v.y, v.z) for v in coords]

    h = m["altura"]
    tem_neck = any(o["nome"] == "Neck" for o in ossos)
    lim_anat = _limites_anatomicos(m, tem_neck=tem_neck)
    tem_ilha_principal = len(ilhas[0]) > 0.40 * n_total
    globais_min: dict[str, float] | None = None
    if len(ilhas) > 1 and not tem_ilha_principal:
        globais_min = {}
        for o in ossos:
            nome = o["nome"]
            if nome in _RAIZES:
                continue
            a = Vector(o["cabeca"])
            b = Vector(o["cauda"])
            d_best = float("inf")
            for _vi, v in enumerate(coords):
                if _osso_permitido_semente(nome, v, m, bracos_baixos, tem_neck=tem_neck, lim=lim_anat):
                    d_v = _dist_ponto_segmento(v, a, b)
                    if d_v < d_best:
                        d_best = d_v
            if d_best < float("inf"):
                globais_min[nome] = d_best

    pesos_por_vertice: dict[int, list[tuple[str, float]]] = {}
    ossos_por_nome = {o["nome"]: o for o in ossos}
    hands_pos = [
        (hn, Vector(ossos_por_nome[hn]["cabeca"]))
        for hn in ("Hand.L", "Hand.R", "LeftHand", "RightHand")
        if hn in ossos_por_nome
    ]

    for idx_ilha, ilha in enumerate(ilhas):
        xs = [coords_xyz[vi][0] for vi in ilha]
        ys = [coords_xyz[vi][1] for vi in ilha]
        zs = [coords_xyz[vi][2] for vi in ilha]
        diag = Vector((max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))).length

        eh_roupa_bilateral = (
            tem_ilha_principal
            and idx_ilha > 0
            and min(xs) < -0.045 * h
            and max(xs) > 0.045 * h
            and diag >= 0.22 * h
        )
        arma_mao_osso: str | None = None
        if idx_ilha == 0:
            e_acessorio = False
        elif tem_ilha_principal:
            e_acessorio = (not eh_roupa_bilateral) and (
                (len(ilha) < 0.12 * n_total) or (diag < 0.22 * h)
            )
            if not e_acessorio and diag < 0.90 * h and hands_pos:
                unilateral = min(xs) > 0.14 * h or max(xs) < -0.14 * h
                if unilateral:
                    d_hand = min(
                        (hn, min((coords[vi] - hp).length for vi in ilha))
                        for hn, hp in hands_pos
                    )
                    if d_hand[1] < 0.14 * h:
                        e_acessorio = True
                        arma_mao_osso = d_hand[0]
        else:
            e_acessorio = diag < 0.18 * h

        calculados = None if e_acessorio else _pesos_ilha_geodesicos(
            ilha, adj, coords, coords_xyz, ossos, m, bracos_baixos, globais_min=globais_min
        )
        if calculados is not None:
            pesos_por_vertice.update(calculados)
        elif eh_roupa_bilateral and ilhas[0]:
            passo_ref = max(1, len(ilhas[0]) // 800)
            amostra_corpo = ilhas[0][::passo_ref]
            for vi in ilha:
                cx, cy_v, cz = coords_xyz[vi]
                melhor_vb = amostra_corpo[0]
                melhor_d2 = float("inf")
                for vb in amostra_corpo:
                    bx, by_v, bz = coords_xyz[vb]
                    d2 = (cx - bx) ** 2 + (cy_v - by_v) ** 2 + (cz - bz) ** 2
                    if d2 < melhor_d2:
                        melhor_d2 = d2
                        melhor_vb = vb
                pesos_por_vertice[vi] = list(
                    pesos_por_vertice.get(melhor_vb, [(ossos[0]["nome"], 1.0)])
                )
        else:
            osso_unico = arma_mao_osso or _osso_acessorio_ilha(
                ilha,
                coords,
                coords_xyz,
                ossos,
                m,
                bracos_baixos,
                ilhas[0] if tem_ilha_principal and idx_ilha > 0 else None,
                pesos_por_vertice,
            )
            for vi in ilha:
                pesos_por_vertice[vi] = [(osso_unico, 1.0)]

    # Suavizacao central apenas quando existe ponte continua de saia/tunica abaixo da virilha
    crotch_z = float(m.get("crotch_z", m["hip_z"]))
    z0_m = float(m.get("z_min", 0.0))
    tem_saia_central = any(
        (z0_m + 0.12 * h < coords_xyz[vi][2] < crotch_z - 0.02 * h)
        and abs(coords_xyz[vi][0]) < 0.022 * h
        for vi in ilhas[0]
    )
    if tem_saia_central:
        banda_costura = [
            vi
            for vi in ilhas[0]
            if (z0_m + 0.08 * h < coords_xyz[vi][2] < crotch_z)
            and abs(coords_xyz[vi][0]) <= 0.042 * h
        ]
        for _ in range(2):
            novos_pesos: dict[int, list[tuple[str, float]]] = {}
            for vi in banda_costura:
                acum: dict[str, float] = {n: w * 0.5 for n, w in pesos_por_vertice.get(vi, ())}
                viz = adj[vi]
                if viz:
                    peso_v = 0.5 / float(len(viz))
                    for vj in viz:
                        for n, w in pesos_por_vertice.get(vj, ()):
                            acum[n] = acum.get(n, 0.0) + w * peso_v
                novos_pesos[vi] = _normalizar_top4([(w, n) for n, w in acum.items()])
            pesos_por_vertice.update(novos_pesos)
        # Mantem isolamento lateral estrito fora da faixa central (<= 0.045 para lado oposto)
        for vi in range(n_total):
            vx = coords_xyz[vi][0]
            if abs(vx) > 0.042 * h:
                lado_opp = "R" if vx > 0.0 else "L"
                filtrados = [
                    (n, min(w, 0.045) if _lado_osso(n) == lado_opp else w)
                    for n, w in pesos_por_vertice.get(vi, ())
                ]
                if filtrados:
                    pesos_por_vertice[vi] = _normalizar_top4([(w, n) for n, w in filtrados])

    def _perm_humano(nome_osso: str, vi_idx: int) -> bool:
        return _osso_permitido(nome_osso, coords[vi_idx], m, bracos_baixos, tem_neck=tem_neck, lim=lim_anat)

    _suavizar_aneis_juntas(
        adj,
        pesos_por_vertice,
        ossos,
        permitido_fn=_perm_humano,
        passos=2,
        alpha=0.32,
        pares_bloqueados={
            frozenset(("Chest", "Head")),
            frozenset(("UpperTorso", "Head")),
            frozenset(("Chest", "Neck")),
        },
    )

    cabelo_slots = {
        idx
        for idx, mat in enumerate(obj.data.materials)
        if mat is not None and str(mat.name).startswith("makehuman_cabelo")
    }
    if cabelo_slots and "Head" in grupos_obj:
        verts_cabelo = {
            vi
            for poly in obj.data.polygons
            if poly.material_index in cabelo_slots
            for vi in poly.vertices
        }
        for vi in verts_cabelo:
            pesos_por_vertice[vi] = [("Head", 1.0)]

    alvo = indices if indices is not None else range(n_total)
    for vi in alvo:
        for nome, peso in pesos_por_vertice.get(vi, ()):
            grupos_obj[nome].add([vi], peso, "REPLACE")


def _normalizar_grupos_e_mapear(obj) -> dict[str, list[int]]:
    """Limita a 4 influências por vértice, normaliza soma = 1.0 e devolve osso -> índices."""
    for vg in list(obj.vertex_groups):
        if vg.name in _RAIZES:
            obj.vertex_groups.remove(vg)
    vgs = {vg.index: vg for vg in obj.vertex_groups}
    mapa: dict[str, list[int]] = {}
    for v in obj.data.vertices:
        pares = []
        zerados = []
        for g in v.groups:
            vg = vgs.get(g.group)
            if vg is None:
                continue
            if g.weight <= 1e-6:
                zerados.append(vg)
            else:
                pares.append((vg, float(g.weight)))
        for vg in zerados:
            vg.remove([v.index])
        if not pares:
            continue
        if len(pares) > 4:
            pares.sort(key=lambda item: item[1], reverse=True)
            manter = pares[:4]
            for vg, _w in pares[4:]:
                vg.remove([v.index])
        else:
            manter = pares
        soma = sum(w for _, w in manter)
        if soma > 0.0:
            if abs(soma - 1.0) > 1e-5:
                for vg, w in manter:
                    wn = w / soma
                    vg.add([v.index], wn, "REPLACE")
            for vg, _w in manter:
                mapa.setdefault(vg.name, []).append(v.index)
    return {k: sorted(v) for k, v in mapa.items() if v}


def _suavizar_aneis_juntas(
    adj: list[list[tuple[int, float]]],
    pesos_por_vertice: dict[int, list[tuple[str, float]]],
    ossos: list[dict],
    permitido_fn=None,
    passos: int = 2,
    alpha: float = 0.32,
    pares_bloqueados: set[frozenset[str]] | None = None,
) -> None:
    """Suaviza pesos apenas nos aneis de fronteira entre ossos pai-filho adjacentes."""
    if not pesos_por_vertice:
        return
    pai_map = {o["nome"]: o["pai"] for o in ossos if o.get("pai")}
    bloqueados = pares_bloqueados or set()

    def _junta_valida(a: str, b: str) -> bool:
        if a == b:
            return True
        if frozenset((a, b)) in bloqueados:
            return False
        return pai_map.get(a) == b or pai_map.get(b) == a

    dom = {vi: ws[0][0] for vi, ws in pesos_por_vertice.items() if ws}
    fronteira: set[int] = set()
    for vi, d_i in dom.items():
        for vj, _c in adj[vi]:
            d_j = dom.get(vj)
            if d_j and d_j != d_i and _junta_valida(d_i, d_j):
                fronteira.add(vi)
                break
    if not fronteira:
        return

    anel: set[int] = set(fronteira)
    for vi in fronteira:
        d_i = dom.get(vi)
        if not d_i:
            continue
        for vj, _c in adj[vi]:
            d_j = dom.get(vj)
            if d_j and _junta_valida(d_i, d_j):
                anel.add(vj)

    for _ in range(passos):
        novos: dict[int, list[tuple[str, float]]] = {}
        for vi in anel:
            ws_i = pesos_por_vertice.get(vi)
            if not ws_i:
                continue
            d_i = ws_i[0][0]
            viz_list = adj[vi]
            if not viz_list:
                continue
            acum: dict[str, float] = {n: w * (1.0 - alpha) for n, w in ws_i}
            fator = alpha / float(len(viz_list))
            for vj, _c in viz_list:
                for n, w in pesos_por_vertice.get(vj, ()):
                    if not _junta_valida(d_i, n):
                        continue
                    if permitido_fn is not None and not permitido_fn(n, vi):
                        continue
                    acum[n] = acum.get(n, 0.0) + w * fator
            novos[vi] = _normalizar_top4([(w, n) for n, w in acum.items() if w > 1e-6])
        for vi, ws_novo in novos.items():
            if ws_novo:
                pesos_por_vertice[vi] = ws_novo


_MAT_BL_PARA_GLTF_LINHAS = ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0), (0.0, -1.0, 0.0))

_SOCKETS_MAPA: dict[str, tuple[str, ...]] = {
    "Hand.R": ("Hand.R", "RightHand"),
    "Hand.L": ("Hand.L", "LeftHand"),
    "Back": ("Chest", "UpperTorso"),
    "Head": ("Head",),
    "Shoulder.L": ("Shoulder.L", "LeftUpperArm"),
    "Shoulder.R": ("Shoulder.R", "RightUpperArm"),
    "MountSeat": ("MountSeat",),
}

_SOCKETS_ALIASES_PARTE: dict[str, str] = {
    "arma": "Hand.R",
    "orbe": "Hand.L",
    "escudo": "Hand.L",
    "capa": "Back",
    "mochila": "Back",
    "asas": "Back",
    "elmo": "Head",
    "ombreiras": "Shoulder.L",
    "sela": "MountSeat",
}


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
            escala_mao = max(vetor_mao.length, 0.05) / 0.10
            # Centro do tunel de empunhadura (punho fechado): ~0.42*(tail-head) + offset palmar (+Y_bl/-Z_bl)
            delta_bl = vetor_mao * 0.42 + (
                m_bone_3x3 @ Vector((0.004 * escala_mao, 0.0, 0.015 * escala_mao))
            )
        elif nome_socket == "Hand.L":
            vetor_mao = osso.tail_local - osso.head_local
            escala_mao = max(vetor_mao.length, 0.05) / 0.10
            # Centro proximo da palma em concha (orbe): ~0.38*(tail-head) + offset palmar compacto
            delta_bl = vetor_mao * 0.38 + (
                m_bone_3x3 @ Vector((-0.003 * escala_mao, 0.0, 0.014 * escala_mao))
            )
        elif nome_socket == "Back":
            meio_osso = (osso.head_local + osso.tail_local) * 0.5
            dorsal_y = -0.14
            if verts_mesh:
                faixa_z = [
                    v for v in verts_mesh
                    if abs(v.z - meio_osso.z) <= max(0.14, osso.length * 0.9) and abs(v.x) <= 0.18
                ]
                if faixa_z:
                    min_y = min(v.y for v in faixa_z)
                    if e_criatura:
                        max_z_dorso = max(v.z for v in faixa_z)
                        delta_bl = Vector((0.0, 0.0, max(0.06, max_z_dorso - meio_osso.z + 0.02)))
                    else:
                        dorsal_y = min(-0.08, min_y - meio_osso.y - 0.02)
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


def _alinhar_orientacao_criatura(obj, com_asas: bool = False) -> None:
    """Orienta criatura/montaria via PCA XY e assimetria cranio-caudal com focinho em +Y_bl."""
    _aplicar_identidade(obj)
    verts = obj.data.vertices
    if not verts:
        return
    pts = [v.co.copy() for v in verts]
    n = float(len(pts))
    mx = sum(p.x for p in pts) / n
    my = sum(p.y for p in pts) / n
    sxx = sum((p.x - mx) ** 2 for p in pts)
    syy = sum((p.y - my) ** 2 for p in pts)
    sxy = sum((p.x - mx) * (p.y - my) for p in pts)
    theta = 0.5 * math.atan2(2.0 * sxy, sxx - syy)
    u1 = Vector((math.cos(theta), math.sin(theta)))
    u2 = Vector((-u1.y, u1.x))

    # Escolhe eixo sagital com maior simetria bilateral no plano XY (crucial em dragoes com asas largas)
    def _score_sagital(eixo_fwd: Vector, eixo_lat: Vector) -> float:
        zs_p: list[float] = []
        zs_n: list[float] = []
        proj_fwd: list[float] = []
        for p in pts:
            dx = p.x - mx
            dy = p.y - my
            pf = dx * eixo_fwd.x + dy * eixo_fwd.y
            pl = dx * eixo_lat.x + dy * eixo_lat.y
            proj_fwd.append(abs(pf))
            if pl >= 0.0:
                zs_p.append(p.z)
            else:
                zs_n.append(p.z)
        if not zs_p or not zs_n:
            return -1e9
        bal_cnt = 1.0 - abs(len(zs_p) - len(zs_n)) / n
        mz_p = sum(zs_p) / len(zs_p)
        mz_n = sum(zs_n) / len(zs_n)
        bal_z = 1.0 / (1.0 + abs(mz_p - mz_n) * 4.0)
        ext_core = sorted(proj_fwd)[int(0.95 * len(proj_fwd))]
        return bal_cnt * 2.0 + bal_z * 3.0 + (0.15 * ext_core if not com_asas else 0.0)

    eixo_fwd = u1 if _score_sagital(u1, u2) >= _score_sagital(u2, u1) else u2
    # Decide sentido do focinho (+Y_bl) vs cauda (-Y_bl): cabeca/pescoco alcancam Z maior na extremidade anterior
    projs = [((p.x - mx) * eixo_fwd.x + (p.y - my) * eixo_fwd.y, p.z) for p in pts]
    p_vals = sorted(pr[0] for pr in projs)
    p_lo, p_hi = p_vals[int(0.02 * len(p_vals))], p_vals[int(0.98 * len(p_vals))]
    meio = 0.5 * (p_lo + p_hi)
    meia = max(0.5 * (p_hi - p_lo), 1e-4)
    ant_zs = [z for p, z in projs if (p - meio) > 0.35 * meia]
    post_zs = [z for p, z in projs if (p - meio) < -0.35 * meia]
    if ant_zs and post_zs:
        ant_zs.sort()
        post_zs.sort()
        top_a = sum(ant_zs[max(0, int(0.8 * len(ant_zs))):]) / max(1, len(ant_zs) - int(0.8 * len(ant_zs)))
        top_p = sum(post_zs[max(0, int(0.8 * len(post_zs))):]) / max(1, len(post_zs) - int(0.8 * len(post_zs)))
        mean_a = sum(ant_zs) / len(ant_zs)
        mean_p = sum(post_zs) / len(post_zs)
        if (top_p + 0.35 * mean_p) > (top_a + 0.35 * mean_a) + 1e-3:
            eixo_fwd = -eixo_fwd

    ang_atual = math.atan2(eixo_fwd.y, eixo_fwd.x)
    rot_z = (math.pi * 0.5) - ang_atual
    # Normaliza angulo para [-pi, pi] e evita rotacao desnecessaria se ja alinhado (< 2 deg)
    rot_z = (rot_z + math.pi) % (2.0 * math.pi) - math.pi
    if abs(rot_z) > math.radians(2.0):
        obj.rotation_euler.z += rot_z
        _aplicar_identidade(obj)

    xs = [v.co.x for v in obj.data.vertices]
    ys = [v.co.y for v in obj.data.vertices]
    zs = [v.co.z for v in obj.data.vertices]
    shift = Vector((-0.5 * (min(xs) + max(xs)), -0.5 * (min(ys) + max(ys)), -min(zs)))
    if shift.length > 1e-5:
        for v in obj.data.vertices:
            v.co += shift
        obj.data.update()


def _estimar_marcos_criatura(obj, com_asas: bool = False) -> dict:
    """Estima marcos anatomicos de quadrupedes e montarias aladas no espaco canonico (+Y frente)."""
    pts = [v.co.copy() for v in obj.data.vertices]
    xs = [p.x for p in pts]
    ys = [p.y for p in pts]
    zs = [p.z for p in pts]
    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)
    z_min, z_max = min(zs), max(zs)
    h = max(z_max - z_min, 1e-3)
    len_y = max(y_max - y_min, 1e-3)
    span_x = max(x_max - x_min, 1e-3)

    core_thresh = 0.24 * len_y if com_asas else 0.48 * span_x
    core = [p for p in pts if abs(p.x) <= max(core_thresh, 0.08 * h)] or pts
    cy_vals = [p.y for p in core]
    y_core_min, y_core_max = min(cy_vals), max(cy_vals)
    core_len = max(y_core_max - y_core_min, 1e-3)
    cy = 0.5 * (y_core_min + y_core_max)

    # Detecta colunas das patas (frente +Y / tras -Y, esquerda +X / direita -X)
    low_pts = [p for p in pts if p.z <= z_min + 0.32 * h and abs(p.x) <= max(0.35 * len_y, 0.25 * span_x)]
    f_l = [p for p in low_pts if p.y > cy and p.x > 0.01 * h]
    f_r = [p for p in low_pts if p.y > cy and p.x < -0.01 * h]
    b_l = [p for p in low_pts if p.y < cy and p.x > 0.01 * h]
    b_r = [p for p in low_pts if p.y < cy and p.x < -0.01 * h]

    x_front = 0.5 * (
        (_mediana([p.x for p in f_l], 0.14 * h) if f_l else 0.14 * h)
        + (_mediana([-p.x for p in f_r], 0.14 * h) if f_r else 0.14 * h)
    )
    x_back = 0.5 * (
        (_mediana([p.x for p in b_l], 0.15 * h) if b_l else 0.15 * h)
        + (_mediana([-p.x for p in b_r], 0.15 * h) if b_r else 0.15 * h)
    )
    x_front = _clamped(x_front, 0.06 * h, 0.35 * len_y)
    x_back = _clamped(x_back, 0.06 * h, 0.35 * len_y)

    y_front_leg = _mediana([p.y for p in (f_l + f_r)], y_core_min + 0.68 * core_len)
    y_back_leg = _mediana([p.y for p in (b_l + b_r)], y_core_min + 0.30 * core_len)
    if y_front_leg <= y_back_leg + 0.12 * core_len:
        y_back_leg = y_core_min + 0.30 * core_len
        y_front_leg = y_core_min + 0.68 * core_len

    # Altura dorsal na regiao da sela
    faixa_sela = [p for p in core if (y_back_leg - 0.05 * core_len) <= p.y <= (y_front_leg + 0.05 * core_len)]
    z_torso_top = max((p.z for p in faixa_sela), default=z_min + 0.62 * h)
    z_torso_mid = _mediana([p.z for p in faixa_sela], z_min + 0.45 * h)
    z_belly = min((p.z for p in faixa_sela if p.z > z_min + 0.15 * h), default=z_min + 0.32 * h)

    # Cabeca e focinho (+Y)
    head_pts = [p for p in core if p.y >= y_front_leg + 0.08 * core_len]
    if not head_pts:
        head_pts = [p for p in core if p.y >= cy + 0.25 * core_len] or core
    y_neck_base = y_front_leg + 0.06 * core_len
    z_neck_base = _clamped(z_torso_mid + 0.08 * h, z_min + 0.35 * h, z_max - 0.15 * h)
    y_snout = max(p.y for p in head_pts)
    y_head_back = max(y_neck_base + 0.06 * core_len, y_snout - 0.20 * core_len)
    z_head = _mediana([p.z for p in head_pts], z_min + 0.72 * h)

    # Cauda (-Y)
    y_tail_base = y_back_leg - 0.04 * core_len
    y_tail_tip = min(y_core_min + 0.02 * core_len, y_tail_base - 0.14 * core_len)
    tail_pts = [p for p in core if p.y <= y_tail_base]
    z_tail_tip = _mediana([p.z for p in tail_pts if p.y <= y_tail_tip + 0.12 * core_len], z_torso_mid - 0.05 * h)

    # Asas laterais
    wing_span = max(abs(x_min), abs(x_max))
    if wing_span < 0.35 * core_len:
        wing_span = 0.75 * core_len
    wing_pts = [p for p in pts if abs(p.x) > max(core_thresh, 0.20 * core_len)]
    z_wing_tip = _mediana([p.z for p in wing_pts if abs(p.x) > 0.70 * wing_span], z_torso_top + 0.18 * h) if wing_pts else z_torso_top + 0.18 * h
    y_wing_tip = _mediana([p.y for p in wing_pts if abs(p.x) > 0.70 * wing_span], y_front_leg - 0.18 * core_len) if wing_pts else y_front_leg - 0.18 * core_len

    return {
        "z_min": z_min,
        "z_max": z_max,
        "altura": h,
        "len_y": len_y,
        "span_x": span_x,
        "cy": cy,
        "y_back_leg": y_back_leg,
        "y_front_leg": y_front_leg,
        "x_front": x_front,
        "x_back": x_back,
        "z_belly": z_belly,
        "z_torso_mid": z_torso_mid,
        "z_torso_top": z_torso_top,
        "y_neck_base": y_neck_base,
        "z_neck_base": z_neck_base,
        "y_head_back": y_head_back,
        "y_snout": y_snout,
        "z_head": z_head,
        "y_tail_base": y_tail_base,
        "y_tail_tip": y_tail_tip,
        "z_tail_tip": z_tail_tip,
        "wing_span": wing_span,
        "y_wing_tip": y_wing_tip,
        "z_wing_tip": z_wing_tip,
    }


def _construir_ossos_criatura(esqueleto: str, m: dict) -> list[dict]:
    """Constroi esqueleto quadruped@1 ou winged_mount@1 no espaco canonico (+Y frente, +Z cima)."""
    z0 = m["z_min"]
    h = m["altura"]
    ml = max(0.01 * h, 1e-3)
    yb = m["y_back_leg"]
    yf = m["y_front_leg"]
    y_spine = 0.55 * yb + 0.45 * yf
    zm = m["z_torso_mid"]
    zt = m["z_torso_top"]
    xf = m["x_front"]
    xb = m["x_back"]
    z_leg_top = _clamped(zm - 0.02 * h, z0 + 0.24 * h, zt - 0.04 * h)
    z_knee_f = z0 + 0.45 * (z_leg_top - z0)
    z_ank_f = z0 + 0.10 * h
    z_knee_b = z0 + 0.52 * (z_leg_top - z0)
    z_ank_b = z0 + 0.14 * h
    foot_fwd = 0.07 * m["len_y"]

    yt0 = m["y_tail_base"]
    yt3 = m["y_tail_tip"]
    yt1 = yt0 + (yt3 - yt0) * 0.33
    yt2 = yt0 + (yt3 - yt0) * 0.67
    zt3 = m["z_tail_tip"]
    zt1 = zm + (zt3 - zm) * 0.33
    zt2 = zm + (zt3 - zm) * 0.67

    ossos = [
        _osso("Root", None, (0.0, 0.0, z0), (0.0, 0.0, z0 + 0.06 * h), ml),
        _osso("Hips", "Root", (0.0, yb, zm), (0.0, y_spine, zm), ml),
        _osso("Spine", "Hips", (0.0, y_spine, zm), (0.0, 0.5 * (y_spine + yf), zm + 0.02 * h), ml),
        _osso("Chest", "Spine", (0.0, 0.5 * (y_spine + yf), zm + 0.02 * h), (0.0, m["y_neck_base"], m["z_neck_base"]), ml),
        _osso("Neck", "Chest", (0.0, m["y_neck_base"], m["z_neck_base"]), (0.0, m["y_head_back"], m["z_head"]), ml),
        _osso("Head", "Neck", (0.0, m["y_head_back"], m["z_head"]), (0.0, m["y_snout"], m["z_head"]), ml),
        _osso("Jaw", "Head", (0.0, m["y_head_back"] + 0.01 * m["len_y"], m["z_head"] - 0.06 * h), (0.0, m["y_snout"] - 0.01 * m["len_y"], m["z_head"] - 0.08 * h), ml),
        _osso("Tail1", "Hips", (0.0, yt0, zm), (0.0, yt1, zt1), ml),
        _osso("Tail2", "Tail1", (0.0, yt1, zt1), (0.0, yt2, zt2), ml),
        _osso("Tail3", "Tail2", (0.0, yt2, zt2), (0.0, yt3, zt3), ml),
        _osso("FrontUpperLeg.L", "Chest", (xf, yf, z_leg_top), (xf, yf - 0.02 * m["len_y"], z_knee_f), ml),
        _osso("FrontLowerLeg.L", "FrontUpperLeg.L", (xf, yf - 0.02 * m["len_y"], z_knee_f), (xf, yf, z_ank_f), ml),
        _osso("FrontFoot.L", "FrontLowerLeg.L", (xf, yf, z_ank_f), (xf, yf + foot_fwd, z0 + 0.02 * h), ml),
        _osso("FrontUpperLeg.R", "Chest", (-xf, yf, z_leg_top), (-xf, yf - 0.02 * m["len_y"], z_knee_f), ml),
        _osso("FrontLowerLeg.R", "FrontUpperLeg.R", (-xf, yf - 0.02 * m["len_y"], z_knee_f), (-xf, yf, z_ank_f), ml),
        _osso("FrontFoot.R", "FrontLowerLeg.R", (-xf, yf, z_ank_f), (-xf, yf + foot_fwd, z0 + 0.02 * h), ml),
        _osso("BackUpperLeg.L", "Hips", (xb, yb, z_leg_top), (xb, yb + 0.03 * m["len_y"], z_knee_b), ml),
        _osso("BackLowerLeg.L", "BackUpperLeg.L", (xb, yb + 0.03 * m["len_y"], z_knee_b), (xb, yb - 0.02 * m["len_y"], z_ank_b), ml),
        _osso("BackFoot.L", "BackLowerLeg.L", (xb, yb - 0.02 * m["len_y"], z_ank_b), (xb, yb + foot_fwd, z0 + 0.02 * h), ml),
        _osso("BackUpperLeg.R", "Hips", (-xb, yb, z_leg_top), (-xb, yb + 0.03 * m["len_y"], z_knee_b), ml),
        _osso("BackLowerLeg.R", "BackUpperLeg.R", (-xb, yb + 0.03 * m["len_y"], z_knee_b), (-xb, yb - 0.02 * m["len_y"], z_ank_b), ml),
        _osso("BackFoot.R", "BackLowerLeg.R", (-xb, yb - 0.02 * m["len_y"], z_ank_b), (-xb, yb + foot_fwd, z0 + 0.02 * h), ml),
        _osso("MountSeat", "Spine", (0.0, y_spine, zt + 0.01 * h), (0.0, y_spine, zt + 0.09 * h), ml),
    ]

    if esqueleto == "winged_mount@1":
        ws = m["wing_span"]
        y_w0 = 0.5 * (y_spine + yf)
        z_w0 = zt - 0.02 * h
        y_wt = m["y_wing_tip"]
        z_wt = m["z_wing_tip"]
        x_r = max(0.08 * ws, xf * 0.7)
        for lado, sx in ((".L", 1.0), (".R", -1.0)):
            p0 = (sx * x_r, y_w0, z_w0)
            p1 = (sx * 0.25 * ws, y_w0 + 0.03 * m["len_y"], z_w0 + 0.30 * (z_wt - z_w0))
            p2 = (sx * 0.52 * ws, 0.5 * (y_w0 + y_wt) + 0.05 * m["len_y"], z_w0 + 0.70 * (z_wt - z_w0))
            p3 = (sx * 0.78 * ws, 0.25 * y_w0 + 0.75 * y_wt, z_w0 + 0.90 * (z_wt - z_w0))
            p4 = (sx * 0.98 * ws, y_wt, z_wt)
            ossos.extend(
                [
                    _osso(f"WingShoulder{lado}", "Chest", p0, p1, ml),
                    _osso(f"WingArm{lado}", f"WingShoulder{lado}", p1, p2, ml),
                    _osso(f"WingForearm{lado}", f"WingArm{lado}", p2, p3, ml),
                    _osso(f"WingTip{lado}", f"WingForearm{lado}", p3, p4, ml),
                ]
            )
    return ossos


def _atribuir_pesos_criatura(obj, ossos: list[dict], m: dict) -> None:
    """Skinning geodesico topologico para quadrupedes e montarias aladas."""
    nao_deform = _RAIZES | {"MountSeat"}
    deformaveis = [o for o in ossos if o["nome"] not in nao_deform]
    grupos_obj = {
        o["nome"]: (obj.vertex_groups.get(o["nome"]) or obj.vertex_groups.new(name=o["nome"]))
        for o in deformaveis
    }

    bm = bmesh.new()
    try:
        bm.from_mesh(obj.data)
        bm.verts.index_update()
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        coords = [v.co.copy() for v in bm.verts]
        ilhas = _ilhas_vertices(bm)
        adj = _grafo_superficie(bm)
    finally:
        bm.free()

    n_total = len(coords)
    if n_total == 0:
        return
    span_x = max(m["span_x"], 1e-3)
    h = max(m["altura"], 1e-3)
    inf = float("inf")
    eps = 0.015 * h
    tol_lado = 0.025 * span_x

    def _lado_ok(nome_osso: str, x: float) -> bool:
        lado = _lado_osso(nome_osso)
        if lado == "L":
            return x >= -tol_lado
        if lado == "R":
            return x <= tol_lado
        return abs(x) <= max(0.32 * m["len_y"], 0.25 * span_x)

    pesos_por_vertice: dict[int, list[tuple[str, float]]] = {}
    for ilha in ilhas:
        dist_mapas: list[tuple[str, list[float]]] = []
        for o in deformaveis:
            nome = o["nome"]
            a, b_pt = Vector(o["cabeca"]), Vector(o["cauda"])
            cand = [
                (_dist_ponto_segmento(coords[vi], a, b_pt), vi)
                for vi in ilha
                if _lado_ok(nome, coords[vi].x)
            ]
            if not cand:
                cand = [(_dist_ponto_segmento(coords[vi], a, b_pt), vi) for vi in ilha]
            cand.sort(key=lambda item: item[0])
            sementes = {vi: d0 for d0, vi in cand[: max(1, min(6, len(cand) // 8 or 1))]}
            dist_v = _dijkstra_osso(n_total, adj, sementes, inf)
            dist_mapas.append((nome, dist_v))

        for vi in ilha:
            vx = coords[vi].x
            brutos: list[tuple[float, str]] = []
            for nome, dist_v in dist_mapas:
                if not _lado_ok(nome, vx):
                    continue
                d = dist_v[vi]
                if d >= inf:
                    continue
                de = d + eps
                de2 = de * de
                brutos.append((1.0 / (de2 * de2), nome))
            if not brutos:
                for o in deformaveis:
                    if not _lado_ok(o["nome"], vx):
                        continue
                    de = _dist_ponto_segmento(coords[vi], Vector(o["cabeca"]), Vector(o["cauda"])) + eps
                    de2 = de * de
                    brutos.append((1.0 / (de2 * de2), o["nome"]))
            pesos_por_vertice[vi] = _normalizar_top4(brutos)

    def _perm_criatura(nome_osso: str, vi_idx: int) -> bool:
        return _lado_ok(nome_osso, coords[vi_idx].x)

    _suavizar_aneis_juntas(
        adj,
        pesos_por_vertice,
        deformaveis,
        permitido_fn=_perm_criatura,
        passos=2,
        alpha=0.32,
        pares_bloqueados={frozenset(("Chest", "Head"))},
    )
    for vi in range(n_total):
        for nome, peso in pesos_por_vertice.get(vi, ()):
            grupos_obj[nome].add([vi], peso, "REPLACE")


def auto_rigar_humanoide(obj, esqueleto: str, criar_armadura_fn) -> tuple["bpy.types.Object", dict]:
    """Cria armadura humanoide ajustada à malha e aplica skinning geodésico topológico."""
    if esqueleto not in _ESQUELETOS_HUMANOS:
        raise ValueError(f"esqueleto nao suportado: {esqueleto}")
    if obj is None or obj.type != "MESH" or not obj.data.vertices:
        raise RuntimeError("objeto invalido para auto-rigging")

    obj.vertex_groups.clear()
    for mod in list(obj.modifiers):
        if mod.type == "ARMATURE":
            obj.modifiers.remove(mod)
    _aplicar_identidade(obj)

    marcos = estimar_marcos(obj)
    ossos = _construir_ossos(esqueleto, marcos)
    rig_obj = criar_armadura_fn(ossos)
    _alinhar_roll_ossos(rig_obj)
    _aplicar_identidade(rig_obj)

    _atribuir_pesos_inverso(obj, ossos, marcos)
    _garantir_modificador_armature(obj, rig_obj)
    grupos = _normalizar_grupos_e_mapear(obj)
    return rig_obj, grupos


def auto_rigar_por_tipo(
    obj,
    esqueleto_spec: str | None,
    criar_armadura_fn,
    tipo: str | None = None,
) -> tuple["bpy.types.Object", dict]:
    """Despacha auto-rig para humanoide, quadrupede ou montaria alada conforme tipo/esqueleto."""
    esq = str(esqueleto_spec or "").strip()
    tipo_norm = str(tipo or "").strip().lower()

    if esq in _ESQUELETOS_CRIATURA:
        alvo_esq = esq
    elif tipo_norm == "criatura_alada":
        alvo_esq = "winged_mount@1"
    elif tipo_norm in ("criatura_quadrupede", "criatura"):
        alvo_esq = "quadruped@1"
    elif tipo_norm == "montaria":
        # Detecta asas laterais largas pela geometria caso esqueleto nao tenha sido explicito
        xs = [v.co.x for v in obj.data.vertices]
        ys = [v.co.y for v in obj.data.vertices]
        sx = (max(xs) - min(xs)) if xs else 0.0
        sy = (max(ys) - min(ys)) if ys else 0.0
        alvo_esq = "winged_mount@1" if sx > 1.25 * max(sy, 1e-4) else "quadruped@1"
    else:
        return auto_rigar_humanoide(obj, esq or "godot-humanoid@1", criar_armadura_fn)

    if obj is None or obj.type != "MESH" or not obj.data.vertices:
        raise RuntimeError("objeto invalido para auto-rigging")

    obj.vertex_groups.clear()
    for mod in list(obj.modifiers):
        if mod.type == "ARMATURE":
            obj.modifiers.remove(mod)

    com_asas = alvo_esq == "winged_mount@1"
    _alinhar_orientacao_criatura(obj, com_asas=com_asas)
    marcos = _estimar_marcos_criatura(obj, com_asas=com_asas)
    ossos = _construir_ossos_criatura(alvo_esq, marcos)
    rig_obj = criar_armadura_fn(ossos)
    _alinhar_roll_ossos(rig_obj)
    _aplicar_identidade(rig_obj)

    _atribuir_pesos_criatura(obj, ossos, marcos)
    _garantir_modificador_armature(obj, rig_obj)
    grupos = _normalizar_grupos_e_mapear(obj)
    return rig_obj, grupos


_ALIAS_OSSO_CRIATURA: dict[str, tuple[str, ...]] = {
    "Spine1": ("Spine",),
    "Shoulder.L": ("WingShoulder.L",),
    "Shoulder.R": ("WingShoulder.R",),
    "UpperArm.L": ("WingArm.L", "FrontUpperLeg.L"),
    "UpperArm.R": ("WingArm.R", "FrontUpperLeg.R"),
    "LowerArm.L": ("WingForearm.L", "FrontLowerLeg.L"),
    "LowerArm.R": ("WingForearm.R", "FrontLowerLeg.R"),
    "Hand.L": ("WingTip.L", "FrontFoot.L"),
    "Hand.R": ("WingTip.R", "FrontFoot.R"),
    "UpperLeg.L": ("BackUpperLeg.L",),
    "UpperLeg.R": ("BackUpperLeg.R",),
    "LowerLeg.L": ("BackLowerLeg.L",),
    "LowerLeg.R": ("BackLowerLeg.R",),
    "Foot.L": ("BackFoot.L",),
    "Foot.R": ("BackFoot.R",),
}


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
