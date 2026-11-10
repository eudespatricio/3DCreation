"""P3-A sem GPU: malha com cor por vertice e sem UV -> UV + bake no ``bpy``.

O fixture e um cubo de 12 triangulos com ``COLOR_0``; o teste prova o caminho que o TripoSR usa
(``forge3d/bruto-arquivo@1`` + ``canonicalizar``) sem depender de GPU. O segundo teste usa o mesmo
asset contra o perfil ``roblox-r15``: ele nao declara ``colisao.prefixo`` e o G7 nao pode estourar.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from forge3d import plan, post, profiles, qc

RAIZ = Path(__file__).resolve().parents[1]
FIXTURE = RAIZ / "tests" / "fixtures" / "malha_colorida.glb"

pytestmark = [pytest.mark.blender, pytest.mark.lento]


@pytest.fixture(scope="module")
def asset(tmp_path_factory):
    base = tmp_path_factory.mktemp("p3a")
    bruto = base / "bruto"
    final = base / "final"
    bruto.mkdir()
    final.mkdir()
    shutil.copyfile(FIXTURE, bruto / "modelo.glb")
    (bruto / "modelo.json").write_text(
        json.dumps(
            {
                "schema": "forge3d/bruto-arquivo@1",
                "arquivo": "modelo.glb",
                "origem_nome": "malha_colorida.glb",
                "canonicalizar": True,
                "textura_px": 128,
                "pivos": {},
            },
            sort_keys=True,
            indent=1,
        ),
        encoding="utf-8",
    )

    item = {
        "id": "prop.fixture.colorida.01",
        "tipo": "prop_estatico",
        "rota": "import",
        "altura_metros": 1.0,
        "pivot": "base",
        "limite_triangulos": 100,
        "colisao": "box",
        "lod": [100],
        "auto_rig": False,
        "tags": [],
    }
    perfil = profiles.carregar("godot4")
    job = {
        "bruto_dir": str(bruto),
        "bruto_arquivo": "modelo.json",
        "saida_dir": str(final),
        "saida_resultado": str(final / "resultado.json"),
        "perfil": plan.perfil_resolvido(perfil),
        "item": item,
        "nome_base": item["id"],
        "nome_arquivo": f"{item['id']}.glb",
    }
    resultado = post.executar(job)
    assert resultado["ok"] is True
    resultado["licenca"] = {
        "modelo": "procedural",
        "uso_comercial": True,
        "notice": "fixture de teste",
    }
    return item, final, resultado


def test_bake_de_cor_por_vertice_gera_uv_e_textura(asset):
    item, final, resultado = asset
    texturas = [a for a in resultado["arquivos"] if a["papel"] == "textura"]
    assert len(texturas) == 1, resultado["arquivos"]
    assert texturas[0]["caminho"].endswith("_baseColor.png")

    perfil = profiles.carregar("godot4")
    relatorio = qc.verificar(item, perfil, final, resultado)
    falhas = [g for g in relatorio["gates"] if g["status"] != "ok"]
    assert relatorio["aprovado"] is True, falhas

    gltf = qc.ler_glb(final / f"{item['id']}.glb")
    info = qc.analisar(gltf)
    assert info["sem_uv"] == 0
    assert info["com_textura"] == 1
    assert info["imagens_externas"] == []
    assert info["triangulos"] <= item["limite_triangulos"]


def test_prop_aceito_no_perfil_roblox_sem_prefixo(asset):
    """Regressao do probe P2: perfil sem `colisao.prefixo` nao pode dar KeyError no G7."""
    item, final, resultado = asset
    perfil = profiles.carregar("roblox-r15")
    relatorio = qc.verificar(item, perfil, final, resultado)
    falhas = [g for g in relatorio["gates"] if g["status"] != "ok"]
    assert relatorio["aprovado"] is True, falhas
    g7 = next(g for g in relatorio["gates"] if g["id"] == "G7")
    assert g7["limite"]["prefixo"] is None
