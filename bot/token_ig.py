"""Mantém o token do Instagram vivo e avisa se ele parar de funcionar.

  Login pelo Instagram (IG_GRAPH_BASE = graph.instagram.com)
    O token de longa duração vale 60 dias e pode ser renovado por mais 60 a
    qualquer momento depois de 24 h de uso. O bot renova uma vez por semana e
    grava o novo em IG_ACCESS_TOKEN_SAIDA; o workflow atualiza o secret com o
    GH_PAT (o mesmo usado pelo TikTok).
  Login pelo Facebook (IG_GRAPH_BASE = graph.facebook.com)
    Token de Página gerado a partir de um token de usuário de longa duração não
    expira; o bot só confere se continua válido.

Em qualquer caso, se a conferência falhar, chega um alerta no Telegram antes
de um post falhar na hora de publicar.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from bot import publisher

log = logging.getLogger(__name__)

RENOVAR_A_CADA = timedelta(days=7)
_http = requests


def login_instagram() -> bool:
    base = os.getenv("IG_GRAPH_BASE") or "https://graph.facebook.com/v23.0"
    return "graph.instagram.com" in base


def conferir() -> dict:
    """Confere se o token funciona. Retorna dados da conta (usuário e seguidores)."""
    base, ig, _ = publisher._cfg()
    return publisher._chamar("GET", f"{base}/{ig}", fields="username,followers_count,media_count")


def renovar() -> datetime:
    """Renova o token (só login pelo Instagram). Retorna quando o novo expira."""
    r = _http.get("https://graph.instagram.com/refresh_access_token", timeout=30, params={
        "grant_type": "ig_refresh_token", "access_token": os.environ["IG_ACCESS_TOKEN"],
    })
    corpo = r.json()
    if r.status_code >= 400 or "access_token" not in corpo:
        raise publisher.ErroPublicacao(f"Renovação do token do Instagram falhou: {corpo.get('error', corpo)}")
    novo = corpo["access_token"]
    if novo != os.environ["IG_ACCESS_TOKEN"]:
        os.environ["IG_ACCESS_TOKEN"] = novo
        saida = os.getenv("IG_ACCESS_TOKEN_SAIDA")
        if saida:
            Path(saida).write_text(novo, encoding="utf-8")
        else:
            log.warning("Token do Instagram renovado, mas IG_ACCESS_TOKEN_SAIDA não está definido: "
                        "atualize o secret IG_ACCESS_TOKEN à mão")
    return datetime.now(timezone.utc) + timedelta(seconds=int(corpo.get("expires_in", 5184000)))


def manter(estado: dict, agora: datetime | None = None) -> tuple[bool, str]:
    """Rotina diária: confere o token e renova se for a hora. Retorna (ok, mensagem)."""
    agora = agora or datetime.now(timezone.utc)
    ig = estado.setdefault("instagram", {})
    try:
        conta = conferir()
    except Exception as e:
        return False, (f"🔑 O token do Instagram não está funcionando ({e}). "
                       "Os posts aprovados vão falhar até você gerar um novo token e atualizar o secret IG_ACCESS_TOKEN.")
    ig["usuario"] = conta.get("username")
    if conta.get("followers_count") is not None:
        ig.setdefault("seguidores", {})[agora.date().isoformat()] = int(conta["followers_count"])
        # guarda só os últimos 120 dias
        for dia in sorted(ig["seguidores"])[:-120]:
            del ig["seguidores"][dia]

    if not login_instagram():
        return True, "token válido (login pelo Facebook)"
    ultima = ig.get("token_renovado_em")
    if ultima and agora - datetime.fromisoformat(ultima) < RENOVAR_A_CADA:
        return True, "token válido"
    try:
        expira = renovar()
    except Exception as e:
        return False, (f"🔑 Não consegui renovar o token do Instagram ({e}). "
                       "Ele vence em até 60 dias desde a última renovação: gere um novo e atualize o secret IG_ACCESS_TOKEN.")
    ig["token_renovado_em"] = agora.isoformat(timespec="seconds")
    ig["token_expira_em"] = expira.isoformat(timespec="seconds")
    return True, f"token renovado, vale até {expira:%d/%m/%Y}"
