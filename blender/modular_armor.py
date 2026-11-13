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
from mathutils import Vector

_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_DIR)
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)
if _DIR not in sys.path:
    sys.path.insert(0, _DIR)

try:
    import autorig
except ImportError:
    from blender import autorig

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
    "cabelo": "Head",
    "arma": "RightHand",
    "corpo": "HumanoidRootPart",
}

_OSSOS_POR_ESQUELETO: dict[str, dict[str, str]] = {
    "godot-humanoid@1": _OSSOS_SOCKET_PADRAO,
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
    except Exception:
        pass

    try:
        from bl_ext.user_default.mpfb.services.assetservice import AssetService

        raizes.extend(AssetService.get_asset_roots(subpasta))
        raizes.extend(AssetService.get_asset_roots("clothes"))
    except Exception:
        pass

    cfg_dir = ""
    try:
        cfg_dir = bpy.utils.user_resource("CONFIG") or ""
    except Exception:
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


def _transferir_pesos_esqueleto(body_obj, cloth_obj, rig_obj) -> None:
    """Aplica DATA_TRANSFER do corpo base de 23 ossos para a peca de armadura e limpa grupos estranhos."""
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

    # Filtra grupos: mantem apenas os 23 ossos do esqueleto padrao
    ossos_validos = {b.name for b in rig_obj.data.bones}
    for vg in list(cloth_obj.vertex_groups):
        if vg.name not in ossos_validos:
            cloth_obj.vertex_groups.remove(vg)

    autorig._normalizar_grupos_e_mapear(cloth_obj)

    # Vincula Armature modifier
    cloth_obj.parent = rig_obj
    arm_mod = cloth_obj.modifiers.new(name="Armature", type="ARMATURE")
    arm_mod.object = rig_obj


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


def _garantir_uv(obj) -> None:
    """Garante camada UV ativa na malha caso o asset nao possua UVs."""
    if obj.data.uv_layers:
        return
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=1.15, island_margin=0.02)
    bpy.ops.object.mode_set(mode="OBJECT")


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


def _aplicar_estilo_visual(obj, job: dict) -> None:
    """Aplica cor/paleta/prompt/textura de concept e configura Principled BSDF exportavel em glTF."""
    estilo = _resolver_estilo_visual(job)
    textura_path = str(job.get("textura") or "").strip()
    if not textura_path:
        origem_cand = str(job.get("origem") or "").strip()
        if origem_cand and os.path.splitext(origem_cand)[1].lower() in (".png", ".jpg", ".jpeg", ".webp"):
            if os.path.isfile(origem_cand):
                textura_path = origem_cand

    _garantir_uv(obj)

    if not obj.data.materials:
        mat_novo = bpy.data.materials.new(name="Armor_Mat")
        mat_novo.use_nodes = True
        obj.data.materials.append(mat_novo)

    concept_img = None
    if textura_path and os.path.isfile(textura_path):
        concept_img = bpy.data.images.load(os.path.abspath(textura_path), check_existing=True)
        try:
            concept_img.pack()
        except Exception:
            pass

    tint_default = estilo["tint"] or (0.55, 0.58, 0.62)

    for idx_m, mat in enumerate(list(obj.data.materials)):
        if mat is None:
            mat = bpy.data.materials.new(name=f"Armor_Mat_{idx_m}")
            obj.data.materials[idx_m] = mat
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

        if concept_img is not None:
            img_final = (
                _tingir_imagem(concept_img, f"ArmorConcept_{idx_m}", estilo["tint"], estilo["accent"])
                if estilo["tint"] is not None
                else concept_img
            )
        elif tex_node is not None and tex_node.image is not None:
            if estilo["tint"] is not None:
                img_final = _tingir_imagem(tex_node.image, f"ArmorTint_{idx_m}", estilo["tint"], estilo["accent"])
            else:
                img_final = tex_node.image
                try:
                    img_final.pack()
                except Exception:
                    pass
        else:
            img_final = _criar_imagem_tinta(f"ArmorBase_{idx_m}", tint_default, estilo["accent"])

        if tex_node is None:
            tex_node = nt.nodes.new("ShaderNodeTexImage")
        tex_node.image = img_final
        if bc_input:
            for lk in list(bc_input.links):
                nt.links.remove(lk)
            nt.links.new(tex_node.outputs["Color"], bc_input)


def _criar_escudo_procedural(nome: str = "EscudoModular") -> "bpy.types.Object":
    """Cria malha estanque manifold de escudo medieval com UVs quando sem .mhclo."""
    bm = bmesh.new()
    # Perfil de escudo heater estanque com espessura ao longo de Y
    largura = 0.28
    altura = 0.68
    espessura = 0.045
    contorno = [
        (-largura * 0.92, altura * 0.50),
        (largura * 0.92, altura * 0.50),
        (largura * 0.96, altura * 0.14),
        (largura * 0.65, -altura * 0.22),
        (0.0, -altura * 0.50),
        (-largura * 0.65, -altura * 0.22),
        (-largura * 0.96, altura * 0.14),
    ]
    y_frente = espessura * 0.5
    y_tras = -espessura * 0.5
    curvatura = 0.035

    frente_v = []
    tras_v = []
    for x, z in contorno:
        curv = curvatura * (1.0 - (x / largura) ** 2)
        frente_v.append(bm.verts.new((x, y_frente + curv, z)))
        tras_v.append(bm.verts.new((x, y_tras + curv, z)))

    centro_f = bm.verts.new((0.0, y_frente + curvatura + 0.015, 0.04))
    centro_t = bm.verts.new((0.0, y_tras + curvatura - 0.005, 0.04))

    n = len(contorno)
    for i in range(n):
        j = (i + 1) % n
        bm.faces.new((centro_f, frente_v[j], frente_v[i]))
        bm.faces.new((centro_t, tras_v[i], tras_v[j]))
        bm.faces.new((frente_v[i], frente_v[j], tras_v[j], tras_v[i]))

    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bmesh.ops.triangulate(bm, faces=bm.faces)

    me = bpy.data.meshes.new(nome)
    bm.to_mesh(me)
    bm.free()

    obj = bpy.data.objects.new(nome, me)
    bpy.context.collection.objects.link(obj)
    _garantir_uv(obj)
    return obj


def _limpar_malha_manifold(obj) -> None:
    """Remove vertices duplicados, faces degeneradas e arestas nao-manifold pos-decimate."""
    me = obj.data
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    bmesh.ops.triangulate(bm, faces=bm.faces)

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
    bm.to_mesh(me)
    bm.free()
    me.update()


def _aplicar_transformes(obj) -> None:
    """Aplica location, rotation e scale mantendo identidade no objeto."""
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)


def _ajustar_pivo_socket(obj, parte: str, osso_alvo: str, cabeca_osso: Vector | None = None) -> None:
    """Ajusta o ponto de pivo do acessorio rigido aplicando translacao nos vertices e zerando location."""
    obj.parent = None
    _aplicar_transformes(obj)

    verts = obj.data.vertices
    if not verts:
        obj.location = Vector((0.0, 0.0, 0.0))
        return

    if parte == "escudo" or cabeca_osso is None:
        xs = [v.co.x for v in verts]
        ys = [v.co.y for v in verts]
        zs = [v.co.z for v in verts]
        centro = Vector(((min(xs) + max(xs)) * 0.5, (min(ys) + max(ys)) * 0.5, (min(zs) + max(zs)) * 0.5))
        delta = -centro
    else:
        delta = -cabeca_osso

    for v in verts:
        v.co += delta
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

    from bl_ext.user_default.mpfb.services.humanservice import HumanService
    from bl_ext.user_default.mpfb.services.targetservice import TargetService

    # 1. Cria humano base com macro CC0 para alinhamento anatomico (+Y frente canonica)
    macro = TargetService.get_default_macro_info_dict()
    macro.update(MACRO_PADRAO)
    if isinstance(job.get("macro"), dict):
        macro.update(job["macro"])
    human = HumanService.create_human(scale=0.1, macro_detail_dict=macro)

    # 2. Localiza e carrega vestuario .mhclo ANTES de bake_targets para casar proporcoes exatas
    subpasta = "clothes"
    if parte in ("cabelo", "capa") and "hair" in origem_raw:
        subpasta = "hair"
    mhclo_path = _encontrar_mhclo(origem_raw, subpasta=subpasta) if origem_raw else None

    eh_procedural = False
    if not mhclo_path:
        if parte == "escudo":
            cloth = _criar_escudo_procedural()
            mhclo_path = "procedural://escudo"
            eh_procedural = True
        elif parte in ("elmo", "capacete"):
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
    _aplicar_transformes(cloth)

    rig_obj = None
    cabeca_osso = None
    if skinned:
        rig_obj, _ = autorig.auto_rigar_humanoide(human, esqueleto, _criar_armadura)
        if osso_alvo in rig_obj.data.bones:
            cabeca_osso = rig_obj.data.bones[osso_alvo].head_local.copy()
    elif parte != "escudo":
        rig_tmp, _ = autorig.auto_rigar_humanoide(human, esqueleto, _criar_armadura)
        if osso_alvo in rig_tmp.data.bones:
            cabeca_osso = rig_tmp.data.bones[osso_alvo].head_local.copy()
        bpy.data.objects.remove(rig_tmp, do_unlink=True)

    # Decimate antes de transferir pesos / ajustar socket para preservar ordenamento limpo
    tris_atuais, _, _ = _medir_geometria(cloth)
    if tris_atuais > limite_tri and tris_atuais > 0:
        ratio = max(0.05, min(1.0, float(limite_tri) / float(tris_atuais)))
        mod_dec = cloth.modifiers.new(name="DecimateArmor", type="DECIMATE")
        mod_dec.ratio = ratio
        bpy.context.view_layer.objects.active = cloth
        bpy.ops.object.modifier_apply(modifier="DecimateArmor")

    _limpar_malha_manifold(cloth)
    _aplicar_estilo_visual(cloth, job)

    if skinned and rig_obj is not None:
        _aplicar_transformes(rig_obj)
        _transferir_pesos_esqueleto(human, cloth, rig_obj)
        bpy.data.objects.remove(human, do_unlink=True)
        rig_obj.location = Vector((0.0, 0.0, 0.0))
        rig_obj.scale = Vector((1.0, 1.0, 1.0))
        cloth.location = Vector((0.0, 0.0, 0.0))
        cloth.scale = Vector((1.0, 1.0, 1.0))
    else:
        bpy.data.objects.remove(human, do_unlink=True)
        _ajustar_pivo_socket(cloth, parte, osso_alvo, cabeca_osso)

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
    relatorio = {
        "ok": True,
        "armadura_modular": True,
        "parte": parte,
        "skinned": skinned,
        "escala_preservada": escala_preservada,
        "esqueleto": esqueleto if skinned else None,
        "osso": osso_alvo,
        "mhclo": mhclo_path,
        "triangulos": tris_final,
        "vertices": verts_final,
        "bbox_m": bbox_m,
        "arquivo": nome_glb,
    }

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
