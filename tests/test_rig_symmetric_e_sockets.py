"""Testes de simetria L/R de bone rolls, skinning DQ com anel de junta e sockets bone-local."""

from __future__ import annotations

import json
import math
import shutil
import subprocess
from pathlib import Path

import jsonschema
import pytest

RAIZ = Path(__file__).resolve().parent.parent


def _blender_bin() -> str:
    bin_blender = shutil.which("blender")
    if not bin_blender:
        pytest.skip("blender nao disponivel no PATH")
    return bin_blender


def _rodar_blender(expr: str, args: list[str], timeout: int = 120) -> None:
    blender = _blender_bin()
    proc = subprocess.run(
        [blender, "-b", "--factory-startup", "--python-exit-code", "1", "--python-expr", expr, "--", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr


_EXPR_SYMM_ET_BLEND = """
import json, math, sys
from pathlib import Path
import bmesh, bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
sys.path.insert(0, argv[0])
out_json = Path(argv[1])
import autorig

def _limpar():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)

def _criar_armadura(ossos):
    arm = bpy.data.armatures.new("Rig")
    rig = bpy.data.objects.new("Rig", arm)
    bpy.context.collection.objects.link(rig)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    ebs = {}
    for o in ossos:
        eb = arm.edit_bones.new(o["nome"])
        eb.head = Vector(o["cabeca"])
        eb.tail = Vector(o["cauda"])
        ebs[o["nome"]] = eb
    for o in ossos:
        if o["pai"]:
            ebs[o["nome"]].parent = ebs[o["pai"]]
    bpy.ops.object.mode_set(mode="OBJECT")
    return rig

def _cilindro(bm, a, b, r, seg=10, rings=10):
    va = Vector(a)
    vb = Vector(b)
    eixo = vb - va
    comp = eixo.length
    d = eixo.normalized()
    ref = Vector((0, 1, 0)) if abs(d.y) < 0.9 else Vector((1, 0, 0))
    u = d.cross(ref).normalized()
    v = d.cross(u).normalized()
    aneis = []
    for ri in range(rings + 1):
        t = ri / float(rings)
        c = va + d * (comp * t)
        anel = []
        for si in range(seg):
            ang = 2.0 * math.pi * si / float(seg)
            p = c + (u * math.cos(ang) + v * math.sin(ang)) * r
            anel.append(bm.verts.new(p))
        aneis.append(anel)
    for ri in range(rings):
        for si in range(seg):
            sn = (si + 1) % seg
            bm.faces.new((aneis[ri][si], aneis[ri][sn], aneis[ri + 1][sn], aneis[ri + 1][si]))
    bm.faces.new(list(reversed(aneis[0])))
    bm.faces.new(aneis[-1])

def _humanoide_dobrado(dir_y_forearm):
    _limpar()
    bm = bmesh.new()
    _cilindro(bm, (0, 0, 0.85), (0, 0, 1.50), 0.16, seg=12, rings=8)
    _cilindro(bm, (0, 0, 1.50), (0, 0, 1.80), 0.10, seg=10, rings=6)
    for sx in (1.0, -1.0):
        _cilindro(bm, (sx * 0.09, 0, 0.85), (sx * 0.09, 0, 0.45), 0.075, seg=10, rings=8)
        _cilindro(bm, (sx * 0.09, 0, 0.45), (sx * 0.09, 0, 0.02), 0.055, seg=10, rings=8)
        _cilindro(bm, (sx * 0.09, 0, 0.02), (sx * 0.09, 0.16, 0.0), 0.045, seg=8, rings=4)
        sh = (sx * 0.17, 0.0, 1.42)
        el = (sx * 0.30, 0.0, 1.15)
        wr = (sx * 0.35, dir_y_forearm * 0.24, 1.00)
        tp = (sx * 0.37, dir_y_forearm * 0.32, 0.94)
        _cilindro(bm, sh, el, 0.055, seg=10, rings=8)
        _cilindro(bm, el, wr, 0.045, seg=10, rings=8)
        _cilindro(bm, wr, tp, 0.035, seg=8, rings=4)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new("Human")
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new("Human", me)
    bpy.context.collection.objects.link(obj)
    return obj

rel = {}
for tag, dy in (("fwd", 1.0), ("bwd", -1.0)):
    obj = _humanoide_dobrado(dy)
    rig, _ = autorig.auto_rigar_humanoide(obj, "godot-humanoid@1", _criar_armadura)
    mods = [m for m in obj.modifiers if m.type == "ARMATURE"]
    bones = {}
    for bn in ("UpperArm.L", "LowerArm.L", "UpperArm.R", "LowerArm.R"):
        b = rig.data.bones[bn]
        m3 = b.matrix_local.to_3x3()
        bones[bn] = {
            "dir": list((b.tail_local - b.head_local).normalized()),
            "lx": list((m3 @ Vector((1, 0, 0))).normalized()),
            "lz": list((m3 @ Vector((0, 0, 1))).normalized()),
        }
    cotovelo_L_mix = 0
    for v in obj.data.vertices:
        ws = {obj.vertex_groups[g.group].name: g.weight for g in v.groups if g.weight > 1e-4}
        if ws.get("UpperArm.L", 0.0) > 0.08 and ws.get("LowerArm.L", 0.0) > 0.08:
            cotovelo_L_mix += 1
    sockets = autorig.extrair_sockets(rig, obj)
    rel[tag] = {
        "dq": bool(mods and mods[0].use_deform_preserve_volume),
        "bones": bones,
        "cotovelo_mix": cotovelo_L_mix,
        "sockets": sockets,
    }

out_json.write_text(json.dumps(rel), encoding="utf-8")
"""


@pytest.mark.blender
def test_symmetric_bone_rolls_dq_boundary_blending_and_extrair_sockets(tmp_path: Path):
    out_json = tmp_path / "symm_sockets.json"
    _rodar_blender(_EXPR_SYMM_ET_BLEND, [str(RAIZ / "blender"), str(out_json)])
    dados = json.loads(out_json.read_text(encoding="utf-8"))

    schema = json.loads((RAIZ / "schemas" / "manifest.v5.schema.json").read_text(encoding="utf-8"))
    sockets_schema = {
        "$schema": schema["$schema"],
        "type": "array",
        "items": schema["properties"]["sockets"]["items"],
    }

    for tag in ("fwd", "bwd"):
        item = dados[tag]
        assert item["dq"] is True
        assert item["cotovelo_mix"] >= 4
        b = item["bones"]
        lx_l = b["LowerArm.L"]["lx"]
        lx_r = b["LowerArm.R"]["lx"]
        # Ambos os bracos alinham com +X canonico e espelham Y/Z mesmo quando dobrados para tras
        assert lx_l[0] > 0.80 and lx_r[0] > 0.80
        assert abs(lx_l[0] - lx_r[0]) < 0.06
        assert abs(lx_l[1] + lx_r[1]) < 0.06
        assert abs(lx_l[2] + lx_r[2]) < 0.06

        socks = item["sockets"]
        jsonschema.validate(socks, sockets_schema)
        nomes = {s["nome"]: s for s in socks}
        assert {"Hand.R", "Hand.L", "Back", "Head", "Shoulder.L", "Shoulder.R"} <= set(nomes)
        for s in socks:
            assert s["frente_local"] == [0.0, 0.0, -1.0]
            q = s["rotacao_quat_wxyz"]
            norma = math.sqrt(sum(c * c for c in q))
            assert norma == pytest.approx(1.0, abs=1e-4)
        # Back deve ficar no dorso do Chest (+Z_gltf)
        assert nomes["Back"]["osso"] == "Chest"
        assert nomes["Back"]["posicao_local"][2] > 0.08
        # Hand.L e Hand.R nunca copiam a mesma rotacao quando em A-pose inclinada
        assert nomes["Hand.L"]["rotacao_quat_wxyz"] != nomes["Hand.R"]["rotacao_quat_wxyz"]


_EXPR_SOCKETS_PARTES = """
import json, math, sys
from pathlib import Path
import bmesh, bpy
from mathutils import Euler, Matrix, Vector

argv = sys.argv[sys.argv.index("--") + 1:]
sys.path.insert(0, argv[0])
out_json = Path(argv[1])
import modular_armor

bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)

def _box(nome, cx, cy, cz, sx, sy, sz):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co.x = cx + v.co.x * sx
        v.co.y = cy + v.co.y * sy
        v.co.z = cz + v.co.z * sz
    me = bpy.data.meshes.new(nome)
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new(nome, me)
    bpy.context.collection.objects.link(obj)
    return obj

# Orbe colocado na palma de Hand.L (X=+0.34, Y=0.04, Z=0.88) longe dos joelhos (Z=0.45)
m_hand_l = Matrix.Translation((0.34, 0.04, 0.88)) @ Euler((math.pi, 0.0, 0.0), "XYZ").to_matrix().to_4x4()
orbe = _box("Orbe", 0.34, 0.04, 0.88, 0.14, 0.14, 0.14)
modular_armor._ajustar_pivo_socket(orbe, "orbe", "Hand.L", Vector((0.34, 0.04, 0.88)), matriz_osso=m_hand_l)
orbe_zs = [v.co.z for v in orbe.data.vertices]
orbe_xs = [v.co.x for v in orbe.data.vertices]

# Capa modelada nas costas do peitoral, porem deitada horizontalmente como prancha (span_y > span_z)
m_chest = Matrix.Translation((0.0, -0.10, 1.32)) @ Euler((math.pi * 0.5, 0.0, 0.0), "XYZ").to_matrix().to_4x4()
capa_prancha = _box("CapaPrancha", 0.0, -0.50, 1.30, 0.45, 0.90, 0.03)
modular_armor._ajustar_pivo_socket(capa_prancha, "capa", "Chest", Vector((0.0, -0.10, 1.32)), matriz_osso=m_chest)
czs = [v.co.z for v in capa_prancha.data.vertices]
cys = [v.co.y for v in capa_prancha.data.vertices]

# Arma standalone centrada na origem: cabo fica a 20% da base
arma = _box("Arma", 0.0, 0.0, 0.50, 0.08, 0.04, 1.00)
modular_armor._ajustar_pivo_socket(arma, "arma", "Hand.R", Vector((-0.34, 0.0, 0.90)))
azs = [v.co.z for v in arma.data.vertices]

# Escudo procedural: frente convexa em +Y, grip interno proximo a Y<=0
esc = modular_armor._criar_escudo_procedural("EscudoTeste")
modular_armor._ajustar_pivo_socket(esc, "escudo", "LowerArm.L", Vector((0.30, 0.0, 1.05)))
eys = [v.co.y for v in esc.data.vertices]

out_json.write_text(json.dumps({
    "orbe_center_x": 0.5 * (min(orbe_xs) + max(orbe_xs)),
    "orbe_center_z": 0.5 * (min(orbe_zs) + max(orbe_zs)),
    "capa_span_z": max(czs) - min(czs),
    "capa_span_y": max(cys) - min(cys),
    "capa_z_max": max(czs),
    "capa_z_min": min(czs),
    "arma_z_min": min(azs),
    "arma_z_max": max(azs),
    "escudo_y_max": max(eys),
    "escudo_y_min": min(eys),
}), encoding="utf-8")
"""


@pytest.mark.blender
def test_modular_armor_bone_local_sockets(tmp_path: Path):
    out_json = tmp_path / "sockets_partes.json"
    _rodar_blender(_EXPR_SOCKETS_PARTES, [str(RAIZ / "blender"), str(out_json)])
    d = json.loads(out_json.read_text(encoding="utf-8"))

    # Orbe centrado no socket da palma Hand.L (nao deslocado para joelhos)
    assert abs(d["orbe_center_x"]) < 0.02
    assert abs(d["orbe_center_z"]) < 0.02
    # Capa pende verticalmente em -Z_bl (jamais horizontal como prancha)
    assert d["capa_span_z"] > d["capa_span_y"] * 2.0
    assert d["capa_z_max"] <= 0.15
    assert d["capa_z_min"] < -0.50
    # Arma com cabo em 20% da base (Z=-0.20..+0.80)
    assert d["arma_z_min"] == pytest.approx(-0.20, abs=0.02)
    assert d["arma_z_max"] == pytest.approx(0.80, abs=0.02)
    # Escudo com face externa (+Y) maior que profundidade de pegada (-Y)
    assert d["escudo_y_max"] > abs(d["escudo_y_min"])


def test_modular_armor_v5_socket_mappings(tmp_path: Path):
    import importlib.util
    import sys
    import types

    spec_mod = importlib.util.spec_from_file_location(
        "modular_armor_unit",
        RAIZ / "blender" / "modular_armor.py",
    )
    assert spec_mod and spec_mod.loader
    sys_backup = {k: sys.modules.get(k) for k in ("bpy", "bmesh", "mathutils")}
    sys.modules["bpy"] = types.ModuleType("bpy")
    sys.modules["bmesh"] = types.ModuleType("bmesh")
    mu = types.ModuleType("mathutils")
    mu.Vector = object
    mu.Matrix = object
    mu.Quaternion = object
    sys.modules["mathutils"] = mu
    try:
        mod = importlib.util.module_from_spec(spec_mod)
        spec_mod.loader.exec_module(mod)
    finally:
        for k, v in sys_backup.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v

    assert mod._osso_socket("orbe", "godot-humanoid@1") == "Hand.L"
    assert mod._osso_socket("mochila", "godot-humanoid@1") == "Chest"
    assert mod._osso_socket("asas", "godot-humanoid@1") == "Chest"
    assert mod._osso_socket("sela", "godot-humanoid@1") == "MountSeat"
    assert mod._osso_socket("orbe", "r15@1") == "LeftHand"
    assert mod._osso_socket("mochila", "r15@1") == "UpperTorso"
