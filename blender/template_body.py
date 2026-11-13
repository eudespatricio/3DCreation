"""Corpo base por template MPFB2 (CC0) + textura projetada da foto frontal (bpy puro, I9).

Uso: blender -b --python blender/template_body.py -- <job.json>
job.json: {"foto": png RGBA (fundo sangrado), "saida": dir, "macro": {...} opcional,
           "auto_ajuste": true, "braco_graus": 7.0, "antebraco_graus": 1.0,
           "perna_graus": -2.0, "marcos": {"olhos_frac": float, "boca_frac": float} opcional,
           "textura": 1024, "rig": false}
Escreve <saida>/template_body.glb (A-pose, frente +Y), baseColor.png e relatorio.json.
"""
import json
import math
import os
import sys

import bmesh
import bpy
from mathutils import Matrix, Vector

MACRO_PADRAO = {
    "gender": 0.0,
    "age": 0.45,
    "muscle": 0.55,
    "weight": 0.48,
    "height": 0.45,
    "cupsize": 0.55,
    "firmness": 0.5,
    "proportions": 0.8,
    "race": {"asian": 0.1, "caucasian": 0.5, "african": 0.4},
}
GRADE = 8

_OSSOS_BRACO_DISTAL = {
    f"{p}_{lado}"
    for lado in ("l", "r")
    for p in ("lowerarm", "hand", "index_01", "index_02", "index_03",
              "middle_01", "middle_02", "middle_03", "ring_01", "ring_02", "ring_03",
              "pinky_01", "pinky_02", "pinky_03", "thumb_01", "thumb_02", "thumb_03")
}
_OSSOS_BRACO = _OSSOS_BRACO_DISTAL | {"upperarm_l", "upperarm_r"}
_OSSOS_TRONCO = {
    "pelvis", "spine_01", "spine_02", "spine_03", "clavicle_l", "clavicle_r",
    "thigh_l", "thigh_r", "calf_l", "calf_r", "foot_l", "foot_r", "ball_l", "ball_r",
}


def _srgb_to_linear(c: float) -> float:
    c = max(0.0, min(1.0, float(c)))
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _rgba_srgb_to_linear(rgba) -> tuple[float, float, float, float]:
    return (_srgb_to_linear(rgba[0]), _srgb_to_linear(rgba[1]), _srgb_to_linear(rgba[2]), 1.0)


def _hex_to_rgb_srgb(cor: str) -> tuple[float, float, float] | None:
    bruto = (cor or "").strip().lstrip("#")
    if len(bruto) != 6:
        return None
    try:
        return (
            int(bruto[0:2], 16) / 255.0,
            int(bruto[2:4], 16) / 255.0,
            int(bruto[4:6], 16) / 255.0,
        )
    except ValueError:
        return None


def _mpfb():
    try:
        from bl_ext.user_default.mpfb.services.humanservice import HumanService
        from bl_ext.user_default.mpfb.services.targetservice import TargetService
    except ImportError as exc:  # pragma: no cover - depende do DCC
        raise SystemExit(f"MPFB2 ausente no Blender (extensao 'mpfb'): {exc}") from exc
    return HumanService, TargetService


def _encontrar_mhclo_cabelo(estilo_ou_caminho: str) -> str:
    bruto = (estilo_ou_caminho or "").strip()
    if not bruto:
        raise SystemExit("estilo MakeHuman vazio")
    if os.path.isfile(bruto):
        return bruto

    estilo = bruto
    if estilo.startswith("makehuman://"):
        estilo = estilo[len("makehuman://"):]
    estilo = estilo.strip("/")
    if estilo.startswith("hair/"):
        estilo = estilo[len("hair/"):]
    estilo = estilo.split("/")[0]
    if estilo.endswith(".mhclo"):
        estilo = estilo[:-6]

    raizes: list[str] = []
    for env_var in ("FORGE3D_MPFB_ASSETS", "FORGE3D_MAKEHUMAN_DIR"):
        env_dir = os.environ.get(env_var, "").strip()
        if env_dir:
            raizes.extend([os.path.join(env_dir, "hair"), env_dir])
    try:
        from bl_ext.user_default.mpfb.services.locationservice import LocationService

        user_hair = LocationService.get_user_data("hair")
        if user_hair:
            raizes.append(user_hair)
    except Exception:
        pass
    try:
        from bl_ext.user_default.mpfb.services.assetservice import AssetService

        raizes.extend(AssetService.get_asset_roots("hair"))
    except Exception:
        pass
    cfg_dir = ""
    try:
        cfg_dir = bpy.utils.user_resource("CONFIG") or ""
    except Exception:
        cfg_dir = ""
    if cfg_dir:
        raizes.extend([
            os.path.join(cfg_dir, "extensions", ".user", "user_default", "mpfb", "data", "hair"),
            os.path.join(cfg_dir, "extensions", "user_default", "mpfb", "data", "hair"),
        ])
    xdg = os.environ.get("XDG_CONFIG_HOME", "").strip()
    if xdg:
        raizes.append(os.path.join(xdg, "blender", "4.2", "extensions", ".user", "user_default", "mpfb", "data", "hair"))
    raizes.append(os.path.expanduser("~/.config/blender/4.2/extensions/.user/user_default/mpfb/data/hair"))
    raizes.append(os.path.expanduser("~/.config/blender/4.2/extensions/user_default/mpfb/data/hair"))

    vistos: set[str] = set()
    for raiz in raizes:
        if not raiz or raiz in vistos:
            continue
        vistos.add(raiz)
        for candidato in (
            os.path.join(raiz, estilo, f"{estilo}.mhclo"),
            os.path.join(raiz, f"{estilo}.mhclo"),
        ):
            if os.path.isfile(candidato):
                return candidato
    raise SystemExit(f"cabelo MakeHuman '{estilo}' nao encontrado nos pacotes MPFB2 locais")


def criar_humano(macro: dict, alvos: dict, mhclo_cabelo: str | None = None):
    HumanService, TargetService = _mpfb()
    m = TargetService.get_default_macro_info_dict()
    m.update(macro)
    obj = HumanService.create_human(scale=0.1, macro_detail_dict=m)
    for nome, peso in alvos.items():
        if TargetService.has_target(obj, nome):
            TargetService.set_target_value(obj, nome, float(peso))
        else:
            caminho = TargetService.target_full_path(nome)
            if caminho:
                TargetService.load_target(obj, caminho, weight=float(peso))
    hair_obj = None
    if mhclo_cabelo:
        # Critico: add_mhclo_asset DEVE rodar ANTES de bake_targets para casar com o cranio 1,55 m.
        hair_obj = HumanService.add_mhclo_asset(
            mhclo_cabelo,
            obj,
            asset_type="Hair",
            subdiv_levels=0,
            material_type="GAMEENGINE",
            set_up_rigging=False,
        )
    rig = HumanService.add_builtin_rig(obj, "game_engine")
    TargetService.bake_targets(obj)
    for mod in list(obj.modifiers):
        if mod.type == "MASK":
            obj.modifiers.remove(mod)
    return obj, rig, hair_obj


def limpar_helpers(obj) -> None:
    """Remove geometria auxiliar do MakeHuman (mantem olhos) e alisa mamilos."""
    vg = {g.name: g.index for g in obj.vertex_groups}
    manter = {vg.get("helper-l-eye"), vg.get("helper-r-eye")} - {None}
    remover = {vg["HelperGeometry"], vg["JointCubes"]}
    mamilo = {vg.get("nipple"), vg.get("nippleTip")} - {None}
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    dl = bm.verts.layers.deform.active
    lixo = [
        v for v in bm.verts
        if (set(v[dl].keys()) & remover) and not (set(v[dl].keys()) & manter)
    ]
    bmesh.ops.delete(bm, geom=lixo, context="VERTS")
    alvo = {v for v in bm.verts if set(v[dl].keys()) & mamilo}
    for _ in range(4):
        alvo |= {o for v in list(alvo) for e in v.link_edges for o in e.verts}
    for _ in range(35):
        bmesh.ops.smooth_vert(
            bm, verts=list(alvo), factor=0.70,
            use_axis_x=True, use_axis_y=True, use_axis_z=True,
        )
    bm.to_mesh(obj.data)
    bm.free()


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
        return tuple(self.px[i:i + 4])


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
        colide_quadril = False
        if peso_bra > 0.35 and tem_fatia[k]:
            if (tronco_min_x[k] - 0.025) <= p.x <= (tronco_max_x[k] + 0.025):
                colide_quadril = True
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


def _info_cabeca(obj) -> dict:
    vg = {g.name: g.index for g in obj.vertex_groups}
    hid = vg.get("head")
    if hid is None:
        return {}
    pts = [
        obj.matrix_world @ v.co for v in obj.data.vertices
        if any(g.group == hid and g.weight > 0.5 for g in v.groups)
    ]
    if not pts:
        return {}
    return {
        "topo_z": round(max(p.z for p in pts), 4),
        "base_z": round(min(p.z for p in pts), 4),
        "centro_x": round(0.5 * (min(p.x for p in pts) + max(p.x for p in pts)), 4),
        "centro_y": round(-0.5 * (min(p.y for p in pts) + max(p.y for p in pts)), 4),
        "largura_x": round(max(p.x for p in pts) - min(p.x for p in pts), 4),
        "profundidade_y": round(max(p.y for p in pts) - min(p.y for p in pts), 4),
    }


def _info_cabelo(hair_obj, body_obj, info_cabeca: dict) -> dict:
    bpy.context.view_layer.update()
    pts_b = [body_obj.matrix_world @ v.co for v in body_obj.data.vertices]
    pts_h = [hair_obj.matrix_world @ v.co for v in hair_obj.data.vertices]
    if not pts_b or not pts_h:
        return {}
    body_h = max(p.z for p in pts_b) - min(p.z for p in pts_b)
    min_h = Vector((min(p.x for p in pts_h), min(p.y for p in pts_h), min(p.z for p in pts_h)))
    max_h = Vector((max(p.x for p in pts_h), max(p.y for p in pts_h), max(p.z for p in pts_h)))
    hair_h = max_h.z - min_h.z
    # Apos rotacao Z=pi, Y do MakeHuman inverte sinal para +Y=frente
    hair_cy_pos = -0.5 * (min_h.y + max_h.y)
    cab_cy_pos = float(info_cabeca.get("centro_y", 0.0))
    cab_topo = float(info_cabeca.get("topo_z", max_h.z))
    return {
        "altura_raw_m": round(hair_h, 4),
        "altura_corpo_raw_m": round(body_h, 4),
        "escala_relativa_corpo": round(hair_h / max(1e-5, body_h), 4),
        "offset_topo_cranio_z": round(max_h.z - cab_topo, 4),
        "offset_centro_y": round(hair_cy_pos - cab_cy_pos, 4),
    }


def _limpar_nao_manifold_aberto(obj) -> None:
    """Divide arestas com >2 faces e vertices multi-leque em tiras de cabelo MakeHuman."""
    for _ in range(5):
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bmesh.ops.triangulate(bm, faces=list(bm.faces))
        bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1e-5)
        bmesh.ops.dissolve_degenerate(bm, dist=1e-6, edges=list(bm.edges))
        slivers = [f for f in bm.faces if f.calc_area() < 1e-8]
        if slivers:
            bmesh.ops.delete(bm, geom=slivers, context="FACES")
            soltas_e = [e for e in bm.edges if not e.link_faces]
            if soltas_e:
                bmesh.ops.delete(bm, geom=soltas_e, context="EDGES")
            soltos = [v for v in bm.verts if not v.link_faces]
            if soltos:
                bmesh.ops.delete(bm, geom=soltos, context="VERTS")
        nm_edges = {e for e in bm.edges if len(e.link_faces) > 2}
        for v in bm.verts:
            if not v.is_manifold and not v.is_boundary:
                nm_edges.update(v.link_edges)
            elif v.link_faces:
                rest = set(v.link_faces)
                f0 = next(iter(rest))
                stack = [f0]
                seen = {f0}
                while stack:
                    cur = stack.pop()
                    for e in cur.edges:
                        if v in e.verts:
                            for nf in e.link_faces:
                                if nf in rest and nf not in seen:
                                    seen.add(nf)
                                    stack.append(nf)
                if len(seen) < len(rest):
                    nm_edges.update(v.link_edges)
        if not nm_edges:
            bm.to_mesh(obj.data)
            bm.free()
            obj.data.update()
            return
        bmesh.ops.split_edges(bm, edges=list(nm_edges))
        bm.normal_update()
        pos_map: dict[tuple[float, float, float], list] = {}
        for v in bm.verts:
            chave = (round(v.co.x, 5), round(v.co.y, 5), round(v.co.z, 5))
            pos_map.setdefault(chave, []).append(v)
        for vs in pos_map.values():
            if len(vs) > 1:
                for idx, v in enumerate(vs[1:], 1):
                    n = v.normal if v.normal.length > 1e-6 else Vector((0.0, 0.0, 1.0))
                    v.co += n * (0.0002 * idx)
        bm.to_mesh(obj.data)
        bm.free()
        obj.data.update()


def _preparar_cabelo_manifold(hair_obj, target_tris: int) -> dict:
    """Converte tiras abertas .mhclo em malha fechada manifold (G1=0) respeitando target_tris."""
    _limpar_nao_manifold_aberto(hair_obj)
    for _ in range(4):
        bm = bmesh.new()
        bm.from_mesh(hair_obj.data)
        t_cur = len(bm.faces)
        b_cur = sum(1 for e in bm.edges if len(e.link_faces) == 1)
        bm.free()
        est_solid = 2 * t_cur + 2 * b_cur
        if target_tris <= 0 or est_solid <= target_tris:
            break
        ratio = max(0.05, min(0.92, (target_tris * 0.90) / max(1, est_solid)))
        mod_d = hair_obj.modifiers.new("pre_dec", "DECIMATE")
        mod_d.ratio = ratio
        bpy.ops.object.select_all(action="DESELECT")
        bpy.context.view_layer.objects.active = hair_obj
        hair_obj.select_set(True)
        bpy.ops.object.modifier_apply(modifier=mod_d.name)
        _limpar_nao_manifold_aberto(hair_obj)

    mod = hair_obj.modifiers.new("Solidify", "SOLIDIFY")
    mod.thickness = 0.0012
    mod.offset = 0.0
    mod.use_rim = True
    mod.use_rim_only = False
    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = hair_obj
    hair_obj.select_set(True)
    bpy.ops.object.modifier_apply(modifier=mod.name)

    bm = bmesh.new()
    bm.from_mesh(hair_obj.data)
    bmesh.ops.triangulate(bm, faces=list(bm.faces))
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1e-5)
    bmesh.ops.dissolve_degenerate(bm, dist=1e-6, edges=list(bm.edges))
    slivers = [f for f in bm.faces if f.calc_area() < 1e-8]
    if slivers:
        bmesh.ops.delete(bm, geom=slivers, context="FACES")
    soltas_e = [e for e in bm.edges if not e.link_faces]
    if soltas_e:
        bmesh.ops.delete(bm, geom=soltas_e, context="EDGES")
    soltos = [v for v in bm.verts if not v.link_faces]
    if soltos:
        bmesh.ops.delete(bm, geom=soltos, context="VERTS")
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    nao_manifold = sum(1 for e in bm.edges if len(e.link_faces) != 2)
    degeneradas = sum(1 for f in bm.faces if f.calc_area() < 1e-12)
    tris = len(bm.faces)
    bm.to_mesh(hair_obj.data)
    bm.free()
    hair_obj.data.shade_smooth()
    hair_obj.data.set_sharp_from_angle(angle=math.radians(85.0))
    hair_obj.data.update()
    return {
        "triangulos": tris,
        "nao_manifold": nao_manifold,
        "degeneradas": degeneradas,
    }


def _preparar_textura_e_material_cabelo(
    hair_obj,
    estilo: str,
    saida: str,
    tex_px: int,
    cor_hex: str = "",
    material_modo: str = "alpha_clip",
    png_nome: str = "baseColor.png",
) -> str:
    """Redimensiona difusa POT, aplica tintura/bleed sem halo branco e cria material glTF."""
    img_orig = None
    for mat in hair_obj.data.materials:
        if mat and mat.use_nodes:
            for node in mat.node_tree.nodes:
                if node.type == "TEX_IMAGE" and node.image is not None:
                    img_orig = node.image
                    break
        if img_orig is not None:
            break
    if img_orig is None:
        raise RuntimeError(f"cabelo MakeHuman '{estilo}' sem textura difusa")

    img = img_orig.copy()
    img.name = f"mh_{estilo}_baseColor"
    if img.size[0] != tex_px or img.size[1] != tex_px:
        img.scale(tex_px, tex_px)

    px = list(img.pixels)
    n_px = len(px) // 4
    soma_r = soma_g = soma_b = soma_lum = 0.0
    qtd_opacos = 0
    tem_alfa = False
    for k in range(n_px):
        off = k * 4
        r, g, b, a = px[off], px[off + 1], px[off + 2], px[off + 3]
        if a < 0.98:
            tem_alfa = True
        if a > 0.60:
            soma_r += r
            soma_g += g
            soma_b += b
            soma_lum += 0.2126 * r + 0.7152 * g + 0.0722 * b
            qtd_opacos += 1

    avg_r = soma_r / max(1, qtd_opacos)
    avg_g = soma_g / max(1, qtd_opacos)
    avg_b = soma_b / max(1, qtd_opacos)
    avg_lum = max(0.05, soma_lum / max(1, qtd_opacos))

    alvo_tint = _hex_to_rgb_srgb(cor_hex)
    fill_r, fill_g, fill_b = alvo_tint if alvo_tint is not None else (avg_r, avg_g, avg_b)
    for k in range(n_px):
        off = k * 4
        r, g, b, a = px[off], px[off + 1], px[off + 2], px[off + 3]
        if alvo_tint is not None and a > 0.02:
            lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
            rel = min(1.35, lum / avg_lum)
            fator = 0.25 + 0.75 * rel
            r = min(1.0, alvo_tint[0] * fator)
            g = min(1.0, alvo_tint[1] * fator)
            b = min(1.0, alvo_tint[2] * fator)
        if a < 0.50:
            # Remove borda branca de alpha=0..0.5 nas pontas de mechas para evitar halo no Alpha Clip
            r, g, b = fill_r, fill_g, fill_b
        px[off], px[off + 1], px[off + 2] = r, g, b
    img.pixels[:] = px

    sc = bpy.context.scene
    ant_mode = sc.render.image_settings.color_mode
    sc.render.image_settings.color_mode = "RGBA"
    caminho = os.path.join(saida, png_nome)
    img.filepath_raw = caminho
    img.file_format = "PNG"
    img.save()
    sc.render.image_settings.color_mode = ant_mode
    img.pack()

    mat = bpy.data.materials.new(f"makehuman_cabelo_{estilo}")
    mat.use_nodes = True
    mat.use_backface_culling = True
    nt = mat.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = img
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    usar_clip = (material_modo == "alpha_clip") or (tem_alfa and material_modo != "opaque")
    if usar_clip:
        mat.blend_method = "CLIP"
        if hasattr(mat, "surface_render_method"):
            mat.surface_render_method = "DITHERED"
        if hasattr(mat, "alpha_threshold"):
            mat.alpha_threshold = 0.5
        cut = nt.nodes.new("ShaderNodeMath")
        cut.operation = "GREATER_THAN"
        cut.inputs[1].default_value = 0.5
        nt.links.new(tex.outputs["Alpha"], cut.inputs[0])
        nt.links.new(cut.outputs["Value"], bsdf.inputs["Alpha"])
    if "Roughness" in bsdf.inputs:
        bsdf.inputs["Roughness"].default_value = 0.85
    if "Specular IOR Level" in bsdf.inputs:
        bsdf.inputs["Specular IOR Level"].default_value = 0.08
    if "Metallic" in bsdf.inputs:
        bsdf.inputs["Metallic"].default_value = 0.0
    hair_obj.data.materials.clear()
    hair_obj.data.materials.append(mat)
    return caminho


def _unificar_materiais_corpo_cabelo(
    body_obj,
    hair_obj,
    tex_corpo_path: str,
    tex_cabelo_path: str,
    tex_px: int,
) -> None:
    """Combina corpo e cabelo em 1 material e 1 atlas lado-a-lado (materiais_max=1)."""
    if not body_obj.data.uv_layers or not hair_obj.data.uv_layers:
        return
    if not body_obj.data.materials:
        return

    uv_b = body_obj.data.uv_layers[0].data
    for lp in uv_b:
        u = max(0.0, min(1.0, float(lp.uv[0])))
        v = max(0.0, min(1.0, float(lp.uv[1])))
        lp.uv = (0.002 + 0.496 * u, v)

    uv_h = hair_obj.data.uv_layers[0].data
    for lp in uv_h:
        u = max(0.0, min(1.0, float(lp.uv[0])))
        v = max(0.0, min(1.0, float(lp.uv[1])))
        lp.uv = (0.502 + 0.496 * u, v)

    img_c = bpy.data.images.load(tex_corpo_path, check_existing=True)
    img_h = bpy.data.images.load(tex_cabelo_path, check_existing=True)
    c_tmp = img_c.copy()
    h_tmp = img_h.copy()
    if int(c_tmp.size[0]) != tex_px or int(c_tmp.size[1]) != tex_px:
        c_tmp.scale(tex_px, tex_px)
    if int(h_tmp.size[0]) != tex_px or int(h_tmp.size[1]) != tex_px:
        h_tmp.scale(tex_px, tex_px)
    px_c = list(c_tmp.pixels)
    px_h = list(h_tmp.pixels)
    bpy.data.images.remove(c_tmp)
    bpy.data.images.remove(h_tmp)

    half = tex_px // 2
    buf = [1.0] * (tex_px * tex_px * 4)
    for y in range(tex_px):
        row_off = y * tex_px
        for x in range(half):
            sx = min(tex_px - 1, x * 2)
            src = (row_off + sx) * 4
            dst = (row_off + x) * 4
            buf[dst] = px_c[src]
            buf[dst + 1] = px_c[src + 1]
            buf[dst + 2] = px_c[src + 2]
            buf[dst + 3] = 1.0
        for x in range(half, tex_px):
            sx = min(tex_px - 1, (x - half) * 2)
            src = (row_off + sx) * 4
            dst = (row_off + x) * 4
            buf[dst] = px_h[src]
            buf[dst + 1] = px_h[src + 1]
            buf[dst + 2] = px_h[src + 2]
            buf[dst + 3] = px_h[src + 3]

    img_unif = bpy.data.images.new("unified_baseColor", width=tex_px, height=tex_px, alpha=True)
    img_unif.pixels.foreach_set(buf)
    sc = bpy.context.scene
    ant_mode = sc.render.image_settings.color_mode
    sc.render.image_settings.color_mode = "RGBA"
    img_unif.filepath_raw = tex_corpo_path
    img_unif.file_format = "PNG"
    img_unif.save()
    sc.render.image_settings.color_mode = ant_mode
    img_unif.pack()

    mat_corpo = body_obj.data.materials[0]
    nt = mat_corpo.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    tex_node = next((n for n in nt.nodes if n.type == "TEX_IMAGE"), None)
    if tex_node is not None:
        tex_node.image = img_unif
        if bsdf is not None and "Alpha" in bsdf.inputs:
            nt.links.new(tex_node.outputs["Alpha"], bsdf.inputs["Alpha"])
    hair_usa_clip = any(getattr(m, "blend_method", "OPAQUE") == "CLIP" for m in hair_obj.data.materials if m)
    if hair_usa_clip:
        mat_corpo.blend_method = "CLIP"
        if hasattr(mat_corpo, "alpha_threshold"):
            mat_corpo.alpha_threshold = 0.5

    hair_obj.data.materials.clear()
    hair_obj.data.materials.append(mat_corpo)


def exportar(obj, rig, saida: str, manter_rig: bool, nome_glb: str = "template_body.glb") -> str:
    if rig is not None:
        for pb in rig.pose.bones:
            pb.matrix_basis = Matrix.Identity(4)
        bpy.context.view_layer.update()
    bpy.ops.object.select_all(action="DESELECT")
    if manter_rig and rig is not None:
        rig.rotation_euler.z = math.pi
        rig.select_set(True)
    else:
        for mod in list(obj.modifiers):
            if mod.type == "ARMATURE":
                obj.modifiers.remove(mod)
        mw = obj.matrix_world.copy()
        obj.parent = None
        obj.matrix_world = mw
        obj.vertex_groups.clear()
        if rig is not None:
            bpy.data.objects.remove(rig, do_unlink=True)
        obj.rotation_euler.z = math.pi
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    obj.select_set(True)
    glb = os.path.join(saida, nome_glb)
    tem_normal = any(
        inp.is_linked
        for mat in (obj.data.materials if obj and obj.data else ())
        if mat and mat.use_nodes
        for node in mat.node_tree.nodes
        if node.type == "BSDF_PRINCIPLED"
        for inp in [node.inputs.get("Normal")]
        if inp is not None
    )
    export_kw = {
        "filepath": glb,
        "use_selection": True,
        "export_format": "GLB",
        "export_animations": False,
    }
    if tem_normal:
        export_kw["export_tangents"] = True
    bpy.ops.export_scene.gltf(**export_kw)
    return glb


def main() -> int:
    job = json.load(open(sys.argv[sys.argv.index("--") + 1]))
    saida = job["saida"]
    os.makedirs(saida, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    macro = dict(MACRO_PADRAO)
    macro.update(job.get("macro") or {})
    alvos = {"nipple-point-decr": 1.0, "nipple-size-decr": 1.0}
    alvos.update(job.get("alvos") or {})

    modo = str(job.get("modo") or "corpo").strip().lower()
    mh_req = str(job.get("mhclo") or job.get("makehuman_cabelo") or "").strip()
    mhclo_path = _encontrar_mhclo_cabelo(mh_req) if mh_req else None
    estilo = str(job.get("estilo") or (os.path.splitext(os.path.basename(mhclo_path))[0] if mhclo_path else "")).strip()

    obj, rig, hair_obj = criar_humano(macro, alvos, mhclo_cabelo=mhclo_path)
    limpar_helpers(obj)
    info_cabeca = _info_cabeca(obj)

    if modo == "cabelo":
        if hair_obj is None:
            raise SystemExit("modo 'cabelo' exige 'mhclo' ou 'makehuman_cabelo'")
        info_cabelo = _info_cabelo(hair_obj, obj, info_cabeca)
        # Remove corpo/rig mantendo apenas o cabelo encaixado ao macro exato do personagem
        bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.objects.remove(rig, do_unlink=True)
        topo = _preparar_cabelo_manifold(hair_obj, int(job.get("limite_triangulos", 6000)))
        tex = _preparar_textura_e_material_cabelo(
            hair_obj,
            estilo or "hair",
            saida,
            int(job.get("textura", 1024)),
            str(job.get("cor_cabelo") or ""),
            str(job.get("material") or "alpha_clip"),
        )
        glb = exportar(hair_obj, None, saida, False, nome_glb="template_hair.glb")
        rel = {
            "glb": glb,
            "baseColor": tex,
            "modo": "cabelo",
            "estilo": estilo,
            "triangulos": topo["triangulos"],
            "nao_manifold": topo["nao_manifold"],
            "degeneradas": topo["degeneradas"],
            "template": "mpfb2 (CC0)",
            "macro": macro,
            "cabeca": info_cabeca,
            "encaixe_cabeca": info_cabelo,
        }
        json.dump(rel, open(os.path.join(saida, "relatorio.json"), "w"), indent=2)
        print("TEMPLATE_HAIR_OK", json.dumps({"estilo": estilo, **topo}))
        return 0

    foto = Foto(job["foto"])
    upper = float(job.get("braco_graus", 7.0))
    lower = float(job.get("antebraco_graus", 1.0))
    perna = float(job.get("perna_graus", -2.0))
    score = None
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="POSE")
    if job.get("auto_ajuste", True):
        score, upper, lower, perna = auto_ajuste(obj, rig, foto, upper, lower, perna)
    else:
        posar(rig, upper, lower, perna)
    bpy.ops.object.mode_set(mode="OBJECT")
    tex, info_proj = projetar_e_assar(obj, foto, saida, int(job.get("textura", 1024)), job.get("marcos"))

    info_cabelo = {}
    if hair_obj is not None:
        info_cabelo = _info_cabelo(hair_obj, obj, info_cabeca)
        limite_total = int(job.get("limite_triangulos", 12000))
        hair_budget = min(max(1500, limite_total // 3), 4500)
        topo_hair = _preparar_cabelo_manifold(hair_obj, hair_budget)
        tex_cabelo = _preparar_textura_e_material_cabelo(
            hair_obj,
            estilo or "hair",
            saida,
            int(job.get("textura", 1024)),
            str(job.get("cor_cabelo") or ""),
            str(job.get("material_cabelo") or "alpha_clip"),
            png_nome="hair_baseColor.png",
        )
        # Mantem o total corpo+cabelo dentro do teto protegendo cabeca/maos (nunca decimate cego no rosto)
        body_budget = max(2500, limite_total - topo_hair["triangulos"])
        tris_body = sum(len(p.vertices) - 2 for p in obj.data.polygons)
        if tris_body > body_budget:
            if not bool(job.get("rig", False)):
                for pb in rig.pose.bones:
                    pb.matrix_basis = Matrix.Identity(4)
                bpy.context.view_layer.update()
                for mod in list(obj.modifiers):
                    if mod.type == "ARMATURE":
                        obj.modifiers.remove(mod)
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import postprocess as _pp  # noqa: E402

            _pp.decimar(obj, body_budget, proteger_cabeca_maos=True)
        if hair_obj.data.uv_layers and obj.data.uv_layers:
            hair_obj.data.uv_layers[0].name = obj.data.uv_layers[0].name
        if int(job.get("materiais_max") or 8) <= 1:
            _unificar_materiais_corpo_cabelo(
                obj,
                hair_obj,
                tex,
                tex_cabelo,
                int(job.get("textura", 1024)),
            )
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        hair_obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.join()

    glb = exportar(obj, rig, saida, bool(job.get("rig", False)))
    rel = {
        "glb": glb,
        "baseColor": tex,
        "braco_graus": upper,
        "antebraco_graus": lower,
        "perna_graus": perna,
        "iou_silhueta": score,
        "triangulos": sum(len(p.vertices) - 2 for p in obj.data.polygons),
        "template": "mpfb2 (CC0)",
        "macro": macro,
        "cabeca": info_cabeca,
        "projecao": info_proj,
    }
    if info_cabelo:
        rel["cabelo"] = {"estilo": estilo, **info_cabelo}
    json.dump(rel, open(os.path.join(saida, "relatorio.json"), "w"), indent=2)
    print("TEMPLATE_OK", json.dumps({k: rel[k] for k in ("braco_graus", "antebraco_graus", "perna_graus", "iou_silhueta", "triangulos")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
