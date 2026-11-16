"""Catalogo local curado de ativos 3D e texturas PBR CC0 com busca semantica — stdlib pura (D26).

Armazena metadados, hashes SHA256, licencas verificadas (I7/D18) e vetores de embedding
(``gemini-embedding-2-preview``) em SQLite sob ``paths.raiz_estado() / "vault"`` (D24, I12).
Quando a chave de API ou embeddings nao estao disponiveis, opera em fallback deterministico
offline via pontuacao lexical BM25 com expansao de sinonimos PT/EN.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import paths
from .errors import erro_input_tampered, erro_licenca, erro_path, erro_recurso

__all__ = [
    "LICENCAS_PERMITIDAS",
    "ORIGENS_PERMITIDAS",
    "PADROES_LICENCA_BLOQUEADOS",
    "VaultCC0",
    "dir_vault",
    "normalizar_vetor_l2",
    "sha256_arquivo",
    "similaridade_cosseno",
    "validar_licenca_cc0",
]

LICENCAS_PERMITIDAS: tuple[str, ...] = (
    "CC0-1.0",
    "CC0",
    "Public Domain",
    "MIT",
)

_MAPA_LICENCAS_CANONICAS: dict[str, str] = {
    "cc0-1.0": "CC0-1.0",
    "cc0 1.0": "CC0-1.0",
    "cc0": "CC0",
    "public domain": "Public Domain",
    "public_domain": "Public Domain",
    "pd": "Public Domain",
    "mit": "MIT",
    "mit license": "MIT",
}

ORIGENS_PERMITIDAS: tuple[str, ...] = (
    "polyhaven",
    "ambientcg",
    "kenney",
    "quaternius",
    "mpfb2_cc0",
    "forge3d_procedural_cc0",
    "local_cc0",
)

PADROES_LICENCA_BLOQUEADOS: tuple[str, ...] = (
    "by-nc",
    "cc-by-nc",
    "noncommercial",
    "non-commercial",
    "gpl",
    "agpl",
    "lgpl",
    "by-sa",
    "cc-by-sa",
    "unknown",
    "proprietary",
    "all rights reserved",
    "hunyuan",
    "pixal3d",
)

_RE_TOKEN_NC = re.compile(r"(?:^|[^a-z0-9])nc(?:$|[^a-z0-9])", re.IGNORECASE)
_RE_MNT_WINDOWS = re.compile(r"^/mnt/[a-zA-Z](?:/|$)")

_SINONIMOS_KITBASH: dict[str, tuple[str, ...]] = {
    "espada": ("sword", "blade", "lamina", "weapon", "arma", "hilt", "guard", "pommel"),
    "sword": ("espada", "blade", "lamina", "weapon", "arma", "hilt", "guard", "pommel"),
    "lamina": ("blade", "sword", "espada", "edge", "steel", "aco"),
    "blade": ("lamina", "sword", "espada", "edge", "steel", "aco"),
    "cabo": ("grip", "handle", "hilt", "punho", "leather", "couro"),
    "punho": ("grip", "handle", "hilt", "cabo", "leather", "couro"),
    "grip": ("cabo", "punho", "handle", "hilt", "leather", "couro"),
    "handle": ("cabo", "punho", "grip", "hilt"),
    "guarda": ("guard", "crossguard", "hilt", "bronze", "steel"),
    "guard": ("guarda", "crossguard", "hilt"),
    "crossguard": ("guarda", "guard", "hilt"),
    "pomo": ("pommel", "counterweight", "hilt", "stone", "gem"),
    "pommel": ("pomo", "hilt", "stone", "gem"),
    "escudo": ("shield", "buckler", "boss", "defesa", "armor"),
    "shield": ("escudo", "buckler", "boss", "armor"),
    "machado": ("axe", "hatchet", "blade", "weapon", "arma"),
    "axe": ("machado", "hatchet", "blade", "weapon", "arma"),
    "armadura": ("armor", "plate", "pauldron", "chestplate", "steel", "aco"),
    "armor": ("armadura", "plate", "pauldron", "chestplate", "steel", "aco"),
    "ombreira": ("pauldron", "shoulder", "armor", "armadura"),
    "pauldron": ("ombreira", "shoulder", "armor", "armadura"),
    "aco": ("steel", "metal", "iron", "forged", "forjado"),
    "steel": ("aco", "metal", "iron", "forged", "forjado"),
    "couro": ("leather", "saddle", "strap", "grip", "cabo"),
    "leather": ("couro", "saddle", "strap", "grip", "cabo"),
    "bronze": ("gold", "ouro", "brass", "filigree", "ornate", "metal"),
    "ouro": ("gold", "bronze", "filigree", "ornate"),
    "gold": ("ouro", "bronze", "filigree", "ornate"),
    "tecido": ("linen", "cloth", "tunic", "fabric", "linho"),
    "linen": ("tecido", "cloth", "tunic", "fabric", "linho"),
    "madeira": ("wood", "timber", "oak", "staff", "handle"),
    "wood": ("madeira", "timber", "oak", "staff", "handle"),
    "pedra": ("stone", "rock", "granite", "moss", "musgo"),
    "stone": ("pedra", "rock", "granite", "moss", "musgo"),
}


def _agora_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _validar_caminho_ext4(caminho: Path, contexto: str = "vault") -> Path:
    resolvido = caminho.expanduser().resolve()
    if _RE_MNT_WINDOWS.match(str(resolvido)):
        raise erro_path(
            f"{contexto} deve residir em filesystem ext4 nativo (I12), nunca em {resolvido}",
            caminho=str(resolvido),
        )
    return resolvido


def dir_vault(vault_dir: Path | str | None = None) -> Path:
    """Resolve o diretorio do Vault CC0 (padrao: ``paths.raiz_estado() / 'vault'``)."""
    if vault_dir is not None and str(vault_dir).strip():
        alvo = Path(vault_dir)
    else:
        env_dir = os.environ.get("FORGE3D_VAULT_DIR", "").strip()
        alvo = Path(env_dir) if env_dir else (paths.raiz_estado() / "vault")
    return _validar_caminho_ext4(alvo, contexto="vault_dir")


def sha256_arquivo(caminho: Path | str) -> str:
    """Calcula ``sha256:<hex>`` de um arquivo em disco."""
    arq = Path(caminho)
    if not arq.is_file():
        raise erro_recurso(f"arquivo ausente para calculo de SHA256: {arq}", caminho=str(arq))
    h = hashlib.sha256()
    with arq.open("rb") as fh:
        while True:
            bloco = fh.read(65536)
            if not bloco:
                break
            h.update(bloco)
    return f"sha256:{h.hexdigest()}"


def validar_licenca_cc0(licenca: str, origem: str = "", modelo: str = "") -> dict[str, Any]:
    """Valida se a licenca, origem e modelo atendem ao gate comercial estrito (I7, D18).

    Apenas ``CC0-1.0``, ``CC0``, ``Public Domain`` e ``MIT`` de origens comerciais limpas
    sao aceitos. Qualquer mencao a ``NC``, ``BY-NC``, ``GPL``, ``unknown``, ``hunyuan`` ou
    ``pixal3d`` dispara ``erro_licenca`` (``FORGE-E-LICENCA``).
    """
    lic_raw = (licenca or "").strip()
    orig_raw = (origem or "").strip()
    mod_raw = (modelo or "").strip()

    combinado_lower = f"{lic_raw} {orig_raw} {mod_raw}".lower()
    for proibido in PADROES_LICENCA_BLOQUEADOS:
        if proibido in combinado_lower:
            raise erro_licenca(
                f"ativo bloqueado pela politica comercial (I7/D18): padrao proibido '{proibido}' "
                f"detectado (licenca={lic_raw!r}, origem={orig_raw!r}, modelo={mod_raw!r})",
                licenca=lic_raw,
                origem=orig_raw,
                modelo=mod_raw,
            )

    if _RE_TOKEN_NC.search(lic_raw) or _RE_TOKEN_NC.search(orig_raw) or _RE_TOKEN_NC.search(mod_raw):
        raise erro_licenca(
            f"ativo bloqueado pela politica comercial (I7/D18): restricao Non-Commercial (NC) "
            f"detectada (licenca={lic_raw!r}, origem={orig_raw!r}, modelo={mod_raw!r})",
            licenca=lic_raw,
            origem=orig_raw,
            modelo=mod_raw,
        )

    if not lic_raw:
        raise erro_licenca(
            "licenca ausente: o Vault CC0 exige licenca explicita (CC0-1.0, CC0, Public Domain ou MIT)",
            licenca=lic_raw,
            origem=orig_raw,
        )

    lic_canonica = _MAPA_LICENCAS_CANONICAS.get(lic_raw.lower())
    if lic_canonica is None or lic_canonica not in LICENCAS_PERMITIDAS:
        raise erro_licenca(
            f"licenca '{lic_raw}' fora da allowlist comercial do Vault (I7/D18). "
            f"Permitidas: {', '.join(LICENCAS_PERMITIDAS)}",
            licenca=lic_raw,
            origem=orig_raw,
        )

    orig_norm = orig_raw.lower() if orig_raw else "local_cc0"
    if orig_norm not in ORIGENS_PERMITIDAS:
        raise erro_licenca(
            f"origem '{orig_raw}' fora da allowlist de origens curadas (I7/D18). "
            f"Permitidas: {', '.join(ORIGENS_PERMITIDAS)}",
            licenca=lic_canonica,
            origem=orig_raw,
        )

    return {
        "ok": True,
        "licenca": lic_canonica,
        "origem": orig_norm,
        "modelo": mod_raw,
        "uso_comercial": True,
    }


def normalizar_vetor_l2(vetor: list[float] | tuple[float, ...]) -> list[float]:
    """Normaliza um vetor numérico na norma L2."""
    if not vetor:
        raise ValueError("vetor de embedding nao pode ser vazio")
    floats = [float(x) for x in vetor]
    norma = math.sqrt(sum(x * x for x in floats))
    if norma <= 1e-12:
        return floats
    return [x / norma for x in floats]


def similaridade_cosseno(v1: list[float] | tuple[float, ...], v2: list[float] | tuple[float, ...]) -> float:
    """Calcula a similaridade de cosseno entre dois vetores de mesma dimensao."""
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot = sum(float(a) * float(b) for a, b in zip(v1, v2))
    n1 = math.sqrt(sum(float(a) * float(a) for a in v1))
    n2 = math.sqrt(sum(float(b) * float(b) for b in v2))
    if n1 <= 1e-12 or n2 <= 1e-12:
        return 0.0
    return max(-1.0, min(1.0, dot / (n1 * n2)))


def _tokenizar(texto: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9]+", (texto or "").lower())
    return [t for t in tokens if len(t) >= 2]


def _expandir_tokens_consulta(tokens: list[str]) -> list[str]:
    expandidos: list[str] = []
    vistos: set[str] = set()
    for tok in tokens:
        if tok not in vistos:
            vistos.add(tok)
            expandidos.append(tok)
        for sin in _SINONIMOS_KITBASH.get(tok, ()):
            if sin not in vistos:
                vistos.add(sin)
                expandidos.append(sin)
    return expandidos


class VaultCC0:
    """Catalogo local SQLite de malhas 3D e texturas PBR sob licenca comercial limpa (CC0/MIT)."""

    def __init__(self, vault_dir: Path | str | None = None) -> None:
        self.vault_dir = dir_vault(vault_dir)
        self.vault_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.vault_dir / "vault.sqlite"
        self._inicializar_db()

    def _conectar(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path, timeout=30.0)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA busy_timeout=30000")
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA foreign_keys=ON")
        return con

    def _inicializar_db(self) -> None:
        con = self._conectar()
        try:
            with con:
                con.execute(
                    """
                    CREATE TABLE IF NOT EXISTS assets (
                        asset_id TEXT PRIMARY KEY,
                        nome TEXT NOT NULL,
                        tipo TEXT NOT NULL,
                        categoria TEXT NOT NULL,
                        caminho TEXT NOT NULL,
                        sha256 TEXT NOT NULL,
                        bytes INTEGER NOT NULL,
                        licenca TEXT NOT NULL,
                        origem TEXT NOT NULL,
                        modelo TEXT NOT NULL DEFAULT '',
                        tags_json TEXT NOT NULL DEFAULT '[]',
                        descricao TEXT NOT NULL DEFAULT '',
                        metadados_json TEXT NOT NULL DEFAULT '{}',
                        criado_em TEXT NOT NULL
                    )
                    """
                )
                con.execute(
                    """
                    CREATE TABLE IF NOT EXISTS embeddings (
                        asset_id TEXT PRIMARY KEY,
                        modelo TEXT NOT NULL,
                        dimensao INTEGER NOT NULL,
                        vetor_json TEXT NOT NULL,
                        atualizado_em TEXT NOT NULL,
                        FOREIGN KEY(asset_id) REFERENCES assets(asset_id) ON DELETE CASCADE
                    )
                    """
                )
        finally:
            con.close()

    @staticmethod
    def _row_para_dict(row: sqlite3.Row) -> dict[str, Any]:
        tags = json.loads(row["tags_json"] or "[]")
        metadados = json.loads(row["metadados_json"] or "{}")
        return {
            "asset_id": row["asset_id"],
            "nome": row["nome"],
            "tipo": row["tipo"],
            "categoria": row["categoria"],
            "caminho": row["caminho"],
            "sha256": row["sha256"],
            "bytes": int(row["bytes"]),
            "licenca": row["licenca"],
            "origem": row["origem"],
            "modelo": row["modelo"],
            "tags": tags if isinstance(tags, list) else [],
            "descricao": row["descricao"],
            "metadados": metadados if isinstance(metadados, dict) else {},
            "criado_em": row["criado_em"],
            "uso_comercial": True,
        }

    def registrar_ativo(
        self,
        *,
        asset_id: str,
        caminho: Path | str,
        tipo: str = "mesh",
        categoria: str = "prop",
        licenca: str = "CC0-1.0",
        origem: str = "local_cc0",
        nome: str = "",
        descricao: str = "",
        tags: list[str] | tuple[str, ...] | None = None,
        modelo: str = "",
        metadados: dict[str, Any] | None = None,
        embedding: list[float] | None = None,
        modelo_embedding: str = "gemini-embedding-2-preview",
    ) -> dict[str, Any]:
        """Registra ou atualiza um ativo CC0/MIT no Vault apos validar licenca e SHA256."""
        id_limpo = (asset_id or "").strip()
        if not id_limpo:
            raise ValueError("asset_id nao pode ser vazio")

        info_lic = validar_licenca_cc0(licenca, origem=origem, modelo=modelo)
        arq = _validar_caminho_ext4(Path(caminho), contexto=f"ativo '{id_limpo}'")
        if not arq.is_file():
            raise erro_recurso(f"arquivo do ativo ausente em disco: {arq}", asset_id=id_limpo, caminho=str(arq))

        digest = sha256_arquivo(arq)
        tamanho = int(arq.stat().st_size)
        nome_final = (nome or arq.stem).strip() or id_limpo
        tipo_final = (tipo or "mesh").strip().lower()
        cat_final = (categoria or "prop").strip().lower()
        lista_tags = [str(t).strip().lower() for t in (tags or []) if str(t).strip()]
        meta_dict = dict(metadados) if isinstance(metadados, dict) else {}
        criado_em = _agora_iso()

        con = self._conectar()
        try:
            with con:
                con.execute(
                    """
                    INSERT INTO assets (
                        asset_id, nome, tipo, categoria, caminho, sha256, bytes,
                        licenca, origem, modelo, tags_json, descricao, metadados_json, criado_em
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(asset_id) DO UPDATE SET
                        nome=excluded.nome,
                        tipo=excluded.tipo,
                        categoria=excluded.categoria,
                        caminho=excluded.caminho,
                        sha256=excluded.sha256,
                        bytes=excluded.bytes,
                        licenca=excluded.licenca,
                        origem=excluded.origem,
                        modelo=excluded.modelo,
                        tags_json=excluded.tags_json,
                        descricao=excluded.descricao,
                        metadados_json=excluded.metadados_json,
                        criado_em=excluded.criado_em
                    """,
                    (
                        id_limpo,
                        nome_final,
                        tipo_final,
                        cat_final,
                        str(arq),
                        digest,
                        tamanho,
                        info_lic["licenca"],
                        info_lic["origem"],
                        info_lic["modelo"],
                        json.dumps(lista_tags, ensure_ascii=False),
                        (descricao or "").strip(),
                        json.dumps(meta_dict, ensure_ascii=False),
                        criado_em,
                    ),
                )
        finally:
            con.close()

        if embedding is not None:
            self.registrar_embedding(id_limpo, embedding, modelo=modelo_embedding)

        ativo = self.obter_ativo(id_limpo)
        assert ativo is not None
        return ativo

    def obter_ativo(self, asset_id: str) -> dict[str, Any] | None:
        con = self._conectar()
        try:
            row = con.execute("SELECT * FROM assets WHERE asset_id = ?", (asset_id,)).fetchone()
            return self._row_para_dict(row) if row is not None else None
        finally:
            con.close()

    def listar_ativos(
        self,
        *,
        tipo: str | None = None,
        categoria: str | None = None,
        origem: str | None = None,
        tag: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if tipo:
            clauses.append("tipo = ?")
            params.append(tipo.strip().lower())
        if categoria:
            clauses.append("categoria = ?")
            params.append(categoria.strip().lower())
        if origem:
            clauses.append("origem = ?")
            params.append(origem.strip().lower())

        sql = "SELECT * FROM assets"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY asset_id ASC"

        con = self._conectar()
        try:
            rows = con.execute(sql, params).fetchall()
            ativos = [self._row_para_dict(r) for r in rows]
        finally:
            con.close()

        if tag:
            tag_norm = tag.strip().lower()
            ativos = [a for a in ativos if tag_norm in a.get("tags", [])]
        return ativos

    def registrar_embedding(
        self,
        asset_id: str,
        vetor: list[float] | tuple[float, ...],
        *,
        modelo: str = "gemini-embedding-2-preview",
    ) -> dict[str, Any]:
        """Armazena vetor de embedding L2-normalizado para ``asset_id``."""
        if self.obter_ativo(asset_id) is None:
            raise erro_recurso(f"ativo '{asset_id}' nao encontrado no Vault para anexar embedding", asset_id=asset_id)
        vetor_norm = normalizar_vetor_l2(vetor)
        agora = _agora_iso()
        con = self._conectar()
        try:
            with con:
                con.execute(
                    """
                    INSERT INTO embeddings (asset_id, modelo, dimensao, vetor_json, atualizado_em)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(asset_id) DO UPDATE SET
                        modelo=excluded.modelo,
                        dimensao=excluded.dimensao,
                        vetor_json=excluded.vetor_json,
                        atualizado_em=excluded.atualizado_em
                    """,
                    (
                        asset_id,
                        (modelo or "gemini-embedding-2-preview").strip(),
                        len(vetor_norm),
                        json.dumps(vetor_norm),
                        agora,
                    ),
                )
        finally:
            con.close()
        return {
            "asset_id": asset_id,
            "modelo": (modelo or "gemini-embedding-2-preview").strip(),
            "dimensao": len(vetor_norm),
            "vetor": vetor_norm,
            "atualizado_em": agora,
        }

    def obter_embedding(self, asset_id: str) -> dict[str, Any] | None:
        con = self._conectar()
        try:
            row = con.execute("SELECT * FROM embeddings WHERE asset_id = ?", (asset_id,)).fetchone()
            if row is None:
                return None
            return {
                "asset_id": row["asset_id"],
                "modelo": row["modelo"],
                "dimensao": int(row["dimensao"]),
                "vetor": [float(x) for x in json.loads(row["vetor_json"])],
                "atualizado_em": row["atualizado_em"],
            }
        finally:
            con.close()

    def validar_integridade(
        self,
        asset_id: str | None = None,
        *,
        levantar: bool = False,
    ) -> dict[str, Any]:
        """Verifica SHA256 em disco e conformidade de licenca para um ou todos os ativos."""
        if asset_id is not None:
            alvo = self.obter_ativo(asset_id)
            if alvo is None:
                raise erro_recurso(f"ativo '{asset_id}' nao registrado no Vault", asset_id=asset_id)
            ativos = [alvo]
        else:
            ativos = self.listar_ativos()

        validos: list[str] = []
        ausentes: list[dict[str, str]] = []
        corrompidos: list[dict[str, str]] = []

        for ativo in ativos:
            aid = ativo["asset_id"]
            validar_licenca_cc0(ativo["licenca"], origem=ativo["origem"], modelo=ativo.get("modelo", ""))
            caminho = Path(ativo["caminho"])
            if not caminho.is_file():
                ausentes.append({"asset_id": aid, "caminho": str(caminho)})
                continue
            hash_atual = sha256_arquivo(caminho)
            if hash_atual != ativo["sha256"]:
                corrompidos.append(
                    {
                        "asset_id": aid,
                        "caminho": str(caminho),
                        "esperado": ativo["sha256"],
                        "atual": hash_atual,
                    }
                )
                continue
            validos.append(aid)

        ok = len(ausentes) == 0 and len(corrompidos) == 0
        if not ok and levantar:
            detalhe_msg = []
            if ausentes:
                detalhe_msg.append(f"ausentes={[a['asset_id'] for a in ausentes]}")
            if corrompidos:
                detalhe_msg.append(f"corrompidos={[c['asset_id'] for c in corrompidos]}")
            raise erro_input_tampered(
                f"falha de integridade SHA256 no Vault CC0: {'; '.join(detalhe_msg)}",
                ausentes=ausentes,
                corrompidos=corrompidos,
            )

        return {
            "ok": ok,
            "total": len(ativos),
            "validos": len(validos),
            "ativos_validos": validos,
            "ausentes": ausentes,
            "corrompidos": corrompidos,
        }

    @staticmethod
    def _pontuar_bm25(
        tokens_query: list[str],
        ativos: list[dict[str, Any]],
    ) -> dict[str, float]:
        if not ativos or not tokens_query:
            return {a["asset_id"]: 0.0 for a in ativos}

        docs_tokens: dict[str, list[str]] = {}
        df: dict[str, int] = {t: 0 for t in set(tokens_query)}

        for ativo in ativos:
            partes = [
                ativo["asset_id"].replace(".", " ").replace("_", " "),
                ativo["nome"].replace("_", " "),
                ativo["tipo"],
                ativo["categoria"],
                " ".join(ativo.get("tags", [])),
                ativo.get("descricao", ""),
            ]
            toks = _tokenizar(" ".join(partes))
            docs_tokens[ativo["asset_id"]] = toks
            conjunto = set(toks)
            for qt in df:
                if qt in conjunto or any(qt in tok or tok in qt for tok in conjunto):
                    df[qt] += 1

        n_docs = len(ativos)
        avgdl = max(1.0, sum(len(v) for v in docs_tokens.values()) / float(n_docs))
        k1 = 1.5
        b = 0.75

        scores: dict[str, float] = {}
        for ativo in ativos:
            aid = ativo["asset_id"]
            toks = docs_tokens[aid]
            dl = float(len(toks))
            score = 0.0
            for qt in tokens_query:
                tf_exato = sum(1 for tok in toks if tok == qt)
                tf_parcial = sum(0.45 for tok in toks if tok != qt and (qt in tok or tok in qt))
                tf = float(tf_exato) + tf_parcial
                if tf <= 0.0:
                    continue
                n_q = df.get(qt, 0)
                idf = math.log(1.0 + (n_docs - n_q + 0.5) / (n_q + 0.5))
                denom = tf + k1 * (1.0 - b + b * (dl / avgdl))
                score += idf * ((tf * (k1 + 1.0)) / denom)
            scores[aid] = score

        max_s = max(scores.values(), default=0.0)
        if max_s > 1e-9:
            return {k: v / max_s for k, v in scores.items()}
        return scores

    def buscar_semantico(
        self,
        query: str,
        *,
        top_k: int = 5,
        query_embedding: list[float] | None = None,
        tipo: str | None = None,
        categoria: str | None = None,
        usar_gemini_online: bool = False,
    ) -> list[dict[str, Any]]:
        """Busca ativos por similaridade de cosseno (Gemini Embedding-2) com fallback BM25 offline."""
        candidatos = self.listar_ativos(tipo=tipo, categoria=categoria)
        if not candidatos or top_k <= 0:
            return []

        vetor_q: list[float] | None = None
        if query_embedding is not None and len(query_embedding) > 0:
            vetor_q = normalizar_vetor_l2(query_embedding)
        elif usar_gemini_online and (query or "").strip():
            try:
                from .providers import cloud_ai

                ok_gem, _ = cloud_ai.gemini_disponivel()
                if ok_gem:
                    vetor_q = cloud_ai.gerar_embedding_gemini(
                        query,
                        task_type="RETRIEVAL_QUERY",
                    )
            except Exception:
                vetor_q = None

        tokens_base = _tokenizar(query or "")
        tokens_exp = _expandir_tokens_consulta(tokens_base)
        scores_lex = self._pontuar_bm25(tokens_exp, candidatos)

        con = self._conectar()
        try:
            rows_emb = con.execute("SELECT asset_id, vetor_json FROM embeddings").fetchall()
            mapa_emb = {
                r["asset_id"]: [float(x) for x in json.loads(r["vetor_json"])]
                for r in rows_emb
            }
        finally:
            con.close()

        resultados: list[dict[str, Any]] = []
        for ativo in candidatos:
            aid = ativo["asset_id"]
            lex = float(scores_lex.get(aid, 0.0))
            emb_ativo = mapa_emb.get(aid)
            if vetor_q is not None and emb_ativo is not None and len(vetor_q) == len(emb_ativo):
                cos = similaridade_cosseno(vetor_q, emb_ativo)
                score_final = cos + (0.05 * lex)
                metodo = "embedding_cosine"
            else:
                cos = 0.0
                score_final = lex
                metodo = "lexical_bm25"

            item = dict(ativo)
            item["score"] = round(score_final, 6)
            item["score_cosseno"] = round(cos, 6)
            item["score_lexical"] = round(lex, 6)
            item["metodo_busca"] = metodo
            resultados.append(item)

        resultados.sort(
            key=lambda r: (-r["score"], -r["score_cosseno"], -r["score_lexical"], r["asset_id"])
        )
        return resultados[: int(top_k)]
