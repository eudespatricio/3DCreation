"""FA4 Visual 3D Zero-Cost Routes opaque-box E2E tests (Tiers 1 & 2, zero fal.run/GPU)."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from typing import Any

import pytest
from PIL import Image

from tests.e2e._helpers_visual3d import (
    build_sword_silhouette_bytes,
    inspect_glb_chestplate_fit,
    inspect_glb_overlay_gaps_mm,
    inspect_glb_textures,
    make_delight_test_sprite,
    make_hero_front_png,
    make_mesh_spec,
    make_turntable_png,
    mpfb_sandbox_env,
    register_gemini_mock,
    run_tool,
    setup_offline_i23d_shim,
    setup_offline_trellis2_shim,
    write_concept_and_render_pair,
    write_tight_budget_profile,
    write_two_tone_glb,
)


def _error_code(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None
    if isinstance(err_obj := payload.get("erro"), dict) and err_obj.get("codigo"):
        return str(err_obj["codigo"])
    if payload.get("codigo"):
        return str(payload["codigo"])
    return next(
        (str(c) for e in (payload.get("erros") or []) if isinstance(e, dict)
         for c in [e.get("codigo"), *(g.get("codigo") for g in (e.get("gates") or []) if isinstance(g, dict))] if c),
        None,
    )


def _assert_validate_spec_error(
    e2e_sandbox: Any, write_spec: Any, filename: str, item: dict[str, Any], *, perfil: str = "godot4"
) -> None:
    spec_path = write_spec(e2e_sandbox.root / filename, make_mesh_spec(e2e_sandbox.dest_dir, [item], perfil=perfil))
    rc, out, err, payload = e2e_sandbox.run_cli(["validate", str(spec_path)])
    assert rc == 2, f"{filename}: expected exit=2, got rc={rc} out={out} err={err}"
    assert _error_code(payload) == "FORGE-E-SPEC", payload


# ---------------------------------------------------------------------------
# Tier 1: Primary zero-cost visual 3D workflows (7 tests)
# ---------------------------------------------------------------------------


@pytest.mark.blender
@pytest.mark.lento
def test_tier1_explicit_subroutes_honor_prompt_and_origem(
    e2e_sandbox, write_spec, make_minimal_glb
) -> None:
    """Explicit sub-routes (`template`, `procedural`, `extrude_2d`, `i23d`) execute `run` honoring prompt/origem without silent bypass."""
    sword_png = e2e_sandbox.root / "sword_ref.png"
    sword_png.write_bytes(build_sword_silhouette_bytes(fmt="PNG", size=(128, 128)))
    hero_png = make_hero_front_png(e2e_sandbox.root / "hero_front.png")
    items = [
        {"id": "sub.tmpl.01", "tipo": "personagem_humanoide", "rota": "template", "origem": str(hero_png), "prompt": "paladin knight", "seed": 101, "altura_metros": 1.80, "pivot": "base", "colisao": "none", "limite_triangulos": 12000},
        {"id": "sub.proc.01", "tipo": "criatura_quadrupede", "rota": "procedural", "prompt": "armored stone hound", "seed": 102, "altura_metros": 1.20, "pivot": "base", "colisao": "none", "limite_triangulos": 8000},
        {"id": "sub.ext2d.01", "tipo": "prop_equipavel", "parte": "arma", "rota": "extrude_2d", "origem": str(sword_png), "prompt": "runed broadsword", "seed": 103, "altura_metros": 1.00, "pivot": "empunhadura", "colisao": "none", "limite_triangulos": 2500},
        {"id": "sub.i23d.01", "tipo": "prop_equipavel", "parte": "elmo", "rota": "i23d", "origem": str(hero_png), "prompt": "winged helm", "seed": 104, "altura_metros": 0.35, "pivot": "base", "colisao": "none", "limite_triangulos": 2500},
    ]
    spec_path = write_spec(e2e_sandbox.root / "explicit_subroutes.yaml", make_mesh_spec(e2e_sandbox.dest_dir, items))

    rc_val, _, err_val, val = e2e_sandbox.run_cli(["validate", str(spec_path)])
    assert rc_val == 0, f"validate failed for explicit sub-routes: {err_val} payload={val}"
    assert isinstance(val, dict) and val["ok"] is True and val["itens"] == 4

    rc_plan, _, err_plan, plan = e2e_sandbox.run_cli(["plan", str(spec_path)])
    assert rc_plan == 0, err_plan
    assert isinstance(plan, dict) and len(plan["tarefas"]) == 4
    by_id = {t["id"]: t for t in plan["tarefas"]}
    for item in items:
        assert by_id[item["id"]]["rota"] == item["rota"]

    glb_tpl = make_minimal_glb(e2e_sandbox.root / "helm_tpl.glb", size_xyz=(0.3, 0.35, 0.3), png_wh=(512, 512))
    shim_env, i23d_marker = setup_offline_i23d_shim(e2e_sandbox.root / "shim_sub", glb_tpl)
    rc_run, _, err_run, rep = e2e_sandbox.run_cli(
        ["run", str(spec_path), "--no-cache"], env_overrides={**mpfb_sandbox_env(e2e_sandbox.root), **shim_env, "FORGE3D_DELIGHT": "0"}
    )
    assert rc_run == 0, f"run failed on explicit sub-routes: {err_run} rep={rep}"
    assert isinstance(rep, dict) and rep["resumo"]["publicados"] == 4
    assert i23d_marker.is_file(), "explicit `rota: i23d` was silently hijacked instead of invoking i23d"
    rc_v, _, err_v, _ = e2e_sandbox.run_cli(["verify", str(e2e_sandbox.dest_dir)])
    assert rc_v == 0, err_v


@pytest.mark.blender
@pytest.mark.lento
def test_tier1_gemini_4view_orthographic_concept_and_sidecar_mock_http(
    e2e_sandbox, write_spec, make_minimal_png, make_minimal_glb, mock_http_server
) -> None:
    """Gemini Nano Banana 2.1 with `referencia_estilo` + 4-view orthographic contract & `concept.json` sidecar."""
    style_ref = make_minimal_png(e2e_sandbox.root / "style_ref.png", width=64, height=64, rgba=(110, 140, 200, 255))
    calls = register_gemini_mock(mock_http_server, concept_bytes=build_sword_silhouette_bytes(fmt="JPEG", size=(128, 128)), concept_mime="image/jpeg")
    gem_env = {
        "FORGE3D_GEMINI_API_URL": f"{mock_http_server.base_url}/v1beta/interactions",
        "FORGE3D_GEMINI_API_KEY": "e2e-gemini-test-key", "FORGE3D_CYCLES_DEVICE": "CPU", "FORGE3D_TEX_PX": "512",
    }

    dest_1v = e2e_sandbox.allowlist_add(e2e_sandbox.root / "dest_1v")
    spec_1v = write_spec(e2e_sandbox.root / "gemini_1v.yaml", make_mesh_spec(dest_1v, [{
        "id": "prop.sword.gem1v.01", "tipo": "prop_equipavel", "parte": "arma", "rota": "mesh", "extrudir_2d": True,
        "provider_conceito": "gemini", "referencia_estilo": str(style_ref), "prompt": "runed silver sword",
        "seed": 20261118, "altura_metros": 1.0, "pivot": "empunhadura", "limite_triangulos": 2500, "material": "pbr", "colisao": "none",
    }]))
    rc_1v, _, err_1v, rep_1v = e2e_sandbox.run_cli(["run", str(spec_1v)], env_overrides=gem_env)
    assert rc_1v == 0 and isinstance(rep_1v, dict) and rep_1v["resumo"]["publicados"] == 1, err_1v
    assert len(calls) == 1 and calls[0]["headers"].get("x-goog-api-key") == "e2e-gemini-test-key"
    assert calls[0]["headers"].get("api-revision") == "2026-05-20" and calls[0]["body"]["model"] == "gemini-nano-banana-2.1"
    assert any(p.get("type") == "image" for p in calls[0]["body"]["input"])
    man_1v = json.loads((dest_1v / "prop.sword.gem1v.01.manifest.json").read_text(encoding="utf-8"))
    assert "+ref" in man_1v["providers"]["texture"]["version"]
    assert e2e_sandbox.run_cli(["verify", str(dest_1v)])[0] == 0

    calls.clear()
    glb_tpl = make_minimal_glb(e2e_sandbox.root / "anvil_tpl.glb", size_xyz=(0.9, 0.9, 0.9), png_wh=(512, 512))
    shim_env, _ = setup_offline_i23d_shim(e2e_sandbox.root / "shim_4v", glb_tpl)
    dest_4v = e2e_sandbox.allowlist_add(e2e_sandbox.root / "dest_4v")
    spec_4v = write_spec(e2e_sandbox.root / "gemini_4v.yaml", make_mesh_spec(dest_4v, [{
        "id": "prop.anvil.gem4v.01", "tipo": "prop_estatico", "rota": "mesh", "provider_conceito": "gemini",
        "referencia_estilo": str(style_ref), "vistas": 4, "prompt": "forged dwarven steel anvil",
        "seed": 20261119, "altura_metros": 0.9, "pivot": "base", "limite_triangulos": 2500, "material": "pbr", "colisao": "none",
    }]))
    rc_4v, _, err_4v, rep_4v = e2e_sandbox.run_cli(["run", str(spec_4v), "--no-cache"], env_overrides={**gem_env, **shim_env, "FORGE3D_DELIGHT": "0"})
    assert rc_4v == 0, f"4-view Gemini concept route failed: {err_4v} rep={rep_4v}"
    assert len(calls) == 4
    prompts_txt = " ".join(str(p.get("text", "")).lower() for c in calls for p in c["body"]["input"] if isinstance(p, dict))
    for view in ("front", "back", "left", "right"):
        assert view in prompts_txt, f"missing orthographic view prompt '{view}'"
    assert all(any(p.get("type") == "image" for p in c["body"]["input"]) for c in calls)
    sidecar = next((p for p in [dest_4v / "concept.json", *dest_4v.glob("*concept*.json")] if p.is_file()), None)
    assert sidecar is not None, f"missing concept.json sidecar in {dest_4v}"
    sidecar_doc = json.loads(sidecar.read_text(encoding="utf-8"))
    assert sidecar_doc.get("prompt_final") and sidecar_doc.get("referencia_estilo_sha256")
    for png in dest_4v.glob("*.png"):
        assert png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert e2e_sandbox.run_cli(["verify", str(dest_4v)])[0] == 0


def test_tier1_trellis2_local_cli_and_preflight_routing(
    e2e_sandbox, make_minimal_png, make_minimal_glb, write_spec
) -> None:
    """`tools/trellis2_infer.py` exposes tuned local flags, and offline TRELLIS.2 shim passes `doctor` and `plan`."""
    help_proc = run_tool("tools/trellis2_infer.py", ["--help"])
    assert help_proc.returncode == 0, help_proc.stderr
    for flag in ("--quant", "--pipeline-type", "--steps", "--decimation-target", "--texture-size", "--remesh-project"):
        assert flag in help_proc.stdout

    glb_tpl = make_minimal_glb(e2e_sandbox.root / "t2_tpl.glb", png_wh=(512, 512))
    shim_env = setup_offline_trellis2_shim(e2e_sandbox.root / "t2_shim", glb_tpl)
    rc_d, _, err_d, doc_d = e2e_sandbox.run_cli(["doctor"], env_overrides=shim_env)
    assert rc_d in (0, 4) and isinstance(doc_d, dict), err_d
    tre = doc_d["conectores_ia"]["trellis"]
    assert tre["ok"] is True and tre["ativo"] is True and "local" in tre["detalhe"].lower()

    png_in = make_minimal_png(e2e_sandbox.root / "t2_front.png", width=128, height=128)
    spec_path = write_spec(e2e_sandbox.root / "t2_plan.yaml", make_mesh_spec(e2e_sandbox.dest_dir, [{
        "id": "mob.trellis2.01", "tipo": "criatura", "rota": "i23d", "origem": str(png_in),
        "seed": 1, "altura_metros": 1.8, "pivot": "base", "qualidade": "ultra",
    }]))
    assert e2e_sandbox.run_cli(["validate", str(spec_path)], env_overrides=shim_env)[0] == 0
    rc_p, _, err_p, plan_doc = e2e_sandbox.run_cli(["plan", str(spec_path)], env_overrides=shim_env)
    assert rc_p == 0 and isinstance(plan_doc, dict), err_p
    assert plan_doc["tarefas"][0]["estado_previsto"] == "pronto"


@pytest.mark.blender
@pytest.mark.lento
def test_tier1_high_low_cycles_bake_pbr_zonas_quadriflow_and_min_res_512(
    e2e_sandbox, write_spec
) -> None:
    """Opaque-box Cycles High->Low bake: Sobel-free normal after scale (`0.35m`), `pbr_zonas` `cor_tinta` variation, `quadriflow`, >=512px under tight budget."""
    src_glb = write_two_tone_glb(e2e_sandbox.root / "two_tone_src.glb", png_wh=(512, 512))
    tight_prof = write_tight_budget_profile(e2e_sandbox.root / "godot4_tight.yaml", bytes_max_kb=800)
    spec_path = write_spec(e2e_sandbox.root / "bake_zones.yaml", make_mesh_spec(e2e_sandbox.dest_dir, [
        {
            "id": "prop.altar.nrm.01", "tipo": "prop_estatico", "rota": "import", "origem": str(src_glb),
            "altura_metros": 0.35, "pivot": "base", "qualidade": "standard", "limite_triangulos": 1200,
            "material": "pbr", "colisao": "box",
            "detalhe_alto": {"ativo": True, "subdiv_niveis": 1, "chanfro_bevel_m": 0.0, "ao_cavidade_forca": 0.0},
        },
        {
            "id": "prop.altar.zon.01", "tipo": "prop_estatico", "rota": "import", "origem": str(src_glb),
            "altura_metros": 0.35, "pivot": "base", "qualidade": "standard", "limite_triangulos": 1200,
            "material": "pbr", "colisao": "none", "retopologia": "quadriflow", "quadriflow_faces": 500,
            "detalhe_alto": {"ativo": True, "subdiv_niveis": 1, "chanfro_bevel_m": 0.0, "ao_cavidade_forca": 0.0},
            "pbr_zonas": [{"nome": "tinted_stone", "preset": "pedra_musgo", "cor_tinta": "#884422"}],
        },
    ], perfil=str(tight_prof)))
    rc, _, err, rep = e2e_sandbox.run_cli(
        ["run", str(spec_path), "--no-cache"], env_overrides={"FORGE3D_CYCLES_DEVICE": "CPU", "FORGE3D_TEX_PX": "1024"}
    )
    assert rc == 0 and isinstance(rep, dict) and rep["resumo"]["publicados"] == 2, err
    rc_v, _, err_v, _ = e2e_sandbox.run_cli(["verify", str(e2e_sandbox.dest_dir)])
    assert rc_v == 0, err_v

    for aid in ("prop.altar.nrm.01", "prop.altar.zon.01"):
        for info in inspect_glb_textures(e2e_sandbox.dest_dir / f"{aid}.glb"):
            if info.get("embedded"):
                assert info["width"] >= 512 and info["height"] >= 512, info
        for suffix in ("baseColor", "normal", "orm"):
            png = e2e_sandbox.dest_dir / f"{aid}_{suffix}.png"
            assert png.is_file(), f"missing {png.name}"
            with Image.open(png) as im:
                assert im.width >= 512 and im.height >= 512, f"silent <512px downscale on {png.name}: {im.size}"

    nm = Image.open(e2e_sandbox.dest_dir / "prop.altar.nrm.01_normal.png").convert("RGB")
    fg_devs = sorted(max(abs(r - 128), abs(g - 128)) for r, g, b in nm.getdata() if b >= 180)
    assert len(fg_devs) >= 1024, f"unexpectedly small foreground normal area: {len(fg_devs)}"
    fg_p99 = fg_devs[int(0.99 * (len(fg_devs) - 1))]
    fg_gt24_ratio = sum(1 for d in fg_devs if d > 24) / len(fg_devs)
    assert fg_p99 <= 16 and fg_gt24_ratio < 0.005, (
        f"normal map polluted by Sobel(BaseColor): fg_p99={fg_p99}, fg_gt24_ratio={fg_gt24_ratio:.4f}"
    )

    bc = Image.open(e2e_sandbox.dest_dir / "prop.altar.zon.01_baseColor.png").convert("RGB")
    bc_pixels = list(bc.getdata())
    fg_bc = [px for px in bc_pixels if px[0] >= 60 and px[1] >= 30]
    assert len(fg_bc) >= 1000, f"insufficient tinted foreground pixels in baseColor: {len(fg_bc)}"
    modal_rgb, modal_cnt = Counter(fg_bc).most_common(1)[0]
    modal_share = modal_cnt / len(fg_bc)
    assert len(set(bc_pixels)) > 48 and modal_share < 0.85, (
        f"pbr_zonas cor_tinta collapsed cor_base == cor_sec: unique={len(set(bc_pixels))}, modal={modal_rgb} ({modal_share:.3f})"
    )

    man_zon = json.loads((e2e_sandbox.dest_dir / "prop.altar.zon.01.manifest.json").read_text(encoding="utf-8"))
    assert man_zon["sombreamento"]["quadriflow_aplicado"] is True
    assert man_zon["geometry"]["bbox_m"][1] == pytest.approx(0.35, abs=0.01)


@pytest.mark.blender
@pytest.mark.lento
def test_tier1_template_body_overlays_attached_and_smart_fit_conformance(
    e2e_sandbox, write_spec
) -> None:
    """`template_body` overlays attach <=2mm; chestplate torso-fit & `import`+`smart_fit` non-crash regression."""
    hero_png = make_hero_front_png(e2e_sandbox.root / "hero_front.png")
    sword_src = write_two_tone_glb(e2e_sandbox.root / "import_sf_src.glb", png_wh=(512, 512))
    spec_path = write_spec(e2e_sandbox.root / "template_and_sf.yaml", make_mesh_spec(e2e_sandbox.dest_dir, [
        {
            "id": "char.tmpl.ov.01", "tipo": "personagem_humanoide", "rota": "mesh", "template_humanoide": True,
            "origem": str(hero_png), "prompt": "paladin knight", "seed": 301, "altura_metros": 1.80,
            "pivot": "base", "colisao": "none", "limite_triangulos": 12000,
        },
        {
            "id": "arm.chest.sf.01", "tipo": "prop_equipavel", "parte": "peitoral", "rota": "mesh", "extrudir_2d": False,
            "prompt": "steel paladin breastplate", "seed": 302, "altura_metros": 0.60, "pivot": "base", "colisao": "none",
            "limite_triangulos": 2500, "smart_fit": {"conformar_anatomico": {"usar_surface_deform": True}, "encaixar_contato": True},
        },
        {
            "id": "prop.import.sf.01", "tipo": "prop_equipavel", "rota": "import", "origem": str(sword_src),
            "altura_metros": 0.90, "pivot": "empunhadura", "colisao": "none", "limite_triangulos": 2500,
            "smart_fit": {"auto_grip": True},
        },
    ]))
    rc, _, err, rep = e2e_sandbox.run_cli(["run", str(spec_path), "--no-cache"], env_overrides={**mpfb_sandbox_env(e2e_sandbox.root), "FORGE3D_DELIGHT": "0"})
    assert rc == 0 and isinstance(rep, dict) and rep["resumo"]["publicados"] == 3, err
    assert e2e_sandbox.run_cli(["verify", str(e2e_sandbox.dest_dir)])[0] == 0

    gaps = inspect_glb_overlay_gaps_mm(e2e_sandbox.dest_dir / "char.tmpl.ov.01.glb")
    assert gaps["bracelets_mm"] and gaps["boots_mm"], f"expected overlay components in template GLB: {gaps}"
    assert all(d <= 2.0 for d in gaps["bracelets_mm"]), f"floating bracelets (>2mm): {gaps['bracelets_mm']}"
    assert all(d <= 2.0 for d in gaps["boots_mm"]), f"floating boot cuffs (>2mm): {gaps['boots_mm']}"
    if gaps["belt_mm"]:
        assert all(d <= 2.0 for d in gaps["belt_mm"]), f"floating belt (>2mm): {gaps['belt_mm']}"

    man_arm = json.loads((e2e_sandbox.dest_dir / "arm.chest.sf.01.manifest.json").read_text(encoding="utf-8"))
    assert man_arm["anexo"]["parte"] == "peitoral" and man_arm["qc"]["aprovado"] is True
    assert man_arm["geometry"]["bbox_m"][1] == pytest.approx(0.60, abs=0.01)
    fit = inspect_glb_chestplate_fit(e2e_sandbox.dest_dir / "arm.chest.sf.01.glb", e2e_sandbox.dest_dir / "char.tmpl.ov.01.glb")
    assert fit["nao_manifold"] == 0 and fit["verts"] >= 500, fit
    assert 0.75 * fit["body_torso_w"] <= fit["w"] <= 1.25 * fit["body_torso_w"], fit
    assert 0.08 <= fit["d"] <= fit["body_torso_d"] and fit["w"] > 1.8 * fit["d"] and abs(fit["center_x"]) <= 0.02, fit

    # Non-crash/verify regression only: `publish.py` echoes `item["smart_fit"]` verbatim; `aplicar_smart_fit_job(..., corpo_obj=None)` is tested in `tests/test_red_r4_visual.py`.
    man_imp = json.loads((e2e_sandbox.dest_dir / "prop.import.sf.01.manifest.json").read_text(encoding="utf-8"))
    assert man_imp["qc"]["aprovado"] is True and (e2e_sandbox.dest_dir / "prop.import.sf.01.glb").is_file()


def test_tier1_delight_and_visual_qa_critic_cli_contract(e2e_sandbox, mock_http_server) -> None:
    """`delight.py` (albedo/metallic/roughness/emissive) and `visual_qa_critic.py` (2x2 turntable + Gemini) CLI contracts."""
    sprite = make_delight_test_sprite(e2e_sandbox.root / "sprite.png")
    out_alb, out_met = e2e_sandbox.root / "out_albedo.png", e2e_sandbox.root / "out_metallic.png"
    out_rgh, out_emi = e2e_sandbox.root / "out_roughness.png", e2e_sandbox.root / "out_emissive.png"
    out_json = e2e_sandbox.root / "delight_res.json"

    proc_dl = run_tool("tools/delight.py", ["--imagem", str(sprite), "--saida-albedo", str(out_alb), "--saida-metallic", str(out_met), "--saida-roughness", str(out_rgh), "--saida-emissive", str(out_emi), "--resultado", str(out_json)])
    assert proc_dl.returncode == 0, proc_dl.stdout + proc_dl.stderr
    assert json.loads(out_json.read_text(encoding="utf-8"))["ok"] is True
    for p in (out_alb, out_met, out_rgh, out_emi):
        assert p.is_file() and Image.open(p).size == (64, 64)
    assert Image.open(out_met).convert("L").getpixel((18, 32)) >= 128
    rgh_img = Image.open(out_rgh).convert("L")
    assert abs(rgh_img.getpixel((42, 16)) - rgh_img.getpixel((18, 32))) >= 20
    emi_img = Image.open(out_emi).convert("L")
    assert emi_img.getpixel((42, 32)) > 150 and emi_img.getpixel((4, 4)) < 30

    tt_clean = make_turntable_png(e2e_sandbox.root / "turntable_clean.png")
    register_gemini_mock(mock_http_server, qa_payload={"aprovado": True, "nota": 9.2, "defeitos": []})
    qa_env = {"FORGE3D_GEMINI_API_URL": f"{mock_http_server.base_url}/v1beta/interactions", "FORGE3D_GEMINI_API_KEY": "e2e-qa-key"}
    proc_qa = run_tool("tools/visual_qa_critic.py", [str(tt_clean), "--json", "--gemini"], env_overrides=qa_env)
    assert proc_qa.returncode == 0, proc_qa.stdout + proc_qa.stderr
    qa_doc = json.loads(proc_qa.stdout)
    assert qa_doc["ok"] is True and qa_doc["aprovado"] is True and qa_doc["layout"] == "turntable"
    assert qa_doc["defeitos"] == [] and qa_doc["gemini"]["aprovado"] is True


def test_tier1_g15_concept_to_3d_fidelity_gate_contract(
    e2e_sandbox, publish_synthetic_asset, repo_root
) -> None:
    """G15 concept->3D fidelity gate schema + `verify` + `visual_qa_critic --concept` CLI matching pair approval."""
    manifest_schema = json.loads((repo_root / "schemas" / "manifest.v6.schema.json").read_text(encoding="utf-8"))
    gate_pat = manifest_schema["properties"]["qc"]["properties"]["gates"]["items"]["properties"]["id"]["pattern"]
    assert re.match(gate_pat, "G15"), f"manifest.v6.schema.json rejects G15: {gate_pat}"

    c_png, r_png = write_concept_and_render_pair(e2e_sandbox.root / "g15_match", mismatch=False)
    concept_dst = e2e_sandbox.dest_dir / "prop.g15.ok.01_concept.png"
    e2e_sandbox.dest_dir.mkdir(parents=True, exist_ok=True)
    c_bytes = c_png.read_bytes()
    concept_dst.write_bytes(c_bytes)
    c_sha = f"sha256:{hashlib.sha256(c_bytes).hexdigest()}"

    _, man_path = publish_synthetic_asset(e2e_sandbox.dest_dir, asset_id="prop.g15.ok.01", perfil="godot4")
    man = json.loads(man_path.read_text(encoding="utf-8"))
    man["files"].append({"caminho": concept_dst.name, "papel": "concept", "sha256": c_sha, "bytes": len(c_bytes)})
    man["qc"]["gates"].append({"id": "G15", "status": "ok", "medido": {"score": 0.92}})
    man_path.write_text(json.dumps(man, indent=2, sort_keys=True), encoding="utf-8")

    rc_v, _, err_v, rep_v = e2e_sandbox.run_cli(["verify", str(e2e_sandbox.dest_dir)])
    assert rc_v == 0, f"verify failed with G15 gate in manifest: {err_v} rep={rep_v}"

    proc_g15 = run_tool("tools/visual_qa_critic.py", [str(r_png), "--concept", str(c_png), "--json"])
    assert proc_g15.returncode == 0, proc_g15.stdout + proc_g15.stderr
    assert json.loads(proc_g15.stdout)["aprovado"] is True


# ---------------------------------------------------------------------------
# Tier 2: Boundary, negative & zero-leak contracts (6 tests)
# ---------------------------------------------------------------------------


def test_tier2_zero_fal_run_or_fal_key_leak_across_doctor_and_contracts(e2e_sandbox, repo_root) -> None:
    """Zero `fal.run` / `fal.ai` / `FORGE3D_FAL_API_KEY` or `colab_trellis_*.py` across contracts and providers."""
    rc, _, err, doc = e2e_sandbox.run_cli(["doctor"])
    assert rc in (0, 4), err
    doc_blob = json.dumps(doc).lower()
    for forbidden in ("fal.run", "fal.ai", "fal.key", "forge3d_fal_api_key", "colab"):
        assert forbidden not in doc_blob, f"doctor --json leaked '{forbidden}'"

    assert not list((repo_root / "tools").glob("colab_trellis_*.py"))
    offenders: list[str] = []
    targets = [*sorted((repo_root / "schemas").glob("*.json")), *sorted((repo_root / "profiles").glob("*.yaml")), repo_root / "tools" / "trellis2_infer.py", *sorted((repo_root / "src" / "forge3d" / "providers").glob("*.py"))]
    for path in targets:
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
        for term in ("fal.run", "fal.ai", "fal.key", "forge3d_fal_api_key"):
            if term in text:
                offenders.append(f"{path.relative_to(repo_root)}:{term}")
    assert not offenders, f"prohibited fal.run/fal.key references found: {offenders}"


def test_tier2_pbr_zonas_referencia_estilo_and_b23_validation_rejections(
    e2e_sandbox, write_spec, make_minimal_png
) -> None:
    """Invalid `pbr_zonas`, invalid `referencia_estilo`, and `B23` (`origem` + `referencia_estilo`) return `exit=2` `FORGE-E-SPEC`."""
    ok_png = make_minimal_png(e2e_sandbox.root / "ok.png")
    bad_txt = e2e_sandbox.root / "bad_ref.txt"
    bad_txt.write_text("not an image", encoding="utf-8")

    cases: list[tuple[str, dict[str, Any]]] = [
        ("b23_both.yaml", {"id": "t2.b23.both", "tipo": "prop_estatico", "rota": "mesh", "origem": str(ok_png), "referencia_estilo": str(ok_png), "prompt": "pillar", "seed": 1, "altura_metros": 1.0, "pivot": "base"}),
        ("ref_missing.yaml", {"id": "t2.ref.miss", "tipo": "prop_estatico", "rota": "mesh", "provider_conceito": "gemini", "referencia_estilo": str(e2e_sandbox.root / "missing.png"), "prompt": "pillar", "seed": 2, "altura_metros": 1.0, "pivot": "base"}),
        ("ref_badext.yaml", {"id": "t2.ref.ext", "tipo": "prop_estatico", "rota": "mesh", "provider_conceito": "gemini", "referencia_estilo": str(bad_txt), "prompt": "pillar", "seed": 3, "altura_metros": 1.0, "pivot": "base"}),
        ("ref_sd15.yaml", {"id": "t2.ref.sd15", "tipo": "prop_estatico", "rota": "mesh", "provider_conceito": "sd15", "referencia_estilo": str(ok_png), "prompt": "pillar", "seed": 4, "altura_metros": 1.0, "pivot": "base"}),
        ("zonas_empty.yaml", {"id": "t2.zonas.empty", "tipo": "prop_estatico", "rota": "blocky", "prompt": "pillar", "altura_metros": 1.0, "pivot": "base", "pbr_zonas": []}),
        ("zonas_badpreset.yaml", {"id": "t2.zonas.preset", "tipo": "prop_estatico", "rota": "blocky", "prompt": "pillar", "altura_metros": 1.0, "pivot": "base", "pbr_zonas": [{"preset": "unknown_material"}]}),
        ("zonas_badhex.yaml", {"id": "t2.zonas.hex", "tipo": "prop_estatico", "rota": "blocky", "prompt": "pillar", "altura_metros": 1.0, "pivot": "base", "pbr_zonas": [{"preset": "pedra_musgo", "cor_tinta": "not-a-hex"}]}),
        ("zonas_cor_base_sec.yaml", {"id": "t2.zonas.cor", "tipo": "prop_estatico", "rota": "blocky", "prompt": "pillar", "altura_metros": 1.0, "pivot": "base", "pbr_zonas": [{"preset": "pedra_musgo", "cor_base": "#111111", "cor_sec": "#111111"}]}),
    ]
    for fname, item in cases:
        _assert_validate_spec_error(e2e_sandbox, write_spec, fname, item)


def test_tier2_qc_rejects_untextured_clay_pbr_and_4x4_texture(
    e2e_sandbox, make_minimal_glb, publish_synthetic_asset
) -> None:
    """G4 rejects below-minimum (`4x4`) PBR textures, and G5 rejects untextured clay (`baseColorFactor` only) on PBR assets."""
    for label, asset_id, glb_kw, man_ov in (
        ("minres_4x4", "prop.min4.01", {"png_wh": (4, 4)}, {"rota": "mesh", "qualidade": "hero", "pbr_zonas": [{"preset": "pedra_musgo"}]}),
        ("clay", "prop.clay.01", {"with_material": True, "with_texture": False}, {"rota": "mesh", "qualidade": "hero", "pbr_zonas": [{"preset": "pedra_musgo"}], "detalhe_alto": {"ativo": True}}),
    ):
        dest = e2e_sandbox.allowlist_add(e2e_sandbox.root / f"dest_{label}")
        glb_p, man_p = publish_synthetic_asset(dest, asset_id=asset_id, perfil="godot4-aa", manifest_overrides=man_ov)
        make_minimal_glb(glb_p, node_name=asset_id, **glb_kw)
        raw = glb_p.read_bytes()
        man = json.loads(man_p.read_text(encoding="utf-8"))
        man["files"][0]["sha256"] = f"sha256:{hashlib.sha256(raw).hexdigest()}"
        man["files"][0]["bytes"] = len(raw)
        man_p.write_text(json.dumps(man, indent=2, sort_keys=True), encoding="utf-8")
        rc, _, err, rep = e2e_sandbox.run_cli(["verify", str(dest)])
        assert rc == 3, f"expected G4/G5 QC rejection for {label}, got rc={rc} err={err} rep={rep}"
        assert _error_code(rep) == "FORGE-E-QC", rep


def test_tier2_smart_fit_and_quadriflow_faces_boundary_rejections(e2e_sandbox, write_spec) -> None:
    """Documented schema bounds on `quadriflow_faces`, `smart_fit`, `detalhe_alto`, and `pbr_zonas` return `exit=2` `FORGE-E-SPEC`."""
    cases: list[tuple[str, dict[str, Any]]] = [
        ("qf_249.yaml", {"id": "t2.qf.low", "tipo": "prop_estatico", "rota": "blocky", "prompt": "altar", "altura_metros": 1.0, "pivot": "base", "quadriflow_faces": 249}),
        ("qf_50001.yaml", {"id": "t2.qf.high", "tipo": "prop_estatico", "rota": "blocky", "prompt": "altar", "altura_metros": 1.0, "pivot": "base", "quadriflow_faces": 50001}),
        ("qf_bad_type.yaml", {"id": "t2.qf.type", "tipo": "prop_estatico", "rota": "blocky", "prompt": "altar", "altura_metros": 1.0, "pivot": "base", "quadriflow_faces": "five_hundred"}),
        ("sf_bad_type.yaml", {"id": "t2.sf.type", "tipo": "prop_equipavel", "rota": "blocky", "prompt": "gauntlets", "altura_metros": 0.3, "pivot": "origem", "smart_fit": "invalid_str"}),
        ("detalhe_subdiv4.yaml", {"id": "t2.det.sub", "tipo": "prop_estatico", "rota": "blocky", "prompt": "altar", "altura_metros": 1.0, "pivot": "base", "detalhe_alto": {"subdiv_niveis": 4}}),
        ("zonas_rough_hi.yaml", {"id": "t2.zon.r", "tipo": "prop_estatico", "rota": "blocky", "prompt": "altar", "altura_metros": 1.0, "pivot": "base", "pbr_zonas": [{"preset": "pedra_musgo", "roughness_escala": 2.5}]}),
    ]
    for fname, item in cases:
        _assert_validate_spec_error(e2e_sandbox, write_spec, fname, item)


def test_tier2_trellis2_local_negative_inputs_and_tampered_sha256(
    e2e_sandbox, make_minimal_png, make_minimal_glb, write_spec
) -> None:
    """`trellis2_infer.py` rejects missing/corrupt/out-of-range inputs, invalid model blocks, and tampered `sha256` fails validation."""
    out_dir = e2e_sandbox.root / "t2_neg_out"
    res_json = e2e_sandbox.root / "t2_neg_res.json"
    p_miss = run_tool("tools/trellis2_infer.py", ["--imagem", str(e2e_sandbox.root / "missing.png"), "--saida-dir", str(out_dir), "--resultado", str(res_json)])
    assert p_miss.returncode != 0 and json.loads(res_json.read_text(encoding="utf-8"))["ok"] is False

    corrupt_png = e2e_sandbox.root / "broken.png"
    corrupt_png.write_bytes(b"NOT_A_VALID_PNG_STREAM")
    res_corrupt = e2e_sandbox.root / "t2_corrupt_res.json"
    p_corrupt = run_tool("tools/trellis2_infer.py", ["--imagem", str(corrupt_png), "--saida-dir", str(out_dir), "--resultado", str(res_corrupt)])
    assert p_corrupt.returncode != 0 and json.loads(res_corrupt.read_text(encoding="utf-8"))["ok"] is False

    valid_png = make_minimal_png(e2e_sandbox.root / "valid_t2.png", width=128, height=128)
    for idx, extra in enumerate((["--steps", "0"], ["--decimation-target", "100"], ["--remesh-project", "2.0"])):
        r_bad = e2e_sandbox.root / f"t2_bad_{idx}.json"
        p_rng = run_tool("tools/trellis2_infer.py", ["--imagem", str(valid_png), "--saida-dir", str(out_dir), "--resultado", str(r_bad), *extra])
        assert p_rng.returncode != 0 and json.loads(r_bad.read_text(encoding="utf-8"))["ok"] is False

    glb_tpl = make_minimal_glb(e2e_sandbox.root / "t2_tamper_tpl.glb", png_wh=(512, 512))
    shim_env = setup_offline_trellis2_shim(e2e_sandbox.root / "t2_neg_shim", glb_tpl)
    spec_bad_mod = write_spec(e2e_sandbox.root / "t2_bad_mod.yaml", make_mesh_spec(e2e_sandbox.dest_dir, [{
        "id": "mob.bad_mod.01", "tipo": "criatura", "rota": "i23d", "origem": str(valid_png), "seed": 1, "altura_metros": 1.8, "pivot": "base",
    }]))
    rc_m, _, _, plan_m = e2e_sandbox.run_cli(["plan", str(spec_bad_mod)], env_overrides={**shim_env, "FORGE3D_I23D_TRELLIS_MODEL": "unsupported/invalid-model"})
    assert rc_m == 0 and isinstance(plan_m, dict) and plan_m["tarefas"][0]["estado_previsto"] == "bloqueada"

    bad_sha = "sha256:" + ("0" * 63) + ("1" if hashlib.sha256(glb_tpl.read_bytes()).hexdigest()[-1] == "0" else "0")
    yaml_tampered = write_spec(e2e_sandbox.root / "t2_tampered.yaml", {
        "schema": "forge3d/spec@6",
        "projeto": "t2_tamper",
        "perfil": "godot4",
        "destino_exportacao": str(e2e_sandbox.dest_dir),
        "requisicao": {"base_externa": {"tipo": "personagem_humanoide", "origem": str(glb_tpl), "sha256": bad_sha, "seed": 1}},
        "lote": [{"id": "t2.imp.01", "tipo": "personagem_humanoide", "rota": "import", "origem": str(glb_tpl), "altura_metros": 1.8}],
    })
    rc_t, _, err_t, payload_t = e2e_sandbox.run_cli(["validate", str(yaml_tampered)])
    assert rc_t == 2, f"expected exit=2 FORGE-E-INPUT-TAMPERED, got rc={rc_t} err={err_t}"
    assert _error_code(payload_t) == "FORGE-E-INPUT-TAMPERED", payload_t


def test_tier2_g15_concept_mismatch_and_delight_visual_qa_errors(e2e_sandbox) -> None:
    """`delight.py`, `visual_qa_critic.py`, and G15 concept-mismatch CLI error contracts."""
    dl_err_json = e2e_sandbox.root / "dl_err.json"
    p_dl = run_tool("tools/delight.py", ["--imagem", str(e2e_sandbox.root / "missing.png"), "--resultado", str(dl_err_json)])
    assert p_dl.returncode == 1
    dl_doc = json.loads(dl_err_json.read_text(encoding="utf-8"))
    assert dl_doc["ok"] is False and "erro" in dl_doc

    p_qa_miss = run_tool("tools/visual_qa_critic.py", [str(e2e_sandbox.root / "missing_tt.png"), "--json"])
    assert p_qa_miss.returncode == 2 and json.loads(p_qa_miss.stdout)["ok"] is False

    tt_bad = make_turntable_png(e2e_sandbox.root / "tt_bad.png", forehead_smear=True, leg_asymmetry=True)
    p_qa_bad = run_tool("tools/visual_qa_critic.py", [str(tt_bad), "--json"])
    assert p_qa_bad.returncode == 1
    bad_doc = json.loads(p_qa_bad.stdout)
    assert bad_doc["aprovado"] is False
    joined_defects = " ".join(bad_doc["defeitos"])
    assert "forehead_smear" in joined_defects and "leg_asymmetry" in joined_defects

    c_png, r_png = write_concept_and_render_pair(e2e_sandbox.root / "g15_mismatch", mismatch=True)
    p_g15_bad = run_tool("tools/visual_qa_critic.py", [str(r_png), "--concept", str(c_png), "--json"])
    assert p_g15_bad.returncode == 1, p_g15_bad.stdout + p_g15_bad.stderr
    assert json.loads(p_g15_bad.stdout)["aprovado"] is False
