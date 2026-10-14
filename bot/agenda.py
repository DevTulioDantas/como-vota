"""Fila de publicação em horários fixos.

Quando você aprova um post no Telegram, ele não sai na hora: vai para o
próximo horário livre de HORARIOS_PUBLICACAO (horário de Brasília), um post
por horário. O verificador roda a cada 15 minutos e publica os que venceram,
no máximo um por rodada (espaça os posts se vários vencerem juntos).

  HORARIOS_PUBLICACAO=11:45,18:45   padrão: sai perto do almoço e das 19h
                                    (o GitHub atrasa alguns minutos)
  HORARIOS_PUBLICACAO=imediato      volta ao comportamento antigo

O botão "⚡ Agora" (ou /agora <id>) publica na próxima verificação, sem fila.
"""
from __future__ import annotations

import os
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

FUSO = ZoneInfo("America/Sao_Paulo")
PADRAO = "11:45,18:45"
INTERVALO_MINIMO = timedelta(minutes=30)
DIAS_SEMANA = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]


def horarios() -> list[time]:
    """Horários configurados; lista vazia = publicar imediatamente."""
    bruto = (os.getenv("HORARIOS_PUBLICACAO") or PADRAO).strip().lower()
    if bruto in ("imediato", "agora", "0"):
        return []
    saida = []
    for parte in bruto.replace(";", ",").split(","):
        parte = parte.strip()
        if not parte:
            continue
        h, _, m = parte.partition(":")
        saida.append(time(int(h), int(m or 0)))
    return sorted(set(saida))


def proximo_horario(ocupados: list[datetime], agora: datetime | None = None) -> datetime | None:
    """Próximo horário livre depois de agora (None = publicar já)."""
    hs = horarios()
    if not hs:
        return None
    agora = agora or datetime.now(timezone.utc)
    hoje = agora.astimezone(FUSO).date()
    for d in range(60):
        dia = hoje + timedelta(days=d)
        for h in hs:
            slot = datetime.combine(dia, h, tzinfo=FUSO)
            if slot <= agora:
                continue
            if any(abs(o - slot) < INTERVALO_MINIMO for o in ocupados):
                continue
            return slot
    return None


def descrever(slot: datetime, agora: datetime | None = None) -> str:
    agora = (agora or datetime.now(timezone.utc)).astimezone(FUSO)
    local = slot.astimezone(FUSO)
    dias = (local.date() - agora.date()).days
    hora = local.strftime("%H:%M")
    if dias == 0:
        return f"hoje às {hora}"
    if dias == 1:
        return f"amanhã às {hora}"
    return f"{DIAS_SEMANA[local.weekday()]} {local:%d/%m} às {hora}"


def ocupados(metas: list[dict]) -> list[datetime]:
    return [datetime.fromisoformat(m["agendado_para"]) for m in metas
            if m.get("status") == "agendado" and m.get("agendado_para")]


def vencidos(metas: list[dict], agora: datetime | None = None) -> list[str]:
    """Ids agendados cujo horário já chegou, do mais antigo para o mais novo."""
    agora = agora or datetime.now(timezone.utc)
    prontos = [(datetime.fromisoformat(m["agendado_para"]), m["id"]) for m in metas
               if m.get("status") == "agendado" and m.get("agendado_para")
               and datetime.fromisoformat(m["agendado_para"]) <= agora]
    return [rid for _, rid in sorted(prontos)]
