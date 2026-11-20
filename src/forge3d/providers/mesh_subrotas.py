"""Validacao e resolucao estrita de sub-rotas da esteira ``mesh``."""

from __future__ import annotations

import os

from . import mesh_diag as _diag


def resolver_subrota(item: dict, rota_explicita: str | None = None) -> str:
    if rota_explicita:
        return rota_explicita
    raw = str(item.get("rota") or "").strip()
    return raw if raw in _diag.SUBROTAS_EXPLICITAS else "mesh"


def _validar_makehuman_subrota(item: dict, raw_origem: str) -> str | None:
    parte_raw = item.get("parte")
    parte = (str(parte_raw).strip().lower() or None) if parte_raw is not None else None
    tipo = str(item.get("tipo") or "").strip()

    mh_cabelo_val = item.get("makehuman_cabelo")
    if mh_cabelo_val is not None:
        if not str(mh_cabelo_val).strip():
            return "makehuman_cabelo vazio"
        if parte not in (None, "cabelo", "corpo"):
            return f"makehuman_cabelo exige parte 'cabelo' ou 'corpo' (recebeu '{parte}')"
        if tipo == "prop_equipavel" and parte != "cabelo":
            return f"makehuman_cabelo incompativel com tipo '{tipo}' e parte '{parte}'"

    if not raw_origem.startswith("makehuman://"):
        return None

    uri_corpo = raw_origem[len("makehuman://") :].strip("/")
    if uri_corpo == "hair" or uri_corpo.startswith("hair/"):
        estilo = uri_corpo[len("hair/") :].strip("/") if uri_corpo.startswith("hair/") else ""
        if not estilo or "/" in estilo:
            return "makehuman_cabelo / origem makehuman://hair/<estilo> vazio"
        if tipo == "personagem_humanoide" and parte in (None, "corpo"):
            return "origem makehuman://hair/* invalida para corpo humanoide (use parte='cabelo')"
        if parte not in (None, "cabelo"):
            return f"origem '{raw_origem}' incompativel com parte '{parte}' (exige parte='cabelo')"
        if parte is None and tipo not in ("", "prop_estatico"):
            return f"origem '{raw_origem}' exige parte='cabelo' para tipo '{tipo}'"
        return None

    if uri_corpo == "clothes" or uri_corpo.startswith("clothes/"):
        peca = uri_corpo[len("clothes/") :].strip("/") if uri_corpo.startswith("clothes/") else ""
        if not peca:
            return "origem makehuman://clothes/<peca> vazio"
        if parte not in _diag._PARTES_ROUPA_MH:
            return (
                f"origem '{raw_origem}' exige parte de armadura/vestuario "
                f"({', '.join(_diag._PARTES_ROUPA_MH)})"
            )
        return None

    return (
        f"origem MakeHuman invalida: '{raw_origem}' "
        "(esperado makehuman://hair/<estilo> ou makehuman://clothes/<peca>)"
    )


def validar_subrota_item(
    subrota: str, item: dict, rota_explicita: str | None = None
) -> str | None:
    if rota_explicita and item.get("rota") and item.get("rota") != rota_explicita:
        return f"rota '{item.get('rota')}' incompativel com provider '{rota_explicita}'"
    raw_origem = str(item.get("origem") or "").strip()
    tem_entrada = bool(raw_origem or str(item.get("prompt") or "").strip())

    if subrota == "i23d":
        if item.get("extrudir_2d") is True:
            return "rota i23d nao aceita extrudir_2d=True (use rota extrude_2d)"
        if item.get("template_humanoide") is True:
            return "rota i23d nao aceita template_humanoide=True (use rota template)"
        if item.get("makehuman_cabelo") or raw_origem.startswith("makehuman://"):
            return "rota i23d nao aceita makehuman_cabelo / makehuman:// (use rota template)"
        if not tem_entrada:
            return "rota i23d exige 'origem' ou 'prompt'"
        return None

    if subrota == "template":
        if item.get("extrudir_2d") is True:
            return "rota template nao aceita extrudir_2d=True (use rota extrude_2d)"
        if item.get("template_humanoide") is False:
            return "rota template incompativel com template_humanoide=False"
        erro_mh = _validar_makehuman_subrota(item, raw_origem)
        if erro_mh:
            return erro_mh
        mh_cabelo_fn = _diag.facade_attr("_usar_makehuman_cabelo", _diag._usar_makehuman_cabelo)
        estilo_fn = _diag.facade_attr("_extrair_estilo_makehuman", _diag._extrair_estilo_makehuman)
        armor_fn = _diag.facade_attr("_usar_modular_armor", _diag._usar_modular_armor)
        if mh_cabelo_fn(item):
            if not estilo_fn(item):
                return "makehuman_cabelo / origem makehuman://hair/<estilo> vazio"
            return None
        if armor_fn(item):
            return None
        if item.get("tipo") == "personagem_humanoide" and item.get("parte") in (None, "corpo"):
            if raw_origem.startswith("makehuman://"):
                return "origem makehuman:// invalida para corpo humanoide"
            if not tem_entrada:
                return "rota template humanoide exige 'origem' ou 'prompt'"
            return None
        return "rota template requer personagem_humanoide, peca modular_armor ou makehuman_cabelo"

    if subrota == "procedural":
        tipo = str(item.get("tipo") or "").strip()
        if tipo not in ("criatura_alada", "criatura_quadrupede", "montaria"):
            return "rota procedural suporta apenas criatura_alada, criatura_quadrupede ou montaria"
        if raw_origem:
            return "rota procedural nao aceita origem externa (use rota i23d ou import)"
        if item.get("extrudir_2d") is True:
            return "rota procedural nao aceita extrudir_2d=True"
        if item.get("makehuman_cabelo"):
            return "rota procedural nao aceita makehuman_cabelo"
        if item.get("template_humanoide") is False:
            return "rota procedural desabilitada por template_humanoide=False"
        env_flag = os.environ.get("FORGE3D_CRIATURA_TEMPLATE", "").strip().lower()
        if env_flag in ("0", "false", "nao", "off"):
            return "rota procedural desabilitada por FORGE3D_CRIATURA_TEMPLATE"
        return None

    if subrota == "extrude_2d":
        if item.get("extrudir_2d") is False:
            return "rota extrude_2d incompativel com extrudir_2d=False"
        if item.get("template_humanoide") is True:
            return "rota extrude_2d incompativel com template_humanoide=True"
        if item.get("makehuman_cabelo") or raw_origem.startswith("makehuman://"):
            return "rota extrude_2d nao aceita makehuman_cabelo / makehuman://"
        if not tem_entrada:
            return "rota extrude_2d exige 'origem' ou 'prompt'"
        return None

    if subrota == "mesh":
        return _validar_makehuman_subrota(item, raw_origem)
    return None
