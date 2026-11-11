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
do `prompt` no modo `draft` — **previsto, não implementado** (GAP-015; hoje o lote é escrito à mão).
Ele **não** escreve coordenada: caixa é geometria, e geometria ruim é detectável mas cara.
Coordenada vem de template por `tipo` + parâmetros numéricos.

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

### Estado real (10/11/2026)

O provider `mesh` **infere TripoSR** na venv única `~/.cache/forge3d/venv-i23d` (Python 3.12.14,
torch 2.4.1+cu121), chamada por subprocesso com `FORGE3D_VENV_I23D`; o núcleo não importa `torch`.
A entrada é `origem` (PNG) — o concept text-to-image é GAP-026; `prompt` é proveniência.

Fluxo medido com o bule:

- `doctor`: `mesh: pronto (TripoSR, torch 2.4.1+cu121, venv venv-i23d)`;
- TripoSR: 80.544 faces em 12,6 s (load 7,7 + forward 1,2 + extração 3,8), VRAM pico 2.378 MiB;
- pós-processo: decimate para 7.960 tris, reparo topológico, `smart_project`, bake `DIFFUSE/COLOR`
  512² (~2,8 s);
- `run`: 23,3 s frio / 2,1 s cache hit; G1–G9 verdes; Godot 4.3 importa com AABB idêntico ao manifesto
  e `albedo_tex=true`;
- `verify` reexecuta G1–G10 contra o perfil atual (C2/D32; G10 desde D67).

**Três requisitos que só apareceram rodando:**

1. **Normalização canônica** — a altura sai em eixos diferentes conforme o input; `canonicalizar` no
   pós-processo leva para Z-up, base em 0 e centro em X/Y.
2. **UV + bake próprios** — TripoSR só entrega `COLOR_0`; o bake no `bpy` (D28) resolve sem
   `moderngl`/EGL e sem CUDA toolkit.
3. **O input manda na qualidade** — fundo neutro/rembg e ausência de oclusão. O bule saiu reconhecível;
   a cadeira saiu blob; personagem com capa segue GAP-036. Pose controlada não resolve oclusão.

O lock de GPU (I6) é exercitado no `run`; o segundo job sai `FORGE-E-RECURSO` (exit 6). O `doctor`
mede VRAM livre e a venv de i23d, sem importar `torch` no núcleo (D29).


### Estagio concept (P3.5)

O provider `mesh` agora **gera a imagem de entrada** quando o item nao tem `origem`:
`prompt` + `seed` → SD 1.5 fp16 → PNG 512² → TripoSR. O concept e um **estagio interno** do mesh,
nao uma rota do lote; o contrato `spec@1` nao muda.

- venv: `~/.venvs/concept` (copia da i23d + `diffusers==0.31.0` / `transformers==4.44.2` /
  `accelerate==1.2.1`; torch 2.4.1+cu121), selecionada por `FORGE3D_VENV_CONCEPT`;
- modelo: `stable-diffusion-v1-5/stable-diffusion-v1-5` fp16, ~2 GB, **OpenRAIL-M**;
- medido em 10/11/2026: 512², 25 steps, geracao **5,5 s**, carga **2,0 s** (cache; a primeira inclui
  download), VRAM pico **2.675 MiB**, PNG 264.929 B; run completo **37,2 s**;
- proveniencia: `providers.texture` no manifesto (`concept/sd15`, versao+revisao, seed) e a licenca
  combinada em `licenca.notice`;
- fundo: o concept e RGB; o i23d roda com `--remover-fundo` automaticamente quando o concept foi
  gerado. `FORGE3D_I23D_REMOVER_FUNDO=1` continua valendo para `origem` externo.
- sentinela: `personagem.sentinel.concept.01`, **7.940 tris**, bbox **1,000387×1,8×0,729638 m**, G1–G9
  verdes e Godot 4.3 com AABB idêntico. A orientação de humanoide e corrigida pelo perfil de área
  (D37): `centro_area=5,55` < 48% → espelha Z antes do bake.

Exemplo: `examples/lote_05_mesh_concept.yaml` (`forge3d run` sem `origem`). O `plan` estima 40 s e o
`doctor` mostra `concept: pronto`.


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
