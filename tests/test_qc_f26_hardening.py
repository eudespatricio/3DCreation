"""Testes unitarios dirigidos de hardening F26.1-F26.10."""

from __future__ import annotations

import io
import json
import math
import struct
from pathlib import Path

import pytest
from PIL import Image

from forge3d import canonical, doctor, profiles, publish, qc, rbx_anim, verify
from tests.test_seguranca_e_qc import _editar_gltf_glb, _glb_bytes


def _normal_png(tamanho: int = 64, *, opengl_y: bool = True) -> bytes:
    img = Image.new("RGB", (tamanho, tamanho), (128, 128, 255))
    px = img.load()
    assert px is not None
    c, r = (tamanho - 1) * 0.5, tamanho * 0.375
    sinal = -1.0 if opengl_y else 1.0
    for y in range(tamanho):
        dy = (y - c) / r
        for x in range(tamanho):
            dx = (x - c) / r
            d2 = dx * dx + dy * dy
            if d2 < 1.0:
                nz = math.sqrt(1.0 - d2)
                px[x, y] = (128 + round(127 * dx), 128 + round(127 * sinal * dy), 128 + round(127 * nz))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _item(**extra: object) -> dict:
    return {
        "id": "prop.f26.01",
        "tipo": "prop_estatico",
        "altura_metros": 1.0,
        "pivot": "base",
        "limite_triangulos": 5000,
        "colisao": "none",
        **extra,
    }


def _res(caminho: str = "m.glb", extras: list[dict] | None = None) -> dict:
    return {
        "medidas": {"nao_manifold": 0, "degeneradas": 0, "partes_colisao": 0},
        "arquivos": [{"caminho": caminho, "papel": "mesh", "nivel": 0, "triangulos": 12}, *(extras or [])],
        "licenca": {"modelo": "MIT", "uso_comercial": True, "notice": "teste"},
        "determinism": "D1",
    }


@pytest.mark.parametrize("bad_val", [float("nan"), float("inf"), float("-inf")])
def test_g2_rejeita_normal_nao_finita_em_prop_estatico_poucos_tris(tmp_path: Path, bad_val: float) -> None:
    def _inj_normal(g: dict, b: bytearray) -> None:
        n_verts = g["accessors"][0]["count"]
        while len(b) % 4:
            b.append(0)
        off = len(b)
        norms = [(0.0, 0.0, 1.0)] * (n_verts - 1) + [(bad_val, 0.0, 1.0)]
        b.extend(b"".join(struct.pack("<3f", *n) for n in norms))
        bv_idx = len(g["bufferViews"])
        g["bufferViews"].append({"buffer": 0, "byteOffset": off, "byteLength": n_verts * 12})
        acc_idx = len(g["accessors"])
        g["accessors"].append({"bufferView": bv_idx, "componentType": 5126, "count": n_verts, "type": "VEC3"})
        g["meshes"][0]["primitives"][0]["attributes"]["NORMAL"] = acc_idx
        g["buffers"][0]["byteLength"] = len(b)

    (tmp_path / "m.glb").write_bytes(_editar_gltf_glb(_glb_bytes(), _inj_normal))
    rel = qc.verificar(_item(), profiles.carregar("godot4"), tmp_path, _res())
    g2 = next(g for g in rel["gates"] if g["id"] == "G2")
    assert g2["status"] == "falhou"
    assert "normal_nao_finita" in g2["medido"]["orientacao"]["motivos"]
    assert rel["aprovado"] is False


@pytest.mark.parametrize(("opengl_y", "esperado"), [(True, "ok"), (False, "falhou")])
def test_g4_valida_polaridade_normal_texture_embutida(tmp_path: Path, opengl_y: bool, esperado: str) -> None:
    png_norm = _normal_png(64, opengl_y=opengl_y)

    def _inj_norm_tex(g: dict, b: bytearray) -> None:
        n_verts = g["accessors"][0]["count"]
        while len(b) % 4:
            b.append(0)
        off_t = len(b)
        b.extend(b"".join(struct.pack("<4f", 1.0, 0.0, 0.0, 1.0) for _ in range(n_verts)))
        bv_t = len(g["bufferViews"])
        g["bufferViews"].append({"buffer": 0, "byteOffset": off_t, "byteLength": n_verts * 16})
        acc_t = len(g["accessors"])
        g["accessors"].append({"bufferView": bv_t, "componentType": 5126, "count": n_verts, "type": "VEC4"})
        g["meshes"][0]["primitives"][0]["attributes"]["TANGENT"] = acc_t

        while len(b) % 4:
            b.append(0)
        off_n = len(b)
        b.extend(png_norm)
        bv_n = len(g["bufferViews"])
        g["bufferViews"].append({"buffer": 0, "byteOffset": off_n, "byteLength": len(png_norm)})
        img_n = len(g["images"])
        g["images"].append({"bufferView": bv_n, "mimeType": "image/png"})
        tex_n = len(g["textures"])
        g["textures"].append({"source": img_n})
        g["materials"][0]["normalTexture"] = {"index": tex_n}
        g["buffers"][0]["byteLength"] = len(b)

    (tmp_path / "m.glb").write_bytes(_editar_gltf_glb(_glb_bytes(), _inj_norm_tex))
    rel = qc.verificar(_item(), profiles.carregar("godot4"), tmp_path, _res())
    g4 = next(g for g in rel["gates"] if g["id"] == "G4")
    assert g4["status"] == esperado


def test_doctor_schemas_resiste_json_corrompido_utf8_invalido_e_oserror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    schemas = tmp_path / "schemas"
    schemas.mkdir()
    for nome in (
        *(f"spec.v{v}.schema.json" for v in range(1, 7)),
        *(f"manifest.v{v}.schema.json" for v in range(1, 7)),
    ):
        (schemas / nome).write_text("{}", encoding="utf-8")
    (schemas / "spec.v1.schema.json").write_text("{json_quebrado", encoding="utf-8")
    (schemas / "spec.v2.schema.json").write_bytes(b"\xff\xfe\x00\x00")
    (schemas / "spec.v3.schema.json").write_text('{"type": "invalid_type_xyz"}', encoding="utf-8")
    (schemas / "spec.v4.schema.json").unlink()
    (schemas / "spec.v4.schema.json").mkdir()  # IsADirectoryError (OSError)

    monkeypatch.setattr(doctor.paths, "raiz_dados", lambda: tmp_path)
    res = doctor._checar_schemas()
    assert res["ok"] is False
    assert "spec.v1.schema.json" in res["detalhe"]
    assert "spec.v2.schema.json" in res["detalhe"]
    assert "spec.v3.schema.json" in res["detalhe"]
    assert "spec.v4.schema.json" in res["detalhe"]


def test_g7_colisor_nodes_none_ou_malformado_reprova_sem_crash(tmp_path: Path) -> None:
    (tmp_path / "m.glb").write_bytes(_glb_bytes())
    col_base = _glb_bytes(no_nome="UCX_col_01")
    perfil = profiles.carregar("godot4")
    item = _item(colisao="convex")

    for nome, mut in (
        ("nodes_none", lambda g, _b: g.update({"nodes": [None]})),
        ("nodes_bad", lambda g, _b: g.update({"nodes": "bad"})),
        ("meshes_none", lambda g, _b: g.update({"meshes": [None]})),
    ):
        sub = tmp_path / nome
        sub.mkdir()
        (sub / "m.glb").write_bytes(_glb_bytes())
        (sub / "m_col.glb").write_bytes(_editar_gltf_glb(col_base, mut))
        rel = qc.verificar(
            item,
            perfil,
            sub,
            _res(extras=[{"caminho": "m_col.glb", "papel": "colisor", "partes": 1}]),
        )
        g7 = next(g for g in rel["gates"] if g["id"] == "G7")
        assert g7["status"] == "falhou", (nome, g7)
        assert rel["aprovado"] is False


def test_rbx_anim_nao_loop_inclui_slash_combo_cast_e_bite() -> None:
    for clipe in ("slash_combo", "cast", "bite"):
        linhas, _ = rbx_anim._sequencia_xml({"nome": clipe, "chaves": []}, 0)
        xml = "\n".join(linhas)
        assert '<bool name="Loop">false</bool>' in xml, (clipe, xml)


def test_g3_densidade_texel_extrema_reprova(tmp_path: Path) -> None:
    verts = [
        (-0.5, 0.0, 0.0), (0.5, 0.0, 0.0), (0.0, 1.0, 0.0),
        (-0.5, 0.0, 0.2), (0.5, 0.0, 0.2), (0.0, 1.0, 0.2),
    ]
    tris = [(0, 1, 2), (3, 4, 5)]
    uvs = [
        (0.05, 0.05), (0.95, 0.05), (0.50, 0.95),
        (0.05, 0.96), (0.06, 0.96), (0.055, 0.97),  # area UV ~5e-5 vs ~0.405 -> >8000x disparity
    ]
    (tmp_path / "m.glb").write_bytes(_glb_bytes(verts=verts, tris=tris, uvs=uvs))
    rel = qc.verificar(_item(alpha_cards=True), profiles.carregar("godot4"), tmp_path, _res())
    g3 = next(g for g in rel["gates"] if g["id"] == "G3")
    assert g3["status"] == "falhou"
    assert g3["medido"]["densidade_extrema"] >= 1


def test_g6_sem_deformacao_reprova_com_matriz_nula_e_g5_verify_pbr_zonas_clay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    perfil = profiles.carregar("godot4")
    ossos = list(perfil["rig"]["mapas"]["godot-humanoid@1"])
    glb_zero_mat = _editar_gltf_glb(
        _glb_bytes(ossos=ossos),
        lambda g, _b: [g["nodes"][j].update({"scale": [0.0, 0.0, 0.0]}) for j in g["skins"][0]["joints"][1:]],
    )
    gltf_z, bin_z = qc.ler_glb_bin(glb_zero_mat)
    skin_st = qc._skin_status(gltf_z, bin_z)
    assert skin_st["ok"] is False
    assert skin_st["sem_deformacao"] >= 1

    monkeypatch.setenv("FORGE3D_HOME", str(tmp_path / "_h"))
    monkeypatch.setenv("FORGE3D_CONFIG", str(tmp_path / "_c"))
    from forge3d import config

    dest = tmp_path / "pub_pbr"
    dest.mkdir()
    config.adicionar(dest)
    clay_glb = dest / "prop.clay.01.glb"
    clay_glb.write_bytes(_glb_bytes(materiais=[{"name": "clay", "pbrMetallicRoughness": {"baseColorFactor": [0.8, 0.8, 0.8, 1.0]}}]))
    item = _item(id="prop.clay.01", pbr_zonas=[{"nome": "aco", "preset": "aco_forjado"}])
    res = _res(clay_glb.name)
    res["arquivos"][0].update(sha256=canonical.sha256_arquivo(clay_glb), bytes=clay_glb.stat().st_size)
    rel_qc = qc.verificar(item, perfil, dest, res, escala_saida=1.0)
    assert next(g for g in rel_qc["gates"] if g["id"] == "G5")["status"] == "falhou"

    # Publicacao forjada como aprovada ainda reprova no verify via forwarding de pbr_zonas
    rel_fake = {**rel_qc, "aprovado": True, "gates": [{**g, "status": "ok"} for g in rel_qc["gates"]]}
    man = publish.montar_manifesto(
        item={**item, "rota": "blocky"},
        spec_doc={"projeto": "demo", "perfil": "godot4", "_arquivo": "lote.yaml"},
        spec_hash="sha256:" + "0" * 64,
        perfil_nome="godot4",
        perfil=perfil,
        provider={"nome": "blocky", "versao": "0.9.4", "determinism": "D1"},
        resultado=res,
        relatorio_qc=rel_fake,
        licenca={"modelo": "MIT", "uso_comercial": True, "notice": "teste"},
        run_id="run-pbr-clay",
    )
    (dest / "prop.clay.01.manifest.json").write_text(json.dumps(man), encoding="utf-8")
    rel_v = verify.verificar(dest)
    assert rel_v["ok"] is False
    assert any("G5" in str(e) for e in rel_v["erros"])
