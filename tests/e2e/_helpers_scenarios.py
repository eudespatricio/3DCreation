"""Shared synthetic builders & offline boundary shims for E2E Tiers 3 & 4 (zero `import forge3d`)."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import math
import shutil
import stat
import struct
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from tests.e2e.conftest import build_minimal_png_bytes, find_godot

R15_15_PARTS: tuple[str, ...] = (
    "LowerTorso", "UpperTorso", "Head",
    "LeftUpperArm", "LeftLowerArm", "LeftHand", "RightUpperArm", "RightLowerArm", "RightHand",
    "LeftUpperLeg", "LeftLowerLeg", "LeftFoot", "RightUpperLeg", "RightLowerLeg", "RightFoot",
)

GODOT_AA_56_BONES: tuple[str, ...] = (
    "Root", "Hips", "Spine", "Chest", "Neck", "Head", "Jaw", "Eye.L", "Eye.R", "Cape",
    "Shoulder.L", "UpperArm.L", "LowerArm.L", "Hand.L", "Shoulder.R", "UpperArm.R", "LowerArm.R", "Hand.R",
    "UpperLeg.L", "LowerLeg.L", "Foot.L", "Toe.L", "UpperLeg.R", "LowerLeg.R", "Foot.R", "Toe.R",
    "Thumb1.L", "Thumb2.L", "Thumb3.L", "Index1.L", "Index2.L", "Index3.L",
    "Middle1.L", "Middle2.L", "Middle3.L", "Ring1.L", "Ring2.L", "Ring3.L",
    "Little1.L", "Little2.L", "Little3.L", "Thumb1.R", "Thumb2.R", "Thumb3.R",
    "Index1.R", "Index2.R", "Index3.R", "Middle1.R", "Middle2.R", "Middle3.R",
    "Ring1.R", "Ring2.R", "Ring3.R", "Little1.R", "Little2.R", "Little3.R",
)


def sha256_prefixed(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def read_glb_chunks(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()
    magic, version, _ = struct.unpack_from("<III", raw, 0)
    assert magic == 0x46546C67 and version == 2, f"invalid GLB header in {path}"
    j_len, j_type = struct.unpack_from("<II", raw, 12)
    assert j_type == 0x4E4F534A
    gltf = json.loads(raw[20 : 20 + j_len].decode("utf-8"))
    b_off = 20 + j_len
    if b_off + 8 <= len(raw):
        b_len, b_type = struct.unpack_from("<II", raw, b_off)
        assert b_type == 0x004E4942
        bin_chunk = raw[b_off + 8 : b_off + 8 + b_len]
    else:
        bin_chunk = b""
    return gltf, bin_chunk


def pack_glb(gltf: dict[str, Any], bin_data: bytes) -> bytes:
    jb = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    jb += b" " * ((-len(jb)) % 4)
    bb = bin_data + b"\x00" * ((-len(bin_data)) % 4)
    total = 12 + 8 + len(jb) + 8 + len(bb)
    return (
        struct.pack("<III", 0x46546C67, 2, total)
        + struct.pack("<II", len(jb), 0x4E4F534A)
        + jb
        + struct.pack("<II", len(bb), 0x004E4942)
        + bb
    )


def _cube_face_geometry(
    cx: float, cy: float, cz: float, hx: float, hy: float, hz: float,
    uv_bounds: tuple[float, float, float, float] = (0.0, 0.0, 1.0, 1.0),
    segs: int = 1,
) -> tuple[list[tuple[float, float, float]], list[tuple[float, float, float]], list[tuple[float, float]], list[tuple[int, int, int]]]:
    y0, y1 = cy - hy, cy + hy
    faces = [
        ((0.0, 0.0, 1.0), [(cx - hx, y0, cz + hz), (cx + hx, y0, cz + hz), (cx + hx, y1, cz + hz), (cx - hx, y1, cz + hz)]),
        ((0.0, 0.0, -1.0), [(cx + hx, y0, cz - hz), (cx - hx, y0, cz - hz), (cx - hx, y1, cz - hz), (cx + hx, y1, cz - hz)]),
        ((1.0, 0.0, 0.0), [(cx + hx, y0, cz + hz), (cx + hx, y0, cz - hz), (cx + hx, y1, cz - hz), (cx + hx, y1, cz + hz)]),
        ((-1.0, 0.0, 0.0), [(cx - hx, y0, cz - hz), (cx - hx, y0, cz + hz), (cx - hx, y1, cz + hz), (cx - hx, y1, cz - hz)]),
        ((0.0, 1.0, 0.0), [(cx - hx, y1, cz + hz), (cx + hx, y1, cz + hz), (cx + hx, y1, cz - hz), (cx - hx, y1, cz - hz)]),
        ((0.0, -1.0, 0.0), [(cx - hx, y0, cz - hz), (cx + hx, y0, cz - hz), (cx + hx, y0, cz + hz), (cx - hx, y0, cz + hz)]),
    ]
    n = max(1, int(segs))
    ub0, vb0, ub1, vb1 = uv_bounds
    du, dv = (ub1 - ub0) / 3.0, (vb1 - vb0) / 2.0
    verts, norms, uvs, tris = [], [], [], []
    for f_idx, (nrm, (c0, c1, c2, c3)) in enumerate(faces):
        base, col, row = len(verts), f_idx % 3, f_idx // 3
        u0, u1 = ub0 + col * du + 0.04 * du, ub0 + (col + 1) * du - 0.04 * du
        v0, v1 = vb0 + row * dv + 0.04 * dv, vb0 + (row + 1) * dv - 0.04 * dv
        for j in range(n + 1):
            tv = j / float(n)
            for i in range(n + 1):
                tu = i / float(n)
                pt = tuple(
                    (1.0 - tv) * ((1.0 - tu) * c0[k] + tu * c1[k]) + tv * ((1.0 - tu) * c3[k] + tu * c2[k])
                    for k in range(3)
                )
                verts.append((pt[0], pt[1], pt[2]))
                norms.append(nrm)
                uvs.append((u0 + tu * (u1 - u0), v0 + tv * (v1 - v0)))
        for j in range(n):
            for i in range(n):
                p00 = base + j * (n + 1) + i
                p10, p11, p01 = p00 + 1, p00 + (n + 1) + 1, p00 + (n + 1)
                tris.extend([(p00, p10, p11), (p00, p11, p01)])
    return verts, norms, uvs, tris


def _quat_y(deg: float) -> tuple[float, float, float, float]:
    rad = math.radians(deg) * 0.5
    return (0.0, math.sin(rad), 0.0, math.cos(rad))


def _pack_static_glb(
    path: Path,
    verts: list[tuple[float, float, float]],
    norms: list[tuple[float, float, float]],
    uvs: list[tuple[float, float]],
    tris: list[tuple[int, int, int]],
    node_name: str,
) -> Path:
    buf = bytearray()

    def add_bv(raw: bytes) -> int:
        buf.extend(b"\x00" * ((-len(buf)) % 4))
        o = len(buf)
        buf.extend(raw)
        return o

    po = add_bv(b"".join(struct.pack("<3f", *v) for v in verts))
    no = add_bv(b"".join(struct.pack("<3f", *n) for n in norms))
    uo = add_bv(b"".join(struct.pack("<2f", *uv) for uv in uvs))
    io = add_bv(b"".join(struct.pack("<3H", *t) for t in tris))
    imgo = add_bv(build_minimal_png_bytes(256, 256, (150, 140, 130, 255)))
    xs, ys, zs = [v[0] for v in verts], [v[1] for v in verts], [v[2] for v in verts]
    gltf = {
        "asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"name": node_name, "mesh": 0}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1, "TEXCOORD_0": 2}, "indices": 3, "material": 0}]}],
        "materials": [{"name": "m0", "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}}],
        "images": [{"bufferView": 4, "mimeType": "image/png"}], "textures": [{"source": 0}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": po, "byteLength": len(verts) * 12},
            {"buffer": 0, "byteOffset": no, "byteLength": len(verts) * 12},
            {"buffer": 0, "byteOffset": uo, "byteLength": len(verts) * 8},
            {"buffer": 0, "byteOffset": io, "byteLength": len(tris) * 6},
            {"buffer": 0, "byteOffset": imgo, "byteLength": len(buf) - imgo},
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": len(verts), "type": "VEC3", "min": [min(xs), min(ys), min(zs)], "max": [max(xs), max(ys), max(zs)]},
            {"bufferView": 1, "componentType": 5126, "count": len(verts), "type": "VEC3"},
            {"bufferView": 2, "componentType": 5126, "count": len(verts), "type": "VEC2"},
            {"bufferView": 3, "componentType": 5123, "count": len(tris) * 3, "type": "SCALAR"},
        ],
        "buffers": [{"byteLength": len(buf)}],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(pack_glb(gltf, bytes(buf)))
    return path


def build_prism_glb(path: Path, *, sides: int = 24, radius: float = 0.4, height: float = 1.0) -> Path:
    """Create a closed watertight N-sided prism GLB (4*N tris) with per-face normals & disjoint UVs."""
    verts: list[tuple[float, float, float]] = [(0.0, 0.0, 0.0), (0.0, height, 0.0)]
    norms: list[tuple[float, float, float]] = [(0.0, -1.0, 0.0), (0.0, 1.0, 0.0)]
    uvs: list[tuple[float, float]] = [(0.25, 0.25), (0.75, 0.25)]
    tris: list[tuple[int, int, int]] = []
    # Bottom cap ring [2 .. 2+sides-1] and top cap ring [2+sides .. 2+2*sides-1]
    for i in range(sides):
        ang = (2.0 * math.pi * i) / sides
        ca, sa = math.cos(ang), math.sin(ang)
        verts.append((radius * ca, 0.0, radius * sa))
        norms.append((0.0, -1.0, 0.0))
        uvs.append((0.25 + 0.18 * ca, 0.25 + 0.18 * sa))
    for i in range(sides):
        ang = (2.0 * math.pi * i) / sides
        ca, sa = math.cos(ang), math.sin(ang)
        verts.append((radius * ca, height, radius * sa))
        norms.append((0.0, 1.0, 0.0))
        uvs.append((0.75 + 0.18 * ca, 0.25 + 0.18 * sa))
    for i in range(sides):
        nxt = (i + 1) % sides
        tris.append((0, 2 + i, 2 + nxt))
        tris.append((1, 2 + sides + nxt, 2 + sides + i))
        a0, a1, amid = (2.0 * math.pi * i) / sides, (2.0 * math.pi * ((i + 1) % sides)) / sides, (2.0 * math.pi * (i + 0.5)) / sides
        x0, z0, x1, z1 = radius * math.cos(a0), radius * math.sin(a0), radius * math.cos(a1), radius * math.sin(a1)
        fn = (math.cos(amid), 0.0, math.sin(amid))
        u0, u1 = 0.04 + (i / sides) * 0.92, 0.04 + ((i + 1) / sides) * 0.92
        sb = len(verts)
        verts.extend([(x0, 0.0, z0), (x0, height, z0), (x1, height, z1), (x1, 0.0, z1)])
        norms.extend([fn, fn, fn, fn])
        uvs.extend([(u0, 0.54), (u0, 0.96), (u1, 0.96), (u1, 0.54)])
        tris.extend([(sb, sb + 1, sb + 2), (sb, sb + 2, sb + 3)])
    return _pack_static_glb(path, verts, norms, uvs, tris, "Prism")


def build_skinned_humanoid_glb(
    path: Path, *, bones: Sequence[str] = GODOT_AA_56_BONES, height: float = 1.8,
    clipes: Sequence[str] = ("idle", "walk", "slash_combo"), with_texture: bool = True,
    include_foot: bool = True, node_name: str = "Hero",
) -> Path:
    """Create a closed, forward-facing (-Z) skinned GLB with disjoint UVs, 256px PNG, and >=5deg loops."""
    verts, norms, uvs, tris = _cube_face_geometry(0.0, height * 0.5, 0.0, 0.25, height * 0.5, 0.22, uv_bounds=(0.0, 0.0, 0.74, 1.0))
    if include_foot:
        v_f, n_f, uv_f, t_f = _cube_face_geometry(0.0, 0.06, -0.14, 0.12, 0.06, 0.08, uv_bounds=(0.76, 0.0, 1.0, 1.0))
        off = len(verts)
        verts.extend(v_f)
        norms.extend(n_f)
        uvs.extend(uv_f)
        tris.extend([(a + off, b + off, c + off) for a, b, c in t_f])
    buf, bvs, accs = bytearray(), [], []

    def add_bv(raw: bytes, target: int | None = None) -> int:
        buf.extend(b"\x00" * ((-len(buf)) % 4))
        o = len(buf)
        buf.extend(raw)
        bv: dict[str, Any] = {"buffer": 0, "byteOffset": o, "byteLength": len(raw)}
        if target is not None:
            bv["target"] = target
        bvs.append(bv)
        return len(bvs) - 1

    def add_acc(bv: int, ctype: int, count: int, atype: str, **extra: Any) -> int:
        accs.append({"bufferView": bv, "componentType": ctype, "count": count, "type": atype, **extra})
        return len(accs) - 1

    xs, ys, zs = [v[0] for v in verts], [v[1] for v in verts], [v[2] for v in verts]
    a_pos = add_acc(add_bv(b"".join(struct.pack("<3f", *v) for v in verts), 34962), 5126, len(verts), "VEC3", min=[min(xs), min(ys), min(zs)], max=[max(xs), max(ys), max(zs)])
    a_nrm = add_acc(add_bv(b"".join(struct.pack("<3f", *n) for n in norms), 34962), 5126, len(verts), "VEC3")
    a_tan = add_acc(add_bv(b"".join(struct.pack("<4f", 1.0, 0.0, 0.0, 1.0) for _ in verts), 34962), 5126, len(verts), "VEC4")
    a_uv = add_acc(add_bv(b"".join(struct.pack("<2f", *uv) for uv in uvs), 34962), 5126, len(verts), "VEC2")
    jv = [(1 + (i % min(10, max(1, len(bones) - 1))), 0, 0, 0) for i in range(len(verts))]
    a_j = add_acc(add_bv(b"".join(struct.pack("<4B", *j) for j in jv), 34962), 5121, len(verts), "VEC4")
    a_w = add_acc(add_bv(b"".join(struct.pack("<4f", 1.0, 0.0, 0.0, 0.0) for _ in verts), 34962), 5126, len(verts), "VEC4")
    a_idx = add_acc(add_bv(b"".join(struct.pack("<3H", *t) for t in tris), 34963), 5123, len(tris) * 3, "SCALAR")
    nodes: list[dict[str, Any]] = [{"name": node_name, "mesh": 0, "skin": 0}]
    joint_map, j_indices = {}, []
    bone_flip = {"Shoulder.L", "Shoulder.R", "UpperArm.L", "LowerArm.L", "UpperArm.R", "LowerArm.R", "UpperLeg.L", "LowerLeg.L", "UpperLeg.R", "LowerLeg.R", "Foot.L", "Foot.R"}
    for idx_b, bname in enumerate(bones):
        ni = len(nodes)
        joint_map[bname] = ni
        j_indices.append(ni)
        node_d: dict[str, Any] = {"name": bname, "translation": [0.0, round((idx_b / max(1, len(bones))) * height * 0.9, 4) if idx_b == 0 else 0.02, 0.0]}
        if bname in bone_flip:
            node_d["rotation"] = [0.0, 1.0, 0.0, 0.0]
        nodes.append(node_d)
    nodes[j_indices[0]]["children"] = j_indices[1:]
    gltf_anims = []
    for clipe in clipes:
        t_acc = add_acc(add_bv(struct.pack("<3f", 0.0, 0.5, 1.0)), 5126, 3, "SCALAR", min=[0.0], max=[1.0])
        q_acc = add_acc(add_bv(b"".join(struct.pack("<4f", *q) for q in (_quat_y(0.0), _quat_y(18.0), _quat_y(0.0)))), 5126, 3, "VEC4")
        gltf_anims.append({
            "name": clipe, "samplers": [{"input": t_acc, "interpolation": "LINEAR", "output": q_acc}],
            "channels": [{"sampler": 0, "target": {"node": joint_map.get("Hips", j_indices[0]), "path": "rotation"}}, {"sampler": 0, "target": {"node": joint_map.get("Spine", j_indices[min(1, len(j_indices) - 1)]), "path": "rotation"}}],
        })
    pbr: dict[str, Any] = {"baseColorFactor": [0.9, 0.9, 0.9, 1.0], "metallicFactor": 0.0, "roughnessFactor": 0.75}
    gltf: dict[str, Any] = {
        "asset": {"version": "2.0", "generator": "forge3d-e2e-scenarios"}, "scene": 0, "scenes": [{"nodes": [0, j_indices[0]]}],
        "nodes": nodes, "skins": [{"joints": j_indices}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": a_pos, "NORMAL": a_nrm, "TANGENT": a_tan, "TEXCOORD_0": a_uv, "JOINTS_0": a_j, "WEIGHTS_0": a_w}, "indices": a_idx, "material": 0}]}],
        "materials": [{"name": "MatHero", "pbrMetallicRoughness": pbr}], "accessors": accs, "bufferViews": bvs, "buffers": [{"byteLength": 0}],
    }
    if with_texture:
        gltf["images"] = [{"bufferView": add_bv(build_minimal_png_bytes(256, 256, (160, 170, 190, 255))), "mimeType": "image/png"}]
        gltf["textures"] = [{"source": 0}]
        pbr["baseColorTexture"] = {"index": 0}
    if gltf_anims:
        gltf["animations"] = gltf_anims
    gltf["buffers"][0]["byteLength"] = len(buf)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(pack_glb(gltf, bytes(buf)))
    return path


def build_multisurface_ucx_glb(
    path: Path,
    *,
    node_name: str = "AssetMulti",
    scale: float = 1.0,
    ucx_count: int = 3,
    with_embedded_images: bool = True,
) -> Path:
    """Create a multisurface GLB (dielectric + metallic/emissive) with optional UCX_ child colliders."""
    verts, norms, uvs, tris = _cube_face_geometry(0.0, 0.5 * scale, 0.0, 0.5 * scale, 0.5 * scale, 0.5 * scale)
    buf, bvs, accs = bytearray(), [], []

    def add_bv(raw: bytes, target: int | None = None) -> int:
        buf.extend(b"\x00" * ((-len(buf)) % 4))
        o = len(buf)
        buf.extend(raw)
        bv: dict[str, Any] = {"buffer": 0, "byteOffset": o, "byteLength": len(raw)}
        if target is not None:
            bv["target"] = target
        bvs.append(bv)
        return len(bvs) - 1

    def add_acc(bv: int, ctype: int, count: int, atype: str, **extra: Any) -> int:
        accs.append({"bufferView": bv, "componentType": ctype, "count": count, "type": atype, **extra})
        return len(accs) - 1

    xs, ys, zs = [v[0] for v in verts], [v[1] for v in verts], [v[2] for v in verts]
    a_pos = add_acc(add_bv(b"".join(struct.pack("<3f", *v) for v in verts), 34962), 5126, len(verts), "VEC3", min=[min(xs), min(ys), min(zs)], max=[max(xs), max(ys), max(zs)])
    a_nrm = add_acc(add_bv(b"".join(struct.pack("<3f", *n) for n in norms), 34962), 5126, len(verts), "VEC3")
    a_tan = add_acc(add_bv(b"".join(struct.pack("<4f", 1.0, 0.0, 0.0, 1.0) for _ in verts), 34962), 5126, len(verts), "VEC4")
    a_uv = add_acc(add_bv(b"".join(struct.pack("<2f", *uv) for uv in uvs), 34962), 5126, len(verts), "VEC2")
    split = len(tris) // 2
    a_i0 = add_acc(add_bv(b"".join(struct.pack("<3H", *t) for t in tris[:split]), 34963), 5123, split * 3, "SCALAR")
    a_i1 = add_acc(add_bv(b"".join(struct.pack("<3H", *t) for t in tris[split:]), 34963), 5123, (len(tris) - split) * 3, "SCALAR")

    nodes: list[dict[str, Any]] = [{"name": node_name, "mesh": 0}]
    meshes: list[dict[str, Any]] = [{
        "name": node_name,
        "primitives": [
            {"attributes": {"POSITION": a_pos, "NORMAL": a_nrm, "TANGENT": a_tan, "TEXCOORD_0": a_uv}, "indices": a_i0, "material": 0},
            {"attributes": {"POSITION": a_pos, "NORMAL": a_nrm, "TANGENT": a_tan, "TEXCOORD_0": a_uv}, "indices": a_i1, "material": 1},
        ],
    }]
    scene_nodes = [0]
    for idx in range(1, ucx_count + 1):
        ucx_name = f"UCX_{node_name}_{idx:02d}"
        uv_c, un_c, _, ut_c = _cube_face_geometry((idx - 2) * 0.25 * scale, 0.5 * scale, 0.0, 0.08 * scale, 0.08 * scale, 0.08 * scale)
        uxs, uys, uzs = [v[0] for v in uv_c], [v[1] for v in uv_c], [v[2] for v in uv_c]
        up = add_acc(add_bv(b"".join(struct.pack("<3f", *v) for v in uv_c), 34962), 5126, len(uv_c), "VEC3", min=[min(uxs), min(uys), min(uzs)], max=[max(uxs), max(uys), max(uzs)])
        un = add_acc(add_bv(b"".join(struct.pack("<3f", *n) for n in un_c), 34962), 5126, len(un_c), "VEC3")
        ui = add_acc(add_bv(b"".join(struct.pack("<3H", *t) for t in ut_c), 34963), 5123, len(ut_c) * 3, "SCALAR")
        meshes.append({
            "name": ucx_name,
            "primitives": [{"attributes": {"POSITION": up, "NORMAL": un, "TEXCOORD_0": a_uv}, "indices": ui}],
        })
        nodes.append({"name": ucx_name, "mesh": len(meshes) - 1})
        scene_nodes.append(len(nodes) - 1)

    m0: dict[str, Any] = {"name": "MatBase", "pbrMetallicRoughness": {"baseColorFactor": [0.8, 0.8, 0.8, 1.0], "metallicFactor": 0.0, "roughnessFactor": 0.9}}
    m1: dict[str, Any] = {"name": "MatTrim", "pbrMetallicRoughness": {"baseColorFactor": [0.9, 0.7, 0.3, 1.0], "metallicFactor": 0.85, "roughnessFactor": 0.25}, "emissiveFactor": [0.3, 0.1, 0.0]}
    gltf: dict[str, Any] = {
        "asset": {"version": "2.0", "generator": "forge3d-e2e-multi"},
        "scene": 0,
        "scenes": [{"nodes": scene_nodes}],
        "nodes": nodes,
        "meshes": meshes,
        "materials": [m0, m1],
        "accessors": accs,
        "bufferViews": bvs,
        "buffers": [{"byteLength": 0}],
    }
    if with_embedded_images:
        bv_img0 = add_bv(build_minimal_png_bytes(64, 64, (140, 120, 100, 255)))
        bv_img1 = add_bv(build_minimal_png_bytes(64, 64, (220, 180, 60, 255)))
        gltf["images"] = [{"bufferView": bv_img0, "mimeType": "image/png"}, {"bufferView": bv_img1, "mimeType": "image/png"}]
        gltf["textures"] = [{"source": 0}, {"source": 1}]
        m0["pbrMetallicRoughness"]["baseColorTexture"] = {"index": 0}
        m1["pbrMetallicRoughness"]["baseColorTexture"] = {"index": 1}

    gltf["buffers"][0]["byteLength"] = len(buf)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(pack_glb(gltf, bytes(buf)))
    return path


def setup_offline_trellis2_shim(base_dir: Path, log_path: Path | None = None) -> dict[str, str]:
    """Create a zero-GPU, zero-network offline local TRELLIS.2 shim for `MeshProvider`."""
    t2_dir = base_dir / "trellis2"
    venv_bin, site_dir = t2_dir / "venv" / "bin", base_dir / "trellis2_site"
    venv_bin.mkdir(parents=True, exist_ok=True)
    site_dir.mkdir(parents=True, exist_ok=True)
    (t2_dir / "repo" / "trellis2_gguf").mkdir(parents=True, exist_ok=True)
    (t2_dir / "cuda128" / "lib").mkdir(parents=True, exist_ok=True)
    models = t2_dir / "models"
    for rel in (
        "Trellis2/pipeline.json",
        "Trellis2/decoders/Stage1/ss_dec_conv3d_16l8_fp16.safetensors",
        "Trellis2/decoders/Stage2/shape_dec_next_dc_f16c32_fp16.safetensors",
        "Trellis2/decoders/Stage2/tex_dec_next_dc_f16c32_fp16.safetensors",
        "Trellis2/refiner/ss_flow_img_dit_1_3B_64_bf16.safetensors",
        "Trellis2/shape/slat_flow_img2shape_dit_1_3B_512_bf16.safetensors",
        "Trellis2/texture/slat_flow_imgshape2tex_dit_1_3B_512_bf16.safetensors",
    ):
        p = models / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x", encoding="utf-8")
    (models / "facebook" / "dinov3-vitl16-pretrain-lvd1689m").mkdir(parents=True, exist_ok=True)

    (site_dir / "torch").mkdir(parents=True, exist_ok=True)
    (site_dir / "torch" / "__init__.py").write_text(
        "__version__ = '2.9.1+e2e'\nclass cuda:\n    @staticmethod\n    def is_available(): return True\n", encoding="utf-8"
    )
    for mod_name in ("o_voxel", "flex_gemm", "nvdiffrast", "cumesh"):
        (site_dir / f"{mod_name}.py").write_text("", encoding="utf-8")

    py_shim = venv_bin / "python"
    py_shim.write_text(
        "\n".join([
            "#!/bin/sh",
            f"PYTHONPATH={str(site_dir)!r}:\"${{PYTHONPATH:-}}\"",
            "export PYTHONPATH",
            f"exec {sys.executable!r} \"$@\"",
            "",
        ]),
        encoding="utf-8",
    )
    py_shim.chmod(py_shim.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    repo_root = str(Path(__file__).resolve().parents[2])
    infer_stub = base_dir / "trellis2_infer_stub.py"
    stub_lines = [
        "import argparse, json, shutil, sys",
        "from pathlib import Path",
        f"sys.path.insert(0, {repo_root!r})",
        "from tests.e2e._helpers_scenarios import write_dense_humanoid_glb",
        "p = argparse.ArgumentParser()",
        "for flag, dflt in (('--imagem', None), ('--saida-dir', None), ('--resultado', None), ('--modelo', 'microsoft/TRELLIS.2-4B'), ('--quant', 'BF16'), ('--pipeline-type', '512'), ('--steps', '25'), ('--decimation-target', '80000'), ('--texture-size', '2048')):",
        "    p.add_argument(flag, required=(dflt is None), default=dflt)",
        "args, _ = p.parse_known_args()",
        "out = Path(args.saida_dir)",
        "out.mkdir(parents=True, exist_ok=True)",
        "write_dense_humanoid_glb(out / 'modelo.glb', height=1.8)",
        "if Path(args.imagem).is_file() and Path(args.imagem).resolve() != (out / 'input.png').resolve():",
        "    shutil.copyfile(args.imagem, out / 'input.png')",
    ]
    if log_path is not None:
        stub_lines.append(
            f"Path({str(log_path)!r}).write_text(json.dumps({{'modelo': args.modelo, 'quant': args.quant, 'pipeline_type': args.pipeline_type, 'steps': args.steps, 'decimation_target': args.decimation_target, 'texture_size': args.texture_size}}), encoding='utf-8')"
        )
    stub_lines.append(
        "Path(args.resultado).write_text(json.dumps({'ok': True, 'provedor': 'trellis2_local', 'modelo': args.modelo, 'arquivo': 'modelo.glb', 'faces': 180}), encoding='utf-8')"
    )
    stub_lines.append("")
    infer_stub.write_text("\n".join(stub_lines), encoding="utf-8")
    return {
        "FORGE3D_MODELO_MESH": "trellis2",
        "FORGE3D_TRELLIS2_DIR": str(t2_dir),
        "FORGE3D_TRELLIS2_SCRIPT": str(infer_stub),
        "FORGE3D_I23D_DEVICE": "cuda:0",
        "FORGE3D_VRAM_MINIMA_MB": "0",
        "FORGE3D_POSE_GUARD": "off",
        "FORGE3D_DELIGHT": "0",
    }


def write_dense_humanoid_glb(path: Path, height: float = 1.8) -> Path:
    """Create a multi-part humanoid-proportioned closed GLB (covering all 15 R15 regions) with disjoint UVs."""
    s = height / 1.8
    boxes = [
        (0.0, 0.90 * s, 0.0, 0.14 * s, 0.12 * s, 0.09 * s), (0.0, 1.22 * s, 0.0, 0.16 * s, 0.20 * s, 0.10 * s),
        (0.0, 1.60 * s, 0.0, 0.11 * s, 0.16 * s, 0.11 * s),
        (-0.28 * s, 1.28 * s, 0.0, 0.07 * s, 0.11 * s, 0.07 * s), (-0.38 * s, 1.04 * s, 0.0, 0.06 * s, 0.11 * s, 0.06 * s), (-0.46 * s, 0.85 * s, 0.0, 0.05 * s, 0.06 * s, 0.05 * s),
        (0.28 * s, 1.28 * s, 0.0, 0.07 * s, 0.11 * s, 0.07 * s), (0.38 * s, 1.04 * s, 0.0, 0.06 * s, 0.11 * s, 0.06 * s), (0.46 * s, 0.85 * s, 0.0, 0.05 * s, 0.06 * s, 0.05 * s),
        (-0.10 * s, 0.60 * s, 0.0, 0.07 * s, 0.18 * s, 0.07 * s), (-0.10 * s, 0.28 * s, 0.0, 0.06 * s, 0.16 * s, 0.06 * s), (-0.10 * s, 0.06 * s, -0.02 * s, 0.06 * s, 0.06 * s, 0.10 * s),
        (0.10 * s, 0.60 * s, 0.0, 0.07 * s, 0.18 * s, 0.07 * s), (0.10 * s, 0.28 * s, 0.0, 0.06 * s, 0.16 * s, 0.06 * s), (0.10 * s, 0.06 * s, -0.02 * s, 0.06 * s, 0.06 * s, 0.10 * s),
    ]
    verts, norms, uvs, tris = [], [], [], []
    for idx, bx in enumerate(boxes):
        gx, gy = idx % 4, idx // 4
        v, n, uv, t = _cube_face_geometry(*bx, uv_bounds=(gx / 4.0, gy / 4.0, (gx + 1) / 4.0, (gy + 1) / 4.0), segs=2)
        o = len(verts)
        verts.extend(v)
        norms.extend(n)
        uvs.extend(uv)
        tris.extend([(a + o, b + o, c + o) for a, b, c in t])
    return _pack_static_glb(path, verts, norms, uvs, tris, "Humanoid")


def setup_offline_i23d_shim(base_dir: Path) -> dict[str, str]:
    """Create a zero-GPU, zero-network offline i23d boundary shim for `MeshProvider`."""
    venv_bin, vendor, modelos = base_dir / "venv_i23d" / "bin", base_dir / "vendor_triposr", base_dir / "modelos"
    (modelos / "TripoSR").mkdir(parents=True, exist_ok=True)
    venv_bin.mkdir(parents=True, exist_ok=True)
    (vendor / "torch").mkdir(parents=True, exist_ok=True)
    (vendor / "tsr").mkdir(parents=True, exist_ok=True)
    py_shim = venv_bin / "python"
    py_shim.write_text(f"#!/bin/sh\nexec {sys.executable!r} \"$@\"\n", encoding="utf-8")
    py_shim.chmod(py_shim.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    (vendor / "torch" / "__init__.py").write_text(
        "__version__ = '2.5.0+e2e'\nclass cuda:\n    @staticmethod\n    def is_available(): return False\n", encoding="utf-8"
    )
    (vendor / "tsr" / "__init__.py").write_text("__version__ = '0.1.0+e2e'\n", encoding="utf-8")
    repo_root = str(Path(__file__).resolve().parents[2])
    i23d_script = base_dir / "i23d_stub.py"
    i23d_script.write_text(
        f"import argparse, json, shutil, sys\nfrom pathlib import Path\nsys.path.insert(0, {repo_root!r})\n"
        "from tests.e2e._helpers_scenarios import write_dense_humanoid_glb\n"
        "p = argparse.ArgumentParser()\np.add_argument('--imagem', required=True)\np.add_argument('--saida-dir', required=True)\np.add_argument('--resultado', required=True)\n"
        "args, _ = p.parse_known_args()\nout = Path(args.saida_dir)\nout.mkdir(parents=True, exist_ok=True)\n"
        "write_dense_humanoid_glb(out / 'modelo.glb', height=1.8)\n"
        "if Path(args.imagem).is_file(): shutil.copyfile(args.imagem, out / 'input.png')\n"
        "Path(args.resultado).write_text(json.dumps({'ok': True, 'arquivo': 'modelo.glb', 'faces': 180}), encoding='utf-8')\n",
        encoding="utf-8",
    )
    return {
        "FORGE3D_VENV_I23D": str(base_dir / "venv_i23d"), "FORGE3D_TRIPOSR": str(vendor),
        "FORGE3D_MODELOS": str(modelos), "FORGE3D_I23D_SCRIPT": str(i23d_script),
        "FORGE3D_I23D_DEVICE": "cpu", "FORGE3D_POSE_GUARD": "off", "CUDA_VISIBLE_DEVICES": "",
    }


def build_humanoid_silhouette_png_bytes(size: int = 128, fg_rgba: tuple[int, int, int, int] = (200, 120, 70, 255)) -> bytes:
    """Create a high-contrast upright humanoid silhouette PNG on a clean transparent background."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw, cx = ImageDraw.Draw(img), size // 2
    s = size / 128.0
    for x0, y0, x1, y1 in (
        (cx - 8 * s, 12 * s, cx + 8 * s, 30 * s),    # Head
        (cx - 12 * s, 31 * s, cx + 12 * s, 56 * s),  # UpperTorso
        (cx - 10 * s, 57 * s, cx + 10 * s, 70 * s),  # LowerTorso
        (cx - 24 * s, 32 * s, cx - 14 * s, 74 * s),  # LeftArm
        (cx + 14 * s, 32 * s, cx + 24 * s, 74 * s),  # RightArm
        (cx - 10 * s, 71 * s, cx - 2 * s, 116 * s),  # LeftLeg
        (cx + 2 * s, 71 * s, cx + 10 * s, 116 * s),  # RightLeg
    ):
        draw.rectangle([int(x0), int(y0), int(x1), int(y1)], fill=fg_rgba)
    r, g, b, a = fg_rgba
    for ty in range(int(31 * s), int(70 * s)):
        for tx in range(int(cx - 10 * s), int(cx + 10 * s)):
            sh = (tx % 4) * 8
            img.putpixel((tx, ty), (min(255, r + sh), min(255, g + sh), min(255, b + sh), a))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def register_gemini_4view_mock(mock_http_server, *, color_rgba: tuple[int, int, int, int] = (200, 120, 70, 255)) -> list[dict[str, Any]]:
    """Register POST /v1beta/interactions returning humanoid silhouette PNG data and recording payloads."""
    captured: list[dict[str, Any]] = []
    b64_png = base64.b64encode(build_humanoid_silhouette_png_bytes(128, color_rgba)).decode("ascii")

    def _handler(raw_body: bytes, _headers: Any) -> dict[str, Any]:
        captured.append(json.loads(raw_body.decode("utf-8")))
        return {"steps": [{"type": "model_output", "content": [{"type": "image", "data": b64_png, "mime_type": "image/png"}]}]}

    mock_http_server.add_route("POST", "/v1beta/interactions", _handler, status=200)
    return captured


def provision_godot_project(proj_dir: Path, repo_root: Path) -> Path:
    """Provision an isolated ext4 Godot 4 project with `addons/forge3d` enabled."""
    proj_dir.mkdir(parents=True, exist_ok=True)
    dst_addon = proj_dir / "addons" / "forge3d"
    if dst_addon.exists():
        shutil.rmtree(dst_addon)
    shutil.copytree(repo_root / "addons" / "forge3d", dst_addon)
    (proj_dir / "project.godot").write_text(
        '; Engine configuration file.\nconfig_version=5\n\n[application]\nconfig/name="forge3d_e2e_proj"\nconfig/features=PackedStringArray("4.3")\n\n[editor_plugins]\nenabled=PackedStringArray("res://addons/forge3d/plugin.cfg")\n',
        encoding="utf-8",
    )
    return proj_dir


def run_godot_in_project(proj_dir: Path, args: Sequence[str], *, timeout: int = 90) -> subprocess.CompletedProcess[str]:
    """Execute `godot --headless --path <proj_dir>` without skipping on missing binary."""
    godot_bin = find_godot()
    assert godot_bin is not None, "Godot 4 binary required for Godot E2E verification"
    return subprocess.run(
        [godot_bin, "--headless", "--path", str(proj_dir), *[str(a) for a in args]],
        cwd=str(proj_dir), capture_output=True, text=True, timeout=timeout,
    )
