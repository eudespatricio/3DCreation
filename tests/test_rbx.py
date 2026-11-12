"""Testes do export nativo R15 (.rbxlx): estrutura, XML e contagens."""

from __future__ import annotations

import json
from xml.etree import ElementTree

import pytest

from forge3d import rbx
from forge3d.cli.comandos import despachar

R15 = {
    "HumanoidRootPart",
    "LowerTorso",
    "UpperTorso",
    "Head",
    "LeftUpperArm",
    "LeftLowerArm",
    "LeftHand",
    "RightUpperArm",
    "RightLowerArm",
    "RightHand",
    "LeftUpperLeg",
    "LeftLowerLeg",
    "LeftFoot",
    "RightUpperLeg",
    "RightLowerLeg",
    "RightFoot",
}


def test_export_r15_gera_place_com_16_partes_e_15_motores(tmp_path):
    saida = tmp_path / "r15.rbxlx"
    rel = rbx.exportar_r15("examples/lote_09_r15.yaml", "personagem.r15.guard.01", saida=saida)
    assert rel["ok"] is True
    assert rel["partes"] == 16
    assert rel["motores"] == 15
    assert rel["textura"] is False
    assert saida.is_file() and saida.stat().st_size == rel["bytes"]

    raiz = ElementTree.fromstring(saida.read_text(encoding="utf-8"))
    modelos = [e for e in raiz.iter("Item") if e.get("class") == "Model"]
    assert len(modelos) == 1
    modelo = modelos[0]
    partes = [e for e in modelo.findall("Item") if e.get("class") == "Part"]
    motores = [e for e in modelo.iter("Item") if e.get("class") == "Motor6D"]
    assert len(partes) == 16
    assert len(motores) == 15

    nomes = {p.findtext("./Properties/string[@name='Name']") for p in partes}
    assert nomes == R15

    for parte in partes:
        props = parte.find("Properties")
        assert props is not None
        assert props.find("Vector3[@name='size']") is not None
        assert props.find("CoordinateFrame[@name='CFrame']") is not None
        assert props.find("Color3uint8[@name='Color3uint8']") is not None

    humanoides = [e for e in modelo.findall("Item") if e.get("class") == "Humanoid"]
    assert len(humanoides) == 1
    assert modelo.find("./Properties/Ref[@name='PrimaryPart']") is not None

    for motor in motores:
        assert motor.find("./Properties/Ref[@name='Part0']") is not None
        assert motor.find("./Properties/Ref[@name='Part1']") is not None
        assert motor.find("./Properties/CoordinateFrame[@name='C0']") is not None
        assert motor.find("./Properties/CoordinateFrame[@name='C1']") is not None


def test_export_r15_gera_keyframe_sequence_do_clipe(tmp_path):
    """D69: o mesmo clipe do glb vira KeyframeSequence no place (5 chaves, 5 poses)."""
    from forge3d import animacao, profiles

    saida = tmp_path / "r15.rbxlx"
    rel = rbx.exportar_r15("examples/lote_09_r15.yaml", "personagem.r15.guard.01", saida=saida)
    assert rel["animacoes"] == ["idle"]
    assert rel["keyframes"] == {"idle": 5}

    place = rbx.ler_place(saida)
    assert len(place["clipes"]) == 1
    clipe = place["clipes"][0]
    assert clipe["nome"] == "idle" and clipe["loop"] is True
    # Core: com Idle (0) o Animator nao aplica a track por cima do que o Humanoid ja toca
    assert clipe["priority"] == 1000
    assert [c["tempo"] for c in clipe["chaves"]] == [0.0, 0.5, 1.0, 1.5, 2.0]

    esperado = animacao.clipes(profiles.carregar("roblox-r15"), "r15@1", ["idle"])[0]
    juntas = set(rbx.JOINT_R15.values())
    for chave, esperada in zip(clipe["chaves"], esperado["chaves"]):
        assert chave["tempo"] == esperada["segundos"]
        # pose COMPLETA: todas as 15 juntas do R15 (o Animator nao aplica chave parcial)
        assert {p["osso"] for p in chave["poses"]} == juntas
        dadas = {
            rbx.JOINT_R15.get(p["osso"], p["osso"]): p for p in esperada["poses"]
        }
        for pose in chave["poses"]:
            fonte = dadas.get(pose["osso"], {"graus": 0.0, "eixo": "X"})
            matriz = rbx._matriz_rotacao(fonte["graus"], fonte["eixo"])
            # o .rbxlx grava com 6 casas: a tolerancia e do formato, nao do calculo
            assert pose["cframe"][3:] == pytest.approx(matriz, abs=1e-5)


def test_export_r15_normaliza_a_altura_para_a_spec(tmp_path):
    """GAP-044: o rig sai na mesma escala do glb — 1,85 m / 0,28 m por stud = 6,6071 studs."""
    saida = tmp_path / "r15.rbxlx"
    rbx.exportar_r15("examples/lote_09_r15.yaml", "personagem.r15.guard.01", saida=saida)
    raiz = ElementTree.fromstring(saida.read_text(encoding="utf-8"))
    bases, topos = [], []
    for parte in raiz.iter("Item"):
        if parte.get("class") != "Part":
            continue
        props = parte.find("Properties")
        if props is None or props.findtext("string[@name='Name']") == "Baseplate":
            continue
        tamanho = props.find("Vector3[@name='size']")
        cframe = props.find("CoordinateFrame[@name='CFrame']")
        meio = float(tamanho.findtext("Y")) / 2
        centro = float(cframe.findtext("Y"))
        bases.append(centro - meio)
        topos.append(centro + meio)
    span = max(topos) - min(bases)
    assert abs(span - 1.85 / 0.28) < 0.01, span


def test_export_r15_attachments_transparency_e_anchored(tmp_path):
    """Pacote 4 + Onda 3: RigAttachments R15 + Hat/BodyBack/RightGrip, HumanoidRootPart transparente e Anchored."""
    from forge3d import profiles

    assert profiles.carregar("roblox-r15")["validacao"]["materiais_max"] == 1

    saida = tmp_path / "r15.rbxlx"
    rel = rbx.exportar_r15("examples/lote_09_r15.yaml", "personagem.r15.guard.01", saida=saida)
    assert rel["attachments"] == 33

    raiz = ElementTree.fromstring(saida.read_text(encoding="utf-8"))
    referents = [e.get("referent") for e in raiz.iter("Item") if e.get("referent")]
    assert len(referents) == len(set(referents)), "referents duplicados no .rbxlx"

    modelo = next(e for e in raiz.iter("Item") if e.get("class") == "Model")
    partes = {
        p.findtext("./Properties/string[@name='Name']"): p
        for p in modelo.findall("Item[@class='Part']")
    }
    assert len(partes) == 16

    for nome, parte in partes.items():
        anchored = parte.findtext("./Properties/bool[@name='Anchored']")
        transp = parte.findtext("./Properties/float[@name='Transparency']")
        if nome == "HumanoidRootPart":
            assert anchored == "true"
            assert float(transp) == pytest.approx(1.0)
        else:
            assert anchored == "false", f"{nome} deve ter Anchored=false"

    def _att_map(parte_xml):
        out = {}
        for att in parte_xml.findall("Item[@class='Attachment']"):
            n = att.findtext("./Properties/string[@name='Name']")
            cf = att.find("./Properties/CoordinateFrame[@name='CFrame']")
            out[n] = [float(cf.findtext(ax)) for ax in ("X", "Y", "Z")]
        return out

    atts_por_parte = {nome: _att_map(p) for nome, p in partes.items()}
    assert "HatAttachment" in atts_por_parte["Head"]
    assert "BodyBackAttachment" in atts_por_parte["UpperTorso"]
    assert atts_por_parte["UpperTorso"]["BodyBackAttachment"][2] > 0.0
    assert "RightGripAttachment" in atts_por_parte["RightHand"]
    assert atts_por_parte["RightHand"]["RightGripAttachment"][1] < 0.0

    place = rbx.ler_place(saida)
    for motor in place["motores"]:
        att_nome = f"{motor['nome']}RigAttachment"
        assert att_nome in atts_por_parte[motor["part0"]], (motor["part0"], att_nome)
        assert att_nome in atts_por_parte[motor["part1"]], (motor["part1"], att_nome)
        assert atts_por_parte[motor["part0"]][att_nome] == pytest.approx(motor["c0"], abs=1e-5)
        assert atts_por_parte[motor["part1"]][att_nome] == pytest.approx(motor["c1"], abs=1e-5)


def test_export_animacao_rbxmx_walk_run_jump_identico_ao_clip(tmp_path):
    """Multi-clipe .rbxmx usa a mesma definicao de `animacao.clipes()` para walk/run/jump."""
    from forge3d import animacao, profiles

    roblox = profiles.carregar("roblox-r15")
    juntas = set(rbx.JOINT_R15.values())

    for clipe_nome, loop_esperado in (("walk", True), ("run", True), ("jump", False)):
        saida = tmp_path / f"{clipe_nome}.rbxmx"
        rel = rbx.exportar_animacao(
            "examples/lote_09_r15.yaml",
            "personagem.r15.guard.01",
            clipe=clipe_nome,
            saida=saida,
        )
        assert rel["ok"] is True
        assert rel["clipe"] == clipe_nome
        assert rel["keyframes"] == 9
        assert rel["duracao_s"] >= 1.6

        lido = rbx.ler_place(saida)
        assert len(lido["clipes"]) == 1
        seq = lido["clipes"][0]
        assert seq["nome"] == clipe_nome
        assert seq["loop"] is loop_esperado
        assert seq["priority"] == 1000

        esperado = animacao.clipes(roblox, "r15@1", [clipe_nome])[0]
        for chave, ch_exp in zip(seq["chaves"], esperado["chaves"]):
            assert chave["tempo"] == pytest.approx(ch_exp["segundos"], abs=1e-4)
            assert {p["osso"] for p in chave["poses"]} == juntas
            dadas = {rbx.JOINT_R15.get(p["osso"], p["osso"]): p for p in ch_exp["poses"]}
            for pose in chave["poses"]:
                fonte = dadas.get(pose["osso"], {"graus": 0.0, "eixo": "X"})
                matriz = rbx._matriz_rotacao(fonte["graus"], fonte["eixo"])
                assert pose["cframe"][3:] == pytest.approx(matriz, abs=1e-5)


def test_export_animacoes_multi_clipes_rbxmx_e_rbxlx(tmp_path):
    """Permite exportar pacote multi-clipe .rbxmx e place .rbxlx com os 4 clipes."""
    lote = tmp_path / "lote_multi.yaml"
    lote.write_text(
        "\n".join(
            [
                "schema: forge3d/spec@3",
                "projeto: demo",
                "perfil: roblox-r15",
                f"destino_exportacao: {tmp_path / 'out'}",
                "lote:",
                "  - id: personagem.r15.multi.01",
                "    tipo: personagem_humanoide",
                "    rota: blocky",
                "    prompt: guarda multi clipe",
                "    altura_metros: 1.85",
                "    auto_rig: true",
                "    esqueleto: r15@1",
                "    animacoes_base: [idle, walk, run, jump]",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    rbxmx = tmp_path / "multi.rbxmx"
    rel_anim = rbx.exportar_animacoes(lote, "personagem.r15.multi.01", saida=rbxmx)
    assert rel_anim["clipes"] == ["idle", "walk", "run", "jump"]
    lido_anim = rbx.ler_place(rbxmx)
    assert [c["nome"] for c in lido_anim["clipes"]] == ["idle", "walk", "run", "jump"]

    rbxlx = tmp_path / "multi.rbxlx"
    rel_place = rbx.exportar_r15(lote, "personagem.r15.multi.01", saida=rbxlx)
    assert rel_place["animacoes"] == ["idle", "walk", "run", "jump"]
    assert rel_place["textura"] is False
    lido_place = rbx.ler_place(rbxlx)
    assert [c["nome"] for c in lido_place["clipes"]] == ["idle", "walk", "run", "jump"]


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
    for parte in modelo.findall("Item[@class='Part']"):
        nome = parte.findtext("Properties/string[@name='Name']")
        sas = parte.findall("Item[@class='SurfaceAppearance']")
        if nome == "HumanoidRootPart":
            assert len(sas) == 0
        else:
            assert len(sas) == 1
    place = rbx.ler_place(rbxlx_pbr)
    assert len(place["surface_appearances"]) == 15


def test_cli_export_anim_clipe_unico_lista_e_todos(tmp_path, capsys):
    """CLI export-anim mantem --clipe unico, aceita lista separada por virgula e --todos."""
    # 1) Backwards-compatible default single clip (--clipe idle)
    unico = tmp_path / "unico.rbxmx"
    rc = despachar(
        [
            "export-anim",
            "examples/lote_09_r15.yaml",
            "--item",
            "personagem.r15.guard.01",
            "--saida",
            str(unico),
            "--json",
        ]
    )
    assert rc == 0
    rel_unico = json.loads(capsys.readouterr().out)
    assert rel_unico["clipe"] == "idle"
    assert rel_unico["keyframes"] == 5
    assert rel_unico["bytes"] == unico.stat().st_size

    # 2) Comma-separated list: --clipe idle,walk (human output + JSON)
    par_rbxmx = tmp_path / "par.rbxmx"
    rc = despachar(
        [
            "export-anim",
            "examples/lote_09_r15.yaml",
            "--item",
            "personagem.r15.guard.01",
            "--clipe",
            "idle,walk",
            "--saida",
            str(par_rbxmx),
        ]
    )
    assert rc == 0
    out_txt = capsys.readouterr().out
    assert "clipes idle,walk" in out_txt
    assert "keyframes" in out_txt
    assert "B" in out_txt

    par_json = tmp_path / "par_json.rbxmx"
    rc = despachar(
        [
            "export-anim",
            "examples/lote_09_r15.yaml",
            "--item",
            "personagem.r15.guard.01",
            "--clipe",
            "idle,walk",
            "--saida",
            str(par_json),
            "--json",
        ]
    )
    assert rc == 0
    rel_par = json.loads(capsys.readouterr().out)
    assert rel_par["clipes"] == ["idle", "walk"]
    assert rel_par["keyframes"] == {"idle": 5, "walk": 9}
    assert [c["nome"] for c in rbx.ler_place(par_json)["clipes"]] == ["idle", "walk"]

    # 3) --todos exports all ANIMACOES_SUPORTADAS clips into one .rbxmx
    todos_rbxmx = tmp_path / "todos.rbxmx"
    rc = despachar(
        [
            "export-anim",
            "examples/lote_09_r15.yaml",
            "--item",
            "personagem.r15.guard.01",
            "--todos",
            "--saida",
            str(todos_rbxmx),
            "--json",
        ]
    )
    assert rc == 0
    rel_todos = json.loads(capsys.readouterr().out)
    assert rel_todos["clipes"] == ["idle", "walk", "run", "jump"]
    assert rel_todos["keyframes"] == {"idle": 5, "walk": 9, "run": 9, "jump": 9}
    assert rel_todos["bytes"] == todos_rbxmx.stat().st_size
    assert [c["nome"] for c in rbx.ler_place(todos_rbxmx)["clipes"]] == [
        "idle",
        "walk",
        "run",
        "jump",
    ]

    # 4) Unknown clip in list fails cleanly with FORGE-E-SPEC
    rc = despachar(
        [
            "export-anim",
            "examples/lote_09_r15.yaml",
            "--item",
            "personagem.r15.guard.01",
            "--clipe",
            "idle,invalido",
            "--json",
        ]
    )
    assert rc == 2
    err = json.loads(capsys.readouterr().out)
    assert err["erro"]["codigo"] == "FORGE-E-SPEC"


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

    # 1) Manifest path without --item and without --saida (writes next to manifest)
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

    # 2) Directory + --item + explicit --saida + --json
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

    # 3) Direct manifest call in Python without writing file
    rel_mem = rbx.exportar_surface_appearance(manifesto)
    assert rel_mem["saida"] is None
    assert rel_mem["mapas"] == rel["mapas"]

    # 4) Mismatched --item against manifest fails cleanly
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

    # Human-readable output indicates SurfaceAppearance
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


