"""Testes de regressao e contrato para qc.ler_glb_bin(bytes), G12, G13, G14, fachada e harness."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from forge3d import profiles, qc
from forge3d.errors import ForgeError
from tests.test_red_r2_roblox import _R15_15, _box_glb, _publicar_asset_box

RAIZ = Path(__file__).resolve().parents[1]


def test_ler_glb_bin_aceita_path_str_bytes_bytearray_e_rejeita_truncado(tmp_path: Path) -> None:
    raw = _box_glb()
    p = tmp_path / "box.glb"
    p.write_bytes(raw)
    g1, b1 = qc.ler_glb_bin(p)
    g2, b2 = qc.ler_glb_bin(str(p))
    g3, b3 = qc.ler_glb_bin(raw)
    g4, b4 = qc.ler_glb_bin(bytearray(raw))
    assert g1 == g2 == g3 == g4
    assert b1 == b2 == b3 == b4
    assert qc.ler_glb(raw)["asset"]["version"] == "2.0"
    with pytest.raises(ForgeError):
        qc.ler_glb_bin(b"glTF\x02")


def test_g12_pivot_local_disjunto_e_fusao_torso(tmp_path: Path) -> None:
    perfil = profiles.carregar("roblox-aa-80")
    escala = float(perfil["unidades"]["escala_saida"])
    # Partes pivot-locais (como split_por_ossos: transformadas por -ancora) tocando em Y=1.0*s
    (tmp_path / "LowerTorso.glb").write_bytes(_box_glb(center=(0.0, 0.5 * escala, 0.0), half=(0.25 * escala, 0.5 * escala, 0.25 * escala)))
    (tmp_path / "UpperTorso.glb").write_bytes(_box_glb(center=(0.0, 0.5 * escala, 0.0), half=(0.25 * escala, 0.5 * escala, 0.25 * escala)))
    partes_ok = [
        {"nome": "LowerTorso", "junta": "Root", "ancora": [0.0, 0.0, 0.0], "arquivo": "LowerTorso.glb"},
        {"nome": "UpperTorso", "junta": "Waist", "ancora": [0.0, 1.0 * escala, 0.0], "arquivo": "UpperTorso.glb"},
    ]
    g12_ok = qc.verificar_g12_separacao({"partes": partes_ok, "rig": {"modo": "motor6d"}}, tmp_path, {"partes": partes_ok}, escala)
    assert g12_ok["status"] == "ok", g12_ok

    # Caso de fusao no torso (LeftUpperArm completamente sobreposto a UpperTorso)
    (tmp_path / "LeftUpperArm.glb").write_bytes(_box_glb(center=(0.0, 0.5 * escala, 0.0), half=(0.2 * escala, 0.4 * escala, 0.2 * escala)))
    partes_fusao = [*partes_ok, {"nome": "LeftUpperArm", "junta": "LeftShoulder", "ancora": [0.0, 1.0 * escala, 0.0], "arquivo": "LeftUpperArm.glb"}]
    g12_fusao = qc.verificar_g12_separacao({"partes": partes_fusao, "rig": {"modo": "motor6d"}}, tmp_path, {"partes": partes_fusao}, escala)
    assert g12_fusao["status"] == "falhou"
    assert any("parte_fundida_no_torso" in p for p in g12_fusao["medido"]["problemas"])

    # Arquivo duplicado reprova
    partes_dup = [partes_ok[0], {**partes_ok[1], "arquivo": "LowerTorso.glb"}]
    assert qc.verificar_g12_separacao({"partes": partes_dup}, tmp_path, {"partes": partes_dup}, escala)["status"] == "falhou"


def test_g13_ancoras_dentro_e_acima_de_1mm() -> None:
    perfil = profiles.carregar("roblox-aa-80")
    escala = float(perfil["unidades"]["escala_saida"])
    desvio_05mm = 0.0005 * escala
    desvio_2mm = 0.002 * escala

    partes_ok = [{"nome": "Head", "junta": "Neck", "ancora": [0.0, escala + desvio_05mm, 0.0]}]
    g13_ok = qc.verificar_g13_ancoras({"partes": partes_ok}, {"partes": partes_ok, "ancoras": {"Neck": [0.0, escala, 0.0]}}, escala)
    assert g13_ok["status"] == "ok" and g13_ok["medido"]["erro_ancora_max_mm"] <= 1.0

    partes_bad = [{"nome": "Head", "junta": "Neck", "ancora": [0.0, escala + desvio_2mm, 0.0]}]
    g13_bad = qc.verificar_g13_ancoras({"partes": partes_bad}, {"partes": partes_bad, "ancoras": {"Neck": [0.0, escala, 0.0]}}, escala)
    assert g13_bad["status"] == "falhou" and g13_bad["medido"]["erro_ancora_max_mm"] > 1.0


def test_g14_walk_passa_idle_e_jump_reprovam_e_flat_rbxmx_reprova(tmp_path: Path) -> None:
    perfil = profiles.carregar("roblox-aa-80")
    item_walk = {"id": "c1", "rig": {"modo": "motor6d", "esqueleto": "r15@1"}, "animacoes_base": ["idle", "walk"]}
    g14_walk = qc.verificar_g14_animacao_roblox(item_walk, perfil, tmp_path, [])
    assert g14_walk["status"] == "ok" and g14_walk["medido"]["amplitude_max_graus"] >= 5.0

    item_idle = {"id": "c2", "rig": {"modo": "motor6d", "esqueleto": "r15@1"}, "animacoes_base": ["idle"]}
    g14_idle = qc.verificar_g14_animacao_roblox(item_idle, perfil, tmp_path, [])
    assert g14_idle["status"] == "ok" and g14_idle["medido"]["amplitude_max_graus"] >= 5.0

    import math

    ang2 = math.radians(2.0)
    c2, s2 = math.cos(ang2), math.sin(ang2)
    tiny_xml = (
        '<?xml version="1.0" encoding="utf-8"?><roblox version="4">'
        '<Item class="KeyframeSequence"><Properties><string name="Name">idle</string><bool name="Loop">true</bool></Properties>'
        '<Item class="Keyframe"><Properties><float name="Time">0</float></Properties>'
        '<Item class="Pose"><Properties><string name="Name">HumanoidRootPart</string><float name="Weight">0</float></Properties>'
        '<Item class="Pose"><Properties><string name="Name">UpperTorso</string><float name="Weight">1</float>'
        '<CoordinateFrame name="CFrame"><X>0</X><Y>0</Y><Z>0</Z>'
        '<R00>1</R00><R01>0</R01><R02>0</R02><R10>0</R10><R11>1</R11><R12>0</R12><R20>0</R20><R21>0</R21><R22>1</R22></CoordinateFrame>'
        '</Properties></Item></Item></Item>'
        '<Item class="Keyframe"><Properties><float name="Time">0.5</float></Properties>'
        '<Item class="Pose"><Properties><string name="Name">HumanoidRootPart</string><float name="Weight">0</float></Properties>'
        '<Item class="Pose"><Properties><string name="Name">UpperTorso</string><float name="Weight">1</float>'
        '<CoordinateFrame name="CFrame"><X>0</X><Y>0</Y><Z>0</Z>'
        f'<R00>1</R00><R01>0</R01><R02>0</R02><R10>0</R10><R11>{c2:.6f}</R11><R12>{-s2:.6f}</R12><R20>0</R20><R21>{s2:.6f}</R21><R22>{c2:.6f}</R22></CoordinateFrame>'
        '</Properties></Item></Item></Item>'
        '<Item class="Keyframe"><Properties><float name="Time">1.0</float></Properties>'
        '<Item class="Pose"><Properties><string name="Name">HumanoidRootPart</string><float name="Weight">0</float></Properties>'
        '<Item class="Pose"><Properties><string name="Name">UpperTorso</string><float name="Weight">1</float>'
        '<CoordinateFrame name="CFrame"><X>0</X><Y>0</Y><Z>0</Z>'
        '<R00>1</R00><R01>0</R01><R02>0</R02><R10>0</R10><R11>1</R11><R12>0</R12><R20>0</R20><R21>0</R21><R22>1</R22></CoordinateFrame>'
        '</Properties></Item></Item></Item></Item></roblox>'
    )
    (tmp_path / "tiny_amp.rbxmx").write_text(tiny_xml, encoding="utf-8")
    g14_tiny = qc.verificar_g14_animacao_roblox({"id": "c2_tiny"}, perfil, tmp_path, [{"caminho": "tiny_amp.rbxmx", "papel": "animacao"}])
    assert g14_tiny["status"] == "falhou"

    item_jump = {"id": "c3", "rig": {"modo": "motor6d", "esqueleto": "r15@1"}, "animacoes_base": ["jump"]}
    assert qc.verificar_g14_animacao_roblox(item_jump, perfil, tmp_path, [])["status"] == "falhou"

    flat_xml = (
        '<?xml version="1.0" encoding="utf-8"?><roblox version="4">'
        '<Item class="KeyframeSequence"><Properties><string name="Name">walk</string><bool name="Loop">true</bool></Properties>'
        '<Item class="Keyframe"><Properties><float name="Time">0</float></Properties>'
        '<Item class="Pose"><Properties><string name="Name">Root</string></Properties></Item>'
        "</Item></Item></roblox>"
    )
    (tmp_path / "flat.rbxmx").write_text(flat_xml, encoding="utf-8")
    g14_flat = qc.verificar_g14_animacao_roblox({"id": "c4"}, perfil, tmp_path, [{"caminho": "flat.rbxmx", "papel": "animacao"}])
    assert g14_flat["status"] == "falhou"


def test_prop_nao_segmentado_emite_g12_g14_ok_e_valida_schema_v6(tmp_path: Path) -> None:
    man = _publicar_asset_box(tmp_path, "prop.clean.01")
    por_id = {g["id"]: g for g in man["qc"]["gates"]}
    for gid in ("G12", "G13", "G14"):
        assert por_id[gid]["status"] == "ok"
        assert por_id[gid]["medido"]["aplicavel"] is False
    schema = json.loads((RAIZ / "schemas" / "manifest.v7.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(man)


def test_fachada_qc_modulos_ate_500_linhas_e_harness_r15() -> None:
    for sym in (
        "GATES", "LIMIAR_SCORE_FRENTE", "PAPEIS_TEXTURA", "_accessor", "_convexo",
        "_desvio_pivo", "_g2_orientacao", "_imagens_embutidas", "_inspecionar_facetamento_organico",
        "_skin_status", "_uv_status", "_validar_bytes_imagem", "_vram_mapa_mb",
        "analisar", "animacoes", "convexidade", "escala_do_perfil", "ler_glb", "ler_glb_bin",
        "malha", "topologia", "verificar", "verificar_g11_orcamento_cena",
    ):
        assert hasattr(qc, sym), f"qc.{sym} ausente na fachada"
    for p in (RAIZ / "src" / "forge3d").glob("qc*.py"):
        assert len(p.read_text(encoding="utf-8").splitlines()) <= 500
    assert any(p.name == "r15_play_g14.py" for p in (RAIZ / "tools").glob("*r15*.*"))
    assert "motor.Part1.Name" in (RAIZ / "tools" / "r15_anim_studio.py").read_text(encoding="utf-8")
    assert len(_R15_15) == 15


def test_g12_espaco_compartilhado_origem_offset_e_vigas_cruzadas(tmp_path: Path) -> None:
    escala = float(profiles.carregar("roblox-aa-80")["unidades"]["escala_saida"])
    # 1) Shared-space spanning (0,0,0) with non-zero ancora must NOT double-shift
    (tmp_path / "UT_shared.glb").write_bytes(_box_glb(center=(0.0, 0.75 * escala, 0.0), half=(0.2 * escala, 0.75 * escala, 0.2 * escala)))
    (tmp_path / "HD_shared.glb").write_bytes(_box_glb(center=(0.0, 1.755 * escala, 0.0), half=(0.15 * escala, 0.245 * escala, 0.15 * escala)))
    partes_sh = [
        {"nome": "UpperTorso", "junta": "Waist", "ancora": [0.0, 0.5 * escala, 0.0], "arquivo": "UT_shared.glb"},
        {"nome": "Head", "junta": "Neck", "ancora": [0.0, 1.51 * escala, 0.0], "arquivo": "HD_shared.glb"},
    ]
    assert qc.verificar_g12_separacao({"partes": partes_sh}, tmp_path, {"partes": partes_sh}, escala)["status"] == "ok"

    # 2) Offset pivot-local parts (with bone head outside AABB) stay disjoint when translated by ancora
    (tmp_path / "LT_off.glb").write_bytes(_box_glb(center=(0.0, 0.2, 0.0), half=(0.2, 0.2, 0.2)))
    (tmp_path / "UT_off.glb").write_bytes(_box_glb(center=(0.0, 0.25, 0.0), half=(0.2, 0.15, 0.2)))
    partes_off = [
        {"nome": "LowerTorso", "junta": "Root", "pivo": "junta", "ancora": [0.0, 0.0, 0.0], "arquivo": "LT_off.glb"},
        {"nome": "UpperTorso", "junta": "Waist", "pivo": "junta", "ancora": [0.0, 1.0, 0.0], "arquivo": "UT_off.glb"},
    ]
    assert qc.verificar_g12_separacao({"partes": partes_off}, tmp_path, {"partes": partes_off}, 1.0)["status"] == "ok"

    # 3) Crossed orthogonal beams with no vertex/centroid inside the other must FAIL G12
    (tmp_path / "BeamA.glb").write_bytes(_box_glb(center=(0.0, 0.04 * escala, 0.0), half=(1.0 * escala, 0.04 * escala, 0.04 * escala)))
    (tmp_path / "BeamB.glb").write_bytes(_box_glb(center=(0.0, 0.04 * escala, 0.0), half=(0.04 * escala, 0.04 * escala, 1.0 * escala)))
    partes_cb = [
        {"nome": "BeamA", "ancora": [0.0, 0.0, 0.0], "arquivo": "BeamA.glb"},
        {"nome": "BeamB", "ancora": [0.0, 0.0, 0.0], "arquivo": "BeamB.glb"},
    ]
    g12_cb = qc.verificar_g12_separacao({"partes": partes_cb}, tmp_path, {"partes": partes_cb}, escala)
    assert g12_cb["status"] == "falhou" and g12_cb["medido"]["penetracao_max_mm"] > 2.0


def test_g13_detecta_drift_em_skins_e_glb_malformado_e_r15_play_g14_valido(tmp_path: Path) -> None:
    import struct
    import sys
    from tests.test_seguranca_e_qc import _editar_gltf_glb

    escala = float(profiles.carregar("roblox-aa-80")["unidades"]["escala_saida"])
    # 1) G13 GLB skins joint drift > 1 mm
    def _add_drifted_skin(g: dict, _b: bytearray) -> None:
        g["nodes"].append({"name": "Neck", "translation": [0.0, 1.25 * escala, 0.0]})
        g["skins"] = [{"joints": [len(g["nodes"]) - 1]}]

    gltf_drift, _ = qc.ler_glb_bin(_editar_gltf_glb(_box_glb(), _add_drifted_skin))
    partes = [{"nome": "Head", "junta": "Neck", "ancora": [0.0, 1.0 * escala, 0.0]}]
    g13_drift = qc.verificar_g13_ancoras({"partes": partes}, {"partes": partes, "ancoras": {"Neck": [0.0, 1.0 * escala, 0.0]}}, escala, gltf=gltf_drift)
    assert g13_drift["status"] == "falhou" and any("ancora_skin_divergente" in p for p in g13_drift["medido"]["problemas"])

    # 2) ler_glb_bin converts malformed JSON, invalid UTF-8, and truncated chunks to ForgeError
    def _pack_chunks(chunks: list[tuple[int, bytes]]) -> bytes:
        body = b"".join(struct.pack("<II", len(d), t) + d for t, d in chunks)
        return struct.pack("<III", 0x46546C67, 2, 12 + len(body)) + body

    for bad_glb in (
        _pack_chunks([(0x4E4F534A, b"{bad")]),
        _pack_chunks([(0x4E4F534A, b"\xff\xfe  ")]),
        struct.pack("<IIIII", 0x46546C67, 2, 40, 2, 0x4E4F534A) + b"{}" + b"\x00\x00" + struct.pack("<II", 1000, 0x004E4942) + b"abcd",
    ):
        with pytest.raises(ForgeError):
            qc.ler_glb_bin(bad_glb)

    # 3) r15_play_g14 Luau output has no dangling export table & qc_roblox_anim handles non-numeric float
    sys.path.insert(0, str(RAIZ / "tools"))
    import r15_play_g14
    luau = r15_play_g14.montar_codigo_g14("walk")
    assert "-- export" not in luau and "players = Players" not in luau and "verificarG14Play(mdl, seq)" in luau

    bad_xml = (
        '<?xml version="1.0" encoding="utf-8"?><roblox version="4">'
        '<Item class="KeyframeSequence"><Properties><string name="Name">walk</string><bool name="Loop">true</bool></Properties>'
        '<Item class="Keyframe"><Properties><float name="Time">0</float></Properties>'
        '<Item class="Pose"><Properties><string name="Name">HumanoidRootPart</string><float name="Weight">bad</float></Properties>'
        "</Item></Item></Item></roblox>"
    )
    (tmp_path / "bad_num.rbxmx").write_text(bad_xml, encoding="utf-8")
    g14_bad = qc.verificar_g14_animacao_roblox({"id": "c_bad"}, profiles.carregar("roblox-aa-80"), tmp_path, [{"caminho": "bad_num.rbxmx", "papel": "animacao"}])
    assert g14_bad["status"] == "falhou" and any("animacao_xml_invalido" in p for p in g14_bad["medido"]["problemas"])


def test_r4_vec3_rejeita_bool_e_string_em_g12_e_g13(tmp_path: Path) -> None:
    from forge3d import qc_roblox

    for bad in ([True, 0, 0], [False, 1, 2], ["1", "0", "0"]):
        assert qc_roblox._vec3_valido(bad) is None
        partes = [{"nome": "Head", "junta": "Neck", "ancora": bad}]
        g13 = qc.verificar_g13_ancoras(
            {"partes": partes}, {"partes": partes, "ancoras": {"Neck": [1.0, 0.0, 0.0]}}, 1.0
        )
        assert g13["status"] == "falhou"
        assert "ancora_parte_invalida:Head" in g13["medido"]["problemas"]

    (tmp_path / "Head.glb").write_bytes(_box_glb(center=(0.0, 0.25, 0.0), half=(0.25, 0.25, 0.25)))
    pm, err = qc_roblox._carregar_parte_malha(
        {"nome": "Head", "pivo": "junta", "ancora": [True, 0, 0], "arquivo": "Head.glb"}, tmp_path, 0.002
    )
    assert pm is not None and err is None
    assert pm.wmin == pytest.approx((-0.25, 0.0, -0.25), abs=1e-6)


def test_r4_g13_e_analisar_resistem_a_nulos_em_listas_gltf() -> None:
    partes = [{"nome": "Head", "junta": "Neck", "ancora": [0.0, 0.0, 0.0]}]
    res = {"partes": partes, "ancoras": {"Neck": [0.0, 0.0, 0.0]}}
    for gltf_bad in (
        {"asset": {"version": "2.0"}, "skins": [None]},
        {"asset": {"version": "2.0"}, "nodes": [None], "skins": [{"joints": [0]}]},
        {"asset": {"version": "2.0"}, "nodes": [{"name": "Neck"}], "skins": [{"joints": [True]}]},
    ):
        g13 = qc.verificar_g13_ancoras({"partes": partes}, res, 1.0, gltf=gltf_bad)
        assert g13["status"] == "falhou" and g13["medido"]["problemas"]

    g_base, b_base = qc.ler_glb_bin(_box_glb())
    for mut in (
        {"meshes": [None]},
        {"accessors": [None]},
        {"meshes": [{"primitives": [None]}]},
        {"bufferViews": [None]},
        {"nodes": [None]},
        {"skins": [None]},
    ):
        g_mut = {**g_base, **mut}
        info = qc.analisar(g_mut, b_base)
        assert isinstance(info, dict) and info.get("erros"), (mut, info)


def test_r4_ler_glb_bin_rejeita_cabecalho_chunk_truncado() -> None:
    import struct

    json_bytes = b'{"asset":{"version":"2.0"}} '
    hdr = struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(json_bytes))
    chunk = struct.pack("<II", len(json_bytes), 0x4E4F534A) + json_bytes
    for trail in (b"\x01", b"\x10\x00\x00\x00", b"\x01\x02\x03\x04\x05\x06\x07"):
        with pytest.raises(ForgeError):
            qc.ler_glb_bin(hdr + chunk + trail)


def test_r4_g14_rejeita_weight_e_cframe_nao_finitos(tmp_path: Path) -> None:
    perfil = profiles.carregar("roblox-aa-80")
    for idx, (peso, x_val, r00_val) in enumerate(
        [("nan", "0", "1"), ("inf", "0", "1"), ("0", "nan", "1"), ("0", "0", "inf")]
    ):
        xml = (
            '<?xml version="1.0" encoding="utf-8"?><roblox version="4">'
            '<Item class="KeyframeSequence"><Properties><string name="Name">walk</string><bool name="Loop">true</bool></Properties>'
            '<Item class="Keyframe"><Properties><float name="Time">0</float></Properties>'
            f'<Item class="Pose"><Properties><string name="Name">HumanoidRootPart</string><float name="Weight">{peso}</float></Properties>'
            '<Item class="Pose"><Properties><string name="Name">UpperTorso</string><float name="Weight">1</float>'
            f'<CoordinateFrame name="CFrame"><X>{x_val}</X><Y>0</Y><Z>0</Z>'
            f'<R00>{r00_val}</R00><R01>0</R01><R02>0</R02><R10>0</R10><R11>0</R11><R12>-1</R12><R20>0</R20><R21>1</R21><R22>0</R22></CoordinateFrame>'
            "</Properties></Item></Item></Item>"
            '<Item class="Keyframe"><Properties><float name="Time">0.5</float></Properties>'
            '<Item class="Pose"><Properties><string name="Name">HumanoidRootPart</string><float name="Weight">0</float></Properties>'
            '<Item class="Pose"><Properties><string name="Name">UpperTorso</string><float name="Weight">1</float></Properties></Item>'
            "</Item></Item></Item></roblox>"
        )
        arq = tmp_path / f"nan_{idx}.rbxmx"
        arq.write_text(xml, encoding="utf-8")
        g14 = qc.verificar_g14_animacao_roblox(
            {"id": f"c_{idx}"}, perfil, tmp_path, [{"caminho": arq.name, "papel": "animacao"}]
        )
        assert g14["status"] == "falhou", (idx, g14)


def test_r5_verify_rejeita_partes_com_materials_ou_images_nulos(tmp_path: Path) -> None:
    from forge3d import verify
    from forge3d.canonical import sha256_arquivo
    from tests.test_seguranca_e_qc import _editar_gltf_glb
    from tests.test_verify_only import _montar_dest_partes_v6

    for key, tag_esperada in (("materials", "material_invalido:0"), ("images", "image_invalida:0")):
        dest = tmp_path / key
        part, man = _montar_dest_partes_v6(dest)
        part.write_bytes(_editar_gltf_glb(_box_glb(), lambda g, _b, k=key: g.update({k: [None]})))
        man["files"][1].update({"sha256": sha256_arquivo(part), "bytes": part.stat().st_size})
        (dest / "char.01.manifest.json").write_text(json.dumps(man), encoding="utf-8")
        rel = verify.verificar(dest)
        assert rel["ok"] is False
        assert any("Head.glb" in str(e) and tag_esperada in str(e) for e in rel["erros"]), rel["erros"]


def test_r5_qc_verificar_reprova_sem_levantar_em_gltf_malformado(tmp_path: Path) -> None:
    from tests.test_seguranca_e_qc import _editar_gltf_glb

    perfil = profiles.carregar("roblox-aa-80")
    item = {
        "id": "mal.qc.01",
        "tipo": "personagem_humanoide",
        "altura_metros": 1.0,
        "pivot": "base",
        "limite_triangulos": 1000,
        "colisao": "none",
        "auto_rig": True,
        "esqueleto": "r15@1",
    }
    mutacoes = [
        ("skins_none", lambda g, _b: g.update({"skins": [None]})),
        ("nodes_none", lambda g, _b: g.update({"nodes": [None], "skins": [{"joints": [0]}]})),
        ("meshes_none", lambda g, _b: g.update({"meshes": [None]})),
        ("primitives_none", lambda g, _b: g.update({"meshes": [{"primitives": [None]}]})),
        ("images_none", lambda g, _b: g.update({"images": [None]})),
        ("animations_none", lambda g, _b: g.update({"animations": [None]})),
        ("accessors_none", lambda g, _b: g.update({"accessors": [None]})),
        ("bufferViews_none", lambda g, _b: g.update({"bufferViews": [None]})),
        ("skins_str", lambda g, _b: g.update({"skins": "bad"})),
        ("nodes_str", lambda g, _b: g.update({"nodes": "bad"})),
        ("meshes_str", lambda g, _b: g.update({"meshes": "bad"})),
    ]
    for nome, mut in mutacoes:
        sub = tmp_path / nome
        sub.mkdir()
        (sub / "m.glb").write_bytes(_editar_gltf_glb(_box_glb(), mut))
        res = {"medidas": {}, "arquivos": [{"caminho": "m.glb", "papel": "mesh"}], "licenca": {"uso_comercial": True}}
        for ex_ori in (True, False):
            rel = qc.verificar(item, perfil, sub, res, exigir_orientacao=ex_ori)
            assert isinstance(rel, dict) and rel["aprovado"] is False, (nome, ex_ori, rel)
            assert any(g["status"] == "falhou" for g in rel["gates"]), (nome, rel)


def test_r5_analisar_mat4_g13_e_verificar_resistem_a_campos_aninhados_invalidos(tmp_path: Path) -> None:
    from forge3d import qc_glb
    from tests.test_seguranca_e_qc import _editar_gltf_glb

    perfil = profiles.carregar("roblox-aa-80")
    item = {"id": "mal.nested.01", "altura_metros": 1.0, "pivot": "base", "limite_triangulos": 1000, "colisao": "none"}
    partes = [{"nome": "Head", "junta": "Neck", "ancora": [0.0, 0.0, 0.0]}]
    res_g13 = {"partes": partes, "ancoras": {"Neck": [0.0, 0.0, 0.0]}}

    assert 0 in qc_glb._matrizes_mundo_nos({"nodes": [{"translation": [1.0]}]})
    assert 0 in qc_glb._matrizes_mundo_nos({"nodes": [{"matrix": [None] * 16}]})

    mutacoes = [
        ("trans_curta", lambda g, _b: g["nodes"][0].update({"translation": [1.0]})),
        ("trans_none", lambda g, _b: g["nodes"][0].update({"translation": [None, 0.0, 0.0]})),
        ("matrix_none", lambda g, _b: g["nodes"][0].update({"matrix": [None] * 16})),
        ("pbr_str", lambda g, _b: g["materials"][0].update({"pbrMetallicRoughness": "bad"})),
        ("count_none", lambda g, _b: g["accessors"][0].update({"count": None})),
        ("min_curto", lambda g, _b: g["accessors"][0].update({"min": [0.0]})),
        ("min_none", lambda g, _b: g["accessors"][0].update({"min": [None, 0.0, 0.0]})),
    ]
    for nome, mut in mutacoes:
        sub = tmp_path / nome
        sub.mkdir()
        raw = _editar_gltf_glb(_box_glb(), mut)
        (sub / "m.glb").write_bytes(raw)
        g_m, b_m = qc.ler_glb_bin(raw)
        info = qc.analisar(g_m, b_m)
        assert isinstance(info, dict) and info.get("erros"), (nome, info)
        assert isinstance(qc_glb._matrizes_mundo_nos(g_m), dict)
        assert isinstance(qc.verificar_g13_ancoras({"partes": partes}, res_g13, 1.0, gltf=g_m), dict)
        rel = qc.verificar(
            item,
            perfil,
            sub,
            {"medidas": {}, "arquivos": [{"caminho": "m.glb", "papel": "mesh"}], "licenca": {"uso_comercial": True}},
        )
        assert isinstance(rel, dict) and rel["aprovado"] is False, (nome, rel)


def test_r6_organico_indice_negativo_reprova_sem_index_error(tmp_path: Path) -> None:
    import struct
    from tests.test_qc_v3 import _empacotar_glb

    perfil = profiles.carregar("roblox-aa-80")
    item = {
        "id": "org.neg.01",
        "tipo": "personagem_humanoide",
        "altura_metros": 1.0,
        "pivot": "base",
        "limite_triangulos": 5000,
        "colisao": "none",
    }
    pos_b = b"".join(struct.pack("<3f", *p) for p in ((0, 0, 0), (0.5, 0, 0), (0, 1, 0), (0, 0, 0.5)))
    norm_b = b"".join(struct.pack("<3f", 0.0, 0.0, 1.0) for _ in range(4))
    uv_b = b"".join(struct.pack("<2f", 0.0, 0.0) for _ in range(4))

    for bad_idx in (-999, -1):
        indices = [0, 1, 2] * 239 + [0, 1, bad_idx]
        idx_b = struct.pack(f"<{len(indices)}h", *indices)
        bin_raw = pos_b + norm_b + uv_b + idx_b
        offs = (0, len(pos_b), len(pos_b) + len(norm_b), len(pos_b) + len(norm_b) + len(uv_b))
        lens = (len(pos_b), len(norm_b), len(uv_b), len(idx_b))
        gltf = {
            "asset": {"version": "2.0"},
            "buffers": [{"byteLength": len(bin_raw)}],
            "bufferViews": [
                {"buffer": 0, "byteOffset": offs[i], "byteLength": lens[i]} for i in range(4)
            ],
            "accessors": [
                {"bufferView": 0, "componentType": 5126, "count": 4, "type": "VEC3", "min": [0, 0, 0], "max": [0.5, 1, 0.5]},
                {"bufferView": 1, "componentType": 5126, "count": 4, "type": "VEC3"},
                {"bufferView": 2, "componentType": 5126, "count": 4, "type": "VEC2"},
                {"bufferView": 3, "componentType": 5122, "count": len(indices), "type": "SCALAR"},
            ],
            "materials": [{"pbrMetallicRoughness": {"baseColorFactor": [1, 1, 1, 1]}}],
            "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1, "TEXCOORD_0": 2}, "indices": 3, "material": 0}]}],
            "nodes": [{"mesh": 0}],
        }
        sub = tmp_path / f"neg_{abs(bad_idx)}"
        sub.mkdir()
        raw = _empacotar_glb(gltf, bin_raw)
        (sub / "m.glb").write_bytes(raw)
        g_m, b_m = qc.ler_glb_bin(raw)
        with pytest.raises(ForgeError):
            qc._inspecionar_facetamento_organico(g_m, b_m)
        rel = qc.verificar(
            item, perfil, sub,
            {"medidas": {}, "arquivos": [{"caminho": "m.glb", "papel": "mesh"}], "licenca": {"uso_comercial": True}},
        )
        assert rel["aprovado"] is False, (bad_idx, rel)
        g1 = next(g for g in rel["gates"] if g["id"] == "G1")
        assert g1["status"] == "falhou" and g1["medido"].get("erros_gltf")


def test_r6_atributos_e_material_dangling_reprovam_g1_g3(tmp_path: Path) -> None:
    import struct
    from forge3d import qc_glb_mat
    from tests.test_seguranca_e_qc import _editar_gltf_glb

    assert qc_glb_mat._num_finito(10**400) is False
    perfil = profiles.carregar("roblox-aa-80")
    escala = float(perfil["unidades"]["escala_saida"])
    box = _box_glb(center=(0.0, 0.5 * escala, 0.0), half=(0.25 * escala, 0.5 * escala, 0.25 * escala))
    item = {"id": "prop.uv.01", "tipo": "prop_estatico", "altura_metros": 1.0, "pivot": "base", "limite_triangulos": 1000, "colisao": "none"}
    base_dir = tmp_path / "base"
    base_dir.mkdir()
    (base_dir / "m.glb").write_bytes(box)
    rel_ok = qc.verificar(
        item, perfil, base_dir,
        {"medidas": {}, "arquivos": [{"caminho": "m.glb", "papel": "mesh"}], "licenca": {"uso_comercial": True}},
    )
    assert rel_ok["aprovado"] is True, rel_ok

    def _nan_idx(g: dict, b: bytearray) -> None:
        acc_i = g["accessors"][g["meshes"][0]["primitives"][0]["indices"]]
        bv_i = g["bufferViews"][acc_i["bufferView"]]
        off = bv_i["byteOffset"] + acc_i.get("byteOffset", 0)
        pad = (-len(b)) % 4
        b.extend(b"\x00" * pad)
        new_off = len(b)
        b.extend(struct.pack("<fff", 0.0, 1.0, float("nan")))
        bv_i.update({"byteOffset": new_off, "byteLength": 12})
        acc_i.update({"componentType": 5126, "count": 3, "byteOffset": 0})
        _ = off

    mutacoes = [
        ("uv0_oob", lambda g, _b: g["meshes"][0]["primitives"][0]["attributes"].update({"TEXCOORD_0": 999}), True),
        ("uv0_bool", lambda g, _b: g["meshes"][0]["primitives"][0]["attributes"].update({"TEXCOORD_0": True}), True),
        ("uv0_str", lambda g, _b: g["meshes"][0]["primitives"][0]["attributes"].update({"TEXCOORD_0": "bad"}), True),
        ("uv0_no_bv", lambda g, _b: g["accessors"][g["meshes"][0]["primitives"][0]["attributes"]["TEXCOORD_0"]].pop("bufferView", None), True),
        ("uv1_oob", lambda g, _b: g["meshes"][0]["primitives"][0]["attributes"].update({"TEXCOORD_1": 999}), False),
        ("norm_oob", lambda g, _b: g["meshes"][0]["primitives"][0]["attributes"].update({"NORMAL": 999}), False),
        ("mat_oob", lambda g, _b: g["meshes"][0]["primitives"][0].update({"material": 999}), False),
        ("mat_bool", lambda g, _b: g["meshes"][0]["primitives"][0].update({"material": True}), False),
        ("mat_str", lambda g, _b: g["meshes"][0]["primitives"][0].update({"material": "bad"}), False),
        ("idx_nan", _nan_idx, False),
    ]
    for nome, mut, espera_g3_falha in mutacoes:
        sub = tmp_path / nome
        sub.mkdir()
        (sub / "m.glb").write_bytes(_editar_gltf_glb(box, mut))
        rel = qc.verificar(
            item, perfil, sub,
            {"medidas": {}, "arquivos": [{"caminho": "m.glb", "papel": "mesh"}], "licenca": {"uso_comercial": True}},
        )
        assert rel["aprovado"] is False, (nome, rel)
        por_id = {g["id"]: g for g in rel["gates"]}
        if espera_g3_falha:
            assert por_id["G3"]["status"] == "falhou", (nome, por_id["G3"])
        assert por_id["G1"]["status"] == "falhou", (nome, por_id["G1"])
