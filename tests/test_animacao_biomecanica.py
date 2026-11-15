"""Testes do motor de animacao biomecanico V2: curvas C1 24fps, Bezier, ride_* e R15."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from forge3d import animacao, profiles

RAIZ = Path(__file__).resolve().parent.parent
GODOT = profiles.carregar("godot4")
ROBLOX = profiles.carregar("roblox-r15")


def _blender_bin() -> str:
    bin_blender = shutil.which("blender")
    if not bin_blender:
        pytest.skip("blender nao disponivel no PATH")
    return bin_blender


def test_c1_24fps_dense_keys_no_v_cusp_and_counter_rotation():
    for nome in (
        "idle",
        "walk",
        "run",
        "jump",
        "attack",
        "slash_combo",
        "cast",
        "block",
        "death",
        "ride_idle",
        "ride_fly",
    ):
        clipe = animacao.clipes(GODOT, "godot-humanoid@1", [nome])[0]
        assert clipe["fps"] == 24
        assert 16 <= len(clipe["chaves"]) <= 32, (nome, len(clipe["chaves"]))

    walk = animacao.clipes(GODOT, "godot-humanoid@1", ["walk"])[0]
    zs = []
    by_bone = {}
    for ch in walk["chaves"]:
        for p in ch["poses"]:
            by_bone.setdefault(p["osso"], []).append((p["eixo"], p["graus"]))
            if p["osso"] == "Hips" and "deslocamento_m" in p:
                zs.append((ch["segundos"] / walk["duracao_s"], p["deslocamento_m"][2]))

    # Bounce C1 sem cuspide em V: inicio, meio (0.5) e fim em 0.0, pico 0.025 em 0.25 e 0.75
    assert zs[0][1] == pytest.approx(0.0, abs=1e-6)
    mid_idx = len(zs) // 2
    assert zs[mid_idx][1] == pytest.approx(0.0, abs=1e-6)
    assert max(z for _f, z in zs) == pytest.approx(0.025, abs=1e-6)
    # Derivada discreta cruza o vale suavemente (delta antes/depois do meio simetrico de sinais opostos pequenos)
    d_antes = zs[mid_idx][1] - zs[mid_idx - 1][1]
    d_depois = zs[mid_idx + 1][1] - zs[mid_idx][1]
    assert abs(d_antes) < 0.002 and abs(d_depois) < 0.002

    # Contra-rotacao coluna/peitoral/cabeca no eixo Y e limites fisicos joelho<=0 / cotovelo>=0
    chest_y = [g for ax, g in by_bone["Chest"] if ax == "Y"]
    head_y = [g for ax, g in by_bone["Head"] if ax == "Y"]
    assert max(abs(g) for g in chest_y) > 3.0
    assert any(c * h < -1.0 for c, h in zip(chest_y, head_y))

    for _, g in by_bone["LowerLeg.L"] + by_bone["LowerLeg.R"]:
        assert g <= 0.0
    for _, g in by_bone["LowerArm.L"] + by_bone["LowerArm.R"]:
        assert g >= 0.0


def test_ride_idle_and_ride_fly_straddle_posture():
    clips = {c["nome"]: c for c in animacao.clipes(GODOT, "godot-humanoid@1", ["ride_idle", "ride_fly"])}
    for nome in ("ride_idle", "ride_fly"):
        c = clips[nome]
        assert c["loop"] is True
        ch0 = c["chaves"][0]["poses"]
        hips = [p for p in ch0 if p["osso"] == "Hips"]
        assert hips[0]["deslocamento_m"][2] < -0.18

        thigh_l_x = [p["graus"] for p in ch0 if p["osso"] == "UpperLeg.L" and p["eixo"] == "X"][0]
        thigh_l_z = [p["graus"] for p in ch0 if p["osso"] == "UpperLeg.L" and p["eixo"] == "Z"][0]
        thigh_r_z = [p["graus"] for p in ch0 if p["osso"] == "UpperLeg.R" and p["eixo"] == "Z"][0]
        knee_l = [p["graus"] for p in ch0 if p["osso"] == "LowerLeg.L"][0]
        chest_x = [p["graus"] for p in ch0 if p["osso"] == "Chest" and p["eixo"] == "X"][0]
        head_x = [p["graus"] for p in ch0 if p["osso"] == "Head" and p["eixo"] == "X"][0]
        arm_l = [p["graus"] for p in ch0 if p["osso"] == "UpperArm.L" and p["eixo"] == "X"][0]
        forearm_l = [p["graus"] for p in ch0 if p["osso"] == "LowerArm.L" and p["eixo"] == "X"][0]

        assert 46.0 <= thigh_l_x <= 58.0
        assert thigh_l_z == pytest.approx(-38.0, abs=4.0)
        assert thigh_r_z == pytest.approx(38.0, abs=4.0)
        assert knee_l == pytest.approx(-78.0, abs=5.0)
        assert chest_x <= -9.0
        assert head_x >= 8.0
        assert arm_l >= 30.0 and forearm_l >= 40.0


def test_slash_combo_and_cast_curves():
    clips = {c["nome"]: c for c in animacao.clipes(GODOT, "godot-humanoid@1", ["slash_combo", "cast"])}
    for nome in ("slash_combo", "cast"):
        c = clips[nome]
        assert c["loop"] is False
        assert 16 <= len(c["chaves"]) <= 32
        max_amp = max(abs(p["graus"]) for ch in c["chaves"] for p in ch["poses"])
        assert max_amp >= 70.0


def test_roblox_r15_upper_torso_separation():
    ret = profiles.retarget(ROBLOX, "r15@1")
    assert ret["quadril"] == "LowerTorso"
    assert ret["coluna"] == "UpperTorso"
    assert ret["tronco"] == "UpperTorso"

    idle = animacao.clipes(ROBLOX, "r15@1", ["idle"])[0]
    assert "LowerTorso" in idle["ossos"]
    assert "UpperTorso" in idle["ossos"]


_EXPR_BLENDER_CURVES = """
import json, math, sys
from pathlib import Path
import bpy
from mathutils import Euler, Quaternion, Vector

argv = sys.argv[sys.argv.index("--") + 1:]
sys.path.insert(0, argv[0])
clipes_json = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
out_json = Path(argv[2])
import autorig

bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)

arm = bpy.data.armatures.new("TestArm")
rig = bpy.data.objects.new("TestArm", arm)
bpy.context.collection.objects.link(rig)
bpy.context.view_layer.objects.active = rig
bpy.ops.object.mode_set(mode="EDIT")
for nome, pai, h, t in (
    ("HumanoidRootPart", None, (0, 0, 0), (0, 0, 0.1)),
    ("LowerTorso", "HumanoidRootPart", (0, 0, 0.8), (0, 0, 1.0)),
    ("UpperTorso", "LowerTorso", (0, 0, 1.0), (0, 0, 1.4)),
    ("Head", "UpperTorso", (0, 0, 1.4), (0, 0, 1.7)),
    ("LeftUpperArm", "UpperTorso", (0.2, 0, 1.35), (0.25, 0, 1.05)),
    ("RightUpperArm", "UpperTorso", (-0.2, 0, 1.35), (-0.25, 0, 1.05)),
    ("LeftUpperLeg", "LowerTorso", (0.1, 0, 0.8), (0.1, 0, 0.4)),
    ("RightUpperLeg", "LowerTorso", (-0.1, 0, 0.8), (-0.1, 0, 0.4)),
    ("LeftLowerLeg", "LeftUpperLeg", (0.1, 0, 0.4), (0.1, 0, 0.05)),
    ("RightLowerLeg", "RightUpperLeg", (-0.1, 0, 0.4), (-0.1, 0, 0.05)),
    ("LeftFoot", "LeftLowerLeg", (0.1, 0, 0.05), (0.1, 0.15, 0.02)),
    ("RightFoot", "RightLowerLeg", (-0.1, 0, 0.05), (-0.1, 0.15, 0.02)),
    ("LeftLowerArm", "LeftUpperArm", (0.25, 0, 1.05), (0.25, 0, 0.8)),
    ("RightLowerArm", "RightUpperArm", (-0.25, 0, 1.05), (-0.25, 0, 0.8)),
):
    eb = arm.edit_bones.new(nome)
    eb.head = Vector(h)
    eb.tail = Vector(t)
    if pai:
        eb.parent = arm.edit_bones[pai]
bpy.ops.object.mode_set(mode="OBJECT")

geradas = autorig.aplicar_animacoes_multi(rig, clipes_json)
linear_count = 0
bezier_auto = 0
for acao in bpy.data.actions:
    for fc in acao.fcurves:
        for kp in fc.keyframe_points:
            if kp.interpolation == "LINEAR":
                linear_count += 1
            elif kp.interpolation == "BEZIER" and kp.handle_left_type == "AUTO_CLAMPED" and kp.handle_right_type == "AUTO_CLAMPED":
                bezier_auto += 1

# Testa composicao multi-eixo em LeftUpperArm no frame 1
acao_comp = bpy.data.actions["comp_test"]
rig.animation_data.action = acao_comp
bpy.context.scene.frame_set(1)
q_obs = rig.pose.bones["LeftUpperArm"].rotation_quaternion.copy()
q_exp = (Quaternion((0, 0, 1), math.radians(15.0)) @ Quaternion((1, 0, 0), math.radians(30.0))).normalized()

out_json.write_text(json.dumps({
    "geradas": [g["nome"] for g in geradas],
    "linear_count": linear_count,
    "bezier_auto": bezier_auto,
    "quat_dot": abs(q_obs.dot(q_exp)),
}), encoding="utf-8")
"""


@pytest.mark.blender
def test_blender_bezier_auto_clamped_and_quaternion_composition(tmp_path: Path):
    blender = _blender_bin()
    clipes_env = animacao.clipes(ROBLOX, "r15@1", ["idle", "walk", "ride_idle"])
    clipes_env.append(
        {
            "nome": "comp_test",
            "fps": 24,
            "duracao_s": 0.5,
            "loop": False,
            "ossos": ["LeftUpperArm"],
            "chaves": [
                {
                    "frame": 1,
                    "segundos": 0.0,
                    "poses": [
                        {"osso": "LeftUpperArm", "graus": 15.0, "eixo": "Z"},
                        {"osso": "LeftUpperArm", "graus": 30.0, "eixo": "X"},
                    ],
                },
                {
                    "frame": 13,
                    "segundos": 0.5,
                    "poses": [{"osso": "LeftUpperArm", "graus": 0.0, "eixo": "X"}],
                },
            ],
        }
    )
    in_json = tmp_path / "clipes.json"
    out_json = tmp_path / "res.json"
    in_json.write_text(json.dumps(clipes_env), encoding="utf-8")
    proc = subprocess.run(
        [
            blender,
            "-b",
            "--factory-startup",
            "--python-exit-code",
            "1",
            "--python-expr",
            _EXPR_BLENDER_CURVES,
            "--",
            str(RAIZ / "blender"),
            str(in_json),
            str(out_json),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr
    res = json.loads(out_json.read_text(encoding="utf-8"))
    assert res["linear_count"] == 0
    assert res["bezier_auto"] > 50
    assert res["quat_dot"] == pytest.approx(1.0, abs=1e-5)
