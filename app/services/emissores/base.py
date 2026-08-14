from abc import ABC, abstractmethod
from dataclasses import dataclass

from ...models import Nota


@dataclass
class ResultadoEmissao:
    autorizada: bool
    chave_acesso: str = ""
    protocolo: str = ""
    motivo: str = ""       # motivo da rejeição, quando houver
    xml: str = ""          # XML autorizado (quando disponível)


class ErroComunicacao(Exception):
    """Falha de rede/temporária — a nota volta para a fila e será retentada."""


class EmissorBase(ABC):
    @abstractmethod
    def emitir(self, nota: Nota, emitente: dict[str, str]) -> ResultadoEmissao:
        """Transmite a nota. Levanta ErroComunicacao em falha de rede."""
