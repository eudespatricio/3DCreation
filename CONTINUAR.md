# CONTINUAR — handoff de sessão

**Data:** 10/11/2026 · **P0, P0.5 e P1 fechadas. P3/P3.5 fechadas para prop, concept→mesh e 3
personagens híbridos com capa; P2 parcial (R15 16 ossos, pivô, `.rbxlx`, Model/Image aprovados; falta GUI).** 68 verdes + 1 GPU
(skip; manual passa) · assets com UV+textura aprovados no QC e importados no Godot 4.3.

Revisão da janela: [`docs/revisao-janela-2026-11-10.md`](docs/revisao-janela-2026-11-10.md).
**Para a próxima janela:** leia [`docs/pendencias.md`](docs/pendencias.md) (o que falta, com critério),
[`docs/gaps.md`](docs/gaps.md) (lacunas) e [`DECISOES.md`](DECISOES.md) §1–§2 e §4. Verificação rápida:
`python -m pytest tests/test_e2e_rapido.py -q` (2,0 s) e `python -m pytest -q` (18,0 s).

---

## O que é este projeto

**Forge3D** transforma um **lote declarativo** (YAML/JSON) em assets 3D verificáveis — `.glb` com
escala, pivô, LOD, colisão, rig, QC e manifesto — e publica de forma atômica num destino autorizado.

Requisito duro do operador (10/11/2026): **o utilitário é independente de projeto**. Não lê config do
diretório onde roda, não escreve fora do próprio estado, não importa código de jogo (D25).

## Onde estamos, por fase

| Fase | Estado | Entrega |
|---|---|---|
| **P0** | ✔ | arquitetura, contratos `spec@1`/`manifest@1`, 2 perfis, docs de processo |
| **P0.5** | ✔ | D23 allowlist · D24 estado central · `tools/check-contexto.sh` |
| **P1** | ✔ | rotas `blocky` e `import` de ponta a ponta: validar → planejar → gerar → Blender → QC G1–G9 → cache → publicar → índice → ledger |
| **P3** | **✔ parcial** | provider `i23d` real (TripoSR) + bake UV/textura próprio + venv única + kit corpo/capa/arma; prop e **3 personagens híbridos** com G1–G9 |
| **P3.5** | **✔** | concept SD1.5 → TripoSR → UV/bake: sentinela sem `origem`, split 3 concepts e **A/B de 3 personagens híbridos** (.02/.05/.04 + capa .03 + arma blocky), `AB_OK` |
| **P2** | **parcial** | `roblox-r15`: R15 16 ossos, pivô e `.rbxlx`; **Model 136741921517312 (1 MeshPart + 16 Bones) e Image 75934318775024 aprovados**; falta ver textura no GUI, pivôs nos Bones, escala/stud e U1–U4 |
| **P4** | pendente | rota `modular` (WFC) |
| **P5** | pendente | animação e retarget |

## O que foi entregue nesta janela

- **P3-A** — `blender/postprocess.py` agora faz **UV + bake próprios** para malha com `COLOR_0`:
  `smart_project` + bake `DIFFUSE/COLOR` em 512², Cycles CPU, PNG irmão no manifesto. Sem `moderngl`
  nem EGL. Reparo topológico remove a ilha de 1 face que o decimate deixa (G1).
- **P3-B** — provider `mesh` de verdade: TripoSR em **subprocesso** na venv
  `~/.cache/forge3d/venv-i23d` via `FORGE3D_VENV_I23D`, normalização canônica no pós-processo, lock de
  GPU (exit 6), publicação atômica. `doctor` diz `mesh: pronto`.
- **P3-C** — venvs consolidadas: `~/.venvs/triposr` (5,8 GB) removida; só `venv-i23d` (torch 2.4.1).
- **P3-D** — kit blocky corpo/capa/arma em `examples/lote_03_kit.yaml` (spec@2): 3 assets publicados e
  montados no Godot (`Chest`, `Hand.R`).
- **C1/C2** — `doctor` do `mesh` correto; `verify` reexecuta G1–G9 contra o perfil atual, com topologia
  em Python puro.
- **Contrato** — `spec@2` adiciona `parte` (`corpo`/`capa`/`arma`); `spec@1` continua aceito e o
  manifesto segue `manifest@1`.
- **P3.5** — concept **SD1.5** local em `~/.venvs/concept` (`FORGE3D_VENV_CONCEPT`), chamado pelo
  provider `mesh` quando o item nao tem `origem`; PNG 512², 25 steps, geração **5,5 s**; o run
  `concept → mesh` publicou `personagem.sentinel.concept.01` em **37,2 s**, **7.940 tris**, G1–G9,
  `providers.texture` (`concept/sd15`, revisão, seed) e Godot com AABB idêntico. A orientação de
  humanoide ganhou o perfil de área (D37): `centro_area=5,55` → espelha Z.
- **P3.5 split** — 3 concepts (corpo/capa/arma) publicaram 7.954/4.972/1.988 tris em **1m39,9s** e
  montaram no Godot (`SPLIT_OK`); capa/arma .02 blobs (D39); capa .03 + arma **blocky** fecharam o
  **híbrido** (`CHAR_CAPE_OK`).
- **P3.5 A/B** — 3 corpos + capa .03 + arma `blocky`; **7.954/7.950/7.960 tris**, `AB_OK`, imagem
  `p3_ab_3personagens.png`; scout .05 expôs sliver (D42) e orientação (D43).
- **P2 R15** — 16 partes, 300 tris, G1–G9, `R15_OK`; os 16 bone heads são os pivôs (D41/D47). Studio:
  `R15_STUDIO_PASS`, `.rbxlx` nativo (`R15_RBXLX_PASS`), Model 136741921517312 (1 MeshPart + 16 Bones) e
  Image 75934318775024 (`TextureID` setado; headless não carrega asset privado); `export-r15` evita o import manual.
- **C3/CI** — `forge3d gc --manter-dias 30` (2 testes, D45); `tools/ci.sh` + workflow com **36 testes**,
  contexto e P0 (D46).

## Números medidos nesta máquina

| Medida | Valor |
|---|---|
| Suíte | **68 verdes + 1 GPU (skip; manual passa)** (24 unidade + 2 P3-A + 6 concept + 2 gc + 1 rbxlx + 3 upload + 17 C5–C11 + 1 e2e rápido + 12 invariantes) em **18,0 s** |
| E2E rápido | **2,0 s** (alvo <30 s) |
| TripoSR — inferência (bule) | load **7,7 s** · forward **1,2 s** · extração **3,8 s** · total **12,6 s** · VRAM pico **2.378 MiB** |
| `run` mesh — bule | **23,3 s** frio · **2,1 s** cache hit |
| Asset `prop.bule.exemplo.01` | **7.960 tris** · 23.878 verts · bbox **0,19769×0,300×0,174134 m** · 1 material · textura **512²** · GLB **1.126.404 B** · PNG **313.107 B** |
| QC do bule | **G1–G9 verdes** |
| Godot 4.3 — bule | `Node3D → MeshInstance3D`; AABB **idêntico ao manifesto**; `albedo_tex=true`; 7.960 tris; previews `docs/preview/p3_bule_frente.png` e `..._tres_quartos.png` |
| Kit P3-D | corpo **300 tris / 23 ossos** · capa **60 tris / sem rig** · arma **36 tris**; 3 publicados |
| Godot 4.3 — kit | capa no osso `Chest` (idx 4), arma em `Hand.R` (idx 14); `KIT_OK` |
| Venv i23d | **5,6 GB** · Python 3.12.14 · torch **2.4.1+cu121** |
| `doctor` mesh/concept | `mesh: pronto ...` · `concept: pronto (SD1.5, diffusers 0.31.0)` |
| `verify` C2 | manifesto íntegro → ok; G2 com `esperado_m=1,2` → **exit 3**, "QC reexecutado reprovou G2" |
| Custo mesh do `plan` | **25 s estimados × 23,3 s reais** (erro +7%) |
| Concept SD1.5 | 512² · 25 steps · geração **5,5 s** · carga **2,0 s** (cache) · VRAM pico **2.675 MiB** · PNG 264.929 B |
| Sentinela concept→mesh | **37,2 s** · **7.940 tris** · bbox **1,000387×1,8×0,729638 m** · GLB **1.149.148 B** · PNG **337.824 B** · G1–G9 |
| Godot 4.3 — sentinela | `Node3D → MeshInstance3D`; AABB **idêntico**; `albedo_tex=true`; 7.940 tris |
| Split mesh — 3 concepts | **1m39,9s**; corpo **7.954** / capa **4.972** / arma **1.988 tris**; 3 publicados |
| Godot 4.3 — split | corpo AABB **1,114836×1,8×0,906218**; capa **0,793371×1,3×0,670403**; arma **0,93732×1,0×0,833001**; `SPLIT_OK` |
| Godot 4.3 — híbrido | corpo .02 + capa .03 + arma blocky .01; AABB capa **0,531849×1,3×0,355717**, arma **0,209×0,95×0,0666**; `CHAR_CAPE_OK` |
| A/B — 3 personagens | sentinela .02 **7.954** · scout .05 **7.950** · heavy .04 **7.960 tris**; mesmo kit capa/arma; `AB_OK` |
| P2 — R15 blocky | **300 tris** · **16 ossos** (todos no mapa R15) · G1–G9 · `verify` · `R15_OK` |
| P2 — pivô por membro (Studio) | **`R15_STUDIO_PASS motores=15 partes=16`**; 16 bone heads no GLB (H=1,85 m) |
| P2 — export nativo `.rbxlx` | **16 Parts + 15 Motor6D**, 18.479 B; `R15_RBXLX_PASS partes=16 motores=15` |
| P2 — upload Open Cloud | Model 136741921517312 (Approved, 1 MeshPart + 16 Bones) + Image 75934318775024 (Approved); `TextureID` setado; headless sem asset privado; 3 testes |
| gc / CI | `gc` 2 testes; `tools/ci.sh` **53 testes** + contexto + P0; GitHub run **42942191684** verde |
| Venv concept | **5,6 GB** · diffusers 0.31.0 · transformers 4.44.2 · torch 2.4.1+cu121 |
| Probe Roblox (sem Studio) | prop blocky publica/verifica; humanoid falha em `pivot: junta`; blocky não gera nomes R15 |

## Decidido (não reabrir sem evidência nova)

`D3` CLI-only · `D5` plan/run/verify/publish · `D7` D1/D2/D3 · `D9` QC sem bypass ·
`D11` GPU serializada · `D14` animação fora da v0 · `D18` licença é gate · `D19` naming neutro ·
`D23` allowlist · `D24` estado central · `D25` isolamento · `D26` núcleo leve ·
**`D27` SF3D encerrado em 6 GB** · **`D28` bake próprio no bpy** · **`D29` i23d em subprocesso na venv
única** · **`D30` spec@2 com `parte`** · **`D31` kit corpo/capa/arma** · **`D32` verify reexecuta G1–G9**
· **`D33` mesh exige `origem` enquanto GAP-026 não fecha** · **`D34` concept SD1.5 em venv separada**
· **`D35` concept interno ao mesh** · **`D36` rembg automático do concept**.

## Aberto — e o que cada um trava

| # | Pergunta | Trava | Fecha em |
|---|---|---|---|
| Q3 | escala/rig Roblox (0,28 m/stud) | perfil Roblox | P2, GUI do Studio |
| Q1 | nome definitivo do produto | publicar o pacote | antes do release |
| Q7 | assets no git do jogo (normal × LFS) | primeiro asset real | antes de integrar |
| Q9 | delegação: chave de API × `agentapi` | uso seguro em execução | P4 |

Gaps abertos que importam: **GAP-006** (GUI/textura/bones/escala R15), **GAP-004** (scanner da
skill em Luau), **GAP-013** (qualidade do LOD blocky), **GAP-015** (`draft` em 4k), **GAP-014**
(I3 sem teste de observação), **GAP-020** (personagem sem clipe de animação).

## Próximos passos — com custo, em ordem de evidência

| # | Ação | Custo | Ataca |
|---|---|---|---|
| **1** | **Roblox P2**: GUI/textura, pivôs nos Bones, escala/stud e U1–U4 | 1 sessão + Studio | P8/GAP-006 |
| **2** | **C6/Q9**: decidir delegação (chave de API × `agentapi`) | decisão do operador | C6 |
| **3** | Republicar assets antigos (manifesto sem `pivo_regra`, colisor côncavo) | 1 sessão | C12 |
| **4** | Animação (P5) | 2–3 sessões | maior salto de percepção no Godot |

## Comandos

```bash
cd /home/eudespatricio/3DCreation && . .venv/bin/activate

forge3d doctor                         # ambiente; mesh deve dizer "pronto"
forge3d plan  examples/lote_01.yaml
forge3d run   examples/lote_01.yaml
forge3d run   examples/lote_03_kit.yaml        # P3-D: corpo/capa/arma (blocky, sem GPU)
FORGE3D_I23D_REMOVER_FUNDO=1 forge3d run examples/lote_04_mesh.yaml   # P3-B: TripoSR + bake
forge3d run examples/lote_05_mesh_concept.yaml                     # P3.5: SD1.5 -> TripoSR
forge3d run examples/lote_06_mesh_split.yaml                       # P3.5: corpo/capa/arma
forge3d run examples/lote_07_cape.yaml                             # capa .03 (negativo de pessoa)
forge3d run examples/lote_08_ab_hybrid.yaml                       # A/B: scout .05 + heavy .04
forge3d run examples/lote_09_r15.yaml                             # R15: 16 ossos
forge3d export-r15 examples/lote_09_r15.yaml --item personagem.r15.guard.01  # .rbxlx nativo
forge3d upload-model <glb> --creator-id <id> --dry-run              # Open Cloud
forge3d upload-image <png> --creator-id <id> --dry-run              # textura
# Studio R15: ver docs/preview/r15_studio_test.log (run-in-roblox 0.3.2 + plugin)
forge3d gc --dry-run --manter-dias 30                             # retencao
bash tools/ci.sh                                                  # CI sem GPU/Blender
forge3d verify ~/.local/state/forge3d/saida/sentinel_concept
forge3d verify ~/.local/state/forge3d/saida/kit_mesh
forge3d verify ~/.local/state/forge3d/saida/r15
forge3d verify ~/.local/state/forge3d/saida/teapot_exemplo
python -m pytest -q                    # 68 verdes + 1 GPU (skip; manual passa)
bash tools/check-contexto.sh           # tetos
python tools/check-p0.py               # docs, schemas, I12/I14

# preview sem abrir o jogo
blender -b --factory-startup --python tools/render_preview.py -- <glb> <saida> --pose|--close
# normalização canônica de malha gerada (ainda útil para inspeção isolada)
blender -b --factory-startup --python tools/normalize_mesh.py -- <in.glb> <out.glb>
# inferência isolada na venv (o provider monta esta linha)
PYTHONPATH=~/.cache/forge3d/vendor/TripoSR ~/.cache/forge3d/venv-i23d/bin/python \
  tools/i23d_infer.py --imagem <png> --saida-dir /tmp/i23d --resultado /tmp/i23d/r.json --sem-rembg
# delegação (só com a IDE aberta; ver docs/delegacao.md)
python tools/delegar.py --tipo segunda_opiniao --texto "..." --exigir riscos --dry-run
```

## Arquivos-chave

`README.md` · `AGENTS.md` · `MAPA.md` · `CONSELHOS.md` · `DECISOES.md` · `INVARIANTES.md` ·
`docs/arquitetura.md` · `docs/contratos.md` · `docs/rotas-e-providers.md` · `docs/perfis-export.md` ·
`docs/qc-e-verificacao.md` · `docs/dependencias.md` · `docs/riscos-e-licencas.md` · `docs/roadmap.md` ·
`docs/gaps.md` · `docs/pendencias.md` · `schemas/` (`spec.v1`, `spec.v2`, `manifest.v1`) ·
`src/forge3d/` (15 módulos) · `blender/postprocess.py` · `tools/` (`i23d_infer`, `concept_infer`,
`setup_concept_venv`, `normalize_mesh`, `render_preview`, `delegar`, `torchmcubes_shim`, `check-*`) ·
`tests/` · `examples/` (`lote_01`, `lote_03_kit`, `lote_04_mesh`, `lote_05_mesh_concept`, `lote_06_mesh_split`, `lote_07_cape`, `lote_08_ab_hybrid`, `lote_09_r15`) ·
`docs/preview/p3_sentinel_*` · `p3_split_*` · `p3_char_cape_*` · `p3_ab_3personagens.png` ·
`src/forge3d/gc.py` · `tools/ci.sh` · `.github/workflows/ci.yml` · `tools/r15_studio_test.lua` ·
`docs/preview/r15_studio_test.log` · `r15_rbxlx_test.log` · `src/forge3d/rbx.py` ·
`tools/r15_rbxlx_test.lua` · `tools/configurar_roblox.sh` · `tools/r15_texture_apply_test.lua` · `tests/test_rbx.py` · `src/forge3d/upload.py` · `tests/test_upload.py`

## Regras invioláveis (top 6)

1. Nada roda sobre `/mnt/c` ou UNC (I12); estado sempre em ext4 sob `$FORGE3D_HOME`.
2. Nenhuma escrita fora do destino autorizado (I3/I13) — autorizar é `forge3d allowlist add`.
3. QC reprovado não publica; não existe bypass (I5).
4. Diffusion/reconstructor nunca é D1 (D7).
5. Mudou a saída de um provider? **Suba `VERSAO`** — entra na chave de cache (D6).
6. Blender 4.2 pinado, subprocesso, canal JSON; nunca `pip install` no Python dele (I9).

## Como retomar

> Leia `3DCreation/CONTINUAR.md`, `MAPA.md` e `DECISOES.md` §2 e §4. P0, P0.5, P1, P3/P3.5 e C5–C11
> fechados; P2 está parcial: R15 16 ossos, pivô, `.rbxlx` (18.479 B no caminho default) e upload
> **Model 136741921517312 + Image 75934318775024** aprovados. Falta o GUI logado para ver a textura,
> testar os pivôs nos 16 Bones, escala/stud e U1–U4.
> Próximo: P8/GAP-006 no Studio; depois C6/Q9, republicar assets antigos e animação. CI verde no
> GitHub (run 42942191684). Não reabra D3–D26; SF3D encerrado (D27); key fora do repo.
