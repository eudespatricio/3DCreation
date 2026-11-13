"""Testes dos pacotes 1 e 2: seguranca do publish/CLI/locks/upload e QC honesto (G1-G9)."""

from __future__ import annotations

import json
import os
import struct
import zlib
from pathlib import Path

import pytest

from forge3d import config, locks, profiles, publish, qc, upload
from forge3d.canonical import sha256_arquivo
from forge3d.cli.comandos import despachar
from forge3d.errors import ForgeError


def _png_bytes(w: int, h: int) -> bytes:
    def chunk(tipo: bytes, dados: bytes) -> bytes:
        crc = zlib.crc32(tipo + dados) & 0xFFFFFFFF
        return struct.pack(">I", len(dados)) + tipo + dados + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\x80\x80\x80" * w for _ in range(h))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def _glb_bytes(
    *,
    verts: list[tuple[float, float, float]] | None = None,
    tris: list[tuple[int, int, int]] | None = None,
    uvs: list[tuple[float, float]] | None = None,
    png_wh: tuple[int, int] = (8, 8),
    materiais: list[dict] | None = None,
    ossos: list[str] | None = None,
    pesos_skin: list[tuple[float, float, float, float]] | None = None,
    no_nome: str = "Asset",
    com_uv: bool = True,
) -> bytes:
    # Cubo fechado valido (8 vertices, 12 triangulos, centro XZ=(0,0), Y=[0,1])
    if verts is None:
        verts = [
            (-0.5, 0.0, -0.5),
            (0.5, 0.0, -0.5),
            (0.5, 1.0, -0.5),
            (-0.5, 1.0, -0.5),
            (-0.5, 0.0, 0.5),
            (0.5, 0.0, 0.5),
            (0.5, 1.0, 0.5),
            (-0.5, 1.0, 0.5),
        ]
    if tris is None:
        tris = [
            (0, 2, 1), (0, 3, 2),
            (4, 5, 6), (4, 6, 7),
            (0, 1, 5), (0, 5, 4),
            (2, 3, 7), (2, 7, 6),
            (0, 4, 7), (0, 7, 3),
            (1, 2, 6), (1, 6, 5),
        ]
    if uvs is None:
        padrao_uv = [(0.1, 0.1), (0.9, 0.1), (0.9, 0.9), (0.1, 0.9)]
        uvs = [padrao_uv[i % 4] for i in range(len(verts))]

    buf = bytearray()

    def pad4():
        while len(buf) % 4:
            buf.append(0)

    pos_off = len(buf)
    for x, y, z in verts:
        buf.extend(struct.pack("<fff", x, y, z))
    pos_len = len(buf) - pos_off

    uv_off = len(buf)
    for u, v in uvs:
        buf.extend(struct.pack("<ff", u, v))
    uv_len = len(buf) - uv_off

    idx_off = len(buf)
    for a, b, c in tris:
        buf.extend(struct.pack("<HHH", a, b, c))
    idx_len = len(buf) - idx_off
    pad4()

    img_bytes = _png_bytes(*png_wh)
    img_off = len(buf)
    buf.extend(img_bytes)
    img_len = len(buf) - img_off
    pad4()

    xs = [p[0] for p in verts]
    ys = [p[1] for p in verts]
    zs = [p[2] for p in verts]

    bvs = [
        {"buffer": 0, "byteOffset": pos_off, "byteLength": pos_len},
        {"buffer": 0, "byteOffset": uv_off, "byteLength": uv_len},
        {"buffer": 0, "byteOffset": idx_off, "byteLength": idx_len},
        {"buffer": 0, "byteOffset": img_off, "byteLength": img_len},
    ]
    accs = [
        {
            "bufferView": 0,
            "componentType": 5126,
            "count": len(verts),
            "type": "VEC3",
            "min": [min(xs), min(ys), min(zs)],
            "max": [max(xs), max(ys), max(zs)],
        },
        {"bufferView": 1, "componentType": 5126, "count": len(verts), "type": "VEC2"},
        {"bufferView": 2, "componentType": 5123, "count": len(tris) * 3, "type": "SCALAR"},
    ]
    attrs = {"POSITION": 0}
    if com_uv:
        attrs["TEXCOORD_0"] = 1

    mats = materiais if materiais is not None else [
        {"name": "m0", "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}}
    ]
    nodes = [{"name": no_nome, "mesh": 0}]
    skins = []
    if ossos:
        j_off = len(buf)
        for _ in range(len(verts)):
            buf.extend(struct.pack("<BBBB", 0, 0, 0, 0))
        j_len = len(buf) - j_off
        w_off = len(buf)
        pesos_v = pesos_skin if pesos_skin is not None else [(1.0, 0.0, 0.0, 0.0)] * len(verts)
        for w0, w1, w2, w3 in pesos_v:
            buf.extend(struct.pack("<ffff", w0, w1, w2, w3))
        w_len = len(buf) - w_off
        bvs.append({"buffer": 0, "byteOffset": j_off, "byteLength": j_len})
        accs.append({"bufferView": len(bvs) - 1, "componentType": 5121, "count": len(verts), "type": "VEC4"})
        attrs["JOINTS_0"] = len(accs) - 1
        bvs.append({"buffer": 0, "byteOffset": w_off, "byteLength": w_len})
        accs.append({"bufferView": len(bvs) - 1, "componentType": 5126, "count": len(verts), "type": "VEC4"})
        attrs["WEIGHTS_0"] = len(accs) - 1
        joint_indices = []
        for nome in ossos:
            joint_indices.append(len(nodes))
            nodes.append({"name": nome})
        skins = [{"joints": joint_indices}]
        nodes[0]["skin"] = 0

    gltf = {
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": len(buf)}],
        "bufferViews": bvs,
        "accessors": accs,
        "images": [{"mimeType": "image/png", "bufferView": 3}],
        "textures": [{"source": 0}],
        "materials": mats,
        "meshes": [{"primitives": [{"attributes": attrs, "indices": 2, "material": 0}]}],
        "nodes": nodes,
        **({"skins": skins} if skins else {}),
    }
    jb = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    while len(jb) % 4:
        jb += b" "
    total = 12 + 8 + len(jb) + 8 + len(buf)
    return (
        struct.pack("<III", 0x46546C67, 2, total)
        + struct.pack("<II", len(jb), 0x4E4F534A)
        + jb
        + struct.pack("<II", len(buf), 0x004E4942)
        + bytes(buf)
    )


def _manifesto_min(destino: Path, staging: Path, nome_arq: str = "a.glb") -> dict:
    dados = b"glTF_dummy_" * 10
    (staging / nome_arq).write_bytes(dados)
    return {
        "schema": "forge3d/manifest@1",
        "asset_id": "asset.seg.01",
        "projeto": "demo",
        "perfil": "godot4",
        "rota": "blocky",
        "determinism": "D1",
        "pipeline_version": "0.1.0",
        "spec_hash": "a" * 64,
        "created_at": "2026-11-11T00:00:00Z",
        "geometry": {"triangulos": 12, "materiais": 1},
        "licenca": {"modelo": "CC0-1.0", "uso_comercial": True, "notice": "none"},
        "files": [
            {
                "caminho": nome_arq,
                "papel": "mesh",
                "sha256": sha256_arquivo(staging / nome_arq),
                "bytes": len(dados),
            }
        ],
        "qc": {"aprovado": True, "gates": []},
    }


# ------------------------------------------------------------------ Pacote 1


def test_limpar_orfaos_bloqueia_path_traversal(tmp_path):
    destino = tmp_path / "destino"
    destino.mkdir()
    alvo_externo = tmp_path / "segredo.txt"
    alvo_externo.write_text("nao apagar", encoding="utf-8")

    (destino / "asset.seg.01.manifest.json").write_text(
        json.dumps({"files": [{"caminho": "../segredo.txt"}]}),
        encoding="utf-8",
    )
    staging = tmp_path / "staging"
    staging.mkdir()
    man = _manifesto_min(destino, staging)

    with pytest.raises(ForgeError) as exc:
        publish.publicar(staging, destino, man, "run-sec-1")
    assert exc.value.codigo == "FORGE-E-MANIFEST"
    assert alvo_externo.is_file()


def test_orfaos_nao_sao_removidos_se_manifesto_falhar(tmp_path, monkeypatch):
    staging = tmp_path / "staging"
    staging.mkdir()
    destino = tmp_path / "destino"
    man = _manifesto_min(destino, staging, "novo.glb")
    (staging / "velho_LOD1.glb").write_bytes(b"velho")
    man["files"].append(
        {
            "caminho": "velho_LOD1.glb",
            "papel": "lod",
            "sha256": sha256_arquivo(staging / "velho_LOD1.glb"),
            "bytes": 5,
        }
    )
    publish.publicar(staging, destino, man, "run-1")

    man2 = _manifesto_min(destino, staging, "novo.glb")
    orig_replace = os.replace

    def falhar_no_manifesto(src, dst):
        if str(dst).endswith(".manifest.json"):
            raise OSError("falha simulada no manifesto")
        return orig_replace(src, dst)

    monkeypatch.setattr(os, "replace", falhar_no_manifesto)
    with pytest.raises(OSError):
        publish.publicar(staging, destino, man2, "run-2")
    assert (destino / "velho_LOD1.glb").is_file()


def test_ler_cache_invalida_arquivo_corrompido(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE3D_HOME", str(tmp_path / "state"))
    origem = tmp_path / "orig"
    origem.mkdir()
    arq = origem / "item.glb"
    arq.write_bytes(b"conteudo-integro")
    entrada = {
        "resultado": {
            "arquivos": [
                {"caminho": "item.glb", "papel": "mesh", "sha256": sha256_arquivo(arq)}
            ]
        }
    }
    publish.salvar_cache("chave-teste", origem, entrada)
    assert publish.ler_cache("chave-teste") is not None

    (tmp_path / "state" / "cache" / "chave-teste" / "final" / "item.glb").write_bytes(b"adulterado")
    assert publish.ler_cache("chave-teste") is None


def test_locks_estado_e_lock_destino(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE3D_HOME", str(tmp_path / "state"))
    with locks.lock_gpu("run-a"):
        assert locks.estado()["ocupado"] is True
    assert locks.estado()["ocupado"] is False

    dest = tmp_path / "dest"
    with locks.lock_destino(dest, "run-a"):
        with pytest.raises(ForgeError) as exc:
            with locks.lock_destino(dest, "run-b", esperar=False):
                pass
        assert exc.value.codigo == "FORGE-E-RECURSO"


def test_cli_excecao_nao_tratada_vira_forge_e_interno_json(monkeypatch, capsys):
    import forge3d.cli.comandos as comandos

    monkeypatch.setattr(comandos, "_doctor", lambda _args: (_ for _ in ()).throw(RuntimeError("boom")))
    code = despachar(["doctor", "--json"])
    assert code == 4
    out = json.loads(capsys.readouterr().out)
    assert out["erro"]["codigo"] == "FORGE-E-INTERNO"
    assert "boom" in out["erro"]["mensagem"]


def test_config_permite_home_com_subpasta_mnt_e_isola_raiz_estado(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE3D_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    p = tmp_path / "home" / "mnt" / "assets"
    config.validar_caminho(p)
    assert not config.destino_permitido(tmp_path / "state" / "cache")


def test_upload_rejeita_http_remoto_e_key_permissiva(tmp_path, monkeypatch):
    glb = tmp_path / "m.glb"
    glb.write_bytes(b"glTF" + b"x" * 16)
    key = tmp_path / "roblox.key"
    key.write_text("segredo", encoding="utf-8")
    os.chmod(key, 0o644)
    monkeypatch.delenv("FORGE3D_ROBLOX_API_KEY", raising=False)
    monkeypatch.setenv("FORGE3D_ROBLOX_API_KEY_FILE", str(key))
    with pytest.raises(ForgeError, match="chmod 600"):
        upload.chave_api()

    os.chmod(key, 0o600)
    with pytest.raises(ForgeError, match="https://"):
        upload.executar(
            glb,
            creator_id="1",
            api_url="http://apis.roblox.com",
            dry_run=True,
        )


# ------------------------------------------------------------------ Pacote 2


def _rodar_qc(tmp_path: Path, glb: bytes, *, perfil_nome: str = "godot4", item_extra: dict | None = None, col_glb: bytes | None = None):
    (tmp_path / "m.glb").write_bytes(glb)
    arquivos = [{"caminho": "m.glb", "papel": "mesh", "nivel": 0, "triangulos": 12}]
    medidas = {"nao_manifold": 0, "degeneradas": 0, "partes_colisao": 0}
    item = {
        "id": "prop.teste.01",
        "altura_metros": 1.0,
        "pivot": "base",
        "limite_triangulos": 500,
        "auto_rig": False,
        "colisao": "none",
    }
    if item_extra:
        item.update(item_extra)
    if col_glb is not None:
        (tmp_path / "m_col.glb").write_bytes(col_glb)
        arquivos.append({"caminho": "m_col.glb", "papel": "colisor", "partes": 1})
        medidas["partes_colisao"] = 1
    resultado = {
        "medidas": medidas,
        "arquivos": arquivos,
        "licenca": {"modelo": "CC0", "uso_comercial": True},
    }
    return qc.verificar(item, profiles.carregar(perfil_nome), tmp_path, resultado, escala_saida=1.0)


def _gate(relatorio: dict, gid: str) -> dict:
    return next(g for g in relatorio["gates"] if g["id"] == gid)


def test_qc_g1_pega_nao_manifold_mesmo_com_medidas_zeradas(tmp_path):
    # Remove uma face do cubo -> borda aberta (nao_manifold > 0)
    tris_abertos = [
        (0, 2, 1), (0, 3, 2),
        (4, 5, 6), (4, 6, 7),
        (0, 1, 5), (0, 5, 4),
        (2, 3, 7), (2, 7, 6),
        (0, 4, 7), (0, 7, 3),
    ]
    rel = _rodar_qc(tmp_path, _glb_bytes(tris=tris_abertos))
    assert _gate(rel, "G1")["status"] == "falhou"


def test_qc_g2_reprova_pivo_descentralizado_em_xz(tmp_path):
    verts_deslocados = [
        (0.0, 0.0, -0.5), (1.0, 0.0, -0.5), (1.0, 1.0, -0.5), (0.0, 1.0, -0.5),
        (0.0, 0.0, 0.5), (1.0, 0.0, 0.5), (1.0, 1.0, 0.5), (0.0, 1.0, 0.5),
    ]
    rel = _rodar_qc(tmp_path, _glb_bytes(verts=verts_deslocados))
    assert _gate(rel, "G2")["status"] == "falhou"


def test_qc_g3_reprova_uv_fora_de_0_1(tmp_path):
    rel = _rodar_qc(tmp_path, _glb_bytes(uvs=[(1.5, 0.5)] * 8))
    assert _gate(rel, "G3")["status"] == "falhou"


def test_qc_g4_reprova_imagem_embutida_nao_pot(tmp_path):
    rel = _rodar_qc(tmp_path, _glb_bytes(png_wh=(10, 10)))
    assert _gate(rel, "G4")["status"] == "falhou"


def test_qc_g5_exige_textura_em_todos_os_materiais(tmp_path):
    mats = [
        {"name": "m0", "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}},
        {"name": "m1", "pbrMetallicRoughness": {}},
    ]
    rel = _rodar_qc(tmp_path, _glb_bytes(materiais=mats))
    assert _gate(rel, "G5")["status"] == "falhou"


def test_qc_g6_reprova_osso_obrigatorio_ausente(tmp_path):
    rel = _rodar_qc(
        tmp_path,
        _glb_bytes(ossos=["Root", "Head"]),
        item_extra={"auto_rig": True, "esqueleto": "godot-humanoid@1"},
    )
    g6 = _gate(rel, "G6")
    assert g6["status"] == "falhou"
    assert "Hips" in g6["medido"]["faltando_no_mapa"]


def test_qc_g7_fail_closed_e_prefixo_colisor_invalido(tmp_path):
    col_ok = _glb_bytes(no_nome="UCX_col_00")
    gltf, binb = qc.ler_glb_bin(
        (lambda p: (p.write_bytes(col_ok), p)[1])(tmp_path / "c.glb")
    )
    med = qc.convexidade(gltf, binb, max_pares=5)
    assert med["convexo"] is False

    col_errado = _glb_bytes(no_nome="BadCollider")
    rel = _rodar_qc(
        tmp_path,
        _glb_bytes(),
        item_extra={"colisao": "convex"},
        col_glb=col_errado,
    )
    assert _gate(rel, "G7")["status"] == "falhou"


def test_qc_gates_inclui_g10():
    assert "G10" in qc.GATES


def test_qc_g2_libera_empunhadura_e_equipavel_assimetrico_em_xz(tmp_path):
    # Empunhadura deslocada em X nao falha G2 quando Y respeita FRACAO_EMPUNHADURA (0.20)
    verts_emp = [
        (0.2, -0.2, -0.5), (1.2, -0.2, -0.5), (1.2, 0.8, -0.5), (0.2, 0.8, -0.5),
        (0.2, -0.2, 0.5), (1.2, -0.2, 0.5), (1.2, 0.8, 0.5), (0.2, 0.8, 0.5),
    ]
    rel_emp = _rodar_qc(
        tmp_path,
        _glb_bytes(verts=verts_emp),
        item_extra={"tipo": "prop_equipavel", "pivot": "empunhadura"},
    )
    assert _gate(rel_emp, "G2")["status"] == "ok"

    # Centro continua exigindo centralizacao em XZ
    rel_centro = _rodar_qc(
        tmp_path,
        _glb_bytes(verts=[
            (0.2, -0.5, -0.5), (1.2, -0.5, -0.5), (1.2, 0.5, -0.5), (0.2, 0.5, -0.5),
            (0.2, -0.5, 0.5), (1.2, -0.5, 0.5), (1.2, 0.5, 0.5), (0.2, 0.5, 0.5),
        ]),
        item_extra={"tipo": "prop_equipavel", "pivot": "centro"},
    )
    assert _gate(rel_centro, "G2")["status"] == "falhou"


def test_qc_g5_aceita_base_color_factor_e_color_0(tmp_path):
    # 1. Material sem textura com baseColorFactor
    mats_factor = [{"name": "m0", "pbrMetallicRoughness": {"baseColorFactor": [0.8, 0.2, 0.2, 1.0]}}]
    rel_factor = _rodar_qc(tmp_path, _glb_bytes(materiais=mats_factor))
    assert _gate(rel_factor, "G5")["status"] == "ok"

    # 2. Material vazio com atributo COLOR_0 na primitiva
    glb_base = _glb_bytes(materiais=[{"name": "vc", "pbrMetallicRoughness": {}}])
    # Injeta COLOR_0 no JSON do GLB sintetico (reusa accessor 0 apenas para inspecao de atributo)
    magic, ver, _ = struct.unpack_from("<III", glb_base, 0)
    jlen, jtype = struct.unpack_from("<II", glb_base, 12)
    gltf = json.loads(glb_base[20 : 20 + jlen].decode("utf-8"))
    gltf["meshes"][0]["primitives"][0]["attributes"]["COLOR_0"] = 0
    bin_hdr = 20 + jlen
    blen, btype = struct.unpack_from("<II", glb_base, bin_hdr)
    bin_data = glb_base[bin_hdr + 8 : bin_hdr + 8 + blen]
    jb = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    while len(jb) % 4:
        jb += b" "
    glb_vc = (
        struct.pack("<III", magic, ver, 12 + 8 + len(jb) + 8 + len(bin_data))
        + struct.pack("<II", len(jb), jtype)
        + jb
        + struct.pack("<II", len(bin_data), btype)
        + bin_data
    )
    rel_vc = _rodar_qc(tmp_path, glb_vc)
    assert _gate(rel_vc, "G5")["status"] == "ok"


def test_qc_v2_g1_invertidas_g3_uv_e_g4_crc_webp(tmp_path):
    # G1 reprova cubo com winding invertido (volume negativo)
    tris_inv = [
        (0, 1, 2), (0, 2, 3),
        (4, 6, 5), (4, 7, 6),
        (0, 5, 1), (0, 4, 5),
        (2, 7, 3), (2, 6, 7),
        (0, 7, 4), (0, 3, 7),
        (1, 6, 2), (1, 5, 6),
    ]
    d_g1 = tmp_path / "g1_inv"
    d_g1.mkdir()
    rel_inv = _rodar_qc(d_g1, _glb_bytes(tris=tris_inv))
    g1_inv = _gate(rel_inv, "G1")
    assert g1_inv["status"] == "falhou"
    assert g1_inv["medido"]["invertidas"] == 1

    # G3 reprova UV colapsada e permite tiling apenas quando item pede
    d_g3c = tmp_path / "g3_col"
    d_g3c.mkdir()
    rel_col = _rodar_qc(d_g3c, _glb_bytes(uvs=[(0.5, 0.5)] * 8))
    assert _gate(rel_col, "G3")["status"] == "falhou"
    assert _gate(rel_col, "G3")["medido"]["uv_colapsada"] == 1

    d_g3t = tmp_path / "g3_tile"
    d_g3t.mkdir()
    rel_tile = _rodar_qc(
        d_g3t,
        _glb_bytes(uvs=[(0.1, 0.1), (2.4, 0.1), (2.4, 2.4), (0.1, 2.4)] * 2),
        item_extra={"permitir_tiling": True},
    )
    assert _gate(rel_tile, "G3")["status"] == "ok"

    # G4 reprova PNG com CRC adulterado e aceita WEBP valido
    from PIL import Image

    d_png = tmp_path / "g4_crc"
    d_png.mkdir()
    glb_crc = bytearray(_glb_bytes())
    idx_iend = glb_crc.rfind(b"IEND")
    assert idx_iend > 0
    glb_crc[idx_iend + 4] ^= 0xFF
    assert _gate(_rodar_qc(d_png, bytes(glb_crc)), "G4")["status"] == "falhou"

    d_webp = tmp_path / "g4_webp"
    d_webp.mkdir()
    Image.new("RGBA", (8, 8), (120, 40, 20, 255)).save(d_webp / "m_albedo.webp", format="WEBP")
    (d_webp / "m.glb").write_bytes(_glb_bytes(materiais=[{"name": "m0", "pbrMetallicRoughness": {"baseColorFactor": [1, 1, 1, 1]}}]))
    rel_webp = qc.verificar(
        {"id": "prop.webp.01", "altura_metros": 1.0, "pivot": "base", "limite_triangulos": 500, "colisao": "none"},
        profiles.carregar("godot4"),
        d_webp,
        {
            "medidas": {"nao_manifold": 0, "degeneradas": 0},
            "arquivos": [
                {"caminho": "m.glb", "papel": "mesh", "nivel": 0, "triangulos": 12},
                {"caminho": "m_albedo.webp", "papel": "textura"},
            ],
            "licenca": {"modelo": "CC0", "uso_comercial": True},
        },
        escala_saida=1.0,
    )
    assert _gate(rel_webp, "G4")["status"] == "ok"


def test_qc_v2_g5_tangent_g6_pesos_g7_coplanar_e_g9_lod(tmp_path):
    # G5 exige TANGENT quando ha normalTexture
    mats_norm = [{
        "name": "m0",
        "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}},
        "normalTexture": {"index": 0},
    }]
    d_g5 = tmp_path / "g5"
    d_g5.mkdir()
    assert _gate(_rodar_qc(d_g5, _glb_bytes(materiais=mats_norm)), "G5")["status"] == "falhou"

    # G6 valida soma de WEIGHTS_0
    d_g6 = tmp_path / "g6"
    d_g6.mkdir()
    ossos_godot = profiles.carregar("godot4")["rig"]["mapas"]["godot-humanoid@1"]
    rel_g6 = _rodar_qc(
        d_g6,
        _glb_bytes(ossos=ossos_godot, pesos_skin=[(0.2, 0.0, 0.0, 0.0)] * 8),
        item_extra={"auto_rig": True, "esqueleto": "godot-humanoid@1"},
    )
    assert _gate(rel_g6, "G6")["status"] == "falhou"

    # G7 reprova colisor coplanar e colisor fora da AABB
    d_g7_cop = tmp_path / "g7_cop"
    d_g7_cop.mkdir()
    col_cop = _glb_bytes(
        verts=[(0.0, 0.0, 0.0), (0.5, 0.0, 0.0), (0.0, 0.5, 0.0), (0.5, 0.5, 0.0)],
        tris=[(0, 1, 2), (1, 3, 2)],
        uvs=[(0.1, 0.1), (0.9, 0.1), (0.9, 0.9), (0.1, 0.9)],
        no_nome="UCX_cop",
    )
    assert _gate(_rodar_qc(d_g7_cop, _glb_bytes(), item_extra={"colisao": "convex"}, col_glb=col_cop), "G7")["status"] == "falhou"

    d_g7_oob = tmp_path / "g7_oob"
    d_g7_oob.mkdir()
    verts_oob = [(x + 5.0, y, z) for (x, y, z) in [
        (-0.5, 0.0, -0.5), (0.5, 0.0, -0.5), (0.5, 1.0, -0.5), (-0.5, 1.0, -0.5),
        (-0.5, 0.0, 0.5), (0.5, 0.0, 0.5), (0.5, 1.0, 0.5), (-0.5, 1.0, 0.5),
    ]]
    assert _gate(
        _rodar_qc(d_g7_oob, _glb_bytes(), item_extra={"colisao": "convex"}, col_glb=_glb_bytes(verts=verts_oob, no_nome="UCX_oob")),
        "G7",
    )["status"] == "falhou"

    # G9 reprova LOD com silhueta divergente
    d_g9 = tmp_path / "g9_lod"
    d_g9.mkdir()
    (d_g9 / "m.glb").write_bytes(_glb_bytes())
    verts_mini = [
        (-0.05, 0.0, -0.05), (0.05, 0.0, -0.05), (0.05, 0.1, -0.05), (-0.05, 0.1, -0.05),
        (-0.05, 0.0, 0.05), (0.05, 0.0, 0.05), (0.05, 0.1, 0.05), (-0.05, 0.1, 0.05),
    ]
    (d_g9 / "m_LOD1.glb").write_bytes(_glb_bytes(verts=verts_mini))
    rel_g9 = qc.verificar(
        {"id": "prop.lod.01", "altura_metros": 1.0, "pivot": "base", "limite_triangulos": 500, "colisao": "none"},
        profiles.carregar("godot4"),
        d_g9,
        {
            "medidas": {"nao_manifold": 0, "degeneradas": 0},
            "arquivos": [
                {"caminho": "m.glb", "papel": "mesh", "nivel": 0, "triangulos": 12},
                {"caminho": "m_LOD1.glb", "papel": "lod", "nivel": 1, "triangulos": 12},
            ],
            "licenca": {"modelo": "CC0", "uso_comercial": True},
        },
        escala_saida=1.0,
    )
    assert _gate(rel_g9, "G9")["status"] == "falhou"
