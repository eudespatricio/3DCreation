"""Servidor MCP (JSON-RPC 2.0 sobre stdio, stdlib pura) para ferramentas do Forge3D.

Exposicoes: ``forge3d_doctor``, ``forge3d_validate``, ``forge3d_plan``, ``forge3d_run``,
``forge3d_verify`` e ``forge3d_query``, delegando aos modulos internos sem shell e sem atalhos
de contrato (I1-I15).
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
from pathlib import Path
from typing import Any, BinaryIO, TextIO

from . import __version__, doctor, pipeline, publish, spec
from .errors import EXIT_AMBIENTE, ForgeError, erro_interno, erro_spec

__all__ = ["TOOLS", "processar_mensagem", "servir"]

PROTOCOLOS_SUPORTADOS = ("2024-11-05", "2025-03-26")
MAX_CONTENT_LENGTH = 10 * 1024 * 1024

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
        "description": "Normaliza e valida um lote YAML/JSON contra spec@1..@4 e regras B1-B22.",
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
                "no_cache": {
                    "type": "boolean",
                    "description": "Quando verdadeiro, ignora o cache e projeta execucao completa.",
                    "default": False,
                },
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
                "no_cache": {
                    "type": "boolean",
                    "description": "Quando verdadeiro, ignora cache e forca nova geracao de todos os itens.",
                    "default": False,
                },
                "clean_dest": {
                    "type": "boolean",
                    "description": "Quando verdadeiro, remove manifestos e arquivos legados no destino que nao pertencem ao lote.",
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
        kw_plan: dict[str, Any] = {"plano_apenas": True}
        if "no_cache" in args:
            kw_plan["no_cache"] = bool(args["no_cache"])
        relatorio, _codigo = pipeline.executar(lote, **kw_plan)
        return relatorio, False

    if nome == "forge3d_run":
        lote = _exigir_str(args, "lote")
        nao_publicar = bool(args.get("nao_publicar", False))
        kw_run: dict[str, Any] = {
            "plano_apenas": False,
            "publicar_arquivos": not nao_publicar,
        }
        if "no_cache" in args:
            kw_run["no_cache"] = bool(args["no_cache"])
        if "clean_dest" in args:
            kw_run["clean_dest"] = bool(args["clean_dest"])
        relatorio, codigo = pipeline.executar(lote, **kw_run)
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


def _eh_binario(stream: Any) -> bool:
    if isinstance(stream, io.TextIOBase):
        return False
    if isinstance(stream, (io.BufferedIOBase, io.RawIOBase)):
        return True
    modo = getattr(stream, "mode", "")
    if isinstance(modo, str) and "b" in modo:
        return True
    try:
        return isinstance(stream.read(0), (bytes, bytearray))
    except Exception:  # noqa: BLE001
        return False


def _ler_corpo_binario(stream: Any, n_bytes: int) -> bytes:
    partes: list[bytes] = []
    restante = n_bytes
    while restante > 0:
        bloco = stream.read(restante)
        if not bloco:
            break
        partes.append(bloco)
        restante -= len(bloco)
    return b"".join(partes)


def _ler_corpo_texto(stream: Any, n_bytes: int) -> str:
    partes: list[str] = []
    lidos = 0
    while lidos < n_bytes:
        restante = n_bytes - lidos
        pedir = 1 if restante < 4 else max(1, restante // 4)
        chunk = stream.read(pedir)
        if not chunk:
            break
        partes.append(chunk)
        lidos += len(chunk.encode("utf-8"))
    return "".join(partes)


def _escrever_resposta(
    out_stream: Any,
    out_binario: bool,
    resp: dict[str, Any],
    framed: bool,
) -> None:
    payload = json.dumps(resp, ensure_ascii=False)
    if framed:
        n_bytes = len(payload.encode("utf-8"))
        texto = f"Content-Length: {n_bytes}\r\n\r\n{payload}"
    else:
        texto = f"{payload}\n"
    out_stream.write(texto.encode("utf-8") if out_binario else texto)
    out_stream.flush()


def servir(
    entrada: TextIO | BinaryIO | None = None,
    saida: TextIO | BinaryIO | None = None,
) -> int:
    """Loop stdio JSON-RPC 2.0 (autodetecta Content-Length framing ou NDJSON)."""
    in_stream: Any = (
        entrada if entrada is not None else (getattr(sys.stdin, "buffer", None) or sys.stdin)
    )
    out_stream: Any = (
        saida if saida is not None else (getattr(sys.stdout, "buffer", None) or sys.stdout)
    )
    in_binario = _eh_binario(in_stream)
    out_binario = _eh_binario(out_stream)
    framed: bool | None = None

    while True:
        linha_raw = in_stream.readline()
        if not linha_raw:
            break
        linha = linha_raw.decode("utf-8", errors="replace") if in_binario else linha_raw
        bruto = linha.strip()
        if not bruto:
            continue

        eh_cabecalho = (framed is True) or bruto.lower().startswith(
            ("content-length:", "content-type:")
        )
        if eh_cabecalho:
            if framed is None:
                framed = True
            content_length: int | None = None
            linha_hdr = bruto
            while linha_hdr:
                if ":" in linha_hdr:
                    chave, valor = linha_hdr.split(":", 1)
                    if chave.strip().lower() == "content-length":
                        try:
                            content_length = int(valor.strip())
                        except ValueError:
                            content_length = -1
                prox_raw = in_stream.readline()
                if not prox_raw:
                    break
                prox = prox_raw.decode("utf-8", errors="replace") if in_binario else prox_raw
                linha_hdr = prox.strip()

            if content_length is None or content_length < 0 or content_length > MAX_CONTENT_LENGTH:
                resp: dict[str, Any] | None = _resposta_erro(
                    None, -32700, "Parse error: missing or invalid Content-Length"
                )
            else:
                try:
                    if in_binario:
                        corpo_str = _ler_corpo_binario(in_stream, content_length).decode("utf-8")
                    else:
                        corpo_str = _ler_corpo_texto(in_stream, content_length)
                    msg = json.loads(corpo_str)
                except (ValueError, UnicodeDecodeError) as exc:
                    resp = _resposta_erro(None, -32700, f"Parse error: {exc}")
                else:
                    resp = processar_mensagem(msg)
        else:
            if framed is None:
                framed = False
            try:
                msg = json.loads(bruto)
            except ValueError as exc:
                resp = _resposta_erro(None, -32700, f"Parse error: {exc}")
            else:
                resp = processar_mensagem(msg)

        if resp is not None:
            _escrever_resposta(out_stream, out_binario, resp, bool(framed))
    return 0
