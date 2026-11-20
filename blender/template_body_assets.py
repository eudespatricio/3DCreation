"""Helpers MPFB2 CC0, malha base, limpeza de helpers e pose de maos."""

from __future__ import annotations

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
    for p in (
        "lowerarm",
        "hand",
        "index_01",
        "index_02",
        "index_03",
        "middle_01",
        "middle_02",
        "middle_03",
        "ring_01",
        "ring_02",
        "ring_03",
        "pinky_01",
        "pinky_02",
        "pinky_03",
        "thumb_01",
        "thumb_02",
        "thumb_03",
    )
}
_OSSOS_BRACO = _OSSOS_BRACO_DISTAL | {"upperarm_l", "upperarm_r"}
_OSSOS_TRONCO = {
    "pelvis",
    "spine_01",
    "spine_02",
    "spine_03",
    "clavicle_l",
    "clavicle_r",
    "thigh_l",
    "thigh_r",
    "calf_l",
    "calf_r",
    "foot_l",
    "foot_r",
    "ball_l",
    "ball_r",
}

_CATEGORIAS_MPFB_CC0 = ("skins", "eyes", "eyebrows", "eyelashes", "clothes", "hair")

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
    except (OSError, zipfile.BadZipFile) as exc:
        print(f"[template_body] aviso ao extrair pacote MPFB {zip_path}: {exc}", file=sys.stderr)
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
    except (ImportError, AttributeError, KeyError, RuntimeError, OSError, TypeError) as exc:
        print(f"[template_body] LocationService indisponivel ({cat}): {exc}", file=sys.stderr)
    try:
        from bl_ext.user_default.mpfb.services.assetservice import AssetService

        raizes.extend(AssetService.get_asset_roots(cat))
    except (ImportError, AttributeError, KeyError, RuntimeError, OSError, TypeError) as exc:
        print(f"[template_body] AssetService indisponivel ({cat}): {exc}", file=sys.stderr)
    cfg_dir = ""
    try:
        cfg_dir = bpy.utils.user_resource("CONFIG") or ""
    except (AttributeError, RuntimeError, OSError, ValueError) as exc:
        print(f"[template_body] bpy.utils.user_resource('CONFIG') indisponivel: {exc}", file=sys.stderr)
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
    # passa para -X_bl (Hand.R canonico), e 'r' (-X pre-pi) passa para +X_bl (Hand.L).
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
