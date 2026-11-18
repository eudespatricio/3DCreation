# PLANO DE HANDOFF — melhorias e defeitos (18/11/2026)

> **Para a próxima janela.** Contexto: sessão de 18/11/2026 — investigação de qualidade de assets,
> `referencia_estilo` (D113), Pixal3D MIT (D112), auditoria do GameOne e testes ponta a ponta de
> concept→i23d→rig→animação. **Tudo aqui está verificado** com evidência neste arquivo.
>
> **Regras que valem nesta implementação:** cada mudança de código de pipeline exige entrada no
> `DECISOES.md` (ledger, D114+) e bump de `PIPELINE_VERSION` quando a saída muda (D6); portões
> `pytest` + `tools/conformidade.py` + `tools/check-p0.py` + `tools/check-contexto.sh` verdes ao fim;
> **nenhum conector novo** (decisão do operador: fazer as conexões existentes trabalharem melhor);
> IP: D4 é **referência conceitual**, nunca input de imagem em asset de produção (I14).

## 0. Estado atual (não reabrir)

- `PIPELINE_VERSION` **0.9.2**; suite **523 verdes + 1 GPU (skip)** em **524 testes**;
  conformidade/P0/contexto verdes (medido em 18/11/2026).
- **D112**: Pixal3D é **MIT** (LICENSE do repo verificada) e saiu do bloqueio do D18
  (`vault.py`, `tests/test_cc0_vault_llm.py`, `INVARIANTES.md` I7, `docs/riscos-e-licencas.md`).
- **D113**: `referencia_estilo` no concept via Gemini — campo aditivo no `spec@6`, regra **B23**,
  parte de imagem no payload do Interactions API, hash na chave de cache, `+ref<12>` na versão do
  `providers.texture`, `concept.VERSAO 0.2.4`, testes em `tests/test_cloud_connectors.py` e
  `tests/test_spec_v6_g11.py`.
- `docs/avaliacao-qualidade-3d.md` (rev. 2, sem conexões novas) e previews dos demos em
  `docs/preview/d113_demo/` (ver §5).

## 1. Defeitos e riscos encontrados (com evidência)

### D-01 — B23 aceita `origem` + `referencia_estilo` juntos (estilo silenciosamente ignorado) — **P0**
- **Evidência**: `spec.preparar` aceitou a combinação (auditoria em 18/11/2026: "VALIDOU e seria
  executado"); no fluxo real, com `origem` o concept **não roda** (`mesh.py` `gerar()`:
  `if origem: … else: _gerar_concept_com_retry`), então a referência nunca é usada.
- **Correção**: B23 rejeita a combinação (são mutuamente exclusivos: `origem` é input do i23d;
  `referencia_estilo` ancora o concept). Mensagem explícita + teste em `tests/test_spec_v6_g11.py`.

### D-02 — Autorig força `quadruped@1` em `tipo: criatura` mesmo com esqueleto humanoide explícito — **P0**
- **Evidência**: `blender/autorig.py::auto_rigar_por_tipo` (≈L2579-2604): só honra esqueleto explícito
  se estiver na família criatura; para `tipo_norm in ("criatura_quadrupede","criatura")` força
  `quadruped@1`. Run do mob bípede com `esqueleto: godot-humanoid-aa@1` publicou glb com
  **23 ossos quadruped** (`FrontFoot`, `Tail`, `MountSeat`).
- **Correção**: esqueleto explícito vence — `esq ∈ família humanoide` → `auto_rigar_humanoide`;
  `esq ∈ família criatura` → criatura; fallback por tipo só quando não explicitado. Regra de
  negócio nova (B24?) recusando combinação esqueleto×tipo incompatível. Teste sem Blender no
  dispatch (`auto_rigar_por_tipo` com mock), e teste Blender no `verificar` se possível.

### D-03 — Manifesto declara esqueleto do spec, glb tem outro (contrato quebrado; `verify` pega) — **P0**
- **Evidência**: `verify` (exit 3) em `saida/mob_rig_v1`: G6 reexecutado acusou
  `godot-humanoid-aa@1` com 23 ossos e **49 ossos do mapa faltando**; `fora_do_mapa` =
  `FrontFoot`, `BackFoot`, `Tail*`, `MountSeat` (quadruped). O run interno tinha aprovado porque o
  G6 do run mediu o rig real; o manifesto publicou o esqueleto pedido.
- **Correção**: fonte única de verdade — `rig.esqueleto` do manifesto = esqueleto **real medido**
  (`medidas`), e o run deve **falhar** se o pedido ≠ real (nunca publicar divergente). Reaproveitar
  `postprocess.py` L1914-1938 (`esqueleto_efetivo` detectado pelos ossos) e
  `publish.py` L153-181/`providers`.
- **Aceite**: `verify` verde no `mob_rig_v1` após re-run; teste de contrato sem GPU
  (manifesto.esqueleto == medido) e o teste do run com Blender (job `verificar`).

### D-04 — Sockets pedidos descartados em silêncio — **P0**
- **Evidência**: spec com `sockets: [Hand.R, Hand.L]`; manifesto `sockets: []` (sem erro/aviso),
  porque o rig quadruped não tem mãos.
- **Correção**: se o socket pedido não existe no esqueleto final → erro explícito
  (`FORGE-E-SPEC`/`FORGE-E-QC`); nunca descarte silencioso. Teste.

### D-05 — Concept do Gemini: bytes JPEG salvos como `concept.png`; dimensões reais ≠ pedidas — **P0**
- **Evidência**: `docs/preview/d113_demo/mob_concept/concept.png` é **JPEG 848×1264** (o `file`
  aponta JFIF) e o demo do Kaelen veio **JPEG 1376×768**; o `meta` registra `largura/altura=512`.
  `cloud_ai.py` grava os bytes crus; `concept_resultado.json`/manifesto não registram o real.
- **Correção**: normalizar para **PNG real** no `concept.py` (Pillow é permitido no núcleo; o teste
  `test_cloud_ai_usa_apenas_stdlib_d26` proíbe import em `cloud_ai.py` — manter a normalização fora
  dele), registrar `largura_real`/`altura_real` no meta e no manifesto; teste com JPEG mockado.
- **Risco atual**: `verify`/G3 valida integridade PNG em texturas; um JPEG renomeado pode passar
  hoje por engano e falhar depois — fechar agora.

### D-06 — `prompt_final` não fica na proveniência — **P1**
- **Evidência**: relatório do run não contém "prompt"; `concept_resultado.json` (com `prompt_final`)
  vive no staging e é limpo após o publish; o manifesto só guarda `spec_hash` + versão do provider.
- **Correção**: sidecar `concept.json` publicado junto do asset (prompt_final, negativo, referência
  hash, modelo, seed, revisão) e/ou hash do prompt na versão do `providers.texture`. Teste.

### D-07 — Template humanoide ignora o concept para a roupa — **P1 (decisão + doc)**
- **Evidência**: Kaelen v3 (do zero, `template_humanoide` default) com prompt de cavaleiro dracônico
  saiu **idêntico ao Kaelen do jogo** (túnica/cinto/pulseiras/botas CC0); `projetar_foto_2d` default
  `False` (`mesh.py` ≈L997); as layers vêm de D99. O concept só dá marcos/proporções.
- **Decisão necessária**: (a) documentar como característica (herói = template + layers; o visual
  dracônico vem de peças `modular_armor` separadas ou do i23d puro), ou (b) mapear paleta do concept
  para as layers / `projetar_foto_2d` para heróis. Recomendação: (a) + doc; (b) só com medição.

### D-08 — Re-observação de orientação em brutos simétricos (G2) — **P1**
- **Evidência**: mob com seed 20261118 reprovado (`malha_de_costas`, `criatura_de_costas`);
  seed 20261119 aprovado. O concept era front (face e núcleo visíveis) — a reconstrução é que virou.
- **Correção**: (a) retry automático de seed quando G2 reprovar por orientação (política opt-in no
  spec), e/ou (b) revisar o sinal de frente para criaturas simétricas. **Sem bypass** (I5).

### D-09 — Doc drift (repositório) — **P0 (documental)**
- `src/forge3d/providers/mesh.py:11`: "concept continua em GAP-026: por isso a rota exige origem"
  (contradiz D35 e o código).
- `docs/rotas-e-providers.md:100`: "A entrada é `origem` (PNG) — o concept text-to-image é GAP-026".
- `docs/rotas-e-providers.md:81`: image→3D 1ª escolha = **SF3D** (encerrado em D27; é TripoSR).
- `docs/rotas-e-providers.md:84-85`: "Não entra: TRELLIS.2 …, Pixal3D (não-comercial)" — TRELLIS
  conectado via endpoint (D101); Pixal3D é MIT (D112).
- **Aceite**: texto alinhado ao código; nenhum comando citado quebrado (D82).

### D-10 — Doc do GameOne (fora deste repo) — **P0 (da próxima janela, no repo do jogo)**
- `05_ferramentas_e_pipeline/01_PIPELINE_BLENDER_E_FORGE3D.md` §2.2: exemplo de arma com
  `rota: mesh` **sem `prompt`** → falharia hoje no B2 (schema exige `prompt` para todo mesh).
- Exemplo da `lyra` referencia `<CONCEPT_VAULT>/heroes/lyra_guardia_apose_ref` — **não existem
  folhas A-pose** (busca em GameOne/state: nada); o vault tem GLBs finais.
- **Ação**: corrigir exemplos ou criar o `CONCEPT_VAULT` com referências A-pose reais; registrar que
  o fluxo de produção atual do jogo é `import` (81/81 manifestos), não o exemplo documentado.

## 2. Plano de implementação (ordem sugerida)

| # | Item | Arquivos | Teste/aceite |
|---|---|---|---|
| P0-1 | D-01 B23: `origem`×`referencia_estilo` mutuamente exclusivos | `src/forge3d/spec.py` | novo caso em `tests/test_spec_v6_g11.py` |
| P0-2 | D-02 autorig honra esqueleto explícito (humanoide em `tipo: criatura`) + regra de compatibilidade esqueleto×tipo | `blender/autorig.py` (+ regra B24 em `spec.py`) | dispatch com mock + run Blender no `verificar` |
| P0-3 | D-03 manifesto com esqueleto real; run falha se pedido ≠ real | `blender/postprocess.py`, `src/forge3d/publish.py`, `src/forge3d/pipeline.py` | `verify` verde em `mob_rig_v1`; teste de contrato |
| P0-4 | D-04 sockets: erro se ausente no esqueleto final | `blender/postprocess.py` / `src/forge3d/qc.py` | teste |
| P0-5 | D-05 concept: normalizar PNG real + dims reais no meta/manifesto | `src/forge3d/providers/concept.py` (+ `publish.py`) | teste com JPEG mockado |
| P0-6 | D-09 drift de doc do repo | `mesh.py`, `docs/rotas-e-providers.md` | conformidade + P0 verdes |
| P0-7 | Teste de contrato do fluxo concept↔mesh sem GPU (D82): `stylized_pbr`→`mesh`; mesh sem `origem` chama concept; com `origem` não chama | `tests/` | teste novo |
| P1-1 | D-06 proveniência do `prompt_final` (sidecar + hash) | `concept.py`, `publish.py` | teste |
| P1-2 | D-08 retry de seed no G2 por orientação (opt-in) | `pipeline.py`/`spec.py` | teste + medição |
| P1-3 | D-07 decisão template×concept (doc e/ou `projetar_foto_2d`) | `mesh.py`, `docs/` | decisão do operador |
| P1-4 | Style sheet por jogo (`referencia_estilo`) + **A/B TRELLIS.2 via fal.run × TripoSR** por classe | spec/exemplo + `tools/` | medição de QC/QA visual |
| P1-5 | Usar Pixal3D MIT (endpoint/Colab) onde fidelidade > TripoSR | provider embrulhado | A/B medido |
| P2-1 | LoRA TRELLIS.2 só se A/B mostrar falha consistente (Vault CC0 + Blender) | `tools/colab_trellis_lora.py` | medição |
| P2-2 | GameOne: passe de paleta/iluminação do jogo (não é pipeline) | GameOne (fora) | screenshots |
| P2-3 | Medir custo real por asset na operação (roadmap) | — | planilha de tempos/custos |

**Bump obrigatório (D6)**: P0-2/P0-3 mudam rig/saída → `PIPELINE_VERSION` **0.9.3**; D-05 muda bytes
de textura → entra no bump. Registrar cada item no ledger (D114+).

## 3. Decisões do operador (antes de executar)

1. **Rota de produção por classe** (à luz dos demos de hoje):
   - herói jogável riggado → `import` (autoral) **ou** `mesh`+template+rig? (v4 provou que o i23d
     puro entrega o visual dracônico, mas sem rig/editabilidade);
   - mob bípede → `mesh` + `godot-humanoid-aa@1` (após D-02);
   - criatura quadrupede/montaria → `mesh` + `quadruped@1`/`winged_mount@1`.
2. **Referência vs prompt**: aceitar que `referencia_estilo` **vence o prompt** (efeito de âncora) e
   documentar; para "visual novo" usar prompt sem referência (v4) ou referência que já seja o alvo.
3. **Template humanoide**: manter como corpo/layers (documentar) ou evoluir para paleta do concept.
4. **IP**: D4 como **conceito textual** apenas; nenhum asset de imagem de terceiro como input em
   asset de produção (I14/§5 de `riscos-e-licencas.md`).

## 4. Inventário de evidências (esta janela)

- `docs/preview/d113_demo/`: `kaelen_antes_*` (jogo), `kaelen_depois_*` (com referência),
  `kaelen_zero_*` (template do zero), `kaelen_v4_i23d_*` (**cavaleiro dracônico** por prompt),
  `mob_concept/` (concept Nano Banana + `concept_resultado.json`), `mob_referencia.png` (D4-style
  lineup do GameOne recortado), `mob_v2_*` (mob final 1 material), specs `lote_*.yaml`.
- Destinos sandbox: `~/.local/state/forge3d/saida/{kaelen_v092, kaelen_zero, mob_prompt_v2,
  mob_rig_v1}` — `mob_rig_v1` é o caso de teste do D-02/D-03 (verify reprovado de propósito).
- Medidos: Kaelen v1 15.872 tris/8 mat/56 ossos/12 clipes; v2 15.858/7; v3 15.872/8; v4 15.914/1;
  mob v2 15.920/1; Godot 4.7.2 `GODOT_ANIM_OK` (idle 2,042 s/12 tracks; walk 20 tracks); verify
  `mob_rig_v1` exit 3 (G6, 49 ossos faltando).
- Pesquisa (não implementar sem decisão): Tripo3D/Tripo API (~$0,30–0,80/asset, termos pagos
  limpos); TRELLIS.2 MIT ($0,25–0,35 via fal.run); LoRA TRELLIS.2 (~$20–70, 50–200 malhas);
  style LoRA SDXL (US$1,5–5). Nada disso entra como conector novo (decisão do operador).

## 5. Como retomar

```bash
cd /home/eudespatricio/3DCreation && . .venv/bin/activate
python -m pytest                      # 523 verdes + 1 GPU (skip) em 524
python tools/conformidade.py && python tools/check-p0.py && bash tools/check-contexto.sh
# caso de teste intencional (deve ficar vermelho até P0-2/P0-3):
forge3d verify ~/.local/state/forge3d/saida/mob_rig_v1; echo "exit=$?"   # hoje: 3
# depois do fix, rerodar o lote rigado e exigir verify verde:
forge3d run docs/preview/d113_demo/lote_mob_rig.yaml --json
```
