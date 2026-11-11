local InsertService = game:GetService("InsertService")
local ASSET_ID = 136741921517312

local function Main()
	local ok, modelo = pcall(function()
		return InsertService:LoadAsset(ASSET_ID)
	end)
	if not ok or not modelo then
		warn("ASSET_INSPECT_FAIL " .. tostring(modelo))
		print("ASSET_INSPECT_FAIL")
		return
	end
	modelo.Parent = workspace
	for _, d in ipairs(modelo:GetDescendants()) do
		if d:IsA("MeshPart") then
			print("MESHPART", d.Name)
			print("  size", d.Size)
			print("  meshId", d.MeshId)
			print("  textureId", d.TextureID)
			print("  color", d.Color)
			for _, c in ipairs(d:GetChildren()) do
				print("  child", c.ClassName, c.Name)
			end
		end
	end
	print("ASSET_INSPECT_OK")
end

return { Main = Main }
