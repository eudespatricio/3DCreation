"""Geracao de ``Assets.lua`` para Rojo com isolamento opcional por projeto/destino."""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import upload
from .errors import erro_spec
from .sync_common import (
    _IDENTIFICADOR_LUAU,
    _checar_destino_externo,
    _escapar_literal,
    _escrever_atomico,
)


@dataclass(frozen=True)
class EscopoRojo:
    """Filtro explicito de isolamento do ledger para ``sync --rojo-lua``."""

    origem: Path | None
    destino: Path | None
    asset_ids: set[str]
    projetos: set[str]
    restringir_projetos: bool = False


def coletar_escopo_origem(origem: Path) -> tuple[set[str], set[str]]:
    """Extrai ``(asset_ids, projetos)`` dos manifestos publicados em ``origem``."""
    asset_ids: set[str] = set()
    projetos: set[str] = set()
    if not origem.is_dir():
        return asset_ids, projetos
    for arq in sorted(origem.glob("*.manifest.json")):
        try:
            dados = json.loads(arq.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if not isinstance(dados, dict):
            continue
        aid = str(dados.get("asset_id") or dados.get("id") or "").strip()
        if aid:
            asset_ids.add(aid)
        proj = str(dados.get("projeto") or "").strip()
        if proj:
            projetos.add(proj)
    return asset_ids, projetos


def _registro_pertence_escopo(rec: object, escopo: EscopoRojo) -> bool:
    if not isinstance(rec, dict) or rec.get("evento") == "run":
        return False

    rec_proj = str(rec.get("projeto") or rec.get("project") or "").strip()
    if rec_proj and (escopo.restringir_projetos or escopo.projetos) and rec_proj not in escopo.projetos:
        return False

    for chave in ("destino", "origem", "dest", "publish_dir"):
        val = str(rec.get(chave) or "").strip()
        if not val:
            continue
        val_res = Path(val).expanduser().resolve(strict=False)
        ok_origem = escopo.origem is not None and val_res == escopo.origem
        ok_destino = escopo.destino is not None and val_res == escopo.destino
        if not ok_origem and not ok_destino:
            return False

    arq = str(rec.get("arquivo") or "").strip()
    if arq:
        arq_p = Path(arq).expanduser()
        if not arq_p.is_absolute():
            return False
        arq_res = arq_p.resolve(strict=False)
        em_origem = escopo.origem is not None and arq_res.is_relative_to(escopo.origem)
        em_destino = escopo.destino is not None and arq_res.is_relative_to(escopo.destino)
        if not em_origem and not em_destino:
            return False

    return True


def _formatar_rbxassetid(valor: str) -> str:
    limpo = valor.strip()
    if limpo.startswith("rbxassetid://"):
        return limpo
    return f"rbxassetid://{limpo}"


def _extrair_pares_registro(rec: dict) -> list[tuple[str, str]]:
    if not isinstance(rec, dict):
        return []
    if rec.get("evento") == "run":
        return []

    schema = str(rec.get("schema") or "")
    eh_manifesto = schema.startswith("forge3d/manifest@") or ("files" in rec and "qc" in rec)
    if eh_manifesto:
        logical_id = str(rec.get("asset_id") or rec.get("id") or "").strip()
        raw_rbx = (
            rec.get("rbxassetid")
            or rec.get("roblox_asset_id")
            or (rec.get("roblox") or {}).get("asset_id")
            or (rec.get("roblox") or {}).get("assetId")
            or (rec.get("upload") or {}).get("asset_id")
            or (rec.get("upload") or {}).get("assetId")
        )
        if logical_id and raw_rbx is not None and str(raw_rbx).strip():
            return [(logical_id, _formatar_rbxassetid(str(raw_rbx)))]
        return []

    if "roblox_asset_id" in rec or "roblox" in rec or "upload" in rec:
        logical_id = str(
            rec.get("id")
            or rec.get("item_id")
            or rec.get("forge3d_id")
            or rec.get("asset_id")
            or rec.get("nome")
            or rec.get("name")
            or ""
        ).strip()
        raw_rbx = (
            rec.get("roblox_asset_id")
            or rec.get("rbxassetid")
            or (rec.get("roblox") or {}).get("asset_id")
            or (rec.get("roblox") or {}).get("assetId")
            or (rec.get("upload") or {}).get("asset_id")
            or (rec.get("upload") or {}).get("assetId")
        )
        if logical_id and raw_rbx is not None and str(raw_rbx).strip():
            return [(logical_id, _formatar_rbxassetid(str(raw_rbx)))]
        return []

    tem_chave_id = any(
        k in rec for k in ("id", "item_id", "forge3d_id", "nome", "name", "displayName", "arquivo")
    )
    tem_chave_rbx = any(k in rec for k in ("rbxassetid", "asset_id", "assetId"))
    if tem_chave_id and tem_chave_rbx:
        logical_id = str(
            rec.get("id")
            or rec.get("item_id")
            or rec.get("forge3d_id")
            or rec.get("nome")
            or rec.get("name")
            or rec.get("displayName")
            or ""
        ).strip()
        if not logical_id and rec.get("arquivo"):
            logical_id = Path(str(rec["arquivo"])).stem
        raw_rbx = rec.get("rbxassetid") or rec.get("asset_id") or rec.get("assetId")
        if logical_id and raw_rbx is not None and str(raw_rbx).strip():
            return [(logical_id, _formatar_rbxassetid(str(raw_rbx)))]
        return []

    pares: list[tuple[str, str]] = []
    if all(isinstance(v, (str, int)) and not isinstance(v, bool) for v in rec.values()):
        for k in sorted(rec):
            val = str(rec[k]).strip()
            if str(k).strip() and val:
                pares.append((str(k).strip(), _formatar_rbxassetid(val)))
    return pares


def _ler_fonte_assets(
    fonte: str | os.PathLike | dict,
    mapa: dict[str, str | dict[str, str]],
    escopo: EscopoRojo | None = None,
) -> None:
    if isinstance(fonte, dict):
        if escopo is not None and not _registro_pertence_escopo(fonte, escopo):
            return
        for k, v in _extrair_pares_registro(fonte):
            if escopo is None or k in escopo.asset_ids:
                mapa[k] = v
        return

    caminho = Path(fonte).expanduser()
    if not caminho.exists():
        return
    if caminho.is_dir():
        dir_res = caminho.resolve(strict=False)
        for arq in sorted(caminho.glob("*.manifest.json")):
            try:
                dados = json.loads(arq.read_text(encoding="utf-8"))
            except ValueError:
                continue
            if not isinstance(dados, dict):
                continue
            if escopo is not None:
                rec_escopo = dict(dados)
                if escopo.origem is not None or escopo.destino is not None:
                    rec_escopo.setdefault("origem", str(dir_res))
                if not _registro_pertence_escopo(rec_escopo, escopo):
                    continue
            for k, v in _extrair_pares_registro(dados):
                if escopo is None or k in escopo.asset_ids:
                    mapa[k] = v
        return

    if caminho.is_file():
        if caminho.suffix.lower() in (".jsonl", ".ndjson"):
            por_id: dict[str, dict[str, str]] = {}
            for linha in caminho.read_text(encoding="utf-8").splitlines():
                texto = linha.strip()
                if not texto:
                    continue
                try:
                    dados = json.loads(texto)
                except ValueError:
                    continue
                if escopo is not None and not _registro_pertence_escopo(dados, escopo):
                    continue
                lids_com_role: set[str] = set()
                for lid, role, uri in upload._extrair_entradas_ledger(dados):
                    if role and (escopo is None or lid in escopo.asset_ids):
                        por_id.setdefault(lid, {})[role] = uri
                        lids_com_role.add(lid)
                for k, v in _extrair_pares_registro(dados):
                    if escopo is None or k in escopo.asset_ids:
                        mapa[k] = v
                        if k not in lids_com_role:
                            por_id.pop(k, None)
            for lid, roles in por_id.items():
                if len(roles) > 1:
                    mapa[lid] = {r: roles[r] for r in sorted(roles)}
            return
        try:
            dados = json.loads(caminho.read_text(encoding="utf-8"))
        except ValueError:
            return
        if isinstance(dados, list):
            for item in dados:
                if escopo is not None and not _registro_pertence_escopo(item, escopo):
                    continue
                for k, v in _extrair_pares_registro(item):
                    if escopo is None or k in escopo.asset_ids:
                        mapa[k] = v
        elif isinstance(dados, dict):
            if escopo is not None and not _registro_pertence_escopo(dados, escopo):
                return
            for k, v in _extrair_pares_registro(dados):
                if escopo is None or k in escopo.asset_ids:
                    mapa[k] = v


def _formatar_luau_valor(valor: str | dict[str, str], nivel: int = 1) -> str:
    if isinstance(valor, dict):
        if not valor:
            return "{}"
        tab = "\t" * (nivel + 1)
        tab_fim = "\t" * nivel
        itens = "\n".join(
            f'{tab}["{_escapar_literal(str(k))}"] = "{_escapar_literal(str(valor[k]))}",'
            for k in sorted(valor)
        )
        return f"{{\n{itens}\n{tab_fim}}}"
    return f'"{_escapar_literal(str(valor))}"'


def _formatar_luau_any(valor: Any, nivel: int = 1) -> str:
    if isinstance(valor, bool):
        return "true" if valor else "false"
    if isinstance(valor, (int, float)):
        return str(valor)
    if valor is None:
        return "nil"
    if isinstance(valor, str):
        return f'"{_escapar_literal(valor)}"'
    if isinstance(valor, list):
        if not valor:
            return "{}"
        tab = "\t" * (nivel + 1)
        tab_fim = "\t" * nivel
        itens = "\n".join(f"{tab}{_formatar_luau_any(v, nivel=nivel + 1)}," for v in valor)
        return f"{{\n{itens}\n{tab_fim}}}"
    if isinstance(valor, dict):
        if not valor:
            return "{}"
        tab = "\t" * (nivel + 1)
        tab_fim = "\t" * nivel
        itens = "\n".join(
            f'{tab}["{_escapar_literal(str(k))}"] = {_formatar_luau_any(valor[k], nivel=nivel + 1)},'
            for k in sorted(valor)
        )
        return f"{{\n{itens}\n{tab_fim}}}"
    return f'"{_escapar_literal(str(valor))}"'


def _coletar_meta_manifesto(
    dados: dict,
    meta_out: dict[str, dict[str, Any]],
    escopo: EscopoRojo | None,
) -> None:
    schema = str(dados.get("schema") or "")
    if not (schema.startswith("forge3d/manifest@") or ("files" in dados and "qc" in dados)):
        return
    aid = str(dados.get("asset_id") or dados.get("id") or "").strip()
    if not aid or (escopo is not None and aid not in escopo.asset_ids):
        return
    entry: dict[str, Any] = {}
    for campo in ("anexo", "sockets", "partes"):
        val = dados.get(campo)
        if val:
            entry[campo] = val
    if entry:
        meta_out[aid] = entry


def coletar_metadados_manifestos(
    fontes: str | os.PathLike | dict | Iterable[str | os.PathLike | dict] | None,
    escopo: EscopoRojo | None = None,
) -> dict[str, dict[str, Any]]:
    """Coleta metadados estruturais (``anexo``, ``sockets``, ``partes``) de manifestos."""
    if fontes is None:
        lista: list[str | os.PathLike | dict] = []
    elif isinstance(fontes, (str, os.PathLike, dict)):
        lista = [fontes]
    else:
        lista = list(fontes)

    meta: dict[str, dict[str, Any]] = {}
    for fonte in lista:
        if isinstance(fonte, dict):
            if escopo is None or _registro_pertence_escopo(fonte, escopo):
                _coletar_meta_manifesto(fonte, meta, escopo)
            continue
        caminho = Path(fonte).expanduser()
        if not caminho.exists():
            continue
        if caminho.is_dir():
            dir_res = caminho.resolve(strict=False)
            for arq in sorted(caminho.glob("*.manifest.json")):
                try:
                    dados = json.loads(arq.read_text(encoding="utf-8"))
                except ValueError:
                    continue
                if not isinstance(dados, dict):
                    continue
                if escopo is not None:
                    rec_escopo = dict(dados)
                    if escopo.origem is not None or escopo.destino is not None:
                        rec_escopo.setdefault("origem", str(dir_res))
                    if not _registro_pertence_escopo(rec_escopo, escopo):
                        continue
                _coletar_meta_manifesto(dados, meta, escopo)
        elif caminho.is_file() and caminho.suffix.lower() == ".json":
            try:
                dados = json.loads(caminho.read_text(encoding="utf-8"))
            except ValueError:
                continue
            itens = dados if isinstance(dados, list) else ([dados] if isinstance(dados, dict) else [])
            for item in itens:
                if isinstance(item, dict) and (escopo is None or _registro_pertence_escopo(item, escopo)):
                    _coletar_meta_manifesto(item, meta, escopo)
    return {k: meta[k] for k in sorted(meta)}


def gerar_assets_lua(
    fontes_ou_ledger: str | os.PathLike | dict | Iterable[str | os.PathLike | dict] | None,
    destino_lua: str | os.PathLike,
    namespace: str = "Assets",
    *,
    origem_escopo: str | os.PathLike | None = None,
    destino_escopo: str | os.PathLike | None = None,
    asset_ids_permitidos: Iterable[str] | None = None,
    projetos_permitidos: Iterable[str] | None = None,
    incluir_metadados: bool = False,
) -> dict:
    """Gera modulo Luau ``Assets.lua`` deterministico (``id -> rbxassetid://<asset_id>`` ou mapa por role)."""
    if not _IDENTIFICADOR_LUAU.match(namespace or ""):
        raise erro_spec(f"namespace Luau invalido: {namespace!r}", namespace=namespace)

    destino = _checar_destino_externo(destino_lua, campo="rojo_lua")
    if fontes_ou_ledger is None:
        fontes: list[str | os.PathLike | dict] = []
    elif isinstance(fontes_ou_ledger, (str, os.PathLike, dict)):
        fontes = [fontes_ou_ledger]
    else:
        fontes = list(fontes_ou_ledger)

    escopo: EscopoRojo | None = None
    if (
        origem_escopo is not None
        or destino_escopo is not None
        or asset_ids_permitidos is not None
        or projetos_permitidos is not None
    ):
        orig_res = (
            Path(origem_escopo).expanduser().resolve(strict=False)
            if origem_escopo is not None
            else None
        )
        dest_res = (
            Path(destino_escopo).expanduser().resolve(strict=False)
            if destino_escopo is not None
            else None
        )
        coletados_ids, coletados_projs = (
            coletar_escopo_origem(orig_res) if orig_res is not None else (set(), set())
        )
        ids_final = (
            set(asset_ids_permitidos) if asset_ids_permitidos is not None else coletados_ids
        )
        projs_final = (
            set(projetos_permitidos) if projetos_permitidos is not None else coletados_projs
        )
        escopo = EscopoRojo(
            origem=orig_res,
            destino=dest_res,
            asset_ids=ids_final,
            projetos=projs_final,
            restringir_projetos=(origem_escopo is not None or projetos_permitidos is not None),
        )

    mapa: dict[str, str | dict[str, str]] = {}
    for fonte in fontes:
        _ler_fonte_assets(fonte, mapa, escopo=escopo)

    ordenado = {k: mapa[k] for k in sorted(mapa)}
    if ordenado:
        entradas = "\n".join(
            f'\t["{_escapar_literal(k)}"] = {_formatar_luau_valor(v, nivel=1)},'
            for k, v in ordenado.items()
        )
        corpo = f"{{\n{entradas}\n}}"
    else:
        corpo = "{}"

    metadados: dict[str, dict[str, Any]] = (
        coletar_metadados_manifestos(fontes, escopo=escopo) if incluir_metadados else {}
    )
    bloco_meta = (
        f"\n{namespace}._meta = {_formatar_luau_any(metadados, nivel=0)}\n"
        if metadados
        else ""
    )

    conteudo = (
        "-- Gerado automaticamente pelo Forge3D. Nao editar manualmente.\n"
        f"local {namespace} = {corpo}\n"
        f"{bloco_meta}\n"
        f"return {namespace}\n"
    )
    _escrever_atomico(destino, conteudo, f"rojo-{os.getpid()}")
    return {
        "ok": True,
        "saida": str(destino),
        "namespace": namespace,
        "total": len(ordenado),
        "assets": ordenado,
        **({"metadados": metadados} if incluir_metadados else {}),
    }
