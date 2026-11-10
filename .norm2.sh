#!/usr/bin/env bash
set -u
cd /home/eudespatricio/3DCreation || exit 4
timeout 300 blender --background --factory-startup --python tools/normalize_mesh.py -- \
  .scratch/tpose_mesh.glb .scratch/tpose_up.glb 2>&1 | grep -E 'eixo_de_altura|extensao_saida|NORMALIZADO'
timeout 600 blender --background --factory-startup --python tools/render_preview.py -- \
  .scratch/tpose_up.glb .scratch/tpose --size 560 --samples 24 2>&1 | grep -E 'RENDER_OK|BBOX'
