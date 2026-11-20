"""F2: o manifesto publica `partes`/`rig.ancoras` e aceita papel `parte`."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from forge3d import profiles, publish

RAIZ = Path(__file__).resolve().parents[1]


def _arquivo(caminho: str, papel: str, byte: str, nivel: int = 0) -> dict:
    return {
        "caminho": caminho,
        "papel": papel,
        "sha256": "sha256:" + byte * 64,
        "bytes": 10,
        "nivel": nivel,
        "triangulos": 100,
    }


def _resultado() -> dict:
    return {
        "determinism": "D2",
        "arquivos": [
            _arquivo("boss.glb", "mesh", "0"),
            _arquivo("Head.glb", "parte", "1"),
            _arquivo("LowerTorso.glb", "parte", "2"),
        ],
        "partes": [
            {
                "nome": "Head",
                "junta": "Neck",
                "ancora": [0.0, 0.0, 9.3],
                "bbox": [5.0, 6.9, 2.6],
                "triangulos": 3272,
                "arquivo": "Head.glb",
            },
            {
                "nome": "LowerTorso",
                "junta": "Root",
                "ancora": [0.0, 4.8, 0.0],
                "bbox": [4.6, 2.9, 5.0],
                "triangulos": 900,
                "arquivo": "LowerTorso.glb",
            },
        ],
        "ancoras": {"Neck": [0.0, 0.0, 9.3], "Root": [0.0, 4.8, 0.0]},
    }


def test_manifesto_emite_partes_e_ancoras():
    manifesto = publish.montar_manifesto(
        item={
            "id": "boss.r15.01",
            "tipo": "criatura",
            "rota": "mesh",
            "auto_rig": True,
            "esqueleto": "r15@1",
            "tags": ["teste"],
            "partes": [{"nome": "Head", "junta": "Neck"}, {"nome": "LowerTorso", "junta": "Root"}],
            "rig": {"modo": "motor6d", "esqueleto": "r15@1"},
        },
        spec_doc={"projeto": "demo", "perfil": "roblox-aa-80"},
        spec_hash="sha256:" + "a" * 64,
        perfil_nome="roblox-aa-80",
        perfil=profiles.carregar("roblox-aa-80"),
        provider={"nome": "mesh", "versao": "x", "determinism": "D2"},
        resultado=_resultado(),
        relatorio_qc={
            "aprovado": True,
            "gates": [{"id": "G1", "status": "ok"}],
            "medidas": {
                "triangulos": 4172,
                "vertices": 2000,
                "bbox_m": [1.0, 1.0, 1.0],
                "materiais": 1,
                "esqueleto": "r15@1",
                "ossos": 16,
                "animacoes": [],
            },
        },
        licenca={"modelo": "TripoSR", "uso_comercial": True, "notice": "MIT"},
        run_id="20261118T000000Z-teste",
    )

    assert manifesto["rig"]["modo"] == "motor6d"
    assert manifesto["rig"]["ancoras"]["Neck"] == [0.0, 0.0, 9.3]
    assert [p["nome"] for p in manifesto["partes"]] == ["Head", "LowerTorso"]
    assert manifesto["partes"][0]["junta"] == "Neck"
    assert any(f["papel"] == "parte" for f in manifesto["files"])

    schema = json.loads((RAIZ / "schemas" / "manifest.v6.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(manifesto)


@pytest.mark.blender
def test_f06_split_respeita_pesos_vertex_groups_fallback_watertight_e_yup(tmp_path: Path) -> None:
    """F06: vertex_groups domina distancia, fallback por osso cobre sem peso, malha watertight Y-up."""
    import subprocess
    from forge3d import post, qc, segmentacao

    blender = post.binario()
    in_glb = tmp_path / "weighted.glb"
    setup_py = tmp_path / "make_weighted.py"
    setup_py.write_text(
        "import bpy, bmesh\n"
        "bpy.ops.wm.read_factory_settings(use_empty=True)\n"
        "arm_d = bpy.data.armatures.new('Arm'); arm = bpy.data.objects.new('Arm', arm_d)\n"
        "bpy.context.scene.collection.objects.link(arm); bpy.context.view_layer.objects.active = arm\n"
        "bpy.ops.object.mode_set(mode='EDIT')\n"
        "b1 = arm_d.edit_bones.new('LowerTorso'); b1.head = (0.0, 0.0, 0.0); b1.tail = (0.0, 0.0, 1.0)\n"
        "b2 = arm_d.edit_bones.new('UpperTorso'); b2.head = (0.0, 0.0, 1.0); b2.tail = (0.0, 0.0, 2.0); b2.parent = b1\n"
        "bpy.ops.object.mode_set(mode='OBJECT')\n"
        "mesh_d = bpy.data.meshes.new('Body'); bm = bmesh.new(); bmesh.ops.create_cube(bm, size=1.0)\n"
        "for v in bm.verts:\n"
        "    v.co.x *= 0.4; v.co.y *= 0.4; v.co.z = (v.co.z + 0.5) * 2.0\n"
        "bmesh.ops.subdivide_edges(bm, edges=bm.edges[:], cuts=3, use_grid_fill=True); bm.to_mesh(mesh_d); bm.free()\n"
        "obj = bpy.data.objects.new('Body', mesh_d); bpy.context.scene.collection.objects.link(obj)\n"
        "uv = mesh_d.uv_layers.new(name='UVMap')\n"
        "for lp in mesh_d.loops: uv.data[lp.index].uv = (0.25 + 0.5 * (lp.vertex_index % 2), 0.5)\n"
        "vg1, vg2 = obj.vertex_groups.new(name='LowerTorso'), obj.vertex_groups.new(name='UpperTorso')\n"
        "for v in mesh_d.vertices:\n"
        "    if v.co.z < 1.35: vg1.add([v.index], 1.0, 'REPLACE')\n"
        "    elif v.co.z > 1.55: vg2.add([v.index], 1.0, 'REPLACE')\n"
        "obj.parent = arm; mod = obj.modifiers.new('Arm', 'ARMATURE'); mod.object = arm\n"
        "mat = bpy.data.materials.new('Mat'); mat.use_nodes = True; nt = mat.node_tree; bsdf = nt.nodes['Principled BSDF']\n"
        "ic = bpy.data.images.new('C', 8, 8); ic.pixels[:] = [0.2, 0.7, 0.3, 1.0]*64; ic.pack()\n"
        "tc = nt.nodes.new('ShaderNodeTexImage'); tc.image = ic; nt.links.new(tc.outputs['Color'], bsdf.inputs['Base Color'])\n"
        "mesh_d.materials.append(mat)\n"
        f"bpy.ops.export_scene.gltf(filepath={str(in_glb)!r}, export_format='GLB', export_yup=True, export_tangents=True)\n",
        encoding="utf-8",
    )
    proc = subprocess.run([blender, "--background", "--factory-startup", "--python-exit-code", "1", "--python", str(setup_py)], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr

    out_dir = tmp_path / "parts"
    res = segmentacao.dividir(in_glb, {"id": "w.01", "partes": [{"nome": "LowerTorso", "junta": "Root"}, {"nome": "UpperTorso", "junta": "Waist"}]}, out_dir)
    lt = next(p for p in res["partes"] if p["nome"] == "LowerTorso")
    ut = next(p for p in res["partes"] if p["nome"] == "UpperTorso")
    # Peso de LowerTorso vai ate z=1.35 (acima do corte geometrico z=1.0)
    assert lt["bbox"][1] > 1.2
    assert ut["ancora"] == pytest.approx([0.0, 1.0, 0.0], abs=1e-3)
    for p in res["partes"]:
        g_p, b_p = qc.ler_glb_bin(out_dir / p["arquivo"])
        assert qc.topologia(g_p, b_p)["bordas_abertas"] == 0
        assert len(g_p.get("images") or []) >= 1
        assert len(g_p.get("materials") or []) >= 1
        assert "TANGENT" in g_p["meshes"][0]["primitives"][0]["attributes"]
        assert p["bbox"] == pytest.approx(qc.analisar(g_p, b_p)["bbox_m"], abs=1e-3)


def test_f06_segmentacao_rejeita_parte_invalida_e_pipeline_nao_cacheia_qc_reprovado(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from forge3d import pipeline, post, publish, qc, segmentacao
    from forge3d.errors import ForgeError

    in_glb = tmp_path / "in.glb"
    in_glb.write_bytes(b"glTF")
    monkeypatch.setattr(post, "binario", lambda: "blender")

    def _fake_subproc(cmd, **_kw):
        res_p = Path(cmd[cmd.index("--") + 2])
        out_p = Path(json.loads(Path(cmd[cmd.index("--") + 1]).read_text(encoding="utf-8"))["saida"])
        (out_p / "Head.glb").write_bytes(b"glTF")
        res_p.write_text(json.dumps({"partes": [{"nome": "Head", "junta": "Neck", "ancora": [0.0, 1.0, 0.0], "bbox": [0.2, 0.2, 0.2], "triangulos": 0, "arquivo": "Head.glb"}], "ancoras": {"Neck": [0.0, 1.0, 0.0]}}), encoding="utf-8")
        return type("_P", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(segmentacao.subprocess, "run", _fake_subproc)
    with pytest.raises(ForgeError) as exc:
        segmentacao.dividir(in_glb, {"id": "x", "partes": [{"nome": "Head"}]}, tmp_path / "seg_out")
    assert exc.value.codigo == "FORGE-E-QC"

    salvamentos: list[str] = []
    final_dir = tmp_path / "final"
    final_dir.mkdir()
    monkeypatch.setattr(pipeline.providers, "obter", lambda _r: type("_Prov", (), {"nome": "mesh", "versao": "1", "determinism": "D2", "usa_gpu": False, "licenca": {"modelo": "MIT", "uso_comercial": True, "notice": "MIT"}, "gerar": lambda self, _i, _p, d: type("_B", (), {"dir": d, "meta": {}})()})())
    monkeypatch.setattr(pipeline, "_pos_processar", lambda *_a, **_k: {"dir_final": str(final_dir), "arquivos": [{"caminho": "b.glb", "papel": "mesh", "sha256": "sha256:" + "0" * 64, "bytes": 10, "nivel": 0, "triangulos": 12}], "medidas": {}})
    monkeypatch.setattr(segmentacao, "dividir", lambda *_a, **_k: {"partes": [], "ancoras": {}, "arquivos": []})
    monkeypatch.setattr(qc, "verificar", lambda *_a, **_k: {"aprovado": False, "gates": [{"id": "G12", "status": "falhou"}], "medidas": {"triangulos": 12}})
    monkeypatch.setattr(publish, "salvar_cache", lambda k, *_a, **_k: salvamentos.append(k))
    with pytest.raises(ForgeError) as exc_qc:
        pipeline._executar_item({"id": "b1", "rota": "mesh", "partes": [{"nome": "Head"}], "rig": {"modo": "motor6d"}}, {"chave": "k"}, spec_doc={"projeto": "d", "perfil": "roblox-aa-80"}, perfil=profiles.carregar("roblox-aa-80"), spec_hash="sha256:" + "a" * 64, destino=tmp_path / "out", run_id="r", publicar_arquivos=False, no_cache=True)
    assert exc_qc.value.codigo == "FORGE-E-QC"
    assert salvamentos == []


def test_f06_segmentacao_valida_ancoras_topo_e_rejeita_invalida(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from forge3d import post, segmentacao
    from forge3d.errors import ForgeError
    from tests.test_red_r2_roblox import _box_glb

    in_glb = tmp_path / "in.glb"
    in_glb.write_bytes(_box_glb())
    monkeypatch.setattr(post, "binario", lambda: "blender")
    for bad_anc in ({"Neck": "not_a_vec3"}, {"Neck": [0.0, float("nan"), 0.0]}, {"Neck": [True, 0.0, 0.0]}):
        def _fake(cmd, _bad=bad_anc, **_kw):
            res_p = Path(cmd[cmd.index("--") + 2])
            out_p = Path(json.loads(Path(cmd[cmd.index("--") + 1]).read_text(encoding="utf-8"))["saida"])
            (out_p / "Head.glb").write_bytes(_box_glb())
            res_p.write_text(
                json.dumps({
                    "partes": [{"nome": "Head", "junta": "Neck", "ancora": [0.0, 1.0, 0.0], "bbox": [0.2, 0.2, 0.2], "triangulos": 12, "arquivo": "Head.glb"}],
                    "ancoras": _bad,
                }, allow_nan=True),
                encoding="utf-8",
            )
            return type("_P", (), {"returncode": 0, "stdout": "", "stderr": ""})()

        monkeypatch.setattr(segmentacao.subprocess, "run", _fake)
        with pytest.raises(ForgeError) as exc:
            segmentacao.dividir(in_glb, {"id": "anc.bad", "partes": [{"nome": "Head"}]}, tmp_path / "out")
        assert exc.value.codigo == "FORGE-E-QC"


@pytest.mark.blender
def test_f06_split_humanoide_15_partes_autorig_e_imagem_externa(tmp_path: Path) -> None:
    """F06: split real 15 partes com autorig (sem starvation de LowerTorso, nao_manifold=0, G12/G13 ok) e glTF com PNG externo."""
    import subprocess
    from forge3d import post, qc, segmentacao

    blender = post.binario()
    # 1) Imagem externa nao empacotada via .gltf + .png
    gltf_ext = tmp_path / "ext_scene.gltf"
    mk_ext = tmp_path / "mk_ext.py"
    mk_ext.write_text(
        "import bpy, bmesh, struct, json\n"
        "from pathlib import Path\n"
        "bpy.ops.wm.read_factory_settings(use_empty=True)\n"
        "arm_d = bpy.data.armatures.new('Arm'); arm = bpy.data.objects.new('Arm', arm_d)\n"
        "bpy.context.scene.collection.objects.link(arm); bpy.context.view_layer.objects.active = arm\n"
        "bpy.ops.object.mode_set(mode='EDIT')\n"
        "b = arm_d.edit_bones.new('Head'); b.head = (0,0,0); b.tail = (0,0,1)\n"
        "bpy.ops.object.mode_set(mode='OBJECT')\n"
        "bm = bmesh.new(); bmesh.ops.create_cube(bm, size=0.5)\n"
        "m = bpy.data.meshes.new('M'); bm.to_mesh(m); bm.free()\n"
        "obj = bpy.data.objects.new('M', m); bpy.context.scene.collection.objects.link(obj)\n"
        "uv = m.uv_layers.new(name='UVMap')\n"
        "for lp in m.loops: uv.data[lp.index].uv = (0.5, 0.5)\n"
        "obj.vertex_groups.new(name='Head').add(list(range(len(m.vertices))), 1.0, 'REPLACE')\n"
        "obj.parent = arm; obj.modifiers.new('Arm', 'ARMATURE').object = arm\n"
        # PNG minimo 2x2 externo
        "import zlib\n"
        "def _chunk(t, d): return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)\n"
        "png = b'\\x89PNG\\r\\n\\x1a\\n' + _chunk(b'IHDR', struct.pack('>IIBBBBB', 2, 2, 8, 6, 0, 0, 0)) + _chunk(b'IDAT', zlib.compress(b'\\x00' + b'\\xff\\x00\\x00\\xff'*2 + b'\\x00' + b'\\xff\\x00\\x00\\xff'*2)) + _chunk(b'IEND', b'')\n"
        f"tex_p = Path({str(tmp_path / 'ext_albedo.png')!r}); tex_p.write_bytes(png)\n"
        "img = bpy.data.images.load(str(tex_p))\n"
        "mat = bpy.data.materials.new('ExtMat'); mat.use_nodes = True; nt = mat.node_tree\n"
        "tc = nt.nodes.new('ShaderNodeTexImage'); tc.image = img; nt.links.new(tc.outputs['Color'], nt.nodes['Principled BSDF'].inputs['Base Color'])\n"
        "m.materials.append(mat)\n"
        f"bpy.ops.export_scene.gltf(filepath={str(gltf_ext)!r}, export_format='GLTF_SEPARATE', export_yup=True)\n",
        encoding="utf-8",
    )
    subprocess.run([blender, "--background", "--factory-startup", "--python-exit-code", "1", "--python", str(mk_ext)], check=True, capture_output=True)
    res_ext = segmentacao.dividir(gltf_ext, {"id": "ext.01", "partes": [{"nome": "Head", "junta": "Neck"}]}, tmp_path / "ext_out")
    g_ext, _ = qc.ler_glb_bin(tmp_path / "ext_out" / res_ext["partes"][0]["arquivo"])
    assert len(g_ext.get("images") or []) >= 1

    # 2) Humanoide conectado 15 ossos com voxel remesh + pesos mistos (sem LowerTorso dominante)
    hum_glb = tmp_path / "hum15.glb"
    mk_hum = tmp_path / "mk_hum.py"
    mk_hum.write_text(
        "import bpy, bmesh\nfrom mathutils import Vector\n"
        "bpy.ops.wm.read_factory_settings(use_empty=True)\n"
        "specs = [\n"
        " ('LowerTorso', (0,0,0.85), (0.30,0.20,0.22), (0,0,0.75), (0,0,0.95)),\n"
        " ('UpperTorso', (0,0,1.22), (0.36,0.22,0.44), (0,0,0.95), (0,0,1.45)),\n"
        " ('Head', (0,0,1.62), (0.22,0.22,0.28), (0,0,1.45), (0,0,1.80)),\n"
        " ('LeftUpperArm', (-0.30,0,1.28), (0.14,0.14,0.30), (-0.22,0,1.40), (-0.36,0,1.15)),\n"
        " ('LeftLowerArm', (-0.42,0,1.02), (0.12,0.12,0.26), (-0.36,0,1.15), (-0.48,0,0.90)),\n"
        " ('LeftHand', (-0.52,0,0.82), (0.10,0.10,0.14), (-0.48,0,0.90), (-0.55,0,0.75)),\n"
        " ('RightUpperArm', (0.30,0,1.28), (0.14,0.14,0.30), (0.22,0,1.40), (0.36,0,1.15)),\n"
        " ('RightLowerArm', (0.42,0,1.02), (0.12,0.12,0.26), (0.36,0,1.15), (0.48,0,0.90)),\n"
        " ('RightHand', (0.52,0,0.82), (0.10,0.10,0.14), (0.48,0,0.90), (0.55,0,0.75)),\n"
        " ('LeftUpperLeg', (-0.11,0,0.58), (0.15,0.15,0.38), (-0.11,0,0.78), (-0.11,0,0.40)),\n"
        " ('LeftLowerLeg', (-0.11,0,0.24), (0.13,0.13,0.32), (-0.11,0,0.40), (-0.11,0,0.08)),\n"
        " ('LeftFoot', (-0.11,-0.04,0.05), (0.13,0.22,0.10), (-0.11,0,0.08), (-0.11,-0.10,0.02)),\n"
        " ('RightUpperLeg', (0.11,0,0.58), (0.15,0.15,0.38), (0.11,0,0.78), (0.11,0,0.40)),\n"
        " ('RightLowerLeg', (0.11,0,0.24), (0.13,0.13,0.32), (0.11,0,0.40), (0.11,0,0.08)),\n"
        " ('RightFoot', (0.11,-0.04,0.05), (0.13,0.22,0.10), (0.11,0,0.08), (0.11,-0.10,0.02)),\n"
        "]\n"
        "bm = bmesh.new()\n"
        "for _n, c, sz, _h, _t in specs:\n"
        "    ret = bmesh.ops.create_cube(bm, size=1.0)\n"
        "    for v in ret['verts']: v.co = Vector((v.co.x*sz[0]+c[0], v.co.y*sz[1]+c[1], v.co.z*sz[2]+c[2]))\n"
        "m = bpy.data.meshes.new('H'); bm.to_mesh(m); bm.free()\n"
        "obj = bpy.data.objects.new('H', m); bpy.context.scene.collection.objects.link(obj)\n"
        "bpy.context.view_layer.objects.active = obj\n"
        "rm = obj.modifiers.new('R', 'REMESH'); rm.mode = 'VOXEL'; rm.voxel_size = 0.04\n"
        "bpy.ops.object.modifier_apply(modifier='R')\n"
        "arm_d = bpy.data.armatures.new('A'); arm = bpy.data.objects.new('A', arm_d)\n"
        "bpy.context.scene.collection.objects.link(arm); bpy.context.view_layer.objects.active = arm\n"
        "bpy.ops.object.mode_set(mode='EDIT')\n"
        "parents = {'UpperTorso':'LowerTorso','Head':'UpperTorso','LeftUpperArm':'UpperTorso','LeftLowerArm':'LeftUpperArm','LeftHand':'LeftLowerArm','RightUpperArm':'UpperTorso','RightLowerArm':'RightUpperArm','RightHand':'RightLowerArm','LeftUpperLeg':'LowerTorso','LeftLowerLeg':'LeftUpperLeg','LeftFoot':'LeftLowerLeg','RightUpperLeg':'LowerTorso','RightLowerLeg':'RightUpperLeg','RightFoot':'RightLowerLeg'}\n"
        "bones_map = {}\n"
        "for n, _c, _s, h, t in specs:\n"
        "    b = arm_d.edit_bones.new(n); b.head = h; b.tail = t; bones_map[n] = b\n"
        "for n, pn in parents.items(): bones_map[n].parent = bones_map[pn]\n"
        "bpy.ops.object.mode_set(mode='OBJECT')\n"
        "uv = obj.data.uv_layers.new(name='UVMap')\n"
        "for lp in obj.data.loops:\n"
        "    co = obj.data.vertices[lp.vertex_index].co; uv.data[lp.index].uv = (0.5+co.x*0.4, 0.1+co.z*0.4)\n"
        "def dseg(p, a, b):\n"
        "    ab = b - a; d2 = ab.length_squared\n"
        "    return (p - a).length if d2 < 1e-12 else (p - (a + ab * max(0.0, min(1.0, (p - a).dot(ab) / d2)))).length\n"
        "vgs = {n: obj.vertex_groups.new(name=n) for n, *_ in specs}\n"
        "segs_v = [(n, Vector(h), Vector(t)) for n, _c, _s, h, t in specs]\n"
        "for v in obj.data.vertices:\n"
        "    ds = sorted([(dseg(v.co, a, b), n) for n, a, b in segs_v])\n"
        "    best_n = ds[0][1]\n"
        "    if best_n == 'LowerTorso':\n"
        "        vgs['LowerTorso'].add([v.index], 0.35, 'REPLACE')\n"
        "        vgs['UpperTorso'].add([v.index], 0.65, 'REPLACE')\n"
        "    else:\n"
        "        vgs[best_n].add([v.index], 1.0, 'REPLACE')\n"
        "obj.parent = arm; obj.modifiers.new('A', 'ARMATURE').object = arm\n"
        f"bpy.ops.export_scene.gltf(filepath={str(hum_glb)!r}, export_format='GLB', export_yup=True)\n",
        encoding="utf-8",
    )
    subprocess.run([blender, "--background", "--factory-startup", "--python-exit-code", "1", "--python", str(mk_hum)], check=True, capture_output=True)
    partes_req = [{"nome": n} for n in ["LowerTorso", "UpperTorso", "Head", "LeftUpperArm", "LeftLowerArm", "LeftHand", "RightUpperArm", "RightLowerArm", "RightHand", "LeftUpperLeg", "LeftLowerLeg", "LeftFoot", "RightUpperLeg", "RightLowerLeg", "RightFoot"]]
    seg_dir = tmp_path / "hum_out"
    res = segmentacao.dividir(hum_glb, {"id": "hum.15", "partes": partes_req}, seg_dir)
    assert len(res["partes"]) == 15
    for p in res["partes"]:
        tp = qc.topologia(*qc.ler_glb_bin(seg_dir / p["arquivo"]))
        assert tp["nao_manifold"] == 0 and tp["bordas_abertas"] == 0 and tp["invertidas"] == 0, (p["nome"], tp)
    g12 = qc.verificar_g12_separacao({"partes": res["partes"], "rig": {"modo": "motor6d"}}, seg_dir, res, 1.0)
    assert g12["status"] == "ok", g12
    g_main, _ = qc.ler_glb_bin(hum_glb)
    g13 = qc.verificar_g13_ancoras({"partes": res["partes"], "rig": {"modo": "motor6d"}}, res, 1.0, gltf=g_main)
    assert g13["status"] == "ok", g13


@pytest.mark.blender
def test_f06_split_autorig_voxel_humanoide_sem_invertidas_e_verify_ok(tmp_path: Path) -> None:
    """F06: voxel remesh 0.04 conectado + autorig r15@1 -> dividir -> invertidas=0, G12/G13 ok e verify limpo."""
    import subprocess
    from forge3d import post, qc, segmentacao, verify
    from forge3d.canonical import sha256_arquivo

    blender = post.binario()
    hum_glb = tmp_path / "hum_autorig.glb"
    mk_auto = tmp_path / "mk_autorig.py"
    mk_auto.write_text(
        f"import sys\nsys.path.insert(0, {str(RAIZ / 'blender')!r})\n"
        "import bpy, bmesh\nfrom mathutils import Vector\nimport autorig, postprocess\n"
        "bpy.ops.wm.read_factory_settings(use_empty=True)\n"
        "boxes = [\n"
        " ((0,0,0.84), (0.32,0.20,0.34)), ((0,0,1.22), (0.36,0.22,0.44)), ((0,0,1.62), (0.22,0.22,0.28)),\n"
        " ((-0.45,0,1.34), (0.56,0.14,0.14)), ((0.45,0,1.34), (0.56,0.14,0.14)),\n"
        " ((-0.12,0,0.40), (0.14,0.14,0.80)), ((0.12,0,0.40), (0.14,0.14,0.80)),\n"
        " ((-0.12,-0.04,0.05), (0.14,0.22,0.10)), ((0.12,-0.04,0.05), (0.14,0.22,0.10)),\n"
        "]\n"
        "bm = bmesh.new()\n"
        "for c, sz in boxes:\n"
        "    ret = bmesh.ops.create_cube(bm, size=1.0)\n"
        "    for v in ret['verts']: v.co = Vector((v.co.x*sz[0]+c[0], v.co.y*sz[1]+c[1], v.co.z*sz[2]+c[2]))\n"
        "m = bpy.data.meshes.new('H'); bm.to_mesh(m); bm.free()\n"
        "obj = bpy.data.objects.new('H', m); bpy.context.scene.collection.objects.link(obj)\n"
        "bpy.context.view_layer.objects.active = obj\n"
        "rm = obj.modifiers.new('R', 'REMESH'); rm.mode = 'VOXEL'; rm.voxel_size = 0.04\n"
        "bpy.ops.object.modifier_apply(modifier='R')\n"
        "uv = obj.data.uv_layers.new(name='UVMap')\n"
        "for lp in obj.data.loops:\n"
        "    co = obj.data.vertices[lp.vertex_index].co; uv.data[lp.index].uv = (0.5+co.x*0.4, 0.1+co.z*0.4)\n"
        "autorig.auto_rigar_humanoide(obj, 'r15@1', postprocess.criar_armadura)\n"
        f"bpy.ops.export_scene.gltf(filepath={str(hum_glb)!r}, export_format='GLB', export_yup=True)\n",
        encoding="utf-8",
    )
    subprocess.run([blender, "--background", "--factory-startup", "--python-exit-code", "1", "--python", str(mk_auto)], check=True, capture_output=True)

    partes_req = [{"nome": n} for n in ["LowerTorso", "UpperTorso", "Head", "LeftUpperArm", "LeftLowerArm", "LeftHand", "RightUpperArm", "RightLowerArm", "RightHand", "LeftUpperLeg", "LeftLowerLeg", "LeftFoot", "RightUpperLeg", "RightLowerLeg", "RightFoot"]]
    seg_dir = tmp_path / "autorig_out"
    res = segmentacao.dividir(hum_glb, {"id": "hum.auto.15", "partes": partes_req}, seg_dir)
    assert len(res["partes"]) == 15
    for p in res["partes"]:
        tp = qc.topologia(*qc.ler_glb_bin(seg_dir / p["arquivo"]))
        assert tp["invertidas"] == 0 and tp["nao_manifold"] == 0 and tp["bordas_abertas"] == 0, (p["nome"], tp)
    g12 = qc.verificar_g12_separacao({"partes": res["partes"], "rig": {"modo": "motor6d"}}, seg_dir, res, 1.0)
    assert g12["status"] == "ok", g12
    g_main, _ = qc.ler_glb_bin(hum_glb)
    g13 = qc.verificar_g13_ancoras({"partes": res["partes"], "rig": {"modo": "motor6d"}}, res, 1.0, gltf=g_main)
    assert g13["status"] == "ok", g13
    man = {
        "files": [{"caminho": p["arquivo"], "papel": "parte", "sha256": sha256_arquivo(seg_dir / p["arquivo"]), "bytes": (seg_dir / p["arquivo"]).stat().st_size} for p in res["partes"]],
        "partes": res["partes"],
    }
    erros: list[dict] = []
    verify._validar_partes_manifesto(man, seg_dir, profiles.carregar("roblox-r15"), False, "hum.manifest.json", erros)
    assert erros == [], erros


def test_partes_malha_e_primitivas_resistem_accessor_nulo_e_ancora_invalida(tmp_path: Path) -> None:
    from forge3d import pipeline_report, qc_roblox
    from tests.test_red_r2_roblox import _box_glb
    from tests.test_seguranca_e_qc import _editar_gltf_glb

    acc_none = tmp_path / "Head.glb"
    acc_none.write_bytes(_editar_gltf_glb(_box_glb(), lambda g, _b: g.update({"accessors": [None]})))
    pm, err = qc_roblox._carregar_parte_malha({"nome": "Head", "arquivo": "Head.glb"}, tmp_path, 0.002)
    assert pm is None and err is not None and err.startswith("parte_ilegivel:")

    mesh_none = tmp_path / "BadMesh.glb"
    mesh_none.write_bytes(_editar_gltf_glb(_box_glb(), lambda g, _b: g.update({"meshes": [None]})))
    assert pipeline_report._contar_primitivas_glb(mesh_none) == 1

    ok_glb = tmp_path / "Ok.glb"
    ok_glb.write_bytes(_box_glb())
    for bad_anc in (["bad", 0.0, 0.0], [float("nan"), 0.0, 0.0]):
        pm_ok, err_ok = qc_roblox._carregar_parte_malha(
            {"nome": "Ok", "arquivo": "Ok.glb", "ancora": bad_anc, "pivo": "junta"}, tmp_path, 0.002
        )
        assert pm_ok is not None and err_ok is None


@pytest.mark.blender
def test_split_fechar_reverte_cascas_invertidas_e_limpa_sliver_menor_1e5(tmp_path: Path) -> None:
    import subprocess
    from forge3d import post, qc

    blender = post.binario()
    out_glb = tmp_path / "repaired.glb"
    sc = tmp_path / "check_fix.py"
    sc.write_text(
        f"import sys\nsys.path.insert(0, {str(RAIZ / 'blender')!r})\n"
        "import bpy, bmesh\nfrom mathutils import Vector\nimport split_por_ossos as spo\n"
        "bpy.ops.wm.read_factory_settings(use_empty=True)\n"
        "bm = bmesh.new()\n"
        "for dz in (-0.3, 0.3):\n"
        "    r = bmesh.ops.create_cube(bm, size=0.2)\n"
        "    for v in r['verts']: v.co += Vector((0, 0, dz))\n"
        "bmesh.ops.subdivide_edges(bm, edges=list(bm.edges), cuts=2, use_grid_fill=True)\n"
        "top_f = min((f for f in bm.faces if f.calc_center_median().z > 0.39), key=lambda f: f.calc_center_median().xy.length)\n"
        "vs = list(top_f.verts); bm.faces.remove(top_f)\n"
        "vs[3].co = vs[0].co + Vector((0, 4e-6, 0)); vs[2].co = vs[1].co + Vector((0, 4e-6, 0))\n"
        "bmesh.ops.reverse_faces(bm, faces=list(bm.faces))\n"
        "spo._fechar_e_triangular(bm, 'LowerTorso', Vector((0,0,0)), 0.0)\n"
        "m = bpy.data.meshes.new('R'); bm.to_mesh(m); bm.free()\n"
        "o = bpy.data.objects.new('R', m); bpy.context.scene.collection.objects.link(o)\n"
        f"bpy.ops.export_scene.gltf(filepath={str(out_glb)!r}, export_format='GLB', export_yup=True)\n",
        encoding="utf-8",
    )
    subprocess.run([blender, "--background", "--factory-startup", "--python-exit-code", "1", "--python", str(sc)], check=True, capture_output=True)
    tp = qc.topologia(*qc.ler_glb_bin(out_glb))
    assert tp["invertidas"] == 0 and tp["nao_manifold"] == 0 and tp["bordas_abertas"] == 0, tp
