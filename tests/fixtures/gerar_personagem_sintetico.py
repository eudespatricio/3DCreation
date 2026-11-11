"""Gera a fixture sintetica do GAP-048: personagem com prop grande, upright e invertido.

Roda no Blender. Constroi um boneco de caixas (sem IP) com:
  * sola chata (placa larga no pe) e cabeca estreita/arredondada no topo;
  * "arma" lateral grande, que infla a banda de area nas duas pontas;
  * gola larga perto do topo, para a razao topo/base ficar ~1 (neutralizando a regra antiga).
Salva os dois glb em tests/fixtures/ e imprime as metricas das regras antigas.
"""
import json
import math
import os

import bmesh
import bpy

SAIDA = os.path.join(os.path.dirname(os.path.abspath(__file__)))


def caixa(nome, x0, x1, y0, y1, z0, z1):
    me = bpy.data.meshes.new(nome)
    vs = [
        (x0, y0, z0),
        (x1, y0, z0),
        (x1, y1, z0),
        (x0, y1, z0),
        (x0, y0, z1),
        (x1, y0, z1),
        (x1, y1, z1),
        (x0, y1, z1),
    ]
    fs = [
        (0, 3, 2, 1),
        (4, 5, 6, 7),
        (0, 1, 5, 4),
        (1, 2, 6, 5),
        (2, 3, 7, 6),
        (3, 0, 4, 7),
    ]
    me.from_pydata(vs, [], fs)
    me.update()
    return bpy.data.objects.new(nome, me)


def montar():
    pecas = []

    def add(nome, x0, x1, y0, y1, z0, z1):
        obj = caixa(nome, x0, x1, y0, y1, z0, z1)
        bpy.context.collection.objects.link(obj)
        pecas.append(obj)

    # sola chata: placa larga em contato com o chao
    add("sola", -0.30, 0.30, -0.12, 0.12, 0.00, 0.06)
    # pernas finas (vao entre elas)
    add("perna_e", -0.10, -0.04, -0.06, 0.06, 0.06, 0.78)
    add("perna_d", 0.04, 0.10, -0.06, 0.06, 0.06, 0.78)
    # tronco
    add("tronco", -0.22, 0.22, -0.12, 0.12, 0.78, 1.36)
    # cabeca estreita no topo (ponta arredondada = fatia fina pequena)
    add("cabeca", -0.09, 0.09, -0.09, 0.09, 1.44, 1.55)
    # gola larga logo abaixo do topo: infla a banda superior sem inflar a fatia fina do topo
    add("gola", -0.35, 0.35, -0.15, 0.15, 1.30, 1.44)
    # "arma" grande ao lado: infla a banda inferior e a largura (o caso real da besta)
    add("arma", 0.24, 0.52, -0.08, 0.08, 0.30, 1.10)

    bpy.context.view_layer.objects.active = pecas[0]
    for obj in pecas:
        obj.select_set(True)
    bpy.ops.object.join()
    obj = bpy.context.view_layer.objects.active
    obj.name = "personagem"
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    # a medicao de faixa e por vertice: sem subdividir, as caixas so tem vertice na quina
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.subdivide(number_cuts=7)
    bpy.ops.object.mode_set(mode="OBJECT")
    return obj


def metricas(obj):
    vs = [obj.matrix_world @ v.co for v in obj.data.vertices]
    zmin = min(v.z for v in vs)
    zmax = max(v.z for v in vs)
    h = zmax - zmin
    n = 12
    areas = []
    for i in range(n):
        z0, z1 = zmin + h * i / n, zmin + h * (i + 1) / n
        faixa = [v for v in vs if z0 <= v.z <= z1]
        if not faixa:
            areas.append(0.0)
            continue
        xs = [v.x for v in faixa]
        ys = [v.y for v in faixa]
        areas.append((max(xs) - min(xs)) * (max(ys) - min(ys)))
    total = sum(areas) or 1.0
    centro = sum(a * (i + 0.5) for i, a in enumerate(areas)) / total
    razao = areas[-1] / areas[0] if areas[0] else 0.0

    def contato(z0, z1):
        faixa = [v for v in vs if z0 <= v.z <= z1]
        if not faixa:
            return 0.0
        xs = [v.x for v in faixa]
        ys = [v.y for v in faixa]
        return (max(xs) - min(xs)) * (max(ys) - min(ys))

    d = h * 0.02
    return {
        "altura": round(h, 4),
        "areas": [round(a, 5) for a in areas],
        "centro_area": round(centro, 3),
        "razao_topo_base": round(razao, 3),
        "contato_base": round(contato(zmin, zmin + d), 5),
        "contato_topo": round(contato(zmax - d, zmax), 5),
        "centro_limite": round(0.48 * n, 2),
    }


bpy.ops.wm.read_factory_settings(use_empty=True)
obj = montar()
m_up = metricas(obj)
bpy.ops.export_scene.gltf(filepath=os.path.join(SAIDA, "personagem_upright.glb"), export_format="GLB")
print("UPRIGHT", json.dumps(m_up))

# inverte 180 no X: (y,z) -> (-y,-z), depois normaliza a base em z=0
bpy.context.view_layer.objects.active = obj
obj.rotation_mode = "XYZ"
obj.rotation_euler[0] = math.pi
bpy.ops.object.transform_apply(location=False, rotation=True, scale=False)
vs = [v.co for v in obj.data.vertices]
dz = min(v.z for v in vs)
for v in obj.data.vertices:
    v.co.z -= dz
obj.data.update()
bm = bmesh.new()
bm.from_mesh(obj.data)
bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
bm.to_mesh(obj.data)
bm.free()
obj.data.update()

m_inv = metricas(obj)
bpy.ops.export_scene.gltf(filepath=os.path.join(SAIDA, "personagem_invertido.glb"), export_format="GLB")
print("INVERTIDO", json.dumps(m_inv))
print("GEN_OK")
