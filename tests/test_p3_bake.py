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
    import ast

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
    # Pacote 3: doubleSided ausente/false e no principal nomeado com asset_id
    for mat in gltf.get("materials", []):
        assert mat.get("doubleSided", False) is False
    nos_malha = [n.get("name") for n in gltf.get("nodes", []) if "mesh" in n]
    assert nos_malha == [item["id"]], gltf.get("nodes")
    assert resultado["medidas"]["gerada"]["smooth"]["angulo_graus"] == 45.0

    # Margem de UV padrao >= 0.02 (evita bleed de mipmap no bake PBR)
    tree = ast.parse((RAIZ / "blender" / "postprocess.py").read_text(encoding="utf-8"))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "desdobrar_uv")
    margem_default = ast.literal_eval(fn.args.defaults[0])
    assert margem_default == pytest.approx(0.02)


def test_prop_aceito_no_perfil_roblox_sem_prefixo(asset):
    """Regressao do probe P2: perfil sem `colisao.prefixo` nao pode dar KeyError no G7.

    O pós-processo do fixture e o do perfil `godot4` (metros); para revalidar o mesmo GLB no perfil
    Roblox a escala declarada e 1.0 — e o caso de um `manifest@1` antigo lido contra o perfil novo.
    """
    item, final, resultado = asset
    perfil = profiles.carregar("roblox-r15")
    relatorio = qc.verificar(item, perfil, final, resultado, escala_saida=1.0)
    falhas = [g for g in relatorio["gates"] if g["status"] != "ok"]
    assert relatorio["aprovado"] is True, falhas
    g7 = next(g for g in relatorio["gates"] if g["id"] == "G7")
    assert g7["limite"]["prefixo"] is None


def test_rota_mesh_smooth_shading_reduz_vertices_e_gera_material_single_sided(tmp_path):
    """Pacote 3: malha organica com COLOR_0 recebe smooth_by_angle e nao exporta 3*tris vertices."""
    import subprocess

    blender = post.binario()
    bruto = tmp_path / "bruto"
    final = tmp_path / "final"
    bruto.mkdir()
    final.mkdir()
    esfera_glb = bruto / "esfera.glb"

    # Cria uma icosphere de 80 tris com atributo COLOR_0 (simulando saida crua do TripoSR)
    subprocess.run(
        [
            blender,
            "--background",
            "--factory-startup",
            "--python-expr",
            (
                "import bpy\n"
                "bpy.ops.wm.read_factory_settings(use_empty=True)\n"
                "bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2)\n"
                "obj = bpy.context.active_object\n"
                "ca = obj.data.color_attributes.new('Color', 'FLOAT_COLOR', 'POINT')\n"
                "for d in ca.data: d.color = (0.8, 0.3, 0.2, 1.0)\n"
                f"bpy.ops.export_scene.gltf(filepath={str(esfera_glb)!r}, export_format='GLB')\n"
            ),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    (bruto / "modelo.json").write_text(
        json.dumps(
            {
                "schema": "forge3d/bruto-arquivo@1",
                "arquivo": "esfera.glb",
                "origem_nome": "esfera.glb",
                "canonicalizar": True,
                "textura_px": 128,
                "pivos": {},
            }
        ),
        encoding="utf-8",
    )
    item = {
        "id": "prop.organico.esfera.01",
        "tipo": "prop_estatico",
        "rota": "mesh",
        "altura_metros": 1.0,
        "pivot": "base",
        "limite_triangulos": 80,
        "colisao": "convex",
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
    resultado["licenca"] = {"modelo": "procedural", "uso_comercial": True, "notice": "teste"}

    relatorio = qc.verificar(item, perfil, final, resultado)
    assert relatorio["aprovado"] is True, [g for g in relatorio["gates"] if g["status"] != "ok"]

    gltf = qc.ler_glb(final / f"{item['id']}.glb")
    info = qc.analisar(gltf)
    # Sem smooth shading, 80 tris exportariam 240 vertices; com smooth shading solda continua < 3*tris
    assert info["triangulos"] == 80
    assert info["vertices"] < 3 * info["triangulos"], info
    for mat in gltf.get("materials", []):
        assert mat.get("doubleSided", False) is False
    nos_malha = [n.get("name") for n in gltf.get("nodes", []) if "mesh" in n]
    assert nos_malha == [item["id"]]


def _encontrar_godot() -> str | None:
    import os

    env = os.environ.get("FORGE3D_GODOT")
    if env and Path(env).is_file():
        return env
    achado = shutil.which("godot")
    if achado:
        return achado
    padrao = Path.home() / "tools" / "godot" / "Godot_v4.3-stable_linux.x86_64"
    return str(padrao) if padrao.is_file() else None


def test_godot_plugin_post_import_e_anim_headless(tmp_path):
    """Pacote 3: valida sintaxe/execucao de addons/forge3d/post_import.gd e godot_anim_check.gd."""
    import os
    import subprocess
    import sys

    godot = _encontrar_godot()
    if not godot:
        pytest.skip("Godot 4.3 headless nao disponivel neste host")

    home = tmp_path / "home"
    home.mkdir()
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["XDG_STATE_HOME"] = str(home / ".local" / "state")
    env["XDG_CONFIG_HOME"] = str(home / ".config")
    env["FORGE3D_ROOT"] = str(RAIZ)
    for k in ("FORGE3D_HOME", "FORGE3D_CONFIG", "PYTHONPATH"):
        env.pop(k, None)

    destino = home / ".local" / "state" / "forge3d" / "saida" / "godot_pkg3"
    lote = tmp_path / "lote_godot.yaml"
    lote.write_text(
        "\n".join(
            [
                "schema: forge3d/spec@3",
                "projeto: demo",
                "perfil: godot4",
                f"destino_exportacao: {destino}",
                "estilo_global: blocky_voxel",
                "lote:",
                "  - id: mob.godot.guard.01",
                "    tipo: personagem_humanoide",
                "    rota: blocky",
                "    prompt: guarda blocky para validar post_import",
                "    altura_metros: 1.85",
                "    pivot: base",
                "    limite_triangulos: 3000",
                "    auto_rig: true",
                "    esqueleto: godot-humanoid@1",
                "    animacoes_base: [idle]",
                "    colisao: convex",
                "    lod: [100]",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    proc_run = subprocess.run(
        [sys.executable, "-m", "forge3d.cli.main", "run", str(lote), "--json"],
        cwd=str(RAIZ),
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc_run.returncode == 0, proc_run.stdout + proc_run.stderr

    glb = destino / "mob.godot.guard.01.glb"
    assert glb.is_file()
    gltf = qc.ler_glb(glb)
    nos_malha = [n.get("name") for n in gltf.get("nodes", []) if "mesh" in n]
    assert nos_malha == ["mob.godot.guard.01"]
    for mat in gltf.get("materials", []):
        assert mat.get("doubleSided", False) is False

    proj = RAIZ / "tools" / "godot_project"
    for script_gd in ("addons/forge3d/post_import.gd", "addons/forge3d/plugin.gd"):
        chk = subprocess.run(
            [godot, "--headless", "--path", str(proj), "--check-only", "--quit", "--script", str(RAIZ / script_gd)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert chk.returncode == 0, chk.stdout + chk.stderr

    anim = subprocess.run(
        [godot, "--headless", "--path", str(proj), "--script", str(RAIZ / "tools" / "godot_anim_check.gd"), "--", str(glb), "idle"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert anim.returncode == 0 and "GODOT_ANIM_OK" in anim.stdout, anim.stdout + anim.stderr

    pi = subprocess.run(
        [godot, "--headless", "--path", str(proj), "--script", str(RAIZ / "tools" / "godot_post_import_check.gd"), "--", str(glb)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert pi.returncode == 0 and "GODOT_POST_IMPORT_OK" in pi.stdout, pi.stdout + pi.stderr
    assert "bodies=0 shapes=0 anims=1 meta=true" in pi.stdout, pi.stdout
