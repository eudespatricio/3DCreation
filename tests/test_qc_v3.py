"""Testes V3 para `src/forge3d/qc.py`: G1/G5 anti-facetamento, G2 roll simetrico + criatura -Z + sockets e G10 loop/multi-osso."""

from __future__ import annotations

import json
import math
import struct
from pathlib import Path

import pytest

from forge3d import profiles, qc

GODOT = profiles.carregar("godot4")


def _empacotar_glb(gltf: dict, binario: bytes) -> bytes:
    js = json.dumps(gltf).encode("utf-8")
    while len(js) % 4:
        js += b" "
    while len(binario) % 4:
        binario += b"\x00"
    total = 12 + 8 + len(js) + 8 + len(binario)
    return (
        struct.pack("<III", 0x46546C67, 2, total)
        + struct.pack("<II", len(js), 0x4E4F534A)
        + js
        + struct.pack("<II", len(binario), 0x004E4942)
        + binario
    )


def _construir_esfera_glb(
    *,
    flat_shaded: bool,
    rings: int = 12,
    sectors: int = 16,
    altura_m: float = 1.80,
) -> tuple[dict, bytes]:
    """Constroi uma esfera UV fechada (>= 300 triangulos) com normais suaves ou flat por face."""
    r = altura_m / 2.0
    cy = r
    grid: list[tuple[float, float, float]] = []
    for i in range(rings + 1):
        theta = math.pi * i / rings
        sin_t = math.sin(theta)
        cos_t = math.cos(theta)
        for j in range(sectors):
            phi = 2.0 * math.pi * j / sectors
            x = r * sin_t * math.cos(phi)
            y = cy + r * cos_t
            z = r * sin_t * math.sin(phi)
            grid.append((x, y, z))

    tris_idx: list[tuple[int, int, int]] = []
    for i in range(rings):
        for j in range(sectors):
            nj = (j + 1) % sectors
            a = i * sectors + j
            b = (i + 1) * sectors + j
            c = (i + 1) * sectors + nj
            d = i * sectors + nj
            if i != 0:
                tris_idx.append((a, d, b))
            if i != rings - 1:
                tris_idx.append((b, d, c))

    pos_list: list[tuple[float, float, float]] = []
    norm_list: list[tuple[float, float, float]] = []
    uv_list: list[tuple[float, float]] = []
    idx_list: list[int] = []

    if flat_shaded:
        for ia, ib, ic in tris_idx:
            va, vb, vc = grid[ia], grid[ib], grid[ic]
            ux, uy, uz = vb[0] - va[0], vb[1] - va[1], vb[2] - va[2]
            vx, vy, vz = vc[0] - va[0], vc[1] - va[1], vc[2] - va[2]
            nx = uy * vz - uz * vy
            ny = uz * vx - ux * vz
            nz = ux * vy - uy * vx
            nl = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
            fn = (nx / nl, ny / nl, nz / nl)
            base = len(pos_list)
            pos_list.extend([va, vb, vc])
            norm_list.extend([fn, fn, fn])
            uv_list.extend([(0.1, 0.1), (0.9, 0.1), (0.5, 0.9)])
            idx_list.extend([base, base + 1, base + 2])
    else:
        for v in grid:
            dx, dy, dz = v[0], v[1] - cy, v[2]
            nl = math.sqrt(dx * dx + dy * dy + dz * dz) or 1.0
            pos_list.append(v)
            norm_list.append((dx / nl, dy / nl, dz / nl))
            u = 0.5 + math.atan2(dz, dx) / (2.0 * math.pi)
            v_uv = 0.5 - math.asin(max(-1.0, min(1.0, dy / nl))) / math.pi
            uv_list.append((max(0.01, min(0.99, u)), max(0.01, min(0.99, v_uv))))
        for ia, ib, ic in tris_idx:
            idx_list.extend([ia, ib, ic])

    p_bytes = b"".join(struct.pack("<3f", *p) for p in pos_list)
    n_bytes = b"".join(struct.pack("<3f", *n) for n in norm_list)
    u_bytes = b"".join(struct.pack("<2f", *u) for u in uv_list)
    i_bytes = b"".join(struct.pack("<I", idx) for idx in idx_list)

    chunks = [p_bytes, n_bytes, u_bytes, i_bytes]
    views = []
    offset = 0
    for ch in chunks:
        views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(ch)})
        offset += len(ch)
    binario = b"".join(chunks)

    xs = [p[0] for p in pos_list]
    ys = [p[1] for p in pos_list]
    zs = [p[2] for p in pos_list]

    gltf = {
        "asset": {"version": "2.0"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"name": "Body", "mesh": 0}],
        "materials": [
            {
                "name": "Mat",
                "pbrMetallicRoughness": {
                    "baseColorFactor": [0.8, 0.7, 0.6, 1.0],
                    "metallicFactor": 0.0,
                    "roughnessFactor": 0.65,
                },
            }
        ],
        "meshes": [
            {
                "name": "Body",
                "primitives": [
                    {
                        "attributes": {"POSITION": 0, "NORMAL": 1, "TEXCOORD_0": 2},
                        "indices": 3,
                        "material": 0,
                    }
                ],
            }
        ],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": len(pos_list),
                "type": "VEC3",
                "min": [min(xs), min(ys), min(zs)],
                "max": [max(xs), max(ys), max(zs)],
            },
            {"bufferView": 1, "componentType": 5126, "count": len(norm_list), "type": "VEC3"},
            {"bufferView": 2, "componentType": 5126, "count": len(uv_list), "type": "VEC2"},
            {"bufferView": 3, "componentType": 5125, "count": len(idx_list), "type": "SCALAR"},
        ],
        "bufferViews": views,
        "buffers": [{"byteLength": len(binario)}],
    }
    return gltf, binario


def test_g1_g5_reprova_malha_organica_facetada_e_isenta_blocky_e_props(tmp_path: Path) -> None:
    gltf_flat, bin_flat = _construir_esfera_glb(flat_shaded=True)
    gltf_smooth, bin_smooth = _construir_esfera_glb(flat_shaded=False)

    p_flat = tmp_path / "flat.glb"
    p_smooth = tmp_path / "smooth.glb"
    p_flat.write_bytes(_empacotar_glb(gltf_flat, bin_flat))
    p_smooth.write_bytes(_empacotar_glb(gltf_smooth, bin_smooth))

    item_org = {
        "id": "personagem.org.01",
        "tipo": "personagem_humanoide",
        "rota": "mesh",
        "altura_metros": 1.80,
        "pivot": "base",
        "limite_triangulos": 5000,
        "colisao": "none",
    }
    res_flat = {
        "arquivos": [{"caminho": "flat.glb", "papel": "mesh"}],
        "licenca": {"modelo": "Procedural", "uso_comercial": True},
    }
    rel_flat = qc.verificar(item_org, GODOT, tmp_path, res_flat)
    gates_flat = {g["id"]: g for g in rel_flat["gates"]}
    assert gates_flat["G1"]["status"] == "falhou"
    assert gates_flat["G1"]["medido"].get("malha_organica_facetada") is True
    assert "malha_organica_facetada" in gates_flat["G1"]["medido"].get("motivos", [])
    assert gates_flat["G5"]["status"] == "falhou"
    assert gates_flat["G5"]["medido"].get("malha_organica_facetada") is True

    # Malha suave passa em G1 e G5
    res_smooth = {
        "arquivos": [{"caminho": "smooth.glb", "papel": "mesh"}],
        "licenca": {"modelo": "Procedural", "uso_comercial": True},
    }
    rel_smooth = qc.verificar(item_org, GODOT, tmp_path, res_smooth)
    gates_smooth = {g["id"]: g for g in rel_smooth["gates"]}
    assert gates_smooth["G1"]["status"] == "ok"
    assert gates_smooth["G5"]["status"] == "ok"

    # Blocky / prop_estatico sao isentos do gate de facetamento organico
    item_blocky = {**item_org, "rota": "blocky", "estilo": "blocky_voxel"}
    rel_blocky = qc.verificar(item_blocky, GODOT, tmp_path, res_flat)
    gates_blocky = {g["id"]: g for g in rel_blocky["gates"]}
    assert gates_blocky["G1"]["status"] == "ok"

    item_prop = {**item_org, "tipo": "prop_estatico"}
    rel_prop = qc.verificar(item_prop, GODOT, tmp_path, res_flat)
    gates_prop = {g["id"]: g for g in rel_prop["gates"]}
    assert gates_prop["G1"]["status"] == "ok"


def test_g2_v3_roll_braco_direito_simetrico_e_criatura_frente_menos_z(tmp_path: Path) -> None:
    # 1. Testa roll invertido no braco DIREITO (x < -0.22, n_ref[0] < -0.5)
    glb_upright = Path("tests/fixtures/personagem_upright.glb")
    gltf_u, bin_u = qc.ler_glb_bin(glb_upright)
    info_u = qc.analisar(gltf_u, bin_u)
    item_h = {
        "id": "personagem.h.01",
        "tipo": "personagem_humanoide",
        "rota": "mesh",
        "altura_metros": 1.80,
        "pivot": "base",
        "auto_rig": True,
        "esqueleto": "godot-humanoid@1",
    }
    ok_u, det_u = qc._g2_orientacao(gltf_u, bin_u, item_h, GODOT, info_u)
    assert ok_u is True, det_u

    # Simula defeito de roll APENAS no braco direito (UpperArm.R)
    gltf_r_bad = {
        "nodes": [
            {"name": "Rig", "children": [1]},
            {"name": "Hips", "translation": [0.0, 1.0, 0.0], "children": [2, 3, 5]},
            {"name": "Head", "translation": [0.0, 1.7, 0.0]},
            {"name": "UpperArm.L", "translation": [0.25, 1.4, 0.0], "rotation": [0.0, 1.0, 0.0, 0.0], "children": [4]},
            {"name": "LowerArm.L", "translation": [0.25, 0.25, 0.0], "rotation": [0.0, 0.0, 0.0, 1.0]},
            {"name": "UpperArm.R", "translation": [-0.25, 1.4, 0.0], "rotation": [0.0, 0.0, 0.0, 1.0], "children": [6]},
            {"name": "LowerArm.R", "translation": [-0.25, 0.25, 0.0], "rotation": [0.0, 1.0, 0.0, 0.0]},
        ],
        "skins": [{"joints": [1, 2, 3, 4, 5, 6]}],
        "meshes": [],
    }
    info_r_bad = {
        "min": [-0.6, 0.0, -0.3],
        "max": [0.6, 1.8, 0.3],
        "bbox_m": [1.2, 1.8, 0.6],
        "ossos": 6,
        "nomes_ossos": ["Hips", "Head", "UpperArm.L", "LowerArm.L", "UpperArm.R", "LowerArm.R"],
    }
    ok_r_bad, det_r_bad = qc._g2_orientacao(gltf_r_bad, b"", item_h, GODOT, info_r_bad)
    assert ok_r_bad is False, det_r_bad
    assert "roll_osso_desalinhado" in det_r_bad["motivos"]
    assert det_r_bad.get("ossos_desalinhados") == ["UpperArm.R"]

    # 2. Testa criatura quadruped@1 invertida (+Z) vs correta (-Z) e validacao de sockets
    gltf_q = {
        "nodes": [
            {"name": "Rig", "children": [1]},
            {"name": "Hips", "translation": [0.0, 1.0, 0.4], "children": [2, 3]},
            {"name": "Head", "translation": [0.0, 1.3, 0.9]},  # Z > Hips.Z -> de costas (+Z)!
            {"name": "Tail1", "translation": [0.0, 1.0, -0.5]},
        ],
        "skins": [{"joints": [1, 2, 3]}],
        "meshes": [],
    }
    info_q = {
        "min": [-0.4, 0.0, -0.8],
        "max": [0.4, 1.4, 0.8],
        "bbox_m": [0.8, 1.4, 1.6],
        "ossos": 3,
        "nomes_ossos": ["Hips", "Head", "Tail1"],
    }
    item_q = {
        "id": "criatura.lobo.01",
        "tipo": "criatura_quadrupede",
        "rota": "mesh",
        "esqueleto": "quadruped@1",
    }
    ok_inv, det_inv = qc._g2_orientacao(gltf_q, b"", item_q, GODOT, info_q)
    assert ok_inv is False
    assert "criatura_de_costas" in det_inv["motivos"]
    assert "rig_de_costas" in det_inv["motivos"]

    # Corrige Head para -Z (frente) e Tail1 para +Z (tras)
    gltf_q["nodes"][1]["translation"] = [0.0, 1.0, 0.2]
    gltf_q["nodes"][2]["translation"] = [0.0, 1.3, -0.7]
    gltf_q["nodes"][3]["translation"] = [0.0, 1.0, 0.8]
    ok_ok, det_ok = qc._g2_orientacao(gltf_q, b"", item_q, GODOT, info_q)
    assert ok_ok is True, det_ok

    # Valida sockets invalidos (quaternion nulo ou osso inexistente)
    info_q_bad_sock = {
        **info_q,
        "_sockets": {
            "Socket_Mount": {
                "osso": "OssoFantasma",
                "posicao_m": [0.0, 0.2, 0.0],
                "rotacao_quat_wxyz": [0.0, 0.0, 0.0, 0.0],
            }
        },
    }
    ok_sock, det_sock = qc._g2_orientacao(gltf_q, b"", item_q, GODOT, info_q_bad_sock)
    assert ok_sock is False
    assert "socket_invalido" in det_sock["motivos"]


def test_g2_socket_pedido_ausente_no_esqueleto_final() -> None:
    # D-04: socket solicitado que o esqueleto final nao fornece vira falha de QC (nunca silencio)
    gltf_q = {
        "nodes": [
            {"name": "Rig", "children": [1]},
            {"name": "Hips", "translation": [0.0, 1.0, 0.2], "children": [2, 3]},
            {"name": "Head", "translation": [0.0, 1.3, -0.7]},
            {"name": "Tail1", "translation": [0.0, 1.0, 0.8]},
        ],
        "skins": [{"joints": [1, 2, 3]}],
        "meshes": [],
    }
    info_q = {
        "min": [-0.4, 0.0, -0.8],
        "max": [0.4, 1.4, 0.8],
        "bbox_m": [0.8, 1.4, 1.6],
        "ossos": 3,
        "nomes_ossos": ["Hips", "Head", "Tail1"],
    }
    item_base = {
        "id": "mob.quadrupede.01",
        "tipo": "criatura_quadrupede",
        "rota": "mesh",
        "esqueleto": "quadruped@1",
    }

    # Rig quadruped nao tem maos: pedir Hand.R/Hand.L seria descarte silencioso -> socket_ausente
    info_sem_sockets = {**info_q, "_sockets": []}
    item_maos = {**item_base, "sockets": ["Hand.R", "Hand.L"]}
    ok, det = qc._g2_orientacao(gltf_q, b"", item_maos, GODOT, info_sem_sockets)
    assert ok is False
    assert "socket_ausente" in det["motivos"]

    # Socket presente no esqueleto final nao marca socket_ausente
    info_com_socket = {
        **info_q,
        "_sockets": [
            {
                "nome": "Head",
                "osso": "Head",
                "posicao_local": [0.0, 0.0, 0.0],
                "rotacao_quat_wxyz": [1.0, 0.0, 0.0, 0.0],
                "frente_local": [0.0, 0.0, -1.0],
            }
        ],
    }
    item_head = {**item_base, "sockets": ["Head"]}
    ok_ok, det_ok = qc._g2_orientacao(gltf_q, b"", item_head, GODOT, info_com_socket)
    assert ok_ok is True, det_ok
    assert "socket_ausente" not in det_ok.get("motivos", [])


def test_g10_v2_continuidade_loop_e_movimento_multi_osso() -> None:
    tempos = b"".join(struct.pack("<f", t) for t in (0.0, 0.5, 1.0))
    # Clipe ciclico "walk" que NAO fecha o loop (termina em 90 graus de rotacao X)
    s45 = math.sin(math.pi / 4.0)
    c45 = math.cos(math.pi / 4.0)
    rots_aberto = b"".join(
        struct.pack("<4f", *q)
        for q in (
            (0.0, 0.0, 0.0, 1.0),
            (s45, 0.0, 0.0, c45),
            (s45, 0.0, 0.0, c45),
        )
    )
    rots_fechado = b"".join(
        struct.pack("<4f", *q)
        for q in (
            (0.0, 0.0, 0.0, 1.0),
            (s45, 0.0, 0.0, c45),
            (0.0, 0.0, 0.0, 1.0),
        )
    )
    dados = tempos + rots_aberto + rots_fechado
    views = [
        {"buffer": 0, "byteOffset": 0, "byteLength": len(tempos)},
        {"buffer": 0, "byteOffset": len(tempos), "byteLength": len(rots_aberto)},
        {"buffer": 0, "byteOffset": len(tempos) + len(rots_aberto), "byteLength": len(rots_fechado)},
    ]
    acessores = [
        {"bufferView": 0, "componentType": 5126, "count": 3, "type": "SCALAR", "min": [0.0], "max": [1.0]},
        {"bufferView": 1, "componentType": 5126, "count": 3, "type": "VEC4"},
        {"bufferView": 2, "componentType": 5126, "count": 3, "type": "VEC4"},
    ]
    gltf = {
        "nodes": [{"name": "Hips"}, {"name": "Spine"}],
        "skins": [{"joints": [0, 1]}],
        "accessors": acessores,
        "bufferViews": views,
        "animations": [
            {
                "name": "walk",
                "channels": [
                    {"sampler": 0, "target": {"node": 0, "path": "rotation"}},
                    {"sampler": 0, "target": {"node": 1, "path": "rotation"}},
                ],
                "samplers": [{"input": 0, "output": 1}],
            },
            {
                "name": "gallop",
                "channels": [
                    {"sampler": 0, "target": {"node": 0, "path": "rotation"}},
                    {"sampler": 0, "target": {"node": 1, "path": "rotation"}},
                ],
                "samplers": [{"input": 0, "output": 2}],
            },
        ],
    }
    clipes = {c["nome"]: c for c in qc.animacoes(gltf, dados)}
    assert clipes["walk"]["loop_fechado"] is False
    assert clipes["walk"]["loop_delta_rad"] > 0.35
    assert clipes["gallop"]["loop_fechado"] is True
    assert clipes["gallop"]["loop_delta_rad"] == pytest.approx(0.0, abs=1e-5)
