#!/usr/bin/env bash
# Configura a API key (fora do repo) e o creator ID, e roda o dry-run/upload do R15.
# Rode em um terminal WSL, de dentro do repo:
#   bash tools/configurar_roblox.sh
set -euo pipefail
cd "$(dirname "$0")/.."

BASE="${HOME:-$(getent passwd "$(id -u)" | cut -d: -f6)}"
KEY_FILE="${FORGE3D_ROBLOX_API_KEY_FILE:-$BASE/.config/forge3d/roblox.key}"
GLB="${1:-$BASE/.local/state/forge3d/saida/r15/personagem.r15.guard.01.glb}"

if [ -n "${FORGE3D_ROBLOX_API_KEY:-}" ]; then
  KEY="$FORGE3D_ROBLOX_API_KEY"
  echo "usando FORGE3D_ROBLOX_API_KEY do ambiente"
else
  printf 'API key (nao aparece no terminal): '
  if [ -t 0 ]; then
    IFS= read -r -s KEY
    printf '\n'
  else
    IFS= read -r KEY
  fi
fi
if [ -z "$KEY" ]; then
  echo "key vazia; nada foi salvo"
  exit 1
fi
mkdir -p "$(dirname "$KEY_FILE")"
chmod 700 "$(dirname "$KEY_FILE")"
printf '%s' "$KEY" > "$KEY_FILE"
chmod 600 "$KEY_FILE"
printf 'key salva em %s (%s caracteres, modo 600)\n' "$KEY_FILE" "${#KEY}"

printf 'Creator ID (user ID do perfil ou group ID): '
IFS= read -r CREATOR
if [ -z "$CREATOR" ]; then
  echo "creator ID vazio; nada foi enviado"
  exit 1
fi
printf 'Tipo [user/group] (user): '
IFS= read -r TIPO
TIPO="${TIPO:-user}"
case "$TIPO" in
  user|group) ;;
  *) echo "tipo invalido: use user ou group"; exit 1 ;;
esac

if [ ! -f "$GLB" ]; then
  printf 'Caminho do GLB: '
  IFS= read -r GLB
fi
if [ ! -f "$GLB" ]; then
  echo "GLB nao encontrado: $GLB"
  exit 1
fi

echo
echo "Dry-run (sem rede):"
FORGE3D_ROBLOX_API_KEY_FILE="$KEY_FILE" .venv/bin/forge3d upload-model "$GLB" \
  --creator-id "$CREATOR" --creator-type "$TIPO" --dry-run

printf 'Upload real agora? [s/N]: '
IFS= read -r RESP
case "$RESP" in
  s|S|sim|SIM)
    echo
    echo "Enviando para o Open Cloud..."
    FORGE3D_ROBLOX_API_KEY_FILE="$KEY_FILE" .venv/bin/forge3d upload-model "$GLB" \
      --creator-id "$CREATOR" --creator-type "$TIPO" --nome "Forge3D R15 Guard"
    ;;
  *)
    echo "dry-run apenas; a key ficou salva."
    ;;
esac
