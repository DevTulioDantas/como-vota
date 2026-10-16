"""Elementos visuais desenhados a partir dos dados: hemiciclo do plenário e fotos oficiais.

O hemiciclo mostra cada cadeira da Casa como um ponto colorido pelo voto (SIM à esquerda,
NÃO à direita, abstenção e quem não votou no meio). As fotos vêm dos sites oficiais da
Câmara e do Senado; se não carregarem, o slide usa as iniciais e o post sai igual.
"""
from __future__ import annotations

import base64
import io
import logging
import math
import time
from functools import lru_cache

import requests

from bot.models import ABSTENCAO, NAO, OBSTRUCAO, SIM, Votacao

log = logging.getLogger(__name__)

ASSENTOS = {"camara": 513, "senado": 81}
CORES = {SIM: "#1FA97A", NAO: "#E4433C", ABSTENCAO: "#8A94A0", OBSTRUCAO: "#8A94A0"}
COR_SEM_VOTO = "#33465A"  # cadeira sem voto registrado (licença, missão, ausência): nunca "falta"
FOTO = {
    "camara": "https://www.camara.leg.br/internet/deputado/bandep/{id}.jpg",
    "senado": "https://www.senado.leg.br/senadores/img/fotos-oficiais/senador{id}.jpg",
}


def _cadeiras(n: int) -> list[tuple[float, float]]:
    """Posições (ângulo, raio) de n cadeiras em fileiras concêntricas, da esquerda para a direita."""
    fileiras = max(2, math.ceil(math.sqrt(n) / 2.1))
    raios = [0.38 + 0.62 * i / (fileiras - 1) for i in range(fileiras)]
    por_fileira = [max(1, round(n * r / sum(raios))) for r in raios]
    por_fileira[-1] += n - sum(por_fileira)  # o arredondamento sobra ou falta na fileira de fora
    pontos = []
    for r, k in zip(raios, por_fileira):
        for j in range(k):
            pontos.append((math.pi * (1 - j / (k - 1)) if k > 1 else math.pi / 2, r))
    pontos.sort(key=lambda p: (-p[0], p[1]))
    return pontos, raios, por_fileira


def hemiciclo_svg(v: Votacao, largura: int = 900) -> str:
    """SVG do plenário com uma cadeira por parlamentar. Cadeiras sem voto na lista oficial
    (a Câmara só lista quem votou) aparecem como "sem voto registrado"."""
    p = v.placar()
    total = max(ASSENTOS.get(v.casa, 0), sum(p.values()))
    ordem = ([CORES[SIM]] * p[SIM] + [CORES[ABSTENCAO]] * (p[ABSTENCAO] + p[OBSTRUCAO])
             + [COR_SEM_VOTO] * (total - p[SIM] - p[NAO] - p[ABSTENCAO] - p[OBSTRUCAO]) + [CORES[NAO]] * p[NAO])
    pontos, raios, por_fileira = _cadeiras(total)
    passo_radial = raios[1] - raios[0]
    passo_arco = math.pi * raios[-1] / max(1, por_fileira[-1] - 1)
    raio_ponto = 0.42 * min(passo_radial, passo_arco)
    m = raio_ponto + 0.01  # margem do tamanho do ponto: no Senado (81 cadeiras) eles são grandes
    altura = round(largura * (1 + 2 * m) / (2 + 2 * m))
    circulos = "".join(
        f'<circle cx="{r * math.cos(a):.4f}" cy="{-r * math.sin(a):.4f}" r="{raio_ponto:.4f}" fill="{cor}"/>'
        for (a, r), cor in zip(pontos, ordem))
    return (f'<svg class="hemiciclo" width="{largura}" height="{altura}" '
            f'viewBox="{-1 - m:.4f} {-1 - m:.4f} {2 + 2 * m:.4f} {1 + 2 * m:.4f}" '
            f'xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Plenário: {p[SIM]} SIM, {p[NAO]} NÃO">'
            f'{circulos}</svg>')


@lru_cache(maxsize=64)
def foto(casa: str, parlamentar_id: str, lado: int = 240) -> str:
    """Foto oficial reduzida, como data URI para embutir no HTML. Vazio se não der para baixar."""
    if not parlamentar_id or casa not in FOTO:
        return ""
    try:
        from PIL import Image
        for tentativa in range(3):  # o servidor do Senado derruba conexões com frequência
            try:
                r = requests.get(FOTO[casa].format(id=parlamentar_id), timeout=15)
                r.raise_for_status()
                break
            except requests.RequestException:
                if tentativa == 2:
                    raise
                time.sleep(2)
        img = Image.open(io.BytesIO(r.content)).convert("RGB")
        menor = min(img.size)  # recorte quadrado pelo topo: o rosto fica na parte de cima
        img = img.crop(((img.width - menor) // 2, 0, (img.width + menor) // 2, menor)).resize((lado, lado))
        saida = io.BytesIO()
        img.save(saida, "JPEG", quality=85)
        return "data:image/jpeg;base64," + base64.b64encode(saida.getvalue()).decode()
    except Exception as e:  # foto é acessório: sem ela, o slide usa as iniciais
        log.warning("Sem foto de %s %s (%s)", casa, parlamentar_id, e)
        return ""


def iniciais(nome: str) -> str:
    partes = [p for p in nome.split() if p[:1].isalpha()]
    return ((partes[0][0] + partes[-1][0]) if len(partes) > 1 else nome[:2]).upper()
