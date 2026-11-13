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
    "aplicar_animacoes_multi",
    "estimar_marcos",
]

ESQUELETOS_SUPORTADOS = ("godot-humanoid@1", "r15@1")
_RAIZES = {"Root", "HumanoidRootPart"}
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
    """Alinha o eixo local dos membros sem singularidade colinear no pe (+Y)."""
    _selecionar_unico(rig_obj)
    bpy.ops.object.mode_set(mode="EDIT")
    frente = Vector((0.0, 1.0, 0.0))
    cima = Vector((0.0, 0.0, 1.0))
    for eb in rig_obj.data.edit_bones:
        if eb.name in _OSSOS_BRACO or eb.name in _OSSOS_PERNA:
            alvo = cima if abs(eb.y_axis.y) > 0.92 else frente
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

        arma_mao_osso: str | None = None
        if idx_ilha == 0:
            e_acessorio = False
        elif tem_ilha_principal:
            e_acessorio = (len(ilha) < 0.12 * n_total) or (diag < 0.22 * h)
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


def auto_rigar_humanoide(obj, esqueleto: str, criar_armadura_fn) -> tuple["bpy.types.Object", dict]:
    """Cria armadura humanoide ajustada à malha e aplica skinning geodésico topológico."""
    if esqueleto not in ESQUELETOS_SUPORTADOS:
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


def aplicar_animacoes_multi(rig_obj, clipes: list[dict]) -> list[dict]:
    """Aplica múltiplos clipes em Actions distintas + NLA tracks mudas sem vazamento de pose."""
    if not clipes:
        return []
    cena = bpy.context.scene
    rig_obj.animation_data_create()
    while rig_obj.animation_data.nla_tracks:
        rig_obj.animation_data.nla_tracks.remove(rig_obj.animation_data.nla_tracks[0])

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
                if not osso or osso not in rig_obj.pose.bones:
                    continue
                eixo = str(pose.get("eixo") or "X").upper()
                vetor = {
                    "X": (1.0, 0.0, 0.0),
                    "Y": (0.0, 1.0, 0.0),
                    "Z": (0.0, 0.0, 1.0),
                }.get(eixo, (1.0, 0.0, 0.0))
                pb = rig_obj.pose.bones[osso]
                pb.rotation_quaternion = pb.rotation_quaternion @ Quaternion(
                    vetor, math.radians(float(pose.get("graus", 0.0)))
                )
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

        if clipe.get("loop", True):
            for fc in acao.fcurves:
                for kp in fc.keyframe_points:
                    kp.interpolation = "LINEAR"

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
