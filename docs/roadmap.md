# Roadmap

> Cada fase tem **portão de saída falsificável**. Sem portão verde, a fase seguinte não começa —
> o custo de construir sobre uma base não verificada é maior que o de atrasar uma semana.

## Visão

| Fase | Objetivo | Precisa de GPU? | Portão de saída |
|---|---|---|---|
| **P0** | Escopo, arquitetura e contratos | não | este repositório de documentos + schemas válidos |
| **P0.5** ✔ | Q2/Q6 fechadas e portão de contexto | não | **concluída em 10/11/2026** (D23, D24, `check-contexto.sh`) |
| **P1** ✔ | Rotas `blocky` + `import` de ponta a ponta | não | **concluída em 10/11/2026**: 2 runs byte-idênticos, rerun = 0 trabalho, QC G1–G9 verde |
| **P2** | Perfil `roblox-r15` | não | um rig R15 importa no Studio com `Humanoid` e anima |
| **P3** | Rota `mesh` com stack local | **sim** | 10 assets com QC aprovado, tempo e VRAM medidos e registrados |
| **P4** | Rota `modular` (WFC) | não | uma dungeon de 10 setores com colisão por setor e seed fixa |
| **P5** | LOD de mesh, retarget, animação | sim | animação base tocando nos dois perfis |
| **P6** | Índice, `gc`, CI e distribuição | não | `forge3d` instalável e `verify` rodando em CI de pull request |

## P0 — Contratos (concluída em 10/11/2026)

**Entrega:** `README`, `AGENTS`, `MAPA`, `CONSELHOS`, `DECISOES`, `INVARIANTES`, `CONTINUAR`, `docs/*`,
`schemas/*`, `profiles/*`, `examples/*`, skill `context-recovery` adaptada.

**Portão:** todo schema é JSON válido e o lote de exemplo valida contra `spec@1`; nenhuma contradição
interna entre documentos (nomes de campo, exit codes, IDs de invariante).

**Não faz:** código, instalação de modelo, dependência pesada.

## P0.5 — Destravar — ✔ concluída

**Entrega:** Q2 (allowlist de destino) e Q6 (onde mora `.forge/`) decididas e escritas em `DECISOES.md`;
`tools/check-contexto.sh` aplicando os tetos; `scan_repo.py` portado para o lens Python/Blender.

**Portão:** `bash tools/check-contexto.sh` sai `0`; nenhum `Q` aberto que bloqueie P1.

## P1 — Rota `blocky` e `import` (o coração) — ✔ concluída

Escopo mínimo que prova o desenho inteiro **sem GPU**:

1. `spec/` com schema, normalização e regras B1–B10;
2. `plan/` com chave de cache e estimativa;
3. provider `blocky` (caixas + atlas Pillow) e provider `import`;
4. `blender/postprocess.py` + `export.py` (4.2, JSON como canal);
5. `qc/` com G1–G9 exceto os que dependem de GPU;
6. `publish/` atômico + manifesto + índice SQLite + ledger;
7. CLI com os seis subcomandos e exit codes;
8. `tests/invariants/` cobrindo I1–I5, I8–I14.

**Medido em 10/11/2026:** 3 itens em 2.082 ms (cache frio) e 476 ms (cache quente, trabalho 0);
sha256 idênticos em 12 artefatos entre dois runs; `verify` detecta arquivo adulterado (exit 3);
rota `import` reprocessa um GLB pronto em 0,55 m com QC aprovado. **Falta** o teste de import no
Godot (GAP-011) — o portão desceu de "entra no jogo" para "QC + manifesto", e está registrado.

**Portão (todos):**
- `forge3d run examples/lote_01.yaml` duas vezes ⇒ **hashes idênticos** (I1);
- segunda execução ⇒ `trabalho_executado: 0` (I11);
- os 3 assets do exemplo entram no GameZero **sem ajuste manual** de escala, pivô ou material;
- `verify` pega um `.glb` alterado à mão ⇒ `exit 3`;
- spec com erro ⇒ `exit 2` sem tocar em provider.

**Não faz:** GPU, LOD de mesh, animação, mapa.

## P2 — Roblox

**Entrega:** `profiles/roblox-r15.yaml` completo, rig `r15@1`, conversão de escala, colisão por parte,
e o teste real no Studio que fecha U1–U4.

**Estado em 10/11/2026 — parcial:** o blocky remapeia para as **16 partes R15** (`HumanoidRootPart`…
`RightFoot`), publica 300 tris com G1–G9 e `verify`, e o GLB/Godot mostra 16 ossos (`R15_OK`). No
Studio, **`R15_STUDIO_PASS motores=15 partes=16`** valida o pivô por membro; o objeto usa `pivot:
base` e os bone heads ficam nos joints (D47). O **`forge3d export-r15`** gera um `.rbxlx` nativo
(16 Parts + 15 Motor6D, `R15_RBXLX_PASS`) sem upload. O `upload-model` sobe o `.glb` como `Model`
via Open Cloud (free); o upload real foi aprovado (asset 136741921517312) e o Studio carrega **1
MeshPart com 16 Bones R15**. Faltam textura (TextureID sem conteúdo), pivôs nos Bones, escala/stud
e U1–U4.

**Portão:** modelo importado no Studio com `Humanoid`, membros girando no pivô certo, textura correta,
e o documento `perfis-export.md` sem nenhum `[verificar]` pendente nesse perfil.

## P3 — Rota `mesh`

**Entrega:** provider `mesh` com image-to-3D local, bake UV/textura próprio, lock de GPU, provenance
D2, `doctor` medindo a venv certa, allowlist de licença aplicada e `verify` reexecutando os gates.

**Estado em 10/11/2026 — fechada para prop:**

- `prop.bule.exemplo.01`: PNG → TripoSR → 7.960 tris → UV+bake 512² → **G1–G9 verdes**;
- Godot 4.3 importou com AABB idêntico ao manifesto e `albedo_tex=true`, sem ajuste manual;
- `run` 23,3 s frio / 2,1 s cache hit; VRAM pico 2.378 MiB;
- kit corpo/capa/arma (blocky, `spec@2`) publicado e montado no Godot;
- 50 verdes + 1 GPU (manual); `doctor` diz `mesh: pronto`.

**Residual (P3.5):** A/B de 10 assets (Q8; 3 personagens feitos), convexidade do colisor no
`verify` (GAP-038), R15/Studio (P2). Concept, capa e split fecharam.

**Portão:**
- 10 assets gerados com QC aprovado e **tempo/VRAM medidos nesta máquina** (entram em `DECISOES.md` §1);
- A/B SF3D × TripoSR registrado — SF3D encerrado em 6 GB (D27), A/B de qualidade ainda aberto;
- decisão de licença para jogo comercial escrita (Q5 resolvida por D27: TripoSR/MIT);
- falha de GPU ⇒ `bloqueado` com `exit 6`, nunca lote perdido.

**Não faz:** TRELLIS.2 em produção (X3 continua experimental), Hunyuan3D (licença).


## P3.5 — Concept local (SD1.5)

**Entrega:** estagio text-to-image local dentro do provider `mesh`, sem `origem` manual; PNG com
proveniencia (modelo, revisao, seed) no manifesto.

**Estado em 10/11/2026 — portao cumprido:** `personagem.sentinel.concept.01` publicado **sem
`origem`** em **37,2 s** (concept 5,5 s + i23d 16,9 s), **7.940 tris**, bbox
**1,000387×1,8×0,729638 m**, G1–G9 verdes, `providers.texture` (`concept/sd15`, revisao, seed) e Godot
4.3 com AABB idêntico. A orientação de humanoide ganhou o perfil de área (D37).

**Portao:** cumprido para o concept sem `origem`, o split (3 concepts) e o **A/B de 3 personagens**
híbridos (.02/.05/.04 + capa .03 + arma blocky, `AB_OK`). R15/Studio (P2), `gc` (feito) e primeiro
run do CI (GAP-008) seguem.


## P4 — Rota `modular`

**Entrega:** catálogo de módulos com sockets, gerador de grafo de layout, WFC com seed, montagem e
*join* por setor no Blender, colisão `UCX_` por peça, export por setor.

**Portão:** dungeon de 10 setores reproduzível por seed, com colisão funcional e sem infinito de
draw calls por setor.

## P5 — Polimento

LOD para mesh gerada (com critério visual, não decimate cego), retarget entre `godot-humanoid@1` e
`r15@1`, animação base opcional. Fecha D14 e o GAP de animação.

## P6 — Produto

Índice consultável (`query`), `gc`, `migrate` de spec, CI de pull request com `verify`, distribuição
(`uv tool install`), e — só se houver consumidor não-Python — o adaptador HTTP. **Feito:**
`forge3d gc` (D45) e `tools/ci.sh` + workflow sem GPU/Blender (D46/GAP-008 configurado).

## Caminho crítico

```
P0 ──► P0.5 ──► P1 ──┬──► P2
                     └──► P3 ──► P5
                     └──► P4
```

P1 é obrigatório antes de qualquer outra coisa: é onde o desenho é provado sem GPU. Inverter isso
(começar pela geração) é reproduzir a lacuna L2–L4 do desenho original.
