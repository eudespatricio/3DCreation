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
| ~~GAP-005~~ | ~~Rota `mesh` sem medição em 6 GB~~ | P0 | **P3 parcial ✔** | medido em 10/11/2026: forward 1,8–3,1 s, extração 3,7–4,5 s, total 21–36 s; falta A/B com 10 assets |
| GAP-027 | TripoSR não entrega frame canônico: altura no eixo Y em 2/2 inputs | P3 | P3 | `tools/normalize_mesh.py` integrado ao provider `i23d`, com QC de orientação |
| GAP-028 | Saída do TripoSR sem UV e sem material (só `COLOR_0`): QC G3/G5 reprovam, corretamente. Bake exige `moderngl` + contexto EGL | P3 | P3 | `--bake-texture` funcionando **ou** UV+bake próprios no `bpy` |
| GAP-029 | Qualidade inutilizável nos 2 inputs testados: foto com capa → casca oca; render flat → laje extrudada | P3 | P3 | um input T-pose com sombreamento gerando malha fechada e reconhecível |
| GAP-006 | Escala/rig Roblox não verificados (U1–U4) | P0 | P2 | teste real no Studio; `[verificar]` removido do perfil |
| GAP-007 | Animação reservada e não implementada (D14) | P0 | P5 | clipe base tocando em `godot-humanoid@1` e `r15@1` |
| GAP-008 | Sem CI configurado (testes existem, pipeline não) | P0 | P1.5 | `pytest` + `check-contexto.sh` rodando em pull request |
| GAP-009 | Nome do produto indefinido (Q1) | P0 | antes de publicar | pacote e CLI renomeados, ou decisão de manter `forge3d` |
| GAP-010 | Q7 (git normal × LFS) indefinida | P0 | antes do 1º asset real | decisão + `.gitattributes` no repo do jogo |
| ~~GAP-011~~ | ~~Import no Godot não verificado~~ | P1 | **P1.5 ✔** | fechado em 10/11/2026: Godot 4.3 importou com hierarquia, 23 ossos, AABB idêntico ao manifesto e textura aplicada |
| GAP-012 | `plan` superestima custo em ~3× (9,0 s estimados × 2,08 s reais para 3 itens) | P1 | P2 | estimativa calibrada por medição, com erro < 50 % |
| GAP-013 | LOD de `blocky` usa decimate: reduz tris, mas a qualidade visual não foi avaliada | P1 | P2 | critério visual registrado para `_LOD1`/`_LOD2` |
| GAP-014 | I3 (publish atômico) tem implementação, mas não teste de observação durante o run | P1 | P1.5 | teste que falha se algum arquivo parcial aparecer no destino |
| GAP-015 | `draft` (LLM) não existe; Ollama mede 4.096 tokens efetivos | P0 | P6 | prompt cabendo em 4k com teste de truncamento |
| GAP-016 | Sem política de retenção do ledger e do cache (`gc`) | P0 | P6 | `gc`/rotação documentada e testada |
| ~~GAP-017~~ | ~~Filtro `nearest` não testado no importador~~ | P0 | **P2 ✔** | fechado: Godot 4.3 aplicou `NEAREST_WITH_MIPMAPS` |
| GAP-020 | Personagem sai com rig e sem clipe de animação (D14): no Godot ele é estático até alguém animar | P0 | P5 | clipe `idle` gerado ou retarget validado |
| GAP-025 | **Rota `mesh` sem inferência**: o slot existe, declara D2/custo/licença e reporta o que falta, mas nenhum modelo é chamado (text-to-image e image-to-3D ausentes) | P0 | P3 | um PNG de concept virando `.glb` com QC aprovado, medido em 6 GB |
| GAP-026 | Sem provider de **concept** (text-to-image): nada gera a imagem de entrada | P0 | P3 | PNG gerado por seed, com provedor e versão no manifesto |
| GAP-021 | Um atlas por asset, sem variantes (dano, time, emissivo); trocar cor exige regerar | P1 | P4 | atlas com 2–3 variantes declaradas na spec |
| GAP-022 | A pose de validação é render manual, não teste: nada no CI falha se o rig inverter eixo | P1 | P2 | teste que compara eixo local de cada osso com o mapa do perfil |
| GAP-023 | **UV estica em face fina:** uma célula serve as 6 faces, então peça de pouca espessura (visor, placa) smear o padrão. Visível no close-up de 10/11 | P1 | P1.5 | célula por orientação de face (frente/lado/topo/fundo) e G3 medindo densidade de texel por face |
| GAP-024 | **Densidade de herói:** atlas 64² e célula 16 px dão 34,6 px/m; close-up pede ~380 px/m. Sem bevel/inset, toda aresta é viva | P1 | P1.5 | atlas 256–512, célula 32–64, 80–150 peças e chanfro de 1 voxel, medido em close-up |
| GAP-018 | `query --tag` existe, mas as tags não são indexadas por tabela própria (LIKE) | P1 | P4 | tabela `tags` normalizada quando o índice passar de ~1.000 assets |
| GAP-019 | Uma execução da suíte e2e deu `ERROR` em 3 fixtures (`test_i2`, `test_i13`, `test_rota_import`) com stdout não-JSON, e **não reproduziu** em 3 execuções seguintes (26/26 verdes) | P1 | P1.5 | reproduzir com `-p no:randomly` e capturar o stderr do subprocesso; até lá, tratar suite vermelha como real |

## Como um gap nasce

1. Duas reprovações de QC no mesmo `id` (`qc-e-verificacao.md` §5).
2. Decisão adiada explicitamente em `DECISOES.md` §4.
3. Achado de fase que não bloqueia o portão, mas não pode ser esquecido.
4. Qualquer `[verificar]`/`[estimado]` que vire dependência de código.

## Como um gap morre

Só com a **condição objetiva** cumprida e a evidência registrada (comando, saída ou link). "Resolvido
na conversa" não fecha gap.
