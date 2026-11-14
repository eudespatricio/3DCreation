"""Testes da Rota Modular de Sets e Armaduras (6 pecas + escudo) - Forge3D 0.5.2."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

import jsonschema
import pytest

from forge3d import post, profiles, publish, spec
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
        ("ombreiras", "Shoulder.L", "LeftCollarAttachment", True),
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


@pytest.mark.blender
def test_blender_modular_armor_gera_peitoral_skinned_e_elmo_socket(tmp_path):
    if not _tem_mpfb2_clothes():
        pytest.skip("MPFB2 clothes nao instalados no ambiente")
    try:
        blender_bin = post.binario()
    except ForgeError:
        pytest.skip("Blender 4.2 nao disponivel neste ambiente")

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
        [blender_bin, "-b", "--python", "blender/modular_armor.py", "--", str(jf_peitoral)],
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
        [blender_bin, "-b", "--python", "blender/modular_armor.py", "--", str(jf_elmo)],
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


def _tem_mpfb2_clothes() -> bool:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    cfg_root = Path(xdg) if xdg else (Path.home() / ".config")
    base = cfg_root / "blender" / "4.2" / "extensions"
    return base.is_dir() and any(base.glob("**/mpfb/data/clothes/shoes01/shoes01.mhclo"))


def test_custo_preflight_e_licenca_rotas_cpu():
    """Modular armor (incl. escudo) e extrude_2d nao exigem GPU VRAM; template sem origem exige."""
    prov = mesh.MeshProvider()
    perfil = profiles.carregar("godot4")

    item_escudo = {
        "id": "set.teste.escudo.01",
        "tipo": "prop_equipavel",
        "rota": "mesh",
        "parte": "escudo",
        "altura_metros": 0.85,
        "prompt": "escudo templario prateado",
        "seed": 11,
    }
    assert mesh._usar_modular_armor(item_escudo) is True
    assert mesh._usar_modular_armor({**item_escudo, "extrudir_2d": True}) is False

    c_armor = prov.custo(item_escudo, perfil)
    assert c_armor["vram_mb"] == 0
    ok_a, _ = prov.preflight_item(item_escudo)
    assert ok_a is True

    item_extrude = {
        "id": "prop.espada.01",
        "tipo": "prop_equipavel",
        "rota": "mesh",
        "parte": "arma",
        "extrudir_2d": True,
        "altura_metros": 1.1,
        "prompt": "espada longa de aco",
        "seed": 12,
    }
    c_ext = prov.custo(item_extrude, perfil)
    assert c_ext["vram_mb"] == 0

    item_hum = {
        "id": "char.heroi.01",
        "tipo": "personagem_humanoide",
        "rota": "mesh",
        "altura_metros": 1.75,
        "prompt": "guerreiro medieval em A-pose",
        "seed": 13,
    }
    c_hum = prov.custo(item_hum, perfil)
    assert 3500 <= c_hum["vram_mb"] <= 4000


def test_r15_mapeamento_e_mhclo_aninhado_e_estilo(tmp_path):
    """r15@1 usa ossos R15, _encontrar_mhclo resolve URIs aninhadas e estilo parseia prompt/paleta/cor."""
    import importlib.util

    spec_mod = importlib.util.spec_from_file_location(
        "modular_armor_mod",
        Path(__file__).resolve().parent.parent / "blender" / "modular_armor.py",
    )
    assert spec_mod and spec_mod.loader
    import types
    import sys

    fake_bpy = types.ModuleType("bpy")
    fake_bmesh = types.ModuleType("bmesh")
    fake_mu = types.ModuleType("mathutils")
    fake_mu.Matrix = object
    fake_mu.Quaternion = object
    fake_mu.Vector = object
    sys_backup = {k: sys.modules.get(k) for k in ("bpy", "bmesh", "mathutils")}
    sys.modules["bpy"] = fake_bpy
    sys.modules["bmesh"] = fake_bmesh
    sys.modules["mathutils"] = fake_mu
    try:
        mod = importlib.util.module_from_spec(spec_mod)
        spec_mod.loader.exec_module(mod)
    finally:
        for k, v in sys_backup.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v

    assert mod._osso_socket("peitoral", "r15@1") == "UpperTorso"
    assert mod._osso_socket("calcas", "r15@1") == "LowerTorso"
    assert mod._osso_socket("elmo", "r15@1") == "Head"
    assert mod._osso_socket("escudo", "r15@1") == "LeftHand"
    assert mod._osso_socket("luvas", "r15@1") == "RightHand"
    assert mod._osso_socket("botas", "r15@1") == "RightFoot"
    assert mod._osso_socket("ombreiras", "r15@1") == "LeftUpperArm"

    clothes_dir = tmp_path / "clothes" / "cavaleiro" / "elmo01"
    clothes_dir.mkdir(parents=True)
    mhclo_alvo = clothes_dir / "elmo01.mhclo"
    mhclo_alvo.write_text("name elmo01\n", encoding="utf-8")

    ant_env = os.environ.get("FORGE3D_MPFB_ASSETS")
    os.environ["FORGE3D_MPFB_ASSETS"] = str(tmp_path)
    try:
        achado = mod._encontrar_mhclo("makehuman://clothes/cavaleiro/elmo01", subpasta="clothes")
        assert Path(achado).resolve() == mhclo_alvo.resolve()
    finally:
        if ant_env is None:
            os.environ.pop("FORGE3D_MPFB_ASSETS", None)
        else:
            os.environ["FORGE3D_MPFB_ASSETS"] = ant_env

    estilo = mod._resolver_estilo_visual(
        {
            "parte": "peitoral",
            "prompt": "armadura de esmeralda e ouro polido",
            "paleta": ["#198f57", "#d9ad3d"],
        }
    )
    assert estilo["tint"] is not None and estilo["tint"][1] > estilo["tint"][0]
    assert estilo["metallic"] >= 0.8
    assert estilo["roughness"] < 0.35


def test_extrude_orientacao_espada_invertida():
    """Espada desenhada de ponta-cabeca e virada 180 graus quando pivot == 'empunhadura'."""
    import importlib.util
    import sys
    import types

    spec_mod = importlib.util.spec_from_file_location(
        "extrude_2d_mod",
        Path(__file__).resolve().parent.parent / "blender" / "extrude_2d.py",
    )
    assert spec_mod and spec_mod.loader
    sys_backup = {k: sys.modules.get(k) for k in ("bpy", "bmesh")}
    sys.modules["bpy"] = types.ModuleType("bpy")
    sys.modules["bmesh"] = types.ModuleType("bmesh")
    try:
        mod = importlib.util.module_from_spec(spec_mod)
        spec_mod.loader.exec_module(mod)
    finally:
        for k, v in sys_backup.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v

    # Espada de ponta-cabeca: ponta fina em z=0, lamina alargando ate z=0.70, guarda em z=0.72..0.80, cabo z=0.80..1.0
    espada_invertida = [
        (0.0, 0.0),
        (0.06, 0.25),
        (0.08, 0.70),
        (0.24, 0.72),
        (0.24, 0.79),
        (0.04, 0.80),
        (0.04, 1.00),
        (-0.04, 1.00),
        (-0.04, 0.80),
        (-0.24, 0.79),
        (-0.24, 0.72),
        (-0.08, 0.70),
        (-0.06, 0.25),
    ]
    pts_corrigidos, rot, _ = mod._orientar_arma_para_empunhadura(espada_invertida, "arma", "empunhadura")
    assert rot == 180
    assert mod._largura_na_altura(pts_corrigidos, 0.97) < mod._largura_na_altura(pts_corrigidos, 0.25)

    # Machado normal (cabo uniforme embaixo, lamina em cima) NAO deve ser invertido
    machado_em_pe = [
        (-0.03, 0.0),
        (0.03, 0.0),
        (0.03, 0.65),
        (0.22, 0.70),
        (0.24, 0.95),
        (0.03, 1.00),
        (-0.03, 1.00),
        (-0.03, 0.65),
    ]
    _, rot_ax, _ = mod._orientar_arma_para_empunhadura(machado_em_pe, "arma", "empunhadura")
    assert rot_ax == 0


def test_delight_bronze_e_gunmetal():
    """delight._mapas_pbr_pil reconhece bronze/cobre e gunmetal escuro com contraste sem quebrar couro."""
    from PIL import Image, ImageDraw
    import importlib.util

    spec_mod = importlib.util.spec_from_file_location(
        "delight_mod",
        Path(__file__).resolve().parent.parent / "tools" / "delight.py",
    )
    assert spec_mod and spec_mod.loader
    mod = importlib.util.module_from_spec(spec_mod)
    spec_mod.loader.exec_module(mod)

    # Bronze com realce especular sobre fundo transparente (contraste >= 18)
    im_bronze = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d_b = ImageDraw.Draw(im_bronze)
    d_b.rectangle([(8, 8), (56, 56)], fill=(195, 118, 56, 255))
    d_b.rectangle([(24, 24), (40, 40)], fill=(245, 195, 130, 255))
    met_b, _ = mod._mapas_pbr_pil(im_bronze)
    assert met_b.getpixel((23, 32)) >= 200

    # Gunmetal escuro com realce sobre fundo transparente
    im_gun = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d_g = ImageDraw.Draw(im_gun)
    d_g.rectangle([(8, 8), (56, 56)], fill=(66, 70, 76, 255))
    d_g.rectangle([(26, 26), (38, 38)], fill=(125, 130, 138, 255))
    met_g, _ = mod._mapas_pbr_pil(im_gun)
    assert met_g.getpixel((25, 32)) >= 190


@pytest.mark.blender
def test_autorig_composicao_quaternions_multiplos_eixos():
    """aplicar_animacoes_multi compoe rotacoes no mesmo osso e frame sem sobrescrever eixo anterior."""
    script = """
import bpy, math, sys
from mathutils import Quaternion
sys.path.insert(0, ".")
from blender import autorig
bpy.ops.wm.read_factory_settings(use_empty=True)
arm = bpy.data.armatures.new("a")
rig = bpy.data.objects.new("rig", arm)
bpy.context.collection.objects.link(rig)
bpy.context.view_layer.objects.active = rig
bpy.ops.object.mode_set(mode="EDIT")
b = arm.edit_bones.new("UpperArm.L")
b.head = (0, 0, 1)
b.tail = (0.3, 0, 1)
bpy.ops.object.mode_set(mode="OBJECT")
clipes = [{
    "nome": "slash",
    "duracao_s": 0.5,
    "fps": 24,
    "ossos": ["UpperArm.L"],
    "chaves": [{
        "frame": 1,
        "poses": [
            {"osso": "UpperArm.L", "eixo": "X", "graus": 30.0},
            {"osso": "UpperArm.L", "eixo": "Z", "graus": 45.0},
        ],
    }],
}]
autorig.aplicar_animacoes_multi(rig, clipes)
qx = Quaternion((1, 0, 0), math.radians(30.0))
qz = Quaternion((0, 0, 1), math.radians(45.0))
esperado = qx @ qz
acao = bpy.data.actions["slash"]
bpy.context.scene.frame_set(1)
rig.animation_data.action = acao
bpy.context.view_layer.update()
obtido = rig.pose.bones["UpperArm.L"].rotation_quaternion
dot = abs(obtido.dot(esperado))
assert dot > 0.9999, f"dot={dot}, obtido={obtido}, esperado={esperado}"
print("QUAT_COMPOSE_OK")
"""
    proc = subprocess.run(
        ["blender", "-b", "--python-expr", script],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0 and "QUAT_COMPOSE_OK" in proc.stdout, proc.stderr + proc.stdout


@pytest.mark.blender
def test_e2e_forge3d_run_modular_armor_e_extrude_2d(tmp_path):
    """E2E real `forge3d plan` + `forge3d run`: peitoral, botas, elmo, escudo e espada extrude_2d (G1-G9)."""
    if not _tem_mpfb2_clothes():
        pytest.skip("Pacote MPFB2 clothes nao instalado no ambiente")

    from PIL import Image, ImageDraw
    import sys

    f_home = tmp_path / "f_home"
    f_cfg = tmp_path / "f_cfg"
    saida = f_home / "saida" / "e2e_armadura"
    f_home.mkdir(parents=True)
    f_cfg.mkdir(parents=True)
    saida.mkdir(parents=True)

    # Espada desenhada de ponta-cabeca (ponta no topo Y=490 da imagem PIL -> bottom Z=0 no Blender antes do fix!)
    espada_png = tmp_path / "espada_inv.png"
    im = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im)
    # Cabo e pomo em cima (y pequeno = topo da imagem = z alto antes da correcao)
    draw.ellipse([(116, 10), (140, 28)], fill=(215, 175, 55, 255))
    draw.rectangle([(120, 26), (136, 60)], fill=(115, 65, 30, 255))
    draw.rectangle([(84, 58), (172, 72)], fill=(215, 175, 55, 255))
    # Lamina apontando para baixo (y=246)
    draw.polygon([(114, 72), (142, 72), (139, 200), (128, 246), (117, 200)], fill=(205, 215, 230, 255))
    im.save(espada_png)

    from forge3d.canonical import sha256_arquivo

    spec_doc = {
        "schema": "forge3d/spec@3",
        "projeto": "e2e_armor_test",
        "perfil": "godot4",
        "destino_exportacao": str(saida),
        "requisicao": {
            "id": "req-e2e-01",
            "isolamento": "estrito",
            "base_externa": {
                "origem": str(espada_png),
                "sha256": sha256_arquivo(espada_png),
                "tipo": "prop_equipavel",
            },
        },
        "lote": [
            {
                "id": "e2e.peitoral.01",
                "tipo": "prop_equipavel",
                "rota": "mesh",
                "parte": "peitoral",
                "altura_metros": 1.65,
                "esqueleto": "godot-humanoid@1",
                "prompt": "peitoral de armadura esmeralda e ouro",
                "paleta": ["#198f57", "#d9ad3d"],
                "colisao": "none",
                "seed": 201,
            },
            {
                "id": "e2e.botas.01",
                "tipo": "prop_equipavel",
                "rota": "mesh",
                "parte": "botas",
                "altura_metros": 0.35,
                "esqueleto": "godot-humanoid@1",
                "prompt": "botas de ferro escuro",
                "colisao": "none",
                "seed": 202,
            },
            {
                "id": "e2e.elmo.01",
                "tipo": "prop_equipavel",
                "rota": "mesh",
                "parte": "elmo",
                "altura_metros": 0.32,
                "pivot": "base",
                "prompt": "elmo de cavaleiro prateado",
                "colisao": "none",
                "seed": 203,
            },
            {
                "id": "e2e.escudo.01",
                "tipo": "prop_equipavel",
                "rota": "mesh",
                "parte": "escudo",
                "altura_metros": 0.78,
                "pivot": "centro",
                "prompt": "escudo real de ouro e rubi",
                "colisao": "none",
                "seed": 204,
            },
            {
                "id": "e2e.espada.01",
                "tipo": "prop_equipavel",
                "rota": "mesh",
                "parte": "arma",
                "extrudir_2d": True,
                "origem": str(espada_png),
                "altura_metros": 1.05,
                "pivot": "empunhadura",
                "prompt": "espada longa de aco",
                "colisao": "convex",
                "seed": 205,
            },
        ],
    }
    spec_file = tmp_path / "spec.json"
    spec_file.write_text(json.dumps(spec_doc, indent=2), encoding="utf-8")

    env = dict(os.environ)
    env["FORGE3D_HOME"] = str(f_home)
    env["FORGE3D_CONFIG"] = str(f_cfg)
    env["FORGE3D_DEVICE"] = "cpu"

    cli_bin = str(Path(sys.executable).parent / "forge3d")

    # 1. `forge3d plan`: zero VRAM para todas as pecas
    p_plan = subprocess.run(
        [cli_bin, "plan", "--json", "--no-cache", str(spec_file)],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    assert p_plan.returncode == 0, p_plan.stderr + p_plan.stdout
    plano = json.loads(p_plan.stdout)
    for it in plano.get("itens", []):
        assert it["custo"]["vram_mb"] == 0, f"VRAM nao zerada para {it['id']}: {it['custo']}"

    # 2. `forge3d run`: G1-G9 verdes, licenca G8 correta e escala exata
    p_run = subprocess.run(
        [cli_bin, "run", "--json", "--no-cache", str(spec_file)],
        capture_output=True,
        text=True,
        env=env,
        timeout=300,
    )
    assert p_run.returncode == 0, p_run.stderr + p_run.stdout
    rel_run = json.loads(p_run.stdout)
    assert rel_run.get("resumo", {}).get("publicados") == 5, rel_run

    licencas_esperadas = {
        "e2e.peitoral.01": "MPFB2 / MakeHuman Base Mesh",
        "e2e.botas.01": "MPFB2 / MakeHuman Base Mesh",
        "e2e.elmo.01": "MPFB2 / MakeHuman Base Mesh",
        "e2e.escudo.01": "MPFB2 / MakeHuman Base Mesh",
        "e2e.espada.01": "procedural (sem modelo de terceiro)",
    }
    for item_id, mod_esp in licencas_esperadas.items():
        man = json.loads((saida / f"{item_id}.manifest.json").read_text(encoding="utf-8"))
        assert man["qc"]["aprovado"] is True, f"QC falhou para {item_id}: {man['qc']}"
        assert man["licenca"]["modelo"] == mod_esp, f"Licenca incorreta para {item_id}: {man['licenca']}"
        for g_res in man["qc"]["gates"]:
            assert g_res["status"] == "ok", f"{item_id} falhou {g_res['id']}: {g_res}"

    import struct

    def _ler_positions_glb(glb_bytes: bytes) -> list[tuple[float, float, float]]:
        jlen = struct.unpack_from("<I", glb_bytes, 12)[0]
        g_json = json.loads(glb_bytes[20 : 20 + jlen])
        bin_off = 20 + jlen + 8
        acc = g_json["accessors"][g_json["meshes"][0]["primitives"][0]["attributes"]["POSITION"]]
        bv = g_json["bufferViews"][acc["bufferView"]]
        return [
            struct.unpack_from(
                "<fff", glb_bytes, bin_off + bv.get("byteOffset", 0) + acc.get("byteOffset", 0) + i * 12
            )
            for i in range(acc["count"])
        ]

    # Confirma altura exata de botas no POSITION do GLB (sem distorcao de Icosphere)
    pts_botas = _ler_positions_glb((saida / "e2e.botas.01.glb").read_bytes())
    alt_botas = max(p[1] for p in pts_botas) - min(p[1] for p in pts_botas)
    assert abs(alt_botas - 0.35) < 0.002, f"altura botas glTF={alt_botas}"

    # Confirma baseColor standalone da espada e ponta orientada para cima (+Y no glTF)
    assert (saida / "e2e.espada.01_baseColor.png").is_file()
    pts_espada = _ler_positions_glb((saida / "e2e.espada.01.glb").read_bytes())
    y_min = min(p[1] for p in pts_espada)
    y_max = max(p[1] for p in pts_espada)
    topo_xs = [abs(p[0]) for p in pts_espada if p[1] > y_min + 0.90 * (y_max - y_min)]
    guarda_xs = [
        abs(p[0])
        for p in pts_espada
        if (y_min + 0.12 * (y_max - y_min)) <= p[1] <= (y_min + 0.38 * (y_max - y_min))
    ]
    # Guarda na metade inferior e ponta fina no topo (+Y)
    assert max(topo_xs) < max(guarda_xs) * 0.5, f"espada invertida: topo={max(topo_xs)}, guarda={max(guarda_xs)}"
