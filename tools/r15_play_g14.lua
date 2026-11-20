-- Harness Play-mode Roblox Studio para Gate G14 (KeyframeSequence / LoadAnimation / RunService).
local Players = game:GetService("Players")
local RunService = game:GetService("RunService")
local KeyframeSequenceProvider = game:GetService("KeyframeSequenceProvider")

local function encontrarModeloR15()
    for _, nomeAlvo in ipairs({"_G14TestModel", "Forge3DR15"}) do
        local direto = workspace:FindFirstChild(nomeAlvo, true)
        if direto and direto:IsA("Model") then
            return direto
        end
    end
    for _, inst in ipairs(workspace:GetDescendants()) do
        if inst:IsA("Model") and (inst:FindFirstChildOfClass("Humanoid") or inst:FindFirstChildOfClass("AnimationController")) then
            return inst
        end
    end
    return nil
end

local function cframeDelta(cf0, cf1)
    local rel = cf0:ToObjectSpace(cf1)
    local dp = (cf1.Position - cf0.Position).Magnitude
    local _, _, _, r00, _, _, _, r11, _, _, _, r22 = rel:GetComponents()
    local tr = math.clamp((r00 + r11 + r22 - 1.0) * 0.5, -1.0, 1.0)
    return math.deg(math.acos(tr)), dp
end

local function verificarG14Play(modelo, seqObj)
    local controller = modelo and (modelo:FindFirstChildOfClass("Humanoid") or modelo:FindFirstChildOfClass("AnimationController"))
    assert(controller ~= nil, "G14: modelo sem Humanoid ou AnimationController")
    local animator = controller:FindFirstChildOfClass("Animator")
    if animator == nil then
        animator = Instance.new("Animator")
        animator.Parent = controller
    end

    local animId = KeyframeSequenceProvider:RegisterKeyframeSequence(seqObj)
    local anim = Instance.new("Animation")
    anim.Name = "G14_Probe"
    anim.AnimationId = animId

    local track = animator:LoadAnimation(anim)
    track.Looped = true
    track.Priority = Enum.AnimationPriority.Action
    track:Play(0.0, 1.0, 1.0)

    local iniciaisParts = {}
    local joints = {}
    for _, desc in ipairs(modelo:GetDescendants()) do
        if desc:IsA("BasePart") then
            iniciaisParts[desc] = desc.CFrame
        elseif desc:IsA("Motor6D") or desc:IsA("Bone") then
            table.insert(joints, desc)
        end
    end

    local maxDeltaPos = 0.0
    local maxDeltaAng = 0.0
    local movedSet = {}
    local frames = 0
    while frames < 25 do
        RunService.Heartbeat:Wait()
        frames = frames + 1
        for part, cf0 in pairs(iniciaisParts) do
            if part.Parent then
                local ang, dp = cframeDelta(cf0, part.CFrame)
                maxDeltaAng = math.max(maxDeltaAng, ang)
                maxDeltaPos = math.max(maxDeltaPos, dp)
            end
        end
        for _, joint in ipairs(joints) do
            if joint.Parent then
                local ang, dp = cframeDelta(CFrame.identity, joint.Transform)
                maxDeltaAng = math.max(maxDeltaAng, ang)
                maxDeltaPos = math.max(maxDeltaPos, dp)
                if ang >= 1.0 or dp >= 0.01 then
                    movedSet[joint] = true
                end
            end
        end
    end

    local movedJoints = 0
    for _ in pairs(movedSet) do
        movedJoints = movedJoints + 1
    end

    track:Stop()
    anim:Destroy()
    local ok = maxDeltaAng >= 5.0 or maxDeltaPos >= 0.05
    local status = ok and "G14_PLAY_PASS" or "G14_PLAY_FAIL"
    print(string.format("%s max_ang_deg=%.2f max_pos_studs=%.4f moved=%d", status, maxDeltaAng, maxDeltaPos, movedJoints))
    return ok, maxDeltaAng, maxDeltaPos, movedJoints
end

return {
    encontrarModeloR15 = encontrarModeloR15,
    verificarG14Play = verificarG14Play,
    players = Players,
}
