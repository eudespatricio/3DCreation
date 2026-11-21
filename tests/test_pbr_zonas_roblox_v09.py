"""Testes v0.9.0: High->Low detalhe_alto, pbr_zonas multi-zona, Roblox PBR/Open Cloud e I4/I9."""

from __future__ import annotations

import hashlib
import json
import struct
import subprocess
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from PIL import Image

from forge3d import config, post, rbx, upload

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ / "blender") not in sys.path:
    sys.path.insert(0, str(RAIZ / "blender"))

import bake_pbr  # noqa: E402
import procedural_pbr  # noqa: E402


@pytest.fixture(autouse=True)
def _isolar_allowlist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORGE3D_HOME", str(tmp_path / "forge_home"))
    monkeypatch.setenv("FORGE3D_CONFIG", str(tmp_path / "forge_cfg"))
    config.adicionar(tmp_path)


def _rodar_blender_py(codigo: str, timeout: int = 180) -> subprocess.CompletedProcess[str]:
    blender = post.binario()
    return subprocess.run(
        [blender, "--background", "--factory-startup", "--python-expr", codigo],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _construir_glb_com_textura_embutida() -> bytes:
    gltf = {
        "asset": {"version": "2.0"},
        "meshes": [
            {
                "primitives": [
                    {
                        "attributes": {"POSITION": 0, "NORMAL": 1, "TEXCOORD_0": 2, "TANGENT": 3},
                        "material": 0,
                    }
                ]
            }
        ],
        "images": [{"bufferView": 0, "mimeType": "image/png"}],
        "textures": [{"source": 0, "sampler": 0}],
        "samplers": [{"magFilter": 9729, "minFilter": 9987}],
        "materials": [
            {
                "name": "bastion_pbr",
                "pbrMetallicRoughness": {
                    "baseColorTexture": {"index": 0},
                    "metallicRoughnessTexture": {"index": 0},
                },
                "normalTexture": {"index": 0},
                "occlusionTexture": {"index": 0},
            }
        ],
    }
    json_raw = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    json_raw += b" " * ((4 - (len(json_raw) % 4)) % 4)
    bin_raw = b"\x01\x02\x03\x04\x05\x06\x07\x08"
    total = 12 + 8 + len(json_raw) + 8 + len(bin_raw)
    return (
        struct.pack("<III", 0x46546C67, 2, total)
        + struct.pack("<II", len(json_raw), 0x4E4F534A)
        + json_raw
        + struct.pack("<II", len(bin_raw), 0x004E4942)
        + bin_raw
    )


def test_post_versao_093_preflight_i9_e_forward_v6(monkeypatch: pytest.MonkeyPatch) -> None:
    assert post.PIPELINE_VERSION == "0.9.9"
    assert post.VERSAO_MIN == (4, 2)
    assert post.VERSAO_MAX == (4, 3)

    monkeypatch.setattr(post, "versao", lambda: (4, 2, 3))
    ok, msg = post.preflight()
    assert ok is True and "4.2.3" in msg

    for v_invalida in ((4, 1, 0), (4, 3, 0), (4, 5, 0)):
        monkeypatch.setattr(post, "versao", lambda v=v_invalida: v)
        ok_inv, msg_inv = post.preflight()
        assert ok_inv is False
        assert "pinado em 4.2.x" in msg_inv

    job_in = {
        "saida_dir": "/tmp/out",
        "item": {
            "id": "prop.bastion.01",
            "detalhe_alto": {"ativo": True, "subdiv_niveis": 2},
            "pbr_zonas": [{"preset": "pedra_musgo", "cor_hex": "#5C6066"}],
            "quantidade_cena": 4,
            "render_fidelity_roblox": "Precise",
            "alpha_cards": True,
            "smart_fit": {"folga_m": 0.0015},
            "roblox_render": {"lighting_technology": "Future"},
        },
    }
    prep = post._preparar_job(job_in)
    for campo in (
        "detalhe_alto",
        "pbr_zonas",
        "quantidade_cena",
        "render_fidelity_roblox",
        "alpha_cards",
        "smart_fit",
        "roblox_render",
    ):
        assert prep[campo] == job_in["item"][campo]


def test_presets_pbr_10_zonas_e_px_bake_recomendado_sem_downgrade_512() -> None:
    esperados = (
        "pele_humana",
        "escamas_dragao",
        "aco_forjado",
        "ouro_ornamentado",
        "couro_gasto",
        "cristal_arcano",
        "pedra_musgo",
        "tecido_nobre",
        "madeira_ancestral",
        "energia_espectral",
    )
    assert procedural_pbr.MATERIAIS_PROCEDURAIS == esperados
    assert set(procedural_pbr.PRESETS_PBR) == set(esperados)

    # 1K / 2K / 4K tiers; nunca rebaixa submapas para 512 quando px >= 1024
    assert bake_pbr.px_bake_recomendado("standard") == (1024, 1024)
    assert bake_pbr.px_bake_recomendado("standard", solicitado=1024) == (1024, 1024)
    assert bake_pbr.px_bake_recomendado("hero") == (2048, 1024)
    assert bake_pbr.px_bake_recomendado("hero", teto_perfil=4096) == (2048, 2048)
    assert bake_pbr.px_bake_recomendado("ultra") == (2048, 2048)
    assert bake_pbr.px_bake_recomendado("ultra", teto_perfil=4096) == (4096, 4096)
    assert bake_pbr.px_bake_recomendado("hero", solicitado=4096, teto_perfil=4096) == (4096, 2048)
    assert bake_pbr.px_bake_recomendado("ultra", solicitado=4096, teto_perfil=2048) == (2048, 2048)
    assert bake_pbr.px_bake_recomendado("standard", solicitado=256) == (256, 256)

    assert (
        bake_pbr.deve_ativar_bake_high_low(
            {"pbr_zonas": [{"preset": "aco_forjado"}]},
            tem_cor_vertice=False,
            tem_uv=False,
            tem_materiais=False,
        )
        is True
    )
    assert (
        bake_pbr.deve_ativar_bake_high_low(
            {"detalhe_alto": {"ativo": True}},
            tem_cor_vertice=False,
            tem_uv=True,
            tem_materiais=False,
        )
        is True
    )
    assert (
        bake_pbr.deve_ativar_bake_high_low(
            {"material": "pbr"},
            tem_cor_vertice=False,
            tem_uv=True,
            tem_materiais=True,
        )
        is True
    )


def test_orm_nunca_sobrescreve_roughnessmap_em_rbx_e_upload(tmp_path: Path) -> None:
    assert rbx.inferir_papel_textura_roblox("bastion_orm.png", "orm") == "OrmPacked"
    assert upload.inferir_papel_textura_roblox("bastion_orm.png", None) == "OrmPacked"
    assert rbx.inferir_papel_textura_roblox("bastion_roughness.png", "roughness") == "RoughnessMap"
    assert rbx.inferir_papel_textura_roblox("bastion_metallic.png", "metallic") == "MetalnessMap"
    assert rbx.inferir_papel_textura_roblox("bastion_normal.png", "normal") == "NormalMap"
    assert rbx.inferir_papel_textura_roblox("bastion_baseColor.png", "textura") == "ColorMap"

    pub = tmp_path / "pub"
    pub.mkdir()
    item_id = "citadel.bastion.l5"
    for suf in ("baseColor", "normal", "orm", "roughness", "metallic"):
        (pub / f"{item_id}_{suf}.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    # Mesmo com _orm.png listado ANTES de _roughness.png no manifesto, RoughnessMap = _roughness.png
    man_path = pub / f"{item_id}.manifest.json"
    man_path.write_text(
        json.dumps(
            {
                "schema": "forge3d/manifest@6",
                "asset_id": item_id,
                "files": [
                    {"caminho": f"{item_id}_baseColor.png", "papel": "textura"},
                    {"caminho": f"{item_id}_normal.png", "papel": "normal"},
                    {"caminho": f"{item_id}_orm.png", "papel": "orm"},
                    {"caminho": f"{item_id}_roughness.png", "papel": "roughness"},
                    {"caminho": f"{item_id}_metallic.png", "papel": "metallic"},
                ],
            }
        ),
        encoding="utf-8",
    )

    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(
        "\n".join(
            [
                json.dumps({"evento": "upload", "id": f"{item_id}_basecolor", "asset_id": "2001"}),
                json.dumps({"evento": "upload", "id": f"{item_id}_normal", "asset_id": "2002"}),
                json.dumps({"evento": "upload", "id": f"{item_id}_orm", "asset_id": "2003"}),
                json.dumps({"evento": "upload", "id": f"{item_id}_roughness", "asset_id": "2004"}),
                json.dumps({"evento": "upload", "id": f"{item_id}_metallic", "asset_id": "2005"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    ids_ledger = upload.asset_ids_do_ledger(item_id, ledger)
    assert ids_ledger["OrmPacked"] == "rbxassetid://2003"
    assert ids_ledger["RoughnessMap"] == "rbxassetid://2004"
    assert ids_ledger["MetalnessMap"] == "rbxassetid://2005"

    sa_disk = rbx.exportar_surface_appearance(man_path)
    assert sa_disk["mapas"] == {
        "ColorMap": f"{item_id}_baseColor.png",
        "NormalMap": f"{item_id}_normal.png",
        "RoughnessMap": f"{item_id}_roughness.png",
        "MetalnessMap": f"{item_id}_metallic.png",
    }

    sa_ledger = rbx.exportar_surface_appearance(man_path, ledger=ledger)
    assert sa_ledger["mapas"] == {
        "ColorMap": "rbxassetid://2001",
        "NormalMap": "rbxassetid://2002",
        "RoughnessMap": "rbxassetid://2004",
        "MetalnessMap": "rbxassetid://2005",
    }

    # Em manifest@6 sem _roughness.png, _orm.png NUNCA entra em RoughnessMap
    pub_v6_sem_r = tmp_path / "pub_v6_sem_r"
    pub_v6_sem_r.mkdir()
    for suf in ("baseColor", "normal", "orm"):
        (pub_v6_sem_r / f"{item_id}_{suf}.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    man_v6_sem_r = pub_v6_sem_r / f"{item_id}.manifest.json"
    man_v6_sem_r.write_text(
        json.dumps(
            {
                "schema": "forge3d/manifest@6",
                "asset_id": item_id,
                "files": [
                    {"caminho": f"{item_id}_baseColor.png", "papel": "textura"},
                    {"caminho": f"{item_id}_normal.png", "papel": "normal"},
                    {"caminho": f"{item_id}_orm.png", "papel": "orm"},
                ],
            }
        ),
        encoding="utf-8",
    )
    sa_v6_sem_r = rbx.exportar_surface_appearance(man_v6_sem_r)
    assert "RoughnessMap" not in sa_v6_sem_r["mapas"]


def test_remover_imagens_embutidas_glb_preserva_sha256_em_disco_i4(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    glb_original = _construir_glb_com_textura_embutida()
    glb_path = tmp_path / "bastion_signed.glb"
    glb_path.write_bytes(glb_original)
    sha256_antes = hashlib.sha256(glb_path.read_bytes()).hexdigest()

    glb_limpo, stats = upload.remover_imagens_embutidas_glb(glb_original)
    assert stats["imagens_removidas"] == 1
    assert stats["texturas_removidas"] == 1
    assert stats["bytes_depois"] < stats["bytes_antes"]
    assert len(glb_limpo) % 4 == 0

    tam_json = struct.unpack_from("<I", glb_limpo, 12)[0]
    gltf_limpo = json.loads(glb_limpo[20 : 20 + tam_json].decode("utf-8"))
    assert "images" not in gltf_limpo
    assert "textures" not in gltf_limpo
    assert "samplers" not in gltf_limpo
    attrs = gltf_limpo["meshes"][0]["primitives"][0]["attributes"]
    assert attrs == {"POSITION": 0, "NORMAL": 1, "TEXCOORD_0": 2, "TANGENT": 3}

    # Upload com strip_embedded_textures=True usa buffer em memoria sem alterar arquivo assinado (I4)
    monkeypatch.setenv("FORGE3D_ROBLOX_CREATOR_ID", "123456")
    rel_dry = upload.executar(
        glb_path,
        asset_type="Model",
        dry_run=True,
        strip_embedded_textures=True,
    )
    assert rel_dry["ok"] is True
    assert rel_dry["bytes"] == len(glb_limpo)
    assert rel_dry["strip_embedded_textures"]["imagens_removidas"] == 1
    assert hashlib.sha256(glb_path.read_bytes()).hexdigest() == sha256_antes


def test_rbxmx_meshpart_pbr_e_manifesto_luau_strict(tmp_path: Path) -> None:
    saida_rbxmx = tmp_path / "bastion_pbr.rbxmx"
    rel_mp = rbx.exportar_meshpart_pbr_rbxmx(
        nome="CitadelBastionL5",
        mesh_id="93722450747257",
        mapas_pbr={
            "ColorMap": "101",
            "NormalMap": "102",
            "RoughnessMap": "103",
            "MetalnessMap": "104",
        },
        render_fidelity="Precise",
        collision_fidelity="Box",
        tamanho_studs=(18.0, 12.0, 6.0),
        saida=saida_rbxmx,
    )
    assert rel_mp["ok"] is True
    assert saida_rbxmx.is_file()
    raiz = ET.fromstring(saida_rbxmx.read_text(encoding="utf-8"))
    mp = raiz.find("Item[@class='MeshPart']")
    assert mp is not None
    assert mp.findtext("Properties/string[@name='Name']") == "CitadelBastionL5"
    assert mp.findtext("Properties/token[@name='RenderFidelity']") == "1"
    assert mp.findtext("Properties/token[@name='CollisionFidelity']") == "2"
    assert mp.findtext("Properties/Content[@name='MeshId']/url") == "rbxassetid://93722450747257"
    sa = mp.find("Item[@class='SurfaceAppearance']")
    assert sa is not None
    assert sa.findtext("Properties/Content[@name='ColorMap']/url") == "rbxassetid://101"
    assert sa.findtext("Properties/Content[@name='NormalMap']/url") == "rbxassetid://102"
    assert sa.findtext("Properties/Content[@name='RoughnessMap']/url") == "rbxassetid://103"
    assert sa.findtext("Properties/Content[@name='MetalnessMap']/url") == "rbxassetid://104"

    saida_luau = tmp_path / "PbrAssets.luau"
    rel_luau = rbx.exportar_manifesto_luau_pbr(
        {
            "citadel.bastion.l5": {
                "meshId": 93722450747257,
                "colorMap": "rbxassetid://101",
                "normalMap": 102,
                "roughnessMap": 103,
                "metalnessMap": 104,
            }
        },
        saida=saida_luau,
    )
    assert rel_luau["ok"] is True
    luau_txt = saida_luau.read_text(encoding="utf-8")
    assert luau_txt.startswith("--!strict\n")
    assert "return table.freeze({" in luau_txt
    assert '["citadel.bastion.l5"] = table.freeze({' in luau_txt
    assert "meshId = 93722450747257," in luau_txt
    assert "roughnessMap = 103," in luau_txt
    assert "metalnessMap = 104," in luau_txt


@pytest.mark.blender
def test_blender_detalhe_alto_pbr_zonas_e_alpha_cards(tmp_path: Path) -> None:
    saida = tmp_path / "saida_zonas"
    saida.mkdir()
    meta_path = tmp_path / "meta_zonas.json"
    nome_base = "prop.citadel.cannon.01"

    codigo = f"""
import json, sys
sys.path.insert(0, {str(RAIZ / "blender")!r})
import bpy, bmesh
import postprocess, bake_pbr

postprocess.limpar_cena()
bpy.ops.mesh.primitive_cube_add(size=1.2)
obj = bpy.context.active_object

# Subdivide cubo base e pinta 2 zonas cromaticas em Color attribute (#5C6066 pedra, #F59E0B ouro)
bm = bmesh.new()
bm.from_mesh(obj.data)
bmesh.ops.subdivide_edges(bm, edges=list(bm.edges), cuts=3, use_grid_fill=True)
bm.to_mesh(obj.data)
bm.free()
obj.data.update()

ca = obj.data.color_attributes.new("Color", "FLOAT_COLOR", "POINT")
for i, v in enumerate(obj.data.vertices):
    if v.co.z >= 0.0:
        ca.data[i].color = (0.96, 0.62, 0.04, 1.0)
    else:
        ca.data[i].color = (0.36, 0.38, 0.40, 1.0)

zonas = [
    {{"nome": "pedra", "cor_hex": "#5C6066", "preset": "pedra_musgo"}},
    {{
        "nome": "ouro",
        "cor_hex": "#F59E0B",
        "uv_faixa": [0.0, 0.0, 1.0, 1.0],
        "preset": "ouro_ornamentado",
        "metallic_override": 0.92,
        "roughness_escala": 0.6,
        "normal_forca": 1.2,
    }},
]
detalhe = {{
    "ativo": True,
    "subdiv_niveis": 1,
    "chanfro_bevel_m": 0.01,
    "crease_angulo_graus": 35.0,
    "ao_cavidade_forca": 0.4,
}}

res = bake_pbr.executar_bake_high_low(
    obj=obj,
    saida_dir={str(saida)!r},
    nome_base={nome_base!r},
    px=256,
    limite_triangulos=400,
    reparo_fn=postprocess.reparar_malha,
    decimar_fn=postprocess.decimar,
    suavizar_fn=postprocess.suavizar_por_angulo,
    uv_fn=postprocess.desdobrar_uv,
    perfil_nome="roblox-aa-80",
    detalhe_alto=detalhe,
    pbr_zonas=zonas,
)

# Testa alpha_cards: preserva bordas abertas na malha visual mas fecha colisor convexo
bpy.ops.mesh.primitive_plane_add(size=1.0)
card_obj = bpy.context.active_object
postprocess.reparar_malha(card_obj, permitir_bordas_abertas=True)
geom_card = postprocess.medir_geometria(card_obj, permitir_bordas_abertas=True)
cols = postprocess.criar_colisor(card_obj, "convex", "card_test", 4)
geom_col = postprocess.medir_geometria(cols[0], permitir_bordas_abertas=False)

res["card_check"] = {{
    "materiais_low": len(obj.data.materials),
    "card_bordas_abertas": geom_card["bordas_abertas"],
    "card_nao_manifold_permitido": geom_card["nao_manifold"],
    "colisor_nao_manifold": geom_col["nao_manifold"],
}}

with open({str(meta_path)!r}, "w", encoding="utf-8") as fh:
    json.dump(res, fh)
print("ZONAS_BLENDER_OK")
"""
    proc = _rodar_blender_py(codigo, timeout=180)
    assert proc.returncode == 0 and "ZONAS_BLENDER_OK" in proc.stdout, proc.stdout + proc.stderr

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["bake"]["detalhe_alto"]["aplicado"] is True
    assert meta["bake"]["detalhe_alto"]["tris_high_enriquecido"] > meta["bake"]["detalhe_alto"][
        "tris_high_inicial"
    ]
    assert meta["bake"]["pbr_zonas"] == 2
    assert meta["card_check"]["materiais_low"] == 1
    assert meta["card_check"]["card_bordas_abertas"] >= 4
    assert meta["card_check"]["card_nao_manifold_permitido"] == 0
    assert meta["card_check"]["colisor_nao_manifold"] == 0

    papeis = {a["papel"]: a["caminho"] for a in meta["arquivos_textura"]}
    assert set(papeis) == {"textura", "normal", "orm", "roughness", "metallic"}
    for cam in papeis.values():
        with Image.open(saida / cam) as im:
            assert im.size == (256, 256)
            assert im.mode == "RGB"
    with Image.open(saida / papeis["metallic"]) as im_met:
        r_ext, _, _ = im_met.getextrema()
        assert r_ext[1] > 150, f"zona metalica ouro nao assada no mapa metallic: {r_ext}"


def test_obelisk_aa_v3_esfera_32_segmentos_sem_intersecao_com_coroa(tmp_path: Path) -> None:
    from forge3d import qc, vault

    glb_path = tmp_path / "runestone_obelisk.glb"
    vault.construir_obelisk_aa_manifold_glb(glb_path)
    gltf, binario = qc.ler_glb_bin(glb_path)
    topo = qc.topologia(gltf, binario)
    assert topo["nao_manifold"] == 0
    assert topo["degeneradas"] == 0
    assert topo["triangulos"] >= 1200

    prim = gltf["meshes"][0]["primitives"][0]
    pos = qc._accessor(gltf, binario, prim["attributes"]["POSITION"])
    uvs = qc._accessor(gltf, binario, prim["attributes"]["TEXCOORD_0"])
    ys_gema = [p[1] for p, uv in zip(pos, uvs) if uv[0] >= 0.67]
    ys_fuste = [p[1] for p, uv in zip(pos, uvs) if 0.34 <= uv[0] < 0.67]
    assert len(ys_gema) >= 400
    assert len(ys_fuste) >= 150
    assert min(ys_gema) > max(ys_fuste) + 0.003, (
        f"V3: coroa do obelisco ({max(ys_fuste):.4f}) intercepta a gema ({min(ys_gema):.4f})"
    )


def test_visual_qa_critic_detecta_v1_v2_e_aprova_v091() -> None:
    import importlib.util

    spec_mod = importlib.util.spec_from_file_location(
        "visual_qa_critic_mod",
        RAIZ / "tools" / "visual_qa_critic.py",
    )
    assert spec_mod and spec_mod.loader
    vqa = importlib.util.module_from_spec(spec_mod)
    spec_mod.loader.exec_module(vqa)

    old_hero = RAIZ / "docs" / "preview" / "v09_aa_hero_1600.png"
    if old_hero.is_file():
        rel_old = vqa.avaliar_turntable_png(old_hero, usar_gemini=False)
        txt_old = " ".join(rel_old["defeitos"])
        assert rel_old["aprovado"] is False
        assert "boot_interpenetration" in txt_old
        assert "tunic_texture_step" in txt_old

    for nome_ok in ("v091_aa_prop_1600.png", "v091_aa_roblox_1600.png", "v091_aa_hero_1600.png"):
        p_ok = RAIZ / "docs" / "preview" / nome_ok
        if p_ok.is_file():
            rel_ok = vqa.avaliar_turntable_png(p_ok, usar_gemini=False)
            assert rel_ok["aprovado"] is True, f"{nome_ok} reprovado: {rel_ok['defeitos']}"

