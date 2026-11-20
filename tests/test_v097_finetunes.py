"""Testes de finetunes e regressoes do Forge3D v0.9.7 (D130+).

Contratos verificados de forma independente ('Sem Oraculo Comprado'):
1. rbx.exportar_r15 com model_id emite place .rbxlx pronto para Play.
2. rbx.exportar_r15 com exigir_asset_ids e CLI export-r15 fail-fast vs rascunho-local.
3. qc_roblox_anim.verificar_g14_animacao_roblox arvore Pose aninhada e play_studio.
4. tools/r15_play_g14.montar_codigo_g14 verifica Bone + Motor6D e AnimationController.
5. mesh_diag._delight_ativo com qualidade ultra e flags de ambiente.
6. tools/delight_pbr classifica ferro_escuro vs pano, pele, couro e cabelo.
7. concept_views_origem preserva PNG de origem byte-a-byte e gera apenas laterais/traseira.
8. bake_pbr_config.px_bake_recomendado e salto de bevel/subsurf em malhas densas.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from xml.etree import ElementTree

import pytest
import yaml
from PIL import Image, ImageDraw

from forge3d import cli, config, profiles, qc_roblox_anim, rbx
from forge3d.errors import ForgeError
from forge3d.providers import concept_views_origem, mesh_diag

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "blender"))
import bake_pbr_config  # noqa: E402
from forge3d import plan_inspect  # noqa: E402
from tools import delight, delight_pbr  # noqa: E402
from tools.r15_play_g14 import montar_codigo_g14  # noqa: E402

_R15_PARTS_15 = [
    "LowerTorso", "UpperTorso", "Head", "LeftUpperArm", "LeftLowerArm", "LeftHand",
    "RightUpperArm", "RightLowerArm", "RightHand", "LeftUpperLeg", "LeftLowerLeg",
    "LeftFoot", "RightUpperLeg", "RightLowerLeg", "RightFoot",
]


def test_rbx_exportar_r15_model_id_ready_to_play(tmp_path: Path) -> None:
    """Contrato 1: exportar_r15 com model_id emite .rbxlx pronto para Play."""
    config.adicionar(str(tmp_path))
    saida, model_id = tmp_path / "guard_model.rbxlx", "120880990771470"
    rel = rbx.exportar_r15(
        "examples/lote_09_r15.yaml", "personagem.r15.guard.01", saida=saida, model_id=model_id,
    )
    assert rel["ok"] is True and rel["model_id"] == model_id and rel["modo_rig"] == "model"

    xml_text = saida.read_text(encoding="utf-8")
    root = ElementTree.fromstring(xml_text)

    # 1. Server Script: carrega modelo e cria Animator antes de sinalizar ready
    srv_scripts = [
        e for e in root.iter("Item")
        if e.get("class") == "Script" and (e.findtext("Properties/string[@name='Name']") or "") == "Forge3DLoadModel"
    ]
    assert len(srv_scripts) == 1
    src_srv = srv_scripts[0].findtext("Properties/ProtectedString[@name='Source']") or ""
    assert f"InsertService:LoadAsset({model_id})" in src_srv or (
        f"MODEL_ID = {model_id}" in src_srv and "InsertService:LoadAsset(MODEL_ID)" in src_srv
    )
    assert 'Instance.new("AnimationController")' in src_srv and 'Instance.new("Animator")' in src_srv
    assert 'modelo:SetAttribute("Forge3DModelReady", true)' in src_srv

    # 2. Client LocalScript: toca animacao nativamente (sem fallback manual Bone.CFrame)
    cli_scripts = [
        e for e in root.iter("Item")
        if e.get("class") == "LocalScript" and (e.findtext("Properties/string[@name='Name']") or "") == "Forge3DPlayAnim"
    ]
    assert len(cli_scripts) == 1
    src_cli = cli_scripts[0].findtext("Properties/ProtectedString[@name='Source']") or ""
    assert "KeyframeSequenceProvider:RegisterKeyframeSequence" in src_cli
    assert "animator:LoadAnimation" in src_cli and "track:Play(" in src_cli
    assert "Bone.CFrame" not in src_cli and "Bone.Transform" not in src_cli

    # 3. Zero MeshId nulos e zero URLs locais de textura .png
    assert '<Content name="MeshId"><null>' not in xml_text and ".png" not in xml_text


def test_rbx_exportar_r15_asset_ids_fail_fast_and_cli(tmp_path: Path) -> None:
    """Contrato 2: rota mesh nao-blocky exige asset_ids e valida CLI fail-fast vs rascunho-local."""
    config.adicionar(str(tmp_path))
    dest = tmp_path / "dest"
    dest.mkdir(parents=True)

    lote_yaml = tmp_path / "lote_mesh.yaml"
    lote_yaml.write_text(yaml.safe_dump({
        "schema": "forge3d/spec@6", "projeto": "demo", "perfil": "roblox-aa-80", "destino_exportacao": str(dest),
        "lote": [{
            "id": "boss.mesh.01", "tipo": "criatura", "rota": "mesh", "prompt": "golem", "seed": 42,
            "altura_metros": 2.2, "auto_rig": True, "esqueleto": "r15@1",
            "partes": [{"nome": n} for n in _R15_PARTS_15], "rig": {"modo": "motor6d", "esqueleto": "r15@1"},
        }],
    }), encoding="utf-8")

    ancoras = {n: [0.0, 1.0, 0.0] for n in _R15_PARTS_15}
    man_file = dest / "boss.mesh.01.manifest.json"
    man_file.write_text(json.dumps({
        "schema": "forge3d/manifest@6", "asset_id": "boss.mesh.01",
        "partes": [{"nome": n, "junta": "RootJoint", "ancora": [0, 0, 0], "bbox": [1, 1, 1], "triangulos": 12, "arquivo": f"{n}.glb"} for n in _R15_PARTS_15],
        "rig": {"esqueleto": "r15@1", "ossos": 16, "modo": "motor6d", "ancoras": ancoras},
        "files": [{"caminho": f"{n}.glb", "papel": "parte"} for n in _R15_PARTS_15],
    }), encoding="utf-8")

    # 1. Python direto: exigir_asset_ids=True falha com FORGE-E-SPEC
    with pytest.raises(ForgeError) as exc_info:
        rbx.exportar_r15(lote_yaml, "boss.mesh.01", saida=tmp_path / "fail.rbxlx", exigir_asset_ids=True)
    assert exc_info.value.codigo == "FORGE-E-SPEC" and "MeshId sem rbxassetid://" in str(exc_info.value)

    # 2. Python direto: exigir_asset_ids=False passa (modo rascunho)
    assert rbx.exportar_r15(lote_yaml, "boss.mesh.01", saida=tmp_path / "draft.rbxlx", exigir_asset_ids=False)["ok"] is True

    # 3. Python direto: asset_ids validos passa com rbxassetid://
    valid_ids = {f"{n}.glb": f"rbxassetid://{2000 + i}" for i, n in enumerate(_R15_PARTS_15)}
    assert rbx.exportar_r15(lote_yaml, "boss.mesh.01", saida=tmp_path / "pub.rbxlx", asset_ids=valid_ids, exigir_asset_ids=True)["ok"] is True

    # 4. CLI fail-fast (exit code 2) sem --rascunho-local nem --asset-ids
    assert cli.main(["export-r15", str(lote_yaml), "--item", "boss.mesh.01", "--saida", str(tmp_path / "cfail.rbxlx")]) == 2

    # 5. CLI com --rascunho-local (exit code 0)
    assert cli.main(["export-r15", str(lote_yaml), "--item", "boss.mesh.01", "--saida", str(tmp_path / "cdraft.rbxlx"), "--rascunho-local"]) == 0

    # 6. CLI com --asset-ids JSON (exit code 0)
    ids_json = tmp_path / "asset_ids.json"
    ids_json.write_text(json.dumps(valid_ids), encoding="utf-8")
    assert cli.main(["export-r15", str(lote_yaml), "--item", "boss.mesh.01", "--saida", str(tmp_path / "cpub.rbxlx"), "--asset-ids", str(ids_json)]) == 0


def test_qc_roblox_anim_g14_nested_pose_and_play_studio(tmp_path: Path) -> None:
    """Contrato 3: verificar_g14_animacao_roblox exige pose_aninhada e suporta play_studio."""
    perfil = profiles.carregar("roblox-aa-80")
    item = {"id": "char.anim.01", "rig": {"modo": "motor6d", "esqueleto": "r15@1"}, "animacoes_base": ["walk"]}

    # 1. Pose aninhada nativa (offline -> skip play_studio sem reprovar G14)
    res_ok = qc_roblox_anim.verificar_g14_animacao_roblox(item, perfil, tmp_path, [])
    assert res_ok["status"] == "ok" and res_ok["medido"]["pose_aninhada"] is True
    assert res_ok["medido"]["play_studio"] == {"status": "skip", "motivo": "studio_mcp_nao_executado"}

    # 2. Relatorio explicito de play_studio com sucesso
    report_ok = {"status": "sucesso", "frames": 30, "max_ang_deg": 45.0}
    res_studio_ok = qc_roblox_anim.verificar_g14_animacao_roblox(item, perfil, tmp_path, [], play_report=report_ok)
    assert res_studio_ok["status"] == "ok" and res_studio_ok["medido"]["play_studio"] == report_ok

    # 3. Relatorio explicito de play_studio com falha (reprova G14)
    report_fail = {"status": "falhou", "motivo": "sem_movimento"}
    res_studio_fail = qc_roblox_anim.verificar_g14_animacao_roblox(item, perfil, tmp_path, [], play_report=report_fail)
    assert res_studio_fail["status"] == "falhou"
    assert "play_studio_falhou:sem_movimento" in res_studio_fail["medido"]["problemas"]

    # 4. Pose plana / sem aninhamento (reprovacao de pose_aninhada)
    flat_xml = (
        '<?xml version="1.0" encoding="utf-8"?><roblox version="4">'
        '<Item class="KeyframeSequence"><Properties><string name="Name">walk</string><bool name="Loop">true</bool></Properties>'
        '<Item class="Keyframe"><Properties><float name="Time">0</float></Properties>'
        '<Item class="Pose"><Properties><string name="Name">HumanoidRootPart</string><float name="Weight">0</float></Properties></Item>'
        '<Item class="Pose"><Properties><string name="Name">LowerTorso</string><float name="Weight">1</float></Properties></Item>'
        "</Item></Item></roblox>"
    )
    flat_file = tmp_path / "walk_flat.rbxmx"
    flat_file.write_text(flat_xml, encoding="utf-8")
    res_flat = qc_roblox_anim.verificar_g14_animacao_roblox(
        {"id": "char.flat"}, perfil, tmp_path, [{"caminho": flat_file.name, "papel": "animacao"}],
    )
    assert res_flat["status"] == "falhou" and res_flat["medido"]["pose_aninhada"] is False
    assert any("pose" in str(p) for p in res_flat["medido"].get("problemas", []))


def test_r15_play_g14_luau_checks_bone_motor6d_and_animator() -> None:
    """Contrato 4: tools/r15_play_g14.montar_codigo_g14 afere Bone/Motor6D e AnimationController."""
    code = montar_codigo_g14("walk")
    assert 'local CLIPE_NOME = "walk"' in code
    assert 'desc:IsA("Motor6D") or desc:IsA("Bone")' in code
    assert "joint.Transform" in code and "cframeDelta(CFrame.identity, joint.Transform)" in code
    assert 'inst:FindFirstChildOfClass("Humanoid") or inst:FindFirstChildOfClass("AnimationController")' in code
    assert 'modelo:FindFirstChildOfClass("Humanoid") or modelo:FindFirstChildOfClass("AnimationController")' in code
    assert "movedSet[joint] = true" in code


def test_mesh_diag_delight_ativo_ultra(monkeypatch: pytest.MonkeyPatch) -> None:
    """Contrato 5: _delight_ativo ativo para qualidade ultra e respeita variavel de ambiente."""
    monkeypatch.delenv("FORGE3D_DELIGHT", raising=False)
    assert mesh_diag._delight_ativo({"qualidade": "ultra"}) is True
    assert mesh_diag._delight_ativo({"qualidade": "hero"}) is True
    assert mesh_diag._delight_ativo({"qualidade": "standard"}) is True
    assert mesh_diag._delight_ativo({"qualidade": "draft"}) is False

    monkeypatch.setenv("FORGE3D_DELIGHT", "0")
    assert mesh_diag._delight_ativo({"qualidade": "ultra"}) is False

    monkeypatch.setenv("FORGE3D_DELIGHT", "1")
    assert mesh_diag._delight_ativo({"qualidade": "draft"}) is True


def test_delight_pbr_classifies_dark_iron_vs_matte_cloth_skin_hair() -> None:
    """Contrato 6: delight_pbr classifica ferro_escuro e preserva tecido fosco, pele e cabelo."""
    # 1. Ferro escuro esculpido (gradiente cinza com contraste local e meio-tom)
    img_iron = Image.new("RGBA", (64, 64), (50, 52, 55, 255))
    d_iron = ImageDraw.Draw(img_iron)
    for y in range(4, 60, 4):
        d_iron.line((4, y, 60, y), fill=(74, 76, 78, 255), width=2)
        d_iron.line((4, y + 2, 60, y + 2), fill=(35, 37, 39, 255), width=2)

    # 2. Tecido escuro fosco (uniforme), 3. Pele / couro, 4. Cabelo escuro, 5. Mecha clara de cabelo
    img_cloth = Image.new("RGBA", (64, 64), (35, 36, 40, 255))
    img_skin = Image.new("RGBA", (64, 64), (150, 95, 58, 255))
    img_hair = Image.new("RGBA", (64, 64), (25, 22, 20, 255))
    d_hair = ImageDraw.Draw(img_hair)
    for y in range(4, 60, 4):
        d_hair.line((4, y, 60, y), fill=(32, 28, 26, 255), width=1)
    img_hl = Image.new("RGBA", (64, 64), (220, 215, 195, 255))

    for fn_pbr in (delight.estimar_mapas_pbr, delight_pbr._mapas_pbr_pil):
        m_iron, r_iron = fn_pbr(img_iron)
        assert m_iron.getpixel((30, 30)) > 140 and r_iron.getpixel((30, 30)) < 120

        m_cloth, _ = fn_pbr(img_cloth)
        assert m_cloth.getpixel((30, 30)) < 30

        m_skin, _ = fn_pbr(img_skin)
        assert m_skin.getpixel((30, 30)) < 30

        m_hair, _ = fn_pbr(img_hair)
        assert m_hair.getpixel((30, 30)) < 30

        m_hl, _ = fn_pbr(img_hl)
        assert m_hl.getpixel((30, 30)) < 20


def test_concept_views_origem_preserves_byte_for_byte_and_calls_lateral_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Contrato 7: gerar_vistas_de_origem preserva PNG de origem e chama Gemini apenas 3x."""
    origem_png = tmp_path / "origem_aprovada.png"
    Image.new("RGBA", (64, 64), (180, 120, 80, 255)).save(origem_png, format="PNG")
    origem_bytes = origem_png.read_bytes()

    destino = tmp_path / "concept_out"
    chamadas: list[dict] = []

    def mock_gemini(_ai, prompt, _neg, seed, out_png, **kwargs):
        chamadas.append({"prompt": prompt, "seed": seed, "out": out_png.name, "kwargs": kwargs})
        Image.new("RGBA", (64, 64), (90, 90, 90, 255)).save(out_png, format="PNG")
        return {"ok": True, "tempo_s": 0.05, "modelo": "gemini/test-v097"}

    monkeypatch.setattr(concept_views_origem, "_chamar_gemini_conceito", mock_gemini)

    res = concept_views_origem.gerar_vistas_de_origem(
        {"id": "hero.concept.01", "prompt": "cyber knight armor", "vistas": 4}, origem_png, destino,
    )
    assert res["ok"] is True and res["origem_frontal_preservada"] is True
    assert (destino / "concept_front.png").read_bytes() == origem_bytes
    assert (destino / "concept.png").read_bytes() == origem_bytes
    assert len(chamadas) == 3
    assert [c["out"] for c in chamadas] == ["concept_back.png", "concept_left.png", "concept_right.png"]
    for c in chamadas:
        assert c["kwargs"].get("referencia_png") == origem_png


def test_bake_pbr_config_resolutions_and_dense_mesh_skip() -> None:
    """Contrato 8: px_bake_recomendado preserva 1024 no roblox e pula bevel/subsurf em malhas densas."""
    # 1. roblox-aa-80 / teto 2048 mantem normal_max=1024
    assert bake_pbr_config.px_bake_recomendado("hero", None, teto_perfil=2048) == (2048, 1024)
    assert plan_inspect._px_bake_estimado("hero", {"material": {"textura_max": 2048}}) == (2048, 1024)

    # 2. Perfil 4k (godot4-aa) escala para (2048, 2048)
    assert bake_pbr_config.px_bake_recomendado("hero", None, teto_perfil=4096) == (2048, 2048)
    assert plan_inspect._px_bake_estimado("hero", {"material": {"textura_max": 4096}}) == (2048, 2048)

    # 3. Malhas densas (> 60k tris) com color_attributes pulam bevel/subsurf
    class MockPoly:
        def __init__(self, n: int) -> None:
            self.vertices = [0] * n

    class MockData:
        def __init__(self, n_tris: int) -> None:
            self.polygons = [MockPoly(3) for _ in range(n_tris)]
            self.color_attributes = ["Col"]

    class MockObj:
        def __init__(self, n_tris: int) -> None:
            self.data = MockData(n_tris)

    res_densa = bake_pbr_config.preparar_high_mesh_detalhe_alto(MockObj(65_000), {"ativo": True})
    assert res_densa["aplicado"] is False
    assert res_densa["motivo"] == "malha_i23d_ja_densa" and res_densa["tris_high_inicial"] == 65_000

    # Inativo ou sem objeto retorna aplicado=False
    assert bake_pbr_config.preparar_high_mesh_detalhe_alto(MockObj(100), {"ativo": False}) == {"aplicado": False}
    assert bake_pbr_config.preparar_high_mesh_detalhe_alto(None, {"ativo": True}) == {"aplicado": False}
