"""Contrato de entrada: carregar, normalizar, validar (spec@1 e spec@2).

Ordem obrigatoria — e ela que o contrato promete:

    carregar -> normalizar (aliases + defaults por perfil) -> validar schema -> regras de negocio

Normalizar antes de validar e o que permite aceitar ``minecraft_bedrock`` como alias legado sem
que o valor canonico apareca em manifesto publicado (I14).
"""

from __future__ import annotations

import re
from pathlib import Path

import jsonschema
import yaml

from . import paths, profiles
from .errors import erro_input_tampered, erro_spec

__all__ = ["carregar_arquivo", "preparar", "SPEC_SCHEMA"]

#: I14: nomes de franquia proibidos em id/tags/prompt de ativos de contrato (evita bare 'halo')
_RE_I14 = re.compile(
    r"(?<![a-z0-9])("
    r"minecraft|fortnite|zelda|mario|pokemon|pok[eé]mon|nintendo|overwatch|valorant|call[ _-]?of[ _-]?duty"
    r")(?![a-z0-9])",
    re.IGNORECASE,
)

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
    "parte",
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
    "paleta",
    "estilo",
    "retopologia",
    "quadriflow_faces",
    "modo_rig_roblox",
)

#: contratos de entrada aceitos. spec@2..@4 sao supersets retrocompativeis de spec@1.
SPEC_SCHEMAS = {
    "forge3d/spec@1": "spec.v1.schema.json",
    "forge3d/spec@2": "spec.v2.schema.json",
    "forge3d/spec@3": "spec.v3.schema.json",
    "forge3d/spec@4": "spec.v4.schema.json",
}
_SPEC_SCHEMA_CACHE: dict[str, dict] = {}


def SPEC_SCHEMA(versao: str | None = "forge3d/spec@1") -> dict:  # noqa: N802
    if versao is None or versao not in SPEC_SCHEMAS:
        raise erro_spec(
            f"schema de lote desconhecido: {versao!r} (aceitos: {', '.join(SPEC_SCHEMAS)})",
            schema=versao,
        )
    if versao not in _SPEC_SCHEMA_CACHE:
        arq = paths.raiz_dados() / "schemas" / SPEC_SCHEMAS[versao]
        import json

        _SPEC_SCHEMA_CACHE[versao] = json.loads(arq.read_text(encoding="utf-8"))
    return _SPEC_SCHEMA_CACHE[versao]


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
        # prompt vazio conta como ausente
        if isinstance(item.get("prompt"), str) and not item["prompt"].strip():
            item.pop("prompt")
        # seed herda a base do lote quando a rota exige (mesh e modular: o layout e por seed)
        if item.get("rota") in ("mesh", "modular") and "seed" not in item:
            base = (doc.get("politica") or {}).get("seed_base")
            if base is not None:
                item["seed"] = base

    req = doc.get("requisicao")
    if isinstance(req, dict):
        req.setdefault("isolamento", "padrao")
        req.setdefault("limpar_destino", False)


def _resolver_defaults(doc: dict, perfil: dict, avisos: list[dict]) -> None:
    paleta_lote = doc.get("paleta")
    for item in doc["lote"]:
        tipo = item["tipo"]
        if isinstance(paleta_lote, list) and paleta_lote and "paleta" not in item:
            item["paleta"] = list(paleta_lote)
        item.setdefault("pivot", profiles.pivot_padrao(perfil, tipo))
        if "limite_triangulos" not in item:
            if item.get("qualidade") == "hero":
                item["limite_triangulos"] = profiles.limite_tri_hero(perfil, tipo)
            else:
                item["limite_triangulos"] = profiles.limite_tri_padrao(perfil, tipo)
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
        if item.get("rota") == "modular":
            # mapa_setor nao exige altura no schema; o modulo tem pe-direito proprio
            item.setdefault("altura_metros", 2.4)
        item.setdefault("tags", [])
        if item["auto_rig"] and "esqueleto" not in item:
            item["esqueleto"] = profiles.esqueleto_padrao(perfil)
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
            esqueleto = item.get("esqueleto") or profiles.esqueleto_padrao(perfil)
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


# ---------------------------------------------------------------- validacao


def _validar_schema(doc: dict) -> None:
    limpo = {k: v for k, v in doc.items() if not k.startswith("_")}
    validador = jsonschema.Draft202012Validator(SPEC_SCHEMA(limpo.get("schema")))
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
    """B1-B13 alem do schema. Uma lista de erros por rodada (nao para no primeiro)."""
    erros: list[dict] = []
    ids: set[str] = set()
    esqueletos = profiles.mapas_esqueleto(perfil)

    for item in doc["lote"]:
        iid = item.get("id", "?")

        if iid in ids:
            erros.append({"id": iid, "regra": "B1", "mensagem": "id duplicado no lote"})
        ids.add(iid)

        if item.get("rota") in ("mesh", "modular") and "seed" not in item:
            erros.append(
                {
                    "id": iid,
                    "regra": "B2",
                    "mensagem": f"rota {item['rota']} exige 'seed' (ou politica.seed_base)",
                }
            )

        bloco_modular = item.get("modular")
        if item.get("rota") == "modular":
            if not isinstance(bloco_modular, dict) or "grade" not in bloco_modular:
                erros.append(
                    {
                        "id": iid,
                        "regra": "B15",
                        "mensagem": "rota modular exige o bloco 'modular' com 'grade' e 'modulos'",
                    }
                )
            else:
                nx, ny = (int(v) for v in bloco_modular["grade"])
                setor = bloco_modular.get("setor") or [0, 0]
                if not (0 <= int(setor[0]) < nx and 0 <= int(setor[1]) < ny):
                    erros.append(
                        {
                            "id": iid,
                            "regra": "B16",
                            "mensagem": f"setor {setor} fora da grade {nx}x{ny}",
                        }
                    )
                from . import modular as _modular

                fora = [m for m in bloco_modular.get("modulos") or [] if m not in _modular.CATALOGO]
                if fora:
                    erros.append(
                        {
                            "id": iid,
                            "regra": "B17",
                            "mensagem": (
                                f"modulo(s) fora do catalogo: {', '.join(fora)} "
                                f"(tem: {', '.join(sorted(_modular.CATALOGO))})"
                            ),
                        }
                    )
        elif bloco_modular is not None:
            erros.append(
                {"id": iid, "regra": "B15", "mensagem": "'modular' so existe na rota modular"}
            )

        if item.get("rota") == "import":
            origem = item.get("origem")
            if not origem:
                erros.append({"id": iid, "regra": "B3", "mensagem": "rota import exige 'origem'"})
            else:
                from .providers import importer

                p = Path(origem).expanduser()
                if not p.is_file():
                    erros.append(
                        {"id": iid, "regra": "B3", "mensagem": f"origem inexistente: {p}"}
                    )
                elif p.suffix.lower() not in importer.EXTENSOES:
                    erros.append(
                        {
                            "id": iid,
                            "regra": "B3",
                            "mensagem": (
                                f"extensao '{p.suffix}' nao suportada na rota import "
                                f"(aceitas: {', '.join(sorted(importer.EXTENSOES))})"
                            ),
                        }
                    )

        campos_i14 = [str(iid)] + [str(t) for t in (item.get("tags") or [])]
        if item.get("prompt"):
            campos_i14.append(str(item["prompt"]))
        for txt_i14 in campos_i14:
            achado_i14 = _RE_I14.search(txt_i14)
            if achado_i14:
                erros.append(
                    {
                        "id": iid,
                        "regra": "I14",
                        "mensagem": f"termo de franquia proibido '{achado_i14.group(0)}' (use termo generico)",
                    }
                )
                break

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

        parte = item.get("parte")
        if parte == "calças":
            parte = "calcas"
            item["parte"] = "calcas"
        if parte:
            esperados = {
                "corpo": ("personagem_humanoide",),
                "capa": ("personagem_humanoide", "prop_estatico"),
                "cabelo": ("personagem_humanoide", "prop_estatico"),
                "arma": ("prop_equipavel",),
                "elmo": ("prop_equipavel", "prop_estatico"),
                "ombreiras": ("prop_equipavel", "prop_estatico", "personagem_humanoide"),
                "peitoral": ("prop_equipavel", "personagem_humanoide"),
                "luvas": ("prop_equipavel", "personagem_humanoide"),
                "calcas": ("prop_equipavel", "personagem_humanoide"),
                "botas": ("prop_equipavel", "personagem_humanoide"),
                "escudo": ("prop_equipavel", "prop_estatico"),
            }.get(parte)
            if item.get("rota") not in ("blocky", "mesh"):
                erros.append(
                    {
                        "id": iid,
                        "regra": "B11",
                        "mensagem": "'parte' so existe nas rotas blocky ou mesh",
                    }
                )
            if esperados and item.get("tipo") not in esperados:
                permitidos = " ou ".join(f"'{t}'" for t in esperados)
                erros.append(
                    {
                        "id": iid,
                        "regra": "B12",
                        "mensagem": f"parte '{parte}' exige tipo {permitidos}",
                    }
                )
            if parte in ("capa", "cabelo", "elmo", "escudo") and item.get("auto_rig"):
                erros.append(
                    {
                        "id": iid,
                        "regra": "B13",
                        "mensagem": f"{parte} e peca estatica (auto_rig false) para montar no osso",
                    }
                )

        if item.get("animacoes_base") and not item.get("auto_rig"):
            erros.append(
                {
                    "id": iid,
                    "regra": "B14",
                    "mensagem": "animacoes_base exige auto_rig: sem rig nao ha o que animar",
                }
            )

        mh_cabelo = item.get("makehuman_cabelo")
        raw_origem = str(item.get("origem") or "").strip()
        eh_mh_uri = raw_origem.startswith("makehuman://")
        if (mh_cabelo or eh_mh_uri) and item.get("rota") != "mesh":
            erros.append(
                {
                    "id": iid,
                    "regra": "B18",
                    "mensagem": "makehuman_cabelo / origem makehuman:// so sao suportados na rota mesh",
                }
            )
        if eh_mh_uri:
            uri_corpo = raw_origem[len("makehuman://"):].strip("/")
            eh_hair = uri_corpo.startswith("hair/")
            eh_clothes = uri_corpo.startswith("clothes/")
            if parte == "cabelo":
                estilo_uri = uri_corpo[len("hair/"):].strip("/") if eh_hair else uri_corpo
                if (
                    not uri_corpo
                    or uri_corpo == "hair"
                    or not eh_hair
                    or "/" in estilo_uri
                    or not estilo_uri
                ):
                    erros.append(
                        {
                            "id": iid,
                            "regra": "B21",
                            "mensagem": f"origem MakeHuman invalida: '{raw_origem}' (esperado makehuman://hair/<estilo>)",
                        }
                    )
            else:
                item_uri = (
                    uri_corpo[len("clothes/"):].strip("/")
                    if eh_clothes
                    else (uri_corpo[len("hair/"):].strip("/") if eh_hair else uri_corpo)
                )
                if (
                    not uri_corpo
                    or uri_corpo in ("hair", "clothes")
                    or not (eh_hair or eh_clothes)
                    or not item_uri
                ):
                    erros.append(
                        {
                            "id": iid,
                            "regra": "B21",
                            "mensagem": f"origem MakeHuman invalida: '{raw_origem}' (esperado makehuman://clothes/<peca> ou makehuman://hair/<estilo>)",
                        }
                    )
        if mh_cabelo and parte and parte not in ("cabelo", "corpo"):
            erros.append(
                {
                    "id": iid,
                    "regra": "B19",
                    "mensagem": f"makehuman_cabelo exige parte 'cabelo' ou 'corpo' (recebeu '{parte}')",
                }
            )
        if eh_mh_uri:
            uri_corpo_clean = raw_origem[len("makehuman://"):].strip("/")
            if uri_corpo_clean.startswith("hair/"):
                if (
                    (parte and parte not in ("cabelo", "corpo"))
                    or (item.get("tipo") == "personagem_humanoide" and parte != "cabelo")
                ):
                    erros.append(
                        {
                            "id": iid,
                            "regra": "B19",
                            "mensagem": f"origem MakeHuman '{raw_origem}' exige parte 'cabelo' (ou prop_estatico)",
                        }
                    )
            elif uri_corpo_clean.startswith("clothes/"):
                partes_roupa_validas = (
                    "elmo",
                    "peitoral",
                    "ombreiras",
                    "luvas",
                    "calcas",
                    "botas",
                    "escudo",
                    "capa",
                )
                if parte and parte not in partes_roupa_validas:
                    erros.append(
                        {
                            "id": iid,
                            "regra": "B19",
                            "mensagem": f"origem MakeHuman '{raw_origem}' exige parte de armadura/vestuario ({', '.join(partes_roupa_validas)})",
                        }
                    )
        if mh_cabelo and (parte == "corpo" or (item.get("tipo") == "personagem_humanoide" and parte != "cabelo")):
            materiais_max = int((perfil.get("validacao") or {}).get("materiais_max") or 8)
            if materiais_max < 2:
                erros.append(
                    {
                        "id": iid,
                        "regra": "B20",
                        "mensagem": (
                            f"perfil '{perfil.get('perfil')}' limita materiais_max={materiais_max}; "
                            "use item separado com parte: 'cabelo' no osso Head/HatAttachment"
                        ),
                    }
                )

    req = doc.get("requisicao")
    if isinstance(req, dict) and req.get("isolamento") == "estrito" and "base_externa" not in req:
        for item in doc["lote"]:
            item_orig = str(item.get("origem") or "").strip()
            if item_orig and not item_orig.startswith("makehuman://"):
                raise erro_input_tampered(
                    f"item '{item.get('id')}' referencia origem externa nao selada '{item_orig}' "
                    "sem bloco requisicao.base_externa sob isolamento estrito",
                    id=item.get("id"),
                    origem=item_orig,
                    regra="B22",
                )
    if isinstance(req, dict) and "base_externa" in req:
        base_ext = req["base_externa"]
        if isinstance(base_ext, dict):
            origem_raw = str(base_ext.get("origem", "")).strip()
            p = Path(origem_raw).expanduser()
            if not p.is_file():
                raise erro_input_tampered(
                    f"base externa declarada inexistente: {origem_raw}",
                    origem=origem_raw,
                    regra="B22",
                )
            from .canonical import sha256_arquivo

            hash_real = sha256_arquivo(p).removeprefix("sha256:").lower()
            hash_esperado = str(base_ext.get("sha256", "")).removeprefix("sha256:").lower()
            if hash_real != hash_esperado:
                raise erro_input_tampered(
                    f"base externa adulterada ou divergente do hash registrado: esperado {hash_esperado}, obtido {hash_real}",
                    origem=origem_raw,
                    esperado=hash_esperado,
                    obtido=hash_real,
                    regra="B22",
                )
            isolamento = str(req.get("isolamento", "padrao")).strip()
            p_res = p.resolve(strict=False)
            for item in doc.get("lote") or []:
                item_orig = str(item.get("origem") or "").strip()
                if not item_orig:
                    continue
                if "://" in item_orig:
                    continue
                item_p = Path(item_orig).expanduser().resolve(strict=False)
                if item_p == p_res:
                    if "tipo" in base_ext and base_ext["tipo"] != item.get("tipo"):
                        erros.append(
                            {
                                "id": item.get("id"),
                                "regra": "B22",
                                "mensagem": (
                                    f"tipo do item '{item.get('tipo')}' diverge do tipo da "
                                    f"base_externa '{base_ext['tipo']}'"
                                ),
                            }
                        )
                elif isolamento == "estrito":
                    raise erro_input_tampered(
                        f"item '{item.get('id')}' referencia origem externa nao selada '{item_orig}' fora de base_externa sob isolamento estrito",
                        id=item.get("id"),
                        origem=item_orig,
                        base_externa=origem_raw,
                        regra="B22",
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
    if item.get("rota") in ("import", "mesh") and item.get("origem"):
        raw_orig = str(item["origem"]).strip()
        if raw_orig.startswith("makehuman://"):
            resolvido["origem_makehuman"] = raw_orig
        else:
            p = Path(raw_orig).expanduser()
            try:
                resolvido["origem_hash"] = sha256_arquivo(p)
            except OSError:
                resolvido["origem_hash"] = "indisponivel"
    return resolvido
