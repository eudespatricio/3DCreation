"""Planejamento — puro, sem GPU, sem escrita de asset (D5, L2).

Fachada modular que mantem ``plan.py`` <= 500 linhas delegando inspecao e orcamento.
"""

from __future__ import annotations

from . import __version__, cache_diag, providers
from .canonical import chave_cache
from .errors import ForgeError
from .plan_budget import (
    _estimar_item_calibrado,
    _estimar_item_teto,
    estimar_orcamento_cena,
)
from .plan_inspect import _inspecionar_arquivo_3d
from .spec import resolver_item

__all__ = ["estimar_orcamento_cena", "montar", "perfil_resolvido", "resumo"]

_REEXPORTS = (_estimar_item_calibrado, _estimar_item_teto, _inspecionar_arquivo_3d)


def perfil_resolvido(perfil: dict) -> dict:
    """Perfil sem metadados de origem: entra na chave de cache so o que muda a saida."""
    return {k: v for k, v in perfil.items() if not k.startswith("_")}


def montar(
    spec_doc: dict,
    perfil: dict,
    cache_disponivel,
    *,
    no_cache: bool = False,
) -> list[dict]:
    """Lista de tarefas resolvidas. Rota nao implementada vira ``bloqueada``, nao erro fatal."""
    tarefas: list[dict] = []
    perfil_para_chave = perfil_resolvido(perfil)
    isolamento = (spec_doc.get("requisicao") or {}).get("isolamento", "padrao")
    ignorar_cache = no_cache or (isolamento == "estrito")

    for item in spec_doc["lote"]:
        tarefa = {
            "id": item["id"],
            "tipo": item["tipo"],
            "rota": item["rota"],
            "estado_previsto": "pronto",
            "razao": None,
            "chave": None,
            "cache_hit": False,
            "provedor": None,
            "estimativa": None,
        }
        try:
            provider = providers.obter(item["rota"])
        except ForgeError as exc:
            tarefa["estado_previsto"] = "bloqueada"
            tarefa["razao"] = exc.mensagem
            tarefa["codigo"] = exc.codigo
            tarefas.append(tarefa)
            continue

        chave = chave_cache(
            resolver_item(item),
            __version__,
            {item["rota"]: provider.versao},
            perfil_para_chave,
        )
        tarefa["chave"] = chave
        tarefa["provedor"] = {"nome": provider.nome, "versao": provider.versao}
        tarefa["estimativa"] = provider.custo(item, perfil)
        tarefa["cache_hit"] = False if ignorar_cache else bool(cache_disponivel(chave))
        # So leitura do ponteiro .por_id (L2 continua: plano nao escreve nada).
        material = (
            {}
            if tarefa["cache_hit"]
            else cache_diag.material_chave_cache(item, __version__, provider, perfil_para_chave)
        )
        tarefa["cache_diagnostico"] = cache_diag.diagnosticar_miss(
            item["id"], chave, material, cache_hit=tarefa["cache_hit"], no_cache=ignorar_cache
        )

        avaliar = getattr(provider, "preflight_item", None)
        pronto, razao = avaliar(item) if callable(avaliar) else provider.preflight()
        if not pronto:
            if tarefa["cache_hit"]:
                tarefa["aviso_preflight"] = razao
            else:
                tarefa["estado_previsto"] = "bloqueada"
                tarefa["razao"] = razao
                if "VRAM" in razao:
                    # D11/I6: falta de VRAM e recurso (exit 6), nao falha de provider (exit 5)
                    tarefa["codigo"] = "FORGE-E-RECURSO"
        tarefas.append(tarefa)

    return tarefas


def resumo(tarefas: list[dict]) -> dict:
    total = len(tarefas)
    bloqueadas = sum(1 for t in tarefas if t["estado_previsto"] == "bloqueada")
    hits = sum(1 for t in tarefas if t["cache_hit"])
    a_executar = sum(
        1 for t in tarefas if t["estado_previsto"] != "bloqueada" and not t["cache_hit"]
    )
    segundos = sum(
        float((t["estimativa"] or {}).get("segundos_estimados", 0))
        for t in tarefas
        if not t["cache_hit"]
    )
    vram = max(
        [
            int((t["estimativa"] or {}).get("vram_mb", 0))
            for t in tarefas
            if t["estado_previsto"] != "bloqueada" and not t["cache_hit"]
        ],
        default=0,
    )
    return {
        "total": total,
        "prontas": total - bloqueadas,
        "bloqueadas": bloqueadas,
        "cache_hits": hits,
        "a_executar": a_executar,
        "segundos_estimados": round(segundos, 1),
        "vram_pico_mb": vram,
    }
