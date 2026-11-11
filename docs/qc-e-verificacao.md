# QC e verificação

> O QC mede o **arquivo exportado**, não a intenção do prompt. É o único lugar do pipeline onde
> "parece bom" não vale: ou o número está dentro do limite do perfil, ou não publica.

## 1. Princípio

Geração pode falhar de forma invisível (mesh linda, escala 3× errada). Por isso a verificação acontece
**depois** do export, sobre o `.glb` final, e usa as tolerâncias **do perfil** — nunca número solto no
código.

Duas consequências:

1. **QC não corrige.** Ele reprova. Corrigir é papel do pós-processo; se o pós-processo não dá conta, o
   problema é do pipeline, não do gate.
2. **QC não tem bypass** (D9). A saída legítima para "quero mesmo assim" é corrigir o perfil do jogo —
   que é versionado e revisado —, não passar uma flag.

## 2. Gates

| # | Gate | Mede | Como | Padrão de limite | Sev. |
|---|---|---|---|---|---|
| **G1** | Geometria sã | arestas não-manifold, faces degeneradas, normais invertidas, buracos | `bpy`: `bmesh` + checagem de normais | `0` não-manifold, `0` degenerada | erro |
| **G2** | Escala e pivô | altura da AABB (÷ `escala_saida`) vs `altura_metros`; posição do pivô vs regra | leitura do `.glb` (accessor min/max), sem Blender | `≤ 0,5 %` e `≤ 1 mm` | erro |
| **G3** | UV | `TEXCOORD_0` presente em todo primitivo; UV em `[0,1]` no modo atlas | parse do `.glb` | cobertura `100 %` | erro |
| **G4** | Textura | dimensão POT, `≤ textura_max`, sem upscale, canais corretos | header PNG | `≤ 1024`, POT obrigatório | erro |
| **G5** | Material | nº de materiais, todos com textura existente, sem caminho absoluto | parse do `.glb` + `fsck` de arquivo | `≤ 8` por asset | erro |
| **G6** | Rig | nº de ossos, nomes contra o mapa do perfil, root na origem, sem escala em osso | parse de `skins`/`nodes` | `≤ 64` (Godot) / `≤ 24` (R15) | erro |
| **G7** | Colisão | presença, nº de partes, prefixo `UCX_`, convexidade, dentro da AABB visual | parse de nodes + `bpy` para convexidade | `≤ 15` partes | erro |
| **G8** | Licença | modelo na allowlist, `uso_comercial: true`, `NOTICE` presente | manifesto + allowlist | obrigatório | erro |
| **G9** | Orçamento | triângulos vs `limite_triangulos`, bytes por arquivo, nº de primitivos | parse do `.glb` | tri `≤` orçamento · `≤ 2048 KB` | erro |

**G1 mede topologia soldada.** O glTF divide vértice em cada costura de UV; sem soldar, todo asset
importado pareceria ter borda aberta. Efeito colateral: duas peças que compartilham **canto exato**
viram uma aresta de 4 faces depois da solda e o G1 reprova — foi o que aconteceu com pelve/coxa.
É por isso que a geometria blocky **sobrepõe** peças em vez de encostá-las (`MAPA.md` armadilha 10).

**G2 mede em metros, contra um arquivo que pode estar em studs.** Desde o D62 o `glb` do perfil
`roblox-r15` sai em studs (`escala_saida: 3,5714`); o G2 divide a AABB do arquivo pela escala
declarada antes de comparar com `altura_metros` e divide o desvio do pivô pela mesma escala. Grava
`altura_export` e `escala_saida` no `medido`, e `bbox_m` do relatório continua em metros.

**G7 mede convexidade com tolerância de escala** (D65): **1 mm por metro de diâmetro** da parte.
Um hull de malha gerada tem regiões quase coplanares e o triangulador deixa desvios de
sub-milímetro (medido: 4,3e-4 m num colisor de 2,2 m); concavidade de verdade — a do C8, com face
atravessando o corpo — desvia em ordem de centímetro e continua reprovando.

**Avisos** (`FORGE-W-QC`, publica com registro): LOD além de `_LOD2`; textura menor que 32 px;
material sem uso; tolerância marcada `[verificar]` no perfil (U1–U5).

## 3. Relatório

Vai para `.forge/staging/<id>/relatorio_qc.json` e é embutido no manifesto:

```json
{
  "aprovado": false,
  "gates": [
    {"id": "G1", "status": "ok",    "medido": {"nao_manifold": 0, "degeneradas": 0}},
    {"id": "G2", "status": "falhou", "medido": {"altura_m": 3.42, "esperado_m": 1.10, "delta_pct": 210.9}},
    {"id": "G9", "status": "ok",    "medido": {"triangulos": 780, "limite": 800}}
  ],
  "codigo": "FORGE-E-SCALE"
}
```

`status` ∈ `ok` · `warn` · `falhou`. Um único `falhou` ⇒ `aprovado: false` ⇒ `exit 3`.

## 4. Verificação em CI (`forge3d verify`)

Roda sobre o que **já está publicado**, sem gerar nada. É o portão de pull request:

1. manifesto existe, valida no schema e está íntegro;
2. `sha256` de cada arquivo confere;
3. todos os gates re-rodam contra o perfil atual: **G1** por topologia em Python puro (solda por
   posição, sem Blender); **G2** lê a regra de pivô gravada no G2 antigo (`pivo_regra`) e mede o
   GLB com a escala **declarada no manifesto** (`unidades_export.escala_saida`; `@1` = 1.0);
   **G3–G9** releem o GLB/PNG do destino;
4. o índice e o disco concordam (nenhum arquivo órfão, nenhum registro fantasma).

Divergiu ⇒ `exit 3` e a lista exata do que divergiu. Isso pega o caso mais comum em jogo — alguém
editou o `.glb` na mão e o manifesto ficou mentindo — e também o perfil que mudou de tolerância
depois da publicação. Manifesto antigo sem `pivo_regra` não tem como revalidar o pivô: o gate é
pulado e isso é **GAP-037**.

## 5. Quando o QC reprova duas vezes

Regra: **duas reprovações seguidas no mesmo `id` abrem um `GAP`** ([`gaps.md`](gaps.md)) e o item sai
do lote. Não se ajusta o limite para passar, nem se tenta em loop. Repetir a mesma tentativa com o
mesmo provider produz o mesmo defeito — e cada volta custa minutos de GPU.
