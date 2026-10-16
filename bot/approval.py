"""Aprovação humana pelo Telegram, sem servidor.

1. `enviar_para_aprovacao` manda o carrossel + legenda para o seu chat, com
   botões [✅ Publicar] [🗑️ Descartar].
2. `ler_decisoes` roda de tempos em tempos (cron), lê os cliques via
   getUpdates e devolve o que foi aprovado/descartado.

Também aceita comandos por texto: /aprovar <id>  e  /descartar <id>.
Só obedece ao TELEGRAM_CHAT_ID configurado.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import requests

from bot import storage

log = logging.getLogger(__name__)


def _api(metodo: str) -> str:
    return f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/{metodo}"


def _chat_id() -> str:
    return str(os.environ["TELEGRAM_CHAT_ID"])


def _post(metodo: str, **kwargs) -> dict:
    r = requests.post(_api(metodo), timeout=60, **kwargs)
    corpo = r.json()
    if not corpo.get("ok"):
        raise RuntimeError(f"Telegram {metodo}: {corpo}")
    return corpo["result"]


def enviar_para_aprovacao(rascunho_id: str, imagens: list[Path], legenda: str) -> None:
    enviadas = []
    # 1) imagens: álbum para carrossel (2 a 10), foto simples para post único
    if len(imagens) == 1:
        img = imagens[0]
        enviadas.append(_post("sendPhoto", data={"chat_id": _chat_id()},
                              files={"photo": (img.name, img.read_bytes(), "image/jpeg")}))
    else:
        arquivos, midia = {}, []
        for i, img in enumerate(imagens[:10]):
            chave = f"img{i}"
            arquivos[chave] = (img.name, img.read_bytes(), "image/jpeg")
            midia.append({"type": "photo", "media": f"attach://{chave}"})
        enviadas += _post("sendMediaGroup", data={"chat_id": _chat_id(), "media": json.dumps(midia)}, files=arquivos)

    # 2) legenda + botões
    texto = f"📝 Rascunho {rascunho_id}\n\n{legenda}"
    if len(texto) > 4000:
        texto = texto[:3990] + "…"
    enviadas.append(_post("sendMessage", json={
        "chat_id": _chat_id(),
        "text": texto,
        "disable_web_page_preview": True,
        "reply_markup": {"inline_keyboard": [[
            {"text": "✅ Aprovar", "callback_data": f"aprovar:{rascunho_id}"[:64]},
            {"text": "⚡ Agora", "callback_data": f"agora:{rascunho_id}"[:64]},
            {"text": "🗑️ Descartar", "callback_data": f"descartar:{rascunho_id}"[:64]},
        ]]},
    }))
    # guarda os números para o "Descartar" poder apagar tudo depois
    storage.registrar_mensagens_telegram(rascunho_id, [m["message_id"] for m in enviadas if "message_id" in m])


def apagar_mensagens(ids: list[int]) -> int:
    """Apaga mensagens do bot no chat. O Telegram só deixa apagar até 48 horas depois do envio;
    as mais antigas (ou já apagadas) ficam como estão. Devolve quantas foram pedidas."""
    ids = sorted(set(ids))
    for i in range(0, len(ids), 100):  # deleteMessages aceita até 100 por vez
        lote = ids[i:i + 100]
        try:
            _post("deleteMessages", json={"chat_id": _chat_id(), "message_ids": lote})
        except Exception as e:
            log.warning("Não consegui apagar as mensagens %s: %s", lote, e)
    return len(ids)


def enviar_pacote_tiktok(rascunho_id: str, imagens: list[Path], legenda: str) -> None:
    """Imagens 9:16 como ARQUIVO (sem compressão do Telegram) + legenda para colar no TikTok."""
    imagens = imagens[:10]
    if len(imagens) == 1:
        img = imagens[0]
        _post("sendDocument", data={"chat_id": _chat_id()},
              files={"document": (img.name, img.read_bytes(), "image/jpeg")})
    else:
        arquivos, midia = {}, []
        for i, img in enumerate(imagens):
            chave = f"doc{i}"
            arquivos[chave] = (f"{rascunho_id}-{img.name}", img.read_bytes(), "image/jpeg")
            midia.append({"type": "document", "media": f"attach://{chave}"})
        _post("sendMediaGroup", data={"chat_id": _chat_id(), "media": json.dumps(midia)}, files=arquivos)
    texto = (f"📱 TikTok · {rascunho_id}\nPoste as imagens acima como carrossel de fotos, nessa ordem, "
             f"com esta legenda:\n\n{legenda}")
    _post("sendMessage", json={"chat_id": _chat_id(), "text": texto[:4000], "disable_web_page_preview": True})


def avisar(texto: str) -> None:
    try:
        _post("sendMessage", json={"chat_id": _chat_id(), "text": texto, "disable_web_page_preview": True})
    except Exception as e:
        log.warning("Não consegui avisar no Telegram: %s", e)


def ler_decisoes(offset: int) -> tuple[list[tuple[str, str]], int]:
    """Retorna ([(acao, rascunho_id[, texto]), ...], novo_offset).
    acao: 'aprovar' (entra na fila) | 'agora' (publica já) | 'descartar' | 'fila' (lista a fila)
          | 'legenda' (mostra ou troca a legenda; o texto novo vem como terceiro item)."""
    r = requests.get(_api("getUpdates"), params={
        "offset": offset, "timeout": 0, "allowed_updates": json.dumps(["message", "callback_query"]),
    }, timeout=60)
    atualizacoes = r.json().get("result", [])
    decisoes, novo_offset = [], offset

    for u in atualizacoes:
        novo_offset = max(novo_offset, u["update_id"] + 1)

        if cb := u.get("callback_query"):
            if str(cb.get("message", {}).get("chat", {}).get("id")) != _chat_id():
                continue
            acao, _, rid = (cb.get("data") or "").partition(":")
            if acao in ("aprovar", "agora", "descartar") and rid:
                decisoes.append((acao, rid))
                try:
                    _post("answerCallbackQuery", json={
                        "callback_query_id": cb["id"],
                        "text": {"aprovar": "Aprovado! Confirmo o horário em instantes.",
                                 "agora": "Publico na próxima verificação.", "descartar": "Descartado."}[acao],
                    })
                except Exception:
                    pass  # o clique pode ter expirado; a decisão vale mesmo assim

        elif msg := u.get("message"):
            if str(msg.get("chat", {}).get("id")) != _chat_id():
                continue
            texto = msg.get("text") or ""
            partes = texto.split()
            if partes and partes[0] == "/legenda" and len(partes) >= 2:
                # "/legenda <id>" sozinho devolve a legenda atual; com texto na linha de baixo, substitui
                _, _, nova = texto.partition("\n")
                decisoes.append(("legenda", partes[1], nova.strip()))
            elif len(partes) == 2 and partes[0] in ("/aprovar", "/agora", "/descartar"):
                decisoes.append((partes[0][1:], partes[1]))
            elif partes and partes[0] in ("/fila", "/agenda"):
                decisoes.append(("fila", ""))

    return decisoes, novo_offset
