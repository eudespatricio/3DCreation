"""Delega uma tarefa a outro agente (Gemini Flash via `agentapi` do Antigravity) e valida a resposta.

Lema: dividir para conquistar — mas **dividir por tipo de trabalho**, não por conveniência.

O que este script garante:
* só aceita tarefas de tipo delegável (`TIPOS_OK`); tarefa com oráculo é recusada com motivo;
* a resposta é **dado**, não instrução: precisa vir em JSON e passar nas exigências declaradas;
* tudo é registrado em `$FORGE3D_HOME/delegacoes/` com hash do prompt (proveniência).

Uso:
    python tools/delegar.py --tipo pesquisa --brief brief.md --exigir campo1,campo2 --json
    python tools/delegar.py --tipo segunda_opiniao --texto "..." --modelo flash
    python tools/delegar.py --tipo pesquisa --brief brief.md --dry-run   # imprime o brief, nao chama

Dependência: `agentapi` (vem com o Antigravity) e `ANTIGRAVITY_LS_ADDRESS` apontando para o language
server no ar — na prática, com o Antigravity aberto. Ver docs/delegacao.md.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from forge3d import paths  # noqa: E402

EXIT_OK = 0
EXIT_USO = 2
EXIT_AMBIENTE = 4
EXIT_RESPOSTA = 5

#: tarefas que podem ser delegadas: nenhuma tem oráculo determinístico e todas são reversíveis
TIPOS_OK = {
    "pesquisa": "levantar fontes e números com URL, sem decidir o que fazer com eles",
    "redacao_doc": "escrever ou traduzir prosa a partir de fatos já registrados",
    "revisao_prosa": "apontar contradição e ambiguidade em texto",
    "variantes_nome": "propor nomes/tags neutros, sem franquia (I14)",
    "prompt_concept": "descrever prompt de imagem a partir de uma ficha de personagem",
    "segunda_opiniao": "criticar um desenho já registrado, com critério explícito",
}

#: tarefas que NUNCA são delegadas: têm oráculo, contrato ou consequência irreversível
TIPOS_PROIBIDOS = {
    "qc": "o QC é oráculo medido no arquivo exportado (I5); opinião não substitui medição",
    "schema": "contrato é versionado e quebra pipe de terceiro (D20); só humano decide",
    "invariante": "invariante vira teste; delegar transforma regra em opinião",
    "publish": "escrita em destino de projeto exige allowlist e revisão (D23)",
    "codigo_pipeline": "código com determinismo D1 precisa de teste, não de segunda opinião",
}

MODELOS = ("flash", "flash_lite", "pro")


def _agora() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _agentapi() -> str:
    for cand in (
        os.environ.get("FORGE3D_AGENTAPI"),
        shutil.which("agentapi"),
        str(Path.home() / ".gemini" / "antigravity" / "bin" / "agentapi"),
    ):
        if cand and Path(cand).is_file():
            return str(cand)
    raise SystemExit("[FORGE-E-AMBIENTE] agentapi nao encontrado (esperado em ~/.gemini/antigravity/bin)")


def _endereco_ls() -> str:
    endereco = os.environ.get("ANTIGRAVITY_LS_ADDRESS", "").strip()
    if not endereco:
        raise SystemExit(
            "[FORGE-E-AMBIENTE] ANTIGRAVITY_LS_ADDRESS nao definido. O `agentapi` fala com o language "
            "server do Antigravity: abra o Antigravity (a extensao exporta o endereco) ou suba o server "
            "headless. Ver docs/delegacao.md §4."
        )
    return endereco


def montar_prompt(brief: str, tipo: str, exigir: list[str]) -> str:
    campos = ", ".join(f'"{c}"' for c in exigir) if exigir else '"resposta"'
    return (
        f"{brief.strip()}\n\n"
        "--- REGRAS DE SAIDA ---\n"
        f"Tipo de tarefa: {tipo}. ({TIPOS_OK.get(tipo, '')})\n"
        "Responda APENAS com um objeto JSON de uma linha, sem markdown e sem comentário, "
        f"contendo exatamente as chaves: {campos}.\n"
        "Se não souber um valor, use null — nunca invente número: marque estimativa como \"[estimado]\"."
    )


def extrair_json(texto: str) -> dict:
    """Aceita JSON puro ou cercado de texto/markdown. Devolve o primeiro objeto válido."""
    texto = texto.strip()
    try:
        return json.loads(texto)
    except ValueError:
        pass
    for bloco in re.findall(r"```(?:json)?\s*(.+?)```", texto, flags=re.S):
        try:
            return json.loads(bloco.strip())
        except ValueError:
            continue
    inicio, fim = texto.find("{"), texto.rfind("}")
    if inicio >= 0 and fim > inicio:
        try:
            return json.loads(texto[inicio : fim + 1])
        except ValueError:
            pass
    raise SystemExit(f"[FORGE-E-RESPOSTA] resposta sem JSON valido:\n{texto[:600]}")


def _brain(conv_id: str) -> Path:
    return Path.home() / ".gemini" / "antigravity" / "brain" / conv_id


def _passos(conv_id: str) -> list[Path]:
    """Saidas dos passos do agente, em ordem numerica."""
    base = _brain(conv_id) / ".system_generated" / "steps"
    if not base.is_dir():
        return []
    return sorted(
        (p for p in base.iterdir() if p.is_dir() and p.name.isdigit()),
        key=lambda p: int(p.name),
    )


def _esperar_resposta(conv_id: str, timeout: int) -> str:
    """O `agentapi` cria uma sessao agentica: a resposta final aparece nos passos do brain."""
    fim = time.monotonic() + timeout
    ultimo = ""
    while time.monotonic() < fim:
        for passo in reversed(_passos(conv_id)):
            try:
                texto = (passo / "output.txt").read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if texto.strip():
                ultimo = texto
                break
        if ultimo and ("{" in ultimo and "}" in ultimo):
            return ultimo
        time.sleep(3)
    if ultimo:
        return ultimo
    raise SystemExit(
        f"[FORGE-E-RESPOSTA] nenhuma saida em {timeout}s. A sessao existe, mas o agente pode estar "
        f"executando ferramentas. Veja ~/.gemini/antigravity/brain/{conv_id}/"
    )


def chamar(agentapi: str, modelo: str, prompt: str, titulo: str, timeout: int) -> tuple[str, str]:
    """Cria a conversa e devolve ``(conversation_id, texto_da_resposta)``.

    ATENCAO: `new-conversation` abre uma **sessao agentica** (pode executar ferramentas), nao um
    endpoint de completude. Ver docs/delegacao.md §9.
    """
    cmd = [agentapi, "new-conversation", f"--model={modelo}", f"--title={titulo}", prompt]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise SystemExit(f"[FORGE-E-RESPOSTA] timeout de {timeout}s criando a conversa") from exc
    if proc.returncode != 0:
        raise SystemExit(f"[FORGE-E-AMBIENTE] agentapi rc={proc.returncode}: {proc.stderr[-400:]}")
    try:
        envelope = json.loads(proc.stdout)
        conv_id = envelope["response"]["newConversation"]["conversationId"]
    except (ValueError, KeyError):
        raise SystemExit(
            f"[FORGE-E-RESPOSTA] resposta inesperada do agentapi: {proc.stdout[:400]!r}"
        ) from None
    print(f"[delegar] conversa {conv_id} criada; aguardando resposta...", file=sys.stderr)
    return conv_id, _esperar_resposta(conv_id, timeout)


def registrar(registro: dict) -> Path:
    destino = paths.raiz_estado() / "delegacoes"
    destino.mkdir(parents=True, exist_ok=True)
    nome = f"{registro['quando'].replace(':', '')}-{registro['tipo']}.json"
    caminho = destino / nome
    caminho.write_text(json.dumps(registro, sort_keys=True, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return caminho


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="delegar", description="Delega tarefa sem oráculo a outro agente.")
    p.add_argument("--tipo", required=True, help=f"um de: {', '.join(TIPOS_OK)}")
    grupo = p.add_mutually_exclusive_group(required=True)
    grupo.add_argument("--brief", help="arquivo com o briefing completo")
    grupo.add_argument("--texto", help="briefing inline")
    p.add_argument("--modelo", default="flash", choices=MODELOS)
    p.add_argument("--exigir", default="", help="chaves obrigatorias na resposta, separadas por virgula")
    p.add_argument("--titulo", default="forge3d delegacao")
    p.add_argument("--timeout", type=int, default=300)
    p.add_argument("--dry-run", action="store_true", help="imprime o prompt e nao chama o agente")
    p.add_argument("--json", action="store_true", help="imprime a resposta validada em JSON")
    args = p.parse_args(argv)

    if args.tipo in TIPOS_PROIBIDOS:
        print(
            f"[FORGE-E-USO] tarefa '{args.tipo}' nao e delegavel: {TIPOS_PROIBIDOS[args.tipo]}",
            file=sys.stderr,
        )
        return EXIT_USO
    if args.tipo not in TIPOS_OK:
        print(f"[FORGE-E-USO] tipo desconhecido. Delegaveis: {', '.join(TIPOS_OK)}", file=sys.stderr)
        return EXIT_USO

    brief = Path(args.brief).read_text(encoding="utf-8") if args.brief else args.texto
    if not brief or not brief.strip():
        print("[FORGE-E-USO] briefing vazio", file=sys.stderr)
        return EXIT_USO

    exigir = [c.strip() for c in args.exigir.split(",") if c.strip()]
    prompt = montar_prompt(brief, args.tipo, exigir)

    if args.dry_run:
        print(prompt)
        print("\n--- dry-run: nada foi enviado ---", file=sys.stderr)
        return EXIT_OK

    agentapi = _agentapi()
    _endereco_ls()  # falha cedo e com instrucao se o server nao estiver no ar
    conv_id, bruto = chamar(agentapi, args.modelo, prompt, args.titulo, args.timeout)
    resposta = extrair_json(bruto)

    faltando = [c for c in exigir if c not in resposta]
    if faltando:
        registrar(
            {
                "quando": _agora(),
                "tipo": args.tipo,
                "modelo": args.modelo,
                "tarefa": args.titulo,
                "prompt": prompt,
                "resposta_bruta": bruto,
                "valido": False,
                "faltando": faltando,
            }
        )
        print(f"[FORGE-E-RESPOSTA] faltam chaves: {', '.join(faltando)}", file=sys.stderr)
        return EXIT_RESPOSTA

    caminho = registrar(
        {
            "quando": _agora(),
            "tipo": args.tipo,
            "modelo": args.modelo,
            "tarefa": args.titulo,
            "prompt": prompt,
            "resposta": resposta,
            "valido": True,
        }
    )
    if args.json:
        print(json.dumps(resposta, sort_keys=True, indent=1, ensure_ascii=False))
    else:
        print(f"delegado a {args.modelo}; registro em {caminho}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
