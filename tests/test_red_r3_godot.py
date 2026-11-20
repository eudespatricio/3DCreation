"""Suite TDD RED (descoberta) para R3 — Godot 4 Game-Ready (F15-F21).

Cada teste valida o contrato comportamental esperado e deve FALHAR (RED)
no working tree atual ate que os defeitos de R3 sejam corrigidos.
"""

from __future__ import annotations

import io
import json
import math
import re
import shutil
import struct
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from forge3d import animacao, config, post, profiles, publish, sync
from forge3d.canonical import sha256_arquivo
from tests.test_godot_addon import (
    PLUGIN_GD, POST_IMPORT_GD, PROJ_GODOT, RAIZ,
    _criar_glb_colisor, _criar_glb_multimesh, _escrever_glb,
    _exigir_godot, _rodar_godot, _validar_cena_godot,
)
from tests.test_seguranca_e_qc import _glb_bytes

SCENE_POST_IMPORT_GD = RAIZ / "addons" / "forge3d" / "scene_post_import_plugin.gd"
VISUAL_QA_GD = RAIZ / "tools" / "godot_visual_qa.gd"
BENCH_GD = RAIZ / "tools" / "godot_draw_calls_bench.gd"


@pytest.fixture(autouse=True)
def _isolar_forge3d(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORGE3D_HOME", str(tmp_path / "forge_home"))
    monkeypatch.setenv("FORGE3D_CONFIG", str(tmp_path / "forge_cfg"))
    config.adicionar(tmp_path)


def _rodar_blender_py(tmp_path: Path, codigo: str, *args: str) -> subprocess.CompletedProcess[str]:
    try:
        blender = post.binario()
    except Exception:
        blender = shutil.which("blender") or ""
    if not blender or not Path(blender).is_file():
        pytest.skip("Blender 4.2.x nao disponivel neste host")
    script = tmp_path / "run_blender_probe.py"
    script.write_text(codigo, encoding="utf-8")
    proc = subprocess.run(
        [blender, "--background", "--factory-startup", "--python-exit-code", "1", "--python", str(script), "--", *args],
        capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return proc


def _ler_glb_json(caminho: Path) -> dict:
    raw = caminho.read_bytes()
    jlen = struct.unpack_from("<I", raw, 12)[0]
    return json.loads(raw[20 : 20 + jlen].decode("utf-8"))


def _criar_glb_multisurface(caminho: Path, escala: float = 1.0) -> None:
    dados, views, acessores = bytearray(), [], []

    def add_view(blob: bytes, target: int | None = None) -> int:
        dados.extend(b"\x00" * ((-len(dados)) % 4))
        off = len(dados)
        dados.extend(blob)
        v: dict = {"buffer": 0, "byteOffset": off, "byteLength": len(blob)}
        if target is not None:
            v["target"] = target
        views.append(v)
        return len(views) - 1

    verts = [(0.0, 0.0, 0.0), (escala, 0.0, 0.0), (0.0, escala, 0.0), (escala, escala, 0.0)]
    v_pos = add_view(b"".join(struct.pack("<3f", *p) for p in verts), 34962)
    acessores.append({"bufferView": v_pos, "componentType": 5126, "count": 4, "type": "VEC3", "min": [0.0, 0.0, 0.0], "max": [escala, escala, 0.0]})
    acessores.append({"bufferView": add_view(b"".join(struct.pack("<3f", 0.0, 0.0, 1.0) for _ in verts), 34962), "componentType": 5126, "count": 4, "type": "VEC3"})
    acessores.append({"bufferView": add_view(b"".join(struct.pack("<2f", u, v) for u, v in [(0, 0), (1, 0), (0, 1), (1, 1)]), 34962), "componentType": 5126, "count": 4, "type": "VEC2"})
    acessores.append({"bufferView": add_view(struct.pack("<3H", 0, 1, 2), 34963), "componentType": 5123, "count": 3, "type": "SCALAR"})
    acessores.append({"bufferView": add_view(struct.pack("<3H", 1, 3, 2), 34963), "componentType": 5123, "count": 3, "type": "SCALAR"})
    buf = io.BytesIO()
    Image.new("RGB", (16, 16), (40, 200, 220)).save(buf, format="PNG")
    v_img = add_view(buf.getvalue())
    gltf = {
        "asset": {"version": "2.0", "generator": "forge3d-red-r3"}, "scene": 0, "scenes": [{"nodes": [0]}],
        "nodes": [{"name": "PropMulti", "mesh": 0}],
        "meshes": [{"name": "PropMulti", "primitives": [
            {"attributes": {"POSITION": 0, "NORMAL": 1, "TEXCOORD_0": 2}, "indices": 3, "material": 0},
            {"attributes": {"POSITION": 0, "NORMAL": 1, "TEXCOORD_0": 2}, "indices": 4, "material": 1},
        ]}],
        "images": [{"bufferView": v_img, "mimeType": "image/png"}], "textures": [{"source": 0}],
        "materials": [
            {"name": "MatBase", "pbrMetallicRoughness": {"baseColorFactor": [1.0, 1.0, 1.0, 1.0], "metallicFactor": 0.0, "roughnessFactor": 1.0}},
            {"name": "MatMetalEmissive", "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}, "metallicFactor": 0.85, "roughnessFactor": 0.25}, "emissiveFactor": [0.4, 0.1, 0.0]},
        ],
        "accessors": acessores, "bufferViews": views, "buffers": [{"byteLength": len(dados)}],
    }
    _escrever_glb(caminho, gltf, bytes(dados))


def _publicar_asset_sync(base: Path, asset_id: str, *, glb_bytes: bytes, rig: dict | None = None, animacoes: list[dict] | None = None, com_texturas: bool = True) -> Path:
    origem = base / f"origem_{asset_id}"
    staging = base / f"staging_{asset_id}"
    staging.mkdir(parents=True, exist_ok=True)
    (staging / f"{asset_id}.glb").write_bytes(glb_bytes)
    files = [{"caminho": f"{asset_id}.glb", "papel": "mesh", "sha256": sha256_arquivo(staging / f"{asset_id}.glb"), "bytes": len(glb_bytes)}]
    if com_texturas:
        for suf, papel, cor in (("baseColor", "textura", (200, 180, 160)), ("normal", "normal", (128, 128, 255)), ("orm", "orm", (255, 180, 40))):
            arq = staging / f"{asset_id}_{suf}.png"
            Image.new("RGB", (32, 32), cor).save(arq)
            files.append({"caminho": arq.name, "papel": papel, "sha256": sha256_arquivo(arq), "bytes": arq.stat().st_size})
    man = {
        "schema": "forge3d/manifest@6", "asset_id": asset_id, "projeto": "demo", "perfil": "godot4", "rota": "mesh", "tags": ["r3"],
        "spec_hash": "sha256:" + "a" * 64, "pipeline_version": "0.9.4", "determinism": "D2",
        "providers": {"geometry": {"name": "mesh", "version": "0.1.8", "license": "MIT", "seed": 1}},
        "geometry": {"triangulos": 12, "vertices": 8, "bbox_m": [1.0, 1.0, 1.0], "materiais": 1},
        "unidades_export": {"metros_por_unidade": 1.0, "escala_saida": 1.0},
        "animacoes": list(animacoes or []), "rig": rig,
        "lod": [{"nivel": 0, "triangulos": 12, "arquivo": f"{asset_id}.glb"}],
        "colisao": {"tipo": "none", "partes": 0}, "files": files,
        "qc": {"aprovado": True, "gates": [{"id": "G2", "status": "ok", "medido": {"esperado_m": 1.0, "pivo_regra": "base"}}, {"id": "G9", "status": "ok", "medido": {"triangulos": 12, "limite": 500}}]},
        "licenca": {"modelo": "MIT", "uso_comercial": True, "notice": "fixture"},
        "origem_spec": {"arquivo": "lote.yaml", "hash": "sha256:" + "a" * 64},
        "run_id": f"run-{asset_id}", "created_at": "2026-11-18T00:00:00Z",
    }
    publish.publicar(staging, origem, man, f"run-{asset_id}")
    return origem


def test_f15_orm_material_metallic_roughness_e_multi_surface(tmp_path: Path) -> None:
    godot = _exigir_godot()
    asset_id = "prop.f15.orm"
    glb = tmp_path / f"{asset_id}.glb"
    _criar_glb_multisurface(glb)
    for suf, cor in (("baseColor", (200, 100, 80)), ("normal", (128, 128, 255)), ("orm", (255, 180, 64))):
        Image.new("RGB", (32, 32), cor).save(tmp_path / f"{asset_id}_{suf}.png")
    (tmp_path / f"{asset_id}.manifest.json").write_text(json.dumps({"schema": "forge3d/manifest@6", "asset_id": asset_id, "perfil": "godot4", "determinism": "D2", "rota": "mesh"}), encoding="utf-8")
    corpo_gd = """
\tvar mi := cena.find_children("*", "MeshInstance3D", true, false)[0] as MeshInstance3D
\tvar m0 := mi.mesh.surface_get_material(0)
\tif not (m0 is ORMMaterial3D):
\t\t_fail("surface 0 nao e ORMMaterial3D", cena); return
\tvar o0 := m0 as ORMMaterial3D
\tif o0.orm_texture == null or not is_equal_approx(o0.metallic, 1.0) or not is_equal_approx(o0.roughness, 1.0):
\t\t_fail("surface 0 ORM exige metallic=1.0 e roughness=1.0 (m=%.2f r=%.2f)" % [o0.metallic, o0.roughness], cena); return
\tvar m1 := mi.mesh.surface_get_material(1)
\tif not (m1 is ORMMaterial3D):
\t\t_fail("surface 1 (metallic>0.05/emissive) perdeu ORMMaterial3D", cena); return
\tvar o1 := m1 as ORMMaterial3D
\tif o1.orm_texture == null or o1.normal_texture == null:
\t\t_fail("surface 1 perdeu orm_texture ou normal_texture", cena); return
\tif o1.albedo_texture == null or o1.albedo_texture == o0.albedo_texture:
\t\t_fail("surface 1 teve albedo_texture proprio sobrescrito ou ausente", cena); return
"""
    _validar_cena_godot(godot, tmp_path / "f15_orm.gd", corpo_gd, glb)


def test_f15_sync_gera_png_import_sidecars(tmp_path: Path) -> None:
    origem = _publicar_asset_sync(tmp_path, "prop.f15.sync", glb_bytes=_glb_bytes(no_nome="prop.f15.sync"), com_texturas=True)
    proj = tmp_path / "godot_proj_f15"
    proj.mkdir()
    (proj / "project.godot").write_text('[application]\nconfig/name="f15"\n', encoding="utf-8")
    sync.executar(origem, proj / "assets", limpar=True)
    for suf in ("baseColor", "normal", "orm"):
        imp = proj / "assets" / f"prop.f15.sync_{suf}.png.import"
        assert imp.is_file(), f"sidecar .png.import ausente: {imp}"
        txt = imp.read_text(encoding="utf-8")
        assert "compress/mode=2" in txt
        if suf == "normal":
            assert "compress/normal_map=1" in txt


def _glb_rigged_qc_valido(no_nome: str, clipes: tuple[str, ...]) -> bytes:
    ossos = list(profiles.carregar("godot4")["rig"]["mapas"]["godot-humanoid@1"])
    base = _glb_bytes(ossos=ossos, no_nome=no_nome)
    jlen = struct.unpack_from("<I", base, 12)[0]
    blen = struct.unpack_from("<I", base, 20 + jlen)[0]
    gltf = json.loads(base[20 : 20 + jlen].decode("utf-8"))
    buf = bytearray(base[28 + jlen : 28 + jlen + blen])
    t_off = len(buf)
    buf.extend(struct.pack("<3f", 0.0, 0.5, 1.0))
    r_off = len(buf)
    buf.extend(struct.pack("<4f", 0.0, 0.0, 0.0, 1.0) + struct.pack("<4f", 0.0, 0.25, 0.0, 0.9682) + struct.pack("<4f", 0.0, 0.0, 0.0, 1.0))
    gltf["bufferViews"].extend([{"buffer": 0, "byteOffset": t_off, "byteLength": 12}, {"buffer": 0, "byteOffset": r_off, "byteLength": 48}])
    acc_t, acc_r = len(gltf["accessors"]), len(gltf["accessors"]) + 1
    gltf["accessors"].extend([
        {"bufferView": len(gltf["bufferViews"]) - 2, "componentType": 5126, "count": 3, "type": "SCALAR", "min": [0.0], "max": [1.0]},
        {"bufferView": len(gltf["bufferViews"]) - 1, "componentType": 5126, "count": 3, "type": "VEC4"},
    ])
    hips_idx = next(i for i, n in enumerate(gltf["nodes"]) if n.get("name") == "Hips")
    spine_idx = next(i for i, n in enumerate(gltf["nodes"]) if n.get("name") == "Spine")
    gltf["buffers"][0]["byteLength"] = len(buf)
    gltf["animations"] = [{"name": c, "samplers": [{"input": acc_t, "output": acc_r, "interpolation": "LINEAR"}], "channels": [{"sampler": 0, "target": {"node": hips_idx, "path": "rotation"}}, {"sampler": 0, "target": {"node": spine_idx, "path": "rotation"}}]} for c in clipes]
    jb = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    jb += b" " * ((-len(jb)) % 4)
    total = 12 + 8 + len(jb) + 8 + len(buf)
    return struct.pack("<3I", 0x46546C67, 2, total) + struct.pack("<2I", len(jb), 0x4E4F534A) + jb + struct.pack("<2I", len(buf), 0x004E4942) + bytes(buf)


def test_f16_sync_gera_glb_import_com_params_e_subresources(tmp_path: Path) -> None:
    clipes = ("idle", "walk", "slash_combo", "hit")
    glb_bytes = _glb_rigged_qc_valido("hero.f16", clipes)
    anims = [{"nome": c, "duracao_s": 1.0, "ossos": ["Hips"]} for c in clipes]
    ossos_n = len(profiles.carregar("godot4")["rig"]["mapas"]["godot-humanoid@1"])
    origem = _publicar_asset_sync(tmp_path, "hero.f16", glb_bytes=glb_bytes, rig={"esqueleto": "godot-humanoid@1", "ossos": ossos_n}, animacoes=anims, com_texturas=False)
    proj = tmp_path / "godot_proj_f16"
    proj.mkdir()
    (proj / "project.godot").write_text('[application]\nconfig/name="f16"\n', encoding="utf-8")
    sync.executar(origem, proj / "assets", limpar=True)

    imp = (proj / "assets" / "hero.f16.glb.import").read_text(encoding="utf-8")
    assert "meshes/ensure_tangents=true" in imp
    assert "meshes/light_baking=2" in imp
    assert "skins/use_named_skins=true" in imp
    assert "animation/fps=24" in imp
    assert "_subresources=" in imp and "retarget/bone_map" in imp and "loop_mode" in imp


def test_f17_post_import_idempotente_e_sem_source_queue(tmp_path: Path) -> None:
    assert "_source_queue" not in PLUGIN_GD.read_text(encoding="utf-8")
    assert "_source_queue" not in SCENE_POST_IMPORT_GD.read_text(encoding="utf-8")
    godot = _exigir_godot()
    asset_id = "prop.f17.idem"
    glb = tmp_path / f"{asset_id}.glb"
    col = tmp_path / f"{asset_id}_colisao.glb"
    _criar_glb_multimesh(glb, [asset_id])
    _criar_glb_colisor(col, f"{asset_id}_col")
    (tmp_path / f"{asset_id}.manifest.json").write_text(json.dumps({"schema": "forge3d/manifest@6", "asset_id": asset_id, "perfil": "godot4", "colisao": {"arquivo": col.name, "partes": 1, "tipo": "convex"}}), encoding="utf-8")
    corpo_gd = """
\tvar n1 := cena.find_children("*", "StaticBody3D", true, false).size()
\tPostImport.aplicar(cena, caminho)
\tvar n2 := cena.find_children("*", "StaticBody3D", true, false).size()
\tif n1 != 1 or n2 != 1:
\t\t_fail("StaticBody3D duplicado na re-execucao: %d -> %d" % [n1, n2], cena); return
"""
    _validar_cena_godot(godot, tmp_path / "f17_idem.gd", corpo_gd, glb)


def test_f18_bone_map_inclui_root_e_upper_chest(tmp_path: Path) -> None:
    godot = _exigir_godot()
    script = tmp_path / "f18_bonemap.gd"
    script.write_text(
        f"""extends SceneTree
const PostImport := preload({str(POST_IMPORT_GD)!r})
func _initialize() -> void:
\tvar bm1 := PostImport.criar_bone_map_humanoid("godot-humanoid@1")
\tvar bm2 := PostImport.criar_bone_map_humanoid("godot-humanoid-aa@1")
\tprint("ROOT=", bm1.get_skeleton_bone_name("Root"))
\tprint("UPPER=", bm2.get_skeleton_bone_name("UpperChest"))
\tquit(0)
""",
        encoding="utf-8",
    )
    proc = _rodar_godot(godot, ["--script", str(script)])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert re.search(r"^ROOT=.+$", proc.stdout, re.MULTILINE), proc.stdout
    assert re.search(r"^UPPER=.+$", proc.stdout, re.MULTILINE), proc.stdout


@pytest.mark.blender
def test_f18_sockets_handl_consistency_e_montar_character_body(tmp_path: Path) -> None:
    godot = _exigir_godot()
    glb = tmp_path / "hero_f18.glb"
    socks_json = tmp_path / "hero_f18_sockets.json"
    _rodar_blender_py(
        tmp_path,
        f"""import json, sys, bpy, bmesh
sys.path.insert(0, {str(RAIZ / "blender")!r})
import autorig, postprocess
bpy.ops.wm.read_factory_settings(use_empty=True)
bm = bmesh.new(); bmesh.ops.create_cube(bm, size=1.8)
for v in bm.verts: v.co.z += 0.9
me = bpy.data.meshes.new("Hero"); bm.to_mesh(me); bm.free()
obj = bpy.data.objects.new("Hero", me); bpy.context.collection.objects.link(obj)
rig, _ = autorig.auto_rigar_humanoide(obj, "godot-humanoid@1", postprocess.criar_armadura)
socks = autorig.extrair_sockets(rig, obj)
postprocess.exportar(sys.argv[-2], [obj, rig], True, False)
with open(sys.argv[-1], "w", encoding="utf-8") as f: json.dump(socks, f)
""",
        str(glb), str(socks_json),
    )
    socks = json.loads(socks_json.read_text(encoding="utf-8"))
    (tmp_path / "hero_f18.manifest.json").write_text(json.dumps({"schema": "forge3d/manifest@6", "asset_id": "hero_f18", "perfil": "godot4", "rig": {"esqueleto": "godot-humanoid@1", "ossos": 23}, "sockets": socks}), encoding="utf-8")
    hr = next(s["posicao_local"] for s in socks if s["nome"] == "Hand.R")
    corpo_gd = f"""
\tvar m_r := cena.find_child("Socket_HandR", true, false) as Marker3D
\tvar m_l := cena.find_child("Socket_HandL", true, false) as Marker3D
\tif m_r == null or m_l == null:
\t\t_fail("Socket_HandR ou Socket_HandL ausente", cena); return
\tif m_l.transform.basis.is_equal_approx(m_r.transform.basis):
\t\t_fail("Socket_HandL reutiliza a mesma basis de Socket_HandR", cena); return
\tif m_r.position.distance_to(Vector3({hr[0]}, {hr[1]}, {hr[2]})) > 0.005:
\t\t_fail("Socket_HandR position divergente", cena); return
\tvar espada := MeshInstance3D.new(); espada.name = "Espada"
\tvar cb := PostImport.montar_character_body(cena, {{"Hand.R": espada}})
\tvar ba := espada.get_parent()
\twhile ba != null and not (ba is BoneAttachment3D): ba = ba.get_parent()
\tif ba == null:
\t\tcb.free(); _fail("anexo sem BoneAttachment3D"); return
\tvar rel_pos := (ba as Node3D).transform.affine_inverse() * espada.transform.origin if espada.get_parent() == ba else (m_r.position + espada.position)
\tif rel_pos.distance_to(m_r.position) > 0.005:
\t\tcb.free(); _fail("montar_character_body ignorou Socket_HandR position: %s vs %s" % [rel_pos, m_r.position]); return
\tcena = cb
"""
    _validar_cena_godot(godot, tmp_path / "f18_sockets.gd", corpo_gd, glb)


@pytest.mark.blender
def test_f19_blender_setor_uv2_aspecto_tangents_e_lod1_sem_imagens(tmp_path: Path) -> None:
    bruto_dir, saida_dir = tmp_path / "bruto", tmp_path / "saida"
    bruto_dir.mkdir()
    saida_dir.mkdir()
    src_glb = bruto_dir / "setor_src.glb"
    _criar_glb_multisurface(src_glb, escala=2.0)
    (bruto_dir / "bruto.json").write_text(json.dumps({"schema": "forge3d/bruto-arquivo@1", "arquivo": src_glb.name}), encoding="utf-8")
    Image.new("RGB", (32, 32), (128, 128, 255)).save(saida_dir / "setor.01_normal.png")
    job = {"bruto_dir": str(bruto_dir), "bruto_arquivo": "bruto.json", "saida_dir": str(saida_dir), "nome_base": "setor.01", "nome_arquivo": "setor.01.glb", "perfil": profiles.carregar("godot4"), "item": {"id": "setor.01", "tipo": "mapa_setor", "altura_metros": 2.0, "pivot": "base", "limite_triangulos": 500, "lod": [100, 50]}}
    job_path, uv_path = tmp_path / "job.json", tmp_path / "uv_bounds.json"
    job_path.write_text(json.dumps(job), encoding="utf-8")
    _rodar_blender_py(
        tmp_path,
        f"""import json, sys, bpy, bmesh
sys.path.insert(0, {str(RAIZ / "blender")!r})
import postprocess
with open(sys.argv[-2], encoding="utf-8") as f: postprocess.processar(json.load(f))
bpy.ops.wm.read_factory_settings(use_empty=True)
bm = bmesh.new(); bmesh.ops.create_cube(bm, size=1.0)
for v in bm.verts: v.co.x *= 8.0; v.co.z *= 0.2
me = bpy.data.meshes.new("Strip"); bm.to_mesh(me); bm.free()
o = bpy.data.objects.new("Strip", me); bpy.context.collection.objects.link(o); bpy.context.view_layer.objects.active = o
lay = o.data.uv_layers[postprocess.gerar_uv_lightmap(o)]
us, vs = [d.uv.x for d in lay.data], [d.uv.y for d in lay.data]
with open(sys.argv[-1], "w", encoding="utf-8") as f: json.dump({{"du": max(us) - min(us), "dv": max(vs) - min(vs)}}, f)
""",
        str(job_path), str(uv_path),
    )
    attrs0 = _ler_glb_json(saida_dir / "setor.01.glb")["meshes"][0]["primitives"][0]["attributes"]
    assert "TEXCOORD_1" in attrs0, "mapa_setor sem TEXCOORD_1 (UV2)"
    assert "TANGENT" in attrs0, "TANGENT ausente com _normal.png sidecar"
    assert not _ler_glb_json(saida_dir / "setor.01_LOD1.glb").get("images"), "_LOD1.glb duplicou imagens embutidas"
    uvb = json.loads(uv_path.read_text(encoding="utf-8"))
    assert min(uvb["du"], uvb["dv"]) < 0.75, f"gerar_uv_lightmap distorceu aspecto (scale_to_bounds=True): {uvb}"


def test_f19_godot_gi_mode_static_e_lod_proporcional_aabb(tmp_path: Path) -> None:
    godot = _exigir_godot()
    for tag, escala in (("peq", 0.4), ("gde", 20.0)):
        glb, lod1 = tmp_path / f"setor_{tag}.glb", tmp_path / f"setor_{tag}_LOD1.glb"
        _criar_glb_multisurface(glb, escala=escala)
        _criar_glb_multisurface(lod1, escala=escala)
        (tmp_path / f"setor_{tag}.manifest.json").write_text(json.dumps({"schema": "forge3d/manifest@6", "asset_id": f"setor_{tag}", "tipo": "mapa_setor", "perfil": "godot4", "lod": [{"arquivo": glb.name, "nivel": 0, "triangulos": 2}, {"arquivo": lod1.name, "nivel": 1, "triangulos": 2}]}), encoding="utf-8")
    script = tmp_path / "f19_gi_lod.gd"
    script.write_text(
        f"""extends SceneTree
const PostImport := preload({str(POST_IMPORT_GD)!r})
func _load_dist(p: String) -> Array:
\tvar doc := GLTFDocument.new(); var st := GLTFState.new(); doc.append_from_file(p, st)
\tvar c := doc.generate_scene(st); PostImport.aplicar(c, p)
\tvar mi := c.find_children("PropMulti", "MeshInstance3D", true, false)[0] as MeshInstance3D
\tvar res := [mi.gi_mode, mi.visibility_range_end]; c.free(); return res
func _initialize() -> void:
\tvar a := _load_dist({str(tmp_path / "setor_peq.glb")!r}); var b := _load_dist({str(tmp_path / "setor_gde.glb")!r})
\tprint("GI=", a[0], " D_PEQ=", a[1], " D_GDE=", b[1]); quit(0)
""",
        encoding="utf-8",
    )
    proc = _rodar_godot(godot, ["--script", str(script)])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    m = re.search(r"GI=(\d+)\s+D_PEQ=([0-9.]+)\s+D_GDE=([0-9.]+)", proc.stdout)
    assert m, proc.stdout
    assert int(m.group(1)) == 1, f"esperado GI_MODE_STATIC (1), obteve {m.group(1)}"
    d_peq, d_gde = float(m.group(2)), float(m.group(3))
    assert d_gde > d_peq and not math.isclose(d_gde, 25.0, abs_tol=0.1), (d_peq, d_gde)


def test_f20_ucx_agrupado_e_capsula_horizontal_quadrupede(tmp_path: Path) -> None:
    godot = _exigir_godot()
    ucx_glb = tmp_path / "prop_ucx.glb"
    pos_b = b"".join(struct.pack("<3f", *p) for p in [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)])
    idx_b = struct.pack("<12H", 0, 2, 1, 0, 1, 3, 0, 3, 2, 1, 2, 3)
    gltf = {
        "asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0, 1, 2, 3]}],
        "nodes": [{"name": "Caixa", "mesh": 0}, {"name": "UCX_Caixa_01", "mesh": 0}, {"name": "UCX_Caixa_02", "mesh": 0}, {"name": "UCX_Caixa_03", "mesh": 0}],
        "meshes": [{"name": "Caixa", "primitives": [{"attributes": {"POSITION": 0}, "indices": 1}]}],
        "accessors": [{"bufferView": 0, "componentType": 5126, "count": 4, "type": "VEC3", "min": [0, 0, 0], "max": [1, 1, 1]}, {"bufferView": 1, "componentType": 5123, "count": 12, "type": "SCALAR"}],
        "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(pos_b)}, {"buffer": 0, "byteOffset": len(pos_b), "byteLength": len(idx_b)}],
        "buffers": [{"byteLength": len(pos_b) + len(idx_b)}],
    }
    _escrever_glb(ucx_glb, gltf, pos_b + idx_b)
    script = tmp_path / "f20_ucx_quad.gd"
    script.write_text(
        f"""extends SceneTree
const PostImport := preload({str(POST_IMPORT_GD)!r})
func _initialize() -> void:
\tvar doc := GLTFDocument.new(); var st := GLTFState.new(); doc.append_from_file({str(ucx_glb)!r}, st)
\tvar c := doc.generate_scene(st); PostImport.aplicar(c, {str(ucx_glb)!r})
\tvar quad := Node3D.new()
\tquad.set_meta("forge3d_manifest", {{"tipo": "criatura_quadrupede", "rig": {{"esqueleto": "quadruped@1"}}}})
\tquad.set_meta("forge3d_geometry", {{"bbox_m": [0.8, 1.0, 2.4]}})
\tvar cb := PostImport.montar_character_body(quad)
\tvar cs := cb.find_children("*", "CollisionShape3D", true, false)[0] as CollisionShape3D
\tprint("SB=", c.find_children("*", "StaticBody3D", true, false).size(), " CS=", c.find_children("*", "CollisionShape3D", true, false).size(), " QROT=", absf(cs.rotation_degrees.x))
\tc.free(); cb.free(); quit(0)
""",
        encoding="utf-8",
    )
    proc = _rodar_godot(godot, ["--script", str(script)])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    m = re.search(r"SB=(\d+)\s+CS=(\d+)\s+QROT=([0-9.]+)", proc.stdout)
    assert m and int(m.group(1)) == 1 and int(m.group(2)) == 3, proc.stdout
    assert abs(float(m.group(3)) - 90.0) < 2.0, f"quadrupede sem capsula horizontal: {proc.stdout}"


@pytest.mark.blender
def test_f20_wing_roll_simetrico_e_tabela_loop_17_clipes(tmp_path: Path) -> None:
    faltantes = set(animacao.CLIPES_SUPORTADOS) - set(profiles.ANIMACOES_SUPORTADAS)
    assert not faltantes, f"profiles.ANIMACOES_SUPORTADAS faltando: {sorted(faltantes)}"

    out_wings = tmp_path / "wings_roll.json"
    _rodar_blender_py(
        tmp_path,
        f"""import json, sys, bpy
from mathutils import Vector
sys.path.insert(0, {str(RAIZ / "blender")!r})
import autorig
bpy.ops.wm.read_factory_settings(use_empty=True)
arm = bpy.data.armatures.new("WingRig"); rig = bpy.data.objects.new("WingRig", arm)
bpy.context.collection.objects.link(rig); bpy.context.view_layer.objects.active = rig
bpy.ops.object.mode_set(mode="EDIT"); eb = arm.edit_bones
def mk(n, h, t, p=None):
    b = eb.new(n); b.head = Vector(h); b.tail = Vector(t)
    if p: b.parent = p
    return b
root = mk("Root", (0, 0, 0), (0, 0, 0.5))
wl = mk("WingArm.L", (0.2, 0, 1.0), (1.0, 0, 1.0), root); mk("WingForearm.L", (1.0, 0, 1.0), (1.6, 0.1, 0.4), wl)
wr = mk("WingArm.R", (-0.2, 0, 1.0), (-1.0, 0, 1.0), root); mk("WingForearm.R", (-1.0, 0, 1.0), (-1.6, 0.1, 0.4), wr)
bpy.ops.object.mode_set(mode="OBJECT"); autorig._alinhar_roll_ossos(rig)
out = {{n: list(rig.data.bones[n].matrix_local.to_3x3().col[0]) for n in ("WingArm.L", "WingForearm.L")}}
with open(sys.argv[-1], "w", encoding="utf-8") as f: json.dump(out, f)
""",
        str(out_wings),
    )
    w = json.loads(out_wings.read_text(encoding="utf-8"))
    dot_l = sum(a * b for a, b in zip(w["WingArm.L"], w["WingForearm.L"]))
    assert abs(dot_l) > 0.98, f"WingArm.L/WingForearm.L nao alinhados ao plano da asa: {dot_l}"

    godot = _exigir_godot()
    script = tmp_path / "f20_anim_loops.gd"
    script.write_text(
        f"""extends SceneTree
const PostImport := preload({str(POST_IMPORT_GD)!r})
func _initialize() -> void:
\tvar raiz := Node3D.new(); var ap := AnimationPlayer.new(); var lib := AnimationLibrary.new()
\tfor clip in ["idle", "slash_combo", "cast", "bite"]:
\t\tvar a := Animation.new(); a.length = 1.0; a.loop_mode = Animation.LOOP_LINEAR; lib.add_animation(clip, a)
\tap.add_animation_library("", lib); raiz.add_child(ap); PostImport.aplicar(raiz, "")
\tfor clip in ["slash_combo", "cast", "bite"]: print(clip, "=", ap.get_animation(clip).loop_mode)
\traiz.free(); quit(0)
""",
        encoding="utf-8",
    )
    proc = _rodar_godot(godot, ["--script", str(script)])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    for clip in ("slash_combo", "cast", "bite"):
        assert f"{clip}=0" in proc.stdout, proc.stdout


def test_f21_godot_visual_qa_e_draw_calls_bench(tmp_path: Path) -> None:
    godot = _exigir_godot()
    qa_src = VISUAL_QA_GD.read_text(encoding="utf-8")
    assert "is StandardMaterial3D" not in qa_src and ("ORMMaterial3D" in qa_src or "BaseMaterial3D" in qa_src)

    asset_id = "prop.f21.bench"
    glb, lod1 = tmp_path / f"{asset_id}.glb", tmp_path / f"{asset_id}_LOD1.glb"
    _criar_glb_multisurface(glb)
    _criar_glb_multisurface(lod1)
    for suf, cor in (("baseColor", (200, 180, 160)), ("normal", (128, 128, 255)), ("orm", (255, 180, 40))):
        Image.new("RGB", (32, 32), cor).save(tmp_path / f"{asset_id}_{suf}.png")
    (tmp_path / f"{asset_id}.manifest.json").write_text(json.dumps({"schema": "forge3d/manifest@6", "asset_id": asset_id, "tipo": "prop_estatico", "perfil": "godot4", "lod": [{"arquivo": glb.name, "nivel": 0, "triangulos": 2}, {"arquivo": lod1.name, "nivel": 1, "triangulos": 2}]}), encoding="utf-8")
    qa_proc = _rodar_godot(godot, ["--script", str(VISUAL_QA_GD), "--", str(glb)])
    assert qa_proc.returncode == 0 and "GODOT_VISUAL_QA_OK" in qa_proc.stdout, qa_proc.stdout + qa_proc.stderr

    assert "PostImport.aplicar" in BENCH_GD.read_text(encoding="utf-8")
    in_j, out_j = tmp_path / "bench_in.json", tmp_path / "bench_out.json"
    in_j.write_text(json.dumps({"mode": "multimesh", "frames_baseline": 2, "frames_measure": 3, "items": [{"id": asset_id, "glb": str(glb), "qtd": 2}]}), encoding="utf-8")
    b_proc = subprocess.run([godot, "--headless", "--path", str(PROJ_GODOT), "--script", str(BENCH_GD), "--", "--input", str(in_j), "--output", str(out_j)], capture_output=True, text=True, timeout=60)
    assert b_proc.returncode == 0, b_proc.stdout + b_proc.stderr
    payload = json.loads(out_j.read_text(encoding="utf-8"))
    assert payload["ok"] is True and payload["items"][0]["placement_efetivo"] == "multimesh"
    assert payload["items"][0]["mesh_nodes_unit"] == 1
