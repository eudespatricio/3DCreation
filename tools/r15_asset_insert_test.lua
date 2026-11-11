local InsertService = game:GetService("InsertService")
local ASSET_ID = 136741921517312

local function Main()
	local ok, modelo = pcall(function()
		return InsertService:LoadAsset(ASSET_ID)
	end)
	if not ok or not modelo then
		warn("ASSET_INSERT_FAIL " .. tostring(modelo))
		print("ASSET_INSERT_FAIL")
		return
	end
	modelo.Parent = workspace
	local partes, malhas, texturas = 0, 0, 0
	for _, d in ipairs(modelo:GetDescendants()) do
		if d:IsA("MeshPart") then
			malhas += 1
			if malhas <= 10 then
				print("MESHPART", d.Name, d.Size, d.MeshId)
			end
		end
		if d:IsA("BasePart") then
			partes += 1
		end
		if d:IsA("Texture") or d:IsA("SurfaceAppearance") then
			texturas += 1
		end
	end
	print(string.format("ASSET_INSERT_OK partes=%d malhas=%d texturas=%d", partes, malhas, texturas))
end

return { Main = Main }
