#!/usr/bin/env bash
# Portao de CI sem GPU/Blender: unidade + concept + gc + migrate + docs/contratos.
# A suite completa (Blender/GPU) roda na maquina do operador.
set -euo pipefail
cd "$(dirname "$0")/.."

PY="${PYTHON:-.venv/bin/python}"

"$PY" -m pytest tests/test_unidade.py tests/test_concept.py tests/test_gc.py tests/test_rbx.py \
    tests/test_upload.py tests/test_correcoes.py tests/test_convexidade.py tests/test_pivo.py \
    tests/test_atomico.py tests/test_locks.py tests/test_conformidade.py \
    tests/test_unidades.py tests/test_animacao.py tests/test_lod.py \
    tests/test_modular.py tests/test_modular_provider.py tests/test_migrate.py \
    tests/test_query.py tests/test_verify_only.py tests/test_doc_comandos.py \
    tests/test_seguranca_e_qc.py tests/test_sync.py -q
bash tools/check-contexto.sh
"$PY" tools/check-p0.py
