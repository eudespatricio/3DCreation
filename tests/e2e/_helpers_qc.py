"""Opaque-box GLB/PNG/manifest@6 builders and mutators for QC G1-G15 E2E tests."""

from __future__ import annotations

import hashlib
import json
import math
import struct
import zlib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from tests.e2e.conftest import build_minimal_png_bytes

GODOT_HUMANOID_BONES: tuple[str, ...] = (
    "Root", "Hips", "Spine", "Spine1", "Chest", "Neck", "Head",
    "Shoulder.L", "UpperArm.L", "LowerArm.L", "Hand.L",
    "Shoulder.R", "UpperArm.R", "LowerArm.R", "Hand.R",
    "UpperLeg.L", "LowerLeg.L", "Foot.L", "Toe.L",
    "UpperLeg.R", "LowerLeg.R", "Foot.R", "Toe.R",
)


def _quat_y(deg: float) -> tuple[float, float, float, float]:
    rad = math.radians(deg) * 0.5
    return (0.0, math.sin(rad), 0.0, math.cos(rad))


def write_png_file(
    path: Path,
    width: int = 64,
    height: int = 64,
    rgba: tuple[int, int, int, int] = (128, 128, 128, 255),
    *,
    corrupt_crc: bool = False,
) -> Path:
    raw = bytearray(build_minimal_png_bytes(width=width, height=height, rgba=rgba))
    if corrupt_crc:
        idx = raw.rfind(b"IDAT")
        assert idx > 0
        raw[idx + 8] ^= 0xFF
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(raw))
    return path


def make_silhouette_png(
    path: Path,
    *,
    width: int = 128,
    height: int = 128,
    rect: tuple[int, int, int, int] = (44, 16, 84, 112),
    fg_rgba: tuple[int, int, int, int] = (200, 60, 60, 255),
    bg_rgba: tuple[int, int, int, int] = (240, 240, 240, 255),
) -> Path:
    """Create a deterministic RGBA PNG with a solid silhouette rectangle on uniform background."""
    def _chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    x0, y0, x1, y1 = rect
    fg = bytes(fg_rgba)
    bg = bytes(bg_rgba)
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        for x in range(width):
            rows.extend(fg if (x0 <= x < x1 and y0 <= y < y1) else bg)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", zlib.compress(bytes(rows))) + _chunk(b"IEND", b"")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)
    return path


def write_hemisphere_normal_png(
    path: Path,
    *,
    width: int = 256,
    height: int = 256,
    opengl_y: bool = True,
) -> Path:
    """Write a spatial tangent-space hemisphere normal map (mean(G)~=128) in OpenGL +Y or DirectX -Y."""
    def _chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    cx = (width - 1) * 0.5
    cy = (height - 1) * 0.5
    radius = min(width, height) * 0.375
    sinal = -1.0 if opengl_y else 1.0
    flat = bytes((128, 128, 255, 255))
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        dy = (y - cy) / radius
        for x in range(width):
            dx = (x - cx) / radius
            d2 = dx * dx + dy * dy
            if d2 < 1.0:
                nz = math.sqrt(1.0 - d2)
                rows.extend((
                    max(0, min(255, 128 + round(127 * dx))),
                    max(0, min(255, 128 + round(127 * sinal * dy))),
                    max(0, min(255, 128 + round(127 * nz))),
                    255,
                ))
            else:
                rows.extend(flat)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", zlib.compress(bytes(rows))) + _chunk(b"IEND", b"")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)
    return path


def build_box_mesh(
    bounds_min: tuple[float, float, float],
    bounds_max: tuple[float, float, float],
    *,
    subdiv: int = 1,
    uv_mode: str = "tile",
    uv_tile: tuple[float, float, float, float] = (0.0, 0.0, 1.0, 1.0),
    omit_back: bool = False,
    flip_front: bool = False,
) -> tuple[list[tuple[float, float, float]], list[tuple[float, float, float]], list[tuple[float, float]], list[tuple[int, int, int]]]:
    """Build closed (or open/flipped) box geometry with optional subdivision and UV mode."""
    x0, y0, z0 = bounds_min
    x1, y1, z1 = bounds_max
    faces = [
        ("front", (0.0, 0.0, 1.0), (x0, y0, z1), (x1 - x0, 0.0, 0.0), (0.0, y1 - y0, 0.0)),
        ("back", (0.0, 0.0, -1.0), (x1, y0, z0), (x0 - x1, 0.0, 0.0), (0.0, y1 - y0, 0.0)),
        ("right", (1.0, 0.0, 0.0), (x1, y0, z1), (0.0, 0.0, z0 - z1), (0.0, y1 - y0, 0.0)),
        ("left", (-1.0, 0.0, 0.0), (x0, y0, z0), (0.0, 0.0, z1 - z0), (0.0, y1 - y0, 0.0)),
        ("top", (0.0, 1.0, 0.0), (x0, y1, z1), (x1 - x0, 0.0, 0.0), (0.0, 0.0, z0 - z1)),
        ("bottom", (0.0, -1.0, 0.0), (x0, y0, z0), (x1 - x0, 0.0, 0.0), (0.0, 0.0, z1 - z0)),
    ]
    u_min, v_min, u_max, v_max = uv_tile
    du = (u_max - u_min) / 3.0
    dv = (v_max - v_min) / 2.0
    verts, normals, uvs, tris = [], [], [], []

    for fidx, (fname, norm, origin, uvec, vvec) in enumerate(faces):
        if omit_back and fname == "back":
            continue
        col, row = fidx % 3, fidx // 3
        fu0, fu1 = u_min + col * du + 0.03 * du, u_min + (col + 1) * du - 0.03 * du
        fv0, fv1 = v_min + row * dv + 0.03 * dv, v_min + (row + 1) * dv - 0.03 * dv
        if uv_mode == "overlap":
            fu0, fv0, fu1, fv1 = 0.1, 0.1, 0.9, 0.9
        elif uv_mode == "oob":
            fu0, fv0, fu1, fv1 = 0.0, 0.0, 1.5, 1.5

        base = len(verts)
        for iy in range(subdiv + 1):
            ty = iy / subdiv
            for ix in range(subdiv + 1):
                tx = ix / subdiv
                vx = origin[0] + tx * uvec[0] + ty * vvec[0]
                vy = origin[1] + tx * uvec[1] + ty * vvec[1]
                vz = origin[2] + tx * uvec[2] + ty * vvec[2]
                verts.append((vx, vy, vz))
                normals.append(norm)
                uvs.append((fu0 + tx * (fu1 - fu0), fv0 + ty * (fv1 - fv0)))

        stride = subdiv + 1
        for iy in range(subdiv):
            for ix in range(subdiv):
                a = base + iy * stride + ix
                b = a + 1
                c = a + stride + 1
                d = a + stride
                if flip_front and fname == "front":
                    tris.extend([(a, c, b), (a, d, c)])
                else:
                    tris.extend([(a, b, c), (a, c, d)])
    return verts, normals, uvs, tris


def write_qc_glb(
    path: Path,
    *,
    boxes: Sequence[tuple[tuple[float, float, float], tuple[float, float, float]]] | None = None,
    verts: list[tuple[float, float, float]] | None = None,
    normals: list[tuple[float, float, float]] | None = None,
    uvs: list[tuple[float, float]] | None = None,
    tris: list[tuple[int, int, int]] | None = None,
    subdiv: int = 1,
    uv_mode: str = "tile",
    with_uv: bool = True,
    with_normals: bool = True,
    with_tangents: bool = False,
    with_material: bool = True,
    with_texture: bool = True,
    png_wh: tuple[int, int] = (64, 64),
    png_rgba: tuple[int, int, int, int] = (128, 128, 128, 255),
    corrupt_png_crc: bool = False,
    skin_mode: str | None = None,
    skin_bones: Sequence[str] | None = None,
    skin_positions: Mapping[str, Sequence[float]] | None = None,
    anim_mode: str | None = None,
    node_name: str = "Asset",
) -> Path:
    """Assemble a custom GLB for G1-G11 testing without touching forge3d internals."""
    if verts is None or normals is None or uvs is None or tris is None:
        all_boxes = list(boxes or [((-0.5, 0.0, -0.5), (0.5, 1.0, 0.5))])
        grid = max(1, math.ceil(math.sqrt(len(all_boxes))))
        verts, normals, uvs, tris = [], [], [], []
        for idx, (bmin, bmax) in enumerate(all_boxes):
            gx, gy = idx % grid, idx // grid
            uv_tile = (gx / grid, gy / grid, (gx + 1) / grid, (gy + 1) / grid)
            bv, bn, bu, bt = build_box_mesh(bmin, bmax, subdiv=subdiv, uv_mode=uv_mode, uv_tile=uv_tile)
            base = len(verts)
            verts.extend(bv)
            normals.extend(bn)
            uvs.extend(bu)
            tris.extend([(a + base, b + base, c + base) for a, b, c in bt])

    buf = bytearray()

    def _pad4() -> None:
        while len(buf) % 4:
            buf.append(0)

    def _add_bv(data: bytes) -> int:
        off = len(buf)
        buf.extend(data)
        bvs.append({"buffer": 0, "byteOffset": off, "byteLength": len(data)})
        _pad4()
        return len(bvs) - 1

    bvs: list[dict[str, Any]] = []
    accs: list[dict[str, Any]] = []
    attrs: dict[str, int] = {}

    pos_bv = _add_bv(b"".join(struct.pack("<fff", x, y, z) for x, y, z in verts))
    xs, ys, zs = [p[0] for p in verts], [p[1] for p in verts], [p[2] for p in verts]
    accs.append({
        "bufferView": pos_bv, "componentType": 5126, "count": len(verts), "type": "VEC3",
        "min": [min(xs), min(ys), min(zs)], "max": [max(xs), max(ys), max(zs)],
    })
    attrs["POSITION"] = len(accs) - 1

    if with_normals:
        nrm_bv = _add_bv(b"".join(struct.pack("<fff", nx, ny, nz) for nx, ny, nz in normals))
        accs.append({"bufferView": nrm_bv, "componentType": 5126, "count": len(verts), "type": "VEC3"})
        attrs["NORMAL"] = len(accs) - 1

    if with_uv:
        uv_bv = _add_bv(b"".join(struct.pack("<ff", u, v) for u, v in uvs))
        accs.append({"bufferView": uv_bv, "componentType": 5126, "count": len(verts), "type": "VEC2"})
        attrs["TEXCOORD_0"] = len(accs) - 1

    if with_tangents:
        tan_bv = _add_bv(b"".join(struct.pack("<ffff", 1.0, 0.0, 0.0, 1.0) for _ in verts))
        accs.append({"bufferView": tan_bv, "componentType": 5126, "count": len(verts), "type": "VEC4"})
        attrs["TANGENT"] = len(accs) - 1

    idx_bv = _add_bv(b"".join(struct.pack("<HHH", a, b, c) for a, b, c in tris))
    accs.append({"bufferView": idx_bv, "componentType": 5123, "count": len(tris) * 3, "type": "SCALAR"})
    idx_acc = len(accs) - 1

    nodes: list[dict[str, Any]] = [{"name": node_name, "mesh": 0}]
    scene_nodes = [0]
    skins: list[dict[str, Any]] = []
    animations: list[dict[str, Any]] = []

    if skin_mode is not None:
        bones_list = tuple(skin_bones or GODOT_HUMANOID_BONES)
        nodes[0]["skin"] = 0
        joint_indices: list[int] = []
        if skin_positions is not None:
            root_pos = [float(c) for c in skin_positions.get(bones_list[0], (0.0, 0.0, 0.0))]
            ibm_vals: list[float] = []
            for b_idx, bname in enumerate(bones_list):
                n_idx = len(nodes)
                pos = [float(c) for c in skin_positions.get(bname, root_pos)]
                if b_idx == 0:
                    node_obj: dict[str, Any] = {"name": bname, "translation": pos}
                    if len(bones_list) > 1:
                        node_obj["children"] = [n_idx + 1 + k for k in range(len(bones_list) - 1)]
                else:
                    node_obj = {"name": bname, "translation": [pos[d] - root_pos[d] for d in range(3)]}
                nodes.append(node_obj)
                joint_indices.append(n_idx)
                ibm_vals.extend((
                    1.0, 0.0, 0.0, 0.0,
                    0.0, 1.0, 0.0, 0.0,
                    0.0, 0.0, 1.0, 0.0,
                    -pos[0], -pos[1], -pos[2], 1.0,
                ))
            scene_nodes.append(joint_indices[0])
            ibm_bv = _add_bv(struct.pack(f"<{len(ibm_vals)}f", *ibm_vals))
        else:
            for b_idx, bname in enumerate(bones_list):
                n_idx = len(nodes)
                # Populate non-empty rest translations so tem_esq_pos=True; root 180-deg Y + Toe +Z keeps -Z roll/forward aligned.
                if b_idx == 0:
                    node_obj = {
                        "name": bname,
                        "translation": [0.0, 0.0, 0.0],
                        "rotation": [0.0, 1.0, 0.0, 0.0],
                    }
                elif bname in ("Toe.L", "Toe.R"):
                    node_obj = {"name": bname, "translation": [0.0, 0.0, 0.08]}
                else:
                    node_obj = {"name": bname, "translation": [0.0, 0.05, 0.0]}
                if b_idx < len(bones_list) - 1:
                    node_obj["children"] = [n_idx + 1]
                nodes.append(node_obj)
                joint_indices.append(n_idx)
            scene_nodes.append(joint_indices[0])

            ident = (
                1.0, 0.0, 0.0, 0.0,
                0.0, 1.0, 0.0, 0.0,
                0.0, 0.0, 1.0, 0.0,
                0.0, 0.0, 0.0, 1.0,
            )
            ibm_bv = _add_bv(b"".join(struct.pack("<16f", *ident) for _ in joint_indices))
        accs.append({"bufferView": ibm_bv, "componentType": 5126, "count": len(joint_indices), "type": "MAT4"})
        ibm_acc = len(accs) - 1

        j_bytes = bytearray()
        w_bytes = bytearray()
        for vi in range(len(verts)):
            if skin_mode == "root_only":
                j_bytes.extend(struct.pack("<HHHH", 0, 0, 0, 0))
                w_bytes.extend(struct.pack("<ffff", 1.0, 0.0, 0.0, 0.0))
            elif skin_mode == "zero_weight":
                j_bytes.extend(struct.pack("<HHHH", 1, 0, 0, 0))
                w_bytes.extend(struct.pack("<ffff", 0.0, 0.0, 0.0, 0.0))
            else:
                j = (1 + (vi % min(10, max(1, len(bones_list) - 1)))) if len(bones_list) > 1 else 0
                j_bytes.extend(struct.pack("<HHHH", j, 0, 0, 0))
                w_bytes.extend(struct.pack("<ffff", 1.0, 0.0, 0.0, 0.0))

        j_bv = _add_bv(bytes(j_bytes))
        accs.append({"bufferView": j_bv, "componentType": 5123, "count": len(verts), "type": "VEC4"})
        attrs["JOINTS_0"] = len(accs) - 1
        w_bv = _add_bv(bytes(w_bytes))
        accs.append({"bufferView": w_bv, "componentType": 5126, "count": len(verts), "type": "VEC4"})
        attrs["WEIGHTS_0"] = len(accs) - 1
        skins.append({"joints": joint_indices, "inverseBindMatrices": ibm_acc})

        if anim_mode is not None:
            t_bv = _add_bv(struct.pack("<fff", 0.0, 0.5, 1.0))
            accs.append({
                "bufferView": t_bv, "componentType": 5126, "count": 3, "type": "SCALAR",
                "min": [0.0], "max": [1.0],
            })
            t_acc = len(accs) - 1
            if anim_mode == "tiny_amp":
                angles_h = (0.0, 1.0, 0.0)
                angles_s = (0.0, 1.0, 0.0)
            elif anim_mode == "unclosed_loop":
                angles_h = (0.0, 30.0, 10.0)
                angles_s = (0.0, 25.0, 0.0)
            else:
                angles_h = (0.0, 15.0, 0.0)
                angles_s = (0.0, 12.0, 0.0)

            samplers: list[dict[str, Any]] = []
            channels: list[dict[str, Any]] = []
            for jnode, angs in ((joint_indices[1], angles_h), (joint_indices[2], angles_s)):
                q_bv = _add_bv(b"".join(struct.pack("<ffff", *_quat_y(a)) for a in angs))
                accs.append({"bufferView": q_bv, "componentType": 5126, "count": 3, "type": "VEC4"})
                q_acc = len(accs) - 1
                s_idx = len(samplers)
                samplers.append({"input": t_acc, "interpolation": "LINEAR", "output": q_acc})
                channels.append({"sampler": s_idx, "target": {"node": jnode, "path": "rotation"}})
            animations.append({"name": "idle", "channels": channels, "samplers": samplers})

    gltf: dict[str, Any] = {
        "asset": {"version": "2.0", "generator": "forge3d-e2e"},
        "scene": 0,
        "scenes": [{"nodes": scene_nodes}],
        "nodes": nodes,
        "meshes": [{"primitives": [{"attributes": attrs, "indices": idx_acc}]}],
        "bufferViews": bvs,
        "accessors": accs,
        "buffers": [{"byteLength": 0}],
    }
    if skins:
        gltf["skins"] = skins
    if animations:
        gltf["animations"] = animations
    if with_material:
        pbr: dict[str, Any] = {"baseColorFactor": [0.8, 0.8, 0.8, 1.0], "metallicFactor": 0.0, "roughnessFactor": 0.8}
        if with_texture:
            png_raw = bytearray(build_minimal_png_bytes(width=png_wh[0], height=png_wh[1], rgba=png_rgba))
            if corrupt_png_crc:
                idx = png_raw.rfind(b"IDAT")
                if idx > 0:
                    png_raw[idx + 8] ^= 0xFF
            img_bv = _add_bv(bytes(png_raw))
            gltf["images"] = [{"mimeType": "image/png", "bufferView": img_bv}]
            gltf["textures"] = [{"source": 0}]
            pbr["baseColorTexture"] = {"index": 0}
        gltf["materials"] = [{"name": "m0", "pbrMetallicRoughness": pbr}]
        gltf["meshes"][0]["primitives"][0]["material"] = 0

    gltf["buffers"][0]["byteLength"] = len(buf)
    jb = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    jb += b" " * ((4 - len(jb) % 4) % 4)
    total = 12 + 8 + len(jb) + 8 + len(buf)
    glb = struct.pack("<III", 0x46546C67, 2, total) + struct.pack("<II", len(jb), 0x4E4F534A) + jb
    glb += struct.pack("<II", len(buf), 0x004E4942) + bytes(buf)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(glb)
    return path


def publish_qc_bundle(
    dest_dir: Path,
    asset_id: str,
    *,
    glb_path: Path,
    perfil: str = "godot4",
    tipo: str = "prop_estatico",
    rota: str = "import",
    bbox_m: tuple[float, float, float] = (1.0, 1.0, 1.0),
    tris: int = 12,
    limite_tris: int = 5000,
    pivo_regra: str = "base",
    extra_files: Sequence[tuple[Path, str]] = (),
    manifest_overrides: Mapping[str, Any] | None = None,
) -> Path:
    """Write a schema-valid manifest@6 with exact SHA256/bytes for all declared files."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    escala = 3.5714 if perfil.startswith("roblox-") else 1.0
    metros = 0.28 if abs(escala - 3.5714) < 1e-4 else 1.0

    def _entry(p: Path, papel: str) -> dict[str, Any]:
        raw = p.read_bytes()
        return {
            "caminho": p.name,
            "papel": papel,
            "sha256": f"sha256:{hashlib.sha256(raw).hexdigest()}",
            "bytes": len(raw),
        }

    files = [_entry(glb_path, "mesh"), *[_entry(p, papel) for p, papel in extra_files]]
    sha_dummy = "sha256:" + ("c" * 64)
    manifest: dict[str, Any] = {
        "schema": "forge3d/manifest@6",
        "asset_id": asset_id,
        "projeto": "e2e_qc",
        "perfil": perfil,
        "tipo": tipo,
        "rota": rota,
        "tags": ["e2e", "qc"],
        "spec_hash": sha_dummy,
        "pipeline_version": "0.9.4",
        "determinism": "D1",
        "providers": {"geometry": {"name": rota, "version": "0.9.4", "license": "CC0-1.0"}},
        "geometry": {"triangulos": tris, "vertices": max(4, tris * 2), "bbox_m": [float(v) for v in bbox_m], "materiais": 1},
        "unidades_export": {"metros_por_unidade": metros, "escala_saida": escala},
        "animacoes": [],
        "rig": None,
        "lod": [{"nivel": 0, "triangulos": tris, "arquivo": glb_path.name}],
        "colisao": {"tipo": "none", "partes": 0},
        "files": files,
        "qc": {
            "aprovado": True,
            "gates": [
                {"id": "G2", "status": "ok", "medido": {"esperado_m": float(bbox_m[1]), "pivo_regra": pivo_regra}},
                {"id": "G9", "status": "ok", "medido": {"triangulos": tris, "limite": limite_tris}},
            ],
        },
        "licenca": {"modelo": "CC0-1.0", "uso_comercial": True, "notice": "CC0-1.0 qc test"},
        "origem_spec": {"arquivo": "lote.yaml", "hash": sha_dummy},
        "run_id": "run-qc-e2e",
        "created_at": "2026-11-19T00:00:00Z",
    }
    if manifest_overrides:
        manifest.update(dict(manifest_overrides))
    man_path = dest_dir / f"{asset_id}.manifest.json"
    man_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return man_path


def extract_failed_gates(payload: dict[str, Any] | list[Any] | None) -> set[str]:
    """Collect failed gate IDs from `forge3d verify --json` output."""
    if not isinstance(payload, dict):
        return set()
    gates: set[str] = set()
    for err in payload.get("erros") or []:
        if isinstance(err, dict):
            for gate in err.get("gates") or []:
                if isinstance(gate, dict) and gate.get("id"):
                    gates.add(str(gate["id"]))
    return gates
