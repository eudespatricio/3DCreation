"""FA6 Invariants I1-I15 opaque-box E2E tests (Tiers 1 & 2)."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml


def _spec6(dest_dir: Path, item: dict[str, Any], *, projeto: str = "e2e_inv") -> dict[str, Any]:
    return {
        "schema": "forge3d/spec@6",
        "projeto": projeto,
        "perfil": "godot4",
        "destino_exportacao": str(dest_dir),
        "estilo_global": "blocky_voxel",
        "paleta": ["#7d858f", "#3b4048", "#ff6a1f"],
        "lote": [item],
    }


def _blocky_item(item_id: str = "prop.inv.crate.01", *, limite_tris: int = 400) -> dict[str, Any]:
    return {
        "id": item_id,
        "tipo": "prop_estatico",
        "rota": "blocky",
        "prompt": "Wooden crate for invariant test",
        "altura_metros": 0.40,
        "pivot": "base",
        "limite_triangulos": limite_tris,
        "colisao": "box",
        "lod": [100],
        "tags": ["inv"],
    }


# ---------------------------------------------------------------------------
# Tier 1: Positive invariant contracts (I1, I3, I4, I8, I9, I10, I11)
# ---------------------------------------------------------------------------


@pytest.mark.blender
@pytest.mark.rapido
def test_i1_blocky_and_import_deterministic_sha256_no_gpu(
    e2e_sandbox, write_spec, make_minimal_glb
) -> None:
    """I1: Both `blocky` and `import` produce deterministic D1 SHA-256 outputs without GPU."""
    import_glb = make_minimal_glb(e2e_sandbox.root / "source_cube.glb", size_xyz=(0.5, 0.5, 0.5))
    dest_b1 = e2e_sandbox.allowlist_add(e2e_sandbox.root / "dest_b1")
    dest_b2 = e2e_sandbox.allowlist_add(e2e_sandbox.root / "dest_b2")
    dest_i1 = e2e_sandbox.allowlist_add(e2e_sandbox.root / "dest_i1")
    dest_i2 = e2e_sandbox.allowlist_add(e2e_sandbox.root / "dest_i2")

    import_item = {
        "id": "prop.inv.import.01",
        "tipo": "prop_estatico",
        "rota": "import",
        "origem": str(import_glb),
        "altura_metros": 0.50,
        "pivot": "base",
        "limite_triangulos": 400,
        "colisao": "box",
        "lod": [100],
    }
    no_gpu_env = {"CUDA_VISIBLE_DEVICES": ""}

    hashes: list[list[tuple[str, str]]] = []
    for dest, item, name in (
        (dest_b1, _blocky_item("prop.inv.det.01"), "b1.yaml"),
        (dest_b2, _blocky_item("prop.inv.det.01"), "b2.yaml"),
        (dest_i1, import_item, "i1.yaml"),
        (dest_i2, import_item, "i2.yaml"),
    ):
        spec_path = write_spec(e2e_sandbox.root / name, _spec6(dest, item))
        rc, _, err, rep = e2e_sandbox.run_cli(
            ["run", str(spec_path), "--no-cache"], env_overrides=no_gpu_env
        )
        assert rc == 0, err
        assert isinstance(rep, dict)
        assert rep["resumo"]["publicados"] == 1
        assert rep["itens"][0]["determinism"] == "D1"
        man_path = dest / rep["itens"][0]["manifesto"]
        man = json.loads(man_path.read_text(encoding="utf-8"))
        assert man["determinism"] == "D1"
        for fentry in man["files"]:
            digest = hashlib.sha256((dest / fentry["caminho"]).read_bytes()).hexdigest()
            assert fentry["sha256"] == f"sha256:{digest}"
        hashes.append(sorted((Path(a["caminho"]).name, a["sha256"]) for a in rep["artifacts"]))

    assert hashes[0] == hashes[1]
    assert hashes[2] == hashes[3]


@pytest.mark.blender
@pytest.mark.rapido
def test_i3_nao_publicar_writes_zero_files_then_publishes_atomically(
    e2e_sandbox, write_spec
) -> None:
    """I3: Nothing writes to dest until atomic staging `publish` succeeds."""
    spec_path = write_spec(
        e2e_sandbox.root / "i3.yaml", _spec6(e2e_sandbox.dest_dir, _blocky_item())
    )

    rc_plan, _, err_plan, _ = e2e_sandbox.run_cli(["plan", str(spec_path)])
    assert rc_plan == 0, err_plan
    assert not e2e_sandbox.dest_dir.exists()

    rc_dry, _, err_dry, dry = e2e_sandbox.run_cli(["run", str(spec_path), "--nao-publicar"])
    assert rc_dry == 0, err_dry
    assert isinstance(dry, dict)
    assert dry["resumo"]["publicados"] == 0
    assert dry["itens"][0]["estado"] == "aprovado_nao_publicado"
    assert dry["itens"][0]["manifesto"] is None
    assert dry["artifacts"] == []
    assert not e2e_sandbox.dest_dir.exists()

    rc_pub, _, err_pub, pub = e2e_sandbox.run_cli(["run", str(spec_path), "--no-cache"])
    assert rc_pub == 0, err_pub
    assert isinstance(pub, dict) and pub["resumo"]["publicados"] == 1
    assert not any(p.name.startswith(".") for p in e2e_sandbox.dest_dir.iterdir())
    rc_ver, _, err_ver, ver = e2e_sandbox.run_cli(["verify", str(e2e_sandbox.dest_dir)])
    assert rc_ver == 0, err_ver
    assert isinstance(ver, dict) and ver["ok"] is True


def test_i4_verify_detects_1byte_glb_tamper_and_missing_manifest(
    e2e_sandbox, publish_synthetic_asset
) -> None:
    """I4: 1-byte GLB tampering fails `verify` (`exit=3`) and `sync` (`FORGE-E-MANIFEST`)."""
    empty_dir = e2e_sandbox.root / "empty_dest"
    empty_dir.mkdir(parents=True, exist_ok=True)
    rc_empty, _, _, err_empty = e2e_sandbox.run_cli(["verify", str(empty_dir)])
    assert rc_empty == 3
    assert isinstance(err_empty, dict) and err_empty["erro"]["codigo"] == "FORGE-E-MANIFEST"

    glb_path, _ = publish_synthetic_asset(e2e_sandbox.dest_dir, "prop.inv.tamper.01")
    rc_pre, _, err_pre, ver_pre = e2e_sandbox.run_cli(["verify", str(e2e_sandbox.dest_dir)])
    assert rc_pre == 0, err_pre
    assert isinstance(ver_pre, dict) and ver_pre["ok"] is True

    raw = bytearray(glb_path.read_bytes())
    raw[-1] ^= 0x01
    glb_path.write_bytes(bytes(raw))

    rc_ver, _, _, ver = e2e_sandbox.run_cli(["verify", str(e2e_sandbox.dest_dir)])
    assert rc_ver == 3
    assert isinstance(ver, dict) and ver["ok"] is False
    assert any("hash divergente" in e["erro"] for e in ver["erros"])

    sync_target = e2e_sandbox.root / "sync_tamper_out"
    rc_sync, _, _, sync_err = e2e_sandbox.run_cli(
        ["sync", str(e2e_sandbox.dest_dir), "--para", str(sync_target)]
    )
    assert rc_sync == 3
    assert isinstance(sync_err, dict)
    assert sync_err["erro"]["codigo"] in ("FORGE-E-MANIFEST", "FORGE-E-QC")
    assert not sync_target.exists()


def test_i8_verify_only_escala_pivo_contract(e2e_sandbox, publish_synthetic_asset) -> None:
    """I8: `verify --only=escala,pivo` passes within tolerance and fails on out-of-tolerance."""
    ok_dir = e2e_sandbox.root / "i8_ok"
    publish_synthetic_asset(ok_dir, "prop.inv.scale.01", size_xyz=(1.0, 1.0, 1.0))

    rc_ok, _, err_ok, ver_ok = e2e_sandbox.run_cli(
        ["verify", str(ok_dir), "--only=escala,pivo"]
    )
    assert rc_ok == 0, err_ok
    assert isinstance(ver_ok, dict)
    assert ver_ok["ok"] is True
    assert ver_ok["escala"]["delta_pct"] <= 0.5
    assert ver_ok["pivo"]["delta_mm"] <= 1.0

    for tag, aid, expected_m, pivo_rule in (
        ("scale", "prop.inv.scale.02", 2.0, "base"),
        ("pivot", "prop.inv.scale.03", 1.0, "centro"),
    ):
        bad_dir = e2e_sandbox.root / f"i8_bad_{tag}"
        publish_synthetic_asset(
            bad_dir,
            aid,
            size_xyz=(1.0, 1.0, 1.0),
            manifest_overrides={
                "qc": {
                    "aprovado": True,
                    "gates": [
                        {"id": "G2", "status": "ok", "medido": {"esperado_m": expected_m, "pivo_regra": pivo_rule}},
                        {"id": "G9", "status": "ok", "medido": {"triangulos": 12, "limite": 500}},
                    ],
                }
            },
        )
        rc_bad, _, _, ver_bad = e2e_sandbox.run_cli(["verify", str(bad_dir), "--only=escala,pivo"])
        assert rc_bad == 3
        assert isinstance(ver_bad, dict) and ver_bad["ok"] is False
        assert any("G2" in e["erro"] for e in ver_bad["erros"])


def test_i9_blender_scripts_no_pip_install_and_post_ipc(repo_root) -> None:
    """I9: Blender scripts never invoke `pip install` and communicate via disk JSON."""
    blender_scripts = sorted((repo_root / "blender").glob("*.py"))
    assert blender_scripts
    for script in blender_scripts:
        content = script.read_text(encoding="utf-8")
        assert "pip install" not in content, f"forbidden pip install in {script.name}"

    post_src = (repo_root / "src" / "forge3d" / "post.py").read_text(encoding="utf-8")
    for token in ("--background", "--factory-startup", "--python", "resultado.json"):
        assert token in post_src


@pytest.mark.blender
@pytest.mark.rapido
def test_i9_doctor_reports_blender_42(e2e_sandbox) -> None:
    """I9: `doctor --json` confirms pinned Blender 4.2.x."""
    rc, _, err, doc = e2e_sandbox.run_cli(["doctor"])
    assert rc == 0, err
    assert isinstance(doc, dict)
    assert doc["ok"] is True
    assert isinstance(doc["blender"], str) and doc["blender"].startswith("4.2.")


def test_i10_verify_only_manifesto_provenance(e2e_sandbox, publish_synthetic_asset) -> None:
    """I10: `verify --only=manifesto` validates full provenance and flags missing fields."""
    ok_dir = e2e_sandbox.root / "i10_ok"
    publish_synthetic_asset(ok_dir, "prop.inv.prov.01")
    rc_ok, _, err_ok, ver_ok = e2e_sandbox.run_cli(
        ["verify", str(ok_dir), "--only=manifesto"]
    )
    assert rc_ok == 0, err_ok
    assert isinstance(ver_ok, dict)
    assert ver_ok["ok"] is True
    assert ver_ok["faltando"] == []

    bad_dir = e2e_sandbox.root / "i10_bad"
    publish_synthetic_asset(
        bad_dir,
        "prop.inv.prov.02",
        manifest_overrides={"licenca": {"modelo": "CC0-1.0", "uso_comercial": True, "notice": ""}},
    )
    rc_bad, _, _, ver_bad = e2e_sandbox.run_cli(
        ["verify", str(bad_dir), "--only=manifesto"]
    )
    assert rc_bad == 3
    assert isinstance(ver_bad, dict) and ver_bad["ok"] is False
    assert any(f["campo"] == "licenca.notice" for f in ver_bad["faltando"])
    assert any(e["erro"] == "proveniencia incompleta" for e in ver_bad["erros"])


@pytest.mark.blender
@pytest.mark.rapido
def test_i11_idempotent_rerun_zero_work(e2e_sandbox, write_spec) -> None:
    """I11: Identical second `run` hits cache (`trabalho_executado == 0`) with identical bytes."""
    spec_path = write_spec(
        e2e_sandbox.root / "i11.yaml", _spec6(e2e_sandbox.dest_dir, _blocky_item("prop.inv.idem.01"))
    )

    rc1, _, err1, run1 = e2e_sandbox.run_cli(["run", str(spec_path)])
    assert rc1 == 0, err1
    assert isinstance(run1, dict)
    assert run1["resumo"]["publicados"] == 1
    assert run1["resumo"]["trabalho_executado"] == 1
    assert run1["resumo"]["cache_hits"] == 0
    glb_file = e2e_sandbox.dest_dir / "prop.inv.idem.01.glb"
    digest_before = hashlib.sha256(glb_file.read_bytes()).hexdigest()

    rc2, _, err2, run2 = e2e_sandbox.run_cli(["run", str(spec_path)])
    assert rc2 == 0, err2
    assert isinstance(run2, dict)
    assert run2["resumo"]["trabalho_executado"] == 0
    assert run2["resumo"]["cache_hits"] == 1
    assert run2["resumo"]["publicados"] == 0
    assert run2["itens"][0]["cache_hit"] is True
    assert run2["itens"][0]["trabalho_executado"] is False
    assert hashlib.sha256(glb_file.read_bytes()).hexdigest() == digest_before


# ---------------------------------------------------------------------------
# Tier 2: Refusals, boundary violations & isolation (I2, I5, I12-I15)
# ---------------------------------------------------------------------------


def test_i2_invalid_spec_fails_before_provider(e2e_sandbox, write_spec) -> None:
    """I2: Invalid spec or business rule fails with `FORGE-E-SPEC` before any run/staging work."""
    bad_height = _blocky_item("prop.inv.badh.01")
    bad_height["altura_metros"] = -1.0
    spec_bad_h = write_spec(e2e_sandbox.root / "i2_h.yaml", _spec6(e2e_sandbox.dest_dir, bad_height))

    bad_import = {
        "id": "prop.inv.noimp.01",
        "tipo": "prop_estatico",
        "rota": "import",
        "altura_metros": 1.0,
        "pivot": "base",
        "limite_triangulos": 400,
    }
    spec_bad_i = write_spec(e2e_sandbox.root / "i2_imp.yaml", _spec6(e2e_sandbox.dest_dir, bad_import))

    for sp in (spec_bad_h, spec_bad_i):
        rc, _, _, err = e2e_sandbox.run_cli(["run", str(sp)])
        assert rc == 2
        assert isinstance(err, dict) and err["erro"]["codigo"] == "FORGE-E-SPEC"

    runs_dir = e2e_sandbox.state_dir / "runs"
    staging_dir = e2e_sandbox.state_dir / "staging"
    assert not runs_dir.exists() or list(runs_dir.iterdir()) == []
    assert not staging_dir.exists() or list(staging_dir.iterdir()) == []
    assert not e2e_sandbox.dest_dir.exists()


def test_i5_cli_rejects_qc_bypass_flags(
    e2e_sandbox, write_spec, publish_synthetic_asset, repo_root
) -> None:
    """I5: CLI refuses bypass flags (`--force`, `--skip-qc`, `--no-verify`) and none exist in CLI."""
    spec_path = write_spec(
        e2e_sandbox.root / "i5_flags.yaml", _spec6(e2e_sandbox.dest_dir, _blocky_item())
    )
    for flag in ("--force", "--skip-qc", "--no-verify"):
        rc, _, stderr, _ = e2e_sandbox.run_cli(["run", str(spec_path), flag], json_out=False)
        assert rc == 2
        assert "unrecognized arguments" in stderr

    publish_synthetic_asset(e2e_sandbox.dest_dir, "prop.inv.bypass.01")
    rc_v, _, stderr_v, _ = e2e_sandbox.run_cli(
        ["verify", str(e2e_sandbox.dest_dir), "--force"], json_out=False
    )
    assert rc_v == 2
    assert "unrecognized arguments" in stderr_v

    cli_texts = "\n".join(
        p.read_text(encoding="utf-8") for p in sorted((repo_root / "src" / "forge3d" / "cli").glob("*.py"))
    )
    for forbidden in ("--force", "--skip-qc", "--no-verify", "skip_qc"):
        assert forbidden not in cli_texts


@pytest.mark.blender
@pytest.mark.rapido
def test_i5_qc_rejection_blocks_publish(e2e_sandbox, write_spec, repo_root) -> None:
    """I5: QC gate failure rejects with `exit=3` and writes zero files to destination."""
    fixture = yaml.safe_load(
        (repo_root / "tests" / "fixtures" / "lote_qc_reprovado.yaml").read_text(encoding="utf-8")
    )
    fixture["destino_exportacao"] = str(e2e_sandbox.dest_dir)
    spec_path = write_spec(e2e_sandbox.root / "i5_qc_fail.yaml", fixture)

    rc, _, _, rep = e2e_sandbox.run_cli(["run", str(spec_path)])
    assert rc == 3
    assert isinstance(rep, dict)
    assert rep["resumo"]["publicados"] == 0
    assert rep["resumo"]["reprovados"] == 1
    assert rep["itens"][0]["estado"] == "reprovado"
    assert rep["itens"][0]["codigo"] == "FORGE-E-QC"
    assert rep["artifacts"] == []
    assert not e2e_sandbox.dest_dir.exists()


def test_i12_refuses_mnt_and_unc_paths(
    e2e_sandbox, write_spec, publish_synthetic_asset
) -> None:
    """I12: Refuses `/mnt/...` and `\\\\wsl...` paths with `exit=2` and `FORGE-E-PATH`."""
    mnt_dest = "/mnt/c/forge3d_e2e_forbidden/assets"
    unc_dest = "\\\\wsl.localhost\\Ubuntu\\home\\e2e_forbidden\\assets"

    for bad_dest, name in ((mnt_dest, "i12_mnt.yaml"), (unc_dest, "i12_unc.yaml")):
        sp = write_spec(e2e_sandbox.root / name, _spec6(Path(bad_dest), _blocky_item()))
        rc, _, _, err = e2e_sandbox.run_cli(["plan", str(sp)])
        assert rc == 2
        assert isinstance(err, dict) and err["erro"]["codigo"] == "FORGE-E-PATH"

    rc_al, _, _, err_al = e2e_sandbox.run_cli(["allowlist", "add", mnt_dest])
    assert rc_al == 2
    assert isinstance(err_al, dict) and err_al["erro"]["codigo"] == "FORGE-E-PATH"

    rc_so, _, _, err_so = e2e_sandbox.run_cli(
        ["sync", mnt_dest, "--para", str(e2e_sandbox.root / "out_mnt")]
    )
    assert rc_so == 2
    assert isinstance(err_so, dict) and err_so["erro"]["codigo"] == "FORGE-E-PATH"

    publish_synthetic_asset(e2e_sandbox.dest_dir, "prop.inv.i12.01")
    rc_su, _, _, err_su = e2e_sandbox.run_cli(
        ["sync", str(e2e_sandbox.dest_dir), "--para", unc_dest]
    )
    assert rc_su == 2
    assert isinstance(err_su, dict) and err_su["erro"]["codigo"] == "FORGE-E-PATH"


def test_i13_outside_allowlist_refusal_and_grant(e2e_sandbox, write_spec) -> None:
    """I13: Non-allowlisted ext4 destination fails (`FORGE-E-DESTINO`) until authorized."""
    outside = e2e_sandbox.root / "outside_game"
    spec_path = write_spec(e2e_sandbox.root / "i13.yaml", _spec6(outside, _blocky_item()))

    rc_deny, _, _, err_deny = e2e_sandbox.run_cli(["plan", str(spec_path)])
    assert rc_deny == 2
    assert isinstance(err_deny, dict) and err_deny["erro"]["codigo"] == "FORGE-E-DESTINO"

    e2e_sandbox.allowlist_add(outside)
    rc_ok, _, err_msg, ok_plan = e2e_sandbox.run_cli(["plan", str(spec_path)])
    assert rc_ok == 0, err_msg
    assert isinstance(ok_plan, dict) and ok_plan["exit"] == 0


def test_i14_franchise_name_refusal_and_legacy_alias(
    e2e_sandbox, write_spec, repo_root
) -> None:
    """I14: Franchise names are refused in id/tags/prompt/style; legacy alias emits warning."""
    bad_id = _blocky_item("mob.mario.01")
    bad_tag = {**_blocky_item("prop.inv.tag.01"), "tags": ["zelda", "fantasy"]}
    bad_prompt = {**_blocky_item("prop.inv.prm.01"), "prompt": "espada pokemon"}
    for idx, item in enumerate((bad_id, bad_tag, bad_prompt)):
        sp = write_spec(e2e_sandbox.root / f"i14_{idx}.yaml", _spec6(e2e_sandbox.dest_dir, item))
        rc, _, _, err = e2e_sandbox.run_cli(["validate", str(sp)])
        assert rc == 2
        assert isinstance(err, dict) and err["erro"]["codigo"] == "FORGE-E-SPEC"
        assert "I14" in json.dumps(err["erro"])

    bad_style = _spec6(e2e_sandbox.dest_dir, _blocky_item("prop.inv.st.01"))
    bad_style["estilo_global"] = "fortnite"
    rc_st, _, _, err_st = e2e_sandbox.run_cli(
        ["validate", str(write_spec(e2e_sandbox.root / "i14_style.yaml", bad_style))]
    )
    assert rc_st == 2
    assert isinstance(err_st, dict) and err_st["erro"]["codigo"] == "FORGE-E-SPEC"

    alias_spec = _spec6(e2e_sandbox.dest_dir, _blocky_item("prop.inv.alias.01"))
    alias_spec["estilo_global"] = "minecraft_bedrock"
    rc_al, _, err_msg, ok_al = e2e_sandbox.run_cli(
        ["validate", str(write_spec(e2e_sandbox.root / "i14_alias.yaml", alias_spec))]
    )
    assert rc_al == 0, err_msg
    assert isinstance(ok_al, dict)
    assert any(w["codigo"] == "FORGE-W-ALIAS" for w in ok_al["avisos"])

    fake_repo = e2e_sandbox.root / "fake_repo_i14"
    (fake_repo / "examples").mkdir(parents=True, exist_ok=True)
    (fake_repo / "examples" / "bad.yaml").write_text("estilo: zelda\n", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(repo_root / "tools" / "conformidade.py"), str(fake_repo)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 1
    assert "I14:" in proc.stdout


def test_i15_project_isolation_and_conformidade(e2e_sandbox, write_spec, repo_root) -> None:
    """I15: Repo passes `conformidade.py` cleanly; planted personal paths fail; CLI stays isolated."""
    live = subprocess.run(
        [sys.executable, str(repo_root / "tools" / "conformidade.py"), str(repo_root)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert live.returncode == 0, live.stdout + live.stderr
    assert live.stdout.strip() == ""

    fake_repo = e2e_sandbox.root / "fake_repo_i15"
    (fake_repo / "src" / "forge3d").mkdir(parents=True, exist_ok=True)
    shutil.copy2(repo_root / "pyproject.toml", fake_repo / "pyproject.toml")
    shutil.copy2(
        repo_root / "src" / "forge3d" / "__init__.py",
        fake_repo / "src" / "forge3d" / "__init__.py",
    )
    proj_tok = "game" + "one"
    (fake_repo / "src" / "forge3d" / "bad_path.py").write_text(
        f'FIXED_PATH = "/home/alice_test/proj"\nPROJ = "{proj_tok}"\n', encoding="utf-8"
    )
    bad = subprocess.run(
        [sys.executable, str(repo_root / "tools" / "conformidade.py"), str(fake_repo)],
        capture_output=True, text=True, timeout=30,
    )
    assert bad.returncode == 1
    assert "I15: caminho pessoal fixo" in bad.stdout
    assert "I15: nome de projeto" in bad.stdout

    consumer_dir = e2e_sandbox.root / "consumer_project_dir"
    consumer_dir.mkdir(parents=True, exist_ok=True)
    sp = write_spec(e2e_sandbox.root / "i15_plan.yaml", _spec6(e2e_sandbox.dest_dir, _blocky_item()))
    rc_p, _, err_p, plan = e2e_sandbox.run_cli(["plan", str(sp)], cwd=consumer_dir)
    assert rc_p == 0, err_p
    assert isinstance(plan, dict) and os.path.realpath(plan["destino"]) == os.path.realpath(e2e_sandbox.dest_dir)
    rc_q, _, err_q, qry = e2e_sandbox.run_cli(["query", "--projeto", "alpha_test"])
    assert rc_q == 0, err_q
    assert isinstance(qry, dict) and qry["total"] == 0 and qry["assets"] == []
