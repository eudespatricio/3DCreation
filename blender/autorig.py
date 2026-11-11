"""Auto-rigging orgânico e animações multi-clipe para Blender 4.2 (Fase B).

Usa **apenas** ``bpy``, ``bmesh``, ``mathutils`` e stdlib (sem Pillow, sem numpy).
Convenção canônica da malha: +Z para cima, base em Z=0, frente +Y, X centrado em 0,
lado esquerdo (``.L`` / ``Left*``) em ``+X`` e lado direito (``.R`` / ``Right*``) em ``-X``
(idêntico a ``blocky.OSSOS_HUMANOIDE`` e ``blocky.OSSOS_R15``).
"""

from __future__ import annotations

import math

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
) -> dict:
    """Detecta ombro, cotovelo, pulso e ponta da mão para +X (L) ou -X (R)."""
    shoulder_z_default = _clamped(chest_top_z - 0.02 * altura, z0 + 0.72 * altura, z0 + 0.79 * altura)
    shoulder_x_default = sinal * _clamped(torso_hw * 1.12, 0.10 * altura, 0.18 * altura)
    clav_x_default = sinal * min(0.10 * altura, 0.65 * abs(shoulder_x_default))

    ombro_verts = [
        v
        for v in coords
        if z0 + 0.68 * altura <= v.z <= z0 + 0.82 * altura
        and abs(shoulder_x_default) * 0.8 <= v.x * sinal <= abs(shoulder_x_default) * 1.35
    ]
    if ombro_verts:
        shoulder_z = _clamped(
            _mediana([v.z for v in ombro_verts], shoulder_z_default),
            z0 + 0.70 * altura,
            z0 + 0.80 * altura,
        )
    else:
        shoulder_z = shoulder_z_default

    limiar_braco = max(torso_hw * 1.05, 0.095 * altura)
    braco_verts = [
        v
        for v in coords
        if v.x * sinal > limiar_braco
        and z0 + 0.28 * altura <= v.z <= z0 + 0.86 * altura
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
        tip.x = sinal * max(0.17 * altura, abs(shoulder_x_default) * 1.05)

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


def estimar_marcos(obj) -> dict:
    """Estima marcos anatômicos a partir da nuvem de vértices canônica (+Z cima, X=0 centro)."""
    coords = [obj.matrix_world @ v.co for v in obj.data.vertices]
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
    melhor_z = z_min + 0.79 * altura
    melhor_largura = float("inf")
    for i in range(14):
        za = z_min + (0.74 + 0.01 * i) * altura
        zb = za + 0.025 * altura
        xs = [v.x for v in coords if za <= v.z <= zb and abs(v.x) <= 0.15 * altura]
        if len(xs) >= 3:
            larg = max(xs) - min(xs)
            if larg < melhor_largura:
                melhor_largura = larg
                melhor_z = 0.5 * (za + zb)

    chest_top_z = _clamped(melhor_z - 0.02 * altura, z_min + 0.75 * altura, z_min + 0.81 * altura)
    neck_z = _clamped(chest_top_z + 0.065 * altura, z_min + 0.81 * altura, z_min + 0.87 * altura)
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

    hip_z = _clamped(leg_top_z + 0.03 * altura, z_min + 0.44 * altura, z_min + 0.50 * altura)
    spine_z = hip_z + 0.05 * altura
    spine1_z = spine_z + 0.035 * altura
    chest_z = _clamped(spine1_z + 0.065 * altura, z_min + 0.58 * altura, chest_top_z - 0.10 * altura)

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

    cintura_x = sorted(
        abs(v.x)
        for v in coords
        if z_min + 0.50 * altura <= v.z <= z_min + 0.64 * altura and abs(v.x) <= 0.15 * altura
    )
    torso_hw = cintura_x[int(0.9 * (len(cintura_x) - 1))] if cintura_x else 0.12 * altura
    torso_hw = _clamped(torso_hw, 0.07 * altura, 0.15 * altura)

    braco_L = _estimar_lado_braco(coords, z_min, altura, cy, chest_top_z, torso_hw, 1.0)
    braco_R = _estimar_lado_braco(coords, z_min, altura, cy, chest_top_z, torso_hw, -1.0)

    return {
        "z_min": z_min,
        "z_max": z_max,
        "altura": altura,
        "cy": cy,
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
            _osso("UpperLeg.L", "Hips", (m["leg_x_L"], cy, m["leg_top_z"]), (m["leg_x_L"], cy, m["knee_z"]), ml),
            _osso("LowerLeg.L", "UpperLeg.L", (m["leg_x_L"], cy, m["knee_z"]), (m["leg_x_L"], cy, m["ankle_z"]), ml),
            _osso("Foot.L", "LowerLeg.L", (m["leg_x_L"], cy, m["ankle_z"]), (m["leg_x_L"], cy + m["foot_y"], z0 + 0.02 * h), ml),
            _osso("Toe.L", "Foot.L", (m["leg_x_L"], cy + m["foot_y"], z0 + 0.02 * h), (m["leg_x_L"], cy + m["toe_y"], z0 + 0.012 * h), ml),
            _osso("UpperLeg.R", "Hips", (m["leg_x_R"], cy, m["leg_top_z"]), (m["leg_x_R"], cy, m["knee_z"]), ml),
            _osso("LowerLeg.R", "UpperLeg.R", (m["leg_x_R"], cy, m["knee_z"]), (m["leg_x_R"], cy, m["ankle_z"]), ml),
            _osso("Foot.R", "LowerLeg.R", (m["leg_x_R"], cy, m["ankle_z"]), (m["leg_x_R"], cy + m["foot_y"], z0 + 0.02 * h), ml),
            _osso("Toe.R", "Foot.R", (m["leg_x_R"], cy + m["foot_y"], z0 + 0.02 * h), (m["leg_x_R"], cy + m["toe_y"], z0 + 0.012 * h), ml),
        ]
    if esqueleto == "r15@1":
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
            _osso("LeftUpperLeg", "LowerTorso", (m["leg_x_L"], cy, m["leg_top_z"]), (m["leg_x_L"], cy, m["knee_z"]), ml),
            _osso("LeftLowerLeg", "LeftUpperLeg", (m["leg_x_L"], cy, m["knee_z"]), (m["leg_x_L"], cy, m["ankle_z"]), ml),
            _osso("LeftFoot", "LeftLowerLeg", (m["leg_x_L"], cy, m["ankle_z"]), (m["leg_x_L"], cy + m["foot_y"], z0 + 0.02 * h), ml),
            _osso("RightUpperLeg", "LowerTorso", (m["leg_x_R"], cy, m["leg_top_z"]), (m["leg_x_R"], cy, m["knee_z"]), ml),
            _osso("RightLowerLeg", "RightUpperLeg", (m["leg_x_R"], cy, m["knee_z"]), (m["leg_x_R"], cy, m["ankle_z"]), ml),
            _osso("RightFoot", "RightLowerLeg", (m["leg_x_R"], cy, m["ankle_z"]), (m["leg_x_R"], cy + m["foot_y"], z0 + 0.02 * h), ml),
        ]
    raise ValueError(f"esqueleto nao suportado pelo auto-rig: {esqueleto}")


def _alinhar_roll_ossos(rig_obj) -> None:
    """Alinha o eixo local X dos membros ao plano de flexão (frente +Y), inclusive em T/A-pose."""
    _selecionar_unico(rig_obj)
    bpy.ops.object.mode_set(mode="EDIT")
    frente = Vector((0.0, 1.0, 0.0))
    for eb in rig_obj.data.edit_bones:
        if eb.name in _OSSOS_BRACO or eb.name in _OSSOS_PERNA:
            eb.align_roll(frente)
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


def _osso_permitido(nome: str, v: Vector, m: dict, bracos_baixos: bool) -> bool:
    if nome in _RAIZES:
        return False
    h = m["altura"]
    x_tol = 0.04 * h
    lado = _lado_osso(nome)
    if v.x > x_tol and lado == "R":
        return False
    if v.x < -x_tol and lado == "L":
        return False
    if abs(v.x) <= x_tol and nome in _OSSOS_BRACO:
        return False

    hip_cut = m["hip_z"]
    arm_z_cut = m["shoulder_z"] - 0.12 * h

    if nome in _OSSOS_PERNA:
        return v.z <= hip_cut + 0.04 * h
    if nome in _OSSOS_BRACO:
        if v.z >= arm_z_cut and abs(v.x) >= 0.08 * h:
            return True
        return bracos_baixos and abs(v.x) > 0.125 * h and v.z >= m["z_min"] + 0.25 * h
    if nome in _OSSOS_TRONCO:
        if v.z < hip_cut - 0.06 * h:
            return False
        if abs(v.x) > max(abs(m["shoulder_x_L"]), 0.15 * h) * 1.15 and v.z >= arm_z_cut - 0.04 * h:
            return False
        return True
    return True


def _pesos_vertice_inverso(
    v: Vector,
    ossos: list[dict],
    m: dict,
    bracos_baixos: bool,
) -> list[tuple[str, float]]:
    h = m["altura"]
    eps = max(0.015 * h, 1e-4)
    brutos: list[tuple[str, float]] = []
    for o in ossos:
        nome = o["nome"]
        if not _osso_permitido(nome, v, m, bracos_baixos):
            continue
        d = _dist_ponto_segmento(v, Vector(o["cabeca"]), Vector(o["cauda"]))
        brutos.append((nome, 1.0 / ((d + eps) ** 4)))

    if not brutos:
        # Fallback absoluto: osso deformador mais próximo sem máscara
        melhor = min(
            (o for o in ossos if o["nome"] not in _RAIZES),
            key=lambda o: _dist_ponto_segmento(v, Vector(o["cabeca"]), Vector(o["cauda"])),
        )
        return [(melhor["nome"], 1.0)]

    brutos.sort(key=lambda par: par[1], reverse=True)
    top = brutos[:4]
    soma = sum(w for _, w in top)
    if soma <= 0.0:
        return [(top[0][0], 1.0)]
    norm = [(n, w / soma) for n, w in top if w / soma >= 1e-4]
    if not norm:
        return [(top[0][0], 1.0)]
    total = sum(w for _, w in norm)
    return [(n, w / total) for n, w in norm]


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

    alvo = indices if indices is not None else range(len(obj.data.vertices))
    for vi in alvo:
        v = obj.data.vertices[vi].co
        for nome, peso in _pesos_vertice_inverso(v, ossos, m, bracos_baixos):
            grupos_obj[nome].add([vi], peso, "REPLACE")


def _normalizar_grupos_e_mapear(obj) -> dict[str, list[int]]:
    """Limita a 4 influências por vértice, normaliza soma = 1.0 e devolve osso -> índices."""
    for vg in list(obj.vertex_groups):
        if vg.name in _RAIZES:
            obj.vertex_groups.remove(vg)
    vgs = {vg.index: vg for vg in obj.vertex_groups}
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
        pares.sort(key=lambda item: item[1], reverse=True)
        manter = pares[:4]
        descartar = pares[4:]
        for vg, _w in descartar:
            vg.remove([v.index])
        soma = sum(w for _, w in manter)
        if soma > 0.0:
            for vg, w in manter:
                vg.add([v.index], w / soma, "REPLACE")

    mapa: dict[str, list[int]] = {}
    for v in obj.data.vertices:
        for g in v.groups:
            vg = vgs.get(g.group)
            if vg is not None and g.weight > 1e-6:
                mapa.setdefault(vg.name, []).append(v.index)
    return {k: sorted(v) for k, v in mapa.items() if v}


def auto_rigar_humanoide(obj, esqueleto: str, criar_armadura_fn) -> tuple["bpy.types.Object", dict]:
    """Cria armadura humanoide ajustada à malha e faz skinning automático + fallback determinístico."""
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

    heat_ok = False
    try:
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        rig_obj.select_set(True)
        bpy.context.view_layer.objects.active = rig_obj
        bpy.ops.object.parent_set(type="ARMATURE_AUTO")
        bpy.ops.object.select_all(action="DESELECT")
        heat_ok = True
    except Exception:  # noqa: BLE001 - heat pode falhar em ilhas/nao-manifold
        heat_ok = False

    n_verts = len(obj.data.vertices)
    sem_peso = [
        v.index
        for v in obj.data.vertices
        if sum(g.weight for g in v.groups if obj.vertex_groups[g.group].name not in _RAIZES) <= 1e-5
    ]
    cobertura = (n_verts - len(sem_peso)) / max(n_verts, 1)

    if not heat_ok or cobertura < 0.95 or not obj.vertex_groups:
        obj.vertex_groups.clear()
        _aplicar_identidade(obj)
        _atribuir_pesos_inverso(obj, ossos, marcos)
    elif sem_peso:
        _atribuir_pesos_inverso(obj, ossos, marcos, indices=sem_peso)

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
                pb.rotation_quaternion = Quaternion(vetor, math.radians(float(pose.get("graus", 0.0))))
                pb.keyframe_insert("rotation_quaternion", frame=frame)

        track = rig_obj.animation_data.nla_tracks.new()
        track.name = nome
        inicio = int(acao.frame_range[0]) if acao.fcurves else 1
        strip = track.strips.new(nome, inicio, acao)
        strip.name = nome
        track.mute = True

        rig_obj.animation_data.action = None
        for pb in rig_obj.pose.bones:
            pb.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)

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
