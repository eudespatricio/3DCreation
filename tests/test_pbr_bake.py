"""Testes da Fase A: bake PBR High->Low (BaseColor, Normal, ORM) dentro do teto de 2048 KB."""

from __future__ import annotations

import ast
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from forge3d import post, qc
from forge3d.providers import mesh

RAIZ = Path(__file__).resolve().parents[1]
BAKE_PBR = RAIZ / "blender" / "bake_pbr.py"


def _encontrar_godot() -> str | None:
    import os

    env = os.environ.get("FORGE3D_GODOT")
    if env and Path(env).is_file():
        return env
    achado = shutil.which("godot")
    if achado:
        return achado
    padrao = Path.home() / "tools" / "godot" / "Godot_v4.3-stable_linux.x86_64"
    return str(padrao) if padrao.is_file() else None


def _rodar_blender_py(codigo: str, timeout: int = 180) -> subprocess.CompletedProcess[str]:
    blender = post.binario()
    return subprocess.run(
        [blender, "--background", "--factory-startup", "--python-expr", codigo],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def test_bake_pbr_usa_apenas_bpy_bmesh_mathutils_e_stdlib():
    arvore = ast.parse(BAKE_PBR.read_text(encoding="utf-8"))
    permitidos = {"__future__", "array", "math", "os", "bpy", "bmesh", "mathutils"}
    encontrados: set[str] = set()
    for node in ast.walk(arvore):
        if isinstance(node, ast.Import):
            for alias in node.names:
                encontrados.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            encontrados.add(node.module.split(".")[0])
    assert encontrados <= permitidos, f"imports nao permitidos: {encontrados - permitidos}"
    assert "PIL" not in encontrados and "numpy" not in encontrados


def test_mesh_provider_versao_e_tex_px_1024(monkeypatch, tmp_path):
    assert mesh.VERSAO == "0.1.8"
    monkeypatch.delenv("FORGE3D_TEX_PX", raising=False)
    prov = mesh.MeshProvider()
    assert "+tex1024+" in prov.versao

    img_in = tmp_path / "concept.png"
    Image.new("RGBA", (64, 64), (200, 120, 80, 255)).save(img_in)
    destino = tmp_path / "raw"

    def fake_run(cmd, **_kwargs):
        out_dir = Path(cmd[cmd.index("--saida-dir") + 1])
        (out_dir / "modelo.glb").write_bytes(b"glTF")
        (out_dir / "i23d_resultado.json").write_text(
            json.dumps({"ok": True, "torch": "2.4.1", "faces": 12000}), encoding="utf-8"
        )
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(prov, "preflight_item", lambda item: (True, "ok"))
    monkeypatch.setattr(mesh.subprocess, "run", fake_run)

    item = {"id": "prop.teste.01", "tipo": "prop_estatico", "origem": str(img_in)}
    prov.gerar(item, {"perfil": "godot4"}, destino)
    modelo = json.loads((destino / "modelo.json").read_text(encoding="utf-8"))
    assert modelo["textura_px"] == 1024

    monkeypatch.setenv("FORGE3D_TEX_PX", "512")
    assert "+tex512+" in prov.versao
    prov.gerar(item, {"perfil": "godot4"}, tmp_path / "raw_512")
    modelo_512 = json.loads((tmp_path / "raw_512" / "modelo.json").read_text(encoding="utf-8"))
    assert modelo_512["textura_px"] == 512


@pytest.mark.blender
def test_bake_pbr_falha_sem_color_attributes(tmp_path):
    saida = tmp_path / "saida"
    codigo = f"""
import sys
sys.path.insert(0, {str(RAIZ / "blender")!r})
import bpy
import postprocess, bake_pbr

postprocess.limpar_cena()
bpy.ops.mesh.primitive_cube_add(size=1.0)
obj = bpy.context.active_object
assert not obj.data.color_attributes
try:
    bake_pbr.executar_bake_high_low(
        obj, {str(saida)!r}, "sem_cor", 128, 100,
        postprocess.reparar_malha, postprocess.decimar,
        postprocess.suavizar_por_angulo, postprocess.desdobrar_uv,
    )
    raise AssertionError("era esperado RuntimeError")
except RuntimeError as exc:
    print("ERRO_ESPERADO:", exc)
"""
    proc = _rodar_blender_py(codigo, timeout=120)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "ERRO_ESPERADO:" in proc.stdout


@pytest.mark.blender
@pytest.mark.lento
def test_bake_pbr_high_low_12k_para_6k_glb_e_godot(tmp_path):
    saida = tmp_path / "saida"
    saida.mkdir()
    nome_base = "prop.pbr.teste.01"
    meta_path = tmp_path / "meta.json"
    glb_path = saida / f"{nome_base}.glb"

    codigo = f"""
import json, math, sys
sys.path.insert(0, {str(RAIZ / "blender")!r})
import bpy, bmesh
import postprocess, bake_pbr

postprocess.limpar_cena()
# 80x76 UV sphere -> 12000 tris exatamente, sem UV, com deslocamento e cor por vertice
bpy.ops.mesh.primitive_uv_sphere_add(segments=80, ring_count=76, radius=0.9)
obj = bpy.context.active_object
bm = bmesh.new()
bm.from_mesh(obj.data)
for v in bm.verts:
    onda = 1.0 + 0.12 * math.sin(v.co.x * 10.0) * math.cos(v.co.y * 10.0) + 0.06 * math.sin(v.co.z * 14.0)
    v.co *= onda
bm.to_mesh(obj.data)
bm.free()
obj.data.update()

while obj.data.uv_layers:
    obj.data.uv_layers.remove(obj.data.uv_layers[0])

ca = obj.data.color_attributes.new("Color", "FLOAT_COLOR", "POINT")
for i, v in enumerate(obj.data.vertices):
    r = max(0.0, min(1.0, 0.5 + 0.45 * math.sin(v.co.x * 5.0 + v.co.z * 3.0)))
    g = max(0.0, min(1.0, 0.5 + 0.45 * math.cos(v.co.y * 6.0)))
    b = max(0.0, min(1.0, 0.5 + 0.45 * math.sin(v.co.z * 7.0)))
    ca.data[i].color = (r, g, b, 1.0)

res = bake_pbr.executar_bake_high_low(
    obj=obj,
    saida_dir={str(saida)!r},
    nome_base={nome_base!r},
    px=1024,
    limite_triangulos=6000,
    reparo_fn=postprocess.reparar_malha,
    decimar_fn=postprocess.decimar,
    suavizar_fn=postprocess.suavizar_por_angulo,
    uv_fn=postprocess.desdobrar_uv,
)

assert len([o for o in bpy.context.scene.objects if o.type == "MESH"]) == 1
assert len(obj.data.color_attributes) == 0
assert len(obj.data.uv_layers) == 1
assert len(obj.data.materials) == 1

obj.name = {nome_base!r}
obj.data.name = {nome_base!r}
postprocess.exportar({str(glb_path)!r}, [obj], False)

with open({str(meta_path)!r}, "w", encoding="utf-8") as fh:
    json.dump(res, fh, indent=1)
print("BAKE_PBR_TEST_OK")
"""
    proc = _rodar_blender_py(codigo, timeout=180)
    assert proc.returncode == 0 and "BAKE_PBR_TEST_OK" in proc.stdout, proc.stdout + proc.stderr

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["textura_px"] == 1024
    assert meta["normal_px"] == 512
    assert meta["orm_px"] == 512
    assert meta["bake"]["triangulos_high"] == 12000
    assert meta["bake"]["triangulos_low"] <= 6000
    assert meta["bake"]["cage_extrusion"] == pytest.approx(
        max(0.02, 0.03 * meta["bake"]["bbox_diag"]), abs=1e-5
    )

    papeis = {a["papel"]: a["caminho"] for a in meta["arquivos_textura"]}
    assert papeis == {
        "textura": f"{nome_base}_baseColor.png",
        "normal": f"{nome_base}_normal.png",
        "orm": f"{nome_base}_orm.png",
    }

    # Verifica dimensoes, modo RGB e conteudo real dos 3 PNGs
    with Image.open(saida / papeis["textura"]) as im_bc:
        assert im_bc.size == (1024, 1024)
        assert im_bc.mode == "RGB"
        extrema_bc = im_bc.getextrema()
        assert all(hi > lo + 20 for lo, hi in extrema_bc), extrema_bc

    with Image.open(saida / papeis["normal"]) as im_nm:
        assert im_nm.size == (512, 512)
        assert im_nm.mode == "RGB"
        r_ext, g_ext, b_ext = im_nm.getextrema()
        assert r_ext[1] > r_ext[0] + 10 and g_ext[1] > g_ext[0] + 10
        assert b_ext[1] >= 250

    with Image.open(saida / papeis["orm"]) as im_orm:
        assert im_orm.size == (512, 512)
        assert im_orm.mode == "RGB"
        r_ext, g_ext, b_ext = im_orm.getextrema()
        assert r_ext[1] > 100
        # Roughness limitado a [0.50, 0.90] -> ~[128, 230] em 8-bit
        assert g_ext[0] >= 127 and g_ext[1] <= 230, g_ext
        # Metallic = 0.0 em toda a imagem
        assert b_ext == (0, 0), b_ext

    # Verifica GLB exportado: orcamento 2048 KB, topologia e canais PBR glTF
    assert glb_path.is_file()
    glb_bytes = glb_path.stat().st_size
    assert glb_bytes <= 2048 * 1024, f"GLB excedeu 2048 KB: {glb_bytes} bytes"

    gltf, binario = qc.ler_glb_bin(glb_path)
    info = qc.analisar(gltf)
    topo = qc.topologia(gltf, binario)
    assert info["triangulos"] <= 6000
    assert info["sem_uv"] == 0
    assert info["imagens"] == 3
    assert info["imagens_externas"] == []
    assert topo["nao_manifold"] == 0
    assert topo["degeneradas"] == 0

    mats = gltf.get("materials", [])
    assert len(mats) == 1
    mat = mats[0]
    assert mat.get("doubleSided", False) is False
    pbr = mat.get("pbrMetallicRoughness") or {}
    assert "baseColorTexture" in pbr
    assert "metallicRoughnessTexture" in pbr
    assert "normalTexture" in mat
    assert "occlusionTexture" in mat
    # ORM compartilha a mesma textura/imagem entre metallicRoughnessTexture e occlusionTexture
    mr_tex_idx = pbr["metallicRoughnessTexture"]["index"]
    occ_tex_idx = mat["occlusionTexture"]["index"]
    assert gltf["textures"][mr_tex_idx]["source"] == gltf["textures"][occ_tex_idx]["source"]

    godot = _encontrar_godot()
    if godot:
        proj = RAIZ / "tools" / "godot_project"
        pi = subprocess.run(
            [
                godot,
                "--headless",
                "--path",
                str(proj),
                "--script",
                str(RAIZ / "tools" / "godot_post_import_check.gd"),
                "--",
                str(glb_path),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert pi.returncode == 0 and "GODOT_POST_IMPORT_OK" in pi.stdout, pi.stdout + pi.stderr


@pytest.mark.blender
def test_bake_pbr_px_256_e_cage_minimo(tmp_path):
    saida = tmp_path / "saida"
    saida.mkdir()
    meta_path = tmp_path / "meta.json"
    glb_path = saida / "mini.glb"

    codigo = f"""
import json, sys
sys.path.insert(0, {str(RAIZ / "blender")!r})
import bpy
import postprocess, bake_pbr

postprocess.limpar_cena()
bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=0.05)
obj = bpy.context.active_object
ca = obj.data.color_attributes.new("Color", "FLOAT_COLOR", "POINT")
for i, v in enumerate(obj.data.vertices):
    ca.data[i].color = (0.2 + 0.5 * (v.co.x > 0), 0.7, 0.4, 1.0)

res = bake_pbr.executar_bake_high_low(
    obj=obj,
    saida_dir={str(saida)!r},
    nome_base="mini",
    px=256,
    limite_triangulos=500,
    reparo_fn=postprocess.reparar_malha,
    decimar_fn=postprocess.decimar,
    suavizar_fn=postprocess.suavizar_por_angulo,
    uv_fn=postprocess.desdobrar_uv,
)
postprocess.exportar({str(glb_path)!r}, [obj], False)
with open({str(meta_path)!r}, "w", encoding="utf-8") as fh:
    json.dump(res, fh)
print("MINI_OK")
"""
    proc = _rodar_blender_py(codigo, timeout=120)
    assert proc.returncode == 0 and "MINI_OK" in proc.stdout, proc.stdout + proc.stderr

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["textura_px"] == 256
    assert meta["normal_px"] == 256
    assert meta["orm_px"] == 256
    assert meta["bake"]["cage_extrusion"] == pytest.approx(0.02)

    for suffix in ("baseColor", "normal", "orm"):
        with Image.open(saida / f"mini_{suffix}.png") as im:
            assert im.size == (256, 256)

    gltf = qc.ler_glb(glb_path)
    mat = gltf["materials"][0]
    assert mat.get("doubleSided", False) is False
    assert "baseColorTexture" in mat["pbrMetallicRoughness"]
    assert "metallicRoughnessTexture" in mat["pbrMetallicRoughness"]
    assert "normalTexture" in mat
