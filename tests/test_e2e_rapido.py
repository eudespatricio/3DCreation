"""End-to-end rapido: um item, ciclo completo, sem GPU. Alvo: < 30 s.

Este e o "teste minoritario" da transicao: prova validate -> plan -> run -> verify -> cache em um
asset so. A suite completa continua em tests/invariants/ (3 itens, ~75 s).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]

pytestmark = [pytest.mark.blender, pytest.mark.rapido]

SPEC = """schema: forge3d/spec@1
projeto: demo
perfil: godot4
destino_exportacao: ~/.local/state/forge3d/saida/rapido
estilo_global: blocky_voxel
paleta: ["#8a9099", "#3b4048", "#1d2024", "#ff6a1f", "#38e8ff"]
lote:
  - id: prop.caixa.teste.01
    tipo: prop_estatico
    rota: blocky
    prompt: "Caixa de teste do ciclo rapido"
    altura_metros: 0.40
    pivot: base
    limite_triangulos: 400
    colisao: box
"""


def _env(tmp_path: Path) -> dict:
    home = tmp_path / "home"
    home.mkdir()
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["XDG_STATE_HOME"] = str(home / ".local" / "state")
    env["XDG_CONFIG_HOME"] = str(home / ".config")
    env["FORGE3D_ROOT"] = str(RAIZ)
    for chave in ("FORGE3D_HOME", "FORGE3D_CONFIG", "PYTHONPATH"):
        env.pop(chave, None)
    return env


def _cli(args: list[str], env: dict) -> tuple[int, dict]:
    proc = subprocess.run(
        [sys.executable, "-m", "forge3d.cli.main", *args, "--json"],
        cwd=str(RAIZ),
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    try:
        return proc.returncode, json.loads(proc.stdout)
    except ValueError:
        raise AssertionError(
            f"stdout nao e JSON (exit {proc.returncode})\n"
            f"STDOUT={proc.stdout}\nSTDERR={proc.stderr[-2000:]}"
        ) from None


def test_ciclo_completo_em_um_asset(tmp_path):
    env = _env(tmp_path)
    spec = tmp_path / "lote.yaml"
    spec.write_text(SPEC, encoding="utf-8")
    destino = tmp_path / "home" / ".local" / "state" / "forge3d" / "saida" / "rapido"

    # 1. valida
    codigo, saida = _cli(["validate", str(spec)], env)
    assert codigo == 0, saida

    # 2. planeja sem escrever nada
    codigo, saida = _cli(["plan", str(spec)], env)
    assert codigo == 0, saida
    assert saida["plano"]["a_executar"] == 1
    assert not destino.exists(), "plan nao pode escrever no destino"

    # 3. executa e publica
    codigo, saida = _cli(["run", str(spec)], env)
    assert codigo == 0, saida["itens"]
    assert saida["resumo"]["publicados"] == 1
    manifesto = destino / "prop.caixa.teste.01.manifest.json"
    assert manifesto.is_file()
    man = json.loads(manifesto.read_text())
    assert man["qc"]["aprovado"] is True
    assert abs(man["geometry"]["bbox_m"][1] - 0.40) / 0.40 * 100 <= 0.5

    # 4. segunda execucao vem do cache e nao trabalha
    codigo, saida = _cli(["run", str(spec)], env)
    assert codigo == 0, saida["itens"]
    assert saida["resumo"]["trabalho_executado"] == 0
    assert saida["resumo"]["cache_hits"] == 1

    # 5. verifica integridade
    codigo, saida = _cli(["verify", str(destino)], env)
    assert codigo == 0 and saida["ok"] is True, saida

    # 6. --only recorta o veredito e devolve a medida (I8/I10)
    codigo, saida = _cli(["verify", str(destino), "--only=escala,pivo"], env)
    assert codigo == 0 and saida["ok"] is True, saida
    assert saida["escala"]["delta_pct"] <= 0.5
    assert saida["pivo"]["delta_mm"] <= 1.0
    codigo, saida = _cli(["verify", str(destino), "--only=manifesto"], env)
    assert codigo == 0 and saida["faltando"] == [], saida
