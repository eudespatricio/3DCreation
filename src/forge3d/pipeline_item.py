"""Execucao individual de item no pipeline: gerar -> pos-processar -> segmentar -> QC -> cache."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import (
    __version__,
    animacao,
    cache_diag,
    locks,
    paths,
    post,
    profiles,
    providers,
    publish,
    spec,
)
from .canonical import sha256_arquivo
from .errors import EXIT_QC, ForgeError, erro_licenca
from .plan import perfil_resolvido

__all__ = ["executar_item", "finalizar_item_cpu", "preparar_item_bruto"]


def _aceita_kwarg(fn: Callable[..., Any], nome: str) -> bool:
    """``fn`` aceita ``nome`` por keyword (explicito ou ``**kwargs``)? Builtins sem assinatura: nao."""
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False
    p = params.get(nome)
    if p is not None and p.kind in (
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
        inspect.Parameter.KEYWORD_ONLY,
    ):
        return True
    return any(param.kind is inspect.Parameter.VAR_KEYWORD for param in params.values())


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


def _pos_processar(
    item: dict,
    perfil: dict,
    bruto,
    run_id: str,
    *,
    env_extra: dict[str, str] | None = None,
) -> dict:
    final = paths.dir_staging() / run_id / item["id"] / "final"
    final.mkdir(parents=True, exist_ok=True)
    job: dict = {
        "bruto_dir": str(bruto.dir),
        "bruto_arquivo": "modelo.json",
        "saida_dir": str(final),
        "saida_resultado": str(final / "resultado.json"),
        "perfil": perfil_resolvido(perfil),
        "item": {k: v for k, v in item.items() if not k.startswith("_")},
        "nome_base": item["id"],
        "nome_arquivo": f"{item['id']}.glb",
        # D66/D69: o clipe viaja pronto (chaves em espaco semantico ja resolvidas para o esqueleto).
        "clipes": animacao.clipes(
            perfil,
            profiles.esqueleto_para_item(perfil, item),
            _clipes_pedidos(item),
            seed=(item.get("seed") if str(item.get("rota") or "") != "blocky" else None),
            postura_preset=item.get("postura_preset"),
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

    resultado = post.executar(job, env_extra=env_extra) if env_extra is not None else post.executar(job)
    for arq in resultado.get("arquivos", []):
        caminho = final / arq["caminho"]
        arq["bytes"] = caminho.stat().st_size if caminho.is_file() else 0
        arq["sha256"] = sha256_arquivo(caminho) if caminho.is_file() else "sha256:" + "0" * 64
    resultado["dir_final"] = str(final)
    return resultado


def preparar_item_bruto(
    item: dict,
    tarefa: dict,
    *,
    perfil: dict,
    run_id: str,
    no_cache: bool = False,
    esperar_gpu_lock: bool = False,
) -> dict[str, Any]:
    """Estagio 1 (GPU): cache ou ``provider.gerar`` + checagem de licenca comercial (I7).

    Sem escrita fora do staging bruto; o estagio 2 (Blender/QC/cache) mora em ``finalizar_item_cpu``.
    """
    entrada_cache = None if no_cache else publish.ler_cache(tarefa["chave"])
    if entrada_cache is not None:
        return {"cache_hit": True, "entrada_cache": entrada_cache}

    provider = providers.obter(item["rota"])
    staging = paths.dir_staging() / run_id / item["id"] / "bruto"
    staging.mkdir(parents=True, exist_ok=True)
    if getattr(provider, "usa_gpu", False):
        # D11/I6: um job de GPU por vez; o segundo falha com exit 6 em vez de CUDA OOM
        gerar_fn: Callable[..., Any] = provider.gerar
        if getattr(provider, "gerencia_lock_gpu", False) and _aceita_kwarg(
            gerar_fn, "gpu_lock_factory"
        ):
            bruto = gerar_fn(
                item,
                perfil,
                staging,
                gpu_lock_factory=lambda: locks.lock_gpu(run_id, esperar=esperar_gpu_lock),
            )
        else:
            with locks.lock_gpu(run_id, esperar=esperar_gpu_lock):
                bruto = provider.gerar(item, perfil, staging)
    else:
        bruto = provider.gerar(item, perfil, staging)

    modelo_meta = str((bruto.meta or {}).get("modelo") or "").strip()
    licenca = providers.licenca_de(modelo_meta) if modelo_meta else dict(provider.licenca)
    if not licenca.get("uso_comercial", False):
        raise erro_licenca(
            f"provider '{provider.nome}' sem uso comercial permitido (I7)",
            modelo=licenca.get("modelo", modelo_meta or provider.nome),
        )
    return {"cache_hit": False, "bruto": bruto, "provider": provider, "licenca": licenca}


def _segmentar_motor6d(item: dict, resultado: dict) -> None:
    """F06: segmentacao em partes articuladas executa ANTES do QC para G12/G13 validarem as partes."""
    from . import segmentacao

    arquivo_mesh = next((a for a in resultado.get("arquivos", []) if a.get("papel") == "mesh"), None)
    if arquivo_mesh is None:
        raise ForgeError(
            "FORGE-E-QC",
            "segmentacao: resultado sem papel mesh",
            EXIT_QC,
            {"id": item["id"]},
        )
    info_seg = segmentacao.dividir(
        Path(resultado["dir_final"]) / arquivo_mesh["caminho"],
        item,
        Path(resultado["dir_final"]),
    )
    resultado["partes"] = info_seg["partes"]
    resultado["ancoras"] = info_seg["ancoras"]
    if info_seg.get("partes_combinadas"):
        resultado["partes_combinadas"] = info_seg["partes_combinadas"]
    resultado["arquivos"] = list(resultado.get("arquivos", [])) + info_seg["arquivos"]


def _processar_bruto(
    item: dict,
    tarefa: dict,
    prep: dict[str, Any],
    *,
    perfil: dict,
    run_id: str,
    pos_fn: Callable[..., dict],
    env_extra_post: dict[str, str] | None,
) -> tuple[dict, dict, dict, dict]:
    from . import qc as qc_mod

    provider, bruto, licenca = prep["provider"], prep["bruto"], prep["licenca"]
    if env_extra_post and _aceita_kwarg(pos_fn, "env_extra"):
        resultado = pos_fn(item, perfil, bruto, run_id, env_extra=env_extra_post)
    else:
        resultado = pos_fn(item, perfil, bruto, run_id)
    resultado["determinism"] = provider.determinism
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

    if (item.get("partes") or []) and str((item.get("rig") or {}).get("modo") or "") == "motor6d":
        _segmentar_motor6d(item, resultado)

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
        tarefa["chave"],
        Path(resultado["dir_final"]),
        {
            "resultado": resultado,
            "qc": relatorio_qc,
            "provider": provedor,
            "licenca": licenca,
            "item": spec.resolver_item(item),
            # material em claro da chave: base do diagnostico de miss (cache_diag)
            "chave_material": cache_diag.material_chave_cache(
                item, __version__, provider, perfil_resolvido(perfil)
            ),
        },
    )
    return resultado, relatorio_qc, provedor, licenca


def finalizar_item_cpu(
    item: dict,
    tarefa: dict,
    prep: dict[str, Any],
    *,
    spec_doc: dict,
    perfil: dict,
    spec_hash: str,
    destino: Path,
    run_id: str,
    publicar_arquivos: bool,
    adiar_publicacao: bool = False,
    pos_processar_fn: Callable | None = None,
    env_extra_post: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Estagio 2 (CPU/Blender): pos-processo -> segmentacao -> QC -> cache -> manifesto."""
    # ``_pos_processar`` resolvido na chamada (nao no import) para monkeypatch no modulo valer.
    pos_fn = pos_processar_fn or _pos_processar
    eh_cache_hit = bool(prep["cache_hit"])
    if eh_cache_hit:
        origem, entrada = prep["entrada_cache"]
        resultado = entrada["resultado"]
        relatorio_qc = entrada["qc"]
        provedor = entrada["provider"]
        licenca = entrada["licenca"]
        estado = "cache_hit" if publicar_arquivos else "aprovado_nao_publicado"
    else:
        resultado, relatorio_qc, provedor, licenca = _processar_bruto(
            item, tarefa, prep, perfil=perfil, run_id=run_id, pos_fn=pos_fn,
            env_extra_post=env_extra_post,
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

    publica_agora = publicar_arquivos and not adiar_publicacao
    artefatos: list[dict] = []
    if publica_agora:
        artefatos = publish.publicar(origem, destino, manifesto, run_id)

    saida_item: dict = {
        "id": item["id"],
        "estado": estado,
        "rota": item["rota"],
        "determinism": resultado.get("determinism", "D1"),
        "qc": "aprovado" if relatorio_qc["aprovado"] else "reprovado",
        "cache_hit": eh_cache_hit,
        "trabalho_executado": not eh_cache_hit,
        "triangulos": relatorio_qc["medidas"]["triangulos"],
        "artefatos": artefatos,
        "manifesto": f"{item['id']}.manifest.json" if publica_agora else None,
        "manifesto_doc": manifesto if publica_agora else None,
    }
    if adiar_publicacao:
        saida_item["_staging"] = {
            "origem": origem,
            "manifesto": manifesto,
            "resultado": resultado,
            "relatorio_qc": relatorio_qc,
            "eh_cache_hit": eh_cache_hit,
        }
    for chave_meta in ("orientacao_export", "sockets", "sombreamento"):
        valor_meta = resultado.get(chave_meta)
        if valor_meta:
            saida_item[chave_meta] = valor_meta
    return saida_item


def executar_item(
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
    pos_processar_fn: Callable | None = None,
) -> dict:
    """Caminho serial: estagio 1 seguido do estagio 2 no mesmo thread (comportamento historico)."""
    prep = preparar_item_bruto(item, tarefa, perfil=perfil, run_id=run_id, no_cache=no_cache)
    return finalizar_item_cpu(
        item,
        tarefa,
        prep,
        spec_doc=spec_doc,
        perfil=perfil,
        spec_hash=spec_hash,
        destino=destino,
        run_id=run_id,
        publicar_arquivos=publicar_arquivos,
        adiar_publicacao=adiar_publicacao,
        pos_processar_fn=pos_processar_fn,
    )
