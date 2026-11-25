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
from .rbx_pbr import (
    _extrair_mapas_pbr_manifesto_dict,
    _normalizar_mapas_pbr,
    _resolver_asset_ids_pbr,
)
from .rbx_xml import JOINT_R15, PARENT_R15, _cframe, _vec

_LUAU_LOAD_HDR = """\
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
"""

_LUAU_LOAD_FTR = """\
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

_LUAU_LOAD_BONE_BODY = """\
local rootPart = modelo.PrimaryPart or modelo:FindFirstChild("HumanoidRootPart") or modelo:FindFirstChildWhichIsA("BasePart", true)
if rootPart ~= nil then
    if modelo.PrimaryPart == nil then modelo.PrimaryPart = rootPart end
    rootPart.Anchored = true
end
"""

_LUAU_ATTACHMENTS_RIGID = """\
local ATTS = {
    {"Head", "HatAttachment", 0, 0.5, 0}, {"Head", "HairAttachment", 0, 0.5, 0},
    {"UpperTorso", "BodyBackAttachment", 0, 0, 0.5}, {"UpperTorso", "BodyFrontAttachment", 0, 0, -0.5},
    {"UpperTorso", "LeftCollarAttachment", -0.5, 0.5, 0}, {"UpperTorso", "RightCollarAttachment", 0.5, 0.5, 0},
    {"LowerTorso", "WaistCenterAttachment", 0, 0, 0},
    {"RightHand", "RightGripAttachment", 0, -0.5, 0}, {"LeftHand", "LeftGripAttachment", 0, -0.5, 0},
}
for _, a in ipairs(ATTS) do
    local prt = partes[a[1]]
    if prt ~= nil and prt:FindFirstChild(a[2]) == nil then
        local att = Instance.new("Attachment")
        att.Name, att.Parent = a[2], prt
        att.Position = Vector3.new(prt.Size.X * a[3], prt.Size.Y * a[4], prt.Size.Z * a[5])
    end
end
"""

_LUAU_LOAD_MODEL_RIGID = """\
local PART_NAMES = {{
    "LowerTorso", "UpperTorso", "Head", "LeftUpperArm", "LeftLowerArm", "LeftHand",
    "RightUpperArm", "RightLowerArm", "RightHand", "LeftUpperLeg", "LeftLowerLeg", "LeftFoot",
    "RightUpperLeg", "RightLowerLeg", "RightFoot",
}}
local COLLIDE_PARTS = {{ LowerTorso = true, UpperTorso = true, HumanoidRootPart = true }}
local ANCORAS = {{
{ancoras_luau}
}}
local JOINTS = {{
{joints_luau}
}}
local LT_CENTER = Vector3.new({lt_cx:.6f}, {lt_cy:.6f}, {lt_cz:.6f})
local function findPart(root, nome)
    local d = root:FindFirstChild(nome, true)
    if d and d:IsA("BasePart") then return d end
    for _, desc in ipairs(root:GetDescendants()) do
        if desc:IsA("BasePart") and (desc.Name == nome or string.sub(desc.Name, -(#nome + 1)) == "/" .. nome) then
            return desc
        end
    end
    return nil
end
local partes = {{}}
for _, nome in ipairs(PART_NAMES) do
    local p = findPart(modelo, nome)
    if p ~= nil then p.Name, p.Parent, partes[nome] = nome, modelo, p end
end
local temRig = (modelo:FindFirstChildWhichIsA("Motor6D", true) ~= nil) or (modelo:FindFirstChildWhichIsA("Bone", true) ~= nil)
local ltPart = partes["LowerTorso"]
if ltPart ~= nil and not temRig then
    local originCF = ltPart.CFrame * CFrame.new(-LT_CENTER.X, -LT_CENTER.Y, -LT_CENTER.Z)
    local hrp = modelo:FindFirstChild("HumanoidRootPart")
    if not (hrp and hrp:IsA("BasePart")) then
        hrp = Instance.new("Part")
        hrp.Name, hrp.Parent = "HumanoidRootPart", modelo
    end
    local ancLT = ANCORAS["LowerTorso"]
    hrp.Transparency, hrp.CanCollide, hrp.Anchored = 1, false, true
    hrp.Size = Vector3.new(math.min(ltPart.Size.X, 2), ltPart.Size.Y, math.min(ltPart.Size.Z, 1))
    hrp.CFrame = originCF * CFrame.new(ancLT.X, ancLT.Y, ancLT.Z)
    modelo.PrimaryPart, partes["HumanoidRootPart"] = hrp, hrp
    for _, nome in ipairs(PART_NAMES) do
        local p = partes[nome]
        if p ~= nil then
            p.Anchored = false
            p.CanCollide = (COLLIDE_PARTS[nome] == true)
        end
    end
    for _, j in ipairs(JOINTS) do
        local p0, p1, anc = partes[j.p0], partes[j.p1], ANCORAS[j.p1]
        if p0 ~= nil and p1 ~= nil and anc ~= nil then
            local jointCF = originCF * CFrame.new(anc.X, anc.Y, anc.Z)
            local m = Instance.new("Motor6D")
            m.Name, m.Part0, m.Part1 = j.nome, p0, p1
            m.C0, m.C1, m.Parent = p0.CFrame:ToObjectSpace(jointCF), p1.CFrame:ToObjectSpace(jointCF), p0
        end
    end
else
{else_body}end
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


def _buscar_partes_combinadas_ledger(
    caminho_ledger: str | Path | None,
    item_id: str,
) -> str | None:
    """Prioriza entrada ``partes_combinadas`` para ``item_id`` (ou geral) no ledger de uploads."""
    especifico: str | None = None
    generico: str | None = None
    arq_ledger = paths.arquivo_ledger() if caminho_ledger is None else Path(caminho_ledger).expanduser()
    if arq_ledger.is_file():
        for linha in arq_ledger.read_text(encoding="utf-8").splitlines():
            texto = linha.strip()
            if not texto:
                continue
            try:
                rec = json.loads(texto)
            except ValueError:
                continue
            if not isinstance(rec, Mapping) or rec.get("evento") == "run":
                continue
            entradas = upload._extrair_entradas_ledger(rec)
            if not entradas:
                continue
            uri = entradas[0][2]
            arquivo = str(rec.get("arquivo") or rec.get("caminho") or "").strip()
            role_raw = str(rec.get("role") or rec.get("papel") or rec.get("canal") or "").strip().lower()
            lids_raw = [
                str(rec.get(k) or "").strip()
                for k in ("id", "item_id", "forge3d_id", "nome", "name", "displayName", "asset_id")
                if rec.get(k)
            ]
            eh_comb = (
                role_raw == "partes_combinadas"
                or "partes_combinadas" in arquivo.lower()
                or any("partes_combinadas" in x.lower() for x in lids_raw)
            )
            if not eh_comb:
                continue
            casa_item = (
                item_id in lids_raw
                or any(
                    x.startswith(f"{item_id}_")
                    or x.startswith(f"{item_id}.")
                    or x.startswith(f"{item_id}/")
                    for x in lids_raw
                )
                or (bool(item_id) and item_id in arquivo)
            )
            if casa_item:
                especifico = uri
            else:
                generico = uri

    mapa_geral = upload.resolver_ledger(caminho_ledger)
    if (item_id, "partes_combinadas") in mapa_geral:
        return mapa_geral[(item_id, "partes_combinadas")]
    for lid_cand in (f"{item_id}_partes_combinadas", f"{item_id}.partes_combinadas"):
        for role in ("partes_combinadas", "model", "Model", "mesh", ""):
            if (lid_cand, role) in mapa_geral:
                return mapa_geral[(lid_cand, role)]
    if especifico:
        return especifico
    for role in ("partes_combinadas", "model", "Model", "mesh", ""):
        if ("partes_combinadas", role) in mapa_geral:
            return mapa_geral[("partes_combinadas", role)]
    return generico


def resolver_model_id(
    model_id: str | int,
    item_id: str,
    ledger: str | Path | bool | None = True,
    modo_rig: str = "motor6d",
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
        escolhido: str | None = None
        if modo_rig == "motor6d":
            escolhido = _buscar_partes_combinadas_ledger(caminho_ledger, item_id)
        if not escolhido:
            mapa_ledger = upload.resolver_ledger(caminho_ledger, asset_id=item_id)
            escolhido = next(
                (
                    mapa_ledger[(item_id, r)]
                    for r in ("partes_combinadas", "model", "Model", "mesh", "")
                    if (item_id, r) in mapa_ledger
                ),
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


def _extrair_rig_r15_segmentado(
    manifesto: Mapping[str, Any] | None,
) -> tuple[dict[str, tuple[float, float, float]], tuple[float, float, float]] | None:
    """Extrai ancoras das 15 partes R15 e ``centro_bbox`` do ``LowerTorso`` quando segmentado."""
    if not isinstance(manifesto, Mapping):
        return None
    raw_partes = manifesto.get("partes")
    if not isinstance(raw_partes, list) or not raw_partes:
        return None
    partes_man = {
        str(p["nome"]): p
        for p in raw_partes
        if isinstance(p, Mapping) and p.get("nome")
    }
    raw_rig = manifesto.get("rig")
    raw_anc = raw_rig.get("ancoras") if isinstance(raw_rig, Mapping) else None
    rig_ancoras: Mapping[str, Any] = raw_anc if isinstance(raw_anc, Mapping) else {}

    ancoras: dict[str, tuple[float, float, float]] = {}
    for nome, junta in JOINT_R15.items():
        p_man = partes_man.get(nome)
        if not isinstance(p_man, Mapping):
            return None
        cand = p_man.get("ancora") or rig_ancoras.get(nome) or rig_ancoras.get(junta)
        if not (isinstance(cand, (list, tuple)) and len(cand) == 3):
            return None
        ancoras[nome] = (float(cand[0]), float(cand[1]), float(cand[2]))

    lt_man = partes_man["LowerTorso"]
    raw_cb = lt_man.get("centro_bbox")
    if isinstance(raw_cb, (list, tuple)) and len(raw_cb) == 3:
        lt_centro = (float(raw_cb[0]), float(raw_cb[1]), float(raw_cb[2]))
    else:
        lt_centro = ancoras["LowerTorso"]
    return ancoras, lt_centro


def _snippet_surface_luau(mapas_rbx: Mapping[str, str]) -> str:
    if not mapas_rbx:
        return ""
    props = "\n".join(f"        sa.{k} = {json.dumps(v)}" for k, v in sorted(mapas_rbx.items()))
    return (
        'for _, desc in ipairs(modelo:GetDescendants()) do\n'
        '    if desc:IsA("MeshPart") then\n'
        '        local sa = desc:FindFirstChildOfClass("SurfaceAppearance") or Instance.new("SurfaceAppearance")\n'
        '        sa.AlphaMode = Enum.AlphaMode.Overlay\n'
        f"{props}\n"
        "        sa.Parent = desc\n"
        "    end\n"
        "end\n"
    )


def _resolver_mapas_rbx_model(
    item_id: str,
    *,
    manifesto: Mapping[str, Any] | None,
    asset_ids: Mapping[str, str] | None,
    mapas_pbr: Mapping[str, str] | None,
    ledger: str | Path | bool | None,
) -> dict[str, str]:
    brutos = _normalizar_mapas_pbr(mapas_pbr)
    if not brutos and isinstance(manifesto, Mapping):
        brutos = _extrair_mapas_pbr_manifesto_dict(manifesto, id_efetivo=item_id)
    resolvidos = _resolver_asset_ids_pbr(
        brutos, asset_ids, item_id=item_id, ledger=None if ledger is False else ledger
    )
    return {k: str(v) for k, v in resolvidos.items() if str(v or "").startswith("rbxassetid://")}


def _montar_script_load_rigido(
    model_id_num: str,
    ancoras: Mapping[str, tuple[float, float, float]],
    lt_centro: tuple[float, float, float],
    mapas_rbx: Mapping[str, str] | None = None,
) -> str:
    linhas_anc = [
        f'    {nome} = Vector3.new({anc[0]:.6f}, {anc[1]:.6f}, {anc[2]:.6f}),'
        for nome, anc in ancoras.items()
    ]
    linhas_juntas = [
        f'    {{ nome = "{junta}", p0 = "{PARENT_R15[nome]}", p1 = "{nome}" }},'
        for nome, junta in JOINT_R15.items()
    ]
    hdr = _LUAU_LOAD_HDR.format(model_id=model_id_num)
    body = _LUAU_LOAD_MODEL_RIGID.format(
        ancoras_luau="\n".join(linhas_anc),
        joints_luau="\n".join(linhas_juntas),
        lt_cx=lt_centro[0], lt_cy=lt_centro[1], lt_cz=lt_centro[2],
        else_body="\n".join(f"    {ln}" for ln in _LUAU_LOAD_BONE_BODY.splitlines()) + "\n",
    )
    return f"{hdr}{body}{_LUAU_ATTACHMENTS_RIGID}{_snippet_surface_luau(mapas_rbx or {})}{_LUAU_LOAD_FTR}"


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
    modo_rig: str = "motor6d",
    manifesto: Mapping[str, Any] | None = None,
    asset_ids: Mapping[str, str] | None = None,
    mapas_pbr: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Gera ``.rbxlx`` com ``KeyframeSequence`` + loader Server + player Client via ``model_id``."""
    model_id_num = resolver_model_id(model_id, item_id, ledger=ledger, modo_rig=modo_rig)
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
        '<bool name="StreamingEnabled">false</bool>',
        "</Properties>",
    ]
    raw_rig = manifesto.get("rig") if isinstance(manifesto, Mapping) else None
    raw_anc = raw_rig.get("ancoras") if isinstance(raw_rig, Mapping) else None
    ancoras_rig = raw_anc if isinstance(raw_anc, Mapping) else None
    ref_idx = 1
    for clipe in clipes:
        clipe_action = {**clipe, "priority": max(2, int(clipe.get("priority", 2)))}
        itens, ref_idx = _sequencia_xml(
            clipe_action, ref_idx, mps=mps, ancoras=ancoras_rig, modo_rig=modo_rig
        )
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

    rig_seg = _extrair_rig_r15_segmentado(manifesto) if modo_rig == "motor6d" else None
    montagem_motor6d = rig_seg is not None
    mapas_rbx = _resolver_mapas_rbx_model(
        item_id, manifesto=manifesto, asset_ids=asset_ids, mapas_pbr=mapas_pbr, ledger=ledger
    )
    if rig_seg is not None:
        ancoras_r15, lt_centro = rig_seg
        codigo_load = _montar_script_load_rigido(model_id_num, ancoras_r15, lt_centro, mapas_rbx)
    else:
        hdr = _LUAU_LOAD_HDR.format(model_id=model_id_num)
        codigo_load = f"{hdr}{_LUAU_LOAD_BONE_BODY}{_snippet_surface_luau(mapas_rbx)}{_LUAU_LOAD_FTR}"

    src_load = escape(codigo_load)
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
        "partes": 16 if montagem_motor6d else 0,
        "motores": 15 if montagem_motor6d else 0,
        "attachments": 0,
        "attachments_script": bool(montagem_motor6d),
        "clipes": nomes_clipes,
        "animacoes": nomes_clipes,
        "keyframes": {c["nome"]: len(c.get("chaves") or []) for c in clipes},
        "model_id": model_id_num,
        "modo_rig": "model",
        "montagem_motor6d": montagem_motor6d,
        "metros_por_stud": mps,
        "textura": bool(mapas_rbx),
        **({"surface_appearance": mapas_rbx} if mapas_rbx else {}),
    }
