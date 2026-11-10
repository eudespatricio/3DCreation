"""Publicacao: a **unica** escrita no destino (I3), manifesto, indice e ledger.

Regras: arquivo entra por ``rename`` dentro do proprio destino (atomico no mesmo filesystem);
o manifesto e escrito por ultimo, para que sua presenca signifique "o asset esta completo".
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from . import __version__, paths
from .canonical import sha256_arquivo
from .errors import erro_manifesto

__all__ = [
    "montar_manifesto",
    "publicar",
    "salvar_cache",
    "ler_cache",
    "verificar",
    "consultar",
    "registrar_ledger",
]

MANIFEST_SCHEMA_CACHE: dict | None = None


def _agora() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _schema_manifesto() -> dict:
    global MANIFEST_SCHEMA_CACHE
    if MANIFEST_SCHEMA_CACHE is None:
        arq = paths.raiz_dados() / "schemas" / "manifest.v1.schema.json"
        MANIFEST_SCHEMA_CACHE = json.loads(arq.read_text(encoding="utf-8"))
    return MANIFEST_SCHEMA_CACHE


def montar_manifesto(
    *,
    item: dict,
    spec_doc: dict,
    spec_hash: str,
    perfil_nome: str,
    provider: dict,
    resultado: dict,
    relatorio_qc: dict,
    licenca: dict,
    run_id: str,
    created_at: str | None = None,
) -> dict:
    arquivos = []
    for arq in resultado.get("arquivos", []):
        arquivos.append(
            {
                "caminho": arq["caminho"],
                "papel": arq["papel"],
                "sha256": arq["sha256"],
                "bytes": arq["bytes"],
            }
        )
    medidas = relatorio_qc["medidas"]
    lods = [
        {"nivel": a["nivel"], "triangulos": a["triangulos"], "arquivo": a["caminho"]}
        for a in resultado.get("arquivos", [])
        if a["papel"] in ("mesh", "lod")
    ]
    colisao = next((a for a in resultado.get("arquivos", []) if a["papel"] == "colisor"), None)

    rig = None
    if item.get("auto_rig") and medidas.get("ossos"):
        rig = {"esqueleto": item.get("esqueleto") or "", "ossos": int(medidas["ossos"])}

    return {
        "schema": "forge3d/manifest@1",
        "asset_id": item["id"],
        "projeto": spec_doc["projeto"],
        "perfil": perfil_nome,
        "rota": item["rota"],
        "tags": list(item.get("tags") or []),
        "spec_hash": spec_hash,
        "pipeline_version": __version__,
        "determinism": resultado.get("determinism", provider["determinism"]),
        "providers": {
            "geometry": {
                "name": provider["nome"],
                "version": provider["versao"],
                "license": licenca["modelo"],
                **({"seed": int(item["seed"])} if "seed" in item else {}),
            }
        },
        "geometry": {
            "triangulos": int(medidas["triangulos"]),
            "vertices": int(medidas["vertices"]),
            "bbox_m": [max(0.0001, float(v)) for v in medidas["bbox_m"]],
            "materiais": max(1, int(medidas["materiais"])),
        },
        "rig": rig,
        "lod": lods,
        "colisao": {
            "tipo": item.get("colisao", "none"),
            "partes": int(medidas.get("partes_colisao", 0)),
            **({"arquivo": colisao["caminho"]} if colisao else {}),
        },
        "files": arquivos,
        "qc": {"aprovado": bool(relatorio_qc["aprovado"]), "gates": relatorio_qc["gates"]},
        "licenca": {
            "modelo": licenca["modelo"],
            "uso_comercial": bool(licenca["uso_comercial"]),
            "notice": licenca["notice"],
        },
        "origem_spec": {"arquivo": spec_doc.get("_arquivo", "?"), "hash": spec_hash},
        "run_id": run_id,
        "created_at": created_at or _agora(),
    }


# ---------------------------------------------------------------- cache


def _dir_cache(chave: str) -> Path:
    return paths.dir_cache() / chave


def salvar_cache(chave: str, origem: Path, entrada: dict) -> None:
    base = _dir_cache(chave)
    final = base / "final"
    if final.exists():
        shutil.rmtree(final)
    final.mkdir(parents=True, exist_ok=True)
    for arq in entrada["resultado"].get("arquivos", []):
        shutil.copyfile(origem / arq["caminho"], final / arq["caminho"])
    tmp = base / "entrada.json.tmp"
    tmp.write_text(json.dumps(entrada, sort_keys=True, indent=1), encoding="utf-8")
    os.replace(tmp, base / "entrada.json")


def ler_cache(chave: str) -> tuple[Path, dict] | None:
    base = _dir_cache(chave)
    entrada = base / "entrada.json"
    final = base / "final"
    if not entrada.is_file() or not final.is_dir():
        return None
    try:
        dados = json.loads(entrada.read_text(encoding="utf-8"))
    except ValueError:
        return None
    for arq in dados.get("resultado", {}).get("arquivos", []):
        if not (final / arq["caminho"]).is_file():
            return None
    return final, dados


# ---------------------------------------------------------------- publicacao


def publicar(origem: Path, destino: Path, manifesto: dict, run_id: str) -> list[dict]:
    """Copia staging->destino por rename, depois grava o manifesto. Devolve artefatos."""
    destino.mkdir(parents=True, exist_ok=True)
    publicados = []
    for arq in manifesto["files"]:
        nome = arq["caminho"]
        origem_arq = origem / nome
        if not origem_arq.is_file():
            raise erro_manifesto(f"arquivo ausente no staging: {nome}", arquivo=nome)
        tmp = destino / f".{nome}.{run_id}.tmp"
        with open(origem_arq, "rb") as fent, open(tmp, "wb") as fsai:
            shutil.copyfileobj(fent, fsai)
            fsai.flush()
            os.fsync(fsai.fileno())
        os.replace(tmp, destino / nome)
        publicados.append(
            {"id": manifesto["asset_id"], "caminho": nome, "sha256": arq["sha256"]}
        )

    nome_manifesto = f"{manifesto['asset_id']}.manifest.json"
    tmp = destino / f".{nome_manifesto}.{run_id}.tmp"
    tmp.write_text(
        json.dumps(manifesto, sort_keys=True, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    os.replace(tmp, destino / nome_manifesto)

    _indice_upsert(manifesto, destino)
    return publicados


def _conexao() -> sqlite3.Connection:
    paths.raiz_estado().mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(paths.arquivo_indice())
    con.execute("PRAGMA journal_mode=WAL")
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS assets (
            asset_id TEXT PRIMARY KEY, projeto TEXT, perfil TEXT, rota TEXT, determinism TEXT,
            triangulos INTEGER, bytes INTEGER, materiais INTEGER, ossos INTEGER,
            licenca TEXT, spec_hash TEXT, pipeline_version TEXT, destino TEXT,
            publicado_em TEXT, tags TEXT
        )
        """
    )
    return con


def _indice_upsert(manifesto: dict, destino: Path) -> None:
    total = sum(a["bytes"] for a in manifesto["files"])
    tags = " ".join(manifesto.get("tags") or [])
    con = _conexao()
    with con:
        con.execute(
            """
            INSERT INTO assets (asset_id, projeto, perfil, rota, determinism, triangulos, bytes,
                                materiais, ossos, licenca, spec_hash, pipeline_version, destino,
                                publicado_em, tags)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(asset_id) DO UPDATE SET
                projeto=excluded.projeto, perfil=excluded.perfil, rota=excluded.rota,
                determinism=excluded.determinism, triangulos=excluded.triangulos,
                bytes=excluded.bytes, materiais=excluded.materiais, ossos=excluded.ossos,
                licenca=excluded.licenca, spec_hash=excluded.spec_hash,
                pipeline_version=excluded.pipeline_version, destino=excluded.destino,
                publicado_em=excluded.publicado_em, tags=excluded.tags
            """,
            (
                manifesto["asset_id"],
                manifesto["projeto"],
                manifesto["perfil"],
                manifesto.get("rota", ""),
                manifesto["determinism"],
                manifesto["geometry"]["triangulos"],
                total,
                manifesto["geometry"]["materiais"],
                (manifesto.get("rig") or {}).get("ossos", 0),
                manifesto["licenca"]["modelo"],
                manifesto["spec_hash"],
                manifesto["pipeline_version"],
                str(destino),
                manifesto["created_at"],
                tags,
            ),
        )
    con.close()


def consultar(
    projeto: str | None = None,
    max_tris: int | None = None,
    perfil: str | None = None,
    tag: str | None = None,
) -> list[dict]:
    con = _conexao()
    sql = "SELECT asset_id, projeto, perfil, rota, determinism, triangulos, bytes, materiais, ossos, licenca, destino, publicado_em FROM assets WHERE 1=1"
    args: list = []
    if projeto:
        sql += " AND projeto = ?"
        args.append(projeto)
    if perfil:
        sql += " AND perfil = ?"
        args.append(perfil)
    if max_tris:
        sql += " AND triangulos <= ?"
        args.append(max_tris)
    if tag:
        sql += " AND tags LIKE ?"
        args.append(f"%{tag}%")
    sql += " ORDER BY asset_id"
    linhas = con.execute(sql, args).fetchall()
    con.close()
    colunas = [
        "asset_id",
        "projeto",
        "perfil",
        "rota",
        "determinism",
        "triangulos",
        "bytes",
        "materiais",
        "ossos",
        "licenca",
        "destino",
        "publicado_em",
    ]
    return [dict(zip(colunas, linha)) for linha in linhas]


def registrar_ledger(evento: dict) -> None:
    caminho = paths.arquivo_ledger()
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with open(caminho, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": _agora(), **evento}, sort_keys=True, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- verificacao


def verificar(destino: Path) -> dict:
    """Portao de CI: manifesto+hash E reexecucao de G1-G9 contra o perfil atual.

    O hash pega arquivo trocado; a reexecucao pega o caso mais sutil: o perfil do jogo mudou
    (tolerancia, textura_max, mapa de ossos) e o manifesto antigo ficou mentindo.
    """
    import jsonschema

    from . import profiles, qc

    if not destino.is_dir():
        raise erro_manifesto(f"destino inexistente: {destino}", destino=str(destino))

    validador = jsonschema.Draft202012Validator(_schema_manifesto())
    manifestos = sorted(destino.glob("*.manifest.json"))
    if not manifestos:
        raise erro_manifesto(f"nenhum manifesto em {destino}", destino=str(destino))

    itens = []
    erros: list[dict] = []
    for caminho in manifestos:
        try:
            man = json.loads(caminho.read_text(encoding="utf-8"))
        except ValueError as exc:
            erros.append({"manifesto": caminho.name, "erro": f"json invalido: {exc}"})
            continue
        problemas = [e.message for e in validador.iter_errors(man)][:5]
        if problemas:
            erros.append({"manifesto": caminho.name, "erro": "schema", "detalhes": problemas})
            continue
        if not man["qc"]["aprovado"]:
            erros.append({"manifesto": caminho.name, "erro": "manifesto publicado sem QC aprovado"})
        for arq in man["files"]:
            alvo = destino / arq["caminho"]
            if not alvo.is_file():
                erros.append({"manifesto": caminho.name, "erro": f"arquivo ausente: {arq['caminho']}"})
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

        # --- reexecucao dos gates contra o perfil ATUAL (C2) ---
        try:
            perfil = profiles.carregar(man["perfil"])
        except Exception as exc:  # noqa: BLE001 - perfil de terceiro nao derruba o verify
            erros.append(
                {"manifesto": caminho.name, "erro": f"perfil '{man.get('perfil')}' invalido: {exc}"}
            )
            continue

        gates_antigos = {g["id"]: g for g in man["qc"]["gates"]}
        medido_g2 = (gates_antigos.get("G2") or {}).get("medido", {})
        medido_g9 = (gates_antigos.get("G9") or {}).get("medido", {})
        item = {
            "id": man["asset_id"],
            "altura_metros": medido_g2.get("esperado_m"),
            "pivot": medido_g2.get("pivo_regra"),
            "limite_triangulos": medido_g9.get("limite"),
            "auto_rig": bool(man.get("rig")),
            "esqueleto": (man.get("rig") or {}).get("esqueleto"),
            "colisao": (man.get("colisao") or {}).get("tipo", "none"),
        }
        if item["altura_metros"] is None or item["limite_triangulos"] is None:
            erros.append(
                {"manifesto": caminho.name, "erro": "manifesto sem G2/G9 para revalidar escala"}
            )
            continue

        lod = {l["arquivo"]: l for l in man.get("lod", [])}
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
            revalidado = qc.verificar(item, perfil, destino, resultado)
        except Exception as exc:  # noqa: BLE001 - diagnostico vira erro do manifesto
            erros.append({"manifesto": caminho.name, "erro": f"QC reexecutado falhou: {exc}"})
            continue
        if not revalidado["aprovado"]:
            falhas = [g for g in revalidado["gates"] if g["status"] == "falhou"]
            erros.append(
                {
                    "manifesto": caminho.name,
                    "erro": "QC reexecutado reprovou",
                    "gates": falhas,
                }
            )
        itens.append(
            {
                "asset_id": man["asset_id"],
                "perfil": man["perfil"],
                "triangulos": man["geometry"]["triangulos"],
                "arquivos": len(man["files"]),
                "licenca": man["licenca"]["modelo"],
                "qc_reexecutado": revalidado["aprovado"],
            }
        )

    return {"ok": not erros, "destino": str(destino), "total": len(itens), "itens": itens, "erros": erros}
