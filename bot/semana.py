"""Formato "Voto da Semana": um parlamentar em destaque e como ele votou nas
principais pautas da semana (imagem única, 1080x1350).

De onde vêm as pautas
  Dos rascunhos de votação dos últimos 7 dias (os mesmos que viraram
  carrossel), menos os descartados. Se houver menos de 2, o bot coleta a
  semana direto da API e usa o seletor normal.

Quem aparece
  Escolha AUTOMÁTICA e IMPARCIAL por rodízio: entre os parlamentares que
  estavam registrados em todas as pautas (ou no maior número delas), sorteia
  um que ainda não apareceu, com semente fixa por semana (o resultado é
  reproduzível). Só depois de todos aparecerem o rodízio recomeça.
  Também dá para escolher manualmente com --parlamentar "Nome".
"""
from __future__ import annotations

import json
import random
import unicodedata
from datetime import date, timedelta

from bot import selector, storage
from bot.models import ABSTENCAO, NAO, OBSTRUCAO, SIM, Votacao, Voto

MAX_PAUTAS = 4

ROTULO = {SIM: "SIM", NAO: "NÃO", ABSTENCAO: "ABSTENÇÃO", OBSTRUCAO: "OBSTRUÇÃO"}
AUSENTE = "NÃO VOTOU"  # sem registro de voto: pode ser licença, missão oficial ou ausência


def _norm(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn").strip()


def chave(v: Voto) -> str:
    return v.id or f"{_norm(v.nome)}|{v.uf}"


def rotulo_semana(d: date) -> str:
    ano, semana, _ = d.isocalendar()
    return f"SEMANA {semana:02d} · {ano}"


def id_rascunho(casa: str, d: date) -> str:
    ano, semana, _ = d.isocalendar()
    return f"semana-{casa}-{ano}-w{semana:02d}"


# ---------------------------------------------------------------- pautas

def pautas_dos_rascunhos(casa: str, fim: date, dias: int = 7) -> list[tuple[Votacao, dict]]:
    """Votações já transformadas em post nos últimos `dias` (exceto descartadas)."""
    inicio = fim - timedelta(days=dias)
    achadas = []
    if not storage.PASTA_RASCUNHOS.exists():
        return achadas
    for arq in storage.PASTA_RASCUNHOS.glob("*/meta.json"):
        try:
            meta = json.loads(arq.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        if meta.get("tipo") == "semana" or meta.get("status") == "descartado" or "votacao" not in meta:
            continue
        v = Votacao.from_dict(meta["votacao"])
        if v.casa != casa or not v.data or not (inicio <= date.fromisoformat(v.data[:10]) <= fim):
            continue
        achadas.append((v, meta.get("textos", {})))
    return achadas


def ordenar_e_limitar(pautas: list[tuple[Votacao, dict]], maximo: int = MAX_PAUTAS) -> list[tuple[Votacao, dict]]:
    vistas, saida = set(), []
    for v, t in sorted(pautas, key=lambda p: -selector.pontuar(p[0])):
        if v.proposicao in vistas:
            continue
        vistas.add(v.proposicao)
        saida.append((v, t))
    saida = saida[:maximo]
    saida.sort(key=lambda p: p[0].data)  # ordem cronológica no post
    return saida


# ---------------------------------------------------------------- parlamentar

def candidatos(pautas: list[tuple[Votacao, dict]]) -> dict[str, Voto]:
    """Parlamentares com registro no maior número de pautas (idealmente todas)."""
    presenca: dict[str, int] = {}
    ultimo: dict[str, Voto] = {}
    for v, _ in pautas:
        for voto in v.votos:
            k = chave(voto)
            presenca[k] = presenca.get(k, 0) + 1
            ultimo[k] = voto  # partido/UF mais recentes
    if not presenca:
        return {}
    melhor = max(presenca.values())
    return {k: ultimo[k] for k, n in presenca.items() if n == melhor}


def escolher(pautas, historico: list[str], semente: str, nome: str | None = None) -> Voto | None:
    if nome:
        alvo = _norm(nome)
        todos = {}
        for v, _ in pautas:
            for voto in v.votos:
                todos[chave(voto)] = voto
        achados = [vt for vt in todos.values() if alvo in _norm(vt.nome)]
        if len(achados) == 1:
            return achados[0]
        exatos = [vt for vt in achados if _norm(vt.nome) == alvo]
        return exatos[0] if len(exatos) == 1 else None

    pool = candidatos(pautas)
    restantes = sorted(k for k in pool if k not in set(historico))
    if not restantes:  # todos já apareceram: recomeça o rodízio
        historico.clear()
        restantes = sorted(pool)
    if not restantes:
        return None
    return pool[random.Random(semente).choice(restantes)]


# ---------------------------------------------------------------- conteúdo

def voto_em(v: Votacao, k: str) -> tuple[str, str]:
    """(rótulo, classe) do voto do parlamentar `k` na votação `v`."""
    for voto in v.votos:
        if chave(voto) == k:
            if voto.voto in ROTULO:
                return ROTULO[voto.voto], voto.voto
            return (voto.voto_original or "OUTRO").upper(), "Outro"
    return AUSENTE, "Ausente"


def iniciais(nome: str) -> str:
    partes = [p for p in nome.replace(".", " ").split() if p.lower() not in {"de", "da", "do", "das", "dos", "e"}]
    if not partes:
        return "?"
    return (partes[0][0] + (partes[-1][0] if len(partes) > 1 else "")).upper()


def montar(pautas, parlamentar: Voto, fim: date, textos_extras: dict | None = None) -> dict:
    k = chave(parlamentar)
    itens = []
    for v, textos in pautas:
        rot, classe = voto_em(v, k)
        titulo = textos.get("titulo") or v.ementa or v.descricao
        itens.append({
            "proposicao": v.proposicao,
            "tema": titulo if len(titulo) <= 90 else titulo[:87].rsplit(" ", 1)[0] + "…",
            "rotulo": rot,
            "classe": classe,
            "resultado": textos.get("resultado") or {True: "APROVADA", False: "REJEITADA", None: ""}[v.aprovada],
            "data": v.data,
            "url_fonte": v.url_fonte,
        })
    casa = pautas[0][0].casa
    return {
        "casa": casa,
        "semana": rotulo_semana(fim),
        "nome": parlamentar.nome,
        "partido": parlamentar.partido,
        "uf": parlamentar.uf,
        "iniciais": iniciais(parlamentar.nome),
        "cargo": "Deputado(a) federal" if casa == "camara" else "Senador(a)",
        "itens": itens,
        "chave": k,
    }


def legenda(dados: dict) -> str:
    quem = f"{dados['nome']} ({dados['partido']}-{dados['uf']})"
    linhas = [f"🗳️ Como {quem} votou essa semana?", ""]
    for it in dados["itens"]:
        linhas.append(f"• {it['proposicao']} — {it['tema']}: {it['rotulo']}")
    linhas += [
        "",
        "\"Não votou\" quer dizer que não há registro de voto. Pode ser licença, viagem oficial ou ausência.",
        "Parlamentar escolhido por rodízio automático entre os que participaram das votações da semana.",
        "",
        "Salve para conferir depois. 📌",
        "🔎 Fontes oficiais:",
    ]
    linhas += [f"{it['proposicao']}: {it['url_fonte']}" for it in dados["itens"] if it["url_fonte"]]
    linhas += ["", "#ComoVotaDeputado #VotoAberto #CongressoNacional #Transparência"]
    return "\n".join(linhas)[:2200]
