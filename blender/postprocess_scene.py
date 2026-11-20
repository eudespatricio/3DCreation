"""Camada L0 de postprocess: cena, utilidades, blocky, armadura, import/medidas."""

from __future__ import annotations

import json
import os
import sys

import bmesh
import bpy
from mathutils import Vector

if __package__:
    from . import autorig
else:
    _BLENDER_DIR = os.path.dirname(os.path.abspath(__file__))
    if _BLENDER_DIR not in sys.path:
        sys.path.insert(0, _BLENDER_DIR)
    import autorig

TIPOS_ORGANICOS = (
    "personagem_humanoide",
    "criatura",
    "criatura_quadrupede",
    "criatura_alada",
    "montaria",
)
PARTES_RIGIDAS = (
    "elmo",
    "ombreiras",
    "peitoral",
    "luvas",
    "calcas",
    "calças",
    "botas",
    "escudo",
    "arma",
)

# Limiar compartilhado com src/forge3d/qc.py para decidir frente/costas humanoide sem ambiguidade.
LIMIAR_SCORE_FRENTE = 0.035

# faces de um cubo por indice de vertice; a orientacao e corrigida depois por recalc
FACES_CUBO = (
    (0, 3, 2, 1),
    (4, 5, 6, 7),
    (0, 1, 5, 4),
    (2, 3, 7, 6),
    (3, 0, 4, 7),
    (1, 2, 6, 5),
)

TEX_PX_GERADA = 1024


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
    ignorar = set()
    col_ne = bpy.data.collections.get("glTF_not_exported")
    if col_ne is not None:
        ignorar.update(o.name for o in col_ne.objects)
    return [
        o
        for o in bpy.context.scene.objects
        if o.type == "MESH" and o.name not in ignorar and not o.name.startswith("UCX_")
    ]


def objetos_colisao_ucx() -> list:
    ignorar = set()
    col_ne = bpy.data.collections.get("glTF_not_exported")
    if col_ne is not None:
        ignorar.update(o.name for o in col_ne.objects)
    return [
        o
        for o in bpy.context.scene.objects
        if o.type == "MESH" and o.name not in ignorar and o.name.startswith("UCX_")
    ]


def material_atlas(atlas: str) -> "bpy.types.Material":
    mat = bpy.data.materials.new("forge3d_atlas")
    mat.use_nodes = True
    mat.use_backface_culling = True
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
    if any(b.name in autorig._OSSOS_BRACO or b.name in autorig._OSSOS_PERNA for b in obj.data.bones):
        autorig._alinhar_roll_ossos(obj)
    return obj


def _limpar_objetos_gltf_internos() -> None:
    """Remove colecoes/objetos auxiliares do importador glTF (ex: Icosphere de custom_shape)."""
    for arm in bpy.data.objects:
        if arm.type == "ARMATURE" and arm.pose is not None:
            for pb in arm.pose.bones:
                pb.custom_shape = None
    for col in list(bpy.data.collections):
        if col.name.startswith("glTF_not_exported"):
            for obj in list(col.objects):
                bpy.data.objects.remove(obj, do_unlink=True)
            bpy.data.collections.remove(col)


def importar_fonte(arquivo: str) -> None:
    ext = os.path.splitext(arquivo)[1].lower()
    if ext == ".glb" or ext == ".gltf":
        bpy.ops.import_scene.gltf(filepath=arquivo)
        _limpar_objetos_gltf_internos()
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


def transformar_armadura(rig, escala: float, deslocamento: Vector) -> None:
    """Ossos acompanham a geometria: skinning rigido exige osso e vertice no mesmo espaco."""
    _aplicar_transformes(rig)
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


def transformar_colisores_ucx(escala: float, deslocamento: Vector) -> None:
    for obj in objetos_colisao_ucx():
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
        # regra do contrato (D58): 20% da altura a partir da base, igual ao blocky
        # (FRACAO_EMPUNHADURA em src/forge3d/profiles.py). Este script roda no Python do
        # Blender e nao importa o pacote: a fracao fica literal de proposito.
        z = minimo.z + 0.2 * (maximo.z - minimo.z)
        return Vector((centro.x, centro.y, z)), "heuristica"
    return Vector((centro.x, centro.y, minimo.z)), "regra"


def malha_triangulada(obj) -> int:
    return sum(max(len(p.vertices) - 2, 0) for p in obj.data.polygons)


def medir_geometria(obj, *, permitir_bordas_abertas: bool = False) -> dict:
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    # glTF divide vertice em cada costura de UV/normal: solda apenas duplicatas exatas (1e-7),
    # sem esconder fendas de 3e-6..9e-6 apos reducao de escala.
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1e-7)
    bordas_abertas = sum(1 for e in bm.edges if len(e.link_faces) == 1)
    arestas_t = sum(1 for e in bm.edges if len(e.link_faces) > 2)
    nao_manifold = arestas_t if permitir_bordas_abertas else (bordas_abertas + arestas_t)
    degeneradas = sum(1 for f in bm.faces if f.calc_area() < 1e-12)
    bm.free()
    return {
        "nao_manifold": nao_manifold,
        "bordas_abertas": bordas_abertas,
        "arestas_t": arestas_t,
        "degeneradas": degeneradas,
    }


def animar(rig_obj, clipes: list[dict]) -> list[dict]:
    """Aplica as chaves dos clipes que vieram no job. O movimento nao e decidido aqui."""
    return autorig.aplicar_animacoes_multi(rig_obj, clipes)


def _resolver_opcional_bruto(bruto_dir: str, relativo: str | None) -> str | None:
    if not relativo:
        return None
    caminho = str(relativo)
    if not os.path.isabs(caminho):
        caminho = os.path.join(bruto_dir, caminho)
    return caminho if os.path.isfile(caminho) else None


def _resolver_vistas_ortograficas(
    bruto_dir: str,
    bruto: dict,
    job: dict,
    item: dict,
) -> dict[str, str] | None:
    concept_raw = bruto.get("concept")
    concept_vistas = concept_raw.get("vistas") if isinstance(concept_raw, dict) else None
    candidatos = (
        bruto.get("vistas_ortograficas"),
        concept_vistas,
        job.get("vistas_ortograficas"),
        item.get("vistas_ortograficas"),
    )
    bruto_vistas = next((c for c in candidatos if isinstance(c, dict) and c), None)
    if not bruto_vistas:
        return None
    resolvidas: dict[str, str] = {}
    for chave, val in bruto_vistas.items():
        if not isinstance(val, str) or not val.strip():
            continue
        caminho = _resolver_opcional_bruto(bruto_dir, val.strip())
        if caminho:
            resolvidas[str(chave).strip()] = caminho
    return resolvidas or None


def _escrever_concept_sidecar(saida_dir: str, nome_base: str, concept: dict) -> dict | None:
    """Grava sidecar de proveniencia do concept (D-06) e devolve o item de arquivo."""
    campos = (
        "prompt_final",
        "negativo",
        "modelo",
        "seed",
        "revisao",
        "versao",
        "provider_conceito",
        "largura_real",
        "altura_real",
        "referencia_estilo",
        "referencia_estilo_sha256",
    )
    dado = {c: concept[c] for c in campos if c in concept}
    if not dado:
        return None
    nome = f"{nome_base}_concept.json"
    jsave(os.path.join(saida_dir, nome), dado)
    return {
        "caminho": nome,
        "papel": "concept",
        "bytes": os.path.getsize(os.path.join(saida_dir, nome)),
    }


def _detectar_esqueleto_pelos_ossos(rig_obj) -> str | None:
    """Infere o esqueleto REAL pelos nomes dos ossos (D-03); None quando nao reconhece."""
    if rig_obj is None:
        return None
    nomes = {b.name for b in rig_obj.data.bones}
    if "WingShoulder.L" in nomes:
        return "winged_mount@1"
    if "FrontUpperLeg.L" in nomes:
        return "quadruped@1"
    if any(b in nomes for b in ("Thumb1.L", "Eye.L", "Cape")):
        return "godot-humanoid-aa@1"
    if "UpperTorso" in nomes:
        return "r15@1"
    if "Neck" in nomes and "Hand.L" in nomes:
        return "godot-humanoid@1"
    return None
