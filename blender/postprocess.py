"""Script bpy do Forge3D — roda com ``blender --background --python``.

Canal unico: arquivo JSON de entrada e arquivo JSON de saida (I9). Nada de parse de stdout.

Etapas: construir geometria -> rig -> normalizar escala/pivo -> LOD -> colisor -> exportar GLB
-> medir. O script nao decide qualidade nem aprova nada: ele mede e exporta. Quem reprova e o QC.
"""

from __future__ import annotations

import json
import math
import os
import sys
import traceback

import bmesh
import bpy
from mathutils import Matrix, Vector

_BLENDER_DIR = os.path.dirname(os.path.abspath(__file__))
if _BLENDER_DIR not in sys.path:
    sys.path.insert(0, _BLENDER_DIR)

import autorig  # noqa: E402
import bake_pbr  # noqa: E402
import extrude_2d  # noqa: E402

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
    ignorar = set()
    col_ne = bpy.data.collections.get("glTF_not_exported")
    if col_ne is not None:
        ignorar.update(o.name for o in col_ne.objects)
    return [o for o in bpy.context.scene.objects if o.type == "MESH" and o.name not in ignorar]


# ------------------------------------------------------------------ construcao


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



# ------------------------------------------------------------------ malha gerada (P3-A)


TEX_PX_GERADA = 1024


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


def _fechar_ciclos_borda_fan(bm) -> int:
    """Fecha ciclos simples de borda nao-planares via leque ao centroide preservando pesos e UV."""
    restantes = [e for e in bm.edges if len(e.link_faces) == 1]
    if not restantes:
        return 0
    dvert_lay = bm.verts.layers.deform.active
    uv_lays = list(bm.loops.layers.uv.values())
    criadas = 0
    visitadas: set = set()
    for e0 in restantes:
        if e0 in visitadas or len(e0.link_faces) != 1:
            continue
        comp_e = []
        fila = [e0]
        visitadas.add(e0)
        adj: dict = {}
        while fila:
            ec = fila.pop()
            comp_e.append(ec)
            for v in ec.verts:
                adj.setdefault(v, []).append(ec)
                for en in v.link_edges:
                    if len(en.link_faces) == 1 and en not in visitadas:
                        visitadas.add(en)
                        fila.append(en)
        if len(comp_e) < 3 or any(len(es) != 2 for es in adj.values()):
            continue
        f_adj = comp_e[0].link_faces[0]
        va, vb = comp_e[0].verts[0], comp_e[0].verts[1]
        for lp in f_adj.loops:
            if lp.edge == comp_e[0]:
                va, vb = lp.link_loop_next.vert, lp.vert
                break
        ciclo = [va, vb]
        usadas = {comp_e[0]}
        while len(ciclo) < len(comp_e):
            atual = ciclo[-1]
            prox_e = next((e for e in adj[atual] if e not in usadas), None)
            if prox_e is None:
                break
            usadas.add(prox_e)
            ciclo.append(prox_e.other_vert(atual))
        if len(ciclo) != len(comp_e):
            continue
        centro = sum((v.co for v in ciclo), Vector((0.0, 0.0, 0.0))) / len(ciclo)
        vc = bm.verts.new(centro)
        if dvert_lay is not None:
            pesos: dict[int, float] = {}
            for v in ciclo:
                for grp, w in v[dvert_lay].items():
                    pesos[grp] = pesos.get(grp, 0.0) + w / len(ciclo)
            tot = sum(pesos.values())
            if tot > 1e-8:
                for grp, w in pesos.items():
                    vc[dvert_lay][grp] = w / tot
        uv_map: dict = {}
        for uvl in uv_lays:
            uv_map[uvl] = {
                v: next((lp[uvl].uv.copy() for lp in v.link_loops), Vector((0.5, 0.5)))
                for v in ciclo
            }
        mat_idx = f_adj.material_index
        for i in range(len(ciclo)):
            v1 = ciclo[i]
            v2 = ciclo[(i + 1) % len(ciclo)]
            try:
                nf = bm.faces.new((v1, v2, vc))
            except ValueError:
                continue
            nf.material_index = mat_idx
            criadas += 1
            for uvl in uv_lays:
                uv1 = uv_map[uvl][v1]
                uv2 = uv_map[uvl][v2]
                uvc = sum(uv_map[uvl].values(), Vector((0.0, 0.0))) / len(ciclo)
                for lp in nf.loops:
                    if lp.vert == v1:
                        lp[uvl].uv = uv1
                    elif lp.vert == v2:
                        lp[uvl].uv = uv2
                    else:
                        lp[uvl].uv = uvc
    return criadas


def reparar_malha(obj) -> dict:
    """Solda, remove ilha solta e fecha buraco antes do export."""
    antes = (len(obj.data.vertices), len(obj.data.polygons))
    obj.data.validate(verbose=False)
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1e-5)
    bmesh.ops.dissolve_degenerate(bm, dist=1e-6, edges=list(bm.edges))
    # sliver de area 1e-9 sobrevive ao dissolve_degenerate (que olha aresta) e vira aresta de 3
    # faces no G1; remover a face e seguro porque ela nao cobre area util
    slivers = [f for f in bm.faces if f.calc_area() < 1e-8]
    if slivers:
        bmesh.ops.delete(bm, geom=slivers, context="FACES")
    soltas_e = [e for e in bm.edges if not e.link_faces]
    if soltas_e:
        bmesh.ops.delete(bm, geom=soltas_e, context="EDGES")
    soltos = [v for v in bm.verts if not v.link_faces]
    if soltos:
        bmesh.ops.delete(bm, geom=soltos, context="VERTS")
    ilhas = _remover_ilhas_de_uma_face(bm)
    bordas = [e for e in bm.edges if len(e.link_faces) == 1]
    if bordas:
        bmesh.ops.holes_fill(bm, edges=bordas, sides=0)
        if any(len(e.link_faces) == 1 for e in bm.edges):
            _fechar_ciclos_borda_fan(bm)
        # holes_fill pode criar uma face solta; remove de novo
        _remover_ilhas_de_uma_face(bm)
    bmesh.ops.triangulate(bm, faces=list(bm.faces))
    vistos_faces: set[frozenset] = set()
    dups_ou_deg = []
    for f in bm.faces:
        chave = frozenset(f.verts)
        if len(chave) < 3 or f.calc_area() < 1e-10 or chave in vistos_faces:
            dups_ou_deg.append(f)
        else:
            vistos_faces.add(chave)
    if dups_ou_deg:
        bmesh.ops.delete(bm, geom=dups_ou_deg, context="FACES")
    for _ in range(2):
        excedentes_nm = set()
        for e in bm.edges:
            if len(e.link_faces) > 2:
                ordenadas = sorted(e.link_faces, key=lambda f: f.calc_area(), reverse=True)
                for f in ordenadas[2:]:
                    excedentes_nm.add(f)
        if not excedentes_nm:
            break
        bmesh.ops.delete(bm, geom=list(excedentes_nm), context="FACES")
        _remover_ilhas_de_uma_face(bm)
        bordas_pos = [e for e in bm.edges if len(e.link_faces) == 1]
        if bordas_pos:
            bmesh.ops.holes_fill(bm, edges=bordas_pos, sides=0)
            if any(len(e.link_faces) == 1 for e in bm.edges):
                _fechar_ciclos_borda_fan(bm)
            _remover_ilhas_de_uma_face(bm)
            bmesh.ops.triangulate(bm, faces=list(bm.faces))
    soltas_e_pos = [e for e in bm.edges if not e.link_faces]
    if soltas_e_pos:
        bmesh.ops.delete(bm, geom=soltas_e_pos, context="EDGES")
    soltos_pos = [v for v in bm.verts if not v.link_faces]
    if soltos_pos:
        bmesh.ops.delete(bm, geom=soltos_pos, context="VERTS")
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
        "slivers_removidos": len(slivers),
        "bordas_preenchidas": len(bordas),
    }


def _media_vizinhos(v):
    edges = v.link_edges
    if not edges:
        return v.co.copy()
    soma = Vector((0.0, 0.0, 0.0))
    for e in edges:
        soma += e.other_vert(v).co
    return soma / len(edges)


def _suavizar_taubin_bm(bm, iteracoes: int = 2, fator: float = 0.45) -> int:
    """Suavizacao Taubin sem encolher volume (reduz ondas de Marching Cubes no bmesh)."""
    if not bm.verts or iteracoes <= 0:
        return 0
    for _ in range(iteracoes):
        for peso in (fator, -1.04 * fator):
            deslocs = [(_media_vizinhos(v) - v.co) * peso for v in bm.verts]
            for v, d in zip(bm.verts, deslocs):
                v.co += d
    bm.normal_update()
    return len(bm.verts)


def _relaxar_arestas_dobradas_bm(bm, passadas: int = 3) -> int:
    """Desdobra arestas internas/invertidas apos decimate para zerar rasgos e normais."""
    total_movidos = 0
    for _ in range(passadas):
        bm.normal_update()
        marcados: set[int] = set()
        for e in bm.edges:
            if len(e.link_faces) == 2 and e.link_faces[0].normal.dot(e.link_faces[1].normal) < -0.15:
                marcados.add(e.verts[0].index)
                marcados.add(e.verts[1].index)
        if not marcados:
            break
        bm.verts.ensure_lookup_table()
        novos = {idx: _media_vizinhos(bm.verts[idx]) for idx in marcados}
        for idx, destino in novos.items():
            v = bm.verts[idx]
            v.co = v.co.lerp(destino, 0.55)
        total_movidos += len(marcados)
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    return total_movidos


def decimar(obj, alvo_tris: int, proteger_cabeca_maos: bool = False) -> int:
    tris = malha_triangulada(obj)
    if alvo_tris <= 0 or tris <= alvo_tris:
        return tris

    if proteger_cabeca_maos and obj.data.vertices and tris >= 4000:
        bm_pre = bmesh.new()
        bm_pre.from_mesh(obj.data)
        _suavizar_taubin_bm(bm_pre, iteracoes=1, fator=0.35)
        bm_pre.to_mesh(obj.data)
        bm_pre.free()
        obj.data.update()

    vg_name: str | None = None
    if proteger_cabeca_maos and obj.data.vertices:
        mw = obj.matrix_world
        coords = [mw @ v.co for v in obj.data.vertices]
        z_min = min(c.z for c in coords)
        z_max = max(c.z for c in coords)
        h = z_max - z_min
        if h > 0.0:
            cx = 0.5 * (min(c.x for c in coords) + max(c.x for c in coords))
            vg_name = "forge3d_decimate_peso"
            vg_temp = obj.vertex_groups.new(name=vg_name)
            cabeca_verts: list[int] = []
            maos_verts: list[int] = []
            resto_verts: list[int] = []
            z_cabeca = z_min + 0.76 * h
            z_mao_min = z_min + 0.30 * h
            z_mao_max = z_min + 0.70 * h
            x_mao = 0.25 * h
            for v, co in zip(obj.data.vertices, coords):
                if co.z >= z_cabeca:
                    cabeca_verts.append(v.index)
                elif z_mao_min <= co.z <= z_mao_max and abs(co.x - cx) >= x_mao:
                    maos_verts.append(v.index)
                else:
                    resto_verts.append(v.index)
            if cabeca_verts:
                vg_temp.add(cabeca_verts, 0.15, "REPLACE")
            if maos_verts:
                vg_temp.add(maos_verts, 0.40, "REPLACE")
            if resto_verts:
                vg_temp.add(resto_verts, 1.0, "REPLACE")

    try:
        mod = obj.modifiers.new("forge3d_decimate", "DECIMATE")
        mod.ratio = max(0.01, min(1.0, (alvo_tris * 0.995) / tris))
        if vg_name is not None:
            mod.vertex_group = vg_name
            mod.invert_vertex_group = False
            if hasattr(mod, "vertex_group_factor"):
                mod.vertex_group_factor = 0.80
        _selecionar(obj)
        if len(obj.modifiers) > 1:
            bpy.ops.object.modifier_move_to_index(modifier=mod.name, index=0)
        bpy.ops.object.modifier_apply(modifier=mod.name)
    finally:
        if vg_name is not None:
            vg_ref = obj.vertex_groups.get(vg_name)
            if vg_ref is not None:
                obj.vertex_groups.remove(vg_ref)

    tris_pos = malha_triangulada(obj)
    if vg_name is not None and tris_pos > alvo_tris:
        mod_fb = obj.modifiers.new("forge3d_decimate_fallback", "DECIMATE")
        mod_fb.ratio = max(0.01, min(1.0, (alvo_tris * 0.995) / tris_pos))
        _selecionar(obj)
        if len(obj.modifiers) > 1:
            bpy.ops.object.modifier_move_to_index(modifier=mod_fb.name, index=0)
        bpy.ops.object.modifier_apply(modifier=mod_fb.name)
        tris_pos = malha_triangulada(obj)

    if proteger_cabeca_maos and obj.data.vertices:
        bm_pos = bmesh.new()
        bm_pos.from_mesh(obj.data)
        _relaxar_arestas_dobradas_bm(bm_pos, passadas=3)
        bm_pos.to_mesh(obj.data)
        bm_pos.free()
        obj.data.update()
    return tris_pos


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

    GAP-048 (medido em 11/11/2026): com uma arma grande ao lado do corpo, a razao topo/base fica
    ~1 (0,988) e o centro de area tambem e neutro (6,18/12), entao o asset saia de cabeca para
    baixo com G1-G10 verdes. Terceiro sinal: a ponta CHATA (sola apoiada) tem area muito maior na
    fatia fina que a ponta arredondada (cabeca/capuz) — no caso real, 0,1218 no topo contra 0,0174
    na base (7x). Espelha quando o topo fino e o chato.
    """
    minimo, maximo = bbox_local()
    extensao = maximo - minimo
    ordem = sorted(range(3), key=lambda i: extensao[i])
    profundidade = ordem[0]
    sobra = [i for i in range(3) if i != profundidade]
    # Em T-pose, a envergadura horizontal (X) frequentemente >= altura (Z): se o eixo fino de
    # profundidade ja e Y (glTF +Y up importado no Blender) e Z nao esta achatado, preserva Z up.
    if (
        tipo in ("personagem_humanoide", "criatura")
        and profundidade == 1
        and extensao[2] >= 0.55 * extensao[0]
    ):
        altura, largura = 2, 0
    else:
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
        razao_ends = (areas[-1] / areas[0]) if areas and areas[0] > 0 else 0.0
        info["razao_topo_base"] = round(razao_ends, 3)
        # GAP-048: a ponta que apoia no chao e chata (sola); a outra e arredondada (cabeca/capuz).
        # A fatia fina denuncia o lado errado mesmo com prop grande, onde area e centro sao neutros.
        fatia = max(altura_z * 0.02, 1e-6)
        area_base_fina = _extensao_faixa(obj, minimo.z, minimo.z + fatia)
        area_topo_fina = _extensao_faixa(obj, maximo.z - fatia, maximo.z)
        invertido_contato = area_base_fina > 0 and area_topo_fina > 3.0 * area_base_fina
        upright_contato = area_topo_fina > 0 and area_base_fina > 3.0 * area_topo_fina
        info["contato_base"] = round(area_base_fina, 6)
        info["contato_topo"] = round(area_topo_fina, 6)
        info["invertido_contato"] = invertido_contato
        # cabeca fina em cima => topo menor que a base; capa/saia longa pode puxar centro < 0,48*n
        # mesmo com base firme e topo 10x menor (razao_ends << 0,5) -> nao inverter falso-positivo
        deve_inverter = invertido_contato or (
            not upright_contato
            and (razao_ends > 1.5 or (centro < n * 0.48 and razao_ends >= 0.5))
        )
        if total > 0 and deve_inverter:
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

def suavizar_por_angulo(obj, angulo_graus: float = 45.0) -> dict:
    """Smooth shading por angulo (Blender 4.2): solda normais suaves e mantem arestas vivas."""
    obj.data.shade_smooth()
    obj.data.set_sharp_from_angle(angle=math.radians(angulo_graus))
    obj.data.update()
    sharp = obj.data.attributes.get("sharp_edge")
    arestas_vivas = sum(1 for d in sharp.data if d.value) if sharp is not None else 0
    return {"angulo_graus": angulo_graus, "arestas_vivas": arestas_vivas}


def aplicar_weighted_normal(obj) -> dict:
    """Aplica normais ponderadas por area/angulo em pecas hard-surface."""
    _selecionar(obj)
    mod = obj.modifiers.new(name="WeightedNormal", type="WEIGHTED_NORMAL")
    mod.mode = "FACE_AREA_WITH_ANGLE"
    mod.keep_sharp = True
    bpy.ops.object.modifier_apply(modifier=mod.name)
    obj.data.update()
    return {"weighted_normal": True}


def retopologizar_quadriflow(obj, alvo_tris: int) -> bool:
    """Retopologia Quadriflow opcional; devolve False se a malha nao suportar remesh."""
    _selecionar(obj)
    alvos_quads = max(200, int(alvo_tris) // 2)
    try:
        bpy.ops.object.quadriflow_remesh(
            use_mesh_symmetry=False,
            use_preserve_sharp=True,
            use_preserve_boundary=True,
            target_faces=alvos_quads,
        )
        return True
    except Exception:
        return False


def desdobrar_uv(obj, margem: float = 0.02) -> str:
    _selecionar(obj)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(
        angle_limit=1.15192,  # 66 graus
        island_margin=max(0.02, float(margem)),
        area_weight=0.5,
        correct_aspect=True,
        scale_to_bounds=False,
    )
    bpy.ops.object.mode_set(mode="OBJECT")
    if not obj.data.uv_layers:
        raise RuntimeError("smart_project nao criou camada UV")
    return obj.data.uv_layers.active.name


def gerar_uv_lightmap(obj) -> str:
    """Gera UVMap_Lightmap (TEXCOORD_1) sem substituir o UV principal (TEXCOORD_0)."""
    if not obj.data.uv_layers:
        desdobrar_uv(obj)
    nome_primario = obj.data.uv_layers[0].name
    lm = obj.data.uv_layers.get("UVMap_Lightmap") or obj.data.uv_layers.new(name="UVMap_Lightmap")
    obj.data.uv_layers.active = lm
    _selecionar(obj)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(
        angle_limit=1.15192,
        island_margin=0.03,
        area_weight=0.5,
        correct_aspect=True,
        scale_to_bounds=True,
    )
    bpy.ops.object.mode_set(mode="OBJECT")
    obj.data.uv_layers.active = obj.data.uv_layers[nome_primario]
    obj.data.uv_layers[nome_primario].active_render = True
    return lm.name


def assar_cor_vertices(obj, png: str, px: int) -> dict:
    """Bake DIFFUSE/COLOR da cor por vertice para PNG e troca o material por textura."""
    if not obj.data.color_attributes:
        raise RuntimeError("malha sem atributo de cor por vertice para assar")
    nome_cor = obj.data.color_attributes[0].name
    obj.data.materials.clear()
    mat = bpy.data.materials.new("forge3d_bake")
    mat.use_nodes = True
    mat.use_backface_culling = True
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
    _aplicar_transformes(rig)
    bpy.context.view_layer.objects.active = rig
    rig.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    for osso in rig.data.edit_bones:
        osso.head = (osso.head * escala) + deslocamento
        osso.tail = (osso.tail * escala) + deslocamento
    bpy.ops.object.mode_set(mode="OBJECT")
    rig.select_set(False)


def _imagens_exportaveis() -> list:
    """Lista todas as imagens exportaveis carregadas na cena (exclui render targets)."""
    imgs = []
    for img in bpy.data.images:
        if getattr(img, "type", "IMAGE") == "RENDER_TARGET":
            continue
        if img.name in ("Render Result", "Viewer Node"):
            continue
        w, h = int(img.size[0]), int(img.size[1])
        if w <= 0 or h <= 0:
            continue
        imgs.append(img)
    return imgs


def _redimensionar_imagem(img, nw: int, nh: int) -> None:
    """Redimensiona imagem para (nw, nh) substituindo buffer empacotado via user_remap."""
    nome_orig = img.name
    cs = img.colorspace_settings.name if hasattr(img, "colorspace_settings") else "sRGB"
    img.scale(nw, nh)
    px = list(img.pixels)
    dst = bpy.data.images.new(name=f"{nome_orig}_r", width=nw, height=nh, alpha=True)
    try:
        dst.colorspace_settings.name = cs
    except Exception:
        pass
    dst.pixels.foreach_set(px)
    dst.pack()
    img.user_remap(dst)
    bpy.data.images.remove(img)
    dst.name = nome_orig


def _pot_abaixo(valor: int) -> int:
    """Maior potencia de 2 menor ou igual a valor (minimo 4px) para G4."""
    v = max(4, int(valor))
    if (v & (v - 1)) == 0:
        return v
    return 1 << (v.bit_length() - 1)


def _enquadrar_texturas_no_teto(textura_max: int) -> None:
    """Redimensiona qualquer imagem em cena maior que textura_max preservando POT (G4)."""
    if textura_max <= 0:
        return
    for img in _imagens_exportaveis():
        w, h = int(img.size[0]), int(img.size[1])
        maior = max(w, h)
        if maior > textura_max:
            fator = float(textura_max) / float(maior)
            nw = _pot_abaixo(max(4, int(round(w * fator))))
            nh = _pot_abaixo(max(4, int(round(h * fator))))
            _redimensionar_imagem(img, nw, nh)


def _reduzir_imagens_embutidas_orcamento(
    caminho_glb: str,
    bytes_max: int,
    exportar_fn,
) -> None:
    """Encolhe texturas embutidas (incluindo .mhclo) preservando POT quando GLB excede bytes_max (G9)."""
    if bytes_max <= 0 or not os.path.isfile(caminho_glb):
        return
    if os.path.getsize(caminho_glb) <= bytes_max:
        return
    for teto in (512, 256, 128):
        mudou = False
        for img in _imagens_exportaveis():
            w, h = int(img.size[0]), int(img.size[1])
            maior = max(w, h)
            if maior > teto:
                fator = float(teto) / float(maior)
                nw = _pot_abaixo(max(4, int(round(w * fator))))
                nh = _pot_abaixo(max(4, int(round(h * fator))))
                _redimensionar_imagem(img, nw, nh)
                mudou = True
        if mudou:
            exportar_fn()
            if os.path.getsize(caminho_glb) <= bytes_max:
                return


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
        # regra do contrato (D58): 20% da altura a partir da base, igual ao blocky
        # (FRACAO_EMPUNHADURA em src/forge3d/profiles.py). Este script roda no Python do
        # Blender e nao importa o pacote: a fracao fica literal de proposito.
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
    for vg in obj.vertex_groups:
        novo.vertex_groups.new(name=vg.name)
    return novo


def aplicar_decimate(obj, proporcao: float) -> None:
    if proporcao >= 1.0:
        return
    mod = obj.modifiers.new("decimate_lod", "DECIMATE")
    mod.ratio = max(0.01, min(1.0, proporcao))
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.modifier_apply(modifier=mod.name)


def _componentes_indices(bm) -> list[list[int]]:
    """Componentes conexas por aresta, como indices de vertice."""
    vistos: set[int] = set()
    grupos: list[list[int]] = []
    for vertice in bm.verts:
        if vertice.index in vistos:
            continue
        pilha = [vertice]
        membros: list[int] = []
        vistos.add(vertice.index)
        while pilha:
            atual = pilha.pop()
            membros.append(atual.index)
            for aresta in atual.link_edges:
                outro = aresta.other_vert(atual)
                if outro.index not in vistos:
                    vistos.add(outro.index)
                    pilha.append(outro)
        grupos.append(membros)
    return grupos


def _volume_componente(bm, indices: list[int]) -> float:
    xs = [bm.verts[i].co.x for i in indices]
    ys = [bm.verts[i].co.y for i in indices]
    zs = [bm.verts[i].co.z for i in indices]
    return (max(xs) - min(xs)) * (max(ys) - min(ys)) * (max(zs) - min(zs))


def aplicar_lod(obj, pct: float) -> dict:
    """LOD: blocky (muitas caixas) perde caixa inteira; malha de uma peca vai de decimate.

    Medido em 11/11/2026 (GAP-013): o decimate cego num blocky de 300 tris virou espinhos
    (IoU de silhueta 0,76 no LOD1 e 0,55 no LOD2). Caixa e a unidade de detalhe do blocky —
    tirar a caixa inteira preserva o que sobrou e nao inventa geometria.
    """
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.verts.ensure_lookup_table()
    grupos = _componentes_indices(bm)
    total_tris = len(bm.faces)
    if len(grupos) < 8:
        bm.free()
        aplicar_decimate(obj, pct / 100.0)
        return {"modo": "decimate", "ilhas": len(grupos)}

    por_vertice = {}
    medidas = []
    for indice, membros in enumerate(grupos):
        for v in membros:
            por_vertice[v] = indice
        coords = [bm.verts[i].co for i in membros]
        minimo = [min(c[k] for c in coords) for k in range(3)]
        maximo = [max(c[k] for c in coords) for k in range(3)]
        medidas.append(
            {
                "indice": indice,
                "volume": _volume_componente(bm, membros),
                # area da maior face do bbox: e o que o jogador ve. Braco fino tem volume
                # pequeno e area grande; visor tem o contrario. Volume como criterio sumia
                # com o braco (medido no render do android).
                "area": max(
                    (maximo[0] - minimo[0]) * (maximo[1] - minimo[1]),
                    (maximo[2] - minimo[2]) * (maximo[1] - minimo[1]),
                    (maximo[0] - minimo[0]) * (maximo[2] - minimo[2]),
                ),
                "tris": 0,
                "min": minimo,
                "max": maximo,
            }
        )
    for face in bm.faces:
        dono = por_vertice.get(face.verts[0].index)
        if dono is not None:
            medidas[dono]["tris"] += 1

    # envelope do asset: caixa que toca um extremo e obrigatoria. O LOD tira detalhe, nunca
    # encolhe o bbox (medido: sem esta regra o LOD2 reprovava com -34% em X).
    global_min = [min(m["min"][k] for m in medidas) for k in range(3)]
    global_max = [max(m["max"][k] for m in medidas) for k in range(3)]

    def toca_extremo(m: dict) -> bool:
        for k in range(3):
            if abs(m["min"][k] - global_min[k]) < 1e-6 or abs(m["max"][k] - global_max[k]) < 1e-6:
                return True
        return False

    obrigatorias = [m for m in medidas if toca_extremo(m)]
    opcionais = sorted(
        (m for m in medidas if not toca_extremo(m)), key=lambda m: m["area"], reverse=True
    )
    alvo = max(1, int(round(total_tris * pct / 100.0)))
    mantidas = list(obrigatorias)
    acumulado = sum(m["tris"] for m in mantidas)
    for medida in opcionais:
        if acumulado >= alvo:
            break
        mantidas.append(medida)
        acumulado += medida["tris"]
    remover_indices = {m["indice"] for m in medidas} - {m["indice"] for m in mantidas}
    remover = [bm.verts[i] for g in remover_indices for i in grupos[g]] if remover_indices else []
    if remover_indices:
        bmesh.ops.delete(bm, geom=remover, context="VERTS")
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
    return {
        "modo": "ilhas",
        "ilhas": len(grupos),
        "mantidas": len(mantidas),
        "obrigatorias": len(obrigatorias),
        "alvo_pct": pct,
        "triangulos": len(obj.data.polygons),
    }


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
                for vertice in ilha.verts:
                    temp.verts.new(vertice.co)
                temp.verts.ensure_lookup_table()
            # O `geom` do convex_hull carrega tambem faces de ENTRADA que ficam dentro do hull:
            # medido em 11/11/2026, o colisor da malha gerada saiu com face interior e o G7
            # reprovou (convexidade por componente). Alimentar o hull com uma NUVEM DE PONTOS
            # (sem faces para herdar) resolve na origem: o hull de um conjunto de pontos e o
            # mesmo, e o `geom` devolve so a superficie convexa.
            nuvem = bmesh.new()
            for vertice in temp.verts:
                nuvem.verts.new(vertice.co)
            nuvem.verts.ensure_lookup_table()
            if nuvem.verts:
                xs_n = [vv.co.x for vv in nuvem.verts]
                ys_n = [vv.co.y for vv in nuvem.verts]
                zs_n = [vv.co.z for vv in nuvem.verts]
                diag_n = math.sqrt(
                    (max(xs_n) - min(xs_n)) ** 2
                    + (max(ys_n) - min(ys_n)) ** 2
                    + (max(zs_n) - min(zs_n)) ** 2
                )
                dist_solda = (
                    max(0.015, min(0.06, diag_n * 0.025))
                    if len(nuvem.verts) > 64
                    else max(0.002, min(0.008, diag_n * 0.0025))
                )
                if len(nuvem.verts) > 16:
                    bmesh.ops.remove_doubles(nuvem, verts=list(nuvem.verts), dist=dist_solda)
                    nuvem.verts.ensure_lookup_table()
            hull = bmesh.ops.convex_hull(nuvem, input=list(nuvem.verts))
            faces_hull = [g for g in hull["geom"] if isinstance(g, bmesh.types.BMFace)]
            limpo = bmesh.new()
            mapa_vert = {}
            for face in faces_hull:
                for vertice in face.verts:
                    if vertice not in mapa_vert:
                        mapa_vert[vertice] = limpo.verts.new(vertice.co)
            limpo.verts.ensure_lookup_table()
            for face in faces_hull:
                try:
                    limpo.faces.new([mapa_vert[v] for v in face.verts])
                except ValueError:
                    continue
            if limpo.faces:
                bmesh.ops.dissolve_degenerate(limpo, dist=1e-3, edges=list(limpo.edges))
                bmesh.ops.triangulate(limpo, faces=list(limpo.faces))
                bmesh.ops.dissolve_degenerate(limpo, dist=1e-3, edges=list(limpo.edges))
            limpo.normal_update()
            if limpo.faces:
                bmesh.ops.recalc_face_normals(limpo, faces=list(limpo.faces))
            malha = bpy.data.meshes.new(f"UCX_{nome_base}_{indice:02d}")
            limpo.to_mesh(malha)
            limpo.free()
            nuvem.free()
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


# ------------------------------------------------------------------ animacao base (D66/D69)


def animar(rig_obj, clipes: list[dict]) -> list[dict]:
    """Aplica as chaves dos clipes que vieram no job. O movimento nao e decidido aqui."""
    return autorig.aplicar_animacoes_multi(rig_obj, clipes)


# ------------------------------------------------------------------ export


def _tem_normal_map(objetos: list) -> bool:
    for obj in objetos:
        if getattr(obj, "type", None) != "MESH" or not obj.data:
            continue
        for mat in obj.data.materials:
            if mat and mat.use_nodes:
                for node in mat.node_tree.nodes:
                    if node.type == "BSDF_PRINCIPLED":
                        inp = node.inputs.get("Normal")
                        if inp is not None and inp.is_linked:
                            return True
    return False


def exportar(
    caminho: str,
    objetos: list,
    com_rig: bool,
    com_animacao: bool = False,
    export_tangents: bool = False,
) -> None:
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objetos:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objetos[0]

    kwargs: dict = {
        "filepath": caminho,
        "export_format": "GLB",
        "use_selection": True,
        "export_apply": False,
        "export_yup": True,
        "export_materials": "EXPORT",
        "export_skins": com_rig,
        "export_animations": com_animacao,
        "export_animation_mode": "ACTIONS",
        "export_rest_position_armature": True,
        "export_texcoords": True,
        "export_normals": True,
        "export_draco_mesh_compression_enable": False,
        "export_image_format": "AUTO",
        "export_cameras": False,
        "export_lights": False,
    }
    if export_tangents:
        kwargs["export_tangents"] = True
    props = set(bpy.ops.export_scene.gltf.get_rna_type().properties.keys())
    kwargs = {k: v for k, v in kwargs.items() if k in props}
    bpy.ops.export_scene.gltf(**kwargs)
    for obj in objetos:
        obj.select_set(False)


# ------------------------------------------------------------------ pipeline


def _resolver_opcional_bruto(bruto_dir: str, relativo: str | None) -> str | None:
    if not relativo:
        return None
    caminho = str(relativo)
    if not os.path.isabs(caminho):
        caminho = os.path.join(bruto_dir, caminho)
    return caminho if os.path.isfile(caminho) else None


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
    texturas_geradas: list[dict] = []
    nome_base = str(job["nome_base"])
    if bruto["schema"] == "forge3d/bruto-blocky@1":
        obj, grupos = construir_blocky(bruto, bruto_dir)
        if bruto.get("ossos"):
            rig_obj = criar_armadura(bruto["ossos"])
    elif bruto["schema"] == "forge3d/bruto-extrude@1":
        imagem_path = _resolver_opcional_bruto(
            bruto_dir, bruto.get("origem_textura")
        ) or os.path.join(bruto_dir, bruto["imagem"])
        modo = str(bruto.get("modo", "arma"))
        obj = extrude_2d.construir_malha_2d(
            imagem_path,
            modo=modo,
            nome=nome_base,
            saida_dir=saida_dir,
            pivot=str(item.get("pivot") or "empunhadura"),
        )
        base_tex_path = os.path.join(saida_dir, f"{nome_base}_baseColor.png")
        if os.path.isfile(base_tex_path):
            texturas_geradas.append(
                {
                    "caminho": f"{nome_base}_baseColor.png",
                    "papel": "textura",
                    "bytes": os.path.getsize(base_tex_path),
                }
            )
        grupos = {}
        info_gerada["extrude_2d"] = {
            "modo": modo,
            "triangulos_iniciais": malha_triangulada(obj),
        }
        info_gerada["reparo_inicial"] = reparar_malha(obj)
        limite_tris = int(item["limite_triangulos"])
        if malha_triangulada(obj) > limite_tris:
            decimar(obj, limite_tris)
            info_gerada["reparo_pos_decimate"] = reparar_malha(obj)
        info_gerada["smooth"] = suavizar_por_angulo(obj, angulo_graus=35.0)
        info_gerada["weighted_normal"] = aplicar_weighted_normal(obj)
        met_hint = _resolver_opcional_bruto(bruto_dir, bruto.get("metallic_hint"))
        rough_hint = _resolver_opcional_bruto(bruto_dir, bruto.get("roughness_hint"))
        if met_hint or rough_hint:
            px_ext = int(bruto.get("textura_px") or TEX_PX_GERADA)
            res_hints = bake_pbr.aplicar_hints_orm_em_material(
                obj,
                saida_dir,
                nome_base,
                px_ext,
                metallic_hint_png=met_hint,
                roughness_hint_png=rough_hint,
                perfil_nome=str(perfil.get("perfil") or item.get("perfil") or ""),
            )
            if res_hints:
                texturas_geradas.extend(res_hints["arquivos_textura"])
    elif bruto["schema"] == "forge3d/bruto-arquivo@1":
        importar_fonte(os.path.join(bruto_dir, bruto["arquivo"]))
        obj = unir_malhas()
        grupos = {}
        armatures = [o for o in bpy.data.objects if o.type == "ARMATURE"]
        if armatures:
            rig_obj = armatures[0]
            _aplicar_transformes(rig_obj)
            grupos = {vg.name: vg for vg in obj.vertex_groups}
        if bruto.get("canonicalizar"):
            info_gerada["canonicalizacao"] = canonicalizar(obj, item.get("tipo"))
        info_gerada["reparo_inicial"] = reparar_malha(obj)
        if obj.data.color_attributes:
            px = int(bruto.get("textura_px") or TEX_PX_GERADA)
            origem_tex = _resolver_opcional_bruto(bruto_dir, bruto.get("origem_textura"))
            met_hint = _resolver_opcional_bruto(bruto_dir, bruto.get("metallic_hint"))
            rough_hint = _resolver_opcional_bruto(bruto_dir, bruto.get("roughness_hint"))
            proteger = bool(bruto.get("proteger_decimate", False))
            angulo_smooth = 85.0 if proteger else 45.0
            res_bake = bake_pbr.executar_bake_high_low(
                obj,
                saida_dir,
                nome_base,
                px,
                int(item["limite_triangulos"]),
                reparar_malha,
                lambda o, t, p=proteger: decimar(o, t, proteger_cabeca_maos=p),
                lambda o, a=angulo_smooth: suavizar_por_angulo(o, angulo_graus=a),
                desdobrar_uv,
                origem_textura=origem_tex,
                metallic_hint_png=met_hint,
                roughness_hint_png=rough_hint,
                proteger_superficie=proteger,
                perfil_nome=str(perfil.get("perfil") or item.get("perfil") or ""),
            )
            bake_meta = res_bake["bake"]
            info_gerada["triangulos_antes_decimate"] = bake_meta["triangulos_high"]
            info_gerada["triangulos_pos_decimate"] = bake_meta["triangulos_low"]
            info_gerada["reparo_pos_decimate"] = bake_meta["reparo"]
            info_gerada["smooth"] = bake_meta["smooth"]
            info_gerada["uv"] = bake_meta["uv"]
            info_gerada["bake"] = bake_meta
            texturas_geradas.extend(res_bake["arquivos_textura"])
        elif not obj.data.uv_layers:
            raise RuntimeError(
                "malha importada sem UV e sem cor por vertice: nao ha como assar textura"
            )
        else:
            proteger = bool(bruto.get("proteger_decimate", False))
            tris_antes = malha_triangulada(obj)
            limite_tris = int(item["limite_triangulos"])
            info_gerada["triangulos_antes_decimate"] = tris_antes
            if bruto.get("retopologia") == "quadriflow" and tris_antes > limite_tris:
                if retopologizar_quadriflow(obj, limite_tris):
                    info_gerada["retopologia"] = "quadriflow"
                    desdobrar_uv(obj)
            if malha_triangulada(obj) > limite_tris:
                decimar(obj, limite_tris, proteger_cabeca_maos=proteger)
                info_gerada["reparo_pos_decimate"] = reparar_malha(obj)
                info_gerada["smooth"] = suavizar_por_angulo(
                    obj, angulo_graus=85.0 if proteger else 45.0
                )
            elif bruto.get("armadura_modular"):
                info_gerada["reparo_pos_decimate"] = reparar_malha(obj)
            elif bruto.get("suavizar"):
                info_gerada["smooth"] = suavizar_por_angulo(
                    obj, angulo_graus=85.0 if proteger else 45.0
                )
            if (
                rig_obj is None
                and item.get("tipo") in ("prop_equipavel", "modulo_cenario")
                and not bruto.get("armadura_modular")
            ):
                info_gerada["weighted_normal"] = aplicar_weighted_normal(obj)
            info_gerada["triangulos_pos_decimate"] = malha_triangulada(obj)
        if bool(item.get("auto_rig")) and item.get("tipo") in ("personagem_humanoide", "criatura"):
            esq = str(
                item.get("esqueleto")
                or (perfil.get("rig") or {}).get("esqueleto_padrao")
                or "godot-humanoid@1"
            )
            rig_obj, grupos = autorig.auto_rigar_humanoide(obj, esq, criar_armadura)
    else:
        raise RuntimeError(f"bruto desconhecido: {bruto['schema']}")

    if bruto["schema"] != "forge3d/bruto-blocky@1" and item.get("tipo") in (
        "modulo_cenario",
        "prop_estatico",
    ):
        gerar_uv_lightmap(obj)

    obj.name = nome_base
    if obj.data is not None:
        obj.data.name = nome_base

    # --- normalizacao de escala e pivo ---
    # D62: a geometria e construida em metros. No perfil roblox-r15 o arquivo exportado tem que
    # sair em studs porque o importador do Studio le 1 unidade glTF = 1 stud; o fator vem do
    # perfil (`unidades.escala_saida`) e vale 1.0 nos perfis que exportam em metros.
    escala_saida = float((perfil.get("unidades") or {}).get("escala_saida", 1.0))
    if escala_saida <= 0:
        raise RuntimeError(f"escala_saida invalida no perfil: {escala_saida}")
    minimo, maximo = bbox_local()
    altura_atual = maximo.z - minimo.z
    if altura_atual <= 0:
        raise RuntimeError("geometria com altura zero")
    escala_preservada = bool(bruto.get("escala_preservada"))
    if escala_preservada:
        escala = 1.0 * escala_saida
        pivo = Vector((0.0, 0.0, 0.0))
        origem_regra = "preservada"
    else:
        alvo = float(item["altura_metros"])
        escala = (alvo / altura_atual) * escala_saida

        pivo_declarado = (bruto.get("pivos") or {}).get(item["pivot"])
        pivo, origem_regra = calcular_pivo(
            item["pivot"], minimo * escala, maximo * escala, pivo_declarado
        )
        if pivo_declarado:
            pivo = Vector(pivo_declarado) * escala

    transformar(escala, -pivo)
    if rig_obj is not None:
        transformar_armadura(rig_obj, escala, -pivo)

    geom_pos_escala = medir_geometria(obj)
    if geom_pos_escala["nao_manifold"] > 0 or geom_pos_escala["degeneradas"] > 0:
        info_gerada["reparo_pos_escala"] = reparar_malha(obj)

    if rig_obj is not None and grupos:
        if obj.parent is not rig_obj:
            obj.parent = rig_obj
        if not any(m.type == "ARMATURE" for m in obj.modifiers):
            mod = obj.modifiers.new("armature", "ARMATURE")
            mod.object = rig_obj

    # --- animacao base (D66/D69) ---
    animacoes_geradas: list[dict] = []
    if rig_obj is not None and job.get("clipes"):
        animacoes_geradas = animar(rig_obj, job["clipes"])

    # --- medicao do LOD0 ---
    # A malha neste ponto esta na unidade do ARQUIVO (studs no roblox-r15). O relatorio guarda as
    # duas: `bbox_export` na unidade do arquivo e `bbox_m` em metros, porque o contrato manda
    # `geometry.bbox_m` em metros e a unidade do arquivo vai em `unidades_export` (D62).
    minimo, maximo = bbox_local()
    bbox_export = [maximo.x - minimo.x, maximo.z - minimo.z, maximo.y - minimo.y]
    medidas_base = {
        "triangulos": malha_triangulada(obj),
        "vertices": len(obj.data.vertices),
        # eixos glTF: [largura x, altura y, profundidade z]
        "bbox_export": bbox_export,
        "bbox_m": [v / escala_saida for v in bbox_export],
        "escala_saida": escala_saida,
        "materiais": len(obj.data.materials),
        "ossos": len(rig_obj.data.bones) if rig_obj is not None else 0,
        "animacoes": animacoes_geradas,
        "pivo_regra": origem_regra,
        "escala_preservada": escala_preservada,
        "aabb_min": [minimo.x / escala_saida, minimo.z / escala_saida, -maximo.y / escala_saida],
        "aabb_max": [maximo.x / escala_saida, maximo.z / escala_saida, -minimo.y / escala_saida],
    }
    medidas_base.update(medir_geometria(obj))

    qualidade_item = str(item.get("qualidade") or "").strip().lower()
    textura_max_perfil = int(
        (perfil.get("material") or {}).get("textura_max")
        or (perfil.get("validacao") or {}).get("textura_max")
        or 0
    )
    if qualidade_item == "hero" and textura_max_perfil > 0:
        textura_max_perfil = max(textura_max_perfil, 2048)
    if textura_max_perfil > 0:
        _enquadrar_texturas_no_teto(textura_max_perfil)

    arquivos: list[dict] = []

    # --- LODs ---
    lods = item.get("lod") or [100]
    for nivel, pct in enumerate(lods):
        if nivel == 0:
            alvo_obj = obj
        else:
            alvo_obj = clonar_malha(obj, f"{nome_base}_LOD{nivel}")
            if alvo_obj.data is not None:
                alvo_obj.data.name = f"{nome_base}_LOD{nivel}"
            if rig_obj is not None and grupos:
                alvo_obj.parent = rig_obj
                mod_lod = alvo_obj.modifiers.new("armature", "ARMATURE")
                mod_lod.object = rig_obj
            info_lod = aplicar_lod(alvo_obj, pct)
            reparar_malha(alvo_obj)
            medidas_base.setdefault("lod_modo", {})[str(nivel)] = info_lod
        nome = job["nome_arquivo"] if nivel == 0 else f"{job['nome_base']}_LOD{nivel}.glb"
        caminho = os.path.join(saida_dir, nome)
        selecionados = [alvo_obj] + ([rig_obj] if rig_obj is not None else [])
        usar_tangents = _tem_normal_map([alvo_obj])
        exportar(
            caminho,
            selecionados,
            rig_obj is not None,
            com_animacao=bool(animacoes_geradas),
            export_tangents=usar_tangents,
        )
        bytes_max_kb = int((perfil.get("validacao") or {}).get("bytes_max_kb") or 0)
        if qualidade_item == "hero" and bytes_max_kb > 0:
            bytes_max_kb = max(bytes_max_kb, 4096)
        if nivel == 0 and bytes_max_kb > 0:
            if texturas_geradas:
                bake_pbr.ajustar_resolucao_orcamento(
                    alvo_obj,
                    saida_dir,
                    texturas_geradas,
                    caminho,
                    bytes_max_kb * 1024,
                    lambda c=caminho, s=selecionados, t=usar_tangents: exportar(
                        c,
                        s,
                        rig_obj is not None,
                        com_animacao=bool(animacoes_geradas),
                        export_tangents=t,
                    ),
                )
            _reduzir_imagens_embutidas_orcamento(
                caminho,
                bytes_max_kb * 1024,
                lambda c=caminho, s=selecionados, t=usar_tangents: exportar(
                    c,
                    s,
                    rig_obj is not None,
                    com_animacao=bool(animacoes_geradas),
                    export_tangents=t,
                ),
            )
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

    for tex in texturas_geradas:
        arquivos.append(
            {
                "caminho": tex["caminho"],
                "papel": tex["papel"],
                "bytes": int(
                    tex.get("bytes")
                    or os.path.getsize(os.path.join(saida_dir, tex["caminho"]))
                ),
            }
        )

    if info_gerada:
        medidas_base["gerada"] = info_gerada
    medidas_base["partes_colisao"] = len(colisores)
    medidas_base["esqueleto"] = (
        (item.get("esqueleto") or (perfil.get("rig") or {}).get("esqueleto_padrao"))
        if rig_obj is not None
        else None
    )
    medidas_base["lod"] = [{"nivel": a["nivel"], "triangulos": a["triangulos"]} for a in arquivos if a["papel"] in ("mesh", "lod")]

    resultado = {
        "ok": True,
        "medidas": medidas_base,
        "arquivos": arquivos,
        # o fator aplicado volta no relatorio: e o que o manifesto declara em unidades_export
        "escala_saida": escala_saida,
    }
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
