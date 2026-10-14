"""Confere a configuração do bot, integração por integração.

Uso:  python main.py diagnostico            (no seu computador, lê o .env)
      Actions → Diagnóstico → Run workflow  (com os secrets do GitHub)

Cada item sai como ✅ (ok), ⚠️ (funciona, mas falta algo opcional) ou ❌ (vai
quebrar). Nada é publicado: só leituras e chamadas de teste.
"""
from __future__ import annotations

import os
from datetime import date, timedelta

import requests

OK, AVISO, ERRO = "✅", "⚠️", "❌"


def _get(url: str, **kw):
    return requests.get(url, timeout=kw.pop("timeout", 20), **kw)


def _telegram() -> list[tuple]:
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return [(ERRO, "Telegram", "faltam TELEGRAM_BOT_TOKEN e/ou TELEGRAM_CHAT_ID: sem aprovação, nada é publicado")]
    try:
        eu = _get(f"https://api.telegram.org/bot{token}/getMe").json()
        if not eu.get("ok"):
            return [(ERRO, "Telegram", f"token do bot inválido ({eu.get('description')})")]
        conversa = _get(f"https://api.telegram.org/bot{token}/getChat", params={"chat_id": chat}).json()
        if not conversa.get("ok"):
            return [(ERRO, "Telegram", f"bot @{eu['result']['username']} não acha o chat {chat}. Mande uma mensagem para o bot primeiro.")]
        return [(OK, "Telegram", f"bot @{eu['result']['username']} falando com o chat {chat}")]
    except requests.RequestException as e:
        return [(ERRO, "Telegram", f"sem conexão: {e}")]


def _instagram() -> list[tuple]:
    from bot import publisher, token_ig
    faltam = [n for n in ("IG_USER_ID", "IG_ACCESS_TOKEN", "PUBLIC_BASE_URL") if not os.getenv(n)]
    if faltam:
        return [(ERRO, "Instagram", "faltam " + ", ".join(faltam))]
    itens = []
    try:
        conta = token_ig.conferir()
        itens.append((OK, "Instagram", f"conta @{conta.get('username')} · {conta.get('followers_count', '?')} seguidores"))
    except Exception as e:
        return [(ERRO, "Instagram", f"token ou ID inválido: {e}")]
    try:
        base, ig, _ = publisher._cfg()
        cota = publisher._chamar("GET", f"{base}/{ig}/content_publishing_limit", fields="quota_usage,config")
        dados = (cota.get("data") or [{}])[0]
        limite = (dados.get("config") or {}).get("quota_total", "?")
        itens.append((OK, "Instagram · cota", f"{dados.get('quota_usage', 0)} de {limite} posts nas últimas 24 h"))
    except Exception as e:
        itens.append((AVISO, "Instagram · cota", f"não consegui ler a cota de publicação ({e})"))
    if not os.getenv("PUBLIC_BASE_URL", "").startswith("https://"):
        itens.append((ERRO, "Instagram · imagens", "PUBLIC_BASE_URL precisa começar com https://"))
    if token_ig.login_instagram() and not os.getenv("GH_PAT"):
        itens.append((AVISO, "Instagram · token", "sem GH_PAT o token renovado não é salvo: vence em 60 dias"))
    if os.getenv("DRY_RUN") == "1":
        itens.append((AVISO, "Instagram", "DRY_RUN=1: nada é publicado de verdade"))
    return itens


def _congresso() -> list[tuple]:
    itens = []
    hoje = date.today()
    testes = [
        ("API da Câmara", "https://dadosabertos.camara.leg.br/api/v2/votacoes", {"itens": 1, "idOrgao": 180}),
        ("API do Senado", "https://legis.senado.leg.br/dadosabertos/votacao",
         {"dataInicio": (hoje - timedelta(days=7)).isoformat(), "dataFim": hoje.isoformat()}),
    ]
    for nome, url, params in testes:
        try:
            r = _get(url, params=params, headers={"Accept": "application/json"}, timeout=30)
            itens.append((OK if r.status_code == 200 else ERRO, nome, f"HTTP {r.status_code}"))
        except requests.RequestException as e:
            itens.append((ERRO, nome, f"fora do ar ou bloqueada: {e.__class__.__name__}"))
    return itens


def _ia() -> list[tuple]:
    chave = os.getenv("ANTHROPIC_API_KEY")
    if not chave:
        return [(AVISO, "IA (resumos)", "sem ANTHROPIC_API_KEY: as legendas usam a ementa oficial, sem reescrita")]
    try:
        r = _get("https://api.anthropic.com/v1/models", headers={"x-api-key": chave, "anthropic-version": "2023-06-01"})
        if r.status_code == 200:
            return [(OK, "IA (resumos)", f"chave válida · modelo {os.getenv('IA_MODELO') or 'padrão'}")]
        return [(ERRO, "IA (resumos)", f"chave recusada (HTTP {r.status_code})")]
    except requests.RequestException as e:
        return [(AVISO, "IA (resumos)", f"sem conexão: {e.__class__.__name__}")]


def _site() -> list[tuple]:
    url = (os.getenv("SITE_TESTE_URL") or "").rstrip("/")
    if not url:
        return [(AVISO, "Site do teste", "SITE_TESTE_URL vazio: o slide e a chamada do teste ficam desligados")]
    try:
        pagina = _get(url + "/")
        if pagina.status_code != 200:
            return [(ERRO, "Site do teste", f"{url} respondeu HTTP {pagina.status_code}")]
        dados = _get(url + "/quiz.json").json()
        if dados.get("demo"):
            return [(ERRO, "Site do teste", "o site está no ar com os dados FICTÍCIOS. Preencha quiz/perguntas.yaml.")]
        return [(OK, "Site do teste", f"no ar · {len(dados.get('perguntas', []))} perguntas · {len(dados.get('parlamentares', []))} parlamentares")]
    except (requests.RequestException, ValueError) as e:
        return [(ERRO, "Site do teste", f"não consegui abrir {url}: {e.__class__.__name__}")]


def _tiktok() -> list[tuple]:
    from bot import tiktok_api
    modo = tiktok_api.modo()
    if modo == "manual":
        return [(OK, "TikTok", "modo manual: imagens e legenda chegam no Telegram depois da aprovação")]
    falta = tiktok_api.faltando()
    if falta:
        return [(ERRO, "TikTok", f"modo {modo}, mas faltam {', '.join(falta)} (cai para o manual)")]
    itens = []
    try:
        info = tiktok_api.creator_info()
        nome = info.get("creator_nickname") or info.get("creator_username") or "?"
        opcoes = info.get("privacy_level_options") or []
        itens.append((OK, "TikTok", f"modo {modo} · conta {nome}"))
        if modo == "direto" and opcoes == ["SELF_ONLY"]:
            itens.append((AVISO, "TikTok", "a conta só aceita posts privados pela API (app sem auditoria)"))
    except Exception as e:
        itens.append((ERRO, "TikTok", f"login ou permissão com problema: {e}"))
    if not os.getenv("GH_PAT"):
        itens.append((AVISO, "TikTok · token", "sem GH_PAT o refresh token renovado não é salvo"))
    return itens


def _conteudo() -> list[tuple]:
    from bot import formatos, frias, storage
    bib = formatos.carregar()
    por_tipo = {t: sum(f["aplica_a"] == t for f in bib.values()) for t in formatos.TIPOS}
    itens = [(OK if all(por_tipo.values()) else ERRO, "Formatos",
              f"{por_tipo['votacao']} de votação e {por_tipo['fria']} de pautas frias ativos")]
    restantes = len(frias.restantes(storage.carregar_estado()))
    itens.append((OK if restantes > 3 else AVISO, "Pautas frias", f"{restantes} explicadores ainda não usados na fila"))
    return itens


def rodar() -> list[tuple]:
    itens = []
    for verificacao in (_telegram, _instagram, _congresso, _ia, _site, _tiktok, _conteudo):
        try:
            itens += verificacao()
        except Exception as e:  # um teste quebrado não derruba os outros
            itens.append((ERRO, verificacao.__name__.strip("_"), f"erro inesperado: {e}"))
    return itens


def texto(itens: list[tuple]) -> str:
    erros = sum(i[0] == ERRO for i in itens)
    avisos = sum(i[0] == AVISO for i in itens)
    resumo = "Tudo certo." if not erros and not avisos else f"{erros} problema(s) e {avisos} aviso(s)."
    linhas = [f"{nivel} {nome}: {msg}" for nivel, nome, msg in itens]
    return "🩺 Diagnóstico do Como Vota\n\n" + "\n".join(linhas) + f"\n\n{resumo}"
