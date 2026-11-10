# GAPS — lacunas abertas

> Regra: toda fase fecha com uma linha `GAP:`. Lacuna sem dono e sem condição de fechamento vira
> arquivo morto — não entra aqui.
> Convenção: `GAP-nnn` · aberto em · fecha em (fase) · condição objetiva · `reabre se`.

| # | Lacuna | Aberto | Fecha em | Condição de fechamento |
|---|---|---|---|---|
| GAP-001 | Allowlist de destino não especificada (Q2) | P0 | P0.5 | formato do arquivo e semântica de erro `FORGE-E-DESTINO` escritos em `DECISOES.md` |
| GAP-002 | Local do `.forge/` não decidido (Q6) | P0 | P0.5 | decisão entre por-projeto e central, com consequência no cache documentada |
| GAP-003 | Tetos já são verificados por `tools/check-p0.py`, mas o script dedicado (`check-contexto.sh`, sem dependência) não existe | P0 | P0.5 | `tools/check-contexto.sh` roda sem `uv` e sai `1` quando um teto estoura |
| GAP-004 | `scan_repo.py` da skill é Luau; lens Python/Blender não portado | P0 | P0.5 | scanner roda em Python puro e produz `radiografia.md` |
| GAP-005 | Rota `mesh` sem nenhuma medição em 6 GB nesta máquina | P0 | P3 | 10 assets com tempo e VRAM medidos em `DECISOES.md` §1 |
| GAP-006 | Escala/rig Roblox não verificados (U1–U4) | P0 | P2 | teste real no Studio; `[verificar]` removido do perfil |
| GAP-007 | Animação reservada e não implementada (D14) | P0 | P5 | clipe base tocando em `godot-humanoid@1` e `r15@1` |
| GAP-008 | Nenhum CI configurado | P0 | P1 | `verify` rodando em pull request com fixture conhecida |
| GAP-009 | Nome do produto indefinido (Q1) | P0 | antes de publicar | `python-package` e CLI renomeados, ou decisão de manter `forge3d` |
| GAP-010 | Q7 (git normal × LFS) indefinida | P0 | antes do 1º asset real no GameZero | decisão + `.gitattributes` no repo do jogo |
| GAP-011 | Filtro `nearest` no import do Godot (U3) não testado | P0 | P1 | textura 16×16 importada sem interpolação |
| GAP-012 | Sem benchmark de `plan` sobre lote grande (1.000 itens) | P0 | P1 | tempo de `plan` < 2 s para 1.000 itens |
| GAP-013 | `draft` (LLM) sem limite de contexto definido (Ollama 4.096) | P0 | P6 | prompt cabendo em 4k com teste de truncamento |
| GAP-014 | Sem política de retenção do ledger | P0 | P6 | `gc`/rotação documentada e testada |

## Como um gap nasce

1. Duas reprovações de QC no mesmo `id` (`qc-e-verificacao.md` §5).
2. Decisão adiada explicitamente em `DECISOES.md` §4.
3. Achado de fase que não bloqueia o portão, mas não pode ser esquecido.
4. Qualquer `[verificar]`/`[estimado]` que vire dependência de código.

## Como um gap morre

Só com a **condição objetiva** cumprida e a evidência registrada (comando, saída ou link). "Resolvido
na conversa" não fecha gap.
