#!/usr/bin/env bash
# O gargalo e resolucao ou o modelo? Marching cubes no shim roda em CPU: 512^3 nao custa VRAM.
set -u
PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export PATH
BASE="$HOME/.cache/forge3d"
PY="$BASE/venv-gpu/bin/python"
WORK=/tmp/forge3d_teste
SCRATCH=/home/eudespatricio/3DCreation/.scratch

echo "=== TripoSR T-pose com mc-resolution 512 ==="
rm -rf "$WORK/saida_tpose512"
ini=$(date +%s%N)
cd "$BASE/vendor/TripoSR" || exit 4
"$PY" run.py "$WORK/tpose_origem.png" \
  --output-dir "$WORK/saida_tpose512" --model-save-format glb \
  --mc-resolution 512 --foreground-ratio 0.85 2>&1 \
  | grep -E "Running model finished|Extracting mesh finished|Error|out of memory" | tail -4
fim=$(date +%s%N)
echo "tempo_total_ms=$(( (fim - ini) / 1000000 ))"
cp "$WORK/saida_tpose512/0/mesh.glb" "$SCRATCH/tpose512.glb" 2>/dev/null && echo "ok tpose512.glb"

cd /home/eudespatricio/3DCreation || exit 4
timeout 300 blender --background --factory-startup --python tools/normalize_mesh.py -- \
  .scratch/tpose512.glb .scratch/tpose512_canon.glb 2>&1 | grep -E 'extensao_saida|NORMALIZADO'
timeout 600 blender --background --factory-startup --python tools/render_preview.py -- \
  .scratch/tpose512_canon.glb .scratch/tpose512 --size 560 --samples 24 2>&1 | grep -E 'RENDER_OK'
