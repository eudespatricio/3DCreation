"""Testes do export nativo R15 (.rbxlx): estrutura, XML e contagens."""

from __future__ import annotations

from xml.etree import ElementTree

import pytest

from forge3d import rbx

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
