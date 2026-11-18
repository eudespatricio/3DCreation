"""Orquestracao de ``run``: plano -> gerar -> pos-processar -> QC -> cache -> publicar.

Regras que moram aqui: falha e local ao item (P6), bloqueio nao e falha (D11), QC reprovado nao
publica (D9) e nada escreve no destino fora de ``publish`` (I3).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from . import (
    __version__,
    animacao,
    config,
    doctor,
    locks,
    paths,
    plan,
    post,
    profiles,
    providers,
    publish,
    qc,
    spec,
)
from .canonical import canon, sha256_arquivo, sha256_bytes
from .errors import (
    EXIT_AMBIENTE,
    EXIT_OK,
    EXIT_PARCIAL,
    EXIT_PROVIDER,
    EXIT_QC,
    EXIT_RECURSO,
    PRECEDENCIA,
    ForgeError,
)

__all__ = ["novo_id", "executar", "verificar"]


def novo_id() -> str:
    carimbo = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{carimbo}-{os.urandom(3).hex()}"


def _spec_hash(spec_doc: dict) -> str:
    limpo = {k: v for k, v in spec_doc.items() if not k.startswith("_")}
    return sha256_bytes(canon(limpo))


def _runs(run_id: str) -> Path:
    d = paths.dir_runs() / run_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _escrever_json(caminho: Path, obj: dict) -> None:
    caminho.write_text(
        json.dumps(obj, sort_keys=True, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )


# ---------------------------------------------------------------- item


def _esqueleto_divergente(medidas: dict) -> tuple[str, str] | None:
    """D-03: devolve (pedido, real) quando o esqueleto medido difere do pedido; None quando ok."""
    pedido = medidas.get("esqueleto_pedido")
    real = medidas.get("esqueleto")
    if pedido and real and str(pedido) != str(real):
        return str(pedido), str(real)
    return None


def _clipes_pedidos(item: dict) -> list[str] | None:
    bruto = [*(item.get("animacoes_base") or []), *(item.get("clipes") or [])]
    if not bruto:
        return None
    return list(dict.fromkeys(str(c) for c in bruto))


def _pos_processar(item: dict, perfil: dict, bruto, run_id: str) -> dict:
    final = paths.dir_staging() / run_id / item["id"] / "final"
    final.mkdir(parents=True, exist_ok=True)
    job: dict = {
        "bruto_dir": str(bruto.dir),
        "bruto_arquivo": "modelo.json",
        "saida_dir": str(final),
        "saida_resultado": str(final / "resultado.json"),
        "perfil": plan.perfil_resolvido(perfil),
        "item": {k: v for k, v in item.items() if not k.startswith("_")},
        "nome_base": item["id"],
        "nome_arquivo": f"{item['id']}.glb",
        # D66/D69: o clipe viaja pronto (chaves em espaco semantico ja resolvidas para o esqueleto).
        # O bpy nao decide movimento: aplica as chaves; o .rbxlx usa a mesma definicao.
        "clipes": animacao.clipes(
            perfil,
            profiles.esqueleto_para_item(perfil, item),
            _clipes_pedidos(item),
        ),
    }
    for chave_opt in (
        "material_procedural",
        "suavizacao_normais",
        "provider_conceito",
        "template_humanoide",
        "sockets",
        "detalhe_alto",
        "pbr_zonas",
        "quantidade_cena",
        "render_fidelity_roblox",
        "alpha_cards",
        "smart_fit",
    ):
        if chave_opt in item:
            job[chave_opt] = item[chave_opt]
    if "clipes" in item:
        job["clipes_pedidos"] = list(item["clipes"])

    resultado = post.executar(job)
    for arq in resultado.get("arquivos", []):
        caminho = final / arq["caminho"]
        arq["bytes"] = caminho.stat().st_size if caminho.is_file() else 0
        arq["sha256"] = sha256_arquivo(caminho) if caminho.is_file() else "sha256:" + "0" * 64
    resultado["dir_final"] = str(final)
    return resultado


def _executar_item(
    item: dict,
    tarefa: dict,
    *,
    spec_doc: dict,
    perfil: dict,
    spec_hash: str,
    destino: Path,
    run_id: str,
    publicar_arquivos: bool,
    no_cache: bool = False,
    adiar_publicacao: bool = False,
) -> dict:
    from . import qc as qc_mod

    chave = tarefa["chave"]
    entrada_cache = None if no_cache else publish.ler_cache(chave)

    if entrada_cache is not None:
        origem, entrada = entrada_cache
        resultado = entrada["resultado"]
        relatorio_qc = entrada["qc"]
        provedor = entrada["provider"]
        licenca = entrada["licenca"]
        estado = "cache_hit" if publicar_arquivos else "aprovado_nao_publicado"
    else:
        provider = providers.obter(item["rota"])
        staging = paths.dir_staging() / run_id / item["id"] / "bruto"
        staging.mkdir(parents=True, exist_ok=True)
        if getattr(provider, "usa_gpu", False):
            # D11/I6: um job de GPU por vez; o segundo falha com exit 6 em vez de CUDA OOM
            with locks.lock_gpu(run_id, esperar=False):
                bruto = provider.gerar(item, perfil, staging)
        else:
            bruto = provider.gerar(item, perfil, staging)

        resultado = _pos_processar(item, perfil, bruto, run_id)
        resultado["determinism"] = provider.determinism
        # cada provider declara a propria licenca: blocky/import sao procedurais, mesh e o modelo
        modelo_meta = str((bruto.meta or {}).get("modelo") or "").strip()
        if modelo_meta:
            licenca = providers.licenca_de(modelo_meta)
        else:
            licenca = dict(provider.licenca)
        if not licenca.get("uso_comercial", False):
            from .errors import erro_licenca

            raise erro_licenca(
                f"provider '{provider.nome}' sem uso comercial permitido (I7)",
                modelo=licenca.get("modelo", modelo_meta or provider.nome),
            )
        resultado["licenca"] = licenca

        # D-03: esqueleto real medido tem que bater com o pedido; nunca publicar divergente.
        divergencia = _esqueleto_divergente(resultado.get("medidas") or {})
        if divergencia:
            pedido, real = divergencia
            raise ForgeError(
                "FORGE-E-QC",
                f"esqueleto pedido '{pedido}' difere do real medido '{real}'",
                EXIT_QC,
                {"esqueleto_pedido": pedido, "esqueleto_real": real},
            )

        relatorio_qc = qc_mod.verificar(item, perfil, Path(resultado["dir_final"]), resultado)
        if not relatorio_qc["aprovado"]:
            falhou = [g["id"] for g in relatorio_qc["gates"] if g["status"] == "falhou"]
            raise ForgeError(
                "FORGE-E-QC",
                f"QC reprovou: {', '.join(falhou)}",
                EXIT_QC,
                {"gates": falhou, "relatorio": relatorio_qc},
            )

        provedor = {
            "nome": provider.nome,
            "versao": provider.versao,
            "determinism": provider.determinism,
        }
        publish.salvar_cache(
            chave,
            Path(resultado["dir_final"]),
            {
                "resultado": resultado,
                "qc": relatorio_qc,
                "provider": provedor,
                "licenca": licenca,
                "item": spec.resolver_item(item),
            },
        )
        origem = Path(resultado["dir_final"])
        estado = "publicado" if publicar_arquivos else "aprovado_nao_publicado"

    manifesto = publish.montar_manifesto(
        item=item,
        spec_doc=spec_doc,
        spec_hash=spec_hash,
        perfil_nome=spec_doc["perfil"],
        perfil=perfil,
        provider=provedor,
        resultado=resultado,
        relatorio_qc=relatorio_qc,
        licenca=licenca,
        run_id=run_id,
    )

    artefatos: list[dict] = []
    if publicar_arquivos and not adiar_publicacao:
        artefatos = publish.publicar(origem, destino, manifesto, run_id)

    saida_item: dict = {
        "id": item["id"],
        "estado": estado,
        "rota": item["rota"],
        "determinism": resultado.get("determinism", "D1"),
        "qc": "aprovado" if relatorio_qc["aprovado"] else "reprovado",
        "cache_hit": entrada_cache is not None,
        "trabalho_executado": entrada_cache is None,
        "triangulos": relatorio_qc["medidas"]["triangulos"],
        "artefatos": artefatos,
        "manifesto": f"{item['id']}.manifest.json" if (publicar_arquivos and not adiar_publicacao) else None,
        "manifesto_doc": manifesto if (publicar_arquivos and not adiar_publicacao) else None,
    }
    if adiar_publicacao:
        saida_item["_staging"] = {
            "origem": origem,
            "manifesto": manifesto,
            "resultado": resultado,
            "relatorio_qc": relatorio_qc,
            "eh_cache_hit": entrada_cache is not None,
        }
    for chave_meta in ("orientacao_export", "sockets", "sombreamento"):
        valor_meta = resultado.get(chave_meta)
        if valor_meta:
            saida_item[chave_meta] = valor_meta
    return saida_item


def _medir_item_g11(item: dict, staging: dict) -> dict:
    """Extrai metricas reais do item staged para avaliacao do Gate G11."""
    iid = str(item["id"])
    origem: Path = staging["origem"]
    resultado: dict = staging["resultado"]
    relatorio_qc: dict = staging["relatorio_qc"]
    manifesto: dict = staging["manifesto"]

    texturas: list[dict] = []
    for arq in resultado.get("arquivos", []):
        papel = str(arq.get("papel") or "")
        if papel not in qc.PAPEIS_TEXTURA:
            continue
        p_tex = origem / str(arq.get("caminho") or "")
        px = 1024
        if p_tex.is_file():
            dims = qc._validar_bytes_imagem(p_tex.read_bytes())
            if dims:
                px = max(dims)
        canais = 1 if papel in ("roughness", "metallic") else 4
        texturas.append({"id": f"{iid}:{arq['caminho']}", "px": px, "canais": canais})

    g4 = next((g for g in relatorio_qc.get("gates", []) if g.get("id") == "G4"), None)
    for idx, emb in enumerate(((g4 or {}).get("medido") or {}).get("embutidas") or []):
        px_list = emb.get("px")
        if isinstance(px_list, list) and px_list:
            texturas.append({"id": f"{iid}:emb:{idx}", "px": max(int(x) for x in px_list), "canais": 4})

    eh_pbr = (
        item.get("material") == "pbr"
        or bool(item.get("pbr_zonas"))
        or bool(item.get("material_procedural"))
    )
    skinned = (
        bool(item.get("auto_rig"))
        or bool(item.get("skinned"))
        or bool((manifesto.get("anexo") or {}).get("skinned"))
    )
    return {
        "id": iid,
        "tris": int(relatorio_qc["medidas"]["triangulos"]),
        "primitivas": max(1, int(relatorio_qc["medidas"].get("primitivas") or 1)),
        "quantidade_cena": int(item.get("quantidade_cena", 1)),
        "mesh_key": str(item.get("mesh_key") or iid),
        "material_key": f"pbr:{iid}" if eh_pbr else "palette_padrao",
        "skinned": skinned,
        "texturas": texturas,
    }


# ---------------------------------------------------------------- lote


def executar(
    caminho: str | Path,
    *,
    plano_apenas: bool = False,
    publicar_arquivos: bool = True,
    no_cache: bool = False,
    clean_dest: bool = False,
    scene_budget: bool = False,
) -> tuple[dict, int]:
    doc = spec.carregar_arquivo(caminho)
    spec_doc, perfil, avisos = spec.preparar(doc)
    destino = config.validar_destino(spec_doc["destino_exportacao"])
    spec_hash = _spec_hash(spec_doc)
    run_id = novo_id()
    caminho_run = _runs(run_id)

    req = spec_doc.get("requisicao") or {}
    isolamento = req.get("isolamento", "padrao")
    ignorar_cache = no_cache or (isolamento == "estrito")
    deve_limpar = clean_dest or bool(req.get("limpar_destino", False))
    aplicar_g11 = ("orcamento_cena" in spec_doc) or (spec_doc.get("schema") == "forge3d/spec@6")

    tarefas = plan.montar(
        spec_doc,
        perfil,
        lambda chave: publish.ler_cache(chave) is not None,
        no_cache=ignorar_cache,
    )
    resumo_plano = plan.resumo(tarefas)

    _escrever_json(
        caminho_run / "plano.json",
        {
            "schema": "forge3d/plano@1",
            "run_id": run_id,
            "projeto": spec_doc["projeto"],
            "perfil": spec_doc["perfil"],
            "destino": str(destino),
            "spec_hash": spec_hash,
            "pipeline_version": __version__,
            "resumo": resumo_plano,
            "tarefas": tarefas,
        },
    )

    relatorio: dict = {
        "schema": "forge3d/report@1",
        "comando": "plan" if plano_apenas else "run",
        "run_id": run_id,
        "projeto": spec_doc["projeto"],
        "perfil": spec_doc["perfil"],
        "destino": str(destino),
        "spec_hash": spec_hash,
        "pipeline_version": __version__,
        "avisos": avisos,
        "plano": resumo_plano,
        "itens": [],
        "artifacts": [],
    }

    if plano_apenas:
        relatorio["tarefas"] = tarefas
        if scene_budget or aplicar_g11:
            relatorio["orcamento_cena"] = plan.estimar_orcamento_cena(spec_doc, perfil)
        relatorio["exit"] = EXIT_OK
        return relatorio, EXIT_OK

    precisa_blender = any(
        t["estado_previsto"] != "bloqueada" and not t["cache_hit"] for t in tarefas
    )
    if precisa_blender or not any(t["cache_hit"] for t in tarefas):
        doctor.exigir(("blender", "estado"))
    else:
        doctor.exigir(("estado",))

    por_id = {item["id"]: item for item in spec_doc["lote"]}
    politica = (spec_doc.get("politica") or {}).get("falha", "continuar")
    codigos: list[int] = []
    manifestos_publicados: list[dict] = []

    for tarefa in tarefas:
        item = por_id[tarefa["id"]]
        if tarefa["estado_previsto"] == "bloqueada" and not tarefa.get("cache_hit"):
            relatorio["itens"].append(
                {
                    "id": tarefa["id"],
                    "estado": "bloqueado",
                    "rota": tarefa["rota"],
                    "codigo": tarefa.get("codigo", "FORGE-E-PROVIDER"),
                    "razao": tarefa["razao"],
                }
            )
            codigos.append(EXIT_RECURSO if tarefa.get("codigo") == "FORGE-E-RECURSO" else EXIT_PROVIDER)
            continue

        try:
            item["_paleta"] = item.get("paleta") or spec_doc.get("paleta")
            saida = _executar_item(
                item,
                tarefa,
                spec_doc=spec_doc,
                perfil=perfil,
                spec_hash=spec_hash,
                destino=destino,
                run_id=run_id,
                publicar_arquivos=publicar_arquivos,
                no_cache=ignorar_cache,
                adiar_publicacao=True,
            )
            relatorio["itens"].append(saida)
            codigos.append(EXIT_OK)
        except ForgeError as exc:
            estado = _estado_por_codigo(exc.codigo)
            relatorio["itens"].append(
                {
                    "id": item["id"],
                    "estado": estado,
                    "rota": item.get("rota"),
                    "codigo": exc.codigo,
                    "razao": exc.mensagem,
                    "detalhes": exc.detalhes,
                }
            )
            codigos.append(exc.exit_code)
            if politica == "abortar" and estado == "falhou":
                break
        except Exception as exc:  # noqa: BLE001 - nada derruba o lote inteiro
            relatorio["itens"].append(
                {
                    "id": item["id"],
                    "estado": "falhou",
                    "rota": item.get("rota"),
                    "codigo": "FORGE-E-INTERNO",
                    "razao": f"{type(exc).__name__}: {exc}",
                }
            )
            codigos.append(EXIT_AMBIENTE)

    # Gate G11 (orcamento_cena) avalia ANTES de publicar qualquer arquivo no destino (I3 + I5).
    g11_falhou = False
    staged_itens = [s for s in relatorio["itens"] if "_staging" in s]
    if aplicar_g11 and staged_itens:
        itens_medidos_g11 = [
            _medir_item_g11(por_id[s["id"]], s["_staging"]) for s in staged_itens
        ]
        rel_g11 = qc.verificar_g11_orcamento_cena(
            itens_medidos_g11,
            limite_cena=profiles.orcamento_cena_perfil(perfil, spec_doc),
        )
        relatorio["orcamento_cena"] = rel_g11
        if rel_g11["status"] == "falhou":
            g11_falhou = True
            for s in staged_itens:
                s.pop("_staging", None)
                s["estado"] = "reprovado"
                s["qc"] = "reprovado"
                s["codigo"] = "FORGE-E-QC-SCENE"
                s["razao"] = "Gate G11 reprovou orcamento_cena"
                s["artefatos"] = []
                s["manifesto"] = None
                s["manifesto_doc"] = None
            relatorio["erro"] = {
                "codigo": "FORGE-E-QC-SCENE",
                "mensagem": "Gate G11 reprovou orcamento_cena",
                "detalhes": rel_g11,
            }
            codigos = [EXIT_QC]

    if not g11_falhou:
        for s in staged_itens:
            staging = s.pop("_staging")
            if publicar_arquivos:
                artefatos = publish.publicar(
                    staging["origem"], destino, staging["manifesto"], run_id
                )
                s["artefatos"] = artefatos
                s["manifesto"] = f"{s['id']}.manifest.json"
                s["manifesto_doc"] = staging["manifesto"]
                relatorio["artifacts"].extend(artefatos)
                manifestos_publicados.append(staging["manifesto"])

    codigo_saida = EXIT_QC if g11_falhou else _agregar(codigos, relatorio["itens"])
    relatorio["exit"] = codigo_saida
    relatorio["resumo"] = _resumo(relatorio["itens"], resumo_plano)

    if publicar_arquivos and deve_limpar and codigo_saida == EXIT_OK and manifestos_publicados:
        expurgados = publish.expurgar_orfaos_destino(destino, manifestos_publicados, run_id)
        if expurgados:
            relatorio["expurgados"] = expurgados

    _escrever_json(caminho_run / "relatorio.json", relatorio)
    publish.registrar_ledger(
        {
            "run_id": run_id,
            "evento": "run",
            "projeto": spec_doc["projeto"],
            "exit": codigo_saida,
            "resumo": relatorio["resumo"],
        }
    )
    return relatorio, codigo_saida


def _estado_por_codigo(codigo: str) -> str:
    if codigo in ("FORGE-E-PROVIDER", "FORGE-E-RECURSO", "FORGE-E-LICENCA"):
        return "bloqueado"
    if codigo == "FORGE-E-QC":
        return "reprovado"
    return "falhou"


def _agregar(codigos: list[int], itens: list[dict]) -> int:
    """Nada publicado => exit da causa mais grave; mistura => parcial (docs/contratos.md §5)."""
    publicados = sum(
        1 for i in itens if i["estado"] in ("publicado", "cache_hit", "aprovado_nao_publicado")
    )
    erros = [c for c in codigos if c != EXIT_OK]
    if not erros:
        return EXIT_OK
    if publicados == 0:
        for code in PRECEDENCIA:
            if code in erros and code != EXIT_OK:
                return code
        return erros[0]
    return EXIT_PARCIAL


def _resumo(itens: list[dict], resumo_plano: dict) -> dict:
    def contar(estado: str) -> int:
        return sum(1 for i in itens if i["estado"] == estado)

    return {
        "total": len(itens),
        "publicados": contar("publicado"),
        "cache_hits": contar("cache_hit"),
        "reprovados": contar("reprovado"),
        "bloqueados": contar("bloqueado"),
        "falhas": contar("falhou"),
        "trabalho_executado": sum(1 for i in itens if i.get("trabalho_executado")),
        "segundos_estimados": resumo_plano.get("segundos_estimados", 0),
    }


def verificar(destino: str | Path, only: str | None = None) -> dict:
    alvo = config.normalizar(destino)
    return publish.verificar(alvo, only=only)
