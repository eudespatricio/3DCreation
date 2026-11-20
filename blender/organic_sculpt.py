"""Soldagem organica por voxel (``REMESH VOXEL``) e ``CORRECTIVE_SMOOTH`` no Blender 4.2+.

Funde primitivas/capsulas organicas disjuntas (ex.: corpo + cabeca + membros de criatura/montaria)
em uma unica malha continua watertight antes do auto-rig e do bake PBR, preservando atributos de
cor por vertice (``COLOR_0``) por amostragem espacial ``KDTree`` quando presentes.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys

import bpy

if __package__:
    from . import organic_sculpt_criatura as _cr
    from . import organic_sculpt_weld as _wd
else:
    _BLENDER_DIR = os.path.dirname(os.path.abspath(__file__))
    if _BLENDER_DIR not in sys.path:
        sys.path.insert(0, _BLENDER_DIR)
    import organic_sculpt_criatura as _cr
    import organic_sculpt_weld as _wd

__all__ = [
    "aplicar_corrective_smooth",
    "contar_componentes",
    "gerar_criatura_anatomica",
    "soldar_componentes_organicos",
]

_selecionar = _wd._selecionar
contar_componentes = _wd.contar_componentes
_suavizar_taubin_fallback = _wd._suavizar_taubin_fallback
aplicar_corrective_smooth = _wd.aplicar_corrective_smooth
_capturar_cores_vertices = _wd._capturar_cores_vertices
_restaurar_cores_vertices = _wd._restaurar_cores_vertices
_remover_ilhas_menores = _wd._remover_ilhas_menores
soldar_componentes_organicos = _wd.soldar_componentes_organicos

_adicionar_tubo_anatomico = _cr._adicionar_tubo_anatomico
_adicionar_membrana_asa = _cr._adicionar_membrana_asa
_construir_bm_criatura_anatomica = _cr._construir_bm_criatura_anatomica
_pintar_cores_vertice_criatura = _cr._pintar_cores_vertice_criatura
_gerar_uv_criatura = _cr._gerar_uv_criatura


def gerar_criatura_anatomica(job: dict) -> dict:
    """Gera criatura quadrupede ou montaria alada 4-patas anatomica em espaco Blender (+Y frente, +Z cima).

    Exporta ``bruto.glb`` e ``modelo.json`` (``frente="+Y"``, ``canonicalizar=False``) prontos
    para o estagio de pos-processamento, bake PBR 3D (``escamas_dragao``) e auto-rigging.
    """
    bpy.ops.wm.read_factory_settings(use_empty=True)

    tipo = str(job.get("tipo", "criatura_alada"))
    esqueleto = str(job.get("esqueleto", ""))
    com_asas = bool(
        job.get(
            "asas",
            tipo == "criatura_alada" or esqueleto == "winged_mount@1",
        )
    )
    voxel_ratio = float(job.get("voxel_ratio", 1.0 / 138.0))
    iteracoes_smooth = int(job.get("iteracoes_smooth", 2))

    bm = _construir_bm_criatura_anatomica(com_asas=com_asas)
    mesh = bpy.data.meshes.new("CriaturaAnatomicaMesh")
    bm.to_mesh(mesh)
    bm.free()

    obj = bpy.data.objects.new("CriaturaAnatomica", mesh)
    bpy.context.scene.collection.objects.link(obj)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)

    # Solda todos os membros em uma unica malha manifold via Voxel Remesh + Corrective Smooth
    info_solda = soldar_componentes_organicos(
        obj,
        voxel_ratio=voxel_ratio,
        iteracoes_smooth=iteracoes_smooth,
    )

    # Re-nivela as 4 patas exatamente em Z = 0.0 apos a suavizacao e garante apoio plantar firme
    verts = obj.data.vertices
    if verts:
        xs = [v.co.x for v in verts]
        zs = [v.co.z for v in verts]
        cx = 0.5 * (min(xs) + max(xs))
        z_min = min(zs)
        for v in verts:
            v.co.x -= cx
            z_rel = max(0.0, v.co.z - z_min)
            if z_rel < 0.032:
                v.co.z = 0.0
            else:
                v.co.z = z_rel - 0.032
        obj.data.update()

    for poly in obj.data.polygons:
        poly.use_smooth = True

    _gerar_uv_criatura(obj)
    _pintar_cores_vertice_criatura(obj.data)

    # Material base compativel com glTF + vertex color / bake PBR posterior
    mat = bpy.data.materials.new(name="CriaturaBaseMat")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        vcol_node = mat.node_tree.nodes.new(type="ShaderNodeVertexColor")
        vcol_node.layer_name = "COLOR_0"
        mat.node_tree.links.new(vcol_node.outputs["Color"], bsdf.inputs["Base Color"])
        bsdf.inputs["Roughness"].default_value = 0.45
        bsdf.inputs["Metallic"].default_value = 0.0
    obj.data.materials.clear()
    obj.data.materials.append(mat)

    saida_dir_str = job.get("saida_dir")
    if saida_dir_str:
        saida_dir = Path(str(saida_dir_str))
    elif job.get("saida_glb"):
        saida_dir = Path(str(job["saida_glb"])).parent
    else:
        saida_dir = Path(".")
    saida_dir.mkdir(parents=True, exist_ok=True)

    nome_glb = Path(str(job.get("saida_glb", saida_dir / "bruto.glb"))).name
    caminho_glb = Path(str(job.get("saida_glb", saida_dir / nome_glb)))
    caminho_meta = Path(str(job.get("saida_meta", saida_dir / "modelo.json")))

    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    export_kwargs = {
        "filepath": str(caminho_glb),
        "export_format": "GLB",
        "use_selection": True,
        "export_yup": True,
        "export_apply": True,
        "export_normals": True,
        "export_colors": True,
        "export_vertex_color": "MATERIAL",
        "export_materials": "EXPORT",
    }
    props_gltf = set(bpy.ops.export_scene.gltf.get_rna_type().properties.keys())
    export_kwargs = {k: v for k, v in export_kwargs.items() if k in props_gltf}
    bpy.ops.export_scene.gltf(**export_kwargs)

    xs = [v.co.x for v in obj.data.vertices]
    ys = [v.co.y for v in obj.data.vertices]
    zs = [v.co.z for v in obj.data.vertices]
    meta = {
        "schema": "forge3d/bruto-arquivo@1",
        "provider": "anatomical_creature_sculpt",
        "arquivo": caminho_glb.name,
        "frente": "+Y",
        "canonicalizar": False,
        "proteger_decimate": True,
        "tipo": tipo,
        "asas": com_asas,
        "solda": info_solda,
        "vertices": len(obj.data.vertices),
        "triangulos": sum(max(0, len(p.vertices) - 2) for p in obj.data.polygons),
        "dimensoes_bl": {
            "largura_x": round(max(xs) - min(xs), 4) if xs else 0.0,
            "comprimento_y": round(max(ys) - min(ys), 4) if ys else 0.0,
            "altura_z": round(max(zs) - min(zs), 4) if zs else 0.0,
        },
    }
    caminho_meta.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return meta


def _cli() -> None:
    argv = sys.argv
    if "--" not in argv:
        raise SystemExit("uso: blender -b --factory-startup --python blender/organic_sculpt.py -- <job.json>")
    args = argv[argv.index("--") + 1 :]
    caminho_job: Path | None = None
    i = 0
    while i < len(args):
        if args[i] == "--modo" and i + 1 < len(args):
            i += 2
            continue
        caminho_job = Path(args[i])
        i += 1
    if caminho_job is None:
        raise SystemExit("job.json nao informado")
    job = json.loads(caminho_job.read_text(encoding="utf-8"))
    gerar_criatura_anatomica(job)


if __name__ == "__main__":
    _cli()
