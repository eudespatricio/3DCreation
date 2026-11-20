"""Regression tests for malformed glTF/GLB attributes, bufferView, OverflowError, and textures."""

from __future__ import annotations

import io
import math
import struct
from pathlib import Path

import pytest
from PIL import Image

from forge3d import profiles, qc, qc_glb_mat, qc_midia
from tests.test_qc_v3 import _empacotar_glb
from tests.test_seguranca_e_qc import _editar_gltf_glb


def _pad4(buf: bytearray) -> None:
    while len(buf) % 4:
        buf.append(0)


def _add_bv_acc(
    gltf: dict,
    buf: bytearray,
    payload: bytes,
    comp: int,
    count: int,
    tipo: str,
    **extra: object,
) -> int:
    _pad4(buf)
    off = len(buf)
    buf.extend(payload)
    bv_idx = len(gltf["bufferViews"])
    gltf["bufferViews"].append({"buffer": 0, "byteOffset": off, "byteLength": len(payload)})
    acc: dict[str, object] = {
        "bufferView": bv_idx,
        "componentType": comp,
        "count": count,
        "type": tipo,
        **extra,
    }
    gltf["accessors"].append(acc)
    return len(gltf["accessors"]) - 1


def _esfera_uv_disjunta(rings: int = 10, sectors: int = 14, altura_m: float = 1.0) -> tuple[list, list, list, list]:
    r = altura_m / 2.0
    cy = r
    verts, norms, uvs, tris = [], [], [], []
    cols = sectors + 1
    for i in range(rings + 1):
        theta = math.pi * i / rings
        st, ct = math.sin(theta), math.cos(theta)
        v_uv = 0.05 + 0.90 * (i / rings)
        for j in range(cols):
            phi = 2.0 * math.pi * (j % sectors) / sectors
            dx, dy, dz = st * math.cos(phi), ct, st * math.sin(phi)
            verts.append((r * dx, cy + r * dy, r * dz))
            norms.append((dx, dy, dz))
            uvs.append((0.05 + 0.90 * (j / sectors), v_uv))
    for i in range(rings):
        for j in range(sectors):
            a, b = i * cols + j, (i + 1) * cols + j
            c, d = (i + 1) * cols + (j + 1), i * cols + (j + 1)
            if i != 0:
                tris.append((a, d, b))
            if i != rings - 1:
                tris.append((b, d, c))
    return verts, norms, uvs, tris


def _build_full_glb(
    *,
    perfil_nome: str,
    esqueleto: str | None = None,
    organico_denso: bool = False,
    com_anim: bool = False,
) -> bytes:
    perfil = profiles.carregar(perfil_nome)
    escala = float(perfil["unidades"]["escala_saida"])
    if organico_denso:
        verts, norms, uvs, tris = _esfera_uv_disjunta(rings=10, sectors=14, altura_m=escala)
    else:
        s = escala
        faces = [
            ([(-0.25 * s, 0.0, -0.25 * s), (-0.25 * s, s, -0.25 * s), (0.25 * s, s, -0.25 * s), (0.25 * s, 0.0, -0.25 * s)], (0.0, 0.0, -1.0)),
            ([(-0.25 * s, 0.0, 0.25 * s), (0.25 * s, 0.0, 0.25 * s), (0.25 * s, s, 0.25 * s), (-0.25 * s, s, 0.25 * s)], (0.0, 0.0, 1.0)),
            ([(-0.25 * s, 0.0, -0.25 * s), (0.25 * s, 0.0, -0.25 * s), (0.25 * s, 0.0, 0.25 * s), (-0.25 * s, 0.0, 0.25 * s)], (0.0, -1.0, 0.0)),
            ([(-0.25 * s, s, -0.25 * s), (-0.25 * s, s, 0.25 * s), (0.25 * s, s, 0.25 * s), (0.25 * s, s, -0.25 * s)], (0.0, 1.0, 0.0)),
            ([(-0.25 * s, 0.0, -0.25 * s), (-0.25 * s, 0.0, 0.25 * s), (-0.25 * s, s, 0.25 * s), (-0.25 * s, s, -0.25 * s)], (-1.0, 0.0, 0.0)),
            ([(0.25 * s, 0.0, -0.25 * s), (0.25 * s, s, -0.25 * s), (0.25 * s, s, 0.25 * s), (0.25 * s, 0.0, 0.25 * s)], (1.0, 0.0, 0.0)),
        ]
        verts, norms, uvs, tris = [], [], [], []
        du, dv, pad = 0.9 / 3.0, 0.9 / 2.0, 0.02
        for k, (q, n_face) in enumerate(faces):
            b = len(verts)
            verts.extend(q)
            norms.extend([n_face] * 4)
            tris.extend([(b, b + 1, b + 2), (b, b + 2, b + 3)])
            cu, cv = 0.05 + (k % 3) * du, 0.05 + (k // 3) * dv
            uvs.extend([(cu + pad, cv + pad), (cu + du - pad, cv + pad), (cu + du - pad, cv + dv - pad), (cu + pad, cv + dv - pad)])

    buf = bytearray()
    gltf: dict = {
        "asset": {"version": "2.0"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"name": "Mesh", "mesh": 0}],
        "materials": [{"name": "M", "pbrMetallicRoughness": {"baseColorFactor": [1, 1, 1, 1]}}],
        "meshes": [{"name": "Mesh", "primitives": [{"attributes": {}, "material": 0}]}],
        "accessors": [],
        "bufferViews": [],
        "buffers": [{"byteLength": 0}],
    }
    xs, ys, zs = [v[0] for v in verts], [v[1] for v in verts], [v[2] for v in verts]
    attrs = gltf["meshes"][0]["primitives"][0]["attributes"]
    attrs["POSITION"] = _add_bv_acc(
        gltf, buf, b"".join(struct.pack("<3f", *p) for p in verts),
        5126, len(verts), "VEC3", min=[min(xs), min(ys), min(zs)], max=[max(xs), max(ys), max(zs)],
    )
    attrs["NORMAL"] = _add_bv_acc(
        gltf, buf, b"".join(struct.pack("<3f", *n) for n in norms), 5126, len(verts), "VEC3"
    )
    attrs["TEXCOORD_0"] = _add_bv_acc(
        gltf, buf, b"".join(struct.pack("<2f", *u) for u in uvs), 5126, len(verts), "VEC2"
    )
    gltf["meshes"][0]["primitives"][0]["indices"] = _add_bv_acc(
        gltf, buf, b"".join(struct.pack("<3H", *t) for t in tris), 5123, len(tris) * 3, "SCALAR"
    )

    prim = gltf["meshes"][0]["primitives"][0]
    attrs = prim["attributes"]
    n_verts = gltf["accessors"][attrs["POSITION"]]["count"]

    attrs["TANGENT"] = _add_bv_acc(
        gltf, buf, b"".join(struct.pack("<4f", 1.0, 0.0, 0.0, 1.0) for _ in range(n_verts)),
        5126, n_verts, "VEC4",
    )
    uv1_pts = [(0.1 + 0.8 * (i % 2), 0.1 + 0.8 * ((i // 2) % 2)) for i in range(n_verts)]
    attrs["TEXCOORD_1"] = _add_bv_acc(
        gltf, buf, b"".join(struct.pack("<2f", *u) for u in uv1_pts),
        5126, n_verts, "VEC2",
    )
    attrs["COLOR_0"] = _add_bv_acc(
        gltf, buf, b"".join(struct.pack("<4f", 1.0, 1.0, 1.0, 1.0) for _ in range(n_verts)),
        5126, n_verts, "VEC4",
    )
    n_nao_raiz = max(1, len(perfil["rig"]["mapas"][esqueleto]) - 1) if esqueleto else 1
    attrs["JOINTS_0"] = _add_bv_acc(
        gltf,
        buf,
        b"".join(
            struct.pack("<4B", (1 + (i % n_nao_raiz)) if esqueleto else 0, 0, 0, 0)
            for i in range(n_verts)
        ),
        5121,
        n_verts,
        "VEC4",
    )
    attrs["WEIGHTS_0"] = _add_bv_acc(
        gltf, buf, b"".join(struct.pack("<4f", 1.0, 0.0, 0.0, 0.0) for _ in range(n_verts)),
        5126, n_verts, "VEC4",
    )

    _pad4(buf)
    img_buf = io.BytesIO()
    Image.new("RGB", (32, 32), (128, 128, 255)).save(img_buf, format="PNG")
    img_bytes = img_buf.getvalue()
    img_off = len(buf)
    buf.extend(img_bytes)
    img_bv = len(gltf["bufferViews"])
    gltf["bufferViews"].append({"buffer": 0, "byteOffset": img_off, "byteLength": len(img_bytes)})
    gltf["images"] = [{"bufferView": img_bv, "mimeType": "image/png"}]
    gltf["textures"] = [{"source": 0}]
    gltf["materials"][0]["pbrMetallicRoughness"]["baseColorTexture"] = {"index": 0}
    gltf["materials"][0]["normalTexture"] = {"index": 0}

    if esqueleto is not None:
        mapa = perfil["rig"]["mapas"][esqueleto]
        joints = []
        for nome_osso in mapa:
            joints.append(len(gltf["nodes"]))
            gltf["nodes"].append({"name": nome_osso})
        gltf["skins"] = [{"joints": joints}]
        gltf["nodes"][0]["skin"] = 0
        gltf["scenes"][0]["nodes"] = list(range(len(gltf["nodes"])))

        if com_anim:
            t_acc = _add_bv_acc(
                gltf, buf, struct.pack("<3f", 0.0, 0.5, 1.0), 5126, 3, "SCALAR", min=[0.0], max=[1.0]
            )
            ang = math.radians(20.0) * 0.5
            q0 = (0.0, 0.0, 0.0, 1.0)
            q1 = (0.0, math.sin(ang), 0.0, math.cos(ang))
            q_acc = _add_bv_acc(
                gltf, buf, struct.pack("<12f", *q0, *q1, *q0), 5126, 3, "VEC4"
            )
            gltf["animations"] = [
                {
                    "name": clipe,
                    "samplers": [{"input": t_acc, "interpolation": "LINEAR", "output": q_acc}],
                    "channels": [
                        {"sampler": 0, "target": {"node": joints[0], "path": "rotation"}},
                        {"sampler": 0, "target": {"node": joints[1], "path": "rotation"}},
                    ],
                }
                for clipe in ("idle", "walk")
            ]

    _pad4(buf)
    gltf["buffers"][0]["byteLength"] = len(buf)
    return _empacotar_glb(gltf, bytes(buf))


def _item_para(tipo: str, auto_rig: bool, esqueleto: str | None) -> dict:
    item: dict = {
        "id": f"test.{tipo}",
        "tipo": tipo,
        "altura_metros": 1.0,
        "pivot": "base",
        "limite_triangulos": 5000,
        "colisao": "none",
    }
    if auto_rig:
        item["auto_rig"] = True
        item["esqueleto"] = esqueleto
    return item


@pytest.mark.parametrize(
    ("perfil_nome", "tipo", "auto_rig", "esqueleto", "organico_denso"),
    [
        ("roblox-aa-80", "prop_estatico", False, None, False),
        ("godot4", "personagem_humanoide", True, "godot-humanoid@1", False),
        ("godot4", "personagem_humanoide", True, "godot-humanoid@1", True),
        ("godot4", "criatura", True, "quadruped@1", True),
    ],
)
def test_missing_and_none_bufferview_on_all_attributes_fail_g1(
    tmp_path: Path,
    perfil_nome: str,
    tipo: str,
    auto_rig: bool,
    esqueleto: str | None,
    organico_denso: bool,
) -> None:
    perfil = profiles.carregar(perfil_nome)
    item = _item_para(tipo, auto_rig, esqueleto)
    glb = _build_full_glb(
        perfil_nome=perfil_nome,
        esqueleto=esqueleto,
        organico_denso=organico_denso,
        com_anim=auto_rig,
    )
    res = {
        "medidas": {},
        "arquivos": [{"caminho": "m.glb", "papel": "mesh"}],
        "licenca": {"uso_comercial": True},
    }

    base_dir = tmp_path / "base"
    base_dir.mkdir()
    (base_dir / "m.glb").write_bytes(glb)
    rel_ok = qc.verificar(item, perfil, base_dir, res)
    assert rel_ok["aprovado"] is True, rel_ok

    for attr in ("NORMAL", "TANGENT", "COLOR_0", "JOINTS_0", "WEIGHTS_0", "TEXCOORD_0", "TEXCOORD_1"):
        for mode in ("pop", "none"):
            def _mut(g: dict, _b: bytearray, a: str = attr, m: str = mode) -> None:
                acc_i = g["meshes"][0]["primitives"][0]["attributes"][a]
                if m == "pop":
                    g["accessors"][acc_i].pop("bufferView", None)
                else:
                    g["accessors"][acc_i]["bufferView"] = None

            sub = tmp_path / f"{attr}_{mode}"
            sub.mkdir()
            (sub / "m.glb").write_bytes(_editar_gltf_glb(glb, _mut))
            rel = qc.verificar(item, perfil, sub, res)
            assert rel["aprovado"] is False, (attr, mode, rel)
            por_id = {g["id"]: g for g in rel["gates"]}
            assert por_id["G1"]["status"] == "falhou", (attr, mode, por_id["G1"])
            erros = por_id["G1"]["medido"].get("erros_gltf") or []
            assert any("bufferView_invalido" in e for e in erros), (attr, mode, erros)
            if attr in ("TEXCOORD_0", "TEXCOORD_1"):
                assert por_id["G3"]["status"] == "falhou", (attr, mode, por_id["G3"])


def test_animation_max_10_pow_400_does_not_raise_overflow_error(tmp_path: Path) -> None:
    perfil = profiles.carregar("godot4")
    item = _item_para("personagem_humanoide", True, "godot-humanoid@1")
    glb = _build_full_glb(
        perfil_nome="godot4",
        esqueleto="godot-humanoid@1",
        organico_denso=False,
        com_anim=True,
    )

    def _inject_huge_max(g: dict, _b: bytearray) -> None:
        t_idx = g["animations"][0]["samplers"][0]["input"]
        g["accessors"][t_idx]["max"] = [10**400]

    raw = _editar_gltf_glb(glb, _inject_huge_max)
    g_m, b_m = qc.ler_glb_bin(raw)
    clipes = qc_midia.animacoes(g_m, b_m)
    assert isinstance(clipes, list) and clipes[0]["duracao_s"] == 0.0

    (tmp_path / "anim_huge.glb").write_bytes(raw)
    rel = qc.verificar(
        item,
        perfil,
        tmp_path,
        {"medidas": {}, "arquivos": [{"caminho": "anim_huge.glb", "papel": "mesh"}], "licenca": {"uso_comercial": True}},
    )
    assert isinstance(rel, dict) and rel["aprovado"] is False
    assert {g["id"]: g["status"] for g in rel["gates"]}["G10"] == "falhou"

    def _boom() -> dict:
        raise OverflowError("int too large to convert to float")

    assert qc._rodar_gate("G10", _boom)["status"] == "falhou"


def test_sparse_validation_json_stub_and_dangling_texture_refs(tmp_path: Path) -> None:
    # 1) JSON-only analisar(gltf, None) remains unaffected when attribute has no bufferView
    stub_gltf = {
        "asset": {"version": "2.0"},
        "accessors": [{"count": 3, "type": "VEC3"}, {"count": 3, "type": "VEC2"}],
        "bufferViews": [],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "TEXCOORD_0": 1}}]}],
    }
    info_stub = qc.analisar(stub_gltf)
    assert "erros" not in info_stub and info_stub["sem_uv"] == 0

    # 2) Bogus empty sparse={} without bufferView fails; valid sparse passes _validar_refs_primitiva
    erros_bogus: list[str] = []
    qc_glb_mat._validar_refs_primitiva(
        {"attributes": {"NORMAL": 0}},
        0,
        [{"count": 3, "type": "VEC3", "sparse": {}}],
        [],
        [],
        erros_bogus,
        exigir_bv=True,
    )
    assert any("bufferView_invalido" in e for e in erros_bogus)

    erros_valid_sparse: list[str] = []
    _, _, _, attrs_ok = qc_glb_mat._validar_refs_primitiva(
        {"attributes": {"NORMAL": 0}},
        0,
        [{"count": 3, "type": "VEC3", "sparse": {"count": 1, "indices": {"bufferView": 0}, "values": {"bufferView": 1}}}],
        [{"byteLength": 4}, {"byteLength": 12}],
        [],
        erros_valid_sparse,
        exigir_bv=True,
    )
    assert not erros_valid_sparse and "NORMAL" in attrs_ok

    # 3) Dangling texture/source indices fail G1
    perfil = profiles.carregar("roblox-aa-80")
    item = _item_para("prop_estatico", False, None)
    glb = _build_full_glb(perfil_nome="roblox-aa-80")
    muts = [
        ("base_tex_oob", lambda g, _b: g["materials"][0]["pbrMetallicRoughness"]["baseColorTexture"].update({"index": 999})),
        ("norm_tex_oob", lambda g, _b: g["materials"][0]["normalTexture"].update({"index": 999})),
        ("tex_src_oob", lambda g, _b: g["textures"][0].update({"source": 999})),
    ]
    for nome, mut in muts:
        sub = tmp_path / nome
        sub.mkdir()
        (sub / "m.glb").write_bytes(_editar_gltf_glb(glb, mut))
        rel = qc.verificar(
            item,
            perfil,
            sub,
            {"medidas": {}, "arquivos": [{"caminho": "m.glb", "papel": "mesh"}], "licenca": {"uso_comercial": True}},
        )
        assert rel["aprovado"] is False, (nome, rel)
        g1 = next(g for g in rel["gates"] if g["id"] == "G1")
        assert g1["status"] == "falhou", (nome, g1)
