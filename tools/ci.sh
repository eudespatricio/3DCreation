#!/usr/bin/env bash
# Portao de CI sem GPU/Blender: toda a suite Python nao-Blender/nao-GPU + lint + types + P0.
# A suite completa (Blender/Godot) roda em tools/ci_verify.sh e na maquina do operador.
set -euo pipefail
cd "$(dirname "$0")/.."

PY="${PYTHON:-.venv/bin/python}"

"$PY" -m pytest -m "not gpu and not blender" -q
if "$PY" -m ruff --version >/dev/null 2>&1; then
    "$PY" -m ruff check src tests tools blender
fi
if "$PY" -m mypy --version >/dev/null 2>&1; then
    "$PY" -m mypy src
fi
bash tools/check-contexto.sh
"$PY" tools/check-p0.py
