"""Testes do Gate G11 por primitiva/superficie e do medidor real Godot 4.x."""

from __future__ import annotations

import importlib.util
import io
import json
import struct
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from forge3d import canonical, pipeline, profiles, publish, qc

RAIZ = Path(__file__).resolve().parents[1]


def _carregar_modulo_medidor():
    caminho = RAIZ / "tools" / "medir_draw_calls_godot.py"
    spec_mod = importlib.util.spec_from_file_location("medir_draw_calls_godot", caminho)
    assert spec_mod and spec_mod.loader
    mod = importlib.util.module_from_spec(spec_mod)
    spec_mod.loader.exec_module(mod)
    return mod


def _glb_multi_primitivas(num_prims: int, altura: float = 1.0) -> bytes:
    """Constroi um cubo fechado dividido em ``num_prims`` primitivas/materiais distintos."""
    hx, hz = 0.25, 0.25
    faces = [
        [(-hx, 0.0, -hz), (-hx, altura, -hz), (hx, altura, -hz), (hx, 0.0, -hz)],
        [(-hx, 0.0, hz), (hx, 0.0, hz), (hx, altura, hz), (-hx, altura, hz)],
        [(-hx, 0.0, -hz), (hx, 0.0, -hz), (hx, 0.0, hz), (-hx, 0.0, hz)],
        [(-hx, altura, -hz), (-hx, altura, hz), (hx, altura, hz), (hx, altura, -hz)],
        [(-hx, 0.0, -hz), (-hx, 0.0, hz), (-hx, altura, hz), (-hx, altura, -hz)],
        [(hx, 0.0, -hz), (hx, altura, -hz), (hx, altura, hz), (hx, 0.0, hz)],
    ]
    verts, tris_base, uvs = [], [], []
    du, dv, pad = 0.9 / 3.0, 0.9 / 2.0, 0.02
    for k, q in enumerate(faces):
        b = len(verts)
        verts.extend(q)
        tris_base.extend([(b, b + 1, b + 2), (b, b + 2, b + 3)])
        cu, cv = 0.05 + (k % 3) * du, 0.05 + (k // 3) * dv
        uvs.extend([(cu + pad, cv + pad), (cu + du - pad, cv + pad), (cu + du - pad, cv + dv - pad), (cu + pad, cv + dv - pad)])

    n_prims = max(1, min(num_prims, len(tris_base)))
    fatias: list[list[tuple[int, int, int]]] = [[] for _ in range(n_prims)]
    for idx_t, tri in enumerate(tris_base):
        fatias[idx_t % n_prims].append(tri)

    pos_bytes = b"".join(struct.pack("<3f", *v) for v in verts)
    norm_bytes = b"".join(struct.pack("<3f", 0.0, 1.0, 0.0) for _ in verts)
    uv_bytes = b"".join(struct.pack("<2f", *uv) for uv in uvs)

    buf = bytearray()
    bvs: list[dict] = []
    accs: list[dict] = []

    def _add_bv(raw: bytes, target: int) -> int:
        while len(buf) % 4 != 0:
            buf.append(0)
        off = len(buf)
        buf.extend(raw)
        bvs.append({"buffer": 0, "byteOffset": off, "byteLength": len(raw), "target": target})
        return len(bvs) - 1

    bv_pos = _add_bv(pos_bytes, 34962)
    bv_norm = _add_bv(norm_bytes, 34962)
    bv_uv = _add_bv(uv_bytes, 34962)
    accs.append(
        {
            "bufferView": bv_pos,
            "componentType": 5126,
            "count": len(verts),
            "type": "VEC3",
            "min": [-hx, 0.0, -hz],
            "max": [hx, altura, hz],
        }
    )
    accs.append({"bufferView": bv_norm, "componentType": 5126, "count": len(verts), "type": "VEC3"})
    accs.append({"bufferView": bv_uv, "componentType": 5126, "count": len(verts), "type": "VEC2"})

    prims_gltf: list[dict] = []
    mats_gltf: list[dict] = []
    for s_idx, tris_s in enumerate(fatias):
        idx_raw = b"".join(struct.pack("<3H", *t) for t in tris_s)
        bv_idx = _add_bv(idx_raw, 34963)
        acc_idx = len(accs)
        accs.append(
            {
                "bufferView": bv_idx,
                "componentType": 5123,
                "count": len(tris_s) * 3,
                "type": "SCALAR",
            }
        )
        prims_gltf.append(
            {
                "attributes": {"POSITION": 0, "NORMAL": 1, "TEXCOORD_0": 2},
                "indices": acc_idx,
                "material": s_idx,
            }
        )
        mats_gltf.append(
            {
                "name": f"mat_{s_idx}",
                "pbrMetallicRoughness": {
                    "baseColorFactor": [0.7, 0.7, 0.75, 1.0],
                    "baseColorTexture": {"index": 0},
                },
            }
        )

    while len(buf) % 4 != 0:
        buf.append(0)
    png_buf = io.BytesIO()
    Image.new("RGB", (32, 32), (180, 180, 190)).save(png_buf, format="PNG")
    img_bytes = png_buf.getvalue()
    img_off = len(buf)
    buf.extend(img_bytes)
    bvs.append({"buffer": 0, "byteOffset": img_off, "byteLength": len(img_bytes)})
    img_bv = len(bvs) - 1
    while len(buf) % 4 != 0:
        buf.append(0)

    gltf = {
        "asset": {"version": "2.0"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"name": "multi_prim_node", "mesh": 0}],
        "meshes": [{"primitives": prims_gltf}],
        "images": [{"bufferView": img_bv, "mimeType": "image/png"}],
        "textures": [{"source": 0}],
        "materials": mats_gltf,
        "accessors": accs,
        "bufferViews": bvs,
        "buffers": [{"byteLength": len(buf)}],
    }
    json_b = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    while len(json_b) % 4 != 0:
        json_b += b" "
    total = 12 + 8 + len(json_b) + 8 + len(buf)
    return (
        struct.pack("<III", 0x46546C67, 2, total)
        + struct.pack("<II", len(json_b), 0x4E4F534A)
        + json_b
        + struct.pack("<II", len(buf), 0x004E4942)
        + bytes(buf)
    )


def test_g11_conta_draw_calls_por_primitiva_skinned_e_instanciado():
    """Regressao calibrada contra v09_aa_godot: 8 prims skinned + 4 prims estaticos = 24 draw calls (nao 7)."""
    itens = [
        {"id": "hero.01", "tris": 15872, "primitivas": 8, "quantidade_cena": 2, "skinned": True},
        {"id": "gauntlets.01", "tris": 2486, "primitivas": 1, "quantidade_cena": 2, "skinned": True},
        {"id": "sword.01", "tris": 1430, "primitivas": 4, "quantidade_cena": 4, "skinned": False, "material_key": "pbr:sword"},
        {"id": "fern.01", "tris": 116, "primitivas": 1, "quantidade_cena": 16, "skinned": False, "material_key": "pbr:fern"},
        {"id": "altar.01", "tris": 136, "primitivas": 1, "quantidade_cena": 6, "skinned": False, "material_key": "pbr:altar"},
    ]
    res = qc.verificar_g11_orcamento_cena(itens)
    assert res["status"] == "ok"
    assert res["medido"]["triangulos_cena"] == 45108
    # 2*8 + 2*1 = 18 skinned; 4 + 1 + 1 = 6 lotes instanciados -> 24 draw calls
    assert res["medido"]["lotes_instanciados"] == 6
    assert res["medido"]["draw_calls_estimados"] == 24

    # Estouro de draw calls por multi-superficie skinned (60 copias * 8 prims = 480 > 400) reprova G11!
    estouro = qc.verificar_g11_orcamento_cena(
        [{"id": "crowd.hero", "tris": 1000, "primitivas": 8, "quantidade_cena": 60, "skinned": True}],
        limite_cena={"triangulos_max": 400000, "draw_calls_max": 400, "vram_mb_max": 200},
    )
    assert estouro["status"] == "falhou"
    assert estouro["codigo"] == "FORGE-E-QC-SCENE"
    assert estouro["medido"]["draw_calls_estimados"] == 480


def test_pipeline_medir_item_g11_propaga_primitivas_do_qc(tmp_path):
    glb_4 = _glb_multi_primitivas(4)
    p_glb = tmp_path / "prop.multi.01.glb"
    p_glb.write_bytes(glb_4)
    perfil = profiles.carregar("godot4-aa")
    item = {
        "id": "prop.multi.01",
        "tipo": "prop_estatico",
        "rota": "blocky",
        "altura_metros": 1.0,
        "pivot": "base",
        "limite_triangulos": 500,
        "colisao": "none",
        "quantidade_cena": 5,
        "material": "pbr",
    }
    res_post = {
        "medidas": {"nao_manifold": 0, "degeneradas": 0, "partes_colisao": 0},
        "arquivos": [{"caminho": "prop.multi.01.glb", "papel": "mesh", "nivel": 0, "triangulos": 12}],
        "licenca": {"modelo": "MIT", "uso_comercial": True},
    }
    rel_qc = qc.verificar(item, perfil, tmp_path, res_post)
    assert rel_qc["aprovado"] is True
    assert rel_qc["medidas"]["primitivas"] == 4

    med_item = pipeline._medir_item_g11(
        item,
        {
            "origem": tmp_path,
            "resultado": res_post,
            "relatorio_qc": rel_qc,
            "manifesto": {},
        },
    )
    assert med_item["primitivas"] == 4
    g11 = qc.verificar_g11_orcamento_cena([med_item])
    assert g11["medido"]["draw_calls_estimados"] == 4


def test_medidor_recusa_ambiente_sem_display_nem_xvfb(monkeypatch):
    mod = _carregar_modulo_medidor()
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setattr(mod.shutil, "which", lambda _cmd: None)
    assert mod.detectar_display() is None


def test_medidor_godot_real_vs_headless_dummy(tmp_path):
    """Prova no Godot 4.x que --headless retorna 0 draw calls (dummy) e driver real mede superficies."""
    mod = _carregar_modulo_medidor()
    godot_bin = mod.localizar_godot()
    disp = mod.detectar_display()
    if godot_bin is None or disp is None:
        pytest.skip("Godot 4.x ou servidor grafico indisponivel no ambiente")

    glb_bytes = _glb_multi_primitivas(4, altura=1.0)
    glb_path = tmp_path / "prop.quatro.01.glb"
    glb_path.write_bytes(glb_bytes)

    perfil = profiles.carregar("godot4-aa")
    item = {
        "id": "prop.quatro.01",
        "tipo": "prop_estatico",
        "rota": "blocky",
        "altura_metros": 1.0,
        "pivot": "base",
        "limite_triangulos": 500,
        "colisao": "none",
        "quantidade_cena": 3,
        "material": "pbr",
    }
    res_post = {
        "medidas": {"nao_manifold": 0, "degeneradas": 0, "partes_colisao": 0},
        "arquivos": [
            {
                "caminho": "prop.quatro.01.glb",
                "papel": "mesh",
                "nivel": 0,
                "triangulos": 12,
                "sha256": canonical.sha256_arquivo(glb_path),
                "bytes": len(glb_bytes),
            }
        ],
        "licenca": {"modelo": "MIT", "uso_comercial": True, "notice": "teste"},
        "determinism": "D1",
    }
    rel_qc = qc.verificar(item, perfil, tmp_path, res_post)
    man = publish.montar_manifesto(
        item=item,
        spec_doc={"projeto": "bench_test", "perfil": "godot4-aa", "_arquivo": "t.yaml"},
        spec_hash="sha256:" + "0" * 64,
        perfil_nome="godot4-aa",
        perfil=perfil,
        provider={"nome": "blocky", "versao": "0.9.0", "determinism": "D1"},
        resultado=res_post,
        relatorio_qc=rel_qc,
        licenca={"modelo": "MIT", "uso_comercial": True, "notice": "teste"},
        run_id="run-bench",
    )
    (tmp_path / "prop.quatro.01.manifest.json").write_text(json.dumps(man), encoding="utf-8")

    # 1. Verifica empiricamente que --headless usa driver dummy -> 0 draw calls
    in_dummy = tmp_path / "in_dummy.json"
    out_dummy = tmp_path / "out_dummy.json"
    in_dummy.write_text(
        json.dumps({"mode": "naive", "shadows": False, "items": [{"id": "p", "glb": str(glb_path), "qtd": 3}]}),
        encoding="utf-8",
    )
    subprocess.run(
        [
            str(godot_bin),
            "--headless",
            "--path",
            str(RAIZ / "tools" / "godot_project"),
            "--script",
            str(RAIZ / "tools" / "godot_draw_calls_bench.gd"),
            "--",
            "--input",
            str(in_dummy),
            "--output",
            str(out_dummy),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    dummy_res = json.loads(out_dummy.read_text(encoding="utf-8"))
    assert dummy_res["engine"]["display_driver"] == "headless"
    assert dummy_res["measured"]["perf_draw_calls"] == 0
    assert dummy_res["measured"]["vp_visible_primitives"] == 0

    # 2. Mede nos drivers reais (opengl3 naive = 3*4 = 12; multimesh = 4; vulkan forward+ = 4)
    out_real = tmp_path / "relatorio_real.json"
    rc = mod.main([str(tmp_path), "--saida-json", str(out_real), "--json"])
    assert rc == 0
    rel = json.loads(out_real.read_text(encoding="utf-8"))
    alvo = rel["resultados"][0]
    assert alvo["g11_legado"]["medido"]["draw_calls_estimados"] == 1
    assert alvo["g11"]["medido"]["draw_calls_estimados"] == 4
    runs = alvo["godot_runs"]
    assert runs["opengl3_naive_noshadow"]["measured"]["perf_draw_calls"] == 12
    assert runs["opengl3_multimesh_noshadow"]["measured"]["perf_draw_calls"] == 4
    assert runs["vulkan_multimesh_noshadow"]["measured"]["perf_draw_calls"] == 4
    assert runs["vulkan_naive_noshadow"]["measured"]["vp_visible_primitives"] == 36
