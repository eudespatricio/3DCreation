"""Implementacao dos subcomandos (argparse, sem dependencia extra).

Contrato unico: ``doctor`` ``validate`` ``plan`` ``run`` ``verify`` ``query`` ``migrate``
``allowlist`` ``gc`` ``sync`` ``export-anim`` ``export-r15`` ``export-surface``
``upload-model`` ``upload-image`` ``upload-animation`` ``mcp``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .. import __version__, config, doctor, paths, pipeline, publish

__all__ = ["construir_parser", "despachar"]


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
    ve.add_argument(
        "--only",
        help="verifica so estes aspectos: manifesto,hash,escala,pivo,gates (virgula)",
    )
    ve.add_argument("--json", action="store_true")

    q = sub.add_parser("query", help="consulta o indice de assets publicados")
    q.add_argument("--projeto")
    q.add_argument("--perfil")
    q.add_argument("--tag")
    q.add_argument("--max-tris", type=int)
    q.add_argument("--json", action="store_true")

    mi = sub.add_parser(
        "migrate", help="sobe um lote para o contrato corrente (spec@3), sem inventar valor"
    )
    mi.add_argument("lote")
    mi.add_argument("--saida", help="grava o lote migrado neste arquivo")
    mi.add_argument("--em-lugar", action="store_true", help="sobrescreve o proprio lote")
    mi.add_argument("--json", action="store_true")

    a = sub.add_parser("allowlist", help="autoriza destinos de publicacao")
    a.add_argument("acao", choices=["list", "add", "remove"])
    a.add_argument("caminho", nargs="?")
    a.add_argument("--json", action="store_true")

    g = sub.add_parser("gc", help="remove cache/runs/staging antigos; nao toca no publicado")
    g.add_argument("--manter-dias", type=int, default=30)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--json", action="store_true")

    sy = sub.add_parser("sync", help="sincroniza destino verificado para pasta externa (ex.: /mnt/...)")
    sy.add_argument("origem")
    sy.add_argument("--para", required=True, help="pasta de destino alvo")
    sy.add_argument("--limpar", action="store_true", help="remove orfaos no destino alvo")
    sy.add_argument("--rojo-lua", help="gera modulo Luau Assets.lua para Rojo com os assetIds")
    sy.add_argument("--json", action="store_true")

    ea = sub.add_parser("export-anim", help="gera .rbxmx do KeyframeSequence (Animation do Roblox)")
    ea.add_argument("lote")
    ea.add_argument("--item", required=True)
    ea.add_argument(
        "--clipe",
        default="idle",
        help="clipe ou lista separada por virgula (ex.: idle,walk,run,jump)",
    )
    ea.add_argument(
        "--todos",
        action="store_true",
        help="exporta todos os clipes suportados em um unico .rbxmx",
    )
    ea.add_argument("--saida")
    ea.add_argument("--json", action="store_true")

    e = sub.add_parser("export-r15", help="gera .rbxlx R15 nativo (Parts+Motor6D) do blocky")
    e.add_argument("lote")
    e.add_argument("--item", required=True)
    e.add_argument("--saida")
    e.add_argument("--texturas-dir", help="diretorio com texturas PBR para SurfaceAppearance")
    e.add_argument("--json", action="store_true")

    es = sub.add_parser(
        "export-surface",
        help="gera .rbxmx do SurfaceAppearance PBR a partir de pasta ou manifesto",
    )
    es.add_argument("origem", help="diretorio publicado ou caminho para .manifest.json")
    es.add_argument("--item", help="id do asset (opcional quando um manifesto e passado)")
    es.add_argument("--saida", help="arquivo .rbxmx de saida (padrao ao lado da origem/asset)")
    es.add_argument("--json", action="store_true")

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

    an = sub.add_parser("upload-animation", help="sobe .rbxmx/.rbxm via Open Cloud Assets (Animation)")
    an.add_argument("arquivo")
    an.add_argument("--nome")
    an.add_argument("--descricao")
    an.add_argument("--creator-id")
    an.add_argument("--creator-type", choices=["user", "group"])
    an.add_argument("--dry-run", action="store_true")
    an.add_argument("--intervalo", type=float, default=2.0)
    an.add_argument("--max-espera", type=float, default=300.0)
    an.add_argument("--json", action="store_true")

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

    sub.add_parser("mcp", help="servidor MCP (JSON-RPC 2.0 sobre stdio)")

    return p


def despachar(argv: list[str]) -> int:
    from ..errors import ForgeError, erro_interno

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
    except Exception as exc:  # noqa: BLE001 - falha nao tratada segue o contrato CLI/JSON
        interno = erro_interno(f"{type(exc).__name__}: {exc}")
        if getattr(args, "json", False):
            _json(
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
    if args.cmd == "upload-model":
        return _upload_model(args)
    if args.cmd == "upload-image":
        return _upload_image(args)
    if args.cmd == "upload-animation":
        return _upload_animation(args)
    if args.cmd == "mcp":
        return _mcp(args)
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
    relatorio = pipeline.verificar(args.destino, only=getattr(args, "only", None))
    if args.json:
        _json(relatorio)
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
        _json(
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
        publish.registrar_ledger(
            {
                "evento": "upload",
                "id": relatorio["nome"],
                "asset_id": relatorio["asset_id"],
                "asset_type": relatorio["asset_type"],
                "arquivo": str(args.arquivo),
            }
        )
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


def _upload_animation(args) -> int:
    return _upload_asset(args, "Animation")


def _export_anim(args) -> int:
    from .. import profiles, rbx
    from ..errors import erro_spec

    if args.todos:
        relatorio = rbx.exportar_animacoes(
            args.lote, args.item, list(profiles.ANIMACOES_SUPORTADAS), saida=args.saida
        )
    else:
        clipes = list(dict.fromkeys(c.strip() for c in str(args.clipe).split(",") if c.strip()))
        if not clipes:
            raise erro_spec("export-anim: informe ao menos um clipe em --clipe ou use --todos")
        if len(clipes) == 1:
            relatorio = rbx.exportar_animacao(args.lote, args.item, clipes[0], saida=args.saida)
        else:
            desconhecidos = [c for c in clipes if c not in profiles.ANIMACOES_SUPORTADAS]
            if desconhecidos:
                raise erro_spec(
                    f"export-anim: clipe(s) nao suportado(s): {', '.join(desconhecidos)}"
                )
            relatorio = rbx.exportar_animacoes(args.lote, args.item, clipes, saida=args.saida)

    if args.json:
        _json(relatorio)
    elif "clipes" in relatorio:
        nomes = ",".join(relatorio["clipes"])
        kf_resumo = ", ".join(f"{k}:{v}" for k, v in relatorio["keyframes"].items())
        print(
            f"rbxmx {relatorio['saida']}  clipes {nomes}  "
            f"keyframes ({kf_resumo})  {relatorio['bytes']} B"
        )
    else:
        print(
            f"rbxmx {relatorio['saida']}  clipe {relatorio['clipe']}  "
            f"{relatorio['keyframes']} keyframes  {relatorio['bytes']} B"
        )
    return 0


def _export_r15(args) -> int:
    from .. import rbx

    relatorio = rbx.exportar_r15(
        args.lote, args.item, args.saida, texturas_dir=args.texturas_dir
    )
    if args.json:
        _json(relatorio)
    else:
        extra = "  +SurfaceAppearance" if relatorio.get("textura") else ""
        print(
            f"rbxlx {relatorio['saida']}  {relatorio['partes']} partes  "
            f"{relatorio['motores']} motores  {relatorio['bytes']} B{extra}"
        )
    return 0


def _export_surface(args) -> int:
    from .. import rbx

    origem = Path(args.origem).expanduser()
    item_id = (args.item or "").strip() or None
    saida: str | Path | None = args.saida
    if saida is None and origem.exists():
        if origem.is_file():
            nome_base = item_id
            if not nome_base:
                try:
                    dados = json.loads(origem.read_text(encoding="utf-8"))
                    if isinstance(dados, dict):
                        nome_base = str(dados.get("asset_id") or dados.get("id") or "").strip() or None
                except (OSError, ValueError):
                    nome_base = None
            if not nome_base:
                nome_base = origem.stem.removesuffix(".manifest")
            saida = origem.parent / f"{nome_base}_surface.rbxmx"
        elif origem.is_dir():
            nome_base = item_id or "surface"
            saida = origem / f"{nome_base}_surface.rbxmx"

    relatorio = rbx.exportar_surface_appearance(origem, item_id=item_id, saida=saida)
    if args.json:
        _json(relatorio)
    else:
        canais = ",".join(sorted(relatorio["mapas"]))
        print(
            f"rbxmx {relatorio['saida']}  canais {canais}  "
            f"materiais {relatorio['materiais']}  {relatorio['bytes']} B"
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


def _sync(args) -> int:
    from .. import sync

    relatorio = sync.executar(
        args.origem, args.para, limpar=args.limpar, rojo_lua=args.rojo_lua
    )
    if args.json:
        _json(relatorio)
    else:
        extra = f"  rojo={relatorio['rojo_lua']} ({relatorio['rojo_assets']})" if "rojo_lua" in relatorio else ""
        print(
            f"sync {relatorio['origem']} -> {relatorio['destino']}  "
            f"{relatorio['ativos']} ativo(s), {len(relatorio['copiados'])} copiado(s), "
            f"{len(relatorio['removidos'])} removido(s), {relatorio['bytes']} B{extra}"
        )
    return 0


def _mcp(_args) -> int:
    from .. import mcp_server

    return mcp_server.servir()


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
