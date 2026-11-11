#!/usr/bin/env bash
# Prova a distribuicao (P6): build do wheel, instalacao num venv limpo, e a CLI rodando FORA do
# repositorio — se `schemas/` e `profiles/` nao tiverem entrado no pacote, o `validate` quebra.
#
# Nao precisa de Blender nem de GPU: `validate`, `migrate` e `plan` sao CPU puro.
set -euo pipefail
cd "$(dirname "$0")/.."

RAIZ="$(mktemp -d)"
trap 'rm -rf "$RAIZ"' EXIT
export XDG_CONFIG_HOME="$RAIZ/config"
export XDG_STATE_HOME="$RAIZ/state"
unset FORGE3D_ROOT 2>/dev/null || true

echo "== build do wheel =="
uv build --wheel --out-dir "$RAIZ/dist" > "$RAIZ/build.log" 2>&1 || {
    echo "FALHA no build do wheel" >&2
    cat "$RAIZ/build.log" >&2
    exit 1
}
WHEEL="$(find "$RAIZ/dist" -name 'forge3d-*.whl' -print -quit)"
[ -n "$WHEEL" ] || { echo "FALHA: wheel nao gerado" >&2; exit 1; }
echo "  $(basename "$WHEEL")"

echo "== instalacao em venv limpo =="
uv venv --python 3.12 "$RAIZ/venv" > /dev/null 2>&1
uv pip install --python "$RAIZ/venv/bin/python" "$WHEEL" > "$RAIZ/install.log" 2>&1 || {
    echo "FALHA na instalacao" >&2
    cat "$RAIZ/install.log" >&2
    exit 1
}
FORGE3D="$RAIZ/venv/bin/forge3d"
"$FORGE3D" --version

echo "== CLI fora do repositorio, com dados do pacote =="
mkdir -p "$RAIZ/fora"
cp examples/lote_01.yaml "$RAIZ/fora/lote.yaml"
# o exemplo aponta para ~/.local/state: redireciona para o estado isolado deste teste
sed -i "s|^destino_exportacao:.*|destino_exportacao: $RAIZ/state/forge3d/saida/lote_01|" "$RAIZ/fora/lote.yaml"
cd "$RAIZ/fora"
"$FORGE3D" validate lote.yaml
"$FORGE3D" migrate lote.yaml --json | grep -q '"para": "forge3d/spec@3"'
"$FORGE3D" plan lote.yaml --json > "$RAIZ/plan.json"
grep -q '"tarefas"' "$RAIZ/plan.json"

echo "CI_DIST_OK"
