"""Escolhe quais votações da semana viram post.

Regras simples e transparentes (ajuste os pesos à vontade):
- descarta votações secretas e com poucos votos registrados;
- prioriza tipos de proposição de maior impacto (PEC > PLP/MPV > PL ...);
- penaliza votações procedimentais (requerimentos, urgência, redação final);
- bônus para placares apertados;
- no máximo um post por proposição (fica a votação mais "de mérito").
"""
from __future__ import annotations

import unicodedata

from bot.models import NAO, SIM, Votacao

PESO_TIPO = {"PEC": 60, "PLP": 45, "MPV": 45, "PLV": 45, "PL": 35, "PDL": 20, "PRC": 10}

PENALIDADES = {
    "requerimento": -60,
    "urgencia": -50,
    "retirada de pauta": -60,
    "adiamento": -50,
    "redacao final": -40,
    "destaque": -20,
    "emenda": -10,
}
BONUS = {
    "texto-base": 25,
    "substitutivo": 15,
    "primeiro turno": 15,
    "segundo turno": 20,
    "proposta de emenda": 15,
    "projeto de lei": 10,
    "medida provisoria": 10,
}

MIN_VOTOS = {"camara": 200, "senado": 40}


def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")


def pontuar(v: Votacao) -> float:
    if v.secreta or not v.proposicao.strip(" /"):
        return -999
    p = v.placar()
    if p[SIM] + p[NAO] < MIN_VOTOS.get(v.casa, 0):
        return -999

    texto = _sem_acento(v.descricao)
    nota = PESO_TIPO.get(v.tipo_proposicao, 0)
    nota += sum(peso for termo, peso in PENALIDADES.items() if termo in texto)
    nota += sum(peso for termo, peso in BONUS.items() if termo in texto)

    total = p[SIM] + p[NAO]
    margem = abs(p[SIM] - p[NAO]) / total if total else 1
    nota += (1 - margem) * 30  # placar apertado rende mais conversa
    return nota


def selecionar(votacoes: list[Votacao], maximo: int = 3, nota_minima: float = 20) -> list[Votacao]:
    melhores: dict[str, tuple[float, Votacao]] = {}
    for v in votacoes:
        nota = pontuar(v)
        if nota < nota_minima:
            continue
        chave = f"{v.casa}:{v.proposicao}"
        if chave not in melhores or nota > melhores[chave][0]:
            melhores[chave] = (nota, v)
    ordenadas = sorted(melhores.values(), key=lambda t: -t[0])
    return [v for _, v in ordenadas[:maximo]]
