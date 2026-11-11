"""Rota `modular`: WFC determinístico e geometria do setor (D74)."""

from __future__ import annotations

import pytest

from forge3d import modular


def test_layout_2x2_e_deterministico():
    a = modular.gerar_layout((2, 2), seed=20261111)
    b = modular.gerar_layout((2, 2), seed=20261111)
    assert a == b
    assert len(a) == 2 and len(a[0]) == 2


def test_layout_2x2_e_valido_em_varias_seeds():
    for seed in range(20):
        layout = modular.gerar_layout((2, 2), seed=seed)
        assert modular.validar_layout(layout, (2, 2)) == [], (seed, layout)


def test_layout_5x2_dez_setores_fecha_em_varias_seeds():
    """Grade do portão (10 setores) valida em seeds diferentes — o WFC não depende de sorte."""
    for seed in (0, 1, 7, 20261111):
        layout = modular.gerar_layout((5, 2), seed=seed)
        assert modular.validar_layout(layout, (5, 2)) == [], (seed, layout)


def test_todo_modulo_cabe_no_max_partes_do_perfil():
    """max_partes=8 no godot4: acima disso o ucx vira um hull só e o piso perde colisor próprio."""
    for nome in modular.CATALOGO:
        caixas = modular.caixas_do_modulo(nome, 4.0, 2.4)
        assert len(caixas) <= 8, (nome, len(caixas))


def test_layout_maior_tambem_fecha():
    """4x3 setores: o WFC acha layout valido e conectado sem backtracking."""
    for seed in (1, 7, 20261111):
        layout = modular.gerar_layout((4, 3), seed=seed)
        assert modular.validar_layout(layout, (4, 3)) == [], (seed, layout)


def test_sockets_encostam_entre_vizinhos():
    layout = modular.gerar_layout((3, 3), seed=42)
    for y in range(3):
        for x in range(3):
            atual = modular.CATALOGO[layout[y][x]]["sockets"]
            if x + 1 < 3:
                assert atual[2] == modular.CATALOGO[layout[y][x + 1]]["sockets"][3]
            if y + 1 < 3:
                assert atual[0] == modular.CATALOGO[layout[y + 1][x]]["sockets"][1]


def test_layout_desconectado_e_reprovado():
    """Dois corredores com parede entre si encostam o socket (fechado = fechado) mas nao se ligam."""
    assert modular.conectado([["reto_ns", "reto_ns"]], (2, 1)) is False
    assert "desconectado" in " ".join(
        modular.validar_layout([["reto_ns", "reto_ns"]], (2, 1))
    )


def test_grade_um_por_um():
    layout = modular.gerar_layout((1, 1), seed=0)
    assert [len(linha) for linha in layout] == [1]
    assert modular.validar_layout(layout, (1, 1)) == []


def test_modulo_fora_do_catalogo_falha():
    with pytest.raises(ValueError):
        modular.gerar_layout((2, 2), modulos=["inexistente"], seed=0)


def test_caixas_do_corredor_tem_duas_paredes_e_piso():
    caixas = modular.caixas_do_modulo("reto_ns", 4.0, 2.4)
    papeis = [c["papel"] for c in caixas]
    assert papeis.count("parede") == 2
    assert papeis.count("piso") == 2  # placa + piso recuado
    alturas = [c["max"][2] for c in caixas]
    assert max(alturas) == pytest.approx(2.4)
    xs = [v for c in caixas for v in (c["min"][0], c["max"][0])]
    assert min(xs) == 0.0 and max(xs) == pytest.approx(4.0)


def test_cruzamento_nao_tem_parede():
    caixas = modular.caixas_do_modulo("quatro_bocas", 4.0, 2.4)
    assert [c["papel"] for c in caixas].count("parede") == 0


def test_curva_tem_duas_paredes():
    caixas = modular.caixas_do_modulo("curva_ne", 4.0, 2.4)
    assert [c["papel"] for c in caixas].count("parede") == 2
