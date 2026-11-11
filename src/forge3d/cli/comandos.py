"""Implementacao dos subcomandos (argparse, sem dependencia extra).

Onze comandos, um contrato: ``doctor`` ``validate`` ``plan`` ``run`` ``verify`` ``query`` ``allowlist`` ``gc`` ``export-r15`` ``upload-model`` ``upload-image``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .. import __version__, config, doctor, paths, pipeline, publish

__all__ = ["despachar", "construir_parser"]


def _json(obj) -> None:
    print(json.dumps(obj, sort_keys=True, indent=1, ensure_ascii=False))


def _marca(ok: bool) -> str:
    return "ok  " if ok else "FALHA"


def construir_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="forge3d",
        description="Esteira de assets 3D por demanda: lote declarativo -> GLB verificado.",
    )
    p.add_argument("--version", action="version", version=f"forge3d {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("doctor", help="diagnostico do ambiente")
    d.add_argument("--json", action="store_true")

    v = sub.add_parser("validate", help="valida o lote contra spec@1/spec@2 + regras de negocio")
    v.add_argument("lote")
    v.add_argument("--json", action="store_true")

    pl = sub.add_parser("plan", help="o que seria feito: custo, cache, bloqueios (nao executa)")
    pl.add_argument("lote")
    pl.add_argument("--json", action="store_true")

    r = sub.add_parser("run", help="executa, verifica QC e publica")
    r.add_argument("lote")
    r.add_argument("--json", action="store_true")
    r.add_argument("--nao-publicar", action="store_true", help="gera e verifica sem escrever no destino")

    ve = sub.add_parser("verify", help="portao de CI: manifesto integro + hash conferido")
    ve.add_argument("destino")
    ve.add_argument("--json", action="store_true")

    q = sub.add_parser("query", help="consulta o indice de assets publicados")
    q.add_argument("--projeto")
    q.add_argument("--perfil")
    q.add_argument("--tag")
    q.add_argument("--max-tris", type=int)
    q.add_argument("--json", action="store_true")

    a = sub.add_parser("allowlist", help="autoriza destinos de publicacao")
    a.add_argument("acao", choices=["list", "add", "remove"])
    a.add_argument("caminho", nargs="?")
    a.add_argument("--json", action="store_true")

    g = sub.add_parser("gc", help="remove cache/runs/staging antigos; nao toca no publicado")
    g.add_argument("--manter-dias", type=int, default=30)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--json", action="store_true")

    e = sub.add_parser("export-r15", help="gera .rbxlx R15 nativo (Parts+Motor6D) do blocky")
    e.add_argument("lote")
    e.add_argument("--item", required=True)
    e.add_argument("--saida")
    e.add_argument("--json", action="store_true")

    u = sub.add_parser("upload-model", help="sobe um .glb via Open Cloud Assets (Model)")
    u.add_argument("arquivo")
    u.add_argument("--nome")
    u.add_argument("--descricao")
    u.add_argument("--creator-id")
    u.add_argument("--creator-type", choices=["user", "group"])
    u.add_argument("--dry-run", action="store_true")
    u.add_argument("--intervalo", type=float, default=2.0)
    u.add_argument("--max-espera", type=float, default=300.0)
    u.add_argument("--json", action="store_true")

    i = sub.add_parser("upload-image", help="sobe PNG/JPG via Open Cloud Assets (Image)")
    i.add_argument("arquivo")
    i.add_argument("--nome")
    i.add_argument("--descricao")
    i.add_argument("--creator-id")
    i.add_argument("--creator-type", choices=["user", "group"])
    i.add_argument("--dry-run", action="store_true")
    i.add_argument("--intervalo", type=float, default=2.0)
    i.add_argument("--max-espera", type=float, default=300.0)
    i.add_argument("--json", action="store_true")

    return p


def despachar(argv: list[str]) -> int:
    from ..errors import ForgeError

    parser = construir_parser()
    args = parser.parse_args(argv)
    try:
        return _executar(args)
    except ForgeError as exc:
        if getattr(args, "json", False):
            _json({"schema": "forge3d/report@1", "comando": args.cmd, "exit": exc.exit_code, "erro": exc.como_dict()})
        print(f"erro: {exc}", file=sys.stderr)
        return exc.exit_code
    except KeyboardInterrupt:  # pragma: no cover
        print("interrompido", file=sys.stderr)
        return 130


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
    if args.cmd == "allowlist":
        return _allowlist(args)
    if args.cmd == "gc":
        return _gc(args)
    if args.cmd == "export-r15":
        return _export_r15(args)
    if args.cmd == "upload-model":
        return _upload_model(args)
    if args.cmd == "upload-image":
        return _upload_image(args)
    raise SystemExit(2)  # pragma: no cover


def _doctor(args) -> int:
    resultado = doctor.checar()
    if args.json:
        _json(resultado)
    else:
        print(f"forge3d {resultado['versao']}")
        print(f"  estado : {resultado['estado']}")
        print(f"  config : {resultado['config']}")
        print(f"  dados  : {resultado['dados']}")
        for check in resultado["checks"]:
            print(f"  [{_marca(check['ok'])}] {check['nome']:<14} {check['detalhe']}")
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
        _json(saida)
    else:
        print(f"ok: {saida['itens']} item(ns), perfil {saida['perfil']}, projeto {saida['projeto']}")
        for aviso in avisos:
            print(f"  aviso [{aviso['codigo']}] {aviso['mensagem']}")
    return 0


def _plan(args) -> int:
    relatorio, codigo = pipeline.executar(args.lote, plano_apenas=True)
    if args.json:
        _json(relatorio)
    else:
        _imprimir_plano(relatorio)
    return codigo


def _run(args) -> int:
    relatorio, codigo = pipeline.executar(
        args.lote, plano_apenas=False, publicar_arquivos=not args.nao_publicar
    )
    if args.json:
        _json(relatorio)
    else:
        _imprimir_run(relatorio)
    return codigo


def _verify(args) -> int:
    relatorio = pipeline.verificar(args.destino)
    if args.json:
        _json(relatorio)
    else:
        print(f"destino {relatorio['destino']}")
        print(f"  {relatorio['total']} manifesto(s), {len(relatorio['erros'])} problema(s)")
        for item in relatorio["itens"]:
            print(f"  ok   {item['asset_id']:<32} {item['triangulos']:>6} tris  {item['licenca']}")
        for erro in relatorio["erros"]:
            print(f"  FALHA {erro.get('manifesto', '?')}: {erro.get('erro')}")
    return 0 if relatorio["ok"] else 3


def _query(args) -> int:
    linhas = publish.consultar(
        projeto=args.projeto, perfil=args.perfil, max_tris=args.max_tris, tag=args.tag
    )
    if args.json:
        _json({"schema": "forge3d/query@1", "total": len(linhas), "assets": linhas})
    else:
        if not linhas:
            print("nenhum asset no indice")
        for linha in linhas:
            print(
                f"{linha['asset_id']:<34} {linha['perfil']:<10} {linha['triangulos']:>6} tris  "
                f"{linha['bytes']:>8} B  {linha['licenca']}"
            )
    return 0


def _allowlist(args) -> int:
    from ..errors import erro_spec

    if args.acao == "list":
        raizes = config.listar()
        if args.json:
            _json({"raizes": raizes})
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
            _json({"adicionado": str(alvo)})
        else:
            print(f"autorizado: {alvo}")
        return 0

    removido = config.remover(args.caminho)
    if args.json:
        _json({"removido": removido})
    else:
        print("removido" if removido else "nao estava na allowlist")
    return 0 if removido else 2


def _upload_asset(args, asset_type: str) -> int:
    from .. import upload

    relatorio = upload.executar(
        args.arquivo,
        asset_type=asset_type,
        nome=args.nome,
        descricao=args.descricao,
        creator_id=args.creator_id,
        creator_type=args.creator_type,
        dry_run=args.dry_run,
        intervalo=args.intervalo,
        max_espera=args.max_espera,
    )
    if args.json:
        _json(relatorio)
    elif relatorio["dry_run"]:
        print("dry-run: nenhum request enviado")
        print(f"  POST {relatorio['url']}")
        print(
            f"  tipo {relatorio['asset_type']}  creator {relatorio['creator']}  "
            f"nome {relatorio['nome']}  {relatorio['bytes']} B  {relatorio['content_type']}"
        )
        print(f"  key: {'encontrada (nao impressa)' if relatorio['key_presente'] else 'ausente'}")
    else:
        print(
            f"{relatorio['asset_type']} assetId {relatorio['asset_id']}  "
            f"operation {relatorio['operation']}  moderacao {relatorio['moderation']}  "
            f"{relatorio['bytes']} B"
        )
    return 0


def _upload_model(args) -> int:
    return _upload_asset(args, "Model")


def _upload_image(args) -> int:
    return _upload_asset(args, "Image")


def _export_r15(args) -> int:
    from .. import rbx

    relatorio = rbx.exportar_r15(args.lote, args.item, args.saida)
    if args.json:
        _json(relatorio)
    else:
        print(
            f"rbxlx {relatorio['saida']}  {relatorio['partes']} partes  "
            f"{relatorio['motores']} motores  {relatorio['bytes']} B"
        )
    return 0


def _gc(args) -> int:
    from .. import gc

    relatorio = gc.executar(args.manter_dias, aplicar=not args.dry_run)
    if args.json:
        _json(relatorio)
    else:
        acao = "removidos" if relatorio["aplicado"] else "seriam removidos"
        print(
            f"{relatorio['total']} alvo(s) {acao} com mais de {relatorio['manter_dias']} dias "
            f"({relatorio['bytes'] / (1024**2):.1f} MB)"
        )
        for alvo in relatorio["alvos"][:20]:
            print(f"  {alvo['tipo']:<8} {alvo['dias']:>6.1f}d  {alvo['caminho']}")
    return 0


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
            marca, extra = "bloqueado", tarefa.get("razao", "")
        elif tarefa["cache_hit"]:
            marca, extra = "cache", tarefa["rota"]
        else:
            marca, extra = "executar", f"{tarefa['rota']}  ~{estimativa}s"
        print(f"  [{marca:<9}] {tarefa['id']:<30} {extra}")


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
