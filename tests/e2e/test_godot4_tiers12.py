"""FA3 Godot 4 addon, sidecars & headless E2E tests (Tiers 1 & 2, opaque-box)."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

import pytest

from tests.e2e._helpers_godot import (
    ALL_17_CLIPS, CLIPS_CYCLIC, CLIPS_ONESHOT, gd_probe_header, measure_uv_edge_isotropy,
    read_glb_json, run_godot_in_project, run_godot_probe, run_godot_tool, stage_temp_godot_project,
    write_custom_glb, write_manifest, write_orm_texture_set, write_published_orm_asset,
)
from tests.e2e.conftest import RAIZ, has_blender, has_godot


def _req_godot() -> None:
    if not has_godot():
        pytest.skip("Godot 4 binary unavailable")


def _req_blender() -> None:
    if not has_blender():
        pytest.skip("Blender 4.2 binary unavailable")


# ---------------------------------------------------------------------------
# Tier 1: Godot 4 import, sidecars, ORMMaterial3D, BoneMap, LODs & clips
# ---------------------------------------------------------------------------


@pytest.mark.godot
@pytest.mark.rapido
def test_tier1_godot_sync_sidecars_and_registry(e2e_sandbox, tmp_path: Path) -> None:
    _req_godot()
    asset_id = "char.knight.01"
    write_published_orm_asset(
        e2e_sandbox.dest_dir, asset_id, tipo="personagem_humanoide", esqueleto="godot-humanoid@1",
        animacoes=["idle", "slash_combo", "cast", "bite", "gallop", "wing_flap", "glide"],
        with_lod1=True, with_colisao=True, size_xyz=(0.8, 1.8, 0.5),
    )
    proj_dir = stage_temp_godot_project(tmp_path)
    assets_dir, gd_out = proj_dir / "assets", proj_dir / "Forge3DAssets.gd"
    e2e_sandbox.allowlist_add(proj_dir)

    rc, _, err, payload = e2e_sandbox.run_cli([
        "sync", str(e2e_sandbox.dest_dir), "--para", str(assets_dir), "--godot-gd", str(gd_out), "--gd-class-name", "GameAssets",
    ])
    assert rc == 0, err
    assert isinstance(payload, dict) and payload["godot_assets"] == 1 and gd_out.is_file()

    probe = run_godot_probe(
        proj_dir, "probe_reg.gd",
        f"""extends SceneTree
const Reg := preload("res://Forge3DAssets.gd")
func _initialize() -> void:
\tif not Reg.has_asset("char.knight.01"): quit(1); return
\tvar mp: String = Reg.get_mesh_path("char.knight.01")
\tif not mp.begins_with("res://assets/") or not mp.ends_with(".glb"): quit(2); return
\tfor pair in [["{asset_id}_baseColor.png.import", false], ["{asset_id}_normal.png.import", true], ["{asset_id}_orm.png.import", false]]:
\t\tvar cf := ConfigFile.new()
\t\tif cf.load("res://assets/" + pair[0]) != OK: printerr("PNG_INI_FAIL ", pair[0]); quit(3); return
\t\tif int(cf.get_value("params", "compress/mode", -1)) != 2 or (int(cf.get_value("params", "compress/normal_map", 0)) == 1) != bool(pair[1]):
\t\t\tprinterr("PNG_PARAM_FAIL ", pair[0]); quit(4); return
\tvar gf := ConfigFile.new()
\tif gf.load("res://assets/{asset_id}.glb.import") != OK: printerr("GLB_INI_FAIL"); quit(5); return
\tif str(gf.get_value("params", "import_script/path", "")) != "res://addons/forge3d/post_import.gd" or not bool(gf.get_value("params", "meshes/ensure_tangents", false)) or int(gf.get_value("params", "meshes/light_baking", -1)) != 2 or not bool(gf.get_value("params", "skins/use_named_skins", false)) or int(gf.get_value("params", "animation/fps", 0)) != 24:
\t\tprinterr("GLB_PARAM_FAIL"); quit(6); return
\tvar sub: Variant = gf.get_value("params", "_subresources", {{}})
\tif typeof(sub) != TYPE_DICTIONARY or not str(sub).contains("retarget/bone_map"): printerr("SUBRES_FAIL"); quit(7); return
\tvar anims: Dictionary = (sub as Dictionary).get("animations", {{}})
\tfor c in ["idle", "gallop", "wing_flap", "glide"]:
\t\tif int((anims.get(c, {{}}) as Dictionary).get("settings/loop_mode", -1)) != 1: printerr("LOOP1_FAIL ", c); quit(8); return
\tfor c in ["slash_combo", "cast", "bite"]:
\t\tif int((anims.get(c, {{}}) as Dictionary).get("settings/loop_mode", -1)) != 0: printerr("LOOP0_FAIL ", c); quit(9); return
\tprint("REG_OK"); quit(0)
""",
    )
    assert probe.returncode == 0 and "REG_OK" in probe.stdout, probe.stdout + probe.stderr
    assert 'importer="keep"' in (assets_dir / f"{asset_id}_LOD1.glb.import").read_text(encoding="utf-8")
    assert 'importer="keep"' in (assets_dir / f"{asset_id}_colisao.glb.import").read_text(encoding="utf-8")
    assert run_godot_in_project(proj_dir, ["--import"]).returncode == 0


@pytest.mark.godot
@pytest.mark.rapido
def test_tier1_godot_orm_material_and_multisurface_textures(tmp_path: Path) -> None:
    _req_godot()
    proj_dir = stage_temp_godot_project(tmp_path)
    assets_dir, asset_id = proj_dir / "assets", "prop.shield.01"
    write_custom_glb(
        assets_dir / f"{asset_id}.glb",
        surfaces=[
            {"name": "body", "pbr": {"baseColorFactor": [1, 1, 1, 1], "metallicFactor": 0.0, "roughnessFactor": 1.0}},
            {"name": "trim_emissive", "pbr": {"baseColorFactor": [0.2, 0.4, 0.9, 1.0], "metallicFactor": 0.85, "roughnessFactor": 0.25}, "emissiveFactor": [0.0, 0.8, 0.4], "with_texture": True},
        ],
    )
    files = write_orm_texture_set(assets_dir, asset_id)
    write_manifest(assets_dir, asset_id, {"schema": "forge3d/manifest@6", "asset_id": asset_id, "perfil": "godot4", "tipo": "prop_estatico", "rota": "mesh", "files": files})
    assert run_godot_in_project(proj_dir, ["--import"]).returncode == 0

    probe = run_godot_probe(
        proj_dir, "probe_orm.gd",
        gd_probe_header() + f"""func _initialize() -> void:
\tvar src := "res://assets/{asset_id}.glb"; var cena := _load(src); PostImport.aplicar(cena, src)
\tvar mi := cena.find_children("*", "MeshInstance3D", true, false)[0] as MeshInstance3D
\tvar m0 := mi.mesh.surface_get_material(0); var m1 := mi.mesh.surface_get_material(1)
\tif not (m0 is ORMMaterial3D) or not (m1 is ORMMaterial3D):
\t\tprinterr("NOT_ORM m0=", m0.get_class(), " m1=", m1.get_class()); cena.free(); quit(2); return
\tvar o0 := m0 as ORMMaterial3D; var o1 := m1 as ORMMaterial3D
\tif o0.orm_texture == null or not o0.ao_enabled or not is_equal_approx(o0.metallic, 1.0) or not is_equal_approx(o0.roughness, 1.0):
\t\tprinterr("BAD_ORM_FACTORS ", o0.metallic, "/", o0.roughness); cena.free(); quit(3); return
\tif not o0.orm_texture.resource_path.begins_with("res://") or not o0.normal_enabled or o0.normal_texture == null or o0.albedo_texture == null:
\t\tprinterr("NOT_RESOURCELOADER ", o0.orm_texture.resource_path); cena.free(); quit(4); return
\tif not o1.emission_enabled or o1.orm_texture == null or o1.normal_texture == null or not o1.normal_enabled or o1.albedo_texture == null or o1.albedo_texture == o0.albedo_texture or not is_equal_approx(o1.metallic, 1.0) or not is_equal_approx(o1.roughness, 1.0):
\t\tprinterr("SURFACE1_INVALID_ORM m=", o1.metallic, " r=", o1.roughness); cena.free(); quit(5); return
\tprint("ORM_OK"); cena.free(); quit(0)
""",
    )
    assert probe.returncode == 0 and "ORM_OK" in probe.stdout, probe.stdout + probe.stderr


@pytest.mark.godot
@pytest.mark.rapido
def test_tier1_godot_idempotent_post_import_no_source_queue_and_ucx_grouped(tmp_path: Path) -> None:
    _req_godot()
    proj_dir = stage_temp_godot_project(tmp_path)
    assets_dir = proj_dir / "assets"
    assert "_source_queue" not in (RAIZ / "addons" / "forge3d" / "plugin.gd").read_text(encoding="utf-8")
    assert "_source_queue" not in (RAIZ / "addons" / "forge3d" / "scene_post_import_plugin.gd").read_text(encoding="utf-8")

    write_custom_glb(assets_dir / "prop.idem.01.glb")
    write_custom_glb(assets_dir / "prop.idem.01_colisao.glb")
    write_manifest(assets_dir, "prop.idem.01", {"schema": "forge3d/manifest@6", "asset_id": "prop.idem.01", "perfil": "godot4", "tipo": "prop_estatico", "colisao": {"tipo": "convex", "partes": 1}})
    write_custom_glb(assets_dir / "prop.ucx.01.glb", ucx_names=("UCX_PartA", "UCX_PartB", "UCX_PartC"))
    write_manifest(assets_dir, "prop.ucx.01", {"schema": "forge3d/manifest@6", "asset_id": "prop.ucx.01", "perfil": "godot4", "tipo": "prop_estatico"})

    probe = run_godot_probe(
        proj_dir, "probe_idem_ucx.gd",
        gd_probe_header() + """func _initialize() -> void:
\tvar c1 := _load("res://assets/prop.idem.01.glb")
\tPostImport.aplicar(c1, "res://assets/prop.idem.01.glb"); PostImport.aplicar(c1, "res://assets/prop.idem.01.glb")
\tif not c1.has_meta("forge3d_post_imported") or c1.find_children("*", "StaticBody3D", true, false).size() != 1:
\t\tprinterr("IDEM_FAIL"); c1.free(); quit(2); return
\tvar c2 := _load("res://assets/prop.ucx.01.glb"); PostImport.aplicar(c2, "res://assets/prop.ucx.01.glb")
\tvar sb2 := c2.find_children("*", "StaticBody3D", true, false); var cs2 := c2.find_children("*", "CollisionShape3D", true, false)
\tif sb2.size() != 1 or cs2.size() != 3 or not c2.find_children("UCX_*", "MeshInstance3D", true, false).is_empty():
\t\tprinterr("UCX_GROUP_FAIL sb=", sb2.size(), " cs=", cs2.size()); c1.free(); c2.free(); quit(3); return
\tprint("IDEM_UCX_OK"); c1.free(); c2.free(); quit(0)
""",
    )
    assert probe.returncode == 0 and "IDEM_UCX_OK" in probe.stdout, probe.stdout + probe.stderr


@pytest.mark.godot
@pytest.mark.rapido
def test_tier1_godot_bonemap_sockets_and_quadruped_capsule(tmp_path: Path) -> None:
    _req_godot()
    proj_dir = stage_temp_godot_project(tmp_path)
    assets_dir = proj_dir / "assets"
    s20, c20 = math.sin(math.radians(10.0)), math.cos(math.radians(10.0))
    bones = [
        {"name": "Root", "parent": -1, "translation": [0.0, 0.0, 0.0]},
        {"name": "Hips", "parent": 0, "translation": [0.0, 0.9, 0.0]},
        {"name": "Chest", "parent": 1, "translation": [0.0, 0.4, 0.0]},
        {"name": "Hand.L", "parent": 2, "translation": [0.45, 0.1, 0.0], "rotation": [0.0, 0.0, s20, c20]},
        {"name": "Hand.R", "parent": 2, "translation": [-0.45, 0.1, 0.0], "rotation": [0.0, 0.0, -s20, c20]},
    ]
    write_custom_glb(assets_dir / "char.sockets.01.glb", bones=bones, size_xyz=(0.6, 1.8, 0.4))
    write_manifest(assets_dir, "char.sockets.01", {
        "schema": "forge3d/manifest@6", "asset_id": "char.sockets.01", "perfil": "godot4", "tipo": "personagem_humanoide",
        "rig": {"esqueleto": "godot-humanoid@1", "ossos": len(bones)},
        "sockets": [
            {"nome": "Socket_HandR", "osso": "Hand.R", "posicao_local": [0.0, 0.05, 0.0]},
            {"nome": "Socket_HandL", "osso": "Hand.L", "posicao_local": [0.0, 0.05, 0.0]},
            {"nome": "Socket_Back", "osso": "Chest", "posicao_local": [0.0, 0.25, 0.15], "rotacao_quat_wxyz": [1.0, 0.0, 0.0, 0.0]},
        ],
    })
    write_custom_glb(assets_dir / "quad.wolf.01.glb", bones=bones[:3], size_xyz=(0.6, 0.85, 2.1))
    write_manifest(assets_dir, "quad.wolf.01", {
        "schema": "forge3d/manifest@6", "asset_id": "quad.wolf.01", "perfil": "godot4", "tipo": "criatura_quadrupede",
        "rig": {"esqueleto": "quadruped@1", "ossos": 3}, "geometry": {"bbox_m": [0.6, 0.85, 2.1], "triangulos": 12, "materiais": 1},
    })

    probe = run_godot_probe(
        proj_dir, "probe_bonemap.gd",
        gd_probe_header() + """func _initialize() -> void:
\tvar bm1 := PostImport.criar_bone_map_humanoid("godot-humanoid@1")
\tvar bmaa := PostImport.criar_bone_map_humanoid("godot-humanoid-aa@1")
\tif bm1.get_skeleton_bone_name("Root") != "Root" or bmaa.get_skeleton_bone_name("UpperChest") == "":
\t\tprinterr("BONEMAP_FAIL"); quit(1); return
\tvar ch := _load("res://assets/char.sockets.01.glb"); PostImport.aplicar(ch, "res://assets/char.sockets.01.glb")
\tvar ml := ch.find_child("Socket_HandL", true, false) as Marker3D; var mr := ch.find_child("Socket_HandR", true, false) as Marker3D; var mb := ch.find_child("Socket_Back", true, false) as Marker3D
\tif ml == null or mr == null or mb == null or ml.transform.basis.is_equal_approx(mr.transform.basis) or absf(ml.transform.basis.determinant() - 1.0) > 0.02:
\t\tprinterr("SOCKETS_FAIL"); ch.free(); quit(2); return
\tif not mb.position.is_equal_approx(Vector3(0.0, 0.25, 0.15)):
\t\tprinterr("SOCKET_BACK_POS_FAIL ", mb.position); ch.free(); quit(3); return
\tvar mr_pos := mr.position; var sword := MeshInstance3D.new(); sword.name = "Sword"
\tvar cb_ch := PostImport.montar_character_body(ch, {"Hand.R": sword})
\tvar ba := sword.get_parent()
\twhile ba != null and not (ba is BoneAttachment3D): ba = ba.get_parent()
\tif ba == null: printerr("NO_ATTACH_BA"); cb_ch.free(); quit(5); return
\tvar cur: Node3D = sword; var pos_in_ba := Vector3.ZERO
\twhile cur != null and cur != ba: pos_in_ba = cur.transform * pos_in_ba; cur = cur.get_parent() as Node3D
\tif pos_in_ba.distance_to(mr_pos) > 0.005:
\t\tprinterr("MOUNT_SOCKET_OFFSET_FAIL ", pos_in_ba, " vs ", mr_pos); cb_ch.free(); quit(6); return
\tvar q := _load("res://assets/quad.wolf.01.glb"); PostImport.aplicar(q, "res://assets/quad.wolf.01.glb")
\tvar cb_q := PostImport.montar_character_body(q)
\tvar axis_y := ((cb_q.get_node("CollisionShape3D") as CollisionShape3D).transform.basis * Vector3.UP).abs()
\tif axis_y.z < 0.7: printerr("QUAD_CAPSULE_VERTICAL ", axis_y); cb_ch.free(); cb_q.free(); quit(4); return
\tprint("BONEMAP_SOCKETS_QUAD_OK"); cb_ch.free(); cb_q.free(); quit(0)
""",
    )
    assert probe.returncode == 0 and "BONEMAP_SOCKETS_QUAD_OK" in probe.stdout, probe.stdout + probe.stderr


@pytest.mark.godot
@pytest.mark.rapido
def test_tier1_godot_17_clip_loops_gi_mode_and_aabb_lod_distances(e2e_sandbox, write_spec, tmp_path: Path) -> None:
    _req_godot()
    spec_path = write_spec(
        e2e_sandbox.root / "clips17.yaml",
        {
            "schema": "forge3d/spec@6", "projeto": "e2e_clips", "perfil": "godot4", "destino_exportacao": str(e2e_sandbox.dest_dir),
            "lote": [{"id": "crea.dragon.01", "tipo": "criatura_alada", "rota": "blocky", "prompt": "Winged dragon mount", "altura_metros": 2.4, "auto_rig": True, "esqueleto": "winged_mount@1", "clipes": list(ALL_17_CLIPS)}],
        },
    )
    rc, _, err, _ = e2e_sandbox.run_cli(["validate", str(spec_path)])
    assert rc == 0, err

    proj_dir = stage_temp_godot_project(tmp_path)
    assets_dir = proj_dir / "assets"
    bones = [{"name": "Root", "parent": -1, "translation": [0.0, 0.0, 0.0]}, {"name": "Hips", "parent": 0, "translation": [0.0, 1.0, 0.0]}]
    clips = {c: {"bone": "Hips", "duration": 1.0, "rotations": [[0, 0, 0, 1], [0, 0.2, 0, 0.98], [0, 0, 0, 1]]} for c in ALL_17_CLIPS}
    write_custom_glb(assets_dir / "crea.all17.01.glb", bones=bones, anim_clips=clips)
    write_custom_glb(assets_dir / "map.sector.01.glb", size_xyz=(6.0, 3.0, 6.0))
    write_manifest(assets_dir, "map.sector.01", {"schema": "forge3d/manifest@6", "asset_id": "map.sector.01", "perfil": "godot4", "tipo": "mapa_setor"})
    for name, sz in (("prop.small.01", (0.3, 0.3, 0.3)), ("prop.large.01", (6.0, 6.0, 6.0))):
        write_custom_glb(assets_dir / f"{name}.glb", size_xyz=sz)
        write_custom_glb(assets_dir / f"{name}_LOD1.glb", size_xyz=sz)
        write_manifest(assets_dir, name, {"schema": "forge3d/manifest@6", "asset_id": name, "perfil": "godot4", "tipo": "prop_estatico", "lod": [{"nivel": 0, "triangulos": 12, "arquivo": f"{name}.glb"}, {"nivel": 1, "triangulos": 12, "arquivo": f"{name}_LOD1.glb"}]})

    probe = run_godot_probe(
        proj_dir, "probe_17_gi_lod.gd",
        gd_probe_header() + f"""func _initialize() -> void:
\tvar a_sc := _load("res://assets/crea.all17.01.glb")
\tvar ap := a_sc.find_children("*", "AnimationPlayer", true, false)[0] as AnimationPlayer
\tfor n in ap.get_animation_list(): ap.get_animation(n).loop_mode = Animation.LOOP_PINGPONG
\tPostImport.aplicar(a_sc, "res://assets/crea.all17.01.glb")
\tfor c in {json.dumps(list(CLIPS_CYCLIC))}:
\t\tif ap.get_animation(c).loop_mode != Animation.LOOP_LINEAR: printerr("NOT_LINEAR ", c); a_sc.free(); quit(1); return
\tfor c in {json.dumps(list(CLIPS_ONESHOT))}:
\t\tif ap.get_animation(c).loop_mode != Animation.LOOP_NONE: printerr("NOT_NONE ", c); a_sc.free(); quit(2); return
\tvar msc := _load("res://assets/map.sector.01.glb"); PostImport.aplicar(msc, "res://assets/map.sector.01.glb")
\tif (msc.find_children("*", "MeshInstance3D", true, false)[0] as MeshInstance3D).gi_mode != GeometryInstance3D.GI_MODE_STATIC:
\t\tprinterr("NO_GI_STATIC"); a_sc.free(); msc.free(); quit(3); return
\tvar ssc := _load("res://assets/prop.small.01.glb"); PostImport.aplicar(ssc, "res://assets/prop.small.01.glb")
\tvar lsc := _load("res://assets/prop.large.01.glb"); PostImport.aplicar(lsc, "res://assets/prop.large.01.glb")
\tvar sd := (ssc.find_children("*", "MeshInstance3D", true, false)[0] as MeshInstance3D).visibility_range_end
\tvar ld := (lsc.find_children("*", "MeshInstance3D", true, false)[0] as MeshInstance3D).visibility_range_end
\tif sd >= ld: printerr("LOD_NOT_AABB_SCALED ", sd, ">=", ld); a_sc.free(); msc.free(); ssc.free(); lsc.free(); quit(4); return
\tprint("CLIPS17_GI_LOD_OK"); a_sc.free(); msc.free(); ssc.free(); lsc.free(); quit(0)
""",
    )
    assert probe.returncode == 0 and "CLIPS17_GI_LOD_OK" in probe.stdout, probe.stdout + probe.stderr


@pytest.mark.blender
@pytest.mark.godot
@pytest.mark.lento
def test_tier1_godot_blender_mapa_setor_uv2_and_wing_roll(e2e_sandbox, write_spec, tmp_path: Path) -> None:
    _req_blender()
    _req_godot()
    tex_surf = [{"name": "m", "pbr": {"baseColorFactor": [1, 1, 1, 1], "metallicFactor": 0.0, "roughnessFactor": 0.8}, "with_texture": True}]
    sector_src = write_custom_glb(e2e_sandbox.root / "sector_in.glb", size_xyz=(4.0, 1.0, 0.5), subdiv=3, surfaces=tex_surf)
    wyvern_src = write_custom_glb(e2e_sandbox.root / "wyvern_in.glb", size_xyz=(3.2, 1.2, 1.6), subdiv=2, surfaces=tex_surf)
    spec_path = write_spec(
        e2e_sandbox.root / "blender_godot.yaml",
        {
            "schema": "forge3d/spec@6", "projeto": "e2e_bl_gd", "perfil": "godot4", "destino_exportacao": str(e2e_sandbox.dest_dir),
            "lote": [
                {"id": "map.sector.e2e.01", "tipo": "mapa_setor", "rota": "import", "origem": str(sector_src), "altura_metros": 1.0, "material_procedural": "pedra_musgo", "lod": [100, 50]},
                {"id": "crea.wyvern.e2e.01", "tipo": "criatura_alada", "rota": "import", "origem": str(wyvern_src), "altura_metros": 1.4, "auto_rig": True, "esqueleto": "winged_mount@1", "clipes": ["idle", "wing_flap"]},
            ],
        },
    )
    rc, _, err, _ = e2e_sandbox.run_cli(["run", str(spec_path)], timeout=300)
    assert rc == 0, err

    sector_glb, wyvern_glb = e2e_sandbox.dest_dir / "map.sector.e2e.01.glb", e2e_sandbox.dest_dir / "crea.wyvern.e2e.01.glb"
    assert (e2e_sandbox.dest_dir / "map.sector.e2e.01_normal.png").is_file()
    sec_gltf, sec_bin = read_glb_json(sector_glb)
    sec_attrs = sec_gltf["meshes"][0]["primitives"][0]["attributes"]
    assert "TANGENT" in sec_attrs
    assert "TEXCOORD_1" in sec_attrs and measure_uv_edge_isotropy(sec_gltf, sec_bin, "TEXCOORD_1") <= 1.03

    proj_dir = stage_temp_godot_project(tmp_path)
    probe = run_godot_probe(
        proj_dir, "probe_bl_gd.gd",
        gd_probe_header() + f"""func _initialize() -> void:
\tvar ms := _load({str(sector_glb)!r}); PostImport.aplicar(ms, {str(sector_glb)!r})
\tif (ms.find_children("*", "MeshInstance3D", true, false)[0] as MeshInstance3D).gi_mode != GeometryInstance3D.GI_MODE_STATIC:
\t\tprinterr("SECTOR_NO_GI_STATIC"); ms.free(); quit(1); return
\tms.free()
\tvar w := _load({str(wyvern_glb)!r}); PostImport.aplicar(w, {str(wyvern_glb)!r})
\troot.add_child(w); await process_frame
\tvar skel := w.find_children("*", "Skeleton3D", true, false)[0] as Skeleton3D
\tvar ap := w.find_children("*", "AnimationPlayer", true, false)[0] as AnimationPlayer
\tvar tl := skel.find_bone("WingTip.L"); var tr := skel.find_bone("WingTip.R")
\tif tl < 0 or tr < 0 or not ap.has_animation("wing_flap"): root.remove_child(w); w.queue_free(); quit(2); return
\tap.play("wing_flap"); var anim := ap.get_animation("wing_flap"); var min_l := INF; var max_l := -INF; var max_asym := 0.0
\tfor f in range(9):
\t\tap.seek(anim.length * float(f) / 8.0, true); await process_frame; skel.force_update_all_bone_transforms()
\t\tvar yl := skel.get_bone_global_pose(tl).origin.y; var yr := skel.get_bone_global_pose(tr).origin.y
\t\tmin_l = minf(min_l, yl); max_l = maxf(max_l, yl); max_asym = maxf(max_asym, absf(yl - yr))
\troot.remove_child(w); w.queue_free()
\tif (max_l - min_l) <= 0.05 or max_asym > 0.08:
\t\tprinterr("WING_FLAP_ASYM swing=", max_l - min_l, " asym=", max_asym); quit(3); return
\tprint("BLENDER_GODOT_OK"); quit(0)
""",
    )
    assert probe.returncode == 0 and "BLENDER_GODOT_OK" in probe.stdout, probe.stdout + probe.stderr


# ---------------------------------------------------------------------------
# Tier 2: Error paths, QA failures, boundaries & LOD texture dedup
# ---------------------------------------------------------------------------


@pytest.mark.rapido
def test_tier2_godot_sync_errors_and_limpar_preserves_sidecars(e2e_sandbox, tmp_path: Path) -> None:
    _, man_path = write_published_orm_asset(e2e_sandbox.dest_dir, "prop.sync.01")
    proj_dir = stage_temp_godot_project(tmp_path)
    assets_dir, gd_out = proj_dir / "assets", proj_dir / "Forge3DAssets.gd"
    e2e_sandbox.allowlist_add(proj_dir)

    rc_cls, _, _, err_cls = e2e_sandbox.run_cli(["sync", str(e2e_sandbox.dest_dir), "--para", str(assets_dir), "--godot-gd", str(gd_out), "--gd-class-name", "123Bad"])
    assert rc_cls == 2 and isinstance(err_cls, dict) and err_cls["erro"]["codigo"] == "FORGE-E-SPEC"

    rc_ov, _, _, err_ov = e2e_sandbox.run_cli(["sync", str(e2e_sandbox.dest_dir), "--para", str(e2e_sandbox.dest_dir / "sub"), "--godot-gd", str(gd_out)])
    assert rc_ov == 2 and isinstance(err_ov, dict) and err_ov["erro"]["codigo"] == "FORGE-E-DESTINO"

    orig_man = man_path.read_text(encoding="utf-8")
    man_path.write_text("{corrupt", encoding="utf-8")
    rc_cor, _, _, err_cor = e2e_sandbox.run_cli(["sync", str(e2e_sandbox.dest_dir), "--para", str(assets_dir), "--godot-gd", str(gd_out)])
    assert rc_cor == 3 and isinstance(err_cor, dict) and err_cor["erro"]["codigo"] == "FORGE-E-MANIFEST"
    man_path.write_text(orig_man, encoding="utf-8")

    assets_dir.mkdir(parents=True, exist_ok=True)
    (assets_dir / "keep.uid").write_text("uid://abc", encoding="utf-8")
    (assets_dir / ".godot" / "imported").mkdir(parents=True, exist_ok=True)
    (assets_dir / ".godot" / "imported" / "cache.bin").write_bytes(b"\x01\x02")
    (assets_dir / "stale.txt").write_text("orphan", encoding="utf-8")

    rc_ok, _, err_ok, _ = e2e_sandbox.run_cli(["sync", str(e2e_sandbox.dest_dir), "--para", str(assets_dir), "--godot-gd", str(gd_out), "--limpar"])
    assert rc_ok == 0, err_ok
    assert not (assets_dir / "stale.txt").exists()
    assert (assets_dir / "keep.uid").is_file() and (assets_dir / ".godot" / "imported" / "cache.bin").is_file()
    assert (assets_dir / "prop.sync.01.glb.import").is_file()


@pytest.mark.godot
@pytest.mark.rapido
def test_tier2_godot_visual_qa_catches_invalid_orm_and_bad_rig(tmp_path: Path) -> None:
    _req_godot()
    good_dir = tmp_path / "good"
    good_glb = good_dir / "prop.good.01.glb"
    write_custom_glb(good_glb, surfaces=[{"name": "s0", "pbr": {"baseColorFactor": [1, 1, 1, 1], "metallicFactor": 1.0, "roughnessFactor": 1.0}}])
    write_orm_texture_set(good_dir, "prop.good.01")
    write_manifest(good_dir, "prop.good.01", {"schema": "forge3d/manifest@6", "asset_id": "prop.good.01", "perfil": "godot4", "tipo": "prop_estatico"})
    ok_proc = run_godot_tool("tools/godot_visual_qa.gd", [str(good_glb)])
    assert ok_proc.returncode == 0 and "GODOT_VISUAL_QA_OK" in ok_proc.stdout, ok_proc.stdout + ok_proc.stderr

    bad_pbr = tmp_path / "bad_pbr.glb"
    write_custom_glb(bad_pbr, surfaces=[{"name": "s0", "pbr": {"baseColorFactor": [1, 1, 1, 1], "metallicFactor": 1.0, "roughnessFactor": 1.0}, "emissiveFactor": [0.1, 0.1, 0.1]}])
    assert run_godot_tool("tools/godot_visual_qa.gd", [str(bad_pbr)]).returncode == 1

    bad_rig = tmp_path / "bad_rig.glb"
    write_custom_glb(bad_rig, bones=[{"name": "Root", "parent": -1, "translation": [0, 0, 0]}, {"name": "Hips", "parent": 0, "translation": [0, 1.5, 0]}, {"name": "Head", "parent": 1, "translation": [0, -0.5, 0]}])
    assert run_godot_tool("tools/godot_visual_qa.gd", [str(bad_rig)]).returncode == 1
    qa_src = (RAIZ / "tools" / "godot_visual_qa.gd").read_text(encoding="utf-8")
    assert ("ORMMaterial3D" in qa_src or "BaseMaterial3D" in qa_src) and "orm_texture" in qa_src
    assert "is StandardMaterial3D" not in qa_src


@pytest.mark.godot
@pytest.mark.rapido
def test_tier2_godot_draw_calls_bench_invokes_post_import(tmp_path: Path) -> None:
    _req_godot()
    bad_proc = run_godot_tool("tools/godot_draw_calls_bench.gd", ["--output", str(tmp_path / "err.json")])
    assert bad_proc.returncode == 1 and "GODOT_DRAW_CALLS_FAIL" in bad_proc.stderr

    prop_glb = tmp_path / "prop.bench.01.glb"
    write_custom_glb(prop_glb, ucx_names=("UCX_Box",))
    write_custom_glb(tmp_path / "prop.bench.01_LOD1.glb")
    files = write_orm_texture_set(tmp_path, "prop.bench.01")
    write_manifest(tmp_path, "prop.bench.01", {"schema": "forge3d/manifest@6", "asset_id": "prop.bench.01", "perfil": "godot4", "tipo": "prop_estatico", "lod": [{"nivel": 0, "triangulos": 12, "arquivo": prop_glb.name}, {"nivel": 1, "triangulos": 12, "arquivo": "prop.bench.01_LOD1.glb"}], "files": files})
    in_json, out_json = tmp_path / "bench_in.json", tmp_path / "bench_out.json"
    in_json.write_text(json.dumps({"mode": "multimesh", "frames_baseline": 2, "frames_measure": 3, "items": [{"id": "prop.bench.01", "glb": str(prop_glb), "qtd": 4}]}), encoding="utf-8")
    ok_proc = run_godot_tool("tools/godot_draw_calls_bench.gd", ["--input", str(in_json), "--output", str(out_json)])
    assert ok_proc.returncode == 0 and "GODOT_DRAW_CALLS_OK" in ok_proc.stdout and "ERROR" not in ok_proc.stderr, ok_proc.stdout + ok_proc.stderr
    report = json.loads(out_json.read_text(encoding="utf-8"))
    assert report["ok"] is True and report["items"][0]["placement_efetivo"] == "multimesh"
    assert report["items"][0]["tris_unit"] >= 12 and report["items"][0]["mesh_nodes_unit"] >= 1
    assert re.search(r"\bPostImport\.aplicar\s*\(", (RAIZ / "tools" / "godot_draw_calls_bench.gd").read_text(encoding="utf-8"))


@pytest.mark.godot
@pytest.mark.rapido
def test_tier2_godot_rig_axes_and_post_import_check_failures(tmp_path: Path) -> None:
    _req_godot()
    bones = [
        {"name": "Hips", "parent": -1, "translation": [0.0, 0.9, 0.0]},
        {"name": "Shoulder.L", "parent": 0, "translation": [0.1, 0.5, 0.0]},
        {"name": "UpperArm.L", "parent": 1, "translation": [0.2, 0.0, 0.0]},
        {"name": "Shoulder.R", "parent": 0, "translation": [-0.1, 0.5, 0.0]},
        {"name": "UpperArm.R", "parent": 3, "translation": [-0.2, 0.0, 0.0]},
    ]
    frozen = tmp_path / "frozen.glb"
    write_custom_glb(frozen, bones=bones, anim_clips={"jump": {"bone": "UpperArm.L", "duration": 1.0, "translations": [[0.2, 0, 0]] * 3}})
    no_jump = tmp_path / "no_jump.glb"
    write_custom_glb(no_jump, bones=bones, anim_clips={"idle": {"bone": "Hips", "duration": 1.0}})

    assert run_godot_tool("tools/godot_rig_axes_check.gd", [str(no_jump)]).returncode == 1
    assert run_godot_tool("tools/godot_rig_axes_check.gd", [str(frozen)]).returncode == 1
    assert run_godot_tool("tools/godot_rig_axes_check.gd", [str(tmp_path / "absent.glb")]).returncode == 1
    assert run_godot_tool("tools/godot_post_import_check.gd", [str(tmp_path / "absent.glb")]).returncode == 1

    bad_loop = tmp_path / "bad_loop.glb"
    write_custom_glb(bad_loop, bones=bones[:1], anim_clips={"idle": {"bone": "Hips", "duration": 1.0}, "idle-loop": {"bone": "Hips", "duration": 1.0}})
    assert run_godot_tool("tools/godot_post_import_check.gd", [str(bad_loop)]).returncode == 1

    rigged_ucx = tmp_path / "rigged_ucx.glb"
    write_custom_glb(rigged_ucx, bones=bones[:1], ucx_names=("UCX_Illegal",))
    write_manifest(tmp_path, "rigged_ucx", {"schema": "forge3d/manifest@6", "asset_id": "rigged_ucx", "perfil": "godot4", "tipo": "personagem_humanoide", "rig": {"esqueleto": "godot-humanoid@1", "ossos": 1}})
    assert run_godot_tool("tools/godot_post_import_check.gd", [str(rigged_ucx)]).returncode == 1


@pytest.mark.godot
@pytest.mark.rapido
def test_tier2_godot_aux_files_missing_manifest_and_dielectric_fallback(tmp_path: Path) -> None:
    _req_godot()
    proj_dir = stage_temp_godot_project(tmp_path)
    assets_dir = proj_dir / "assets"
    write_custom_glb(assets_dir / "prop.aux.01_LOD1.glb")
    write_custom_glb(assets_dir / "prop.aux.01_colisao.glb")
    write_custom_glb(assets_dir / "prop.nomanifest.01.glb", surfaces=[{"name": "diel", "pbr": {"baseColorFactor": [1, 1, 1, 1], "metallicFactor": 1.0, "roughnessFactor": 1.0}}])
    (assets_dir / "prop.nomanifest.01.manifest.json").write_text("{broken json", encoding="utf-8")

    probe = run_godot_probe(
        proj_dir, "probe_aux.gd",
        gd_probe_header() + """func _initialize() -> void:
\tvar lod1 := _load("res://assets/prop.aux.01_LOD1.glb"); PostImport.aplicar(lod1, "res://assets/prop.aux.01_LOD1.glb")
\tvar col := _load("res://assets/prop.aux.01_colisao.glb"); PostImport.aplicar(col, "res://assets/prop.aux.01_colisao.glb")
\tif lod1.has_meta("forge3d_post_imported") or col.has_meta("forge3d_post_imported"):
\t\tprinterr("AUX_NOT_SKIPPED"); lod1.free(); col.free(); quit(1); return
\tvar nm := _load("res://assets/prop.nomanifest.01.glb"); PostImport.aplicar(nm, "res://assets/prop.nomanifest.01.glb")
\tvar mat := (nm.find_children("*", "MeshInstance3D", true, false)[0] as MeshInstance3D).mesh.surface_get_material(0) as StandardMaterial3D
\tif not is_equal_approx(mat.metallic, 0.0) or not is_equal_approx(mat.roughness, 0.65):
\t\tprinterr("DIELECTRIC_FAIL"); lod1.free(); col.free(); nm.free(); quit(2); return
\tprint("AUX_DIEL_OK"); lod1.free(); col.free(); nm.free(); quit(0)
""",
    )
    assert probe.returncode == 0 and "AUX_DIEL_OK" in probe.stdout, probe.stdout + probe.stderr


@pytest.mark.blender
@pytest.mark.rapido
def test_tier2_godot_lod_no_duplicate_embedded_textures(e2e_sandbox, write_spec) -> None:
    _req_blender()
    src_glb = write_custom_glb(
        e2e_sandbox.root / "textured_in.glb", size_xyz=(1.0, 1.0, 1.0), subdiv=3,
        surfaces=[{"name": "tex_mat", "pbr": {"baseColorFactor": [1, 1, 1, 1], "metallicFactor": 0.0, "roughnessFactor": 0.8}, "with_texture": True}],
    )
    spec_path = write_spec(e2e_sandbox.root / "lod_dedup.yaml", {
        "schema": "forge3d/spec@6", "projeto": "e2e_lod_dedup", "perfil": "godot4", "destino_exportacao": str(e2e_sandbox.dest_dir),
        "lote": [{"id": "prop.lodtex.01", "tipo": "prop_estatico", "rota": "import", "origem": str(src_glb), "altura_metros": 1.0, "lod": [100, 50]}],
    })
    rc, _, err, _ = e2e_sandbox.run_cli(["run", str(spec_path)], timeout=300)
    assert rc == 0, err

    lod0_glb, lod1_glb = e2e_sandbox.dest_dir / "prop.lodtex.01.glb", e2e_sandbox.dest_dir / "prop.lodtex.01_LOD1.glb"
    assert lod0_glb.is_file() and lod1_glb.is_file()
    lod1_gltf, _ = read_glb_json(lod1_glb)
    assert len(lod1_gltf.get("images", [])) == 0, f"_LOD1.glb duplicated embedded images: {lod1_gltf.get('images')}"
    assert lod1_glb.stat().st_size < lod0_glb.stat().st_size
