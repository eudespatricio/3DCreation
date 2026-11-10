# CONTINUAR — handoff de sessão

**Data:** 10/11/2026 · **P0, P0.5 e P1 fechadas. P3 fechada para prop (bule) e kit blocky; qualidade
de personagem com capa continua aberta.** 38 testes verdes · 1 asset com UV+textura aprovado no QC e
importado no Godot 4.3 sem ajuste manual.

**Para a próxima janela:** leia [`docs/pendencias.md`](docs/pendencias.md) (o que falta, com critério),
[`docs/gaps.md`](docs/gaps.md) (lacunas) e [`DECISOES.md`](DECISOES.md) §1–§2 e §4. Verificação rápida:
`python -m pytest tests/test_e2e_rapido.py -q` (2,0 s) e `python -m pytest -q` (14,3 s).

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

## Números medidos nesta máquina

| Medida | Valor |
|---|---|
| Suíte | **38 verdes** (24 unidade + 2 P3-A + 1 e2e rápido + 11 invariantes) em **14,3 s** |
| E2E rápido | **2,0 s** (alvo <30 s) |
| TripoSR — inferência (bule) | load **7,7 s** · forward **1,2 s** · extração **3,8 s** · total **12,6 s** · VRAM pico **2.378 MiB** |
| `run` mesh — bule | **23,3 s** frio · **2,1 s** cache hit |
| Asset `prop.bule.exemplo.01` | **7.960 tris** · 23.878 verts · bbox **0,19769×0,300×0,174134 m** · 1 material · textura **512²** · GLB **1.126.404 B** · PNG **313.107 B** |
| QC do bule | **G1–G9 verdes** |
| Godot 4.3 — bule | `Node3D → MeshInstance3D`; AABB **idêntico ao manifesto**; `albedo_tex=true`; 7.960 tris |
| Kit P3-D | corpo **300 tris / 23 ossos** · capa **60 tris / sem rig** · arma **36 tris**; 3 publicados |
| Godot 4.3 — kit | capa no osso `Chest` (idx 4), arma em `Hand.R` (idx 14); `KIT_OK` |
| Venv i23d | **5,6 GB** · Python 3.12.14 · torch **2.4.1+cu121** |
| `doctor` mesh | `mesh: pronto (TripoSR, torch 2.4.1+cu121, venv venv-i23d)` |
| `verify` C2 | manifesto íntegro → ok; G2 com `esperado_m=1,2` → **exit 3**, "QC reexecutado reprovou G2" |
| Custo mesh do `plan` | **25 s estimados × 23,3 s reais** (erro +7%) |
| Probe Roblox (sem Studio) | prop blocky publica/verifica; humanoid falha em `pivot: junta`; blocky não gera nomes R15 |

## Decidido (não reabrir sem evidência nova)

`D3` CLI-only · `D5` plan/run/verify/publish · `D7` D1/D2/D3 · `D9` QC sem bypass ·
`D11` GPU serializada · `D14` animação fora da v0 · `D18` licença é gate · `D19` naming neutro ·
`D23` allowlist · `D24` estado central · `D25` isolamento · `D26` núcleo leve ·
**`D27` SF3D encerrado em 6 GB** · **`D28` bake próprio no bpy** · **`D29` i23d em subprocesso na venv
única** · **`D30` spec@2 com `parte`** · **`D31` kit corpo/capa/arma** · **`D32` verify reexecuta G1–G9**
· **`D33` mesh exige `origem` enquanto GAP-026 não fecha**.

## Aberto — e o que cada um trava

| # | Pergunta | Trava | Fecha em |
|---|---|---|---|
| **Q8** | qualidade do reconstructor para **personagem com capa** (TripoSR × SF3D) | a qualidade de personagem | P3.5, com 3 personagens |
| Q3 | escala/rig Roblox (0,28 m/stud) | perfil Roblox | P2, teste no Studio |
| Q1 | nome definitivo do produto | publicar o pacote | antes do release |
| Q7 | assets no git do jogo (normal × LFS) | primeiro asset real | antes de integrar |
| Q9 | delegação: chave de API × `agentapi` | uso seguro em execução | P4 |

Gaps abertos que importam: **GAP-026** (concept text-to-image), **GAP-036** (personagem com capa),
**GAP-037** (split do input mesh), **GAP-038** (verify de manifesto antigo sem `pivo_regra`),
**GAP-039** (convexidade no G7), **GAP-040** (rembg explícito).

## Próximos passos — com custo, em ordem de evidência

| # | Ação | Custo | Ataca |
|---|---|---|---|
| **1** | Provider de **concept** (text-to-image → PNG): fecha GAP-026 e tira o `origem` manual | 1 sessão | entrada da rota mesh |
| **2** | **Split do input mesh** (corpo/capa/arma): 3 concepts → 3 malhas | 1 sessão + GPU | GAP-036/GAP-037 |
| **3** | **Roblox P2**: implementar `pivot: junta` + esqueleto R15 e validar no Studio | 1 sessão | segundo perfil; P8/GAP-006 |
| **4** | Qualidade de personagem: 3 inputs com capa, medir e decidir TripoSR × SF3D | 1–2 sessões | Q8, GAP-029 |
| **5** | `gc` de cache/ledger + CI de pull request | 1 sessão | C3, GAP-008 |
| **6** | Animação (P5) | 2–3 sessões | maior salto de percepção no Godot |

## Comandos

```bash
cd /home/eudespatricio/3DCreation && . .venv/bin/activate

forge3d doctor                         # ambiente; mesh deve dizer "pronto"
forge3d plan  examples/lote_01.yaml
forge3d run   examples/lote_01.yaml
forge3d run   examples/lote_03_kit.yaml        # P3-D: corpo/capa/arma (blocky, sem GPU)
FORGE3D_I23D_REMOVER_FUNDO=1 forge3d run examples/lote_04_mesh.yaml   # P3-B: TripoSR + bake
forge3d verify ~/.local/state/forge3d/saida/teapot_exemplo
python -m pytest -q                    # 38 testes
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
`src/forge3d/` (14 módulos) · `blender/postprocess.py` · `tools/` (`i23d_infer`, `normalize_mesh`,
`render_preview`, `delegar`, `torchmcubes_shim`, `check-*`) · `tests/` · `examples/`

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
> **kit blocky** corpo/capa/arma. O que falta: concept provider (GAP-026), split do input mesh
> (GAP-036/037), qualidade de personagem com capa (Q8/GAP-029), Roblox P2 (Q3/GAP-006) e `gc`/CI.
> Não reabra D3–D26; SF3D está encerrado (D27) e não deve ser reinstalado.
