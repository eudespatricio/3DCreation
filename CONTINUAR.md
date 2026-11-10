# CONTINUAR — handoff de sessão

**Data:** 10/11/2026 · **P0, P0.5 e P1 fechadas. P3 fechada para prop (bule) e kit blocky; P3.5
fechada para concept→mesh e para 1 personagem híbrido com capa (corpo/capa mesh + arma blocky).**
44 verdes + 1 GPU (skip; manual passa) · assets com UV+textura aprovados no QC e importados no
Godot 4.3.

**Para a próxima janela:** leia [`docs/pendencias.md`](docs/pendencias.md) (o que falta, com critério),
[`docs/gaps.md`](docs/gaps.md) (lacunas) e [`DECISOES.md`](DECISOES.md) §1–§2 e §4. Verificação rápida:
`python -m pytest tests/test_e2e_rapido.py -q` (2,0 s) e `python -m pytest -q` (~15 s).

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
| **P3** | **✔ parcial** | provider `i23d` real (TripoSR) + bake UV/textura próprio + venv única + kit corpo/capa/arma; **prop** fecha com G1–G9 verdes; personagem com capa ainda não |
| **P3.5** | **✔ parcial** | concept SD1.5 → TripoSR → UV/bake: sentinela sem `origem`, split 3 concepts e **híbrido** corpo .02 + capa .03 + arma blocky (`CHAR_CAPE_OK`); faltam 3 personagens para o A/B |
| **P2** | pendente (probe) | perfil `roblox-r15`: prop publica/verifica; humanoid bloqueado em `pivot: junta` e nos nomes R15; falta Studio |
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
- **P3.5 split** — 3 concepts separados (corpo/capa/arma) publicaram 7.954 / 4.972 / 1.988 tris em
  **1m39,9s** e montaram no Godot (`SPLIT_OK`); o corpo é utilizável, capa/arma .02 saíram blobs
  (D39). A capa .03 (prompt de capa vazia + negativo de pessoa) e a arma **blocky** fecharam o
  **híbrido** com `CHAR_CAPE_OK` no Godot.

## Números medidos nesta máquina

| Medida | Valor |
|---|---|
| Suíte | **44 verdes + 1 GPU (skip; manual passa)** (24 unidade + 2 P3-A + 6 concept + 1 e2e rápido + 11 invariantes) em **13,7 s** |
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
| **Q8** | qualidade do reconstructor para **personagem com capa** (TripoSR × SF3D) | a qualidade de personagem | P3.5, com 3 personagens |
| Q3 | escala/rig Roblox (0,28 m/stud) | perfil Roblox | P2, teste no Studio |
| Q1 | nome definitivo do produto | publicar o pacote | antes do release |
| Q7 | assets no git do jogo (normal × LFS) | primeiro asset real | antes de integrar |
| Q9 | delegação: chave de API × `agentapi` | uso seguro em execução | P4 |

Gaps abertos que importam: **GAP-037** (verify de manifesto antigo sem `pivo_regra`), **GAP-038**
(convexidade no G7), **GAP-039** (rembg explícito), **GAP-040** (`FORGE3D_MODELOS`).

## Próximos passos — com custo, em ordem de evidência

| # | Ação | Custo | Ataca |
|---|---|---|---|
| **1** | **3 personagens híbridos** para o A/B (P7/Q8) | 1–2 sessões | qualidade com capa |
| **2** | **Roblox P2**: implementar `pivot: junta` + esqueleto R15 e validar no Studio | 1 sessão | segundo perfil; P8/GAP-006 |
| **3** | `gc` de cache/ledger + CI de pull request | 1 sessão | C3, GAP-008 |
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
forge3d verify ~/.local/state/forge3d/saida/sentinel_concept
forge3d verify ~/.local/state/forge3d/saida/kit_mesh
forge3d verify ~/.local/state/forge3d/saida/teapot_exemplo
python -m pytest -q                    # 44 verdes + 1 GPU (skip; manual passa)
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
`tests/` · `examples/` (`lote_01`, `lote_03_kit`, `lote_04_mesh`, `lote_05_mesh_concept`) ·
`docs/preview/p3_sentinel_*` · `docs/preview/p3_split_*` · `docs/preview/p3_char_cape_*` (híbrido)

## Regras invioláveis (top 6)

1. Nada roda sobre `/mnt/c` ou UNC (I12); estado sempre em ext4 sob `$FORGE3D_HOME`.
2. Nenhuma escrita fora do destino autorizado (I3/I13) — autorizar é `forge3d allowlist add`.
3. QC reprovado não publica; não existe bypass (I5).
4. Diffusion/reconstructor nunca é D1 (D7).
5. Mudou a saída de um provider? **Suba `VERSAO`** — entra na chave de cache (D6).
6. Blender 4.2 pinado, subprocesso, canal JSON; nunca `pip install` no Python dele (I9).

## Como retomar

> Leia `3DCreation/CONTINUAR.md`, `MAPA.md` e `DECISOES.md` §2 e §4. P0, P0.5 e P1 estão fechadas;
> P3 está fechada **para prop** (bule com UV+textura, G1–G9 verdes, importado no Godot 4.3) e para o
> **kit blocky** corpo/capa/arma. P3.5 fechou o **concept local → mesh** com o sentinela sem `origem`
> (7.940 tris, G1–G9, Godot com AABB idêntico). Próximo: split do input mesh (GAP-036/037) e
> qualidade de personagem **com capa** (Q8/GAP-029); depois Roblox P2 (Q3/GAP-006) e `gc`/CI.
> Não reabra D3–D26; SF3D está encerrado (D27) e não deve ser reinstalado.
