#!/usr/bin/env bash
# Portao de CI sem GPU/Blender: unidade + concept + gc + docs/contratos.
# A suite completa (Blender/GPU) roda na maquina do operador.
set -euo pipefail
cd "$(dirname "$0")/.."

PY="${PYTHON:-.venv/bin/python}"

"$PY" -m pytest tests/test_unidade.py tests/test_concept.py tests/test_gc.py tests/test_rbx.py \
    tests/test_upload.py tests/test_correcoes.py tests/test_convexidade.py tests/test_pivo.py \
    tests/test_atomico.py tests/test_locks.py tests/test_conformidade.py \
    tests/test_unidades.py tests/test_animacao.py -q
bash tools/check-contexto.sh
"$PY" tools/check-p0.py
