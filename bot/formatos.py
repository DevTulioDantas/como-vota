"""Biblioteca de formatos validados (a "estrutura que funcionou", nunca o conteúdo).

Cada arquivo em formatos/*.yaml descreve UMA estrutura: tipo de gancho, estilo
de capa, ordem dos slides, posição do slide do teste e a primeira linha da
legenda. O conteúdo (textos, números, imagens) é sempre o do próprio perfil.

Como o bot escolhe o formato de cada post
  1. Só entram formatos ativos, do tipo certo e cuja condição ("quando") vale
     para aquela votação (ex.: placar apertado).
  2. Enquanto algum formato elegível tiver menos de MIN_AMOSTRA posts medidos,
     o bot faz rodízio: usa o formato menos usado. Assim todos são testados.
  3. Depois disso, sorteia com peso pela pontuação média de cada formato
     (métricas do Instagram, ver bot/metricas.py). O formato que performa
     melhor aparece mais, mas os outros continuam sendo testados.

Regras de neutralidade
  Os textos fixos do formato (gancho da legenda, kicker e faixa da capa) são
  checados contra uma lista de palavras de tom opinativo ou sensacionalista.
  Um formato que use alguma delas é recusado e não entra no rodízio.
"""
from __future__ import annotations

import json
import logging
import random
import string
import unicodedata
from pathlib import Path

import yaml

from bot import storage

log = logging.getLogger(__name__)

PASTA = Path(__file__).resolve().parent.parent / "formatos"
TIPOS = {"votacao", "fria"}  # fria = explicadores e Bancada do Estado
CAPAS = {"classico", "pergunta", "numero", "apertado", "estados"}
SLIDES_VOTACAO = {"capa", "entenda", "minoria", "placar", "partidos", "dissidentes", "mapa", "cta_teste", "final"}
POSICOES_CTA = {"meio", "antes_final", "nao"}
MIN_AMOSTRA = 3

VARIAVEIS = {
    "votacao": {"titulo", "titulo_min", "proposicao", "casa", "na_casa", "quem_plural",
                "sim", "nao", "diferenca", "diferenca_txt", "resultado", "quorum", "decisao_txt"},
    "fria": {"titulo", "titulo_min", "serie"},
}

# Raízes (sem acento, minúsculas) de palavras que não combinam com a marca.
PROIBIDOS = [
    "polemic", "vergonh", "absurd", "escandal", "traic", "traidor", "golpe", "chocant",
    "inacreditavel", "revoltant", "bomba", "mentir", "lacr", "destrui", "humilh",
    "olha o que", "nao acredit", "urgente", "desmascar", "exposed", "vexame", "ridicul", "drastic",
]


def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")


def _placeholders(texto: str) -> set[str]:
    return {nome for _, nome, _, _ in string.Formatter().parse(texto or "") if nome}


# ------------------------------------------------------------ carregar e validar

def validar(fmt: dict, origem: str = "") -> dict:
    erro = lambda msg: ValueError(f"{origem or fmt.get('id', '?')}: {msg}")
    if not fmt.get("id"):
        raise erro("falta 'id'")
    tipo = fmt.get("aplica_a")
    if tipo not in TIPOS:
        raise erro(f"'aplica_a' deve ser um de {sorted(TIPOS)}")

    textos = {k: fmt.get(k) or "" for k in ("legenda_gancho", "capa_kicker", "faixa_capa")}
    for campo, texto in textos.items():
        sem = _sem_acento(texto)
        achado = next((p for p in PROIBIDOS if p in sem), None)
        if achado:
            raise erro(f"'{campo}' tem tom opinativo/sensacionalista (\"{achado}\"). Reescreva de forma neutra.")
    desconhecidas = _placeholders(textos["legenda_gancho"]) - VARIAVEIS[tipo]
    if desconhecidas:
        raise erro(f"variáveis desconhecidas em legenda_gancho: {sorted(desconhecidas)}")

    if tipo == "votacao":
        if fmt.get("capa", "classico") not in CAPAS:
            raise erro(f"'capa' deve ser um de {sorted(CAPAS)}")
        seq = fmt.get("sequencia") or []
        if not seq or seq[0] != "capa" or seq[-1] != "final":
            raise erro("'sequencia' precisa começar em capa e terminar em final")
        invalidos = set(seq) - SLIDES_VOTACAO
        if invalidos:
            raise erro(f"slides desconhecidos na sequência: {sorted(invalidos)}")
        if len(seq) != len(set(seq)):
            raise erro("a sequência repete slides")
    else:
        if fmt.get("cta_teste", "antes_final") not in POSICOES_CTA:
            raise erro(f"'cta_teste' deve ser um de {sorted(POSICOES_CTA)}")
    return fmt


def carregar(pasta: Path = PASTA) -> dict[str, dict]:
    """Formatos válidos e ativos, por id. Os inválidos são ignorados com aviso."""
    saida = {}
    for arq in sorted(pasta.glob("*.y*ml")):
        if arq.name.startswith("_"):
            continue
        try:
            fmt = validar(yaml.safe_load(arq.read_text(encoding="utf-8")) or {}, arq.name)
        except (ValueError, yaml.YAMLError) as e:
            log.warning("Formato ignorado: %s", e)
            continue
        if fmt.get("ativo", True):
            saida[fmt["id"]] = fmt
    return saida


# ------------------------------------------------------------ desempenho

def desempenho() -> dict[str, list[float]]:
    """Pontuações (métricas do Instagram) dos posts publicados, por formato."""
    notas: dict[str, list[float]] = {}
    if not storage.PASTA_RASCUNHOS.exists():
        return notas
    for arq in storage.PASTA_RASCUNHOS.glob("*/meta.json"):
        try:
            meta = json.loads(arq.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        pont = (meta.get("metricas") or {}).get("pontuacao")
        if meta.get("formato") and pont is not None:
            notas.setdefault(meta["formato"], []).append(float(pont))
    return notas


# ------------------------------------------------------------ escolher

def info_votacao(v) -> dict:
    from bot.models import NAO, SIM
    p = v.placar()
    q = v.quorum()
    if q:  # PEC/PLP: o que decide é a distância até o mínimo de votos SIM
        return {"casa": v.casa, "margem": abs(p[SIM] - q[0]) / q[0], "quorum": q[0]}
    total = (p[SIM] + p[NAO]) or 1
    return {"casa": v.casa, "margem": abs(p[SIM] - p[NAO]) / total}


def _elegivel(fmt: dict, info: dict) -> bool:
    q = fmt.get("quando") or {}
    if "margem_max" in q and info.get("margem", 1) > float(q["margem_max"]):
        return False
    if "margem_min" in q and info.get("margem", 0) < float(q["margem_min"]):
        return False
    if "casa" in q and info.get("casa") != q["casa"]:
        return False
    return True


def escolher(tipo: str, estado: dict, info: dict | None = None, semente: str = "",
             forcar: str | None = None, formatos: dict | None = None, notas: dict | None = None) -> dict | None:
    formatos = carregar() if formatos is None else formatos
    if forcar:
        if forcar not in formatos:
            raise ValueError(f"Formato desconhecido ou inativo: {forcar}")
        return formatos[forcar]
    elegiveis = [f for f in formatos.values() if f["aplica_a"] == tipo and _elegivel(f, info or {})]
    if not elegiveis:
        return None
    notas = desempenho() if notas is None else notas
    uso = estado.setdefault("formatos", {}).setdefault("uso", {})

    if any(len(notas.get(f["id"], [])) < MIN_AMOSTRA for f in elegiveis):
        # Fase de teste: rodízio pelo menos usado (formatos condicionais, como o de
        # placar apertado, aparecem pouco e por isso ganham a vez quando são elegíveis).
        return min(elegiveis, key=lambda f: (uso.get(f["id"], 0), f["id"]))

    medias = {f["id"]: sum(notas[f["id"]]) / len(notas[f["id"]]) for f in elegiveis}
    piso = max(medias.values()) * 0.15 or 1  # todo formato mantém alguma chance
    pesos = [max(medias[f["id"]], piso) for f in elegiveis]
    return random.Random(semente or None).choices(elegiveis, weights=pesos, k=1)[0]


def registrar_uso(estado: dict, fmt: dict | None) -> None:
    if fmt:
        uso = estado.setdefault("formatos", {}).setdefault("uso", {})
        uso[fmt["id"]] = uso.get(fmt["id"], 0) + 1


# ------------------------------------------------------------ textos

class _Seguro(dict):
    def __missing__(self, chave):
        return "{" + chave + "}"


def _minusculo(t: str) -> str:
    if len(t) > 1 and t[1].isupper():  # sigla no começo (PEC, SUS...)
        return t
    return t[:1].lower() + t[1:]


def variaveis_votacao(v, textos: dict) -> dict:
    from bot.models import NAO, SIM
    p = v.placar()
    q = v.quorum()
    dif = abs(p[SIM] - q[0]) if q else abs(p[SIM] - p[NAO])
    titulo = textos.get("titulo", "")
    na_casa = "na Câmara" if v.casa == "camara" else "no Senado"
    dif_txt = f"{dif} voto" if dif == 1 else f"{dif} votos"
    if q:
        decisao = f"{p[SIM]} votos SIM {na_casa}, eram necessários {q[0]}"
    else:
        decisao = f"Decidido por {dif_txt} {na_casa}"
    return {
        "quorum": q[0] if q else "", "decisao_txt": decisao,
        "titulo": titulo, "titulo_min": _minusculo(titulo), "proposicao": v.proposicao,
        "casa": "Câmara" if v.casa == "camara" else "Senado",
        "na_casa": "na Câmara" if v.casa == "camara" else "no Senado",
        "quem_plural": "deputados" if v.casa == "camara" else "senadores",
        "sim": p[SIM], "nao": p[NAO], "diferenca": dif,
        "diferenca_txt": f"{dif} voto" if dif == 1 else f"{dif} votos",
        "resultado": (textos.get("resultado") or "").lower(),
    }


def variaveis_fria(item: dict) -> dict:
    t = item.get("titulo", "")
    return {"titulo": t, "titulo_min": _minusculo(t), "serie": item.get("serie") or "Entenda o Congresso"}


def aplicar_gancho(legenda: str, fmt: dict | None, variaveis: dict) -> str:
    """Troca a primeira linha da legenda (a que aparece no feed) pelo gancho do formato."""
    if not fmt or not fmt.get("legenda_gancho"):
        return legenda
    linhas = legenda.split("\n")
    linhas[0] = fmt["legenda_gancho"].format_map(_Seguro(variaveis))
    return "\n".join(linhas)
