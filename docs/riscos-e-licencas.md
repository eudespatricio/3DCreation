# Riscos e licenças

> **Nenhum número deste arquivo foi medido nesta máquina.** Todos vêm de README oficial, paper ou
> relato de terceiro, e estão rotulados. Medição própria só existe a partir de P3.
>
> Rótulos: `[oficial]` README/licença do projeto · `[terceiro]` issue/blog/usuário · `[estimado]`
> derivação declarada · `[não verificado]` não achei fonte.

## 1. Viabilidade em 6 GB — tabela de modelos

| Modelo | Licença | VRAM mín. relatada | Qualidade | PBR | Veredito 6 GB |
|---|---|---|---|---|---|
| **SF3D** (Stable Fast 3D) | Stability AI Community License | ~6 GB `[oficial]` | boa; **UV + delight nativos** | parcial | **cabe** — 1ª escolha |
| **TripoSR** | **MIT** | ~6 GB `[oficial]` | topologia irregular, cor por vértice | não | **cabe** — alternativa MIT |
| **Hunyuan3D-2mini / 2.0 shape-only** | Tencent (exclui UE/UK/Coreia) | <6 GB só via fork mmgp `[terceiro]`; textura oficial 16 GB `[oficial]` | boa geometria | não | cabe shape, **textura não** |
| **SPAR3D** (sucessor do SF3D) | Stability Community `[não verificado no arquivo]` | 10,5 GB; ~7 GB em low-VRAM `[oficial]` | melhor material | sim | **não cabe** |
| **TRELLIS.2** (4B) | **MIT** | ≥24 GB `[oficial]`; Q4 GGUF existe | melhor open de 2026 | sim (4 canais) | experimental — 8–15 min/asset `[estimado]` |
| **Hunyuan3D-2.1** | Tencent (mesma cláusula) | 10 GB shape · 21 GB textura `[oficial]` | estado da arte PBR | sim | **inviável** |
| **TRELLIS v1** | MIT | ≥16 GB `[oficial]` | boa | não | **inviável** |
| **InstantMesh** | Apache-2.0 | ~15 GiB numa alocação `[terceiro]` | zero123++ | não | **inviável** |
| **CraftsMan3D** | MIT | ~12–16 GB `[estimado]` | topologia regular | não | inviável |
| **Pixal3D** | **acadêmica / não comercial, proibida na UE** `[terceiro]` | ≥16 GB | fine-tune do TRELLIS.2 | sim | **inviável por VRAM e licença** |
| **SAM 3D Objects** | SAM License, gated | ≥32 GB `[oficial]` | objeto único | não | inviável |

## 2. Text-to-image (concept e atlas)

| Modelo | Licença | VRAM | Nota |
|---|---|---|---|
| **Z-Image-Turbo** (6B, 8 steps) | Apache-2.0 | ~16 GB em fp16; **Q3_K/offload roda em ≤4 GB** `[oficial, sd.cpp]` | melhor relação qualidade/VRAM em 2026 |
| SD 1.5 | OpenRAIL-M | ~4 GB | barato para atlas tileável |
| SDXL-Turbo/Lightning | OpenRAIL++-M | ~8 GB; 6 GB só com lowvram `[estimado]` | 1024², 4–8 steps |
| FLUX.1-schnell | Apache-2.0 | fp16 ~24 GB; GGUF Q4 ~7–8 GB | caro demais no alvo |

**Interface recomendada:** `stable-diffusion.cpp` (`sd-cli`) ou SDK do modelo, **não** ComfyUI (D22).
ComfyUI é a maior stack do ambiente para uma função coberta por binário leve — e tem nós oficiais de
SF3D/TRELLIS se um dia forem necessários (é o dissenso X2).

## 3. Licenças que bloqueiam publicação

| Modelo | Restrição | Impacto |
|---|---|---|
| **Hunyuan3D-2.x** | a licença Tencent **não se aplica na UE, Reino Unido e Coreia do Sul**; proíbe uso fora do "Territory"; exige licença acima de 1 M MAU | jogo vendido na Steam (UE) fica em zona de risco — **fora da allowlist** |
| **Pixal3D** | explicitamente acadêmica, **não comercial**, proibida na UE | fora da allowlist |
| **SAM 3D Objects** | gated, uso comercial restrito `[não verificado em detalhe]` | fora da allowlist |
| **SF3D / SPAR3D** | Stability Community License: comercial **até US$ 1 M** de receita anual, com **registro** e "Powered by Stability AI"; acima disso a licença **termina** | permitido **com obrigações** — `NOTICE` no manifesto (G8) |

## 4. Licenças sem fricção

`MIT`: **TripoSR**, **TRELLIS/TRELLIS.2**, **CraftsMan3D**.
`Apache-2.0`: **InstantMesh**, **Z-Image-Turbo**, **FLUX.1-schnell**.

**Nuance que quase sempre se perde:** quase toda licença isenta os *outputs* ("claims no rights in
Outputs"), mas a licença do **modelo** rege o **ato de gerar**. Gerar com Hunyuan3D na UE é o problema,
não apenas redistribuir o mesh. Por isso a licença é gate de pipeline (D18, I7), não nota de rodapé.

> Este documento não é parecer jurídico. Antes de publicar um jogo comercial, revise a licença vigente
> do modelo escolhido.

## 5. Risco de IP (estética vs marca)

| Risco | Mitigação |
|---|---|
| `minecraft_*` em tag, arquivo, perfil ou produto | `blocky_voxel` canônico; alias aceito só na entrada (D19, I14) |
| textura "inspirada" em asset de franquia | atlas gerado de paleta declarada, sem import de textura de terceiro |
| nome de item copiado de jogo conhecido | `id` e `tags` sem franquia; o `prompt` pode descrever estilo, não marca |

## 6. Riscos técnicos

| # | Risco | Prob. | Impacto | Mitigação |
|---|---|---|---|---|
| R1 | `CUDA OOM` intermitente com dois modelos | alta | alto | lock de GPU + serialização + `doctor` medindo VRAM livre (I6) |
| R2 | Diffusion não determinística ⇒ CI vermelho sem bug | alta | alto | D1/D2/D3 separados; CI só checa D1 (D7) |
| R3 | API do `bpy`/exportador muda com versão do Blender | média | alto | Blender pinado 4.2.x + `doctor` (I9) |
| R4 | Escala/rig do Roblox diferem do previsto | alta | médio | U1–U4 em `perfis-export.md`; QC só avisa até fechar |
| R5 | Blender crash no pós-processo mata o lote | média | médio | retry 1× + checkpoint por item + isolamento por subprocesso |
| R6 | I/O em `/mnt/c`/UNC degrada e quebra ferramenta | média | médio | recusa de caminho (I12) |
| R7 | Modelo com licença restritiva entra no repo | média | **alto** | allowlist de licença em `providers/` (I7, G8) |
| R8 | Cache cresce sem limite | média | baixo | orçamento 20 GB + `gc` (P6) |
| R9 | Ollama com 4.096 tokens efetivos trunca `draft` | alta | baixo | prompt curto e chunked; `draft` é opcional e fora do caminho crítico (D13) |
| R10 | Asset gerado com topologia que ninguém consegue editar | média | médio | rota `mesh` não é usada para asset de herói; `import` existe para isso |

## 7. Matriz risco → decisão

| Risco | Vira qual regra |
|---|---|
| R1 | D11, I6 |
| R2 | D7, §6 de `arquitetura.md` |
| R3 | D15, I9 |
| R4 | Q3, U1–U4 |
| R7 | D18, I7, G8 |
| R6 | I12 |
| R9 | D13 |

## 8. Fontes

- https://github.com/Stability-AI/stable-fast-3d — "about 6GB VRAM"
- https://github.com/Stability-AI/stable-point-aware-3d — 10,5 GB / ~7 GB low-VRAM
- https://github.com/VAST-AI-Research/TripoSR — ~6 GB, MIT
- https://github.com/Tencent-Hunyuan/Hunyuan3D-2 — 6 GB shape / 16 GB shape+texture
- https://github.com/Tencent-Hunyuan/Hunyuan3D-2/blob/main/LICENSE — exclusão UE/UK/Coreia
- https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1 — 10/21/29 GB
- https://github.com/microsoft/TRELLIS — "at least 16GB"
- https://github.com/microsoft/TRELLIS.2 — ≥24 GB, MIT, PBR
- https://huggingface.co/spaces/stabilityai/stable-fast-3d/raw/main/LICENSE.md — Community License, US$ 1 M
- https://github.com/leejet/stable-diffusion.cpp/blob/master/docs/z_image.md — Z-Image em 4 GB
- https://huggingface.co/Tongyi-MAI/Z-Image-Turbo — Apache-2.0, 6B, 8 NFEs
- https://github.com/TencentARC/InstantMesh — Apache-2.0, alocação de ~15 GiB
