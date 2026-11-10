# Plano — concept com pose controlada (P3, etapa 1)

> Objetivo: produzir a **imagem de entrada** do image-to-3D de forma reproduzível, com pose travada,
> fundo neutro e sem oclusão. Este documento é o plano de instalação e teste no WSL do operador, e
> substitui a ideia de um pipeline paralelo em `~/tpose-pipeline/`.

## 1. O que já foi testado (evidência, 10/11/2026)

| Input | Pose | Resultado do TripoSR | Veredito |
|---|---|---|---|
| Foto promocional | A-pose, capa | casca oca, pernas fundidas pela capa | inutilizável |
| Render do nosso android | A-pose, flat | laje extrudada (silhueta sem volume) | inutilizável |
| **Concept T-pose (OpenPose)** | **T-pose, capa** | **capa virou uma chapa de 1 m; corpo virou lâmina** | **pior que os anteriores** |

Arquivos: `.scratch/tpose_canon_frente.png` (T-pose), `.scratch/android_up_*.png`, `.scratch/i23d_v3_*`.

**Conclusão que muda o plano:** pose controlada resolve **simetria e alinhamento**, não resolve
**oclusão e superfície fina**. A capa é o pior caso possível para um modelo de vista única: ela
esconde os braços e as pernas, e é uma superfície fina sem volume — o modelo funde tudo numa chapa.

### O que o T-pose entregou de bom

- Enquadramento e simetria corretos, 942×967 px de sujeito, razão W/H 0,974 (T-pose largo).
- `rembg` limpo e fundo neutro — a etapa de "concept limpo" funciona em qualquer dos inputs.
- O modelo **não** melhorou com a pose: extração de malha foi de 4,5 s para **23,1 s** (mais área
  de silhueta), sinal de que ele está triangulando superfície, não inferindo volume.

## 2. Requisitos de um concept que o image-to-3D aceita

Da evidência, nesta ordem de impacto:

1. **Sem oclusão**: braços e pernas separados do tronco e **sem capa** (capa é outro asset).
2. **Volume visível**: sombreamento com gradiente; cor chapada gera laje.
3. **Pose travada**: T-pose ou A-pose larga, simétrica, ortográfica.
4. **Fundo neutro**, sujeito ocupando 80–90 % da altura.
5. **Uma peça por vez**: corpo, capa, arma são `id` separados no lote.

> Recomendação central: **separar o asset**. `personagem.corpo`, `personagem.capa`, `personagem.capa_
> rigida`. Cada um vira um item do lote, entra no mesmo QC e é montado no Godot por socket. Isso
> aumenta o número de assets e reduz drasticamente a taxa de falha.

## 3. Arquitetura: provider, não pipeline paralelo

O concept é **mais um provider** dentro do Forge3D (`providers/concept.py`), não um projeto à parte.
Motivo (D24/D25): estado, cache, licença, proveniência e QC já existem; um diretório paralelo
duplicaria tudo e sairia do allowlist.

```
spec.lote[i].concept = {"modelo": "sd15-controlnet-openpose", "pose": "tpose", "seed": 123}
        │
        ▼
providers/concept.py ──► subprocesso no venv de GPU ──► PNG + pose_map.png
        │                                                (hash dos dois no manifesto)
        ▼
providers/mesh.py (i23d) ──► normalização canônica ──► UV/bake ──► QC ──► publish
```

Reaproveita o que já está instalado: `~/.cache/forge3d/venv-gpu` (torch 2.4.1+cu121, CUDA ok) e o
TripoSR vendorizado. O venv **não** é recriado — evita duplicar 2,5 GB de torch.

## 4. Stack local recomendada (6 GB VRAM)

| Componente | Escolha | VRAM | Licença | Nota |
|---|---|---|---|---|
| base | **SD 1.5** (fp16) | ~2,0 GB | CreativeML OpenRAIL-M | comercial permitido com restrições de uso |
| pose | **ControlNet OpenPose** (sd15) | ~1,4 GB | `[verificar]` no card do modelo | exige entrada em allowlist (D18) |
| pose map | **gerado por script** (COCO-18, desenhado em Pillow) | 0 | — | determinístico, sem `mmpose`/`controlnet_aux` |
| (opcional) estilo | IP-Adapter Plus (CLIP image) | ~1,0 GB | Apache-2.0 | **evitar IP-Adapter FaceID**: modelos InsightFace são não-comerciais |
| image-to-3D | TripoSR (já instalado) | ~3,5 GB | MIT | — |

Total de download novo: **~4,5 GB** (SD1.5 + ControlNet + opcional IP-Adapter). Disco livre hoje: 868 GB.

**Não usar**: FLUX (não cabe sem GGUF e offload), SDXL em fp16 (8 GB), e **qualquer API fechada** —
a v0 do projeto declara "nenhum modelo fechado por API" (D3/`DECISOES` §3), e um asset que depende de
serviço remoto quebra D2/D3 (determinismo e degradação).

### Por que não `~/tpose-pipeline/` + `~/.venvs/tpose-gen`

- Duplica torch (2,5 GB) e o estado de cache.
- Sai do allowlist de destino e da proveniência — o PNG nasceria fora do manifesto.
- Cria um segundo lugar para "onde está o modelo", que é exatamente o que `doctor` existe para evitar.
Se a intenção é isolamento, o caminho é `FORGE3D_VENV_CONCEPT` apontando para um venv próprio — sem
criar um projeto paralelo.

## 5. Fases e portões

| Fase | Entrega | Portão de saída |
|---|---|---|
| **C0** | `tools/pose_map.py`: desenha COCO-18 em T-pose (determinístico, sem dependência) | mesmo seed ⇒ mesmo PNG (hash) |
| **C1** | instalar SD1.5 + ControlNet no `venv-gpu`; script `tools/concept.py` | 1 PNG 1024² em ≤ 30 s e VRAM de pico ≤ 5,5 GB |
| **C2** | provider `concept` + campo na spec + proveniência | `forge3d plan` estima custo; manifesto traz modelo/seed/hash do pose map |
| **C3** | 10 concepts (5 corpos, 5 capas) → i23d | **≥ 7 de 10** com casca fechada e bbox plausível após normalização |
| **C4** | A/B: com e sem capa no mesmo corpo | capa separada melhora a taxa de aprovação em ≥ 30 p.p. |

## 6. Ordem de execução no WSL (o que rodar)

```bash
# 1. Pose map procedural (zero dependência)
python3 tools/pose_map.py --pose tpose --saida .scratch/pose_tpose.png

# 2. Instalar a stack de concept no venv ja existente (nao recriar torch)
uv pip install --python ~/.cache/forge3d/venv-gpu/bin/python \
  diffusers==0.31.* accelerate safetensors controlnet-aux

# 3. Baixar pesos (uma vez, ~4,5 GB)
#    runwayml/stable-diffusion-v1-5  +  lllyasviel/control_v11p_sd15_openpose

# 4. Gerar e testar
python tools/concept.py --prompt "..." --pose .scratch/pose_tpose.png --seed 20261110 \
  --saida .scratch/concept_01.png
forge3d run exemplos/lote_concept.yaml   # depois de C2
```

## 7. Riscos e respostas

| Risco | Resposta |
|---|---|
| SD1.5 não alcança fidelidade a um ator/personagem específico | **não é objetivo**: copiar likeness de ator é passivo jurídico. O alvo é personagem original |
| ControlNet OpenPose com licença ambígua | allowlist do provider exige licença declarada; `[verificar]` até leitura do card |
| Concept bonito, malha ruim | portão C3 mede o **i23d**, não a imagem. Imagem bonita não é o produto |
| 6 GB com SD1.5 + ControlNet + i23d | executar em sequência com descarregamento; nunca os dois residentes |
| Capa sempre funde | tratada como asset separado (requisito 1) |

## 8. O que este plano não resolve

- **Animação**: continua em P5 (GAP-020).
- **UV/textura do mesh gerado**: GAP-028 (bake exige `moderngl` + EGL).
- **Qualidade de herói**: o concept melhora a entrada, não transforma LRM de vista única em asset de
  protagonista. Para herói, o caminho continua sendo autoria + rota `import`.

## 9. Reconciliação com o plano do Antigravity (lido em 10/11/2026)

| Afirmação do outro plano | Verificação nesta máquina |
|---|---|
| `~/.venvs/triposr` existe com torch 2.5.1+cu121 e rembg | **confirmado** (Python 3.11.16, CUDA True, sem `pip`) |
| `~/3DCreation/.venv` é o núcleo leve | confirmado (sem torch) |
| Cache HF já tem VAE e TripoSR | confirmado: 2,0 GB, `stabilityai/TripoSR` e `stabilityai/sd-vae-ft-mse` |
| `inkscape` disponível | confirmado (`/usr/bin/inkscape`) |
| `generate_openpose.py` existe | confirmado no brain do Antigravity |
| SD 1.5 / ControlNet já baixados | **não** — faltam ~3,5 GB |

### Correções

1. **Eu dupliquei torch.** Instalei `~/.cache/forge3d/venv-gpu` (2.4.1) sem verificar
   `~/.venvs/triposr` (2.5.1). Consolidar: **uma** venv para i23d, **outra** para concept — e duas
   venvs aqui é decisão consciente, porque TripoSR prende `transformers==4.35` e `diffusers` moderno
   exige ≥4.44. O conflito de pin é real; o desperdício não (GAP-031).
2. **`~/tpose-pipeline/` não é o lugar.** Concept é provider; estado e proveniência ficam em
   `$FORGE3D_HOME` (D24). Diretório paralelo duplica cache, sai do allowlist e cria um segundo
   "onde está o modelo".
3. **`~/.venvs/tpose-gen` é aceitável** como nome da venv do concept (fora do repo, isolada).
4. **IP-Adapter FaceID: evitar** — os modelos InsightFace são **não comerciais**; a allowlist reprova.
5. **Via híbrida (API Gemini)**: não usar para asset de jogo. Quebra D3 (v0 sem modelo fechado por
   API) e a reprodutibilidade (D2/D3). "Fidelidade de likeness de ator" é passivo jurídico, não
   requisito de produto.

### O dado que faltava: pose não era o gargalo

O T-pose **piorou** o resultado (capa virou chapa, corpo virou lâmina). E `--mc-resolution 512`
custou 336 s e devolveu a mesma topologia de 256. Ou seja: o gargalo é a representação do modelo de
vista única, não a pose nem a resolução. Ordem de investimento que a evidência sustenta:

1. **separar o asset** (corpo, capa, arma como itens do lote) — barato, ataca a oclusão;
2. **trocar/avaliar o reconstruir** (SF3D com UV+material) antes de investir em concept;
3. concept com pose só depois, e ainda assim para personagem original, sem capa.
