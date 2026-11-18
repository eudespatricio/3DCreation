"""Testes D-03: esqueleto REAL medido vira fonte unica de verdade e divergencia falha o run."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

from forge3d import pipeline, publish

RAIZ = Path(__file__).resolve().parents[1]


def test_esqueleto_divergente():
    assert pipeline._esqueleto_divergente({}) is None
    assert pipeline._esqueleto_divergente({"esqueleto_pedido": "a", "esqueleto": "a"}) is None
    assert pipeline._esqueleto_divergente({"esqueleto_pedido": "a"}) is None
    assert pipeline._esqueleto_divergente({"esqueleto": "b"}) is None
    assert pipeline._esqueleto_divergente(
        {"esqueleto_pedido": "godot-humanoid-aa@1", "esqueleto": "quadruped@1"}
    ) == ("godot-humanoid-aa@1", "quadruped@1")


def test_manifesto_rig_usa_esqueleto_medido_nao_o_pedido():
    # D-03: rig.esqueleto = esqueleto REAL medido (medidas), nao o que a spec pediu.
    resultado = {
        "arquivos": [
            {
                "caminho": "a.glb",
                "papel": "mesh",
                "nivel": 0,
                "triangulos": 1,
                "sha256": "sha256:" + "0" * 64,
                "bytes": 10,
            }
        ]
    }
    relatorio = {
        "aprovado": True,
        "gates": [{"id": "G1", "status": "ok"}],
        "medidas": {
            "triangulos": 1,
            "vertices": 1,
            "bbox_m": [0.1, 0.1, 0.1],
            "materiais": 1,
            "ossos": 23,
            "partes_colisao": 0,
            "esqueleto": "quadruped@1",  # real medido
        },
    }
    manifesto = publish.montar_manifesto(
        item={
            "id": "a.b",
            "rota": "mesh",
            "seed": 7,
            "auto_rig": True,
            "esqueleto": "godot-humanoid-aa@1",  # pedido (divergente)
            "tipo": "criatura",
        },
        spec_doc={"projeto": "demo", "perfil": "godot4-aa", "_arquivo": "lote.yaml"},
        spec_hash="sha256:" + "0" * 64,
        perfil_nome="godot4-aa",
        provider={"nome": "mesh", "versao": "x", "determinism": "D2"},
        resultado=resultado,
        relatorio_qc=relatorio,
        licenca={"modelo": "TripoSR", "uso_comercial": True, "notice": "TripoSR (MIT)."},
        run_id="run-teste",
    )
    assert manifesto["rig"]["esqueleto"] == "quadruped@1"


def _importar_postprocess():
    spec_mod = importlib.util.spec_from_file_location(
        "postprocess_d03", RAIZ / "blender" / "postprocess.py"
    )
    assert spec_mod and spec_mod.loader

    fake_bpy = types.ModuleType("bpy")
    fake_bmesh = types.ModuleType("bmesh")
    fake_mu = types.ModuleType("mathutils")
    fake_mu.Matrix = object
    fake_mu.Vector = object

    nomes_irmaos = ("autorig", "bake_pbr", "extrude_2d", "organic_sculpt")
    backup = {
        k: sys.modules.get(k)
        for k in ("bpy", "bmesh", "mathutils", *nomes_irmaos)
    }
    sys.modules["bpy"] = fake_bpy
    sys.modules["bmesh"] = fake_bmesh
    sys.modules["mathutils"] = fake_mu
    for nome in nomes_irmaos:
        sys.modules[nome] = types.ModuleType(nome)
    try:
        mod = importlib.util.module_from_spec(spec_mod)
        spec_mod.loader.exec_module(mod)
        return mod
    finally:
        for k, v in backup.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


def test_detectar_esqueleto_pelos_ossos():
    pp = _importar_postprocess()

    class _Bone:
        def __init__(self, name):
            self.name = name

    class _Rig:
        def __init__(self, nomes):
            self.data = type("_Data", (), {"bones": [_Bone(n) for n in nomes]})()

    def det(nomes):
        return pp._detectar_esqueleto_pelos_ossos(_Rig(nomes))

    assert det(["Root", "Hips", "Neck", "Hand.L", "Hand.R"]) == "godot-humanoid@1"
    assert det(["Root", "Thumb1.L", "Eye.L", "Cape", "Hand.L"]) == "godot-humanoid-aa@1"
    assert det(["Root", "UpperTorso", "LeftUpperArm", "RightHand"]) == "r15@1"
    assert det(["Root", "FrontUpperLeg.L", "FrontFoot.L", "MountSeat", "Tail1"]) == "quadruped@1"
    assert det(["Root", "WingShoulder.L", "MountSeat"]) == "winged_mount@1"
    assert det(["Root", "desconhecido"]) is None
    assert pp._detectar_esqueleto_pelos_ossos(None) is None
