"""Sincronizacao explicita pos-verify entre ext4 (I12) e pastas externas (ex.: /mnt/<letra>/).

O pipeline (`plan`/`run`/`allowlist`) continua restrito a ext4 sob /home. Este modulo e a
ponte controlada de saida: so copia de um destino ext4 depois de `publish.verificar()` aprovar
todos os manifestos, hashes e gates G1-G10. Tambem gera o modulo Luau ``Assets.lua`` para Rojo.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from . import config, paths, publish, upload
from .errors import erro_destino, erro_manifesto, erro_path, erro_qc, erro_spec

__all__ = ["executar", "gerar_assets_gd", "gerar_assets_lua"]

_IDENTIFICADOR_LUAU = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SUFIXO_GODOT_KEEP_RE = re.compile(r"(?:_colisao|_lod[1-9]\d*)\.glb$", re.IGNORECASE)


def _raiz_repo() -> Path | None:
    """Detecta a raiz do repositorio Forge3D sem caminho pessoal fixo (I15)."""
    for cand in Path(__file__).resolve().parents:
        if (cand / "pyproject.toml").is_file() and (cand / "src" / "forge3d").is_dir():
            return cand.resolve(strict=False)
    return None


def _sobrepoe(a: Path, b: Path) -> bool:
    return a == b or a.is_relative_to(b) or b.is_relative_to(a)


def _checar_destino_externo(alvo_raw: str | os.PathLike, campo: str = "para") -> Path:
    bruto = str(alvo_raw)
    if "\\\\wsl" in bruto or bruto.startswith("//"):
        raise erro_path(
            f"destino de sync aponta para caminho UNC de rede: {bruto}. "
            "Use caminho montado (/mnt/<letra>/...) ou ext4.",
            campo=campo,
        )
    alvo = config.normalizar(alvo_raw)
    repo = _raiz_repo()
    if repo is not None and _sobrepoe(alvo, repo):
        raise erro_destino(
            f"destino de sync nao pode apontar para o repositorio do Forge3D: {alvo}",
            destino=str(alvo),
        )
    internos = (
        paths.raiz_config(),
        paths.dir_cache(),
        paths.dir_runs(),
        paths.dir_staging(),
        paths.dir_locks(),
    )
    if alvo == paths.raiz_estado() or any(_sobrepoe(alvo, raiz) for raiz in internos):
        raise erro_destino(
            f"destino de sync nao pode apontar para estado/config interno do Forge3D: {alvo}",
            destino=str(alvo),
        )
    return alvo


def _validar_alvo(alvo_raw: str | os.PathLike, origem: Path) -> Path:
    alvo = _checar_destino_externo(alvo_raw, campo="para")
    if _sobrepoe(alvo, origem):
        raise erro_destino(
            f"destino de sync ({alvo}) nao pode coincidir nem sobrepor a origem ({origem})",
            origem=str(origem),
            destino=str(alvo),
        )
    return alvo


def _copiar_atomico(src: Path, dst: Path, tag: str) -> int:
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.parent / f".{dst.name}.{tag}.tmp"
    try:
        with open(src, "rb") as fent, open(tmp, "wb") as fsai:
            shutil.copyfileobj(fent, fsai)
            fsai.flush()
            try:
                os.fsync(fsai.fileno())
            except OSError:
                pass
        os.replace(tmp, dst)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return dst.stat().st_size


def _escrever_atomico(dst: Path, conteudo: str, tag: str) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.parent / f".{dst.name}.{tag}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fsai:
            fsai.write(conteudo)
            fsai.flush()
            try:
                os.fsync(fsai.fileno())
            except OSError:
                pass
        os.replace(tmp, dst)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _formatar_rbxassetid(valor: str) -> str:
    limpo = valor.strip()
    if limpo.startswith("rbxassetid://"):
        return limpo
    return f"rbxassetid://{limpo}"


def _escapar_luau(texto: str) -> str:
    return (
        texto.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )


def _extrair_pares_registro(rec: dict) -> list[tuple[str, str]]:
    if not isinstance(rec, dict):
        return []
    if rec.get("evento") == "run":
        return []

    schema = str(rec.get("schema") or "")
    eh_manifesto = schema.startswith("forge3d/manifest@") or ("files" in rec and "qc" in rec)
    if eh_manifesto:
        logical_id = str(rec.get("asset_id") or rec.get("id") or "").strip()
        raw_rbx = (
            rec.get("rbxassetid")
            or rec.get("roblox_asset_id")
            or (rec.get("roblox") or {}).get("asset_id")
            or (rec.get("roblox") or {}).get("assetId")
            or (rec.get("upload") or {}).get("asset_id")
            or (rec.get("upload") or {}).get("assetId")
        )
        if logical_id and raw_rbx is not None and str(raw_rbx).strip():
            return [(logical_id, _formatar_rbxassetid(str(raw_rbx)))]
        return []

    if "roblox_asset_id" in rec or "roblox" in rec or "upload" in rec:
        logical_id = str(
            rec.get("id")
            or rec.get("item_id")
            or rec.get("forge3d_id")
            or rec.get("asset_id")
            or rec.get("nome")
            or rec.get("name")
            or ""
        ).strip()
        raw_rbx = (
            rec.get("roblox_asset_id")
            or rec.get("rbxassetid")
            or (rec.get("roblox") or {}).get("asset_id")
            or (rec.get("roblox") or {}).get("assetId")
            or (rec.get("upload") or {}).get("asset_id")
            or (rec.get("upload") or {}).get("assetId")
        )
        if logical_id and raw_rbx is not None and str(raw_rbx).strip():
            return [(logical_id, _formatar_rbxassetid(str(raw_rbx)))]
        return []

    tem_chave_id = any(
        k in rec for k in ("id", "item_id", "forge3d_id", "nome", "name", "displayName", "arquivo")
    )
    tem_chave_rbx = any(k in rec for k in ("rbxassetid", "asset_id", "assetId"))
    if tem_chave_id and tem_chave_rbx:
        logical_id = str(
            rec.get("id")
            or rec.get("item_id")
            or rec.get("forge3d_id")
            or rec.get("nome")
            or rec.get("name")
            or rec.get("displayName")
            or ""
        ).strip()
        if not logical_id and rec.get("arquivo"):
            logical_id = Path(str(rec["arquivo"])).stem
        raw_rbx = rec.get("rbxassetid") or rec.get("asset_id") or rec.get("assetId")
        if logical_id and raw_rbx is not None and str(raw_rbx).strip():
            return [(logical_id, _formatar_rbxassetid(str(raw_rbx)))]
        return []

    pares: list[tuple[str, str]] = []
    if all(isinstance(v, (str, int)) and not isinstance(v, bool) for v in rec.values()):
        for k in sorted(rec):
            val = str(rec[k]).strip()
            if str(k).strip() and val:
                pares.append((str(k).strip(), _formatar_rbxassetid(val)))
    return pares


def _ler_fonte_assets(fonte: str | os.PathLike | dict, mapa: dict[str, str | dict[str, str]]) -> None:
    if isinstance(fonte, dict):
        for k, v in _extrair_pares_registro(fonte):
            mapa[k] = v
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
            for k, v in _extrair_pares_registro(dados):
                mapa[k] = v
        return

    if caminho.is_file():
        if caminho.suffix.lower() in (".jsonl", ".ndjson"):
            for linha in caminho.read_text(encoding="utf-8").splitlines():
                texto = linha.strip()
                if not texto:
                    continue
                try:
                    dados = json.loads(texto)
                except ValueError:
                    continue
                for k, v in _extrair_pares_registro(dados):
                    mapa[k] = v
            por_id: dict[str, dict[str, str]] = {}
            for (lid, role), uri in upload.resolver_ledger(caminho).items():
                if role:
                    por_id.setdefault(lid, {})[role] = uri
            for lid, roles in por_id.items():
                if len(roles) > 1:
                    mapa[lid] = {r: roles[r] for r in sorted(roles)}
            return
        try:
            dados = json.loads(caminho.read_text(encoding="utf-8"))
        except ValueError:
            return
        if isinstance(dados, list):
            for item in dados:
                for k, v in _extrair_pares_registro(item):
                    mapa[k] = v
        elif isinstance(dados, dict):
            for k, v in _extrair_pares_registro(dados):
                mapa[k] = v


def _eh_metadado_godot(rel_path: Path) -> bool:
    """Identifica metadados gerenciados pelo editor Godot (.import, .uid, .godot/)."""
    if ".godot" in rel_path.parts:
        return True
    return rel_path.suffix.lower() in (".import", ".uid")


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
        return f'"{_escapar_luau(valor)}"'
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
            f'{tab}"{_escapar_luau(str(k))}": {_formatar_gdscript(valor[k], nivel + 1)}'
            for k in sorted(valor, key=str)
        )
        return f"{{\n{itens},\n{tab_fim}}}"
    return f'"{_escapar_luau(str(valor))}"'


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
        papel = str(item.get("papel") or "").strip()
        if not caminho:
            continue
        if papel == "mesh" and not mesh_rel:
            mesh_rel = caminho
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
                if not mesh_rel and int(lod_item.get("nivel", 0)) == 0:
                    mesh_rel = arq_lod
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


def _formatar_luau_valor(valor: str | dict[str, str], nivel: int = 1) -> str:
    if isinstance(valor, dict):
        if not valor:
            return "{}"
        tab = "\t" * (nivel + 1)
        tab_fim = "\t" * nivel
        itens = "\n".join(
            f'{tab}["{_escapar_luau(str(k))}"] = "{_escapar_luau(str(valor[k]))}",'
            for k in sorted(valor)
        )
        return f"{{\n{itens}\n{tab_fim}}}"
    return f'"{_escapar_luau(str(valor))}"'


def gerar_assets_lua(
    fontes_ou_ledger: str | os.PathLike | dict | Iterable[str | os.PathLike | dict] | None,
    destino_lua: str | os.PathLike,
    namespace: str = "Assets",
) -> dict:
    """Gera modulo Luau ``Assets.lua`` deterministico (``id -> rbxassetid://<asset_id>`` ou mapa por role)."""
    if not _IDENTIFICADOR_LUAU.match(namespace or ""):
        raise erro_spec(f"namespace Luau invalido: {namespace!r}", namespace=namespace)

    destino = _checar_destino_externo(destino_lua, campo="rojo_lua")
    if fontes_ou_ledger is None:
        fontes: list[str | os.PathLike | dict] = []
    elif isinstance(fontes_ou_ledger, (str, os.PathLike, dict)):
        fontes = [fontes_ou_ledger]
    else:
        fontes = list(fontes_ou_ledger)

    mapa: dict[str, str | dict[str, str]] = {}
    for fonte in fontes:
        _ler_fonte_assets(fonte, mapa)

    ordenado = {k: mapa[k] for k in sorted(mapa)}
    if ordenado:
        entradas = "\n".join(
            f'\t["{_escapar_luau(k)}"] = {_formatar_luau_valor(v, nivel=1)},'
            for k, v in ordenado.items()
        )
        corpo = f"{{\n{entradas}\n}}"
    else:
        corpo = "{}"

    conteudo = (
        "-- Gerado automaticamente pelo Forge3D. Nao editar manualmente.\n"
        f"local {namespace} = {corpo}\n\n"
        f"return {namespace}\n"
    )
    _escrever_atomico(destino, conteudo, f"rojo-{os.getpid()}")
    return {
        "ok": True,
        "saida": str(destino),
        "namespace": namespace,
        "total": len(ordenado),
        "assets": ordenado,
    }


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
    destino_gd_res: Path | None = None
    if godot_gd is not None:
        destino_gd_res = _checar_destino_externo(godot_gd, campo="godot_gd")
        if _sobrepoe(destino_gd_res, origem):
            raise erro_destino(
                f"destino godot_gd ({destino_gd_res}) nao pode sobrepor a origem ({origem})",
                origem=str(origem),
                destino=str(destino_gd_res),
            )
    elif (alvo / "project.godot").is_file():
        destino_gd_res = _checar_destino_externo(alvo / "forge3d_assets.gd", campo="godot_gd")

    manifestos = sorted(origem.glob("*.manifest.json"))
    pares_arquivos: list[tuple[Path, Path, str]] = []
    pares_manifestos: list[tuple[Path, Path, str]] = []
    esperados: set[str] = set()

    for caminho_man in manifestos:
        man = json.loads(caminho_man.read_text(encoding="utf-8"))
        for arq in man.get("files", []):
            rel = str(arq["caminho"])
            src_arq = publish._caminho_seguro(origem, rel)
            dst_arq = publish._caminho_seguro(alvo, rel)
            if rel not in esperados:
                esperados.add(rel)
                pares_arquivos.append((src_arq, dst_arq, rel))
        rel_man = caminho_man.name
        dst_man = publish._caminho_seguro(alvo, rel_man)
        if rel_man not in esperados:
            esperados.add(rel_man)
            pares_manifestos.append((caminho_man, dst_man, rel_man))

    alvo.mkdir(parents=True, exist_ok=True)
    tag = f"sync-{os.getpid()}"
    copiados: list[str] = []
    total_bytes = 0

    is_godot = (alvo / "project.godot").is_file() or destino_gd_res is not None
    sidecars_godot: list[Path] = []
    for src, dst, rel in pares_arquivos:
        total_bytes += _copiar_atomico(src, dst, tag)
        copiados.append(rel)
        if is_godot and _SUFIXO_GODOT_KEEP_RE.search(dst.name):
            import_dst = Path(f"{dst}.import")
            _escrever_atomico(import_dst, '[remap]\nimporter="keep"\n', tag)
            sidecars_godot.append(import_dst.resolve(strict=False))
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
