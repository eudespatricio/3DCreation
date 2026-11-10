"""Normaliza a orientação de malha gerada: altura no eixo Z, base em Z=0, centro em X/Y.

Uso:
    blender --background --factory-startup --python tools/normalize_mesh.py -- \
        <entrada.glb> <saida.glb> [--eixo auto|x|y|z] [--frente +Y|-Y]

Por que existe: modelos image-to-3D (TripoSR e afins) **não** entregam frame canônico — verificado
em 10/11/2026 com dois inputs diferentes, o eixo de altura saiu em Y. Sem esta etapa, o asset chega
deitado no Godot e o QC de escala mede a dimensão errada.
"""

from __future__ import annotations

import math
import sys

import bpy
from mathutils import Matrix, Vector


def _args() -> dict:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    if len(argv) < 2:
        raise SystemExit("uso: normalize_mesh.py -- <entrada.glb> <saida.glb> [--eixo auto]")
    opcoes = {"entrada": argv[0], "saida": argv[1], "eixo": "auto"}
    i = 2
    while i < len(argv):
        if argv[i] == "--eixo" and i + 1 < len(argv):
            opcoes["eixo"] = argv[i + 1]
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

    eixo = opcoes["eixo"]
    if eixo == "auto":
        # a altura e o eixo de maior extensao; se ja for Z, nao rotaciona
        eixo = "xyz"[max(range(3), key=lambda i: extensao[i])]
    print("eixo_de_altura", eixo)

    rotacao = Matrix.Identity(4)
    if eixo == "y":  # Y -> Z: rotaciona -90 em X
        rotacao = Matrix.Rotation(math.radians(-90), 4, "X")
    elif eixo == "x":  # X -> Z: rotaciona 90 em Y
        rotacao = Matrix.Rotation(math.radians(90), 4, "Y")

    for obj in malhas:
        obj.matrix_world = rotacao @ obj.matrix_world
    bpy.context.view_layer.update()

    # base em Z=0 e centro em X/Y
    minimo, maximo = _bbox(malhas)
    centro = (minimo + maximo) / 2
    deslocamento = Matrix.Translation(Vector((-centro.x, -centro.y, -minimo.z)))
    for obj in malhas:
        obj.matrix_world = deslocamento @ obj.matrix_world
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
