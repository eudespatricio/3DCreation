"""Testes comportamentais independentes (@pytest.mark.blender, Sem Oraculo Comprado) para Onda 5 no Blender 4.2 headless."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from forge3d import config, post

RAIZ = Path(__file__).resolve().parents[1]
_BLENDER_DIR = RAIZ / "blender"


def _exigir_blender() -> str:
    ok, _ = post.preflight()
    blender = post.binario() if ok else None
    if not blender:
        pytest.skip("Blender 4.2 nao disponivel neste ambiente")
    return blender


_ONDA5_BLENDER_SCRIPT = """
import json, math, sys, traceback
import bpy, bmesh
from mathutils import Matrix, Vector

cfg = json.loads(open(sys.argv[-1], encoding="utf-8").read())
sys.path.insert(0, cfg["blender_dir"])
import bake_pbr_config, postprocess, postprocess_canon, postprocess_normals_uv, postprocess_repair

out = {}

def _bbox_extents(obj):
    xs = [v.co.x for v in obj.data.vertices]
    ys = [v.co.y for v in obj.data.vertices]
    zs = [v.co.z for v in obj.data.vertices]
    if not xs:
        return {"dx": 0.0, "dy": 0.0, "dz": 0.0, "z_min": 0.0, "z_max": 0.0}
    return {
        "dx": max(xs) - min(xs),
        "dy": max(ys) - min(ys),
        "dz": max(zs) - min(zs),
        "z_min": min(zs),
        "z_max": max(zs),
    }

def _add_subdivided_box(bm, sx, sy, sz0, sz1, cuts=6):
    hz = 0.5 * (sz1 - sz0)
    cz = 0.5 * (sz0 + sz1)
    ret = bmesh.ops.create_cube(bm, size=1.0)
    verts = ret["verts"]
    for v in verts:
        v.co.x *= sx
        v.co.y *= sy
        v.co.z = cz + v.co.z * (sz1 - sz0)
    edges = [e for e in bm.edges if all(v in verts for v in e.verts)]
    if cuts > 0:
        bmesh.ops.subdivide_edges(bm, edges=edges, cuts=cuts, use_grid_fill=True)

# ==============================================================================
# TEST A: Hard-surface stepped house + <0.4% ornament finial + Quadriflow/Decimate
# ==============================================================================
try:
    postprocess.limpar_cena()
    me_a = bpy.data.meshes.new("templo_hard_surface")
    obj_a = bpy.data.objects.new("templo_hard_surface", me_a)
    bpy.context.collection.objects.link(obj_a)
    bpy.context.view_layer.objects.active = obj_a

    bm_a = bmesh.new()
    # 3 degraus ortogonais 90 graus (~2916 faces triangulares)
    _add_subdivided_box(bm_a, 3.0, 2.4, 0.0, 1.4, cuts=8)
    _add_subdivided_box(bm_a, 2.0, 1.6, 1.4, 2.2, cuts=8)
    _add_subdivided_box(bm_a, 1.2, 1.0, 2.2, 2.8, cuts=8)
    # Ornamento/pinaculo pequeno destacado no topo (12 tris em ~2928 -> ~0.41%, ou tetraedro/octaedro 8 tris -> 0.27% < 0.4%)
    ret_fin = bmesh.ops.create_cone(
        bm_a,
        cap_ends=True,
        cap_tris=True,
        segments=4,
        radius1=0.06,
        radius2=0.0,
        depth=0.20,
        matrix=Matrix.Translation((0.0, 0.0, 3.05)),
    )
    bmesh.ops.triangulate(bm_a, faces=list(bm_a.faces))
    bm_a.normal_update()
    bm_a.to_mesh(me_a)
    bm_a.free()
    me_a.update()

    faces_iniciais = len(me_a.polygons)
    verts_finial_antes = sum(1 for v in me_a.vertices if v.co.z >= 2.92)
    frac_finial = 6.0 / float(max(1, faces_iniciais))

    # 1) _remesh_voxel_preservando_partes com eh_organico=False deve ser no-op estrito (False)
    voxel_noop = postprocess_repair._remesh_voxel_preservando_partes(obj_a, eh_organico=False)
    faces_pos_noop = len(obj_a.data.polygons)
    verts_finial_pos_noop = sum(1 for v in obj_a.data.vertices if v.co.z >= 2.92)

    # 2) retopologizar_quadriflow com eh_organico=False deve retornar False sem rodar voxel remesh nem apagar pinaculo
    qf_ret = postprocess.retopologizar_quadriflow(obj_a, 1800, eh_organico=False)
    faces_pos_qf = len(obj_a.data.polygons)
    verts_finial_pos_qf = sum(1 for v in obj_a.data.vertices if v.co.z >= 2.92)

    # 2b) Quando forcar_hard_surface=True (opt-in explicito na spec) e eh_organico=False, NAO pode chamar _remesh_voxel_preservando_partes
    me_qf_hs = obj_a.data.copy()
    obj_qf_hs = bpy.data.objects.new("templo_qf_optin", me_qf_hs)
    bpy.context.collection.objects.link(obj_qf_hs)
    chamadas_voxel_hs = {"n": 0}
    orig_voxel_fn = postprocess_repair._remesh_voxel_preservando_partes
    def _spy_voxel_hs(*a, **kw):
        if kw.get("eh_organico", True) is not False:
            chamadas_voxel_hs["n"] += 1
        return orig_voxel_fn(*a, **kw)
    postprocess_repair._remesh_voxel_preservando_partes = _spy_voxel_hs
    try:
        postprocess.retopologizar_quadriflow(obj_qf_hs, 1800, eh_organico=False, forcar_hard_surface=True)
    finally:
        postprocess_repair._remesh_voxel_preservando_partes = orig_voxel_fn
    bpy.data.objects.remove(obj_qf_hs, do_unlink=True)
    bpy.data.meshes.remove(me_qf_hs, do_unlink=True)
    bpy.context.view_layer.objects.active = obj_a

    # 3) decimar com eh_organico=False preserva altura, quinas 90 graus e o pinaculo <0.4%
    tris_dec = postprocess_repair.decimar(obj_a, 1800, eh_organico=False)
    ext_pos_dec = _bbox_extents(obj_a)
    verts_finial_pos_dec = sum(1 for v in obj_a.data.vertices if v.co.z >= 2.92)
    sharp_edges_dec = sum(1 for e in obj_a.data.edges if e.use_edge_sharp)

    # Fidelidade ortogonal das normais (faces principais do templo continuam alinhadas aos eixos X/Y/Z)
    area_tot = 0.0
    area_orto = 0.0
    for p in obj_a.data.polygons:
        if p.center.z < 2.85:
            a = float(p.area)
            area_tot += a
            n = p.normal
            if max(abs(n.x), abs(n.y), abs(n.z)) >= 0.95:
                area_orto += a
    frac_orto = area_orto / max(1e-9, area_tot)

    # 4) calcular_quadriflow_faces
    qf_1800 = postprocess.calcular_quadriflow_faces(1800)
    qf_4000_hero = postprocess.calcular_quadriflow_faces(4000, qualidade="hero")

    out["test_a"] = {
        "ok": True,
        "faces_iniciais": faces_iniciais,
        "frac_finial": frac_finial,
        "verts_finial_antes": verts_finial_antes,
        "voxel_noop": voxel_noop,
        "faces_pos_noop": faces_pos_noop,
        "verts_finial_pos_noop": verts_finial_pos_noop,
        "qf_ret": qf_ret,
        "faces_pos_qf": faces_pos_qf,
        "verts_finial_pos_qf": verts_finial_pos_qf,
        "chamadas_voxel_hs": chamadas_voxel_hs["n"],
        "tris_dec": tris_dec,
        "ext_pos_dec": ext_pos_dec,
        "verts_finial_pos_dec": verts_finial_pos_dec,
        "sharp_edges_dec": sharp_edges_dec,
        "frac_orto": frac_orto,
        "qf_1800": qf_1800,
        "qf_4000_hero": qf_4000_hero,
    }
except Exception:
    out["test_a"] = {"ok": False, "erro": traceback.format_exc()}

# ==============================================================================
# TEST B: Thin wall protection + dual-shell sphere regression + T-edge + spire guard
# ==============================================================================
try:
    postprocess.limpar_cena()

    def _construir_parede_fina(nome, cuts=6):
        me = bpy.data.meshes.new(nome)
        ob = bpy.data.objects.new(nome, me)
        bpy.context.collection.objects.link(ob)
        bm = bmesh.new()
        # Parede arquitetonica fina: 2.0m x 0.04m x 1.0m (espessura 0.04m vs diag ~2.236m = 1.79%)
        _add_subdivided_box(bm, 2.0, 0.04, 0.0, 1.0, cuts=cuts)
        bmesh.ops.triangulate(bm, faces=list(bm.faces))
        bm.normal_update()
        bm.to_mesh(me)
        bm.free()
        me.update()
        return ob

    parede_high_hs = _construir_parede_fina("parede_high_hs", cuts=6)
    parede_high_org = _construir_parede_fina("parede_high_org", cuts=6)
    parede_low = _construir_parede_fina("parede_low", cuts=3)

    res_parede_hs = bake_pbr_config.filtrar_casca_interna_high(parede_high_hs, parede_low, eh_organico=False)
    res_parede_org = bake_pbr_config.filtrar_casca_interna_high(parede_high_org, parede_low, eh_organico=True)

    # Regressao: esfera R=1.5 com casca interna coplanar invertida (offset 0.002) ainda deve ser limpa
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=1.5)
    esf_low = bpy.context.active_object
    esf_low.name = "esf_low"
    bpy.ops.mesh.primitive_uv_sphere_add(segments=36, ring_count=18, radius=1.5)
    esf_high = bpy.context.active_object
    esf_high.name = "esf_high"
    bm_e = bmesh.new()
    bm_e.from_mesh(esf_high.data)
    bmesh.ops.triangulate(bm_e, faces=list(bm_e.faces))
    bm_e.normal_update()
    dup = bmesh.ops.duplicate(bm_e, geom=list(bm_e.verts) + list(bm_e.edges) + list(bm_e.faces))
    for v in (g for g in dup["geom"] if isinstance(g, bmesh.types.BMVert)):
        v.co = v.co - v.normal * 0.002
    bmesh.ops.reverse_faces(bm_e, faces=[g for g in dup["geom"] if isinstance(g, bmesh.types.BMFace)])
    bm_e.to_mesh(esf_high.data)
    bm_e.free()
    esf_high.data.update()
    res_esfera_dupla = bake_pbr_config.filtrar_casca_interna_high(esf_high, esf_low, eh_organico=True)

    # T-edge exterior preservation em reparar_malha:
    # Cubo externo [-1, 1]^3 fechado + aba T interna apontando para dentro numa aresta do topo
    me_t = bpy.data.meshes.new("cubo_t_edge")
    obj_t = bpy.data.objects.new("cubo_t_edge", me_t)
    bpy.context.collection.objects.link(obj_t)
    bm_t = bmesh.new()
    bmesh.ops.create_cube(bm_t, size=2.0)
    bmesh.ops.triangulate(bm_t, faces=list(bm_t.faces))
    bm_t.verts.ensure_lookup_table()
    bm_t.edges.ensure_lookup_table()
    # Escolhe uma aresta externa e pendura um triangulo interno cuja normal aponta para o centroide (dot < 0)
    e_top = next(e for e in bm_t.edges if e.verts[0].co.z > 0.9 and e.verts[1].co.z > 0.9)
    v_in = bm_t.verts.new((0.0, 0.0, 0.85))
    f_in = bm_t.faces.new((e_top.verts[0], e_top.verts[1], v_in))
    bm_t.normal_update()
    if f_in.normal.dot(f_in.calc_center_median()) > 0.0:
        f_in.normal_flip()
    bm_t.to_mesh(me_t)
    bm_t.free()
    me_t.update()

    rep_t = postprocess_repair.reparar_malha(obj_t)
    nm_pos_t = postprocess_repair._contar_nao_manifold(obj_t, weld_dist=0.0)
    faces_restantes_t = len(obj_t.data.polygons)

    # Spire shrinkage guard em _remesh_voxel_preservando_partes:
    # Base solida 1.0x1.0x0.4 + agulha ultra-fina (0.002m x 0.002m x 1.6m ate z=2.0m) que o voxel remesh colapsaria
    me_sp = bpy.data.meshes.new("torre_agulha")
    obj_sp = bpy.data.objects.new("torre_agulha", me_sp)
    bpy.context.collection.objects.link(obj_sp)
    bm_sp = bmesh.new()
    _add_subdivided_box(bm_sp, 1.0, 1.0, 0.0, 0.4, cuts=2)
    _add_subdivided_box(bm_sp, 0.002, 0.002, 0.4, 2.0, cuts=0)
    bmesh.ops.triangulate(bm_sp, faces=list(bm_sp.faces))
    bm_sp.to_mesh(me_sp)
    bm_sp.free()
    me_sp.update()
    dz_antes_sp = _bbox_extents(obj_sp)["dz"]
    sp_ret = postprocess_repair._remesh_voxel_preservando_partes(obj_sp, eh_organico=True, max_encolhimento_h=0.10)
    dz_depois_sp = _bbox_extents(obj_sp)["dz"]

    out["test_b"] = {
        "ok": True,
        "parede_hs": res_parede_hs,
        "parede_org": res_parede_org,
        "esfera_dupla": res_esfera_dupla,
        "rep_t": rep_t,
        "nm_pos_t": nm_pos_t,
        "faces_restantes_t": faces_restantes_t,
        "dz_antes_sp": dz_antes_sp,
        "sp_ret": sp_ret,
        "dz_depois_sp": dz_depois_sp,
    }
except Exception:
    out["test_b"] = {"ok": False, "erro": traceback.format_exc()}

# ==============================================================================
# TEST C: canonicalizar wide prop preservation + desdobrar_uv head boost gating
# ==============================================================================
try:
    postprocess.limpar_cena()
    # Predio baixo e largo: 4.0m (X) x 2.0m (Y) x 1.2m (Z)
    me_w = bpy.data.meshes.new("predio_largo")
    obj_w = bpy.data.objects.new("predio_largo", me_w)
    bpy.context.collection.objects.link(obj_w)
    bpy.context.view_layer.objects.active = obj_w
    bm_w = bmesh.new()
    _add_subdivided_box(bm_w, 4.0, 2.0, 0.0, 1.2, cuts=2)
    bmesh.ops.triangulate(bm_w, faces=list(bm_w.faces))
    bm_w.to_mesh(me_w)
    bm_w.free()
    me_w.update()

    postprocess_canon.canonicalizar(obj_w, tipo="prop_estatico", frente_origem=None)
    ext_wide = _bbox_extents(obj_w)

    # Torso (1.0 x 1.0, z=0..2.2) + cabeca destacada (0.45 x 0.45, z=2.2..3.0) para formar ilhas UV separadas no topo (>= 78% altura, >= 400 poligonos)
    def _medir_razao_uv_topo(nome, eh_organico):
        me = bpy.data.meshes.new(nome)
        ob = bpy.data.objects.new(nome, me)
        bpy.context.collection.objects.link(ob)
        bpy.context.view_layer.objects.active = ob
        bm = bmesh.new()
        _add_subdivided_box(bm, 1.0, 1.0, 0.0, 2.2, cuts=6)
        _add_subdivided_box(bm, 0.45, 0.45, 2.2, 3.0, cuts=5)
        bmesh.ops.triangulate(bm, faces=list(bm.faces))
        bm.to_mesh(me)
        bm.free()
        me.update()

        postprocess_normals_uv.desdobrar_uv(ob, eh_organico=eh_organico)
        bm_u = bmesh.new()
        bm_u.from_mesh(ob.data)
        uv_lay = bm_u.loops.layers.uv.active
        uv_top, area3d_top = 0.0, 0.0
        uv_mid, area3d_mid = 0.0, 0.0
        for f in bm_u.faces:
            # Considera apenas faces verticais laterais (todas do mesmo tamanho nas faixas Z)
            if abs(f.normal.z) > 0.5:
                continue
            cz = f.calc_center_median().z
            a3 = max(1e-9, float(f.calc_area()))
            uvs = [l[uv_lay].uv for l in f.loops]
            if len(uvs) == 3:
                auv = 0.5 * abs((uvs[1].x - uvs[0].x) * (uvs[2].y - uvs[0].y) - (uvs[2].x - uvs[0].x) * (uvs[1].y - uvs[0].y))
            else:
                auv = 0.0
            if cz >= 2.40:
                uv_top += auv
                area3d_top += a3
            elif 0.60 <= cz <= 1.80:
                uv_mid += auv
                area3d_mid += a3
        bm_u.free()
        dens_top = uv_top / max(1e-9, area3d_top)
        dens_mid = uv_mid / max(1e-9, area3d_mid)
        return dens_top / max(1e-12, dens_mid)

    razao_uv_hs = _medir_razao_uv_topo("col_hs", False)
    razao_uv_org = _medir_razao_uv_topo("col_org", True)

    out["test_c"] = {
        "ok": True,
        "ext_wide": ext_wide,
        "razao_uv_hs": razao_uv_hs,
        "razao_uv_org": razao_uv_org,
    }
except Exception:
    out["test_c"] = {"ok": False, "erro": traceback.format_exc()}

open(cfg["out_json"], "w", encoding="utf-8").write(json.dumps(out))
"""


@pytest.fixture(scope="module")
def _dados_blender_onda5(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    blender = _exigir_blender()
    pasta = tmp_path_factory.mktemp("onda5_blender")
    mp = pytest.MonkeyPatch()
    mp.setenv("FORGE3D_HOME", str(pasta / "forge_home"))
    mp.setenv("FORGE3D_CONFIG", str(pasta / "forge_cfg"))
    config.adicionar(pasta)
    try:
        cfg_path = pasta / "cfg.json"
        script_path = pasta / "run_onda5.py"
        out_json = pasta / "out.json"
        cfg_path.write_text(
            json.dumps({"blender_dir": str(_BLENDER_DIR), "out_json": str(out_json)}),
            encoding="utf-8",
        )
        script_path.write_text(_ONDA5_BLENDER_SCRIPT, encoding="utf-8")
        proc = subprocess.run(
            [
                blender,
                "--background",
                "--factory-startup",
                "--python-exit-code",
                "1",
                "--python",
                str(script_path),
                "--",
                str(cfg_path),
            ],
            capture_output=True,
            text=True,
            timeout=180,
        )
        assert proc.returncode == 0, f"Blender Onda 5 falhou:\nSTDOUT={proc.stdout}\nSTDERR={proc.stderr}"
        return json.loads(out_json.read_text(encoding="utf-8"))
    finally:
        mp.undo()


@pytest.mark.blender
def test_onda5_blender_a_hard_surface_protege_ornamento_e_pula_quadriflow(_dados_blender_onda5: dict[str, Any]) -> None:
    ta = _dados_blender_onda5["test_a"]
    assert ta["ok"] is True, ta.get("erro")
    assert ta["frac_finial"] < 0.004, f"Ornamento deve ter < 0.4% das faces: {ta['frac_finial']}"
    assert ta["verts_finial_antes"] >= 4

    # _remesh_voxel_preservando_partes(obj, eh_organico=False) -> no-op estrito
    assert ta["voxel_noop"] is False
    assert ta["faces_pos_noop"] == ta["faces_iniciais"]
    assert ta["verts_finial_pos_noop"] == ta["verts_finial_antes"]

    # retopologizar_quadriflow(obj, 1800, eh_organico=False) -> False e preserva malha/ornamento
    assert ta["qf_ret"] is False
    assert ta["faces_pos_qf"] == ta["faces_iniciais"]
    assert ta["verts_finial_pos_qf"] == ta["verts_finial_antes"]
    assert ta["chamadas_voxel_hs"] == 0

    # decimar(obj, 1800, eh_organico=False) -> preserva silhueta, quinas 90 graus e ornamento < 0.4%
    assert ta["tris_dec"] <= 1800
    assert ta["ext_pos_dec"]["z_max"] == pytest.approx(3.15, abs=0.05)
    assert ta["ext_pos_dec"]["dz"] == pytest.approx(3.15, abs=0.05)
    assert ta["verts_finial_pos_dec"] >= 4, f"Pinaculo <0.4% foi apagado na decimacao: {ta}"
    assert ta["sharp_edges_dec"] > 0
    assert ta["frac_orto"] >= 0.90, f"Quinas de 90 graus perderam fidelidade ortogonal: {ta['frac_orto']}"

    # calcular_quadriflow_faces
    assert ta["qf_1800"] == int(round(1800 * 0.38))
    assert ta["qf_4000_hero"] == int(round(4000 * 0.42))


@pytest.mark.blender
def test_onda5_blender_b_parede_fina_preservada_casca_dupla_limpa_t_edge_e_agulha(_dados_blender_onda5: dict[str, Any]) -> None:
    tb = _dados_blender_onda5["test_b"]
    assert tb["ok"] is True, tb.get("erro")

    # Parede arquitetonica fina (2.0 x 0.04 x 1.0m) preservada tanto em eh_organico=False quanto True
    for modo, res_p in (("hard_surface", tb["parede_hs"]), ("organico", tb["parede_org"])):
        assert int(res_p["faces_removidas"]) == 0 or res_p["aplicado"] is False, (modo, res_p)

    # Regressao: casca dupla coplanar invertida em esfera R=1.5 continua sendo removida
    esf = tb["esfera_dupla"]
    tot_esf = int(esf["faces_removidas"]) + int(esf["faces_restantes"])
    assert esf["aplicado"] is True and tot_esf > 0 and int(esf["faces_removidas"]) >= 0.40 * tot_esf, esf

    # T-edge pruning preserva as 12 faces da casca externa e remove apenas a aba interna
    assert tb["nm_pos_t"][0] == 0 and tb["nm_pos_t"][1] == 0, tb["nm_pos_t"]
    assert tb["faces_restantes_t"] == 12, f"Casca externa do cubo foi furada no T-edge pruning: {tb}"

    # Spire shrinkage guard restaura backup quando o voxel remesh encolhe a agulha > 10%
    assert tb["dz_depois_sp"] >= 0.90 * tb["dz_antes_sp"], (
        f"Agulha encolheu de {tb['dz_antes_sp']} para {tb['dz_depois_sp']} (ret={tb['sp_ret']})"
    )


@pytest.mark.blender
def test_onda5_blender_c_canonicalizar_prop_largo_e_uv_sem_boost_cabeca_em_hard_surface(
    _dados_blender_onda5: dict[str, Any],
) -> None:
    tc = _dados_blender_onda5["test_c"]
    assert tc["ok"] is True, tc.get("erro")

    # Predio baixo e largo (4.0m x 2.0m x 1.2m) com tipo="prop_estatico" permanece com altura Z ~ 1.2m
    ext = tc["ext_wide"]
    assert ext["dz"] == pytest.approx(1.2, abs=0.05), f"Prop largo foi tombado de lado: {ext}"
    assert max(ext["dx"], ext["dy"]) == pytest.approx(4.0, abs=0.05)

    # desdobrar_uv(..., eh_organico=False) nao infla as faces superiores como o boost de cabeca organico
    assert tc["razao_uv_hs"] == pytest.approx(1.0, abs=0.18), f"Hard-surface recebeu boost UV no topo: {tc}"
    assert tc["razao_uv_org"] > tc["razao_uv_hs"] * 1.35, (
        f"Organico deveria ter boost UV na cabeca significativamente maior que hard-surface: {tc}"
    )
