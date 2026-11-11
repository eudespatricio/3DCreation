# Integração — como outro projeto consome o Forge3D

> Fronteira: **CLI + arquivo de lote + manifesto**. O projeto de jogo não importa código, não roda
> daemon e não precisa do Forge3D instalado para **consumir** o asset (D3/D25).
> Os comandos citados aqui são conferidos por `tests/test_doc_comandos.py` contra o `argparse` real.

## 1. Instalar

```bash
uv tool install --from /caminho/para/3DCreation forge3d
forge3d --version
```

O wheel leva `schemas/`, `profiles/` e `blender/` dentro do pacote: a CLI funciona sem o repositório
do lado (`tools/ci_dist.sh` prova isso no CI). Alternativa dentro do venv do próprio projeto:
`uv pip install /caminho/para/3DCreation`.

## 2. O que o host precisa

| Comando | Blender 4.2.x | GPU |
|---|---|---|
| `validate` · `plan` · `query` · `migrate` · `verify` | **não** | não |
| `export-r15` · `export-anim` | **não** | não |
| `run` (rotas `blocky`/`import`/`modular`) | **sim** | não |
| `run` (rota `mesh`) | **sim** | **sim** (6 GB, serializada por lock) |

Medido em 11/11/2026: `validate`, `plan`, `verify` e `export-r15` rodaram com `PATH` sem Blender.
Só quem **gera** precisa dele.

## 3. Autorizar o destino uma vez

Destino é *deny by default*: o único gravável sem configuração é o sandbox do Forge3D (D23).

```bash
forge3d allowlist add /caminho/do/jogo/assets/forge3d
```

O arquivo é global, fora do repo do jogo:

```yaml
schema: forge3d/allowlist@1
raizes:
- /caminho/do/jogo/assets/forge3d
```

Em CI, isole config e estado para não depender da máquina:

```bash
export XDG_CONFIG_HOME="$PWD/.ci/forge3d-config"
export XDG_STATE_HOME="$PWD/.ci/forge3d-state"
forge3d allowlist add "$PWD/assets/forge3d"
```

> `plan` também resolve o destino: sem allowlist ele sai `2` (`FORGE-E-DESTINO`), não só o `run`.

## 4. Escrever o lote (`spec@3`)

Topo obrigatório: `schema`, `projeto`, `perfil`, `destino_exportacao`, `lote`. Item obrigatório:
`id`, `tipo`. Exemplo mínimo que passa em `validate`:

```yaml
schema: forge3d/spec@3
projeto: meu-jogo
perfil: godot4                 # ou roblox-r15
destino_exportacao: /caminho/do/jogo/assets/forge3d

politica:
  falha: continuar             # continuar | abortar
  custo_max_min: 15
  seed_base: 20261111          # mesh/modular herdam quando o item não declara seed

paleta: ["#6f7f8f", "#2e3440", "#1b1f24"]

lote:
  - id: weapon.caixa.demo.01   # padrão: a.b.c, minúsculo
    tipo: prop_equipavel
    rota: blocky
    prompt: caixa de madeira com ferragens
    altura_metros: 0.45
    colisao: convex
    tags: [props, madeira]
```

Condicionais que o contrato aplica (schema + B1–B17 em `src/forge3d/spec.py`):

| Situação | Exige |
|---|---|
| `rota: mesh` | `seed` e `prompt` |
| `rota: import` | `origem` (arquivo existente) |
| `rota: modular` | bloco `modular` com `grade`/`modulos`, e `seed` |
| `tipo` ≠ `textura`/`mapa_setor` | `altura_metros` |
| `auto_rig: true` | `tipo` humanoide/criatura e `esqueleto` do perfil |
| `animacoes_base` | `auto_rig: true` |
| `parte` | só rota `blocky` |
| `id` | único e no padrão `a.b.c` |

Lote antigo (`spec@1`/`@2`) sobe sem reescrever à mão:

```bash
forge3d migrate lote.yaml --saida lote.v3.yaml   # dry-run sem --saida/--em-lugar
```

## 5. O ciclo no pipe

```bash
set -uo pipefail

forge3d validate lote.yaml                    # 2 = entrada inválida
forge3d plan     lote.yaml --json > plano.json   # custo e cache, sem gerar

forge3d run lote.yaml --json > run.json
rc=$?
case $rc in
  0) echo "publicado (ou cache)" ;;
  7) echo "parcial: ver run.json" ;;
  6) echo "recurso ocupado: retry" ; exit 6 ;;
  *) echo "falhou: $rc" ; exit $rc ;;
esac

forge3d verify "$DESTINO"                      # 3 = QC/manifesto
```

- `--json` devolve **um objeto por invocação** (`forge3d/report@1`) com `resumo`, `itens[]` e
  `artifacts[]`; texto humano vai para stdout só sem `--json` (contrato em `docs/contratos.md` §4).
- Gerar sem publicar (PR que não escreve no jogo): `forge3d run lote.yaml --nao-publicar --json`.
- O item que não publica aparece como `reprovado`, `bloqueado`, `falhou` ou `cache_hit` — o pipe
  decide pelo `estado`, não pela mensagem.

## 6. Exit codes

| Código | Significado | O pipe deve |
|---|---|---|
| `0` | tudo publicado ou cache-hit | seguir |
| `2` | spec, destino, allowlist ou caminho inválido | falhar o build |
| `3` | QC reprovou / manifesto inválido | falhar o build e abrir o relatório |
| `4` | ambiente (Blender, perfil, schema, disco) | falhar e rodar `doctor` |
| `5` | provider falhou / licença não permite | decidir: retry ou remover item |
| `6` | recurso ocupado/insuficiente (GPU, lock) | **retry** |
| `7` | parcial: parte publicada, parte pendente | sucesso com pendência |

Quando nada publicou, vale a causa mais grave (`4 > 2 > 6 > 5 > 3`). `0` só quando tudo publicou.

## 7. O que o jogo lê: o manifesto

`<asset_id>.manifest.json` (`manifest@1`/`@2`/`@3`; o corrente é `@3`). Campos que o consumidor usa:

```json
{
  "asset_id": "weapon.caixa.demo.01",
  "schema": "forge3d/manifest@3",
  "perfil": "godot4",
  "determinism": "D1",
  "unidades_export": { "metros_por_unidade": 1.0, "escala_saida": 1.0 },
  "geometry": { "triangulos": 300, "bbox_m": [0.35, 0.45, 0.35], "materiais": 1 },
  "files": [
    { "caminho": "weapon.caixa.demo.01.glb", "papel": "mesh", "sha256": "sha256:…", "bytes": 48120 },
    { "caminho": "weapon.caixa.demo.01_baseColor.png", "papel": "textura", "sha256": "sha256:…", "bytes": 1024 }
  ],
  "colisao": { "tipo": "convex", "partes": 1 },
  "lod": [], "animacoes": [],
  "qc": { "aprovado": true, "gates": [] }
}
```

- **`bbox_m` é em metros**; o `glb` está na unidade do arquivo (`unidades_export.metros_por_unidade`).
  Em `roblox-r15` o glb sai em **studs** (`escala_saida: 3.5714`): não converta à mão (D62).
- **Confie no `sha256`** de `files[]` e no `papel` de cada arquivo; LOD e colisor são arquivos
  próprios (`lod`, `colisor`), não sufixo adivinhado.
- `determinism`: `D1` = byte-idêntico entre execuções (`blocky`/`import`/`modular`); `D2` = gerado
  por modelo, **não** reproduzível (`mesh`) — versione esse asset no repo do jogo (D73/LFS).

## 8. Por plataforma

**Godot 4** (`perfil: godot4`) — glb em metros, frente `-Z`, pivô `base` (estático/personagem) ou
`empunhadura` (20 % da altura). Colisão sai como `UCX_*` ou irmão `*_colisao.glb`; ative
`addons/forge3d/` (`post_import.gd`) para configurar loop linear em `idle`/`walk`/`run`,
`visibility_range` automático do `*_LOD1.glb` e `PostImport.montar_character_body()` com `BoneAttachment3D`.

Para copiar um destino já verificado do ext4 para outra pasta (ex.: projeto aberto no Windows):

```bash
forge3d sync ~/.local/state/forge3d/saida/lote_01 --para <pasta_destino> --limpar
```

Para projetos Roblox gerenciados via **Rojo**, passe `--rojo-lua <caminho/Assets.lua>` junto com `sync`:

```bash
forge3d sync ~/.local/state/forge3d/saida/lote_r15 --para ./assets --rojo-lua ./src/Assets.lua
```

**Roblox** (`perfil: roblox-r15`) — glb em studs; para asset nativo, multi-clipe e PBR `SurfaceAppearance`:

```bash
forge3d export-r15 lote.yaml --item personagem.r15.guard.01 --texturas-dir ~/.local/state/forge3d/saida/lote_r15 --saida guard.rbxlx
forge3d export-anim lote.yaml --item personagem.r15.guard.01 --todos --saida guard_anims.rbxmx
forge3d export-surface ~/.local/state/forge3d/saida/lote_r15 --item personagem.r15.guard.01 --saida guard_surface.rbxmx
forge3d upload-model guard.glb --creator-id <id> --dry-run
forge3d upload-animation guard_anims.rbxmx --creator-id <id>
```

A key do Open Cloud fica em `~/.config/forge3d/roblox.key`, **fora** do repositório.

## 9. Portão de CI do projeto consumidor

`verify` não precisa de Blender e é o que impede asset trocado ou perfil divergente:

```bash
forge3d verify /caminho/do/jogo/assets/forge3d
```

Para recortar o que checar (e o custo): `--only=manifesto,hash,escala,pivo,gates`.

```bash
forge3d verify assets/forge3d --only=manifesto     # proveniencia; devolve faltando[]
forge3d verify assets/forge3d --only=escala,pivo   # devolve escala.delta_pct e pivo.delta_mm
```

`verify` reexecuta G1–G10 contra o perfil **atual** (D32): se o perfil do jogo mudou de tolerância,
ele acusa em vez de confiar no manifesto antigo.

## 10. Tropeços que custam tempo

1. Destino fora da allowlist → `2` no `plan` **e** no `run` (não só no `run`).
2. `destino_exportacao` em `/mnt/<letra>` ou caminho UNC → `2` (`FORGE-E-PATH`); use ext4.
3. Blender ausente ou fora de 4.2.x → `4` no `run` (só nele).
4. `politica.falha: parar` não existe: o enum é `continuar` | `abortar`.
5. Dois `run` de rota `mesh` ao mesmo tempo → o segundo sai `6`; é o lock, não bug: retry.
6. `--only` recorta o **veredito**, não o I/O dos gates: `escala`/`pivo` ainda leem o glb
   (reexecutam o G2). Os aspectos são fixos (`manifesto`, `hash`, `escala`, `pivo`, `gates`);
   token fora disso sai `2`.

## 11. Onde está o contrato

- `schemas/spec.v3.schema.json` (entrada) e `schemas/manifest.v3.schema.json` (saída)
- `docs/contratos.md` — regras, B1–B17, saída JSON, exit codes, códigos de erro
- `profiles/godot4.yaml` · `profiles/roblox-r15.yaml` — unidade, eixos, pivô, colisão, tolerâncias
- `docs/perfis-export.md` — o que cada plataforma espera do arquivo

## 12. Plugar agentes externos via MCP (`stdio`)

Agentes, IDEs ou scripts podem disparar `validate`, `plan`, `run`, `verify`, `query` e `doctor` diretamente via JSON-RPC 2.0:

```bash
forge3d mcp
```

Exemplo de entrada em configuração de servidor MCP (`command` + `args` no host do projeto):

```json
{
  "mcpServers": {
    "forge3d": {
      "command": "forge3d",
      "args": ["mcp"]
    }
  }
}
```
