"""Acoes mutaveis e despachos de pipeline, verify, migrate, export, sync, upload e governanca."""

from __future__ import annotations

import copy
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import yaml

from .. import animacao, config, gc, migrate, paths, pipeline, profiles, publish, rbx, spec, sync, upload
from ..errors import ForgeError, erro_destino, erro_spec
from .state import (
    JobManager,
    erro_proibido,
    erro_requisicao,
    resolver_caminho_leitura,
    salvar_spec_ui,
)

_MAPA_UPLOAD_CMD = {"Model": "upload-model", "Image": "upload-image", "Animation": "upload-animation"}
_MAPA_UPLOAD_TIPO = {"model": "Model", "image": "Image", "animation": "Animation"}


def _negar_config(alvo: Path) -> None:
    raiz_cfg = paths.raiz_config().resolve(strict=False)
    res = alvo.resolve(strict=False)
    if res == raiz_cfg or res.is_relative_to(raiz_cfg):
        raise erro_proibido("acesso negado ao diretorio de configuracao do Forge3D", caminho=str(res))


def _limpar_chaves_privadas(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _limpar_chaves_privadas(v) for k, v in obj.items() if not str(k).startswith("_")}
    if isinstance(obj, list):
        return [_limpar_chaves_privadas(v) for v in obj]
    return obj


def _carregar_spec_payload(payload: dict[str, Any]) -> tuple[dict[str, Any], str, Path | None]:
    raw_yaml = payload.get("yaml")
    raw_caminho = payload.get("caminho") or payload.get("lote")
    if isinstance(raw_yaml, str) and raw_yaml.strip():
        try:
            doc = yaml.safe_load(raw_yaml)
        except yaml.YAMLError as exc:
            raise erro_spec(f"YAML invalido: {exc}") from exc
        if not isinstance(doc, dict):
            raise erro_spec("lote precisa ser um objeto no topo")
        return doc, raw_yaml, None
    if isinstance(raw_caminho, str) and raw_caminho.strip():
        arq = resolver_caminho_leitura(raw_caminho)
        doc = spec.carregar_arquivo(arq)
        return doc, arq.read_text(encoding="utf-8"), arq
    raise erro_requisicao("informe 'yaml' ou 'caminho' no corpo da requisicao")


def validar_spec(payload: dict[str, Any]) -> dict[str, Any]:
    doc, _texto, _arq = _carregar_spec_payload(payload)
    spec_doc, perfil, avisos = spec.preparar(copy.deepcopy(doc))
    return {
        "ok": True,
        "projeto": spec_doc["projeto"],
        "perfil": perfil.get("_nome", spec_doc["perfil"]),
        "destino": spec_doc["destino_exportacao"],
        "itens": len(spec_doc["lote"]),
        "avisos": avisos,
        "spec_canon": _limpar_chaves_privadas(spec_doc),
    }


def planejar_spec(payload: dict[str, Any]) -> dict[str, Any]:
    doc, texto, arq_existente = _carregar_spec_payload(payload)
    spec_doc, _perfil, _avisos = spec.preparar(copy.deepcopy(doc))
    config.validar_destino(spec_doc["destino_exportacao"])

    no_cache = bool(payload.get("no_cache", False))
    raw_sb = payload.get("scene_budget")
    scene_budget = True if raw_sb is None else bool(raw_sb)

    if arq_existente is not None:
        relatorio, codigo = pipeline.executar(
            arq_existente, plano_apenas=True, no_cache=no_cache, scene_budget=scene_budget
        )
        return {"ok": True, "exit": codigo, "relatorio": relatorio}

    slug_tmp = f"_plan_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}_{os.urandom(3).hex()}"
    arq_tmp = salvar_spec_ui(slug_tmp, texto)
    try:
        relatorio, codigo = pipeline.executar(
            arq_tmp, plano_apenas=True, no_cache=no_cache, scene_budget=scene_budget
        )
    finally:
        arq_tmp.unlink(missing_ok=True)
    return {"ok": True, "exit": codigo, "relatorio": relatorio}


def iniciar_run(payload: dict[str, Any], jobs: JobManager) -> dict[str, Any]:
    doc, texto, _arq = _carregar_spec_payload(payload)
    spec_doc, _perfil, _avisos = spec.preparar(copy.deepcopy(doc))
    config.validar_destino(spec_doc["destino_exportacao"])

    carimbo = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    slug = f"run_{carimbo}_{os.urandom(2).hex()}_{spec_doc['projeto']}"
    spec_path = salvar_spec_ui(slug, texto)

    cli_args = ["run", str(spec_path), "--json"]
    if bool(payload.get("nao_publicar", False)):
        cli_args.append("--nao-publicar")
    if bool(payload.get("no_cache", False)):
        cli_args.append("--no-cache")
    if bool(payload.get("clean_dest", False)):
        cli_args.append("--clean-dest")

    job = jobs.iniciar(
        "run",
        cli_args,
        extra={
            "spec_path": str(spec_path),
            "projeto": spec_doc["projeto"],
            "perfil": spec_doc["perfil"],
            "destino": spec_doc["destino_exportacao"],
        },
    )
    return {"ok": True, "job_id": job["job_id"], "spec_path": str(spec_path), "job": job}


def verificar_destino(payload: dict[str, Any]) -> dict[str, Any]:
    raw_dest = str(payload.get("destino") or "").strip()
    if not raw_dest:
        raise erro_requisicao("informe 'destino' para verificacao")
    alvo = resolver_caminho_leitura(raw_dest)
    config.validar_caminho(alvo, campo="destino")

    raw_only = payload.get("only")
    only_str: str | None = None
    if isinstance(raw_only, list):
        only_str = ",".join(str(x).strip() for x in raw_only if str(x).strip()) or None
    elif isinstance(raw_only, str) and raw_only.strip():
        only_str = raw_only.strip()

    resultado = publish.verificar(alvo, only=only_str)
    ok = bool(resultado.get("ok"))
    return {"ok": ok, "exit": 0 if ok else 3, "resultado": resultado}


def _validar_texto_migrado(texto: str) -> list[str]:
    try:
        doc = yaml.safe_load(texto)
    except yaml.YAMLError as exc:
        return [f"YAML ilegivel apos migracao: {exc}"]
    if not isinstance(doc, dict):
        return ["lote precisa ser um objeto no topo"]
    try:
        spec.preparar(copy.deepcopy(doc))
    except ForgeError as exc:
        erros = (exc.detalhes or {}).get("erros") or []
        msgs = [
            f"{e.get('campo') or e.get('id') or '?'}: {e.get('mensagem')}"
            for e in erros[:10]
            if isinstance(e, dict)
        ]
        return msgs or [exc.mensagem]
    return []


def migrar_spec(payload: dict[str, Any]) -> dict[str, Any]:
    raw_yaml = payload.get("yaml")
    if not isinstance(raw_yaml, str) or not raw_yaml.strip():
        if isinstance(payload.get("caminho"), str) and payload["caminho"].strip():
            arq = resolver_caminho_leitura(payload["caminho"])
            raw_yaml = arq.read_text(encoding="utf-8")
        else:
            raise erro_requisicao("informe 'yaml' para migrar")

    if raw_yaml.lstrip().startswith("{"):
        novo, mudancas, versao = migrate._migrar_json(raw_yaml)
    else:
        novo, mudancas, versao = migrate.migrar_texto(raw_yaml)
    erros = _validar_texto_migrado(novo if mudancas else raw_yaml)
    return {
        "ok": True,
        "de": versao,
        "para": migrate.ALVO,
        "mudancas": mudancas,
        "yaml": novo,
        "valido": not erros,
        "erros": erros,
    }


def _validar_saida_export(raw_saida: Any) -> Path | None:
    if raw_saida is None or not str(raw_saida).strip():
        return None
    alvo = config.normalizar(str(raw_saida).strip())
    _negar_config(alvo)
    config.validar_caminho(alvo, campo="saida")
    raiz_est = paths.raiz_estado().resolve(strict=False)
    if not (alvo.is_relative_to(raiz_est) or config.destino_permitido(alvo)):
        raise erro_destino(
            f"saida de exportacao fora da allowlist/estado: {alvo}",
            saida=str(alvo),
            allowlist=config.listar(),
        )
    return alvo


def _saida_padrao_rbxmx(origem: Path, item_id: str | None, sufixo: str) -> Path:
    nome_base = (item_id or "").strip()
    if not nome_base and origem.is_file():
        if origem.suffix.lower() == ".json":
            try:
                dados = json.loads(origem.read_text(encoding="utf-8"))
                if isinstance(dados, dict):
                    nome_base = str(dados.get("asset_id") or dados.get("id") or "").strip()
            except (OSError, json.JSONDecodeError):
                nome_base = ""
        nome_base = nome_base or origem.stem.removesuffix(".manifest")
    nome_base = nome_base or sufixo
    pasta_base = origem.parent if origem.is_file() else origem
    raiz_est = paths.raiz_estado().resolve(strict=False)
    pasta_res = pasta_base.resolve(strict=False)
    if pasta_res.is_relative_to(raiz_est) or config.destino_permitido(pasta_res):
        return pasta_res / f"{nome_base}_{sufixo}.rbxmx"
    return paths.dir_saida() / "r15" / f"{nome_base}_{sufixo}.rbxmx"


def _resolver_lote_export(payload: dict[str, Any]) -> tuple[Path, bool]:
    raw_lote = payload.get("lote") or payload.get("spec") or payload.get("caminho")
    if isinstance(raw_lote, str) and raw_lote.strip():
        return resolver_caminho_leitura(raw_lote), False
    raw_yaml = payload.get("yaml")
    if isinstance(raw_yaml, str) and raw_yaml.strip():
        slug = f"_export_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}_{os.urandom(3).hex()}"
        return salvar_spec_ui(slug, raw_yaml), True
    raise erro_requisicao("informe 'lote' (caminho) ou 'yaml' para exportar")


def exportar_asset(payload: dict[str, Any]) -> dict[str, Any]:
    tipo_raw = str(payload.get("tipo") or "").strip().lower().removeprefix("export-")
    if tipo_raw not in ("r15", "anim", "surface", "acessorio"):
        raise erro_requisicao(f"tipo de exportacao invalido: {tipo_raw!r} (use r15, anim, surface ou acessorio)")

    saida_custom = _validar_saida_export(payload.get("saida"))
    item_id = str(payload.get("item") or payload.get("item_id") or payload.get("id") or "").strip()
    no_ledger = bool(payload.get("no_ledger", False))

    if tipo_raw in ("r15", "anim"):
        if not item_id:
            raise erro_requisicao(f"export-{tipo_raw} exige o parametro 'item'")
        lote_path, eh_tmp = _resolver_lote_export(payload)
        try:
            if tipo_raw == "r15":
                tex_raw = payload.get("texturas_dir")
                tex_dir = resolver_caminho_leitura(tex_raw) if (isinstance(tex_raw, str) and tex_raw.strip()) else None
                relatorio = rbx.exportar_r15(
                    lote_path,
                    item_id,
                    saida=saida_custom,
                    anchored_root=bool(payload.get("anchored_root", False)),
                    texturas_dir=tex_dir,
                    ledger=False if no_ledger else True,
                    modo_rig=str(payload.get("modo_rig") or "motor6d"),
                )
            else:
                if bool(payload.get("todos", False)):
                    relatorio = rbx.exportar_animacoes(
                        lote_path, item_id, list(profiles.ANIMACOES_SUPORTADAS), saida=saida_custom
                    )
                else:
                    raw_cl = payload.get("clipes") if payload.get("clipes") is not None else payload.get("clipe", "idle")
                    partes_c = (
                        [s.strip() for el in raw_cl for s in str(el).split(",") if s.strip()]
                        if isinstance(raw_cl, (list, tuple))
                        else [s.strip() for s in str(raw_cl).split(",") if s.strip()]
                    )
                    clipes = list(dict.fromkeys(partes_c))
                    if not clipes:
                        raise erro_spec("export-anim: informe ao menos um clipe em 'clipe'/'clipes' ou use todos=true")
                    if len(clipes) > 1:
                        desconhecidos = [c for c in clipes if c not in animacao.CLIPES_SUPORTADOS]
                        if desconhecidos:
                            raise erro_spec(f"export-anim: clipe(s) nao suportado(s): {', '.join(desconhecidos)}")
                        relatorio = rbx.exportar_animacoes(lote_path, item_id, clipes, saida=saida_custom)
                    else:
                        relatorio = rbx.exportar_animacao(lote_path, item_id, clipes[0], saida=saida_custom)
        finally:
            if eh_tmp:
                lote_path.unlink(missing_ok=True)
    else:
        raw_orig = payload.get("origem") or payload.get("manifesto") or payload.get("destino") or payload.get("arquivo")
        if not isinstance(raw_orig, str) or not raw_orig.strip():
            raise erro_requisicao(f"export-{tipo_raw} exige o parametro 'origem'")
        origem_path = resolver_caminho_leitura(raw_orig)
        if tipo_raw == "surface":
            saida_eff = saida_custom or _saida_padrao_rbxmx(origem_path, item_id or None, "surface")
            relatorio = rbx.exportar_surface_appearance(
                origem_path, item_id=item_id or None, saida=saida_eff, ledger=None if no_ledger else True
            )
        else:
            saida_eff = saida_custom or _saida_padrao_rbxmx(origem_path, item_id or None, "accessory")
            att = str(payload.get("attachment_name") or payload.get("attachment") or "").strip() or None
            skinned_val = payload.get("skinned") if isinstance(payload.get("skinned"), bool) else None
            relatorio = rbx.exportar_acessorio_rbxmx(
                origem_path,
                item_id=item_id or None,
                saida=saida_eff,
                attachment_name=att,
                skinned=skinned_val,
                ledger=None if no_ledger else True,
            )

    saida_str = str(relatorio.get("saida") or "")
    q_saida = quote(saida_str, safe="") if saida_str else ""
    return {
        "ok": True,
        "saida": saida_str,
        "url": f"/api/file?path={q_saida}" if q_saida else None,
        "download_url": f"/api/file?path={q_saida}&download=1" if q_saida else None,
        "relatorio": relatorio,
    }


def sincronizar_destino(payload: dict[str, Any]) -> dict[str, Any]:
    raw_origem = str(payload.get("origem") or "").strip()
    raw_para = str(payload.get("para") or "").strip()
    if not raw_origem or not raw_para:
        raise erro_requisicao("sync exige 'origem' e 'para'")
    origem_segura = resolver_caminho_leitura(raw_origem)
    _negar_config(config.normalizar(raw_para))

    rojo_lua = str(payload["rojo_lua"]).strip() if payload.get("rojo_lua") else None
    godot_gd = str(payload["godot_gd"]).strip() if payload.get("godot_gd") else None
    relatorio = sync.executar(
        origem_segura,
        raw_para,
        limpar=bool(payload.get("limpar", False)),
        rojo_lua=rojo_lua or None,
        namespace=str(payload.get("namespace") or "Assets"),
        godot_gd=godot_gd or None,
        gd_class_name=str(payload.get("gd_class_name") or "Forge3DAssets"),
        res_prefix=str(payload.get("res_prefix") or ""),
    )
    return {"ok": True, "relatorio": relatorio}


def upload_cloud(payload: dict[str, Any], jobs: JobManager) -> tuple[int, dict[str, Any]]:
    raw_tipo = str(payload.get("tipo") or "Model").strip()
    tipo = _MAPA_UPLOAD_TIPO.get(raw_tipo.lower(), raw_tipo)
    if tipo not in _MAPA_UPLOAD_CMD:
        raise erro_requisicao(f"tipo Open Cloud invalido: {raw_tipo!r} (use Model, Image ou Animation)")

    raw_arq = str(payload.get("arquivo") or "").strip()
    if not raw_arq:
        raise erro_requisicao("informe 'arquivo' para upload Open Cloud")
    arq_seguro = resolver_caminho_leitura(raw_arq)

    nome = str(payload["nome"]).strip() if payload.get("nome") else None
    descricao = str(payload["descricao"]).strip() if payload.get("descricao") else None
    creator_id = str(payload["creator_id"]).strip() if payload.get("creator_id") else None
    creator_type = str(payload["creator_type"]).strip().lower() if payload.get("creator_type") else None
    strip_tex = bool(payload.get("strip_embedded_textures", False))
    raw_dry = payload.get("dry_run")
    dry_run = True if raw_dry is None else bool(raw_dry)

    if dry_run:
        relatorio = upload.executar(
            arq_seguro,
            asset_type=tipo,
            nome=nome or None,
            descricao=descricao or None,
            creator_id=creator_id or None,
            creator_type=creator_type or None,
            dry_run=True,
            strip_embedded_textures=strip_tex,
        )
        return 200, {"ok": True, "relatorio": relatorio}

    if payload.get("confirmar_envio_real") is not True:
        raise erro_requisicao(
            "envio real ao Open Cloud exige confirmar_envio_real=true quando dry_run=false"
        )

    cmd_cli = _MAPA_UPLOAD_CMD[tipo]
    cli_args = [cmd_cli, str(arq_seguro), "--json"]
    if nome:
        cli_args += ["--nome", nome]
    if descricao:
        cli_args += ["--descricao", descricao]
    if creator_id:
        cli_args += ["--creator-id", creator_id]
    if creator_type:
        cli_args += ["--creator-type", creator_type]
    if strip_tex and tipo == "Model":
        cli_args.append("--strip-embedded-textures")

    job = jobs.iniciar(cmd_cli, cli_args, extra={"arquivo": str(arq_seguro), "asset_type": tipo})
    return 202, {"ok": True, "job_id": job["job_id"], "job": job}


def gerenciar_allowlist(payload: dict[str, Any]) -> dict[str, Any]:
    acao = str(payload.get("acao") or "list").strip().lower()
    if acao == "list":
        raizes = config.listar()
        return {"ok": True, "acao": "list", "allowlist": raizes, "raizes": raizes}
    raw_cam = str(payload.get("caminho") or "").strip()
    if not raw_cam:
        raise erro_requisicao(f"allowlist '{acao}' exige o parametro 'caminho'")
    if acao == "add":
        _negar_config(config.normalizar(raw_cam))
        alvo = config.adicionar(raw_cam)
        raizes = config.listar()
        return {"ok": True, "acao": "add", "adicionado": str(alvo), "allowlist": raizes, "raizes": raizes}
    if acao == "remove":
        removido = config.remover(raw_cam)
        raizes = config.listar()
        return {"ok": True, "acao": "remove", "removido": removido, "allowlist": raizes, "raizes": raizes}
    raise erro_requisicao(f"acao de allowlist invalida: {acao!r} (use list, add ou remove)")


def executar_gc(payload: dict[str, Any]) -> dict[str, Any]:
    raw_dias = payload.get("manter_dias", 30)
    try:
        manter_dias = int(raw_dias)
    except (TypeError, ValueError) as exc:
        raise erro_requisicao(f"manter_dias invalido: {raw_dias!r}") from exc

    if "aplicar" in payload:
        aplicar = bool(payload.get("aplicar"))
    elif "dry_run" in payload:
        aplicar = not bool(payload.get("dry_run"))
    else:
        aplicar = False

    relatorio = gc.executar(manter_dias=manter_dias, aplicar=aplicar)
    return {**relatorio, "relatorio": relatorio}
