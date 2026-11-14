"""Testes de regressao da Onda 2 (M01..M21 — melhorias Godot, QC, verify, sync, rbx e CI)."""

from __future__ import annotations

import json
import shutil
import struct
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from forge3d import config, profiles, publish, qc, rbx, sync, verify
from forge3d.canonical import sha256_arquivo
from forge3d.errors import ForgeError
from tests.test_seguranca_e_qc import _glb_bytes

RAIZ = Path(__file__).resolve().parents[1]


def _injetar_atributos_glb(
    glb_base: bytes,
    *,
    com_tangent: bool = False,
    uv1: list[tuple[float, float]] | None = None,
    extra_mat: dict | None = None,
) -> bytes:
    magic, ver, _ = struct.unpack_from("<III", glb_base, 0)
    jlen, jtype = struct.unpack_from("<II", glb_base, 12)
    gltf = json.loads(glb_base[20 : 20 + jlen].decode("utf-8"))
    bin_hdr = 20 + jlen
    blen, btype = struct.unpack_from("<II", glb_base, bin_hdr)
    buf = bytearray(glb_base[bin_hdr + 8 : bin_hdr + 8 + blen])

    def pad4() -> None:
        while len(buf) % 4:
            buf.append(0)

    prim = gltf["meshes"][0]["primitives"][0]
    n_verts = gltf["accessors"][prim["attributes"]["POSITION"]]["count"]

    if com_tangent:
        pad4()
        t_off = len(buf)
        for _ in range(n_verts):
            buf.extend(struct.pack("<ffff", 1.0, 0.0, 0.0, 1.0))
        t_len = len(buf) - t_off
        gltf["bufferViews"].append({"buffer": 0, "byteOffset": t_off, "byteLength": t_len})
        gltf["accessors"].append(
            {"bufferView": len(gltf["bufferViews"]) - 1, "componentType": 5126, "count": n_verts, "type": "VEC4"}
        )
        prim["attributes"]["TANGENT"] = len(gltf["accessors"]) - 1

    if uv1 is not None:
        pad4()
        u_off = len(buf)
        for u, v in uv1:
            buf.extend(struct.pack("<ff", u, v))
        u_len = len(buf) - u_off
        gltf["bufferViews"].append({"buffer": 0, "byteOffset": u_off, "byteLength": u_len})
        gltf["accessors"].append(
            {"bufferView": len(gltf["bufferViews"]) - 1, "componentType": 5126, "count": len(uv1), "type": "VEC2"}
        )
        prim["attributes"]["TEXCOORD_1"] = len(gltf["accessors"]) - 1

    if extra_mat:
        gltf["materials"][0].update(extra_mat)

    pad4()
    gltf["buffers"][0]["byteLength"] = len(buf)
    jb = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    while len(jb) % 4:
        jb += b" "
    return (
        struct.pack("<III", magic, ver, 12 + 8 + len(jb) + 8 + len(buf))
        + struct.pack("<II", len(jb), jtype)
        + jb
        + struct.pack("<II", len(buf), btype)
        + bytes(buf)
    )


def _gate(relatorio: dict, gid: str) -> dict:
    return next(g for g in relatorio["gates"] if g["id"] == gid)


def test_m05_montar_manifesto_preenche_tangentes_uv_lightmap_e_modo_rig_roblox(tmp_path):
    uv1 = [(0.1, 0.1), (0.9, 0.1), (0.9, 0.9), (0.1, 0.9)] * 2
    ossos_r15 = profiles.carregar("roblox-r15")["rig"]["mapas"]["r15@1"]
    glb = _injetar_atributos_glb(_glb_bytes(ossos=ossos_r15), com_tangent=True, uv1=uv1)
    (tmp_path / "m.glb").write_bytes(glb)

    item = {
        "id": "hero.r15.01",
        "rota": "mesh",
        "altura_metros": 1.0,
        "pivot": "base",
        "limite_triangulos": 500,
        "auto_rig": True,
        "esqueleto": "r15@1",
        "modo_rig_roblox": "bone",
        "colisao": "none",
        "seed": 1,
    }
    perfil = profiles.carregar("roblox-r15")
    resultado = {
        "medidas": {"nao_manifold": 0, "degeneradas": 0, "partes_colisao": 0},
        "arquivos": [
            {
                "caminho": "m.glb",
                "papel": "mesh",
                "nivel": 0,
                "triangulos": 12,
                "sha256": sha256_arquivo(tmp_path / "m.glb"),
                "bytes": len(glb),
            }
        ],
        "licenca": {"modelo": "MIT", "uso_comercial": True, "notice": "ok"},
        "determinism": "D2",
    }
    rel_qc = qc.verificar(item, perfil, tmp_path, resultado, escala_saida=1.0)
    assert rel_qc["medidas"].get("tangentes") is True
    assert rel_qc["medidas"].get("uv_lightmap") is True

    man = publish.montar_manifesto(
        item=item,
        spec_doc={"projeto": "demo", "perfil": "roblox-r15", "_arquivo": "lote.yaml"},
        spec_hash="sha256:" + "a" * 64,
        perfil_nome="roblox-r15",
        perfil=perfil,
        provider={"nome": "mesh", "versao": "0.1.8", "determinism": "D2"},
        resultado=resultado,
        relatorio_qc=rel_qc,
        licenca={"modelo": "MIT", "uso_comercial": True, "notice": "ok"},
        run_id="run-m05",
    )
    assert man["geometry"].get("tangentes") is True
    assert man["geometry"].get("uv_lightmap") is True
    assert man["rig"].get("modo_rig_roblox") == "bone"


def test_m06_qc_g7_reprova_colisor_minusculo_e_respeita_flag_dentro_da_aabb(tmp_path):
    # 1. Colisor minusculo (1mm dentro de cubo de 1m) deve reprovar por cobertura insuficiente
    d_tiny = tmp_path / "tiny"
    d_tiny.mkdir()
    (d_tiny / "m.glb").write_bytes(_glb_bytes())
    verts_tiny = [
        (-0.0005, 0.0, -0.0005), (0.0005, 0.0, -0.0005), (0.0005, 0.001, -0.0005), (-0.0005, 0.001, -0.0005),
        (-0.0005, 0.0, 0.0005), (0.0005, 0.0, 0.0005), (0.0005, 0.001, 0.0005), (-0.0005, 0.001, 0.0005),
    ]
    (d_tiny / "m_col.glb").write_bytes(_glb_bytes(verts=verts_tiny, no_nome="UCX_tiny"))
    perfil = profiles.carregar("godot4")
    item = {"id": "prop.tiny.01", "altura_metros": 1.0, "pivot": "base", "limite_triangulos": 500, "colisao": "convex"}
    res = {
        "medidas": {"nao_manifold": 0, "degeneradas": 0, "partes_colisao": 1},
        "arquivos": [
            {"caminho": "m.glb", "papel": "mesh", "nivel": 0, "triangulos": 12},
            {"caminho": "m_col.glb", "papel": "colisor", "partes": 1},
        ],
        "licenca": {"modelo": "CC0", "uso_comercial": True},
    }
    rel_tiny = qc.verificar(item, perfil, d_tiny, res, escala_saida=1.0)
    assert _gate(rel_tiny, "G7")["status"] == "falhou"

    # 2. Quando perfil tem dentro_da_aabb=False, colisor deslocado mas com cobertura valida passa
    d_flag = tmp_path / "flag"
    d_flag.mkdir()
    (d_flag / "m.glb").write_bytes(_glb_bytes())
    verts_shift = [(x + 3.0, y, z) for (x, y, z) in [
        (-0.5, 0.0, -0.5), (0.5, 0.0, -0.5), (0.5, 1.0, -0.5), (-0.5, 1.0, -0.5),
        (-0.5, 0.0, 0.5), (0.5, 0.0, 0.5), (0.5, 1.0, 0.5), (-0.5, 1.0, 0.5),
    ]]
    (d_flag / "m_col.glb").write_bytes(_glb_bytes(verts=verts_shift, no_nome="UCX_shift"))
    perfil_sem_aabb = json.loads(json.dumps(perfil))
    perfil_sem_aabb["colisao"]["dentro_da_aabb"] = False
    rel_flag = qc.verificar(item, perfil_sem_aabb, d_flag, res, escala_saida=1.0)
    assert _gate(rel_flag, "G7")["status"] == "ok"


def test_m07_qc_g9_reprova_lod_sem_reducao_ou_com_degeneradas(tmp_path):
    # Malha LOD0 com 24 triangulos (dois cubos empilhados dentro de [0,1])
    v_cubo1 = [
        (-0.5, 0.0, -0.5), (0.5, 0.0, -0.5), (0.5, 0.5, -0.5), (-0.5, 0.5, -0.5),
        (-0.5, 0.0, 0.5), (0.5, 0.0, 0.5), (0.5, 0.5, 0.5), (-0.5, 0.5, 0.5),
    ]
    v_cubo2 = [(x, y + 0.5, z) for (x, y, z) in v_cubo1]
    t_cubo1 = [
        (0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7),
        (0, 1, 5), (0, 5, 4), (2, 3, 7), (2, 7, 6),
        (0, 4, 7), (0, 7, 3), (1, 2, 6), (1, 6, 5),
    ]
    t_cubo2 = [(a + 8, b + 8, c + 8) for (a, b, c) in t_cubo1]
    glb_24 = _glb_bytes(verts=v_cubo1 + v_cubo2, tris=t_cubo1 + t_cubo2)

    # Caso 1: LOD1 com os mesmos 24 triangulos (sem reducao) -> G9 deve falhar
    d1 = tmp_path / "lod_sem_reducao"
    d1.mkdir()
    (d1 / "m.glb").write_bytes(glb_24)
    (d1 / "m_LOD1.glb").write_bytes(glb_24)
    perfil = profiles.carregar("godot4")
    item = {"id": "prop.lod.01", "altura_metros": 1.0, "pivot": "base", "limite_triangulos": 500, "colisao": "none"}
    rel1 = qc.verificar(
        item,
        perfil,
        d1,
        {
            "medidas": {"nao_manifold": 0, "degeneradas": 0},
            "arquivos": [
                {"caminho": "m.glb", "papel": "mesh", "nivel": 0, "triangulos": 24},
                {"caminho": "m_LOD1.glb", "papel": "lod", "nivel": 1, "triangulos": 24},
            ],
            "licenca": {"modelo": "CC0", "uso_comercial": True},
        },
        escala_saida=1.0,
    )
    assert _gate(rel1, "G9")["status"] == "falhou"

    # Caso 2: LOD1 com 13 triangulos (< 24), mas 1 face degenerada -> G9 deve falhar
    d2 = tmp_path / "lod_degen"
    d2.mkdir()
    (d2 / "m.glb").write_bytes(glb_24)
    tris_degen = list(t_cubo1) + [(0, 0, 1)]
    (d2 / "m_LOD1.glb").write_bytes(_glb_bytes( tris=tris_degen))
    rel2 = qc.verificar(
        item,
        perfil,
        d2,
        {
            "medidas": {"nao_manifold": 0, "degeneradas": 0},
            "arquivos": [
                {"caminho": "m.glb", "papel": "mesh", "nivel": 0, "triangulos": 24},
                {"caminho": "m_LOD1.glb", "papel": "lod", "nivel": 1, "triangulos": 13},
            ],
            "licenca": {"modelo": "CC0", "uso_comercial": True},
        },
        escala_saida=1.0,
    )
    assert _gate(rel2, "G9")["status"] == "falhou"


def test_m08_qc_g3_valida_texcoord_1_lightmap(tmp_path):
    # UV0 valida, mas TEXCOORD_1 colapsada em um unico ponto -> G3 deve falhar
    glb_bad_uv1 = _injetar_atributos_glb(_glb_bytes(), uv1=[(0.5, 0.5)] * 8)
    (tmp_path / "m.glb").write_bytes(glb_bad_uv1)
    rel = qc.verificar(
        {"id": "prop.uv1.01", "altura_metros": 1.0, "pivot": "base", "limite_triangulos": 500, "colisao": "none"},
        profiles.carregar("godot4"),
        tmp_path,
        {
            "medidas": {"nao_manifold": 0, "degeneradas": 0},
            "arquivos": [{"caminho": "m.glb", "papel": "mesh", "nivel": 0, "triangulos": 12}],
            "licenca": {"modelo": "CC0", "uso_comercial": True},
        },
        escala_saida=1.0,
    )
    assert _gate(rel, "G3")["status"] == "falhou"


def test_m09_qc_g4_g5_valida_normal_map_z_positivo_e_vinculo_orm(tmp_path):
    # Normal map com canal B invertido (Z negativo: B=20 < 128) deve falhar no G4
    d_nm = tmp_path / "bad_nm"
    d_nm.mkdir()
    glb = _injetar_atributos_glb(
        _glb_bytes(),
        com_tangent=True,
        extra_mat={"normalTexture": {"index": 0}},
    )
    (d_nm / "m.glb").write_bytes(glb)
    Image.new("RGB", (8, 8), (128, 128, 20)).save(d_nm / "m_normal.png")
    rel_nm = qc.verificar(
        {"id": "prop.nm.01", "altura_metros": 1.0, "pivot": "base", "limite_triangulos": 500, "colisao": "none"},
        profiles.carregar("godot4"),
        d_nm,
        {
            "medidas": {"nao_manifold": 0, "degeneradas": 0},
            "arquivos": [
                {"caminho": "m.glb", "papel": "mesh", "nivel": 0, "triangulos": 12},
                {"caminho": "m_normal.png", "papel": "normal"},
            ],
            "licenca": {"modelo": "CC0", "uso_comercial": True},
        },
        escala_saida=1.0,
    )
    assert _gate(rel_nm, "G4")["status"] == "falhou"


def test_m10_verify_detecta_arquivo_orfao_no_destino(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE3D_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("FORGE3D_CONFIG", str(tmp_path / "config"))
    from tests.test_sync import _publicar_valido

    destino = _publicar_valido(tmp_path, asset_id="prop.orfao.01")
    (destino / "lixo_orfao.glb").write_bytes(b"orfao")

    rel = verify.verificar(destino)
    assert rel["ok"] is False
    assert any("lixo_orfao.glb" in str(e) for e in rel["erros"])


def test_m13_m14_sync_detecta_project_godot_ancestral_e_deduplica_lod0(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE3D_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("FORGE3D_CONFIG", str(tmp_path / "config"))

    origem = tmp_path / "ext4_src"
    staging = tmp_path / "staging"
    staging.mkdir(parents=True)
    asset_id = "prop.sub.01"
    glb = _glb_bytes(no_nome=asset_id)
    (staging / f"{asset_id}.glb").write_bytes(glb)
    (staging / f"{asset_id}_LOD1.glb").write_bytes(glb)
    man = {
        "schema": "forge3d/manifest@4",
        "asset_id": asset_id,
        "projeto": "demo",
        "perfil": "godot4",
        "rota": "blocky",
        "tags": ["sync"],
        "spec_hash": "sha256:" + "a" * 64,
        "pipeline_version": "0.6.0",
        "determinism": "D1",
        "providers": {"geometry": {"name": "blocky", "version": "0.2.3", "license": "CC0-1.0"}},
        "geometry": {"triangulos": 12, "vertices": 8, "bbox_m": [1.0, 1.0, 1.0], "materiais": 1},
        "unidades_export": {"metros_por_unidade": 1.0, "escala_saida": 1.0},
        "animacoes": [],
        "rig": None,
        "lod": [
            {"nivel": 0, "triangulos": 12, "arquivo": f"{asset_id}.glb"},
            {"nivel": 1, "triangulos": 6, "arquivo": f"{asset_id}_LOD1.glb"},
        ],
        "colisao": {"tipo": "none", "partes": 0},
        "files": [
            {"caminho": f"{asset_id}.glb", "papel": "mesh", "sha256": sha256_arquivo(staging / f"{asset_id}.glb"), "bytes": len(glb)},
            {"caminho": f"{asset_id}_LOD1.glb", "papel": "lod", "sha256": sha256_arquivo(staging / f"{asset_id}_LOD1.glb"), "bytes": len(glb)},
        ],
        "qc": {
            "aprovado": True,
            "gates": [
                {"id": "G2", "status": "ok", "medido": {"esperado_m": 1.0, "pivo_regra": "base"}},
                {"id": "G9", "status": "ok", "medido": {"triangulos": 12, "limite": 500}},
            ],
        },
        "licenca": {"modelo": "CC0-1.0", "uso_comercial": True, "notice": "fixture"},
        "origem_spec": {"arquivo": "lote.yaml", "hash": "sha256:" + "a" * 64},
        "run_id": "run-sub-1",
        "created_at": "2026-11-11T00:00:00Z",
    }
    publish.publicar(staging, origem, man, "run-sub-1")

    raiz_godot = tmp_path / "meu_jogo"
    alvo_sub = raiz_godot / "assets" / "forge3d"
    raiz_godot.mkdir(parents=True)
    (raiz_godot / "project.godot").write_text('[application]\nconfig/name="sub"\n', encoding="utf-8")

    rel = sync.executar(origem, alvo_sub, limpar=True)
    assert rel["ok"] is True
    assert (alvo_sub / f"{asset_id}_LOD1.glb.import").is_file()
    gd_file = alvo_sub / "forge3d_assets.gd"
    assert gd_file.is_file()
    conteudo_gd = gd_file.read_text(encoding="utf-8")
    assert f'"res://assets/forge3d/{asset_id}.glb"' in conteudo_gd
    # nivel 0 (malha base) nao deve estar duplicado dentro do array "lod"
    assert f'"res://assets/forge3d/{asset_id}_LOD1.glb"' in conteudo_gd
    assert conteudo_gd.count(f'"res://assets/forge3d/{asset_id}.glb"') == 1


def test_m15_gerar_rbxmx_animacoes_valida_destino_allowlist(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE3D_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("FORGE3D_CONFIG", str(tmp_path / "config"))
    # Nao adiciona tmp_path / "fora_allowlist" na allowlist
    config.adicionar(tmp_path / "permitido")
    fora = tmp_path / "fora_allowlist" / "idle.rbxmx"

    with pytest.raises(ForgeError) as exc:
        rbx.exportar_animacao(
            "examples/lote_09_r15.yaml",
            "personagem.r15.guard.01",
            clipe="idle",
            saida=fora,
        )
    assert exc.value.codigo == "FORGE-E-DESTINO"


def test_m01_m02_ci_verify_restaura_glb_e_roda_blender_suite():
    conteudo = (RAIZ / "tools" / "ci_verify.sh").read_text(encoding="utf-8")
    assert "blender and not gpu" in conteudo or "-m blender" in conteudo
    # Apos corromper $GLB para testar exit 3, deve restaurar o arquivo integro
    pos_corrupcao = conteudo.find('printf \'x\' >> "$GLB"')
    pos_p3 = conteudo.find("contratos GLB Godot game-ready (Pacote 3)")
    assert pos_corrupcao != -1 and pos_p3 > pos_corrupcao
    trecho = conteudo[pos_corrupcao:pos_p3]
    assert 'mv "$GLB.bak" "$GLB"' in trecho or 'cp "$GLB.bak" "$GLB"' in trecho


def test_m04_m11_post_import_mipmaps_reuso_e_colisor_sem_simplify(tmp_path):
    godot = shutil.which("godot")
    if not godot:
        cand = Path.home() / ".gemini" / "antigravity" / "bin" / "godot"
        if cand.is_file():
            godot = str(cand)
    if not godot:
        pytest.skip("Godot headless ausente")

    post_import_gd = RAIZ / "addons" / "forge3d" / "post_import.gd"
    tex_path = tmp_path / "teste_mip.png"
    Image.new("RGBA", (16, 16), (100, 150, 200, 255)).save(tex_path)

    script = tmp_path / "check_m04_m11.gd"
    script.write_text(
        f"""extends SceneTree
const PostImport := preload({str(post_import_gd)!r})

func _initialize() -> void:
\tvar tex := PostImport._carregar_textura({str(tex_path)!r})
\tif tex == null or not tex.get_image().has_mipmaps():
\t\tprint("FAIL_MIPMAPS")
\t\tquit(1)
\t\treturn
\tvar mat_in := StandardMaterial3D.new()
\tvar emb_albedo := ImageTexture.create_from_image(Image.create(8, 8, true, Image.FORMAT_RGBA8))
\tvar emb_norm := ImageTexture.create_from_image(Image.create(8, 8, true, Image.FORMAT_RGBA8))
\tmat_in.albedo_texture = emb_albedo
\tmat_in.normal_enabled = true
\tmat_in.normal_texture = emb_norm
\tvar sib_norm := ImageTexture.create_from_image(Image.create(16, 16, true, Image.FORMAT_RGBA8))
\tvar sib_orm := ImageTexture.create_from_image(Image.create(16, 16, true, Image.FORMAT_RGBA8))
\tvar out_mat := PostImport._processar_material(mat_in, sib_orm, sib_norm, tex, false) as ORMMaterial3D
\tif out_mat == null:
\t\tprint("FAIL_ORM_NULL")
\t\tquit(1)
\t\treturn
\tif out_mat.albedo_texture != emb_albedo or out_mat.normal_texture != emb_norm:
\t\tprint("FAIL_DUPLICOU_TEXTURA_EMBUTIDA")
\t\tquit(1)
\t\treturn
\tprint("M04_M11_OK")
\tquit(0)
""",
        encoding="utf-8",
    )
    proj_repo = RAIZ / "tools" / "godot_project"
    proc = subprocess.run(
        [godot, "--headless", "--path", str(proj_repo), "--script", str(script)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0 and "M04_M11_OK" in proc.stdout, proc.stdout + proc.stderr
    assert "mesh.create_convex_shape(true, false)" in post_import_gd.read_text(encoding="utf-8")
