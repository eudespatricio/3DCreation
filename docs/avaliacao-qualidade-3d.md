# AVALIAÇÃO — Escalar a qualidade dos assets 3D (rev. 2, sem novas conexões)

> **Data:** 18/11/2026 (atualizado em 21/11/2026 após D133 — integração local TRELLIS.2-4B).
> **Decisão do operador:** não adicionar conexões novas — fazer as existentes trabalharem melhor
> (Google Ultra / Nano Banana, TRELLIS.2-4B MIT local em RTX 3060 6 GB, Vault CC0 + kitbash).
> Todo número é rotulado `[oficial]` / `[terceiro]` / `[estimado]`. Fontes no fim.
>
> **Implementado nesta janela:** D112 (Pixal3D MIT sai do bloqueio do D18) e D113
> (`referencia_estilo` no concept via Gemini, `PIPELINE_VERSION` 0.9.2). GameOne auditado:
> pipeline 100 % Godot (`godot4`/`godot4-aa`, 81 manifestos) — o "look Roblox" é DNA de material
> compartilhado da leva AA v0.9.0, não pipe Roblox.

## 1. Diagnóstico — onde a qualidade trava hoje

| Elo da cadeia | Estado atual | Veredito |
|---|---|---|
| Concept (2D) | SD1.5 local / Gemini (Nano Banana) / Higgsfield, **sem consistência de estilo** | gargalo nº 1: cada asset nasce com estilo solto |
| Geometria | TripoSR local (MIT, 6 GB) vs **TRELLIS.2-4B MIT local** (`BF16/512`, `301s`, `4.488 MiB` VRAM, `tools/trellis2_infer.py`) | resolvido em D133: `TRELLIS.2` local como motor principal em GPU CUDA |
| Textura/PBR | bake Cycles, `pbr_zonas`, albedos 1024 | forte |
| Rig/QC | smart_fit, rig 56, G1–G11, LOD medido, QA visual | forte — o portão do Forge3D é melhor que o de qualquer serviço |

O que o Tripo3D faz não é mágica de modelo: é pipeline encadeado por etapa com curadoria. O Forge3D
já tem a segunda metade (bake/rig/QC); a primeira metade (estilo consistente + gerador de maior
fidelidade) agora é atacada **sem conexão nova**.

## 2. Motor 1 — Nano Banana com imagem de referência (implementado: D113)

O Google publicou o codelab oficial de [imagens consistentes com o Nano Banana](https://codelabs.developers.google.cn/gemini-consistent-imagery-notebook?hl=pt-br):
imagem de referência (style sheet/character sheet) + prompt mantêm o estilo nas gerações seguintes;
custo do lab completo < US$ 0,40 `[oficial]`.

- **Campo novo no `spec@6`** (aditivo, precedente D87): `referencia_estilo` por item — exige rota
  `mesh` e provider `gemini`/`auto` (regra B23). O PNG entra como parte de imagem no payload
  existente do Gemini Interactions (mesmo formato do QA visual), o sha256 entra na chave de cache e
  o hash curto na versão do `providers.texture` do manifesto (`+ref<12>`, I10).
- **Sem treino, sem serviço novo, sem custo novo** além do plano Google Ultra já pago.
- **Próximo passo natural:** um check de "deriva de estilo vs. referência" no `visual_qa_critic`
  usando o `gemini-4-hydrogen` já conectado — consistência vira gate, não sorte.

## 3. Motor 2 — TRELLIS.2-4B local (MIT, D133)

- Validado na RTX 3060 Laptop 6 GB (`low_vram=True` + 24 GB RAM WSL2, `BF16/512 tuned`) via subprocesso isolado `tools/trellis2_infer.py` (`301,01 s`, `4.488 MiB` VRAM pico, `0` custo de API).
- `Pixal3D` (MIT desde D112) e `TRELLIS-image-large` (MIT) seguem aceitos na allowlist D18.

## 4. Motor 3 — ajuste fino / fallback

- Style LoRA SDXL (US$1,5–5 `[terceiro]`) fica como plano B do Motor 1, se a referência de imagem do Nano Banana não bastar para o estilo do jogo.
- Caminho Colab anterior (`colab_trellis_*`) foi descontinuado em D133 após validação da inferência local.

## 5. O que NÃO fazer (registrado para não re-pesquisar)

- **Não adicionar provider Tripo/Meshy/Rodin agora** — nenhuma conexão nova (decisão do operador,
  18/11/2026). Se um dia faltar qualidade que as conexões atuais não entreguem: Tripo API
  $0,30–0,80/asset `[estimado]`, termos pagos limpos (dono do output, sem treino com dados pagos
  `[oficial]`); Rodin só via fal.ai $0,40 `[terceiro]` para benchmark.
- **Free tier de serviço nunca** (outputs públicos/CC BY `[oficial]`); **outputs de serviço nunca
  como dataset de treino** (cláusula anti-treino `[oficial]`).
- **Nenhum modelo novo cabe em 6 GB local** — o caminho sem GPU (`blocky`/`import`/TripoSR) permanece.

## 6. GameOne — resultado da auditoria (18/11/2026)

- 81 manifestos: 78 `godot4` + 3 `godot4-aa`, `escala_saida: 1.0`, `manifest@6`, pipeline 0.9.0;
  zero menções a roblox em specs/manifestos; zero `.rbxlx`; todas as texturas Forge3D do jogo têm
  origem (sha256) em `saida/game1_sylveria` (destino Godot).
- O "look Roblox" percebido é a **paleta de material compartilhada** da leva AA v0.9.0 (cristal
  arcano, obsidiana, esmeralda + trios `_basecolor/_normal/_orm`), criada para os dois showcases.
  Para diferenciar o visual: paleta + iluminação (WorldEnvironment do Godot), não pipeline.
- Gap de proveniência no nível do jogo: texturas `_v09b_256`/`_v09c` existem só no GameOne, sem
  origem no estado do Forge3D — provável re-bake do pipeline do próprio jogo.

## 7. Próximos passos propostos (por medição)

1. Rodar o primeiro lote com `referencia_estilo` (style sheet do jogo) e medir consistência no QA visual;
2. A/B TripoSR × TRELLIS por classe (pass-rate G1–G11 + turntables) e decidir o padrão;
3. Só então avaliar LoRA TRELLIS.2 para a classe que falhar de forma consistente;
4. Se o Nano Banana não segurar o estilo: style LoRA SDXL (plano B do Motor 1).

## 8. Fontes principais

- [Codelab Google — imagens consistentes com Nano Banana](https://codelabs.developers.google.cn/gemini-consistent-imagery-notebook?hl=pt-br)
- [HF blog — 3D LoRA finetuning (12/11/2026)](https://huggingface.co/blog/3d-lora-finetuning) ·
  [repo trellis2-finetuning](https://github.com/suvadityamuk/trellis2-finetuning)
- [Pixal3D LICENSE (MIT)](https://raw.githubusercontent.com/TencentARC/Pixal3D/master/LICENSE) ·
  [TripoSG](https://huggingface.co/VAST-AI/TripoSG)
- [custo de LoRA em GPU cloud](https://aiofm.info/en/guides/cost-to-train-lora-cloud-gpu) ·
  [pipeline indie Althera](https://altheragames.com/en/blog/ai-asset-pipeline-stable-diffusion-ue5)
- [Tripo pricing](https://www.tripo3d.ai/product-doc/getting-started/pricing-credits) ·
  [Tripo terms](https://www.tripo3d.ai/terms) (referência futura, não adotado)
