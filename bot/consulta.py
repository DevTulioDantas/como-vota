"""Consulta livre ao Gemini para o dono (ex.: ideias para deixar os posts mais interessantes).

Roda no GitHub Actions (onde está a GEMINI_API_KEY) pelo workflow "Consultar a IA" e manda a
resposta no Telegram. Não mexe em post nenhum: é só conversa.
"""
from __future__ import annotations

import json
import logging

from bot import storage
from bot.summarizer import gemini_gerar

log = logging.getLogger(__name__)

PERGUNTA_PADRAO = """Você é especialista em crescimento de perfis no Instagram, com foco em carrosséis \
informativos. Analise o perfil descrito abaixo e o post de exemplo, e diga, de forma concreta e prática, \
como deixar as publicações mais interessantes para a rede social: mais gente parando na capa, arrastando \
o carrossel até o fim, salvando, compartilhando, comentando e seguindo.

Cubra: capa (texto e hierarquia), sequência e conteúdo dos slides, legenda (primeira linha, estrutura, \
hashtags), chamada final, ideias de formatos novos para o rodízio, frequência e horários, e o que medir.
Para cada sugestão, dê um exemplo pronto usando o post de exemplo.

Respeite as regras do perfil (elas não podem ser quebradas): ele é apartidário, nunca opina sobre o \
mérito de um voto, partido ou político, só usa dados oficiais e verificáveis, não usa sensacionalismo \
nem clickbait, e não diz "faltou" para quem não votou (pode ser licença ou missão oficial)."""

PERFIL = """Perfil: "Como Vota Deputado?" (@comovotadeputado). Publica carrosséis 1080x1080 com votações \
nominais da Câmara e do Senado, com dados oficiais. Público geral, que em geral não acompanha o Congresso. \
Linguagem simples. Identidade: azul-escuro, amarelo, verde para SIM e vermelho para NÃO.

Estrutura atual de um carrossel de votação:
1. Capa: assunto em destaque (título grande), resumo de 1 a 2 frases, uma chamada ("Como votou cada \
estado?") e um carimbo com o resultado (APROVADA, REJEITADA, SUBSTITUTIVO REJEITADO...).
2. "O que está em votação": o que é o tipo de projeto (PEC, PLP...), lista do que o projeto faz, a etapa \
votada e "E agora?" (próximo passo).
3. Placar SIM x NÃO, abstenções, quórum necessário e orientação do governo.
4. Quando o placar é muito desigual (ex.: 461 x 4): os nomes de quem ficou no lado menor.
5. Como votou cada partido (barras) ou cada estado (mapa em grade).
6. Quem votou diferente do próprio partido.
7. Final: chamada ligada ao tema, três motivos para seguir e botão "Siga".
Os formatos de capa alternam por rodízio (clássico, pergunta, mapa, placar na capa, placar apertado)."""


def _exemplo() -> str:
    """Um post real recente (o mais novo em rascunho) para a IA comentar."""
    metas = [json.loads(a.read_text(encoding="utf-8")) for a in storage.pasta("x").parent.glob("*/meta.json")]
    # o mais completo (com lista e chamada) e mais recente: é o que mostra o formato atual dos posts
    metas.sort(key=lambda m: (bool(m.get("textos", {}).get("detalhes")), bool(m.get("textos", {}).get("chamada")),
                              m.get("criado_em", "")), reverse=True)
    for meta in metas:
        if meta.get("textos", {}).get("legenda") and not meta.get("demo"):
            t = meta["textos"]
            detalhes = "\n".join(f"- {d}" for d in t.get("detalhes") or [])
            return (f"Título da capa: {t.get('titulo')}\nResumo: {t.get('resumo')}\n"
                    f"O que o projeto faz:\n{detalhes}\nChamada final: {t.get('chamada') or '(fixa)'}\n\n"
                    f"Legenda completa:\n{t['legenda']}")
    return "(sem post recente)"


def consultar(pergunta: str = "") -> str:
    texto = f"{pergunta.strip() or PERGUNTA_PADRAO}\n\n{PERFIL}\n\nPost de exemplo:\n{_exemplo()}"
    corpo = gemini_gerar({"contents": [{"role": "user", "parts": [{"text": texto}]}],
                          "generationConfig": {"temperature": 0.7, "maxOutputTokens": 32000}}, timeout=180)
    partes = ((corpo.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
    return "".join(p.get("text", "") for p in partes).strip()

