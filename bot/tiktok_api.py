"""Publicação no TikTok pela Content Posting API, com app próprio.

Modos (variável TIKTOK_MODO)
  manual    Padrão. Depois da aprovação, o bot manda no Telegram as imagens 9:16
            e a legenda para você postar.
  rascunho  O bot envia o carrossel para a caixa de entrada do TikTok (MEDIA_UPLOAD).
            Chega uma notificação no app; você escolhe a música e publica.
            Exige o escopo video.upload aprovado para o app.
  direto    Publica direto (DIRECT_POST). Atenção: enquanto o app não passar na
            auditoria do TikTok, a API só publica em CONTA PRIVADA e os posts
            ficam privados (SELF_ONLY).

Se o modo automático falhar, o bot cai para o manual e avisa no Telegram, para
nenhum post se perder.

Regras da API que este módulo respeita
  - As imagens são baixadas pelo TikTok a partir de uma URL HTTPS de domínio
    VERIFICADO no portal de desenvolvedores (TIKTOK_MIDIA_URL), sem redirecionamento.
  - JPEG ou WebP, no máximo 1080p e 20 MB por imagem (as nossas têm 1080×1920).
  - Título até 90 caracteres; descrição até 4000.
  - No modo direto, a privacidade precisa estar entre as opções que a conta
    permite (creator_info) — por isso é consultada antes de cada post.
  - O token de acesso dura 24 h; o de renovação dura 365 dias e PODE MUDAR a cada
    renovação. O novo é gravado em TIKTOK_REFRESH_TOKEN_SAIDA para o workflow
    atualizar o secret (ver .github/workflows/verificar.yml).
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path

import requests

from bot import segredos

log = logging.getLogger(__name__)

API = "https://open.tiktokapis.com/v2"
MODOS = {"manual", "rascunho", "direto"}
STATUS_OK = {"SEND_TO_USER_INBOX", "PUBLISH_COMPLETE"}
LIMITE_TITULO = 90
LIMITE_DESCRICAO = 4000

_http = requests          # trocado nos testes
_dormir = time.sleep      # trocado nos testes
_token_cache: dict = {}


class ErroTikTok(RuntimeError):
    pass


class ImagemForaDoAr(ErroTikTok):
    """As imagens ainda não chegaram ao site (deploy em andamento): vale tentar de novo depois."""


# ------------------------------------------------------------ configuração

def modo() -> str:
    m = (os.getenv("TIKTOK_MODO") or "manual").strip().lower()
    return m if m in MODOS else "manual"


def faltando() -> list[str]:
    nomes = ["TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET", "TIKTOK_REFRESH_TOKEN", "TIKTOK_MIDIA_URL"]
    return [n for n in nomes if not os.getenv(n)]


def automatico() -> bool:
    return modo() != "manual" and not faltando()


def urls_midia(rid: str, imagens: list[Path]) -> list[str]:
    base = os.environ["TIKTOK_MIDIA_URL"].rstrip("/")
    return [f"{base}/{rid}/{img.name}" for img in imagens]


# ------------------------------------------------------------ autenticação

def _resposta(r) -> dict:
    try:
        corpo = r.json()
    except ValueError:
        raise ErroTikTok(f"HTTP {r.status_code}: resposta inválida")
    erro = corpo.get("error")
    if isinstance(erro, dict) and erro.get("code") not in (None, "", "ok"):
        raise ErroTikTok(f"{erro.get('code')}: {erro.get('message', '')}".strip())
    if "error" in corpo and isinstance(erro, str) and erro:  # formato do endpoint de token
        raise ErroTikTok(f"{erro}: {corpo.get('error_description', '')}".strip())
    if r.status_code >= 400:
        raise ErroTikTok(f"HTTP {r.status_code}: {corpo}")
    return corpo


def _salvar_refresh(novo: str) -> None:
    """Guarda o refresh token novo (o TikTok pode trocá-lo a cada renovação)."""
    segredos.mascarar(novo)
    os.environ["TIKTOK_REFRESH_TOKEN"] = novo
    saida = os.getenv("TIKTOK_REFRESH_TOKEN_SAIDA")
    if saida:
        Path(saida).write_text(novo, encoding="utf-8")
        log.info("O TikTok trocou o refresh token; o novo foi salvo para atualizar o secret")
    else:
        log.warning("O TikTok trocou o refresh token, mas TIKTOK_REFRESH_TOKEN_SAIDA não está definido: "
                    "atualize o secret TIKTOK_REFRESH_TOKEN à mão ou o próximo login vai falhar")


def token_de_acesso() -> str:
    if _token_cache.get("expira", 0) > time.time() + 60:
        return _token_cache["token"]
    atual = os.environ["TIKTOK_REFRESH_TOKEN"]
    r = _http.post(f"{API}/oauth/token/", timeout=30, data={
        "client_key": os.environ["TIKTOK_CLIENT_KEY"],
        "client_secret": os.environ["TIKTOK_CLIENT_SECRET"],
        "grant_type": "refresh_token",
        "refresh_token": atual,
    }, headers={"Content-Type": "application/x-www-form-urlencoded"})
    corpo = _resposta(r)
    dados = corpo.get("data", corpo)  # o endpoint de token responde sem o envelope "data"
    if not dados.get("access_token"):
        raise ErroTikTok("Renovação do token não devolveu access_token")
    novo = dados.get("refresh_token")
    if novo and novo != atual:
        _salvar_refresh(novo)
    _token_cache.update(token=dados["access_token"], expira=time.time() + int(dados.get("expires_in", 3600)))
    return dados["access_token"]


def trocar_codigo(codigo: str, redirect_uri: str) -> dict:
    """Troca o código do login (OAuth) pelos tokens. Usado uma vez, no `tiktok-login`."""
    r = _http.post(f"{API}/oauth/token/", timeout=30, data={
        "client_key": os.environ["TIKTOK_CLIENT_KEY"],
        "client_secret": os.environ["TIKTOK_CLIENT_SECRET"],
        "code": codigo,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    }, headers={"Content-Type": "application/x-www-form-urlencoded"})
    corpo = _resposta(r)
    return corpo.get("data", corpo)


def url_de_login(redirect_uri: str, estado: str, escopos: str) -> str:
    from urllib.parse import urlencode
    return "https://www.tiktok.com/v2/auth/authorize/?" + urlencode({
        "client_key": os.environ["TIKTOK_CLIENT_KEY"],
        "scope": escopos,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "state": estado,
    })


# ------------------------------------------------------------ chamadas

def _post(caminho: str, corpo: dict) -> dict:
    r = _http.post(f"{API}{caminho}", json=corpo, timeout=60, headers={
        "Authorization": f"Bearer {token_de_acesso()}",
        "Content-Type": "application/json; charset=UTF-8",
    })
    return _resposta(r).get("data", {})


def creator_info() -> dict:
    return _post("/post/publish/creator_info/query/", {})


def checar_urls(urls: list[str]) -> None:
    """As imagens precisam estar no ar, em HTTPS e sem redirecionamento."""
    for url in urls:
        if not url.startswith("https://"):
            raise ErroTikTok(f"URL precisa ser HTTPS: {url}")
        try:
            r = _http.head(url, timeout=20, allow_redirects=False)
        except requests.RequestException as e:
            raise ErroTikTok(f"Imagem inacessível ({url}): {e}")
        if r.status_code != 200:
            raise ImagemForaDoAr(f"Imagem ainda não está no site (HTTP {r.status_code}): {url}. "
                             "O deploy do site ainda não terminou.")


def aguardar(publish_id: str, limite_s: int = 180) -> dict:
    inicio, ultimo = time.time(), {}
    while time.time() - inicio < limite_s:
        ultimo = _post("/post/publish/status/fetch/", {"publish_id": publish_id})
        status = ultimo.get("status")
        if status in STATUS_OK:
            return ultimo
        if status == "FAILED":
            raise ErroTikTok(f"TikTok recusou o post: {ultimo.get('fail_reason', 'sem motivo informado')}")
        _dormir(5)
    return ultimo  # ainda processando: o post costuma terminar sozinho


def _cortar(texto: str, limite: int) -> str:
    # a API conta em unidades UTF-16; emojis contam 2
    saida, total = [], 0
    for c in texto:
        n = 2 if ord(c) > 0xFFFF else 1
        if total + n > limite:
            break
        saida.append(c)
        total += n
    return "".join(saida)


def publicar(urls: list[str], legenda: str) -> dict:
    """Envia o carrossel. Retorna {'publish_id', 'status', 'modo'}."""
    m = modo()
    if m == "manual":
        raise ErroTikTok("TIKTOK_MODO=manual: nada a publicar pela API")
    if not 1 <= len(urls) <= 35:
        raise ErroTikTok("O TikTok aceita de 1 a 35 fotos por post")
    titulo = _cortar(legenda.split("\n", 1)[0].strip(), LIMITE_TITULO)
    descricao = _cortar(legenda.strip(), LIMITE_DESCRICAO)

    if os.getenv("DRY_RUN") == "1":
        log.info("[DRY_RUN] TikTok (%s): %d fotos, título %r", m, len(urls), titulo)
        return {"publish_id": "dry-run", "status": "DRY_RUN", "modo": m}

    checar_urls(urls)
    post_info: dict = {"title": titulo, "description": descricao}
    if m == "direto":
        info = creator_info()
        privacidade = (os.getenv("TIKTOK_PRIVACIDADE") or "SELF_ONLY").strip().upper()
        opcoes = info.get("privacy_level_options") or []
        if privacidade not in opcoes:
            raise ErroTikTok(f"Privacidade {privacidade} não permitida para esta conta. Opções: {opcoes}")
        post_info.update(privacy_level=privacidade, disable_comment=False, auto_add_music=True,
                         brand_content_toggle=False, brand_organic_toggle=False)

    dados = _post("/post/publish/content/init/", {
        "media_type": "PHOTO",
        "post_mode": "DIRECT_POST" if m == "direto" else "MEDIA_UPLOAD",
        "post_info": post_info,
        "source_info": {"source": "PULL_FROM_URL", "photo_images": urls, "photo_cover_index": 0},
    })
    publish_id = dados.get("publish_id")
    if not publish_id:
        raise ErroTikTok(f"Resposta sem publish_id: {dados}")
    final = aguardar(publish_id)
    return {"publish_id": publish_id, "status": final.get("status", "PROCESSANDO"), "modo": m}
