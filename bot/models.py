"""Modelo único para votações da Câmara e do Senado.

Os coletores convertem o formato de cada API para estas classes, e o resto
do bot (seleção, texto, imagens, publicação) só conhece este formato.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from typing import Optional

# Votos normalizados
SIM = "Sim"
NAO = "Não"
ABSTENCAO = "Abstenção"
OBSTRUCAO = "Obstrução"
OUTRO = "Outro"


# Votações que exigem quórum qualificado (Constituição, arts. 60 e 69):
# (casa, tipo) -> (votos SIM necessários, explicação)
QUORUM = {
    ("camara", "PEC"): (308, "3/5 dos deputados"),
    ("senado", "PEC"): (49, "3/5 dos senadores"),
    ("camara", "PLP"): (257, "maioria absoluta dos deputados"),
    ("senado", "PLP"): (41, "maioria absoluta dos senadores"),
}
# Votações procedimentais dentro de uma PEC/PLP seguem outra regra: sem quórum no post.
_FORA_DO_QUORUM = ("destaque", "requerimento", "adiamento", "retirada", "encerramento", "preferencia")


def _sem_acento(s: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", (s or "").lower()) if unicodedata.category(c) != "Mn")


def totais_do_texto(texto: str) -> dict[str, int]:
    """Placar oficial escrito no texto da Casa: "Sim: 368; Não: 96; Abstenção: 7" (Câmara)
    ou "Sim - 58, Não - 1" (Senado). Vazio se o texto tiver mais de um placar."""
    t = _sem_acento(texto)
    saida = {}
    for chave, rotulo in ((SIM, "sim"), (NAO, "nao"), (ABSTENCAO, "abstenc(?:ao|oes)")):
        achados = re.findall(rf"\b{rotulo}\s*[:\-–]\s*(\d+)", t)
        if len(achados) > 1:
            return {}
        if achados:
            saida[chave] = int(achados[0])
    return saida


def normalizar_voto(valor: str) -> str:
    v = (valor or "").strip().lower()
    if v in {"sim", "s"}:
        return SIM
    if v in {"não", "nao", "n"}:
        return NAO
    if v.startswith("absten"):
        return ABSTENCAO
    if v.startswith("obstru"):
        return OBSTRUCAO
    return OUTRO


@dataclass
class Voto:
    nome: str
    partido: str
    uf: str
    voto: str  # um dos valores normalizados acima
    voto_original: str = ""
    id: str = ""  # id do parlamentar na API (deputado_.id / codigoParlamentar)


@dataclass
class Votacao:
    id: str
    casa: str  # "camara" | "senado"
    data: str  # AAAA-MM-DD
    proposicao: str  # ex.: "PL 1234/2026"
    tipo_proposicao: str  # ex.: "PL", "PEC"
    ementa: str
    descricao: str  # o que exatamente foi votado (texto-base, destaque...)
    aprovada: Optional[bool]
    url_fonte: str
    votos: list[Voto] = field(default_factory=list)
    # partido/bloco -> "Sim" | "Não" | "Liberado" | ...
    orientacoes: dict[str, str] = field(default_factory=dict)
    orientacao_governo: Optional[str] = None
    secreta: bool = False
    # totais que a própria API informa (o Senado manda), para conferir a contagem voto a voto
    totais_oficiais: dict[str, int] = field(default_factory=dict)
    # nome pelo qual o projeto é conhecido ("Fim da escala 6x1") e de onde ele veio
    apelido: str = ""
    fonte_apelido: str = ""

    # ---------- números ----------
    def placar(self) -> dict[str, int]:
        c = Counter(v.voto for v in self.votos)
        return {k: c.get(k, 0) for k in (SIM, NAO, ABSTENCAO, OBSTRUCAO, OUTRO)}

    def por_partido(self) -> list[dict]:
        """Lista de partidos ordenada por bancada, com contagem de cada voto."""
        grupos: dict[str, Counter] = defaultdict(Counter)
        for v in self.votos:
            grupos[v.partido or "S/Partido"][v.voto] += 1
        linhas = []
        for partido, c in grupos.items():
            total = sum(c.values())
            linhas.append({
                "partido": partido,
                "total": total,
                "sim": c.get(SIM, 0),
                "nao": c.get(NAO, 0),
                "outros": total - c.get(SIM, 0) - c.get(NAO, 0),
                "orientacao": self.orientacao_do_partido(partido),
            })
        linhas.sort(key=lambda l: (-l["total"], l["partido"]))
        return linhas

    def orientacao_do_partido(self, partido: str) -> Optional[str]:
        """Procura a orientação do partido (pode estar dentro de um bloco)."""
        if not partido:
            return None
        p = partido.lower()
        for chave, ori in self.orientacoes.items():
            # a Câmara manda federações como "Fdr PT-PCdoB-PV" e blocos como "Bl UniPpPsd..."
            limpa = re.sub(r"^(fdr|bl)\.?\s+", "", chave.strip(), flags=re.I)
            nomes = [n.strip().lower() for n in re.split(r"[/,\-]", limpa)]
            if p in nomes or chave.lower() == p:
                return ori
        return None

    def quorum(self) -> tuple[int, str] | None:
        """(votos SIM necessários, explicação) quando a votação exige quórum qualificado."""
        q = QUORUM.get((self.casa, self.tipo_proposicao))
        if not q or any(t in _sem_acento(self.descricao) for t in _FORA_DO_QUORUM):
            return None
        return q

    def dissidentes(self) -> list[Voto]:
        """Parlamentares que votaram Sim/Não contra a orientação do próprio partido."""
        saida = []
        for v in self.votos:
            ori = normalizar_voto(self.orientacao_do_partido(v.partido) or "")
            if ori in (SIM, NAO) and v.voto in (SIM, NAO) and v.voto != ori:
                saida.append(v)
        return saida

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Votacao":
        d = dict(d)
        d["votos"] = [Voto(**v) for v in d.get("votos", [])]
        return cls(**d)
