"""Mede no Studio o clipe do `.rbxlx` aplicado aos Motor6D do rig (D69/GAP-045).

O `InsertService:LoadLocalAsset` é bloqueado (`RobloxScript`), então o rig é reconstruído no Luau a
partir do próprio `.rbxlx` — Partes, tamanhos, CFrame, Motor6D (C0/C1) e poses do
`KeyframeSequence` — e a cadeia é resolvida como o `Animator` faz:

    Part1.CFrame = Part0.CFrame * C0 * Transform * C1:Inverse()

Uso:
    python tools/r15_anim_studio.py [--place <rbxlx>] [--clipe idle] [--tempo 0.5]

Precisa do Studio aberto com o MCP ligado (`tools/mcp_studio.py --estado`).
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

PADRAO = Path.home() / ".local/state/forge3d/saida/r15/personagem.r15.guard.01.rbxlx"


def _lua(valor) -> str:
    """Serializa para literal de tabela Luau (JSON nao serve: usa ':' e nao '=')."""
    if isinstance(valor, dict):
        itens = ",".join(f"[{json.dumps(str(k))}]={_lua(v)}" for k, v in valor.items())
        return "{" + itens + "}"
    if isinstance(valor, (list, tuple)):
        return "{" + ",".join(_lua(v) for v in valor) + "}"
    if isinstance(valor, bool):
        return "true" if valor else "false"
    if isinstance(valor, (int, float)):
        return repr(valor)
    return json.dumps(str(valor))


def _dados(place: dict, clipe: str) -> dict:
    escolhido = next((c for c in place["clipes"] if c["nome"] == clipe), None)
    if escolhido is None:
        raise SystemExit(f"clipe '{clipe}' nao esta no place")
    return {
        "partes": place["partes"],
        "motores": place["motores"],
        "clipe": {
            "nome": escolhido["nome"],
            "chaves": [
                {
                    "tempo": chave["tempo"],
                    "poses": {p["osso"]: p["cframe"] for p in chave["poses"]},
                }
                for chave in escolhido["chaves"]
            ],
        },
    }


CODIGO = """
local D = DADOS
local model = Instance.new("Model")
model.Name = "Forge3D_P5B"
model.Parent = workspace

local partes = {}
local total_partes = 0
for nome, p in pairs(D.partes) do
    local part = Instance.new("Part")
    part.Name = nome
    part.Size = Vector3.new(p.size[1], p.size[2], p.size[3])
    part.CFrame = CFrame.new(p.cframe[1], p.cframe[2], p.cframe[3])
    part.Anchored = true
    part.CanCollide = false
    part.Parent = model
    partes[nome] = part
    total_partes = total_partes + 1
end

local motores = {}
local motor_por_junta = {}
for _, m in ipairs(D.motores) do
    local p0 = partes[m.part0]
    local p1 = partes[m.part1]
    if p0 and p1 then
        local motor = Instance.new("Motor6D")
        motor.Name = m.nome
        motor.Part0 = p0
        motor.Part1 = p1
        motor.C0 = CFrame.new(m.c0[1], m.c0[2], m.c0[3])
        motor.C1 = CFrame.new(m.c1[1], m.c1[2], m.c1[3])
        motor.Parent = p0
        motores[m.part1] = motor
        motor_por_junta[m.nome] = motor
    end
end

local function cf12(t)
    return CFrame.new(0, 0, 0, t[4], t[5], t[6], t[7], t[8], t[9], t[10], t[11], t[12])
end

local function poses_em(tempo)
    local tr = {}
    for _, chave in ipairs(D.clipe.chaves) do
        if math.abs(chave.tempo - tempo) < 0.01 then
            for osso, matriz in pairs(chave.poses) do
                tr[osso] = cf12(matriz)
            end
        end
    end
    return tr
end

local function mundo(tempo)
    local tr = poses_em(tempo)
    local cf = {}
    cf["HumanoidRootPart"] = CFrame.new(
        D.partes["HumanoidRootPart"].cframe[1],
        D.partes["HumanoidRootPart"].cframe[2],
        D.partes["HumanoidRootPart"].cframe[3]
    )
    local pendentes = {}
    for filho, motor in pairs(motores) do pendentes[filho] = motor end
    local mudou = true
    while mudou do
        mudou = false
        for filho, motor in pairs(pendentes) do
            local pai = motor.Part0.Name
            if cf[pai] ~= nil then
                -- a pose e por nome de JUNTA (D69); o motor tambem
                local t = tr[motor.Name] or CFrame.new()
                cf[filho] = cf[pai] * motor.C0 * t * motor.C1:Inverse()
                pendentes[filho] = nil
                mudou = true
            end
        end
    end
    return cf
end

local a = mundo(0.0)
local b = mundo(TEMPO)
local cabeca0 = a["Head"].Position
local cabeca1 = b["Head"].Position
local delta = (cabeca1 - cabeca0).Magnitude
local maior = 0.0
for nome, cf in pairs(a) do
    local outro = b[nome]
    if outro then
        maior = math.max(maior, (outro.Position - cf.Position).Magnitude)
    end
end
model:Destroy()
return string.format(
    "P5B clipe=%s partes=%d motores=%d t=0 head=%.4f,%.4f,%.4f t=%.2f head=%.4f,%.4f,%.4f delta=%.4f studs | maior_delta=%.4f",
    D.clipe.nome, total_partes, #D.motores,
    cabeca0.X, cabeca0.Y, cabeca0.Z, TEMPO, cabeca1.X, cabeca1.Y, cabeca1.Z, delta, maior
)
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Mede o clipe do .rbxlx nos Motor6D no Studio")
    parser.add_argument("--place", default=str(PADRAO))
    parser.add_argument("--clipe", default="idle")
    parser.add_argument("--tempo", type=float, default=0.5)
    args = parser.parse_args(argv)

    place = rbx.ler_place(args.place)
    dados = _dados(place, args.clipe)
    codigo = CODIGO.replace("DADOS", _lua(dados)).replace("TEMPO", f"{args.tempo:.4f}")

    cliente = Cliente()
    try:
        cliente.abrir()
        sid = cliente.studio_id(tentativas=15)
        if not sid:
            print("nenhum Studio conectado (MCP ligado? proxy vivo alguns segundos?)")
            return 1
        print("studio:", sid)
        print(cliente.luau(codigo, sid))
        return 0
    finally:
        cliente.fechar()


if __name__ == "__main__":
    raise SystemExit(main())
