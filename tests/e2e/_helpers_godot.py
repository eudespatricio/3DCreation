"""Pure-stdlib & subprocess helpers for FA3 Godot 4 opaque-box E2E tests."""

from __future__ import annotations

import hashlib
import json
import shutil
import struct
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from tests.e2e.conftest import RAIZ, build_minimal_png_bytes, find_godot, run_godot_script

CLIPS_CYCLIC: tuple[str, ...] = ("idle", "walk", "run", "ride_idle", "ride_fly", "gallop", "wing_flap", "glide")
CLIPS_ONESHOT: tuple[str, ...] = ("jump", "attack", "slash_combo", "cast", "block", "hit", "death", "bite", "roar")
ALL_17_CLIPS: tuple[str, ...] = CLIPS_CYCLIC + CLIPS_ONESHOT

_ROLL_Y180 = [0.0, 1.0, 0.0, 0.0]
HUMANOID_V1_BONES: tuple[dict[str, Any], ...] = (
    {"name": "Root", "parent": -1, "translation": [0.0, 0.0, 0.0]},
    {"name": "Hips", "parent": 0, "translation": [0.0, 0.9, 0.0]},
    {"name": "Spine", "parent": 1, "translation": [0.0, 0.15, 0.0]},
    {"name": "Spine1", "parent": 2, "translation": [0.0, 0.15, 0.0]},
    {"name": "Chest", "parent": 3, "translation": [0.0, 0.15, 0.0]},
    {"name": "Neck", "parent": 4, "translation": [0.0, 0.15, 0.0]},
    {"name": "Head", "parent": 5, "translation": [0.0, 0.15, 0.0]},
    {"name": "Shoulder.L", "parent": 4, "translation": [0.1, 0.1, 0.0], "rotation": _ROLL_Y180},
    {"name": "UpperArm.L", "parent": 7, "translation": [-0.15, 0.0, 0.0]},
    {"name": "LowerArm.L", "parent": 8, "translation": [-0.2, 0.0, 0.0]},
    {"name": "Hand.L", "parent": 9, "translation": [-0.2, 0.0, 0.0]},
    {"name": "Shoulder.R", "parent": 4, "translation": [-0.1, 0.1, 0.0], "rotation": _ROLL_Y180},
    {"name": "UpperArm.R", "parent": 11, "translation": [0.15, 0.0, 0.0]},
    {"name": "LowerArm.R", "parent": 12, "translation": [0.2, 0.0, 0.0]},
    {"name": "Hand.R", "parent": 13, "translation": [0.2, 0.0, 0.0]},
    {"name": "UpperLeg.L", "parent": 1, "translation": [0.1, -0.1, 0.0], "rotation": _ROLL_Y180},
    {"name": "LowerLeg.L", "parent": 15, "translation": [0.0, -0.35, 0.0]},
    {"name": "Foot.L", "parent": 16, "translation": [0.0, -0.35, 0.0]},
    {"name": "Toe.L", "parent": 17, "translation": [0.0, -0.05, 0.1]},
    {"name": "UpperLeg.R", "parent": 1, "translation": [-0.1, -0.1, 0.0], "rotation": _ROLL_Y180},
    {"name": "LowerLeg.R", "parent": 19, "translation": [0.0, -0.35, 0.0]},
    {"name": "Foot.R", "parent": 20, "translation": [0.0, -0.35, 0.0]},
    {"name": "Toe.R", "parent": 21, "translation": [0.0, -0.05, 0.1]},
)


def gd_probe_header() -> str:
    return (
        'extends SceneTree\n'
        'const PostImport := preload("res://addons/forge3d/post_import.gd")\n'
        'func _load(p: String) -> Node:\n'
        '\tvar d := GLTFDocument.new(); var s := GLTFState.new()\n'
        '\tvar rp := ProjectSettings.globalize_path(p) if p.begins_with("res://") else p\n'
        '\tif d.append_from_file(rp, s) != OK: return null\n'
        '\treturn d.generate_scene(s)\n'
    )


def write_manifest(base_dir: Path, asset_id: str, data: Mapping[str, Any]) -> Path:
    base_dir.mkdir(parents=True, exist_ok=True)
    out = base_dir / f"{asset_id}.manifest.json"
    out.write_text(json.dumps(dict(data), indent=2, sort_keys=True), encoding="utf-8")
    return out


def stage_temp_godot_project(
    tmp_path: Path, *, name: str = "godot_proj", enable_plugin: bool = True, copy_profiles: bool = True
) -> Path:
    """Create an isolated temp Godot 4 project with `addons/forge3d` copied."""
    proj_dir = tmp_path / name
    proj_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(RAIZ / "addons", proj_dir / "addons", dirs_exist_ok=True)
    if copy_profiles:
        shutil.copytree(RAIZ / "profiles", proj_dir / "profiles", dirs_exist_ok=True)
    lines = ["config_version=5", "", "[application]", f'config/name="{name}"', 'config/features=PackedStringArray("4.3", "Forward Plus")']
    if enable_plugin:
        lines.extend(["", "[editor_plugins]", 'enabled=PackedStringArray("res://addons/forge3d/plugin.cfg")'])
    (proj_dir / "project.godot").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return proj_dir


def run_godot_in_project(proj_dir: Path, args: Sequence[str], *, timeout: int = 90) -> subprocess.CompletedProcess[str]:
    """Run `godot --headless --path <proj_dir>` with the given CLI arguments."""
    godot_bin = find_godot()
    if not godot_bin:
        pytest.skip("Godot 4 binary unavailable in environment")
    return subprocess.run([godot_bin, "--headless", "--path", str(proj_dir), *[str(a) for a in args]], cwd=str(proj_dir), capture_output=True, text=True, timeout=timeout)


def run_godot_probe(
    proj_dir: Path, script_name: str, script_text: str, script_args: Sequence[str] = (), *, timeout: int = 90
) -> subprocess.CompletedProcess[str]:
    """Write a temporary GDScript inside `proj_dir` and execute it headless."""
    script_path = proj_dir / script_name
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(script_text, encoding="utf-8")
    args = ["--script", f"res://{script_path.relative_to(proj_dir).as_posix()}"]
    if script_args:
        args.extend(["--", *[str(a) for a in script_args]])
    return run_godot_in_project(proj_dir, args, timeout=timeout)


def run_godot_tool(script_rel: str, script_args: Sequence[str] = (), *, timeout: int = 90) -> subprocess.CompletedProcess[str]:
    """Run a `tools/godot_*.gd` script against `tools/godot_project` (read-only)."""
    return run_godot_script(script_rel, script_args, timeout=timeout)


def read_glb_json(glb_path: Path) -> tuple[dict[str, Any], bytes]:
    """Parse GLB 2.0 header and return `(gltf_json_dict, bin_chunk_bytes)`."""
    raw = glb_path.read_bytes()
    magic, version, _ = struct.unpack_from("<III", raw, 0)
    assert magic == 0x46546C67 and version == 2, f"Invalid GLB header in {glb_path}"
    j_len, j_type = struct.unpack_from("<II", raw, 12)
    assert j_type == 0x4E4F534A
    gltf = json.loads(raw[20 : 20 + j_len].decode("utf-8"))
    bin_bytes, off = b"", 20 + j_len
    if off + 8 <= len(raw):
        b_len, b_type = struct.unpack_from("<II", raw, off)
        if b_type == 0x004E4942:
            bin_bytes = raw[off + 8 : off + 8 + b_len]
    return gltf, bin_bytes


def measure_uv_edge_isotropy(gltf: Mapping[str, Any], bin_bytes: bytes, uv_attr: str = "TEXCOORD_1") -> float:
    """Return `max(d_uv/d_3d) / min(d_uv/d_3d)` across mesh 0 primitive 0 edges (1.0 = isotropic)."""
    prim = gltf["meshes"][0]["primitives"][0]
    attrs, accs, bvs = prim["attributes"], gltf["accessors"], gltf["bufferViews"]

    def _unpack_floats(acc_idx: int, width: int) -> list[tuple[float, ...]]:
        acc = accs[acc_idx]
        bv = bvs[acc["bufferView"]]
        base = int(bv.get("byteOffset", 0)) + int(acc.get("byteOffset", 0))
        stride = int(bv.get("byteStride", width * 4))
        fmt = f"<{width}f"
        return [struct.unpack_from(fmt, bin_bytes, base + i * stride) for i in range(int(acc["count"]))]

    pos = _unpack_floats(int(attrs["POSITION"]), 3)
    uvs = _unpack_floats(int(attrs[uv_attr]), 2)
    if "indices" in prim:
        iacc = accs[int(prim["indices"])]
        ibv = bvs[iacc["bufferView"]]
        ibase = int(ibv.get("byteOffset", 0)) + int(iacc.get("byteOffset", 0))
        icomp = int(iacc["componentType"])
        ifmt, isize = ("<H", 2) if icomp == 5123 else ("<I", 4)
        idx = [struct.unpack_from(ifmt, bin_bytes, ibase + k * isize)[0] for k in range(int(iacc["count"]))]
    else:
        idx = list(range(len(pos)))

    ratios: list[float] = []
    for k in range(0, len(idx) - 2, 3):
        tri = (idx[k], idx[k + 1], idx[k + 2])
        for a, b in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
            d3 = ((pos[b][0] - pos[a][0]) ** 2 + (pos[b][1] - pos[a][1]) ** 2 + (pos[b][2] - pos[a][2]) ** 2) ** 0.5
            d2 = ((uvs[b][0] - uvs[a][0]) ** 2 + (uvs[b][1] - uvs[a][1]) ** 2) ** 0.5
            if d3 > 1e-6:
                ratios.append(d2 / d3)
    assert ratios, f"No non-degenerate edges found for {uv_attr}"
    return max(ratios) / min(ratios)


def _cube_arrays(sx: float, sy: float, sz: float, *, y_base: float = 0.0, subdiv: int = 1):
    hx, hz, y0, y1 = sx / 2.0, sz / 2.0, y_base, y_base + sy
    faces = [
        ((0.0, 0.0, 1.0), (-hx, y0, hz), (sx, 0.0, 0.0), (0.0, sy, 0.0)),
        ((0.0, 0.0, -1.0), (hx, y0, -hz), (-sx, 0.0, 0.0), (0.0, sy, 0.0)),
        ((1.0, 0.0, 0.0), (hx, y0, hz), (0.0, 0.0, -sz), (0.0, sy, 0.0)),
        ((-1.0, 0.0, 0.0), (-hx, y0, -hz), (0.0, 0.0, sz), (0.0, sy, 0.0)),
        ((0.0, 1.0, 0.0), (-hx, y1, hz), (sx, 0.0, 0.0), (0.0, 0.0, -sz)),
        ((0.0, -1.0, 0.0), (-hx, y0, -hz), (sx, 0.0, 0.0), (0.0, 0.0, sz)),
    ]
    verts, normals, uvs, tris, n = [], [], [], [], max(1, int(subdiv))
    for idx, (norm, o, du, dv) in enumerate(faces):
        col, row = idx % 3, idx // 3
        u0, u1, v0, v1, base = col / 3.0 + 0.02, (col + 1) / 3.0 - 0.02, row / 2.0 + 0.02, (row + 1) / 2.0 - 0.02, len(verts)
        for iy in range(n + 1):
            fy = iy / n
            for ix in range(n + 1):
                fx = ix / n
                verts.append((o[0] + du[0] * fx + dv[0] * fy, o[1] + du[1] * fx + dv[1] * fy, o[2] + du[2] * fx + dv[2] * fy))
                normals.append(norm)
                uvs.append((u0 + (u1 - u0) * fx, v0 + (v1 - v0) * fy))
        stride = n + 1
        for iy in range(n):
            for ix in range(n):
                p0 = base + iy * stride + ix
                tris.extend([(p0, p0 + 1, p0 + stride + 1), (p0, p0 + stride + 1, p0 + stride)])
    return verts, normals, uvs, tris


def _quat_to_mat4(q: Sequence[float], t: Sequence[float]) -> list[list[float]]:
    x, y, z, w = q
    xx, yy, zz, xy, xz, yz, wx, wy, wz = x * x, y * y, z * z, x * y, x * z, y * z, w * x, w * y, w * z
    return [
        [1.0 - 2.0 * (yy + zz), 2.0 * (xy - wz), 2.0 * (xz + wy), t[0]],
        [2.0 * (xy + wz), 1.0 - 2.0 * (xx + zz), 2.0 * (yz - wx), t[1]],
        [2.0 * (xz - wy), 2.0 * (yz + wx), 1.0 - 2.0 * (xx + yy), t[2]],
        [0.0, 0.0, 0.0, 1.0],
    ]


def _mat4_mul(a: list[list[float]], b: list[list[float]]) -> list[list[float]]:
    return [[sum(a[r][k] * b[k][c] for k in range(4)) for c in range(4)] for r in range(4)]


def _rigid_inv_col_major(m: list[list[float]]) -> list[float]:
    rt = [[m[c][r] for c in range(3)] for r in range(3)]
    t = [m[0][3], m[1][3], m[2][3]]
    it = [-(rt[r][0] * t[0] + rt[r][1] * t[1] + rt[r][2] * t[2]) for r in range(3)]
    inv = [[rt[0][0], rt[0][1], rt[0][2], it[0]], [rt[1][0], rt[1][1], rt[1][2], it[1]], [rt[2][0], rt[2][1], rt[2][2], it[2]], [0.0, 0.0, 0.0, 1.0]]
    return [inv[r][c] for c in range(4) for r in range(4)]


def write_custom_glb(
    path: Path,
    *,
    size_xyz: tuple[float, float, float] = (1.0, 1.0, 1.0),
    surfaces: Sequence[Mapping[str, Any]] | None = None,
    ucx_names: Sequence[str] = (),
    bones: Sequence[Mapping[str, Any]] | None = None,
    anim_clips: Mapping[str, Mapping[str, Any]] | None = None,
    node_name: str = "Asset",
    y_base: float = 0.0,
    subdiv: int = 1,
) -> Path:
    """Build a multi-surface, UCX-enabled, or rigged+animated GLB 2.0 file using stdlib only."""
    verts, normals, uvs, tris = _cube_arrays(*size_xyz, y_base=y_base, subdiv=subdiv)
    buf, bvs, accs = bytearray(), [], []

    def _pad4() -> None:
        while len(buf) % 4:
            buf.append(0)

    def _add_bv(raw: bytes) -> int:
        _pad4()
        off = len(buf)
        buf.extend(raw)
        bvs.append({"buffer": 0, "byteOffset": off, "byteLength": len(raw)})
        return len(bvs) - 1

    def _pack_vec3(items: Sequence[tuple[float, float, float]], bounds: bool = False) -> int:
        bv = _add_bv(b"".join(struct.pack("<fff", *v) for v in items))
        acc: dict[str, Any] = {"bufferView": bv, "componentType": 5126, "count": len(items), "type": "VEC3"}
        if bounds:
            acc["min"] = [min(p[i] for p in items) for i in range(3)]
            acc["max"] = [max(p[i] for p in items) for i in range(3)]
        accs.append(acc)
        return len(accs) - 1

    attrs: dict[str, int] = {"POSITION": _pack_vec3(verts, bounds=True), "NORMAL": _pack_vec3(normals)}
    uv_bv = _add_bv(b"".join(struct.pack("<ff", *uv) for uv in uvs))
    accs.append({"bufferView": uv_bv, "componentType": 5126, "count": len(uvs), "type": "VEC2"})
    attrs["TEXCOORD_0"] = len(accs) - 1

    if bones:
        if len(bones) > 1:
            j_bv = _add_bv(
                b"".join(struct.pack("<HHHH", 1 + (i % (len(bones) - 1)), 0, 0, 0) for i in range(len(verts)))
            )
        else:
            j_bv = _add_bv(b"".join(struct.pack("<HHHH", 0, 0, 0, 0) for _ in verts))
        accs.append({"bufferView": j_bv, "componentType": 5123, "count": len(verts), "type": "VEC4"})
        attrs["JOINTS_0"] = len(accs) - 1
        w_bv = _add_bv(b"".join(struct.pack("<ffff", 1.0, 0.0, 0.0, 0.0) for _ in verts))
        accs.append({"bufferView": w_bv, "componentType": 5126, "count": len(verts), "type": "VEC4"})
        attrs["WEIGHTS_0"] = len(accs) - 1

    surf_specs = list(surfaces) if surfaces else [{"name": "m0", "pbr": {"baseColorFactor": [1.0, 1.0, 1.0, 1.0], "metallicFactor": 0.0, "roughnessFactor": 0.8}}]
    split_at = len(tris) // len(surf_specs)
    primitives, materials, images, textures = [], [], [], []
    for s_idx, spec in enumerate(surf_specs):
        chunk = tris[s_idx * split_at : (len(tris) if s_idx == len(surf_specs) - 1 else (s_idx + 1) * split_at)]
        idx_bv = _add_bv(b"".join(struct.pack("<HHH", a, b, c) for a, b, c in chunk))
        accs.append({"bufferView": idx_bv, "componentType": 5123, "count": len(chunk) * 3, "type": "SCALAR"})
        pbr = dict(spec.get("pbr") or {"baseColorFactor": [1.0, 1.0, 1.0, 1.0], "metallicFactor": 0.0, "roughnessFactor": 0.8})
        if spec.get("with_texture"):
            img_bv = _add_bv(build_minimal_png_bytes(width=32, height=32, rgba=tuple(spec.get("rgba", (200, 160, 120, 255)))))
            images.append({"mimeType": "image/png", "bufferView": img_bv})
            textures.append({"source": len(images) - 1})
            pbr["baseColorTexture"] = {"index": len(textures) - 1}
        mat_doc: dict[str, Any] = {"name": str(spec.get("name", f"m{s_idx}")), "pbrMetallicRoughness": pbr}
        if "emissiveFactor" in spec:
            mat_doc["emissiveFactor"] = list(spec["emissiveFactor"])
        materials.append(mat_doc)
        primitives.append({"attributes": dict(attrs), "indices": len(accs) - 1, "material": s_idx})

    nodes: list[dict[str, Any]] = [{"name": node_name, "mesh": 0}]
    scene_nodes = [0]
    for ucx_name in ucx_names:
        nodes.append({"name": ucx_name, "mesh": 0})
        scene_nodes.append(len(nodes) - 1)

    gltf: dict[str, Any] = {
        "asset": {"version": "2.0", "generator": "forge3d-e2e-godot"}, "scene": 0,
        "scenes": [{"nodes": scene_nodes}], "nodes": nodes, "meshes": [{"primitives": primitives}],
        "materials": materials, "bufferViews": bvs, "accessors": accs, "buffers": [{"byteLength": 0}],
    }
    if images:
        gltf["images"], gltf["textures"] = images, textures

    bone_node_idx: dict[str, int] = {}
    if bones:
        base_idx, children_map, global_mats = len(nodes), {}, []
        for b_i, b in enumerate(bones):
            parent, t, q = int(b.get("parent", -1)), list(b.get("translation", [0.0, 0.0, 0.0])), list(b.get("rotation", [0.0, 0.0, 0.0, 1.0]))
            nodes.append({"name": str(b["name"]), "translation": t, "rotation": q})
            bone_node_idx[str(b["name"])] = base_idx + b_i
            local_m = _quat_to_mat4(q, t)
            global_mats.append(local_m if parent < 0 else _mat4_mul(global_mats[parent], local_m))
            if parent >= 0:
                children_map.setdefault(base_idx + parent, []).append(base_idx + b_i)
            else:
                scene_nodes.append(base_idx + b_i)
        for p_idx, ch_list in children_map.items():
            nodes[p_idx]["children"] = ch_list
        ibm_floats = [val for m in global_mats for val in _rigid_inv_col_major(m)]
        ibm_bv = _add_bv(struct.pack(f"<{len(ibm_floats)}f", *ibm_floats))
        accs.append({"bufferView": ibm_bv, "componentType": 5126, "count": len(bones), "type": "MAT4"})
        gltf["skins"] = [{"inverseBindMatrices": len(accs) - 1, "joints": [base_idx + i for i in range(len(bones))]}]
        nodes[0]["skin"] = 0

    if anim_clips and bone_node_idx:
        anims: list[dict[str, Any]] = []
        for clip_name, cfg in anim_clips.items():
            dur = float(cfg.get("duration", 1.0))
            t_bv = _add_bv(struct.pack("<3f", 0.0, dur * 0.5, dur))
            accs.append({"bufferView": t_bv, "componentType": 5126, "count": 3, "type": "SCALAR", "min": [0.0], "max": [dur]})
            t_acc = len(accs) - 1
            target_bones = [str(b) for b in cfg["bones"]] if "bones" in cfg else [str(cfg.get("bone", next(iter(bone_node_idx))))]
            samplers, channels = [], []
            for b_name in target_bones:
                if "translations" in cfg:
                    v_bv = _add_bv(b"".join(struct.pack("<fff", *v) for v in cfg["translations"]))
                    accs.append({"bufferView": v_bv, "componentType": 5126, "count": 3, "type": "VEC3"})
                    pk = "translation"
                else:
                    rots = cfg.get("rotations") or [[0.0, 0.0, 0.0, 1.0]] * 3
                    v_bv = _add_bv(b"".join(struct.pack("<ffff", *q) for q in rots))
                    accs.append({"bufferView": v_bv, "componentType": 5126, "count": 3, "type": "VEC4"})
                    pk = "rotation"
                s_idx = len(samplers)
                samplers.append({"input": t_acc, "interpolation": "LINEAR", "output": len(accs) - 1})
                channels.append({"sampler": s_idx, "target": {"node": bone_node_idx[b_name], "path": pk}})
            anims.append({"name": clip_name, "samplers": samplers, "channels": channels})
        gltf["animations"] = anims

    _pad4()
    gltf["buffers"][0]["byteLength"] = len(buf)
    jb = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    jb += b" " * ((4 - len(jb) % 4) % 4)
    total = 12 + 8 + len(jb) + 8 + len(buf)
    glb = struct.pack("<III", 0x46546C67, 2, total) + struct.pack("<II", len(jb), 0x4E4F534A) + jb + struct.pack("<II", len(buf), 0x004E4942) + bytes(buf)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(glb)
    return path


def write_orm_texture_set(base_dir: Path, asset_id: str, *, width: int = 64, height: int = 64) -> list[dict[str, Any]]:
    """Write valid `_baseColor.png`, `_normal.png`, `_orm.png` sibling maps and return `files` entries."""
    specs = [(f"{asset_id}_baseColor.png", "textura", (180, 140, 110, 255)), (f"{asset_id}_normal.png", "normal", (128, 128, 255, 255)), (f"{asset_id}_orm.png", "orm", (255, 160, 40, 255))]
    entries: list[dict[str, Any]] = []
    base_dir.mkdir(parents=True, exist_ok=True)
    for fname, papel, rgba in specs:
        fpath = base_dir / fname
        raw = build_minimal_png_bytes(width=width, height=height, rgba=rgba)
        fpath.write_bytes(raw)
        entries.append({"caminho": fname, "papel": papel, "sha256": f"sha256:{hashlib.sha256(raw).hexdigest()}", "bytes": len(raw)})
    return entries


def write_published_orm_asset(
    dest_dir: Path,
    asset_id: str = "prop.e2e.orm.01",
    *,
    perfil: str = "godot4",
    tipo: str = "prop_estatico",
    esqueleto: str | None = None,
    animacoes: Sequence[str] = (),
    with_lod1: bool = False,
    with_colisao: bool = False,
    size_xyz: tuple[float, float, float] = (1.0, 1.0, 1.0),
) -> tuple[Path, Path]:
    """Write a complete published `manifest@6` asset passing `forge3d verify`."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    glb_path = dest_dir / f"{asset_id}.glb"
    bones = HUMANOID_V1_BONES if esqueleto == "godot-humanoid@1" else (HUMANOID_V1_BONES[:3] if esqueleto else None)
    clips = ({c: {"bones": ["Hips", "Chest"], "duration": 1.0, "rotations": [[0, 0, 0, 1], [0, 0.15, 0, 0.988], [0, 0, 0, 1]]} for c in animacoes} if animacoes else None)
    write_custom_glb(glb_path, size_xyz=size_xyz, bones=bones, anim_clips=clips, node_name=asset_id)
    glb_bytes = glb_path.read_bytes()
    files: list[dict[str, Any]] = [{"caminho": glb_path.name, "papel": "mesh", "sha256": f"sha256:{hashlib.sha256(glb_bytes).hexdigest()}", "bytes": len(glb_bytes)}]
    files.extend(write_orm_texture_set(dest_dir, asset_id))
    lods = [{"nivel": 0, "triangulos": 12, "arquivo": glb_path.name}]
    if with_lod1:
        lod_path = dest_dir / f"{asset_id}_LOD1.glb"
        write_custom_glb(lod_path, size_xyz=size_xyz, bones=bones, node_name=f"{asset_id}_LOD1")
        lb = lod_path.read_bytes()
        files.append({"caminho": lod_path.name, "papel": "lod", "sha256": f"sha256:{hashlib.sha256(lb).hexdigest()}", "bytes": len(lb)})
        lods.append({"nivel": 1, "triangulos": 12, "arquivo": lod_path.name})
    col_obj: dict[str, Any] = {"tipo": "none", "partes": 0}
    if with_colisao:
        col_path = dest_dir / f"{asset_id}_colisao.glb"
        write_custom_glb(col_path, size_xyz=size_xyz, node_name=f"UCX_{asset_id}_col")
        cb = col_path.read_bytes()
        files.append({"caminho": col_path.name, "papel": "colisor", "sha256": f"sha256:{hashlib.sha256(cb).hexdigest()}", "bytes": len(cb)})
        col_obj = {"tipo": "convex", "partes": 1, "arquivo": col_path.name}

    sha_dummy = "sha256:" + ("b" * 64)
    bone_names = [b["name"] for b in bones] if bones else ["Root", "Hips", "Head"]
    manifest: dict[str, Any] = {
        "schema": "forge3d/manifest@6", "asset_id": asset_id, "projeto": "e2e_godot", "perfil": perfil,
        "tipo": tipo, "rota": "blocky", "tags": ["e2e", "godot4"], "spec_hash": sha_dummy,
        "pipeline_version": "0.9.4", "determinism": "D1",
        "providers": {"geometry": {"name": "blocky", "version": "0.9.4", "license": "CC0-1.0"}},
        "geometry": {"triangulos": 12, "vertices": 24, "bbox_m": [float(v) for v in size_xyz], "materiais": 1},
        "unidades_export": {"metros_por_unidade": 1.0, "escala_saida": 1.0},
        "animacoes": [{"nome": c, "duracao_s": 1.0, "ossos": bone_names} for c in animacoes],
        "rig": {"esqueleto": esqueleto, "ossos": len(bones)} if (esqueleto and bones) else None,
        "lod": lods, "colisao": col_obj, "files": files,
        "qc": {"aprovado": True, "gates": [{"id": "G2", "status": "ok", "medido": {"esperado_m": float(size_xyz[1]), "pivo_regra": "base"}}, {"id": "G9", "status": "ok", "medido": {"triangulos": 12, "limite": 5000}}]},
        "licenca": {"modelo": "CC0-1.0", "uso_comercial": True, "notice": "CC0-1.0 e2e fixture"},
        "origem_spec": {"arquivo": "lote.yaml", "hash": sha_dummy}, "run_id": "run-e2e-godot-1", "created_at": "2026-11-19T00:00:00Z",
    }
    return glb_path, write_manifest(dest_dir, asset_id, manifest)
