-- Valida o .rbxlx nativo gerado por `forge3d export-r15`: 16 Parts, 15 Motor6D e
-- pivo de cada junta no joint esperado (H=1,85 m, 0,28 m/stud).
local H = 1.85
local MPS = 0.28
local joints = {
	LowerTorso = { 0, 0, 0.44 },
	UpperTorso = { 0, 0, 0.52 },
	Head = { 0, 0, 0.78 },
	LeftUpperArm = { 0.10, 0, 0.76 },
	LeftLowerArm = { 0.17, 0, 0.60 },
	LeftHand = { 0.17, 0, 0.44 },
	RightUpperArm = { -0.10, 0, 0.76 },
	RightLowerArm = { -0.17, 0, 0.60 },
	RightHand = { -0.17, 0, 0.44 },
	LeftUpperLeg = { 0.065, 0, 0.44 },
	LeftLowerLeg = { 0.065, 0, 0.235 },
	LeftFoot = { 0.065, 0, 0.065 },
	RightUpperLeg = { -0.065, 0, 0.44 },
	RightLowerLeg = { -0.065, 0, 0.235 },
	RightFoot = { -0.065, 0, 0.065 },
}

local function esperado(nome)
	local j = joints[nome]
	if not j then
		return nil
	end
	return Vector3.new(j[1] * H / MPS, j[3] * H / MPS, -j[2] * H / MPS)
end

local model = workspace:FindFirstChild("Forge3DR15")

local function Main()
	if not model then
		warn("R15_RBXLX_FAIL: Workspace.Forge3DR15 ausente")
		print("R15_RBXLX_FAIL")
		return
	end
	local partes, motores = {}, {}
	for _, d in ipairs(model:GetDescendants()) do
		if d:IsA("Motor6D") then
			table.insert(motores, d)
		elseif d:IsA("BasePart") and d.Parent == model then
			table.insert(partes, d)
		end
	end
	local falhas = {}
	if #partes ~= 16 then
		table.insert(falhas, string.format("partes=%d (esperado 16)", #partes))
	end
	if #motores ~= 15 then
		table.insert(falhas, string.format("motores=%d (esperado 15)", #motores))
	end
	for _, m in ipairs(motores) do
		local exp = esperado(m.Part1.Name)
		local pivo = m.Part0.CFrame * m.C0
		if not exp then
			table.insert(falhas, "sem joint esperado para " .. m.Part1.Name)
		else
			local erro = (pivo.Position - exp).Magnitude
			if erro > 0.02 then
				table.insert(falhas, string.format("%s: pivo fora do joint (%.3f)", m.Name, erro))
			end
		end
		local rest = m.Part1.CFrame
		local restDist = (rest.Position - pivo.Position).Magnitude
		local rot = CFrame.Angles(math.rad(30), 0, 0)
		local novo = m.Part0.CFrame * (m.C0 * rot) * m.C1:Inverse()
		local novoPivo = m.Part0.CFrame * (m.C0 * rot)
		local novaDist = (novo.Position - novoPivo.Position).Magnitude
		if math.abs(novaDist - restDist) > 0.02 then
			table.insert(falhas, m.Name .. ": distancia ao pivo mudou")
		end
		if (novo.Position - rest.Position).Magnitude < 0.005 then
			table.insert(falhas, m.Name .. ": rotacao nao moveu")
		end
	end
	if #falhas == 0 then
		print("R15_RBXLX_PASS partes=16 motores=15")
	else
		for _, f in ipairs(falhas) do
			warn("R15_RBXLX_FAIL " .. f)
		end
		print(string.format("R15_RBXLX_FAIL falhas=%d", #falhas))
	end
end

return { Main = Main }
