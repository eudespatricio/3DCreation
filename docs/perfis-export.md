# Perfis de export

> Engine não entra no código: entra aqui (D4). Um perfil é dado versionado, não código.
> Alvos do v0: **Godot 4** e **Roblox (R15/blocky)** — escolha do operador.
> Fonte executável: [`../profiles/godot4.yaml`](../profiles/godot4.yaml), [`../profiles/roblox-r15.yaml`](../profiles/roblox-r15.yaml).

## 1. O que um perfil controla

| Bloco | Decide |
|---|---|
| `formato` | `.glb` (padrão), `.gltf`+bin, `.fbx` |
| `unidades` | metros por unidade de export; conversão opcional para studs |
| `eixos` | up e frente (Godot/glTF: +Y up, −Z frente) |
| `aplicar_transforms` | zerar rotação e escala antes de exportar |
| `pivot` | regra geométrica por `tipo` (`empunhadura`, `base`, …) |
| `colisao` | modo, prefixo, geração de hull |
| `lod` | quantos níveis, sufixo, preservação de material |
| `rig` | esqueleto nomeado/versionado, limite de ossos, escala de osso |
| `material` | modelo (metallic-roughness), tamanho máximo de textura, POT, filtro |
| `validacao` | tolerâncias usadas pelo QC (escala %, pivô mm, tri máx por material, bytes máx) |

Princípio: **se o QC precisa saber, o perfil declara**. Tolerância mágica no código é bug esperando
para acontecer com a segunda engine.

## 2. `godot4`

| Chave | Valor | Nota |
|---|---|---|
| `formato` | `glb` | Godot importa glTF 2.0 nativamente |
| `unidades.metros_por_unidade` | `1.0` | 1 unidade glTF = 1 m; casa com `Node3D` do Godot |
| `eixos` | up `+Y`, frente `−Z` | padrão glTF; `apply_transform` ligado |
| `aplicar_transforms` | `true` | escala/rotação zeradas no exportador |
| `pivot` | `base` para `prop_estatico`/`modulo_cenario`; `empunhadura` para `prop_equipavel`; `base` para humanoides | origem no centro da base da AABB, não no centro de massa |
| `colisao` | `convex_hull` por peça, nome `UCX_<Mesh>_<nn>` | Godot gera `-col` do sufixo `-colonly`/`-col`; `UCX_` é convenção de pipeline para achar depois |
| `lod` | sufixos `_LOD0.._LOD2` | importar como `MeshInstance3D` separado; LOD automático é P5 |
| `rig.esqueleto` | `godot-humanoid@1` | 22 ossos, sufixo `.L`/`.R` (convenção Blender) |
| `rig.max_ossos` | `64` | acima disso, multiplica custo de skinning |
| `material.modelo` | `metallic-roughness` | PBR padrão glTF |
| `material.textura_max` | `1024` | pixel art fica em 64–256, por decisão de arte |
| `material.filtro` | `nearest` | **o glTF não força filtro**; precisa do preset de import no Godot (`[verificar]` na importação) |
| `validacao` | escala `0.5 %` · pivô `1 mm` · materiais `≤ 8` · bytes `≤ 2048 KB` | consumido pelo QC |

## 3. `roblox-r15`

| Chave | Valor | Nota |
|---|---|---|
| `formato` | `glb` + **`rbxlx` nativo** | `glb` via 3D Importer; `rbxlx` é Parts+Motor6D, sem upload |
| `unidades.metros_por_unidade` | `1.0` (Blender) · conversão `studs = metros / 0.28` | 1 stud ≈ 0,28 m; arredondar na geração, nunca no importador `[verificar]` |
| `eixos` | up `+Y`, frente `−Z` | igual ao glTF; Roblox usa +Y up, −Z frente |
| `aplicar_transforms` | `true` | `MeshPart` com escala aplicada quebra `Motor6D` |
| `pivot` | `base` no objeto; membros = **16 bone heads R15** (validado no Studio) | pivô errado = membro gira em torno do ponto errado |
| `colisao` | hull por parte, no máximo 1 por parte | Roblox calcula colisão por `MeshPart`; colisor separado não é importado como tal `[verificar]` |
| `rig.esqueleto` | `r15@1` — 15 partes + `HumanoidRootPart` | nomes exigidos pelo `Humanoid` |
| `rig.max_ossos` | `24` | acima do R15 há solução mais barata |
| `material.modelo` | `SurfaceAppearance` (base color + normal + roughness) | PBR na Roblox é `SurfaceAppearance`, que **não vem por glTF** `[verificar]`; o `.rbxlx` usa cor por Part |
| `material.textura_max` | `1024` | limite prático de tamanho de imagem |
| `lod` | `nenhum` | Roblox tem `RenderFidelity` próprio; LOD exportado é ignorado |
| `validacao` | escala `1 %` (arredondamento de stud) · pivô por junta `2 mm` · tri/parte `≤ 10.000` · partes `≤ 15` | |

**Export nativo:** `forge3d export-r15 <lote> --item <id>` monta um place `.rbxlx` com **16
Parts** (agregando as caixas de cada osso) e **15 Motor6D** com `CFrame`/`C0`/`C1` no joint. O
arquivo abre direto no Studio — `R15_RBXLX_PASS partes=16 motores=15` — sem upload, sem 3D
Importer e sem textura (as Part usam a cor do blocky). Textura/atlas e `MeshPart` continuam no
`glb` e em P8.

### Upload Open Cloud (free)

`forge3d upload-model <glb> --creator-id <id>` sobe o arquivo como **`Model`** via Open Cloud
Assets API (20 MB por chamada; `.glb`/`.gltf`/`.fbx`). A key vem de `FORGE3D_ROBLOX_API_KEY`,
`FORGE3D_ROBLOX_API_KEY_FILE` ou `~/.config/forge3d/roblox.key`; `--dry-run` monta o request sem
rede. O resultado é um **package de MeshParts**, não um rig R15 — o `.rbxlx` nativo continua sendo
o rig; o upload resolve a malha, e a montagem do package no rig é o passo seguinte. O upload real
foi aprovado (asset 136741921517312): no Studio, `InsertService` carrega 1 MeshPart com 16 Bones
R15. A textura derivada falhou; o atlas 64×64 subiu como **Image 75934318775024** (Approved) e o
`TextureID` foi setado. O servidor headless não carrega asset privado; a conferência visual é no
Studio GUI.

**Probe em 10/11/2026:** um `prop_estatico` blocky publica e `verify` passa com este perfil
(48 tris, 1 colisor). O `personagem_humanoide` com `auto_rig: true` e `esqueleto: r15@1` publica
**300 tris com 16 ossos/nomes R15** (`HumanoidRootPart`…`RightFoot`), G1–G9, `verify` ok e
`R15_OK` no Godot. No Studio, **`R15_STUDIO_PASS motores=15 partes=16`** valida o pivô por membro;
os bone heads do GLB ficam nos joints (D47). O objeto usa `pivot: base`; import da malha/textura,
escala/stud e U1–U4 continuam pendentes (GAP-006). `colisao.prefixo` ausente não estoura mais o G7.

### Esqueleto `r15@1` (Rig)

`HumanoidRootPart` · `Head` · `UpperTorso` · `LowerTorso` · `LeftUpperArm` · `LeftLowerArm` ·
`LeftHand` · `RightUpperArm` · `RightLowerArm` · `RightHand` · `LeftUpperLeg` · `LeftLowerLeg` ·
`LeftFoot` · `RightUpperLeg` · `RightLowerLeg` · `RightFoot`.

### Esqueleto `godot-humanoid@1`

`Root` · `Hips` · `Spine` · `Spine1` · `Chest` · `Neck` · `Head` · `Shoulder.L/R` · `UpperArm.L/R` ·
`LowerArm.L/R` · `Hand.L/R` · `UpperLeg.L/R` · `LowerLeg.L/R` · `Foot.L/R` · `Toe.L/R` — 22 ossos.

**Estes dois esqueletos são convenção deste projeto**, não padrão de indústria. Mixamo usa
`mixamorig:LeftArm`; Rigify usa `DEF-upper_arm.L`. Por isso o mapa de retarget é **tabela no perfil**,
versionada — e o teste de rig verifica nome a nome, não "parece razoável".

## 4. Regra de pivô (resolve a contradição do lote original)

`pivot: "empunhadura"` não é um ponto; é uma **regra** que depende de geometria e tipo:

| `tipo` | `pivot` | Como o pipeline calcula |
|---|---|---|
| `prop_equipavel` | `empunhadura` | **20 % da altura a partir da base**, no eixo X/Y do centro da AABB, para `blocky` e `mesh` (D58). A regra de "menor secção transversal" fica em GAP-042 |
| `prop_estatico`, `modulo_cenario` | `base` | centro da face inferior da AABB |
| `personagem_humanoide`, `criatura` | `base` | centro da face inferior da AABB (pés no chão) |
| qualquer | `centro` | centro da AABB |
| qualquer | `origem` | origem do arquivo, sem correção (rota `import`) |
| qualquer | `topo` | centro da face superior (pingentes, luminárias) |

A regra é **determinística e testável** (I8): o QC mede a posição do pivô no `.glb` exportado e compara
com o esperado. Se a regra não conseguir decidir, o item falha com `FORGE-E-QC` e mensagem explícita —
não chuta.

### Convenção de eixos de osso (medida em 10/11/2026)

Todos os ossos exportados têm **X local = +X do mundo** e **Y local ao longo do osso** (verificado
no Blender e no import do Godot 4.3). Consequência direta para animar:

| Rotação local X | Efeito | Uso |
|---|---|---|
| **positiva** | membro vai para a frente (+Y no Blender, −Z no glTF) | flexão de **ombro, quadril e cotovelo** |
| **negativa** | membro vai para trás | flexão de **joelho**; extensão de ombro/cotovelo |

Não é convenção de mercado — Mixamo e Rigify usam outra. Por isso o mapa de retarget é tabela no
perfil e a validação de rig confere nome a nome, não "parece razoável".

## 5. Convenções de nome (contrato com o jogo)

| Objeto | Padrão | Exemplo |
|---|---|---|
| Arquivo principal | `<asset_id>.glb` | `weapon.sword.fire.01.glb` |
| Textura | `<asset_id>_baseColor.png` | `weapon.sword.fire.01_baseColor.png` |
| Normal / ORM | `_normal.png` · `_orm.png` | — |
| Colisor | `UCX_<mesh>_<nn>` | `UCX_Blade_01` |
| LOD | `<asset_id>_LOD<n>.glb` | `weapon.sword.fire.01_LOD1.glb` |
| Manifesto | `manifest.json` (um por asset) ou `<asset_id>.manifest.json` | — |

Nome de arquivo é **determinístico a partir do `id`**: nada de timestamp, nada de sufixo `_final_v2`.

## 6. Incertezas declaradas

| # | Incerteza | Como fecha |
|---|---|---|
| U1 | Escala exata do importador Roblox (0,28 m/stud e opção de escala na UI) | teste real no Studio, P2 |
| U2 | `SurfaceAppearance`/PBR por glTF no importador Roblox | teste real, P2 |
| ~~U3~~ | **Fechada (10/11/2026):** Godot 4.3 aplicou `TEXTURE_FILTER_NEAREST_WITH_MIPMAPS` (`filtro=2`) | import real do android |
| U4 | `Humanoid` aceita rig vindo de glTF importado como `Model`? | teste no Studio, P2 |
| U5 | LOD separado em `MeshInstance3D` vs `ImporterMesh` no Godot 4.2 | teste de import, P5 |

Enquanto não fechadas, o perfil carrega o valor com comentário `# [verificar]` e o QC **não** falha
por essas tolerâncias — apenas avisa (`FORGE-W-QC`).
