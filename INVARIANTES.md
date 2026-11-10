# INVARIANTES — Forge3D

**Regra:** quebrar qualquer item é **bug**, não escolha. Cada item tem comando de verificação.
**Base:** P0 (documentos e contratos), 10/11/2026.

Legenda: `[P0]` verificável hoje · `[P1]` depende da implementação (P1–P4) · `[P3]` depende da GPU.

---

## I1 — Determinismo D1 é byte-idêntico `[P1]`

Rota `blocky`, `import` e `modular` produzem o **mesmo hash** em execuções repetidas, com o mesmo
perfil e o mesmo `pipeline_version`. Rota `mesh` **nunca** promete isso (é D2).

```bash
forge3d run examples/lote_01.yaml --json > /tmp/a.json
forge3d run examples/lote_01.yaml --json > /tmp/b.json
python3 -c "import json;a=json.load(open('/tmp/a.json'));b=json.load(open('/tmp/b.json'));print([x['sha256'] for x in a['artifacts']]==[x['sha256'] for x in b['artifacts']])"
```
Esperado: `True`.

## I2 — Spec validada antes de qualquer provider `[P1]`

Nenhum provider é instanciado sem passar pelo JSON Schema e pelas regras de negócio.

```bash
sed 's/altura_metros: 1.10/altura_metros: -1/' examples/lote_01.yaml > /tmp/ruim.yaml
forge3d validate /tmp/ruim.yaml; echo "exit=$?"
```
Esperado: `exit=2` e código `FORGE-E-SPEC`.

## I3 — Nenhuma escrita direta no destino `[P1]`

Arquivo só aparece na pasta do jogo no passo `publish`, vindo de staging por `rename`.

```bash
forge3d run examples/lote_01.yaml --no-publish --json | python3 -c "import json,sys;print(json.load(sys.stdin)['published'])"
```
Esperado: lista vazia. E `tests/invariants/test_i3_publish_atomico.py` prova que nenhum arquivo
parcial aparece no destino durante o run.

## I4 — Todo artefato publicado tem manifesto válido `[P1]`

`verify` recalcula o `sha256` de cada arquivo e compara com o manifesto; manifesto ausente, schema
errado ou hash divergente = falha.

```bash
forge3d verify <destino>; echo "exit=$?"
python3 -c "print(0)" # hash de um arquivo alterado à mão deve derrubar o verify
```
Esperado: `exit=0` íntegro · `exit=3` com `FORGE-E-MANIFEST` após corromper.

## I5 — QC é portão, não aviso `[P1]`

Reprovação em qualquer gate G1–G9 impede publicação. **Não existe flag de bypass.**

```bash
grep -rnE "force|skip.?qc|--no-verify" src/forge3d/cli/ || echo "OK: sem bypass"
forge3d run tests/fixtures/lote_qc_reprovado.yaml; echo "exit=$?"
```
Esperado: `OK: sem bypass` e `exit=3` com o destino inalterado.

## I6 — Um job de GPU por vez `[P3]`

Dois processos com rota `mesh` não coexistem: o segundo sai `6` com `FORGE-E-RECURSO` em vez de
estourar VRAM.

```bash
forge3d run tests/fixtures/lote_mesh.yaml --json & forge3d run tests/fixtures/lote_mesh.yaml --json; echo "exit=$?"
```
Esperado: um completa; o outro `exit=6`. VRAM de pico registrada no manifesto.

## I7 — Licença é gate `[P3]`

Modelo fora da allowlist comercial não gera asset publicado.

```bash
forge3d doctor --json | python3 -c "import json,sys;print(json.load(sys.stdin)['modelos_aptos'])"
grep -rn "hunyuan\|pixal3d" profiles/ src/ || echo "OK: ausente"
```
Esperado: só modelos com `uso_comercial: true`. Hunyuan3D-2.x e Pixal3D ausentes (D18).

## I8 — Escala e pivô conforme o perfil `[P1]`

Diferença de altura ≤ **0,5 %** do declarado; pivô a ≤ **1 mm** do ponto declarado, por perfil.

```bash
forge3d verify <destino> --only=escala,pivo --json
```
Esperado: `{"escala":{"delta_pct":0.0},"pivo":{"delta_mm":0.0}}` dentro da tolerância do perfil.

## I9 — Blender pinado e canal por arquivo `[P1]`

Blender fora de `4.2.x` = falha de preflight. Scripts `bpy` leem e escrevem JSON em disco; nunca
dependem de stdout.

```bash
forge3d doctor --json | python3 -c "import json,sys;d=json.load(sys.stdin);print(d['blender'])"
grep -rn "pip install" blender/ || echo "OK: não instala no python do Blender"
```
Esperado: `4.2.x` · `OK: não instala no python do Blender`.

## I10 — Proveniência completa `[P1]` `[P3]`

Todo manifesto publicado tem `spec_hash`, `pipeline_version`, `determinism`, provider+versão, `seed`
(quando D2), `licenca` e `created_at` não nulos.

```bash
forge3d verify <destino> --only=manifesto --json | python3 -c "import json,sys;print(json.load(sys.stdin)['faltando'])"
```
Esperado: `[]`.

## I11 — Idempotência: rerun sem mudança não trabalha `[P1]`

Segunda execução idêntica reporta zero misses e não toca nenhum arquivo.

```bash
forge3d run examples/lote_01.yaml --json | python3 -c "import json,sys;print(json.load(sys.stdin)['cache_hits'])"
```
Esperado: igual ao total de tarefas; `trabalho_executado: 0`.

## I12 — Nada roda sobre `/mnt/c` ou caminho UNC `[P0]`

I/O lento e `edit` já falhou em UNC (medido no `conselho`). Exemplos, perfis e destinos padrão usam
ext4 sob `/home`.

```bash
grep -rnE '/mnt/[a-z]/|\\\\wsl' examples/ profiles/ schemas/ || echo "OK: nenhum caminho /mnt"
```
Esperado: `OK: nenhum caminho /mnt`.

## I13 — Destino sob allowlist `[P1]`

`publish` só escreve em caminho declarado na allowlist (Q2). Destino arbitrário = `exit=2`
`FORGE-E-DESTINO`.

```bash
forge3d publish --destino /tmp/qualquer --json; echo "exit=$?"
```
Esperado: `exit=2`.

## I14 — IP neutro em asset publicado `[P0]`

`asset_id`, `tags`, nome de arquivo, material e textura não contêm nome de franquia de jogo.
Nome de **plataforma alvo** em perfil é permitido (`godot4`, `roblox-r15`): descreve destino, não
origem nem origem estética.

```bash
grep -rniE "minecraft|fortnite|zelda|mario|pokemon|call of duty" examples/ profiles/ schemas/ || echo "OK: nenhuma franquia"
```
Esperado: `OK: nenhuma franquia`. `minecraft_bedrock` é aceito **só** como alias legado de entrada,
com aviso de depreciação, e nunca aparece em manifesto publicado.

## Estado da automação (P1, 10/11/2026)

| Invariante | Como está |
|---|---|
| I1 determinismo | **automatizado** — `test_i1_determinismo` compara sha256 de 12 artefatos em 2 runs com cache limpo |
| I2 spec inválida | **automatizado** — `test_i2_spec_invalida_sai_2_sem_tocar_provider` |
| I3 publish atômico | **parcial** — `rename` + manifesto por último implementados; falta teste de observação (GAP-014) |
| I4 manifesto íntegro | **automatizado** — `test_i4_verify_pega_arquivo_adulterado` |
| I5 QC sem bypass | **automatizado** — `test_i5_qc_nao_tem_bypass` (varre a fonte) |
| I6 lock de GPU | implementado em `locks.py`, sem teste (rota `mesh` só em P3) |
| I7 licença | allowlist implementada em `providers.LICENCAS`; teste quando a rota `mesh` entrar |
| I8 escala e pivô | **automatizado** — `test_i8_escala_e_pivo_conforme_perfil` |
| I9 Blender pinado | `doctor` verifica 4.2.x; falta teste dedicado |
| I10 proveniência | garantida pelo schema do manifesto; falta teste de campo obrigatório |
| I11 idempotência | **automatizado** — `test_i11_idempotencia_rerun_nao_trabalha` |
| I12 caminhos proibidos | **automatizado** — `test_i12_recusa_mnt_e_unc` |
| I13 allowlist | **automatizado** — `test_i13_destino_fora_da_allowlist_falha` e `..._sai_2` |
| I14 IP neutro | **automatizado** — `tools/check-p0.py` |

## Ciclo de vida deste arquivo

`INVARIANTES.md` é **artefato de transição** (ver `skills/context-recovery/SKILL.md`, fase 3). Ele existe
porque a implementação ainda não existe. Regra:

1. cada `I<n>` vira `tests/invariants/test_i<n>_*.py` quando a fase correspondente chega;
2. a linha é **apagada** deste arquivo quando o teste entra no CI — sobra só o comando;
3. invariante que não vira teste em duas fases seguidas é **pergunta**, não dogma (vai para
   `DECISOES.md` §4).

Consequência desejada: este arquivo deve **encolher**. Se ele cresce, a verificação está sendo
substituída por prosa — e prosa não reprova build.
