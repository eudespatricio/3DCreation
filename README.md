# Forge3D — esteira de assets 3D por demanda

> Utilitário de linha de comando que transforma um **lote declarativo** (YAML/JSON) em assets finais
> prontos para o jogo — `.glb` com escala, pivô, LOD, colisão, rig, QC e manifesto — e publica de forma
> atômica num destino autorizado.

**Estado:** `P0`–`P1`, `P2`, `P3`, `P3.5` e `P5` — **121 verdes + 1 GPU (skip)** em 122 testes e CI
no GitHub com 106. A `P2` fechou com `manifest@2`/D62 (glb em studs; package e `.rbxlx` em 6,6071
studs); a `P5` fechou com o clipe `idle` por retarget tocando no Godot e no Roblox (`manifest@3`,
D66/D67/D69) e com o LOD medido por silhueta (D71). `blocky`/`import` sem GPU; `mesh` com TripoSR +
bake UV/textura e concept SD1.5 **sem `origem`**; kit corpo/capa/arma. `modular` em P4. Leia
[`AGENTS.md`](AGENTS.md) antes de qualquer ação.

---

## O problema

Cada projeto precisa de assets. Hoje cada um resolve do seu jeito — modela à mão, baixa pack ou cola um
script de geração — e o resultado é sempre parecido:

- o asset chega com escala errada e alguém conserta no editor;
- o pivô está na origem do mundo e a arma flutua na mão;
- são 50 mil triângulos para uma espada;
- ninguém sabe com qual prompt, modelo ou licença aquilo nasceu;
- rodar o build de novo gera arquivos diferentes e suja o git do jogo.

**Forge3D torna geração de asset um passo de build**: reprodutível, verificável, barato de repetir e
seguro de plugar no pipe de terceiros.

## Como um projeto de jogo usa isto

Um comando, um arquivo, um código de saída. Nada de importar código, nada de daemon.

```bash
forge3d plan   lote_01.yaml --json   # custo e cache, sem GPU, sem escrever nada (roda no CI)
forge3d run    lote_01.yaml --json   # gera, verifica QC e publica no destino autorizado
forge3d verify <destino>   --json    # portão de CI: hash + G1–G9 reexecutados
forge3d query  --max-tris 100 --json # "by demand": o que já existe
forge3d doctor                       # diagnóstico do ambiente
forge3d gc --manter-dias 30          # retenção de cache/runs/staging (não toca no publicado)
forge3d export-r15 examples/lote_09_r15.yaml --item personagem.r15.guard.01  # .rbxlx nativo
forge3d upload-model <arquivo.glb> --creator-id <id> --dry-run  # request sem rede
forge3d upload-model <arquivo.glb> --creator-id <id>           # Open Cloud Model (free)
forge3d upload-image <atlas.png> --creator-id <id>             # Open Cloud Image (textura)
```

Branching no pipe é por **código de saída estável** ([`docs/contratos.md`](docs/contratos.md) §5):
`0` ok · `2` spec inválida · `3` QC reprovou · `4` ambiente · `5` provider · `6` recurso · `7` parcial.

## Isolamento — o utilitário é independente do projeto

Requisito duro (D25). O Forge3D **não contamina** o repositório de quem o chama:

| Regra | Efeito |
|---|---|
| **Estado próprio** | cache, runs, staging, locks, índice e ledger em `~/.local/state/forge3d`. Rodar de dentro de um jogo não cria pasta nem arquivo lá |
| **Destino é allowlist** | por padrão só o sandbox do Forge3D é gravável; autorizar um projeto é ato explícito: `forge3d allowlist add /caminho/do/jogo/assets` |
| **Config global, nunca do cwd** | o comportamento não muda conforme o diretório de onde você chamou (D24) |
| **Zero import de código de jogo** | a fronteira é CLI + arquivo de lote; o consumidor não precisa do Forge3D instalado para validar o asset |
| **`/mnt/c` e UNC são recusados** | I/O lento e hash instável; tudo roda em ext4 sob `/home` |

## As quatro rotas

| Rota | Para quê | Determinismo | Custo real | Estado |
|---|---|---|---|---|
| `blocky` | voxel/blocky, item, personagem de blocos | **D1** (byte-idêntico) | ~0,7 s/asset, sem GPU | **P1 ✔** |
| `import` | asset feito à mão (Blockbench/Blender) entra no mesmo QC | D1 | ~0,7 s/asset | **P1 ✔** |
| `mesh` | 3D orgânico/detalhado por modelo local (TripoSR; concept SD1.5) | D2 (semeado) | ~23 s com `origem` · **37 s** gerando concept | **P3 ✔ parcial** |
| `modular` | dungeon/cenário por WFC + montagem | D1 (seed fixa) | segundos | P4 |

A GPU é **opcional**: o sistema é útil sem ela, e é isso que o mantém barato no pipe.

## O lote

[`examples/lote_01.yaml`](examples/lote_01.yaml) é a fixture canônica — 3 assets, roda hoje.
[`examples/lote_03_kit.yaml`](examples/lote_03_kit.yaml) é o kit corpo/capa/arma (`spec@2`) e
[`examples/lote_04_mesh.yaml`](examples/lote_04_mesh.yaml) é a rota `mesh` (TripoSR + bake) e
[`examples/lote_05_mesh_concept.yaml`](examples/lote_05_mesh_concept.yaml) é o concept sem `origem` e
[`examples/lote_06_mesh_split.yaml`](examples/lote_06_mesh_split.yaml) é o split corpo/capa/arma e
[`examples/lote_07_cape.yaml`](examples/lote_07_cape.yaml) é a capa isolada do híbrido:

```yaml
schema: forge3d/spec@1
projeto: demo
perfil: godot4
destino_exportacao: ~/.local/state/forge3d/saida/lote_01
paleta: ["#0d0d0f", "#3a3a40", "#ff5a1f", "#ffd166", "#c9a227"]

lote:
  - id: weapon.sword.fire.01
    tipo: prop_equipavel
    rota: blocky
    prompt: "Espada larga de ferro negro com runas de lava na lâmina, cabo de couro gasto"
    altura_metros: 1.10
    pivot: empunhadura
    limite_triangulos: 800
    colisao: convex
    lod: [100, 50]
```

## O que o pipeline faz

```
lote ──► VALIDAR (schema + B1–B13)
      ──► PLANEJAR (chave de cache, custo, bloqueios)   ◄── roda no CI, sem GPU
      ──► CONCEPT (SD1.5 → PNG; só mesh sem `origem`)
      ──► GERAR (provider → staging)
      ──► PÓS-PROCESSAR (Blender 4.2 headless: escala, pivô, LOD, colisor, rig)
      ──► VERIFICAR (QC G1–G9; reprovou, não publica)
      ──► PUBLICAR (rename atômico + manifesto + índice + ledger)
```

O que faz diferença em produção, e não está num "script que chama modelo":

1. **Plano antes da execução** — custo e cache calculados sem gastar recurso.
2. **Cache por conteúdo** — rerun sem mudança é `trabalho_executado: 0` (medido: 476 ms contra 2.082 ms).
3. **QC como portão** — manifold, orçamento de triângulos, escala ±0,5 %, pivô 1 mm, UV, materiais,
   rig, colisão, licença.
4. **Publicação atômica** — staging → `rename`; nunca se escreve direto na pasta do jogo.
5. **Manifesto e proveniência** — provider, versão, seed, hash do spec e licença de cada asset.
6. **Degradação explícita** — GPU fora bloqueia só as tarefas que precisam dela.

## Verificar esta entrega

```bash
cd /home/eudespatricio/3DCreation && . .venv/bin/activate

python -m pytest -q                     # 51 + 1 GPU (manual); P3-A, concept, gc, rbxlx, upload
bash tools/check-contexto.sh            # tetos de contexto
python tools/check-p0.py                # schemas, exemplos, perfis, I12/I14

# revisar qualidade sem abrir o jogo (Cycles, ~4 s por vista)
blender --background --factory-startup --python tools/render_preview.py -- \
  ~/.local/state/forge3d/saida/android/mob.android.sentinel.01.glb docs/preview/meu_asset --pose
```

R15: `run-in-roblox` 0.3.2 no Studio passou `R15_STUDIO_PASS motores=15 partes=16` (log
[`docs/preview/r15_studio_test.log`](docs/preview/r15_studio_test.log)). O `forge3d export-r15`
gera um **`.rbxlx` nativo** (16 Parts + 15 Motor6D, com CFrame e pivô no joint) que abre direto no
Studio — `R15_RBXLX_PASS partes=16 motores=15`; textura/MeshPart e escala/stud seguem em P8.

**Upload Open Cloud (free):** o `upload-model` sobe `.glb` como `Model` (20 MB max) e devolve
`assetId`; a key fica fora do repo:

```bash
mkdir -p ~/.config/forge3d && chmod 700 ~/.config/forge3d
# crie ~/.config/forge3d/roblox.key e cole APENAS a key (sem export, sem ID)
chmod 600 ~/.config/forge3d/roblox.key
forge3d upload-model ~/.local/state/forge3d/saida/r15/personagem.r15.guard.01.glb \
  --creator-id 1234567 --dry-run
```

Se preferir um passo a passo interativo — key oculta, creator ID e dry-run — rode
`bash tools/configurar_roblox.sh`. A **key fica só no arquivo**; o creator ID vai por
`--creator-id`, nunca dentro do arquivo da key.

A key também pode vir de `FORGE3D_ROBLOX_API_KEY`; nunca commite. O upload cria um **package de
MeshParts**, não um rig R15; o `.rbxlx` nativo continua sendo o rig.

**Upload real validado:** `assetId 136741921517312` (Model, **Approved**, 39.068 B).
`InsertService:LoadAsset` no Studio carrega **1 MeshPart com 16 Bones R15**. A textura do Model
falhou; o atlas 64×64 foi extraído e subiu como **Image `75934318775024`** (Approved), com
`TextureID` setado no MeshPart. O servidor **headless** do `run-in-roblox` não carrega assets
privados (“No asset content representation”), então a textura precisa ser conferida no Studio GUI
logado. Logs: [`r15_asset_insert.log`](docs/preview/r15_asset_insert.log) e
[`r15_texture_apply.log`](docs/preview/r15_texture_apply.log).

`bash tools/ci.sh` roda o portão de pull request sem GPU/Blender (unidade + concept + gc + contexto +
P0); a suíte completa com Blender/GPU continua local. O workflow está em `.github/workflows/ci.yml`.

Os testes de invariante rodam o Blender de verdade: provam escala, pivô, hash idêntico entre execuções,
detecção de arquivo adulterado e reexecução dos gates no `verify`, idempotência e recusa de
destino fora da allowlist. Assets de aceitação: `prop.bule.exemplo.01` (prop, 7.960 tris) e
`personagem.sentinel.concept.01` (concept→mesh sem `origem`, 7.940 tris) e o corpo do split
`personagem.sentinel.corpo.02` (7.954 tris), todos com textura 512², G1–G9 verdes e AABB idêntico
no Godot 4.3. O híbrido corpo .02 + capa .03 + arma blocky monta com `CHAR_CAPE_OK`; capa/arma mesh
.02 isoladas seguem blobs (D39). O A/B de **3 personagens** (.02/.05/.04) monta com `AB_OK` — veja
[`docs/preview/p3_ab_3personagens.png`](docs/preview/p3_ab_3personagens.png).

## Documentos

| Quero saber | Leia |
|---|---|
| onde cada coisa mora e as armadilhas | [`MAPA.md`](MAPA.md) |
| o que foi decidido e por quê | [`DECISOES.md`](DECISOES.md) |
| regras que quebram o projeto se violadas | [`INVARIANTES.md`](INVARIANTES.md) |
| avaliação crítica do desenho original | [`docs/avaliacao.md`](docs/avaliacao.md) |
| arquitetura completa | [`docs/arquitetura.md`](docs/arquitetura.md) |
| contrato de spec e manifesto | [`docs/contratos.md`](docs/contratos.md) |
| como retomar uma sessão | [`CONTINUAR.md`](CONTINUAR.md) |
| método de decisão por conselho | [`CONSELHOS.md`](CONSELHOS.md) |

## Escopo explicitamente fora da v0

Animação/retarget, geração de mapa completo (Rota C), servidor HTTP, MCP e qualquer modelo fechado por
API. Motivos em [`DECISOES.md`](DECISOES.md) §3.
