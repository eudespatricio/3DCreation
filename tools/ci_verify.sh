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

echo "== contratos GLB Godot game-ready (Pacote 3) =="
"$PY" - "$GLB" <<'PY'
import ast, json, pathlib, struct, sys

glb_path = pathlib.Path(sys.argv[1])
data = glb_path.read_bytes()
jlen = struct.unpack_from("<I", data, 12)[0]
gltf = json.loads(data[20 : 20 + jlen])

for mat in gltf.get("materials", []):
    assert mat.get("doubleSided", False) is False, f"doubleSided inesperado: {mat}"
nos_malha = [n.get("name") for n in gltf.get("nodes", []) if "mesh" in n]
assert nos_malha == ["ci.bloco.01"], f"nome de no inesperado: {nos_malha}"

tree = ast.parse(pathlib.Path("blender/postprocess.py").read_text(encoding="utf-8"))
fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "desdobrar_uv")
assert abs(ast.literal_eval(fn.args.defaults[0]) - 0.008) < 1e-9
print("GLB_PACOTE3_OK", nos_malha)
PY

GODOT_BIN="${FORGE3D_GODOT:-$(command -v godot || true)}"
if [ -z "$GODOT_BIN" ] && [ -x "$HOME/tools/godot/Godot_v4.3-stable_linux.x86_64" ]; then
    GODOT_BIN="$HOME/tools/godot/Godot_v4.3-stable_linux.x86_64"
fi
if [ -n "$GODOT_BIN" ]; then
    echo "== Godot headless check (addons/forge3d) =="
    "$GODOT_BIN" --headless --path tools/godot_project --check-only --quit --script "$(pwd)/addons/forge3d/post_import.gd"
    "$GODOT_BIN" --headless --path tools/godot_project --check-only --quit --script "$(pwd)/addons/forge3d/plugin.gd"
    "$GODOT_BIN" --headless --path tools/godot_project --script "$(pwd)/tools/godot_post_import_check.gd" -- "$GLB"
fi

echo "CI_VERIFY_OK"
