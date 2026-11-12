"""Testes headless de Onda 3 (extrude_2d + decimate protegido) e Onda 1 (UV proj + ORM hints)."""

from __future__ import annotations

import ast
import json
import subprocess
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from forge3d import plan, post, profiles, qc

RAIZ = Path(__file__).resolve().parents[1]
BLENDER_DIR = RAIZ / "blender"


def _rodar_blender_py(codigo: str, timeout: int = 180) -> subprocess.CompletedProcess[str]:
    blender = post.binario()
    return subprocess.run(
        [blender, "--background", "--factory-startup", "--python-expr", codigo],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def test_blender_scripts_sem_pil_ou_numpy():
    """I9: todos os scripts em blender/*.py usam apenas stdlib e modulos do Blender."""
    proibidos = {"PIL", "Pillow", "numpy", "np", "cv2", "torch"}
    for arq in sorted(BLENDER_DIR.glob("*.py")):
        arvore = ast.parse(arq.read_text(encoding="utf-8"))
        encontrados: set[str] = set()
        for node in ast.walk(arvore):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    encontrados.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.module:
                encontrados.add(node.module.split(".")[0])
        violacoes = encontrados & proibidos
        assert not violacoes, f"{arq.name} importou modulos proibidos: {violacoes}"


@pytest.mark.blender
def test_extrude_2d_espada_e_capa_manifold_e_qc_verde(tmp_path: Path):
    """Silhueta PNG de espada e capa geram malhas estanques (0 nao-manifold) aprovadas no QC."""
    bruto_arma = tmp_path / "bruto_arma"
    final_arma = tmp_path / "final_arma"
    bruto_arma.mkdir()
    final_arma.mkdir()

    # Espada RGBA com lamina + guarda + cabo + pomo
    espada_png = bruto_arma / "espada.png"
    im = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im)
    draw.polygon([(256, 20), (288, 95), (282, 340), (230, 340), (224, 95)], fill=(210, 220, 235, 255))
    draw.rectangle([(175, 340), (337, 370)], fill=(215, 175, 55, 255))
    draw.rectangle([(242, 370), (270, 462)], fill=(115, 65, 30, 255))
    draw.ellipse([(234, 458), (278, 496)], fill=(215, 175, 55, 255))
    im.save(espada_png)

    (bruto_arma / "modelo.json").write_text(
        json.dumps(
            {
                "schema": "forge3d/bruto-extrude@1",
                "imagem": "espada.png",
                "modo": "arma",
            }
        ),
        encoding="utf-8",
    )

    perfil = profiles.carregar("godot4")
    item_arma = {
        "id": "prop.espada.extrude.01",
        "tipo": "prop_equipavel",
        "rota": "mesh",
        "parte": "arma",
        "altura_metros": 1.10,
        "pivot": "empunhadura",
        "limite_triangulos": 800,
        "colisao": "convex",
        "lod": [100],
        "auto_rig": False,
        "tags": [],
    }
    job_arma = {
        "bruto_dir": str(bruto_arma),
        "bruto_arquivo": "modelo.json",
        "saida_dir": str(final_arma),
        "saida_resultado": str(final_arma / "resultado.json"),
        "perfil": plan.perfil_resolvido(perfil),
        "item": item_arma,
        "nome_base": item_arma["id"],
        "nome_arquivo": f"{item_arma['id']}.glb",
    }
    res_arma = post.executar(job_arma)
    assert res_arma["ok"] is True
    assert res_arma["medidas"]["nao_manifold"] == 0
    assert res_arma["medidas"]["degeneradas"] == 0
    assert res_arma["medidas"]["triangulos"] <= 800
    assert res_arma["medidas"]["gerada"]["extrude_2d"]["modo"] == "arma"
    res_arma["licenca"] = {"modelo": "procedural", "uso_comercial": True, "notice": "teste"}

    rel_arma = qc.verificar(item_arma, perfil, final_arma, res_arma)
    assert rel_arma["aprovado"] is True, [g for g in rel_arma["gates"] if g["status"] != "ok"]
    gltf_arma = qc.ler_glb(final_arma / f"{item_arma['id']}.glb")
    info_arma = qc.analisar(gltf_arma)
    assert info_arma["sem_uv"] == 0
    assert info_arma["com_textura"] == 1
    assert info_arma["imagens_externas"] == []

    # Capa com dimensao nao-POT e fundo opaco uniforme (deve normalizar para POT e curvar em Y)
    bruto_capa = tmp_path / "bruto_capa"
    final_capa = tmp_path / "final_capa"
    bruto_capa.mkdir()
    final_capa.mkdir()

    capa_png = bruto_capa / "capa.png"
    imc = Image.new("RGB", (300, 500), (242, 242, 242))
    dc = ImageDraw.Draw(imc)
    dc.polygon([(95, 35), (205, 35), (258, 470), (42, 470)], fill=(155, 25, 35))
    imc.save(capa_png)

    (bruto_capa / "modelo.json").write_text(
        json.dumps(
            {
                "schema": "forge3d/bruto-extrude@1",
                "imagem": "capa.png",
                "modo": "capa",
            }
        ),
        encoding="utf-8",
    )
    item_capa = {
        "id": "prop.capa.extrude.01",
        "tipo": "prop_estatico",
        "rota": "mesh",
        "parte": "capa",
        "altura_metros": 0.90,
        "pivot": "topo",
        "limite_triangulos": 800,
        "colisao": "none",
        "lod": [100],
        "auto_rig": False,
        "tags": [],
    }
    job_capa = {
        "bruto_dir": str(bruto_capa),
        "bruto_arquivo": "modelo.json",
        "saida_dir": str(final_capa),
        "saida_resultado": str(final_capa / "resultado.json"),
        "perfil": plan.perfil_resolvido(perfil),
        "item": item_capa,
        "nome_base": item_capa["id"],
        "nome_arquivo": f"{item_capa['id']}.glb",
    }
    res_capa = post.executar(job_capa)
    assert res_capa["ok"] is True
    assert res_capa["medidas"]["nao_manifold"] == 0
    assert res_capa["medidas"]["degeneradas"] == 0
    assert res_capa["medidas"]["triangulos"] <= 800
    res_capa["licenca"] = {"modelo": "procedural", "uso_comercial": True, "notice": "teste"}

    rel_capa = qc.verificar(item_capa, perfil, final_capa, res_capa)
    assert rel_capa["aprovado"] is True, [g for g in rel_capa["gates"] if g["status"] != "ok"]


@pytest.mark.blender
@pytest.mark.lento
def test_bake_pbr_camera_uv_proj_dot_blend_e_hints_orm(tmp_path: Path):
    """Projecao frontal +Y usa origem_textura na frente, VertexColor atras, e assa ORM metallic/roughness."""
    saida = tmp_path / "saida"
    saida.mkdir()

    # Textura frontal 256x256: esquerda vermelho (230,25,25), direita verde (25,215,40)
    origem_png = tmp_path / "origem.png"
    im_orig = Image.new("RGB", (256, 256))
    px_orig = im_orig.load()
    for y in range(256):
        for x in range(256):
            px_orig[x, y] = (230, 25, 25) if x < 128 else (25, 215, 40)
    im_orig.save(origem_png)

    # Metallic hint: metade superior metalica (240), metade inferior dielétrica (0)
    met_png = tmp_path / "metallic_hint.png"
    im_met = Image.new("L", (256, 256), 0)
    for y in range(128):
        for x in range(256):
            im_met.putpixel((x, y), 240)
    im_met.save(met_png)

    # Roughness hint: metade superior lisa (40), metade inferior fosca (215)
    rough_png = tmp_path / "roughness_hint.png"
    im_rough = Image.new("L", (256, 256), 215)
    for y in range(128):
        for x in range(256):
            im_rough.putpixel((x, y), 40)
    im_rough.save(rough_png)

    meta_path = tmp_path / "meta.json"
    probe_path = tmp_path / "probe.json"

    codigo = f"""
import json, sys
sys.path.insert(0, {str(BLENDER_DIR)!r})
import bpy, bmesh
import postprocess, bake_pbr

postprocess.limpar_cena()
bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=32, radius=0.8)
obj = bpy.context.active_object
while obj.data.uv_layers:
    obj.data.uv_layers.remove(obj.data.uv_layers[0])

# VertexColor traseiro/geral azul intenso (0.08, 0.22, 0.90)
ca = obj.data.color_attributes.new("Color", "FLOAT_COLOR", "POINT")
for i in range(len(obj.data.vertices)):
    ca.data[i].color = (0.08, 0.22, 0.90, 1.0)

res = bake_pbr.executar_bake_high_low(
    obj=obj,
    saida_dir={str(saida)!r},
    nome_base="proj_test",
    px=256,
    limite_triangulos=2000,
    reparo_fn=postprocess.reparar_malha,
    decimar_fn=postprocess.decimar,
    suavizar_fn=postprocess.suavizar_por_angulo,
    uv_fn=postprocess.desdobrar_uv,
    origem_textura={str(origem_png)!r},
    metallic_hint_png={str(met_png)!r},
    roughness_hint_png={str(rough_png)!r},
)

# Amostra UV nas faces frontais (+Y, +X e -X) e traseira (-Y) na malha low-poly assada
img_bc = bpy.data.images.load({str(saida / "proj_test_baseColor.png")!r}, check_existing=False)
img_orm = bpy.data.images.load({str(saida / "proj_test_orm.png")!r}, check_existing=False)
w_bc, h_bc = img_bc.size
w_o, h_o = img_orm.size
px_bc = list(img_bc.pixels)
px_orm = list(img_orm.pixels)

def sample_px(buf, w, h, u, v):
    x = max(0, min(w - 1, int(u * (w - 1))))
    y = max(0, min(h - 1, int(v * (h - 1))))
    idx = (y * w + x) * 4
    return (buf[idx], buf[idx+1], buf[idx+2])

amostras = {{"frente_esq": [], "frente_dir": [], "frente_topo": [], "tras": []}}
uv_layer = obj.data.uv_layers[0].data
for poly in obj.data.polygons:
    n = poly.normal
    c = poly.center
    u = sum(uv_layer[li].uv[0] for li in poly.loop_indices) / len(poly.loop_indices)
    v = sum(uv_layer[li].uv[1] for li in poly.loop_indices) / len(poly.loop_indices)
    rgb_bc = sample_px(px_bc, w_bc, h_bc, u, v)
    rgb_orm = sample_px(px_orm, w_o, h_o, u, v)
    if n.y > 0.7 and c.x > 0.25:
        amostras["frente_esq"].append(rgb_bc)
    elif n.y > 0.7 and c.x < -0.25:
        amostras["frente_dir"].append(rgb_bc)
    if n.y > 0.7 and c.z > 0.3:
        amostras["frente_topo"].append(rgb_orm)
    elif n.y < -0.7:
        amostras["tras"].append((rgb_bc, rgb_orm))

with open({str(meta_path)!r}, "w", encoding="utf-8") as fh:
    json.dump(res, fh)
with open({str(probe_path)!r}, "w", encoding="utf-8") as fh:
    json.dump(amostras, fh)
print("PROJ_BAKE_OK")
"""
    proc = _rodar_blender_py(codigo, timeout=180)
    assert proc.returncode == 0 and "PROJ_BAKE_OK" in proc.stdout, proc.stdout + proc.stderr

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["bake"]["origem_textura_aplicada"] is True
    assert meta["bake"]["metallic_hint_aplicado"] is True
    assert meta["bake"]["roughness_hint_aplicado"] is True

    amostras = json.loads(probe_path.read_text(encoding="utf-8"))
    assert amostras["frente_esq"] and amostras["frente_dir"] and amostras["tras"]

    # +X (lado esquerdo na visao +Y) deve ser vermelho; -X (lado direito) deve ser verde
    r_fe = sum(c[0] for c in amostras["frente_esq"]) / len(amostras["frente_esq"])
    g_fe = sum(c[1] for c in amostras["frente_esq"]) / len(amostras["frente_esq"])
    assert r_fe > g_fe + 0.3, (r_fe, g_fe)

    r_fd = sum(c[0] for c in amostras["frente_dir"]) / len(amostras["frente_dir"])
    g_fd = sum(c[1] for c in amostras["frente_dir"]) / len(amostras["frente_dir"])
    assert g_fd > r_fd + 0.3, (r_fd, g_fd)

    # Traseira (-Y) deve manter azul do VertexColor (nao projetado)
    b_tras = sum(item[0][2] for item in amostras["tras"]) / len(amostras["tras"])
    r_tras = sum(item[0][0] for item in amostras["tras"]) / len(amostras["tras"])
    assert b_tras > r_tras + 0.3, (b_tras, r_tras)

    # ORM frontal superior deve ter Metallic (B) > 0.5 e Roughness (G) baixa (~0.16)
    met_topo = sum(c[2] for c in amostras["frente_topo"]) / len(amostras["frente_topo"])
    rough_topo = sum(c[1] for c in amostras["frente_topo"]) / len(amostras["frente_topo"])
    assert met_topo > 0.5, met_topo
    assert rough_topo < 0.35, rough_topo

    # ORM traseiro deve cair no fallback dielectrico (Metallic ~ 0.0, Roughness AO >= 0.45)
    met_tras = sum(item[1][2] for item in amostras["tras"]) / len(amostras["tras"])
    rough_tras = sum(item[1][1] for item in amostras["tras"]) / len(amostras["tras"])
    assert met_tras < 0.1, met_tras
    assert rough_tras >= 0.45, rough_tras


@pytest.mark.blender
def test_decimar_protegido_preserva_mais_vertices_na_cabeca(tmp_path: Path):
    """decimar(..., proteger_cabeca_maos=True) preserva cabeca e limpa grupo temporario."""
    out_json = tmp_path / "decimate_cmp.json"
    codigo = f"""
import json, sys
sys.path.insert(0, {str(BLENDER_DIR)!r})
import bpy
import postprocess

postprocess.limpar_cena()
# Cria corpo composto subdividido (~5120 tris): esfera alongada Z in [0, 1.8]
bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=5, radius=1.0)
obj_prot = bpy.context.active_object
for v in obj_prot.data.vertices:
    v.co.z = (v.co.z + 1.0) * 0.9
obj_prot.data.update()

obj_unif = obj_prot.copy()
obj_unif.data = obj_prot.data.copy()
bpy.context.collection.objects.link(obj_unif)

head_antes = sum(1 for v in obj_prot.data.vertices if v.co.z >= 0.76 * 1.8)
tris_prot = postprocess.decimar(obj_prot, 2200, proteger_cabeca_maos=True)
tris_unif = postprocess.decimar(obj_unif, 2200, proteger_cabeca_maos=False)

head_prot = sum(1 for v in obj_prot.data.vertices if v.co.z >= 0.76 * 1.8)
head_unif = sum(1 for v in obj_unif.data.vertices if v.co.z >= 0.76 * 1.8)

assert "forge3d_decimate_peso" not in obj_prot.vertex_groups
with open({str(out_json)!r}, "w", encoding="utf-8") as fh:
    json.dump({{
        "head_antes": head_antes,
        "head_prot": head_prot,
        "head_unif": head_unif,
        "tris_prot": tris_prot,
        "tris_unif": tris_unif,
    }}, fh)
print("DECIMATE_CMP_OK")
"""
    proc = _rodar_blender_py(codigo, timeout=120)
    assert proc.returncode == 0 and "DECIMATE_CMP_OK" in proc.stdout, proc.stdout + proc.stderr

    res = json.loads(out_json.read_text(encoding="utf-8"))
    assert res["tris_prot"] <= 2200
    assert res["tris_unif"] <= 2200
    assert res["head_prot"] > res["head_unif"] * 1.5, res
    assert res["head_prot"] >= res["head_antes"] * 0.90, res


@pytest.mark.blender
@pytest.mark.lento
def test_postprocess_bruto_arquivo_com_uv_proj_hints_e_proteger_decimate(tmp_path: Path):
    """Pipeline completo bruto-arquivo@1 com origem_textura, hints ORM e proteger_decimate."""
    bruto = tmp_path / "bruto"
    final = tmp_path / "final"
    bruto.mkdir()
    final.mkdir()

    raw_glb = bruto / "modelo.glb"
    proc_raw = _rodar_blender_py(
        f"""
import bpy
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=4, radius=0.8)
o = bpy.context.active_object
for v in o.data.vertices:
    v.co.y *= 0.65
    v.co.z = (v.co.z + 0.8) * 1.1
o.data.update()
ca = o.data.color_attributes.new("Color", "FLOAT_COLOR", "POINT")
for i in range(len(o.data.vertices)):
    ca.data[i].color = (0.15, 0.25, 0.85, 1.0)
bpy.ops.export_scene.gltf(filepath={str(raw_glb)!r}, export_format="GLB")
"""
    )
    assert proc_raw.returncode == 0, proc_raw.stderr

    Image.new("RGB", (256, 256), (210, 60, 45)).save(bruto / "origem_delit.png")
    Image.new("L", (256, 256), 220).save(bruto / "metallic_hint.png")
    Image.new("L", (256, 256), 60).save(bruto / "roughness_hint.png")

    (bruto / "modelo.json").write_text(
        json.dumps(
            {
                "schema": "forge3d/bruto-arquivo@1",
                "arquivo": "modelo.glb",
                "canonicalizar": True,
                "textura_px": 256,
                "origem_textura": "origem_delit.png",
                "metallic_hint": "metallic_hint.png",
                "roughness_hint": "roughness_hint.png",
                "proteger_decimate": True,
                "pivos": {},
            }
        ),
        encoding="utf-8",
    )

    perfil = profiles.carregar("godot4")
    item = {
        "id": "personagem.proj.teste.01",
        "tipo": "personagem_humanoide",
        "rota": "mesh",
        "altura_metros": 1.80,
        "pivot": "base",
        "limite_triangulos": 800,
        "colisao": "convex",
        "lod": [100],
        "auto_rig": False,
        "tags": [],
    }
    job = {
        "bruto_dir": str(bruto),
        "bruto_arquivo": "modelo.json",
        "saida_dir": str(final),
        "saida_resultado": str(final / "resultado.json"),
        "perfil": plan.perfil_resolvido(perfil),
        "item": item,
        "nome_base": item["id"],
        "nome_arquivo": f"{item['id']}.glb",
    }
    res = post.executar(job)
    assert res["ok"] is True
    bake = res["medidas"]["gerada"]["bake"]
    assert bake["origem_textura_aplicada"] is True
    assert bake["metallic_hint_aplicado"] is True
    assert bake["roughness_hint_aplicado"] is True
    assert res["medidas"]["triangulos"] <= 800

    res["licenca"] = {"modelo": "procedural", "uso_comercial": True, "notice": "teste"}
    rel = qc.verificar(item, perfil, final, res)
    assert rel["aprovado"] is True, [g for g in rel["gates"] if g["status"] != "ok"]

    with Image.open(final / f"{item['id']}_orm.png") as im_orm:
        assert im_orm.getextrema()[2][1] > 150  # canal B (Metallic) > 0.5


@pytest.mark.blender
def test_extrude_2d_forma_diamante_curva_capa_e_hints_orm(tmp_path: Path):
    """Arma tem perfil lenticular (centro > borda), capa curva -0.12*x^2, e aceita hints ORM."""
    espada_png = tmp_path / "espada.png"
    im = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im)
    draw.polygon([(128, 12), (160, 80), (156, 230), (100, 230), (96, 80)], fill=(190, 200, 220, 255))
    im.save(espada_png)

    capa_png = tmp_path / "capa.png"
    imc = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    dc = ImageDraw.Draw(imc)
    dc.rectangle([(24, 24), (232, 232)], fill=(140, 20, 30, 255))
    imc.save(capa_png)

    met_png = tmp_path / "met.png"
    Image.new("L", (256, 256), 210).save(met_png)
    rough_png = tmp_path / "rough.png"
    Image.new("L", (256, 256), 70).save(rough_png)

    probe = tmp_path / "forma.json"
    saida_orm = tmp_path / "orm_out"
    saida_orm.mkdir()

    codigo = f"""
import json, sys
sys.path.insert(0, {str(BLENDER_DIR)!r})
import extrude_2d, postprocess, bake_pbr

postprocess.limpar_cena()
arma = extrude_2d.construir_malha_2d({str(espada_png)!r}, modo="arma", nome="arma")
ys_centro = [abs(v.co.y) for v in arma.data.vertices if abs(v.co.x) < 0.04 and 0.35 < v.co.z < 0.75]
ys_borda = [abs(v.co.y) for v in arma.data.vertices if abs(v.co.x) > 0.08 and 0.35 < v.co.z < 0.75]
res_h = bake_pbr.aplicar_hints_orm_em_material(
    arma, {str(saida_orm)!r}, "arma", 128,
    metallic_hint_png={str(met_png)!r},
    roughness_hint_png={str(rough_png)!r},
)

postprocess.limpar_cena()
capa = extrude_2d.construir_malha_2d({str(capa_png)!r}, modo="capa", nome="capa")
y_c = [v.co.y for v in capa.data.vertices if abs(v.co.x) < 0.05]
y_lat = [v.co.y for v in capa.data.vertices if abs(v.co.x) > 0.35]

with open({str(probe)!r}, "w", encoding="utf-8") as fh:
    json.dump({{
        "max_y_centro_arma": max(ys_centro),
        "max_y_borda_arma": max(ys_borda),
        "media_y_centro_capa": sum(y_c) / len(y_c),
        "media_y_lateral_capa": sum(y_lat) / len(y_lat),
        "orm_gerado": bool(res_h),
    }}, fh)
print("FORMA_OK")
"""
    proc = _rodar_blender_py(codigo, timeout=120)
    assert proc.returncode == 0 and "FORMA_OK" in proc.stdout, proc.stdout + proc.stderr

    info = json.loads(probe.read_text(encoding="utf-8"))
    assert info["max_y_centro_arma"] > info["max_y_borda_arma"] * 1.4, info
    assert info["media_y_lateral_capa"] < info["media_y_centro_capa"] - 0.01, info
    assert info["orm_gerado"] is True
    with Image.open(saida_orm / "arma_orm.png") as im_orm:
        assert im_orm.getextrema()[2][1] > 150


