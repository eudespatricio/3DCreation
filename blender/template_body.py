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
import zipfile

import bmesh
import bpy
from mathutils import Euler, Matrix, Vector

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


_CATEGORIAS_MPFB_CC0 = ("skins", "eyes", "eyebrows", "eyelashes", "clothes", "hair")


def _garantir_pacote_mpfb_extraido() -> str | None:
    """Extrai idempotentemente makehuman_system_assets_cc0.zip para <mpfb_cache>/extracted_cc0."""
    cache_padrao = os.path.join(os.path.expanduser("~"), ".cache", "forge3d", "mpfb_assets")
    env_assets = os.environ.get("FORGE3D_MPFB_ASSETS", "").strip()
    base_dir = os.path.expanduser(env_assets) if env_assets else cache_padrao

    if os.path.isdir(base_dir) and all(
        os.path.isdir(os.path.join(base_dir, c)) for c in ("skins", "clothes", "hair")
    ):
        return base_dir

    dest_dir = os.path.join(base_dir, "extracted_cc0")
    marcador = os.path.join(dest_dir, ".extracted_ok")
    if os.path.isfile(marcador) or (
        os.path.isdir(os.path.join(dest_dir, "skins"))
        and os.path.isdir(os.path.join(dest_dir, "clothes"))
    ):
        return dest_dir

    env_zip = os.environ.get("FORGE3D_MPFB_ASSETS_ZIP", "").strip()
    candidatos_zip = []
    if env_zip:
        candidatos_zip.append(os.path.expanduser(env_zip))
    candidatos_zip.extend([
        os.path.join(base_dir, "makehuman_system_assets_cc0.zip"),
        os.path.join(cache_padrao, "makehuman_system_assets_cc0.zip"),
    ])
    zip_path = next((p for p in candidatos_zip if p and os.path.isfile(p)), None)
    if not zip_path:
        return dest_dir if os.path.isdir(dest_dir) else None

    try:
        os.makedirs(dest_dir, exist_ok=True)
        prefixos = tuple(f"{c}/" for c in _CATEGORIAS_MPFB_CC0)
        with zipfile.ZipFile(zip_path, "r") as zf:
            for member in zf.namelist():
                if not member.startswith(prefixos) or ".." in member:
                    continue
                alvo = os.path.join(dest_dir, member)
                if member.endswith("/"):
                    os.makedirs(alvo, exist_ok=True)
                elif not os.path.isfile(alvo):
                    os.makedirs(os.path.dirname(alvo), exist_ok=True)
                    with zf.open(member) as src, open(alvo, "wb") as dst:
                        dst.write(src.read())
        with open(marcador, "w", encoding="utf-8") as f_ok:
            f_ok.write("ok\n")
        return dest_dir
    except OSError:
        return dest_dir if os.path.isdir(dest_dir) else None


def _raizes_categoria_mpfb(categoria: str) -> list[str]:
    """Retorna diretorios de busca ordenados para uma categoria MPFB2 (skins, eyes, clothes, hair...)."""
    cat = categoria.strip("/")
    raizes: list[str] = []
    for env_var in ("FORGE3D_MPFB_ASSETS", "FORGE3D_MAKEHUMAN_DIR"):
        env_dir = os.environ.get(env_var, "").strip()
        if env_dir:
            exp = os.path.expanduser(env_dir)
            raizes.extend([os.path.join(exp, cat), os.path.join(exp, "extracted_cc0", cat), exp])
    extraido = _garantir_pacote_mpfb_extraido()
    if extraido:
        raizes.extend([os.path.join(extraido, cat), extraido])
    try:
        from bl_ext.user_default.mpfb.services.locationservice import LocationService

        user_cat = LocationService.get_user_data(cat)
        if user_cat:
            raizes.append(user_cat)
    except Exception:
        pass
    try:
        from bl_ext.user_default.mpfb.services.assetservice import AssetService

        raizes.extend(AssetService.get_asset_roots(cat))
    except Exception:
        pass
    cfg_dir = ""
    try:
        cfg_dir = bpy.utils.user_resource("CONFIG") or ""
    except Exception:
        cfg_dir = ""
    if cfg_dir:
        raizes.extend([
            os.path.join(cfg_dir, "extensions", ".user", "user_default", "mpfb", "data", cat),
            os.path.join(cfg_dir, "extensions", "user_default", "mpfb", "data", cat),
        ])
    xdg = os.environ.get("XDG_CONFIG_HOME", "").strip()
    if xdg:
        raizes.append(
            os.path.join(
                os.path.expanduser(xdg),
                "blender",
                "4.2",
                "extensions",
                ".user",
                "user_default",
                "mpfb",
                "data",
                cat,
            )
        )
    home = os.path.expanduser("~")
    raizes.append(
        os.path.join(home, ".config", "blender", "4.2", "extensions", ".user", "user_default", "mpfb", "data", cat)
    )
    raizes.append(
        os.path.join(home, ".config", "blender", "4.2", "extensions", "user_default", "mpfb", "data", cat)
    )
    vistos: set[str] = set()
    saida: list[str] = []
    for r in raizes:
        if r and r not in vistos:
            vistos.add(r)
            saida.append(r)
    return saida


def _encontrar_ativo_mpfb(categoria: str, nome: str, ext: str = ".mhclo") -> str | None:
    """Procura arquivo <nome><ext> dentro das raizes da categoria MPFB2."""
    alvo = nome.strip("/")
    if alvo.endswith(ext):
        alvo = alvo[: -len(ext)]
    for raiz in _raizes_categoria_mpfb(categoria):
        for cand in (
            os.path.join(raiz, alvo, f"{alvo}{ext}"),
            os.path.join(raiz, f"{alvo}{ext}"),
        ):
            if os.path.isfile(cand):
                return cand
    return None


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

    achado = _encontrar_ativo_mpfb("hair", estilo, ".mhclo")
    if achado:
        return achado
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
    alpha_cutoff: float = 0.5,
    fallback_tex_path: str | None = None,
    mat_nome: str | None = None,
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
    if img_orig is None and fallback_tex_path and os.path.isfile(fallback_tex_path):
        img_orig = bpy.data.images.load(fallback_tex_path, check_existing=True)
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

    mat = bpy.data.materials.new(mat_nome or f"makehuman_cabelo_{estilo}")
    mat.use_nodes = True
    mat.use_backface_culling = True
    nt = mat.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = img
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    usar_clip = (material_modo == "alpha_clip") or (tem_alfa and material_modo != "opaque")
    if usar_clip:
        limiar_a = float(alpha_cutoff)
        mat.blend_method = "CLIP"
        if hasattr(mat, "surface_render_method"):
            mat.surface_render_method = "DITHERED"
        if hasattr(mat, "alpha_threshold"):
            mat.alpha_threshold = limiar_a
        cut = nt.nodes.new("ShaderNodeMath")
        cut.operation = "GREATER_THAN"
        cut.inputs[1].default_value = limiar_a
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


_ANGULOS_DEDOS_POSE = {
    "grip": {
        "fingers": (62.0, 68.0, 52.0),
        "thumb": ((28.0, 32.0), (38.0, 18.0), (32.0, 10.0)),
    },
    "cupped": {
        "fingers": (26.0, 28.0, 22.0),
        "thumb": ((16.0, 18.0), (20.0, 10.0), (16.0, 6.0)),
    },
    "relaxed": {
        "fingers": (14.0, 16.0, 12.0),
        "thumb": ((10.0, 10.0), (12.0, 6.0), (10.0, 4.0)),
    },
    "open": {
        "fingers": (0.0, 0.0, 0.0),
        "thumb": ((0.0, 0.0), (0.0, 0.0), (0.0, 0.0)),
    },
}


def aplicar_pose_maos_mpfb(
    rig,
    pose_mao_r: str = "grip",
    pose_mao_l: str = "cupped",
    compensar_rotacao_z: bool = False,
) -> dict:
    """Posa as 15 falanges de cada mao no rig MPFB2 (grip, cupped, relaxed, open)."""
    if rig is None or getattr(rig, "pose", None) is None:
        return {}
    modo_r = (pose_mao_r or "grip").strip().lower()
    modo_l = (pose_mao_l or "cupped").strip().lower()
    if modo_r not in _ANGULOS_DEDOS_POSE:
        modo_r = "grip"
    if modo_l not in _ANGULOS_DEDOS_POSE:
        modo_l = "cupped"

    # Apos exportar() aplicar rotation_euler.z = pi, o lado MPFB 'l' (+X pre-pi)
    # passa para -X_bl (Hand.R canônico), e 'r' (-X pre-pi) passa para +X_bl (Hand.L).
    lado_para_modo = (
        {"l": modo_r, "r": modo_l}
        if compensar_rotacao_z
        else {"r": modo_r, "l": modo_l}
    )

    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="POSE")
    pbones = rig.pose.bones

    for lado, modo in lado_para_modo.items():
        cfg = _ANGULOS_DEDOS_POSE[modo]
        ang_f = cfg["fingers"]
        ang_t = cfg["thumb"]
        sinal = 1.0 if lado == "r" else -1.0
        for fn in ("index", "middle", "ring", "pinky"):
            for idx, deg in enumerate(ang_f, 1):
                pb = pbones.get(f"{fn}_0{idx}_{lado}")
                if pb is not None:
                    pb.matrix_basis = Matrix.Rotation(math.radians(deg), 4, "X")
        for idx, (rx, rz) in enumerate(ang_t, 1):
            pb = pbones.get(f"thumb_0{idx}_{lado}")
            if pb is not None:
                pb.matrix_basis = (
                    Euler((math.radians(rx), 0.0, math.radians(rz * sinal)), "XYZ")
                    .to_matrix()
                    .to_4x4()
                )

    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.context.view_layer.update()

    mw = rig.matrix_world
    res: dict = {"pose_mao_r": modo_r, "pose_mao_l": modo_l}
    for lado_mpfb, chave_can in (
        (("l", "r"), ("r", "l")) if compensar_rotacao_z else (("r", "r"), ("l", "l"))
    ):
        hand_pb = pbones.get(f"hand_{lado_mpfb}")
        mid_pb = pbones.get(f"middle_03_{lado_mpfb}")
        m01_pb = pbones.get(f"middle_01_{lado_mpfb}")
        if hand_pb is not None and mid_pb is not None and m01_pb is not None:
            palma = mw @ ((hand_pb.head + m01_pb.head) * 0.5)
            ponta = mw @ mid_pb.tail
            res[f"dist_ponta_palma_{chave_can}_m"] = round(float((ponta - palma).length), 5)
    return res


def _assar_pose_em_malhas(malhas: list, rig) -> None:
    """Fixa a deformacao atual da armadura nas coordenadas locais das malhas (sem perder UV/materiais)."""
    if rig is None:
        return
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    for m_obj in malhas:
        if m_obj is None or getattr(m_obj, "type", None) != "MESH":
            continue
        ev = m_obj.evaluated_get(dg)
        me_eval = ev.to_mesh()
        if len(me_eval.vertices) == len(m_obj.data.vertices):
            for v_dst, v_src in zip(m_obj.data.vertices, me_eval.vertices):
                v_dst.co = v_src.co.copy()
            m_obj.data.update()
        ev.to_mesh_clear()


def _selecionar_skin_cc0(macro: dict) -> str | None:
    """Seleciona textura difusa anatomica CC0 de skins/ compativel com macro (genero/idade/etnia)."""
    gender = float(macro.get("gender", 0.0))
    age = float(macro.get("age", 0.45))
    race = macro.get("race") if isinstance(macro.get("race"), dict) else {}
    af = float(race.get("african", 0.0))
    as_ = float(race.get("asian", 0.0))
    eh_fem = gender >= 0.5
    eh_meia_idade = age >= 0.62

    if af >= 0.55:
        if eh_meia_idade:
            prefs = (
                ("middleage_african_female", "young_african_female")
                if eh_fem
                else ("middleage_african_male", "young_african_male")
            )
        else:
            prefs = (
                ("young_african_female", "middleage_african_female")
                if eh_fem
                else ("young_african_male", "middleage_african_male")
            )
    elif as_ >= 0.55:
        if eh_meia_idade:
            prefs = (
                ("middleage_asian_female", "young_asian_female")
                if eh_fem
                else ("middleage_asian_male", "young_asian_male")
            )
        else:
            prefs = (
                ("young_asian_female", "middleage_asian_female")
                if eh_fem
                else ("young_asian_male", "middleage_asian_male")
            )
    else:
        if eh_meia_idade:
            prefs = (
                ("middleage_caucasian_female", "young_caucasian_female2", "young_caucasian_female")
                if eh_fem
                else ("middleage_caucasian_male", "young_caucasian_male2", "young_caucasian_male")
            )
        else:
            prefs = (
                ("young_caucasian_female2", "young_caucasian_female", "middleage_caucasian_female")
                if eh_fem
                else ("young_caucasian_male2", "young_caucasian_male", "middleage_caucasian_male")
            )

    raizes = _raizes_categoria_mpfb("skins")
    for nome_pasta in prefs:
        for raiz in raizes:
            pasta = os.path.join(raiz, nome_pasta)
            if not os.path.isdir(pasta):
                continue
            for arq in sorted(os.listdir(pasta)):
                low = arq.lower()
                if low.endswith(".png") and ("diffuse" in low or low == f"{nome_pasta}.png"):
                    return os.path.join(pasta, arq)
    return None


def _gerar_pele_procedural_limpa(saida: str, tam: int, macro: dict, png_nome: str = "baseColor.png") -> str:
    """Fallback de pele anatomica limpa (sem franja preta na testa) quando pacote CC0 nao esta no disco."""
    race = macro.get("race") if isinstance(macro.get("race"), dict) else {}
    af = float(race.get("african", 0.35))
    as_ = float(race.get("asian", 0.15))
    r_base = max(0.32, min(0.86, 0.78 - 0.34 * af - 0.04 * as_))
    g_base = max(0.22, min(0.72, 0.58 - 0.28 * af - 0.02 * as_))
    b_base = max(0.16, min(0.62, 0.46 - 0.24 * af - 0.04 * as_))

    img = bpy.data.images.new("skin_procedural", width=tam, height=tam, alpha=True)
    buf = [1.0] * (tam * tam * 4)
    for y in range(tam):
        v = y / float(max(1, tam - 1))
        for x in range(tam):
            u = x / float(max(1, tam - 1))
            var = 0.018 * math.sin(u * 18.0) * math.cos(v * 18.0)
            r = max(0.15, min(0.95, r_base + var))
            g = max(0.12, min(0.88, g_base + var * 0.8))
            b = max(0.10, min(0.82, b_base + var * 0.6))
            # Leve rubor facial/labial suave sem escurecer testa
            if 0.38 <= u <= 0.62 and 0.66 <= v <= 0.76:
                r = min(0.95, r + 0.04)
                g = max(0.10, g - 0.01)
            idx = (y * tam + x) * 4
            buf[idx] = r
            buf[idx + 1] = g
            buf[idx + 2] = b
            buf[idx + 3] = 1.0
    img.pixels.foreach_set(buf)
    sc = bpy.context.scene
    ant_mode = sc.render.image_settings.color_mode
    sc.render.image_settings.color_mode = "RGBA"
    caminho = os.path.join(saida, png_nome)
    img.filepath_raw = caminho
    img.file_format = "PNG"
    img.save()
    sc.render.image_settings.color_mode = ant_mode
    img.pack()
    return caminho


def _criar_material_pbr(
    nome: str,
    cor_srgb: tuple[float, float, float],
    roughness: float = 0.62,
    metallic: float = 0.0,
    specular: float = 0.32,
    tex_path: str | None = None,
    tint_strength: float = 0.0,
    uv_scale: float = 1.0,
):
    """Cria material Principled BSDF com textura opcional (empacotada para glTF) e fallback limpo."""
    mat = bpy.data.materials.new(nome)
    mat.use_nodes = True
    mat.use_backface_culling = False
    nt = mat.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    if bsdf is None:
        bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Base Color"].default_value = _rgba_srgb_to_linear(cor_srgb)
    if "Roughness" in bsdf.inputs:
        bsdf.inputs["Roughness"].default_value = float(roughness)
    if "Metallic" in bsdf.inputs:
        bsdf.inputs["Metallic"].default_value = float(metallic)
    if "Specular IOR Level" in bsdf.inputs:
        bsdf.inputs["Specular IOR Level"].default_value = float(specular)

    if tex_path and os.path.isfile(tex_path):
        img = bpy.data.images.load(tex_path, check_existing=True)
        if tint_strength > 0.01:
            src_work = img.copy()
            if int(src_work.size[0]) > 512 or int(src_work.size[1]) > 512:
                src_work.scale(min(int(src_work.size[0]), 512), min(int(src_work.size[1]), 512))
            w_im, h_im = int(src_work.size[0]), int(src_work.size[1])
            px = list(src_work.pixels)
            bpy.data.images.remove(src_work)
            n_px = max(1, len(px) // 4)
            avg_lum = max(
                0.05,
                sum(0.2126 * px[i] + 0.7152 * px[i + 1] + 0.0722 * px[i + 2] for i in range(0, len(px), 4))
                / float(n_px),
            )
            tr, tg, tb = cor_srgb
            s = float(tint_strength)
            for k in range(0, len(px), 4):
                lum = 0.2126 * px[k] + 0.7152 * px[k + 1] + 0.0722 * px[k + 2]
                rel = max(0.35, min(1.55, lum / avg_lum))
                cr = min(1.0, tr * (0.28 + 0.72 * rel))
                cg = min(1.0, tg * (0.28 + 0.72 * rel))
                cb = min(1.0, tb * (0.28 + 0.72 * rel))
                px[k] = max(0.0, min(1.0, px[k] * (1.0 - s) + cr * s))
                px[k + 1] = max(0.0, min(1.0, px[k + 1] * (1.0 - s) + cg * s))
                px[k + 2] = max(0.0, min(1.0, px[k + 2] * (1.0 - s) + cb * s))
                px[k + 3] = 1.0
            novo_im = bpy.data.images.new(name=f"_tmp_{nome}_tex", width=w_im, height=h_im, alpha=True)
            novo_im.pixels.foreach_set(px)
            import tempfile

            fd_t, tmp_png = tempfile.mkstemp(prefix="f3d_body_tint_", suffix=".png")
            os.close(fd_t)
            try:
                sc = bpy.context.scene
                ant_cm = sc.render.image_settings.color_mode
                sc.render.image_settings.color_mode = "RGBA"
                novo_im.filepath_raw = tmp_png
                novo_im.file_format = "PNG"
                novo_im.save()
                sc.render.image_settings.color_mode = ant_cm
                bpy.data.images.remove(novo_im)
                carregada = bpy.data.images.load(tmp_png)
                carregada.name = f"{nome}_tex"
                try:
                    carregada.colorspace_settings.name = "sRGB"
                except Exception:
                    pass
                carregada.pack()
                img = carregada
            finally:
                if os.path.exists(tmp_png):
                    os.unlink(tmp_png)
        else:
            try:
                img.pack()
            except RuntimeError:
                pass
        tex_node = nt.nodes.new("ShaderNodeTexImage")
        tex_node.image = img
        if abs(float(uv_scale) - 1.0) > 1e-4:
            tc_node = nt.nodes.new("ShaderNodeTexCoord")
            mp_node = nt.nodes.new("ShaderNodeMapping")
            sc_v = float(uv_scale)
            mp_node.inputs["Scale"].default_value = (sc_v, sc_v, sc_v)
            nt.links.new(tc_node.outputs["UV"], mp_node.inputs["Vector"])
            nt.links.new(mp_node.outputs["Vector"], tex_node.inputs["Vector"])
        nt.links.new(tex_node.outputs["Color"], bsdf.inputs["Base Color"])
    return mat


def _fechar_olhos_manifold(eyes_obj) -> dict:
    """Fecha os 2 aneis traseiros de eyes/low-poly em malha 2-manifold estanque (G1=0)."""
    bm = bmesh.new()
    bm.from_mesh(eyes_obj.data)
    bmesh.ops.triangulate(bm, faces=list(bm.faces))
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1e-5)
    uv_layer = bm.loops.layers.uv.active or bm.loops.layers.uv.new("UVMap")

    # Fecha cada loop de borda conectado com um vertice central no fundo do globo ocular
    for _ in range(8):
        b_edges = [e for e in bm.edges if len(e.link_faces) == 1]
        if not b_edges:
            break
        e0 = b_edges[0]
        comp_v = set(e0.verts)
        comp_e = {e0}
        mudou = True
        while mudou:
            mudou = False
            for e in b_edges:
                if e not in comp_e and (e.verts[0] in comp_v or e.verts[1] in comp_v):
                    comp_e.add(e)
                    comp_v.update(e.verts)
                    mudou = True
        centro = sum((v.co for v in comp_v), Vector((0.0, 0.0, 0.0))) / float(len(comp_v))
        vc = bm.verts.new(centro)
        for e in comp_e:
            v_a, v_b = e.verts[0], e.verts[1]
            try:
                f = bm.faces.new((v_a, v_b, vc))
                for lp in f.loops:
                    lp[uv_layer].uv = (0.08, 0.08)
            except ValueError:
                pass

    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    nao_manifold = sum(1 for e in bm.edges if len(e.link_faces) != 2)
    tris = len(bm.faces)
    bm.to_mesh(eyes_obj.data)
    bm.free()
    eyes_obj.data.update()
    if nao_manifold > 0:
        return _preparar_cabelo_manifold(eyes_obj, 400)
    return {"triangulos": tris, "nao_manifold": nao_manifold, "degeneradas": 0}


def _preparar_camada_mhclo_manifold(
    camada_obj,
    target_tris: int,
    thickness: float = 0.0045,
    offset_normal: float = 0.0024,
) -> dict:
    """Converte roupa/sobrancelha .mhclo em camada 3D estanque (espessura >= 4mm, separacao >= 2mm)."""
    _limpar_nao_manifold_aberto(camada_obj)
    bm0 = bmesh.new()
    bm0.from_mesh(camada_obj.data)
    bmesh.ops.recalc_face_normals(bm0, faces=list(bm0.faces))
    bm0.normal_update()
    for v in bm0.verts:
        n = v.normal if v.normal.length > 1e-6 else Vector((0.0, -1.0, 0.0))
        v.co += n * offset_normal
    bm0.to_mesh(camada_obj.data)
    bm0.free()
    camada_obj.data.update()

    for _ in range(4):
        bm = bmesh.new()
        bm.from_mesh(camada_obj.data)
        t_cur = len(bm.faces)
        b_cur = sum(1 for e in bm.edges if len(e.link_faces) == 1)
        bm.free()
        est_solid = 2 * t_cur + 2 * b_cur
        if target_tris <= 0 or est_solid <= target_tris:
            break
        ratio = max(0.06, min(0.90, (target_tris * 0.88) / max(1, est_solid)))
        mod_d = camada_obj.modifiers.new("pre_dec", "DECIMATE")
        mod_d.ratio = ratio
        bpy.ops.object.select_all(action="DESELECT")
        bpy.context.view_layer.objects.active = camada_obj
        camada_obj.select_set(True)
        bpy.ops.object.modifier_apply(modifier=mod_d.name)
        _limpar_nao_manifold_aberto(camada_obj)

    mod = camada_obj.modifiers.new("Solidify", "SOLIDIFY")
    mod.thickness = max(0.0006, float(thickness))
    mod.offset = 1.0
    mod.use_rim = True
    mod.use_rim_only = False
    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = camada_obj
    camada_obj.select_set(True)
    bpy.ops.object.modifier_apply(modifier=mod.name)

    bm = bmesh.new()
    bm.from_mesh(camada_obj.data)
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
    bm.to_mesh(camada_obj.data)
    bm.free()
    camada_obj.data.update()
    if nao_manifold > 0:
        _limpar_nao_manifold_aberto(camada_obj)
    return {"triangulos": tris, "nao_manifold": nao_manifold, "degeneradas": degeneradas}


def _adicionar_tubo_contornado_manifold(
    bm,
    uv_layer,
    aneis_internos: list[list[Vector]],
    aneis_externos: list[list[Vector]],
    mat_index: int,
) -> None:
    """Cria casca tubular fechada 2-manifold (parede interna + externa + tampas superior/inferior)."""
    n_rings = len(aneis_internos)
    if n_rings < 2:
        return
    n_seg = len(aneis_internos[0])
    v_in = [[bm.verts.new(p) for p in ring] for ring in aneis_internos]
    v_out = [[bm.verts.new(p) for p in ring] for ring in aneis_externos]

    def _set_face_uv(face, uvs):
        face.material_index = mat_index
        for lp, uv_co in zip(face.loops, uvs):
            lp[uv_layer].uv = uv_co

    for r in range(n_rings - 1):
        v0 = r / float(n_rings - 1)
        v1 = (r + 1) / float(n_rings - 1)
        for s in range(n_seg):
            sn = (s + 1) % n_seg
            u0 = s / float(n_seg)
            u1 = (s + 1) / float(n_seg)
            # Parede externa
            f_out = bm.faces.new((v_out[r][s], v_out[r][sn], v_out[r + 1][sn], v_out[r + 1][s]))
            _set_face_uv(f_out, ((u0, v0), (u1, v0), (u1, v1), (u0, v1)))
            # Parede interna (orientacao oposta)
            f_in = bm.faces.new((v_in[r][sn], v_in[r][s], v_in[r + 1][s], v_in[r + 1][sn]))
            _set_face_uv(f_in, ((u1, v0), (u0, v0), (u0, v1), (u1, v1)))

    # Borda inferior (r = 0) e superior (r = n_rings - 1)
    for s in range(n_seg):
        sn = (s + 1) % n_seg
        u0 = s / float(n_seg)
        u1 = (s + 1) / float(n_seg)
        f_bot = bm.faces.new((v_in[0][s], v_in[0][sn], v_out[0][sn], v_out[0][s]))
        _set_face_uv(f_bot, ((u0, 0.0), (u1, 0.0), (u1, 0.04), (u0, 0.04)))
        top = n_rings - 1
        f_top = bm.faces.new((v_out[top][s], v_out[top][sn], v_in[top][sn], v_in[top][s]))
        _set_face_uv(f_top, ((u0, 0.96), (u1, 0.96), (u1, 1.0), (u0, 1.0)))


def _construir_sobreposicoes_medievais_3d(
    body_obj,
    mat_idx_tunic: int,
    mat_idx_leather: int,
    mat_idx_metal: int,
    rig=None,
    suit_obj=None,
):
    """Cria camadas 3D contornadas (tunica/jerkin, cinto com fivela de latao, braceletes e botas)."""
    pts = [v.co.copy() for v in body_obj.data.vertices]
    pts_ref_torso = list(pts)
    if suit_obj is not None and getattr(suit_obj, "data", None) is not None:
        pts_ref_torso.extend(v.co.copy() for v in suit_obj.data.vertices)
    z_min = min(p.z for p in pts)
    z_max = max(p.z for p in pts)
    h = max(0.5, z_max - z_min)

    bm = bmesh.new()
    uv_layer = bm.loops.layers.uv.new("UVMap")

    def _raios_elipticos_fatia(za: float, zb: float, x_lim: float, padrao_rx: float, padrao_ry: float):
        fatia = [p for p in pts_ref_torso if za <= p.z <= zb and abs(p.x) <= x_lim]
        if len(fatia) < 6:
            return 0.0, 0.0, padrao_rx, padrao_ry
        cx = 0.0
        cy = 0.5 * (min(p.y for p in fatia) + max(p.y for p in fatia))
        rx = min(0.132 * h, max(padrao_rx * 0.75, max(abs(p.x - cx) for p in fatia)))
        ry = min(0.105 * h, max(padrao_ry * 0.75, max(abs(p.y - cy) for p in fatia)))
        return cx, cy, rx, ry

    # 1. Tunica / Jerkin medieval contornado iniciando em zf=0.50 (dentro do cinto, nunca na virilha)
    z_fracs_tunica = (0.50, 0.54, 0.58, 0.63, 0.67)
    n_seg_t = 16
    tun_in: list[list[Vector]] = []
    tun_out: list[list[Vector]] = []
    for zf in z_fracs_tunica:
        zc = z_min + zf * h
        cx, cy, rx, ry = _raios_elipticos_fatia(
            zc - 0.020 * h, zc + 0.020 * h, 0.118 * h, 0.098 * h, 0.074 * h
        )
        flare = 0.0045
        thick = 0.0050
        ring_i = []
        ring_o = []
        for s in range(n_seg_t):
            ang = (2.0 * math.pi * s) / float(n_seg_t)
            ca, sa = math.cos(ang), math.sin(ang)
            ring_i.append(Vector((cx + (rx + flare) * ca, cy + (ry + flare) * sa, zc)))
            ring_o.append(
                Vector((cx + (rx + flare + thick) * ca, cy + (ry + flare + thick) * sa, zc))
            )
        tun_in.append(ring_i)
        tun_out.append(ring_o)
    _adicionar_tubo_contornado_manifold(bm, uv_layer, tun_in, tun_out, mat_idx_tunic)

    # 2. Cinto de couro pespontado em superelipse (cobre 100% os cantos diagonais do quadril sem expor pele)
    z_belt_lo = z_min + 0.476 * h
    z_belt_hi = z_min + 0.526 * h
    cx_b, cy_b, rx_b, ry_b = _raios_elipticos_fatia(
        z_belt_lo, z_belt_hi, 0.126 * h, 0.104 * h, 0.078 * h
    )
    belt_in: list[list[Vector]] = []
    belt_out: list[list[Vector]] = []
    for zc in (z_belt_lo, 0.5 * (z_belt_lo + z_belt_hi), z_belt_hi):
        ri = []
        ro = []
        for s in range(n_seg_t):
            ang = (2.0 * math.pi * s) / float(n_seg_t)
            ca, sa = math.cos(ang), math.sin(ang)
            sup_b = (abs(ca) ** 2.3 + abs(sa) ** 2.3) ** (-1.0 / 2.3)
            ux_b, uy_b = ca * sup_b, sa * sup_b
            ri.append(Vector((cx_b + (rx_b + 0.0155) * ux_b, cy_b + (ry_b + 0.0155) * uy_b, zc)))
            ro.append(Vector((cx_b + (rx_b + 0.0225) * ux_b, cy_b + (ry_b + 0.0225) * uy_b, zc)))
        belt_in.append(ri)
        belt_out.append(ro)
    _adicionar_tubo_contornado_manifold(bm, uv_layer, belt_in, belt_out, mat_idx_leather)

    # 3. Fivela frontal de latao/bronze (em -Y no espaco MPFB pre-exportacao -> +Y_bl apos Z=pi)
    z_bm = 0.5 * (z_belt_lo + z_belt_hi)
    y_frente = cy_b - (ry_b + 0.0240)
    f_in: list[list[Vector]] = []
    f_out: list[list[Vector]] = []
    for dy_i, dy_o in ((0.002, -0.006), (-0.002, -0.011)):
        yi = y_frente + dy_i
        yo = y_frente + dy_o
        f_in.append([
            Vector((-0.018, yi, z_bm - 0.016)),
            Vector((0.018, yi, z_bm - 0.016)),
            Vector((0.018, yi, z_bm + 0.016)),
            Vector((-0.018, yi, z_bm + 0.016)),
        ])
        f_out.append([
            Vector((-0.032, yo, z_bm - 0.027)),
            Vector((0.032, yo, z_bm - 0.027)),
            Vector((0.032, yo, z_bm + 0.027)),
            Vector((-0.032, yo, z_bm + 0.027)),
        ])
    _adicionar_tubo_contornado_manifold(bm, uv_layer, f_in, f_out, mat_idx_metal)

    # 4. Braceletes de couro nos antebracos (ancorados exatamente em lowerarm_l/lowerarm_r quando rig presente)
    n_seg_b = 10
    for lado_b, sinal_x in (("r", -1.0), ("l", 1.0)):
        p_elb = None
        p_wri = None
        if rig is not None:
            for cand_b in (f"lowerarm_{lado_b}", f"LowerArm.{lado_b.upper()}"):
                if cand_b in rig.pose.bones:
                    pb_la = rig.pose.bones[cand_b]
                    p_elb = rig.matrix_world @ pb_la.head
                    p_wri = rig.matrix_world @ pb_la.tail
                    break
        if p_elb is None or p_wri is None:
            faixa_fb = [
                p
                for p in pts
                if 0.16 * h <= p.x * sinal_x <= 0.27 * h and z_min + 0.60 * h <= p.z <= z_min + 0.74 * h
            ]
            if len(faixa_fb) >= 10:
                faixa_fb.sort(key=lambda p: p.x * sinal_x)
                p_elb = faixa_fb[int(0.20 * len(faixa_fb))]
                p_wri = faixa_fb[int(0.82 * len(faixa_fb))]
        if p_elb is not None and p_wri is not None:
            eixo_a = p_wri - p_elb
            len_a = eixo_a.length
            if len_a > 0.04:
                u_dir = eixo_a / len_a
                v_dir = u_dir.cross(Vector((0.0, 1.0, 0.0)))
                if v_dir.length < 1e-4:
                    v_dir = u_dir.cross(Vector((0.0, 0.0, 1.0)))
                v_dir.normalize()
                w_dir = u_dir.cross(v_dir).normalized()
                br_in: list[list[Vector]] = []
                br_out: list[list[Vector]] = []
                for t_frac, r_base in ((0.30, 0.040), (0.54, 0.036), (0.76, 0.033)):
                    centro_a = p_elb.lerp(p_wri, t_frac)
                    perto = [
                        p
                        for p in pts
                        if abs((p - centro_a).dot(u_dir)) <= 0.022
                        and math.hypot((p - centro_a).dot(v_dir), (p - centro_a).dot(w_dir)) <= 0.056
                    ]
                    if len(perto) >= 4:
                        centro_a = sum(perto, Vector((0.0, 0.0, 0.0))) / float(len(perto))
                        r_med = min(
                            0.046,
                            max(
                                0.026,
                                max(
                                    math.hypot((p - centro_a).dot(v_dir), (p - centro_a).dot(w_dir))
                                    for p in perto
                                ),
                            ),
                        )
                    else:
                        r_med = r_base
                    r_i = r_med + 0.0040
                    r_o = r_i + 0.0045
                    ri_ring = []
                    ro_ring = []
                    for s in range(n_seg_b):
                        ang = (2.0 * math.pi * s) / float(n_seg_b)
                        radial = v_dir * math.cos(ang) + w_dir * math.sin(ang)
                        ri_ring.append(centro_a + radial * r_i)
                        ro_ring.append(centro_a + radial * r_o)
                    br_in.append(ri_ring)
                    br_out.append(ro_ring)
                _adicionar_tubo_contornado_manifold(bm, uv_layer, br_in, br_out, mat_idx_leather)

    # 5. Canos/punhos dobrados de botas de couro nas canelas (iniciando em zf=0.045 junto ao sapato)
    n_seg_leg = 12
    for sinal_x in (-1.0, 1.0):
        boot_in: list[list[Vector]] = []
        boot_out: list[list[Vector]] = []
        for zf, cuff_extra in (
            (0.045, 0.011),
            (0.095, 0.012),
            (0.155, 0.014),
            (0.210, 0.016),
            (0.250, 0.019),
        ):
            zc = z_min + zf * h
            fatia_l = [
                p
                for p in pts
                if zc - 0.02 * h <= p.z <= zc + 0.02 * h and p.x * sinal_x >= 0.01 * h
            ]
            if len(fatia_l) >= 4:
                cxl = 0.5 * (min(p.x for p in fatia_l) + max(p.x for p in fatia_l))
                cyl = 0.5 * (min(p.y for p in fatia_l) + max(p.y for p in fatia_l))
                rxl = max(0.042, max(abs(p.x - cxl) for p in fatia_l))
                ryl = max(0.045, max(abs(p.y - cyl) for p in fatia_l))
            else:
                cxl, cyl, rxl, ryl = sinal_x * 0.068 * h, 0.0, 0.048, 0.052
            ri_l = []
            ro_l = []
            for s in range(n_seg_leg):
                ang = (2.0 * math.pi * s) / float(n_seg_leg)
                ca, sa = math.cos(ang), math.sin(ang)
                ri_l.append(
                    Vector((cxl + (rxl + cuff_extra) * ca, cyl + (ryl + cuff_extra) * sa, zc))
                )
                ro_l.append(
                    Vector(
                        (
                            cxl + (rxl + cuff_extra + 0.005) * ca,
                            cyl + (ryl + cuff_extra + 0.005) * sa,
                            zc,
                        )
                    )
                )
            boot_in.append(ri_l)
            boot_out.append(ro_l)
        _adicionar_tubo_contornado_manifold(bm, uv_layer, boot_in, boot_out, mat_idx_leather)

    bmesh.ops.triangulate(bm, faces=list(bm.faces))
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    me_ov = bpy.data.meshes.new("camadas_medievais_3d")
    for _ in range(3):
        me_ov.materials.append(None)
    bm.to_mesh(me_ov)
    bm.free()
    ov_obj = bpy.data.objects.new("camadas_medievais_3d", me_ov)
    bpy.context.collection.objects.link(ov_obj)
    return ov_obj


def _garantir_g1_pos_join(obj) -> dict:
    """Garante 0 arestas nao-manifold mesmo apos soldagem G1 (1e-5 m) do qc.topologia."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.triangulate(bm, faces=list(bm.faces))
    bm.normal_update()

    # Desloca vertices de ilhas distintas que caiam na mesma celula de 1e-4 m
    celulas: dict[tuple[int, int, int], list] = {}
    for v in bm.verts:
        chave = (int(round(v.co.x * 20000.0)), int(round(v.co.y * 20000.0)), int(round(v.co.z * 20000.0)))
        celulas.setdefault(chave, []).append(v)
    for vs in celulas.values():
        if len(vs) > 1:
            for idx, v in enumerate(vs[1:], 1):
                n = v.normal if v.normal.length > 1e-6 else Vector((0.0, -1.0, 0.0))
                v.co += n * (0.00025 * idx)

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
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
    if nao_manifold > 0:
        _limpar_nao_manifold_aberto(obj)
        bm2 = bmesh.new()
        bm2.from_mesh(obj.data)
        nao_manifold = sum(1 for e in bm2.edges if len(e.link_faces) != 2)
        degeneradas = sum(1 for f in bm2.faces if f.calc_area() < 1e-12)
        tris = len(bm2.faces)
        bm2.free()
    return {"triangulos": tris, "nao_manifold": nao_manifold, "degeneradas": degeneradas}


def _unificar_atlas_multicamadas(obj, saida: str, tex_px: int) -> str:
    """Empacota materiais multicamadas em 1 atlas UV baseColor.png e 1 material (materiais_max <= 1)."""
    if not obj.data.uv_layers:
        obj.data.uv_layers.new(name="UVMap")
    uv_data = obj.data.uv_layers[0].data
    mats = list(obj.data.materials)
    n_mats = max(1, len(mats))

    # Grade 2x4: metade esquerda [0.0..0.5, 0.0..1.0] dedicada a skin (preserva resolucao facial!),
    # metade direita dividida em ate 8 celulas para olhos, roupas, couro, metal e cabelo.
    tiles: list[tuple[float, float, float, float]] = [(0.002, 0.496, 0.002, 0.996)]
    for idx in range(1, max(2, n_mats)):
        col = (idx - 1) % 2
        row = (idx - 1) // 2
        u0 = 0.502 + col * 0.248
        v0 = 0.002 + (row % 4) * 0.248
        tiles.append((u0, 0.244, v0, 0.244))

    for poly in obj.data.polygons:
        mi = max(0, min(len(tiles) - 1, int(poly.material_index)))
        u0, uw, v0, vh = tiles[mi]
        for li in poly.loop_indices:
            u = float(uv_data[li].uv[0]) % 1.0
            v = float(uv_data[li].uv[1]) % 1.0
            uv_data[li].uv = (u0 + u * uw, v0 + v * vh)

    buf = [0.75, 0.55, 0.42, 1.0] * (tex_px * tex_px)
    for mi, mat in enumerate(mats):
        if mi >= len(tiles) or mat is None:
            continue
        u0, uw, v0, vh = tiles[mi]
        x0 = max(0, int(u0 * tex_px))
        x1 = min(tex_px, int((u0 + uw) * tex_px))
        y0 = max(0, int(v0 * tex_px))
        y1 = min(tex_px, int((v0 + vh) * tex_px))
        tw = max(1, x1 - x0)
        th = max(1, y1 - y0)

        img_m = None
        cor_m = (0.65, 0.50, 0.40, 1.0)
        if mat.use_nodes:
            bsdf = mat.node_tree.nodes.get("Principled BSDF")
            if bsdf is not None:
                c_def = bsdf.inputs["Base Color"].default_value
                cor_m = (float(c_def[0]) ** (1.0 / 2.2), float(c_def[1]) ** (1.0 / 2.2), float(c_def[2]) ** (1.0 / 2.2), 1.0)
            for n in mat.node_tree.nodes:
                if n.type == "TEX_IMAGE" and n.image is not None:
                    img_m = n.image
                    break

        if img_m is not None:
            copia = img_m.copy()
            copia.scale(tw, th)
            px_m = list(copia.pixels)
            bpy.data.images.remove(copia)
            for ty in range(th):
                for tx in range(tw):
                    src = (ty * tw + tx) * 4
                    dst = ((y0 + ty) * tex_px + (x0 + tx)) * 4
                    buf[dst : dst + 4] = px_m[src : src + 4]
        else:
            for ty in range(th):
                for tx in range(tw):
                    dst = ((y0 + ty) * tex_px + (x0 + tx)) * 4
                    buf[dst : dst + 4] = cor_m

    caminho = os.path.join(saida, "baseColor.png")
    img_atlas = bpy.data.images.new("atlas_multicamadas", width=tex_px, height=tex_px, alpha=True)
    img_atlas.pixels.foreach_set(buf)
    sc = bpy.context.scene
    ant_mode = sc.render.image_settings.color_mode
    sc.render.image_settings.color_mode = "RGBA"
    img_atlas.filepath_raw = caminho
    img_atlas.file_format = "PNG"
    img_atlas.save()
    sc.render.image_settings.color_mode = ant_mode
    img_atlas.pack()

    mat_unif = _criar_material_pbr("skin", (0.78, 0.58, 0.46), roughness=0.62, specular=0.32, tex_path=caminho)
    obj.data.materials.clear()
    obj.data.materials.append(mat_unif)
    for poly in obj.data.polygons:
        poly.material_index = 0
    return caminho


def vestir_e_texturizar_camadas_cc0(
    obj,
    rig,
    saida: str,
    tam: int,
    macro: dict | None = None,
    job: dict | None = None,
    hair_obj=None,
    estilo_cabelo: str = "",
) -> tuple[str, dict]:
    """Aplica pele anatomica CC0, olhos/sobrancelhas 3D, roupas .mhclo e armadura leve 3D contornada."""
    macro_ef = dict(MACRO_PADRAO)
    if macro:
        macro_ef.update(macro)
    job_ef = job or {}
    corpo_nu = bool(job_ef.get("corpo_nu") is True)
    limite_total = int(job_ef.get("limite_triangulos") or 12000)
    materiais_max = int(job_ef.get("materiais_max") or 8)
    pose_mao_r = str(job_ef.get("pose_mao_r") or "grip").strip()
    pose_mao_l = str(job_ef.get("pose_mao_l") or "cupped").strip()

    extraido_dir = _garantir_pacote_mpfb_extraido()
    HumanService, _ = _mpfb()

    # 1. Carrega ativos 3D .mhclo (olhos, sobrancelhas e trajes base) ANTES de limpar_helpers(obj)
    eyes_obj = None
    brow_obj = None
    suit_obj = None
    shoes_obj = None
    tem_malha_integra = len(obj.data.vertices) == 19158

    if tem_malha_integra:
        eyes_path = _encontrar_ativo_mpfb("eyes", "low-poly", ".mhclo")
        if eyes_path:
            try:
                eyes_obj = HumanService.add_mhclo_asset(
                    eyes_path,
                    obj,
                    asset_type="Eyes",
                    subdiv_levels=0,
                    material_type="GAMEENGINE",
                    set_up_rigging=True,
                )
            except Exception:
                eyes_obj = None

        brow_path = _encontrar_ativo_mpfb("eyebrows", "eyebrow001", ".mhclo")
        if brow_path:
            try:
                brow_obj = HumanService.add_mhclo_asset(
                    brow_path,
                    obj,
                    asset_type="Eyebrows",
                    subdiv_levels=0,
                    material_type="GAMEENGINE",
                    set_up_rigging=True,
                )
            except Exception:
                brow_obj = None

        if not corpo_nu:
            eh_fem = float(macro_ef.get("gender", 0.0)) >= 0.5
            suit_nome = "female_casualsuit01" if eh_fem else "male_casualsuit04"
            suit_path = _encontrar_ativo_mpfb("clothes", suit_nome, ".mhclo")
            if suit_path:
                try:
                    suit_obj = HumanService.add_mhclo_asset(
                        suit_path,
                        obj,
                        asset_type="Clothes",
                        subdiv_levels=0,
                        material_type="GAMEENGINE",
                        set_up_rigging=True,
                    )
                except Exception:
                    suit_obj = None

            shoes_path = (
                _encontrar_ativo_mpfb("clothes", "shoes01", ".mhclo")
                or _encontrar_ativo_mpfb("clothes", "shoes03", ".mhclo")
            )
            if shoes_path:
                try:
                    shoes_obj = HumanService.add_mhclo_asset(
                        shoes_path,
                        obj,
                        asset_type="Clothes",
                        subdiv_levels=0,
                        material_type="GAMEENGINE",
                        set_up_rigging=True,
                    )
                except Exception:
                    shoes_obj = None

        # Remove modificadores MASK adicionados pelo MPFB2 para manter o corpo 2-manifold fechado
        for mod in list(obj.modifiers):
            if mod.type == "MASK":
                obj.modifiers.remove(mod)

        # Quando eyes/low-poly 3D real foi carregado, remove tb os olhos helper internos do base.obj
        vg = {g.name: g.index for g in obj.vertex_groups}
        if eyes_obj is not None:
            bm_h = bmesh.new()
            bm_h.from_mesh(obj.data)
            dl_h = bm_h.verts.layers.deform.active
            ids_eye_h = {vg.get("helper-l-eye"), vg.get("helper-r-eye")} - {None}
            if dl_h is not None and ids_eye_h:
                v_eyes = [v for v in bm_h.verts if set(v[dl_h].keys()) & ids_eye_h]
                if v_eyes:
                    bmesh.ops.delete(bm_h, geom=v_eyes, context="VERTS")
                    bm_h.to_mesh(obj.data)
            bm_h.free()
        limpar_helpers(obj)

    # 2. Posa falanges das maos (grip na direita, cupped na esquerda) e fixa nas malhas
    info_maos = aplicar_pose_maos_mpfb(
        rig,
        pose_mao_r=pose_mao_r,
        pose_mao_l=pose_mao_l,
        compensar_rotacao_z=True,
    )
    malhas_rigadas = [m for m in (obj, eyes_obj, brow_obj, suit_obj, shoes_obj, hair_obj) if m is not None]
    if not bool(job_ef.get("rig", False)):
        _assar_pose_em_malhas(malhas_rigadas, rig)

    # 3. Coloca corpo e camadas auxiliares no espaco em metros (escala 1.0 aplicada, pre-rotacao Z=pi)
    def _destacar_para_metros(m_obj) -> None:
        if m_obj is None:
            return
        for mod in list(m_obj.modifiers):
            if mod.type == "ARMATURE":
                m_obj.modifiers.remove(mod)
        mw = m_obj.matrix_world.copy()
        m_obj.parent = None
        m_obj.matrix_world = mw
        bpy.ops.object.select_all(action="DESELECT")
        bpy.context.view_layer.objects.active = m_obj
        m_obj.select_set(True)
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

    for m_obj in (obj, eyes_obj, brow_obj, suit_obj, shoes_obj, hair_obj):
        _destacar_para_metros(m_obj)

    # 4. Textura de pele anatomica CC0 (ou fallback procedural limpo) -> <saida>/baseColor.png
    skin_src = _selecionar_skin_cc0(macro_ef)
    tex_base_path = os.path.join(saida, "baseColor.png")
    if skin_src and os.path.isfile(skin_src):
        img_skin = bpy.data.images.load(skin_src, check_existing=True).copy()
        img_skin.name = "cc0_skin_baseColor"
        if int(img_skin.size[0]) != tam or int(img_skin.size[1]) != tam:
            img_skin.scale(tam, tam)
        sc = bpy.context.scene
        ant_mode = sc.render.image_settings.color_mode
        sc.render.image_settings.color_mode = "RGBA"
        img_skin.filepath_raw = tex_base_path
        img_skin.file_format = "PNG"
        img_skin.save()
        sc.render.image_settings.color_mode = ant_mode
        img_skin.pack()
        skin_origem = os.path.basename(os.path.dirname(skin_src))
    else:
        tex_base_path = _gerar_pele_procedural_limpa(saida, tam, macro_ef, png_nome="baseColor.png")
        skin_origem = "procedural_anatomica"

    dir_pbr = os.path.join(os.path.dirname(os.path.abspath(__file__)), "textures_pbr")
    tex_tunic = os.path.join(dir_pbr, "linen_tunic_albedo.png")
    tex_leather = os.path.join(dir_pbr, "leather_saddle_albedo.png")
    tex_metal = os.path.join(dir_pbr, "bronze_filigree_albedo.png")

    cor_tunica = _hex_to_rgb_srgb(str(job_ef.get("cor") or "")) or (_hex_to_rgb_srgb("#23334A") or (0.137, 0.200, 0.290))
    cor_calca = _hex_to_rgb_srgb("#24211F") or (0.141, 0.129, 0.122)

    mat_skin = _criar_material_pbr(
        "skin", (0.78, 0.58, 0.46), roughness=0.62, metallic=0.0, specular=0.32, tex_path=tex_base_path
    )
    mat_tunic = _criar_material_pbr(
        "tunic",
        cor_tunica,
        roughness=0.78,
        metallic=0.0,
        specular=0.20,
        tex_path=tex_tunic if os.path.isfile(tex_tunic) else None,
        tint_strength=0.78,
        uv_scale=3.8,
    )
    mat_trousers = _criar_material_pbr(
        "trousers",
        cor_calca,
        roughness=0.85,
        metallic=0.0,
        specular=0.14,
        tex_path=tex_tunic if os.path.isfile(tex_tunic) else None,
        tint_strength=0.88,
        uv_scale=3.8,
    )
    mat_leather = _criar_material_pbr(
        "leather",
        (0.36, 0.21, 0.11),
        roughness=0.58,
        metallic=0.04,
        specular=0.28,
        tex_path=tex_leather if os.path.isfile(tex_leather) else None,
        tint_strength=0.35,
        uv_scale=2.4,
    )
    mat_metal = _criar_material_pbr(
        "metal",
        (0.78, 0.61, 0.28),
        roughness=0.28,
        metallic=0.88,
        specular=0.50,
        tex_path=tex_metal if os.path.isfile(tex_metal) else None,
        tint_strength=0.20,
    )

    tex_eyes = None
    if eyes_obj is not None:
        for m in eyes_obj.data.materials:
            if m and m.use_nodes:
                for n in m.node_tree.nodes:
                    if n.type == "TEX_IMAGE" and n.image is not None and n.image.filepath:
                        cand_e = bpy.path.abspath(n.image.filepath)
                        if os.path.isfile(cand_e):
                            tex_eyes = cand_e
                            break
    if not tex_eyes:
        for r_eye in _raizes_categoria_mpfb("eyes"):
            cand_b = os.path.join(r_eye, "materials", "brown_eye.png")
            if os.path.isfile(cand_b):
                tex_eyes = cand_b
                break
    mat_eyes = _criar_material_pbr(
        "eyes", (0.35, 0.52, 0.68), roughness=0.12, metallic=0.0, specular=0.55, tex_path=tex_eyes
    )

    obj.data.materials.clear()
    obj.data.materials.append(mat_skin)
    for p in obj.data.polygons:
        p.material_index = 0

    # 5. Prepara camadas 3D manifold dentro do orcamento de triangulos
    camadas_join: list = []
    tris_extras = 0
    nomes_camadas: list[str] = ["skin"]

    if eyes_obj is not None:
        topo_e = _fechar_olhos_manifold(eyes_obj)
        eyes_obj.data.materials.clear()
        eyes_obj.data.materials.append(mat_eyes)
        for p in eyes_obj.data.polygons:
            p.material_index = 0
        camadas_join.append(eyes_obj)
        tris_extras += topo_e["triangulos"]
        nomes_camadas.append("eyes/low-poly")

    if brow_obj is not None:
        brow_png_fb = None
        if brow_path:
            cand_bp = os.path.join(os.path.dirname(brow_path), "eyebrow001.png")
            if os.path.isfile(cand_bp):
                brow_png_fb = cand_bp
        topo_b = _preparar_camada_mhclo_manifold(
            brow_obj, target_tris=360, thickness=0.0008, offset_normal=0.0009
        )
        _preparar_textura_e_material_cabelo(
            brow_obj,
            "eyebrow001",
            saida,
            min(tam, 512),
            cor_hex="#261810",
            material_modo="alpha_clip",
            png_nome="brow_baseColor.png",
            alpha_cutoff=0.45,
            fallback_tex_path=brow_png_fb,
            mat_nome="brow",
        )
        for p in brow_obj.data.polygons:
            p.material_index = 0
        camadas_join.append(brow_obj)
        tris_extras += topo_b["triangulos"]
        nomes_camadas.append("eyebrows/eyebrow001")

    if not corpo_nu:
        if suit_obj is not None:
            # Apara barra da calca bem fundo dentro da bota (< 0.14*h) e recolhe 0.78 radial ate 0.250*h
            b_zs = [v.co.z for v in obj.data.vertices]
            bz_min = min(b_zs)
            bh = max(0.5, max(b_zs) - bz_min)
            z_trim_bota = bz_min + 0.140 * bh
            z_corte_bota = bz_min + 0.250 * bh
            z_corte_cinto = bz_min + 0.500 * bh

            bm_suit = bmesh.new()
            bm_suit.from_mesh(suit_obj.data)
            faces_boot = [f for f in bm_suit.faces if f.calc_center_median().z < z_trim_bota]
            if faces_boot:
                bmesh.ops.delete(bm_suit, geom=faces_boot, context="FACES")
                soltos_s = [v for v in bm_suit.verts if not v.link_faces]
                if soltos_s:
                    bmesh.ops.delete(bm_suit, geom=soltos_s, context="VERTS")
            pernas_pts_l = [v.co for v in obj.data.vertices if v.co.x >= 0.01 * bh and v.co.z <= z_corte_bota + 0.03]
            pernas_pts_r = [v.co for v in obj.data.vertices if v.co.x <= -0.01 * bh and v.co.z <= z_corte_bota + 0.03]
            for sv in bm_suit.verts:
                if sv.co.z < z_corte_bota:
                    ref_leg = pernas_pts_l if sv.co.x >= 0.0 else pernas_pts_r
                    fat = [p for p in ref_leg if abs(p.z - sv.co.z) <= 0.025 * bh]
                    if fat:
                        cxl = 0.5 * (min(p.x for p in fat) + max(p.x for p in fat))
                        cyl = 0.5 * (min(p.y for p in fat) + max(p.y for p in fat))
                    else:
                        cxl = (0.068 * bh) if sv.co.x >= 0.0 else (-0.068 * bh)
                        cyl = 0.0
                    # Afunda 0.78 dentro da bota mas abre suavemente para 0.94 na boca da bota (0.25*h)
                    t_rim = max(0.0, min(1.0, (sv.co.z - (bz_min + 0.19 * bh)) / (0.06 * bh)))
                    fator_r = 0.78 + 0.16 * t_rim
                    sv.co.x = cxl + (sv.co.x - cxl) * fator_r
                    sv.co.y = cyl + (sv.co.y - cyl) * fator_r
            bm_suit.to_mesh(suit_obj.data)
            bm_suit.free()
            suit_obj.data.update()

            topo_s = _preparar_camada_mhclo_manifold(
                suit_obj, target_tris=1350, thickness=0.0040, offset_normal=0.0018
            )
            suit_obj.data.materials.clear()
            suit_obj.data.materials.append(mat_tunic)
            suit_obj.data.materials.append(mat_trousers)
            for p in suit_obj.data.polygons:
                p.material_index = 1 if p.center.z < z_corte_cinto else 0
            camadas_join.append(suit_obj)
            tris_extras += topo_s["triangulos"]
            nomes_camadas.append("clothes/suit")

        if shoes_obj is not None:
            topo_sh = _preparar_camada_mhclo_manifold(
                shoes_obj, target_tris=520, thickness=0.0045, offset_normal=0.0025
            )
            shoes_obj.data.materials.clear()
            shoes_obj.data.materials.append(mat_leather)
            for p in shoes_obj.data.polygons:
                p.material_index = 0
            camadas_join.append(shoes_obj)
            tris_extras += topo_sh["triangulos"]
            nomes_camadas.append("clothes/shoes")

        ov_obj = _construir_sobreposicoes_medievais_3d(obj, 0, 1, 2, rig=rig, suit_obj=suit_obj)
        mats_poly = [int(p.material_index) for p in ov_obj.data.polygons]
        ov_obj.data.materials.clear()
        ov_obj.data.materials.append(mat_tunic)
        ov_obj.data.materials.append(mat_leather)
        ov_obj.data.materials.append(mat_metal)
        for p, mi in zip(ov_obj.data.polygons, mats_poly):
            p.material_index = mi
        camadas_join.append(ov_obj)
        tris_extras += len(ov_obj.data.polygons)
        nomes_camadas.extend(["tunic_jerkin_3d", "leather_belt_bracers_boots_3d", "brass_buckle_3d"])

    info_cabelo = {}
    if hair_obj is not None:
        cab_info = _info_cabeca(obj)
        info_cabelo = _info_cabelo(hair_obj, obj, cab_info)
        hair_budget = min(max(1400, limite_total // 4), 3200)
        topo_h = _preparar_cabelo_manifold(hair_obj, hair_budget)
        _preparar_textura_e_material_cabelo(
            hair_obj,
            estilo_cabelo or "hair",
            saida,
            tam,
            str(job_ef.get("cor_cabelo") or ""),
            str(job_ef.get("material_cabelo") or "alpha_clip"),
            png_nome="hair_baseColor.png",
        )
        camadas_join.append(hair_obj)
        tris_extras += topo_h["triangulos"]
        nomes_camadas.append(f"hair/{estilo_cabelo or 'hair'}")

    # 6. Decima corpo protegendo rosto e maos para respeitar limite_triangulos total
    body_budget = max(2600, limite_total - tris_extras - 80)
    tris_body = sum(len(p.vertices) - 2 for p in obj.data.polygons)
    if tris_body > body_budget:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import postprocess as _pp  # noqa: E402

        _pp.decimar(obj, body_budget, proteger_cabeca_maos=True)

    # Uniformiza nome da UV layer e limpa color_attributes antes do join()
    uv_nome = obj.data.uv_layers[0].name if obj.data.uv_layers else "UVMap"
    for m_obj in [obj, *camadas_join]:
        if not m_obj.data.uv_layers:
            m_obj.data.uv_layers.new(name=uv_nome)
        else:
            m_obj.data.uv_layers[0].name = uv_nome
        while getattr(m_obj.data, "color_attributes", None) and len(m_obj.data.color_attributes) > 0:
            m_obj.data.color_attributes.remove(m_obj.data.color_attributes[0])

    if camadas_join:
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        for c_obj in camadas_join:
            c_obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.join()

    topo_final = _garantir_g1_pos_join(obj)
    if materiais_max <= 1 and len(obj.data.materials) > 1:
        tex_base_path = _unificar_atlas_multicamadas(obj, saida, tam)

    rel_camadas = {
        "modo_textura": "camadas_cc0_3d",
        "projetar_foto_2d": False,
        "corpo_nu": corpo_nu,
        "skin_origem": skin_origem,
        "pacote_cc0_extraido": bool(extraido_dir),
        "camadas": nomes_camadas,
        "materiais": [m.name for m in obj.data.materials if m is not None],
        "maos": info_maos,
        "topologia": topo_final,
    }
    if info_cabelo:
        rel_camadas["cabelo"] = {"estilo": estilo_cabelo, **info_cabelo}
    return tex_base_path, rel_camadas


def exportar(obj, rig, saida: str, manter_rig: bool, nome_glb: str = "template_body.glb") -> str:
    if rig is not None:
        for pb in rig.pose.bones:
            pb.matrix_basis = Matrix.Identity(4)
        bpy.context.view_layer.update()
    bpy.ops.object.select_all(action="DESELECT")
    if manter_rig and rig is not None:
        rig.rotation_euler.z = math.pi
        rig.select_set(True)
        obj.select_set(True)
        for filho in rig.children:
            filho.select_set(True)
        bpy.context.view_layer.objects.active = rig
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
        bpy.ops.object.select_all(action="DESELECT")
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
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import postprocess as _pp  # noqa: E402

    if obj is not None and getattr(obj, "type", None) == "MESH":
        _pp.suavizar_por_angulo(obj, angulo_graus=65.0)
    if manter_rig and rig is not None:
        for filho in rig.children:
            if filho is not obj and getattr(filho, "type", None) == "MESH":
                _pp.suavizar_por_angulo(filho, angulo_graus=65.0)
    bpy.ops.object.select_all(action="DESELECT")
    if manter_rig and rig is not None:
        rig.select_set(True)
        for filho in rig.children:
            filho.select_set(True)
    obj.select_set(True)
    glb = os.path.join(saida, nome_glb)
    export_kw = {
        "filepath": glb,
        "use_selection": True,
        "export_format": "GLB",
        "export_animations": False,
        "export_normals": True,
        "export_tangents": True,
    }
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

    if modo == "cabelo":
        limpar_helpers(obj)
        info_cabeca = _info_cabeca(obj)
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

    if not bool(job.get("projetar_foto_2d") is True):
        tex, info_camadas = vestir_e_texturizar_camadas_cc0(
            obj,
            rig,
            saida,
            int(job.get("textura", 1024)),
            macro=macro,
            job=job,
            hair_obj=hair_obj,
            estilo_cabelo=estilo,
        )
        info_cabeca = _info_cabeca(obj)
        glb = exportar(obj, rig, saida, bool(job.get("rig", False)))
        topo_rel = info_camadas.get("topologia") or {}
        rel = {
            "glb": glb,
            "baseColor": tex,
            "braco_graus": 35.0,
            "antebraco_graus": 0.0,
            "perna_graus": 0.0,
            "iou_silhueta": None,
            "triangulos": sum(len(p.vertices) - 2 for p in obj.data.polygons),
            "nao_manifold": int(topo_rel.get("nao_manifold", 0)),
            "degeneradas": int(topo_rel.get("degeneradas", 0)),
            "template": "mpfb2 (CC0)",
            "macro": macro,
            "cabeca": info_cabeca,
            "camadas_cc0": info_camadas,
            "maos": info_camadas.get("maos") or {},
        }
        if info_camadas.get("cabelo"):
            rel["cabelo"] = info_camadas["cabelo"]
        json.dump(rel, open(os.path.join(saida, "relatorio.json"), "w"), indent=2)
        print(
            "TEMPLATE_OK",
            json.dumps(
                {
                    "modo_textura": "camadas_cc0_3d",
                    "triangulos": rel["triangulos"],
                    "nao_manifold": rel["nao_manifold"],
                }
            ),
        )
        return 0

    limpar_helpers(obj)
    info_cabeca = _info_cabeca(obj)
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
    info_maos = aplicar_pose_maos_mpfb(
        rig,
        pose_mao_r=str(job.get("pose_mao_r") or "grip"),
        pose_mao_l=str(job.get("pose_mao_l") or "cupped"),
        compensar_rotacao_z=True,
    )
    if not bool(job.get("rig", False)):
        _assar_pose_em_malhas([obj], rig)

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
        "maos": info_maos,
    }
    if info_cabelo:
        rel["cabelo"] = {"estilo": estilo, **info_cabelo}
    json.dump(rel, open(os.path.join(saida, "relatorio.json"), "w"), indent=2)
    print("TEMPLATE_OK", json.dumps({k: rel[k] for k in ("braco_graus", "antebraco_graus", "perna_graus", "iou_silhueta", "triangulos")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
