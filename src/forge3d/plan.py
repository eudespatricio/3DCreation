"""Planejamento — puro, sem GPU, sem escrita de asset (D5, L2).

``plan`` e o passo que transforma um script em utilitario: responde "o que seria feito, quanto custa,
quanto vem do cache" sem gastar recurso. E o que roda no CI de pull request.
"""

from __future__ import annotations

from . import __version__, profiles, providers, qc
from .canonical import chave_cache
from .errors import ForgeError
from .spec import resolver_item

__all__ = ["estimar_orcamento_cena", "montar", "perfil_resolvido", "resumo"]


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


def estimar_orcamento_cena(spec_doc: dict, perfil: dict) -> dict:
    """Estima o orcamento de cena (Gate G11: tris, draw calls, VRAM) sem executar Blender/GPU."""
    tex_max_perfil = int(((perfil.get("material") or {}).get("textura_max") or 1024))
    itens_medidos: list[dict] = []
    for item in spec_doc.get("lote") or []:
        iid = str(item.get("id") or "?")
        tipo = str(item.get("tipo") or "prop_estatico")
        qualidade = str(item.get("qualidade") or "standard").strip().lower()
        tris = int(
            item.get("limite_triangulos")
            or profiles.limite_tri_qualidade(perfil, tipo, qualidade)
        )
        qtd = int(item.get("quantidade_cena", 1))
        skinned = bool(item.get("auto_rig")) or bool(item.get("skinned"))
        eh_pbr = (
            item.get("material") == "pbr"
            or bool(item.get("pbr_zonas"))
            or bool(item.get("material_procedural"))
        )
        px_base = min(tex_max_perfil, 2048 if qualidade in ("hero", "ultra") else 1024)
        px_sub = min(tex_max_perfil, 2048 if qualidade == "ultra" else 1024)
        if eh_pbr:
            texturas = [
                {"id": f"{iid}:color", "px": px_base, "canais": 4},
                {"id": f"{iid}:normal", "px": px_sub, "canais": 3},
                {"id": f"{iid}:roughness", "px": px_sub, "canais": 1},
                {"id": f"{iid}:metallic", "px": px_sub, "canais": 1},
            ]
        else:
            texturas = [{"id": f"{iid}:albedo", "px": min(px_base, 1024), "canais": 4}]
        itens_medidos.append(
            {
                "id": iid,
                "tris": tris,
                "quantidade_cena": qtd,
                "mesh_key": str(item.get("mesh_key") or iid),
                "material_key": f"pbr:{iid}" if eh_pbr else "palette_padrao",
                "skinned": skinned,
                "texturas": texturas,
            }
        )
    limite = profiles.orcamento_cena_perfil(perfil, spec_doc)
    return qc.verificar_g11_orcamento_cena(itens_medidos, limite_cena=limite)
