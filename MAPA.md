# MAPA — onde cada responsabilidade mora
> Teto: 60 linhas. Se um caminho não estiver aqui, procure antes de editar.

| Caminho | O que tem | Quando carregar |
|---|---|---|
| `CONTINUAR.md` | fase, próximos passos, como retomar | sessão nova, sempre primeiro |
| `DECISOES.md` §1–§2 | fatos medidos + decisões firmadas | antes de propor mudança de rumo |
| `DECISOES.md` §4 | perguntas ainda abertas (Q1–Q7) | quando a resposta não estiver decidida |
| `INVARIANTES.md` | regras cujo desrespeito é bug, com comando de verificação | antes de concluir qualquer tarefa |
| `CONSELHOS.md` | quando convocar conselho e como ele decide | decisão irreversível ou sem oráculo |
| `docs/arquitetura.md` | fluxo, camadas, fronteiras | desenhar/alterar etapa do pipeline |
| `docs/contratos.md` | spec, manifesto, exit codes, códigos de erro | mexer na fronteira com o jogo |
| `docs/rotas-e-providers.md` | as 4 rotas, interface de provider, roteamento | adicionar gerador novo |
| `docs/perfis-export.md` | `godot4` e `roblox-r15`: eixos, escala, rig, colisão | exportar ou integrar no jogo |
| `docs/qc-e-verificacao.md` | gates G1–G9, severidade, remediação | asset reprovado no QC |
| `docs/dependencias.md` | versões pinadas, o que instalar, o que não instalar | `doctor` falhou / montar ambiente |
| `docs/riscos-e-licencas.md` | VRAM, licenças de modelo, IP, tabela de modelos 6 GB | escolher modelo ou publicar |
| `docs/roadmap.md` | P0–P6 com portão de saída por fase | planejar próxima fase |
| `docs/gaps.md` | lacunas abertas com dono e condição de fechamento | fim de fase |
| `schemas/spec.v1.schema.json` | contrato de entrada (fonte de verdade) | validar lote |
| `schemas/manifest.v1.schema.json` | contrato de saída (fonte de verdade) | consumir asset no jogo |
| `profiles/godot4.yaml` | perfil de export Godot 4 | exportar para Godot |
| `profiles/roblox-r15.yaml` | perfil de export Roblox (R15/blocky) | exportar para Roblox |
| `examples/lote_01.yaml` | lote de referência, executável | exemplo canônico e fixture de teste |
| `tools/check-p0.py` | portão do P0: schemas, exemplos, tetos, I12, I14 | antes de dizer "P0 fechada" |
| `tools/render_preview.py` | preview headless (Cycles): frente, 3/4, `--pose` | revisar qualidade do asset |
| `docs/preview/` | renders de referência do android (v1, final, pose) | mostrar qualidade a quem não abre o jogo |
| `skills/context-recovery/` | protocolo de recuperação de contexto + templates | assumir projeto herdado / auditar |
| `src/forge3d/` | `spec` `plan` `qc` `publish` `pipeline` `doctor` `locks` `canonical` `config` `paths` | implementação |
| `src/forge3d/cli/` | `comandos.py` (7 subcomandos) + `main.py` | contrato CLI |
| `src/forge3d/providers/` | `base` `blocky` `importer` | adicionar rota |
| `src/forge3d/post.py` + `blender/postprocess.py` | subprocesso + script `bpy` | pós-processo, LOD, colisor, rig |
| `tests/` | `tests/test_unidade.py` + `tests/invariants/test_invariantes_e2e.py` | portão de CI |
| `$FORGE3D_HOME` | `cache` `runs` `staging` `locks` `indice.sqlite` `ledger.jsonl` `saida/` | depurar run |
| `~/.config/forge3d/allowlist.yaml` | destinos autorizados (D23) | publicar em projeto de jogo |

## Armadilhas conhecidas

1. **Blender 4.2 usa Python 3.11 embutido.** `pip install` nele contamina o interpretador do DCC e
   quebra na próxima atualização. Scripts `bpy` recebem dados por arquivo JSON, nunca por stdout (I9).
2. **`/mnt/c` e UNC são armadilha dupla:** I/O lento e `edit` falha com `GetFileSecurityW EIO` — já aconteceu no
   projeto `conselho` e foi reproduzido aqui em 10/11/2026. Use `write`/`sed` por WSL. Tudo roda em ext4 sob `/home` (I12).
3. **Python 3.14 é o do sistema e não serve** para o stack ML (`torch` não publica wheel). Use 3.12 do
   `uv`; 3.11/3.12 já estão instalados localmente.
4. **6 GB de VRAM não comportam dois modelos residentes.** Sem o lock (I6), o sintoma é `CUDA OOM`
   intermitente que parece bug de código.
5. **`ollama` mede 4.096 tokens de contexto efetivo**, não 32k (medido no `conselho`). Prompt de
   `draft` tem que caber nisso, ou o resultado sai truncado em silêncio.
6. **Diffusion não é determinístico entre versões de driver/modelo.** Só a rota `blocky` pode ser
   byte-idêntica (I1). Prometer D1 para `mesh` é mentir para o CI.
7. **Nome de franquia é passivo jurídico.** `minecraft_bedrock` foi aceito como alias legado, mas o
   valor canônico é `blocky_voxel` (I14).
8. **Alterou a saída de um provider sem subir `VERSAO`?** O cache serve o artefato velho e o QC
   passa. Mudou geometria/atlas ⇒ suba a versão do provider — ela entra na chave de cache (D6).
9. **G1 solda antes de contar não-manifold.** glTF divide vértice em cada costura de UV; sem soldar,
   todo asset importado parece ter borda aberta. O gate mede topologia soldada de propósito.
10. **Sobreponha o pivô, nunca compartilhe canto exato:** encostar abre fenda ao animar e canto
    exato vira não-manifold no G1 após a solda. **Joelho e cotovelo giram ao contrário:** local X
    negativo dobra o joelho, positivo dobra o cotovelo — sinal igual nos dois inverte o membro.
