"""Preview de asset — render headless para revisar qualidade antes de abrir o jogo.

Uso:
    blender --background --factory-startup --python tools/render_preview.py -- \
        <arquivo.glb> <saida_sem_extensao> [--size 720] [--samples 32] [--alto]

Gera ``<saida>_frente.png`` e ``<saida>_tres_quartos.png`` com camera ortografica,
tres luzes e piso, para julgar silhueta, proporcao, paleta e contato com o chao.
"""

from __future__ import annotations

import math
import shutil
import subprocess
import sys

try:
    import bpy
    from mathutils import Vector
except ModuleNotFoundError:
    if __name__ == "__main__":
        _bl_bin = shutil.which("blender") or "blender"
        _uargs = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:]
        raise SystemExit(
            subprocess.call(
                [_bl_bin, "--background", "--factory-startup", "--python", __file__, "--", *_uargs]
            )
        ) from None
    raise

ORDEM = ["--size", "--samples"]


def _args() -> dict:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:]
    opcoes: dict = {
        "glb": "",
        "saida": "",
        "size": 720,
        "samples": 32,
        "pose": False,
        "close": False,
        "alto": False,
        "turntable": False,
        "square": False,
    }
    posicionais: list[str] = []
    i = 0
    while i < len(argv):
        if argv[i] == "--size":
            opcoes["size"] = int(argv[i + 1])
            i += 2
        elif argv[i] == "--samples":
            opcoes["samples"] = int(argv[i + 1])
            i += 2
        elif argv[i] == "--pose":
            opcoes["pose"] = True
            i += 1
        elif argv[i] == "--close":
            opcoes["close"] = True
            i += 1
        elif argv[i] == "--alto":
            opcoes["alto"] = True
            i += 1
        elif argv[i] == "--turntable":
            opcoes["turntable"] = True
            i += 1
        elif argv[i] == "--square":
            opcoes["square"] = True
            i += 1
        else:
            posicionais.append(argv[i])
            i += 1
    if len(posicionais) < 2:
        raise SystemExit(
            "uso: render_preview.py [--turntable] <glb> <saida> [--size N] [--samples N]"
        )
    opcoes["glb"] = posicionais[0]
    opcoes["saida"] = posicionais[1]
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
    bsdf.inputs["Base Color"].default_value = (0.16, 0.17, 0.20, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.95
    if "Specular IOR Level" in bsdf.inputs:
        bsdf.inputs["Specular IOR Level"].default_value = 0.18
    obj.data.materials.append(material)


def luzes(centro: Vector, raio: float) -> None:
    fator_escala = max(1.0, (raio / 1.05) ** 2)

    def area(nome: str, direcao: Vector, energia: float, tamanho: float) -> None:
        dados = bpy.data.lights.new(nome, "AREA")
        dados.energy = energia * fator_escala
        dados.size = tamanho
        obj = bpy.data.objects.new(nome, dados)
        bpy.context.collection.objects.link(obj)
        obj.location = centro + direcao.normalized() * raio * 2.2
        direcao_para_centro = (centro - obj.location).normalized()
        obj.rotation_euler = direcao_para_centro.to_track_quat("-Z", "Y").to_euler()

    area("key", Vector((-0.7, 1.0, 1.2)), 65.0, raio * 2.0)
    area("fill", Vector((1.0, 0.6, 0.3)), 42.0, raio * 2.4)
    area("rim", Vector((0.2, -1.2, 0.9)), 45.0, raio * 1.6)


def camera(
    centro: Vector,
    raio: float,
    direcao: Vector,
    escala: float,
    *,
    perspectiva: bool = False,
) -> None:
    dados = bpy.data.cameras.new("cam")
    dados.sensor_fit = "VERTICAL"
    if perspectiva:
        dados.type = "PERSP"
        dados.lens = 50.0
        dist = max(raio * 3.8, escala * 2.15)
    else:
        dados.type = "ORTHO"
        dados.ortho_scale = escala
        dist = raio * 6.0
    obj = bpy.data.objects.new("cam", dados)
    bpy.context.collection.objects.link(obj)
    obj.location = centro + direcao.normalized() * dist
    obj.rotation_euler = (centro - obj.location).normalized().to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.camera = obj


def compor_contact_sheet_2x2(
    caminhos_4: tuple[str, str, str, str],
    destino_png: str,
) -> str:
    """Compoe 4 PNGs (TL=Front -Z, TR=Right +X, BL=Back +Z, BR=3/4 Persp) em contact sheet 2x2."""
    tl_path, tr_path, bl_path, br_path = caminhos_4
    imgs = [bpy.data.images.load(p, check_existing=False) for p in (tl_path, tr_path, bl_path, br_path)]
    try:
        w, h = int(imgs[0].size[0]), int(imgs[0].size[1])
        for im in imgs[1:]:
            if int(im.size[0]) != w or int(im.size[1]) != h:
                im.scale(w, h)
        px_tl = list(imgs[0].pixels)
        px_tr = list(imgs[1].pixels)
        px_bl = list(imgs[2].pixels)
        px_br = list(imgs[3].pixels)

        out_w = w * 2
        out_h = h * 2
        buf = [0.0] * (out_w * out_h * 4)
        row_len = w * 4
        out_row_len = out_w * 4

        for y in range(h):
            src_off = y * row_len
            # Parte inferior (y = 0..h-1 no buffer de imagem do Blender): BL (esq) e BR (dir)
            dst_bot = y * out_row_len
            buf[dst_bot : dst_bot + row_len] = px_bl[src_off : src_off + row_len]
            buf[dst_bot + row_len : dst_bot + out_row_len] = px_br[src_off : src_off + row_len]
            # Parte superior (y = h..2h-1): TL (esq) e TR (dir)
            dst_top = (y + h) * out_row_len
            buf[dst_top : dst_top + row_len] = px_tl[src_off : src_off + row_len]
            buf[dst_top + row_len : dst_top + out_row_len] = px_tr[src_off : src_off + row_len]

        sheet = bpy.data.images.new("turntable_2x2", width=out_w, height=out_h, alpha=True)
        try:
            sheet.pixels.foreach_set(buf)
            sheet.filepath_raw = destino_png
            sheet.file_format = "PNG"
            sheet.save()
        finally:
            bpy.data.images.remove(sheet)
    finally:
        for im in imgs:
            bpy.data.images.remove(im)
    return destino_png


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
    for transform in ("AgX", "Filmic", "Standard"):
        try:
            cena.view_settings.view_transform = transform
            break
        except (TypeError, ValueError):
            continue
    try:
        cena.view_settings.look = "None"
    except (TypeError, ValueError):
        pass

    mundo = bpy.data.worlds.new("mundo")
    mundo.use_nodes = True
    fundo = mundo.node_tree.nodes.get("Background")
    fundo.inputs["Color"].default_value = (0.16, 0.17, 0.19, 1.0)
    fundo.inputs["Strength"].default_value = 0.45
    cena.world = mundo


def main() -> int:
    opcoes = _args()
    limpar()
    bpy.ops.import_scene.gltf(filepath=opcoes["glb"])
    if opcoes["pose"]:
        aplicar_pose()
    else:
        for obj in bpy.context.scene.objects:
            if obj.type == "ARMATURE":
                if obj.animation_data is not None:
                    obj.animation_data.action = None
                for pb in obj.pose.bones:
                    pb.location = (0.0, 0.0, 0.0)
                    pb.rotation_quaternion = (1.0, 0.0, 0.0, 0.0)
                    pb.rotation_euler = (0.0, 0.0, 0.0)
                    pb.scale = (1.0, 1.0, 1.0)
        bpy.context.view_layer.update()

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
    # asset largo e baixo (setor de dungeon 4x4x2,4 m) estoura a moldura quando a escala vem
    # so da altura: a diagonal do footprint tambem manda. Personagem (0,9 m) nao muda.
    escala = max(escala, math.hypot(maximo.x - minimo.x, maximo.y - minimo.y) * 1.25)
    vistas = {
        "frente": Vector((0.0, 1.0, 0.08)),
        "tres_quartos": Vector((0.8, 1.0, 0.28)),
    }
    vistas_persp: set[str] = set()
    if opcoes["turntable"]:
        # 2x2 contact sheet: Front -Z (+Y Blender), Right +X (-X Blender), Back +Z (-Y Blender), 3/4 Perspective
        vistas = {
            "frente": Vector((0.0, 1.0, 0.08)),
            "direita": Vector((-1.0, 0.0, 0.08)),
            "costas": Vector((0.0, -1.0, 0.08)),
            "tres_quartos": Vector((0.8, 1.0, 0.28)),
        }
        vistas_persp.add("tres_quartos")
    if opcoes["close"]:
        # close-up do terco superior: e onde densidade de texel e detalhe aparecem
        centro = Vector((0.0, 0.0, maximo.z - altura_total * 0.22))
        escala = altura_total * 0.42
        vistas = {"close": Vector((0.55, 1.0, 0.18))}
    if opcoes["alto"]:
        # vista de cima: e a unica que mostra o lado fechado continuo de um setor (GAP-047)
        vistas["alto"] = Vector((0.55, 0.75, 1.0))

    saida_base = opcoes["saida"][:-4] if opcoes["saida"].lower().endswith(".png") else opcoes["saida"]
    gerados: dict[str, str] = {}
    for nome, direcao in vistas.items():
        for obj in [o for o in bpy.context.scene.objects if o.type == "CAMERA"]:
            bpy.data.objects.remove(obj, do_unlink=True)
        camera(centro, raio, direcao, escala, perspectiva=(nome in vistas_persp))
        arq_vista = f"{saida_base}_{nome}.png"
        configurar_render(arq_vista, opcoes["size"], opcoes["samples"])
        if nome == "alto" or opcoes["square"]:
            # a vista de cima enquadra o footprint inteiro: moldura quadrada, nao retrato
            bpy.context.scene.render.resolution_y = opcoes["size"]
        bpy.ops.render.render(write_still=True)
        gerados[nome] = arq_vista
        print(f"RENDER_OK {arq_vista}")

    if opcoes["turntable"] and all(k in gerados for k in ("frente", "direita", "costas", "tres_quartos")):
        destino_sheet = (
            opcoes["saida"]
            if opcoes["saida"].lower().endswith(".png")
            else f"{saida_base}_turntable.png"
        )
        compor_contact_sheet_2x2(
            (
                gerados["frente"],
                gerados["direita"],
                gerados["costas"],
                gerados["tres_quartos"],
            ),
            destino_sheet,
        )
        print(f"RENDER_TURNTABLE_OK {destino_sheet}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
