"""GAP-022: valida eixos locais, direcoes, simetria e cadeia de pais do auto-rig no Blender."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from forge3d import profiles

RAIZ = Path(__file__).resolve().parents[1]

_PAIS_ESPERADOS: dict[str, dict[str, str | None]] = {
    "godot-humanoid@1": {
        "Root": None,
        "Hips": "Root",
        "Spine": "Hips",
        "Spine1": "Spine",
        "Chest": "Spine1",
        "Neck": "Chest",
        "Head": "Neck",
        "Shoulder.L": "Chest",
        "UpperArm.L": "Shoulder.L",
        "LowerArm.L": "UpperArm.L",
        "Hand.L": "LowerArm.L",
        "Shoulder.R": "Chest",
        "UpperArm.R": "Shoulder.R",
        "LowerArm.R": "UpperArm.R",
        "Hand.R": "LowerArm.R",
        "UpperLeg.L": "Hips",
        "LowerLeg.L": "UpperLeg.L",
        "Foot.L": "LowerLeg.L",
        "Toe.L": "Foot.L",
        "UpperLeg.R": "Hips",
        "LowerLeg.R": "UpperLeg.R",
        "Foot.R": "LowerLeg.R",
        "Toe.R": "Foot.R",
    },
    "r15@1": {
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
    },
}

_TRONCO = {
    "Root",
    "Hips",
    "Spine",
    "Spine1",
    "Chest",
    "Neck",
    "Head",
    "HumanoidRootPart",
    "LowerTorso",
    "UpperTorso",
}
_PERNAS = {
    "UpperLeg.L",
    "LowerLeg.L",
    "UpperLeg.R",
    "LowerLeg.R",
    "LeftUpperLeg",
    "LeftLowerLeg",
    "RightUpperLeg",
    "RightLowerLeg",
}
_PES = {"Foot.L", "Toe.L", "Foot.R", "Toe.R", "LeftFoot", "RightFoot"}
_BRACOS = {
    "UpperArm.L",
    "LowerArm.L",
    "Hand.L",
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
_MEMBROS_FLEXAO = _PERNAS | _BRACOS

_BLENDER_EXPR = """
import json, sys
import bpy, bmesh

argv = sys.argv[sys.argv.index("--") + 1 :]
blender_dir, esqueleto, out_json = argv[0], argv[1], argv[2]
sys.path.insert(0, blender_dir)
import autorig, postprocess

bpy.ops.wm.read_factory_settings(use_empty=True)
bm = bmesh.new()

def add_box(cx, cy, cz, sx, sy, sz):
    ret = bmesh.ops.create_cube(bm, size=1.0)
    for v in ret["verts"]:
        v.co.x = v.co.x * sx + cx
        v.co.y = v.co.y * sy + cy
        v.co.z = v.co.z * sz + cz

# Humanoide sintetico em pe (+Z cima, +Y frente, +X esquerda)
add_box(0.0, 0.0, 1.05, 0.28, 0.16, 0.56)
add_box(0.0, 0.0, 1.44, 0.11, 0.11, 0.14)
add_box(0.0, 0.0, 1.67, 0.20, 0.22, 0.34)
add_box(0.11, 0.0, 0.42, 0.13, 0.13, 0.84)
add_box(-0.11, 0.0, 0.42, 0.13, 0.13, 0.84)
add_box(0.11, 0.07, 0.04, 0.13, 0.22, 0.08)
add_box(-0.11, 0.07, 0.04, 0.13, 0.22, 0.08)
add_box(0.28, 0.0, 1.03, 0.10, 0.10, 0.72)
add_box(-0.28, 0.0, 1.03, 0.10, 0.10, 0.72)

bmesh.ops.subdivide_edges(bm, edges=list(bm.edges), cuts=3, use_grid_fill=True)
me = bpy.data.meshes.new("humanoide")
bm.to_mesh(me)
bm.free()
obj = bpy.data.objects.new("humanoide", me)
bpy.context.collection.objects.link(obj)

rig_obj, _ = autorig.auto_rigar_humanoide(obj, esqueleto, postprocess.criar_armadura)
ossos = []
for b in rig_obj.data.bones:
    mat = b.matrix_local.to_3x3()
    d = (b.tail_local - b.head_local).normalized()
    ossos.append({
        "name": b.name,
        "parent": b.parent.name if b.parent else None,
        "head": [float(v) for v in b.head_local],
        "tail": [float(v) for v in b.tail_local],
        "dir": [float(v) for v in d],
        "local_x": [float(v) for v in mat.col[0]],
        "local_y": [float(v) for v in mat.col[1]],
        "local_z": [float(v) for v in mat.col[2]],
    })
with open(out_json, "w", encoding="utf-8") as fh:
    json.dump(ossos, fh)
"""


def _blender_bin() -> str:
    bin_blender = shutil.which("blender")
    if not bin_blender:
        pytest.skip("blender nao disponivel no PATH")
    return bin_blender


def _pares_simetricos(nomes: list[str]) -> list[tuple[str, str]]:
    pares: list[tuple[str, str]] = []
    conjunto = set(nomes)
    for nome in nomes:
        if nome.endswith(".L") and (oposto := nome[:-2] + ".R") in conjunto:
            pares.append((nome, oposto))
        elif nome.startswith("Left") and (oposto := "Right" + nome[4:]) in conjunto:
            pares.append((nome, oposto))
    return pares


@pytest.mark.blender
@pytest.mark.parametrize(
    ("perfil_nome", "esqueleto", "qtd_ossos"),
    [
        ("godot4", "godot-humanoid@1", 23),
        ("roblox-r15", "r15@1", 16),
    ],
)
def test_rig_eixos_direcoes_simetria_e_cadeia_de_pais(
    tmp_path: Path, perfil_nome: str, esqueleto: str, qtd_ossos: int
):
    blender = _blender_bin()
    perfil = profiles.carregar(perfil_nome)
    mapa_esperado = perfil["rig"]["mapas"][esqueleto]
    assert len(mapa_esperado) == qtd_ossos

    out_json = tmp_path / f"axes_{esqueleto.replace('@', '_')}.json"
    proc = subprocess.run(
        [
            blender,
            "-b",
            "--factory-startup",
            "--python-expr",
            _BLENDER_EXPR,
            "--",
            str(RAIZ / "blender"),
            esqueleto,
            str(out_json),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert out_json.is_file()

    ossos = json.loads(out_json.read_text(encoding="utf-8"))
    por_nome = {o["name"]: o for o in ossos}

    # 1. Conjunto exato de ossos e cadeia de pais do perfil
    assert len(ossos) == qtd_ossos
    assert set(por_nome) == set(mapa_esperado)
    pais_obtidos = {o["name"]: o["parent"] for o in ossos}
    assert pais_obtidos == _PAIS_ESPERADOS[esqueleto]

    for nome, info in por_nome.items():
        hx, _hy, _hz = info["head"]
        dx, dy, dz = info["dir"]
        lx = info["local_x"]
        ly = info["local_y"]
        lz = info["local_z"]

        # 2. Simetria esquerda (+X) / direita (-X) / tronco central (|x| < 1e-3)
        if nome.endswith(".L") or nome.startswith("Left"):
            assert hx > 0.0, f"{nome} deveria estar em +X, obteve head.x={hx}"
        elif nome.endswith(".R") or nome.startswith("Right"):
            assert hx < 0.0, f"{nome} deveria estar em -X, obteve head.x={hx}"
        else:
            assert abs(hx) < 1e-3, f"{nome} central fora de X=0: head.x={hx}"

        # local_y sempre coincide com (tail - head) normalizado
        assert sum(a * b for a, b in zip(ly, info["dir"], strict=True)) > 0.999

        # 3. Direcoes normalizadas dos ossos
        if nome in _TRONCO:
            assert dz > 0.99, f"tronco {nome} deve apontar +Z: dir={info['dir']}"
        elif nome in _PERNAS:
            assert dz < -0.99, f"perna {nome} deve apontar -Z: dir={info['dir']}"
        elif nome in _PES:
            assert dy > 0.80, f"pe {nome} deve apontar +Y: dir={info['dir']}"
        elif nome == "Shoulder.L":
            assert dx > 0.99, f"Shoulder.L deve apontar +X: dir={info['dir']}"
        elif nome == "Shoulder.R":
            assert dx < -0.99, f"Shoulder.R deve apontar -X: dir={info['dir']}"

        # 4. Eixos locais de flexao (local_z frente +Y > 0.90, local_x lateral +X > 0.75)
        if nome in _MEMBROS_FLEXAO:
            assert lz[1] > 0.90, f"{nome} local_z deve apontar +Y (>0.90): lz={lz}"
            assert lx[0] > 0.75, f"{nome} local_x deve apontar +X (>0.75): lx={lx}"
        elif nome in _PES:
            assert lx[0] > 0.75, f"{nome} local_x deve apontar +X (>0.75): lx={lx}"
            assert lz[1] > 0.0, f"{nome} local_z invertido em -Y: lz={lz}"

    # Simetria espelhada entre pares L/R
    for esq_nome, dir_nome in _pares_simetricos(mapa_esperado):
        hl = por_nome[esq_nome]["head"]
        hr = por_nome[dir_nome]["head"]
        assert abs(hl[0] + hr[0]) < 1e-3, (esq_nome, hl, dir_nome, hr)
        assert abs(hl[2] - hr[2]) < 1e-3, (esq_nome, hl, dir_nome, hr)
