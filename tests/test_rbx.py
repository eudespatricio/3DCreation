"""Testes do export nativo R15 (.rbxlx): estrutura, XML e contagens."""

from __future__ import annotations

from xml.etree import ElementTree

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
