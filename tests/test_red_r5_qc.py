"""Suite TDD RED (F26-F27): blind spots QC G1-G11, verify G11 e governanca R5."""

from __future__ import annotations

import ast
import io
import json
import math
import re
import struct
from pathlib import Path

import pytest
from PIL import Image

import forge3d
from forge3d import canonical, config, post, profiles, publish, qc, verify

RAIZ = Path(__file__).resolve().parents[1]


def _png_bytes(w: int, h: int, rgb: tuple[int, int, int] = (128, 128, 128)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), rgb).save(buf, format="PNG")
    return buf.getvalue()


def _normal_hemisferio_png(tamanho: int = 128, *, opengl_y: bool = True) -> bytes:
    img = Image.new("RGB", (tamanho, tamanho), (128, 128, 255))
    px = img.load()
    assert px is not None
    c, r = (tamanho - 1) * 0.5, tamanho * 0.375
    sinal = -1.0 if opengl_y else 1.0
    for y in range(tamanho):
        dy = (y - c) / r
        for x in range(tamanho):
            dx = (x - c) / r
            d2 = dx * dx + dy * dy
            if d2 < 1.0:
                nz = math.sqrt(1.0 - d2)
                px[x, y] = (128 + round(127 * dx), 128 + round(127 * sinal * dy), 128 + round(127 * nz))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _caixa_uv(
    x0: float, x1: float, y0: float, y1: float, z0: float, z1: float,
    uv_box: tuple[float, float, float, float] = (0.05, 0.95, 0.05, 0.95),
) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]], list[tuple[float, float]]]:
    faces = [
        [(x0, y0, z0), (x0, y1, z0), (x1, y1, z0), (x1, y0, z0)], [(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)],
        [(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)], [(x0, y1, z0), (x0, y1, z1), (x1, y1, z1), (x1, y1, z0)],
        [(x0, y0, z0), (x0, y0, z1), (x0, y1, z1), (x0, y1, z0)], [(x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1)],
    ]
    u0, u1, v0, v1 = uv_box
    du, dv = (u1 - u0) / 3.0, (v1 - v0) / 2.0
    p = 0.05 * min(du, dv)
    verts, tris, uvs = [], [], []
    for k, q in enumerate(faces):
        b = len(verts)
        verts.extend(q)
        tris.extend([(b, b + 1, b + 2), (b, b + 2, b + 3)])
        cu, cv = u0 + (k % 3) * du, v0 + (k // 3) * dv
        uvs.extend([(cu + p, cv + p), (cu + du - p, cv + p), (cu + du - p, cv + dv - p), (cu + p, cv + dv - p)])
    return verts, tris, uvs


def _empacotar_glb(gltf: dict, binario: bytes) -> bytes:
    json_b = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    json_b += b" " * ((-len(json_b)) % 4)
    bin_b = binario + b"\x00" * ((-len(binario)) % 4)
    total = 12 + 8 + len(json_b) + 8 + len(bin_b)
    return struct.pack("<III", 0x46546C67, 2, total) + struct.pack("<II", len(json_b), 0x4E4F534A) + json_b + struct.pack("<II", len(bin_b), 0x004E4942) + bin_b


def _cubo_vt(hx: float = 0.25, y0: float = 0.0, y1: float = 1.0, hz: float = 0.25) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    verts = [(-hx, y0, -hz), (hx, y0, -hz), (hx, y1, -hz), (-hx, y1, -hz), (-hx, y0, hz), (hx, y0, hz), (hx, y1, hz), (-hx, y1, hz)]
    tris = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4), (2, 3, 7), (2, 7, 6), (0, 4, 7), (0, 7, 3), (1, 2, 6), (1, 6, 5)]
    return verts, tris


def _prisma_vt(lados: int = 250, raio: float = 0.25, altura: float = 1.0) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    verts: list[tuple[float, float, float]] = [(0.0, 0.0, 0.0), (0.0, altura, 0.0)]
    for i in range(lados):
        ang = (2.0 * math.pi * i) / lados
        x, z = raio * math.cos(ang), raio * math.sin(ang)
        verts.extend([(x, 0.0, z), (x, altura, z)])
    tris: list[tuple[int, int, int]] = []
    for i in range(lados):
        nxt = (i + 1) % lados
        b0, t0, b1, t1 = 2 + 2 * i, 3 + 2 * i, 2 + 2 * nxt, 3 + 2 * nxt
        tris.extend([(0, b0, b1), (1, t1, t0), (b0, t0, t1), (b0, t1, b1)])
    return verts, tris


def _construir_glb(
    verts: list[tuple[float, float, float]], tris: list[tuple[int, int, int]], *,
    uvs: list[tuple[float, float]] | None = None, com_uv: bool = True,
    materiais: list[dict] | None = None, png_bytes: bytes | None = None,
    ossos: list[str] | None = None, joints_v: list[tuple[int, int, int, int]] | None = None,
    weights_v: list[tuple[float, float, float, float]] | None = None, animacoes: list[dict] | None = None,
) -> bytes:
    buf, bvs, accs = bytearray(), [], []

    def add_bv(raw: bytes, target: int | None = None) -> int:
        buf.extend(b"\x00" * ((-len(buf)) % 4))
        off = len(buf)
        buf.extend(raw)
        bvs.append({"buffer": 0, "byteOffset": off, "byteLength": len(raw), **({"target": target} if target is not None else {})})
        return len(bvs) - 1

    def add_acc(bv: int, ctype: int, count: int, atype: str, **extra) -> int:
        accs.append({"bufferView": bv, "componentType": ctype, "count": count, "type": atype, **extra})
        return len(accs) - 1

    uv_gen: list[tuple[float, float]] | None = uvs
    if com_uv and uvs is None and tris:
        cols = max(1, math.ceil(math.sqrt(len(tris))))
        cw = 0.96 / cols
        pad = 0.1 * cw
        span = 0.8 * cw
        verts_u: list[tuple[float, float, float]] = []
        tris_u: list[tuple[int, int, int]] = []
        uvs_u: list[tuple[float, float]] = []
        jv_u: list[tuple[int, int, int, int]] | None = [] if joints_v is not None else None
        wv_u: list[tuple[float, float, float, float]] | None = [] if weights_v is not None else None
        for k, (i0, i1, i2) in enumerate(tris):
            base = len(verts_u)
            verts_u.extend((verts[i0], verts[i1], verts[i2]))
            tris_u.append((base, base + 1, base + 2))
            cu = 0.02 + (k % cols) * cw + pad
            cv = 0.02 + (k // cols) * cw + pad
            uvs_u.extend(((cu, cv), (cu + span, cv), (cu, cv + span)))
            if jv_u is not None and joints_v is not None:
                jv_u.extend((joints_v[i0], joints_v[i1], joints_v[i2]))
            if wv_u is not None and weights_v is not None:
                wv_u.extend((weights_v[i0], weights_v[i1], weights_v[i2]))
        verts, tris, uv_gen = verts_u, tris_u, uvs_u
        joints_v, weights_v = jv_u, wv_u

    xs, ys, zs = [v[0] for v in verts], [v[1] for v in verts], [v[2] for v in verts]
    a_pos = add_acc(add_bv(b"".join(struct.pack("<3f", *v) for v in verts), 34962), 5126, len(verts), "VEC3", min=[min(xs), min(ys), min(zs)], max=[max(xs), max(ys), max(zs)])
    a_norm = add_acc(add_bv(b"".join(struct.pack("<3f", 0.0, 0.0, 1.0) for _ in verts), 34962), 5126, len(verts), "VEC3")
    attrs: dict[str, int] = {"POSITION": a_pos, "NORMAL": a_norm}
    if com_uv:
        uv_list = uv_gen if uv_gen is not None else [((i % 2) * 0.8 + 0.1, ((i // 2) % 2) * 0.8 + 0.1) for i in range(len(verts))]
        attrs["TEXCOORD_0"] = add_acc(add_bv(b"".join(struct.pack("<2f", *uv) for uv in uv_list), 34962), 5126, len(verts), "VEC2")
    idx_acc = add_acc(add_bv(b"".join(struct.pack("<3H", *t) for t in tris), 34963), 5123, len(tris) * 3, "SCALAR")
    nodes: list[dict] = [{"name": "Asset", "mesh": 0}]
    skins: list[dict] = []
    joint_map: dict[str, int] = {}
    if ossos:
        jv = joints_v or [(0, 0, 0, 0)] * len(verts)
        wv = weights_v or [(1.0, 0.0, 0.0, 0.0)] * len(verts)
        attrs["JOINTS_0"] = add_acc(add_bv(b"".join(struct.pack("<4B", *j) for j in jv), 34962), 5121, len(verts), "VEC4")
        attrs["WEIGHTS_0"] = add_acc(add_bv(b"".join(struct.pack("<4f", *w) for w in wv), 34962), 5126, len(verts), "VEC4")
        j_indices: list[int] = []
        for nome in ossos:
            joint_map[nome] = len(nodes)
            j_indices.append(len(nodes))
            nodes.append({"name": nome})
        skins = [{"joints": j_indices}]
        nodes[0]["skin"] = 0

    gltf_anims: list[dict] = []
    for clipe in animacoes or []:
        tempos = clipe["tempos"]
        t_acc = add_acc(add_bv(b"".join(struct.pack("<f", t) for t in tempos)), 5126, len(tempos), "SCALAR", min=[min(tempos)], max=[max(tempos)])
        samplers, channels = [], []
        for osso_nome, quats in clipe["canais"].items():
            q_acc = add_acc(add_bv(b"".join(struct.pack("<4f", *q) for q in quats)), 5126, len(quats), "VEC4")
            samplers.append({"input": t_acc, "interpolation": "LINEAR", "output": q_acc})
            channels.append({"sampler": len(samplers) - 1, "target": {"node": joint_map[osso_nome], "path": "rotation"}})
        gltf_anims.append({"name": clipe["nome"], "samplers": samplers, "channels": channels})

    images, textures = [], []
    if png_bytes is not None:
        images = [{"bufferView": add_bv(png_bytes), "mimeType": "image/png"}]
        textures = [{"source": 0}]
        materiais = materiais or [{"name": "m0", "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}}]
    elif materiais is None:
        materiais = [{"name": "m0", "pbrMetallicRoughness": {"baseColorFactor": [0.8, 0.8, 0.8, 1.0]}}]

    gltf: dict = {
        "asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": list(range(len(nodes)))}],
        "nodes": nodes, "meshes": [{"primitives": [{"attributes": attrs, "indices": idx_acc, "material": 0}]}],
        "materials": materiais, "accessors": accs, "bufferViews": bvs, "buffers": [{"byteLength": len(buf)}],
    }
    if images:
        gltf["images"], gltf["textures"] = images, textures
    if skins:
        gltf["skins"] = skins
    if gltf_anims:
        gltf["animations"] = gltf_anims
    return _empacotar_glb(gltf, bytes(buf))


def _item(**extra) -> dict:
    return {"id": "asset.red.01", "tipo": "prop_estatico", "altura_metros": 1.0, "pivot": "base", "limite_triangulos": 5000, "colisao": "none", **extra}


def _res(nome_glb: str, tris: int, extras: list[dict] | None = None) -> dict:
    arqs = [{"caminho": nome_glb, "papel": "mesh", "nivel": 0, "triangulos": tris}, *(extras or [])]
    return {"medidas": {"nao_manifold": 0, "degeneradas": 0, "partes_colisao": 0}, "arquivos": arqs, "licenca": {"modelo": "MIT", "uso_comercial": True, "notice": "teste"}, "determinism": "D1"}


def _gate(rel: dict, gid: str) -> dict:
    return next(g for g in rel["gates"] if g["id"] == gid)


def _quat_y(deg: float) -> tuple[float, float, float, float]:
    rad = math.radians(deg) * 0.5
    return (0.0, math.sin(rad), 0.0, math.cos(rad))


def test_f26_g1_winding_inconsistente_em_malha_aberta_reprova(tmp_path: Path) -> None:
    verts, tris = _cubo_vt()
    tris_aberta = tris[:2] + [(4, 6, 5), (4, 7, 6)] + tris[4:6] + tris[8:]
    (tmp_path / "open_bad.glb").write_bytes(_construir_glb(verts, tris_aberta, png_bytes=_png_bytes(256, 256)))
    gltf, binario = qc.ler_glb_bin(tmp_path / "open_bad.glb")

    topo = qc.topologia(gltf, binario)
    assert topo["bordas_abertas"] == 4
    assert topo["invertidas"] > 0

    rel = qc.verificar(_item(alpha_cards=True), profiles.carregar("godot4"), tmp_path, _res("open_bad.glb", 10))
    assert _gate(rel, "G1")["status"] == "falhou"
    assert rel["aprovado"] is False


def test_f26_g2_skinned_humanoid_de_costas_reprova(tmp_path: Path) -> None:
    perfil = profiles.carregar("godot4")
    ossos = list(perfil["rig"]["mapas"]["godot-humanoid@1"])
    caixas = [
        _caixa_uv(-0.20, 0.20, 0.0, 0.08, -0.30, 0.05, (0.05, 0.32, 0.05, 0.95)),
        _caixa_uv(-0.20, 0.20, 0.20, 1.45, -0.10, 0.30, (0.36, 0.63, 0.05, 0.95)),
        _caixa_uv(-0.15, 0.15, 1.50, 1.80, -0.22, 0.06, (0.67, 0.95, 0.05, 0.95)),
    ]
    verts_fwd, tris, uvs = [], [], []
    for cv, ct, cu in caixas:
        off = len(verts_fwd)
        verts_fwd.extend(cv)
        tris.extend([(a + off, b + off, c + off) for a, b, c in ct])
        uvs.extend(cu)
    verts_back = [(-x, y, -z) for x, y, z in verts_fwd]
    jv = [(1 + (i % 10), 0, 0, 0) for i in range(len(verts_fwd))]
    item = _item(tipo="personagem_humanoide", altura_metros=1.8, auto_rig=True, esqueleto="godot-humanoid@1")

    (tmp_path / "fwd_rig.glb").write_bytes(_construir_glb(verts_fwd, tris, uvs=uvs, png_bytes=_png_bytes(256, 256), ossos=ossos, joints_v=jv))
    rel_fwd = qc.verificar(item, perfil, tmp_path, _res("fwd_rig.glb", len(tris)))
    assert _gate(rel_fwd, "G1")["status"] == "ok"
    assert _gate(rel_fwd, "G2")["status"] == "ok"
    assert _gate(rel_fwd, "G2")["medido"]["desvio_xz_m"] <= 0.001
    assert rel_fwd["aprovado"] is True

    (tmp_path / "back_rig.glb").write_bytes(_construir_glb(verts_back, tris, uvs=uvs, png_bytes=_png_bytes(256, 256), ossos=ossos, joints_v=jv))
    gltf, binario = qc.ler_glb_bin(tmp_path / "back_rig.glb")
    ok_orient, det = qc._g2_orientacao(gltf, binario, item, perfil, qc.analisar(gltf, binario))
    assert ok_orient is False
    assert "malha_de_costas" in det["motivos"]
    rel = qc.verificar(item, perfil, tmp_path, _res("back_rig.glb", len(tris)))
    assert _gate(rel, "G1")["status"] == "ok"
    assert _gate(rel, "G2")["medido"]["desvio_xz_m"] <= 0.001
    assert _gate(rel, "G2")["status"] == "falhou"
    assert rel["aprovado"] is False


def test_f26_g3_uv_sobreposta_reprova(tmp_path: Path) -> None:
    verts = [
        (-0.25, 0.0, -0.1), (0.25, 0.0, -0.1), (0.25, 1.0, -0.1), (-0.25, 1.0, -0.1),
        (-0.25, 0.0, 0.1), (0.25, 0.0, 0.1), (0.25, 1.0, 0.1), (-0.25, 1.0, 0.1),
    ]
    tris = [(0, 1, 2), (0, 2, 3), (4, 5, 6), (4, 6, 7)]
    uvs_ok = [(0.05, 0.1), (0.45, 0.1), (0.45, 0.9), (0.05, 0.9), (0.55, 0.1), (0.95, 0.1), (0.95, 0.9), (0.55, 0.9)]
    uvs_overlap = [(0.1, 0.1), (0.9, 0.1), (0.9, 0.9), (0.1, 0.9)] * 2
    perfil, item = profiles.carregar("godot4"), _item(alpha_cards=True)

    (tmp_path / "uv_ok.glb").write_bytes(_construir_glb(verts, tris, uvs=uvs_ok, png_bytes=_png_bytes(256, 256)))
    rel_ok = qc.verificar(item, perfil, tmp_path, _res("uv_ok.glb", 4))
    for gid in ("G1", "G2", "G3", "G4", "G5"):
        assert _gate(rel_ok, gid)["status"] == "ok"

    (tmp_path / "uv_ov.glb").write_bytes(_construir_glb(verts, tris, uvs=uvs_overlap, png_bytes=_png_bytes(256, 256)))
    rel = qc.verificar(item, perfil, tmp_path, _res("uv_ov.glb", 4))
    assert _gate(rel, "G1")["status"] == "ok"
    assert _gate(rel, "G2")["status"] == "ok"
    assert _gate(rel, "G3")["status"] == "falhou"
    assert rel["aprovado"] is False


def test_f26_g3_uv_triangulo_colapsado_e_densidade_extrema_reprova(tmp_path: Path) -> None:
    verts = [(-0.25, 0.0, -0.1), (0.25, 0.0, -0.1), (0.25, 1.0, -0.1), (-0.25, 0.0, 0.1), (0.25, 0.0, 0.1), (0.25, 1.0, 0.1)]
    tris = [(0, 1, 2), (3, 4, 5)]
    uvs_ok = [(0.05, 0.1), (0.45, 0.1), (0.45, 0.9), (0.55, 0.1), (0.95, 0.1), (0.95, 0.9)]
    uvs_bad = [(0.1, 0.1), (0.9, 0.1), (0.9, 0.9), (0.5, 0.5), (0.5, 0.5), (0.5, 0.5)]
    perfil, item = profiles.carregar("godot4"), _item(alpha_cards=True)

    (tmp_path / "uv_col_ok.glb").write_bytes(_construir_glb(verts, tris, uvs=uvs_ok, png_bytes=_png_bytes(256, 256)))
    rel_ok = qc.verificar(item, perfil, tmp_path, _res("uv_col_ok.glb", 2))
    assert _gate(rel_ok, "G1")["status"] == "ok"
    assert _gate(rel_ok, "G2")["status"] == "ok"
    assert _gate(rel_ok, "G3")["status"] == "ok"
    assert rel_ok["aprovado"] is True

    (tmp_path / "uv_col.glb").write_bytes(_construir_glb(verts, tris, uvs=uvs_bad, png_bytes=_png_bytes(256, 256)))
    rel = qc.verificar(item, perfil, tmp_path, _res("uv_col.glb", 2))
    assert _gate(rel, "G1")["status"] == "ok"
    assert _gate(rel, "G2")["status"] == "ok"
    assert _gate(rel, "G3")["status"] == "falhou"
    assert rel["aprovado"] is False


def test_f26_g4_resolucao_minima_4x4_pot_reprova(tmp_path: Path) -> None:
    verts, tris = _cubo_vt()
    (tmp_path / "tiny.glb").write_bytes(_construir_glb(verts, tris, png_bytes=_png_bytes(4, 4)))
    rel = qc.verificar(_item(), profiles.carregar("godot4"), tmp_path, _res("tiny.glb", len(tris)))
    assert _gate(rel, "G4")["status"] == "falhou"
    assert rel["aprovado"] is False


def test_f26_g4_normal_directx_menos_y_reprova_vs_opengl_mais_y(tmp_path: Path) -> None:
    verts, tris = _cubo_vt()
    perfil = profiles.carregar("godot4")
    (tmp_path / "mesh.glb").write_bytes(_construir_glb(verts, tris, png_bytes=_png_bytes(256, 256)))
    gl_bytes, dx_bytes = _normal_hemisferio_png(128, opengl_y=True), _normal_hemisferio_png(128, opengl_y=False)
    (tmp_path / "n_gl.png").write_bytes(gl_bytes)
    (tmp_path / "n_dx.png").write_bytes(dx_bytes)
    for nome in ("n_gl.png", "n_dx.png"):
        with Image.open(tmp_path / nome) as im:
            g_vals = list(im.getchannel(1).getdata())
            assert abs((sum(g_vals) / len(g_vals)) - 128.0) < 0.5

    rel_gl = qc.verificar(_item(), perfil, tmp_path, _res("mesh.glb", len(tris), [{"caminho": "n_gl.png", "papel": "normal"}]))
    rel_dx = qc.verificar(_item(), perfil, tmp_path, _res("mesh.glb", len(tris), [{"caminho": "n_dx.png", "papel": "normal"}]))
    assert _gate(rel_gl, "G4")["status"] == "ok"
    assert rel_gl["aprovado"] is True
    assert _gate(rel_dx, "G4")["status"] == "falhou"
    assert rel_dx["aprovado"] is False


def test_f26_g5_clay_sem_textura_em_material_pbr_reprova(tmp_path: Path) -> None:
    verts, tris = _cubo_vt()
    mat = [{"name": "clay", "pbrMetallicRoughness": {"baseColorFactor": [0.8, 0.8, 0.8, 1.0]}}]
    (tmp_path / "clay.glb").write_bytes(_construir_glb(verts, tris, materiais=mat))
    rel = qc.verificar(_item(material="pbr"), profiles.carregar("godot4"), tmp_path, _res("clay.glb", len(tris)))
    assert _gate(rel, "G5")["status"] == "falhou"
    assert rel["aprovado"] is False


def test_f26_g6_peso_100_por_cento_raiz_reprova(tmp_path: Path) -> None:
    verts, tris = _cubo_vt(y1=1.8)
    perfil = profiles.carregar("godot4")
    ossos = list(perfil["rig"]["mapas"]["godot-humanoid@1"])
    (tmp_path / "root_only.glb").write_bytes(_construir_glb(verts, tris, png_bytes=_png_bytes(256, 256), ossos=ossos))
    gltf, binario = qc.ler_glb_bin(tmp_path / "root_only.glb")

    assert qc._skin_status(gltf, binario)["ok"] is False
    item = _item(tipo="personagem_humanoide", altura_metros=1.8, auto_rig=True, esqueleto="godot-humanoid@1")
    rel = qc.verificar(item, perfil, tmp_path, _res("root_only.glb", len(tris)))
    assert _gate(rel, "G6")["status"] == "falhou"
    assert rel["aprovado"] is False


def test_f26_g9_lod_solicitado_ausente_reprova(tmp_path: Path) -> None:
    perfil = profiles.carregar("godot4")
    ossos = list(perfil["rig"]["mapas"]["godot-humanoid@1"])
    verts0, tris0 = _prisma_vt(lados=16, altura=1.8)
    glb0 = _construir_glb(
        verts0, tris0, png_bytes=_png_bytes(256, 256), ossos=ossos,
        joints_v=[(1 + (i % 10), 0, 0, 0) for i in range(len(verts0))],
    )
    (tmp_path / "hero.glb").write_bytes(glb0)
    item = _item(tipo="personagem_humanoide", altura_metros=1.8, auto_rig=True, esqueleto="godot-humanoid@1", lod=[100, 50, 25])
    rel = qc.verificar(item, perfil, tmp_path, _res("hero.glb", len(tris0)))
    assert _gate(rel, "G9")["status"] == "falhou"
    assert rel["aprovado"] is False


def test_f26_g9_lod1_sem_uv_ou_skin_quando_lod0_possui_reprova(tmp_path: Path) -> None:
    perfil = profiles.carregar("godot4")
    ossos = list(perfil["rig"]["mapas"]["godot-humanoid@1"])
    verts0, tris0 = _prisma_vt(lados=16, altura=1.8)
    verts1, tris1 = _prisma_vt(lados=8, altura=1.8)
    (tmp_path / "hero.glb").write_bytes(
        _construir_glb(
            verts0, tris0, png_bytes=_png_bytes(256, 256), ossos=ossos,
            joints_v=[(1 + (i % 10), 0, 0, 0) for i in range(len(verts0))],
        )
    )
    (tmp_path / "hero_LOD1.glb").write_bytes(_construir_glb(verts1, tris1, com_uv=False, png_bytes=_png_bytes(256, 256)))
    item = _item(tipo="personagem_humanoide", altura_metros=1.8, auto_rig=True, esqueleto="godot-humanoid@1", lod=[100, 50])
    rel = qc.verificar(
        item, perfil, tmp_path,
        _res("hero.glb", len(tris0), [{"caminho": "hero_LOD1.glb", "papel": "lod", "nivel": 1, "triangulos": len(tris1)}]),
    )
    assert _gate(rel, "G9")["status"] == "falhou"
    assert rel["aprovado"] is False


def test_f26_g10_amplitude_menor_que_5_graus_reprova(tmp_path: Path) -> None:
    verts, tris = _cubo_vt(y1=1.8)
    perfil = profiles.carregar("godot4")
    ossos = list(perfil["rig"]["mapas"]["godot-humanoid@1"])
    glb = _construir_glb(
        verts, tris, png_bytes=_png_bytes(256, 256), ossos=ossos,
        joints_v=[(1 + (i % 10), 0, 0, 0) for i in range(len(verts))],
        animacoes=[{
            "nome": "idle", "tempos": [0.0, 0.5, 1.0],
            "canais": {"Hips": [_quat_y(0), _quat_y(1), _quat_y(0)], "Spine": [_quat_y(0), _quat_y(1), _quat_y(0)]},
        }],
    )
    (tmp_path / "jit.glb").write_bytes(glb)
    item = _item(tipo="personagem_humanoide", altura_metros=1.8, auto_rig=True, esqueleto="godot-humanoid@1", animacoes_base=["idle"])
    rel = qc.verificar(item, perfil, tmp_path, _res("jit.glb", len(tris)))
    assert _gate(rel, "G10")["status"] == "falhou"
    assert rel["aprovado"] is False


def test_f26_g10_loop_ciclico_maior_que_3_graus_reprova(tmp_path: Path) -> None:
    verts, tris = _cubo_vt(y1=1.8)
    perfil = profiles.carregar("godot4")
    ossos = list(perfil["rig"]["mapas"]["godot-humanoid@1"])
    glb = _construir_glb(
        verts, tris, png_bytes=_png_bytes(256, 256), ossos=ossos,
        joints_v=[(1 + (i % 10), 0, 0, 0) for i in range(len(verts))],
        animacoes=[{
            "nome": "idle", "tempos": [0.0, 0.5, 1.0],
            "canais": {"Hips": [_quat_y(0), _quat_y(30), _quat_y(10)], "Spine": [_quat_y(0), _quat_y(25), _quat_y(0)]},
        }],
    )
    (tmp_path / "jump.glb").write_bytes(glb)
    gltf, binario = qc.ler_glb_bin(tmp_path / "jump.glb")
    assert qc.animacoes(gltf, binario)[0]["loop_fechado"] is False
    item = _item(tipo="personagem_humanoide", altura_metros=1.8, auto_rig=True, esqueleto="godot-humanoid@1", animacoes_base=["idle"])
    rel = qc.verificar(item, perfil, tmp_path, _res("jump.glb", len(tris)))
    assert _gate(rel, "G10")["status"] == "falhou"


def test_f26_verify_reprova_quando_excede_orcamento_cena_g11(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FORGE3D_HOME", str(tmp_path / "_home"))
    monkeypatch.setenv("FORGE3D_CONFIG", str(tmp_path / "_cfg"))
    dest = tmp_path / "pub"
    dest.mkdir()
    config.adicionar(dest)

    verts, tris = _prisma_vt(lados=250, altura=1.0)
    glb_path = dest / "prop.heavy.01.glb"
    glb_path.write_bytes(_construir_glb(verts, tris, png_bytes=_png_bytes(256, 256)))

    perfil = profiles.carregar("godot4")
    item = _item(id="prop.heavy.01", rota="blocky", limite_triangulos=1500, quantidade_cena=500)
    res = _res(glb_path.name, len(tris))
    res["arquivos"][0].update(sha256=canonical.sha256_arquivo(glb_path), bytes=glb_path.stat().st_size)
    rel_qc = qc.verificar(item, perfil, dest, res, escala_saida=1.0)
    assert rel_qc["aprovado"] is True

    man = publish.montar_manifesto(
        item=item, spec_doc={"projeto": "demo", "perfil": "godot4", "_arquivo": "lote.yaml"},
        spec_hash="sha256:" + "0" * 64, perfil_nome="godot4", perfil=perfil,
        provider={"nome": "blocky", "versao": "0.9.4", "determinism": "D1"},
        resultado=res, relatorio_qc=rel_qc, licenca={"modelo": "MIT", "uso_comercial": True, "notice": "teste"},
        run_id="run-g11",
    )
    (dest / "prop.heavy.01.manifest.json").write_text(json.dumps(man), encoding="utf-8")
    assert verify.verificar(dest)["ok"] is False


def test_f27_ast_zero_except_silencioso_em_src_e_blender() -> None:
    silenciosos: list[str] = []
    for base in ("src/forge3d", "blender"):
        for arq in sorted((RAIZ / base).rglob("*.py")):
            arvore = ast.parse(arq.read_text(encoding="utf-8"), filename=str(arq))
            for no in ast.walk(arvore):
                if not isinstance(no, ast.ExceptHandler):
                    continue
                amplo = no.type is None or (isinstance(no.type, ast.Name) and no.type.id in ("Exception", "BaseException"))
                if not amplo or len(no.body) != 1:
                    continue
                stmt = no.body[0]
                eh_sil = isinstance(stmt, (ast.Pass, ast.Continue)) or (
                    isinstance(stmt, ast.Return)
                    and (stmt.value is None or (isinstance(stmt.value, ast.Constant) and stmt.value.value in (None, False)))
                )
                if eh_sil:
                    silenciosos.append(f"{arq.relative_to(RAIZ)}:{no.lineno}")
    assert silenciosos == [], f"except silencioso encontrado: {silenciosos}"


def test_f27_modulos_core_r2_r5_ate_500_linhas() -> None:
    alvos = [
        "src/forge3d/qc.py", "src/forge3d/rbx.py", "src/forge3d/spec.py", "src/forge3d/sync.py",
        "src/forge3d/pipeline.py", "src/forge3d/plan.py", "src/forge3d/upload.py",
        "src/forge3d/providers/mesh.py", "src/forge3d/providers/cloud_ai.py", "src/forge3d/providers/concept.py",
        "blender/template_body.py", "blender/autorig.py", "blender/postprocess.py", "blender/bake_pbr.py",
        "blender/smart_fit.py", "blender/procedural_pbr.py", "addons/forge3d/post_import.gd",
        "tools/visual_qa_critic.py", "tools/delight.py",
    ]
    acima = {
        rel: len((RAIZ / rel).read_text(encoding="utf-8").splitlines())
        for rel in alvos
        if (RAIZ / rel).is_file() and len((RAIZ / rel).read_text(encoding="utf-8").splitlines()) > 500
    }
    assert acima == {}, f"modulos acima de 500 linhas: {acima}"


def test_f27_pipeline_version_acima_de_0_9_4() -> None:
    pyproject = (RAIZ / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.MULTILINE)
    assert m is not None
    v_py = m.group(1)
    assert v_py == forge3d.__version__ == forge3d.PIPELINE_VERSION == post.PIPELINE_VERSION
    assert tuple(int(p) for p in v_py.split(".")[:3]) > (0, 9, 4)
