"""Testes comportamentais independentes (@pytest.mark.blender, Sem Oraculo Comprado) para Onda 6 no Blender 4.2 headless."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from PIL import Image, ImageDraw

from forge3d import config, plan, post, profiles, qc

RAIZ = Path(__file__).resolve().parents[1]
_BLENDER_DIR = RAIZ / "blender"

_STAGING_GLBS: tuple[tuple[str, Path], ...] = (
    ("egg_dracorex_10", Path("/home/eudespatricio/.local/state/forge3d/staging/20261124T214422Z-0b7ade/egg.dracorex.10/bruto/modelo.glb")),
    ("relic_placa_de_ambar_04", Path("/home/eudespatricio/.local/state/forge3d/staging/20261124T205613Z-f6ea7a/relic.placa_de_ambar.04/bruto/modelo.glb")),
    ("relic_ovo_raro_de_gelo_05", Path("/home/eudespatricio/.local/state/forge3d/staging/20261124T210016Z-002329/relic.ovo_raro_de_gelo.05/bruto/modelo.glb")),
)


@pytest.fixture(autouse=True)
def _isolar_forge3d(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORGE3D_HOME", str(tmp_path / "forge_home"))
    monkeypatch.setenv("FORGE3D_CONFIG", str(tmp_path / "forge_cfg"))
    config.adicionar(tmp_path)


def _exigir_blender() -> str:
    try:
        ok, _ = post.preflight()
        blender = post.binario() if ok else None
    except Exception:
        blender = None
    if not blender:
        pytest.skip("Blender 4.2 nao disponivel neste ambiente")
    return blender


_ONDA6_SYNTH_BLENDER_SCRIPT = """
import json, os, sys, traceback
import bpy, bmesh
from array import array

cfg = json.loads(open(sys.argv[-1], encoding="utf-8").read())
sys.path.insert(0, cfg["blender_dir"])
import bake_pbr, bake_pbr_emissive, bake_pbr_heal, bake_pbr_nativo_back, postprocess

out = {}

def _medir_cobertura_uv_e_pretos(cena, obj, path_bc, path_orm, px, px_sub, prefixo):
    img_uv_bc = bake_pbr_heal.assar_mascara_ilhas_uv(cena, obj, px, f"{prefixo}_uv_bc")
    buf_uv_bc = array("f", [0.0] * (px * px * 4))
    img_uv_bc.pixels.foreach_get(buf_uv_bc)
    bpy.data.images.remove(img_uv_bc)

    img_bc_disk = bpy.data.images.load(path_bc, check_existing=False)
    buf_bc = array("f", [0.0] * (px * px * 4))
    img_bc_disk.pixels.foreach_get(buf_bc)
    bpy.data.images.remove(img_bc_disk)

    n_uv_bc = 0
    n_black = 0
    for u, r, g, b in zip(buf_uv_bc[0::4], buf_bc[0::4], buf_bc[1::4], buf_bc[2::4]):
        if u > 0.5:
            n_uv_bc += 1
            if r <= 0.02 and g <= 0.02 and b <= 0.02:
                n_black += 1

    img_uv_sub = bake_pbr_heal.assar_mascara_ilhas_uv(cena, obj, px_sub, f"{prefixo}_uv_sub")
    buf_uv_sub = array("f", [0.0] * (px_sub * px_sub * 4))
    img_uv_sub.pixels.foreach_get(buf_uv_sub)
    bpy.data.images.remove(img_uv_sub)

    img_orm_disk = bpy.data.images.load(path_orm, check_existing=False)
    buf_orm = array("f", [0.0] * (px_sub * px_sub * 4))
    img_orm_disk.pixels.foreach_get(buf_orm)
    bpy.data.images.remove(img_orm_disk)

    n_uv_sub = 0
    n_ao_zero = 0
    for u, ao in zip(buf_uv_sub[0::4], buf_orm[0::4]):
        if u > 0.5:
            n_uv_sub += 1
            if ao <= 0.461:
                n_ao_zero += 1

    return {
        "n_uv_bc": n_uv_bc, "n_black": n_black,
        "pure_black_uv": float(n_black) / float(max(1, n_uv_bc)),
        "n_uv_sub": n_uv_sub, "n_ao_zero": n_ao_zero,
        "ao_zero": float(n_ao_zero) / float(max(1, n_uv_sub)),
    }

# TEST 1: Spiky native-PBR sphere (tipo_item="prop_estatico")
try:
    postprocess.limpar_cena()
    bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=32, radius=0.60)
    obj_sp = bpy.context.active_object
    obj_sp.name = "spiky_prop"

    bm = bmesh.new()
    bm.from_mesh(obj_sp.data)
    bmesh.ops.triangulate(bm, faces=list(bm.faces))
    bm.normal_update()
    for idx, v in enumerate(bm.verts):
        if idx % 5 == 0:
            v.co = v.co + v.normal * 0.045
    bm.normal_update()
    bm.to_mesh(obj_sp.data)
    bm.free()
    obj_sp.data.update()

    mat_nat = bpy.data.materials.new("mat_spiky_nat")
    mat_nat.use_nodes = True
    nt = mat_nat.node_tree
    bsdf = nt.nodes.get("Principled BSDF")

    px_src = 64
    n_src = px_src * px_src
    img_bc_s = bpy.data.images.new("spiky_bc_src", width=px_src, height=px_src, alpha=False)
    img_bc_s.colorspace_settings.name = "sRGB"
    img_bc_s.pixels.foreach_set(array("f", [0.82, 0.52, 0.22, 1.0] * n_src))

    img_met_s = bpy.data.images.new("spiky_met_src", width=px_src, height=px_src, alpha=False)
    img_met_s.colorspace_settings.name = "Non-Color"
    img_met_s.pixels.foreach_set(array("f", [0.12, 0.12, 0.12, 1.0] * n_src))

    img_rough_s = bpy.data.images.new("spiky_rough_src", width=px_src, height=px_src, alpha=False)
    img_rough_s.colorspace_settings.name = "Non-Color"
    img_rough_s.pixels.foreach_set(array("f", [0.58, 0.58, 0.58, 1.0] * n_src))

    for inp_name, im_s in (("Base Color", img_bc_s), ("Metallic", img_met_s), ("Roughness", img_rough_s)):
        tn = nt.nodes.new("ShaderNodeTexImage")
        tn.image = im_s
        nt.links.new(tn.outputs["Color"], bsdf.inputs[inp_name])
    obj_sp.data.materials.append(mat_nat)

    px_t1, px_sub_t1 = 256, 128
    res_sp = bake_pbr.executar_bake_high_low(
        obj=obj_sp, saida_dir=cfg["spiky_dir"], nome_base="spiky_prop",
        px=px_t1, px_sub=px_sub_t1, limite_triangulos=500,
        reparo_fn=postprocess.reparar_malha, decimar_fn=postprocess.decimar,
        suavizar_fn=postprocess.suavizar_por_angulo, uv_fn=postprocess.desdobrar_uv,
        origem_textura=cfg["front_cutout_png"], proteger_superficie=True, tipo_item="prop_estatico",
    )
    med_sp = _medir_cobertura_uv_e_pretos(
        bpy.context.scene, obj_sp,
        os.path.join(cfg["spiky_dir"], "spiky_prop_baseColor.png"),
        os.path.join(cfg["spiky_dir"], "spiky_prop_orm.png"),
        px_t1, px_sub_t1, "spiky_prop",
    )
    out["test_spiky"] = {"ok": True, "res": res_sp, "med": med_sp}
except Exception:
    out["test_spiky"] = {"ok": False, "erro": traceback.format_exc()}

# TEST 2: Multi-material preservation (GAP-067 #1)
try:
    postprocess.limpar_cena()
    bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=16, radius=1.0)
    obj_mm = bpy.context.active_object
    obj_mm.name = "esfera_multimat"

    mat0 = bpy.data.materials.new("MatSlot0")
    mat0.use_nodes = True
    mat1 = bpy.data.materials.new("MatSlot1")
    mat1.use_nodes = True
    obj_mm.data.materials.append(mat0)
    obj_mm.data.materials.append(mat1)

    indices_orig = []
    for poly in obj_mm.data.polygons:
        idx_mat = 0 if poly.center.z >= 0.0 else 1
        poly.material_index = idx_mat
        indices_orig.append(idx_mat)

    px_mm = 128
    img_bc_mm = bpy.data.images.new("multimat_bc", width=px_mm, height=px_mm, alpha=False)
    img_bc_mm.colorspace_settings.name = "sRGB"
    img_bc_mm.pixels.foreach_set(array("f", [0.35, 0.45, 0.75, 1.0] * (px_mm * px_mm)))
    img_bc_mm.filepath_raw = cfg["mm_path_bc"]
    img_bc_mm.file_format = "PNG"
    img_bc_mm.save()

    res_front = bake_pbr_nativo_back.aplicar_vista_frontal_pbr_nativo(
        bpy.context.scene, obj_mm, img_bc_mm, cfg["mm_path_bc"], px_mm, "multimat", cfg["front_cutout_png"]
    )
    slots_pos_front = [m.name for m in obj_mm.data.materials if m is not None]
    indices_pos_front = [int(p.material_index) for p in obj_mm.data.polygons]
    img_bc_vivo_pos_front = (img_bc_mm.name in bpy.data.images) and (len(img_bc_mm.pixels) == px_mm * px_mm * 4)

    img_em_hint = bpy.data.images.load(cfg["em_hint_png"], check_existing=False)
    img_orig_mm = bpy.data.images.load(cfg["front_cutout_png"], check_existing=False)
    img_em_out, img_bc_ret, _em_ok = bake_pbr_emissive.assar_e_aplicar_emissive_uv0(
        bpy.context.scene, obj_mm, cfg["spiky_dir"], "multimat", px_mm, 64, img_em_hint, img_orig_mm, img_bc_mm, cfg["mm_path_bc"]
    )
    slots_pos_em = [m.name for m in obj_mm.data.materials if m is not None]
    indices_pos_em = [int(p.material_index) for p in obj_mm.data.polygons]
    img_bc_vivo_pos_em = (img_bc_ret is not None) and (img_bc_ret.name in bpy.data.images) and (len(img_bc_ret.pixels) == px_mm * px_mm * 4)

    out["test_multimat"] = {
        "ok": True, "res_front": res_front,
        "slots_pos_front": slots_pos_front, "slots_pos_em": slots_pos_em,
        "indices_preservados_front": (indices_pos_front == indices_orig),
        "indices_preservados_em": (indices_pos_em == indices_orig),
        "tem_ambos_slots": (0 in indices_orig and 1 in indices_orig),
        "img_bc_vivo_pos_front": img_bc_vivo_pos_front,
        "img_bc_vivo_pos_em": img_bc_vivo_pos_em,
        "emissive_gerado": img_em_out is not None,
    }
except Exception:
    out["test_multimat"] = {"ok": False, "erro": traceback.format_exc()}

open(cfg["out_json"], "w", encoding="utf-8").write(json.dumps(out))
"""


_ONDA6_STAGING_BLENDER_SCRIPT = """
import json, os, sys, traceback
import bpy
from array import array

cfg = json.loads(open(sys.argv[-1], encoding="utf-8").read())
sys.path.insert(0, cfg["blender_dir"])
import bake_pbr, bake_pbr_heal, postprocess

out = {}
px, px_sub = 1024, 512

for item_cfg in cfg["items"]:
    nome, glb_path, saida_dir = item_cfg["nome"], item_cfg["glb_path"], item_cfg["saida_dir"]
    os.makedirs(saida_dir, exist_ok=True)
    try:
        postprocess.limpar_cena()
        bpy.ops.import_scene.gltf(filepath=glb_path)
        malhas = [o for o in bpy.context.scene.objects if o.type == "MESH"]
        for m in malhas:
            bpy.context.view_layer.objects.active = m
            m.select_set(True)
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
        obj = postprocess.unir_malhas(malhas) if len(malhas) > 1 else malhas[0]
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)

        res_bake = bake_pbr.executar_bake_high_low(
            obj=obj, saida_dir=saida_dir, nome_base=nome,
            px=px, px_sub=px_sub, limite_triangulos=2500,
            reparo_fn=postprocess.reparar_malha, decimar_fn=postprocess.decimar,
            suavizar_fn=postprocess.suavizar_por_angulo, uv_fn=postprocess.desdobrar_uv,
            proteger_superficie=False, tipo_item="prop_estatico",
        )
        cena = bpy.context.scene
        img_uv_bc = bake_pbr_heal.assar_mascara_ilhas_uv(cena, obj, px, f"{nome}_uv_bc")
        buf_uv_bc = array("f", [0.0] * (px * px * 4))
        img_uv_bc.pixels.foreach_get(buf_uv_bc)
        bpy.data.images.remove(img_uv_bc)

        img_bc_disk = bpy.data.images.load(os.path.join(saida_dir, f"{nome}_baseColor.png"), check_existing=False)
        buf_bc = array("f", [0.0] * (px * px * 4))
        img_bc_disk.pixels.foreach_get(buf_bc)
        bpy.data.images.remove(img_bc_disk)

        n_uv_bc, n_black = 0, 0
        for u, r, g, b in zip(buf_uv_bc[0::4], buf_bc[0::4], buf_bc[1::4], buf_bc[2::4]):
            if u > 0.5:
                n_uv_bc += 1
                if r <= 0.02 and g <= 0.02 and b <= 0.02:
                    n_black += 1

        img_orm_disk = bpy.data.images.load(os.path.join(saida_dir, f"{nome}_orm.png"), check_existing=False)
        orm_w, orm_h = int(img_orm_disk.size[0]), int(img_orm_disk.size[1])
        buf_orm = array("f", [0.0] * (orm_w * orm_h * 4))
        img_orm_disk.pixels.foreach_get(buf_orm)
        bpy.data.images.remove(img_orm_disk)

        img_uv_sub = bake_pbr_heal.assar_mascara_ilhas_uv(cena, obj, orm_w, f"{nome}_uv_sub")
        buf_uv_sub = array("f", [0.0] * (orm_w * orm_h * 4))
        img_uv_sub.pixels.foreach_get(buf_uv_sub)
        bpy.data.images.remove(img_uv_sub)

        n_uv_sub, n_ao_zero = 0, 0
        for u, ao in zip(buf_uv_sub[0::4], buf_orm[0::4]):
            if u > 0.5:
                n_uv_sub += 1
                if ao <= 0.461:
                    n_ao_zero += 1

        out[nome] = {
            "ok": True, "n_uv_bc": n_uv_bc, "n_black": n_black,
            "pure_black_uv": float(n_black) / float(max(1, n_uv_bc)),
            "n_uv_sub": n_uv_sub, "n_ao_zero": n_ao_zero,
            "ao_zero": float(n_ao_zero) / float(max(1, n_uv_sub)),
            "bake": res_bake,
        }
    except Exception:
        out[nome] = {"ok": False, "erro": traceback.format_exc()}

open(cfg["out_json"], "w", encoding="utf-8").write(json.dumps(out))
"""


@pytest.mark.blender
def test_onda6_blender_spiky_ray_miss_heal_e_multimaterial_gap067(tmp_path: Path) -> None:
    blender = _exigir_blender()
    spiky_dir = tmp_path / "spiky_out"
    spiky_dir.mkdir()

    front_cutout = tmp_path / "front_cutout.png"
    im_cut = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    ImageDraw.Draw(im_cut).rectangle((20, 20, 108, 108), fill=(50, 205, 80, 255))
    im_cut.save(front_cutout)

    em_hint = tmp_path / "em_hint.png"
    im_em = Image.new("L", (128, 128), 0)
    ImageDraw.Draw(im_em).rectangle((40, 40, 88, 88), fill=245)
    im_em.save(em_hint)

    cfg_path, script_path, out_json = tmp_path / "cfg_onda6.json", tmp_path / "run_onda6_synth.py", tmp_path / "out_onda6.json"
    cfg_path.write_text(
        json.dumps({
            "blender_dir": str(_BLENDER_DIR), "spiky_dir": str(spiky_dir),
            "front_cutout_png": str(front_cutout), "em_hint_png": str(em_hint),
            "mm_path_bc": str(tmp_path / "multimat_bc.png"), "out_json": str(out_json),
        }),
        encoding="utf-8",
    )
    script_path.write_text(_ONDA6_SYNTH_BLENDER_SCRIPT, encoding="utf-8")

    proc = subprocess.run(
        [blender, "--background", "--factory-startup", "--python-exit-code", "1", "--python", str(script_path), "--", str(cfg_path)],
        capture_output=True, text=True, timeout=240,
    )
    assert proc.returncode == 0, f"Blender Onda 6 synth falhou:\nSTDOUT={proc.stdout}\nSTDERR={proc.stderr}"
    dados: dict[str, Any] = json.loads(out_json.read_text(encoding="utf-8"))

    sp = dados["test_spiky"]
    assert sp["ok"] is True, sp.get("erro")
    med_sp, res_sp = sp["med"], sp["res"]
    bake_sp = res_sp["bake"]
    assert med_sp["n_uv_bc"] > 1000 and med_sp["n_uv_sub"] > 250
    assert float(med_sp["pure_black_uv"]) < 0.005, f"pure_black_uv >= 0.5%: {med_sp}"
    assert float(med_sp["ao_zero"]) < 0.02, f"ao_zero >= 2.0%: {med_sp}"
    assert "ray_miss_heal" in bake_sp, f"ray_miss_heal ausente no bake dict: {bake_sp}"
    vf = bake_sp.get("vista_front_nativo") or {}
    assert vf.get("vista_front_aplicada") is False and vf.get("motivo") == "ignorado_hard_surface", vf

    mm = dados["test_multimat"]
    assert mm["ok"] is True, mm.get("erro")
    assert mm["tem_ambos_slots"] is True
    assert mm["slots_pos_front"] == ["MatSlot0", "MatSlot1"] and mm["slots_pos_em"] == ["MatSlot0", "MatSlot1"]
    assert mm["indices_preservados_front"] is True and mm["indices_preservados_em"] is True
    assert mm["img_bc_vivo_pos_front"] is True and mm["img_bc_vivo_pos_em"] is True and mm["emissive_gerado"] is True


@pytest.mark.blender
def test_onda6_blender_extrude_2d_com_emissive_hint_gap052(tmp_path: Path) -> None:
    _exigir_blender()
    bruto_arma, final_arma = tmp_path / "bruto_arma_em", tmp_path / "final_arma_em"
    bruto_arma.mkdir()
    final_arma.mkdir()

    espada_png = bruto_arma / "espada.png"
    im = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im)
    draw.polygon([(128, 12), (144, 48), (141, 170), (115, 170), (112, 48)], fill=(200, 215, 230, 255))
    draw.rectangle([(88, 170), (168, 185)], fill=(215, 175, 55, 255))
    draw.rectangle([(121, 185), (135, 232)], fill=(115, 65, 30, 255))
    im.save(espada_png)

    em_png = bruto_arma / "emissive_hint.png"
    im_em = Image.new("L", (256, 256), 0)
    ImageDraw.Draw(im_em).rectangle([(122, 55), (134, 155)], fill=250)
    im_em.save(em_png)

    (bruto_arma / "modelo.json").write_text(
        json.dumps({"schema": "forge3d/bruto-extrude@1", "imagem": "espada.png", "modo": "arma", "emissive_hint": "emissive_hint.png"}),
        encoding="utf-8",
    )
    perfil = profiles.carregar("godot4")
    item_arma = {
        "id": "prop.espada.emissive.01", "tipo": "prop_equipavel", "rota": "mesh", "parte": "arma",
        "altura_metros": 1.10, "pivot": "empunhadura", "limite_triangulos": 800,
        "colisao": "convex", "lod": [100], "auto_rig": False, "tags": [],
    }
    job_arma = {
        "bruto_dir": str(bruto_arma), "bruto_arquivo": "modelo.json",
        "saida_dir": str(final_arma), "saida_resultado": str(final_arma / "resultado.json"),
        "perfil": plan.perfil_resolvido(perfil), "item": item_arma,
        "nome_base": item_arma["id"], "nome_arquivo": f"{item_arma['id']}.glb",
    }
    res_arma = post.executar(job_arma)
    assert res_arma["ok"] is True
    assert "emissive" not in {a["papel"] for a in res_arma.get("arquivos", [])}
    arquivos_tex_bake = res_arma.get("medidas", {}).get("bake", {}).get("arquivos_textura", [])
    assert "emissive" not in {a["papel"] for a in arquivos_tex_bake}

    gltf = qc.ler_glb(final_arma / f"{item_arma['id']}.glb")
    mats = gltf.get("materials", [])
    assert mats and "emissiveTexture" in mats[0], f"emissiveTexture ausente no GLB extrude_2d: {mats}"


@pytest.mark.blender
@pytest.mark.skipif(
    not all(p.is_file() for _, p in _STAGING_GLBS),
    reason="Arquivos reais de staging (egg.dracorex.10 / relic.placa_de_ambar.04 / relic.ovo_raro_de_gelo.05) ausentes",
)
def test_onda6_blender_regressao_staging_real_tres_glbs(tmp_path: Path) -> None:
    blender = _exigir_blender()
    items_cfg = [{"nome": nome, "glb_path": str(caminho), "saida_dir": str(tmp_path / nome)} for nome, caminho in _STAGING_GLBS]
    cfg_path, script_path, out_json = tmp_path / "cfg_staging.json", tmp_path / "run_onda6_staging.py", tmp_path / "out_staging.json"
    cfg_path.write_text(json.dumps({"blender_dir": str(_BLENDER_DIR), "items": items_cfg, "out_json": str(out_json)}), encoding="utf-8")
    script_path.write_text(_ONDA6_STAGING_BLENDER_SCRIPT, encoding="utf-8")

    proc = subprocess.run(
        [blender, "--background", "--factory-startup", "--python-exit-code", "1", "--python", str(script_path), "--", str(cfg_path)],
        capture_output=True, text=True, timeout=600,
    )
    assert proc.returncode == 0, f"Blender staging real falhou:\nSTDOUT={proc.stdout}\nSTDERR={proc.stderr}"
    dados: dict[str, Any] = json.loads(out_json.read_text(encoding="utf-8"))

    for nome, _ in _STAGING_GLBS:
        info = dados[nome]
        assert info["ok"] is True, f"Falha no staging {nome}: {info.get('erro')}"
        assert info["n_uv_bc"] > 10_000 and info["n_uv_sub"] > 2_500
        assert float(info["pure_black_uv"]) < 0.005, f"{nome}: pure_black_uv={info['pure_black_uv']:.4%} >= 0.5%"
        assert float(info["ao_zero"]) < 0.02, f"{nome}: ao_zero={info['ao_zero']:.4%} >= 2.0%"
