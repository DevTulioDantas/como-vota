"""Publicação de carrossel no Instagram via Graph API (Content Publishing).

Fluxo oficial:
  1. POST /{ig-user-id}/media  image_url=..., is_carousel_item=true   (1 por imagem)
  2. POST /{ig-user-id}/media  media_type=CAROUSEL, children=..., caption=...
  3. espera o container ficar FINISHED
  4. POST /{ig-user-id}/media_publish  creation_id=...

Requisitos:
  - conta Profissional (Business ou Creator) no Instagram;
  - token com permissão de publicação (instagram_content_publish ou
    instagram_business_content_publish, conforme o tipo de login do app);
  - as imagens precisam estar numa URL pública (JPEG). A Meta baixa de lá.

IG_GRAPH_BASE:
  - "Instagram API com login do Facebook"  -> https://graph.facebook.com/v23.0
  - "Instagram API com login do Instagram" -> https://graph.instagram.com/v23.0
"""
from __future__ import annotations

import logging
import os
import time

import requests

log = logging.getLogger(__name__)


class ErroPublicacao(RuntimeError):
    pass


def _cfg() -> tuple[str, str, str]:
    base = (os.getenv("IG_GRAPH_BASE") or "https://graph.facebook.com/v23.0").rstrip("/")
    return base, os.environ["IG_USER_ID"], os.environ["IG_ACCESS_TOKEN"]


def _chamar(metodo: str, url: str, **params) -> dict:
    _, _, token = _cfg()
    params["access_token"] = token
    r = requests.request(metodo, url, params=params if metodo == "GET" else None,
                         data=params if metodo == "POST" else None, timeout=60)
    corpo = r.json()
    if r.status_code >= 400 or "error" in corpo:
        raise ErroPublicacao(f"{url}: {corpo.get('error', corpo)}")
    return corpo


def _esperar(container_id: str, limite_s: int = 180) -> None:
    base, _, _ = _cfg()
    inicio = time.time()
    while time.time() - inicio < limite_s:
        status = _chamar("GET", f"{base}/{container_id}", fields="status_code").get("status_code")
        if status == "FINISHED":
            return
        if status in ("ERROR", "EXPIRED"):
            raise ErroPublicacao(f"Container {container_id} terminou com status {status}")
        time.sleep(5)
    raise ErroPublicacao(f"Container {container_id} não ficou pronto em {limite_s}s")


def publicar(urls_imagens: list[str], legenda: str) -> dict:
    """Escolhe o formato pelo número de imagens: 1 = post único, 2–10 = carrossel."""
    if len(urls_imagens) == 1:
        return publicar_imagem(urls_imagens[0], legenda)
    return publicar_carrossel(urls_imagens, legenda)


def publicar_imagem(url_imagem: str, legenda: str) -> dict:
    """Post de imagem única (ex.: Voto da Semana)."""
    if os.getenv("DRY_RUN") == "1":
        log.info("[DRY_RUN] publicaria imagem única: %s", url_imagem)
        return {"id": "dry-run", "permalink": ""}
    base, ig, _ = _cfg()
    container = _chamar("POST", f"{base}/{ig}/media", image_url=url_imagem, caption=legenda)
    _esperar(container["id"])
    publicado = _chamar("POST", f"{base}/{ig}/media_publish", creation_id=container["id"])
    try:
        link = _chamar("GET", f"{base}/{publicado['id']}", fields="permalink").get("permalink", "")
    except ErroPublicacao:
        link = ""
    return {"id": publicado["id"], "permalink": link}


def publicar_carrossel(urls_imagens: list[str], legenda: str) -> dict:
    """Publica e retorna {'id': ..., 'permalink': ...}. Aceita 2 a 10 imagens."""
    if os.getenv("DRY_RUN") == "1":
        log.info("[DRY_RUN] publicaria %d imagens:\n%s", len(urls_imagens), "\n".join(urls_imagens))
        return {"id": "dry-run", "permalink": ""}
    if not 2 <= len(urls_imagens) <= 10:
        raise ErroPublicacao("Carrossel precisa de 2 a 10 imagens")

    base, ig, _ = _cfg()
    filhos = []
    for url in urls_imagens:
        c = _chamar("POST", f"{base}/{ig}/media", image_url=url, is_carousel_item="true")
        filhos.append(c["id"])
    for f in filhos:
        _esperar(f)

    carrossel = _chamar("POST", f"{base}/{ig}/media",
                        media_type="CAROUSEL", children=",".join(filhos), caption=legenda)
    _esperar(carrossel["id"])

    publicado = _chamar("POST", f"{base}/{ig}/media_publish", creation_id=carrossel["id"])
    try:
        link = _chamar("GET", f"{base}/{publicado['id']}", fields="permalink").get("permalink", "")
    except ErroPublicacao:
        link = ""
    return {"id": publicado["id"], "permalink": link}


# ------------------------------------------------------------------ métricas

# Do conjunto mais completo ao mais simples: se a API recusar uma métrica
# (os nomes mudam entre versões), tenta o próximo conjunto.
CONJUNTOS_METRICAS = ("reach,saved,shares,total_interactions", "reach,saved,shares", "reach,saved")


def insights(media_id: str) -> dict:
    """Métricas de um post: alcance, salvamentos, compartilhamentos, curtidas e comentários."""
    base, _, _ = _cfg()
    campos = _chamar("GET", f"{base}/{media_id}", fields="like_count,comments_count")
    saida = {"likes": int(campos.get("like_count") or 0), "comments": int(campos.get("comments_count") or 0)}
    ultimo_erro = None
    for conjunto in CONJUNTOS_METRICAS:
        try:
            corpo = _chamar("GET", f"{base}/{media_id}/insights", metric=conjunto)
        except ErroPublicacao as e:
            ultimo_erro = e
            continue
        for item in corpo.get("data", []):
            valor = (item.get("total_value") or {}).get("value")
            if valor is None:
                valor = ((item.get("values") or [{}])[0]).get("value", 0)
            saida[item.get("name")] = int(valor or 0)
        return saida
    raise ultimo_erro or ErroPublicacao(f"Sem métricas para {media_id}")
