"""Testes TDD independentes (@pytest.mark.blender, janela limpa) para v0.9.11 — Contrato C2c (projecao frontal em PBR nativo)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from forge3d import config, post

RAIZ = Path(__file__).resolve().parents[1]
_BLENDER_DIR = RAIZ / "blender"


@pytest.fixture(autouse=True)
def _isolar_forge3d(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORGE3D_HOME", str(tmp_path / "forge_home"))
    monkeypatch.setenv("FORGE3D_CONFIG", str(tmp_path / "forge_cfg"))
    config.adicionar(tmp_path)


def _exigir_blender() -> str:
    ok, _ = post.preflight()
    blender = post.binario() if ok else None
    if not blender:
        pytest.skip("Blender 4.2 nao disponivel neste ambiente")
    return blender


_C2C_BLENDER_SCRIPT = """
import json, sys, bpy, bmesh
from array import array

cfg = json.loads(open(sys.argv[-1], encoding="utf-8").read())
sys.path.insert(0, cfg["blender_dir"])
import bake_pbr_nativo_back as bnb_back, postprocess

postprocess.limpar_cena()
bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=1.0)
obj = bpy.context.active_object
obj.name = "esfera_front_proj"

bm = bmesh.new()
bm.from_mesh(obj.data)
bmesh.ops.triangulate(bm, faces=list(bm.faces))
bm.normal_update()
uv_lay = bm.loops.layers.uv.active or bm.loops.layers.uv.new("UVMap")
for f in bm.faces:
    ny = f.normal.y
    for lp in f.loops:
        co = lp.vert.co
        tx = max(0.0, min(1.0, (co.x + 1.0) / 2.0))
        tz = max(0.0, min(1.0, (co.z + 1.0) / 2.0))
        if ny > 0.25:
            lp[uv_lay].uv = (0.08 + tx * 0.34, 0.15 + tz * 0.70)
        elif ny < -0.25:
            lp[uv_lay].uv = (0.58 + tx * 0.34, 0.15 + tz * 0.70)
        else:
            lp[uv_lay].uv = (0.08 + tx * 0.84, 0.02 + tz * 0.08)
bm.to_mesh(obj.data)
bm.free()
obj.data.update()

px = 128
img_bc = bpy.data.images.new("esfera_front_bc", width=px, height=px, alpha=False)
img_bc.colorspace_settings.name = "sRGB"
img_bc.pixels.foreach_set(array("f", [40.0 / 255.0, 90.0 / 255.0, 210.0 / 255.0, 1.0] * (px * px)))
img_bc.filepath_raw = cfg["path_bc"]
img_bc.file_format = "PNG"
img_bc.save()

res_opaco = bnb_back.aplicar_vista_frontal_pbr_nativo(
    bpy.context.scene, obj, img_bc, cfg["path_bc"], px, "esfera_front", cfg["front_opaco_png"]
)
res_cutout = bnb_back.aplicar_vista_frontal_pbr_nativo(
    bpy.context.scene, obj, img_bc, cfg["path_bc"], px, "esfera_front", cfg["front_cutout_png"]
)
open(cfg["out_json"], "w", encoding="utf-8").write(json.dumps({"opaco": res_opaco, "cutout": res_cutout}))
"""


@pytest.mark.blender
def test_c2c_blender_aplicar_vista_frontal_pbr_nativo_projeta_frente_e_exige_alpha(tmp_path: Path) -> None:
    blender = _exigir_blender()
    front_cutout, front_opaco, path_bc = tmp_path / "front_cutout.png", tmp_path / "front_opaco.png", tmp_path / "bc.png"
    im_cut = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    ImageDraw.Draw(im_cut).rectangle((16, 16, 112, 112), fill=(45, 200, 70, 255))
    im_cut.save(front_cutout)
    Image.new("RGBA", (128, 128), (45, 200, 70, 255)).save(front_opaco)

    cfg_path, script_path, out_json = tmp_path / "cfg.json", tmp_path / "run_c2c.py", tmp_path / "out.json"
    cfg_path.write_text(json.dumps({"blender_dir": str(_BLENDER_DIR), "front_cutout_png": str(front_cutout), "front_opaco_png": str(front_opaco), "path_bc": str(path_bc), "out_json": str(out_json)}), encoding="utf-8")
    script_path.write_text(_C2C_BLENDER_SCRIPT, encoding="utf-8")
    proc = subprocess.run([blender, "--background", "--factory-startup", "--python-exit-code", "1", "--python", str(script_path), "--", str(cfg_path)], capture_output=True, text=True, timeout=180)
    assert proc.returncode == 0, f"Blender C2c falhou:\nSTDOUT={proc.stdout}\nSTDERR={proc.stderr}"
    dados = json.loads(out_json.read_text(encoding="utf-8"))

    assert dados["opaco"]["vista_front_aplicada"] is False and dados["opaco"].get("motivo") == "sem_alpha_cutout"
    res_c = dados["cutout"]
    assert res_c["vista_front_aplicada"] is True and int(res_c["pixels_mesclados"]) > 0
    assert 0.80 <= float(res_c["ganho_luminancia"]) <= 1.25

    with Image.open(path_bc) as im_bc:
        rgb = im_bc.convert("RGB")
        w, h = rgb.size
        front_gb = [rgb.getpixel((x, y))[1] - rgb.getpixel((x, y))[2] for y in range(int(h * 0.40), int(h * 0.60)) for x in range(int(w * 0.20), int(w * 0.30))]
        back_deltas = [max(abs(rgb.getpixel((x, y))[0] - 40), abs(rgb.getpixel((x, y))[1] - 90), abs(rgb.getpixel((x, y))[2] - 210)) for y in range(int(h * 0.40), int(h * 0.60)) for x in range(int(w * 0.70), int(w * 0.80))]
    assert (sum(front_gb) / float(len(front_gb))) > 20.0
    assert max(back_deltas) < 5
