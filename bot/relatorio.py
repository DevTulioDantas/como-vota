"""Relatório semanal no Telegram (toda segunda de manhã, junto com as métricas).

Mostra o que saiu na semana, os posts com melhor pontuação, o ranking dos
formatos (para você ver a estratégia de formato validado funcionando), a
variação de seguidores e o que precisa da sua atenção.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

from bot import formatos, frias, metricas

ROTULOS = {  # (singular, plural)
    "votacao": ("votação", "votações"), "semana": ("Voto da Semana", "Votos da Semana"),
    "explicador": ("explicador", "explicadores"), "bancada": ("Bancada do Estado", "Bancadas do Estado"),
    "repost": ("repost", "reposts"),
}


def _n(n: int, singular: str, plural: str) -> str:
    return f"{n} {singular if n == 1 else plural}"


def _tipo(meta: dict) -> str:
    if meta.get("tipo") == "semana":
        return "semana"
    if meta.get("tipo") == "fria":
        return meta.get("fonte_tipo") or "explicador"
    return "votacao"


def _seguidores(estado: dict, agora: datetime) -> str | None:
    serie = (estado.get("instagram") or {}).get("seguidores") or {}
    if not serie:
        return None
    dias = sorted(serie)
    atual = serie[dias[-1]]
    corte = (agora - timedelta(days=7)).date().isoformat()
    antes = [d for d in dias if d <= corte]
    if not antes:
        return f"{atual:,} seguidores".replace(",", ".")
    dif = atual - serie[antes[-1]]
    sinal = "+" if dif >= 0 else ""
    return f"{atual:,} seguidores ({sinal}{dif:,} na semana)".replace(",", ".")


def montar(estado: dict, metas: list[dict] | None = None, agora: datetime | None = None) -> str:
    agora = agora or datetime.now(timezone.utc)
    metas = metricas.todas_as_metas() if metas is None else metas
    metas = [m for m in metas if not m.get("demo")]
    inicio = agora - timedelta(days=7)

    publicados = [m for m in metas if m.get("status") == "publicado"
                  and (q := metricas.publicado_em(m)) and q >= inicio]
    por_tipo = Counter(_tipo(m) for m in publicados)
    tiktok = sum(1 for m in publicados if m.get("tiktok_enviado")
                 or (m.get("tiktok") or {}).get("status") in ("SEND_TO_USER_INBOX", "PUBLISH_COMPLETE"))
    descartados = sum(1 for m in metas if m.get("status") == "descartado"
                      and any(h.get("status") == "descartado" and datetime.fromisoformat(h["em"]) >= inicio
                              for h in m.get("historico") or []))
    aguardando = sum(1 for m in metas if m.get("status") == "enviado")
    agendados = sum(1 for m in metas if m.get("status") == "agendado")

    linhas = [f"📊 Semana do Como Vota ({inicio:%d/%m} a {agora:%d/%m})", ""]
    if publicados:
        detalhe = ", ".join(_n(n, *ROTULOS[t]) for t, n in por_tipo.most_common())
        linhas.append(f"📤 {_n(len(publicados), 'post', 'posts')} no Instagram: {detalhe}")
    else:
        linhas.append("📤 Nenhum post publicado nesta semana.")
    if tiktok:
        linhas.append(f"🎵 {_n(tiktok, 'enviado', 'enviados')} para o TikTok")
    if descartados:
        linhas.append(f"🗑️ {_n(descartados, 'rascunho descartado', 'rascunhos descartados')}")
    seg = _seguidores(estado, agora)
    if seg:
        linhas.append(f"👥 {seg}")

    medidos = [m for m in metas if (m.get("metricas") or {}).get("pontuacao") is not None
               and (q := metricas.publicado_em(m)) and q >= agora - timedelta(days=30)]
    medidos.sort(key=lambda m: -m["metricas"]["pontuacao"])
    if medidos:
        linhas += ["", "🏆 Melhores posts (últimos 30 dias):"]
        for m in medidos[:3]:
            mt = m["metricas"]
            titulo = (m.get("textos") or {}).get("titulo") or m["id"]
            linhas.append(f"• {titulo[:60]} · pontuação {mt['pontuacao']} "
                          f"({mt.get('saved', 0)} salvos, {mt.get('shares', 0)} compart., alcance {mt.get('reach', 0)})")
        if permalink := medidos[0].get("permalink"):
            linhas.append(f"  {permalink}")

    notas = formatos.desempenho()
    if notas:
        ranking = sorted(((sum(v) / len(v), len(v), k) for k, v in notas.items()), reverse=True)
        linhas += ["", "🧪 Formatos (pontuação média · posts medidos):"]
        for media, n, fid in ranking[:6]:
            marca = "" if n >= formatos.MIN_AMOSTRA else " (ainda em teste)"
            linhas.append(f"• {fid}: {media:.1f} · {n}{marca}")

    atencao = []
    if aguardando:
        atencao.append(f"{_n(aguardando, 'rascunho esperando', 'rascunhos esperando')} sua aprovação")
    if agendados:
        atencao.append(f"{_n(agendados, 'post', 'posts')} na fila de publicação (/fila)")
    restantes = len(frias.restantes(estado))
    if restantes <= 3:
        atencao.append(f"só {_n(restantes, 'explicador novo', 'explicadores novos')} na fila de pautas frias")
    expira = (estado.get("instagram") or {}).get("token_expira_em")
    if expira and datetime.fromisoformat(expira) - agora < timedelta(days=14):
        atencao.append(f"o token do Instagram vence em {datetime.fromisoformat(expira):%d/%m}")
    if atencao:
        linhas += ["", "👀 Precisa de atenção:"] + [f"• {a}" for a in atencao]
    return "\n".join(linhas)
