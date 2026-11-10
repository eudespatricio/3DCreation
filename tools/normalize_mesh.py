"""Normaliza a orientação de malha gerada: altura em Z, largura em X, profundidade em Y, base em Z=0.

Uso:
    blender --background --factory-startup --python tools/normalize_mesh.py -- \
        <entrada.glb> <saida.glb> [--eixo auto|x|y|z] [--girar 0|90|180|270]

Por que existe (medido em 10/11/2026, três inputs diferentes): modelos image-to-3D não entregam frame
canônico. O TripoSR devolveu altura em Y nos dois primeiros testes e **giro de 90° na vertical** no
terceiro (T-pose com os braços apontando para a câmera). Sem esta etapa o asset chega deitado ou de
perfil no Godot, e o QC de escala mede a dimensão errada.

Heurística (figura humanoide em pé ou em T-pose):
    profundidade = eixo de MENOR extensão   (um corpo é fino no eixo frente-trás)
    altura       = maior extensão entre os dois eixos restantes
    largura      = o eixo que sobra
A rotação aplicada é uma permutação de eixos com determinante +1 (nunca espelha a malha).
"""

from __future__ import annotations

import math
import sys

import bpy
from mathutils import Matrix, Vector

EIXOS = "XYZ"


def _args() -> dict:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    if len(argv) < 2:
        raise SystemExit("uso: normalize_mesh.py -- <entrada.glb> <saida.glb> [--eixo auto] [--girar N]")
    opcoes = {"entrada": argv[0], "saida": argv[1], "eixo": "auto", "girar": 0}
    i = 2
    while i < len(argv):
        if argv[i] == "--eixo" and i + 1 < len(argv):
            opcoes["eixo"] = argv[i + 1]
            i += 2
        elif argv[i] == "--girar" and i + 1 < len(argv):
            opcoes["girar"] = int(argv[i + 1])
            i += 2
        else:
            i += 1
    return opcoes


def _bbox(objetos) -> tuple[Vector, Vector]:
    minimo = Vector((1e18, 1e18, 1e18))
    maximo = Vector((-1e18, -1e18, -1e18))
    for obj in objetos:
        for v in obj.data.vertices:
            co = obj.matrix_world @ v.co
            for i in range(3):
                minimo[i] = min(minimo[i], co[i])
                maximo[i] = max(maximo[i], co[i])
    return minimo, maximo


def _rotacao_para_canonico(extensao: Vector, eixo_forcado: str) -> tuple[Matrix, str]:
    """Permutação de eixos: altura->Z, largura->X, profundidade->Y. Determinante +1."""
    ordens = sorted(range(3), key=lambda i: extensao[i])
    if eixo_forcado != "auto" and eixo_forcado.upper() in EIXOS:
        indice_altura = EIXOS.index(eixo_forcado.upper())
        resto = [i for i in range(3) if i != indice_altura]
        indice_profundidade = min(resto, key=lambda i: extensao[i])
        indice_largura = max(resto, key=lambda i: extensao[i])
        descricao = f"forcado {eixo_forcado}"
    else:
        indice_profundidade = ordens[0]
        sobra = [i for i in range(3) if i != indice_profundidade]
        indice_altura = max(sobra, key=lambda i: extensao[i])
        indice_largura = min(sobra, key=lambda i: extensao[i])
        descricao = "heuristica"

    # alvo X <- largura, alvo Y <- profundidade, alvo Z <- altura (matriz por LINHAS)
    destinos = (indice_largura, indice_profundidade, indice_altura)
    linhas = []
    for origem in destinos:
        linha = [0.0, 0.0, 0.0]
        linha[origem] = 1.0
        linhas.append(linha)

    if Matrix(linhas).determinant() < 0:
        # permutacao impar espelharia a malha (logo/texto invertido): nega o eixo de profundidade
        linhas[1] = [-v for v in linhas[1]]
        descricao += "+frente invertida"

    rot = Matrix(linhas).to_4x4()
    return rot, (
        f"{descricao} | altura={EIXOS[indice_altura]} largura={EIXOS[indice_largura]} "
        f"profundidade={EIXOS[indice_profundidade]}"
    )


def main() -> int:
    opcoes = _args()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=opcoes["entrada"])

    malhas = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    if not malhas:
        raise SystemExit("sem malha no arquivo")

    minimo, maximo = _bbox(malhas)
    extensao = maximo - minimo
    print("extensao_entrada", tuple(round(v, 4) for v in extensao))

    rotacao, descricao = _rotacao_para_canonico(extensao, opcoes["eixo"])
    print("mapeamento", descricao)

    for obj in malhas:
        obj.matrix_world = rotacao @ obj.matrix_world
    if opcoes["girar"]:
        giro = Matrix.Rotation(math.radians(opcoes["girar"]), 4, "Z")
        for obj in malhas:
            obj.matrix_world = giro @ obj.matrix_world
        print("giro_z_graus", opcoes["girar"])
    bpy.context.view_layer.update()

    minimo, maximo = _bbox(malhas)
    centro = (minimo + maximo) / 2
    for obj in malhas:
        obj.matrix_world = Matrix.Translation(Vector((-centro.x, -centro.y, -minimo.z))) @ obj.matrix_world
    bpy.context.view_layer.update()

    minimo, maximo = _bbox(malhas)
    extensao = maximo - minimo
    print("extensao_saida", tuple(round(v, 4) for v in extensao))
    print("base_z", round(minimo.z, 6))

    for obj in malhas:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = malhas[0]
    bpy.ops.export_scene.gltf(
        filepath=opcoes["saida"],
        export_format="GLB",
        use_selection=True,
        export_apply=True,
        export_yup=True,
    )
    print("NORMALIZADO", opcoes["saida"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
