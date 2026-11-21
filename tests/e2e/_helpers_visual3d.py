"""Shared opaque-box helpers for FA4 Visual 3D Zero-Cost E2E tests (no `import forge3d`)."""

from __future__ import annotations

import base64
import io
import json
import os
import shutil
import stat
import struct
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml
from PIL import Image, ImageDraw

from tests.e2e.conftest import RAIZ, build_minimal_png_bytes, find_blender


def run_tool(
    script_rel: str,
    args: Sequence[str],
    *,
    env_overrides: Mapping[str, str] | None = None,
    cwd: Path | None = None,
    timeout: int = 120,
) -> subprocess.CompletedProcess[str]:
    """Execute a CLI script under `tools/` via subprocess."""
    env = dict(os.environ)
    if env_overrides:
        env.update({str(k): str(v) for k, v in env_overrides.items()})
    return subprocess.run(
        [sys.executable, str(RAIZ / script_rel), *[str(a) for a in args]],
        cwd=str(cwd or RAIZ), env=env, capture_output=True, text=True, timeout=timeout,
    )


def run_blender_expr(
    code: str, *, env_overrides: Mapping[str, str] | None = None, timeout: int = 180
) -> subprocess.CompletedProcess[str]:
    """Run an isolated Blender 4.2.x background expression subprocess."""
    blender_bin = find_blender()
    assert blender_bin is not None, "Blender 4.2.x binary unavailable in environment"
    env = dict(os.environ)
    env["FORGE3D_CYCLES_DEVICE"] = "CPU"
    if env_overrides:
        env.update({str(k): str(v) for k, v in env_overrides.items()})
    return subprocess.run(
        [blender_bin, "--background", "--factory-startup", "--python-expr", code],
        cwd=str(RAIZ), env=env, capture_output=True, text=True, timeout=timeout,
    )


def mpfb_sandbox_env(sandbox_dir: Path) -> dict[str, str]:
    """Expose host MPFB2 extension/assets read-only while sandboxing Blender user config/resources."""
    home = Path.home()
    host_cfg = home / ".config" / "blender" / "4.2" / "config"
    blender_res = sandbox_dir / "blender_res"
    sandbox_cfg = blender_res / "config"
    sandbox_cfg.mkdir(parents=True, exist_ok=True)
    if host_cfg.is_dir():
        shutil.copytree(host_cfg, sandbox_cfg, dirs_exist_ok=True)
    return {
        "BLENDER_USER_RESOURCES": str(blender_res),
        "BLENDER_USER_CONFIG": str(sandbox_cfg),
        "BLENDER_USER_EXTENSIONS": str(home / ".config" / "blender" / "4.2" / "extensions"),
        "FORGE3D_MPFB_DIR": str(home / ".config" / "blender" / "4.2" / "extensions" / "user_default" / "mpfb"),
        "FORGE3D_MPFB_ASSETS": str(home / ".cache" / "forge3d" / "mpfb_assets"),
        "FORGE3D_MPFB_ASSETS_ZIP": str(home / ".cache" / "forge3d" / "mpfb_assets" / "makehuman_system_assets_cc0.zip"),
        "FORGE3D_VENV_I23D": str(home / ".cache" / "forge3d" / "venv-i23d"),
        "FORGE3D_TRIPOSR": str(home / ".cache" / "forge3d" / "vendor" / "TripoSR"),
        "U2NET_HOME": os.environ.get("U2NET_HOME") or str(home / ".u2net"),
        "FORGE3D_REMBG_MODELO": os.environ.get("FORGE3D_REMBG_MODELO") or "u2net",
        "FORGE3D_CYCLES_DEVICE": "CPU",
        "CUDA_VISIBLE_DEVICES": "",
    }


def setup_offline_i23d_shim(base_dir: Path, glb_template: Path) -> tuple[dict[str, str], Path]:
    """Create a zero-GPU offline i23d boundary shim recording invocations at `marker_path`."""
    venv_bin, vendor, modelos = base_dir / "venv_i23d" / "bin", base_dir / "vendor_triposr", base_dir / "modelos"
    for d in (modelos / "TripoSR", venv_bin, vendor / "torch", vendor / "tsr"):
        d.mkdir(parents=True, exist_ok=True)
    py_shim = venv_bin / "python"
    py_shim.write_text(f"#!/bin/sh\nexec {sys.executable!r} \"$@\"\n", encoding="utf-8")
    py_shim.chmod(py_shim.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    (vendor / "torch" / "__init__.py").write_text(
        "__version__ = '2.5.0+e2e'\nclass cuda:\n    @staticmethod\n    def is_available():\n        return False\n",
        encoding="utf-8",
    )
    (vendor / "tsr" / "__init__.py").write_text("__version__ = '0.1.0+e2e'\n", encoding="utf-8")
    marker_path, i23d_script = base_dir / "i23d_invoked.json", base_dir / "i23d_stub.py"
    i23d_script.write_text(
        f"""import argparse, json, shutil
from pathlib import Path
p = argparse.ArgumentParser()
p.add_argument("--imagem", required=True)
p.add_argument("--saida-dir", required=True)
p.add_argument("--resultado", required=True)
args, _ = p.parse_known_args()
out = Path(args.saida_dir)
out.mkdir(parents=True, exist_ok=True)
shutil.copyfile({str(glb_template)!r}, out / "modelo.glb")
src = Path(args.imagem)
if src.is_file(): shutil.copyfile(src, out / "input.png")
Path({str(marker_path)!r}).write_text(json.dumps({{"imagem": str(src)}}), encoding="utf-8")
Path(args.resultado).write_text(json.dumps({{"ok": True, "arquivo": "modelo.glb", "faces": 12}}), encoding="utf-8")
""",
        encoding="utf-8",
    )
    return {
        "FORGE3D_VENV_I23D": str(base_dir / "venv_i23d"), "FORGE3D_TRIPOSR": str(vendor),
        "FORGE3D_MODELOS": str(modelos), "FORGE3D_I23D_SCRIPT": str(i23d_script),
        "FORGE3D_I23D_DEVICE": "cpu", "FORGE3D_POSE_GUARD": "off",
        "FORGE3D_CYCLES_DEVICE": "CPU", "CUDA_VISIBLE_DEVICES": "",
    }, marker_path


def build_sword_silhouette_bytes(*, fmt: str = "JPEG", size: tuple[int, int] = (128, 128)) -> bytes:
    """Create a high-contrast upright sword silhouette image (JPEG or PNG) for concept/extrude2d."""
    w, h = size
    mode = "RGB" if fmt.upper() == "JPEG" else "RGBA"
    bg = (235, 235, 240) if mode == "RGB" else (0, 0, 0, 0)
    img = Image.new(mode, size, bg)
    draw = ImageDraw.Draw(img)
    cx = w // 2
    blade = (180, 190, 205) if mode == "RGB" else (180, 190, 205, 255)
    guard = (175, 135, 45) if mode == "RGB" else (175, 135, 45, 255)
    grip = (90, 55, 35) if mode == "RGB" else (90, 55, 35, 255)
    draw.polygon([(cx, int(h * 0.08)), (cx + int(w * 0.06), int(h * 0.22)), (cx - int(w * 0.06), int(h * 0.22))], fill=blade)
    draw.rectangle([cx - int(w * 0.05), int(h * 0.20), cx + int(w * 0.05), int(h * 0.68)], fill=blade)
    draw.rectangle([cx - int(w * 0.18), int(h * 0.67), cx + int(w * 0.18), int(h * 0.74)], fill=guard)
    draw.rectangle([cx - int(w * 0.03), int(h * 0.74), cx + int(w * 0.03), int(h * 0.90)], fill=grip)
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


def register_gemini_mock(
    mock_http_server: Any, *, concept_bytes: bytes | None = None,
    concept_mime: str = "image/jpeg", qa_payload: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Register POST /v1beta/interactions handling both concept generation and Gemini visual QA."""
    parsed_calls: list[dict[str, Any]] = []
    img_b64 = base64.b64encode(concept_bytes or build_sword_silhouette_bytes(fmt="JPEG")).decode("ascii")
    qa_json = json.dumps(qa_payload or {"aprovado": True, "nota": 9.0, "defeitos": []})

    def _respond(raw_body: bytes, headers: Any) -> dict[str, Any]:
        body = json.loads(raw_body.decode("utf-8"))
        parsed_calls.append({"headers": {k.lower(): v for k, v in headers.items()}, "body": body})
        if "hydrogen" in str(body.get("model") or ""):
            return {"steps": [{"type": "model_output", "content": [{"type": "text", "text": qa_json}]}]}
        return {"steps": [{"type": "model_output", "content": [{"type": "image", "data": img_b64, "mime_type": concept_mime}]}]}

    mock_http_server.add_route("POST", "/v1beta/interactions", _respond, status=200)
    return parsed_calls


def make_mesh_spec(
    dest_dir: Path, items: list[dict[str, Any]], *,
    projeto: str = "e2e_visual3d", perfil: str = "godot4", estilo_global: str = "stylized_pbr",
) -> dict[str, Any]:
    """Build a canonical `forge3d/spec@6` dictionary."""
    return {
        "schema": "forge3d/spec@6", "projeto": projeto, "perfil": perfil,
        "destino_exportacao": str(dest_dir), "estilo_global": estilo_global,
        "paleta": ["#6b7280", "#884422", "#d4af37"], "lote": items,
    }


def write_tight_budget_profile(path: Path, *, bytes_max_kb: int = 550) -> Path:
    """Create a sandboxed copy of `profiles/godot4.yaml` with tight `bytes_max_kb` budget."""
    prof = yaml.safe_load((RAIZ / "profiles" / "godot4.yaml").read_text(encoding="utf-8"))
    prof["validacao"]["bytes_max_kb"] = int(bytes_max_kb)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(prof, sort_keys=False), encoding="utf-8")
    return path


def make_two_tone_png_bytes(width: int = 512, height: int = 512) -> bytes:
    """Create a sharp half-white / half-black PNG to expose Sobel normal contamination."""
    img = Image.new("RGBA", (width, height), (245, 245, 245, 255))
    img.paste((12, 12, 12, 255), (width // 2, 0, width, height))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def write_two_tone_glb(path: Path, *, png_wh: tuple[int, int] = (512, 512)) -> Path:
    """Build a minimal closed-cube GLB with sharp two-tone `baseColorTexture` for bake tests."""
    from tests.e2e.conftest import _build_cube_geometry

    verts, normals, uvs, tris = _build_cube_geometry(1.0, 1.0, 1.0)
    buf = bytearray()

    def _add(raw: bytes) -> tuple[int, int]:
        while len(buf) % 4:
            buf.append(0)
        off = len(buf)
        buf.extend(raw)
        return off, len(raw)

    po, pl = _add(b"".join(struct.pack("<fff", *v) for v in verts))
    no, nl = _add(b"".join(struct.pack("<fff", *n) for n in normals))
    uo, ul = _add(b"".join(struct.pack("<ff", *uv) for uv in uvs))
    io_off, il = _add(b"".join(struct.pack("<HHH", *t) for t in tris))
    imo, iml = _add(make_two_tone_png_bytes(*png_wh))
    while len(buf) % 4:
        buf.append(0)
    xs, ys, zs = [p[0] for p in verts], [p[1] for p in verts], [p[2] for p in verts]
    gltf = {
        "asset": {"version": "2.0", "generator": "forge3d-e2e-visual3d"},
        "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"name": "TwoToneCube", "mesh": 0}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1, "TEXCOORD_0": 2}, "indices": 3, "material": 0}]}],
        "materials": [{"name": "TwoToneMat", "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}, "metallicFactor": 0.0, "roughnessFactor": 0.8}}],
        "textures": [{"source": 0}], "images": [{"mimeType": "image/png", "bufferView": 4}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": po, "byteLength": pl},
            {"buffer": 0, "byteOffset": no, "byteLength": nl},
            {"buffer": 0, "byteOffset": uo, "byteLength": ul},
            {"buffer": 0, "byteOffset": io_off, "byteLength": il},
            {"buffer": 0, "byteOffset": imo, "byteLength": iml},
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": len(verts), "type": "VEC3", "min": [min(xs), min(ys), min(zs)], "max": [max(xs), max(ys), max(zs)]},
            {"bufferView": 1, "componentType": 5126, "count": len(verts), "type": "VEC3"},
            {"bufferView": 2, "componentType": 5126, "count": len(verts), "type": "VEC2"},
            {"bufferView": 3, "componentType": 5123, "count": len(tris) * 3, "type": "SCALAR"},
        ],
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


def inspect_glb_textures(glb_path: Path) -> list[dict[str, Any]]:
    """Read embedded PNG dimensions and color channel variance directly from a GLB binary."""
    data = glb_path.read_bytes()
    assert len(data) >= 20 and struct.unpack_from("<I", data, 0)[0] == 0x46546C67
    off, gltf, bin_chunk = 12, None, b""
    while off + 8 <= len(data):
        length, ctype = struct.unpack_from("<II", data, off)
        chunk = data[off + 8 : off + 8 + length]
        off += 8 + length
        if ctype == 0x4E4F534A:
            gltf = json.loads(chunk.decode("utf-8"))
        elif ctype == 0x004E4942:
            bin_chunk = chunk
    assert gltf is not None
    bvs, results = gltf.get("bufferViews") or [], []
    for idx, img in enumerate(gltf.get("images") or []):
        bv_idx = img.get("bufferView")
        if bv_idx is None:
            results.append({"index": idx, "uri": img.get("uri"), "embedded": False})
            continue
        bv = bvs[int(bv_idx)]
        raw = bin_chunk[int(bv.get("byteOffset", 0)) : int(bv.get("byteOffset", 0)) + int(bv["byteLength"])]
        with Image.open(io.BytesIO(raw)) as im:
            rgb = im.convert("RGB")
            results.append({
                "index": idx, "embedded": True, "width": im.width, "height": im.height,
                "extrema": rgb.getextrema(), "unique_sample": len(set(rgb.resize((64, 64)).getdata())),
            })
    return results


def inspect_glb_overlay_gaps_mm(glb_path: Path) -> dict[str, list[float]]:
    """Measure opaque-box min gap (mm) from forearm bracelets, boot cuffs, and belt to body in a published GLB."""
    code = f"""
import json, bpy, bmesh
from mathutils.bvhtree import BVHTree
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath={str(glb_path)!r})
m = next(o for o in bpy.data.objects if o.type == "MESH")
bm = bmesh.new(); bm.from_mesh(m.data); bm.transform(m.matrix_world)
bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1e-4)
verts = list(bm.verts); zs = [v.co.z for v in verts]; z0, h = min(zs), max(zs) - min(zs)
seen, comps = set(), []
for v in verts:
    if v.index in seen: continue
    stack, comp = [v], []
    seen.add(v.index)
    while stack:
        cur = stack.pop(); comp.append(cur)
        for e in cur.link_edges:
            nb = e.other_vert(cur)
            if nb.index not in seen: seen.add(nb.index); stack.append(nb)
    comps.append(comp)
comps.sort(key=len, reverse=True)
def _bvh_for(subset):
    b_idx = {{v.index for v in subset}}; bm_s = bmesh.new()
    vmap = {{v.index: bm_s.verts.new(v.co) for v in subset}}
    for f in bm.faces:
        if all(v.index in b_idx for v in f.verts):
            try: bm_s.faces.new([vmap[v.index] for v in f.verts])
            except ValueError: pass
    return BVHTree.FromBMesh(bm_s), bm_s
bvh_body, bm_body = _bvh_for(comps[0])
bvh_torso, bm_torso = _bvh_for([v for c in comps if len(c) >= 200 for v in c])
bracelets_mm, boots_mm, belt_mm = [], [], []
for c in comps[1:]:
    czs = [(v.co.z - z0) / h for v in c]; cxs = [abs(v.co.x) / h for v in c]
    z_lo, z_hi, x_hi = min(czs), max(czs), max(cxs)
    if 0.55 <= z_lo and z_hi <= 0.78 and x_hi >= 0.16 and len(c) >= 24:
        bracelets_mm.append(round(min(bvh_body.find_nearest(v.co)[3] for v in c) * 1000.0, 3))
    elif 0.03 <= z_lo and z_hi <= 0.28 and len(c) >= 100:
        boots_mm.append(round(min(bvh_body.find_nearest(v.co)[3] for v in c) * 1000.0, 3))
    elif 0.45 <= z_lo and z_hi <= 0.56 and 60 <= len(c) <= 150:
        belt_mm.append(round(min(bvh_torso.find_nearest(v.co)[3] for v in c) * 1000.0, 3))
bm_body.free(); bm_torso.free(); bm.free()
print("OVERLAY_JSON:" + json.dumps({{"bracelets_mm": bracelets_mm, "boots_mm": boots_mm, "belt_mm": belt_mm}}))
"""
    proc = run_blender_expr(code)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    for line in proc.stdout.splitlines():
        if line.startswith("OVERLAY_JSON:"):
            return json.loads(line.split("OVERLAY_JSON:", 1)[1])
    raise AssertionError(f"missing OVERLAY_JSON in Blender stdout:\n{proc.stdout}")


def inspect_glb_chestplate_fit(arm_glb: Path, body_glb: Path) -> dict[str, Any]:
    """Inspect manifoldness and torso-conforming chestplate dimensions of `arm_glb` vs `body_glb`."""
    code = f"""
import json, bpy, bmesh
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath={str(arm_glb)!r})
m_a = next(o for o in bpy.data.objects if o.type == "MESH")
bm_a = bmesh.new(); bm_a.from_mesh(m_a.data); bm_a.transform(m_a.matrix_world)
bmesh.ops.remove_doubles(bm_a, verts=list(bm_a.verts), dist=1e-4)
nm = sum(1 for e in bm_a.edges if len(e.link_faces) != 2)
vs_a = [v.co for v in bm_a.verts]
ax_lo, ax_hi = min(v.x for v in vs_a), max(v.x for v in vs_a)
ay_lo, ay_hi = min(v.y for v in vs_a), max(v.y for v in vs_a)
az_lo, az_hi = min(v.z for v in vs_a), max(v.z for v in vs_a)
bm_a.free()
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath={str(body_glb)!r})
m_b = next(o for o in bpy.data.objects if o.type == "MESH")
bm_b = bmesh.new(); bm_b.from_mesh(m_b.data); bm_b.transform(m_b.matrix_world)
torso = [v.co for v in bm_b.verts if 1.05 <= v.co.z <= 1.45 and abs(v.co.x) <= 0.22]
bw = max(v.x for v in torso) - min(v.x for v in torso)
bd = max(v.y for v in torso) - min(v.y for v in torso)
bm_b.free()
print("CHEST_JSON:" + json.dumps({{
    "verts": len(vs_a), "nao_manifold": nm,
    "w": round(ax_hi - ax_lo, 4), "d": round(ay_hi - ay_lo, 4), "h": round(az_hi - az_lo, 4),
    "center_x": round(0.5 * (ax_lo + ax_hi), 4),
    "body_torso_w": round(bw, 4), "body_torso_d": round(bd, 4),
}}))
"""
    proc = run_blender_expr(code)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    for line in proc.stdout.splitlines():
        if line.startswith("CHEST_JSON:"):
            return json.loads(line.split("CHEST_JSON:", 1)[1])
    raise AssertionError(f"missing CHEST_JSON in Blender stdout:\n{proc.stdout}")


def make_turntable_png(path: Path, *, forehead_smear: bool = False, leg_asymmetry: bool = False) -> Path:
    """Create a 2x2 turntable PNG (256x256) with clean or defective humanoid silhouettes."""
    img = Image.new("RGBA", (256, 256), (220, 224, 230, 255))
    draw = ImageDraw.Draw(img)
    for q_idx, (ox, oy) in enumerate([(0, 0), (128, 0), (0, 128), (128, 128)]):
        cx = ox + 64
        draw.rectangle([cx - 10, oy + 16, cx + 10, oy + 34], fill=(210, 175, 145, 255))
        if forehead_smear and q_idx == 0:
            draw.rectangle([cx - 10, oy + 16, cx + 10, oy + 23], fill=(10, 10, 12, 255))
        for ty in range(oy + 35, oy + 75):
            for tx in range(cx - 16, cx + 17):
                shade = (tx % 4) * 8
                img.putpixel((tx, ty), (70 + shade, 95 + shade, 145, 255))
        left_col = (50, 60, 80, 255)
        right_col = (195, 50, 50, 255) if (leg_asymmetry and q_idx == 0) else (50, 60, 80, 255)
        draw.rectangle([cx - 15, oy + 75, cx - 5, oy + 112], fill=left_col)
        draw.rectangle([cx + 5, oy + 75, cx + 15, oy + 112], fill=right_col)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, format="PNG")
    return path


def make_hero_front_png(path: Path) -> Path:
    """Create a clean 128x128 front-view humanoid concept PNG."""
    tmp_tt = path.with_suffix(".tt.png")
    make_turntable_png(tmp_tt)
    with Image.open(tmp_tt) as im:
        im.crop((0, 0, 128, 128)).save(path, format="PNG")
    tmp_tt.unlink(missing_ok=True)
    return path


def make_delight_test_sprite(path: Path) -> Path:
    """Create an RGBA sprite with silver metallic, warm skin, cool cloth, and bright emissive rune."""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    for y in range(8, 56):
        for x in range(8, 28):
            v = 180 + ((x - 8) % 8)
            img.putpixel((x, y), (v, v, min(255, v + 4), 255))
    for y in range(8, 32):
        for x in range(30, 56):
            img.putpixel((x, y), (40, 50, 140, 255))
    for y in range(32, 56):
        for x in range(30, 56):
            img.putpixel((x, y), (160, 105, 65, 255))
    for y in range(24, 40):
        for x in range(36, 48):
            img.putpixel((x, y), (255, 235, 65, 255))
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, format="PNG")
    return path


def setup_offline_trellis2_shim(base_dir: Path, glb_template: Path) -> dict[str, str]:
    """Create a zero-GPU, zero-network offline local TRELLIS.2 shim emitting `glb_template`."""
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
        f"#!/bin/sh\nPYTHONPATH={str(site_dir)!r}:\"${{PYTHONPATH:-}}\"\nexport PYTHONPATH\nexec {sys.executable!r} \"$@\"\n",
        encoding="utf-8",
    )
    py_shim.chmod(py_shim.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    infer_stub = base_dir / "trellis2_infer_stub.py"
    infer_stub.write_text(
        "import argparse, json, shutil\nfrom pathlib import Path\n"
        "p = argparse.ArgumentParser()\np.add_argument('--imagem', required=True)\np.add_argument('--saida-dir', required=True)\np.add_argument('--resultado', required=True)\n"
        "args, _ = p.parse_known_args()\nout = Path(args.saida_dir)\nout.mkdir(parents=True, exist_ok=True)\n"
        f"shutil.copyfile({str(glb_template)!r}, out / 'modelo.glb')\n"
        "if Path(args.imagem).is_file() and Path(args.imagem).resolve() != (out / 'input.png').resolve():\n"
        "    shutil.copyfile(args.imagem, out / 'input.png')\n"
        "Path(args.resultado).write_text(json.dumps({'ok': True, 'provedor': 'trellis2_local', 'modelo': 'microsoft/TRELLIS.2-4B', 'arquivo': 'modelo.glb', 'faces': 12}), encoding='utf-8')\n",
        encoding="utf-8",
    )
    return {
        "FORGE3D_MODELO_MESH": "trellis2",
        "FORGE3D_TRELLIS2_DIR": str(t2_dir),
        "FORGE3D_TRELLIS2_SCRIPT": str(infer_stub),
        "FORGE3D_I23D_DEVICE": "cuda:0",
        "FORGE3D_VRAM_MINIMA_MB": "0",
        "FORGE3D_POSE_GUARD": "off",
        "FORGE3D_DELIGHT": "0",
    }


def write_concept_and_render_pair(root: Path, *, mismatch: bool) -> tuple[Path, Path]:
    """Create a concept PNG and either a matching square or mismatched 3D render PNG."""
    root.mkdir(parents=True, exist_ok=True)
    c_path = root / "concept_ref.png"
    r_path = root / ("render_mismatch.png" if mismatch else "render_match.png")
    c_img = Image.new("RGBA", (128, 128), (220, 220, 220, 255))
    if not mismatch:
        ImageDraw.Draw(c_img).rectangle([24, 24, 104, 104], fill=(128, 128, 128, 255))
        c_img.save(c_path, format="PNG")
        c_img.save(r_path, format="PNG")
    else:
        ImageDraw.Draw(c_img).rectangle([52, 16, 76, 112], fill=(210, 40, 40, 255))
        c_img.save(c_path, format="PNG")
        r_img = Image.new("RGBA", (128, 128), (220, 220, 220, 255))
        ImageDraw.Draw(r_img).rectangle([12, 56, 116, 72], fill=(40, 60, 210, 255))
        r_img.save(r_path, format="PNG")
    return c_path, r_path


def minimal_png_bytes(width: int = 64, height: int = 64) -> bytes:
    return build_minimal_png_bytes(width=width, height=height)
