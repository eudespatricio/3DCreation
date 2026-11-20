"""Exportador de place ``.rbxlx`` pronto para Play usando ``Model`` publicado no Roblox."""

from __future__ import annotations

from collections.abc import Mapping
from html import escape
import json
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from . import animacao, config, paths, upload
from .errors import erro_spec
from .rbx_anim import _sequencia_xml
from .rbx_xml import _cframe, _vec

_LUAU_LOAD_MODEL = """\
local InsertService = game:GetService("InsertService")
local MODEL_ID = {model_id}
local container = InsertService:LoadAsset(MODEL_ID)
local modelo = container:FindFirstChildOfClass("Model")
if modelo ~= nil then
    modelo.Parent = workspace
    container:Destroy()
else
    modelo = container
end
modelo.Name = "Forge3DR15"
local rootPart = modelo.PrimaryPart
    or modelo:FindFirstChild("HumanoidRootPart")
    or modelo:FindFirstChildWhichIsA("BasePart", true)
if rootPart ~= nil then
    if modelo.PrimaryPart == nil then modelo.PrimaryPart = rootPart end
    rootPart.Anchored = true
end
local controller = modelo:FindFirstChildOfClass("Humanoid")
    or modelo:FindFirstChildOfClass("AnimationController")
if controller == nil then
    controller = Instance.new("AnimationController")
    controller.Name = "AnimationController"
    controller.Parent = modelo
end
local animator = controller:FindFirstChildOfClass("Animator")
if animator == nil then
    animator = Instance.new("Animator")
    animator.Parent = controller
end
modelo.Parent = workspace
modelo:SetAttribute("Forge3DModelReady", true)
"""

_LUAU_PLAY_ANIM = """\
local KeyframeSequenceProvider = game:GetService("KeyframeSequenceProvider")
local DEFAULT_CLIP = {clipe_padrao}
local modelo = workspace:WaitForChild("Forge3DR15")
while not modelo:GetAttribute("Forge3DModelReady") do
    modelo:GetAttributeChangedSignal("Forge3DModelReady"):Wait()
end
local controller = modelo:FindFirstChildOfClass("Humanoid")
    or modelo:FindFirstChildOfClass("AnimationController")
    or modelo:WaitForChild("AnimationController", 10)
if controller == nil then return end
local animator = controller:FindFirstChildOfClass("Animator")
    or controller:WaitForChild("Animator", 10)
if animator == nil then return end
local kfs = workspace:FindFirstChild(DEFAULT_CLIP)
if not (kfs and kfs:IsA("KeyframeSequence")) then
    kfs = workspace:FindFirstChildOfClass("KeyframeSequence")
end
if kfs == nil then return end
local anim = Instance.new("Animation")
anim.Name = "Forge3DAnim"
anim.AnimationId = KeyframeSequenceProvider:RegisterKeyframeSequence(kfs)
local track = animator:LoadAnimation(anim)
track.Looped = kfs.Loop
track.Priority = Enum.AnimationPriority.Action
track:Play(0.0, 1.0, 1.0)
"""


def resolver_model_id(
    model_id: str | int,
    item_id: str,
    ledger: str | Path | bool | None = True,
) -> str:
    """Resolve ``model_id`` numerico ou ``'auto'`` via ledger para ``item_id``."""
    if isinstance(model_id, bool):
        raise erro_spec("export-r15: model_id invalido (bool)")
    bruto = str(model_id).strip()
    if not bruto:
        raise erro_spec("export-r15: model_id vazio")

    if bruto.lower() == "auto":
        if ledger is False:
            raise erro_spec(
                f"export-r15: model_id='auto' para '{item_id}' exige ledger habilitado (remova --no-ledger)"
            )
        caminho_ledger: str | Path | None = None if isinstance(ledger, bool) else ledger
        mapa_ledger = upload.resolver_ledger(caminho_ledger, asset_id=item_id)
        escolhido = next(
            (mapa_ledger[(item_id, r)] for r in ("model", "Model", "mesh", "") if (item_id, r) in mapa_ledger),
            None,
        )
        if not escolhido:
            raise erro_spec(
                f"export-r15: model_id='auto' nao encontrado no ledger para '{item_id}' "
                "(passe --model-id <id> ou execute forge3d upload-model)"
            )
        bruto = escolhido

    if bruto.startswith("rbxassetid://"):
        bruto = bruto[len("rbxassetid://") :].strip()
    if not bruto.isdigit() or int(bruto) <= 0:
        raise erro_spec(f"export-r15: model_id invalido '{model_id}' (esperado ID numerico ou 'auto')")
    return str(int(bruto))


def exportar_r15_model(
    item: Mapping[str, Any],
    perfil: Mapping[str, Any],
    item_id: str,
    esqueleto_item: str,
    mps: float,
    model_id: str | int,
    *,
    saida: str | Path | None = None,
    ledger: str | Path | bool | None = True,
) -> dict[str, Any]:
    """Gera ``.rbxlx`` com ``KeyframeSequence`` + loader Server + player Client via ``model_id``."""
    model_id_num = resolver_model_id(model_id, item_id, ledger=ledger)
    pedidos_anim = (
        item.get("animacoes_base")
        or item.get("clipes")
        or ([str(a["nome"]) for a in (item.get("animacoes") or []) if isinstance(a, Mapping) and a.get("nome")] or None)
    )
    clipes = animacao.clipes(dict(perfil), str(esqueleto_item or "r15@1"), pedidos_anim)
    nomes_clipes = [c["nome"] for c in clipes]
    clipe_padrao = "walk" if "walk" in nomes_clipes else (nomes_clipes[0] if nomes_clipes else "walk")

    linhas = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<roblox version="4">',
        '<Item class="Workspace" referent="RBX0">',
        "<Properties>",
        '<string name="Name">Workspace</string>',
        "</Properties>",
    ]
    ref_idx = 1
    for clipe in clipes:
        clipe_action = {**clipe, "priority": max(2, int(clipe.get("priority", 2)))}
        itens, ref_idx = _sequencia_xml(clipe_action, ref_idx, mps=mps)
        linhas += itens

    linhas += [
        f'<Item class="Part" referent="RBX{ref_idx}">',
        "<Properties>",
        '<string name="Name">Baseplate</string>',
        '<bool name="Anchored">true</bool>',
        '<Color3uint8 name="Color3uint8">5404741</Color3uint8>',
        *_vec("size", 40.0, 1.0, 40.0),
        *_cframe("CFrame", 0.0, -0.5, 0.0),
        "</Properties>",
        "</Item>",
        "</Item>",
    ]
    ref_idx += 1

    src_load = escape(_LUAU_LOAD_MODEL.format(model_id=model_id_num))
    src_play = escape(_LUAU_PLAY_ANIM.format(clipe_padrao=json.dumps(clipe_padrao)))
    linhas += [
        f'<Item class="ServerScriptService" referent="RBX{ref_idx}">',
        '<Properties><string name="Name">ServerScriptService</string></Properties>',
        f'<Item class="Script" referent="RBX{ref_idx + 1}">',
        '<Properties><string name="Name">Forge3DLoadModel</string><bool name="Disabled">false</bool>'
        f'<ProtectedString name="Source">{src_load}</ProtectedString></Properties>',
        "</Item>",
        "</Item>",
        f'<Item class="StarterPlayer" referent="RBX{ref_idx + 2}">',
        '<Properties><string name="Name">StarterPlayer</string></Properties>',
        f'<Item class="StarterPlayerScripts" referent="RBX{ref_idx + 3}">',
        '<Properties><string name="Name">StarterPlayerScripts</string></Properties>',
        f'<Item class="LocalScript" referent="RBX{ref_idx + 4}">',
        '<Properties><string name="Name">Forge3DPlayAnim</string><bool name="Disabled">false</bool>'
        f'<ProtectedString name="Source">{src_play}</ProtectedString></Properties>',
        "</Item>",
        "</Item>",
        "</Item>",
        "</roblox>",
    ]

    xml = "\n".join(linhas) + "\n"
    ElementTree.fromstring(xml)
    destino = (paths.dir_saida() / "r15" / f"{item_id}.rbxlx") if saida is None else config.normalizar(saida)
    if saida is not None:
        config.validar_destino(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(xml, encoding="utf-8")

    return {
        "ok": True,
        "saida": str(destino),
        "item": item_id,
        "bytes": destino.stat().st_size,
        "partes": 0,
        "motores": 0,
        "attachments": 0,
        "clipes": nomes_clipes,
        "animacoes": nomes_clipes,
        "keyframes": {c["nome"]: len(c.get("chaves") or []) for c in clipes},
        "model_id": model_id_num,
        "modo_rig": "model",
        "metros_por_stud": mps,
        "textura": False,
    }
