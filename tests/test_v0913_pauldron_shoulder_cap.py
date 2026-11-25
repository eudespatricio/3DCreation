"""Testes independentes de regressao para v0.9.13 — ombro/pauldron cap e rig Heroine."""

from __future__ import annotations

import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

from forge3d import animacao, config, post, profiles

RAIZ = Path(__file__).resolve().parents[1]
_BLENDER_DIR = RAIZ / "blender"
if str(_BLENDER_DIR) not in sys.path:
    sys.path.insert(0, str(_BLENDER_DIR))


class _Vec3:
    def __init__(self, xyz=(0.0, 0.0, 0.0)) -> None:
        self.x, self.y, self.z = float(xyz[0]), float(xyz[1]), float(xyz[2])


@pytest.fixture()
def _tronco_mod(monkeypatch: pytest.MonkeyPatch):
    if "mathutils" not in sys.modules:
        mod_mu = types.ModuleType("mathutils")
        mod_mu.Vector = _Vec3  # type: ignore[attr-defined]
        mod_mu.Matrix = object  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "mathutils", mod_mu)
    if "bpy" not in sys.modules:
        monkeypatch.setitem(sys.modules, "bpy", types.ModuleType("bpy"))
    pre_tronco = "autorig_marcos_tronco" in sys.modules
    pre_const = "autorig_const" in sys.modules
    import autorig_marcos_tronco as amt

    try:
        yield amt
    finally:
        if not pre_tronco:
            sys.modules.pop("autorig_marcos_tronco", None)
        if not pre_const:
            sys.modules.pop("autorig_const", None)


def _construir_malha_perfil(z_min: float, h: float, hw_fn, dx_step: float = 0.02) -> tuple[list[_Vec3], list[tuple[int, int]]]:
    """Gera fatias contiguas em X/Y/Z com arestas conectadas para teste de perfil."""
    coords: list[_Vec3] = []
    edges: list[tuple[int, int]] = []
    ys = (-0.12, -0.06, 0.0, 0.06, 0.12)
    prev_mid: int | None = None
    for i in range(20):
        f = 0.46 + 0.02 * i
        z, hw = z_min + f * h, float(hw_fn(f))
        n_half = max(2, int(round(hw / dx_step)))
        xs = [-hw + (2.0 * hw * k / (2 * n_half)) for k in range(2 * n_half + 1)]
        row_ids: list[list[int]] = []
        for y in ys:
            row: list[int] = []
            for x in xs:
                idx = len(coords)
                coords.append(_Vec3((x, y, z)))
                if row:
                    edges.append((row[-1], idx))
                row.append(idx)
            if row_ids:
                edges.extend(zip(row_ids[-1], row))
            row_ids.append(row)
        mid_idx = row_ids[len(ys) // 2][n_half]
        if prev_mid is not None:
            edges.append((prev_mid, mid_idx))
        prev_mid = mid_idx
    return coords, edges


def test_heroine_slender_flared_skirt_e_pauldron_espesso(_tronco_mod) -> None:
    h, z_min = 1.74, 0.0
    coords, edges = _construir_malha_perfil(z_min, h, lambda f: 0.26 if f <= 0.56 else (0.15 if f < 0.70 else (0.32 if f <= 0.80 else 0.14)))
    torso_hw, perfil = _tronco_mod._perfil_tronco_fatias(coords, edges, z_min, h)
    w_sh = _tronco_mod._largura_em_z(perfil, torso_hw, z_min + 0.75 * h)
    assert 0.13 <= torso_hw <= 0.20, f"torso_hw inesperado para Heroine: {torso_hw:.4f}"
    assert w_sh <= 0.20, f"largura em 0.75*h vazou para pauldron: {w_sh:.4f}"


def test_heroine_pauldron_baixo_caindo_no_peito(_tronco_mod) -> None:
    h, z_min = 1.74, 0.0
    coords, edges = _construir_malha_perfil(z_min, h, lambda f: 0.25 if f <= 0.56 else (0.15 if f < 0.65 else (0.32 if f <= 0.80 else 0.14)))
    torso_hw, perfil = _tronco_mod._perfil_tronco_fatias(coords, edges, z_min, h)
    w_sh = _tronco_mod._largura_em_z(perfil, torso_hw, z_min + 0.75 * h)
    assert w_sh <= 0.20, f"pauldron baixo inflou largura em 0.75*h: {w_sh:.4f}"


def test_boss_largo_uniforme_sem_estreitamento(_tronco_mod) -> None:
    h, z_min = 2.0, 0.0
    coords, edges = _construir_malha_perfil(z_min, h, lambda _f: 0.36)
    torso_hw, perfil = _tronco_mod._perfil_tronco_fatias(coords, edges, z_min, h)
    w_sh = _tronco_mod._largura_em_z(perfil, torso_hw, z_min + 0.75 * h)
    assert w_sh >= 0.34, f"boss uniforme estreitado artificialmente em 0.75*h: {w_sh:.4f}"


def test_torso_atletico_v_taper_sem_pauldron(_tronco_mod) -> None:
    h, z_min = 1.80, 0.0
    coords, edges = _construir_malha_perfil(
        z_min, h, lambda f: 0.14 if f <= 0.56 else (0.23 if f >= 0.70 else 0.14 + 0.09 * ((f - 0.56) / 0.14))
    )
    torso_hw, perfil = _tronco_mod._perfil_tronco_fatias(coords, edges, z_min, h)
    w_sh = _tronco_mod._largura_em_z(perfil, torso_hw, z_min + 0.75 * h)
    assert w_sh >= 0.20, f"torso V-taper pincado para a cintura estreita: {w_sh:.4f}"


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


_HEROINE_BLENDER_SCRIPT = r"""
import json, sys, bpy, bmesh
from mathutils import Vector

cfg = json.loads(open(sys.argv[-1], encoding="utf-8").read())
sys.path.insert(0, cfg["blender_dir"])
import autorig, autorig_marcos, postprocess, postprocess_deform

def build_heroine_mesh(name="heroine_pauldron"):
    bm = bmesh.new()
    def box(c, sz):
        for v in bmesh.ops.create_cube(bm, size=1.0)["verts"]:
            v.co = Vector((v.co.x * sz[0] + c[0], v.co.y * sz[1] + c[1], v.co.z * sz[2] + c[2]))
    def seg(p0, p1, w, d):
        p0, p1 = Vector(p0), Vector(p1)
        q = (p1 - p0).normalized().to_track_quat("Z", "Y")
        mid, ln = (p0 + p1) * 0.5, (p1 - p0).length
        for v in bmesh.ops.create_cube(bm, size=1.0)["verts"]:
            v.co = q @ Vector((v.co.x * w, v.co.y * d, v.co.z * ln)) + mid

    for s in (1.0, -1.0):
        box((s * 0.13, 0.03, 0.05), (0.12, 0.22, 0.10))
        seg((s * 0.13, 0.0, 0.10), (s * 0.13, 0.0, 0.46), 0.11, 0.11)
        seg((s * 0.13, 0.0, 0.44), (s * 0.13, 0.0, 0.88), 0.14, 0.14)
    box((0.0, 0.0, 0.92), (0.50, 0.26, 0.16))
    box((0.0, 0.0, 1.12), (0.30, 0.22, 0.26))
    box((0.0, 0.0, 1.32), (0.30, 0.24, 0.18))
    for s in (1.0, -1.0):
        box((s * 0.23, 0.0, 1.32), (0.18, 0.24, 0.16))
        sh, el, wr = Vector((s * 0.20, 0.0, 1.32)), Vector((s * 0.42, 0.02, 1.09)), Vector((s * 0.61, 0.0, 0.85))
        seg(sh, el, 0.09, 0.09); seg(el, wr, 0.08, 0.08); seg(wr, Vector((s * 0.66, 0.0, 0.77)), 0.07, 0.05)
    box((0.0, 0.0, 1.46), (0.11, 0.11, 0.12))
    box((0.0, 0.0, 1.62), (0.20, 0.22, 0.24))

    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    obj = bpy.data.objects.new(name, me); bpy.context.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj; obj.select_set(True)
    mod = obj.modifiers.new("VoxelWeld", "REMESH"); mod.mode = "VOXEL"; mod.voxel_size = 0.028
    bpy.ops.object.modifier_apply(modifier=mod.name)
    postprocess.reparar_malha(obj)
    return obj

def dom_counts(obj, rig):
    vgs = {vg.index: vg.name for vg in obj.vertex_groups}
    dom = {b.name: 0 for b in rig.data.bones}
    for v in obj.data.vertices:
        pesos = [(g.weight, vgs[g.group]) for g in v.groups if g.group in vgs and g.weight > 1e-5]
        if pesos:
            dom[max(pesos)[1]] = dom.get(max(pesos)[1], 0) + 1
    return dom

bpy.ops.wm.read_factory_settings(use_empty=True)
obj_aa = build_heroine_mesh("heroine_aa")
marcos = autorig_marcos.estimar_marcos(obj_aa)
rig_aa, _ = autorig.auto_rigar_humanoide(obj_aa, "godot-humanoid-aa@1", postprocess.criar_armadura)
dom_aa = dom_counts(obj_aa, rig_aa)
ger_aa = autorig.aplicar_animacoes_multi(rig_aa, cfg["clipes_aa"])
deform_aa = postprocess_deform.medir_deformacao_animacao(obj_aa, rig_aa, ger_aa)

bpy.ops.wm.read_factory_settings(use_empty=True)
obj_r15 = build_heroine_mesh("heroine_r15")
marcos_r15 = autorig_marcos.estimar_marcos(obj_r15)
rig_r15, _ = autorig.auto_rigar_humanoide(obj_r15, "r15@1", postprocess.criar_armadura)
dom_r15 = dom_counts(obj_r15, rig_r15)

open(cfg["out_json"], "w", encoding="utf-8").write(json.dumps({
    "marcos": {
        "altura": float(marcos["altura"]), "torso_hw": float(marcos["torso_hw"]),
        "shoulder_x_L": float(marcos["shoulder_x_L"]), "shoulder_x_R": float(marcos["shoulder_x_R"]),
        "clav_x_R": float(marcos["braco_R"]["clav_x"]), "elbow_x_R": float(marcos["elbow_x_R"]),
    },
    "dom_aa": dom_aa,
    "max_stretch": float(deform_aa["max_stretch"]) if deform_aa else 999.0,
    "r15": {
        "dom_L": int(dom_r15.get("LeftUpperArm", 0)), "dom_R": int(dom_r15.get("RightUpperArm", 0)),
        "head_x_L": float(rig_r15.data.bones["LeftUpperArm"].head_local.x),
        "head_x_R": float(rig_r15.data.bones["RightUpperArm"].head_local.x),
        "shoulder_x_L": float(marcos_r15["shoulder_x_L"]), "shoulder_x_R": float(marcos_r15["shoulder_x_R"]),
    },
}))
"""


@pytest.mark.blender
def test_blender_heroine_pauldron_shoulder_cap_e_r15(tmp_path: Path) -> None:
    blender = _exigir_blender()
    perfil_aa = profiles.carregar("godot4-aa")
    clipes_aa = animacao.clipes(perfil_aa, "godot-humanoid-aa@1", ["idle", "walk", "run", "attack"])
    out_json, cfg_path, script_path = tmp_path / "out.json", tmp_path / "cfg.json", tmp_path / "run.py"
    cfg_path.write_text(json.dumps({"blender_dir": str(_BLENDER_DIR), "clipes_aa": clipes_aa, "out_json": str(out_json)}), encoding="utf-8")
    script_path.write_text(_HEROINE_BLENDER_SCRIPT, encoding="utf-8")
    proc = subprocess.run(
        [blender, "--background", "--factory-startup", "--python-exit-code", "1", "--python", str(script_path), "--", str(cfg_path)],
        capture_output=True, text=True, timeout=240,
    )
    assert proc.returncode == 0, f"Blender falhou:\nSTDOUT={proc.stdout}\nSTDERR={proc.stderr}"
    res = json.loads(out_json.read_text(encoding="utf-8"))
    print("HEROINE_METRICS:", json.dumps(res))

    m = res["marcos"]
    assert abs(m["shoulder_x_R"]) <= 0.23, f"shoulder_x_R empurrado para pauldron: {m}"
    assert abs(m["clav_x_R"]) < abs(m["shoulder_x_R"]) < abs(m["elbow_x_R"]), m

    dom = res["dom_aa"]
    assert dom.get("UpperArm.R", 0) > dom.get("Shoulder.R", 0), dom
    assert dom.get("UpperArm.L", 0) > dom.get("Shoulder.L", 0), dom
    assert float(res["max_stretch"]) <= 8.5, f"G16 excedeu 8.5x: {res['max_stretch']}"

    r15 = res["r15"]
    assert r15["dom_L"] > 0 and r15["dom_R"] > 0, r15
    assert abs(r15["head_x_L"]) >= 0.85 * abs(r15["shoulder_x_L"]), r15
    assert abs(r15["head_x_R"]) >= 0.85 * abs(r15["shoulder_x_R"]), r15
