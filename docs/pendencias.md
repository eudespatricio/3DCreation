# Pendências e correções que demandam atenção

> Regra: item sem critério de aceitação não entra aqui — vira conversa.
> Prioridade: **A** = destrava a fase seguinte · **B** = correção que já morde · **C** = dívida aceitável.

Última revisão: 11/11/2026 (C5–C11 fechados; CI verde no GitHub; suíte 68 + 1 GPU; R15 ainda parcial).

## 1. Bloqueiam a próxima fase (P2/P4)

| # | Pendência | Por que importa | Aceitação | Prio |
|---|---|---|---|---|
| P8 | **Roblox P2**: GUI, textura e bones | Asset 136741921517312 (1 MeshPart + 16 Bones) e **Image 75934318775024 Approved** com `TextureID` setado; o servidor headless não carrega asset privado; faltam GUI, pivôs nos Bones, escala/stud e U1–U4 (Q3/GAP-006) | textura visível no Studio GUI, pivôs nos Bones, U1–U4 sem `[verificar]`, escala/stud | **B** |

## 2. Correções que já mordem

| # | Correção | Sintoma hoje | Aceitação | Prio |
|---|---|---|---|---|
| C12 | Assets publicados antes de 11/11/2026 têm manifesto sem `pivo_regra` e colisor côncavo | `forge3d verify` nesses destinos agora reprova (`C7`/`C8` funcionando como portão) | republicar os destinos antigos (`lote_01`, `lote_03_kit`, `lote_06`, `r15`) ou aceitar o destino como arquivo morto | **B** |

## 3. Decisões que precisam do operador

| # | Pergunta | Contexto medido | Prio |
|---|---|---|---|
| Q9 | delegação: chave de API × `agentapi` | `agentapi` é sessão agêntica com execução de ferramenta (GAP-030) | B |
| Q3 | escala/rig Roblox | upload real + Image aprovada; GUI/textura, pivôs nos Bones, escala/stud e U1–U4 pendentes | B |
| Q1 | nome definitivo do produto | `forge3d` é provisório | C |
| Q7 | assets no git do jogo: normal × LFS | primeiro asset real ainda não integrado | C |

## 4. Fechado nesta janela (não reabrir)

- **C13/D58** `empunhadura` virou regra numérica (20 % da altura) usada pelas duas rotas, e o
  G2 passou a medir os quatro casos (base/centro/topo/empunhadura); a regra do perfil
  ("menor secção transversal") fica em GAP-042.
- **C6/Q9** decidido em 11/11/2026 por **D57**: `delegar.py` fica no `agentapi`, que exige a IDE
  (Antigravity) aberta; sem chave de API e sem caminho headless.
- **C5–C11** fechados em 11/11/2026: 10 execuções seguidas do e2e (C5); `verify` reprova manifesto
  sem `pivo_regra` (C7); G7 mede convexidade por componente e o `convex_hull` foi corrigido — o gate
  achou colisor com 22–146 arestas não-manifold (C8); `rembg` decidido por procedência/alfa (C9);
  `preflight` acha pesos em `FORGE3D_MODELOS` (C10); prompt do CLIP medido/truncado em 77 e sufixo sem
  duplicata (C11). Suíte 68 verdes + 1 GPU; CI verde no GitHub (run 42942191684).
- **P3-A** bake próprio de UV+textura no `blender/postprocess.py` para malha `COLOR_0`: `smart_project` +
  bake `DIFFUSE/COLOR` 512² em Cycles CPU; G3/G5 verdes; `tests/test_p3_bake.py`.
- **P3-B** provider `i23d` real: TripoSR na venv `~/.cache/forge3d/venv-i23d` via `FORGE3D_VENV_I23D`,
  normalização canônica no pós-processo, lock de GPU, publicação atômica; `prop.bule.exemplo.01` com
  G1–G9 verdes.
- **P3-C** venvs consolidadas: `~/.venvs/triposr` (5,8 GB) removida; só `venv-i23d` (torch 2.4.1).
- **P3-D** kit blocky corpo/capa/arma: `examples/lote_03_kit.yaml`, 3 assets publicados e montados no
  Godot (`Chest`, `Hand.R`).
- **P2 export nativo** — `forge3d export-r15` gera `.rbxlx` com 16 Parts + 15 Motor6D, sem upload;
  abre no Studio e passa `R15_RBXLX_PASS partes=16 motores=15`; textura/MeshPart seguem em P8.
- **P2 pivô por membro** — R15 com 16 ossos; `R15_STUDIO_PASS motores=15 partes=16` no Studio e bone
  heads do GLB nos joints (D47); import de malha/textura segue em P8.
- **P7** A/B de **3 personagens híbridos**: .02/.05/.04 + capa .03 + arma `blocky` .01, `AB_OK`,
  G1–G9; imagem `docs/preview/p3_ab_3personagens.png`.
- **C3** `forge3d gc --manter-dias 30` com 2 testes; não toca publicado/índice/ledger.
- **Q8** TripoSR escolhido: 3 personagens híbridos medidos; SF3D encerrado (D27).
- **P5** split do input mesh: 3 concepts → **corpo 7.954 / capa 4.972 / arma 1.988 tris** publicados
  (`personagem.sentinel.*.02`) e montados no Godot (`SPLIT_OK`); corpo utilizável, capa/arma blobs
  (GAP-041).
- **P6** concept **SD1.5** local: `examples/lote_05_mesh_concept.yaml` publicou
  `personagem.sentinel.concept.01` **sem `origem`** (7.940 tris, 37,2 s, G1–G9, `providers.texture`
  `concept/sd15`, importado no Godot com AABB idêntico).
- **C1** `doctor` do `mesh`: reporta `pronto (TripoSR, torch 2.4.1+cu121, venv venv-i23d)`.
- **C4** `MAPA.md` reorganizado: **49/60 linhas**, 11 de folga; spec@2, mesh, concept, split e gc entram no mapa.
- **C2** `verify` reexecuta G1–G9 contra o perfil atual, com topologia em Python puro; manifesto com
  `esperado_m` adulterado reprova em G2.
- **SF3D** encerrado em 6 GB (GAP-032/033/034/035 fechados por **D27**); não reinstalar.
- **Godot 4.3**: bule importado com AABB idêntico ao manifesto; kit montado sem ajuste manual.
- **Schema**: `spec@2` com `parte` (corpo/capa/arma), retrocompatível com `spec@1`; manifesto `@1`.

## 5. Como usar este documento

1. Item concluído sai daqui e vira linha em `DECISOES.md` §1 (fato medido) + commit.
2. Item que cresce vira `GAP` em `docs/gaps.md`.
3. Revisão obrigatória no fim de cada fase — documento de pendência que ninguém poda vira ficção.
