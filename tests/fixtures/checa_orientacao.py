"""Roda a canonicalizacao real (blender/postprocess.py) sobre um glb e imprime o info em JSON.

Uso (dentro do Blender):
    blender --background --factory-startup --python tests/fixtures/checa_orientacao.py -- \
        <glb> <arquivo postprocess.py>
"""
import importlib.util
import json
import sys

import bpy

argv = sys.argv[sys.argv.index("--") + 1 :]
glb, script_post = argv[0], argv[1]

spec = importlib.util.spec_from_file_location("forge3d_postprocess", script_post)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=glb)
obj = next(o for o in bpy.context.scene.objects if o.type == "MESH")
bpy.context.view_layer.objects.active = obj
obj.select_set(True)

info = mod.canonicalizar(obj, "personagem_humanoide")
print("RESULTADO " + json.dumps(info, sort_keys=True))
