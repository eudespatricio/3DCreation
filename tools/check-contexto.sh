#!/usr/bin/env bash
# Portao de contexto do Forge3D — sem dependencia, roda em qualquer shell.
# GAP-003. Reproduz os tetos de AGENTS.md e falha quando algum estoura.
set -u
cd "$(dirname "$0")/.." || exit 4

limite() {
  local arquivo="$1" teto="$2" linhas
  [ -f "$arquivo" ] || { printf 'FALTA %s\n' "$arquivo"; return 1; }
  linhas=$(wc -l < "$arquivo")
  if [ "$linhas" -gt "$teto" ]; then
    printf 'ESTOURO %-16s %4d > %d\n' "$arquivo" "$linhas" "$teto"
    return 1
  fi
  printf 'ok      %-16s %4d <= %d\n' "$arquivo" "$linhas" "$teto"
}

estado=0
limite MAPA.md 60 || estado=1
limite AGENTS.md 80 || estado=1
limite INVARIANTES.md 220 || estado=1
limite CONTINUAR.md 220 || estado=1
limite CONSELHOS.md 140 || estado=1

# todo caminho citado no MAPA precisa existir (mapa que mente e pior que mapa nenhum)
if command -v grep >/dev/null 2>&1; then
  while IFS= read -r alvo; do
    case "$alvo" in
      ''|*'*'*|'('*) continue ;;
      */*) ;;            # so caminhos relativos com diretorio
      *) continue ;;     # 'comandos.py' dentro de uma celula nao e caminho do repo
    esac
    if [ ! -e "$alvo" ] && [ ! -e "${alvo%% *}" ]; then
      printf 'MAPA cita caminho inexistente: %s\n' "$alvo"
      estado=1
    fi
  done < <(grep -oE '`[A-Za-z0-9_./-]+\.(md|json|yaml|py|sh)`' MAPA.md | tr -d '`' | sort -u)
fi

if [ "$estado" -eq 0 ]; then
  echo "contexto: verde"
else
  echo "contexto: FALHOU"
fi
exit "$estado"
