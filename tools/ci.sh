#!/usr/bin/env bash
# Portao de CI sem GPU/Blender: unidade + concept + gc + docs/contratos.
# A suite completa (Blender/GPU) roda na maquina do operador.
set -euo pipefail
cd "$(dirname "$0")/.."

PY="${PYTHON:-.venv/bin/python}"

"$PY" -m pytest tests/test_unidade.py tests/test_concept.py tests/test_gc.py tests/test_rbx.py -q
bash tools/check-contexto.sh
"$PY" tools/check-p0.py
