"""Testes TDD independentes (@pytest.mark.blender, janela limpa) para v0.9.10 — Contratos F-01, F-02, F-03, F-05, F-06 e F-08."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from PIL import Image, ImageDraw

from forge3d import animacao, config, post, profiles, qc

RAIZ = Path(__file__).resolve().parents[1]
_BLENDER_DIR = RAIZ / "blender"


@pytest.fixture(autouse=True)
def _isolar_forge3d(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORGE3D_HOME", str(tmp_path / "forge_home"))
    monkeypatch.setenv("FORGE3D_CONFIG", str(tmp_path / "forge_cfg"))
    config.adicionar(tmp_path)


def _exigir_blender() -> str:
    try:
        ok, _ = post.preflight()
        blender = post.binario() if ok else None
    except Exception:
        blender = None
    if not blender:
        pytest.skip("Blender 4.2 nao disponivel neste ambiente")
    return blender


_BOSS_BLENDER_SCRIPT = """
import json, math, os, sys, bpy, bmesh
from mathutils import Vector

cfg = json.loads(open(sys.argv[-1], encoding="utf-8").read())
sys.path.insert(0, cfg["blender_dir"])
import autorig, autorig_marcos, autorig_ossos, autorig_anim_sockets, postprocess, postprocess_deform

def build_boss_mesh(name="boss_apose45"):
    bm = bmesh.new()
    def box(cx, cy, cz, sx, sy, sz, cuts=2):
        bm_t = bmesh.new()
        bmesh.ops.create_cube(bm_t, size=1.0)
        for v in bm_t.verts:
            v.co.x = v.co.x * sx + cx
            v.co.y = v.co.y * sy + cy
            v.co.z = v.co.z * sz + cz
        if cuts > 0:
            bmesh.ops.subdivide_edges(bm_t, edges=list(bm_t.edges), cuts=cuts, use_grid_fill=True)
        me_t = bpy.data.meshes.new("_tmp")
        bm_t.to_mesh(me_t)
        bm_t.free()
        bm.from_mesh(me_t)
        bpy.data.meshes.remove(me_t)

    # Altura total h = 2.00m (z in [0.00, 2.00])
    # 1) Pes e pernas em X = +-0.32m (+-0.16*h)
    for s in (1.0, -1.0):
        box(s * 0.32, 0.03, 0.06, 0.14, 0.22, 0.12, cuts=2)  # Foot (z: 0.00..0.12)
        box(s * 0.32, 0.00, 0.28, 0.15, 0.16, 0.36, cuts=2)  # LowerLeg (z: 0.10..0.46)
        box(s * 0.32, 0.00, 0.68, 0.18, 0.18, 0.48, cuts=2)  # UpperLeg (z: 0.44..0.92)

    # 2) Pelve e cintura limpa em f in [0.48..0.59] (z: 0.96..1.18, w_waist = 0.24m = 0.12*h)
    box(0.0, 0.0, 0.96, 0.56, 0.24, 0.16, cuts=2)  # Hips (x: +-0.28, z: 0.88..1.04)
    box(0.0, 0.0, 1.11, 0.48, 0.24, 0.18, cuts=3)  # Waist limpa (x: +-0.24, z: 1.02..1.20)
    # Torax central (y_back = -0.14, y_front = +0.14, z: 1.20..1.60)
    box(0.0, 0.0, 1.40, 0.56, 0.28, 0.40, cuts=3)  # Chest (x: +-0.28, y: -0.14..0.14, z: 1.20..1.60)

    # 3) Axila/Pauldron soldado ao torax em f >= 0.61 (z: 1.22..1.68) + braco A-pose 45 deg
    # com cotovelo angulado e manopla densa baixa em X = +-0.84 (+-0.42*h, z: 0.42..0.94)
    for s in (1.0, -1.0):
        box(s * 0.46, 0.00, 1.40, 0.38, 0.26, 0.36, cuts=3)  # Armpit/Deltoid soldado (x: 0.27..0.65, z: 1.22..1.58)
        box(s * 0.48, 0.00, 1.56, 0.32, 0.28, 0.24, cuts=2)  # Pauldron alto (x: 0.32..0.64, z: 1.44..1.68)
        box(s * 0.64, 0.10, 1.24, 0.20, 0.20, 0.24, cuts=2)  # Cotovelo angulado (+Y=0.10, z: 1.12..1.36)
        box(s * 0.76, 0.04, 1.02, 0.18, 0.18, 0.26, cuts=3)  # Forearm mid (x: 0.67..0.85, z: 0.89..1.15)
        box(s * 0.84, -0.02, 0.68, 0.18, 0.20, 0.48, cuts=4) # Manopla densa baixa (x: 0.75..0.93, z: 0.44..0.92)

    # 4) Pescoco, cabeca e chifres largos (z: 1.58..2.00, chifres sobrepoem AABB de Pauldron/UpperArm em X=0.32..0.42, Z=1.60..2.00)
    box(0.0, 0.0, 1.63, 0.22, 0.22, 0.14, cuts=1)  # Neck
    box(0.0, 0.0, 1.75, 0.28, 0.26, 0.22, cuts=1)  # Head (z: 1.64..1.86)
    for s in (1.0, -1.0):
        box(s * 0.24, -0.01, 1.74, 0.22, 0.16, 0.24, cuts=1)  # Horn base (x: 0.13..0.35, z: 1.62..1.86)
        box(s * 0.35, -0.02, 1.89, 0.16, 0.16, 0.22, cuts=1)  # Horn tip (x: 0.27..0.43, z: 1.78..2.00)

    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    mod_rem = obj.modifiers.new("VoxelWeld", "REMESH")
    mod_rem.mode = "VOXEL"
    mod_rem.voxel_size = 0.042
    bpy.ops.object.modifier_apply(modifier=mod_rem.name)
    postprocess.reparar_malha(obj)
    return obj

def build_vertical_arm_mesh(name="hero_vert"):
    bm = bmesh.new()
    def box(cx, cy, cz, sx, sy, sz):
        res = bmesh.ops.create_cube(bm, size=1.0)
        for v in res["verts"]:
            v.co.x = v.co.x * sx + cx
            v.co.y = v.co.y * sy + cy
            v.co.z = v.co.z * sz + cz
    box(0.0, 0.0, 1.15, 0.44, 0.22, 0.62)
    box(0.0, 0.0, 1.66, 0.24, 0.24, 0.26)
    for s in (1.0, -1.0):
        box(s * 0.12, 0.0, 0.44, 0.16, 0.16, 0.88)
        box(s * 0.30, 0.0, 1.12, 0.12, 0.12, 0.64)
    bmesh.ops.subdivide_edges(bm, edges=list(bm.edges), cuts=1, use_grid_fill=True)
    bmesh.ops.triangulate(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(obj)
    return obj

out = {}

# 1) F-01 Marcos + Godot-AA Cape
bpy.ops.wm.read_factory_settings(use_empty=True)
obj_aa = build_boss_mesh("boss_aa")
zs_aa = [v.co.z for v in obj_aa.data.vertices]
h_aa = max(zs_aa) - min(zs_aa)
dorsal_ys = [v.co.y for v in obj_aa.data.vertices if 1.20 <= v.co.z <= 1.56 and abs(v.co.x) <= 0.22]
dorsal_min_y, dorsal_max_y = min(dorsal_ys), max(dorsal_ys)
marcos = autorig_marcos.estimar_marcos(obj_aa)
rig_aa, _ = autorig.auto_rigar_humanoide(obj_aa, "godot-humanoid-aa@1", postprocess.criar_armadura)
cape_bone = rig_aa.data.bones.get("Cape")
out["f01_marcos_cape"] = {
    "h": h_aa,
    "leg_x_L": float(marcos["leg_x_L"]),
    "leg_x_R": float(marcos["leg_x_R"]),
    "torso_hw": float(marcos["torso_hw"]),
    "has_torso_back_y": "torso_back_y" in marcos,
    "has_torso_front_y": "torso_front_y" in marcos,
    "torso_back_y": float(marcos.get("torso_back_y", 999.0)),
    "torso_front_y": float(marcos.get("torso_front_y", -999.0)),
    "dorsal_min_y": float(dorsal_min_y),
    "dorsal_max_y": float(dorsal_max_y),
    "cy": float(marcos["cy"]),
    "cape_head_y": float(cape_bone.head_local.y) if cape_bone else None,
}

# 2) F-01 R15 Geodesic Skinning + G16 + F-05 Sagittal Roll + F-02 Ground-Clamp + F-08 Droop + F-06 Export for Split
bpy.ops.wm.read_factory_settings(use_empty=True)
obj_r15 = build_boss_mesh("boss_r15")
zs = [v.co.z for v in obj_r15.data.vertices]
h = max(zs) - min(zs)
horn_top_z = max(zs)
rig_r15, _ = autorig.auto_rigar_humanoide(obj_r15, "r15@1", postprocess.criar_armadura)

vgs = {vg.index: vg.name for vg in obj_r15.vertex_groups}
dom_counts = {b.name: 0 for b in rig_r15.data.bones}
forearm_in_leg_or_torso = 0
for v in obj_r15.data.vertices:
    pesos = [(g.weight, vgs[g.group]) for g in v.groups if g.group in vgs and g.weight > 1e-5]
    if not pesos:
        continue
    _, dom_name = max(pesos)
    dom_counts[dom_name] = dom_counts.get(dom_name, 0) + 1
    if abs(v.co.x) >= 0.35 * h and 0.44 <= v.co.z <= 1.10:
        if dom_name in ("LeftUpperLeg", "RightUpperLeg", "LeftLowerLeg", "RightLowerLeg", "LowerTorso"):
            forearm_in_leg_or_torso += 1

b_lla = rig_r15.data.bones["LeftLowerArm"]
b_rla = rig_r15.data.bones["RightLowerArm"]
lx_arm = b_lla.matrix_local.to_3x3().col[0].normalized()
rx_arm = b_rla.matrix_local.to_3x3().col[0].normalized()
out["f05_roll"] = {
    "left_x": [float(lx_arm.x), float(lx_arm.y), float(lx_arm.z)],
    "right_x": [float(rx_arm.x), float(rx_arm.y), float(rx_arm.z)],
}

foot_bones_r15 = [rig_r15.data.bones[n] for n in ("LeftFoot", "RightFoot") if n in rig_r15.data.bones]
z_chao_rest = min(min(float((rig_r15.matrix_world @ b.head_local).z), float((rig_r15.matrix_world @ b.tail_local).z)) for b in foot_bones_r15)
geradas_r15 = autorig.aplicar_animacoes_multi(rig_r15, cfg["clipes_r15"])
deform_r15 = postprocess_deform.medir_deformacao_animacao(obj_r15, rig_r15, geradas_r15)

out["f01_r15_skin_g16"] = {
    "dom_counts": dom_counts,
    "forearm_in_leg_or_torso": forearm_in_leg_or_torso,
    "max_stretch": float(deform_r15["max_stretch"]) if deform_r15 else 999.0,
    "deform": deform_r15,
}

cena = bpy.context.scene
min_foot_z_por_clipe = {}
wrist_swing_por_clipe = {}
for nome_c in ("death", "walk", "run", "attack", "idle"):
    acao = next((a for a in bpy.data.actions if a.name.startswith(f"{nome_c}_") or a.name == nome_c), None)
    if acao is None:
        continue
    rig_r15.animation_data.action = acao
    f0, f1 = int(round(acao.frame_range[0])), int(round(acao.frame_range[1]))
    min_z_c = 999.0
    xs_w, ys_w = [], []
    for fr in range(f0, f1 + 1):
        cena.frame_set(fr)
        bpy.context.view_layer.update()
        for fn_b in ("LeftFoot", "RightFoot"):
            pb = rig_r15.pose.bones[fn_b]
            wh = (rig_r15.matrix_world @ pb.head).z
            wt = (rig_r15.matrix_world @ pb.tail).z
            min_z_c = min(min_z_c, float(wh), float(wt))
        if nome_c == "attack":
            p_rel = rig_r15.pose.bones["UpperTorso"].matrix.inverted() @ rig_r15.pose.bones["RightHand"].head
            xs_w.append(float(p_rel.x))
            ys_w.append(float(p_rel.z))
        else:
            wh_hand = rig_r15.matrix_world @ rig_r15.pose.bones["LeftHand"].head
            xs_w.append(float(wh_hand.x))
            ys_w.append(float(wh_hand.y))
    min_foot_z_por_clipe[nome_c] = min_z_c
    wrist_swing_por_clipe[nome_c] = {"dx": max(xs_w) - min(xs_w), "dy": max(ys_w) - min(ys_w)}

out["f02_ground_clamp"] = {"z_chao_rest": z_chao_rest, "min_foot_z_por_clipe": min_foot_z_por_clipe}
out["f05_wrist_swing"] = wrist_swing_por_clipe

f08_info = {}
try:
    import autorig_pose_natural as apn
    info_apose = apn.calcular_caimento_braco_rig(rig_r15)
    acao_idle = next((a for a in bpy.data.actions if a.name.startswith("idle_") or a.name == "idle"), None)
    rig_r15.animation_data.action = acao_idle
    cena.frame_set(1)
    bpy.context.view_layer.update()
    pb_ua = rig_r15.pose.bones["LeftUpperArm"]
    vec_pose = (rig_r15.matrix_world @ pb_ua.tail) - (rig_r15.matrix_world @ pb_ua.head)
    theta_pose_deg = math.degrees(math.atan2(abs(vec_pose.x), max(-vec_pose.z, 1e-5)))

    obj_v = build_vertical_arm_mesh("hero_vert")
    rig_v, _ = autorig.auto_rigar_humanoide(obj_v, "r15@1", postprocess.criar_armadura)
    info_vert = apn.calcular_caimento_braco_rig(rig_v)
    f08_info = {"ok_import": True, "info_apose": info_apose, "theta_pose_idle_deg": float(theta_pose_deg), "info_vert": info_vert}
except Exception as exc:
    f08_info = {"ok_import": False, "erro": str(exc)}
out["f08_droop"] = f08_info

for o_extra in list(bpy.data.objects):
    if o_extra not in (obj_r15, rig_r15):
        bpy.data.objects.remove(o_extra, do_unlink=True)
rig_r15.animation_data_clear()
for pb in rig_r15.pose.bones:
    pb.matrix_basis.identity()
bpy.context.view_layer.update()
bpy.ops.export_scene.gltf(filepath=cfg["boss_glb"], export_format="GLB", export_yup=True)
out["f06_meta"] = {"horn_top_z": float(horn_top_z), "h": float(h)}

open(cfg["out_json"], "w", encoding="utf-8").write(json.dumps(out))
"""


@pytest.fixture(scope="module")
def _boss_bundle(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    blender = _exigir_blender()
    work_dir = tmp_path_factory.mktemp("v0910_boss_blender")
    perfil_r15 = profiles.carregar("roblox-aa-80")
    clipes_r15 = animacao.clipes(perfil_r15, "r15@1", ["idle", "walk", "run", "attack", "death"])
    boss_glb = work_dir / "boss_r15.glb"
    out_json = work_dir / "boss_report.json"
    cfg_path = work_dir / "cfg.json"
    script_path = work_dir / "run_boss.py"

    cfg_path.write_text(
        json.dumps({"blender_dir": str(_BLENDER_DIR), "clipes_r15": clipes_r15, "boss_glb": str(boss_glb), "out_json": str(out_json)}),
        encoding="utf-8",
    )
    script_path.write_text(_BOSS_BLENDER_SCRIPT, encoding="utf-8")
    proc = subprocess.run(
        [blender, "--background", "--factory-startup", "--python-exit-code", "1", "--python", str(script_path), "--", str(cfg_path)],
        capture_output=True, text=True, timeout=240,
    )
    assert proc.returncode == 0, f"Blender boss script falhou:\nSTDOUT={proc.stdout}\nSTDERR={proc.stderr}"
    report = json.loads(out_json.read_text(encoding="utf-8"))
    report["work_dir"] = work_dir
    report["boss_glb"] = boss_glb
    report["blender"] = blender
    return report


@pytest.mark.blender
def test_f01_blender_boss_marcos_cape_e_r15_skin_g16(_boss_bundle: dict[str, Any]) -> None:
    mc = _boss_bundle["f01_marcos_cape"]
    h = float(mc["h"])
    assert mc["has_torso_back_y"] is True and mc["has_torso_front_y"] is True
    assert mc["torso_back_y"] < 0.0 < mc["torso_front_y"]
    assert abs(mc["leg_x_L"]) <= 0.24 * h and abs(mc["leg_x_R"]) <= 0.24 * h
    assert mc["torso_hw"] <= 0.30 * h
    assert mc["cape_head_y"] is not None
    assert mc["dorsal_min_y"] - 0.03 * h <= mc["cape_head_y"] <= mc["cy"] - 0.03 * h

    sk = _boss_bundle["f01_r15_skin_g16"]
    dom = sk["dom_counts"]
    assert dom.get("LeftUpperArm", 0) > 0 and dom.get("RightUpperArm", 0) > 0
    assert sk["forearm_in_leg_or_torso"] == 0
    assert float(sk["max_stretch"]) <= 8.5, f"G16 excedeu 8.5x no boss R15: {sk['deform']}"


@pytest.mark.blender
def test_f02_blender_fk_ground_clamp_boss(_boss_bundle: dict[str, Any]) -> None:
    gc = _boss_bundle["f02_ground_clamp"]
    z_chao = float(gc["z_chao_rest"])
    min_z_map = gc["min_foot_z_por_clipe"]
    for clipe_nome in ("death", "walk", "run", "attack"):
        assert clipe_nome in min_z_map
        assert float(min_z_map[clipe_nome]) >= z_chao - 0.005, (
            f"Pe afundou abaixo do solo em '{clipe_nome}': min_z={min_z_map[clipe_nome]:.4f} < z_chao={z_chao:.4f}"
        )


@pytest.mark.blender
def test_f05_blender_sagittal_arm_roll_e_wrist_swing(_boss_bundle: dict[str, Any]) -> None:
    roll = _boss_bundle["f05_roll"]
    lx, rx = roll["left_x"], roll["right_x"]
    assert lx[0] >= 0.85 and rx[0] >= 0.85, f"Eixo local X do antebraco fora do plano sagital: L={lx}, R={rx}"
    assert abs(lx[1]) <= 0.15 and abs(rx[1]) <= 0.15, f"Eixo local X do antebraco vazou para Y: L={lx}, R={rx}"
    assert abs(lx[0] - rx[0]) <= 0.05 and abs(lx[2] + rx[2]) <= 0.05

    swing = _boss_bundle["f05_wrist_swing"]
    for nome_c in ("walk", "attack"):
        dx, dy = float(swing[nome_c]["dx"]), float(swing[nome_c]["dy"])
        assert dy / max(dx, 1e-6) >= 2.0, f"Pulso moveu-se lateralmente em '{nome_c}': dy={dy:.4f}, dx={dx:.4f}"


@pytest.mark.blender
def test_f06_blender_r15_split_15_partes_chifres_e_g12(_boss_bundle: dict[str, Any]) -> None:
    from forge3d.rbx_xml import JOINT_R15

    blender = _boss_bundle["blender"]
    work_dir: Path = _boss_bundle["work_dir"]
    boss_glb: Path = _boss_bundle["boss_glb"]
    horn_top_z = float(_boss_bundle["f06_meta"]["horn_top_z"])
    h = float(_boss_bundle["f06_meta"]["h"])

    split_dir = work_dir / "split_out"
    job_json = work_dir / "split_job.json"
    resumo_json = work_dir / "split_resumo.json"
    partes_cfg = [{"nome": nome, "junta": junta} for nome, junta in JOINT_R15.items()]
    job_json.write_text(json.dumps({"glb": str(boss_glb), "saida": str(split_dir), "partes": partes_cfg}), encoding="utf-8")

    proc = subprocess.run(
        [blender, "--background", "--factory-startup", "--python", str(_BLENDER_DIR / "split_por_ossos.py"), "--", str(job_json), str(resumo_json)],
        capture_output=True, text=True, timeout=180,
    )
    assert proc.returncode == 0, f"split_por_ossos falhou:\nSTDOUT={proc.stdout}\nSTDERR={proc.stderr}"
    resumo = json.loads(resumo_json.read_text(encoding="utf-8"))
    assert len(resumo["partes"]) == 15

    partes_por_nome: dict[str, dict] = {}
    for parte in resumo["partes"]:
        partes_por_nome[parte["nome"]] = parte
        g_p, b_p = qc.ler_glb_bin(split_dir / parte["arquivo"])
        topo = qc.topologia(g_p, b_p)
        assert topo["bordas_abertas"] == 0 and topo["nao_manifold"] == 0, f"Parte {parte['nome']} nao estanque: {topo}"

    # World Y-up top of Head = centro_bbox[1] + 0.5 * bbox[1] (must preserve horn top at Z=2.0m without truncation by UpperArm)
    p_head = partes_por_nome["Head"]
    head_world_max_y = float(p_head["centro_bbox"][1]) + 0.5 * float(p_head["bbox"][1])
    assert head_world_max_y >= horn_top_z - 0.03, (
        f"Chifres de Head truncados no split: head_world_max_y={head_world_max_y:.3f} vs {horn_top_z:.3f}"
    )

    # World max |X| of LeftUpperLeg = abs(centro_bbox[0]) + 0.5 * bbox[0] (must stay on thigh <= 0.28 * h)
    p_leg = partes_por_nome["LeftUpperLeg"]
    leg_world_max_x = abs(float(p_leg["centro_bbox"][0])) + 0.5 * float(p_leg["bbox"][0])
    assert leg_world_max_x <= 0.28 * h, f"LeftUpperLeg invadiu antebraco em X={leg_world_max_x:.3f} (> {0.28 * h:.3f})"

    g12 = qc.verificar_g12_separacao({"partes": resumo["partes"], "rig": {"modo": "motor6d"}}, split_dir, resumo, 1.0)
    assert g12["status"] == "ok" and float(g12["medido"]["penetracao_max_mm"]) <= 2.0, g12


@pytest.mark.blender
def test_f08_blender_arm_gravity_droop_apose_vs_vertical(_boss_bundle: dict[str, Any]) -> None:
    f08 = _boss_bundle["f08_droop"]
    assert f08.get("ok_import") is True, f"Falha em autorig_pose_natural: {f08.get('erro')}"
    info_apose = f08["info_apose"]
    assert info_apose["aplicavel"] is True
    assert 12.0 <= float(info_apose["delta_total_graus"]) <= 26.0
    assert float(f08["theta_pose_idle_deg"]) <= 26.0, (
        f"Braco A-pose nao desceu para <= 26 deg no frame 1 de idle: {f08['theta_pose_idle_deg']:.2f} deg"
    )
    info_vert = f08["info_vert"]
    assert info_vert["aplicavel"] is False and float(info_vert["delta_total_graus"]) == pytest.approx(0.0)


@pytest.mark.blender
def test_f03_blender_pbr_bake_ior_ao_floor_e_emissive_glb(tmp_path: Path) -> None:
    blender = _exigir_blender()
    saida = tmp_path / "pbr_out"
    saida.mkdir()
    src_tex = tmp_path / "src.png"
    img_src = Image.new("RGBA", (64, 64), (48, 50, 56, 255))
    d_src = ImageDraw.Draw(img_src)
    d_src.rectangle((20, 20, 44, 44), fill=(245, 165, 25, 255))
    img_src.save(src_tex)

    em_hint = tmp_path / "emissive_hint.png"
    img_em = Image.new("L", (64, 64), 0)
    d_em = ImageDraw.Draw(img_em)
    d_em.rectangle((20, 20, 44, 44), fill=240)
    img_em.save(em_hint)

    glb_out = saida / "orb_emissive.glb"
    res_json = tmp_path / "pbr_res.json"
    codigo = f"""
import json, sys, bpy
from array import array
sys.path.insert(0, {str(_BLENDER_DIR)!r})
import postprocess, bake_pbr, bake_pbr_maps

postprocess.limpar_cena()
img_ao_zero = bpy.data.images.new("ao_zero", width=16, height=16, alpha=False)
img_ao_zero.colorspace_settings.name = "Non-Color"
buf_z = array("f", [0.0, 0.0, 0.0, 1.0] * (16 * 16))
img_ao_zero.pixels.foreach_set(buf_z)
img_orm_t = bake_pbr_maps._empacotar_orm(img_ao_zero, "orm_test", 16)
buf_orm = array("f", [0.0] * (16 * 16 * 4))
img_orm_t.pixels.foreach_get(buf_orm)
min_ao_orm = min(buf_orm[i] for i in range(0, len(buf_orm), 4))

bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=16, radius=0.6)
obj = bpy.context.active_object
ca = obj.data.color_attributes.new("Color", "FLOAT_COLOR", "POINT")
for i in range(len(obj.data.vertices)):
    ca.data[i].color = (0.25, 0.26, 0.28, 1.0)

res = bake_pbr.executar_bake_high_low(
    obj=obj,
    saida_dir={str(saida)!r},
    nome_base="orb_emissive",
    px=128,
    limite_triangulos=300,
    reparo_fn=postprocess.reparar_malha,
    decimar_fn=postprocess.decimar,
    suavizar_fn=postprocess.suavizar_por_angulo,
    uv_fn=postprocess.desdobrar_uv,
    origem_textura={str(src_tex)!r},
    emissive_hint={str(em_hint)!r},
)
mat = obj.data.materials[0]
bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
spec_ior = float(bsdf.inputs["Specular IOR Level"].default_value)
postprocess.exportar({str(glb_out)!r}, [obj], False)
open({str(res_json)!r}, "w", encoding="utf-8").write(json.dumps({{
    "min_ao_orm": float(min_ao_orm),
    "spec_ior": spec_ior,
    "res": res,
}}))
"""
    proc = subprocess.run(
        [blender, "--background", "--factory-startup", "--python-exit-code", "1", "--python-expr", codigo],
        capture_output=True, text=True, timeout=180,
    )
    assert proc.returncode == 0, f"Blender PBR bake falhou:\nSTDOUT={proc.stdout}\nSTDERR={proc.stderr}"
    dados = json.loads(res_json.read_text(encoding="utf-8"))
    assert float(dados["spec_ior"]) == pytest.approx(0.50)
    assert float(dados["min_ao_orm"]) >= 0.34

    with Image.open(saida / "orb_emissive_orm.png") as im_orm:
        r_ext, _g_ext, _b_ext = im_orm.getextrema()
        assert r_ext[0] >= 86, f"Canal R (AO) de _orm.png caiu abaixo de 0.34 (86/255): {r_ext}"

    papeis = {a["papel"] for a in dados["res"]["arquivos_textura"]}
    assert "emissive" not in papeis
    gltf = qc.ler_glb(glb_out)
    mat_gltf = gltf["materials"][0]
    assert "emissiveTexture" in mat_gltf, f"emissiveTexture ausente no GLB exportado: {mat_gltf}"
