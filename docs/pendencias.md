# Pendências e correções que demandam atenção

> Regra: item sem critério de aceitação não entra aqui — vira conversa.
> Prioridade: **A** = destrava a fase seguinte · **B** = correção que já morde · **C** = dívida aceitável.

Última revisão: 10/11/2026 (P3 fechada para prop + kit blocky; 38 testes verdes).

## 1. Bloqueiam a próxima fase (P3.5/P4)

| # | Pendência | Por que importa | Aceitação | Prio |
|---|---|---|---|---|
| P5 | **Split do input `mesh`**: corpo / capa / arma como três concepts e três malhas | o P3-D foi feito na rota `blocky`; o reconstructor ainda recebe o personagem inteiro e funde a capa (GAP-036) | 3 PNGs separados → 3 GLBs com QC aprovado → montados no Godot | **A** |
| P6 | Provider **concept** (text-to-image) | a rota `mesh` exige `origem`; o `prompt` sozinho não gera imagem (GAP-026) | prompt + seed → PNG, com provider/versão/seed no manifesto | **A** |
| P7 | **Qualidade de personagem** com capa/tecido | bule saiu reconhecível, cadeira saiu blob, capa funde o corpo | 3 personagens com capa, malha fechada e reconhecível, sem fusão | **A** |
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

## 3. Decisões que precisam do operador

| # | Pergunta | Contexto medido | Prio |
|---|---|---|---|
| Q8 | reconstrutor/qualidade: TripoSR × SF3D | **TripoSR escolhido para prop** (bule em 23,3 s, G1–G9 verdes); SF3D encerrado por **D27** (8 min/imagem); personagem com capa continua aberto (GAP-029/036) | **A** |
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
