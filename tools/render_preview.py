"""Preview de asset — render headless para revisar qualidade antes de abrir o jogo.

Uso:
    blender --background --factory-startup --python tools/render_preview.py -- \
        <arquivo.glb> <saida_sem_extensao> [--size 720] [--samples 32]

Gera ``<saida>_frente.png`` e ``<saida>_tres_quartos.png`` com camera ortografica,
tres luzes e piso, para julgar silhueta, proporcao, paleta e contato com o chao.
"""

from __future__ import annotations

import math
import os
import sys

import bpy
from mathutils import Vector

ORDEM = ["--size", "--samples"]


def _args() -> dict:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    if len(argv) < 2:
        raise SystemExit("uso: render_preview.py -- <glb> <saida> [--size N] [--samples N]")
    opcoes = {"glb": argv[0], "saida": argv[1], "size": 720, "samples": 32, "pose": False}
    resto = argv[2:]
    i = 0
    while i < len(resto):
        if resto[i] == "--size":
            opcoes["size"] = int(resto[i + 1])
            i += 2
        elif resto[i] == "--samples":
            opcoes["samples"] = int(resto[i + 1])
            i += 2
        elif resto[i] == "--pose":
            opcoes["pose"] = True
            i += 1
        else:
            i += 1
    return opcoes


def limpar() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def _formas_de_osso() -> set:
    """O importador glTF cria uma Icosphere como custom shape dos ossos — nao e asset."""
    formas = set()
    for obj in bpy.context.scene.objects:
        if obj.type != "ARMATURE":
            continue
        for osso in obj.pose.bones:
            if osso.custom_shape is not None:
                formas.add(osso.custom_shape.name)
    return formas


def bbox_objetos() -> tuple[Vector, Vector]:
    """Bbox da malha AVALIADA: inclui deformacao de armadura (asset com rig)."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    ignorar = _formas_de_osso()
    minimo = Vector((1e9, 1e9, 1e9))
    maximo = Vector((-1e9, -1e9, -1e9))
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH" or obj.name in ignorar:
            continue
        if obj.hide_render or obj.hide_viewport:
            continue
        avaliado = obj.evaluated_get(depsgraph)
        malha = avaliado.to_mesh()
        for vertice in malha.vertices:
            co = avaliado.matrix_world @ vertice.co
            for i in range(3):
                minimo[i] = min(minimo[i], co[i])
                maximo[i] = max(maximo[i], co[i])
        avaliado.to_mesh_clear()
    print(f"BBOX min={tuple(round(v, 4) for v in minimo)} max={tuple(round(v, 4) for v in maximo)}")
    return minimo, maximo


#: pose de validacao. Convencao medida nos ossos exportados (todos tem X local = +X do mundo,
#: Y local ao longo do osso): rotacao local X POSITIVA leva o membro para a frente (+Y);
#: joelho e cotovelo giram em sentidos OPOSTOS: antebraco vai a frente, panturrilha vai atras.
#: Ver docs/perfis-export.md §4 (convencao medida, nao convencao de mercado).
POSE_VALIDACAO = {
    "UpperArm.L": (22.0, 0.0, 0.0),     # ombro: leve a frente
    "LowerArm.L": (62.0, 0.0, 0.0),     # cotovelo: antebraco dobra para FRENTE (positivo)
    "UpperArm.R": (-4.0, 0.0, 0.0),
    "LowerArm.R": (16.0, 0.0, 0.0),
    "UpperLeg.L": (28.0, 0.0, 0.0),     # quadril: passo a frente
    "LowerLeg.L": (-42.0, 0.0, 0.0),    # joelho: panturrilha para TRAS (negativo)
    "Foot.L": (14.0, 0.0, 0.0),
    "UpperLeg.R": (-9.0, 0.0, 0.0),     # perna de tras
    "LowerLeg.R": (-6.0, 0.0, 0.0),
    "Head": (0.0, 0.0, 12.0),           # yaw
}


def aplicar_pose() -> None:
    from math import radians

    for obj in bpy.context.scene.objects:
        if obj.type != "ARMATURE":
            continue
        for osso in obj.pose.bones:
            if osso.name not in POSE_VALIDACAO:
                continue
            osso.rotation_mode = "XYZ"
            osso.rotation_euler = tuple(radians(a) for a in POSE_VALIDACAO[osso.name])
        print("POSE_APLICADA", len(POSE_VALIDACAO))


def piso(minimo: Vector, maximo: Vector) -> None:
    tam = max(maximo.x - minimo.x, maximo.y - minimo.y) * 3.0
    malha = bpy.data.meshes.new("piso")
    z = minimo.z
    malha.from_pydata(
        [
            (minimo.x - tam, minimo.y - tam, z),
            (maximo.x + tam, minimo.y - tam, z),
            (maximo.x + tam, maximo.y + tam, z),
            (minimo.x - tam, maximo.y + tam, z),
        ],
        [],
        [(0, 1, 2, 3)],
    )
    malha.update()
    obj = bpy.data.objects.new("piso", malha)
    bpy.context.collection.objects.link(obj)
    material = bpy.data.materials.new("piso")
    material.use_nodes = True
    bsdf = material.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (0.20, 0.21, 0.24, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.95
    obj.data.materials.append(material)


def luzes(centro: Vector, raio: float) -> None:
    def area(nome: str, direcao: Vector, energia: float, tamanho: float) -> None:
        dados = bpy.data.lights.new(nome, "AREA")
        dados.energy = energia
        dados.size = tamanho
        obj = bpy.data.objects.new(nome, dados)
        bpy.context.collection.objects.link(obj)
        obj.location = centro + direcao.normalized() * raio * 2.2
        direcao_para_centro = (centro - obj.location).normalized()
        obj.rotation_euler = direcao_para_centro.to_track_quat("-Z", "Y").to_euler()

    area("key", Vector((-0.7, 1.0, 1.2)), 150.0, raio * 2.0)
    area("fill", Vector((1.0, 0.6, 0.3)), 50.0, raio * 2.4)
    area("rim", Vector((0.2, -1.2, 0.9)), 110.0, raio * 1.6)


def camera(centro: Vector, raio: float, direcao: Vector, escala: float) -> None:
    dados = bpy.data.cameras.new("cam")
    dados.type = "ORTHO"
    dados.sensor_fit = "VERTICAL"
    dados.ortho_scale = escala
    obj = bpy.data.objects.new("cam", dados)
    bpy.context.collection.objects.link(obj)
    obj.location = centro + direcao.normalized() * raio * 6.0
    obj.rotation_euler = (centro - obj.location).normalized().to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.camera = obj


def configurar_render(saida: str, size: int, samples: int) -> None:
    cena = bpy.context.scene
    cena.render.resolution_x = size
    cena.render.resolution_y = int(size * 1.25)
    cena.render.resolution_percentage = 100
    cena.render.film_transparent = False
    cena.render.image_settings.file_format = "PNG"
    cena.render.filepath = saida
    cena.render.engine = "CYCLES"
    cena.cycles.device = "CPU"
    cena.cycles.samples = samples
    cena.cycles.use_denoising = True
    cena.view_settings.view_transform = "Standard"

    mundo = bpy.data.worlds.new("mundo")
    mundo.use_nodes = True
    fundo = mundo.node_tree.nodes.get("Background")
    fundo.inputs["Color"].default_value = (0.16, 0.17, 0.19, 1.0)
    fundo.inputs["Strength"].default_value = 0.55
    cena.world = mundo


def main() -> int:
    opcoes = _args()
    limpar()
    bpy.ops.import_scene.gltf(filepath=opcoes["glb"])
    if opcoes["pose"]:
        aplicar_pose()

    minimo, maximo = bbox_objetos()
    if minimo.x > 1e8:
        raise SystemExit("nenhuma malha no GLB")
    centro = (minimo + maximo) / 2.0
    raio = max((maximo - minimo).length / 2.0, 0.2)
    # enquadra pela altura, que e o eixo de comparacao do perfil
    raio = max(raio, (maximo.z - minimo.z) / 2.0 * 1.05)

    piso(minimo, maximo)
    luzes(centro, raio)

    # frente do asset e +Y no Blender (equivale a -Z no glTF, frente do Godot)
    altura_total = max(maximo.z - minimo.z, (maximo - minimo).length * 0.5)
    escala = altura_total * 1.25
    vistas = {
        "frente": Vector((0.0, 1.0, 0.08)),
        "tres_quartos": Vector((0.8, 1.0, 0.28)),
    }
    for nome, direcao in vistas.items():
        for obj in [o for o in bpy.context.scene.objects if o.type == "CAMERA"]:
            bpy.data.objects.remove(obj, do_unlink=True)
        camera(centro, raio, direcao, escala)
        configurar_render(f"{opcoes['saida']}_{nome}.png", opcoes["size"], opcoes["samples"])
        bpy.ops.render.render(write_still=True)
        print(f"RENDER_OK {opcoes['saida']}_{nome}.png")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
