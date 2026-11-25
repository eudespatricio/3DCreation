"""Implementacao dos subcomandos (argparse, sem dependencia extra).

Contrato unico: ``doctor`` ``validate`` ``plan`` ``run`` ``verify`` ``query`` ``migrate``
``allowlist`` ``gc`` ``sync`` ``export-anim`` ``export-r15`` ``export-surface``
``export-acessorio`` ``upload-model`` ``upload-image`` ``upload-animation`` ``mcp`` ``ui``.
"""

from __future__ import annotations

import sys
from pathlib import Path

from .. import config, doctor, paths, pipeline, publish
from .handlers_export import (
    export_acessorio,
    export_anim,
    export_r15,
    export_surface,
    sync_cmd,
    upload_animation,
    upload_asset,
    upload_image,
    upload_model,
)
from .output import emit_json, marca, stdout_json_context
from .parsers import construir_parser

__all__ = ["construir_parser", "despachar"]

_json = emit_json
_marca = marca
_upload_asset = upload_asset
_upload_model = upload_model
_upload_image = upload_image
_upload_animation = upload_animation
_export_anim = export_anim
_export_r15 = export_r15
_export_surface = export_surface
_export_acessorio = export_acessorio
_sync = sync_cmd


def despachar(argv: list[str]) -> int:
    from ..errors import ForgeError, erro_interno

    parser = construir_parser()
    args = parser.parse_args(argv)
    modo_json = bool(getattr(args, "json", False))
    try:
        with stdout_json_context(modo_json):
            return _executar(args)
    except ForgeError as exc:
        if modo_json:
            emit_json({"schema": "forge3d/report@1", "comando": args.cmd, "exit": exc.exit_code, "erro": exc.como_dict()})
        print(f"erro: {exc}", file=sys.stderr)
        return exc.exit_code
    except KeyboardInterrupt:  # pragma: no cover
        print("interrompido", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001 - falha nao tratada segue o contrato CLI/JSON
        interno = erro_interno(f"{type(exc).__name__}: {exc}")
        if modo_json:
            emit_json(
                {
                    "schema": "forge3d/report@1",
                    "comando": args.cmd,
                    "exit": interno.exit_code,
                    "erro": interno.como_dict(),
                }
            )
        print(f"erro: {interno}", file=sys.stderr)
        return interno.exit_code


def _executar(args) -> int:
    if args.cmd == "doctor":
        return _doctor(args)
    if args.cmd == "validate":
        return _validate(args)
    if args.cmd == "plan":
        return _plan(args)
    if args.cmd == "run":
        return _run(args)
    if args.cmd == "verify":
        return _verify(args)
    if args.cmd == "query":
        return _query(args)
    if args.cmd == "migrate":
        return _migrate(args)
    if args.cmd == "allowlist":
        return _allowlist(args)
    if args.cmd == "gc":
        return _gc(args)
    if args.cmd == "sync":
        return _sync(args)
    if args.cmd == "export-r15":
        return _export_r15(args)
    if args.cmd == "export-anim":
        return _export_anim(args)
    if args.cmd == "export-surface":
        return _export_surface(args)
    if args.cmd == "export-acessorio":
        return _export_acessorio(args)
    if args.cmd == "upload-model":
        return _upload_model(args)
    if args.cmd == "upload-image":
        return _upload_image(args)
    if args.cmd == "upload-animation":
        return _upload_animation(args)
    if args.cmd == "mcp":
        return _mcp(args)
    if args.cmd == "ui":
        return _ui(args)
    raise SystemExit(2)  # pragma: no cover


def _doctor(args) -> int:
    resultado = doctor.checar()
    if args.json:
        emit_json(resultado)
    else:
        print(f"forge3d {resultado['versao']}")
        print(f"  estado : {resultado['estado']}")
        print(f"  config : {resultado['config']}")
        print(f"  dados  : {resultado['dados']}")
        for check in resultado["checks"]:
            print(f"  [{marca(check['ok'])}] {check['nome']:<14} {check['detalhe']}")
    return 0 if resultado["ok"] else 4


def _validate(args) -> int:
    from .. import spec

    doc = spec.carregar_arquivo(args.lote)
    spec_doc, perfil, avisos = spec.preparar(doc)
    saida = {
        "ok": True,
        "lote": str(Path(args.lote)),
        "projeto": spec_doc["projeto"],
        "perfil": perfil.get("_nome", spec_doc["perfil"]),
        "destino": spec_doc["destino_exportacao"],
        "itens": len(spec_doc["lote"]),
        "avisos": avisos,
    }
    if args.json:
        emit_json(saida)
    else:
        print(f"ok: {saida['itens']} item(ns), perfil {saida['perfil']}, projeto {saida['projeto']}")
        for aviso in avisos:
            print(f"  aviso [{aviso['codigo']}] {aviso['mensagem']}")
    return 0


def _plan(args) -> int:
    relatorio, codigo = pipeline.executar(
        args.lote,
        plano_apenas=True,
        no_cache=getattr(args, "no_cache", False),
        scene_budget=getattr(args, "scene_budget", False),
    )
    if args.json:
        emit_json(relatorio)
    else:
        _imprimir_plano(relatorio)
    return codigo


def _run(args) -> int:
    relatorio, codigo = pipeline.executar(
        args.lote,
        plano_apenas=False,
        publicar_arquivos=not args.nao_publicar,
        no_cache=getattr(args, "no_cache", False),
        clean_dest=getattr(args, "clean_dest", False),
        overlap=getattr(args, "overlap", None),
        warm_worker=getattr(args, "warm_worker", False),
    )
    if args.json:
        emit_json(relatorio)
    else:
        _imprimir_run(relatorio)
    return codigo


def _verify(args) -> int:
    relatorio = pipeline.verificar(args.destino, only=getattr(args, "only", None))
    if args.json:
        emit_json(relatorio)
    else:
        print(f"destino {relatorio['destino']}")
        print(f"  {relatorio['total']} manifesto(s), {len(relatorio['erros'])} problema(s)")
        for item in relatorio["itens"]:
            print(f"  ok   {item['asset_id']:<32} {item['triangulos']:>6} tris  {item['licenca']}")
        for erro in relatorio["erros"]:
            print(f"  FALHA {erro.get('manifesto', '?')}: {erro.get('erro')}")
        if "faltando" in relatorio:
            print(f"  proveniencia: {len(relatorio['faltando'])} campo(s) faltando")
        if "escala" in relatorio:
            print(f"  escala: delta {relatorio['escala']['delta_pct']} %")
        if "pivo" in relatorio:
            print(f"  pivo: desvio {relatorio['pivo']['delta_mm']} mm")
    return 0 if relatorio["ok"] else 3


def _query(args) -> int:
    linhas = publish.consultar(
        projeto=args.projeto, perfil=args.perfil, max_tris=args.max_tris, tag=args.tag
    )
    if args.json:
        emit_json({"schema": "forge3d/query@1", "total": len(linhas), "assets": linhas})
    else:
        if not linhas:
            print("nenhum asset no indice")
        for linha in linhas:
            print(
                f"{linha['asset_id']:<34} {linha['perfil']:<10} {linha['triangulos']:>6} tris  "
                f"{linha['bytes']:>8} B  {linha['licenca']}"
            )
    return 0


def _migrate(args) -> int:
    from .. import migrate
    from ..errors import erro_spec

    plano = migrate.planejar(args.lote)
    if not plano["valido"]:
        raise erro_spec(
            f"lote migrado nao valida em {migrate.ALVO}: {plano['erros'][0]}",
            arquivo=plano["arquivo"],
            de=plano["de"],
            erros=plano["erros"],
        )
    escrito = None
    if args.em_lugar or args.saida:
        escrito = str(migrate.gravar(plano, saida=args.saida, em_lugar=args.em_lugar))
    if args.json:
        emit_json(
            {
                "schema": "forge3d/report@1",
                "comando": "migrate",
                "arquivo": plano["arquivo"],
                "de": plano["de"],
                "para": plano["para"],
                "mudancas": plano["mudancas"],
                "valido": True,
                "escrito": escrito,
            }
        )
        return 0
    if not plano["mudancas"]:
        print(f"{plano['arquivo']}: ja esta em {plano['de']}; nada a migrar")
        return 0
    print(f"{plano['arquivo']}: {plano['de']} -> {plano['para']}")
    for mudanca in plano["mudancas"]:
        print(f"  {mudanca['campo']}: {mudanca['de']} -> {mudanca['para']}")
    if escrito:
        print(f"escrito: {escrito}")
    else:
        print("dry-run: use '--saida ARQ' ou '--em-lugar' para gravar")
    return 0


def _allowlist(args) -> int:
    from ..errors import erro_spec

    if args.acao == "list":
        raizes = config.listar()
        if args.json:
            emit_json({"raizes": raizes})
        else:
            print("destinos autorizados:")
            for raiz in raizes:
                print(f"  {raiz}")
        return 0

    if not args.caminho:
        raise erro_spec(f"allowlist {args.acao} exige um caminho")
    if args.acao == "add":
        alvo = config.adicionar(args.caminho)
        if args.json:
            emit_json({"adicionado": str(alvo)})
        else:
            print(f"autorizado: {alvo}")
        return 0

    removido = config.remover(args.caminho)
    if args.json:
        emit_json({"removido": removido})
    else:
        print("removido" if removido else "nao estava na allowlist")
    return 0 if removido else 2


def _gc(args) -> int:
    from .. import gc

    relatorio = gc.executar(args.manter_dias, aplicar=not args.dry_run)
    if args.json:
        emit_json(relatorio)
    else:
        acao = "removidos" if relatorio["aplicado"] else "seriam removidos"
        print(
            f"{relatorio['total']} alvo(s) {acao} com mais de {relatorio['manter_dias']} dias "
            f"({relatorio['bytes'] / (1024**2):.1f} MB)"
        )
        for alvo in relatorio["alvos"][:20]:
            print(f"  {alvo['tipo']:<8} {alvo['dias']:>6.1f}d  {alvo['caminho']}")
    return 0


def _mcp(_args) -> int:
    from .. import mcp_server

    return mcp_server.servir()


def _ui(args) -> int:
    from ..ui import server

    return server.servir(
        host=args.host,
        port=args.port,
        no_browser=bool(getattr(args, "no_browser", False)),
    )


def _resumo_miss(diag: dict | None, maximo: int = 3) -> str:
    """``  (miss: provider.steps 25->12, ...)`` quando o diagnostico aponta campos alterados."""
    if not isinstance(diag, dict) or not diag.get("campos_alterados"):
        return ""
    difs = diag.get("diferencas") or {}
    partes = []
    for campo in diag["campos_alterados"][:maximo]:
        d = difs.get(campo) or {}
        partes.append(f"{campo} {d.get('antes')!s:.24}->{d.get('depois')!s:.24}")
    resto = len(diag["campos_alterados"]) - maximo
    if resto > 0:
        partes.append(f"+{resto}")
    return f"  (miss: {', '.join(partes)})"


def _imprimir_plano(relatorio: dict) -> None:
    plano = relatorio["plano"]
    print(f"plano {relatorio['run_id']}  projeto {relatorio['projeto']}  perfil {relatorio['perfil']}")
    print(f"destino: {relatorio['destino']}")
    print(
        f"{plano['total']} item(ns): {plano['cache_hits']} do cache, "
        f"{plano['a_executar']} a executar, {plano['bloqueadas']} bloqueado(s), "
        f"~{plano['segundos_estimados']}s"
    )
    for tarefa in relatorio.get("tarefas", []):
        estimativa = (tarefa.get("estimativa") or {}).get("segundos_estimados", 0)
        if tarefa["estado_previsto"] == "bloqueada":
            marca_t, extra = "bloqueado", tarefa.get("razao", "")
        elif tarefa["cache_hit"]:
            marca_t, extra = "cache", tarefa["rota"]
        else:
            marca_t, extra = "executar", f"{tarefa['rota']}  ~{estimativa}s"
            extra += _resumo_miss(tarefa.get("cache_diagnostico"))
        print(f"  [{marca_t:<9}] {tarefa['id']:<30} {extra}")
    orc = relatorio.get("orcamento_cena")
    if isinstance(orc, dict):
        lim = orc.get("limite") or {}
        est = orc.get("estimativa")
        teto = orc.get("teto_pior_caso") or orc.get("medido") or {}
        blocos: list[tuple[str, dict]] = []
        if isinstance(est, dict):
            blocos.append(("estimativa", est))
        blocos.append(("teto_pior_caso", teto))
        for rotulo, bloco in blocos:
            status_b = bloco.get("status", orc.get("status"))
            print(
                f"orcamento_cena {rotulo} [{status_b}]: "
                f"{bloco.get('triangulos_cena')}/{lim.get('triangulos_cena_max')} tris "
                f"({bloco.get('ocupacao_500k_pct')}% de 500k), "
                f"{bloco.get('draw_calls_estimados')}/{lim.get('draw_calls_cena_max')} draw calls, "
                f"{bloco.get('vram_texturas_mb')}/{lim.get('vram_texturas_mb_max')} MB VRAM"
            )


def _imprimir_run(relatorio: dict) -> None:
    for item in relatorio["itens"]:
        estado = item["estado"]
        extra = ""
        if estado in ("publicado", "cache_hit"):
            extra = f"{item['triangulos']} tris  {item['rota']}  {item['determinism']}"
        else:
            extra = f"{item.get('codigo', '')}  {item.get('razao', '')}"
        print(f"  [{estado:<10}] {item['id']:<30} {extra}")
    resumo = relatorio["resumo"]
    print(
        f"\n{resumo['publicados']} publicado(s), {resumo['cache_hits']} cache, "
        f"{resumo['reprovados']} reprovado(s), {resumo['bloqueados']} bloqueado(s), "
        f"{resumo['falhas']} falha(s)  ->  exit {relatorio['exit']}"
    )
    print(f"relatorio: {paths.dir_runs() / relatorio['run_id'] / 'relatorio.json'}")
