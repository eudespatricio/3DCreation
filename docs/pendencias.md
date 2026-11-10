# Pendências e correções que demandam atenção

> Regra: item sem critério de aceitação não entra aqui — vira conversa.
> Prioridade: **A** = destrava a fase seguinte · **B** = correção que já morde · **C** = dívida aceitável.

Última revisão: 10/11/2026 (P3 fechada para prop + kit blocky; 44 verdes + 1 GPU (manual)).

## 1. Bloqueiam a próxima fase (P3.5/P4)

| # | Pendência | Por que importa | Aceitação | Prio |
|---|---|---|---|---|
| P7 | **Qualidade de personagem com capa/tecido** | sentinela e corpo do split saíram reconhecíveis; capa/arma do split saíram blobs (GAP-041) | capa/arma reconhecíveis **ou** rota `blocky` para elas (D39); 3 personagens com capa | **A** |
| P8 | **Roblox P2**: validar o perfil no Studio | segundo perfil de export nunca foi testado; probe 10/11 mostrou que **prop** publica/verifica, mas humanoid falha em `pivot: junta` (fora do enum) e o blocky não gera nomes R15 (Q3/GAP-006) | import no Studio, U1–U4 sem `[verificar]`, R15 com `HumanoidRootPart` e membros nos nomes R15 | **B** |

## 2. Correções que já mordem

| # | Correção | Sintoma hoje | Aceitação | Prio |
|---|---|---|---|---|
| C3 | Sem `gc` de cache e ledger | cache cresce sem teto (orçamento declarado: 20 GB) | `forge3d gc --manter-dias 30` testado | **B** |
| C5 | Flake não reproduzido na suíte e2e (GAP-019) | uma execução deu `ERROR` em 3 fixtures e não repetiu | 10 execuções seguidas verdes, ou causa identificada | **C** |
| C6 | `tools/delegar.py` depende da IDE aberta | falha com mensagem clara, mas não tem caminho sem IDE | decisão entre chave de API e `agentapi` registrada (Q9) | **C** |
| C7 | `verify` de manifesto antigo sem `pivo_regra` pula o pivô (GAP-037) | asset publicado antes do C2 não tem a regra no relatório | todo manifesto novo tem `pivo_regra`; `verify` reprova a ausência | **B** |
| C8 | G7 não mede convexidade (GAP-038) | colisor côncavo passaria no gate | `verify` mede convexidade e reprova | **B** |
| C9 | `rembg` é opcional e explícito (GAP-039) | concept com fundo não neutro entra com fundo ou falha | provider decide por alfa/metadado e registra na versão | **B** |
| C10 | `preflight` ignora `FORGE3D_MODELOS` (GAP-040) | pesos locais fora do HF cache não são vistos | preflight respeita o caminho local | **C** |
| C11 | Prompt do concept pode passar de **77 tokens** (CLIP) e o sufixo duplica `game asset concept art` | o prompt do sentinela já ficou no limite; prompts longos podem ser truncados em silêncio | medir tokens, avisar/truncar com log e remover a duplicata do sufixo | **C** |

## 3. Decisões que precisam do operador

| # | Pergunta | Contexto medido | Prio |
|---|---|---|---|
| Q8 | reconstrutor/qualidade: TripoSR × SF3D | **TripoSR escolhido para prop** (bule em 23,3 s) e **sentinela sem capa** (37,2 s, G1–G9 verdes); SF3D encerrado por **D27** (8 min/imagem); personagem **com capa** continua aberto (GAP-029/036) | **A** |
| Q9 | delegação: chave de API × `agentapi` | `agentapi` é sessão agêntica com execução de ferramenta (GAP-030) | B |
| Q3 | escala/rig Roblox | perfil escrito, nunca validado no Studio | B |
| Q1 | nome definitivo do produto | `forge3d` é provisório | C |
| Q7 | assets no git do jogo: normal × LFS | primeiro asset real ainda não integrado | C |

## 4. Fechado nesta janela (não reabrir)

- **P3-A** bake próprio de UV+textura no `blender/postprocess.py` para malha `COLOR_0`: `smart_project` +
  bake `DIFFUSE/COLOR` 512² em Cycles CPU; G3/G5 verdes; `tests/test_p3_bake.py`.
- **P3-B** provider `i23d` real: TripoSR na venv `~/.cache/forge3d/venv-i23d` via `FORGE3D_VENV_I23D`,
  normalização canônica no pós-processo, lock de GPU, publicação atômica; `prop.bule.exemplo.01` com
  G1–G9 verdes.
- **P3-C** venvs consolidadas: `~/.venvs/triposr` (5,8 GB) removida; só `venv-i23d` (torch 2.4.1).
- **P3-D** kit blocky corpo/capa/arma: `examples/lote_03_kit.yaml`, 3 assets publicados e montados no
  Godot (`Chest`, `Hand.R`).
- **P5** split do input mesh: 3 concepts → **corpo 7.954 / capa 4.972 / arma 1.988 tris** publicados
  (`personagem.sentinel.*.02`) e montados no Godot (`SPLIT_OK`); corpo utilizável, capa/arma blobs
  (GAP-041).
- **P6** concept **SD1.5** local: `examples/lote_05_mesh_concept.yaml` publicou
  `personagem.sentinel.concept.01` **sem `origem`** (7.940 tris, 37,2 s, G1–G9, `providers.texture`
  `concept/sd15`, importado no Godot com AABB idêntico).
- **C1** `doctor` do `mesh`: reporta `pronto (TripoSR, torch 2.4.1+cu121, venv venv-i23d)`.
- **C4** `MAPA.md` reorganizado: **48/60 linhas**, 12 de folga; spec@2 e rota mesh entram no mapa.
- **C2** `verify` reexecuta G1–G9 contra o perfil atual, com topologia em Python puro; manifesto com
  `esperado_m` adulterado reprova em G2.
- **SF3D** encerrado em 6 GB (GAP-032/033/034/035 fechados por **D27**); não reinstalar.
- **Godot 4.3**: bule importado com AABB idêntico ao manifesto; kit montado sem ajuste manual.
- **Schema**: `spec@2` com `parte` (corpo/capa/arma), retrocompatível com `spec@1`; manifesto `@1`.

## 5. Como usar este documento

1. Item concluído sai daqui e vira linha em `DECISOES.md` §1 (fato medido) + commit.
2. Item que cresce vira `GAP` em `docs/gaps.md`.
3. Revisão obrigatória no fim de cada fase — documento de pendência que ninguém poda vira ficção.
