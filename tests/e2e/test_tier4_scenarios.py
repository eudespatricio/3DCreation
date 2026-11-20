"""Tier 4 real-world end-to-end scenario tests (opaque-box, zero `import forge3d`)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest
import yaml

from tests.e2e._helpers_scenarios import (
    R15_15_PARTS,
    build_multisurface_ucx_glb,
    build_prism_glb,
    provision_godot_project,
    register_gemini_4view_mock,
    run_godot_in_project,
    setup_offline_i23d_shim,
    write_colab_trellis_stub_package,
    write_dense_humanoid_glb,
)
from tests.e2e.conftest import find_godot, run_godot_script


@pytest.mark.blender
@pytest.mark.lento
def test_scenario1_roblox_r15_segmented_hero_pipeline(
    e2e_sandbox, write_spec, make_minimal_png
) -> None:
    """Scenario 1: Segmented R15 hero/creature -> validate -> plan -> run -> export-r15 -> sync --rojo-lua -> verify."""
    concept_png = make_minimal_png(e2e_sandbox.root / "hero_concept.png", width=256, height=256, rgba=(170, 110, 70, 255))
    shim_env = setup_offline_i23d_shim(e2e_sandbox.root / "shim_s1")
    spec_path = write_spec(
        e2e_sandbox.root / "s1_r15.yaml",
        {
            "schema": "forge3d/spec@6",
            "projeto": "e2e_s1_r15",
            "perfil": "roblox-aa-80",
            "destino_exportacao": str(e2e_sandbox.dest_dir),
            "estilo_global": "stylized_pbr",
            "lote": [
                {
                    "id": "char.paladin.r15.01", "tipo": "personagem_humanoide", "rota": "mesh",
                    "origem": str(concept_png), "prompt": "segmented armored R15 guardian", "seed": 77,
                    "altura_metros": 2.0, "pivot": "base", "limite_triangulos": 12000, "material": "pbr",
                    "auto_rig": True, "esqueleto": "r15@1", "animacoes_base": ["idle", "walk"],
                    "partes": [{"nome": n} for n in R15_15_PARTS],
                    "rig": {"modo": "motor6d", "esqueleto": "r15@1"},
                }
            ],
        },
    )

    rc_val, _, err_val, val = e2e_sandbox.run_cli(["validate", str(spec_path)], env_overrides=shim_env)
    assert rc_val == 0 and isinstance(val, dict) and val["ok"] is True, err_val

    rc_pl, _, err_pl, plan_rep = e2e_sandbox.run_cli(["plan", str(spec_path)], env_overrides=shim_env)
    assert rc_pl == 0 and isinstance(plan_rep, dict) and plan_rep["plano"]["a_executar"] == 1, err_pl
    assert not e2e_sandbox.dest_dir.exists()

    rc_run, out_run, err_run, run_rep = e2e_sandbox.run_cli(["run", str(spec_path), "--no-cache"], env_overrides=shim_env)
    assert rc_run == 0, f"S1 run failed (rc={rc_run}): {out_run} {err_run}"
    assert isinstance(run_rep, dict) and run_rep["resumo"]["publicados"] == 1

    man = json.loads((e2e_sandbox.dest_dir / "char.paladin.r15.01.manifest.json").read_text(encoding="utf-8"))
    assert len(man.get("partes") or []) == 15
    gate_ids = {g["id"] for g in man["qc"]["gates"]}
    assert {"G12", "G13", "G14"}.issubset(gate_ids)

    rbxlx = e2e_sandbox.dest_dir / "out" / "paladin_r15.rbxlx"
    rc_exp, out_exp, err_exp, exp_rep = e2e_sandbox.run_cli(
        ["export-r15", str(spec_path), "--item", "char.paladin.r15.01", "--saida", str(rbxlx)]
    )
    assert rc_exp == 0, f"S1 export-r15 failed (rc={rc_exp}): {out_exp} {err_exp}"
    assert isinstance(exp_rep, dict) and exp_rep["partes"] == 16 and exp_rep["motores"] == 15

    root_xml = ET.fromstring(rbxlx.read_text(encoding="utf-8"))
    assert len([e for e in root_xml.iter("Item") if e.get("class") == "MeshPart"]) == 15
    assert len([e for e in root_xml.iter("Item") if e.get("class") == "Motor6D"]) == 15
    assert len([e for e in root_xml.iter("Item") if e.get("class") == "SurfaceAppearance"]) == 15
    kfs = [e for e in root_xml.iter("Item") if e.get("class") == "Keyframe"]
    assert kfs and kfs[0].findtext("Properties/string[@name='Name']") == "Keyframe"
    assert [p.findtext("Properties/string[@name='Name']") for p in kfs[0].findall("Item[@class='Pose']")] == ["HumanoidRootPart"]

    # Ledger isolation + verify
    (e2e_sandbox.state_dir / "ledger.jsonl").write_text(
        json.dumps({"evento": "upload", "id": "unrelated.asset.99", "asset_id": "999999"}) + "\n", encoding="utf-8"
    )
    lua_path = e2e_sandbox.root / "rojo" / "Assets.lua"
    rc_sy, _, err_sy, _ = e2e_sandbox.run_cli(
        ["sync", str(e2e_sandbox.dest_dir), "--para", str(e2e_sandbox.root / "rojo_sync"), "--rojo-lua", str(lua_path)]
    )
    assert rc_sy == 0, err_sy
    assert "999999" not in lua_path.read_text(encoding="utf-8")

    rc_ver, _, err_ver, ver_rep = e2e_sandbox.run_cli(["verify", str(e2e_sandbox.dest_dir)])
    assert rc_ver == 0 and isinstance(ver_rep, dict) and ver_rep["ok"] is True, err_ver


@pytest.mark.blender
@pytest.mark.godot
@pytest.mark.lento
def test_scenario2_godot4_aa_hero_equipment_and_dungeon_sector(
    e2e_sandbox, write_spec, make_minimal_glb, repo_root
) -> None:
    """Scenario 2: Godot 4 AA 56-bone hero + equipable prop + mapa_setor UV2/GI -> sync -> godot --import -> visual QA."""
    src_dir = e2e_sandbox.root / "s2_sources"
    hero_src = write_dense_humanoid_glb(src_dir / "hero_aa.glb", height=1.8)
    sword_src = make_minimal_glb(src_dir / "sword.glb", size_xyz=(0.15, 1.0, 0.10), png_wh=(256, 256))
    sector_src = build_multisurface_ucx_glb(src_dir / "sector.glb", node_name="DungeonSector", scale=2.0, ucx_count=3)

    spec_path = write_spec(
        e2e_sandbox.root / "s2_godot_aa.yaml",
        {
            "schema": "forge3d/spec@6",
            "projeto": "e2e_s2_godot",
            "perfil": "godot4-aa",
            "destino_exportacao": str(e2e_sandbox.dest_dir),
            "lote": [
                {
                    "id": "char.hero.aa.01", "tipo": "personagem_humanoide", "rota": "import",
                    "origem": str(hero_src), "altura_metros": 1.8, "pivot": "base",
                    "limite_triangulos": 10000, "auto_rig": True, "esqueleto": "godot-humanoid-aa@1",
                    "clipes": ["idle", "walk", "slash_combo"], "sockets": ["Hand.R", "Hand.L", "Back"],
                    "lod": [100, 50],
                },
                {
                    "id": "weapon.sword.aa.01", "tipo": "prop_equipavel", "rota": "import",
                    "origem": str(sword_src), "altura_metros": 1.0, "pivot": "empunhadura",
                    "limite_triangulos": 2000, "colisao": "convex", "lod": [100],
                },
                {
                    "id": "env.dungeon.sector.01", "tipo": "mapa_setor", "rota": "import",
                    "origem": str(sector_src), "altura_metros": 2.0, "pivot": "centro",
                    "limite_triangulos": 10000, "colisao": "ucx", "lod": [100],
                },
            ],
        },
    )
    rc_run, out_run, err_run, run_rep = e2e_sandbox.run_cli(
        ["run", str(spec_path), "--no-cache"], env_overrides={"CUDA_VISIBLE_DEVICES": ""}
    )
    assert rc_run == 0, f"S2 run failed (rc={rc_run}): {out_run} {err_run}"
    assert isinstance(run_rep, dict) and run_rep["resumo"]["publicados"] == 3

    proj_dir = provision_godot_project(e2e_sandbox.root / "godot_s2", repo_root)
    rc_sync, _, err_sync, sync_rep = e2e_sandbox.run_cli(
        ["sync", str(e2e_sandbox.dest_dir), "--para", str(proj_dir / "assets"), "--godot-gd", str(proj_dir / "assets" / "Forge3DAssets.gd"), "--limpar"]
    )
    assert rc_sync == 0 and isinstance(sync_rep, dict) and sync_rep["godot_assets"] == 3, err_sync

    imp_proc = run_godot_in_project(proj_dir, ["--import", "--quit"])
    assert imp_proc.returncode == 0, imp_proc.stdout + imp_proc.stderr

    s2_gd = proj_dir / "check_s2.gd"
    s2_gd.write_text(
        """extends SceneTree
const PostImport := preload("res://addons/forge3d/post_import.gd")
func _fail(m: String) -> void:
\tprinterr("S2_FAIL: " + m); quit(1)
func _initialize() -> void:
\tvar h := (ResourceLoader.load("res://assets/char.hero.aa.01.glb") as PackedScene).instantiate()
\tif h.find_children("*", "Skeleton3D", true, false).is_empty() or h.find_children("*", "AnimationPlayer", true, false).is_empty():
\t\t_fail("hero missing Skeleton3D or AnimationPlayer"); return
\tif h.find_children("Socket_*", "Marker3D", true, false).size() < 3:
\t\t_fail("hero missing Socket_* Marker3D nodes"); return
\tvar sec := (ResourceLoader.load("res://assets/env.dungeon.sector.01.glb") as PackedScene).instantiate()
\tvar mi := sec.find_children("*", "MeshInstance3D", true, false)[0] as MeshInstance3D
\tif mi.gi_mode != GeometryInstance3D.GI_MODE_STATIC:
\t\t_fail("mapa_setor missing GI_MODE_STATIC"); return
\tif mi.mesh.surface_get_arrays(0)[Mesh.ARRAY_TEX_UV2] == null:
\t\t_fail("mapa_setor missing UV2"); return
\tPostImport.aplicar(sec, "res://assets/env.dungeon.sector.01.glb")
\tif sec.find_children("*", "StaticBody3D", true, false).size() != 1 or not sec.has_meta("forge3d_post_imported"):
\t\t_fail("PostImport idempotency failed"); return
\th.free(); sec.free(); print("S2_GODOT_OK"); quit(0)
""",
        encoding="utf-8",
    )
    chk = run_godot_in_project(proj_dir, ["--script", "res://check_s2.gd"])
    assert chk.returncode == 0 and "S2_GODOT_OK" in chk.stdout, chk.stdout + chk.stderr

    qa_src = (repo_root / "tools" / "godot_visual_qa.gd").read_text(encoding="utf-8")
    assert "is StandardMaterial3D" not in qa_src and ("ORMMaterial3D" in qa_src or "BaseMaterial3D" in qa_src)
    assert find_godot() is not None, "Godot 4 binary required for godot_visual_qa.gd"
    qa_proc = run_godot_script(
        "tools/godot_visual_qa.gd",
        [str(e2e_sandbox.dest_dir / "char.hero.aa.01.glb"), str(e2e_sandbox.dest_dir / "weapon.sword.aa.01.glb")],
    )
    assert qa_proc.returncode == 0 and "GODOT_VISUAL_QA_OK" in qa_proc.stdout, qa_proc.stdout + qa_proc.stderr


@pytest.mark.blender
@pytest.mark.rapido
def test_scenario3_zero_cost_colab_trellis_import_to_verify(
    e2e_sandbox, make_minimal_png, repo_root
) -> None:
    """Scenario 3: Colab TRELLIS.2-4B/Pixal3D worker (4-view offline stub) -> spec@6 -> validate -> run -> verify -> query."""
    stub_dir = e2e_sandbox.root / "trellis_stub"
    call_log = e2e_sandbox.root / "trellis_calls.json"
    write_colab_trellis_stub_package(stub_dir, call_log)

    in_dir = e2e_sandbox.root / "concepts"
    for view in ("front", "back", "left", "right"):
        make_minimal_png(in_dir / "paladin_hero" / f"{view}.png", width=64, height=64, rgba=(180, 140, 100, 255))
    glb_out = e2e_sandbox.root / "colab_glbs"
    yaml_out = e2e_sandbox.root / "spec_trellis.yaml"

    env = dict(e2e_sandbox.env)
    env["CUDA_VISIBLE_DEVICES"] = ""
    env["PYTHONPATH"] = f"{stub_dir}{os.pathsep}{env['PYTHONPATH']}"
    proc = subprocess.run(
        [
            sys.executable,
            str(repo_root / "tools" / "colab_trellis_worker.py"),
            "--input-dir", str(in_dir),
            "--output-dir", str(glb_out),
            "--yaml-out", str(yaml_out),
            "--perfil", "godot4",
            "--altura", "1.8",
            "--schema-version", "6",
            "--qualidade", "hero",
        ],
        cwd=str(repo_root),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, f"colab_trellis_worker failed: {proc.stdout}\n{proc.stderr}"
    call_info = json.loads(call_log.read_text(encoding="utf-8"))
    assert "TRELLIS.2" in call_info["model"] or "Pixal3D" in call_info["model"]
    assert call_info["multi"] is True and call_info["views"] == 4

    doc = yaml.safe_load(yaml_out.read_text(encoding="utf-8"))
    assert doc["schema"] == "forge3d/spec@6"
    assert doc["lote"][0]["rota"] == "import"
    assert str(doc["requisicao"]["base_externa"]["sha256"]).startswith("sha256:")
    doc["destino_exportacao"] = str(e2e_sandbox.dest_dir)
    doc["lote"][0]["tags"] = ["colab_s3"]
    doc["lote"][0]["limite_triangulos"] = 2000
    spec_ready = e2e_sandbox.root / "spec_trellis_ready.yaml"
    spec_ready.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")

    no_gpu = {"CUDA_VISIBLE_DEVICES": ""}
    rc_v, _, err_v, _ = e2e_sandbox.run_cli(["validate", str(spec_ready)], env_overrides=no_gpu)
    assert rc_v == 0, err_v
    rc_r, _, err_r, rep_r = e2e_sandbox.run_cli(["run", str(spec_ready), "--no-cache"], env_overrides=no_gpu)
    assert rc_r == 0 and isinstance(rep_r, dict) and rep_r["resumo"]["publicados"] == 1, err_r
    rc_ver, _, err_ver, ver = e2e_sandbox.run_cli(["verify", str(e2e_sandbox.dest_dir)], env_overrides=no_gpu)
    assert rc_ver == 0 and isinstance(ver, dict) and ver["ok"] is True, err_ver
    rc_q, _, err_q, qry = e2e_sandbox.run_cli(["query", "--tag", "colab_s3"])
    assert rc_q == 0 and isinstance(qry, dict) and qry["total"] == 1, err_q


@pytest.mark.blender
@pytest.mark.rapido
def test_scenario4_zero_gpu_blocky_full_lifecycle(e2e_sandbox, write_spec) -> None:
    """Scenario 4 (MUST PASS NOW): Zero-GPU blocky full lifecycle + tamper detection + clean rebuild + cache hit."""
    spec_path = write_spec(
        e2e_sandbox.root / "s4_blocky.yaml",
        {
            "schema": "forge3d/spec@6",
            "projeto": "e2e_s4_blocky",
            "perfil": "godot4",
            "destino_exportacao": str(e2e_sandbox.dest_dir),
            "estilo_global": "blocky_voxel",
            "paleta": ["#7d858f", "#3b4048", "#ff6a1f"],
            "lote": [
                {
                    "id": "prop.s4.chest.01", "tipo": "prop_estatico", "rota": "blocky",
                    "prompt": "Voxel supply chest with iron corner brackets",
                    "altura_metros": 0.60, "pivot": "base", "limite_triangulos": 500,
                    "colisao": "box", "lod": [100], "tags": ["s4", "blocky"],
                }
            ],
        },
    )
    no_gpu = {"CUDA_VISIBLE_DEVICES": ""}

    rc_val, _, err_val, val = e2e_sandbox.run_cli(["validate", str(spec_path)], env_overrides=no_gpu)
    assert rc_val == 0 and isinstance(val, dict) and val["ok"] is True, err_val

    rc_pl, _, err_pl, _ = e2e_sandbox.run_cli(["plan", str(spec_path)], env_overrides=no_gpu)
    assert rc_pl == 0 and not e2e_sandbox.dest_dir.exists(), err_pl

    rc_np, _, err_np, np_rep = e2e_sandbox.run_cli(["run", str(spec_path), "--nao-publicar"], env_overrides=no_gpu)
    assert rc_np == 0 and isinstance(np_rep, dict), err_np
    assert np_rep["resumo"]["publicados"] == 0
    assert np_rep["itens"][0]["estado"] == "aprovado_nao_publicado"
    assert not e2e_sandbox.dest_dir.exists()

    rc_pub, _, err_pub, pub_rep = e2e_sandbox.run_cli(["run", str(spec_path), "--no-cache"], env_overrides=no_gpu)
    assert rc_pub == 0 and isinstance(pub_rep, dict) and pub_rep["resumo"]["publicados"] == 1, err_pub
    glb_path = e2e_sandbox.dest_dir / "prop.s4.chest.01.glb"
    assert glb_path.is_file() and (e2e_sandbox.dest_dir / "prop.s4.chest.01.manifest.json").is_file()

    rc_ver, _, err_ver, ver = e2e_sandbox.run_cli(["verify", str(e2e_sandbox.dest_dir)], env_overrides=no_gpu)
    assert rc_ver == 0 and isinstance(ver, dict) and ver["ok"] is True and ver["erros"] == [], err_ver

    rc_q, _, err_q, qry = e2e_sandbox.run_cli(["query", "--projeto", "e2e_s4_blocky", "--tag", "s4"])
    assert rc_q == 0 and isinstance(qry, dict) and qry["total"] == 1, err_q

    # 1-byte tamper -> verify rc=3 ("hash divergente") + sync rc=3 ("FORGE-E-MANIFEST")
    tampered = bytearray(glb_path.read_bytes())
    tampered[-1] ^= 0x01
    glb_path.write_bytes(bytes(tampered))
    rc_bad, _, _, bad_ver = e2e_sandbox.run_cli(["verify", str(e2e_sandbox.dest_dir)], env_overrides=no_gpu)
    assert rc_bad == 3 and isinstance(bad_ver, dict) and bad_ver["ok"] is False
    assert any("hash divergente" in str(e.get("erro", "")) for e in bad_ver["erros"])

    sync_dir = e2e_sandbox.root / "s4_sync_blocked"
    rc_sy, _, _, sy_err = e2e_sandbox.run_cli(["sync", str(e2e_sandbox.dest_dir), "--para", str(sync_dir)], env_overrides=no_gpu)
    assert rc_sy == 3 and isinstance(sy_err, dict) and sy_err["erro"]["codigo"] == "FORGE-E-MANIFEST"
    assert not sync_dir.exists()

    # Clean rebuild -> verify rc=0 -> idempotent cache hit
    rc_rb, _, err_rb, rb_rep = e2e_sandbox.run_cli(["run", str(spec_path), "--no-cache", "--clean-dest"], env_overrides=no_gpu)
    assert rc_rb == 0 and isinstance(rb_rep, dict) and rb_rep["resumo"]["publicados"] == 1, err_rb
    rc_v2, _, err_v2, v2 = e2e_sandbox.run_cli(["verify", str(e2e_sandbox.dest_dir)], env_overrides=no_gpu)
    assert rc_v2 == 0 and isinstance(v2, dict) and v2["ok"] is True, err_v2

    rc_hit, _, err_hit, hit_rep = e2e_sandbox.run_cli(["run", str(spec_path)], env_overrides=no_gpu)
    assert rc_hit == 0 and isinstance(hit_rep, dict), err_hit
    assert hit_rep["resumo"]["trabalho_executado"] == 0
    assert hit_rep["resumo"]["cache_hits"] == 1
    assert hit_rep["itens"][0]["estado"] == "cache_hit"


@pytest.mark.blender
@pytest.mark.rapido
def test_scenario5_scene_budget_g11_multi_asset_pipeline(e2e_sandbox, write_spec) -> None:
    """Scenario 5: Multi-item 80% AA scene budget -> plan --scene-budget -> run pass -> verify -> overload G11 fail."""
    prism_glb = build_prism_glb(e2e_sandbox.root / "pillar_120t.glb", sides=30, height=1.0)
    base_spec = {
        "schema": "forge3d/spec@6",
        "projeto": "e2e_s5_budget",
        "perfil": "godot4",
        "destino_exportacao": str(e2e_sandbox.dest_dir),
        "estilo_global": "blocky_voxel",
        "orcamento_cena": {"triangulos_max": 40000, "draw_calls_max": 40, "vram_mb_max": 64},
        "lote": [
            {
                "id": "prop.s5.crate.01", "tipo": "prop_estatico", "rota": "blocky",
                "prompt": "oak crate", "altura_metros": 0.5, "pivot": "base",
                "limite_triangulos": 400, "colisao": "box", "lod": [100], "quantidade_cena": 80,
            },
            {
                "id": "prop.s5.pillar.01", "tipo": "prop_estatico", "rota": "import",
                "origem": str(prism_glb), "altura_metros": 1.0, "pivot": "base",
                "limite_triangulos": 500, "colisao": "none", "lod": [100], "quantidade_cena": 10,
            },
        ],
    }
    ok_path = write_spec(e2e_sandbox.root / "s5_ok.yaml", base_spec)
    rc_p, _, err_p, plan_rep = e2e_sandbox.run_cli(["plan", str(ok_path), "--scene-budget"])
    assert rc_p == 0 and isinstance(plan_rep, dict) and plan_rep["orcamento_cena"]["status"] == "ok", err_p

    rc_r, _, err_r, run_rep = e2e_sandbox.run_cli(["run", str(ok_path), "--no-cache"])
    assert rc_r == 0 and isinstance(run_rep, dict) and run_rep["resumo"]["publicados"] == 2, err_r
    assert run_rep["orcamento_cena"]["status"] == "ok"

    rc_v, _, err_v, ver = e2e_sandbox.run_cli(["verify", str(e2e_sandbox.dest_dir)])
    assert rc_v == 0 and isinstance(ver, dict) and ver["ok"] is True, err_v
    rc_q, _, err_q, qry = e2e_sandbox.run_cli(["query", "--projeto", "e2e_s5_budget"])
    assert rc_q == 0 and isinstance(qry, dict) and qry["total"] == 2, err_q
    assert {a["asset_id"] for a in qry["assets"]} == {"prop.s5.crate.01", "prop.s5.pillar.01"}

    snap_before = {p.name: p.read_bytes() for p in sorted(e2e_sandbox.dest_dir.iterdir())}

    # Overload quantidade_cena so 120 * 500 = 60,000 tris > 40,000 limit -> G11 fail, prior dest untouched.
    over_spec = json.loads(json.dumps(base_spec))
    over_spec["lote"][1]["quantidade_cena"] = 500
    over_path = write_spec(e2e_sandbox.root / "s5_over.yaml", over_spec)
    rc_fail, _, _, fail_rep = e2e_sandbox.run_cli(["run", str(over_path), "--no-cache"])
    assert rc_fail == 3 and isinstance(fail_rep, dict) and fail_rep["erro"]["codigo"] == "FORGE-E-QC-SCENE"
    assert fail_rep["artifacts"] == []
    snap_after = {p.name: p.read_bytes() for p in sorted(e2e_sandbox.dest_dir.iterdir())}
    assert snap_after == snap_before


@pytest.mark.blender
@pytest.mark.lento
def test_scenario6_zero_cost_gemini_4view_cycles_bake_g15(
    e2e_sandbox, write_spec, make_minimal_png, mock_http_server
) -> None:
    """Scenario 6: Zero-cost 4-view Gemini concept + Cycles High->Low bake -> verify + G15 gate."""
    captured = register_gemini_4view_mock(mock_http_server)
    shim_env = setup_offline_i23d_shim(e2e_sandbox.root / "shim_s6")
    shim_env.update({
        "FORGE3D_GEMINI_API_URL": f"{mock_http_server.base_url}/v1beta/interactions",
        "FORGE3D_GEMINI_API_KEY": "gem-e2e-s6-key",
        "FORGE3D_PROVIDER_CONCEITO": "gemini",
        "FORGE3D_DELIGHT": "0",
    })
    ref_png = make_minimal_png(e2e_sandbox.root / "s6_ref.png", width=128, height=128, rgba=(80, 120, 180, 255))
    spec_path = write_spec(
        e2e_sandbox.root / "s6_gemini_g15.yaml",
        {
            "schema": "forge3d/spec@6",
            "projeto": "e2e_s6_visual",
            "perfil": "godot4",
            "destino_exportacao": str(e2e_sandbox.dest_dir),
            "estilo_global": "stylized_pbr",
            "lote": [
                {
                    "id": "prop.s6.anvil.01", "tipo": "prop_estatico", "rota": "mesh",
                    "prompt": "forged dwarven steel anvil with runic edge bevels",
                    "seed": 6060, "altura_metros": 0.9, "pivot": "base", "limite_triangulos": 4000,
                    "provider_conceito": "gemini", "referencia_estilo": str(ref_png), "vistas": 4,
                    "detalhe_alto": {"ativo": True, "subdiv_niveis": 1, "ao_cavidade_forca": 0.45},
                    "pbr_zonas": [{"preset": "aco_forjado", "cor_tinta": "#667788"}],
                }
            ],
        },
    )
    rc_r, out_r, err_r, rep_r = e2e_sandbox.run_cli(["run", str(spec_path), "--no-cache"], env_overrides=shim_env)
    assert rc_r == 0, f"S6 run failed (rc={rc_r}): {out_r} {err_r}"
    assert isinstance(rep_r, dict) and rep_r["resumo"]["publicados"] == 1
    assert len(captured) == 4
    assert all(req.get("headers", {}).get("Host", "").startswith("127.0.0.1:") for req in mock_http_server.requests)

    rc_v, _, err_v, ver = e2e_sandbox.run_cli(["verify", str(e2e_sandbox.dest_dir)])
    assert rc_v == 0 and isinstance(ver, dict) and ver["ok"] is True, err_v
    man = json.loads((e2e_sandbox.dest_dir / "prop.s6.anvil.01.manifest.json").read_text(encoding="utf-8"))
    by_id = {g["id"]: g for g in man["qc"]["gates"]}
    assert "G15" in by_id and by_id["G15"]["status"] == "ok"
