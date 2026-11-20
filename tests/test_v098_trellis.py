"""Testes independentes da v0.9.8 (Onda 1 TRELLIS.2): BUG-T1..BUG-T5."""

from __future__ import annotations

import base64
import io
import json
import subprocess
import sys
import threading
import types
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from forge3d import doctor, post
from forge3d.errors import ForgeError
from forge3d.providers import cloud_ai, concept, concept_prompt, mesh, mesh_i23d, mesh_trellis
from forge3d.qc_glb import ler_glb_bin
from forge3d.qc_uv import _uv_status

RAIZ = Path(__file__).resolve().parents[1]
BLENDER_DIR, TOOLS_DIR = RAIZ / "blender", RAIZ / "tools"
for _p in (str(BLENDER_DIR), str(TOOLS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import bake_pbr_config  # noqa: E402
import colab_trellis_server  # noqa: E402
import colab_trellis_worker  # noqa: E402


def _rodar_blender_py(codigo: str, timeout: int = 180) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [post.binario(), "--background", "--factory-startup", "--python-expr", codigo],
        capture_output=True, text=True, timeout=timeout,
    )


def _png_b64(cor: tuple[int, int, int, int] = (200, 90, 40, 255)) -> str:
    buf = io.BytesIO()
    Image.new("RGBA", (16, 16), cor).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def test_bug_t1_preparar_high_mesh_pula_acima_60k_com_e_sem_color_attributes(monkeypatch):
    def _obj(ca: Any) -> Any:
        return types.SimpleNamespace(data=types.SimpleNamespace(color_attributes=ca), modifiers=[])

    monkeypatch.setattr(bake_pbr_config, "_contar_triangulos", lambda _o: 60_001)
    for ca in (["Col"], [], None):
        res = bake_pbr_config.preparar_high_mesh_detalhe_alto(_obj(ca), {"ativo": True})
        assert res == {"aplicado": False, "motivo": "malha_i23d_ja_densa", "tris_high_inicial": 60_001}
    assert bake_pbr_config.preparar_high_mesh_detalhe_alto(_obj([]), None) == {"aplicado": False}
    assert bake_pbr_config.preparar_high_mesh_detalhe_alto(_obj([]), {"ativo": False}) == {"aplicado": False}
    assert bake_pbr_config.preparar_high_mesh_detalhe_alto(None, {"ativo": True}) == {"aplicado": False}


@pytest.mark.blender
def test_bug_t1_blender_high_mesh_abaixo_e_acima_60k():
    codigo = f"""
import json, sys
sys.path.insert(0, {str(BLENDER_DIR)!r})
import bpy, postprocess, bake_pbr_config
postprocess.limpar_cena()
bpy.ops.mesh.primitive_cube_add(size=1.0)
cubo = bpy.context.active_object
res_b = bake_pbr_config.preparar_high_mesh_detalhe_alto(cubo, {{"ativo": True, "subdiv_niveis": 1, "chanfro_bevel_m": 0.005}})
bpy.ops.mesh.primitive_uv_sphere_add(segments=200, ring_count=160, radius=1.0)
densa = bpy.context.active_object
res_d = bake_pbr_config.preparar_high_mesh_detalhe_alto(densa, {{"ativo": True, "subdiv_niveis": 2, "chanfro_bevel_m": 0.008}})
print("OUT_T1:" + json.dumps({{"baixo": res_b, "densa": res_d}}))
"""
    proc = _rodar_blender_py(codigo, timeout=120)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    dados = json.loads(next(ln for ln in proc.stdout.splitlines() if ln.startswith("OUT_T1:"))[7:])
    assert dados["baixo"]["aplicado"] is True
    assert dados["baixo"]["tris_high_enriquecido"] > dados["baixo"]["tris_high_inicial"]
    assert dados["densa"]["aplicado"] is False and dados["densa"]["motivo"] == "malha_i23d_ja_densa"
    assert dados["densa"]["tris_high_inicial"] > 60_000


@pytest.mark.blender
def test_bug_t2_decimar_humanoide_denso_nao_manifold_preserva_altura_pernas():
    codigo = f"""
import json, sys
sys.path.insert(0, {str(BLENDER_DIR)!r})
import bpy, bmesh
from mathutils import Vector
import postprocess, postprocess_repair

postprocess.limpar_cena()
partes = []
bpy.ops.mesh.primitive_uv_sphere_add(segments=120, ring_count=100, radius=0.14, location=(0.0, 0.0, 0.86))
partes.append(bpy.context.active_object)
bpy.ops.mesh.primitive_cylinder_add(vertices=110, radius=0.15, depth=0.36, location=(0.0, 0.0, 0.62))
partes.append(bpy.context.active_object)
for sx in (-1.0, 1.0):
    bpy.ops.mesh.primitive_cylinder_add(vertices=70, radius=0.055, depth=0.34, location=(sx * 0.24, 0.0, 0.64), rotation=(0.0, sx * 0.78, 0.0))
    partes.append(bpy.context.active_object)
for sx in (-0.09, 0.09):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=100, ring_count=65, radius=0.075, location=(sx, 0.0, 0.23))
    perna = bpy.context.active_object
    perna.scale = (1.0, 1.0, 0.23 / 0.075)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    partes.append(perna)
bpy.ops.object.select_all(action="DESELECT")
for p in partes: p.select_set(True)
bpy.context.view_layer.objects.active = partes[0]
bpy.ops.object.join()
obj = bpy.context.active_object

bm = bmesh.new()
bm.from_mesh(obj.data)
bmesh.ops.triangulate(bm, faces=list(bm.faces))
zs = [v.co.z for v in bm.verts]
z_min0, h0 = min(zs), max(zs) - min(zs)
for v in bm.verts: v.co.z = (v.co.z - z_min0) / h0
bm.edges.ensure_lookup_table()
for e in [ed for ed in bm.edges if len(ed.link_faces) == 2][:35]:
    v0, v1 = e.verts[0], e.verts[1]
    vm = bm.verts.new(((v0.co + v1.co) * 0.5) + Vector((0.0, 0.003, 0.0)))
    try: bm.faces.new((v0, v1, vm))
    except ValueError: pass
bm.to_mesh(obj.data)
bm.free()
obj.data.update()

tris_a = postprocess.malha_triangulada(obj)
nm_a = postprocess_repair._contar_nao_manifold(obj, weld_dist=1e-6)
zs_a = [v.co.z for v in obj.data.vertices]
h_a = max(zs_a) - min(zs_a)
tris_d = postprocess_repair.decimar(obj, 8000, proteger_cabeca_maos=True)
nm_d = postprocess_repair._contar_nao_manifold(obj)
zs_d = [v.co.z for v in obj.data.vertices]
print("OUT_T2:" + json.dumps({{"tris_a": tris_a, "nm_a": list(nm_a), "h_a": h_a, "tris_d": tris_d, "nm_d": list(nm_d), "h_d": max(zs_d) - min(zs_d)}}))
"""
    proc = _rodar_blender_py(codigo, timeout=180)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    res = json.loads(next(ln for ln in proc.stdout.splitlines() if ln.startswith("OUT_T2:"))[7:])
    assert res["tris_a"] > 45_000 and res["nm_a"][0] >= 20
    assert res["tris_d"] <= 8000 and res["nm_d"] == [0, 0]
    assert res["h_d"] >= 0.96 * res["h_a"]


def test_bug_t2_calcular_decimation_target_e_payload_remoto(monkeypatch, tmp_path):
    monkeypatch.delenv("FORGE3D_I23D_DECIMATION_TARGET", raising=False)
    assert mesh_trellis.calcular_decimation_target({"limite_triangulos": 16000}) == 64_000
    assert mesh_trellis.calcular_decimation_target({"limite_triangulos": 2000}) == 48_000
    assert mesh_trellis.calcular_decimation_target({"limite_triangulos": 40000}) == 100_000

    monkeypatch.setenv("FORGE3D_I23D_DECIMATION_TARGET", "2000")
    assert mesh_trellis.calcular_decimation_target({"limite_triangulos": 16000}) == 8_000
    monkeypatch.setenv("FORGE3D_I23D_DECIMATION_TARGET", "999999")
    assert mesh_trellis.calcular_decimation_target({"limite_triangulos": 16000}) == 300_000
    for inv in ("0", "-50"):
        monkeypatch.setenv("FORGE3D_I23D_DECIMATION_TARGET", inv)
        with pytest.raises(ValueError, match="FORGE3D_I23D_DECIMATION_TARGET"):
            mesh_trellis.calcular_decimation_target({"limite_triangulos": 16000})

    monkeypatch.delenv("FORGE3D_I23D_DECIMATION_TARGET", raising=False)
    monkeypatch.setenv("FORGE3D_I23D_ENDPOINT", "http://127.0.0.1:8765")
    img_path = tmp_path / "front.png"
    Image.new("RGBA", (16, 16), (255, 0, 0, 255)).save(img_path)
    capturado: dict[str, Any] = {}

    class _FakeResp:
        headers = {"Content-Type": "application/json"}
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self) -> bytes:
            b64 = base64.b64encode(b"glTF\x02\x00\x00\x00").decode("ascii")
            return json.dumps({"ok": True, "glb_base64": b64, "faces": 12000}).encode("utf-8")

    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=60: (capturado.update(json.loads(req.data.decode())) or _FakeResp()))
    res = mesh_trellis.executar_i23d_remoto(
        {"id": "mob.01", "limite_triangulos": 16000, "qualidade": "ultra"},
        tmp_path / "out", img_path, None, {},
    )
    assert res["ok"] is True
    assert capturado["decimation_target"] == 64_000 and capturado["texture_size"] == 2048


def test_bug_t2_e_t4_colab_trellis_server_decimation_target_e_multivista():
    assert colab_trellis_server._validar_decimation_target(None) is None
    assert colab_trellis_server._validar_decimation_target(2_000) == 8_000
    assert colab_trellis_server._validar_decimation_target(500_000) == 300_000
    assert colab_trellis_server._validar_decimation_target(64_000) == 64_000
    assert colab_trellis_server._validar_texture_size(999_999) == 4096
    assert colab_trellis_server._validar_simplify(0.95) == 0.95
    with pytest.raises(ValueError):
        colab_trellis_server._validar_texture_size(-1)
    with pytest.raises(ValueError):
        colab_trellis_server._validar_simplify(1.5)

    chamadas: list[dict[str, Any]] = []

    class _FakeGlb:
        faces = [1, 2, 3, 4]
        def export(self, caminho: str) -> None: Path(caminho).write_bytes(b"glTF\x02\x00\x00\x00")

    class _PipeSingleOnly:
        def run(self, img: Any, seed: int = 1) -> Any:
            chamadas.append({"modo": "single", "eh_pil": isinstance(img, Image.Image), "seed": seed})
            return _FakeGlb()

    class _PipeMulti:
        def run(self, img: Any, seed: int = 1) -> Any: raise AssertionError("esperado run_multi_image")
        def run_multi_image(self, imgs: list[Any], seed: int = 1) -> Any:
            chamadas.append({"modo": "multi", "qtd": len(imgs), "seed": seed})
            return _FakeGlb()

    b64 = _png_b64()
    vistas4 = {"front": b64, "back": b64, "left": b64, "right": b64}
    srv1 = colab_trellis_server.criar_servidor("127.0.0.1", 0, pipeline=_PipeSingleOnly())
    threading.Thread(target=srv1.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{srv1.server_port}/generate"
        for inv in (0, -10, "abc", True):
            req = urllib.request.Request(url, data=json.dumps({"images": vistas4, "decimation_target": inv}).encode(), headers={"Content-Type": "application/json"}, method="POST")
            with pytest.raises(urllib.error.HTTPError) as exc:
                urllib.request.urlopen(req, timeout=10)
            assert exc.value.code == 400
        req_ok = urllib.request.Request(url, data=json.dumps({"images": vistas4, "decimation_target": 72000}).encode(), headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req_ok, timeout=10) as resp:
            assert json.loads(resp.read().decode())["ok"] is True
        assert chamadas[-1] == {"modo": "single", "eh_pil": True, "seed": 1}
    finally:
        srv1.shutdown()
        srv1.server_close()

    srv2 = colab_trellis_server.criar_servidor("127.0.0.1", 0, pipeline=_PipeMulti())
    threading.Thread(target=srv2.serve_forever, daemon=True).start()
    try:
        url_m = f"http://127.0.0.1:{srv2.server_port}/generate"
        req_m = urllib.request.Request(url_m, data=json.dumps({"images": vistas4, "seed": 7}).encode(), headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req_m, timeout=10) as resp:
            assert json.loads(resp.read().decode())["ok"] is True
        assert chamadas[-1] == {"modo": "multi", "qtd": 4, "seed": 7}
    finally:
        srv2.shutdown()
        srv2.server_close()


@pytest.mark.blender
def test_bug_t3_bake_pbr_nativo_preserva_albedo_metalico_e_anti_regressao(tmp_path):
    saida_nat, saida_vc, saida_err = tmp_path / "nat", tmp_path / "vc", tmp_path / "err"
    codigo = f"""
import json, sys
sys.path.insert(0, {str(BLENDER_DIR)!r})
import bpy, postprocess, bake_pbr

postprocess.limpar_cena()
bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=24, radius=0.8)
obj_nat = bpy.context.active_object
img_albedo = bpy.data.images.new("AlbedoNativo", width=64, height=64, alpha=False)
img_albedo.colorspace_settings.name = "sRGB"
img_albedo.pixels = [0.85, 0.12, 0.12, 1.0] * (64 * 64)
img_mr = bpy.data.images.new("MRNativo", width=64, height=64, alpha=False)
img_mr.colorspace_settings.name = "Non-Color"
img_mr.pixels = [1.0, 0.25, 0.90, 1.0] * (64 * 64)

mat = bpy.data.materials.new("MatNativoTrellis")
mat.use_nodes = True
nt = mat.node_tree
bsdf = nt.nodes.get("Principled BSDF")
tex_c = nt.nodes.new("ShaderNodeTexImage")
tex_c.image = img_albedo
nt.links.new(tex_c.outputs["Color"], bsdf.inputs["Base Color"])
tex_mr = nt.nodes.new("ShaderNodeTexImage")
tex_mr.image = img_mr
sep = nt.nodes.new("ShaderNodeSeparateColor")
sep.mode = "RGB"
nt.links.new(tex_mr.outputs["Color"], sep.inputs["Color"])
nt.links.new(sep.outputs["Blue"], bsdf.inputs["Metallic"])
nt.links.new(sep.outputs["Green"], bsdf.inputs["Roughness"])
obj_nat.data.materials.append(mat)

assert bake_pbr.objeto_tem_pbr_nativo(obj_nat) is True
res_nat = bake_pbr.executar_bake_high_low(
    obj_nat, {str(saida_nat)!r}, "trellis_nat", 128, 600,
    postprocess.reparar_malha, postprocess.decimar, postprocess.suavizar_por_angulo, postprocess.desdobrar_uv,
)

postprocess.limpar_cena()
bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=24, radius=0.8)
obj_vc = bpy.context.active_object
ca = obj_vc.data.color_attributes.new(name="Col", type="BYTE_COLOR", domain="POINT")
for d in ca.data: d.color = (0.2, 0.7, 0.35, 1.0)
assert bake_pbr.objeto_tem_pbr_nativo(obj_vc) is False
res_vc = bake_pbr.executar_bake_high_low(
    obj_vc, {str(saida_vc)!r}, "triposr_vc", 128, 600,
    postprocess.reparar_malha, postprocess.decimar, postprocess.suavizar_por_angulo, postprocess.desdobrar_uv,
)

postprocess.limpar_cena()
bpy.ops.mesh.primitive_cube_add(size=1.0)
obj_err = bpy.context.active_object
erro_levantado = False
try:
    bake_pbr.executar_bake_high_low(
        obj_err, {str(saida_err)!r}, "sem_cor", 64, 100,
        postprocess.reparar_malha, postprocess.decimar, postprocess.suavizar_por_angulo, postprocess.desdobrar_uv,
    )
except RuntimeError: erro_levantado = True
print("OUT_T3:" + json.dumps({{"nat_bake": res_nat["bake"], "vc_bake": res_vc["bake"], "erro_levantado": erro_levantado}}))
"""
    proc = _rodar_blender_py(codigo, timeout=180)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = json.loads(next(ln for ln in proc.stdout.splitlines() if ln.startswith("OUT_T3:"))[7:])
    assert out["nat_bake"]["pbr_nativo_preservado"] is True
    assert out["nat_bake"]["metallic_hint_aplicado"] is True and out["nat_bake"]["roughness_hint_aplicado"] is True

    px_bc = list(Image.open(saida_nat / "trellis_nat_baseColor.png").convert("RGB").getdata())
    vermelhos = [p for p in px_bc if p[0] > p[1] + 40 and p[0] > p[2] + 40]
    assert len(vermelhos) > len(px_bc) // 4 and (sum(p[0] for p in vermelhos) / len(vermelhos)) >= 150.0

    px_orm = list(Image.open(saida_nat / "trellis_nat_orm.png").convert("RGB").getdata())
    metalicos = [p for p in px_orm if p[2] >= 180]
    assert len(metalicos) > len(px_orm) // 4
    assert (sum(p[2] for p in metalicos) / len(metalicos)) >= 180.0
    assert (sum(p[1] for p in metalicos) / len(metalicos)) <= 100.0

    assert out["vc_bake"]["pbr_nativo_preservado"] is False
    for suf in ("baseColor", "normal", "orm"):
        assert (saida_vc / f"triposr_vc_{suf}.png").is_file()
    assert out["erro_levantado"] is True


def test_bug_t4_exportar_saida_pipeline_trellis2_o_voxel_e_trellis_v1(monkeypatch):
    capturado_ov: dict[str, Any] = {}

    class _FakeMeshWithVoxel:
        vertices, faces, attrs, coords = "v_tensor", "f_tensor", "attrs_vol", "coords_vol"
        layout = {"base_color": (0, 3)}
        voxel_size = 0.005

    fake_ov = types.ModuleType("o_voxel.postprocess")
    fake_ov.to_glb = lambda **kw: (capturado_ov.update(kw) or "GLB_TRELLIS2_OK")  # type: ignore[attr-defined]
    orig_import = colab_trellis_worker.importlib.import_module

    def _fake_import(nome: str):
        if nome == "o_voxel.postprocess":
            return fake_ov
        if nome == "trellis.utils.postprocessing_utils":
            mod_v1 = types.ModuleType(nome)
            mod_v1.to_glb = lambda g, m, simplify, texture_size: {"v1_g": g, "v1_m": m, "simplify": simplify, "texture_size": texture_size}  # type: ignore[attr-defined]
            return mod_v1
        return orig_import(nome)

    monkeypatch.setattr(colab_trellis_worker.importlib, "import_module", _fake_import)
    out_t2 = colab_trellis_worker._exportar_saida_pipeline(
        [_FakeMeshWithVoxel()], "microsoft/TRELLIS.2-4B", simplify=0.95, texture_size=2048, decimation_target=64_000
    )
    assert out_t2 == "GLB_TRELLIS2_OK"
    assert capturado_ov["vertices"] == "v_tensor" and capturado_ov["faces"] == "f_tensor"
    assert capturado_ov["attr_volume"] == "attrs_vol" and capturado_ov["coords"] == "coords_vol"
    assert capturado_ov["attr_layout"] == {"base_color": (0, 3)} and capturado_ov["voxel_size"] == 0.005
    assert capturado_ov["decimation_target"] == 64_000 and capturado_ov["texture_size"] == 2048
    assert capturado_ov["remesh"] is True

    out_v1 = colab_trellis_worker._exportar_saida_pipeline(
        {"gaussian": ["g0"], "mesh": ["m0"]}, "microsoft/TRELLIS-image-large", simplify=0.92, texture_size=1024
    )
    assert out_v1 == {"v1_g": "g0", "v1_m": "m0", "simplify": 0.92, "texture_size": 1024}


def test_bug_t5_doctor_cloud_ai_licenca_require_remote_e_ultra_2048(monkeypatch, tmp_path):
    monkeypatch.delenv("FORGE3D_I23D_ENDPOINT", raising=False)
    monkeypatch.delenv("FORGE3D_I23D_REQUIRE_REMOTE", raising=False)
    monkeypatch.delenv("FORGE3D_TEX_PX", raising=False)

    ok_inativo, det_inativo = cloud_ai.trellis_disponivel()
    assert ok_inativo is True and det_inativo.startswith("inativo (FORGE3D_I23D_ENDPOINT vazio")
    tr_inativo = doctor.checar()["conectores_ia"]["trellis"]
    assert tr_inativo["status"] == "inativo" and tr_inativo["ativo"] is False

    monkeypatch.setenv("FORGE3D_I23D_REQUIRE_REMOTE", "1")
    prov = mesh.MeshProvider()
    ok_pf, msg_pf = prov.preflight()
    assert ok_pf is False and "FORGE3D_I23D_REQUIRE_REMOTE=1" in msg_pf

    img = tmp_path / "in.png"
    Image.new("RGBA", (16, 16), (120, 120, 120, 255)).save(img)
    dl_noop = lambda *_a: {"report": {}, "albedo": "", "metallic_hint": "", "roughness_hint": "", "arquivos": []}  # noqa: E731
    with pytest.raises(ForgeError, match="FORGE3D_I23D_REQUIRE_REMOTE=1"):
        mesh_i23d.executar_i23d_step(
            {"id": "mob.req", "qualidade": "ultra"}, tmp_path / "err", img, None, {}, 0.0, lambda *_a: (img, {}), dl_noop
        )

    monkeypatch.setenv("FORGE3D_I23D_ENDPOINT", "https://trellis.example.ngrok.app")
    ok_ativo, det_ativo = cloud_ai.trellis_disponivel()
    assert ok_ativo is True and det_ativo.startswith("ativo (https://trellis.example.ngrok.app")
    tr_ativo = doctor.checar()["conectores_ia"]["trellis"]
    assert tr_ativo["status"] == "ativo" and tr_ativo["ativo"] is True
    assert "TRELLIS" in prov.licenca["modelo"] and prov.licenca["uso_comercial"] is True

    def _fake_remoto(item, destino, imagem, vistas, env):
        destino.mkdir(parents=True, exist_ok=True)
        (destino / "modelo.glb").write_bytes(b"glTF\x02\x00\x00\x00")
        (destino / "input.png").write_bytes(imagem.read_bytes())
        return {"ok": True, "provedor": "trellis_remoto", "modelo": "microsoft/TRELLIS.2-4B"}

    monkeypatch.setattr(mesh_trellis, "executar_i23d_remoto", _fake_remoto)
    step_out = tmp_path / "step_ultra"
    mesh_i23d.executar_i23d_step(
        {"id": "mob.ultra", "qualidade": "ultra"}, step_out, img, None, {}, 0.0, lambda *_a: (img, {}), dl_noop
    )
    assert json.loads((step_out / "modelo.json").read_text(encoding="utf-8"))["textura_px"] == 2048


def test_bug_t5_concept_prompt_apose_45_e_orcamento_clip(tmp_path):
    item_rig = {
        "id": "hero.rig", "tipo": "personagem_humanoide", "auto_rig": True,
        "prompt": "armored anime cyber knight with glowing visor and heavy pauldrons",
    }
    reforcado = concept_prompt.reforcar_prompt_rig(item_rig["prompt"], item_rig)
    assert "open A-pose arms at 45 degrees clearly separated from hips and legs" in reforcado
    assert "visible neck and lower collar" in reforcado
    for vista in ("front", "back", "left", "right"):
        pv = concept_prompt.prompt_para_vista(item_rig["prompt"], vista, auto_rig=True)
        assert "open A-pose arms at 45 degrees clearly separated from hips and legs" in pv
        assert "visible neck and lower collar" in pv and "T-pose/A-pose" not in pv
    _cmd, info = concept.montar_comando(item_rig, tmp_path / "concept_out")
    assert concept_prompt.estimar_tokens_clip(info["prompt_final"]) <= concept_prompt.LIMITE_TOKENS_CLIP
    assert "open A-pose arms at 45 degrees" in info["prompt_final"]


@pytest.mark.blender
def test_bug_t5_uv_boost_cabeca_humanoide_sem_rasgar_ilha_no_pescoco(tmp_path):
    glb_out = tmp_path / "humanoid_uv.glb"
    codigo = f"""
import json, sys
sys.path.insert(0, {str(BLENDER_DIR)!r})
import bpy, bmesh
import postprocess_normals_uv, postprocess_uv_boost, postprocess

postprocess.limpar_cena()
bpy.ops.mesh.primitive_cylinder_add(vertices=48, radius=0.18, depth=1.45, location=(0.0, 0.0, 0.725))
tronco = bpy.context.active_object
bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.subdivide(number_cuts=12)
bpy.ops.object.mode_set(mode="OBJECT")
bpy.ops.mesh.primitive_uv_sphere_add(segments=36, ring_count=24, radius=0.16, location=(0.0, 0.0, 1.62))
cabeca = bpy.context.active_object
bpy.ops.object.select_all(action="DESELECT")
tronco.select_set(True); cabeca.select_set(True)
bpy.context.view_layer.objects.active = tronco
bpy.ops.object.join()
obj = bpy.context.active_object

bm = bmesh.new(); bm.from_mesh(obj.data)
bmesh.ops.triangulate(bm, faces=list(bm.faces))
bm.to_mesh(obj.data); bm.free(); obj.data.update()

uv_name = postprocess_normals_uv.desdobrar_uv(obj)
escaladas_extra = postprocess_uv_boost.aplicar_prioridade_uv_cabeca(obj, fator=1.0)

zs = [v.co.z for v in obj.data.vertices]
z_corte = min(zs) + 0.78 * (max(zs) - min(zs))
bm2 = bmesh.new(); bm2.from_mesh(obj.data)
uv_lay = bm2.loops.layers.uv.active
rasgadas = 0
for e in bm2.edges:
    if len(e.link_faces) != 2: continue
    f0, f1 = e.link_faces[0], e.link_faces[1]
    if (f0.calc_center_median().z >= z_corte) == (f1.calc_center_median().z >= z_corte): continue
    uv0 = {{lp.vert.index: lp[uv_lay].uv.copy() for lp in f0.loops}}
    uv1 = {{lp.vert.index: lp[uv_lay].uv.copy() for lp in f1.loops}}
    va, vb = e.verts[0].index, e.verts[1].index
    if ((uv0[va] - uv1[va]).length < 1e-4) != ((uv0[vb] - uv1[vb]).length < 1e-4): rasgadas += 1
bm2.free()

img = bpy.data.images.new("AlbedoUV", width=32, height=32, alpha=False)
img.pixels = [0.7, 0.6, 0.5, 1.0] * (32 * 32)
mat = bpy.data.materials.new("MatUV"); mat.use_nodes = True
tex = mat.node_tree.nodes.new("ShaderNodeTexImage"); tex.image = img
mat.node_tree.links.new(tex.outputs["Color"], mat.node_tree.nodes.get("Principled BSDF").inputs["Base Color"])
obj.data.materials.append(mat)
bpy.ops.export_scene.gltf(filepath={str(glb_out)!r}, export_format="GLB")
print("OUT_T5_UV:" + json.dumps({{"uv_name": uv_name, "polys": len(obj.data.polygons), "escaladas": escaladas_extra, "rasgadas": rasgadas}}))
"""
    proc = _rodar_blender_py(codigo, timeout=120)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    info_uv = json.loads(next(ln for ln in proc.stdout.splitlines() if ln.startswith("OUT_T5_UV:"))[10:])
    assert info_uv["polys"] >= 1000 and info_uv["escaladas"] > 0 and info_uv["rasgadas"] == 0

    gltf, binario = ler_glb_bin(glb_out)
    status = _uv_status(gltf, binario, forcar_area=True)
    assert status["fora_intervalo"] == 0 and status["uv_colapsada"] == 0 and status["uv_sobreposta"] == 0
    assert status["uv_area_total"] >= 0.25
