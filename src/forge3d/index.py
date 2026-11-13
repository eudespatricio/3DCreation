"""Indice SQLite consultavel e ledger append-only de execucoes/uploads."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from . import locks, paths

__all__ = ["consultar", "registrar_ledger"]


def _agora() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _conexao() -> sqlite3.Connection:
    paths.raiz_estado().mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(paths.arquivo_indice(), timeout=30.0)
    con.execute("PRAGMA busy_timeout=30000")
    con.execute("PRAGMA journal_mode=WAL")
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS assets (
            asset_id TEXT, projeto TEXT, perfil TEXT, rota TEXT, determinism TEXT,
            triangulos INTEGER, bytes INTEGER, materiais INTEGER, ossos INTEGER,
            licenca TEXT, spec_hash TEXT, pipeline_version TEXT, destino TEXT,
            publicado_em TEXT, tags TEXT,
            PRIMARY KEY (asset_id, destino)
        )
        """
    )
    pk_cols = [row[1] for row in con.execute("PRAGMA table_info(assets)").fetchall() if row[5] > 0]
    if pk_cols != ["asset_id", "destino"]:
        with con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS assets_v2 (
                    asset_id TEXT, projeto TEXT, perfil TEXT, rota TEXT, determinism TEXT,
                    triangulos INTEGER, bytes INTEGER, materiais INTEGER, ossos INTEGER,
                    licenca TEXT, spec_hash TEXT, pipeline_version TEXT, destino TEXT,
                    publicado_em TEXT, tags TEXT,
                    PRIMARY KEY (asset_id, destino)
                )
                """
            )
            con.execute(
                """
                INSERT OR REPLACE INTO assets_v2
                SELECT asset_id, projeto, perfil, rota, determinism, triangulos, bytes,
                       materiais, ossos, licenca, spec_hash, pipeline_version, destino,
                       publicado_em, tags
                FROM assets
                """
            )
            con.execute("DROP TABLE assets")
            con.execute("ALTER TABLE assets_v2 RENAME TO assets")
    return con


def _indice_upsert(manifesto: dict, destino: Path) -> None:
    total = sum(a["bytes"] for a in manifesto["files"])
    tags = " ".join(manifesto.get("tags") or [])
    con = _conexao()
    try:
        with con:
            con.execute(
                """
                INSERT INTO assets (asset_id, projeto, perfil, rota, determinism, triangulos, bytes,
                                    materiais, ossos, licenca, spec_hash, pipeline_version, destino,
                                    publicado_em, tags)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(asset_id, destino) DO UPDATE SET
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
    finally:
        con.close()


def _indice_remover(asset_id: str, destino: Path | str | None = None) -> None:
    con = _conexao()
    try:
        with con:
            if destino is not None:
                con.execute(
                    "DELETE FROM assets WHERE asset_id = ? AND destino = ?",
                    (asset_id, str(destino)),
                )
            else:
                con.execute("DELETE FROM assets WHERE asset_id = ?", (asset_id,))
    finally:
        con.close()


def consultar(
    projeto: str | None = None,
    max_tris: int | None = None,
    perfil: str | None = None,
    tag: str | None = None,
) -> list[dict]:
    """Consulta assets publicados no indice SQLite filtrando por projeto, perfil, tris e tag."""
    con = _conexao()
    try:
        sql = (
            "SELECT asset_id, projeto, perfil, rota, determinism, triangulos, bytes, materiais, "
            "ossos, licenca, destino, publicado_em FROM assets WHERE 1=1"
        )
        args: list = []
        if projeto:
            sql += " AND projeto = ?"
            args.append(projeto)
        if perfil:
            sql += " AND perfil = ?"
            args.append(perfil)
        if max_tris is not None:
            sql += " AND triangulos <= ?"
            args.append(max_tris)
        if tag:
            sql += " AND ' ' || COALESCE(tags, '') || ' ' LIKE ?"
            args.append(f"% {tag.strip()} %")
        sql += " ORDER BY asset_id"
        linhas = con.execute(sql, args).fetchall()
    finally:
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
    """Anexa evento JSONL ao ledger global sob lock de arquivo."""
    caminho = paths.arquivo_ledger()
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with open(caminho, "a", encoding="utf-8") as fh:
        if locks.fcntl is not None:
            locks.fcntl.flock(fh.fileno(), locks.fcntl.LOCK_EX)
        try:
            linha = json.dumps({"ts": _agora(), **evento}, sort_keys=True, ensure_ascii=False)
            fh.write(linha + "\n")
            fh.flush()
        finally:
            if locks.fcntl is not None:
                locks.fcntl.flock(fh.fileno(), locks.fcntl.LOCK_UN)
