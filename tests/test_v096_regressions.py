"""Testes comportamentais independentes de regressao v0.9.6 (Contratos 1 a 9)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from PIL import Image, ImageDraw

from forge3d import locks, post, profiles, qc, qc_geom
from forge3d.errors import ForgeError
from forge3d.providers import concept_prompt, concept_views, mesh_diag, mesh_trellis
from forge3d.providers.mesh import MeshProvider
from forge3d.qc_fidelidade import avaliar_fidelidade_concept_3d, _comparar_mascaras
from forge3d.qc_gates import _avaliar_g3

RAIZ = Path(__file__).resolve().parents[1]
_BLENDER_DIR = RAIZ / "blender"
if str(_BLENDER_DIR) not in sys.path:
    sys.path.insert(0, str(_BLENDER_DIR))


def _rodar_blender(codigo: str, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [post.binario(), "--background", "--factory-startup", "--python-expr", codigo],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


# 1. UV Unwrap Coverage (blender/postprocess_normals_uv.py)
def test_c1_uv_unwrap_coverage_subdivided_icosphere(tmp_path: Path) -> None:
    saida = tmp_path / "uv_res.json"
    codigo = f"""
import bpy, bmesh, json, sys, math
from pathlib import Path
sys.path.insert(0, {str(_BLENDER_DIR)!r})
import postprocess_normals_uv as pnu

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=3, radius=1.0)
obj = bpy.context.active_object
for v in obj.data.vertices:
    v.co.x += 0.15 * math.sin(v.co.y * 3.0)
    v.co.z += 0.12 * math.cos(v.co.x * 2.0)
obj.data.update()
pnu.desdobrar_uv(obj)

uv_layer = obj.data.uv_layers.active.data
obj.data.calc_loop_triangles()
tot_area, out_rng = 0.0, 0
for tri in obj.data.loop_triangles:
    u0, v0 = uv_layer[tri.loops[0]].uv
    u1, v1 = uv_layer[tri.loops[1]].uv
    u2, v2 = uv_layer[tri.loops[2]].uv
    for u, v in ((u0, v0), (u1, v1), (u2, v2)):
        if u < -1e-4 or u > 1.0001 or v < -1e-4 or v > 1.0001:
            out_rng += 1
    tot_area += 0.5 * abs((u1 - u0) * (v2 - v0) - (u2 - u0) * (v1 - v0))

bm = bmesh.new()
bm.from_mesh(obj.data)
uv_lay = bm.loops.layers.uv.active
adj = {{f.index: [] for f in bm.faces}}
for e in bm.edges:
    if len(e.link_faces) == 2:
        f1, f2 = e.link_faces
        v1, v2 = e.verts
        l1 = [l for l in f1.loops if l.vert in (v1, v2)]
        l2 = [l for l in f2.loops if l.vert in (v1, v2)]
        if len(l1) == 2 and len(l2) == 2:
            m1 = {{(l.vert): l[uv_lay].uv for l in l1}}
            m2 = {{(l.vert): l[uv_lay].uv for l in l2}}
            if (m1[v1] - m2[v1]).length < 1e-4 and (m1[v2] - m2[v2]).length < 1e-4:
                adj[f1.index].append(f2.index); adj[f2.index].append(f1.index)

vis, islands = set(), 0
for f_idx in adj:
    if f_idx not in vis:
        islands += 1
        q = [f_idx]; vis.add(f_idx)
        while q:
            c = q.pop()
            for nbr in adj[c]:
                if nbr not in vis:
                    vis.add(nbr); q.append(nbr)
bm.free()
Path({str(saida)!r}).write_text(json.dumps({{"faces": len(obj.data.polygons), "uv_area": tot_area, "out_of_range": out_rng, "islands": islands}}), encoding="utf-8")
"""
    proc = _rodar_blender(codigo)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    dados = json.loads(saida.read_text(encoding="utf-8"))
    assert dados["faces"] >= 320 and dados["uv_area"] >= 0.35
    assert dados["out_of_range"] == 0 and dados["islands"] < (dados["faces"] // 2)


# 2. Convex Collider at Roblox Stud Scale (postprocess_lod_col.py + qc_geom)
def test_c2_convex_collider_roblox_stud_scale(tmp_path: Path) -> None:
    glb_out = tmp_path / "boss_col.glb"
    codigo = f"""
import bpy, bmesh, sys, math
from pathlib import Path
sys.path.insert(0, {str(_BLENDER_DIR)!r})
import postprocess_lod_col as plc

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_torus_add(major_radius=6.0, minor_radius=2.0, major_segments=24, minor_segments=16)
obj = bpy.context.active_object
cos = [v.co for v in obj.data.vertices]
dx = max(c.x for c in cos) - min(c.x for c in cos)
dy = max(c.y for c in cos) - min(c.y for c in cos)
dz = max(c.z for c in cos) - min(c.z for c in cos)
diag = math.sqrt(dx * dx + dy * dy + dz * dz)
for v in obj.data.vertices:
    v.co *= (19.0 / diag)
obj.data.update()

cols = plc.criar_colisor(obj, "convex", "boss_test", 8)
bpy.ops.object.select_all(action="DESELECT")
cols[0].select_set(True)
bpy.context.view_layer.objects.active = cols[0]
bpy.ops.export_scene.gltf(filepath={str(glb_out)!r}, export_format="GLB", use_selection=True)
"""
    proc = _rodar_blender(codigo)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    gltf, b = qc.ler_glb_bin(glb_out)
    res = qc_geom.convexidade(gltf, b)
    assert res["convexo"] is True and res["concavas"] == 0


# 3. All-Pair Non-Adjacent R15 Split Separation (split_por_ossos.py + qc_roblox)
def test_c3_r15_split_non_adjacent_separation(tmp_path: Path) -> None:
    blender = post.binario()
    perfil = profiles.carregar("roblox-aa-80")
    escala = float(perfil["unidades"]["escala_saida"])

    in_glb = tmp_path / "rigged.glb"
    setup_py = tmp_path / "make_rigged.py"
    setup_py.write_text(
        f"""
import bpy, bmesh
bpy.ops.wm.read_factory_settings(use_empty=True)
arm_d = bpy.data.armatures.new("Arm")
arm = bpy.data.objects.new("Arm", arm_d)
bpy.context.scene.collection.objects.link(arm); bpy.context.view_layer.objects.active = arm

bpy.ops.object.mode_set(mode="EDIT")
b_root = arm_d.edit_bones.new("LowerTorso"); b_root.head = (0.0, 0.0, 1.0); b_root.tail = (0.0, 0.0, 1.5)
b_leg = arm_d.edit_bones.new("RightUpperLeg"); b_leg.head = (0.5, 0.0, 1.0); b_leg.tail = (0.5, 0.0, 0.5); b_leg.parent = b_root
b_hand = arm_d.edit_bones.new("RightHand"); b_hand.head = (0.5, 0.0, 0.6); b_hand.tail = (0.5, 0.0, 0.4); b_hand.parent = b_root
bpy.ops.object.mode_set(mode="OBJECT")

mesh_d = bpy.data.meshes.new("Mesh"); bm = bmesh.new()
bmesh.ops.create_cube(bm, size=0.4)
for v in bm.verts: v.co.x += 0.5; v.co.z = v.co.z * 0.8 + 0.8
bm_h = bmesh.new(); bmesh.ops.create_cube(bm_h, size=0.3)
for v in bm_h.verts: bm.verts.new((v.co.x + 0.5, v.co.y, v.co.z * 0.5 + 0.55))
bm_h.free(); bm.verts.ensure_lookup_table()
bmesh.ops.subdivide_edges(bm, edges=list(bm.edges), cuts=2, use_grid_fill=True)
bm.to_mesh(mesh_d); bm.free()

obj = bpy.data.objects.new("Body", mesh_d); bpy.context.scene.collection.objects.link(obj)
vg_root, vg_leg, vg_hand = obj.vertex_groups.new(name="LowerTorso"), obj.vertex_groups.new(name="RightUpperLeg"), obj.vertex_groups.new(name="RightHand")
for v in mesh_d.vertices: (vg_leg if v.co.z >= 0.7 else vg_hand).add([v.index], 1.0, "REPLACE")
obj.parent = arm; mod = obj.modifiers.new("Arm", "ARMATURE"); mod.object = arm
bpy.ops.export_scene.gltf(filepath={str(in_glb)!r}, export_format="GLB", export_yup=True)
""",
        encoding="utf-8",
    )
    p_prep = subprocess.run([blender, "--background", "--factory-startup", "--python", str(setup_py)], capture_output=True, text=True, timeout=60)
    assert p_prep.returncode == 0, p_prep.stderr

    out_dir, job, resumo_path = tmp_path / "split_out", tmp_path / "job.json", tmp_path / "resumo.json"
    partes = [{"nome": "RightUpperLeg", "junta": "RightHip"}, {"nome": "RightHand", "junta": "RightWrist"}]
    job.write_text(json.dumps({"glb": str(in_glb), "saida": str(out_dir), "partes": partes}), encoding="utf-8")

    p_split = subprocess.run(
        [blender, "--background", "--factory-startup", "--python", str(_BLENDER_DIR / "split_por_ossos.py"), "--", str(job), str(resumo_path)],
        capture_output=True, text=True, timeout=60,
    )
    assert p_split.returncode == 0, p_split.stderr + p_split.stdout
    resumo = json.loads(resumo_path.read_text(encoding="utf-8"))

    g12 = qc.verificar_g12_separacao({"partes": resumo["partes"], "rig": {"modo": "motor6d"}}, out_dir, resumo, escala)
    assert g12["status"] == "ok" and g12["medido"]["disjuntas"] is True and g12["medido"]["penetracao_max_mm"] <= 2.0

    g13 = qc.verificar_g13_ancoras({"partes": resumo["partes"], "rig": {"modo": "motor6d"}}, resumo, escala)
    assert g13["status"] == "ok" and g13["medido"]["erro_ancora_max_mm"] <= 1.0

    for parte in resumo["partes"]:
        g_p, b_p = qc.ler_glb_bin(out_dir / parte["arquivo"])
        assert qc.topologia(g_p, b_p)["bordas_abertas"] == 0


# 4. 4-View Prompt Sanitization & Turnaround Guard
def test_c4_prompt_sanitization_and_turnaround_guard(tmp_path: Path) -> None:
    prompt_base = "armored boss, full body front view"
    for v in ("back", "left", "right"):
        p_v = concept_prompt.prompt_para_vista(prompt_base, v)
        assert "front view" not in p_v.lower()
        assert ("single isolated character only" in p_v) or ("strictly one figure" in p_v.lower())

    def _figuras(p: Path, n: int) -> None:
        p.parent.mkdir(parents=True, exist_ok=True)
        im = Image.new("RGBA", (128, 128), (255, 255, 255, 255))
        d = ImageDraw.Draw(im)
        if n == 2:
            d.rectangle([20, 20, 45, 100], fill=(20, 20, 20, 255))
            d.rectangle([80, 20, 105, 100], fill=(20, 20, 20, 255))
        else:
            d.rectangle([45, 20, 85, 100], fill=(20, 20, 20, 255))
        im.save(p)

    class MockAI_Retry:
        def __init__(self) -> None: self.back_calls = 0
        def modelo_gemini_escolhido(self) -> str: return "gemini-nano-banana-2.1"
        def gerar_conceito_gemini(self, prompt: str, neg: str, seed: int, png: Path, **kw: Any) -> dict[str, Any]:
            if "back" in png.name:
                self.back_calls += 1
                _figuras(png, 2 if self.back_calls == 1 else 1)
            else:
                _figuras(png, 1)
            return {"tempo_s": 0.05, "seed": seed, "origem": "gemini"}

    res_retry = concept_views.gerar_conceito_cloud(
        {"prompt": "boss", "vistas": 4},
        tmp_path / "c4_retry",
        prov_conceito="gemini",
        versao="0.9.6",
        cloud_ai_mod=MockAI_Retry(),
        normalizar_fn=concept_views._normalizar_png_real,
    )
    assert "back" in res_retry["meta"]["vistas"]
    assert res_retry["meta"]["vistas_detalhes"]["back"]["retentativa_multiplas_figuras"] is True
    assert not concept_views._detectar_multiplas_figuras(Path(res_retry["meta"]["vistas"]["back"]))

    class MockAI_DoubleFail:
        def modelo_gemini_escolhido(self) -> str: return "gemini-nano-banana-2.1"
        def gerar_conceito_gemini(self, prompt: str, neg: str, seed: int, png: Path, **kw: Any) -> dict[str, Any]:
            _figuras(png, 2 if "back" in png.name else 1)
            return {"tempo_s": 0.05, "seed": seed, "origem": "gemini"}

    res_df = concept_views.gerar_conceito_cloud(
        {"prompt": "boss", "vistas": 4},
        tmp_path / "c4_df",
        prov_conceito="gemini",
        versao="0.9.6",
        cloud_ai_mod=MockAI_DoubleFail(),
        normalizar_fn=concept_views._normalizar_png_real,
    )
    v_df, det_back = res_df["meta"]["vistas"], res_df["meta"]["vistas_detalhes"]["back"]
    if "back" in v_df:
        assert det_back.get("auto_crop") == "right_half"
        assert not concept_views._detectar_multiplas_figuras(Path(v_df["back"]))
    else:
        assert det_back.get("omitida") == "multiplas_figuras"


# 5. Local TRELLIS.2 Subprocess Roundtrip + D18 License Gate
def test_c5_local_trellis2_subprocess_and_d18_license(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.test_red_r2_roblox import _box_glb

    t2_dir = tmp_path / "trellis2"
    (t2_dir / "venv" / "bin").mkdir(parents=True)
    py_shim = t2_dir / "venv" / "bin" / "python"
    py_shim.write_text(f"#!/bin/sh\nexec {sys.executable!r} \"$@\"\n", encoding="utf-8")
    py_shim.chmod(0o755)
    (t2_dir / "repo" / "trellis2_gguf").mkdir(parents=True)
    (t2_dir / "cuda128" / "lib").mkdir(parents=True)
    models = t2_dir / "models"
    for rel in (
        "Trellis2/pipeline.json",
        "Trellis2/decoders/Stage1/ss_dec_conv3d_16l8_fp16.safetensors",
        "Trellis2/decoders/Stage2/shape_dec_next_dc_f16c32_fp16.safetensors",
        "Trellis2/decoders/Stage2/tex_dec_next_dc_f16c32_fp16.safetensors",
        "Trellis2/refiner/ss_flow_img_dit_1_3B_64_bf16.safetensors",
        "Trellis2/shape/slat_flow_img2shape_dit_1_3B_512_bf16.safetensors",
        "Trellis2/texture/slat_flow_imgshape2tex_dit_1_3B_512_bf16.safetensors",
    ):
        p = models / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x", encoding="utf-8")
    (models / "facebook" / "dinov3-vitl16-pretrain-lvd1689m").mkdir(parents=True)

    glb_bytes = _box_glb()
    stub_infer = tmp_path / "stub_trellis2_infer.py"
    stub_infer.write_text(
        "import argparse, json\nfrom pathlib import Path\n"
        "p = argparse.ArgumentParser()\np.add_argument('--saida-dir', required=True)\np.add_argument('--resultado', required=True)\n"
        "args, _ = p.parse_known_args()\nout = Path(args.saida_dir)\nout.mkdir(parents=True, exist_ok=True)\n"
        f"(out / 'modelo.glb').write_bytes({glb_bytes!r})\n"
        "Path(args.resultado).write_text(json.dumps({'ok': True, 'arquivo': 'modelo.glb', 'faces': 12}), encoding='utf-8')\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("FORGE3D_MODELO_MESH", "trellis2")
    monkeypatch.setenv("FORGE3D_TRELLIS2_DIR", str(t2_dir))
    monkeypatch.setenv("FORGE3D_TRELLIS2_SCRIPT", str(stub_infer))
    monkeypatch.setenv("FORGE3D_I23D_DEVICE", "cuda:0")
    monkeypatch.setattr(locks, "vram_livre_mb", lambda: 5600)
    monkeypatch.setattr(mesh_trellis, "diagnostico_trellis2", lambda: {"ok": True, "torch": "2.9.1+cu128", "cuda": True})

    img_in = tmp_path / "input.png"
    im = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    ImageDraw.Draw(im).rectangle([16, 16, 48, 48], fill=(120, 120, 120, 255))
    im.save(img_in)

    mp = MeshProvider()
    ok_pre, msg_pre = mp.preflight()
    assert ok_pre is True and "TRELLIS.2 local" in msg_pre

    out_ok = tmp_path / "out_ok"
    mp.gerar({"id": "trellis_test", "origem": str(img_in)}, {}, out_ok)
    assert (out_ok / "modelo.glb").is_file() and (out_ok / "modelo.glb").stat().st_size > 0
    res = json.loads((out_ok / "i23d_resultado.json").read_text(encoding="utf-8"))
    assert res["provedor"] == "trellis2_local" and res["licenca"]["uso_comercial"] is True

    monkeypatch.setenv("FORGE3D_I23D_TRELLIS_MODEL", "forbidden/non-mit-model")
    with pytest.raises(ForgeError) as exc_info:
        mesh_trellis.validar_modelo_trellis_licenca()
    assert exc_info.value.codigo == "FORGE-E-LICENCA"


# 6. QC G3 Low-UV-Area Rejection (forge3d.qc)
def test_c6_qc_g3_low_uv_area_rejection(tmp_path: Path) -> None:
    perfil = profiles.carregar("roblox-aa-80")
    glb_h, glb_t = tmp_path / "healthy.glb", tmp_path / "tiny.glb"
    codigo = f"""
import bpy, bmesh
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=3, radius=1.0)
obj = bpy.context.active_object
mat = bpy.data.materials.new("Mat"); mat.use_nodes = True
img = bpy.data.images.new("Tex", 64, 64); img.pixels[:] = [0.5, 0.5, 0.5, 1.0] * (64 * 64)
tex = mat.node_tree.nodes.new("ShaderNodeTexImage"); tex.image = img
bsdf = mat.node_tree.nodes["Principled BSDF"]
mat.node_tree.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
obj.data.materials.append(mat)

bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.select_all(action="SELECT")
bpy.ops.uv.smart_project(angle_limit=1.15, island_margin=0.004)
bpy.ops.uv.pack_islands(margin=0.004)
bpy.ops.object.mode_set(mode="OBJECT")
bpy.ops.export_scene.gltf(filepath={str(glb_h)!r}, export_format="GLB")

for d in obj.data.uv_layers.active.data:
    d.uv = (d.uv.x * 0.05 + 0.1, d.uv.y * 0.05 + 0.1)
bpy.ops.export_scene.gltf(filepath={str(glb_t)!r}, export_format="GLB")
"""
    proc = _rodar_blender(codigo)
    assert proc.returncode == 0, proc.stderr + proc.stdout

    gh, bh = qc.ler_glb_bin(glb_h)
    gt, bt = qc.ler_glb_bin(glb_t)
    item = {"id": "g3_test"}

    res_h = _avaliar_g3(gh, bh, item, perfil, qc.analisar(gh, bh))
    assert res_h["status"] == "ok" and res_h["medido"]["uv_area_total"] >= 0.45 and res_h["medido"]["uv_baixa_cobertura"] == 0

    res_t = _avaliar_g3(gt, bt, item, perfil, qc.analisar(gt, bt))
    assert res_t["status"] == "falhou" and res_t["medido"]["uv_baixa_cobertura"] == 1


# 7. QC G15 Tightened Thresholds (forge3d.qc_fidelidade / qc.verificar)
def test_c7_qc_g15_tightened_thresholds(tmp_path: Path) -> None:
    p_c, p_skinny, p_match = tmp_path / "c.png", tmp_path / "s.png", tmp_path / "m.png"

    # Concept: wide 82x100 (aspect ~ 0.82)
    im_c = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    ImageDraw.Draw(im_c).rectangle([59, 50, 141, 150], fill=(255, 0, 0, 255))
    im_c.save(p_c)

    # Skinny mesh: narrow silhouette (aspect ~ 0.42 / low IoU)
    im_s = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    d_s = ImageDraw.Draw(im_s)
    d_s.rectangle([79, 50, 121, 150], fill=(0, 255, 0, 255))
    d_s.rectangle([95, 20, 105, 180], fill=(0, 255, 0, 255))
    im_s.save(p_skinny)

    # Matching wide mesh: wide 75x100 (aspect ~ 0.75 >= 0.70, IoU >= 0.65)
    im_m = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    ImageDraw.Draw(im_m).rectangle([62, 50, 137, 150], fill=(0, 0, 255, 255))
    im_m.save(p_match)

    res_s = avaliar_fidelidade_concept_3d(p_c, p_skinny)
    res_m = avaliar_fidelidade_concept_3d(p_c, p_match)
    assert res_s["aprovado"] is False and res_m["aprovado"] is True

    # Direct mask comparison assertion
    m_c = {"mask": [1] * 48 + [0] * 52, "aspect_ratio": 0.82}
    assert _comparar_mascaras(m_c, {"mask": [1] * 48 + [1] * 52, "aspect_ratio": 0.42})["aprovado"] is False
    assert _comparar_mascaras(m_c, {"mask": [1] * 48 + [0] * 52, "aspect_ratio": 0.75})["aprovado"] is True


# 8. Humanoid Template Routing (mesh_diag._usar_template_humanoide)
def test_c8_humanoid_template_routing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mesh_diag, "mpfb2_cc0_disponivel", lambda: (True, "disponivel"))
    assert mesh_diag._usar_template_humanoide({"tipo": "personagem_humanoide", "rota": "i23d"}) is False
    assert mesh_diag._usar_template_humanoide({"tipo": "personagem_humanoide", "vistas": 4}) is False
    assert mesh_diag._usar_template_humanoide({"tipo": "personagem_humanoide", "vistas": "4"}) is False
    assert mesh_diag._usar_template_humanoide({"tipo": "personagem_humanoide"}) is True


# 9. VRAM Guard (mesh_diag.VRAM_MINIMA_MB + MeshProvider.preflight for TripoSR & TRELLIS.2)
def test_c9_vram_guard_triposr_and_trellis2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from forge3d.providers import mesh as mesh_mod

    assert mesh_diag.VRAM_MINIMA_MB >= 4200

    monkeypatch.setattr(locks, "vram_livre_mb", lambda: 3600)
    monkeypatch.setattr(mesh_mod, "_vram_livre_mb", lambda: 3600)
    monkeypatch.setattr(mesh_mod, "_device", lambda: "cuda:0")
    monkeypatch.setattr(mesh_mod, "_diagnostico", lambda: {"ok": True, "torch": "2.4.1", "cuda": True})

    monkeypatch.setenv("FORGE3D_MODELO_MESH", "triposr")
    mp = MeshProvider()
    ok_tripo, msg_tripo = mp.preflight()
    assert ok_tripo is False
    assert "3600 MiB" in msg_tripo and f"{mesh_diag.VRAM_MINIMA_MB} MiB" in msg_tripo

    t2_dir = tmp_path / "t2_vram"
    m = t2_dir / "models"
    for rel in (
        "Trellis2/pipeline.json",
        "Trellis2/decoders/Stage1/ss_dec_conv3d_16l8_fp16.safetensors",
        "Trellis2/decoders/Stage2/shape_dec_next_dc_f16c32_fp16.safetensors",
        "Trellis2/decoders/Stage2/tex_dec_next_dc_f16c32_fp16.safetensors",
        "Trellis2/refiner/ss_flow_img_dit_1_3B_64_bf16.safetensors",
        "Trellis2/shape/slat_flow_img2shape_dit_1_3B_512_bf16.safetensors",
        "Trellis2/texture/slat_flow_imgshape2tex_dit_1_3B_512_bf16.safetensors",
    ):
        p = m / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x", encoding="utf-8")
    (m / "facebook" / "dinov3-vitl16-pretrain-lvd1689m").mkdir(parents=True)
    monkeypatch.setenv("FORGE3D_TRELLIS2_DIR", str(t2_dir))
    monkeypatch.setattr(mesh_trellis, "diagnostico_trellis2", lambda: {"ok": True, "torch": "2.9.1+cu128", "cuda": True})
    monkeypatch.setenv("FORGE3D_MODELO_MESH", "trellis2")

    ok_t2, msg_t2 = mp.preflight()
    assert ok_t2 is False
    assert "3600 MiB" in msg_t2 and f"{mesh_diag.VRAM_MINIMA_MB} MiB" in msg_t2

    monkeypatch.setattr(mesh_mod, "_device", lambda: "cpu")
    ok_cpu, msg_cpu = mp.preflight()
    assert ok_cpu is False and "CUDA" in msg_cpu
