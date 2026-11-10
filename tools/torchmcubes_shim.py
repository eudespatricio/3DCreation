"""Shim de compatibilidade: torchmcubes -> PyMCubes (sem CUDA toolkit).

Por que existe: o TripoSR importa ``from torchmcubes import marching_cubes``, e ``torchmcubes``
compila kernels CUDA na instalacao — exige ``nvcc``. Esta maquina nao tem CUDA toolkit, so driver.
PyMCubes faz o mesmo marching cubes em C++ puro, compilavel com ``g++``.

Convencao de eixos (bug real, 10/11/2026)
-----------------------------------------
PyMCubes devolve vertices na ordem de eixos do array de entrada; ``torchmcubes`` devolve **invertido**
(e a razao de o TripoSR aplicar ``v_pos[..., [2,1,0]]`` depois). Se o shim nao inverter, a altura do
personagem vai para a profundidade e o resultado vira uma lamina chata.

    shim inverte [2,1,0]  +  TripoSR inverte [2,1,0]  =>  duas reflexoes se cancelam
    => posicoes corretas e winding das faces intacto (nenhuma reflexao liquida)

Verificacao: elipsoide alongado em X (0,85 x 0,45 x 0,20). Apos o flip do TripoSR, a maior extensao
tem de cair no eixo 0. Sem a inversao no shim, cai no eixo 2.

Instalacao: copie para ``<venv-gpu>/lib/python3.12/site-packages/torchmcubes.py``.
"""

import mcubes as _mc
import numpy as np
import torch

_EIXOS = [2, 1, 0]


def marching_cubes(volume, thresh):
    """Mesma assinatura de ``torchmcubes.marching_cubes``: (vol, thresh) -> (verts[N,3], faces[M,3])."""
    arr = volume.detach().cpu().numpy() if isinstance(volume, torch.Tensor) else np.asarray(volume)
    verts, faces = _mc.marching_cubes(arr.astype(np.float32), float(thresh))
    verts = verts[:, _EIXOS]
    return torch.from_numpy(verts.astype(np.float32)), torch.from_numpy(faces.astype(np.int64))
