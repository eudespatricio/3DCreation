# MAPA — onde cada responsabilidade mora
> Teto: 60 linhas. Se um caminho não estiver aqui, procure antes de editar.

| Caminho | O que tem | Quando carregar |
|---|---|---|
| `CONTINUAR.md` | fase, próximos passos, como retomar | sessão nova, sempre primeiro |
| `DECISOES.md` §1–§2 | fatos medidos + decisões firmadas | antes de propor mudança de rumo |
| `DECISOES.md` §4 | perguntas ainda abertas (Q1–Q8) | quando a resposta não estiver decidida |
| `INVARIANTES.md` | regras cujo desrespeito é bug, com comando de verificação | antes de concluir qualquer tarefa |
| `CONSELHOS.md` | quando convocar conselho e como ele decide | decisão irreversível ou sem oráculo |
| `docs/arquitetura.md` | fluxo, camadas, fronteiras | desenhar/alterar etapa do pipeline |
| `docs/contratos.md` | `spec@1`/`spec@2`, manifesto, exit codes, códigos de erro | mexer na fronteira com o jogo |
| `docs/rotas-e-providers.md` | as 4 rotas, interface de provider, roteamento | adicionar gerador novo |
| `docs/perfis-export.md` | `godot4` e `roblox-r15`: eixos, escala, rig, colisão | exportar ou integrar no jogo |
| `docs/qc-e-verificacao.md` | gates G1–G9, severidade, remediação, `verify` reexecutando | asset reprovado no QC |
| `docs/dependencias.md` | versões pinadas, venv i23d, o que instalar, o que não instalar | `doctor` falhou / montar ambiente |
| `docs/riscos-e-licencas.md` | VRAM, licenças de modelo, IP, tabela de modelos 6 GB | escolher modelo ou publicar |
| `docs/roadmap.md` | P0–P6 com portão de saída por fase | planejar próxima fase |
| `docs/gaps.md` | lacunas abertas com dono e condição de fechamento | fim de fase |
| `schemas/spec.v1.schema.json` · `schemas/spec.v2.schema.json` | contrato de entrada (fonte de verdade) | validar lote |
| `schemas/manifest.v1.schema.json` | contrato de saída (fonte de verdade) | consumir asset no jogo |
| `profiles/godot4.yaml` · `profiles/roblox-r15.yaml` | perfis de export | exportar para Godot/Roblox |
| `examples/lote_01.yaml` · `examples/lote_03_kit.yaml` · `examples/lote_04_mesh.yaml` · `examples/lote_05_mesh_concept.yaml` | fixtures: blocky, kit P3-D, mesh P3, concept P3.5 | exemplo canônico e fixture de teste |
| `examples/concepts/` | PNGs de entrada da rota `mesh` (teapot MIT) | rodar o exemplo mesh |
| `tools/check-p0.py` | portão do P0: schemas, exemplos, tetos, I12, I14 | antes de dizer "P0 fechada" |
| `tools/render_preview.py` · `docs/preview/` | preview headless e renders de referência | revisar qualidade do asset |
| `tools/i23d_infer.py` · `tools/concept_infer.py` · `tools/normalize_mesh.py` | inferência i23d, concept SD1.5 e normalização canônica | depurar rota mesh |
| `src/forge3d/` + `src/forge3d/cli/` | `spec` `plan` `qc` `publish` `pipeline` `doctor` `locks` `canonical` `config` `paths` + 7 subcomandos | implementação |
| `src/forge3d/providers/` | `base` `blocky` `importer` `mesh` | adicionar rota |
| `src/forge3d/post.py` + `blender/postprocess.py` | subprocesso + script `bpy` (LOD, colisor, rig, UV+bake) | pós-processo, textura, rig |
| `tests/` | `test_unidade.py` + `test_p3_bake.py` + `test_concept.py` + `invariants/` + `fixtures/` | portão de CI |
| `~/.venvs/concept` | venv do SD1.5/diffusers (cópia da i23d; pin de transformers diferente) | gerar concept |
| `$FORGE3D_HOME` | `cache` `runs` `staging` `locks` `indice.sqlite` `ledger.jsonl` `saida/` | depurar run |
| `~/.config/forge3d/allowlist.yaml` | destinos autorizados (D23) | publicar em projeto de jogo |

## Armadilhas conhecidas

1. **Blender 4.2 usa Python 3.11 embutido.** `pip install` nele contamina o DCC e quebra na próxima atualização; scripts `bpy` recebem dados por arquivo JSON, nunca por stdout (I9).
2. **`/mnt/c` e UNC são armadilha dupla:** I/O lento e `edit` falha com `GetFileSecurityW EIO`; use `write`/`sed` por WSL, tudo em ext4 sob `/home` (I12).
3. **Python 3.14 é o do sistema e não serve** para o stack ML (`torch` não publica wheel); use 3.12 do `uv`.
4. **6 GB de VRAM não comportam dois modelos residentes;** sem o lock (I6) o sintoma é `CUDA OOM` intermitente que parece bug.
5. **`ollama` mede 4.096 tokens de contexto efetivo**, não 32k; prompt de `draft` tem que caber nisso.
6. **Diffusion não é determinístico entre versões de driver/modelo;** só `blocky` pode ser byte-idêntico (I1).
7. **Nome de franquia é passivo jurídico;** `blocky_voxel`, nunca `minecraft_*` no manifesto (I14).
8. **Alterou a saída de um provider sem subir `VERSAO`?** O cache serve o artefato velho e o QC passa; a versão entra na chave (D6).
9. **G1 solda antes de contar não-manifold.** glTF divide vértice em cada costura de UV; sem soldar, todo asset importado parece ter borda aberta. O gate mede topologia soldada de propósito.
10. **Sobreponha o pivô, nunca compartilhe canto exato:** encostar abre fenda ao animar e canto exato vira não-manifold no G1 após a solda. **Joelho e cotovelo giram ao contrário:** local X negativo dobra o joelho, positivo dobra o cotovelo — sinal igual nos dois inverte o membro.
11. **Decimate cria ilha de uma face.** O TripoSR a 7.960 tris deixou um triângulo solto de 5,1e-6 m²; `reparar_malha` remove **toda** ilha de 1 face.
12. **Rota `mesh` exige `origem` (PNG);** o prompt não gera imagem enquanto GAP-026 não fecha. Fundo neutro/alfa ou `FORGE3D_I23D_REMOVER_FUNDO=1`.
