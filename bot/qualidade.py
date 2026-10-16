"""Checagem automática dos dados antes de o rascunho chegar para aprovação.

Não bloqueia nada: os alertas aparecem no topo da mensagem do Telegram
("⚠️ Confira antes de aprovar") para você olhar a fonte oficial com atenção.
Um perfil que vive de credibilidade não pode publicar um placar errado.
"""
from __future__ import annotations

from collections import Counter

from bot.formatos import PROIBIDOS
from bot.models import NAO, SIM, Votacao, _sem_acento

TOLERANCIA_TOTAIS = 1   # diferença aceitável entre a contagem e o total oficial


def checar(v: Votacao) -> list[str]:
    alertas: list[str] = []
    p = v.placar()

    # 1. resultado informado x placar
    q = v.quorum()
    if v.aprovada is None:
        alertas.append("a API não informou se foi aprovada ou rejeitada (o carimbo da capa fica neutro)")
    elif q:
        alcancou = p[SIM] >= q[0]
        if v.aprovada != alcancou:
            alertas.append(f"o resultado ({'aprovada' if v.aprovada else 'rejeitada'}) não bate com o quórum: "
                           f"{p[SIM]} votos SIM para um mínimo de {q[0]}")
    elif v.aprovada and p[SIM] < p[NAO]:
        alertas.append(f"consta como aprovada, mas teve menos SIM ({p[SIM]}) que NÃO ({p[NAO]})")
    elif v.aprovada is False and p[SIM] > p[NAO] and not v.tipo_proposicao in ("PEC", "PLP"):
        alertas.append(f"consta como rejeitada, mas teve mais SIM ({p[SIM]}) que NÃO ({p[NAO]})")

    # 2. contagem voto a voto x totais oficiais (Senado)
    for chave, oficial in (v.totais_oficiais or {}).items():
        contado = p.get(chave, 0)
        if abs(contado - oficial) > TOLERANCIA_TOTAIS:
            alertas.append(f"contei {contado} votos {chave.upper()}, mas o total oficial é {oficial}")

    # 3. lista de votos
    ids = Counter(x.id for x in v.votos if x.id)
    repetidos = [i for i, n in ids.items() if n > 1]
    if repetidos:
        alertas.append(f"{len(repetidos)} parlamentar(es) aparece(m) mais de uma vez na lista de votos")
    sem_partido = sum(1 for x in v.votos if not x.partido)
    if v.votos and sem_partido / len(v.votos) > 0.05:
        alertas.append(f"{sem_partido} votos sem partido informado")
    limite = 513 if v.casa == "camara" else 81
    if len(v.votos) > limite:
        alertas.append(f"{len(v.votos)} votos registrados, mais que os {limite} parlamentares da Casa")

    # 4. textos
    if v.apelido:
        origem = "registrado pelo Senado" if v.fonte_apelido == "Senado" else "do apelidos.yaml"
        alertas.append(f"o título usa o apelido “{v.apelido}” ({origem}): confira se o nome é neutro")
        if any(p in _sem_acento(v.apelido) for p in PROIBIDOS):
            alertas.append("o apelido tem palavra da lista de termos opinativos: troque no apelidos.yaml")
    if not v.ementa:
        alertas.append("sem ementa oficial: o título veio da descrição da votação")
    if not v.url_fonte:
        alertas.append("sem link da fonte oficial na legenda")
    return alertas


def checar_textos(textos: dict) -> list[str]:
    """Texto que não veio da ementa oficial (agente ou IA) sempre passa por você antes de publicar."""
    alertas: list[str] = []
    if textos.get("fonte_texto") == "explicacoes.yaml":
        alertas.append("a explicação foi escrita por um agente (explicacoes.yaml): confira se está correta e neutra")
    elif textos.get("fonte_texto") == "ia":
        alertas.append("a explicação foi escrita pela IA: confira se está correta e neutra")
    escrito = _sem_acento(f"{textos.get('titulo', '')} {textos.get('resumo', '')}")
    achado = next((p for p in PROIBIDOS if p in escrito), None)
    if achado:
        alertas.append(f"a explicação tem termo opinativo (\"{achado}\"): reescreva antes de aprovar")
    return alertas
