"""Testes headless do plugin Godot 4 (BoneMap, sockets, transforms e eixos end-to-end)."""

from __future__ import annotations

import json
import math
import shutil
import struct
import subprocess
from pathlib import Path

import pytest

from tests.test_godot_addon import (
    POST_IMPORT_GD,
    RAIZ,
    _criar_glb_colisor,
    _criar_glb_multimesh,
    _criar_glb_rigged,
    _escrever_glb,
    _exigir_godot,
    _rodar_godot,
    _validar_cena_godot,
)


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


def test_bone_map_humanoid_aa_56_ossos(tmp_path: Path) -> None:
    godot = _exigir_godot()
    script = tmp_path / "check_bonemap_aa.gd"
    script.write_text(
        f"""extends SceneTree
const PostImport := preload({str(POST_IMPORT_GD)!r})

func _initialize() -> void:
\tvar bm := PostImport.criar_bone_map_humanoid("godot-humanoid-aa@1")
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
    assert mapeados.get("Root") == "Root", mapeados
    assert mapeados.get("Spine") == "Spine", mapeados
    assert mapeados.get("Chest") == "Chest", mapeados
    assert mapeados.get("UpperChest") == "Chest", mapeados
    assert mapeados.get("Jaw") == "Jaw", mapeados
    assert mapeados.get("LeftEye") == "Eye.L", mapeados
    assert mapeados.get("RightEye") == "Eye.R", mapeados
    assert mapeados.get("LeftThumbMetacarpal") == "Thumb1.L", mapeados
    assert mapeados.get("RightLittleDistal") == "Little3.R", mapeados
    assert len(mapeados) == 56


def test_montar_character_body_orienta_arma_escudo_e_ombreira(tmp_path: Path) -> None:
    godot = _exigir_godot()
    body_glb = tmp_path / "body.glb"
    _criar_glb_rigged(body_glb, "body", escala=1.0, com_animacoes=False)
    data = body_glb.read_bytes()
    jlen = struct.unpack_from("<I", data, 12)[0]
    blen = struct.unpack_from("<I", data, 20 + jlen)[0]
    gltf = json.loads(data[20 : 20 + jlen])
    bin_bytes = bytearray(data[28 + jlen : 28 + jlen + blen])
    ang = math.radians(15.0)
    sh_q = [0.0, 0.0, math.sin(math.pi / 4.0), math.cos(math.pi / 4.0)]
    arm_q = [0.0, 0.0, math.sin((math.pi - ang) / 2.0), math.cos((math.pi - ang) / 2.0)]
    gltf["nodes"] = [
        {"name": "Armature", "children": [1, 2]},
        {"name": "body", "mesh": 0, "skin": 0},
        {"name": "Hips", "children": [3, 5]},
        {"name": "Shoulder.L", "translation": [-0.1, 1.35, 0.0], "rotation": sh_q, "children": [4]},
        {"name": "LowerArm.L", "translation": [0.0, 0.15, 0.0], "rotation": arm_q},
        {"name": "Hand.R", "translation": [0.3, 1.0, 0.0], "rotation": [0.0, 0.0, math.sin((math.pi + ang) / 2.0), math.cos((math.pi + ang) / 2.0)]},
    ]
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
\tif esc_frente.dot(Vector3(-1.0, 0.0, 0.0)) <= 0.9:
\t\t_fail("escudo nao aponta face externa para fora (-X): " + str(esc_frente), cb)
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
    godot = _exigir_godot()
    asset_id = "prop.rot.pai.01"
    glb = tmp_path / f"{asset_id}.glb"
    lod1_glb = tmp_path / f"{asset_id}_LOD1.glb"
    manifest = tmp_path / f"{asset_id}.manifest.json"

    q_90y = (0.0, math.sin(math.pi / 4.0), 0.0, math.cos(math.pi / 4.0))
    _criar_glb_com_no_rotacionado(glb, "PaiUCX", q_90y, "UCX_Corpo", com_ucx=False)
    data = glb.read_bytes()
    jlen = struct.unpack_from("<I", data, 12)[0]
    blen = struct.unpack_from("<I", data, 20 + jlen)[0]
    gltf = json.loads(data[20 : 20 + jlen])
    bin_bytes = data[28 + jlen : 28 + jlen + blen]
    gltf["nodes"].append({"name": "Corpo", "mesh": 0, "rotation": list(q_90y)})
    gltf["scenes"][0]["nodes"] = [0, 2]
    _escrever_glb(glb, gltf, bin_bytes)

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


def test_headless_import_lod1_e_colisao_irmao_importer_mesh(tmp_path: Path) -> None:
    """Regressao M3.2: godot --headless --import processa ImporterMeshInstance3D em _LOD1 e _colisao."""
    godot = _exigir_godot()
    proj = tmp_path / "proj_import"
    (proj / "assets").mkdir(parents=True)
    shutil.copytree(RAIZ / "addons" / "forge3d", proj / "addons" / "forge3d")
    (proj / "project.godot").write_text(
        '[application]\nconfig/name="imp_test"\n'
        '[editor_plugins]\nenabled=PackedStringArray("res://addons/forge3d/plugin.cfg")\n',
        encoding="utf-8",
    )

    asset_id = "prop.imp.lodcol"
    _criar_glb_multimesh(proj / "assets" / f"{asset_id}.glb", ["BodyMesh"])
    _criar_glb_multimesh(proj / "assets" / f"{asset_id}_LOD1.glb", ["BodyMesh_LOD1"])
    _criar_glb_colisor(proj / "assets" / f"{asset_id}_colisao.glb", "ColPart")
    (proj / "assets" / f"{asset_id}.manifest.json").write_text(
        json.dumps(
            {
                "schema": "forge3d/manifest@6",
                "asset_id": asset_id,
                "perfil": "godot4",
                "tipo": "prop_estatico",
                "lod": [
                    {"arquivo": f"{asset_id}.glb", "nivel": 0, "triangulos": 1},
                    {"arquivo": f"{asset_id}_LOD1.glb", "nivel": 1, "triangulos": 1},
                ],
                "colisao": {"arquivo": f"{asset_id}_colisao.glb", "partes": 1, "tipo": "convex"},
            }
        ),
        encoding="utf-8",
    )

    imp = subprocess.run(
        [godot, "--headless", "--path", str(proj), "--import", "--quit"],
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert imp.returncode == 0, imp.stdout + imp.stderr

    verify_gd = tmp_path / "verify_imported.gd"
    verify_gd.write_text(
        f"""extends SceneTree
func _initialize() -> void:
\tvar packed := ResourceLoader.load("res://assets/{asset_id}.glb") as PackedScene
\tif packed == null:
\t\tprinterr("FAIL packed null"); quit(1); return
\tvar cena := packed.instantiate()
\tvar mis := cena.find_children("*", "MeshInstance3D", true, false)
\tvar sbs := cena.find_children("*", "StaticBody3D", true, false)
\tvar css := cena.find_children("*", "CollisionShape3D", true, false)
\tvar tem_lod1 := false
\tfor m in mis:
\t\tif String(m.name).begins_with("LOD1_"):
\t\t\ttem_lod1 = true
\tprint("IMP_CHECK mi=", mis.size(), " sb=", sbs.size(), " cs=", css.size(), " lod1=", tem_lod1)
\tcena.free()
\tif mis.size() < 2 or not tem_lod1 or sbs.size() < 1 or css.size() < 1:
\t\tquit(1); return
\tquit(0)
""",
        encoding="utf-8",
    )
    chk = subprocess.run(
        [godot, "--headless", "--path", str(proj), "--script", str(verify_gd)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert chk.returncode == 0 and "IMP_CHECK " in chk.stdout, chk.stdout + chk.stderr
