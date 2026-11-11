"""Testes do gc: remove antigos, preserva recentes, publicado e ledger."""

from __future__ import annotations

import os
import time

import pytest

from forge3d import gc, paths
from forge3d.errors import ForgeError


def _envelhecer(p, dias: int) -> None:
    ts = time.time() - dias * 86400
    os.utime(p, (ts, ts))


def test_gc_remove_antigos_e_preserva_recentes(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE3D_HOME", str(tmp_path))

    velho_cache = paths.dir_cache() / "cache-velho"
    velho_cache.mkdir(parents=True)
    (velho_cache / "a.bin").write_bytes(b"x" * 128)
    novo_cache = paths.dir_cache() / "cache-novo"
    novo_cache.mkdir()

    velho_run = paths.dir_runs() / "run-velho"
    velho_run.mkdir(parents=True)
    (velho_run / "relatorio.json").write_text("{}", encoding="utf-8")

    velho_staging = paths.dir_staging() / "run-velho"
    velho_staging.mkdir(parents=True)
    (velho_staging / "modelo.glb").write_bytes(b"y" * 64)

    publicado = paths.dir_saida() / "asset-publicado"
    publicado.mkdir(parents=True)
    (publicado / "asset.glb").write_bytes(b"z" * 32)

    for p in (velho_cache, velho_run, velho_staging, publicado):
        _envelhecer(p, 40)

    seco = gc.executar(30, aplicar=False)
    assert seco["total"] == 3
    assert seco["bytes"] > 0
    assert velho_cache.exists()
    assert velho_run.exists()
    assert velho_staging.exists()

    feito = gc.executar(30, aplicar=True)
    assert feito["total"] == 3
    assert all(a["removido"] for a in feito["alvos"])
    assert not velho_cache.exists()
    assert not velho_run.exists()
    assert not velho_staging.exists()
    assert novo_cache.exists()
    assert publicado.exists()
    assert (publicado / "asset.glb").is_file()


def test_gc_recusa_manter_dias_invalido():
    with pytest.raises(ForgeError) as exc:
        gc.executar(0, aplicar=False)
    assert exc.value.codigo == "FORGE-E-SPEC"
