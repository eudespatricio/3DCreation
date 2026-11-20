"""Estimadores calibrados e de pior caso para ``plan --scene-budget`` (G11)."""

from __future__ import annotations

from pathlib import Path

from . import profiles, qc
from .plan_inspect import (
    _EXTS_3D,
    _atlas_px_blocky,
    _detalhe_alto_ativo,
    _estimar_modular_tris,
    _inspecionar_arquivo_3d,
    _px_bake_estimado,
    _tex_max_perfil,
    _texturas_bake_pbr,
)
from .providers import blocky as blocky_provider
from .providers import mesh as mesh_provider
from .spec import ALIASES_ESTILO, ROTEAMENTO

_TRIS_MODULAR_ARMOR: dict[str, int] = {
    "luvas": 2400,
    "peitoral": 2800,
    "elmo": 2200,
    "ombreiras": 1800,
    "calcas": 2200,
    "calças": 2200,
    "botas": 2000,
    "capa": 2000,
    "arma": 1500,
    "escudo": 1000,
    "mochila": 1700,
    "orbe": 1850,
    "sela": 1200,
}

_SKINNED_MODULAR_PADRAO: dict[str, bool] = {
    "peitoral": True,
    "luvas": True,
    "calcas": True,
    "calças": True,
    "botas": True,
    "corpo": True,
    "ombreiras": True,
}

_PRIM_MODULAR_ARMOR: dict[str, int] = {
    "luvas": 1,
    "corpo": 1,
    "peitoral": 2,
    "elmo": 2,
    "ombreiras": 2,
    "calcas": 2,
    "calças": 2,
    "botas": 2,
    "capa": 2,
    "escudo": 3,
    "mochila": 3,
    "orbe": 3,
    "sela": 3,
    "arma": 4,
}


def _resolver_rota(item: dict, spec_doc: dict) -> str:
    rota = str(item.get("rota") or "").strip().lower()
    if rota:
        return rota
    estilo = str(item.get("estilo") or spec_doc.get("estilo_global") or "").strip()
    if estilo in ALIASES_ESTILO:
        estilo = ALIASES_ESTILO[estilo]
    tabela = ROTEAMENTO.get(estilo, {})
    return str(tabela.get(str(item.get("tipo") or ""), tabela.get("*", "blocky")))


def _eh_pbr(item: dict) -> bool:
    return (
        item.get("material") == "pbr"
        or bool(item.get("pbr_zonas"))
        or bool(item.get("material_procedural"))
    )


def _rig_modo_skinned(item: dict) -> bool:
    return str((item.get("rig") or {}).get("modo") or "").strip().lower() in (
        "motor6d",
        "skinned",
    )


def _estimar_item_teto(item: dict, perfil: dict) -> dict:
    iid = str(item.get("id") or "?")
    tipo = str(item.get("tipo") or "prop_estatico")
    qualidade = str(item.get("qualidade") or "standard").strip().lower()
    tris = int(item.get("limite_triangulos") or profiles.limite_tri_qualidade(perfil, tipo, qualidade))
    qtd = int(item.get("quantidade_cena", 1))
    n_partes = len(item.get("partes") or [])
    skinned = (
        bool(item.get("auto_rig"))
        or bool(item.get("skinned"))
        or _rig_modo_skinned(item)
    )
    eh_pbr = _eh_pbr(item)
    mat_max_perfil = max(1, int((perfil.get("validacao") or {}).get("materiais_max") or 1))
    tex_max_perfil = int(
        (perfil.get("material") or {}).get("textura_max")
        or (perfil.get("validacao") or {}).get("textura_max")
        or 1024
    )
    px_base, px_sub = _px_bake_estimado(qualidade, perfil)
    px_teto = max(px_base, min(tex_max_perfil, 2048))
    if eh_pbr or _detalhe_alto_ativo(item):
        texturas = [
            {"id": f"{iid}:color", "px": px_teto, "canais": 4},
            {"id": f"{iid}:normal", "px": px_sub, "canais": 4},
            {"id": f"{iid}:orm", "px": px_sub, "canais": 4},
            {"id": f"{iid}:roughness", "px": px_sub, "canais": 1},
            {"id": f"{iid}:metallic", "px": px_sub, "canais": 1},
            {"id": f"{iid}:emb:0", "px": px_teto, "canais": 4},
            {"id": f"{iid}:emb:1", "px": px_sub, "canais": 4},
            {"id": f"{iid}:emb:2", "px": px_sub, "canais": 4},
        ]
        for idx in range(3, mat_max_perfil):
            texturas.append({"id": f"{iid}:emb:{idx}", "px": 512, "canais": 4})
    else:
        px_simples = min(px_teto, 1024)
        texturas = [
            {"id": f"{iid}:albedo", "px": px_simples, "canais": 4},
            {"id": f"{iid}:emb:0", "px": px_simples, "canais": 4},
        ]
        for idx in range(1, mat_max_perfil):
            texturas.append({"id": f"{iid}:emb:{idx}", "px": 512, "canais": 4})
    return {
        "id": iid,
        "tris": tris,
        "primitivas": max(mat_max_perfil, n_partes),
        "quantidade_cena": qtd,
        "mesh_key": str(item.get("mesh_key") or iid),
        "material_key": f"pbr:{iid}" if eh_pbr else "palette_padrao",
        "skinned": skinned,
        "texturas": texturas,
    }


def _estimar_template_humanoide_texturas(
    iid: str, item: dict, perfil: dict, qualidade: str, detalhe_alto: bool, mat_max_perfil: int
) -> tuple[list[dict], int]:
    mat_proc = str(item.get("material_procedural") or "").strip()
    if (mat_proc and mat_proc != "pele_humana") or bool(item.get("pbr_zonas")) or detalhe_alto:
        return _texturas_bake_pbr(iid, item, perfil, qualidade), 1
    primitivas = max(1, min(mat_max_perfil, 8 if qualidade in ("hero", "ultra") else 6))
    tex_perfil_base = int((perfil.get("material") or {}).get("textura_max") or 1024)
    tex_cap = max(256, min(tex_perfil_base, 2048))
    texturas = [
        {"id": f"{iid}:baseColor", "px": tex_cap, "canais": 4},
        {"id": f"{iid}:emb:0", "px": tex_cap, "canais": 4},
        {"id": f"{iid}:emb:1", "px": tex_cap, "canais": 4},
        {"id": f"{iid}:emb:2", "px": 1024, "canais": 4},
        *[{"id": f"{iid}:emb:{k}", "px": 512, "canais": 4} for k in range(3, 8)],
    ]
    return texturas, primitivas


def _estimar_modular_armor_texturas(
    iid: str, item: dict, perfil: dict, qualidade: str, detalhe_alto: bool, mat_max_perfil: int, parte: str
) -> tuple[list[dict], int]:
    if bool(item.get("material_procedural")) or bool(item.get("pbr_zonas")) or detalhe_alto:
        return _texturas_bake_pbr(iid, item, perfil, qualidade), 1
    primitivas = max(1, min(mat_max_perfil, _PRIM_MODULAR_ARMOR.get(parte, 2)))
    texturas = [
        {"id": f"{iid}:emb:0", "px": 1024, "canais": 4},
        {"id": f"{iid}:emb:1", "px": 1024, "canais": 4},
        {"id": f"{iid}:emb:2", "px": 512, "canais": 4},
        {"id": f"{iid}:emb:3", "px": 512, "canais": 4},
    ]
    return texturas, primitivas


def _estimar_item_calibrado(item: dict, spec_doc: dict, perfil: dict) -> dict:
    """Estimador calibrado por rota usando apenas sinais baratos pre-run (sem Blender/GPU)."""
    iid = str(item.get("id") or "?")
    tipo = str(item.get("tipo") or "prop_estatico")
    qualidade = str(item.get("qualidade") or "standard").strip().lower()
    limite_tri = int(
        item.get("limite_triangulos") or profiles.limite_tri_qualidade(perfil, tipo, qualidade)
    )
    qtd = int(item.get("quantidade_cena", 1))
    rota = _resolver_rota(item, spec_doc)
    eh_pbr = _eh_pbr(item)
    retopologia = str(item.get("retopologia") or "padrao").strip().lower()
    detalhe_alto = _detalhe_alto_ativo(item)
    n_partes = len(item.get("partes") or [])
    skinned = (
        bool(item.get("auto_rig"))
        or bool(item.get("skinned"))
        or _rig_modo_skinned(item)
    )

    tris_est: int
    fonte: str
    texturas: list[dict]
    primitivas = 1
    mat_max_perfil = int((perfil.get("validacao") or {}).get("materiais_max") or 8)

    if rota == "blocky":
        altura = float(item.get("altura_metros") or 1.0)
        paleta = item.get("paleta") or spec_doc.get("paleta")
        caixas = blocky_provider._caixas(tipo, altura, {**item, "_paleta": paleta})
        tris_est = min(limite_tri, len(caixas) * 12)
        atlas_px = _atlas_px_blocky(caixas)
        texturas = [
            {"id": f"{iid}:baseColor", "px": atlas_px, "canais": 4},
            {"id": f"{iid}:emb:0", "px": atlas_px, "canais": 4},
        ]
        fonte = "blocky_template"

    elif rota == "modular":
        tris_mod, fonte = _estimar_modular_tris(item)
        tris_est = min(limite_tri, tris_mod)
        texturas = [
            {"id": f"{iid}:baseColor", "px": 32, "canais": 4},
            {"id": f"{iid}:emb:0", "px": 32, "canais": 4},
        ]

    elif rota == "import":
        raw_origem = str(item.get("origem") or "").strip()
        info = _inspecionar_arquivo_3d(Path(raw_origem).expanduser()) if raw_origem else None
        if info and info["tris"] > 0:
            tris_est = min(limite_tri, int(info["tris"]))
            fonte = f"{info['formato']}_header"
        else:
            tris_est = min(limite_tri, max(12, round(limite_tri * 0.35)))
            fonte = "import_heuristica"
        if info and info["skinned"]:
            skinned = True
        tem_uv = bool(info["tem_uv"]) if info else True
        tem_mat = (int(info["materiais"]) > 0) if info else True
        tem_cor = bool(info["tem_cor_vertice"]) if info else False
        deve_bake = (
            tem_cor
            or bool(item.get("material_procedural"))
            or bool(item.get("pbr_zonas"))
            or (str(item.get("material") or "").strip().lower() == "pbr" and (tem_uv or tem_mat))
            or (detalhe_alto and (tem_uv or tem_mat))
            or (retopologia == "quadriflow" and tem_uv and tem_mat)
        )
        if deve_bake:
            texturas = _texturas_bake_pbr(iid, item, perfil, qualidade)
            primitivas = 1
        else:
            if info and info.get("primitivas"):
                primitivas = max(1, min(mat_max_perfil, int(info["primitivas"])))
            if info and info["imagens_px"]:
                texturas = [
                    {"id": f"{iid}:emb:{idx}", "px": px_img, "canais": 4}
                    for idx, px_img in enumerate(info["imagens_px"])
                ]
            else:
                px_fb = min(_tex_max_perfil(perfil, qualidade) or 1024, 1024)
                texturas = [{"id": f"{iid}:emb:0", "px": px_fb, "canais": 4}]

    elif rota == "i23d":
        raw_origem = str(item.get("origem") or "").strip()
        origem_path = Path(raw_origem).expanduser() if raw_origem else None
        info = (
            _inspecionar_arquivo_3d(origem_path)
            if origem_path is not None and origem_path.suffix.lower() in _EXTS_3D
            else None
        )
        if info and info["tris"] > 0:
            tris_est = min(limite_tri, int(info["tris"]))
            fonte = f"i23d_{info['formato']}_header"
            if info["skinned"]:
                skinned = True
        else:
            tris_est = min(limite_tri, round(limite_tri * 0.95))
            fonte = "i23d_heuristica"
        texturas = _texturas_bake_pbr(iid, item, perfil, qualidade)

    elif rota == "template":
        if mesh_provider._usar_makehuman_cabelo(item):
            tris_est = min(limite_tri, 2500)
            fonte = "template_makehuman_cabelo"
            texturas = [{"id": f"{iid}:emb:0", "px": 1024, "canais": 4}]
        elif mesh_provider._usar_modular_armor(item):
            parte = str(item.get("parte") or "peitoral").strip().lower()
            tris_est = min(limite_tri, _TRIS_MODULAR_ARMOR.get(parte, round(limite_tri * 0.75)))
            fonte = "template_modular_armor"
            if item.get("skinned") is None and not item.get("auto_rig"):
                skinned = _SKINNED_MODULAR_PADRAO.get(parte, False)
            texturas, primitivas = _estimar_modular_armor_texturas(
                iid, item, perfil, qualidade, detalhe_alto, mat_max_perfil, parte
            )
        else:
            tris_est = min(limite_tri, round(limite_tri * 0.98))
            fonte = "template_humanoide"
            auto_rig_padrao = (
                tipo
                in (
                    "personagem_humanoide",
                    "criatura",
                    "criatura_quadrupede",
                    "criatura_alada",
                    "montaria",
                )
                and str((item.get("rig") or {}).get("modo") or "").strip().lower() != "none"
            )
            skinned = bool(item.get("auto_rig", auto_rig_padrao)) or bool(item.get("skinned")) or skinned
            texturas, primitivas = _estimar_template_humanoide_texturas(
                iid, item, perfil, qualidade, detalhe_alto, mat_max_perfil
            )

    elif rota == "procedural":
        if mesh_provider._usar_template_criatura(item):
            tris_est = min(limite_tri, round(limite_tri * 0.95))
            fonte = "procedural_template_criatura"
            skinned = bool(item.get("auto_rig", True)) or bool(item.get("skinned")) or skinned
        else:
            tris_est = min(limite_tri, round(limite_tri * 0.95))
            fonte = "procedural_heuristica"
        texturas = _texturas_bake_pbr(iid, item, perfil, qualidade)

    elif rota == "extrude_2d":
        tris_est = min(limite_tri, round(limite_tri * 0.90))
        fonte = "extrude_2d"
        texturas = [
            {"id": f"{iid}:baseColor", "px": 1024, "canais": 4},
            {"id": f"{iid}:emb:0", "px": 1024, "canais": 4},
        ]

    else:
        raw_origem = str(item.get("origem") or "").strip()
        origem_path = Path(raw_origem).expanduser() if raw_origem else None
        info = (
            _inspecionar_arquivo_3d(origem_path)
            if origem_path is not None and origem_path.suffix.lower() in _EXTS_3D
            else None
        )
        if info and info["tris"] > 0:
            tris_est = min(limite_tri, int(info["tris"]))
            fonte = f"mesh_{info['formato']}_header"
            if info["skinned"]:
                skinned = True
            texturas = _texturas_bake_pbr(iid, item, perfil, qualidade)
        elif mesh_provider._usar_makehuman_cabelo(item):
            tris_est = min(limite_tri, 2500)
            fonte = "mesh_makehuman_cabelo"
            texturas = [{"id": f"{iid}:emb:0", "px": 1024, "canais": 4}]
        elif mesh_provider._usar_modular_armor(item):
            parte = str(item.get("parte") or "peitoral").strip().lower()
            tris_est = min(limite_tri, _TRIS_MODULAR_ARMOR.get(parte, round(limite_tri * 0.75)))
            fonte = "mesh_modular_armor"
            if item.get("skinned") is None and not item.get("auto_rig"):
                skinned = _SKINNED_MODULAR_PADRAO.get(parte, False)
            texturas, primitivas = _estimar_modular_armor_texturas(
                iid, item, perfil, qualidade, detalhe_alto, mat_max_perfil, parte
            )
        elif mesh_provider._usar_template_criatura(item):
            tris_est = min(limite_tri, round(limite_tri * 0.95))
            fonte = "mesh_template_criatura"
            skinned = bool(item.get("auto_rig", True)) or bool(item.get("skinned")) or skinned
            texturas = _texturas_bake_pbr(iid, item, perfil, qualidade)
        elif (
            item.get("template_humanoide") is True
            or bool(item.get("makehuman_cabelo"))
            or mesh_provider._usar_template_humanoide(item)
        ):
            tris_est = min(limite_tri, round(limite_tri * 0.98))
            fonte = "mesh_template_humanoide"
            skinned = bool(item.get("auto_rig", True)) or bool(item.get("skinned")) or skinned
            texturas, primitivas = _estimar_template_humanoide_texturas(
                iid, item, perfil, qualidade, detalhe_alto, mat_max_perfil
            )
        elif mesh_provider._usar_extrude_2d(item):
            tris_est = min(limite_tri, round(limite_tri * 0.90))
            fonte = "mesh_extrude_2d"
            texturas = [
                {"id": f"{iid}:baseColor", "px": 1024, "canais": 4},
                {"id": f"{iid}:emb:0", "px": 1024, "canais": 4},
            ]
        else:
            tris_est = min(limite_tri, round(limite_tri * 0.95))
            fonte = "mesh_heuristica"
            texturas = _texturas_bake_pbr(iid, item, perfil, qualidade)

    if n_partes > 0:
        primitivas = max(primitivas, n_partes)

    vram_item = round(
        sum(qc._vram_mapa_mb(int(t["px"]), int(t["canais"])) for t in texturas),
        2,
    )
    return {
        "id": iid,
        "tris": tris_est,
        "primitivas": primitivas,
        "quantidade_cena": qtd,
        "mesh_key": str(item.get("mesh_key") or iid),
        "material_key": f"pbr:{iid}" if eh_pbr else "palette_padrao",
        "skinned": skinned,
        "texturas": texturas,
        "_meta": {
            "rota": rota,
            "fonte": fonte,
            "primitivas": primitivas,
            "skinned": skinned,
            "draw_calls": (qtd * primitivas if skinned else (primitivas if qtd > 0 else 0)),
            "vram_mb": vram_item,
        },
    }


def _vram_lista_mb(texturas: list[dict]) -> float:
    return sum(qc._vram_mapa_mb(int(t["px"]), int(t["canais"])) for t in texturas)


def estimar_orcamento_cena(spec_doc: dict, perfil: dict) -> dict:
    """Estima o orcamento de cena (Gate G11) separando ``teto_pior_caso`` e ``estimativa`` calibrada."""
    lote = spec_doc.get("lote") or []
    itens_teto = [_estimar_item_teto(item, perfil) for item in lote]
    itens_est = [_estimar_item_calibrado(item, spec_doc, perfil) for item in lote]

    for teto_it, est_it in zip(itens_teto, itens_est):
        teto_it["tris"] = max(int(teto_it["tris"]), int(est_it["tris"]))
        teto_it["primitivas"] = max(int(teto_it["primitivas"]), int(est_it["primitivas"]))
        teto_it["skinned"] = bool(teto_it["skinned"]) or bool(est_it["skinned"])
        if _vram_lista_mb(est_it["texturas"]) > _vram_lista_mb(teto_it["texturas"]):
            teto_it["texturas"] = list(est_it["texturas"])

    limite = profiles.orcamento_cena_perfil(perfil, spec_doc)
    rel_teto = qc.verificar_g11_orcamento_cena(itens_teto, limite_cena=limite)
    rel_est = qc.verificar_g11_orcamento_cena(itens_est, limite_cena=limite)

    meta_por_id = {it["id"]: it["_meta"] for it in itens_est}
    itens_est_detalhados = [
        {**entry, **meta_por_id.get(entry["id"], {})}
        for entry in (rel_est["medido"].get("itens") or [])
    ]
    est_medido = {**rel_est["medido"], "itens": itens_est_detalhados}

    return {
        "id": rel_teto["id"],
        "status": rel_teto["status"],
        "medido": rel_teto["medido"],
        "limite": rel_teto["limite"],
        "codigo": rel_teto["codigo"],
        "nao_bloqueante": True,
        "teto_pior_caso": {
            "status": rel_teto["status"],
            "codigo": rel_teto["codigo"],
            **rel_teto["medido"],
        },
        "estimativa": {
            "status": rel_est["status"],
            "codigo": rel_est["codigo"],
            **est_medido,
        },
    }
