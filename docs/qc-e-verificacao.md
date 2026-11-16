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
| **G1** | Geometria sã | arestas não-manifold (ou `arestas_t == 0` quando `alpha_cards: true`), faces degeneradas, normais invertidas por componente e anti-facetamento orgânico (`malha_organica_facetada`) | `bpy` + volume assinado + inspeção de normais por vértice em Python puro | `0` não-manifold, `0` degenerada, normais suaves em orgânicos `@5`+ | erro |
| **G2** | Escala, pivô e eixos | altura da AABB vs `altura_metros`; pivô vs regra; frente `-Z` (humanoide e focinho de criatura), roll simétrico de braços e `sockets` válidos | leitura do `.glb` (sem Blender) | `≤ 0,5 %`, `≤ 1 mm`, roll simétrico e frente `-Z` | erro |
| **G3** | UV | `TEXCOORD_0` presente, UV em `[0,1]` (salvo `permitir_tiling`) e área UV 2D não colapsada (`uv_colapsada`) | parse do `.glb` + buffer binário | cobertura `100 %`, área UV > 0 | erro |
| **G4** | Textura | dimensão POT, `≤ textura_max`, integridade PNG (`CRC32`/`IHDR`/`IEND`), JPEG e WEBP | header/chunks + `PIL.Image` | `≤ 1024..4096` (perfil), POT obrigatório | erro |
| **G5** | Material | nº de materiais, texturas existentes, sem caminho absoluto, `exigir_tangent_normal` (`@4`+) e sombreamento suave em orgânicos | parse do `.glb` + `fsck` de arquivo | `≤ 8` Godot / `1` `roblox-aa-80` | erro |
| **G6** | Rig | nº de ossos, nomes contra mapa do perfil (`godot-humanoid@1` 23, `godot-humanoid-aa@1` 56, `r15@1` 16, `quadruped@1` 23, `winged_mount@1` 31), root na origem, sem escala e `JOINTS_0`/`WEIGHTS_0` válidos | parse de `skins`/`nodes`/primitivos | `≤ 64` (Godot) / `≤ 24` (R15) | erro |
| **G7** | Colisão | presença, nº de partes, prefixo `UCX_`, convexidade 1 mm/m e detecção coplanar/degenerada | parse de nodes + análise geométrica | `≤ 15` partes | erro |
| **G8** | Licença | modelo na allowlist, `uso_comercial: true`, `NOTICE` presente | manifesto + allowlist | obrigatório | erro |
| **G9** | Orçamento | triângulos vs `limite_triangulos` (`qualidade: hero`/`ultra` elevados), bytes por arquivo e silhueta IoU 128×128 entre LODs | parse do `.glb` + render 2D Pillow | tri `≤` orçamento · bytes `≤` perfil | erro |
| **G10** | Animação | clipes pedidos (`animacoes_base`/`clipes`) existem, duração > 0,2 s, ≥ 2 ossos em movimento em marchas e fechamento C0 de loop cíclico (`loop_quebrado`) | parse de `animations` do `.glb` | clipe presente · loop fechado (< 0,08 rad / < 0,03 m) | erro |
| **G11** | Orçamento de cena (`spec@6`) | soma ponderada por `quantidade_cena` de triângulos visíveis, draw calls (com hardware instancing quando `materiais == 1` sem rig) e VRAM única de texturas antes do `publish` (`FORGE-E-QC-SCENE`); estimável antes de gerar via `forge3d plan <lote> --scene-budget` | agregação em staging pós-QC por item | `≤ 400k` tris · `≤ 400` draw calls · `≤ 200 MB` VRAM (default 80 % AA) | erro |

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
  "codigo": "FORGE-E-QC"
}
```

`status` ∈ `ok` · `warn` · `falhou`. Um único `falhou` ⇒ `aprovado: false` ⇒ `exit 3`.

**LOD não é bloqueador fora do critério de silhueta** (D71/D92): no QC V2 o **G9** compara a silhueta
ortográfica 128×128 (Pillow) dos LODs quando declarados; e o script `tools/lod_qualidade.py` mede IoU
(frente e lado), pior faixa vertical (8) e delta de bbox contra o LOD0 — critério padrão IoU ≥ 0,85,
faixa ≥ 0,75 e bbox ≤ 2% (adaptado para `0,78` / `0,65` quando o LOD0 tem `< 200` tris). Roda na máquina
do operador depois do `run`; `verify` preserva `exigir_tangent_normal` em `manifest@4`+ e anti-facetamento
orgânico / sockets em `manifest@5`, mantendo todos os destinos legados `@1`–`@4` verdes. Para QA de
importação real no Godot 4 headless, [`../tools/godot_visual_qa.gd`](../tools/godot_visual_qa.gd) valida
instanciação, ausência de faces facetadas em malhas orgânicas, materiais PBR, `Skeleton3D`, `Socket_*`
e `AnimationPlayer` (`GODOT_VISUAL_QA_OK`).

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
