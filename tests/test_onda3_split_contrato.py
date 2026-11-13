"""Testes do contrato Onda 3 (Etapa 1A): split em mesh, hero tri budget, manifest@3 anexo e R15 attachments."""

from __future__ import annotations

import json
from pathlib import Path
from xml.etree import ElementTree

import jsonschema
import pytest

from forge3d import canonical, profiles, publish, rbx, spec
from forge3d.canonical import sha256_arquivo
from forge3d.errors import ForgeError

RAIZ = Path(__file__).resolve().parents[1]


def _doc_spec(
    *,
    schema: str = "forge3d/spec@3",
    perfil: str = "godot4",
    item_extra: dict | None = None,
) -> dict:
    item: dict = {
        "id": "hero.split.01",
        "tipo": "personagem_humanoide",
        "rota": "mesh",
        "prompt": "guerreiro estilizado",
        "altura_metros": 1.85,
        "seed": 42,
    }
    if item_extra:
        item.update(item_extra)
    return {
        "schema": schema,
        "projeto": "demo",
        "perfil": perfil,
        "destino_exportacao": "~/.local/state/forge3d/saida/onda3",
        "lote": [item],
    }


# ---------------------------------------------------------------- B11/B12/B13/B14 + spec@2/spec@3


@pytest.mark.parametrize("schema", ["forge3d/spec@2", "forge3d/spec@3"])
@pytest.mark.parametrize("rota", ["blocky", "mesh"])
@pytest.mark.parametrize(
    ("parte", "tipo", "auto_rig"),
    [
        ("corpo", "personagem_humanoide", True),
        ("capa", "personagem_humanoide", False),
        ("capa", "prop_estatico", False),
        ("cabelo", "personagem_humanoide", False),
        ("cabelo", "prop_estatico", False),
        ("arma", "prop_equipavel", False),
    ],
)
def test_b11_b12_aceitam_parte_em_blocky_e_mesh(schema, rota, parte, tipo, auto_rig):
    doc = _doc_spec(
        schema=schema,
        item_extra={
            "rota": rota,
            "parte": parte,
            "tipo": tipo,
            "auto_rig": auto_rig,
            "altura_metros": 1.2 if parte != "corpo" else 1.85,
        },
    )
    preparado, _perfil, _avisos = spec.preparar(doc)
    assert preparado["lote"][0]["parte"] == parte
    assert preparado["lote"][0]["rota"] == rota
    assert preparado["lote"][0]["tipo"] == tipo


def test_lote_03_kit_existente_continua_valido():
    doc = spec.carregar_arquivo(RAIZ / "examples" / "lote_03_kit.yaml")
    preparado, _perfil, _avisos = spec.preparar(doc)
    assert [i["parte"] for i in preparado["lote"]] == ["corpo", "capa", "arma"]


@pytest.mark.parametrize("schema", ["forge3d/spec@2", "forge3d/spec@3"])
def test_b11_recusa_parte_em_import_e_modular(schema, tmp_path):
    origem = tmp_path / "dummy.glb"
    origem.write_bytes(b"glb")

    doc_import = _doc_spec(
        schema=schema,
        item_extra={"rota": "import", "parte": "arma", "tipo": "prop_equipavel", "origem": str(origem)},
    )
    with pytest.raises(ForgeError) as exc_imp:
        spec.preparar(doc_import)
    assert exc_imp.value.codigo == "FORGE-E-SPEC"

    doc_mod = _doc_spec(
        schema=schema,
        item_extra={
            "rota": "modular",
            "parte": "capa",
            "tipo": "prop_estatico",
            "modular": {"grade": [2, 2], "modulos": ["corredor"]},
        },
    )
    with pytest.raises(ForgeError) as exc_mod:
        spec.preparar(doc_mod)
    assert exc_mod.value.codigo == "FORGE-E-SPEC"


def test_b11_regra_negocio_direta_recusa_rota_invalida():
    doc = _doc_spec(item_extra={"rota": "import", "parte": "corpo", "origem": "/tmp/nao_existe.glb"})
    perfil = profiles.carregar("godot4")
    with pytest.raises(ForgeError) as exc:
        spec._regras_negocio(doc, perfil)
    assert any(e.get("regra") == "B11" for e in exc.value.detalhes["erros"])


@pytest.mark.parametrize(
    ("parte", "tipo_invalido"),
    [
        ("corpo", "prop_estatico"),
        ("capa", "prop_equipavel"),
        ("arma", "personagem_humanoide"),
        ("arma", "prop_estatico"),
    ],
)
def test_b12_recusa_tipos_incompativeis(parte, tipo_invalido):
    doc = _doc_spec(item_extra={"parte": parte, "tipo": tipo_invalido, "auto_rig": False})
    with pytest.raises(ForgeError) as exc:
        spec.preparar(doc)
    assert any(e.get("regra") == "B12" for e in exc.value.detalhes["erros"])


def test_b13_e_b14_preservados_com_mesh_e_capa():
    doc_b13 = _doc_spec(
        item_extra={"rota": "mesh", "parte": "capa", "tipo": "personagem_humanoide", "auto_rig": True}
    )
    with pytest.raises(ForgeError) as exc_b13:
        spec.preparar(doc_b13)
    assert any(e.get("regra") == "B13" for e in exc_b13.value.detalhes["erros"])

    doc_b14 = _doc_spec(
        item_extra={"rota": "mesh", "parte": "corpo", "auto_rig": False, "animacoes_base": ["idle"]}
    )
    with pytest.raises(ForgeError) as exc_b14:
        spec.preparar(doc_b14)
    assert any(e.get("regra") == "B14" for e in exc_b14.value.detalhes["erros"])


def test_spec_v1_continua_rejeitando_parte():
    doc = _doc_spec(schema="forge3d/spec@1", item_extra={"rota": "blocky", "parte": "corpo"})
    with pytest.raises(ForgeError) as exc:
        spec.preparar(doc)
    assert exc.value.codigo == "FORGE-E-SPEC"


# ---------------------------------------------------------------- campos aditivos spec@3 & hero budget


def test_spec_v3_aceita_campos_onda3_e_entra_na_chave_cache():
    for campo in ("qualidade", "pose_guard", "extrudir_2d"):
        assert campo in spec.CAMPOS_CANONICOS_ITEM

    doc = _doc_spec(
        schema="forge3d/spec@3",
        item_extra={"qualidade": "hero", "pose_guard": "repose", "extrudir_2d": False},
    )
    preparado, perfil, _avisos = spec.preparar(doc)
    item_hero = preparado["lote"][0]
    assert item_hero["qualidade"] == "hero"
    assert item_hero["pose_guard"] == "repose"
    assert item_hero["extrudir_2d"] is False

    doc_std = _doc_spec(
        schema="forge3d/spec@3",
        item_extra={"qualidade": "standard", "pose_guard": "off", "extrudir_2d": True},
    )
    item_std = spec.preparar(doc_std)[0]["lote"][0]

    k_hero = canonical.chave_cache(item_hero, "0.1.0", {"mesh": "0.1.0"}, perfil)
    k_std = canonical.chave_cache(item_std, "0.1.0", {"mesh": "0.1.0"}, perfil)
    assert k_hero != k_std


@pytest.mark.parametrize(
    "campo_invalido",
    [
        {"qualidade": "ultra"},
        {"pose_guard": "force"},
        {"extrudir_2d": "sim"},
    ],
)
def test_spec_v3_rejeita_valores_invalidos_campos_onda3(campo_invalido):
    doc = _doc_spec(schema="forge3d/spec@3", item_extra=campo_invalido)
    with pytest.raises(ForgeError) as exc:
        spec.preparar(doc)
    assert exc.value.codigo == "FORGE-E-SPEC"


def test_spec_v2_nao_aceita_campos_exclusivos_v3():
    for campo in ({"qualidade": "hero"}, {"pose_guard": "auto"}, {"extrudir_2d": True}):
        doc = _doc_spec(schema="forge3d/spec@2", item_extra=campo)
        with pytest.raises(ForgeError) as exc:
            spec.preparar(doc)
        assert exc.value.codigo == "FORGE-E-SPEC"


def test_limite_tri_hero_e_default_no_spec_preparar():
    godot = profiles.carregar("godot4")
    roblox = profiles.carregar("roblox-r15")

    assert profiles.limite_tri_hero(godot, "personagem_humanoide") == 12000
    assert profiles.limite_tri_hero(godot, "criatura") == 12000
    assert profiles.limite_tri_hero(godot, "prop_equipavel") == 800
    assert profiles.limite_tri_hero(godot, "prop_estatico") == 1500

    assert profiles.limite_tri_hero(roblox, "personagem_humanoide") == 10000
    assert profiles.limite_tri_hero(roblox, "criatura") == 10000
    assert profiles.limite_tri_hero(roblox, "prop_equipavel") == 800

    # Caso limite: orcamento base maior que 10000 em roblox-r15 ainda respeita G9 10000
    roblox_alto = {"perfil": "roblox-r15", "orcamento_triangulos": {"personagem_humanoide": 15000}}
    assert profiles.limite_tri_hero(roblox_alto, "personagem_humanoide") == 10000
    godot_alto = {"perfil": "godot4", "orcamento_triangulos": {"personagem_humanoide": 15000}}
    assert profiles.limite_tri_hero(godot_alto, "personagem_humanoide") == 15000

    # Default de spec.preparar com qualidade: hero vs standard vs explicito
    hero_godot, _, _ = spec.preparar(_doc_spec(perfil="godot4", item_extra={"qualidade": "hero"}))
    assert hero_godot["lote"][0]["limite_triangulos"] == 12000

    hero_r15, _, _ = spec.preparar(_doc_spec(perfil="roblox-r15", item_extra={"qualidade": "hero"}))
    assert hero_r15["lote"][0]["limite_triangulos"] == 10000

    hero_arma, _, _ = spec.preparar(
        _doc_spec(
            perfil="godot4",
            item_extra={"tipo": "prop_equipavel", "parte": "arma", "qualidade": "hero"},
        )
    )
    assert hero_arma["lote"][0]["limite_triangulos"] == 800

    hero_explicito, _, _ = spec.preparar(
        _doc_spec(perfil="godot4", item_extra={"qualidade": "hero", "limite_triangulos": 7500})
    )
    assert hero_explicito["lote"][0]["limite_triangulos"] == 7500

    std_godot, _, _ = spec.preparar(_doc_spec(perfil="godot4", item_extra={"qualidade": "standard"}))
    assert std_godot["lote"][0]["limite_triangulos"] == 6000


# ---------------------------------------------------------------- manifest@3 anexo & verify


def test_manifest_v3_schema_aceita_anexo_opcional_e_retrocompatibilidade():
    schema = json.loads((RAIZ / "schemas" / "manifest.v3.schema.json").read_text(encoding="utf-8"))
    val = jsonschema.Draft202012Validator(schema)

    base = json.loads((RAIZ / "examples" / "manifest.exemplo.v3.json").read_text(encoding="utf-8"))
    assert list(val.iter_errors(base)) == []

    com_null = {**base, "anexo": None}
    assert list(val.iter_errors(com_null)) == []

    com_anexo = {
        **base,
        "anexo": {"parte": "arma", "osso": "Hand.R", "attachment_roblox": "RightGripAttachment"},
    }
    assert list(val.iter_errors(com_anexo)) == []

    invalido_extra = {
        **base,
        "anexo": {
            "parte": "arma",
            "osso": "Hand.R",
            "attachment_roblox": "RightGripAttachment",
            "extra": 1,
        },
    }
    assert list(val.iter_errors(invalido_extra)) != []

    invalido_parte = {
        **base,
        "anexo": {"parte": "capacete", "osso": "Head", "attachment_roblox": "HatAttachment"},
    }
    assert list(val.iter_errors(invalido_parte)) != []


@pytest.mark.parametrize(
    ("parte", "esperado"),
    [
        ("capa", {"parte": "capa", "osso": "Chest", "attachment_roblox": "BodyBackAttachment", "skinned": False}),
        ("cabelo", {"parte": "cabelo", "osso": "Head", "attachment_roblox": "HatAttachment", "skinned": False}),
        ("arma", {"parte": "arma", "osso": "Hand.R", "attachment_roblox": "RightGripAttachment", "skinned": False}),
        ("corpo", {"parte": "corpo", "osso": "Root", "attachment_roblox": "HumanoidRootPart", "skinned": True}),
        ("elmo", {"parte": "elmo", "osso": "Head", "attachment_roblox": "HatAttachment", "skinned": False}),
        ("ombreiras", {"parte": "ombreiras", "osso": "Shoulder.L", "attachment_roblox": "LeftCollarAttachment", "skinned": True}),
        ("peitoral", {"parte": "peitoral", "osso": "Chest", "attachment_roblox": "BodyFrontAttachment", "skinned": True}),
        ("luvas", {"parte": "luvas", "osso": "Hand.R", "attachment_roblox": "RightGripAttachment", "skinned": True}),
        ("calcas", {"parte": "calcas", "osso": "Hips", "attachment_roblox": "WaistCenterAttachment", "skinned": True}),
        ("botas", {"parte": "botas", "osso": "Foot.R", "attachment_roblox": "RightFootAttachment", "skinned": True}),
        ("escudo", {"parte": "escudo", "osso": "LowerArm.L", "attachment_roblox": "LeftGripAttachment", "skinned": False}),
        (None, None),
    ],
)
def test_montar_manifesto_popula_anexo_e_passa_verificar(tmp_path, monkeypatch, parte, esperado):
    glb = tmp_path / "item.glb"
    glb.write_bytes(b"glTF-dummy")
    item: dict = {"id": "hero.kit.01", "rota": "mesh", "seed": 7, "colisao": "none"}
    if parte is not None:
        item["parte"] = parte

    resultado = {
        "arquivos": [
            {
                "caminho": "item.glb",
                "papel": "mesh",
                "nivel": 0,
                "triangulos": 420,
                "sha256": sha256_arquivo(glb),
                "bytes": glb.stat().st_size,
            }
        ],
        "determinism": "D2",
    }
    relatorio_qc = {
        "aprovado": True,
        "gates": [
            {"id": "G1", "status": "ok"},
            {
                "id": "G2",
                "status": "ok",
                "medido": {
                    "altura_m": 1.2,
                    "esperado_m": 1.2,
                    "delta_pct": 0.0,
                    "pivo_regra": "base",
                    "escala_saida": 1.0,
                },
            },
            {"id": "G9", "status": "ok", "medido": {"limite": 1500}},
        ],
        "medidas": {
            "triangulos": 420,
            "vertices": 240,
            "bbox_m": [0.4, 0.3, 1.2],
            "materiais": 1,
            "ossos": 0,
            "partes_colisao": 0,
        },
    }
    man = publish.montar_manifesto(
        item=item,
        spec_doc={"projeto": "demo", "perfil": "godot4", "_arquivo": "lote.yaml"},
        spec_hash="sha256:" + "0" * 64,
        perfil_nome="godot4",
        perfil=profiles.carregar("godot4"),
        provider={"nome": "mesh", "versao": "0.1.8", "determinism": "D2"},
        resultado=resultado,
        relatorio_qc=relatorio_qc,
        licenca={"modelo": "MIT", "uso_comercial": True, "notice": "teste"},
        run_id="run-onda3",
    )

    if esperado is None:
        assert "anexo" not in man
    else:
        assert man["anexo"] == esperado

    (tmp_path / "hero.kit.01.manifest.json").write_text(json.dumps(man), encoding="utf-8")

    # 1) Validacao de schema + hash + proveniencia sem blender/glb real
    rel_mh = publish.verificar(tmp_path, only="manifesto,hash")
    assert rel_mh["ok"] is True, rel_mh["erros"]

    # 2) Validacao completa com gates simulando leitura do glb
    from forge3d import qc

    monkeypatch.setattr(qc, "ler_glb_bin", lambda _p: ({"meshes": []}, b""))
    monkeypatch.setattr(
        qc,
        "topologia",
        lambda _g, _b: {
            "triangulos": 420,
            "vertices": 240,
            "bbox_m": [0.4, 0.3, 1.2],
            "materiais": 1,
            "ossos": 0,
        },
    )
    monkeypatch.setattr(
        qc,
        "verificar",
        lambda *_a, **_kw: {
            "aprovado": True,
            "gates": relatorio_qc["gates"],
            "medidas": relatorio_qc["medidas"],
        },
    )
    rel_full = publish.verificar(tmp_path)
    assert rel_full["ok"] is True, rel_full["erros"]


# ---------------------------------------------------------------- Roblox R15 attachments


def test_rbx_export_r15_inclui_bodyback_e_rightgrip_attachments(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE3D_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("FORGE3D_CONFIG", str(tmp_path / "cfg" / "config.yaml"))
    from forge3d import config

    config.adicionar(tmp_path)
    saida = tmp_path / "r15_onda3.rbxlx"
    rel = rbx.exportar_r15("examples/lote_09_r15.yaml", "personagem.r15.guard.01", saida=saida)
    assert rel["ok"] is True
    assert rel["attachments"] == 39

    raiz = ElementTree.fromstring(saida.read_text(encoding="utf-8"))
    modelo = next(e for e in raiz.iter("Item") if e.get("class") == "Model")
    partes = {
        p.findtext("./Properties/string[@name='Name']"): p
        for p in modelo.findall("Item[@class='Part']")
    }

    def _atts(parte_xml) -> dict[str, list[float]]:
        res = {}
        for att in parte_xml.findall("Item[@class='Attachment']"):
            nome = att.findtext("./Properties/string[@name='Name']") or ""
            cf = att.find("./Properties/CoordinateFrame[@name='CFrame']")
            assert cf is not None
            res[nome] = [float(cf.findtext(ax) or 0.0) for ax in ("X", "Y", "Z")]
        return res

    upper_torso = partes["UpperTorso"]
    upper_size_z = float(upper_torso.findtext("./Properties/Vector3[@name='size']/Z") or 0.0)
    upper_atts = _atts(upper_torso)
    assert "BodyBackAttachment" in upper_atts
    assert upper_atts["BodyBackAttachment"] == pytest.approx([0.0, 0.0, upper_size_z / 2.0], abs=1e-5)

    right_hand = partes["RightHand"]
    hand_size_y = float(right_hand.findtext("./Properties/Vector3[@name='size']/Y") or 0.0)
    hand_atts = _atts(right_hand)
    assert "RightGripAttachment" in hand_atts
    assert hand_atts["RightGripAttachment"] == pytest.approx([0.0, -hand_size_y / 2.0, 0.0], abs=1e-5)
