"""Teste de atomicidade do publish (GAP-014, docs/gaps.md, I3).

Verifica que:
1. Nenhum arquivo parcial aparece no destino enquanto a publicacao esta em andamento;
2. Arquivos entram por rename atomico no mesmo filesystem (staging .tmp -> destino);
3. O manifesto e o ultimo a ser publicado, garantindo completude do asset;
4. Falha durante a copia nao deixa arquivo sob o nome final no destino.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import threading
import time
from pathlib import Path

import pytest

from forge3d.publish import publicar


def _criar_dados_teste(tmp_path: Path):
    staging = tmp_path / "staging"
    staging.mkdir()
    destino = tmp_path / "destino"

    # Criar arquivos de teste com conteudo conhecido
    dados_mesh = b"MESH_GLB_BYTES_TESTE_" * 10000  # ~220 KB
    dados_tex = b"TEXTURE_PNG_BYTES_TESTE_" * 5000  # ~120 KB

    (staging / "mesh.glb").write_bytes(dados_mesh)
    (staging / "texture.png").write_bytes(dados_tex)

    h_mesh = hashlib.sha256(dados_mesh).hexdigest()
    h_tex = hashlib.sha256(dados_tex).hexdigest()

    manifesto = {
        "schema": "forge3d/manifest@1",
        "asset_id": "asset.teste.atomico",
        "projeto": "demo",
        "perfil": "godot4",
        "rota": "blocky",
        "determinism": "D1",
        "pipeline_version": "0.1.0",
        "spec_hash": "a" * 64,
        "created_at": "2026-11-10T00:00:00Z",
        "geometry": {"triangulos": 120, "materiais": 1},
        "licenca": {"modelo": "CC0-1.0", "uso_comercial": True, "notice": "none"},
        "files": [
            {"caminho": "mesh.glb", "papel": "mesh", "sha256": h_mesh, "bytes": len(dados_mesh)},
            {"caminho": "texture.png", "papel": "textura", "sha256": h_tex, "bytes": len(dados_tex)},
        ],
        "qc": {"aprovado": True, "gates": []},
    }

    tamanhos = {
        "mesh.glb": len(dados_mesh),
        "texture.png": len(dados_tex),
    }

    return staging, destino, manifesto, tamanhos


def test_observador_thread_durante_publish_sem_arquivos_parciais(tmp_path, monkeypatch):
    """Thread observadora vigia o destino continuamente durante o publish.

    Garante que nenhum arquivo final aparece incompleto (0 < bytes < total)
    e que o manifesto so surge quando todos os arquivos estao integros.
    """
    monkeypatch.setenv("FORGE3D_HOME", str(tmp_path / "state"))
    staging, destino, manifesto, tamanhos = _criar_dados_teste(tmp_path)

    # Injeta um pequeno atraso artificial no copyfileobj para permitir centenas
    # de observacoes durante o fluxo de publicacao sem alterar a logica.
    def slow_copy(fsrc, fdst, length=0):
        # Le e grava em pequenos blocos com mini-pausa
        while True:
            bloco = fsrc.read(4096)
            if not bloco:
                break
            fdst.write(bloco)
            time.sleep(0.001)

    monkeypatch.setattr(shutil, "copyfileobj", slow_copy)

    violacoes: list[str] = []
    observacoes = 0
    parar_observador = threading.Event()

    def observar():
        nonlocal observacoes
        while not parar_observador.is_set():
            observacoes += 1
            if destino.is_dir():
                try:
                    itens = os.listdir(destino)
                except OSError:
                    continue

                for item in itens:
                    caminho = destino / item
                    # Arquivos temporarios comecam com '.'
                    if item.startswith("."):
                        continue

                    # Se e um dos arquivos publicados finais
                    if item in tamanhos:
                        esperado = tamanhos[item]
                        try:
                            tamanho_atual = caminho.stat().st_size
                            if tamanho_atual < esperado:
                                violacoes.append(
                                    f"Arquivo parcial detectado: {item} tem {tamanho_atual}B, esperado {esperado}B"
                                )
                        except OSError:
                            pass

                    # Se o manifesto final apareceu, todos os arquivos devem estar completos
                    if item.endswith(".manifest.json"):
                        for arq_final, tam_esperado in tamanhos.items():
                            p_final = destino / arq_final
                            if not p_final.is_file():
                                violacoes.append(
                                    f"Manifesto presente mas {arq_final} ainda ausente no destino"
                                )
                            elif p_final.stat().st_size != tam_esperado:
                                violacoes.append(
                                    f"Manifesto presente mas {arq_final} incompleto ({p_final.stat().st_size}B != {tam_esperado}B)"
                                )
            time.sleep(0.0005)

    thread_obs = threading.Thread(target=observar, daemon=True)
    thread_obs.start()

    try:
        publicados = publicar(staging, destino, manifesto, "run-teste-obs-01")
    finally:
        parar_observador.set()
        thread_obs.join(timeout=2.0)

    assert observacoes >= 10, f"Observador rodou poucas vezes: {observacoes}"
    assert len(violacoes) == 0, f"Violacoes de atomicidade observadas: {violacoes}"
    assert len(publicados) == 2

    # Verifica integridade final
    for arq in manifesto["files"]:
        final = destino / arq["caminho"]
        assert final.is_file()
        assert final.stat().st_size == arq["bytes"]
    assert (destino / f"{manifesto['asset_id']}.manifest.json").is_file()


def test_publicar_remove_arquivo_que_saiu_do_manifesto(tmp_path):
    """Um LOD que deixou de ser gerado nao pode ficar orfao no destino (medido no android)."""
    staging, destino, manifesto, _tamanhos = _criar_dados_teste(tmp_path)
    publicar(staging, destino, manifesto, "run-1")
    (staging / "antigo_LOD2.glb").write_bytes(b"sobra")
    manifesto["files"].append(
        {
            "caminho": "antigo_LOD2.glb",
            "papel": "lod",
            "sha256": "sha256:" + "0" * 64,
            "bytes": 5,
        }
    )
    publicar(staging, destino, manifesto, "run-2")
    extra = destino / "antigo_LOD2.glb"
    assert extra.is_file()

    manifesto["files"] = [a for a in manifesto["files"] if a["caminho"] != "antigo_LOD2.glb"]
    publicar(staging, destino, manifesto, "run-3")
    assert not extra.exists()


def test_interceptacao_rename_destino_vazio_antes_do_replace(tmp_path, monkeypatch):
    """Intercepta os.replace provando que o destino nao existe antes do rename."""
    monkeypatch.setenv("FORGE3D_HOME", str(tmp_path / "state"))
    staging, destino, manifesto, tamanhos = _criar_dados_teste(tmp_path)

    replaces: list[dict] = []
    orig_replace = os.replace

    def spy_replace(src, dst):
        src_path = Path(src)
        dst_path = Path(dst)
        replaces.append({
            "src_name": src_path.name,
            "dst_name": dst_path.name,
            "dst_existia_antes": dst_path.exists(),
            "src_completo": src_path.stat().st_size > 0,
            "src_size": src_path.stat().st_size,
        })
        return orig_replace(src, dst)

    monkeypatch.setattr(os, "replace", spy_replace)

    publicados = publicar(staging, destino, manifesto, "run-teste-spy-01")

    assert len(replaces) == 3  # 2 arquivos + 1 manifesto
    for r in replaces:
        assert not r["dst_existia_antes"], f"Destino {r['dst_name']} ja existia antes do rename!"
        assert r["src_completo"], f"Origem temporaria {r['src_name']} estava vazia no rename!"

    # O manifesto deve ser o ultimo rename
    assert replaces[-1]["dst_name"] == f"{manifesto['asset_id']}.manifest.json"
    assert len(publicados) == 2


def test_falha_no_meio_do_publish_nao_deixa_arquivo_no_destino(tmp_path, monkeypatch):
    """Simula erro durante a copia do primeiro arquivo e verifica ausencia de arquivo final."""
    monkeypatch.setenv("FORGE3D_HOME", str(tmp_path / "state"))
    staging, destino, manifesto, _ = _criar_dados_teste(tmp_path)

    def erro_copia(fsrc, fdst, length=0):
        fdst.write(b"parcial...")
        raise IOError("Falha simulada de disco/IO")

    monkeypatch.setattr(shutil, "copyfileobj", erro_copia)

    with pytest.raises(IOError, match="Falha simulada"):
        publicar(staging, destino, manifesto, "run-teste-falha-01")

    # O arquivo final 'mesh.glb' NUNCA deve existir no destino
    assert not (destino / "mesh.glb").exists()
    assert not (destino / f"{manifesto['asset_id']}.manifest.json").exists()
