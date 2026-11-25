"""Tier 3 cross-feature pairwise opaque-box E2E tests (zero `import forge3d`)."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from typing import Any

import pytest

from tests.e2e._helpers_scenarios import (
    GODOT_AA_56_BONES,
    R15_15_PARTS,
    build_humanoid_silhouette_png_bytes,
    build_multisurface_ucx_glb,
    build_prism_glb,
    build_skinned_humanoid_glb,
    provision_godot_project,
    read_glb_chunks,
    register_gemini_4view_mock,
    run_godot_in_project,
    setup_offline_i23d_shim,
    sha256_prefixed,
)


@pytest.mark.blender
@pytest.mark.lento
def test_pair1_r15_mesh_partes_export_r15_nested_pose_and_sync_rojo_lua(
    e2e_sandbox, write_spec, publish_synthetic_asset, make_minimal_png, repo_root
) -> None:
    """Pair 1: mesh + 15 R15 partes + export-r15 + nested KeyframeSequence + isolated sync --rojo-lua."""
    concept_png = e2e_sandbox.root / "pair1_concept.png"
    concept_png.write_bytes(build_humanoid_silhouette_png_bytes(size=256))
    shim_env = setup_offline_i23d_shim(e2e_sandbox.root / "shim_pair1")
    spec_doc = {
        "schema": "forge3d/spec@6", "projeto": "e2e_pair1", "perfil": "roblox-aa-80",
        "destino_exportacao": str(e2e_sandbox.dest_dir), "estilo_global": "stylized_pbr",
        "lote": [{
            "id": "char.sentinel.mesh.01", "tipo": "criatura", "rota": "mesh",
            "origem": str(concept_png), "prompt": "armored stone sentinel with articulated joints",
            "seed": 101, "altura_metros": 2.1, "pivot": "base", "limite_triangulos": 12000,
            "auto_rig": True, "esqueleto": "r15@1", "animacoes_base": ["idle", "walk"],
            "partes": [{"nome": n} for n in R15_15_PARTS], "rig": {"modo": "motor6d", "esqueleto": "r15@1"},
        }],
    }
    spec_path = write_spec(e2e_sandbox.root / "r15_mesh.yaml", spec_doc)
    rc_v, _, err_v, val = e2e_sandbox.run_cli(["validate", str(spec_path)], env_overrides=shim_env)
    assert rc_v == 0, err_v
    assert isinstance(val, dict) and val["ok"] is True

    # R2 F05: nested Pose hierarchy + Keyframe Name + EasingStyle/Direction + studs conversion.
    anim_out = e2e_sandbox.dest_dir / "walk.rbxmx"
    rc_a, _, err_a, anim_rep = e2e_sandbox.run_cli([
        "export-anim", str(repo_root / "examples" / "lote_09_r15.yaml"),
        "--item", "personagem.r15.guard.01", "--clipe", "walk", "--saida", str(anim_out),
    ])
    assert rc_a == 0, err_a
    assert isinstance(anim_rep, dict) and anim_rep["ok"] is True
    anim_xml = ET.fromstring(anim_out.read_text(encoding="utf-8"))
    kf = anim_xml.find(".//Item[@class='Keyframe']")
    assert kf is not None
    assert kf.findtext("Properties/string[@name='Name']") == "Keyframe"
    root_poses = kf.findall("Item[@class='Pose']")
    assert [p.findtext("Properties/string[@name='Name']") for p in root_poses] == ["HumanoidRootPart"]
    assert float(root_poses[0].findtext("Properties/float[@name='Weight']") or -1.0) == pytest.approx(0.0)
    lt = root_poses[0].find("Item[@class='Pose']")
    assert lt is not None and lt.findtext("Properties/string[@name='Name']") == "LowerTorso"
    assert lt.find("Properties/token[@name='EasingStyle']") is not None
    assert lt.find("Properties/token[@name='EasingDirection']") is not None

    # Publish segmented 15-part R15 bundle before export-r15 (R2 F08).
    rc_run, out_run, err_run, run_rep = e2e_sandbox.run_cli(["run", str(spec_path), "--no-cache"], env_overrides=shim_env)
    assert rc_run == 0 and isinstance(run_rep, dict) and run_rep["resumo"]["publicados"] == 1, f"{out_run} {err_run}"

    r15_out = e2e_sandbox.dest_dir / "out" / "sentinel.rbxlx"
    rc_r, out_r, err_r, r15_rep = e2e_sandbox.run_cli([
        "export-r15", str(spec_path), "--item", "char.sentinel.mesh.01",
        "--texturas-dir", str(e2e_sandbox.dest_dir), "--rascunho-local", "--saida", str(r15_out),
    ])
    assert rc_r == 0, f"export-r15 failed on mesh+partes (rc={rc_r}): {out_r} {err_r}"
    assert isinstance(r15_rep, dict) and r15_rep["partes"] == 16 and r15_rep["motores"] == 15
    r15_xml = ET.fromstring(r15_out.read_text(encoding="utf-8"))
    assert len(r15_xml.findall(".//Item[@class='MeshPart']")) == 15
    assert len(r15_xml.findall(".//Item[@class='Motor6D']")) == 15

    # R2 F13: sync --rojo-lua isolates ledger strictly to synced project/assets.
    pub_a = e2e_sandbox.allowlist_add(e2e_sandbox.root / "pub_a")
    publish_synthetic_asset(pub_a, "proj_a.hero.01", projeto="proj_a", perfil="roblox-r15")
    ledger_lines = [
        json.dumps({"evento": "upload", "id": "proj_a.hero.01", "role": "mesh", "asset_id": "111222"}),
        json.dumps({"evento": "upload", "id": "other_proj.wyvern.99", "role": "mesh", "asset_id": "999888"}),
    ]
    (e2e_sandbox.state_dir / "ledger.jsonl").write_text("\n".join(ledger_lines) + "\n", encoding="utf-8")
    lua_out = e2e_sandbox.root / "rojo" / "Assets.lua"
    rc_s, _, err_s, sync_rep = e2e_sandbox.run_cli(
        ["sync", str(pub_a), "--para", str(e2e_sandbox.root / "sync_a"), "--rojo-lua", str(lua_out)]
    )
    assert rc_s == 0, err_s
    assert isinstance(sync_rep, dict) and sync_rep["ok"] is True
    lua_txt = lua_out.read_text(encoding="utf-8")
    assert "proj_a.hero.01" in lua_txt
    assert "other_proj.wyvern.99" not in lua_txt and "999888" not in lua_txt


@pytest.mark.godot
@pytest.mark.lento
def test_pair2_godot4_aa_orm_bonemap_ucx_lod1_sync_and_headless_import(
    e2e_sandbox, make_minimal_png, make_minimal_glb, repo_root
) -> None:
    """Pair 2: godot4-aa + ORMMaterial3D + BoneMap(UpperChest) + UCX_ + _LOD1 + sync --godot-gd + godot --import."""
    pub_dir = e2e_sandbox.dest_dir
    pub_dir.mkdir(parents=True, exist_ok=True)

    # 1. Hero asset (56-bone godot-humanoid-aa@1 + skinned _LOD1 without embedded images + PBR sidecars)
    hero_id = "char.aa.hero.01"
    hero_glb = build_skinned_humanoid_glb(pub_dir / f"{hero_id}.glb", bones=GODOT_AA_56_BONES, node_name=hero_id)
    hero_lod1 = build_skinned_humanoid_glb(
        pub_dir / f"{hero_id}_LOD1.glb", bones=GODOT_AA_56_BONES, clipes=(), with_texture=False, include_foot=False, node_name=hero_id
    )
    assert not read_glb_chunks(hero_lod1)[0].get("images")
    hero_files: list[dict[str, Any]] = [
        {"caminho": hero_glb.name, "papel": "mesh", "sha256": sha256_prefixed(hero_glb), "bytes": hero_glb.stat().st_size},
        {"caminho": hero_lod1.name, "papel": "lod", "sha256": sha256_prefixed(hero_lod1), "bytes": hero_lod1.stat().st_size},
    ]
    for suf, papel, rgba in (("baseColor", "textura", (180, 140, 120, 255)), ("normal", "normal", (128, 128, 255, 255)), ("orm", "orm", (255, 180, 50, 255))):
        tex = make_minimal_png(pub_dir / f"{hero_id}_{suf}.png", width=256, height=256, rgba=rgba)
        hero_files.append({"caminho": tex.name, "papel": papel, "sha256": sha256_prefixed(tex), "bytes": tex.stat().st_size})
    (pub_dir / f"{hero_id}.manifest.json").write_text(json.dumps({
        "schema": "forge3d/manifest@6", "asset_id": hero_id, "projeto": "e2e_pair2", "perfil": "godot4-aa",
        "tipo": "personagem_humanoide", "rota": "import", "tags": ["aa", "hero"], "spec_hash": "sha256:" + "a" * 64,
        "pipeline_version": "0.9.4", "determinism": "D1", "providers": {"geometry": {"name": "import", "version": "0.1.0", "license": "CC0-1.0"}},
        "geometry": {"triangulos": 24, "vertices": 48, "bbox_m": [0.5, 1.8, 0.44], "materiais": 1},
        "unidades_export": {"metros_por_unidade": 1.0, "escala_saida": 1.0},
        "animacoes": [{"nome": c, "duracao_s": 1.0, "ossos": ["Hips"]} for c in ("idle", "walk", "slash_combo")],
        "rig": {"esqueleto": "godot-humanoid-aa@1", "ossos": 56},
        "lod": [{"nivel": 0, "triangulos": 24, "arquivo": hero_glb.name}, {"nivel": 1, "triangulos": 12, "arquivo": hero_lod1.name}],
        "colisao": {"tipo": "none", "partes": 0}, "files": hero_files,
        "qc": {"aprovado": True, "gates": [{"id": "G2", "status": "ok", "medido": {"esperado_m": 1.8, "pivo_regra": "base"}}, {"id": "G9", "status": "ok", "medido": {"triangulos": 24, "limite": 10000}}]},
        "licenca": {"modelo": "CC0-1.0", "uso_comercial": True, "notice": "CC0"},
        "origem_spec": {"arquivo": "lote.yaml", "hash": "sha256:" + "a" * 64}, "run_id": "pair2-hero", "created_at": "2026-11-19T00:00:00Z",
    }, indent=2), encoding="utf-8")

    # 2. Multisurface + 3x UCX_ asset
    prop_id = "prop.aa.pillar.01"
    prop_glb = build_multisurface_ucx_glb(pub_dir / f"{prop_id}.glb", node_name="Pillar", ucx_count=3, with_embedded_images=True)
    prop_files: list[dict[str, Any]] = [{"caminho": prop_glb.name, "papel": "mesh", "sha256": sha256_prefixed(prop_glb), "bytes": prop_glb.stat().st_size}]
    for suf, papel, rgba in (("baseColor", "textura", (150, 150, 160, 255)), ("normal", "normal", (128, 128, 255, 255)), ("orm", "orm", (255, 190, 40, 255))):
        tex = make_minimal_png(pub_dir / f"{prop_id}_{suf}.png", width=256, height=256, rgba=rgba)
        prop_files.append({"caminho": tex.name, "papel": papel, "sha256": sha256_prefixed(tex), "bytes": tex.stat().st_size})
    (pub_dir / f"{prop_id}.manifest.json").write_text(json.dumps({
        "schema": "forge3d/manifest@6", "asset_id": prop_id, "projeto": "e2e_pair2", "perfil": "godot4-aa",
        "tipo": "prop_estatico", "rota": "import", "tags": ["aa", "ucx"], "spec_hash": "sha256:" + "b" * 64,
        "pipeline_version": "0.9.4", "determinism": "D1", "providers": {"geometry": {"name": "import", "version": "0.1.0", "license": "CC0-1.0"}},
        "geometry": {"triangulos": 12, "vertices": 24, "bbox_m": [1.0, 1.0, 1.0], "materiais": 2},
        "unidades_export": {"metros_por_unidade": 1.0, "escala_saida": 1.0}, "animacoes": [], "rig": None,
        "lod": [{"nivel": 0, "triangulos": 12, "arquivo": prop_glb.name}], "colisao": {"tipo": "none", "partes": 0}, "files": prop_files,
        "qc": {"aprovado": True, "gates": [{"id": "G2", "status": "ok", "medido": {"esperado_m": 1.0, "pivo_regra": "base"}}, {"id": "G9", "status": "ok", "medido": {"triangulos": 12, "limite": 2000}}]},
        "licenca": {"modelo": "CC0-1.0", "uso_comercial": True, "notice": "CC0"},
        "origem_spec": {"arquivo": "lote.yaml", "hash": "sha256:" + "b" * 64}, "run_id": "pair2-prop", "created_at": "2026-11-19T00:00:00Z",
    }, indent=2), encoding="utf-8")

    proj_dir = provision_godot_project(e2e_sandbox.root / "godot_pair2", repo_root)
    assets_dir = proj_dir / "assets"
    gd_catalog = assets_dir / "Forge3DAssets.gd"
    rc_s, _, err_s, sync_rep = e2e_sandbox.run_cli(
        ["sync", str(pub_dir), "--para", str(assets_dir), "--godot-gd", str(gd_catalog), "--limpar"]
    )
    assert rc_s == 0, err_s
    assert isinstance(sync_rep, dict) and sync_rep["ok"] is True and sync_rep["godot_assets"] == 2
    assert gd_catalog.is_file() and hero_id in gd_catalog.read_text(encoding="utf-8")

    # R3 F15/F16: .png.import & .glb.import sidecar checks
    norm_imp = assets_dir / f"{hero_id}_normal.png.import"
    assert norm_imp.is_file(), f"missing .png.import sidecar: {norm_imp}"
    assert "compress/mode=2" in norm_imp.read_text(encoding="utf-8")
    assert "compress/normal_map=1" in norm_imp.read_text(encoding="utf-8")
    glb_imp = (assets_dir / f"{hero_id}.glb.import").read_text(encoding="utf-8")
    for token in ("meshes/ensure_tangents=true", "meshes/light_baking=2", "skins/use_named_skins=true", "animation/fps=24", "_subresources="):
        assert token in glb_imp, f"missing {token} in .glb.import"

    # Headless Godot --import + PostImport inspection
    imp_proc = run_godot_in_project(proj_dir, ["--import", "--quit"])
    assert imp_proc.returncode == 0, imp_proc.stdout + imp_proc.stderr

    inspect_gd = proj_dir / "inspect_pair2.gd"
    inspect_gd.write_text(
        """extends SceneTree
const PostImport := preload("res://addons/forge3d/post_import.gd")
func _fail(msg: String) -> void:
\tprinterr("PAIR2_FAIL: " + msg); quit(1)
func _initialize() -> void:
\tvar h_sc := (ResourceLoader.load("res://assets/char.aa.hero.01.glb") as PackedScene).instantiate()
\tvar bm := PostImport.criar_bone_map_humanoid("godot-humanoid-aa@1")
\tif bm.get_skeleton_bone_name("UpperChest") == "":
\t\t_fail("BoneMap missing UpperChest"); return
\tvar p_sc := (ResourceLoader.load("res://assets/prop.aa.pillar.01.glb") as PackedScene).instantiate()
\tvar sbs := p_sc.find_children("*", "StaticBody3D", true, false)
\tvar css := p_sc.find_children("*", "CollisionShape3D", true, false)
\tif sbs.size() != 1 or css.size() != 3:
\t\t_fail("UCX expected 1 StaticBody3D + 3 CollisionShape3D, got %d/%d" % [sbs.size(), css.size()]); return
\tvar mi := p_sc.find_children("*", "MeshInstance3D", true, false)[0] as MeshInstance3D
\tfor s in range(2):
\t\tvar mat := mi.mesh.surface_get_material(s) as ORMMaterial3D
\t\tif mat == null or mat.orm_texture == null or mat.albedo_texture == null or not mat.ao_enabled or not mat.normal_enabled or not is_equal_approx(mat.roughness, 1.0):
\t\t\t_fail("Surface %d ORMMaterial3D invalid (orm/albedo/ao/normal/roughness)" % s); return
\tPostImport.aplicar(p_sc, "res://assets/prop.aa.pillar.01.glb")
\tif p_sc.find_children("*", "StaticBody3D", true, false).size() != 1 or not p_sc.has_meta("forge3d_post_imported"):
\t\t_fail("PostImport not idempotent"); return
\th_sc.free(); p_sc.free()
\tprint("PAIR2_GODOT_OK")
\tquit(0)
""",
        encoding="utf-8",
    )
    ins_proc = run_godot_in_project(proj_dir, ["--script", "res://inspect_pair2.gd"])
    assert ins_proc.returncode == 0 and "PAIR2_GODOT_OK" in ins_proc.stdout, ins_proc.stdout + ins_proc.stderr


@pytest.mark.blender
@pytest.mark.rapido
def test_pair3_scene_budget_plan_run_verify_g11_and_atomic_publish(
    e2e_sandbox, write_spec
) -> None:
    """Pair 3: plan --scene-budget + run G11 static instancing + atomic publish + verify G11."""
    spec_doc = {
        "schema": "forge3d/spec@6",
        "projeto": "e2e_pair3",
        "perfil": "godot4",
        "destino_exportacao": str(e2e_sandbox.dest_dir),
        "estilo_global": "blocky_voxel",
        "orcamento_cena": {"triangulos_max": 12000, "draw_calls_max": 50, "vram_mb_max": 64},
        "lote": [
            {
                "id": "prop.instanced.crate.01", "tipo": "prop_estatico", "rota": "blocky",
                "prompt": "wooden crate", "altura_metros": 0.5, "pivot": "base",
                "limite_triangulos": 400, "colisao": "box", "lod": [100], "quantidade_cena": 25,
            },
            {
                "id": "prop.equip.torch.01", "tipo": "prop_equipavel", "rota": "blocky",
                "prompt": "iron torch", "altura_metros": 0.7, "pivot": "empunhadura",
                "limite_triangulos": 400, "colisao": "convex", "lod": [100], "quantidade_cena": 2,
            },
        ],
    }
    spec_path = write_spec(e2e_sandbox.root / "pair3_budget.yaml", spec_doc)

    rc_p, _, err_p, plan_rep = e2e_sandbox.run_cli(["plan", str(spec_path), "--scene-budget"])
    assert rc_p == 0, err_p
    assert isinstance(plan_rep, dict)
    assert plan_rep["orcamento_cena"]["nao_bloqueante"] is True
    assert plan_rep["orcamento_cena"]["status"] == "ok"
    assert plan_rep["orcamento_cena"]["estimativa"]["draw_calls_estimados"] < 10
    assert not e2e_sandbox.dest_dir.exists()

    rc_r, _, err_r, run_rep = e2e_sandbox.run_cli(["run", str(spec_path), "--no-cache"])
    assert rc_r == 0, err_r
    assert isinstance(run_rep, dict) and run_rep["resumo"]["publicados"] == 2
    assert run_rep["orcamento_cena"]["status"] == "ok"

    rc_v, _, err_v, ver_rep = e2e_sandbox.run_cli(["verify", str(e2e_sandbox.dest_dir)])
    assert rc_v == 0, err_v
    assert isinstance(ver_rep, dict) and ver_rep["ok"] is True

    # R5 F26: verify must re-validate G11 scene budget across published destination manifests.
    g11_dest = e2e_sandbox.allowlist_add(e2e_sandbox.root / "dest_g11_verify")
    heavy_src = build_prism_glb(e2e_sandbox.root / "heavy_src.glb", sides=250, height=1.0)
    over_spec = write_spec(
        e2e_sandbox.root / "pair3_verify_g11.yaml",
        {
            "schema": "forge3d/spec@6",
            "projeto": "e2e_pair3_g11",
            "perfil": "godot4",
            "destino_exportacao": str(g11_dest),
            "orcamento_cena": {"triangulos_max": 400000, "draw_calls_max": 400, "vram_mb_max": 200},
            "lote": [
                {
                    "id": "prop.g11.test.01", "tipo": "prop_estatico", "rota": "import",
                    "origem": str(heavy_src), "altura_metros": 1.0, "pivot": "base",
                    "limite_triangulos": 1500, "colisao": "none", "lod": [100], "quantidade_cena": 50,
                }
            ],
        },
    )
    rc_o, _, err_o, _ = e2e_sandbox.run_cli(["run", str(over_spec), "--no-cache"])
    assert rc_o == 0, err_o
    man_path = g11_dest / "prop.g11.test.01.manifest.json"
    man = json.loads(man_path.read_text(encoding="utf-8"))
    # Mutate schema-valid quantidade_cena (<=500) to exceed 400k tris: 1000 * 500 = 500k > 400k.
    man["quantidade_cena"] = 500
    man["orcamento_cena"] = {"triangulos_max": 400000, "draw_calls_max": 400, "vram_mb_max": 200}
    man_path.write_text(json.dumps(man, indent=2), encoding="utf-8")
    rc_vg, _, _, ver_g11 = e2e_sandbox.run_cli(["verify", str(g11_dest)])
    assert rc_vg == 3 and isinstance(ver_g11, dict) and ver_g11["ok"] is False
    assert "G11" in json.dumps(ver_g11["erros"]) or "FORGE-E-QC-SCENE" in json.dumps(ver_g11["erros"])


@pytest.mark.blender
@pytest.mark.lento
def test_pair4_gemini_4view_cycles_bake_and_g15_zero_fal_run(
    e2e_sandbox, write_spec, make_minimal_png, mock_http_server, repo_root
) -> None:
    """Pair 4: 4-view Gemini concept + referencia_estilo + Cycles High->Low bake + G15 (zero fal.run)."""
    forbidden_hits: list[str] = []
    for base in (repo_root / "src" / "forge3d", repo_root / "tools"):
        for pyf in base.rglob("*.py"):
            txt = pyf.read_text(encoding="utf-8", errors="ignore")
            for tok in ("fal.run", "fal.ai", "FORGE3D_FAL_API_KEY"):
                if tok in txt:
                    forbidden_hits.append(f"{pyf.relative_to(repo_root)}:{tok}")
    assert not forbidden_hits, f"forbidden fal.run references: {forbidden_hits}"

    captured = register_gemini_4view_mock(mock_http_server)
    shim_env = setup_offline_i23d_shim(e2e_sandbox.root / "shim_pair4")
    shim_env.update({
        "FORGE3D_GEMINI_API_URL": f"{mock_http_server.base_url}/v1beta/interactions",
        "FORGE3D_GEMINI_API_KEY": "gem-e2e-pair4-key",
        "FORGE3D_PROVIDER_CONCEITO": "gemini",
        "FORGE3D_DELIGHT": "0",
    })
    ref_png = make_minimal_png(e2e_sandbox.root / "style_ref.png", width=128, height=128, rgba=(90, 130, 210, 255))
    spec_path = write_spec(
        e2e_sandbox.root / "pair4_gemini.yaml",
        {
            "schema": "forge3d/spec@6",
            "projeto": "e2e_pair4",
            "perfil": "godot4",
            "destino_exportacao": str(e2e_sandbox.dest_dir),
            "estilo_global": "stylized_pbr",
            "lote": [
                {
                    "id": "prop.relic.orb.01", "tipo": "prop_estatico", "rota": "mesh",
                    "prompt": "engraved bronze arcane pedestal with glowing crystal core",
                    "seed": 4242, "altura_metros": 1.2, "pivot": "base", "limite_triangulos": 4000,
                    "provider_conceito": "gemini", "referencia_estilo": str(ref_png), "vistas": 4,
                    "detalhe_alto": {"ativo": True, "subdiv_niveis": 1, "ao_cavidade_forca": 0.4},
                    "pbr_zonas": [{"preset": "ouro_ornamentado", "cor_tinta": "#c9a227"}],
                }
            ],
        },
    )
    rc_r, out_r, err_r, rep_r = e2e_sandbox.run_cli(["run", str(spec_path), "--no-cache"], env_overrides=shim_env)
    assert rc_r == 0, f"Pair 4 run failed (rc={rc_r}): {out_r} {err_r}"
    assert isinstance(rep_r, dict) and rep_r["resumo"]["publicados"] == 1
    assert len(captured) == 4
    assert all(req.get("model") == "gemini-nano-banana-2.1" for req in captured)
    man = json.loads((e2e_sandbox.dest_dir / "prop.relic.orb.01.manifest.json").read_text(encoding="utf-8"))
    gate_ids = {g["id"] for g in man["qc"]["gates"]}
    assert "G15" in gate_ids


@pytest.mark.blender
@pytest.mark.rapido
def test_pair5_import_strict_base_externa_autorig_sockets_verify_query(
    e2e_sandbox, write_spec, make_minimal_glb
) -> None:
    """Pair 5: rota import (spec@6 + sha256 + isolamento estrito) + godot4 auto_rig/sockets + verify + query."""
    src_glb = make_minimal_glb(e2e_sandbox.root / "colab_hero.glb", size_xyz=(0.6, 1.8, 0.35), png_wh=(256, 256))
    digest = sha256_prefixed(src_glb)
    spec_doc = {
        "schema": "forge3d/spec@6",
        "projeto": "e2e_pair5",
        "perfil": "godot4",
        "destino_exportacao": str(e2e_sandbox.dest_dir),
        "requisicao": {
            "isolamento": "estrito",
            "base_externa": {"tipo": "personagem_humanoide", "origem": str(src_glb), "sha256": digest, "seed": 7},
        },
        "lote": [
            {
                "id": "char.colab.knight.01", "tipo": "personagem_humanoide", "rota": "import",
                "origem": str(src_glb), "altura_metros": 1.8, "pivot": "base",
                "limite_triangulos": 5000, "auto_rig": True, "esqueleto": "godot-humanoid@1",
                "sockets": ["Hand.R", "Hand.L", "Back"], "tags": ["colab", "pair5"],
            }
        ],
    }
    spec_path = write_spec(e2e_sandbox.root / "pair5_import.yaml", spec_doc)
    no_gpu = {"CUDA_VISIBLE_DEVICES": ""}

    rc_val, _, err_val, _ = e2e_sandbox.run_cli(["validate", str(spec_path)], env_overrides=no_gpu)
    assert rc_val == 0, err_val
    rc_run, _, err_run, rep = e2e_sandbox.run_cli(["run", str(spec_path), "--no-cache"], env_overrides=no_gpu)
    assert rc_run == 0, err_run
    assert isinstance(rep, dict) and rep["resumo"]["publicados"] == 1
    assert rep["itens"][0]["determinism"] == "D1"

    man = json.loads((e2e_sandbox.dest_dir / "char.colab.knight.01.manifest.json").read_text(encoding="utf-8"))
    assert man["rig"]["esqueleto"] == "godot-humanoid@1"
    sock_names = {s["nome"] for s in man.get("sockets") or []}
    assert {"Hand.R", "Hand.L", "Back"}.issubset(sock_names)

    rc_ver, _, err_ver, ver = e2e_sandbox.run_cli(["verify", str(e2e_sandbox.dest_dir)])
    assert rc_ver == 0 and isinstance(ver, dict) and ver["ok"] is True, err_ver

    rc_q, _, err_q, qry = e2e_sandbox.run_cli(["query", "--tag", "pair5"])
    assert rc_q == 0 and isinstance(qry, dict) and qry["total"] == 1, err_q
    assert qry["assets"][0]["asset_id"] == "char.colab.knight.01"

    # Negative B22 boundary: mutate 1 byte of sealed base_externa GLB.
    raw = bytearray(src_glb.read_bytes())
    raw[-1] ^= 0xFF
    src_glb.write_bytes(bytes(raw))
    rc_bad, _, _, bad_rep = e2e_sandbox.run_cli(["validate", str(spec_path)], env_overrides=no_gpu)
    assert rc_bad == 2 and isinstance(bad_rep, dict) and bad_rep["erro"]["codigo"] == "FORGE-E-INPUT-TAMPERED"


@pytest.mark.blender
@pytest.mark.rapido
def test_pair6_blocky_equipavel_roblox_scale_export_acessorio_verify_scale_pivot(
    e2e_sandbox, write_spec, publish_synthetic_asset
) -> None:
    """Pair 6: blocky prop_equipavel (empunhadura) + roblox-r15 3.5714 + export-acessorio + verify escala,pivo."""
    spec_path = write_spec(
        e2e_sandbox.root / "pair6_blade.yaml",
        {
            "schema": "forge3d/spec@6",
            "projeto": "e2e_pair6",
            "perfil": "roblox-r15",
            "destino_exportacao": str(e2e_sandbox.dest_dir),
            "estilo_global": "blocky_voxel",
            "lote": [
                {
                    "id": "weapon.blade.pair6.01", "tipo": "prop_equipavel", "rota": "blocky",
                    "prompt": "bronze short sword with iron crossguard",
                    "altura_metros": 1.12, "pivot": "empunhadura",
                    "limite_triangulos": 800, "colisao": "convex", "lod": [100], "tags": ["pair6"],
                }
            ],
        },
    )
    rc_run, _, err_run, rep = e2e_sandbox.run_cli(["run", str(spec_path), "--no-cache"], env_overrides={"CUDA_VISIBLE_DEVICES": ""})
    assert rc_run == 0, err_run
    assert isinstance(rep, dict) and rep["resumo"]["publicados"] == 1
    man = json.loads((e2e_sandbox.dest_dir / "weapon.blade.pair6.01.manifest.json").read_text(encoding="utf-8"))
    assert man["unidades_export"]["escala_saida"] == pytest.approx(3.5714, abs=1e-3)
    assert man["unidades_export"]["metros_por_unidade"] == pytest.approx(0.28, abs=1e-3)

    rc_v, _, err_v, ver = e2e_sandbox.run_cli(["verify", str(e2e_sandbox.dest_dir), "--only=escala,pivo"])
    assert rc_v == 0 and isinstance(ver, dict) and ver["ok"] is True, err_v
    assert ver["escala"]["delta_pct"] <= 0.5
    assert ver["pivo"]["delta_mm"] <= 1.0

    acc_out = e2e_sandbox.dest_dir / "blade.rbxmx"
    rc_a, _, err_a, acc_rep = e2e_sandbox.run_cli(
        ["export-acessorio", str(e2e_sandbox.dest_dir), "--item", "weapon.blade.pair6.01", "--saida", str(acc_out)]
    )
    assert rc_a == 0 and isinstance(acc_rep, dict) and acc_rep["ok"] is True, err_a
    assert ET.fromstring(acc_out.read_text(encoding="utf-8")).find(".//Item[@class='Accessory']") is not None

    # R2 F09/F10: asymmetric Y-up bbox_m (no Y/Z swap) + single-divided socket (no double / 0.28).
    asym_dir = e2e_sandbox.allowlist_add(e2e_sandbox.root / "asym_acc")
    _, asym_man_path = publish_synthetic_asset(
        asym_dir,
        "weapon.asym.pair6.01",
        perfil="roblox-r15",
        size_xyz=(0.28, 1.40, 0.56),
        manifest_overrides={
            "tipo": "prop_equipavel",
            "anexo": {"parte": "arma", "osso": "Hand.R", "attachment_roblox": "RightGripAttachment", "skinned": False},
            "sockets": [{
                "nome": "Socket_HandR", "osso": "Hand.R", "posicao_local": [0.0, -1.4, 0.0],
                "rotacao_quat_wxyz": [1.0, 0.0, 0.0, 0.0], "frente_local": [0.0, 0.0, -1.0],
            }],
        },
    )
    asym_xml = asym_dir / "asym.rbxmx"
    rc_ax, _, err_ax, _ = e2e_sandbox.run_cli(
        ["export-acessorio", str(asym_man_path), "--saida", str(asym_xml)]
    )
    assert rc_ax == 0, err_ax
    xml_root = ET.fromstring(asym_xml.read_text(encoding="utf-8"))
    sz = xml_root.find(".//Item[@class='MeshPart']/Properties/Vector3[@name='size']")
    assert sz is not None
    assert (float(sz.findtext("X") or 0), float(sz.findtext("Y") or 0), float(sz.findtext("Z") or 0)) == pytest.approx((1.0, 5.0, 2.0), abs=1e-3)
    att_y = float(xml_root.findtext(".//Item[@class='Attachment']/Properties/CoordinateFrame[@name='CFrame']/Y") or 0.0)
    assert att_y == pytest.approx(-1.4, abs=1e-3)
