"""Validacao de midia, silhueta de LODs e animacoes glTF para QC (reexporta _uv_status e _skin_status)."""

from __future__ import annotations

import base64
import io
import logging
import math
import struct
import zlib
from pathlib import Path

from PIL import Image, ImageDraw, UnidentifiedImageError

from .errors import ForgeError, erro_qc
from .qc_glb import _accessor
from .qc_glb_mat import _eh_int, _num_finito
from .qc_skin import _skin_status
from .qc_uv import _uv_status

__all__ = [
    "PAPEIS_TEXTURA",
    "TEXTURA_MIN_PX",
    "_CLIPES_CICLICOS",
    "_dimensoes_bytes_imagem",
    "_imagens_embutidas",
    "_normal_opengl_valido",
    "_png_dimensoes",
    "_pot",
    "_silhueta_iou_lod",
    "_skin_status",
    "_uv_status",
    "_validar_bytes_imagem",
    "animacoes",
]

logger = logging.getLogger(__name__)

TEXTURA_MIN_PX = 32

PAPEIS_TEXTURA = (
    "textura",
    "basecolor",
    "albedo",
    "normal",
    "orm",
    "metallic",
    "roughness",
    "emissive",
)

_CLIPES_CICLICOS = frozenset(
    {"idle", "walk", "run", "gallop", "wing_flap", "glide", "ride_idle", "ride_fly"}
)


def _pot(n: int) -> bool:
    return n > 0 and (n & (n - 1)) == 0


def _validar_bytes_imagem(dados: bytes) -> tuple[int, int] | None:
    if not dados:
        return None
    if len(dados) >= 8 and dados[:8] == b"\x89PNG\r\n\x1a\n":
        pos = 8
        primeiro_chunk = True
        viu_iend = False
        while pos + 12 <= len(dados):
            tam = struct.unpack(">I", dados[pos : pos + 4])[0]
            tipo = dados[pos + 4 : pos + 8]
            if pos + 12 + tam > len(dados):
                return None
            if primeiro_chunk and (tipo != b"IHDR" or tam < 13):
                return None
            primeiro_chunk = False
            crc_lido = struct.unpack(">I", dados[pos + 8 + tam : pos + 12 + tam])[0]
            if (zlib.crc32(dados[pos + 4 : pos + 8 + tam]) & 0xFFFFFFFF) != crc_lido:
                return None
            pos += 12 + tam
            if tipo == b"IEND":
                viu_iend = True
                break
        if not viu_iend:
            return None
    elif not (
        (len(dados) >= 2 and dados[:2] == b"\xff\xd8")
        or (len(dados) >= 12 and dados[:4] == b"RIFF" and dados[8:12] == b"WEBP")
    ):
        return None
    try:
        with Image.open(io.BytesIO(dados)) as im:
            largura, altura = im.size
            im.verify()
    except (OSError, ValueError, EOFError, struct.error, UnidentifiedImageError) as exc:
        logger.debug("binario de imagem invalido: %s", exc)
        return None
    if largura <= 0 or altura <= 0:
        return None
    return int(largura), int(altura)


_dimensoes_bytes_imagem = _validar_bytes_imagem


def _png_dimensoes(caminho: Path) -> tuple[int, int]:
    dims = _validar_bytes_imagem(Path(caminho).read_bytes())
    if dims is None:
        raise erro_qc(f"textura invalida ou nao PNG/JPEG/WEBP: {caminho}", arquivo=str(caminho))
    return dims


def _normal_opengl_valido(dados: bytes) -> bool:
    """Valida Z positivo (mean(B) >= 128) e polaridade OpenGL +Y vs DirectX -Y."""
    try:
        with Image.open(io.BytesIO(dados)) as im:
            rgb = im.convert("RGB")
            w, h = rgb.size
            if w > 256 or h > 256:
                rgb = rgb.resize((min(w, 256), min(h, 256)), Image.Resampling.BILINEAR)
                w, h = rgb.size
            px = list(rgb.getdata())
    except (OSError, ValueError, UnidentifiedImageError) as exc:
        logger.debug("normal map ilegivel: %s", exc)
        return False
    if not px:
        return False
    if (sum(c[2] for c in px) / len(px)) < 128.0:
        return False
    if w < 3 or h < 3:
        return True
    nx = [(c[0] - 128.0) / 127.0 for c in px]
    ny = [(c[1] - 128.0) / 127.0 for c in px]
    num = 0.0
    den = 0.0
    for y in range(1, h - 1):
        row = y * w
        row_p = (y - 1) * w
        row_n = (y + 1) * w
        for x in range(1, w - 1):
            gxx = 0.5 * (nx[row + x + 1] - nx[row + x - 1])
            gxy = 0.5 * (nx[row_n + x] - nx[row_p + x])
            gyx = 0.5 * (ny[row + x + 1] - ny[row + x - 1])
            gyy = 0.5 * (ny[row_n + x] - ny[row_p + x])
            num += gxx * (-gyy) + gxy * (-gyx)
            den += abs(gxx * gyy) + abs(gxy * gyx)
    if den >= 0.5 and (num / den) < -0.25:
        return False
    return True


def _indices_imagens_normais(gltf: dict) -> set[int]:
    mats = gltf.get("materials", [])
    texs = gltf.get("textures", [])
    if not isinstance(mats, list) or not isinstance(texs, list):
        return set()
    indices: set[int] = set()
    for m in mats:
        if not isinstance(m, dict):
            continue
        nt = m.get("normalTexture")
        if not isinstance(nt, dict):
            continue
        ti = nt.get("index")
        if _eh_int(ti) and 0 <= ti < len(texs) and isinstance(texs[ti], dict):
            src = texs[ti].get("source")
            if _eh_int(src) and src >= 0:
                indices.add(src)
    return indices


def _imagens_embutidas(
    gltf: dict, binario: bytes, textura_max: int, textura_min: int = TEXTURA_MIN_PX
) -> list[dict[str, object]]:
    raw_vistas = gltf.get("bufferViews", [])
    vistas = raw_vistas if isinstance(raw_vistas, list) else []
    raw_imgs = gltf.get("images", [])
    imgs = raw_imgs if isinstance(raw_imgs, list) else []
    normal_imgs = _indices_imagens_normais(gltf)
    resultado: list[dict[str, object]] = []
    for idx, im in enumerate(imgs):
        if not isinstance(im, dict):
            resultado.append({"indice": idx, "px": None, "pot": False, "valida": False})
            continue
        dados = b""
        bv_idx = im.get("bufferView")
        if _eh_int(bv_idx) and 0 <= bv_idx < len(vistas) and isinstance(vistas[bv_idx], dict):
            bv = vistas[bv_idx]
            off = bv.get("byteOffset", 0)
            tam = bv.get("byteLength", 0)
            if _eh_int(off) and off >= 0 and _eh_int(tam) and tam >= 0:
                dados = binario[off : off + tam]
        elif isinstance(im.get("uri"), str) and im["uri"].startswith("data:"):
            partes = im["uri"].split(",", 1)
            if len(partes) == 2 and ";base64" in partes[0]:
                try:
                    dados = base64.b64decode(partes[1])
                except ValueError:
                    dados = b""
        dims = _validar_bytes_imagem(dados)
        if dims is None:
            resultado.append({"indice": idx, "px": None, "pot": False, "valida": False})
            continue
        w, h = dims
        pot = _pot(w) and _pot(h)
        normal_ok = _normal_opengl_valido(dados) if idx in normal_imgs else True
        valida = pot and min(w, h) >= textura_min and max(w, h) <= textura_max and normal_ok
        item_emb: dict[str, object] = {"indice": idx, "px": [w, h], "pot": pot, "valida": valida}
        if idx in normal_imgs:
            item_emb["normal_valida"] = normal_ok
        resultado.append(item_emb)
    return resultado


def _silhueta_iou_lod(
    pos0: list[tuple[float, float, float]],
    tris0: list[tuple[int, int, int]],
    pos_lod: list[tuple[float, float, float]],
    tris_lod: list[tuple[int, int, int]],
    tamanho: int = 128,
) -> float:
    todos = pos0 + pos_lod
    if not todos:
        return 0.0
    xs = [p[0] for p in todos]
    ys = [p[1] for p in todos]
    zs = [p[2] for p in todos]
    mn = (min(xs), min(ys), min(zs))
    mx = (max(xs), max(ys), max(zs))
    ext = max(mx[0] - mn[0], mx[1] - mn[1], mx[2] - mn[2], 1e-6)

    def _raster(
        pos: list[tuple[float, float, float]],
        tris: list[tuple[int, int, int]],
        eixo_u: int,
    ) -> list[int]:
        im = Image.new("L", (tamanho, tamanho), 0)
        draw = ImageDraw.Draw(im)
        margem = 4.0
        escala_px = (tamanho - 2.0 * margem) / ext
        for a, b, c in tris:
            pts = []
            for idx in (a, b, c):
                p = pos[idx]
                px = margem + (p[eixo_u] - mn[eixo_u]) * escala_px
                py = tamanho - 1.0 - margem - (p[1] - mn[1]) * escala_px
                pts.append((px, py))
            draw.polygon(pts, fill=255)
        return list(im.getdata())

    ious: list[float] = []
    for eixo in (0, 2):
        r0 = _raster(pos0, tris0, eixo)
        rl = _raster(pos_lod, tris_lod, eixo)
        inter = sum(1 for a, b in zip(r0, rl) if a > 0 and b > 0)
        uniao = sum(1 for a, b in zip(r0, rl) if a > 0 or b > 0)
        ious.append(inter / float(uniao) if uniao > 0 else 0.0)
    return min(ious)


def _amostrar_indices(n: int, limite: int = 64) -> list[int]:
    if n <= limite:
        return list(range(n))
    return sorted({0, n - 1, *(int(round(k * (n - 1) / (limite - 1))) for k in range(limite))})


def _norm_quat(q: tuple) -> tuple[float, float, float, float]:
    qf = (float(q[0]), float(q[1]), float(q[2]), float(q[3]))
    n = math.sqrt(sum(c * c for c in qf))
    return (qf[0] / n, qf[1] / n, qf[2] / n, qf[3] / n) if n > 1e-12 else (0.0, 0.0, 0.0, 1.0)


def animacoes(gltf: dict, binario: bytes) -> list[dict]:
    """Le os clipes do glTF: nome, duracao em segundos, ossos animados e continuidade de loop."""
    raw_acc = gltf.get("accessors", [])
    acessores = raw_acc if isinstance(raw_acc, list) else []
    raw_nos = gltf.get("nodes", [])
    nos = raw_nos if isinstance(raw_nos, list) else []
    raw_skins = gltf.get("skins", [])
    skins = raw_skins if isinstance(raw_skins, list) else []
    raw_anims = gltf.get("animations", [])
    anims = raw_anims if isinstance(raw_anims, list) else []
    ossos_do_rig: set[str] = set()
    if skins and isinstance(skins[0], dict):
        joints0 = skins[0].get("joints")
        if isinstance(joints0, list):
            ossos_do_rig = {
                str(nos[i].get("name", ""))
                for i in joints0
                if _eh_int(i) and 0 <= i < len(nos) and isinstance(nos[i], dict)
            }
    limiar_amp_rad = math.radians(5.0) - 1e-6
    clipes: list[dict] = []
    for animacao in anims:
        if not isinstance(animacao, dict):
            continue
        nome_clipe = str(animacao.get("name") or f"anim{len(clipes)}")
        duracao = 0.0
        ossos: set[str] = set()
        movendo: set[str] = set()
        canais = 0
        max_loop_delta_rot = 0.0
        max_loop_delta_pos = 0.0
        max_amp_rot = 0.0
        canais_raw = animacao.get("channels", [])
        if not isinstance(canais_raw, list):
            canais_raw = []
        raw_samp = animacao.get("samplers")
        amostradores = raw_samp if isinstance(raw_samp, list) else []
        for canal in canais_raw:
            if not isinstance(canal, dict):
                continue
            alvo_raw = canal.get("target")
            alvo = alvo_raw if isinstance(alvo_raw, dict) else {}
            indice = alvo.get("node")
            samp_idx = canal.get("sampler", 0)
            amostrador = (
                amostradores[samp_idx]
                if _eh_int(samp_idx) and 0 <= samp_idx < len(amostradores) and isinstance(amostradores[samp_idx], dict)
                else {}
            )
            entrada = amostrador.get("input")
            if _eh_int(entrada) and 0 <= entrada < len(acessores) and isinstance(acessores[entrada], dict):
                maximo = acessores[entrada].get("max")
                if isinstance(maximo, list) and maximo and _num_finito(maximo[0]):
                    duracao = max(duracao, float(maximo[0]))
            nome = ""
            if _eh_int(indice) and 0 <= indice < len(nos) and isinstance(nos[indice], dict):
                nome = str(nos[indice].get("name", ""))
            if nome not in ossos_do_rig:
                continue
            ossos.add(nome)
            canais += 1
            saida = amostrador.get("output")
            caminho_alvo = alvo.get("path")
            if (
                caminho_alvo in ("rotation", "translation")
                and _eh_int(saida)
                and 0 <= saida < len(acessores)
            ):
                try:
                    valores = _accessor(gltf, binario, saida)
                except (
                    ForgeError, KeyError, IndexError, OverflowError, TypeError, ValueError, struct.error
                ) as exc:
                    logger.debug("accessor animacao '%s' ignorado: %s", nome_clipe, exc)
                    valores = []
                if valores:
                    idxs = _amostrar_indices(len(valores))
                    if caminho_alvo == "rotation" and len(valores[0]) >= 4:
                        quats = [_norm_quat(valores[i]) for i in idxs]
                        amp_canal = 0.0
                        for i in range(len(quats)):
                            qi = quats[i]
                            for j in range(i + 1, len(quats)):
                                qj = quats[j]
                                dot = abs(qi[0] * qj[0] + qi[1] * qj[1] + qi[2] * qj[2] + qi[3] * qj[3])
                                ang = 2.0 * math.acos(min(1.0, max(0.0, dot)))
                                if ang > amp_canal:
                                    amp_canal = ang
                        max_amp_rot = max(max_amp_rot, amp_canal)
                        if amp_canal >= limiar_amp_rad:
                            movendo.add(nome)
                        if len(quats) >= 2:
                            q0, q1 = quats[0], quats[-1]
                            dot_se = abs(q0[0] * q1[0] + q0[1] * q1[1] + q0[2] * q1[2] + q0[3] * q1[3])
                            max_loop_delta_rot = max(
                                max_loop_delta_rot, 2.0 * math.acos(min(1.0, max(0.0, dot_se)))
                            )
                    elif caminho_alvo == "translation" and len(valores[0]) >= 3:
                        pts = [(float(valores[i][0]), float(valores[i][1]), float(valores[i][2])) for i in idxs]
                        amp_pos = 0.0
                        for i in range(len(pts)):
                            pi = pts[i]
                            for j in range(i + 1, len(pts)):
                                pj = pts[j]
                                d = math.sqrt((pi[0] - pj[0]) ** 2 + (pi[1] - pj[1]) ** 2 + (pi[2] - pj[2]) ** 2)
                                if d > amp_pos:
                                    amp_pos = d
                        if amp_pos >= 0.01:
                            movendo.add(nome)
                        if len(pts) >= 2:
                            p0, p1 = pts[0], pts[-1]
                            dist_se = math.sqrt((p0[0] - p1[0]) ** 2 + (p0[1] - p1[1]) ** 2 + (p0[2] - p1[2]) ** 2)
                            max_loop_delta_pos = max(max_loop_delta_pos, dist_se)
        eh_ciclico = nome_clipe in _CLIPES_CICLICOS
        loop_fechado = True
        if eh_ciclico:
            loop_fechado = max_loop_delta_rot <= math.radians(3.0) + 1e-6 and max_loop_delta_pos <= 0.15
        clipes.append(
            {
                "nome": nome_clipe,
                "duracao_s": round(duracao, 3),
                "ossos": sorted(ossos),
                "movendo": sorted(movendo),
                "canais": canais,
                "amplitude_max_graus": round(math.degrees(max_amp_rot), 3),
                "loop_delta_rad": round(max_loop_delta_rot, 5),
                "loop_fechado": loop_fechado,
            }
        )
    return clipes
