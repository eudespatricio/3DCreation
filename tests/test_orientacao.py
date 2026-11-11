"""Regressao do GAP-048: personagem de cabeca para baixo tem que ser corrigido.

O caso real (conceito externo, 11/11/2026) saiu de cabeca para baixo com G1-G10 verdes: com uma
arma grande ao lado, `razao_topo_base` deu 0,988 e `centro_area` 6,18/12 — os dois sinais antigos
ficaram neutros. A fixture sintetica reproduz o padrao:
  * `personagem_upright.glb` — sola chata embaixo, cabeca estreita em cima, arma lateral e gola
    larga (para as regras antigas ficarem neutras); `invertido` tem que dar False.
  * `personagem_invertido.glb` — o mesmo mesh girado 180 no X; tem que ser espelhado, com
    `invertido_contato` True (o sinal novo e o do contato chato da sola).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
DRIVER = RAIZ / "tests" / "fixtures" / "checa_orientacao.py"
POSTPROCESS = RAIZ / "blender" / "postprocess.py"
BLENDER = shutil.which("blender") or str(Path.home() / ".local" / "bin" / "blender")


def _canonicalizar(glb: Path) -> dict:
    proc = subprocess.run(
        [
            BLENDER,
            "--background",
            "--factory-startup",
            "--python",
            str(DRIVER),
            "--",
            str(glb),
            str(POSTPROCESS),
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )
    linha = next(
        (l for l in proc.stdout.splitlines() if l.startswith("RESULTADO ")),
        None,
    )
    assert linha is not None, (proc.stdout[-2000:], proc.stderr[-2000:])
    return json.loads(linha[len("RESULTADO ") :])


@pytest.mark.blender
@pytest.mark.lento
def test_personagem_upright_nao_e_invertido():
    info = _canonicalizar(RAIZ / "tests" / "fixtures" / "personagem_upright.glb")
    assert info["invertido"] is False, info
    # as regras antigas ficam neutras de proposito (e a nova tambem nao dispara)
    assert info["razao_topo_base"] <= 1.5, info
    assert info["centro_area"] >= 5.76, info
    assert info["invertido_contato"] is False, info


@pytest.mark.blender
@pytest.mark.lento
def test_personagem_invertido_com_prop_grande_e_corrigido():
    info = _canonicalizar(RAIZ / "tests" / "fixtures" / "personagem_invertido.glb")
    assert info["invertido"] is True, info
    assert info["invertido_contato"] is True, info
    assert info["contato_topo"] > 3.0 * info["contato_base"], info


@pytest.mark.blender
@pytest.mark.lento
def test_personagem_tpose_envergadura_maior_que_altura_nao_tomba(tmp_path: Path):
    """T-pose larga (envergadura X > altura Z) nao pode ser tombada de lado por canonicalizar."""
    script = tmp_path / "mk_tpose.py"
    glb = tmp_path / "tpose.glb"
    script.write_text(
        f"""
import bpy
bpy.ops.wm.read_factory_settings(use_empty=True)
partes = []
for loc, scale in [
    ((0.0, 0.0, 0.03), (0.30, 0.14, 0.03)),   # sola larga
    ((0.0, -0.14, 0.64), (0.32, 0.03, 0.62)), # capa longa puxando centro_area < 0.48*n
    ((0.0, 0.0, 0.70), (0.20, 0.10, 0.65)),   # corpo vertical (topo z=1.35)
    ((0.0, 0.0, 1.50), (0.09, 0.09, 0.12)),   # cabeca z=1.62 (altura total 1.62)
    ((0.0, 0.0, 1.25), (0.95, 0.07, 0.07)),   # bracos T-pose (envergadura 1.90 > 1.62)
]:
    bpy.ops.mesh.primitive_cube_add(size=2.0, location=loc)
    o = bpy.context.active_object
    o.scale = scale
    partes.append(o)
bpy.ops.object.select_all(action="DESELECT")
for o in partes:
    o.select_set(True)
bpy.context.view_layer.objects.active = partes[0]
bpy.ops.object.join()
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.select_all(action="SELECT")
bpy.ops.mesh.subdivide(number_cuts=5)
bpy.ops.object.mode_set(mode="OBJECT")
bpy.ops.export_scene.gltf(filepath={str(glb)!r}, export_format="GLB")
""",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [BLENDER, "--background", "--factory-startup", "--python", str(script)],
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    assert glb.is_file(), proc.stderr[-1000:]
    info = _canonicalizar(glb)
    assert info["altura_eixo"] == "Z", info
    assert info["largura_eixo"] == "X", info
    assert info["invertido"] is False, info

