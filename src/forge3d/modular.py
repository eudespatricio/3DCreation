"""Rota `modular`: catálogo de módulos com sockets e WFC determinístico (D74).

Duas coisas moram aqui, e só elas:

* **layout** — grade de módulos conectados por sockets, resolvida por WFC com seed. Determinístico:
  a mesma seed + grade + catálogo dão o mesmo layout, byte a byte (D1);
* **geometria do setor** — as caixas (piso, paredes fechadas, pilar de canto) de um módulo, em
  metros. Quem exporta é o pós-processo, como em qualquer rota.

O layout é por grade (x = leste, y = norte). Cada lado de um módulo é `aberto` ou `fechado`;
dois vizinhos só encostam se o lado de um for igual ao lado oposto do outro. A borda da grade fica
**livre**: a fatiada de 4 setores é um fragmento de dungeon e o lado aberto no limite é uma saída —
fechar a borda exige um módulo de parede, que não entra nos 3 da fatiada.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

__all__ = [
    "CATALOGO",
    "LADOS",
    "gerar_layout",
    "validar_layout",
    "caixas_do_modulo",
    "conectado",
]

#: ordem dos lados no socket
LADOS = ("norte", "sul", "leste", "oeste")
ABERTO = "aberto"
FECHADO = "fechado"

#: módulos da fatiada: três é o mínimo que produz escolha de verdade no WFC
CATALOGO: dict[str, dict] = {
    "corredor": {
        "sockets": (ABERTO, ABERTO, FECHADO, FECHADO),
        "descricao": "corredor reto norte-sul",
    },
    "sala": {
        "sockets": (ABERTO, ABERTO, ABERTO, ABERTO),
        "descricao": "sala aberta nos quatro lados",
    },
    "curva": {
        "sockets": (ABERTO, FECHADO, ABERTO, FECHADO),
        "descricao": "curva que dobra de norte para leste",
    },
}

#: (dx, dy, lado do vizinho que encosta) — x = leste, y = norte
VIZINHOS = (
    (1, 0, 2, 3),  # leste do atual encosta no oeste do vizinho
    (-1, 0, 3, 2),  # oeste encosta no leste
    (0, 1, 0, 1),  # norte encosta no sul
    (0, -1, 1, 0),  # sul encosta no norte
)


def _encosta(a: str, lado_a: int, b: str, lado_b: int) -> bool:
    return a["sockets"][lado_a] == b["sockets"][lado_b]


def validar_layout(layout: list[list[str]], grade: tuple[int, int]) -> list[str]:
    """Lista os problemas do layout (vazio = válido): socket, borda e conectividade."""
    problemas: list[str] = []
    nx, ny = grade
    for y in range(ny):
        for x in range(nx):
            nome = layout[y][x]
            modulo = CATALOGO.get(nome)
            if modulo is None:
                problemas.append(f"modulo desconhecido em ({x},{y}): {nome}")
                continue
            for dx, dy, meu, dele in VIZINHOS:
                vx, vy = x + dx, y + dy
                if not (0 <= vx < nx and 0 <= vy < ny):
                    continue
                if not _encosta(modulo, meu, CATALOGO[layout[vy][vx]], dele):
                    problemas.append(f"({x},{y}) {nome} x ({vx},{vy}): socket nao encosta")
    if not conectado(layout, grade):
        problemas.append("layout desconectado (setor inalcancavel)")
    return problemas


def conectado(layout: list[list[str]], grade: tuple[int, int]) -> bool:
    """Todos os setores são alcançáveis a pé? (BFS pelos lados abertos)."""
    nx, ny = grade
    inicio = (0, 0)
    vistos = {inicio}
    pilha = [inicio]
    while pilha:
        x, y = pilha.pop()
        modulo = CATALOGO[layout[y][x]]
        for dx, dy, meu, dele in VIZINHOS:
            vx, vy = x + dx, y + dy
            if not (0 <= vx < nx and 0 <= vy < ny):
                continue
            if modulo["sockets"][meu] != ABERTO:
                continue
            if (vx, vy) not in vistos:
                vistos.add((vx, vy))
                pilha.append((vx, vy))
    return len(vistos) == nx * ny


def _propagar(dominios: list[list[set[str]]], grade: tuple[int, int]) -> bool:
    """Aperta os domínios até estabilizar; devolve False se algum esvaziar."""
    nx, ny = grade
    mudou = True
    while mudou:
        mudou = False
        for y in range(ny):
            for x in range(nx):
                atual = dominios[y][x]
                for dx, dy, meu, dele in VIZINHOS:
                    vx, vy = x + dx, y + dy
                    if not (0 <= vx < nx and 0 <= vy < ny):
                        continue  # borda livre: lado aberto no limite e uma saida do fragmento
                    vizinhos = dominios[vy][vx]
                    if not vizinhos:
                        return False
                    permitidos = {
                        nome
                        for nome in atual
                        if any(_encosta(CATALOGO[nome], meu, CATALOGO[v], dele) for v in vizinhos)
                    }
                    if permitidos != atual:
                        atual &= permitidos
                        mudou = True
                        if not atual:
                            return False
    return True


def _resolver(grade: tuple[int, int], nomes: list[str], rng: random.Random) -> list[list[str]] | None:
    nx, ny = grade
    dominios = [[set(nomes) for _ in range(nx)] for _ in range(ny)]
    if not _propagar(dominios, grade):
        return None
    while True:
        celulas = [
            (len(dominios[y][x]), x, y)
            for y in range(ny)
            for x in range(nx)
            if len(dominios[y][x]) > 1
        ]
        if not celulas:
            return [[next(iter(dominios[y][x])) for x in range(nx)] for y in range(ny)]
        celulas.sort()
        _, escolhida_x, escolhida_y = celulas[0]
        opcoes = sorted(dominios[escolhida_y][escolhida_x])
        dominios[escolhida_y][escolhida_x] = {rng.choice(opcoes)}
        if not _propagar(dominios, grade):
            return None


def gerar_layout(
    grade: tuple[int, int],
    modulos: list[str] | None = None,
    seed: int = 0,
    tentativas: int = 64,
) -> list[list[str]]:
    """Layout determinístico: ``layout[y][x]`` com o nome do módulo de cada setor.

    A seed decide apenas o desempate do WFC; a mesma seed sempre devolve o mesmo layout. Se uma
    tentativa morre (contradição), a próxima usa ``seed + tentativa`` — continua determinístico.
    """
    nx, ny = int(grade[0]), int(grade[1])
    if nx < 1 or ny < 1:
        raise ValueError("grade precisa ter ao menos 1 x 1 setor")
    nomes = [str(m) for m in (modulos or sorted(CATALOGO))]
    if not nomes:
        raise ValueError("lista de modulos vazia")
    desconhecidos = [n for n in nomes if n not in CATALOGO]
    if desconhecidos:
        raise ValueError(f"modulo(s) fora do catalogo: {', '.join(desconhecidos)}")
    for tentativa in range(max(1, tentativas)):
        rng = random.Random(int(seed) + tentativa)
        layout = _resolver((nx, ny), nomes, rng)
        if layout is not None and not validar_layout(layout, (nx, ny)):
            return layout
    raise ValueError(f"WFC nao encontrou layout valido (grade {nx}x{ny}, seed {seed})")


def caixas_do_modulo(nome: str, tamanho: float, altura: float) -> list[dict]:
    """Caixas do setor em metros: placa, piso recuado, pilares e paredes parciais.

    Por que assim (medido em 11/11/2026): duas caixas que encostam face a face no limite do modulo
    dividem a aresta do canto e o G1 acusa 4 faces na mesma aresta. A peca de piso evita isso por
    construcao — tudo que "encosta" tem a aresta **dentro** da face do outro:

    * placa: ocupa o modulo inteiro (0..tam) e define o bbox que encaixa no setor vizinho;
    * piso: recuado ``esp`` e apoiado na placa (aresta de baixo dentro da face de cima da placa);
    * pilares: recuados, apoiados na placa;
    * parede parcial: so no meio do lado fechado, apoiada no piso — nao alcanca canto nem vizinha.

    Sem cor: quem pinta e o provider (o mesmo vocabulario do blocky: cor + padrao).
    """
    if nome not in CATALOGO:
        raise ValueError(f"modulo desconhecido: {nome}")
    tam = float(tamanho)
    alt = float(altura)
    esp = round(tam * 0.05, 4)  # espessura de placa/piso/parede: 5% do modulo
    sockets = CATALOGO[nome]["sockets"]
    caixas: list[dict] = [
        {"nome": "placa", "min": [0.0, 0.0, 0.0], "max": [tam, tam, esp], "papel": "piso"},
        {
            "nome": "piso",
            "min": [esp, esp, esp],
            "max": [tam - esp, tam - esp, 2 * esp],
            "papel": "piso",
        },
    ]

    # parede parcial: metade central do lado, apoiada no piso (z = 2*esp), sem tocar canto
    meio0, meio1 = round(tam * 0.30, 4), round(tam * 0.70, 4)
    y0, y1 = 2 * esp, 3 * esp
    x0, x1 = 2 * esp, 3 * esp
    if sockets[0] == FECHADO:  # norte: parede no meio, encostada no limite norte
        caixas.append(
            {"nome": "parede_norte", "min": [meio0, tam - 3 * esp, 2 * esp], "max": [meio1, tam - 2 * esp, alt], "papel": "parede"}
        )
    if sockets[1] == FECHADO:  # sul
        caixas.append(
            {"nome": "parede_sul", "min": [meio0, y0, 2 * esp], "max": [meio1, y1, alt], "papel": "parede"}
        )
    if sockets[2] == FECHADO:  # leste
        caixas.append(
            {"nome": "parede_leste", "min": [tam - 3 * esp, meio0, 2 * esp], "max": [tam - 2 * esp, meio1, alt], "papel": "parede"}
        )
    if sockets[3] == FECHADO:  # oeste
        caixas.append(
            {"nome": "parede_oeste", "min": [x0, meio0, 2 * esp], "max": [x1, meio1, alt], "papel": "parede"}
        )

    # pilar de canto: recuado esp, apoiado na placa
    p = round(tam * 0.06, 4)
    interna = tam - esp - p
    for cx, cy in ((esp, esp), (interna, esp), (esp, interna), (interna, interna)):
        caixas.append(
            {
                "nome": f"pilar_{int(cx)}_{int(cy)}",
                "min": [cx, cy, esp],
                "max": [cx + p, cy + p, alt],
                "papel": "pilar",
            }
        )
    return caixas
