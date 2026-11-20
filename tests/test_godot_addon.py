"""Testes headless do plugin Godot 4 (helpers compartilhados, sintaxe e LOD customizado)."""

from __future__ import annotations

import json
import os
import shutil
import struct
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
PROJ_GODOT = RAIZ / "tools" / "godot_project"
POST_IMPORT_GD = RAIZ / "addons" / "forge3d" / "post_import.gd"
PLUGIN_GD = RAIZ / "addons" / "forge3d" / "plugin.gd"
CHECK_GD = RAIZ / "tools" / "godot_post_import_check.gd"
HERO_REAL_GLB = (
    Path.home() / ".local" / "state" / "forge3d" / "saida" / "hero_t2i_godot" / "hero.sentinel.body.01.glb"
)


def _encontrar_godot() -> str | None:
    env = os.environ.get("FORGE3D_GODOT")
    if env and Path(env).is_file():
        return env
    achado = shutil.which("godot")
    if achado:
        return achado
    padrao = Path.home() / "tools" / "godot" / "Godot_v4.3-stable_linux.x86_64"
    if padrao.is_file():
        return str(padrao)
    antigravity = Path.home() / ".gemini" / "antigravity" / "bin" / "godot"
    return str(antigravity) if antigravity.is_file() else None


def _exigir_godot() -> str:
    godot = _encontrar_godot()
    if not godot:
        pytest.skip("Godot 4 headless nao disponivel neste host")
    return godot


def _rodar_godot(godot: str, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [godot, "--headless", "--path", str(PROJ_GODOT), *args],
        capture_output=True,
        text=True,
        timeout=60,
    )


def _escrever_glb(caminho: Path, gltf: dict, binario: bytes) -> None:
    json_bytes = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    json_pad = (-len(json_bytes)) % 4
    json_chunk = json_bytes + (b" " * json_pad)

    bin_pad = (-len(binario)) % 4
    bin_chunk = binario + (b"\x00" * bin_pad)

    total = 12 + 8 + len(json_chunk) + 8 + len(bin_chunk)
    cabecalho = struct.pack("<3I", 0x46546C67, 2, total)
    c_json = struct.pack("<2I", len(json_chunk), 0x4E4F534A) + json_chunk
    c_bin = struct.pack("<2I", len(bin_chunk), 0x004E4942) + bin_chunk
    caminho.write_bytes(cabecalho + c_json + c_bin)


def _criar_glb_rigged(
    caminho: Path,
    nome_malha: str,
    escala: float = 1.0,
    com_animacoes: bool = True,
) -> None:
    dados = bytearray()
    views: list[dict] = []
    acessores: list[dict] = []

    def add_view(blob: bytes, target: int | None = None) -> int:
        while len(dados) % 4:
            dados.append(0)
        offset = len(dados)
        dados.extend(blob)
        view: dict = {"buffer": 0, "byteOffset": offset, "byteLength": len(blob)}
        if target is not None:
            view["target"] = target
        views.append(view)
        return len(views) - 1

    verts = [
        (0.0, 0.0, 0.0),
        (0.5 * escala, 0.0, 0.0),
        (0.0, 1.0 * escala, 0.0),
    ]
    v_pos = add_view(b"".join(struct.pack("<3f", *v) for v in verts), 34962)
    acessores.append(
        {
            "bufferView": v_pos,
            "componentType": 5126,
            "count": 3,
            "type": "VEC3",
            "min": [0.0, 0.0, 0.0],
            "max": [0.5 * escala, 1.0 * escala, 0.0],
        }
    )
    acc_pos = len(acessores) - 1

    v_norm = add_view(b"".join(struct.pack("<3f", 0.0, 0.0, 1.0) for _ in verts), 34962)
    acessores.append({"bufferView": v_norm, "componentType": 5126, "count": 3, "type": "VEC3"})
    acc_norm = len(acessores) - 1

    v_joints = add_view(b"".join(struct.pack("<4B", 0, 0, 0, 0) for _ in verts), 34962)
    acessores.append({"bufferView": v_joints, "componentType": 5121, "count": 3, "type": "VEC4"})
    acc_joints = len(acessores) - 1

    v_weights = add_view(b"".join(struct.pack("<4f", 1.0, 0.0, 0.0, 0.0) for _ in verts), 34962)
    acessores.append({"bufferView": v_weights, "componentType": 5126, "count": 3, "type": "VEC4"})
    acc_weights = len(acessores) - 1

    v_idx = add_view(struct.pack("<3H", 0, 1, 2), 34963)
    acessores.append({"bufferView": v_idx, "componentType": 5123, "count": 3, "type": "SCALAR"})
    acc_idx = len(acessores) - 1

    ident_mat = (
        1.0, 0.0, 0.0, 0.0,
        0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
        0.0, 0.0, 0.0, 1.0,
    )
    v_ibm = add_view(struct.pack("<16f", *ident_mat) * 2)
    acessores.append({"bufferView": v_ibm, "componentType": 5126, "count": 2, "type": "MAT4"})
    acc_ibm = len(acessores) - 1

    animations = []
    if com_animacoes:
        v_t = add_view(struct.pack("<3f", 0.0, 1.0, 2.0))
        acessores.append(
            {
                "bufferView": v_t,
                "componentType": 5126,
                "count": 3,
                "type": "SCALAR",
                "min": [0.0],
                "max": [2.0],
            }
        )
        acc_t = len(acessores) - 1

        rots = [(0.0, 0.0, 0.0, 1.0), (0.0, 0.15, 0.0, 0.9887), (0.0, 0.0, 0.0, 1.0)]
        v_r = add_view(b"".join(struct.pack("<4f", *q) for q in rots))
        acessores.append({"bufferView": v_r, "componentType": 5126, "count": 3, "type": "VEC4"})
        acc_r = len(acessores) - 1

        for nome_anim in ("idle", "walk", "run", "jump"):
            animations.append(
                {
                    "name": nome_anim,
                    "samplers": [{"input": acc_t, "output": acc_r, "interpolation": "LINEAR"}],
                    "channels": [{"sampler": 0, "target": {"node": 2, "path": "rotation"}}],
                }
            )

    gltf: dict = {
        "asset": {"version": "2.0", "generator": "forge3d-test"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [
            {"name": "Armature", "children": [1, 2]},
            {"name": nome_malha, "mesh": 0, "skin": 0},
            {"name": "Hips", "children": [3]},
            {"name": "Hand.R", "translation": [0.35, 1.0, 0.0]},
        ],
        "skins": [{"name": "Armature", "joints": [2, 3], "inverseBindMatrices": acc_ibm}],
        "meshes": [
            {
                "name": nome_malha,
                "primitives": [
                    {
                        "attributes": {
                            "POSITION": acc_pos,
                            "NORMAL": acc_norm,
                            "JOINTS_0": acc_joints,
                            "WEIGHTS_0": acc_weights,
                        },
                        "indices": acc_idx,
                    }
                ],
            }
        ],
        "accessors": acessores,
        "bufferViews": views,
        "buffers": [{"byteLength": len(dados)}],
    }
    if animations:
        gltf["animations"] = animations
    _escrever_glb(caminho, gltf, bytes(dados))


def _criar_glb_colisor(caminho: Path, nome: str = "colisor") -> None:
    verts = [
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (0.0, 0.0, 1.0),
    ]
    indices = (0, 2, 1, 0, 1, 3, 0, 3, 2, 1, 2, 3)
    pos_bytes = b"".join(struct.pack("<3f", *v) for v in verts)
    idx_bytes = struct.pack("<12H", *indices)
    dados = pos_bytes + idx_bytes
    gltf = {
        "asset": {"version": "2.0", "generator": "forge3d-test"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"name": nome, "mesh": 0}],
        "meshes": [
            {
                "name": nome,
                "primitives": [{"attributes": {"POSITION": 0}, "indices": 1}],
            }
        ],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": 4,
                "type": "VEC3",
                "min": [0.0, 0.0, 0.0],
                "max": [1.0, 1.0, 1.0],
            },
            {"bufferView": 1, "componentType": 5123, "count": 12, "type": "SCALAR"},
        ],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(pos_bytes), "target": 34962},
            {"buffer": 0, "byteOffset": len(pos_bytes), "byteLength": len(idx_bytes), "target": 34963},
        ],
        "buffers": [{"byteLength": len(dados)}],
    }
    _escrever_glb(caminho, gltf, dados)


def _escrever_manifesto(
    caminho: Path,
    asset_id: str,
    com_lod1: bool = True,
    com_colisor: bool = True,
) -> None:
    lods = [{"arquivo": f"{asset_id}.glb", "nivel": 0, "triangulos": 1}]
    if com_lod1:
        lods.append({"arquivo": f"{asset_id}_LOD1.glb", "nivel": 1, "triangulos": 1})
    manifesto: dict = {
        "schema": "forge3d/manifest@3",
        "asset_id": asset_id,
        "perfil": "godot4",
        "determinism": "D2",
        "lod": lods,
    }
    if com_colisor:
        manifesto["colisao"] = {"arquivo": f"{asset_id}_colisao.glb", "partes": 1, "tipo": "convex"}
    caminho.write_text(json.dumps(manifesto, indent=1), encoding="utf-8")


def _validar_cena_godot(godot: str, script_path: Path, corpo_gd: str, glb: Path) -> str:
    script_path.write_text(
        f"""extends SceneTree
const PostImport := preload({str(POST_IMPORT_GD)!r})

func _fail(msg: String, cena: Node = null) -> void:
\tprint("TEST_FAIL " + msg)
\tif cena != null:
\t\tcena.free()
\tquit(1)

func _initialize() -> void:
\tvar args := OS.get_cmdline_user_args()
\tvar caminho: String = args[0]
\tvar doc := GLTFDocument.new()
\tvar estado := GLTFState.new()
\tvar erro := doc.append_from_file(caminho, estado)
\tif erro != OK:
\t\t_fail("append_from_file=%d" % erro)
\t\treturn
\tvar cena := doc.generate_scene(estado)
\tif cena == null:
\t\t_fail("cena nula")
\t\treturn
\tPostImport.aplicar(cena, caminho)
{corpo_gd}
\tcena.free()
\tprint("TEST_OK")
\tquit(0)
""",
        encoding="utf-8",
    )
    proc = _rodar_godot(godot, ["--script", str(script_path), "--", str(glb)])
    assert proc.returncode == 0 and "TEST_OK" in proc.stdout, proc.stdout + proc.stderr
    return proc.stdout


def _criar_glb_multimesh(caminho: Path, nomes_malhas: list[str]) -> None:
    dados = bytearray()
    views: list[dict] = []
    acessores: list[dict] = []

    def add_view(blob: bytes, target: int | None = None) -> int:
        while len(dados) % 4:
            dados.append(0)
        offset = len(dados)
        dados.extend(blob)
        view: dict = {"buffer": 0, "byteOffset": offset, "byteLength": len(blob)}
        if target is not None:
            view["target"] = target
        views.append(view)
        return len(views) - 1

    verts = [(0.0, 0.0, 0.0), (0.5, 0.0, 0.0), (0.0, 1.0, 0.0)]
    v_pos = add_view(b"".join(struct.pack("<3f", *v) for v in verts), 34962)
    acessores.append(
        {"bufferView": v_pos, "componentType": 5126, "count": 3, "type": "VEC3", "min": [0.0, 0.0, 0.0], "max": [0.5, 1.0, 0.0]}
    )
    acc_pos = len(acessores) - 1
    v_norm = add_view(b"".join(struct.pack("<3f", 0.0, 0.0, 1.0) for _ in verts), 34962)
    acessores.append({"bufferView": v_norm, "componentType": 5126, "count": 3, "type": "VEC3"})
    acc_norm = len(acessores) - 1
    v_uv = add_view(b"".join(struct.pack("<2f", 0.0, 0.0) for _ in verts), 34962)
    acessores.append({"bufferView": v_uv, "componentType": 5126, "count": 3, "type": "VEC2"})
    acc_uv = len(acessores) - 1
    v_joints = add_view(b"".join(struct.pack("<4B", 0, 0, 0, 0) for _ in verts), 34962)
    acessores.append({"bufferView": v_joints, "componentType": 5121, "count": 3, "type": "VEC4"})
    acc_joints = len(acessores) - 1
    v_weights = add_view(b"".join(struct.pack("<4f", 1.0, 0.0, 0.0, 0.0) for _ in verts), 34962)
    acessores.append({"bufferView": v_weights, "componentType": 5126, "count": 3, "type": "VEC4"})
    acc_weights = len(acessores) - 1
    v_idx = add_view(struct.pack("<3H", 0, 1, 2), 34963)
    acessores.append({"bufferView": v_idx, "componentType": 5123, "count": 3, "type": "SCALAR"})
    acc_idx = len(acessores) - 1

    ident_mat = (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0)
    v_ibm = add_view(struct.pack("<16f", *ident_mat) * 2)
    acessores.append({"bufferView": v_ibm, "componentType": 5126, "count": 2, "type": "MAT4"})
    acc_ibm = len(acessores) - 1

    n_malhas = len(nomes_malhas)
    idx_hips = 1 + n_malhas
    idx_hand = idx_hips + 1
    nodes: list[dict] = [{"name": "Armature", "children": list(range(1, idx_hips + 1))}]
    meshes: list[dict] = []
    for i, nome in enumerate(nomes_malhas):
        nodes.append({"name": nome, "mesh": i, "skin": 0})
        meshes.append(
            {
                "name": nome,
                "primitives": [
                    {
                        "attributes": {
                            "POSITION": acc_pos,
                            "NORMAL": acc_norm,
                            "TEXCOORD_0": acc_uv,
                            "JOINTS_0": acc_joints,
                            "WEIGHTS_0": acc_weights,
                        },
                        "indices": acc_idx,
                        "material": 0,
                    }
                ],
            }
        )
    nodes.append({"name": "Hips", "children": [idx_hand]})
    nodes.append({"name": "Hand.R", "translation": [0.35, 1.0, 0.0]})

    gltf: dict = {
        "asset": {"version": "2.0", "generator": "forge3d-test"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": nodes,
        "skins": [{"name": "Armature", "joints": [idx_hips, idx_hand], "inverseBindMatrices": acc_ibm}],
        "meshes": meshes,
        "materials": [{"name": "Mat0", "pbrMetallicRoughness": {"baseColorFactor": [1.0, 1.0, 1.0, 1.0]}}],
        "accessors": acessores,
        "bufferViews": views,
        "buffers": [{"byteLength": len(dados)}],
    }
    _escrever_glb(caminho, gltf, bytes(dados))


def test_post_import_e_plugin_sintaxe_headless() -> None:
    godot = _exigir_godot()
    for script_gd in (POST_IMPORT_GD, PLUGIN_GD):
        chk = _rodar_godot(godot, ["--check-only", "--quit", "--script", str(script_gd)])
        assert chk.returncode == 0, chk.stdout + chk.stderr


def test_post_import_sem_lod1_preserva_visibility_range(tmp_path: Path) -> None:
    godot = _exigir_godot()
    asset_id = "prop.sem_lod.01"
    glb = tmp_path / f"{asset_id}.glb"
    col_glb = tmp_path / f"{asset_id}_colisao.glb"
    manifest = tmp_path / f"{asset_id}.manifest.json"

    _criar_glb_rigged(glb, asset_id, escala=1.0, com_animacoes=False)
    _criar_glb_colisor(col_glb, f"{asset_id}_colisor")
    _escrever_manifesto(manifest, asset_id, com_lod1=False, com_colisor=True)

    pi = _rodar_godot(godot, ["--script", str(CHECK_GD), "--", str(glb)])
    assert pi.returncode == 0 and "GODOT_POST_IMPORT_OK" in pi.stdout, pi.stdout + pi.stderr
    assert "bodies=1 shapes=1 anims=0 meta=true" in pi.stdout, pi.stdout

    corpo_gd = """
\tvar meshes := cena.find_children("*", "MeshInstance3D", true, false)
\tif meshes.size() != 1:
\t\t_fail("MeshInstance3D count=%d" % meshes.size(), cena)
\t\treturn
\tvar mi := meshes[0] as MeshInstance3D
\tif mi.visibility_range_begin != 0.0 or mi.visibility_range_end != 0.0 or mi.visibility_range_fade_mode != GeometryInstance3D.VISIBILITY_RANGE_FADE_DISABLED:
\t\t_fail("visibility_range alterado sem LOD1", cena)
\t\treturn
"""
    _validar_cena_godot(godot, tmp_path / "check_sem_lod1.gd", corpo_gd, glb)


def test_post_import_multimesh_lod1_e_distancia_customizada(tmp_path: Path) -> None:
    godot = _exigir_godot()
    asset_id = "hero.multi.lod.01"
    glb = tmp_path / f"{asset_id}.glb"
    lod1_glb = tmp_path / f"{asset_id}_LOD1.glb"
    manifest = tmp_path / f"{asset_id}.manifest.json"

    _criar_glb_multimesh(glb, ["Corpo", "Capa"])
    _criar_glb_multimesh(lod1_glb, ["Corpo_LOD1", "Capa_LOD1"])
    manifest.write_text(
        json.dumps(
            {
                "schema": "forge3d/manifest@3",
                "asset_id": asset_id,
                "perfil": "godot4",
                "determinism": "D1",
                "lod_distancia_m": 40.0,
                "lod": [
                    {"arquivo": f"{asset_id}.glb", "nivel": 0, "triangulos": 2},
                    {"arquivo": f"{asset_id}_LOD1.glb", "nivel": 1, "triangulos": 2},
                ],
            }
        ),
        encoding="utf-8",
    )

    corpo_gd = """
\tvar meshes := cena.find_children("*", "MeshInstance3D", true, false)
\tif meshes.size() != 4:
\t\t_fail("esperava 4 MeshInstance3D (2 LOD0 + 2 LOD1), obteve %d" % meshes.size(), cena)
\t\treturn
\tvar nomes := {}
\tfor m in meshes:
\t\tvar mi := m as MeshInstance3D
\t\tnomes[String(mi.name)] = mi
\tfor par in [["Corpo", "LOD1_Corpo"], ["Capa", "LOD1_Capa"]]:
\t\tif not nomes.has(par[0]) or not nomes.has(par[1]):
\t\t\t_fail("par LOD ausente: %s" % str(par), cena)
\t\t\treturn
\t\tvar m0 := nomes[par[0]] as MeshInstance3D
\t\tvar m1 := nomes[par[1]] as MeshInstance3D
\t\tif m0.visibility_range_end != 40.0 or m1.visibility_range_begin != 40.0:
\t\t\t_fail("distancia customizada 40.0 nao aplicada em %s" % par[0], cena)
\t\t\treturn
"""
    _validar_cena_godot(godot, tmp_path / "check_multimesh_lod.gd", corpo_gd, glb)
