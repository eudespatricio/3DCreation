"""Verificacao de integridade pos-publicacao: manifestos, hashes e reexecucao G1-G10."""

from __future__ import annotations

import json
from pathlib import Path

from . import paths
from .canonical import sha256_arquivo
from .errors import ForgeError, erro_manifesto, erro_spec

__all__ = [
    "CAMPOS_PROVENIENCIA",
    "VERIFY_ASPECTOS",
    "verificar",
]

MANIFEST_SCHEMA_CACHE: dict[str, dict] = {}

#: versao do contrato por `schema`; `manifest@1..@3` continuam aceitos na leitura (D62)
_VERSAO_POR_SCHEMA = {
    "forge3d/manifest@1": "1",
    "forge3d/manifest@2": "2",
    "forge3d/manifest@3": "3",
    "forge3d/manifest@4": "4",
}

#: aspectos que o `verify --only` sabe recortar (I8/I10)
VERIFY_ASPECTOS = ("manifesto", "hash", "escala", "pivo", "gates")

#: campos de proveniencia que o I10 exige nao-nulos
CAMPOS_PROVENIENCIA = ("spec_hash", "pipeline_version", "determinism", "created_at", "run_id")


def _schema_manifesto(versao: str = "1") -> dict:
    if versao not in MANIFEST_SCHEMA_CACHE:
        arq = paths.raiz_dados() / "schemas" / f"manifest.v{versao}.schema.json"
        MANIFEST_SCHEMA_CACHE[versao] = json.loads(arq.read_text(encoding="utf-8"))
    return MANIFEST_SCHEMA_CACHE[versao]


def _pedidos_verificar(only: str | None) -> set[str] | None:
    """Aspectos pedidos em ``--only``; ``None`` = verificacao completa."""
    if not only:
        return None
    pedidos = {t.strip().lower() for t in str(only).split(",") if t.strip()}
    desconhecidos = sorted(pedidos - set(VERIFY_ASPECTOS))
    if desconhecidos:
        raise erro_spec(
            f"--only com aspecto desconhecido: {', '.join(desconhecidos)} "
            f"(aceitos: {', '.join(VERIFY_ASPECTOS)})",
            aceitos=list(VERIFY_ASPECTOS),
        )
    return pedidos or None


def _faltando_proveniencia(man: dict) -> list[str]:
    """Campos de proveniencia ausentes ou vazios no manifesto (I10)."""
    ausentes = [campo for campo in CAMPOS_PROVENIENCIA if not str(man.get(campo) or "").strip()]
    geometria = (man.get("providers") or {}).get("geometry") or {}
    for campo in ("name", "version"):
        if not str(geometria.get(campo) or "").strip():
            ausentes.append(f"providers.geometry.{campo}")
    if man.get("determinism") == "D2" and geometria.get("seed") is None:
        ausentes.append("providers.geometry.seed")
    licenca = man.get("licenca") or {}
    for campo in ("modelo", "notice"):
        if not str(licenca.get(campo) or "").strip():
            ausentes.append(f"licenca.{campo}")
    return ausentes


def verificar(destino: Path, only: str | None = None) -> dict:
    """Portao de CI: manifesto+hash E reexecucao de G1-G10 contra o perfil atual.

    O hash pega arquivo trocado; a reexecucao pega o caso mais sutil: o perfil do jogo mudou
    (tolerancia, textura_max, mapa de ossos) e o manifesto antigo ficou mentindo.
    """
    import jsonschema

    from . import profiles, qc
    from .publish import _caminho_seguro

    pedidos = _pedidos_verificar(only)

    if not destino.is_dir():
        raise erro_manifesto(f"destino inexistente: {destino}", destino=str(destino))

    manifestos = sorted(destino.glob("*.manifest.json"))
    if not manifestos:
        raise erro_manifesto(f"nenhum manifesto em {destino}", destino=str(destino))

    itens = []
    erros: list[dict] = []
    faltando: list[dict] = []
    deltas_escala: list[float] = []
    deltas_pivo: list[float] = []
    for caminho in manifestos:
        try:
            man = json.loads(caminho.read_text(encoding="utf-8"))
        except ValueError as exc:
            erros.append({"manifesto": caminho.name, "erro": f"json invalido: {exc}"})
            continue
        # D62: cada versao de contrato tem o seu schema; versao desconhecida e erro, nao perdao
        versao = _VERSAO_POR_SCHEMA.get(man.get("schema"))
        if versao is None:
            erros.append(
                {
                    "manifesto": caminho.name,
                    "erro": f"schema desconhecido: {man.get('schema')!r}",
                }
            )
            continue
        validador = jsonschema.Draft202012Validator(_schema_manifesto(versao))
        problemas = [e.message for e in validador.iter_errors(man)][:5]
        if problemas:
            erros.append({"manifesto": caminho.name, "erro": "schema", "detalhes": problemas})
            continue
        checar_hash = pedidos is None or "hash" in pedidos
        if checar_hash and not man["qc"]["aprovado"]:
            erros.append({"manifesto": caminho.name, "erro": "manifesto publicado sem QC aprovado"})
        for arq in man["files"] if checar_hash else []:
            try:
                alvo = _caminho_seguro(destino, arq["caminho"])
            except ForgeError as exc:
                erros.append({"manifesto": caminho.name, "erro": str(exc)})
                continue
            if not alvo.is_file():
                erros.append(
                    {"manifesto": caminho.name, "erro": f"arquivo ausente: {arq['caminho']}"}
                )
                continue
            real = sha256_arquivo(alvo)
            if real != arq["sha256"]:
                erros.append(
                    {
                        "manifesto": caminho.name,
                        "erro": f"hash divergente: {arq['caminho']}",
                        "esperado": arq["sha256"],
                        "medido": real,
                    }
                )

        if pedidos is None or "manifesto" in pedidos:
            ausentes = _faltando_proveniencia(man)
            if ausentes:
                faltando.extend({"manifesto": caminho.name, "campo": c} for c in ausentes)
                erros.append(
                    {
                        "manifesto": caminho.name,
                        "erro": "proveniencia incompleta",
                        "campos": ausentes,
                    }
                )

        if pedidos is not None and not (pedidos & {"gates", "escala", "pivo"}):
            # --only sem gate: nao abre o glb nem reexecuta QC
            itens.append(
                {
                    "asset_id": man["asset_id"],
                    "schema": man["schema"],
                    "perfil": man["perfil"],
                    "escala_saida": float(
                        (man.get("unidades_export") or {}).get("escala_saida", 1.0)
                    ),
                    "triangulos": man["geometry"]["triangulos"],
                    "arquivos": len(man["files"]),
                    "licenca": man["licenca"]["modelo"],
                    "qc_reexecutado": None,
                }
            )
            continue

        # --- reexecucao dos gates contra o perfil ATUAL (C2) ---
        try:
            perfil = profiles.carregar(man["perfil"])
        except Exception as exc:  # noqa: BLE001 - perfil de terceiro nao derruba o verify
            erros.append(
                {
                    "manifesto": caminho.name,
                    "erro": f"perfil '{man.get('perfil')}' invalido: {exc}",
                }
            )
            continue

        gates_antigos = {g["id"]: g for g in man["qc"]["gates"]}
        medido_g2 = (gates_antigos.get("G2") or {}).get("medido", {})
        g9_antigo = gates_antigos.get("G9") or {}
        medido_g9 = g9_antigo.get("medido", {})
        limite_g9 = g9_antigo.get("limite") or {}
        bytes_max_kb_g9 = int(limite_g9.get("bytes_max_kb") or 0)
        # C7/GAP-037: manifesto anterior ao C2 nao tem pivo_regra e o G2 pularia o pivo
        # em silencio; ausencia de regra e reprovacao, nao perdao.
        if not medido_g2.get("pivo_regra"):
            erros.append(
                {
                    "manifesto": caminho.name,
                    "erro": "manifesto sem G2.pivo_regra (anterior ao C2): republique o asset",
                }
            )
            continue
        # D62: manifest@1 nao declara unidade — o arquivo dele esta em metros (escala 1.0).
        escala = 1.0
        if versao in ("2", "3", "4"):
            unidades = man["unidades_export"]
            escala = float(unidades["escala_saida"])
            metros = float(unidades["metros_por_unidade"])
            if abs(escala * metros - 1.0) > 1e-3:
                erros.append(
                    {
                        "manifesto": caminho.name,
                        "erro": (
                            f"unidades_export inconsistentes: escala_saida {escala} x "
                            f"metros_por_unidade {metros} != 1"
                        ),
                    }
                )
            esperada = float((perfil.get("unidades") or {}).get("escala_saida", 1.0))
            if abs(escala - esperada) > 1e-6:
                erros.append(
                    {
                        "manifesto": caminho.name,
                        "erro": (
                            f"escala_saida {escala} do manifesto difere do perfil atual "
                            f"({esperada}): republique o asset"
                        ),
                    }
                )
        qualidade_item = medido_g9.get("qualidade") or (
            "hero"
            if bytes_max_kb_g9 >= 4096 and int(perfil["validacao"]["bytes_max_kb"]) < 4096
            else None
        )
        anexo_man = man.get("anexo")
        item = {
            "id": man["asset_id"],
            "altura_metros": medido_g2.get("esperado_m"),
            # D66: os clipes declarados no manifesto sao os que o verify exige de novo no glb
            "animacoes_base": [a.get("nome") for a in man.get("animacoes") or []],
            "pivot": medido_g2.get("pivo_regra"),
            "limite_triangulos": medido_g9.get("limite"),
            "auto_rig": bool(man.get("rig")),
            "esqueleto": (man.get("rig") or {}).get("esqueleto"),
            "colisao": (man.get("colisao") or {}).get("tipo", "none"),
            "escala_preservada": bool(medido_g2.get("escala_preservada")),
            **({"anexo": anexo_man, "parte": anexo_man.get("parte")} if isinstance(anexo_man, dict) else {}),
            **({"qualidade": qualidade_item} if qualidade_item else {}),
        }
        if item["altura_metros"] is None or item["limite_triangulos"] is None:
            erros.append(
                {"manifesto": caminho.name, "erro": "manifesto sem G2/G9 para revalidar escala"}
            )
            continue

        lod = {item_lod["arquivo"]: item_lod for item_lod in man.get("lod", [])}
        arquivos = []
        for f in man["files"]:
            arq = {"caminho": f["caminho"], "papel": f["papel"]}
            if f["papel"] == "mesh":
                arq.update(nivel=0, triangulos=man["geometry"]["triangulos"])
            elif f["caminho"] in lod:
                arq.update(
                    nivel=lod[f["caminho"]]["nivel"],
                    triangulos=lod[f["caminho"]]["triangulos"],
                )
            arquivos.append(arq)

        malha = next((f for f in man["files"] if f["papel"] == "mesh"), None)
        if malha is None:
            erros.append({"manifesto": caminho.name, "erro": "manifesto sem arquivo de malha"})
            continue
        try:
            gltf, binario = qc.ler_glb_bin(destino / malha["caminho"])
            topo = qc.topologia(gltf, binario)
        except Exception as exc:  # noqa: BLE001 - GLB de terceiro pode ser ilegivel
            erros.append({"manifesto": caminho.name, "erro": f"malha ilegivel: {exc}"})
            continue

        resultado = {
            "medidas": {
                **topo,
                "partes_colisao": int((man.get("colisao") or {}).get("partes", 0)),
            },
            "arquivos": arquivos,
            "licenca": man.get("licenca") or {},
            "determinism": man.get("determinism"),
        }
        try:
            revalidado = qc.verificar(
                item,
                perfil,
                destino,
                resultado,
                escala_saida=escala,
                exigir_tangent_normal=(versao == "4"),
            )
        except Exception as exc:  # noqa: BLE001 - diagnostico vira erro do manifesto
            erros.append({"manifesto": caminho.name, "erro": f"QC reexecutado falhou: {exc}"})
            continue
        gates_revalidados = {g["id"]: g for g in revalidado["gates"]}
        medido_g2_novo = (gates_revalidados.get("G2") or {}).get("medido") or {}
        if (pedidos is None or "gates" in pedidos) and not revalidado["aprovado"]:
            falhas = [g for g in revalidado["gates"] if g["status"] == "falhou"]
            erros.append(
                {
                    "manifesto": caminho.name,
                    "erro": "QC reexecutado reprovou",
                    "gates": falhas,
                }
            )
        if pedidos is not None and (pedidos & {"escala", "pivo"}):
            g2 = gates_revalidados.get("G2") or {}
            if g2.get("status") == "falhou":
                erros.append(
                    {
                        "manifesto": caminho.name,
                        "erro": "G2 reprovou escala/pivo",
                        "gates": [g2],
                    }
                )
        if "escala" in (pedidos or set()):
            deltas_escala.append(abs(float(medido_g2_novo.get("delta_pct") or 0.0)))
        if "pivo" in (pedidos or set()):
            deltas_pivo.append(abs(float(medido_g2_novo.get("desvio_pivo_m") or 0.0)) * 1000.0)
        itens.append(
            {
                "asset_id": man["asset_id"],
                "schema": man["schema"],
                "perfil": man["perfil"],
                "escala_saida": escala,
                "triangulos": man["geometry"]["triangulos"],
                "arquivos": len(man["files"]),
                "licenca": man["licenca"]["modelo"],
                "qc_reexecutado": revalidado["aprovado"],
            }
        )

    relatorio: dict = {
        "ok": not erros,
        "destino": str(destino),
        "total": len(itens),
        "itens": itens,
        "erros": erros,
    }
    if pedidos is not None:
        if "manifesto" in pedidos:
            relatorio["faltando"] = faltando
        if "escala" in pedidos:
            relatorio["escala"] = {"delta_pct": round(max(deltas_escala or [0.0]), 3)}
        if "pivo" in pedidos:
            relatorio["pivo"] = {"delta_mm": round(max(deltas_pivo or [0.0]), 3)}
    return relatorio
