"""Testes v0.8.0 de props AA procedurais, vidro refrativo/emissivo e pos-import Godot."""

from __future__ import annotations

import json
import math
import os
import shutil
import struct
import subprocess
from pathlib import Path

import pytest

from forge3d import post as post_mod
from forge3d import qc

RAIZ = Path(__file__).resolve().parents[1]
BLENDER_DIR = RAIZ / "blender"
POST_IMPORT_GD = RAIZ / "addons" / "forge3d" / "post_import.gd"
PROJ_GODOT = RAIZ / "tools" / "godot_project"


def _exigir_blender() -> str:
    try:
        return post_mod.binario()
    except Exception:
        pytest.skip("Blender 4.2 headless nao disponivel neste host")


def _encontrar_godot() -> str | None:
    env = os.environ.get("FORGE3D_GODOT")
    if env and Path(env).is_file():
        return env
    achado = shutil.which("godot")
    if achado:
        return achado
    padrao = Path.home() / "tools" / "godot" / "Godot_v4.3-stable_linux.x86_64"
    if padrao.is_file():
        return str(padrao)
    antigravity = Path.home() / ".gemini" / "antigravity" / "bin" / "godot"
    return str(antigravity) if antigravity.is_file() else None


def _rodar_blender_py(codigo: str, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    blender = _exigir_blender()
    return subprocess.run(
        [blender, "-b", "--factory-startup", "--python-expr", codigo],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _ler_glb_topo_e_verts(glb_path: Path) -> tuple[dict, dict, list[tuple[float, float, float]]]:
    raw = glb_path.read_bytes()
    jlen = struct.unpack_from("<I", raw, 12)[0]
    jend = 20 + jlen
    gltf = json.loads(raw[20:jend])
    blen = struct.unpack_from("<I", raw, jend)[0]
    binb = raw[jend + 8 : jend + 8 + blen]
    topo = qc.topologia(gltf, binb)
    verts: list[tuple[float, float, float]] = []
    for mesh in gltf.get("meshes", []):
        for prim in mesh.get("primitives", []):
            pos_idx = prim["attributes"]["POSITION"]
            acc = gltf["accessors"][pos_idx]
            bv = gltf["bufferViews"][acc["bufferView"]]
            off = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
            stride = bv.get("byteStride") or 12
            for i in range(acc["count"]):
                verts.append(struct.unpack_from("<3f", binb, off + i * stride))
    return gltf, topo, verts


def _gerar_prop_headless(parte: str, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    meta_out = out_dir / "meta_check.json"
    codigo = f"""
import json, sys
sys.path.insert(0, {str(BLENDER_DIR)!r})
import modular_armor
rel = modular_armor.gerar_modular_armor({{"parte": {parte!r}, "saida": {str(out_dir)!r}}})
obj = next(o for o in __import__("bpy").context.scene.objects if o.type == "MESH")
xs = [v.co.x for v in obj.data.vertices]
ys = [v.co.y for v in obj.data.vertices]
zs = [v.co.z for v in obj.data.vertices]
rel["bl_bounds"] = {{
    "min_x": min(xs), "max_x": max(xs),
    "min_y": min(ys), "max_y": max(ys),
    "min_z": min(zs), "max_z": max(zs),
}}
with open({str(meta_out)!r}, "w", encoding="utf-8") as fh:
    json.dump(rel, fh)
print("PROP_OK", rel["triangulos"])
"""
    proc = _rodar_blender_py(codigo)
    assert proc.returncode == 0 and "PROP_OK" in proc.stdout, proc.stdout + proc.stderr
    return json.loads(meta_out.read_text(encoding="utf-8"))


@pytest.mark.blender
def test_arma_forjada_manifold_multimaterial_e_pivo_empunhadura(tmp_path: Path) -> None:
    rel = _gerar_prop_headless("arma", tmp_path / "arma")
    glb = tmp_path / "arma" / "template_armor.glb"
    gltf, topo, verts = _ler_glb_topo_e_verts(glb)

    assert topo["nao_manifold"] == 0
    assert topo["degeneradas"] == 0
    assert topo["invertidas"] == 0
    assert topo["triangulos"] >= 800
    assert 1200 <= rel["triangulos"] <= 2200

    # Empunhadura centrada em (0, 0, 0): pomo abaixo (-Z_bl) e lamina acima (+Z_bl)
    bl = rel["bl_bounds"]
    assert bl["min_z"] < -0.08
    assert bl["max_z"] > 0.85
    # Em glTF (+Y up), ponta > 0.80 e pomo < -0.08
    gy = [v[1] for v in verts]
    assert min(gy) < -0.08 and max(gy) > 0.80

    mats = gltf.get("materials", [])
    assert len(mats) >= 4
    emissivos = [m for m in mats if "emissiveFactor" in m]
    metais = [m for m in mats if (m.get("pbrMetallicRoughness") or {}).get("metallicFactor", 0.0) >= 0.9]
    assert len(emissivos) >= 1
    assert len(metais) >= 2


@pytest.mark.blender
def test_orbe_arcano_refrativo_emissivo_aneis_e_raio_compacto(tmp_path: Path) -> None:
    rel = _gerar_prop_headless("orbe", tmp_path / "orbe")
    glb = tmp_path / "orbe" / "template_armor.glb"
    gltf, topo, verts = _ler_glb_topo_e_verts(glb)

    assert topo["nao_manifold"] == 0
    assert topo["degeneradas"] == 0
    assert topo["invertidas"] == 0
    assert 1200 <= rel["triangulos"] <= 1900

    max_r = max(math.sqrt(x * x + y * y + z * z) for x, y, z in verts)
    assert max_r < 0.11

    mats = gltf.get("materials", [])
    assert len(mats) == 3
    vidro = [
        m
        for m in mats
        if m.get("alphaMode") == "BLEND"
        and "KHR_materials_transmission" in (m.get("extensions") or {})
    ]
    nucleo = [m for m in mats if "emissiveFactor" in m]
    ouro = [m for m in mats if (m.get("pbrMetallicRoughness") or {}).get("metallicFactor", 0.0) >= 0.9]
    assert len(vidro) == 1
    assert vidro[0]["extensions"]["KHR_materials_transmission"]["transmissionFactor"] >= 0.85
    assert len(nucleo) == 1
    assert len(ouro) == 1


@pytest.mark.blender
def test_mochila_anatomica_alcas_ombro_e_multimaterial(tmp_path: Path) -> None:
    rel = _gerar_prop_headless("mochila", tmp_path / "mochila")
    glb = tmp_path / "mochila" / "template_armor.glb"
    gltf, topo, _ = _ler_glb_topo_e_verts(glb)

    assert topo["nao_manifold"] == 0
    assert topo["degeneradas"] == 0
    assert topo["invertidas"] == 0
    assert topo["triangulos"] >= 1000
    assert 1500 <= rel["triangulos"] <= 2600

    # Alcas anatomicas sobre as claviculas estendem-se para o peito (+Y_bl) e topo do rolo (Z_bl > 0)
    bl = rel["bl_bounds"]
    assert bl["max_y"] > 0.14
    assert bl["min_y"] < -0.15
    assert bl["max_z"] > 0.08

    mats = gltf.get("materials", [])
    assert len(mats) >= 3
    metais = [m for m in mats if (m.get("pbrMetallicRoughness") or {}).get("metallicFactor", 0.0) >= 0.85]
    assert len(metais) >= 1


@pytest.mark.blender
def test_capa_cloth_simulacao_dobras_manifold_e_fechos(tmp_path: Path) -> None:
    rel = _gerar_prop_headless("capa", tmp_path / "capa")
    glb = tmp_path / "capa" / "template_armor.glb"
    gltf, topo, verts = _ler_glb_topo_e_verts(glb)

    assert topo["nao_manifold"] == 0
    assert topo["degeneradas"] == 0
    assert topo["invertidas"] == 0
    assert 1300 <= rel["triangulos"] <= 2300

    # Confirma caimento vertical em -Z_bl (Y_gltf negativo) e dobras reais na barra
    bl = rel["bl_bounds"]
    assert bl["min_z"] < -0.70
    ys_gltf = [v[1] for v in verts]
    y_min, y_max = min(ys_gltf), max(ys_gltf)
    barra = [v for v in verts if v[1] < y_min + 0.18 * (y_max - y_min)]
    assert len(barra) >= 10
    z_barra = [v[2] for v in barra]
    assert (max(z_barra) - min(z_barra)) > 0.03

    mats = gltf.get("materials", [])
    assert len(mats) >= 2


@pytest.mark.blender
def test_textura_local_cristal_arcano_e_bake_multizona(tmp_path: Path) -> None:
    saida_bake = tmp_path / "bake"
    saida_bake.mkdir()
    codigo = f"""
import sys
sys.path.insert(0, {str(BLENDER_DIR)!r})
import bpy
import modular_armor, procedural_pbr, postprocess, bake_pbr

assert modular_armor._carregar_textura_pbr_local("nao_existe_123.png") is None

mat_c = procedural_pbr.criar_material_procedural("cristal_arcano")
bsdf_c = next(n for n in mat_c.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
assert mat_c.blend_method == "BLEND"
assert abs(bsdf_c.inputs["Transmission Weight"].default_value - 0.85) < 1e-4
assert abs(bsdf_c.inputs["Alpha"].default_value - 0.35) < 1e-4
assert abs(bsdf_c.inputs["Emission Strength"].default_value - 2.0) < 1e-4
assert abs(bsdf_c.inputs["Roughness"].default_value - 0.06) < 1e-4

postprocess.limpar_cena()
orbe = modular_armor._criar_orbe_arcano_procedural("OrbeCheck")
n_mats_antes = len(orbe.data.materials)
res = bake_pbr.executar_bake_high_low(
    obj=orbe,
    saida_dir={str(saida_bake)!r},
    nome_base="orbe_check",
    px=256,
    limite_triangulos=2400,
    reparo_fn=postprocess.reparar_malha,
    decimar_fn=postprocess.decimar,
    suavizar_fn=postprocess.suavizar_por_angulo,
    uv_fn=postprocess.desdobrar_uv,
    material_procedural="cristal_arcano",
    permitir_sem_cor_vertice=True,
)
assert len(orbe.data.materials) == n_mats_antes == 3
assert res["bake"]["multimaterial_preservado"] is True
print("PBR_MULTIZONA_OK")
"""
    proc = _rodar_blender_py(codigo)
    assert proc.returncode == 0 and "PBR_MULTIZONA_OK" in proc.stdout, proc.stdout + proc.stderr


def test_post_import_gd_preserva_vidro_emissivo_e_metais(tmp_path: Path) -> None:
    godot = _encontrar_godot()
    if not godot:
        pytest.skip("Godot 4 headless nao disponivel neste host")

    script_gd = tmp_path / "check_glass_guard.gd"
    script_gd.write_text(
        """extends SceneTree

const PostImport := preload("__POST_IMPORT__")

func _fail(msg: String) -> void:
\tprinterr("FAIL: " + msg)
\tquit(1)

func _initialize() -> void:
\tvar cena := Node3D.new()
\tvar mi := MeshInstance3D.new()
\tvar mesh := ArrayMesh.new()
\tvar st := SurfaceTool.new()

\t# Superficie 0: vidro refrativo com roughness alto legado (nao pode ser sobrescrito!)
\tst.begin(Mesh.PRIMITIVE_TRIANGLES)
\tst.add_vertex(Vector3(0, 0, 0)); st.add_vertex(Vector3(1, 0, 0)); st.add_vertex(Vector3(0, 1, 0))
\tmesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, st.commit_to_arrays())
\tvar m_glass := StandardMaterial3D.new()
\tm_glass.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
\tm_glass.metallic = 0.0
\tm_glass.roughness = 1.0
\tm_glass.refraction_enabled = true
\tmesh.surface_set_material(0, m_glass)

\t# Superficie 1: nucleo emissivo (nao pode ter roughness alterado!)
\tst.clear(); st.begin(Mesh.PRIMITIVE_TRIANGLES)
\tst.add_vertex(Vector3(0, 0, 0)); st.add_vertex(Vector3(1, 0, 0)); st.add_vertex(Vector3(0, 1, 0))
\tmesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, st.commit_to_arrays())
\tvar m_core := StandardMaterial3D.new()
\tm_core.emission_enabled = true
\tm_core.metallic = 0.0
\tm_core.roughness = 1.0
\tmesh.surface_set_material(1, m_core)

\t# Superficie 2: metal parcial/ouro (metallic > 0.05 nao pode ser alterado!)
\tst.clear(); st.begin(Mesh.PRIMITIVE_TRIANGLES)
\tst.add_vertex(Vector3(0, 0, 0)); st.add_vertex(Vector3(1, 0, 0)); st.add_vertex(Vector3(0, 1, 0))
\tmesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, st.commit_to_arrays())
\tvar m_gold := StandardMaterial3D.new()
\tm_gold.metallic = 0.65
\tm_gold.roughness = 1.0
\tmesh.surface_set_material(2, m_gold)

\t# Superficie 3: couro fosco opaco sem emissao (deve receber roughness = 0.65!)
\tst.clear(); st.begin(Mesh.PRIMITIVE_TRIANGLES)
\tst.add_vertex(Vector3(0, 0, 0)); st.add_vertex(Vector3(1, 0, 0)); st.add_vertex(Vector3(0, 1, 0))
\tmesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, st.commit_to_arrays())
\tvar m_matte := StandardMaterial3D.new()
\tm_matte.metallic = 0.0
\tm_matte.roughness = 1.0
\tmesh.surface_set_material(3, m_matte)

\tmi.mesh = mesh
\tcena.add_child(mi)
\tPostImport._configurar_materiais(cena, "", {}, {})

\tvar r0 := mi.mesh.surface_get_material(0) as StandardMaterial3D
\tvar r1 := mi.mesh.surface_get_material(1) as StandardMaterial3D
\tvar r2 := mi.mesh.surface_get_material(2) as StandardMaterial3D
\tvar r3 := mi.mesh.surface_get_material(3) as StandardMaterial3D

\tif r0.transparency != BaseMaterial3D.TRANSPARENCY_ALPHA or not is_equal_approx(r0.roughness, 1.0):
\t\t_fail("vidro foi alterado pelo fallback: r=%f" % r0.roughness); return
\tif not r1.emission_enabled or not is_equal_approx(r1.roughness, 1.0):
\t\t_fail("emissivo foi alterado pelo fallback: r=%f" % r1.roughness); return
\tif not is_equal_approx(r2.metallic, 0.65) or not is_equal_approx(r2.roughness, 1.0):
\t\t_fail("metal > 0.05 foi alterado: m=%f r=%f" % [r2.metallic, r2.roughness]); return
\tif not is_equal_approx(r3.roughness, 0.65) or not is_equal_approx(r3.metallic, 0.0):
\t\t_fail("dieletrico fosco nao recebeu fallback 0.65: r=%f" % r3.roughness); return

\tprint("GODOT_GLASS_GUARD_OK")
\tcena.free()
\tquit(0)
""".replace("__POST_IMPORT__", str(POST_IMPORT_GD)),
        encoding="utf-8",
    )
    proc = subprocess.run(
        [godot, "--headless", "--path", str(PROJ_GODOT), "--script", str(script_gd)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0 and "GODOT_GLASS_GUARD_OK" in proc.stdout, proc.stdout + proc.stderr
