-- Teste de pivo por membro no Roblox Studio (R15). Roda via run-in-roblox ou colado no
-- Command Bar com o place aberto. Cria um rig R15 de prova (Parts + Motor6D) a partir das
-- fracoes de osso do Forge3D e verifica, para cada junta, que o pivo fica no joint e que a
-- rotacao de C0 mantem a distancia da parte ao pivo.
--
-- Uso headless:
--   run-in-roblox run --place-file <place.rbxlx> --script tools/r15_studio_test.lua \
--     --universe-id 0 --place-id 0 --oneshot

local Workspace = game:GetService("Workspace")

local H = 1.85
local function Main()
local existing = Workspace:FindFirstChild("Forge3DR15Test")
if existing then
	existing:Destroy()
end

local model = Instance.new("Model")
model.Name = "Forge3DR15Test"
model.Parent = Workspace

-- head/tail em fracao de altura; motor = nome do Motor6D que liga ao pai.
local bones = {
	{ name = "HumanoidRootPart", parent = nil, head = { 0, 0, 0 }, tail = { 0, 0, 0.10 }, motor = nil },
	{ name = "LowerTorso", parent = "HumanoidRootPart", head = { 0, 0, 0.44 }, tail = { 0, 0, 0.52 }, motor = "RootJoint" },
	{ name = "UpperTorso", parent = "LowerTorso", head = { 0, 0, 0.52 }, tail = { 0, 0, 0.78 }, motor = "Waist" },
	{ name = "Head", parent = "UpperTorso", head = { 0, 0, 0.78 }, tail = { 0, 0, 1.00 }, motor = "Neck" },
	{ name = "LeftUpperArm", parent = "UpperTorso", head = { 0.10, 0, 0.76 }, tail = { 0.17, 0, 0.60 }, motor = "LeftShoulder" },
	{ name = "LeftLowerArm", parent = "LeftUpperArm", head = { 0.17, 0, 0.60 }, tail = { 0.17, 0, 0.44 }, motor = "LeftElbow" },
	{ name = "LeftHand", parent = "LeftLowerArm", head = { 0.17, 0, 0.44 }, tail = { 0.17, 0, 0.36 }, motor = "LeftWrist" },
	{ name = "RightUpperArm", parent = "UpperTorso", head = { -0.10, 0, 0.76 }, tail = { -0.17, 0, 0.60 }, motor = "RightShoulder" },
	{ name = "RightLowerArm", parent = "RightUpperArm", head = { -0.17, 0, 0.60 }, tail = { -0.17, 0, 0.44 }, motor = "RightElbow" },
	{ name = "RightHand", parent = "RightLowerArm", head = { -0.17, 0, 0.44 }, tail = { -0.17, 0, 0.36 }, motor = "RightWrist" },
	{ name = "LeftUpperLeg", parent = "LowerTorso", head = { 0.065, 0, 0.44 }, tail = { 0.065, 0, 0.235 }, motor = "LeftHip" },
	{ name = "LeftLowerLeg", parent = "LeftUpperLeg", head = { 0.065, 0, 0.235 }, tail = { 0.065, 0, 0.065 }, motor = "LeftKnee" },
	{ name = "LeftFoot", parent = "LeftLowerLeg", head = { 0.065, 0, 0.065 }, tail = { 0.065, 0.12, 0.02 }, motor = "LeftAnkle" },
	{ name = "RightUpperLeg", parent = "LowerTorso", head = { -0.065, 0, 0.44 }, tail = { -0.065, 0, 0.235 }, motor = "RightHip" },
	{ name = "RightLowerLeg", parent = "RightUpperLeg", head = { -0.065, 0, 0.235 }, tail = { -0.065, 0, 0.065 }, motor = "RightKnee" },
	{ name = "RightFoot", parent = "RightLowerLeg", head = { -0.065, 0, 0.065 }, tail = { -0.065, 0.12, 0.02 }, motor = "RightAnkle" },
}

local function v(t)
	return Vector3.new(t[1] * H, t[2] * H, t[3] * H)
end

local parts = {}
local joints = {}
for _, b in ipairs(bones) do
	local part = Instance.new("Part")
	part.Name = b.name
	part.Anchored = true
	part.CanCollide = false
	part.Size = Vector3.new(0.12, 0.12, 0.12)
	part.Color = Color3.fromRGB(90, 120, 160)
	part.Material = Enum.Material.SmoothPlastic
	local head = v(b.head)
	local tail = v(b.tail)
	part.CFrame = CFrame.new((head + tail) * 0.5)
	part.Parent = model
	parts[b.name] = part
end

local falhas = {}
local motores = 0

for _, b in ipairs(bones) do
	if b.parent and b.motor then
		local part = parts[b.name]
		local pai = parts[b.parent]
		local joint = v(b.head)
		local centro = Vector3.new(
			(b.head[1] + b.tail[1]) / 2 * H,
			(b.head[2] + b.tail[2]) / 2 * H,
			(b.head[3] + b.tail[3]) / 2 * H
		)
		local offset = centro - joint
		local motor = Instance.new("Motor6D")
		motor.Name = b.motor
		motor.Part0 = pai
		motor.Part1 = part
		motor.C0 = CFrame.new(joint - pai.Position)
		motor.C1 = CFrame.new(-offset)
		motor.Parent = pai
		motores += 1

		local pivo = pai.CFrame * motor.C0
		local dist = (pivo.Position - joint).Magnitude
		if dist > 0.002 then
			table.insert(falhas, string.format("%s: pivo fora do joint (%.4f m)", b.motor, dist))
		end

		local restDist = (part.Position - pivo.Position).Magnitude
		local rot = CFrame.Angles(0, math.rad(30), 0)
		local novoC0 = motor.C0 * rot
		local novoPivo = pai.CFrame * novoC0
		local novo = pai.CFrame * novoC0 * motor.C1:Inverse()
		local novaDist = (novo.Position - novoPivo.Position).Magnitude
		local movimento = (novo.Position - part.Position).Magnitude
		if math.abs(novaDist - restDist) > 0.002 then
			table.insert(falhas, string.format("%s: distancia ao pivo mudou (%.4f -> %.4f)", b.motor, restDist, novaDist))
		end
		if movimento < 0.002 then
			table.insert(falhas, string.format("%s: rotacao nao moveu a parte", b.motor))
		end

		-- tenta tambem o comportamento real do Studio em Edit mode (pode nao aplicar sem Play)
		motor.C0 = novoC0
		task.wait()
		local real = part.Position
		local realPivo = pai.CFrame * motor.C0
		local realDist = (real - realPivo.Position).Magnitude
		if (real - novo.Position).Magnitude < 0.002 then
			if math.abs(realDist - restDist) > 0.01 then
				table.insert(falhas, string.format("%s: Motor6D real perdeu o pivo", b.motor))
			end
		end
		motor.C0 = novoC0 * rot:Inverse()
	end
end

local humanoid = Instance.new("Humanoid")
humanoid.RigType = Enum.HumanoidRigType.R15
humanoid.Parent = model
model.PrimaryPart = parts["HumanoidRootPart"]

if #falhas == 0 then
	print(string.format("R15_STUDIO_PASS motores=%d partes=%d", motores, #bones))
else
	for _, f in ipairs(falhas) do
		warn("R15_STUDIO_FAIL " .. f)
	end
	print(string.format("R15_STUDIO_FAIL motores=%d falhas=%d", motores, #falhas))
end

end

return { Main = Main }
