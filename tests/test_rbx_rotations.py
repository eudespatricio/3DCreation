"""Testes V3 para `src/forge3d/rbx.py`: rotacoes 3x3 em CFrame, colarinhos L/R, sockets e composicao de quaternions."""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from forge3d import config, rbx


@pytest.fixture(autouse=True)
def _isolar_allowlist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORGE3D_HOME", str(tmp_path / "forge_home"))
    monkeypatch.setenv("FORGE3D_CONFIG", str(tmp_path / "forge_cfg"))
    config.adicionar(tmp_path)


def _parse_cframe_node(cf: ET.Element) -> tuple[tuple[float, float, float], list[list[float]]]:
    pos = (
        float(cf.findtext("X", "0")),
        float(cf.findtext("Y", "0")),
        float(cf.findtext("Z", "0")),
    )
    mat = [
        [float(cf.findtext(f"R{r}{c}", "0")) for c in range(3)]
        for r in range(3)
    ]
    return pos, mat


def _det3(m: list[list[float]]) -> float:
    return (
        m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
        - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
        + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0])
    )


def test_cframe_identidade_e_matriz_3x3_ortonormal() -> None:
    xml_id = "\n".join(rbx._cframe((1.0, 2.0, 3.0)))
    cf_id = ET.fromstring(xml_id)
    pos, mat = _parse_cframe_node(cf_id)
    assert pos == pytest.approx((1.0, 2.0, 3.0))
    assert _det3(mat) == pytest.approx(1.0, abs=1e-6)
    assert mat == [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]

    # Rotacao de 90 graus em torno de Y (nested 3x3)
    rot_y90 = [
        [0.0, 0.0, 1.0],
        [0.0, 1.0, 0.0],
        [-1.0, 0.0, 0.0],
    ]
    xml_rot = "\n".join(rbx._cframe((0.5, -1.0, 2.5), rot_y90))
    cf_rot = ET.fromstring(xml_rot)
    pos_r, mat_r = _parse_cframe_node(cf_rot)
    assert pos_r == pytest.approx((0.5, -1.0, 2.5))
    assert _det3(mat_r) == pytest.approx(1.0, abs=1e-6)
    assert mat_r[0][2] == pytest.approx(1.0, abs=1e-6)
    assert mat_r[2][0] == pytest.approx(-1.0, abs=1e-6)

    # Quaternion wxyz de 90 graus em torno de Z
    meio = math.pi / 4.0
    quat_z90 = (math.cos(meio), 0.0, 0.0, math.sin(meio))
    xml_q = "\n".join(rbx._cframe((0.0, 0.0, 0.0), quat_z90))
    _, mat_q = _parse_cframe_node(ET.fromstring(xml_q))
    assert _det3(mat_q) == pytest.approx(1.0, abs=1e-6)
    assert mat_q[0][1] == pytest.approx(-1.0, abs=1e-6)
    assert mat_q[1][0] == pytest.approx(1.0, abs=1e-6)


def test_collar_attachment_sinais_x_corretos(tmp_path: Path) -> None:
    saida = tmp_path / "r15.rbxlx"
    rbx.exportar_r15("examples/lote_09_r15.yaml", "personagem.r15.guard.01", saida=saida)
    arvore = ET.parse(saida)
    atts: dict[str, ET.Element] = {}
    for item in arvore.findall(".//Item[@class='Attachment']"):
        props = item.find("Properties")
        if props is None:
            continue
        nome = props.findtext("string[@name='Name']", "")
        cf = props.find("CoordinateFrame[@name='CFrame']")
        if nome and cf is not None:
            atts[nome] = cf

    assert "LeftCollarAttachment" in atts
    assert "RightCollarAttachment" in atts
    left_x = float(atts["LeftCollarAttachment"].findtext("X", "0"))
    right_x = float(atts["RightCollarAttachment"].findtext("X", "0"))
    assert left_x < 0.0, f"LeftCollarAttachment X deveria ser negativo (< 0): {left_x}"
    assert right_x > 0.0, f"RightCollarAttachment X deveria ser positivo (> 0): {right_x}"
    assert left_x == pytest.approx(-right_x, abs=1e-5)


def test_sockets_do_manifesto_aplicados_em_attachments_e_motor6d(tmp_path: Path) -> None:
    meio = math.pi / 4.0
    quat_y90 = [math.cos(meio), 0.0, math.sin(meio), 0.0]
    manifesto_acc = {
        "schema": "forge3d/manifest@5",
        "asset_id": "arma.espada.01",
        "anexo": {"parte": "arma", "osso": "Hand.R", "skinned": False},
        "sockets": {
            "RightGripAttachment": {
                "osso": "Hand.R",
                "posicao_m": [0.028, 0.056, -0.028],
                "rotacao_quat_wxyz": quat_y90,
            }
        },
        "files": [{"caminho": "arma.espada.01.glb", "papel": "mesh"}],
    }
    saida_acc = tmp_path / "espada.rbxmx"
    res_acc = rbx.exportar_acessorio_rbxmx(manifesto_acc, saida=saida_acc, mesh_id="rbxassetid://123456")
    assert res_acc["ok"] is True
    arvore_acc = ET.fromstring(res_acc["xml"])
    att_el = arvore_acc.find(".//Item[@class='Attachment']/Properties/CoordinateFrame[@name='CFrame']")
    assert att_el is not None
    pos_a, mat_a = _parse_cframe_node(att_el)
    assert pos_a == pytest.approx((0.1, 0.2, -0.1), abs=1e-4)
    assert _det3(mat_a) == pytest.approx(1.0, abs=1e-6)
    assert mat_a[0][2] == pytest.approx(1.0, abs=1e-5)

    # Verifica tambem offsets de sockets em Motor6D C0 e Attachments do rig R15
    saida_r15 = tmp_path / "r15_sock.rbxlx"
    manifesto_r15 = {
        "sockets": {
            "BodyBackAttachment": {
                "osso": "UpperTorso",
                "posicao_m": [0.0, 0.056, 0.14],
                "rotacao_quat_wxyz": [0.0, 0.0, 1.0, 0.0],
            },
            "RightWrist": {
                "osso": "RightHand",
                "posicao_m": [0.028, 0.0, 0.0],
                "rotacao_quat_wxyz": [0.70710678, 0.0, 0.70710678, 0.0],
            },
        }
    }
    rbx.exportar_r15(
        "examples/lote_09_r15.yaml",
        "personagem.r15.guard.01",
        saida=saida_r15,
        manifesto=manifesto_r15,
    )
    arvore_r15 = ET.parse(saida_r15)
    atts_r15: dict[str, ET.Element] = {}
    for item in arvore_r15.findall(".//Item[@class='Attachment']"):
        props = item.find("Properties")
        if props is not None:
            nome = props.findtext("string[@name='Name']", "")
            cf = props.find("CoordinateFrame[@name='CFrame']")
            if nome and cf is not None:
                atts_r15[nome] = cf
    _, mat_back = _parse_cframe_node(atts_r15["BodyBackAttachment"])
    assert _det3(mat_back) == pytest.approx(1.0, abs=1e-6)
    assert mat_back[0][0] == pytest.approx(-1.0, abs=1e-5)

    motores_r15: dict[str, ET.Element] = {}
    for item in arvore_r15.findall(".//Item[@class='Motor6D']"):
        props = item.find("Properties")
        if props is not None:
            nome = props.findtext("string[@name='Name']", "")
            cf0 = props.find("CoordinateFrame[@name='C0']")
            if nome and cf0 is not None:
                motores_r15[nome] = cf0
    _, mat_rw = _parse_cframe_node(motores_r15["RightWrist"])
    assert _det3(mat_rw) == pytest.approx(1.0, abs=1e-6)
    assert mat_rw[0][2] == pytest.approx(1.0, abs=1e-5)


def test_composicao_quaternions_multiplas_trilhas_mesma_junta_r15() -> None:
    clipe = {
        "nome": "combo",
        "duracao_s": 1.0,
        "loop": False,
        "chaves": [
            {
                "segundos": 0.5,
                "poses": [
                    {"osso": "LeftUpperArm", "eixo": "x", "graus": 90.0},
                    {"osso": "LeftUpperArm", "eixo": "z", "graus": 90.0},
                ],
            }
        ],
    }
    linhas, _ = rbx._sequencia_xml(clipe, 0)
    arvore = ET.fromstring("\n".join(linhas))
    poses_arm = [
        el
        for el in arvore.findall(".//Item[@class='Pose']")
        if el.findtext("Properties/string[@name='Name']") == "LeftUpperArm"
    ]
    assert len(poses_arm) == 1
    cf = poses_arm[0].find("Properties/CoordinateFrame[@name='CFrame']")
    assert cf is not None
    _, mat = _parse_cframe_node(cf)
    assert _det3(mat) == pytest.approx(1.0, abs=1e-6)
    # Se tivesse sobrescrito apenas com Z=90, R21 seria 0.0; com X=90 * Z=90 composto via quaternion, R20=-1.0 e R12=-1.0
    assert abs(mat[2][0]) > 0.9 or abs(mat[1][2]) > 0.9


def test_sockets_posicao_local_em_motor6d_c0_sem_dupla_divisao(tmp_path: Path) -> None:
    """F10: posicao_local (ja em studs) aplicada em Motor6D.C0 nao deve ser dividida por 0.28."""
    base_out = tmp_path / "r15_base.rbxlx"
    sock_out = tmp_path / "r15_local.rbxlx"
    rbx.exportar_r15("examples/lote_09_r15.yaml", "personagem.r15.guard.01", saida=base_out)
    rbx.exportar_r15(
        "examples/lote_09_r15.yaml",
        "personagem.r15.guard.01",
        saida=sock_out,
        sockets=[
            {
                "nome": "RightWrist",
                "osso": "RightHand",
                "posicao_local": [0.14, -0.28, 0.07],
            }
        ],
    )

    def _c0_motor(path: Path, motor_nome: str) -> tuple[float, float, float]:
        for m in ET.parse(path).findall(".//Item[@class='Motor6D']"):
            props = m.find("Properties")
            if props is not None and props.findtext("string[@name='Name']") == motor_nome:
                cf0 = props.find("CoordinateFrame[@name='C0']")
                assert cf0 is not None
                pos, _ = _parse_cframe_node(cf0)
                return pos
        raise AssertionError(f"Motor6D {motor_nome} ausente")

    base_c0 = _c0_motor(base_out, "RightWrist")
    sock_c0 = _c0_motor(sock_out, "RightWrist")
    assert (sock_c0[0] - base_c0[0], sock_c0[1] - base_c0[1], sock_c0[2] - base_c0[2]) == pytest.approx(
        (0.14, -0.28, 0.07), abs=1e-4
    )


def test_segmentada_r15_isola_motor6d_c0_de_sockets_autorig_e_aplica_em_attachments(tmp_path: Path) -> None:
    """Sockets de acessorio do autorig.py (Back/Hand.R/Hand.L/Head) nao deslocam/rotacionam Motor6D.C0."""
    partes_nomes = tuple(rbx.JOINT_R15.keys())
    lote = tmp_path / "lote_seg.yaml"
    lote.write_text(
        "\n".join(
            [
                "schema: forge3d/spec@6",
                "projeto: demo",
                "perfil: roblox-aa-80",
                f"destino_exportacao: {tmp_path / 'dest'}",
                "lote:",
                "  - id: boss.sock.seg.01",
                "    tipo: criatura",
                "    rota: mesh",
                "    prompt: golem",
                "    altura_metros: 2.2",
                "    seed: 1",
                "    auto_rig: true",
                "    esqueleto: r15@1",
                "    partes:",
                *[f"      - nome: {n}" for n in partes_nomes],
                "    rig:",
                "      modo: motor6d",
                "      esqueleto: r15@1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    ancoras = {n: [0.1 * (i % 3), 1.0 + i * 0.25, -0.05 * (i % 2)] for i, n in enumerate(partes_nomes)}
    man_base = {
        "schema": "forge3d/manifest@6",
        "asset_id": "boss.sock.seg.01",
        "partes": [
            {
                "nome": n,
                "junta": rbx.JOINT_R15[n],
                "ancora": ancoras[n],
                "bbox": [0.8, 0.8, 0.6],
                "arquivo": f"{n}.glb",
            }
            for n in partes_nomes
        ],
        "rig": {"esqueleto": "r15@1", "ossos": 16, "modo": "motor6d", "ancoras": ancoras},
        "files": [],
    }
    meio = math.pi / 4.0
    quat_x90 = [math.cos(meio), math.sin(meio), 0.0, 0.0]
    quat_y90 = [math.cos(meio), 0.0, math.sin(meio), 0.0]
    man_sock = {
        **man_base,
        "sockets": [
            {"nome": "Back", "osso": "UpperTorso", "posicao_local": [0.0, 0.1, 0.35], "rotacao_quat_wxyz": [1.0, 0.0, 0.0, 0.0]},
            {"nome": "Hand.R", "osso": "RightHand", "posicao_local": [0.02, 0.15, -0.05], "rotacao_quat_wxyz": quat_x90},
            {"nome": "Hand.L", "osso": "LeftHand", "posicao_local": [-0.02, 0.15, -0.05], "rotacao_quat_wxyz": quat_x90},
            {"nome": "Head", "osso": "Head", "posicao_local": [0.0, 0.2, 0.0], "rotacao_quat_wxyz": quat_y90},
        ],
    }
    out_base = tmp_path / "base.rbxlx"
    out_sock = tmp_path / "sock.rbxlx"
    rbx.exportar_r15(lote, "boss.sock.seg.01", saida=out_base, manifesto=man_base)
    rbx.exportar_r15(lote, "boss.sock.seg.01", saida=out_sock, manifesto=man_sock)

    def _ler_attachments(path: Path) -> dict[str, tuple[tuple[float, float, float], list[list[float]]]]:
        out: dict[str, tuple[tuple[float, float, float], list[list[float]]]] = {}
        for att in ET.parse(path).findall(".//Item[@class='Attachment']"):
            props = att.find("Properties")
            if props is None:
                continue
            nome = props.findtext("string[@name='Name']", "")
            cf = props.find("CoordinateFrame[@name='CFrame']")
            if nome and cf is not None:
                out[nome] = _parse_cframe_node(cf)
        return out

    raiz_sock = ET.parse(out_sock).getroot()
    part_pos_por_ref: dict[str, tuple[float, float, float]] = {}
    ref_para_nome: dict[str, str] = {}
    for item in raiz_sock.iter("Item"):
        if item.get("class") in ("Part", "MeshPart"):
            ref = item.get("referent") or ""
            props = item.find("Properties")
            if ref and props is not None:
                nome_p = props.findtext("string[@name='Name']", "")
                cf = props.find("CoordinateFrame[@name='CFrame']")
                if nome_p != "Baseplate" and cf is not None:
                    pos, _ = _parse_cframe_node(cf)
                    part_pos_por_ref[ref] = pos
                    ref_para_nome[ref] = nome_p

    motores = [m for m in raiz_sock.findall(".//Item[@class='Motor6D']")]
    assert len(motores) == 15
    identidade_flat = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
    for m in motores:
        props = m.find("Properties")
        assert props is not None
        r0 = props.findtext("Ref[@name='Part0']", "")
        r1 = props.findtext("Ref[@name='Part1']", "")
        cf0 = props.find("CoordinateFrame[@name='C0']")
        cf1 = props.find("CoordinateFrame[@name='C1']")
        assert cf0 is not None and cf1 is not None
        c0_pos, c0_mat = _parse_cframe_node(cf0)
        c1_pos, c1_mat = _parse_cframe_node(cf1)
        p0 = part_pos_por_ref[r0]
        p1 = part_pos_por_ref[r1]
        anchor = tuple(ancoras[ref_para_nome[r1]])
        assert tuple(p0[i] + c0_pos[i] for i in range(3)) == pytest.approx(anchor, abs=1e-5)
        assert tuple(p1[i] + c1_pos[i] for i in range(3)) == pytest.approx(anchor, abs=1e-5)
        assert [v for row in c0_mat for v in row] == pytest.approx(identidade_flat, abs=1e-6)
        assert [v for row in c1_mat for v in row] == pytest.approx(identidade_flat, abs=1e-6)

    att_base = _ler_attachments(out_base)
    att_sock = _ler_attachments(out_sock)
    for att_nome, delta in (
        ("BodyBackAttachment", (0.0, 0.1, 0.35)),
        ("RightGripAttachment", (0.02, 0.15, -0.05)),
        ("LeftGripAttachment", (-0.02, 0.15, -0.05)),
        ("HatAttachment", (0.0, 0.2, 0.0)),
    ):
        p_b, _ = att_base[att_nome]
        p_s, _ = att_sock[att_nome]
        assert tuple(p_s[i] - p_b[i] for i in range(3)) == pytest.approx(delta, abs=1e-4)
    _, mat_hat = att_sock["HatAttachment"]
    assert mat_hat[0][2] == pytest.approx(1.0, abs=1e-5)
    _, mat_rgrip = att_sock["RightGripAttachment"]
    assert mat_rgrip[2][1] == pytest.approx(1.0, abs=1e-5)
