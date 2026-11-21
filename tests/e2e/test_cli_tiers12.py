"""FA1 CLI lifecycle & error-boundary opaque-box E2E tests (Tiers 1 & 2)."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.e2e.conftest import build_minimal_png_bytes


def _minimal_spec6(dest_dir: Path, *, projeto: str = "e2e_cli") -> dict[str, Any]:
    return {
        "schema": "forge3d/spec@6",
        "projeto": projeto,
        "perfil": "godot4",
        "destino_exportacao": str(dest_dir),
        "estilo_global": "blocky_voxel",
        "paleta": ["#7d858f", "#3b4048", "#ff6a1f"],
        "orcamento_cena": {
            "triangulos_max": 400000,
            "draw_calls_max": 400,
            "vram_mb_max": 200,
        },
        "lote": [
            {
                "id": "prop.crate.cli.01",
                "tipo": "prop_estatico",
                "rota": "blocky",
                "prompt": "Wooden supply crate with iron bands",
                "altura_metros": 0.40,
                "pivot": "base",
                "limite_triangulos": 400,
                "colisao": "box",
                "lod": [100],
                "quantidade_cena": 2,
                "tags": ["prop", "cli"],
            }
        ],
    }


def _minimal_r15_spec(dest_dir: Path) -> dict[str, Any]:
    return {
        "schema": "forge3d/spec@6",
        "projeto": "e2e_r15",
        "perfil": "roblox-r15",
        "destino_exportacao": str(dest_dir),
        "estilo_global": "blocky_voxel",
        "paleta": ["#5b7c99", "#34495e", "#d4af37"],
        "lote": [
            {
                "id": "char.guard.cli.01",
                "tipo": "personagem_humanoide",
                "rota": "blocky",
                "prompt": "Voxel guard hero with dark cloak",
                "altura_metros": 1.85,
                "pivot": "base",
                "limite_triangulos": 3000,
                "auto_rig": True,
                "esqueleto": "r15@1",
                "animacoes_base": ["idle"],
                "tags": ["hero", "r15"],
            }
        ],
    }


# ---------------------------------------------------------------------------
# Tier 1: Primary CLI lifecycle contracts (happy path)
# ---------------------------------------------------------------------------


def test_tier1_validate_and_plan_scene_budget_json(e2e_sandbox, write_spec) -> None:
    spec_path = write_spec(e2e_sandbox.root / "lote_cli.yaml", _minimal_spec6(e2e_sandbox.dest_dir))

    rc_val, _, err_val, val = e2e_sandbox.run_cli(["validate", str(spec_path)])
    assert rc_val == 0, err_val
    assert isinstance(val, dict)
    assert val["ok"] is True
    assert val["projeto"] == "e2e_cli"
    assert val["perfil"] == "godot4"
    assert val["itens"] == 1

    rc_plan, _, err_plan, plan = e2e_sandbox.run_cli(["plan", str(spec_path), "--scene-budget"])
    assert rc_plan == 0, err_plan
    assert isinstance(plan, dict)
    assert plan["schema"] == "forge3d/report@1"
    assert plan["comando"] == "plan"
    assert plan["exit"] == 0
    assert plan["plano"]["total"] == 1
    assert plan["plano"]["a_executar"] == 1
    assert plan["tarefas"][0]["rota"] == "blocky"
    budget = plan["orcamento_cena"]
    assert budget["nao_bloqueante"] is True
    assert budget["status"] == "ok"
    assert budget["estimativa"]["triangulos_cena"] > 0
    assert budget["estimativa"]["draw_calls_estimados"] >= 1
    assert budget["teto_pior_caso"]["triangulos_cena"] >= budget["estimativa"]["triangulos_cena"]
    assert not e2e_sandbox.dest_dir.exists()


def test_tier1_migrate_spec1_to_spec6_json(e2e_sandbox, write_spec) -> None:
    spec1 = _minimal_spec6(e2e_sandbox.dest_dir)
    spec1["schema"] = "forge3d/spec@1"
    spec1.pop("orcamento_cena", None)
    spec1["lote"][0].pop("quantidade_cena", None)
    src_path = write_spec(e2e_sandbox.root / "spec_v1.yaml", spec1)

    rc_dry, _, err_dry, dry = e2e_sandbox.run_cli(["migrate", str(src_path)])
    assert rc_dry == 0, err_dry
    assert isinstance(dry, dict)
    assert dry["de"] == "forge3d/spec@1"
    assert dry["para"] == "forge3d/spec@6"
    assert dry["valido"] is True
    assert dry["escrito"] is None
    assert len(dry["mudancas"]) >= 1

    out_path = e2e_sandbox.root / "spec_v6.yaml"
    rc_out, _, err_out, written = e2e_sandbox.run_cli(["migrate", str(src_path), "--saida", str(out_path)])
    assert rc_out == 0, err_out
    assert isinstance(written, dict) and written["escrito"] == str(out_path)
    migrated = yaml.safe_load(out_path.read_text(encoding="utf-8"))
    assert migrated["schema"] == "forge3d/spec@6"


def test_tier1_export_r15_json(e2e_sandbox, write_spec) -> None:
    spec_path = write_spec(e2e_sandbox.root / "lote_r15.yaml", _minimal_r15_spec(e2e_sandbox.dest_dir))
    out_rbxlx = e2e_sandbox.dest_dir / "char_guard.rbxlx"

    rc, _, err, payload = e2e_sandbox.run_cli(
        ["export-r15", str(spec_path), "--item", "char.guard.cli.01", "--saida", str(out_rbxlx)]
    )
    assert rc == 0, err
    assert isinstance(payload, dict)
    assert payload["ok"] is True
    assert payload["partes"] == 16
    assert payload["motores"] == 15
    assert payload["modo_rig"] == "motor6d"
    assert payload["metros_por_stud"] == pytest.approx(0.28)
    assert "idle" in payload["animacoes"]
    assert out_rbxlx.is_file()
    root_xml = ET.fromstring(out_rbxlx.read_text(encoding="utf-8"))
    assert root_xml.tag == "roblox"


def test_tier1_upload_model_dry_run_json(e2e_sandbox, make_minimal_glb) -> None:
    glb_path = make_minimal_glb(e2e_sandbox.root / "crate.glb")

    rc, _, err, payload = e2e_sandbox.run_cli(
        [
            "upload-model",
            str(glb_path),
            "--creator-id",
            "12345",
            "--nome",
            "DemoCrate",
            "--dry-run",
        ]
    )
    assert rc == 0, err
    assert isinstance(payload, dict)
    assert payload["ok"] is True
    assert payload["dry_run"] is True
    assert payload["content_type"] == "model/gltf-binary"
    assert payload["asset_type"] == "Model"
    assert payload["creator"] == {"userId": "12345"}
    assert payload["request"]["displayName"] == "DemoCrate"
    assert payload["key_presente"] is False


def test_tier1_verify_only_manifesto_and_query_empty_json(
    e2e_sandbox, publish_synthetic_asset
) -> None:
    publish_synthetic_asset(e2e_sandbox.dest_dir, "prop.e2e.crate.01", projeto="e2e_cli")

    rc_ver, _, err_ver, ver = e2e_sandbox.run_cli(
        ["verify", str(e2e_sandbox.dest_dir), "--only=manifesto"]
    )
    assert rc_ver == 0, err_ver
    assert isinstance(ver, dict)
    assert ver["ok"] is True
    assert ver["total"] == 1
    assert ver["faltando"] == []
    assert ver["itens"][0]["qc_reexecutado"] is None

    rc_q, _, err_q, qry = e2e_sandbox.run_cli(["query"])
    assert rc_q == 0, err_q
    assert isinstance(qry, dict)
    assert qry["schema"] == "forge3d/query@1"
    assert qry["total"] == 0
    assert qry["assets"] == []


def test_tier1_sync_json_rojo_and_godot(e2e_sandbox, publish_synthetic_asset) -> None:
    publish_synthetic_asset(e2e_sandbox.dest_dir, "prop.e2e.sync.01", projeto="e2e_cli")
    ledger_line = json.dumps({"evento": "upload", "id": "prop.e2e.sync.01", "asset_id": "987654321"})
    (e2e_sandbox.state_dir / "ledger.jsonl").write_text(ledger_line + "\n", encoding="utf-8")
    target = e2e_sandbox.root / "sync_target"
    target.mkdir(parents=True, exist_ok=True)
    stale = target / "stale_orphan.txt"
    stale.write_text("remove me", encoding="utf-8")
    rojo_lua = e2e_sandbox.root / "out" / "Assets.lua"
    godot_gd = e2e_sandbox.root / "out" / "Forge3DAssets.gd"

    rc, _, err, payload = e2e_sandbox.run_cli(
        [
            "sync",
            str(e2e_sandbox.dest_dir),
            "--para",
            str(target),
            "--limpar",
            "--rojo-lua",
            str(rojo_lua),
            "--godot-gd",
            str(godot_gd),
        ]
    )
    assert rc == 0, err
    assert isinstance(payload, dict)
    assert payload["ok"] is True
    assert payload["ativos"] == 1
    assert payload["rojo_assets"] == 1
    assert payload["godot_assets"] == 1
    assert "stale_orphan.txt" in payload["removidos"]
    assert not stale.exists()
    assert (target / "prop.e2e.sync.01.glb").is_file()
    assert (target / "prop.e2e.sync.01.manifest.json").is_file()
    assert rojo_lua.is_file() and "prop.e2e.sync.01" in rojo_lua.read_text(encoding="utf-8")
    assert godot_gd.is_file() and "prop.e2e.sync.01" in godot_gd.read_text(encoding="utf-8")


@pytest.mark.blender
@pytest.mark.rapido
def test_tier1_run_nao_publicar_publish_verify_query_json(e2e_sandbox, write_spec) -> None:
    spec_path = write_spec(e2e_sandbox.root / "lote_run.yaml", _minimal_spec6(e2e_sandbox.dest_dir))

    rc_dry, _, err_dry, dry = e2e_sandbox.run_cli(["run", str(spec_path), "--nao-publicar"])
    assert rc_dry == 0, err_dry
    assert isinstance(dry, dict)
    assert dry["resumo"]["publicados"] == 0
    assert dry["itens"][0]["estado"] == "aprovado_nao_publicado"
    assert dry["artifacts"] == []
    assert not e2e_sandbox.dest_dir.exists()

    rc_pub, _, err_pub, pub = e2e_sandbox.run_cli(["run", str(spec_path), "--no-cache"])
    assert rc_pub == 0, err_pub
    assert isinstance(pub, dict)
    assert pub["resumo"]["publicados"] == 1
    assert (e2e_sandbox.dest_dir / "prop.crate.cli.01.glb").is_file()
    assert (e2e_sandbox.dest_dir / "prop.crate.cli.01.manifest.json").is_file()

    rc_ver, _, err_ver, ver = e2e_sandbox.run_cli(["verify", str(e2e_sandbox.dest_dir)])
    assert rc_ver == 0, err_ver
    assert isinstance(ver, dict) and ver["ok"] is True

    rc_ep, _, err_ep, ep = e2e_sandbox.run_cli(
        ["verify", str(e2e_sandbox.dest_dir), "--only=escala,pivo"]
    )
    assert rc_ep == 0, err_ep
    assert isinstance(ep, dict)
    assert ep["ok"] is True
    assert ep["escala"]["delta_pct"] <= 0.5
    assert ep["pivo"]["delta_mm"] <= 1.0

    rc_q, _, err_q, qry = e2e_sandbox.run_cli(["query", "--projeto", "e2e_cli", "--tag", "cli"])
    assert rc_q == 0, err_q
    assert isinstance(qry, dict)
    assert qry["total"] == 1
    assert qry["assets"][0]["asset_id"] == "prop.crate.cli.01"


# ---------------------------------------------------------------------------
# Tier 2: Error boundaries, validation refusals & expected RED contracts
# ---------------------------------------------------------------------------


def test_tier2_malformed_yaml_and_invalid_schema(e2e_sandbox, write_spec) -> None:
    bad_yaml = write_spec(e2e_sandbox.root / "bad.yaml", "schema: forge3d/spec@6\nlote: [unclosed\n")
    rc_y, _, _, py_err = e2e_sandbox.run_cli(["validate", str(bad_yaml)])
    assert rc_y == 2
    assert isinstance(py_err, dict) and py_err["erro"]["codigo"] == "FORGE-E-SPEC"

    bad_schema = _minimal_spec6(e2e_sandbox.dest_dir)
    bad_schema["schema"] = "forge3d/spec@99"
    bad_schema_path = write_spec(e2e_sandbox.root / "bad_schema.yaml", bad_schema)
    for cmd in ("validate", "plan"):
        rc_s, _, _, err_s = e2e_sandbox.run_cli([cmd, str(bad_schema_path)])
        assert rc_s == 2
        assert isinstance(err_s, dict) and err_s["erro"]["codigo"] == "FORGE-E-SPEC"


def test_tier2_missing_files_spec_and_verify(e2e_sandbox) -> None:
    missing_yaml = e2e_sandbox.root / "does_not_exist.yaml"
    for cmd in ("validate", "plan", "migrate"):
        rc, _, _, payload = e2e_sandbox.run_cli([cmd, str(missing_yaml)])
        assert rc == 2
        assert isinstance(payload, dict) and payload["erro"]["codigo"] == "FORGE-E-SPEC"

    missing_dest = e2e_sandbox.root / "missing_dest"
    rc_v, _, _, err_v = e2e_sandbox.run_cli(["verify", str(missing_dest)])
    assert rc_v == 3
    assert isinstance(err_v, dict) and err_v["erro"]["codigo"] == "FORGE-E-MANIFEST"


def test_tier2_verify_unknown_only_aspect(e2e_sandbox, publish_synthetic_asset) -> None:
    publish_synthetic_asset(e2e_sandbox.dest_dir, "prop.e2e.only.01")
    rc, _, _, payload = e2e_sandbox.run_cli(
        ["verify", str(e2e_sandbox.dest_dir), "--only=xpto"]
    )
    assert rc == 2
    assert isinstance(payload, dict) and payload["erro"]["codigo"] == "FORGE-E-SPEC"


def test_tier2_non_allowlisted_destination(e2e_sandbox, write_spec) -> None:
    unlisted_dir = e2e_sandbox.root / "unlisted_dest"
    spec_path = write_spec(e2e_sandbox.root / "unlisted.yaml", _minimal_spec6(unlisted_dir))

    rc_p, _, _, err_p = e2e_sandbox.run_cli(["plan", str(spec_path)])
    assert rc_p == 2
    assert isinstance(err_p, dict) and err_p["erro"]["codigo"] == "FORGE-E-DESTINO"

    r15_path = write_spec(e2e_sandbox.root / "unlisted_r15.yaml", _minimal_r15_spec(e2e_sandbox.dest_dir))
    rc_r, _, _, err_r = e2e_sandbox.run_cli(
        [
            "export-r15",
            str(r15_path),
            "--item",
            "char.guard.cli.01",
            "--saida",
            str(unlisted_dir / "char.rbxlx"),
        ]
    )
    assert rc_r == 2
    assert isinstance(err_r, dict) and err_r["erro"]["codigo"] == "FORGE-E-DESTINO"


def test_tier2_upload_model_strip_embedded_textures_dry_run(e2e_sandbox, make_minimal_glb) -> None:
    """Contract F11: `upload-model --dry-run --strip-embedded-textures` strips embedded PNGs."""
    glb_path = make_minimal_glb(e2e_sandbox.root / "textured.glb", png_wh=(64, 64), with_texture=True)

    rc, stdout, stderr, payload = e2e_sandbox.run_cli(
        [
            "upload-model",
            str(glb_path),
            "--creator-id",
            "12345",
            "--dry-run",
            "--strip-embedded-textures",
        ]
    )
    assert rc == 0, f"expected F11 flag support (rc={rc}): stdout={stdout} stderr={stderr}"
    assert isinstance(payload, dict)
    assert payload["ok"] is True
    assert payload["dry_run"] is True
    strip_info = payload["strip_embedded_textures"]
    png_len = len(build_minimal_png_bytes(64, 64))
    assert strip_info["imagens_removidas"] >= 1
    assert strip_info["bytes_antes"] - strip_info["bytes_depois"] >= png_len
    assert payload["bytes"] == strip_info["bytes_depois"]


def test_tier2_doctor_json_reports_spec_and_manifest_v7(e2e_sandbox) -> None:
    """Contract F03: `doctor --json` validates and reports spec@1..@6 and manifest@1..@7."""
    rc, _, err, payload = e2e_sandbox.run_cli(["doctor"])
    assert rc in (0, 4), err
    assert isinstance(payload, dict)
    checks = {c["nome"]: c for c in payload["checks"]}
    schemas_check = checks["schemas"]
    assert schemas_check["ok"] is True
    assert "spec@1..@6" in schemas_check["detalhe"]
    assert "manifest@1..@7" in schemas_check["detalhe"]
