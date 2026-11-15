"""Testes de anatomia 3D multicamadas CC0, empunhadura de dedos (grip/cupped) e sockets."""

from __future__ import annotations

import json
import os
import subprocess
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from forge3d import post, qc
from forge3d.errors import ForgeError
from forge3d.providers import mesh

RAIZ = Path(__file__).resolve().parents[1]


def _blender_bin() -> str:
    try:
        return post.binario()
    except ForgeError:
        pytest.skip("Blender 4.2 ausente neste ambiente")


def _tem_mpfb2() -> bool:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    cfg_root = Path(xdg) if xdg else (Path.home() / ".config")
    base = cfg_root / "blender" / "4.2" / "extensions"
    return base.is_dir() and any(base.glob("**/mpfb/__init__.py"))


def test_mesh_provider_versao_e_repassa_camadas_e_poses_maos(monkeypatch, tmp_path):
    assert mesh.VERSAO >= "0.1.9"
    prov = mesh.MeshProvider()
    monkeypatch.setattr(prov, "preflight_item", lambda _item: (True, "ok"))

    foto = tmp_path / "hero.png"
    Image.new("RGBA", (64, 128), (200, 155, 125, 255)).save(foto)
    jobs_vistos: list[dict] = []

    def fake_run(cmd, **_kwargs):
        if any("template_prep.py" in str(c) for c in cmd):
            out_dir = Path(cmd[cmd.index("--saida-dir") + 1])
            res_json = Path(cmd[cmd.index("--resultado") + 1])
            tex = out_dir / "input_template.png"
            Image.new("RGBA", (64, 128), (200, 155, 125, 255)).save(tex)
            res_json.write_text(
                json.dumps({"ok": True, "foto_template": str(tex), "marcos": {}}),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if any("template_body.py" in str(c) for c in cmd):
            job = json.loads(Path(cmd[-1]).read_text(encoding="utf-8"))
            jobs_vistos.append(job)
            out_dir = Path(job["saida"])
            (out_dir / "template_body.glb").write_bytes(b"glTF")
            Image.new("RGBA", (64, 64), (204, 168, 142, 255)).save(out_dir / "baseColor.png")
            (out_dir / "relatorio.json").write_text(
                json.dumps({"triangulos": 11500, "nao_manifold": 0, "template": "mpfb2 (CC0)"}),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(cmd, 0, "", "")
        raise AssertionError(f"Comando inesperado: {cmd}")

    monkeypatch.setattr(mesh.subprocess, "run", fake_run)
    prov.gerar(
        {
            "id": "hero.layers.01",
            "tipo": "personagem_humanoide",
            "parte": "corpo",
            "qualidade": "hero",
            "auto_rig": True,
            "limite_triangulos": 12000,
            "origem": str(foto),
        },
        {"perfil": "godot4", "material": {"textura_max": 1024}},
        tmp_path / "bruto_hero",
    )
    assert len(jobs_vistos) == 1
    job = jobs_vistos[0]
    assert job["projetar_foto_2d"] is False
    assert job["corpo_nu"] is False
    assert job["pose_mao_r"] == "grip"
    assert job["pose_mao_l"] == "cupped"
    assert job["limite_triangulos"] == 12000


@pytest.mark.blender
def test_extrator_idempotente_pacote_mpfb_cc0(tmp_path):
    blender = _blender_bin()
    cache_dir = tmp_path / "mpfb_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    zip_path = cache_dir / "makehuman_system_assets_cc0.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("skins/young_caucasian_male2/young_caucasian_male2_diffuse.png", b"PNG")
        zf.writestr("eyes/low-poly/low-poly.mhclo", "verts 0\n")
        zf.writestr("eyebrows/eyebrow001/eyebrow001.mhclo", "verts 0\n")
        zf.writestr("eyelashes/eyelash01/eyelash01.mhclo", "verts 0\n")
        zf.writestr("clothes/shoes01/shoes01.mhclo", "verts 0\n")
        zf.writestr("hair/short01/short01.mhclo", "verts 0\n")

    env = dict(os.environ)
    env["FORGE3D_MPFB_ASSETS"] = str(cache_dir)
    env["FORGE3D_MPFB_ASSETS_ZIP"] = str(zip_path)
    out_json = tmp_path / "ext_res.json"
    expr = (
        "import sys, json; sys.path.insert(0, 'blender'); import template_body; "
        "d1 = template_body._garantir_pacote_mpfb_extraido(); "
        "d2 = template_body._garantir_pacote_mpfb_extraido(); "
        "h = template_body._encontrar_mhclo_cabelo('short01'); "
        f"json.dump({{'d1': d1, 'd2': d2, 'hair': h}}, open({str(out_json)!r}, 'w'))"
    )
    proc = subprocess.run(
        [blender, "-b", "--factory-startup", "--python-expr", expr],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    res = json.loads(out_json.read_text(encoding="utf-8"))
    assert res["d1"] == res["d2"]
    ext_root = Path(res["d1"])
    assert (ext_root / "skins" / "young_caucasian_male2" / "young_caucasian_male2_diffuse.png").is_file()
    assert (ext_root / "eyes" / "low-poly" / "low-poly.mhclo").is_file()
    assert (ext_root / "clothes" / "shoes01" / "shoes01.mhclo").is_file()
    assert Path(res["hair"]).name == "short01.mhclo"


@pytest.mark.blender
def test_humanoide_camadas_cc0_g1_pele_natural_grip_e_sockets(tmp_path):
    blender = _blender_bin()
    if not _tem_mpfb2():
        pytest.skip("extensao MPFB2 nao instalada neste ambiente")

    saida = tmp_path / "hero_cc0"
    saida.mkdir(parents=True, exist_ok=True)
    res_json = tmp_path / "verificacao.json"
    script = tmp_path / "run_verify.py"
    script.write_text(
        f"""
import json
import os
import sys
import bpy

sys.path.insert(0, {str(RAIZ / "blender")!r})
import template_body
import autorig
import postprocess

saida = {str(saida)!r}
obj_open, rig_open, _ = template_body.criar_humano(dict(template_body.MACRO_PADRAO), {{}})
info_open = template_body.aplicar_pose_maos_mpfb(
    rig_open, pose_mao_r="open", pose_mao_l="open", compensar_rotacao_z=True
)
info_grip = template_body.aplicar_pose_maos_mpfb(
    rig_open, pose_mao_r="grip", pose_mao_l="cupped", compensar_rotacao_z=True
)

for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)

job = {{
    "saida": saida,
    "textura": 512,
    "limite_triangulos": 12000,
    "materiais_max": 8,
    "pose_mao_r": "grip",
    "pose_mao_l": "cupped",
}}
job_path = os.path.join(saida, "job.json")
with open(job_path, "w", encoding="utf-8") as f:
    json.dump(job, f)

sys.argv = ["blender", "--", job_path]
rc = template_body.main()
assert rc == 0

# Importa o template_body.glb exportado e roda auto_rigar_humanoide + extrair_sockets
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)
bpy.ops.import_scene.gltf(filepath=os.path.join(saida, "template_body.glb"))
meshes = [o for o in bpy.data.objects if o.type == "MESH"]
assert len(meshes) == 1
mesh_obj = meshes[0]
rig_auto, grupos = autorig.auto_rigar_humanoide(
    mesh_obj, "godot-humanoid@1", postprocess.criar_armadura
)
sockets = autorig.extrair_sockets(rig_auto, mesh_obj, ["Hand.R", "Hand.L", "Back"])

with open({str(res_json)!r}, "w", encoding="utf-8") as f:
    json.dump(
        {{
            "open_r": info_open["dist_ponta_palma_r_m"],
            "open_l": info_open["dist_ponta_palma_l_m"],
            "grip_r": info_grip["dist_ponta_palma_r_m"],
            "cupped_l": info_grip["dist_ponta_palma_l_m"],
            "sockets": sockets,
            "hand_r_head": list(rig_auto.data.bones["Hand.R"].head_local),
            "hand_l_head": list(rig_auto.data.bones["Hand.L"].head_local),
        }},
        f,
    )
""",
        encoding="utf-8",
    )

    proc = subprocess.run(
        [blender, "-b", "--python", str(script)],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout

    glb_path = saida / "template_body.glb"
    base_color_path = saida / "baseColor.png"
    rel_path = saida / "relatorio.json"
    assert glb_path.is_file()
    assert base_color_path.is_file()
    assert rel_path.is_file()

    rel = json.loads(rel_path.read_text(encoding="utf-8"))
    assert rel["nao_manifold"] == 0
    assert rel["degeneradas"] == 0
    assert rel["triangulos"] <= 12000
    assert rel["camadas_cc0"]["projetar_foto_2d"] is False

    # (a) Verifica G1 real (qc.topologia com soldagem 1e-5 m) e testa pele natural na testa
    gltf, binario = qc.ler_glb_bin(glb_path)
    topo = qc.topologia(gltf, binario)
    assert topo["nao_manifold"] == 0
    assert topo["degeneradas"] == 0
    assert topo["triangulos"] <= 12000
    nomes_mat = {m.get("name", "") for m in gltf.get("materials", [])}
    assert {"skin", "tunic", "leather", "metal"} <= nomes_mat

    img = Image.open(base_color_path).convert("RGB")
    w, h = img.size
    amostras_testa = [
        img.getpixel((int(u * w), int((1.0 - v) * h)))
        for u in (0.46, 0.50, 0.54)
        for v in (0.70, 0.73, 0.76)
    ]
    r_med = sum(p[0] for p in amostras_testa) / len(amostras_testa)
    g_med = sum(p[1] for p in amostras_testa) / len(amostras_testa)
    b_med = sum(p[2] for p in amostras_testa) / len(amostras_testa)
    assert r_med > 90.0 and g_med > 60.0 and b_med > 45.0, f"Testa escura/preta: {(r_med, g_med, b_med)}"
    assert r_med >= g_med >= b_med

    # (b) Verifica curvatura real dos dedos em grip e cupped vs mao aberta A-pose
    ver = json.loads(res_json.read_text(encoding="utf-8"))
    assert ver["grip_r"] < ver["open_r"] * 0.65
    assert ver["cupped_l"] < ver["open_l"] * 0.90
    assert ver["grip_r"] < ver["cupped_l"]

    # (c) Verifica extracao limpa de sockets Hand.R, Hand.L e Back + simetria L/R
    por_nome = {s["nome"]: s for s in ver["sockets"]}
    assert set(por_nome) == {"Hand.R", "Hand.L", "Back"}
    assert por_nome["Hand.R"]["osso"] == "Hand.R"
    assert por_nome["Hand.L"]["osso"] == "Hand.L"
    assert por_nome["Back"]["osso"] == "Chest"
    assert por_nome["Hand.R"]["frente_local"] == [0.0, 0.0, -1.0]
    assert por_nome["Hand.L"]["frente_local"] == [0.0, 0.0, -1.0]
    assert por_nome["Hand.R"]["posicao_local"][1] > 0.02
    assert por_nome["Hand.L"]["posicao_local"][1] > 0.02
    assert ver["hand_r_head"][0] < 0.0 and ver["hand_l_head"][0] > 0.0
    assert abs(ver["hand_r_head"][0] + ver["hand_l_head"][0]) < 1e-4
