"""Shared opaque-box E2E test harness for Forge3D (strictly zero `import forge3d`)."""

from __future__ import annotations

import hashlib
import http.server
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import zlib
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml

RAIZ = Path(__file__).resolve().parents[2]
_REAL_HOME = Path.home()

_SCRUB_ENV_KEYS = (
    "FORGE3D_HOME", "FORGE3D_CONFIG", "FORGE3D_JSON_OUT", "FORGE3D_VAULT_DIR",
    "FORGE3D_GEMINI_API_KEY", "FORGE3D_HIGGSFIELD_API_KEY", "FORGE3D_FAL_API_KEY",
    "FORGE3D_ROBLOX_API_KEY", "ROBLOX_OPEN_CLOUD_API_KEY", "FORGE3D_ROBLOX_API_KEY_FILE",
    "FORGE3D_ROBLOX_CREATOR_ID", "FORGE3D_ROBLOX_CREATOR_TYPE",
    "FORGE3D_GEMINI_API_URL", "FORGE3D_GEMINI_EMBEDDING_URL", "FORGE3D_GEMINI_MODELO",
    "FORGE3D_HIGGSFIELD_API_URL", "FORGE3D_FAL_API_URL", "FORGE3D_ROBLOX_API_URL",
    "FORGE3D_MODELO_CONCEPT", "FORGE3D_MODELO_MESH", "FORGE3D_DEVICE",
)


def find_blender() -> str | None:
    """Return path to Blender binary if present on host, else None."""
    for candidate in (
        os.environ.get("FORGE3D_BLENDER"),
        shutil.which("blender"),
        str(_REAL_HOME / ".local" / "bin" / "blender"),
    ):
        if candidate and Path(candidate).is_file():
            return str(candidate)
    return None


def has_blender() -> bool:
    return find_blender() is not None


def find_godot() -> str | None:
    """Return path to Godot 4 binary if present on host, else None."""
    for candidate in (
        os.environ.get("FORGE3D_GODOT"),
        shutil.which("godot"),
        str(_REAL_HOME / ".gemini" / "antigravity" / "bin" / "godot"),
        str(_REAL_HOME / "tools" / "godot" / "Godot_v4.3-stable_linux.x86_64"),
    ):
        if candidate and Path(candidate).is_file():
            return str(candidate)
    return None


def has_godot() -> bool:
    return find_godot() is not None


def _run_cli_with_env(
    base_env: Mapping[str, str],
    args: Sequence[str],
    *,
    env_overrides: Mapping[str, str] | None = None,
    json_out: bool = True,
    timeout: int = 300,
    cwd: Path | None = None,
) -> tuple[int, str, str, dict[str, Any] | list[Any] | None]:
    """Run `forge3d.cli.main` as an opaque subprocess and return (rc, stdout, stderr, payload)."""
    cmd_args = list(args)
    wants_help = any(flag in cmd_args for flag in ("-h", "--help", "--version"))
    if json_out and not wants_help and "--json" not in cmd_args:
        cmd_args.append("--json")

    proc_env = dict(base_env)
    if env_overrides:
        proc_env.update({str(k): str(v) for k, v in env_overrides.items()})

    with tempfile.TemporaryDirectory(prefix="forge3d-e2e-json-") as tmp_json_dir:
        json_path = Path(tmp_json_dir) / "out.json"
        if json_out and not wants_help:
            proc_env["FORGE3D_JSON_OUT"] = str(json_path)
        elif "FORGE3D_JSON_OUT" not in (env_overrides or {}):
            proc_env.pop("FORGE3D_JSON_OUT", None)

        proc = subprocess.run(
            [sys.executable, "-m", "forge3d.cli.main", *cmd_args],
            cwd=str(cwd or RAIZ),
            env=proc_env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        payload: dict[str, Any] | list[Any] | None = None
        if json_out and not wants_help:
            if json_path.is_file():
                raw = json_path.read_text(encoding="utf-8").strip()
                if raw:
                    payload = json.loads(raw)
            elif proc.stdout.strip():
                try:
                    payload = json.loads(proc.stdout)
                except json.JSONDecodeError:
                    payload = None

    return proc.returncode, proc.stdout, proc.stderr, payload


@dataclass(frozen=True)
class E2ESandbox:
    """Isolated ext4 sandbox for opaque-box E2E tests."""

    root: Path
    home: Path
    state_dir: Path
    config_dir: Path
    dest_dir: Path
    env: dict[str, str]

    def run_cli(
        self,
        args: Sequence[str],
        *,
        env_overrides: Mapping[str, str] | None = None,
        json_out: bool = True,
        timeout: int = 300,
        cwd: Path | None = None,
    ) -> tuple[int, str, str, dict[str, Any] | list[Any] | None]:
        return _run_cli_with_env(
            self.env, args, env_overrides=env_overrides, json_out=json_out, timeout=timeout, cwd=cwd
        )

    def allowlist_add(self, path: Path | str) -> Path:
        target = Path(path)
        rc, stdout, stderr, payload = self.run_cli(["allowlist", "add", str(target)], json_out=True)
        assert rc == 0, f"allowlist add failed (rc={rc}): stdout={stdout} stderr={stderr}"
        assert isinstance(payload, dict) and "adicionado" in payload
        return target


@pytest.fixture
def repo_root() -> Path:
    return RAIZ


@pytest.fixture
def e2e_sandbox(tmp_path: Path) -> E2ESandbox:
    """Provision isolated HOME/XDG dirs on ext4 with pre-allowlisted `dest_dir`."""
    home = tmp_path / "home"
    state_dir = home / ".local" / "state" / "forge3d"
    config_dir = home / ".config" / "forge3d"
    dest_dir = tmp_path / "dest"
    for d in (home, state_dir, config_dir):
        d.mkdir(parents=True, exist_ok=True)

    env = dict(os.environ)
    for key in _SCRUB_ENV_KEYS:
        env.pop(key, None)
    env.update({
        "HOME": str(home), "XDG_STATE_HOME": str(home / ".local" / "state"),
        "XDG_CONFIG_HOME": str(home / ".config"), "FORGE3D_ROOT": str(RAIZ), "PYTHONPATH": str(RAIZ / "src"),
    })
    sandbox = E2ESandbox(
        root=tmp_path, home=home, state_dir=state_dir, config_dir=config_dir, dest_dir=dest_dir, env=env
    )
    sandbox.allowlist_add(dest_dir)
    return sandbox


@pytest.fixture
def run_cli(e2e_sandbox: E2ESandbox):
    return e2e_sandbox.run_cli


def _write_spec_file(path: Path, data: Mapping[str, Any] | str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = data if isinstance(data, str) else yaml.safe_dump(dict(data), sort_keys=False, allow_unicode=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def write_spec() -> Callable[[Path, Mapping[str, Any] | str], Path]:
    return _write_spec_file


def build_minimal_png_bytes(
    width: int = 64, height: int = 64, rgba: tuple[int, int, int, int] = (128, 128, 128, 255)
) -> bytes:
    """Generate a deterministic valid RGBA PNG using only stdlib zlib/struct."""

    def _chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    raw = (b"\x00" + bytes(rgba) * width) * height
    return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", zlib.compress(raw)) + _chunk(b"IEND", b"")


def _write_minimal_png(
    path: Path, *, width: int = 64, height: int = 64, rgba: tuple[int, int, int, int] = (128, 128, 128, 255)
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(build_minimal_png_bytes(width=width, height=height, rgba=rgba))
    return path


@pytest.fixture
def make_minimal_png():
    return _write_minimal_png


def _build_cube_geometry(sx: float, sy: float, sz: float):
    """Return 24-vert closed cube (base Y=0, XZ centered) with outward CCW tris and 3x2 UV tiles."""
    hx, hz = sx / 2.0, sz / 2.0
    faces = [
        ((0.0, 0.0, 1.0), [(-hx, 0.0, hz), (hx, 0.0, hz), (hx, sy, hz), (-hx, sy, hz)]),
        ((0.0, 0.0, -1.0), [(hx, 0.0, -hz), (-hx, 0.0, -hz), (-hx, sy, -hz), (hx, sy, -hz)]),
        ((1.0, 0.0, 0.0), [(hx, 0.0, hz), (hx, 0.0, -hz), (hx, sy, -hz), (hx, sy, hz)]),
        ((-1.0, 0.0, 0.0), [(-hx, 0.0, -hz), (-hx, 0.0, hz), (-hx, sy, hz), (-hx, sy, -hz)]),
        ((0.0, 1.0, 0.0), [(-hx, sy, hz), (hx, sy, hz), (hx, sy, -hz), (-hx, sy, -hz)]),
        ((0.0, -1.0, 0.0), [(-hx, 0.0, -hz), (hx, 0.0, -hz), (hx, 0.0, hz), (-hx, 0.0, hz)]),
    ]
    verts, normals, uvs, tris = [], [], [], []
    for face_idx, (norm, corners) in enumerate(faces):
        base = len(verts)
        col, row = face_idx % 3, face_idx // 3
        u0, u1 = col / 3.0 + 0.02, (col + 1) / 3.0 - 0.02
        v0, v1 = row / 2.0 + 0.02, (row + 1) / 2.0 - 0.02
        for corner, uv in zip(corners, [(u0, v0), (u1, v0), (u1, v1), (u0, v1)]):
            verts.append(corner)
            normals.append(norm)
            uvs.append(uv)
        tris.extend([(base, base + 1, base + 2), (base, base + 2, base + 3)])
    return verts, normals, uvs, tris


def _write_minimal_glb(
    path: Path,
    *,
    size_xyz: tuple[float, float, float] = (1.0, 1.0, 1.0),
    png_wh: tuple[int, int] = (64, 64),
    with_uv: bool = True,
    with_normals: bool = True,
    with_material: bool = True,
    with_texture: bool = True,
    node_name: str = "Asset",
) -> Path:
    """Create a valid closed-cube GLB passing QC G1-G5, Blender import, and Godot headless."""
    verts, normals, uvs, tris = _build_cube_geometry(*size_xyz)
    buf = bytearray()

    def _pad4() -> None:
        while len(buf) % 4:
            buf.append(0)

    pos_off = len(buf)
    for x, y, z in verts:
        buf.extend(struct.pack("<fff", x, y, z))
    bvs: list[dict[str, int]] = [{"buffer": 0, "byteOffset": pos_off, "byteLength": len(buf) - pos_off}]
    xs, ys, zs = [p[0] for p in verts], [p[1] for p in verts], [p[2] for p in verts]
    accs: list[dict[str, Any]] = [{
        "bufferView": 0, "componentType": 5126, "count": len(verts), "type": "VEC3",
        "min": [min(xs), min(ys), min(zs)], "max": [max(xs), max(ys), max(zs)],
    }]
    attrs: dict[str, int] = {"POSITION": 0}

    if with_normals:
        nrm_off = len(buf)
        for nx, ny, nz in normals:
            buf.extend(struct.pack("<fff", nx, ny, nz))
        bvs.append({"buffer": 0, "byteOffset": nrm_off, "byteLength": len(buf) - nrm_off})
        accs.append({"bufferView": len(bvs) - 1, "componentType": 5126, "count": len(verts), "type": "VEC3"})
        attrs["NORMAL"] = len(accs) - 1

    if with_uv:
        uv_off = len(buf)
        for u, v in uvs:
            buf.extend(struct.pack("<ff", u, v))
        bvs.append({"buffer": 0, "byteOffset": uv_off, "byteLength": len(buf) - uv_off})
        accs.append({"bufferView": len(bvs) - 1, "componentType": 5126, "count": len(verts), "type": "VEC2"})
        attrs["TEXCOORD_0"] = len(accs) - 1

    idx_off = len(buf)
    for a, b, c in tris:
        buf.extend(struct.pack("<HHH", a, b, c))
    bvs.append({"buffer": 0, "byteOffset": idx_off, "byteLength": len(buf) - idx_off})
    accs.append({"bufferView": len(bvs) - 1, "componentType": 5123, "count": len(tris) * 3, "type": "SCALAR"})
    idx_acc = len(accs) - 1
    _pad4()

    gltf: dict[str, Any] = {
        "asset": {"version": "2.0", "generator": "forge3d-e2e"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"name": node_name, "mesh": 0}],
        "meshes": [{"primitives": [{"attributes": attrs, "indices": idx_acc}]}],
        "bufferViews": bvs,
        "accessors": accs,
        "buffers": [{"byteLength": 0}],
    }
    if with_material:
        pbr: dict[str, Any] = {"baseColorFactor": [1.0, 1.0, 1.0, 1.0], "metallicFactor": 0.0, "roughnessFactor": 0.8}
        if with_texture:
            img_off = len(buf)
            buf.extend(build_minimal_png_bytes(width=png_wh[0], height=png_wh[1]))
            img_len = len(buf) - img_off
            _pad4()
            bvs.append({"buffer": 0, "byteOffset": img_off, "byteLength": img_len})
            gltf["images"] = [{"mimeType": "image/png", "bufferView": len(bvs) - 1}]
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


@pytest.fixture
def make_minimal_glb():
    return _write_minimal_glb


def write_published_asset(
    dest_dir: Path,
    asset_id: str = "prop.e2e.crate.01",
    *,
    projeto: str = "e2e_test",
    perfil: str = "godot4",
    size_xyz: tuple[float, float, float] = (1.0, 1.0, 1.0),
    escala_saida: float | None = None,
    manifest_overrides: Mapping[str, Any] | None = None,
) -> tuple[Path, Path]:
    """Write a compliant GLB + `manifest@6` pair directly to `dest_dir` without importing forge3d."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    escala = (3.5714 if perfil.startswith("roblox-") else 1.0) if escala_saida is None else float(escala_saida)
    metros = 0.28 if abs(escala - 3.5714) < 1e-4 else round(1.0 / escala, 6)
    glb_path = dest_dir / f"{asset_id}.glb"
    glb_size = (size_xyz[0] * escala, size_xyz[1] * escala, size_xyz[2] * escala)
    _write_minimal_glb(glb_path, size_xyz=glb_size, node_name=asset_id)
    glb_bytes = glb_path.read_bytes()
    digest = hashlib.sha256(glb_bytes).hexdigest()
    sha_dummy = "sha256:" + ("a" * 64)
    manifest: dict[str, Any] = {
        "schema": "forge3d/manifest@6", "asset_id": asset_id, "projeto": projeto, "perfil": perfil,
        "tipo": "prop_estatico", "rota": "blocky", "tags": ["e2e"], "spec_hash": sha_dummy,
        "pipeline_version": "0.9.4", "determinism": "D1",
        "providers": {"geometry": {"name": "blocky", "version": "0.9.4", "license": "CC0-1.0"}},
        "geometry": {"triangulos": 12, "vertices": 24, "bbox_m": [float(x) for x in size_xyz], "materiais": 1},
        "unidades_export": {"metros_por_unidade": metros, "escala_saida": escala},
        "animacoes": [], "rig": None,
        "lod": [{"nivel": 0, "triangulos": 12, "arquivo": glb_path.name}],
        "colisao": {"tipo": "none", "partes": 0},
        "files": [{"caminho": glb_path.name, "papel": "mesh", "sha256": f"sha256:{digest}", "bytes": len(glb_bytes)}],
        "qc": {
            "aprovado": True,
            "gates": [
                {"id": "G2", "status": "ok", "medido": {"esperado_m": float(size_xyz[1]), "pivo_regra": "base"}},
                {"id": "G9", "status": "ok", "medido": {"triangulos": 12, "limite": 500}},
            ],
        },
        "licenca": {"modelo": "CC0-1.0", "uso_comercial": True, "notice": "CC0-1.0 synthetic fixture"},
        "origem_spec": {"arquivo": "lote.yaml", "hash": sha_dummy},
        "run_id": "run-e2e-1", "created_at": "2026-11-19T00:00:00Z",
    }
    if manifest_overrides:
        manifest.update(dict(manifest_overrides))
    manifest_path = dest_dir / f"{asset_id}.manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return glb_path, manifest_path


@pytest.fixture
def publish_synthetic_asset():
    return write_published_asset


class MockHTTPController:
    """Localhost HTTP stub controller for deterministic external API boundary tests."""

    def __init__(self, server: http.server.ThreadingHTTPServer, routes: dict[tuple[str, str], tuple[int, Any]], requests_log: list[dict[str, Any]]) -> None:
        self._server = server
        self._routes = routes
        self.requests = requests_log
        host, port = server.server_address[:2]
        self.base_url = f"http://{host}:{port}"

    def add_route(self, method: str, path: str, body: Any, status: int = 200) -> None:
        self._routes[(method.upper(), path)] = (status, body)


@pytest.fixture
def mock_http_server() -> Iterator[MockHTTPController]:
    """Start a localhost-only ThreadingHTTPServer with clean teardown."""
    routes: dict[tuple[str, str], tuple[int, Any]] = {}
    requests_log: list[dict[str, Any]] = []

    class _Handler(http.server.BaseHTTPRequestHandler):
        def _handle(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            raw_body = self.rfile.read(length) if length > 0 else b""
            requests_log.append(
                {"method": self.command, "path": self.path, "headers": dict(self.headers.items()), "body": raw_body}
            )
            method = self.command.upper()
            route = routes.get((method, self.path)) or routes.get((method, self.path.split("?", 1)[0]))
            if route is None:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b'{"error":"not_found"}')
                return
            status, payload = route
            data = payload(raw_body, self.headers) if callable(payload) else payload
            if isinstance(data, (dict, list)):
                encoded, ctype = json.dumps(data).encode("utf-8"), "application/json"
            elif isinstance(data, bytes):
                encoded, ctype = data, "application/octet-stream"
            else:
                encoded, ctype = str(data).encode("utf-8"), "text/plain; charset=utf-8"
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self) -> None:
            self._handle()

        def do_POST(self) -> None:
            self._handle()

        def log_message(self, format: str, *args: Any) -> None:
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield MockHTTPController(server, routes, requests_log)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def run_godot_script(
    script_path: Path | str,
    script_args: Sequence[str] = (),
    *,
    check_only: bool = False,
    env: Mapping[str, str] | None = None,
    timeout: int = 60,
) -> subprocess.CompletedProcess[str]:
    """Run a GDScript inside `tools/godot_project` via `godot --headless`, skipping if absent."""
    godot_bin = find_godot()
    if not godot_bin:
        pytest.skip("Godot 4 binary unavailable in environment")
    script_abs = Path(script_path)
    if not script_abs.is_absolute():
        script_abs = (RAIZ / script_abs).resolve()
    cmd = [godot_bin, "--headless", "--path", str(RAIZ / "tools" / "godot_project")]
    if check_only:
        cmd.extend(["--check-only", "--quit", "--script", str(script_abs)])
    else:
        cmd.extend(["--script", str(script_abs), "--", *[str(a) for a in script_args]])
    return subprocess.run(
        cmd, cwd=str(RAIZ), env=dict(env) if env is not None else dict(os.environ), capture_output=True, text=True, timeout=timeout
    )
