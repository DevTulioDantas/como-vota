"""Textos do slide "O que está em votação": o que é o tipo de projeto e o que
foi decidido naquela votação específica (texto-base, substitutivo, destaque...).

São textos fixos e factuais, escritos uma vez e revisados: nada aqui depende
de IA, e nada opina sobre o mérito. A ementa (ou o resumo da IA) entra junto.
"""
from __future__ import annotations

from bot.models import Votacao, _sem_acento

TIPOS = {
    "PEC": "Proposta de Emenda à Constituição: muda o texto da Constituição. "
           "É votada em dois turnos na Câmara e no Senado.",
    "PLP": "Projeto de Lei Complementar: regulamenta temas que a Constituição manda tratar "
           "por lei complementar. Precisa da maioria absoluta da Casa.",
    "PL": "Projeto de Lei: cria ou muda uma lei comum.",
    "MPV": "Medida Provisória: norma editada pelo presidente da República. Já vale por até "
           "120 dias, mas só continua valendo se o Congresso aprovar.",
    "PLV": "Projeto de Lei de Conversão: é a Medida Provisória com as mudanças feitas "
           "pelo Congresso.",
    "PDL": "Projeto de Decreto Legislativo: trata de assuntos que só o Congresso decide, "
           "como aprovar acordos internacionais ou sustar atos do governo.",
    "PRC": "Projeto de Resolução da Câmara: muda regras internas da Câmara.",
    "PRS": "Projeto de Resolução do Senado: trata de temas que só o Senado decide, "
           "como regras internas e limites de dívida de estados e municípios.",
}

# (trecho procurado na descrição oficial, explicação, o resultado vale só para esta etapa?)
# A ordem importa: "Aprovado o texto-base do Substitutivo" é texto-base.
_ETAPAS = (
    ("texto-base", "decidiram o texto principal (texto-base). Trechos ainda podem ser votados à parte, nos destaques.", False),
    ("texto base", "decidiram o texto principal (texto-base). Trechos ainda podem ser votados à parte, nos destaques.", False),
    ("subemenda substitutiva", "decidiram sobre o substitutivo: a versão do texto proposta pelo relator.", True),
    ("substitutivo", "decidiram sobre o substitutivo: a versão do texto proposta pelo relator.", True),
    ("destaque", "decidiram um destaque: um trecho votado separadamente do texto principal.", True),
    ("emenda aglutinativa", "decidiram uma emenda aglutinativa: uma versão que junta propostas de mudança no texto.", True),
    ("redacao final", "votaram a redação final: a versão definitiva do texto, com as mudanças já decididas.", False),
    ("primeiro turno", "votaram em primeiro turno. A PEC ainda precisa passar por um segundo turno nesta Casa.", False),
    ("segundo turno", "votaram em segundo turno, a última votação da PEC nesta Casa.", False),
)


def explicar_tipo(v: Votacao) -> str:
    return TIPOS.get(v.tipo_proposicao, "")


def explicar_etapa(v: Votacao) -> tuple[str, bool]:
    """(frase sobre o que foi decidido, se o resultado vale só para essa parte do projeto)."""
    desc = _sem_acento(v.descricao)
    quem = "os deputados" if v.casa == "camara" else "os senadores"
    for trecho, explicacao, so_etapa in _ETAPAS:
        if trecho in desc:
            return f"Nesta votação, {quem} {explicacao}", so_etapa
    return "", False
