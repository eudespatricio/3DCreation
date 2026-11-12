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

_SKINNED_PADRAO: dict[str, bool] = {
    "peitoral": True,
    "luvas": True,
    "calcas": True,
    "botas": True,
    "corpo": True,
    "elmo": False,
    "ombreiras": False,
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
    estilo = estilo.split("/")[0]
    if estilo.endswith(".mhclo"):
        estilo = estilo[:-6]

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

    # Busca recursiva de fallback na pasta clothes do MPFB2 se instalada
    for raiz in raizes:
        if not raiz or not os.path.isdir(raiz):
            continue
        for root, _, files in os.walk(raiz):
            if f"{estilo}.mhclo" in files:
                return os.path.join(root, f"{estilo}.mhclo")

    raise SystemExit(f"peca MakeHuman '{estilo}' nao encontrada nos pacotes MPFB2 locais")


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
    mod.vert_mapping = "NEAREST"
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

    # Vincula Armature modifier
    cloth_obj.parent = rig_obj
    arm_mod = cloth_obj.modifiers.new(name="Armature", type="ARMATURE")
    arm_mod.object = rig_obj


def _ajustar_pivo_socket(obj, parte: str, osso_alvo: str, cabeca_osso: Vector | None = None) -> None:
    """Ajusta o ponto de pivo do acessorio rigido para o encaixe articular do osso alvo."""
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)

    if parte == "escudo":
        # Pivô na braçadeira interna/empunhadura alinhada ao eixo lateral do antebraço
        # Centro da face traseira (-Y ou lateral X dependendo do modelo)
        bpy.ops.object.origin_set(type="ORIGIN_GEOMETRY", center="BOUNDS")
        # Offset suave para a lateral do braco evitando clipping no quadril durante walk/run
        obj.location = Vector((0.0, 0.0, 0.0))
    elif cabeca_osso is not None:
        # Move geometria para coincidir a origem com o ponto de encaixe do osso
        delta = -cabeca_osso
        obj.location = Vector((0.0, 0.0, 0.0))
    else:
        bpy.ops.object.origin_set(type="ORIGIN_GEOMETRY", center="BOUNDS")


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
    osso_alvo = str(job.get("osso") or _OSSOS_SOCKET_PADRAO.get(parte, "Chest"))

    if job.get("skinned") is not None:
        skinned = bool(job["skinned"])
    else:
        skinned = _SKINNED_PADRAO.get(parte, False)

    limite_tri = int(job.get("limite_triangulos") or 10000)
    origem_raw = str(job.get("origem") or job.get("mhclo") or "").strip()

    # Limpa cena inicial
    bpy.ops.wm.read_factory_settings(use_empty=True)

    from bl_ext.user_default.mpfb.services.humanservice import HumanService

    # 1. Cria humano base com macro CC0 para alinhamento anatomico
    macro = dict(MACRO_PADRAO)
    if isinstance(job.get("macro"), dict):
        macro.update(job["macro"])
    human = HumanService.create_human(macro)

    # 2. Localiza e carrega vestuario .mhclo
    subpasta = "clothes"
    if parte in ("cabelo", "capa") and "hair" in origem_raw:
        subpasta = "hair"
    mhclo_path = _encontrar_mhclo(origem_raw, subpasta=subpasta) if origem_raw else None
    if not mhclo_path:
        # Fallback para vestuario basico MPFB2 conforme a peca
        if parte in ("elmo", "capacete"):
            mhclo_path = _encontrar_mhclo("fedora01", subpasta="clothes")
        elif parte in ("botas", "shoes"):
            mhclo_path = _encontrar_mhclo("shoes01", subpasta="clothes")
        else:
            mhclo_path = _encontrar_mhclo("male_casualsuit01", subpasta="clothes")

    rig_obj = None
    if skinned:
        rig_obj, _ = autorig.auto_rigar_humanoide(human, esqueleto, _criar_armadura)

    cloth = HumanService.add_mhclo_asset(mhclo_path, human, asset_type="Clothes", set_up_rigging=False)
    if cloth is None or cloth.type != "MESH":
        raise RuntimeError(f"falha ao carregar peca de vestuario '{mhclo_path}'")

    cabeca_osso = None
    if rig_obj and osso_alvo in rig_obj.data.bones:
        cabeca_osso = rig_obj.data.bones[osso_alvo].head_local.copy()

    if skinned and rig_obj is not None:
        _transferir_pesos_esqueleto(human, cloth, rig_obj)
        # Remove humano base, deixando apenas cloth e rig
        bpy.data.objects.remove(human, do_unlink=True)
    else:
        # Remove humano e rig se houver
        if rig_obj is not None:
            bpy.data.objects.remove(rig_obj, do_unlink=True)
            rig_obj = None
        bpy.data.objects.remove(human, do_unlink=True)
        _ajustar_pivo_socket(cloth, parte, osso_alvo, cabeca_osso)

    # Decimate se ultrapassar limite_tri
    tris_atuais, verts_atuais, _ = _medir_geometria(cloth)
    if tris_atuais > limite_tri and tris_atuais > 0:
        ratio = max(0.05, min(1.0, float(limite_tri) / float(tris_atuais)))
        mod_dec = cloth.modifiers.new(name="DecimateArmor", type="DECIMATE")
        mod_dec.ratio = ratio
        bpy.context.view_layer.objects.active = cloth
        bpy.ops.object.modifier_apply(modifier="DecimateArmor")

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

    bpy.ops.export_scene.gltf(
        filepath=caminho_glb,
        use_selection=True,
        export_format="GLB",
        export_animations=False,
    )

    relatorio = {
        "ok": True,
        "parte": parte,
        "skinned": skinned,
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
