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
    qrcode_url: str = ""


@dataclass
class ResultadoEvento:
    autorizado: bool
    protocolo: str = ""
    motivo: str = ""
    xml: str = ""
    sequencia: int = 0


class ErroComunicacao(Exception):
    """Falha de rede/temporária — a nota volta para a fila e será retentada."""


class EmissorBase(ABC):
    @abstractmethod
    def emitir(self, nota: Nota, emitente: dict[str, str]) -> ResultadoEmissao:
        """Transmite a nota. Levanta ErroComunicacao em falha de rede."""

    @abstractmethod
    def cancelar(self, nota: Nota, justificativa: str) -> ResultadoEvento:
        """Cancela uma nota autorizada. Levanta ErroComunicacao em falha de rede."""

    @abstractmethod
    def carta_correcao(self, nota: Nota, texto: str) -> ResultadoEvento:
        """Registra carta de correção. Levanta ErroComunicacao em falha de rede."""
