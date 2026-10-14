"""Versão 9:16 (1080x1920) de cada post, para slideshow de fotos no TikTok.

Por que a postagem é manual
  A API de postagem do TikTok exige app aprovado em auditoria (antes disso os
  posts saem privados) e só aceita fotos hospedadas em domínio verificado.
  Então o bot prepara o pacote e, quando você aprova o post no Telegram, manda
  as imagens em qualidade original (como arquivo) e a legenda pronta para colar.

Layout
  O slide original é reduzido para 85% da largura e centralizado na área livre
  da tela do TikTok: abaixo da barra superior (~150px) e acima da legenda e dos
  botões (~380px de baixo e ~120px à direita). O fundo repete a cor do slide.
"""
from __future__ import annotations

import base64
import os
from pathlib import Path

from PIL import Image

LARGURA, ALTURA = 1080, 1920
ESCALA = 0.85
TOPO_LIVRE = 150          # barra "Seguindo | Para você"
CENTRO_Y = 845            # meio da área livre (150 → 1540)
HASHTAGS = "#ComoVotaDeputado #CongressoNacional #Política #CâmaraDosDeputados #SenadoFederal"
LIMITE_LEGENDA = 900


def ativo() -> bool:
    return os.getenv("TIKTOK_EXPORT", "1") != "0"


def _cor(img: Image.Image) -> tuple[str, bool]:
    r, g, b = img.convert("RGB").getpixel((6, 6))
    escura = (0.299 * r + 0.587 * g + 0.114 * b) < 140
    return f"#{r:02x}{g:02x}{b:02x}", escura


def legenda_tiktok(legenda_ig: str) -> str:
    """Mesma legenda, sem as hashtags do Instagram e mais curta."""
    linhas = [l for l in legenda_ig.split("\n") if not l.lstrip().startswith("#")]
    texto = "\n".join(linhas).strip()
    while "\n\n\n" in texto:
        texto = texto.replace("\n\n\n", "\n\n")
    if len(texto) > LIMITE_LEGENDA:
        corte = texto.rfind("\n", 0, LIMITE_LEGENDA)
        texto = texto[: corte if corte > 200 else LIMITE_LEGENDA].rstrip() + "…"
    return f"{texto}\n\n{HASHTAGS}"


def exportar(pasta: Path, legenda_ig: str) -> list[Path]:
    """Gera pasta/tiktok/slide_XX.jpg e pasta/tiktok/legenda.txt a partir dos slides do post."""
    from bot.render.renderer import _capturar, fontes_css

    originais = sorted(pasta.glob("slide_*.jpg"))
    destino = pasta / "tiktok"
    destino.mkdir(parents=True, exist_ok=True)
    for antigo in destino.glob("slide_*.jpg"):
        antigo.unlink()

    secoes = []
    for i, arq in enumerate(originais, 1):
        im = Image.open(arq)
        w, h = im.size
        lw = int(LARGURA * ESCALA)
        lh = int(h * lw / w)
        topo = max(TOPO_LIVRE + 20, CENTRO_Y - lh // 2)
        fundo, _ = _cor(im)
        dados = base64.b64encode(arq.read_bytes()).decode()
        secoes.append(f"""
<section class="t" id="t-{i}" style="background:{fundo}">
  <img src="data:image/jpeg;base64,{dados}" alt="" style="left:{(LARGURA - lw) // 2}px;top:{topo}px;width:{lw}px;height:{lh}px">
</section>""")

    html = f"""<!doctype html><html><head><meta charset="utf-8"><style>{fontes_css()}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  .t {{ width: {LARGURA}px; height: {ALTURA}px; position: relative; overflow: hidden; }}
  .t img {{ position: absolute; border-radius: 18px; }}
</style></head><body>{''.join(secoes)}</body></html>"""

    saidas = [destino / f"slide_{i:02d}.jpg" for i in range(1, len(originais) + 1)]
    _capturar(html, [f"#t-{i}" for i in range(1, len(originais) + 1)], saidas, altura=ALTURA)
    (destino / "legenda.txt").write_text(legenda_tiktok(legenda_ig), encoding="utf-8")
    return saidas
