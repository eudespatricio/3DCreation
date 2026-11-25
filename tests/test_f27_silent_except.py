"""Testes F27 — zero except silencioso (AST + diagnostico real) e PIPELINE_VERSION 0.9.5."""

from __future__ import annotations

import ast
import importlib.util
import io
import json
import re
import sys
import types
from pathlib import Path
from typing import Any

import pytest

import forge3d
from forge3d import mcp_server, post
from forge3d.errors import ForgeError
from forge3d.providers import cloud_ai
from forge3d.vault import VaultCC0

RAIZ = Path(__file__).resolve().parents[1]


def _carregar_modulo(nome: str, rel_path: str) -> Any:
    spec = importlib.util.spec_from_file_location(nome, RAIZ / rel_path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _instalar_stubs_blender_minimos(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Instala stubs minimos de bpy/bmesh/mathutils/autorig/smart_fit para testes sem Blender."""
    estado: dict[str, Any] = {"imagens_carregadas": [], "shade_smooth_erro": None}

    class _Vec:
        def __init__(self, coords=(0.0, 0.0, 0.0)) -> None:
            vals = list(coords)
            self.x = float(vals[0])
            self.y = float(vals[1])
            self.z = float(vals[2])

        def __getitem__(self, idx: int) -> float:
            return (self.x, self.y, self.z)[idx]

        def __setitem__(self, idx: int, val: float) -> None:
            if idx == 0:
                self.x = float(val)
            elif idx == 1:
                self.y = float(val)
            else:
                self.z = float(val)

        @property
        def length(self) -> float:
            return (self.x**2 + self.y**2 + self.z**2) ** 0.5

        def normalize(self) -> None:
            ln = self.length
            if ln > 1e-9:
                self.x /= ln
                self.y /= ln
                self.z /= ln

        def __add__(self, other: _Vec) -> _Vec:
            return _Vec((self.x + other.x, self.y + other.y, self.z + other.z))

        def __sub__(self, other: _Vec) -> _Vec:
            return _Vec((self.x - other.x, self.y - other.y, self.z - other.z))

        def __mul__(self, escalar: float) -> _Vec:
            return _Vec((self.x * escalar, self.y * escalar, self.z * escalar))

        def __neg__(self) -> _Vec:
            return _Vec((-self.x, -self.y, -self.z))

    class _Mat:
        def copy(self) -> _Mat:
            return self

        def identity(self) -> None:
            return None

        def __matmul__(self, other: _Vec) -> _Vec:
            return _Vec((other.x, other.y, other.z))

    class _FakeVert:
        def __init__(self, x: float, y: float, z: float) -> None:
            self.co = _Vec((x, y, z))

    class _FakeMesh:
        def __init__(self, nome: str = "mesh") -> None:
            self.name = nome
            self.vertices = [_FakeVert(-0.1, -0.1, 0.0), _FakeVert(0.1, 0.1, 0.4)]
            self.polygons = [types.SimpleNamespace(use_smooth=False)]
            self.materials = types.SimpleNamespace(clear=lambda: None, append=lambda _m: None)

        def transform(self, _mat: Any) -> None:
            return None

        def update(self) -> None:
            return None

        def shade_smooth(self) -> None:
            err = estado.get("shade_smooth_erro")
            if err is not None:
                raise err

        def set_sharp_from_angle(self, angle: float = 0.0) -> None:
            _ = angle

    class _FakeObj:
        def __init__(self, nome: str) -> None:
            self.name = nome
            self.type = "MESH"
            self.data = _FakeMesh(nome)
            self.matrix_world = _Mat()

        def select_set(self, _flag: bool) -> None:
            return None

    objetos_cena: list[_FakeObj] = []

    def _add_cyl(**_kw: Any) -> None:
        obj = _FakeObj(f"cyl_{len(objetos_cena)}")
        objetos_cena.append(obj)
        bpy_mod.context.active_object = obj
        bpy_mod.context.view_layer.objects.active = obj

    def _export_gltf(filepath: str, **_kw: Any) -> None:
        Path(filepath).write_bytes(b"glTF\x02\x00\x00\x00")

    def _load_image(caminho: str, **_kw: Any) -> Any:
        estado["imagens_carregadas"].append(caminho)
        raise OSError(f"falha simulada ao ler {caminho}")

    fake_bsdf = types.SimpleNamespace(
        inputs={
            "Base Color": types.SimpleNamespace(default_value=(0, 0, 0, 1)),
            "Metallic": types.SimpleNamespace(default_value=0.0),
            "Roughness": types.SimpleNamespace(default_value=0.5),
        }
    )

    bpy_mod = types.ModuleType("bpy")
    bpy_mod.utils = types.SimpleNamespace(
        user_resource=lambda _kind: (_ for _ in ()).throw(RuntimeError("sem user_resource"))
    )
    bpy_mod.data = types.SimpleNamespace(
        images=types.SimpleNamespace(load=_load_image),
        objects=types.SimpleNamespace(remove=lambda *_a, **_k: None),
        materials=types.SimpleNamespace(
            new=lambda _n: types.SimpleNamespace(
                use_nodes=True,
                node_tree=types.SimpleNamespace(nodes={"Principled BSDF": fake_bsdf}),
            )
        ),
    )
    bpy_mod.context = types.SimpleNamespace(
        scene=types.SimpleNamespace(objects=objetos_cena),
        view_layer=types.SimpleNamespace(
            update=lambda: None,
            objects=types.SimpleNamespace(active=None),
        ),
        active_object=None,
    )
    bpy_mod.ops = types.SimpleNamespace(
        wm=types.SimpleNamespace(read_factory_settings=lambda **_k: objetos_cena.clear()),
        import_scene=types.SimpleNamespace(gltf=lambda **_k: None),
        mesh=types.SimpleNamespace(primitive_cylinder_add=_add_cyl),
        object=types.SimpleNamespace(
            select_all=lambda **_k: None,
            join=lambda: None,
        ),
        export_scene=types.SimpleNamespace(gltf=_export_gltf),
    )

    bmesh_inst = types.SimpleNamespace(
        verts=[1, 2, 3],
        edges=[],
        faces=[1, 2],
        from_mesh=lambda _m: None,
        transform=lambda _m: None,
        to_mesh=lambda _m: None,
        free=lambda: None,
    )
    bmesh_mod = types.ModuleType("bmesh")
    bmesh_mod.new = lambda: bmesh_inst
    bmesh_mod.ops = types.SimpleNamespace(
        remove_doubles=lambda *_a, **_k: None,
        holes_fill=lambda *_a, **_k: None,
        triangulate=lambda *_a, **_k: None,
        recalc_face_normals=lambda *_a, **_k: None,
    )

    mathutils_mod = types.ModuleType("mathutils")
    mathutils_mod.Matrix = _Mat
    mathutils_mod.Vector = _Vec
    bvhtree_mod = types.ModuleType("mathutils.bvhtree")
    bvhtree_mod.BVHTree = types.SimpleNamespace(
        FromBMesh=lambda _bm: types.SimpleNamespace(ray_cast=lambda *_a: (None, None, None, None))
    )

    autorig_mod = types.ModuleType("autorig")
    smart_fit_mod = types.ModuleType("smart_fit")
    smart_fit_mod.encaixar_contato_bvh = lambda *_a, **_k: (_ for _ in ()).throw(
        RuntimeError("smart_fit bvh falhou")
    )
    smart_fit_mod.auto_grip_cilindrico = lambda *_a, **_k: (_ for _ in ()).throw(
        RuntimeError("smart_fit grip falhou")
    )

    for nome, mod in {
        "bpy": bpy_mod,
        "bmesh": bmesh_mod,
        "mathutils": mathutils_mod,
        "mathutils.bvhtree": bvhtree_mod,
        "autorig": autorig_mod,
        "smart_fit": smart_fit_mod,
    }.items():
        monkeypatch.setitem(sys.modules, nome, mod)

    estado["FakeObj"] = _FakeObj
    return estado


def test_f27_ast_zero_silent_except_src_blender_tools() -> None:
    """Garante zero except silencioso em src/forge3d, blender e tools (incluindo blocos multi-linha)."""
    silenciosos: list[str] = []
    alvos_estritos = {
        "src/forge3d/mcp_server.py",
        "src/forge3d/vault.py",
        "blender/modular_armor.py",
        "tools/i23d_infer.py",
        "tools/trellis2_infer.py",
        "tools/kitbash_composer.py",
        "tools/vault_sync_cc0.py",
        "tools/pose_guard.py",
        "tools/concept_infer.py",
    }
    for base in ("src/forge3d", "blender", "tools"):
        for arq in sorted((RAIZ / base).rglob("*.py")):
            rel = str(arq.relative_to(RAIZ))
            arvore = ast.parse(arq.read_text(encoding="utf-8"), filename=rel)
            for no in ast.walk(arvore):
                if not isinstance(no, ast.ExceptHandler):
                    continue
                amplo = no.type is None or (
                    isinstance(no.type, ast.Name) and no.type.id in ("Exception", "BaseException")
                )
                if not amplo:
                    continue
                if len(no.body) == 1:
                    stmt = no.body[0]
                    eh_sil = isinstance(stmt, (ast.Pass, ast.Continue)) or (
                        isinstance(stmt, ast.Return)
                        and (
                            stmt.value is None
                            or (isinstance(stmt.value, ast.Constant) and stmt.value.value in (None, False))
                        )
                    )
                    if eh_sil:
                        silenciosos.append(f"{rel}:{no.lineno}")
                if rel in alvos_estritos:
                    src_blk = "\n".join(ast.unparse(s) for s in no.body)
                    tem_diag = any(
                        tok in src_blk
                        for tok in ("stderr", "print(", "warn", "log", "erro_interno", "raise", "'erro'", '"erro"')
                    )
                    if not tem_diag:
                        silenciosos.append(f"{rel}:{no.lineno} (sem diagnostico)")
    assert silenciosos == [], f"handlers silenciosos encontrados: {silenciosos}"


def test_f27_mcp_server_eh_binario_narrow_and_diagnostic(capsys: pytest.CaptureFixture[str]) -> None:
    assert mcp_server._eh_binario(io.StringIO("x")) is False
    assert mcp_server._eh_binario(io.BytesIO(b"x")) is True
    assert mcp_server._eh_binario(types.SimpleNamespace(mode="rb")) is True
    assert mcp_server._eh_binario(types.SimpleNamespace(mode="w")) is False

    class _UnsupportedRead:
        def read(self, _n: int = 0) -> bytes:
            raise io.UnsupportedOperation("not readable")

    assert mcp_server._eh_binario(_UnsupportedRead()) is False
    err = capsys.readouterr().err
    assert "UnsupportedOperation" in err

    class _BuggyStream:
        def read(self, _n: int = 0) -> bytes:
            raise RuntimeError("falha inesperada")

    with pytest.raises(RuntimeError, match="falha inesperada"):
        mcp_server._eh_binario(_BuggyStream())

    saida_chunks: list[str] = []
    escritor = types.SimpleNamespace(
        mode="w",
        write=lambda s: saida_chunks.append(s),
        flush=lambda: None,
    )
    req = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}) + "\n"
    assert mcp_server.servir(io.StringIO(req), escritor) == 0
    assert json.loads(saida_chunks[0])["id"] == 1


def test_f27_vault_buscar_semantico_warning_on_gemini_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    vault = VaultCC0(tmp_path / "vault")
    glb = tmp_path / "blade.glb"
    glb.write_bytes(b"glTF\x02\x00\x00\x00")
    vault.registrar_ativo(
        asset_id="kb.blade",
        caminho=glb,
        tipo="kitbash_part",
        categoria="weapon",
        licenca="CC0",
        origem="kenney",
        nome="Steel Blade",
        tags=["blade", "sword"],
    )

    monkeypatch.setattr(cloud_ai, "gemini_disponivel", lambda: (True, "ok"))
    monkeypatch.setattr(
        cloud_ai,
        "gerar_embedding_gemini",
        lambda *_a, **_k: (_ for _ in ()).throw(ForgeError("FORGE-E-TEST", "boom gemini", 5)),
    )
    res = vault.buscar_semantico("blade", usar_gemini_online=True)
    assert len(res) == 1
    assert res[0]["asset_id"] == "kb.blade"
    assert res[0]["metodo_busca"] == "lexical_bm25"
    assert "boom gemini" in res[0]["aviso_embedding"]
    assert "boom gemini" in capsys.readouterr().err

    monkeypatch.setattr(
        cloud_ai,
        "gerar_embedding_gemini",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("bug nao previsto")),
    )
    with pytest.raises(RuntimeError, match="bug nao previsto"):
        vault.buscar_semantico("blade", usar_gemini_online=True)


def test_f27_modular_armor_diagnostics_with_bpy_stub(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    estado = _instalar_stubs_blender_minimos(monkeypatch)
    mod = _carregar_modulo("modular_armor_test_f27", "blender/modular_armor.py")

    with pytest.raises(SystemExit):
        mod._encontrar_mhclo("item_inexistente_f27", subpasta="clothes")
    err_mh = capsys.readouterr().err
    assert "user_resource('CONFIG') indisponivel" in err_mh

    tex_existente = next((RAIZ / "blender" / "textures_pbr").glob("*.png"))
    assert mod._carregar_textura_pbr_local(tex_existente.name) is None
    err_tex = capsys.readouterr().err
    assert "falha ao carregar textura local" in err_tex

    estado["shade_smooth_erro"] = RuntimeError("shade_smooth indisponivel")
    obj = estado["FakeObj"]("ArmaduraTeste")
    mod._aplicar_suavizacao_modular(obj)
    err_sm = capsys.readouterr().err
    assert "aviso suavizacao modular" in err_sm


def test_f27_i23d_infer_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mod = _carregar_modulo("i23d_infer_test_f27", "tools/i23d_infer.py")

    info = mod._suavizar_malha_taubin(object(), iteracoes=2)
    assert info["aplicado"] is False
    assert "erro" in info
    assert "suavizacao Taubin falhou" in capsys.readouterr().err

    fake_onnx = types.ModuleType("onnxruntime")
    fake_onnx.SessionOptions = lambda: (_ for _ in ()).throw(RuntimeError("ort quebrado"))
    monkeypatch.setitem(sys.modules, "onnxruntime", fake_onnx)

    def _fake_new_session(modelo: str, sess_opts: Any = None, **_kw: Any) -> str:
        _ = sess_opts
        if modelo != "u2net":
            raise ConnectionError("offline")
        return "sess:u2net"

    fake_rembg = types.ModuleType("rembg")
    fake_rembg.__file__ = "/fake/rembg.py"
    fake_rembg.new_session = _fake_new_session
    monkeypatch.setitem(sys.modules, "rembg", fake_rembg)

    sess, usado, fallback = mod._criar_sessao_rembg("birefnet-general")
    assert (sess, usado, fallback) == ("sess:u2net", "u2net", True)
    err_rembg = capsys.readouterr().err
    assert "onnxruntime SessionOptions indisponivel" in err_rembg
    assert "fallback para 'u2net'" in err_rembg


def test_f27_tools_diagnostics_vault_sync_kitbash_pose_concept(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    vs = _carregar_modulo("vault_sync_f27", "tools/vault_sync_cc0.py")
    vault = VaultCC0(tmp_path / "v_sync")
    glb = tmp_path / "part.glb"
    glb.write_bytes(b"glTF\x02\x00\x00\x00")
    vault.registrar_ativo(
        asset_id="kb.part",
        caminho=glb,
        tipo="kitbash_part",
        categoria="weapon",
        licenca="CC0",
        origem="kenney",
        nome="Grip",
    )
    monkeypatch.setattr(vs.cloud_ai, "gemini_disponivel", lambda: (True, "ok"))
    monkeypatch.setattr(
        vs.cloud_ai,
        "gerar_embedding_gemini",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("rede indisponivel")),
    )
    assert vs.sincronizar_embeddings_vault(vault) == 1
    cap_vs = capsys.readouterr()
    assert cap_vs.out == ""
    assert "offline-sha256" in cap_vs.err

    _instalar_stubs_blender_minimos(monkeypatch)
    kc = _carregar_modulo("kitbash_f27", "tools/kitbash_composer.py")
    job_in = tmp_path / "kb_in.json"
    job_out = tmp_path / "kb_out.json"
    out_glb = tmp_path / "kb_out.glb"
    job_in.write_text(
        json.dumps({"out_glb": str(out_glb), "pecas": [{"id": "base"}, {"id": "top", "snap_para": "base"}]}),
        encoding="utf-8",
    )
    assert kc._executar_worker_blender(job_in, job_out) == 0
    dados_kb = json.loads(job_out.read_text(encoding="utf-8"))
    assert "smart_fit_erro" in dados_kb["pecas_montadas"][1]["snap"]
    assert "fallback_motivo" in dados_kb["grip_info"]
    err_kb = capsys.readouterr().err
    assert "encaixar_contato_bvh falhou" in err_kb
    assert "auto_grip_cilindrico falhou" in err_kb

    pg = _carregar_modulo("pose_guard_f27", "tools/pose_guard.py")
    from PIL import Image

    src_png = tmp_path / "opaca.png"
    out_png = tmp_path / "recorte.png"
    im = Image.new("RGBA", (32, 32), (240, 240, 240, 255))
    for y in range(8, 24):
        for x in range(12, 20):
            im.putpixel((x, y), (40, 50, 90, 255))
    im.save(src_png)
    fake_rembg_pg = types.ModuleType("rembg")
    fake_rembg_pg.new_session = lambda _m: (_ for _ in ()).throw(RuntimeError("sem cache rembg"))
    monkeypatch.setitem(sys.modules, "rembg", fake_rembg_pg)
    res_pg = pg.decompor_silhueta_arma(str(src_png), str(out_png))
    assert res_pg["ok"] is True
    assert res_pg.get("avisos")
    assert "rembg indisponivel" in capsys.readouterr().err

    ci = _carregar_modulo("concept_infer_f27", "tools/concept_infer.py")

    class _Loader:
        @staticmethod
        def from_pretrained(*_a: Any, variant: str | None = None, **_kw: Any) -> str:
            if variant == "fp16":
                raise OSError("sem fp16")
            return "pipe_fp32"

    avisos_ci: list[str] = []
    assert ci._carregar_com_fallback_fp16(_Loader, "modelo", avisos=avisos_ci, label="txt2img") == "pipe_fp32"
    assert len(avisos_ci) == 1
    assert "fallback sem variant=fp16" in capsys.readouterr().err


def test_f27_pipeline_version_0_9_5_consistency() -> None:
    pyproject = (RAIZ / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.MULTILINE)
    assert m is not None
    assert m.group(1) == "0.9.13"
    assert forge3d.__version__ == "0.9.13"
    assert forge3d.PIPELINE_VERSION == "0.9.13"
    assert post.PIPELINE_VERSION == "0.9.13"
