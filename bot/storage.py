"""Rascunhos e estado do bot guardados em arquivos (data/), versionados no Git.

data/
  state.json                      offset do Telegram + status de cada rascunho
  drafts/<id>/meta.json           votação, textos e status
  drafts/<id>/slide_01.jpg ...    imagens do carrossel

Como o GitHub Actions faz commit da pasta data/, as imagens ficam acessíveis
por URL pública (PUBLIC_BASE_URL), que é o que a API do Instagram exige.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent / "data"
PASTA_RASCUNHOS = RAIZ / "drafts"
ARQ_ESTADO = RAIZ / "state.json"

# status possíveis: gerado -> enviado -> aprovado -> publicado | descartado | erro


def agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def carregar_estado() -> dict:
    if ARQ_ESTADO.exists():
        return json.loads(ARQ_ESTADO.read_text(encoding="utf-8"))
    return {"telegram_offset": 0, "rascunhos": {}}


def salvar_estado(estado: dict) -> None:
    RAIZ.mkdir(parents=True, exist_ok=True)
    ARQ_ESTADO.write_text(json.dumps(estado, ensure_ascii=False, indent=2), encoding="utf-8")


def pasta(rascunho_id: str) -> Path:
    return PASTA_RASCUNHOS / rascunho_id


def salvar_meta(rascunho_id: str, meta: dict) -> None:
    p = pasta(rascunho_id)
    p.mkdir(parents=True, exist_ok=True)
    (p / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def carregar_meta(rascunho_id: str) -> dict:
    return json.loads((pasta(rascunho_id) / "meta.json").read_text(encoding="utf-8"))


def imagens(rascunho_id: str) -> list[Path]:
    return sorted(pasta(rascunho_id).glob("slide_*.jpg"))


def atualizar_status(estado: dict, rascunho_id: str, status: str, **extra) -> None:
    meta = carregar_meta(rascunho_id)
    meta["status"] = status
    meta.setdefault("historico", []).append({"status": status, "em": agora(), **extra})
    meta.update(extra)
    salvar_meta(rascunho_id, meta)
    estado["rascunhos"][rascunho_id] = status


def ja_existe(votacao_id: str) -> bool:
    """Evita gerar de novo uma votação que já virou rascunho em dias anteriores."""
    return (pasta(votacao_id) / "meta.json").exists()


def proposicao_recente(casa: str, proposicao: str, dias: int = 7) -> bool:
    """True se a mesma proposição já virou rascunho (não descartado) nos últimos `dias`.

    Evita, por exemplo, postar o texto-base na terça e um destaque do mesmo
    projeto na quarta. Rascunhos descartados não contam, para que outra
    votação da proposição possa ser aproveitada.
    """
    if not PASTA_RASCUNHOS.exists() or not proposicao:
        return False
    limite = datetime.now(timezone.utc) - timedelta(days=dias)
    for arq in PASTA_RASCUNHOS.glob("*/meta.json"):
        try:
            meta = json.loads(arq.read_text(encoding="utf-8"))
            v = meta.get("votacao", {})
            if (v.get("casa") == casa and v.get("proposicao") == proposicao
                    and meta.get("status") != "descartado"
                    and datetime.fromisoformat(meta.get("criado_em", "1970-01-01T00:00:00+00:00")) >= limite):
                return True
        except (ValueError, OSError):
            continue
    return False
