"""Invariantes de ponta a ponta (I1, I4, I8, I11) e contrato de exit code.

Estes testes rodam o Blender de verdade: sao a prova do portao P1, nao simulacao.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from forge3d import qc

RAIZ = Path(__file__).resolve().parents[2]
EXEMPLO = RAIZ / "examples" / "lote_01.yaml"

pytestmark = [pytest.mark.blender, pytest.mark.lento]


def _ambiente(home: Path) -> dict:
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["XDG_STATE_HOME"] = str(home / ".local" / "state")
    env["XDG_CONFIG_HOME"] = str(home / ".config")
    env["FORGE3D_ROOT"] = str(RAIZ)
    for chave in ("FORGE3D_HOME", "FORGE3D_CONFIG", "FORGE3D_JSON_OUT"):
        env.pop(chave, None)
    env["PYTHONPATH"] = str(RAIZ / "src")
    return env


def _rodar(args: list[str], env: dict) -> tuple[int, dict]:
    with tempfile.TemporaryDirectory(prefix="forge3d-cli-json-") as tmp_dir:
        json_out = Path(tmp_dir) / "saida.json"
        env_exec = dict(env)
        env_exec["FORGE3D_JSON_OUT"] = str(json_out)
        cmd = [sys.executable, "-m", "forge3d.cli.main", *args, "--json"]
        proc = subprocess.run(
            cmd,
            cwd=str(RAIZ),
            env=env_exec,
            capture_output=True,
            text=True,
            timeout=1800,
        )
        texto_arq = json_out.read_text(encoding="utf-8") if json_out.is_file() else ""
    bruto = texto_arq or proc.stdout
    try:
        dados = json.loads(bruto)
        if texto_arq and proc.stdout.strip():
            assert json.loads(proc.stdout) == dados
        return proc.returncode, dados
    except (ValueError, AssertionError) as exc:
        diag = (
            f"[gap-019-diag] stdout/json_out nao e JSON valido (exit {proc.returncode})\n"
            f"CMD={cmd}\nSTDOUT={proc.stdout}\nJSON_OUT={texto_arq}\nSTDERR={proc.stderr[-3000:]}"
        )
        print(diag, file=sys.stderr, flush=True)
        raise AssertionError(diag) from exc


@pytest.fixture(scope="module")
def execucao(tmp_path_factory):
    home = tmp_path_factory.mktemp("home")
    env = _ambiente(home)
    state = home / ".local" / "state" / "forge3d"
    codigo, relatorio = _rodar(["run", str(EXEMPLO)], env)
    saida = state / "saida" / "lote_01"
    return {
        "home": home,
        "env": env,
        "state": state,
        "saida": saida,
        "codigo": codigo,
        "relatorio": relatorio,
    }


def test_primeira_execucao_publica_tudo(execucao):
    assert execucao["codigo"] == 0, execucao["relatorio"]["itens"]
    resumo = execucao["relatorio"]["resumo"]
    assert resumo["publicados"] == 3
    assert resumo["falhas"] == 0
    assert resumo["reprovados"] == 0
    # espada: mesh+colisor+atlas = 3 · pocao: mesh+colisor+atlas = 3 · mob: mesh+colisor+atlas = 3
    assert len(execucao["relatorio"]["artifacts"]) == 9


def test_i8_escala_e_pivo_conforme_perfil(execucao):
    """Altura exportada bate com o declarado; pivo 'base' deixa a AABB no chao."""
    manifestos = sorted(execucao["saida"].glob("*.manifest.json"))
    assert len(manifestos) == 3
    por_id = {m.name.replace(".manifest.json", ""): json.loads(m.read_text()) for m in manifestos}

    guarda = por_id["mob.skeleton.guard"]
    assert abs(guarda["geometry"]["bbox_m"][1] - 1.85) / 1.85 * 100 <= 0.5
    assert guarda["qc"]["aprovado"] is True
    assert guarda["rig"]["ossos"] == 23
    assert guarda["rig"]["esqueleto"] == "godot-humanoid@1"

    espada = por_id["weapon.sword.fire.01"]
    assert abs(espada["geometry"]["bbox_m"][1] - 1.10) / 1.10 * 100 <= 0.5
    assert espada["colisao"]["tipo"] == "convex"
    assert espada["colisao"]["partes"] >= 1


def test_i11_idempotencia_rerun_nao_trabalha(execucao):
    codigo, relatorio = _rodar(["run", str(EXEMPLO)], execucao["env"])
    assert codigo == 0
    resumo = relatorio["resumo"]
    assert resumo["trabalho_executado"] == 0, resumo
    assert resumo["cache_hits"] == 3, resumo


def test_i4_verify_pega_arquivo_adulterado(execucao, tmp_path):
    destino = tmp_path / "saida_i4"
    shutil.copytree(execucao["saida"], destino)
    codigo, saida = _rodar(["verify", str(destino)], execucao["env"])
    assert codigo == 0 and saida["ok"] is True, saida

    alvo = sorted(destino.glob("weapon.sword.fire.01*"))[0]
    original = alvo.read_bytes()
    alvo.write_bytes(original + b"\x00aduterado")
    codigo, saida = _rodar(["verify", str(destino)], execucao["env"])
    assert codigo == 3, saida
    assert saida["ok"] is False
    assert any("hash divergente" in e["erro"] for e in saida["erros"])


def test_i1_determinismo_byte_identico(execucao, tmp_path):
    """Mesma spec + mesma versao => mesmo sha256, mesmo com cache vazio."""
    home = tmp_path / "home_i1"
    home.mkdir()
    env = _ambiente(home)
    state = home / ".local" / "state" / "forge3d"
    saida = state / "saida" / "lote_01"
    hashes = []
    for _ in range(2):
        shutil.rmtree(state / "cache", ignore_errors=True)
        shutil.rmtree(saida, ignore_errors=True)
        codigo, relatorio = _rodar(["run", str(EXEMPLO)], env)
        assert codigo == 0, relatorio["itens"]
        hashes.append(sorted((a["caminho"], a["sha256"]) for a in relatorio["artifacts"]))

    assert hashes[0] == hashes[1], "rota D1 nao e byte-identica entre execucoes"
    hashes_fixture = sorted((a["caminho"], a["sha256"]) for a in execucao["relatorio"]["artifacts"])
    assert hashes[0] == hashes_fixture


def test_i2_spec_invalida_sai_2_sem_tocar_provider(execucao, tmp_path):
    home = tmp_path / "home_i2"
    home.mkdir()
    env = _ambiente(home)
    ruim = tmp_path / "ruim.yaml"
    texto = EXEMPLO.read_text(encoding="utf-8").replace("altura_metros: 1.10", "altura_metros: -1")
    ruim.write_text(texto, encoding="utf-8")
    codigo, saida = _rodar(["run", str(ruim)], env)
    assert codigo == 2, saida
    assert saida["erro"]["codigo"] == "FORGE-E-SPEC"


def test_i5_qc_nao_tem_bypass():
    fontes = list((RAIZ / "src").rglob("*.py"))
    proibidos = ("--force", "--skip-qc", "--no-verify", "skip_qc")
    achados = [f"{p}:{t}" for p in fontes for t in proibidos if t in p.read_text(encoding="utf-8")]
    assert not achados, f"bypass de QC encontrado: {achados}"


def test_i13_destino_fora_da_allowlist_sai_2(execucao, tmp_path):
    home = tmp_path / "home_i13"
    home.mkdir()
    env = _ambiente(home)
    alvo = tmp_path / "destino-arbitrario"
    texto = EXEMPLO.read_text(encoding="utf-8").replace(
        "destino_exportacao: ~/.local/state/forge3d/saida/lote_01",
        f"destino_exportacao: {alvo}",
    )
    spec_ruim = tmp_path / "lote.yaml"
    spec_ruim.write_text(texto, encoding="utf-8")
    codigo, saida = _rodar(["plan", str(spec_ruim)], env)
    assert codigo == 2, saida
    assert saida["erro"]["codigo"] == "FORGE-E-DESTINO"


def test_rota_import_normaliza_asset_existente(execucao, tmp_path):
    """Rota import: um GLB ja pronto passa pelo mesmo trilho e vira outro tamanho/pivo."""
    origem = execucao["saida"] / "weapon.sword.fire.01.glb"
    assert origem.is_file()

    home = tmp_path / "home_import"
    home.mkdir()
    env = _ambiente(home)
    state = home / ".local" / "state" / "forge3d"

    spec_import = tmp_path / "lote_import.yaml"
    spec_import.write_text(
        "\n".join(
            [
                "schema: forge3d/spec@1",
                "projeto: demo",
                "perfil: godot4",
                "destino_exportacao: ~/.local/state/forge3d/saida/importado",
                "estilo_global: blocky_voxel",
                "lote:",
                "  - id: prop.reliquia.importada.01",
                "    tipo: prop_equipavel",
                "    rota: import",
                f"    origem: {origem}",
                "    altura_metros: 0.55",
                "    pivot: base",
                "    limite_triangulos: 800",
                "    colisao: convex",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    codigo, relatorio = _rodar(["run", str(spec_import)], env)
    assert codigo == 0, relatorio["itens"]

    destino = state / "saida" / "importado"
    manifesto = json.loads((destino / "prop.reliquia.importada.01.manifest.json").read_text())
    altura = manifesto["geometry"]["bbox_m"][1]
    assert abs(altura - 0.55) / 0.55 * 100 <= 0.5, altura
    assert manifesto["providers"]["geometry"]["name"] == "import"
    assert manifesto["qc"]["aprovado"] is True


def test_i4_verify_reexecuta_gates_contra_manifesto(execucao, tmp_path):
    """C2: trocar a altura esperada no manifesto (sem tocar no GLB) tem que reprovar no verify."""
    destino = tmp_path / "saida_i4_gates"
    shutil.copytree(execucao["saida"], destino)
    manifesto = destino / "mob.skeleton.guard.manifest.json"
    original = manifesto.read_text(encoding="utf-8")
    man = json.loads(original)
    for gate in man["qc"]["gates"]:
        if gate["id"] == "G2":
            gate["medido"]["esperado_m"] = 9.99
    manifesto.write_text(json.dumps(man, indent=1), encoding="utf-8")
    codigo, saida = _rodar(["verify", str(destino)], execucao["env"])
    assert codigo == 3, saida
    assert saida["ok"] is False
    assert any("QC reexecutado" in erro["erro"] for erro in saida["erros"]), saida["erros"]


def test_kit_corpo_capa_arma_publica_e_verifica(tmp_path):
    """P3-D: corpo (rig), capa (estatica no Chest) e arma (empunhadura) como assets distintos."""
    home = tmp_path / "home"
    home.mkdir()
    env = _ambiente(home)
    lote = RAIZ / "examples" / "lote_03_kit.yaml"
    codigo, relatorio = _rodar(["run", str(lote)], env)
    assert codigo == 0, relatorio["itens"]
    assert relatorio["resumo"]["publicados"] == 3

    destino = home / ".local" / "state" / "forge3d" / "saida" / "kit_sentinel"
    manifestos = {
        p.name.replace(".manifest.json", ""): json.loads(p.read_text())
        for p in destino.glob("*.manifest.json")
    }
    assert len(manifestos) == 3
    corpo = manifestos["personagem.sentinel.corpo.01"]
    capa = manifestos["personagem.sentinel.capa.01"]
    arma = manifestos["personagem.sentinel.arma.01"]
    assert corpo["rig"]["ossos"] == 23
    assert capa["rig"] is None
    assert arma["rig"] is None
    assert capa["colisao"]["tipo"] == "none"
    assert arma["colisao"]["tipo"] == "convex"

    codigo, saida = _rodar(["verify", str(destino)], env)
    assert codigo == 0 and saida["ok"] is True, saida

def test_r15_blocky_gera_16_ossos_com_nomes_r15(tmp_path):
    """P2: o blocky com `esqueleto: r15@1` produz os 16 nomes de parte do R15 e passa no G6."""
    home = tmp_path / "home"
    home.mkdir()
    env = _ambiente(home)
    lote = RAIZ / "examples" / "lote_09_r15.yaml"
    codigo, relatorio = _rodar(["run", str(lote)], env)
    assert codigo == 0, relatorio["itens"]

    destino = home / ".local" / "state" / "forge3d" / "saida" / "r15"
    manifesto = json.loads((destino / "personagem.r15.guard.01.manifest.json").read_text())
    assert manifesto["rig"] == {"esqueleto": "r15@1", "ossos": 16}
    gltf, binario_glb = qc.ler_glb_bin(destino / "personagem.r15.guard.01.glb")
    nomes = qc.analisar(gltf)["nomes_ossos"]
    assert len(nomes) == 16
    assert "HumanoidRootPart" in nomes
    assert "LeftHand" in nomes
    assert manifesto["qc"]["aprovado"] is True

    # D62 (opcao A da P2): o glb do roblox-r15 sai em studs e o manifesto declara a unidade.
    # `geometry.bbox_m` continua em metros; o arquivo tem 1,85 m * 3,5714 = 6,607 studs.
    assert manifesto["schema"] == "forge3d/manifest@7"
    assert manifesto["unidades_export"] == {"metros_por_unidade": 0.28, "escala_saida": 3.5714}

    # D66: o clipe base `idle` embutido no glb, retargetado para os 16 ossos do R15
    assert [a["nome"] for a in manifesto["animacoes"]] == ["idle"]
    clipe = manifesto["animacoes"][0]
    assert clipe["duracao_s"] > 1.5
    ossos_movendo = set(clipe["ossos"])
    assert {"UpperTorso", "LowerTorso", "Head", "LeftUpperArm", "RightUpperArm"} <= ossos_movendo
    assert len(qc.animacoes(gltf, binario_glb)[0]["movendo"]) >= 5
    assert abs(manifesto["geometry"]["bbox_m"][1] - 1.85) / 1.85 * 100 <= 0.5
    altura_studs = qc.analisar(gltf)["bbox_m"][1]
    assert abs(altura_studs - 6.607) / 6.607 * 100 <= 0.5, altura_studs

    codigo, saida = _rodar(["verify", str(destino)], env)
    assert codigo == 0 and saida["ok"] is True, saida
