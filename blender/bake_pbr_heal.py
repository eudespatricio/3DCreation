"""Calculo de cage adaptativo e cura em 2 estagios de ray-misses em bakes PBR."""

from __future__ import annotations

import importlib
import os
import sys
from array import array
from typing import Any

try:
    import bmesh
    import bpy
    from mathutils.bvhtree import BVHTree
except ImportError:  # pragma: no cover - permite import puro em testes fora do Blender
    bmesh = None  # type: ignore[assignment]
    bpy = None  # type: ignore[assignment]
    BVHTree = None  # type: ignore[assignment,misc]

try:
    np = importlib.import_module("numpy")
except ImportError:  # pragma: no cover - fallback puro fora do Blender
    np = None  # type: ignore[assignment]

if __package__:
    from . import bake_pbr_config as _cfg
    from . import bake_pbr_maps as _maps
    from . import bake_pbr_nativo as _nat
else:
    _BLENDER_DIR = os.path.dirname(os.path.abspath(__file__))
    if _BLENDER_DIR not in sys.path:
        sys.path.insert(0, _BLENDER_DIR)
    import bake_pbr_config as _cfg
    import bake_pbr_maps as _maps
    import bake_pbr_nativo as _nat


def _percentil_ordenado(valores_ordenados: list[float], q: float) -> float:
    if not valores_ordenados:
        return 0.0
    idx = min(len(valores_ordenados) - 1, max(0, int(q * (len(valores_ordenados) - 1))))
    return float(valores_ordenados[idx])


def calcular_cage_adaptativo(
    low_obj, high_obj, diag: float, cage_base: float, max_ray_base: float,
    *, eh_organico: bool = False, max_amostras: int = 4096,
) -> tuple[float, float, dict]:
    """Calcula ``(cage, max_ray, stats)`` adaptando a jaula pela geometria High->Low via BVH."""
    vazio = (float(cage_base), float(max_ray_base), {"aplicado": False})
    if (
        bmesh is None or BVHTree is None or low_obj is None or high_obj is None
        or getattr(low_obj, "data", None) is None or getattr(high_obj, "data", None) is None
        or diag <= 1e-6 or max_amostras <= 0
    ):
        return vazio

    bm_high, bm_low = bmesh.new(), bmesh.new()
    try:
        bm_high.from_mesh(high_obj.data)
        bm_high.transform(high_obj.matrix_world)
        bm_high.normal_update()
        bm_low.from_mesh(low_obj.data)
        bm_low.transform(low_obj.matrix_world)
        bm_low.normal_update()
        if not bm_high.verts or not bm_high.faces or not bm_low.verts:
            return vazio

        bvh_high = BVHTree.FromBMesh(bm_high)
        bm_low.verts.ensure_lookup_table()
        bm_low.faces.ensure_lookup_table()
        verts, faces = list(bm_low.verts), list(bm_low.faces)
        amostras: list[tuple] = []
        if len(verts) + len(faces) <= max_amostras:
            amostras.extend((v.co, v.normal) for v in verts)
            amostras.extend((f.calc_center_median(), f.normal) for f in faces)
        else:
            lim_v = min(len(verts), max_amostras // 2)
            lim_f = min(len(faces), max_amostras - lim_v)
            if lim_v > 0:
                amostras.extend((v.co, v.normal) for v in verts[:: max(1, len(verts) // lim_v)][:lim_v])
            if lim_f > 0:
                amostras.extend((f.calc_center_median(), f.normal) for f in faces[:: max(1, len(faces) // lim_f)][:lim_f])

        outs: list[float] = []
        ins: list[float] = []
        abss: list[float] = []
        for p_low, n_raw in amostras:
            if n_raw.length <= 1e-8:
                continue
            p_high, _nh, _idx, _dist = bvh_high.find_nearest(p_low)
            if p_high is None:
                continue
            delta = p_high - p_low
            proj = float(delta.dot(n_raw.normalized()))
            outs.append(max(0.0, proj))
            ins.append(max(0.0, -proj))
            abss.append(float(delta.length))
    finally:
        bm_low.free()
        bm_high.free()

    if not outs:
        return vazio

    outs.sort()
    ins.sort()
    abss.sort()
    p98_out, p99_out = _percentil_ordenado(outs, 0.98), _percentil_ordenado(outs, 0.99)
    p98_in, p99_abs = _percentil_ordenado(ins, 0.98), _percentil_ordenado(abss, 0.99)
    if not eh_organico:
        piso, teto = max(float(cage_base), max(0.004, 0.006 * diag)), 0.045 * diag
    else:
        piso, teto = float(cage_base), 0.018 * diag

    cage = min(max(piso, p98_out * 1.15), max(piso, teto))
    max_ray = max(float(max_ray_base), 3.5 * cage, cage + p98_in * 1.35, cage + p99_abs * 1.25)
    return cage, max_ray, {
        "aplicado": True, "p98_out": round(p98_out, 6), "p99_out": round(p99_out, 6),
        "p98_in": round(p98_in, 6), "p99_abs": round(p99_abs, 6),
        "cage_base": round(float(cage_base), 6), "cage_adaptado": round(cage, 6),
        "max_ray_adaptado": round(max_ray, 6), "amostras": len(outs),
    }


def _restaurar_materiais_e_indices(obj, mats_ant: list, poly_mat_indices: list[int]) -> None:
    obj.data.materials.clear()
    for m_ant in mats_ant:
        obj.data.materials.append(m_ant)
    for poly, idx_mat in zip(obj.data.polygons, poly_mat_indices):
        poly.material_index = idx_mat


def assar_mascara_ilhas_uv(cena, obj, px: int, nome_base: str):
    """Assa mascara 1-sample ``EMIT (1,1,1)`` em UV0 (``R > 0.5`` indica cobertura de ilhas UV)."""
    if bpy is None or obj is None or getattr(obj, "data", None) is None or not obj.data.uv_layers:
        return None

    uv0_nome = str(obj.data.uv_layers[0].name)
    mats_ant = list(obj.data.materials)
    poly_mat_indices = [int(p.material_index) for p in obj.data.polygons]
    engine_ant = str(cena.render.engine)
    s2a_ant, clear_ant = bool(cena.render.bake.use_selected_to_active), bool(cena.render.bake.use_clear)
    margin_ant, samples_ant = int(cena.render.bake.margin), int(cena.cycles.samples)
    active_ant = bpy.context.view_layer.objects.active
    mat_mask = tex_mask = img_mask = None
    ok_mask = False
    try:
        if cena.render.engine != "CYCLES":
            _cfg._configurar_dispositivo_cycles(cena, preferir_gpu=True)
        mat_mask, tex_mask = _maps._criar_material_alvo_bake(f"{nome_base}_uv_mask_mat_tmp")
        nt = mat_mask.node_tree
        bsdf = nt.nodes.get("Principled BSDF")
        if bsdf is not None:
            nt.nodes.remove(bsdf)
        out = nt.nodes.get("Material Output") or nt.nodes.new("ShaderNodeOutputMaterial")
        emit = nt.nodes.new("ShaderNodeEmission")
        emit.inputs["Color"].default_value, emit.inputs["Strength"].default_value = (1.0, 1.0, 1.0, 1.0), 1.0
        nt.links.new(emit.outputs["Emission"], out.inputs["Surface"])

        img_mask = bpy.data.images.new(f"{nome_base}_uv_mask_tmp", width=px, height=px, alpha=False)
        img_mask.colorspace_settings.name = "Non-Color"
        tex_mask.image, tex_mask.select, nt.nodes.active = img_mask, True, tex_mask

        obj.data.materials.clear()
        obj.data.materials.append(mat_mask)
        obj.data.uv_layers.active = obj.data.uv_layers[uv0_nome]
        obj.data.uv_layers[uv0_nome].active_render = True
        cena.render.bake.use_selected_to_active, cena.render.bake.use_clear = False, True
        cena.render.bake.margin, cena.cycles.samples = 0, 1
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        _cfg._executar_bake_seguro(cena, type="EMIT")
        ok_mask = True
        return img_mask
    finally:
        if tex_mask is not None:
            tex_mask.image = None
        if not ok_mask and img_mask is not None and img_mask.name in bpy.data.images and img_mask.users == 0:
            bpy.data.images.remove(img_mask)
        _restaurar_materiais_e_indices(obj, mats_ant, poly_mat_indices)
        if mat_mask is not None and mat_mask.name in bpy.data.materials and mat_mask.users == 0:
            bpy.data.materials.remove(mat_mask)
        cena.render.bake.use_selected_to_active, cena.render.bake.use_clear = s2a_ant, clear_ant
        cena.render.bake.margin, cena.cycles.samples, cena.render.engine = margin_ant, samples_ant, engine_ant
        if active_ant is not None:
            bpy.context.view_layer.objects.active = active_ant


def _escrever_buf_saida(buf, dados):
    if isinstance(buf, array):
        if np is not None and isinstance(dados, np.ndarray) and buf.typecode == "f":
            out_arr = array("f")
            out_arr.frombytes(np.ascontiguousarray(dados, dtype=np.float32).tobytes())
            buf[:] = out_arr
            return buf
        flat = dados.ravel().tolist() if (np is not None and isinstance(dados, np.ndarray)) else dados
        buf[:] = array(buf.typecode, flat)
        return buf
    flat = dados.ravel().tolist() if (np is not None and isinstance(dados, np.ndarray)) else dados
    if isinstance(buf, list):
        buf[:] = flat
        return buf
    return flat


def _propagar_numpy(buf, valid_mask_bool, target_mask_bool, w: int, h: int, canais: int, fb: tuple[float, ...], max_iters: int) -> tuple[Any, int]:
    valid = np.asarray(valid_mask_bool, dtype=bool).reshape(h, w).copy()
    target = np.asarray(target_mask_bool, dtype=bool).reshape(h, w)
    if not np.any(target & ~valid):
        return buf, 0

    arr = np.asarray(buf, dtype=np.float32).reshape(h, w, canais).copy()
    orig_mean = arr[valid].mean(axis=0) if np.any(valid) else np.asarray(fb[:canais], dtype=np.float32)
    n_filled = 0
    for _ in range(max(1, int(max_iters))):
        pending = target & ~valid
        if not np.any(pending):
            break
        pad_v = np.pad(valid, 1, mode="constant", constant_values=False)
        pad_c = np.pad(arr, ((1, 1), (1, 1), (0, 0)), mode="constant", constant_values=0.0)
        sum_c = np.zeros((h, w, canais), dtype=np.float32)
        cnt = np.zeros((h, w), dtype=np.int32)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                m_nb = pad_v[1 + dy : 1 + dy + h, 1 + dx : 1 + dx + w]
                cnt += m_nb
                sum_c += pad_c[1 + dy : 1 + dy + h, 1 + dx : 1 + dx + w] * m_nb[:, :, None]
        fill_now = pending & (cnt > 0)
        if not np.any(fill_now):
            break
        arr[fill_now] = sum_c[fill_now] / cnt[fill_now, None].astype(np.float32)
        valid |= fill_now
        n_filled += int(np.count_nonzero(fill_now))

    still_pending = target & ~valid
    n_iso = int(np.count_nonzero(still_pending))
    if n_iso > 0:
        arr[still_pending] = orig_mean
        n_filled += n_iso
    if isinstance(buf, np.ndarray):
        buf[...] = arr.reshape(buf.shape).astype(buf.dtype, copy=False)
        return buf, n_filled
    return _escrever_buf_saida(buf, arr), n_filled


def _vizinhos_8(p: int, w: int, h: int) -> list[int]:
    x, y = p % w, p // w
    return [
        ny * w + nx
        for dy in (-1, 0, 1) if 0 <= (ny := y + dy) < h
        for dx in (-1, 0, 1) if (dx != 0 or dy != 0) and 0 <= (nx := x + dx) < w
    ]


def propagar_texels_validos_buf(
    buf, valid_mask_bool, target_mask_bool, w: int, h: int,
    *, canais: int = 4, fallback_rgba: tuple[float, ...] | list[float] | None = None, max_iters: int = 64,
) -> tuple[Any, int]:
    """Dilatacao Voronoi 8-vizinhos iterativa para preencher ``target_mask_bool & ~valid_mask_bool``."""
    fb_base = tuple(float(v) for v in fallback_rgba) if fallback_rgba is not None else (0.5, 0.5, 0.5, 1.0)
    if len(fb_base) < canais:
        fb_base = fb_base + (1.0,) * (canais - len(fb_base))
    if np is not None:
        return _propagar_numpy(buf, valid_mask_bool, target_mask_bool, w, h, canais, fb_base, max_iters)

    n_px = w * h
    valid, target = [bool(v) for v in valid_mask_bool], [bool(t) for t in target_mask_bool]
    pending_set = {p for p in range(n_px) if target[p] and not valid[p]}
    if not pending_set:
        return buf, 0

    somas, orig_cnt = [0.0] * canais, 0
    for p in range(n_px):
        if valid[p]:
            off = p * canais
            for c in range(canais):
                somas[c] += float(buf[off + c])
            orig_cnt += 1
    orig_mean = tuple(s / float(orig_cnt) for s in somas) if orig_cnt > 0 else fb_base[:canais]

    frontier = {p for p in pending_set if any(valid[nb] for nb in _vizinhos_8(p, w, h))}
    n_filled = 0
    for _ in range(max(1, int(max_iters))):
        if not frontier:
            break
        updates: list[tuple[int, tuple[float, ...]]] = []
        next_frontier: set[int] = set()
        for p in frontier:
            acc, cnt = [0.0] * canais, 0
            for nb in _vizinhos_8(p, w, h):
                if valid[nb]:
                    nb_off = nb * canais
                    for c in range(canais):
                        acc[c] += float(buf[nb_off + c])
                    cnt += 1
                elif nb in pending_set:
                    next_frontier.add(nb)
            if cnt > 0:
                inv = 1.0 / float(cnt)
                updates.append((p, tuple(a * inv for a in acc)))
        if not updates:
            break
        for p, vals in updates:
            off = p * canais
            for c in range(canais):
                buf[off + c] = vals[c]
            valid[p] = True
            pending_set.discard(p)
        n_filled += len(updates)
        frontier = {q for q in next_frontier if q in pending_set}

    for p in pending_set:
        off = p * canais
        for c in range(canais):
            buf[off + c] = orig_mean[c]
        n_filled += 1
    return buf, n_filled


def _ler_buf_imagem(img, w: int, h: int) -> array:
    buf = array("f", [0.0]) * (w * h * 4)
    img.pixels.foreach_get(buf)
    return buf


def _upsample_indices(px_dst: int, px_src: int) -> tuple[list[int], list[int]]:
    return [min(px_src - 1, (y * px_src) // px_dst) for y in range(px_dst)], [min(px_src - 1, (x * px_src) // px_dst) for x in range(px_dst)]


def _aplicar_patch_buf(dst_buf, src_buf, mask_sub: list[bool], px_dst: int, px_src: int, *, set_b_um: bool = False) -> bool:
    mudou = False
    ys, xs = (range(px_dst), range(px_dst)) if px_dst == px_src else _upsample_indices(px_dst, px_src)
    for by, sy in enumerate(ys):
        row_d, row_s = by * px_dst, sy * px_src
        for bx, sx in enumerate(xs):
            sp = row_s + sx
            if not mask_sub[sp]:
                continue
            doff, soff = (row_d + bx) * 4, sp * 4
            dst_buf[doff], dst_buf[doff + 1], dst_buf[doff + 3] = src_buf[soff], src_buf[soff + 1], src_buf[soff + 3]
            dst_buf[doff + 2] = 1.0 if set_b_um else src_buf[soff + 2]
            mudou = True
    return mudou


def curar_ray_misses_pbr(
    cena, obj, high_obj, high_mats_nativos, low_bake_mat, tex_bake,
    img_bc, path_bc: str, img_nm, path_nm: str, img_ao_tmp, img_hints_tmp,
    px: int, px_sub: int, diag: float, cage_atual: float, max_ray_atual: float,
    stats_cage: dict | None, samples_bake: int, samples_ao: int, margem_bc: int, margem_sub: int,
) -> tuple[Any, Any, dict]:
    """Cura ray-misses de PBR nativo em 2 estagios: retry com cage amplo + dilatacao Voronoi."""
    if bpy is None or obj is None or high_obj is None or img_bc is None or img_hints_tmp is None:
        return img_bc, img_nm, {"aplicado": False, "motivo": "precondicao_ausente"}

    mats_ant = list(obj.data.materials)
    poly_mat_indices = [int(p.material_index) for p in obj.data.polygons]
    cage_ext_ant, max_ray_ant = float(cena.render.bake.cage_extrusion), float(cena.render.bake.max_ray_distance)
    s2a_ant, clear_ant = bool(cena.render.bake.use_selected_to_active), bool(cena.render.bake.use_clear)
    margin_ant, samples_ant = int(cena.render.bake.margin), int(cena.cycles.samples)
    active_ant = bpy.context.view_layer.objects.active
    estado_cena = _cfg._capturar_estado_cena(cena)

    img_uv_sub = img_uv_bc = hints2 = bc2 = nm2 = ao2 = None
    try:
        img_uv_sub = assar_mascara_ilhas_uv(cena, obj, px_sub, f"{obj.name}_sub")
        if img_uv_sub is None:
            return img_bc, img_nm, {"aplicado": False, "motivo": "sem_uv"}

        uv_sub_buf, hints_buf = _ler_buf_imagem(img_uv_sub, px_sub, px_sub), _ler_buf_imagem(img_hints_tmp, px_sub, px_sub)
        uv_mask_sub = [uv_sub_buf[i] > 0.5 for i in range(0, px_sub * px_sub * 4, 4)]
        uv_count_sub = sum(1 for m in uv_mask_sub if m)
        if uv_count_sub == 0:
            return img_bc, img_nm, {"aplicado": False, "motivo": "uv_vazia"}

        miss_mask = [uv_mask_sub[p] and hints_buf[p * 4 + 2] < 0.5 for p in range(px_sub * px_sub)]
        n_miss_ini = sum(1 for m in miss_mask if m)
        miss_frac_ini = n_miss_ini / float(uv_count_sub)
        if n_miss_ini == 0:
            return img_bc, img_nm, {
                "aplicado": False, "miss_frac_inicial": 0.0, "miss_pixels_inicial": 0, "retry_cage_executado": False,
                "pixels_recuperados_retry": 0, "pixels_curados_bc": 0, "pixels_curados_sub": 0, "miss_frac_final": 0.0,
            }

        bc_buf = _ler_buf_imagem(img_bc, px, px)
        nm_buf = _ler_buf_imagem(img_nm, px_sub, px_sub) if img_nm is not None else None
        ao_buf = _ler_buf_imagem(img_ao_tmp, px_sub, px_sub) if img_ao_tmp is not None else None
        bc_changed = nm_changed = ao_changed = hints_changed = False

        retry_exec, n_recup, cage2, max_ray2 = False, 0, cage_atual, max_ray_atual
        if miss_frac_ini > 0.005 and high_mats_nativos and low_bake_mat is not None and tex_bake is not None:
            retry_exec, sc = True, (stats_cage or {})
            cage2 = min(0.08 * diag, max(cage_atual * 2.5, float(sc.get("p99_out", 0.0)) * 1.40, 0.015 * diag))
            max_ray2 = max(cage2 * 4.0, float(sc.get("p99_abs", 0.0)) * 2.0, max_ray_atual * 2.0)
            _cfg._configurar_render_png_linear(cena)
            obj.data.materials.clear()
            obj.data.materials.append(low_bake_mat)
            cena.render.bake.use_selected_to_active, cena.render.bake.use_cage = True, True
            cena.render.bake.cage_object, cena.render.bake.use_clear = None, True
            cena.render.bake.cage_extrusion, cena.render.bake.max_ray_distance = cage2, max_ray2

            def _assar_r2(sufixo: str, cs: str, samples: int, margem: int, btype: str, tok_fn=None):
                im = bpy.data.images.new(f"{obj.name}_{sufixo}_r2_tmp", width=px_sub, height=px_sub, alpha=False)
                im.colorspace_settings.name = cs
                tex_bake.image, tex_bake.select, low_bake_mat.node_tree.nodes.active = im, True, tex_bake
                cena.cycles.samples, cena.render.bake.margin = samples, margem
                _cfg._selecionar_high_para_low(high_obj, obj)
                toks = tok_fn(high_mats_nativos) if tok_fn is not None else []
                try:
                    _cfg._executar_bake_seguro(cena, type=btype)
                finally:
                    if toks:
                        _nat.restaurar_saidas_nativos(toks)
                return im

            hints2 = _assar_r2("hints2", "Non-Color", samples_bake, margem_sub, "EMIT", _nat.configurar_saida_orm_emit_nativos)
            h2_buf = _ler_buf_imagem(hints2, px_sub, px_sub)
            recup_sub = [miss_mask[p] and h2_buf[p * 4 + 2] >= 0.5 for p in range(px_sub * px_sub)]
            n_recup = sum(1 for r in recup_sub if r)
            if n_recup > 0:
                hints_changed |= _aplicar_patch_buf(hints_buf, h2_buf, recup_sub, px_sub, px_sub, set_b_um=True)
                bc2 = _assar_r2("bc2", "sRGB", samples_bake, margem_sub, "EMIT", _nat.configurar_saida_basecolor_emit_nativos)
                bc_changed |= _aplicar_patch_buf(bc_buf, _ler_buf_imagem(bc2, px_sub, px_sub), recup_sub, px, px_sub)
                if nm_buf is not None:
                    nm2 = _assar_r2("nm2", "Non-Color", samples_bake, margem_sub, "NORMAL")
                    _maps._corrigir_normais_invertidas(nm2, px_sub)
                    nm_changed |= _aplicar_patch_buf(nm_buf, _ler_buf_imagem(nm2, px_sub, px_sub), recup_sub, px_sub, px_sub)
                if ao_buf is not None:
                    ao2 = _assar_r2("ao2", "Non-Color", samples_ao, margem_sub, "AO")
                    ao_changed |= _aplicar_patch_buf(ao_buf, _ler_buf_imagem(ao2, px_sub, px_sub), recup_sub, px_sub, px_sub)

        valid_sub_now = [uv_mask_sub[p] and hints_buf[p * 4 + 2] >= 0.5 for p in range(px_sub * px_sub)]
        still_miss_sub = [uv_mask_sub[p] and not valid_sub_now[p] for p in range(px_sub * px_sub)]
        if px == px_sub:
            uv_mask_bc, valid_bc = uv_mask_sub, valid_sub_now
        else:
            img_uv_bc = assar_mascara_ilhas_uv(cena, obj, px, f"{obj.name}_bc")
            uv_bc_buf = _ler_buf_imagem(img_uv_bc, px, px)
            uv_mask_bc = [uv_bc_buf[i] > 0.5 for i in range(0, px * px * 4, 4)]
            ys, xs = _upsample_indices(px, px_sub)
            valid_bc = [uv_mask_bc[by * px + bx] and valid_sub_now[sy * px_sub + sx] for by, sy in enumerate(ys) for bx, sx in enumerate(xs)]

        bc_buf, n_cur_bc = propagar_texels_validos_buf(bc_buf, valid_bc, uv_mask_bc, px, px, canais=4, fallback_rgba=None)
        bc_changed |= n_cur_bc > 0

        n_cur_ao = n_cur_nm = n_cur_hints = 0
        if any(still_miss_sub):
            if ao_buf is not None:
                ao_buf, n_cur_ao = propagar_texels_validos_buf(ao_buf, valid_sub_now, uv_mask_sub, px_sub, px_sub, canais=4, fallback_rgba=(0.78, 0.78, 0.78, 1.0))
                ao_changed |= n_cur_ao > 0
            if nm_buf is not None:
                nm_buf, n_cur_nm = propagar_texels_validos_buf(nm_buf, valid_sub_now, uv_mask_sub, px_sub, px_sub, canais=4, fallback_rgba=(0.5, 0.5, 1.0, 1.0))
                nm_changed |= n_cur_nm > 0
            hints_buf, n_cur_hints = propagar_texels_validos_buf(hints_buf, valid_sub_now, uv_mask_sub, px_sub, px_sub, canais=4, fallback_rgba=(0.0, 0.78, 1.0, 1.0))
            for p, miss in enumerate(still_miss_sub):
                if miss:
                    hints_buf[p * 4 + 2] = 1.0
            hints_changed |= n_cur_hints > 0

        if hints_changed:
            img_hints_tmp.pixels.foreach_set(hints_buf)
        if ao_changed and img_ao_tmp is not None:
            img_ao_tmp.pixels.foreach_set(ao_buf)
        if nm_changed and img_nm is not None:
            img_nm.pixels.foreach_set(nm_buf)
            _cfg._configurar_render_png_linear(cena)
            img_nm = _maps._salvar_e_recarregar_png(img_nm, path_nm, "Non-Color", cena)
        if bc_changed:
            img_bc.pixels.foreach_set(bc_buf)
            _cfg._configurar_render_png_linear(cena)
            img_bc = _maps._salvar_e_recarregar_png(img_bc, path_bc, "sRGB", cena)

        miss_fin = sum(1 for p in range(px_sub * px_sub) if uv_mask_sub[p] and hints_buf[p * 4 + 2] < 0.5)
        info_heal = {
            "aplicado": bool(n_recup > 0 or n_cur_bc > 0 or n_cur_ao > 0 or n_cur_nm > 0 or n_cur_hints > 0),
            "miss_frac_inicial": round(miss_frac_ini, 6), "miss_pixels_inicial": int(n_miss_ini),
            "retry_cage_executado": retry_exec, "pixels_recuperados_retry": int(n_recup),
            "pixels_curados_bc": int(n_cur_bc), "pixels_curados_sub": int(max(n_cur_hints, n_cur_ao, n_cur_nm)),
            "miss_frac_final": round(miss_fin / float(uv_count_sub), 6),
        }
        if retry_exec:
            info_heal["cage2"], info_heal["max_ray2"] = round(cage2, 6), round(max_ray2, 6)
        return img_bc, img_nm, info_heal
    finally:
        if tex_bake is not None:
            tex_bake.image = None
        _restaurar_materiais_e_indices(obj, mats_ant, poly_mat_indices)
        for im_tmp in (img_uv_sub, img_uv_bc, hints2, bc2, nm2, ao2):
            if im_tmp is not None and im_tmp.name in bpy.data.images and im_tmp.users == 0:
                bpy.data.images.remove(im_tmp)
        cena.render.bake.cage_extrusion, cena.render.bake.max_ray_distance = cage_ext_ant, max_ray_ant
        cena.render.bake.use_selected_to_active, cena.render.bake.use_clear = s2a_ant, clear_ant
        cena.render.bake.margin, cena.cycles.samples = margin_ant, samples_ant
        _cfg._restaurar_estado_cena(cena, estado_cena)
        if active_ant is not None:
            bpy.context.view_layer.objects.active = active_ant
