local InsertService = game:GetService("InsertService")
local MODEL_ID = 136741921517312
local TEXTURE_ID = 75934318775024

local function Main()
	local ok, modelo = pcall(function()
		return InsertService:LoadAsset(MODEL_ID)
	end)
	if not ok or not modelo then
		warn("TEXTURE_APPLY_FAIL load " .. tostring(modelo))
		print("TEXTURE_APPLY_FAIL")
		return
	end
	modelo.Parent = workspace
	local mesh = modelo:FindFirstChild("forge3d_mesh", true)
	if not mesh or not mesh:IsA("MeshPart") then
		warn("TEXTURE_APPLY_FAIL sem MeshPart")
		print("TEXTURE_APPLY_FAIL")
		return
	end
	print("TEXTURE_ANTES", mesh.TextureID)
	mesh.TextureID = "rbxassetid://" .. TEXTURE_ID
	task.wait(3)
	print("TEXTURE_DEPOIS", mesh.TextureID)
	print("TEXTURE_APPLY_OK")
end

return { Main = Main }
