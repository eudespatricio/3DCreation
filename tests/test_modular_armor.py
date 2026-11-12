"""Testes da Rota Modular de Sets e Armaduras (6 pecas + escudo) - Forge3D 0.5.2."""

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

import jsonschema
import pytest

from forge3d import profiles, publish, spec
from forge3d.errors import ForgeError
from forge3d.providers import mesh


def _doc_spec(**kwargs) -> dict:
    lote = kwargs.pop("lote", None)
    if lote is None:
        item = {
            "id": "set.silvanor.peitoral.01",
            "tipo": "prop_equipavel",
            "rota": "mesh",
            "parte": "peitoral",
            "altura_metros": 1.72,
            "seed": 42,
            "prompt": "armadura peitoral de placas",
            "colisao": "none",
            "esqueleto": "godot-humanoid@1",
            **kwargs.pop("item_extra", {}),
        }
        lote = [item]
    return {
        "schema": "forge3d/spec@3",
        "projeto": "silvanor_rpg",
        "perfil": "godot4",
        "destino_exportacao": "~/.local/state/forge3d/saida/modular_armor",
        "requisicao": {
            "id": "req-set-01",
            "isolamento": "estrito",
        },
        "lote": lote,
        **kwargs,
    }


# ------------------------------------------------------------------ Schemas


def test_schemas_spec_v3_e_manifest_v3_aceitam_partes_de_armadura_e_escudo():
    val_spec = jsonschema.Draft202012Validator(
        json.loads(Path("schemas/spec.v3.schema.json").read_text(encoding="utf-8"))
    )
    val_man = jsonschema.Draft202012Validator(
        json.loads(Path("schemas/manifest.v3.schema.json").read_text(encoding="utf-8"))
    )
    base_man = json.loads(Path("examples/manifest.exemplo.v3.json").read_text(encoding="utf-8"))

    partes_validas = [
        "elmo", "ombreiras", "peitoral", "luvas", "calcas", "calças", "botas", "escudo",
        "corpo", "capa", "cabelo", "arma",
    ]

    for p in partes_validas:
        doc = _doc_spec(item_extra={"parte": p})
        erros_spec = list(val_spec.iter_errors(doc))
        assert not erros_spec, f"spec.v3 rejeitou parte '{p}': {erros_spec}"

        man_anexo = {
            **base_man,
            "anexo": {
                "parte": p,
                "osso": "Head",
                "attachment_roblox": "HatAttachment",
                "skinned": False,
            },
        }
        erros_man = list(val_man.iter_errors(man_anexo))
        assert not erros_man, f"manifest.v3 rejeitou anexo parte '{p}': {erros_man}"


def test_schema_recusa_parte_invalida():
    val_spec = jsonschema.Draft202012Validator(
        json.loads(Path("schemas/spec.v3.schema.json").read_text(encoding="utf-8"))
    )
    doc_invalido = _doc_spec(item_extra={"parte": "capacete_alien"})
    assert list(val_spec.iter_errors(doc_invalido)) != []


# ------------------------------------------------------------------ Regras B11, B12, B13


def test_b12_valida_tipos_por_parte():
    # Elmo, ombreiras, escudo aceitam prop_equipavel e prop_estatico
    for p in ("elmo", "ombreiras", "escudo"):
        doc_eq = _doc_spec(item_extra={"parte": p, "tipo": "prop_equipavel"})
        assert spec.preparar(doc_eq)[0]["lote"][0]["parte"] == p
        doc_est = _doc_spec(item_extra={"parte": p, "tipo": "prop_estatico"})
        assert spec.preparar(doc_est)[0]["lote"][0]["parte"] == p

    # Peitoral, calcas, botas, luvas aceitam prop_equipavel e personagem_humanoide
    for p in ("peitoral", "calcas", "botas", "luvas"):
        doc_eq = _doc_spec(item_extra={"parte": p, "tipo": "prop_equipavel"})
        assert spec.preparar(doc_eq)[0]["lote"][0]["parte"] == p
        doc_hum = _doc_spec(item_extra={"parte": p, "tipo": "personagem_humanoide"})
        assert spec.preparar(doc_hum)[0]["lote"][0]["parte"] == p


def test_b12_rejeita_tipos_invalidos_para_armadura():
    # Elmo nao pode ser personagem_humanoide nem criatura
    doc_bad = _doc_spec(item_extra={"parte": "elmo", "tipo": "personagem_humanoide"})
    with pytest.raises(ForgeError) as exc:
        spec.preparar(doc_bad)
    assert any(e.get("regra") == "B12" for e in exc.value.detalhes["erros"])


def test_b13_bloqueia_auto_rig_em_pecas_socket_estaticas():
    # Socket nao aceita auto_rig
    for p in ("elmo", "ombreiras", "escudo"):
        doc_bad = _doc_spec(item_extra={"parte": p, "tipo": "prop_equipavel", "auto_rig": True})
        with pytest.raises(ForgeError) as exc:
            spec.preparar(doc_bad)
        assert exc.value.codigo == "FORGE-E-SPEC"

    for p in ("capa", "cabelo"):
        doc_b13 = _doc_spec(item_extra={"parte": p, "tipo": "personagem_humanoide", "auto_rig": True})
        with pytest.raises(ForgeError) as exc_b13:
            spec.preparar(doc_b13)
        assert any(e.get("regra") == "B13" for e in exc_b13.value.detalhes["erros"])


def test_normalizacao_calcas_com_cedilha():
    doc = _doc_spec(item_extra={"parte": "calças"})
    res, _, _ = spec.preparar(doc)
    assert res["lote"][0]["parte"] == "calcas"


# ------------------------------------------------------------------ MakeHuman B18, B19, B21


def test_makehuman_clothes_uri_suportada_em_armaduras():
    doc = _doc_spec(
        item_extra={
            "parte": "peitoral",
            "tipo": "prop_equipavel",
            "origem": "makehuman://clothes/male_casualsuit01",
        }
    )
    res, _, _ = spec.preparar(doc)
    assert res["lote"][0]["origem"] == "makehuman://clothes/male_casualsuit01"


def test_makehuman_clothes_em_cabelo_falha_b21():
    doc = _doc_spec(
        item_extra={
            "parte": "cabelo",
            "tipo": "prop_estatico",
            "origem": "makehuman://clothes/fedora01",
        }
    )
    with pytest.raises(ForgeError) as exc:
        spec.preparar(doc)
    assert any(e.get("regra") == "B21" for e in exc.value.detalhes["erros"])


# ------------------------------------------------------------------ Manifestos v3 Anexos & Skinned


@pytest.mark.parametrize(
    ("parte", "osso_esperado", "attachment_esperado", "skinned_esperado"),
    [
        ("elmo", "Head", "HatAttachment", False),
        ("ombreiras", "Shoulder.L", "LeftCollarAttachment", False),
        ("peitoral", "Chest", "BodyFrontAttachment", True),
        ("luvas", "Hand.R", "RightGripAttachment", True),
        ("calcas", "Hips", "WaistCenterAttachment", True),
        ("botas", "Foot.R", "RightFootAttachment", True),
        ("escudo", "LowerArm.L", "LeftGripAttachment", False),
    ],
)
def test_montar_manifesto_armaduras_e_escudo(tmp_path, parte, osso_esperado, attachment_esperado, skinned_esperado):
    glb = tmp_path / "item.glb"
    glb.write_bytes(b"glTF-dummy")
    item = {
        "id": f"set.silvanor.{parte}.01",
        "rota": "mesh",
        "parte": parte,
        "seed": 7,
        "colisao": "none",
    }
    resultado = {
        "arquivos": [
            {
                "caminho": "item.glb",
                "papel": "mesh",
                "nivel": 0,
                "triangulos": 500,
                "sha256": hashlib.sha256(glb.read_bytes()).hexdigest(),
                "bytes": glb.stat().st_size,
            }
        ],
        "determinism": "D2",
    }
    relatorio_qc = {
        "aprovado": True,
        "gates": [{"id": "G1", "status": "ok"}],
        "medidas": {
            "triangulos": 500,
            "vertices": 250,
            "bbox_m": [0.5, 0.5, 0.5],
            "materiais": 1,
            "ossos": 23 if skinned_esperado else 0,
            "partes_colisao": 0,
        },
    }
    man = publish.montar_manifesto(
        item=item,
        spec_doc={"projeto": "rpg", "perfil": "godot4", "_arquivo": "lote.yaml"},
        spec_hash="sha256:" + "0" * 64,
        perfil_nome="godot4",
        perfil=profiles.carregar("godot4"),
        provider={"nome": "mesh", "versao": "0.1.8", "determinism": "D2"},
        resultado=resultado,
        relatorio_qc=relatorio_qc,
        licenca={"modelo": "MIT", "uso_comercial": True, "notice": "teste"},
        run_id="run-armor",
    )

    assert man["anexo"] == {
        "parte": parte,
        "osso": osso_alvo if (osso_alvo := item.get("osso")) else osso_esperado,
        "attachment_roblox": attachment_esperado,
        "skinned": skinned_esperado,
    }
    if skinned_esperado:
        assert man["rig"] == {"esqueleto": "godot-humanoid@1", "ossos": 23}
    else:
        assert man["rig"] is None


# ------------------------------------------------------------------ Macro Set Completo


def test_set_completo_6_pecas_mais_escudo_valida_em_lote():
    doc_set = {
        "schema": "forge3d/spec@3",
        "projeto": "silvanor_rpg",
        "perfil": "godot4",
        "destino_exportacao": "~/.local/state/forge3d/saida/modular_armor",
        "requisicao": {
            "id": "req-set-silvanor-01",
            "isolamento": "estrito",
        },
        "lote": [
            {
                "id": "set.silvanor.elmo.01",
                "tipo": "prop_equipavel",
                "rota": "mesh",
                "parte": "elmo",
                "altura_metros": 0.35,
                "prompt": "elmo de cavaleiro com visor",
                "seed": 101,
            },
            {
                "id": "set.silvanor.peitoral.01",
                "tipo": "prop_equipavel",
                "rota": "mesh",
                "parte": "peitoral",
                "altura_metros": 1.72,
                "esqueleto": "godot-humanoid@1",
                "prompt": "peitoral de aco com emblema",
                "seed": 102,
            },
            {
                "id": "set.silvanor.ombreiras.01",
                "tipo": "prop_equipavel",
                "rota": "mesh",
                "parte": "ombreiras",
                "altura_metros": 0.40,
                "prompt": "par de ombreiras pontiagudas",
                "seed": 103,
            },
            {
                "id": "set.silvanor.luvas.01",
                "tipo": "prop_equipavel",
                "rota": "mesh",
                "parte": "luvas",
                "altura_metros": 0.30,
                "esqueleto": "godot-humanoid@1",
                "prompt": "manoplas de metal reforçadas",
                "seed": 104,
            },
            {
                "id": "set.silvanor.calcas.01",
                "tipo": "prop_equipavel",
                "rota": "mesh",
                "parte": "calcas",
                "altura_metros": 1.00,
                "esqueleto": "godot-humanoid@1",
                "prompt": "perneiras de cota de malha",
                "seed": 105,
            },
            {
                "id": "set.silvanor.botas.01",
                "tipo": "prop_equipavel",
                "rota": "mesh",
                "parte": "botas",
                "altura_metros": 0.45,
                "esqueleto": "godot-humanoid@1",
                "prompt": "botas blindadas de ferro",
                "seed": 106,
            },
            {
                "id": "set.silvanor.escudo.01",
                "tipo": "prop_equipavel",
                "rota": "mesh",
                "parte": "escudo",
                "extrudir_2d": True,
                "altura_metros": 0.85,
                "pivot": "base",
                "colisao": "box",
                "prompt": "escudo pipa heraldico",
                "seed": 107,
            },
        ],
    }

    res, _, _ = spec.preparar(doc_set)
    assert len(res["lote"]) == 7
    partes = [item["parte"] for item in res["lote"]]
    assert partes == ["elmo", "peitoral", "ombreiras", "luvas", "calcas", "botas", "escudo"]


# ------------------------------------------------------------------ Execucao Blender modular_armor.py


def test_blender_modular_armor_gera_peitoral_skinned_e_elmo_socket(tmp_path):
    # 1. Testa Peitoral Skinned com DATA_TRANSFER
    dir_peitoral = tmp_path / "peitoral"
    dir_peitoral.mkdir()
    job_peitoral = {
        "saida": str(dir_peitoral),
        "parte": "peitoral",
        "origem": "male_casualsuit01",
        "esqueleto": "godot-humanoid@1",
        "limite_triangulos": 9000,
        "skinned": True,
    }
    jf_peitoral = dir_peitoral / "job.json"
    jf_peitoral.write_text(json.dumps(job_peitoral), encoding="utf-8")

    proc = subprocess.run(
        ["blender", "-b", "--python", "blender/modular_armor.py", "--", str(jf_peitoral)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, f"Blender peitoral falhou: {proc.stderr}"
    assert (dir_peitoral / "template_armor.glb").is_file()
    rel_p = json.loads((dir_peitoral / "relatorio.json").read_text(encoding="utf-8"))
    assert rel_p["ok"] is True
    assert rel_p["skinned"] is True
    assert rel_p["osso"] == "Chest"
    assert rel_p["esqueleto"] == "godot-humanoid@1"
    assert rel_p["triangulos"] <= 9000

    # 2. Testa Elmo Socket Rigido
    dir_elmo = tmp_path / "elmo"
    dir_elmo.mkdir()
    job_elmo = {
        "saida": str(dir_elmo),
        "parte": "elmo",
        "origem": "fedora01",
        "limite_triangulos": 5000,
        "skinned": False,
    }
    jf_elmo = dir_elmo / "job.json"
    jf_elmo.write_text(json.dumps(job_elmo), encoding="utf-8")

    proc_elmo = subprocess.run(
        ["blender", "-b", "--python", "blender/modular_armor.py", "--", str(jf_elmo)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc_elmo.returncode == 0, f"Blender elmo falhou: {proc_elmo.stderr}"
    assert (dir_elmo / "template_armor.glb").is_file()
    rel_e = json.loads((dir_elmo / "relatorio.json").read_text(encoding="utf-8"))
    assert rel_e["ok"] is True
    assert rel_e["skinned"] is False
    assert rel_e["osso"] == "Head"
