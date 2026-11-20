"""Testes Roblox PBR SurfaceAppearance, acessorios e rota R15 segmentada (F08/F09)."""

from __future__ import annotations

import json
from xml.etree import ElementTree

import pytest

from forge3d import config, rbx
from forge3d.cli.comandos import despachar
from forge3d.errors import ForgeError


@pytest.fixture(autouse=True)
def _isolar_allowlist(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE3D_HOME", str(tmp_path / "forge_home"))
    monkeypatch.setenv("FORGE3D_CONFIG", str(tmp_path / "forge_cfg"))
    config.adicionar(tmp_path)


def test_surface_appearance_xml_e_r15_com_pbr(tmp_path):
    """Gera SurfaceAppearance valido quando existem texturas PBR e preserva materiais_max: 1."""
    from forge3d import profiles

    assert profiles.carregar("roblox-r15")["validacao"]["materiais_max"] == 1
    assert rbx.surface_appearance_xml({}) == ""
    assert rbx.descobrir_texturas_pbr(tmp_path, "personagem.r15.guard.01") == {}

    tex_dir = tmp_path / "tex"
    tex_dir.mkdir()
    for sufixo in ("baseColor", "normal", "roughness", "metalness"):
        (tex_dir / f"personagem.r15.guard.01_{sufixo}.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    mapas = rbx.descobrir_texturas_pbr(tex_dir, "personagem.r15.guard.01")
    assert mapas == {
        "ColorMap": "personagem.r15.guard.01_baseColor.png",
        "NormalMap": "personagem.r15.guard.01_normal.png",
        "RoughnessMap": "personagem.r15.guard.01_roughness.png",
        "MetalnessMap": "personagem.r15.guard.01_metalness.png",
    }

    sa_rbxmx = tmp_path / "sa.rbxmx"
    rel_sa = rbx.exportar_surface_appearance(tex_dir, "personagem.r15.guard.01", saida=sa_rbxmx)
    assert rel_sa["ok"] is True and rel_sa["materiais"] == 1
    sa_raiz = ElementTree.fromstring(sa_rbxmx.read_text(encoding="utf-8"))
    sa_item = sa_raiz.find("Item[@class='SurfaceAppearance']")
    assert sa_item is not None
    assert sa_item.findtext("Properties/Content[@name='ColorMap']/url") == "personagem.r15.guard.01_baseColor.png"
    assert sa_item.findtext("Properties/Content[@name='NormalMap']/url") == "personagem.r15.guard.01_normal.png"
    assert sa_item.findtext("Properties/Content[@name='RoughnessMap']/url") == "personagem.r15.guard.01_roughness.png"
    assert sa_item.findtext("Properties/Content[@name='MetalnessMap']/url") == "personagem.r15.guard.01_metalness.png"

    rbxlx_pbr = tmp_path / "r15_pbr.rbxlx"
    rel_pbr = rbx.exportar_r15(
        "examples/lote_09_r15.yaml",
        "personagem.r15.guard.01",
        saida=rbxlx_pbr,
        texturas_dir=tex_dir,
    )
    assert rel_pbr["textura"] is True
    raiz = ElementTree.fromstring(rbxlx_pbr.read_text(encoding="utf-8"))
    referents = [e.get("referent") for e in raiz.iter("Item") if e.get("referent")]
    assert len(referents) == len(set(referents))
    modelo = next(e for e in raiz.iter("Item") if e.get("class") == "Model")
    hrps = modelo.findall("Item[@class='Part']")
    assert len(hrps) == 1
    assert hrps[0].findtext("Properties/string[@name='Name']") == "HumanoidRootPart"
    assert len(hrps[0].findall("Item[@class='SurfaceAppearance']")) == 0
    meshparts = modelo.findall("Item[@class='MeshPart']")
    assert len(meshparts) == 15
    for parte in meshparts:
        assert len(parte.findall("Item[@class='SurfaceAppearance']")) == 1
    place = rbx.ler_place(rbxlx_pbr)
    assert len(place["surface_appearances"]) == 15


def test_cli_export_surface_pasta_e_manifesto(tmp_path, capsys):
    """CLI export-surface aceita manifesto ou pasta publicada com _baseColor/_normal/_orm."""
    pub = tmp_path / "pub"
    pub.mkdir()
    asset_id = "hero.sentinel.01"
    for sufixo in ("baseColor", "normal", "orm"):
        (pub / f"{asset_id}_{sufixo}.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    manifesto = pub / f"{asset_id}.manifest.json"
    manifesto.write_text(
        json.dumps(
            {
                "schema": "forge3d/manifest@3",
                "asset_id": asset_id,
                "files": [
                    {"caminho": f"{asset_id}_baseColor.png", "papel": "textura"},
                    {"caminho": f"{asset_id}_normal.png", "papel": "normal"},
                    {"caminho": f"{asset_id}_orm.png", "papel": "orm"},
                ],
            },
            indent=1,
        ),
        encoding="utf-8",
    )

    rc = despachar(["export-surface", str(manifesto)])
    assert rc == 0
    stdout = capsys.readouterr().out
    assert "ColorMap,NormalMap,RoughnessMap" in stdout
    esperado_default = pub / f"{asset_id}_surface.rbxmx"
    assert esperado_default.is_file()
    sas = rbx.ler_place(esperado_default)["surface_appearances"]
    assert len(sas) == 1
    assert sas[0]["ColorMap"] == f"{asset_id}_baseColor.png"
    assert sas[0]["NormalMap"] == f"{asset_id}_normal.png"
    assert sas[0]["RoughnessMap"] == f"{asset_id}_orm.png"
    assert sas[0]["MetalnessMap"] is None

    custom_sa = tmp_path / "custom_sa.rbxmx"
    rc = despachar(
        [
            "export-surface",
            str(pub),
            "--item",
            asset_id,
            "--saida",
            str(custom_sa),
            "--json",
        ]
    )
    assert rc == 0
    rel = json.loads(capsys.readouterr().out)
    assert rel["ok"] is True
    assert rel["materiais"] == 1
    assert rel["saida"] == str(custom_sa)
    assert rel["mapas"] == {
        "ColorMap": f"{asset_id}_baseColor.png",
        "NormalMap": f"{asset_id}_normal.png",
        "RoughnessMap": f"{asset_id}_orm.png",
    }
    assert custom_sa.is_file()

    rel_mem = rbx.exportar_surface_appearance(manifesto)
    assert rel_mem["saida"] is None
    assert rel_mem["mapas"] == rel["mapas"]

    rc = despachar(["export-surface", str(manifesto), "--item", "outro.id", "--json"])
    assert rc == 2
    assert json.loads(capsys.readouterr().out)["erro"]["codigo"] == "FORGE-E-SPEC"


def test_cli_export_r15_com_texturas_dir(tmp_path, capsys):
    """CLI export-r15 --texturas-dir anexa SurfaceAppearance nas 15 partes visiveis."""
    tex_dir = tmp_path / "tex"
    tex_dir.mkdir()
    for sufixo in ("baseColor", "normal", "orm"):
        (tex_dir / f"personagem.r15.guard.01_{sufixo}.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    saida = tmp_path / "guard_pbr.rbxlx"
    rc = despachar(
        [
            "export-r15",
            "examples/lote_09_r15.yaml",
            "--item",
            "personagem.r15.guard.01",
            "--texturas-dir",
            str(tex_dir),
            "--saida",
            str(saida),
            "--json",
        ]
    )
    assert rc == 0
    rel = json.loads(capsys.readouterr().out)
    assert rel["ok"] is True
    assert rel["textura"] is True
    assert rel["surface_appearance"] == {
        "ColorMap": "personagem.r15.guard.01_baseColor.png",
        "NormalMap": "personagem.r15.guard.01_normal.png",
        "RoughnessMap": "personagem.r15.guard.01_orm.png",
    }
    place = rbx.ler_place(saida)
    assert len(place["surface_appearances"]) == 15
    assert all(sa["ColorMap"] == "personagem.r15.guard.01_baseColor.png" for sa in place["surface_appearances"])
    assert all(sa["RoughnessMap"] == "personagem.r15.guard.01_orm.png" for sa in place["surface_appearances"])

    saida2 = tmp_path / "guard_pbr_txt.rbxlx"
    rc2 = despachar(
        [
            "export-r15",
            "examples/lote_09_r15.yaml",
            "--item",
            "personagem.r15.guard.01",
            "--texturas-dir",
            str(tex_dir),
            "--saida",
            str(saida2),
        ]
    )
    assert rc2 == 0
    assert "+SurfaceAppearance" in capsys.readouterr().out


def test_surface_appearance_injeta_rbxassetid_por_mapa_e_ledger(tmp_path):
    """surface_appearance_xml e exportar_surface_appearance aceitam asset_ids e ledger."""
    xml = rbx.surface_appearance_xml(
        {"ColorMap": "hero_baseColor.png", "NormalMap": "hero_normal.png", "RoughnessMap": "hero_orm.png"},
        asset_ids={"ColorMap": "111222333", "hero_normal.png": "rbxassetid://444555666"},
    )
    sa_node = ElementTree.fromstring(xml)
    assert sa_node.findtext("Properties/Content[@name='ColorMap']/url") == "rbxassetid://111222333"
    assert sa_node.findtext("Properties/Content[@name='NormalMap']/url") == "rbxassetid://444555666"
    assert sa_node.findtext("Properties/Content[@name='RoughnessMap']/url") == "hero_orm.png"

    pub = tmp_path / "pub"
    pub.mkdir()
    asset_id = "set.silvanor.peitoral.01"
    for suf in ("baseColor", "normal", "orm"):
        (pub / f"{asset_id}_{suf}.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    manifesto = pub / f"{asset_id}.manifest.json"
    manifesto.write_text(
        json.dumps(
            {
                "schema": "forge3d/manifest@3",
                "asset_id": asset_id,
                "files": [
                    {"caminho": f"{asset_id}_baseColor.png", "papel": "textura"},
                    {"caminho": f"{asset_id}_normal.png", "papel": "normal"},
                    {"caminho": f"{asset_id}_orm.png", "papel": "orm"},
                ],
            }
        ),
        encoding="utf-8",
    )
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(
        "\n".join(
            [
                json.dumps({"evento": "upload", "id": asset_id, "role": "ColorMap", "asset_id": "1001"}),
                json.dumps({"evento": "upload", "id": asset_id, "papel": "normal", "asset_id": "1002"}),
                json.dumps({"evento": "upload", "id": f"{asset_id}_orm", "asset_id": "1003"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    sa_out = tmp_path / "peitoral_sa.rbxmx"
    rel = rbx.exportar_surface_appearance(manifesto, saida=sa_out, ledger=ledger)
    assert rel["mapas"] == {
        "ColorMap": "rbxassetid://1001",
        "NormalMap": "rbxassetid://1002",
        "RoughnessMap": "rbxassetid://1003",
    }
    lido = rbx.ler_place(sa_out)["surface_appearances"][0]
    assert lido["ColorMap"] == "rbxassetid://1001"
    assert lido["NormalMap"] == "rbxassetid://1002"
    assert lido["RoughnessMap"] == "rbxassetid://1003"

    # Negative: exportar_r15 rejeita item nao-blocky sem manifesto segmentado
    lote_mesh = tmp_path / "lote_mesh.yaml"
    lote_mesh.write_text(
        "\n".join(
            [
                "schema: forge3d/spec@3",
                "projeto: demo",
                "perfil: roblox-r15",
                f"destino_exportacao: {tmp_path / 'out'}",
                "lote:",
                "  - id: personagem.mesh.01",
                "    tipo: personagem_humanoide",
                "    rota: mesh",
                "    seed: 1",
                "    prompt: guerreiro",
                "    altura_metros: 1.85",
                "    auto_rig: true",
                "    esqueleto: r15@1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ForgeError) as exc:
        rbx.exportar_r15(lote_mesh, "personagem.mesh.01")
    assert exc.value.codigo == "FORGE-E-SPEC"


def test_exportar_acessorio_rbxmx_manifesto_skinned_e_glb(tmp_path):
    """exportar_acessorio_rbxmx gera Accessory + Handle MeshPart + Attachment + SurfaceAppearance."""
    pub = tmp_path / "pub"
    pub.mkdir()
    elmo_id = "set.armadura.elmo.01"
    for suf in ("baseColor", "normal", "orm"):
        (pub / f"{elmo_id}_{suf}.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (pub / f"{elmo_id}.glb").write_bytes(b"glTF\x02\x00\x00\x00")
    man_elmo = pub / f"{elmo_id}.manifest.json"
    man_elmo.write_text(
        json.dumps(
            {
                "schema": "forge3d/manifest@3",
                "asset_id": elmo_id,
                "geometry": {"bbox_m": [0.28, 0.56, 0.28]},
                "unidades_export": {"metros_por_unidade": 0.28, "escala_saida": 3.5714},
                "anexo": {
                    "parte": "elmo",
                    "osso": "Head",
                    "attachment_roblox": "HatAttachment",
                    "skinned": False,
                },
                "files": [
                    {"caminho": f"{elmo_id}.glb", "papel": "mesh"},
                    {"caminho": f"{elmo_id}_baseColor.png", "papel": "textura"},
                    {"caminho": f"{elmo_id}_normal.png", "papel": "normal"},
                    {"caminho": f"{elmo_id}_orm.png", "papel": "orm"},
                ],
            }
        ),
        encoding="utf-8",
    )
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(
        "\n".join(
            [
                json.dumps({"evento": "upload", "id": elmo_id, "role": "mesh", "asset_id": "777001"}),
                json.dumps({"evento": "upload", "id": elmo_id, "role": "ColorMap", "asset_id": "777002"}),
                json.dumps({"evento": "upload", "id": elmo_id, "role": "NormalMap", "asset_id": "777003"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    out_elmo = tmp_path / "elmo.rbxmx"
    rel = rbx.exportar_acessorio_rbxmx(man_elmo, saida=out_elmo, ledger=ledger)
    assert rel["ok"] is True
    assert rel["attachment"] == "HatAttachment"
    assert rel["skinned"] is False
    assert rel["mesh_id"] == "rbxassetid://777001"
    assert rel["materiais"] == 1
    assert rel["mapas"] == {
        "ColorMap": "rbxassetid://777002",
        "NormalMap": "rbxassetid://777003",
        "RoughnessMap": f"{elmo_id}_orm.png",
    }

    raiz = ElementTree.fromstring(out_elmo.read_text(encoding="utf-8"))
    acc = raiz.find("Item[@class='Accessory']")
    assert acc is not None
    handle = acc.find("Item[@class='MeshPart']")
    assert handle is not None
    assert handle.findtext("Properties/string[@name='Name']") == "Handle"
    assert handle.findtext("Properties/Content[@name='MeshId']/url") == "rbxassetid://777001"
    size_node = handle.find("Properties/Vector3[@name='size']")
    assert float(size_node.findtext("X")) == pytest.approx(1.0, abs=1e-4)
    assert float(size_node.findtext("Y")) == pytest.approx(2.0, abs=1e-4)
    assert float(size_node.findtext("Z")) == pytest.approx(1.0, abs=1e-4)

    place = rbx.ler_place(out_elmo)
    assert place["acessorios"] == [
        {
            "nome": elmo_id,
            "handle": "Handle",
            "mesh_id": "rbxassetid://777001",
            "attachments": ["HatAttachment"],
        }
    ]
    assert len(place["surface_appearances"]) == 1
    assert place["surface_appearances"][0]["parte"] == "Handle"
    assert handle.find("Item[@class='WeldConstraint']") is not None

    glb_peito = pub / "peito.glb"
    glb_peito.write_bytes(b"glTF\x02\x00\x00\x00")
    (pub / "peito_baseColor.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    rel_sk = rbx.exportar_acessorio_rbxmx(
        glb_peito,
        attachment_name="BodyFrontAttachment",
        skinned=True,
        asset_ids={"mesh": "888001", "ColorMap": "888002"},
    )
    assert rel_sk["skinned"] is True
    assert rel_sk["attachment"] == "BodyFrontAttachment"
    assert rel_sk["mesh_id"] == "rbxassetid://888001"
    assert rel_sk["mapas"] == {"ColorMap": "rbxassetid://888002"}
    assert "WeldConstraint" not in rel_sk["xml"]

    out_bone = tmp_path / "r15_bone.rbxlx"
    rel_bone = rbx.exportar_r15(
        "examples/lote_09_r15.yaml",
        "personagem.r15.guard.01",
        saida=out_bone,
        modo_rig="bone",
    )
    assert rel_bone["modo_rig"] == "bone"
    assert rel_bone["partes"] == 1
    raiz_bone = ElementTree.fromstring(out_bone.read_text(encoding="utf-8"))
    assert len(raiz_bone.findall(".//Item[@class='Bone']")) == 16
    assert raiz_bone.find(".//Item[@class='Animator']") is not None

    with pytest.raises(ForgeError) as exc_mnt:
        rbx.exportar_acessorio_rbxmx(glb_peito, saida="/mnt/c/temp/elmo.rbxmx")
    assert exc_mnt.value.codigo == "FORGE-E-PATH"


def test_exportar_r15_segmentada_autodiscover_manifesto_e_motor6d(tmp_path):
    """F08: auto-descobre manifesto em destino_exportacao e monta C0/C1 consistentes sem OrmPacked."""
    dest = tmp_path / "pub_dest"
    dest.mkdir()
    item_id = "boss.seg.auto.01"
    partes_nomes = list(rbx.JOINT_R15.keys())
    ancoras = {
        "LowerTorso": [0.0, 3.0, 0.0],
        "UpperTorso": [0.0, 4.0, 0.0],
        "Head": [0.0, 5.2, 0.0],
        "LeftUpperArm": [1.5, 4.8, 0.0],
        "LeftLowerArm": [1.8, 3.8, 0.0],
        "LeftHand": [1.8, 2.8, 0.0],
        "RightUpperArm": [-1.5, 4.8, 0.0],
        "RightLowerArm": [-1.8, 3.8, 0.0],
        "RightHand": [-1.8, 2.8, 0.0],
        "LeftUpperLeg": [0.5, 2.5, 0.0],
        "LeftLowerLeg": [0.5, 1.4, 0.0],
        "LeftFoot": [0.5, 0.4, 0.0],
        "RightUpperLeg": [-0.5, 2.5, 0.0],
        "RightLowerLeg": [-0.5, 1.4, 0.0],
        "RightFoot": [-0.5, 0.4, 0.0],
    }
    manifesto = {
        "schema": "forge3d/manifest@6",
        "asset_id": item_id,
        "partes": [
            {
                "nome": n,
                "junta": rbx.JOINT_R15[n],
                "ancora": ancoras[n],
                "bbox": [1.0, 1.2, 0.8],
                "arquivo": f"{n}.glb",
            }
            for n in partes_nomes
        ],
        "rig": {"esqueleto": "r15@1", "ossos": 16, "modo": "motor6d", "ancoras": ancoras},
        "files": [
            {"caminho": f"{item_id}_baseColor.png", "papel": "textura"},
            {"caminho": f"{item_id}_normal.png", "papel": "normal"},
            {"caminho": f"{item_id}_roughness.png", "papel": "roughness"},
            {"caminho": f"{item_id}_metallic.png", "papel": "metallic"},
            {"caminho": f"{item_id}_orm.png", "papel": "orm"},
        ],
    }
    (dest / f"{item_id}.manifest.json").write_text(json.dumps(manifesto), encoding="utf-8")
    lote = tmp_path / "lote_auto.yaml"
    lote.write_text(
        "\n".join(
            [
                "schema: forge3d/spec@6",
                "projeto: demo",
                "perfil: roblox-aa-80",
                f"destino_exportacao: {dest}",
                "lote:",
                f"  - id: {item_id}",
                "    tipo: criatura",
                "    rota: mesh",
                "    prompt: golem segmentado",
                "    seed: 7",
                "    altura_metros: 2.0",
                "    auto_rig: true",
                "    esqueleto: r15@1",
                "    partes:",
                *[f"      - nome: {n}" for n in partes_nomes],
                "    rig:",
                "      modo: motor6d",
                "      esqueleto: r15@1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "boss_auto.rbxlx"
    rel = rbx.exportar_r15(lote, item_id, saida=out)
    assert rel["partes"] == 16 and rel["motores"] == 15
    assert rel["surface_appearance"]["RoughnessMap"] == f"{item_id}_roughness.png"

    place = rbx.ler_place(out)
    waist = next(m for m in place["motores"] if m["nome"] == "Waist")
    assert waist["c0"] == pytest.approx([0.0, 1.0, 0.0], abs=1e-4)
    assert waist["c1"] == pytest.approx([0.0, 0.0, 0.0], abs=1e-4)
