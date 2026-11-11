"""C8/GAP-038: o G7 mede convexidade de verdade, nao so a existencia do colisor."""

from __future__ import annotations

import struct

from forge3d import qc

CUBO = [
    (-1.0, -1.0, -1.0),
    (1.0, -1.0, -1.0),
    (1.0, 1.0, -1.0),
    (-1.0, 1.0, -1.0),
    (-1.0, -1.0, 1.0),
    (1.0, -1.0, 1.0),
    (1.0, 1.0, 1.0),
    (-1.0, 1.0, 1.0),
]

FACES_CUBO = [
    (0, 1, 2),
    (0, 2, 3),
    (4, 6, 5),
    (4, 7, 6),
    (0, 4, 5),
    (0, 5, 1),
    (1, 5, 6),
    (1, 6, 2),
    (2, 6, 7),
    (2, 7, 3),
    (3, 7, 4),
    (3, 4, 0),
]


def _pacote(partes):
    """Monta (gltf, binario) no formato que o QC le, sem arquivo em disco."""
    dados = b""
    views = []
    acessores = []
    primitivas = []
    for posicoes, triangulos in partes:
        bytes_pos = b"".join(struct.pack("<3f", *p) for p in posicoes)
        bytes_idx = b"".join(struct.pack("<H", i) for t in triangulos for i in t)
        views.append({"buffer": 0, "byteOffset": len(dados), "byteLength": len(bytes_pos)})
        dados += bytes_pos
        views.append({"buffer": 0, "byteOffset": len(dados), "byteLength": len(bytes_idx)})
        dados += bytes_idx
        minimos = [min(p[i] for p in posicoes) for i in range(3)]
        maximos = [max(p[i] for p in posicoes) for i in range(3)]
        acessores.append(
            {
                "bufferView": len(views) - 2,
                "componentType": 5126,
                "count": len(posicoes),
                "type": "VEC3",
                "min": minimos,
                "max": maximos,
            }
        )
        acessores.append(
            {
                "bufferView": len(views) - 1,
                "componentType": 5123,
                "count": len(triangulos) * 3,
                "type": "SCALAR",
            }
        )
        primitivas.append(
            {"attributes": {"POSITION": len(acessores) - 2}, "indices": len(acessores) - 1, "mode": 4}
        )
    gltf = {"meshes": [{"primitives": primitivas}], "accessors": acessores, "bufferViews": views}
    return gltf, dados


def test_cubo_e_convexo():
    assert qc._convexo(CUBO, FACES_CUBO, 1e-9) is True


def test_vertice_para_dentro_torna_concavo():
    """Um canto puxado para dentro do hull e o caso que o gate antigo deixava passar."""
    furado = list(CUBO)
    furado[0] = (-0.2, -0.2, -0.2)
    assert qc._convexo(furado, FACES_CUBO, 1e-9) is False


def test_convexidade_por_componente_nao_condena_uniao_de_hulls():
    """Dois hulls soltos: a uniao nao e convexa, cada parte e (medir por componente)."""
    deslocado = [(x + 5.0, y, z) for x, y, z in CUBO]
    gltf, binario = _pacote([(CUBO, FACES_CUBO), (deslocado, FACES_CUBO)])
    medido = qc.convexidade(gltf, binario)
    assert medido["medida"] is True
    assert medido["partes"] == 2
    assert medido["convexo"] is True, medido


def test_convexidade_reprova_parte_concava():
    furado = list(CUBO)
    furado[0] = (-0.2, -0.2, -0.2)
    gltf, binario = _pacote([(furado, FACES_CUBO)])
    medido = qc.convexidade(gltf, binario)
    assert medido["convexo"] is False
    assert medido["concavas"] == 1
