"""Testes headless do plugin Godot 4 (addons/forge3d/post_import.gd)."""

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


def test_post_import_e_plugin_sintaxe_headless() -> None:
    godot = _exigir_godot()
    for script_gd in (POST_IMPORT_GD, PLUGIN_GD):
        chk = _rodar_godot(godot, ["--check-only", "--quit", "--script", str(script_gd)])
        assert chk.returncode == 0, chk.stdout + chk.stderr


def test_post_import_animacoes_lod1_e_check_sintetico(tmp_path: Path) -> None:
    godot = _exigir_godot()
    asset_id = "hero.sintetico.01"
    glb = tmp_path / f"{asset_id}.glb"
    lod1_glb = tmp_path / f"{asset_id}_LOD1.glb"
    col_glb = tmp_path / f"{asset_id}_colisao.glb"
    manifest = tmp_path / f"{asset_id}.manifest.json"

    _criar_glb_rigged(glb, asset_id, escala=1.0, com_animacoes=True)
    _criar_glb_rigged(lod1_glb, f"{asset_id}_LOD1", escala=0.95, com_animacoes=True)
    _criar_glb_colisor(col_glb, f"{asset_id}_colisor")
    _escrever_manifesto(manifest, asset_id, com_lod1=True, com_colisor=True)

    pi = _rodar_godot(godot, ["--script", str(CHECK_GD), "--", str(glb)])
    assert pi.returncode == 0 and "GODOT_POST_IMPORT_OK" in pi.stdout, pi.stdout + pi.stderr
    assert "bodies=1 shapes=1 anims=1 meta=true" in pi.stdout, pi.stdout

    corpo_gd = """
\tvar players := cena.find_children("*", "AnimationPlayer", true, false)
\tif players.size() != 1:
\t\t_fail("AnimationPlayer count=%d" % players.size(), cena)
\t\treturn
\tvar skels := cena.find_children("*", "Skeleton3D", true, false)
\tif skels.size() != 1:
\t\t_fail("Skeleton3D count=%d" % skels.size(), cena)
\t\treturn
\tvar player := players[0] as AnimationPlayer
\tif player.has_animation("idle-loop"):
\t\t_fail("idle-loop presente", cena)
\t\treturn
\tfor clip in ["idle", "walk", "run"]:
\t\tif not player.has_animation(clip) or player.get_animation(clip).loop_mode != Animation.LOOP_LINEAR:
\t\t\t_fail("clip %s sem LOOP_LINEAR" % clip, cena)
\t\t\treturn
\tif not player.has_animation("jump") or player.get_animation("jump").loop_mode != Animation.LOOP_NONE:
\t\t_fail("clip jump sem LOOP_NONE", cena)
\t\treturn
\tvar meshes := cena.find_children("*", "MeshInstance3D", true, false)
\tif meshes.size() != 2:
\t\t_fail("MeshInstance3D count=%d" % meshes.size(), cena)
\t\treturn
\tvar lod0 := meshes[0] as MeshInstance3D
\tvar lod1 := meshes[1] as MeshInstance3D
\tif String(lod1.name) != "LOD1_" + String(lod0.name):
\t\t_fail("nome LOD1 inesperado: %s vs %s" % [lod1.name, lod0.name], cena)
\t\treturn
\tif lod0.visibility_range_begin != 0.0 or lod0.visibility_range_end != 25.0 or lod0.visibility_range_fade_mode != GeometryInstance3D.VISIBILITY_RANGE_FADE_SELF:
\t\t_fail("visibility_range LOD0 invalido", cena)
\t\treturn
\tif lod1.visibility_range_begin != 25.0 or lod1.visibility_range_end != 0.0 or lod1.visibility_range_fade_mode != GeometryInstance3D.VISIBILITY_RANGE_FADE_SELF:
\t\t_fail("visibility_range LOD1 invalido", cena)
\t\treturn
\tif lod1.mesh == null or lod1.skin == null:
\t\t_fail("LOD1 sem mesh ou skin", cena)
\t\treturn
\tvar skel_resolvido := lod1.get_node_or_null(lod1.skeleton)
\tif skel_resolvido != skels[0]:
\t\t_fail("LOD1 skeleton nao aponta para Skeleton3D principal", cena)
\t\treturn
\tPostImport.aplicar(cena, caminho)
\tif cena.find_children("*", "MeshInstance3D", true, false).size() != 2:
\t\t_fail("aplicar duplicou LOD1", cena)
\t\treturn
\tif cena.find_children("*", "AnimationPlayer", true, false).size() != 1:
\t\t_fail("aplicar duplicou AnimationPlayer", cena)
\t\treturn
"""
    _validar_cena_godot(godot, tmp_path / "check_lod1.gd", corpo_gd, glb)


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


def test_post_import_hero_t2i_real_se_presente(tmp_path: Path) -> None:
    godot = _exigir_godot()
    if not HERO_REAL_GLB.is_file():
        pytest.skip(f"Asset real ausente neste host: {HERO_REAL_GLB}")

    pi = _rodar_godot(godot, ["--script", str(CHECK_GD), "--", str(HERO_REAL_GLB)])
    assert pi.returncode == 0 and "GODOT_POST_IMPORT_OK" in pi.stdout, pi.stdout + pi.stderr
    assert "bodies=0 shapes=0 anims=1 meta=true" in pi.stdout, pi.stdout

    corpo_gd = """
\tvar players := cena.find_children("*", "AnimationPlayer", true, false)
\tif players.size() != 1:
\t\t_fail("AnimationPlayer count=%d" % players.size(), cena)
\t\treturn
\tvar skels := cena.find_children("*", "Skeleton3D", true, false)
\tif skels.size() != 1:
\t\t_fail("Skeleton3D count=%d" % skels.size(), cena)
\t\treturn
\tvar player := players[0] as AnimationPlayer
\tif player.has_animation("idle-loop"):
\t\t_fail("idle-loop presente no hero real", cena)
\t\treturn
\tfor clip in ["idle", "walk", "run"]:
\t\tif player.get_animation(clip).loop_mode != Animation.LOOP_LINEAR:
\t\t\t_fail("hero clip %s sem LOOP_LINEAR" % clip, cena)
\t\t\treturn
\tif player.get_animation("jump").loop_mode != Animation.LOOP_NONE:
\t\t_fail("hero clip jump sem LOOP_NONE", cena)
\t\treturn
\tvar meshes := cena.find_children("*", "MeshInstance3D", true, false)
\tif meshes.size() != 2:
\t\t_fail("hero MeshInstance3D count=%d" % meshes.size(), cena)
\t\treturn
\tvar lod0 := meshes[0] as MeshInstance3D
\tvar lod1 := meshes[1] as MeshInstance3D
\tif not String(lod1.name).begins_with("LOD1_"):
\t\t_fail("hero LOD1 sem prefixo LOD1_: %s" % lod1.name, cena)
\t\treturn
\tif lod0.visibility_range_begin != 0.0 or lod0.visibility_range_end != 25.0 or lod0.visibility_range_fade_mode != GeometryInstance3D.VISIBILITY_RANGE_FADE_SELF:
\t\t_fail("hero LOD0 visibility_range invalido", cena)
\t\treturn
\tif lod1.visibility_range_begin != 25.0 or lod1.visibility_range_end != 0.0 or lod1.visibility_range_fade_mode != GeometryInstance3D.VISIBILITY_RANGE_FADE_SELF:
\t\t_fail("hero LOD1 visibility_range invalido", cena)
\t\treturn
\tvar mat := lod0.mesh.surface_get_material(0)
\tif not (mat is ORMMaterial3D):
\t\t_fail("hero material nao virou ORMMaterial3D", cena)
\t\treturn
\tvar orm_mat := mat as ORMMaterial3D
\tif orm_mat.orm_texture == null or not orm_mat.normal_enabled or orm_mat.normal_texture == null:
\t\t_fail("hero ORMMaterial3D sem orm_texture ou normal_texture", cena)
\t\treturn
\tif orm_mat.texture_filter != BaseMaterial3D.TEXTURE_FILTER_LINEAR_WITH_MIPMAPS_ANISOTROPIC:
\t\t_fail("hero ORMMaterial3D sem TEXTURE_FILTER_LINEAR_WITH_MIPMAPS_ANISOTROPIC", cena)
\t\treturn
\tif lod1.get_node_or_null(lod1.skeleton) != skels[0]:
\t\t_fail("hero LOD1 skeleton nao aponta para Skeleton3D principal", cena)
\t\treturn
"""
    _validar_cena_godot(godot, tmp_path / "check_hero_real.gd", corpo_gd, HERO_REAL_GLB)


def test_montar_character_body_capsula_remove_col_e_anexos(tmp_path: Path) -> None:
    godot = _exigir_godot()
    asset_id = "hero.charbody.01"
    glb = tmp_path / f"{asset_id}.glb"
    col_glb = tmp_path / f"{asset_id}_colisao.glb"
    manifest = tmp_path / f"{asset_id}.manifest.json"

    _criar_glb_rigged(glb, asset_id, escala=1.0, com_animacoes=True)
    _criar_glb_colisor(col_glb, f"{asset_id}_colisor")
    _escrever_manifesto(manifest, asset_id, com_lod1=False, com_colisor=True)

    script = tmp_path / "check_char_body.gd"
    script.write_text(
        f"""extends SceneTree
const PostImport := preload({str(POST_IMPORT_GD)!r})

func _fail(msg: String, node: Node = null) -> void:
\tprint("TEST_FAIL " + msg)
\tif node != null:
\t\tnode.free()
\tquit(1)

func _initialize() -> void:
\tvar caminho := {str(glb)!r}
\tvar doc := GLTFDocument.new()
\tvar estado := GLTFState.new()
\tif doc.append_from_file(caminho, estado) != OK:
\t\t_fail("append_from_file falhou")
\t\treturn
\tvar body := doc.generate_scene(estado)
\tPostImport.aplicar(body, caminho)
\tif body.find_children("*", "StaticBody3D", true, false).size() != 1:
\t\t_fail("esperava 1 StaticBody3D antes de montar_character_body", body)
\t\treturn

\tvar escudo := MeshInstance3D.new()
\tescudo.name = "EscudoTeste"
\tvar char_body := PostImport.montar_character_body(body, {{"Hand.R": escudo}}, 1.85, 0.35, true)
\tif not (char_body is CharacterBody3D):
\t\t_fail("retorno nao e CharacterBody3D", char_body)
\t\treturn
\tif body.get_parent() != char_body:
\t\t_fail("body_node nao e filho do CharacterBody3D", char_body)
\t\treturn
\tif not body.find_children("*", "StaticBody3D", true, false).is_empty():
\t\t_fail("StaticBody3D _col nao foi removido", char_body)
\t\treturn

\tvar shapes := char_body.find_children("*", "CollisionShape3D", false, false)
\tif shapes.size() != 1:
\t\t_fail("CollisionShape3D direto ausente: %d" % shapes.size(), char_body)
\t\treturn
\tvar cs := shapes[0] as CollisionShape3D
\tif not (cs.shape is CapsuleShape3D):
\t\t_fail("shape nao e CapsuleShape3D", char_body)
\t\treturn
\tvar cap := cs.shape as CapsuleShape3D
\tif absf(cap.height - 1.85) > 0.001 or absf(cap.radius - 0.35) > 0.001 or absf(cs.position.y - 0.925) > 0.001:
\t\t_fail("dimensoes ou centro da capsula incorretos", char_body)
\t\treturn

\tvar attachments := char_body.find_children("*", "BoneAttachment3D", true, false)
\tif attachments.size() != 1:
\t\t_fail("BoneAttachment3D count=%d" % attachments.size(), char_body)
\t\treturn
\tvar ba := attachments[0] as BoneAttachment3D
\tif ba.bone_name != "Hand.R" or escudo.get_parent() != ba:
\t\t_fail("BoneAttachment3D nao vinculou Hand.R ou escudo", char_body)
\t\treturn
\tchar_body.free()

\t# Valida remover_static_body = false preservando _col
\tvar doc2 := GLTFDocument.new()
\tvar estado2 := GLTFState.new()
\tdoc2.append_from_file(caminho, estado2)
\tvar body2 := doc2.generate_scene(estado2)
\tPostImport.aplicar(body2, caminho)
\tvar char_keep := PostImport.montar_character_body(body2, {{}}, 2.0, 0.4, false)
\tif body2.find_children("*", "StaticBody3D", true, false).size() != 1:
\t\t_fail("remover_static_body=false removeu _col", char_keep)
\t\treturn
\tchar_keep.free()
\tprint("CHAR_BODY_OK")
\tquit(0)
""",
        encoding="utf-8",
    )
    proc = _rodar_godot(godot, ["--script", str(script)])
    assert proc.returncode == 0 and "CHAR_BODY_OK" in proc.stdout, proc.stdout + proc.stderr


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


def test_plugin_captura_path_sem_scene_file_path(tmp_path: Path) -> None:
    godot = _exigir_godot()
    asset_id = "prop.plugin.path.01"
    glb = tmp_path / f"{asset_id}.glb"
    manifest = tmp_path / f"{asset_id}.manifest.json"
    _criar_glb_rigged(glb, asset_id, escala=1.0, com_animacoes=False)
    _escrever_manifesto(manifest, asset_id, com_lod1=False, com_colisor=False)

    plugin_src = PLUGIN_GD.read_text(encoding="utf-8")
    assert "_get_import_options" in plugin_src
    assert "_source_queue" in plugin_src
    assert "PostImport.aplicar(scene, source_path)" in plugin_src

    script = tmp_path / "check_plugin_path.gd"
    script.write_text(
        f"""extends SceneTree
const Plugin := preload({str(PLUGIN_GD)!r})

func _initialize() -> void:
\tvar importer := Plugin.Forge3DPostImportPlugin.new()
\tvar caminho := {str(glb)!r}
\tvar doc := GLTFDocument.new()
\tvar estado := GLTFState.new()
\tif doc.append_from_file(caminho, estado) != OK:
\t\tprint("PLUGIN_FAIL append")
\t\tquit(1)
\t\treturn
\tvar cena := doc.generate_scene(estado)
\tcena.scene_file_path = ""
\timporter._get_import_options(caminho)
\timporter._post_process(cena)
\tif not cena.has_meta("forge3d_manifest") or str(cena.get_meta("forge3d_asset_id")) != {asset_id!r}:
\t\tprint("PLUGIN_FAIL sem manifesto apos _get_import_options + _post_process")
\t\tcena.free()
\t\tquit(1)
\t\treturn
\tcena.free()
\tprint("PLUGIN_PATH_OK")
\tquit(0)
""",
        encoding="utf-8",
    )
    proc = _rodar_godot(godot, ["--editor", "--script", str(script)])
    assert proc.returncode == 0 and "PLUGIN_PATH_OK" in proc.stdout, proc.stdout + proc.stderr


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


def test_post_import_orm_normal_e_filtro_nearest(tmp_path: Path) -> None:
    from PIL import Image

    godot = _exigir_godot()
    asset_id = "prop.orm.01"
    glb = tmp_path / f"{asset_id}.glb"
    manifest = tmp_path / f"{asset_id}.manifest.json"
    _criar_glb_multimesh(glb, [asset_id])
    Image.new("RGB", (32, 32), (200, 150, 100)).save(tmp_path / f"{asset_id}_baseColor.png")
    Image.new("RGB", (32, 32), (128, 128, 255)).save(tmp_path / f"{asset_id}_normal.png")
    Image.new("RGB", (32, 32), (255, 180, 64)).save(tmp_path / f"{asset_id}_orm.png")
    _escrever_manifesto(manifest, asset_id, com_lod1=False, com_colisor=False)

    corpo_gd = """
\tvar meshes := cena.find_children("*", "MeshInstance3D", true, false)
\tvar mi := meshes[0] as MeshInstance3D
\tvar mat := mi.mesh.surface_get_material(0)
\tif not (mat is ORMMaterial3D):
\t\t_fail("material nao convertido para ORMMaterial3D", cena)
\t\treturn
\tvar orm := mat as ORMMaterial3D
\tif orm.orm_texture == null or not orm.ao_enabled:
\t\t_fail("orm_texture ou ao_enabled ausente", cena)
\t\treturn
\tif not orm.normal_enabled or orm.normal_texture == null:
\t\t_fail("normal_texture nao conectado", cena)
\t\treturn
\tif orm.albedo_texture == null:
\t\t_fail("albedo_texture fallback nao conectado", cena)
\t\treturn
\tif orm.texture_filter != BaseMaterial3D.TEXTURE_FILTER_NEAREST_WITH_MIPMAPS:
\t\t_fail("texture_filter diferente de TEXTURE_FILTER_NEAREST_WITH_MIPMAPS", cena)
\t\treturn
"""
    _validar_cena_godot(godot, tmp_path / "check_orm.gd", corpo_gd, glb)


def test_post_import_skip_static_body_personagem_e_turn_180_y(tmp_path: Path) -> None:
    godot = _exigir_godot()
    asset_id = "hero.rigged.turn.01"
    glb = tmp_path / f"{asset_id}.glb"
    col_glb = tmp_path / f"{asset_id}_colisao.glb"
    manifest = tmp_path / f"{asset_id}.manifest.json"
    _criar_glb_rigged(glb, asset_id, escala=1.0, com_animacoes=True)
    _criar_glb_colisor(col_glb, f"{asset_id}_colisor")
    manifest.write_text(
        json.dumps(
            {
                "schema": "forge3d/manifest@3",
                "asset_id": asset_id,
                "perfil": "godot4",
                "determinism": "D1",
                "rig": {"esqueleto": "godot-humanoid@1", "ossos": 2},
                "frente": "+Z",
                "colisao": {"arquivo": f"{asset_id}_colisao.glb", "partes": 1, "tipo": "convex"},
            }
        ),
        encoding="utf-8",
    )

    pi = _rodar_godot(godot, ["--script", str(CHECK_GD), "--", str(glb)])
    assert pi.returncode == 0 and "GODOT_POST_IMPORT_OK" in pi.stdout, pi.stdout + pi.stderr
    assert "bodies=0 shapes=0" in pi.stdout, pi.stdout

    corpo_gd = """
\tif not cena.find_children("*", "StaticBody3D", true, false).is_empty():
\t\t_fail("StaticBody3D criado para asset com rig != null", cena)
\t\treturn
\tvar root3d := cena as Node3D
\tif absf(absf(root3d.rotation.y) - PI) > 0.001:
\t\t_fail("rotacao 180 graus Y nao aplicada: %f" % root3d.rotation.y, cena)
\t\treturn
\tPostImport.aplicar(cena, caminho)
\tif absf(absf(root3d.rotation.y) - PI) > 0.001:
\t\t_fail("rotacao 180 graus Y nao idempotente: %f" % root3d.rotation.y, cena)
\t\treturn
"""
    _validar_cena_godot(godot, tmp_path / "check_skip_turn.gd", corpo_gd, glb)


def test_attach_skinned_mesh_e_validacao_bone_attachment(tmp_path: Path) -> None:
    godot = _exigir_godot()
    asset_id = "hero.skinned.attach.01"
    glb = tmp_path / f"{asset_id}.glb"
    _criar_glb_rigged(glb, asset_id, escala=1.0, com_animacoes=False)

    script = tmp_path / "check_attach_skinned.gd"
    script.write_text(
        f"""extends SceneTree
const PostImport := preload({str(POST_IMPORT_GD)!r})

func _fail(msg: String, node: Node = null) -> void:
\tprint("TEST_FAIL " + msg)
\tif node != null:
\t\tnode.free()
\tquit(1)

func _initialize() -> void:
\tvar caminho := {str(glb)!r}
\tvar doc := GLTFDocument.new()
\tvar estado := GLTFState.new()
\tif doc.append_from_file(caminho, estado) != OK:
\t\t_fail("append_from_file falhou")
\t\treturn
\tvar body := doc.generate_scene(estado)
\tvar skels := body.find_children("*", "Skeleton3D", true, false)
\tif skels.is_empty():
\t\t_fail("Skeleton3D ausente", body)
\t\treturn
\tvar skel := skels[0] as Skeleton3D

\tvar armadura := MeshInstance3D.new()
\tarmadura.name = "PeitoralSkinned"
\tif not PostImport.attach_skinned_mesh(armadura, skel):
\t\t_fail("attach_skinned_mesh retornou false", body)
\t\treturn
\tif armadura.get_parent() != skel or armadura.get_node_or_null(armadura.skeleton) != skel:
\t\t_fail("armadura nao vinculada ao Skeleton3D alvo", body)
\t\treturn
\tif PostImport.attach_skinned_mesh(null, skel):
\t\t_fail("attach_skinned_mesh deveria retornar false para null", body)
\t\treturn

\tvar espada := MeshInstance3D.new()
\tespada.name = "Espada"
\tvar invalido := MeshInstance3D.new()
\tinvalido.name = "AnexoOssoInexistente"
\tvar char_body := PostImport.montar_character_body(body, {{"Hand.R": espada, "OssoQueNaoExiste": invalido}})
\tvar attachments := char_body.find_children("*", "BoneAttachment3D", true, false)
\tif attachments.size() != 1:
\t\t_fail("esperava apenas 1 BoneAttachment3D valido, obteve %d" % attachments.size(), char_body)
\t\treturn
\tif (attachments[0] as BoneAttachment3D).bone_name != "Hand.R":
\t\t_fail("BoneAttachment3D com osso inesperado", char_body)
\t\treturn
\tinvalido.free()
\tchar_body.free()
\tprint("ATTACH_SKINNED_OK")
\tquit(0)
""",
        encoding="utf-8",
    )
    proc = _rodar_godot(godot, ["--script", str(script)])
    assert proc.returncode == 0 and "ATTACH_SKINNED_OK" in proc.stdout, proc.stdout + proc.stderr


def _criar_glb_com_no_rotacionado(
    caminho: Path,
    nome_pai: str,
    rot_pai_quat: tuple[float, float, float, float],
    nome_malha: str,
    com_ucx: bool = False,
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

    verts = [(0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.2, 0.0, 0.0)]
    v_pos = add_view(b"".join(struct.pack("<3f", *v) for v in verts), 34962)
    acessores.append(
        {"bufferView": v_pos, "componentType": 5126, "count": 3, "type": "VEC3", "min": [0.0, 0.0, 0.0], "max": [0.2, 1.0, 0.0]}
    )
    v_norm = add_view(b"".join(struct.pack("<3f", 0.0, 0.0, 1.0) for _ in verts), 34962)
    acessores.append({"bufferView": v_norm, "componentType": 5126, "count": 3, "type": "VEC3"})
    v_idx = add_view(struct.pack("<3H", 0, 1, 2), 34963)
    acessores.append({"bufferView": v_idx, "componentType": 5123, "count": 3, "type": "SCALAR"})

    nodes: list[dict] = [
        {"name": nome_pai, "rotation": list(rot_pai_quat), "children": [1] + ([2] if com_ucx else [])},
        {"name": nome_malha, "mesh": 0},
    ]
    meshes = [
        {
            "name": nome_malha,
            "primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1}, "indices": 2, "material": 0}],
        }
    ]
    if com_ucx:
        nodes.append({"name": f"UCX_{nome_malha}", "mesh": 1})
        meshes.append(
            {
                "name": f"UCX_{nome_malha}",
                "primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1}, "indices": 2, "material": 0}],
            }
        )
    gltf = {
        "asset": {"version": "2.0", "generator": "forge3d-test"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": nodes,
        "meshes": meshes,
        "materials": [{"name": "Mat0", "pbrMetallicRoughness": {"baseColorFactor": [1.0, 1.0, 1.0, 1.0]}}],
        "accessors": acessores,
        "bufferViews": views,
        "buffers": [{"byteLength": len(dados)}],
    }
    _escrever_glb(caminho, gltf, bytes(dados))


def test_bone_map_humanoid_nomes_existem_no_perfil_godot(tmp_path: Path) -> None:
    from forge3d import profiles

    godot = _exigir_godot()
    ossos_validos = set(profiles.carregar("godot4")["rig"]["mapas"]["godot-humanoid@1"])
    script = tmp_path / "check_bonemap.gd"
    script.write_text(
        f"""extends SceneTree
const PostImport := preload({str(POST_IMPORT_GD)!r})

func _initialize() -> void:
\tvar bm := PostImport.criar_bone_map_humanoid()
\tvar prof := bm.profile
\tfor i in range(prof.bone_size):
\t\tvar pname := prof.get_bone_name(i)
\t\tvar sname := bm.get_skeleton_bone_name(pname)
\t\tif sname != "":
\t\t\tprint("MAP ", pname, "=", sname)
\tquit(0)
""",
        encoding="utf-8",
    )
    proc = _rodar_godot(godot, ["--script", str(script)])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    mapeados = {}
    for linha in proc.stdout.splitlines():
        if linha.startswith("MAP "):
            k, v = linha[4:].split("=", 1)
            mapeados[k] = v
    assert mapeados.get("Chest") == "Spine1", mapeados
    assert mapeados.get("UpperChest") == "Chest", mapeados
    assert mapeados.get("LeftToes") == "Toe.L", mapeados
    assert mapeados.get("RightToes") == "Toe.R", mapeados
    invalidos = {k: v for k, v in mapeados.items() if v not in ossos_validos}
    assert not invalidos, f"Ossos inexistentes em godot-humanoid@1: {invalidos}"


def test_montar_character_body_orienta_arma_escudo_e_ombreira(tmp_path: Path) -> None:
    import math

    godot = _exigir_godot()
    body_glb = tmp_path / "body.glb"
    _criar_glb_rigged(body_glb, "body", escala=1.0, com_animacoes=False)
    # Enriquece o GLB rigged com Shoulder.L, LowerArm.L e Hand.R em A-pose leve
    data = body_glb.read_bytes()
    jlen = struct.unpack_from("<I", data, 12)[0]
    blen = struct.unpack_from("<I", data, 20 + jlen)[0]
    gltf = json.loads(data[20 : 20 + jlen])
    bin_bytes = bytearray(data[28 + jlen : 28 + jlen + blen])
    # Substitui joints por Hips(0) -> Shoulder.L -> LowerArm.L e Hand.R (A-pose inclinada)
    ang = math.radians(15.0)
    sh_q = [0.0, 0.0, -math.sin(math.pi / 4.0), math.cos(math.pi / 4.0)]  # Y -> +X
    arm_q = [0.0, 0.0, math.sin((math.pi - ang) / 2.0), math.cos((math.pi - ang) / 2.0)]  # Y -> -Y/+X
    gltf["nodes"] = [
        {"name": "Armature", "children": [1, 2]},
        {"name": "body", "mesh": 0, "skin": 0},
        {"name": "Hips", "children": [3, 5]},
        {"name": "Shoulder.L", "translation": [0.1, 1.35, 0.0], "rotation": sh_q, "children": [4]},
        {"name": "LowerArm.L", "translation": [0.0, 0.15, 0.0], "rotation": arm_q},
        {"name": "Hand.R", "translation": [-0.3, 1.0, 0.0], "rotation": [0.0, 0.0, math.sin((math.pi + ang) / 2.0), math.cos((math.pi + ang) / 2.0)]},
    ]
    # Expand inverseBindMatrices to 4 matrices
    ident = struct.pack("<16f", 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)
    while len(bin_bytes) % 4:
        bin_bytes.append(0)
    ibm_off = len(bin_bytes)
    bin_bytes.extend(ident * 4)
    gltf["bufferViews"].append({"buffer": 0, "byteOffset": ibm_off, "byteLength": len(ident) * 4})
    gltf["accessors"].append({"bufferView": len(gltf["bufferViews"]) - 1, "componentType": 5126, "count": 4, "type": "MAT4"})
    gltf["buffers"][0]["byteLength"] = len(bin_bytes)
    gltf["skins"][0] = {"name": "Armature", "joints": [2, 3, 4, 5], "inverseBindMatrices": len(gltf["accessors"]) - 1}
    _escrever_glb(body_glb, gltf, bytes(bin_bytes))

    script = tmp_path / "check_sockets.gd"
    script.write_text(
        f"""extends SceneTree
const PostImport := preload({str(POST_IMPORT_GD)!r})

func _fail(msg: String, node: Node = null) -> void:
\tprint("SOCKET_FAIL " + msg)
\tif node != null:
\t\tnode.free()
\tquit(1)

func _initialize() -> void:
\tvar doc := GLTFDocument.new()
\tvar st := GLTFState.new()
\tdoc.append_from_file({str(body_glb)!r}, st)
\tvar body := doc.generate_scene(st)

\tvar arma := MeshInstance3D.new()
\tarma.name = "Espada"
\tarma.set_meta("forge3d_manifest", {{"anexo": {{"parte": "arma", "osso": "Hand.R"}}}})

\tvar escudo := MeshInstance3D.new()
\tescudo.name = "Escudo"
\tescudo.set_meta("forge3d_manifest", {{"anexo": {{"parte": "escudo", "osso": "LowerArm.L"}}}})

\tvar ombreira := MeshInstance3D.new()
\tombreira.name = "Ombreira"
\tombreira.set_meta("forge3d_manifest", {{"anexo": {{"parte": "ombreiras", "osso": "Shoulder.L"}}}})

\tvar cb := PostImport.montar_character_body(body, {{"Hand.R": arma, "LowerArm.L": escudo, "Shoulder.L": ombreira}})
\troot.add_child(cb)
\tawait process_frame

\tvar arma_ponta := (arma.global_transform.basis * Vector3(0.0, 1.0, 0.0)).normalized()
\tvar arma_fio := (arma.global_transform.basis * Vector3(1.0, 0.0, 0.0)).normalized()
\tif arma_ponta.dot(Vector3(0.0, 0.0, -1.0)) <= 0.9:
\t\t_fail("arma nao aponta para frente (-Z): " + str(arma_ponta), cb)
\t\treturn
\tif absf(arma_fio.y) <= 0.9:
\t\t_fail("fio da arma nao esta vertical: " + str(arma_fio), cb)
\t\treturn

\tvar esc_topo := (escudo.global_transform.basis * Vector3(0.0, 1.0, 0.0)).normalized()
\tvar esc_frente := (escudo.global_transform.basis * Vector3(0.0, 0.0, -1.0)).normalized()
\tif esc_topo.dot(Vector3(0.0, 1.0, 0.0)) <= 0.9:
\t\t_fail("escudo nao esta com topo para cima (+Y): " + str(esc_topo), cb)
\t\treturn
\tif esc_frente.dot(Vector3(1.0, 0.0, 0.0)) <= 0.9:
\t\t_fail("escudo nao aponta face externa para fora (+X): " + str(esc_frente), cb)
\t\treturn

\tvar omb_topo := (ombreira.global_transform.basis * Vector3(0.0, 1.0, 0.0)).normalized()
\tvar omb_frente := (ombreira.global_transform.basis * Vector3(0.0, 0.0, -1.0)).normalized()
\tif omb_topo.dot(Vector3(0.0, 1.0, 0.0)) <= 0.9 or omb_frente.dot(Vector3(0.0, 0.0, -1.0)) <= 0.9:
\t\t_fail("ombreira desalinhada: topo=%s frente=%s" % [omb_topo, omb_frente], cb)
\t\treturn

\tcb.queue_free()
\tprint("SOCKETS_OK")
\tquit(0)
""",
        encoding="utf-8",
    )
    proc = _rodar_godot(godot, ["--script", str(script)])
    assert proc.returncode == 0 and "SOCKETS_OK" in proc.stdout, proc.stdout + proc.stderr


def test_ucx_e_lod_preservam_transform_relativo_sob_pai_rotacionado(tmp_path: Path) -> None:
    import math

    godot = _exigir_godot()
    asset_id = "prop.rot.pai.01"
    glb = tmp_path / f"{asset_id}.glb"
    lod1_glb = tmp_path / f"{asset_id}_LOD1.glb"
    manifest = tmp_path / f"{asset_id}.manifest.json"

    q_90y = (0.0, math.sin(math.pi / 4.0), 0.0, math.cos(math.pi / 4.0))
    # LOD0: Corpo tem 90Y direto; PaiUCX tem 90Y e filho UCX_Corpo tem identidade
    _criar_glb_com_no_rotacionado(glb, "PaiUCX", q_90y, "UCX_Corpo", com_ucx=False)
    data = glb.read_bytes()
    jlen = struct.unpack_from("<I", data, 12)[0]
    blen = struct.unpack_from("<I", data, 20 + jlen)[0]
    gltf = json.loads(data[20 : 20 + jlen])
    bin_bytes = data[28 + jlen : 28 + jlen + blen]
    gltf["nodes"].append({"name": "Corpo", "mesh": 0, "rotation": list(q_90y)})
    gltf["scenes"][0]["nodes"] = [0, 2]
    _escrever_glb(glb, gltf, bin_bytes)

    # LOD1 com WrapperLOD1 rotacionado 90Y no root e Corpo_LOD1 com identidade
    _criar_glb_com_no_rotacionado(lod1_glb, "WrapperLOD1", q_90y, "Corpo_LOD1", com_ucx=False)
    manifest.write_text(
        json.dumps(
            {
                "schema": "forge3d/manifest@3",
                "asset_id": asset_id,
                "perfil": "godot4",
                "determinism": "D1",
                "lod": [
                    {"arquivo": f"{asset_id}.glb", "nivel": 0, "triangulos": 1},
                    {"arquivo": f"{asset_id}_LOD1.glb", "nivel": 1, "triangulos": 1},
                ],
            }
        ),
        encoding="utf-8",
    )
    corpo_gd = """
\tvar corpo := cena.find_child("Corpo", true, false) as MeshInstance3D
\tvar lod1 := cena.find_child("LOD1_Corpo", true, false) as MeshInstance3D
\tvar col := cena.find_child("UCX_Corpo_col", true, false) as StaticBody3D
\tif corpo == null or lod1 == null or col == null:
\t\t_fail("nodos ausentes", cena)
\t\treturn
\troot.add_child(cena)
\tawait process_frame
\tvar p := Vector3(0.2, 0.0, 0.0)
\tvar p_c := corpo.global_transform * p
\tvar p_l := lod1.global_transform * p
\tvar p_col := col.global_transform * p
\tif p_c.distance_to(p_l) > 0.001:
\t\t_fail("LOD1 desalinhado de LOD0: %s vs %s" % [p_c, p_l], cena)
\t\treturn
\tif p_c.distance_to(p_col) > 0.001:
\t\t_fail("UCX colisor desalinhado de LOD0: %s vs %s" % [p_c, p_col], cena)
\t\treturn
"""
    _validar_cena_godot(godot, tmp_path / "check_ucx_lod_rot.gd", corpo_gd, glb)


@pytest.mark.blender
def test_godot_rig_axes_check_end_to_end(tmp_path: Path) -> None:
    """Valida em Godot headless o script tools/godot_rig_axes_check.gd com rig e clipe reais."""
    import shutil
    from forge3d import animacao, profiles

    godot = _exigir_godot()
    blender = shutil.which("blender") or str(Path.home() / ".local" / "bin" / "blender")
    if not Path(blender).exists():
        pytest.skip("blender nao instalado")

    godot_perfil = profiles.carregar("godot4")
    clipes = animacao.clipes(godot_perfil, "godot-humanoid@1", ["jump"])
    clipes_json = tmp_path / "clipes.json"
    clipes_json.write_text(json.dumps(clipes), encoding="utf-8")

    body_glb = tmp_path / "body.glb"
    arma_glb = tmp_path / "arma.glb"
    escudo_glb = tmp_path / "escudo.glb"
    _criar_glb_com_no_rotacionado(arma_glb, "Espada", (0.0, 0.0, 0.0, 1.0), "EspadaMesh", com_ucx=False)
    _criar_glb_com_no_rotacionado(escudo_glb, "Escudo", (0.0, 0.0, 0.0, 1.0), "EscudoMesh", com_ucx=False)

    script = tmp_path / "mk_body.py"
    script.write_text(
        f"""
import json, sys
import bpy, bmesh
from mathutils import Vector
sys.path.insert(0, {str(RAIZ / "blender")!r})
import autorig, postprocess

bpy.ops.wm.read_factory_settings(use_empty=True)
bm = bmesh.new()
def add_seg(p0, p1, r=0.05):
    v0, v1 = Vector(p0), Vector(p1)
    d = v1 - v0
    ret = bmesh.ops.create_cube(bm, size=1.0)
    rot = d.normalized().to_track_quat("Z", "Y").to_matrix()
    for v in ret["verts"]:
        v.co = (v0 + v1) * 0.5 + (rot @ Vector((v.co.x * r * 2.0, v.co.y * r * 2.0, v.co.z * d.length)))
add_seg((0.0, 0.0, 0.85), (0.0, 0.0, 1.45), 0.14)
add_seg((0.0, 0.0, 1.45), (0.0, 0.0, 1.80), 0.10)
add_seg((0.11, 0.0, 0.02), (0.11, 0.0, 0.88), 0.065)
add_seg((-0.11, 0.0, 0.02), (-0.11, 0.0, 0.88), 0.065)
add_seg((0.11, -0.02, 0.04), (0.11, 0.16, 0.04), 0.045)
add_seg((-0.11, -0.02, 0.04), (-0.11, 0.16, 0.04), 0.045)
for s in (1.0, -1.0):
    add_seg((s * 0.17, 0.0, 1.38), (s * 0.31, -0.02, 1.15), 0.048)
    add_seg((s * 0.31, -0.02, 1.15), (s * 0.39, 0.22, 0.94), 0.042)
    add_seg((s * 0.39, 0.22, 0.94), (s * 0.43, 0.31, 0.86), 0.036)
bmesh.ops.subdivide_edges(bm, edges=list(bm.edges), cuts=2, use_grid_fill=True)
me = bpy.data.meshes.new("body")
bm.to_mesh(me)
bm.free()
obj = bpy.data.objects.new("body", me)
bpy.context.collection.objects.link(obj)

rig, _ = autorig.auto_rigar_humanoide(obj, "godot-humanoid@1", postprocess.criar_armadura)
with open({str(clipes_json)!r}, "r", encoding="utf-8") as fh:
    clipes = json.load(fh)
autorig.aplicar_animacoes_multi(rig, clipes)
bpy.ops.object.select_all(action="DESELECT")
rig.select_set(True)
obj.select_set(True)
bpy.ops.export_scene.gltf(
    filepath={str(body_glb)!r},
    use_selection=True,
    export_format="GLB",
    export_animations=True,
    export_nla_strips=True,
)
""",
        encoding="utf-8",
    )
    proc_bl = subprocess.run(
        [blender, "--background", "--factory-startup", "--python-exit-code", "1", "--python", str(script)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc_bl.returncode == 0, proc_bl.stdout + proc_bl.stderr

    proc = _rodar_godot(
        godot,
        [
            "--script",
            str(RAIZ / "tools" / "godot_rig_axes_check.gd"),
            "--",
            str(body_glb),
            str(arma_glb),
            str(escudo_glb),
        ],
    )
    assert proc.returncode == 0 and "RIG_AXES_OK" in proc.stdout, proc.stdout + proc.stderr

