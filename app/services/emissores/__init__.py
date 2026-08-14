"""Provedores de emissão de NF-e.

O sistema conversa com um "emissor" através de uma interface única
(`EmissorBase`), o que permite trocar de provedor sem mexer no resto
do código. Provedores disponíveis:

- ``simulado``: autoriza localmente, para desenvolvimento/demonstração.
- ``focus_nfe``: emissão real via API da Focus NFe (requer token).
"""
from sqlalchemy.orm import Session

from .. import config as cfg
from .base import EmissorBase, ResultadoEmissao
from .focus_nfe import EmissorFocusNFe
from .simulado import EmissorSimulado

__all__ = ["EmissorBase", "ResultadoEmissao", "obter_emissor"]


def obter_emissor(db: Session) -> EmissorBase:
    provedor = cfg.obter(db, "emissao_provedor")
    if provedor == "focus_nfe":
        return EmissorFocusNFe(
            token=cfg.obter(db, "focus_nfe_token"),
            ambiente=cfg.obter(db, "emissao_ambiente"),
        )
    return EmissorSimulado()
