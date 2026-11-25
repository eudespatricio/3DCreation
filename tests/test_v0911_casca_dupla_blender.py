"""Testes TDD independentes (@pytest.mark.blender, janela limpa) para v0.9.11 — Contrato C2b (casca dupla)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from PIL import Image

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


_C2B_BLENDER_SCRIPT = """
import json, sys, bpy, bmesh
from array import array

cfg = json.loads(open(sys.argv[-1], encoding="utf-8").read())
sys.path.insert(0, cfg["blender_dir"])
import bake_pbr, postprocess

def criar_material_pbr_nativo(nome):
    mat = bpy.data.materials.new(nome)
    mat.use_nodes = True
    nt, bsdf, px_s = mat.node_tree, mat.node_tree.nodes.get("Principled BSDF"), 32
    n_px = px_s * px_s
    for sufixo, cs, rgba, inp in (
        ("bc", "sRGB", [0.68, 0.42, 0.14, 1.0], "Base Color"),
        ("r", "Non-Color", [0.75, 0.75, 0.75, 1.0], "Roughness"),
        ("m", "Non-Color", [0.0, 0.0, 0.0, 1.0], "Metallic"),
    ):
        im = bpy.data.images.new(f"{nome}_{sufixo}", width=px_s, height=px_s, alpha=False)
        im.colorspace_settings.name = cs
        im.pixels.foreach_set(array("f", rgba * n_px))
        tn = nt.nodes.new("ShaderNodeTexImage")
        tn.image = im
        nt.links.new(tn.outputs["Color"], bsdf.inputs[inp])
    return mat

def construir_esfera_bake(nome, dupla_casca, saida_dir):
    postprocess.limpar_cena()
    mat = criar_material_pbr_nativo(f"mat_{nome}")
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=1.5)
    low_obj = bpy.context.active_object
    low_mesh = low_obj.data.copy()
    bpy.data.objects.remove(low_obj, do_unlink=True)
    bpy.ops.mesh.primitive_uv_sphere_add(segments=40, ring_count=20, radius=1.5)
    obj = bpy.context.active_object
    obj.name = nome
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.triangulate(bm, faces=list(bm.faces))
    bm.normal_update()
    if dupla_casca:
        dup = bmesh.ops.duplicate(bm, geom=list(bm.verts) + list(bm.edges) + list(bm.faces))
        for v in (g for g in dup["geom"] if isinstance(g, bmesh.types.BMVert)):
            v.co = v.co - v.normal * 0.002
        bmesh.ops.reverse_faces(bm, faces=[g for g in dup["geom"] if isinstance(g, bmesh.types.BMFace)])
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
    obj.data.materials.append(mat)
    def decimar_swap(alvo, _lim):
        if alvo is obj and obj.data is not low_mesh:
            obj.data = low_mesh
        return postprocess.malha_triangulada(alvo)
    return bake_pbr.executar_bake_high_low(
        obj=obj, saida_dir=saida_dir, nome_base=nome, px=128, px_sub=128,
        limite_triangulos=2000, reparo_fn=lambda _o: {}, decimar_fn=decimar_swap,
        suavizar_fn=postprocess.suavizar_por_angulo,
        uv_fn=lambda o: o.data.uv_layers[0].name, proteger_superficie=True,
    )

out = {
    "dupla": construir_esfera_bake("esfera_dupla", True, cfg["dir_dupla"]),
    "simples": construir_esfera_bake("esfera_simples", False, cfg["dir_simples"]),
}
open(cfg["out_json"], "w", encoding="utf-8").write(json.dumps(out))
"""


@pytest.mark.blender
def test_c2b_blender_bake_remove_casca_interna_invertida_e_preserva_casca_simples(tmp_path: Path) -> None:
    blender = _exigir_blender()
    dir_dupla, dir_simples = tmp_path / "dupla", tmp_path / "simples"
    dir_dupla.mkdir()
    dir_simples.mkdir()
    cfg_path, script_path, out_json = tmp_path / "cfg.json", tmp_path / "run_c2b.py", tmp_path / "out.json"
    cfg_path.write_text(json.dumps({"blender_dir": str(_BLENDER_DIR), "dir_dupla": str(dir_dupla), "dir_simples": str(dir_simples), "out_json": str(out_json)}), encoding="utf-8")
    script_path.write_text(_C2B_BLENDER_SCRIPT, encoding="utf-8")
    proc = subprocess.run([blender, "--background", "--factory-startup", "--python-exit-code", "1", "--python", str(script_path), "--", str(cfg_path)], capture_output=True, text=True, timeout=180)
    assert proc.returncode == 0, f"Blender C2b falhou:\nSTDOUT={proc.stdout}\nSTDERR={proc.stderr}"
    dados = json.loads(out_json.read_text(encoding="utf-8"))
    bake_d = dados["dupla"]["bake"]
    assert "casca_interna_removida" in bake_d, f"casca_interna_removida ausente em bake: {bake_d.keys()}"
    casca_d = bake_d["casca_interna_removida"]
    tot_faces = int(casca_d["faces_removidas"]) + int(casca_d["faces_restantes"])
    assert casca_d["aplicado"] is True and tot_faces > 0 and int(casca_d["faces_removidas"]) >= 0.40 * tot_faces

    def metricas_bake(pasta: Path, prefixo: str) -> tuple[float, float, float]:
        with Image.open(pasta / f"{prefixo}_baseColor.png") as im_bc, Image.open(pasta / f"{prefixo}_orm.png") as im_orm, Image.open(pasta / f"{prefixo}_normal.png") as im_nm:
            bc_px, orm_px, nm_px = list(im_bc.getdata()), list(im_orm.getdata()), list(im_nm.getdata())
        ativos = [i for i, rgb in enumerate(bc_px) if (max(rgb[:3]) / 255.0) > 0.05]
        assert len(ativos) >= 500
        aos, nzs = sorted(orm_px[i][0] / 255.0 for i in ativos), sorted(nm_px[i][2] / 255.0 for i in ativos)
        return aos[len(aos) // 2], sum(1 for a in aos if a < 0.50) / float(len(aos)), nzs[int(0.05 * (len(nzs) - 1))]

    ao_med_d, frac_low_d, nz_p05_d = metricas_bake(dir_dupla, "esfera_dupla")
    _ao_med_s, frac_low_s, _nz_p05_s = metricas_bake(dir_simples, "esfera_simples")
    assert ao_med_d >= 0.85 and frac_low_d < 0.05 and nz_p05_d >= 0.85 and frac_low_d <= frac_low_s + 0.01
    casca_s = dados["simples"]["bake"]["casca_interna_removida"]
    assert casca_s["aplicado"] is False and int(casca_s["faces_removidas"]) == 0
