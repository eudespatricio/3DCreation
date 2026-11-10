# GAPS — lacunas abertas

> Regra: toda fase fecha com uma linha `GAP:`. Lacuna sem dono e sem condição de fechamento vira
> arquivo morto — não entra aqui.
> Convenção: `GAP-nnn` · aberto em · fecha em (fase) · condição objetiva.

| # | Lacuna | Aberto | Fecha em | Condição de fechamento |
|---|---|---|---|---|
| ~~GAP-001~~ | ~~Allowlist de destino (Q2)~~ | P0 | **P0.5 ✔** | fechado por **D23**: allowlist global + sandbox próprio, sem bypass |
| ~~GAP-002~~ | ~~Local do estado (Q6)~~ | P0 | **P0.5 ✔** | fechado por **D24**: tudo em `$FORGE3D_HOME`, nada no repo do jogo |
| ~~GAP-003~~ | ~~Teto de contexto sem script~~ | P0 | **P0.5 ✔** | `tools/check-contexto.sh`, sem dependência, verde |
| GAP-004 | `scan_repo.py` da skill ainda é Luau; lens Python/Blender não portado | P0 | P6 | scanner em Python puro produzindo `radiografia.md` |
| GAP-005 | Rota `mesh` sem nenhuma medição em 6 GB nesta máquina | P0 | P3 | 10 assets com tempo e VRAM medidos em `DECISOES.md` §1 |
| GAP-006 | Escala/rig Roblox não verificados (U1–U4) | P0 | P2 | teste real no Studio; `[verificar]` removido do perfil |
| GAP-007 | Animação reservada e não implementada (D14) | P0 | P5 | clipe base tocando em `godot-humanoid@1` e `r15@1` |
| GAP-008 | Sem CI configurado (testes existem, pipeline não) | P0 | P1.5 | `pytest` + `check-contexto.sh` rodando em pull request |
| GAP-009 | Nome do produto indefinido (Q1) | P0 | antes de publicar | pacote e CLI renomeados, ou decisão de manter `forge3d` |
| GAP-010 | Q7 (git normal × LFS) indefinida | P0 | antes do 1º asset real | decisão + `.gitattributes` no repo do jogo |
| GAP-011 | Import no Godot não foi verificado: o portão P1 fala em "sem ajuste manual", mas o teste rodado aqui é QC + manifesto | P1 | P1.5 | um asset importado no Godot 4 sem correção de escala/pivô/material |
| GAP-012 | `plan` superestima custo em ~3× (9,0 s estimados × 2,08 s reais para 3 itens) | P1 | P2 | estimativa calibrada por medição, com erro < 50 % |
| GAP-013 | LOD de `blocky` usa decimate: reduz tris, mas a qualidade visual não foi avaliada | P1 | P2 | critério visual registrado para `_LOD1`/`_LOD2` |
| GAP-014 | I3 (publish atômico) tem implementação, mas não teste de observação durante o run | P1 | P1.5 | teste que falha se algum arquivo parcial aparecer no destino |
| GAP-015 | `draft` (LLM) não existe; Ollama mede 4.096 tokens efetivos | P0 | P6 | prompt cabendo em 4k com teste de truncamento |
| GAP-016 | Sem política de retenção do ledger e do cache (`gc`) | P0 | P6 | `gc`/rotação documentada e testada |
| GAP-017 | Perfil `godot4` com filtro `nearest` não testado no importador (U3) | P0 | P2 | textura 16×16 importada sem interpolação |
| GAP-018 | `query --tag` existe, mas as tags não são indexadas por tabela própria (LIKE) | P1 | P4 | tabela `tags` normalizada quando o índice passar de ~1.000 assets |

## Como um gap nasce

1. Duas reprovações de QC no mesmo `id` (`qc-e-verificacao.md` §5).
2. Decisão adiada explicitamente em `DECISOES.md` §4.
3. Achado de fase que não bloqueia o portão, mas não pode ser esquecido.
4. Qualquer `[verificar]`/`[estimado]` que vire dependência de código.

## Como um gap morre

Só com a **condição objetiva** cumprida e a evidência registrada (comando, saída ou link). "Resolvido
na conversa" não fecha gap.
