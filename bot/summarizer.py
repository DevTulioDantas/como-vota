"""Gera o título curto, o resumo dos slides e a legenda do post.

Com GEMINI_API_KEY (modelo em GEMINI_MODELO) ou ANTHROPIC_API_KEY (SDK oficial,
modelo em IA_MODELO), a IA reescreve a ementa oficial em linguagem simples para
leigos; o Gemini tem prioridade. Sem chave, ou se a IA falhar, usa a própria
ementa: o post sai do mesmo jeito.

Regra de ouro: só fatos. Nada de adjetivo, opinião ou previsão de efeito.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import date
from pathlib import Path

import anthropic
import requests
import yaml

from bot import entenda
from bot.models import ABSTENCAO, NAO, OBSTRUCAO, SIM, Votacao

log = logging.getLogger(__name__)

MODELO = os.getenv("IA_MODELO") or "claude-opus-5-5"
GEMINI_MODELO = os.getenv("GEMINI_MODELO") or "gemini-2.5-flash"
GEMINI_API = "https://generativelanguage.googleapis.com/v1beta"
# plano gratuito: o modelo principal vive dando "alta demanda" (503); estes entram no lugar dele
GEMINI_RESERVAS = [m.strip() for m in (os.getenv("GEMINI_RESERVAS")
                   or "gemini-3.1-flash-lite-preview,gemini-2.5-flash,gemini-2.5-flash-lite").split(",") if m.strip()]


def gemini_gerar(pedido: dict, timeout: int = 60) -> dict:
    """Chama o Gemini no modelo principal e, se ele estiver sobrecarregado, sem cota ou fora do ar,
    nos modelos reserva. Devolve o corpo da resposta ou levanta o último erro."""
    erro = "nenhum modelo configurado"
    for modelo in dict.fromkeys([GEMINI_MODELO, *GEMINI_RESERVAS]):
        for tentativa in range(2):
            r = requests.post(f"{GEMINI_API}/models/{modelo}:generateContent", json=pedido, timeout=timeout,
                              headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]})
            corpo = r.json()
            if r.status_code == 200:
                if modelo != GEMINI_MODELO:
                    log.info("Gemini %s sobrecarregado; respondeu o reserva %s", GEMINI_MODELO, modelo)
                return corpo
            erro = f"{modelo}: HTTP {r.status_code}: {(corpo.get('error') or {}).get('message', corpo)}"
            if r.status_code in (500, 503) and tentativa == 0:
                time.sleep(5)  # "alta demanda" às vezes passa em segundos
                continue
            if r.status_code in (404, 429, 500, 503):
                break  # modelo inexistente, sem cota ou ainda sobrecarregado: tenta o próximo
            raise RuntimeError(erro)  # chave inválida, pedido errado: trocar de modelo não resolve
    raise RuntimeError(erro)

INSTRUCOES = """Você escreve para um perfil apartidário no Instagram que mostra como deputados e senadores votaram.
O público é geral: muita gente nunca acompanhou o Congresso. O post concorre com tudo o que passa no feed, então \
o texto precisa fazer a pessoa parar de rolar e entender, em 2 segundos, do que se trata e por que aquilo tem a \
ver com a vida dela.

A partir da ementa oficial e da descrição da votação, escreva um título (o texto grande da capa) e um resumo.

Como prender a atenção (sem perder a neutralidade):
- Assunto nas primeiras palavras, pelo nome que as pessoas usam no dia a dia, não pelo nome técnico: \
"MEI" e não "Lei Complementar nº 123"; "conta de luz" e não "tarifa de energia elétrica"; "escala 6x1" e não \
"duração do trabalho". Se o tema tem um nome conhecido, use-o.
- Diga a quem aquilo diz respeito quando a ementa deixar isso claro ("quem é MEI", "quem trabalha de carteira \
assinada", "quem tem plano de saúde"). É isso que faz a pessoa se reconhecer no post.
- Concreto vence abstrato: "quanto o MEI pode faturar por ano" prende mais que "limite de receita bruta anual".
- Título como manchete: curto, direto, com verbo. Pode usar "o que muda" ou uma pergunta, desde que a resposta \
esteja no post.
- No resumo, a primeira frase responde "o que isso tem a ver comigo?"; a segunda dá o detalhe.

Limites (obrigatórios, valem mais que qualquer técnica acima):
- Use só o que a ementa diz e o significado comum dos termos. Não invente números, valores, prazos, efeitos, \
contexto, nomes nem consequências. Se a ementa não diz o novo valor, não diga.
- Explique termos técnicos ou jurídicos com palavras simples (ex.: "regime de resolução" são as regras para \
quando um banco quebra).
- Nada de sensacionalismo, opinião, ironia, adjetivo de valor ou previsão: proibido "urgente", "bomba", \
"você não vai acreditar", "histórico", "polêmico", "importante", "vai prejudicar", "vai beneficiar". Atrair \
pelo assunto, nunca pelo exagero.
- Não diga se a proposta foi aprovada ou rejeitada: o post já mostra isso.
- Frases curtas, voz ativa, português do Brasil.

titulo: até 60 caracteres. Ex.: "Teto do MEI: muda quanto dá para faturar", "Reduz a jornada semanal de trabalho".
resumo: 1 ou 2 frases, até 220 caracteres.
detalhes: de 2 a 4 itens, cada um com até 100 caracteres, explicando em palavras simples cada parte do que a \
ementa diz. Cubra TODAS as partes da ementa, sem omitir nenhuma (ex.: se ela também perdoa dívidas ou muda \
prazos, isso precisa estar na lista).
chamada: até 70 caracteres, a frase do último slide, que convida a seguir o perfil. Ligue o assunto do post ao \
representante de quem lê (ex.: "Teto do MEI: e o deputado que você elegeu, como votou?", "Escala 6x1: você sabe \
como votou o seu senador?"). Nunca cite nome de pessoa nem de partido, nunca sugira como avaliar o voto e nada \
de pressão ou ataque: o convite é para acompanhar, não para punir ninguém."""

_FORMATO = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {"titulo": {"type": "string"}, "resumo": {"type": "string"},
                       "detalhes": {"type": "array", "items": {"type": "string"}},
                       "chamada": {"type": "string"}},
        "required": ["titulo", "resumo", "detalhes", "chamada"],
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


def _pergunta(v: Votacao) -> str:
    return f"Proposição: {v.proposicao}\nEmenta oficial: {v.ementa}\nO que foi votado: {v.descricao}"


def _valida(dados: dict) -> dict | None:
    if dados.get("titulo") and dados.get("resumo"):
        detalhes = [str(d).strip()[:120] for d in (dados.get("detalhes") or []) if str(d).strip()][:4]
        return {"titulo": dados["titulo"][:80], "resumo": dados["resumo"][:260], "detalhes": detalhes,
                "chamada": str(dados.get("chamada") or "").strip()[:90]}
    return None


def _ia(v: Votacao) -> dict | None:
    """IA configurada: Gemini se houver GEMINI_API_KEY, senão Claude se houver ANTHROPIC_API_KEY."""
    if os.getenv("GEMINI_API_KEY"):
        return _ia_gemini(v)
    if os.getenv("ANTHROPIC_API_KEY"):
        return _ia_anthropic(v)
    return None


def _ia_gemini(v: Votacao) -> dict | None:
    pedido = {
        "systemInstruction": {"parts": [{"text": INSTRUCOES}]},
        "contents": [{"role": "user", "parts": [{"text": _pergunta(v)}]}],
        "generationConfig": {
            "temperature": 0.2,  # texto informativo: pouca variação
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "OBJECT",
                "properties": {"titulo": {"type": "STRING"}, "resumo": {"type": "STRING"},
                               "detalhes": {"type": "ARRAY", "items": {"type": "STRING"}},
                               "chamada": {"type": "STRING"}},
                "required": ["titulo", "resumo", "detalhes", "chamada"],
            },
        },
    }
    try:
        corpo = gemini_gerar(pedido)
        candidato = (corpo.get("candidates") or [{}])[0]
        if candidato.get("finishReason") != "STOP":
            bloqueio = (corpo.get("promptFeedback") or {}).get("blockReason")
            log.warning("Gemini parou com %s em %s; usando ementa", bloqueio or candidato.get("finishReason"), v.id)
            return None
        texto = "".join(p.get("text", "") for p in candidato["content"]["parts"])
        return _valida(json.loads(texto))
    except Exception as e:  # nunca derrubar o pipeline por causa do texto
        log.warning("Gemini indisponível para %s (%s); usando ementa", v.id, e)
    return None


def _ia_anthropic(v: Votacao) -> dict | None:
    pedido = {
        "model": MODELO,
        "max_tokens": 4000,
        "system": INSTRUCOES,
        # texto curto e tarefa simples: esforço baixo basta e sai mais barato
        "output_config": {"effort": "low", "format": _FORMATO},
        "messages": [{"role": "user", "content": _pergunta(v)}],
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
        return _valida(json.loads(next(b.text for b in resposta.content if b.type == "text")))
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


ARQUIVO_EXPLICACOES = Path(__file__).resolve().parent.parent / "explicacoes.yaml"


def explicacoes() -> dict:
    """explicacoes.yaml: título e resumo em linguagem simples escritos por um agente ou pelo dono."""
    try:
        return yaml.safe_load(ARQUIVO_EXPLICACOES.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        return {}
    except yaml.YAMLError as e:
        log.warning("explicacoes.yaml inválido (%s); ignorado", e)
        return {}


def explicacao_escrita(v: Votacao) -> dict | None:
    texto = _valida(explicacoes().get(v.proposicao) or {})
    return {**texto, "fonte_texto": "explicacoes.yaml"} if texto else None


def gerar_textos(v: Votacao, handle: str = "@comovotadeputado") -> dict:
    aplicar_apelido_manual(v)
    # ordem: texto escrito (agente ou dono) > IA pela API > ementa oficial
    base = explicacao_escrita(v)
    if not base and (ia := _ia(v)):
        base = {**ia, "fonte_texto": "ia"}
    base = base or {**_fallback(v), "fonte_texto": "ementa"}
    if v.apelido:  # o nome conhecido do projeto é o melhor título; a ementa segue no resumo
        base = {**base, "titulo": v.apelido}
    p = v.placar()
    resultado = {True: "APROVADA", False: "REJEITADA", None: "RESULTADO"}[v.aprovada]
    carimbo = entenda.carimbo(v) or resultado

    linhas = [
        f"🗳️ {base['titulo']}",
        "",
        base["resumo"],
        *([""] + ["O que o projeto faz:"] + [f"• {d}" for d in base["detalhes"]] if base.get("detalhes") else []),
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
    if minoria := v.minoria():
        lado, votos = minoria
        nomes = ", ".join(f"{x.nome} ({x.partido}-{x.uf})" for x in votos)
        linhas.append(f"🔎 Votaram {lado.upper()} ({len(votos)}): {nomes}")
    if passo := entenda.proximo_passo(v):
        linhas.append(f"➡️ E agora? {passo}")
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
