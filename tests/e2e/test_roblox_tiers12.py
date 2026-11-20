"""Opaque-box E2E tests (Tiers 1 & 2) for FA2: Roblox R15/MeshPart & Pose Tree."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET

import pytest

from tests.e2e._helpers_qc import extract_failed_gates
from tests.e2e._helpers_roblox import (
    R15_15_PARTS,
    R15_JOINT_NAMES,
    R15_PARENT_MAP,
    cframe_position,
    find_attachment_y,
    find_pose_tree,
    make_custom_r15_glb,
    make_r15_spec,
    make_sparse_oversized_glb,
    props_dict,
    recompute_manifest_hashes,
    refresh_single_mesh_manifest,
    vector3_values,
    write_r15_segmented_package,
)
from tests.e2e.conftest import build_minimal_png_bytes, write_published_asset

pytestmark = pytest.mark.usefixtures("e2e_sandbox")


# ---------------------------------------------------------------------------
# Tier 1 — Primary Happy Paths
# ---------------------------------------------------------------------------


def test_tier1_export_r15_segmented_meshpart_and_surface_appearance(e2e_sandbox, run_cli, write_spec) -> None:
    """F08: export-r15 supports segmented `mesh` route with 15 MeshParts, Motor6Ds, SurfaceAppearance & Fidelity."""
    pub_dir = e2e_sandbox.dest_dir / "pub_r15"
    item_id = "char.e2e.knight.01"
    write_r15_segmented_package(
        pub_dir,
        item_id,
        state_dir=e2e_sandbox.state_dir,
        with_4ch_textures=True,
        asset_id_start=600001,
    )
    spec_path = write_spec(
        e2e_sandbox.root / "lote_mesh_r15.yaml",
        make_r15_spec(
            pub_dir,
            item_id=item_id,
            rota="mesh",
            extra_item={
                "seed": 123,
                "partes": [{"nome": p} for p in R15_15_PARTS],
                "rig": {"modo": "motor6d", "esqueleto": "r15@1"},
            },
        ),
    )
    out_rbxlx = e2e_sandbox.dest_dir / "out" / "knight_r15.rbxlx"
    rc, stdout, stderr, payload = run_cli(
        [
            "export-r15", str(spec_path), "--item", item_id,
            "--texturas-dir", str(pub_dir), "--saida", str(out_rbxlx),
        ]
    )
    assert rc == 0, f"export-r15 segmented failed (rc={rc}): stdout={stdout} stderr={stderr}"
    assert isinstance(payload, dict) and payload.get("ok") is True
    assert payload.get("partes") == 16
    assert payload.get("motores") == 15
    assert payload.get("modo_rig") == "motor6d"

    root = ET.fromstring(out_rbxlx.read_text(encoding="utf-8"))
    mesh_parts = root.findall(".//Item[@class='MeshPart']")
    motors = root.findall(".//Item[@class='Motor6D']")
    surfaces = root.findall(".//Item[@class='SurfaceAppearance']")
    humanoid = root.find(".//Item[@class='Humanoid']")
    assert len(mesh_parts) == 15
    assert len(motors) == 15
    assert len(surfaces) >= 1
    assert humanoid is not None and float(props_dict(humanoid)["HipHeight"].text or 0.0) > 0.0

    for mp in mesh_parts[:3]:
        pdict = props_dict(mp)
        assert "CollisionFidelity" in pdict
        assert "RenderFidelity" in pdict
    sprops = props_dict(surfaces[0])
    for chan in ("ColorMap", "NormalMap", "RoughnessMap", "MetalnessMap"):
        assert chan in sprops and sprops[chan].findtext("url", "").startswith("rbxassetid://")
    motor_names = {props_dict(m)["Name"].text for m in motors}
    assert motor_names == set(R15_JOINT_NAMES.values())


def test_tier1_export_r15_bone_mode_and_anchored_root(e2e_sandbox, run_cli, write_spec) -> None:
    """export-r15 `--modo-rig bone --anchored-root` emits single MeshPart + 16 Bone hierarchy."""
    spec_path = write_spec(e2e_sandbox.root / "lote_bone.yaml", make_r15_spec(e2e_sandbox.dest_dir))
    out_rbxlx = e2e_sandbox.dest_dir / "out" / "hero_bone.rbxlx"
    rc, stdout, stderr, payload = run_cli(
        [
            "export-r15", str(spec_path), "--item", "char.e2e.hero.01",
            "--modo-rig", "bone", "--anchored-root", "--no-ledger", "--saida", str(out_rbxlx),
        ]
    )
    assert rc == 0, f"export-r15 bone failed (rc={rc}): stdout={stdout} stderr={stderr}"
    assert isinstance(payload, dict) and payload.get("modo_rig") == "bone"
    assert payload.get("partes") == 1
    root = ET.fromstring(out_rbxlx.read_text(encoding="utf-8"))
    mesh_parts = root.findall(".//Item[@class='MeshPart']")
    bones = root.findall(".//Item[@class='Bone']")
    assert len(mesh_parts) == 1
    assert props_dict(mesh_parts[0])["Anchored"].text == "true"
    assert len(bones) == 16


def test_tier1_export_anim_nested_pose_tree_and_stud_displacement(e2e_sandbox, run_cli, write_spec) -> None:
    """F05: export-anim emits Name='Keyframe', nested Pose tree by Part1.Name, Easing*, and /0.28 studs."""
    spec_path = write_spec(e2e_sandbox.root / "lote_anim.yaml", make_r15_spec(e2e_sandbox.dest_dir))
    out_rbxmx = e2e_sandbox.dest_dir / "out" / "hero_anims.rbxmx"
    rc, stdout, stderr, payload = run_cli(
        [
            "export-anim", str(spec_path), "--item", "char.e2e.hero.01",
            "--clipe", "walk,run", "--saida", str(out_rbxmx),
        ]
    )
    assert rc == 0, f"export-anim failed (rc={rc}): stdout={stdout} stderr={stderr}"
    assert isinstance(payload, dict) and payload.get("ok") is True

    root = ET.fromstring(out_rbxmx.read_text(encoding="utf-8"))
    seqs = root.findall(".//Item[@class='KeyframeSequence']")
    assert len(seqs) == 2
    by_name = {props_dict(s)["Name"].text: s for s in seqs}
    assert set(by_name) == {"walk", "run"}

    for seq in seqs:
        kfs = seq.findall("./Item[@class='Keyframe']")
        assert len(kfs) >= 2
        for kf in kfs:
            assert props_dict(kf).get("Name") is not None and props_dict(kf)["Name"].text == "Keyframe"
            poses = find_pose_tree(kf)
            assert "HumanoidRootPart" in poses
            hrp_parent, hrp_el = poses["HumanoidRootPart"]
            assert hrp_parent is None
            assert float(props_dict(hrp_el)["Weight"].text or -1.0) == pytest.approx(0.0, abs=1e-6)
            for part_name, expected_parent in R15_PARENT_MAP.items():
                assert part_name in poses, f"missing Pose {part_name}"
                parent_name, pose_el = poses[part_name]
                assert parent_name == expected_parent, f"{part_name} parent={parent_name}, expected={expected_parent}"
                pprops = props_dict(pose_el)
                assert "EasingStyle" in pprops and "EasingDirection" in pprops

    run_kf0 = by_name["run"].findall("./Item[@class='Keyframe']")[0]
    run_lower = find_pose_tree(run_kf0)["LowerTorso"][1]
    _, ry, _ = cframe_position(props_dict(run_lower)["CFrame"])
    assert ry == pytest.approx(-0.02 / 0.28, abs=1e-3)

    walk_ys = [
        cframe_position(props_dict(find_pose_tree(kf)["LowerTorso"][1])["CFrame"])[1]
        for kf in by_name["walk"].findall("./Item[@class='Keyframe']")
    ]
    assert max(walk_ys) == pytest.approx(0.025 / 0.28, abs=1e-3)


def test_tier1_yup_bbox_and_single_socket_stud_scaling(e2e_sandbox, run_cli) -> None:
    """F09/F10: export-acessorio preserves Y-up bbox_m (no Y/Z swap) and single /0.28 socket scale."""
    pub_dir = e2e_sandbox.dest_dir / "acc_pub"
    item_id = "acc.e2e.blade.01"
    _, man_path = write_published_asset(
        pub_dir,
        item_id,
        perfil="roblox-r15",
        size_xyz=(0.70, 1.82, 0.42),
    )
    tex_path = pub_dir / f"{item_id}_baseColor.png"
    tex_path.write_bytes(build_minimal_png_bytes(64, 64, rgba=(180, 140, 100, 255)))
    man = json.loads(man_path.read_text(encoding="utf-8"))
    man["tipo"] = "prop_equipavel"
    man["anexo"] = {
        "parte": "arma",
        "osso": "RightHand",
        "attachment_roblox": "RightGripAttachment",
        "skinned": False,
    }
    man["sockets"] = [
        {
            "nome": "Socket_MaoD",
            "osso": "RightHand",
            "posicao_local": [0.0, -1.4, 0.0],
            "rotacao_quat_wxyz": [1.0, 0.0, 0.0, 0.0],
            "frente_local": [0.0, 0.0, -1.0],
        }
    ]
    man_path.write_text(json.dumps(man, indent=2), encoding="utf-8")

    state_ledger = e2e_sandbox.state_dir / "ledger.jsonl"
    state_ledger.write_text(
        json.dumps({"evento": "upload", "id": item_id, "asset_id": 710001, "asset_type": "Model", "arquivo": str(pub_dir / f"{item_id}.glb")}) + "\n"
        + json.dumps({"evento": "upload", "id": f"{item_id}_baseColor", "asset_id": 710002, "asset_type": "Image", "arquivo": str(tex_path)}) + "\n",
        encoding="utf-8",
    )

    out_rbxmx = e2e_sandbox.dest_dir / "out" / "blade_acc.rbxmx"
    rc, stdout, stderr, payload = run_cli(
        ["export-acessorio", str(man_path), "--saida", str(out_rbxmx)]
    )
    assert rc == 0, f"export-acessorio failed (rc={rc}): stdout={stdout} stderr={stderr}"
    assert isinstance(payload, dict) and payload.get("attachment") == "RightGripAttachment"

    root = ET.fromstring(out_rbxmx.read_text(encoding="utf-8"))
    handle = root.find(".//Item[@class='MeshPart']")
    att = root.find(".//Item[@class='Attachment']")
    assert handle is not None and att is not None
    sx, sy, sz = vector3_values(props_dict(handle)["size"])
    assert (sx, sy, sz) == pytest.approx((2.5, 6.5, 1.5), abs=1e-3)
    _, ay, _ = cframe_position(props_dict(att)["CFrame"])
    assert ay == pytest.approx(-1.4, abs=1e-3)


def test_tier1_export_surface_orm_and_sync_rojo_lua_isolated_ledger(e2e_sandbox, run_cli) -> None:
    """export-surface excludes _orm from RoughnessMap on manifest@6; F13 sync isolates Rojo ledger."""
    pub_a = e2e_sandbox.dest_dir / "proj_a"
    pub_b = e2e_sandbox.dest_dir / "proj_b"
    _, man_a = write_published_asset(pub_a, "prop.e2e.alpha.01", projeto="proj_a", perfil="roblox-r15")
    base_a_path = pub_a / "prop.e2e.alpha.01_baseColor.png"
    base_a_path.write_bytes(build_minimal_png_bytes(64, 64, rgba=(190, 170, 150, 255)))
    norm_a_path = pub_a / "prop.e2e.alpha.01_normal.png"
    norm_a_path.write_bytes(build_minimal_png_bytes(64, 64, rgba=(128, 192, 255, 255)))
    orm_only_path = pub_a / "prop.e2e.alpha.01_orm.png"
    orm_only_path.write_bytes(build_minimal_png_bytes(64, 64, rgba=(255, 180, 30, 255)))
    man_obj = json.loads(man_a.read_text(encoding="utf-8"))
    man_obj["files"].extend([
        {"caminho": base_a_path.name, "papel": "textura", "sha256": "sha256:" + "0" * 64, "bytes": 1},
        {"caminho": orm_only_path.name, "papel": "orm", "sha256": "sha256:" + "0" * 64, "bytes": 1},
        {"caminho": norm_a_path.name, "papel": "textura", "sha256": "sha256:" + "0" * 64, "bytes": 1},
    ])
    man_a.write_text(json.dumps(man_obj, indent=2), encoding="utf-8")
    recompute_manifest_hashes(man_a, pub_a)

    pub_b.mkdir(parents=True, exist_ok=True)
    foreign_glb = pub_b / "other.dragon.99.glb"
    make_custom_r15_glb(foreign_glb)

    ledger = e2e_sandbox.state_dir / "ledger.jsonl"
    ledger.write_text(
        json.dumps({"evento": "upload", "id": "prop.e2e.alpha.01_baseColor", "asset_id": 810001, "asset_type": "Image", "arquivo": str(base_a_path)}) + "\n"
        + json.dumps({"evento": "upload", "id": "prop.e2e.alpha.01_orm", "asset_id": 810002, "asset_type": "Image", "arquivo": str(orm_only_path)}) + "\n"
        + json.dumps({"evento": "upload", "id": "other.dragon.99", "asset_id": 990999, "asset_type": "Model", "arquivo": str(foreign_glb)}) + "\n",
        encoding="utf-8",
    )

    surf_out = e2e_sandbox.dest_dir / "out" / "alpha_surface.rbxmx"
    rc_s, out_s, err_s, pay_s = run_cli(["export-surface", str(man_a), "--saida", str(surf_out)])
    assert rc_s == 0, f"export-surface failed: {out_s} {err_s}"
    assert isinstance(pay_s, dict) and pay_s.get("mapas", {}).get("ColorMap") == "rbxassetid://810001"
    assert "RoughnessMap" not in pay_s["mapas"] and "810002" not in str(pay_s["mapas"])

    sync_a = e2e_sandbox.root / "sync_a"
    e2e_sandbox.allowlist_add(sync_a)
    lua_out = e2e_sandbox.dest_dir / "rojo" / "Assets.lua"
    rc_sync, out_sync, err_sync, _ = run_cli(
        ["sync", str(pub_a), "--para", str(sync_a), "--rojo-lua", str(lua_out)]
    )
    assert rc_sync == 0, f"sync failed: {out_sync} {err_sync}"
    lua_text = lua_out.read_text(encoding="utf-8")
    assert "810001" in lua_text
    assert "990999" not in lua_text and "other.dragon.99" not in lua_text


@pytest.mark.blender
@pytest.mark.rapido
def test_tier1_spec_cache_key_sensitivity_partes_rig_animacoes_qtd(e2e_sandbox, run_cli, write_spec) -> None:
    """F12: changing quantidade_cena, animacoes, rig, or partes invalidates plan cache key."""
    base_spec = make_r15_spec(
        e2e_sandbox.dest_dir,
        item_id="char.e2e.cache.01",
        extra_item={"quantidade_cena": 1, "animacoes": [{"nome": "idle"}]},
    )
    p_base = write_spec(e2e_sandbox.root / "cache_base.yaml", base_spec)
    rc_run, out_r, err_r, pay_r = run_cli(["run", str(p_base)])
    assert rc_run == 0, f"initial run failed: {out_r} {err_r}"
    assert isinstance(pay_r, dict) and pay_r["resumo"]["publicados"] == 1

    rc_hit, _, _, pay_hit = run_cli(["plan", str(p_base)])
    assert rc_hit == 0 and isinstance(pay_hit, dict)
    base_key = pay_hit["tarefas"][0]["chave"]
    assert pay_hit["plano"]["cache_hits"] == 1

    for label, patch in (
        ("quantidade_cena", {"quantidade_cena": 8}),
        ("animacoes", {"animacoes": [{"nome": "idle"}, {"nome": "walk"}]}),
        ("rig", {"rig": {"modo": "skinned", "esqueleto": "r15@1"}}),
    ):
        mut = json.loads(json.dumps(base_spec))
        mut["lote"][0].update(patch)
        p_mut = write_spec(e2e_sandbox.root / f"cache_{label}.yaml", mut)
        rc_p, _, _, pay_p = run_cli(["plan", str(p_mut)])
        assert rc_p == 0 and isinstance(pay_p, dict)
        assert pay_p["tarefas"][0]["chave"] != base_key, f"plan cache key ignored change to {label}"
        assert pay_p["plano"]["cache_hits"] == 0, f"plan reported false cache hit after {label} change"

    mesh_a = make_r15_spec(e2e_sandbox.dest_dir, item_id="char.e2e.partes.01", rota="mesh", extra_item={"seed": 123})
    mesh_b = make_r15_spec(
        e2e_sandbox.dest_dir,
        item_id="char.e2e.partes.01",
        rota="mesh",
        extra_item={"seed": 123, "partes": [{"nome": p} for p in R15_15_PARTS], "rig": {"modo": "motor6d", "esqueleto": "r15@1"}},
    )
    rc_a, _, _, pay_a = run_cli(["plan", str(write_spec(e2e_sandbox.root / "partes_a.yaml", mesh_a))])
    rc_b, _, _, pay_b = run_cli(["plan", str(write_spec(e2e_sandbox.root / "partes_b.yaml", mesh_b))])
    assert rc_a == 0 and rc_b == 0
    assert pay_a["tarefas"][0]["chave"] != pay_b["tarefas"][0]["chave"], "plan cache key ignored `partes`"


# ---------------------------------------------------------------------------
# Tier 2 — Boundaries & Negative Rejections
# ---------------------------------------------------------------------------


def test_tier2_r15_partes_b11_b13_b24_b25_refusals(e2e_sandbox, run_cli, write_spec) -> None:
    """B11, B12, B13, B24, B25 spec rejections fail with exit=2 and FORGE-E-SPEC."""
    glb_src = e2e_sandbox.root / "dummy.glb"
    make_custom_r15_glb(glb_src)

    cases: list[tuple[str, dict]] = [
        ("b11_import_parte", {
            "id": "prop.e2e.b11.01", "tipo": "prop_equipavel", "rota": "import",
            "origem": str(glb_src), "parte": "arma", "altura_metros": 1.0, "limite_triangulos": 1500,
        }),
        ("b12_mismatch_tipo", {
            "id": "char.e2e.b12.01", "tipo": "personagem_humanoide", "rota": "blocky", "prompt": "test",
            "parte": "arma", "altura_metros": 1.8, "limite_triangulos": 4000,
        }),
        ("b13_rigid_autorig", {
            "id": "acc.e2e.b13.01", "tipo": "prop_equipavel", "rota": "blocky", "prompt": "test",
            "parte": "capa", "auto_rig": True, "altura_metros": 1.0, "limite_triangulos": 1500,
        }),
        ("b24_r15_winged", {
            "id": "mob.e2e.b24.01", "tipo": "criatura_alada", "rota": "blocky", "prompt": "test",
            "auto_rig": True, "esqueleto": "r15@1", "altura_metros": 2.0, "limite_triangulos": 6000,
        }),
        ("b25_missing_partes", {
            "id": "char.e2e.b25a.01", "tipo": "personagem_humanoide", "rota": "mesh", "prompt": "test", "seed": 123,
            "auto_rig": True, "esqueleto": "r15@1", "rig": {"modo": "motor6d", "esqueleto": "r15@1"},
            "altura_metros": 1.8, "limite_triangulos": 8000,
        }),
        ("b25_dup_partes", {
            "id": "char.e2e.b25b.01", "tipo": "personagem_humanoide", "rota": "mesh", "prompt": "test", "seed": 123,
            "auto_rig": True, "esqueleto": "r15@1", "rig": {"modo": "motor6d", "esqueleto": "r15@1"},
            "partes": [{"nome": p} for p in (*R15_15_PARTS[:-1], R15_15_PARTS[0])],
            "altura_metros": 1.8, "limite_triangulos": 8000,
        }),
    ]
    for name, item in cases:
        spec = {
            "schema": "forge3d/spec@6",
            "projeto": "e2e_b_rules",
            "perfil": "roblox-r15",
            "destino_exportacao": str(e2e_sandbox.dest_dir),
            "estilo_global": "blocky_voxel",
            "lote": [item],
        }
        p = write_spec(e2e_sandbox.root / f"{name}.yaml", spec)
        rc, _, _, payload = run_cli(["validate", str(p)])
        assert rc == 2, f"{name} expected rc=2, got {rc}"
        assert isinstance(payload, dict) and payload.get("erro", {}).get("codigo") == "FORGE-E-SPEC"
        assert "lote" in json.dumps(payload) or "parte" in json.dumps(payload) or "r15" in json.dumps(payload)


def test_tier2_r15_caps_tris_partes_bytes_and_verify_parte_corrupted(e2e_sandbox, run_cli) -> None:
    """R15 caps (>16000 tris/part, >15 partes, >16384 KB) & F07 corrupted `papel: parte` fail verify (rc=3)."""
    d_tris = e2e_sandbox.dest_dir / "cap_tris"
    _, man_t = write_published_asset(d_tris, "char.e2e.tris.01", perfil="roblox-aa-80", size_xyz=(1.0, 1.8, 1.0))
    make_custom_r15_glb(d_tris / "char.e2e.tris.01.glb", prim_count=1, cubes_per_prim=1334, size_xyz=(3.5714, 1.8 * 3.5714, 3.5714))
    refresh_single_mesh_manifest(man_t, d_tris / "char.e2e.tris.01.glb", tris=16008, limite=25000, qualidade="hero")
    rc_t, _, _, pay_t = run_cli(["verify", str(d_tris)])
    assert rc_t == 3 and "G9" in extract_failed_gates(pay_t)

    d_prims = e2e_sandbox.dest_dir / "cap_prims"
    _, man_p = write_published_asset(d_prims, "char.e2e.prims.01", perfil="roblox-r15", size_xyz=(1.0, 1.8, 1.0))
    make_custom_r15_glb(d_prims / "char.e2e.prims.01.glb", prim_count=16, cubes_per_prim=1, size_xyz=(3.5714, 1.8 * 3.5714, 3.5714))
    refresh_single_mesh_manifest(man_p, d_prims / "char.e2e.prims.01.glb", tris=192, limite=8000)
    rc_p, _, _, pay_p = run_cli(["verify", str(d_prims)])
    assert rc_p == 3 and "G9" in extract_failed_gates(pay_p)

    d_bytes = e2e_sandbox.dest_dir / "cap_bytes"
    _, man_b = write_published_asset(d_bytes, "char.e2e.bytes.01", perfil="roblox-r15", size_xyz=(1.0, 1.8, 1.0))
    make_custom_r15_glb(d_bytes / "char.e2e.bytes.01.glb", pad_bytes=16_800_000, size_xyz=(3.5714, 1.8 * 3.5714, 3.5714))
    refresh_single_mesh_manifest(man_b, d_bytes / "char.e2e.bytes.01.glb", tris=12, limite=8000)
    rc_b, _, _, pay_b = run_cli(["verify", str(d_bytes)])
    assert rc_b == 3 and "G9" in extract_failed_gates(pay_b)

    d_part = e2e_sandbox.dest_dir / "corrupt_parte"
    _, man_part = write_r15_segmented_package(d_part, "char.e2e.badpart.01", with_4ch_textures=False)
    rc_ok, out_ok, err_ok, pay_ok = run_cli(["verify", str(d_part)])
    assert rc_ok == 0 and isinstance(pay_ok, dict) and pay_ok.get("ok") is True, (
        f"uncorrupted write_r15_segmented_package failed verify: {out_ok} {err_ok} {pay_ok}"
    )
    (d_part / "Head.glb").write_bytes(b"NOT_A_VALID_GLB" * 16)
    recompute_manifest_hashes(man_part, d_part)
    rc_part, _, _, pay_part = run_cli(["verify", str(d_part)])
    assert rc_part == 3, f"F07: verify ignored corrupted papel=parte GLB (pay={pay_part})"
    assert isinstance(pay_part, dict) and any(
        "Head.glb" in str(e) or "parte" in str(e).lower() for e in (pay_part.get("erros") or [])
    ), f"F07: verify did not report corrupted Head.glb (pay={pay_part})"


def test_tier2_r15_invalid_altura_and_escala_mismatch_refused(e2e_sandbox, run_cli, write_spec) -> None:
    """altura_metros <= 0 fails validate (rc=2); mismatched escala_saida fails verify (rc=3)."""
    for bad_h in (0.0, -0.5):
        spec = make_r15_spec(e2e_sandbox.dest_dir, extra_item={"altura_metros": bad_h})
        p = write_spec(e2e_sandbox.root / f"bad_h_{bad_h}.yaml", spec)
        rc, _, _, payload = run_cli(["validate", str(p)])
        assert rc == 2 and isinstance(payload, dict) and payload.get("erro", {}).get("codigo") == "FORGE-E-SPEC"

    d_scale = e2e_sandbox.dest_dir / "bad_scale"
    write_published_asset(d_scale, "prop.e2e.scale.01", perfil="roblox-r15", escala_saida=1.0)
    rc_v, _, _, pay_v = run_cli(["verify", str(d_scale)])
    assert rc_v == 3 and isinstance(pay_v, dict)
    assert any("escala_saida" in str(e) for e in pay_v.get("erros") or [])


def test_tier2_export_anim_invalid_clip_and_r15_socket_double_scale_guard(e2e_sandbox, run_cli, write_spec) -> None:
    """Invalid clip fails export-anim (rc=2); export-r15 must NOT double-divide sockets by 0.28 (F10)."""
    spec_path = write_spec(e2e_sandbox.root / "lote_anim_err.yaml", make_r15_spec(e2e_sandbox.dest_dir))
    rc_bad, _, _, pay_bad = run_cli(
        ["export-anim", str(spec_path), "--item", "char.e2e.hero.01", "--clipe", "voo_inexistente"]
    )
    assert rc_bad == 2 and isinstance(pay_bad, dict) and pay_bad.get("erro", {}).get("codigo") == "FORGE-E-SPEC"

    tex_dir = e2e_sandbox.dest_dir / "r15_sock_tex"
    tex_dir.mkdir(parents=True, exist_ok=True)
    _, man_p = write_published_asset(tex_dir, "char.e2e.hero.01", perfil="roblox-r15", size_xyz=(1.0, 1.8, 0.5))
    for suffix, rgba in (
        ("baseColor", (180, 180, 180, 255)),
        ("normal", (128, 192, 255, 255)),
        ("roughness", (160, 160, 160, 255)),
        ("metalness", (40, 40, 40, 255)),
    ):
        (tex_dir / f"char.e2e.hero.01_{suffix}.png").write_bytes(build_minimal_png_bytes(64, 64, rgba=rgba))
    man = json.loads(man_p.read_text(encoding="utf-8"))
    man["sockets"] = [
        {
            "nome": "RightGripAttachment", "osso": "RightHand",
            "posicao_local": [0.0, -0.56, 0.0], "rotacao_quat_wxyz": [1.0, 0.0, 0.0, 0.0], "frente_local": [0.0, 0.0, -1.0],
        }
    ]
    man_p.write_text(json.dumps(man, indent=2), encoding="utf-8")

    rbxlx_base = e2e_sandbox.dest_dir / "out" / "r15_nosock.rbxlx"
    rbxlx_sock = e2e_sandbox.dest_dir / "out" / "r15_withsock.rbxlx"
    rc_0, _, _, _ = run_cli(["export-r15", str(spec_path), "--item", "char.e2e.hero.01", "--no-ledger", "--saida", str(rbxlx_base)])
    rc_1, _, _, _ = run_cli(["export-r15", str(spec_path), "--item", "char.e2e.hero.01", "--texturas-dir", str(tex_dir), "--no-ledger", "--saida", str(rbxlx_sock)])
    assert rc_0 == 0 and rc_1 == 0
    assert find_attachment_y(rbxlx_sock, "RightGripAttachment") - find_attachment_y(rbxlx_base, "RightGripAttachment") == pytest.approx(-0.56, abs=1e-3)


def test_tier2_sync_rojo_lua_cross_project_ledger_boundary(e2e_sandbox, run_cli) -> None:
    """F13: sync --rojo-lua excludes foreign project asset IDs; refuses unverified/tampered source."""
    pub_alpha = e2e_sandbox.dest_dir / "alpha"
    pub_beta = e2e_sandbox.dest_dir / "beta"
    glb_a, _ = write_published_asset(pub_alpha, "prop.alpha.01", projeto="alpha", perfil="roblox-r15")
    glb_b, _ = write_published_asset(pub_beta, "prop.beta.01", projeto="beta", perfil="roblox-r15")

    (e2e_sandbox.state_dir / "ledger.jsonl").write_text(
        json.dumps({"evento": "upload", "id": "prop.alpha.01", "asset_id": 111111, "asset_type": "Model", "arquivo": str(glb_a)}) + "\n"
        + json.dumps({"evento": "upload", "id": "prop.beta.01", "asset_id": 222222, "asset_type": "Model", "arquivo": str(glb_b)}) + "\n",
        encoding="utf-8",
    )

    sync_beta = e2e_sandbox.root / "sync_beta"
    e2e_sandbox.allowlist_add(sync_beta)
    lua_beta = e2e_sandbox.dest_dir / "rojo_beta" / "Assets.lua"
    rc_ok, _, _, _ = run_cli(["sync", str(pub_beta), "--para", str(sync_beta), "--rojo-lua", str(lua_beta)])
    assert rc_ok == 0
    lua_txt = lua_beta.read_text(encoding="utf-8")
    assert "222222" in lua_txt and "111111" not in lua_txt and "prop.alpha.01" not in lua_txt

    raw = bytearray(glb_b.read_bytes())
    raw[-1] ^= 0x01
    glb_b.write_bytes(bytes(raw))
    rc_tamper, _, _, pay_t = run_cli(["sync", str(pub_beta), "--para", str(sync_beta), "--rojo-lua", str(lua_beta)])
    assert rc_tamper == 3 and isinstance(pay_t, dict) and pay_t.get("erro", {}).get("codigo") == "FORGE-E-MANIFEST"


def test_tier2_upload_model_20mb_cap_refusal(e2e_sandbox, run_cli) -> None:
    """upload-model --dry-run accepts exact 20 MB (20971520 B) and refuses >20 MB with exit=5 FORGE-E-UPLOAD."""
    ok_glb = e2e_sandbox.root / "exact_20mb.glb"
    make_sparse_oversized_glb(ok_glb, size_bytes=20 * 1024 * 1024)
    rc_ok, out_ok, err_ok, pay_ok = run_cli(["upload-model", str(ok_glb), "--creator-id", "12345", "--dry-run"])
    assert rc_ok == 0, f"exact 20MB dry-run failed: {out_ok} {err_ok}"
    assert isinstance(pay_ok, dict) and pay_ok.get("ok") is True and pay_ok.get("bytes") == 20 * 1024 * 1024

    big_glb = e2e_sandbox.root / "too_big.glb"
    make_sparse_oversized_glb(big_glb, size_bytes=20 * 1024 * 1024 + 1)
    rc, _, _, payload = run_cli(["upload-model", str(big_glb), "--creator-id", "12345", "--dry-run"])
    assert rc == 5 and isinstance(payload, dict) and payload.get("erro", {}).get("codigo") == "FORGE-E-UPLOAD"
