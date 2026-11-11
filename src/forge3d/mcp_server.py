"""Servidor MCP (JSON-RPC 2.0 sobre stdio, stdlib pura) para ferramentas do Forge3D.

Exposicoes: ``forge3d_doctor``, ``forge3d_validate``, ``forge3d_plan``, ``forge3d_run``,
``forge3d_verify`` e ``forge3d_query``, delegando aos modulos internos sem shell e sem atalhos
de contrato (I1-I15).
"""

from __future__ import annotations

import contextlib
import json
import sys
from pathlib import Path
from typing import Any, TextIO

from . import __version__, doctor, pipeline, publish, spec
from .errors import EXIT_AMBIENTE, ForgeError, erro_interno, erro_spec

__all__ = ["TOOLS", "processar_mensagem", "servir"]

PROTOCOLOS_SUPORTADOS = ("2024-11-05", "2025-03-26")

TOOLS: list[dict[str, Any]] = [
    {
        "name": "forge3d_doctor",
        "description": "Executa o preflight do ambiente Forge3D e retorna diagnostico JSON.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    {
        "name": "forge3d_validate",
        "description": "Normaliza e valida um lote YAML/JSON contra spec@1..@3 e regras B1-B17.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "lote": {"type": "string", "description": "Caminho para o arquivo de lote."},
            },
            "required": ["lote"],
            "additionalProperties": False,
        },
    },
    {
        "name": "forge3d_plan",
        "description": "Monta o plano de execucao (cache, estimativas, bloqueios) sem gerar assets.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "lote": {"type": "string", "description": "Caminho para o arquivo de lote."},
            },
            "required": ["lote"],
            "additionalProperties": False,
        },
    },
    {
        "name": "forge3d_run",
        "description": "Executa o pipeline completo (gerar -> pos-processar -> QC -> publicar).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "lote": {"type": "string", "description": "Caminho para o arquivo de lote."},
                "nao_publicar": {
                    "type": "boolean",
                    "description": "Quando verdadeiro, executa e valida QC sem gravar no destino.",
                    "default": False,
                },
            },
            "required": ["lote"],
            "additionalProperties": False,
        },
    },
    {
        "name": "forge3d_verify",
        "description": "Verifica manifestos, hashes SHA-256 e reexecuta gates G1-G10 no destino.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "destino": {"type": "string", "description": "Pasta publicada a verificar."},
                "only": {
                    "type": "string",
                    "description": "Recorte opcional: manifesto,hash,escala,pivo,gates.",
                },
            },
            "required": ["destino"],
            "additionalProperties": False,
        },
    },
    {
        "name": "forge3d_query",
        "description": "Consulta o indice SQLite de assets publicados.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "projeto": {"type": "string"},
                "perfil": {"type": "string"},
                "tag": {"type": "string"},
                "max_tris": {"type": "integer"},
            },
            "additionalProperties": False,
        },
    },
]

_NOMES_TOOLS = {t["name"] for t in TOOLS}


def _exigir_str(args: dict[str, Any], campo: str) -> str:
    valor = args.get(campo)
    if not isinstance(valor, str) or not valor.strip():
        raise erro_spec(f"parametro '{campo}' obrigatorio e nao vazio", campo=campo)
    return valor.strip()


def _executar_tool(nome: str, args: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    if nome == "forge3d_doctor":
        return doctor.checar(), False

    if nome == "forge3d_validate":
        lote = _exigir_str(args, "lote")
        doc = spec.carregar_arquivo(lote)
        spec_doc, perfil, avisos = spec.preparar(doc)
        return {
            "ok": True,
            "lote": str(Path(lote)),
            "projeto": spec_doc["projeto"],
            "perfil": perfil.get("_nome", spec_doc["perfil"]),
            "destino": spec_doc["destino_exportacao"],
            "itens": len(spec_doc["lote"]),
            "avisos": avisos,
        }, False

    if nome == "forge3d_plan":
        lote = _exigir_str(args, "lote")
        relatorio, _codigo = pipeline.executar(lote, plano_apenas=True)
        return relatorio, False

    if nome == "forge3d_run":
        lote = _exigir_str(args, "lote")
        nao_publicar = bool(args.get("nao_publicar", False))
        relatorio, codigo = pipeline.executar(
            lote, plano_apenas=False, publicar_arquivos=not nao_publicar
        )
        return relatorio, codigo != 0

    if nome == "forge3d_verify":
        destino = _exigir_str(args, "destino")
        only = args.get("only")
        if only is not None and not isinstance(only, str):
            raise erro_spec("parametro 'only' precisa ser string", campo="only")
        relatorio = pipeline.verificar(destino, only=only)
        return relatorio, not bool(relatorio.get("ok", False))

    if nome == "forge3d_query":
        max_tris = args.get("max_tris")
        if max_tris is not None and isinstance(max_tris, bool):
            raise erro_spec("parametro 'max_tris' precisa ser inteiro", campo="max_tris")
        linhas = publish.consultar(
            projeto=args.get("projeto"),
            perfil=args.get("perfil"),
            max_tris=int(max_tris) if max_tris is not None else None,
            tag=args.get("tag"),
        )
        return {"schema": "forge3d/query@1", "total": len(linhas), "assets": linhas}, False

    raise ValueError(f"ferramenta desconhecida: {nome}")


def _resposta_erro(req_id: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": err}


def _resposta_ok(req_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _resultado_tool(payload: dict[str, Any], is_error: bool) -> dict[str, Any]:
    texto = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return {"content": [{"type": "text", "text": texto}], "isError": is_error}


def processar_mensagem(msg: Any) -> dict[str, Any] | None:
    """Processa uma mensagem JSON-RPC 2.0 e retorna a resposta (ou ``None`` se notificacao)."""
    if not isinstance(msg, dict) or not isinstance(msg.get("method"), str):
        req_id = msg.get("id") if isinstance(msg, dict) else None
        return _resposta_erro(req_id, -32600, "Invalid Request")

    metodo = msg["method"]
    eh_notificacao = "id" not in msg
    req_id = msg.get("id")
    params = msg.get("params")
    if params is None:
        params = {}
    if not isinstance(params, dict):
        if eh_notificacao:
            return None
        return _resposta_erro(req_id, -32602, "Invalid params: expected object")

    if metodo == "notifications/initialized" or metodo.startswith("notifications/"):
        return None

    if metodo == "initialize":
        if eh_notificacao:
            return None
        pedida = params.get("protocolVersion")
        versao = pedida if isinstance(pedida, str) and pedida in PROTOCOLOS_SUPORTADOS else "2024-11-05"
        return _resposta_ok(
            req_id,
            {
                "protocolVersion": versao,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "forge3d", "version": __version__},
            },
        )

    if metodo == "ping":
        return None if eh_notificacao else _resposta_ok(req_id, {})

    if metodo == "tools/list":
        return None if eh_notificacao else _resposta_ok(req_id, {"tools": TOOLS})

    if metodo == "tools/call":
        nome = params.get("name")
        if not isinstance(nome, str) or nome not in _NOMES_TOOLS:
            return None if eh_notificacao else _resposta_erro(req_id, -32602, f"Unknown tool: {nome!r}")
        argumentos = params.get("arguments")
        if argumentos is None:
            argumentos = {}
        if not isinstance(argumentos, dict):
            return None if eh_notificacao else _resposta_erro(
                req_id, -32602, "Invalid params: arguments must be an object"
            )
        try:
            with contextlib.redirect_stdout(sys.stderr):
                payload, is_err = _executar_tool(nome, argumentos)
            res = _resultado_tool(payload, is_err)
        except ForgeError as exc:
            res = _resultado_tool(
                {"ok": False, "exit": exc.exit_code, "erro": exc.como_dict()},
                True,
            )
        except Exception as exc:  # noqa: BLE001 - JSON-RPC nunca derruba por falha interna
            interno = erro_interno(f"{type(exc).__name__}: {exc}")
            res = _resultado_tool(
                {"ok": False, "exit": EXIT_AMBIENTE, "erro": interno.como_dict()},
                True,
            )
        return None if eh_notificacao else _resposta_ok(req_id, res)

    if eh_notificacao:
        return None
    return _resposta_erro(req_id, -32601, f"Method not found: {metodo}")


def servir(entrada: TextIO | None = None, saida: TextIO | None = None) -> int:
    """Loop stdio JSON-RPC 2.0 (uma mensagem JSON por linha)."""
    in_stream = entrada if entrada is not None else sys.stdin
    out_stream = saida if saida is not None else sys.stdout

    for linha in in_stream:
        bruto = linha.strip()
        if not bruto:
            continue
        try:
            msg = json.loads(bruto)
        except ValueError as exc:
            resp: dict[str, Any] | None = _resposta_erro(None, -32700, f"Parse error: {exc}")
        else:
            resp = processar_mensagem(msg)
        if resp is not None:
            out_stream.write(json.dumps(resp, ensure_ascii=False) + "\n")
            out_stream.flush()
    return 0
