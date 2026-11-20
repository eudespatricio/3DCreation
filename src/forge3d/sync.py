"""Sincronizacao explicita pos-verify entre ext4 (I12) e pastas externas (ex.: /mnt/<letra>/).

O pipeline (`plan`/`run`/`allowlist`) continua restrito a ext4 sob /home. Este modulo e a
ponte controlada de saida: so copia de um destino ext4 depois de `publish.verificar()` aprovar
todos os manifestos, hashes e gates G1-G10. Tambem gera ``Assets.lua`` (Rojo) e ``Forge3DAssets.gd``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from . import config, paths, publish
from .errors import erro_destino, erro_manifesto, erro_qc
from .sync_common import (
    _checar_destino_externo,
    _copiar_atomico,
    _sobrepoe,
    _validar_alvo,
)
from .sync_godot import (
    _atualizar_import_sidecar_glb,
    _eh_metadado_godot,
    aplicar_sidecars_godot,
    detectar_raiz_godot,
    gerar_assets_gd,
)
from .sync_rojo import gerar_assets_lua

__all__ = ["executar", "gerar_assets_gd", "gerar_assets_lua"]

# Re-exports internos mantidos para testes de contrato e M3.
_COMPAT_INTERNOS = (_atualizar_import_sidecar_glb, _validar_alvo)


def executar(
    origem_raw: str | os.PathLike,
    para_raw: str | os.PathLike,
    *,
    limpar: bool = False,
    rojo_lua: str | os.PathLike | None = None,
    namespace: str = "Assets",
    godot_gd: str | os.PathLike | None = None,
    gd_class_name: str = "Forge3DAssets",
    res_prefix: str = "",
) -> dict:
    """Verifica ``origem`` e copia apenas artefatos publicados + manifestos para ``para``."""
    origem = config.normalizar(origem_raw)
    config.validar_caminho(origem, campo="origem")

    verificacao = publish.verificar(origem)
    if not verificacao["ok"]:
        erros = verificacao.get("erros") or []
        eh_qc = any("gates" in e or "QC" in str(e.get("erro", "")) for e in erros)
        fabrica = erro_qc if eh_qc else erro_manifesto
        raise fabrica(
            f"sync recusado: verify falhou em {origem} ({len(erros)} problema(s))",
            origem=str(origem),
            erros=erros,
        )

    alvo = _validar_alvo(para_raw, origem)
    destino_lua_res: Path | None = None
    if rojo_lua is not None:
        destino_lua_res = _checar_destino_externo(rojo_lua, campo="rojo_lua")
        if _sobrepoe(destino_lua_res, origem):
            raise erro_destino(
                f"destino --rojo-lua ({destino_lua_res}) nao pode sobrepor a origem ({origem})",
                origem=str(origem),
                destino=str(destino_lua_res),
            )

    alvo_abs = alvo.resolve(strict=False)
    raiz_godot = detectar_raiz_godot(alvo_abs)

    destino_gd_res: Path | None = None
    if godot_gd is not None:
        destino_gd_res = _checar_destino_externo(godot_gd, campo="godot_gd")
        if _sobrepoe(destino_gd_res, origem):
            raise erro_destino(
                f"destino godot_gd ({destino_gd_res}) nao pode sobrepor a origem ({origem})",
                origem=str(origem),
                destino=str(destino_gd_res),
            )
    elif raiz_godot is not None:
        destino_gd_res = _checar_destino_externo(alvo / "forge3d_assets.gd", campo="godot_gd")

    if not res_prefix and raiz_godot is not None:
        rel_sub = alvo_abs.relative_to(raiz_godot).as_posix()
        res_prefix = "res://" if rel_sub in ("", ".") else f"res://{rel_sub}"

    manifestos = sorted(origem.glob("*.manifest.json"))
    pares_arquivos: list[tuple[Path, Path, str]] = []
    pares_manifestos: list[tuple[Path, Path, str]] = []
    esperados: set[str] = set()
    asset_ids_origem: set[str] = set()
    projetos_origem: set[str] = set()
    man_por_arquivo: dict[str, dict[str, Any]] = {}

    for caminho_man in manifestos:
        man = json.loads(caminho_man.read_text(encoding="utf-8"))
        if isinstance(man, dict):
            aid = str(man.get("asset_id") or man.get("id") or "").strip()
            if aid:
                asset_ids_origem.add(aid)
            proj = str(man.get("projeto") or "").strip()
            if proj:
                projetos_origem.add(proj)
        for arq in man.get("files", []):
            rel = str(arq["caminho"])
            src_arq = publish._caminho_seguro(origem, rel)
            dst_arq = publish._caminho_seguro(alvo, rel)
            if rel not in esperados:
                esperados.add(rel)
                pares_arquivos.append((src_arq, dst_arq, rel))
                if isinstance(man, dict):
                    man_por_arquivo[rel] = man
        rel_man = caminho_man.name
        dst_man = publish._caminho_seguro(alvo, rel_man)
        if rel_man not in esperados:
            esperados.add(rel_man)
            pares_manifestos.append((caminho_man, dst_man, rel_man))

    alvo.mkdir(parents=True, exist_ok=True)
    tag = f"sync-{os.getpid()}"
    copiados: list[str] = []
    total_bytes = 0

    is_godot = raiz_godot is not None or destino_gd_res is not None
    sidecars_godot: list[Path] = []
    for src, dst, rel in pares_arquivos:
        total_bytes += _copiar_atomico(src, dst, tag)
        copiados.append(rel)
        if is_godot:
            sidecars_godot.extend(
                aplicar_sidecars_godot(dst, tag, manifesto=man_por_arquivo.get(rel))
            )
    for src, dst, rel in pares_manifestos:
        total_bytes += _copiar_atomico(src, dst, tag)
        copiados.append(rel)

    removidos: list[str] = []
    if limpar:
        alvo_res = alvo.resolve(strict=False)
        esperados_res = {publish._caminho_seguro(alvo, rel) for rel in esperados}
        esperados_res.update(sidecars_godot)
        if destino_lua_res is not None:
            esperados_res.add(destino_lua_res)
        if destino_gd_res is not None:
            esperados_res.add(destino_gd_res)
        proj_godot = (alvo / "project.godot").resolve(strict=False)
        if proj_godot.is_file():
            esperados_res.add(proj_godot)
        for item in sorted(alvo.rglob("*"), key=lambda p: len(p.parts), reverse=True):
            item_res = item.resolve(strict=False)
            if not item_res.is_relative_to(alvo_res) or item_res == alvo_res:
                continue
            rel_item = item.relative_to(alvo)
            if _eh_metadado_godot(rel_item):
                continue
            if item.is_file() or item.is_symlink():
                if item_res not in esperados_res:
                    item.unlink()
                    removidos.append(rel_item.as_posix())
            elif item.is_dir():
                try:
                    item.rmdir()
                except OSError:
                    # Diretorio nao vazio (ex.: contem metadados Godot preservados).
                    pass

    relatorio = {
        "schema": "forge3d/report@1",
        "comando": "sync",
        "ok": True,
        "origem": str(origem),
        "destino": str(alvo),
        "ativos": len(manifestos),
        "copiados": copiados,
        "removidos": removidos,
        "bytes": total_bytes,
    }
    if destino_lua_res is not None:
        lua_res = gerar_assets_lua(
            [origem, paths.arquivo_ledger()],
            destino_lua_res,
            namespace=namespace,
            origem_escopo=origem,
            destino_escopo=alvo,
            asset_ids_permitidos=asset_ids_origem,
            projetos_permitidos=projetos_origem,
        )
        relatorio["rojo_lua"] = lua_res["saida"]
        relatorio["rojo_assets"] = lua_res["total"]
    if destino_gd_res is not None:
        gd_res = gerar_assets_gd(
            origem,
            destino_gd_res,
            class_name=gd_class_name,
            res_prefix=res_prefix,
        )
        relatorio["godot_gd"] = gd_res["saida"]
        relatorio["godot_assets"] = gd_res["total"]
    return relatorio
