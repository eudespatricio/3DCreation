#!/usr/bin/env bash
# Cria a venv do estagio concept (SD1.5) como copia da venv de i23d + diffusers.
#
# Por que copia: o TripoSR prende transformers==4.35 e o diffusers 0.31 exige >=4.44.
# Sao modelos diferentes, nao duas copias do mesmo i23d (D34/GAP-031).
#
# Uso:
#   bash tools/setup_concept_venv.sh
#   FORGE3D_VENV_CONCEPT=/caminho bash tools/setup_concept_venv.sh
#
# Depois, a primeira geracao baixa os pesos (~2 GB, fp16):
#   FORGE3D_CONCEPT_E2E=1 python -m pytest tests/test_concept_gpu.py -q
set -euo pipefail

BASE="${FORGE3D_VENV_I23D:-$HOME/.cache/forge3d/venv-i23d}"
DEST="${FORGE3D_VENV_CONCEPT:-$HOME/.venvs/concept}"
UV="${UV:-$(command -v uv || true)}"

if [ -z "$UV" ]; then
  echo "uv nao encontrado; instale com: curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
  exit 1
fi
if [ ! -x "$BASE/bin/python" ]; then
  echo "venv de i23d ausente em $BASE; rode primeiro o setup do i23d (docs/dependencias.md §4)" >&2
  exit 1
fi
if [ -e "$DEST" ]; then
  echo "concept venv ja existe: $DEST"
  exit 0
fi

cp -a "$BASE" "$DEST"
"$UV" pip install --python "$DEST/bin/python" \
  "diffusers==0.31.0" "transformers==4.44.2" "accelerate==1.2.1"

"$DEST/bin/python" -c 'import torch, diffusers, transformers, accelerate; print("CONCEPT_STACK", torch.__version__, torch.cuda.is_available(), diffusers.__version__, transformers.__version__, accelerate.__version__)'
echo "concept venv pronta em $DEST; a primeira geracao baixa o SD1.5 (~2 GB)."
