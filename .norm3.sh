#!/usr/bin/env bash
set -u
cd /home/eudespatricio/3DCreation || exit 4
for n in tpose_mesh android_recon i23d_mesh2; do
  echo "--- $n ---"
  timeout 300 blender --background --factory-startup --python tools/normalize_mesh.py -- \
    ".scratch/${n}.glb" ".scratch/${n}_canon.glb" 2>&1 \
    | grep -E 'extensao_entrada|mapeamento|extensao_saida|NORMALIZADO'
done
echo "=== render T-pose canonico ==="
timeout 600 blender --background --factory-startup --python tools/render_preview.py -- \
  .scratch/tpose_mesh_canon.glb .scratch/tpose_canon --size 560 --samples 24 2>&1 | grep -E 'RENDER_OK|BBOX'
