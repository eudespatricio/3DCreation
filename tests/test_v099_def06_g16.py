"""Testes TDD independentes (janela limpa) para v0.9.9: manifest@7, export-r15 Motor6D, autorig DEF-06 e Gate G16."""

from __future__ import annotations

import json
import math
import struct
import subprocess
import sys
from pathlib import Path
from xml.etree import ElementTree

import jsonschema
import pytest
import yaml

from forge3d import animacao, config, post, profiles, publish, qc, rbx, rbx_pbr, rbx_r15_model, verify, verify_g11
from forge3d.canonical import sha256_bytes
from forge3d.rbx_xml import JOINT_R15

RAIZ = Path(__file__).resolve().parents[1]
_R15_15: tuple[str, ...] = tuple(JOINT_R15.keys())


@pytest.fixture(autouse=True)
def _isolar_forge3d(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORGE3D_HOME", str(tmp_path / "forge_home"))
    monkeypatch.setenv("FORGE3D_CONFIG", str(tmp_path / "forge_cfg"))
    config.adicionar(tmp_path)


def _pack_glb(gltf: dict, buf: bytearray) -> bytes:
    buf.extend(b"\x00" * ((4 - len(buf) % 4) % 4))
    gltf["buffers"] = [{"byteLength": len(buf)}]
    jb = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    jb += b" " * ((4 - len(jb) % 4) % 4)
    total = 12 + 8 + len(jb) + 8 + len(buf)
    return (
        struct.pack("<III", 0x46546C67, 2, total)
        + struct.pack("<II", len(jb), 0x4E4F534A) + jb
        + struct.pack("<II", len(buf), 0x004E4942) + bytes(buf)
    )


def _add_bv(buf: bytearray, bvs: list[dict], raw: bytes, target: int | None = None) -> int:
    buf.extend(b"\x00" * ((4 - len(buf) % 4) % 4))
    bv: dict = {"buffer": 0, "byteOffset": len(buf), "byteLength": len(raw)}
    if target is not None:
        bv["target"] = target
    buf.extend(raw)
    bvs.append(bv)
    return len(bvs) - 1


def _box_geom(center: tuple[float, float, float], half: tuple[float, float, float]):
    cx, cy, cz = center
    hx, hy, hz = half
    verts = [
        (cx - hx, cy - hy, cz - hz), (cx + hx, cy - hy, cz - hz),
        (cx + hx, cy + hy, cz - hz), (cx - hx, cy + hy, cz - hz),
        (cx - hx, cy - hy, cz + hz), (cx + hx, cy - hy, cz + hz),
        (cx + hx, cy + hy, cz + hz), (cx - hx, cy + hy, cz + hz),
    ]
    tris = [
        (0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4),
        (2, 3, 7), (2, 7, 6), (0, 4, 7), (0, 7, 3), (1, 2, 6), (1, 6, 5),
    ]
    return verts, tris


def _multi_node_glb(
    nodes_boxes: dict[str, tuple[tuple[float, float, float], tuple[float, float, float]]],
    *,
    non_manifold_node: str | None = None,
) -> bytes:
    """GLB com 1 no/malha nomeado por parte (opcionalmente com aleta nao-manifold)."""
    buf, bvs, accessors, meshes, nodes = bytearray(), [], [], [], []
    for idx, (nome, (center, half)) in enumerate(nodes_boxes.items()):
        verts, tris = _box_geom(center, half)
        if non_manifold_node == nome:
            verts.append((center[0], center[1] - half[1] - 0.1, center[2] - half[2] - 0.1))
            tris.append((0, 1, len(verts) - 1))
        bv_p = _add_bv(buf, bvs, b"".join(struct.pack("<3f", *v) for v in verts), 34962)
        bv_n = _add_bv(buf, bvs, b"".join(struct.pack("<3f", 0.0, 1.0, 0.0) for _ in verts), 34962)
        bv_u = _add_bv(buf, bvs, b"".join(struct.pack("<2f", (i % 2) * 0.8 + 0.1, ((i // 2) % 2) * 0.8 + 0.1) for i in range(len(verts))), 34962)
        bv_i = _add_bv(buf, bvs, b"".join(struct.pack("<3H", *t) for t in tris), 34963)
        base = len(accessors)
        xs, ys, zs = [v[0] for v in verts], [v[1] for v in verts], [v[2] for v in verts]
        accessors.extend([
            {"bufferView": bv_p, "componentType": 5126, "count": len(verts), "type": "VEC3",
             "min": [min(xs), min(ys), min(zs)], "max": [max(xs), max(ys), max(zs)]},
            {"bufferView": bv_n, "componentType": 5126, "count": len(verts), "type": "VEC3"},
            {"bufferView": bv_u, "componentType": 5126, "count": len(verts), "type": "VEC2"},
            {"bufferView": bv_i, "componentType": 5123, "count": len(tris) * 3, "type": "SCALAR"},
        ])
        meshes.append({"name": nome, "primitives": [{"attributes": {"POSITION": base, "NORMAL": base + 1, "TEXCOORD_0": base + 2}, "indices": base + 3, "material": 0}]})
        nodes.append({"name": nome, "mesh": idx})
    gltf = {
        "asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": list(range(len(nodes)))}],
        "nodes": nodes, "meshes": meshes, "accessors": accessors, "bufferViews": bvs,
        "materials": [{"name": "mat0", "pbrMetallicRoughness": {"baseColorFactor": [0.7, 0.7, 0.7, 1.0]}}],
    }
    return _pack_glb(gltf, buf)


def _skinned_animated_glb(
    *, tear_def06: bool = False, rot_deg: float = 90.0, scale: float = 1.0,
    include_anim: bool = True, r15_bones: bool = False,
) -> bytes:
    """GLB skinned watertight com LBS real (limpo ou com rasgo DEF-06 > 10x)."""
    s = scale
    if r15_bones:
        verts, tris = _box_geom((0.0, 0.5 * s, 0.0), (0.25 * s, 0.5 * s, 0.25 * s))
        j_weights = [(1, 1.0)] * len(verts)  # LowerTorso (nao-raiz)
        joint_specs: list[tuple[str, int | None, tuple[float, float, float]]] = [
            ("HumanoidRootPart", None, (0.0, 0.0, 0.0)), ("LowerTorso", 0, (0.0, 0.5 * s, 0.0)),
            ("UpperTorso", 1, (0.0, 0.7 * s, 0.0)), ("Head", 2, (0.0, 0.9 * s, 0.0)),
            ("LeftUpperArm", 2, (0.2 * s, 0.8 * s, 0.0)), ("LeftLowerArm", 4, (0.3 * s, 0.8 * s, 0.0)),
            ("LeftHand", 5, (0.4 * s, 0.8 * s, 0.0)), ("RightUpperArm", 2, (-0.2 * s, 0.8 * s, 0.0)),
            ("RightLowerArm", 7, (-0.3 * s, 0.8 * s, 0.0)), ("RightHand", 8, (-0.4 * s, 0.8 * s, 0.0)),
            ("LeftUpperLeg", 1, (0.1 * s, 0.4 * s, 0.0)), ("LeftLowerLeg", 10, (0.1 * s, 0.2 * s, 0.0)),
            ("LeftFoot", 11, (0.1 * s, 0.05 * s, 0.0)), ("RightUpperLeg", 1, (-0.1 * s, 0.4 * s, 0.0)),
            ("RightLowerLeg", 13, (-0.1 * s, 0.2 * s, 0.0)), ("RightFoot", 14, (-0.1 * s, 0.05 * s, 0.0)),
        ]
        anim_slot = 10
    else:
        v_leg, t_leg = _box_geom((0.10 * s, 0.25 * s, 0.0), (0.05 * s, 0.20 * s, 0.05 * s))
        v_hand, t_hand = _box_geom((0.45 * s, 0.80 * s, 0.0), (0.01 * s, 0.01 * s, 0.01 * s))
        verts = v_leg + v_hand
        tris = t_leg + [(a + 8, b + 8, c + 8) for a, b, c in t_hand]
        j_weights = [(2, 1.0)] * 8 + [(5, 1.0)] * 8
        if tear_def06:
            # Vertices da mao presos na coxa (UpperLeg.L=slot 2) -> aresta de 0.02m estica > 20x.
            j_weights[8] = j_weights[9] = (2, 1.0)
        joint_specs = [
            ("Root", None, (0.0, 0.0, 0.0)), ("Hips", 0, (0.0, 0.50 * s, 0.0)),
            ("UpperLeg.L", 1, (0.10 * s, 0.45 * s, 0.0)), ("Chest", 1, (0.0, 0.75 * s, 0.0)),
            ("UpperArm.L", 3, (0.25 * s, 0.80 * s, 0.0)), ("Hand.L", 4, (0.45 * s, 0.80 * s, 0.0)),
        ]
        anim_slot = 2

    nodes: list[dict] = [{"name": "MeshNode", "mesh": 0, "skin": 0}]
    world_pos = [pos for _, _, pos in joint_specs]
    children_map: dict[int, list[int]] = {i: [] for i in range(len(joint_specs))}
    for i, (_, p_i, _) in enumerate(joint_specs):
        if p_i is not None:
            children_map[p_i].append(i + 1)
    for i, (nome, p_i, pos) in enumerate(joint_specs):
        p_pos = world_pos[p_i] if p_i is not None else (0.0, 0.0, 0.0)
        node_d: dict = {"name": nome, "translation": [pos[k] - p_pos[k] for k in range(3)]}
        if children_map[i]:
            node_d["children"] = children_map[i]
        nodes.append(node_d)

    buf, bvs = bytearray(), []
    bv_p = _add_bv(buf, bvs, b"".join(struct.pack("<3f", *v) for v in verts), 34962)
    bv_n = _add_bv(buf, bvs, b"".join(struct.pack("<3f", 0.0, 1.0, 0.0) for _ in verts), 34962)
    bv_u = _add_bv(buf, bvs, b"".join(struct.pack("<2f", (i % 2) * 0.8 + 0.1, ((i // 2) % 2) * 0.8 + 0.1) for i in range(len(verts))), 34962)
    bv_j = _add_bv(buf, bvs, b"".join(struct.pack("<4B", slot, 0, 0, 0) for slot, _ in j_weights), 34962)
    bv_w = _add_bv(buf, bvs, b"".join(struct.pack("<4f", w, 0.0, 0.0, 0.0) for _, w in j_weights), 34962)
    bv_i = _add_bv(buf, bvs, b"".join(struct.pack("<3H", *t) for t in tris), 34963)
    bv_ibm = _add_bv(buf, bvs, b"".join(struct.pack("<16f", 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, -px, -py, -pz, 1) for px, py, pz in world_pos))
    xs, ys, zs = [v[0] for v in verts], [v[1] for v in verts], [v[2] for v in verts]
    accessors: list[dict] = [
        {"bufferView": bv_p, "componentType": 5126, "count": len(verts), "type": "VEC3",
         "min": [min(xs), min(ys), min(zs)], "max": [max(xs), max(ys), max(zs)]},
        {"bufferView": bv_n, "componentType": 5126, "count": len(verts), "type": "VEC3"},
        {"bufferView": bv_u, "componentType": 5126, "count": len(verts), "type": "VEC2"},
        {"bufferView": bv_j, "componentType": 5121, "count": len(verts), "type": "VEC4"},
        {"bufferView": bv_w, "componentType": 5126, "count": len(verts), "type": "VEC4"},
        {"bufferView": bv_i, "componentType": 5123, "count": len(tris) * 3, "type": "SCALAR"},
        {"bufferView": bv_ibm, "componentType": 5126, "count": len(joint_specs), "type": "MAT4"},
    ]
    gltf: dict = {
        "asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0, 1]}], "nodes": nodes,
        "skins": [{"joints": list(range(1, len(joint_specs) + 1)), "inverseBindMatrices": 6}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1, "TEXCOORD_0": 2, "JOINTS_0": 3, "WEIGHTS_0": 4}, "indices": 5, "material": 0}]}],
        "materials": [{"name": "mat0", "pbrMetallicRoughness": {"baseColorFactor": [0.7, 0.7, 0.7, 1.0]}}],
        "accessors": accessors, "bufferViews": bvs,
    }
    if include_anim:
        hr = math.radians(rot_deg) / 2.0
        bv_t = _add_bv(buf, bvs, struct.pack("<3f", 0.0, 0.5, 1.0))
        bv_r = _add_bv(buf, bvs, struct.pack("<12f", 0, 0, 0, 1, math.sin(hr), 0, 0, math.cos(hr), 0, 0, 0, 1))
        acc_t, acc_r = len(accessors), len(accessors) + 1
        accessors.extend([
            {"bufferView": bv_t, "componentType": 5126, "count": 3, "type": "SCALAR", "min": [0.0], "max": [1.0]},
            {"bufferView": bv_r, "componentType": 5126, "count": 3, "type": "VEC4"},
        ])
        gltf["animations"] = [{"name": "walk", "channels": [{"sampler": 0, "target": {"node": anim_slot + 1, "path": "rotation"}}],
                               "samplers": [{"input": acc_t, "interpolation": "LINEAR", "output": acc_r}]}]
    return _pack_glb(gltf, buf)


# ------------------------------------------------------------------ Contrato 1: manifest@7 + retrocompat@6 + G11 + rbx_pbr
def test_c1_manifesto_v7_emissao_e_schema() -> None:
    perfil = profiles.carregar("roblox-aa-80")
    resultado = {
        "determinism": "D2", "partes_combinadas": "hero_partes_combinadas.glb",
        "ancoras": {"Root": [0.0, 0.0, 0.0], "Waist": [0.0, 1.0, 0.0]},
        "arquivos": [
            {"caminho": "hero.glb", "papel": "mesh", "sha256": "sha256:" + "0" * 64, "bytes": 100, "nivel": 0, "triangulos": 400},
            {"caminho": "LowerTorso.glb", "papel": "parte", "sha256": "sha256:" + "1" * 64, "bytes": 50},
            {"caminho": "UpperTorso.glb", "papel": "parte", "sha256": "sha256:" + "2" * 64, "bytes": 50},
            {"caminho": "hero_partes_combinadas.glb", "papel": "partes_combinadas", "sha256": "sha256:" + "3" * 64, "bytes": 120},
        ],
        "partes": [
            {"nome": "LowerTorso", "junta": "Root", "ancora": [0.0, 0.0, 0.0], "centro_bbox": [0.0, 0.5, 0.0], "bbox": [1.0, 1.0, 1.0], "triangulos": 200, "arquivo": "LowerTorso.glb"},
            {"nome": "UpperTorso", "junta": "Waist", "ancora": [0.0, 1.0, 0.0], "centro_bbox": [0.0, 1.5, 0.0], "bbox": [1.0, 1.0, 1.0], "triangulos": 200, "arquivo": "UpperTorso.glb"},
        ],
    }
    man = publish.montar_manifesto(
        item={"id": "hero.r15.01", "tipo": "personagem_humanoide", "rota": "mesh", "auto_rig": True, "esqueleto": "r15@1",
              "tags": ["teste"], "partes": [{"nome": "LowerTorso", "junta": "Root"}, {"nome": "UpperTorso", "junta": "Waist"}],
              "rig": {"modo": "motor6d", "esqueleto": "r15@1"}},
        spec_doc={"projeto": "demo", "perfil": "roblox-aa-80"}, spec_hash="sha256:" + "a" * 64,
        perfil_nome="roblox-aa-80", perfil=perfil, provider={"nome": "mesh", "versao": "1.0", "determinism": "D2"},
        resultado=resultado, licenca={"modelo": "TripoSR", "uso_comercial": True, "notice": "MIT"}, run_id="20261121T000000Z-v099",
        relatorio_qc={"aprovado": True, "gates": [{"id": "G1", "status": "ok"}, {"id": "G16", "status": "ok", "medido": {"aplicavel": True, "modo": "motor6d_rigido", "max_stretch": 1.0}}],
                      "medidas": {"triangulos": 400, "vertices": 200, "bbox_m": [1.0, 2.0, 1.0], "materiais": 1, "esqueleto": "r15@1", "ossos": 16, "animacoes": []}},
    )
    assert man["schema"] == "forge3d/manifest@7"
    assert man["rig"]["partes_combinadas"] == "hero_partes_combinadas.glb"
    assert man["partes"][0]["centro_bbox"] == [0.0, 0.5, 0.0]
    assert any(f["papel"] == "partes_combinadas" for f in man["files"])
    assert any(g["id"] == "G16" for g in man["qc"]["gates"])

    val = jsonschema.Draft202012Validator(json.loads((RAIZ / "schemas" / "manifest.v7.schema.json").read_text(encoding="utf-8")))
    val.validate(man)
    bad_bbox = json.loads(json.dumps(man))
    bad_bbox["partes"][0]["centro_bbox"] = [0.0, 0.5]
    with pytest.raises(jsonschema.ValidationError):
        val.validate(bad_bbox)
    bad_gate = json.loads(json.dumps(man))
    bad_gate["qc"]["gates"].append({"id": "G99", "status": "ok"})
    with pytest.raises(jsonschema.ValidationError):
        val.validate(bad_gate)


def test_c1_verify_retrocompat_v6_e_integridade_v7(tmp_path: Path) -> None:
    perfil = profiles.carregar("roblox-r15")
    escala = float(perfil["unidades"]["escala_saida"])
    lic = {"modelo": "procedural", "uso_comercial": True, "notice": "MIT"}

    # 1) Bundle legado forge3d/manifest@6 (sem G16 nem partes_combinadas) continua aceito.
    dest_v6 = tmp_path / "dest_v6"
    dest_v6.mkdir()
    raw_v6 = _multi_node_glb({"mesh_node": ((0.0, 0.5 * escala, 0.0), (0.25 * escala, 0.5 * escala, 0.25 * escala))})
    (dest_v6 / "prop.legacy.01.glb").write_bytes(raw_v6)
    g_v6, b_v6 = qc.ler_glb_bin(raw_v6)
    item_v6 = {"id": "prop.legacy.01", "tipo": "prop_estatico", "rota": "blocky", "altura_metros": 1.0,
               "pivot": "base", "limite_triangulos": 500, "colisao": "none", "lod": [100], "tags": ["teste"]}
    res_v6_in = {"determinism": "D1", "licenca": lic, "medidas": {**qc.topologia(g_v6, b_v6), "partes_colisao": 0},
                 "arquivos": [{"caminho": "prop.legacy.01.glb", "papel": "mesh", "sha256": sha256_bytes(raw_v6), "bytes": len(raw_v6), "nivel": 0, "triangulos": 12}]}
    man_v6 = publish.montar_manifesto(
        item=item_v6, spec_doc={"projeto": "demo", "perfil": "roblox-r15"}, spec_hash="sha256:" + "a" * 64,
        perfil_nome="roblox-r15", perfil=perfil, provider={"nome": "blocky", "versao": "1.0", "determinism": "D1"},
        resultado=res_v6_in, relatorio_qc=qc.verificar(item_v6, perfil, dest_v6, res_v6_in, escala_saida=escala),
        licenca=lic, run_id="20261121T000000Z-v6",
    )
    man_v6["schema"] = "forge3d/manifest@6"
    man_v6["qc"]["gates"] = [g for g in man_v6["qc"]["gates"] if g["id"] != "G16"]
    jsonschema.Draft202012Validator(json.loads((RAIZ / "schemas" / "manifest.v6.schema.json").read_text(encoding="utf-8"))).validate(man_v6)
    (dest_v6 / "prop.legacy.01.manifest.json").write_text(json.dumps(man_v6, indent=1), encoding="utf-8")
    ver_v6 = verify.verificar(dest_v6)
    assert ver_v6["ok"] is True, ver_v6

    # 2) Bundle v7 motor6d com partes_combinadas.glb: valido -> tamper falha -> delete falha.
    dest_v7 = tmp_path / "dest_v7"
    dest_v7.mkdir()
    raw_main = _skinned_animated_glb(scale=escala, include_anim=False, r15_bones=True)
    raw_lt = _multi_node_glb({"LowerTorso": ((0.0, 0.10 * escala, 0.0), (0.2 * escala, 0.10 * escala, 0.2 * escala))})
    raw_ut = _multi_node_glb({"UpperTorso": ((0.0, 0.15 * escala, 0.0), (0.2 * escala, 0.15 * escala, 0.2 * escala))})
    raw_comb = _multi_node_glb({
        "LowerTorso": ((0.0, 0.60 * escala, 0.0), (0.2 * escala, 0.10 * escala, 0.2 * escala)),
        "UpperTorso": ((0.0, 0.85 * escala, 0.0), (0.2 * escala, 0.15 * escala, 0.2 * escala)),
    })
    (dest_v7 / "hero.v7.01.glb").write_bytes(raw_main)
    (dest_v7 / "LowerTorso.glb").write_bytes(raw_lt)
    (dest_v7 / "UpperTorso.glb").write_bytes(raw_ut)
    comb_path = dest_v7 / "hero.v7.01_partes_combinadas.glb"
    comb_path.write_bytes(raw_comb)
    g_m, b_m = qc.ler_glb_bin(raw_main)
    partes_v7 = [
        {"nome": "LowerTorso", "junta": "Root", "ancora": [0.0, 0.5 * escala, 0.0], "centro_bbox": [0.0, 0.6 * escala, 0.0],
         "bbox": [0.4 * escala, 0.2 * escala, 0.4 * escala], "triangulos": 12, "arquivo": "LowerTorso.glb"},
        {"nome": "UpperTorso", "junta": "Waist", "ancora": [0.0, 0.7 * escala, 0.0], "centro_bbox": [0.0, 0.85 * escala, 0.0],
         "bbox": [0.4 * escala, 0.3 * escala, 0.4 * escala], "triangulos": 12, "arquivo": "UpperTorso.glb"},
    ]
    item_v7 = {"id": "hero.v7.01", "tipo": "prop_estatico", "rota": "blocky", "altura_metros": 1.0, "pivot": "base",
               "limite_triangulos": 500, "colisao": "none", "lod": [100], "tags": ["teste"],
               "auto_rig": True, "esqueleto": "r15@1", "partes": partes_v7, "rig": {"modo": "motor6d", "esqueleto": "r15@1"}}
    res_v7_in = {
        "determinism": "D1", "licenca": lic, "medidas": {**qc.topologia(g_m, b_m), "partes_colisao": 0},
        "partes": partes_v7, "ancoras": {"Root": [0.0, 0.5 * escala, 0.0], "Waist": [0.0, 0.7 * escala, 0.0]},
        "partes_combinadas": comb_path.name,
        "arquivos": [
            {"caminho": "hero.v7.01.glb", "papel": "mesh", "sha256": sha256_bytes(raw_main), "bytes": len(raw_main), "nivel": 0, "triangulos": 12},
            {"caminho": "LowerTorso.glb", "papel": "parte", "sha256": sha256_bytes(raw_lt), "bytes": len(raw_lt)},
            {"caminho": "UpperTorso.glb", "papel": "parte", "sha256": sha256_bytes(raw_ut), "bytes": len(raw_ut)},
            {"caminho": comb_path.name, "papel": "partes_combinadas", "sha256": sha256_bytes(raw_comb), "bytes": len(raw_comb)},
        ],
    }
    rel_qc_v7 = qc.verificar(item_v7, perfil, dest_v7, res_v7_in, escala_saida=escala)
    assert rel_qc_v7["aprovado"] is True, rel_qc_v7
    man_v7 = publish.montar_manifesto(
        item=item_v7, spec_doc={"projeto": "demo", "perfil": "roblox-r15"}, spec_hash="sha256:" + "b" * 64,
        perfil_nome="roblox-r15", perfil=perfil, provider={"nome": "blocky", "versao": "1.0", "determinism": "D1"},
        resultado=res_v7_in, relatorio_qc=rel_qc_v7, licenca=lic, run_id="20261121T000000Z-v7",
    )
    assert man_v7["schema"] == "forge3d/manifest@7"
    (dest_v7 / "hero.v7.01.manifest.json").write_text(json.dumps(man_v7, indent=1), encoding="utf-8")
    assert verify.verificar(dest_v7)["ok"] is True

    comb_path.write_bytes(raw_comb + b"\x00\x00\x00\x00")
    ver_tamper = verify.verificar(dest_v7)
    assert ver_tamper["ok"] is False and ver_tamper["erros"]

    # Substituir partes_combinadas.glb por GLB nao-manifold COM hash atualizado -> G16 reprova no verify.
    raw_bad_comb = _multi_node_glb({
        "LowerTorso": ((0.0, 0.60 * escala, 0.0), (0.2 * escala, 0.10 * escala, 0.2 * escala)),
        "UpperTorso": ((0.0, 0.85 * escala, 0.0), (0.2 * escala, 0.15 * escala, 0.2 * escala)),
    }, non_manifold_node="UpperTorso")
    comb_path.write_bytes(raw_bad_comb)
    man_v7_bad = json.loads(json.dumps(man_v7))
    for f_entry in man_v7_bad["files"]:
        if f_entry["papel"] == "partes_combinadas":
            f_entry["sha256"], f_entry["bytes"] = sha256_bytes(raw_bad_comb), len(raw_bad_comb)
    (dest_v7 / "hero.v7.01.manifest.json").write_text(json.dumps(man_v7_bad, indent=1), encoding="utf-8")
    ver_g16_fail = verify.verificar(dest_v7)
    assert ver_g16_fail["ok"] is False and ver_g16_fail["erros"]

    comb_path.unlink()
    ver_missing = verify.verificar(dest_v7)
    assert ver_missing["ok"] is False and ver_missing["erros"]


def test_c1_g11_nao_duplica_partes_combinadas(tmp_path: Path) -> None:
    perfil = profiles.carregar("roblox-aa-80")
    p1 = _multi_node_glb({"LowerTorso": ((0.0, 0.5, 0.0), (0.2, 0.5, 0.2))})
    p2 = _multi_node_glb({"UpperTorso": ((0.0, 1.5, 0.0), (0.2, 0.5, 0.2))})
    pc = _multi_node_glb({"LowerTorso": ((0.0, 0.5, 0.0), (0.2, 0.5, 0.2)), "UpperTorso": ((0.0, 1.5, 0.0), (0.2, 0.5, 0.2))})
    (tmp_path / "LowerTorso.glb").write_bytes(p1)
    (tmp_path / "UpperTorso.glb").write_bytes(p2)
    (tmp_path / "hero_partes_combinadas.glb").write_bytes(pc)

    base_files = [
        {"caminho": "hero.glb", "papel": "mesh", "sha256": "sha256:" + "0" * 64, "bytes": 100},
        {"caminho": "LowerTorso.glb", "papel": "parte", "sha256": sha256_bytes(p1), "bytes": len(p1)},
        {"caminho": "UpperTorso.glb", "papel": "parte", "sha256": sha256_bytes(p2), "bytes": len(p2)},
    ]
    partes = [{"nome": "LowerTorso", "triangulos": 12, "arquivo": "LowerTorso.glb"}, {"nome": "UpperTorso", "triangulos": 12, "arquivo": "UpperTorso.glb"}]
    man_sem = {"schema": "forge3d/manifest@7", "asset_id": "hero.g11.01", "geometry": {"triangulos": 24}, "files": base_files, "partes": partes, "rig": {"modo": "motor6d"}}
    man_com = {**man_sem, "files": [*base_files, {"caminho": "hero_partes_combinadas.glb", "papel": "partes_combinadas", "sha256": sha256_bytes(pc), "bytes": len(pc)}]}
    reval = {"medidas": {"triangulos": 24, "primitivas": 1, "ossos": 16}, "gates": []}
    e_s, e_c = [], []
    prim_s, tris_s = verify_g11._validar_partes_manifesto(man_sem, tmp_path, perfil, False, "sem.json", e_s)
    prim_c, tris_c = verify_g11._validar_partes_manifesto(man_com, tmp_path, perfil, False, "com.json", e_c)
    assert e_s == [] and e_c == [] and prim_c == prim_s == 2 and tris_c == tris_s == 24
    med_s = verify_g11._medir_manifesto_g11(man_sem, tmp_path, reval, {"id": "hero.g11.01"}, prim_partes=prim_s, tris_partes=tris_s)
    med_c = verify_g11._medir_manifesto_g11(man_com, tmp_path, reval, {"id": "hero.g11.01"}, prim_partes=prim_c, tris_partes=tris_c)
    assert med_c["tris"] == med_s["tris"] == 24 and med_c["primitivas"] == med_s["primitivas"] == 2


def test_c1_rbx_pbr_manifesto_v7_sem_fallback_orm(tmp_path: Path) -> None:
    (tmp_path / "hero.01_albedo.png").write_bytes(b"png")
    (tmp_path / "hero.01_orm.png").write_bytes(b"png")
    arqs = [{"caminho": "hero.01_albedo.png", "papel": "textura"}, {"caminho": "hero.01_orm.png", "papel": "orm"}]
    m_v7 = rbx_pbr._extrair_mapas_pbr_manifesto_dict({"schema": "forge3d/manifest@7", "files": arqs}, pasta_base=tmp_path, id_efetivo="hero.01")
    assert m_v7.get("ColorMap") == "hero.01_albedo.png" and "RoughnessMap" not in m_v7
    m_v5 = rbx_pbr._extrair_mapas_pbr_manifesto_dict({"schema": "forge3d/manifest@5", "files": arqs}, pasta_base=tmp_path, id_efetivo="hero.01")
    assert m_v5.get("RoughnessMap") == "hero.01_orm.png"


# ------------------------------------------------------------------ Contrato 2: export-r15 --model-id Motor6D vs bone
def _fixture_r15_lote_e_manifesto(tmp_path: Path) -> tuple[Path, dict]:
    dest = tmp_path / "dest_r15"
    dest.mkdir()
    lote_yaml = tmp_path / "lote_r15.yaml"
    lote_yaml.write_text(yaml.safe_dump({
        "schema": "forge3d/spec@6", "projeto": "demo", "perfil": "roblox-aa-80", "destino_exportacao": str(dest),
        "lote": [{"id": "hero.r15.01", "tipo": "personagem_humanoide", "rota": "mesh", "prompt": "guerreiro medieval",
                  "seed": 42, "altura_metros": 1.85, "auto_rig": True, "esqueleto": "r15@1",
                  "animacoes_base": ["idle", "walk"], "partes": [{"nome": n, "junta": JOINT_R15[n]} for n in _R15_15],
                  "rig": {"modo": "motor6d", "esqueleto": "r15@1"}}],
    }), encoding="utf-8")
    partes, ancoras = [], {}
    for idx, nome in enumerate(_R15_15):
        junta = JOINT_R15[nome]
        anc = [0.0, round(0.5 + idx * 0.25, 3), 0.0]
        ancoras[junta] = anc
        partes.append({"nome": nome, "junta": junta, "ancora": anc, "centro_bbox": [0.0, round(anc[1] + 0.12, 3), 0.0],
                       "bbox": [0.8, 0.8, 0.8], "triangulos": 120, "arquivo": f"{nome}.glb"})
    man = {
        "schema": "forge3d/manifest@7", "asset_id": "hero.r15.01", "partes": partes,
        "rig": {"esqueleto": "r15@1", "ossos": 16, "modo": "motor6d", "ancoras": ancoras, "partes_combinadas": "hero.r15.01_partes_combinadas.glb"},
        "files": [{"caminho": f"{n}.glb", "papel": "parte"} for n in _R15_15] + [{"caminho": "hero.r15.01_partes_combinadas.glb", "papel": "partes_combinadas"}],
    }
    return lote_yaml, man


def _script_source(xml_path: Path, name: str) -> str:
    root = ElementTree.fromstring(xml_path.read_text(encoding="utf-8"))
    found = [e.findtext("Properties/ProtectedString[@name='Source']") or "" for e in root.iter("Item")
             if e.get("class") == "Script" and (e.findtext("Properties/string[@name='Name']") or "") == name]
    assert len(found) == 1
    return found[0]


def test_c2_export_r15_model_id_motor6d_default_vs_bone(tmp_path: Path) -> None:
    lote_yaml, man = _fixture_r15_lote_e_manifesto(tmp_path)
    mid = "72623231126473"

    out_m6d = tmp_path / "hero_m6d.rbxlx"
    rel_m6d = rbx.exportar_r15(lote_yaml, "hero.r15.01", saida=out_m6d, model_id=mid, manifesto=man)
    assert rel_m6d["ok"] is True and rel_m6d["modo_rig"] == "model"
    assert rel_m6d["montagem_motor6d"] is True and rel_m6d["partes"] == 16 and rel_m6d["motores"] == 15
    src_m6d = _script_source(out_m6d, "Forge3DLoadModel")
    assert f"InsertService:LoadAsset({mid})" in src_m6d or (mid in src_m6d and "InsertService:LoadAsset(" in src_m6d)
    assert 'Instance.new("Motor6D")' in src_m6d or "Instance.new('Motor6D')" in src_m6d
    for token in ("HumanoidRootPart", "ToObjectSpace", "Anchored = false",
                  "AnimationController", "Animator", "Forge3DModelReady"):
        assert token in src_m6d, f"Token ausente no script: {token}"
    for parte_nome, junta_nome in JOINT_R15.items():
        assert parte_nome in src_m6d and junta_nome in src_m6d

    out_bone = tmp_path / "hero_bone.rbxlx"
    rel_bone = rbx.exportar_r15(lote_yaml, "hero.r15.01", saida=out_bone, modo_rig="bone", model_id=mid, manifesto=man)
    assert rel_bone["ok"] is True and rel_bone["montagem_motor6d"] is False
    src_bone = _script_source(out_bone, "Forge3DLoadModel")
    assert "InsertService:LoadAsset(" in src_bone and "Forge3DModelReady" in src_bone
    assert 'Instance.new("Motor6D")' not in src_bone and "ToObjectSpace" not in src_bone


def test_c2_resolver_model_id_prioriza_partes_combinadas(tmp_path: Path) -> None:
    # Entrada partes_combinadas vem ANTES da generica para evitar falso positivo de "ultima linha vence".
    ledger_a = tmp_path / "ledger_a.jsonl"
    ledger_a.write_text("\n".join([
        json.dumps({"id": "hero.r15.01_partes_combinadas", "role": "model", "arquivo": "hero.r15.01_partes_combinadas.glb", "asset_id": "72623231126473"}),
        json.dumps({"id": "hero.r15.01", "role": "model", "arquivo": "hero.r15.01.glb", "asset_id": "111111111"}),
    ]) + "\n", encoding="utf-8")
    assert rbx_r15_model.resolver_model_id("auto", "hero.r15.01", ledger=ledger_a, modo_rig="motor6d") == "72623231126473"
    assert rbx_r15_model.resolver_model_id("auto", "hero.r15.01", ledger=ledger_a, modo_rig="bone") == "111111111"

    ledger_b = tmp_path / "ledger_b.jsonl"
    ledger_b.write_text("\n".join([
        json.dumps({"id": "hero.r15.01", "role": "partes_combinadas", "arquivo": "saida/hero.r15.01_partes_combinadas.glb", "asset_id": "999888777"}),
        json.dumps({"id": "hero.r15.01", "role": "model", "arquivo": "saida/hero.r15.01.glb", "asset_id": "222222222"}),
    ]) + "\n", encoding="utf-8")
    assert rbx_r15_model.resolver_model_id("auto", "hero.r15.01", ledger=ledger_b, modo_rig="motor6d") == "999888777"


# ------------------------------------------------------------------ Contrato 3: autorig skinning hardening (unit + Blender)
def _dist_hier_par(dist_hier: dict, a: str, b: str) -> int:
    if (a, b) in dist_hier:
        return int(dist_hier[(a, b)])
    if (b, a) in dist_hier:
        return int(dist_hier[(b, a)])
    sub = dist_hier.get(a)
    return int(sub[b]) if isinstance(sub, dict) and b in sub else 999


def test_c3_autorig_pesos_coerencia_unitario() -> None:
    blender_dir = str(RAIZ / "blender")
    if blender_dir not in sys.path:
        sys.path.insert(0, blender_dir)
    import autorig_pesos_coerencia as apc

    assert apc.MAX_INFLUENCIAS_VERTICE == 3
    top3 = apc.normalizar_top_k([(0.5, "A"), (0.3, "B"), (0.15, "C"), (0.05, "D")], max_k=3)
    assert [n for n, _ in top3] == ["A", "B", "C"] and sum(w for _, w in top3) == pytest.approx(1.0, abs=1e-6)

    ossos_g = [
        {"nome": "Root", "pai": None}, {"nome": "Hips", "pai": "Root"}, {"nome": "Spine", "pai": "Hips"},
        {"nome": "Chest", "pai": "Spine"}, {"nome": "Neck", "pai": "Chest"}, {"nome": "Head", "pai": "Neck"},
        {"nome": "Shoulder.L", "pai": "Chest"}, {"nome": "UpperArm.L", "pai": "Shoulder.L"},
        {"nome": "LowerArm.L", "pai": "UpperArm.L"}, {"nome": "Hand.L", "pai": "LowerArm.L"},
        {"nome": "Shoulder.R", "pai": "Chest"}, {"nome": "UpperArm.R", "pai": "Shoulder.R"},
        {"nome": "LowerArm.R", "pai": "UpperArm.R"}, {"nome": "Hand.R", "pai": "LowerArm.R"},
        {"nome": "UpperLeg.L", "pai": "Hips"}, {"nome": "UpperLeg.R", "pai": "Hips"},
    ]
    _, dist_g, lca_g = apc.construir_hierarquia_ossos(ossos_g)
    assert lca_g("Head", "UpperArm.L") == "Chest"
    r_head = apc.filtrar_pesos_coerentes([(0.65, "Head"), (0.25, "Neck"), (0.10, "UpperArm.L")], dist_g, max_k=3)
    assert "UpperArm.L" not in dict(r_head) and sum(w for _, w in r_head) == pytest.approx(1.0, abs=1e-6)
    r_hips = apc.filtrar_pesos_coerentes([(0.55, "Hips"), (0.20, "Spine"), (0.15, "UpperLeg.L"), (0.08, "UpperLeg.R"), (0.25, "LowerArm.R")], dist_g, max_k=3)
    assert "LowerArm.R" not in dict(r_hips) and len(r_hips) <= 3 and sum(w for _, w in r_hips) == pytest.approx(1.0, abs=1e-6)

    ossos_r15 = [
        {"nome": "HumanoidRootPart", "pai": None}, {"nome": "LowerTorso", "pai": "HumanoidRootPart"},
        {"nome": "UpperTorso", "pai": "LowerTorso"}, {"nome": "LeftUpperArm", "pai": "UpperTorso"},
        {"nome": "LeftLowerArm", "pai": "LeftUpperArm"}, {"nome": "LeftHand", "pai": "LeftLowerArm"},
        {"nome": "LeftUpperLeg", "pai": "LowerTorso"}, {"nome": "RightUpperLeg", "pai": "LowerTorso"},
    ]
    _, dist_r15, _ = apc.construir_hierarquia_ossos(ossos_r15)
    r_hand = apc.filtrar_pesos_coerentes([(0.60, "LeftHand"), (0.30, "LeftUpperLeg"), (0.10, "LeftLowerArm")], dist_r15, max_k=3)
    assert "LeftUpperLeg" not in dict(r_hand) and "LeftHand" in dict(r_hand) and sum(w for _, w in r_hand) == pytest.approx(1.0, abs=1e-6)

    # Root / HumanoidRootPart NAO podem servir de atalho entre pernas ou bracos opostos
    ossos_at = [
        {"nome": "Root", "pai": None}, {"nome": "UpperLeg.L", "pai": "Root"}, {"nome": "UpperLeg.R", "pai": "Root"},
        {"nome": "HumanoidRootPart", "pai": None}, {"nome": "LeftUpperArm", "pai": "HumanoidRootPart"}, {"nome": "RightUpperArm", "pai": "HumanoidRootPart"},
    ]
    _, dist_at, lca_at = apc.construir_hierarquia_ossos(ossos_at)
    assert lca_at("UpperLeg.L", "UpperLeg.R") is None
    assert _dist_hier_par(dist_at, "UpperLeg.L", "UpperLeg.R") >= 3
    assert _dist_hier_par(dist_at, "LeftUpperArm", "RightUpperArm") >= 3
    assert dict(apc.filtrar_pesos_coerentes([(0.7, "UpperLeg.L"), (0.3, "UpperLeg.R")], dist_at, max_k=3)) == {"UpperLeg.L": pytest.approx(1.0, abs=1e-6)}


@pytest.mark.blender
def test_c3_autorig_blender_ombreiras_cinto_e_coerencia(tmp_path: Path) -> None:
    try:
        ok, _ = post.preflight()
        blender = post.binario() if ok else None
    except Exception:
        blender = None
    if not blender:
        pytest.skip("Blender 4.2 nao disponivel neste ambiente")

    clipes = animacao.clipes(profiles.carregar("godot4-aa"), "godot-humanoid-aa@1", ["walk", "attack"])
    cfg_path, out_json, script = tmp_path / "cfg.json", tmp_path / "res.json", tmp_path / "run_c3.py"
    cfg_path.write_text(json.dumps({"blender_dir": str(RAIZ / "blender"), "clipes": clipes, "out_json": str(out_json)}), encoding="utf-8")
    script.write_text(
        """
import json, sys, bpy, bmesh
cfg = json.loads(open(sys.argv[-1], encoding="utf-8").read())
sys.path.insert(0, cfg["blender_dir"])
import autorig, autorig_pesos_coerencia as apc, postprocess

bpy.ops.wm.read_factory_settings(use_empty=True)
bm = bmesh.new()
def add_box(target, cx, cy, cz, sx, sy, sz):
    for v in bmesh.ops.create_cube(target, size=1.0)["verts"]:
        v.co.x, v.co.y, v.co.z = v.co.x * sx + cx, v.co.y * sy + cy, v.co.z * sz + cz

for args in ((0,0,1.06,.28,.16,.56),(0,0,1.42,.11,.11,.14),(0,0,1.67,.20,.22,.34),(.11,0,.42,.13,.13,.84),(-.11,0,.42,.13,.13,.84),(.29,0,1.04,.10,.10,.68),(-.29,0,1.04,.10,.10,.68),(.45,0,1.58,.38,.18,.14),(-.45,0,1.58,.38,.18,.14)):
    add_box(bm, *args)
bmesh.ops.subdivide_edges(bm, edges=list(bm.edges), cuts=2, use_grid_fill=True)
bm_belt = bmesh.new()
for cx, cy, sx, sy in ((0,.12,.36,.04),(0,-.12,.36,.04),(.18,0,.04,.22),(-.18,0,.04,.22)):
    add_box(bm_belt, cx, cy, 0.90, sx, sy, 0.08)
bmesh.ops.subdivide_edges(bm_belt, edges=list(bm_belt.edges), cuts=1, use_grid_fill=True)
me_belt = bpy.data.meshes.new("belt_tmp"); bm_belt.to_mesh(me_belt); bm_belt.free()
n_body = len(bm.verts); bm.from_mesh(me_belt); bpy.data.meshes.remove(me_belt)

me = bpy.data.meshes.new("hero_aa"); bm.to_mesh(me); bm.free()
obj = bpy.data.objects.new("hero_aa", me); bpy.context.collection.objects.link(obj)
rig_obj, _ = autorig.auto_rigar_humanoide(obj, "godot-humanoid-aa@1", postprocess.criar_armadura)
geradas = autorig.aplicar_animacoes_multi(rig_obj, cfg["clipes"])

_, dist_hier, _ = apc.construir_hierarquia_ossos([{"nome": b.name, "pai": b.parent.name if b.parent else None} for b in rig_obj.data.bones])
def _d(a, b):
    if (a, b) in dist_hier: return int(dist_hier[(a, b)])
    if (b, a) in dist_hier: return int(dist_hier[(b, a)])
    sub = dist_hier.get(a)
    return int(sub[b]) if isinstance(sub, dict) and b in sub else 999

zs = [v.co.z for v in obj.data.vertices]
h, neck_z, shoulder_z = max(zs) - min(zs), float(rig_obj.data.bones["Head"].head_local.z), float(rig_obj.data.bones["UpperArm.L"].head_local.z)
vgs = {vg.index: vg.name for vg in obj.vertex_groups}
arm_bones = {"UpperArm.L", "LowerArm.L", "Hand.L", "UpperArm.R", "LowerArm.R", "Hand.R"}
gt3 = pauldron_n = pauldron_head = belt_n = belt_arm = incoh = 0
for vi, v in enumerate(obj.data.vertices):
    names = [vgs[g.group] for g in v.groups if g.weight > 1e-6]
    gt3 += int(len(names) > 3)
    incoh += int(any(_d(names[i], names[j]) >= 3 for i in range(len(names)) for j in range(i + 1, len(names))))
    if abs(v.co.x) > 0.25 * h and v.co.z >= neck_z:
        pauldron_n += 1; pauldron_head += int("Head" in names)
    if vi >= n_body:
        belt_n += 1; belt_arm += int(any(n in arm_bones for n in names))
belt_max_z = max(obj.data.vertices[vi].co.z for vi in range(n_body, len(obj.data.vertices)))
open(cfg["out_json"], "w", encoding="utf-8").write(json.dumps({
    "geradas": geradas, "gt3": gt3, "pauldron_n": pauldron_n, "pauldron_head": pauldron_head,
    "belt_n": belt_n, "belt_arm": belt_arm, "incoh": incoh, "belt_max_z": belt_max_z, "shoulder_z": shoulder_z, "h": h,
}))
""",
        encoding="utf-8",
    )
    proc = subprocess.run([blender, "--background", "--factory-startup", "--python-exit-code", "1", "--python", str(script), "--", str(cfg_path)], capture_output=True, text=True, timeout=180)
    assert proc.returncode == 0, f"Blender falhou:\nSTDOUT={proc.stdout}\nSTDERR={proc.stderr}"
    res = json.loads(out_json.read_text(encoding="utf-8"))
    nomes_geradas = {g["nome"] if isinstance(g, dict) else g for g in res["geradas"]}
    assert nomes_geradas >= {"walk", "attack"} and res["pauldron_n"] > 0 and res["belt_n"] > 0
    assert res["belt_max_z"] < res["shoulder_z"] - 0.14 * res["h"]
    assert res["gt3"] == 0 and res["pauldron_head"] == 0 and res["belt_arm"] == 0 and res["incoh"] == 0, res


# ------------------------------------------------------------------ Contrato 4: Gate G16 (qc_deformacao & qc.verificar)
def test_c4_g16_constantes_e_nao_aplicavel(tmp_path: Path) -> None:
    from forge3d import qc_deformacao

    assert qc_deformacao.LIMIAR_G16_MAX_STRETCH == pytest.approx(8.5)
    assert qc_deformacao.LIMIAR_G16_FRAC_GT_2X == pytest.approx(0.01)
    assert qc_deformacao.LIMIAR_G16_FRAC_GT_3X == pytest.approx(0.0025)
    assert qc_deformacao.LIMIAR_G16_RIGIDO_MAX == pytest.approx(1.05)
    assert "G16" in qc.GATES

    perfil = profiles.carregar("godot4-aa")
    g_p, b_p = qc.ler_glb_bin(_multi_node_glb({"Box": ((0.0, 0.5, 0.0), (0.3, 0.5, 0.3))}))
    res_p = qc_deformacao.verificar_g16_deformacao(g_p, b_p, {"id": "p.01", "tipo": "prop_estatico"}, perfil, tmp_path, {}, {})
    assert res_p["id"] == "G16" and res_p["status"] == "ok" and res_p["medido"]["aplicavel"] is False

    g_na, b_na = qc.ler_glb_bin(_skinned_animated_glb(tear_def06=False, include_anim=False))
    res_na = qc_deformacao.verificar_g16_deformacao(g_na, b_na, {"id": "h.01", "auto_rig": True}, perfil, tmp_path, {}, {})
    assert res_na["id"] == "G16" and res_na["status"] == "ok" and res_na["medido"]["aplicavel"] is False


def test_c4_g16_skinned_rasgo_def06_vs_limpo_e_qc_verificar(tmp_path: Path) -> None:
    from forge3d import qc_deformacao

    perfil = profiles.carregar("godot4-aa")
    item_rig = {"id": "hero.skin.01", "tipo": "personagem_humanoide", "auto_rig": True, "esqueleto": "godot-humanoid-aa@1", "animacoes_base": ["walk"]}

    raw_tear = _skinned_animated_glb(tear_def06=True, rot_deg=90.0, include_anim=True)
    g_tear, b_tear = qc.ler_glb_bin(raw_tear)
    res_lbs = qc_deformacao.verificar_g16_deformacao(g_tear, b_tear, item_rig, perfil, tmp_path, {}, {})
    assert res_lbs["id"] == "G16" and res_lbs["status"] == "falhou" and res_lbs["codigo"] == "FORGE-E-QC"
    assert res_lbs["medido"]["aplicavel"] is True and float(res_lbs["medido"]["max_stretch"]) > qc_deformacao.LIMIAR_G16_MAX_STRETCH

    raw_ok = _skinned_animated_glb(tear_def06=False, rot_deg=35.0, include_anim=True)
    g_ok, b_ok = qc.ler_glb_bin(raw_ok)
    res_ok = qc_deformacao.verificar_g16_deformacao(g_ok, b_ok, item_rig, perfil, tmp_path, {}, {})
    assert res_ok["id"] == "G16" and res_ok["status"] == "ok" and res_ok["medido"]["aplicavel"] is True
    assert float(res_ok["medido"]["max_stretch"]) <= 1.2

    res_med = qc_deformacao.verificar_g16_deformacao(
        g_ok, b_ok, item_rig, perfil, tmp_path, {},
        {"deformacao_anim": {"max_stretch": 12.4, "frac_gt_2x": 0.03, "frac_gt_3x": 0.01}},
    )
    assert res_med["id"] == "G16" and res_med["status"] == "falhou" and res_med["codigo"] == "FORGE-E-QC"

    tear_path = tmp_path / "tear.glb"
    tear_path.write_bytes(raw_tear)
    rel = qc.verificar(
        {**item_rig, "altura_metros": 1.0, "pivot": "base", "limite_triangulos": 5000, "colisao": "none"},
        perfil, tmp_path, {"arquivos": [{"caminho": tear_path.name, "papel": "mesh", "nivel": 0, "triangulos": 24}], "medidas": {}},
    )
    g16 = next((g for g in rel["gates"] if g["id"] == "G16"), None)
    assert g16 is not None and g16["status"] == "falhou" and g16["codigo"] == "FORGE-E-QC" and rel["aprovado"] is False


def test_c4_g16_motor6d_rigido_valido_e_falhas(tmp_path: Path) -> None:
    from forge3d import qc_deformacao

    perfil = profiles.carregar("roblox-aa-80")
    g_main, b_main = qc.ler_glb_bin(_multi_node_glb({"Main": ((0.0, 0.5, 0.0), (0.3, 0.5, 0.3))}))
    partes = [{"nome": "LowerTorso", "arquivo": "LowerTorso.glb"}, {"nome": "UpperTorso", "arquivo": "UpperTorso.glb"}, {"nome": "Head", "arquivo": "Head.glb"}]
    comb_name = "hero_partes_combinadas.glb"
    item_m6d = {"id": "hero.m6d.01", "auto_rig": True, "esqueleto": "r15@1",
                "rig": {"modo": "motor6d", "esqueleto": "r15@1", "partes_combinadas": comb_name}, "partes": partes}
    resultado = {"arquivos": [{"caminho": "hero.glb", "papel": "mesh"}, {"caminho": comb_name, "papel": "partes_combinadas"}],
                 "partes": partes, "partes_combinadas": comb_name}
    comb_path = tmp_path / comb_name

    # 1) Valido watertight com todos os nos -> ok
    comb_path.write_bytes(_multi_node_glb({"LowerTorso": ((0, .3, 0), (.2, .3, .2)), "UpperTorso": ((0, .9, 0), (.2, .3, .2)), "Head": ((0, 1.4, 0), (.15, .15, .15))}))
    res_ok = qc_deformacao.verificar_g16_deformacao(g_main, b_main, item_m6d, perfil, tmp_path, resultado, {})
    assert res_ok["id"] == "G16" and res_ok["status"] == "ok" and res_ok["medido"]["modo"] == "motor6d_rigido"
    assert float(res_ok["medido"]["max_stretch"]) == pytest.approx(1.0)

    # 2) No de parte ausente -> falhou
    comb_path.write_bytes(_multi_node_glb({"LowerTorso": ((0, .3, 0), (.2, .3, .2)), "UpperTorso": ((0, .9, 0), (.2, .3, .2))}))
    res_node = qc_deformacao.verificar_g16_deformacao(g_main, b_main, item_m6d, perfil, tmp_path, resultado, {})
    assert res_node["status"] == "falhou" and res_node["codigo"] == "FORGE-E-QC"

    # 3) Geometria nao-manifold -> falhou
    comb_path.write_bytes(_multi_node_glb({"LowerTorso": ((0, .3, 0), (.2, .3, .2)), "UpperTorso": ((0, .9, 0), (.2, .3, .2)), "Head": ((0, 1.4, 0), (.15, .15, .15))}, non_manifold_node="Head"))
    res_nm = qc_deformacao.verificar_g16_deformacao(g_main, b_main, item_m6d, perfil, tmp_path, resultado, {})
    assert res_nm["status"] == "falhou" and res_nm["codigo"] == "FORGE-E-QC"

    # 4) Arquivo partes_combinadas.glb ausente -> falhou
    comb_path.unlink()
    res_miss = qc_deformacao.verificar_g16_deformacao(g_main, b_main, item_m6d, perfil, tmp_path, resultado, {})
    assert res_miss["status"] == "falhou" and res_miss["codigo"] == "FORGE-E-QC"
