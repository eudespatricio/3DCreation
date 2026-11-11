"""locks: helpers de diagnostico, sem tocar na exclusividade garantida pelo flock."""

from __future__ import annotations

import os

import pytest

from forge3d import locks


def test_pid_ativo_reconhece_o_proprio_processo():
    assert locks.pid_ativo(os.getpid()) is True


def test_pid_ativo_rejeita_pid_invalido():
    assert locks.pid_ativo(0) is False
    assert locks.pid_ativo(-1) is False


def test_pid_ativo_com_pid_inexistente():
    assert locks.pid_ativo(999_999_999) is False


def test_vram_sem_nvidia_smi_devolve_none(monkeypatch):
    monkeypatch.setattr(locks.shutil, "which", lambda _nome: None)
    assert locks.vram_livre_mb() is None


def test_lock_gpu_recusa_concorrencia(tmp_path, monkeypatch):
    """D11: o segundo job nao pode entrar enquanto o primeiro segura o lock."""
    monkeypatch.setattr(locks, "caminho_lock", lambda: tmp_path / "gpu.lock")
    with locks.lock_gpu("run-a"):
        with pytest.raises((Exception, SystemExit)):
            with locks.lock_gpu("run-b", esperar=False):
                pass


def test_lock_gpu_libera_ao_sair(tmp_path, monkeypatch):
    monkeypatch.setattr(locks, "caminho_lock", lambda: tmp_path / "gpu.lock")
    with locks.lock_gpu("run-a"):
        pass
    with locks.lock_gpu("run-b"):
        pass
