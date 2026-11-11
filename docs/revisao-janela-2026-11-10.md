# Revisão da janela — 10/11/2026

## Resultado

- **P0, P0.5 e P1 fechadas.**
- **P3/P3.5 fechadas** para prop, concept→mesh, split e **3 personagens híbridos** com capa.
- **P2 parcial**: R15 com 16 ossos, pivô no Studio, `.rbxlx` nativo e upload Open Cloud real aprovado;
  falta a verificação visual no GUI, os pivôs nos Bones, escala/stud e U1–U4.

## Ativos e medições

| Item | Resultado |
|---|---|
| Bule P3 | 7.960 tris, textura 512², G1–G9, Godot AABB idêntico |
| Sentinela concept→mesh | 7.940 tris, 37,2 s, sem `origem`, Godot AABB idêntico |
| A/B 3 personagens | sentinela .02 7.954 / scout .05 7.950 / heavy .04 7.960 tris, `AB_OK` |
| R15 `.rbxlx` nativo | 16 Parts + 15 Motor6D, `R15_RBXLX_PASS` |
| R15 GLB no Studio | 1 MeshPart 1,85 m + **16 Bones R15**, `BONES_OK ossos=16` |
| Upload Model | asset **136741921517312**, Approved, 39.068 B |
| Upload Image/atlas | asset **75934318775024**, Approved, 843 B (64×64) |
| `TextureID` | `rbxassetid://75934318775024`, `TEXTURE_APPLY_OK` |
| Suíte | **51 verdes + 1 GPU (skip)** em 16,0 s |
| E2E rápido | **2,0 s** |
| CI sem GPU/Blender | **36 verdes** + contexto + P0 |
| Contexto | `CONTINUAR` 199/200, `MAPA` 49/60 |

## Limitações conhecidas

- O **servidor headless** do `run-in-roblox` não carrega assets privados: a textura aparece como
  `No asset content representation`; a Image está Approved e o `GET` funciona. Verificação visual
  exige o **Studio GUI logado**.
- O upload **Model** entrega **1 MeshPart + 16 Bones**, não um `Humanoid` R15 com Parts/Motor6D.
  O `.rbxlx` nativo é o rig de pivôs validado; o asset skinned é a malha texturizada.
- A key tem **Read + Write** e fica em `~/.config/forge3d/roblox.key` (modo 600, fora do repo).
  Creator do asset: **11966727684**. Nenhum segredo está no repositório.
- GPU é compartilhada com um `llama-server`; runs `mesh` podem bloquear com `FORGE-E-RECURSO` (exit 6).

## Aberto

- **P8/GAP-006**: GUI/textura, pivôs nos Bones, escala/stud, U1–U4, `[verificar]` do perfil.
- **GAP-008**: primeiro run do workflow no GitHub; suíte Blender/GPU continua local.
- **C5–C11**: flake e2e, `delegar.py`, `verify` antigo sem `pivo_regra`, convexidade no G7,
  rembg explícito, `FORGE3D_MODELOS`, limite de 77 tokens do CLIP.
- **P4/P5**: rota `modular` (WFC) e animação/retarget.

## Próximos passos (ordem)

1. **Fechar P8/GAP-006**
   - abrir o Studio GUI logado, inserir o package **136741921517312** e conferir a textura
     **75934318775024**;
   - testar rotação dos 16 Bones (pivô por membro) e o `Humanoid`/rig;
   - validar escala/stud e U1–U4; remover `[verificar]` do perfil Roblox.
2. **Primeiro run do CI no GitHub** (GAP-008); documentar que a suíte Blender/GPU é local.
3. **Correções C5–C11** em uma sessão.
4. **P5 animação/retarget** (2–3 sessões).

## Como retomar

```bash
cd /home/eudespatricio/3DCreation && . .venv/bin/activate
python -m pytest tests/test_e2e_rapido.py -q
python -m pytest -q
bash tools/check-contexto.sh
python tools/check-p0.py

# R15
forge3d run examples/lote_09_r15.yaml
forge3d export-r15 examples/lote_09_r15.yaml --item personagem.r15.guard.01
forge3d upload-model <glb> --creator-id 11966727684 --dry-run
forge3d upload-image <png> --creator-id 11966727684 --dry-run
FORGE3D_ROBLOX_API_KEY_FILE=~/.config/forge3d/roblox.key forge3d verify <destino>
```

## Commits da janela

`a78897a` concept/sentinela · `5208cd5` split · `5bbd392` híbrido · `026e123` A/B/R15/gc/CI ·
`8b8e3f0`/`b9a77a1` Studio/pivô · `a254bbb` `.rbxlx` nativo · `ea1733f` upload ·
`1ae65b7` helper · `1b35a13` upload real/Bones · `aa8ef73` textura.

> Fonte de verdade: `DECISOES.md` §1–§2, `docs/gaps.md`, `docs/pendencias.md` e os logs em
> `docs/preview/`. Documento mais velho que o código mente.
