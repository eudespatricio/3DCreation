"""Contrato de entrada: carregar, normalizar, validar (spec@1).

Ordem obrigatoria — e ela que o contrato promete:

    carregar -> normalizar (aliases + defaults por perfil) -> validar schema -> regras de negocio

Normalizar antes de validar e o que permite aceitar ``minecraft_bedrock`` como alias legado sem
que o valor canonico apareca em manifesto publicado (I14).
"""

from __future__ import annotations

from pathlib import Path

import jsonschema
import yaml

from . import paths, profiles
from .errors import erro_spec

__all__ = ["carregar_arquivo", "preparar", "SPEC_SCHEMA"]

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
    "colisao",
    "lod",
    "seed",
    "auto_rig",
    "esqueleto",
    "origem",
    "tags",
    "animacoes_base",
    "paleta",
)

_SPEC_SCHEMA_CACHE: dict | None = None


def SPEC_SCHEMA() -> dict:  # noqa: N802 - constante com carga preguicosa
    global _SPEC_SCHEMA_CACHE
    if _SPEC_SCHEMA_CACHE is None:
        arq = paths.raiz_dados() / "schemas" / "spec.v1.schema.json"
        import json

        _SPEC_SCHEMA_CACHE = json.loads(arq.read_text(encoding="utf-8"))
    return _SPEC_SCHEMA_CACHE


def carregar_arquivo(caminho: str | Path) -> dict:
    p = Path(caminho).expanduser()
    if not p.is_file():
        raise erro_spec(f"lote nao encontrado: {p}", arquivo=str(p))
    try:
        if p.suffix.lower() in (".json",):
            import json

            doc = json.loads(p.read_text(encoding="utf-8"))
        else:
            doc = yaml.safe_load(p.read_text(encoding="utf-8"))
    except (yaml.YAMLError, ValueError) as exc:
        raise erro_spec(f"lote ilegivel ({p}): {exc}", arquivo=str(p)) from exc
    if not isinstance(doc, dict):
        raise erro_spec(f"lote precisa ser um objeto no topo ({p})", arquivo=str(p))
    doc["_arquivo"] = str(p)
    return doc


def preparar(doc: dict) -> tuple[dict, dict, list[dict]]:
    """Normaliza e valida. Devolve ``(spec, perfil, avisos)``."""
    avisos: list[dict] = []
    _normalizar(doc, avisos)
    _validar_schema(doc)
    perfil = profiles.carregar(doc["perfil"])
    _resolver_defaults(doc, perfil, avisos)
    _validar_schema(doc)  # de novo: defaults nao podem quebrar o contrato
    _regras_negocio(doc, perfil)
    return doc, perfil, avisos


# ---------------------------------------------------------------- normalizacao


def _normalizar(doc: dict, avisos: list[dict]) -> None:
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
        # rota derivada do estilo global quando ausente
        if "rota" not in item:
            tabela = ROTEAMENTO.get(doc.get("estilo_global", ""), {})
            item["rota"] = tabela.get(item.get("tipo", ""), tabela.get("*", "blocky"))
        # prompt vazio conta como ausente
        if isinstance(item.get("prompt"), str) and not item["prompt"].strip():
            item.pop("prompt")
        # seed herda a base do lote quando a rota exige
        if item.get("rota") == "mesh" and "seed" not in item:
            base = (doc.get("politica") or {}).get("seed_base")
            if base is not None:
                item["seed"] = base


def _resolver_defaults(doc: dict, perfil: dict, avisos: list[dict]) -> None:
    for item in doc["lote"]:
        tipo = item["tipo"]
        item.setdefault("pivot", profiles.pivot_padrao(perfil, tipo))
        item.setdefault("limite_triangulos", profiles.limite_tri_padrao(perfil, tipo))
        item.setdefault("material", "opaque")
        item.setdefault("colisao", profiles.colisao_padrao(perfil, tipo))
        item.setdefault("lod", [100])
        item.setdefault("auto_rig", False)
        item.setdefault("tags", [])
        if item["auto_rig"] and "esqueleto" not in item:
            item["esqueleto"] = profiles.esqueleto_padrao(perfil)
        if item.get("animacoes_base"):
            avisos.append(
                {
                    "codigo": "FORGE-W-ANIM",
                    "mensagem": (
                        f"{item['id']}: 'animacoes_base' e reservado (D14) e nao gera animacao nesta fase"
                    ),
                }
            )


# ---------------------------------------------------------------- validacao


def _validar_schema(doc: dict) -> None:
    limpo = {k: v for k, v in doc.items() if not k.startswith("_")}
    validador = jsonschema.Draft202012Validator(SPEC_SCHEMA())
    erros = sorted(validador.iter_errors(limpo), key=lambda e: list(e.path))
    if erros:
        detalhes = [
            {"campo": "/".join(str(p) for p in e.path) or "(raiz)", "mensagem": e.message}
            for e in erros[:10]
        ]
        raise erro_spec(
            f"spec invalida: {detalhes[0]['campo']}: {detalhes[0]['mensagem']}",
            erros=detalhes,
            total=len(erros),
        )


def _regras_negocio(doc: dict, perfil: dict) -> None:
    """B1-B10 alem do schema. Uma lista de erros por rodada (nao para no primeiro)."""
    erros: list[dict] = []
    ids: set[str] = set()
    esqueletos = profiles.mapas_esqueleto(perfil)

    for item in doc["lote"]:
        iid = item.get("id", "?")

        if iid in ids:
            erros.append({"id": iid, "regra": "B1", "mensagem": "id duplicado no lote"})
        ids.add(iid)

        if item.get("rota") == "mesh" and "seed" not in item:
            erros.append(
                {"id": iid, "regra": "B2", "mensagem": "rota mesh exige 'seed' (ou politica.seed_base)"}
            )

        if item.get("rota") == "import":
            origem = item.get("origem")
            if not origem:
                erros.append({"id": iid, "regra": "B3", "mensagem": "rota import exige 'origem'"})
            else:
                p = Path(origem).expanduser()
                if not p.is_file():
                    erros.append(
                        {"id": iid, "regra": "B3", "mensagem": f"origem inexistente: {p}"}
                    )

        lod = item.get("lod") or [100]
        if lod[0] != 100 or any(a <= b for a, b in zip(lod, lod[1:])):
            erros.append(
                {"id": iid, "regra": "B4", "mensagem": f"lod precisa comecar em 100 e decrescer: {lod}"}
            )

        limite = item.get("limite_triangulos", 0)
        if limite > 50000:
            erros.append({"id": iid, "regra": "B5", "mensagem": f"limite_triangulos {limite} > 50000"})

        if item.get("auto_rig") and item.get("tipo") not in ("personagem_humanoide", "criatura"):
            erros.append(
                {"id": iid, "regra": "B6", "mensagem": "auto_rig so em personagem_humanoide/criatura"}
            )

        if item.get("auto_rig"):
            esq = item.get("esqueleto") or perfil["rig"]["esqueleto_padrao"]
            if esq not in esqueletos:
                erros.append(
                    {
                        "id": iid,
                        "regra": "B10",
                        "mensagem": f"esqueleto '{esq}' nao existe no perfil (tem: {', '.join(esqueletos)})",
                    }
                )

    if erros:
        raise erro_spec(
            f"{len(erros)} violacao(oes) de regra de negocio",
            erros=erros,
            total=len(erros),
        )


def resolver_item(item: dict) -> dict:
    """Item canonico usado na chave de cache: so o que afeta a saida."""
    from .canonical import sha256_arquivo

    resolvido = {k: item[k] for k in CAMPOS_CANONICOS_ITEM if k in item}
    resolvido.setdefault("tags", [])
    if item.get("rota") == "import" and item.get("origem"):
        p = Path(item["origem"]).expanduser()
        try:
            resolvido["origem_hash"] = sha256_arquivo(p)
        except OSError:
            resolvido["origem_hash"] = "indisponivel"
    return resolvido
