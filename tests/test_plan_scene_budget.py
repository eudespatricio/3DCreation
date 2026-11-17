"""Testes unitarios e de regressao para o estimador calibrado de ``plan --scene-budget``."""

from __future__ import annotations

import json
import struct
from io import BytesIO
from pathlib import Path

from PIL import Image
import yaml

from forge3d import config, plan, profiles, spec
from forge3d.cli.main import main

RAIZ = Path(__file__).resolve().parents[1]


def _glb_com_tris(
    n_tris: int,
    *,
    skinned: bool = False,
    imagens_px: list[int] | None = None,
    tem_uv: bool = True,
) -> bytes:
    """Gera um GLB minimo valido com ``n_tris`` triangulos nos accessors e imagens opcionais."""
    n_verts = max(3, n_tris * 3)
    buf = bytearray()
    bvs: list[dict] = []

    def _push(raw: bytes) -> int:
        while len(buf) % 4 != 0:
            buf.append(0)
        off = len(buf)
        buf.extend(raw)
        bvs.append({"buffer": 0, "byteOffset": off, "byteLength": len(raw)})
        return len(bvs) - 1

    bv_pos = _push(b"\x00" * (n_verts * 12))
    bv_idx = _push(b"\x00" * (n_tris * 3 * 2))
    accs = [
        {"bufferView": bv_pos, "componentType": 5126, "count": n_verts, "type": "VEC3"},
        {"bufferView": bv_idx, "componentType": 5123, "count": n_tris * 3, "type": "SCALAR"},
    ]
    attrs: dict[str, int] = {"POSITION": 0}
    if tem_uv:
        bv_uv = _push(b"\x00" * (n_verts * 8))
        accs.append({"bufferView": bv_uv, "componentType": 5126, "count": n_verts, "type": "VEC2"})
        attrs["TEXCOORD_0"] = 2

    images: list[dict] = []
    for px in imagens_px or []:
        bio = BytesIO()
        Image.new("RGBA", (px, px), (120, 130, 140, 255)).save(bio, format="PNG")
        bv_img = _push(bio.getvalue())
        images.append({"bufferView": bv_img, "mimeType": "image/png"})

    while len(buf) % 4 != 0:
        buf.append(0)

    gltf: dict = {
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": len(buf)}],
        "bufferViews": bvs,
        "accessors": accs,
        "materials": [{"name": "mat_0"}],
        "meshes": [{"primitives": [{"attributes": attrs, "indices": 1, "material": 0}]}],
    }
    if images:
        gltf["images"] = images
    if skinned:
        gltf["skins"] = [{"joints": [0]}]

    jbytes = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    while len(jbytes) % 4 != 0:
        jbytes += b" "
    total_len = 12 + 8 + len(jbytes) + 8 + len(buf)
    header = struct.pack("<3I", 0x46546C67, 2, total_len)
    c0 = struct.pack("<2I", len(jbytes), 0x4E4F534A) + jbytes
    c1 = struct.pack("<2I", len(buf), 0x004E4942) + bytes(buf)
    return header + c0 + c1


def _err_pct(estimado: float, medido: float) -> float:
    return abs(estimado - medido) / max(1e-9, medido) * 100.0


def test_separacao_teto_e_estimativa_e_retrocompatibilidade(capsys):
    lote13 = RAIZ / "examples" / "lote_13_scene_budget_aa.yaml"
    assert main(["plan", str(lote13), "--scene-budget", "--json"]) == 0
    rel = json.loads(capsys.readouterr().out)
    orc = rel["orcamento_cena"]

    # Retrocompatibilidade: chaves antigas preservadas no bloco `medido` (teto pior caso)
    assert orc["status"] == "ok"
    assert orc["medido"]["triangulos_cena"] == 350400
    assert orc["teto_pior_caso"]["triangulos_cena"] == 350400
    assert orc["teto_pior_caso"]["vram_texturas_mb"] == 68.0
    assert orc["nao_bloqueante"] is True

    # Estimativa calibrada para lote_13 (blocky)
    est = orc["estimativa"]
    assert est["status"] == "ok"
    assert est["triangulos_cena"] == 15516
    assert est["draw_calls_estimados"] == 10
    assert est["vram_texturas_mb"] == 0.08


def test_cli_texto_exibe_estimativa_e_teto_rotulados(capsys):
    lote13 = RAIZ / "examples" / "lote_13_scene_budget_aa.yaml"
    assert main(["plan", str(lote13), "--scene-budget"]) == 0
    out = capsys.readouterr().out
    assert "orcamento_cena estimativa [ok]: 15516/400000 tris" in out
    assert "0.08/200.0 MB VRAM" in out
    assert "orcamento_cena teto_pior_caso [ok]: 350400/400000 tris" in out
    assert "68.0/200.0 MB VRAM" in out


def test_plan_permanece_nao_bloqueante_mesmo_acima_do_teto(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("FORGE3D_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("FORGE3D_CONFIG", str(tmp_path / "cfg" / "config.yaml"))
    destino = tmp_path / "saida_plan"
    config.adicionar(tmp_path)

    lote = tmp_path / "lote_alto.yaml"
    lote.write_text(
        yaml.safe_dump(
            {
                "schema": "forge3d/spec@6",
                "projeto": "plan_non_gating",
                "perfil": "roblox-aa-80",
                "destino_exportacao": str(destino),
                "orcamento_cena": {"triangulos_max": 10000, "draw_calls_max": 50, "vram_mb_max": 20},
                "lote": [
                    {
                        "id": "horde.mob.01",
                        "tipo": "criatura",
                        "rota": "blocky",
                        "altura_metros": 1.0,
                        "pivot": "base",
                        "limite_triangulos": 2400,
                        "quantidade_cena": 10,
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    assert main(["plan", str(lote), "--scene-budget", "--json"]) == 0
    rel = json.loads(capsys.readouterr().out)
    orc = rel["orcamento_cena"]
    assert orc["teto_pior_caso"]["status"] == "falhou"
    assert orc["teto_pior_caso"]["triangulos_cena"] == 24000
    assert orc["estimativa"]["status"] == "ok"
    assert orc["estimativa"]["triangulos_cena"] == 3000


def test_estimador_por_rota_import_obj_gltf_modular_e_mesh(tmp_path):
    perfil = profiles.carregar("godot4-aa")

    obj_path = tmp_path / "prop.obj"
    obj_path.write_text(
        "v 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\nvt 0 0\nf 1/1 2/1 3/1 4/1\n",
        encoding="utf-8",
    )
    glb_sem_pbr = tmp_path / "raw.glb"
    glb_sem_pbr.write_bytes(_glb_com_tris(240, skinned=True, imagens_px=[512], tem_uv=True))

    gltf_path = tmp_path / "mesa.gltf"
    gltf_path.write_text(
        json.dumps(
            {
                "asset": {"version": "2.0"},
                "accessors": [{"count": 90}, {"count": 180}],
                "materials": [{"name": "m"}],
                "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "TEXCOORD_0": 1}, "indices": 1}]}],
            }
        ),
        encoding="utf-8",
    )

    spec_doc = {
        "schema": "forge3d/spec@6",
        "lote": [
            {
                "id": "imp.obj.01",
                "tipo": "prop_estatico",
                "rota": "import",
                "origem": str(obj_path),
                "limite_triangulos": 5000,
                "quantidade_cena": 3,
                "material": "pbr",
            },
            {
                "id": "imp.glb.01",
                "tipo": "criatura",
                "rota": "import",
                "origem": str(glb_sem_pbr),
                "limite_triangulos": 5000,
                "quantidade_cena": 2,
                "material": "padrao",
            },
            {
                "id": "imp.gltf.01",
                "tipo": "prop_estatico",
                "rota": "import",
                "origem": str(gltf_path),
                "limite_triangulos": 5000,
                "quantidade_cena": 1,
                "material": "padrao",
            },
            {
                "id": "mod.setor.01",
                "tipo": "mapa_setor",
                "rota": "modular",
                "limite_triangulos": 40000,
                "quantidade_cena": 4,
                "seed": 42,
                "modular": {"grade": [2, 2], "setor": [0, 0]},
            },
            {
                "id": "mesh.extrude.01",
                "tipo": "prop_equipavel",
                "rota": "mesh",
                "parte": "arma",
                "extrudir_2d": True,
                "limite_triangulos": 2000,
                "quantidade_cena": 2,
            },
            {
                "id": "mesh.cabelo.01",
                "tipo": "prop_estatico",
                "rota": "mesh",
                "origem": "makehuman://hair/short01",
                "limite_triangulos": 4000,
                "quantidade_cena": 1,
            },
        ],
    }

    orc = plan.estimar_orcamento_cena(spec_doc, perfil)
    por_id = {it["id"]: it for it in orc["estimativa"]["itens"]}

    # OBJ com 1 quad -> 2 tris * 3 copias = 6 tris
    assert por_id["imp.obj.01"]["tris_unit"] == 2
    assert por_id["imp.obj.01"]["fonte"] == "obj_header"

    # GLB com skin e 1 imagem 512px sem bake PBR -> 240 tris, skinned -> 2 draw calls
    assert por_id["imp.glb.01"]["tris_unit"] == 240
    assert por_id["imp.glb.01"]["skinned"] is True
    assert por_id["imp.glb.01"]["draw_calls"] == 2
    assert por_id["imp.glb.01"]["vram_mb"] == 0.33

    # GLTF com indices=180 -> 60 tris
    assert por_id["imp.gltf.01"]["tris_unit"] == 60
    assert por_id["imp.gltf.01"]["fonte"] == "gltf_header"

    # Modular WFC deterministico -> 24..48 tris
    assert 24 <= por_id["mod.setor.01"]["tris_unit"] <= 48
    assert por_id["mod.setor.01"]["fonte"] == "modular_wfc"

    # Mesh extrude_2d e makehuman cabelo
    assert por_id["mesh.extrude.01"]["tris_unit"] == 1800
    assert por_id["mesh.cabelo.01"]["tris_unit"] == 2500


def test_regressao_calibracao_tres_lotes_erro_abaixo_50_pct(tmp_path):
    # 1. lote_13 (medido: 15516 tris, 10 dc, 0.08 MB)
    doc_13 = spec.carregar_arquivo(RAIZ / "examples" / "lote_13_scene_budget_aa.yaml")
    s13, p13, _ = spec.preparar(doc_13)
    est_13 = plan.estimar_orcamento_cena(s13, p13)["estimativa"]
    assert _err_pct(est_13["triangulos_cena"], 15516) < 50.0
    assert _err_pct(est_13["draw_calls_estimados"], 10) < 50.0
    assert _err_pct(est_13["vram_texturas_mb"], 0.08) < 50.0

    # Fixtures GLB autocontidas para v09_aa_godot e v09_aa_roblox (sem depender de ~/.local/state)
    obelisk_glb = tmp_path / "runestone_obelisk.glb"
    obelisk_glb.write_bytes(_glb_com_tris(136))
    fern_glb = tmp_path / "arcane_fern_cards.glb"
    fern_glb.write_bytes(_glb_com_tris(116))
    sword_glb = tmp_path / "runeblade_kitbash.glb"
    sword_glb.write_bytes(_glb_com_tris(328))

    # 2. v09_aa_godot (medido: 45108 tris, 7 dc, 53.0 MB)
    godot_spec, godot_perfil, _ = spec.preparar(
        {
            "schema": "forge3d/spec@6",
            "projeto": "citadel_godot_aa",
            "perfil": "godot4-aa",
            "destino_exportacao": str(tmp_path / "out_godot"),
            "politica": {"seed_base": 20261116},
            "lote": [
                {
                    "id": "hero.warden.aa.01",
                    "tipo": "personagem_humanoide",
                    "rota": "mesh",
                    "prompt": "Arcane warden hero",
                    "template_humanoide": True,
                    "makehuman_cabelo": "short01",
                    "qualidade": "hero",
                    "altura_metros": 1.82,
                    "pivot": "base",
                    "limite_triangulos": 16000,
                    "material": "pbr",
                    "auto_rig": True,
                    "quantidade_cena": 2,
                    "seed": 20261116,
                },
                {
                    "id": "armor.warden.gauntlets.01",
                    "tipo": "prop_equipavel",
                    "rota": "mesh",
                    "prompt": "Knight plate gauntlets",
                    "parte": "luvas",
                    "skinned": True,
                    "altura_metros": 0.30,
                    "pivot": "origem",
                    "limite_triangulos": 2500,
                    "material": "pbr",
                    "quantidade_cena": 2,
                    "seed": 20261117,
                },
                {
                    "id": "gear.warden.sword.01",
                    "tipo": "prop_equipavel",
                    "rota": "mesh",
                    "prompt": "Arcane warden longsword",
                    "parte": "arma",
                    "extrudir_2d": False,
                    "skinned": False,
                    "altura_metros": 0.98,
                    "pivot": "empunhadura",
                    "limite_triangulos": 2500,
                    "material": "pbr",
                    "quantidade_cena": 4,
                    "seed": 20261118,
                },
                {
                    "id": "prop.runestone.altar.01",
                    "tipo": "prop_estatico",
                    "rota": "import",
                    "origem": str(obelisk_glb),
                    "altura_metros": 2.20,
                    "pivot": "base",
                    "qualidade": "hero",
                    "limite_triangulos": 6000,
                    "material": "pbr",
                    "quantidade_cena": 6,
                    "detalhe_alto": {"ativo": True},
                    "pbr_zonas": [
                        {"nome": "obsidiana", "preset": "pedra_musgo", "cor_tinta": "#2A2E38"}
                    ],
                },
                {
                    "id": "prop.arcane.fern.01",
                    "tipo": "prop_estatico",
                    "rota": "import",
                    "origem": str(fern_glb),
                    "altura_metros": 0.85,
                    "pivot": "base",
                    "qualidade": "standard",
                    "limite_triangulos": 1200,
                    "material": "pbr",
                    "material_procedural": "pedra_musgo",
                    "alpha_cards": True,
                    "quantidade_cena": 16,
                },
            ],
        }
    )
    est_godot = plan.estimar_orcamento_cena(godot_spec, godot_perfil)["estimativa"]
    assert _err_pct(est_godot["triangulos_cena"], 45108) < 50.0
    assert _err_pct(est_godot["draw_calls_estimados"], 7) < 50.0
    assert _err_pct(est_godot["vram_texturas_mb"], 53.0) < 50.0

    # 3. v09_aa_roblox (medido: 6000 tris, 14 dc, 34.68 MB)
    roblox_spec, roblox_perfil, _ = spec.preparar(
        {
            "schema": "forge3d/spec@6",
            "projeto": "citadel_roblox_aa",
            "perfil": "roblox-aa-80",
            "destino_exportacao": str(tmp_path / "out_roblox"),
            "lote": [
                {
                    "id": "prop.obsidian.obelisk.01",
                    "tipo": "prop_estatico",
                    "rota": "import",
                    "origem": str(obelisk_glb),
                    "altura_metros": 2.20,
                    "pivot": "base",
                    "qualidade": "hero",
                    "limite_triangulos": 4000,
                    "material": "pbr",
                    "quantidade_cena": 8,
                    "detalhe_alto": {"ativo": True},
                    "pbr_zonas": [{"nome": "pedestal_pedra", "preset": "pedra_musgo"}],
                },
                {
                    "id": "weapon.paladin.runeblade.01",
                    "tipo": "prop_equipavel",
                    "rota": "import",
                    "origem": str(sword_glb),
                    "altura_metros": 1.18,
                    "pivot": "empunhadura",
                    "qualidade": "hero",
                    "limite_triangulos": 3200,
                    "material": "pbr",
                    "quantidade_cena": 4,
                    "detalhe_alto": {"ativo": True},
                    "pbr_zonas": [{"nome": "lamina_aco", "preset": "aco_forjado"}],
                },
                {
                    "id": "guard.citadel.warden.01",
                    "tipo": "personagem_humanoide",
                    "rota": "blocky",
                    "altura_metros": 1.85,
                    "pivot": "base",
                    "qualidade": "standard",
                    "limite_triangulos": 2400,
                    "auto_rig": True,
                    "esqueleto": "r15@1",
                    "quantidade_cena": 12,
                },
            ],
        }
    )
    est_roblox = plan.estimar_orcamento_cena(roblox_spec, roblox_perfil)["estimativa"]
    assert _err_pct(est_roblox["triangulos_cena"], 6000) < 50.0
    assert _err_pct(est_roblox["draw_calls_estimados"], 14) < 50.0
    assert _err_pct(est_roblox["vram_texturas_mb"], 34.68) < 50.0
