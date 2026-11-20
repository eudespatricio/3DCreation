"""Regras de origem externa de spec: MakeHuman (B18-B21) e requisicao.base_externa (B22)."""

from __future__ import annotations

from pathlib import Path

from .errors import erro_input_tampered


def validar_makehuman_item(
    item: dict,
    iid: str,
    parte: str | None,
    perfil: dict,
    erros: list[dict],
) -> None:
    mh_cabelo = item.get("makehuman_cabelo")
    raw_origem = str(item.get("origem") or "").strip()
    eh_mh_uri = raw_origem.startswith("makehuman://")
    if (mh_cabelo or eh_mh_uri) and item.get("rota") not in ("mesh", "template"):
        erros.append(
            {
                "id": iid,
                "regra": "B18",
                "mensagem": "makehuman_cabelo / origem makehuman:// so sao suportados nas rotas mesh e template",
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
                        "mensagem": (
                            f"origem MakeHuman invalida: '{raw_origem}' "
                            "(esperado makehuman://clothes/<peca> ou makehuman://hair/<estilo>)"
                        ),
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
            if not parte or parte not in partes_roupa_validas:
                erros.append(
                    {
                        "id": iid,
                        "regra": "B19",
                        "mensagem": (
                            f"origem MakeHuman '{raw_origem}' exige parte de armadura/vestuario "
                            f"({', '.join(partes_roupa_validas)})"
                        ),
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


def validar_requisicao_externa(doc: dict, erros: list[dict]) -> None:
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
                if not item_orig or "://" in item_orig:
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
