"""Regras de negocio B1-B25 e I14 alem do JSON Schema de spec."""

from __future__ import annotations

import re
from pathlib import Path

from . import profiles
from .errors import erro_spec
from .spec_regras_origem import validar_makehuman_item, validar_requisicao_externa

#: I14: nomes de franquia proibidos em id/tags/prompt de ativos de contrato (evita bare 'halo')
RE_I14 = re.compile(
    r"(?<![a-z0-9])("
    r"minecraft|fortnite|zelda|mario|pokemon|pok[eé]mon|nintendo|overwatch|valorant|call[ _-]?of[ _-]?duty"
    r")(?![a-z0-9])",
    re.IGNORECASE,
)


def regras_negocio(doc: dict, perfil: dict) -> None:
    """B1-B25 alem do schema. Uma lista de erros por rodada (nao para no primeiro)."""
    erros: list[dict] = []
    ids: set[str] = set()
    esqueletos = profiles.mapas_esqueleto(perfil)

    for item in doc["lote"]:
        iid = item.get("id", "?")

        if iid in ids:
            erros.append({"id": iid, "regra": "B1", "mensagem": "id duplicado no lote"})
        ids.add(iid)

        rota_item = item.get("rota")
        origem_limpa = str(item.get("origem") or "").strip()
        precisa_seed = (
            rota_item in ("mesh", "modular", "procedural")
            or (rota_item in ("i23d", "extrude_2d") and not origem_limpa)
            or (
                rota_item == "template"
                and not (origem_limpa or item.get("makehuman_cabelo") or item.get("parte"))
            )
        )
        if precisa_seed and "seed" not in item:
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
            origem = str(item.get("origem") or "").strip()
            if not origem:
                erros.append({"id": iid, "regra": "B3", "mensagem": "rota import exige 'origem'"})
            else:
                from .providers import importer

                p = Path(origem).expanduser()
                if not p.is_file() and p.name.lower() in (
                    "runestone_obelisk.glb",
                    "arcane_fern_cards.glb",
                    "runeblade_kitbash.glb",
                ):
                    from . import vault as _vault

                    _vault.garantir_fixture_kitbash_showcase(p)
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

        ref_estilo = item.get("referencia_estilo")
        if ref_estilo:
            prov_conceito_raw = str(item.get("provider_conceito") or "auto").strip().lower()
            if origem_limpa:
                # D-01: origem e input do i23d e referencia_estilo ancora o concept; juntos o
                # concept nunca roda (mesh.gerar pula quando ha origem) e a referencia seria
                # ignorada em silencio.
                erros.append(
                    {
                        "id": iid,
                        "regra": "B23",
                        "mensagem": "'origem' e 'referencia_estilo' sao mutuamente exclusivos",
                    }
                )
            elif item.get("rota") not in ("mesh", "i23d", "template", "procedural", "extrude_2d"):
                erros.append(
                    {
                        "id": iid,
                        "regra": "B23",
                        "mensagem": "'referencia_estilo' so existe na rota mesh ou sub-rotas visuais",
                    }
                )
            elif prov_conceito_raw in ("sd15", "higgsfield"):
                erros.append(
                    {
                        "id": iid,
                        "regra": "B23",
                        "mensagem": (
                            f"'referencia_estilo' exige provider_conceito 'gemini' ou 'auto' "
                            f"(recebido '{prov_conceito_raw}')"
                        ),
                    }
                )
            else:
                p_ref = Path(str(ref_estilo)).expanduser()
                if not p_ref.is_file():
                    erros.append(
                        {
                            "id": iid,
                            "regra": "B23",
                            "mensagem": f"referencia_estilo inexistente: {p_ref}",
                        }
                    )
                elif p_ref.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
                    erros.append(
                        {
                            "id": iid,
                            "regra": "B23",
                            "mensagem": f"extensao '{p_ref.suffix}' invalida para referencia_estilo",
                        }
                    )

        campos_i14 = [str(iid)] + [str(t) for t in (item.get("tags") or [])]
        if item.get("prompt"):
            campos_i14.append(str(item["prompt"]))
        for txt_i14 in campos_i14:
            achado_i14 = RE_I14.search(txt_i14)
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

        if item.get("auto_rig") and item.get("tipo") not in (
            "personagem_humanoide",
            "criatura",
            "criatura_quadrupede",
            "criatura_alada",
            "montaria",
        ):
            erros.append(
                {
                    "id": iid,
                    "regra": "B6",
                    "mensagem": "auto_rig so em personagem_humanoide, criatura, criatura_quadrupede, criatura_alada ou montaria",
                }
            )

        if item.get("auto_rig"):
            esq = profiles.esqueleto_para_item(perfil, item)
            if esq not in esqueletos:
                erros.append(
                    {
                        "id": iid,
                        "regra": "B10",
                        "mensagem": f"esqueleto '{esq}' nao existe no perfil (tem: {', '.join(esqueletos)})",
                    }
                )
            # B24 (D-02): combinacao esqueleto x tipo claramente incompativel. "criatura" generico
            # aceita qualquer familia (mob bipede com esqueleto humanoide e valido).
            tipo_b24 = item.get("tipo")
            humano_b24 = esq in ("godot-humanoid@1", "godot-humanoid-aa@1", "r15@1")
            criatura_b24 = esq in ("quadruped@1", "winged_mount@1")
            if criatura_b24 and tipo_b24 == "personagem_humanoide":
                erros.append(
                    {
                        "id": iid,
                        "regra": "B24",
                        "mensagem": f"esqueleto '{esq}' (criatura) incompativel com tipo 'personagem_humanoide'",
                    }
                )
            elif humano_b24 and tipo_b24 in ("criatura_alada", "criatura_quadrupede", "montaria"):
                erros.append(
                    {
                        "id": iid,
                        "regra": "B24",
                        "mensagem": f"esqueleto '{esq}' (humanoide) incompativel com tipo '{tipo_b24}'",
                    }
                )

        # B25 (D123): partes articuladas declaradas. Motor6D exige a lista completa do esqueleto
        # do perfil (sem HumanoidRootPart): o consumidor monta por junta, nao por bbox.
        partes_item = item.get("partes")
        rig_item = item.get("rig") or {}
        modo_rig_item = str(rig_item.get("modo") or "")
        if partes_item:
            nomes_partes = [str(p.get("nome")) for p in partes_item if isinstance(p, dict)]
            if len(set(nomes_partes)) != len(nomes_partes):
                erros.append(
                    {"id": iid, "regra": "B25", "mensagem": "partes com nome duplicado"}
                )
            if modo_rig_item == "motor6d":
                esq_p = str(rig_item.get("esqueleto") or item.get("esqueleto") or "")
                if esq_p not in esqueletos:
                    erros.append(
                        {
                            "id": iid,
                            "regra": "B25",
                            "mensagem": f"rig.modo motor6d exige esqueleto do perfil (tem: {', '.join(esqueletos)})",
                        }
                    )
                else:
                    alvo = [
                        n
                        for n in profiles.mapas_esqueleto(perfil).get(esq_p, [])
                        if n != "HumanoidRootPart"
                    ]
                    faltando = sorted(set(alvo) - set(nomes_partes))
                    sobrando = sorted(set(nomes_partes) - set(alvo))
                    if faltando or sobrando:
                        erros.append(
                            {
                                "id": iid,
                                "regra": "B25",
                                "mensagem": f"partes nao batem com {esq_p}: faltando={faltando} sobrando={sobrando}",
                            }
                        )
        elif modo_rig_item == "motor6d":
            erros.append(
                {"id": iid, "regra": "B25", "mensagem": "rig.modo motor6d exige 'partes'"}
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
                "mochila": ("prop_equipavel", "prop_estatico", "personagem_humanoide"),
                "orbe": ("prop_equipavel", "prop_estatico"),
                "sela": (
                    "prop_equipavel",
                    "prop_estatico",
                    "montaria",
                    "criatura_quadrupede",
                    "criatura_alada",
                    "criatura",
                ),
                "asas": (
                    "prop_equipavel",
                    "prop_estatico",
                    "personagem_humanoide",
                    "criatura_alada",
                    "criatura",
                    "montaria",
                ),
            }.get(parte)
            if item.get("rota") not in ("blocky", "mesh", "i23d", "template", "procedural", "extrude_2d"):
                erros.append(
                    {
                        "id": iid,
                        "regra": "B11",
                        "mensagem": "'parte' so existe nas rotas blocky, mesh ou sub-rotas visuais",
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
            if parte in ("capa", "cabelo", "elmo", "escudo", "mochila", "orbe", "sela") and item.get(
                "auto_rig"
            ):
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

        validar_makehuman_item(item, iid, parte, perfil, erros)

    validar_requisicao_externa(doc, erros)

    if erros:
        raise erro_spec(
            f"{len(erros)} violacao(oes) de regra de negocio",
            erros=erros,
            total=len(erros),
        )
