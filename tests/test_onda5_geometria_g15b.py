"""Testes comportamentais independentes (Sem Oraculo Comprado) para Onda 5: TRELLIS.2 o_voxel, GAP-060, G15b volumetrico e GAP-054."""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image, ImageDraw

from forge3d import profiles, qc, qc_fidelidade, qc_geom
from forge3d.providers import mesh_trellis
from tests.test_seguranca_e_qc import _glb_bytes

RAIZ = Path(__file__).resolve().parents[1]


def _carregar_modulo_tools(nome_arquivo: str) -> Any:
    caminho = RAIZ / "tools" / nome_arquivo
    spec = importlib.util.spec_from_file_location(f"_tools_{caminho.stem}", caminho)
    assert spec is not None and spec.loader is not None, f"Nao foi possivel carregar {caminho}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _caixa_fechada(
    semi_x: float,
    semi_y: float,
    semi_z: float,
    *,
    centro: tuple[float, float, float] = (0.0, 0.0, 0.0),
    inverter_winding: bool = False,
    inverter_apenas_ultimo_tri: bool = False,
    offset_idx: int = 0,
) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    cx, cy, cz = centro
    verts = [
        (cx - semi_x, cy - semi_y, cz - semi_z),
        (cx + semi_x, cy - semi_y, cz - semi_z),
        (cx + semi_x, cy + semi_y, cz - semi_z),
        (cx - semi_x, cy + semi_y, cz - semi_z),
        (cx - semi_x, cy - semi_y, cz + semi_z),
        (cx + semi_x, cy - semi_y, cz + semi_z),
        (cx + semi_x, cy + semi_y, cz + semi_z),
        (cx - semi_x, cy + semi_y, cz + semi_z),
    ]
    tris_base = [
        (0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7),
        (0, 1, 5), (0, 5, 4), (2, 3, 7), (2, 7, 6),
        (0, 4, 7), (0, 7, 3), (1, 2, 6), (1, 6, 5),
    ]
    tris: list[tuple[int, int, int]] = []
    for i, (a, b, c) in enumerate(tris_base):
        inv = (not inverter_winding) if (inverter_apenas_ultimo_tri and i == len(tris_base) - 1) else inverter_winding
        tris.append((a + offset_idx, c + offset_idx, b + offset_idx) if inv else (a + offset_idx, b + offset_idx, c + offset_idx))
    return verts, tris


def _elipsoide_malha(
    rx: float = 0.40,
    ry: float = 0.50,
    rz: float = 0.38,
    *,
    cy: float = 0.50,
    segments: int = 20,
    rings: int = 12,
    modo: str = "solido",
) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    """Constroi elipsoide/ovo UV fechado ou com defeitos controlados (sem_costas, buraco_frontal)."""
    verts: list[tuple[float, float, float]] = [(0.0, cy + ry, 0.0)]
    for r in range(1, rings):
        theta = math.pi * r / rings
        st, ct = math.sin(theta), math.cos(theta)
        y = cy + ry * ct
        for s in range(segments):
            phi = 2.0 * math.pi * s / segments
            verts.append((rx * st * math.sin(phi), y, rz * st * math.cos(phi)))
    polo_sul = len(verts)
    verts.append((0.0, cy - ry, 0.0))

    def _anel(r_idx: int, s_idx: int) -> int:
        return 1 + (r_idx - 1) * segments + (s_idx % segments)

    tris_brutos: list[tuple[int, int, int]] = [(0, _anel(1, s), _anel(1, s + 1)) for s in range(segments)]
    for r in range(1, rings - 1):
        for s in range(segments):
            v00, v10, v11, v01 = _anel(r, s), _anel(r + 1, s), _anel(r + 1, s + 1), _anel(r, s + 1)
            tris_brutos.extend(((v00, v10, v11), (v00, v11, v01)))
    tris_brutos.extend((_anel(rings - 1, s), polo_sul, _anel(rings - 1, s + 1)) for s in range(segments))
    if modo == "solido":
        return verts, tris_brutos

    tris_filtrados: list[tuple[int, int, int]] = []
    for a, b, c in tris_brutos:
        pa, pb, pc = verts[a], verts[b], verts[c]
        cx_t, cy_t, cz_t = (pa[0] + pb[0] + pc[0]) / 3.0, (pa[1] + pb[1] + pc[1]) / 3.0, (pa[2] + pb[2] + pc[2]) / 3.0
        if modo == "sem_costas":
            if cz_t <= 0.0:
                tris_filtrados.append((a, b, c))
        elif modo == "buraco_frontal":
            r2d = math.hypot(cx_t / max(rx, 1e-6), (cy_t - cy) / max(ry, 1e-6))
            if cz_t >= 0.0 or r2d >= 0.88:
                tris_filtrados.append((a, b, c))
        else:
            raise ValueError(f"Modo desconhecido: {modo}")
    return verts, tris_filtrados


def _casca_crescente_fina_z(
    *,
    rx: float = 0.50,
    ry: float = 0.50,
    cy: float = 0.50,
    curvatura_z: float = 0.385,
    espessura_z: float = 0.015,
    nx: int = 12,
    ny: int = 12,
) -> tuple[list[tuple[float, float, float]], list[tuple[int, int, int]]]:
    """Casca curva fina em Z: bounding dz ~ 0.40m, mas espessura local (z_max - z_min) = 0.015m em cada pixel."""
    verts: list[tuple[float, float, float]] = []
    stride = nx + 1
    for iy in range(ny + 1):
        v = -1.0 + 2.0 * iy / ny
        for ix in range(nx + 1):
            u = -1.0 + 2.0 * ix / nx
            zf = -0.20 + curvatura_z * min(1.0, 0.5 * (u * u + v * v))
            verts.append((rx * u, cy + ry * v, zf))
    offset_back = len(verts)
    verts.extend((x, y, zf + espessura_z) for x, y, zf in list(verts))

    tris: list[tuple[int, int, int]] = []
    for iy in range(ny):
        for ix in range(nx):
            i00 = iy * stride + ix
            i10, i01, i11 = i00 + 1, (iy + 1) * stride + ix, (iy + 1) * stride + ix + 1
            b00, b10, b01, b11 = i00 + offset_back, i10 + offset_back, i01 + offset_back, i11 + offset_back
            tris.extend(((i00, i01, i11), (i00, i11, i10), (b00, b11, b01), (b00, b10, b11)))

    borda = (
        list(range(nx))
        + [iy * stride + nx for iy in range(ny)]
        + [ny * stride + ix for ix in range(nx, 0, -1)]
        + [iy * stride for iy in range(ny, 0, -1)]
    )
    for k, f0 in enumerate(borda):
        f1 = borda[(k + 1) % len(borda)]
        b0, b1 = f0 + offset_back, f1 + offset_back
        tris.extend(((f0, f1, b1), (f0, b1, b0)))
    return verts, tris


def _glb_de_malha(
    verts: list[tuple[float, float, float]],
    tris: list[tuple[int, int, int]],
) -> tuple[bytes, dict[str, Any], bytes]:
    uvs = [(0.1 + 0.8 * ((i * 7) % 13) / 12.0, 0.1 + 0.8 * ((i * 11) % 17) / 16.0) for i in range(len(verts))]
    raw = _glb_bytes(verts=verts, tris=tris, uvs=uvs)
    gltf, binario = qc.ler_glb_bin(raw)
    return raw, gltf, binario


def test_trellis2_remesh_project_default_09_e_cache_tag_sensivel(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FORGE3D_TRELLIS2_REMESH_PROJECT", raising=False)
    assert mesh_trellis.remesh_project_trellis2() == pytest.approx(0.9)
    tag_padrao = mesh_trellis.cache_tag_trellis2()

    monkeypatch.setenv("FORGE3D_TRELLIS2_REMESH_PROJECT", "0.9")
    assert mesh_trellis.cache_tag_trellis2() == tag_padrao

    monkeypatch.setenv("FORGE3D_TRELLIS2_REMESH_PROJECT", "1.0")
    assert mesh_trellis.remesh_project_trellis2() == pytest.approx(1.0)
    tag_10 = mesh_trellis.cache_tag_trellis2()
    assert tag_10 != tag_padrao

    monkeypatch.setenv("FORGE3D_TRELLIS2_REMESH_PROJECT", "0.65")
    assert mesh_trellis.remesh_project_trellis2() == pytest.approx(0.65)
    assert mesh_trellis.cache_tag_trellis2() not in {tag_padrao, tag_10}


def test_executar_to_glb_seguro_injeta_remove_inner_faces_e_limpa_antes_de_uv_unwrap() -> None:
    t2_mod = _carregar_modulo_tools("trellis2_infer.py")
    fn_seguro = t2_mod._executar_to_glb_seguro
    eventos: list[str] = []
    dc_kwargs_recebidos: list[dict[str, Any]] = []

    def orig_remesh_dc(_grid: Any, *, band: float = 1.0, remove_inner_faces: bool = False) -> str:
        dc_kwargs_recebidos.append({"band": band, "remove_inner_faces": remove_inner_faces})
        eventos.append(f"remesh_dc:remove_inner_faces={remove_inner_faces}")
        return "dc_ok"

    class FakeCuMesh:
        def remove_duplicate_faces(self) -> None:
            eventos.append("remove_duplicate_faces")

        def remove_degenerate_faces(self) -> None:
            eventos.append("remove_degenerate_faces")

        def repair_non_manifold_edges(self) -> None:
            eventos.append("repair_non_manifold_edges")

        def remove_small_connected_components(self, *_a: Any, **_kw: Any) -> None:
            eventos.append("remove_small_connected_components")

        def fill_holes(self, *_a: Any, **_kw: Any) -> None:
            eventos.append("fill_holes")

        def unify_face_orientations(self) -> None:
            eventos.append("unify_face_orientations")

        def uv_unwrap(self, *_a: Any, **_kw: Any) -> str:
            eventos.append("uv_unwrap")
            return "uv_ok"

    orig_uv_unwrap = FakeCuMesh.uv_unwrap
    cumesh_mod = SimpleNamespace(remeshing=SimpleNamespace(remesh_narrow_band_dc=orig_remesh_dc), CuMesh=FakeCuMesh)

    def fake_to_glb(**kwargs: Any) -> dict[str, Any]:
        cumesh_mod.remeshing.remesh_narrow_band_dc("grid_dummy", band=0.5)
        cumesh_mod.CuMesh().uv_unwrap()
        return {"glb": "ok", "kwargs": kwargs}

    o_voxel_mod = SimpleNamespace(postprocess=SimpleNamespace(to_glb=fake_to_glb))
    fake_mesh_out = SimpleNamespace(
        vertices=[1, 2, 3], faces=[1], attrs="a", coords="c", layout={}, voxel_size=0.01
    )
    res, meta = fn_seguro(
        o_voxel_mod, cumesh_mod, fake_mesh_out,
        decimation_target=32000, texture_size=2048, remesh=True, remesh_project=0.9, timeout_s=5.0,
    )
    assert res["glb"] == "ok"
    assert dc_kwargs_recebidos == [{"band": 0.5, "remove_inner_faces": True}]
    assert eventos == [
        "remesh_dc:remove_inner_faces=True",
        "remove_duplicate_faces",
        "remove_degenerate_faces",
        "repair_non_manifold_edges",
        "remove_small_connected_components",
        "fill_holes",
        "unify_face_orientations",
        "uv_unwrap",
    ]
    assert meta.get("remesh_fallback") is not True
    assert cumesh_mod.remeshing.remesh_narrow_band_dc is orig_remesh_dc
    assert FakeCuMesh.uv_unwrap is orig_uv_unwrap


def test_executar_to_glb_seguro_assinatura_sem_remove_inner_faces_e_fallback_remesh() -> None:
    t2_mod = _carregar_modulo_tools("trellis2_infer.py")
    fn_seguro = t2_mod._executar_to_glb_seguro
    chamadas_dc: list[tuple[Any, ...]] = []

    def dc_legado(grid: Any, band: float = 1.0) -> str:
        chamadas_dc.append((grid, band))
        return "dc_legado_ok"

    class FakeCuMesh:
        def uv_unwrap(self, *_a: Any, **_kw: Any) -> str:
            return "uv_ok"

    orig_uv = FakeCuMesh.uv_unwrap
    cumesh_mod = SimpleNamespace(remeshing=SimpleNamespace(remesh_narrow_band_dc=dc_legado), CuMesh=FakeCuMesh)
    tentativas: list[dict[str, Any]] = []

    def fake_to_glb_com_falha_no_remesh(**kwargs: Any) -> str:
        tentativas.append(dict(kwargs))
        cumesh_mod.remeshing.remesh_narrow_band_dc("g", 0.75)
        cumesh_mod.CuMesh().uv_unwrap()
        if kwargs.get("remesh") is True:
            raise TimeoutError("xatlas travou no remesh=True")
        return "glb_recuperado"

    o_voxel_mod = SimpleNamespace(postprocess=SimpleNamespace(to_glb=fake_to_glb_com_falha_no_remesh))
    fake_mesh_out = SimpleNamespace(
        vertices=[1, 2, 3], faces=[1], attrs="a", coords="c", layout={}, voxel_size=0.01
    )
    glb, meta = fn_seguro(
        o_voxel_mod, cumesh_mod, fake_mesh_out,
        decimation_target=48000, texture_size=2048, remesh=True, remesh_project=0.9, timeout_s=5.0,
    )
    assert glb == "glb_recuperado"
    assert len(tentativas) == 2
    assert tentativas[0]["remesh"] is True and tentativas[0]["decimation_target"] == 48000
    assert tentativas[1]["remesh"] is False and tentativas[1]["decimation_target"] == 48000
    assert meta.get("remesh_fallback") is True
    assert len(chamadas_dc) == 2
    assert cumesh_mod.remeshing.remesh_narrow_band_dc is dc_legado
    assert FakeCuMesh.uv_unwrap is orig_uv

    def fake_to_glb_falha_dupla(**_kwargs: Any) -> str:
        raise RuntimeError("falha fatal em ambos")

    o_voxel_falho = SimpleNamespace(postprocess=SimpleNamespace(to_glb=fake_to_glb_falha_dupla))
    with pytest.raises(RuntimeError, match="falha fatal em ambos"):
        fn_seguro(
            o_voxel_falho, cumesh_mod, fake_mesh_out,
            decimation_target=48000, texture_size=2048, remesh=True, remesh_project=0.9, timeout_s=5.0,
        )
    assert cumesh_mod.remeshing.remesh_narrow_band_dc is dc_legado
    assert FakeCuMesh.uv_unwrap is orig_uv


def test_qc_geom_topologia_gap_060_conflito_w_e_casca_interna_trellis() -> None:
    v_out, t_out = _caixa_fechada(1.0, 1.0, 1.0, inverter_winding=False, offset_idx=0)

    # GAP-060: casca interna pequena (<10% vol_out) mas com conflito_w=True -> invertidas >= 1
    v_in_w, t_in_w = _caixa_fechada(0.3, 0.3, 0.3, inverter_winding=True, inverter_apenas_ultimo_tri=True, offset_idx=len(v_out))
    topo_w = qc_geom.topologia(v_out + v_in_w, t_out + t_in_w)
    assert topo_w["invertidas"] >= 1, f"GAP-060: conflito_w em casca interna deve incrementar invertidas: {topo_w}"
    assert "volume_total" in topo_w and "aabb_fill" in topo_w

    # Casca interna de dual-contouring TRELLIS (abs(vol_in)/vol_out = 0.85 >= 0.70) -> invertidas >= 1
    s_85 = 0.85 ** (1.0 / 3.0)
    v_in_85, t_in_85 = _caixa_fechada(s_85, s_85, s_85, inverter_winding=True, offset_idx=len(v_out))
    topo_85 = qc_geom.topologia(v_out + v_in_85, t_out + t_in_85)
    assert topo_85["invertidas"] >= 1, f"Casca interna de 85% do volume deve reprovar como invertida: {topo_85}"

    # Cavidade interna verdadeira pequena (abs(vol_in)/vol_out = 0.10 < 0.70, conflito_w=False) -> invertidas == 0
    s_10 = 0.10 ** (1.0 / 3.0)
    v_in_10, t_in_10 = _caixa_fechada(s_10, s_10, s_10, inverter_winding=True, offset_idx=len(v_out))
    topo_10 = qc_geom.topologia(v_out + v_in_10, t_out + t_in_10)
    assert topo_10["invertidas"] == 0, f"Cavidade interna legitima (10%) nao deveria contar invertida: {topo_10}"
    assert topo_10["volume_total"] == pytest.approx(8.0 * 0.90, rel=1e-3)
    assert topo_10["aabb_fill"] == pytest.approx(0.90, rel=1e-3)


def test_qc_volumetria_g15b_ovo_solido_vs_panqueca_crescente_sem_costas_e_buraco_frontal() -> None:
    from forge3d import qc_volumetria

    item_base = {"id": "prop.ovo.01", "tipo": "prop_estatico", "rota": "i23d", "altura_metros": 1.0}

    v_ok, t_ok = _elipsoide_malha(0.40, 0.50, 0.38, modo="solido")
    _, gltf_ok, bin_ok = _glb_de_malha(v_ok, t_ok)
    res_ok = qc_volumetria.avaliar_volumetria_glb(gltf_ok, bin_ok, item_base, {})
    assert res_ok["aplicavel"] is True and res_ok["aprovado"] is True and res_ok["motivos"] == []

    v_pan, t_pan = _elipsoide_malha(0.50, 0.50, 0.015, modo="solido")
    _, gltf_pan, bin_pan = _glb_de_malha(v_pan, t_pan)
    res_pan = qc_volumetria.avaliar_volumetria_glb(gltf_pan, bin_pan, item_base, {})
    assert res_pan["aplicavel"] is True and res_pan["aprovado"] is False
    assert "colapso_profundidade_z" in res_pan["motivos"], res_pan

    v_cr, t_cr = _casca_crescente_fina_z(rx=0.50, ry=0.50, curvatura_z=0.385, espessura_z=0.015)
    _, gltf_cr, bin_cr = _glb_de_malha(v_cr, t_cr)
    res_cr = qc_volumetria.avaliar_volumetria_glb(gltf_cr, bin_cr, item_base, {})
    assert res_cr["aplicavel"] is True and res_cr["aprovado"] is False
    assert any(m in res_cr["motivos"] for m in ("casca_fina_colapsada", "cavidade_profunda_z", "volume_baixo_aabb")), res_cr

    v_sc, t_sc = _elipsoide_malha(0.40, 0.50, 0.38, modo="sem_costas")
    _, gltf_sc, bin_sc = _glb_de_malha(v_sc, t_sc)
    res_sc = qc_volumetria.avaliar_volumetria_glb(gltf_sc, bin_sc, item_base, {})
    assert res_sc["aplicavel"] is True and res_sc["aprovado"] is False
    assert "cavidade_ou_cobertura_traseira" in res_sc["motivos"], res_sc

    v_bf, t_bf = _elipsoide_malha(0.40, 0.50, 0.38, modo="buraco_frontal")
    _, gltf_bf, bin_bf = _glb_de_malha(v_bf, t_bf)
    res_bf = qc_volumetria.avaliar_volumetria_glb(gltf_bf, bin_bf, item_base, {})
    assert res_bf["aplicavel"] is True and res_bf["aprovado"] is False
    assert "buraco_cobertura_frontal" in res_bf["motivos"], res_bf


def test_qc_volumetria_g15b_cerca_fina_e_gazebo_aberto_passam_mas_casca_oca_reprova() -> None:
    from forge3d import qc_volumetria

    item_prop = {"id": "prop.cerca.01", "tipo": "prop_estatico", "rota": "import", "altura_metros": 1.0}

    # Cerca fina valida (dz_r = 0.11, solida fill ~ 1.0 > 0.15 e z_fill ~ 1.0) -> passa G15b
    v_cerca, t_cerca = _caixa_fechada(0.90, 0.50, 0.099, centro=(0.0, 0.50, 0.0))
    # Subdivide para >48 tris (nao acionar skip de stub curto)
    for idx_b in range(4):
        vb, tb = _caixa_fechada(0.08, 0.45, 0.095, centro=(-0.6 + idx_b * 0.4, 0.50, 0.0), offset_idx=len(v_cerca))
        v_cerca.extend(vb)
        t_cerca.extend(tb)
    _, gltf_cerca, bin_cerca = _glb_de_malha(v_cerca, t_cerca)
    res_cerca = qc_volumetria.avaliar_volumetria_glb(gltf_cerca, bin_cerca, item_prop, {})
    assert res_cerca["aplicavel"] is True and res_cerca["aprovado"] is True, res_cerca

    # Gazebo aberto com 4 pilares finos nos cantos + 2 vigas de teto (aabb_fill < 0.06, shell_solidity >= 0.11) -> passa G15b
    v_gaz: list[tuple[float, float, float]] = []
    t_gaz: list[tuple[int, int, int]] = []
    for sx in (-0.95, 0.95):
        for sz in (-0.95, 0.95):
            vp, tp = _caixa_fechada(0.05, 0.95, 0.05, centro=(sx, 0.95, sz), offset_idx=len(v_gaz))
            v_gaz.extend(vp)
            t_gaz.extend(tp)
    vt1, tt1 = _caixa_fechada(1.0, 0.04, 0.05, centro=(0.0, 1.90, -0.95), offset_idx=len(v_gaz))
    v_gaz.extend(vt1)
    t_gaz.extend(tt1)
    _, gltf_gaz, bin_gaz = _glb_de_malha(v_gaz, t_gaz)
    res_gaz = qc_volumetria.avaliar_volumetria_glb(gltf_gaz, bin_gaz, item_prop, {})
    assert res_gaz["aplicavel"] is True and res_gaz["aabb_fill"] < 0.06
    assert res_gaz["aprovado"] is True and res_gaz["shell_solidity"] >= 0.11, res_gaz

    # Ovo oco papel-fino de casca dupla fechada (aabb_fill < 0.06 e shell_solidity < 0.11) -> reprova G15b
    v_out, t_out = _elipsoide_malha(0.50, 0.50, 0.50, segments=16, rings=10, modo="solido")
    v_in, t_in = _elipsoide_malha(0.49, 0.49, 0.49, segments=16, rings=10, modo="solido")
    t_in_inv = [(a + len(v_out), c + len(v_out), b + len(v_out)) for a, b, c in t_in]
    v_ovo_oco = v_out + v_in
    t_ovo_oco = t_out + t_in_inv
    _, gltf_oco, bin_oco = _glb_de_malha(v_ovo_oco, t_ovo_oco)
    # Simula topo com cavidade perdoada/casca fina fechada onde g1 passa com aabb_fill=0.03
    info_oco = {"g1_medido": {"nao_manifold": 0, "aabb_fill": 0.03}}
    res_oco = qc_volumetria.avaliar_volumetria_glb(gltf_oco, bin_oco, item_prop, info_oco)
    assert res_oco["aplicavel"] is True and res_oco["aprovado"] is False
    assert "volume_baixo_aabb" in res_oco["motivos"], res_oco


def test_qc_volumetria_g15b_skips_extrude2d_alpha_cards_arma_mapa_setor_e_stub_curto() -> None:
    from forge3d import qc_volumetria

    v_pan, t_pan = _elipsoide_malha(0.50, 0.50, 0.015, modo="solido")
    _, gltf_pan, bin_pan = _glb_de_malha(v_pan, t_pan)
    for item_skip in (
        {"id": "p1", "tipo": "prop_estatico", "rota": "extrude_2d"},
        {"id": "p2", "tipo": "prop_estatico", "extrudir_2d": True},
        {"id": "p3", "tipo": "prop_estatico", "alpha_cards": True},
        {"id": "p4", "tipo": "equipamento", "parte": "arma"},
        {"id": "p5", "tipo": "mapa_setor"},
    ):
        res = qc_volumetria.avaliar_volumetria_glb(gltf_pan, bin_pan, item_skip, {})
        assert res["aplicavel"] is False and res["aprovado"] is True, (item_skip, res)

    gltf_stub, bin_stub = qc.ler_glb_bin(_glb_bytes())
    res_stub = qc_volumetria.avaliar_volumetria_glb(
        gltf_stub, bin_stub, {"id": "p.stub", "tipo": "prop_estatico", "rota": "i23d"}, {},
    )
    assert res_stub["aplicavel"] is False and res_stub["aprovado"] is True


def test_qc_verificar_g15_reprova_ovo_panqueca_mesmo_com_silhueta_2d_perfeita(tmp_path: Path) -> None:
    concept_png = tmp_path / "ovo_concept.png"
    im = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
    ImageDraw.Draw(im).ellipse([24, 14, 104, 114], fill=(215, 180, 120, 255))
    im.save(concept_png)

    v_pan, t_pan = _elipsoide_malha(0.40, 0.50, 0.015, cy=0.50, modo="solido")
    raw_pan, _, _ = _glb_de_malha(v_pan, t_pan)
    glb_path = tmp_path / "ovo_panqueca.glb"
    glb_path.write_bytes(raw_pan)

    item = {
        "id": "prop.ovo.panqueca", "tipo": "prop_estatico", "rota": "i23d", "altura_metros": 1.0,
        "pivot": "base", "limite_triangulos": 5000, "colisao": "none", "origem": str(concept_png),
    }
    resultado = {
        "medidas": {"nao_manifold": 0, "degeneradas": 0, "partes_colisao": 0},
        "arquivos": [
            {"caminho": glb_path.name, "papel": "mesh", "nivel": 0, "triangulos": len(t_pan)},
            {"caminho": concept_png.name, "papel": "concept"},
        ],
        "concept": {"caminho": concept_png.name},
        "licenca": {"modelo": "MIT", "uso_comercial": True, "notice": "teste"},
        "determinism": "D1",
    }
    rel = qc.verificar(item, profiles.carregar("godot4"), tmp_path, resultado)
    g15 = next(g for g in rel["gates"] if g["id"] == "G15")
    assert g15["status"] == "falhou", f"G15 deveria falhar por volumetria em ovo panqueca: {g15}"
    assert g15.get("codigo") == "FORGE-E-QC"
    assert g15["medido"]["volumetrico"]["aprovado"] is False
    assert "colapso_profundidade_z" in g15["medido"]["volumetrico"]["motivos"]
    assert rel["aprovado"] is False


def test_gap_054_limiares_g15_unificados_qc_fidelidade_e_visual_qa_fidelidade(tmp_path: Path) -> None:
    vqa_fid = _carregar_modulo_tools("visual_qa_fidelidade.py")
    assert qc_fidelidade.LIMIAR_IOU_G15 == pytest.approx(0.55)
    assert qc_fidelidade.LIMIAR_ASPECT_G15 == pytest.approx(0.60)
    assert vqa_fid.LIMIAR_IOU_G15 == pytest.approx(0.55)
    assert vqa_fid.LIMIAR_ASPECT_G15 == pytest.approx(0.60)

    p_concept, p_render = tmp_path / "concept_gap054.png", tmp_path / "render_gap054.png"
    im_c = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    ImageDraw.Draw(im_c).rectangle([50, 50, 150, 150], fill=(220, 80, 60, 255))
    im_c.save(p_concept)

    im_r = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    ImageDraw.Draw(im_r).rectangle([67, 50, 133, 150], fill=(60, 140, 220, 255))
    im_r.save(p_render)

    res_qc = qc_fidelidade.avaliar_fidelidade_concept_3d(p_concept, p_render)
    res_cli = vqa_fid.avaliar_fidelidade_concept_3d(p_concept, p_render)
    assert res_qc["aprovado"] is True and res_cli["aprovado"] is True
    assert res_qc["iou_silhueta"] == pytest.approx(res_cli["iou_silhueta"], abs=1e-4)
    assert res_qc["aspect_ratio_score"] == pytest.approx(res_cli["aspect_sim"], abs=1e-4)
