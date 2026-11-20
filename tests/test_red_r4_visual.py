"""RED discovery suite (TDD) for R4 Visual Quality 3D & G15 (F22-F25)."""

from __future__ import annotations

import ast
import base64
import importlib
import inspect
import io
import json
import re
import subprocess
import sys
import types
from pathlib import Path

import jsonschema
import pytest
import yaml
from PIL import Image

from forge3d import post, qc
from forge3d.providers import cloud_ai, concept, mesh

RAIZ = Path(__file__).resolve().parents[1]
SPEC_V6 = RAIZ / "schemas" / "spec.v6.schema.json"
MANIFEST_V6 = RAIZ / "schemas" / "manifest.v6.schema.json"


def _rodar_blender(codigo: str, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [post.binario(), "--background", "--factory-startup", "--python-expr", codigo],
        capture_output=True, text=True, timeout=timeout,
    )


_BPY_PROXY_SRC = """class _SubProxy:
    def __init__(self, real, ov): self._r, self._ov = real, ov
    def __getattr__(self, k): return self._ov[k] if k in self._ov else getattr(self._r, k)
class _BpyProxy(_SubProxy):
    def __init__(self, real, obj_ov):
        super().__init__(real, {"ops": _SubProxy(real.ops, {"object": _SubProxy(real.ops.object, obj_ov)})})
"""


def _png_bytes(cor: tuple[int, int, int, int] = (180, 120, 90, 255), size: tuple[int, int] = (64, 64)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", size, cor).save(buf, format="PNG")
    return buf.getvalue()


def _importar_tool(nome: str):
    tools_dir = str(RAIZ / "tools")
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    return importlib.import_module(nome)


# F22: Explicit sub-routes (spec/mesh) & conformal template_body attachments
def test_f22_spec_e_mesh_separam_subrotas_sem_bypass_silencioso(monkeypatch, tmp_path):
    schema = json.loads(SPEC_V6.read_text(encoding="utf-8"))
    rotas_schema = set(schema["$defs"]["item"]["properties"]["rota"]["enum"])
    assert {"i23d", "template", "procedural", "extrude_2d"} <= rotas_schema

    img_in = tmp_path / "elmo_concept.png"
    img_in.write_bytes(_png_bytes((200, 170, 90, 255)))
    destino = tmp_path / "raw_elmo"

    prov = mesh.MeshProvider()
    monkeypatch.setattr(prov, "preflight_item", lambda _item: (True, "ok"))
    comandos: list[list[str]] = []

    def fake_run(cmd, **_kwargs):
        comandos.append([str(c) for c in cmd])
        out_dir = Path(cmd[cmd.index("--saida-dir") + 1])
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "modelo.glb").write_bytes(b"glTF\x02\x00\x00\x00")
        (out_dir / "i23d_resultado.json").write_text(json.dumps({"ok": True, "faces": 4000}), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(mesh.subprocess, "run", fake_run)

    # Explicit i23d sub-route + origem MUST NOT silently short-circuit into modular_armor.py.
    item = {
        "id": "arm.elmo.01", "tipo": "prop_equipavel", "parte": "elmo",
        "rota": "i23d", "origem": str(img_in), "prompt": "ornate winged paladin helm",
    }
    prov.gerar(item, {"perfil": "godot4"}, destino)
    assert comandos, "nenhum subprocesso executado"
    assert "modular_armor.py" not in " ".join(comandos[0])
    assert str(img_in) in comandos[0]


@pytest.mark.blender
def test_f22_template_body_sobreposicoes_conformes_sem_folga_flutuante(tmp_path):
    metricas_path = tmp_path / "ov_metrics.json"
    codigo = f"""
import json, math, sys
from pathlib import Path
sys.path.insert(0, {str(RAIZ / "blender")!r})
import bpy, bmesh
from mathutils.bvhtree import BVHTree
import template_body

bpy.ops.wm.read_factory_settings(use_empty=True)
h = 1.75
bpy.ops.mesh.primitive_cylinder_add(vertices=24, radius=0.095, depth=0.95, location=(0.0, 0.0, 1.22))
body = bpy.context.active_object
for sx in (-1.0, 1.0):
    bpy.ops.mesh.primitive_cylinder_add(vertices=16, radius=0.048, depth=0.80, location=(sx * 0.11, 0.0, 0.40))
    leg = bpy.context.active_object
    bpy.ops.mesh.primitive_cylinder_add(vertices=16, radius=0.032, depth=0.34, rotation=(0.0, math.pi / 2, 0.0), location=(sx * 0.36, 0.0, 1.18))
    arm = bpy.context.active_object
    bm_a = bmesh.new()
    bm_a.from_mesh(arm.data)
    bmesh.ops.subdivide_edges(bm_a, edges=list(bm_a.edges), cuts=4, use_grid_fill=True)
    bm_a.to_mesh(arm.data)
    bm_a.free()
    bpy.ops.object.select_all(action="DESELECT")
    for o in (leg, arm, body):
        o.select_set(True)
    bpy.context.view_layer.objects.active = body
    bpy.ops.object.join()
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

ov = template_body._construir_sobreposicoes_medievais_3d(body, 0, 1, 2)
bvh = BVHTree.FromObject(body, bpy.context.evaluated_depsgraph_get())
bracelet_dists, boot_dists = [], []
for v in ov.data.vertices:
    z = v.co.z
    if 0.60 * h <= z <= 0.74 * h and abs(v.co.x) >= 0.16 * h:
        bracelet_dists.append(float(bvh.find_nearest(v.co)[3]))
    elif 0.04 * h <= z <= 0.26 * h:
        boot_dists.append(float(bvh.find_nearest(v.co)[3]))

Path({str(metricas_path)!r}).write_text(json.dumps({{
    "bracelet_min_m": min(bracelet_dists) if bracelet_dists else 999.0,
    "boot_min_m": min(boot_dists) if boot_dists else 999.0,
    "n_br": len(bracelet_dists), "n_bo": len(boot_dists),
}}), encoding="utf-8")
print("OV_OK")
"""
    proc = _rodar_blender(codigo)
    assert proc.returncode == 0 and "OV_OK" in proc.stdout, proc.stdout + proc.stderr
    res = json.loads(metricas_path.read_text(encoding="utf-8"))
    assert res["n_br"] > 0 and res["n_bo"] > 0
    assert res["bracelet_min_m"] <= 0.0015, f"bracelete flutuando a {res['bracelet_min_m']*1000:.2f} mm"
    assert res["boot_min_m"] <= 0.0020, f"bota flutuando a {res['boot_min_m']*1000:.2f} mm"


# F23: 4-view orthographic Gemini concepts & zero fal.run
def test_f23_concept_provider_gera_4_vistas_ortograficas_gemini_com_referencia(monkeypatch, tmp_path):
    monkeypatch.setenv("FORGE3D_GEMINI_API_KEY", "gem_test_secret_123")
    ref_png = tmp_path / "estilo_ref.png"
    ref_png.write_bytes(_png_bytes((110, 140, 200, 255)))
    out_dir = tmp_path / "concept_4v"

    b64_out = base64.b64encode(_png_bytes((210, 90, 60, 255), size=(128, 128))).decode("ascii")
    chamadas: list[dict] = []

    class _FakeResp:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self) -> bytes:
            payload = {"steps": [{"type": "model_output", "content": [{"type": "image", "data": b64_out, "mime_type": "image/png"}]}]}
            return json.dumps(payload).encode("utf-8")

    def fake_urlopen(req, timeout=120):
        chamadas.append({"url": req.full_url, "body": json.loads(req.data.decode("utf-8"))})
        return _FakeResp()

    monkeypatch.setattr(cloud_ai.urllib.request, "urlopen", fake_urlopen)
    prov = concept.ConceptProvider()
    item = {
        "id": "char.paladin.01", "tipo": "personagem_humanoide",
        "prompt": "medieval paladin knight in silver armor",
        "provider_conceito": "gemini", "referencia_estilo": str(ref_png), "vistas": 4,
    }
    meta = prov.gerar(item, out_dir)["meta"]
    vistas = meta.get("vistas") or {}
    for v in ("front", "back", "left", "right"):
        assert v in vistas, f"vista ortografica ausente: {v}"
        assert Path(vistas[v]).is_file()
    assert len(chamadas) == 4
    assert all(c["body"]["model"] == "gemini-nano-banana-2.1" for c in chamadas)
    assert meta.get("referencia_estilo_sha256")


def test_f23_zero_referencias_fal_run_ou_chave_fal_em_src_e_tools():
    ofensores: list[str] = []
    proibidos = ("fal.run", "fal.ai", "FORGE3D_FAL_API_KEY")
    for pasta in (RAIZ / "src" / "forge3d", RAIZ / "tools"):
        for arq in sorted(pasta.rglob("*.py")):
            txt = arq.read_text(encoding="utf-8", errors="ignore")
            for termo in proibidos:
                if termo in txt:
                    ofensores.append(f"{arq.relative_to(RAIZ)}:{termo}")
    assert not ofensores, f"referencias proibidas fal.run encontradas: {ofensores}"


# F24: Bake 4-vistas, cage, no Sobel, bake order, quadriflow, pbr_zonas, delight
@pytest.mark.blender
def test_f24_bake_pbr_sem_sobel_com_cage_4_vistas_e_sem_downscale_256(tmp_path):
    sys.path.insert(0, str(RAIZ / "blender"))
    bake_mod = importlib.import_module("bake_pbr")
    sig = inspect.signature(bake_mod.executar_bake_high_low)
    params_4v = {"origem_texturas", "vistas", "vistas_ortograficas"} & set(sig.parameters)
    assert params_4v, "executar_bake_high_low nao aceita entradas multi-vista (4 vistas)"

    saida = tmp_path / "bake_out"
    res_json = tmp_path / "bake_check.json"
    orc_dir = tmp_path / "orc"
    orc_dir.mkdir()
    nm_1024, orm_1024 = orc_dir / "big_normal.png", orc_dir / "big_orm.png"
    for p_img, cor in ((nm_1024, (128, 128, 255, 255)), (orm_1024, (255, 180, 0, 255))):
        p_img.write_bytes(_png_bytes(cor, size=(1024, 1024)))
    glb_fake = orc_dir / "big.glb"
    glb_fake.write_bytes(b"0" * 5000)

    codigo = _BPY_PROXY_SRC + f"""
import json, sys
from pathlib import Path
sys.path.insert(0, {str(RAIZ / "blender")!r})
import bpy, postprocess, bake_pbr

postprocess.limpar_cena()
bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=16, radius=0.8)
obj = bpy.context.active_object
ca = obj.data.color_attributes.new("Color", "FLOAT_COLOR", "POINT")
for i, v in enumerate(obj.data.vertices):
    ca.data[i].color = (0.95, 0.95, 0.95, 1.0) if v.co.x >= 0.0 else (0.05, 0.05, 0.05, 1.0)

orig_bake = bpy.ops.object.bake
cage_flags = []
def spy_bake(*args, **kwargs):
    cage_flags.append(bool(bpy.context.scene.render.bake.use_cage))
    return orig_bake(*args, **kwargs)
bake_pbr.bpy = _BpyProxy(bpy, {{"bake": spy_bake}})
try:
    res = bake_pbr.executar_bake_high_low(
        obj=obj, saida_dir={str(saida)!r}, nome_base="esfera_step", px=128, limite_triangulos=400,
        reparo_fn=postprocess.reparar_malha, decimar_fn=postprocess.decimar, suavizar_fn=postprocess.suavizar_por_angulo, uv_fn=postprocess.desdobrar_uv, px_sub=128,
    )
finally:
    bake_pbr.bpy = bpy
Path({str(res_json)!r}).write_text(json.dumps({{"cage_flags": cage_flags, "res": res}}), encoding="utf-8")

bpy.ops.mesh.primitive_cube_add(size=1.0)
obj_orc = bpy.context.active_object
mat_orc = bpy.data.materials.new("OrcMat")
mat_orc.use_nodes = True
bsdf_orc = mat_orc.node_tree.nodes.get("Principled BSDF")
for cam_img in ({str(nm_1024)!r}, {str(orm_1024)!r}):
    tn = mat_orc.node_tree.nodes.new("ShaderNodeTexImage")
    tn.image = bpy.data.images.load(cam_img, check_existing=False)
    tn.image.colorspace_settings.name = "Non-Color"
    mat_orc.node_tree.links.new(tn.outputs["Color"], bsdf_orc.inputs["Roughness"])
obj_orc.data.materials.append(mat_orc)
texs_orc = [{{"papel": "normal", "caminho": "big_normal.png", "bytes": {nm_1024.stat().st_size}}}, {{"papel": "orm", "caminho": "big_orm.png", "bytes": {orm_1024.stat().st_size}}}]
bake_pbr.ajustar_resolucao_orcamento(obj_orc, {str(orc_dir)!r}, texs_orc, {str(glb_fake)!r}, 100, lambda: None)
print("BAKE_CHECK_OK")
"""
    proc = _rodar_blender(codigo, timeout=180)
    assert proc.returncode == 0 and "BAKE_CHECK_OK" in proc.stdout, proc.stdout + proc.stderr
    dados = json.loads(res_json.read_text(encoding="utf-8"))
    assert dados["cage_flags"] and all(dados["cage_flags"]), "bake deve ativar use_cage=True"

    nm_img = Image.open(saida / "esfera_step_normal.png").convert("RGB")
    max_dev_rg = max(max(abs(r - 128), abs(g - 128)) for r, g, _b in nm_img.getdata())
    assert max_dev_rg <= 24, f"normal map contaminado por Sobel(BaseColor): desvio RG={max_dev_rg}"
    assert Image.open(nm_1024).size[0] >= 512 and Image.open(orm_1024).size[0] >= 512, "ajustar_resolucao_orcamento fez downscale indevido abaixo de 512px"


@pytest.mark.blender
def test_f24_postprocess_ordem_bake_apos_escala_quadriflow_e_sem_taubin_cumulativo(tmp_path):
    src_pp = (RAIZ / "blender" / "postprocess.py").read_text(encoding="utf-8")
    assert src_pp.index("bake_pbr.executar_bake_high_low") > src_pp.index("transformar(escala, -pivo)"), "bake_pbr.executar_bake_high_low roda ANTES de transformar(escala, -pivo)"

    qf_json = tmp_path / "qf_kwargs.json"
    codigo = _BPY_PROXY_SRC + f"""
import json, sys
from pathlib import Path
sys.path.insert(0, {str(RAIZ / "blender")!r})
import bpy, postprocess

postprocess.limpar_cena()
bpy.ops.mesh.primitive_cube_add(size=1.0)
obj = bpy.context.active_object
capturado = {{}}
orig_qf = bpy.ops.object.quadriflow_remesh
class _SpyQF:
    def get_rna_type(self): return orig_qf.get_rna_type()
    def __call__(self, **kw): return capturado.update(kw) or {{"FINISHED"}}

postprocess.bpy = _BpyProxy(bpy, {{"quadriflow_remesh": _SpyQF()}})
try:
    postprocess.retopologizar_quadriflow(obj, 1000)
finally:
    postprocess.bpy = bpy

bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=5, radius=1.0)
obj_hi = bpy.context.active_object
taubin_bm_iters = []
orig_t = getattr(postprocess, "_suavizar_taubin_bm", None)
if callable(orig_t):
    def spy_t(bm, iteracoes=2, fator=0.45):
        taubin_bm_iters.append(int(iteracoes))
        return orig_t(bm, iteracoes=iteracoes, fator=fator)
    postprocess._suavizar_taubin_bm = spy_t
postprocess.decimar(obj_hi, 1500, proteger_cabeca_maos=True)

Path({str(qf_json)!r}).write_text(json.dumps({{"qf": capturado, "taubin_bm_iters": taubin_bm_iters}}), encoding="utf-8")
print("QF_OK")
"""
    proc = _rodar_blender(codigo)
    assert proc.returncode == 0 and "QF_OK" in proc.stdout, proc.stdout + proc.stderr
    dados_pp = json.loads(qf_json.read_text(encoding="utf-8"))
    kw = dados_pp["qf"]
    assert kw.get("preserve_attributes") is True
    assert kw.get("use_preserve_sharp") is True
    assert not any(i > 0 for i in dados_pp["taubin_bm_iters"]), f"Taubin em decimar ativo: {dados_pp['taubin_bm_iters']}"

    for arq, fn_tb in ((RAIZ / "blender" / "bake_pbr.py", "_suavizar_high_taubin"), (RAIZ / "blender" / "postprocess.py", "_suavizar_taubin_bm")):
        tree_tb = ast.parse(arq.read_text(encoding="utf-8"))
        ativos = [
            n.lineno for n in ast.walk(tree_tb)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == fn_tb
            and not any(k.arg == "iteracoes" and isinstance(k.value, ast.Constant) and k.value.value == 0 for k in n.keywords)
            and not (len(n.args) >= 2 and isinstance(n.args[1], ast.Constant) and n.args[1].value == 0)
        ]
        assert not ativos, f"passada Taubin cumulativa {fn_tb} ativa em {arq.name}:{ativos}"

    tree_pp = ast.parse(src_pp)
    fn_red = next(n for n in tree_pp.body if isinstance(n, ast.FunctionDef) and n.name == "_reduzir_imagens_embutidas_orcamento")
    consts = {c.value for c in ast.walk(fn_red) if isinstance(c, ast.Constant) and isinstance(c.value, int)}
    assert 256 not in consts and 128 not in consts, f"downscale silencioso 256/128 presente: {consts}"


@pytest.mark.blender
def test_f24_procedural_pbr_zonas_cor_tinta_gera_variacao_base_vs_sec(tmp_path):
    res_json = tmp_path / "zonas_mix.json"
    codigo = f"""
import json, sys
from pathlib import Path
sys.path.insert(0, {str(RAIZ / "blender")!r})
import bpy, procedural_pbr

bpy.ops.wm.read_factory_settings(use_empty=True)
mat = procedural_pbr.construir_shader_pbr_zonas_blender("mat_tinta", [{{"preset": "pedra_musgo", "cor_tinta": "#884422"}}])
pares = []
for node in mat.node_tree.nodes:
    if node.type == "MIX" and getattr(node, "data_type", "") == "RGBA":
        a = [round(float(x), 4) for x in node.inputs["A"].default_value]
        b = [round(float(x), 4) for x in node.inputs["B"].default_value]
        if any(lnk.to_socket == node.inputs["Factor"] for lnk in mat.node_tree.links):
            pares.append({{"a": a, "b": b}})
Path({str(res_json)!r}).write_text(json.dumps(pares), encoding="utf-8")
print("ZONAS_OK")
"""
    proc = _rodar_blender(codigo)
    assert proc.returncode == 0 and "ZONAS_OK" in proc.stdout, proc.stdout + proc.stderr
    pares = json.loads(res_json.read_text(encoding="utf-8"))
    assert pares and any(p["a"] != p["b"] for p in pares), f"cor_base == cor_sec em pbr_zonas: {pares}"


def test_f24_delight_emissive_metal_liso_e_variacao_roughness_dieletrico(tmp_path):
    delight = _importar_tool("delight")

    img_em = Image.new("RGBA", (64, 64), (30, 30, 35, 255))
    img_em.paste((255, 230, 60, 255), (24, 24, 40, 40))
    in_em, out_em = tmp_path / "runa.png", tmp_path / "emissive.png"
    img_em.save(in_em)
    rc = delight.main(["--imagem", str(in_em), "--saida-emissive", str(out_em)])
    assert rc == 0 and out_em.is_file()
    em_l = Image.open(out_em).convert("L")
    assert em_l.getpixel((32, 32)) > 150 and em_l.getpixel((5, 5)) < 30

    img_met = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    for y in range(12, 52):
        for x in range(12, 52):
            v = 175 + ((x - 12) % 8)
            img_met.putpixel((x, y), (v, v, min(255, v + 4), 255))
    met_l, _ = delight.estimar_mapas_pbr(img_met)
    assert met_l.getpixel((32, 32)) >= 128

    img_diel = Image.new("RGBA", (64, 64), (40, 50, 140, 255))
    img_diel.paste((220, 220, 230, 255), (32, 0, 64, 64))
    _, rough_diel = delight.estimar_mapas_pbr(img_diel)
    assert abs(rough_diel.getpixel((10, 32)) - rough_diel.getpixel((50, 32))) >= 20


# F25: Colab TRELLIS.2-4B / Pixal3D (MIT), boss rig, smart_fit, G15
def test_f25_colab_trellis_worker_trellis2_pixal3d_multiview_e_spec6(monkeypatch, tmp_path):
    worker = _importar_tool("colab_trellis_worker")
    assert "TRELLIS.2" in worker.MODELO_TRELLIS_PADRAO or "Pixal3D" in worker.MODELO_TRELLIS_PADRAO

    in_dir = tmp_path / "concepts"
    asset_dir = in_dir / "paladin"
    asset_dir.mkdir(parents=True)
    for vista in ("front", "back", "left", "right"):
        (asset_dir / f"{vista}.png").write_bytes(_png_bytes((180, 140, 100, 255)))
    out_dir = tmp_path / "glbs"

    chamadas_run: list[tuple] = []

    class _FakeMesh:
        def export(self, path_str: str) -> None:
            Path(path_str).write_bytes(b"glTF\x02\x00\x00\x00FAKE_TRELLIS2")

    class _FakePipe:
        def run(self, imagem, seed=1, **_kw):
            chamadas_run.append((imagem, seed))
            return {"gaussian": ["g"], "mesh": ["m"]}

    fake_trellis = types.ModuleType("trellis")
    fake_utils = types.ModuleType("trellis.utils")
    fake_pp = types.ModuleType("trellis.utils.postprocessing_utils")
    fake_pp.to_glb = lambda *_a, **_kw: _FakeMesh()
    monkeypatch.setitem(sys.modules, "trellis", fake_trellis)
    monkeypatch.setitem(sys.modules, "trellis.utils", fake_utils)
    monkeypatch.setitem(sys.modules, "trellis.utils.postprocessing_utils", fake_pp)

    entradas = worker.processar_pasta(in_dir, out_dir, pipeline=_FakePipe())
    assert len(entradas) == 1 and len(chamadas_run) == 1
    assert isinstance(chamadas_run[0][0], (list, tuple)) and len(chamadas_run[0][0]) == 4
    doc = yaml.safe_load(worker.gerar_yaml_spec(entradas, schema_version=6))
    jsonschema.validate(doc, json.loads(SPEC_V6.read_text(encoding="utf-8")))
    assert doc["lote"][0]["rota"] == "import"
    assert entradas[0]["sha256"].startswith("sha256:")


@pytest.mark.blender
def test_f25_autorig_boss_largo_e_smart_fit_corpo_obj_surface_deform(tmp_path):
    res_json = tmp_path / "boss_sf.json"
    codigo = f"""
import json, sys
from pathlib import Path
sys.path.insert(0, {str(RAIZ / "blender")!r})
import bpy, bmesh, autorig, smart_fit

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_cylinder_add(vertices=24, radius=0.42, depth=1.0, location=(0.0, 0.0, 1.30))
boss = bpy.context.active_object
bm_b = bmesh.new()
bm_b.from_mesh(boss.data)
bmesh.ops.subdivide_edges(bm_b, edges=list(bm_b.edges), cuts=6, use_grid_fill=True)
bm_b.to_mesh(boss.data)
bm_b.free()
for sx in (-1.0, 1.0):
    bpy.ops.mesh.primitive_cylinder_add(vertices=16, radius=0.11, depth=0.90, location=(sx * 0.34, 0.0, 0.45))
    leg = bpy.context.active_object
    bpy.ops.object.select_all(action="DESELECT")
    leg.select_set(True)
    boss.select_set(True)
    bpy.context.view_layer.objects.active = boss
    bpy.ops.object.join()
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
marcos = autorig.estimar_marcos(boss)

bpy.ops.mesh.primitive_cylinder_add(vertices=20, radius=0.20, depth=1.0, location=(0.0, 0.0, 0.5))
bpy.context.active_object.name = "HeroBody"
bpy.ops.mesh.primitive_cylinder_add(vertices=20, radius=0.35, depth=0.5, location=(0.0, 0.0, 0.6))
armor = bpy.context.active_object
armor.name = "ArmorChest"
sf_res = smart_fit.aplicar_smart_fit_job(armor, {{"conformar_anatomico": {{"usar_surface_deform": True}}}}, corpo_obj=None)

Path({str(res_json)!r}).write_text(json.dumps({{"altura": marcos["altura"], "torso_hw": marcos["torso_hw"], "leg_x_L": marcos["leg_x_L"], "sf": sf_res}}), encoding="utf-8")
print("BOSS_SF_OK")
"""
    proc = _rodar_blender(codigo)
    assert proc.returncode == 0 and "BOSS_SF_OK" in proc.stdout, proc.stdout + proc.stderr
    dados = json.loads(res_json.read_text(encoding="utf-8"))
    h = dados["altura"]
    assert dados["torso_hw"] > 0.16 * h, f"torso_hw grampeado em {dados['torso_hw'] / h:.3f}*h"
    assert dados["leg_x_L"] > 0.135 * h, f"leg_x_L grampeado em {dados['leg_x_L'] / h:.3f}*h"
    assert dados["sf"].get("aplicado") is True, f"smart_fit ignorou corpo da cena: {dados['sf']}"


def test_f25_qc_g15_e_visual_qa_critic_fidelidade_concept_3d(tmp_path):
    assert "G15" in qc.GATES
    manifest_schema = json.loads(MANIFEST_V6.read_text(encoding="utf-8"))
    gate_pat = manifest_schema["properties"]["qc"]["properties"]["gates"]["items"]["properties"]["id"]["pattern"]
    assert re.match(gate_pat, "G15"), f"manifest.v6.schema.json rejeita G15: {gate_pat}"

    critic = _importar_tool("visual_qa_critic")
    concept_png, render_png = tmp_path / "concept.png", tmp_path / "render_mismatched.png"
    c_img = Image.new("RGBA", (128, 128), (220, 220, 220, 255))
    c_img.paste((210, 40, 40, 255), (52, 16, 76, 112))
    c_img.save(concept_png)

    r_img = Image.new("RGBA", (128, 128), (220, 220, 220, 255))
    r_img.paste((40, 60, 210, 255), (12, 56, 116, 72))
    r_img.save(render_png)

    fn_fid = getattr(critic, "avaliar_fidelidade_concept_3d", None) or getattr(critic, "avaliar_fidelidade_g15", None)
    assert callable(fn_fid), "visual_qa_critic nao expoe avaliador de fidelidade concept->3D (G15)"
    res_fid = fn_fid(concept_png, render_png)
    assert res_fid["aprovado"] is False
