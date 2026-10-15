"""Gera o título curto, o resumo dos slides e a legenda do post.

Com ANTHROPIC_API_KEY configurada, a IA (SDK oficial da Anthropic, modelo em
IA_MODELO) reescreve a ementa oficial em linguagem simples para leigos. Sem a
chave, ou se a IA falhar, usa a própria ementa: o post sai do mesmo jeito.

Regra de ouro: só fatos. Nada de adjetivo, opinião ou previsão de efeito.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import date
from pathlib import Path

import anthropic
import yaml

from bot import entenda
from bot.models import ABSTENCAO, NAO, OBSTRUCAO, SIM, Votacao

log = logging.getLogger(__name__)

MODELO = os.getenv("IA_MODELO") or "claude-opus-5-5"

INSTRUCOES = """Você escreve para um perfil apartidário no Instagram que mostra como deputados e senadores votaram.
O público é geral: muita gente nunca acompanhou o Congresso e não conhece os termos jurídicos.

A partir da ementa oficial e da descrição da votação, escreva um título e um resumo em linguagem simples.

Regras:
- Diga o que a proposta faz com palavras do dia a dia. Quando a ementa usar um termo técnico ou jurídico, \
explique o que ele quer dizer (por exemplo: "regime de resolução" são as regras para quando um banco ou \
outra instituição financeira quebra).
- Use só o que a ementa diz e o significado comum dos termos. Não invente números, prazos, efeitos, \
contexto, nomes nem consequências.
- Nada de opinião, ironia, adjetivos de valor ou previsão ("histórico", "polêmico", "vai prejudicar", \
"importante"). Descreva, não avalie.
- Não diga se a proposta foi aprovada ou rejeitada: o post já mostra isso.
- Frases curtas, voz ativa, português do Brasil.

titulo: até 60 caracteres, como manchete, com o verbo no presente quando der (ex.: "Reduz a jornada \
semanal de trabalho").
resumo: 1 ou 2 frases, até 220 caracteres, explicando para uma pessoa leiga o que a proposta faz."""

_FORMATO = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {"titulo": {"type": "string"}, "resumo": {"type": "string"}},
        "required": ["titulo", "resumo"],
        "additionalProperties": False,
    },
}
# modelos que aceitam o fallback automático do servidor quando um filtro de segurança recusa o pedido
_COM_FALLBACK = {"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5"}

CASA_NOME = {"camara": "Câmara dos Deputados", "senado": "Senado Federal"}


# "Altera o art. 7º da Constituição Federal para reduzir..." -> o que interessa vem depois do "para"
_PREAMBULO = re.compile(
    r"^(?:altera|acrescenta|modifica|inclui|insere|revoga|d[aá] nova reda[cç][aã]o)\b.{0,160}?\bpara\s+(.+)$",
    re.I | re.S,
)
_OUTRAS_PROVIDENCIAS = re.compile(r"[;,]?\s*e d[aá] outras provid[eê]ncias\.?\s*$", re.I)
# nomes de leis citadas entre aspas ("Estabelece normas para as eleições") não são o objetivo
_CITACAO = re.compile(r"[“\"][^”\"]*[”\"]")
_VERBOS_IRREGULARES = {
    "dispor": "dispõe", "prever": "prevê", "proibir": "proíbe", "manter": "mantém", "ter": "tem",
    "obter": "obtém", "propor": "propõe", "impor": "impõe", "compor": "compõe", "ver": "vê",
}


# palavras que não podem ficar no fim de um título cortado
_SOLTAS = {"a", "o", "as", "os", "à", "às", "ao", "aos", "de", "do", "da", "dos", "das", "e", "em", "no", "na",
           "nos", "nas", "para", "por", "pelo", "pela", "com", "que", "um", "uma", "sobre", "ou"}


def _presente(verbo: str) -> str:
    """Infinitivo -> 3ª pessoa do presente, para o título ler como manchete: reduzir -> reduz."""
    v = verbo.lower()
    if v in _VERBOS_IRREGULARES:
        p = _VERBOS_IRREGULARES[v]
    elif v.endswith("uir"):
        p = v[:-1]  # instituir -> institui
    elif v.endswith("uzir"):
        p = v[:-2]  # reduzir -> reduz
    elif v.endswith(("ar", "er", "ir")):
        p = v[:-2] + ("a" if v.endswith("ar") else "e")
    else:
        return verbo
    return p[:1].upper() + p[1:] if verbo[:1].isupper() else p


def titulo_da_ementa(ementa: str, limite: int = 70) -> str:
    """Título sem IA: tira o preâmbulo jurídico e corta numa pausa natural da frase."""
    t = _OUTRAS_PROVIDENCIAS.sub("", " ".join(ementa.split())).rstrip(" .;,")
    m = _PREAMBULO.match(" ".join(_CITACAO.sub("", t).split()))
    if m:
        palavras = m.group(1).split(" ")
        palavras[0] = _presente(palavras[0])
        if len(palavras) > 2 and palavras[1] == "e":  # "simplificar e conferir" -> "simplifica e confere"
            palavras[2] = _presente(palavras[2])
        t = " ".join(palavras)
    t = t.split(";")[0].strip()
    t = t[:1].upper() + t[1:]
    if len(t) <= limite:
        return t
    # termina antes de um segundo verbo ("reduzir X e prever Y"), nunca no meio de uma lista
    cortes = [c.start() for c in re.finditer(r" e (?=\w+(?:ar|er|ir)\b)", t[:limite]) if c.start() >= 25]
    if cortes:
        return t[:cortes[-1]]
    palavras = t[:limite - 1].rsplit(" ", 1)[0].rstrip(",").split(" ")
    while len(palavras) > 4 and palavras[-1].lower().rstrip(",") in _SOLTAS:
        palavras.pop()  # "... gestão de" -> "... gestão"
    return " ".join(palavras).rstrip(",") + "…"


def _fallback(v: Votacao) -> dict:
    ementa = v.ementa or v.descricao
    titulo = titulo_da_ementa(ementa)
    resumo = ementa if len(ementa) <= 220 else ementa[:217].rsplit(" ", 1)[0] + "…"
    return {"titulo": titulo, "resumo": resumo}


def _ia(v: Votacao) -> dict | None:
    if not os.getenv("ANTHROPIC_API_KEY"):
        return None
    pedido = {
        "model": MODELO,
        "max_tokens": 4000,
        "system": INSTRUCOES,
        # texto curto e tarefa simples: esforço baixo basta e sai mais barato
        "output_config": {"effort": "low", "format": _FORMATO},
        "messages": [{"role": "user", "content": (
            f"Proposição: {v.proposicao}\nEmenta oficial: {v.ementa}\nO que foi votado: {v.descricao}"
        )}],
    }
    try:
        cliente = anthropic.Anthropic(timeout=60.0)
        if MODELO in _COM_FALLBACK:  # se um filtro de segurança recusar, outro modelo responde
            resposta = cliente.beta.messages.create(
                **pedido, betas=["server-side-fallback-2026-07-01"], fallbacks="default")
        else:
            resposta = cliente.messages.create(**pedido)
        if resposta.stop_reason != "end_turn":
            log.warning("IA parou com %s em %s; usando ementa", resposta.stop_reason, v.id)
            return None
        dados = json.loads(next(b.text for b in resposta.content if b.type == "text"))
        if dados.get("titulo") and dados.get("resumo"):
            return {"titulo": dados["titulo"][:80], "resumo": dados["resumo"][:260]}
    except Exception as e:  # nunca derrubar o pipeline por causa do texto
        log.warning("IA indisponível para %s (%s); usando ementa", v.id, e)
    return None


def _data_br(iso: str) -> str:
    try:
        return date.fromisoformat(iso[:10]).strftime("%d/%m/%Y")
    except ValueError:
        return iso


ARQUIVO_APELIDOS = Path(__file__).resolve().parent.parent / "apelidos.yaml"


def aplicar_apelido_manual(v: Votacao) -> None:
    """apelidos.yaml ("PEC 221/2019": "Fim da escala 6x1") vale mais que o registro oficial:
    é a curadoria do dono, para quando a imprensa batizou o projeto antes do Senado."""
    try:
        tabela = yaml.safe_load(ARQUIVO_APELIDOS.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        return
    except yaml.YAMLError as e:
        log.warning("apelidos.yaml inválido (%s); ignorado", e)
        return
    nome = str(tabela.get(v.proposicao) or "").strip()
    if nome:
        v.apelido, v.fonte_apelido = nome, "curadoria"


# nome por extenso do tipo, na legenda: "PLP 281/2019 (Projeto de Lei Complementar)"
_NOME_TIPO = {sigla: texto.split(":")[0] for sigla, texto in entenda.TIPOS.items()}


def gerar_textos(v: Votacao, handle: str = "@comovotadeputado") -> dict:
    aplicar_apelido_manual(v)
    base = _ia(v) or _fallback(v)
    if v.apelido:  # o nome conhecido do projeto é o melhor título; a ementa segue no resumo
        base = {**base, "titulo": v.apelido}
    p = v.placar()
    resultado = {True: "APROVADA", False: "REJEITADA", None: "RESULTADO"}[v.aprovada]
    carimbo = entenda.carimbo(v) or resultado

    linhas = [
        f"🗳️ {base['titulo']}",
        "",
        base["resumo"],
        "",
        f"📍 {CASA_NOME[v.casa]} · {_data_br(v.data)}",
        f"📄 {v.proposicao}" + (f" ({_NOME_TIPO[v.tipo_proposicao]})" if v.tipo_proposicao in _NOME_TIPO else "")
        + (f" · conhecida como “{v.apelido}”" if v.apelido else ""),
        # Guia de marca: voto nunca é representado por emoji (✅/❌) — só texto aqui.
        f"📊 Resultado: {carimbo.capitalize()} · SIM {p[SIM]} × {p[NAO]} NÃO"
        + f" · Abstenção {p[ABSTENCAO]}"
        + (f" · Obstrução {p[OBSTRUCAO]}" if p[OBSTRUCAO] else ""),
    ]
    if q := v.quorum():
        situacao = "Conseguiu." if p[SIM] >= q[0] else f"Faltaram {q[0] - p[SIM]}."
        linhas.append(f"📏 Para aprovar, precisava de {q[0]} votos SIM ({q[1]}). {situacao}")
    if v.orientacao_governo:
        linhas.append(f"⚖️ O governo pediu voto {v.orientacao_governo.upper()}")
    if v.descricao:
        etapa = entenda.explicar_etapa(v)[0]
        linhas += [""] + ([etapa] if etapa else []) + [f"Texto oficial da votação: {v.descricao}"]
    quem = "deputado" if v.casa == "camara" else "senador"
    linhas += [
        "",
        f"O voto de cada {quem} está na fonte oficial abaixo.",
        f"🔎 Fonte oficial: {v.url_fonte}" if v.url_fonte else "🔎 Fonte: dados abertos do Congresso Nacional",
        "",
        "#ComoVotaDeputado #VotoAberto #CongressoNacional #Transparência",
    ]
    return {**base, "resultado": resultado, "carimbo": carimbo, "legenda": "\n".join(linhas)[:2200]}
