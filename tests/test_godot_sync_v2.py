"""Testes V2 para Godot 4 Zero-Click Post-Import, `sync.py` `.glb.import`, `post_import.gd` e `godot_visual_qa.gd`."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from forge3d import config, sync

RAIZ = Path(__file__).resolve().parents[1]
GODOT_PROJ = RAIZ / "tools" / "godot_project"
VISUAL_QA_GD = RAIZ / "tools" / "godot_visual_qa.gd"


@pytest.fixture(autouse=True)
def _isolar_allowlist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORGE3D_HOME", str(tmp_path / "forge_home"))
    monkeypatch.setenv("FORGE3D_CONFIG", str(tmp_path / "forge_cfg"))
    config.adicionar(tmp_path)


def _godot_bin() -> str:
    env_g = os.environ.get("FORGE3D_GODOT")
    if env_g and Path(env_g).is_file():
        return env_g
    bin_g = shutil.which("godot") or shutil.which("godot4")
    if bin_g:
        return bin_g
    padrao = Path.home() / "tools" / "godot" / "Godot_v4.3-stable_linux.x86_64"
    if padrao.is_file():
        return str(padrao)
    pytest.skip("Godot 4 nao disponivel neste ambiente")


def test_plugin_godot_registra_scene_post_import_plugin() -> None:
    plugin_gd = (RAIZ / "addons" / "forge3d" / "plugin.gd").read_text(encoding="utf-8")
    scene_plugin_gd = (RAIZ / "addons" / "forge3d" / "scene_post_import_plugin.gd").read_text(encoding="utf-8")

    assert "extends EditorScenePostImportPlugin" in scene_plugin_gd
    assert "PostImport.aplicar(" in scene_plugin_gd
    assert "add_scene_post_import_plugin(" in plugin_gd
    assert "remove_scene_post_import_plugin(" in plugin_gd


def test_sync_cria_e_atualiza_sidecar_glb_import_preservando_params(tmp_path: Path) -> None:
    from tests.test_sync import _publicar_valido

    origem = _publicar_valido(tmp_path, asset_id="personagem.heroi.01")

    destino_jogo = tmp_path / "jogo_godot"
    destino_assets = destino_jogo / "assets" / "chars"
    destino_assets.mkdir(parents=True)
    (destino_jogo / "project.godot").write_text("[application]\nconfig/name=\"Teste\"\n", encoding="utf-8")

    # 1. Sync com --godot-gd cria .glb.import automaticamente
    rel1 = sync.executar(origem, destino_assets, godot_gd=destino_jogo / "forge3d_assets.gd")
    assert rel1["ok"] is True
    sidecar = destino_assets / "personagem.heroi.01.glb.import"
    assert sidecar.is_file()
    texto1 = sidecar.read_text(encoding="utf-8")
    assert 'import_script/path="res://addons/forge3d/post_import.gd"' in texto1

    # 2. Se o usuario tinha parametros customizados e import_script/path="", preserva parametros e injeta post_import.gd
    sidecar.write_text(
        '[remap]\n\nimporter="scene"\n\n[params]\n\nmeshes/create_shadow_meshes=false\nimport_script/path=""\n',
        encoding="utf-8",
    )
    sync._atualizar_import_sidecar_glb(destino_assets / "personagem.heroi.01.glb")
    texto2 = sidecar.read_text(encoding="utf-8")
    assert "meshes/create_shadow_meshes=false" in texto2
    assert 'import_script/path="res://addons/forge3d/post_import.gd"' in texto2
    assert 'import_script/path=""' not in texto2


def test_post_import_dielectric_sockets_det_positivo_e_montaria_headless(tmp_path: Path) -> None:
    godot = _godot_bin()
    script_gd = tmp_path / "run_post_import_v2_test.gd"
    script_gd.write_text(
        """extends SceneTree

const PostImport := preload("__POST_IMPORT__")

func _fail(msg: String) -> void:
	printerr("FAIL: " + msg)
	quit(1)

func _initialize() -> void:
	# 1. Testa fallback dieletrico PBR (sem textura ORM -> metallic=0.0, roughness=0.65)
	var cena := Node3D.new()
	cena.name = "Heroi"
	var mi := MeshInstance3D.new()
	var box := BoxMesh.new()
	var mat := StandardMaterial3D.new()
	# Simula default do glTF sem textura ORM (roughness=1.0, metallic=0.0 ou 1.0/1.0)
	mat.metallic = 1.0
	mat.roughness = 1.0
	box.material = mat
	mi.mesh = box
	cena.add_child(mi)

	var skel := Skeleton3D.new()
	skel.name = "GeneralSkeleton"
	for bname in ["Hips", "Chest", "Head", "Hand.R", "Hand.L", "MountSeat"]:
		skel.add_bone(bname)
	cena.add_child(skel)

	var ap := AnimationPlayer.new()
	var lib := AnimationLibrary.new()
	for cname in ["idle", "gallop", "wing_flap", "glide", "ride_idle", "ride_fly"]:
		var anim := Animation.new()
		anim.length = 1.0
		lib.add_animation(cname, anim)
	ap.add_animation_library("", lib)
	cena.add_child(ap)

	var manifesto := {
		"schema": "forge3d/manifest@5",
		"asset_id": "montaria.grifo.01",
		"tipo": "criatura_alada",
		"rig": {"esqueleto": "winged_mount@1"},
		"sockets": {
			"Socket_Mount": {
				"osso": "MountSeat",
				"posicao_m": [0.0, 0.25, 0.0],
				"rotacao_quat_wxyz": [1.0, 0.0, 0.0, 0.0]
			}
		}
	}
	cena.set_meta("forge3d_manifest", manifesto)
	PostImport._configurar_materiais(cena, "", manifesto, {})
	PostImport._aplicar_bone_map(cena, manifesto)
	PostImport._configurar_animacoes(cena)
	PostImport._configurar_sockets(cena, manifesto)

	var smat := mi.mesh.surface_get_material(0) as StandardMaterial3D
	if not is_equal_approx(smat.metallic, 0.0) or not is_equal_approx(smat.roughness, 0.65):
		_fail("fallback dieletrico incorreto: metallic=%f roughness=%f" % [smat.metallic, smat.roughness])
		return

	# Verifica LOOP_LINEAR em clipes ciclicos de criatura/montaria
	for cname in ["idle", "gallop", "wing_flap", "glide", "ride_idle", "ride_fly"]:
		if ap.get_animation(cname).loop_mode != Animation.LOOP_LINEAR:
			_fail("clipe %s sem LOOP_LINEAR" % cname)
			return

	# Verifica sockets ortonormais (det = +1) e espelhamento de Socket_HandL != Socket_HandR
	var s_r := cena.find_child("Socket_HandR", true, false) as Marker3D
	var s_l := cena.find_child("Socket_HandL", true, false) as Marker3D
	var s_b := cena.find_child("Socket_Back", true, false) as Marker3D
	var s_m := cena.find_child("Socket_Mount", true, false) as Marker3D
	if s_r == null or s_l == null or s_b == null or s_m == null:
		_fail("sockets obrigatorios ausentes")
		return
	for s in [s_r, s_l, s_b, s_m]:
		var det := (s as Marker3D).transform.basis.determinant()
		if absf(det - 1.0) > 0.01:
			_fail("socket %s com det != +1: %f" % [s.name, det])
			return
	if s_l.transform.basis.is_equal_approx(s_r.transform.basis):
		_fail("Socket_HandL reutilizou a mesma basis de Socket_HandR!")
		return

	# Verifica helper montar_cavaleiro_em_montaria (alinhado com -Z, yaw=0 e ride_idle tocando)
	var cavaleiro := Node3D.new()
	cavaleiro.name = "Cavaleiro"
	var ap_cav := AnimationPlayer.new()
	var lib_cav := AnimationLibrary.new()
	var anim_ride := Animation.new()
	anim_ride.length = 1.2
	lib_cav.add_animation("ride_idle", anim_ride)
	ap_cav.add_animation_library("", lib_cav)
	cavaleiro.add_child(ap_cav)

	PostImport.montar_cavaleiro_em_montaria(cavaleiro, cena)
	if cavaleiro.get_parent() != s_m:
		_fail("cavaleiro nao foi anexado em Socket_Mount")
		return
	if not cavaleiro.transform.basis.is_equal_approx(Basis.IDENTITY):
		_fail("cavaleiro nao esta alinhado com -Z (yaw=0)")
		return
	if ap_cav.get_animation("ride_idle").loop_mode != Animation.LOOP_LINEAR:
		_fail("ride_idle do cavaleiro sem LOOP_LINEAR")
		return

	cena.free()
	print("POST_IMPORT_V2_OK")
	quit(0)
""".replace("__POST_IMPORT__", str(RAIZ / "addons" / "forge3d" / "post_import.gd")),
        encoding="utf-8",
    )
    proc = subprocess.run(
        [godot, "--headless", "--path", str(GODOT_PROJ), "--script", str(script_gd)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr
    assert "POST_IMPORT_V2_OK" in proc.stdout


def test_godot_visual_qa_aprova_upright_e_reprova_facetada(tmp_path: Path) -> None:
    godot = _godot_bin()
    glb_ok = RAIZ / "tests" / "fixtures" / "personagem_upright.glb"
    proc_ok = subprocess.run(
        [
            godot,
            "--headless",
            "--path",
            str(GODOT_PROJ),
            "--script",
            str(VISUAL_QA_GD),
            "--",
            str(glb_ok),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert proc_ok.returncode == 0, proc_ok.stdout + "\n" + proc_ok.stderr
    assert "GODOT_VISUAL_QA_OK" in proc_ok.stdout

    # Cria GLB organico 100%% facetado com manifesto personagem_humanoide e confere reprovacao
    from tests.test_qc_v3 import _construir_esfera_glb, _empacotar_glb

    gltf_flat, bin_flat = _construir_esfera_glb(flat_shaded=True)
    glb_bad = tmp_path / "organico_facetado.glb"
    glb_bad.write_bytes(_empacotar_glb(gltf_flat, bin_flat))
    (tmp_path / "organico_facetado.manifest.json").write_text(
        json.dumps(
            {
                "schema": "forge3d/manifest@5",
                "asset_id": "organico_facetado",
                "tipo": "personagem_humanoide",
                "rota": "mesh",
            }
        ),
        encoding="utf-8",
    )
    proc_bad = subprocess.run(
        [
            godot,
            "--headless",
            "--path",
            str(GODOT_PROJ),
            "--script",
            str(VISUAL_QA_GD),
            "--",
            str(glb_bad),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert proc_bad.returncode != 0
    assert "GODOT_VISUAL_QA_FAIL" in proc_bad.stdout
    assert "malha_organica_facetada" in proc_bad.stdout


def test_godot_anim_check_fallback_nome_vazio_e_nao_ciclicos(tmp_path: Path) -> None:
    godot = _godot_bin()
    anim_check_gd = RAIZ / "tools" / "godot_anim_check.gd"

    # 1. Probe direto de _extrair_manifest_loop_overrides e _loop_esperado
    probe = tmp_path / "probe_anim_check.gd"
    probe.write_text(
        f"""extends SceneTree
const AnimCheck := preload({str(anim_check_gd)!r})
func _initialize() -> void:
\tvar ov := AnimCheck._extrair_manifest_loop_overrides({{"animacoes": [{{"nome": "", "name": "idle", "loop": false}}]}})
\tif ov.get("idle", -1) != Animation.LOOP_NONE:
\t\tprinterr("FAIL ov=", ov)
\t\tquit(1)
\t\treturn
\tfor c in ["slash_combo", "cast", "bite"]:
\t\tif AnimCheck._loop_esperado(c, c, {{}}, {{}}) != Animation.LOOP_NONE:
\t\t\tprinterr("FAIL nao_ciclico=", c)
\t\t\tquit(1)
\t\t\treturn
\tif AnimCheck._loop_esperado("slash_combo", "slash_combo", {{"slash_combo": Animation.LOOP_LINEAR}}, {{}}) != Animation.LOOP_LINEAR:
\t\tprinterr("FAIL override")
\t\tquit(1)
\t\treturn
\tif AnimCheck._loop_esperado("custom_dance", "custom_dance", {{}}, {{}}) != -1:
\t\tprinterr("FAIL custom")
\t\tquit(1)
\t\treturn
\tprint("ANIM_CHECK_PROBE_OK")
\tquit(0)
""",
        encoding="utf-8",
    )
    proc_p = subprocess.run([godot, "--headless", "--path", str(GODOT_PROJ), "--script", str(probe)], capture_output=True, text=True, timeout=30, check=False)
    assert proc_p.returncode == 0 and "ANIM_CHECK_PROBE_OK" in proc_p.stdout, proc_p.stdout + proc_p.stderr

    # 2. Execucao real de godot_anim_check.gd com {"nome": "", "name": "idle", "loop": false} + clipes nao-ciclicos
    from tests.test_godot_addon_anim_loop import _criar_glb_clips

    glb = tmp_path / "hero_anim_chk.glb"
    _criar_glb_clips(glb, ("idle", "slash_combo", "cast", "bite"))
    (tmp_path / "hero_anim_chk.manifest.json").write_text(
        json.dumps({"animacoes": [{"nome": "", "name": "idle", "loop": False}]}),
        encoding="utf-8",
    )
    proc_cli = subprocess.run(
        [godot, "--headless", "--path", str(GODOT_PROJ), "--script", str(anim_check_gd), "--", str(glb)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert proc_cli.returncode == 0, proc_cli.stdout + proc_cli.stderr
    assert "GODOT_ANIM_OK" in proc_cli.stdout
    for c in ("slash_combo", "cast", "bite"):
        assert f"{c} " in proc_cli.stdout and "loop=0" in proc_cli.stdout


def test_godot_visual_qa_reprova_manifesto_malformado(tmp_path: Path) -> None:
    godot = _godot_bin()
    glb = tmp_path / "bad_manifest.glb"
    shutil.copyfile(RAIZ / "tests" / "fixtures" / "personagem_upright.glb", glb)

    for payload in ("{bad json", "[]"):
        (tmp_path / "bad_manifest.manifest.json").write_text(payload, encoding="utf-8")
        proc = subprocess.run(
            [godot, "--headless", "--path", str(GODOT_PROJ), "--script", str(VISUAL_QA_GD), "--", str(glb)],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert proc.returncode != 0
        assert "GODOT_VISUAL_QA_FAIL" in proc.stdout
        assert "manifesto invalido" in proc.stdout
