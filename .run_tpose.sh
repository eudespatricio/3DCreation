#!/usr/bin/env bash
# Teste do concept T-pose (OpenPose) no pipeline image-to-3D ja instalado
set -u
PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export PATH
BASE="$HOME/.cache/forge3d"
PY="$BASE/venv-gpu/bin/python"
WORK=/tmp/forge3d_teste
SCRATCH=/home/eudespatricio/3DCreation/.scratch
mkdir -p "$WORK" "$SCRATCH"

ORIGEM="/mnt/c/Users/Eudes/.dsh/attachments/v1/objects/21/214b694dd8de9bb5104c6072dea26a6bb28e78a9c5dbf1e7b4a57ec7eefb2ced"
cp "$ORIGEM" "$WORK/tpose_origem.png"
echo "sha256: $(sha256sum "$WORK/tpose_origem.png" | cut -d' ' -f1)"

echo "=== concept limpo ==="
"$PY" - <<'PY'
from pathlib import Path

from PIL import Image
from rembg import remove

src = Path("/tmp/forge3d_teste/tpose_origem.png")
out = Path("/tmp/forge3d_teste")
img = Image.open(src).convert("RGBA")
print("origem", img.size)
corte = remove(img)
bbox = corte.getbbox()
fundo = Image.new("RGBA", corte.size, (128, 128, 128, 255))
fundo.alpha_composite(corte)
fundo.convert("RGB").save(out / "tpose_concept.png")
print("bbox sujeito", bbox)
if bbox:
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    print(f"foreground {w}x{h} | razao W/H {w/h:.3f} (T-pose deve ser largo)")
PY

echo "=== TripoSR no T-pose ==="
rm -rf "$WORK/saida_tpose"
ini=$(date +%s%N)
cd "$BASE/vendor/TripoSR" || exit 4
"$PY" run.py "$WORK/tpose_origem.png" \
  --output-dir "$WORK/saida_tpose" --model-save-format glb \
  --mc-resolution 256 --foreground-ratio 0.85 2>&1 \
  | grep -E "Running model finished|Extracting mesh finished|Error|error" | tail -4
fim=$(date +%s%N)
echo "tempo_total_ms=$(( (fim - ini) / 1000000 ))"
cp "$WORK/saida_tpose/0/mesh.glb" "$SCRATCH/tpose_mesh.glb" 2>/dev/null && echo "ok tpose_mesh.glb"
find "$WORK/saida_tpose" -name '*.glb' -printf '%p %s\n' 2>/dev/null
