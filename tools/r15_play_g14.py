"""Harness Play-mode Roblox Studio para Gate G14 via StudioMCP (LoadAnimation + RunService).

Uso:
    python tools/r15_play_g14.py --place <rbxlx> --clipe walk [--datamodel Client] [--auto-play] [--model-id 120880990771470]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from xml.etree import ElementTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mcp_studio import Cliente  # noqa: E402

from forge3d import rbx  # noqa: E402

logger = logging.getLogger(__name__)
_LUA_SCRIPT = Path(__file__).with_name("r15_play_g14.lua")


def _normalizar_model_id(raw_id: str) -> int:
    limpo = str(raw_id).strip()
    if limpo.startswith("rbxassetid://"):
        limpo = limpo[len("rbxassetid://") :].strip()
    if not limpo.isdigit() or int(limpo) <= 0:
        raise SystemExit(f"G14: --model-id invalido '{raw_id}' (esperado ID numerico)")
    return int(limpo)


def _verificar_place(place_path: str, clipe: str, model_id_arg: str | None) -> None:
    place = rbx.ler_place(place_path)
    nomes = [c["nome"] for c in place.get("clipes") or []]
    if clipe not in nomes:
        raise SystemExit(f"G14: clipe '{clipe}' ausente no place (disponiveis: {nomes})")
    if not place.get("partes") and not model_id_arg:
        raiz = ElementTree.parse(Path(place_path)).getroot()
        tem_loader = any(
            el.get("class") == "Script"
            and (el.findtext("Properties/string[@name='Name']") or "") == "Forge3DLoadModel"
            for el in raiz.iter("Item")
        )
        if not tem_loader:
            raise SystemExit(
                "G14: place sem partes R15 nem Forge3DLoadModel; informe --model-id <id>"
            )


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
        + "local ok, ang, pos, moved = verificarG14Play(mdl, seq)\n"
        + "return string.format('%s max_ang_deg=%.2f max_pos_studs=%.4f moved=%d', "
        + "ok and 'G14_PLAY_PASS' or 'G14_PLAY_FAIL', ang, pos, moved)\n"
    )


def _luau_carregar_modelo_servidor(model_id_num: int) -> str:
    return (
        'local InsertService = game:GetService("InsertService")\n'
        'local antigo = workspace:FindFirstChild("_G14TestModel")\n'
        "if antigo then antigo:Destroy() end\n"
        f"local container = InsertService:LoadAsset({model_id_num})\n"
        'local mdl = container:FindFirstChildOfClass("Model")\n'
        "if mdl ~= nil then\n"
        "    mdl.Parent = workspace\n"
        "    container:Destroy()\n"
        "else\n"
        "    mdl = container\n"
        "end\n"
        'mdl.Name = "_G14TestModel"\n'
        'local root = mdl.PrimaryPart or mdl:FindFirstChildWhichIsA("BasePart", true)\n'
        "if root ~= nil then\n"
        "    if mdl.PrimaryPart == nil then mdl.PrimaryPart = root end\n"
        "    root.Anchored = true\n"
        "end\n"
        'local ctrl = mdl:FindFirstChildOfClass("Humanoid") '
        'or mdl:FindFirstChildOfClass("AnimationController")\n'
        "if ctrl == nil then\n"
        '    ctrl = Instance.new("AnimationController")\n'
        '    ctrl.Name = "AnimationController"\n'
        "    ctrl.Parent = mdl\n"
        "end\n"
        'local anim = ctrl:FindFirstChildOfClass("Animator")\n'
        "if anim == nil then\n"
        '    anim = Instance.new("Animator")\n'
        "    anim.Parent = ctrl\n"
        "end\n"
        "mdl.Parent = workspace\n"
        "return 'G14_MODEL_READY'\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Valida Gate G14 em Play mode no Studio via MCP")
    parser.add_argument("--place", help="Caminho para o .rbxlx")
    parser.add_argument("--clipe", default="walk", help="Nome do KeyframeSequence a validar")
    parser.add_argument("--datamodel", default="Client", choices=["Edit", "Client", "Server"])
    parser.add_argument("--auto-play", action="store_true", help="Inicia/para Play mode via StudioMCP")
    parser.add_argument("--model-id", help="Carrega Model publicado no Server antes da probe Client")
    args = parser.parse_args(argv)

    if not args.place and not args.model_id:
        parser.error("informe --place <rbxlx> ou --model-id <id>")
    if args.place:
        _verificar_place(args.place, args.clipe, args.model_id)
    model_id_num = _normalizar_model_id(args.model_id) if args.model_id else None

    codigo = montar_codigo_g14(args.clipe)
    cliente = Cliente()
    sid: str | None = None
    play_started = False
    model_spawned = False
    try:
        cliente.abrir()
        sid = cliente.studio_id(tentativas=15)
        if not sid:
            print("nenhum Studio conectado (MCP ligado?)")
            return 1
        if args.auto_play:
            cliente.chamar("start_stop_play", {"studio_id": sid, "is_start": True}, timeout=60)
            play_started = True
            time.sleep(2.0)
        if model_id_num is not None:
            resp_srv = cliente.luau(
                _luau_carregar_modelo_servidor(model_id_num), sid, datamodel="Server"
            )
            if "G14_MODEL_READY" not in resp_srv:
                print(f"G14_PLAY_FAIL server_load={resp_srv}")
                return 2
            model_spawned = True
            time.sleep(0.5)
        saida = cliente.luau(codigo, sid, datamodel=args.datamodel)
        print(saida)
        return 0 if "G14_PLAY_PASS" in saida else 2
    finally:
        if model_spawned and sid:
            try:
                cliente.luau(
                    "local m = workspace:FindFirstChild('_G14TestModel'); if m then m:Destroy() end; return 'OK'",
                    sid,
                    datamodel="Server",
                )
            except (OSError, RuntimeError, ValueError) as exc:
                logger.warning("G14: falha ao remover _G14TestModel no Server: %s", exc)
        if play_started and sid:
            try:
                cliente.chamar("start_stop_play", {"studio_id": sid, "is_start": False}, timeout=60)
            except (OSError, RuntimeError, ValueError) as exc:
                logger.warning("G14: falha ao parar Play mode: %s", exc)
        cliente.fechar()


if __name__ == "__main__":
    raise SystemExit(main())
