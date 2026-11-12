"""Testes de skinning geodésico topológico em ``blender/autorig.py``."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from forge3d import post, profiles

RAIZ = Path(__file__).resolve().parents[1]


def _blender_bin() -> str:
    try:
        ok, _ = post.preflight()
        if ok:
            return post.binario()
    except Exception:
        pass
    pytest.skip("Blender 4.2 nao disponivel neste ambiente")


_SCRIPT_BLENDER = """
import json
import sys
import time
import bpy
import bmesh

cfg = json.loads(open(sys.argv[-1], encoding="utf-8").read())
sys.path.insert(0, cfg["blender_dir"])
import autorig
import postprocess

bpy.ops.wm.read_factory_settings(use_empty=True)
bm = bmesh.new()


def make_tube(x0, x1, y0, y1, z_vals):
    rings = []
    for z in z_vals:
        v00 = bm.verts.new((x0, y0, z))
        v10 = bm.verts.new((x1, y0, z))
        v11 = bm.verts.new((x1, y1, z))
        v01 = bm.verts.new((x0, y1, z))
        rings.append((v00, v10, v11, v01))
    for k in range(len(rings) - 1):
        a, b = rings[k], rings[k + 1]
        for i in range(4):
            ni = (i + 1) % 4
            bm.faces.new((a[i], a[ni], b[ni], b[i]))
    bm.faces.new((rings[0][3], rings[0][2], rings[0][1], rings[0][0]))
    bm.faces.new(rings[-1])
    return rings


# Torso+hips X in [-0.14, 0.14], arms hanging at |X| in [0.17, 0.25] (vao aereo 0.03 m)
torso = make_tube(-0.14, 0.14, -0.08, 0.08, [0.77, 0.90, 1.05, 1.24, 1.34])
leg_l = make_tube(0.03, 0.13, -0.06, 0.06, [0.0, 0.12, 0.42, 0.77])
leg_r = make_tube(-0.13, -0.03, -0.06, 0.06, [0.0, 0.12, 0.42, 0.77])
head = make_tube(-0.09, 0.09, -0.09, 0.09, [1.34, 1.48, 1.84])
arm_l = make_tube(0.17, 0.25, -0.04, 0.04, [0.68, 0.80, 1.05, 1.24, 1.34])
arm_r = make_tube(-0.25, -0.17, -0.04, 0.04, [0.68, 0.80, 1.05, 1.24, 1.34])

if cfg.get("com_capa"):
    cape = make_tube(-0.14, 0.14, -0.18, -0.13, [0.45, 0.85, 1.24, 1.34])
    bm.edges.new((torso[4][0], cape[3][3]))
    bm.edges.new((torso[4][1], cape[3][2]))

for a, b in zip(torso[-1], head[0]):
    bm.edges.new((a, b))
bm.edges.new((torso[0][1], leg_l[-1][1]))
bm.edges.new((torso[0][2], leg_l[-1][2]))
bm.edges.new((torso[0][0], leg_r[-1][0]))
bm.edges.new((torso[0][3], leg_r[-1][3]))

# Bracos conectados APENAS na regiao do ombro (z in [1.24, 1.34])
for k in (3, 4):
    bm.edges.new((torso[k][1], arm_l[k][0]))
    bm.edges.new((torso[k][2], arm_l[k][3]))
    bm.edges.new((torso[k][0], arm_r[k][1]))
    bm.edges.new((torso[k][3], arm_r[k][2]))

bmesh.ops.subdivide_edges(bm, edges=list(bm.edges), cuts=int(cfg["cuts"]), use_grid_fill=True)

# Ilha desconexa pequena: belt pouch no quadril frontal direito
ret = bmesh.ops.create_cube(bm, size=1.0)
for v in ret["verts"]:
    v.co.x = v.co.x * 0.06 - 0.10
    v.co.y = v.co.y * 0.05 + 0.12
    v.co.z = v.co.z * 0.08 + 0.86
pouch_edges = [e for e in bm.edges if e.verts[0].co.y > 0.094 and e.verts[1].co.y > 0.094]
bmesh.ops.subdivide_edges(bm, edges=pouch_edges, cuts=2, use_grid_fill=True)

me = bpy.data.meshes.new("humanoide_arms_down")
bm.to_mesh(me)
bm.free()
obj = bpy.data.objects.new("humanoide_arms_down", me)
bpy.context.collection.objects.link(obj)

t0 = time.perf_counter()
rig_obj, grupos = autorig.auto_rigar_humanoide(obj, cfg["esqueleto"], postprocess.criar_armadura)
duracao_s = time.perf_counter() - t0

vgs = {vg.index: vg.name for vg in obj.vertex_groups}
sem_peso = 0
max_inf = 0
max_soma_err = 0.0
hip_max_arm = 0.0
arm_max_torso_leg = 0.0
arm_min_arm = 1.0
cape_max_leg_arm = 0.0
pouch_weights = []

for v in obj.data.vertices:
    ws = {vgs[g.group]: g.weight for g in v.groups if g.weight > 1e-6}
    if not ws:
        sem_peso += 1
        continue
    max_inf = max(max_inf, len(ws))
    max_soma_err = max(max_soma_err, abs(sum(ws.values()) - 1.0))

    if abs(v.co.x) <= 0.1401 and 0.77 <= v.co.z <= 1.00 and abs(v.co.y) <= 0.0801:
        aw = sum(w for n, w in ws.items() if "Arm" in n or "Hand" in n)
        hip_max_arm = max(hip_max_arm, aw)

    if abs(v.co.x) >= 0.1699 and 0.68 <= v.co.z <= 1.05 and abs(v.co.y) <= 0.0401:
        tw = sum(w for n, w in ws.items() if n in autorig._OSSOS_TRONCO or n in autorig._OSSOS_PERNA)
        aw = sum(w for n, w in ws.items() if n in autorig._OSSOS_BRACO)
        arm_max_torso_leg = max(arm_max_torso_leg, tw)
        arm_min_arm = min(arm_min_arm, aw)

    if cfg.get("com_capa") and v.co.y < -0.12 and v.co.z < 1.00:
        cw = sum(w for n, w in ws.items() if n in autorig._OSSOS_PERNA or n in autorig._OSSOS_BRACO)
        cape_max_leg_arm = max(cape_max_leg_arm, cw)

    if v.co.y > 0.094:
        pouch_weights.append(ws)

rel = {
    "n_verts": len(obj.data.vertices),
    "duracao_s": duracao_s,
    "ossos": [b.name for b in rig_obj.data.bones],
    "sem_peso": sem_peso,
    "max_inf": max_inf,
    "max_soma_err": max_soma_err,
    "hip_max_arm": hip_max_arm,
    "arm_max_torso_leg": arm_max_torso_leg,
    "arm_min_arm": arm_min_arm,
    "cape_max_leg_arm": cape_max_leg_arm,
    "pouch_count": len(pouch_weights),
    "pouch_bones": sorted({k for pw in pouch_weights for k in pw}),
    "pouch_arm_max": max(
        (sum(w for n, w in pw.items() if "Arm" in n or "Hand" in n) for pw in pouch_weights),
        default=0.0,
    ),
    "grupos_qtd": len(grupos),
}
open(cfg["out_json"], "w", encoding="utf-8").write(json.dumps(rel))
"""


def _executar_blender_geodesico(
    tmp_path: Path,
    esqueleto: str,
    cuts: int = 4,
    com_capa: bool = False,
) -> dict:
    blender = _blender_bin()
    tag = f"{esqueleto.replace('@', '_')}_c{cuts}_{'capa' if com_capa else 'base'}"
    script = tmp_path / f"geo_{tag}.py"
    cfg_path = tmp_path / f"cfg_{tag}.json"
    out_json = tmp_path / f"out_{tag}.json"

    script.write_text(_SCRIPT_BLENDER, encoding="utf-8")
    cfg_path.write_text(
        json.dumps(
            {
                "blender_dir": str(RAIZ / "blender"),
                "esqueleto": esqueleto,
                "cuts": cuts,
                "com_capa": com_capa,
                "out_json": str(out_json),
            }
        ),
        encoding="utf-8",
    )

    proc = subprocess.run(
        [blender, "--background", "--factory-startup", "--python", str(script), "--", str(cfg_path)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert out_json.is_file()
    return json.loads(out_json.read_text(encoding="utf-8"))


@pytest.mark.blender
@pytest.mark.parametrize(
    ("perfil_nome", "esqueleto", "ossos_tronco_pelve"),
    [
        ("godot4", "godot-humanoid@1", {"Hips", "Spine", "Spine1", "Chest"}),
        ("roblox-r15", "r15@1", {"LowerTorso", "UpperTorso"}),
    ],
)
def test_autorig_geodesico_arms_down_sem_sangramento_e_pouch(
    tmp_path: Path,
    perfil_nome: str,
    esqueleto: str,
    ossos_tronco_pelve: set[str],
):
    rel = _executar_blender_geodesico(tmp_path, esqueleto, cuts=4, com_capa=False)
    perfil = profiles.carregar(perfil_nome)
    mapa_esperado = perfil["rig"]["mapas"][esqueleto]

    assert len(rel["ossos"]) == len(mapa_esperado)
    assert set(rel["ossos"]) == set(mapa_esperado)
    assert rel["sem_peso"] == 0
    assert 1 <= rel["max_inf"] <= 4
    assert rel["max_soma_err"] < 1e-4

    # Quadril ao lado do vao aereo de 0.03 m nao recebe pesos de braco/mao
    assert rel["hip_max_arm"] < 0.01
    # Antebraco/mao nao sangra para tronco/pernas e mantem dominio de braco
    assert rel["arm_max_torso_leg"] < 0.05
    assert rel["arm_min_arm"] > 0.90

    # Belt pouch desconexo liga-se de modo coerente a um unico osso de torso/pelve
    assert rel["pouch_count"] > 0
    assert len(rel["pouch_bones"]) == 1
    assert set(rel["pouch_bones"]) <= ossos_tronco_pelve
    assert rel["pouch_arm_max"] == 0.0


@pytest.mark.blender
def test_autorig_geodesico_capa_solta_e_desempenho_12k(tmp_path: Path):
    rel = _executar_blender_geodesico(tmp_path, "godot-humanoid@1", cuts=10, com_capa=False)
    assert rel["n_verts"] >= 10000
    assert rel["sem_peso"] == 0
    assert rel["max_inf"] <= 4
    assert rel["max_soma_err"] < 1e-4
    assert rel["hip_max_arm"] < 0.01
    assert rel["arm_max_torso_leg"] < 0.05
    assert rel["duracao_s"] < 1.2, f"auto_rigar_humanoide lento para {rel['n_verts']} verts: {rel['duracao_s']:.3f}s"

    rel_capa = _executar_blender_geodesico(tmp_path, "godot-humanoid@1", cuts=5, com_capa=True)
    assert rel_capa["sem_peso"] == 0
    assert rel_capa["cape_max_leg_arm"] < 0.01
    assert rel_capa["hip_max_arm"] < 0.01
    assert len(rel_capa["pouch_bones"]) == 1


_SCRIPT_ISOLAMENTO = """
import json
import math
import sys
import bpy
import bmesh

cfg = json.loads(open(sys.argv[-1], encoding="utf-8").read())
sys.path.insert(0, cfg["blender_dir"])
import autorig
import postprocess

if cfg["modo"] == "mpfb2":
    import template_body
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    try:
        template_body.criar_humano(dict(template_body.MACRO_PADRAO), {})
    except Exception as exc:
        open(cfg["out_json"], "w", encoding="utf-8").write(json.dumps({"skip": str(exc)}))
        sys.exit(0)
    obj = [o for o in bpy.data.objects if o.type == "MESH"][0]
    for r in [o for o in bpy.data.objects if o.type == "ARMATURE"]:
        bpy.data.objects.remove(r, do_unlink=True)
    template_body.limpar_helpers(obj)
    obj.modifiers.clear()
    obj.vertex_groups.clear()
else:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bm = bmesh.new()

    def make_tube(x0, x1, y0, y1, z_vals):
        rings = []
        for z in z_vals:
            v00 = bm.verts.new((x0, y0, z))
            v10 = bm.verts.new((x1, y0, z))
            v11 = bm.verts.new((x1, y1, z))
            v01 = bm.verts.new((x0, y1, z))
            rings.append((v00, v10, v11, v01))
        for k in range(len(rings) - 1):
            a, b = rings[k], rings[k + 1]
            for i in range(4):
                ni = (i + 1) % 4
                bm.faces.new((a[i], a[ni], b[ni], b[i]))
        bm.faces.new((rings[0][3], rings[0][2], rings[0][1], rings[0][0]))
        bm.faces.new(rings[-1])
        return rings

    torso = make_tube(-0.14, 0.14, -0.08, 0.08, [0.80, 0.96, 1.12, 1.32, 1.45])
    leg_l = make_tube(0.03, 0.13, -0.06, 0.06, [0.0, 0.12, 0.44, 0.80])
    leg_r = make_tube(-0.13, -0.03, -0.06, 0.06, [0.0, 0.12, 0.44, 0.80])
    neck = make_tube(-0.05, 0.05, -0.05, 0.05, [1.45, 1.57])
    head = make_tube(-0.08, 0.08, -0.08, 0.08, [1.57, 1.71, 1.84])
    arm_l = make_tube(0.17, 0.25, -0.04, 0.04, [0.72, 0.88, 1.12, 1.32, 1.45])
    arm_r = make_tube(-0.25, -0.17, -0.04, 0.04, [0.72, 0.88, 1.12, 1.32, 1.45])

    for a, b in zip(torso[-1], neck[0]):
        bm.edges.new((a, b))
    for a, b in zip(neck[-1], head[0]):
        bm.edges.new((a, b))
    bm.edges.new((torso[0][1], leg_l[-1][1]))
    bm.edges.new((torso[0][2], leg_l[-1][2]))
    bm.edges.new((torso[0][0], leg_r[-1][0]))
    bm.edges.new((torso[0][3], leg_r[-1][3]))
    for k in (3, 4):
        bm.edges.new((torso[k][1], arm_l[k][0]))
        bm.edges.new((torso[k][2], arm_l[k][3]))
        bm.edges.new((torso[k][0], arm_r[k][1]))
        bm.edges.new((torso[k][3], arm_r[k][2]))

    bmesh.ops.subdivide_edges(bm, edges=list(bm.edges), cuts=4, use_grid_fill=True)
    me = bpy.data.meshes.new("humanoide_isolamento")
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new("humanoide_isolamento", me)
    bpy.context.collection.objects.link(obj)

rig_obj, _ = autorig.auto_rigar_humanoide(obj, cfg["esqueleto"], postprocess.criar_armadura)
m = autorig.estimar_marcos(obj)
zs = [v.co.z for v in obj.data.vertices]
z_min, z_max = min(zs), max(zs)
h = z_max - z_min
vgs = {vg.index: vg.name for vg in obj.vertex_groups}

eh_r15 = cfg["esqueleto"] == "r15@1"
back_ok = (lambda v: v.co.y > 0.02) if cfg["modo"] == "mpfb2" else (lambda v: abs(v.co.y) <= 0.0801)
dorso_cs = []
dorso_head_max = 0.0
lumbar_trunk = []
lumbar_arm_max = 0.0
foot_leg_max = 0.0
sem_peso = 0
max_inf = 0
max_soma_err = 0.0

for v in obj.data.vertices:
    ws = {vgs[g.group]: g.weight for g in v.groups if g.weight > 1e-6}
    if not ws:
        sem_peso += 1
        continue
    max_inf = max(max_inf, len(ws))
    max_soma_err = max(max_soma_err, abs(sum(ws.values()) - 1.0))
    rz = (v.co.z - z_min) / h

    if rz < 0.06:
        leg_b = ("LeftUpperLeg", "RightUpperLeg", "LowerTorso") if eh_r15 else ("UpperLeg.L", "UpperLeg.R", "Hips")
        foot_leg_max = max(foot_leg_max, sum(ws.get(b, 0.0) for b in leg_b))

    if 0.65 <= rz <= 0.78 and abs(v.co.x) <= m["torso_hw"] * 0.60 and back_ok(v):
        dorso_head_max = max(dorso_head_max, ws.get("Head", 0.0))
        core = ("UpperTorso", "LowerTorso") if eh_r15 else ("Chest", "Spine1", "Spine")
        dorso_cs.append(sum(ws.get(b, 0.0) for b in core))

    if 0.50 <= rz <= 0.64 and abs(v.co.x) <= m["torso_hw"] * 0.90 and (v.co.y > 0.02 if cfg["modo"] == "mpfb2" else True):
        core = ("LowerTorso", "UpperTorso") if eh_r15 else ("Hips", "Spine", "Spine1", "Chest")
        arm_b = ("LeftUpperArm", "RightUpperArm", "LeftHand", "RightHand") if eh_r15 else ("UpperArm.L", "UpperArm.R", "Hand.L", "Hand.R")
        lumbar_trunk.append(sum(ws.get(b, 0.0) for b in core))
        lumbar_arm_max = max(lumbar_arm_max, sum(ws.get(b, 0.0) for b in arm_b))

bpy.context.view_layer.objects.active = rig_obj
bpy.ops.object.mode_set(mode="POSE")


def eval_disp(pose_fn, filt_fn):
    for pb in rig_obj.pose.bones:
        pb.rotation_mode = "XYZ"
        pb.rotation_euler = (0.0, 0.0, 0.0)
    pose_fn()
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    dm = ev.to_mesh()
    max_d = 0.0
    for v, dv in zip(obj.data.vertices, dm.vertices):
        if filt_fn(v):
            max_d = max(max_d, (dv.co - v.co).length)
    ev.to_mesh_clear()
    return max_d


ua_l = "LeftUpperArm" if eh_r15 else "UpperArm.L"
ua_r = "RightUpperArm" if eh_r15 else "UpperArm.R"
arm_x_min = m["torso_hw"] * 1.15
dorso_filt = lambda v: 0.65 * h <= (v.co.z - z_min) <= 0.77 * h and abs(v.co.x) <= m["torso_hw"] * 0.55 and back_ok(v)

head_self_disp = eval_disp(
    lambda: setattr(rig_obj.pose.bones["Head"], "rotation_euler", (0.0, math.radians(30), 0.0)),
    lambda v: (v.co.z - z_min) >= 0.90 * h,
)
dorso_head_disp = eval_disp(
    lambda: setattr(rig_obj.pose.bones["Head"], "rotation_euler", (0.0, math.radians(30), 0.0)),
    dorso_filt,
)
arm_self_disp = eval_disp(
    lambda: setattr(rig_obj.pose.bones[ua_l], "rotation_euler", (0.0, math.radians(45), 0.0)),
    lambda v: v.co.x >= arm_x_min and (v.co.z - z_min) <= 0.78 * h,
)
dorso_arms_disp = eval_disp(
    lambda: (
        setattr(rig_obj.pose.bones[ua_l], "rotation_euler", (0.0, math.radians(45), 0.0)),
        setattr(rig_obj.pose.bones[ua_r], "rotation_euler", (0.0, math.radians(-45), 0.0)),
    ),
    dorso_filt,
)

open(cfg["out_json"], "w", encoding="utf-8").write(json.dumps({
    "sem_peso": sem_peso,
    "max_inf": max_inf,
    "max_soma_err": max_soma_err,
    "chest_top_rel": (m["chest_top_z"] - z_min) / h,
    "foot_leg_max": foot_leg_max,
    "dorso_head_max": dorso_head_max,
    "dorso_cs_avg": sum(dorso_cs) / max(len(dorso_cs), 1),
    "lumbar_trunk_avg": sum(lumbar_trunk) / max(len(lumbar_trunk), 1),
    "lumbar_arm_max": lumbar_arm_max,
    "head_self_disp": head_self_disp,
    "dorso_head_disp": dorso_head_disp,
    "arm_self_disp": arm_self_disp,
    "dorso_arms_disp": dorso_arms_disp,
}))
"""


def _executar_isolamento(tmp_path: Path, esqueleto: str, modo: str) -> dict:
    blender = _blender_bin()
    tag = f"{modo}_{esqueleto.replace('@', '_')}"
    script = tmp_path / f"iso_{tag}.py"
    cfg_path = tmp_path / f"iso_cfg_{tag}.json"
    out_json = tmp_path / f"iso_out_{tag}.json"

    script.write_text(_SCRIPT_ISOLAMENTO, encoding="utf-8")
    cfg_path.write_text(
        json.dumps(
            {
                "blender_dir": str(RAIZ / "blender"),
                "esqueleto": esqueleto,
                "modo": modo,
                "out_json": str(out_json),
            }
        ),
        encoding="utf-8",
    )

    cmd = [blender, "--background"]
    if modo != "mpfb2":
        cmd.append("--factory-startup")
    cmd.extend(["--python", str(script), "--", str(cfg_path)])

    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert out_json.is_file()
    return json.loads(out_json.read_text(encoding="utf-8"))


@pytest.mark.blender
@pytest.mark.parametrize("esqueleto", ["godot-humanoid@1", "r15@1"])
def test_autorig_isolamento_dorso_cabeca_e_poses(tmp_path: Path, esqueleto: str):
    rel = _executar_isolamento(tmp_path, esqueleto, "sintetico")
    assert rel["sem_peso"] == 0
    assert rel["max_inf"] <= 4
    assert rel["max_soma_err"] < 1e-4
    assert rel["foot_leg_max"] < 0.01
    assert rel["dorso_head_max"] == 0.0
    assert rel["dorso_cs_avg"] >= 0.85
    assert rel["lumbar_trunk_avg"] >= 0.95
    assert rel["lumbar_arm_max"] < 0.02
    assert rel["head_self_disp"] > 0.02
    assert rel["dorso_head_disp"] < 0.002
    assert rel["arm_self_disp"] > 0.05
    assert rel["dorso_arms_disp"] < 0.002


@pytest.mark.blender
def test_autorig_mpfb2_dorso_ombro_e_poses(tmp_path: Path):
    rel = _executar_isolamento(tmp_path, "godot-humanoid@1", "mpfb2")
    if "skip" in rel:
        pytest.skip(f"MPFB2 indisponivel: {rel['skip']}")
    assert rel["sem_peso"] == 0
    assert rel["max_inf"] <= 4
    assert rel["max_soma_err"] < 1e-4
    assert 0.74 <= rel["chest_top_rel"] <= 0.795
    assert rel["foot_leg_max"] < 0.01
    assert rel["dorso_head_max"] == 0.0
    assert rel["dorso_cs_avg"] >= 0.85
    assert rel["lumbar_trunk_avg"] >= 0.95
    assert rel["lumbar_arm_max"] < 0.02
    assert rel["head_self_disp"] > 0.03
    assert rel["dorso_head_disp"] < 0.002
    assert rel["arm_self_disp"] > 0.10
    assert rel["dorso_arms_disp"] < 0.002
