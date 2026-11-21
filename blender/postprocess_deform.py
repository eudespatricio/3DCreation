"""Medicao de esticamento de malha sob animacao no Blender (B2 / Gate G16)."""

from __future__ import annotations

import math
from typing import Any

import bpy


def _resolver_acao(nome: str, rig_name: str):
    acoes = bpy.data.actions
    for cand in (f"{nome}_{rig_name}", f"{nome}_Armature", nome):
        if (acao := acoes.get(cand)) is not None:
            return acao
    return next((a for a in acoes if a.name.startswith(f"{nome}_")), None)


def _resumir_ratios(ratios: list[float]) -> dict[str, Any]:
    if not ratios:
        return {"max_stretch": 1.0, "p99_stretch": 1.0, "arestas_gt_15": 0, "arestas_gt_20": 0, "arestas_gt_30": 0, "frac_gt_20": 0.0, "frac_gt_30": 0.0}
    ord_r = sorted(ratios)
    p99_idx = min(len(ord_r) - 1, int(0.99 * (len(ord_r) - 1)))
    gt15 = sum(1 for r in ratios if r > 1.5)
    gt20 = sum(1 for r in ratios if r > 2.0)
    gt30 = sum(1 for r in ratios if r > 3.0)
    n = float(len(ratios))
    return {
        "max_stretch": round(float(ord_r[-1]), 4),
        "p99_stretch": round(float(ord_r[p99_idx]), 4),
        "arestas_gt_15": gt15,
        "arestas_gt_20": gt20,
        "arestas_gt_30": gt30,
        "frac_gt_20": round(gt20 / n, 6),
        "frac_gt_30": round(gt30 / n, 6),
    }


_CHAVES_PICO = ("max_stretch", "p99_stretch", "arestas_gt_15", "arestas_gt_20", "arestas_gt_30", "frac_gt_20", "frac_gt_30")


def _agregar_pico_clipes(clipes_res: list[dict[str, Any]]) -> dict[str, Any]:
    if not clipes_res:
        return {**_resumir_ratios([]), "clipe_pico": ""}
    clipe_pico = max(clipes_res, key=lambda c: float(c.get("max_stretch", 1.0)))["nome"]
    return {**{k: max(c[k] for c in clipes_res) for k in _CHAVES_PICO}, "clipe_pico": clipe_pico}


def _amostrar_malha(obj, deps, com_arestas: bool = False):
    eval_obj = obj.evaluated_get(deps)
    me = eval_obj.to_mesh()
    try:
        co = [(float(v.co.x), float(v.co.y), float(v.co.z)) for v in me.vertices]
        if not com_arestas:
            return co, []
        zs = [p[2] for p in co]
        min_len = max(0.005 * max((max(zs) - min(zs)) if zs else 0.0, 1e-4), 1e-5)
        arestas: list[tuple[int, int, float]] = []
        for e in me.edges:
            i, j = e.vertices[0], e.vertices[1]
            if i != j and i < len(co) and j < len(co):
                comp = math.dist(co[i], co[j])
                if comp >= min_len:
                    arestas.append((i, j, comp))
        return co, arestas
    finally:
        eval_obj.to_mesh_clear()


def medir_deformacao_animacao(
    obj,
    rig_obj,
    animacoes_geradas: list[dict] | list[str] | None,
) -> dict[str, Any] | None:
    """Mede esticamento de arestas em 9 frames por clipe restaurando cena/pose no finally."""
    if obj is None or getattr(obj, "type", None) != "MESH" or rig_obj is None:
        return None
    arm_mods = [m for m in obj.modifiers if m.type == "ARMATURE"]
    if not arm_mods or not bpy.data.actions or not animacoes_geradas or getattr(rig_obj, "animation_data", None) is None:
        return None

    cena = bpy.context.scene
    frame_orig = cena.frame_current
    orig_action = rig_obj.animation_data.action
    orig_vp = [(m, m.show_viewport, m.use_deform_preserve_volume) for m in arm_mods]
    orig_poses = {
        pb.name: (pb.location.copy(), pb.rotation_quaternion.copy(), pb.rotation_euler.copy(), pb.scale.copy())
        for pb in rig_obj.pose.bones
    }
    deps = bpy.context.evaluated_depsgraph_get()

    try:
        for mod in arm_mods:
            mod.show_viewport = False
        deps.update()
        rest_co, edges_validas = _amostrar_malha(obj, deps, com_arestas=True)
        if not edges_validas:
            return None
        for mod in arm_mods:
            mod.show_viewport = True
            mod.use_deform_preserve_volume = False

        clipes_res: list[dict[str, Any]] = []

        for item_anim in animacoes_geradas:
            nome = str(item_anim["nome"] if isinstance(item_anim, dict) else item_anim)
            acao = _resolver_acao(nome, rig_obj.name)
            if acao is None:
                continue
            f0, f1 = (
                (int(round(acao.frame_range[0])), int(round(acao.frame_range[1])))
                if acao.fcurves
                else (1, max(2, int(item_anim.get("frames") or 24) if isinstance(item_anim, dict) else 24))
            )
            frames = list(dict.fromkeys(f0 + int(round((f1 - f0) * k / 8.0)) for k in range(9)))
            rig_obj.animation_data.action = acao
            clip_max_e = [1.0] * len(edges_validas)
            clip_pico, frame_pico = 1.0, frames[0]

            for fr in frames:
                cena.frame_set(fr)
                deps.update()
                ev, _ = _amostrar_malha(obj, deps)
                if len(ev) != len(rest_co):
                    continue
                for idx, (i, j, rest_len) in enumerate(edges_validas):
                    ratio = math.dist(ev[i], ev[j]) / rest_len
                    if ratio > clip_max_e[idx]:
                        clip_max_e[idx] = ratio
                    if ratio > clip_pico:
                        clip_pico, frame_pico = ratio, fr

            res_clip = _resumir_ratios(clip_max_e)
            clipes_res.append({"nome": nome, "frame_pico": frame_pico, **res_clip})

        if not clipes_res:
            return None
        return {
            "fonte": "blender",
            **_agregar_pico_clipes(clipes_res),
            "arestas_avaliadas": len(edges_validas),
            "clipes": clipes_res,
        }
    finally:
        rig_obj.animation_data.action = orig_action
        for pb in rig_obj.pose.bones:
            if pb.name in orig_poses:
                pb.location, pb.rotation_quaternion, pb.rotation_euler, pb.scale = orig_poses[pb.name]
        for mod, vp, pv in orig_vp:
            mod.show_viewport = vp
            mod.use_deform_preserve_volume = pv
        cena.frame_set(frame_orig)
        bpy.context.evaluated_depsgraph_get().update()
