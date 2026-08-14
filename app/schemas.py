"""Schemas de entrada/saída da API."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ClienteIn(BaseModel):
    tipo: str = "PF"
    nome: str
    cpf_cnpj: str = ""
    ie: str = ""
    email: str = ""
    whatsapp: str = ""
    logradouro: str = ""
    numero: str = ""
    complemento: str = ""
    bairro: str = ""
    municipio: str = ""
    uf: str = ""
    cep: str = ""


class ClienteOut(ClienteIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class ProdutoIn(BaseModel):
    codigo: str = ""
    descricao: str
    ncm: str = "00000000"
    cfop: str = "5102"
    csosn: str = "102"
    unidade: str = "UN"
    preco: float = 0.0
    ativo: int = 1


class ProdutoOut(ProdutoIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class ItemIn(BaseModel):
    produto_id: int
    quantidade: float = 1.0
    preco_unitario: float | None = None  # se None, usa o preço do cadastro


class NotaIn(BaseModel):
    cliente_id: int
    itens: list[ItemIn] = Field(min_length=1)
    desconto: float = 0.0
    observacoes: str = ""
    emitir_agora: bool = True  # False = salva como rascunho


class ItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    descricao: str
    ncm: str
    cfop: str
    unidade: str
    quantidade: float
    preco_unitario: float
    total: float


class NotaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    numero: int
    serie: int
    cliente_id: int
    status: str
    total: float
    desconto: float
    observacoes: str
    chave_acesso: str
    protocolo: str
    motivo_rejeicao: str
    tentativas: int
    ultimo_erro: str
    criado_em: datetime
    autorizada_em: datetime | None
    email_enviado_em: datetime | None
    cancelada_em: datetime | None = None
    justificativa_cancelamento: str = ""
    itens: list[ItemOut] = []
    cliente: ClienteOut | None = None
    eventos: list["EventoOut"] = []


class EventoIn(BaseModel):
    texto: str = Field(min_length=15, max_length=1000)


class EventoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    tipo: str
    status: str
    texto: str
    sequencia: int
    protocolo: str
    xml_path: str = ""
    tentativas: int
    ultimo_erro: str
    motivo_rejeicao: str
    criado_em: datetime
    processado_em: datetime | None


NotaOut.model_rebuild()
