"""Constantes R15 e primitivos XML/CFrame/matematica para exportacao Roblox."""

from __future__ import annotations

import math
from collections.abc import Sequence
from html import escape
from pathlib import Path
from typing import Any

from . import config
from .errors import erro_spec

#: Parte R15 -> nome da junta (Motor6D) no padrao do Roblox.
JOINT_R15: dict[str, str] = {
    "LowerTorso": "Root",
    "UpperTorso": "Waist",
    "Head": "Neck",
    "LeftUpperArm": "LeftShoulder",
    "LeftLowerArm": "LeftElbow",
    "LeftHand": "LeftWrist",
    "RightUpperArm": "RightShoulder",
    "RightLowerArm": "RightElbow",
    "RightHand": "RightWrist",
    "LeftUpperLeg": "LeftHip",
    "LeftLowerLeg": "LeftKnee",
    "LeftFoot": "LeftAnkle",
    "RightUpperLeg": "RightHip",
    "RightLowerLeg": "RightKnee",
    "RightFoot": "RightAnkle",
}

JOINT_R15_REV: dict[str, str] = {v: k for k, v in JOINT_R15.items()}

PARENT_R15: dict[str, str | None] = {
    "HumanoidRootPart": None,
    "LowerTorso": "HumanoidRootPart",
    "UpperTorso": "LowerTorso",
    "Head": "UpperTorso",
    "LeftUpperArm": "UpperTorso",
    "LeftLowerArm": "LeftUpperArm",
    "LeftHand": "LeftLowerArm",
    "RightUpperArm": "UpperTorso",
    "RightLowerArm": "RightUpperArm",
    "RightHand": "RightLowerArm",
    "LeftUpperLeg": "LowerTorso",
    "LeftLowerLeg": "LeftUpperLeg",
    "LeftFoot": "LeftLowerLeg",
    "RightUpperLeg": "LowerTorso",
    "RightLowerLeg": "RightUpperLeg",
    "RightFoot": "RightLowerLeg",
}

R15_FILHOS: dict[str | None, tuple[str, ...]] = {
    None: ("HumanoidRootPart",),
    "HumanoidRootPart": ("LowerTorso",),
    "LowerTorso": ("UpperTorso", "LeftUpperLeg", "RightUpperLeg"),
    "UpperTorso": ("Head", "LeftUpperArm", "RightUpperArm"),
    "LeftUpperArm": ("LeftLowerArm",),
    "LeftLowerArm": ("LeftHand",),
    "RightUpperArm": ("RightLowerArm",),
    "RightLowerArm": ("RightHand",),
    "LeftUpperLeg": ("LeftLowerLeg",),
    "LeftLowerLeg": ("LeftFoot",),
    "RightUpperLeg": ("RightLowerLeg",),
    "RightLowerLeg": ("RightFoot",),
}

COLLISION_FIDELITY_TOKENS: dict[str, int] = {
    "Default": 0,
    "Hull": 1,
    "Box": 2,
    "PreciseConvexDecomposition": 3,
}

RENDER_FIDELITY_TOKENS: dict[str, int] = {
    "Automatic": 0,
    "Precise": 1,
    "Performance": 2,
}


def _cor_int(hexcor: str) -> int:
    valor = int(str(hexcor).lstrip("#"), 16)
    r, g, b = (valor >> 16) & 0xFF, (valor >> 8) & 0xFF, valor & 0xFF
    return (r << 16) | (g << 8) | b


def _vec(tag: str, x: float, y: float, z: float) -> list[str]:
    return [
        f'<Vector3 name="{tag}">',
        f"<X>{x:.6f}</X>",
        f"<Y>{y:.6f}</Y>",
        f"<Z>{z:.6f}</Z>",
        "</Vector3>",
    ]


def _quat_normalizar(q: Sequence[float]) -> tuple[float, float, float, float]:
    w, x, y, z = float(q[0]), float(q[1]), float(q[2]), float(q[3])
    norm = math.sqrt(w * w + x * x + y * y + z * z)
    if norm < 1e-12:
        return (1.0, 0.0, 0.0, 0.0)
    return (w / norm, x / norm, y / norm, z / norm)


def _quat_mul(
    q1: Sequence[float],
    q2: Sequence[float],
) -> tuple[float, float, float, float]:
    """Multiplica dois quaternions ``(w, x, y, z)`` e normaliza o resultado."""
    w1, x1, y1, z1 = float(q1[0]), float(q1[1]), float(q1[2]), float(q1[3])
    w2, x2, y2, z2 = float(q2[0]), float(q2[1]), float(q2[2]), float(q2[3])
    return _quat_normalizar(
        (
            w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2,
            w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
            w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2,
            w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2,
        )
    )


def _quat_de_eixo_graus(graus: float, eixo: str) -> tuple[float, float, float, float]:
    """Converte rotacao em graus em torno de X/Y/Z para quaternion unitario ``(w, x, y, z)``."""
    meio = math.radians(float(graus)) * 0.5
    c, s = math.cos(meio), math.sin(meio)
    ax = eixo.strip().upper()
    if ax == "Y":
        return (c, 0.0, s, 0.0)
    if ax == "Z":
        return (c, 0.0, 0.0, s)
    return (c, s, 0.0, 0.0)


def _quat_para_mat3(q: Sequence[float]) -> list[float]:
    """Converte quaternion ``(w, x, y, z)`` para matriz 3x3 ortonormal (det = +1) linha a linha."""
    w, x, y, z = _quat_normalizar(q)
    xx, yy, zz = x * x, y * y, z * z
    xy, xz, yz = x * y, x * z, y * z
    wx, wy, wz = w * x, w * y, w * z
    return [
        1.0 - 2.0 * (yy + zz),
        2.0 * (xy - wz),
        2.0 * (xz + wy),
        2.0 * (xy + wz),
        1.0 - 2.0 * (xx + zz),
        2.0 * (yz - wx),
        2.0 * (xz - wy),
        2.0 * (yz + wx),
        1.0 - 2.0 * (xx + yy),
    ]


def _ortonormalizar_mat3(rot_mat: Any) -> list[float]:
    """Converte matriz 3x3 (9 floats, 3x3 aninhada) ou quaternion wxyz para 9 floats ortonormais (det = +1)."""
    if rot_mat is None:
        return [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
    if isinstance(rot_mat, (list, tuple)) and len(rot_mat) == 4 and not isinstance(rot_mat[0], (list, tuple)):
        return _quat_para_mat3([float(v) for v in rot_mat])
    if isinstance(rot_mat, (list, tuple)) and len(rot_mat) == 3 and isinstance(rot_mat[0], (list, tuple)):
        flat = [float(v) for linha in rot_mat for v in linha]
    elif isinstance(rot_mat, (list, tuple)) and len(rot_mat) == 9:
        flat = [float(v) for v in rot_mat]
    else:
        raise erro_spec(f"_cframe: formato de rot_mat invalido: {rot_mat!r}")

    c0 = [flat[0], flat[3], flat[6]]
    c1 = [flat[1], flat[4], flat[7]]
    n0 = math.sqrt(sum(v * v for v in c0))
    if n0 < 1e-12:
        return [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
    c0 = [v / n0 for v in c0]
    proj = sum(c0[i] * c1[i] for i in range(3))
    c1 = [c1[i] - proj * c0[i] for i in range(3)]
    n1 = math.sqrt(sum(v * v for v in c1))
    if n1 < 1e-12:
        cand = [0.0, 1.0, 0.0] if abs(c0[1]) < 0.9 else [1.0, 0.0, 0.0]
        proj = sum(c0[i] * cand[i] for i in range(3))
        c1 = [cand[i] - proj * c0[i] for i in range(3)]
        n1 = math.sqrt(sum(v * v for v in c1))
    c1 = [v / n1 for v in c1]
    c2 = [
        c0[1] * c1[2] - c0[2] * c1[1],
        c0[2] * c1[0] - c0[0] * c1[2],
        c0[0] * c1[1] - c0[1] * c1[0],
    ]
    return [
        c0[0], c1[0], c2[0],
        c0[1], c1[1], c2[1],
        c0[2], c1[2], c2[2],
    ]


def _cframe(
    tag_ou_pos: str | Sequence[float],
    x_ou_rot: Any = 0.0,
    y: float | None = None,
    z: float | None = None,
    rot_mat: Any = None,
    *,
    tag: str = "CFrame",
) -> list[str]:
    """Emite ``<CoordinateFrame>`` com translacao e matriz 3x3 ortonormal (det = +1)."""
    if isinstance(tag_ou_pos, str):
        nome_tag = tag_ou_pos
        if isinstance(x_ou_rot, (list, tuple)) and len(x_ou_rot) == 3 and z is None:
            px, py, pz = float(x_ou_rot[0]), float(x_ou_rot[1]), float(x_ou_rot[2])
            rot_efetiva = y if rot_mat is None else rot_mat
        else:
            px = float(x_ou_rot)
            py = float(0.0 if y is None else y)
            pz = float(0.0 if z is None else z)
            rot_efetiva = rot_mat
    else:
        nome_tag = tag
        px, py, pz = float(tag_ou_pos[0]), float(tag_ou_pos[1]), float(tag_ou_pos[2])
        rot_efetiva = x_ou_rot if (x_ou_rot != 0.0 or rot_mat is None) else rot_mat
        if isinstance(x_ou_rot, (int, float)) and x_ou_rot == 0.0 and rot_mat is None:
            rot_efetiva = None

    if rot_efetiva is None:
        r_linhas = [
            "<R00>1</R00><R01>0</R01><R02>0</R02>",
            "<R10>0</R10><R11>1</R11><R12>0</R12>",
            "<R20>0</R20><R21>0</R21><R22>1</R22>",
        ]
    else:
        m = _ortonormalizar_mat3(rot_efetiva)
        r_linhas = [
            f"<R00>{m[0]:.6f}</R00><R01>{m[1]:.6f}</R01><R02>{m[2]:.6f}</R02>",
            f"<R10>{m[3]:.6f}</R10><R11>{m[4]:.6f}</R11><R12>{m[5]:.6f}</R12>",
            f"<R20>{m[6]:.6f}</R20><R21>{m[7]:.6f}</R21><R22>{m[8]:.6f}</R22>",
        ]
    return [
        f'<CoordinateFrame name="{nome_tag}">',
        f"<X>{px:.6f}</X>",
        f"<Y>{py:.6f}</Y>",
        f"<Z>{pz:.6f}</Z>",
        *r_linhas,
        "</CoordinateFrame>",
    ]


def _roblox(p: Sequence[float], mps: float) -> tuple[float, float, float]:
    """metros (x, y, z) do blocky -> studs (x, z, -y) no Roblox."""
    return (p[0] / mps, p[2] / mps, -p[1] / mps)


def _attachment_xml(nome: str, ref: str, pos: Sequence[float], rot_mat: Any = None) -> list[str]:
    linhas = [
        f'<Item class="Attachment" referent="{ref}">',
        "<Properties>",
        f'<string name="Name">{escape(nome)}</string>',
    ]
    linhas += _cframe("CFrame", pos[0], pos[1], pos[2], rot_mat=rot_mat)
    linhas += ["</Properties>", "</Item>"]
    return linhas


def _parte_xml(
    nome: str,
    ref: str,
    centro: Sequence[float],
    tamanho: Sequence[float],
    cor: int,
    filhos: list[list[str]],
    *,
    anchored: bool = False,
    can_collide: bool = False,
    transparency: float | None = None,
    classe: str = "Part",
    mesh_id: str | None = None,
    collision_fidelity: str | None = None,
    render_fidelity: str | None = None,
) -> list[str]:
    linhas = [
        f'<Item class="{escape(classe)}" referent="{ref}">',
        "<Properties>",
        f'<string name="Name">{escape(nome)}</string>',
        f'<bool name="Anchored">{"true" if anchored else "false"}</bool>',
        f'<bool name="CanCollide">{"true" if can_collide else "false"}</bool>',
        f'<Color3uint8 name="Color3uint8">{cor}</Color3uint8>',
    ]
    if classe == "MeshPart":
        cf_tok = COLLISION_FIDELITY_TOKENS.get(str(collision_fidelity or "Box"), 2)
        rf_tok = RENDER_FIDELITY_TOKENS.get(str(render_fidelity or "Precise"), 1)
        linhas.append(f'<token name="CollisionFidelity">{cf_tok}</token>')
        linhas.append(f'<token name="RenderFidelity">{rf_tok}</token>')
        if mesh_id:
            linhas.append(f'<Content name="MeshId"><url>{escape(mesh_id)}</url></Content>')
        else:
            linhas.append('<Content name="MeshId"><null></null></Content>')
        linhas.append('<Content name="TextureID"><null></null></Content>')
    if transparency is not None:
        linhas.append(f'<float name="Transparency">{transparency:.6g}</float>')
    linhas += _vec("size", *tamanho)
    linhas += _cframe("CFrame", *centro)
    linhas += ["</Properties>"]
    for filho in filhos:
        linhas += filho
    linhas += ["</Item>"]
    return linhas


def _matriz_rotacao(graus: float, eixo: str) -> list[float]:
    """Matriz 3x3 (linha a linha) de rotacao em torno de um eixo local, em graus."""
    rad = math.radians(float(graus))
    c, s = math.cos(rad), math.sin(rad)
    if eixo.upper() == "Y":
        return [c, 0.0, s, 0.0, 1.0, 0.0, -s, 0.0, c]
    if eixo.upper() == "Z":
        return [c, -s, 0.0, s, c, 0.0, 0.0, 0.0, 1.0]
    return [1.0, 0.0, 0.0, 0.0, c, -s, 0.0, s, c]


def _mul_mat3(a: list[float], b: list[float]) -> list[float]:
    """Multiplica duas matrizes 3x3 em formato lista linha a linha."""
    return [
        a[r * 3] * b[c] + a[r * 3 + 1] * b[c + 3] + a[r * 3 + 2] * b[c + 6]
        for r in range(3)
        for c in range(3)
    ]


def _escrever_xml_seguro(
    xml: str,
    saida: str | Path | None,
    contexto: str,
) -> tuple[str | None, int]:
    destino_str = None
    tamanho = len(xml.encode("utf-8"))
    if saida is not None:
        destino = config.normalizar(saida)
        config.validar_destino(destino)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(xml, encoding="utf-8")
        destino_str = str(destino)
        tamanho = destino.stat().st_size
    return destino_str, tamanho
