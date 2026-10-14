"""Pautas frias: conteúdo atemporal para os dias sem votação relevante.

Três fontes, usadas em rodízio (explicador → bancada → repost):

1. EXPLICADOR — fila editorial em pautas_frias/*.yaml (escrita por você, ou
   rascunhada com IA e revisada). Cada arquivo vira um carrossel e é usado
   uma única vez, em ordem de nome de arquivo. Quando a fila acaba, o bot
   avisa no Telegram.
2. BANCADA DO ESTADO — gerado automaticamente com dados da API da Câmara:
   quem são os deputados em exercício de uma UF e de quais partidos. Faz
   rodízio pelas 27 unidades da federação e recomeça no fim.
3. REPOST — um explicador que já foi publicado e ficou entre os 30% com maior
   pontuação (salvamentos e compartilhamentos por alcance, ver bot/metricas.py)
   volta a sair, com o formato e o visual atuais, depois de REPOST_APOS_DIAS
   (padrão 60). Só entra no rodízio quando há pelo menos 4 explicadores medidos.

Quando entram
  O comando diário `gerar` chama `precisa_de_fria()`: se nenhum post
  (não descartado) foi gerado nos últimos DIAS_SEM_POST_PARA_FRIA dias
  (padrão 3), gera UMA pauta fria. Como ela também conta como post, o
  relógio zera: em recesso, sai uma pauta fria a cada 3 dias.
"""
from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import yaml

from bot import storage
from bot.collectors.camara import BASE as CAMARA_API, _paginar

log = logging.getLogger(__name__)

PASTA_FILA = Path(__file__).resolve().parent.parent / "pautas_frias"
TIPOS_SLIDE = {"texto", "numero", "passos", "votos", "partidos", "lista"}
MAX_SLIDES_CONTEUDO = 8  # + capa + final = 10, o limite do carrossel
POR_PAGINA_LISTA = 16

UFS = {
    "AC": "Acre", "AL": "Alagoas", "AP": "Amapá", "AM": "Amazonas", "BA": "Bahia", "CE": "Ceará",
    "DF": "Distrito Federal", "ES": "Espírito Santo", "GO": "Goiás", "MA": "Maranhão", "MT": "Mato Grosso",
    "MS": "Mato Grosso do Sul", "MG": "Minas Gerais", "PA": "Pará", "PB": "Paraíba", "PR": "Paraná",
    "PE": "Pernambuco", "PI": "Piauí", "RJ": "Rio de Janeiro", "RN": "Rio Grande do Norte",
    "RS": "Rio Grande do Sul", "RO": "Rondônia", "RR": "Roraima", "SC": "Santa Catarina",
    "SP": "São Paulo", "SE": "Sergipe", "TO": "Tocantins",
}


def _slug(s: str) -> str:
    s = "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:50]


def _estado_frias(estado: dict) -> dict:
    f = estado.setdefault("frias", {})
    f.setdefault("usadas", [])
    f.setdefault("ufs_feitas", [])
    f.setdefault("reposts", {})
    f.setdefault("ultima_fonte", "repost")  # assim a primeira é um explicador
    return f


# ------------------------------------------------------------ quando entram

def precisa_de_fria(dias: int) -> bool:
    """True se nenhum post não descartado foi gerado nos últimos `dias` dias."""
    if dias <= 0:
        return False
    limite = datetime.now(timezone.utc) - timedelta(days=dias)
    if not storage.PASTA_RASCUNHOS.exists():
        return True
    for arq in storage.PASTA_RASCUNHOS.glob("*/meta.json"):
        try:
            meta = json.loads(arq.read_text(encoding="utf-8"))
            if meta.get("status") == "descartado" or meta.get("demo"):
                continue
            if datetime.fromisoformat(meta.get("criado_em", "1970-01-01T00:00:00+00:00")) >= limite:
                return False
        except (ValueError, OSError):
            continue
    return True


# ------------------------------------------------------------ fila editorial

def validar(item: dict, origem: str) -> dict:
    if not item.get("titulo") or not item.get("slides"):
        raise ValueError(f"{origem}: precisa de 'titulo' e 'slides'")
    if len(item["slides"]) > MAX_SLIDES_CONTEUDO:
        raise ValueError(f"{origem}: no máximo {MAX_SLIDES_CONTEUDO} slides de conteúdo")
    for i, s in enumerate(item["slides"], 1):
        if s.get("tipo") not in TIPOS_SLIDE:
            raise ValueError(f"{origem}: slide {i} com tipo inválido {s.get('tipo')!r}")
    return item


def carregar_fila() -> list[dict]:
    itens = []
    for arq in sorted(PASTA_FILA.glob("*.y*ml")):
        if arq.name.startswith("_"):
            continue
        item = yaml.safe_load(arq.read_text(encoding="utf-8")) or {}
        item["id"] = f"fria-{arq.stem}"
        item["fonte_tipo"] = "explicador"
        itens.append(validar(item, arq.name))
    return itens


def restantes(estado: dict) -> list[dict]:
    usadas = set(_estado_frias(estado)["usadas"])
    return [i for i in carregar_fila() if i["id"] not in usadas]


# ------------------------------------------------------------ bancada do estado

def bancada(uf: str, hoje: date | None = None) -> dict:
    """Carrossel com os deputados em exercício de uma UF (API da Câmara)."""
    hoje = hoje or date.today()
    deps = _paginar(f"{CAMARA_API}/deputados", {"siglaUf": uf, "ordem": "ASC", "ordenarPor": "nome", "itens": 100})
    if not deps:
        raise RuntimeError(f"API não retornou deputados para {uf}")
    return montar_bancada(uf, [{"nome": d.get("nome", ""), "partido": d.get("siglaPartido", "")} for d in deps], hoje)


def montar_bancada(uf: str, deputados: list[dict], hoje: date) -> dict:
    contagem: dict[str, int] = {}
    for d in deputados:
        contagem[d["partido"]] = contagem.get(d["partido"], 0) + 1
    partidos = sorted(contagem.items(), key=lambda kv: (-kv[1], kv[0]))
    nome_uf = UFS.get(uf, uf)
    n = len(deputados)

    slides = [{
        "tipo": "numero", "numero": str(n), "rotulo": "deputados federais em exercício",
        "texto": f"{nome_uf} tem hoje {n} representantes na Câmara dos Deputados, de {len(partidos)} partidos diferentes.",
    }, {
        "tipo": "partidos", "titulo": "Por partido",
        "linhas": [{"partido": p, "total": t} for p, t in partidos[:12]]
        + ([{"partido": f"Outros ({len(partidos) - 12})", "total": sum(t for _, t in partidos[12:])}] if len(partidos) > 12 else []),
    }]
    ordenados = sorted(deputados, key=lambda d: d["nome"])
    paginas = [ordenados[i:i + POR_PAGINA_LISTA] for i in range(0, n, POR_PAGINA_LISTA)]
    for i, pag in enumerate(paginas, 1):
        slides.append({
            "tipo": "lista",
            "titulo": "Os deputados" + (f" ({i}/{len(paginas)})" if len(paginas) > 1 else ""),
            "linhas": [{"nome": d["nome"], "detalhe": d["partido"]} for d in pag],
        })
    return validar({
        "id": f"fria-bancada-{uf.lower()}-{hoje:%Y%m%d}",
        "fonte_tipo": "bancada",
        "serie": "Bancada do Estado",
        "titulo": f"Quem representa {nome_uf} na Câmara",
        "resumo": f"Conheça os {n} deputados federais em exercício que representam {nome_uf} e veja de quais partidos eles são.",
        "fonte": f"Câmara dos Deputados · Dados Abertos (em exercício em {hoje:%d/%m/%Y})",
        "nota": "Partido atual de cada deputado, que pode ser diferente do partido pelo qual foi eleito.",
        "slides": slides,
    }, f"bancada {uf}")


def proxima_uf(estado: dict) -> str:
    f = _estado_frias(estado)
    faltam = [uf for uf in sorted(UFS) if uf not in f["ufs_feitas"]]
    if not faltam:
        f["ufs_feitas"].clear()
        faltam = sorted(UFS)
    return faltam[0]


# ------------------------------------------------------------ escolha

# ------------------------------------------------------------ repost

CICLO = ["explicador", "bancada", "repost"]
REPOST_MIN_AMOSTRA = 4     # explicadores medidos para haver com o que comparar
REPOST_MIN_ALCANCE = 100   # alcance mínimo para a pontuação valer
REPOST_PERCENTIL = 0.7     # só os 30% melhores


def _dias_repost() -> int:
    return int(os.getenv("REPOST_APOS_DIAS") or 60)


def candidatos_repost(estado: dict, agora: datetime | None = None, metas: list[dict] | None = None) -> list[dict]:
    """Explicadores que performaram bem e já podem voltar, do melhor para o pior."""
    from bot import metricas
    metas = metricas.todas_as_metas() if metas is None else metas
    agora = agora or datetime.now(timezone.utc)
    grupos: dict[str, dict] = {}
    for m in metas:
        if m.get("tipo") != "fria" or m.get("demo") or m.get("fonte_tipo") not in ("explicador", "repost"):
            continue
        base = m.get("base_id") or m["id"]
        g = grupos.setdefault(base, {"base_id": base, "pontuacao": None, "meta": None, "ultimo": None, "publicacoes": 0})
        quando = metricas.publicado_em(m)
        if quando:
            g["publicacoes"] += 1
            g["ultimo"] = max(quando, g["ultimo"]) if g["ultimo"] else quando
        met = m.get("metricas") or {}
        if met.get("pontuacao") is not None and (met.get("reach") or 0) >= REPOST_MIN_ALCANCE:
            if g["pontuacao"] is None or met["pontuacao"] > g["pontuacao"]:
                g["pontuacao"], g["meta"] = met["pontuacao"], m

    medidos = [g for g in grupos.values() if g["pontuacao"] is not None]
    if len(medidos) < REPOST_MIN_AMOSTRA:
        return []
    # ranking por pontuação (empate: o publicado há mais tempo primeiro); só os 30% de cima
    vazio = datetime.min.replace(tzinfo=timezone.utc)
    medidos.sort(key=lambda g: (-g["pontuacao"], g["ultimo"] or vazio))
    topo = medidos[: max(1, round((1 - REPOST_PERCENTIL) * len(medidos)))]
    limite = agora - timedelta(days=_dias_repost())
    gerados = _estado_frias(estado)["reposts"]
    saida = []
    for g in topo:
        if g["ultimo"] and g["ultimo"] > limite:
            continue
        if g["base_id"] in gerados and datetime.fromisoformat(gerados[g["base_id"]]) > limite:
            continue  # já tem repost gerado esperando aprovação ou recente
        saida.append(g)
    return saida


def item_repost(g: dict) -> dict:
    """Monta o item do repost. Usa o texto atual do YAML, se existir (pega correções)."""
    atual = next((i for i in carregar_fila() if i["id"] == g["base_id"]), None)
    item = dict(atual or g["meta"]["item"])
    m = g["meta"].get("metricas") or {}
    item.update(
        id=f"{g['base_id']}-r{g['publicacoes'] + 1}",
        base_id=g["base_id"],
        fonte_tipo="repost",
        repost_info=(f"🔁 REPOST · da última vez: {m.get('saved', 0)} salvamentos, "
                     f"{m.get('shares', 0)} compartilhamentos, alcance {m.get('reach', 0)} "
                     f"(pontuação {g['pontuacao']})"),
    )
    return item


# ------------------------------------------------------------ escolha

def escolher(estado: dict, coletar_bancada=None, candidatos: list[dict] | None = None) -> tuple[dict | None, list[str]]:
    """Próxima pauta fria no rodízio explicador → bancada → repost. Retorna (item, avisos)."""
    coletar_bancada = coletar_bancada or bancada
    f = _estado_frias(estado)
    avisos: list[str] = []
    fila = restantes(estado)
    reps = candidatos_repost(estado) if candidatos is None else candidatos
    i = CICLO.index(f["ultima_fonte"]) if f["ultima_fonte"] in CICLO else len(CICLO) - 1
    ordem = CICLO[i + 1:] + CICLO[: i + 1]

    for fonte in ordem:
        if fonte == "explicador":
            if fila:
                if len(fila) <= 3:
                    avisos.append(f"📚 Restam {len(fila) - 1} explicadores na fila de pautas frias. Que tal escrever mais?")
                return fila[0], avisos
            avisos.append("📚 A fila de explicadores acabou. Adicione novos arquivos em pautas_frias/.")
        elif fonte == "bancada":
            uf = proxima_uf(estado)
            try:
                return coletar_bancada(uf), avisos
            except Exception as e:
                log.warning("Bancada %s indisponível: %s", uf, e)
                avisos.append(f"⚠️ Não consegui gerar a Bancada de {uf}: {e}")
        elif fonte == "repost" and reps:
            return item_repost(reps[0]), avisos
    return None, avisos


def registrar_uso(estado: dict, item: dict) -> None:
    f = _estado_frias(estado)
    f["ultima_fonte"] = item["fonte_tipo"]
    if item["fonte_tipo"] == "explicador":
        f["usadas"].append(item["id"])
    elif item["fonte_tipo"] == "repost":
        f["reposts"][item["base_id"]] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    else:
        uf = item["id"].split("-")[2].upper()
        if uf not in f["ufs_feitas"]:
            f["ufs_feitas"].append(uf)


# ------------------------------------------------------------ legenda

def legenda(item: dict) -> str:
    linhas = [f"📌 {item['titulo']}", "", item.get("resumo", "")]
    if item.get("nota"):
        linhas += ["", item["nota"]]
    linhas += [
        "",
        "Arraste para o lado e salve para consultar depois.",
        f"🔎 Fonte: {item.get('fonte', 'Congresso Nacional')}",
        "",
        "#ComoVotaDeputado #EntendaOCongresso #CongressoNacional #Transparência",
    ]
    return "\n".join(linhas)[:2200]
