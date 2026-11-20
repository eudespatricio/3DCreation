"""Constantes canonicas, normalizacao, defaults e chave de cache de itens de spec."""

from __future__ import annotations

from pathlib import Path

from . import profiles

#: alias legado -> valor canonico (D19). Sempre gera FORGE-W-ALIAS.
ALIASES_ESTILO = {
    "minecraft_bedrock": "blocky_voxel",
    "low_poly_pixel_lit": "lowpoly_lit",
}

#: estilo -> rota por tipo (docs/rotas-e-providers.md §1). Deterministico, nunca LLM.
ROTEAMENTO: dict[str, dict[str, str]] = {
    "blocky_voxel": {"*": "blocky"},
    "lowpoly_lit": {
        "personagem_humanoide": "mesh",
        "criatura": "mesh",
        "criatura_quadrupede": "mesh",
        "criatura_alada": "mesh",
        "montaria": "mesh",
        "prop_equipavel": "mesh",
        "prop_estatico": "modular",
        "modulo_cenario": "modular",
        "mapa_setor": "modular",
        "*": "modular",
    },
    "stylized_pbr": {"*": "mesh"},
}

CAMPOS_CANONICOS_ITEM = (
    "id",
    "tipo",
    "rota",
    "prompt",
    "altura_metros",
    "pivot",
    "limite_triangulos",
    "material",
    "material_procedural",
    "suavizacao_normais",
    "provider_conceito",
    "referencia_estilo",
    "vistas",
    "colisao",
    "lod",
    "seed",
    "auto_rig",
    "esqueleto",
    "origem",
    "parte",
    "partes",
    "rig",
    "animacoes",
    "quantidade_cena",
    "qualidade",
    "pose_guard",
    "extrudir_2d",
    "template_humanoide",
    "makehuman_cabelo",
    "cor_cabelo",
    "macro",
    "modular",
    "skinned",
    "attachment_roblox",
    "osso",
    "tags",
    "animacoes_base",
    "clipes",
    "sockets",
    "paleta",
    "estilo",
    "retopologia",
    "quadriflow_faces",
    "modo_rig_roblox",
    "detalhe_alto",
    "pbr_zonas",
    "render_fidelity_roblox",
    "alpha_cards",
    "smart_fit",
)


def normalizar(doc: dict, avisos: list[dict]) -> None:
    estilo = doc.get("estilo_global")
    if estilo in ALIASES_ESTILO:
        avisos.append(
            {
                "codigo": "FORGE-W-ALIAS",
                "mensagem": f"estilo legado '{estilo}' normalizado para '{ALIASES_ESTILO[estilo]}'",
            }
        )
        doc["estilo_global"] = ALIASES_ESTILO[estilo]

    for item in doc.get("lote") or []:
        if not isinstance(item, dict):
            continue
        item_estilo = item.get("estilo")
        if isinstance(item_estilo, str) and item_estilo in ALIASES_ESTILO:
            avisos.append(
                {
                    "codigo": "FORGE-W-ALIAS",
                    "mensagem": (
                        f"{item.get('id', '?')}: estilo legado '{item_estilo}' "
                        f"normalizado para '{ALIASES_ESTILO[item_estilo]}'"
                    ),
                }
            )
            item["estilo"] = ALIASES_ESTILO[item_estilo]
        # rota derivada do estilo do item ou estilo global quando ausente
        if "rota" not in item:
            tabela = ROTEAMENTO.get(item.get("estilo") or doc.get("estilo_global", ""), {})
            item["rota"] = tabela.get(item.get("tipo", ""), tabela.get("*", "blocky"))
        # prompt e origem vazios contam como ausentes
        if isinstance(item.get("prompt"), str) and not item["prompt"].strip():
            item.pop("prompt")
        if isinstance(item.get("origem"), str) and not item["origem"].strip():
            item.pop("origem")
        # seed herda a base do lote quando a rota exige (mesh, modular e sub-rotas visuais)
        if item.get("rota") in (
            "mesh",
            "modular",
            "i23d",
            "template",
            "procedural",
            "extrude_2d",
        ) and "seed" not in item:
            base = (doc.get("politica") or {}).get("seed_base")
            if base is not None:
                item["seed"] = base

    req = doc.get("requisicao")
    if isinstance(req, dict):
        req.setdefault("isolamento", "padrao")
        req.setdefault("limpar_destino", False)


def resolver_defaults(doc: dict, perfil: dict, avisos: list[dict]) -> None:
    paleta_lote = doc.get("paleta")
    for item in doc["lote"]:
        tipo = item["tipo"]
        if isinstance(paleta_lote, list) and paleta_lote and "paleta" not in item:
            item["paleta"] = list(paleta_lote)
        item.setdefault("pivot", profiles.pivot_padrao(perfil, tipo))
        if "limite_triangulos" not in item:
            item["limite_triangulos"] = profiles.limite_tri_qualidade(
                perfil, tipo, item.get("qualidade", "standard")
            )
        eh_mh_cabelo = bool(
            item.get("makehuman_cabelo")
            or str(item.get("origem") or "").strip().startswith("makehuman://")
        )
        if eh_mh_cabelo and (item.get("parte") == "cabelo" or item.get("tipo") == "prop_estatico"):
            item.setdefault("material", "alpha_clip")
        else:
            item.setdefault("material", "opaque")
        item.setdefault("colisao", profiles.colisao_padrao(perfil, tipo))
        item.setdefault("lod", [100])
        item.setdefault("auto_rig", False)
        if item.get("rota") == "modular" or (
            item.get("rota") == "blocky" and item.get("tipo") in ("mapa_setor", "textura")
        ):
            # mapa_setor nao exige altura no schema; modular tem pe-direito proprio e blocky precisa de base
            item.setdefault("altura_metros", 2.4)
        item.setdefault("tags", [])
        if item["auto_rig"] and "esqueleto" not in item:
            item["esqueleto"] = profiles.esqueleto_para_item(perfil, item)
        pedidas = [str(a) for a in (item.get("animacoes_base") or [])]
        desconhecidas = [a for a in pedidas if a not in profiles.ANIMACOES_SUPORTADAS]
        if desconhecidas:
            avisos.append(
                {
                    "codigo": "FORGE-W-ANIM",
                    "mensagem": (
                        f"{item['id']}: clipe(s) {', '.join(desconhecidas)} sem gerador nesta fase "
                        f"(P5 gera: {', '.join(profiles.ANIMACOES_SUPORTADAS)})"
                    ),
                }
            )
        if item.get("rota") == "blocky" and any(int(p) < 50 for p in (item.get("lod") or [100])):
            avisos.append(
                {
                    "codigo": "FORGE-W-LOD",
                    "mensagem": (
                        f"{item['id']}: LOD de blocky abaixo de 50% perde a silhueta "
                        "(a caixa e a unidade de detalhe; medido em GAP-013)"
                    ),
                }
            )
        if pedidas:
            esqueleto = profiles.esqueleto_para_item(perfil, item)
            if not profiles.retarget(perfil, esqueleto):
                avisos.append(
                    {
                        "codigo": "FORGE-W-ANIM",
                        "mensagem": (
                            f"{item['id']}: perfil sem 'rig.retarget' para '{esqueleto}'; "
                            "o clipe nao sera gerado"
                        ),
                    }
                )


def resolver_item(item: dict) -> dict:
    """Item canonico usado na chave de cache: so o que afeta a saida."""
    from .canonical import sha256_arquivo

    resolvido = {k: item[k] for k in CAMPOS_CANONICOS_ITEM if k in item}
    resolvido.setdefault("tags", [])
    if item.get("rota") in ("import", "mesh", "i23d", "template", "extrude_2d") and item.get("origem"):
        raw_orig = str(item["origem"]).strip()
        if raw_orig.startswith("makehuman://"):
            resolvido["origem_makehuman"] = raw_orig
        else:
            p = Path(raw_orig).expanduser()
            try:
                resolvido["origem_hash"] = sha256_arquivo(p)
            except OSError:
                resolvido["origem_hash"] = "indisponivel"
    if item.get("referencia_estilo"):
        p_ref = Path(str(item["referencia_estilo"])).expanduser()
        try:
            resolvido["referencia_estilo_hash"] = sha256_arquivo(p_ref)
        except OSError:
            resolvido["referencia_estilo_hash"] = "indisponivel"
    return resolvido
