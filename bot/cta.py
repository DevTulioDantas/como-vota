"""Chamada para o teste "Quem vota como você?" (o "produto" no meio dos posts).

Fica DESLIGADA até o site estar no ar: basta definir SITE_TESTE_URL
(ex.: https://comovotadeputado.com.br ou https://usuario.github.io/como-vota).
Com ela definida, o slide do teste entra nos carrosséis na posição que o
formato pedir, e a legenda ganha uma linha de chamada.
Para desligar mesmo com o site no ar: CTA_TESTE=0.
"""
from __future__ import annotations

import os
import re

LINHA_LEGENDA = "🧭 Quem vota como você? Faça o teste no link da bio."


def site_url() -> str:
    return (os.getenv("SITE_TESTE_URL") or "").strip()


def ativo() -> bool:
    return bool(site_url()) and os.getenv("CTA_TESTE", "1") != "0"


def dominio() -> str:
    """Endereço para mostrar no slide, sem https:// e sem barra final."""
    if not ativo():
        return ""
    return re.sub(r"^https?://", "", site_url()).rstrip("/")


def adicionar_na_legenda(legenda: str) -> str:
    """Insere a chamada antes da linha de hashtags (ou no fim)."""
    if not ativo() or LINHA_LEGENDA in legenda:
        return legenda
    linhas = legenda.split("\n")
    pos = next((i for i in range(len(linhas) - 1, -1, -1) if linhas[i].lstrip().startswith("#")), None)
    if pos is None:
        return legenda.rstrip() + "\n\n" + LINHA_LEGENDA
    linhas[pos:pos] = [LINHA_LEGENDA, ""]
    return "\n".join(linhas)
