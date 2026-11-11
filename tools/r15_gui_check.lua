-- Forge3D — fechamento do P8/GAP-006 (R15 no Roblox Studio)
--
-- COMO USAR
--   1. Abra o Studio LOGADO (a conta é a dona dos assets 136741921517312 / 75934318775024).
--   2. View -> Command Bar.
--   3. Cole este arquivo INTEIRO na Command Bar e dê Enter.
--   4. Copie o bloco que aparece no Output e devolva para o Forge3D.
--
-- O script só LÊ e mede: insere o package num Model temporário, liga a textura, mede a escala
-- e responde U1/U2/U4. Não publica, não altera place e não escreve em disco.

local InsertService = game:GetService("InsertService")
local ContentProvider = game:GetService("ContentProvider")

local MODEL_ID = 136741921517312
local TEXTURE_ID = 75934318775024
local ALTURA_M = 1.85
local METROS_POR_STUD = 0.28

local pass, fail = 0, 0

local function linha(ok, nome, detalhe)
	if ok then
		pass = pass + 1
	else
		fail = fail + 1
	end
	print(string.format("%s %-22s %s", ok and "PASS" or "FAIL", nome, detalhe or ""))
end

print("=== FORGE3D P8/GAP-006 ===")

-- 1) inserir o package -------------------------------------------------------
local ok, modelo = pcall(function()
	return InsertService:LoadAsset(MODEL_ID)
end)
if not ok or not modelo then
	linha(false, "MODELO", "falhou: " .. tostring(modelo))
	print("P8_GUI: 0 PASS / 1 FAIL")
	return
end
modelo.Parent = workspace
modelo.Name = "Forge3D_P8_check"
linha(true, "MODELO", "inserido " .. tostring(MODEL_ID))

-- 2) inventário do que veio --------------------------------------------------
local mesh = nil
local bones = {}
local humanoid = nil
local surface = nil
for _, d in ipairs(modelo:GetDescendants()) do
	if d:IsA("MeshPart") and mesh == nil then
		mesh = d
	elseif d:IsA("Bone") then
		table.insert(bones, d)
	elseif d:IsA("Humanoid") then
		humanoid = d
	elseif d:IsA("SurfaceAppearance") then
		surface = d
	end
end

if mesh == nil then
	linha(false, "MESHPART", "nenhum MeshPart no package")
	print("P8_GUI: " .. pass .. " PASS / " .. fail .. " FAIL")
	return
end
linha(true, "MESHPART", string.format("name=%s size=%.3f x %.3f x %.3f studs", mesh.Name, mesh.Size.X, mesh.Size.Y, mesh.Size.Z))

-- 3) escala (U1) -------------------------------------------------------------
local altura_studs = mesh.Size.Y
local como_1stud_por_metro = altura_studs
local como_028_m_por_stud = altura_studs * METROS_POR_STUD
linha(true, "ESCALA_U1", string.format(
	"Y=%.3f studs | se 1 m = 1 stud -> %.2f m | se 1 stud = 0,28 m -> %.2f m (alvo %.2f m)",
	altura_studs, como_1stud_por_metro, como_028_m_por_stud, ALTURA_M))
print(string.format("INFO %-22s %s", "escala_esperada", string.format("%.3f studs para %.2f m a 0,28 m/stud", ALTURA_M / METROS_POR_STUD, ALTURA_M)))

-- 4) textura (P8) + SurfaceAppearance (U2) ----------------------------------
mesh.TextureID = "rbxassetid://" .. TEXTURE_ID
print("INFO " .. string.format("%-22s", "textura_id") .. " " .. tostring(mesh.TextureID))

local status = nil
local okPreload = pcall(function()
	ContentProvider:PreloadAsync({ mesh }, function(_id, s)
		status = s
	end)
end)
local carregou = okPreload and status == Enum.AssetFetchStatus.Success
linha(carregou, "TEXTURA", string.format("preload_ok=%s status=%s", tostring(okPreload), tostring(status)))

if surface ~= nil then
	linha(true, "SURFACEAPPEARANCE_U2", "presente")
else
	linha(false, "SURFACEAPPEARANCE_U2", "ausente (glTF PBR nao veio no package)")
end

-- 5) Humanoid (U4) -----------------------------------------------------------
if humanoid ~= nil then
	linha(true, "HUMANOID_U4", "presente (rig aceito como Humanoid)")
else
	linha(false, "HUMANOID_U4", "ausente (so bones; rig R15 fica no .rbxlx nativo)")
end

-- 6) bones (pivos) -----------------------------------------------------------
linha(#bones == 16, "BONES", string.format("%d bones", #bones))
local nomes = {}
for _, b in ipairs(bones) do
	table.insert(nomes, b.Name)
end
table.sort(nomes)
print("INFO " .. string.format("%-22s", "bones_nomes") .. " " .. table.concat(nomes, ","))

-- 7) teste de pivô: girar um bone e ver se o mundo dele muda em torno do próprio head
if #bones > 0 then
	local alvo = bones[1]
	for _, b in ipairs(bones) do
		if b.Name == "UpperTorso" or b.Name == "Torso" or b.Name == "Head" then
			alvo = b
			break
		end
	end
	local antes = alvo.WorldCFrame.Position
	alvo.Transform = alvo.Transform * CFrame.Angles(0, math.rad(30), 0)
	task.wait(0.2)
	local depois = alvo.WorldCFrame.Position
	local desloc = (depois - antes).Magnitude
	linha(desloc < 1e-3, "PIVO_BONE", string.format(
		"bone=%s deslocamento_do_head=%.6f studs (esperado ~0: gira no proprio pivo)", alvo.Name, desloc))
	alvo.Transform = CFrame.new()
end

print(string.format("P8_GUI: %d PASS / %d FAIL", pass, fail))
print("=== fim ===")
