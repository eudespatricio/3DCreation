"""Handlers CLI de upload, exportacao Roblox e sincronizacao."""

from __future__ import annotations

import json
from pathlib import Path

from .. import publish
from .output import emit_json


def _ler_manifesto_dict(arq_man: Path) -> dict | None:
    try:
        dados = json.loads(arq_man.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return dados if isinstance(dados, dict) else None


def _extrair_meta_manifesto(arq_man: Path, dados: dict) -> dict[str, str]:
    meta: dict[str, str] = {"origem": str(arq_man.parent)}
    raw_proj = dados.get("projeto")
    if isinstance(raw_proj, str):
        proj = raw_proj.strip()
        if proj:
            meta["projeto"] = proj
    return meta


def _metadados_manifesto_adjacente(arquivo_res: Path, nome_relatorio: str) -> dict[str, str]:
    arquivo_alvo = arquivo_res.resolve(strict=False)
    pastas: list[Path] = []
    for pasta_cand in (arquivo_alvo.parent, arquivo_alvo.parent.parent):
        if pasta_cand.is_dir() and pasta_cand not in pastas:
            pastas.append(pasta_cand)
    if not pastas:
        return {}

    # Prioridade 1: <stem>.manifest.json no diretorio direto do arquivo
    direto = arquivo_alvo.parent / f"{arquivo_alvo.stem}.manifest.json"
    if direto.is_file():
        dados_direto = _ler_manifesto_dict(direto)
        if dados_direto is not None:
            return _extrair_meta_manifesto(direto, dados_direto)

    candidatos: list[tuple[Path, dict]] = []
    vistos: set[Path] = set()
    for pasta in pastas:
        try:
            arqs = sorted(pasta.glob("*.manifest.json"))
        except OSError:
            continue
        for arq_man in arqs:
            if arq_man in vistos:
                continue
            vistos.add(arq_man)
            dados = _ler_manifesto_dict(arq_man)
            if dados is not None:
                candidatos.append((arq_man, dados))

    # Prioridade 2: correspondencia exata de caminho resolvido em files[].caminho
    for arq_man, dados in candidatos:
        raw_files = dados.get("files")
        if not isinstance(raw_files, list):
            continue
        for item in raw_files:
            if not isinstance(item, dict):
                continue
            raw_caminho = item.get("caminho")
            if not isinstance(raw_caminho, str) or not raw_caminho.strip():
                continue
            try:
                caminho_item = (arq_man.parent / raw_caminho.strip()).resolve(strict=False)
            except (OSError, ValueError, TypeError):
                continue
            if caminho_item == arquivo_alvo:
                return _extrair_meta_manifesto(arq_man, dados)

    # Prioridade 3 (fallback): correspondencia por asset_id/id do manifesto
    alvos_id = {arquivo_alvo.stem, nome_relatorio}
    for arq_man, dados in candidatos:
        try:
            raw_aid = dados.get("asset_id") or dados.get("id")
            if isinstance(raw_aid, (str, int)) and not isinstance(raw_aid, bool):
                aid = str(raw_aid).strip()
            else:
                aid = ""
        except (ValueError, TypeError):
            continue
        if aid and aid in alvos_id:
            return _extrair_meta_manifesto(arq_man, dados)
    return {}


def upload_asset(args, asset_type: str) -> int:
    from .. import upload

    arquivo_res = Path(args.arquivo).expanduser().resolve(strict=False)
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
        strip_embedded_textures=bool(getattr(args, "strip_embedded_textures", False)),
    )
    if not relatorio["dry_run"]:
        registro_ledger: dict[str, str] = {
            "evento": "upload",
            "id": str(relatorio["nome"]),
            "asset_id": str(relatorio["asset_id"]),
            "asset_type": str(relatorio["asset_type"]),
            "arquivo": str(arquivo_res),
        }
        registro_ledger.update(
            _metadados_manifesto_adjacente(arquivo_res, str(relatorio["nome"]))
        )
        publish.registrar_ledger(registro_ledger)

    if args.json:
        emit_json(relatorio)
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


def upload_model(args) -> int:
    return upload_asset(args, "Model")


def upload_image(args) -> int:
    return upload_asset(args, "Image")


def upload_animation(args) -> int:
    return upload_asset(args, "Animation")


def export_anim(args) -> int:
    from .. import animacao, profiles, rbx
    from ..errors import erro_spec

    modo_rig = str(getattr(args, "modo_rig", "motor6d") or "motor6d")
    manifesto = getattr(args, "manifesto", None)

    if args.todos:
        relatorio = rbx.exportar_animacoes(
            args.lote,
            args.item,
            list(profiles.ANIMACOES_SUPORTADAS),
            saida=args.saida,
            modo_rig=modo_rig,
            manifesto=manifesto,
        )
    else:
        clipes = list(dict.fromkeys(c.strip() for c in str(args.clipe).split(",") if c.strip()))
        if not clipes:
            raise erro_spec("export-anim: informe ao menos um clipe em --clipe ou use --todos")
        if len(clipes) == 1:
            relatorio = rbx.exportar_animacao(
                args.lote,
                args.item,
                clipes[0],
                saida=args.saida,
                modo_rig=modo_rig,
                manifesto=manifesto,
            )
        else:
            desconhecidos = [c for c in clipes if c not in animacao.CLIPES_SUPORTADOS]
            if desconhecidos:
                raise erro_spec(
                    f"export-anim: clipe(s) nao suportado(s): {', '.join(desconhecidos)}"
                )
            relatorio = rbx.exportar_animacoes(
                args.lote,
                args.item,
                clipes,
                saida=args.saida,
                modo_rig=modo_rig,
                manifesto=manifesto,
            )

    if args.json:
        emit_json(relatorio)
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


def export_r15(args) -> int:
    from .. import rbx
    from ..errors import erro_spec

    asset_ids_map: dict[str, str] | None = None
    raw_asset_ids = getattr(args, "asset_ids", None)
    if raw_asset_ids:
        arq_ids = Path(str(raw_asset_ids)).expanduser()
        try:
            dados_ids = json.loads(arq_ids.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise erro_spec(f"export-r15: falha ao ler --asset-ids '{arq_ids}': {exc}") from exc
        if not isinstance(dados_ids, dict):
            raise erro_spec(f"export-r15: --asset-ids '{arq_ids}' precisa ser um objeto JSON")
        asset_ids_map = {
            str(k): str(v) for k, v in dados_ids.items() if k and v is not None and str(v).strip()
        }

    model_id = getattr(args, "model_id", None)
    rascunho_local = bool(getattr(args, "rascunho_local", False))
    relatorio = rbx.exportar_r15(
        args.lote,
        args.item,
        args.saida,
        anchored_root=args.anchored_root,
        texturas_dir=args.texturas_dir,
        asset_ids=asset_ids_map,
        ledger=False if args.no_ledger else True,
        modo_rig=args.modo_rig,
        model_id=model_id,
        exigir_asset_ids=(not rascunho_local and not model_id),
    )
    if args.json:
        emit_json(relatorio)
    else:
        extra = "  +SurfaceAppearance" if relatorio.get("textura") else ""
        if relatorio.get("model_id"):
            extra += f"  model_id={relatorio['model_id']}"
        print(
            f"rbxlx {relatorio['saida']}  {relatorio['partes']} partes  "
            f"{relatorio['motores']} motores  {relatorio['bytes']} B{extra}"
        )
        sa = relatorio.get("surface_appearance") or {}
        if any(str(v).startswith("rbxassetid://") for v in sa.values()):
            print(
                "nota: PlaceId == 0 no .rbxlx local; no Roblox Studio use 'Save to Roblox' "
                "(ou 3D Importer) para pre-carregar os Image rbxassetid:// do SurfaceAppearance."
            )
    return 0


def export_surface(args) -> int:
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

    relatorio = rbx.exportar_surface_appearance(
        origem,
        item_id=item_id,
        saida=saida,
        ledger=None if args.no_ledger else True,
    )
    if args.json:
        emit_json(relatorio)
    else:
        canais = ",".join(sorted(relatorio["mapas"]))
        print(
            f"rbxmx {relatorio['saida']}  canais {canais}  "
            f"materiais {relatorio['materiais']}  {relatorio['bytes']} B"
        )
    return 0


def export_acessorio(args) -> int:
    from .. import rbx

    origem = Path(args.origem).expanduser()
    item_id = (args.item or "").strip() or None
    tipo_item = str(getattr(args, "tipo", "Accessory") or "Accessory")
    sufixo = "tool" if tipo_item.strip().lower() == "tool" else "accessory"
    saida: str | Path | None = args.saida
    if saida is None and origem.exists():
        if origem.is_file():
            nome_base = item_id or origem.stem.removesuffix(".manifest")
            saida = origem.parent / f"{nome_base}_{sufixo}.rbxmx"
        elif origem.is_dir():
            nome_base = item_id or sufixo
            saida = origem / f"{nome_base}_{sufixo}.rbxmx"

    relatorio = rbx.exportar_acessorio_rbxmx(
        origem,
        item_id=item_id,
        saida=saida,
        ledger=None if args.no_ledger else True,
        tipo_item_roblox=tipo_item,
    )
    if args.json:
        emit_json(relatorio)
    else:
        print(
            f"rbxmx {relatorio['saida']}  attachment {relatorio['attachment']}  "
            f"skinned={relatorio['skinned']}  {relatorio['bytes']} B"
        )
    return 0


def sync_cmd(args) -> int:
    from .. import sync

    relatorio = sync.executar(
        args.origem,
        args.para,
        limpar=args.limpar,
        rojo_lua=args.rojo_lua,
        godot_gd=args.godot_gd,
        gd_class_name=args.gd_class_name,
        res_prefix=args.res_prefix,
    )
    if args.json:
        emit_json(relatorio)
    else:
        extra = f"  rojo={relatorio['rojo_lua']} ({relatorio['rojo_assets']})" if "rojo_lua" in relatorio else ""
        if "godot_gd" in relatorio:
            extra += f"  godot={relatorio['godot_gd']} ({relatorio['godot_assets']})"
        print(
            f"sync {relatorio['origem']} -> {relatorio['destino']}  "
            f"{relatorio['ativos']} ativo(s), {len(relatorio['copiados'])} copiado(s), "
            f"{len(relatorio['removidos'])} removido(s), {relatorio['bytes']} B{extra}"
        )
    return 0
