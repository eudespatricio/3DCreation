"""Opaque-box Roblox R15, GLB, manifest@6, and XML builders/inspectors for E2E-M2."""

from __future__ import annotations

import hashlib
import json
import math
import struct
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from tests.e2e._helpers_qc import write_qc_glb
from tests.e2e.conftest import build_minimal_png_bytes

R15_15_PARTS: tuple[str, ...] = (
    "LowerTorso", "UpperTorso", "Head",
    "LeftUpperArm", "LeftLowerArm", "LeftHand",
    "RightUpperArm", "RightLowerArm", "RightHand",
    "LeftUpperLeg", "LeftLowerLeg", "LeftFoot",
    "RightUpperLeg", "RightLowerLeg", "RightFoot",
)

R15_PARENT_MAP: dict[str, str] = {
    "LowerTorso": "HumanoidRootPart", "UpperTorso": "LowerTorso", "Head": "UpperTorso",
    "LeftUpperArm": "UpperTorso", "LeftLowerArm": "LeftUpperArm", "LeftHand": "LeftLowerArm",
    "RightUpperArm": "UpperTorso", "RightLowerArm": "RightUpperArm", "RightHand": "RightLowerArm",
    "LeftUpperLeg": "LowerTorso", "LeftLowerLeg": "LeftUpperLeg", "LeftFoot": "LeftLowerLeg",
    "RightUpperLeg": "LowerTorso", "RightLowerLeg": "RightUpperLeg", "RightFoot": "RightLowerLeg",
}

R15_JOINT_NAMES: dict[str, str] = {
    "LowerTorso": "Root", "UpperTorso": "Waist", "Head": "Neck",
    "LeftUpperArm": "LeftShoulder", "LeftLowerArm": "LeftElbow", "LeftHand": "LeftWrist",
    "RightUpperArm": "RightShoulder", "RightLowerArm": "RightElbow", "RightHand": "RightWrist",
    "LeftUpperLeg": "LeftHip", "LeftLowerLeg": "LeftKnee", "LeftFoot": "LeftAnkle",
    "RightUpperLeg": "RightHip", "RightLowerLeg": "RightKnee", "RightFoot": "RightAnkle",
}

R15_ANCHORS_DEFAULT: dict[str, list[float]] = {
    "Root": [0.0, 2.5, 0.0], "Waist": [0.0, 3.3, 0.0], "Neck": [0.0, 4.6, 0.0],
    "LeftShoulder": [-1.2, 4.3, 0.0], "LeftElbow": [-1.4, 3.5, 0.0], "LeftWrist": [-1.4, 2.7, 0.0],
    "RightShoulder": [1.2, 4.3, 0.0], "RightElbow": [1.4, 3.5, 0.0], "RightWrist": [1.4, 2.7, 0.0],
    "LeftHip": [-0.5, 2.2, 0.0], "LeftKnee": [-0.5, 1.2, 0.0], "LeftAnkle": [-0.5, 0.3, 0.0],
    "RightHip": [0.5, 2.2, 0.0], "RightKnee": [0.5, 1.2, 0.0], "RightAnkle": [0.5, 0.3, 0.0],
}


def _cube_geom_in_bounds(
    bounds_min: tuple[float, float, float],
    bounds_max: tuple[float, float, float],
    uv_tile: tuple[float, float, float, float],
) -> tuple[list[tuple[float, float, float]], list[tuple[float, float, float]], list[tuple[float, float]], list[tuple[int, int, int]]]:
    x0, y0, z0 = bounds_min
    x1, y1, z1 = bounds_max
    u0, v0, u1, v1 = uv_tile
    faces = [
        ((0.0, 0.0, 1.0), [(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]),
        ((0.0, 0.0, -1.0), [(x1, y0, z0), (x0, y0, z0), (x0, y1, z0), (x1, y1, z0)]),
        ((1.0, 0.0, 0.0), [(x1, y0, z1), (x1, y0, z0), (x1, y1, z0), (x1, y1, z1)]),
        ((-1.0, 0.0, 0.0), [(x0, y0, z0), (x0, y0, z1), (x0, y1, z1), (x0, y1, z0)]),
        ((0.0, 1.0, 0.0), [(x0, y1, z1), (x1, y1, z1), (x1, y1, z0), (x0, y1, z0)]),
        ((0.0, -1.0, 0.0), [(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)]),
    ]
    verts, normals, uvs, tris = [], [], [], []
    du = (u1 - u0) / 3.0
    dv = (v1 - v0) / 2.0
    for fidx, (norm, corners) in enumerate(faces):
        base = len(verts)
        col, row = fidx % 3, fidx // 3
        fu0, fu1 = u0 + col * du + 0.04 * du, u0 + (col + 1) * du - 0.04 * du
        fv0, fv1 = v0 + row * dv + 0.04 * dv, v0 + (row + 1) * dv - 0.04 * dv
        for corner, uv in zip(corners, [(fu0, fv0), (fu1, fv0), (fu1, fv1), (fu0, fv1)]):
            verts.append(corner)
            normals.append(norm)
            uvs.append(uv)
        tris.extend([(base, base + 1, base + 2), (base, base + 2, base + 3)])
    return verts, normals, uvs, tris


def make_custom_r15_glb(
    path: Path,
    *,
    prim_count: int = 1,
    cubes_per_prim: int = 1,
    pad_bytes: int = 0,
    size_xyz: tuple[float, float, float] = (1.0, 1.0, 1.0),
    node_name: str = "Asset",
) -> Path:
    """Create a valid multi-primitive or high-tri closed-manifold GLB with non-overlapping UVs."""
    sx, sy, sz = size_xyz
    hx, hz = sx / 2.0, sz / 2.0
    total_cubes = prim_count * cubes_per_prim
    grid = max(1, math.ceil(math.sqrt(total_cubes)))
    buf = bytearray()
    bvs: list[dict[str, Any]] = []
    accs: list[dict[str, Any]] = []
    primitives: list[dict[str, Any]] = []

    def _pad4() -> None:
        while len(buf) % 4:
            buf.append(0)

    cube_idx = 0
    for _p in range(prim_count):
        verts: list[tuple[float, float, float]] = []
        normals: list[tuple[float, float, float]] = []
        uvs: list[tuple[float, float]] = []
        tris: list[tuple[int, int, int]] = []
        for _c in range(cubes_per_prim):
            if total_cubes == 1:
                bmin, bmax = (-hx, 0.0, -hz), (hx, sy, hz)
            else:
                # Keep symmetric outer span (-hx..hx, 0..sy, -hz..hz) while keeping sub-cubes disjoint
                t = cube_idx / max(1, total_cubes - 1)
                sub = min(sx, sy, sz) * 0.02
                if cube_idx == 0:
                    bmin, bmax = (-hx, 0.0, -hz), (-hx + sub, sub, -hz + sub)
                elif cube_idx == total_cubes - 1:
                    bmin, bmax = (hx - sub, sy - sub, hz - sub), (hx, sy, hz)
                else:
                    cx = -hx * 0.6 + 1.2 * hx * ((cube_idx % 7) / 6.0)
                    cz = -hz * 0.6 + 1.2 * hz * (((cube_idx // 7) % 7) / 6.0)
                    cy = sub + t * max(sub, sy - 3.0 * sub)
                    bmin = (cx - sub * 0.4, cy, cz - sub * 0.4)
                    bmax = (cx + sub * 0.4, cy + sub * 0.4, cz + sub * 0.4)
            gx, gy = cube_idx % grid, cube_idx // grid
            uv_tile = (gx / grid, gy / grid, (gx + 1) / grid, (gy + 1) / grid)
            cv, cn, cu, ct = _cube_geom_in_bounds(bmin, bmax, uv_tile)
            base = len(verts)
            verts.extend(cv)
            normals.extend(cn)
            uvs.extend(cu)
            tris.extend([(a + base, b + base, c + base) for a, b, c in ct])
            cube_idx += 1

        pos_off = len(buf)
        for x, y, z in verts:
            buf.extend(struct.pack("<fff", x, y, z))
        pos_bv = len(bvs)
        bvs.append({"buffer": 0, "byteOffset": pos_off, "byteLength": len(buf) - pos_off})
        xs, ys, zs = [p[0] for p in verts], [p[1] for p in verts], [p[2] for p in verts]
        pos_acc = len(accs)
        accs.append({
            "bufferView": pos_bv, "componentType": 5126, "count": len(verts), "type": "VEC3",
            "min": [min(xs), min(ys), min(zs)], "max": [max(xs), max(ys), max(zs)],
        })

        nrm_off = len(buf)
        for nx, ny, nz in normals:
            buf.extend(struct.pack("<fff", nx, ny, nz))
        nrm_bv = len(bvs)
        bvs.append({"buffer": 0, "byteOffset": nrm_off, "byteLength": len(buf) - nrm_off})
        nrm_acc = len(accs)
        accs.append({"bufferView": nrm_bv, "componentType": 5126, "count": len(verts), "type": "VEC3"})

        uv_off = len(buf)
        for u, v in uvs:
            buf.extend(struct.pack("<ff", u, v))
        uv_bv = len(bvs)
        bvs.append({"buffer": 0, "byteOffset": uv_off, "byteLength": len(buf) - uv_off})
        uv_acc = len(accs)
        accs.append({"bufferView": uv_bv, "componentType": 5126, "count": len(verts), "type": "VEC2"})

        idx_off = len(buf)
        use_u32 = len(verts) > 65535
        fmt = "<III" if use_u32 else "<HHH"
        for a, b, c in tris:
            buf.extend(struct.pack(fmt, a, b, c))
        idx_bv = len(bvs)
        bvs.append({"buffer": 0, "byteOffset": idx_off, "byteLength": len(buf) - idx_off})
        idx_acc = len(accs)
        accs.append({
            "bufferView": idx_bv,
            "componentType": 5125 if use_u32 else 5123,
            "count": len(tris) * 3,
            "type": "SCALAR",
        })
        _pad4()
        primitives.append({
            "attributes": {"POSITION": pos_acc, "NORMAL": nrm_acc, "TEXCOORD_0": uv_acc},
            "indices": idx_acc,
            "material": 0,
        })

    img_off = len(buf)
    buf.extend(build_minimal_png_bytes(width=64, height=64))
    img_len = len(buf) - img_off
    _pad4()
    img_bv = len(bvs)
    bvs.append({"buffer": 0, "byteOffset": img_off, "byteLength": img_len})

    if pad_bytes > len(buf):
        buf.extend(b"\x00" * (pad_bytes - len(buf)))
    _pad4()

    gltf: dict[str, Any] = {
        "asset": {"version": "2.0", "generator": "forge3d-e2e"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"name": node_name, "mesh": 0}],
        "meshes": [{"primitives": primitives}],
        "images": [{"mimeType": "image/png", "bufferView": img_bv}],
        "textures": [{"source": 0}],
        "materials": [{
            "name": "m0",
            "pbrMetallicRoughness": {"baseColorFactor": [1.0, 1.0, 1.0, 1.0], "baseColorTexture": {"index": 0}},
        }],
        "bufferViews": bvs,
        "accessors": accs,
        "buffers": [{"byteLength": len(buf)}],
    }
    jb = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    jb += b" " * ((4 - len(jb) % 4) % 4)
    total = 12 + 8 + len(jb) + 8 + len(buf)
    glb = struct.pack("<III", 0x46546C67, 2, total) + struct.pack("<II", len(jb), 0x4E4F534A) + jb
    glb += struct.pack("<II", len(buf), 0x004E4942) + bytes(buf)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(glb)
    return path


def make_sparse_oversized_glb(path: Path, size_bytes: int = 20 * 1024 * 1024 + 1) -> Path:
    """Write a fast sparse file with a valid GLB magic header exceeding 20 MB."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fh:
        fh.write(struct.pack("<III", 0x46546C67, 2, size_bytes))
        fh.seek(size_bytes - 1)
        fh.write(b"\x00")
    return path


def _file_entry(path: Path, papel: str) -> dict[str, Any]:
    raw = path.read_bytes()
    return {
        "caminho": path.name,
        "papel": papel,
        "sha256": f"sha256:{hashlib.sha256(raw).hexdigest()}",
        "bytes": len(raw),
    }


def write_r15_segmented_package(
    dest_dir: Path,
    asset_id: str = "char.e2e.knight.01",
    *,
    projeto: str = "e2e_roblox",
    state_dir: Path | None = None,
    with_4ch_textures: bool = True,
    with_orm: bool = False,
    scale: float = 3.5714,
    sockets: list[dict[str, Any]] | None = None,
    asset_id_start: int = 500001,
) -> tuple[Path, Path]:
    """Publish a segmented 15-part R15 manifest@6 bundle with optional PBR textures and ledger."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    metros = 0.28 if abs(scale - 3.5714) < 1e-4 else round(1.0 / scale, 6)
    main_glb = dest_dir / f"{asset_id}.glb"
    skin_pos = {
        "HumanoidRootPart": [0.0, 0.0, 0.0],
        **{p: list(R15_ANCHORS_DEFAULT[R15_JOINT_NAMES[p]]) for p in R15_15_PARTS},
    }
    write_qc_glb(
        main_glb,
        boxes=[((-0.5 * scale, 0.0, -0.25 * scale), (0.5 * scale, 1.8 * scale, 0.25 * scale))],
        skin_mode="valid",
        skin_bones=("HumanoidRootPart", *R15_15_PARTS),
        skin_positions=skin_pos,
        node_name=asset_id,
    )
    files: list[dict[str, Any]] = [_file_entry(main_glb, "mesh")]
    partes_meta: list[dict[str, Any]] = []
    ledger_rows: list[dict[str, Any]] = []
    next_id = asset_id_start
    half = 0.1

    for part_name in R15_15_PARTS:
        p_glb = dest_dir / f"{part_name}.glb"
        junta = R15_JOINT_NAMES[part_name]
        ancora = list(R15_ANCHORS_DEFAULT[junta])
        ax, ay, az = ancora
        write_qc_glb(
            p_glb,
            boxes=[((ax - half, ay - half, az - half), (ax + half, ay + half, az + half))],
            node_name=part_name,
        )
        files.append(_file_entry(p_glb, "parte"))
        partes_meta.append({
            "nome": part_name,
            "papel": "parte",
            "junta": junta,
            "pivo": "junta",
            "ancora": ancora,
            "bbox": [half * 2.0, half * 2.0, half * 2.0],
            "triangulos": 12,
            "arquivo": p_glb.name,
        })
        ledger_rows.append({
            "evento": "upload",
            "id": f"{asset_id}.{part_name}",
            "asset_id": next_id,
            "asset_type": "Model",
            "arquivo": str(p_glb),
        })
        next_id += 1

    if with_4ch_textures:
        chan_map = [
            (f"{asset_id}_baseColor.png", "textura", (190, 170, 150, 255)),
            (f"{asset_id}_normal.png", "normal", (128, 192, 255, 255)),
            (f"{asset_id}_roughness.png", "roughness", (160, 160, 160, 255)),
            (f"{asset_id}_metalness.png", "metallic", (64, 64, 64, 255)),
        ]
        for fname, papel, rgba in chan_map:
            tpath = dest_dir / fname
            tpath.write_bytes(build_minimal_png_bytes(64, 64, rgba=rgba))
            files.append(_file_entry(tpath, papel))
            ledger_rows.append({
                "evento": "upload",
                "id": tpath.stem,
                "asset_id": next_id,
                "asset_type": "Image",
                "arquivo": str(tpath),
            })
            next_id += 1

    if with_orm:
        orm_path = dest_dir / f"{asset_id}_orm.png"
        orm_path.write_bytes(build_minimal_png_bytes(64, 64, rgba=(255, 180, 30, 255)))
        files.append(_file_entry(orm_path, "orm"))

    if state_dir is not None:
        state_dir.mkdir(parents=True, exist_ok=True)
        with (state_dir / "ledger.jsonl").open("a", encoding="utf-8") as fh:
            for row in ledger_rows:
                fh.write(json.dumps(row) + "\n")

    sha_dummy = "sha256:" + ("b" * 64)
    manifest: dict[str, Any] = {
        "schema": "forge3d/manifest@6",
        "asset_id": asset_id,
        "projeto": projeto,
        "perfil": "roblox-r15",
        "tipo": "personagem_humanoide",
        "rota": "mesh",
        "tags": ["e2e", "r15"],
        "spec_hash": sha_dummy,
        "pipeline_version": "0.9.4",
        "determinism": "D1",
        "providers": {"geometry": {"name": "mesh", "version": "0.9.4", "license": "CC0-1.0"}},
        "geometry": {"triangulos": 192, "vertices": 384, "bbox_m": [1.0, 1.8, 0.5], "materiais": 1, "tangentes": True},
        "unidades_export": {"metros_por_unidade": metros, "escala_saida": scale},
        "animacoes": [],
        "rig": {
            "esqueleto": "r15@1",
            "ossos": 16,
            "modo": "motor6d",
            "modo_rig_roblox": "motor6d",
            "ancoras": dict(R15_ANCHORS_DEFAULT),
        },
        "partes": partes_meta,
        "lod": [{"nivel": 0, "triangulos": 192, "arquivo": main_glb.name}],
        "colisao": {"tipo": "none", "partes": 0},
        "files": files,
        "qc": {
            "aprovado": True,
            "gates": [
                {"id": "G2", "status": "ok", "medido": {"esperado_m": 1.8, "pivo_regra": "base"}},
                {"id": "G9", "status": "ok", "medido": {"triangulos": 192, "limite": 8000}},
            ],
        },
        "licenca": {"modelo": "CC0-1.0", "uso_comercial": True, "notice": "CC0-1.0 e2e"},
        "origem_spec": {"arquivo": "lote.yaml", "hash": sha_dummy},
        "run_id": "run-r15-e2e",
        "created_at": "2026-11-19T00:00:00Z",
    }
    if sockets is not None:
        manifest["sockets"] = sockets
    man_path = dest_dir / f"{asset_id}.manifest.json"
    man_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return main_glb, man_path


def make_r15_spec(
    dest_dir: Path,
    item_id: str = "char.e2e.hero.01",
    *,
    rota: str = "blocky",
    projeto: str = "e2e_roblox",
    extra_item: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a valid spec@6 dictionary targeting roblox-r15."""
    item: dict[str, Any] = {
        "id": item_id,
        "tipo": "personagem_humanoide",
        "rota": rota,
        "prompt": "stylized humanoid hero",
        "altura_metros": 1.8,
        "pivot": "base",
        "limite_triangulos": 8000,
        "auto_rig": True,
        "esqueleto": "r15@1",
        "animacoes_base": ["idle", "walk", "run"],
        "colisao": "none",
    }
    if extra_item:
        item.update(extra_item)
    return {
        "schema": "forge3d/spec@6",
        "projeto": projeto,
        "perfil": "roblox-r15",
        "destino_exportacao": str(dest_dir),
        "estilo_global": "blocky_voxel",
        "lote": [item],
    }


def props_dict(item_elem: ET.Element) -> dict[str, ET.Element]:
    props = item_elem.find("Properties")
    if props is None:
        return {}
    return {el.attrib["name"]: el for el in props if "name" in el.attrib}


def find_pose_tree(keyframe_elem: ET.Element) -> dict[str, tuple[str | None, ET.Element]]:
    """Map every <Item class='Pose'> name inside a Keyframe to (parent_pose_name, element)."""
    out: dict[str, tuple[str | None, ET.Element]] = {}

    def _walk(node: ET.Element, parent_name: str | None) -> None:
        for child in node:
            if child.tag == "Item" and child.attrib.get("class") == "Pose":
                pdict = props_dict(child)
                pname = pdict["Name"].text if "Name" in pdict else ""
                out[str(pname)] = (parent_name, child)
                _walk(child, pname)

    _walk(keyframe_elem, None)
    return out


def cframe_position(cf_elem: ET.Element) -> tuple[float, float, float]:
    return (
        float(cf_elem.findtext("X", "0")),
        float(cf_elem.findtext("Y", "0")),
        float(cf_elem.findtext("Z", "0")),
    )


def vector3_values(vec_elem: ET.Element) -> tuple[float, float, float]:
    return (
        float(vec_elem.findtext("X", "0")),
        float(vec_elem.findtext("Y", "0")),
        float(vec_elem.findtext("Z", "0")),
    )


def refresh_single_mesh_manifest(
    man_path: Path, glb_path: Path, *, tris: int, limite: int, qualidade: str | None = None
) -> None:
    man = json.loads(man_path.read_text(encoding="utf-8"))
    raw = glb_path.read_bytes()
    man["files"][0]["sha256"] = f"sha256:{hashlib.sha256(raw).hexdigest()}"
    man["files"][0]["bytes"] = len(raw)
    man["geometry"]["triangulos"] = tris
    man["lod"] = [{"nivel": 0, "triangulos": tris, "arquivo": glb_path.name}]
    man["qc"]["gates"][1]["medido"] = {"triangulos": tris, "limite": limite}
    if qualidade:
        man["qualidade"] = qualidade
    man_path.write_text(json.dumps(man, indent=2), encoding="utf-8")


def recompute_manifest_hashes(man_path: Path, dest_dir: Path) -> None:
    man = json.loads(man_path.read_text(encoding="utf-8"))
    for entry in man["files"]:
        raw = (dest_dir / entry["caminho"]).read_bytes()
        entry["sha256"] = f"sha256:{hashlib.sha256(raw).hexdigest()}"
        entry["bytes"] = len(raw)
    man_path.write_text(json.dumps(man, indent=2), encoding="utf-8")


def find_attachment_y(rbxlx_path: Path, att_name: str) -> float:
    root = ET.fromstring(rbxlx_path.read_text(encoding="utf-8"))
    for att in root.findall(".//Item[@class='Attachment']"):
        p = props_dict(att)
        if p.get("Name") is not None and p["Name"].text == att_name:
            return cframe_position(p["CFrame"])[1]
    raise AssertionError(f"Attachment {att_name} not found in {rbxlx_path}")
