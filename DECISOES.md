# DECISOES — Forge3D

**Regra deste arquivo:** só entra o que foi **decidido** ou **medido**. Discussão em aberto fica em §4.
Se algo não está aqui nem no `CONTINUAR.md`, não foi decidido — foi só conversa.

> Este arquivo é **ledger append-only** (herdado de D19 do projeto `conselho`): agente não o lê inteiro.
> O estado canônico e enxuto vive em `MAPA.md` + `CONTINUAR.md` + `INVARIANTES.md`.

---

## 1. Fatos medidos (10/11/2026, WSL2 Ubuntu, máquina do operador)

| Fato | Valor | Como foi medido |
|---|---|---|
| Blender headless | **4.2.0** em `~/.local/bin/blender` | `blender --version` |
| Export GLB por script | **funciona**; gerou `smoke.glb` de 1.728 B | `blender -b --python` com `export_scene.gltf` |
| Draco no export | disponível | log do exportador |
| Python embutido do Blender | **3.11** (`4.2/python/lib/python3.11`) | caminho do `libextern_draco.so` |
| Python do sistema | **3.14.4** — inadequado para `torch` | `python3 --version` |
| Interpretadores via `uv` | 3.10.22 · 3.11.16 · **3.12.14** já instalados | `ls ~/.local/share/uv/python` |
| GPU | **RTX 3060 Laptop, 6.144 MiB**, driver 617.42 | `nvidia-smi` |
| Passthrough GPU no WSL | ativo (`/dev/dxg` presente) | `ls -la /dev/dxg` |
| RAM | **15 GB** total | `free -g` |
| Disco livre | **868 GB** em `/` | `df -h /home` |
| Rede | pypi e github acessíveis (HTTP 200) | `curl -o /dev/null -w %{http_code}` |
| Docker no WSL | presente, usuário em grupo `docker` | `docker` + `id` |
| Ferramentas ausentes | `rg`, `jq`, `ffmpeg`, `unzip`, `git-lfs` | `command -v` |
| ImageMagick | presente (`convert`/`magick`) | `command -v` |
| Ollama | `llama3.1`, `qwen2.5-coder:7b`; **contexto efetivo 4.096** | `ollama list`; contexto medido no projeto `conselho` (DECISOES §1) |
| Diretório do projeto | `/home/eudespatricio/3DCreation` — **vazio** antes desta sessão | `ls -la` |
| `edit` em caminho UNC | **falha** com `GetFileSecurityW EIO` (reproduzido nesta sessão) | tentativa de editar `docs/perfis-export.md` pelo harness |
| `run` 3 itens, cache frio | **2.082 ms**, exit 0, 3 publicados | `date +%s%N` em 10/11/2026 |
| `run` 3 itens, cache quente | **476 ms**, `cache_hits: 3`, `trabalho_executado: 0` | idem |
| `plan` 3 itens | **141 ms** | idem |
| `verify` 3 manifestos / 12 arquivos | **127 ms** | idem |
| Determinismo D1 | **sha256 idênticos** nos 12 artefatos entre 2 runs com cache limpo | `tests/invariants/test_i1_determinismo` |
| Asset `mob.skeleton.guard` | 72 tris · bbox 0,814×1,85×0,333 m · 23 ossos · 1 colisor convexo · 5 arquivos · 38.619 B | manifesto publicado |
| Suíte de testes | **26 verdes** (17 unidade + 9 ponta a ponta) em ~75 s | `python -m pytest -q` |
| `mob.android.sentinel.01` (humanoide, blocky) | **300 tris** · 25 caixas · 23 ossos · atlas 128 px · 1 material · 5 arquivos · 73.222 B | manifesto publicado |
| LODs da rota blocky | LOD0 **300** · LOD1 **130** · LOD2 **45** tris | campo `lod` do manifesto |
| `run` android (1 item) | **939 ms** frio · **307 ms** quente (`trabalho_executado: 0`) | `date +%s%N` em 10/11/2026 |
| Import no **Godot 4.3** | `Node3D → Armature → Skeleton3D (23 ossos) → MeshInstance3D`; AABB 0,7584×1,85×0,4255 **idêntico ao manifesto**; `albedo_tex=true`; `filtro=2` (nearest + mipmaps) | `godot --headless --import` + inspeção GDScript |
| Eixos de osso | todos com **X local = +X do mundo**, Y ao longo do osso | `data.bones[].matrix_local` no Blender |
| Rig rígido sob pose | sem fenda nas juntas depois de sobrepor peça ao pivô; manga de junta no osso pai | render `docs/preview/android_pose_final_*` |
| Slot da rota `mesh` | registrado; `doctor` reporta `P3: torch ausente — instale o extra GPU`; lote com rota mesh sai `bloqueado` com exit 5 e **nada escrito no destino** | `forge3d doctor` + `run examples/lote_02_rotas.yaml` em 10/11/2026 |
| Atlas do android | **64×64 px** → 34,6 px/m de densidade de texel (close-up pede ~380 px/m) | `Pillow` sobre o PNG publicado |
| Stack GPU instalada | torch **2.4.1+cu121**, `cuda_available=True` na RTX 3060 Laptop; venv fora do repo em `~/.cache/forge3d/venv-gpu` | `torch.cuda.is_available()` |
| `torchmcubes` sem CUDA toolkit | **inviável compilar** (sem `nvcc`, cmake, ninja) → substituído por `tools/torchmcubes_shim.py` (PyMCubes) | `command -v nvcc` |
| Bug de eixo no shim | PyMCubes devolve eixos invertidos vs `torchmcubes`; sem inverter, altura vira profundidade. Corrigido e provado com elipsoide | `tools/torchmcubes_shim.py` |
| Background removal (concept limpo) | **funciona**: rembg recortou o sujeito e compôs fundo neutro; o input do modelo ficou correto (85 % de enquadramento) | render do `input.png` do TripoSR |
| TripoSR — tempos medidos | model forward **1,8–3,1 s** · extração de malha **3,7–4,5 s** · total **21–36 s** frio (24 s é carregar pesos) | log do `run.py` |
| TripoSR — saída | ~**67.800 tris**, GLB de 1,36 MB, **sem UV e sem material** (só `COLOR_0`) | `qc.analisar` no GLB |
| TripoSR — orientação | altura sai no **eixo Y em 2 de 2 inputs** → normalização obrigatória | `tools/normalize_mesh.py` |
| TripoSR — qualidade (2 inputs) | foto real com capa → casca oca, pernas fundidas; render flat do android → laje extrudada | renders em `.scratch/` |
| TripoSR — T-pose (OpenPose) | **pior**: capa virou chapa de 1 m, corpo virou lâmina; extração de 4,5 s → 23,1 s | `.scratch/tpose_canon_frente.png` |
| TripoSR `--mc-resolution 512` | **336 s** (CPU, via shim) e **topologia igual** a 256 — só suaviza | run em 10/11/2026 |
| Venv do TripoSR já existia | `~/.venvs/triposr` (3.11.16, torch 2.5.1+cu121, CUDA ok, sem pip); instalei uma segunda (2.4.1) | `~/.venvs` + `~/.cache/forge3d/venv-gpu` |
| Canal de delegação (`agentapi`) | **funciona** com `ANTIGRAVITY_LS_ADDRESS=127.0.0.1:43023` + `ANTIGRAVITY_CSRF_TOKEN`; cria conversa e responde via `brain/<id>/.system_generated/steps/` | teste em 10/11/2026 com IDE aberta |
| `new-conversation` é **agêntico** | executa ferramentas (`commandExecutionPolicy: eager`), não é endpoint de completude; no teste rodou comandos de shell | `brain/3836b572-…/steps/13/output.txt` |
| Language server headless sozinho | **crashou** (panic do binário Go); só sobe com a IDE | `-headless=true -http_server_port=50091` |
| SF3D — acesso gated | token salvo e usuário `eudespatricio` OK, mas **HTTP 403** em `config.yaml` e `model.safetensors`; repo é `gated: auto`, `emailVerified` nulo | API `/api/whoami-v2` + `/resolve/main/*` em 10/11/2026 |
| SF3D — instalação | `~/.venvs/sf3d` (3.12, torch 2.4.1+cu121, CUDA ok); `texture_baker` compilado **CPU** (`USE_CUDA=0`, sem nvcc) → `_C` ok | smoke test de import |
| SF3D — conflitos resolvidos | `cmake` 4.x quebra build antigo (usei 3.31 via PyPI, sem sudo); `scipy 1.18` exige numpy 2 e quebrava trimesh/rembg (fixei 1.13.1) | logs do build |
| SF3D — `gpytoolbox` | falhou no build (cmake); é usado **só** no remesh → import tornado opcional no vendor, `--remesh_option none` | patch em `sf3d/models/mesh.py` |
| SF3D — **acesso liberado** | aceite gated concedido; `config.yaml` passou de 403 para 200 | `curl` com token em 10/11/2026 |
| SF3D — geometria em 6 GB | **funciona**: mesh extraída com 8.066 vértices / 16.128 faces | log: `After Remesh 8066 16128` |
| SF3D — **tempo real** | **~8 min por imagem** (`0/1 [08:01]`), VRAM de pico **5.844/6.144 MiB** — o "0,5 s" é A100 | mon amostrador 1 Hz |
| SF3D — bake de textura **falha** sem CUDA toolkit | `texture_baker` compilado com `USE_CUDA=0` só registra kernel CPU: `NotImplementedError: 'texture_baker_cpp::rasterize' ... only available for [CPU]` | traceback em `/tmp/forge3d_teste/sf3d512.log` |
| Estimativa do `plan` | 9,0 s estimados × 2,08 s reais para 3 itens (≈3× conservador) | comparação dos dois relatórios |

| P3-A — bake próprio (`bpy`/Cycles CPU) | **funciona**: malha com `COLOR_0` sem UV vira `TEXCOORD_0` + PNG 512²; G3/G5 verdes | `blender/postprocess.py` + `tests/test_p3_bake.py` em 10/11/2026 |
| P3-A — reparo de topologia | **1 triângulo solto** (área 5,1e-6 m²) saído do decimate; remover ilha de 1 face zera o G1 (3 bordas → 0) | `resultado.json` + inspeção `bmesh` em 10/11/2026 |
| P3-A — tempo do bake | **~2,8 s** para 7.958 tris a 512 px (Blender 4.2, CPU) | `time` no run do bule em 10/11/2026 |
| i23d — venv consolidada | **`~/.cache/forge3d/venv-i23d`** (Python 3.12.14, torch 2.4.1+cu121, 5,6 GB); `~/.venvs/triposr` (5,8 GB) removida | `du -sh` + `import torch` em 10/11/2026 |
| i23d — inferência TripoSR (bule) | **7.960 tris** publicados; load 7,7 s + forward 1,2 s + extração 3,8 s (total 12,6 s); VRAM pico **2.378 MiB** | `i23d_resultado.json` em 10/11/2026 |
| i23d — run completo (mesh) | **23,3 s** frio; **2,1 s** cache hit; GLB 1.126.404 B + PNG 313.107 B | `time` + manifesto publicado em 10/11/2026 |
| QC `prop.bule.exemplo.01` | **G1–G9 verdes**, 7.960 tris, bbox 0,19769×0,300×0,174134 m, 1 material, textura 512² | manifesto + `forge3d verify` em 10/11/2026 |
| Godot 4.3 — bule | `Node3D → MeshInstance3D`; AABB **0,19769×0,300×0,174134** idêntico ao manifesto; `albedo_tex=true`; 7.960 tris; previews em `docs/preview/p3_bule_*` | `godot --headless --import` + GDScript em 10/11/2026 |
| `doctor` mesh | **`mesh: pronto (TripoSR, torch 2.4.1+cu121, venv venv-i23d)`** | `forge3d doctor` em 10/11/2026 |
| `verify` reexecuta G1–G9 | manifesto íntegro → ok; G2 com `esperado_m=1,2` → exit 3, "QC reexecutado reprovou G2" | `tests/invariants/test_invariantes_e2e.py::test_i4_verify_reexecuta_gates_contra_manifesto` |
| Kit P3-D | corpo **300 tris / 23 ossos**, capa **60 tris / sem rig**, arma **36 tris**; 3 publicados e `verify` ok | `examples/lote_03_kit.yaml` em 10/11/2026 |
| Godot 4.3 — kit | capa montada no osso `Chest` (idx 4), arma em `Hand.R` (idx 14); `KIT_OK` | `mount_kit.gd` em 10/11/2026 |
| Suíte após P3.5 | **44 verdes + 1 GPU (skip; manual passa)** (24 unidade + 2 P3-A + 6 concept + 1 e2e rápido + 11 invariantes) em **13,7 s**; e2e rápido **2,0 s** | `pytest -q` em 10/11/2026 |
| Probe Roblox R15 (sem Studio) | **prop** blocky publica e `verify` passa (48 tris, 1 colisor); **humanoid** falha em `pivot: junta` (fora do enum) e o blocky não gera nomes R15; `colisao.prefixo` ausente causava `KeyError` no G7 (corrigido) | `docs/perfis-export.md` §3 + `run`/`verify` em 10/11/2026 |
| Planilha de custo mesh | **25 s estimados × 23,3 s reais** (erro +7%, dentro de 50%) | comparação `plan` × `run` em 10/11/2026 |
| Qualidade TripoSR (cadeira) | **inutilizável**: 81.952 faces de entrada viraram blob; mesmo com rembg. Bule ficou reconhecível | previews `.scratch/chair_*` / `.scratch/teapot_*` em 10/11/2026 |


| P3.5 — concept SD1.5 (robô) | 512², 20 steps: geração **5,3 s**, primeira carga **47,1 s** (inclui download de 13 arquivos, ~2 GB), VRAM pico **2.690 MiB**, PNG 287.681 B | `tools/concept_infer.py` em 10/11/2026 |
| P3.5 — venv concept | `~/.venvs/concept` **5,6 GB** (cópia da i23d + diffusers 0.31.0 / transformers 4.44.2 / accelerate 1.2.1; torch 2.4.1+cu121) | `tools/setup_concept_venv.sh` + `du -sh` em 10/11/2026 |
| P3.5 — concept SD1.5 (cache quente) | load **2,0 s** + geração **5,5 s** = **7,6 s**; VRAM pico **2.675 MiB** | `concept_resultado.json` do run sentinela em 10/11/2026 |
| P3.5 — concept→mesh (sentinela) | **37,2 s** de run; i23d 16,9 s (load 6,8 + extração 3,7); **7.940 tris**; bbox **1,000387×1,8×0,729638 m**; GLB **1.149.148 B**; PNG **337.824 B**; G1–G9 verdes | `run` em 10/11/2026 |
| P3.5 — orientação de humanoide | `centro_area=5,55` < 5,76 → espelha Z; `invertido=true`; 10 ilhas de 1 face removidas; G1 0 | `resultado.json` em 10/11/2026 |
| P3.5 — Godot 4.3 (sentinela) | `Node3D → MeshInstance3D`; AABB **1,000387×1,8×0,729638** idêntico ao manifesto; `albedo_tex=true`; 7.940 tris | `godot --headless` + GDScript em 10/11/2026 |
| P3.5 — fallback CPU | run completo **71,4 s** (384²/8 steps, mc128); mecânica OK, concept em close e malha não utilizável | `time` em 10/11/2026 |
| P3.5 — split mesh (3 concepts) | **1m39,9s**; corpo **7.954 tris**, capa **4.972**, arma **1.988**; 3 publicados e `verify` ok | `run` em 10/11/2026 |
| P3.5 — split no Godot | corpo AABB **1,114836×1,8×0,906218**; capa **0,793371×1,3×0,670403**; arma **0,93732×1,0×0,833001**; `SPLIT_OK` | `mount_split.gd` em 10/11/2026 |
| P3.5 — qualidade do split | corpo reconhecível; **capa e arma saíram blobs** (TripoSR não lida com peça fina/isolada) | previews `docs/preview/p3_split_*` em 10/11/2026 |

| P3.5 — capa .03 | prompt "empty cloak" + negativo de pessoa: **35,8 s**, **4.972 tris**, G1–G9; o concept ainda é uma figura encapuzada, a malha é uma casca de capa | `run` em 10/11/2026 |
| P3.5 — personagem híbrido | corpo .02 + capa .03 + arma `blocky` .01; Godot `CHAR_CAPE_OK`; AABB corpo **1,114836×1,8×0,906218**, capa **0,531849×1,3×0,355717**, arma **0,209×0,95×0,0666** | `godot --headless` em 10/11/2026 |
| P3.5 — qualidade do conjunto | corpo/capa/arma reconhecíveis no híbrido; capa/arma mesh .02 isoladas seguem blobs (D39) | previews `docs/preview/p3_char_cape_*` em 10/11/2026 |

| P3.5 — A/B 3 personagens | corpos .02/.05/.04 (**7.954/7.950/7.960 tris**) + capa .03 + arma blocky .01; Godot `AB_OK`; imagem `docs/preview/p3_ab_3personagens.png` | `run` do lote_08 + Godot em 10/11/2026 |
| P3.5 — scout .05 | **7.950 tris**; orientação `razao_topo_base=5,071` → invertido; G1 0 | `resultado.json` em 10/11/2026 |
| P3.5 — sliver no G1 | face de área **2,96e-9 m²** deixava 3 arestas não-manifold; remover faces < 1e-8 resolveu | `resultado.json` em 10/11/2026 |
| P2 — R15 blocky | **300 tris**, **16 ossos** R15 (todos no mapa), G1–G9, `verify` ok; Godot `R15_OK`; Studio pendente | `run`/`godot` em 10/11/2026 |
| gc | remove cache/runs/staging > 30 dias; **2 testes**; não toca `saida/`, índice nem ledger | `tests/test_gc.py` em 10/11/2026 |
| CI | `tools/ci.sh` roda **36 testes** + contexto + P0; workflow em `.github/workflows/ci.yml` | `bash tools/ci.sh` em 10/11/2026 |

| P2 — R15 no Studio | **`R15_STUDIO_PASS motores=15 partes=16`**; Studio `63eb6055af4e4688`, `run-in-roblox` 0.3.2; log `docs/preview/r15_studio_test.log` | `run-in-roblox` em 10/11/2026 |
| P2 — R15 GLB, pivôs por membro | 16 ossos com cabeça nos joints (H=1,85 m): LowerTorso **0,814** · UpperTorso **0,962** · Head **1,443** · braço **1,406/1,110/0,814** · perna **0,814/0,4347/0,1203**; Y constante **-0,0554** | Blender no GLB em 10/11/2026 |
| P2 — import do GLB no Studio | `AssetImportService:StartSessionWithPathAsync` **nil** no plugin; import de malha/textura segue manual | `run-in-roblox` em 10/11/2026 |

| P2 — export nativo `.rbxlx` | `forge3d export-r15` gera **16 Parts + 15 Motor6D** (18.479 B); abre no Studio e passa **`R15_RBXLX_PASS partes=16 motores=15`**, sem upload/textura | CLI + `run-in-roblox` em 10/11/2026 |
| P2 — CFrame no `.rbxlx` | Part precisa de `CFrame`; com `Position` os Parts ficavam na origem e o pivô errava | primeira versão em 10/11/2026 |

| P2 — upload Open Cloud | `upload-model` dry-run + servidor local: POST multipart com `x-api-key`, `operation` e `assetId=999`; 2 testes; upload real pendente de key/creator | `tests/test_upload.py` em 10/11/2026 |
| P2 — `Model` no Open Cloud | `.glb` 39 KB, limite 20 MB; importa como **package de MeshParts**, não como rig R15; API key/upload **free** | doc Open Cloud em 10/11/2026 |

| P2 — diagnóstico da key | `~/.config/forge3d/roblox.key` existe, modo **600**, **0 B**; creator ID/type ausente no shell; **nenhum upload** foi feito | diagnóstico em 10/11/2026 |
| P2 — helper de config | `tools/configurar_roblox.sh`: key oculta, creator ID, dry-run e upload opcional; `bash -n` ok | 10/11/2026 |

| P2 — upload real aprovado | assetId **136741921517312**, operation `856adaa5-…`, moderação **Approved**, **39.068 B** | upload em 10/11/2026 |
| P2 — asset no Studio | `InsertService:LoadAsset` → **1 MeshPart** 0,7584×1,85×0,4255 com **16 Bones R15**; `TextureID` 126102198021602 falha (sem conteúdo) | `run-in-roblox` em 10/11/2026 |

| P2 — textura R15 separada | PNG 64×64 do GLB (843 B) subiu como **Image** assetId **75934318775024**, moderação **Approved**; `TextureID` do MeshPart trocado para ele | upload em 10/11/2026 |
| P2 — texture no headless | servidor `run-in-roblox` ainda falha `No asset content representation` para 75934318775024; asset aprovado e GET ok; falta ver no GUI logado | `run-in-roblox` em 10/11/2026 |

| Custo concept→mesh | **40 s estimados × 37,2 s reais** (erro -7%) | `plan` × `run` em 10/11/2026 |

| P3.5 — pesos SD1.5 | **2,0 GB** em `~/.cache/huggingface/hub/models--stable-diffusion-v1-5--stable-diffusion-v1-5` (fp16, revision `451f4fe…`) | `du -sh` + snapshot HF em 10/11/2026 |


| CI no GitHub | repo público `github.com/eudespatricio/3DCreation`; run **42942191684** `success` em `cc89da4`; **PR #1** verde em `push` e `pull_request`, merge `7e24615` | API do Actions em 10/11/2026 |
| Suíte após C5–C11 | **68 verdes + 1 GPU (skip)** em ~18 s; 17 testes novos (`test_correcoes.py`, `test_convexidade.py`) | `pytest -q` em 10/11/2026 |
| C5 — flake e2e | **10 execuções seguidas** de `test_e2e_rapido.py` verdes | loop local em 10/11/2026 |
| Colisor `convex` (defeito) | 44–497 tris com **22–146 arestas não-manifold**; `convex_hull` não apaga a entrada e faces originais ficavam no recorte | 14 colisores publicados, 10/11/2026 |
| Colisor após correção | hull reconstruído só com `hull["geom"]`; G7/convexidade verde nos 12 invariantes | `test_invariantes_e2e.py` em 10/11/2026 |
| `.rbxlx` no caminho default | **18.479 B**, 16 partes, 15 motores em `saida/r15/personagem.r15.guard.01.rbxlx` | `export-r15` em 10/11/2026 |

| Trabalho paralelo (worktree) | 3 itens revisados e integrados: atomicidade do publish, helpers de VRAM/PID, linter de conformidade. A reescrita do `lock_gpu` com `unlink` antes do `flock` foi **rejeitada** (corrida de inode) e refeita | revisão em 11/11/2026 |
| Suíte após o paralelo | **86 verdes + 1 GPU (skip)** em **17,2 s**; CI em **71 testes** | `pytest` e `tools/ci.sh` em 11/11/2026 |

| P8 — package no Studio GUI | `size=0,758 × 1,850 × 0,426` studs, **16 Bones**, `surface=false`, `humanoid=false`, `TextureID=rbxassetid://75934318775024` | Command Bar do Studio 63eb6055af4e4688, 11/11/2026 |
| P8 — escala do rig `.rbxlx` | **6,478 studs** de extensão vertical (17 Parts), contra 1,850 studs do package: **3,57×** | `medir_rbxlx` sobre `saida/r15/personagem.r15.guard.01.rbxlx`, 11/11/2026 |

| P8 — textura no Studio (MCP) | `PreloadAsync` = **`Enum.AssetFetchStatus.Success`** para `rbxassetid://75934318775024`; 16 Bones; `surface=false`; `humanoid=false` | `tools/mcp_studio.py` contra Studio 63eb6055af4e4688, 11/11/2026 |
| MCP do Studio | `StudioMCP.exe` é proxy **stdio** (38 ferramentas, inclui `execute_luau` e `screen_capture`); o Studio só aparece em `list_roblox_studios` com o proxy vivo alguns segundos | handshake em 11/11/2026 |

| Escala no Studio (MCP) | package `Size.Y = 1,850` studs; `.rbxlx` mede `6,478` studs; fator **1/0,28 = 3,5714** | `tools/mcp_studio.py` + parser do `.rbxlx`, 11/11/2026 |

| P8 fechado — escala (D62) | `manifest@2` com `unidades_export {metros_por_unidade: 0,28; escala_saida: 3,5714}`; glb `2,70855 × 6,60709 × 1,519631` **studs** para `bbox_m [0,7584; 1,85; 0,4255]` m; G2 grava `altura_export=6,60709` e `delta_pct=0` | republish do `r15` com 0.2.5 e `verify` em 0 problemas, 11/11/2026 |
| Package R15 v2 no Studio (MCP) | `Size = 2,7086 × 6,6071 × 1,5196` studs · **16 Bones** · `surface=false` · `humanoid=false` · `TextureID=rbxassetid://75934318775024` · `preload=Enum.AssetFetchStatus.Success` | asset Model **134628989553440** (39.004 B, Approved), `tools/mcp_studio.py`, Studio 16c88345, 11/11/2026 |
| Rig `.rbxlx` — defeito de tamanho (GAP-044) | as Parts saíam com **Y e Z trocados** no tamanho (o centro permutava, o tamanho não): o rig esticava para **6,8086 studs** (base `-0,3302`, topo `6,4784`) em vez de 6,6071; o fallback do `HumanoidRootPart` ainda passava 7,5 mm abaixo da base | parser do `.rbxlx` em 11/11/2026; corrigido por D68 |
| Rig `.rbxlx` após D68 | **6,6071 × 2,7086 × 1,5196 studs** (base 0, topo 6,6071; 16 Parts + Baseplate, 18.461 B) — **idêntico ao package**, resíduo 0 | parser do `.rbxlx` e Studio, 11/11/2026 |
| Compat de `verify` | `manifest@1` de `lote_01` e `kit_sentinel` continua **0 problemas** (escala 1.0); `r15` republicado em `@2` | `forge3d verify` em 11/11/2026 |
| Suíte após D62 | **99 verdes + 1 GPU (skip)** em **100 testes**; CI no GitHub roda **84** | `pytest -q` e `tools/ci.sh` em 11/11/2026 |
| Suíte após C12/D64/D65 | **101 verdes + 1 GPU (skip)** em **102 testes**; CI no GitHub roda **86**; `PIPELINE_VERSION` 0.2.6 | `pytest -q` e `tools/ci.sh` em 11/11/2026 |
| Suíte após P5/P5-B | **117 verdes + 1 GPU (skip)** em **118 testes**; CI no GitHub roda **102**; `PIPELINE_VERSION` 0.2.7 | `pytest -q` e `tools/ci.sh` em 11/11/2026 |
| CI após D62 | run **42956720067** `success` em `a21e944`; job com 84 testes + contexto + P0 | API do Actions em 11/11/2026 |
| C12 — hull do colisor (defeito real) | `convex_hull` herda faces de ENTRADA: o colisor da malha gerada saiu com face interior e o G7 reprovou (desvio de 1,8 m numa face de um colisor de 2,2 m de diâmetro) | 3 lotes mesh (`lote_05`, `lote_06`, `lote_08`), 11/11/2026 |
| C12 — colisor depois do fix (D64/D65) | hull sobre **nuvem de pontos**; desvio máximo residual **4,3e-4 m** (sub-milímetro) em 438 faces, dentro da tolerância de 1 mm/m | colisor de `personagem.sentinel.concept.01`, 11/11/2026 |
| C12 — destinos republicados | **7 destinos, 16 manifestos** em `manifest@2` 0.2.6; `verify` **0 problemas** em todos | `verify` em todos os destinos, 11/11/2026 |
| P5 — clipe `idle` por retarget (D66) | duração **2,042 s**; move `{UpperTorso, LowerTorso, Head, LeftUpperArm, RightUpperArm}` no `r15@1` e `{Chest, Spine1, Head, UpperArm.L, UpperArm.R}` no `godot-humanoid@1` | 48 canais no glb do R15 (o export amostra os 16 ossos) e 69 no android; `qc.animacoes` em 11/11/2026 |
| P5 — clipe no Godot 4.3 (headless) | `GODOT_ANIM_OK clipes=[idle] duracao=2.042 tracks=5 movimento=0.0697` (R15) e `tracks=7 movimento=0.0697` (android) | `tools/godot_anim_check.gd` em 11/11/2026 |
| P5 — manifest@3 | **7 destinos, 16 manifestos** em `manifest@3` 0.2.7, todos com `verify` **0 problemas** | `verify` nos 7 destinos, 11/11/2026 |
| P5-B — `KeyframeSequence` no `.rbxlx` | clipe `idle` com **5 keyframes** e pose completa (15 juntas; só 5 giram) por chave; place de **~40 KB** com o clipe | `export-r15` em 11/11/2026 |
| P5-B — clipe medido no rig (MCP) | com os dados do arquivo, a cadeia `Part1 = Part0 · C0 · Transform · C1⁻¹` move a Head **0,1091 studs** entre t=0 e t=0,5 (maior delta de parte 0,1253) | `tools/r15_anim_studio.py` no Studio 16c88345, 11/11/2026 |
| P5-B — playback no Roblox (client) | Animation **116049702979137** (Core): a Head anda **0,0949 / 0,0662 studs** em duas execuções no client do Play mode, no rig Motor6D construído do `.rbxlx`; com `Idle` (assets v2/v3) fica em **0,0002** | `start_stop_play` + `execute_luau` no client, Studio 16c88345, 11/11/2026 |
| P5-B — prioridade decide a aplicação | `KeyframeSequence.Priority` da animação pública 507766666 é `Core`; a nossa era `Idle`. Com Core o clip aplica, com Idle não — a diferença não era o nome da pose (testadas as duas convenções) | lido via `KeyframeSequenceProvider:GetKeyframeSequenceAsync` em 11/11/2026 |
| CI após P5/D68 | run **42960740797** `success` em `7b739f3` e **42961348850** em `9245091`; job com **96 testes** + contexto + P0 | API do Actions em 11/11/2026 |

**Não medido nesta sessão** (marcar `[estimado]` ou `[verificar]` se usar): concept→mesh
end-to-end (implementado, execução pendente), A/B de 10 assets, qualidade de personagem com capa,
comportamento do importador Roblox, desempenho do `uv` resolvendo `torch`.

## 2. Decisões

| # | Decisão | Motivo |
|---|---|---|
| D1 | **P0 é só documento.** Código de pipeline, PyTorch e download de modelo só em P1/P3, com autorização explícita | escolha do operador nesta sessão; evita construir sobre contrato não fechado |
| D2 | Produto e CLI = **`forge3d`**; o diretório permanece `3DCreation` | nome curto para pipe; renomear pasta não paga o custo. Nome definitivo é Q1 |
| D3 | Contrato de integração = **CLI + arquivo de lote + exit codes estáveis**; sem HTTP, sem MCP, sem import de biblioteca na v0 | escolha do operador; é o único contrato que qualquer pipe (bash, make, CI) consome sem adaptador |
| D4 | **Perfis de export** (`godot4`, `roblox-r15`) resolvem engine; a lógica não conhece engine | o mesmo asset serve dois jogos mudando perfil, não código |
| D5 | Fluxo canônico = **`plan → run → verify → publish`**, com etapas separáveis por subcomando | `plan` roda em CI sem GPU; `verify` é portão; separação é o que torna o custo previsível |
| D6 | **Cache por conteúdo**: `sha256(spec canônico + versão da pipeline + versões dos providers + perfil)` | rerun sem mudança tem que custar zero e não tocar arquivo (I11) |
| D7 | **Providers declararam determinismo** (D1 byte-idêntico · D2 semeado · D3 estocástico) e o pipeline trata cada classe diferente | herdado de D25 do `conselho`: teste verde é consistência, não correção. Diffusion nunca é D1 |
| D8 | Rotas nomeadas por **técnica**, não por letra: `blocky`, `import`, `mesh`, `modular` | "Rota B" não diz nada a quem entra no repo; letra vira jargão morto |
| D9 | **QC é portão duro.** Reprovou, não publica; não existe `--force` | asset ruim não entra no jogo "só pra testar" e depois fica |
| D10 | Publicação **atômica** via staging + `rename`; escrita em destino só no passo `publish` | o jogo pode ter watcher com hot-reload; arquivo parcial quebra a importação |
| D11 | **GPU é opcional e serializada**: lock de exclusividade, descarregamento declarado por provider, indisponibilidade **bloqueia** a tarefa (não falha o lote) | 6 GB não comportam dois modelos residentes; `CUDA OOM` intermitente é o pior modo de falha |
| D12 | **Manifesto + índice SQLite + ledger append-only** | origem, licença e versão precisam sobreviver ao asset; `query` por demanda exige índice |
| D13 | **LLM só como front-end opcional `forge3d draft`**, nunca no caminho crítico | lote já é declarativo; LLM no caminho crítico adiciona não-determinismo e 4k de contexto útil |
| D14 | **Animação e retarget fora da v0.** Rig = transferência de template determinística (bpy) | UniRig/RigNet em 6 GB é caro e instável; `animacoes_base` do lote fica reservado, sem promessa |
| D15 | **Blender 4.2.x pinado**, invocado por `subprocess`, entrada/saída por arquivo JSON | API do `bpy` e parâmetros do exportador mudam entre versões; stdout do Blender é ruidoso |
| D16 | **Python 3.12 via `uv`** para o pacote; 3.14 do sistema não é usado | wheels de ML não existem para 3.14; 3.12 já é o padrão do ecossistema (`ia_trader`, `dark_studio`) |
| D17 | **Preflight obrigatório** (`forge3d doctor`) com modelos de falha nomeados | 80% do tempo perdido em pipeline é ambiente, não algoritmo |
| D18 | **Licença é gate**: allowlist de modelos com uso comercial permitido; `NOTICE` por asset no manifesto | Hunyuan3D-2.x exclui UE/UK/Coreia; Pixal3D é não-comercial; asset sem licença é passivo |
| D19 | **Naming neutro**: `blocky_voxel`, nunca `minecraft_*`; valores antigos aceitos como alias legado com aviso | estética é livre, marca registrada não |
| D20 | Spec é **versionada** (`forge3d/spec@1`, hoje também `spec@2`) e validada por JSON Schema antes de qualquer provider | contrato silencioso quebra os pipes dos jogos sem aviso |
| D21 | Erros têm **código estável** `FORGE-E-*` além do exit code | pipe precisa ramificar por causa, não por parse de mensagem |
| D22 | **ComfyUI não é dependência da v0**; quando a Rota B entrar, a interface é HTTP/CLI atrás de provider | stack mais pesada do ambiente para uma função que `sd.cpp`/`sf3d` cobrem |
| D23 | **Allowlist de destino** em `~/.config/forge3d/allowlist.yaml`; sandbox do próprio Forge3D sempre liberado; **sem flag de bypass**; autorizar é `forge3d allowlist add` | deny by default — destino errado publica asset no projeto errado e não há desfazer barato (fecha Q2) |
| D24 | **Estado centralizado** em `$FORGE3D_HOME` (`~/.local/state/forge3d`): cache, runs, staging, locks, índice, ledger, saída. Nenhum `.forge/` no diretório de execução | rodar de dentro de um jogo não cria pasta nem arquivo no jogo (fecha Q6) |
| D25 | **Isolamento por padrão**: sem leitura de config a partir do cwd, sem escrita fora do estado próprio ou de destino autorizado, sem import de código de projeto de jogo | exigência explícita do operador (10/11/2026): o utilitário tem que funcionar independente de projeto |
| D26 | **Núcleo leve**: `jsonschema` + `PyYAML` + `Pillow` e `argparse`; sem pydantic/typer/rich/orjson/numpy | o schema é a fonte de verdade; instalar em segundos é o que deixa `plan` rodar no CI |

| D27 | **SF3D encerrado em 6 GB**: TripoSR é o i23d da P3; SF3D não é reinstalado (GAP-032/033/034/035 fechados por decisão) | medido: ~8 min/imagem e bake exige CUDA toolkit; TripoSR entrega em ~23 s e o bake próprio resolve UV |
| D28 | **Bake próprio no `bpy`** para malha com `COLOR_0`: `smart_project` + bake `DIFFUSE/COLOR` em 512², Cycles CPU; sem `moderngl`/EGL | medido em 10/11/2026: G3/G5 verdes em 2,8 s; TripoSR só entrega cor por vértice (GAP-028) |
| D29 | **i23d em subprocesso** na venv única `FORGE3D_VENV_I23D` (`~/.cache/forge3d/venv-i23d`), canal JSON; o núcleo não importa `torch` | 6 GB: o núcleo leve (D26) não paga 2,5 GB de torch; `doctor` mede a venv certa (GAP-031/C1) |
| D30 | **`spec@2`** adiciona `parte` (`corpo`/`capa`/`arma`), retrocompatível: `spec@1` continua aceito e o manifesto segue `manifest@1` | P3-D precisa separar peças no contrato; mudança de schema sempre sobe versão |
| D31 | **Kit P3-D**: corpo com rig, capa estática montada no osso `Chest`, arma no `Hand.R`; ids `personagem.*` | a capa estática evita esqueleto divergente; montagem por osso é o que o Godot consome |
| D32 | **`verify` reexecuta G1–G9** contra o perfil atual, com topologia em Python puro; G2 grava `pivo_regra` no relatório | hash pega arquivo trocado; reexecução pega perfil/tolerância que mudou (C2) |
| D33 | **Rota `mesh` exige `origem` (PNG)** enquanto o provider de concept text-to-image não existe (GAP-026); `prompt` é proveniência | separa a variável do diffusion da inferência; a imagem é o que o TripoSR consome |


| D34 | Concept local **SD1.5** em venv separada `~/.venvs/concept` (`FORGE3D_VENV_CONCEPT`), porque o TripoSR fixa `transformers==4.35` e o diffusers 0.31 exige `>=4.44` | dois modelos com pins incompatíveis; sem API fechada (D3); licença OpenRAIL-M na allowlist |
| D35 | Provider `mesh` executa o concept **internamente** quando o item não tem `origem`; o manifesto grava `providers.texture` (`concept/sd15`, versão+revisão, seed) e a licença combinada; `spec@1` não muda | o slot `providers.texture` já existe no `manifest@1`; evita bump de schema para uma etapa interna |
| D36 | Concept gerado usa **rembg automático** no i23d (fundo neutro), com `FORGE3D_I23D_REMOVER_FUNDO` ainda válido para imagens externas | o fundo do diffusion não é transparente; sem rembg o TripoSR inclui o fundo |
| D37 | **Orientação de humanoides gerados**: após permutar eixos, mede o perfil de área em 12 faixas; se o centro de área < 48% da altura, espelha Z (mantém frente/lados) e recalcula normais | medido: sentinela `centro_area=5,55` (cabeça embaixo) e android blocky `6,52` (ok); G2 passava mesmo invertido |
| D38 | **Fallback CPU** para `mesh`/concept via `FORGE3D_DEVICE=cpu` (lento, sem VRAM); não é o caminho de aceitação | GPU compartilhada nesta máquina; o fallback validou o encadeamento em 71,4 s |
| D39 | **Split mesh**: o corpo gerado é viável; capa/arma finas e isoladas **não** são confiáveis no TripoSR. O mecanismo de 3 itens/3 concepts fica; para capa/arma usáveis, a rota `blocky` (kit P3-D) ou um modelo especializado | medido: corpo reconhecível; capa e arma publicadas mas blobs (GAP-041) |
| D40 | **Kit híbrido para personagem com capa**: corpo `mesh` + capa `mesh` (prompt de capa vazia + negativo de pessoa) + arma `blocky`; montagem estática no Godot. A capa/arma mesh isoladas não são o produto | medido: `CHAR_CAPE_OK`, 3 assets reconhecíveis; capa/arma .02 blobs (D39) |
| D41 | **R15 no blocky**: templates godot são remapeados para as 16 partes R15; o perfil `roblox-r15` usa `pivot: base` até o pivô por membro existir | medido: 16 ossos, G6/verify ok; `pivot: junta` não é valor de spec e o Studio não está disponível |
| D42 | **Sliver de área < 1e-8 m² é removido** no `reparar_malha` antes do G1 | medido: face 2,96e-9 deixava 3 arestas não-manifold e o `dissolve_degenerate` não pegava |
| D43 | **Orientação por duas pistas**: `razao_topo_base > 1,5` ou centro de área < 48% → espelha Z | medido: sentinela/heavy pelo centro; scout `razao=5,071` com centro 6,136 (sem a pista nova ficava de cabeça para baixo) |
| D44 | **A/B de 3 personagens híbridos**: .02/.05/.04 + capa .03 + arma `blocky` .01; 3 corpos distintos, mesmo kit | 3 personagens reconhecíveis/fechados, `AB_OK`; P7/Q8 fechados para 3 personagens |
| D45 | **`gc` por idade** em cache/runs/staging; publicado, índice e ledger ficam intocados | `tests/test_gc.py`; `C3`/GAP-016 fechados |
| D46 | **CI sem GPU/Blender**: `tools/ci.sh` roda unidade/concept/gc + contexto + P0; a suíte Blender/GPU continua local | GAP-008 configurado; primeira execução no GitHub pendente |
| D47 | **Pivô por membro = head dos 16 bones**, não o pivô do objeto; o objeto fica em `base`. O teste no Studio valida 15 Motor6D; o import da malha/textura no Studio continua manual | 16 bone heads medidos no GLB; `R15_STUDIO_PASS`; `AssetImportService` sem sessão por caminho |
| D48 | **Export nativo `.rbxlx`** para R15: 16 `Part`s (agregando caixas por osso) + 15 `Motor6D` com `CFrame`/`C0`/`C1`; sem upload e sem textura. Evita o import manual do rig; o GLB/MeshPart com textura continua o caminho de mesh | 16/15, `R15_RBXLX_PASS`; Part com `CFrame` (não `Position`) |
| D49 | **Upload Open Cloud via `Model`**: `forge3d upload-model` lê a key de `FORGE3D_ROBLOX_API_KEY`, `FORGE3D_ROBLOX_API_KEY_FILE` ou `~/.config/forge3d/roblox.key`; `--dry-run` não usa rede. Key nunca entra no repo; o asset sobe como package, então o rig R15 continua no `.rbxlx` | fluxo testado contra servidor local; upload real pendente de creator/key |
| D50 | **O upload Open Cloud preserva os 16 Bones R15** dentro de um único MeshPart skinned; a textura derivada 126102198021602 não tem conteúdo. Corrigir com upload de imagem separado ou usar o rig `.rbxlx` para os pivôs | asset 136741921517312; 16 Bones; erro de `TextureID` |
| D51 | **Textura em asset separado**: `upload-image` sobe o atlas e o `TextureID` do MeshPart aponta para ele. O servidor headless do `run-in-roblox` não carrega assets privados (asset delivery sem sessão); a verificação visual é no Studio GUI logado | asset 75934318775024 Approved; `TextureID` setado; warning headless |

| D52 | **Colisor `convex` é hull fechado**: o recorte é reconstruído só com `hull["geom"]` do `bmesh`, porque `convex_hull` não apaga a geometria de entrada | medido: faces originais sobre o hull deixavam 22–146 arestas não-manifold e o G7/C8 reprovava com razão |
| D53 | **G7 mede convexidade por componente conexa** em Python puro e reprova colisor côncavo; perfil sem `prefixo` segue aceito | convexidade é da parte: dois hulls soltos no mesmo GLB são convexos e a união não é |
| D54 | **Prompt do concept é medido e truncado no limite CLIP (77)** dentro da venv, com aviso em stderr e contagem no JSON; o sufixo não repete trecho já presente no prompt | o diffusers truncava em silêncio e `game asset concept art` ia duas vezes nos prompts do lote |
| D55 | **`rembg` decidido pelo provider** por procedência (`concept`) ou canal alfa, com `FORGE3D_I23D_REMOVER_FUNDO` ainda mandando; a política (`rembgauto2`) entra na versão/cache e o motivo no resultado | `rembg` era opt-in por env e imagem opaca de origem ficava com fundo |
| D56 | **CI roda no GitHub em repo público**; `tools/ci.sh` é a fonte do job e cobre os testes de C5–C11 | primeiro run verde em 42942191684; GAP-008 fechado |
| D57 | **Delegação fica no `agentapi` e exige a IDE aberta**; não se adiciona chave de API e `tools/delegar.py` não ganha caminho headless | decisão do operador em 11/11/2026 (fecha Q9/C6): custo por token e mais um segredo não pagam um front-end opcional que nunca está no caminho crítico (D13) |
| D58 | **`empunhadura` é 20 % da altura a partir da base**, uma regra numérica única: o blocky declara o pivô nessa fração (`FRACAO_EMPUNHADURA`) e o G2 mede o desvio contra ela | medido: a mesma regra dava 10 % no blocky e 20 % no `postprocess`, e o G2 não media nenhum dos dois; a intenção do perfil ("menor secção") fica em GAP-042 |
| D59 | **`flock` é o dono do lock de GPU**; `pid_ativo` e `vram_livre_mb` são **diagnóstico**, nunca condição de posse. `lock_gpu` não faz `unlink` do arquivo de lock | a versão paralela removia o arquivo e reabria antes do `flock`: dois processos podiam flockar inodes diferentes e quebrar a exclusividade do D11 |
| D60 | **Validação no Roblox usa o MCP do Studio** (`tools/mcp_studio.py`, proxy stdio) quando o MCP está ligado; a Command Bar fica como plano B, porque é linha única e colapsa script multi-linha | medido: o `preload` só foi confirmável com o proxy vivo; a Command Bar mostrou o modelo mas não os `print`s |
| D64 | **Hull do colisor em nuvem de pontos**: o `geom` do `convex_hull` carrega faces de entrada que ficam dentro do hull; alimentar o hull só com os vértices (sem faces) devolve a superfície convexa | medido em 11/11/2026: o colisor da malha gerada saiu com face interior (desvio de 1,8 m) e o G7 reprovou os 3 lotes mesh; depois do fix o desvio máximo caiu para 4,3e-4 m |
| D65 | **Convexidade medida com tolerância de escala**: 1 mm por metro de diâmetro da parte (antes: 1e-6 do diâmetro). Concavidade real desvia em ordem de centímetro | um hull legítimo de malha gerada tem regiões quase coplanares e o triangulador do Blender deixa sub-milímetro (4,3e-4 m em 2,2 m); o gate continua pegando a face interior do C8 |
| D62 | **Escala de export declarada no manifesto**: `manifest@2` ganha `unidades_export` (`metros_por_unidade`, `escala_saida`); o `glb` do `roblox-r15` sai em studs e `bbox_m` continua em metros | medido: package 1,850 studs × `.rbxlx` 6,478 studs (3,57×); `manifest@1` não tem como declarar a unidade, e a alternativa (importar com escala 3,5714 na UI) é passo manual que o consumidor esquece |

| D66 | **Animação base por retarget semântico**: o perfil declara `rig.retarget` (osso semântico → osso do esqueleto); o `idle` é gerado no `bpy` como senoide de 5 chaves (2 s a 24 fps) e embutido no glb. O G10 mede **movimento real** (quanto o osso saiu da rotação inicial), não só a existência do canal | o mesmo clipe tem que rodar em `godot-humanoid@1` (23 ossos) e `r15@1` (16 ossos) sem nome de osso igual; procedural e determinístico, sem modelo generativo de animação (o que D14 evitava) |
| D67 | **`manifest@3` declara `animacoes`**: lista `{nome, duracao_s, ossos}` dos clipes embutidos no glb; `manifest@1`/`@2` continuam aceitos na leitura e `qc.gates` passa a aceitar `G10` | o consumidor precisa saber que o asset tem clipe sem abrir o glb; contrato silencioso é o que o `verify` existe para impedir |

| D68 | **Part do `.rbxlx` permuta o tamanho como o centro**: `Roblox XYZ = (x, z, −y)` vale para `size` e para `CFrame`; e a caixa de fallback de osso sem geometria não pode descer abaixo da base | medido em 11/11/2026: o tamanho ia `(x, y, z)` direto e cada Part saía com altura = profundidade, esticando o rig para 6,8086 studs (topo 6,4784) e escondendo o defeito atrás de "3 % de diferença"; depois do fix o rig mede 6,6071, igual ao package |

| D69 | **O clipe do Roblox sai da mesma definição**: `animacao.py` materializa o `idle` em espaço semântico; o `.rbxlx` ganha um `KeyframeSequence` (5 chaves, pose completa com as 15 juntas) e a Motor6D/Pose usam o **nome da junta R15** (`Root`, `Waist`, `Neck`, `LeftShoulder`…), não o nome da parte. O bpy e o `rbx.py` não decidem movimento, só aplicam chaves | o GLB e o `.rbxlx` não podem divergir de clipe; medido no Studio pelo MCP: a cadeia `Part1 = Part0 · C0 · Transform · C1⁻¹` move a Head **0,1091 studs** entre t=0 e t=0,5. O nome de junta é a convenção do rig R15; a **Priority é `Core` (1000)**, porque com `Idle` (0) o Animator carrega a track e não a aplica por cima do que o Humanoid toca; medido no client do Studio: a Head anda **0,066–0,095 studs** com Core e ~0,0002 com Idle |

## 3. Rejeitados (e por quê)

- **ComfyUI + TripoSR + Blender acoplados num script só** — três falhas diferentes viram uma mensagem
  só; impossível degradar, impossível testar.
- **HTTP/FastAPI na v0** (escolha do operador) — daemon para servir um comando que roda em segundos;
  retorna em P6 se houver consumidor não-Python.
- **MCP/agente chamando direto** — não substitui contrato determinístico; agente não é build.
- **LLM decidindo rota, custo ou qualidade** — herdado de D8 do `conselho`: LLM não decide o próprio gasto.
- **"Publicar mesmo assim" (`--force`/`--skip-qc`)** — o gate que tem bypass não é gate.
- **Escrever direto na pasta do jogo durante a geração** — quebra hot-reload e deixa lixo parcial.
- **Gerar `LOD` a partir de decimate cego na Rota B** — decimate destrói silhouette de mesh gerada;
  LOD de mesh generativa é P5, com critério visual.
- **Animar via modelo generativo** — fora de escopo, custo desproporcional em 6 GB (D14).
- **Rodar a pipeline sobre `/mnt/c`** — I/O lento comprovado e `edit` já quebrou em UNC no `conselho`.
- **YAML como formato de manifesto de saída** — consumidor precisa de parse estrito e hash estável; JSON.

## 4. Em aberto (não decidido)

| # | Pergunta | Quando fecha | Bloqueia |
|---|---|---|---|
| Q1 | Nome definitivo do produto (`forge3d` é provisório) | antes de publicar o pacote | nada — é reversível |
| ~~Q2~~ | **Resolvida em 10/11/2026 por D23** — allowlist em arquivo global, sandbox próprio liberado, sem bypass | — | — |
| ~~Q3~~ | **Resolvida em 11/11/2026 por D62/C15** — escala: o importador usa **1 unidade glTF = 1 stud** (medido), o `.rbxlx` usa 0,28 m/stud e o glb declara a unidade em `unidades_export`; package e `.rbxlx` medem **6,6071 studs** (D68 fechou o resíduo). Animação e retarget seguem em P5, não em Q3 | — | — |
| Q4 | Biblioteca de WFC para `modular` | P4 | Rota C |
| ~~Q5~~ | **Resolvida em 10/11/2026 por D27** — SF3D encerrado em 6 GB; TripoSR (MIT) é o i23d da P3 | — | — |
| ~~Q6~~ | **Resolvida em 10/11/2026 por D24** — estado central em `$FORGE3D_HOME`, nada no repo do jogo | — | — |
| Q7 | Assets versionados no git do jogo: direto × Git LFS | antes do primeiro asset real no GameZero | nada técnico |
| Q8 | Qualidade do reconstructor para personagem com capa: TripoSR × SF3D | P3 fechada para prop (bule) com TripoSR; A/B de 10 assets e personagem continuam abertos | Rota `mesh`, D18 |
| ~~Q9~~ | **Resolvida em 11/11/2026 por D57** — delegação no `agentapi`, que exige a IDE aberta; sem chave de API e sem caminho headless | — | — |

## 5. Herdado do projeto `conselho` (aplicado aqui)

| Origem | Regra que vale aqui |
|---|---|
| D3 · D8 | local é executor; roteamento e custo são determinísticos, nunca decisão de LLM |
| D19 | ledger histórico (append-only, não lido) ≠ estado canônico (sobrescrito, curto, regenerado) |
| D23 | conselho só onde **não há oráculo** — ver [`CONSELHOS.md`](CONSELHOS.md) §1 |
| D24 | autoridade: decisão humana > código + teste > documento por data |
| D25 | teste verde = consistência, não correção → por isso D7 separa D1/D2/D3 |
| D26 | mudança de rumo exige critério escrito **antes** e custo na conta |
