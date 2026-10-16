"""Transforma uma votação em imagens JPEG 1080x1080, no padrão do
Guia de Marca "Como Vota, Deputado?" v1.0.

As fontes da marca (Archivo Black, Inter, IBM Plex Mono — licença OFL) ficam
em render/fonts e são embutidas no HTML, então o resultado é idêntico no seu
computador e no GitHub Actions, com ou sem internet.
"""
from __future__ import annotations

import base64
from datetime import date
from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.sync_api import sync_playwright

from bot import cta, entenda
from bot.models import NAO, SIM, Votacao

PASTA = Path(__file__).parent
PASTA_TEMPLATES = PASTA / "templates"
PASTA_FONTES = PASTA / "fonts"
TAMANHO = 1080  # quadrado, conforme o guia (capa 1080x1080)
MAX_PARTIDOS = 10
MAX_DISSIDENTES = 16

FONTES = [  # (família, peso, arquivo)
    ("Archivo Black", 400, "ArchivoBlack-400.woff2"),
    ("Inter", 400, "Inter-400.woff2"),
    ("Inter", 500, "Inter-500.woff2"),
    ("Inter", 600, "Inter-600.woff2"),
    ("Inter", 700, "Inter-700.woff2"),
    ("IBM Plex Mono", 400, "IBMPlexMono-400.woff2"),
    ("IBM Plex Mono", 600, "IBMPlexMono-600.woff2"),
    ("IBM Plex Mono", 700, "IBMPlexMono-700.woff2"),
]

_env = Environment(loader=FileSystemLoader(PASTA_TEMPLATES), autoescape=select_autoescape(["html"]))

CASA = {
    "camara": ("Câmara", "Câmara dos Deputados", "deputado"),
    "senado": ("Senado", "Senado Federal", "senador"),
}
SEQUENCIA_PADRAO = ["capa", "placar", "partidos", "dissidentes", "cta_teste", "final"]

# Mapa em grade: um quadrado por UF, na posição aproximada do mapa (linha, coluna).
GRADE_UF = {
    "RR": (0, 2), "AP": (0, 4),
    "AM": (1, 1), "PA": (1, 3), "MA": (1, 4), "CE": (1, 5), "RN": (1, 6),
    "AC": (2, 0), "RO": (2, 1), "MT": (2, 2), "TO": (2, 3), "PI": (2, 4), "PE": (2, 5), "PB": (2, 6),
    "MS": (3, 2), "GO": (3, 3), "DF": (3, 4), "BA": (3, 5), "AL": (3, 6),
    "PR": (4, 2), "SP": (4, 3), "MG": (4, 4), "ES": (4, 5), "SE": (4, 6),
    "SC": (5, 2), "RJ": (5, 4),
    "RS": (6, 2),
}


def _misturar(a: str, b: str, t: float) -> str:
    ca = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    cb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(ca, cb))


def _cor_pct(pct: float) -> tuple[str, str]:
    """Cor do quadrado (vermelho → neutro → verde) e cor do texto que contrasta."""
    neutro, verde, vermelho = "#E2DCCF", "#1FA97A", "#E4433C"
    cor = _misturar(neutro, verde, (pct - .5) * 2) if pct >= .5 else _misturar(neutro, vermelho, (.5 - pct) * 2)
    return cor, ("#101820" if .3 < pct < .7 else "#FFFFFF")


def _estados(v: Votacao) -> dict:
    por_uf: dict[str, list[int]] = {uf: [0, 0] for uf in GRADE_UF}
    for voto in v.votos:
        if voto.uf in por_uf and voto.voto in (SIM, NAO):
            por_uf[voto.uf][0 if voto.voto == SIM else 1] += 1
    tiles, maioria = [], {"sim": 0, "nao": 0, "empate": 0}
    for uf, (lin, col) in GRADE_UF.items():
        s, n = por_uf[uf]
        if s + n == 0:
            tiles.append({"uf": uf, "lin": lin + 1, "col": col + 1, "texto": "—", "cor": "#C9CED6", "tinta": "#101820"})
            continue
        cor, tinta = _cor_pct(s / (s + n))
        tiles.append({"uf": uf, "lin": lin + 1, "col": col + 1, "texto": f"{s}×{n}", "cor": cor, "tinta": tinta})
        maioria["sim" if s > n else "nao" if n > s else "empate"] += 1
    return {"tiles": tiles, "maioria": maioria}
MAX_SLIDES = 10  # limite do carrossel do Instagram


def _dominio_cta(demo: bool) -> str:
    """Endereço do teste para o slide de chamada; vazio = slide desligado.
    No modo demo usa um endereço de exemplo para dar para ver o slide."""
    return cta.dominio() or ("seu-site.com.br" if demo else "")


@lru_cache(maxsize=1)
def fontes_css() -> str:
    regras = []
    for familia, peso, arquivo in FONTES:
        dados = base64.b64encode((PASTA_FONTES / arquivo).read_bytes()).decode()
        regras.append(
            f'@font-face{{font-family:"{familia}";font-weight:{peso};font-style:normal;'
            f'src:url(data:font/woff2;base64,{dados}) format("woff2");}}'
        )
    return "\n".join(regras)


def logo_svg(mono: bool = False, sem_nome: bool = False, cargo: str = "Deputado") -> str:
    return _env.get_template("logo.svg").render(logo_mono=mono, logo_sem_nome=sem_nome, cargo=cargo)


def marca_cargo(casa: str) -> str:
    """O nome do perfil é "Como Vota Deputado?", mas post do Senado se assina "Como Vota Senador?"."""
    return "Senador" if casa == "senado" else "Deputado"


def _partidos(v: Votacao) -> list[dict]:
    linhas = v.por_partido()
    if len(linhas) <= MAX_PARTIDOS:
        return linhas
    topo, resto = linhas[: MAX_PARTIDOS - 1], linhas[MAX_PARTIDOS - 1:]
    agregado = {"partido": f"Outros ({len(resto)})", "orientacao": None}
    for k in ("total", "sim", "nao", "outros", "abstencao", "nao_votou"):
        agregado[k] = sum(l[k] for l in resto)
    return topo + [agregado]


def _curto(texto: str, limite: int) -> str:
    return texto if len(texto) <= limite else texto[: limite - 3].rsplit(" ", 1)[0] + "…"


def contexto(v: Votacao, textos: dict, handle: str, demo: bool = False, formato: dict | None = None) -> dict:
    p = v.placar()
    total = sum(p.values()) or 1
    outros = total - p[SIM] - p[NAO]
    partidos = _partidos(v)
    dissidentes = sorted(v.dissidentes(), key=lambda d: (d.partido, d.nome)) if v.casa == "camara" else []
    site_dominio = _dominio_cta(demo)

    # A ordem dos slides vem do formato; slides sem conteúdo são pulados.
    estados = _estados(v)
    slides = [s for s in ((formato or {}).get("sequencia") or SEQUENCIA_PADRAO)
              if (s != "dissidentes" or dissidentes) and (s != "cta_teste" or site_dominio)]
    # logo depois da capa, o slide "O que está em votação": o que o projeto faz, a etapa e o próximo passo
    capa_estilo = (formato or {}).get("capa", "classico")
    if "entenda" not in slides:
        slides.insert(1, "entenda")
    minoria = v.minoria()
    if minoria and "minoria" not in slides:
        depois = slides.index("placar") + 1 if "placar" in slides else 2
        slides.insert(depois, "minoria")
    if len(slides) > MAX_SLIDES:
        slides = slides[: MAX_SLIDES - 1] + ["final"]
    quorum = v.quorum()
    etapa, so_etapa = entenda.explicar_etapa(v)
    resumo = textos["resumo"]
    # sem IA o resumo é a ementa cortada: aqui cabe a ementa inteira
    texto_entenda = v.ementa if v.ementa and resumo.rstrip("…").strip() in v.ementa else resumo
    dif = abs(p[SIM] - (quorum[0] if quorum else p[NAO]))

    d = date.fromisoformat(v.data[:10])
    casa_curta, casa_completa, quem = CASA[v.casa]
    return {
        "fontes_css": fontes_css(),
        "logo_svg": logo_svg(cargo=marca_cargo(v.casa)),
        "marca_cargo": marca_cargo(v.casa),
        "slides": slides,
        "titulo": textos["titulo"],
        # títulos longos encolhem para caber em até ~4 linhas na capa
        "tamanho_titulo": 66 if len(textos["titulo"]) <= 45 else 58 if len(textos["titulo"]) <= 65 else 50,
        "resumo": _curto(textos["resumo"], 230),
        "resultado": textos["resultado"],
        "carimbo": textos.get("carimbo") or textos["resultado"],
        "proposicao": v.proposicao,
        "casa_nome": casa_completa,
        "casa_nome_completo": casa_completa,
        "quem": quem,
        "quem_plural": {"senador": "senadores"}.get(quem, quem + "s"),
        "capa_estilo": capa_estilo,
        "tipo_txt": entenda.explicar_tipo(v),
        "entenda_texto": _curto(texto_entenda, 380),
        "etapa_txt": etapa,
        "so_etapa": so_etapa,
        "detalhes": textos.get("detalhes") or [],
        "proximo_passo": entenda.proximo_passo(v),
        "faixa_capa": (formato or {}).get("faixa_capa") or "Veja o voto deles →",
        "diferenca_txt": f"{dif} voto" if dif == 1 else f"{dif} votos",
        "quorum_num": quorum[0] if quorum else None,
        "quorum_txt": quorum[1] if quorum else "",
        "quorum_faltaram": max(0, quorum[0] - p[SIM]) if quorum else 0,
        "site_dominio": site_dominio,
        "estados": estados,
        "data_br": d.strftime("%d/%m/%Y"),
        "data_curta": d.strftime("%d/%m"),
        "placar": p,
        "pct_sim": 100 * p[SIM] / total,
        "pct_nao": 100 * p[NAO] / total,
        "pct_outros": 100 * outros / total,
        "descricao": v.descricao,
        "descricao_curta": _curto(v.descricao, 150),
        "orientacao_governo": v.orientacao_governo,
        "partidos": partidos,
        "maior_bancada": max((l["total"] for l in partidos), default=1),
        "dissidentes": dissidentes[:MAX_DISSIDENTES],
        "minoria": {"lado": minoria[0], "votos": minoria[1],
                    "maioria": p[SIM] if minoria[0] == NAO else p[NAO],
                    "lado_maioria": "SIM" if minoria[0] == NAO else "NÃO"} if minoria else None,
        "dissidentes_restantes": max(0, len(dissidentes) - MAX_DISSIDENTES),
        "handle": handle,
        "demo": demo,
    }


def _capturar(html: str, seletores: list[str], destinos: list[Path], tamanho: int = TAMANHO, altura: int | None = None) -> None:
    with sync_playwright() as pw:
        navegador = pw.chromium.launch()
        pagina = navegador.new_page(viewport={"width": tamanho, "height": altura or tamanho})
        pagina.set_content(html, wait_until="load")
        pagina.evaluate("document.fonts.ready")
        for sel, destino in zip(seletores, destinos):
            tipo = "png" if destino.suffix == ".png" else "jpeg"
            extra = {} if tipo == "png" else {"quality": 92}
            pagina.locator(sel).screenshot(path=str(destino), type=tipo, **extra)
        navegador.close()


def renderizar(v: Votacao, textos: dict, pasta_saida: Path, handle: str, demo: bool = False,
               formato: dict | None = None) -> list[Path]:
    pasta_saida.mkdir(parents=True, exist_ok=True)
    for antigo in pasta_saida.glob("slide_*.jpg"):  # ao regerar, não deixa slides sobrando
        antigo.unlink()
    ctx = contexto(v, textos, handle, demo, formato)
    html = _env.get_template("carrossel.html").render(**ctx)

    n = len(ctx["slides"])
    destinos = [pasta_saida / f"slide_{i:02d}.jpg" for i in range(1, n + 1)]
    _capturar(html, [f"#slide-{i}" for i in range(1, n + 1)], destinos)
    return destinos


def renderizar_avatar(destino: Path, mono: bool = True) -> Path:
    """Foto de perfil 1080x1080: versão monocromática do símbolo (guia, seção 2)."""
    html = f"""<!doctype html><html><head><meta charset="utf-8"><style>{fontes_css()}
    *{{margin:0}} #a{{width:{TAMANHO}px;height:{TAMANHO}px;background:#0E2233;display:flex;
    align-items:center;justify-content:center}} #a svg{{width:880px;height:auto;margin-top:150px}}</style></head>
    <body><div id="a">{logo_svg(mono=mono, sem_nome=True)}</div></body></html>"""
    destino.parent.mkdir(parents=True, exist_ok=True)
    _capturar(html, ["#a"], [destino])
    return destino


def renderizar_voto_semana(dados: dict, destino: Path, demo: bool = False) -> Path:
    """Post único 1080x1350 do formato "Voto da Semana"."""
    n = len(dados["itens"])
    nome = dados["nome"]
    ctx = {
        **dados,
        "fontes_css": fontes_css(),
        "demo": demo,
        "fonte": "Câmara dos Deputados" if dados["casa"] == "camara" else "Senado Federal",
        "fonte_nome": 78 if len(nome) <= 14 else 64 if len(nome) <= 20 else 52,
        "altura_card": {1: 220, 2: 200, 3: 170, 4: 140}.get(n, 140),
        "fonte_tema": 34 if n <= 3 else 30,
    }
    html = _env.get_template("voto_semana.html").render(**ctx)
    destino.parent.mkdir(parents=True, exist_ok=True)
    _capturar(html, ["#post"], [destino], altura=1350)
    return destino


def renderizar_explicador(item: dict, pasta_saida: Path, handle: str, demo: bool = False,
                          formato: dict | None = None) -> list[Path]:
    """Carrossel de pauta fria (explicador ou Bancada do Estado), 1080x1080."""
    pasta_saida.mkdir(parents=True, exist_ok=True)
    for antigo in pasta_saida.glob("slide_*.jpg"):
        antigo.unlink()
    titulo = item["titulo"]
    slides = list(item["slides"])
    site_dominio = _dominio_cta(demo)
    posicao = (formato or {}).get("cta_teste", "antes_final")
    if site_dominio and posicao != "nao" and len(slides) + 3 <= MAX_SLIDES:
        slides.insert(len(slides) // 2 + len(slides) % 2 if posicao == "meio" else len(slides), {"tipo": "cta_teste"})
    ctx = {
        **item,
        "slides": slides,
        "site_dominio": site_dominio,
        "kicker_capa": (formato or {}).get("capa_kicker"),
        "faixa_capa": (formato or {}).get("faixa_capa"),
        "serie": item.get("serie") or "Entenda o Congresso",
        "fonte": item.get("fonte", "Congresso Nacional"),
        "nota": item.get("nota"),
        "fontes_css": fontes_css(),
        "logo_svg": logo_svg(),
        "handle": handle,
        "demo": demo,
        "tamanho_titulo": 76 if len(titulo) <= 30 else 66 if len(titulo) <= 50 else 56,
    }
    html = _env.get_template("explicador.html").render(**ctx)
    n = len(slides) + 2
    destinos = [pasta_saida / f"slide_{i:02d}.jpg" for i in range(1, n + 1)]
    _capturar(html, [f"#slide-{i}" for i in range(1, n + 1)], destinos)
    return destinos


FIXADOS = {"post-01-quem-somos": 6, "post-02-o-que-tem-aqui": 6, "post-03-faca-parte": 5}


def renderizar_fixados(pasta_saida: Path, handle: str) -> dict[str, list[Path]]:
    """Os 3 carrosséis fixados de conversão (1080x1350). Retorna {post: [imagens]}."""
    html = _env.get_template("fixados.html").render(fontes_css=fontes_css(), logo_svg=logo_svg(), handle=handle)
    seletores, destinos, saida = [], [], {}
    for i, (nome, n) in enumerate(FIXADOS.items(), 1):
        (pasta_saida / nome).mkdir(parents=True, exist_ok=True)
        saida[nome] = []
        for j in range(1, n + 1):
            seletores.append(f"#p{i}-{j}")
            destino = pasta_saida / nome / f"slide_{j:02d}.jpg"
            destinos.append(destino)
            saida[nome].append(destino)
    _capturar(html, seletores, destinos, altura=1350)
    return saida
