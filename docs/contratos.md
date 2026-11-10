# Contratos — spec, manifesto, CLI

> Esta é a **fronteira** com os projetos de jogo. Mudança aqui quebra pipe de terceiro; por isso é
> versionada e nunca silenciosa (D20). Fonte de verdade executável: `schemas/*.json`.

## 1. Regras gerais

| Regra | Definição |
|---|---|
| Versionamento | `schema: forge3d/<tipo>@<major>`. Campo novo **opcional** → mesma major. Rename, remoção, mudança de tipo/semântica → major novo |
| stdout | **um único objeto JSON** com `--json`; caso contrário, texto humano. Nunca mistura |
| stderr | log humano, progresso, stack trace. **Nunca** consumido por pipe automático |
| Exit code | estável (§5). Ramificação de pipe acontece por exit code + `FORGE-E-*`, nunca por regex de mensagem |
| Caminhos | absolutos ou relativos ao arquivo de lote. `/mnt/*` e UNC são **recusados** (I12) |
| Encoding | UTF-8, LF. JSON de saída com chaves ordenadas e sem espaços variáveis (hash estável) |
| Relógio | `created_at` em UTC ISO-8601; nunca entra na chave de cache |

## 2. `spec@1` — a entrada

Exemplo canônico: [`../examples/lote_01.yaml`](../examples/lote_01.yaml).

### Raiz

| Campo | Tipo | Obrig. | Regra |
|---|---|---|---|
| `schema` | string | sim | constante `forge3d/spec@1` |
| `projeto` | string | sim | slug `^[a-z][a-z0-9_-]*$` |
| `perfil` | string | sim | `godot4` \| `roblox-r15` \| caminho para YAML de perfil |
| `destino_exportacao` | string | sim | sob allowlist (D23); `~` é expandido; recusa `/mnt/*` e UNC |
| `estilo_global` | string | não | `blocky_voxel` \| `lowpoly_lit` \| `stylized_pbr`. Default vem do perfil |
| `paleta` | string[] | não | 1–16 cores `#rrggbb`; usada pela rota `blocky` |
| `politica` | objeto | não | `falha` (`continuar`\|`abortar`), `custo_max_min` (int), `seed_base` (int) |
| `lote` | objeto[] | sim | 1..1000 itens |

**Aliases legados aceitos** (com aviso `FORGE-W-ALIAS`, D19):
`minecraft_bedrock` → `blocky_voxel` · `low_poly_pixel_lit` → `lowpoly_lit` · `stylized_pbr` → igual.
A normalização acontece **antes** da validação: o schema só aceita o valor canônico, então o alias
nunca aparece em manifesto publicado (I14).

### Item do lote

| Campo | Tipo | Obrig. | Regra |
|---|---|---|---|
| `id` | string | sim | `^[a-z][a-z0-9_]*(\.[a-z0-9_]+){1,4}$`, único, **estável** (mudar `id` = asset novo) |
| `tipo` | string | sim | `prop_estatico` \| `prop_equipavel` \| `personagem_humanoide` \| `criatura` \| `modulo_cenario` \| `textura` \| `mapa_setor` |
| `rota` | string | não | `blocky` \| `import` \| `mesh` \| `modular`. Default derivado de `estilo_global` |
| `prompt` | string | cond. | obrigatório em `blocky`/`mesh`; ≤ 2.000 caracteres |
| `altura_metros` | number | cond. | obrigatório exceto `textura`/`mapa_setor`; faixa `0.05–10.0` |
| `pivot` | string | não | `empunhadura` \| `base` \| `centro` \| `origem` \| `topo`; resolvido por regra no perfil |
| `limite_triangulos` | integer | não | `50–50.000`; default por `tipo` no perfil |
| `material` | string | não | `opaque` \| `alpha_clip` \| `transparent` \| `pbr`; default `opaque` |
| `colisao` | string | não | `none` \| `box` \| `convex` \| `ucx`; default do perfil por `tipo` |
| `lod` | integer[] | não | percentuais **decrescentes**, começando em `100`; default `[100]` |
| `seed` | integer | cond. | **obrigatório** em `rota: mesh`; opcional nas demais |
| `auto_rig` | boolean | não | default `false`; exige `tipo` humanoide/criatura |
| `esqueleto` | string | não | `godot-humanoid@1` \| `r15@1`; default do perfil |
| `animacoes_base` | string[] | não | **reservado** (D14). Preenchido ⇒ aviso `FORGE-W-ANIM`, nunca erro |
| `origem` | string | cond. | obrigatório em `rota: import`; arquivo existente `.blend`/`.bbmodel`/`.glb`/`.obj` |
| `tags` | string[] | não | `^[a-z0-9][a-z0-9_-]*$`, ≤ 8, sem nome de franquia (I14) |

### Regras de negócio (além do schema)

| # | Regra | Violação |
|---|---|---|
| B1 | `id` único no lote | erro |
| B2 | `seed` obrigatório em `mesh` | erro `FORGE-E-SPEC` |
| B3 | `origem` existe e extensão suportada em `import` | erro |
| B4 | `lod[0] == 100` e estritamente decrescente | erro |
| B5 | `limite_triangulos` coerente com a rota (`blocky` ≤ 5.000) | aviso se acima, erro se > 50.000 |
| B6 | `auto_rig` só em `personagem_humanoide`/`criatura` | erro |
| B7 | `destino_exportacao` sob allowlist e em filesystem local | erro `FORGE-E-DESTINO` |
| B8 | `paleta` ≤ 16 cores, todas `#rrggbb` | erro |
| B9 | `prompt` não vazio quando exigido | erro |
| B10 | Esqueleto declarado existe no perfil | erro |

## 3. `manifest@1` — a saída

Viaja **junto** do asset, no destino. É o que permite o jogo validar sem ter o Forge3D instalado.

| Campo | Tipo | Conteúdo |
|---|---|---|
| `schema` | string | `forge3d/manifest@1` |
| `asset_id` / `projeto` / `perfil` / `rota` | string | identidade, alvo e técnica de geração |
| `tags` | string[] | rótulos do item; consultáveis por `forge3d query --tag` |
| `spec_hash` | string | `sha256:` do spec canônico que originou o asset |
| `pipeline_version` | string | versão do Forge3D (git describe) — entra na chave de cache |
| `determinism` | string | `D1` \| `D2` \| `D3` |
| `providers` | objeto | `geometry` e `texture`: `{name, version, license, seed}` |
| `geometry` | objeto | `triangulos`, `vertices`, `bbox_m[3]`, `materiais` |
| `rig` | objeto\|null | `{esqueleto, ossos}` |
| `lod` | objeto[] | `{nivel, triangulos, arquivo}` |
| `colisao` | objeto | `{tipo, partes, arquivo}` |
| `files` | objeto[] | `{caminho, papel, sha256, bytes}` — `papel` ∈ `mesh\|textura\|normal\|colisor\|lod\|animacao` |
| `qc` | objeto | `{aprovado, gates: [{id, status, medido, limite}]}` |
| `licenca` | objeto | `{modelo, uso_comercial, notice}` |
| `origem_spec` | objeto | `{arquivo, hash}` |
| `run_id` / `created_at` | string | rastreabilidade (UTC) |

Schema completo: [`../schemas/manifest.v1.schema.json`](../schemas/manifest.v1.schema.json).

## 4. Saída do CLI (`--json`)

```json
{
  "schema": "forge3d/report@1",
  "comando": "run",
  "run_id": "01JB0X8K2Q",
  "exit": 7,
  "resumo": {
    "total": 3, "publicados": 2, "reprovados": 0, "bloqueados": 1,
    "falhas": 0, "cache_hits": 1, "trabalho_executado": 2, "duracao_s": 12.4
  },
  "itens": [
    {
      "id": "weapon.sword.fire.01",
      "estado": "publicado",
      "rota": "blocky",
      "determinism": "D1",
      "qc": "aprovado",
      "artefatos": [{"caminho": "weapon.sword.fire.01.glb", "sha256": "sha256:ab…"}]
    },
    {
      "id": "mob.skeleton.guard",
      "estado": "bloqueado",
      "rota": "mesh",
      "codigo": "FORGE-E-RECURSO",
      "razao": "VRAM livre 812 MiB < 6144 MiB exigidos pelo provider sf3d"
    }
  ],
  "artifacts": [
    {"id": "weapon.sword.fire.01", "caminho": "weapon.sword.fire.01.glb", "sha256": "sha256:ab…"}
  ]
}
```

`estado` ∈ `publicado` · `aprovado_nao_publicado` · `reprovado` · `bloqueado` · `falhou` · `cache_hit`.

## 5. Exit codes

| Código | Significado | O pipe deve |
|---|---|---|
| `0` | tudo publicado (ou tudo cache-hit) | seguir |
| `2` | entrada inválida: spec, destino, caminho, allowlist | **falhar o build**, corrigir spec |
| `3` | QC reprovou ou manifesto inválido | falhar o build, abrir relatório |
| `4` | ambiente: blender ausente/versão, perfil, schema, disco | falhar o build, rodar `doctor` |
| `5` | provider falhou ou licença não permite | decidir: retry ou remover item |
| `6` | recurso ocupado/insuficiente (GPU, lock) | **retry depois**, não é bug |
| `7` | parcial: parte publicada, parte bloqueada/falhou | tratar como sucesso com pendência |

Quando **nada** foi publicado, vale a causa mais grave (`4 > 2 > 6 > 5 > 3`). Quando **algo** foi
publicado e algo falhou ou ficou bloqueado, o lote é **parcial**: `7`. `0` só quando todo item
publicou ou veio do cache.

## 6. Códigos de erro e aviso

| Código | Quando | Exit |
|---|---|---|
| `FORGE-E-SPEC` | schema ou regra de negócio violada | 2 |
| `FORGE-E-DESTINO` | destino fora da allowlist | 2 |
| `FORGE-E-PATH` | caminho em `/mnt/*`, UNC ou fora do escopo | 2 |
| `FORGE-E-AMBIENTE` | blender, perfil, schema ou disco inválido | 4 |
| `FORGE-E-PROVIDER` | provider não instalado/registrado | 5 |
| `FORGE-E-PROVIDER-RUN` | provider falhou durante geração | 5 |
| `FORGE-E-LICENCA` | modelo sem permissão de uso comercial | 5 |
| `FORGE-E-RECURSO` | VRAM, lock, disco, timeout de recurso | 6 |
| `FORGE-E-BPY` | falha no script Blender (2 tentativas) | 5 |
| `FORGE-E-QC` | gate G1–G9 reprovado | 3 |
| `FORGE-E-MANIFEST` | manifesto ausente, inválido ou hash divergente | 3 |
| `FORGE-E-INTERNO` | bug do Forge3D | 4 |
| `FORGE-W-ALIAS` | alias legado de estilo usado | — |
| `FORGE-W-ANIM` | `animacoes_base` preenchido (reservado, D14) | — |
| `FORGE-W-QC` | gate em estado `warn` | — |

## 7. Compatibilidade

- **Aditivo** (campo opcional novo, valor novo em enum com default): mantém `@1`.
- **Quebra** (renomear, tornar obrigatório, mudar unidade, mudar default): `@2`, com `forge3d migrate`
  lendo `@1` e o `@1` congelado por uma major.
- O manifesto carrega a major do spec **com** a do manifesto: asset velho continua verificável.

## 8. Exemplo ilustrativo

[`../examples/manifest.exemplo.json`](../examples/manifest.exemplo.json) é um manifesto completo de
referência, com valores e hashes **ilustrativos**. Serve para três coisas: validar o schema, servir de
fixture de teste e mostrar ao consumidor do jogo exatamente o que ele recebe.
