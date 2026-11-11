"""Testes reais em Blender 4.2 + Godot 4.3 para ``blender/autorig.py`` (Fase B)."""

from __future__ import annotations

import ast
import json
import subprocess
from pathlib import Path

import pytest

from forge3d import animacao, post, profiles, qc

RAIZ = Path(__file__).resolve().parents[1]
AUTORIG_PY = RAIZ / "blender" / "autorig.py"
GODOT_PROJ = RAIZ / "tools" / "godot_project"
GODOT_ANIM_SCRIPT = RAIZ / "tools" / "godot_anim_check.gd"


def _blender_bin() -> str:
    try:
        ok, _ = post.preflight()
        if ok:
            return post.binario()
    except Exception:
        pass
    pytest.skip("Blender 4.2 nao disponivel neste ambiente")


def _godot_bin() -> str:
    import shutil

    bin_g = shutil.which("godot") or shutil.which("godot4")
    if not bin_g:
        pytest.skip("Godot 4 nao disponivel neste ambiente")
    return bin_g


def test_autorig_nao_importa_pillow_ou_numpy():
    arvore = ast.parse(AUTORIG_PY.read_text(encoding="utf-8"))
    proibidos = {"PIL", "numpy", "np"}
    encontrados = set()
    for node in ast.walk(arvore):
        if isinstance(node, ast.Import):
            for alias in node.names:
                encontrados.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            encontrados.add(node.module.split(".")[0])
    assert not (encontrados & proibidos), encontrados & proibidos


def _rodar_blender_autorig(
    tmp_path: Path,
    modo_malha: str,
    esqueleto: str,
    clipes: list[dict],
    export_mode: str = "NLA_TRACKS",
    *,
    forcar_fallback: bool = False,
) -> tuple[dict, Path]:
    blender = _blender_bin()
    tag = f"{modo_malha}_{esqueleto.replace('@', '_')}_{export_mode}_{'fb' if forcar_fallback else 'auto'}"
    out_json = tmp_path / f"res_{tag}.json"
    out_glb = tmp_path / f"asset_{tag}.glb"
    script = tmp_path / f"run_{tag}.py"
    cfg_path = tmp_path / f"cfg_{tag}.json"
    cfg_path.write_text(
        json.dumps(
            {
                "blender_dir": str(RAIZ / "blender"),
                "modo_malha": modo_malha,
                "esqueleto": esqueleto,
                "clipes": clipes,
                "out_glb": str(out_glb),
                "out_json": str(out_json),
                "export_mode": export_mode,
                "forcar_fallback": forcar_fallback,
            }
        ),
        encoding="utf-8",
    )
    script.write_text(
        """
import json, sys
import bpy, bmesh

cfg = json.loads(open(sys.argv[-1], encoding="utf-8").read())
sys.path.insert(0, cfg["blender_dir"])
import autorig, postprocess

bpy.ops.wm.read_factory_settings(use_empty=True)
bm = bmesh.new()

def add_box(cx, cy, cz, sx, sy, sz):
    ret = bmesh.ops.create_cube(bm, size=1.0)
    for v in ret["verts"]:
        v.co.x = v.co.x * sx + cx
        v.co.y = v.co.y * sy + cy
        v.co.z = v.co.z * sz + cz

add_box(0.0, 0.0, 1.05, 0.28, 0.16, 0.56)
add_box(0.0, 0.0, 1.44, 0.11, 0.11, 0.14)
add_box(0.0, 0.0, 1.67, 0.20, 0.22, 0.34)
add_box(0.11, 0.0, 0.42, 0.13, 0.13, 0.84)
add_box(-0.11, 0.0, 0.42, 0.13, 0.13, 0.84)

modo = cfg["modo_malha"]
if modo == "tpose_remesh":
    add_box(0.42, 0.0, 1.38, 0.58, 0.11, 0.11)
    add_box(-0.42, 0.0, 1.38, 0.58, 0.11, 0.11)
elif modo == "apose_ilhas":
    for s in (1.0, -1.0):
        ret = bmesh.ops.create_cube(bm, size=1.0)
        for v in ret["verts"]:
            t = v.co.x + 0.5
            v.co.x = s * (0.16 + 0.40 * t)
            v.co.y = v.co.y * 0.10
            v.co.z = 1.38 - 0.32 * t + v.co.z * 0.10
elif modo == "bracos_baixos":
    add_box(0.28, 0.0, 1.03, 0.10, 0.10, 0.72)
    add_box(-0.28, 0.0, 1.03, 0.10, 0.10, 0.72)

bmesh.ops.subdivide_edges(bm, edges=list(bm.edges), cuts=3, use_grid_fill=True)
me = bpy.data.meshes.new("humanoide")
bm.to_mesh(me)
bm.free()
obj = bpy.data.objects.new("humanoide", me)
bpy.context.collection.objects.link(obj)

if modo == "tpose_remesh":
    mod = obj.modifiers.new("remesh", "REMESH")
    mod.mode = "VOXEL"
    mod.voxel_size = 0.035
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.modifier_apply(modifier=mod.name)
    obj.select_set(False)

if cfg.get("forcar_fallback"):
    def _falhar_heat(*_a, **_kw):
        raise RuntimeError("bone heat disabled for fallback test")
    bpy.ops.object.parent_set = _falhar_heat

rig_obj, grupos = autorig.auto_rigar_humanoide(obj, cfg["esqueleto"], postprocess.criar_armadura)
geradas = autorig.aplicar_animacoes_multi(rig_obj, cfg["clipes"])

vgs = {vg.index: vg.name for vg in obj.vertex_groups}
n_verts = len(obj.data.vertices)
sem_peso = 0
max_inf = 0
max_soma_err = 0.0
troca_sinal = 0
for v in obj.data.vertices:
    ws = [(vgs[g.group], g.weight) for g in v.groups if g.weight > 1e-6]
    if not ws:
        sem_peso += 1
        continue
    max_inf = max(max_inf, len(ws))
    soma = sum(w for _, w in ws)
    max_soma_err = max(max_soma_err, abs(soma - 1.0))
    if v.co.x > 0.08:
        if any((n.endswith(".R") or n.startswith("Right")) and w > 0.05 for n, w in ws):
            troca_sinal += 1
    elif v.co.x < -0.08:
        if any((n.endswith(".L") or n.startswith("Left")) and w > 0.05 for n, w in ws):
            troca_sinal += 1

ossos_info = {
    b.name: {"head": tuple(round(x, 4) for x in b.head_local), "tail": tuple(round(x, 4) for x in b.tail_local)}
    for b in rig_obj.data.bones
}
nla_info = [
    {"name": t.name, "mute": t.mute, "strips": [s.action.name for s in t.strips if s.action]}
    for t in rig_obj.animation_data.nla_tracks
]

bpy.ops.object.select_all(action="DESELECT")
obj.select_set(True)
rig_obj.select_set(True)
bpy.context.view_layer.objects.active = obj
bpy.ops.export_scene.gltf(
    filepath=cfg["out_glb"],
    export_format="GLB",
    use_selection=True,
    export_skins=True,
    export_animations=True,
    export_animation_mode=cfg["export_mode"],
    export_rest_position_armature=True,
)

rel = {
    "n_verts": n_verts,
    "sem_peso": sem_peso,
    "max_inf": max_inf,
    "max_soma_err": max_soma_err,
    "troca_sinal": troca_sinal,
    "grupos_qtd": len(grupos),
    "parent_ok": obj.parent == rig_obj,
    "armature_mod_ok": any(m.type == "ARMATURE" and m.object == rig_obj for m in obj.modifiers),
    "ossos": list(ossos_info.keys()),
    "ossos_info": ossos_info,
    "actions": [a.name for a in bpy.data.actions if a.use_fake_user],
    "nla": nla_info,
    "active_action_none": rig_obj.animation_data.action is None,
    "geradas": [g["nome"] for g in geradas],
}
open(cfg["out_json"], "w", encoding="utf-8").write(json.dumps(rel))
""",
        encoding="utf-8",
    )

    proc = subprocess.run(
        [blender, "--background", "--factory-startup", "--python", str(script), "--", str(cfg_path)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert out_json.is_file() and out_glb.is_file()
    return json.loads(out_json.read_text(encoding="utf-8")), out_glb


def _checar_godot_4_clipes(glb: Path) -> None:
    godot = _godot_bin()
    for clipe in ("idle", "walk", "run", "jump"):
        proc = subprocess.run(
            [godot, "--headless", "--path", str(GODOT_PROJ), "--script", str(GODOT_ANIM_SCRIPT), "--", str(glb), clipe],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert proc.returncode == 0 and "GODOT_ANIM_OK" in proc.stdout, (clipe, proc.stdout + proc.stderr)


@pytest.mark.parametrize("export_mode", ["ACTIONS", "NLA_TRACKS"])
def test_autorig_organico_conectado_godot_humanoid_4_clipes(tmp_path, export_mode):
    godot_perfil = profiles.carregar("godot4")
    pedidos = ["idle", "walk", "run", "jump"]
    clipes = animacao.clipes(godot_perfil, "godot-humanoid@1", pedidos)

    rel, glb = _rodar_blender_autorig(tmp_path, "tpose_remesh", "godot-humanoid@1", clipes, export_mode)
    assert rel["parent_ok"] is True
    assert rel["armature_mod_ok"] is True
    assert rel["sem_peso"] == 0
    assert rel["max_inf"] <= 4
    assert rel["max_soma_err"] < 1e-4
    assert rel["troca_sinal"] == 0
    assert rel["active_action_none"] is True
    assert set(rel["actions"]) == set(pedidos)
    assert [t["name"] for t in rel["nla"]] == pedidos
    assert all(t["mute"] is True for t in rel["nla"])

    # Convenção X (+X esquerda, -X direita) e lista exata de 23 ossos do G6
    mapa_esperado = godot_perfil["rig"]["mapas"]["godot-humanoid@1"]
    assert rel["ossos"] == mapa_esperado
    assert rel["ossos_info"]["UpperArm.L"]["head"][0] > 0.0
    assert rel["ossos_info"]["UpperArm.R"]["head"][0] < 0.0
    assert rel["ossos_info"]["UpperLeg.L"]["head"][0] > 0.0
    assert rel["ossos_info"]["UpperLeg.R"]["head"][0] < 0.0

    gltf, binb = qc.ler_glb_bin(glb)
    info = qc.analisar(gltf)
    assert info["ossos"] == 23
    assert set(info["nomes_ossos"]) == set(mapa_esperado)
    anims_qc = qc.animacoes(gltf, binb)
    assert {a["nome"] for a in anims_qc} == set(pedidos)
    for a in anims_qc:
        assert a["duracao_s"] > 0.2
        assert a["canais"] >= 1
        assert len(a["movendo"]) >= 5

    _checar_godot_4_clipes(glb)


@pytest.mark.parametrize(
    ("perfil_nome", "esqueleto", "modo", "forcar_fallback"),
    [
        ("godot4", "godot-humanoid@1", "apose_ilhas", False),
        ("godot4", "godot-humanoid@1", "apose_ilhas", True),
        ("godot4", "godot-humanoid@1", "bracos_baixos", True),
        ("roblox-r15", "r15@1", "apose_ilhas", True),
    ],
)
def test_autorig_fallback_deterministico_e_r15_e_apose(tmp_path, perfil_nome, esqueleto, modo, forcar_fallback):
    perfil = profiles.carregar(perfil_nome)
    pedidos = ["idle", "walk", "run", "jump"]
    clipes = animacao.clipes(perfil, esqueleto, pedidos)

    rel, glb = _rodar_blender_autorig(
        tmp_path, modo, esqueleto, clipes, "NLA_TRACKS", forcar_fallback=forcar_fallback
    )
    assert rel["sem_peso"] == 0
    assert rel["max_inf"] <= 4
    assert rel["max_soma_err"] < 1e-4
    assert rel["troca_sinal"] == 0
    assert rel["parent_ok"] is True
    assert rel["armature_mod_ok"] is True

    mapa_esperado = perfil["rig"]["mapas"][esqueleto]
    assert len(rel["ossos"]) == len(mapa_esperado)
    assert set(rel["ossos"]) == set(mapa_esperado)

    gltf, binb = qc.ler_glb_bin(glb)
    info = qc.analisar(gltf)
    assert info["ossos"] == len(mapa_esperado)
    assert set(info["nomes_ossos"]) == set(mapa_esperado)
    anims_qc = qc.animacoes(gltf, binb)
    assert [a["nome"] for a in anims_qc] == pedidos
    for a in anims_qc:
        assert a["duracao_s"] >= 1.5
        assert a["canais"] >= 1
        assert a["movendo"]

    _checar_godot_4_clipes(glb)
