#!/usr/bin/env python3
"""Sincronizador e semeador do Vault CC0 (malhas 3D kitbash e texturas PBR) — I7/D18.

Ingere ativos locais sob licenca comercial limpa (``CC0-1.0``, ``CC0``, ``Public Domain``,
``MIT``), valida SHA256 em disco, gera pecas procedurais manifold CC0 e calcula vetores
``gemini-embedding-2-preview`` (ou vetores deterministicos offline).

Uso:
    python tools/vault_sync_cc0.py --seed-local [--vault-dir <dir>] [--embed] [--verify] [--json]
    python tools/vault_sync_cc0.py --manifest <manifest.json> [--vault-dir <dir>] [--json]
    python tools/vault_sync_cc0.py --query "forged steel blade" [--vault-dir <dir>] [--json]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

RAIZ_REPO = Path(__file__).resolve().parents[1]
if str(RAIZ_REPO / "src") not in sys.path:
    sys.path.insert(0, str(RAIZ_REPO / "src"))

from forge3d.errors import ForgeError  # noqa: E402
from forge3d.providers import cloud_ai  # noqa: E402
from forge3d.vault import VaultCC0, normalizar_vetor_l2, validar_licenca_cc0  # noqa: E402

CATALOGO_TEXTURAS_LOCAIS: tuple[dict[str, Any], ...] = (
    {
        "arquivo": "bronze_filigree_albedo.png",
        "asset_id": "pbr.bronze_filigree_albedo",
        "nome": "Bronze Filigree Albedo",
        "tipo": "pbr_texture",
        "categoria": "material",
        "licenca": "CC0-1.0",
        "origem": "forge3d_procedural_cc0",
        "tags": ["bronze", "filigree", "gold", "ouro", "ornate", "guard", "pommel", "metal", "pbr"],
        "descricao": "Textura PBR CC0 de bronze ornamentado com filigrana dourada para guardas e pomos.",
    },
    {
        "arquivo": "leather_saddle_albedo.png",
        "asset_id": "pbr.leather_saddle_albedo",
        "nome": "Leather Saddle Albedo",
        "tipo": "pbr_texture",
        "categoria": "material",
        "licenca": "CC0-1.0",
        "origem": "forge3d_procedural_cc0",
        "tags": ["leather", "couro", "saddle", "grip", "handle", "cabo", "punho", "strap", "pbr"],
        "descricao": "Textura PBR CC0 de couro gasto para cabos cilindricos, correias e selas.",
    },
    {
        "arquivo": "linen_tunic_albedo.png",
        "asset_id": "pbr.linen_tunic_albedo",
        "nome": "Linen Tunic Albedo",
        "tipo": "pbr_texture",
        "categoria": "material",
        "licenca": "CC0-1.0",
        "origem": "forge3d_procedural_cc0",
        "tags": ["linen", "cloth", "tecido", "tunic", "wrap", "cape", "pbr"],
        "descricao": "Textura PBR CC0 de linho tecido para tunicas, faixas de punho e capas.",
    },
    {
        "arquivo": "steel_forged_albedo.png",
        "asset_id": "pbr.steel_forged_albedo",
        "nome": "Steel Forged Albedo",
        "tipo": "pbr_texture",
        "categoria": "material",
        "licenca": "CC0-1.0",
        "origem": "forge3d_procedural_cc0",
        "tags": ["steel", "aco", "forged", "forjado", "blade", "lamina", "sword", "armor", "metal", "pbr"],
        "descricao": "Textura PBR CC0 de aco forjado temperado para laminas de espada e placas de armadura.",
    },
    {
        "arquivo": "obsidian_runestone_albedo.png",
        "asset_id": "pbr.obsidian_runestone_albedo",
        "nome": "Obsidian Runestone Albedo",
        "tipo": "pbr_texture",
        "categoria": "material",
        "licenca": "CC0-1.0",
        "origem": "forge3d_procedural_cc0",
        "tags": ["obsidian", "runestone", "stone", "pedra", "rune", "basalt", "altar", "pbr"],
        "descricao": "Textura PBR 1024x1024 de obsidiana gravada com runas arcanas para monólitos e altares.",
    },
    {
        "arquivo": "arcane_crystal_albedo.png",
        "asset_id": "pbr.arcane_crystal_albedo",
        "nome": "Arcane Crystal Albedo",
        "tipo": "pbr_texture",
        "categoria": "material",
        "licenca": "CC0-1.0",
        "origem": "forge3d_procedural_cc0",
        "tags": ["crystal", "cristal", "arcane", "arcano", "gem", "gema", "orb", "magic", "pbr"],
        "descricao": "Textura PBR 1024x1024 de cristal arcano facetado para nucleos, gemas e cetros.",
    },
)

CATALOGO_PECAS_KITBASH_CC0: tuple[dict[str, Any], ...] = (
    {
        "asset_id": "kb.cylindrical_grip",
        "arquivo": "kb_cylindrical_grip.glb",
        "nome": "Cylindrical Weapon Grip",
        "tipo": "kitbash_part",
        "categoria": "weapon",
        "licenca": "CC0-1.0",
        "origem": "forge3d_procedural_cc0",
        "tags": ["grip", "handle", "cabo", "punho", "cylinder", "leather", "couro", "sword", "espada", "base"],
        "descricao": "Cabo cilindrico anatomico CC0 para empunhadura de espadas, machados e cetros.",
        "aneis": [
            (0.00, 0.052, 0.048),
            (0.08, 0.046, 0.044),
            (0.18, 0.048, 0.045),
            (0.28, 0.046, 0.044),
            (0.36, 0.052, 0.048),
        ],
        "segmentos": 12,
        "cor_rgba": (0.48, 0.33, 0.22, 1.0),
    },
    {
        "asset_id": "kb.crossguard",
        "arquivo": "kb_crossguard.glb",
        "nome": "Ornate Bronze Crossguard",
        "tipo": "kitbash_part",
        "categoria": "weapon",
        "licenca": "CC0-1.0",
        "origem": "forge3d_procedural_cc0",
        "tags": ["guard", "crossguard", "guarda", "hilt", "bronze", "gold", "ouro", "sword", "espada"],
        "descricao": "Guarda-mao cruzada simetrica CC0 em bronze ornamentado para espadas.",
        "aneis": [
            (0.00, 0.14, 0.065),
            (0.03, 0.22, 0.075),
            (0.09, 0.22, 0.075),
            (0.12, 0.14, 0.065),
        ],
        "segmentos": 8,
        "cor_rgba": (0.76, 0.60, 0.34, 1.0),
    },
    {
        "asset_id": "kb.sword_blade",
        "arquivo": "kb_sword_blade.glb",
        "nome": "Forged Steel Broadsword Blade",
        "tipo": "kitbash_part",
        "categoria": "weapon",
        "licenca": "CC0-1.0",
        "origem": "forge3d_procedural_cc0",
        "tags": ["blade", "lamina", "sword", "espada", "steel", "aco", "forged", "weapon", "arma"],
        "descricao": "Lamina larga chanfrada de aco forjado CC0 com geometria 100% manifold.",
        "aneis": [
            (0.00, 0.115, 0.048),
            (0.22, 0.110, 0.045),
            (0.48, 0.095, 0.040),
            (0.66, 0.065, 0.032),
            (0.76, 0.025, 0.018),
        ],
        "segmentos": 8,
        "cor_rgba": (0.66, 0.70, 0.75, 1.0),
    },
    {
        "asset_id": "kb.pommel_stone",
        "arquivo": "kb_pommel_stone.glb",
        "nome": "Faceted Counterweight Pommel",
        "tipo": "kitbash_part",
        "categoria": "weapon",
        "licenca": "CC0-1.0",
        "origem": "forge3d_procedural_cc0",
        "tags": ["pommel", "pomo", "counterweight", "bronze", "stone", "gem", "sword", "espada", "hilt"],
        "descricao": "Pomo facetado CC0 de contrapeso para base de empunhadura.",
        "aneis": [
            (0.00, 0.045, 0.045),
            (0.04, 0.080, 0.075),
            (0.09, 0.080, 0.075),
            (0.13, 0.045, 0.045),
        ],
        "segmentos": 8,
        "cor_rgba": (0.72, 0.56, 0.32, 1.0),
    },
)


def construir_glb_revolucao_manifold(
    caminho_glb: Path,
    *,
    aneis: list[tuple[float, float, float]],
    segmentos: int = 8,
    cor_rgba: tuple[float, float, float, float] = (0.65, 0.68, 0.72, 1.0),
    nome_malha: str = "kitbash_part",
) -> Path:
    """Gera um arquivo binario ``.glb`` (glTF 2.0) fechado e 100% manifold sem depender de GPU.

    No glTF 2.0 o eixo vertical e ``+Y`` (que o Blender converte para ``+Z`` ao importar).
    Cada aresta e compartilhada por exatamente 2 triangulos com orientacao consistente.
    """
    n_seg = max(4, int(segmentos))
    if len(aneis) < 2:
        raise ValueError("aneis deve conter pelo menos 2 niveis (y, rx, rz)")

    y_min = float(aneis[0][0])
    y_max = float(aneis[-1][0])
    alt = max(1e-4, y_max - y_min)
    y_polo_inf = y_min - 0.02 * alt
    y_polo_sup = y_max + 0.02 * alt

    vertices: list[tuple[float, float, float]] = [(0.0, y_polo_inf, 0.0)]
    normais: list[tuple[float, float, float]] = [(0.0, -1.0, 0.0)]

    for y_val, rx, rz in aneis:
        for k in range(n_seg):
            ang = (2.0 * math.pi * k) / float(n_seg)
            ca = math.cos(ang)
            sa = math.sin(ang)
            vx = float(rx) * ca
            vy = float(y_val)
            vz = float(rz) * sa
            vertices.append((vx, vy, vz))
            nx = ca / max(1e-4, float(rx))
            nz = sa / max(1e-4, float(rz))
            nl = math.hypot(nx, nz) or 1.0
            normais.append((nx / nl, 0.0, nz / nl))

    idx_topo = len(vertices)
    vertices.append((0.0, y_polo_sup, 0.0))
    normais.append((0.0, 1.0, 0.0))

    indices: list[int] = []
    # Calota inferior (polo 0)
    for k in range(n_seg):
        k_next = (k + 1) % n_seg
        indices.extend([0, 1 + k, 1 + k_next])

    # Faixas laterais entre aneis
    n_aneis = len(aneis)
    for r in range(n_aneis - 1):
        base0 = 1 + r * n_seg
        base1 = 1 + (r + 1) * n_seg
        for k in range(n_seg):
            k_next = (k + 1) % n_seg
            i00 = base0 + k
            i01 = base0 + k_next
            i10 = base1 + k
            i11 = base1 + k_next
            indices.extend([i00, i10, i11])
            indices.extend([i00, i11, i01])

    # Calota superior (polo idx_topo)
    base_ult = 1 + (n_aneis - 1) * n_seg
    for k in range(n_seg):
        k_next = (k + 1) % n_seg
        indices.extend([idx_topo, base_ult + k_next, base_ult + k])

    pos_bytes = b"".join(struct.pack("<3f", *v) for v in vertices)
    norm_bytes = b"".join(struct.pack("<3f", *n) for n in normais)
    idx_bytes = b"".join(struct.pack("<H", idx) for idx in indices)
    while len(idx_bytes) % 4 != 0:
        idx_bytes += b"\x00"

    xs = [v[0] for v in vertices]
    ys = [v[1] for v in vertices]
    zs = [v[2] for v in vertices]

    bin_blob = pos_bytes + norm_bytes + idx_bytes
    while len(bin_blob) % 4 != 0:
        bin_blob += b"\x00"

    off_pos = 0
    len_pos = len(pos_bytes)
    off_norm = len_pos
    len_norm = len(norm_bytes)
    off_idx = off_norm + len_norm
    len_idx_raw = len(indices) * 2

    gltf_dict: dict[str, Any] = {
        "asset": {"version": "2.0", "generator": "Forge3D VaultCC0 Manifold Builder"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"name": nome_malha, "mesh": 0}],
        "materials": [
            {
                "name": f"{nome_malha}_mat",
                "pbrMetallicRoughness": {
                    "baseColorFactor": [float(c) for c in cor_rgba],
                    "metallicFactor": 0.45,
                    "roughnessFactor": 0.55,
                },
            }
        ],
        "meshes": [
            {
                "name": nome_malha,
                "primitives": [
                    {
                        "attributes": {"POSITION": 0, "NORMAL": 1},
                        "indices": 2,
                        "material": 0,
                        "mode": 4,
                    }
                ],
            }
        ],
        "buffers": [{"byteLength": len(bin_blob)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": off_pos, "byteLength": len_pos, "target": 34962},
            {"buffer": 0, "byteOffset": off_norm, "byteLength": len_norm, "target": 34962},
            {"buffer": 0, "byteOffset": off_idx, "byteLength": len_idx_raw, "target": 34963},
        ],
        "accessors": [
            {
                "bufferView": 0,
                "byteOffset": 0,
                "componentType": 5126,
                "count": len(vertices),
                "type": "VEC3",
                "min": [min(xs), min(ys), min(zs)],
                "max": [max(xs), max(ys), max(zs)],
            },
            {
                "bufferView": 1,
                "byteOffset": 0,
                "componentType": 5126,
                "count": len(normais),
                "type": "VEC3",
            },
            {
                "bufferView": 2,
                "byteOffset": 0,
                "componentType": 5123,
                "count": len(indices),
                "type": "SCALAR",
            },
        ],
    }

    json_bytes = json.dumps(gltf_dict, separators=(",", ":")).encode("utf-8")
    while len(json_bytes) % 4 != 0:
        json_bytes += b" "

    total_len = 12 + 8 + len(json_bytes) + 8 + len(bin_blob)
    header = struct.pack("<4sII", b"glTF", 2, total_len)
    chunk_json = struct.pack("<II", len(json_bytes), 0x4E4F534A) + json_bytes
    chunk_bin = struct.pack("<II", len(bin_blob), 0x004E4942) + bin_blob

    caminho_glb.parent.mkdir(parents=True, exist_ok=True)
    caminho_glb.write_bytes(header + chunk_json + chunk_bin)
    return caminho_glb


def embedding_deterministico_offline(texto: str, dimensao: int = 64) -> list[float]:
    """Gera vetor unitario deterministico offline baseado em tokens para testes sem chave cloud."""
    dim = max(8, int(dimensao))
    acum = [0.0] * dim
    palavras = [p.strip().lower() for p in (texto or "").replace(".", " ").replace("_", " ").split() if p.strip()]
    if not palavras:
        palavras = ["cc0"]
    for pal in palavras:
        digest = hashlib.sha256(pal.encode("utf-8")).digest()
        for i in range(dim):
            b = digest[i % len(digest)]
            sinal = 1.0 if (b & 1) == 0 else -1.0
            mag = ((b >> 1) / 127.0) + 0.1
            acum[i] += sinal * mag
    return normalizar_vetor_l2(acum)


def gerar_pecas_kitbash_Via_blender_json(pasta_destino: Path) -> list[str]:
    """Opcional: valida/regenera GLBs no Blender 4.2 via JSON job em disco (I9)."""
    bl_bin = shutil.which("blender")
    if not bl_bin:
        return []
    pasta_destino.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="forge3d_vault_bl_") as tmp:
        job_in = Path(tmp) / "job_in.json"
        job_out = Path(tmp) / "job_out.json"
        script_bl = Path(tmp) / "verify_glbs.py"
        alvos = [str(pasta_destino / p["arquivo"]) for p in CATALOGO_PECAS_KITBASH_CC0]
        job_in.write_text(json.dumps({"arquivos": alvos}), encoding="utf-8")
        script_bl.write_text(
            "import json, sys, bpy\n"
            "argv = sys.argv[sys.argv.index('--') + 1:]\n"
            "dados = json.loads(open(argv[0], encoding='utf-8').read())\n"
            "verificados = []\n"
            "for arq in dados.get('arquivos', []):\n"
            "    bpy.ops.wm.read_factory_settings(use_empty=True)\n"
            "    bpy.ops.import_scene.gltf(filepath=arq)\n"
            "    verificados.append(arq)\n"
            "open(argv[1], 'w', encoding='utf-8').write(json.dumps({'ok': True, 'verificados': verificados}))\n",
            encoding="utf-8",
        )
        subprocess.run(
            [bl_bin, "--background", "--factory-startup", "--python", str(script_bl), "--", str(job_in), str(job_out)],
            check=False,
            capture_output=True,
            timeout=90,
        )
        if job_out.is_file():
            res = json.loads(job_out.read_text(encoding="utf-8"))
            return list(res.get("verificados", []))
    return []


def seed_local_cc0(
    vault: VaultCC0,
    *,
    gerar_embeddings: bool = False,
    dimensao_embedding: int = 64,
    usar_blender: bool = False,
) -> dict[str, Any]:
    """Semeia o Vault com as texturas PBR CC0 do repo e as pecas procedurais de kitbash CC0."""
    registrados: list[dict[str, Any]] = []
    dir_tex = RAIZ_REPO / "blender" / "textures_pbr"

    for spec_tex in CATALOGO_TEXTURAS_LOCAIS:
        caminho_tex = dir_tex / spec_tex["arquivo"]
        if not caminho_tex.is_file():
            continue
        ativo = vault.registrar_ativo(
            asset_id=spec_tex["asset_id"],
            caminho=caminho_tex,
            tipo=spec_tex["tipo"],
            categoria=spec_tex["categoria"],
            licenca=spec_tex["licenca"],
            origem=spec_tex["origem"],
            nome=spec_tex["nome"],
            descricao=spec_tex["descricao"],
            tags=spec_tex["tags"],
        )
        registrados.append(ativo)

    dir_pecas = vault.vault_dir / "kitbash_parts"
    dir_pecas.mkdir(parents=True, exist_ok=True)
    for spec_peca in CATALOGO_PECAS_KITBASH_CC0:
        caminho_glb = dir_pecas / spec_peca["arquivo"]
        construir_glb_revolucao_manifold(
            caminho_glb,
            aneis=list(spec_peca["aneis"]),
            segmentos=int(spec_peca["segmentos"]),
            cor_rgba=tuple(spec_peca["cor_rgba"]),
            nome_malha=spec_peca["asset_id"].replace(".", "_"),
        )
        ativo = vault.registrar_ativo(
            asset_id=spec_peca["asset_id"],
            caminho=caminho_glb,
            tipo=spec_peca["tipo"],
            categoria=spec_peca["categoria"],
            licenca=spec_peca["licenca"],
            origem=spec_peca["origem"],
            nome=spec_peca["nome"],
            descricao=spec_peca["descricao"],
            tags=spec_peca["tags"],
            metadados={"manifold": True, "procedimento": "revolucao_fechada_cc0"},
        )
        registrados.append(ativo)

    if usar_blender:
        gerar_pecas_kitbash_Via_blender_json(dir_pecas)

    embeddings_gerados = 0
    if gerar_embeddings:
        embeddings_gerados = sincronizar_embeddings_vault(vault, dimensao_offline=dimensao_embedding)

    return {
        "ok": True,
        "vault_dir": str(vault.vault_dir),
        "total_registrados": len(registrados),
        "ativos": [a["asset_id"] for a in registrados],
        "embeddings_gerados": embeddings_gerados,
    }


def ingerir_manifesto_cc0(
    vault: VaultCC0,
    caminho_manifesto: Path,
    *,
    gerar_embeddings: bool = False,
) -> dict[str, Any]:
    """Ingere ativos descritos em um arquivo JSON de manifesto, aplicando o gate I7/D18."""
    arq = Path(caminho_manifesto)
    if not arq.is_file():
        raise FileNotFoundError(f"manifesto nao encontrado: {arq}")

    bruto = json.loads(arq.read_text(encoding="utf-8"))
    if isinstance(bruto, dict):
        itens = bruto.get("assets") or bruto.get("ativos") or []
    elif isinstance(bruto, list):
        itens = bruto
    else:
        raise ValueError("manifesto deve ser lista ou objeto com chave 'assets'")

    registrados: list[str] = []
    for item in itens:
        if not isinstance(item, dict):
            continue
        lic = str(item.get("licenca") or "")
        orig = str(item.get("origem") or "local_cc0")
        mod = str(item.get("modelo") or "")
        validar_licenca_cc0(lic, origem=orig, modelo=mod)

        caminho_raw = Path(str(item["caminho"]))
        if not caminho_raw.is_absolute():
            caminho_raw = (arq.parent / caminho_raw).resolve()

        emb = item.get("embedding")
        ativo = vault.registrar_ativo(
            asset_id=str(item["asset_id"]),
            caminho=caminho_raw,
            tipo=str(item.get("tipo") or "mesh"),
            categoria=str(item.get("categoria") or "prop"),
            licenca=lic,
            origem=orig,
            nome=str(item.get("nome") or ""),
            descricao=str(item.get("descricao") or ""),
            tags=list(item.get("tags") or []),
            modelo=mod,
            metadados=dict(item.get("metadados") or {}),
            embedding=list(emb) if isinstance(emb, list) else None,
        )
        registrados.append(ativo["asset_id"])

    if gerar_embeddings:
        sincronizar_embeddings_vault(vault)

    return {
        "ok": True,
        "manifesto": str(arq),
        "total_registrados": len(registrados),
        "ativos": registrados,
    }


def sincronizar_embeddings_vault(
    vault: VaultCC0,
    *,
    dimensao_offline: int = 64,
) -> int:
    """Gera e persiste embeddings para todos os ativos do Vault (Gemini online ou fallback deterministico)."""
    ativos = vault.listar_ativos()
    ok_gem, _ = cloud_ai.gemini_disponivel()
    total = 0
    for ativo in ativos:
        texto_doc = " ".join(
            [
                ativo["asset_id"],
                ativo["nome"],
                ativo["tipo"],
                ativo["categoria"],
                " ".join(ativo.get("tags", [])),
                ativo.get("descricao", ""),
            ]
        ).strip()
        vetor: list[float] | None = None
        modelo_emb = cloud_ai.MODELO_GEMINI_EMBEDDING_PADRAO
        if ok_gem:
            try:
                vetor = cloud_ai.gerar_embedding_gemini(
                    texto_doc,
                    task_type="RETRIEVAL_DOCUMENT",
                )
            except Exception:
                vetor = None
        if vetor is None:
            vetor = embedding_deterministico_offline(texto_doc, dimensao=dimensao_offline)
            modelo_emb = "offline-sha256-embedding"

        vault.registrar_embedding(ativo["asset_id"], vetor, modelo=modelo_emb)
        total += 1
    return total


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Sincronizador do Vault CC0 (malhas 3D, texturas PBR, SHA256 e embeddings)"
    )
    parser.add_argument("--seed-local", action="store_true", help="Ingere texturas PBR e pecas kitbash CC0 locais")
    parser.add_argument("--manifest", type=Path, default=None, help="Arquivo JSON de manifesto para ingestao")
    parser.add_argument("--query", default="", help="Executa busca semantica/lexical no Vault")
    parser.add_argument("--top-k", type=int, default=5, help="Numero maximo de resultados em --query")
    parser.add_argument("--embed", action="store_true", help="Gera e armazena embeddings para os ativos")
    parser.add_argument("--verify", action="store_true", help="Valida integridade SHA256 e licencas (I7/D18)")
    parser.add_argument("--vault-dir", type=Path, default=None, help="Diretorio do Vault (padrao: raiz_estado/vault)")
    parser.add_argument("--json", action="store_true", dest="em_json", help="Imprime saida em formato JSON")
    args = parser.parse_args(argv)

    try:
        vault = VaultCC0(args.vault_dir)
        relatorio: dict[str, Any] = {"ok": True, "vault_dir": str(vault.vault_dir)}

        if args.seed_local:
            relatorio["seed"] = seed_local_cc0(vault, gerar_embeddings=args.embed)
        if args.manifest is not None:
            relatorio["manifest"] = ingerir_manifesto_cc0(
                vault,
                args.manifest,
                gerar_embeddings=args.embed,
            )
        if args.embed and not args.seed_local and args.manifest is None:
            relatorio["embeddings_atualizados"] = sincronizar_embeddings_vault(vault)
        if args.verify:
            verif = vault.validar_integridade(levantar=True)
            relatorio["integridade"] = verif
        if args.query.strip():
            relatorio["resultados"] = vault.buscar_semantico(args.query.strip(), top_k=args.top_k)

        if not any([args.seed_local, args.manifest is not None, args.embed, args.verify, bool(args.query.strip())]):
            relatorio["ativos"] = vault.listar_ativos()
    except ForgeError as exc:
        if args.em_json:
            print(json.dumps({"ok": False, "codigo": exc.codigo, "erro": exc.mensagem}, ensure_ascii=False))
        else:
            print(f"[{exc.codigo}] {exc.mensagem}", file=sys.stderr)
        return exc.exit_code
    except Exception as exc:
        if args.em_json:
            print(json.dumps({"ok": False, "erro": str(exc)}, ensure_ascii=False))
        else:
            print(f"FAIL: {exc}", file=sys.stderr)
        return 2

    if args.em_json:
        print(json.dumps(relatorio, indent=2, ensure_ascii=False))
    else:
        print(f"VAULT_OK {vault.vault_dir}")
        if "resultados" in relatorio:
            for r in relatorio["resultados"]:
                print(f"  - {r['asset_id']} (score={r['score']:.4f}, metodo={r['metodo_busca']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
