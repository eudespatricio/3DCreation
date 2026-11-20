"""B25 (D123): partes articuladas no contrato — R15/Motor6D exige a lista completa do esqueleto."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from forge3d import profiles, spec
from forge3d.errors import ForgeError

RAIZ = Path(__file__).resolve().parents[1]

R15_PARTES = [
    "Head",
    "UpperTorso",
    "LowerTorso",
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
]


def _doc(item_extra: dict | None = None) -> dict:
    item: dict = {
        "id": "boss.iron_ram.r15.01",
        "tipo": "criatura",
        "rota": "mesh",
        "prompt": "colosso de cerco com cranio de aríete",
        "altura_metros": 3.3,
        "seed": 42,
    }
    if item_extra:
        item.update(item_extra)
    return {
        "schema": "forge3d/spec@6",
        "projeto": "demo",
        "perfil": "roblox-aa-80",
        "destino_exportacao": "~/.local/state/forge3d/saida/f0",
        "lote": [item],
    }


def _partes(nomes: list[str]) -> list[dict]:
    return [{"nome": n} for n in nomes]


def test_spec_aceita_partes_r15_com_motor6d():
    doc = _doc(
        {
            "auto_rig": True,
            "esqueleto": "r15@1",
            "partes": _partes(R15_PARTES),
            "rig": {"modo": "motor6d", "esqueleto": "r15@1"},
            "animacoes": [{"nome": "idle", "formato": "keyframe", "alvo": "motor6d", "loop": True}],
        }
    )
    preparado, perfil, _avisos = spec.preparar(doc)
    item = preparado["lote"][0]
    assert [p["nome"] for p in item["partes"]] == R15_PARTES
    assert item["rig"]["modo"] == "motor6d"
    assert perfil["perfil"] == "roblox-aa-80"


def test_b25_recusa_nome_fora_do_esqueleto():
    nomes = ["torso"] + R15_PARTES[1:]
    doc = _doc(
        {
            "auto_rig": True,
            "esqueleto": "r15@1",
            "partes": _partes(nomes),
            "rig": {"modo": "motor6d", "esqueleto": "r15@1"},
        }
    )
    perfil = profiles.carregar("roblox-aa-80")
    with pytest.raises(ForgeError) as exc:
        spec._regras_negocio(doc, perfil)
    assert any(e.get("regra") == "B25" for e in exc.value.detalhes["erros"])


def test_b25_recusa_partes_duplicadas():
    nomes = R15_PARTES[:-1] + [R15_PARTES[0]]
    doc = _doc(
        {
            "auto_rig": True,
            "esqueleto": "r15@1",
            "partes": _partes(nomes),
            "rig": {"modo": "motor6d", "esqueleto": "r15@1"},
        }
    )
    perfil = profiles.carregar("roblox-aa-80")
    with pytest.raises(ForgeError) as exc:
        spec._regras_negocio(doc, perfil)
    assert any(e.get("regra") == "B25" for e in exc.value.detalhes["erros"])


def test_b25_exige_partes_quando_motor6d():
    doc = _doc({"auto_rig": True, "esqueleto": "r15@1", "rig": {"modo": "motor6d"}})
    perfil = profiles.carregar("roblox-aa-80")
    with pytest.raises(ForgeError) as exc:
        spec._regras_negocio(doc, perfil)
    assert any(e.get("regra") == "B25" for e in exc.value.detalhes["erros"])


def test_manifest_v6_aceita_partes_e_ancoras():
    schema = json.loads((RAIZ / "schemas" / "manifest.v6.schema.json").read_text(encoding="utf-8"))
    doc = json.loads((RAIZ / "examples" / "manifest.exemplo.v6.json").read_text(encoding="utf-8"))
    doc["rig"] = {"esqueleto": "r15@1", "ossos": 16, "modo": "motor6d"}
    doc["rig"]["ancoras"] = {"Root": [0.0, 0.0, 0.0], "LeftKnee": [-1.8, 2.4, 0.0]}
    doc["partes"] = [
        {"nome": "LowerTorso", "junta": "Root", "pivo": "base", "ancora": [0.0, 2.4, 0.0],
         "bbox": [4.6, 2.9, 5.0], "triangulos": 900, "arquivos": ["LowerTorso.glb"]},
        {"nome": "LeftLowerLeg", "junta": "LeftKnee", "pivo": "origem", "ancora": [-1.8, 2.4, 0.0]},
    ]
    jsonschema.Draft202012Validator(schema).validate(doc)


def test_f12_cache_key_diverges_on_partes_rig_animacoes_quantidade_cena():
    from forge3d import canonical

    base = {
        "id": "boss.iron_ram.r15.01",
        "tipo": "criatura",
        "rota": "mesh",
        "altura_metros": 3.3,
        "seed": 42,
    }
    # Backwards-compatibility: omitting the 4 fields must not inject defaults into resolver_item
    res_base = spec.resolver_item(base)
    for k in ("partes", "rig", "animacoes", "quantidade_cena"):
        assert k not in res_base

    h_base = canonical.chave_cache(res_base, "0.9.4", {"mesh": "0.1.0"}, {"perfil": "roblox-aa-80"})

    mutacoes = [
        {"partes": [{"nome": "Head"}]},
        {"rig": {"modo": "motor6d", "esqueleto": "r15@1"}},
        {"animacoes": [{"nome": "idle", "formato": "keyframe", "alvo": "motor6d", "loop": True}]},
        {"quantidade_cena": 4},
    ]
    for extra in mutacoes:
        mod = {**base, **extra}
        res_mod = spec.resolver_item(mod)
        for k, v in extra.items():
            assert res_mod[k] == v
        h_mod = canonical.chave_cache(res_mod, "0.9.4", {"mesh": "0.1.0"}, {"perfil": "roblox-aa-80"})
        assert h_mod != h_base
