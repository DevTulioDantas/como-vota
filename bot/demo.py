"""Votação FICTÍCIA para testar o layout sem acessar a API.

Nomes, partidos e proposição são inventados de propósito: o perfil nunca
deve publicar um voto que não aconteceu. As imagens do modo demo saem com
a marca d'água "EXEMPLO FICTÍCIO".
"""
from __future__ import annotations

import random

from bot.models import Voto, Votacao

PARTIDOS = {  # sigla fictícia: (bancada, chance de votar Sim)
    "PAA": (92, .85), "PBB": (68, .2), "PCC": (59, .7), "PDD": (48, .55), "PEE": (44, .9),
    "PFF": (40, .3), "PGG": (35, .6), "PHH": (25, .75), "PII": (22, .1), "PJJ": (18, .5),
    "PKK": (16, .65), "PLL": (14, .4), "PMM": (12, .8), "PNN": (10, .25), "POO": (6, .5), "PPP": (4, .5),
}
UFS = "AC AL AM AP BA CE DF ES GO MA MG MS MT PA PB PE PI PR RJ RN RO RR RS SC SE SP TO".split()
NOMES = "Ana Bruno Carla Diego Elisa Fábio Gisele Hugo Íris João Karen Lucas Marta Nilo Olga Paulo Rita Sérgio Tânia Vitor".split()
SOBRENOMES = "Almeida Barros Campos Duarte Esteves Freitas Gomes Lima Moraes Nunes Prado Queiroz Rocha Teixeira Vieira".split()


def votacao_exemplo(semente: int = 7, apertado: bool = False) -> Votacao:
    rnd = random.Random(semente)
    votos, orientacoes = [], {}
    for sigla, (bancada, p_sim) in PARTIDOS.items():
        orientacoes[sigla] = "Sim" if p_sim >= .6 else "Não" if p_sim <= .35 else "Liberado"
        for _ in range(bancada):
            r = rnd.random()
            chance = p_sim - .07 if apertado else p_sim  # demo do formato "placar apertado"
            voto = "Sim" if r < chance * .96 else "Abstenção" if r > .985 else "Não"
            if rnd.random() < .04:
                voto = "Obstrução"
            votos.append(Voto(
                nome=f"{rnd.choice(NOMES)} {rnd.choice(SOBRENOMES)}",
                partido=sigla, uf=rnd.choice(UFS), voto=voto, voto_original=voto,
            ))
    return Votacao(
        id="camara-demo-0001",
        casa="camara",
        data="2026-10-07",
        proposicao="PL 0000/2026 (exemplo)",
        tipo_proposicao="PL",
        ementa=("Altera regras de exemplo para o cadastro de bibliotecas municipais e cria prazo "
                "de 180 dias para que os municípios atualizem as informações no sistema nacional."),
        descricao=("Rejeitado" if apertado else "Aprovado") + " o texto-base do Substitutivo ao Projeto de Lei (exemplo fictício).",
        aprovada=sum(v.voto == "Sim" for v in votos) > sum(v.voto == "Não" for v in votos),
        url_fonte="https://dadosabertos.camara.leg.br",
        votos=votos,
        orientacoes=orientacoes,
        orientacao_governo="Sim",
    )


TEMAS_SEMANA = [  # (proposição fictícia, título, data, aprovada, desvio de chance de Sim)
    ("PL 0001/2026", "Regras de exemplo para cadastro de bibliotecas municipais", "2026-10-06", True, 0.0),
    ("PL 0002/2026", "Prazo de exemplo para renovação de licenças de táxi", "2026-10-07", False, -0.35),
    ("PEC 0003/2026", "Emenda de exemplo sobre calendário de feriados regionais", "2026-10-08", True, 0.1),
]


def semana_exemplo(semente: int = 11) -> list[tuple[Votacao, dict]]:
    """Três votações FICTÍCIAS com o mesmo elenco, para testar o Voto da Semana."""
    rnd = random.Random(semente)
    elenco = []
    for sigla, (bancada, p_sim) in PARTIDOS.items():
        for i in range(bancada):
            elenco.append((f"demo-{sigla}-{i}", f"{rnd.choice(NOMES)} {rnd.choice(SOBRENOMES)}", sigla, rnd.choice(UFS), p_sim))
    pautas = []
    for n, (prop, titulo, data, aprovada, desvio) in enumerate(TEMAS_SEMANA):
        votos = []
        for pid, nome, sigla, uf, p_sim in elenco:
            if rnd.random() < .06:
                continue  # sem registro de voto
            r = rnd.random()
            p = min(max(p_sim + desvio, .02), .98)
            voto = "Sim" if r < p * .97 else "Abstenção" if r > .99 else "Não"
            votos.append(Voto(nome=nome, partido=sigla, uf=uf, voto=voto, voto_original=voto, id=pid))
        v = Votacao(
            id=f"camara-demo-semana-{n}", casa="camara", data=data, proposicao=prop,
            tipo_proposicao=prop.split()[0], ementa=titulo, descricao="Votação fictícia de exemplo.",
            aprovada=aprovada, url_fonte="https://dadosabertos.camara.leg.br", votos=votos,
        )
        pautas.append((v, {"titulo": titulo, "resultado": "APROVADA" if aprovada else "REJEITADA"}))
    return pautas


def bancada_exemplo() -> dict:
    """Bancada do Estado FICTÍCIA (70 nomes, como SP), para testar o layout."""
    from datetime import date
    from bot.frias import montar_bancada
    rnd = random.Random(5)
    deps = [{"nome": f"{rnd.choice(NOMES)} {rnd.choice(SOBRENOMES)}", "partido": rnd.choice(list(PARTIDOS)[:9])}
            for _ in range(70)]
    return montar_bancada("SP", deps, date(2026, 10, 13))
