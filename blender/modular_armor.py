"""Modulo de geracao e transferencia de pesos para sets modulares e armaduras (bpy puro, I9).

Suporta 2 categorias fisicas:
1. Skinned Deformavel (peitoral, calcas, botas, luvas):
   Carrega vestuario (.mhclo MakeHuman CC0 ou malha), alinha ao corpo base de 23 ossos
   (godot-humanoid@1), transfere pesos de vertex groups via modificador DATA_TRANSFER e
   exporta GLB game-ready com esqueleto e pesos perfeitamente mapeados sem rasgos nas juncoes.
2. Acessorios Socket Rigidos (elmo, ombreiras, escudo):
   Ajusta pivo/origem para o encaixe articular do osso alvo (Head, Shoulder.L, LowerArm.L)
   e exporta GLB estanque sem deformacao esqueletica para fixacao via BoneAttachment3D ou
   Attachment R15 (HatAttachment, LeftCollarAttachment, LeftGripAttachment).

Uso: blender -b --python blender/modular_armor.py -- <job.json>
"""

from __future__ import annotations

import json
import math
import os
import sys
from typing import Any

import bmesh
import bpy
from mathutils import Matrix, Vector

_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_DIR)
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)
if _DIR not in sys.path:
    sys.path.insert(0, _DIR)

try:
    import autorig
    import smart_fit
except ImportError:
    from blender import autorig, smart_fit

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

_OSSOS_SOCKET_PADRAO: dict[str, str] = {
    "elmo": "Head",
    "ombreiras": "Shoulder.L",
    "peitoral": "Chest",
    "luvas": "Hand.R",
    "calcas": "Hips",
    "botas": "Foot.R",
    "escudo": "LowerArm.L",
    "capa": "Chest",
    "mochila": "Chest",
    "asas": "Chest",
    "orbe": "Hand.L",
    "sela": "MountSeat",
    "cabelo": "Head",
    "arma": "Hand.R",
    "corpo": "Root",
}

_OSSOS_R15_PADRAO: dict[str, str] = {
    "elmo": "Head",
    "ombreiras": "LeftUpperArm",
    "peitoral": "UpperTorso",
    "luvas": "RightHand",
    "calcas": "LowerTorso",
    "botas": "RightFoot",
    "escudo": "LeftHand",
    "capa": "UpperTorso",
    "mochila": "UpperTorso",
    "asas": "UpperTorso",
    "orbe": "LeftHand",
    "sela": "UpperTorso",
    "cabelo": "Head",
    "arma": "RightHand",
    "corpo": "HumanoidRootPart",
}

_OSSOS_AA_PADRAO: dict[str, str] = dict(_OSSOS_SOCKET_PADRAO, capa="Cape")

_OSSOS_POR_ESQUELETO: dict[str, dict[str, str]] = {
    "godot-humanoid@1": _OSSOS_SOCKET_PADRAO,
    "godot-humanoid-aa@1": _OSSOS_AA_PADRAO,
    "r15@1": _OSSOS_R15_PADRAO,
}


def _osso_socket(parte: str, esqueleto: str = "godot-humanoid@1") -> str:
    """Retorna o nome do osso alvo para a parte e esqueleto especificados."""
    tabela = _OSSOS_POR_ESQUELETO.get(esqueleto, _OSSOS_SOCKET_PADRAO)
    return tabela.get(parte) or _OSSOS_SOCKET_PADRAO.get(parte, "Chest")


_SKINNED_PADRAO: dict[str, bool] = {
    "peitoral": True,
    "luvas": True,
    "calcas": True,
    "botas": True,
    "corpo": True,
    "elmo": False,
    "ombreiras": True,
    "escudo": False,
    "capa": False,
    "mochila": False,
    "asas": False,
    "orbe": False,
    "sela": False,
    "cabelo": False,
    "arma": False,
}


def _encontrar_mhclo(item_ou_caminho: str, subpasta: str = "clothes") -> str:
    """Localiza asset .mhclo nos pacotes MPFB2 e diretorios locais sem caminhos fixos (I15)."""
    bruto = (item_ou_caminho or "").strip()
    if not bruto:
        raise SystemExit(f"caminho MakeHuman vazio para {subpasta}")
    if os.path.isfile(bruto):
        return bruto

    estilo = bruto
    if estilo.startswith("makehuman://"):
        estilo = estilo[len("makehuman://"):]
    estilo = estilo.strip("/")
    if estilo.startswith(f"{subpasta}/"):
        estilo = estilo[len(f"{subpasta}/"):]
    elif estilo.startswith("clothes/"):
        estilo = estilo[len("clothes/"):]
    elif estilo.startswith("hair/"):
        estilo = estilo[len("hair/"):]
    estilo = estilo.strip("/")
    if estilo.endswith(".mhclo"):
        estilo = estilo[:-6]
    rel = estilo.replace("\\", "/").strip("/")
    if not rel:
        raise SystemExit(f"caminho MakeHuman vazio para {subpasta}")
    base = os.path.basename(rel)

    raizes: list[str] = []
    for env_var in ("FORGE3D_MPFB_ASSETS", "FORGE3D_MAKEHUMAN_DIR"):
        env_dir = os.environ.get(env_var, "").strip()
        if env_dir:
            raizes.extend([
                os.path.join(env_dir, subpasta),
                os.path.join(env_dir, "clothes"),
                os.path.join(env_dir, "hair"),
                env_dir,
            ])

    try:
        from bl_ext.user_default.mpfb.services.locationservice import LocationService

        user_data = LocationService.get_user_data(subpasta)
        if user_data:
            raizes.append(user_data)
        user_clothes = LocationService.get_user_data("clothes")
        if user_clothes:
            raizes.append(user_clothes)
    except (ImportError, AttributeError, KeyError, RuntimeError, OSError, TypeError) as exc:
        print(f"[modular_armor] LocationService indisponivel ({subpasta}): {exc}", file=sys.stderr)

    try:
        from bl_ext.user_default.mpfb.services.assetservice import AssetService

        raizes.extend(AssetService.get_asset_roots(subpasta))
        raizes.extend(AssetService.get_asset_roots("clothes"))
    except (ImportError, AttributeError, KeyError, RuntimeError, OSError, TypeError) as exc:
        print(f"[modular_armor] AssetService indisponivel ({subpasta}): {exc}", file=sys.stderr)

    cfg_dir = ""
    try:
        cfg_dir = bpy.utils.user_resource("CONFIG") or ""
    except (AttributeError, RuntimeError, OSError, ValueError) as exc:
        print(f"[modular_armor] bpy.utils.user_resource('CONFIG') indisponivel: {exc}", file=sys.stderr)
        cfg_dir = ""
    if cfg_dir:
        for p in (subpasta, "clothes", "hair"):
            raizes.extend([
                os.path.join(cfg_dir, "extensions", ".user", "user_default", "mpfb", "data", p),
                os.path.join(cfg_dir, "extensions", "user_default", "mpfb", "data", p),
            ])

    xdg = os.environ.get("XDG_CONFIG_HOME", "").strip()
    if xdg:
        for p in (subpasta, "clothes", "hair"):
            raizes.append(
                os.path.join(xdg, "blender", "4.2", "extensions", ".user", "user_default", "mpfb", "data", p)
            )

    home = os.path.expanduser("~")
    for p in (subpasta, "clothes", "hair"):
        raizes.extend([
            os.path.join(home, ".config", "blender", "4.2", "extensions", ".user", "user_default", "mpfb", "data", p),
            os.path.join(home, ".config", "blender", "4.2", "extensions", "user_default", "mpfb", "data", p),
        ])

    vistos: set[str] = set()
    rel_os = os.path.join(*rel.split("/")) if "/" in rel else rel
    for raiz in raizes:
        if not raiz or raiz in vistos or not os.path.isdir(raiz):
            continue
        vistos.add(raiz)
        for candidato in (
            os.path.join(raiz, f"{rel_os}.mhclo"),
            os.path.join(raiz, rel_os, f"{base}.mhclo"),
        ):
            if os.path.isfile(candidato):
                return candidato

    # Busca recursiva priorizando subcaminho completo antes do nome base
    rel_suffix_a = os.path.normpath(f"{rel_os}.mhclo")
    rel_suffix_b = os.path.normpath(os.path.join(rel_os, f"{base}.mhclo"))
    for raiz in vistos:
        for root, _, files in os.walk(raiz):
            if f"{base}.mhclo" in files:
                full = os.path.normpath(os.path.join(root, f"{base}.mhclo"))
                if "/" in rel and not (full.endswith(rel_suffix_a) or full.endswith(rel_suffix_b)):
                    continue
                return full

    for raiz in vistos:
        for root, _, files in os.walk(raiz):
            if f"{base}.mhclo" in files:
                return os.path.join(root, f"{base}.mhclo")

    raise SystemExit(f"peca MakeHuman '{rel}' nao encontrada nos pacotes MPFB2 locais")


def _criar_armadura(ossos: list[dict], nome: str = "Armature") -> "bpy.types.Object":
    """Cria objeto Armature com hierarquia de ossos para rigging e export glTF."""
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
    return obj


def _transferir_pesos_esqueleto(
    body_obj,
    cloth_obj,
    rig_obj,
    parte: str = "",
) -> None:
    """Aplica DATA_TRANSFER do corpo base (23 ou 56 ossos) para a peca e garante pesos limpos."""
    mod = cloth_obj.modifiers.new(name="DATA_TRANSFER", type="DATA_TRANSFER")
    mod.object = body_obj
    mod.use_vert_data = True
    mod.data_types_verts = {"VGROUP_WEIGHTS"}
    mod.vert_mapping = "POLYINTERP_NEAREST"
    mod.layers_vgroup_select_src = "ALL"
    mod.layers_vgroup_select_dst = "NAME"

    bpy.context.view_layer.objects.active = cloth_obj
    bpy.ops.object.datalayout_transfer(modifier="DATA_TRANSFER")
    bpy.ops.object.modifier_apply(modifier="DATA_TRANSFER")

    # Filtra grupos: mantem apenas os ossos validos do esqueleto de referencia
    ossos_validos = {b.name for b in rig_obj.data.bones}
    for vg in list(cloth_obj.vertex_groups):
        if vg.name not in ossos_validos:
            cloth_obj.vertex_groups.remove(vg)

    # Garante todos os grupos nao-raiz e refina luvas/manoplas nas falanges (56 ossos)
    raizes = getattr(autorig, "_RAIZES", {"Root", "HumanoidRootPart"})
    ossos_dedos = getattr(autorig, "_OSSOS_DEDOS", set())
    tem_dedos = any(b.name in ossos_dedos for b in rig_obj.data.bones)
    vgs_por_nome = {vg.name: vg for vg in cloth_obj.vertex_groups}
    for b in rig_obj.data.bones:
        if b.name not in raizes and b.name not in vgs_por_nome:
            vgs_por_nome[b.name] = cloth_obj.vertex_groups.new(name=b.name)

    segmentos_ossos = [
        (b.name, b.head_local.copy(), b.tail_local.copy())
        for b in rig_obj.data.bones
        if b.name not in raizes
    ]
    segmentos_mao_dedos: dict[str, list[tuple[str, Vector, Vector]]] = {}
    if tem_dedos:
        for lado in ("L", "R"):
            alvos_l = [
                (b.name, b.head_local.copy(), b.tail_local.copy())
                for b in rig_obj.data.bones
                if b.name == f"Hand.{lado}" or (b.name in ossos_dedos and b.name.endswith(f".{lado}"))
            ]
            if alvos_l:
                segmentos_mao_dedos[f"Hand.{lado}"] = alvos_l

    idx_para_nome = {vg.index: vg.name for vg in cloth_obj.vertex_groups}
    for v in cloth_obj.data.vertices:
        pesos_v = [(idx_para_nome[g.group], float(g.weight)) for g in v.groups if g.group in idx_para_nome and g.weight > 1e-6]
        if not pesos_v and segmentos_ossos:
            cands = sorted(
                ((autorig._dist_ponto_segmento(v.co, h_b, t_b), n_b) for n_b, h_b, t_b in segmentos_ossos),
                key=lambda item: item[0],
            )[:4]
            inv_w = [(1.0 / ((d + 0.005) ** 4), n_b) for d, n_b in cands]
            for n_b, w_b in autorig._normalizar_top4(inv_w):
                vgs_por_nome[n_b].add([v.index], w_b, "REPLACE")
        elif parte in ("luvas", "manoplas") and tem_dedos:
            for hand_n, segs_mao in segmentos_mao_dedos.items():
                w_h = sum(w for n, w in pesos_v if n == hand_n)
                if w_h < 0.05:
                    continue
                hand_bone = rig_obj.data.bones.get(hand_n)
                if hand_bone is None:
                    continue
                hand_dir = (hand_bone.tail_local - hand_bone.head_local)
                if hand_dir.length > 1e-4 and (v.co - hand_bone.head_local).dot(hand_dir.normalized()) < 0.35 * hand_dir.length:
                    continue
                inv_f = [
                    (1.0 / ((autorig._dist_ponto_segmento(v.co, hb, tb) + (0.012 if nb == hand_n else 0.0025)) ** 5), nb)
                    for nb, hb, tb in segs_mao
                ]
                dist_f = autorig._normalizar_top4(inv_f)
                mistura = [(w, n) for n, w in pesos_v if n != hand_n]
                for nb, wb in dist_f:
                    mistura.append((w_h * wb, nb))
                for vg in list(cloth_obj.vertex_groups):
                    if any(g.group == vg.index for g in v.groups):
                        vg.remove([v.index])
                for nb, wb in autorig._normalizar_top4(mistura):
                    vgs_por_nome[nb].add([v.index], wb, "REPLACE")

    autorig._normalizar_grupos_e_mapear(cloth_obj)

    # Vincula Armature modifier com preservacao de volume (Dual Quaternion)
    cloth_obj.parent = rig_obj
    arm_mod = cloth_obj.modifiers.new(name="Armature", type="ARMATURE")
    arm_mod.object = rig_obj
    arm_mod.use_deform_preserve_volume = True


_CORES_PROMPT: dict[str, tuple[float, float, float]] = {
    "esmeralda": (0.10, 0.56, 0.34),
    "emerald": (0.10, 0.56, 0.34),
    "jade": (0.14, 0.58, 0.42),
    "verde": (0.15, 0.50, 0.25),
    "green": (0.15, 0.50, 0.25),
    "dourado": (0.85, 0.68, 0.24),
    "dourada": (0.85, 0.68, 0.24),
    "ouro": (0.85, 0.68, 0.24),
    "gold": (0.85, 0.68, 0.24),
    "golden": (0.85, 0.68, 0.24),
    "prata": (0.72, 0.75, 0.79),
    "prateado": (0.72, 0.75, 0.79),
    "prateada": (0.72, 0.75, 0.79),
    "silver": (0.72, 0.75, 0.79),
    "mithril": (0.76, 0.82, 0.88),
    "aco": (0.52, 0.55, 0.59),
    "aço": (0.52, 0.55, 0.59),
    "steel": (0.52, 0.55, 0.59),
    "ferro": (0.44, 0.46, 0.50),
    "iron": (0.44, 0.46, 0.50),
    "bronze": (0.72, 0.45, 0.24),
    "cobre": (0.76, 0.42, 0.25),
    "copper": (0.76, 0.42, 0.25),
    "obsidiana": (0.12, 0.13, 0.16),
    "obsidian": (0.12, 0.13, 0.16),
    "gunmetal": (0.24, 0.26, 0.30),
    "sombrio": (0.16, 0.17, 0.20),
    "dark": (0.18, 0.19, 0.22),
    "preto": (0.11, 0.12, 0.14),
    "black": (0.11, 0.12, 0.14),
    "rubi": (0.64, 0.14, 0.16),
    "ruby": (0.64, 0.14, 0.16),
    "vermelho": (0.64, 0.15, 0.15),
    "crimson": (0.60, 0.12, 0.16),
    "red": (0.64, 0.15, 0.15),
    "safira": (0.16, 0.34, 0.68),
    "sapphire": (0.16, 0.34, 0.68),
    "azul": (0.18, 0.36, 0.68),
    "blue": (0.18, 0.36, 0.68),
    "ametista": (0.46, 0.22, 0.62),
    "amethyst": (0.46, 0.22, 0.62),
    "roxo": (0.44, 0.22, 0.58),
    "purple": (0.44, 0.22, 0.58),
    "couro": (0.36, 0.22, 0.13),
    "leather": (0.36, 0.22, 0.13),
    "marrom": (0.36, 0.22, 0.13),
    "brown": (0.36, 0.22, 0.13),
    "marfim": (0.84, 0.82, 0.76),
    "ivory": (0.84, 0.82, 0.76),
    "branco": (0.84, 0.84, 0.86),
    "white": (0.84, 0.84, 0.86),
}


def _parse_cor_hex(valor: str) -> tuple[float, float, float] | None:
    """Converte '#rrggbb' ou '#rgb' para tupla sRGB [0..1]."""
    s = (valor or "").strip().lstrip("#")
    if len(s) == 3 and all(c in "0123456789abcdefABCDEF" for c in s):
        s = "".join(c * 2 for c in s)
    if len(s) == 6 and all(c in "0123456789abcdefABCDEF" for c in s):
        return (int(s[0:2], 16) / 255.0, int(s[2:4], 16) / 255.0, int(s[4:6], 16) / 255.0)
    return None


def _resolver_estilo_visual(job: dict) -> dict[str, Any]:
    """Extrai cor base, acento, metallic e roughness a partir de cor/paleta/prompt."""
    cores: list[tuple[float, float, float]] = []

    cor_raw = job.get("cor")
    if isinstance(cor_raw, str):
        parsed = _parse_cor_hex(cor_raw) or _CORES_PROMPT.get(cor_raw.strip().lower())
        if parsed:
            cores.append(parsed)

    paleta_raw = job.get("paleta")
    tokens_paleta: list[str] = []
    if isinstance(paleta_raw, (list, tuple)):
        tokens_paleta = [str(x).strip() for x in paleta_raw if str(x).strip()]
    elif isinstance(paleta_raw, str):
        tokens_paleta = [t.strip() for t in paleta_raw.replace(";", ",").split(",") if t.strip()]

    for tok in tokens_paleta:
        parsed = _parse_cor_hex(tok) or _CORES_PROMPT.get(tok.lower())
        if parsed:
            cores.append(parsed)

    prompt = str(job.get("prompt") or "").strip().lower()
    if prompt:
        for palavra, rgb in _CORES_PROMPT.items():
            if palavra in prompt and rgb not in cores:
                cores.append(rgb)

    tint = cores[0] if cores else None
    accent = cores[1] if len(cores) > 1 else None

    parte = str(job.get("parte") or "").strip().lower()
    nao_metal = any(
        k in prompt for k in ("couro", "leather", "tecido", "cloth", "fabric", "veludo", "velvet", "linho", "linen", "madeira", "wood")
    )
    e_metal = any(
        k in prompt
        for k in (
            "metal", "armadura", "armor", "placa", "plate", "steel", "aco", "aço",
            "ferro", "iron", "ouro", "dourad", "gold", "prata", "pratead", "silver",
            "bronze", "cobre", "copper", "chrome", "titanium", "mithril", "cavaleiro", "knight",
        )
    )

    if nao_metal and not e_metal:
        metallic = 0.05
        roughness = 0.62
    elif e_metal or parte in ("elmo", "peitoral", "ombreiras", "escudo", "botas", "luvas"):
        metallic = 0.85 if e_metal else 0.55
        if any(k in prompt for k in ("polido", "polished", "ouro", "gold", "dourad", "prata", "silver", "esmeralda", "emerald")):
            roughness = 0.24
        elif any(k in prompt for k in ("gasto", "worn", "velho", "aged", "rust", "ferrugem")):
            roughness = 0.45
        else:
            roughness = 0.32
    else:
        metallic = 0.12
        roughness = 0.55

    if job.get("metallic") is not None:
        metallic = max(0.0, min(1.0, float(job["metallic"])))
    if job.get("roughness") is not None:
        roughness = max(0.05, min(1.0, float(job["roughness"])))

    return {
        "tint": tint,
        "accent": accent,
        "metallic": metallic,
        "roughness": roughness,
        "has_custom": bool(tint or prompt or cor_raw or paleta_raw),
    }


_UV_GRID_ARMOR = 64


def _area_tri_2d_uv(
    a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]
) -> float:
    return 0.5 * abs((b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1]))


def _area_tri_3d_vec(a, b, c) -> float:
    ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
    cx = uy * vz - uz * vy
    cy = uz * vx - ux * vz
    cz = ux * vy - uy * vx
    return 0.5 * math.sqrt(cx * cx + cy * cy + cz * cz)


def _orientar_ccw_2d(
    tri: tuple[tuple[float, float], tuple[float, float], tuple[float, float]],
) -> tuple[tuple[float, float], tuple[float, float], tuple[float, float]]:
    a, b, c = tri
    cross = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    return (a, c, b) if cross < 0.0 else tri


def _clip_tri_2d_area(
    sujeito: tuple[tuple[float, float], tuple[float, float], tuple[float, float]],
    recorte: tuple[tuple[float, float], tuple[float, float], tuple[float, float]],
) -> float:
    """Area de intersecao de dois triangulos 2D via Sutherland-Hodgman."""
    poly: list[tuple[float, float]] = list(_orientar_ccw_2d(sujeito))
    c_tri = _orientar_ccw_2d(recorte)
    for k in range(3):
        if not poly:
            return 0.0
        p = c_tri[k]
        q = c_tri[(k + 1) % 3]
        ex, ey = q[0] - p[0], q[1] - p[1]
        saida: list[tuple[float, float]] = []
        s_pt = poly[-1]
        for e_pt in poly:
            e_in = (ex * (e_pt[1] - p[1]) - ey * (e_pt[0] - p[0])) >= -1e-11
            s_in = (ex * (s_pt[1] - p[1]) - ey * (s_pt[0] - p[0])) >= -1e-11
            if e_in:
                if not s_in:
                    dx, dy = e_pt[0] - s_pt[0], e_pt[1] - s_pt[1]
                    denom = ex * dy - ey * dx
                    if abs(denom) <= 1e-15:
                        saida.append(s_pt)
                    else:
                        t = (ex * (p[1] - s_pt[1]) - ey * (p[0] - s_pt[0])) / denom
                        saida.append((s_pt[0] + t * dx, s_pt[1] + t * dy))
                saida.append(e_pt)
            elif s_in:
                dx, dy = e_pt[0] - s_pt[0], e_pt[1] - s_pt[1]
                denom = ex * dy - ey * dx
                if abs(denom) <= 1e-15:
                    saida.append(s_pt)
                else:
                    t = (ex * (p[1] - s_pt[1]) - ey * (p[0] - s_pt[0])) / denom
                    saida.append((s_pt[0] + t * dx, s_pt[1] + t * dy))
            s_pt = e_pt
        poly = saida

    if len(poly) < 3:
        return 0.0
    area2 = 0.0
    n_p = len(poly)
    for i in range(n_p):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n_p]
        area2 += x1 * y2 - x2 * y1
    return 0.5 * abs(area2)


def _grupo_uv_sobreposto(
    tris_uv: list[
        tuple[
            tuple[float, float],
            tuple[float, float],
            tuple[float, float],
            float,
            float,
            float,
            float,
            float,
        ]
    ],
) -> bool:
    n = len(tris_uv)
    if n < 2:
        return False

    def _sobrepoe(i: int, j: int) -> bool:
        a0, a1, a2, area_a, u0a, v0a, u1a, v1a = tris_uv[i]
        b0, b1, b2, area_b, u0b, v0b, u1b, v1b = tris_uv[j]
        if max(u0a, u0b) + 1e-6 >= min(u1a, u1b) or max(v0a, v0b) + 1e-6 >= min(v1a, v1b):
            return False
        inter = _clip_tri_2d_area((a0, a1, a2), (b0, b1, b2))
        return inter > 1e-8 and inter > 1e-4 * min(area_a, area_b)

    if n <= 32:
        for i in range(n):
            for j in range(i + 1, n):
                if _sobrepoe(i, j):
                    return True
        return False

    grade: dict[tuple[int, int], list[int]] = {}
    vistos: set[tuple[int, int]] = set()
    for idx, item in enumerate(tris_uv):
        _, _, _, _, u0, v0, u1, v1 = item
        gx0 = max(0, min(_UV_GRID_ARMOR - 1, int(math.floor(u0 * _UV_GRID_ARMOR))))
        gx1 = max(0, min(_UV_GRID_ARMOR - 1, int(math.floor(u1 * _UV_GRID_ARMOR))))
        gy0 = max(0, min(_UV_GRID_ARMOR - 1, int(math.floor(v0 * _UV_GRID_ARMOR))))
        gy1 = max(0, min(_UV_GRID_ARMOR - 1, int(math.floor(v1 * _UV_GRID_ARMOR))))
        for gx in range(gx0, gx1 + 1):
            for gy in range(gy0, gy1 + 1):
                cel = grade.setdefault((gx, gy), [])
                for outro in cel:
                    par = (outro, idx)
                    if par in vistos:
                        continue
                    vistos.add(par)
                    if _sobrepoe(outro, idx):
                        return True
                cel.append(idx)
    return False


def _uv_saudavel(obj) -> bool:
    """Verifica se a malha possui TEXCOORD_0 valido sem colapso, sobreposicao ou densidade extrema."""
    me = getattr(obj, "data", None)
    uv_layers = getattr(me, "uv_layers", None) if me is not None else None
    if not uv_layers:
        return False
    if not hasattr(bmesh, "new"):
        return True
    polygons = getattr(me, "polygons", None)
    if polygons is not None and len(polygons) == 0:
        return True
    uv_obj = getattr(uv_layers, "active", None) or uv_layers[0]
    if uv_obj is None:
        return False

    bm = bmesh.new()
    bm.from_mesh(me)
    uv_lay = bm.loops.layers.uv.get(uv_obj.name) or bm.loops.layers.uv.active
    if uv_lay is None:
        bm.free()
        return False
    if len(bm.faces) == 0:
        bm.free()
        return True

    grupos: dict[int, list] = {}
    ratios: dict[int, list[float]] = {}
    ok = True
    for f in bm.faces:
        loops = list(f.loops)
        if len(loops) < 3:
            continue
        for lp in loops:
            u_val = float(lp[uv_lay].uv[0])
            v_val = float(lp[uv_lay].uv[1])
            if (
                not math.isfinite(u_val)
                or not math.isfinite(v_val)
                or u_val < -1e-4
                or u_val > 1.0 + 1e-4
                or v_val < -1e-4
                or v_val > 1.0 + 1e-4
            ):
                ok = False
                break
        if not ok:
            break
        mat_i = int(f.material_index)
        g_list = grupos.setdefault(mat_i, [])
        r_list = ratios.setdefault(mat_i, [])
        lp0 = loops[0]
        for k in range(1, len(loops) - 1):
            lp1 = loops[k]
            lp2 = loops[k + 1]
            area_3d = _area_tri_3d_vec(lp0.vert.co, lp1.vert.co, lp2.vert.co)
            a = (float(lp0[uv_lay].uv[0]), float(lp0[uv_lay].uv[1]))
            b = (float(lp1[uv_lay].uv[0]), float(lp1[uv_lay].uv[1]))
            c = (float(lp2[uv_lay].uv[0]), float(lp2[uv_lay].uv[1]))
            area_uv = _area_tri_2d_uv(a, b, c)
            if area_3d > 1e-10 and area_uv <= 1e-10:
                ok = False
                break
            if area_uv > 1e-10:
                g_list.append(
                    (
                        a,
                        b,
                        c,
                        area_uv,
                        min(a[0], b[0], c[0]),
                        min(a[1], b[1], c[1]),
                        max(a[0], b[0], c[0]),
                        max(a[1], b[1], c[1]),
                    )
                )
                if area_3d > 1e-6:
                    r_list.append(area_uv / area_3d)
        if not ok:
            break

    bm.free()
    if not ok:
        return False

    for rs in ratios.values():
        if len(rs) >= 2:
            r_min = min(rs)
            r_max = max(rs)
            if r_min > 0.0 and (r_max / r_min) > 1000.0:
                return False

    for tris_g in grupos.values():
        if _grupo_uv_sobreposto(tris_g):
            return False

    return True


def _empacotar_shelves_uv(
    itens: list[tuple[int, float, float, float]],
    rho: float,
    uv_min: float,
    uv_max: float,
    gap: float,
    s_min: float,
    s_max: float,
) -> list[tuple[float, float, float]] | None:
    """Empacota caixas UV proporcionais a sqrt(area_3d) por shelf-packing decrescente."""
    caixas: list[tuple[float, int]] = []
    for idx, a_ref, k_poly, s_floor in itens:
        s_alvo = math.sqrt(max(0.0, rho * a_ref / max(k_poly, 1e-6))) if rho > 0.0 else s_floor
        s_i = max(s_floor, s_min, min(s_max, s_alvo))
        caixas.append((s_i, idx))
    caixas.sort(key=lambda item: item[0], reverse=True)

    posicoes: list[tuple[float, float, float] | None] = [None] * len(itens)
    x = uv_min
    y = uv_min
    shelf_h = 0.0
    for s_i, idx in caixas:
        if (uv_min + s_i) > uv_max:
            return None
        if x > uv_min and (x + s_i) > uv_max:
            y += shelf_h + gap
            x = uv_min
            shelf_h = 0.0
        if (y + s_i) > uv_max:
            return None
        posicoes[idx] = (x, y, s_i)
        if s_i > shelf_h:
            shelf_h = s_i
        x += s_i + gap
    return [p for p in posicoes if p is not None]


def _fallback_uv_disjunto_bmesh(obj) -> None:
    """Fallback deterministico puro-bmesh: atribui UVs disjuntos proporcionais a area 3D."""
    me = getattr(obj, "data", None)
    if me is None or not hasattr(bmesh, "new"):
        return
    uv_layers = getattr(me, "uv_layers", None)
    if uv_layers is None:
        return
    while len(uv_layers) > 1:
        uv_layers.remove(uv_layers[-1])
    if not uv_layers:
        uv_layers.new(name="UVMap")
    uv_obj = uv_layers[0]
    uv_layers.active = uv_obj
    uv_obj.active_render = True

    bm = bmesh.new()
    bm.from_mesh(me)
    if len(bm.faces) == 0:
        bm.free()
        return
    uv_lay = bm.loops.layers.uv.get(uv_obj.name) or bm.loops.layers.uv.active
    if uv_lay is None:
        uv_lay = bm.loops.layers.uv.new(uv_obj.name)

    faces_validas = []
    itens: list[tuple[int, float, float, float]] = []
    soma_area = 0.0
    for f in bm.faces:
        loops = list(f.loops)
        m = len(loops)
        if m < 3:
            continue
        if m == 3:
            area_3d = _area_tri_3d_vec(loops[0].vert.co, loops[1].vert.co, loops[2].vert.co)
            k_poly = 0.5
        else:
            area_3d = sum(
                _area_tri_3d_vec(loops[0].vert.co, loops[k].vert.co, loops[k + 1].vert.co)
                for k in range(1, m - 1)
            )
            ang = 2.0 * math.pi / m
            k_poly = 0.2304 * math.sin(ang) * (1.0 - math.cos(ang))
        a_ref = max(area_3d / max(1, m - 2), 1e-10)
        s_floor = max(8.0e-5, math.sqrt(2.5e-9 / max(k_poly, 1e-6)))
        itens.append((len(faces_validas), a_ref, k_poly, s_floor))
        faces_validas.append(loops)
        soma_area += a_ref

    if not faces_validas:
        bm.free()
        return

    uv_min = 0.02
    uv_max = 0.98
    gap = 2.0e-5
    s_min = 8.0e-5
    s_max = 0.90

    rho_hi = min(1.0e6, 0.5 / max(soma_area, 1e-12))
    posicoes = _empacotar_shelves_uv(itens, rho_hi, uv_min, uv_max, gap, s_min, s_max)
    if posicoes is None:
        rho_lo = rho_hi
        for _ in range(28):
            rho_lo *= 0.5
            posicoes = _empacotar_shelves_uv(itens, rho_lo, uv_min, uv_max, gap, s_min, s_max)
            if posicoes is not None:
                break
        if posicoes is None:
            posicoes = _empacotar_shelves_uv(itens, 0.0, uv_min, uv_max, gap, s_min, s_max)
        else:
            lo = rho_lo
            hi = rho_hi
            melhor = posicoes
            for _ in range(14):
                mid = math.sqrt(lo * hi)
                cand = _empacotar_shelves_uv(itens, mid, uv_min, uv_max, gap, s_min, s_max)
                if cand is not None:
                    melhor = cand
                    lo = mid
                else:
                    hi = mid
            posicoes = melhor

    if posicoes is None:
        cols = max(1, int(math.ceil(math.sqrt(len(faces_validas)))))
        step = (uv_max - uv_min) / cols
        cell = max(1e-6, step - gap)
        posicoes = [
            (uv_min + (idx % cols) * step, uv_min + (idx // cols) * step, cell)
            for idx in range(len(faces_validas))
        ]

    for idx, loops in enumerate(faces_validas):
        u0, v0, s_i = posicoes[idx]
        m = len(loops)
        if m == 3:
            coords = ((u0, v0), (u0 + s_i, v0), (u0, v0 + s_i))
        else:
            cx = u0 + 0.5 * s_i
            cy = v0 + 0.5 * s_i
            rad = 0.48 * s_i
            coords = tuple(
                (
                    cx + rad * math.cos(2.0 * math.pi * k / m),
                    cy + rad * math.sin(2.0 * math.pi * k / m),
                )
                for k in range(m)
            )
        for lp, uv_xy in zip(loops, coords):
            lp[uv_lay].uv = uv_xy

    bm.to_mesh(me)
    bm.free()
    me.update()


def _garantir_uv(obj, *, forcar: bool = False) -> None:
    """Garante camada UV ativa e saudavel na malha (re-unwrap se invalida ou ausente)."""
    if not forcar and _uv_saudavel(obj):
        return
    uv_layers = obj.data.uv_layers
    while len(uv_layers) > 1:
        uv_layers.remove(uv_layers[-1])
    if not uv_layers:
        uv_layers.new(name="UVMap")
    uv_act = uv_layers[0]
    uv_layers.active = uv_act
    uv_act.active_render = True

    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(
        angle_limit=math.radians(20.0),
        island_margin=0.02,
        area_weight=0.5,
        correct_aspect=True,
        scale_to_bounds=False,
    )
    bpy.ops.object.mode_set(mode="OBJECT")

    if not _uv_saudavel(obj):
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.uv.smart_project(
            angle_limit=math.radians(15.0),
            island_margin=0.03,
            area_weight=0.5,
            correct_aspect=True,
            scale_to_bounds=False,
        )
        bpy.ops.object.mode_set(mode="OBJECT")

    if not _uv_saudavel(obj):
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.uv.smart_project(
            angle_limit=math.radians(5.0),
            island_margin=0.04,
            area_weight=0.5,
            correct_aspect=True,
            scale_to_bounds=False,
        )
        bpy.ops.object.mode_set(mode="OBJECT")

    if not _uv_saudavel(obj):
        _fallback_uv_disjunto_bmesh(obj)


def _criar_imagem_tinta(
    nome: str,
    tint: tuple[float, float, float],
    accent: tuple[float, float, float] | None = None,
    tamanho: int = 256,
) -> "bpy.types.Image":
    """Gera textura RGBA empacotada deterministica com variacao metalica sutil."""
    img = bpy.data.images.new(name=nome, width=tamanho, height=tamanho, alpha=True)
    r0, g0, b0 = tint
    r1, g1, b1 = accent if accent is not None else (min(1.0, r0 * 1.18), min(1.0, g0 * 1.18), min(1.0, b0 * 1.18))
    buf = [1.0] * (tamanho * tamanho * 4)
    for y in range(tamanho):
        fy = y / max(1, tamanho - 1)
        borda = fy < 0.08 or fy > 0.92
        for x in range(tamanho):
            fx = x / max(1, tamanho - 1)
            rib = 0.92 + 0.08 * (((x * 7 + y * 13) % 17) / 16.0)
            if borda or fx < 0.06 or fx > 0.94:
                cr, cg, cb = r1, g1, b1
            else:
                cr, cg, cb = r0 * rib, g0 * rib, b0 * rib
            idx = (y * tamanho + x) * 4
            buf[idx] = max(0.0, min(1.0, cr))
            buf[idx + 1] = max(0.0, min(1.0, cg))
            buf[idx + 2] = max(0.0, min(1.0, cb))
            buf[idx + 3] = 1.0
    img.pixels.foreach_set(buf)
    img.pack()
    return img


def _tingir_imagem(
    src_img: "bpy.types.Image",
    nome: str,
    tint: tuple[float, float, float],
    accent: tuple[float, float, float] | None = None,
) -> "bpy.types.Image":
    """Cria copia empacotada de textura existente aplicando tonalizacao sem perder detalhe."""
    work = src_img.copy()
    w, h = work.size
    if w <= 0 or h <= 0:
        bpy.data.images.remove(work)
        return _criar_imagem_tinta(nome, tint, accent)
    max_dim = max(w, h)
    if max_dim > 512:
        escala = 512.0 / float(max_dim)
        work.scale(max(1, int(round(w * escala))), max(1, int(round(h * escala))))
        w, h = work.size

    px = list(work.pixels)
    bpy.data.images.remove(work)

    tr, tg, tb = tint
    n = w * h
    for i in range(0, n * 4, 4):
        r, g, b, a = px[i], px[i + 1], px[i + 2], px[i + 3]
        lum = 0.299 * r + 0.587 * g + 0.114 * b
        fator = 0.35 + 0.75 * lum
        # Preserva 20% da variacao original mantendo a cor alvo dominante
        px[i] = max(0.0, min(1.0, 0.80 * tr * fator + 0.20 * r))
        px[i + 1] = max(0.0, min(1.0, 0.80 * tg * fator + 0.20 * g))
        px[i + 2] = max(0.0, min(1.0, 0.80 * tb * fator + 0.20 * b))
        px[i + 3] = a if a > 0.0 else 1.0

    out = bpy.data.images.new(name=nome, width=w, height=h, alpha=True)
    out.pixels.foreach_set(px)
    out.pack()
    return out


_TEXTURA_POR_ZONA = {
    "leather": "leather_saddle_albedo.png",
    "couro": "leather_saddle_albedo.png",
    "saddle": "leather_saddle_albedo.png",
    "linen": "linen_tunic_albedo.png",
    "cloth": "linen_tunic_albedo.png",
    "capa": "linen_tunic_albedo.png",
    "bedroll": "linen_tunic_albedo.png",
    "steel": "steel_forged_albedo.png",
    "aco": "steel_forged_albedo.png",
    "blade": "steel_forged_albedo.png",
    "gold": "bronze_filigree_albedo.png",
    "brass": "bronze_filigree_albedo.png",
    "bronze": "bronze_filigree_albedo.png",
    "ouro": "bronze_filigree_albedo.png",
    "clasp": "bronze_filigree_albedo.png",
    "obsidian": "obsidian_runestone_albedo.png",
    "runestone": "obsidian_runestone_albedo.png",
    "pedra": "obsidian_runestone_albedo.png",
    "crystal": "arcane_crystal_albedo.png",
    "cristal": "arcane_crystal_albedo.png",
    "arcane": "arcane_crystal_albedo.png",
}


def _carregar_textura_pbr_local(nome_arquivo: str):
    """Carrega textura sRGB de ``blender/textures_pbr/<nome_arquivo>`` se disponivel em disco."""
    if not nome_arquivo:
        return None
    pasta = os.path.join(os.path.dirname(os.path.abspath(__file__)), "textures_pbr")
    caminho = os.path.join(pasta, nome_arquivo)
    if not os.path.isfile(caminho):
        return None
    try:
        img = bpy.data.images.load(caminho, check_existing=True)
        try:
            img.colorspace_settings.name = "sRGB"
        except (TypeError, ValueError, AttributeError, RuntimeError) as exc:
            print(f"[modular_armor] colorspace sRGB indisponivel ({nome_arquivo}): {exc}", file=sys.stderr)
        return img
    except (RuntimeError, OSError, ValueError, TypeError, AttributeError) as exc:
        print(f"[modular_armor] falha ao carregar textura local ({nome_arquivo}): {exc}", file=sys.stderr)
        return None


def _vincular_micro_relevo_bsdf(
    nt,
    bsdf,
    bump_strength: float,
    noise_scale: float,
) -> None:
    """Conecta micro-relevo procedural sutil ao ``Normal`` sem invalidar glTF."""
    if bump_strength <= 0.0:
        return
    normal_inp = bsdf.inputs.get("Normal")
    if normal_inp is None or normal_inp.is_linked:
        return
    tc = nt.nodes.new("ShaderNodeTexCoord")
    tc.location = (-680, -240)
    nz = nt.nodes.new("ShaderNodeTexNoise")
    nz.inputs["Scale"].default_value = float(noise_scale)
    nz.inputs["Detail"].default_value = 6.0
    nz.location = (-480, -240)
    bmp = nt.nodes.new("ShaderNodeBump")
    bmp.inputs["Strength"].default_value = float(bump_strength)
    bmp.inputs["Distance"].default_value = 0.004
    bmp.location = (-260, -240)
    nt.links.new(tc.outputs["Object"], nz.inputs["Vector"])
    nt.links.new(nz.outputs["Fac"], bmp.inputs["Height"])
    nt.links.new(bmp.outputs["Normal"], normal_inp)


def _tingir_textura_preservando_trama(
    src_img,
    nome: str,
    cor_srgb: tuple[float, float, float],
    forca: float = 0.88,
):
    """Tinge textura em nova imagem GENERATED (para .pack() nao reler PNG original do disco)."""
    src_work = src_img.copy()
    if int(src_work.size[0]) > 512 or int(src_work.size[1]) > 512:
        src_work.scale(min(int(src_work.size[0]), 512), min(int(src_work.size[1]), 512))
    w, h = int(src_work.size[0]), int(src_work.size[1])
    px = list(src_work.pixels)
    bpy.data.images.remove(src_work)
    n_px = max(1, len(px) // 4)
    avg_lum = max(
        0.05,
        sum(0.2126 * px[i] + 0.7152 * px[i + 1] + 0.0722 * px[i + 2] for i in range(0, len(px), 4))
        / float(n_px),
    )
    tr, tg, tb = cor_srgb
    s = float(forca)
    for k in range(0, len(px), 4):
        lum = 0.2126 * px[k] + 0.7152 * px[k + 1] + 0.0722 * px[k + 2]
        rel = max(0.38, min(1.55, lum / avg_lum))
        cr = min(1.0, tr * (0.26 + 0.74 * rel))
        cg = min(1.0, tg * (0.26 + 0.74 * rel))
        cb = min(1.0, tb * (0.26 + 0.74 * rel))
        px[k] = max(0.0, min(1.0, px[k] * (1.0 - s) + cr * s))
        px[k + 1] = max(0.0, min(1.0, px[k + 1] * (1.0 - s) + cg * s))
        px[k + 2] = max(0.0, min(1.0, px[k + 2] * (1.0 - s) + cb * s))
        px[k + 3] = 1.0
    novo = bpy.data.images.new(name=f"_tmp_{nome}", width=w, height=h, alpha=True)
    novo.pixels.foreach_set(px)
    import tempfile

    fd_t, tmp_png = tempfile.mkstemp(prefix="f3d_tint_", suffix=".png")
    os.close(fd_t)
    try:
        sc = bpy.context.scene
        ant_cm = sc.render.image_settings.color_mode
        sc.render.image_settings.color_mode = "RGBA"
        novo.filepath_raw = tmp_png
        novo.file_format = "PNG"
        novo.save()
        sc.render.image_settings.color_mode = ant_cm
        bpy.data.images.remove(novo)
        carregada = bpy.data.images.load(tmp_png)
        carregada.name = nome
        try:
            carregada.colorspace_settings.name = "sRGB"
        except (TypeError, ValueError, AttributeError, RuntimeError) as exc:
            print(f"[modular_armor] colorspace sRGB indisponivel ({nome}): {exc}", file=sys.stderr)
        carregada.pack()
    finally:
        if os.path.exists(tmp_png):
            os.unlink(tmp_png)
    return carregada


def _vincular_textura_base_color(nt, bsdf, img, uv_scale: float = 1.0) -> None:
    """Conecta ``img`` ao ``Base Color`` reutilizando ou criando ``ShaderNodeTexImage``."""
    bc_inp = bsdf.inputs.get("Base Color")
    if bc_inp is None:
        return
    tex_node = next((n for n in nt.nodes if n.type == "TEX_IMAGE"), None)
    if tex_node is None:
        tex_node = nt.nodes.new("ShaderNodeTexImage")
        tex_node.location = (-360, 220)
    tex_node.image = img
    if abs(float(uv_scale) - 1.0) > 1e-4:
        mp_node = next((n for n in nt.nodes if n.type == "MAPPING"), None)
        tc_node = next((n for n in nt.nodes if n.type == "TEX_COORD" and n.location[1] > 0), None)
        if tc_node is None:
            tc_node = nt.nodes.new("ShaderNodeTexCoord")
            tc_node.location = (-780, 220)
        if mp_node is None:
            mp_node = nt.nodes.new("ShaderNodeMapping")
            mp_node.location = (-580, 220)
        sc_v = float(uv_scale)
        mp_node.inputs["Scale"].default_value = (sc_v, sc_v, sc_v)
        for lk in list(mp_node.inputs["Vector"].links):
            nt.links.remove(lk)
        for lk in list(tex_node.inputs["Vector"].links):
            nt.links.remove(lk)
        nt.links.new(tc_node.outputs["UV"], mp_node.inputs["Vector"])
        nt.links.new(mp_node.outputs["Vector"], tex_node.inputs["Vector"])
    for lk in list(bc_inp.links):
        nt.links.remove(lk)
    nt.links.new(tex_node.outputs["Color"], bc_inp)


def _criar_material_pbr_zona(
    nome: str,
    base_color: tuple[float, float, float, float],
    *,
    metallic: float = 0.0,
    roughness: float = 0.5,
    textura_arquivo: str | None = None,
    accent_color: tuple[float, float, float, float] | None = None,
    emission_color: tuple[float, float, float, float] | None = None,
    emission_strength: float = 0.0,
    transmission: float = 0.0,
    ior: float = 1.45,
    alpha: float = 1.0,
    blend_method: str | None = None,
    bump_strength: float = 0.14,
    noise_scale: float = 42.0,
    backface_culling: bool = True,
    zona_tag: str = "",
    uv_scale: float = 1.0,
    tint_srgb: tuple[float, float, float] | None = None,
):
    """Constroi material PBR por zona usando textura local quando existir e fallback procedural."""
    mat = bpy.data.materials.new(name=nome)
    mat.use_nodes = True
    mat.use_backface_culling = bool(backface_culling)
    if blend_method and hasattr(mat, "blend_method"):
        mat.blend_method = str(blend_method)
    if zona_tag:
        mat["forge3d_zona_pbr"] = zona_tag
    if textura_arquivo:
        mat["forge3d_textura_local"] = textura_arquivo
    if abs(float(uv_scale) - 1.0) > 1e-4:
        mat["forge3d_uv_scale"] = float(uv_scale)

    nt = mat.node_tree
    nt.nodes.clear()
    out_node = nt.nodes.new("ShaderNodeOutputMaterial")
    out_node.location = (320, 0)
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (0, 0)
    nt.links.new(bsdf.outputs["BSDF"], out_node.inputs["Surface"])

    if "Base Color" in bsdf.inputs:
        bsdf.inputs["Base Color"].default_value = tuple(base_color)
    if "Metallic" in bsdf.inputs:
        bsdf.inputs["Metallic"].default_value = float(metallic)
    if "Roughness" in bsdf.inputs:
        bsdf.inputs["Roughness"].default_value = float(roughness)
    if "Alpha" in bsdf.inputs:
        bsdf.inputs["Alpha"].default_value = float(alpha)
    if "IOR" in bsdf.inputs:
        bsdf.inputs["IOR"].default_value = float(ior)
    if "Transmission Weight" in bsdf.inputs:
        bsdf.inputs["Transmission Weight"].default_value = float(transmission)
    if emission_color is not None and "Emission Color" in bsdf.inputs:
        bsdf.inputs["Emission Color"].default_value = tuple(emission_color)
    if "Emission Strength" in bsdf.inputs:
        bsdf.inputs["Emission Strength"].default_value = float(emission_strength)

    # Materiais refrativos ou emissivos preservam Base Color escalar exato no glTF
    if transmission <= 0.0 and emission_strength <= 0.0:
        img_local = _carregar_textura_pbr_local(textura_arquivo or "")
        if img_local is not None:
            if tint_srgb is not None:
                img_use = _tingir_textura_preservando_trama(img_local, f"Tinted_{nome}", tint_srgb)
                mat["forge3d_ja_tingido"] = True
            else:
                img_use = img_local
            _vincular_textura_base_color(nt, bsdf, img_use, uv_scale=uv_scale)
        else:
            acc = accent_color[:3] if accent_color else None
            img_proc = _criar_imagem_tinta(f"ZoneTex_{nome}", base_color[:3], acc)
            _vincular_textura_base_color(nt, bsdf, img_proc, uv_scale=uv_scale)
        _vincular_micro_relevo_bsdf(nt, bsdf, bump_strength, noise_scale)

    return mat


def _inferir_arquivo_textura_slot(mat, job: dict | None = None) -> str | None:
    """Resolve arquivo esperado em ``textures_pbr`` a partir de tag, nome do material ou job."""
    if mat is not None:
        explicito = mat.get("forge3d_textura_local") if hasattr(mat, "get") else None
        if explicito:
            return str(explicito)
        nome_low = str(getattr(mat, "name", "") or "").lower()
        for chave, arq in _TEXTURA_POR_ZONA.items():
            if chave in nome_low:
                return arq
    if isinstance(job, dict):
        prompt_low = str(job.get("prompt") or "").lower()
        parte_low = str(job.get("parte") or "").strip().lower()
        for chave, arq in _TEXTURA_POR_ZONA.items():
            if chave in prompt_low:
                return arq
        if parte_low in ("luvas", "peitoral", "elmo", "ombreiras", "escudo"):
            return "steel_forged_albedo.png"
        if parte_low == "botas":
            return "leather_saddle_albedo.png"
        if parte_low in ("calcas", "calças", "capa"):
            return "linen_tunic_albedo.png"
    return None


_NOMES_VAZADOS_MAKEHUMAN = (
    "casualsuit",
    "worksuit",
    "elegantsuit",
    "sportsuit",
    "fedora",
    "shoes",
)


def _nome_material_vaza_origem(nome: str) -> bool:
    low = (nome or "").strip().lower()
    return low.startswith("human.") or low.startswith("armor_mat") or any(k in low for k in _NOMES_VAZADOS_MAKEHUMAN)


def _aplicar_estilo_visual(obj, job: dict) -> None:
    """Aplica estilo/texturas PBR preservando slots multi-zona ja construidos."""
    _garantir_uv(obj)

    if len(obj.data.materials) > 1:
        for mat in list(obj.data.materials):
            if mat is None or not getattr(mat, "use_nodes", False) or mat.node_tree is None:
                continue
            bsdf = next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
            if bsdf is None:
                continue
            tw = bsdf.inputs.get("Transmission Weight")
            es = bsdf.inputs.get("Emission Strength")
            if (tw and tw.default_value > 0.0) or (es and es.default_value > 0.0):
                continue
            if hasattr(mat, "get") and mat.get("forge3d_ja_tingido"):
                continue
            arq_tex = _inferir_arquivo_textura_slot(mat)
            if arq_tex:
                img_local = _carregar_textura_pbr_local(arq_tex)
                if img_local is not None:
                    sc_uv = float(mat.get("forge3d_uv_scale", 1.0)) if hasattr(mat, "get") else 1.0
                    _vincular_textura_base_color(mat.node_tree, bsdf, img_local, uv_scale=sc_uv)
                    _vincular_micro_relevo_bsdf(mat.node_tree, bsdf, 0.14, 42.0)
        return

    estilo = _resolver_estilo_visual(job)
    textura_path = str(job.get("textura") or "").strip()
    if not textura_path:
        origem_cand = str(job.get("origem") or "").strip()
        if origem_cand and os.path.splitext(origem_cand)[1].lower() in (".png", ".jpg", ".jpeg", ".webp"):
            if os.path.isfile(origem_cand):
                textura_path = origem_cand

    if not obj.data.materials:
        mat_novo = bpy.data.materials.new(name="Armor_Mat")
        mat_novo.use_nodes = True
        obj.data.materials.append(mat_novo)

    concept_img = None
    if textura_path and os.path.isfile(textura_path):
        concept_img = bpy.data.images.load(os.path.abspath(textura_path), check_existing=True)
        try:
            concept_img.pack()
        except (RuntimeError, OSError, AttributeError) as exc:
            print(f"[modular_armor] concept_img.pack() ignorado ({textura_path}): {exc}", file=sys.stderr)

    tint_default = estilo["tint"] or (0.55, 0.58, 0.62)

    parte_limpa = str(job.get("parte") or "piece").strip().lower() or "piece"
    if parte_limpa == "calças":
        parte_limpa = "calcas"

    for idx_m, mat in enumerate(list(obj.data.materials)):
        nome_canonico = f"armor_{parte_limpa}_pbr" if idx_m == 0 else f"armor_{parte_limpa}_pbr_{idx_m}"
        if mat is None:
            mat = bpy.data.materials.new(name=nome_canonico)
            obj.data.materials[idx_m] = mat
        elif _nome_material_vaza_origem(mat.name):
            mat.name = nome_canonico
        if hasattr(mat, "blend_method"):
            mat.blend_method = "OPAQUE"
        mat.use_nodes = True
        nt = mat.node_tree
        bsdf = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
        if bsdf is None:
            nt.nodes.clear()
            bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
            out_node = nt.nodes.new("ShaderNodeOutputMaterial")
            nt.links.new(bsdf.outputs["BSDF"], out_node.inputs["Surface"])

        if "Metallic" in bsdf.inputs:
            bsdf.inputs["Metallic"].default_value = estilo["metallic"]
        if "Roughness" in bsdf.inputs:
            bsdf.inputs["Roughness"].default_value = estilo["roughness"]
        if "Coat Weight" in bsdf.inputs:
            bsdf.inputs["Coat Weight"].default_value = 0.0

        # Remove normal map vazado de traje MakeHuman (ex.: male_casualsuit01_normal)
        normal_inp = bsdf.inputs.get("Normal")
        if normal_inp is not None and normal_inp.is_linked:
            nodos_remover = []
            for n_cand in list(nt.nodes):
                if n_cand.type == "TEX_IMAGE" and n_cand.image is not None:
                    nm_im = str(getattr(n_cand.image, "name", "") or "").lower()
                    fp_im = str(getattr(n_cand.image, "filepath", "") or "").lower()
                    if any(k in nm_im or k in fp_im for k in _NOMES_VAZADOS_MAKEHUMAN) and (
                        "normal" in nm_im or "normal" in fp_im or n_cand != bsdf.inputs.get("Base Color")
                    ):
                        if any(lk.from_node == n_cand or lk.to_socket == normal_inp for lk in normal_inp.links):
                            nodos_remover.append(n_cand)
                        elif "normal" in nm_im or "normal" in fp_im:
                            nodos_remover.append(n_cand)
            if nodos_remover:
                for lk in list(normal_inp.links):
                    nt.links.remove(lk)
                for n_rm in nodos_remover:
                    nt.nodes.remove(n_rm)

        # Localiza TEX_IMAGE ligado ao Base Color (se houver)
        tex_node = None
        bc_input = bsdf.inputs.get("Base Color")
        if bc_input and bc_input.is_linked:
            from_node = bc_input.links[0].from_node
            if from_node.type == "TEX_IMAGE":
                tex_node = from_node
            else:
                for n in nt.nodes:
                    if n.type == "TEX_IMAGE" and n.image is not None:
                        tex_node = n
                        break
        if tex_node is None:
            tex_node = next((n for n in nt.nodes if n.type == "TEX_IMAGE" and n.image is not None), None)

        arq_local = _inferir_arquivo_textura_slot(mat, job)
        img_local = _carregar_textura_pbr_local(arq_local or "")
        if concept_img is not None:
            img_final = (
                _tingir_imagem(concept_img, f"ArmorConcept_{idx_m}", estilo["tint"], estilo["accent"])
                if estilo["tint"] is not None
                else concept_img
            )
        elif img_local is not None:
            if estilo["tint"] is not None:
                img_final = _tingir_imagem(img_local, f"{nome_canonico}_albedo", estilo["tint"], estilo["accent"])
            else:
                img_final = img_local
                try:
                    img_final.pack()
                except (RuntimeError, OSError, AttributeError) as exc:
                    print(f"[modular_armor] img_local.pack() ignorado ({arq_local}): {exc}", file=sys.stderr)
        elif tex_node is not None and tex_node.image is not None:
            if estilo["tint"] is not None:
                img_final = _tingir_imagem(tex_node.image, f"ArmorTint_{idx_m}", estilo["tint"], estilo["accent"])
            else:
                img_final = tex_node.image
                try:
                    img_final.pack()
                except (RuntimeError, OSError, AttributeError) as exc:
                    print(
                        f"[modular_armor] tex_node.image.pack() ignorado ({getattr(img_final, 'name', '')}): {exc}",
                        file=sys.stderr,
                    )
        else:
            img_final = _criar_imagem_tinta(f"ArmorBase_{idx_m}", tint_default, estilo["accent"])

        if tex_node is None:
            tex_node = nt.nodes.new("ShaderNodeTexImage")
        tex_node.image = img_final
        if bc_input:
            for lk in list(bc_input.links):
                nt.links.remove(lk)
            nt.links.new(tex_node.outputs["Color"], bc_input)
        _vincular_micro_relevo_bsdf(nt, bsdf, 0.14, 42.0)


def _criar_escudo_procedural(nome: str = "EscudoModular") -> "bpy.types.Object":
    """Cria escudo heater curvado multi-zona 2-manifold (aco forjado, borda/umbo de bronze e alcas de couro)."""
    mat_aco = _criar_material_pbr_zona(
        "Shield_ForgedSteel",
        (0.46, 0.49, 0.54, 1.0),
        metallic=0.86,
        roughness=0.30,
        textura_arquivo="steel_forged_albedo.png",
        accent_color=(0.30, 0.33, 0.38, 1.0),
        bump_strength=0.14,
        noise_scale=52.0,
        zona_tag="steel",
    )
    mat_bronze = _criar_material_pbr_zona(
        "Shield_BronzeTrim",
        (0.76, 0.56, 0.24, 1.0),
        metallic=0.90,
        roughness=0.25,
        textura_arquivo="bronze_filigree_albedo.png",
        accent_color=(0.52, 0.36, 0.14, 1.0),
        bump_strength=0.16,
        noise_scale=64.0,
        zona_tag="bronze",
    )
    mat_couro = _criar_material_pbr_zona(
        "Shield_LeatherGrip",
        (0.24, 0.13, 0.07, 1.0),
        metallic=0.02,
        roughness=0.70,
        textura_arquivo="leather_saddle_albedo.png",
        accent_color=(0.14, 0.07, 0.04, 1.0),
        bump_strength=0.18,
        noise_scale=44.0,
        zona_tag="leather",
    )

    bm = bmesh.new()
    meia_larg = 0.28
    z_topo = 0.36
    z_base = -0.40
    esp = 0.026

    def _curv_y(x_val: float, z_val: float) -> float:
        nx = min(1.15, abs(x_val) / meia_larg)
        nz = (z_val - 0.02) / 0.40
        return 0.062 * (1.0 - 0.82 * nx * nx) - 0.010 * nz * nz

    # Contorno heater suavizado (24 pontos bem espacados, sentido horario visto de +Y)
    contorno_xz: list[tuple[float, float]] = []
    # Borda superior levemente arqueada (-X -> +X)
    for k in range(6):
        u = -0.86 + (1.72 * k) / 5.0
        contorno_xz.append((meia_larg * u, z_topo + 0.018 * (1.0 - u * u)))
    # Flanco direito ogival (+X -> ponta inferior)
    for k in range(1, 9):
        s = k / 9.0
        larg_f = math.pow(max(0.0, math.cos(s * math.pi * 0.48)), 0.72)
        z_v = z_topo * 0.92 - (z_topo * 0.92 - z_base) * s
        contorno_xz.append((meia_larg * larg_f, z_v))
    # Ponta inferior arredondada
    contorno_xz.append((0.0, z_base))
    # Flanco esquerdo simetrico (ponta inferior -> -X)
    for k in range(8, 0, -1):
        s = k / 9.0
        larg_f = math.pow(max(0.0, math.cos(s * math.pi * 0.48)), 0.72)
        z_v = z_topo * 0.92 - (z_topo * 0.92 - z_base) * s
        contorno_xz.append((-meia_larg * larg_f, z_v))

    z_centro = 0.02
    aneis_corpo: list[list[tuple[float, float, float]]] = []
    # Casca traseira (-Y) -> borda -> face frontal convexa (+Y)
    for escala_r, offset_y in (
        (0.42, -esp * 0.50),
        (0.84, -esp * 0.50),
        (0.99, -esp * 0.32),
        (1.00, esp * 0.32),
        (0.86, esp * 0.50),
        (0.42, esp * 0.54),
    ):
        anel_c: list[tuple[float, float, float]] = []
        for cx, cz in contorno_xz:
            px = cx * escala_r
            pz = z_centro + (cz - z_centro) * escala_r
            py = _curv_y(px, pz) + offset_y
            anel_c.append((px, py, pz))
        aneis_corpo.append(anel_c)

    _adicionar_loft_fechado_bm(
        bm,
        aneis_corpo,
        mat_idx=0,
        ponto_base=(0.0, _curv_y(0.0, z_centro) - esp * 0.50, z_centro),
        ponto_topo=(0.0, _curv_y(0.0, z_centro) + esp * 0.58, z_centro),
    )

    # Moldura perimetral fechada em bronze (toro deformado 2-manifold ao redor da borda)
    pts_borda = [Vector((cx, _curv_y(cx, cz), cz)) for cx, cz in contorno_xz]
    n_borda = len(pts_borda)
    segs_rim = 6
    r_rim_rad = 0.016
    r_rim_esp = 0.019
    aneis_rim: list[list[bmesh.types.BMVert]] = []
    for i in range(n_borda):
        p_prev = pts_borda[(i - 1) % n_borda]
        p_curr = pts_borda[i]
        p_next = pts_borda[(i + 1) % n_borda]
        tang = (p_next - p_prev).normalized()
        n_frente = Vector((0.0, 1.0, 0.0))
        rad_out = tang.cross(n_frente)
        if rad_out.length < 1e-6:
            rad_out = Vector((1.0, 0.0, 0.0))
        else:
            rad_out.normalize()
        # Garante que rad_out aponte para fora do centro do escudo no plano XZ
        dir_centro = Vector((p_curr.x, 0.0, p_curr.z - z_centro))
        if rad_out.dot(dir_centro) < 0.0:
            rad_out = -rad_out
        eixo_esp = rad_out.cross(tang).normalized()
        anel_v: list[bmesh.types.BMVert] = []
        for k in range(segs_rim):
            ang = (2.0 * math.pi * k) / float(segs_rim)
            pt = p_curr + rad_out * (r_rim_rad * math.cos(ang)) + eixo_esp * (r_rim_esp * math.sin(ang))
            anel_v.append(bm.verts.new((pt.x, pt.y, pt.z)))
        aneis_rim.append(anel_v)

    for i in range(n_borda):
        a0 = aneis_rim[i]
        a1 = aneis_rim[(i + 1) % n_borda]
        for k in range(segs_rim):
            k2 = (k + 1) % segs_rim
            f_rim = bm.faces.new((a0[k], a1[k], a1[k2], a0[k2]))
            f_rim.material_index = 1

    # Umbo central (boss de bronze abaulado) + nervura heráldica vertical na face frontal (+Y)
    z_boss = 0.055
    y_boss_base = _curv_y(0.0, z_boss) + esp * 0.44
    aneis_boss: list[list[tuple[float, float, float]]] = []
    for r_b, dy_b in ((0.082, -0.004), (0.086, 0.008), (0.058, 0.022), (0.032, 0.040)):
        anel_b: list[tuple[float, float, float]] = []
        for k in range(16):
            ang = (2.0 * math.pi * k) / 16.0
            anel_b.append((r_b * math.cos(ang), y_boss_base + dy_b, z_boss + r_b * math.sin(ang)))
        aneis_boss.append(anel_b)
    _adicionar_loft_fechado_bm(
        bm,
        aneis_boss,
        mat_idx=1,
        ponto_base=(0.0, y_boss_base - 0.006, z_boss),
        ponto_topo=(0.0, y_boss_base + 0.048, z_boss),
    )

    # Nervura vertical de filigrana de bronze
    _adicionar_gema_octaedrica_bm(
        bm,
        (0.0, _curv_y(0.0, 0.02) + esp * 0.54, 0.01),
        (0.020, 0.010, 0.24),
        mat_idx=1,
    )

    # Alcas traseiras de couro (enarmes) e almofada de antebraco em -Y
    faces_pre_pad = set(bm.faces)
    verts_pad = _adicionar_caixa_chanfrada(
        bm,
        (0.0, _curv_y(0.0, 0.04) - esp * 0.58, 0.04),
        (0.17, 0.016, 0.18),
        subdiv=1,
    )
    for vp in verts_pad:
        vp.co.y += _curv_y(vp.co.x, vp.co.z) - _curv_y(0.0, 0.04)
    _atribuir_mat_novas_faces(bm, faces_pre_pad, 2)

    for sx_alca in (-0.068, 0.068):
        y_anc = _curv_y(sx_alca, 0.04) - esp * 0.48
        pts_alca: list[tuple[float, float, float]] = []
        for k in range(7):
            t_a = k / 6.0
            ang_a = math.pi * t_a
            z_a = 0.04 + 0.075 * math.cos(ang_a)
            y_a = y_anc - 0.052 * math.sin(ang_a)
            pts_alca.append((sx_alca, y_a, z_a))
        _adicionar_tubo_curva_bm(bm, pts_alca, 0.013, 0.005, segs=6, mat_idx=2)

    return _bmesh_criar_objeto_multimat(
        nome,
        bm,
        [mat_aco, mat_bronze, mat_couro],
        angulo_suave=44.0,
    )


def _adicionar_caixa_chanfrada(
    bm: bmesh.types.BMesh,
    centro: tuple[float, float, float],
    tamanho: tuple[float, float, float],
    subdiv: int = 1,
) -> list[bmesh.types.BMVert]:
    """Cria bloco fechado subdividido no BMesh para modelagem procedural manifold."""
    antes = set(bm.verts)
    ret = bmesh.ops.create_cube(bm, size=1.0)
    verts = ret["verts"]
    sx, sy, sz = tamanho
    cx, cy, cz = centro
    for v in verts:
        v.co.x = v.co.x * sx + cx
        v.co.y = v.co.y * sy + cy
        v.co.z = v.co.z * sz + cz
    if subdiv > 0:
        arestas = [
            e
            for e in bm.edges
            if e.verts[0] in verts and e.verts[1] in verts
        ]
        bmesh.ops.subdivide_edges(bm, edges=arestas, cuts=subdiv, use_grid_fill=True)
    return [v for v in bm.verts if v.is_valid and v not in antes]


def _atribuir_mat_novas_faces(bm: bmesh.types.BMesh, faces_antes: set, mat_idx: int) -> None:
    """Atribui ``mat_idx`` as faces criadas desde ``faces_antes``."""
    for f in bm.faces:
        if f not in faces_antes:
            f.material_index = mat_idx


def _adicionar_loft_fechado_bm(
    bm: bmesh.types.BMesh,
    aneis: list[list[tuple[float, float, float]]],
    mat_idx: int = 0,
    ponto_base: tuple[float, float, float] | None = None,
    ponto_topo: tuple[float, float, float] | None = None,
) -> list[bmesh.types.BMVert]:
    """Constroi casca fechada manifold conectando aneis sucessivos e tampando extremos."""
    bm_aneis = [[bm.verts.new(p) for p in anel] for anel in aneis]
    n_seg = len(bm_aneis[0])
    novas_faces = []
    for r in range(len(bm_aneis) - 1):
        a0 = bm_aneis[r]
        a1 = bm_aneis[r + 1]
        for i in range(n_seg):
            j = (i + 1) % n_seg
            novas_faces.append(bm.faces.new((a0[i], a0[j], a1[j], a1[i])))

    if ponto_base is not None:
        vb = bm.verts.new(ponto_base)
        a0 = bm_aneis[0]
        for i in range(n_seg):
            j = (i + 1) % n_seg
            novas_faces.append(bm.faces.new((vb, a0[j], a0[i])))
    else:
        novas_faces.append(bm.faces.new(tuple(reversed(bm_aneis[0]))))

    if ponto_topo is not None:
        vt = bm.verts.new(ponto_topo)
        a_top = bm_aneis[-1]
        for i in range(n_seg):
            j = (i + 1) % n_seg
            novas_faces.append(bm.faces.new((vt, a_top[i], a_top[j])))
    else:
        novas_faces.append(bm.faces.new(tuple(bm_aneis[-1])))

    for f in novas_faces:
        f.material_index = mat_idx
    return [v for anel in bm_aneis for v in anel]


def _adicionar_toro_bm(
    bm: bmesh.types.BMesh,
    major_r: float,
    minor_r: float,
    segs_major: int = 32,
    segs_minor: int = 10,
    *,
    rx: float = 1.0,
    ry: float = 1.0,
    mat_idx: int = 0,
    transform: Matrix | None = None,
) -> None:
    """Adiciona toro fechado 2-manifold sem arestas abertas ou vertices duplicados."""
    aneis = []
    for m in range(segs_major):
        phi = (2.0 * math.pi * m) / float(segs_major)
        cphi = math.cos(phi)
        sphi = math.sin(phi)
        n_vec = Vector((cphi * ry, sphi * rx, 0.0))
        if n_vec.length > 1e-8:
            n_vec.normalize()
        else:
            n_vec = Vector((cphi, sphi, 0.0))
        centro_anel = Vector((major_r * rx * cphi, major_r * ry * sphi, 0.0))
        anel_verts = []
        for k in range(segs_minor):
            theta = (2.0 * math.pi * k) / float(segs_minor)
            pt = centro_anel + n_vec * (minor_r * math.cos(theta)) + Vector((0.0, 0.0, minor_r * math.sin(theta)))
            if transform is not None:
                pt = transform @ pt
            anel_verts.append(bm.verts.new((pt.x, pt.y, pt.z)))
        aneis.append(anel_verts)

    for m in range(segs_major):
        a0 = aneis[m]
        a1 = aneis[(m + 1) % segs_major]
        for k in range(segs_minor):
            k2 = (k + 1) % segs_minor
            f = bm.faces.new((a0[k], a1[k], a1[k2], a0[k2]))
            f.material_index = mat_idx


def _adicionar_tubo_curva_bm(
    bm: bmesh.types.BMesh,
    pontos: list[tuple[float, float, float]],
    r_larg: float,
    r_esp: float,
    segs: int = 6,
    mat_idx: int = 0,
) -> None:
    """Varre secao oval fechada por transporte paralelo ao longo de uma polilinha 3D."""
    pts = [Vector(p) for p in pontos]
    if len(pts) < 2:
        return
    tangentes: list[Vector] = []
    for i, p in enumerate(pts):
        if i == 0:
            t = pts[1] - p
        elif i == len(pts) - 1:
            t = p - pts[-2]
        else:
            t = pts[i + 1] - pts[i - 1]
        tangentes.append(t.normalized() if t.length > 1e-8 else Vector((0.0, 0.0, 1.0)))

    u_ref = Vector((1.0, 0.0, 0.0))
    if abs(u_ref.dot(tangentes[0])) > 0.9:
        u_ref = Vector((0.0, 1.0, 0.0))
    u = (u_ref - tangentes[0] * u_ref.dot(tangentes[0])).normalized()

    aneis: list[list[tuple[float, float, float]]] = []
    for i, (p, t) in enumerate(zip(pts, tangentes)):
        if i > 0:
            u_proj = u - t * u.dot(t)
            if u_proj.length > 1e-6:
                u = u_proj.normalized()
        v = t.cross(u).normalized()
        anel: list[tuple[float, float, float]] = []
        for k in range(segs):
            ang = (2.0 * math.pi * k) / float(segs)
            pos = p + u * (r_larg * math.cos(ang)) + v * (r_esp * math.sin(ang))
            anel.append((pos.x, pos.y, pos.z))
        aneis.append(anel)

    _adicionar_loft_fechado_bm(bm, aneis, mat_idx=mat_idx)


def _adicionar_gema_octaedrica_bm(
    bm: bmesh.types.BMesh,
    centro: tuple[float, float, float],
    raios: tuple[float, float, float],
    rot_euler: tuple[float, float, float] = (0.0, 0.0, 0.0),
    mat_idx: int = 0,
) -> None:
    """Adiciona gema/medalhao octogonal chanfrado fechado para incrustacoes e fechos."""
    rx, ry, rz = raios
    rot = Matrix.Rotation(rot_euler[2], 4, "Z") @ Matrix.Rotation(rot_euler[1], 4, "Y") @ Matrix.Rotation(rot_euler[0], 4, "X")
    c_vec = Vector(centro)
    aneis: list[list[tuple[float, float, float]]] = []
    for z_f, r_f in ((-1.0, 0.48), (-0.42, 1.0), (0.42, 1.0), (1.0, 0.48)):
        anel: list[tuple[float, float, float]] = []
        for k in range(8):
            ang = (2.0 * math.pi * k) / 8.0 + (math.pi / 8.0)
            local = Vector((rx * r_f * math.cos(ang), ry * r_f * math.sin(ang), rz * z_f))
            mundo = c_vec + (rot @ local)
            anel.append((mundo.x, mundo.y, mundo.z))
        aneis.append(anel)
    _adicionar_loft_fechado_bm(bm, aneis, mat_idx=mat_idx)


def _aplicar_suavizacao_modular(obj, angulo_graus: float = 48.0) -> None:
    """Aplica smooth shading com arestas vivas por angulo diedro."""
    me = obj.data
    if me is None or not me.polygons:
        return
    for poly in me.polygons:
        poly.use_smooth = True
    try:
        me.shade_smooth()
        me.set_sharp_from_angle(angle=math.radians(float(angulo_graus)))
        me.update()
    except (RuntimeError, AttributeError, TypeError, ValueError) as exc:
        print(
            f"[modular_armor] aviso suavizacao modular em {getattr(obj, 'name', '?')}: {exc}",
            file=sys.stderr,
        )


def _bmesh_criar_objeto_multimat(
    nome: str,
    bm: bmesh.types.BMesh,
    materiais: list,
    angulo_suave: float = 48.0,
) -> "bpy.types.Object":
    """Finaliza BMesh multi-zona como objeto fechado triangulado com UVs e normais."""
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bmesh.ops.triangulate(bm, faces=bm.faces)
    me = bpy.data.meshes.new(nome)
    bm.to_mesh(me)
    bm.free()

    for mat in materiais:
        me.materials.append(mat)
    obj = bpy.data.objects.new(nome, me)
    bpy.context.collection.objects.link(obj)
    _garantir_uv(obj)
    _aplicar_suavizacao_modular(obj, angulo_graus=angulo_suave)
    obj["forge3d_angulo_suave"] = float(angulo_suave)
    return obj


def _criar_mochila_procedural(nome: str = "MochilaModular") -> "bpy.types.Object":
    """Cria mochila anatomica em couro selado com alcas peitorais, rolo de linho e fivelas."""
    mat_couro = _criar_material_pbr_zona(
        "Pack_SaddleLeather",
        (0.26, 0.14, 0.08, 1.0),
        metallic=0.0,
        roughness=0.68,
        textura_arquivo="leather_saddle_albedo.png",
        accent_color=(0.14, 0.07, 0.04, 1.0),
        bump_strength=0.20,
        noise_scale=36.0,
        zona_tag="couro_gasto",
    )
    mat_linho = _criar_material_pbr_zona(
        "Pack_LinenBedroll",
        (0.62, 0.55, 0.44, 1.0),
        metallic=0.0,
        roughness=0.84,
        textura_arquivo="linen_tunic_albedo.png",
        accent_color=(0.44, 0.38, 0.28, 1.0),
        bump_strength=0.24,
        noise_scale=64.0,
        zona_tag="tecido_linho",
        uv_scale=3.2,
        tint_srgb=(0.64, 0.57, 0.45),
    )
    mat_latao = _criar_material_pbr_zona(
        "Pack_BrassHardware",
        (0.77, 0.61, 0.22, 1.0),
        metallic=0.90,
        roughness=0.25,
        textura_arquivo="bronze_filigree_albedo.png",
        accent_color=(0.48, 0.36, 0.12, 1.0),
        bump_strength=0.08,
        noise_scale=52.0,
        zona_tag="bronze_latao",
    )

    bm = bmesh.new()

    # 1. Corpo principal ergonomico (concavidade em +Y_bl voltada para as costas, bojo em -Y_bl)
    aneis_corpo: list[list[tuple[float, float, float]]] = []
    n_z = 9
    n_rad = 16
    for iz in range(n_z):
        t = iz / float(n_z - 1)
        z = -0.35 + 0.36 * t
        escala_ext = 0.72 + 0.28 * math.sin(math.pi * (0.12 + 0.76 * t))
        hx = 0.142 * escala_ext
        hy_tras = 0.165 * (0.80 + 0.24 * math.sin(math.pi * (1.0 - t) ** 0.75)) * escala_ext
        hy_frente = 0.022 * escala_ext
        anel: list[tuple[float, float, float]] = []
        for ir in range(n_rad):
            ang = (2.0 * math.pi * ir) / float(n_rad)
            ca, sa = math.cos(ang), math.sin(ang)
            sup = (abs(ca) ** 3.2 + abs(sa) ** 3.2) ** (-1.0 / 3.2)
            ux = ca * sup
            uy = sa * sup
            x = hx * ux
            if uy >= 0.0:
                concavo = -0.020 * (1.0 - ux * ux)
                y = -0.012 + concavo + hy_frente * uy
            else:
                y = -0.012 + hy_tras * uy
            anel.append((x, y, z))
        aneis_corpo.append(anel)
    _adicionar_loft_fechado_bm(
        bm,
        aneis_corpo,
        mat_idx=0,
        ponto_base=(0.0, -0.09, -0.368),
        ponto_topo=(0.0, -0.085, 0.024),
    )

    # 2. Aba superior curva arredondada sobre a tampa
    aneis_aba: list[list[tuple[float, float, float]]] = []
    curva_aba = (
        (-0.012, 0.010, 0.0, 1.0),
        (-0.060, 0.040, 0.0, 1.0),
        (-0.135, 0.044, -0.45, 0.90),
        (-0.184, 0.004, -1.10, 0.45),
        (-0.194, -0.075, -1.48, 0.08),
        (-0.190, -0.155, -1.55, 0.02),
    )
    for idx_c, (cy, cz, ny, nz) in enumerate(curva_aba):
        larg_x = 0.148 if idx_c < 4 else (0.140 if idx_c == 4 else 0.122)
        esp = 0.0065
        perfil = (
            (-larg_x, cy + esp * ny, cz + esp * nz),
            (-larg_x * 0.65, cy + esp * ny, cz + esp * nz),
            (0.0, cy + esp * ny, cz + esp * nz),
            (larg_x * 0.65, cy + esp * ny, cz + esp * nz),
            (larg_x, cy + esp * ny, cz + esp * nz),
            (larg_x, cy - esp * ny, cz - esp * nz),
            (larg_x * 0.65, cy - esp * ny, cz - esp * nz),
            (0.0, cy - esp * ny, cz - esp * nz),
            (-larg_x * 0.65, cy - esp * ny, cz - esp * nz),
            (-larg_x, cy - esp * ny, cz - esp * nz),
        )
        aneis_aba.append(list(perfil))
    _adicionar_loft_fechado_bm(bm, aneis_aba, mat_idx=0)

    # 3. Duas tiras verticais dianteiras da aba + fivelas de latao
    for sx in (-0.072, 0.072):
        _adicionar_tubo_curva_bm(
            bm,
            [
                (sx, -0.015, 0.018),
                (sx, -0.065, 0.050),
                (sx, -0.142, 0.052),
                (sx, -0.194, 0.008),
                (sx, -0.203, -0.085),
                (sx, -0.201, -0.175),
                (sx, -0.190, -0.245),
            ],
            r_larg=0.014,
            r_esp=0.0045,
            segs=6,
            mat_idx=0,
        )
        _adicionar_gema_octaedrica_bm(
            bm,
            (sx, -0.208, -0.120),
            (0.020, 0.0065, 0.022),
            rot_euler=(0.0, 0.0, 0.0),
            mat_idx=2,
        )

    # 4. Rolo horizontal de linho/la amarrado no topo (Z > 0) + 2 cintas de couro
    aneis_rolo: list[list[tuple[float, float, float]]] = []
    for ix in range(8):
        tx = ix / 7.0
        x = -0.165 + 0.330 * tx
        estreita = 0.88 if (abs(abs(x) - 0.085) < 0.025) else (0.76 if ix in (0, 7) else 1.0)
        r_rolo = 0.046 * estreita
        anel_r: list[tuple[float, float, float]] = []
        for ir in range(12):
            a = (2.0 * math.pi * ir) / 12.0
            anel_r.append((x, -0.095 + r_rolo * math.cos(a), 0.092 + r_rolo * math.sin(a)))
        aneis_rolo.append(anel_r)
    _adicionar_loft_fechado_bm(
        bm,
        aneis_rolo,
        mat_idx=1,
        ponto_base=(-0.180, -0.095, 0.092),
        ponto_topo=(0.180, -0.095, 0.092),
    )
    rot_y90 = Matrix.Translation((0.0, -0.095, 0.092)) @ Matrix.Rotation(math.pi * 0.5, 4, "Y")
    for sx in (-0.085, 0.085):
        _adicionar_toro_bm(
            bm,
            major_r=0.045,
            minor_r=0.0055,
            segs_major=14,
            segs_minor=6,
            mat_idx=0,
            transform=Matrix.Translation((sx, 0.0, 0.0)) @ rot_y90,
        )

    # 5. Dois bolsos laterais arredondados
    for lado in (-1.0, 1.0):
        aneis_bolso: list[list[tuple[float, float, float]]] = []
        for iz in range(4):
            tz = iz / 3.0
            z = -0.295 + 0.165 * tz
            esc_b = 0.78 + 0.22 * math.sin(math.pi * (0.15 + 0.70 * tz))
            anel_b: list[tuple[float, float, float]] = []
            for ir in range(10):
                a = (2.0 * math.pi * ir) / 10.0
                ca, sa = math.cos(a), math.sin(a)
                sup = (abs(ca) ** 2.6 + abs(sa) ** 2.6) ** (-1.0 / 2.6)
                anel_b.append((
                    lado * (0.160 + 0.032 * esc_b * ca * sup),
                    -0.095 + 0.052 * esc_b * sa * sup,
                    z,
                ))
            aneis_bolso.append(anel_b)
        _adicionar_loft_fechado_bm(
            bm,
            aneis_bolso,
            mat_idx=0,
            ponto_base=(lado * 0.160, -0.095, -0.310),
            ponto_topo=(lado * 0.158, -0.095, -0.118),
        )

    # 6. Duas alcas anatomicas rentes aos ombros e claviculas (+Y_bl) + cinta esternal
    for lado in (-1.0, 1.0):
        _adicionar_tubo_curva_bm(
            bm,
            [
                (lado * 0.092, -0.015, -0.014),
                (lado * 0.104, 0.036, 0.038),
                (lado * 0.108, 0.102, 0.052),
                (lado * 0.110, 0.162, 0.004),
                (lado * 0.102, 0.188, -0.068),
                (lado * 0.132, 0.138, -0.168),
                (lado * 0.168, 0.032, -0.242),
                (lado * 0.135, -0.032, -0.296),
            ],
            r_larg=0.018,
            r_esp=0.0045,
            segs=6,
            mat_idx=0,
        )
    _adicionar_tubo_curva_bm(
        bm,
        [
            (-0.102, 0.192, -0.048),
            (-0.048, 0.198, -0.048),
            (0.0, 0.200, -0.048),
            (0.048, 0.198, -0.048),
            (0.102, 0.192, -0.048),
        ],
        r_larg=0.011,
        r_esp=0.004,
        segs=6,
        mat_idx=0,
    )
    _adicionar_gema_octaedrica_bm(
        bm,
        (0.0, 0.204, -0.048),
        (0.018, 0.006, 0.016),
        mat_idx=2,
    )

    return _bmesh_criar_objeto_multimat(nome, bm, [mat_couro, mat_linho, mat_latao], angulo_suave=48.0)


def _criar_capa_procedural(nome: str = "CapaSimuladaModular") -> "bpy.types.Object":
    """Cria capa de la carmesim com colarinho em U sobre os ombros, pregas profundas e fechos."""
    mat_tecido = _criar_material_pbr_zona(
        "Cape_WovenCloth",
        (0.361, 0.094, 0.125, 1.0),
        metallic=0.0,
        roughness=0.84,
        textura_arquivo="linen_tunic_albedo.png",
        accent_color=(0.20, 0.04, 0.06, 1.0),
        bump_strength=0.22,
        noise_scale=58.0,
        zona_tag="tecido_capa",
        uv_scale=3.5,
        tint_srgb=(0.361, 0.094, 0.125),
    )
    mat_fecho = _criar_material_pbr_zona(
        "Cape_GoldClasp",
        (0.831, 0.686, 0.216, 1.0),
        metallic=0.90,
        roughness=0.25,
        textura_arquivo="bronze_filigree_albedo.png",
        accent_color=(0.50, 0.39, 0.12, 1.0),
        bump_strength=0.08,
        noise_scale=54.0,
        zona_tag="ouro_ornamentado",
    )

    cena = bpy.context.scene
    frame_orig = cena.frame_current

    # Proxy headless de torso e omoplatas para colisao natural do caimento
    bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=12, radius=0.18, location=(0.0, 0.115, -0.27))
    proxy = bpy.context.active_object
    proxy.name = f"{nome}_TorsoColProxy"
    proxy.scale = (1.02, 0.72, 1.65)
    bpy.ops.object.transform_apply(scale=True)
    proxy.modifiers.new(name="TorsoCollision", type="COLLISION")

    # Malha com colarinho em U abracando ombros/claviculas e pregas profundas
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=18, y_subdivisions=24, size=1.0)
    capa = bpy.context.active_object
    capa.name = nome
    for v in capa.data.vertices:
        u = v.co.x * 2.0  # -1..+1
        t = 0.5 - v.co.y  # 0 no colarinho (+Z), 1 na barra (-Z)
        largura_x = 0.195 + 0.175 * t
        x = u * largura_x
        pregas = 0.028 * (0.15 + 0.85 * t) * math.cos(5.0 * math.pi * u)
        u_col = max(0.0, (0.24 - t) / 0.24)
        abraco_u_clavicula = 0.125 * u_col * (abs(u) ** 1.6)
        abraco_ombro = 0.058 * (1.0 - t) * (u * u) + abraco_u_clavicula
        queda_z = 0.024 - 0.86 * t - 0.030 * (1.0 - t) * (u * u) - 0.018 * u_col * (abs(u) ** 2.0)
        y = -0.028 - 0.105 * t + abraco_ombro - pregas
        v.co = Vector((x, y, queda_z))

    vg_pin = capa.vertex_groups.new(name="PinCollar")
    for v in capa.data.vertices:
        if v.co.z > -0.045:
            peso = 1.0 if v.co.z > -0.015 else 0.72
            vg_pin.add([v.index], peso, "REPLACE")

    mc = capa.modifiers.new(name="Cloth", type="CLOTH")
    mc.settings.vertex_group_mass = "PinCollar"
    mc.settings.quality = 6
    mc.settings.mass = 0.42
    mc.settings.tension_stiffness = 14.0
    mc.settings.bending_stiffness = 0.30
    mc.settings.air_damping = 1.15
    mc.collision_settings.use_collision = True
    mc.collision_settings.distance_min = 0.008

    for f in range(1, 36):
        cena.frame_set(f)

    bpy.context.view_layer.objects.active = capa
    bpy.ops.object.modifier_apply(modifier="Cloth")
    bpy.data.objects.remove(proxy, do_unlink=True)
    cena.frame_set(frame_orig)

    ms = capa.modifiers.new(name="SolidifyCloth", type="SOLIDIFY")
    ms.thickness = 0.004
    ms.offset = 0.0
    ms.use_rim = True
    bpy.ops.object.modifier_apply(modifier="SolidifyCloth")

    # Adiciona 2 fechos metalicos sobre as pontas claviculares do colarinho em U
    bm = bmesh.new()
    bm.from_mesh(capa.data)
    for f in bm.faces:
        f.material_index = 0
    for sx in (-0.155, 0.155):
        _adicionar_gema_octaedrica_bm(
            bm,
            (sx, 0.115, 0.004),
            (0.026, 0.013, 0.024),
            rot_euler=(math.radians(18.0), 0.0, sx * -1.2),
            mat_idx=1,
        )
    capa.data.materials.clear()
    capa.data.materials.append(mat_tecido)
    capa.data.materials.append(mat_fecho)

    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bmesh.ops.triangulate(bm, faces=bm.faces)
    while bm.loops.layers.uv:
        bm.loops.layers.uv.remove(bm.loops.layers.uv[0])
    bm.to_mesh(capa.data)
    bm.free()
    _garantir_uv(capa, forcar=True)
    _aplicar_suavizacao_modular(capa, angulo_graus=65.0)
    capa["forge3d_angulo_suave"] = 65.0
    return capa


def _criar_mochila_capa_procedural(
    nome: str = "MochilaCapaModular",
    tipo: str = "mochila",
) -> "bpy.types.Object":
    """Despacha construtor dedicado entre ``mochila`` estruturada e ``capa`` simulada."""
    if str(tipo or "").strip().lower() in ("capa", "asas"):
        return _criar_capa_procedural(nome=nome)
    return _criar_mochila_procedural(nome=nome)


def _criar_orbe_arcano_procedural(nome: str = "OrbeArcanoModular") -> "bpy.types.Object":
    """Cria orbe astrolabio de mao: nucleo estrelado emissivo, vidro refrativo e 2 aneis de ouro."""
    mat_nucleo = _criar_material_pbr_zona(
        "Orb_ArcaneCore",
        (0.094, 0.784, 1.0, 1.0),
        metallic=0.0,
        roughness=0.14,
        emission_color=(0.010, 0.575, 1.0, 1.0),
        emission_strength=2.6,
        zona_tag="nucleo_emissivo",
    )
    mat_vidro = _criar_material_pbr_zona(
        "Orb_RefractiveGlass",
        (0.72, 0.95, 1.0, 0.30),
        metallic=0.0,
        roughness=0.04,
        transmission=0.92,
        ior=1.52,
        alpha=0.28,
        blend_method="BLEND",
        zona_tag="vidro_refrativo",
    )
    mat_ouro = _criar_material_pbr_zona(
        "Orb_AstrolabeGold",
        (0.831, 0.686, 0.216, 1.0),
        metallic=0.94,
        roughness=0.20,
        textura_arquivo="bronze_filigree_albedo.png",
        accent_color=(0.55, 0.42, 0.12, 1.0),
        bump_strength=0.08,
        noise_scale=60.0,
        zona_tag="ouro_astrolabio",
    )

    bm = bmesh.new()

    # 1. Nucleo estrelado arcano interno (r=0.028 m, 80 tris)
    faces_0 = set(bm.faces)
    ret_core = bmesh.ops.create_icosphere(bm, subdivisions=1, radius=0.028)
    for idx_v, v in enumerate(ret_core["verts"]):
        fator = 1.0 if (idx_v % 2 == 0) else 0.72
        v.co *= fator
    _atribuir_mat_novas_faces(bm, faces_0, 0)

    # 2. Casca esferica externa de vidro refrativo (subdiv=3 -> 320 tris suaves, r=0.062 m)
    faces_1 = set(bm.faces)
    bmesh.ops.create_icosphere(bm, subdivisions=3, radius=0.062)
    _atribuir_mat_novas_faces(bm, faces_1, 1)

    # 3. Dois aneis astrolabio circulares inclinados +/-34 graus + 4 engastes cardinais
    rot_pos = Matrix.Rotation(math.radians(34.0), 4, "X") @ Matrix.Rotation(math.radians(10.0), 4, "Y")
    rot_neg = Matrix.Rotation(math.radians(-34.0), 4, "X") @ Matrix.Rotation(math.radians(-10.0), 4, "Y")
    _adicionar_toro_bm(
        bm, major_r=0.075, minor_r=0.005, segs_major=32, segs_minor=10, mat_idx=2, transform=rot_pos
    )
    _adicionar_toro_bm(
        bm, major_r=0.081, minor_r=0.005, segs_major=32, segs_minor=10, mat_idx=2, transform=rot_neg
    )

    for cx, cy, cz, rx, ry, rz in (
        (0.075, 0.0, 0.0, 0.009, 0.007, 0.009),
        (-0.075, 0.0, 0.0, 0.009, 0.007, 0.009),
        (0.0, 0.067, 0.045, 0.007, 0.009, 0.009),
        (0.0, -0.067, -0.045, 0.007, 0.009, 0.009),
    ):
        _adicionar_gema_octaedrica_bm(bm, (cx, cy, cz), (rx, ry, rz), mat_idx=2)

    return _bmesh_criar_objeto_multimat(
        nome, bm, [mat_nucleo, mat_vidro, mat_ouro], angulo_suave=60.0
    )


def _criar_espada_arcana_procedural(nome: str = "EspadaArcanaModular") -> "bpy.types.Object":
    """Cria espada longa forjada centrada na empunhadura (0,0,0), lamina diamante e gema arcana."""
    mat_couro = _criar_material_pbr_zona(
        "Sword_LeatherHilt",
        (0.22, 0.12, 0.07, 1.0),
        metallic=0.0,
        roughness=0.68,
        textura_arquivo="leather_saddle_albedo.png",
        accent_color=(0.12, 0.06, 0.03, 1.0),
        bump_strength=0.18,
        noise_scale=52.0,
        zona_tag="couro_gasto",
    )
    mat_ouro = _criar_material_pbr_zona(
        "Sword_OrnateGold",
        (0.831, 0.686, 0.216, 1.0),
        metallic=0.92,
        roughness=0.24,
        textura_arquivo="bronze_filigree_albedo.png",
        accent_color=(0.52, 0.39, 0.11, 1.0),
        bump_strength=0.10,
        noise_scale=56.0,
        zona_tag="ouro_ornamentado",
    )
    mat_aco = _criar_material_pbr_zona(
        "Sword_ForgedSteel",
        (0.76, 0.80, 0.86, 1.0),
        metallic=0.92,
        roughness=0.28,
        textura_arquivo="steel_forged_albedo.png",
        accent_color=(0.62, 0.67, 0.74, 1.0),
        bump_strength=0.07,
        noise_scale=48.0,
        zona_tag="aco_forjado",
        tint_srgb=(0.76, 0.80, 0.86),
    )
    mat_gema = _criar_material_pbr_zona(
        "Sword_ArcaneGem",
        (0.094, 0.784, 1.0, 1.0),
        metallic=0.0,
        roughness=0.10,
        emission_color=(0.010, 0.575, 1.0, 1.0),
        emission_strength=2.6,
        zona_tag="gema_arcana",
    )

    bm = bmesh.new()

    # 1. Haste oval em couro (Z = -0.068 .. +0.062) + 6 cordoes envoltos centrados na palma (0,0,0)
    aneis_haste: list[list[tuple[float, float, float]]] = []
    for iz, z in enumerate((-0.068, -0.035, 0.0, 0.032, 0.062)):
        waist = 1.06 if iz == 2 else (0.98 if iz in (1, 3) else 0.92)
        anel = [
            (0.015 * waist * math.cos(2.0 * math.pi * k / 12.0),
             0.020 * waist * math.sin(2.0 * math.pi * k / 12.0),
             z)
            for k in range(12)
        ]
        aneis_haste.append(anel)
    _adicionar_loft_fechado_bm(bm, aneis_haste, mat_idx=0)

    for idx_w in range(6):
        zw = -0.052 + 0.020 * idx_w
        rot_cordao = Matrix.Translation((0.0, 0.0, zw)) @ Matrix.Rotation(math.radians(7.0), 4, "Y")
        _adicionar_toro_bm(
            bm,
            major_r=0.0155,
            minor_r=0.0028,
            segs_major=10,
            segs_minor=5,
            rx=1.0,
            ry=1.32,
            mat_idx=0,
            transform=rot_cordao,
        )

    # 2. Pomo facetado em gota invertida (Z = -0.112 .. -0.068)
    aneis_pomo: list[list[tuple[float, float, float]]] = []
    perfil_pomo = (
        (-0.112, 0.006, 0.006),
        (-0.102, 0.019, 0.016),
        (-0.090, 0.026, 0.021),
        (-0.078, 0.022, 0.018),
        (-0.068, 0.015, 0.019),
    )
    for z, rx, ry in perfil_pomo:
        anel = []
        for k in range(10):
            flute = 1.07 if (k % 2 == 0) else 0.94
            ang = (2.0 * math.pi * k) / 10.0
            anel.append((rx * flute * math.cos(ang), ry * flute * math.sin(ang), z))
        aneis_pomo.append(anel)
    _adicionar_loft_fechado_bm(bm, aneis_pomo, mat_idx=1)

    # 3. Guarda em S / quillons alargados (X in [-0.120, +0.120], Z in [+0.062, +0.098])
    aneis_guarda: list[list[tuple[float, float, float]]] = []
    n_g = 17
    for ig in range(n_g):
        u = -1.0 + 2.0 * (ig / float(n_g - 1))
        x = 0.120 * u
        flare = 1.0 + 0.55 * (abs(u) ** 2.4)
        ponta_taper = 0.52 if abs(u) > 0.96 else 1.0
        zc = 0.072 + 0.018 * (u * u) + 0.006 * math.sin(math.pi * u)
        yc = 0.010 * math.sin(math.pi * u)
        hw = 0.009 * flare * ponta_taper
        hh = 0.0085 * flare * ponta_taper
        anel_g = [
            (x, yc - hw, zc),
            (x, yc - hw * 0.45, zc + hh),
            (x, yc + hw * 0.45, zc + hh),
            (x, yc + hw, zc),
            (x, yc + hw * 0.45, zc - hh),
            (x, yc - hw * 0.45, zc - hh),
        ]
        aneis_guarda.append(anel_g)
    _adicionar_loft_fechado_bm(bm, aneis_guarda, mat_idx=1)

    # Colar chanfrado de ricasso + incrustacoes de gema arcana frontal/traseira
    aneis_ricasso: list[list[tuple[float, float, float]]] = []
    for z, sx, sy in ((0.062, 0.025, 0.023), (0.080, 0.036, 0.026), (0.104, 0.029, 0.018)):
        anel_r = []
        for k in range(8):
            ang = (2.0 * math.pi * k) / 8.0 + (math.pi / 8.0)
            anel_r.append((sx * math.cos(ang), sy * math.sin(ang), z))
        aneis_ricasso.append(anel_r)
    _adicionar_loft_fechado_bm(bm, aneis_ricasso, mat_idx=1)
    for sy_g in (-0.022, 0.022):
        _adicionar_gema_octaedrica_bm(bm, (0.0, sy_g, 0.082), (0.011, 0.0065, 0.015), mat_idx=3)

    # 4. Lamina de aco forjado de 8 faces (sulco central hollow-ground + gume duplo + ponta parabolica)
    aneis_lamina: list[list[tuple[float, float, float]]] = []
    n_lam = 16
    for il in range(n_lam):
        t = il / float(n_lam - 1)
        z = 0.095 + (0.905 - 0.095) * t
        if t < 0.72:
            afila_w = 1.0 - 0.24 * (t / 0.72)
        else:
            tp = (t - 0.72) / 0.28
            afila_w = 0.76 * max(0.08, 1.0 - (tp ** 1.55))
        w = 0.034 * afila_w
        esp_crista = 0.0085 * (1.0 - 0.58 * t)
        # Concavidade hollow-ground no meio da lamina (Z ~ 0.14..0.64)
        fuller = 0.62 if (0.05 < t < 0.70) else 0.88
        esp_ombro = esp_crista * fuller
        x_sh = w * 0.34
        anel_l = [
            (-w, 0.0, z),
            (-x_sh, esp_ombro, z),
            (0.0, esp_crista, z),
            (x_sh, esp_ombro, z),
            (w, 0.0, z),
            (x_sh, -esp_ombro, z),
            (0.0, -esp_crista, z),
            (-x_sh, -esp_ombro, z),
        ]
        aneis_lamina.append(anel_l)
    _adicionar_loft_fechado_bm(
        bm,
        aneis_lamina,
        mat_idx=2,
        ponto_topo=(0.0, 0.0, 0.920),
    )

    return _bmesh_criar_objeto_multimat(
        nome, bm, [mat_couro, mat_ouro, mat_aco, mat_gema], angulo_suave=36.0
    )


def _criar_sela_montaria_procedural(nome: str = "SelaMontariaModular") -> "bpy.types.Object":
    """Cria sela anatomica multi-zona em couro trabalhado, assento acolchoado e estribos de bronze."""
    mat_couro = _criar_material_pbr_zona(
        "Saddle_TooledLeather",
        (0.26, 0.14, 0.07, 1.0),
        metallic=0.02,
        roughness=0.66,
        textura_arquivo="leather_saddle_albedo.png",
        accent_color=(0.15, 0.08, 0.04, 1.0),
        bump_strength=0.18,
        noise_scale=44.0,
        zona_tag="leather",
    )
    mat_assento = _criar_material_pbr_zona(
        "Saddle_PaddedSeat",
        (0.36, 0.22, 0.13, 1.0),
        metallic=0.0,
        roughness=0.80,
        textura_arquivo="linen_tunic_albedo.png",
        accent_color=(0.24, 0.14, 0.08, 1.0),
        bump_strength=0.14,
        noise_scale=52.0,
        zona_tag="linen",
    )
    mat_bronze = _criar_material_pbr_zona(
        "Saddle_BrassTrim",
        (0.76, 0.56, 0.24, 1.0),
        metallic=0.90,
        roughness=0.26,
        textura_arquivo="bronze_filigree_albedo.png",
        accent_color=(0.50, 0.36, 0.14, 1.0),
        bump_strength=0.14,
        noise_scale=60.0,
        zona_tag="bronze",
    )

    bm = bmesh.new()
    # Arvore principal da sela em arco invertido U abracando o dorso cilindrico da montaria
    f_pre = set(bm.faces)
    verts_base = _adicionar_caixa_chanfrada(bm, (0.0, 0.0, 0.06), (0.44, 0.48, 0.055), subdiv=3)
    for v in verts_base:
        v.co.z -= 1.05 * (v.co.x ** 2) - 0.22 * (v.co.y ** 2)
    _atribuir_mat_novas_faces(bm, f_pre, 0)

    # Almofada central acolchoada do assento
    f_pre = set(bm.faces)
    verts_pad = _adicionar_caixa_chanfrada(bm, (0.0, -0.01, 0.088), (0.30, 0.30, 0.036), subdiv=2)
    for v in verts_pad:
        v.co.z -= 0.65 * (v.co.x ** 2) - 0.28 * (v.co.y ** 2)
    _atribuir_mat_novas_faces(bm, f_pre, 1)

    # Pomo frontal arqueado (+Y_bl) e cantle traseiro curvo (-Y_bl) + frisos de bronze
    f_pre = set(bm.faces)
    v_pom = _adicionar_caixa_chanfrada(bm, (0.0, 0.19, 0.125), (0.18, 0.075, 0.095), subdiv=2)
    for v in v_pom:
        v.co.z -= 1.2 * (v.co.x ** 2)
    v_can = _adicionar_caixa_chanfrada(bm, (0.0, -0.19, 0.135), (0.28, 0.085, 0.105), subdiv=2)
    for v in v_can:
        v.co.z -= 0.85 * (v.co.x ** 2)
        v.co.y -= 0.20 * (v.co.x ** 2)
    _atribuir_mat_novas_faces(bm, f_pre, 0)

    _adicionar_gema_octaedrica_bm(bm, (0.0, 0.225, 0.145), (0.042, 0.016, 0.032), mat_idx=2)
    _adicionar_gema_octaedrica_bm(bm, (0.0, -0.232, 0.162), (0.085, 0.016, 0.026), mat_idx=2)

    # Abas laterais curvas (flaps) + loros e estribos de bronze (±X_bl)
    for sx in (-1.0, 1.0):
        f_pre = set(bm.faces)
        v_flap = _adicionar_caixa_chanfrada(bm, (sx * 0.215, 0.0, -0.055), (0.028, 0.32, 0.19), subdiv=2)
        for v in v_flap:
            dz = v.co.z - 0.04
            v.co.x += sx * (-0.08 * dz)
        _atribuir_mat_novas_faces(bm, f_pre, 0)

        pts_loro = [
            (sx * 0.195, 0.03, 0.02),
            (sx * 0.228, 0.03, -0.07),
            (sx * 0.242, 0.03, -0.16),
        ]
        _adicionar_tubo_curva_bm(bm, pts_loro, 0.012, 0.004, segs=6, mat_idx=0)
        tm_estribo = Matrix.Translation((sx * 0.244, 0.03, -0.185)) @ Matrix.Rotation(math.pi * 0.5, 4, "Y")
        _adicionar_toro_bm(
            bm, 0.034, 0.006, segs_major=14, segs_minor=6, rx=0.85, ry=1.05, mat_idx=2, transform=tm_estribo
        )

    return _bmesh_criar_objeto_multimat(
        nome,
        bm,
        [mat_couro, mat_assento, mat_bronze],
        angulo_suave=46.0,
    )


def _fechar_ciclos_borda_fan_armor(bm) -> int:
    """Fallback de fechamento por leque no centroide para ciclos de borda nao-planares."""
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
        uv_centros: dict = {}
        for uvl in uv_lays:
            uv_map[uvl] = {
                v: next((lp[uvl].uv.copy() for lp in v.link_loops), Vector((0.5, 0.5)))
                for v in ciclo
            }
            uv_centros[uvl] = sum(uv_map[uvl].values(), Vector((0.0, 0.0))) / len(ciclo)
        mat_idx = f_adj.material_index
        for i in range(len(ciclo)):
            v1 = ciclo[i]
            v2 = ciclo[(i + 1) % len(ciclo)]
            if v1 == v2 or v1 == vc or v2 == vc:
                continue
            if bm.faces.get((v1, v2, vc)) is not None:
                continue
            nf = bm.faces.new((v1, v2, vc))
            nf.material_index = mat_idx
            criadas += 1
            for uvl in uv_lays:
                uv1 = uv_map[uvl][v1]
                uv2 = uv_map[uvl][v2]
                uvc = uv_centros[uvl]
                for lp in nf.loops:
                    if lp.vert == v1:
                        lp[uvl].uv = uv1
                    elif lp.vert == v2:
                        lp[uvl].uv = uv2
                    else:
                        lp[uvl].uv = uvc
    return criadas


def _corrigir_orientacao_componentes_bm(bm) -> None:
    """Inverte faces de componentes manifold fechados com volume assinado negativo."""
    if not bm.faces or not hasattr(bmesh.ops, "reverse_faces"):
        return
    visitadas_f: set = set()
    for f_ini in list(bm.faces):
        if f_ini in visitadas_f or not hasattr(f_ini, "edges"):
            continue
        comp_faces = []
        fila = [f_ini]
        visitadas_f.add(f_ini)
        while fila:
            fc = fila.pop()
            comp_faces.append(fc)
            for e in fc.edges:
                for fn in e.link_faces:
                    if fn not in visitadas_f:
                        visitadas_f.add(fn)
                        fila.append(fn)
        if len(comp_faces) < 4:
            continue
        comp_edges = {e for f in comp_faces for e in f.edges}
        if not comp_edges or any(len(e.link_faces) != 2 for e in comp_edges):
            continue
        comp_verts = {v for f in comp_faces for v in f.verts}
        if not comp_verts:
            continue
        centro = sum((v.co for v in comp_verts), Vector((0.0, 0.0, 0.0))) / float(len(comp_verts))
        vol = 0.0
        for f in comp_faces:
            verts_f = f.verts
            if len(verts_f) < 3:
                continue
            v0 = verts_f[0].co - centro
            for idx in range(1, len(verts_f) - 1):
                v1 = verts_f[idx].co - centro
                v2 = verts_f[idx + 1].co - centro
                vol += v0.dot(v1.cross(v2)) / 6.0
        if vol < 0.0:
            bmesh.ops.reverse_faces(bm, faces=comp_faces)


def _limpar_malha_manifold(obj, *, fechar_bordas: bool = True) -> None:
    """Remove vertices duplicados, fecha bordas abertas, remove degeneradas e arestas nao-manifold."""
    me = obj.data
    bm = bmesh.new()
    bm.from_mesh(me)
    # 2e-5 > sqrt(3)*1e-5 garante que vertices nao colidam na solda round(p, 5) do QC G1
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=2e-5)
    if fechar_bordas:
        bordas = [e for e in bm.edges if len(e.link_faces) == 1]
        if bordas:
            bmesh.ops.holes_fill(bm, edges=bordas, sides=0)
            if any(len(e.link_faces) == 1 for e in bm.edges):
                _fechar_ciclos_borda_fan_armor(bm)
            ilhas = [f for f in bm.faces if all(len(e.link_faces) == 1 for e in f.edges)]
            if ilhas:
                bmesh.ops.delete(bm, geom=ilhas, context="FACES")
    bmesh.ops.triangulate(bm, faces=bm.faces)
    if hasattr(bmesh.ops, "dissolve_degenerate"):
        bmesh.ops.dissolve_degenerate(bm, dist=2e-5, edges=list(bm.edges))
    if hasattr(bm.verts, "index_update"):
        bm.verts.index_update()

    # Remove faces duplicadas ou degeneradas
    vistos: set[frozenset[int]] = set()
    remover_faces = []
    for f in bm.faces:
        chave = frozenset(v.index for v in f.verts)
        if len(chave) < 3 or f.calc_area() < 1e-10 or chave in vistos:
            remover_faces.append(f)
        else:
            vistos.add(chave)
    if remover_faces:
        bmesh.ops.delete(bm, geom=remover_faces, context="FACES")

    # Remove faces excedentes em arestas com >2 faces
    excedentes = set()
    for e in bm.edges:
        if len(e.link_faces) > 2:
            ordenadas = sorted(e.link_faces, key=lambda f: f.calc_area())
            for f in ordenadas[2:]:
                excedentes.add(f)
    if excedentes:
        bmesh.ops.delete(bm, geom=list(excedentes), context="FACES")

    soltos = [v for v in bm.verts if not v.link_faces]
    if soltos:
        bmesh.ops.delete(bm, geom=soltos, context="VERTS")

    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    _corrigir_orientacao_componentes_bm(bm)
    if hasattr(bm, "normal_update"):
        bm.normal_update()
    bm.to_mesh(me)
    bm.free()
    me.update()


def _aplicar_transformes(obj) -> None:
    """Aplica location, rotation e scale mantendo identidade no objeto."""
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)


_MAT_GLTF_PARA_BL_LINHAS = ((1.0, 0.0, 0.0), (0.0, 0.0, -1.0), (0.0, 1.0, 0.0))


def _ajustar_pivo_socket(
    obj,
    parte: str,
    osso_alvo: str,
    cabeca_osso: Vector | None = None,
    matriz_osso: Matrix | None = None,
) -> None:
    """Ajusta o pivo do acessorio rigido para o espaco local do osso alvo (M_bone_rest.inverted())."""
    obj.parent = None
    _aplicar_transformes(obj)

    verts = obj.data.vertices
    if not verts:
        obj.location = Vector((0.0, 0.0, 0.0))
        return

    xs = [v.co.x for v in verts]
    ys = [v.co.y for v in verts]
    zs = [v.co.z for v in verts]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    min_z, max_z = min(zs), max(zs)
    centro = Vector(((min_x + max_x) * 0.5, (min_y + max_y) * 0.5, (min_z + max_z) * 0.5))
    diag = Vector((max_x - min_x, max_y - min_y, max_z - min_z)).length

    ref_cabeca = cabeca_osso
    if ref_cabeca is None and matriz_osso is not None:
        ref_cabeca = matriz_osso.translation.copy()

    # Detecta se a malha foi modelada em coordenadas do corpo (proxima ao osso) ou na origem (procedural)
    lateral_mismatch = (
        ref_cabeca is not None
        and abs(ref_cabeca.x) > 0.12
        and abs(centro.x) < 0.05
        and abs(centro.x - ref_cabeca.x) > 0.15
    )
    na_origem = (
        ref_cabeca is None
        or lateral_mismatch
        or (
            centro.length <= max(diag * 0.6, 0.20)
            and (centro - ref_cabeca).length > max(diag * 0.75, 0.35)
        )
    )

    if not na_origem and matriz_osso is not None:
        m_inv = matriz_osso.inverted_safe()
        p_inv = Matrix(_MAT_GLTF_PARA_BL_LINHAS).to_4x4()
        xform = p_inv @ m_inv
        for v in verts:
            v.co = xform @ v.co
    elif not na_origem and ref_cabeca is not None:
        delta = -ref_cabeca
        for v in verts:
            v.co += delta
    else:
        # Malha standalone centrada na origem: aplica ancoragem canonica por tipo de parte
        if parte == "arma":
            if min_z < -0.05 and max_z > 0.5:
                ancora = Vector((0.0, 0.0, 0.0))
            else:
                ancora = Vector((centro.x, centro.y, min_z + 0.12 * max(max_z - min_z, 1e-4)))
        elif parte == "escudo":
            # Lado interno de pegada no antebraco (-Y_bl), face convexa externa em +Y_bl
            ancora = Vector((centro.x, min_y + 0.15 * max(max_y - min_y, 1e-4), centro.z))
        elif parte == "mochila":
            if min_y < -0.10 and max_y > 0.05 and min_z < -0.25 and max_z > 0.02:
                ancora = Vector((0.0, 0.0, 0.0))
            else:
                ancora = Vector((centro.x, max_y, max_z - 0.12 * max(max_z - min_z, 1e-4)))
        elif parte in ("capa", "asas"):
            if min_z < -0.50 and max_z <= 0.12 and (max_z - min_z) > (max_y - min_y) * 1.5:
                ancora = Vector((0.0, 0.0, 0.0))
            else:
                # Ancoragem dorsal na borda superior-frontal (+Y_bl, z alto) para pender em -Z_bl
                ancora = Vector((centro.x, max_y, max_z - 0.12 * max(max_z - min_z, 1e-4)))
        elif parte == "sela":
            ancora = Vector((centro.x, centro.y, min_z + 0.25 * max(max_z - min_z, 1e-4)))
        else:
            ancora = centro
        for v in verts:
            v.co -= ancora

    # Garante que capa nao sobressaia horizontalmente como prancha (deve pender em -Z_bl)
    if parte == "capa":
        ys_pos = [v.co.y for v in verts]
        zs_pos = [v.co.z for v in verts]
        span_y = max(ys_pos) - min(ys_pos)
        span_z = max(zs_pos) - min(zs_pos)
        if span_y > span_z * 1.5 and span_y > 0.15:
            rot_x = Matrix.Rotation(-math.pi * 0.5, 4, "X")
            for v in verts:
                v.co = rot_x @ v.co
        # Garante que o topo da capa fique proximo a Z=0 e o tecido penda para -Z_bl
        z_topo = max(v.co.z for v in verts)
        if z_topo > 0.15:
            shift_z = 0.08 - z_topo
            for v in verts:
                v.co.z += shift_z

    obj.data.update()
    obj.location = Vector((0.0, 0.0, 0.0))
    obj.rotation_euler = (0.0, 0.0, 0.0)
    obj.scale = Vector((1.0, 1.0, 1.0))
    _aplicar_transformes(obj)


def _limpar_helpers_humano(human_obj) -> None:
    """Remove modificadores MASK e vertices HelperGeometry/JointCubes antes do skinning."""
    for mod in list(human_obj.modifiers):
        if mod.type == "MASK":
            human_obj.modifiers.remove(mod)
    vg = {g.name: g.index for g in human_obj.vertex_groups}
    manter = {vg.get("helper-l-eye"), vg.get("helper-r-eye")} - {None}
    remover = {vg.get("HelperGeometry"), vg.get("JointCubes")} - {None}
    if not remover:
        return
    bm = bmesh.new()
    bm.from_mesh(human_obj.data)
    dl = bm.verts.layers.deform.active
    if dl is not None:
        lixo = [
            v for v in bm.verts
            if (set(v[dl].keys()) & remover) and not (set(v[dl].keys()) & manter)
        ]
        if lixo:
            bmesh.ops.delete(bm, geom=lixo, context="VERTS")
            bm.to_mesh(human_obj.data)
    bm.free()
    human_obj.data.update()


def _tem_normal_map(obj) -> bool:
    for mat in obj.data.materials:
        if mat and mat.use_nodes:
            for node in mat.node_tree.nodes:
                if node.type == "BSDF_PRINCIPLED":
                    inp = node.inputs.get("Normal")
                    if inp is not None and inp.is_linked:
                        return True
    return False


def _medir_geometria(obj) -> tuple[int, int, list[float]]:
    """Calcula contagem de triangulos, vertices e bounding box em metros."""
    tris = sum(len(p.vertices) - 2 for p in obj.data.polygons if len(p.vertices) >= 3)
    verts = len(obj.data.vertices)
    bbox = [max(0.001, round(float(dim), 4)) for dim in obj.dimensions]
    return tris, verts, bbox


def gerar_modular_armor(job: dict) -> dict[str, Any]:
    """Processa peca do set (skinned ou socket) e grava template_armor.glb + relatorio.json."""
    saida = str(job.get("saida") or ".").strip()
    os.makedirs(saida, exist_ok=True)

    parte = str(job.get("parte") or "peitoral").strip().lower()
    if parte == "calças":
        parte = "calcas"

    esqueleto = str(job.get("esqueleto") or "godot-humanoid@1").strip()
    osso_alvo = str(job.get("osso") or _osso_socket(parte, esqueleto))

    if job.get("skinned") is not None:
        skinned = bool(job["skinned"])
    else:
        skinned = _SKINNED_PADRAO.get(parte, False)

    limite_tri = int(job.get("limite_triangulos") or 10000)
    origem_raw = str(job.get("origem") or job.get("mhclo") or "").strip()
    if origem_raw and os.path.splitext(origem_raw)[1].lower() in (".png", ".jpg", ".jpeg", ".webp"):
        if os.path.isfile(origem_raw) and not job.get("textura"):
            job = dict(job, textura=origem_raw)
        origem_raw = ""

    # Limpa cena inicial
    bpy.ops.wm.read_factory_settings(use_empty=True)

    subpasta = "clothes"
    if parte in ("cabelo", "capa") and "hair" in origem_raw:
        subpasta = "hair"
    mhclo_path = _encontrar_mhclo(origem_raw, subpasta=subpasta) if origem_raw else None

    eh_procedural = False
    human = None
    cloth = None
    if not mhclo_path and not skinned and parte in ("escudo", "mochila", "capa", "asas", "orbe", "arma", "sela"):
        eh_procedural = True
        if parte == "escudo":
            cloth = _criar_escudo_procedural()
            mhclo_path = "procedural://escudo"
        elif parte == "mochila":
            cloth = _criar_mochila_procedural()
            mhclo_path = "procedural://mochila"
        elif parte in ("capa", "asas"):
            cloth = _criar_capa_procedural()
            mhclo_path = f"procedural://{parte}"
        elif parte == "orbe":
            cloth = _criar_orbe_arcano_procedural()
            mhclo_path = "procedural://orbe"
        elif parte == "arma":
            cloth = _criar_espada_arcana_procedural()
            mhclo_path = "procedural://arma"
        elif parte == "sela":
            cloth = _criar_sela_montaria_procedural()
            mhclo_path = "procedural://sela"
    else:
        from bl_ext.user_default.mpfb.services.humanservice import HumanService
        from bl_ext.user_default.mpfb.services.targetservice import TargetService

        # 1. Cria humano base com macro CC0 para alinhamento anatomico (+Y frente canonica)
        macro = TargetService.get_default_macro_info_dict()
        macro.update(MACRO_PADRAO)
        if isinstance(job.get("macro"), dict):
            macro.update(job["macro"])
        human = HumanService.create_human(scale=0.1, macro_detail_dict=macro)

        # 2. Localiza e carrega vestuario .mhclo ANTES de bake_targets para casar proporcoes exatas
        if not mhclo_path:
            if parte in ("elmo", "capacete"):
                mhclo_path = _encontrar_mhclo("fedora01", subpasta="clothes")
                cloth = HumanService.add_mhclo_asset(
                    mhclo_path, human, asset_type="Clothes", subdiv_levels=0, set_up_rigging=False
                )
            elif parte in ("botas", "shoes"):
                mhclo_path = _encontrar_mhclo("shoes01", subpasta="clothes")
                cloth = HumanService.add_mhclo_asset(
                    mhclo_path, human, asset_type="Clothes", subdiv_levels=0, set_up_rigging=False
                )
            else:
                mhclo_path = _encontrar_mhclo("male_casualsuit01", subpasta="clothes")
                cloth = HumanService.add_mhclo_asset(
                    mhclo_path, human, asset_type="Clothes", subdiv_levels=0, set_up_rigging=False
                )
        else:
            cloth = HumanService.add_mhclo_asset(
                mhclo_path, human, asset_type="Clothes", subdiv_levels=0, set_up_rigging=False
            )

        if cloth is None or cloth.type != "MESH":
            raise RuntimeError(f"falha ao carregar peca de vestuario '{mhclo_path}'")

        TargetService.bake_targets(human)
        _limpar_helpers_humano(human)

        # Desvincula de human e orienta MPFB2 (-Y) para frente canonica (+Y) antes de auto-rig
        cloth.parent = None
        if not eh_procedural:
            human.rotation_euler.z = math.pi
            cloth.rotation_euler.z = math.pi
        _aplicar_transformes(human)

    if cloth is None or cloth.type != "MESH":
        raise RuntimeError(f"falha ao carregar peca de vestuario '{mhclo_path}'")
    _aplicar_transformes(cloth)

    rig_obj = None
    cabeca_osso = None
    matriz_osso = None
    if skinned and human is not None:
        rig_obj, _ = autorig.auto_rigar_humanoide(human, esqueleto, _criar_armadura)
        if osso_alvo in rig_obj.data.bones:
            bone = rig_obj.data.bones[osso_alvo]
            matriz_osso = bone.matrix_local.copy()
            cabeca_osso = bone.head_local.copy()
    elif human is not None:
        rig_tmp, _ = autorig.auto_rigar_humanoide(human, esqueleto, _criar_armadura)
        if osso_alvo in rig_tmp.data.bones:
            bone = rig_tmp.data.bones[osso_alvo]
            matriz_osso = bone.matrix_local.copy()
            if parte == "orbe":
                # Centro da palma da mao, nunca punho/joelhos
                cabeca_osso = (bone.head_local + bone.tail_local) * 0.5
                matriz_osso.translation = cabeca_osso
            elif parte in ("capa", "mochila", "asas"):
                cabeca_osso = (bone.head_local + bone.tail_local) * 0.5 + Vector((0.0, -0.10, 0.0))
                matriz_osso.translation = cabeca_osso
            else:
                cabeca_osso = bone.head_local.copy()
        bpy.data.objects.remove(rig_tmp, do_unlink=True)

    # Fecha bordas abertas antes do decimate para estabilizar orcamento de triangulos e UVs
    _limpar_malha_manifold(cloth)
    for _ in range(3):
        tris_atuais, _, _ = _medir_geometria(cloth)
        if tris_atuais <= limite_tri or tris_atuais <= 0:
            break
        ratio = max(0.02, min(0.98, float(max(4, limite_tri - 4)) / float(tris_atuais)))
        mod_dec = cloth.modifiers.new(name="DecimateArmor", type="DECIMATE")
        mod_dec.ratio = ratio
        bpy.context.view_layer.objects.active = cloth
        bpy.ops.object.modifier_apply(modifier="DecimateArmor")
        _limpar_malha_manifold(cloth)
    angulo_pos = cloth.get("forge3d_angulo_suave") if hasattr(cloth, "get") else None
    if angulo_pos is None and eh_procedural:
        angulo_pos = {"arma": 36.0, "capa": 65.0, "asas": 65.0}.get(parte, 48.0)
    if angulo_pos is not None:
        _aplicar_suavizacao_modular(cloth, float(angulo_pos))
    _aplicar_estilo_visual(cloth, job)

    sf_cfg = job.get("smart_fit")
    smart_fit_res: dict[str, Any] = {}
    grip_info: dict[str, Any] | None = None
    if parte == "arma" or (isinstance(sf_cfg, dict) and sf_cfg.get("auto_grip")):
        if smart_fit.HAS_BPY:
            frac_cabo = tuple(sf_cfg.get("fracao_cabo") or (0.05, 0.35)) if isinstance(sf_cfg, dict) else (0.05, 0.35)
            grip_info = smart_fit.auto_grip_cilindrico(
                cloth, fracao_cabo=(float(frac_cabo[0]), float(frac_cabo[1]))
            )

    if sf_cfg and smart_fit.HAS_BPY and human is not None:
        sf_dict = sf_cfg if isinstance(sf_cfg, dict) else {}
        folga_m = float(sf_dict.get("folga_m") or smart_fit.FOLGA_CONTATO_PADRAO_M)
        if sf_cfg is True or sf_dict.get("encaixar_contato", True):
            smart_fit_res["encaixar_contato"] = smart_fit.encaixar_contato_bvh(
                cloth,
                human,
                direcao=sf_dict.get("direcao"),
                folga_m=folga_m,
            )
            _aplicar_transformes(cloth)
        if sf_dict.get("conformar_anatomico"):
            smart_fit_res["conformar_anatomico"] = smart_fit.conformar_anatomico(
                cloth,
                human,
                folga_m=folga_m,
                usar_surface_deform=bool(sf_dict.get("usar_surface_deform", True)),
            )
            _limpar_malha_manifold(cloth)
        if sf_dict.get("recortar_oclusao"):
            smart_fit_res["recortar_oclusao"] = smart_fit.recortar_oclusao_interna(
                human,
                [cloth],
                dist_max_m=float(sf_dict.get("dist_max_m", 0.035)),
                limiar_cobertura=float(sf_dict.get("limiar_cobertura", 0.85)),
            )
        if "conformar_anatomico" in smart_fit_res or "recortar_oclusao" in smart_fit_res:
            _garantir_uv(cloth, forcar=True)

    if skinned and rig_obj is not None and human is not None:
        _aplicar_transformes(rig_obj)
        _transferir_pesos_esqueleto(human, cloth, rig_obj, parte=parte)
        if isinstance(sf_cfg, dict) and sf_cfg.get("conformar_punho") and smart_fit.HAS_BPY:
            smart_fit_res["conformar_punho"] = smart_fit.conformar_punho_ao_cabo(
                rig_obj,
                lado=str(sf_cfg.get("lado") or "R"),
                grip_info=sf_cfg.get("grip_info") or grip_info,
            )
        bpy.data.objects.remove(human, do_unlink=True)
        rig_obj.location = Vector((0.0, 0.0, 0.0))
        rig_obj.scale = Vector((1.0, 1.0, 1.0))
        cloth.location = Vector((0.0, 0.0, 0.0))
        cloth.scale = Vector((1.0, 1.0, 1.0))
    else:
        if human is not None:
            bpy.data.objects.remove(human, do_unlink=True)
        _ajustar_pivo_socket(cloth, parte, osso_alvo, cabeca_osso, matriz_osso=matriz_osso)

    tris_final, verts_final, bbox_m = _medir_geometria(cloth)

    # Exporta GLB
    nome_glb = "template_armor.glb"
    caminho_glb = os.path.join(saida, nome_glb)

    bpy.ops.object.select_all(action="DESELECT")
    if skinned and rig_obj is not None:
        rig_obj.select_set(True)
        cloth.select_set(True)
        bpy.context.view_layer.objects.active = cloth
    else:
        cloth.select_set(True)
        bpy.context.view_layer.objects.active = cloth

    export_kwargs: dict[str, Any] = {
        "filepath": caminho_glb,
        "use_selection": True,
        "export_format": "GLB",
        "export_animations": False,
    }
    if _tem_normal_map(cloth):
        export_kwargs["export_tangents"] = True
    bpy.ops.export_scene.gltf(**export_kwargs)

    escala_preservada = bool(skinned and float(job.get("altura_metros", 1.72)) >= 1.2)
    relatorio: dict[str, Any] = {
        "ok": True,
        "armadura_modular": True,
        "parte": parte,
        "skinned": skinned,
        "escala_preservada": escala_preservada,
        "esqueleto": esqueleto if skinned else None,
        "ossos": len(rig_obj.data.bones) if (skinned and rig_obj is not None) else 0,
        "osso": osso_alvo,
        "mhclo": mhclo_path,
        "triangulos": tris_final,
        "vertices": verts_final,
        "bbox_m": bbox_m,
        "arquivo": nome_glb,
    }
    if grip_info is not None:
        relatorio["grip_cilindrico"] = grip_info
    if smart_fit_res:
        relatorio["smart_fit"] = smart_fit_res

    caminho_rel = os.path.join(saida, "relatorio.json")
    with open(caminho_rel, "w", encoding="utf-8") as f:
        json.dump(relatorio, f, indent=2, ensure_ascii=False)

    return relatorio


def main() -> int:
    if "--" not in sys.argv:
        print("uso: blender -b --python blender/modular_armor.py -- <job.json>", file=sys.stderr)
        return 1
    job_file = sys.argv[sys.argv.index("--") + 1]
    with open(job_file, encoding="utf-8") as f:
        job = json.load(f)
    gerar_modular_armor(job)
    return 0


if __name__ == "__main__":
    main()
