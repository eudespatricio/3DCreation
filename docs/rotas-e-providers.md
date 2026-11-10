# Rotas e providers

> A rota é **técnica** (como o asset nasce). A estética é dado (`estilo_global`). Engine é perfil.
> Nenhuma dessas três coisas se mistura no código (D4, D8).

## 1. Roteamento é determinístico

Regra em código, sem LLM (D13). `rota` explícita no item vence sempre.

| `estilo_global` | `tipo` | Rota padrão |
|---|---|---|
| `blocky_voxel` | qualquer | `blocky` |
| `lowpoly_lit` | `personagem_humanoide`, `criatura`, `prop_equipavel` | `mesh` |
| `lowpoly_lit` | `prop_estatico`, `modulo_cenario`, `mapa_setor` | `modular` |
| `stylized_pbr` | qualquer | `mesh` |
| — | `item com origem declarada` | `import` |

Rota inexistente para a combinação ⇒ erro `FORGE-E-SPEC` com a lista de rotas válidas. Nunca "escolhe
a que der".

## 2. Rota `blocky` — voxel/blocky determinística (P1, sem GPU)

**Entrada:** `prompt` + `paleta` + `altura_metros` + `tipo` + `limite_triangulos`.

**Processo:**

```
spec ──► 1. ESQUELETO LÓGICO   hierarquia de membros por tipo (não é rig: é estrutura)
      ──► 2. CAIXAS            cada membro = N caixas [x0,y0,z0, x1,y1,z1] em unidades de voxel
      ──► 3. UV POR FACE      cada face recebe uma região do atlas (reuso máximo → menos draw call)
      ──► 4. ATLAS            paleta travada, 16×16/32×32, nearest, Pillow, determinístico
      ──► 5. GEOMETRIA bpy    constrói malha + material + bones por script, sem Blockbench
      ──► 6. PÓS-PROCESSO     passo 4 do fluxo (normaliza, LOD por fusão de faces, colisão)
      ──► 7. QC + PUBLISH
```

**Decisão de arquitetura importante:** **não depender do Blockbench.** O `.bbmodel` é um artefato de
*autoria humana* (para o artista abrir e ajustar), não a fonte da verdade da pipeline. Ele exige
Electron/Node, não tem CLI estável de export e adiciona um runtime inteiro por um export que o
`bpy` faz em 100 linhas. A pipeline gera a geometria direto no Blender a partir do mesmo JSON de
caixas; o `.bbmodel` sai como **export opcional** (`--emitir-bbmodel`) para revisão humana.

**Onde o LLM entra (e onde não entra):** o LLM pode propor a *hierarquia de membros e a paleta* a partir
do `prompt` no modo `forge3d draft`. Ele **não** escreve coordenada: caixa é geometria, e geometria
ruim é detectável mas cara. Coordenada vem de template por `tipo` + parâmetros numéricos.

**Determinismo:** D1. Mesma entrada ⇒ mesmo `sha256`, inclusive do atlas. Ordem de dicionário, ordem
de face e arredondamento de vértice são fixados (sem `set` iterado, sem float livre).

**Limites honestos:** voxel parece simples e não é — silhueta legível depende de escala de voxel por
tipo (4–8 voxels de altura para item pequeno, 16–24 para personagem). Isso é tabela no perfil, não
criatividade do modelo.

**Quando não usar:** orgânico, tecido, detalhe fino, normal map com relevo, personagem realista.

## 3. Rota `import` — asset manual entra no mesmo trilho (P1)

Quem modela à mão no Blockbench/Blender **não pode** ficar fora do QC, porque é justamente o asset
mais importante do jogo. A rota `import` aceita `.blend`, `.bbmodel`, `.glb`, `.obj` e aplica
exatamente o passo 4 em diante.

**Efeito:** asset manual ganha escala, pivô, LOD, colisão, manifesto e entrada no índice sem código
novo. É a rota com melhor custo-benefício do projeto e não existia no desenho original.

**Determinismo:** D1 se a entrada for estável (o `sha256` do arquivo de origem entra na chave).

## 4. Rota `mesh` — 3D generativo local (P3, GPU)

**Entrada:** `prompt` + `seed` + `altura_metros` + orçamento de triângulos.

```
prompt ──► concept (text-to-image) ──► image-to-3D ──► remesh/decimate ──► UV + bake ──► pós-processo
```

**Stack recomendada para 6 GB** (números e licenças em [`riscos-e-licencas.md`](riscos-e-licencas.md)):

| Etapa | 1ª escolha | Alternativa | Motivo |
|---|---|---|---|
| concept | `Z-Image-Turbo` Q4 via `sd.cpp` (Apache-2.0) | SD 1.5 (OpenRAIL-M) | roda em 4 GB, 8 passos, sem Python |
| image→3D | **SF3D** (6 GB, UV + material nativos) | **TripoSR** (MIT, topologia pior) | único que entrega UV nessa faixa |
| limpeza | remesh + decimate no `bpy` | Instant Meshes via subprocess | controlável e local |

**Não entra:** TRELLIS.2 (16–24 GB), Hunyuan3D-2.1 (10–29 GB e cláusula territorial), InstantMesh
(~15 GiB), Pixal3D (não-comercial). Ver D18.

**Determinismo:** D2. Seed fixa + versões pinadas tornam o resultado *estável na forma*, não idêntico.
`plan` registra a seed resolvida; manifesto guarda provider, versão e seed.

**Limites honestos:** obrigatoriamente o asset passa por LOD/retopo e por QC visual humano na primeira
vez. Mesh gerada tem topologia irregular e UV que não sobrevive a edição — não é asset de herói.

**Bloqueio:** sem provider instalado ou sem VRAM, o item sai `bloqueado` com `FORGE-E-RECURSO` ou
`FORGE-E-PROVIDER` — **nunca** `falhou`, porque não é bug (D11).

### Estado do slot (10/11/2026)

O provider `mesh` **existe como slot registrado**, sem inferência: ele declara determinismo `D2`,
custo (35 s, 5.500 MiB, 250 MB), capacidades e **preflight com diagnóstico nomeado**. Efeito:

```
$ forge3d doctor
  providers  blocky: pronto · import: pronto · mesh: P3: torch ausente — instale o extra GPU …
$ forge3d run lote_com_mesh.yaml
  [bloqueado] weapon.axe.ice.01  P3: torch ausente — instale o extra GPU (docs/dependencias.md §4)
```

Ordem de construção recomendada, de propósito: **image-to-3D primeiro** (entra imagem, sai malha —
testável com um PNG fixo, sem a variável do diffusion) e **text-to-image depois** (só precisa
produzir um PNG). Nesta ordem, qualquer erro tem uma causa só.

Entregas de P3: (1) provider `concept` (text-to-image → PNG); (2) provider de image-to-3D
(PNG → malha + textura); (3) encadeamento e proveniência das duas etapas no manifesto; (4) lock
de GPU exercitado de verdade e `doctor` medindo VRAM livre.

**Primeiro teste real (10/11/2026, TripoSR em 6 GB)** — três requisitos que só apareceram rodando:

1. **Normalizar orientação**: a saída vem com a altura no eixo Y (2 de 2 inputs).
   `tools/normalize_mesh.py` leva para Z-up com base em 0 e centro em X/Y.
2. **UV + textura**: sem `--bake-texture` a malha sai só com cor por vértice e o QC G3/G5 reprova
   — comportamento correto. Bake precisa de `moderngl` com contexto EGL (sem CUDA toolkit).
3. **O input manda na qualidade**: foto com capa gerou casca oca (pernas fundidas); render flat do
   nosso android gerou laje extrudada. T-pose e sombreamento não são preferência — são condição
   de o modelo inferir volume (GAP-029).

## 5. Rota `modular` — mapa por montagem (P4)

Não é "gerar um mapa com IA". É **layout → WFC → instância → fusão**, exatamente como o desenho
original intuía e como a indústria faz:

1. **Grafo de layout** (salas, corredores, portas, spawns) — gerado por regra/seed, não por malha.
2. **WFC** encaixa módulos de um catálogo aprovado (biblioteca de peças, com sockets declarados).
3. **Montagem no Blender**: instância por célula, *join* por setor (para reduzir draw call).
4. **Colisão**: `UCX_` por peça, não por setor inteiro (colisor de mapa inteiro é inútil).
5. **Export por setor** + occlusion/portal hints no manifesto.

**Determinismo:** D1 com `seed`. **Pré-requisito:** catálogo de módulos aprovado no padrão do perfil.
Sem catálogo, não há WFC — e é por isso que fica em P4.

## 6. Interface de provider

Contrato único; é a **única** superfície de extensão que pode trazer dependência pesada.

```
GeometryProvider
├── nome: str
├── versao: str
├── determinism: "D1" | "D2" | "D3"
├── licenca: {modelo, uso_comercial, notice}
├── capabilities() -> {blocky, organic, riggable, pbr, mapa}
├── custo(spec) -> {segundos_estimados, vram_mb, disco_mb}     # usado no plan
├── preflight() -> {disponivel: bool, razao: str}              # usado no doctor
└── gerar(spec, staging) -> RawAsset                           # escreve SÓ em staging
```

Regras:

- provider **nunca** exporta para o destino, **nunca** aprova QC, **nunca** publica;
- provider **nunca** lê o lote inteiro: recebe um item resolvido;
- provider cujo custo passa de `politica.custo_max_min` é marcado `bloqueado` no `plan`, não no `run`;
- provider `D3` exige aprovação humana explícita (`--aprovar-d3`) para publicar.

Registro em `providers/__init__.py` com allowlist de licença (D18). Modelo fora da allowlist não é
instanciado, mesmo que instalado.

## 7. Adicionar um provider novo — checklist

1. Declarar `determinism`, `licenca` e `custo` — se não souber o custo, não está pronto.
2. Entrada só por `spec` resolvida; saída só em `staging/<asset_id>/bruto/`.
3. `preflight()` obrigatório, com razão legível (vira mensagem no `doctor`).
4. Rodar sob o lock de GPU se tocar VRAM (I6).
5. Fixture pequena em `tests/fixtures/` + um caso de falha esperada.
6. Atualizar a tabela de licenças em `docs/riscos-e-licencas.md`.
7. Não alterar contrato: se o provider precisa de campo novo, é `spec@2`.
