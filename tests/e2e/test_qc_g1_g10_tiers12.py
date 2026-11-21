"""Opaque-box E2E tests (Tiers 1 & 2) for FA5: QC Gates G1-G10 & R5 Blind Spots."""

from __future__ import annotations

import json

import pytest

from tests.e2e._helpers_qc import (
    build_box_mesh,
    extract_failed_gates,
    publish_qc_bundle,
    write_hemisphere_normal_png,
    write_qc_glb,
)

pytestmark = pytest.mark.usefixtures("e2e_sandbox")


# ---------------------------------------------------------------------------
# Tier 1 — Primary Happy Paths (Blender run + pure-Python verify)
# ---------------------------------------------------------------------------


@pytest.mark.blender
@pytest.mark.rapido
def test_tier1_qc_g1_g10_blocky_and_import_run_happy_path(e2e_sandbox, run_cli, write_spec, make_minimal_glb) -> None:
    """blocky (godot4-aa rigged) and import (roblox-r15) pass G1-G10 during run & verify."""
    src_glb = make_minimal_glb(e2e_sandbox.root / "crate.glb", size_xyz=(1.0, 1.0, 1.0))
    dest = e2e_sandbox.dest_dir / "happy_g1_g10"
    e2e_sandbox.allowlist_add(dest)

    spec_g = {
        "schema": "forge3d/spec@6",
        "projeto": "e2e_qc_t1",
        "perfil": "godot4-aa",
        "destino_exportacao": str(dest),
        "estilo_global": "blocky_voxel",
        "lote": [
            {
                "id": "char.e2e.qc.01",
                "tipo": "personagem_humanoide",
                "rota": "blocky",
                "prompt": "stylized blocky knight",
                "altura_metros": 1.8,
                "pivot": "base",
                "limite_triangulos": 8000,
                "auto_rig": True,
                "esqueleto": "godot-humanoid@1",
                "animacoes_base": ["idle"],
                "colisao": "convex",
            }
        ],
    }
    rc, out, err, pay = run_cli(["run", str(write_spec(e2e_sandbox.root / "qc_godot.yaml", spec_g))])
    assert rc == 0, f"blocky godot4-aa run failed: {out} {err}"
    assert isinstance(pay, dict) and pay["resumo"]["publicados"] == 1
    man = json.loads((dest / "char.e2e.qc.01.manifest.json").read_text(encoding="utf-8"))
    assert man["schema"] == "forge3d/manifest@7"
    assert man["qc"]["aprovado"] is True
    gate_ids = {g["id"] for g in man["qc"]["gates"]}
    assert {"G1", "G2", "G3", "G4", "G5", "G6", "G7", "G8", "G9", "G10"} <= gate_ids
    assert all(g["status"] in ("ok", "warn") for g in man["qc"]["gates"])

    dest_rbx = e2e_sandbox.dest_dir / "happy_rbx"
    e2e_sandbox.allowlist_add(dest_rbx)
    spec_r = {
        "schema": "forge3d/spec@6",
        "projeto": "e2e_qc_t1_rbx",
        "perfil": "roblox-r15",
        "destino_exportacao": str(dest_rbx),
        "estilo_global": "blocky_voxel",
        "lote": [
            {
                "id": "prop.e2e.crate.01",
                "tipo": "prop_estatico",
                "rota": "import",
                "origem": str(src_glb),
                "altura_metros": 1.0,
                "pivot": "base",
                "limite_triangulos": 1000,
                "colisao": "none",
            }
        ],
    }
    rc2, out2, err2, pay2 = run_cli(["run", str(write_spec(e2e_sandbox.root / "qc_rbx.yaml", spec_r))])
    assert rc2 == 0, f"import roblox-r15 run failed: {out2} {err2}"
    assert isinstance(pay2, dict) and pay2["resumo"]["publicados"] == 1

    rc_v1, _, _, pay_v1 = run_cli(["verify", str(dest)])
    rc_v2, _, _, pay_v2 = run_cli(["verify", str(dest_rbx)])
    assert rc_v1 == 0 and isinstance(pay_v1, dict) and pay_v1["ok"] is True
    assert rc_v2 == 0 and isinstance(pay_v2, dict) and pay_v2["ok"] is True


@pytest.mark.blender
@pytest.mark.rapido
def test_tier1_qc_g1_alpha_cards_allows_open_borders_without_t_edges(e2e_sandbox, run_cli, write_spec) -> None:
    """alpha_cards=true passes G1 on an open quad (bordas_abertas>0, arestas_t==0) and rejects T-edges."""
    quad_glb = e2e_sandbox.root / "foliage_quad.glb"
    write_qc_glb(
        quad_glb,
        verts=[(-0.25, 0.0, 0.0), (0.25, 0.0, 0.0), (0.25, 1.0, 0.0), (-0.25, 1.0, 0.0)],
        normals=[(0.0, 0.0, 1.0)] * 4,
        uvs=[(0.1, 0.1), (0.9, 0.1), (0.9, 0.9), (0.1, 0.9)],
        tris=[(0, 1, 2), (0, 2, 3)],
        node_name="FoliageCard",
    )
    dest = e2e_sandbox.dest_dir / "alpha_ok"
    e2e_sandbox.allowlist_add(dest)
    spec = {
        "schema": "forge3d/spec@6",
        "projeto": "e2e_alpha",
        "perfil": "godot4",
        "destino_exportacao": str(dest),
        "estilo_global": "blocky_voxel",
        "lote": [
            {
                "id": "prop.e2e.leaf.01",
                "tipo": "prop_estatico",
                "rota": "import",
                "origem": str(quad_glb),
                "alpha_cards": True,
                "altura_metros": 1.0,
                "pivot": "base",
                "limite_triangulos": 100,
                "colisao": "none",
            }
        ],
    }
    rc, out, err, pay = run_cli(["run", str(write_spec(e2e_sandbox.root / "alpha.yaml", spec))])
    assert rc == 0, f"alpha_cards run failed: {out} {err}"
    assert isinstance(pay, dict) and pay["resumo"]["publicados"] == 1
    man = json.loads((dest / "prop.e2e.leaf.01.manifest.json").read_text(encoding="utf-8"))
    g1 = next(g for g in man["qc"]["gates"] if g["id"] == "G1")
    assert g1["status"] == "ok" and g1["medido"]["alpha_cards"] is True
    assert g1["medido"]["bordas_abertas"] == 4 and g1["medido"]["arestas_t"] == 0

    # Paired negative boundary: T-edge with alpha_cards=True must still fail ONLY G1 (centered in XZ, disjoint UVs)
    t_dest = e2e_sandbox.dest_dir / "alpha_tedge"
    p0, p1, p2, p3, p4 = (-0.5, 0.0, -0.25), (0.5, 0.0, -0.25), (0.5, 1.0, -0.25), (-0.5, 1.0, -0.25), (0.0, 0.5, 0.25)
    t_glb = write_qc_glb(
        t_dest / "prop.e2e.tedge.01.glb",
        verts=[p0, p1, p2, p0, p1, p3, p0, p1, p4],
        normals=[(0.0, 0.0, 1.0)] * 9,
        uvs=[
            (0.05, 0.05), (0.30, 0.05), (0.30, 0.90),
            (0.35, 0.05), (0.60, 0.05), (0.35, 0.90),
            (0.65, 0.05), (0.90, 0.05), (0.775, 0.90),
        ],
        tris=[(0, 1, 2), (3, 4, 5), (6, 7, 8)],
    )
    publish_qc_bundle(
        t_dest, "prop.e2e.tedge.01", glb_path=t_glb, bbox_m=(1.0, 1.0, 0.5), tris=3,
        manifest_overrides={"alpha_cards": True},
    )
    rc_t, _, _, pay_t = run_cli(["verify", str(t_dest)])
    assert rc_t == 3 and extract_failed_gates(pay_t) == {"G1"}


def test_tier1_qc_g1_g10_verify_all_gates_manifest_v6(e2e_sandbox, run_cli) -> None:
    """Pure-Python verify re-executes G1-G10 cleanly on a compliant synthetic manifest@6 bundle."""
    dest = e2e_sandbox.dest_dir / "verify_ok"
    glb = write_qc_glb(dest / "prop.e2e.valid.01.glb", boxes=[((-0.5, 0.0, -0.5), (0.5, 1.0, 0.5))])
    publish_qc_bundle(dest, "prop.e2e.valid.01", glb_path=glb, bbox_m=(1.0, 1.0, 1.0), tris=12)
    rc, out, err, pay = run_cli(["verify", str(dest)])
    assert rc == 0, f"verify failed: {out} {err}"
    assert isinstance(pay, dict) and pay["ok"] is True
    assert pay["itens"][0]["qc_reexecutado"] is True


# ---------------------------------------------------------------------------
# Tier 2 — R5 Blind Spots & Boundary Rejections (Pure-Python `verify`)
# ---------------------------------------------------------------------------


def test_tier2_g1_open_mesh_inverted_winding_rejected(e2e_sandbox, run_cli) -> None:
    """R5/F26 G1: open mesh with inverted winding on front face must fail G1."""
    dest = e2e_sandbox.dest_dir / "g1_open_winding"
    v, n, uv, t = build_box_mesh((-0.5, 0.0, -0.5), (0.5, 1.0, 0.5), omit_back=True, flip_front=True)
    glb = write_qc_glb(dest / "prop.e2e.openwind.01.glb", verts=v, normals=n, uvs=uv, tris=t)
    publish_qc_bundle(
        dest, "prop.e2e.openwind.01", glb_path=glb, tris=len(t),
        manifest_overrides={"alpha_cards": True},
    )
    rc, _, _, pay = run_cli(["verify", str(dest)])
    assert rc == 3 and "G1" in extract_failed_gates(pay)


def test_tier2_g2_skinned_character_facing_plus_z_rejected(e2e_sandbox, run_cli) -> None:
    """R5/F26 G2: skinned humanoid with feet facing +Z (backwards) must fail G2."""
    dest = e2e_sandbox.dest_dir / "g2_skinned_plusz"
    glb = write_qc_glb(
        dest / "char.e2e.backwards.01.glb",
        boxes=[
            ((-0.25, 0.12, -0.15), (0.25, 1.80, 0.15)),
            ((-0.20, 0.00, 0.15), (0.20, 0.10, 0.30)),
            ((-0.20, 0.60, -0.30), (0.20, 1.50, -0.10)),
        ],
        subdiv=6,
        skin_mode="valid",
        anim_mode="valid",
    )
    publish_qc_bundle(
        dest,
        "char.e2e.backwards.01",
        glb_path=glb,
        tipo="personagem_humanoide",
        bbox_m=(0.5, 1.8, 0.6),
        tris=1296,
        limite_tris=8000,
        manifest_overrides={
            "rig": {"esqueleto": "godot-humanoid@1", "ossos": 23},
            "animacoes": [{"nome": "idle", "duracao_s": 1.0, "ossos": ["Hips", "Spine"]}],
        },
    )
    rc, _, _, pay = run_cli(["verify", str(dest)])
    assert rc == 3 and "G2" in extract_failed_gates(pay)


def test_tier2_g3_uv_overlap_zero_area_and_oob_rejected(e2e_sandbox, run_cli) -> None:
    """G3: OOB UVs (GREEN) + R5/F26 overlapping UV islands & per-triangle zero-area UVs fail G3."""
    d_oob = e2e_sandbox.dest_dir / "g3_oob"
    g_oob = write_qc_glb(d_oob / "prop.e2e.oob.01.glb", uv_mode="oob")
    publish_qc_bundle(d_oob, "prop.e2e.oob.01", glb_path=g_oob)
    rc_oob, _, _, pay_oob = run_cli(["verify", str(d_oob)])
    assert rc_oob == 3 and "G3" in extract_failed_gates(pay_oob)

    d_ovl = e2e_sandbox.dest_dir / "g3_overlap"
    g_ovl = write_qc_glb(d_ovl / "prop.e2e.ovl.01.glb", uv_mode="overlap")
    publish_qc_bundle(d_ovl, "prop.e2e.ovl.01", glb_path=g_ovl)
    rc_ovl, _, _, pay_ovl = run_cli(["verify", str(d_ovl)])
    assert rc_ovl == 3 and "G3" in extract_failed_gates(pay_ovl)

    d_zero = e2e_sandbox.dest_dir / "g3_zero"
    g_zero = write_qc_glb(
        d_zero / "prop.e2e.zerouv.01.glb",
        verts=[
            (-0.5, 0.0, 0.0), (0.0, 0.0, 0.0), (-0.25, 1.0, 0.0),
            (0.1, 0.0, 0.0), (0.5, 0.0, 0.0), (0.3, 1.0, 0.0),
        ],
        normals=[(0.0, 0.0, 1.0)] * 6,
        uvs=[(0.1, 0.1), (0.9, 0.1), (0.5, 0.9), (0.5, 0.5), (0.5, 0.5), (0.5, 0.5)],
        tris=[(0, 1, 2), (3, 4, 5)],
    )
    publish_qc_bundle(
        d_zero, "prop.e2e.zerouv.01", glb_path=g_zero, tris=2,
        manifest_overrides={"alpha_cards": True},
    )
    rc_z, _, _, pay_z = run_cli(["verify", str(d_zero)])
    assert rc_z == 3 and "G3" in extract_failed_gates(pay_z)


def test_tier2_g4_non_pot_low_res_bad_crc_and_directx_normal_rejected(e2e_sandbox, run_cli) -> None:
    """G4: non-POT & bad CRC (GREEN) + R5/F26 <min_res (4x4) & DirectX -Y normal fail G4."""
    d_npot = e2e_sandbox.dest_dir / "g4_npot"
    g_npot = write_qc_glb(d_npot / "prop.e2e.npot.01.glb", png_wh=(48, 48))
    publish_qc_bundle(d_npot, "prop.e2e.npot.01", glb_path=g_npot)
    rc_npot, _, _, pay_npot = run_cli(["verify", str(d_npot)])
    assert rc_npot == 3 and "G4" in extract_failed_gates(pay_npot)

    d_crc = e2e_sandbox.dest_dir / "g4_crc"
    g_crc = write_qc_glb(d_crc / "prop.e2e.crc.01.glb", png_wh=(64, 64), corrupt_png_crc=True)
    publish_qc_bundle(d_crc, "prop.e2e.crc.01", glb_path=g_crc)
    rc_crc, _, _, pay_crc = run_cli(["verify", str(d_crc)])
    assert rc_crc == 3 and "G4" in extract_failed_gates(pay_crc)

    d_low = e2e_sandbox.dest_dir / "g4_lowres"
    g_low = write_qc_glb(d_low / "prop.e2e.lowres.01.glb", png_wh=(4, 4))
    publish_qc_bundle(d_low, "prop.e2e.lowres.01", glb_path=g_low)
    rc_low, _, _, pay_low = run_cli(["verify", str(d_low)])
    assert rc_low == 3 and "G4" in extract_failed_gates(pay_low)

    d_gl = e2e_sandbox.dest_dir / "g4_gl_normal"
    g_gl = write_qc_glb(d_gl / "prop.e2e.gln.01.glb", png_wh=(256, 256), with_tangents=True)
    n_gl = write_hemisphere_normal_png(d_gl / "prop.e2e.gln.01_normal.png", width=256, height=256, opengl_y=True)
    publish_qc_bundle(d_gl, "prop.e2e.gln.01", glb_path=g_gl, extra_files=[(n_gl, "normal")])
    rc_gl, out_gl, err_gl, pay_gl = run_cli(["verify", str(d_gl)])
    assert rc_gl == 0, f"OpenGL +Y hemisphere normal failed verify: {out_gl} {err_gl} {pay_gl}"

    d_dx = e2e_sandbox.dest_dir / "g4_dx_normal"
    g_dx = write_qc_glb(d_dx / "prop.e2e.dxn.01.glb", png_wh=(256, 256), with_tangents=True)
    n_dx = write_hemisphere_normal_png(d_dx / "prop.e2e.dxn.01_normal.png", width=256, height=256, opengl_y=False)
    publish_qc_bundle(d_dx, "prop.e2e.dxn.01", glb_path=g_dx, extra_files=[(n_dx, "normal")])
    rc_dx, _, _, pay_dx = run_cli(["verify", str(d_dx)])
    assert rc_dx == 3 and "G4" in extract_failed_gates(pay_dx)


def test_tier2_g5_untextured_clay_rejected_on_pbr_material(e2e_sandbox, run_cli) -> None:
    """R5/F26 G5: untextured clay GLB (`baseColorFactor` only) with PBR zones/detail fails G5."""
    dest = e2e_sandbox.dest_dir / "g5_clay"
    glb = write_qc_glb(dest / "prop.e2e.clay.01.glb", with_material=True, with_texture=False)
    publish_qc_bundle(
        dest, "prop.e2e.clay.01", glb_path=glb,
        manifest_overrides={"pbr_zonas": [{"nome": "clay", "preset": "aco_forjado"}], "detalhe_alto": {"ativo": True}},
    )
    rc, _, _, pay = run_cli(["verify", str(dest)])
    assert rc == 3 and "G5" in extract_failed_gates(pay)


def test_tier2_g6_100pct_root_and_zero_weight_skin_rejected(e2e_sandbox, run_cli) -> None:
    """G6: zero-weight skinning (GREEN) + R5/F26 100% root-bone binding fail G6."""
    d_zero = e2e_sandbox.dest_dir / "g6_zero"
    g_zero = write_qc_glb(d_zero / "char.e2e.zerow.01.glb", boxes=[((-0.25, 0.0, -0.15), (0.25, 1.8, 0.15))], skin_mode="zero_weight")
    publish_qc_bundle(
        d_zero, "char.e2e.zerow.01", glb_path=g_zero, tipo="personagem_humanoide",
        bbox_m=(0.5, 1.8, 0.3), limite_tris=8000,
        manifest_overrides={"rig": {"esqueleto": "godot-humanoid@1", "ossos": 23}},
    )
    rc_z, _, _, pay_z = run_cli(["verify", str(d_zero)])
    assert rc_z == 3 and "G6" in extract_failed_gates(pay_z)

    d_root = e2e_sandbox.dest_dir / "g6_root"
    g_root = write_qc_glb(d_root / "char.e2e.rootw.01.glb", boxes=[((-0.25, 0.0, -0.15), (0.25, 1.8, 0.15))], skin_mode="root_only")
    publish_qc_bundle(
        d_root, "char.e2e.rootw.01", glb_path=g_root, tipo="personagem_humanoide",
        bbox_m=(0.5, 1.8, 0.3), limite_tris=8000,
        manifest_overrides={"rig": {"esqueleto": "godot-humanoid@1", "ossos": 23}},
    )
    rc_r, _, _, pay_r = run_cli(["verify", str(d_root)])
    assert rc_r == 3 and "G6" in extract_failed_gates(pay_r)


def test_tier2_g9_missing_mandatory_lod_or_lod_missing_uv_skin_rejected(e2e_sandbox, run_cli) -> None:
    """R5/F26 G9: missing declared LOD1 file or LOD1 stripped of UV/skin fails G9."""
    d_miss = e2e_sandbox.dest_dir / "g9_miss_lod"
    g0 = write_qc_glb(d_miss / "char.e2e.lodm.01.glb", boxes=[((-0.3, 0.0, -0.2), (0.3, 1.8, 0.2))], subdiv=2, skin_mode="valid")
    publish_qc_bundle(
        d_miss, "char.e2e.lodm.01", glb_path=g0, tipo="personagem_humanoide",
        bbox_m=(0.6, 1.8, 0.4), tris=48, limite_tris=8000,
        manifest_overrides={
            "rig": {"esqueleto": "godot-humanoid@1", "ossos": 23},
            "lod": [
                {"nivel": 0, "triangulos": 48, "arquivo": "char.e2e.lodm.01.glb"},
                {"nivel": 1, "triangulos": 12, "arquivo": "char.e2e.lodm.01_LOD1.glb"},
            ],
        },
    )
    rc_m, _, _, pay_m = run_cli(["verify", str(d_miss)])
    assert rc_m == 3 and "G9" in extract_failed_gates(pay_m)

    d_bad = e2e_sandbox.dest_dir / "g9_bad_lod1"
    g0b = write_qc_glb(d_bad / "char.e2e.lodb.01.glb", boxes=[((-0.3, 0.0, -0.2), (0.3, 1.8, 0.2))], subdiv=2, skin_mode="valid")
    g1b = write_qc_glb(
        d_bad / "char.e2e.lodb.01_LOD1.glb",
        boxes=[((-0.3, 0.0, -0.2), (0.3, 1.8, 0.2))], subdiv=1, with_uv=False, with_texture=False, skin_mode=None,
    )
    publish_qc_bundle(
        d_bad, "char.e2e.lodb.01", glb_path=g0b, tipo="personagem_humanoide",
        bbox_m=(0.6, 1.8, 0.4), tris=48, limite_tris=8000,
        extra_files=[(g1b, "lod")],
        manifest_overrides={
            "rig": {"esqueleto": "godot-humanoid@1", "ossos": 23},
            "lod": [
                {"nivel": 0, "triangulos": 48, "arquivo": "char.e2e.lodb.01.glb"},
                {"nivel": 1, "triangulos": 12, "arquivo": "char.e2e.lodb.01_LOD1.glb"},
            ],
        },
    )
    rc_b, _, _, pay_b = run_cli(["verify", str(d_bad)])
    assert rc_b == 3 and "G9" in extract_failed_gates(pay_b)


def test_tier2_g10_tiny_amplitude_and_unclosed_loop_anim_rejected(e2e_sandbox, run_cli) -> None:
    """R5/F26 G10: cyclic clip with <5 deg amplitude or >3 deg loop gap fails G10."""
    for suffix, mode in (("tiny_amp", "tiny_amp"), ("unclosed_loop", "unclosed_loop")):
        dest = e2e_sandbox.dest_dir / f"g10_{suffix}"
        glb = write_qc_glb(
            dest / f"char.e2e.{suffix}.01.glb",
            boxes=[((-0.25, 0.0, -0.15), (0.25, 1.8, 0.15))],
            skin_mode="valid",
            anim_mode=mode,
        )
        publish_qc_bundle(
            dest, f"char.e2e.{suffix}.01", glb_path=glb, tipo="personagem_humanoide",
            bbox_m=(0.5, 1.8, 0.3), limite_tris=8000,
            manifest_overrides={
                "rig": {"esqueleto": "godot-humanoid@1", "ossos": 23},
                "animacoes": [{"nome": "idle", "duracao_s": 1.0, "ossos": ["Hips", "Spine"]}],
            },
        )
        rc, _, _, pay = run_cli(["verify", str(dest)])
        assert rc == 3 and "G10" in extract_failed_gates(pay), f"{suffix} did not fail G10 (rc={rc}, pay={pay})"
