"""Onda 7 (testes independentes, sem Blender): perfis rig.postura, idle sem flutuar, walk/run com aducao,
presets de postura por seed, SkinnedMesh R15 nativo, export-anim com ancoras/modo-rig e GAP-064/067 puros.

Asserts derivados apenas do contrato congelado da Onda 7 (nenhum oraculo copiado do codigo dos coders).
"""

from __future__ import annotations

import copy
import json
import math
import sys
import types
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from forge3d import animacao, config, profiles, qc, rbx, sync_godot_sidecars
from forge3d.cli.comandos import construir_parser, despachar
from forge3d.errors import ForgeError

RAIZ = Path(__file__).resolve().parents[1]
LOTE_R15 = RAIZ / "examples" / "lote_09_r15.yaml"
ITEM_R15 = "personagem.r15.guard.01"
MPS = 0.28

# (perfil, esqueleto) cobrindo Roblox R15 e as duas familias Godot.
PERFIS_ESQ = [("roblox-r15", "r15@1"), ("godot4", "godot-humanoid@1"), ("godot4-aa", "godot-humanoid-aa@1")]
BONE_ROBLOX = [("roblox-r15", "r15@1"), ("roblox-aa-80", "r15@1")]


@pytest.fixture(autouse=True)
def _isolar_forge3d(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORGE3D_HOME", str(tmp_path / "forge_home"))
    monkeypatch.setenv("FORGE3D_CONFIG", str(tmp_path / "forge_cfg"))
    config.adicionar(tmp_path)


# ------------------------------------------------------------------ helpers de clipe
def _clipe(perfil: str, esq: str, nome: str, **kw) -> dict:
    return animacao.clipes(profiles.carregar(perfil), esq, [nome], **kw)[0]


def _osso(perfil: str, esq: str, chave: str) -> str:
    return profiles.retarget(profiles.carregar(perfil), esq)[chave]


def _serie(clipe: dict, osso: str, eixo: str) -> list[float]:
    """Soma dos graus por chave de ``osso`` no ``eixo`` (poses repetidas compoem no mesmo eixo)."""
    return [
        sum(float(p["graus"]) for p in ch["poses"] if p["osso"] == osso and str(p["eixo"]).upper() == eixo)
        for ch in clipe["chaves"]
    ]


def _assinatura(chave: dict) -> list[tuple]:
    return sorted(
        (p["osso"], str(p["eixo"]), round(float(p["graus"]), 4), tuple(round(float(v), 5) for v in p.get("deslocamento_m") or ()))
        for p in chave["poses"]
    )


def _distancia(a: dict, b: dict) -> float:
    """Maior diferenca angular (graus) por (osso, eixo) entre dois clipes de mesmo numero de chaves."""
    assert len(a["chaves"]) == len(b["chaves"])
    maior = 0.0
    for ca, cb in zip(a["chaves"], b["chaves"]):
        def _soma(ch):
            acc: dict[tuple, float] = {}
            for p in ch["poses"]:
                k = (p["osso"], str(p["eixo"]).upper())
                acc[k] = acc.get(k, 0.0) + float(p["graus"])
            return acc
        sa, sb = _soma(ca), _soma(cb)
        for k in set(sa) | set(sb):
            maior = max(maior, abs(sa.get(k, 0.0) - sb.get(k, 0.0)))
    return maior


# ------------------------------------------------------------------ perfis e sidecar Godot
@pytest.mark.parametrize(
    ("nome", "modo", "angulo", "silhueta"),
    [
        ("roblox-r15", "natural_relaxada", 14.0, False),
        ("roblox-aa-80", "natural_relaxada", 14.0, False),
        ("godot4", "apose", 45.0, True),
        ("godot4-aa", "apose", 45.0, True),
    ],
)
def test_perfis_declaram_rig_postura(nome: str, modo: str, angulo: float, silhueta: bool) -> None:
    postura = profiles.carregar(nome)["rig"]["postura"]
    assert postura["modo_rest"] == modo
    assert postura["angulo_braco_graus"] == pytest.approx(angulo)
    assert postura["fix_silhouette"] is silhueta
    assert postura["variacao_seed"] is True


@pytest.mark.parametrize("esq", ["godot-humanoid@1", "godot-humanoid-aa@1"])
def test_godot_sidecar_habilita_fix_silhouette_no_skeleton3d(esq: str) -> None:
    sub = sync_godot_sidecars._construir_subresources_glb({"rig": {"esqueleto": esq}})
    no_skel = sub["nodes"]["PATH:Skeleton3D"]
    assert no_skel["retarget/rest_fixer/fix_silhouette/enable"] is True
    assert "retarget/bone_map" in no_skel


# ------------------------------------------------------------------ idle: sem flutuar, sem rolagem lateral
def test_motores_idle_sem_rolagem_z_no_quadril() -> None:
    assert [m for m in animacao.MOTORES_IDLE if m[0] == "quadril" and m[3] == "Z"] == []
    assert any(m[0] == "quadril" and m[3] == "X" for m in animacao.MOTORES_IDLE)


@pytest.mark.parametrize(("perfil", "esq"), PERFIS_ESQ)
def test_idle_sem_z_roll_sem_elevacao_e_loop_fechado(perfil: str, esq: str) -> None:
    clipe = _clipe(perfil, esq, "idle")
    quadril = _osso(perfil, esq, "quadril")
    assert max(abs(v) for v in _serie(clipe, quadril, "Z")) < 1e-9
    dzs = [
        float(p["deslocamento_m"][2])
        for ch in clipe["chaves"]
        for p in ch["poses"]
        if isinstance(p.get("deslocamento_m"), (list, tuple))
    ]
    assert all(dz <= 1e-9 for dz in dzs), f"idle ainda levanta o quadril: max dz={max(dzs):.6f}"
    assert _assinatura(clipe["chaves"][0]) == _assinatura(clipe["chaves"][-1])


def test_idle_quadril_ativo_e_igual_entre_r15_e_godot() -> None:
    r15 = _serie(_clipe("roblox-r15", "r15@1", "idle"), "LowerTorso", "X")
    godot = _serie(_clipe("godot4", "godot-humanoid@1", "idle"), "Hips", "X")
    assert max(abs(v) for v in r15) > 0.1
    assert r15 == pytest.approx(godot, abs=1e-6)


def test_idle_mantem_g14_amplitude_minima_via_gate_e_via_rbxmx(tmp_path: Path) -> None:
    item = {"id": "idle.g14", "rig": {"modo": "motor6d", "esqueleto": "r15@1"}, "animacoes_base": ["idle"]}
    g14 = qc.verificar_g14_animacao_roblox(item, profiles.carregar("roblox-aa-80"), tmp_path, [])
    assert g14["status"] == "ok" and g14["medido"]["amplitude_max_graus"] >= 5.0

    from forge3d import qc_roblox_anim

    saida = tmp_path / "idle.rbxmx"
    rbx.exportar_animacao(LOTE_R15, ITEM_R15, clipe="idle", saida=saida)
    seq = ET.parse(saida).getroot().find(".//Item[@class='KeyframeSequence']")
    info = qc_roblox_anim._inspecionar_keyframe_sequence(seq)
    assert info["loop"] is True and info["amplitude_max_graus"] >= 5.0


# ------------------------------------------------------------------ walk / run: aducao e menos rolagem pelvica
@pytest.mark.parametrize(("perfil", "esq"), PERFIS_ESQ)
@pytest.mark.parametrize(("nome", "teto_pelve"), [("walk", 1.8), ("run", 2.5)])
def test_locomocao_quadril_z_reduzido_e_pernas_aduzidas(perfil: str, esq: str, nome: str, teto_pelve: float) -> None:
    clipe = _clipe(perfil, esq, nome)
    z_pelve = _serie(clipe, _osso(perfil, esq, "quadril"), "Z")
    assert max(abs(v) for v in z_pelve) <= teto_pelve + 1e-6
    ciclo = slice(0, -1)  # ultima chave repete a primeira (loop fechado)
    media_e = sum(_serie(clipe, _osso(perfil, esq, "perna_e"), "Z")[ciclo]) / (len(clipe["chaves"]) - 1)
    media_d = sum(_serie(clipe, _osso(perfil, esq, "perna_d"), "Z")[ciclo]) / (len(clipe["chaves"]) - 1)
    assert media_e > 2.0, f"perna esquerda nao aduz (+Z) em {nome}: media={media_e:.2f}"
    assert media_d < -2.0, f"perna direita nao aduz (-Z) em {nome}: media={media_d:.2f}"


@pytest.mark.parametrize(("perfil", "esq"), PERFIS_ESQ)
@pytest.mark.parametrize("nome", ["walk", "run"])
def test_locomocao_preserva_joelho_cotovelo_e_loop(perfil: str, esq: str, nome: str) -> None:
    clipe = _clipe(perfil, esq, nome)
    for chave in ("canela_e", "canela_d"):
        assert max(_serie(clipe, _osso(perfil, esq, chave), "X")) <= 1e-6
    for chave in ("antebraco_e", "antebraco_d"):
        assert min(_serie(clipe, _osso(perfil, esq, chave), "X")) >= -1e-6
    assert _assinatura(clipe["chaves"][0]) == _assinatura(clipe["chaves"][-1])


def test_walk_preserva_bounce_do_quadril_em_0_025() -> None:
    clipe = _clipe("roblox-r15", "r15@1", "walk")
    dzs = [
        float(p["deslocamento_m"][2])
        for ch in clipe["chaves"]
        for p in ch["poses"]
        if p["osso"] == "LowerTorso" and isinstance(p.get("deslocamento_m"), (list, tuple))
    ]
    assert max(dzs) == pytest.approx(0.025, abs=1e-3)


def _matriz_pose(modo: str, parte: str, graus: float) -> list[float]:
    pose = {"osso": parte, "graus": graus, "eixo": "Z"}
    clipe = {"nome": "walk", "fps": 24, "duracao_s": 1.0, "loop": True, "chaves": [
        {"frame": 0, "segundos": 0.0, "poses": [pose]}, {"frame": 24, "segundos": 1.0, "poses": [pose]}]}
    linhas, _ = rbx._sequencia_xml(clipe, 1, MPS, modo_rig=modo)
    raiz = ET.fromstring("<roblox>" + "".join(linhas) + "</roblox>")
    for it in raiz.iter("Item"):
        if it.get("class") == "Pose" and it.findtext("Properties/string[@name='Name']") == parte:
            cf = it.find("Properties/CoordinateFrame[@name='CFrame']")
            return [float(cf.findtext(f"R{i}{j}")) for i in range(3) for j in range(3)]
    raise AssertionError(f"Pose {parte} ausente no KeyframeSequence")


@pytest.mark.parametrize(("parte", "graus"), [("LeftUpperLeg", 5.0), ("RightUpperLeg", -5.0)])
def test_sequencia_xml_bone_mantem_sinal_e_motor6d_inverte_z_das_coxas(parte: str, graus: float) -> None:
    assert _matriz_pose("bone", parte, graus) == pytest.approx(rbx._matriz_rotacao(graus, "Z"), abs=1e-4)
    assert _matriz_pose("motor6d", parte, graus) == pytest.approx(rbx._matriz_rotacao(-graus, "Z"), abs=1e-4)


# ------------------------------------------------------------------ presets de postura por seed
def test_presets_postura_sao_cinco_e_incluem_neutro() -> None:
    from forge3d import animacao_presets

    assert len(animacao_presets.PRESETS_POSTURA) == 5 and len(set(animacao_presets.PRESETS_POSTURA)) == 5
    assert "neutro_relaxado" in animacao_presets.PRESETS_POSTURA
    assert tuple(animacao.PRESETS_POSTURA) == tuple(animacao_presets.PRESETS_POSTURA)


@pytest.mark.parametrize(("perfil", "esq"), PERFIS_ESQ)
def test_idle_por_seed_e_deterministico_distinto_e_fecha_loop(perfil: str, esq: str) -> None:
    clipes = {s: _clipe(perfil, esq, "idle", seed=s) for s in (101, 202, 303)}
    assert clipes[101] == _clipe(perfil, esq, "idle", seed=101)
    for a, b in ((101, 202), (202, 303), (101, 303)):
        assert _distancia(clipes[a], clipes[b]) > 0.1, f"seeds {a} e {b} produzem idle indistinguivel"
    for clipe in clipes.values():
        assert _assinatura(clipe["chaves"][0]) == _assinatura(clipe["chaves"][-1])


def test_preset_explicito_e_ausencia_de_seed_preservam_canonico() -> None:
    perfil = profiles.carregar("roblox-r15")
    canonico = animacao.clipes(perfil, "r15@1", ["idle", "walk"])
    assert animacao.clipes(perfil, "r15@1", ["idle", "walk"], seed=None, postura_preset=None) == canonico
    conf = animacao.clipes(perfil, "r15@1", ["idle"], postura_preset="confiante")
    assert conf == animacao.clipes(perfil, "r15@1", ["idle"], postura_preset="confiante")
    assert _assinatura(conf[0]["chaves"][0]) == _assinatura(conf[0]["chaves"][-1])


def test_variacao_seed_false_no_perfil_ignora_seed() -> None:
    perfil = copy.deepcopy(profiles.carregar("roblox-r15"))
    perfil["rig"]["postura"]["variacao_seed"] = False
    assert animacao.clipes(perfil, "r15@1", ["idle"], seed=101) == animacao.clipes(perfil, "r15@1", ["idle"])


@pytest.mark.parametrize("nome", ["walk", "run"])
def test_locomocao_com_seed_mantem_invariantes_biomecanicos(nome: str) -> None:
    clipe = _clipe("roblox-r15", "r15@1", nome, seed=101)
    assert max(_serie(clipe, "LeftLowerLeg", "X")) <= 1e-6 and max(_serie(clipe, "RightLowerLeg", "X")) <= 1e-6
    assert min(_serie(clipe, "LeftLowerArm", "X")) >= -1e-6 and min(_serie(clipe, "RightLowerArm", "X")) >= -1e-6
    assert max(abs(v) for v in _serie(clipe, "LowerTorso", "Z")) <= (1.8 if nome == "walk" else 2.5) + 1e-6
    assert _assinatura(clipe["chaves"][0]) == _assinatura(clipe["chaves"][-1])


# ------------------------------------------------------------------ Roblox SkinnedMesh R15 sem partes[]
_METROS = {
    "HumanoidRootPart": (0, 0.95, 0), "LowerTorso": (0, 1.0, 0), "UpperTorso": (0, 1.2, 0), "Head": (0, 1.52, 0),
    "LeftUpperArm": (0.22, 1.42, 0), "LeftLowerArm": (0.30, 1.14, 0), "LeftHand": (0.36, 0.90, 0),
    "LeftUpperLeg": (0.10, 0.92, 0), "LeftLowerLeg": (0.10, 0.50, 0), "LeftFoot": (0.10, 0.10, 0),
}
_METROS.update({n.replace("Left", "Right"): (-x, y, z) for n, (x, y, z) in list(_METROS.items()) if n.startswith("Left")})
ANC_RELAX = {n: [round(c / MPS, 5) for c in p] for n, p in _METROS.items()}
_METROS_45 = {**_METROS, "LeftLowerArm": (0.46, 1.18, 0), "LeftHand": (0.70, 0.94, 0),
              "RightLowerArm": (-0.46, 1.18, 0), "RightHand": (-0.70, 0.94, 0)}
ANC_A45 = {n: [round(c / MPS, 5) for c in p] for n, p in _METROS_45.items()}


def _lote_sem_partes(tmp_path: Path) -> Path:
    lote = tmp_path / "lote_skinned.yaml"
    lote.write_text("\n".join([
        "schema: forge3d/spec@6", "projeto: demo", "perfil: roblox-aa-80", f"destino_exportacao: {tmp_path / 'dest'}",
        "lote:", "  - id: heroi.skinned.01", "    tipo: criatura", "    rota: mesh", "    prompt: guerreiro",
        "    altura_metros: 1.8", "    seed: 5", "    auto_rig: true", "    esqueleto: r15@1",
        "    rig:", "      modo: skinned", "      esqueleto: r15@1",
    ]) + "\n", encoding="utf-8")
    return lote


def _manifesto(ancoras: dict | None) -> dict:
    rig = {"esqueleto": "r15@1", "ossos": 16, "modo": "skinned"}
    if ancoras is not None:
        rig["ancoras"] = ancoras
    return {"schema": "forge3d/manifest@7", "asset_id": "heroi.skinned.01", "geometry": {"bbox_m": [0.8, 1.8, 0.4]},
            "rig": rig, "files": []}


def _vec(node, tags="XYZ") -> list[float]:
    return [float(node.findtext(t)) for t in tags]


def test_exportar_r15_bone_sem_partes_emite_skinnedmesh_com_ancoras(tmp_path: Path) -> None:
    saida = tmp_path / "skinned.rbxlx"
    rel = rbx.exportar_r15(_lote_sem_partes(tmp_path), "heroi.skinned.01", saida=saida, metros_por_stud=MPS,
                           modo_rig="bone", manifesto=_manifesto(ANC_RELAX), exigir_asset_ids=False)
    assert (rel["modo_rig"], rel["partes"], rel["motores"]) == ("bone", 1, 0)
    raiz = ET.parse(saida).getroot()
    malhas = [i for i in raiz.iter("Item") if i.get("class") == "MeshPart"
              and i.findtext("Properties/string[@name='Name']") == "Forge3DMesh"]
    assert len(malhas) == 1
    tamanho = _vec(malhas[0].find("Properties/Vector3[@name='size']"))
    assert tamanho == pytest.approx([0.8 / MPS, 1.8 / MPS, 0.4 / MPS], rel=0.02)

    mundo: dict[str, list[float]] = {}

    def _visita(bone, pai):
        cf = bone.find("Properties/CoordinateFrame[@name='CFrame']")
        assert [float(cf.findtext(f"R{i}{j}")) for i in range(3) for j in range(3)] == pytest.approx(
            [1, 0, 0, 0, 1, 0, 0, 0, 1], abs=1e-6), "Bone R15 em repouso precisa de rotacao identidade"
        pos = [p + d for p, d in zip(pai, _vec(cf))]
        mundo[bone.findtext("Properties/string[@name='Name']")] = pos
        for filho in bone.findall("Item[@class='Bone']"):
            _visita(filho, pos)

    for raiz_bone in malhas[0].findall("Item[@class='Bone']"):
        _visita(raiz_bone, [0.0, 0.0, 0.0])
    assert set(mundo) == set(ANC_RELAX) and len(mundo) == 16
    for nome, esperado in ANC_RELAX.items():
        assert mundo[nome] == pytest.approx(esperado, abs=1e-3), f"Bone {nome} fora da ancora rig.ancoras"


def test_exportar_r15_bone_sem_partes_e_sem_ancoras_levanta_forge_error(tmp_path: Path) -> None:
    with pytest.raises(ForgeError):
        rbx.exportar_r15(_lote_sem_partes(tmp_path), "heroi.skinned.01", saida=tmp_path / "x.rbxlx",
                         metros_por_stud=MPS, modo_rig="bone", manifesto=_manifesto(None))


# ------------------------------------------------------------------ export-anim: ancoras, manifesto, modo_rig
def _angulo_max_braco(saida: Path) -> float:
    ang = 0.0
    for clipe in rbx.ler_place(saida)["clipes"]:
        for chave in clipe["chaves"]:
            for pose in chave["poses"]:
                if pose["osso"] == "LeftUpperArm":
                    m = pose["cframe"][3:]
                    ang = max(ang, math.degrees(math.acos(max(-1.0, min(1.0, (m[0] + m[4] + m[8] - 1.0) / 2.0)))))
    return ang


def test_exportar_animacao_com_ancoras_a45_derruba_braco_e_relaxadas_nao(tmp_path: Path) -> None:
    base = rbx.exportar_animacao(LOTE_R15, ITEM_R15, clipe="idle", saida=tmp_path / "base.rbxmx")
    a45 = rbx.exportar_animacao(LOTE_R15, ITEM_R15, clipe="idle", saida=tmp_path / "a45.rbxmx",
                                ancoras=ANC_A45, modo_rig="bone")
    relax = rbx.exportar_animacao(LOTE_R15, ITEM_R15, clipe="idle", saida=tmp_path / "relax.rbxmx",
                                  ancoras=ANC_RELAX, modo_rig="motor6d")
    assert a45["modo_rig"] == "bone" and a45["ancoras_aplicadas"] is True
    assert relax["modo_rig"] == "motor6d" and relax["ancoras_aplicadas"] is True
    assert base["ancoras_aplicadas"] is False
    assert _angulo_max_braco(tmp_path / "a45.rbxmx") >= 15.0
    assert _angulo_max_braco(tmp_path / "relax.rbxmx") == pytest.approx(_angulo_max_braco(tmp_path / "base.rbxmx"), abs=0.5)


def test_exportar_animacoes_aceita_manifesto_e_valida_modo_rig(tmp_path: Path) -> None:
    rel = rbx.exportar_animacoes(LOTE_R15, ITEM_R15, ["idle", "walk"], saida=tmp_path / "multi.rbxmx",
                                 manifesto=_manifesto(ANC_A45), modo_rig="bone")
    assert rel["modo_rig"] == "bone" and rel["ancoras_aplicadas"] is True and rel["clipes"] == ["idle", "walk"]
    with pytest.raises(ForgeError):
        rbx.exportar_animacoes(LOTE_R15, ITEM_R15, ["idle"], saida=tmp_path / "x.rbxmx", modo_rig="invalido")


def test_cli_export_anim_modo_rig_bone_com_manifesto(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    parser = construir_parser()
    assert parser.parse_args(["export-anim", "l.yaml", "--item", "x"]).modo_rig == "motor6d"
    with pytest.raises(SystemExit):
        parser.parse_args(["export-anim", "l.yaml", "--item", "x", "--modo-rig", "foo"])
    man = tmp_path / "man.json"
    man_dados = _manifesto(ANC_A45)
    man_dados["asset_id"] = ITEM_R15
    man.write_text(json.dumps(man_dados), encoding="utf-8")
    saida = tmp_path / "cli.rbxmx"
    rc = despachar(["export-anim", str(LOTE_R15), "--item", ITEM_R15, "--clipe", "idle", "--saida", str(saida),
                    "--modo-rig", "bone", "--manifesto", str(man), "--json"])
    rel = json.loads(capsys.readouterr().out)
    assert rc == 0 and saida.is_file()
    assert rel["modo_rig"] == "bone" and rel["ancoras_aplicadas"] is True


# ------------------------------------------------------------------ GAP-064 / GAP-067 #5 (matematica pura, bpy/mathutils falsos)
class _Vec3:
    def __init__(self, xyz=(0.0, 0.0, 0.0)) -> None:
        self.x, self.y, self.z = float(xyz[0]), float(xyz[1]), float(xyz[2])

    def __getitem__(self, i: int) -> float:
        return (self.x, self.y, self.z)[i]

    def __sub__(self, o):
        return _Vec3((self.x - o.x, self.y - o.y, self.z - o.z))

    def __add__(self, o):
        return _Vec3((self.x + o.x, self.y + o.y, self.z + o.z))

    def __mul__(self, k: float):
        return _Vec3((self.x * k, self.y * k, self.z * k))

    @property
    def length(self) -> float:
        return math.sqrt(self.x ** 2 + self.y ** 2 + self.z ** 2)

    @property
    def length_squared(self) -> float:
        return self.x ** 2 + self.y ** 2 + self.z ** 2

    def dot(self, o) -> float:
        return self.x * o.x + self.y * o.y + self.z * o.z


@pytest.fixture
def blender_puro(monkeypatch: pytest.MonkeyPatch):
    antes = set(sys.modules)
    monkeypatch.syspath_prepend(str(RAIZ / "blender"))
    if "mathutils" not in sys.modules:
        mu = types.ModuleType("mathutils")
        mu.Vector, mu.Matrix = _Vec3, object  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "mathutils", mu)
    if "bpy" not in sys.modules:
        monkeypatch.setitem(sys.modules, "bpy", types.ModuleType("bpy"))
    import autorig_grafo as ag
    import autorig_pesos_limites as apl

    yield ag, apl
    for nome in set(sys.modules) - antes:
        if nome.startswith("autorig"):
            del sys.modules[nome]


def _marcos(**ajustes) -> dict:
    m = {
        "altura": 2.0, "z_min": 0.0, "z_max": 2.0, "cy": 0.0, "torso_hw": 0.22, "neck_hw": 0.08,
        "leg_x_L": 0.28, "leg_x_R": -0.28, "shoulder_x_L": 0.38, "shoulder_x_R": -0.38,
        "elbow_x_L": 0.70, "elbow_x_R": -0.70, "shoulder_z": 1.50, "chest_top_z": 1.58, "neck_z": 1.66,
        "chest_z": 1.36, "spine1_z": 1.18, "spine_z": 1.06, "hip_z": 0.94, "leg_top_z": 0.84,
        "knee_z": 0.48, "ankle_z": 0.14, "head_top_z": 2.0,
        "braco_L": {"shoulder": _Vec3((0.38, 0, 1.50)), "elbow": _Vec3((0.70, 0, 1.20)), "wrist": _Vec3((0.52, 0, 0.90))},
        "braco_R": {"shoulder": _Vec3((-0.38, 0, 1.50)), "elbow": _Vec3((-0.70, 0, 1.20)), "wrist": _Vec3((-0.52, 0, 0.90))},
    }
    m.update(ajustes)
    return m


def test_gap064_raio_do_ombro_exclui_chifre_largo_e_aceita_ombreira(blender_puro) -> None:
    ag, apl = blender_puro
    m = _marcos()
    lim = apl._limites_anatomicos(m, tem_neck=True)
    assert lim["sh_x_eff"] > 0.0 and lim["cy"] == pytest.approx(m["cy"])
    for lado in (1.0, -1.0):
        assert apl._vertice_no_raio_ombro(_Vec3((lado * 0.52, 0, 1.72)), lim, m) is False  # ponta de chifre largo
        assert apl._vertice_no_raio_ombro(_Vec3((lado * 0.40, 0, 1.69)), lim, m) is False  # medial-alto acima do pescoco
        assert apl._vertice_no_raio_ombro(_Vec3((lado * 0.40, 0, 1.60)), lim, m) is True  # ombreira sobre a junta
        assert apl._vertice_no_raio_ombro(_Vec3((lado * 0.90, 0, 1.20)), lim, m) is True  # abaixo do corte: sempre livre
    for nome, lado in (("Shoulder.L", 1.0), ("Shoulder.R", -1.0)):
        assert ag._osso_permitido(nome, _Vec3((lado * 0.52, 0, 1.72)), m, True, tem_neck=True, lim=lim) is False
        assert ag._osso_permitido(nome, _Vec3((lado * 0.40, 0, 1.69)), m, True, tem_neck=True, lim=lim) is False
        assert ag._osso_permitido(nome, _Vec3((lado * 0.40, 0, 1.60)), m, True, tem_neck=True, lim=lim) is True


def test_gap067_5_cotovelo_abduzido_com_pulso_baixo_ativa_pose_abduzida(blender_puro) -> None:
    _ag, apl = blender_puro
    h = 2.0
    pulso = {"braco_L": {**_marcos()["braco_L"], "wrist": _Vec3((0.43, 0, 0.90))},
             "braco_R": {**_marcos()["braco_R"], "wrist": _Vec3((-0.43, 0, 0.90))}}
    # min_arm_low_x=0.43 <= sh_x+0.04h (0.46): so o ramo novo (> leg_abs+0.06h e > torso_hw+0.02h) o ativa.
    lim = apl._limites_anatomicos(_marcos(**pulso), tem_neck=True)
    assert lim["arm_hip_block_z"] > 0.9, "pose abduzida deveria ativar o bloqueio braco/quadril"
    assert lim["hips_max_x"] < 0.43 - 0.03 * h
    # Controle: cotovelo junto ao corpo nao e pose abduzida.
    junto = _marcos(elbow_x_L=0.30, elbow_x_R=-0.30, **{"braco_L": {**pulso["braco_L"], "elbow": _Vec3((0.30, 0, 1.20))},
                                                         "braco_R": {**pulso["braco_R"], "elbow": _Vec3((-0.30, 0, 1.20))}})
    assert apl._limites_anatomicos(junto, tem_neck=True).get("arm_hip_block_z", -1e9) < -1e8
