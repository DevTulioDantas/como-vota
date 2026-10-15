"""Gera o título curto, o resumo dos slides e a legenda do post.

Com ANTHROPIC_API_KEY configurada, usa a IA para reescrever a ementa oficial
em linguagem simples. Sem a chave, usa a própria ementa (funciona igual,
só fica menos fluido).

Regra de ouro: só fatos. Nada de adjetivo, opinião ou previsão de efeito.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import date
from pathlib import Path

import requests
import yaml

from bot import entenda
from bot.models import ABSTENCAO, NAO, OBSTRUCAO, SIM, Votacao

log = logging.getLogger(__name__)

MODELO = os.getenv("IA_MODELO", "claude-haiku-5-5")

INSTRUCOES = """Você escreve para um perfil apartidário que informa como parlamentares votaram.
Regras obrigatórias:
- Use somente as informações fornecidas (ementa oficial e descrição da votação). Não invente efeitos, números ou contexto.
- Linguagem simples, frases curtas, português do Brasil.
- Proibido: adjetivos valorativos, ironia, opinião, previsões ("vai prejudicar", "histórico", "polêmico", "polêmica").
- Se a ementa não deixar claro o que muda, diga apenas o que ela diz.
Responda APENAS com JSON válido neste formato:
{"titulo": "até 70 caracteres, diz o que foi votado", "resumo": "1 a 2 frases, até 220 caracteres, explicando o que a proposta faz"}"""

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
    chave = os.getenv("ANTHROPIC_API_KEY")
    if not chave:
        return None
    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": chave, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={
                "model": MODELO,
                "max_tokens": 400,
                "system": INSTRUCOES,
                "messages": [{"role": "user", "content": (
                    f"Proposição: {v.proposicao}\nEmenta oficial: {v.ementa}\n"
                    f"O que foi votado: {v.descricao}"
                )}],
            },
            timeout=60,
        )
        r.raise_for_status()
        texto = "".join(b.get("text", "") for b in r.json().get("content", []))
        texto = texto[texto.find("{"): texto.rfind("}") + 1]
        dados = json.loads(texto)
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
