"""Independent behavioral parity suite for v0.9.12 Roblox pipeline."""

from __future__ import annotations

import json
import math
import re
import subprocess
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import jsonschema
import pytest

from forge3d import (
    animacao, config, post, profiles, qc_roblox, qc_roblox_anim,
    rbx, rbx_acessorio, rbx_anim, rbx_r15_model, rbx_xml, sync_rojo,
)
from forge3d.cli import comandos
from forge3d.errors import ForgeError

RAIZ = Path(__file__).resolve().parents[1]
_BLENDER_DIR = RAIZ / "blender"
_LOTE_R15 = RAIZ / "examples" / "lote_09_r15.yaml"
_ANC_WIDE = {
    "Head": [0.0, 1.84, 0.0], "UpperTorso": [0.0, 1.35, 0.0], "LowerTorso": [0.0, 0.98, 0.0],
    "LeftUpperArm": [-0.24, 1.45, 0.0], "LeftLowerArm": [-0.54, 1.45, 0.0], "LeftHand": [-0.82, 1.45, 0.0],
    "RightUpperArm": [0.24, 1.45, 0.0], "RightLowerArm": [0.54, 1.45, 0.0], "RightHand": [0.82, 1.45, 0.0],
    "LeftUpperLeg": [-0.2265, 0.92, 0.0], "RightUpperLeg": [0.2265, 0.92, 0.0],
    "LeftFoot": [-0.2265, 0.04, 0.0], "RightFoot": [0.2265, 0.04, 0.0],
}
_ANC_NARROW = {
    "Head": [0.0, 1.80, 0.0], "UpperTorso": [0.0, 1.32, 0.0], "LowerTorso": [0.0, 0.94, 0.0],
    "LeftUpperLeg": [-0.11, 0.90, 0.0], "RightUpperLeg": [0.11, 0.90, 0.0],
    "LeftFoot": [-0.11, 0.04, 0.0], "RightFoot": [0.11, 0.04, 0.0],
}


@pytest.fixture(autouse=True)
def _isolar_forge3d(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORGE3D_HOME", str(tmp_path / "forge_home"))
    monkeypatch.setenv("FORGE3D_CONFIG", str(tmp_path / "forge_cfg"))
    config.adicionar(tmp_path)


def _exigir_blender() -> str:
    ok, _ = post.preflight()
    if not ok:
        pytest.skip("Blender 4.2 nao disponivel neste ambiente")
    return post.binario()


def _pose_mats(seq: ET.Element, bone: str) -> list[tuple[float, ...]]:
    return [
        qc_roblox_anim._rot_pose_mat3(pose)
        for kf in seq.findall("Item[@class='Keyframe']")
        for pose in kf.iter("Item")
        if pose.get("class") == "Pose" and pose.findtext("Properties/string[@name='Name']") == bone
    ]


def _z_col(m: tuple[float, ...]) -> float:
    return math.degrees(math.atan2(m[3], m[0]))


def _z_row(m: tuple[float, ...]) -> float:
    return math.degrees(math.atan2(-m[1], m[0]))


def _y_col(m: tuple[float, ...]) -> float:
    return math.degrees(math.atan2(-m[6], m[0]))


def _cf_pos_rot(cf: ET.Element | None) -> tuple[tuple[float, float, float], list[float]]:
    assert cf is not None
    pos = (float(cf.findtext("X") or 0), float(cf.findtext("Y") or 0), float(cf.findtext("Z") or 0))
    rot = [float(cf.findtext(f"R{i}{j}") or (1.0 if i == j else 0.0)) for i in range(3) for j in range(3)]
    return pos, rot


def _r15_partes_e_ancoras(
    *, invert_arm: str | None = None, zero_x: bool = False
) -> tuple[list[dict[str, Any]], dict[str, list[float]]]:
    base = {
        "LowerTorso": [0.0, 3.5, 0.0], "UpperTorso": [0.0, 4.3, 0.0], "Head": [0.0, 5.8, 0.0],
        "LeftUpperArm": [-0.9, 5.2, 0.0], "LeftLowerArm": [-1.2, 4.3, 0.0], "LeftHand": [-1.2, 3.5, 0.0],
        "RightUpperArm": [0.9, 5.2, 0.0], "RightLowerArm": [1.2, 4.3, 0.0], "RightHand": [1.2, 3.5, 0.0],
        "LeftUpperLeg": [-0.5, 3.3, 0.0], "LeftLowerLeg": [-0.5, 1.8, 0.0], "LeftFoot": [-0.5, 0.4, 0.0],
        "RightUpperLeg": [0.5, 3.3, 0.0], "RightLowerLeg": [0.5, 1.8, 0.0], "RightFoot": [0.5, 0.4, 0.0],
    }
    if zero_x:
        for coords in base.values():
            coords[0] = 0.0
    elif invert_arm == "left":
        base["LeftUpperArm"][0] = 0.9
    elif invert_arm == "right":
        base["RightUpperArm"][0] = -0.9
    partes = [
        {"nome": n, "junta": rbx_xml.JOINT_R15[n], "ancora": list(v), "centro_bbox": list(v), "arquivo": f"{n}.glb"}
        for n, v in base.items()
    ]
    return partes, {k: list(v) for k, v in base.items()}


# ------------------------------------------------------------------ 1) rbx_anim Motor6D & bone signs


def test_rbx_anim_motor6d_inverted_z_and_attack_signs() -> None:
    expected = {
        "LeftUpperArm", "RightUpperArm", "LeftLowerArm", "RightLowerArm",
        "LeftHand", "RightHand", "LeftUpperLeg", "RightUpperLeg", "LeftLowerLeg", "RightLowerLeg",
    }
    assert rbx_anim._PARTES_Z_INVERTIDO_MOTOR6D == expected
    excluded = {"LowerTorso", "UpperTorso", "Head", "HumanoidRootPart", "LeftFoot", "RightFoot"}
    assert not (excluded & rbx_anim._PARTES_Z_INVERTIDO_MOTOR6D)

    synth = {
        "nome": "synth", "duracao_s": 1.0, "loop": False,
        "chaves": [{"segundos": 0.5, "poses": [
            {"osso": "LowerTorso", "eixo": "Z", "graus": 15.0},
            {"osso": "UpperTorso", "eixo": "Z", "graus": -12.0},
            {"osso": "LeftUpperArm", "eixo": "Z", "graus": 20.0},
            {"osso": "RightUpperArm", "eixo": "Z", "graus": -25.0},
        ]}],
    }
    seq_m = ET.fromstring("\n".join(rbx_anim._sequencia_xml(synth, 1, modo_rig="motor6d")[0]))
    seq_b = ET.fromstring("\n".join(rbx_anim._sequencia_xml(synth, 1, modo_rig="bone")[0]))
    for part, ang_m, ang_b in (
        ("LowerTorso", 15.0, 15.0), ("UpperTorso", -12.0, -12.0),
        ("LeftUpperArm", -20.0, 20.0), ("RightUpperArm", 25.0, -25.0),
    ):
        assert _z_col(_pose_mats(seq_m, part)[0]) == pytest.approx(ang_m, abs=1e-3)
        assert _z_col(_pose_mats(seq_b, part)[0]) == pytest.approx(ang_b, abs=1e-3)

    perfil = profiles.carregar("roblox-r15")
    clip_map = {c["nome"]: c for c in animacao.clipes(perfil, "r15@1", ["jump", "attack"])}
    jm = ET.fromstring("\n".join(rbx_anim._sequencia_xml(clip_map["jump"], 1, modo_rig="motor6d")[0]))
    jb = ET.fromstring("\n".join(rbx_anim._sequencia_xml(clip_map["jump"], 1, modo_rig="bone")[0]))
    mid = len(_pose_mats(jm, "LowerTorso")) // 2
    assert _z_col(_pose_mats(jm, "LowerTorso")[1]) == pytest.approx(_z_col(_pose_mats(jb, "LowerTorso")[1]), abs=1e-3)
    assert _z_col(_pose_mats(jm, "LeftUpperArm")[mid]) == pytest.approx(-_z_col(_pose_mats(jb, "LeftUpperArm")[mid]), abs=1e-2)
    assert _z_col(_pose_mats(jm, "RightUpperArm")[mid]) == pytest.approx(-_z_col(_pose_mats(jb, "RightUpperArm")[mid]), abs=1e-2)

    am = ET.fromstring("\n".join(rbx_anim._sequencia_xml(clip_map["attack"], 1, modo_rig="motor6d")[0]))
    ab = ET.fromstring("\n".join(rbx_anim._sequencia_xml(clip_map["attack"], 1, modo_rig="bone")[0]))
    zs_m, zs_b = [_z_col(m) for m in _pose_mats(am, "RightUpperArm")], [_z_col(m) for m in _pose_mats(ab, "RightUpperArm")]
    idx_w, idx_s = round(0.25 * (len(zs_m) - 1)), round(0.50 * (len(zs_m) - 1))
    assert zs_m[idx_w] > 10.0 and zs_m[idx_s] < -10.0 and zs_b[idx_w] < -10.0 and zs_b[idx_s] > 10.0


def test_walk_run_foot_counter_roll_none_and_wide_ancoras() -> None:
    perfil = profiles.carregar("roblox-r15")
    clip_map = {c["nome"]: c for c in animacao.clipes(perfil, "r15@1", ["walk", "run"])}

    for nome in ("walk", "run"):
        seq_m = ET.fromstring("\n".join(rbx_anim._sequencia_xml(clip_map[nome], 1, ancoras=None, modo_rig="motor6d")[0]))
        seq_b = ET.fromstring("\n".join(rbx_anim._sequencia_xml(clip_map[nome], 1, ancoras=None, modo_rig="bone")[0]))
        for leg, foot in (("LeftUpperLeg", "LeftFoot"), ("RightUpperLeg", "RightFoot")):
            leg_m, foot_m = [_z_row(m) for m in _pose_mats(seq_m, leg)], [_z_col(m) for m in _pose_mats(seq_m, foot)]
            assert all(abs(lz + fz) < 1e-2 for lz, fz in zip(leg_m, foot_m)) and abs(sum(foot_m) / len(foot_m)) > 4.0
            leg_b = [_z_row(m) for m in _pose_mats(seq_b, leg)]
            foot_y, foot_z = [_y_col(m) for m in _pose_mats(seq_b, foot)], [_z_col(m) for m in _pose_mats(seq_b, foot)]
            assert all(abs(lz + fy) < 1e-2 for lz, fy in zip(leg_b, foot_y)) and all(abs(fz) < 1e-3 for fz in foot_z)
            assert abs(sum(foot_y) / len(foot_y)) > 4.0

    wm_none = ET.fromstring("\n".join(rbx_anim._sequencia_xml(clip_map["walk"], 1, ancoras=None, modo_rig="motor6d")[0]))
    wm_wide = ET.fromstring("\n".join(rbx_anim._sequencia_xml(clip_map["walk"], 1, ancoras=_ANC_WIDE, modo_rig="motor6d")[0]))
    wb_wide = ET.fromstring("\n".join(rbx_anim._sequencia_xml(clip_map["walk"], 1, ancoras=_ANC_WIDE, modo_rig="bone")[0]))
    for leg, foot in (("LeftUpperLeg", "LeftFoot"), ("RightUpperLeg", "RightFoot")):
        base_abs = sum(abs(_z_col(m)) for m in _pose_mats(wm_none, foot))
        w_m_leg, w_m_foot = [_z_row(m) for m in _pose_mats(wm_wide, leg)], [_z_col(m) for m in _pose_mats(wm_wide, foot)]
        assert sum(abs(v) for v in w_m_foot) > base_abs + 20.0
        assert all(abs(lz + fz) < 1e-2 for lz, fz in zip(w_m_leg, w_m_foot))
        w_b_leg = [_z_row(m) for m in _pose_mats(wb_wide, leg)]
        w_b_y, w_b_z = [_y_col(m) for m in _pose_mats(wb_wide, foot)], [_z_col(m) for m in _pose_mats(wb_wide, foot)]
        assert all(abs(lz + fy) < 1e-2 for lz, fy in zip(w_b_leg, w_b_y)) and all(abs(fz) < 1e-3 for fz in w_b_z)


# ------------------------------------------------------------------ 2) Blender R15 vs Godot sockets


_BLENDER_SOCKET_SCRIPT = """\
import json, sys, bpy
sys.path.insert(0, sys.argv[-2])
import autorig_anim_sockets as aas

def build_armature(name, defs):
    arm = bpy.data.armatures.new(name)
    obj = bpy.data.objects.new(name, arm)
    bpy.context.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode="EDIT")
    created = {}
    for bname, parent, head, tail in defs:
        eb = arm.edit_bones.new(bname)
        eb.head, eb.tail = head, tail
        if parent: eb.parent = created[parent]
        created[bname] = eb
    bpy.ops.object.mode_set(mode="OBJECT")
    return obj

r15_defs = [("HumanoidRootPart", None, (0, 0, 0.80), (0, 0, 0.90)), ("LowerTorso", "HumanoidRootPart", (0, 0, 0.85), (0, 0, 1.02)),
            ("UpperTorso", "LowerTorso", (0, 0, 1.02), (0, 0, 1.44)), ("Head", "UpperTorso", (0, 0, 1.44), (0, 0, 1.78))]
godot_defs = [("Root", None, (0, 0, 0.0), (0, 0, 0.1)), ("Hips", "Root", (0, 0, 0.85), (0, 0, 1.02)),
              ("Spine", "Hips", (0, 0, 1.02), (0, 0, 1.22)), ("Chest", "Spine", (0, 0, 1.22), (0, 0, 1.44)),
              ("Neck", "Chest", (0, 0, 1.44), (0, 0, 1.54)), ("Head", "Neck", (0, 0, 1.54), (0, 0, 1.78))]
for pfx, sfx, sg in (("Left", ".L", -1), ("Right", ".R", 1)):
    r15_defs += [(f"{pfx}UpperArm", "UpperTorso", (sg*0.18, 0, 1.40), (sg*0.31, 0, 1.11)),
                 (f"{pfx}LowerArm", f"{pfx}UpperArm", (sg*0.31, 0, 1.11), (sg*0.31, 0, 0.82)),
                 (f"{pfx}Hand", f"{pfx}LowerArm", (sg*0.31, 0, 0.82), (sg*0.31, 0, 0.67)),
                 (f"{pfx}UpperLeg", "LowerTorso", (sg*0.12, 0, 0.81), (sg*0.12, 0, 0.43)),
                 (f"{pfx}LowerLeg", f"{pfx}UpperLeg", (sg*0.12, 0, 0.43), (sg*0.12, 0, 0.12)),
                 (f"{pfx}Foot", f"{pfx}LowerLeg", (sg*0.12, 0, 0.12), (sg*0.12, -0.18, 0.04))]
    godot_defs += [(f"Shoulder{sfx}", "Chest", (sg*0.05, 0, 1.40), (sg*0.18, 0, 1.40)),
                   (f"UpperArm{sfx}", f"Shoulder{sfx}", (sg*0.18, 0, 1.40), (sg*0.31, 0, 1.11)),
                   (f"LowerArm{sfx}", f"UpperArm{sfx}", (sg*0.31, 0, 1.11), (sg*0.31, 0, 0.82)),
                   (f"Hand{sfx}", f"LowerArm{sfx}", (sg*0.31, 0, 0.82), (sg*0.31, 0, 0.67)),
                   (f"UpperLeg{sfx}", "Hips", (sg*0.12, 0, 0.81), (sg*0.12, 0, 0.43)),
                   (f"LowerLeg{sfx}", f"UpperLeg{sfx}", (sg*0.12, 0, 0.43), (sg*0.12, 0, 0.12)),
                   (f"Foot{sfx}", f"LowerLeg{sfx}", (sg*0.12, 0, 0.12), (sg*0.12, -0.18, 0.04))]
open(sys.argv[-1], "w", encoding="utf-8").write(json.dumps({
    "r15": aas.extrair_sockets(build_armature("R15Rig", r15_defs)),
    "godot": aas.extrair_sockets(build_armature("GodotRig", godot_defs)),
}))
"""


@pytest.mark.blender
def test_blender_r15_sockets_schema_export_and_godot_unchanged(tmp_path: Path) -> None:
    blender = _exigir_blender()
    script, out_json = tmp_path / "sockets_check.py", tmp_path / "sockets.json"
    script.write_text(_BLENDER_SOCKET_SCRIPT, encoding="utf-8")
    proc = subprocess.run(
        [blender, "--background", "--factory-startup", "--python-exit-code", "1",
         "--python", str(script), "--", str(_BLENDER_DIR), str(out_json)],
        capture_output=True, text=True, timeout=180,
    )
    assert proc.returncode == 0, f"Blender falhou:\nSTDOUT={proc.stdout}\nSTDERR={proc.stderr}"
    dados = json.loads(out_json.read_text(encoding="utf-8"))
    r15_socks = dados["r15"]
    schema_v7 = json.loads((RAIZ / "schemas" / "manifest.v7.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator({"$schema": schema_v7["$schema"], **schema_v7["properties"]["sockets"]}).validate(r15_socks)

    chaves_exatas = {"nome", "osso", "posicao_local", "rotacao_quat_wxyz", "frente_local"}
    por_nome = {s["nome"]: s for s in r15_socks}
    assert {"Hand.R", "Hand.L", "Back", "Head", "Shoulder.L", "Shoulder.R"} <= set(por_nome)
    for sock in r15_socks:
        assert set(sock.keys()) == chaves_exatas and sock["rotacao_quat_wxyz"] == [1.0, 0.0, 0.0, 0.0]
    assert por_nome["Hand.R"]["posicao_local"][0] < 0.0 and por_nome["Hand.R"]["posicao_local"][1] > 0.0
    assert por_nome["Hand.R"]["posicao_local"][2] < 0.0 and por_nome["Back"]["posicao_local"][2] > 0.0

    rbxlx = tmp_path / "r15_sock.rbxlx"
    rbx.exportar_r15(_LOTE_R15, "personagem.r15.guard.01", saida=rbxlx, sockets=r15_socks)
    root = ET.parse(rbxlx).getroot()
    att = next(el for el in root.iter("Item")
               if el.get("class") == "Attachment" and el.findtext("Properties/string[@name='Name']") == "RightGripAttachment")
    pos, rot = _cf_pos_rot(att.find("Properties/CoordinateFrame[@name='CFrame']"))
    assert pos[1] < 0.0 and rot == pytest.approx([1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0], abs=1e-6)

    godot_by_name = {s["nome"]: s for s in dados["godot"]}
    assert godot_by_name["Hand.R"]["rotacao_quat_wxyz"] != [1.0, 0.0, 0.0, 0.0]
    assert godot_by_name["Hand.L"]["rotacao_quat_wxyz"] != [1.0, 0.0, 0.0, 0.0]


# ------------------------------------------------------------------ 3) Studio Lua laterality


def test_studio_lua_laterality() -> None:
    rbxlx_entries = re.findall(
        r"\b(Left\w+|Right\w+)\s*=\s*\{\s*([-+]?\d+(?:\.\d+)?)\s*,",
        (RAIZ / "tools" / "r15_rbxlx_test.lua").read_text(encoding="utf-8"),
    )
    left_r = [float(x) for n, x in rbxlx_entries if n.startswith("Left")]
    right_r = [float(x) for n, x in rbxlx_entries if n.startswith("Right")]
    assert len(left_r) == 6 and len(right_r) == 6 and all(x < 0.0 for x in left_r) and all(x > 0.0 for x in right_r)

    studio_entries = re.findall(
        r'name\s*=\s*"((?:Left|Right)\w+)"[^}]*head\s*=\s*\{\s*([-+]?\d+(?:\.\d+)?)[^}]*\}\s*,\s*tail\s*=\s*\{\s*([-+]?\d+(?:\.\d+)?)',
        (RAIZ / "tools" / "r15_studio_test.lua").read_text(encoding="utf-8"),
    )
    left_s = [(float(hx), float(tx)) for n, hx, tx in studio_entries if n.startswith("Left")]
    right_s = [(float(hx), float(tx)) for n, hx, tx in studio_entries if n.startswith("Right")]
    assert len(left_s) == 6 and len(right_s) == 6
    assert all(hx < 0.0 and tx < 0.0 for hx, tx in left_s) and all(hx > 0.0 and tx > 0.0 for hx, tx in right_s)


# ------------------------------------------------------------------ 4) Grip & Tool export


def test_grip_socket_and_tool_export(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert "Grip" in rbx_acessorio._MAPA_ATT_SOCKETS["RightGripAttachment"]
    man = {
        "schema": "forge3d/manifest@7", "asset_id": "arma.espada.01", "anexo": {"parte": "arma"},
        "sockets": [{"nome": "Grip", "osso": "Weapon", "posicao_local": [0.05, -0.4, 0.1],
                     "rotacao_quat_wxyz": [0.70710678, 0.70710678, 0.0, 0.0], "frente_local": [0.0, 0.0, -1.0]}],
        "texturas": {"ColorMap": "rbxassetid://777"},
    }
    rot90x = [1.0, 0.0, 0.0, 0.0, 0.0, -1.0, 0.0, 1.0, 0.0]

    acc_res = rbx_acessorio.exportar_acessorio_rbxmx(man, saida=tmp_path / "acc.rbxmx", ledger=False)
    assert acc_res["classe_roblox"] == "Accessory"
    acc_item = ET.fromstring(acc_res["xml"]).find("Item[@class='Accessory']")
    assert acc_item is not None
    ap_pos, ap_rot = _cf_pos_rot(acc_item.find("Properties/CoordinateFrame[@name='AttachmentPoint']"))
    att_pos, att_rot = _cf_pos_rot(acc_item.find(".//Item[@class='Attachment']/Properties/CoordinateFrame[@name='CFrame']"))
    assert ap_pos == pytest.approx((0.05, -0.4, 0.1), abs=1e-5) and ap_rot == pytest.approx(rot90x, abs=1e-5)
    assert att_pos == pytest.approx((0.05, -0.4, 0.1), abs=1e-5) and att_rot == pytest.approx(rot90x, abs=1e-5)

    for tipo_arg in ("Tool", "tool"):
        tool_res = rbx_acessorio.exportar_acessorio_rbxmx(
            man, saida=tmp_path / f"item_{tipo_arg}.rbxmx", ledger=False, tipo_item_roblox=tipo_arg
        )
        assert tool_res["classe_roblox"] == "Tool"
        root_t = ET.fromstring(tool_res["xml"])
        tool_el = root_t.find("Item[@class='Tool']")
        assert tool_el is not None
        assert tool_el.findtext("Properties/bool[@name='RequiresHandle']") == "true"
        assert tool_el.findtext("Properties/bool[@name='CanBeDropped']") == "true"
        g_pos, g_rot = _cf_pos_rot(tool_el.find("Properties/CoordinateFrame[@name='Grip']"))
        assert g_pos == pytest.approx((0.05, -0.4, 0.1), abs=1e-5) and g_rot == pytest.approx(rot90x, abs=1e-5)
        handle = tool_el.find("Item[@class='MeshPart']")
        assert handle is not None and handle.findtext("Properties/string[@name='Name']") == "Handle"
        assert handle.find("Item[@class='Attachment']") is not None and handle.find("Item[@class='SurfaceAppearance']") is not None
        assert not [el for el in root_t.iter("Item") if el.get("class") == "WeldConstraint"]

    with pytest.raises(ForgeError) as exc_info:
        rbx_acessorio.exportar_acessorio_rbxmx(man, saida=tmp_path / "bad.rbxmx", ledger=False, tipo_item_roblox="Hat")
    assert exc_info.value.codigo == "FORGE-E-SPEC"

    man_path = tmp_path / "arma.espada.01.manifest.json"
    man_path.write_text(json.dumps(man), encoding="utf-8")
    assert comandos.despachar(["export-acessorio", str(man_path), "--tipo", "Tool", "--no-ledger", "--json"]) == 0
    cli_out = json.loads(capsys.readouterr().out)
    expected_out = tmp_path / "arma.espada.01_tool.rbxmx"
    assert cli_out["classe_roblox"] == "Tool" and expected_out.is_file() and Path(cli_out["saida"]) == expected_out


# ------------------------------------------------------------------ 5) rbx_r15_model attachments & SurfaceAppearance


def test_rbx_r15_model_attachments_surface_and_png_strip(tmp_path: Path) -> None:
    partes, ancoras = _r15_partes_e_ancoras()
    seg_man = {
        "schema": "forge3d/manifest@7", "asset_id": "heroi.seg.01",
        "rig": {"modo": "motor6d", "ancoras": ancoras}, "partes": partes,
        "texturas": {"ColorMap": "heroi_baseColor.png", "NormalMap": "heroi_normal.png", "MetalnessMap": "heroi_metal.png"},
        "files": [{"papel": "textura_roughness", "caminho": "heroi_roughness.png"}],
    }
    perfil = profiles.carregar("roblox-r15")
    item = {"id": "heroi.seg.01", "esqueleto": "r15@1", "animacoes_base": ["idle", "walk"]}
    aids = {"ColorMap": "111", "NormalMap": "222", "RoughnessMap": "333", "MetalnessMap": "444"}

    out_ok = tmp_path / "model_ok.rbxlx"
    res = rbx_r15_model.exportar_r15_model(
        item, perfil, "heroi.seg.01", "r15@1", 0.28, "987654",
        saida=out_ok, ledger=False, modo_rig="motor6d", manifesto=seg_man, asset_ids=aids,
    )
    assert res["attachments_script"] is True and res["textura"] is True
    assert res["surface_appearance"] == {
        "ColorMap": "rbxassetid://111", "NormalMap": "rbxassetid://222",
        "RoughnessMap": "rbxassetid://333", "MetalnessMap": "rbxassetid://444",
    }

    root = ET.parse(out_ok).getroot()
    load_script = next(el for el in root.iter("Item")
                       if el.get("class") == "Script" and el.findtext("Properties/string[@name='Name']") == "Forge3DLoadModel")
    src = load_script.findtext("Properties/ProtectedString[@name='Source']") or ""
    for tok in ("RightGripAttachment", "LeftGripAttachment", "BodyBackAttachment", "HatAttachment",
                "LeftCollarAttachment", "RightCollarAttachment", "SurfaceAppearance", "Enum.AlphaMode.Overlay",
                "rbxassetid://111", "rbxassetid://222", "rbxassetid://333", "rbxassetid://444"):
        assert tok in src

    res_rbx = rbx.exportar_r15(
        _LOTE_R15, "personagem.r15.guard.01", saida=tmp_path / "via_rbx.rbxlx",
        model_id="987654", manifesto=seg_man, asset_ids=aids, ledger=False,
    )
    assert res_rbx["attachments_script"] is True and res_rbx["textura"] is True

    for modo in ("motor6d", "bone"):
        out_png = tmp_path / f"model_nopng_{modo}.rbxlx"
        res_nopng = rbx_r15_model.exportar_r15_model(
            item, perfil, "heroi.seg.01", "r15@1", 0.28, "987654", saida=out_png, ledger=False,
            modo_rig=modo, manifesto=seg_man, mapas_pbr={"MetalnessMap": "local_metalness.png"},
        )
        assert res_nopng["textura"] is False and "surface_appearance" not in res_nopng
        assert ".png" not in out_png.read_text(encoding="utf-8").lower()


# ------------------------------------------------------------------ 6) QC G13 & G14 hardening


def test_qc_g13_ancoras_laterality_and_zero_x() -> None:
    partes_ok, anc_ok = _r15_partes_e_ancoras()
    assert qc_roblox.verificar_g13_ancoras({"rig": {"modo": "motor6d"}}, {"partes": partes_ok, "ancoras": anc_ok}, 3.5714)["status"] == "ok"
    for inv in ("left", "right"):
        partes_inv, anc_inv = _r15_partes_e_ancoras(invert_arm=inv)
        res_inv = qc_roblox.verificar_g13_ancoras({"rig": {"modo": "motor6d"}}, {"partes": partes_inv, "ancoras": anc_inv}, 3.5714)
        assert res_inv["status"] == "falhou" and res_inv["codigo"] == "FORGE-E-QC"
        assert any("lateralidade_invertida" in p for p in res_inv["medido"]["problemas"])
    partes_z, anc_z = _r15_partes_e_ancoras(zero_x=True)
    assert qc_roblox.verificar_g13_ancoras({"rig": {"modo": "motor6d"}}, {"partes": partes_z, "ancoras": anc_z}, 3.5714)["status"] == "ok"


def _mutar_pose_z_rbxmx(src: Path, dst: Path, bone: str, *, modo: str) -> None:
    root = ET.parse(src).getroot()
    for pose in root.iter("Item"):
        if pose.get("class") != "Pose" or pose.findtext("Properties/string[@name='Name']") != bone:
            continue
        cf = pose.find("Properties/CoordinateFrame[@name='CFrame']")
        assert cf is not None
        vals = ([1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0] if modo == "identidade"
                else [float(cf.findtext(f"R{i}{j}") or 0.0) for i in range(3) for j in range(3)])
        if modo != "identidade":
            vals[1], vals[3], vals[5], vals[7] = -vals[1], -vals[3], -vals[5], -vals[7]
        for idx, (i, j) in enumerate((i, j) for i in range(3) for j in range(3)):
            if (node := cf.find(f"R{i}{j}")) is not None:
                node.text = f"{vals[idx]:.6f}"
    dst.write_text(ET.tostring(root, encoding="unicode"), encoding="utf-8")


def test_qc_g14_ancoras_propagation_and_sign_checks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    perfil = profiles.carregar("roblox-r15")
    item_idle = {"id": "p.idle", "esqueleto": "r15@1", "rig": {"modo": "motor6d"}, "animacoes_base": ["idle"]}
    assert (qc_roblox_anim.verificar_g14_animacao_roblox(item_idle, perfil, tmp_path, [], ancoras=_ANC_WIDE)["medido"]["amplitude_max_graus"]
            > qc_roblox_anim.verificar_g14_animacao_roblox(item_idle, perfil, tmp_path, [], ancoras=None)["medido"]["amplitude_max_graus"])

    capturado: dict[str, Any] = {}
    orig_seq = rbx_anim._sequencia_xml

    def _spy_seq(clipe: dict, ref: int, mps: float = 0.28, *, ancoras=None, modo_rig: str = "motor6d"):
        linhas, prox = orig_seq(clipe, ref, mps=mps, ancoras=ancoras, modo_rig=modo_rig)
        if clipe.get("nome") == "walk":
            capturado["ancoras"], capturado["seq"] = ancoras, ET.fromstring("\n".join(linhas))
        return linhas, prox

    item_walk = {"id": "p.walk", "esqueleto": "r15@1", "rig": {"modo": "motor6d"}, "animacoes_base": ["walk"]}
    with monkeypatch.context() as mp:
        mp.setattr(rbx_anim, "_sequencia_xml", _spy_seq)
        g14_walk_wide = qc_roblox_anim.verificar_g14_animacao_roblox(item_walk, perfil, tmp_path, [], ancoras=_ANC_WIDE)
    assert g14_walk_wide["status"] == "ok" and capturado["ancoras"] == _ANC_WIDE
    seq_narrow = ET.fromstring("\n".join(orig_seq(animacao.clipes(perfil, "r15@1", ["walk"])[0], 1, ancoras=_ANC_NARROW, modo_rig="motor6d")[0]))
    assert sum(abs(_z_row(m)) for m in _pose_mats(capturado["seq"], "LeftUpperLeg")) > sum(abs(_z_row(m)) for m in _pose_mats(seq_narrow, "LeftUpperLeg"))

    walk_ok, atk_ok = tmp_path / "walk_ok.rbxmx", tmp_path / "atk_ok.rbxmx"
    rbx_anim.exportar_animacao(_LOTE_R15, "personagem.r15.guard.01", "walk", saida=walk_ok)
    rbx_anim.exportar_animacao(_LOTE_R15, "personagem.r15.guard.01", "attack", saida=atk_ok)
    item_m6d = {"id": "p.m6d", "esqueleto": "r15@1", "rig": {"modo": "motor6d"}}
    assert qc_roblox_anim.verificar_g14_animacao_roblox(item_m6d, perfil, tmp_path, [{"papel": "animacao", "caminho": "walk_ok.rbxmx"}])["status"] == "ok"
    assert qc_roblox_anim.verificar_g14_animacao_roblox(
        item_m6d, perfil, tmp_path, [{"papel": "animacao", "caminho": "walk_ok.rbxmx"}, {"papel": "animacao", "caminho": "atk_ok.rbxmx"}]
    )["status"] == "ok"
    for idx, (src_p, bone, modo_mut, esperado, incl_walk) in enumerate((
        (walk_ok, "LeftUpperLeg", "inverter", "sinal_z_invertido:walk:LeftUpperLeg", False),
        (walk_ok, "LeftFoot", "identidade", "sinal_z_invertido:walk:LeftFoot", False),
        (walk_ok, "LeftFoot", "inverter", "sinal_z_invertido:walk:LeftFoot", False),
        (atk_ok, "RightUpperArm", "inverter", "sinal_z_invertido:attack:RightUpperArm", True),
    )):
        mut = tmp_path / f"bad_{idx}.rbxmx"
        _mutar_pose_z_rbxmx(src_p, mut, bone, modo=modo_mut)
        arqs = ([{"papel": "animacao", "caminho": "walk_ok.rbxmx"}] if incl_walk else []) + [{"papel": "animacao", "caminho": mut.name}]
        g14_bad = qc_roblox_anim.verificar_g14_animacao_roblox(item_m6d, perfil, tmp_path, arqs)
        assert g14_bad["status"] == "falhou" and esperado in g14_bad["medido"]["problemas"]


def test_profiles_and_sync_rojo_metadata(tmp_path: Path) -> None:
    p_r15 = profiles.carregar("roblox-r15")
    assert p_r15["rig"]["max_ossos"] == 64
    ret_r15, map_r15 = p_r15["rig"]["retarget"], p_r15["rig"]["mapas"]
    assert "mao_e" not in ret_r15["r15@1"] and "mao_d" not in ret_r15["r15@1"] and len(ret_r15["r15@1"]) == 16
    for esq in ("quadruped@1", "winged_mount@1"):
        assert ret_r15[esq] and map_r15[esq] and set(ret_r15[esq].values()) <= set(map_r15[esq])
    assert {"pata_dianteira_e", "pata_traseira_d", "sela"} <= set(ret_r15["quadruped@1"])
    assert {"asa_ombro_e", "asa_ponta_d", "sela"} <= set(ret_r15["winged_mount@1"])
    p_aa80 = profiles.carregar("roblox-aa-80")
    assert p_aa80["rig"]["retarget"]["r15@1"]["mao_e"] == "LeftHand" and p_aa80["rig"]["retarget"]["r15@1"]["mao_d"] == "RightHand"

    origem_dir, outro_dir = tmp_path / "origem_proj", tmp_path / "outro_proj"
    sock_stub = [{"nome": "Grip", "osso": "Weapon", "posicao_local": [0.0, 0.0, 0.0], "rotacao_quat_wxyz": [1.0, 0.0, 0.0, 0.0], "frente_local": [0.0, 0.0, -1.0]}]
    for pasta, aid, proj, rbx_id, parte, osso, pnome in (
        (origem_dir, "espada.01", "jogo_a", "111222", "arma", "RightHand", "Handle"),
        (outro_dir, "alien.01", "jogo_b", "999888", "capa", "UpperTorso", "Wing"),
    ):
        pasta.mkdir()
        (pasta / f"{aid}.manifest.json").write_text(json.dumps({
            "schema": "forge3d/manifest@7", "asset_id": aid, "projeto": proj, "rbxassetid": rbx_id,
            "anexo": {"parte": parte, "osso": osso}, "sockets": sock_stub, "partes": [{"nome": pnome, "arquivo": f"{pnome}.glb"}],
        }), encoding="utf-8")

    lua_meta = tmp_path / "rojo_out" / "Assets.lua"
    res_meta = sync_rojo.gerar_assets_lua([origem_dir, outro_dir], lua_meta, origem_escopo=origem_dir, incluir_metadados=True)
    assert set(res_meta["metadados"]) == {"espada.01"} and set(res_meta["metadados"]["espada.01"]) == {"anexo", "sockets", "partes"}
    txt_meta = lua_meta.read_text(encoding="utf-8")
    assert "Assets._meta = {" in txt_meta and '"espada.01"' in txt_meta and "alien.01" not in txt_meta
    assert all(k in txt_meta for k in ('"anexo"', '"sockets"', '"partes"'))

    lua_default = tmp_path / "rojo_out" / "AssetsDefault.lua"
    res_default = sync_rojo.gerar_assets_lua([origem_dir, outro_dir], lua_default, origem_escopo=origem_dir)
    assert "metadados" not in res_default and "_meta" not in lua_default.read_text(encoding="utf-8")
