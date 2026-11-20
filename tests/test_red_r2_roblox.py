"""Suite TDD RED de descoberta para R2 (F05–F14): Roblox R15/MeshPart + G12–G14."""

from __future__ import annotations

import json
import struct
import subprocess
from pathlib import Path
from xml.etree import ElementTree

import jsonschema
import pytest
import yaml

from forge3d import (
    config, pipeline, plan, post, profiles, publish, qc, rbx, segmentacao, spec, sync, upload, verify,
)
from forge3d.canonical import sha256_bytes
from forge3d.cli.comandos import construir_parser

RAIZ = Path(__file__).resolve().parents[1]
_R15_15 = (
    "LowerTorso", "UpperTorso", "Head",
    "LeftUpperArm", "LeftLowerArm", "LeftHand", "RightUpperArm", "RightLowerArm", "RightHand",
    "LeftUpperLeg", "LeftLowerLeg", "LeftFoot", "RightUpperLeg", "RightLowerLeg", "RightFoot",
)


@pytest.fixture(autouse=True)
def _isolar_forge3d(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORGE3D_HOME", str(tmp_path / "forge_home"))
    monkeypatch.setenv("FORGE3D_CONFIG", str(tmp_path / "forge_cfg"))
    config.adicionar(tmp_path)


def _box_glb(
    center: tuple[float, float, float] = (0.0, 0.5, 0.0),
    half: tuple[float, float, float] = (0.25, 0.5, 0.25),
    *,
    extra_image_bytes: bytes | None = None,
) -> bytes:
    """Constroi GLB fechado (12 tris, outward winding) com material PBR opcionalmente texturizado."""
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
    pos_b = b"".join(struct.pack("<3f", *v) for v in verts)
    nrm_b = b"".join(struct.pack("<3f", 0.0, 1.0, 0.0) for _ in verts)
    uv_b = b"".join(struct.pack("<2f", (i % 2) * 1.0, ((i // 2) % 2) * 1.0) for i in range(8))
    idx_b = b"".join(struct.pack("<3H", *t) for t in tris)
    buf, bvs = bytearray(), []

    def _add(raw: bytes, target: int | None) -> int:
        while len(buf) % 4 != 0:
            buf.append(0)
        off = len(buf)
        buf.extend(raw)
        bv: dict = {"buffer": 0, "byteOffset": off, "byteLength": len(raw)}
        if target is not None:
            bv["target"] = target
        bvs.append(bv)
        return len(bvs) - 1

    bv_pos, bv_nrm, bv_uv, bv_idx = _add(pos_b, 34962), _add(nrm_b, 34962), _add(uv_b, 34962), _add(idx_b, 34963)
    bv_img = _add(extra_image_bytes, None) if extra_image_bytes is not None else None
    while len(buf) % 4 != 0:
        buf.append(0)

    xs, ys, zs = [v[0] for v in verts], [v[1] for v in verts], [v[2] for v in verts]
    mat: dict = {"name": "mat0", "pbrMetallicRoughness": {"baseColorFactor": [0.8, 0.8, 0.8, 1.0]}}
    gltf: dict = {
        "asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0]}],
        "nodes": [{"name": "mesh_node", "mesh": 0}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1, "TEXCOORD_0": 2}, "indices": 3, "material": 0}]}],
        "materials": [mat],
        "accessors": [
            {"bufferView": bv_pos, "componentType": 5126, "count": 8, "type": "VEC3",
             "min": [min(xs), min(ys), min(zs)], "max": [max(xs), max(ys), max(zs)]},
            {"bufferView": bv_nrm, "componentType": 5126, "count": 8, "type": "VEC3"},
            {"bufferView": bv_uv, "componentType": 5126, "count": 8, "type": "VEC2"},
            {"bufferView": bv_idx, "componentType": 5123, "count": 36, "type": "SCALAR"},
        ],
        "bufferViews": bvs, "buffers": [{"byteLength": len(buf)}],
    }
    if bv_img is not None:
        mat["pbrMetallicRoughness"]["baseColorTexture"] = {"index": 0}
        gltf["samplers"] = [{"magFilter": 9729, "minFilter": 9987}]
        gltf["textures"] = [{"sampler": 0, "source": 0}]
        gltf["images"] = [{"bufferView": bv_img, "mimeType": "image/png"}]

    jb = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    jb += b" " * ((4 - len(jb) % 4) % 4)
    total = 12 + 8 + len(jb) + 8 + len(buf)
    return (
        struct.pack("<III", 0x46546C67, 2, total)
        + struct.pack("<II", len(jb), 0x4E4F534A) + jb
        + struct.pack("<II", len(buf), 0x004E4942) + bytes(buf)
    )


def _publicar_asset_box(pasta: Path, asset_id: str, extra_files: list[dict] | None = None) -> dict:
    """Publica prop blocky fechado valido em ``pasta`` e devolve o manifesto gravado."""
    pasta.mkdir(parents=True, exist_ok=True)
    perfil = profiles.carregar("roblox-r15")
    escala = float(perfil["unidades"]["escala_saida"])
    glb_bytes = _box_glb(center=(0.0, 0.5 * escala, 0.0), half=(0.25 * escala, 0.5 * escala, 0.25 * escala))
    glb_path = pasta / f"{asset_id}.glb"
    glb_path.write_bytes(glb_bytes)
    gltf, bin_b = qc.ler_glb_bin(glb_path)
    topo = qc.topologia(gltf, bin_b)
    licenca = {"modelo": "procedural", "uso_comercial": True, "notice": "MIT"}
    item = {
        "id": asset_id, "tipo": "prop_estatico", "rota": "blocky", "altura_metros": 1.0,
        "pivot": "base", "limite_triangulos": 500, "colisao": "none", "lod": [100], "tags": ["teste"],
    }
    resultado = {
        "determinism": "D1", "licenca": licenca, "medidas": {**topo, "partes_colisao": 0},
        "arquivos": [
            {"caminho": glb_path.name, "papel": "mesh", "sha256": sha256_bytes(glb_bytes),
             "bytes": len(glb_bytes), "nivel": 0, "triangulos": 12},
            *(extra_files or []),
        ],
    }
    rel_qc = qc.verificar(item, perfil, pasta, resultado, escala_saida=escala)
    assert rel_qc["aprovado"] is True, rel_qc
    man = publish.montar_manifesto(
        item=item, spec_doc={"projeto": "proj_a", "perfil": "roblox-r15"}, spec_hash="sha256:" + "a" * 64,
        perfil_nome="roblox-r15", perfil=perfil, provider={"nome": "blocky", "versao": "1.0", "determinism": "D1"},
        resultado=resultado, relatorio_qc=rel_qc, licenca=licenca, run_id="20261119T000000Z-red",
    )
    (pasta / f"{asset_id}.manifest.json").write_text(json.dumps(man, indent=1), encoding="utf-8")
    return man


# ------------------------------------------------------------------ F05
def test_f05_sequencia_xml_arvore_pose_r15_easing_e_studs() -> None:
    clipe = {
        "nome": "walk", "loop": True,
        "chaves": [{"segundos": 0.25, "poses": [
            {"osso": "LowerTorso", "graus": 0.0, "eixo": "X", "deslocamento_m": [0.0, 0.0, 0.28]},
            {"osso": "Head", "graus": 30.0, "eixo": "X"},
        ]}],
    }
    linhas, _ = rbx._sequencia_xml(clipe, 10)
    seq = ElementTree.fromstring("\n".join(linhas))
    kf = seq.find("Item[@class='Keyframe']")
    assert kf is not None
    assert kf.findtext("Properties/string[@name='Name']") == "Keyframe"

    poses_raiz = kf.findall("Item[@class='Pose']")
    assert [p.findtext("Properties/string[@name='Name']") for p in poses_raiz] == ["HumanoidRootPart"]
    hrp = poses_raiz[0]
    assert float(hrp.findtext("Properties/float[@name='Weight']") or -1) == pytest.approx(0.0)

    lt = hrp.find("Item[@class='Pose']")
    assert lt is not None and lt.findtext("Properties/string[@name='Name']") == "LowerTorso"
    assert lt.find("Properties/token[@name='EasingStyle']") is not None
    assert lt.find("Properties/token[@name='EasingDirection']") is not None
    assert float(lt.findtext("Properties/CoordinateFrame[@name='CFrame']/Y") or 0.0) == pytest.approx(1.0, abs=1e-4)

    ut = lt.find("Item[@class='Pose']")
    assert ut is not None and ut.findtext("Properties/string[@name='Name']") == "UpperTorso"
    head = next((p for p in ut.findall("Item[@class='Pose']") if p.findtext("Properties/string[@name='Name']") == "Head"), None)
    assert head is not None


def test_f05_ler_place_le_poses_aninhadas(tmp_path: Path) -> None:
    xml_place = (
        '<?xml version="1.0" encoding="utf-8"?><roblox version="4">'
        '<Item class="Workspace" referent="RBX0"><Properties><string name="Name">Workspace</string></Properties>'
        '<Item class="KeyframeSequence" referent="RBX1"><Properties>'
        '<string name="Name">idle</string><bool name="Loop">true</bool><token name="Priority">0</token></Properties>'
        '<Item class="Keyframe" referent="RBX2"><Properties><string name="Name">Keyframe</string><float name="Time">0.0</float></Properties>'
        '<Item class="Pose" referent="RBX3"><Properties><string name="Name">HumanoidRootPart</string><float name="Weight">0</float></Properties>'
        '<Item class="Pose" referent="RBX4"><Properties><string name="Name">LowerTorso</string><float name="Weight">1</float></Properties>'
        '<Item class="Pose" referent="RBX5"><Properties><string name="Name">UpperTorso</string><float name="Weight">1</float></Properties>'
        '<Item class="Pose" referent="RBX6"><Properties><string name="Name">Head</string><float name="Weight">1</float></Properties>'
        "</Item></Item></Item></Item></Item></Item></Item></roblox>"
    )
    rbxlx = tmp_path / "nested.rbxlx"
    rbxlx.write_text(xml_place, encoding="utf-8")
    place = rbx.ler_place(rbxlx)
    nomes = {p["osso"] for p in place["clipes"][0]["chaves"][0]["poses"]}
    assert {"HumanoidRootPart", "LowerTorso", "UpperTorso", "Head"}.issubset(nomes)


# ------------------------------------------------------------------ F06
@pytest.mark.blender
def test_f06_split_por_ossos_yup_watertight_texturas_e_tangentes(tmp_path: Path) -> None:
    blender = post.binario()
    in_glb = tmp_path / "rigged.glb"
    setup_py = tmp_path / "make_rigged.py"
    setup_py.write_text(
        "import bpy, bmesh\n"
        "bpy.ops.wm.read_factory_settings(use_empty=True)\n"
        "arm_d = bpy.data.armatures.new('Arm'); arm = bpy.data.objects.new('Arm', arm_d)\n"
        "bpy.context.scene.collection.objects.link(arm); bpy.context.view_layer.objects.active = arm\n"
        "bpy.ops.object.mode_set(mode='EDIT')\n"
        "b1 = arm_d.edit_bones.new('LowerTorso'); b1.head = (0.2, 0.4, 0.0); b1.tail = (0.2, 0.4, 1.0)\n"
        "b2 = arm_d.edit_bones.new('UpperTorso'); b2.head = (0.2, 0.4, 1.0); b2.tail = (0.2, 0.4, 2.0); b2.parent = b1\n"
        "bpy.ops.object.mode_set(mode='OBJECT')\n"
        "mesh_d = bpy.data.meshes.new('Body'); bm = bmesh.new(); bmesh.ops.create_cube(bm, size=1.0)\n"
        "for v in bm.verts:\n"
        "    v.co.x = v.co.x * 0.4 + 0.2; v.co.y = v.co.y * 0.6 + 0.4; v.co.z = (v.co.z + 0.5) * 2.0\n"
        "bmesh.ops.subdivide_edges(bm, edges=bm.edges[:], cuts=2, use_grid_fill=True); bm.to_mesh(mesh_d); bm.free()\n"
        "obj = bpy.data.objects.new('Body', mesh_d); bpy.context.scene.collection.objects.link(obj)\n"
        "uv = mesh_d.uv_layers.new(name='UVMap')\n"
        "for lp in mesh_d.loops: uv.data[lp.index].uv = (lp.vertex_index % 2, 0.5)\n"
        "vg1, vg2 = obj.vertex_groups.new(name='LowerTorso'), obj.vertex_groups.new(name='UpperTorso')\n"
        "for v in mesh_d.vertices: (vg1 if v.co.z < 1.0 else vg2).add([v.index], 1.0, 'REPLACE')\n"
        "obj.parent = arm; mod = obj.modifiers.new('Arm', 'ARMATURE'); mod.object = arm\n"
        "mat = bpy.data.materials.new('Mat'); mat.use_nodes = True; nt = mat.node_tree; bsdf = nt.nodes['Principled BSDF']\n"
        "ic = bpy.data.images.new('C', 8, 8); ic.pixels[:] = [0.8, 0.2, 0.2, 1.0]*64; ic.pack()\n"
        "tc = nt.nodes.new('ShaderNodeTexImage'); tc.image = ic; nt.links.new(tc.outputs['Color'], bsdf.inputs['Base Color'])\n"
        "inm = bpy.data.images.new('N', 8, 8); inm.colorspace_settings.name = 'Non-Color'; inm.pixels[:] = [0.5, 0.5, 1.0, 1.0]*64; inm.pack()\n"
        "tn = nt.nodes.new('ShaderNodeTexImage'); tn.image = inm; nm = nt.nodes.new('ShaderNodeNormalMap')\n"
        "nt.links.new(tn.outputs['Color'], nm.inputs['Color']); nt.links.new(nm.outputs['Normal'], bsdf.inputs['Normal'])\n"
        "mesh_d.materials.append(mat)\n"
        f"bpy.ops.export_scene.gltf(filepath={str(in_glb)!r}, export_format='GLB', export_yup=True, export_tangents=True)\n",
        encoding="utf-8",
    )
    proc_prep = subprocess.run([blender, "--background", "--factory-startup", "--python-exit-code", "1", "--python", str(setup_py)], capture_output=True, text=True, timeout=60)
    assert proc_prep.returncode == 0, proc_prep.stderr

    out_dir, job, resumo_path = tmp_path / "split_out", tmp_path / "job.json", tmp_path / "resumo.json"
    job.write_text(json.dumps({"glb": str(in_glb), "saida": str(out_dir), "partes": [{"nome": "LowerTorso", "junta": "Root"}, {"nome": "UpperTorso", "junta": "Waist"}]}), encoding="utf-8")
    proc_split = subprocess.run([blender, "--background", "--factory-startup", "--python-exit-code", "1", "--python", str(RAIZ / "blender" / "split_por_ossos.py"), "--", str(job), str(resumo_path)], capture_output=True, text=True, timeout=60)
    assert proc_split.returncode == 0, proc_split.stderr

    resumo = json.loads(resumo_path.read_text(encoding="utf-8"))
    assert resumo["ancoras"]["LowerTorso"] == pytest.approx([0.2, 0.0, -0.4], abs=1e-3)
    lt_info = next(p for p in resumo["partes"] if p["nome"] == "LowerTorso")
    assert lt_info["bbox"][1] > lt_info["bbox"][2]

    gltf_p, bin_p = qc.ler_glb_bin(out_dir / "LowerTorso.glb")
    assert qc.topologia(gltf_p, bin_p)["bordas_abertas"] == 0
    assert len(gltf_p.get("images") or []) >= 1
    assert "TANGENT" in gltf_p["meshes"][0]["primitives"][0]["attributes"]


def test_f06_pipeline_executa_qc_apos_segmentacao(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ordem: list[str] = []

    class _FakeProv:
        nome, versao, determinism, usa_gpu = "mesh", "1.0", "D2", False
        licenca = {"modelo": "MIT", "uso_comercial": True, "notice": "MIT"}

        def gerar(self, _item, _perfil, pasta: Path):
            return type("_B", (), {"dir": pasta, "meta": {}})()

    final_dir = tmp_path / "final"
    final_dir.mkdir()
    (final_dir / "boss.glb").write_bytes(_box_glb())
    monkeypatch.setattr(pipeline.providers, "obter", lambda _r: _FakeProv())
    monkeypatch.setattr(
        pipeline, "_pos_processar",
        lambda *_a, **_k: {
            "dir_final": str(final_dir),
            "arquivos": [{"caminho": "boss.glb", "papel": "mesh", "sha256": "sha256:" + "0" * 64, "bytes": 10, "nivel": 0, "triangulos": 12}],
            "medidas": {},
        },
    )
    monkeypatch.setattr(segmentacao, "dividir", lambda *_a, **_k: (ordem.append("segmentacao"), {"partes": [], "ancoras": {}, "arquivos": []})[1])
    monkeypatch.setattr(
        qc, "verificar",
        lambda *_a, **_k: (
            ordem.append("qc"),
            {"aprovado": True, "gates": [{"id": "G1", "status": "ok"}],
             "medidas": {"triangulos": 12, "vertices": 8, "bbox_m": [0.5, 1.0, 0.5], "materiais": 1, "esqueleto": "r15@1", "ossos": 16, "animacoes": []}},
        )[1],
    )
    monkeypatch.setattr(publish, "salvar_cache", lambda *_a, **_k: None)

    item = {"id": "boss.r15.01", "rota": "mesh", "partes": [{"nome": n} for n in _R15_15], "rig": {"modo": "motor6d", "esqueleto": "r15@1"}}
    pipeline._executar_item(
        item, {"chave": "k1"}, spec_doc={"projeto": "demo", "perfil": "roblox-aa-80"},
        perfil=profiles.carregar("roblox-aa-80"), spec_hash="sha256:" + "b" * 64,
        destino=tmp_path / "out", run_id="r1", publicar_arquivos=False, no_cache=True,
    )
    assert ordem.index("segmentacao") < ordem.index("qc")


# ------------------------------------------------------------------ F07
def test_f07_verify_rejeita_parte_glb_corrompida(tmp_path: Path) -> None:
    parte_bytes = b"CORRUPTED_NOT_GLB"
    (tmp_path / "Head.glb").write_bytes(parte_bytes)
    man = _publicar_asset_box(
        tmp_path, "boss.seg.01",
        extra_files=[{"caminho": "Head.glb", "papel": "parte", "sha256": sha256_bytes(parte_bytes), "bytes": len(parte_bytes)}],
    )
    man["partes"] = [{"nome": "Head", "junta": "Neck", "ancora": [0.0, 1.5, 0.0], "bbox": [0.4, 0.4, 0.4], "triangulos": 12, "arquivo": "Head.glb"}]
    (tmp_path / "boss.seg.01.manifest.json").write_text(json.dumps(man, indent=1), encoding="utf-8")
    assert verify.verificar(tmp_path)["ok"] is False


def test_f07_g11_e_plan_contam_draw_calls_de_partes(tmp_path: Path) -> None:
    partes = [{"nome": n, "junta": "Root", "ancora": [0.0, 0.0, 0.0], "bbox": [0.3, 0.3, 0.3], "triangulos": 100, "arquivo": f"{n}.glb"} for n in _R15_15]
    item = {"id": "boss.r15.01", "tipo": "criatura", "rota": "mesh", "auto_rig": True, "esqueleto": "r15@1", "partes": partes, "rig": {"modo": "motor6d", "esqueleto": "r15@1"}}
    staging = {"origem": tmp_path, "resultado": {"arquivos": [], "partes": partes}, "relatorio_qc": {"medidas": {"triangulos": 1500, "primitivas": 1}, "gates": []}, "manifesto": {"anexo": {"skinned": False}}}
    assert pipeline._medir_item_g11(item, staging)["primitivas"] == 15

    perfil = profiles.carregar("roblox-aa-80")
    assert plan._estimar_item_calibrado(item, {"perfil": "roblox-aa-80", "lote": [item]}, perfil)["primitivas"] == 15


# ------------------------------------------------------------------ F08
def test_f08_exportar_r15_aceita_rota_mesh_segmentada(tmp_path: Path) -> None:
    lote_yaml = tmp_path / "lote_mesh.yaml"
    lote_yaml.write_text(yaml.safe_dump({
        "schema": "forge3d/spec@6", "projeto": "demo", "perfil": "roblox-aa-80", "destino_exportacao": str(tmp_path / "dest"),
        "lote": [{"id": "boss.mesh.01", "tipo": "criatura", "rota": "mesh", "prompt": "golem", "altura_metros": 2.2,
                  "seed": 42, "auto_rig": True, "esqueleto": "r15@1", "partes": [{"nome": n} for n in _R15_15],
                  "rig": {"modo": "motor6d", "esqueleto": "r15@1"}}],
    }), encoding="utf-8")
    ancoras = {n: [0.0, 1.0 + i * 0.2, 0.0] for i, n in enumerate(_R15_15)}
    manifesto = {
        "schema": "forge3d/manifest@6", "asset_id": "boss.mesh.01",
        "partes": [{"nome": n, "junta": rbx.JOINT_R15[n], "ancora": ancoras[n], "bbox": [1.0, 1.0, 1.0], "triangulos": 120, "arquivo": f"{n}.glb"} for n in _R15_15],
        "rig": {"esqueleto": "r15@1", "ossos": 16, "modo": "motor6d", "ancoras": ancoras},
        "files": [
            *[{"caminho": f"{n}.glb", "papel": "parte"} for n in _R15_15],
            {"caminho": "boss_baseColor.png", "papel": "basecolor"}, {"caminho": "boss_normal.png", "papel": "normal"},
            {"caminho": "boss_roughness.png", "papel": "roughness"}, {"caminho": "boss_metallic.png", "papel": "metallic"},
        ],
    }
    asset_ids = {f"{n}.glb": str(1000 + i) for i, n in enumerate(_R15_15)}
    asset_ids.update({"ColorMap": "2001", "NormalMap": "2002", "RoughnessMap": "2003", "MetalnessMap": "2004"})

    out = tmp_path / "boss_mesh.rbxlx"
    rel = rbx.exportar_r15(lote_yaml, "boss.mesh.01", saida=out, asset_ids=asset_ids, manifesto=manifesto)
    assert rel["ok"] is True
    raiz = ElementTree.fromstring(out.read_text(encoding="utf-8"))
    meshparts = [e for e in raiz.iter("Item") if e.get("class") == "MeshPart"]
    motores = [e for e in raiz.iter("Item") if e.get("class") == "Motor6D"]
    assert len(meshparts) == 15 and len(motores) == 15
    assert meshparts[0].find("Properties/token[@name='CollisionFidelity']") is not None
    assert meshparts[0].find("Properties/token[@name='RenderFidelity']") is not None
    sa = meshparts[0].find("Item[@class='SurfaceAppearance']/Properties")
    assert sa is not None and sa.findtext("Content[@name='MetalnessMap']/url") == "rbxassetid://2004"
    hum = raiz.find(".//Item[@class='Humanoid']/Properties")
    assert hum is not None and float(hum.findtext("float[@name='HipHeight']") or 0.0) > 0.0


# ------------------------------------------------------------------ F09
def test_f09_bbox_m_yup_sem_swap_yz_em_meshpart_e_acessorio(tmp_path: Path) -> None:
    man = {"schema": "forge3d/manifest@6", "asset_id": "prop.yup.01", "geometry": {"bbox_m": [0.70, 1.82, 0.42]}, "unidades_export": {"metros_por_unidade": 0.28, "escala_saida": 3.5714}}
    res_mp = rbx.exportar_meshpart_pbr_rbxmx(man, mesh_id="123", saida=tmp_path / "mp.rbxmx")
    sz_mp = ElementTree.fromstring(res_mp["xml"]).find(".//Item[@class='MeshPart']/Properties/Vector3[@name='size']")
    assert (float(sz_mp.findtext("X")), float(sz_mp.findtext("Y")), float(sz_mp.findtext("Z"))) == pytest.approx((2.5, 6.5, 1.5), abs=1e-4)

    res_ac = rbx.exportar_acessorio_rbxmx(man, mesh_id="123", saida=tmp_path / "acc.rbxmx")
    sz_ac = ElementTree.fromstring(res_ac["xml"]).find(".//Item[@class='MeshPart']/Properties/Vector3[@name='size']")
    assert (float(sz_ac.findtext("X")), float(sz_ac.findtext("Y")), float(sz_ac.findtext("Z"))) == pytest.approx((2.5, 6.5, 1.5), abs=1e-4)


# ------------------------------------------------------------------ F10
def test_f10_sockets_sem_dupla_divisao_por_028(tmp_path: Path) -> None:
    sockets = [{"nome": "Socket_HandR", "osso": "Hand.R", "posicao_local": [0.0, -1.4, 0.0]}]
    man = {"schema": "forge3d/manifest@6", "asset_id": "espada.01", "sockets": sockets, "unidades_export": {"metros_por_unidade": 0.28, "escala_saida": 3.5714}}
    res_acc = rbx.exportar_acessorio_rbxmx(man, mesh_id="555", attachment_name="RightGripAttachment", saida=tmp_path / "espada.rbxmx")
    att_cf = ElementTree.fromstring(res_acc["xml"]).find(".//Item[@class='Attachment']/Properties/CoordinateFrame[@name='CFrame']")
    assert float(att_cf.findtext("Y")) == pytest.approx(-1.4, abs=1e-3)

    base_out, sock_out = tmp_path / "r15_base.rbxlx", tmp_path / "r15_sock.rbxlx"
    rbx.exportar_r15("examples/lote_09_r15.yaml", "personagem.r15.guard.01", saida=base_out)
    rbx.exportar_r15("examples/lote_09_r15.yaml", "personagem.r15.guard.01", saida=sock_out, sockets=sockets)

    def _att_y(path: Path) -> float:
        for att in ElementTree.parse(path).getroot().iter("Item"):
            if att.get("class") == "Attachment" and att.findtext("Properties/string[@name='Name']") == "RightGripAttachment":
                return float(att.findtext("Properties/CoordinateFrame[@name='CFrame']/Y") or 0.0)
        raise AssertionError("RightGripAttachment ausente")

    assert _att_y(sock_out) - _att_y(base_out) == pytest.approx(-1.4, abs=1e-3)


# ------------------------------------------------------------------ F11
def test_f11_remover_imagens_embutidas_glb_compacta_bin() -> None:
    glb_in = _box_glb(extra_image_bytes=b"\x89PNG\r\n\x1a\n" + (b"\xAB" * 4088))
    glb_out, info = upload.remover_imagens_embutidas_glb(glb_in)
    assert info["imagens_removidas"] == 1
    assert info["bytes_depois"] <= info["bytes_antes"] - 4000
    gltf_out, bin_out = qc.ler_glb_bin(glb_out)
    assert gltf_out["buffers"][0]["byteLength"] == len(bin_out)
    assert len(bin_out) < 512


def test_f11_cli_upload_model_aceita_strip_embedded_textures() -> None:
    parser = construir_parser()
    try:
        args = parser.parse_args(["upload-model", "modelo.glb", "--strip-embedded-textures", "--dry-run"])
    except SystemExit as exc:
        pytest.fail(f"upload-model parser rejeitou --strip-embedded-textures (exit={exc.code})")
    assert args.strip_embedded_textures is True


# ------------------------------------------------------------------ F12
def test_f12_spec_campos_canonicos_incluem_partes_rig_animacoes_quantidade_cena() -> None:
    esperados = {"partes", "rig", "animacoes", "quantidade_cena"}
    assert esperados.issubset(spec.CAMPOS_CANONICOS_ITEM)
    item = {
        "id": "boss.01", "tipo": "criatura", "rota": "mesh", "partes": [{"nome": "Head"}],
        "rig": {"modo": "motor6d", "esqueleto": "r15@1"},
        "animacoes": [{"nome": "idle", "formato": "keyframe", "alvo": "motor6d", "loop": True}], "quantidade_cena": 3,
    }
    resolvido = spec.resolver_item(item)
    for k in esperados:
        assert resolvido[k] == item[k]


# ------------------------------------------------------------------ F13
def test_f13_sync_rojo_lua_isola_ledger_por_projeto(tmp_path: Path) -> None:
    origem = tmp_path / "pub_a"
    _publicar_asset_box(origem, "proj_a.sword.01")
    publish.registrar_ledger({"evento": "upload", "id": "proj_a.sword.01", "role": "mesh", "asset_id": "111111"})
    publish.registrar_ledger({"evento": "upload", "id": "other_game.dragon.99", "role": "mesh", "asset_id": "999999"})

    lua_out = tmp_path / "rojo" / "Assets.lua"
    assert sync.executar(origem, tmp_path / "sync_a", rojo_lua=lua_out)["ok"] is True
    conteudo = lua_out.read_text(encoding="utf-8")
    assert "proj_a.sword.01" in conteudo
    assert "other_game.dragon.99" not in conteudo and "999999" not in conteudo


# ------------------------------------------------------------------ F14
def test_f14_qc_gates_e_manifest_schema_suportam_g12_g13_g14_g15(tmp_path: Path) -> None:
    assert {"G12", "G13", "G14"}.issubset(qc.GATES)
    man = _publicar_asset_box(tmp_path, "prop.gates.01")
    man["qc"]["gates"].extend([{"id": g, "status": "ok"} for g in ("G12", "G13", "G14", "G15")])
    schema = json.loads((RAIZ / "schemas" / "manifest.v6.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(man)


def test_f14_g12_g13_g14_detectam_interpenetracao_ancora_e_pose(tmp_path: Path) -> None:
    perfil = profiles.carregar("roblox-aa-80")
    escala = float(perfil["unidades"]["escala_saida"])
    (tmp_path / "LowerTorso.glb").write_bytes(_box_glb(center=(0.0, 0.5, 0.0), half=(0.2, 0.5, 0.2)))
    (tmp_path / "UpperTorso.glb").write_bytes(_box_glb(center=(0.0, 0.9, 0.0), half=(0.2, 0.5, 0.2)))
    (tmp_path / "boss.glb").write_bytes(_box_glb(center=(0.0, 0.5 * escala, 0.0), half=(0.25 * escala, 0.5 * escala, 0.25 * escala)))

    partes = [
        {"nome": "LowerTorso", "junta": "Root", "ancora": [0.0, 0.0, 0.0], "bbox": [0.4, 1.0, 0.4], "triangulos": 12, "arquivo": "LowerTorso.glb"},
        {"nome": "UpperTorso", "junta": "Waist", "ancora": [0.0, 1.01, 0.0], "bbox": [0.4, 1.0, 0.4], "triangulos": 12, "arquivo": "UpperTorso.glb"},
    ]
    item = {"id": "boss.qc.01", "tipo": "criatura", "rota": "mesh", "altura_metros": 1.0, "pivot": "base", "limite_triangulos": 5000, "colisao": "none", "lod": [100], "partes": partes, "rig": {"modo": "motor6d", "esqueleto": "r15@1"}, "animacoes_base": ["idle"]}
    resultado = {
        "medidas": {"triangulos": 12, "vertices": 8, "nao_manifold": 0, "bordas_abertas": 0, "arestas_t": 0, "degeneradas": 0, "invertidas": 0, "materiais": 1, "bbox_m": [0.5, 1.0, 0.5], "esqueleto": "r15@1", "ossos": 16, "animacoes": ["idle"]},
        "arquivos": [{"caminho": "boss.glb", "papel": "mesh", "nivel": 0, "triangulos": 12}, {"caminho": "LowerTorso.glb", "papel": "parte"}, {"caminho": "UpperTorso.glb", "papel": "parte"}],
        "partes": partes, "ancoras": {"Root": [0.0, 0.0, 0.0], "Waist": [0.0, 1.0, 0.0]},
    }
    rel = qc.verificar(item, perfil, tmp_path, resultado, escala_saida=escala)
    por_id = {g["id"]: g for g in rel["gates"]}
    assert por_id.get("G12", {}).get("status") == "falhou"
    assert por_id.get("G13", {}).get("status") == "falhou"
    assert "G14" in por_id


def test_f14_tools_possui_harness_play_mode_studio_g14() -> None:
    play_scripts = [p for p in (RAIZ / "tools").glob("*r15*.*") if any(tok in p.read_text(encoding="utf-8") for tok in ("G14", "LoadAnimation", "RunService"))]
    assert play_scripts, "Nenhum harness Play-mode G14 encontrado em tools/"
