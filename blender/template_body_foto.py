"""Projecao de foto frontal 2D, auto-ajuste de silhueta (IoU) e bake em Cycles."""

from __future__ import annotations

import math
import os
import sys

import bpy
from mathutils import Matrix, Vector

if __package__:
    from . import template_body_assets as _assets
else:
    _BLENDER_DIR = os.path.dirname(os.path.abspath(__file__))
    if _BLENDER_DIR not in sys.path:
        sys.path.insert(0, _BLENDER_DIR)
    import template_body_assets as _assets

GRADE = _assets.GRADE
_OSSOS_BRACO = _assets._OSSOS_BRACO
_OSSOS_BRACO_DISTAL = _assets._OSSOS_BRACO_DISTAL
_OSSOS_TRONCO = _assets._OSSOS_TRONCO
_rgba_srgb_to_linear = _assets._rgba_srgb_to_linear


def _apontar(rig, nome: str, d: Vector) -> None:
    pb = rig.pose.bones[nome]
    bpy.context.view_layer.update()
    mw = rig.matrix_world
    q = ((mw @ pb.tail) - (mw @ pb.head)).normalized().rotation_difference(d.normalized())
    m = pb.matrix.copy()
    novo = q.to_matrix().to_4x4() @ Matrix(m.to_3x3()).to_4x4()
    novo.translation = m.to_translation()
    pb.matrix = novo
    bpy.context.view_layer.update()


def posar(rig, upper: float, lower: float, perna: float) -> None:
    for pb in rig.pose.bones:
        pb.matrix_basis = Matrix.Identity(4)
    au, al, ap = math.radians(upper), math.radians(lower), math.radians(perna)
    for lado, sx in (("l", 1.0), ("r", -1.0)):
        _apontar(rig, f"upperarm_{lado}", Vector((sx * math.sin(au), 0.0, -math.cos(au))))
        dl = Vector((sx * math.sin(al), 0.0, -math.cos(al)))
        for b in ("lowerarm", "hand"):
            _apontar(rig, f"{b}_{lado}", dl)
        dp = Vector((sx * math.sin(ap), 0.0, -math.cos(ap)))
        for b in ("thigh", "calf"):
            _apontar(rig, f"{b}_{lado}", dp)


def coords_posadas(obj):
    dg = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    me = ev.to_mesh()
    mw = obj.matrix_world
    pts = [mw @ v.co for v in me.vertices]
    nrm = [(mw.to_3x3() @ v.normal).normalized() for v in me.vertices]
    ev.to_mesh_clear()
    return pts, nrm


class Foto:
    def __init__(self, caminho: str):
        self.img = bpy.data.images.load(caminho)
        self.img.alpha_mode = "CHANNEL_PACKED"
        self.w, self.h = self.img.size
        self.px = list(self.img.pixels)
        ys, xs = [], []
        for y in range(0, self.h, 2):
            for x in range(0, self.w, 2):
                if self.px[(y * self.w + x) * 4 + 3] > 0.5:
                    ys.append(y)
                    xs.append(x)
        if not ys:
            raise SystemExit("foto sem alfa: rode o recorte antes")
        self.y0, self.y1, self.x0, self.x1 = min(ys), max(ys), min(xs), max(xs)
        self.grade = set()
        for y in range(0, self.h, GRADE):
            for x in range(0, self.w, GRADE):
                if self.px[(y * self.w + x) * 4 + 3] > 0.5:
                    self.grade.add((x // GRADE, y // GRADE))

    def amostra(self, x: float, y: float):
        xi = min(self.w - 1, max(0, int(x)))
        yi = min(self.h - 1, max(0, int(y)))
        i = (yi * self.w + xi) * 4
        return tuple(self.px[i : i + 4])


def _limites_xy(pts):
    zmin = min(p.z for p in pts)
    zmax = max(p.z for p in pts)
    xs = [p.x for p in pts]
    xc = (min(xs) + max(xs)) / 2.0
    return zmin, zmax, xc


def iou(pts, foto: Foto) -> float:
    zmin, zmax, xc = _limites_xy(pts)
    s = (foto.y1 - foto.y0) / max(1e-5, zmax - zmin)
    cx = (foto.x0 + foto.x1) / 2.0
    cel = set()
    for p in pts[::2]:
        x = cx + (p.x - xc) * s
        y = foto.y0 + (p.z - zmin) * s
        gx, gy = int(x) // GRADE, int(y) // GRADE
        cel.update(((gx, gy), (gx + 1, gy), (gx, gy + 1), (gx - 1, gy), (gx, gy - 1)))
    inter = len(cel & foto.grade)
    return inter / max(1, len(cel | foto.grade))


def auto_ajuste(obj, rig, foto: Foto, upper: float, lower: float, perna: float):
    melhor = (-1.0, upper, lower, perna)
    for u in (upper - 4, upper - 1.5, upper, upper + 2.5, upper + 5):
        for lo in (lower - 3, lower, lower + 3):
            for pe in (perna - 2, perna, perna + 2):
                posar(rig, u, lo, pe)
                v = iou(coords_posadas(obj)[0], foto)
                if v > melhor[0]:
                    melhor = (v, u, lo, pe)
    _, u0, l0, p0 = melhor
    for du in (-1.0, 0.0, 1.0):
        for dl in (-1.5, 0.0, 1.5):
            posar(rig, u0 + du, l0 + dl, p0)
            v = iou(coords_posadas(obj)[0], foto)
            if v > melhor[0]:
                melhor = (v, u0 + du, l0 + dl, p0)
    posar(rig, melhor[1], melhor[2], melhor[3])
    return melhor


def _mapear_t_z(t: float, ancoras_src: list[float], ancoras_dst: list[float]) -> float:
    if t <= ancoras_src[0]:
        return ancoras_dst[0]
    for k in range(len(ancoras_src) - 1):
        s0, s1 = ancoras_src[k], ancoras_src[k + 1]
        d0, d1 = ancoras_dst[k], ancoras_dst[k + 1]
        if t <= s1 and s1 > s0:
            return d0 + (d1 - d0) * ((t - s0) / (s1 - s0))
    return ancoras_dst[-1]


def _peso_grupo(v, grupo_ids: set[int]) -> float:
    return sum(g.weight for g in v.groups if g.group in grupo_ids)


def _centro_z_grupo(me, pts, grupo_ids: set[int]) -> float | None:
    zs = [pts[v.index].z for v in me.vertices if _peso_grupo(v, grupo_ids) > 0.35]
    return sum(zs) / len(zs) if zs else None


def projetar_e_assar(obj, foto: Foto, saida: str, tam: int, marcos: dict | None = None) -> tuple[str, dict]:
    me = obj.data
    pts, nrm = coords_posadas(obj)
    zmin, zmax, xc = _limites_xy(pts)
    h_tot = max(1e-5, zmax - zmin)
    s = (foto.y1 - foto.y0) / h_tot
    cx_foto = (foto.x0 + foto.x1) / 2.0

    vg = {g.name: g.index for g in obj.vertex_groups}
    ids_cab = {vg.get("head"), vg.get("neck_01")} - {None}
    ids_olhos = {vg.get("helper-l-eye"), vg.get("helper-r-eye")} - {None}
    ids_boca = {vg.get("lips")} - {None}
    ids_bracos_distais = {vg[n] for n in _OSSOS_BRACO_DISTAL if n in vg}
    ids_bracos = {vg[n] for n in _OSSOS_BRACO if n in vg}
    ids_tronco = {vg[n] for n in _OSSOS_TRONCO if n in vg}

    eye_z = _centro_z_grupo(me, pts, ids_olhos)
    mouth_z = _centro_z_grupo(me, pts, ids_boca)
    anc_src = [0.0, 1.0]
    anc_dst = [0.0, 1.0]
    if marcos and eye_z and mouth_z:
        ef, bf = float(marcos.get("olhos_frac", 0)), float(marcos.get("boca_frac", 0))
        et, bt = (eye_z - zmin) / h_tot, (mouth_z - zmin) / h_tot
        if 0.70 < bt < et < 0.98 and 0.70 < bf < ef < 0.98:
            anc_src = [0.0, bt, et, 1.0]
            anc_dst = [0.0, bf, ef, 1.0]

    fatias = 32
    tronco_min_x = [0.0] * fatias
    tronco_max_x = [0.0] * fatias
    tem_fatia = [False] * fatias
    for v in me.vertices:
        if _peso_grupo(v, ids_tronco) > 0.45 and _peso_grupo(v, ids_bracos) < 0.2:
            p = pts[v.index]
            k = min(fatias - 1, max(0, int((p.z - zmin) / h_tot * fatias)))
            if not tem_fatia[k]:
                tronco_min_x[k] = tronco_max_x[k] = p.x
                tem_fatia[k] = True
            else:
                tronco_min_x[k] = min(tronco_min_x[k], p.x)
                tronco_max_x[k] = max(tronco_max_x[k], p.x)

    # Amostra tom medio quente natural de pele (rosto/pescoco/abdome/pernas) e converte sRGB -> Linear.
    h_px = foto.y1 - foto.y0
    eye_y_px = foto.y0 + (anc_dst[2] if len(anc_dst) > 2 else 0.93) * h_px

    def _parece_pele(px_val) -> bool:
        return (
            px_val[3] > 0.85
            and px_val[0] > px_val[1] > px_val[2]
            and (px_val[0] - px_val[2]) >= 0.08
            and 0.30 <= px_val[0] <= 0.88
        )

    amostras_cabeca = []
    for dx in (-12, -8, 8, 12):
        for dy in (-22, -18, -14):
            px_c = foto.amostra(cx_foto + dx, eye_y_px + dy)
            if _parece_pele(px_c):
                amostras_cabeca.append(px_c)
    for frac_y in (0.79, 0.82):
        for dx in (-8, 0, 8):
            px_c = foto.amostra(cx_foto + dx, foto.y0 + frac_y * h_px)
            if _parece_pele(px_c):
                amostras_cabeca.append(px_c)

    amostras_corpo = list(amostras_cabeca)
    for frac_y in (0.58, 0.62, 0.30, 0.36):
        xs_cand = (-14, -6, 6, 14) if frac_y > 0.50 else (-28, -20, 20, 28)
        for dx in xs_cand:
            px_c = foto.amostra(cx_foto + dx, foto.y0 + frac_y * h_px)
            if _parece_pele(px_c):
                amostras_corpo.append(px_c)

    if amostras_corpo:
        amostras_corpo.sort(key=lambda c: 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2])
        # Percentil 40 evita picos de flash/brilho estourado na bochecha mantendo tom quente natural
        pele_srgb = amostras_corpo[int(len(amostras_corpo) * 0.40)]
    elif amostras_cabeca:
        amostras_cabeca.sort(key=lambda c: c[0])
        pele_srgb = amostras_cabeca[len(amostras_cabeca) // 2]
    else:
        pele_srgb = foto.amostra(cx_foto, foto.y1 - 0.05 * h_px)

    pele_cranio = _rgba_srgb_to_linear(pele_srgb)
    pele_braco = pele_cranio

    uv_orig = me.uv_layers[0].name
    uvp = me.uv_layers.new(name="proj")
    uvl = me.uv_layers.new(name="proj_limpo")
    attr_frente = me.color_attributes.new("frente", "FLOAT_COLOR", "POINT")
    attr_pele = me.color_attributes.new("usa_pele", "FLOAT_COLOR", "POINT")
    attr_cor_pele = me.color_attributes.new("pele_local", "FLOAT_COLOR", "POINT")

    for v in me.vertices:
        i = v.index
        p = pts[i]
        t_raw = (p.z - zmin) / h_tot
        t_warp = _mapear_t_z(t_raw, anc_src, anc_dst)
        yy = foto.y0 + t_warp * h_px
        xx = cx_foto + (p.x - xc) * s
        px_proj = foto.amostra(xx, yy)
        proj_pele_limpa = (
            px_proj[3] > 0.78
            and px_proj[0] > px_proj[1] > px_proj[2]
            and (px_proj[0] - px_proj[2]) >= 0.06
            and 0.30 <= px_proj[0] <= 0.86
            and abs(px_proj[0] - pele_srgb[0]) <= 0.16
        )

        frente = max(0.0, min(1.0, (-nrm[i].y - 0.14) / 0.42))
        peso_cab = _peso_grupo(v, ids_cab) + _peso_grupo(v, ids_olhos)
        peso_bra = _peso_grupo(v, ids_bracos)
        peso_bra_distal = _peso_grupo(v, ids_bracos_distais)
        k = min(fatias - 1, max(0, int((p.z - zmin) / h_tot * fatias)))
        colide_quadril = (
            peso_bra > 0.35
            and tem_fatia[k]
            and (tronco_min_x[k] - 0.025) <= p.x <= (tronco_max_x[k] + 0.025)
        )
        fator_borda = 1.0
        if peso_bra <= 0.35 and tem_fatia[k]:
            larg_k = max(0.01, tronco_max_x[k] - tronco_min_x[k])
            raz_x = abs(p.x - xc) / larg_k
            if raz_x > 0.32:
                fator_borda = max(0.0, min(1.0, 1.0 - (raz_x - 0.32) / 0.14))

        usa_pele_fixa = min(1.0, max(0.0, max(peso_cab * 1.4, (peso_bra - 0.12) * 1.45)))

        if colide_quadril:
            w_frente = 0.0
        elif peso_bra_distal > 0.35:
            # Antebracos e maos usam preenchimento uniforme quente sem palido estourado nem halo de A-pose
            usa_pele_fixa = 1.0
            w_frente = min(frente, 0.18) if proj_pele_limpa else 0.0
        elif peso_bra > 0.18:
            base_f = max(0.0, min(1.0, (-nrm[i].y - 0.14) / 0.40))
            if not proj_pele_limpa:
                w_frente = 0.0
                usa_pele_fixa = 1.0
            else:
                w_frente = base_f * 0.55
                usa_pele_fixa = max(usa_pele_fixa, 0.85)
        elif peso_cab > 0.25:
            w_frente = max(0.0, min(1.0, (-nrm[i].y - 0.14) / 0.40))
            if px_proj[3] < 0.75:
                w_frente = 0.0
        else:
            w_frente = max(0.0, min(1.0, (-nrm[i].y - 0.18) / 0.42)) * fator_borda

        attr_frente.data[i].color = (w_frente, w_frente, w_frente, 1.0)
        attr_pele.data[i].color = (usa_pele_fixa, usa_pele_fixa, usa_pele_fixa, 1.0)
        t_b = min(1.0, max(0.0, (peso_bra - 0.15) * 1.35))
        cor_p = tuple(pele_cranio[c] * (1.0 - t_b) + pele_braco[c] * t_b for c in range(4))
        attr_cor_pele.data[i].color = cor_p

    for lp in me.loops:
        p = pts[lp.vertex_index]
        t_raw = (p.z - zmin) / h_tot
        t_warp = _mapear_t_z(t_raw, anc_src, anc_dst)
        yy = foto.y0 + t_warp * (foto.y1 - foto.y0)
        xx = cx_foto + (p.x - xc) * s
        # Mantem proj_limpo no pano liso longe da costura central do short/top e das bordas laterais
        dx = p.x - xc
        sinal = 1.0 if dx >= 0.0 else -1.0
        dx_limpo = sinal * max(0.028 * h_tot, min(0.048 * h_tot, abs(dx) * 0.30))
        xx_limpo = cx_foto + dx_limpo * s
        uvp.data[lp.index].uv = (xx / foto.w, yy / foto.h)
        uvl.data[lp.index].uv = (xx_limpo / foto.w, yy / foto.h)

    mat = bpy.data.materials.new("bake_proj")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    em = nt.nodes.new("ShaderNodeEmission")

    uv_f = nt.nodes.new("ShaderNodeUVMap")
    uv_f.uv_map = "proj"
    ti_f = nt.nodes.new("ShaderNodeTexImage")
    ti_f.image = foto.img
    ti_f.extension = "EXTEND"
    nt.links.new(uv_f.outputs[0], ti_f.inputs[0])

    uv_b = nt.nodes.new("ShaderNodeUVMap")
    uv_b.uv_map = "proj_limpo"
    ti_b = nt.nodes.new("ShaderNodeTexImage")
    ti_b.image = foto.img
    ti_b.extension = "EXTEND"
    nt.links.new(uv_b.outputs[0], ti_b.inputs[0])

    at_p = nt.nodes.new("ShaderNodeAttribute")
    at_p.attribute_name = "usa_pele"
    at_cp = nt.nodes.new("ShaderNodeAttribute")
    at_cp.attribute_name = "pele_local"
    mix_back = nt.nodes.new("ShaderNodeMix")
    mix_back.data_type = "RGBA"
    nt.links.new(at_p.outputs["Fac"], mix_back.inputs[0])
    nt.links.new(ti_b.outputs[0], mix_back.inputs[6])
    nt.links.new(at_cp.outputs["Color"], mix_back.inputs[7])

    at_f = nt.nodes.new("ShaderNodeAttribute")
    at_f.attribute_name = "frente"
    mix_fin = nt.nodes.new("ShaderNodeMix")
    mix_fin.data_type = "RGBA"
    nt.links.new(at_f.outputs["Fac"], mix_fin.inputs[0])
    nt.links.new(mix_back.outputs[2], mix_fin.inputs[6])
    nt.links.new(ti_f.outputs[0], mix_fin.inputs[7])
    nt.links.new(mix_fin.outputs[2], em.inputs[0])
    nt.links.new(em.outputs[0], out.inputs[0])

    alvo = bpy.data.images.new("baseColor", tam, tam)
    tn = nt.nodes.new("ShaderNodeTexImage")
    tn.image = alvo
    nt.nodes.active = tn
    me.materials.clear()
    me.materials.append(mat)
    for lyr in me.uv_layers:
        lyr.active_render = lyr.name == uv_orig
    me.uv_layers.active = me.uv_layers[uv_orig]

    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.samples = 1
    sc.cycles.device = "CPU"
    sc.render.bake.margin = 8
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.bake(type="EMIT")
    caminho = os.path.join(saida, "baseColor.png")
    alvo.filepath_raw = caminho
    alvo.file_format = "PNG"
    alvo.save()

    alvo.pack()
    final = bpy.data.materials.new("template_pele")
    final.use_nodes = True
    final.use_backface_culling = True
    bsdf = final.node_tree.nodes["Principled BSDF"]
    tx = final.node_tree.nodes.new("ShaderNodeTexImage")
    tx.image = alvo
    final.node_tree.links.new(tx.outputs[0], bsdf.inputs["Base Color"])
    if "Roughness" in bsdf.inputs:
        bsdf.inputs["Roughness"].default_value = 0.78
    if "Specular IOR Level" in bsdf.inputs:
        bsdf.inputs["Specular IOR Level"].default_value = 0.18
    if "Metallic" in bsdf.inputs:
        bsdf.inputs["Metallic"].default_value = 0.0
    me.materials.clear()
    me.materials.append(final)
    me.uv_layers.remove(me.uv_layers["proj"])
    me.uv_layers.remove(me.uv_layers["proj_limpo"])
    me.color_attributes.remove(me.color_attributes["frente"])
    me.color_attributes.remove(me.color_attributes["usa_pele"])
    me.color_attributes.remove(me.color_attributes["pele_local"])
    return caminho, {
        "ancoras_src": [round(x, 4) for x in anc_src],
        "ancoras_dst": [round(x, 4) for x in anc_dst],
        "pele_srgb": [round(float(c), 3) for c in pele_srgb[:3]],
        "pele_braco": [round(float(c), 3) for c in pele_braco[:3]],
    }
