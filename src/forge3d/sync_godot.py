"""Sidecars ``.import`` e geracao de ``Forge3DAssets.gd`` para Godot 4."""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .errors import erro_spec
from .sync_common import (
    _IDENTIFICADOR_LUAU,
    _checar_destino_externo,
    _escapar_literal,
    _escrever_atomico,
)
from .sync_godot_sidecars import (
    _atualizar_import_sidecar_glb,
    _atualizar_import_sidecar_png,
    aplicar_sidecars_godot,
)

__all__ = [
    "_atualizar_import_sidecar_glb",
    "_atualizar_import_sidecar_png",
    "_eh_metadado_godot",
    "aplicar_sidecars_godot",
    "detectar_raiz_godot",
    "gerar_assets_gd",
]


def _eh_metadado_godot(rel_path: Path) -> bool:
    """Identifica metadados gerenciados pelo editor Godot (.import, .uid, .godot/)."""
    if ".godot" in rel_path.parts:
        return True
    return rel_path.suffix.lower() in (".import", ".uid")


def detectar_raiz_godot(alvo: Path) -> Path | None:
    alvo_abs = alvo.resolve(strict=False)
    for cand in (alvo_abs, *alvo_abs.parents):
        if (cand / "project.godot").is_file() or (
            cand / "addons" / "forge3d" / "post_import.gd"
        ).is_file():
            return cand
    return None


def _prefixar_caminho_gd(caminho: str, res_prefix: str) -> str:
    limpo = caminho.strip().lstrip("/")
    pref = (res_prefix or "").strip().rstrip("/")
    if not pref or not limpo:
        return limpo
    return f"{pref}/{limpo}"


def _formatar_gdscript(valor: object, nivel: int = 0) -> str:
    if valor is None:
        return "null"
    if isinstance(valor, bool):
        return "true" if valor else "false"
    if isinstance(valor, (int, float)):
        return json.dumps(valor)
    if isinstance(valor, str):
        return f'"{_escapar_literal(valor)}"'
    if isinstance(valor, (list, tuple)):
        if not valor:
            return "[]"
        tab = "\t" * (nivel + 1)
        tab_fim = "\t" * nivel
        itens = ",\n".join(f"{tab}{_formatar_gdscript(v, nivel + 1)}" for v in valor)
        return f"[\n{itens},\n{tab_fim}]"
    if isinstance(valor, dict):
        if not valor:
            return "{}"
        tab = "\t" * (nivel + 1)
        tab_fim = "\t" * nivel
        itens = ",\n".join(
            f'{tab}"{_escapar_literal(str(k))}": {_formatar_gdscript(valor[k], nivel + 1)}'
            for k in sorted(valor, key=str)
        )
        return f"{{\n{itens},\n{tab_fim}}}"
    return f'"{_escapar_literal(str(valor))}"'


def _extrair_entrada_gd(rec: dict, res_prefix: str, manifest_rel: str | None = None) -> tuple[str, dict] | None:
    if not isinstance(rec, dict) or rec.get("evento") == "run":
        return None
    asset_id = str(rec.get("asset_id") or rec.get("id") or "").strip()
    if not asset_id:
        return None

    raw_files = rec.get("files")
    arquivos: list[Any] = raw_files if isinstance(raw_files, list) else []
    mesh_rel = ""
    textures: dict[str, str] = {}
    colisor_rel = ""
    for item in arquivos:
        if not isinstance(item, dict):
            continue
        caminho = str(item.get("caminho") or "").strip()
        papel = str(item.get("papel") or "").strip().lower()
        if not caminho:
            continue
        nome_arq = Path(caminho.replace("\\", "/")).name.lower()
        eh_emissive = (
            papel == "emissive"
            or nome_arq == "emissive.png"
            or nome_arq.endswith("_emissive.png")
        )
        if papel == "mesh" and not mesh_rel:
            mesh_rel = caminho
        elif eh_emissive:
            if "emissive" not in textures:
                textures["emissive"] = _prefixar_caminho_gd(caminho, res_prefix)
        elif papel == "textura" and "baseColor" not in textures:
            textures["baseColor"] = _prefixar_caminho_gd(caminho, res_prefix)
        elif papel == "normal" and "normal" not in textures:
            textures["normal"] = _prefixar_caminho_gd(caminho, res_prefix)
        elif papel == "orm" and "orm" not in textures:
            textures["orm"] = _prefixar_caminho_gd(caminho, res_prefix)
        elif papel == "roughness" and "roughness" not in textures:
            textures["roughness"] = _prefixar_caminho_gd(caminho, res_prefix)
        elif papel in ("metallic", "metalness") and "metalness" not in textures:
            textures["metalness"] = _prefixar_caminho_gd(caminho, res_prefix)
        elif papel == "colisor" and not colisor_rel:
            colisor_rel = caminho

    raw_lod = rec.get("lod")
    lods_raw: list[Any] = raw_lod if isinstance(raw_lod, list) else []
    lods: list[str] = []
    for lod_item in lods_raw:
        if isinstance(lod_item, dict) and lod_item.get("arquivo"):
            arq_lod = str(lod_item["arquivo"]).strip()
            if arq_lod:
                nivel_lod = int(lod_item.get("nivel", 0))
                if not mesh_rel and nivel_lod == 0:
                    mesh_rel = arq_lod
                elif nivel_lod >= 1:
                    lods.append(_prefixar_caminho_gd(arq_lod, res_prefix))
    if not mesh_rel:
        mesh_rel = f"{asset_id}.glb"

    raw_col = rec.get("colisao")
    col_info: dict[str, Any] = raw_col if isinstance(raw_col, dict) else {}
    if not colisor_rel and col_info.get("arquivo"):
        colisor_rel = str(col_info["arquivo"]).strip()

    entrada: dict[str, object] = {
        "asset_id": asset_id,
        "mesh": _prefixar_caminho_gd(mesh_rel, res_prefix),
        "manifest": _prefixar_caminho_gd(manifest_rel or f"{asset_id}.manifest.json", res_prefix),
        "perfil": str(rec.get("perfil") or ""),
        "lod": lods,
        "textures": {k: textures[k] for k in sorted(textures)},
        "rig": rec.get("rig"),
    }
    if colisor_rel:
        entrada["colisor"] = _prefixar_caminho_gd(colisor_rel, res_prefix)
    if rec.get("anexo") is not None:
        entrada["anexo"] = rec["anexo"]
    return asset_id, entrada


def _ler_fonte_gd(fonte: str | os.PathLike | dict, mapa: dict[str, dict], res_prefix: str) -> None:
    if isinstance(fonte, dict):
        par = _extrair_entrada_gd(fonte, res_prefix)
        if par is not None:
            mapa[par[0]] = par[1]
        return

    caminho = Path(fonte).expanduser()
    if not caminho.exists():
        return
    if caminho.is_dir():
        for arq in sorted(caminho.glob("*.manifest.json")):
            try:
                dados = json.loads(arq.read_text(encoding="utf-8"))
            except ValueError:
                continue
            par = _extrair_entrada_gd(dados, res_prefix, manifest_rel=arq.name)
            if par is not None:
                mapa[par[0]] = par[1]
        return

    if caminho.is_file():
        try:
            dados = json.loads(caminho.read_text(encoding="utf-8"))
        except ValueError:
            return
        if isinstance(dados, list):
            for item in dados:
                par = _extrair_entrada_gd(item, res_prefix)
                if par is not None:
                    mapa[par[0]] = par[1]
        elif isinstance(dados, dict):
            par = _extrair_entrada_gd(dados, res_prefix, manifest_rel=caminho.name)
            if par is not None:
                mapa[par[0]] = par[1]


def gerar_assets_gd(
    fontes_ou_manifestos: str | os.PathLike | dict | Iterable[str | os.PathLike | dict] | None,
    destino_gd: str | os.PathLike,
    class_name: str = "Forge3DAssets",
    res_prefix: str = "",
) -> dict:
    """Gera registro GDScript tipado deterministico (``asset_id -> metadados/caminhos``)."""
    if class_name and not _IDENTIFICADOR_LUAU.match(class_name):
        raise erro_spec(f"class_name GDScript invalido: {class_name!r}", class_name=class_name)

    destino = _checar_destino_externo(destino_gd, campo="godot_gd")
    if fontes_ou_manifestos is None:
        fontes: list[str | os.PathLike | dict] = []
    elif isinstance(fontes_ou_manifestos, (str, os.PathLike, dict)):
        fontes = [fontes_ou_manifestos]
    else:
        fontes = list(fontes_ou_manifestos)

    mapa: dict[str, dict] = {}
    for fonte in fontes:
        _ler_fonte_gd(fonte, mapa, res_prefix)

    ordenado = {k: mapa[k] for k in sorted(mapa)}
    dicionario_gd = _formatar_gdscript(ordenado, nivel=0)
    linhas = [
        "# Gerado automaticamente pelo Forge3D. Nao editar manualmente.",
    ]
    if class_name:
        linhas.append(f"class_name {class_name}")
    linhas.extend(
        [
            "extends RefCounted",
            "",
            f"const ASSETS: Dictionary = {dicionario_gd}",
            "",
            "",
            "static func has_asset(asset_id: String) -> bool:",
            "\treturn ASSETS.has(asset_id)",
            "",
            "",
            "static func get_asset(asset_id: String) -> Dictionary:",
            "\tvar entry: Variant = ASSETS.get(asset_id, {})",
            "\tif typeof(entry) == TYPE_DICTIONARY:",
            "\t\treturn entry as Dictionary",
            "\treturn {}",
            "",
            "",
            "static func get_mesh_path(asset_id: String) -> String:",
            "\tvar entry := get_asset(asset_id)",
            '\treturn str(entry.get("mesh", ""))',
            "",
            "",
            "static func list_ids() -> Array[String]:",
            "\tvar ids: Array[String] = []",
            "\tfor k in ASSETS.keys():",
            "\t\tids.append(str(k))",
            "\treturn ids",
            "",
        ]
    )
    _escrever_atomico(destino, "\n".join(linhas), f"godot-{os.getpid()}")
    return {
        "ok": True,
        "saida": str(destino),
        "class_name": class_name or "",
        "total": len(ordenado),
        "assets": ordenado,
    }
