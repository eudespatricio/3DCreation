"""Testes do servidor MCP stdio (JSON-RPC 2.0) e subcomando `forge3d mcp`."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path

from forge3d import mcp_server
from tests.test_sync import _publicar_valido

RAIZ = Path(__file__).resolve().parents[1]


def _lote_valido(tmp_path: Path, destino: Path) -> Path:
    spec = tmp_path / "lote.yaml"
    spec.write_text(
        "\n".join(
            [
                "schema: forge3d/spec@3",
                "projeto: mcp_demo",
                "perfil: godot4",
                f"destino_exportacao: {destino}",
                "estilo_global: blocky_voxel",
                "lote:",
                "  - id: prop.caixa.mcp.01",
                "    tipo: prop_estatico",
                "    rota: blocky",
                '    prompt: "caixa mcp"',
                "    altura_metros: 0.5",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return spec


def test_mcp_initialize_notificacao_e_tools_list():
    entrada = io.StringIO(
        "\n".join(
            [
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {"protocolVersion": "2024-11-05"},
                    }
                ),
                json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
                json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
                json.dumps({"jsonrpc": "2.0", "id": 3, "method": "ping"}),
            ]
        )
        + "\n"
    )
    saida = io.StringIO()
    rc = mcp_server.servir(entrada=entrada, saida=saida)
    assert rc == 0

    linhas = [json.loads(ln) for ln in saida.getvalue().splitlines() if ln.strip()]
    assert [r["id"] for r in linhas] == [1, 2, 3]
    assert linhas[0]["result"]["protocolVersion"] == "2024-11-05"
    assert linhas[0]["result"]["serverInfo"]["name"] == "forge3d"

    nomes = [t["name"] for t in linhas[1]["result"]["tools"]]
    assert nomes == [
        "forge3d_doctor",
        "forge3d_validate",
        "forge3d_plan",
        "forge3d_run",
        "forge3d_verify",
        "forge3d_query",
    ]
    assert linhas[2]["result"] == {}


def test_mcp_erros_jsonrpc():
    entrada = io.StringIO(
        "\n".join(
            [
                "{json-quebrado",
                json.dumps({"jsonrpc": "2.0", "id": 10, "method": "nao/existe"}),
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 11,
                        "method": "tools/call",
                        "params": {"name": "ferramenta_inexistente", "arguments": {}},
                    }
                ),
            ]
        )
        + "\n"
    )
    saida = io.StringIO()
    mcp_server.servir(entrada=entrada, saida=saida)
    resps = [json.loads(ln) for ln in saida.getvalue().splitlines() if ln.strip()]
    assert resps[0]["error"]["code"] == -32700
    assert resps[1]["error"]["code"] == -32601
    assert resps[2]["error"]["code"] == -32602


def test_mcp_chama_doctor_validate_plan_verify_query_e_run(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE3D_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("FORGE3D_CONFIG", str(tmp_path / "config"))

    # 1. doctor
    r_doc = mcp_server.processar_mensagem(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "forge3d_doctor", "arguments": {}},
        }
    )
    assert r_doc is not None and r_doc["result"]["isError"] is False
    doc_payload = json.loads(r_doc["result"]["content"][0]["text"])
    assert "checks" in doc_payload

    # 2. validate + plan
    destino = tmp_path / "state" / "saida" / "mcp"
    lote = _lote_valido(tmp_path, destino)
    r_val = mcp_server.processar_mensagem(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "forge3d_validate", "arguments": {"lote": str(lote)}},
        }
    )
    val_payload = json.loads(r_val["result"]["content"][0]["text"])
    assert r_val["result"]["isError"] is False
    assert val_payload["projeto"] == "mcp_demo"
    assert val_payload["itens"] == 1

    r_plan = mcp_server.processar_mensagem(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "forge3d_plan", "arguments": {"lote": str(lote)}},
        }
    )
    plan_payload = json.loads(r_plan["result"]["content"][0]["text"])
    assert r_plan["result"]["isError"] is False
    assert plan_payload["comando"] == "plan"
    assert plan_payload["plano"]["total"] == 1
    assert not destino.exists()

    # Spec inexistente devolve isError=True estruturado
    r_err = mcp_server.processar_mensagem(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "forge3d_validate",
                "arguments": {"lote": str(tmp_path / "faltando.yaml")},
            },
        }
    )
    assert r_err["result"]["isError"] is True
    assert json.loads(r_err["result"]["content"][0]["text"])["erro"]["codigo"] == "FORGE-E-SPEC"

    # 3. verify + query sobre destino publicado sintetico (sem Blender)
    origem = _publicar_valido(tmp_path, asset_id="prop.mcp.01")
    r_ver = mcp_server.processar_mensagem(
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {"name": "forge3d_verify", "arguments": {"destino": str(origem)}},
        }
    )
    assert r_ver["result"]["isError"] is False
    assert json.loads(r_ver["result"]["content"][0]["text"])["ok"] is True

    # Adultera GLB -> isError=True no verify
    (origem / "prop.mcp.01.glb").write_bytes(b"adulterado")
    r_ver_fail = mcp_server.processar_mensagem(
        {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {"name": "forge3d_verify", "arguments": {"destino": str(origem)}},
        }
    )
    assert r_ver_fail["result"]["isError"] is True
    assert json.loads(r_ver_fail["result"]["content"][0]["text"])["ok"] is False

    r_q = mcp_server.processar_mensagem(
        {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {"name": "forge3d_query", "arguments": {"projeto": "demo"}},
        }
    )
    q_payload = json.loads(r_q["result"]["content"][0]["text"])
    assert r_q["result"]["isError"] is False
    assert q_payload["total"] == 1
    assert q_payload["assets"][0]["asset_id"] == "prop.mcp.01"

    # 4. run delegando a pipeline.executar
    monkeypatch.setattr(
        mcp_server.pipeline,
        "executar",
        lambda path, plano_apenas=False, publicar_arquivos=True: (
            {"comando": "run", "exit": 0, "publicar_arquivos": publicar_arquivos},
            0,
        ),
    )
    r_run = mcp_server.processar_mensagem(
        {
            "jsonrpc": "2.0",
            "id": 8,
            "method": "tools/call",
            "params": {
                "name": "forge3d_run",
                "arguments": {"lote": str(lote), "nao_publicar": True},
            },
        }
    )
    run_payload = json.loads(r_run["result"]["content"][0]["text"])
    assert r_run["result"]["isError"] is False
    assert run_payload["publicar_arquivos"] is False


def test_cli_subcomando_mcp_stdio(tmp_path):
    env = dict(os.environ)
    env["FORGE3D_HOME"] = str(tmp_path / "state")
    env["FORGE3D_CONFIG"] = str(tmp_path / "config")
    env["FORGE3D_ROOT"] = str(RAIZ)
    entrada = "\n".join(
        [
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": "forge3d_query", "arguments": {}},
                }
            ),
        ]
    ) + "\n"
    proc = subprocess.run(
        [sys.executable, "-m", "forge3d.cli.main", "mcp"],
        cwd=str(RAIZ),
        env=env,
        input=entrada,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    linhas = [json.loads(ln) for ln in proc.stdout.splitlines() if ln.strip()]
    assert [r["id"] for r in linhas] == [1, 2, 3]
    assert len(linhas[1]["result"]["tools"]) == 6
    assert json.loads(linhas[2]["result"]["content"][0]["text"])["total"] == 0
