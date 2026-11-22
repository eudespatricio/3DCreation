"""Constantes e utilidades geometricas base do auto-rigging (camada L0)."""

from __future__ import annotations

import bpy
from mathutils import Matrix, Vector

ESQUELETOS_SUPORTADOS = (
    "godot-humanoid@1",
    "godot-humanoid-aa@1",
    "r15@1",
    "quadruped@1",
    "winged_mount@1",
)
_ESQUELETOS_HUMANOS = ("godot-humanoid@1", "godot-humanoid-aa@1", "r15@1")
_ESQUELETOS_CRIATURA = ("quadruped@1", "winged_mount@1")
_DEDOS_NOMES = ("Thumb", "Index", "Middle", "Ring", "Little")
_OSSOS_DEDOS_L = {f"{d}{n}.L" for d in _DEDOS_NOMES for n in (1, 2, 3)}
_OSSOS_DEDOS_R = {f"{d}{n}.R" for d in _DEDOS_NOMES for n in (1, 2, 3)}
_OSSOS_DEDOS = _OSSOS_DEDOS_L | _OSSOS_DEDOS_R
_OSSOS_FACE_AA = {"Jaw", "Eye.L", "Eye.R"}
_OSSOS_CAPA_AA = {"Cape"}
_OSSOS_AA_EXTRAS = _OSSOS_DEDOS | _OSSOS_FACE_AA | _OSSOS_CAPA_AA

OSSOS_GODOT_HUMANOID_AA: tuple[str, ...] = (
    "Root",
    "Hips",
    "Spine",
    "Chest",
    "Neck",
    "Head",
    "Jaw",
    "Eye.L",
    "Eye.R",
    "Cape",
    "Shoulder.L",
    "UpperArm.L",
    "LowerArm.L",
    "Hand.L",
    "Shoulder.R",
    "UpperArm.R",
    "LowerArm.R",
    "Hand.R",
    *(f"{d}{n}.L" for d in _DEDOS_NOMES for n in (1, 2, 3)),
    *(f"{d}{n}.R" for d in _DEDOS_NOMES for n in (1, 2, 3)),
    "UpperLeg.L",
    "LowerLeg.L",
    "Foot.L",
    "Toe.L",
    "UpperLeg.R",
    "LowerLeg.R",
    "Foot.R",
    "Toe.R",
)
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
_OSSOS_BRACO_PROXIMAL_R15 = {"LeftUpperArm", "RightUpperArm"}
_OSSOS_MEMBROS_CORE = {
    "UpperArm.L",
    "UpperArm.R",
    "LowerArm.L",
    "LowerArm.R",
    "UpperLeg.L",
    "UpperLeg.R",
    "LowerLeg.L",
    "LowerLeg.R",
    "LeftUpperArm",
    "RightUpperArm",
    "LeftLowerArm",
    "RightLowerArm",
    "LeftUpperLeg",
    "RightUpperLeg",
    "LeftLowerLeg",
    "RightLowerLeg",
}
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
