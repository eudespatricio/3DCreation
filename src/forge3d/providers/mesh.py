"""Rota ``mesh`` e sub-rotas explicitas (``i23d``, ``template``, ``procedural``, ``extrude_2d``).

Fachada modular (<= 500L) que delega diagnosticos, templates e inferencia i23d mantendo
compatibilidade integral de monkeypatch e contratos AST em ``forge3d.providers.mesh``.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Any

from .. import locks, paths
from . import concept_views_origem as _views_origem
from . import mesh_armor_proc as _armor_proc
from . import mesh_diag as _diag
from . import mesh_i23d as _i23d
from . import mesh_pose_concept as _pose_concept
from . import mesh_subrotas as _sub
from . import mesh_templates as _tmpl
from . import mesh_trellis as _trellis
from .base import RawAsset

VERSAO = _diag.VERSAO
MODELO_PADRAO = _diag.MODELO_PADRAO
MODELO_HF = _diag.MODELO_HF
VRAM_MINIMA_MB = _diag.VRAM_MINIMA_MB
TIMEOUT_S = _diag.TIMEOUT_S
SUBROTAS_EXPLICITAS = _diag.SUBROTAS_EXPLICITAS
_DIAGNOSTICO = _diag._DIAGNOSTICO

_REEXPORTS = (locks, paths, subprocess)

_device = _diag._device
modelo_escolhido = _diag.modelo_escolhido
dir_venv = _diag.dir_venv
dir_vendor = _diag.dir_vendor
dir_modelos = _diag.dir_modelos
pesos_triposr = _diag.pesos_triposr
_cache_hf = _diag._cache_hf
script_inferencia = _diag.script_inferencia
script_pose_guard = _diag.script_pose_guard
script_delight = _diag.script_delight
script_template_prep = _diag.script_template_prep
script_template_body = _diag.script_template_body
script_modular_armor = _diag.script_modular_armor
script_organic_sculpt = _diag.script_organic_sculpt
_python_imagem = _diag._python_imagem
_rembg_modelo = _diag._rembg_modelo
_pose_guard_modo = _diag._pose_guard_modo
_qualidade = _diag._qualidade
_delight_ativo = _diag._delight_ativo
_usar_extrude_2d = _diag._usar_extrude_2d
_extrair_estilo_makehuman = _diag._extrair_estilo_makehuman
_usar_makehuman_cabelo = _diag._usar_makehuman_cabelo
_usar_modular_armor = _diag._usar_modular_armor
mpfb2_cc0_disponivel = _diag.mpfb2_cc0_disponivel
_usar_template_humanoide = _diag._usar_template_humanoide
_usar_template_criatura = _diag._usar_template_criatura
_vram_minima_mb = _diag._vram_minima_mb
_vram_livre_mb = _diag._vram_livre_mb
_diagnostico = _diag._diagnostico
_politica_rembg = _diag._politica_rembg
_alfa_util = _diag._alfa_util
_decidir_rembg = _diag._decidir_rembg
_preflight_concept_item = _diag._preflight_concept_item
_resolver_subrota = _sub.resolver_subrota
_validar_subrota_item = _sub.validar_subrota_item


def _preflight_blender_binario() -> tuple[bool, str]:
    from .. import post
    from ..errors import ForgeError

    try:
        post.binario()
    except ForgeError as exc:
        return False, exc.mensagem
    return True, "ok"


class MeshProvider:
    nome = "mesh"
    determinism = "D2"  # image-to-3D nunca e D1 (D7)
    usa_gpu = True
    _rota_explicita: str | None = None

    @property
    def versao(self) -> str:
        """Versao efetiva: entra na chave de cache (D6) e muda com as opcoes de env."""
        from . import concept as _concept

        rembg = _politica_rembg()
        rembg_mod = _rembg_modelo().replace("/", "_").replace(":", "_")
        pg_mode = _pose_guard_modo(None)
        delight = "1" if _delight_ativo(None) else "0"
        qualidade = _qualidade(None)
        mc = os.environ.get("FORGE3D_MC_RESOLUTION", "256").strip()
        tex = os.environ.get("FORGE3D_TEX_PX", "1024").strip()
        concept_mod = os.environ.get("FORGE3D_MODELO_CONCEPT", "sd15").strip().replace("/", "_")
        c_step = os.environ.get("FORGE3D_CONCEPT_PASSOS", "25").strip()
        c_w = os.environ.get("FORGE3D_CONCEPT_LARGURA", "512").strip()
        c_h = os.environ.get("FORGE3D_CONCEPT_ALTURA", "512").strip()
        c_g = os.environ.get("FORGE3D_CONCEPT_GUIDANCE", "7.5").strip()
        tmpl = "1" if os.environ.get("FORGE3D_HUMANOIDE_TEMPLATE", "").strip() == "1" else "0"
        dev = _device().replace(":", "").replace("/", "_")
        mod_mesh = modelo_escolhido()
        suf_trellis = f"+{_trellis.cache_tag_trellis2()}" if mod_mesh == "trellis" else ""
        return (
            f"{VERSAO}+mc{mc}+tex{tex}+rembg{rembg}"
            f"+rm{rembg_mod}+pg{pg_mode}+dl{delight}+q{qualidade}"
            f"+concept{concept_mod}@{_concept.VERSAO}"
            f"+p{_concept.estado_pose_cache()}+c{c_w}x{c_h}s{c_step}g{c_g}+cut2+tx3+tmpl2_{tmpl}+mh1+dev{dev}+m{mod_mesh}{suf_trellis}"
        )

    def _licenca(self) -> dict:
        from . import LICENCAS

        modelo = modelo_escolhido()
        if modelo == "trellis":
            _trellis.validar_modelo_trellis_licenca()
            return dict(LICENCAS["trellis"])
        if modelo not in LICENCAS:
            from ..errors import erro_licenca

            raise erro_licenca(
                f"FORGE3D_MODELO_MESH='{modelo}' fora da allowlist comercial. Permitidos: {', '.join(sorted(LICENCAS))}",
                modelo=modelo,
            )
        return dict(LICENCAS[modelo])

    @property
    def licenca(self) -> dict:
        return self._licenca()

    def capabilities(self) -> set[str]:
        return {"organic", "riggable", "pbr", "detail"}

    def _custo_i23d(self, item: dict) -> dict:
        tem_origem = bool(str(item.get("origem") or "").strip())
        if modelo_escolhido() == "trellis":
            return {"segundos_estimados": 320.0 if not tem_origem else 300.0, "vram_mb": 4500, "disco_mb": 250}
        if _device().startswith("cpu"):
            return {"segundos_estimados": 220.0 if not tem_origem else 200.0, "vram_mb": 0, "disco_mb": 4500}
        if not tem_origem:
            return {"segundos_estimados": 40.0, "vram_mb": 3500, "disco_mb": 4500}
        return {"segundos_estimados": 25.0, "vram_mb": 3200, "disco_mb": 250}

    def custo(self, item: dict, perfil: dict) -> dict:
        tem_origem = bool(str(item.get("origem") or "").strip())
        subrota = _resolver_subrota(item, self._rota_explicita)
        if subrota == "i23d":
            return self._custo_i23d(item)
        if subrota == "procedural":
            return {"segundos_estimados": 12.0, "vram_mb": 0, "disco_mb": 60}
        if subrota == "extrude_2d":
            return {"segundos_estimados": 10.0, "vram_mb": 0, "disco_mb": 50}
        if subrota == "template":
            if _usar_makehuman_cabelo(item):
                return {"segundos_estimados": 6.0, "vram_mb": 0, "disco_mb": 20}
            if _usar_modular_armor(item):
                return {"segundos_estimados": 10.0, "vram_mb": 0, "disco_mb": 50}
            vram_tmpl = 0 if (tem_origem or _device().startswith("cpu")) else 3500
            return {"segundos_estimados": 18.0 if tem_origem else 35.0, "vram_mb": vram_tmpl, "disco_mb": 120}

        if _usar_makehuman_cabelo(item):
            return {"segundos_estimados": 6.0, "vram_mb": 0, "disco_mb": 20}
        if _usar_modular_armor(item):
            return {"segundos_estimados": 10.0, "vram_mb": 0, "disco_mb": 50}
        if _usar_template_criatura(item):
            return {"segundos_estimados": 12.0, "vram_mb": 0, "disco_mb": 60}
        if _usar_template_humanoide(item):
            vram_tmpl = 0 if (tem_origem or _device().startswith("cpu")) else 3500
            return {"segundos_estimados": 18.0 if tem_origem else 35.0, "vram_mb": vram_tmpl, "disco_mb": 120}
        if _usar_extrude_2d(item):
            return {"segundos_estimados": 10.0, "vram_mb": 0, "disco_mb": 50}
        return self._custo_i23d(item)

    def preflight_triposr(self) -> tuple[bool, str]:
        """Diagnostico especifico da stack local TripoSR."""
        diagnostico = _diagnostico()
        if not diagnostico["ok"]:
            return False, diagnostico["razao"]

        if not _device().startswith("cpu"):
            livre = _vram_livre_mb()
            vram_min = _vram_minima_mb()
            if livre is not None and livre < vram_min:
                return False, f"P3: VRAM livre {livre} MiB < {vram_min} MiB exigidos"

        if pesos_triposr() is None:
            return False, (
                f"P3: pesos do TripoSR ausentes em {_cache_hf() / 'models--stabilityai--TripoSR'} e em {dir_modelos()} "
                "(GAP-040: o preflight respeita FORGE3D_MODELOS)"
            )
        return True, f"pronto (TripoSR, torch {diagnostico.get('torch', '?')}, venv {dir_venv().name})"

    def preflight(self) -> tuple[bool, str]:
        """Diagnostico nomeado: cada falta vira uma frase que diz o que instalar."""
        from ..errors import ForgeError

        try:
            self._licenca()
        except ForgeError as exc:
            return False, exc.mensagem

        modelo = modelo_escolhido()
        if modelo == "trellis":
            return _trellis.preflight_trellis2()
        if modelo == "sf3d":
            return False, "P3: SF3D encerrado em 6 GB (GAP-035: ~8 min/imagem); use FORGE3D_MODELO_MESH=triposr"
        if modelo != "triposr":
            return False, f"P3: modelo '{modelo}' reconhecido na licença, mas sem provider implementado"
        return self.preflight_triposr()

    def _preflight_modo(self, modo: str, item: dict) -> tuple[bool, str]:
        if modo in ("cabelo", "armor", "criatura", "humanoide", "extrude"):
            ok_b, msg_b = _preflight_blender_binario()
            if not ok_b:
                return False, msg_b
        if modo == "cabelo":
            if not script_template_body().is_file():
                return False, "script blender/template_body.py ausente"
            estilo = _extrair_estilo_makehuman(item)
            if not estilo:
                return False, "makehuman_cabelo / origem makehuman://hair/<estilo> vazio"
            return True, f"pronto (cabelo MakeHuman/MPFB2 CC0: {estilo})"
        if modo == "armor":
            if not script_modular_armor().is_file():
                return False, "script blender/modular_armor.py ausente"
            return True, f"pronto (modular armor MakeHuman/MPFB2 CC0: {item.get('parte')})"
        if modo == "criatura":
            if not script_organic_sculpt().is_file():
                return False, "script blender/organic_sculpt.py ausente"
            return True, f"pronto (criatura anatomica 4-patas: {item.get('tipo')})"
        if modo in ("humanoide", "extrude"):
            if not _python_imagem().is_file():
                return False, f"P3: venv de imagem ausente em {dir_venv()}"
            if modo == "humanoide":
                if not script_template_prep().is_file() or not script_template_body().is_file():
                    return False, "scripts de template MPFB2 ausentes"
                rotulo = "template MPFB2"
            else:
                if not script_pose_guard().is_file():
                    return False, f"script tools/pose_guard.py ausente em {script_pose_guard()}"
                rotulo = "extrude 2D"
            tem_orig_v1 = bool(str(item.get("origem") or "").strip()) and item.get("vistas") in (None, 1, "1") and not isinstance(item.get("vistas"), bool)
            if tem_orig_v1:
                return True, f"pronto ({rotulo} com origem)"
            c_pronto, c_razao = _preflight_concept_item(item)
            return (True, f"pronto ({rotulo}); concept: {c_razao}") if c_pronto else (False, c_razao)

        pronto, razao = self.preflight()
        tem_orig_v1 = bool(str(item.get("origem") or "").strip()) and item.get("vistas") in (None, 1, "1") and not isinstance(item.get("vistas"), bool)
        if not pronto or tem_orig_v1:
            return pronto, razao
        c_pronto, c_razao = _preflight_concept_item(item)
        return (True, f"{razao}; concept: {c_razao}") if c_pronto else (False, c_razao)

    def preflight_item(self, item: dict) -> tuple[bool, str]:
        """Preflight do item: respeita sub-rotas explicitas ou preserva cascata legada ``mesh``."""
        subrota = _resolver_subrota(item, self._rota_explicita)
        erro = _validar_subrota_item(subrota, item, self._rota_explicita)
        if erro:
            return False, erro

        if subrota == "i23d":
            return self._preflight_modo("i23d", item)
        if subrota == "procedural":
            return self._preflight_modo("criatura", item)
        if subrota == "extrude_2d":
            return self._preflight_modo("extrude", item)
        if subrota == "template":
            if _usar_makehuman_cabelo(item):
                return self._preflight_modo("cabelo", item)
            if _usar_modular_armor(item):
                return self._preflight_modo("armor", item)
            return self._preflight_modo("humanoide", item)

        if _usar_makehuman_cabelo(item):
            return self._preflight_modo("cabelo", item)
        if _usar_modular_armor(item):
            return self._preflight_modo("armor", item)
        if _usar_template_criatura(item):
            return self._preflight_modo("criatura", item)
        if _usar_template_humanoide(item):
            return self._preflight_modo("humanoide", item)
        if _usar_extrude_2d(item):
            return self._preflight_modo("extrude", item)
        return self._preflight_modo("i23d", item)

    def _executar_pose_guard(self, item: dict, imagem: Path, destino: Path, env: dict[str, str]) -> tuple[Path, dict[str, Any]]:
        return _pose_concept.executar_pose_guard(item, imagem, destino, env)

    def _executar_cutout_2d(self, imagem: Path, destino: Path, env: dict[str, str], item_id: Any) -> tuple[Path, dict[str, Any]]:
        return _i23d.executar_cutout_2d(imagem, destino, env, item_id)

    def _executar_delight(self, entrada_png: Path, destino: Path, env: dict[str, str]) -> dict[str, Any]:
        return _i23d.executar_delight(entrada_png, destino, env)

    def _raw_de_tupla(self, destino: Path, dados: tuple[str, list[Path], dict[str, Any]]) -> RawAsset:
        schema, arquivos, meta = dados
        return RawAsset(dir=destino, schema=schema, determinism=self.determinism, arquivos=arquivos, meta=meta)

    def _gerar_template_humanoide(self, item: dict, perfil: dict, destino: Path, imagem: Path, concept_meta: dict | None, env: dict[str, str], t0: float) -> RawAsset:
        return self._raw_de_tupla(destino, _tmpl.gerar_template_humanoide(item, perfil, destino, imagem, concept_meta, env, t0))

    def _gerar_makehuman_cabelo(self, item: dict, perfil: dict, destino: Path, env: dict[str, str], t0: float) -> RawAsset:
        return self._raw_de_tupla(destino, _tmpl.gerar_makehuman_cabelo(item, perfil, destino, env, t0))

    def _gerar_modular_armor(self, item: dict, perfil: dict, destino: Path, env: dict[str, str], t0: float) -> RawAsset:
        return self._raw_de_tupla(destino, _armor_proc.gerar_modular_armor(item, perfil, destino, env, t0))

    def _gerar_criatura_anatomica(self, item: dict, perfil: dict, destino: Path, env: dict[str, str], t0: float) -> RawAsset:
        return self._raw_de_tupla(destino, _armor_proc.gerar_criatura_anatomica(item, perfil, destino, env, t0))

    def _gerar_extrude_2d(self, item: dict, destino: Path, imagem: Path, concept_meta: dict | None, env: dict[str, str], t0: float) -> RawAsset:
        return self._raw_de_tupla(destino, _i23d.executar_extrude_2d(item, destino, imagem, concept_meta, env, t0, self._executar_cutout_2d, self._executar_delight))

    def _gerar_concept_com_retry(self, item: dict, destino: Path, env: dict[str, str], max_tentativas: int = 3) -> tuple[Path, dict[str, Any]]:
        return _pose_concept.gerar_concept_com_retry(item, destino, env, max_tentativas=max_tentativas)

    def _resolver_entrada(self, item: dict, destino: Path, env: dict[str, str]) -> tuple[Path, dict[str, Any] | None]:
        if str(item.get("origem") or "").strip():
            origem_png = _i23d.resolver_imagem_origem(item)
            if item.get("vistas") is not None and str(item.get("vistas")).strip() not in ("", "1"):
                meta = _views_origem.gerar_vistas_de_origem(item, origem_png, destino, env)
                front_png = destino / "concept_front.png"
                return (front_png if front_png.is_file() else origem_png), meta
            return origem_png, None
        return self._gerar_concept_com_retry(item, destino, env)

    def _gerar_triposr_i23d(self, item: dict, destino: Path, imagem: Path, concept_meta: dict | None, env: dict[str, str], t0: float) -> RawAsset:
        dados = _i23d.executar_i23d_step(
            item, destino, imagem, concept_meta, env, t0, self._executar_pose_guard, self._executar_delight
        )
        res = dados["resultado"]
        if res.get("provedor") == "trellis2_local":
            modelo_lic = "trellis"
            modelo_hf_meta = str(res.get("modelo") or _trellis.MODELO_TRELLIS_PADRAO)
        else:
            modelo_lic = modelo_escolhido()
            modelo_hf_meta = MODELO_HF
        return RawAsset(
            dir=destino,
            schema=str(dados["schema"]),
            determinism=self.determinism,
            arquivos=dados["arquivos"],
            meta={
                # chave da allowlist (pipeline.licenca_de); o repo HF fica so como proveniencia
                "modelo": modelo_lic,
                "modelo_hf": modelo_hf_meta,
                "torch": res.get("torch"),
                "mc_resolution": res.get("mc_resolution"),
                "tempos_s": res.get("tempos_s"),
                "vram_pico_mb": res.get("vram_pico_mb"),
                "faces": res.get("faces"),
                "rembg": dados["remover_fundo"],
                "rembg_motivo": dados["motivo_rembg"],
                "rembg_modelo": res.get("rembg_modelo"),
                "rembg_fallback": res.get("rembg_fallback"),
                "pose_guard": dados["pose_guard_report"],
                "delight": dados["delight_report"],
                "concept": concept_meta,
                **({"vistas_ortograficas": dados["vistas_ortograficas"]} if dados.get("vistas_ortograficas") else {}),
            },
        )

    def gerar(self, item: dict, perfil: dict, destino: Path) -> RawAsset:
        from ..errors import erro_provider_run, erro_recurso

        subrota = _resolver_subrota(item, self._rota_explicita)
        erro_sub = _validar_subrota_item(subrota, item, self._rota_explicita)
        if erro_sub:
            raise erro_provider_run(erro_sub, id=item.get("id"), modelo=modelo_escolhido())

        pronto, razao = self.preflight_item(item)
        if not pronto:
            if "VRAM" in razao:
                raise erro_recurso(f"rota {subrota} sem VRAM: {razao}", id=item.get("id"), modelo=modelo_escolhido())
            raise erro_provider_run(f"rota {subrota} indisponivel: {razao}", id=item.get("id"), modelo=modelo_escolhido())

        destino.mkdir(parents=True, exist_ok=True)
        resultado_path = destino / "i23d_resultado.json"
        if resultado_path.exists():
            resultado_path.unlink()

        env = dict(os.environ)
        env["PYTHONPATH"] = str(dir_vendor()) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        env.setdefault("HF_HOME", str(Path.home() / ".cache" / "huggingface"))
        env.setdefault("TORCH_HOME", str(Path.home() / ".cache" / "torch"))
        env.setdefault("PYTHONUNBUFFERED", "1")
        t0 = time.monotonic()

        if subrota == "i23d":
            imagem, concept_meta = self._resolver_entrada(item, destino, env)
            return self._gerar_triposr_i23d(item, destino, imagem, concept_meta, env, t0)
        if subrota == "procedural":
            return self._gerar_criatura_anatomica(item, perfil, destino, env, t0)
        if subrota == "extrude_2d":
            imagem, concept_meta = self._resolver_entrada(item, destino, env)
            return self._gerar_extrude_2d(item, destino, imagem, concept_meta, env, t0)
        if subrota == "template":
            if _usar_makehuman_cabelo(item):
                return self._gerar_makehuman_cabelo(item, perfil, destino, env, t0)
            if _usar_modular_armor(item):
                return self._gerar_modular_armor(item, perfil, destino, env, t0)
            imagem, concept_meta = self._resolver_entrada(item, destino, env)
            return self._gerar_template_humanoide(item, perfil, destino, imagem, concept_meta, env, t0)

        if _usar_makehuman_cabelo(item):
            return self._gerar_makehuman_cabelo(item, perfil, destino, env, t0)
        if _usar_modular_armor(item):
            return self._gerar_modular_armor(item, perfil, destino, env, t0)
        if _usar_template_criatura(item):
            return self._gerar_criatura_anatomica(item, perfil, destino, env, t0)
        imagem, concept_meta = self._resolver_entrada(item, destino, env)
        if _usar_template_humanoide(item):
            return self._gerar_template_humanoide(item, perfil, destino, imagem, concept_meta, env, t0)
        if _usar_extrude_2d(item):
            return self._gerar_extrude_2d(item, destino, imagem, concept_meta, env, t0)
        return self._gerar_triposr_i23d(item, destino, imagem, concept_meta, env, t0)


class I23DProvider(MeshProvider):
    nome = "i23d"
    _rota_explicita = "i23d"


class TemplateProvider(MeshProvider):
    nome = "template"
    _rota_explicita = "template"

    def preflight(self) -> tuple[bool, str]:
        ok_b, msg_b = _preflight_blender_binario()
        if not ok_b:
            return False, msg_b
        if not script_template_body().is_file() or not script_modular_armor().is_file():
            return False, "scripts de template MPFB2/modular_armor ausentes"
        return True, "pronto (template)"


class ProceduralProvider(MeshProvider):
    nome = "procedural"
    usa_gpu = False
    _rota_explicita = "procedural"

    def preflight(self) -> tuple[bool, str]:
        ok_b, msg_b = _preflight_blender_binario()
        if not ok_b:
            return False, msg_b
        if not script_organic_sculpt().is_file():
            return False, "script blender/organic_sculpt.py ausente"
        return True, "pronto (procedural)"


class Extrude2DProvider(MeshProvider):
    nome = "extrude_2d"
    _rota_explicita = "extrude_2d"

    def preflight(self) -> tuple[bool, str]:
        ok_b, msg_b = _preflight_blender_binario()
        if not ok_b:
            return False, msg_b
        if not script_pose_guard().is_file():
            return False, f"script tools/pose_guard.py ausente em {script_pose_guard()}"
        return True, "pronto (extrude_2d)"
