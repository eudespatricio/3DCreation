"""Regressao do GAP-048: personagem de cabeca para baixo tem que ser corrigido.

O caso real (conceito externo, 11/11/2026) saiu de cabeca para baixo com G1-G10 verdes: com uma
arma grande ao lado, `razao_topo_base` deu 0,988 e `centro_area` 6,18/12 — os dois sinais antigos
ficaram neutros. A fixture sintetica reproduz o padrao:
  * `personagem_upright.glb` — sola chata embaixo, cabeca estreita em cima, arma lateral e gola
    larga (para as regras antigas ficarem neutras); `invertido` tem que dar False.
  * `personagem_invertido.glb` — o mesmo mesh girado 180 no X; tem que ser espelhado, com
    `invertido_contato` True (o sinal novo e o do contato chato da sola).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
DRIVER = RAIZ / "tests" / "fixtures" / "checa_orientacao.py"
POSTPROCESS = RAIZ / "blender" / "postprocess.py"
BLENDER = shutil.which("blender") or str(Path.home() / ".local" / "bin" / "blender")


def _canonicalizar(glb: Path) -> dict:
    proc = subprocess.run(
        [
            BLENDER,
            "--background",
            "--factory-startup",
            "--python",
            str(DRIVER),
            "--",
            str(glb),
            str(POSTPROCESS),
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )
    linha = next(
        (linha_out for linha_out in proc.stdout.splitlines() if linha_out.startswith("RESULTADO ")),
        None,
    )
    assert linha is not None, (proc.stdout[-2000:], proc.stderr[-2000:])
    return json.loads(linha[len("RESULTADO ") :])


@pytest.mark.blender
@pytest.mark.lento
def test_personagem_upright_nao_e_invertido():
    info = _canonicalizar(RAIZ / "tests" / "fixtures" / "personagem_upright.glb")
    assert info["invertido"] is False, info
    # as regras antigas ficam neutras de proposito (e a nova tambem nao dispara)
    assert info["razao_topo_base"] <= 1.5, info
    assert info["centro_area"] >= 5.76, info
    assert info["invertido_contato"] is False, info


@pytest.mark.blender
@pytest.mark.lento
def test_personagem_invertido_com_prop_grande_e_corrigido():
    info = _canonicalizar(RAIZ / "tests" / "fixtures" / "personagem_invertido.glb")
    assert info["invertido"] is True, info
    assert info["invertido_contato"] is True, info
    assert info["contato_topo"] > 3.0 * info["contato_base"], info


@pytest.mark.blender
@pytest.mark.lento
def test_personagem_tpose_envergadura_maior_que_altura_nao_tomba(tmp_path: Path):
    """T-pose larga (envergadura X > altura Z) nao pode ser tombada de lado por canonicalizar."""
    script = tmp_path / "mk_tpose.py"
    glb = tmp_path / "tpose.glb"
    script.write_text(
        f"""
import bpy
bpy.ops.wm.read_factory_settings(use_empty=True)
partes = []
for loc, scale in [
    ((0.0, 0.0, 0.03), (0.30, 0.14, 0.03)),   # sola larga
    ((0.0, -0.14, 0.64), (0.32, 0.03, 0.62)), # capa longa puxando centro_area < 0.48*n
    ((0.0, 0.0, 0.70), (0.20, 0.10, 0.65)),   # corpo vertical (topo z=1.35)
    ((0.0, 0.0, 1.50), (0.09, 0.09, 0.12)),   # cabeca z=1.62 (altura total 1.62)
    ((0.0, 0.0, 1.25), (0.95, 0.07, 0.07)),   # bracos T-pose (envergadura 1.90 > 1.62)
]:
    bpy.ops.mesh.primitive_cube_add(size=2.0, location=loc)
    o = bpy.context.active_object
    o.scale = scale
    partes.append(o)
bpy.ops.object.select_all(action="DESELECT")
for o in partes:
    o.select_set(True)
bpy.context.view_layer.objects.active = partes[0]
bpy.ops.object.join()
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.select_all(action="SELECT")
bpy.ops.mesh.subdivide(number_cuts=5)
bpy.ops.object.mode_set(mode="OBJECT")
bpy.ops.export_scene.gltf(filepath={str(glb)!r}, export_format="GLB")
""",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [BLENDER, "--background", "--factory-startup", "--python", str(script)],
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    assert glb.is_file(), proc.stderr[-1000:]
    info = _canonicalizar(glb)
    assert info["altura_eixo"] == "Z", info
    assert info["largura_eixo"] == "X", info
    assert info["invertido"] is False, info


@pytest.mark.blender
@pytest.mark.lento
def test_canonicalizar_invertido_preserva_lateralidade_espada(tmp_path: Path):
    """EIXO-05: personagem invertido com espada na mao direita (-X) nao pode espelhar det<0."""
    script = tmp_path / "mk_inv_espada.py"
    out_info = tmp_path / "out_inv_espada.json"
    script.write_text(
        f"""
import json, math, sys
import bpy
from mathutils import Matrix
sys.path.insert(0, {str(RAIZ / "blender")!r})
import postprocess

bpy.ops.wm.read_factory_settings(use_empty=True)

def add_box(name, loc, scale):
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=loc)
    o = bpy.context.active_object
    o.name = name
    o.scale = scale
    return o

# Humanoide upright em Blender (+Y frente, -X direita): sola chata grande, cabeca fina, espada no braco -X
partes = [
    add_box("sola_l", (0.12, 0.09, 0.04), (0.14, 0.30, 0.08)),
    add_box("sola_r", (-0.12, 0.09, 0.04), (0.14, 0.30, 0.08)),
    add_box("perna_l", (0.12, 0.0, 0.45), (0.11, 0.11, 0.78)),
    add_box("perna_r", (-0.12, 0.0, 0.45), (0.11, 0.11, 0.78)),
    add_box("tronco", (0.0, 0.0, 1.15), (0.42, 0.24, 0.65)),
    add_box("cabeca", (0.0, 0.02, 1.65), (0.12, 0.12, 0.24)),
    add_box("espada_dir", (-0.42, 0.10, 1.10), (0.06, 0.06, 0.70)),
]
partes[-1].vertex_groups.new(name="espada").add(list(range(len(partes[-1].data.vertices))), 1.0, "REPLACE")
bpy.ops.object.select_all(action="DESELECT")
for o in partes:
    o.select_set(True)
bpy.context.view_layer.objects.active = partes[0]
bpy.ops.object.join()
obj = bpy.context.active_object
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.select_all(action="SELECT")
bpy.ops.mesh.subdivide(number_cuts=3)
bpy.ops.object.mode_set(mode="OBJECT")
# Vira de cabeca para baixo girando 180 no Y (lado direito -X vai para +X; frente +Y continua +Y)
obj.matrix_world = Matrix.Rotation(math.pi, 4, "Y") @ obj.matrix_world
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

info = postprocess.canonicalizar(obj, "personagem_humanoide")
vg_idx = obj.vertex_groups["espada"].index
xs_espada = [v.co.x for v in obj.data.vertices if any(g.group == vg_idx for g in v.groups)]
info["espada_x_medio"] = sum(xs_espada) / len(xs_espada)
with open({str(out_info)!r}, "w", encoding="utf-8") as fh:
    json.dump(info, fh)
""",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [BLENDER, "--background", "--factory-startup", "--python-exit-code", "1", "--python", str(script)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    info = json.loads(out_info.read_text(encoding="utf-8"))
    assert info["invertido"] is True, info
    # Rotacao pura (det=+1) + correcao de frente retorna a espada para o lado direito (-X)
    assert info["espada_x_medio"] < -0.22, info


@pytest.mark.blender
@pytest.mark.lento
def test_canonicalizar_corrige_humanoide_de_costas_e_preserva_quadrupede(tmp_path: Path):
    """EIXO-05: detecta humanoide virado de costas (-Y Blender / +Z glTF) e preserva altura Z de quadrupede."""
    script = tmp_path / "mk_frente_quad.py"
    out_info = tmp_path / "out_frente_quad.json"
    script.write_text(
        f"""
import json, math, sys
import bpy
from mathutils import Matrix
sys.path.insert(0, {str(RAIZ / "blender")!r})
import postprocess

bpy.ops.wm.read_factory_settings(use_empty=True)

def add_box(loc, scale):
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=loc)
    o = bpy.context.active_object
    o.scale = scale
    return o

# 1) Humanoide virado de costas (-Y em Blender): pes estendem para -Y em relacao as canelas
partes_h = [
    add_box((0.12, -0.09, 0.04), (0.12, 0.28, 0.08)),
    add_box((-0.12, -0.09, 0.04), (0.12, 0.28, 0.08)),
    add_box((0.12, 0.02, 0.45), (0.11, 0.11, 0.78)),
    add_box((-0.12, 0.02, 0.45), (0.11, 0.11, 0.78)),
    add_box((0.0, 0.0, 1.15), (0.42, 0.22, 0.65)),
    add_box((0.0, 0.0, 1.62), (0.14, 0.14, 0.24)),
]
bpy.ops.object.select_all(action="DESELECT")
for o in partes_h:
    o.select_set(True)
bpy.context.view_layer.objects.active = partes_h[0]
bpy.ops.object.join()
hum = bpy.context.active_object
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.select_all(action="SELECT")
bpy.ops.mesh.subdivide(number_cuts=3)
bpy.ops.object.mode_set(mode="OBJECT")
info_hum = postprocess.canonicalizar(hum, "personagem_humanoide")
zs_hum = [v.co.z for v in hum.data.vertices]
h_hum = max(zs_hum) - min(zs_hum)
pes_y = [v.co.y for v in hum.data.vertices if v.co.z <= 0.06 * h_hum]
can_y = [v.co.y for v in hum.data.vertices if 0.12 * h_hum <= v.co.z <= 0.30 * h_hum]
info_hum["pes_menos_canela_y"] = (sum(pes_y) / len(pes_y)) - (sum(can_y) / len(can_y))

# 2) Quadrupede 2.0m comprimento x 0.7m largura x 1.2m altura (Z deve permanecer altura)
bpy.ops.wm.read_factory_settings(use_empty=True)
partes_q = [
    add_box((0.0, 0.0, 0.85), (0.70, 1.80, 0.55)),
    add_box((0.0, 0.85, 1.05), (0.30, 0.35, 0.30)),
    add_box((0.22, 0.65, 0.35), (0.12, 0.12, 0.70)),
    add_box((-0.22, 0.65, 0.35), (0.12, 0.12, 0.70)),
    add_box((0.22, -0.65, 0.35), (0.12, 0.12, 0.70)),
    add_box((-0.22, -0.65, 0.35), (0.12, 0.12, 0.70)),
]
bpy.ops.object.select_all(action="DESELECT")
for o in partes_q:
    o.select_set(True)
bpy.context.view_layer.objects.active = partes_q[0]
bpy.ops.object.join()
quad = bpy.context.active_object
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
info_quad = postprocess.canonicalizar(quad, "criatura")
zs_q = [v.co.z for v in quad.data.vertices]
ys_q = [v.co.y for v in quad.data.vertices]
info_quad["ext_z"] = max(zs_q) - min(zs_q)
info_quad["ext_y"] = max(ys_q) - min(ys_q)

with open({str(out_info)!r}, "w", encoding="utf-8") as fh:
    json.dump({{"hum": info_hum, "quad": info_quad}}, fh)
""",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [BLENDER, "--background", "--factory-startup", "--python-exit-code", "1", "--python", str(script)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    res = json.loads(out_info.read_text(encoding="utf-8"))
    assert res["hum"]["girado_frente"] is True, res["hum"]
    assert res["hum"]["pes_menos_canela_y"] > 0.04, res["hum"]
    assert res["quad"]["invertido"] is False, res["quad"]
    assert res["quad"]["ext_z"] == pytest.approx(1.20, abs=0.05), res["quad"]
    assert res["quad"]["ext_y"] == pytest.approx(2.00, abs=0.08), res["quad"]


@pytest.mark.blender
def test_template_body_exportar_manter_rig_sem_rotacao_residual(tmp_path: Path):
    """EIXO-06: template_body.exportar(manter_rig=True) nao pode vazar node.rotation no glTF."""
    import struct

    script = tmp_path / "mk_tbody_exp.py"
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    script.write_text(
        f"""
import sys
import bpy
sys.path.insert(0, {str(RAIZ / "blender")!r})
import template_body

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.object.armature_add(enter_editmode=True, location=(0.0, 0.0, 0.0))
rig = bpy.context.active_object
rig.data.edit_bones[0].head = (0.0, 0.0, 0.0)
rig.data.edit_bones[0].tail = (0.0, 0.0, 1.0)
bpy.ops.object.mode_set(mode="OBJECT")

bpy.ops.mesh.primitive_cube_add(size=0.5, location=(0.0, 0.1, 0.5))
obj = bpy.context.active_object
vg = obj.vertex_groups.new(name="Bone")
vg.add(list(range(len(obj.data.vertices))), 1.0, "REPLACE")
obj.parent = rig
mod = obj.modifiers.new(name="Armature", type="ARMATURE")
mod.object = rig

template_body.exportar(obj, rig, {str(out_dir)!r}, manter_rig=True, nome_glb="tbody.glb")
""",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [BLENDER, "--background", "--factory-startup", "--python-exit-code", "1", "--python", str(script)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    raw = (out_dir / "tbody.glb").read_bytes()
    jlen, _ = struct.unpack_from("<II", raw, 12)
    gltf = json.loads(raw[20 : 20 + jlen].decode("utf-8"))
    joints = {j for s in gltf.get("skins", []) for j in s.get("joints", [])}
    for idx, no in enumerate(gltf.get("nodes", [])):
        if idx in joints:
            continue
        rot = no.get("rotation")
        if rot is not None:
            assert abs(rot[3]) > 0.999, f"No {no.get('name')} manteve rotacao residual: {rot}"


@pytest.mark.blender
def test_reparar_malha_nao_abre_buraco_em_triangulo_pequeno_e_metrica_bate_qc(tmp_path: Path):
    """Regressao G1 (capa.03/bule): triangulo valido com area ~8.5e-11 nao pode virar buraco
    apos reparar_malha, e limiar de frente do postprocess coincide com o do qc."""
    from forge3d import qc

    script = tmp_path / "mk_reparo_g1.py"
    out_glb = tmp_path / "mini.glb"
    out_info = tmp_path / "info.json"
    script.write_text(
        f"""
import json, sys, math
import bpy, bmesh
sys.path.insert(0, {str(RAIZ / "blender")!r})
import postprocess

assert hasattr(postprocess, "LIMIAR_SCORE_FRENTE")
limiar = postprocess.LIMIAR_SCORE_FRENTE

# Malha fechada (tetraedro escalado + patch com triangulo de aresta ~1.4e-5m, area ~8.5e-11)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=0.15)
obj = bpy.context.active_object
# Encolhe uma face a ~1.4e-5m de lado (area ~8.5e-11, valida no G1 > 1e-12)
bm = bmesh.new()
bm.from_mesh(obj.data)
bm.faces.ensure_lookup_table()
f0 = bm.faces[0]
c = f0.calc_center_median()
for v in f0.verts:
    d = (v.co - c).normalized()
    v.co = c + d * 8.1e-6  # lado ~ 1.4e-5 m -> area ~ 8.5e-11
bm.to_mesh(obj.data)
bm.free()

rep = postprocess.reparar_malha(obj)
med = postprocess.medir_geometria(obj)
postprocess.exportar({str(out_glb)!r}, [obj], False)
with open({str(out_info)!r}, "w", encoding="utf-8") as fh:
    json.dump({{"rep": rep, "med": med, "limiar": limiar}}, fh)
""",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [BLENDER, "--background", "--factory-startup", "--python-exit-code", "1", "--python", str(script)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    info = json.loads(out_info.read_text(encoding="utf-8"))
    assert info["limiar"] == qc.LIMIAR_SCORE_FRENTE
    assert info["med"]["nao_manifold"] == 0, info
    gl, bn = qc.ler_glb_bin(out_glb)
    topo = qc.topologia(gl, bn)
    assert topo["nao_manifold"] == 0, topo
    assert topo["degeneradas"] == 0, topo
    assert topo["invertidas"] == 0, topo

