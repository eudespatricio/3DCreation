"""Testes round-trip headless Godot 4 para override explicito de loop em animacoes."""

from __future__ import annotations

import json
import re
import shutil
import struct
import subprocess
from pathlib import Path

import pytest

from forge3d import config, profiles, publish, sync, sync_godot_sidecars
from forge3d.canonical import sha256_arquivo
from tests.test_godot_addon import (
    POST_IMPORT_GD,
    RAIZ,
    _criar_glb_rigged,
    _escrever_glb,
    _exigir_godot,
    _rodar_godot,
)
from tests.test_seguranca_e_qc import _glb_bytes

VISUAL_QA_GD = RAIZ / "tools" / "godot_visual_qa.gd"


@pytest.fixture(autouse=True)
def _isolar_forge3d(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORGE3D_HOME", str(tmp_path / "forge_home"))
    monkeypatch.setenv("FORGE3D_CONFIG", str(tmp_path / "forge_cfg"))
    config.adicionar(tmp_path)


def _criar_glb_clips(destino: Path, clips: tuple[str, ...]) -> None:
    _criar_glb_rigged(destino, "Hero", com_animacoes=True)
    raw = destino.read_bytes()
    jl = int.from_bytes(raw[12:16], "little")
    bl = int.from_bytes(raw[20 + jl : 24 + jl], "little")
    gltf = json.loads(raw[20 : 20 + jl])
    tmpl = gltf["animations"][0]
    gltf["animations"] = [{**tmpl, "name": nome} for nome in clips]
    _escrever_glb(destino, gltf, raw[28 + jl : 28 + jl + bl])


def _glb_humanoid_qc_valido(no_nome: str, clipes: tuple[str, ...]) -> bytes:
    ossos = list(profiles.carregar("godot4")["rig"]["mapas"]["godot-humanoid@1"])
    base = _glb_bytes(ossos=ossos, no_nome=no_nome)
    jlen = struct.unpack_from("<I", base, 12)[0]
    blen = struct.unpack_from("<I", base, 20 + jlen)[0]
    gltf = json.loads(base[20 : 20 + jlen].decode("utf-8"))
    buf = bytearray(base[28 + jlen : 28 + jlen + blen])
    t_off = len(buf)
    buf.extend(struct.pack("<3f", 0.0, 0.5, 1.0))
    r_off = len(buf)
    buf.extend(
        struct.pack("<4f", 0.0, 0.0, 0.0, 1.0)
        + struct.pack("<4f", 0.0, 0.25, 0.0, 0.9682)
        + struct.pack("<4f", 0.0, 0.0, 0.0, 1.0)
    )
    gltf["bufferViews"].extend(
        [
            {"buffer": 0, "byteOffset": t_off, "byteLength": 12},
            {"buffer": 0, "byteOffset": r_off, "byteLength": 48},
        ]
    )
    acc_t, acc_r = len(gltf["accessors"]), len(gltf["accessors"]) + 1
    gltf["accessors"].extend(
        [
            {
                "bufferView": len(gltf["bufferViews"]) - 2,
                "componentType": 5126,
                "count": 3,
                "type": "SCALAR",
                "min": [0.0],
                "max": [1.0],
            },
            {
                "bufferView": len(gltf["bufferViews"]) - 1,
                "componentType": 5126,
                "count": 3,
                "type": "VEC4",
            },
        ]
    )
    hips_idx = next(i for i, n in enumerate(gltf["nodes"]) if n.get("name") == "Hips")
    spine_idx = next(i for i, n in enumerate(gltf["nodes"]) if n.get("name") == "Spine")
    gltf["buffers"][0]["byteLength"] = len(buf)
    gltf["animations"] = [
        {
            "name": c,
            "samplers": [{"input": acc_t, "output": acc_r, "interpolation": "LINEAR"}],
            "channels": [
                {"sampler": 0, "target": {"node": hips_idx, "path": "rotation"}},
                {"sampler": 0, "target": {"node": spine_idx, "path": "rotation"}},
            ],
        }
        for c in clipes
    ]
    jb = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    jb += b" " * ((-len(jb)) % 4)
    total = 12 + 8 + len(jb) + 8 + len(buf)
    return (
        struct.pack("<3I", 0x46546C67, 2, total)
        + struct.pack("<2I", len(jb), 0x4E4F534A)
        + jb
        + struct.pack("<2I", len(buf), 0x004E4942)
        + bytes(buf)
    )


def _preparar_proj_godot(proj: Path, *, ativar_plugin: bool = False) -> None:
    (proj / "assets").mkdir(parents=True, exist_ok=True)
    cfg = (
        'config_version=5\n\n[application]\n\nconfig/name="probe_anim_loop"\n'
        'config/features=PackedStringArray("4.3")\n'
    )
    if ativar_plugin:
        cfg += '\n[editor_plugins]\n\nenabled=PackedStringArray("res://addons/forge3d/plugin.cfg")\n'
    (proj / "project.godot").write_text(cfg, encoding="utf-8")
    shutil.copytree(RAIZ / "addons" / "forge3d", proj / "addons" / "forge3d")


def _inspecionar_loops_res(godot: str, proj: Path, res_path: str, clips: list[str]) -> dict[str, int]:
    probe_gd = proj / "_probe_loops.gd"
    clips_arr = json.dumps(clips)
    probe_gd.write_text(
        f"""extends SceneTree
func _initialize() -> void:
\tvar packed := ResourceLoader.load({res_path!r}) as PackedScene
\tif packed == null:
\t\tpush_error("packed_null")
\t\tquit(1)
\t\treturn
\tvar root := packed.instantiate()
\tvar players := root.find_children("*", "AnimationPlayer", true, false)
\tif players.size() != 1:
\t\tpush_error("players=%d" % players.size())
\t\troot.free()
\t\tquit(1)
\t\treturn
\tvar ap := players[0] as AnimationPlayer
\tvar out := {{}}
\tfor cname in {clips_arr}:
\t\tvar a := ap.get_animation(cname)
\t\tout[cname] = -1 if a == null else a.loop_mode
\tprint("META_IMPORTED=", root.has_meta("forge3d_post_imported"))
\tprint("LOOP_JSON=", JSON.stringify(out))
\troot.free()
\tquit(0)
""",
        encoding="utf-8",
    )
    res = subprocess.run(
        [godot, "--headless", "--path", str(proj), "--script", str(probe_gd)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert res.returncode == 0, res.stdout + res.stderr
    assert "META_IMPORTED=true" in res.stdout, res.stdout + res.stderr
    m = re.search(r"LOOP_JSON=(\{.*\})", res.stdout)
    assert m is not None, res.stdout + res.stderr
    return json.loads(m.group(1))


def _godot_import(godot: str, proj: Path) -> None:
    imp = subprocess.run(
        [godot, "--headless", "--path", str(proj), "--import", "--quit"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert imp.returncode == 0, imp.stdout + imp.stderr


def test_roundtrip_godot_import_honra_override_loop_explicito(tmp_path: Path) -> None:
    godot = _exigir_godot()
    proj = tmp_path / "proj"
    _preparar_proj_godot(proj)
    glb = proj / "assets" / "hero.glb"
    _criar_glb_clips(glb, ("idle", "attack", "walk"))
    manifesto = {
        "schema": "forge3d/manifest@6",
        "asset_id": "hero",
        "perfil": "godot4",
        "animacoes": [{"nome": "idle", "loop": False}, {"nome": "attack", "loop": True}, "walk"],
    }
    (proj / "assets" / "hero.manifest.json").write_text(json.dumps(manifesto), encoding="utf-8")
    sync_godot_sidecars.aplicar_sidecars_godot(glb, "probe", manifesto=manifesto)
    _godot_import(godot, proj)
    loops = _inspecionar_loops_res(godot, proj, "res://assets/hero.glb", ["idle", "attack", "walk"])
    assert loops == {"idle": 0, "attack": 1, "walk": 1}


def test_roundtrip_godot_import_sem_manifesto_usa_glb_import_probe_b(tmp_path: Path) -> None:
    godot = _exigir_godot()
    proj = tmp_path / "proj_probe_b"
    _preparar_proj_godot(proj)
    glb = proj / "assets" / "hero.glb"
    clips = ("Idle", "Attack", "walk", "Rig|idle", "patrol")
    _criar_glb_clips(glb, clips)

    manifesto = {
        "animacoes": [
            {"nome": "idle", "loop": False},
            {"nome": "attack", "loop": True},
            "walk",
            "Rig|idle",
        ]
    }
    sync_godot_sidecars.aplicar_sidecars_godot(glb, "probe_b", manifesto=manifesto)
    imp_path = proj / "assets" / "hero.glb.import"
    imp_txt = imp_path.read_text(encoding="utf-8")
    imp_txt = imp_txt.replace(
        '"walk": {\n"settings/loop_mode": 1\n}',
        '"patrol": {\n"settings/loop_mode": 2\n},\n"walk": {\n"settings/loop_mode": 1\n}',
    )
    imp_path.write_text(imp_txt, encoding="utf-8")
    assert not (proj / "assets" / "hero.manifest.json").exists()

    _godot_import(godot, proj)
    loops = _inspecionar_loops_res(godot, proj, "res://assets/hero.glb", list(clips))
    assert loops == {"Idle": 0, "Attack": 1, "walk": 1, "Rig|idle": 1, "patrol": 2}


def test_sync_executar_subdir_com_manifesto_raiz_e_resync_probe_f(tmp_path: Path) -> None:
    godot = _exigir_godot()
    clips = ("idle", "attack", "walk")
    glb_bytes = _glb_humanoid_qc_valido("hero", clips)
    staging = tmp_path / "staging"
    (staging / "sub").mkdir(parents=True)
    glb_src = staging / "sub" / "hero_mesh.glb"
    glb_src.write_bytes(glb_bytes)

    ossos_n = len(profiles.carregar("godot4")["rig"]["mapas"]["godot-humanoid@1"])
    man = {
        "schema": "forge3d/manifest@6",
        "asset_id": "hero.probe.f",
        "projeto": "demo",
        "perfil": "godot4",
        "rota": "mesh",
        "tags": ["probe_f"],
        "spec_hash": "sha256:" + "a" * 64,
        "pipeline_version": "0.9.4",
        "determinism": "D2",
        "providers": {"geometry": {"name": "mesh", "version": "0.1.8", "license": "MIT", "seed": 1}},
        "geometry": {"triangulos": 12, "vertices": 8, "bbox_m": [1.0, 1.0, 1.0], "materiais": 1},
        "unidades_export": {"metros_por_unidade": 1.0, "escala_saida": 1.0},
        "animacoes": [{"nome": c, "duracao_s": 1.0, "ossos": ["Hips"]} for c in clips],
        "rig": {"esqueleto": "godot-humanoid@1", "ossos": ossos_n},
        "lod": [{"nivel": 0, "triangulos": 12, "arquivo": "sub/hero_mesh.glb"}],
        "colisao": {"tipo": "none", "partes": 0},
        "files": [
            {
                "caminho": "sub/hero_mesh.glb",
                "papel": "mesh",
                "sha256": sha256_arquivo(glb_src),
                "bytes": len(glb_bytes),
            }
        ],
        "qc": {
            "aprovado": True,
            "gates": [
                {"id": "G2", "status": "ok", "medido": {"esperado_m": 1.0, "pivo_regra": "base"}},
                {"id": "G9", "status": "ok", "medido": {"triangulos": 12, "limite": 500}},
            ],
        },
        "licenca": {"modelo": "MIT", "uso_comercial": True, "notice": "fixture"},
        "origem_spec": {"arquivo": "lote.yaml", "hash": "sha256:" + "a" * 64},
        "run_id": "run-probe-f",
        "created_at": "2026-11-19T00:00:00Z",
    }
    origem = tmp_path / "origem"
    publish.publicar(staging, origem, man, "run-probe-f")

    proj = tmp_path / "proj_probe_f"
    _preparar_proj_godot(proj, ativar_plugin=True)
    rel = sync.executar(origem, proj / "assets", limpar=True)
    assert rel["ok"] is True
    assert "sub/hero_mesh.glb" in rel["copiados"]
    assert "hero.probe.f.manifest.json" in rel["copiados"]
    assert not (proj / "assets" / "sub" / "hero_mesh.manifest.json").exists()

    glb_dst = proj / "assets" / "sub" / "hero_mesh.glb"
    imp_dst = proj / "assets" / "sub" / "hero_mesh.glb.import"
    sync_godot_sidecars.aplicar_sidecars_godot(
        glb_dst,
        "probe_f_1",
        manifesto={
            "rig": {"esqueleto": "godot-humanoid@1"},
            "animacoes": [{"nome": "idle", "loop": False}, {"nome": "attack", "loop": True}, "walk"],
        },
    )
    _godot_import(godot, proj)
    loops1 = _inspecionar_loops_res(godot, proj, "res://assets/sub/hero_mesh.glb", list(clips))
    assert loops1 == {"idle": 0, "attack": 1, "walk": 1}

    m_uid = re.search(r'uid="(uid://[^"]+)"', imp_dst.read_text(encoding="utf-8"))
    assert m_uid is not None
    uid_orig = m_uid.group(1)

    sync.executar(origem, proj / "assets", limpar=True)
    assert f'uid="{uid_orig}"' in imp_dst.read_text(encoding="utf-8")

    sync_godot_sidecars.aplicar_sidecars_godot(
        glb_dst,
        "probe_f_2",
        manifesto={
            "rig": {"esqueleto": "godot-humanoid@1"},
            "animacoes": [{"nome": "idle", "loop": True}, {"nome": "attack", "loop": False}, "walk"],
        },
    )
    assert f'uid="{uid_orig}"' in imp_dst.read_text(encoding="utf-8")
    _godot_import(godot, proj)
    loops2 = _inspecionar_loops_res(godot, proj, "res://assets/sub/hero_mesh.glb", list(clips))
    assert loops2 == {"idle": 1, "attack": 0, "walk": 1}


def test_precedencia_e_nome_null_vazio_paridade_python_gdscript(tmp_path: Path) -> None:
    godot = _exigir_godot()
    sub_py = sync_godot_sidecars._construir_subresources_glb(
        {
            "animacoes": [
                "Rig|idle",
                {"nome": "Armature|walk"},
                {"nome": None, "name": "attack", "loop": True},
                {"nome": "   ", "name": "custom_one", "loop": True},
                {"nome": "idle", "loop": False},
            ]
        }
    )
    assert sub_py["animations"]["Rig|idle"]["settings/loop_mode"] == 1
    assert sub_py["animations"]["Armature|walk"]["settings/loop_mode"] == 1
    assert sub_py["animations"]["attack"]["settings/loop_mode"] == 1
    assert sub_py["animations"]["custom_one"]["settings/loop_mode"] == 1
    assert sub_py["animations"]["idle"]["settings/loop_mode"] == 0

    proj = tmp_path / "proj_prec"
    _preparar_proj_godot(proj)
    glb = proj / "assets" / "hero.glb"
    clips = ("idle", "attack", "Rig|idle", "custom_one")
    _criar_glb_clips(glb, clips)
    sync_godot_sidecars.aplicar_sidecars_godot(
        glb,
        "prec_imp",
        manifesto={
            "animacoes": [
                {"nome": "idle", "loop": False},
                {"nome": "attack", "loop": True},
                {"nome": "Rig|idle", "loop": False},
            ]
        },
    )
    manifesto_colocado = {
        "animacoes": [
            {"nome": "idle", "loop": True},
            {"nome": None, "name": "attack", "loop": False},
            {"nome": "   ", "name": "custom_one", "loop": True},
        ]
    }
    (proj / "assets" / "hero.manifest.json").write_text(
        json.dumps(manifesto_colocado), encoding="utf-8"
    )
    _godot_import(godot, proj)
    loops = _inspecionar_loops_res(godot, proj, "res://assets/hero.glb", list(clips))
    assert loops == {"idle": 1, "attack": 0, "Rig|idle": 0, "custom_one": 1}


def test_configurar_animacoes_prefixo_e_clip_customizado(tmp_path: Path) -> None:
    godot = _exigir_godot()
    script_gd = tmp_path / "check_prefixo_custom.gd"
    script_gd.write_text(
        f"""extends SceneTree
const PostImport := preload({str(POST_IMPORT_GD)!r})
func _initialize() -> void:
\tvar cena := Node3D.new()
\tvar ap := AnimationPlayer.new()
\tvar lib := AnimationLibrary.new()
\tfor cname in ["mixamo_com|idle", "custom_dance", "attack", "custom_one"]:
\t\tvar anim := Animation.new()
\t\tanim.length = 1.0
\t\tlib.add_animation(cname, anim)
\tap.add_animation_library("", lib)
\tcena.add_child(ap)
\tvar manifesto := {{"animacoes": [
\t\t{{"nome": "idle", "loop": false}},
\t\t{{"name": "custom_dance", "loop": true}},
\t\t{{"nome": null, "name": "attack", "loop": true}},
\t\t{{"nome": "  ", "name": "custom_one", "loop": true}},
\t]}}
\tPostImport._configurar_animacoes(cena, manifesto)
\tvar ok := (
\t\tap.get_animation("mixamo_com|idle").loop_mode == Animation.LOOP_NONE
\t\tand ap.get_animation("custom_dance").loop_mode == Animation.LOOP_LINEAR
\t\tand ap.get_animation("attack").loop_mode == Animation.LOOP_LINEAR
\t\tand ap.get_animation("custom_one").loop_mode == Animation.LOOP_LINEAR
\t)
\tcena.free()
\tprint("CUSTOM_LOOP_OK=", ok)
\tquit(0 if ok else 1)
""",
        encoding="utf-8",
    )
    proc = _rodar_godot(godot, ["--script", str(script_gd)])
    assert proc.returncode == 0 and "CUSTOM_LOOP_OK=true" in proc.stdout, proc.stdout + proc.stderr


def test_godot_visual_qa_honra_override_loop_e_reprova_sem_override(tmp_path: Path) -> None:
    godot = _exigir_godot()
    glb = tmp_path / "hero_noloop.glb"
    _criar_glb_clips(glb, ("idle", "walk", "attack"))
    (tmp_path / "hero_noloop.manifest.json").write_text(
        json.dumps(
            {
                "schema": "forge3d/manifest@6",
                "asset_id": "hero_noloop",
                "perfil": "godot4",
                "animacoes": [{"nome": "idle", "loop": False}, "walk", "attack"],
            }
        ),
        encoding="utf-8",
    )
    qa_cli = _rodar_godot(godot, ["--script", str(VISUAL_QA_GD), "--", str(glb)])
    assert qa_cli.returncode == 0 and "GODOT_VISUAL_QA_OK" in qa_cli.stdout, (
        qa_cli.stdout + qa_cli.stderr
    )

    probe_qa = tmp_path / "probe_visual_qa_anim.gd"
    probe_qa.write_text(
        f"""extends SceneTree
const VisualQA := preload({str(VISUAL_QA_GD)!r})
func _criar_cena(idle_mode: int) -> Node3D:
\tvar cena := Node3D.new()
\tvar ap := AnimationPlayer.new()
\tvar lib := AnimationLibrary.new()
\tvar anim := Animation.new()
\tanim.length = 1.0
\tanim.loop_mode = idle_mode
\tvar tr := anim.add_track(Animation.TYPE_ROTATION_3D)
\tanim.track_set_path(tr, "Hips")
\tanim.rotation_track_insert_key(tr, 0.0, Quaternion.IDENTITY)
\tanim.rotation_track_insert_key(tr, 1.0, Quaternion(Vector3.UP, 0.5))
\tlib.add_animation("idle", anim)
\tap.add_animation_library("", lib)
\tcena.add_child(ap)
\treturn cena
func _initialize() -> void:
\tvar c_none := _criar_cena(Animation.LOOP_NONE)
\tvar err_sem := VisualQA._validar_animacoes_cena(c_none, "res://sem_ov.glb", {{}})
\tvar err_ov_ok := VisualQA._validar_animacoes_cena(c_none, "res://ov.glb", {{"animacoes": [{{"nome": "idle", "loop": false}}]}})
\tc_none.free()
\tvar c_lin := _criar_cena(Animation.LOOP_LINEAR)
\tvar err_ov_bad := VisualQA._validar_animacoes_cena(c_lin, "res://ov.glb", {{"animacoes": [{{"nome": "idle", "loop": false}}]}})
\tc_lin.free()
\tvar ok := ("clipe ciclico 'idle' sem LOOP_LINEAR" in err_sem) and err_ov_ok == "" and ("esperado 0" in err_ov_bad)
\tprint("QA_ANIM_PARITY_OK=", ok, " | ", err_sem, " | ", err_ov_bad)
\tquit(0 if ok else 1)
""",
        encoding="utf-8",
    )
    proc = _rodar_godot(godot, ["--script", str(probe_qa)])
    assert proc.returncode == 0 and "QA_ANIM_PARITY_OK=true" in proc.stdout, (
        proc.stdout + proc.stderr
    )
