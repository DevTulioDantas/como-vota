"""Exporta os dados do teste "Quem vota como você?" para o site (site/quiz.json).

Curadoria em quiz/perguntas.yaml: VOCÊ escolhe as votações e escreve o resumo
neutro de cada pergunta. O bot só busca os votos oficiais e monta o arquivo.

O cálculo do resultado acontece no navegador de quem faz o teste: as
respostas nunca são enviadas junto com qualquer identificação.
"""
from __future__ import annotations

import json
import logging
import random
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import yaml

from bot import storage
from bot.collectors import camara, senado
from bot.models import ABSTENCAO, NAO, OBSTRUCAO, SIM, Votacao

log = logging.getLogger(__name__)

RAIZ = Path(__file__).resolve().parent.parent
ARQ_CURADORIA = RAIZ / "quiz" / "perguntas.yaml"
ARQ_SAIDA = RAIZ / "site" / "quiz.json"
CODIGO = {SIM: "S", NAO: "N", ABSTENCAO: "A", OBSTRUCAO: "O"}
CAMPOS_OBRIGATORIOS = ("votacao", "titulo", "resumo", "sim_significa")


def carregar_curadoria(arq: Path = ARQ_CURADORIA) -> list[dict]:
    dados = yaml.safe_load(arq.read_text(encoding="utf-8")) or {}
    perguntas = dados.get("perguntas") or []
    for i, p in enumerate(perguntas, 1):
        faltando = [c for c in CAMPOS_OBRIGATORIOS if not p.get(c)]
        if faltando:
            raise ValueError(f"Pergunta {i} sem: {', '.join(faltando)}")
    return perguntas


def obter_votacao(vid: str, cfg: dict | None = None) -> Votacao | None:
    """Usa o rascunho salvo, se houver; senão busca na API da Câmara ou do Senado."""
    arq = storage.pasta(vid) / "meta.json"
    if arq.exists():
        meta = json.loads(arq.read_text(encoding="utf-8"))
        if "votacao" in meta:
            return Votacao.from_dict(meta["votacao"])
    if vid.startswith("senado-"):
        data = (cfg or {}).get("data")
        if not data:
            raise ValueError(f"{vid}: perguntas do Senado precisam do campo 'data' (AAAA-MM-DD da sessão)")
        return senado.coletar_por_id(vid, str(data))
    return camara.coletar_por_id(vid)


def exportar(curadoria: list[dict], obter=obter_votacao, demo: bool = False) -> dict:
    perguntas, parlamentares = [], {}
    for n, cfg in enumerate(curadoria, 1):
        v = obter(cfg["votacao"], cfg)
        if v is None or not v.votos:
            raise ValueError(f"Votação {cfg['votacao']} não encontrada ou sem votos nominais")
        qid = f"q{n}"
        p = v.placar()
        perguntas.append({
            "id": qid,
            "casa": v.casa,
            "tema": cfg.get("tema", ""),
            "proposicao": v.proposicao,
            "data": v.data,
            "titulo": cfg["titulo"],
            "resumo": cfg["resumo"],
            "sim_significa": cfg["sim_significa"],
            "link": cfg.get("link") or v.url_fonte,
            "resultado": {True: "Aprovada", False: "Rejeitada", None: ""}[v.aprovada],
            "placar": {"sim": p[SIM], "nao": p[NAO]},
        })
        for voto in v.votos:
            if not voto.id:
                continue
            chave = f"{v.casa}-{voto.id}"
            reg = parlamentares.setdefault(chave, {"id": chave, "casa": v.casa, "votos": {}})
            # partido/UF da votação mais recente (as perguntas vêm em ordem cronológica)
            if v.data >= reg.get("_data", ""):
                reg.update(nome=voto.nome, partido=voto.partido, uf=voto.uf, _data=v.data)
            reg["votos"][qid] = CODIGO.get(voto.voto, "X")

    lista = []
    for reg in parlamentares.values():
        reg.pop("_data", None)
        lista.append(reg)
    lista.sort(key=lambda r: (r["casa"], r["nome"]))
    return {
        "versao": 1,
        "demo": demo,
        "casas": sorted({p["casa"] for p in perguntas}),
        "gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "perguntas": perguntas,
        "parlamentares": lista,
    }


def salvar(dados: dict, destino: Path = ARQ_SAIDA) -> Path:
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(dados, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log.info("quiz.json: %d perguntas, %d parlamentares → %s",
             len(dados["perguntas"]), len(dados["parlamentares"]), destino)
    return destino


# ---------------------------------------------------------------- demo fictícia

TEMAS_DEMO = [
    ("Economia", "Limite de exemplo para juros do cartão de crédito",
     "Proposta fictícia que define um teto para os juros cobrados no rotativo do cartão.",
     "Votar SIM era aprovar o teto de juros."),
    ("Meio ambiente", "Prazo de exemplo para licenciamento ambiental",
     "Proposta fictícia que muda o prazo máximo para órgãos analisarem pedidos de licença ambiental.",
     "Votar SIM era aprovar o novo prazo."),
    ("Segurança", "Regras de exemplo para câmeras em fardas policiais",
     "Proposta fictícia que torna obrigatório o uso de câmeras corporais por policiais federais.",
     "Votar SIM era tornar as câmeras obrigatórias."),
    ("Educação", "Programa de exemplo de ensino integral",
     "Proposta fictícia que cria repasse federal para escolas que ampliarem a jornada para tempo integral.",
     "Votar SIM era criar o programa."),
    ("Saúde", "Exemplo de piso para agentes de saúde",
     "Proposta fictícia que fixa um valor mínimo de salário para agentes comunitários de saúde.",
     "Votar SIM era aprovar o piso salarial."),
    ("Gestão pública", "Exemplo de limite para gastos com publicidade",
     "Proposta fictícia que limita os gastos do governo federal com propaganda institucional.",
     "Votar SIM era aprovar o limite."),
    ("Tributos", "Exemplo de isenção para cesta básica",
     "Proposta fictícia que zera um imposto federal sobre itens da cesta básica.",
     "Votar SIM era aprovar a isenção."),
    ("Trabalho", "Exemplo de regras para trabalho por aplicativo",
     "Proposta fictícia que cria contribuição previdenciária para motoristas de aplicativo.",
     "Votar SIM era criar a contribuição."),
    ("Transporte", "Exemplo de subsídio a ônibus urbanos",
     "Proposta fictícia que cria repasse federal para baratear a tarifa de ônibus nas capitais.",
     "Votar SIM era criar o repasse."),
    ("Tecnologia", "Exemplo de regras para inteligência artificial",
     "Proposta fictícia que obriga plataformas a identificar conteúdos gerados por IA.",
     "Votar SIM era aprovar a obrigação."),
]


SENADO_DEMO = [
    ("Economia", "Exemplo de regra para renegociação de dívidas",
     "Proposta fictícia que cria um programa federal para renegociar dívidas de pessoas físicas com bancos.",
     "Votar SIM era criar o programa."),
    ("Segurança", "Exemplo de pena maior para golpes digitais",
     "Proposta fictícia que aumenta a pena para crimes de estelionato praticados pela internet.",
     "Votar SIM era aumentar a pena."),
    ("Meio ambiente", "Exemplo de meta para reciclagem de plástico",
     "Proposta fictícia que obriga fabricantes a reciclar um percentual mínimo das embalagens plásticas.",
     "Votar SIM era criar a obrigação."),
    ("Gestão pública", "Exemplo de prazo para obras paradas",
     "Proposta fictícia que fixa prazo para a retomada de obras federais interrompidas.",
     "Votar SIM era aprovar o prazo."),
    ("Saúde", "Exemplo de lista de remédios gratuitos",
     "Proposta fictícia que amplia a lista de medicamentos distribuídos de graça pelo SUS.",
     "Votar SIM era ampliar a lista."),
]


def exportar_demo(semente: int = 21) -> dict:
    """10 perguntas da Câmara, 5 do Senado e 594 parlamentares FICTÍCIOS para testar o site."""
    from bot.demo import NOMES, PARTIDOS, SOBRENOMES, UFS
    from bot.models import Voto

    rnd = random.Random(semente)
    elenco = []
    for sigla, (bancada, _) in PARTIDOS.items():
        for i in range(bancada):
            elenco.append((f"d{sigla}{i}", f"{rnd.choice(NOMES)} {rnd.choice(SOBRENOMES)}", sigla, rnd.choice(UFS)))
    # cada partido tem uma chance de SIM diferente por tema
    posicao = {(s, t): rnd.random() for s in PARTIDOS for t in range(len(TEMAS_DEMO))}

    votacoes = {}
    for t, (tema, titulo, *_r) in enumerate(TEMAS_DEMO):
        votos = []
        for pid, nome, sigla, uf in elenco:
            if rnd.random() < .07:
                continue
            r = rnd.random()
            voto = SIM if r < posicao[(sigla, t)] * .96 else ABSTENCAO if r > .985 else NAO
            votos.append(Voto(nome=nome, partido=sigla, uf=uf, voto=voto, voto_original=voto, id=pid))
        sim = sum(1 for v in votos if v.voto == SIM)
        votacoes[f"demo-{t}"] = Votacao(
            id=f"demo-{t}", casa="camara", data=f"2026-0{1 + t % 9}-1{t % 9}", proposicao=f"PL 00{t:02d}/2026",
            tipo_proposicao="PL", ementa=titulo, descricao="Exemplo fictício", aprovada=sim > len(votos) / 2,
            url_fonte="https://dadosabertos.camara.leg.br", votos=votos,
        )
    curadoria = [
        {"votacao": f"demo-{t}", "tema": tema, "titulo": titulo, "resumo": resumo, "sim_significa": sim_sig}
        for t, (tema, titulo, resumo, sim_sig) in enumerate(TEMAS_DEMO)
    ]

    # Senado fictício: 3 senadores por UF
    senadores = [(f"s{uf}{i}", f"{rnd.choice(NOMES)} {rnd.choice(SOBRENOMES)}", rnd.choice(list(PARTIDOS)[:10]), uf)
                 for uf in UFS for i in range(3)]
    pos_s = {(s, t): rnd.random() for s in PARTIDOS for t in range(len(SENADO_DEMO))}
    for t, (tema, titulo, resumo, sim_sig) in enumerate(SENADO_DEMO):
        votos = []
        for pid, nome, sigla, uf in senadores:
            if rnd.random() < .08:
                continue
            voto = SIM if rnd.random() < pos_s[(sigla, t)] else NAO
            votos.append(Voto(nome=nome, partido=sigla, uf=uf, voto=voto, voto_original=voto, id=pid))
        sim = sum(1 for v in votos if v.voto == SIM)
        vid = f"demo-senado-{t}"
        votacoes[vid] = Votacao(
            id=vid, casa="senado", data=f"2026-0{2 + t}-2{t}", proposicao=f"PLS 00{t:02d}/2026",
            tipo_proposicao="PL", ementa=titulo, descricao="Exemplo fictício", aprovada=sim > len(votos) / 2,
            url_fonte="https://legis.senado.leg.br/dadosabertos", votos=votos,
        )
        curadoria.append({"votacao": vid, "tema": tema, "titulo": titulo, "resumo": resumo, "sim_significa": sim_sig})
    return exportar(curadoria, obter=lambda vid, cfg=None: votacoes.get(vid), demo=True)


def resumo_temas(curadoria: list[dict]) -> Counter:
    return Counter(p.get("tema", "sem tema") for p in curadoria)
