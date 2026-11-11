"""Mede o package R15 no Studio via MCP (D60) — o portão de escala da P2, reexecutável.

Uso:
    python tools/r15_escala_studio.py                # asset padrao (ultimo upload do r15)
    python tools/r15_escala_studio.py 134628989553440

Devolve `Size` em studs, numero de Bones, `SurfaceAppearance`/`Humanoid` e o resultado do
`PreloadAsync` da textura. Esperado no perfil `roblox-r15` (D62): `Size.Y = 6,6071` studs, 16 Bones,
textura `Enum.AssetFetchStatus.Success`.

Precisa do Studio aberto com o MCP ligado; o proxy so lista o Studio com ele vivo alguns segundos
(ver `tools/mcp_studio.py`).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mcp_studio import Cliente  # noqa: E402

ASSET_PADRAO = 134628989553440
TEXTURA = 75934318775024

CODIGO = """
local I = game:GetService("InsertService")
local C = game:GetService("ContentProvider")
local m = I:LoadAsset(ASSET_ID)
m.Parent = workspace
m.Name = "Forge3D_P8_escala"
local mesh = m:FindFirstChildWhichIsA("MeshPart", true)
if not mesh then return "SEM MESHPART" end
local bones = 0
for _, d in ipairs(m:GetDescendants()) do if d:IsA("Bone") then bones = bones + 1 end end
local sa = m:FindFirstChildWhichIsA("SurfaceAppearance", true)
local hum = m:FindFirstChildWhichIsA("Humanoid", true)
mesh.TextureID = "rbxassetid://TEXTURE_ID"
local st = nil
C:PreloadAsync({mesh}, function(_, s) st = s end)
return string.format(
    "R15 asset=%d size=%.4f,%.4f,%.4f studs | bones=%d | surface=%s | humanoid=%s | tex=%s | preload=%s",
    ASSET_ID, mesh.Size.X, mesh.Size.Y, mesh.Size.Z, bones, tostring(sa ~= nil),
    tostring(hum ~= nil), tostring(mesh.TextureID), tostring(st)
)
"""


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    asset = int(argv[0]) if argv else ASSET_PADRAO
    codigo = CODIGO.replace("ASSET_ID", str(asset)).replace("TEXTURE_ID", str(TEXTURA))
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
