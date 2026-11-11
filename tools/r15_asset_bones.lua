local InsertService = game:GetService("InsertService")
local ASSET_ID = 136741921517312

local function Main()
	local ok, modelo = pcall(function()
		return InsertService:LoadAsset(ASSET_ID)
	end)
	if not ok or not modelo then
		warn("BONES_FAIL " .. tostring(modelo))
		print("BONES_FAIL")
		return
	end
	modelo.Parent = workspace
	local ossos = 0
	for _, d in ipairs(modelo:GetDescendants()) do
		if d:IsA("Bone") then
			ossos += 1
			print("BONE", d.Name, "pai", d.Parent and d.Parent.Name or "nil")
		end
	end
	print(string.format("BONES_OK ossos=%d", ossos))
end

return { Main = Main }
