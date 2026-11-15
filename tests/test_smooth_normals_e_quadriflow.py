"""Testes de smooth split normals, Quadriflow + COLOR_0, PBR procedural 3D, voxel-weld e turntable."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from forge3d import plan, post, profiles, qc

RAIZ = Path(__file__).resolve().parents[1]
BLENDER_DIR = RAIZ / "blender"

pytestmark = [pytest.mark.blender]


def test_custom_split_normals_organico_vs_hard_surface_e_orientacao_export(tmp_path):
    """Verifica custom split normals ponderadas por angulo (65 deg vs 38 deg) e metadados."""
    blender = post.binario()
    rel_json = tmp_path / "normals_rel.json"

    codigo = (
        "import json, sys, bpy\n"
        f"sys.path.insert(0, {str(BLENDER_DIR)!r})\n"
        "import postprocess\n"
        "bpy.ops.wm.read_factory_settings(use_empty=True)\n"
        "bpy.ops.mesh.primitive_cylinder_add(vertices=12, radius=0.5, depth=1.2)\n"
        "cyl = bpy.context.active_object\n"
        "info_org = postprocess.suavizar_por_angulo(cyl, angulo_graus=65.0)\n"
        "smooth_all = all(p.use_smooth for p in cyl.data.polygons)\n"
        "has_cn = bool(getattr(cyl.data, 'has_custom_normals', False))\n"
        "bpy.ops.mesh.primitive_cube_add(size=1.0)\n"
        "cubo = bpy.context.active_object\n"
        "info_hs = postprocess.suavizar_por_angulo(cubo, angulo_graus=38.0)\n"
        "wn = postprocess.aplicar_weighted_normal(cubo)\n"
        "cfg_org = postprocess._resolver_config_suavizacao({'tipo': 'criatura_alada'}, {})\n"
        "cfg_hs = postprocess._resolver_config_suavizacao({'tipo': 'prop_equipavel', 'item': {'parte': 'elmo'}}, {'armadura_modular': True})\n"
        f"open({str(rel_json)!r}, 'w').write(json.dumps({{\n"
        "    'info_org': info_org, 'smooth_all': smooth_all, 'has_cn': has_cn,\n"
        "    'info_hs': info_hs, 'wn': wn, 'cfg_org': cfg_org, 'cfg_hs': cfg_hs\n"
        "}))\n"
    )
    subprocess.run(
        [blender, "--background", "--factory-startup", "--python-expr", codigo],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    dados = json.loads(rel_json.read_text("utf-8"))
    assert dados["smooth_all"] is True
    assert dados["has_cn"] is True
    assert dados["info_org"]["custom_normals"] is True
    assert dados["info_org"]["angulo_graus"] == 65.0
    assert dados["info_org"]["arestas_vivas"] == 24  # tampas superior/inferior (90 deg > 65 deg), laterais (30 deg) suaves
    assert dados["info_hs"]["arestas_vivas"] == 12
    assert dados["wn"]["weighted_normal"] is True
    assert dados["cfg_org"]["angulo_graus"] == 65.0
    assert dados["cfg_hs"]["angulo_graus"] == 38.0


def test_quadriflow_com_color_0_e_material_procedural_pbr_bake(tmp_path):
    """Desbloqueia Quadriflow em malha com COLOR_0 + assa 10 presets procedurais (incluindo metal)."""
    blender = post.binario()
    bruto = tmp_path / "bruto_qf"
    final = tmp_path / "final_qf"
    bruto.mkdir()
    final.mkdir()
    esfera_glb = bruto / "esfera_high.glb"
    presets_json = tmp_path / "presets.json"

    codigo_setup = (
        "import json, sys, bpy\n"
        f"sys.path.insert(0, {str(BLENDER_DIR)!r})\n"
        "import procedural_pbr\n"
        "bpy.ops.wm.read_factory_settings(use_empty=True)\n"
        "nomes = []\n"
        "for p in procedural_pbr.MATERIAIS_PROCEDURAIS:\n"
        "    m = procedural_pbr.criar_material_procedural(p)\n"
        "    assert m.use_nodes\n"
        "    nomes.append(p)\n"
        f"open({str(presets_json)!r}, 'w').write(json.dumps(nomes))\n"
        "bpy.ops.wm.read_factory_settings(use_empty=True)\n"
        "bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=3, radius=0.6)\n"
        "obj = bpy.context.active_object\n"
        "ca = obj.data.color_attributes.new('Color', 'FLOAT_COLOR', 'POINT')\n"
        "for i, d in enumerate(ca.data):\n"
        "    d.color = (0.7, 0.25 + (i % 5) * 0.1, 0.2, 1.0)\n"
        f"bpy.ops.export_scene.gltf(filepath={str(esfera_glb)!r}, export_format='GLB')\n"
    )
    subprocess.run(
        [blender, "--background", "--factory-startup", "--python-expr", codigo_setup],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    presets = json.loads(presets_json.read_text("utf-8"))
    assert len(presets) == 10
    assert "aco_forjado" in presets and "escamas_dragao" in presets and "pele_humana" in presets

    (bruto / "modelo.json").write_text(
        json.dumps(
            {
                "schema": "forge3d/bruto-arquivo@1",
                "arquivo": "esfera_high.glb",
                "origem_nome": "esfera_high.glb",
                "canonicalizar": True,
                "retopologia": "quadriflow",
                "material_procedural": "aco_forjado",
                "textura_px": 64,
                "pivos": {},
            }
        ),
        encoding="utf-8",
    )
    item = {
        "id": "prop.aco.quadriflow.01",
        "tipo": "prop_equipavel",
        "rota": "mesh",
        "retopologia": "quadriflow",
        "material_procedural": "aco_forjado",
        "altura_metros": 1.0,
        "pivot": "base",
        "limite_triangulos": 1200,
        "colisao": "convex",
        "lod": [100],
        "auto_rig": False,
        "tags": [],
    }
    perfil = profiles.carregar("godot4")
    job = {
        "bruto_dir": str(bruto),
        "bruto_arquivo": "modelo.json",
        "saida_dir": str(final),
        "saida_resultado": str(final / "resultado.json"),
        "perfil": plan.perfil_resolvido(perfil),
        "item": item,
        "retopologia": "quadriflow",
        "material_procedural": "aco_forjado",
        "nome_base": item["id"],
        "nome_arquivo": f"{item['id']}.glb",
    }
    resultado = post.executar(job)
    assert resultado["ok"] is True
    assert resultado["sombreamento"]["smooth_normals"] is True
    assert resultado["sombreamento"]["quadriflow_aplicado"] is True
    assert resultado["orientacao_export"] == {
        "frente_gltf": "-Z",
        "cima_gltf": "+Y",
        "direita_gltf": "+X",
        "det_matriz": 1,
    }
    assert resultado["medidas"]["gerada"]["retopologia"] == "quadriflow"
    assert resultado["medidas"]["gerada"]["material_procedural"] == "aco_forjado"

    orm_png = final / f"{item['id']}_orm.png"
    base_png = final / f"{item['id']}_baseColor.png"
    norm_png = final / f"{item['id']}_normal.png"
    assert orm_png.is_file() and base_png.is_file() and norm_png.is_file()
    with Image.open(orm_png) as img_orm:
        # Canal B (Metallic) em aco_forjado deve ser > 100 (sem clamp em 0.0!)
        b_vals = list(img_orm.convert("RGB").getchannel("B").tobytes())
        assert max(b_vals) > 150

    resultado["licenca"] = {"modelo": "procedural", "uso_comercial": True, "notice": "teste"}
    rel_qc = qc.verificar(item, perfil, final, resultado)
    assert rel_qc["aprovado"] is True, [g for g in rel_qc["gates"] if g["status"] != "ok"]


def test_organic_sculpt_soldar_componentes_e_turntable_preview(tmp_path):
    """Testa soldagem voxel de primitivos organicos disjuntos e render_preview --turntable."""
    blender = post.binario()
    rel_weld = tmp_path / "weld.json"
    glb_path = tmp_path / "criatura_weld.glb"

    codigo_weld = (
        "import json, sys, bpy\n"
        f"sys.path.insert(0, {str(BLENDER_DIR)!r})\n"
        "import organic_sculpt, postprocess\n"
        "bpy.ops.wm.read_factory_settings(use_empty=True)\n"
        "bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=12, radius=0.45, location=(0, 0, 0.45))\n"
        "s1 = bpy.context.active_object\n"
        "bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=12, radius=0.35, location=(0, 0, 0.95))\n"
        "s2 = bpy.context.active_object\n"
        "bpy.ops.object.select_all(action='DESELECT')\n"
        "s1.select_set(True); s2.select_set(True)\n"
        "bpy.context.view_layer.objects.active = s1\n"
        "bpy.ops.object.join()\n"
        "ca = s1.data.color_attributes.new('Color', 'FLOAT_COLOR', 'POINT')\n"
        "for d in ca.data: d.color = (0.3, 0.65, 0.35, 1.0)\n"
        "info = organic_sculpt.soldar_componentes_organicos(s1, voxel_ratio=1.0/32.0, iteracoes_smooth=2)\n"
        "postprocess.suavizar_por_angulo(s1, angulo_graus=65.0)\n"
        f"bpy.ops.export_scene.gltf(filepath={str(glb_path)!r}, export_format='GLB')\n"
        f"open({str(rel_weld)!r}, 'w').write(json.dumps(info))\n"
    )
    subprocess.run(
        [blender, "--background", "--factory-startup", "--python-expr", codigo_weld],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    info = json.loads(rel_weld.read_text("utf-8"))
    assert info["executado"] is True
    assert info["componentes_antes"] == 2
    assert info["componentes_depois"] == 1
    assert glb_path.is_file()

    # Renderiza turntable 2x2 de baixa resolucao para QA rapido
    saida_base = tmp_path / "preview"
    subprocess.run(
        [
            blender,
            "--background",
            "--factory-startup",
            "--python",
            str(RAIZ / "tools" / "render_preview.py"),
            "--",
            str(glb_path),
            str(saida_base),
            "--size",
            "64",
            "--samples",
            "2",
            "--turntable",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    sheet_png = Path(f"{saida_base}_turntable.png")
    assert sheet_png.is_file()
    with Image.open(sheet_png) as img_t:
        assert img_t.size == (128, 160)
