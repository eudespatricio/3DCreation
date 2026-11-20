"""Testes headless do plugin Godot 4 (LOD, materiais ORM, idempotencia e CharacterBody3D)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from forge3d import sync_godot_sidecars
from tests.test_godot_addon import (
    CHECK_GD,
    HERO_REAL_GLB,
    PLUGIN_GD,
    POST_IMPORT_GD,
    RAIZ,
    _criar_glb_colisor,
    _criar_glb_multimesh,
    _criar_glb_rigged,
    _escrever_glb,
    _escrever_manifesto,
    _exigir_godot,
    _rodar_godot,
    _validar_cena_godot,
)


def test_post_import_animacoes_lod1_e_check_sintetico(tmp_path: Path) -> None:
    godot = _exigir_godot()
    asset_id = "hero.sintetico.01"
    glb = tmp_path / f"{asset_id}.glb"
    lod1_glb = tmp_path / f"{asset_id}_LOD1.glb"
    col_glb = tmp_path / f"{asset_id}_colisao.glb"
    manifest = tmp_path / f"{asset_id}.manifest.json"

    _criar_glb_rigged(glb, asset_id, escala=1.0, com_animacoes=True)
    _criar_glb_rigged(lod1_glb, f"{asset_id}_LOD1", escala=0.95, com_animacoes=True)
    _criar_glb_colisor(col_glb, f"{asset_id}_colisor")
    _escrever_manifesto(manifest, asset_id, com_lod1=True, com_colisor=True)

    pi = _rodar_godot(godot, ["--script", str(CHECK_GD), "--", str(glb)])
    assert pi.returncode == 0 and "GODOT_POST_IMPORT_OK" in pi.stdout, pi.stdout + pi.stderr
    assert "bodies=1 shapes=1 anims=1 meta=true" in pi.stdout, pi.stdout

    corpo_gd = """
\tvar players := cena.find_children("*", "AnimationPlayer", true, false)
\tif players.size() != 1:
\t\t_fail("AnimationPlayer count=%d" % players.size(), cena)
\t\treturn
\tvar skels := cena.find_children("*", "Skeleton3D", true, false)
\tif skels.size() != 1:
\t\t_fail("Skeleton3D count=%d" % skels.size(), cena)
\t\treturn
\tvar player := players[0] as AnimationPlayer
\tif player.has_animation("idle-loop"):
\t\t_fail("idle-loop presente", cena)
\t\treturn
\tfor clip in ["idle", "walk", "run"]:
\t\tif not player.has_animation(clip) or player.get_animation(clip).loop_mode != Animation.LOOP_LINEAR:
\t\t\t_fail("clip %s sem LOOP_LINEAR" % clip, cena)
\t\t\treturn
\tif not player.has_animation("jump") or player.get_animation("jump").loop_mode != Animation.LOOP_NONE:
\t\t_fail("clip jump sem LOOP_NONE", cena)
\t\treturn
\tvar meshes := cena.find_children("*", "MeshInstance3D", true, false)
\tif meshes.size() != 2:
\t\t_fail("MeshInstance3D count=%d" % meshes.size(), cena)
\t\treturn
\tvar lod0 := meshes[0] as MeshInstance3D
\tvar lod1 := meshes[1] as MeshInstance3D
\tif String(lod1.name) != "LOD1_" + String(lod0.name):
\t\t_fail("nome LOD1 inesperado: %s vs %s" % [lod1.name, lod0.name], cena)
\t\treturn
\tif lod0.visibility_range_begin != 0.0 or lod0.visibility_range_end <= 0.0 or lod0.visibility_range_fade_mode != GeometryInstance3D.VISIBILITY_RANGE_FADE_SELF:
\t\t_fail("visibility_range LOD0 invalido", cena)
\t\treturn
\tif not is_equal_approx(lod1.visibility_range_begin, lod0.visibility_range_end) or lod1.visibility_range_end != 0.0 or lod1.visibility_range_fade_mode != GeometryInstance3D.VISIBILITY_RANGE_FADE_SELF:
\t\t_fail("visibility_range LOD1 invalido", cena)
\t\treturn
\tif lod1.mesh == null or lod1.skin == null:
\t\t_fail("LOD1 sem mesh ou skin", cena)
\t\treturn
\tvar skel_resolvido := lod1.get_node_or_null(lod1.skeleton)
\tif skel_resolvido != skels[0]:
\t\t_fail("LOD1 skeleton nao aponta para Skeleton3D principal", cena)
\t\treturn
\tPostImport.aplicar(cena, caminho)
\tif cena.find_children("*", "MeshInstance3D", true, false).size() != 2:
\t\t_fail("aplicar duplicou LOD1", cena)
\t\treturn
\tif cena.find_children("*", "AnimationPlayer", true, false).size() != 1:
\t\t_fail("aplicar duplicou AnimationPlayer", cena)
\t\treturn
"""
    _validar_cena_godot(godot, tmp_path / "check_lod1.gd", corpo_gd, glb)


def test_post_import_hero_t2i_real_se_presente(tmp_path: Path) -> None:
    godot = _exigir_godot()
    if not HERO_REAL_GLB.is_file():
        pytest.skip(f"Asset real ausente neste host: {HERO_REAL_GLB}")

    pi = _rodar_godot(godot, ["--script", str(CHECK_GD), "--", str(HERO_REAL_GLB)])
    assert pi.returncode == 0 and "GODOT_POST_IMPORT_OK" in pi.stdout, pi.stdout + pi.stderr
    assert "bodies=0 shapes=0 anims=1 meta=true" in pi.stdout, pi.stdout

    corpo_gd = """
\tvar players := cena.find_children("*", "AnimationPlayer", true, false)
\tif players.size() != 1:
\t\t_fail("AnimationPlayer count=%d" % players.size(), cena)
\t\treturn
\tvar skels := cena.find_children("*", "Skeleton3D", true, false)
\tif skels.size() != 1:
\t\t_fail("Skeleton3D count=%d" % skels.size(), cena)
\t\treturn
\tvar player := players[0] as AnimationPlayer
\tif player.has_animation("idle-loop"):
\t\t_fail("idle-loop presente no hero real", cena)
\t\treturn
\tfor clip in ["idle", "walk", "run"]:
\t\tif player.get_animation(clip).loop_mode != Animation.LOOP_LINEAR:
\t\t\t_fail("hero clip %s sem LOOP_LINEAR" % clip, cena)
\t\t\treturn
\tif player.get_animation("jump").loop_mode != Animation.LOOP_NONE:
\t\t_fail("hero clip jump sem LOOP_NONE", cena)
\t\treturn
\tvar meshes := cena.find_children("*", "MeshInstance3D", true, false)
\tif meshes.size() != 2:
\t\t_fail("hero MeshInstance3D count=%d" % meshes.size(), cena)
\t\treturn
\tvar lod0 := meshes[0] as MeshInstance3D
\tvar lod1 := meshes[1] as MeshInstance3D
\tif not String(lod1.name).begins_with("LOD1_"):
\t\t_fail("hero LOD1 sem prefixo LOD1_: %s" % lod1.name, cena)
\t\treturn
\tif lod0.visibility_range_begin != 0.0 or lod0.visibility_range_end <= 0.0 or lod0.visibility_range_fade_mode != GeometryInstance3D.VISIBILITY_RANGE_FADE_SELF:
\t\t_fail("hero LOD0 visibility_range invalido", cena)
\t\treturn
\tif not is_equal_approx(lod1.visibility_range_begin, lod0.visibility_range_end) or lod1.visibility_range_end != 0.0 or lod1.visibility_range_fade_mode != GeometryInstance3D.VISIBILITY_RANGE_FADE_SELF:
\t\t_fail("hero LOD1 visibility_range invalido", cena)
\t\treturn
\tvar mat := lod0.mesh.surface_get_material(0)
\tif not (mat is ORMMaterial3D):
\t\t_fail("hero material nao virou ORMMaterial3D", cena)
\t\treturn
\tvar orm_mat := mat as ORMMaterial3D
\tif orm_mat.orm_texture == null or not orm_mat.normal_enabled or orm_mat.normal_texture == null:
\t\t_fail("hero ORMMaterial3D sem orm_texture ou normal_texture", cena)
\t\treturn
\tif orm_mat.texture_filter != BaseMaterial3D.TEXTURE_FILTER_LINEAR_WITH_MIPMAPS_ANISOTROPIC:
\t\t_fail("hero ORMMaterial3D sem TEXTURE_FILTER_LINEAR_WITH_MIPMAPS_ANISOTROPIC", cena)
\t\treturn
\tif lod1.get_node_or_null(lod1.skeleton) != skels[0]:
\t\t_fail("hero LOD1 skeleton nao aponta para Skeleton3D principal", cena)
\t\treturn
"""
    _validar_cena_godot(godot, tmp_path / "check_hero_real.gd", corpo_gd, HERO_REAL_GLB)


def test_montar_character_body_capsula_remove_col_e_anexos(tmp_path: Path) -> None:
    godot = _exigir_godot()
    asset_id = "hero.charbody.01"
    glb = tmp_path / f"{asset_id}.glb"
    col_glb = tmp_path / f"{asset_id}_colisao.glb"
    manifest = tmp_path / f"{asset_id}.manifest.json"

    _criar_glb_rigged(glb, asset_id, escala=1.0, com_animacoes=True)
    _criar_glb_colisor(col_glb, f"{asset_id}_colisor")
    _escrever_manifesto(manifest, asset_id, com_lod1=False, com_colisor=True)

    script = tmp_path / "check_char_body.gd"
    script.write_text(
        f"""extends SceneTree
const PostImport := preload({str(POST_IMPORT_GD)!r})

func _fail(msg: String, node: Node = null) -> void:
\tprint("TEST_FAIL " + msg)
\tif node != null:
\t\tnode.free()
\tquit(1)

func _initialize() -> void:
\tvar caminho := {str(glb)!r}
\tvar doc := GLTFDocument.new()
\tvar estado := GLTFState.new()
\tif doc.append_from_file(caminho, estado) != OK:
\t\t_fail("append_from_file falhou")
\t\treturn
\tvar body := doc.generate_scene(estado)
\tPostImport.aplicar(body, caminho)
\tif body.find_children("*", "StaticBody3D", true, false).size() != 1:
\t\t_fail("esperava 1 StaticBody3D antes de montar_character_body", body)
\t\treturn

\tvar escudo := MeshInstance3D.new()
\tescudo.name = "EscudoTeste"
\tvar char_body := PostImport.montar_character_body(body, {{"Hand.R": escudo}}, 1.85, 0.35, true)
\tif not (char_body is CharacterBody3D):
\t\t_fail("retorno nao e CharacterBody3D", char_body)
\t\treturn
\tif body.get_parent() != char_body:
\t\t_fail("body_node nao e filho do CharacterBody3D", char_body)
\t\treturn
\tif not body.find_children("*", "StaticBody3D", true, false).is_empty():
\t\t_fail("StaticBody3D _col nao foi removido", char_body)
\t\treturn

\tvar shapes := char_body.find_children("*", "CollisionShape3D", false, false)
\tif shapes.size() != 1:
\t\t_fail("CollisionShape3D direto ausente: %d" % shapes.size(), char_body)
\t\treturn
\tvar cs := shapes[0] as CollisionShape3D
\tif not (cs.shape is CapsuleShape3D):
\t\t_fail("shape nao e CapsuleShape3D", char_body)
\t\treturn
\tvar cap := cs.shape as CapsuleShape3D
\tif absf(cap.height - 1.85) > 0.001 or absf(cap.radius - 0.35) > 0.001 or absf(cs.position.y - 0.925) > 0.001:
\t\t_fail("dimensoes ou centro da capsula incorretos", char_body)
\t\treturn

\tvar attachments := char_body.find_children("*", "BoneAttachment3D", true, false)
\tif attachments.size() != 1:
\t\t_fail("BoneAttachment3D count=%d" % attachments.size(), char_body)
\t\treturn
\tvar ba := attachments[0] as BoneAttachment3D
\tvar anexo_ok := escudo.get_parent() == ba or (escudo.get_parent() is Marker3D and escudo.get_parent().get_parent() == ba)
\tif ba.bone_name != "Hand.R" or not anexo_ok:
\t\t_fail("BoneAttachment3D nao vinculou Hand.R ou escudo", char_body)
\t\treturn
\tchar_body.free()

\t# Valida remover_static_body = false preservando _col
\tvar doc2 := GLTFDocument.new()
\tvar estado2 := GLTFState.new()
\tdoc2.append_from_file(caminho, estado2)
\tvar body2 := doc2.generate_scene(estado2)
\tPostImport.aplicar(body2, caminho)
\tvar char_keep := PostImport.montar_character_body(body2, {{}}, 2.0, 0.4, false)
\tif body2.find_children("*", "StaticBody3D", true, false).size() != 1:
\t\t_fail("remover_static_body=false removeu _col", char_keep)
\t\treturn
\tchar_keep.free()
\tprint("CHAR_BODY_OK")
\tquit(0)
""",
        encoding="utf-8",
    )
    proc = _rodar_godot(godot, ["--script", str(script)])
    assert proc.returncode == 0 and "CHAR_BODY_OK" in proc.stdout, proc.stdout + proc.stderr


def test_plugin_captura_path_sem_scene_file_path(tmp_path: Path) -> None:
    godot = _exigir_godot()
    asset_id = "prop.plugin.path.01"
    glb = tmp_path / f"{asset_id}.glb"
    manifest = tmp_path / f"{asset_id}.manifest.json"
    _criar_glb_rigged(glb, asset_id, escala=1.0, com_animacoes=False)
    _escrever_manifesto(manifest, asset_id, com_lod1=False, com_colisor=False)
    man_data = json.loads(manifest.read_text(encoding="utf-8"))
    man_data["rota"] = "blocky"
    man_data["material"] = {"filtro": "nearest"}
    manifest.write_text(json.dumps(man_data, indent=1), encoding="utf-8")

    plugin_src = PLUGIN_GD.read_text(encoding="utf-8")
    assert "_get_import_options" in plugin_src
    assert "_source_queue" not in plugin_src
    assert "PostImport.aplicar(scene, source_path)" in plugin_src

    script = tmp_path / "check_plugin_path.gd"
    script.write_text(
        f"""extends SceneTree
const Plugin := preload({str(PLUGIN_GD)!r})

func _initialize() -> void:
\tvar importer := Plugin.Forge3DPostImportPlugin.new()
\tvar caminho := {str(glb)!r}
\tvar doc := GLTFDocument.new()
\tvar estado := GLTFState.new()
\tif doc.append_from_file(caminho, estado) != OK:
\t\tprint("PLUGIN_FAIL append")
\t\tquit(1)
\t\treturn
\tvar cena := doc.generate_scene(estado)
\tcena.scene_file_path = ""
\timporter._get_import_options(caminho)
\timporter._post_process(cena)
\tif not cena.has_meta("forge3d_manifest") or str(cena.get_meta("forge3d_asset_id")) != {asset_id!r}:
\t\tprint("PLUGIN_FAIL sem manifesto apos _get_import_options + _post_process")
\t\tcena.free()
\t\tquit(1)
\t\treturn
\tcena.free()
\tprint("PLUGIN_PATH_OK")
\tquit(0)
""",
        encoding="utf-8",
    )
    proc = _rodar_godot(godot, ["--editor", "--script", str(script)])
    assert proc.returncode == 0 and "PLUGIN_PATH_OK" in proc.stdout, proc.stdout + proc.stderr


def test_post_import_orm_normal_e_filtro_nearest(tmp_path: Path) -> None:
    from PIL import Image

    godot = _exigir_godot()
    asset_id = "prop.orm.01"
    glb = tmp_path / f"{asset_id}.glb"
    manifest = tmp_path / f"{asset_id}.manifest.json"
    _criar_glb_multimesh(glb, [asset_id])
    Image.new("RGB", (32, 32), (200, 150, 100)).save(tmp_path / f"{asset_id}_baseColor.png")
    Image.new("RGB", (32, 32), (128, 128, 255)).save(tmp_path / f"{asset_id}_normal.png")
    Image.new("RGB", (32, 32), (255, 180, 64)).save(tmp_path / f"{asset_id}_orm.png")
    _escrever_manifesto(manifest, asset_id, com_lod1=False, com_colisor=False)
    man_data = json.loads(manifest.read_text(encoding="utf-8"))
    man_data["rota"] = "blocky"
    man_data["material"] = {"filtro": "nearest"}
    manifest.write_text(json.dumps(man_data, indent=1), encoding="utf-8")

    corpo_gd = """
\tvar meshes := cena.find_children("*", "MeshInstance3D", true, false)
\tvar mi := meshes[0] as MeshInstance3D
\tvar mat := mi.mesh.surface_get_material(0)
\tif not (mat is ORMMaterial3D):
\t\t_fail("material nao convertido para ORMMaterial3D", cena)
\t\treturn
\tvar orm := mat as ORMMaterial3D
\tif orm.orm_texture == null or not orm.ao_enabled:
\t\t_fail("orm_texture ou ao_enabled ausente", cena)
\t\treturn
\tif not orm.normal_enabled or orm.normal_texture == null:
\t\t_fail("normal_texture nao conectado", cena)
\t\treturn
\tif orm.albedo_texture == null:
\t\t_fail("albedo_texture fallback nao conectado", cena)
\t\treturn
\tif orm.texture_filter != BaseMaterial3D.TEXTURE_FILTER_NEAREST_WITH_MIPMAPS:
\t\t_fail("texture_filter diferente de TEXTURE_FILTER_NEAREST_WITH_MIPMAPS", cena)
\t\treturn
"""
    _validar_cena_godot(godot, tmp_path / "check_orm.gd", corpo_gd, glb)


def test_post_import_skip_static_body_personagem_e_turn_180_y(tmp_path: Path) -> None:
    godot = _exigir_godot()
    asset_id = "hero.rigged.turn.01"
    glb = tmp_path / f"{asset_id}.glb"
    col_glb = tmp_path / f"{asset_id}_colisao.glb"
    manifest = tmp_path / f"{asset_id}.manifest.json"
    _criar_glb_rigged(glb, asset_id, escala=1.0, com_animacoes=True)
    _criar_glb_colisor(col_glb, f"{asset_id}_colisor")
    manifest.write_text(
        json.dumps(
            {
                "schema": "forge3d/manifest@3",
                "asset_id": asset_id,
                "perfil": "godot4",
                "determinism": "D1",
                "rig": {"esqueleto": "godot-humanoid@1", "ossos": 2},
                "frente": "+Z",
                "colisao": {"arquivo": f"{asset_id}_colisao.glb", "partes": 1, "tipo": "convex"},
            }
        ),
        encoding="utf-8",
    )

    pi = _rodar_godot(godot, ["--script", str(CHECK_GD), "--", str(glb)])
    assert pi.returncode == 0 and "GODOT_POST_IMPORT_OK" in pi.stdout, pi.stdout + pi.stderr
    assert "bodies=0 shapes=0" in pi.stdout, pi.stdout

    corpo_gd = """
\tif not cena.find_children("*", "StaticBody3D", true, false).is_empty():
\t\t_fail("StaticBody3D criado para asset com rig != null", cena)
\t\treturn
\tvar root3d := cena as Node3D
\tif absf(absf(root3d.rotation.y) - PI) > 0.001:
\t\t_fail("rotacao 180 graus Y nao aplicada: %f" % root3d.rotation.y, cena)
\t\treturn
\tPostImport.aplicar(cena, caminho)
\tif absf(absf(root3d.rotation.y) - PI) > 0.001:
\t\t_fail("rotacao 180 graus Y nao idempotente: %f" % root3d.rotation.y, cena)
\t\treturn
"""
    _validar_cena_godot(godot, tmp_path / "check_skip_turn.gd", corpo_gd, glb)


def test_attach_skinned_mesh_e_validacao_bone_attachment(tmp_path: Path) -> None:
    godot = _exigir_godot()
    asset_id = "hero.skinned.attach.01"
    glb = tmp_path / f"{asset_id}.glb"
    _criar_glb_rigged(glb, asset_id, escala=1.0, com_animacoes=False)

    script = tmp_path / "check_attach_skinned.gd"
    script.write_text(
        f"""extends SceneTree
const PostImport := preload({str(POST_IMPORT_GD)!r})

func _fail(msg: String, node: Node = null) -> void:
\tprint("TEST_FAIL " + msg)
\tif node != null:
\t\tnode.free()
\tquit(1)

func _initialize() -> void:
\tvar caminho := {str(glb)!r}
\tvar doc := GLTFDocument.new()
\tvar estado := GLTFState.new()
\tif doc.append_from_file(caminho, estado) != OK:
\t\t_fail("append_from_file falhou")
\t\treturn
\tvar body := doc.generate_scene(estado)
\tvar skels := body.find_children("*", "Skeleton3D", true, false)
\tif skels.is_empty():
\t\t_fail("Skeleton3D ausente", body)
\t\treturn
\tvar skel := skels[0] as Skeleton3D

\tvar armadura := MeshInstance3D.new()
\tarmadura.name = "PeitoralSkinned"
\tif not PostImport.attach_skinned_mesh(armadura, skel):
\t\t_fail("attach_skinned_mesh retornou false", body)
\t\treturn
\tif armadura.get_parent() != skel or armadura.get_node_or_null(armadura.skeleton) != skel:
\t\t_fail("armadura nao vinculada ao Skeleton3D alvo", body)
\t\treturn
\tif PostImport.attach_skinned_mesh(null, skel):
\t\t_fail("attach_skinned_mesh deveria retornar false para null", body)
\t\treturn

\tvar espada := MeshInstance3D.new()
\tespada.name = "Espada"
\tvar invalido := MeshInstance3D.new()
\tinvalido.name = "AnexoOssoInexistente"
\tvar char_body := PostImport.montar_character_body(body, {{"Hand.R": espada, "OssoQueNaoExiste": invalido}})
\tvar attachments := char_body.find_children("*", "BoneAttachment3D", true, false)
\tif attachments.size() != 1:
\t\t_fail("esperava apenas 1 BoneAttachment3D valido, obteve %d" % attachments.size(), char_body)
\t\treturn
\tif (attachments[0] as BoneAttachment3D).bone_name != "Hand.R":
\t\t_fail("BoneAttachment3D com osso inesperado", char_body)
\t\treturn
\tinvalido.free()
\tchar_body.free()
\tprint("ATTACH_SKINNED_OK")
\tquit(0)
""",
        encoding="utf-8",
    )
    proc = _rodar_godot(godot, ["--script", str(script)])
    assert proc.returncode == 0 and "ATTACH_SKINNED_OK" in proc.stdout, proc.stdout + proc.stderr


def test_regressao_materiais_meta_e_loop_explicito(tmp_path: Path) -> None:
    """Cobre fallback emissivo glTF, flags unlit/vcol, surface_override null-mesh, has_meta e loop=false."""
    sub = sync_godot_sidecars._construir_subresources_glb(
        {"animacoes": [{"nome": "idle", "loop": False}, {"nome": "attack", "loop": True}, {"nome": "walk"}]}
    )
    assert sub["animations"]["idle"]["settings/loop_mode"] == 0 and sub["animations"]["attack"]["settings/loop_mode"] == 1 and sub["animations"]["walk"]["settings/loop_mode"] == 1

    godot = _exigir_godot()
    em_glb = tmp_path / "emissive_clamp.glb"
    _criar_glb_multimesh(em_glb, ["Lamp"])
    raw = em_glb.read_bytes()
    jl = int.from_bytes(raw[12:16], "little")
    bl = int.from_bytes(raw[20 + jl : 24 + jl], "little")
    gltf = json.loads(raw[20 : 20 + jl])
    gltf["materials"] = [{"name": "MatEm", "emissiveFactor": [0.5, 0.1, 0.0], "pbrMetallicRoughness": {"metallicFactor": 1.0, "roughnessFactor": 1.0}}]
    _escrever_glb(em_glb, gltf, raw[28 + jl : 28 + jl + bl])
    (tmp_path / "emissive_clamp.manifest.json").write_text(json.dumps({"schema": "forge3d/manifest@6", "asset_id": "emissive_clamp", "perfil": "godot4"}), encoding="utf-8")
    qa = _rodar_godot(godot, ["--script", str(RAIZ / "tools" / "godot_visual_qa.gd"), "--", str(em_glb)])
    assert qa.returncode == 0 and "GODOT_VISUAL_QA_OK" in qa.stdout, qa.stdout + qa.stderr

    rig_glb = tmp_path / "plain_rig.glb"
    _criar_glb_rigged(rig_glb, "Body", com_animacoes=False)
    script = tmp_path / "check_mat_meta.gd"
    script.write_text(
        f"""extends SceneTree
const PostImport := preload({str(POST_IMPORT_GD)!r})
func _initialize() -> void:
\tvar doc := GLTFDocument.new(); var st := GLTFState.new(); doc.append_from_file({str(rig_glb)!r}, st)
\tvar rig := doc.generate_scene(st); var cb := PostImport.montar_character_body(rig, {{"Hand.R": MeshInstance3D.new()}})
\tvar orm := ImageTexture.create_from_image(Image.create(4, 4, false, Image.FORMAT_RGBA8))
\tvar src := StandardMaterial3D.new(); src.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
\tsrc.vertex_color_use_as_albedo = true; src.vertex_color_is_srgb = true
\tvar res := PostImport._processar_material(src, orm, null, null, false) as ORMMaterial3D
\tvar mesh := ArrayMesh.new(); var tool := SurfaceTool.new()
\tfor _i in range(2):
\t\ttool.clear(); tool.begin(Mesh.PRIMITIVE_TRIANGLES); tool.add_vertex(Vector3.ZERO); tool.add_vertex(Vector3.RIGHT); tool.add_vertex(Vector3.UP)
\t\tmesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, tool.commit_to_arrays())
\tvar mi := MeshInstance3D.new(); mi.mesh = mesh; var ov := StandardMaterial3D.new(); ov.metallic = 0.8; mi.set_surface_override_material(1, ov)
\tvar root := Node3D.new(); root.add_child(mi); PostImport._configurar_materiais(root, "", {{}}, {{}})
\tvar ok := res != null and res.shading_mode == BaseMaterial3D.SHADING_MODE_UNSHADED and res.vertex_color_use_as_albedo and res.vertex_color_is_srgb and mi.get_surface_override_material(1) != null
\tcb.free(); root.free(); print("MAT_META_OK=", ok); quit(0 if ok else 1)
""",
        encoding="utf-8",
    )
    proc = _rodar_godot(godot, ["--script", str(script)])
    assert proc.returncode == 0 and "MAT_META_OK=true" in proc.stdout, proc.stdout + proc.stderr
    assert "does not have any 'meta' values" not in (proc.stdout + proc.stderr), proc.stdout + proc.stderr
