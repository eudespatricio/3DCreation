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

from . import config, paths, publish
from .errors import erro_destino, erro_manifesto, erro_path, erro_qc, erro_spec

__all__ = ["executar", "gerar_assets_lua"]

_IDENTIFICADOR_LUAU = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


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


def _ler_fonte_assets(fonte: str | os.PathLike | dict, mapa: dict[str, str]) -> None:
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


def gerar_assets_lua(
    fontes_ou_ledger: str | os.PathLike | dict | Iterable[str | os.PathLike | dict] | None,
    destino_lua: str | os.PathLike,
    namespace: str = "Assets",
) -> dict:
    """Gera modulo Luau ``Assets.lua`` deterministico (``id -> rbxassetid://<asset_id>``)."""
    if not _IDENTIFICADOR_LUAU.match(namespace or ""):
        raise erro_spec(f"namespace Luau invalido: {namespace!r}", namespace=namespace)

    destino = _checar_destino_externo(destino_lua, campo="rojo_lua")
    if fontes_ou_ledger is None:
        fontes: list[str | os.PathLike | dict] = []
    elif isinstance(fontes_ou_ledger, (str, os.PathLike, dict)):
        fontes = [fontes_ou_ledger]
    else:
        fontes = list(fontes_ou_ledger)

    mapa: dict[str, str] = {}
    for fonte in fontes:
        _ler_fonte_assets(fonte, mapa)

    ordenado = {k: mapa[k] for k in sorted(mapa)}
    if ordenado:
        entradas = "\n".join(
            f'\t["{_escapar_luau(k)}"] = "{_escapar_luau(v)}",' for k, v in ordenado.items()
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

    for src, dst, rel in pares_arquivos:
        total_bytes += _copiar_atomico(src, dst, tag)
        copiados.append(rel)
    for src, dst, rel in pares_manifestos:
        total_bytes += _copiar_atomico(src, dst, tag)
        copiados.append(rel)

    removidos: list[str] = []
    if limpar:
        alvo_res = alvo.resolve(strict=False)
        esperados_res = {publish._caminho_seguro(alvo, rel) for rel in esperados}
        if destino_lua_res is not None:
            esperados_res.add(destino_lua_res)
        for item in sorted(alvo.rglob("*"), key=lambda p: len(p.parts), reverse=True):
            item_res = item.resolve(strict=False)
            if not item_res.is_relative_to(alvo_res) or item_res == alvo_res:
                continue
            if item.is_file() or item.is_symlink():
                if item_res not in esperados_res:
                    item.unlink()
                    removidos.append(item.relative_to(alvo).as_posix())
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
    return relatorio
