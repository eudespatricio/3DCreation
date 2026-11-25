"""Diagnostico de cache miss: qual campo mudou entre o ultimo cache salvo e o plano atual.

A chave de cache (D6) e um hash opaco; aqui guardamos o *material* que a gerou para explicar um
miss ("provider.steps 25 -> 12") sem reabrir o hash. Diagnostico nunca decide hit/miss: a chave
continua sendo a unica fonte de verdade e este modulo so le o ponteiro ``.por_id`` do cache.
"""

from __future__ import annotations

import inspect
import os
from collections.abc import Callable
from typing import Any

from . import cache
from .spec import resolver_item

__all__ = ["diagnosticar_miss", "extrair_campos_provider", "material_chave_cache"]


def _valor_seguro(fn: Callable[[], Any]) -> Any:
    """Env invalida vira valor diagnostico explicito (nunca some): o provider falha depois com o
    erro real; aqui so registramos o que estava configurado."""
    try:
        return fn()
    except (ValueError, OSError) as exc:
        return f"invalido: {exc}"


def _steps_trellis(mesh_trellis: Any, item: dict) -> Any:
    fn = mesh_trellis.steps_trellis2
    try:
        aceita_item = len(inspect.signature(fn).parameters) >= 1
    except (TypeError, ValueError):
        aceita_item = False
    return _valor_seguro(lambda: fn(item) if aceita_item else fn())


def _campos_trellis(item: dict) -> dict[str, Any]:
    from .providers import mesh_trellis as tr

    return {
        "steps": _steps_trellis(tr, item),
        "steps_env": os.environ.get("FORGE3D_TRELLIS2_STEPS", "").strip() or None,
        "quant": _valor_seguro(tr.quant_trellis2),
        "pipeline_type": _valor_seguro(tr.pipeline_type_trellis2),
        "shape_guidance": _valor_seguro(tr.shape_guidance_trellis2),
        "tex_guidance": _valor_seguro(tr.tex_guidance_trellis2),
        "remesh_project": _valor_seguro(tr.remesh_project_trellis2),
        "decimation_target": _valor_seguro(lambda: tr.calcular_decimation_target(item)),
        "trellis_model": (
            os.environ.get("FORGE3D_I23D_TRELLIS_MODEL", "").strip() or tr.MODELO_TRELLIS_PADRAO
        ),
    }


def extrair_campos_provider(item: dict, provider: Any) -> dict[str, Any]:
    """Opcoes efetivas do provider image-to-3D, em claro (o que ``versao`` resume em string).

    Providers sem opcoes de env (blocky, import, ...) devolvem ``{}``: a versao basta.
    """
    if isinstance(provider, dict) or provider is None:
        return {}
    from .providers import mesh_diag as md
    from .providers.mesh import MeshProvider

    if not isinstance(provider, MeshProvider):
        return {}
    modelo = _valor_seguro(md.modelo_escolhido)
    campos: dict[str, Any] = {
        "modelo_mesh": modelo,
        "rembg_politica": md._politica_rembg(),
        "rembg_mod": _valor_seguro(md._rembg_modelo),
        "pose_guard": md._pose_guard_modo(item),
        "delight": md._delight_ativo(item),
        "qualidade": md._qualidade(item),
        "mc_resolution": os.environ.get("FORGE3D_MC_RESOLUTION", "256").strip(),
        "tex_px": os.environ.get("FORGE3D_TEX_PX", "1024").strip(),
        "device": md._device(),
    }
    if modelo == "trellis":
        campos.update(_campos_trellis(item))
    return campos


def _versao_provider(provider: Any) -> str:
    if provider is None:
        return ""
    if isinstance(provider, dict):
        return str(provider.get("versao") or "")
    return str(getattr(provider, "versao", "") or "")


def material_chave_cache(
    item: dict, pipeline_version: str, provider: Any, perfil_para_chave: dict
) -> dict[str, Any]:
    """Material que gerou a chave (mesmos insumos de ``canonical.chave_cache``) + campos em claro."""
    return {
        "item": resolver_item(item),
        "pipeline": pipeline_version,
        "providers": {item["rota"]: _versao_provider(provider)},
        "provider_campos": extrair_campos_provider(item, provider),
        "perfil": perfil_para_chave,
    }


def _resultado(
    status: str, motivo: str | None, chave_anterior: str | None, diferencas: dict | None = None
) -> dict[str, Any]:
    dif = diferencas or {}
    return {
        "status": status,
        "motivo": motivo,
        "chave_anterior": chave_anterior,
        "campos_alterados": sorted(dif),
        "diferencas": {k: dif[k] for k in sorted(dif)},
    }


def _diff_dict(prefixo: str, antes: Any, depois: Any, saida: dict[str, dict]) -> None:
    a = antes if isinstance(antes, dict) else {}
    d = depois if isinstance(depois, dict) else {}
    for chave in set(a) | set(d):
        va, vd = a.get(chave), d.get(chave)
        if va != vd:
            saida[f"{prefixo}.{chave}"] = {"antes": va, "depois": vd}


def _material_anterior(registro: dict) -> dict[str, Any]:
    """Registros sem ``chave_material`` (gravados antes da 0.9.12) ainda comparam item+versao."""
    material = registro.get("chave_material")
    if isinstance(material, dict):
        return material
    item_raw, prov_raw = registro.get("item"), registro.get("provider")
    item: dict = item_raw if isinstance(item_raw, dict) else {}
    prov: dict = prov_raw if isinstance(prov_raw, dict) else {}
    rota = item.get("rota")
    return {
        "item": item,
        "providers": {rota: prov.get("versao")} if rota and prov.get("versao") else {},
    }


def diagnosticar_miss(
    item_id: str,
    chave_atual: str,
    material_atual: dict[str, Any],
    *,
    cache_hit: bool,
    no_cache: bool,
) -> dict[str, Any]:
    """Explica hit/miss de ``item_id`` comparando com o ultimo registro ``.por_id`` do cache."""
    if cache_hit:
        return _resultado("hit", None, chave_atual)
    registro = cache.ler_ultimo_registro_item(item_id)
    chave_ant = str(registro["chave"]) if registro and registro.get("chave") else None
    if no_cache:
        return _resultado("miss", "no_cache", chave_ant)
    if registro is None or chave_ant is None:
        return _resultado("miss", "sem_cache_anterior", None)
    if chave_ant == chave_atual:
        # mesma chave e mesmo assim miss: entrada removida pelo gc ou falhou integridade SHA-256
        return _resultado("miss", "cache_invalido", chave_ant)

    anterior = _material_anterior(registro)
    dif: dict[str, dict] = {}
    if "pipeline" in anterior and anterior.get("pipeline") != material_atual.get("pipeline"):
        dif["pipeline_version"] = {
            "antes": anterior.get("pipeline"),
            "depois": material_atual.get("pipeline"),
        }
    _diff_dict("item", anterior.get("item"), material_atual.get("item"), dif)
    campos_prov: dict[str, dict] = {}
    if "provider_campos" in anterior:
        _diff_dict(
            "provider", anterior.get("provider_campos"), material_atual.get("provider_campos"),
            campos_prov,
        )
    dif.update(campos_prov)
    if not campos_prov:
        # versao do provider e um resumo opaco: so aparece quando os campos em claro nao explicam
        _diff_dict("providers", anterior.get("providers"), material_atual.get("providers"), dif)
    if "perfil" in anterior:
        _diff_dict("perfil", anterior.get("perfil"), material_atual.get("perfil"), dif)
    if not dif:
        # chave mudou sem diferenca visivel no material (ex.: registro antigo sem perfil/pipeline)
        return _resultado("miss", "chave_alterada", chave_ant)
    return _resultado("miss", "campos_alterados", chave_ant, dif)
