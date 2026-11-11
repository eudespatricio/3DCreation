# GAPS — lacunas abertas

> Regra: toda fase fecha com uma linha `GAP:`. Lacuna sem dono e sem condição de fechamento vira
> arquivo morto — não entra aqui.
> Convenção: `GAP-nnn` · aberto em · fecha em (fase) · condição objetiva.

## Abertos

> Com P0–P6 fechadas, "Fecha em" vencida não é dívida de fase: é **backlog**. Nada aqui bloqueia
> operação; cada linha fica até alguém decidir fazer (ou descartar).

| # | Lacuna | Aberto | Fecha em | Condição de fechamento |
|---|---|---|---|---|
| GAP-004 | A skill `context-recovery` **deste repo** tem só `SKILL.md` + templates: não há scanner (nem Luau — o `scan_repo.py` citado é do projeto `conselho`) | P0 | backlog | lens Python/Blender produzindo `radiografia.md`, se o operador quiser |
| GAP-042 | `empunhadura` foi simplificada para **20 % da altura** (D58); a regra do perfil — "menor secção transversal na faixa inferior 30 %" — não está implementada | P3 | P4 | regra geométrica implementada em função única e medida pelo G2 com o mesmo critério |
| GAP-015 | `draft` (LLM) não existe; Ollama mede 4.096 tokens efetivos | P0 | P6 | prompt cabendo em 4k com teste de truncamento |
| GAP-018 | `query --tag` existe, mas as tags não são indexadas por tabela própria (LIKE) | P1 | P4 | tabela `tags` normalizada quando o índice passar de ~1.000 assets |
| GAP-019 | Uma execução da suíte e2e deu `ERROR` em 3 fixtures (`test_i2`, `test_i13`, `test_rota_import`) com stdout não-JSON, e **não reproduziu** em 3 execuções seguintes (26/26 verdes) | P1 | P1.5 | reproduzir com `-p no:randomly` e capturar o stderr do subprocesso; até lá, tratar suite vermelha como real |
| GAP-021 | Um atlas por asset, sem variantes (dano, time, emissivo); trocar cor exige regerar | P1 | P4 | atlas com 2–3 variantes declaradas na spec |
| GAP-022 | A pose de validação é render manual, não teste: nada no CI falha se o rig inverter eixo | P1 | P2 | teste que compara eixo local de cada osso com o mapa do perfil |
| GAP-023 | **UV estica em face fina:** uma célula serve as 6 faces, então peça de pouca espessura (visor, placa) smear o padrão | P1 | P1.5 | célula por orientação de face (frente/lado/topo/fundo) e G3 medindo densidade de texel por face |
| GAP-024 | **Densidade de herói:** atlas 64² e célula 16 px dão 34,6 px/m; close-up pede ~380 px/m. Sem bevel/inset, toda aresta é viva | P1 | P1.5 | atlas 256–512, célula 32–64, 80–150 peças e chanfro de 1 voxel, medido em close-up |
| GAP-030 | Delegação ao Antigravity é **sessão agêntica** (executa ferramentas), não completude: risco em execução desatendida | P3 | P4 | transporte com escopo restrito ou endpoint de completude com chave própria |
| GAP-048 | **Orientação invertida passa no QC**: a canonicalização decide cabeça-para-baixo por razão topo/base > 1,5 **ou** centro de área < 5,76/12; num personagem com arma grande os dois sinais falham (medido: razão **0,988**, centro **6,18/12**) e o asset sai de cabeça para baixo com G1–G10 verdes | P6 | backlog | heurística que detecte o invertido mesmo com prop grande (ex.: separação de pernas na base × topo) e fixture de regressão do glb, já que `mesh` é D2 |

## Fechados

| # | Lacuna | Aberto | Fecha em | Condição de fechamento |
|---|---|---|---|---|
| ~~GAP-045~~ | ~~Playback do clipe no Roblox não verificado~~ | P5 | **P5 ✔** | `Animation` **116049702979137** (`Priority=Core`) tocando no rig Motor6D no **client** do Play mode: Head anda **0,0949 / 0,0662 studs** em duas execuções (Idle dava 0,0002); `KeyframeSequence` no `.rbxlx`, `.rbxmx` e `upload-animation` no caminho |
| ~~GAP-001~~ | ~~Allowlist de destino (Q2)~~ | P0 | **P0.5 ✔** | fechado por **D23**: allowlist global + sandbox próprio, sem bypass |
| ~~GAP-002~~ | ~~Local do estado (Q6)~~ | P0 | **P0.5 ✔** | fechado por **D24**: tudo em `$FORGE3D_HOME`, nada no repo do jogo |
| ~~GAP-003~~ | ~~Teto de contexto sem script~~ | P0 | **P0.5 ✔** | `tools/check-contexto.sh`, sem dependência, verde |
| ~~GAP-005~~ | ~~Rota `mesh` sem medição em 6 GB~~ | P0 | **P3 ✔** | medido em 10/11/2026: forward 1,2–3,1 s, extração 3,8–4,5 s, total 21–36 s; A/B de 10 assets segue em Q8 |
| ~~GAP-011~~ | ~~Import no Godot não verificado~~ | P1 | **P1.5 ✔** | Godot 4.3 importou com hierarquia, 23 ossos, AABB idêntico ao manifesto e textura aplicada |
| ~~GAP-012~~ | ~~`plan` superestima custo em ~3×~~ | P1 | **P3 ✔** | mesh: 25 s estimados × 23,3 s reais (erro +7%, < 50%); `blocky` continua barato |
| ~~GAP-017~~ | ~~Filtro `nearest` não testado no importador~~ | P0 | **P2 ✔** | Godot 4.3 aplicou `NEAREST_WITH_MIPMAPS` no atlas blocky |
| ~~GAP-025~~ | ~~Rota `mesh` sem inferência~~ | P0 | **P3 ✔** | PNG → TripoSR → GLB com QC aprovado em 6 GB; `prop.bule.exemplo.01` |
| ~~GAP-027~~ | ~~TripoSR não entrega frame canônico~~ | P3 | **P3 ✔** | `canonicalizar` integrado ao pós-processo; Godot 4.3 com AABB idêntico ao manifesto |
| ~~GAP-028~~ | ~~Saída do TripoSR sem UV e sem material~~ | P3 | **P3 ✔** | `--bake-texture` não foi usado; bake próprio no `bpy` (D28), G3/G5 verdes |
| ~~GAP-031~~ | ~~Duas venvs de torch instaladas~~ | P3 | **P3 ✔** | só `~/.cache/forge3d/venv-i23d` (torch 2.4.1); `FORGE3D_VENV_I23D` seleciona; `~/.venvs/triposr` removida |
| ~~GAP-032~~ | ~~SF3D gated com 403~~ | P3 | **P3 ✔** | acesso liberado em 10/11/2026 e geometria extraída; SF3D encerrado por D27 |
| ~~GAP-033~~ | ~~`gpytoolbox` não compila no SF3D~~ | P3 | **P3 ✔** | não se aplica: SF3D encerrado por D27; remesh não está no caminho |
| ~~GAP-034~~ | ~~Bake do SF3D exige kernel CUDA~~ | P3 | **P3 ✔** | não se aplica: bake próprio em CPU no `bpy` (D28); SF3D encerrado por D27 |
| ~~GAP-035~~ | ~~SF3D leva ~8 min/imagem em 6 GB~~ | P3 | **P3 ✔** | decisão consciente **D27**: SF3D não é usado em 6 GB; TripoSR + bake em ~23 s |
| ~~GAP-026~~ | ~~Sem provider de concept text-to-image~~ | P0 | **P3.5 ✔** | sentinela publicada **sem `origem`**, `providers.texture` (`concept/sd15`, revisão, seed), G1–G9 e Godot 4.3 |
| ~~GAP-036~~ | ~~Personagem com capa / split do input mesh~~ | P3 | **P3.5 ✔** | híbrido corpo .02 + capa .03 + arma `blocky` .01 montado no Godot (`CHAR_CAPE_OK`); capa/arma mesh .02 isoladas ficam D39 |
| ~~GAP-041~~ | ~~Capa/arma no split mesh~~ | P3.5 | **P3.5 ✔** | D39/D40: arma vai para `blocky`; capa .03 reconhecível no conjunto; previews `docs/preview/p3_char_cape_*` |
| ~~GAP-029~~ | ~~Qualidade do reconstructor~~ | P3 | **P3.5 ✔** | 3 personagens híbridos (.02/.05/.04 + capa .03 + arma blocky .01), `AB_OK`, G1–G9; `docs/preview/p3_ab_3personagens.png` |
| ~~GAP-014~~ | ~~I3 sem teste de observação durante o run~~ | P1 | **C14 ✔** | `tests/test_atomico.py`: thread observadora não vê arquivo parcial, `spy` em `os.replace` prova destino vazio antes do rename, falha injetada não deixa arquivo final |
| ~~GAP-016~~ | ~~Sem política de retenção do cache~~ | P0 | **P6 parcial ✔** | `forge3d gc --manter-dias 30`, 2 testes; publicado/índice/ledger intocados |
| ~~GAP-008~~ | ~~CI nunca rodou no GitHub~~ | P0 | **C5–C11 ✔** | repo público `github.com/eudespatricio/3DCreation`; run **42942191684** `success` em `cc89da4` e **PR #1** verde nos dois gatilhos (`push` e `pull_request`), merge `7e24615`; job = `tools/ci.sh` com 53 testes + contexto + P0 |
| ~~GAP-037~~ | ~~`verify` pulava o pivô de manifesto antigo~~ | P3 | **C7 ✔** | `verify` reprova manifesto sem `G2.pivo_regra`; `tests/test_correcoes.py` |
| ~~GAP-038~~ | ~~G7 não media convexidade~~ | P1 | **C8 ✔** | `qc.convexidade` mede por componente conexa e reprova; o gate achou colisor não-manifold (22–146 arestas) e o hull foi corrigido; `tests/test_convexidade.py` |
| ~~GAP-039~~ | ~~`rembg` opcional e explícito~~ | P3 | **C9 ✔** | decide por procedência/alfa, com override por env; `rembgauto2` na versão e motivo no `i23d_resultado.json` |
| ~~GAP-040~~ | ~~`preflight` ignorava `FORGE3D_MODELOS`~~ | P3 | **C10 ✔** | `pesos_triposr()` procura env, cache HF e dir padrão; teste dedicado |
| ~~GAP-043~~ | ~~`manifest@1` não declara a unidade do arquivo~~ | P2 | **C15 ✔** | `manifest@2` com `unidades_export`; `verify` aceita `@1` (escala 1.0) e `@2` (escala declarada); schema `schemas/manifest.v2.schema.json` + 13 testes em `tests/test_unidades.py` |
| ~~GAP-006~~ | ~~Roblox: faltava a escala do package~~ | P0 | **P2 ✔** | medido em 11/11/2026: package `2,7086 × 6,6071 × 1,5196` studs (asset **134628989553440**) e `.rbxlx` `6,6071 × 2,7086 × 1,5196` studs — a mesma escala, fixada por D62 |
| ~~GAP-007~~ | ~~Animação reservada e não implementada~~ | P0 | **P5 ✔** | clipe `idle` embutido no glb dos dois esqueletos, retarget por `rig.retarget` (D66) e validado no Godot 4.3 headless (`GODOT_ANIM_OK`, 2,042 s, movimento 0,0697) |
| ~~GAP-020~~ | ~~Personagem sem clipe de animação~~ | P0 | **P5 ✔** | `idle` gerado (D66) e declarado em `manifest@3` (D67); o lado Roblox fechou em **GAP-045** (D69) |
| ~~GAP-044~~ | ~~Rig `.rbxlx` acima do glb~~ | P2 | **P5 ✔** | causa real: o tamanho da Part não permutava Y/Z (**D68**) e o rig esticava para 6,8086; corrigido, o rig mede **6,6071 × 2,7086 × 1,5196 studs**, idêntico ao package. `tests/test_rbx.py::test_export_r15_normaliza_a_altura_para_a_spec` |
| ~~GAP-009~~ | ~~Nome do produto indefinido (Q1)~~ | P0 | **Q1 ✔** | decisão **D72**: o produto continua `forge3d`; a marca, se houver, na vitrine |
| ~~GAP-010~~ | ~~Q7 (git normal × LFS) indefinida~~ | P0 | **Q7 ✔** | decisão **D73**: LFS no repo do jogo (`*.glb`, `*.png`, `*.rbxm`, `*.blend`…), antes do primeiro asset |
| ~~GAP-047~~ | ~~Lado fechado do módulo é parede parcial~~ | P4 | **P4 ✔** | parede de vão inteiro, do topo da placa ao pé-direito e recuada 0,40 m do limite; G1 **nao_manifold=0** nos 10 setores e `verify` 0 problemas, sem boolean — a falha do D75 era **parede×pilar**, e sem pilar (D77) as paredes se cruzam em volume. Renders: `docs/preview/p4_setor_reto_ns_alto.png` e `docs/preview/p4_setor_curva_no_alto.png` |
| ~~GAP-013~~ | ~~LOD de `blocky` sem critério visual~~ | P1 | **P5 ✔** | critério medido (IoU ≥ 0,85, faixa ≥ 0,75, bbox ≤ 2%) em `tools/lod_qualidade.py`; blocky de 300 tris não gera LOD (decimate 0,76/0,55 e ilha com faixa 0,65); bule mesh LOD1 50% passa com 0,993/0,994/0,948 (D71) |
| ~~GAP-046~~ | ~~LOD de personagem `mesh` não medido~~ | P5 | **P5 ✔** | `personagem.sentinel.corpo.02` LOD1 50% (3.978 tris): IoU **0,9800** frente / **0,9865** lado, faixa **0,9712**, bbox ≤ 0,11% — no critério de D71 |

## Como um gap nasce

1. Duas reprovações de QC no mesmo `id` (`qc-e-verificacao.md` §5).
2. Decisão adiada explicitamente em `DECISOES.md` §4.
3. Achado de fase que não bloqueia o portão, mas não pode ser esquecido.
4. Qualquer `[verificar]`/`[estimado]` que vire dependência de código.

## Como um gap morre

Só com a **condição objetiva** cumprida e a evidência registrada (comando, saída ou link). "Resolvido
na conversa" não fecha gap.
