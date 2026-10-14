"""Coletor do Senado Federal (Dados Abertos).

Endpoint: https://legis.senado.leg.br/dadosabertos/votacao?dataInicio=...&dataFim=...
Cada registro já traz a matéria, o resultado e o voto de cada senador.
Votações secretas (ex.: autoridades) não revelam o voto individual: ficam
marcadas como secretas e o seletor as descarta.
"""
from __future__ import annotations

import logging

from bot.collectors.camara import _get  # mesma rotina com retry
from bot.models import Votacao, Voto, normalizar_voto, totais_do_texto

log = logging.getLogger(__name__)

BASE = "https://legis.senado.leg.br/dadosabertos"


def coletar(data_inicio: str, data_fim: str) -> list[Votacao]:
    corpo = _get(f"{BASE}/votacao", {"dataInicio": data_inicio, "dataFim": data_fim})
    registros = corpo if isinstance(corpo, list) else corpo.get("votacoes", []) or []
    log.info("Senado: %d votações entre %s e %s", len(registros), data_inicio, data_fim)

    saida: list[Votacao] = []
    for r in registros:
        secreta = str(r.get("votacaoSecreta", "N")).upper() == "S"
        votos = [
            Voto(
                nome=v.get("nomeParlamentar", ""),
                partido=v.get("siglaPartidoParlamentar", ""),
                uf=v.get("siglaUFParlamentar", ""),
                voto=normalizar_voto(v.get("siglaVotoParlamentar") or v.get("descricaoVotoParlamentar", "")),
                voto_original=v.get("descricaoVotoParlamentar") or v.get("siglaVotoParlamentar", ""),
                id=str(v.get("codigoParlamentar", "")),
            )
            for v in (r.get("votos") or [])
        ]
        sigla = r.get("sigla", "")
        resultado = str(r.get("resultadoVotacao", "")).upper()
        cod = r.get("codigoMateria")
        saida.append(Votacao(
            id=f"senado-{r.get('codigoSessaoVotacao') or r.get('codigoVotacaoSve')}",
            casa="senado",
            data=str(r.get("dataSessao", ""))[:10],
            proposicao=r.get("identificacao") or f"{sigla} {r.get('numero', '')}/{r.get('ano', '')}",
            tipo_proposicao=sigla,
            ementa=(r.get("ementa") or "").strip(),
            descricao=(r.get("descricaoVotacao") or "").strip(),
            aprovada=True if resultado == "A" else False if resultado == "R" else None,
            url_fonte=(
                f"https://www25.senado.leg.br/web/atividade/materias/-/materia/{cod}" if cod else ""
            ),
            votos=votos,
            secreta=secreta,
            totais_oficiais=_totais(r),
        ))
    return saida


def _totais(r: dict) -> dict[str, int]:
    """Os campos totalVotos* costumam vir nulos; aí o placar sai do texto do informe."""
    totais = {k: int(r[c]) for k, c in (("Sim", "totalVotosSim"), ("Não", "totalVotosNao"),
                                         ("Abstenção", "totalVotosAbstencao"))
              if str(r.get(c, "")).strip().isdigit()}
    return totais or totais_do_texto((r.get("informeLegislativo") or {}).get("texto") or "")


def coletar_por_id(vid: str, data: str) -> Votacao | None:
    """Uma votação específica do Senado. A API lista por período, então a curadoria
    informa a data da sessão (AAAA-MM-DD) e o id é procurado nesse dia."""
    alvo = vid if vid.startswith("senado-") else f"senado-{vid}"
    for v in coletar(data, data):
        if v.id == alvo:
            return None if v.secreta else v
    return None
