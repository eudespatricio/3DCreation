"""Harness Play-mode Roblox Studio para Gate G14 via StudioMCP (LoadAnimation + RunService).

Uso:
    python tools/r15_play_g14.py --place <rbxlx> --clipe walk [--datamodel Client]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mcp_studio import Cliente  # noqa: E402

from forge3d import rbx  # noqa: E402

_LUA_SCRIPT = Path(__file__).with_name("r15_play_g14.lua")


def montar_codigo_g14(clipe_nome: str) -> str:
    """Constroi o script Luau de verificacao Play-mode G14 com RunService e LoadAnimation."""
    corpo = _LUA_SCRIPT.read_text(encoding="utf-8").split("\nreturn {", 1)[0].rstrip()
    return (
        f"local CLIPE_NOME = {json.dumps(clipe_nome)}\n"
        + corpo
        + "\nlocal mdl = encontrarModeloR15()\n"
        + "local seq = workspace:FindFirstChild(CLIPE_NOME, true)\n"
        + "if not (mdl and seq and seq:IsA('KeyframeSequence')) then\n"
        + "    return 'G14_PLAY_FAIL missing_model_or_keyframe_sequence'\n"
        + "end\n"
        + "local ok, ang, pos = verificarG14Play(mdl, seq)\n"
        + "return string.format('%s ang=%.2f pos=%.4f', ok and 'G14_PLAY_PASS' or 'G14_PLAY_FAIL', ang, pos)\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Valida Gate G14 em Play mode no Studio via MCP")
    parser.add_argument("--place", required=True, help="Caminho para o .rbxlx")
    parser.add_argument("--clipe", default="walk", help="Nome do KeyframeSequence a validar")
    parser.add_argument("--datamodel", default="Client", choices=["Edit", "Client", "Server"])
    args = parser.parse_args(argv)

    place = rbx.ler_place(args.place)
    nomes = [c["nome"] for c in place.get("clipes") or []]
    if args.clipe not in nomes:
        raise SystemExit(f"G14: clipe '{args.clipe}' ausente no place (disponiveis: {nomes})")

    codigo = montar_codigo_g14(args.clipe)
    cliente = Cliente()
    try:
        cliente.abrir()
        sid = cliente.studio_id(tentativas=15)
        if not sid:
            print("nenhum Studio conectado (MCP ligado?)")
            return 1
        saida = cliente.luau(codigo, sid, datamodel=args.datamodel)
        print(saida)
        return 0 if "G14_PLAY_PASS" in saida else 2
    finally:
        cliente.fechar()


if __name__ == "__main__":
    raise SystemExit(main())
