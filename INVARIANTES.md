# INVARIANTES — Forge3D

**Regra:** quebrar qualquer item é **bug**, não escolha. Cada item tem comando de verificação.
**Base:** P0 (documentos e contratos), 10/11/2026.

Legenda: `[P0]` documental · `[P1]`–`[P5]` entrada · `[P3]` GPU · tabela final mostra automação v0.9.5.

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
forge3d run examples/lote_01.yaml --nao-publicar --json | python3 -c "import json,sys;print(json.load(sys.stdin)['resumo']['publicados'])"
```
Esperado: `0` (`aprovado_nao_publicado`). `tests/test_atomico.py` prova thread observadora, `spy` em
`os.replace` e falha sem lixo (GAP-014/C14).

## I4 — Todo artefato publicado tem manifesto válido `[P1]`

`verify` recalcula `sha256` e reexecuta `G1–G16` + `G11` (`partes[]`); manifesto ausente, schema
errado ou hash divergente = falha.

```bash
forge3d verify <destino>; echo "exit=$?"
TMP=$(mktemp -d); cp -a <destino>/. "$TMP"/
printf 'x' >> "$(find "$TMP" -name '*.glb' -print -quit)"   # um byte trocado no glb
forge3d verify "$TMP"; echo "exit=$?"; rm -rf "$TMP"
```
Esperado: `exit=0` íntegro · `exit=3` com `FORGE-E-MANIFEST` após corromper.

## I5 — QC é portão, não aviso `[P1]`

Reprovação em qualquer gate `G1–G16` (`G12–G14` Roblox, `G15` concept→3D, `G16` deformação/`motor6d`) impede publicação. **Não existe flag de bypass.**

```bash
grep -rnE "force|skip.?qc|--no-verify" src/forge3d/cli/ || echo "OK: sem bypass"
forge3d run tests/fixtures/lote_qc_reprovado.yaml; echo "exit=$?"
```
Esperado: `OK: sem bypass` e `exit=3` com o destino inalterado.

## I6 — Um job de GPU por vez `[P3]`

Dois processos com rota `mesh` não coexistem: o segundo sai `6` com `FORGE-E-RECURSO` em vez de
estourar VRAM.

```bash
python -m pytest tests/test_locks.py -k concorrencia; echo "exit=$?"
```
Esperado: lock recusa 2ª entrada; com GPU, dois `run` `mesh` simultâneos dão `exit=0` e `exit=6` (`FORGE-E-RECURSO`).

## I7 — Licença é gate `[P3]`

Modelo fora da allowlist comercial não gera asset publicado.

```bash
forge3d doctor --json | python3 -c "import json,sys;print(json.load(sys.stdin)['modelos_aptos'])"
grep -rn "hunyuan" profiles/ src/ || echo "OK: ausente"
```
Esperado: só modelos com `uso_comercial: true`. Hunyuan3D-2.x ausente; Pixal3D é MIT
(D112, 18/11/2026) e saiu do bloqueio.

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
forge3d run examples/lote_01.yaml --json | python3 -c "import json,sys;print(json.load(sys.stdin)['resumo']['cache_hits'])"
```
Esperado: igual ao total de tarefas; `trabalho_executado: 0`.

## I12 — Dados só em ext4, nunca em `/mnt/c` `[P0]`

Repo em ext4 sob `/home` (UNC no Windows é normal, `AGENTS.md` §Ambiente). Violação: spec, perfil,
destino ou comando com `/mnt/<letra>/`.

```bash
grep -rnE '/mnt/[a-z]/|\\\\wsl' examples/ profiles/ schemas/ || echo "OK: nenhum caminho /mnt"
```
Esperado: `OK: nenhum caminho /mnt`.

## I13 — Destino sob allowlist `[P1]`

`publish` só escreve em caminho declarado na allowlist (Q2). Destino arbitrário = `exit=2`
`FORGE-E-DESTINO`.

```bash
forge3d plan tests/fixtures/lote_destino_fora.yaml --json; echo "exit=$?"
```
Esperado: `exit=2` com `FORGE-E-DESTINO` (o `plan` também resolve o destino).

## I14 — IP neutro em asset publicado `[P0]`

`asset_id`, `tags`, nome de arquivo, material e textura não contêm nome de franquia de jogo.
Nome de **plataforma alvo** em perfil é permitido (`godot4`, `roblox-r15`): descreve destino, não
origem nem origem estética.

```bash
grep -rniE "minecraft|fortnite|zelda|mario|pokemon|call of duty" examples/ profiles/ schemas/ || echo "OK: nenhuma franquia"
```
Esperado: `OK: nenhuma franquia`. `minecraft_bedrock` é aceito **só** como alias legado de entrada,
com aviso de depreciação, e nunca aparece em manifesto publicado.

## I15 — Projeto de jogo não entra no pipeline `[P1]`

`src/`, `profiles/`, `examples/` e `schemas/` não citam projeto de jogo nem `/home/<user>/`; projeto
entra só por **perfil**, **spec** e **allowlist**.

```bash
python tools/conformidade.py; echo "exit=$?"
```
Esperado: `exit=0` e nenhuma linha `I15:`. `GameZero`/`jogo-roblox` podem aparecer em `DECISOES.md`
(ledger de fato medido) e em `pendencias.md` (ação do operador), não nos contratos.

## Estado da automação (v0.9.5, 19/11/2026)

| Invariante | Como está (medido em 19/11/2026) |
|---|---|
| I1 determinismo | **automatizado** — `test_i1_determinismo` compara sha256 de 12 artefatos em 2 runs com cache limpo |
| I2 spec inválida | **automatizado** — `test_i2_spec_invalida_sai_2_sem_tocar_provider` |
| I3 publish atômico | **automatizado** — `tests/test_atomico.py`: thread observadora, `spy` em `os.replace`, falha no meio (GAP-014/C14) |
| I4 manifesto íntegro | **automatizado** — hash + `test_i4_verify_reexecuta_gates_contra_manifesto` (`G1–G16`, `@1–@7`) + `test_i4_verify_detects_1byte_glb_tamper_and_missing_manifest` |
| I5 QC sem bypass | **automatizado** — `test_i5_qc_nao_tem_bypass` + `test_qc_f26_hardening` + `test_red_r5_qc` + `test_v099_def06_g16` (`G1–G16`) |
| I6 lock de GPU | **parcial** — `test_locks.py` cobre recusa e liberação; falta teste com dois *jobs* reais |
| I7 licença | **parcial** — a allowlist comercial é asseverada em `test_concept.py`; falta exercitar a recusa |
| I8 escala e pivô | **automatizado** — `test_i8_escala_e_pivo_conforme_perfil` |
| I9 Blender pinado | **automatizado no CI** — `doctor` mede, `post.py` recusa ≠ 4.2.x e o job `verificar` baixa 4.2.0 conferindo sha256; `tools/ci_verify.sh` confere a versão no PATH |
| I10 proveniência | **automatizado** — schema + E2E `test_i10_verify_only_manifesto_provenance` |
| I11 idempotência | **automatizado** — `test_i11_idempotencia_rerun_nao_trabalha` |
| I12 caminhos proibidos | **automatizado** — `test_i12_recusa_mnt_e_unc` |
| I13 allowlist | **automatizado** — `test_i13_destino_fora_da_allowlist_falha` e `..._sai_2` |
| I14 IP neutro | **automatizado** — `tools/check-p0.py` |
| I15 projeto fora do pipeline | **automatizado** — `tools/conformidade.py` (item e) + `tests/test_conformidade.py` |

## Ciclo de vida deste arquivo

Artefato de transição já ligado aos testes acima. Regra:
1. prosa do item **encurta** quando o teste entra (2–3 linhas + comando);
2. item sem teste em duas fases seguidas vira pergunta em `DECISOES.md` §4;
3. teto **200 linhas**: o que passa disso é verificação substituída por prosa.
