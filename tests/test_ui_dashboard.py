"""Testes de conformidade, seguranca e REST API do Forge3D Studio (forge3d ui).

Cobre:
1. CLI e rotas estaticas do SPA (ui_web/) + auditoria estatica de rotas JS
2. Endpoints de leitura e catalogo (health, doctor, meta, examples, destinations)
3. Limites de seguranca (CSRF, travessia, isolamento de segredos, uploads e allowlist)
4. Validacao, migracao, planejamento e codigos de erro da API
5. E2E sobre HTTP: cenario sintetico sem Blender e cenario ponta a ponta com Blender
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

import pytest

from forge3d import __version__, config, paths
from forge3d.cli.comandos import construir_parser
from forge3d.ui.server import criar_servidor
from tests.test_sync import _publicar_valido

RAIZ = Path(__file__).resolve().parents[1]
PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c636000000002000148afa4710000000049454e44ae426082"
)


def http_req(
    url: str,
    method: str = "GET",
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, Any, dict[str, str]]:
    hdrs, data = dict(headers or {}), None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15.0) as resp:
            st, raw, resp_hdrs = resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        st, raw, resp_hdrs = exc.code, exc.read(), dict(exc.headers)
    if "application/json" in resp_hdrs.get("Content-Type", "") and raw:
        try:
            return st, json.loads(raw.decode("utf-8")), resp_hdrs
        except (UnicodeDecodeError, json.JSONDecodeError):
            return st, raw, resp_hdrs
    return st, raw, resp_hdrs


@pytest.fixture
def test_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    home, cfg = tmp_path / "home", tmp_path / "config"
    home.mkdir(parents=True, exist_ok=True)
    cfg.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("FORGE3D_HOME", str(home))
    monkeypatch.setenv("FORGE3D_CONFIG", str(cfg))
    monkeypatch.setenv("HOME", str(home))

    srv = criar_servidor("127.0.0.1", 0)
    port = srv.server_address[1]
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}", home, cfg, srv
    finally:
        srv.shutdown()
        srv.job_manager.encerrar_todos()
        srv.server_close()
        thread.join(timeout=2.0)


# ==============================================================================
# 1. CLI & Packaging Sanity
# ==============================================================================


def test_cli_ui_help():
    sub = next(a for a in construir_parser()._actions if a.dest == "cmd").choices["ui"]
    assert {"--host", "--port", "--no-browser"}.issubset(set(sub._option_string_actions.keys()))

    p = subprocess.run([sys.executable, "-m", "forge3d.cli.main", "ui", "--help"], capture_output=True, text=True, check=False)
    assert p.returncode == 0 and all(f in p.stdout for f in ("--host", "--port", "--no-browser"))


def test_spa_static_files(test_server):
    base, *_ = test_server
    st, body, hdrs = http_req(f"{base}/")
    assert st == 200 and "text/html" in hdrs.get("Content-Type", "") and b"FORGE3D STUDIO" in body.upper()

    estaticos = [
        ("app.js", "text/javascript"), ("viewer3d.js", "text/javascript"), ("styles.css", "text/css"),
        ("api.js", "text/javascript"), ("spec_builder.js", "text/javascript"),
        ("outputs_view.js", "text/javascript"), ("ops_view.js", "text/javascript"),
    ]
    for arq, mime in estaticos:
        st, b, h = http_req(f"{base}/static/{arq}")
        assert st == 200 and mime in h.get("Content-Type", "") and len(b) > 0


def test_static_traversal_blocked(test_server):
    base, *_ = test_server
    for bad in ("/static/../ui/server.py", "/static/%2e%2e/ui/server.py"):
        st, _, _ = http_req(f"{base}{bad}")
        assert st in (403, 404), f"{bad} deveria retornar 403/404, deu {st}"


def test_static_frontend_to_backend_route_audit():
    rotas = {
        "/api/health", "/api/doctor", "/api/meta", "/api/examples", "/api/destinations",
        "/api/assets", "/api/asset", "/api/asset/bundle", "/api/file", "/api/runs", "/api/ledger",
        "/api/jobs", "/api/upload-input", "/api/spec/save", "/api/validate", "/api/plan",
        "/api/run", "/api/verify", "/api/migrate", "/api/export", "/api/sync",
        "/api/upload-cloud", "/api/allowlist", "/api/gc",
    }
    dir_web = RAIZ / "src" / "forge3d" / "ui_web"
    for js_path in dir_web.glob("*.js"):
        for m in re.finditer(r"/api/[a-zA-Z0-9_\-\/]+", js_path.read_text(encoding="utf-8")):
            rota = m.group(0).rstrip("/")
            assert any(rota == p or rota.startswith(f"{p}/") for p in rotas), f"Rota front-end desconhecida: {rota}"


# ==============================================================================
# 2. Metadata & Read Endpoints
# ==============================================================================


def test_api_health_and_doctor(test_server):
    base, home, cfg, _ = test_server
    st, data, _ = http_req(f"{base}/api/health")
    assert st == 200 and data["ok"] is True and data["versao"] == __version__
    assert data["pipeline_version"] == "0.9.5" and data["estado"] == str(home) and data["config"] == str(cfg)

    st_doc, data_doc, _ = http_req(f"{base}/api/doctor")
    assert st_doc == 200 and data_doc["ok"] is True and "checks" in data_doc.get("doctor", {})


def test_api_meta_contract(test_server):
    base, *_ = test_server
    st, meta, _ = http_req(f"{base}/api/meta")
    assert st == 200 and meta["ok"] is True
    assert {"godot4", "godot4-aa", "roblox-r15", "roblox-aa-80"}.issubset({p["nome"] for p in meta["perfis"]})
    assert len(meta["clipes"]) == 17 and len(meta["partes_r15"]) == 15 and "HumanoidRootPart" not in meta["partes_r15"]
    assert any(e["nome"] == "lote_01.yaml" for e in meta["exemplos"]) and "schema_enums" in meta and "sockets" in meta


def test_api_examples_and_destinations(test_server):
    base, home, _, _ = test_server
    st_ex, ex_doc, _ = http_req(f"{base}/api/examples/lote_01.yaml")
    assert st_ex == 200 and ex_doc["ok"] is True and "yaml" in ex_doc and isinstance(ex_doc["doc"], dict)

    st_bad, _, _ = http_req(f"{base}/api/examples/../pyproject.toml")
    assert st_bad in (403, 404)
    st_miss, _, _ = http_req(f"{base}/api/examples/lote_fantasma.yaml")
    assert st_miss == 404

    st_dest, dests, _ = http_req(f"{base}/api/destinations")
    assert st_dest == 200 and dests["ok"] is True and dests["sandbox"] == str(home / "saida")
    assert isinstance(dests["allowlist"], list) and isinstance(dests["destinos"], list)


# ==============================================================================
# 3. Security & Invariant Boundaries (CRITICAL)
# ==============================================================================


def test_security_file_endpoint_traversal_and_secrets(test_server):
    base, home, cfg, _ = test_server
    saida = home / "saida"
    saida.mkdir(parents=True, exist_ok=True)
    (cfg / "gemini.key").write_text("segredo_super_critico_123", encoding="utf-8")
    (saida / "evil_link").symlink_to("/etc/passwd")

    for p in ("/etc/passwd", str(cfg / "gemini.key"), str(saida / "evil_link")):
        st, err, _ = http_req(f"{base}/api/file?path={p}")
        assert st == 403 and err.get("codigo") == "FORGE-E-FORBIDDEN"

    st_v_bad, err_v_bad, _ = http_req(f"{base}/api/verify", method="POST", body={"destino": "/etc"})
    assert st_v_bad == 403 and err_v_bad.get("codigo") == "FORGE-E-FORBIDDEN"


def test_csrf_guard(test_server):
    base, *_ = test_server
    st_evil, err_evil, _ = http_req(f"{base}/api/validate", method="POST", body={}, headers={"Origin": "https://evil.example"})
    assert st_evil == 403 and err_evil["codigo"] == "FORGE-E-FORBIDDEN"

    st_ref, err_ref, _ = http_req(f"{base}/api/validate", method="POST", body={}, headers={"Referer": "https://evil.example/page"})
    assert st_ref == 403 and err_ref["codigo"] == "FORGE-E-FORBIDDEN"

    st_ok, err_ok, _ = http_req(f"{base}/api/validate", method="POST", body={}, headers={"Origin": "http://127.0.0.1:8765"})
    assert st_ok != 403 and err_ok["codigo"] == "FORGE-E-REQUISICAO"


def test_upload_input_validation(test_server):
    base, home, *_ = test_server
    for bad_name, bad_bytes in (("exploit.sh", b"echo pwn"), ("fake.png", b"nao e um png")):
        st_bad, _, _ = http_req(f"{base}/api/upload-input", method="POST", body={"nome": bad_name, "conteudo_b64": base64.b64encode(bad_bytes).decode()})
        assert st_bad in (400, 422)

    b64_png = base64.b64encode(PNG_1X1).decode("ascii")
    st_ok, resp_ok, _ = http_req(f"{base}/api/upload-input", method="POST", body={"nome": "pixel.png", "conteudo_b64": b64_png})
    assert st_ok == 200 and resp_ok["ok"] is True
    salvo = Path(resp_ok["caminho"])
    assert salvo.is_file() and salvo.is_relative_to(home / "inputs" / "ui_uploads")
    assert resp_ok["sha256"] == f"sha256:{hashlib.sha256(PNG_1X1).hexdigest()}"
    assert resp_ok["bytes"] == len(PNG_1X1)

    st_get, dados_get, _ = http_req(f"{base}{resp_ok['url']}")
    assert st_get == 200 and dados_get == PNG_1X1


def test_spec_save_and_traversal(test_server):
    base, home, *_ = test_server
    st_bad, err_bad, _ = http_req(f"{base}/api/spec/save", method="POST", body={"nome": "../../evil", "yaml": "projeto: demo"})
    assert st_bad in (400, 403) and err_bad["codigo"] in ("FORGE-E-FORBIDDEN", "FORGE-E-REQUISICAO")

    st_ok, resp_ok, _ = http_req(f"{base}/api/spec/save", method="POST", body={"nome": "meu_lote.01", "yaml": "projeto: demo\nlote: []"})
    assert st_ok == 200 and resp_ok["ok"] is True and Path(resp_ok["caminho"]).is_relative_to(home / "inputs" / "ui_specs")


def test_allowlist_management_and_i12(test_server, tmp_path):
    base, *_ = test_server
    st_i12, err_i12, _ = http_req(f"{base}/api/allowlist", method="POST", body={"acao": "add", "caminho": "/mnt/c/forbidden"})
    assert st_i12 == 422 and err_i12["codigo"] == "FORGE-E-PATH"

    pasta_ext4 = tmp_path / "minha_ext4_valida"
    pasta_ext4.mkdir()
    st_add, resp_add, _ = http_req(f"{base}/api/allowlist", method="POST", body={"acao": "add", "caminho": str(pasta_ext4)})
    assert st_add == 200 and str(pasta_ext4) in resp_add["allowlist"]

    st_list, resp_list, _ = http_req(f"{base}/api/allowlist", method="POST", body={"acao": "list"})
    assert st_list == 200 and str(pasta_ext4) in resp_list["allowlist"]

    st_rem, resp_rem, _ = http_req(f"{base}/api/allowlist", method="POST", body={"acao": "remove", "caminho": str(pasta_ext4)})
    assert st_rem == 200 and resp_rem["removido"] is True and str(pasta_ext4) not in resp_rem["allowlist"]


# ==============================================================================
# 4. Validation, Migration, Planning & Error Codes
# ==============================================================================

SPEC_VALIDO = """schema: forge3d/spec@6
projeto: demo
perfil: godot4
destino_exportacao: ~/.local/state/forge3d/saida/teste
lote:
  - id: prop.caixa.01
    tipo: prop_estatico
    rota: blocky
    prompt: caixa
    altura_metros: 0.5
    pivot: base
"""


def test_validate_and_plan_endpoints(test_server):
    base, *_ = test_server
    st_val, resp_val, _ = http_req(f"{base}/api/validate", method="POST", body={"yaml": SPEC_VALIDO})
    assert st_val == 200 and resp_val["ok"] is True and resp_val["projeto"] == "demo" and resp_val["itens"] == 1

    st_err, resp_err, _ = http_req(f"{base}/api/validate", method="POST", body={"yaml": SPEC_VALIDO.replace("altura_metros: 0.5", "altura_metros: -1.0")})
    assert st_err == 422 and resp_err["codigo"] == "FORGE-E-SPEC"

    spec_v1 = "schema: forge3d/spec@1\nprojeto: demo\nperfil: godot4\ndestino_exportacao: ~/.local/state/forge3d/saida/t\nlote:\n  - id: prop.l.01\n    tipo: prop_estatico\n    rota: blocky\n    altura_metros: 0.4\n    pivot: base\n"
    st_mig, resp_mig, _ = http_req(f"{base}/api/migrate", method="POST", body={"yaml": spec_v1})
    assert st_mig == 200 and resp_mig["ok"] is True and resp_mig["para"] == "forge3d/spec@6" and len(resp_mig["mudancas"]) > 0

    spec_plan = SPEC_VALIDO.replace("destino_exportacao: ~/.local/state/forge3d/saida/teste", f"destino_exportacao: {paths.dir_saida()}/teste")
    st_plan, resp_plan, _ = http_req(f"{base}/api/plan", method="POST", body={"yaml": spec_plan, "scene_budget": True})
    assert st_plan == 200 and resp_plan["ok"] is True
    rel = resp_plan["relatorio"]
    assert "tarefas" in rel and "teto_pior_caso" in rel.get("orcamento_cena", {}) and "estimativa" in rel.get("orcamento_cena", {})


def test_run_allowlist_precheck_sync_422(test_server):
    base, *_ = test_server
    spec_fora = SPEC_VALIDO.replace("destino_exportacao: ~/.local/state/forge3d/saida/teste", "destino_exportacao: /outside/allowlist/dest")
    st, resp, _ = http_req(f"{base}/api/run", method="POST", body={"yaml": spec_fora})
    assert st == 422 and resp["codigo"] == "FORGE-E-DESTINO"

    st_jobs, resp_jobs, _ = http_req(f"{base}/api/jobs")
    assert st_jobs == 200 and len(resp_jobs["jobs"]) == 0


def test_upload_cloud_and_gc(test_server):
    base, home, *_ = test_server
    glb = home / "upload_test.glb"
    glb.write_bytes(b"glTF" + b"\x00" * 30)

    st_cd, resp_cd, _ = http_req(f"{base}/api/upload-cloud", method="POST", body={"arquivo": str(glb), "tipo": "Model", "creator_id": "12345"})
    assert st_cd == 200 and resp_cd["ok"] is True and resp_cd["relatorio"]["dry_run"] is True

    st_cb, resp_cb, _ = http_req(f"{base}/api/upload-cloud", method="POST", body={"arquivo": str(glb), "tipo": "Model", "dry_run": False})
    assert st_cb == 400 and resp_cb["codigo"] == "FORGE-E-REQUISICAO"

    st_gc, resp_gc, _ = http_req(f"{base}/api/gc", method="POST", body={"aplicar": False, "manter_dias": 30})
    assert st_gc == 200 and resp_gc["ok"] is True and resp_gc["aplicado"] is False
    assert not (home / "saida").exists() or len(list((home / "saida").iterdir())) == 0


# ==============================================================================
# 5. Full Pipeline E2E over HTTP
# ==============================================================================


def test_pipeline_e2e_non_blender(test_server):
    base, home, *_ = test_server
    st_canc, _, _ = http_req(f"{base}/api/jobs/job_inexistente/cancel", method="POST", body={})
    assert st_canc == 404

    origem = _publicar_valido(home / "saida", asset_id="prop.sync.01")
    asset_id = "prop.sync.01"

    st_assets, resp_assets, _ = http_req(f"{base}/api/assets?destino={origem}")
    assert st_assets == 200 and any(a["asset_id"] == asset_id for a in resp_assets["ativos"])

    st_det, resp_det, _ = http_req(f"{base}/api/asset?destino={origem}&id={asset_id}")
    assert st_det == 200 and resp_det["ok"] is True and resp_det["asset_id"] == asset_id
    mesh_f = next(f for f in resp_det["arquivos"] if f["papel"] == "mesh")

    st_file, data_file, h_file = http_req(f"{base}/api/file?path={mesh_f['caminho_abs']}")
    assert st_file == 200 and h_file.get("Content-Type") == "model/gltf-binary" and data_file.startswith(b"glTF")

    st_zip, zip_bytes, h_zip = http_req(f"{base}/api/asset/bundle.zip?destino={origem}&id={asset_id}")
    assert st_zip == 200 and h_zip.get("Content-Type") == "application/zip"
    zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    assert f"{asset_id}.manifest.json" in zf.namelist() and f"{asset_id}.glb" in zf.namelist()

    st_runs, resp_runs, _ = http_req(f"{base}/api/runs")
    assert st_runs == 200 and "runs" in resp_runs
    st_led, resp_led, _ = http_req(f"{base}/api/ledger")
    assert st_led == 200 and "eventos" in resp_led

    st_ver, resp_ver, _ = http_req(f"{base}/api/verify", method="POST", body={"destino": str(origem)})
    assert st_ver == 200 and resp_ver["ok"] is True and resp_ver["exit"] == 0

    sync_alvo = home / "synced_output"
    sync_alvo.mkdir(parents=True, exist_ok=True)
    config.adicionar(sync_alvo)
    st_sync, resp_sync, _ = http_req(f"{base}/api/sync", method="POST", body={"origem": str(origem), "para": str(sync_alvo)})
    assert st_sync == 200 and resp_sync["ok"] is True and (sync_alvo / f"{asset_id}.glb").is_file()

    acc_man = home / "saida" / "acc.manifest.json"
    (home / "saida" / "acc_baseColor.png").write_bytes(PNG_1X1)
    (home / "saida" / "acc.glb").write_bytes(b"glTF" + b"\x00" * 30)
    acc_man.write_text(json.dumps({
        "schema": "forge3d/manifest@6",
        "asset_id": "acc.01",
        "tipo": "acessorio",
        "files": [
            {"caminho": "acc.glb", "papel": "mesh"},
            {"caminho": "acc_baseColor.png", "papel": "textura"},
        ],
    }), encoding="utf-8")

    st_surf, resp_surf, _ = http_req(f"{base}/api/export", method="POST", body={"tipo": "surface", "origem": str(acc_man)})
    assert st_surf == 200 and resp_surf["ok"] is True and resp_surf["download_url"] is not None and Path(resp_surf["saida"]).is_file()

    st_acc, resp_acc, _ = http_req(f"{base}/api/export", method="POST", body={"tipo": "acessorio", "origem": str(acc_man)})
    assert st_acc == 200 and resp_acc["ok"] is True and resp_acc["download_url"] is not None and Path(resp_acc["saida"]).is_file()

    st_unk, err_unk, _ = http_req(
        f"{base}/api/export",
        method="POST",
        body={"tipo": "anim", "lote": "examples/lote_09_r15.yaml", "item": "personagem.r15.guard.01", "clipes": ["idle", "inexistente"]},
    )
    assert st_unk == 422 and err_unk["codigo"] == "FORGE-E-SPEC"


@pytest.mark.blender
def test_pipeline_e2e_blender(test_server):
    base, home, *_ = test_server
    dest, asset_id = paths.dir_saida() / "e2e_blender", "prop.caixa.ui.01"
    spec_yaml = f"""schema: forge3d/spec@6
projeto: demo
perfil: godot4
destino_exportacao: {dest}
estilo_global: blocky_voxel
paleta: ["#8a9099", "#3b4048", "#1d2024", "#ff6a1f", "#38e8ff"]
lote:
  - id: {asset_id}
    tipo: prop_estatico
    rota: blocky
    prompt: "Caixa de teste UI dashboard"
    altura_metros: 0.40
    pivot: base
    limite_triangulos: 400
    colisao: box
"""
    st_run, resp_run, _ = http_req(f"{base}/api/run", method="POST", body={"yaml": spec_yaml})
    assert st_run == 202 and resp_run["ok"] is True
    jid = resp_run["job_id"]

    for _ in range(60):
        time.sleep(0.5)
        st_j, job, _ = http_req(f"{base}/api/jobs/{jid}")
        assert st_j == 200
        if job.get("status") in ("done", "error", "cancelled"):
            assert job.get("status") == "done", f"Job falhou: {job.get('erro')}"
            assert job.get("exit_code") == 0
            break
    else:
        pytest.fail(f"Timeout aguardando conclusao do job {jid}")

    st_assets, resp_assets, _ = http_req(f"{base}/api/assets?destino={dest}")
    assert st_assets == 200 and resp_assets["total"] == 1 and resp_assets["ativos"][0]["asset_id"] == asset_id

    st_det, resp_det, _ = http_req(f"{base}/api/asset?destino={dest}&id={asset_id}")
    assert st_det == 200 and resp_det["ok"] is True
    mesh_f = next(f for f in resp_det["arquivos"] if f["papel"] == "mesh")

    st_file, data_file, h_file = http_req(f"{base}/api/file?path={mesh_f['caminho_abs']}")
    assert st_file == 200 and h_file.get("Content-Type") == "model/gltf-binary" and data_file.startswith(b"glTF")

    st_zip, zip_bytes, _ = http_req(f"{base}/api/asset/bundle.zip?destino={dest}&id={asset_id}")
    assert st_zip == 200
    zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    assert any(n.endswith(".manifest.json") for n in zf.namelist()) and any(n.endswith(".glb") for n in zf.namelist())

    st_ver, resp_ver, _ = http_req(f"{base}/api/verify", method="POST", body={"destino": str(dest)})
    assert st_ver == 200 and resp_ver["ok"] is True and resp_ver["exit"] == 0

    st_r15, resp_r15, _ = http_req(f"{base}/api/export", method="POST", body={"tipo": "r15", "lote": "examples/lote_09_r15.yaml", "item": "personagem.r15.guard.01"})
    assert st_r15 == 200 and resp_r15["ok"] is True and resp_r15["download_url"] is not None

    st_anim, resp_anim, _ = http_req(f"{base}/api/export", method="POST", body={"tipo": "anim", "lote": "examples/lote_09_r15.yaml", "item": "personagem.r15.guard.01", "clipe": "walk"})
    assert st_anim == 200 and resp_anim["ok"] is True and resp_anim["download_url"] is not None

    st_multi, resp_multi, _ = http_req(
        f"{base}/api/export",
        method="POST",
        body={"tipo": "anim", "lote": "examples/lote_09_r15.yaml", "item": "personagem.r15.guard.01", "clipes": ["idle", "walk"]},
    )
    assert st_multi == 200 and resp_multi["ok"] is True and resp_multi["download_url"] is not None

    sync_dest = home / "e2e_synced"
    sync_dest.mkdir(parents=True, exist_ok=True)
    config.adicionar(sync_dest)
    st_sync, resp_sync, _ = http_req(f"{base}/api/sync", method="POST", body={"origem": str(dest), "para": str(sync_dest)})
    assert st_sync == 200 and resp_sync["ok"] is True and (sync_dest / f"{asset_id}.glb").is_file()

    st_runs, resp_runs, _ = http_req(f"{base}/api/runs")
    assert st_runs == 200 and resp_runs["total"] >= 1
    st_led, resp_led, _ = http_req(f"{base}/api/ledger")
    assert st_led == 200 and resp_led["total"] >= 1
