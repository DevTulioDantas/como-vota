"""Textos do slide "O que está em votação": o que é o tipo de projeto e o que
foi decidido naquela votação específica (texto-base, substitutivo, destaque...).

São textos fixos e factuais, escritos uma vez e revisados: nada aqui depende
de IA, e nada opina sobre o mérito. A ementa (ou o resumo da IA) entra junto.
"""
from __future__ import annotations

from bot.models import Votacao, _sem_acento

TIPOS = {
    "PEC": "Proposta de Emenda à Constituição: muda a Constituição, a lei mais importante do país. "
           "Precisa do SIM de 3 em cada 5 deputados e senadores, em duas votações na Câmara e duas no Senado.",
    "PLP": "Projeto de Lei Complementar: uma lei sobre temas que a Constituição pede que sejam decididos "
           "com mais apoio. Precisa do SIM de mais da metade de todos os deputados ou senadores.",
    "PL": "Projeto de Lei: cria uma lei nova ou muda uma lei que já existe.",
    "MPV": "Medida Provisória: regra criada pelo presidente da República. Ela já vale assim que sai, "
           "por até 120 dias. Para continuar valendo, deputados e senadores precisam aprovar.",
    "PLV": "Projeto de Lei de Conversão: é a Medida Provisória com as mudanças feitas por deputados e senadores.",
    "PDL": "Projeto de Decreto Legislativo: decisão que só o Congresso pode tomar, como aprovar acordos "
           "com outros países ou cancelar uma decisão do governo.",
    "PRC": "Projeto de Resolução da Câmara: muda as regras de funcionamento da própria Câmara.",
    "PRS": "Projeto de Resolução do Senado: decisão que só o Senado toma, como regras internas e limites "
           "para as dívidas de estados e cidades.",
}

# (trecho procurado na descrição oficial, explicação, o resultado vale só para esta etapa?)
# A ordem importa: "Aprovado o texto-base do Substitutivo" é texto-base.
# {relator}: "o deputado" / "o senador" encarregado de analisar o projeto; {na_casa}: "na Câmara" / "no Senado"
_ETAPAS = (
    ("texto-base", "votaram o texto principal do projeto. Depois, partes dele ainda podem ser votadas separadamente.", False),
    ("texto base", "votaram o texto principal do projeto. Depois, partes dele ainda podem ser votadas separadamente.", False),
    ("subemenda substitutiva", "votaram uma nova versão do texto, escrita pelo relator ({relator} encarregado de analisar o projeto).", True),
    ("substitutivo", "votaram uma nova versão do texto, escrita pelo relator ({relator} encarregado de analisar o projeto).", True),
    ("destaque", "votaram um trecho do projeto separado do resto. Isso se chama destaque.", True),
    ("emenda aglutinativa", "votaram uma proposta de mudança que junta várias sugestões para o texto.", True),
    ("redacao final", "votaram a versão final do texto, já com todas as mudanças decididas.", False),
    ("primeiro turno", "fizeram a primeira votação da PEC. Ela ainda precisa ser votada mais uma vez {na_casa}.", False),
    ("segundo turno", "fizeram a segunda e última votação da PEC {na_casa}.", False),
)

# o que o carimbo da capa diz quando o resultado vale só para uma parte do projeto
_CARIMBOS = (
    ("subemenda substitutiva", "Substitutivo", "o"),
    ("substitutivo", "Substitutivo", "o"),
    ("destaque", "Destaque", "o"),
    ("emenda aglutinativa", "Emenda", "a"),
)


def carimbo(v: Votacao) -> str:
    """"SUBSTITUTIVO REJEITADO" em vez de "REJEITADA", que daria a entender que o projeto inteiro caiu.
    Vazio quando a votação decide o projeto (ou o texto-base) e o carimbo normal serve."""
    if v.aprovada is None or not explicar_etapa(v)[1]:
        return ""
    desc = _sem_acento(v.descricao)
    for trecho, nome, genero in _CARIMBOS:
        if trecho in desc:
            return f"{nome} {'aprovad' if v.aprovada else 'rejeitad'}{genero}".upper()
    return ""


# (trecho do andamento oficial, explicação simples). A ordem importa: "à sanção" antes de "à Câmara".
_PASSOS = (
    ("promulga", "A mudança vai ser oficializada pelo Congresso e passa a valer depois de publicada."),
    ("sanção", "O projeto vai para o presidente da República, que pode aprovar (sancionar) ou barrar (vetar)."),
    ("sancao", "O projeto vai para o presidente da República, que pode aprovar (sancionar) ou barrar (vetar)."),
    ("câmara", "O projeto segue para a Câmara dos Deputados, que ainda precisa votar."),
    ("camara", "O projeto segue para a Câmara dos Deputados, que ainda precisa votar."),
    ("senado", "O projeto segue para o Senado, que ainda precisa votar."),
    ("arquiv", "O projeto foi arquivado."),
)


def proximo_passo(v: Votacao) -> str:
    """O que acontece agora, quando a Casa informa (por enquanto, o informe do Senado)."""
    andamento = (v.andamento or "").lower()
    return next((texto for trecho, texto in _PASSOS if trecho in andamento), "")


def explicar_tipo(v: Votacao) -> str:
    return TIPOS.get(v.tipo_proposicao, "")


def explicar_etapa(v: Votacao) -> tuple[str, bool]:
    """(frase sobre o que foi decidido, se o resultado vale só para essa parte do projeto)."""
    desc = _sem_acento(v.descricao)
    quem = "os deputados" if v.casa == "camara" else "os senadores"
    relator = "o deputado" if v.casa == "camara" else "o senador"
    na_casa = "na Câmara" if v.casa == "camara" else "no Senado"
    for trecho, explicacao, so_etapa in _ETAPAS:
        if trecho in desc:
            return f"Nesta votação, {quem} {explicacao.format(relator=relator, na_casa=na_casa)}", so_etapa
    return "", False
