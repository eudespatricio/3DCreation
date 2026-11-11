"""Publicacao: a **unica** escrita no destino (I3), manifesto, indice e ledger.

Regras: arquivo entra por ``rename`` dentro do proprio destino (atomico no mesmo filesystem);
o manifesto e escrito por ultimo, para que sua presenca signifique "o asset esta completo".
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path

from . import __version__, locks
from .cache import _dir_cache, ler_cache, salvar_cache  # noqa: F401
from .errors import erro_manifesto
from .index import _conexao, _indice_upsert, consultar, registrar_ledger  # noqa: F401
from .verify import (  # noqa: F401
    _VERSAO_POR_SCHEMA,
    CAMPOS_PROVENIENCIA,
    MANIFEST_SCHEMA_CACHE,
    VERIFY_ASPECTOS,
    _faltando_proveniencia,
    _pedidos_verificar,
    _schema_manifesto,
    verificar,
)

__all__ = [
    "consultar",
    "ler_cache",
    "montar_manifesto",
    "publicar",
    "registrar_ledger",
    "salvar_cache",
    "verificar",
]


def _agora() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _unidades_export(perfil: dict, medidas: dict) -> dict:
    """Unidade do arquivo exportado (D62): fator efetivo do QC + unidade declarada no perfil."""
    unidades = perfil.get("unidades") or {}
    escala = float(medidas.get("escala_saida") or unidades.get("escala_saida", 1.0))
    metros = float(unidades.get("metros_por_unidade", 1.0 / escala))
    return {"metros_por_unidade": metros, "escala_saida": escala}


def montar_manifesto(
    *,
    item: dict,
    spec_doc: dict,
    spec_hash: str,
    perfil_nome: str,
    perfil: dict | None = None,
    provider: dict,
    resultado: dict,
    relatorio_qc: dict,
    licenca: dict,
    run_id: str,
    created_at: str | None = None,
) -> dict:
    """Monta o dicionario canonico de manifesto@3 a partir de item, resultado e QC."""
    arquivos = [
        {
            "caminho": arq["caminho"],
            "papel": arq["papel"],
            "sha256": arq["sha256"],
            "bytes": arq["bytes"],
        }
        for arq in resultado.get("arquivos", [])
    ]
    medidas = relatorio_qc["medidas"]
    unidades_export = _unidades_export(perfil or {}, medidas)
    lods = [
        {"nivel": a["nivel"], "triangulos": a["triangulos"], "arquivo": a["caminho"]}
        for a in resultado.get("arquivos", [])
        if a["papel"] in ("mesh", "lod")
    ]
    colisao = next((a for a in resultado.get("arquivos", []) if a["papel"] == "colisor"), None)

    providers = {
        "geometry": {
            "name": provider["nome"],
            "version": provider["versao"],
            "license": licenca["modelo"],
            **({"seed": int(item["seed"])} if "seed" in item else {}),
        }
    }
    licenca_manifesto = {
        "modelo": licenca["modelo"],
        "uso_comercial": bool(licenca["uso_comercial"]),
        "notice": licenca["notice"],
    }
    concept = resultado.get("concept")
    if concept:
        c_lic = concept.get("licenca") or {}
        versao_concept = str(concept.get("versao", "0.1.0"))
        revisao = str(concept.get("revisao", "") or "")
        if revisao:
            versao_concept = f"{versao_concept}+{revisao[:12]}"
        detalhe = "{w}x{h}s{passos}g{guidance}".format(
            w=concept.get("largura", "?"),
            h=concept.get("altura", "?"),
            passos=concept.get("passos", "?"),
            guidance=concept.get("guidance", "?"),
        )
        versao_concept = f"{versao_concept}+{detalhe}"
        if concept.get("device"):
            dev = str(concept["device"]).replace(":", "").replace("/", "_")
            versao_concept = f"{versao_concept}+{dev}"
        nome_modelo = str(concept.get("modelo", "sd15")).rstrip("/").split("/")[-1]
        providers["texture"] = {
            "name": f"concept/{nome_modelo}",
            "version": versao_concept,
            "license": str(c_lic.get("modelo", "Stable Diffusion 1.5")),
            "seed": int(concept.get("seed", item.get("seed", 0))),
        }
        if c_lic.get("notice"):
            licenca_manifesto["notice"] = (
                licenca_manifesto["notice"].rstrip() + " Concept: " + c_lic["notice"]
            ).strip()

    rig = None
    if item.get("auto_rig") and medidas.get("ossos"):
        rig = {"esqueleto": item.get("esqueleto") or "", "ossos": int(medidas["ossos"])}

    return {
        "schema": "forge3d/manifest@3",
        "asset_id": item["id"],
        "projeto": spec_doc["projeto"],
        "perfil": perfil_nome,
        "rota": item["rota"],
        "tags": list(item.get("tags") or []),
        "spec_hash": spec_hash,
        "pipeline_version": __version__,
        "determinism": resultado.get("determinism", provider["determinism"]),
        "providers": providers,
        "geometry": {
            "triangulos": int(medidas["triangulos"]),
            "vertices": int(medidas["vertices"]),
            "bbox_m": [max(0.0001, float(v)) for v in medidas["bbox_m"]],
            "materiais": max(1, int(medidas["materiais"])),
        },
        # D62: o glb do roblox-r15 sai em studs; quem consome le a unidade aqui, nunca supoe metro
        "unidades_export": unidades_export,
        # D66: clipes embutidos no glb (nome, duracao, ossos animados)
        "animacoes": [
            {
                "nome": str(c["nome"]),
                "duracao_s": float(c["duracao_s"]),
                "ossos": [str(o) for o in c.get("ossos") or []],
            }
            for c in medidas.get("animacoes") or []
        ],
        "rig": rig,
        "lod": lods,
        "colisao": {
            "tipo": item.get("colisao", "none"),
            "partes": int(medidas.get("partes_colisao", 0)),
            **({"arquivo": colisao["caminho"]} if colisao else {}),
        },
        "files": arquivos,
        "qc": {"aprovado": bool(relatorio_qc["aprovado"]), "gates": relatorio_qc["gates"]},
        "licenca": licenca_manifesto,
        "origem_spec": {"arquivo": spec_doc.get("_arquivo", "?"), "hash": spec_hash},
        "run_id": run_id,
        "created_at": created_at or _agora(),
    }


def _caminho_seguro(raiz: Path, nome: str) -> Path:
    """Resolve ``nome`` dentro de ``raiz`` e recusa traversal / caminho absoluto."""
    bruto = str(nome or "")
    if not bruto or "\\" in bruto:
        raise erro_manifesto(f"caminho invalido no manifesto: {nome!r}", arquivo=bruto)
    rel = Path(bruto)
    if rel.is_absolute() or ".." in rel.parts:
        raise erro_manifesto(f"caminho fora do destino: {nome!r}", arquivo=bruto)
    raiz_res = raiz.resolve(strict=False)
    alvo = (raiz_res / rel).resolve(strict=False)
    if not alvo.is_relative_to(raiz_res) or alvo == raiz_res:
        raise erro_manifesto(f"caminho fora do destino: {nome!r}", arquivo=bruto)
    return alvo


def _fsync_dir(pasta: Path) -> None:
    try:
        fd = os.open(pasta, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _coletar_orfaos(destino: Path, manifesto: dict) -> list[Path]:
    """Identifica arquivos do manifesto ANTERIOR ausentes no novo, garantindo escopo no destino."""
    anterior = destino / f"{manifesto['asset_id']}.manifest.json"
    if not anterior.is_file():
        return []
    try:
        antigo = json.loads(anterior.read_text(encoding="utf-8"))
    except ValueError:
        return []
    novos = {a["caminho"] for a in manifesto.get("files", [])}
    orfaos: list[Path] = []
    for arq in antigo.get("files", []):
        nome = arq.get("caminho", "")
        if nome and nome not in novos:
            orfaos.append(_caminho_seguro(destino, nome))
    return orfaos


def _escrever_texto_atomico(alvo: Path, tmp: Path, conteudo: str) -> None:
    try:
        with open(tmp, "w", encoding="utf-8") as fsai:
            fsai.write(conteudo)
            fsai.flush()
            os.fsync(fsai.fileno())
        os.replace(tmp, alvo)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def publicar(origem: Path, destino: Path, manifesto: dict, run_id: str) -> list[dict]:
    """Copia staging->destino por rename, grava manifesto com fsync e remove orfaos por ultimo."""
    with locks.lock_destino(destino, run_id):
        destino.mkdir(parents=True, exist_ok=True)
        orfaos = _coletar_orfaos(destino, manifesto)
        publicados = []
        for arq in manifesto["files"]:
            nome = arq["caminho"]
            origem_arq = _caminho_seguro(origem, nome)
            alvo = _caminho_seguro(destino, nome)
            if not origem_arq.is_file():
                raise erro_manifesto(f"arquivo ausente no staging: {nome}", arquivo=nome)
            alvo.parent.mkdir(parents=True, exist_ok=True)
            tmp = alvo.parent / f".{alvo.name}.{run_id}.tmp"
            try:
                with open(origem_arq, "rb") as fent, open(tmp, "wb") as fsai:
                    shutil.copyfileobj(fent, fsai)
                    fsai.flush()
                    os.fsync(fsai.fileno())
                os.replace(tmp, alvo)
            except BaseException:
                tmp.unlink(missing_ok=True)
                raise
            publicados.append(
                {"id": manifesto["asset_id"], "caminho": nome, "sha256": arq["sha256"]}
            )

        nome_manifesto = f"{manifesto['asset_id']}.manifest.json"
        alvo_manifesto = _caminho_seguro(destino, nome_manifesto)
        tmp_manifesto = destino / f".{nome_manifesto}.{run_id}.tmp"
        _escrever_texto_atomico(
            alvo_manifesto,
            tmp_manifesto,
            json.dumps(manifesto, sort_keys=True, indent=1, ensure_ascii=False) + "\n",
        )

        for orfao in orfaos:
            if orfao.is_file():
                orfao.unlink()
        _fsync_dir(destino)
        _indice_upsert(manifesto, destino)
        return publicados
