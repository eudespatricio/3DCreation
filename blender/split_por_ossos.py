"""Divide uma malha rigada em partes por peso de osso / distancia ponto-segmento (F06).

Entrada (JSON em disco, I9): {"glb": str, "saida": str, "partes": [{"nome": str, "junta": str}]}
Saida: um .glb watertight por parte (pivo na cabeca do osso, Y-up) + partes_combinadas.glb + JSON.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Matrix, Vector


def _bl_para_yup(v: Vector) -> list[float]:
    return [float(v.x), float(v.z), float(-v.y)]


def _dist_ponto_segmento(p: Vector, a: Vector, b: Vector) -> float:
    ab = b - a
    denom = ab.length_squared
    if denom < 1e-12:
        return (p - a).length
    t = max(0.0, min(1.0, (p - a).dot(ab) / denom))
    return (p - (a + ab * t)).length


def _extrair_ciclos_borda(bm) -> list[list]:
    """Extrai ciclos simples de borda via walking de half-edge (decompoe vertices pinch)."""
    edge_set = {e for e in bm.edges if len(e.link_faces) == 1}
    if not edge_set:
        return []
    next_at_vert: dict = {}
    edge_dir: dict = {}
    for e in sorted(edge_set, key=lambda x: x.index):
        for lp in e.link_faces[0].loops:
            if lp.edge == e:
                v_from, v_to = lp.link_loop_next.vert, lp.vert
                next_at_vert.setdefault(v_from, []).append((e, v_to))
                edge_dir[e] = (v_from, v_to)
                break
    ciclos: list[list] = []
    while edge_set:
        e0 = min(edge_set, key=lambda x: x.index)
        edge_set.remove(e0)
        if e0 not in edge_dir:
            continue
        v_start, v_curr = edge_dir[e0]
        caminho = [v_start, v_curr]
        while v_curr != v_start:
            cands = [(en, vn) for (en, vn) in next_at_vert.get(v_curr, ()) if en in edge_set]
            if not cands:
                break
            en, vn = cands[0]
            edge_set.remove(en)
            caminho.append(vn)
            v_curr = vn
        if v_curr != v_start or len(caminho) < 4:
            continue
        pilha: list = []
        pos: dict = {}
        for v in caminho[:-1]:
            if v in pos:
                sub = pilha[pos[v] :]
                for sv in sub[1:]:
                    pos.pop(sv, None)
                pilha = pilha[: pos[v] + 1]
                if len(sub) >= 3:
                    ciclos.append(sub)
            else:
                pos[v] = len(pilha)
                pilha.append(v)
        if len(pilha) >= 3:
            ciclos.append(pilha)
    return ciclos


def _retrair_bordas(bm, bone_mid_local: Vector, retract_dist: float) -> None:
    """Retrai levemente vertices de borda para o interior da parte (evita colisao na costura)."""
    if retract_dist <= 0.0:
        return
    b_verts = {v for e in bm.edges if len(e.link_faces) == 1 for v in e.verts}
    novas: dict = {}
    for v in b_verts:
        viz_int = [e.other_vert(v) for e in v.link_edges if len(e.link_faces) == 2 and e.other_vert(v) not in b_verts]
        alvo = sum((nv.co for nv in viz_int), Vector((0.0, 0.0, 0.0))) / len(viz_int) if viz_int else bone_mid_local
        delta = alvo - v.co
        if delta.length > 1e-6:
            novas[v] = v.co + delta * (min(retract_dist, 0.15 * delta.length) / delta.length)
    for v, co in novas.items():
        v.co = co


def _fechar_ciclos_borda_fan(bm, orig_faces: set, bone_mid_local: Vector, inset_dist: float) -> int:
    """Fecha ciclos simples de borda via leque preservando material, UV e pesos."""
    ciclos = _extrair_ciclos_borda(bm)
    if not ciclos:
        return 0
    dvert_lay = bm.verts.layers.deform.active
    uv_lays = list(bm.loops.layers.uv.values())
    criadas = 0
    for ciclo in ciclos:
        centro = sum((v.co for v in ciclo), Vector((0.0, 0.0, 0.0))) / len(ciclo)
        r_loop = max((v.co - centro).length for v in ciclo)
        min_r = min((v.co - centro).length for v in ciclo)
        usar_vc = len(ciclo) > 3 and min_r >= 2e-5 and r_loop >= 3e-5
        uv_map = {
            uvl: {
                v: next((lp[uvl].uv.copy() for lp in v.link_loops if lp.face in orig_faces), next((lp[uvl].uv.copy() for lp in v.link_loops), Vector((0.5, 0.5))))
                for v in ciclo
            }
            for uvl in uv_lays
        }
        f_adj = next((e.link_faces[0] for e in ciclo[0].link_edges if len(e.link_faces) == 1), next(iter(ciclo[0].link_faces), None))
        mat_idx = f_adj.material_index if f_adj is not None else 0
        if usar_vc:
            in_dir = bone_mid_local - centro
            if in_dir.length > 1e-6 and inset_dist > 0.0:
                centro = centro + in_dir.normalized() * min(inset_dist, 0.1 * r_loop)
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
            uv_cent = {uvl: sum(uv_map[uvl].values(), Vector((0.0, 0.0))) / len(ciclo) for uvl in uv_lays}
            tris = [(v1, ciclo[(i + 1) % len(ciclo)], vc) for i, v1 in enumerate(ciclo)]
        else:
            uv_cent, tris = {}, [(ciclo[0], ciclo[i], ciclo[i + 1]) for i in range(1, len(ciclo) - 1)]
        for tri in tris:
            if len({tri[0], tri[1], tri[2]}) < 3:
                continue
            try:
                nf = bm.faces.new(tri)
            except ValueError:
                continue
            nf.material_index = mat_idx
            criadas += 1
            for uvl in uv_lays:
                uvm, uvc = uv_map[uvl], uv_cent.get(uvl)
                for lp in nf.loops:
                    lp[uvl].uv = uvm[lp.vert] if lp.vert in uvm else uvc
    return criadas


def _limpar_degenerados(bm, dist: float = 2e-5) -> None:
    bmesh.ops.dissolve_degenerate(bm, dist=dist, edges=list(bm.edges))
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=dist)
    vistas: set[frozenset] = set()
    dups = [f for f in bm.faces if len(frozenset(f.verts)) < 3 or frozenset(f.verts) in vistas or vistas.add(frozenset(f.verts)) is not None]
    if dups:
        bmesh.ops.delete(bm, geom=dups, context="FACES_ONLY")
    _limpar_orfaos(bm)


def _cascas_fechadas(bm) -> list[tuple[list, float]]:
    visitadas: set = set()
    out: list[tuple[list, float]] = []
    for f0 in bm.faces:
        if f0 in visitadas:
            continue
        comp, fila = [], [f0]
        visitadas.add(f0)
        while fila:
            fc = fila.pop()
            comp.append(fc)
            for e in fc.edges:
                for nf in e.link_faces:
                    if nf not in visitadas:
                        visitadas.add(nf)
                        fila.append(nf)
        cset = set(comp)
        if any(sum(1 for nf in e.link_faces if nf in cset) != 2 for f in comp for e in f.edges):
            continue
        verts_c = {v for f in comp for v in f.verts}
        c = sum((v.co for v in verts_c), Vector((0.0, 0.0, 0.0))) / max(1, len(verts_c))
        vol = sum((f.verts[0].co - c).dot((f.verts[i].co - c).cross(f.verts[i + 1].co - c)) / 6.0 for f in comp for i in range(1, len(f.verts) - 1))
        out.append((comp, vol))
    return out


def _fechar_e_triangular(bm, nome: str, bone_mid_local: Vector, retract_dist: float) -> None:
    uv_lays = list(bm.loops.layers.uv.values())
    _retrair_bordas(bm, bone_mid_local, retract_dist)
    _limpar_degenerados(bm, 2e-5)
    for _pass in range(2):
        orig_faces = set(bm.faces)
        if any(len(e.link_faces) == 1 for e in bm.edges):
            _fechar_ciclos_borda_fan(bm, orig_faces, bone_mid_local, retract_dist if _pass == 0 else 0.0)
        restantes = [e for e in bm.edges if len(e.link_faces) == 1]
        if restantes:
            bmesh.ops.holes_fill(bm, edges=restantes, sides=0)
            for nf in list(bm.faces):
                if nf in orig_faces:
                    continue
                adj = next((of for e in nf.edges for of in e.link_faces if of in orig_faces), None)
                if adj is not None:
                    nf.material_index = adj.material_index
                for uvl in uv_lays:
                    for lp in nf.loops:
                        uv_s = next((olp[uvl].uv.copy() for olp in lp.vert.link_loops if olp.face in orig_faces), None)
                        if uv_s is not None:
                            lp[uvl].uv = uv_s
        bmesh.ops.triangulate(bm, faces=list(bm.faces))
        _limpar_degenerados(bm, 1.8e-5)
        if not any(len(e.link_faces) == 1 for e in bm.edges):
            break
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    for comp, vol in _cascas_fechadas(bm):
        if vol < 0.0:
            bmesh.ops.reverse_faces(bm, faces=comp)
    abertas = sum(1 for e in bm.edges if len(e.link_faces) == 1)
    nao_man = sum(1 for e in bm.edges if len(e.link_faces) != 2)
    bm_chk = bm.copy()
    bmesh.ops.remove_doubles(bm_chk, verts=list(bm_chk.verts), dist=1e-5)
    weld_nm = sum(1 for e in bm_chk.edges if len(e.link_faces) != 2)
    invertidas = sum(1 for _c, vol in _cascas_fechadas(bm_chk) if vol < -1e-9)
    bm_chk.free()
    if abertas > 0 or nao_man > 0 or weld_nm > 0 or invertidas > 0:
        raise SystemExit(f"split: topologia invalida em {nome}: abertas={abertas} nao_manifold={nao_man} weld_nm={weld_nm} invertidas={invertidas}")


def _empacotar_imagens_externas(base_dir: Path | None = None) -> None:
    for img in bpy.data.images:
        if img.source != "FILE" or img.packed_file is not None:
            continue
        cands = [bpy.path.abspath(img.filepath)] + ([str(base_dir / img.filepath.lstrip("/"))] if base_dir and img.filepath else [])
        for cand in cands:
            if cand and Path(cand).is_file():
                img.filepath = cand
                img.pack()
                break


def _exportar_glb(caminho: Path, objetos: list) -> None:
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objetos:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objetos[0]
    props = set(bpy.ops.export_scene.gltf.get_rna_type().properties.keys())
    kwargs = {
        "filepath": str(caminho), "export_format": "GLB", "use_selection": True, "export_yup": True,
        "export_apply": True, "export_materials": "EXPORT", "export_texcoords": True, "export_normals": True,
        "export_tangents": True, "export_image_format": "AUTO", "export_draco_mesh_compression_enable": False,
    }
    bpy.ops.export_scene.gltf(**{k: v for k, v in kwargs.items() if k in props})


def _atribuir_faces(bm_base, malha, mundo_malha: Matrix, segmentos: list[tuple[str, Vector, Vector]]) -> list[int]:
    parte_idx_by_nome = {nome: idx for idx, (nome, _a, _b) in enumerate(segmentos)}
    vg_idx_to_parte = {vg.index: parte_idx_by_nome[vg.name] for vg in malha.vertex_groups if vg.name in parte_idx_by_nome}
    dvert_lay = bm_base.verts.layers.deform.active

    atrib: list[int] = []
    vert_pesos: list[dict[int, float]] = []
    for v in bm_base.verts:
        pesos_v: dict[int, float] = {}
        if dvert_lay is not None and vg_idx_to_parte:
            for vg_idx, w in v[dvert_lay].items():
                if vg_idx in vg_idx_to_parte and w > 1e-4:
                    p_idx = vg_idx_to_parte[vg_idx]
                    pesos_v[p_idx] = pesos_v.get(p_idx, 0.0) + float(w)
        vert_pesos.append(pesos_v)
        if pesos_v:
            melhor = max(pesos_v.items(), key=lambda kv: (kv[1], -kv[0]))[0]
        else:
            p = mundo_malha @ v.co
            melhor = min(range(len(segmentos)), key=lambda idx: (_dist_ponto_segmento(p, segmentos[idx][1], segmentos[idx][2]), idx))
        atrib.append(melhor)

    face_parte: list[int] = []
    for f in bm_base.faces:
        soma_w: dict[int, float] = {}
        for v in f.verts:
            for p_idx, w in vert_pesos[v.index].items():
                soma_w[p_idx] = soma_w.get(p_idx, 0.0) + w
        if soma_w:
            face_parte.append(max(soma_w.items(), key=lambda kv: (kv[1], -kv[0]))[0])
            continue
        votos: dict[int, int] = {}
        for v in f.verts:
            votos[atrib[v.index]] = votos.get(atrib[v.index], 0) + 1
        max_v = max(votos.values())
        cands = [k for k, cnt in votos.items() if cnt == max_v]
        centro = mundo_malha @ f.calc_center_median()
        face_parte.append(cands[0] if len(cands) == 1 else min(cands, key=lambda idx: (_dist_ponto_segmento(centro, segmentos[idx][1], segmentos[idx][2]), idx)))

    counts: dict[int, int] = {}
    for lbl in face_parte:
        counts[lbl] = counts.get(lbl, 0) + 1
    for _pass in range(2):
        for f in bm_base.faces:
            cur = face_parte[f.index]
            if counts.get(cur, 0) <= 4:
                continue
            freq: dict[int, int] = {}
            for nl in (face_parte[nf.index] for e in f.edges for nf in e.link_faces if nf != f):
                freq[nl] = freq.get(nl, 0) + 1
            if not freq:
                continue
            cand, cand_cnt = max(freq.items(), key=lambda kv: (kv[1], -kv[0]))
            if cand != cur and (freq.get(cur, 0) == 0 or (cand_cnt >= 2 and cand_cnt > freq.get(cur, 0))):
                face_parte[f.index] = cand
                counts[cur] -= 1
                counts[cand] = counts.get(cand, 0) + 1

    faces = list(bm_base.faces)
    famintos = {i for i in range(len(segmentos)) if counts.get(i, 0) == 0}
    for p_idx, (_nome, seg_a, seg_b) in enumerate(segmentos):
        if counts.get(p_idx, 0) > 0:
            continue
        min_keep = 4 if any(counts.get(face_parte[f.index], 0) > 4 for f in faces) else 1
        cands = [f for f in faces if counts.get(face_parte[f.index], 0) > min_keep]
        if not cands:
            continue

        def _score(f, _p=p_idx, _a=seg_a, _b=seg_b):
            cur_f = face_parte[f.index]
            c_w = mundo_malha @ f.calc_center_median()
            d_p = _dist_ponto_segmento(c_w, _a, _b)
            d_c = _dist_ponto_segmento(c_w, segmentos[cur_f][1], segmentos[cur_f][2])
            w_p = sum(vert_pesos[v.index].get(_p, 0.0) for v in f.verts)
            return (0 if d_p < d_c else 1, d_p - d_c - 0.05 * w_p, d_p, f.index)

        seed = min(cands, key=_score)
        counts[face_parte[seed.index]] -= 1
        face_parte[seed.index] = p_idx
        counts[p_idx] = counts.get(p_idx, 0) + 1
        famintos.discard(p_idx)
        fila, seen = [seed], {seed}
        while fila:
            f_cur = fila.pop(0)
            for e in f_cur.edges:
                for nf in e.link_faces:
                    cur_nf = face_parte[nf.index]
                    if nf in seen or cur_nf == p_idx or counts.get(cur_nf, 0) <= min_keep:
                        continue
                    c_w = mundo_malha @ nf.calc_center_median()
                    d_p = _dist_ponto_segmento(c_w, seg_a, seg_b)
                    d_c = _dist_ponto_segmento(c_w, segmentos[cur_nf][1], segmentos[cur_nf][2])
                    melhor_outro = any(_dist_ponto_segmento(c_w, segmentos[q][1], segmentos[q][2]) < d_p for q in famintos)
                    if (d_p < d_c and not melhor_outro) or counts.get(p_idx, 0) < 4:
                        seen.add(nf)
                        face_parte[nf.index] = p_idx
                        counts[cur_nf] -= 1
                        counts[p_idx] = counts.get(p_idx, 0) + 1
                        fila.append(nf)
    return face_parte


def _limpar_orfaos(bm) -> None:
    for tipo, ctx in ((bm.edges, "EDGES"), (bm.verts, "VERTS")):
        soltos = [g for g in tipo if not g.link_faces]
        if soltos:
            bmesh.ops.delete(bm, geom=soltos, context=ctx)


def _bmesh_aabb(bm) -> tuple[Vector, Vector]:
    cos = [v.co for v in bm.verts]
    return Vector((min(c.x for c in cos), min(c.y for c in cos), min(c.z for c in cos))), Vector((max(c.x for c in cos), max(c.y for c in cos), max(c.z for c in cos)))


def _bisectar_sobrepostos(bms: list, arm, segmentos: list[tuple[str, Vector, Vector]], retract_dist: float) -> None:
    """Separa pares pai-filho com caixas sobrepostas na malha de entrada no plano da junta."""
    idx_by_nome = {nome: i for i, (nome, _a, _b) in enumerate(segmentos)}
    tol_ov, gap = max(retract_dist * 2.5, 0.0015), max(retract_dist * 0.6, 0.0004)
    aabbs = [_bmesh_aabb(bm) for bm in bms]
    for c_idx, (c_nome, seg_a_c, seg_b_c) in enumerate(segmentos):
        osso_c = arm.data.bones.get(c_nome)
        pai = osso_c.parent if osso_c is not None else None
        if pai is None or pai.name not in idx_by_nome:
            continue
        p_idx = idx_by_nome[pai.name]
        p_nome, seg_a_p, seg_b_p = segmentos[p_idx]
        pmin, pmax = aabbs[p_idx]
        cmin, cmax = aabbs[c_idx]
        if min(min(pmax[d], cmax[d]) - max(pmin[d], cmin[d]) for d in range(3)) <= tol_ov:
            continue
        mid_p, mid_c = 0.5 * (seg_a_p + seg_b_p), 0.5 * (seg_a_c + seg_b_c)
        u = mid_c - mid_p
        if u.length < 1e-6:
            continue
        u.normalize()
        c_ov = Vector((0.5 * (max(pmin[d], cmin[d]) + min(pmax[d], cmax[d])) for d in range(3)))
        p_cut = seg_a_c if all(max(pmin[d], cmin[d]) <= seg_a_c[d] <= min(pmax[d], cmax[d]) for d in range(3)) else c_ov
        for idx_a, nome_a, mid_a, co_p, out_f, in_f in ((p_idx, p_nome, mid_p, p_cut - u * gap, True, False), (c_idx, c_nome, mid_c, p_cut + u * gap, False, True)):
            bm_t = bms[idx_a].copy()
            bmesh.ops.bisect_plane(bm_t, geom=list(bm_t.verts) + list(bm_t.edges) + list(bm_t.faces), plane_co=co_p, plane_no=u, clear_outer=out_f, clear_inner=in_f, dist=1e-5)
            _limpar_orfaos(bm_t)
            if len(bm_t.faces) >= 4:
                _fechar_e_triangular(bm_t, nome_a, mid_a, 0.0)
                bms[idx_a].free()
                bms[idx_a] = bm_t
                aabbs[idx_a] = _bmesh_aabb(bm_t)
            else:
                bm_t.free()


def main() -> None:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:]
    job = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    glb, saida, partes = Path(job["glb"]), Path(job["saida"]), job["partes"]
    saida.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(glb))

    arm = next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)
    malhas_cand = [o for o in bpy.data.objects if o.type == "MESH"]
    malha = max(malhas_cand, key=lambda o: (bool(o.vertex_groups), len(o.data.polygons)), default=None)
    if arm is None or malha is None:
        raise SystemExit("split: glb sem armature/malha")
    mundo_arm, mundo_malha = arm.matrix_world, malha.matrix_world

    segmentos, cabecas_bl, ancoras = [], {}, {}
    for parte in partes:
        nome = str(parte["nome"])
        osso = arm.data.bones.get(nome)
        if osso is None:
            raise SystemExit(f"split: osso ausente no rig: {nome}")
        cabeca, cauda = mundo_arm @ osso.head_local, mundo_arm @ osso.tail_local
        segmentos.append((nome, cabeca, cauda))
        cabecas_bl[nome] = cabeca
        ancoras[nome] = _bl_para_yup(cabeca)

    dados = malha.data
    bm_base = bmesh.new()
    bm_base.from_mesh(dados)
    bmesh.ops.remove_doubles(bm_base, verts=list(bm_base.verts), dist=1e-5)
    for seq in (bm_base.verts, bm_base.edges, bm_base.faces):
        seq.index_update()
    bm_base.verts.ensure_lookup_table()
    bm_base.faces.ensure_lookup_table()

    zs_w = [(mundo_malha @ v.co).z for v in bm_base.verts]
    altura_w = (max(zs_w) - min(zs_w)) if zs_w else 1.8
    retract_dist = 0.0006 * max(1.0, altura_w / 1.8)

    face_parte = _atribuir_faces(bm_base, malha, mundo_malha, segmentos)
    _empacotar_imagens_externas(glb.parent)

    bms_parte: list = []
    for idx, (nome, seg_a, seg_b) in enumerate(segmentos):
        bm = bm_base.copy()
        bm.faces.ensure_lookup_table()
        apagar = [f for f in bm.faces if face_parte[f.index] != idx]
        if len(apagar) == len(bm.faces):
            bm.free()
            raise SystemExit(f"split: parte vazia: {nome}")
        bmesh.ops.delete(bm, geom=apagar, context="FACES_ONLY")
        _limpar_orfaos(bm)
        bmesh.ops.transform(bm, matrix=mundo_malha, verts=list(bm.verts))
        _fechar_e_triangular(bm, nome, 0.5 * (seg_a + seg_b), retract_dist)
        bms_parte.append(bm)
    bm_base.free()

    _bisectar_sobrepostos(bms_parte, arm, segmentos, retract_dist)

    resumo, objetos = [], []
    for idx, (bm, (nome, _seg_a, _seg_b)) in enumerate(zip(bms_parte, segmentos)):
        novo = bpy.data.meshes.new(nome)
        for mat in dados.materials:
            novo.materials.append(mat)
        bm.to_mesh(novo)
        bm.free()

        obj = bpy.data.objects.new(nome, novo)
        bpy.context.scene.collection.objects.link(obj)
        obj.matrix_world = Matrix.Identity(4)
        obj.data.transform(Matrix.Translation(-cabecas_bl[nome]))
        cos = [v.co for v in obj.data.vertices]
        bbox_yup = [max(c.x for c in cos) - min(c.x for c in cos), max(c.z for c in cos) - min(c.z for c in cos), max(c.y for c in cos) - min(c.y for c in cos)]
        arquivo = f"{nome}.glb"
        _exportar_glb(saida / arquivo, [obj])
        resumo.append({"nome": nome, "junta": str(partes[idx].get("junta") or ""), "pivo": "junta", "ancora": ancoras[nome], "bbox": bbox_yup, "triangulos": len(obj.data.polygons), "arquivo": arquivo})
        objetos.append(obj)

    for obj, parte in zip(objetos, resumo):
        obj.location = cabecas_bl[parte["nome"]]
    _exportar_glb(saida / "partes_combinadas.glb", objetos)
    total = sum(p["triangulos"] for p in resumo)
    Path(argv[1]).write_text(json.dumps({"partes": resumo, "triangulos_total": total, "ancoras": ancoras}, indent=1), encoding="utf-8")
    print(f"SPLIT_OK partes={len(resumo)} tris={total}")


if __name__ == "__main__":
    main()
