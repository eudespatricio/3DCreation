"""Motor geometrico Smart-Fit (camada L3 fachada publica).

Reexporta a API matematica pura (``smart_fit_math``), contato BVH e
``SURFACE_DEFORM`` (``smart_fit_contato``) e oclusao/grip (``smart_fit_oclusao_grip``),
adicionando auto-deteccao de corpo na cena e o despachante JSON-driven.
"""

from __future__ import annotations

import os
import sys
from typing import Any

if __package__:
    from .smart_fit_contato import (  # noqa: F401
        HAS_BPY,
        BVHTree,
        Euler,
        Matrix,
        Vector,
        _amostrar_vertices_mundo,
        _aplicar_surface_deform_cage,
        _bvh_mundo,
        _exigir_bpy,
        _limpar_topologia_smart_fit,
        _mover_objeto_mundo,
        _nao_manifold_bmesh,
        _peca_envolve_corpo_xy,
        bmesh,
        bpy,
        conformar_anatomico,
        encaixar_contato_bvh,
    )
    from .smart_fit_math import (  # noqa: F401
        FOLGA_CONTATO_PADRAO_M,
        _add,
        _as_vec3,
        _canonicalizar_eixo,
        _dot,
        _norm,
        _normalize,
        _pca_3x3,
        _scale,
        _sub,
        calcular_angulos_punho_cilindrico,
        calcular_deslocamento_contato,
        calcular_pca_cilindro,
    )
    from .smart_fit_oclusao_grip import (  # noqa: F401
        _extrair_loops_borda,
        _preencher_loop_fan,
        auto_grip_cilindrico,
        conformar_punho_ao_cabo,
        recortar_oclusao_interna,
    )
else:
    _BLENDER_DIR = os.path.dirname(os.path.abspath(__file__))
    if _BLENDER_DIR not in sys.path:
        sys.path.insert(0, _BLENDER_DIR)
    from smart_fit_contato import (  # noqa: F401
        HAS_BPY,
        BVHTree,
        Euler,
        Matrix,
        Vector,
        _amostrar_vertices_mundo,
        _aplicar_surface_deform_cage,
        _bvh_mundo,
        _exigir_bpy,
        _limpar_topologia_smart_fit,
        _mover_objeto_mundo,
        _nao_manifold_bmesh,
        _peca_envolve_corpo_xy,
        bmesh,
        bpy,
        conformar_anatomico,
        encaixar_contato_bvh,
    )
    from smart_fit_math import (  # noqa: F401
        FOLGA_CONTATO_PADRAO_M,
        _add,
        _as_vec3,
        _canonicalizar_eixo,
        _dot,
        _norm,
        _normalize,
        _pca_3x3,
        _scale,
        _sub,
        calcular_angulos_punho_cilindrico,
        calcular_deslocamento_contato,
        calcular_pca_cilindro,
    )
    from smart_fit_oclusao_grip import (  # noqa: F401
        _extrair_loops_borda,
        _preencher_loop_fan,
        auto_grip_cilindrico,
        conformar_punho_ao_cabo,
        recortar_oclusao_interna,
    )

__all__ = [
    "HAS_BPY",
    "FOLGA_CONTATO_PADRAO_M",
    "calcular_pca_cilindro",
    "calcular_angulos_punho_cilindrico",
    "calcular_deslocamento_contato",
    "encaixar_contato_bvh",
    "conformar_anatomico",
    "recortar_oclusao_interna",
    "auto_grip_cilindrico",
    "conformar_punho_ao_cabo",
    "aplicar_smart_fit_job",
]

_PREFIXOS_EXCLUIDOS = ("_", "UCX_", "UBX_", "USP_", "UCP_", "SmartFit", "Cage")
_SUFIXOS_EXCLUIDOS = ("_high", "_low", "_cage", "_col", "_lod0", "_lod1", "_lod2", "_lod3")
_TOKENS_HELPER = ("cage", "collider", "colisor", "helper", "gizmo", "camera", "proxy")
_TOKENS_EQUIP = (
    "armor",
    "chestplate",
    "peitoral",
    "elmo",
    "helmet",
    "luva",
    "glove",
    "bota",
    "boot",
    "escudo",
    "shield",
    "espada",
    "sword",
    "arma",
    "weapon",
    "placa",
    "stage",
    "floor",
    "ground",
    "pedestal",
    "pauldron",
    "cape",
    "cloak",
    "gauntlet",
    "greave",
    "belt",
    "buckle",
    "cuirass",
    "prop",
)
_TOKENS_CORPO_EXATOS = {
    "herobody",
    "template_body",
    "basebody",
    "humanbody",
    "characterbody",
    "body",
    "corpo",
    "human",
    "humano",
}
_TOKENS_CORPO = ("body", "corpo", "human", "humano", "mannequin", "avatar", "character", "personagem")


def _resolver_objeto_cena(ref: Any):
    if ref is None:
        return None
    if not isinstance(ref, str):
        return ref
    return bpy.data.objects.get(ref)


def _detectar_corpo_cena(peca_obj=None, rig_obj=None):
    """Detecta automaticamente uma malha de corpo na cena quando ``corpo_obj`` nao e informado."""
    if not HAS_BPY or bpy is None:
        return None
    melhor_obj = None
    melhor_score = -1.0
    for obj in bpy.data.objects:
        if obj is None or obj is peca_obj or getattr(obj, "type", None) != "MESH":
            continue
        data = getattr(obj, "data", None)
        if data is None or len(getattr(data, "vertices", ())) == 0:
            continue
        nome = str(getattr(obj, "name", ""))
        nome_low = nome.lower()
        if nome.startswith(_PREFIXOS_EXCLUIDOS) or nome_low.endswith(_SUFIXOS_EXCLUIDOS):
            continue
        if any(tok in nome_low for tok in _TOKENS_HELPER):
            continue
        if any(tok in nome_low for tok in _TOKENS_EQUIP) and nome_low not in _TOKENS_CORPO_EXATOS:
            continue

        has_body_token = False
        score = 0.0
        if nome_low in _TOKENS_CORPO_EXATOS or "herobody" in nome_low or "template_body" in nome_low:
            score += 100.0
            has_body_token = True
        elif any(tok in nome_low for tok in _TOKENS_CORPO):
            score += 50.0
            has_body_token = True
        is_rig_child = rig_obj is not None and (
            obj.parent is rig_obj
            or any(
                getattr(m, "type", None) == "ARMATURE" and getattr(m, "object", None) is rig_obj
                for m in getattr(obj, "modifiers", ())
            )
        )
        if not has_body_token and not is_rig_child:
            continue

        mw = obj.matrix_world
        cantos = [mw @ Vector(c) for c in obj.bound_box]
        z_span = max(c.z for c in cantos) - min(c.z for c in cantos)
        diag = (
            Vector((max(c.x for c in cantos), max(c.y for c in cantos), max(c.z for c in cantos)))
            - Vector((min(c.x for c in cantos), min(c.y for c in cantos), min(c.z for c in cantos)))
        ).length
        if is_rig_child:
            score += 25.0 if (has_body_token or diag >= 0.9) else 24.0
        if score < 25.0:
            continue
        score += z_span * 0.1 + diag * 0.01

        if score > melhor_score:
            melhor_score = score
            melhor_obj = obj
    return melhor_obj


def aplicar_smart_fit_job(
    obj,
    job: dict[str, Any],
    corpo_obj=None,
    rig_obj=None,
) -> dict[str, Any]:
    """Despachante JSON-driven para operacoes Smart-Fit no pipeline Blender."""
    _exigir_bpy()
    if not isinstance(job, dict):
        return {"aplicado": False, "motivo": "job_invalido"}

    cfg = job.get("smart_fit")
    if not isinstance(cfg, dict):
        item_cfg = job.get("item") if isinstance(job.get("item"), dict) else {}
        cfg = item_cfg.get("smart_fit") if isinstance(item_cfg.get("smart_fit"), dict) else None
    if cfg is None:
        cfg = job if any(
            k in job
            for k in (
                "encaixar_contato",
                "contato_bvh",
                "conformar_anatomico",
                "conformar",
                "recortar_oclusao",
                "recortar_oclusao_interna",
                "auto_grip",
                "auto_grip_cilindrico",
                "folga_m",
            )
        ) else {}

    if not cfg:
        return {"aplicado": False, "operacoes": []}

    raw_folga = cfg.get("folga_m")
    folga_padrao = float(raw_folga) if raw_folga is not None else FOLGA_CONTATO_PADRAO_M
    rig_ref = rig_obj or _resolver_objeto_cena(cfg.get("rig")) or (
        obj.parent if obj is not None and getattr(obj.parent, "type", None) == "ARMATURE" else None
    )
    corpo_explicit = cfg.get("corpo") or cfg.get("alvo")
    corpo_ref = corpo_obj or (
        _resolver_objeto_cena(corpo_explicit)
        if corpo_explicit is not None
        else _detectar_corpo_cena(peca_obj=obj, rig_obj=rig_ref)
    )

    resultados: dict[str, Any] = {"aplicado": False, "operacoes": []}
    alvo_ausente = False

    contato_cfg = cfg.get("encaixar_contato") or cfg.get("contato_bvh")
    if contato_cfg and obj is not None:
        c_dict = contato_cfg if isinstance(contato_cfg, dict) else {}
        alvo_explicit = c_dict.get("alvo")
        if isinstance(alvo_explicit, str) and alvo_explicit.strip():
            alvo = _resolver_objeto_cena(alvo_explicit)
        elif alvo_explicit is not None and not isinstance(alvo_explicit, str):
            alvo = _resolver_objeto_cena(alvo_explicit)
        else:
            alvo = corpo_ref
        if alvo is None:
            alvo_ausente = True
        else:
            raw_fc = c_dict.get("folga_m")
            res_c = encaixar_contato_bvh(
                obj,
                alvo,
                direcao=c_dict.get("direcao"),
                folga_m=float(raw_fc) if raw_fc is not None else folga_padrao,
            )
            resultados["encaixar_contato"] = res_c
            resultados["operacoes"].append("encaixar_contato")
            resultados["aplicado"] = True

    conf_cfg = cfg.get("conformar_anatomico") or cfg.get("conformar")
    if conf_cfg and obj is not None:
        cf_dict = conf_cfg if isinstance(conf_cfg, dict) else {}
        cf_explicit = cf_dict.get("corpo") or cf_dict.get("alvo")
        if isinstance(cf_explicit, str) and cf_explicit.strip():
            alvo_cf = _resolver_objeto_cena(cf_explicit)
        elif cf_explicit is not None and not isinstance(cf_explicit, str):
            alvo_cf = _resolver_objeto_cena(cf_explicit)
        else:
            alvo_cf = corpo_ref
        if alvo_cf is None:
            alvo_ausente = True
        else:
            raw_fcf = cf_dict.get("folga_m")
            res_cf = conformar_anatomico(
                obj,
                alvo_cf,
                folga_m=float(raw_fcf) if raw_fcf is not None else folga_padrao,
                usar_surface_deform=bool(cf_dict.get("usar_surface_deform", True)),
            )
            resultados["conformar_anatomico"] = res_cf
            if res_cf.get("aplicado"):
                resultados["operacoes"].append("conformar_anatomico")
                resultados["aplicado"] = True

    ocl_cfg = cfg.get("recortar_oclusao") or cfg.get("recortar_oclusao_interna")
    if ocl_cfg:
        oc_dict = ocl_cfg if isinstance(ocl_cfg, dict) else {}
        oc_corpo_explicit = oc_dict.get("corpo")
        if isinstance(oc_corpo_explicit, str) and oc_corpo_explicit.strip():
            alvo_corpo = _resolver_objeto_cena(oc_corpo_explicit)
        elif oc_corpo_explicit is not None and not isinstance(oc_corpo_explicit, str):
            alvo_corpo = _resolver_objeto_cena(oc_corpo_explicit)
        else:
            alvo_corpo = corpo_ref or obj
        raw_cob = oc_dict.get("pecas_cobertura") or oc_dict.get("coberturas") or []
        coberturas = [_resolver_objeto_cena(x) for x in (raw_cob if isinstance(raw_cob, (list, tuple)) else [raw_cob])]
        coberturas = [c for c in coberturas if c is not None]
        if not coberturas and corpo_ref is not None and obj is not None and obj is not corpo_ref:
            coberturas = [obj]
        if alvo_corpo is not None and coberturas:
            res_oc = recortar_oclusao_interna(
                alvo_corpo,
                coberturas,
                dist_max_m=float(oc_dict.get("dist_max_m", 0.035)),
                limiar_cobertura=float(oc_dict.get("limiar_cobertura", 0.85)),
            )
            resultados["recortar_oclusao"] = res_oc
            resultados["operacoes"].append("recortar_oclusao")
            resultados["aplicado"] = True

    grip_cfg = cfg.get("auto_grip") or cfg.get("auto_grip_cilindrico")
    if grip_cfg and obj is not None:
        g_dict = grip_cfg if isinstance(grip_cfg, dict) else {}
        frac = tuple(g_dict.get("fracao_cabo") or (0.05, 0.35))
        res_g = auto_grip_cilindrico(obj, fracao_cabo=(float(frac[0]), float(frac[1])))
        resultados["auto_grip"] = res_g
        resultados["operacoes"].append("auto_grip")
        resultados["aplicado"] = True
        if rig_ref is not None and bool(g_dict.get("aplicar_no_rig", True)):
            res_p = conformar_punho_ao_cabo(
                rig_ref,
                lado=str(g_dict.get("lado") or "R"),
                grip_info=res_g,
            )
            resultados["conformar_punho"] = res_p
            resultados["operacoes"].append("conformar_punho")

    if not resultados["aplicado"] and (conf_cfg or contato_cfg) and (corpo_ref is None or alvo_ausente):
        resultados["motivo"] = "corpo_nao_encontrado"
    return resultados
