"""Definicao do parser argparse de todos os subcomandos ``forge3d``."""

from __future__ import annotations

import argparse

from .. import __version__


def construir_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="forge3d",
        description="Esteira de assets 3D por demanda: lote declarativo -> GLB verificado.",
    )
    p.add_argument("--version", action="version", version=f"forge3d {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("doctor", help="diagnostico do ambiente")
    d.add_argument("--json", action="store_true")

    v = sub.add_parser("validate", help="valida o lote contra spec@1..@6 + regras de negocio")
    v.add_argument("lote")
    v.add_argument("--json", action="store_true")

    pl = sub.add_parser("plan", help="o que seria feito: custo, cache, bloqueios (nao executa)")
    pl.add_argument("lote")
    pl.add_argument("--json", action="store_true")
    pl.add_argument(
        "--no-cache",
        "--fresh",
        dest="no_cache",
        action="store_true",
        help="ignora cache e projeta custo de geracao completa",
    )
    pl.add_argument(
        "--scene-budget",
        dest="scene_budget",
        action="store_true",
        help="estima orcamento de cena (Gate G11: tris, draw calls, VRAM)",
    )

    r = sub.add_parser("run", help="executa, verifica QC e publica")
    r.add_argument("lote")
    r.add_argument("--json", action="store_true")
    r.add_argument("--nao-publicar", action="store_true", help="gera e verifica sem escrever no destino")
    r.add_argument(
        "--no-cache",
        "--fresh",
        dest="no_cache",
        action="store_true",
        help="ignora cache e forca nova geracao de todos os itens",
    )
    r.add_argument(
        "--clean-dest",
        action="store_true",
        help="remove manifestos e arquivos legados no destino que nao pertencem ao lote",
    )

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
        "migrate", help="sobe um lote para o contrato corrente (spec@6), sem inventar valor"
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
    sy.add_argument("--godot-gd", help="gera Forge3DAssets.gd tipado para Godot 4")
    sy.add_argument("--gd-class-name", default="Forge3DAssets", help="class_name do script GDScript")
    sy.add_argument("--res-prefix", default="", help="prefixo res:// aplicado aos caminhos Godot")
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
    ea.add_argument("--modo-rig", choices=["motor6d", "bone"], default="motor6d")
    ea.add_argument("--manifesto", help="caminho .manifest.json com rig.ancoras para calibracao de pose")
    ea.add_argument("--saida")
    ea.add_argument("--json", action="store_true")

    e = sub.add_parser("export-r15", help="gera .rbxlx R15 nativo (Parts+Motor6D ou Bone skinned) do blocky")
    e.add_argument("lote")
    e.add_argument("--item", required=True)
    e.add_argument("--saida")
    e.add_argument("--texturas-dir", help="diretorio com texturas PBR para SurfaceAppearance")
    e.add_argument("--modo-rig", choices=["motor6d", "bone"], default="motor6d")
    e.add_argument("--anchored-root", action="store_true", help="ancora o HumanoidRootPart/MeshPart no place")
    e.add_argument("--model-id", help="AssetId de Model publicado no Roblox (ou 'auto' via ledger)")
    e.add_argument("--asset-ids", help="caminho JSON mapeando parte/canal para AssetId Roblox")
    e.add_argument("--rascunho-local", action="store_true", help="permite exportar rota nao-blocky sem rbxassetid://")
    e.add_argument("--no-ledger", action="store_true", help="ignora ledger.jsonl ao resolver AssetIds")
    e.add_argument("--json", action="store_true")

    es = sub.add_parser(
        "export-surface",
        help="gera .rbxmx do SurfaceAppearance PBR a partir de pasta ou manifesto",
    )
    es.add_argument("origem", help="diretorio publicado ou caminho para .manifest.json")
    es.add_argument("--item", help="id do asset (opcional quando um manifesto e passado)")
    es.add_argument("--saida", help="arquivo .rbxmx de saida (padrao ao lado da origem/asset)")
    es.add_argument("--no-ledger", action="store_true", help="ignora ledger.jsonl ao resolver AssetIds")
    es.add_argument("--json", action="store_true")

    ec = sub.add_parser(
        "export-acessorio",
        help="gera .rbxmx do Accessory + Handle MeshPart + Attachment + SurfaceAppearance",
    )
    ec.add_argument("origem", help="diretorio publicado, manifesto JSON ou .glb")
    ec.add_argument("--item", help="id do asset (obrigatorio ao passar diretorio)")
    ec.add_argument("--saida", help="arquivo .rbxmx de saida (padrao ao lado da origem/asset)")
    ec.add_argument("--no-ledger", action="store_true", help="ignora ledger.jsonl ao resolver AssetIds")
    ec.add_argument("--json", action="store_true")

    u = sub.add_parser("upload-model", help="sobe um .glb via Open Cloud Assets (Model)")
    u.add_argument("arquivo")
    u.add_argument("--nome")
    u.add_argument("--descricao")
    u.add_argument("--creator-id")
    u.add_argument("--creator-type", choices=["user", "group"])
    u.add_argument("--dry-run", action="store_true")
    u.add_argument("--intervalo", type=float, default=2.0)
    u.add_argument("--max-espera", type=float, default=300.0)
    u.add_argument(
        "--strip-embedded-textures",
        action="store_true",
        help="remove texturas embutidas do GLB em memoria antes do upload",
    )
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

    ui_p = sub.add_parser("ui", help="interface web local (Forge3D Studio)")
    ui_p.add_argument("--host", default="127.0.0.1", help="endereco de bind HTTP (padrao: 127.0.0.1)")
    ui_p.add_argument("--port", type=int, default=8765, help="porta TCP (padrao: 8765)")
    ui_p.add_argument("--no-browser", action="store_true", help="nao abre o navegador automaticamente")

    return p
