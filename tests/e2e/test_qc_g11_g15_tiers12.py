"""Opaque-box E2E tests (Tiers 1 & 2) for FA5: QC Gates G11-G15."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.e2e._helpers_qc import (
    extract_failed_gates,
    make_silhouette_png,
    publish_qc_bundle,
    write_qc_glb,
)
from tests.e2e._helpers_roblox import R15_15_PARTS, R15_ANCHORS_DEFAULT, R15_JOINT_NAMES, R15_PARENT_MAP
from tests.e2e.conftest import RAIZ

pytestmark = pytest.mark.usefixtures("e2e_sandbox")


def _write_rbxmx(path: Path, *, nested: bool) -> Path:
    if nested:
        children_map: dict[str, list[str]] = {}
        for part, parent in R15_PARENT_MAP.items():
            children_map.setdefault(parent, []).append(part)

        id_cf = (
            '<CoordinateFrame name="CFrame"><X>0</X><Y>0</Y><Z>0</Z>'
            "<R00>1.000000</R00><R01>0.000000</R01><R02>0.000000</R02>"
            "<R10>0.000000</R10><R11>1.000000</R11><R12>0.000000</R12>"
            "<R20>0.000000</R20><R21>0.000000</R21><R22>1.000000</R22></CoordinateFrame>"
        )
        rot_x15_cf = (
            '<CoordinateFrame name="CFrame"><X>0</X><Y>0</Y><Z>0</Z>'
            "<R00>1.000000</R00><R01>0.000000</R01><R02>0.000000</R02>"
            "<R10>0.000000</R10><R11>0.965926</R11><R12>-0.258819</R12>"
            "<R20>0.000000</R20><R21>0.258819</R21><R22>0.965926</R22></CoordinateFrame>"
        )

        def _pose_xml(name: str, *, tilt_lower_torso: bool = False) -> str:
            kids = "".join(_pose_xml(ch, tilt_lower_torso=tilt_lower_torso) for ch in children_map.get(name, []))
            if name == "HumanoidRootPart":
                return (
                    '<Item class="Pose"><Properties>'
                    f'<string name="Name">HumanoidRootPart</string>{id_cf}'
                    '<float name="Weight">0</float>'
                    f"</Properties>{kids}</Item>"
                )
            cf = rot_x15_cf if (tilt_lower_torso and name == "LowerTorso") else id_cf
            return (
                '<Item class="Pose"><Properties>'
                f'<string name="Name">{name}</string>{cf}'
                '<float name="Weight">1</float>'
                '<token name="EasingStyle">1</token>'
                '<token name="EasingDirection">0</token>'
                f"</Properties>{kids}</Item>"
            )

        pose_rest = _pose_xml("HumanoidRootPart", tilt_lower_torso=False)
        pose_mid = _pose_xml("HumanoidRootPart", tilt_lower_torso=True)
        xml = (
            '<?xml version="1.0" encoding="utf-8"?><roblox version="4">'
            '<Item class="KeyframeSequence"><Properties><string name="Name">idle</string></Properties>'
            f'<Item class="Keyframe"><Properties><string name="Name">Keyframe</string><float name="Time">0</float></Properties>{pose_rest}</Item>'
            f'<Item class="Keyframe"><Properties><string name="Name">Keyframe</string><float name="Time">0.5</float></Properties>{pose_mid}</Item>'
            f'<Item class="Keyframe"><Properties><string name="Name">Keyframe</string><float name="Time">1</float></Properties>{pose_rest}</Item>'
            "</Item></roblox>"
        )
    else:
        xml = (
            '<?xml version="1.0" encoding="utf-8"?><roblox version="4">'
            '<Item class="KeyframeSequence"><Properties><string name="Name">idle</string></Properties>'
            '<Item class="Keyframe"><Properties><float name="Time">0</float></Properties>'
            '<Item class="Pose"><Properties><string name="Name">Root</string><float name="Weight">1</float></Properties></Item>'
            '<Item class="Pose"><Properties><string name="Name">Waist</string><float name="Weight">1</float></Properties></Item>'
            '</Item></Item></roblox>'
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(xml, encoding="utf-8")
    return path


def _run_visual_qa_g15_fidelity(concept_png: Path, render_png: Path) -> dict[str, Any]:
    env = {**os.environ, "PYTHONPATH": str(RAIZ / "tools")}
    code = (
        "import json; from pathlib import Path; import visual_qa_critic as c; "
        "fn = getattr(c, 'avaliar_fidelidade_concept_3d', None) or getattr(c, 'avaliar_fidelidade_g15', None); "
        "assert callable(fn), 'missing G15 concept fidelity evaluator'; "
        f"print(json.dumps(fn(Path({str(concept_png)!r}), Path({str(render_png)!r}))))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(RAIZ),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, f"visual_qa_critic G15 evaluator failed: {proc.stdout} {proc.stderr}"
    return json.loads(proc.stdout)


def _publish_two_part_r15(
    dest: Path,
    asset_id: str,
    *,
    upper_y: tuple[float, float],
    upper_anchor: list[float],
    gates: list[dict],
) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    s = 3.5714
    skin_pos = {
        "HumanoidRootPart": [0.0, 0.0, 0.0],
        "LowerTorso": [0.0, 0.0, 0.0],
        "UpperTorso": [0.0, 1.0 * s, 0.0],
        **{
            p: list(R15_ANCHORS_DEFAULT[R15_JOINT_NAMES[p]])
            for p in R15_15_PARTS
            if p not in ("LowerTorso", "UpperTorso")
        },
    }
    main_glb = write_qc_glb(
        dest / f"{asset_id}.glb",
        boxes=[((-0.5 * s, 0.0, -0.5 * s), (0.5 * s, 2.0 * s, 0.5 * s))],
        skin_mode="valid",
        skin_bones=("HumanoidRootPart", *R15_15_PARTS),
        skin_positions=skin_pos,
    )
    lower_glb = write_qc_glb(
        dest / "LowerTorso.glb",
        boxes=[((-0.4 * s, 0.0, -0.3 * s), (0.4 * s, 1.0 * s, 0.3 * s))],
        node_name="LowerTorso",
    )
    upper_glb = write_qc_glb(
        dest / "UpperTorso.glb",
        boxes=[((-0.4 * s, upper_y[0] * s, -0.3 * s), (0.4 * s, upper_y[1] * s, 0.3 * s))],
        node_name="UpperTorso",
    )
    return publish_qc_bundle(
        dest,
        asset_id,
        glb_path=main_glb,
        perfil="roblox-r15",
        tipo="personagem_humanoide",
        rota="mesh",
        bbox_m=(1.0, 2.0, 1.0),
        tris=12,
        limite_tris=8000,
        extra_files=[(lower_glb, "parte"), (upper_glb, "parte")],
        manifest_overrides={
            "unidades_export": {"metros_por_unidade": 0.28, "escala_saida": s},
            "rig": {
                "esqueleto": "r15@1",
                "ossos": 16,
                "modo": "motor6d",
                "modo_rig_roblox": "motor6d",
                "ancoras": {**R15_ANCHORS_DEFAULT, "Root": [0.0, 0.0, 0.0], "Waist": [0.0, 1.0 * s, 0.0]},
            },
            "partes": [
                {"nome": "LowerTorso", "papel": "parte", "junta": "Root", "ancora": [0.0, 0.0, 0.0], "arquivo": "LowerTorso.glb"},
                {"nome": "UpperTorso", "papel": "parte", "junta": R15_JOINT_NAMES["UpperTorso"], "ancora": [c * s for c in upper_anchor], "arquivo": "UpperTorso.glb"},
            ],
            "qc": {"aprovado": True, "gates": gates},
        },
    )


# ---------------------------------------------------------------------------
# Tier 1 — Primary Happy Paths (G11-G15)
# ---------------------------------------------------------------------------


@pytest.mark.blender
@pytest.mark.lento
def test_tier1_g11_plan_scene_budget_and_run_verify_within_budget(e2e_sandbox, run_cli, write_spec) -> None:
    """G11: multi-item spec within 80% AA budget passes plan --scene-budget, run, and verify."""
    dest = e2e_sandbox.dest_dir / "g11_ok"
    e2e_sandbox.allowlist_add(dest)
    spec = {
        "schema": "forge3d/spec@6",
        "projeto": "e2e_g11_ok",
        "perfil": "godot4-aa",
        "destino_exportacao": str(dest),
        "estilo_global": "blocky_voxel",
        "orcamento_cena": {"triangulos_max": 400000, "draw_calls_max": 400, "vram_mb_max": 200},
        "lote": [
            {"id": "prop.e2e.pillar.01", "tipo": "prop_estatico", "rota": "blocky", "prompt": "stone pillar", "altura_metros": 2.0, "pivot": "base", "limite_triangulos": 4000, "quantidade_cena": 4, "colisao": "none"},
            {"id": "prop.e2e.crate.02", "tipo": "prop_estatico", "rota": "blocky", "prompt": "wooden crate", "altura_metros": 1.0, "pivot": "base", "limite_triangulos": 2000, "quantidade_cena": 6, "colisao": "none"},
        ],
    }
    p_spec = write_spec(e2e_sandbox.root / "g11_ok.yaml", spec)

    rc_p, out_p, err_p, pay_p = run_cli(["plan", str(p_spec), "--scene-budget"])
    assert rc_p == 0, f"plan failed: {out_p} {err_p}"
    assert isinstance(pay_p, dict) and pay_p["orcamento_cena"]["id"] == "G11"
    assert pay_p["orcamento_cena"]["status"] == "ok"
    assert pay_p["orcamento_cena"]["nao_bloqueante"] is True

    rc_r, out_r, err_r, pay_r = run_cli(["run", str(p_spec)])
    assert rc_r == 0, f"run failed: {out_r} {err_r}"
    assert isinstance(pay_r, dict) and pay_r["resumo"]["publicados"] == 2
    assert pay_r["orcamento_cena"]["id"] == "G11" and pay_r["orcamento_cena"]["status"] == "ok"

    rc_v, _, _, pay_v = run_cli(["verify", str(dest)])
    assert rc_v == 0 and isinstance(pay_v, dict) and pay_v["ok"] is True


def test_tier1_g12_g13_segmented_separation_and_anchor_fit_pass(e2e_sandbox, run_cli) -> None:
    """F14 G12/G13: segmented parts within <=2mm gap and <=1mm anchor fit pass verify."""
    dest = e2e_sandbox.dest_dir / "g12_g13_ok"
    _publish_two_part_r15(
        dest,
        "char.e2e.g12ok.01",
        upper_y=(1.0005, 2.0),
        upper_anchor=[0.0, 1.0, 0.0],
        gates=[
            {"id": "G2", "status": "ok", "medido": {"esperado_m": 2.0, "pivo_regra": "base"}},
            {"id": "G9", "status": "ok", "medido": {"triangulos": 12, "limite": 8000}},
            {"id": "G12", "status": "ok", "medido": {"penetracao_max_mm": 0.0, "limite_mm": 2.0}},
            {"id": "G13", "status": "ok", "medido": {"erro_ancora_max_mm": 0.0, "limite_mm": 1.0}},
        ],
    )
    rc, out, err, pay = run_cli(["verify", str(dest)])
    assert rc == 0, f"F14 G12/G13 verify failed (rc={rc}): {out} {err} {pay}"
    assert isinstance(pay, dict) and pay["ok"] is True


def test_tier1_g14_pose_tree_and_playback_gate_pass(e2e_sandbox, run_cli) -> None:
    """F14 G14: nested Pose tree .rbxmx + Play-mode Studio harness pass verify."""
    dest = e2e_sandbox.dest_dir / "g14_ok"
    glb = write_qc_glb(dest / "char.e2e.g14ok.01.glb")
    rbxmx = _write_rbxmx(dest / "char.e2e.g14ok.01_idle.rbxmx", nested=True)
    publish_qc_bundle(
        dest,
        "char.e2e.g14ok.01",
        glb_path=glb,
        extra_files=[(rbxmx, "animacao")],
        manifest_overrides={
            "qc": {
                "aprovado": True,
                "gates": [
                    {"id": "G2", "status": "ok", "medido": {"esperado_m": 1.0, "pivo_regra": "base"}},
                    {"id": "G9", "status": "ok", "medido": {"triangulos": 12, "limite": 5000}},
                    {"id": "G14", "status": "ok", "medido": {"pose_aninhada": True}},
                ],
            }
        },
    )
    rc, out, err, pay = run_cli(["verify", str(dest)])
    assert rc == 0, f"F14 G14 verify failed: {out} {err} {pay}"
    assert isinstance(pay, dict) and pay["ok"] is True

    r15_tools = list((RAIZ / "tools").glob("*r15*.*"))
    assert any(
        "LoadAnimation" in p.read_text(encoding="utf-8", errors="ignore")
        or "G14" in p.read_text(encoding="utf-8", errors="ignore")
        for p in r15_tools
    ), "Play-mode G14 Studio harness missing from tools/*r15*.*"


def test_tier1_g15_concept_to_3d_fidelity_gate_pass(e2e_sandbox, run_cli) -> None:
    """F25 G15: matching concept/render passes visual_qa_critic fidelity & manifest@6 G15 verify."""
    dest = e2e_sandbox.dest_dir / "g15_ok"
    glb = write_qc_glb(dest / "prop.e2e.g15ok.01.glb")
    concept_png = make_silhouette_png(dest / "prop.e2e.g15ok.01_concept.png", rect=(44, 16, 84, 112))
    render_png = make_silhouette_png(e2e_sandbox.root / "prop.e2e.g15ok.01_render.png", rect=(44, 16, 84, 112))
    publish_qc_bundle(
        dest,
        "prop.e2e.g15ok.01",
        glb_path=glb,
        extra_files=[(concept_png, "concept")],
        manifest_overrides={
            "qc": {
                "aprovado": True,
                "gates": [
                    {"id": "G2", "status": "ok", "medido": {"esperado_m": 1.0, "pivo_regra": "base"}},
                    {"id": "G9", "status": "ok", "medido": {"triangulos": 12, "limite": 5000}},
                    {"id": "G15", "status": "ok", "medido": {"iou_silhueta": 1.0}},
                ],
            }
        },
    )
    rc_v, out_v, err_v, pay_v = run_cli(["verify", str(dest)])
    assert rc_v == 0, f"F25 G15 verify failed: {out_v} {err_v} {pay_v}"

    fid_res = _run_visual_qa_g15_fidelity(concept_png, render_png)
    assert fid_res["aprovado"] is True, f"matching concept/render rejected: {fid_res}"


# ---------------------------------------------------------------------------
# Tier 2 — Boundaries & Rejections (G11-G15)
# ---------------------------------------------------------------------------


@pytest.mark.blender
@pytest.mark.lento
def test_tier2_g11_scene_budget_exceeded_blocks_publish_and_fails_verify(e2e_sandbox, run_cli, write_spec) -> None:
    """G11: exceeded budget blocks publish (rc=3 FORGE-E-QC-SCENE), F07 counts partes[] draw calls, F26 verify re-checks G11."""
    dest_run = e2e_sandbox.dest_dir / "g11_exceed_run"
    e2e_sandbox.allowlist_add(dest_run)
    spec_exceed = {
        "schema": "forge3d/spec@6",
        "projeto": "e2e_g11_fail",
        "perfil": "godot4-aa",
        "destino_exportacao": str(dest_run),
        "estilo_global": "blocky_voxel",
        "orcamento_cena": {"triangulos_max": 10000, "draw_calls_max": 400, "vram_mb_max": 200},
        "lote": [
            {
                "id": "char.e2e.crowd.01", "tipo": "personagem_humanoide", "rota": "blocky",
                "prompt": "crowd knight", "altura_metros": 1.8, "pivot": "base", "limite_triangulos": 4000, "auto_rig": True,
                "esqueleto": "godot-humanoid@1", "quantidade_cena": 50, "colisao": "none",
            }
        ],
    }
    rc_r, _, _, pay_r = run_cli(["run", str(write_spec(e2e_sandbox.root / "g11_fail.yaml", spec_exceed))])
    assert rc_r == 3 and isinstance(pay_r, dict)
    assert pay_r["orcamento_cena"]["status"] == "falhou"
    assert pay_r["orcamento_cena"]["codigo"] == "FORGE-E-QC-SCENE"
    assert pay_r.get("erro", {}).get("codigo") == "FORGE-E-QC-SCENE"
    assert not dest_run.exists() or list(dest_run.iterdir()) == []

    # F07: segmented 15-part item * 30 instances = 450 draw calls > 400
    spec_seg = {
        "schema": "forge3d/spec@6",
        "projeto": "e2e_g11_seg_dc",
        "perfil": "roblox-r15",
        "destino_exportacao": str(e2e_sandbox.dest_dir / "g11_seg"),
        "estilo_global": "blocky_voxel",
        "orcamento_cena": {"triangulos_max": 400000, "draw_calls_max": 400, "vram_mb_max": 200},
        "lote": [
            {
                "id": "char.e2e.army.01", "tipo": "personagem_humanoide", "rota": "mesh", "seed": 123,
                "prompt": "segmented army guard", "altura_metros": 1.8, "pivot": "base", "limite_triangulos": 8000, "auto_rig": True,
                "esqueleto": "r15@1", "partes": [{"nome": p} for p in R15_15_PARTS],
                "rig": {"modo": "motor6d", "esqueleto": "r15@1"}, "quantidade_cena": 30,
            }
        ],
    }
    rc_p, _, _, pay_p = run_cli(["plan", str(write_spec(e2e_sandbox.root / "g11_seg.yaml", spec_seg)), "--scene-budget"])
    assert rc_p == 0 and isinstance(pay_p, dict)
    assert pay_p["orcamento_cena"]["status"] == "falhou"

    # F26: verify re-evaluates G11 scene budget (84 boxes = 1008 tris * 500 = 504,000 > 400,000)
    d_ver = e2e_sandbox.dest_dir / "g11_verify_fail"
    boxes = [((-0.5 + (i % 7) * 0.1, (i // 42) * 0.2, -0.5 + ((i // 7) % 6) * 0.1), (-0.42 + (i % 7) * 0.1, (i // 42) * 0.2 + 0.15, -0.42 + ((i // 7) % 6) * 0.1)) for i in range(84)]
    boxes[0] = ((-0.5, 0.0, -0.5), (-0.42, 0.15, -0.42))
    boxes[-1] = ((0.42, 0.85, 0.42), (0.5, 1.0, 0.5))
    big_glb = write_qc_glb(d_ver / "prop.e2e.swarm.01.glb", boxes=boxes)
    publish_qc_bundle(
        d_ver, "prop.e2e.swarm.01", glb_path=big_glb, tris=1008, limite_tris=5000,
        manifest_overrides={
            "quantidade_cena": 500,
            "orcamento_cena": {"triangulos_max": 400000, "draw_calls_max": 400, "vram_mb_max": 200},
        },
    )
    rc_v, _, _, pay_v = run_cli(["verify", str(d_ver)])
    assert rc_v == 3 and (
        "G11" in extract_failed_gates(pay_v) or "FORGE-E-QC-SCENE" in json.dumps(pay_v)
    )


def test_tier2_g12_part_separation_gt_2mm_rejected(e2e_sandbox, run_cli) -> None:
    """F14 G12: >2mm interpenetration between segmented R15 parts fails verify with G12."""
    dest = e2e_sandbox.dest_dir / "g12_overlap_fail"
    _publish_two_part_r15(
        dest,
        "char.e2e.g12fail.01",
        upper_y=(0.90, 1.90),
        upper_anchor=[0.0, 1.0, 0.0],
        gates=[
            {"id": "G2", "status": "ok", "medido": {"esperado_m": 2.0, "pivo_regra": "base"}},
            {"id": "G9", "status": "ok", "medido": {"triangulos": 12, "limite": 8000}},
            {"id": "G12", "status": "ok", "medido": {"penetracao_max_mm": 0.0, "limite_mm": 2.0}},
        ],
    )
    rc, _, _, pay = run_cli(["verify", str(dest)])
    assert rc == 3 and "G12" in extract_failed_gates(pay)


def test_tier2_g13_anchor_fit_gt_1mm_rejected(e2e_sandbox, run_cli) -> None:
    """F14 G13: >1mm anchor mismatch re-evaluated in verify fails with G13."""
    dest = e2e_sandbox.dest_dir / "g13_anchor_fail"
    _publish_two_part_r15(
        dest,
        "char.e2e.g13fail.01",
        upper_y=(1.0005, 2.0),
        upper_anchor=[0.0, 1.01, 0.0],
        gates=[
            {"id": "G2", "status": "ok", "medido": {"esperado_m": 2.0, "pivo_regra": "base"}},
            {"id": "G9", "status": "ok", "medido": {"triangulos": 12, "limite": 8000}},
            {"id": "G13", "status": "ok", "medido": {"erro_ancora_max_mm": 0.0, "limite_mm": 1.0}},
        ],
    )
    rc, _, _, pay = run_cli(["verify", str(dest)])
    assert rc == 3 and "G13" in extract_failed_gates(pay)


def test_tier2_g14_flat_pose_tree_rejected(e2e_sandbox, run_cli) -> None:
    """F14 G14: flat unnested Pose tree in .rbxmx fails verify with G14."""
    dest = e2e_sandbox.dest_dir / "g14_flat_fail"
    glb = write_qc_glb(dest / "char.e2e.g14fail.01.glb")
    rbxmx = _write_rbxmx(dest / "char.e2e.g14fail.01_idle.rbxmx", nested=False)
    publish_qc_bundle(
        dest,
        "char.e2e.g14fail.01",
        glb_path=glb,
        extra_files=[(rbxmx, "animacao")],
        manifest_overrides={
            "qc": {
                "aprovado": True,
                "gates": [
                    {"id": "G2", "status": "ok", "medido": {"esperado_m": 1.0, "pivo_regra": "base"}},
                    {"id": "G9", "status": "ok", "medido": {"triangulos": 12, "limite": 5000}},
                    {"id": "G14", "status": "ok", "medido": {"pose_aninhada": True}},
                ],
            }
        },
    )
    rc, _, _, pay = run_cli(["verify", str(dest)])
    assert rc == 3 and "G14" in extract_failed_gates(pay)


def test_tier2_g15_low_concept_fidelity_rejected(e2e_sandbox, run_cli) -> None:
    """F25 G15: mismatched concept vs render fails visual_qa_critic fidelity & verify G15."""
    dest = e2e_sandbox.dest_dir / "g15_fail"
    glb = write_qc_glb(dest / "prop.e2e.g15fail.01.glb")
    concept_png = make_silhouette_png(
        dest / "prop.e2e.g15fail.01_concept.png", rect=(52, 16, 76, 112), fg_rgba=(220, 30, 30, 255)
    )
    render_png = make_silhouette_png(
        e2e_sandbox.root / "prop.e2e.g15fail.01_render.png", rect=(12, 56, 116, 72), fg_rgba=(30, 60, 220, 255)
    )
    fid_res = _run_visual_qa_g15_fidelity(concept_png, render_png)
    assert fid_res["aprovado"] is False, f"expected fidelity fail (aprovado=False), got {fid_res}"

    publish_qc_bundle(
        dest,
        "prop.e2e.g15fail.01",
        glb_path=glb,
        extra_files=[(concept_png, "concept")],
        manifest_overrides={
            "qc": {
                "aprovado": False,
                "gates": [
                    {"id": "G2", "status": "ok", "medido": {"esperado_m": 1.0, "pivo_regra": "base"}},
                    {"id": "G9", "status": "ok", "medido": {"triangulos": 12, "limite": 5000}},
                    {"id": "G15", "status": "falhou", "codigo": "FORGE-E-QC", "medido": {"iou_silhueta": 0.12}},
                ],
            }
        },
    )
    rc_v, _, _, pay_v = run_cli(["verify", str(dest)])
    assert rc_v == 3 and isinstance(pay_v, dict) and pay_v.get("ok") is False
    errs = pay_v.get("erros") or []
    assert errs and not any(e.get("erro") == "schema" for e in errs)
    assert "G15" in extract_failed_gates(pay_v) or any(
        "sem QC aprovado" in str(e.get("erro", "")) for e in errs
    )
