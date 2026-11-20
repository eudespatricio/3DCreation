"""Catalogo de presets PBR 3D e utilitarios cromaticos (sem dependencia de ``bpy``)."""

from __future__ import annotations

MATERIAIS_PROCEDURAIS: tuple[str, ...] = (
    "pele_humana",
    "escamas_dragao",
    "aco_forjado",
    "ouro_ornamentado",
    "couro_gasto",
    "cristal_arcano",
    "pedra_musgo",
    "tecido_nobre",
    "madeira_ancestral",
    "energia_espectral",
)

#: Parametros fisicos e de relevo multi-oitava em espaco 3D por preset.
PRESETS_PBR: dict[str, dict] = {
    "pele_humana": {
        "cor_base": (0.76, 0.54, 0.43, 1.0),
        "cor_secundaria": (0.64, 0.39, 0.31, 1.0),
        "cor_cavidade": (0.48, 0.29, 0.23, 1.0),
        "cor_crista": (0.85, 0.65, 0.54, 1.0),
        "escala_macro": 6.5,
        "escala_micro": 28.0,
        "escala_voronoi": 46.0,
        "voronoi_feature": "F1",
        "distorcao": 0.35,
        "escala_eixo": (1.0, 1.0, 1.0),
        "metallic_min": 0.0,
        "metallic_max": 0.0,
        "roughness_min": 0.46,
        "roughness_max": 0.66,
        "bump_strength": 0.18,
        "bump_distance": 0.004,
        "ao_distance": 0.18,
        "peso_crista": 0.28,
        "peso_musgo": 0.0,
    },
    "escamas_dragao": {
        "cor_base": (0.018, 0.088, 0.048, 1.0),
        "cor_secundaria": (0.036, 0.145, 0.068, 1.0),
        "cor_cavidade": (0.005, 0.015, 0.010, 1.0),
        "cor_crista": (0.12, 0.25, 0.11, 1.0),
        "escala_macro": 5.5,
        "escala_micro": 26.0,
        "escala_voronoi": 24.0,
        "voronoi_feature": "DISTANCE_TO_EDGE",
        "voronoi_map_range": (0.02, 0.18),
        "distorcao": 0.48,
        "escala_eixo": (1.0, 1.0, 1.18),
        "metallic_min": 0.06,
        "metallic_max": 0.34,
        "roughness_min": 0.24,
        "roughness_max": 0.68,
        "bump_strength": 0.78,
        "bump_distance": 0.018,
        "ao_distance": 0.24,
        "peso_crista": 0.56,
        "peso_musgo": 0.0,
    },
    "aco_forjado": {
        "cor_base": (0.54, 0.57, 0.61, 1.0),
        "cor_secundaria": (0.40, 0.43, 0.47, 1.0),
        "cor_cavidade": (0.20, 0.22, 0.25, 1.0),
        "cor_crista": (0.78, 0.81, 0.85, 1.0),
        "escala_macro": 8.0,
        "escala_micro": 36.0,
        "escala_voronoi": 14.0,
        "voronoi_feature": "F1",
        "distorcao": 0.40,
        "escala_eixo": (1.0, 1.0, 1.0),
        "metallic_min": 0.82,
        "metallic_max": 0.96,
        "roughness_min": 0.22,
        "roughness_max": 0.50,
        "bump_strength": 0.34,
        "bump_distance": 0.008,
        "ao_distance": 0.20,
        "peso_crista": 0.58,
        "peso_musgo": 0.0,
    },
    "ouro_ornamentado": {
        "cor_base": (0.92, 0.71, 0.22, 1.0),
        "cor_secundaria": (0.78, 0.55, 0.15, 1.0),
        "cor_cavidade": (0.46, 0.29, 0.08, 1.0),
        "cor_crista": (0.99, 0.86, 0.45, 1.0),
        "escala_macro": 7.0,
        "escala_micro": 30.0,
        "escala_voronoi": 16.0,
        "voronoi_feature": "DISTANCE_TO_EDGE",
        "distorcao": 0.65,
        "escala_eixo": (1.0, 1.0, 1.0),
        "metallic_min": 0.86,
        "metallic_max": 0.98,
        "roughness_min": 0.16,
        "roughness_max": 0.40,
        "bump_strength": 0.42,
        "bump_distance": 0.009,
        "ao_distance": 0.18,
        "peso_crista": 0.62,
        "peso_musgo": 0.0,
    },
    "couro_gasto": {
        "cor_base": (0.34, 0.19, 0.10, 1.0),
        "cor_secundaria": (0.25, 0.13, 0.07, 1.0),
        "cor_cavidade": (0.14, 0.07, 0.04, 1.0),
        "cor_crista": (0.54, 0.35, 0.20, 1.0),
        "escala_macro": 5.5,
        "escala_micro": 26.0,
        "escala_voronoi": 34.0,
        "voronoi_feature": "F1",
        "distorcao": 0.45,
        "escala_eixo": (1.0, 1.0, 1.0),
        "metallic_min": 0.0,
        "metallic_max": 0.02,
        "roughness_min": 0.46,
        "roughness_max": 0.78,
        "bump_strength": 0.32,
        "bump_distance": 0.007,
        "ao_distance": 0.20,
        "peso_crista": 0.48,
        "peso_musgo": 0.0,
    },
    "cristal_arcano": {
        "cor_base": (0.20, 0.60, 0.92, 1.0),
        "cor_secundaria": (0.36, 0.18, 0.72, 1.0),
        "cor_cavidade": (0.09, 0.12, 0.34, 1.0),
        "cor_crista": (0.68, 0.94, 1.00, 1.0),
        "escala_macro": 4.5,
        "escala_micro": 18.0,
        "escala_voronoi": 9.5,
        "voronoi_feature": "DISTANCE_TO_EDGE",
        "distorcao": 0.25,
        "escala_eixo": (1.0, 1.0, 1.3),
        "metallic_min": 0.0,
        "metallic_max": 0.0,
        "roughness_min": 0.04,
        "roughness_max": 0.08,
        "bump_strength": 0.35,
        "bump_distance": 0.008,
        "ao_distance": 0.24,
        "peso_crista": 0.68,
        "peso_musgo": 0.0,
        "transmission": 0.85,
        "ior": 1.52,
        "alpha": 0.35,
        "blend_method": "BLEND",
        "emission_color": (0.15, 0.85, 1.0, 1.0),
        "emission_strength": 2.0,
    },
    "pedra_musgo": {
        "cor_base": (0.38, 0.39, 0.36, 1.0),
        "cor_secundaria": (0.28, 0.29, 0.27, 1.0),
        "cor_cavidade": (0.15, 0.16, 0.14, 1.0),
        "cor_crista": (0.20, 0.46, 0.16, 1.0),
        "escala_macro": 4.2,
        "escala_micro": 24.0,
        "escala_voronoi": 11.0,
        "voronoi_feature": "F1",
        "distorcao": 0.75,
        "escala_eixo": (1.0, 1.0, 1.0),
        "metallic_min": 0.0,
        "metallic_max": 0.0,
        "roughness_min": 0.70,
        "roughness_max": 0.92,
        "bump_strength": 0.62,
        "bump_distance": 0.014,
        "ao_distance": 0.25,
        "peso_crista": 0.35,
        "peso_musgo": 0.65,
    },
    "tecido_nobre": {
        "cor_base": (0.50, 0.10, 0.16, 1.0),
        "cor_secundaria": (0.36, 0.07, 0.12, 1.0),
        "cor_cavidade": (0.18, 0.03, 0.06, 1.0),
        "cor_crista": (0.76, 0.56, 0.24, 1.0),
        "escala_macro": 6.0,
        "escala_micro": 52.0,
        "escala_voronoi": 44.0,
        "voronoi_feature": "F1",
        "distorcao": 0.30,
        "escala_eixo": (1.0, 1.0, 1.0),
        "metallic_min": 0.0,
        "metallic_max": 0.16,
        "roughness_min": 0.64,
        "roughness_max": 0.88,
        "bump_strength": 0.24,
        "bump_distance": 0.005,
        "ao_distance": 0.18,
        "peso_crista": 0.42,
        "peso_musgo": 0.0,
    },
    "madeira_ancestral": {
        "cor_base": (0.36, 0.22, 0.12, 1.0),
        "cor_secundaria": (0.24, 0.14, 0.07, 1.0),
        "cor_cavidade": (0.13, 0.07, 0.04, 1.0),
        "cor_crista": (0.48, 0.34, 0.21, 1.0),
        "escala_macro": 5.0,
        "escala_micro": 28.0,
        "escala_voronoi": 15.0,
        "voronoi_feature": "DISTANCE_TO_EDGE",
        "distorcao": 0.85,
        "escala_eixo": (2.4, 2.4, 0.45),
        "metallic_min": 0.0,
        "metallic_max": 0.0,
        "roughness_min": 0.56,
        "roughness_max": 0.84,
        "bump_strength": 0.46,
        "bump_distance": 0.010,
        "ao_distance": 0.22,
        "peso_crista": 0.40,
        "peso_musgo": 0.0,
    },
    "energia_espectral": {
        "cor_base": (0.12, 0.82, 0.76, 1.0),
        "cor_secundaria": (0.07, 0.32, 0.54, 1.0),
        "cor_cavidade": (0.04, 0.10, 0.20, 1.0),
        "cor_crista": (0.66, 0.98, 0.92, 1.0),
        "escala_macro": 4.8,
        "escala_micro": 20.0,
        "escala_voronoi": 10.5,
        "voronoi_feature": "DISTANCE_TO_EDGE",
        "distorcao": 1.65,
        "escala_eixo": (1.0, 1.0, 0.8),
        "metallic_min": 0.05,
        "metallic_max": 0.22,
        "roughness_min": 0.18,
        "roughness_max": 0.44,
        "bump_strength": 0.30,
        "bump_distance": 0.008,
        "ao_distance": 0.20,
        "peso_crista": 0.65,
        "peso_musgo": 0.0,
    },
}


def _hex_para_rgba_linear(cor_hex: str) -> tuple[float, float, float, float]:
    limpo = str(cor_hex).strip().lstrip("#")
    if len(limpo) != 6:
        return (0.5, 0.5, 0.5, 1.0)
    r = int(limpo[0:2], 16) / 255.0
    g = int(limpo[2:4], 16) / 255.0
    b = int(limpo[4:6], 16) / 255.0

    def _srgb_lin(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    return (_srgb_lin(r), _srgb_lin(g), _srgb_lin(b), 1.0)


def _resolver_cores_zona(
    zona: dict,
    preset_cfg: dict,
) -> tuple[tuple[float, float, float, float], tuple[float, float, float, float]]:
    """Retorna ``(cor_base, cor_sec)`` lineares com variacao garantida mesmo com ``cor_tinta``."""
    tinta_raw = zona.get("cor_tinta")
    if not tinta_raw:
        cor_base = tuple(preset_cfg.get("cor_base", (0.5, 0.5, 0.5, 1.0)))
        cor_sec = tuple(preset_cfg.get("cor_secundaria", cor_base))
        return cor_base, cor_sec

    tinta = _hex_para_rgba_linear(str(tinta_raw))
    r, g, b, a = float(tinta[0]), float(tinta[1]), float(tinta[2]), float(tinta[3])
    c_hi = (
        max(0.0, min(1.0, r * 1.45 + 0.025)),
        max(0.0, min(1.0, g * 1.45 + 0.025)),
        max(0.0, min(1.0, b * 1.45 + 0.025)),
        a,
    )
    c_lo = (
        max(0.0, min(1.0, r * 0.42)),
        max(0.0, min(1.0, g * 0.42)),
        max(0.0, min(1.0, b * 0.42)),
        a,
    )
    pb = preset_cfg.get("cor_base", (0.5, 0.5, 0.5, 1.0))
    ps = preset_cfg.get("cor_secundaria", pb)
    lum_pb = 0.2126 * float(pb[0]) + 0.7152 * float(pb[1]) + 0.0722 * float(pb[2])
    lum_ps = 0.2126 * float(ps[0]) + 0.7152 * float(ps[1]) + 0.0722 * float(ps[2])
    return (c_lo, c_hi) if lum_ps > lum_pb else (c_hi, c_lo)
