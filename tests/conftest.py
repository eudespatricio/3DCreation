"""Fixtures: sandbox hermetico por teste.

Cada teste roda com ``HOME`` falso, entao o estado do Forge3D, a allowlist e o destino do exemplo
ficam dentro do ``tmp_path``. Nada toca a maquina do operador e nada enxerga outro projeto.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]


def _ambiente(home: Path) -> dict:
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["XDG_STATE_HOME"] = str(home / ".local" / "state")
    env["XDG_CONFIG_HOME"] = str(home / ".config")
    env["FORGE3D_ROOT"] = str(RAIZ)
    env.pop("FORGE3D_HOME", None)
    env.pop("FORGE3D_CONFIG", None)
    env.pop("PYTHONPATH", None)
    return env


@pytest.fixture()
def sandbox(tmp_path: Path) -> dict:
    home = tmp_path / "home"
    home.mkdir()
    return {
        "home": home,
        "env": _ambiente(home),
        "state": home / ".local" / "state" / "forge3d",
        "tmp": tmp_path,
    }


def rodar(args: list[str], sandbox: dict, esperar_json: bool = False):
    """Executa a CLI num processo novo. Devolve ``(exit_code, stdout)``."""
    cmd = [sys.executable, "-m", "forge3d.cli.main", *args]
    proc = subprocess.run(
        cmd, cwd=str(RAIZ), env=sandbox["env"], capture_output=True, text=True, timeout=900
    )
    saida = proc.stdout
    if esperar_json:
        try:
            saida = json.loads(proc.stdout)
        except ValueError:
            raise AssertionError(
                f"stdout nao e JSON (exit {proc.returncode}):\nSTDOUT={proc.stdout}\nSTDERR={proc.stderr}"
            ) from None
    return proc.returncode, saida


@pytest.fixture()
def rodar_cli(sandbox):
    def _rodar(args: list[str], esperar_json: bool = False):
        return rodar(args, sandbox, esperar_json)

    return _rodar
