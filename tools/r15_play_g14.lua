-- Harness Play-mode Roblox Studio para Gate G14 (KeyframeSequence / LoadAnimation / RunService).
local Players = game:GetService("Players")
local RunService = game:GetService("RunService")
local KeyframeSequenceProvider = game:GetService("KeyframeSequenceProvider")

local function encontrarModeloR15()
    for _, inst in ipairs(workspace:GetDescendants()) do
        if inst:IsA("Model") and inst:FindFirstChildOfClass("Humanoid") then
            return inst
        end
    end
    return nil
end

local function verificarG14Play(modelo, seqObj)
    local humanoid = modelo and modelo:FindFirstChildOfClass("Humanoid")
    assert(humanoid ~= nil, "G14: modelo sem Humanoid")
    local animator = humanoid:FindFirstChildOfClass("Animator")
    if animator == nil then
        animator = Instance.new("Animator")
        animator.Parent = humanoid
    end

    local animId = KeyframeSequenceProvider:RegisterKeyframeSequence(seqObj)
    local anim = Instance.new("Animation")
    anim.Name = "G14_Probe"
    anim.AnimationId = animId

    local track = animator:LoadAnimation(anim)
    track.Looped = true
    track:Play(0.0, 1.0, 1.0)

    local iniciais = {}
    for _, desc in ipairs(modelo:GetDescendants()) do
        if desc:IsA("BasePart") then
            iniciais[desc.Name] = desc.CFrame
        end
    end

    local maxDeltaPos = 0.0
    local maxDeltaAng = 0.0
    local frames = 0
    while frames < 20 do
        RunService.Heartbeat:Wait()
        frames = frames + 1
        for _, desc in ipairs(modelo:GetDescendants()) do
            if desc:IsA("BasePart") and iniciais[desc.Name] then
                local cf0 = iniciais[desc.Name]
                local cf1 = desc.CFrame
                maxDeltaPos = math.max(maxDeltaPos, (cf1.Position - cf0.Position).Magnitude)
                local rel = cf0:ToObjectSpace(cf1)
                local _, _, _, r00, _, _, _, r11, _, _, _, r22 = rel:GetComponents()
                local tr = math.clamp((r00 + r11 + r22 - 1.0) * 0.5, -1.0, 1.0)
                maxDeltaAng = math.max(maxDeltaAng, math.deg(math.acos(tr)))
            end
        end
    end

    track:Stop()
    local ok = maxDeltaAng >= 5.0 or maxDeltaPos >= 0.05
    local status = ok and "G14_PLAY_PASS" or "G14_PLAY_FAIL"
    print(string.format("%s max_ang_deg=%.2f max_pos_studs=%.4f", status, maxDeltaAng, maxDeltaPos))
    return ok, maxDeltaAng, maxDeltaPos
end

return {
    encontrarModeloR15 = encontrarModeloR15,
    verificarG14Play = verificarG14Play,
    players = Players,
}
