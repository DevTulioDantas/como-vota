"""Coleta as métricas dos posts publicados no Instagram e calcula uma pontuação.

A pontuação mede o quanto o post foi SALVO e COMPARTILHADO em relação a quantas
pessoas ele alcançou. É o que indica conteúdo útil, que vale repostar, e não
depende do tamanho do perfil no dia:

    pontuação = (3 × salvamentos + 3 × compartilhamentos + comentários + 0,5 × curtidas)
                ÷ alcance × 1000

Usada em dois lugares:
  - bot/formatos.py: formatos com pontuação média maior aparecem mais;
  - bot/frias.py: escolhe quais explicadores voltam a ser publicados (repost).

As métricas são atualizadas enquanto o post tem entre 2 e 30 dias.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from bot import publisher, storage

log = logging.getLogger(__name__)

IDADE_MIN = timedelta(days=2)
IDADE_MAX = timedelta(days=30)


def pontuar(m: dict) -> float | None:
    alcance = m.get("reach") or 0
    if alcance <= 0:
        return None
    pesos = 3 * m.get("saved", 0) + 3 * m.get("shares", 0) + m.get("comments", 0) + 0.5 * m.get("likes", 0)
    return round(pesos / alcance * 1000, 1)


def publicado_em(meta: dict) -> datetime | None:
    for h in reversed(meta.get("historico") or []):
        if h.get("status") == "publicado" and h.get("em"):
            try:
                return datetime.fromisoformat(h["em"])
            except ValueError:
                return None
    return None


def todas_as_metas() -> list[dict]:
    saida = []
    if not storage.PASTA_RASCUNHOS.exists():
        return saida
    for arq in sorted(storage.PASTA_RASCUNHOS.glob("*/meta.json")):
        try:
            saida.append(json.loads(arq.read_text(encoding="utf-8")))
        except (ValueError, OSError):
            continue
    return saida


def coletar(agora: datetime | None = None, obter=None) -> int:
    """Atualiza meta['metricas'] dos posts publicados há 2–30 dias. Retorna quantos foram medidos."""
    agora = agora or datetime.now(timezone.utc)
    obter = obter or publisher.insights
    medidos = 0
    for meta in todas_as_metas():
        ig = meta.get("instagram_id")
        quando = publicado_em(meta)
        if meta.get("status") != "publicado" or not ig or ig == "dry-run" or not quando:
            continue
        if not (IDADE_MIN <= agora - quando <= IDADE_MAX):
            continue
        try:
            m = obter(ig)
        except Exception as e:
            log.warning("Sem métricas para %s: %s", meta["id"], e)
            continue
        m["pontuacao"] = pontuar(m)
        m["coletado_em"] = agora.isoformat(timespec="seconds")
        meta["metricas"] = m
        storage.salvar_meta(meta["id"], meta)
        medidos += 1
        log.info("%s: alcance %s, salvos %s, compart. %s → pontuação %s",
                 meta["id"], m.get("reach"), m.get("saved"), m.get("shares"), m["pontuacao"])
    return medidos
