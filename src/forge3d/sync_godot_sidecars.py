"""Geracao e atualizacao de sidecars ``.import`` (.glb e .png) para Godot 4."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from . import animacao
from .sync_common import _escrever_atomico

_SUFIXO_GODOT_KEEP_RE = re.compile(r"(?:_colisao|_lod[1-9]\d*)\.glb$", re.IGNORECASE)
_GODOT_POST_IMPORT_RES = "res://addons/forge3d/post_import.gd"
_SECTION_HEADER_RE = re.compile(r"^\[([^\]]+)\]\s*$")

_CLIPES_CICLICOS: frozenset[str] = (
    frozenset(animacao.CLIPES_SUPORTADOS) - animacao._NAO_LOOP_CLIPES
)

_BONE_MAP_HUMANOID_V1: dict[str, str] = {
    "Root": "Root",
    "Hips": "Hips",
    "Spine": "Spine",
    "Chest": "Spine1",
    "UpperChest": "Chest",
    "Neck": "Neck",
    "Head": "Head",
    "LeftShoulder": "Shoulder.L",
    "LeftUpperArm": "UpperArm.L",
    "LeftLowerArm": "LowerArm.L",
    "LeftHand": "Hand.L",
    "RightShoulder": "Shoulder.R",
    "RightUpperArm": "UpperArm.R",
    "RightLowerArm": "LowerArm.R",
    "RightHand": "Hand.R",
    "LeftUpperLeg": "UpperLeg.L",
    "LeftLowerLeg": "LowerLeg.L",
    "LeftFoot": "Foot.L",
    "LeftToes": "Toe.L",
    "RightUpperLeg": "UpperLeg.R",
    "RightLowerLeg": "LowerLeg.R",
    "RightFoot": "Foot.R",
    "RightToes": "Toe.R",
}

_BONE_MAP_HUMANOID_AA: dict[str, str] = {
    "Root": "Root",
    "Hips": "Hips",
    "Spine": "Spine",
    "Chest": "Chest",
    "UpperChest": "Chest",
    "Neck": "Neck",
    "Head": "Head",
    "LeftEye": "Eye.L",
    "RightEye": "Eye.R",
    "Jaw": "Jaw",
    "LeftShoulder": "Shoulder.L",
    "LeftUpperArm": "UpperArm.L",
    "LeftLowerArm": "LowerArm.L",
    "LeftHand": "Hand.L",
    "LeftThumbMetacarpal": "Thumb1.L",
    "LeftThumbProximal": "Thumb2.L",
    "LeftThumbDistal": "Thumb3.L",
    "LeftIndexProximal": "Index1.L",
    "LeftIndexIntermediate": "Index2.L",
    "LeftIndexDistal": "Index3.L",
    "LeftMiddleProximal": "Middle1.L",
    "LeftMiddleIntermediate": "Middle2.L",
    "LeftMiddleDistal": "Middle3.L",
    "LeftRingProximal": "Ring1.L",
    "LeftRingIntermediate": "Ring2.L",
    "LeftRingDistal": "Ring3.L",
    "LeftLittleProximal": "Little1.L",
    "LeftLittleIntermediate": "Little2.L",
    "LeftLittleDistal": "Little3.L",
    "RightShoulder": "Shoulder.R",
    "RightUpperArm": "UpperArm.R",
    "RightLowerArm": "LowerArm.R",
    "RightHand": "Hand.R",
    "RightThumbMetacarpal": "Thumb1.R",
    "RightThumbProximal": "Thumb2.R",
    "RightThumbDistal": "Thumb3.R",
    "RightIndexProximal": "Index1.R",
    "RightIndexIntermediate": "Index2.R",
    "RightIndexDistal": "Index3.R",
    "RightMiddleProximal": "Middle1.R",
    "RightMiddleIntermediate": "Middle2.R",
    "RightMiddleDistal": "Middle3.R",
    "RightRingProximal": "Ring1.R",
    "RightRingIntermediate": "Ring2.R",
    "RightRingDistal": "Ring3.R",
    "RightLittleProximal": "Little1.R",
    "RightLittleIntermediate": "Little2.R",
    "RightLittleDistal": "Little3.R",
    "LeftUpperLeg": "UpperLeg.L",
    "LeftLowerLeg": "LowerLeg.L",
    "LeftFoot": "Foot.L",
    "LeftToes": "Toe.L",
    "RightUpperLeg": "UpperLeg.R",
    "RightLowerLeg": "LowerLeg.R",
    "RightFoot": "Foot.R",
    "RightToes": "Toe.R",
}


class _RawGodotExpr:
    """Token bruto de ConfigFile do Godot (ex.: Object(...))."""

    def __init__(self, expr: str) -> None:
        self.expr = expr


def _formatar_bone_map_object(mapa: dict[str, str]) -> str:
    props = ['"profile":Object(SkeletonProfileHumanoid,"resource_name":"")']
    for prof_name, bone_name in mapa.items():
        props.append(f'"bone_map/{prof_name}":&{json.dumps(bone_name)}')
    return f"Object(BoneMap,{','.join(props)})"


def _formatar_valor_configfile(valor: Any) -> str:
    if isinstance(valor, _RawGodotExpr):
        return valor.expr
    if isinstance(valor, bool):
        return "true" if valor else "false"
    if isinstance(valor, int):
        return str(valor)
    if isinstance(valor, float):
        return json.dumps(valor)
    if isinstance(valor, str):
        return json.dumps(valor)
    if isinstance(valor, list):
        return "[" + ", ".join(_formatar_valor_configfile(v) for v in valor) + "]"
    if isinstance(valor, dict):
        if not valor:
            return "{}"
        itens = ",\n".join(
            f"{json.dumps(str(k))}: {_formatar_valor_configfile(valor[k])}"
            for k in sorted(valor, key=str)
        )
        return "{\n" + itens + "\n}"
    return json.dumps(str(valor))


def _eh_clipe_ciclico(nome: str) -> bool:
    chave = nome.strip().lower()
    base = chave.rsplit("|", 1)[-1].strip() if "|" in chave else chave
    return chave in _CLIPES_CICLICOS or base in _CLIPES_CICLICOS


def _construir_subresources_glb(manifesto: dict[str, Any] | None) -> dict[str, Any]:
    sub: dict[str, Any] = {}
    if not isinstance(manifesto, dict):
        return sub

    rig = manifesto.get("rig")
    if isinstance(rig, dict):
        esq = str(rig.get("esqueleto") or "").strip().lower()
        if esq.startswith("godot-humanoid") or esq.startswith("humanoid"):
            mapa = (
                _BONE_MAP_HUMANOID_AA
                if esq == "godot-humanoid-aa@1"
                else _BONE_MAP_HUMANOID_V1
            )
            sub["nodes"] = {
                "PATH:Skeleton3D": {
                    "retarget/bone_map": _RawGodotExpr(_formatar_bone_map_object(mapa)),
                    "retarget/rest_fixer/fix_silhouette/enable": True,
                }
            }

    raw_anims = manifesto.get("animacoes")
    if isinstance(raw_anims, list):
        anims_dict: dict[str, dict[str, int]] = {}
        for entry in raw_anims:
            if isinstance(entry, str):
                nome = entry.strip()
                loop_flag = _eh_clipe_ciclico(nome)
            elif isinstance(entry, dict):
                raw_nome = entry.get("nome")
                raw_name = entry.get("name")
                nome = (str(raw_nome).strip() if raw_nome is not None else "") or (
                    str(raw_name).strip() if raw_name is not None else ""
                )
                if "loop" in entry and entry["loop"] is not None:
                    loop_flag = bool(entry["loop"])
                else:
                    loop_flag = _eh_clipe_ciclico(nome)
            else:
                continue
            if not nome:
                continue
            anims_dict[nome] = {"settings/loop_mode": 1 if loop_flag else 0}
        if anims_dict:
            sub["animations"] = anims_dict

    return sub


def _delta_delimitadores(linha: str) -> tuple[int, int]:
    """Conta abertura menos fechamento de ``{}`` e ``()`` fora de strings."""
    braces = 0
    parens = 0
    in_str = False
    escaped = False
    for ch in linha:
        if escaped:
            escaped = False
            continue
        if in_str:
            if ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            braces += 1
        elif ch == "}":
            braces -= 1
        elif ch == "(":
            parens += 1
        elif ch == ")":
            parens -= 1
    return braces, parens


def _parse_params_entries(bloco: str) -> list[tuple[str | None, str]]:
    """Extrai entradas ``(chave, texto_completo)`` do bloco ``[params]`` respeitando blocos ``{}``."""
    entries: list[tuple[str | None, str]] = []
    linhas = bloco.splitlines(keepends=True)
    i = 0
    while i < len(linhas):
        linha = linhas[i]
        stripped = linha.strip()
        if not stripped or stripped.startswith(";"):
            entries.append((None, linha))
            i += 1
            continue
        if "=" in linha:
            chave = linha.split("=", 1)[0].strip()
            buf = [linha]
            braces, parens = _delta_delimitadores(linha)
            i += 1
            while i < len(linhas) and (braces > 0 or parens > 0):
                nxt = linhas[i]
                buf.append(nxt)
                db, dp = _delta_delimitadores(nxt)
                braces += db
                parens += dp
                i += 1
            entries.append((chave, "".join(buf)))
        else:
            entries.append((None, linha))
            i += 1
    return entries


def _upsert_params_ini(
    texto: str,
    updates: list[tuple[str, str]],
    *,
    preserve_if_nonempty: frozenset[str] = frozenset(),
    preserve_if_present: frozenset[str] = frozenset(),
) -> str:
    """Atualiza ou insere chaves na secao ``[params]`` preservando demais chaves/secoes."""
    linhas = texto.splitlines(keepends=True)
    params_start: int | None = None
    params_end = len(linhas)

    for idx, linha in enumerate(linhas):
        m = _SECTION_HEADER_RE.match(linha.strip())
        if m is None:
            continue
        if params_start is None and m.group(1).strip() == "params":
            params_start = idx + 1
        elif params_start is not None:
            params_end = idx
            break

    if params_start is None:
        sep = "" if (not texto or texto.endswith("\n")) else "\n"
        extra_sep = "\n" if texto else ""
        corpo = "".join(f"{k}={v}\n" for k, v in updates)
        return f"{texto}{sep}{extra_sep}[params]\n\n{corpo}"

    pre = "".join(linhas[:params_start])
    bloco = "".join(linhas[params_start:params_end])
    post = "".join(linhas[params_end:])

    entries = _parse_params_entries(bloco)
    update_map = dict(updates)
    seen: set[str] = set()
    novas_entries: list[str] = []

    for chave, raw in entries:
        if chave is None or chave not in update_map:
            novas_entries.append(raw)
            continue
        seen.add(chave)
        atual_val = raw.split("=", 1)[1].strip()
        if chave in preserve_if_present:
            novas_entries.append(raw)
        elif chave in preserve_if_nonempty and atual_val not in ("", '""', "{}"):
            novas_entries.append(raw)
        else:
            eol = "\n" if raw.endswith("\n") else ""
            novas_entries.append(f"{chave}={update_map[chave]}{eol}")

    corpo_params = "".join(novas_entries)
    if corpo_params and not corpo_params.endswith("\n"):
        corpo_params += "\n"
    for chave, valor in updates:
        if chave not in seen:
            corpo_params += f"{chave}={valor}\n"

    return f"{pre}{corpo_params}{post}"


def _atualizar_import_sidecar_glb(
    import_dst: Path,
    tag: str = "sync",
    *,
    manifesto: dict[str, Any] | None = None,
) -> None:
    """Cria ou atualiza ``<asset>.glb.import`` com parametros de import e ``_subresources``."""
    if import_dst.suffix.lower() == ".glb":
        import_dst = Path(f"{import_dst}.import")

    subresources = _construir_subresources_glb(manifesto)
    sub_str = _formatar_valor_configfile(subresources)

    updates: list[tuple[str, str]] = [
        ("import_script/path", f'"{_GODOT_POST_IMPORT_RES}"'),
        ("meshes/ensure_tangents", "true"),
        ("meshes/light_baking", "2"),
        ("skins/use_named_skins", "true"),
        ("animation/fps", "24"),
        ("_subresources", sub_str),
    ]

    if not import_dst.is_file():
        corpo = "\n".join(f"{k}={v}" for k, v in updates)
        conteudo = (
            "[remap]\n\n"
            'importer="scene"\n'
            "importer_version=1\n"
            'type="PackedScene"\n\n'
            "[params]\n\n"
            f"{corpo}\n"
        )
        _escrever_atomico(import_dst, conteudo, tag)
        return

    texto = import_dst.read_text(encoding="utf-8")
    preserve_present = frozenset({"_subresources"}) if manifesto is None else frozenset()
    novo = _upsert_params_ini(
        texto,
        updates,
        preserve_if_nonempty=frozenset({"import_script/path"}),
        preserve_if_present=preserve_present,
    )
    if novo != texto:
        _escrever_atomico(import_dst, novo, tag)


def _atualizar_import_sidecar_png(
    import_dst: Path,
    *,
    is_normal: bool,
    tag: str = "sync",
) -> None:
    """Cria ou atualiza ``<tex>.png.import`` para VRAM compressed texture2D."""
    normal_flag = "1" if is_normal else "0"
    updates = [
        ("compress/mode", "2"),
        ("compress/normal_map", normal_flag),
        ("mipmaps/generate", "true"),
    ]
    if not import_dst.is_file():
        corpo = "\n".join(f"{k}={v}" for k, v in updates)
        conteudo = (
            "[remap]\n\n"
            'importer="texture"\n'
            'type="CompressedTexture2D"\n\n'
            "[params]\n\n"
            f"{corpo}\n"
        )
        _escrever_atomico(import_dst, conteudo, tag)
        return

    texto = import_dst.read_text(encoding="utf-8")
    novo = _upsert_params_ini(texto, updates)
    if novo != texto:
        _escrever_atomico(import_dst, novo, tag)


def aplicar_sidecars_godot(
    dst: Path,
    tag: str,
    *,
    manifesto: dict[str, Any] | None = None,
) -> list[Path]:
    """Gera sidecars ``.import`` apropriados para o arquivo sincronizado em projeto Godot."""
    sidecars: list[Path] = []
    if _SUFIXO_GODOT_KEEP_RE.search(dst.name):
        import_dst = Path(f"{dst}.import")
        _escrever_atomico(import_dst, '[remap]\nimporter="keep"\n', tag)
        sidecars.append(import_dst.resolve(strict=False))
    elif dst.suffix.lower() == ".glb":
        import_dst = Path(f"{dst}.import")
        _atualizar_import_sidecar_glb(import_dst, tag, manifesto=manifesto)
        sidecars.append(import_dst.resolve(strict=False))
    elif dst.suffix.lower() == ".png":
        import_dst = Path(f"{dst}.import")
        _atualizar_import_sidecar_png(
            import_dst,
            is_normal=dst.name.lower().endswith("_normal.png"),
            tag=tag,
        )
        sidecars.append(import_dst.resolve(strict=False))
    return sidecars
