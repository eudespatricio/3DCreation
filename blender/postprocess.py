"""Script bpy do Forge3D — roda com ``blender --background --python``.

Canal unico: arquivo JSON de entrada e arquivo JSON de saida (I9). Nada de parse de stdout.

Etapas: construir geometria -> rig -> normalizar escala/pivo -> LOD -> colisor -> exportar GLB
-> medir. O script nao decide qualidade nem aprova nada: ele mede e exporta. Quem reprova e o QC.
"""

from __future__ import annotations

import json
import os
import sys
import traceback

import bmesh
import bpy
from mathutils import Matrix, Vector

# faces de um cubo por indice de vertice; a orientacao e corrigida depois por recalc
FACES_CUBO = (
    (0, 3, 2, 1),
    (4, 5, 6, 7),
    (0, 1, 5, 4),
    (2, 3, 7, 6),
    (3, 0, 4, 7),
    (1, 2, 6, 5),
)


# ------------------------------------------------------------------ utilidades


def jload(caminho: str) -> dict:
    with open(caminho, encoding="utf-8") as fh:
        return json.load(fh)


def jsave(caminho: str, obj: dict) -> None:
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    with open(caminho, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, sort_keys=True, indent=1)
        fh.write("\n")


def limpar_cena() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def objetos_malha() -> list:
    return [o for o in bpy.context.scene.objects if o.type == "MESH"]


# ------------------------------------------------------------------ construcao


def material_atlas(atlas: str) -> "bpy.types.Material":
    mat = bpy.data.materials.new("forge3d_atlas")
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = bpy.data.images.load(atlas, check_existing=False)
    tex.interpolation = "Closest"
    tex.extension = "EXTEND"
    tex.location = (-420, 260)
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    if "Roughness" in bsdf.inputs:
        bsdf.inputs["Roughness"].default_value = 0.85
    if "Metallic" in bsdf.inputs:
        bsdf.inputs["Metallic"].default_value = 0.0
    return mat


def construir_blocky(bruto: dict, base_dir: str) -> tuple:
    """Uma malha com todas as caixas + atribuicao rigida de osso por vertice."""
    verts: list[tuple] = []
    faces: list[tuple] = []
    uvs: list[tuple] = []
    grupos: dict[str, list[int]] = {}

    for caixa in bruto["caixas"]:
        i0 = len(verts)
        x0, y0, z0 = caixa["min"]
        x1, y1, z1 = caixa["max"]
        verts.extend(
            [
                (x0, y0, z0),
                (x1, y0, z0),
                (x1, y1, z0),
                (x0, y1, z0),
                (x0, y0, z1),
                (x1, y0, z1),
                (x1, y1, z1),
                (x0, y1, z1),
            ]
        )
        for face in FACES_CUBO:
            faces.append(tuple(i0 + i for i in face))
        regiao = caixa["uv"]
        regiao_topo = caixa.get("uv_topo") or regiao
        for indice_face in range(6):
            # face 1 de FACES_CUBO e o topo: recebe a celula clareada
            u0, v0, u1, v1 = regiao_topo if indice_face == 1 else regiao
            uvs.extend([(u0, v0), (u1, v0), (u1, v1), (u0, v1)])
        osso = caixa.get("osso")
        if osso:
            grupos.setdefault(osso, []).extend(range(i0, i0 + 8))

    malha = bpy.data.meshes.new("forge3d_mesh")
    malha.from_pydata(verts, [], faces)
    malha.update()

    camada_uv = malha.uv_layers.new(name="UVMap")
    for indice, loop in enumerate(malha.loops):
        camada_uv.data[loop.index].uv = uvs[indice]

    obj = bpy.data.objects.new("forge3d_asset", malha)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(material_atlas(os.path.join(base_dir, bruto["atlas"])))

    # normais para fora (winding consistente, independente da ordem em que as faces nasceram)
    bm = bmesh.new()
    bm.from_mesh(malha)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(malha)
    bm.free()
    malha.update()

    for osso, indices in grupos.items():
        grupo = obj.vertex_groups.new(name=osso)
        grupo.add(indices, 1.0, "REPLACE")

    return obj, grupos


def criar_armadura(ossos: list[dict], nome: str = "Armature") -> "bpy.types.Object":
    arm = bpy.data.armatures.new("forge3d_rig")
    obj = bpy.data.objects.new(nome, arm)
    bpy.context.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)

    bpy.ops.object.mode_set(mode="EDIT")
    criados = {}
    for osso in ossos:
        eb = arm.edit_bones.new(osso["nome"])
        eb.head = Vector(osso["cabeca"])
        eb.tail = Vector(osso["cauda"])
        criados[osso["nome"]] = eb
    for osso in ossos:
        pai = osso.get("pai")
        if pai and pai in criados and pai != osso["nome"]:
            criados[osso["nome"]].parent = criados[pai]
            criados[osso["nome"]].use_connect = False
    bpy.ops.object.mode_set(mode="OBJECT")
    obj.select_set(False)
    return obj


def importar_fonte(arquivo: str) -> None:
    ext = os.path.splitext(arquivo)[1].lower()
    if ext == ".glb" or ext == ".gltf":
        bpy.ops.import_scene.gltf(filepath=arquivo)
    elif ext == ".obj":
        if bpy.app.version >= (4, 0, 0):
            bpy.ops.wm.obj_import(filepath=arquivo)
        else:  # pragma: no cover - so 4.2 e suportado
            bpy.ops.import_scene.obj(filepath=arquivo)
    elif ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=arquivo)
    elif ext == ".blend":
        with bpy.data.libraries.load(arquivo, link=False) as (de, para):
            para.objects = [n for n in de.objects]
        for obj in para.objects:
            if obj is not None:
                bpy.context.collection.objects.link(obj)
    else:
        raise RuntimeError(f"formato de origem nao suportado: {ext}")



# ------------------------------------------------------------------ malha gerada (P3-A)


TEX_PX_GERADA = 512


def _selecionar(obj) -> None:
    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)


def _aplicar_transformes(obj) -> None:
    _selecionar(obj)
    if obj.parent is not None:
        bpy.ops.object.parent_clear(type="CLEAR_KEEP_TRANSFORM")
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)


def unir_malhas() -> "bpy.types.Object":
    """Uma malha so: o gerador pode devolver varias; o pos-processo trata um asset."""
    malhas = objetos_malha()
    if not malhas:
        raise RuntimeError("origem sem malha importavel")
    if len(malhas) == 1:
        obj = malhas[0]
        _aplicar_transformes(obj)
        return obj
    for obj in malhas:
        _aplicar_transformes(obj)
    bpy.ops.object.select_all(action="DESELECT")
    for obj in malhas:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = malhas[0]
    bpy.ops.object.join()
    return bpy.context.view_layer.objects.active


def _remover_ilhas_de_uma_face(bm) -> int:
    """Ilha de uma face minuscula (sobra de decimate) vira borda aberta no G1."""
    vistos = set()
    remover = []
    for face in bm.faces:
        if face.index in vistos:
            continue
        pilha = [face]
        componente = []
        vistos.add(face.index)
        while pilha:
            atual = pilha.pop()
            componente.append(atual)
            for aresta in atual.edges:
                for vizinha in aresta.link_faces:
                    if vizinha.index not in vistos:
                        vistos.add(vizinha.index)
                        pilha.append(vizinha)
        # qualquer ilha de uma face e sobra: nao e geometria de asset
        if len(componente) == 1:
            remover.append(componente[0])
    if remover:
        bmesh.ops.delete(bm, geom=remover, context="FACES")
        soltos = [v for v in bm.verts if not v.link_faces]
        if soltos:
            bmesh.ops.delete(bm, geom=soltos, context="VERTS")
    return len(remover)


def reparar_malha(obj) -> dict:
    """Solda, remove ilha solta e fecha buraco antes do export."""
    antes = (len(obj.data.vertices), len(obj.data.polygons))
    obj.data.validate(verbose=False)
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1e-5)
    bmesh.ops.dissolve_degenerate(bm, dist=1e-6, edges=list(bm.edges))
    ilhas = _remover_ilhas_de_uma_face(bm)
    bordas = [e for e in bm.edges if len(e.link_faces) == 1]
    if bordas:
        bmesh.ops.holes_fill(bm, edges=bordas, sides=0)
        # holes_fill pode criar uma face solta; remove de novo
        _remover_ilhas_de_uma_face(bm)
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
    return {
        "vertices_antes": antes[0],
        "faces_antes": antes[1],
        "vertices_depois": len(obj.data.vertices),
        "faces_depois": len(obj.data.polygons),
        "ilhas_removidas": ilhas,
        "bordas_preenchidas": len(bordas),
    }


def decimar(obj, alvo_tris: int) -> int:
    tris = malha_triangulada(obj)
    if alvo_tris <= 0 or tris <= alvo_tris:
        return tris
    mod = obj.modifiers.new("forge3d_decimate", "DECIMATE")
    mod.ratio = max(0.01, min(1.0, (alvo_tris * 0.995) / tris))
    _selecionar(obj)
    bpy.ops.object.modifier_apply(modifier=mod.name)
    return malha_triangulada(obj)


def _extensao_faixa(obj, z0: float, z1: float) -> float:
    """Area da faixa horizontal [z0,z1] no plano XY: cabeca fina vs base larga."""
    xs: list[float] = []
    ys: list[float] = []
    for v in obj.data.vertices:
        co = obj.matrix_world @ v.co
        if z0 <= co.z <= z1:
            xs.append(co.x)
            ys.append(co.y)
    if not xs:
        return 0.0
    return (max(xs) - min(xs)) * (max(ys) - min(ys))


def canonicalizar(obj, tipo: str | None = None) -> dict:
    """Altura em Z, largura em X, profundidade em Y, base em Z=0 (tools/normalize_mesh.py).

    Para humanoide/criatura, corrige o caso em que a cabeca (faixa estreita) caiu embaixo: espelha
    Z, preservando frente e lados, e recalcula normais. Medido no sentinela da P3.5: o TripoSR
    devolveu o corpo de cabeca para baixo e o G2 passava (altura certa) sem essa checagem.
    """
    minimo, maximo = bbox_local()
    extensao = maximo - minimo
    ordem = sorted(range(3), key=lambda i: extensao[i])
    profundidade = ordem[0]
    sobra = [i for i in range(3) if i != profundidade]
    altura = max(sobra, key=lambda i: extensao[i])
    largura = min(sobra, key=lambda i: extensao[i])
    destinos = (largura, profundidade, altura)
    linhas = []
    for origem in destinos:
        linha = [0.0, 0.0, 0.0]
        linha[origem] = 1.0
        linhas.append(linha)
    if Matrix(linhas).determinant() < 0:
        # permutacao impar espelharia a malha (logo/texto invertido)
        linhas[1] = [-v for v in linhas[1]]
    rot = Matrix(linhas).to_4x4()
    obj.matrix_world = rot @ obj.matrix_world
    _aplicar_transformes(obj)
    minimo, maximo = bbox_local()
    desloc = Vector(
        (-(minimo.x + maximo.x) / 2.0, -(minimo.y + maximo.y) / 2.0, -minimo.z)
    )
    obj.matrix_world = Matrix.Translation(desloc) @ obj.matrix_world
    _aplicar_transformes(obj)

    info = {
        "altura_eixo": "XYZ"[altura],
        "largura_eixo": "XYZ"[largura],
        "profundidade_eixo": "XYZ"[profundidade],
    }
    if tipo in ("personagem_humanoide", "criatura"):
        minimo, maximo = bbox_local()
        altura_z = maximo.z - minimo.z
        # perfil de area em 12 faixas: em T-pose os bracos/ombros puxam o centro para cima
        n = 12
        areas = []
        for i in range(n):
            z0 = minimo.z + altura_z * i / n
            z1 = minimo.z + altura_z * (i + 1) / n
            areas.append(_extensao_faixa(obj, z0, z1))
        total = sum(areas)
        centro = (
            sum(a * (i + 0.5) for i, a in enumerate(areas)) / total if total else 0.0
        )
        info["centro_area"] = round(centro, 3)
        info["areas"] = [round(a, 6) for a in areas]
        if total > 0 and centro < n * 0.48:
            # espelha Z: mantem frente (+Y) e lados (+-X), corrige cabeca para cima
            for v in obj.data.vertices:
                v.co.z = -v.co.z
            obj.data.update()
            bm = bmesh.new()
            bm.from_mesh(obj.data)
            bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
            bm.to_mesh(obj.data)
            bm.free()
            obj.data.update()
            minimo, _maximo = bbox_local()
            for v in obj.data.vertices:
                v.co.z -= minimo.z
            obj.data.update()
            info["invertido"] = True
        else:
            info["invertido"] = False
    return info

def desdobrar_uv(obj, margem: float = 0.003) -> str:
    _selecionar(obj)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(
        angle_limit=1.15192,  # 66 graus
        island_margin=margem,
        area_weight=0.0,
        correct_aspect=True,
        scale_to_bounds=False,
    )
    bpy.ops.object.mode_set(mode="OBJECT")
    if not obj.data.uv_layers:
        raise RuntimeError("smart_project nao criou camada UV")
    return obj.data.uv_layers.active.name


def assar_cor_vertices(obj, png: str, px: int) -> dict:
    """Bake DIFFUSE/COLOR da cor por vertice para PNG e troca o material por textura."""
    if not obj.data.color_attributes:
        raise RuntimeError("malha sem atributo de cor por vertice para assar")
    nome_cor = obj.data.color_attributes[0].name
    obj.data.materials.clear()
    mat = bpy.data.materials.new("forge3d_bake")
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    if "Roughness" in bsdf.inputs:
        bsdf.inputs["Roughness"].default_value = 0.85
    if "Metallic" in bsdf.inputs:
        bsdf.inputs["Metallic"].default_value = 0.0
    vc = nt.nodes.new("ShaderNodeVertexColor")
    vc.layer_name = nome_cor
    nt.links.new(vc.outputs["Color"], bsdf.inputs["Base Color"])
    img = bpy.data.images.new("forge3d_baseColor", width=px, height=px, alpha=False)
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = img
    tex.select = True
    nt.nodes.active = tex
    obj.data.materials.append(mat)

    cena = bpy.context.scene
    cena.render.engine = "CYCLES"
    cena.cycles.device = "CPU"
    cena.cycles.samples = 1
    cena.cycles.use_denoising = False
    cena.render.bake.use_pass_direct = False
    cena.render.bake.use_pass_indirect = False
    cena.render.bake.use_pass_color = True
    cena.render.bake.margin = max(4, px // 128)
    cena.render.bake.use_clear = True
    _selecionar(obj)
    bpy.ops.object.bake(type="DIFFUSE")

    img.filepath_raw = png
    img.file_format = "PNG"
    img.save()
    img.pack()
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    nt.nodes.remove(vc)
    for atributo in list(obj.data.color_attributes):
        obj.data.color_attributes.remove(atributo)
    return {
        "textura_px": px,
        "cor_atributo": nome_cor,
        "png_bytes": os.path.getsize(png),
    }


# ------------------------------------------------------------------ geometria


def transformar_armadura(rig, escala: float, deslocamento: Vector) -> None:
    """Ossos acompanham a geometria: skinning rigido exige osso e vertice no mesmo espaco."""
    bpy.context.view_layer.objects.active = rig
    rig.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    for osso in rig.data.edit_bones:
        osso.head = (osso.head * escala) + deslocamento
        osso.tail = (osso.tail * escala) + deslocamento
    bpy.ops.object.mode_set(mode="OBJECT")
    rig.select_set(False)


def bbox_local() -> tuple[Vector, Vector]:
    minimo = Vector((float("inf"),) * 3)
    maximo = Vector((float("-inf"),) * 3)
    for obj in objetos_malha():
        for v in obj.data.vertices:
            co = obj.matrix_world @ v.co
            for i in range(3):
                minimo[i] = min(minimo[i], co[i])
                maximo[i] = max(maximo[i], co[i])
    if minimo.x == float("inf"):
        raise RuntimeError("nenhuma geometria para medir")
    return minimo, maximo


def transformar(escala: float, deslocamento: Vector) -> None:
    for obj in objetos_malha():
        for v in obj.data.vertices:
            v.co = (v.co * escala) + deslocamento
        obj.data.update()


def calcular_pivo(regra: str, minimo: Vector, maximo: Vector, declarado) -> tuple[Vector, str]:
    """Pivo pedido pela spec, ou a regra geometrica quando o provider nao declara."""
    centro = (minimo + maximo) / 2
    if declarado:
        return Vector(declarado), "provider"
    if regra == "base":
        return Vector((centro.x, centro.y, minimo.z)), "regra"
    if regra == "centro":
        return centro, "regra"
    if regra == "topo":
        return Vector((centro.x, centro.y, maximo.z)), "regra"
    if regra == "origem":
        return Vector((0.0, 0.0, 0.0)), "regra"
    if regra == "empunhadura":
        # heuristica declarada: 20% da altura a partir da base (docs/perfis-export.md §4)
        z = minimo.z + 0.2 * (maximo.z - minimo.z)
        return Vector((centro.x, centro.y, z)), "heuristica"
    return Vector((centro.x, centro.y, minimo.z)), "regra"


def malha_triangulada(obj) -> int:
    return sum(max(len(p.vertices) - 2, 0) for p in obj.data.polygons)


def medir_geometria(obj) -> dict:
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    # glTF divide vertice em cada costura de UV/normal: solda antes de julgar topologia,
    # senao toda aresta de um asset importado parece "borda aberta" (falso positivo).
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1e-5)
    nao_manifold = sum(1 for e in bm.edges if len(e.link_faces) != 2)
    degeneradas = sum(1 for f in bm.faces if f.calc_area() < 1e-12)
    bm.free()
    return {"nao_manifold": nao_manifold, "degeneradas": degeneradas}


# ------------------------------------------------------------------ LOD / colisor


def clonar_malha(obj, nome: str):
    novo = bpy.data.objects.new(nome, obj.data.copy())
    bpy.context.collection.objects.link(novo)
    return novo


def aplicar_decimate(obj, proporcao: float) -> None:
    if proporcao >= 1.0:
        return
    mod = obj.modifiers.new("decimate_lod", "DECIMATE")
    mod.ratio = max(0.01, min(1.0, proporcao))
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.modifier_apply(modifier=mod.name)


def criar_colisor(obj, modo: str, nome_base: str, max_partes: int) -> list:
    """Colisor convexo por peca; prefixo UCX_ (convencao do perfil)."""
    if modo in ("none", None):
        return []
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    resultados = []

    if modo == "box":
        minimo, maximo = bbox_local()
        malha = bpy.data.meshes.new(f"{nome_base}_box")
        v = [
            (minimo.x, minimo.y, minimo.z),
            (maximo.x, minimo.y, minimo.z),
            (maximo.x, maximo.y, minimo.z),
            (minimo.x, maximo.y, minimo.z),
            (minimo.x, minimo.y, maximo.z),
            (maximo.x, minimo.y, maximo.z),
            (maximo.x, maximo.y, maximo.z),
            (minimo.x, maximo.y, maximo.z),
        ]
        malha.from_pydata(v, [], list(FACES_CUBO))
        malha.update()
        col = bpy.data.objects.new(f"UCX_{nome_base}_00", malha)
        bpy.context.collection.objects.link(col)
        resultados.append(col)
    else:
        # convex hull (convex) ou um hull por ilha (ucx), limitado por max_partes
        ilhas = _ilhas(bm)
        if modo == "convex" or len(ilhas) > max_partes:
            ilhas = [bm]
        for indice, ilha in enumerate(ilhas[:max_partes]):
            temp = bmesh.new()
            temp.from_mesh(obj.data) if ilha is bm else None
            if ilha is not bm:
                vmap = {}
                for vertice in ilha.verts:
                    vmap[vertice] = temp.verts.new(vertice.co)
                temp.verts.ensure_lookup_table()
            hull = bmesh.ops.convex_hull(temp, input=list(temp.verts))
            manter = set(hull["geom_interior"]) | set(hull["geom_unused"])
            bmesh.ops.delete(temp, geom=list(manter), context="VERTS")
            malha = bpy.data.meshes.new(f"UCX_{nome_base}_{indice:02d}")
            temp.to_mesh(malha)
            temp.free()
            malha.update()
            col = bpy.data.objects.new(f"UCX_{nome_base}_{indice:02d}", malha)
            bpy.context.collection.objects.link(col)
            resultados.append(col)

    bm.free()
    return resultados


def _ilhas(bm) -> list:
    vistos = set()
    ilhas = []
    for vertice in bm.verts:
        if vertice.index in vistos:
            continue
        pilha = [vertice]
        membros = []
        vistos.add(vertice.index)
        while pilha:
            atual = pilha.pop()
            membros.append(atual)
            for aresta in atual.link_edges:
                outro = aresta.other_vert(atual)
                if outro.index not in vistos:
                    vistos.add(outro.index)
                    pilha.append(outro)
        ilha = bmesh.new()
        mapa = {}
        for v in membros:
            mapa[v.index] = ilha.verts.new(v.co)
        ilha.verts.ensure_lookup_table()
        for v in membros:
            for f in v.link_faces:
                try:
                    ilha.faces.new([mapa[x.index] for x in f.verts])
                except ValueError:
                    pass
        ilhas.append(ilha)
    return ilhas


# ------------------------------------------------------------------ export


def exportar(caminho: str, objetos: list, com_rig: bool) -> None:
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objetos:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objetos[0]

    kwargs = {
        "filepath": caminho,
        "export_format": "GLB",
        "use_selection": True,
        "export_apply": False,
        "export_yup": True,
        "export_materials": "EXPORT",
        "export_skins": com_rig,
        "export_animations": False,
        "export_texcoords": True,
        "export_normals": True,
        "export_draco_mesh_compression_enable": False,
        "export_image_format": "AUTO",
        "export_cameras": False,
        "export_lights": False,
    }
    props = set(bpy.ops.export_scene.gltf.get_rna_type().properties.keys())
    kwargs = {k: v for k, v in kwargs.items() if k in props}
    bpy.ops.export_scene.gltf(**kwargs)
    for obj in objetos:
        obj.select_set(False)


# ------------------------------------------------------------------ pipeline


def processar(job: dict) -> dict:
    saida_dir = job["saida_dir"]
    os.makedirs(saida_dir, exist_ok=True)
    bruto_dir = job["bruto_dir"]
    bruto = jload(os.path.join(bruto_dir, job["bruto_arquivo"]))
    perfil = job["perfil"]
    item = job["item"]

    limpar_cena()

    rig_obj = None
    info_gerada: dict = {}
    textura_gerada: dict | None = None
    if bruto["schema"] == "forge3d/bruto-blocky@1":
        obj, grupos = construir_blocky(bruto, bruto_dir)
        if bruto.get("ossos"):
            rig_obj = criar_armadura(bruto["ossos"])
    elif bruto["schema"] == "forge3d/bruto-arquivo@1":
        importar_fonte(os.path.join(bruto_dir, bruto["arquivo"]))
        obj = unir_malhas()
        grupos = {}
        if bruto.get("canonicalizar"):
            info_gerada["canonicalizacao"] = canonicalizar(obj, item.get("tipo"))
        info_gerada["reparo_inicial"] = reparar_malha(obj)
        if obj.data.color_attributes:
            # malha gerada: corta o orcamento ANTES do UV/bake; o bake roda em 512 px
            info_gerada["triangulos_antes_decimate"] = malha_triangulada(obj)
            info_gerada["triangulos_pos_decimate"] = decimar(
                obj, int(item["limite_triangulos"])
            )
            info_gerada["reparo_pos_decimate"] = reparar_malha(obj)
            info_gerada["uv"] = desdobrar_uv(obj)
            px = int(bruto.get("textura_px") or TEX_PX_GERADA)
            nome_png = f"{job['nome_base']}_baseColor.png"
            info_gerada["bake"] = assar_cor_vertices(
                obj, os.path.join(saida_dir, nome_png), max(64, min(px, 1024))
            )
            textura_gerada = {"caminho": nome_png, "papel": "textura"}
        elif not obj.data.uv_layers:
            raise RuntimeError(
                "malha importada sem UV e sem cor por vertice: nao ha como assar textura"
            )
    else:
        raise RuntimeError(f"bruto desconhecido: {bruto['schema']}")

    # --- normalizacao de escala e pivo ---
    minimo, maximo = bbox_local()
    altura_atual = maximo.z - minimo.z
    if altura_atual <= 0:
        raise RuntimeError("geometria com altura zero")
    alvo = float(item["altura_metros"])
    escala = alvo / altura_atual

    pivo_declarado = (bruto.get("pivos") or {}).get(item["pivot"])
    pivo, origem_regra = calcular_pivo(item["pivot"], minimo * escala, maximo * escala, pivo_declarado)
    if pivo_declarado:
        pivo = Vector(pivo_declarado) * escala

    transformar(escala, -pivo)
    if rig_obj is not None:
        transformar_armadura(rig_obj, escala, -pivo)

    if rig_obj is not None and grupos:
        obj.parent = rig_obj
        mod = obj.modifiers.new("armature", "ARMATURE")
        mod.object = rig_obj

    # --- medicao do LOD0 ---
    minimo, maximo = bbox_local()
    medidas_base = {
        "triangulos": malha_triangulada(obj),
        "vertices": len(obj.data.vertices),
        # eixos glTF: [largura x, altura y, profundidade z]
        "bbox_m": [maximo.x - minimo.x, maximo.z - minimo.z, maximo.y - minimo.y],
        "materiais": len(obj.data.materials),
        "ossos": len(rig_obj.data.bones) if rig_obj is not None else 0,
        "pivo_regra": origem_regra,
        "aabb_min": [minimo.x, minimo.z, -maximo.y],
        "aabb_max": [maximo.x, maximo.z, -minimo.y],
    }
    medidas_base.update(medir_geometria(obj))

    arquivos: list[dict] = []

    # --- LODs ---
    lods = item.get("lod") or [100]
    for nivel, pct in enumerate(lods):
        if nivel == 0:
            alvo_obj = obj
        else:
            alvo_obj = clonar_malha(obj, f"forge3d_lod{nivel}")
            aplicar_decimate(alvo_obj, pct / 100.0)
        nome = job["nome_arquivo"] if nivel == 0 else f"{job['nome_base']}_LOD{nivel}.glb"
        caminho = os.path.join(saida_dir, nome)
        selecionados = [alvo_obj] + ([rig_obj] if rig_obj is not None else [])
        exportar(caminho, selecionados, rig_obj is not None)
        arquivos.append(
            {
                "caminho": nome,
                "papel": "mesh" if nivel == 0 else "lod",
                "nivel": nivel,
                "triangulos": malha_triangulada(alvo_obj),
            }
        )
        if nivel > 0:
            bpy.data.objects.remove(alvo_obj, do_unlink=True)

    # --- colisor ---
    colisores = criar_colisor(obj, item.get("colisao"), job["nome_base"], perfil["colisao"]["max_partes"])
    arquivo_colisor = None
    if colisores:
        arquivo_colisor = f"{job['nome_base']}_colisao.glb"
        exportar(os.path.join(saida_dir, arquivo_colisor), colisores, False)
        arquivos.append(
            {"caminho": arquivo_colisor, "papel": "colisor", "partes": len(colisores)}
        )

    # --- atlas (vai junto como arquivo irmao) ---
    if bruto.get("atlas"):
        import shutil

        destino_atlas = os.path.join(saida_dir, f"{job['nome_base']}_baseColor.png")
        shutil.copyfile(os.path.join(bruto_dir, bruto["atlas"]), destino_atlas)
        arquivos.append(
            {
                "caminho": f"{job['nome_base']}_baseColor.png",
                "papel": "textura",
                "bytes": os.path.getsize(destino_atlas),
            }
        )

    if textura_gerada:
        arquivos.append(
            {
                "caminho": textura_gerada["caminho"],
                "papel": textura_gerada["papel"],
                "bytes": os.path.getsize(os.path.join(saida_dir, textura_gerada["caminho"])),
            }
        )

    if info_gerada:
        medidas_base["gerada"] = info_gerada
    medidas_base["partes_colisao"] = len(colisores)
    medidas_base["esqueleto"] = item.get("esqueleto") if rig_obj is not None else None
    medidas_base["lod"] = [{"nivel": a["nivel"], "triangulos": a["triangulos"]} for a in arquivos if a["papel"] in ("mesh", "lod")]

    resultado = {"ok": True, "medidas": medidas_base, "arquivos": arquivos}
    if bruto.get("concept"):
        # proveniencia do estagio text-to-image; o manifest grava em providers.texture
        resultado["concept"] = bruto["concept"]
    return resultado


def main() -> int:
    argv = sys.argv
    if "--" not in argv:
        print("uso: blender -b -P postprocess.py -- <job.json>", file=sys.stderr)
        return 2
    job_path = argv[argv.index("--") + 1]
    job = jload(job_path)
    try:
        resultado = processar(job)
    except Exception as exc:  # noqa: BLE001 - o erro precisa sair como arquivo
        jsave(
            job["saida_resultado"],
            {
                "ok": False,
                "erro": str(exc),
                "traceback": traceback.format_exc(limit=8),
            },
        )
        print(f"FORGE3D_BPY_FALHOU: {exc}", file=sys.stderr)
        return 1
    jsave(job["saida_resultado"], resultado)
    print("FORGE3D_BPY_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
