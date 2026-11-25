"""Onda 8 (Godot 4) — Suite independente ('Sem Oraculo Comprado') derivada do contrato congelado."""

from __future__ import annotations

import configparser
import json
import os
import shutil
import struct
import subprocess
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from forge3d import animacao, config, post, profiles, publish, sync, sync_godot, sync_godot_sidecars
from forge3d.canonical import sha256_arquivo

RAIZ = Path(__file__).resolve().parents[1]
_REAL_HOME = Path.home()
PLUGIN_CFG = RAIZ / "addons" / "forge3d" / "plugin.cfg"
POST_IMPORT_GD = RAIZ / "addons" / "forge3d" / "post_import.gd"
GODOT_PROJ = RAIZ / "tools" / "godot_project"
ANIM_CHECK_GD = RAIZ / "tools" / "godot_anim_check.gd"
VISUAL_QA_GD = RAIZ / "tools" / "godot_visual_qa.gd"

CLIPES_CICLICOS_8: tuple[str, ...] = ("idle", "walk", "run", "ride_idle", "ride_fly", "gallop", "wing_flap", "glide")
CLIPES_NAO_CICLICOS_14: tuple[str, ...] = (
    "jump", "attack", "slash_combo", "cast", "block", "hit", "death",
    "bite", "roar", "tail_swipe", "land", "rear_up", "mount_up", "dismount",
)


@pytest.fixture(autouse=True)
def _isolar_forge3d(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORGE3D_HOME", str(tmp_path / "forge_home"))
    monkeypatch.setenv("FORGE3D_CONFIG", str(tmp_path / "forge_cfg"))
    config.adicionar(tmp_path)


def _exigir_godot() -> str:
    env_g = os.environ.get("FORGE3D_GODOT")
    if env_g and Path(env_g).is_file():
        return env_g
    if achado := shutil.which("godot"):
        return achado
    for base in (Path.home(), _REAL_HOME):
        cand = base / ".gemini" / "antigravity" / "bin" / "godot"
        if cand.is_file():
            return str(cand)
    pytest.skip("Godot 4 headless nao disponivel neste host")


def _exigir_blender() -> str:
    try:
        ok, _ = post.preflight()
        blender = post.binario() if ok else None
    except Exception:
        blender = None
    if not blender:
        pytest.skip("Blender 4.2 nao disponivel neste host")
    return blender


def _rodar_godot(godot: str, args: list[str], tmp_path: Path) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    for sub in ("data", "config", "cache"):
        d = tmp_path / "_godot_xdg" / sub
        d.mkdir(parents=True, exist_ok=True)
        env[f"XDG_{sub.upper()}_HOME"] = str(d)
    return subprocess.run([godot, "--headless", "--path", str(GODOT_PROJ), *args], env=env, capture_output=True, text=True, timeout=90, check=False)


def _salvar_png(caminho: Path, cor: tuple[int, int, int], tamanho: int = 32) -> Path:
    Image.new("RGB", (tamanho, tamanho), cor).save(caminho, format="PNG")
    return caminho


def _ler_params_import(caminho_import: Path) -> dict[str, str]:
    secao, params = "", {}
    for raw in caminho_import.read_text(encoding="utf-8").splitlines():
        linha = raw.strip()
        if linha.startswith("[") and linha.endswith("]"):
            secao = linha[1:-1].strip()
        elif secao == "params" and "=" in linha and not linha.startswith(";"):
            k, v = linha.split("=", 1)
            params[k.strip()] = v.strip()
    return params


def _construir_glb_box(caminho: Path, *, nome: str = "AssetOnda8", com_rig_e_clipes: tuple[str, ...] = ()) -> bytes:
    faces = [
        ([(-0.5, 0.0, 0.5), (0.5, 0.0, 0.5), (0.5, 1.0, 0.5), (-0.5, 1.0, 0.5)], (0.0, 0.0, 1.0)),
        ([(0.5, 0.0, -0.5), (-0.5, 0.0, -0.5), (-0.5, 1.0, -0.5), (0.5, 1.0, -0.5)], (0.0, 0.0, -1.0)),
        ([(-0.5, 1.0, 0.5), (0.5, 1.0, 0.5), (0.5, 1.0, -0.5), (-0.5, 1.0, -0.5)], (0.0, 1.0, 0.0)),
        ([(-0.5, 0.0, -0.5), (0.5, 0.0, -0.5), (0.5, 0.0, 0.5), (-0.5, 0.0, 0.5)], (0.0, -1.0, 0.0)),
        ([(0.5, 0.0, 0.5), (0.5, 0.0, -0.5), (0.5, 1.0, -0.5), (0.5, 1.0, 0.5)], (1.0, 0.0, 0.0)),
        ([(-0.5, 0.0, -0.5), (-0.5, 0.0, 0.5), (-0.5, 1.0, 0.5), (-0.5, 1.0, -0.5)], (-1.0, 0.0, 0.0)),
    ]
    verts = [p for quad, _ in faces for p in quad]
    norms = [nrm for _, nrm in faces for _ in range(4)]
    tris = [t for k in range(6) for t in ((4 * k, 4 * k + 1, 4 * k + 2), (4 * k, 4 * k + 2, 4 * k + 3))]
    uvs = [uv for k in range(6) for cu, cv in [(0.05 + (k % 3) * 0.3, 0.05 + (k // 3) * 0.45)] for uv in ((cu + 0.02, cv + 0.02), (cu + 0.28, cv + 0.02), (cu + 0.28, cv + 0.43), (cu + 0.02, cv + 0.43))]
    dados, views, accs = bytearray(), [], []

    def add_view(blob: bytes, target: int | None = None) -> int:
        dados.extend(b"\x00" * ((-len(dados)) % 4))
        off = len(dados)
        dados.extend(blob)
        views.append({"buffer": 0, "byteOffset": off, "byteLength": len(blob), **({"target": target} if target else {})})
        return len(views) - 1

    accs.extend([
        {"bufferView": add_view(b"".join(struct.pack("<3f", *p) for p in verts), 34962), "componentType": 5126, "count": 24, "type": "VEC3", "min": [-0.5, 0.0, -0.5], "max": [0.5, 1.0, 0.5]},
        {"bufferView": add_view(b"".join(struct.pack("<3f", *n) for n in norms), 34962), "componentType": 5126, "count": 24, "type": "VEC3"},
        {"bufferView": add_view(b"".join(struct.pack("<2f", *u) for u in uvs), 34962), "componentType": 5126, "count": 24, "type": "VEC2"},
        {"bufferView": add_view(b"".join(struct.pack("<4f", 1.0, 0.0, 0.0, 1.0) for _ in verts), 34962), "componentType": 5126, "count": 24, "type": "VEC4"},
        {"bufferView": add_view(b"".join(struct.pack("<3H", *t) for t in tris), 34963), "componentType": 5123, "count": 36, "type": "SCALAR"},
    ])
    attrs: dict[str, int] = {"POSITION": 0, "NORMAL": 1, "TEXCOORD_0": 2, "TANGENT": 3}
    nodes: list[dict[str, Any]] = [{"name": nome, "mesh": 0}]
    gltf: dict[str, Any] = {
        "asset": {"version": "2.0", "generator": "forge3d-onda8-test"}, "scene": 0, "scenes": [{"nodes": [0]}], "nodes": nodes,
        "meshes": [{"name": nome, "primitives": [{"attributes": attrs, "indices": 4, "material": 0}]}],
        "materials": [{"name": "MatBase", "pbrMetallicRoughness": {"baseColorFactor": [0.7, 0.75, 0.8, 1.0], "metallicFactor": 0.0, "roughnessFactor": 0.65}}],
        "accessors": accs, "bufferViews": views,
    }
    if com_rig_e_clipes:
        ident = (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0)
        rots = [(0.0, 0.0, 0.0, 1.0), (0.0, 0.18, 0.0, 0.983666), (0.0, 0.0, 0.0, 1.0)]
        accs.extend([
            {"bufferView": add_view(b"".join(struct.pack("<4B", 1, 0, 0, 0) for _ in verts), 34962), "componentType": 5121, "count": 24, "type": "VEC4"},
            {"bufferView": add_view(b"".join(struct.pack("<4f", 1.0, 0.0, 0.0, 0.0) for _ in verts), 34962), "componentType": 5126, "count": 24, "type": "VEC4"},
            {"bufferView": add_view(struct.pack("<16f", *ident) * 4), "componentType": 5126, "count": 4, "type": "MAT4"},
            {"bufferView": add_view(struct.pack("<3f", 0.0, 1.0, 2.0)), "componentType": 5126, "count": 3, "type": "SCALAR", "min": [0.0], "max": [2.0]},
            {"bufferView": add_view(b"".join(struct.pack("<4f", *q) for q in rots)), "componentType": 5126, "count": 3, "type": "VEC4"},
        ])
        attrs.update({"JOINTS_0": 5, "WEIGHTS_0": 6})
        nodes.extend([{"name": "Root", "children": [2]}, {"name": "Hips", "translation": [0.0, 0.9, 0.0], "children": [3]}, {"name": "Chest", "translation": [0.0, 0.35, 0.0], "children": [4]}, {"name": "Head", "translation": [0.0, 0.35, -0.4]}])
        gltf["scenes"][0]["nodes"] = [0, 1]
        nodes[0]["skin"] = 0
        gltf["skins"] = [{"joints": [1, 2, 3, 4], "skeleton": 1, "inverseBindMatrices": 7}]
        gltf["animations"] = [{"name": c, "samplers": [{"input": 8, "output": 9, "interpolation": "LINEAR"}], "channels": [{"sampler": 0, "target": {"node": 2, "path": "rotation"}}]} for c in com_rig_e_clipes]

    gltf["buffers"] = [{"byteLength": len(dados)}]
    jb = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    jb += b" " * ((-len(jb)) % 4)
    bb = bytes(dados) + b"\x00" * ((-len(dados)) % 4)
    raw = struct.pack("<3I", 0x46546C67, 2, 28 + len(jb) + len(bb)) + struct.pack("<2I", len(jb), 0x4E4F534A) + jb + struct.pack("<2I", len(bb), 0x004E4942) + bb
    caminho.write_bytes(raw)
    return raw


def test_plugin_cfg_declares_version_0_8_0() -> None:
    texto = PLUGIN_CFG.read_text(encoding="utf-8")
    assert 'version="0.8.0"' in texto, f"plugin.cfg nao declara version=\"0.8.0\":\n{texto}"
    cp = configparser.ConfigParser()
    cp.read_string(texto)
    assert cp.get("plugin", "version").strip('"') == "0.8.0" and cp.get("plugin", "script").strip('"') == "plugin.gd"


def test_sync_godot_emissive_papel_textura_and_emissive(tmp_path: Path) -> None:
    asset_id = "prop.crystal.pylon.01"
    staging, origem = tmp_path / "staging", tmp_path / "publicado"
    staging.mkdir(parents=True)
    glb_bytes = _construir_glb_box(staging / f"{asset_id}.glb", nome=asset_id)
    arquivos = [{"caminho": f"{asset_id}.glb", "papel": "mesh", "sha256": sha256_arquivo(staging / f"{asset_id}.glb"), "bytes": len(glb_bytes)}]
    for suf, papel, cor in (("emissive", "textura", (24, 210, 255)), ("baseColor", "textura", (70, 80, 100)), ("normal", "normal", (128, 128, 255)), ("orm", "orm", (255, 165, 0))):
        p = _salvar_png(staging / f"{asset_id}_{suf}.png", cor)
        arquivos.append({"caminho": p.name, "papel": papel, "sha256": sha256_arquivo(p), "bytes": p.stat().st_size})

    man_v7 = {
        "schema": "forge3d/manifest@7", "asset_id": asset_id, "projeto": "onda8_demo", "perfil": "godot4-aa",
        "tipo": "prop_estatico", "rota": "mesh", "tags": ["onda8"], "spec_hash": "sha256:" + "b" * 64,
        "pipeline_version": "0.9.11", "determinism": "D2",
        "providers": {"geometry": {"name": "mesh", "version": "0.1.12", "license": "MIT", "seed": 7}},
        "geometry": {"triangulos": 12, "vertices": 24, "bbox_m": [1.0, 1.0, 1.0], "materiais": 1, "tangentes": True},
        "unidades_export": {"metros_por_unidade": 1.0, "escala_saida": 1.0}, "animacoes": [], "rig": None,
        "lod": [{"nivel": 0, "triangulos": 12, "arquivo": f"{asset_id}.glb"}], "colisao": {"tipo": "none", "partes": 0}, "files": arquivos,
        "qc": {"aprovado": True, "gates": [{"id": "G2", "status": "ok", "medido": {"esperado_m": 1.0, "pivo_regra": "base"}}, {"id": "G9", "status": "ok", "medido": {"triangulos": 12, "limite": 5000}}]},
        "licenca": {"modelo": "MIT", "uso_comercial": True, "notice": "onda8"}, "run_id": "run-onda8-sync", "created_at": "2026-11-25T00:00:00Z",
    }
    publish.publicar(staging, origem, man_v7, "run-onda8-sync")

    proj, destino_assets = tmp_path / "godot_proj", tmp_path / "godot_proj" / "assets" / "props"
    destino_assets.mkdir(parents=True)
    (proj / "project.godot").write_text('[application]\nconfig/name="Onda8"\n', encoding="utf-8")
    gd_out = proj / "Forge3DAssets.gd"
    rel = sync.executar(origem, destino_assets, limpar=True, godot_gd=gd_out)
    assert rel["ok"] is True and (destino_assets / f"{asset_id}_emissive.png.import").is_file()
    gd_txt = gd_out.read_text(encoding="utf-8")
    assert f'"emissive": "res://assets/props/{asset_id}_emissive.png"' in gd_txt, gd_txt
    assert f'"baseColor": "res://assets/props/{asset_id}_baseColor.png"' in gd_txt, gd_txt

    res_exp = sync_godot.gerar_assets_gd(
        {"asset_id": asset_id, "perfil": "godot4-aa", "files": [{"caminho": f"{asset_id}.glb", "papel": "mesh"}, {"caminho": f"{asset_id}_baseColor.png", "papel": "textura"}, {"caminho": f"{asset_id}_emissive.png", "papel": "emissive"}]},
        tmp_path / "Forge3DAssetsExplicit.gd", res_prefix="res://assets/props",
    )
    tex_map = res_exp["assets"][asset_id]["textures"]
    assert tex_map.get("emissive") == f"res://assets/props/{asset_id}_emissive.png"
    assert tex_map.get("baseColor") == f"res://assets/props/{asset_id}_baseColor.png"


def test_sidecars_glb_subresources_bonemap_fix_silhouette_and_22_clips(tmp_path: Path) -> None:
    assert len(CLIPES_CICLICOS_8) == 8 and len(CLIPES_NAO_CICLICOS_14) == 14 and not (set(CLIPES_CICLICOS_8) & set(CLIPES_NAO_CICLICOS_14))
    for c in CLIPES_CICLICOS_8:
        assert sync_godot_sidecars._eh_clipe_ciclico(c) is True and sync_godot_sidecars._eh_clipe_ciclico(f"Armature|{c}") is True
    for nc in CLIPES_NAO_CICLICOS_14:
        assert sync_godot_sidecars._eh_clipe_ciclico(nc) is False and sync_godot_sidecars._eh_clipe_ciclico(f"Armature|{nc}") is False

    todos_22 = [*CLIPES_CICLICOS_8, *CLIPES_NAO_CICLICOS_14]
    for esq in ("godot-humanoid@1", "godot-humanoid-aa@1"):
        man = {"rig": {"esqueleto": esq, "ossos": 56 if "aa" in esq else 23}, "animacoes": [{"nome": n, "duracao_s": 1.5} for n in todos_22]}
        sub = sync_godot_sidecars._construir_subresources_glb(man)
        skel_cfg = sub["nodes"]["PATH:Skeleton3D"]
        assert skel_cfg.get("retarget/rest_fixer/fix_silhouette/enable") is True
        bm_expr = getattr(skel_cfg.get("retarget/bone_map"), "expr", str(skel_cfg.get("retarget/bone_map")))
        assert "Object(BoneMap," in bm_expr and "SkeletonProfileHumanoid" in bm_expr and '"bone_map/Chest":' in bm_expr and '"bone_map/UpperChest":' in bm_expr
        for c in CLIPES_CICLICOS_8:
            assert sub["animations"][c] == {"settings/loop_mode": 1}
        for nc in CLIPES_NAO_CICLICOS_14:
            assert sub["animations"][nc] == {"settings/loop_mode": 0}
        glb_dummy = tmp_path / f"hero_{esq.replace('@', '_')}.glb"
        glb_dummy.write_bytes(b"glTF")
        sync_godot_sidecars.aplicar_sidecars_godot(glb_dummy, "test", manifesto=man)
        assert '"retarget/rest_fixer/fix_silhouette/enable": true' in Path(f"{glb_dummy}.import").read_text(encoding="utf-8")


def test_sidecars_png_import_distinguishes_normal_linear_and_srgb(tmp_path: Path) -> None:
    por_sufixo: dict[str, dict[str, str]] = {}
    for suf in ("_normal.png", "_orm.png", "_roughness.png", "_metalness.png", "_ao.png", "_emissive.png", "_baseColor.png"):
        png = _salvar_png(tmp_path / f"hero{suf}", (128, 128, 128))
        sync_godot_sidecars.aplicar_sidecars_godot(png, "onda8")
        por_sufixo[suf] = _ler_params_import(Path(f"{png}.import"))

    assert por_sufixo["_normal.png"].get("compress/normal_map") == "1"
    for lin in ("_orm.png", "_roughness.png", "_metalness.png", "_ao.png"):
        assert por_sufixo[lin].get("compress/normal_map") == "0" and por_sufixo[lin].get("process/hdr_as_srgb") == "false", (lin, por_sufixo[lin])
    for srgb in ("_emissive.png", "_baseColor.png"):
        assert por_sufixo[srgb].get("compress/normal_map") == "0" and por_sufixo[srgb].get("compress/mode") == "2", (srgb, por_sufixo[srgb])
        assert por_sufixo[srgb] != por_sufixo["_orm.png"] and por_sufixo[srgb] != por_sufixo["_normal.png"]


def test_godot_post_import_emissive_sidecar_and_visual_qa(tmp_path: Path) -> None:
    godot = _exigir_godot()
    asset_id = "prop.arcane.lantern.01"
    glb = tmp_path / f"{asset_id}.glb"
    _construir_glb_box(glb, nome=asset_id)
    for suf, cor in (("emissive", (32, 220, 255)), ("baseColor", (55, 65, 85)), ("orm", (255, 170, 0)), ("normal", (128, 128, 255))):
        _salvar_png(tmp_path / f"{asset_id}_{suf}.png", cor)
    (tmp_path / f"{asset_id}.manifest.json").write_text(json.dumps({
        "schema": "forge3d/manifest@7", "asset_id": asset_id, "tipo": "prop_estatico", "rota": "mesh", "perfil": "godot4-aa",
        "files": [{"caminho": f"{asset_id}.glb", "papel": "mesh"}, {"caminho": f"{asset_id}_emissive.png", "papel": "textura"}, {"caminho": f"{asset_id}_baseColor.png", "papel": "textura"}, {"caminho": f"{asset_id}_orm.png", "papel": "orm"}, {"caminho": f"{asset_id}_normal.png", "papel": "normal"}],
    }), encoding="utf-8")

    script = tmp_path / "check_emissive_sidecar.gd"
    script.write_text(f"""extends SceneTree
const PostImport := preload({str(POST_IMPORT_GD)!r})
func _fail(msg: String, n: Node = null) -> void:
\tprinterr("EMISSIVE_FAIL: " + msg); if n != null: n.free()
\tquit(1)
func _initialize() -> void:
\tvar doc := GLTFDocument.new(); var st := GLTFState.new()
\tif doc.append_from_file({str(glb)!r}, st) != OK: _fail("append_from_file falhou"); return
\tvar cena := doc.generate_scene(st)
\tPostImport.aplicar(cena, {str(glb)!r})
\tvar mat := (cena.find_children("*", "MeshInstance3D", true, false)[0] as MeshInstance3D).mesh.surface_get_material(0)
\tif not (mat is ORMMaterial3D): _fail("material nao e ORMMaterial3D", cena); return
\tvar orm := mat as ORMMaterial3D
\tif not orm.emission_enabled or orm.emission_texture == null: _fail("emission ausente", cena); return
\tif not is_equal_approx(orm.metallic, 1.0) or not is_equal_approx(orm.roughness, 1.0): _fail("m/r != 1.0", cena); return
\tif orm.albedo_texture == null or orm.albedo_texture == orm.emission_texture: _fail("albedo confundido", cena); return
\tcena.free(); print("EMISSIVE_SIDECAR_OK"); quit(0)
""", encoding="utf-8")
    proc = _rodar_godot(godot, ["--script", str(script)], tmp_path)
    assert proc.returncode == 0 and "EMISSIVE_SIDECAR_OK" in proc.stdout, proc.stdout + proc.stderr
    qa = _rodar_godot(godot, ["--script", str(VISUAL_QA_GD), "--", str(glb)], tmp_path)
    assert qa.returncode == 0 and "GODOT_VISUAL_QA_OK" in qa.stdout, qa.stdout + qa.stderr


def test_godot_processar_material_5_args_backward_compat(tmp_path: Path) -> None:
    godot = _exigir_godot()
    script = tmp_path / "check_mat_5args.gd"
    script.write_text(f"""extends SceneTree
const PostImport := preload({str(POST_IMPORT_GD)!r})
func _tex(c: Color) -> ImageTexture:
\tvar img := Image.create(8, 8, false, Image.FORMAT_RGBA8); img.fill(c)
\treturn ImageTexture.create_from_image(img)
func _novo_src(emb: Texture2D) -> StandardMaterial3D:
\tvar s := StandardMaterial3D.new(); s.emission_enabled = true; s.emission = Color(0.2, 0.9, 1.0); s.emission_texture = emb
\treturn s
func _initialize() -> void:
\tvar orm := _tex(Color(1.0, 0.65, 0.0)); var emb1 := _tex(Color(0.1, 0.8, 1.0))
\tvar out5 := PostImport._processar_material(_novo_src(emb1), orm, null, null, false)
\tif not (out5 is ORMMaterial3D): printerr("out5 nao e ORMMaterial3D"); quit(1); return
\tvar m5 := out5 as ORMMaterial3D
\tif not m5.emission_enabled or m5.emission_texture != emb1 or not is_equal_approx(m5.metallic, 1.0) or not is_equal_approx(m5.roughness, 1.0):
\t\tprinterr("5-args invalido"); quit(1); return
\tvar aceita_6 := false
\tfor m in (PostImport as Script).get_script_method_list():
\t\tif str(m.get("name", "")) == "_processar_material" and (m.get("args", []) as Array).size() >= 6: aceita_6 = true
\tif not aceita_6: printerr("_processar_material nao expoe 6o parametro opcional"); quit(1); return
\tvar emb2 := _tex(Color(1.0, 0.4, 0.1))
\tvar m6 := (PostImport as Object).call("_processar_material", _novo_src(emb2), orm, null, null, false, null) as ORMMaterial3D
\tif m6 == null or not m6.emission_enabled or m6.emission_texture != emb2: printerr("6o arg null perdeu emission"); quit(1); return
\tprint("MAT_BACKCOMPAT_OK"); quit(0)
""", encoding="utf-8")
    proc = _rodar_godot(godot, ["--script", str(script)], tmp_path)
    assert proc.returncode == 0 and "MAT_BACKCOMPAT_OK" in proc.stdout, proc.stdout + proc.stderr


def test_godot_22_clips_anim_check_and_visual_qa(tmp_path: Path) -> None:
    godot = _exigir_godot()
    asset_id = "mount.drake.qa.01"
    glb = tmp_path / f"{asset_id}.glb"
    clipes_22 = (*CLIPES_CICLICOS_8, *CLIPES_NAO_CICLICOS_14)
    _construir_glb_box(glb, nome=asset_id, com_rig_e_clipes=clipes_22)
    man = {"schema": "forge3d/manifest@7", "asset_id": asset_id, "tipo": "criatura", "rota": "blocky", "perfil": "godot4", "rig": {"esqueleto": "quadruped@1", "ossos": 4}, "animacoes": [{"nome": c, "duracao_s": 2.0, "ossos": ["Hips"]} for c in clipes_22]}
    (tmp_path / f"{asset_id}.manifest.json").write_text(json.dumps(man), encoding="utf-8")
    sync_godot_sidecars.aplicar_sidecars_godot(glb, "onda8-22", manifesto=man)

    script = tmp_path / "check_22_loops.gd"
    script.write_text(f"""extends SceneTree
const PostImport := preload({str(POST_IMPORT_GD)!r})
func _initialize() -> void:
\tvar doc := GLTFDocument.new(); var st := GLTFState.new()
\tif doc.append_from_file({str(glb)!r}, st) != OK: quit(1); return
\tvar cena := doc.generate_scene(st)
\tPostImport.aplicar(cena, {str(glb)!r})
\tvar ap := cena.find_children("*", "AnimationPlayer", true, false)[0] as AnimationPlayer
\tfor c in {json.dumps(list(CLIPES_CICLICOS_8))}:
\t\tif not ap.has_animation(c) or ap.get_animation(c).loop_mode != Animation.LOOP_LINEAR: cena.free(); quit(1); return
\tfor nc in {json.dumps(list(CLIPES_NAO_CICLICOS_14))}:
\t\tif not ap.has_animation(nc) or ap.get_animation(nc).loop_mode != Animation.LOOP_NONE: cena.free(); quit(1); return
\tcena.free(); print("LOOPS_22_OK"); quit(0)
""", encoding="utf-8")
    res_loops = _rodar_godot(godot, ["--script", str(script)], tmp_path)
    assert res_loops.returncode == 0 and "LOOPS_22_OK" in res_loops.stdout, res_loops.stdout + res_loops.stderr
    for alvo in ("idle", "ride_fly", "tail_swipe", "dismount"):
        ac = _rodar_godot(godot, ["--script", str(ANIM_CHECK_GD), "--", str(glb), alvo], tmp_path)
        assert ac.returncode == 0 and "GODOT_ANIM_OK" in ac.stdout, f"{alvo}:\n{ac.stdout}\n{ac.stderr}"
    qa = _rodar_godot(godot, ["--script", str(VISUAL_QA_GD), "--", str(glb)], tmp_path)
    assert qa.returncode == 0 and "GODOT_VISUAL_QA_OK" in qa.stdout, qa.stdout + qa.stderr


_BLENDER_E2E_SCRIPT = r"""
import json, math, sys, bpy, bmesh
from mathutils import Vector

cfg = json.loads(open(sys.argv[-1], encoding="utf-8").read())
sys.path.insert(0, cfg["blender_dir"])
import autorig, postprocess, postprocess_export_pipe as pep
from postprocess_lod_col import exportar
from postprocess_normals_uv import suavizar_por_angulo

bpy.ops.wm.read_factory_settings(use_empty=True)
bm = bmesh.new()
def box(c, sz):
    for v in bmesh.ops.create_cube(bm, size=1.0)["verts"]:
        v.co = Vector((v.co.x * sz[0] + c[0], v.co.y * sz[1] + c[1], v.co.z * sz[2] + c[2]))
def seg(p0, p1, w, d):
    p0, p1 = Vector(p0), Vector(p1)
    q, mid, ln = (p1 - p0).normalized().to_track_quat("Z", "Y"), (p0 + p1) * 0.5, (p1 - p0).length
    for v in bmesh.ops.create_cube(bm, size=1.0)["verts"]:
        v.co = q @ Vector((v.co.x * w, v.co.y * d, v.co.z * ln)) + mid

box((0, 0, 0.98), (0.54, 0.24, 0.20)); box((0, 0, 1.12), (0.40, 0.22, 0.16)); box((0, 0, 1.40), (0.50, 0.26, 0.40))
box((0, 0, 1.66), (0.12, 0.12, 0.12)); box((0, 0, 1.80), (0.22, 0.22, 0.28))
aa = math.radians(45.0)
for s in (1.0, -1.0):
    box((s * 0.16, 0.04, 0.05), (0.14, 0.26, 0.10))
    seg((s * 0.16, 0, 0.10), (s * 0.16, 0, 0.50), 0.13, 0.13); seg((s * 0.16, 0, 0.46), (s * 0.16, 0, 0.96), 0.17, 0.17)
    sh, dfa = Vector((s * 0.30, 0, 1.55)), Vector((s * math.sin(aa), 0, -math.cos(aa)))
    el, wr = sh + dfa * 0.34, sh + dfa * 0.64
    box((s * 0.33, 0, 1.50), (0.18, 0.20, 0.20)); seg(sh, el, 0.12, 0.12); seg(el, wr, 0.10, 0.10); seg(wr, wr + dfa * 0.12, 0.09, 0.05)

me = bpy.data.meshes.new("HeroGodotAA"); bm.to_mesh(me); bm.free()
obj = bpy.data.objects.new("HeroGodotAA", me); bpy.context.collection.objects.link(obj)
bpy.context.view_layer.objects.active = obj; obj.select_set(True)
mod = obj.modifiers.new("VoxelWeld", "REMESH"); mod.mode = "VOXEL"; mod.voxel_size = 0.042
bpy.ops.object.modifier_apply(modifier=mod.name)
postprocess.reparar_malha(obj); suavizar_por_angulo(obj, angulo_graus=65.0)

mat = bpy.data.materials.new("HeroMat"); mat.use_nodes = True
bsdf = mat.node_tree.nodes.get("Principled BSDF")
if bsdf is not None:
    bsdf.inputs["Base Color"].default_value = (0.55, 0.60, 0.68, 1.0)
    bsdf.inputs["Metallic"].default_value, bsdf.inputs["Roughness"].default_value = 0.0, 0.65
obj.data.materials.append(mat)

def arm_thetas(rig):
    out = {}
    for lado in ("L", "R"):
        h, t = rig.matrix_world @ rig.data.bones[f"UpperArm.{lado}"].head_local, rig.matrix_world @ rig.data.bones[f"LowerArm.{lado}"].head_local
        out[lado] = math.degrees(math.atan2(abs(t.x - h.x), max(h.z - t.z, 1e-6)))
    return out

rig_obj, grupos = autorig.auto_rigar_humanoide(obj, "godot-humanoid-aa@1", postprocess.criar_armadura)
theta_antes, info_gerada = arm_thetas(rig_obj), {}
anims, sockets = pep._pos_escala_rig_e_animacao(
    obj, rig_obj, grupos, {"clipes": cfg["clipes"], "seed": 42}, {"rota": "mesh", "seed": 42},
    {}, 1.0, False, True, 65.0, False, info_gerada, pular_reparo_pos_escala=True, perfil=cfg["perfil"], saida_dir=cfg["saida_dir"],
)
exportar(cfg["out_glb"], [obj, rig_obj], True, com_animacao=True, export_tangents=False, export_image_format="AUTO")
open(cfg["out_json"], "w", encoding="utf-8").write(json.dumps({"ossos": len(rig_obj.data.bones), "theta_antes": theta_antes, "theta_depois": arm_thetas(rig_obj), "pose_natural": info_gerada.get("pose_natural"), "animacoes": anims, "sockets": sockets}, default=str))
"""


@pytest.mark.blender
def test_cross_engine_e2e_blender_onda7_to_godot4_aa(tmp_path: Path) -> None:
    blender, godot = _exigir_blender(), _exigir_godot()
    perfil_aa = profiles.carregar("godot4-aa")
    clipes_aa = animacao.clipes(perfil_aa, "godot-humanoid-aa@1", ["idle", "walk", "run"], seed=42)
    asset_id = "hero.onda8.aa.01"
    glb, out_json, cfg_json, script_py = tmp_path / f"{asset_id}.glb", tmp_path / "out.json", tmp_path / "cfg.json", tmp_path / "e2e.py"
    cfg_json.write_text(json.dumps({"blender_dir": str(RAIZ / "blender"), "saida_dir": str(tmp_path), "out_glb": str(glb), "out_json": str(out_json), "perfil": perfil_aa, "clipes": clipes_aa}, default=str), encoding="utf-8")
    script_py.write_text(_BLENDER_E2E_SCRIPT, encoding="utf-8")
    proc_bl = subprocess.run([blender, "--background", "--factory-startup", "--python-exit-code", "1", "--python", str(script_py), "--", str(cfg_json)], capture_output=True, text=True, timeout=300, check=False)
    assert proc_bl.returncode == 0, proc_bl.stdout[-2500:] + "\n" + proc_bl.stderr[-2500:]

    res_bl = json.loads(out_json.read_text(encoding="utf-8"))
    assert res_bl["ossos"] == 56 and not (res_bl.get("pose_natural") or {}).get("aplicado")
    for lado in ("L", "R"):
        assert 40.0 <= res_bl["theta_depois"][lado] <= 50.0 and abs(res_bl["theta_depois"][lado] - res_bl["theta_antes"][lado]) <= 0.5
    assert {"Hand.R", "Hand.L", "Back", "Head"}.issubset({s["nome"] for s in res_bl["sockets"]})

    man = {"schema": "forge3d/manifest@7", "asset_id": asset_id, "tipo": "personagem_humanoide", "rota": "mesh", "perfil": "godot4-aa", "rig": {"esqueleto": "godot-humanoid-aa@1", "ossos": 56}, "animacoes": res_bl["animacoes"], "sockets": res_bl["sockets"]}
    (tmp_path / f"{asset_id}.manifest.json").write_text(json.dumps(man), encoding="utf-8")
    sync_godot_sidecars.aplicar_sidecars_godot(glb, "onda8-e2e", manifesto=man)
    glb_import = Path(f"{glb}.import")
    assert glb_import.is_file()

    check_gd = tmp_path / "check_e2e_godot.gd"
    check_gd.write_text(f"""extends SceneTree
const PostImport := preload({str(POST_IMPORT_GD)!r})
func _fail(msg: String, n: Node = null) -> void:
\tprinterr("E2E_FAIL: " + msg); if n != null: n.free()
\tquit(1)
func _validar_bm(bm: BoneMap, skel: Skeleton3D, tag: String) -> String:
\tif bm == null or not (bm.profile is SkeletonProfileHumanoid): return tag + " sem SkeletonProfileHumanoid"
\tfor req in ["UpperChest", "Chest"]:
\t\tvar sb := String(bm.get_skeleton_bone_name(req))
\t\tif sb == "" or skel.find_bone(sb) < 0: return "%s %s invalido (%s)" % [tag, req, sb]
\tfor i in range(bm.profile.bone_size):
\t\tvar s := String(bm.get_skeleton_bone_name(bm.profile.get_bone_name(i)))
\t\tif s != "" and skel.find_bone(s) < 0: return tag + " osso ausente: " + s
\treturn ""
func _initialize() -> void:
\tvar doc := GLTFDocument.new(); var st := GLTFState.new()
\tif doc.append_from_file({str(glb)!r}, st) != OK: _fail("append_from_file falhou"); return
\tvar cena := doc.generate_scene(st)
\tPostImport.aplicar(cena, {str(glb)!r})
\tvar skels := cena.find_children("*", "Skeleton3D", true, false)
\tif skels.size() != 1 or (skels[0] as Skeleton3D).get_bone_count() != 56: _fail("Skeleton3D != 56 ossos", cena); return
\tvar skel := skels[0] as Skeleton3D
\tvar err_m := _validar_bm(cena.get_meta("forge3d_bone_map", null) as BoneMap, skel, "meta")
\tif err_m != "": _fail(err_m, cena); return
\tvar cf := ConfigFile.new()
\tif cf.load({str(glb_import)!r}) != OK: _fail("falha lendo .glb.import", cena); return
\tvar skel_sub := ((cf.get_value("params", "_subresources", {{}}) as Dictionary).get("nodes", {{}}) as Dictionary).get("PATH:Skeleton3D", {{}}) as Dictionary
\tif bool(skel_sub.get("retarget/rest_fixer/fix_silhouette/enable", false)) != true: _fail("fix_silhouette ausente", cena); return
\tvar err_i := _validar_bm(skel_sub.get("retarget/bone_map", null) as BoneMap, skel, "import")
\tif err_i != "": _fail(err_i, cena); return
\tvar ap := cena.find_children("*", "AnimationPlayer", true, false)[0] as AnimationPlayer
\tfor clip in ["idle", "walk", "run"]:
\t\tif not ap.has_animation(clip) or ap.get_animation(clip).loop_mode != Animation.LOOP_LINEAR: _fail("loop " + clip, cena); return
\tfor sock in ["Socket_HandR", "Socket_HandL", "Socket_Back", "Socket_Head"]:
\t\tvar mk := cena.find_child(sock, true, false) as Marker3D
\t\tif mk == null or not (mk.get_parent() is BoneAttachment3D): _fail("socket " + sock, cena); return
\tcena.free(); print("CROSS_ENGINE_E2E_OK"); quit(0)
""", encoding="utf-8")
    proc_gd = _rodar_godot(godot, ["--script", str(check_gd)], tmp_path)
    assert proc_gd.returncode == 0 and "CROSS_ENGINE_E2E_OK" in proc_gd.stdout, proc_gd.stdout + proc_gd.stderr
    for clip in ("idle", "walk", "run"):
        ac = _rodar_godot(godot, ["--script", str(ANIM_CHECK_GD), "--", str(glb), clip], tmp_path)
        assert ac.returncode == 0 and "GODOT_ANIM_OK" in ac.stdout, ac.stdout + ac.stderr
    qa = _rodar_godot(godot, ["--script", str(VISUAL_QA_GD), "--", str(glb)], tmp_path)
    assert qa.returncode == 0 and "GODOT_VISUAL_QA_OK" in qa.stdout, qa.stdout + qa.stderr
