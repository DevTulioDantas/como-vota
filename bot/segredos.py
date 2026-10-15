"""Proteção de segredos nos logs do GitHub Actions (que são públicos num repositório público)."""
from __future__ import annotations

import os


def mascarar(valor: str) -> None:
    """Pede ao GitHub Actions para esconder (***) este valor em todo log daqui em diante.
    Necessário para tokens renovados durante a execução: só os secrets de origem são escondidos sozinhos."""
    if valor and os.getenv("GITHUB_ACTIONS") == "true":
        print(f"::add-mask::{valor}", flush=True)
