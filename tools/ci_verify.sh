#!/usr/bin/env bash
# Portao de PR com pipeline real (P6): roda um lote minimo, publica num destino temporario
# autorizado e prova que o `verify` passa no destino integro e FALHA no adulterado.
#
# Precisa de Blender 4.2.x no PATH (I9). Nao precisa de GPU: rota blocky.
# Roda hermetico: cache, indice, allowlist e destino vivem em $TMPDIR.
set -euo pipefail
cd "$(dirname "$0")/.."

FORGE3D="${FORGE3D:-.venv/bin/forge3d}"
RAIZ="$(mktemp -d)"
trap 'rm -rf "$RAIZ"' EXIT
export XDG_CONFIG_HOME="$RAIZ/config"
export XDG_STATE_HOME="$RAIZ/state"
unset FORGE3D_ROOT 2>/dev/null || true
DESTINO="$RAIZ/saida"

run() { "$FORGE3D" "$@"; }

echo "== Blender 4.2.x no PATH (I9) =="
command -v blender > /dev/null || { echo "FALHA: Blender fora do PATH (I9)" >&2; exit 1; }
blender --version | head -1 | grep -q "^Blender 4\.2\." || {
    echo "FALHA: Blender nao e 4.2.x: $(blender --version | head -1)" >&2
    exit 1
}

mkdir -p "$RAIZ/lote"
cat > "$RAIZ/lote/minimo.yaml" <<YAML
schema: forge3d/spec@3
projeto: ci
perfil: godot4
destino_exportacao: $DESTINO
estilo_global: blocky_voxel
politica:
  falha: abortar
  custo_max_min: 5
lote:
  - id: ci.bloco.01
    tipo: prop_estatico
    rota: blocky
    prompt: bloco do portao de ci
    altura_metros: 0.5
    tags: [ci]
YAML

run allowlist add "$DESTINO" > /dev/null
run run "$RAIZ/lote/minimo.yaml" --json > "$RAIZ/run.json"

echo "== verify no destino integro =="
run verify "$DESTINO" | tee "$RAIZ/verify_ok.txt"
grep -q "0 problema" "$RAIZ/verify_ok.txt"

echo "== verify tem que morder: um byte trocado no glb =="
GLB="$(find "$DESTINO" -name '*.glb' ! -name '*_colisao.glb' -print -quit)"
[ -n "$GLB" ] || { echo "FALHA: nenhum .glb de malha no destino" >&2; exit 1; }
printf 'x' >> "$GLB"
set +e
run verify "$DESTINO" > "$RAIZ/verify_ruim.txt" 2>&1
rc=$?
set -e
if [ "$rc" -ne 3 ]; then
    echo "FALHA: verify no destino adulterado saiu $rc (contrato: 3)" >&2
    cat "$RAIZ/verify_ruim.txt" >&2
    exit 1
fi
grep -q "hash divergente" "$RAIZ/verify_ruim.txt" || {
    echo "FALHA: verify saiu 3 sem apontar hash divergente" >&2
    cat "$RAIZ/verify_ruim.txt" >&2
    exit 1
}

echo "== regressao de orientacao (GAP-048) =="
PY="${PYTHON:-.venv/bin/python}"
"$PY" -m pytest tests/test_orientacao.py -q

echo "CI_VERIFY_OK"
