"""Coletor da Câmara dos Deputados (API Dados Abertos v2).

Docs: https://dadosabertos.camara.leg.br/swagger/api.html
Só votações NOMINAIS do Plenário têm voto individual; as simbólicas vêm com
a lista de votos vazia e são descartadas aqui.
"""
from __future__ import annotations

import logging
import time

import requests

from bot.models import Votacao, Voto, normalizar_voto, totais_do_texto

log = logging.getLogger(__name__)

BASE = "https://dadosabertos.camara.leg.br/api/v2"
ID_PLENARIO = 180
TIPOS_PRINCIPAIS = ("PEC", "PLP", "MPV", "PL", "PLV", "PDL", "PRC")

_sessao = requests.Session()
_sessao.headers.update({"Accept": "application/json", "User-Agent": "como-vota-bot/1.0"})


def _get(url: str, params: dict | None = None, tentativas: int = 4) -> dict:
    for i in range(tentativas):
        try:
            r = _sessao.get(url, params=params, timeout=30)
            if r.status_code == 429 or r.status_code >= 500:
                raise requests.HTTPError(f"HTTP {r.status_code}")
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError) as e:
            if i == tentativas - 1:
                raise
            espera = 2 ** i
            log.warning("Falha em %s (%s), nova tentativa em %ss", url, e, espera)
            time.sleep(espera)
    return {}


def _paginar(url: str, params: dict) -> list[dict]:
    itens, proxima = [], url
    while proxima:
        corpo = _get(proxima, params)
        itens.extend(corpo.get("dados", []))
        proxima = next((l["href"] for l in corpo.get("links", []) if l.get("rel") == "next"), None)
        params = None  # o link "next" já traz os parâmetros
    return itens


def _proposicao_principal(detalhe: dict) -> dict | None:
    afetadas = detalhe.get("proposicoesAfetadas") or []
    for tipo in TIPOS_PRINCIPAIS:
        for p in afetadas:
            if p.get("siglaTipo") == tipo:
                return p
    return afetadas[0] if afetadas else None


def coletar(data_inicio: str, data_fim: str) -> list[Votacao]:
    """Retorna as votações nominais do Plenário no período (datas AAAA-MM-DD)."""
    lista = _paginar(f"{BASE}/votacoes", {
        "idOrgao": ID_PLENARIO,
        "dataInicio": data_inicio,
        "dataFim": data_fim,
        "itens": 200,
        "ordem": "ASC",
        "ordenarPor": "dataHoraRegistro",
    })
    log.info("Câmara: %d votações no plenário entre %s e %s", len(lista), data_inicio, data_fim)

    saida: list[Votacao] = []
    for item in lista:
        v = _montar(item["id"], item)
        if v:
            saida.append(v)
    log.info("Câmara: %d votações nominais", len(saida))
    return saida


def coletar_por_id(vid: str) -> Votacao | None:
    """Uma votação específica pelo id da API (ex.: "2611313-34" ou "camara-2611313-34")."""
    vid = vid.removeprefix("camara-")
    return _montar(vid, None)


def _montar(vid: str, item: dict | None) -> Votacao | None:
    votos_raw = _get(f"{BASE}/votacoes/{vid}/votos").get("dados", [])
    if not votos_raw:
        return None  # votação simbólica: não há voto individual

    detalhe = _get(f"{BASE}/votacoes/{vid}").get("dados", {}) or {}
    item = item or detalhe
    prop = _proposicao_principal(detalhe) or {}
    orient_raw = _get(f"{BASE}/votacoes/{vid}/orientacoes").get("dados", [])

    orientacoes, governo = {}, None
    for o in orient_raw:
        sigla = (o.get("siglaPartidoBloco") or "").strip()
        ori = (o.get("orientacaoVoto") or "").strip()
        if not sigla:
            continue
        if sigla.lower().startswith("gov"):
            governo = ori
        else:
            orientacoes[sigla] = ori

    votos = []
    for v in votos_raw:
        dep = v.get("deputado_") or {}
        votos.append(Voto(
            nome=dep.get("nome", ""),
            partido=dep.get("siglaPartido", ""),
            uf=dep.get("siglaUf", ""),
            voto=normalizar_voto(v.get("tipoVoto", "")),
            voto_original=v.get("tipoVoto", ""),
            id=str(dep.get("id", "")),
        ))

    tipo = prop.get("siglaTipo", "")
    nome_prop = f"{tipo} {prop.get('numero', '')}/{prop.get('ano', '')}".strip() if tipo else ""
    aprov = item.get("aprovacao")
    descricao = (item.get("descricao") or detalhe.get("descricao") or "").strip()
    return Votacao(
        id=f"camara-{vid}",
        casa="camara",
        data=item.get("data", "") or str(detalhe.get("dataHoraRegistro", ""))[:10],
        proposicao=nome_prop,
        tipo_proposicao=tipo,
        ementa=(prop.get("ementa") or "").strip(),
        descricao=descricao,
        aprovada=None if aprov is None else bool(aprov),
        url_fonte=(
            f"https://www.camara.leg.br/propostas-legislativas/{prop['id']}"
            if prop.get("id") else item.get("uri", "")
        ),
        votos=votos,
        orientacoes=orientacoes,
        orientacao_governo=governo,
        totais_oficiais=totais_do_texto(descricao),
    )
