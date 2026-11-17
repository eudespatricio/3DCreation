"""Testes do motor Smart-Fit, rig 56 ossos (godot-humanoid-aa@1), animacao e Godot BoneMap."""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from forge3d import animacao, post, profiles, qc

RAIZ = Path(__file__).resolve().parents[1]
BLENDER_DIR = RAIZ / "blender"
POST_IMPORT_GD = RAIZ / "addons" / "forge3d" / "post_import.gd"
PROJ_GODOT = RAIZ / "tools" / "godot_project"

if str(BLENDER_DIR) not in sys.path:
    sys.path.insert(0, str(BLENDER_DIR))

import smart_fit  # noqa: E402

OSSOS_56_ESPERADOS = (
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
    "Thumb1.L",
    "Thumb2.L",
    "Thumb3.L",
    "Index1.L",
    "Index2.L",
    "Index3.L",
    "Middle1.L",
    "Middle2.L",
    "Middle3.L",
    "Ring1.L",
    "Ring2.L",
    "Ring3.L",
    "Little1.L",
    "Little2.L",
    "Little3.L",
    "Thumb1.R",
    "Thumb2.R",
    "Thumb3.R",
    "Index1.R",
    "Index2.R",
    "Index3.R",
    "Middle1.R",
    "Middle2.R",
    "Middle3.R",
    "Ring1.R",
    "Ring2.R",
    "Ring3.R",
    "Little1.R",
    "Little2.R",
    "Little3.R",
    "UpperLeg.L",
    "LowerLeg.L",
    "Foot.L",
    "Toe.L",
    "UpperLeg.R",
    "LowerLeg.R",
    "Foot.R",
    "Toe.R",
)


def _blender_bin() -> str:
    try:
        ok, _ = post.preflight()
        if ok:
            return post.binario()
    except Exception:
        pass
    pytest.skip("Blender 4.2 nao disponivel neste ambiente")


def _godot_bin() -> str:
    env = os.environ.get("FORGE3D_GODOT")
    if env and Path(env).is_file():
        return env
    bin_g = shutil.which("godot") or shutil.which("godot4")
    if bin_g:
        return bin_g
    pytest.skip("Godot 4 headless nao disponivel neste ambiente")


def _rodar_blender_script(tmp_path: Path, codigo: str, tag: str = "sf") -> dict:
    blender = _blender_bin()
    out_json = tmp_path / f"out_{tag}.json"
    script = tmp_path / f"run_{tag}.py"
    script.write_text(codigo, encoding="utf-8")
    proc = subprocess.run(
        [blender, "-b", "--factory-startup", "--python-exit-code", "1", "--python", str(script), "--", str(out_json)],
        cwd=str(RAIZ),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, f"Blender falhou:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    assert out_json.is_file(), f"JSON nao gerado: {out_json}"
    return json.loads(out_json.read_text(encoding="utf-8"))


def _pontos_cilindro_inclinado(raio: float, comprimento: float, eixo_dir: tuple[float, float, float]) -> list[tuple[float, float, float]]:
    ex, ey, ez = eixo_dir
    n = math.sqrt(ex * ex + ey * ey + ez * ez)
    ux, uy, uz = ex / n, ey / n, ez / n
    ref = (1.0, 0.0, 0.0) if abs(ux) < 0.8 else (0.0, 1.0, 0.0)
    vx = uy * ref[2] - uz * ref[1]
    vy = uz * ref[0] - ux * ref[2]
    vz = ux * ref[1] - uy * ref[0]
    vn = math.sqrt(vx * vx + vy * vy + vz * vz)
    vx, vy, vz = vx / vn, vy / vn, vz / vn
    wx = uy * vz - uz * vy
    wy = uz * vx - ux * vz
    wz = ux * vy - uy * vx

    pts: list[tuple[float, float, float]] = []
    for k in range(101):
        s = comprimento * (k / 100.0)
        for a in range(16):
            ang = 2.0 * math.pi * (a / 16.0)
            ca, sa = math.cos(ang), math.sin(ang)
            pts.append(
                (
                    s * ux + raio * (ca * vx + sa * wx),
                    s * uy + raio * (ca * vy + sa * wy),
                    s * uz + raio * (ca * vz + sa * wz),
                )
            )
    return pts


# ------------------------------------------------------------------ 1. Pure-math Smart-Fit


def test_smart_fit_importa_sem_bpy_e_pca_cilindro():
    assert smart_fit.HAS_BPY is False
    pts = _pontos_cilindro_inclinado(raio=0.022, comprimento=0.40, eixo_dir=(1.0, 1.0, 2.0))
    info = smart_fit.calcular_pca_cilindro(pts, fracao_cabo=(0.05, 0.35))
    assert info["raio_m"] == pytest.approx(0.022, abs=0.0015)
    assert info["comprimento_m"] == pytest.approx(0.12, abs=0.015)
    assert len(info["centro"]) == 3
    assert info["socket_offset"] == info["centro"]

    e_ref = (1.0 / math.sqrt(6.0), 1.0 / math.sqrt(6.0), 2.0 / math.sqrt(6.0))
    dot = abs(sum(a * b for a, b in zip(info["eixo"], e_ref)))
    assert dot > 0.99


def test_smart_fit_angulos_punho_monotonicos():
    fino = smart_fit.calcular_angulos_punho_cilindrico(0.012)
    medio = smart_fit.calcular_angulos_punho_cilindrico(0.025)
    grosso = smart_fit.calcular_angulos_punho_cilindrico(0.045)

    assert fino["soma_graus"] > medio["soma_graus"] > grosso["soma_graus"]
    for res in (fino, medio, grosso):
        for segs in res["dedos"].values():
            assert len(segs) == 3
            assert all(4.0 <= ang <= 95.0 for ang in segs)
        for rx, rz in res["thumb"]:
            assert 4.0 <= rx <= 65.0
            assert 1.0 <= rz <= 45.0


def test_smart_fit_deslocamento_contato():
    # Peca flutuando 0.05 m acima de Z=0 (normal +Z)
    pts_flt = [(0.0, 0.0, 0.05), (0.1, 0.0, 0.05)]
    alvo = [((0.0, 0.0, 0.0), (0.0, 0.0, 1.0)), ((0.1, 0.0, 0.0), (0.0, 0.0, 1.0))]
    res_flt = smart_fit.calcular_deslocamento_contato(pts_flt, alvo, folga_m=0.0015)
    assert res_flt["penetrando"] is False
    assert res_flt["deslocamento"][2] == pytest.approx(-0.0485, abs=1e-5)

    # Peca penetrando -0.01 m dentro de Z=0
    pts_pen = [(0.0, 0.0, -0.01), (0.1, 0.0, 0.02)]
    res_pen = smart_fit.calcular_deslocamento_contato(pts_pen, alvo, folga_m=0.0015)
    assert res_pen["penetrando"] is True
    assert res_pen["deslocamento"][2] == pytest.approx(0.0115, abs=1e-5)


# ------------------------------------------------------------------ 2. Animacao AA & retrocompat


def _perfil_aa_sintetico() -> dict:
    mapa_aa = {
        "quadril": "Hips",
        "coluna": "Spine",
        "tronco": "Chest",
        "pescoco": "Neck",
        "cabeca": "Head",
        "mandibula": "Jaw",
        "capa": "Cape",
        "ombro_e": "Shoulder.L",
        "ombro_d": "Shoulder.R",
        "braco_e": "UpperArm.L",
        "braco_d": "UpperArm.R",
        "antebraco_e": "LowerArm.L",
        "antebraco_d": "LowerArm.R",
        "mao_e": "Hand.L",
        "mao_d": "Hand.R",
        "perna_e": "UpperLeg.L",
        "perna_d": "UpperLeg.R",
        "canela_e": "LowerLeg.L",
        "canela_d": "LowerLeg.R",
        "pe_e": "Foot.L",
        "pe_d": "Foot.R",
        "dedo_pe_e": "Toe.L",
        "dedo_pe_d": "Toe.R",
    }
    for pt_d, en_d in (
        ("polegar", "Thumb"),
        ("indicador", "Index"),
        ("medio", "Middle"),
        ("anelar", "Ring"),
        ("mindinho", "Little"),
    ):
        for seg in (1, 2, 3):
            mapa_aa[f"{pt_d}_{seg}_e"] = f"{en_d}{seg}.L"
            mapa_aa[f"{pt_d}_{seg}_d"] = f"{en_d}{seg}.R"
    return {"rig": {"esqueleto_padrao": "godot-humanoid-aa@1", "retarget": {"godot-humanoid-aa@1": mapa_aa}}}


def test_animacao_aa_secundaria_e_retrocompat():
    godot = profiles.carregar("godot4")
    r15 = profiles.carregar("roblox-r15")

    # Retrocompatibilidade 100% preservada: zero ossos extras nos esqueletos antigos
    for perfil, esq in ((godot, "godot-humanoid@1"), (r15, "r15@1")):
        cls = animacao.clipes(perfil, esq, ["idle", "walk", "run", "jump", "attack"])
        for c in cls:
            assert "Cape" not in c["ossos"]
            assert "Jaw" not in c["ossos"]
            assert "Thumb1.L" not in c["ossos"]

    # Novo esqueleto AA sintetiza Cape, Jaw e falanges com curvas C1 suaves
    aa_perfil = _perfil_aa_sintetico()
    pedidos = ["idle", "walk", "run", "jump", "attack", "death"]
    cls_aa = animacao.clipes(aa_perfil, "godot-humanoid-aa@1", pedidos)
    assert [c["nome"] for c in cls_aa] == pedidos

    for c in cls_aa:
        ossos_c = set(c["ossos"])
        assert {"Cape", "Jaw", "Neck", "Hand.L", "Hand.R", "Thumb1.L", "Index2.R", "Little3.L"} <= ossos_c
        for osso_sec in ("Cape", "Jaw", "Thumb1.L", "Middle2.R"):
            vals = [p["graus"] for ch in c["chaves"] for p in ch["poses"] if p["osso"] == osso_sec]
            assert max(vals) - min(vals) > 1.0, (c["nome"], osso_sec, vals)
        if c["loop"]:
            p0 = {(p["osso"], p["eixo"]): p["graus"] for p in c["chaves"][0]["poses"]}
            pf = {(p["osso"], p["eixo"]): p["graus"] for p in c["chaves"][-1]["poses"]}
            for k, v0 in p0.items():
                assert pf[k] == pytest.approx(v0, abs=1e-4)


# ------------------------------------------------------------------ 3. Blender Smart-Fit & Rig 56


@pytest.mark.blender
def test_blender_smart_fit_bvh_conform_oclusao_e_grip(tmp_path: Path):
    codigo = f"""
import json, math, sys
from pathlib import Path
sys.path.insert(0, {str(BLENDER_DIR)!r})
import bmesh, bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree
import smart_fit, autorig, postprocess

bpy.ops.wm.read_factory_settings(use_empty=True)

# 1. Alvo cilindro vertical r=0.10, z=[0..1]
bpy.ops.mesh.primitive_cylinder_add(vertices=24, radius=0.10, depth=1.0, location=(0.0, 0.0, 0.5))
alvo = bpy.context.active_object
alvo.name = "CorpoCilindro"

# 2. Placa flutuante em y=0.20 (10 cm longe da parede y=0.10)
bpy.ops.mesh.primitive_cube_add(size=0.06, location=(0.0, 0.20, 0.5))
placa = bpy.context.active_object
placa.name = "PlacaFlutuante"
res_flt = smart_fit.encaixar_contato_bvh(placa, alvo, direcao=(0.0, -1.0, 0.0), folga_m=0.0015)

# 3. Placa penetrando dentro do cilindro
bpy.ops.mesh.primitive_cube_add(size=0.06, location=(0.0, 0.06, 0.5))
placa_pen = bpy.context.active_object
placa_pen.name = "PlacaPenetrante"
res_pen = smart_fit.encaixar_contato_bvh(placa_pen, alvo, direcao=None, folga_m=0.0015)

# 4. Conformacao anatomica de patch aberto + placa solida fechada sobre cilindro
bpy.ops.mesh.primitive_grid_add(x_subdivisions=6, y_subdivisions=6, size=0.12, location=(0.0, 0.16, 0.5))
patch = bpy.context.active_object
patch.rotation_euler.x = math.pi * 0.5
bpy.context.view_layer.update()
res_conf = smart_fit.conformar_anatomico(patch, alvo, folga_m=0.0015, usar_surface_deform=True)

bpy.ops.mesh.primitive_cube_add(size=0.08, location=(0.0, 0.16, 0.5))
placa_solida = bpy.context.active_object
placa_solida.scale = (1.2, 0.2, 1.2)
bpy.context.view_layer.update()
res_conf_solida = smart_fit.conformar_anatomico(placa_solida, alvo, folga_m=0.0015, usar_surface_deform=True)

# 5. Corte de oclusao interna: bota cobre metade inferior do cilindro corpo [0..0.48]
bpy.ops.mesh.primitive_cylinder_add(vertices=24, radius=0.10, depth=1.0, location=(1.0, 0.0, 0.5))
corpo_oc = bpy.context.active_object
bpy.ops.mesh.primitive_subdivide_edge_ring if False else None
bm_sub = bmesh.new()
bm_sub.from_mesh(corpo_oc.data)
bmesh.ops.subdivide_edges(bm_sub, edges=list(bm_sub.edges), cuts=4, use_grid_fill=True)
bm_sub.to_mesh(corpo_oc.data)
bm_sub.free()

bpy.ops.mesh.primitive_cylinder_add(vertices=24, radius=0.115, depth=0.45, location=(1.0, 0.0, 0.225))
bota = bpy.context.active_object
res_oc = smart_fit.recortar_oclusao_interna(corpo_oc, [bota], dist_max_m=0.035, limiar_cobertura=0.85)

# 6. Auto grip cilindrico em espada/cabo + conformacao de punho no rig 56 ossos
bpy.ops.mesh.primitive_cylinder_add(vertices=20, radius=0.014, depth=0.60, location=(2.0, 0.0, 0.30))
arma = bpy.context.active_object
res_grip = smart_fit.auto_grip_cilindrico(arma, fracao_cabo=(0.05, 0.35))

# Cria rig minimo AA 56 ossos e testa aplicar_smart_fit_job
bpy.ops.mesh.primitive_cube_add(size=0.2, location=(0.0, 0.0, 0.5))
box_rig = bpy.context.active_object
marcos = {{
    "z_min": 0.0, "z_max": 1.8, "altura": 1.8, "cy": 0.0, "torso_hw": 0.16, "neck_hw": 0.05,
    "leg_top_z": 0.80, "hip_z": 0.88, "spine_z": 0.98, "spine1_z": 1.08, "chest_z": 1.22,
    "chest_top_z": 1.38, "neck_z": 1.48, "head_top_z": 1.80, "knee_z": 0.45, "ankle_z": 0.10,
    "leg_x_L": 0.10, "leg_x_R": -0.10, "foot_y": 0.16, "toe_y": 0.22, "shoulder_z": 1.35,
    "shoulder_x_L": 0.22, "shoulder_x_R": -0.22, "elbow_x_L": 0.45, "elbow_x_R": -0.45,
    "wrist_x_L": 0.70, "wrist_x_R": -0.70,
    "braco_L": {{"clav_x": 0.08, "shoulder": Vector((0.22, 0.0, 1.35)), "elbow": Vector((0.45, 0.0, 1.35)), "wrist": Vector((0.70, 0.0, 1.35)), "tip": Vector((0.86, 0.0, 1.35))}},
    "braco_R": {{"clav_x": -0.08, "shoulder": Vector((-0.22, 0.0, 1.35)), "elbow": Vector((-0.45, 0.0, 1.35)), "wrist": Vector((-0.70, 0.0, 1.35)), "tip": Vector((-0.86, 0.0, 1.35))}},
}}
ossos = autorig._construir_ossos("godot-humanoid-aa@1", marcos)
rig_aa = postprocess.criar_armadura(ossos)
autorig._alinhar_roll_ossos(rig_aa)
res_job = smart_fit.aplicar_smart_fit_job(
    arma,
    {{"smart_fit": {{"auto_grip": {{"fracao_cabo": [0.05, 0.35], "lado": "R", "aplicar_no_rig": True}}}}}},
    rig_obj=rig_aa,
)

Path(sys.argv[sys.argv.index("--") + 1]).write_text(json.dumps({{
    "res_flt": res_flt,
    "res_pen": res_pen,
    "res_conf": res_conf,
    "res_conf_solida": res_conf_solida,
    "res_oc": res_oc,
    "res_grip": res_grip,
    "res_job": res_job,
}}), encoding="utf-8")
"""
    res = _rodar_blender_script(tmp_path, codigo, tag="smart_fit_ops")
    assert res["res_flt"]["distancia_min_depois_m"] == pytest.approx(0.0015, abs=0.0006)
    assert res["res_pen"]["penetracao_resolvida"] is True
    assert res["res_pen"]["distancia_min_depois_m"] == pytest.approx(0.0015, abs=0.0008)
    assert res["res_conf"]["aplicado"] is True
    assert res["res_conf"]["distancia_min_m"] == pytest.approx(0.0015, abs=0.0015)
    assert res["res_conf_solida"]["aplicado"] is True
    assert res["res_conf_solida"]["nao_manifold"] == 0
    assert res["res_conf_solida"]["distancia_min_m"] == pytest.approx(0.0015, abs=0.0012)
    assert res["res_oc"]["faces_removidas"] > 0
    assert res["res_oc"]["nao_manifold"] == 0
    assert res["res_grip"]["raio_m"] == pytest.approx(0.014, abs=0.0015)
    assert res["res_job"]["aplicado"] is True
    assert res["res_job"]["conformar_punho"]["ossos_posados"] == 15


@pytest.mark.blender
def test_blender_autorig_56_ossos_hierarquia_pesos_e_g6_gltf(tmp_path: Path):
    glb_path = tmp_path / "hero_aa_56.glb"
    codigo = f"""
import json, sys
from pathlib import Path
sys.path.insert(0, {str(BLENDER_DIR)!r})
import bmesh, bpy
from mathutils import Vector
import autorig, postprocess

bpy.ops.wm.read_factory_settings(use_empty=True)

def _add_box(bm, cx, cy, cz, sx, sy, sz, mat_idx=0):
    ret = bmesh.ops.create_cube(bm, size=1.0)
    verts = ret["verts"]
    for v in verts:
        v.co.x = cx + v.co.x * sx
        v.co.y = cy + v.co.y * sy
        v.co.z = cz + v.co.z * sz
    for f in bm.faces:
        if all(v in verts for v in f.verts):
            f.material_index = mat_idx

bm = bmesh.new()
# Corpo conectado estilizado (tronco, cabeca, bracos T-pose + 5 dedos por mao, pernas)
_add_box(bm, 0.0, 0.0, 1.05, 0.28, 0.16, 0.60, 0)  # tronco/quadril
_add_box(bm, 0.0, 0.0, 1.58, 0.16, 0.16, 0.28, 0)  # cabeca + queixo
# Bracos L (+X) e R (-X) em T-pose ate pulso (x=+-0.55)
_add_box(bm, 0.34, 0.0, 1.32, 0.44, 0.07, 0.07, 0)
_add_box(bm, -0.34, 0.0, 1.32, 0.44, 0.07, 0.07, 0)
# Palmas L/R (x=0.56..0.64)
_add_box(bm, 0.60, 0.0, 1.32, 0.08, 0.08, 0.025, 0)
_add_box(bm, -0.60, 0.0, 1.32, 0.08, 0.08, 0.025, 0)
# 5 dedos separados por mao
for sgn in (1.0, -1.0):
    for fy in (0.030, 0.012, -0.008, -0.028):
        _add_box(bm, sgn * 0.69, fy, 1.32, 0.09, 0.012, 0.012, 0)
    _add_box(bm, sgn * 0.62, 0.055, 1.315, 0.055, 0.014, 0.014, 0)
# Pernas L/R
_add_box(bm, 0.09, 0.0, 0.40, 0.09, 0.09, 0.80, 0)
_add_box(bm, -0.09, 0.0, 0.40, 0.09, 0.09, 0.80, 0)
# Olhos (mat_idx=1) e Capa dorsal (mat_idx=2)
_add_box(bm, 0.032, 0.085, 1.60, 0.022, 0.022, 0.022, 1)
_add_box(bm, -0.032, 0.085, 1.60, 0.022, 0.022, 0.022, 1)
_add_box(bm, 0.0, -0.14, 1.05, 0.34, 0.02, 0.68, 2)

bmesh.ops.subdivide_edges(bm, edges=list(bm.edges), cuts=1, use_grid_fill=True)
me = bpy.data.meshes.new("HeroAA")
for mname in ("skin", "eyes", "cape"):
    me.materials.append(bpy.data.materials.new(mname))
bm.to_mesh(me)
bm.free()
obj = bpy.data.objects.new("HeroAA", me)
bpy.context.collection.objects.link(obj)

rig, grupos = autorig.auto_rigar_humanoide(obj, "godot-humanoid-aa@1", postprocess.criar_armadura)
hierarquia = {{b.name: (b.parent.name if b.parent else None) for b in rig.data.bones}}

# Verifica normalizacao de pesos e top-4 por vertice
max_inf = 0
max_err_soma = 0.0
sem_peso = 0
for v in obj.data.vertices:
    ws = [g.weight for g in v.groups if g.weight > 1e-6]
    if not ws:
        sem_peso += 1
    max_inf = max(max_inf, len(ws))
    max_err_soma = max(max_err_soma, abs(sum(ws) - 1.0))

postprocess.exportar({str(glb_path)!r}, [rig, obj], com_rig=True, com_animacao=False)
Path(sys.argv[sys.argv.index("--") + 1]).write_text(json.dumps({{
    "ossos_rig": [b.name for b in rig.data.bones],
    "hierarquia": hierarquia,
    "grupos_nao_vazios": sorted(grupos.keys()),
    "max_inf": max_inf,
    "max_err_soma": max_err_soma,
    "sem_peso": sem_peso,
}}), encoding="utf-8")
"""
    res = _rodar_blender_script(tmp_path, codigo, tag="autorig_56")
    assert len(res["ossos_rig"]) == 56
    assert set(res["ossos_rig"]) == set(OSSOS_56_ESPERADOS)
    assert res["max_inf"] <= 4
    assert res["sem_peso"] == 0
    assert res["max_err_soma"] < 1e-4

    h = res["hierarquia"]
    assert h["Jaw"] == "Head"
    assert h["Eye.L"] == "Head"
    assert h["Eye.R"] == "Head"
    assert h["Cape"] == "Chest"
    assert h["Chest"] == "Spine"
    assert h["Spine"] == "Hips"
    for lado in ("L", "R"):
        for d in ("Thumb", "Index", "Middle", "Ring", "Little"):
            assert h[f"{d}1.{lado}"] == f"Hand.{lado}"
            assert h[f"{d}2.{lado}"] == f"{d}1.{lado}"
            assert h[f"{d}3.{lado}"] == f"{d}2.{lado}"

    # Verifica que olhos, capa e falanges receberam pesos
    grupos = set(res["grupos_nao_vazios"])
    assert {"Eye.L", "Eye.R", "Cape", "Index3.L", "Middle3.R", "Thumb2.L"} <= grupos

    # Verifica no GLB exportado (Gate G6 skin + 56 joints exatos)
    gltf, binario = qc.ler_glb_bin(glb_path)
    info = qc.analisar(gltf, binario)
    skin_st = qc._skin_status(gltf, binario)
    assert skin_st["ok"] is True, skin_st
    assert info["ossos"] == 56
    assert set(info["nomes_ossos"]) == set(OSSOS_56_ESPERADOS)


def _tem_mpfb2() -> bool:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    cfg_root = Path(xdg) if xdg else (Path.home() / ".config")
    base = cfg_root / "blender" / "4.2" / "extensions"
    return base.is_dir() and any(base.glob("**/mpfb/__init__.py"))


@pytest.mark.blender
def test_blender_template_body_e_modular_armor_aa_56(tmp_path: Path):
    blender = _blender_bin()
    if not _tem_mpfb2():
        pytest.skip("extensao MPFB2 nao instalada/visivel no Blender deste ambiente")
    dir_body = tmp_path / "body_aa"
    dir_body.mkdir()
    job_body = tmp_path / "job_body.json"
    job_body.write_text(
        json.dumps(
            {
                "saida": str(dir_body),
                "esqueleto": "godot-humanoid-aa@1",
                "rig": True,
                "textura": 512,
                "limite_triangulos": 12000,
            }
        ),
        encoding="utf-8",
    )
    proc_b = subprocess.run(
        [blender, "-b", "--python-exit-code", "1", "--python", str(BLENDER_DIR / "template_body.py"), "--", str(job_body)],
        cwd=str(RAIZ),
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc_b.returncode == 0, proc_b.stdout + proc_b.stderr
    rel_b = json.loads((dir_body / "relatorio.json").read_text(encoding="utf-8"))
    assert rel_b["esqueleto"] == "godot-humanoid-aa@1"
    assert rel_b["ossos"] == 56
    assert rel_b["nao_manifold"] == 0
    gltf_b, bin_b = qc.ler_glb_bin(dir_body / "template_body.glb")
    info_b = qc.analisar(gltf_b, bin_b)
    assert info_b["ossos"] == 56
    assert set(info_b["nomes_ossos"]) == set(OSSOS_56_ESPERADOS)

    # Luvas skinned com transferencia de pesos 56 ossos + smart_fit 1.5 mm
    dir_luvas = tmp_path / "luvas_aa"
    dir_luvas.mkdir()
    job_luvas = tmp_path / "job_luvas.json"
    job_luvas.write_text(
        json.dumps(
            {
                "saida": str(dir_luvas),
                "parte": "luvas",
                "esqueleto": "godot-humanoid-aa@1",
                "smart_fit": {"encaixar_contato": True, "folga_m": 0.0015},
            }
        ),
        encoding="utf-8",
    )
    proc_l = subprocess.run(
        [blender, "-b", "--python-exit-code", "1", "--python", str(BLENDER_DIR / "modular_armor.py"), "--", str(job_luvas)],
        cwd=str(RAIZ),
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc_l.returncode == 0, proc_l.stdout + proc_l.stderr
    rel_l = json.loads((dir_luvas / "relatorio.json").read_text(encoding="utf-8"))
    assert rel_l["esqueleto"] == "godot-humanoid-aa@1"
    assert rel_l["ossos"] == 56
    assert "smart_fit" in rel_l and "encaixar_contato" in rel_l["smart_fit"]
    gltf_l, bin_l = qc.ler_glb_bin(dir_luvas / "template_armor.glb")
    info_l = qc.analisar(gltf_l, bin_l)
    assert info_l["ossos"] == 56
    assert set(info_l["nomes_ossos"]) == set(OSSOS_56_ESPERADOS)

    # Arma procedural em modular_armor gera telemetria auto_grip_cilindrico
    dir_arma = tmp_path / "arma_grip"
    dir_arma.mkdir()
    job_arma = tmp_path / "job_arma.json"
    job_arma.write_text(
        json.dumps({"saida": str(dir_arma), "parte": "arma", "esqueleto": "godot-humanoid-aa@1"}),
        encoding="utf-8",
    )
    proc_a = subprocess.run(
        [blender, "-b", "--python-exit-code", "1", "--python", str(BLENDER_DIR / "modular_armor.py"), "--", str(job_arma)],
        cwd=str(RAIZ),
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc_a.returncode == 0, proc_a.stdout + proc_a.stderr
    rel_a = json.loads((dir_arma / "relatorio.json").read_text(encoding="utf-8"))
    assert "grip_cilindrico" in rel_a
    assert 0.006 <= rel_a["grip_cilindrico"]["raio_m"] <= 0.060


# ------------------------------------------------------------------ 4. Godot BoneMap 56


@pytest.mark.godot
def test_godot_bone_map_56_aa_e_retrocompat(tmp_path: Path):
    godot = _godot_bin()
    script = tmp_path / "check_bonemap_aa.gd"
    script.write_text(
        f"""extends SceneTree
const PostImport := preload({str(POST_IMPORT_GD)!r})

func _dump(bm: BoneMap, prefix: String) -> void:
\tvar prof := bm.profile
\tfor i in range(prof.bone_size):
\t\tvar pname := prof.get_bone_name(i)
\t\tvar sname := bm.get_skeleton_bone_name(pname)
\t\tif sname != "":
\t\t\tprint(prefix, " ", pname, "=", sname)

func _initialize() -> void:
\t_dump(PostImport.criar_bone_map_humanoid(), "STD")
\t_dump(PostImport.criar_bone_map_humanoid("godot-humanoid-aa@1"), "AA")
\tquit(0)
""",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [godot, "--headless", "--path", str(PROJ_GODOT), "--script", str(script)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr

    std: dict[str, str] = {}
    aa: dict[str, str] = {}
    for linha in proc.stdout.splitlines():
        if linha.startswith("STD "):
            k, v = linha[4:].split("=", 1)
            std[k] = v
        elif linha.startswith("AA "):
            k, v = linha[3:].split("=", 1)
            aa[k] = v

    # Legado preservado
    assert std.get("Chest") == "Spine1"
    assert std.get("UpperChest") == "Chest"
    assert "LeftThumbMetacarpal" not in std

    # AA 56 ossos
    assert aa.get("Root") == "Root"
    assert aa.get("Spine") == "Spine"
    assert aa.get("Chest") == "Chest"
    assert "UpperChest" not in aa
    assert aa.get("Jaw") == "Jaw"
    assert aa.get("LeftEye") == "Eye.L"
    assert aa.get("RightEye") == "Eye.R"
    assert aa.get("LeftThumbMetacarpal") == "Thumb1.L"
    assert aa.get("RightLittleDistal") == "Little3.R"
    assert len(aa) == 55  # 56 profile bones minus UpperChest
    assert set(aa.values()) <= set(OSSOS_56_ESPERADOS)
