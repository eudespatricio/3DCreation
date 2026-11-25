"""Testes do export nativo R15 (.rbxlx) e animacoes KeyframeSequence: estrutura, XML e contagens."""

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
    """D69/F05: o mesmo clipe do glb vira KeyframeSequence aninhada por Part1.Name."""
    from forge3d import animacao, profiles

    esperado = animacao.clipes(profiles.carregar("roblox-r15"), "r15@1", ["idle"])[0]
    saida = tmp_path / "r15.rbxlx"
    rel = rbx.exportar_r15("examples/lote_09_r15.yaml", "personagem.r15.guard.01", saida=saida)
    assert rel["animacoes"] == ["idle"]
    assert rel["keyframes"] == {"idle": len(esperado["chaves"])}

    place = rbx.ler_place(saida)
    assert len(place["clipes"]) == 1
    clipe = place["clipes"][0]
    assert clipe["nome"] == "idle" and clipe["loop"] is True
    assert clipe["priority"] == 0
    assert clipe["chaves"][0]["tempo"] == 0.0
    assert clipe["chaves"][-1]["tempo"] == pytest.approx(2.0, abs=1e-4)

    partes_r15 = set(rbx.JOINT_R15.keys()) | {"HumanoidRootPart"}
    identidade = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
    for chave, ch_exp in zip(clipe["chaves"], esperado["chaves"]):
        assert chave["tempo"] == pytest.approx(ch_exp["segundos"], abs=1e-4)
        assert {p["osso"] for p in chave["poses"]} == partes_r15
        dadas_m: dict[str, list[float]] = {}
        for p in ch_exp["poses"]:
            parte = rbx.JOINT_R15_REV.get(p["osso"], p["osso"])
            m_p = rbx._matriz_rotacao(p["graus"], p["eixo"])
            dadas_m[parte] = m_p if parte not in dadas_m else rbx._mul_mat3(dadas_m[parte], m_p)
        for pose in chave["poses"]:
            matriz = dadas_m.get(pose["osso"], identidade)
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
    """Pacote 4 + Onda 3: RigAttachments R15 + Hat/BodyBack/RightGrip, HumanoidRootPart transparente."""
    from forge3d import profiles

    assert profiles.carregar("roblox-r15")["validacao"]["materiais_max"] == 1

    saida = tmp_path / "r15.rbxlx"
    rel = rbx.exportar_r15("examples/lote_09_r15.yaml", "personagem.r15.guard.01", saida=saida)
    assert rel["attachments"] == 39

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
            assert anchored == "false"
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
    assert "HairAttachment" in atts_por_parte["Head"]
    assert atts_por_parte["Head"]["HairAttachment"][1] > 0.0
    assert "BodyBackAttachment" in atts_por_parte["UpperTorso"]
    assert atts_por_parte["UpperTorso"]["BodyBackAttachment"][2] > 0.0
    assert "BodyFrontAttachment" in atts_por_parte["UpperTorso"]
    assert atts_por_parte["UpperTorso"]["BodyFrontAttachment"][2] < 0.0
    assert "LeftCollarAttachment" in atts_por_parte["UpperTorso"]
    assert atts_por_parte["UpperTorso"]["LeftCollarAttachment"][0] < 0.0
    assert atts_por_parte["UpperTorso"]["LeftCollarAttachment"][1] > 0.0
    assert "RightCollarAttachment" in atts_por_parte["UpperTorso"]
    assert atts_por_parte["UpperTorso"]["RightCollarAttachment"][0] > 0.0
    assert atts_por_parte["UpperTorso"]["RightCollarAttachment"][1] > 0.0
    assert "WaistCenterAttachment" in atts_por_parte["LowerTorso"]
    assert atts_por_parte["LowerTorso"]["WaistCenterAttachment"] == pytest.approx([0.0, 0.0, 0.0])
    assert "RightGripAttachment" in atts_por_parte["RightHand"]
    assert atts_por_parte["RightHand"]["RightGripAttachment"][1] < 0.0
    assert "LeftGripAttachment" in atts_por_parte["LeftHand"]
    assert atts_por_parte["LeftHand"]["LeftGripAttachment"][1] < 0.0

    place = rbx.ler_place(saida)
    for motor in place["motores"]:
        att_nome = f"{motor['nome']}RigAttachment"
        assert att_nome in atts_por_parte[motor["part0"]], (motor["part0"], att_nome)
        assert att_nome in atts_por_parte[motor["part1"]], (motor["part1"], att_nome)
        assert atts_por_parte[motor["part0"]][att_nome] == pytest.approx(motor["c0"], abs=1e-5)
        assert atts_por_parte[motor["part1"]][att_nome] == pytest.approx(motor["c1"], abs=1e-5)


def test_export_animacao_rbxmx_walk_run_jump_identico_ao_clip(tmp_path):
    """Multi-clipe .rbxmx usa a mesma definicao de `animacao.clipes()` com poses R15 aninhadas."""
    from forge3d import animacao, profiles

    roblox = profiles.carregar("roblox-r15")
    partes_r15 = set(rbx.JOINT_R15.keys()) | {"HumanoidRootPart"}

    for clipe_nome, loop_esperado, prio_esperada in (("walk", True, 1), ("run", True, 1), ("jump", False, 2)):
        saida = tmp_path / f"{clipe_nome}.rbxmx"
        rel = rbx.exportar_animacao(
            "examples/lote_09_r15.yaml",
            "personagem.r15.guard.01",
            clipe=clipe_nome,
            saida=saida,
        )
        esperado = animacao.clipes(roblox, "r15@1", [clipe_nome])[0]
        assert rel["ok"] is True
        assert rel["clipe"] == clipe_nome
        assert rel["keyframes"] == len(esperado["chaves"])
        assert rel["keyframes"] >= 16
        assert rel["duracao_s"] >= 1.6

        lido = rbx.ler_place(saida)
        assert len(lido["clipes"]) == 1
        seq = lido["clipes"][0]
        assert seq["nome"] == clipe_nome
        assert seq["loop"] is loop_esperado
        assert seq["priority"] == prio_esperada

        for chave, ch_exp in zip(seq["chaves"], esperado["chaves"]):
            assert chave["tempo"] == pytest.approx(ch_exp["segundos"], abs=1e-4)
            assert {p["osso"] for p in chave["poses"]} == partes_r15
            dadas_m: dict[str, list[float]] = {}
            for p in ch_exp["poses"]:
                parte = rbx.JOINT_R15_REV.get(p["osso"], p["osso"])
                graus = float(p["graus"])
                if parte in ("LeftUpperLeg", "RightUpperLeg") and str(p["eixo"]).upper() == "Z":
                    graus = -graus
                m_p = rbx._matriz_rotacao(graus, p["eixo"])
                dadas_m[parte] = m_p if parte not in dadas_m else rbx._mul_mat3(dadas_m[parte], m_p)
            identidade = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
            for pose in chave["poses"]:
                matriz = dadas_m.get(pose["osso"], identidade)
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


def test_cli_export_anim_clipe_unico_lista_e_todos(tmp_path, capsys):
    """CLI export-anim mantem --clipe unico, aceita lista separada por virgula e --todos."""
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
    from forge3d import animacao, profiles

    roblox = profiles.carregar("roblox-r15")
    kf_por_clipe = {
        c["nome"]: len(c["chaves"])
        for c in animacao.clipes(roblox, "r15@1", list(profiles.ANIMACOES_SUPORTADAS))
    }

    assert rc == 0
    rel_unico = json.loads(capsys.readouterr().out)
    assert rel_unico["clipe"] == "idle"
    assert rel_unico["keyframes"] == kf_por_clipe["idle"]
    assert rel_unico["bytes"] == unico.stat().st_size

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
    assert rel_par["keyframes"] == {"idle": kf_por_clipe["idle"], "walk": kf_por_clipe["walk"]}
    assert [c["nome"] for c in rbx.ler_place(par_json)["clipes"]] == ["idle", "walk"]

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
    todos_esperados = [
        "idle", "walk", "run", "jump", "attack", "slash_combo", "cast",
        "block", "hit", "death", "ride_idle", "ride_fly", "gallop",
        "wing_flap", "glide", "bite", "roar",
    ]
    assert list(profiles.ANIMACOES_SUPORTADAS) == todos_esperados
    assert rel_todos["clipes"] == todos_esperados
    assert rel_todos["keyframes"] == kf_por_clipe
    assert rel_todos["bytes"] == todos_rbxmx.stat().st_size
    assert [c["nome"] for c in rbx.ler_place(todos_rbxmx)["clipes"]] == todos_esperados

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


def test_sequencia_xml_normaliza_junta_e_converte_deslocamento_studs():
    """F05: aceita entrada por junta (ex.: Root) e converte deslocamento_m para studs."""
    clipe = {
        "nome": "jump",
        "loop": False,
        "chaves": [
            {
                "segundos": 0.1,
                "poses": [
                    {"osso": "Root", "graus": 0.0, "eixo": "X", "deslocamento_m": [0.0, 0.0, 0.56]}
                ],
            }
        ],
    }
    linhas, _ = rbx._sequencia_xml(clipe, 0, mps=0.28)
    raiz = ElementTree.fromstring("\n".join(linhas))
    hrp = raiz.find("Item[@class='Keyframe']/Item[@class='Pose']")
    assert hrp is not None and hrp.findtext("Properties/string[@name='Name']") == "HumanoidRootPart"
    lt = hrp.find("Item[@class='Pose']")
    assert lt is not None and lt.findtext("Properties/string[@name='Name']") == "LowerTorso"
    assert float(lt.findtext("Properties/CoordinateFrame[@name='CFrame']/Y") or 0.0) == pytest.approx(2.0, abs=1e-4)


def test_exportar_r15_segmentada_rejeita_partes_incompletas(tmp_path):
    """F08: modo_rig=motor6d exige todas as 15 partes R15 no manifesto segmentado."""
    partes_nomes = list(rbx.JOINT_R15.keys())
    lote = tmp_path / "lote_parcial.yaml"
    lote.write_text(
        "\n".join(
            [
                "schema: forge3d/spec@6",
                "projeto: demo",
                "perfil: roblox-aa-80",
                f"destino_exportacao: {tmp_path / 'dest'}",
                "lote:",
                "  - id: boss.parcial.01",
                "    tipo: criatura",
                "    rota: mesh",
                "    prompt: golem",
                "    altura_metros: 2.0",
                "    seed: 7",
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
    manifesto_parcial = {
        "schema": "forge3d/manifest@6",
        "asset_id": "boss.parcial.01",
        "partes": [
            {"nome": "LowerTorso", "junta": "Root", "ancora": [0.0, 2.0, 0.0], "bbox": [1.0, 1.0, 1.0], "arquivo": "LowerTorso.glb"},
            {"nome": "UpperTorso", "junta": "Waist", "ancora": [0.0, 3.0, 0.0], "bbox": [1.0, 1.0, 1.0], "arquivo": "UpperTorso.glb"},
        ],
        "rig": {
            "esqueleto": "r15@1",
            "ossos": 16,
            "modo": "motor6d",
            "ancoras": {"LowerTorso": [0.0, 2.0, 0.0], "UpperTorso": [0.0, 3.0, 0.0]},
        },
        "files": [],
    }
    with pytest.raises(ForgeError) as exc:
        rbx.exportar_r15(lote, "boss.parcial.01", manifesto=manifesto_parcial, modo_rig="motor6d")
    assert exc.value.codigo == "FORGE-E-SPEC"
    assert "Head" in str(exc.value)
