"""Schemas de entrada/saída da API, com validação dos campos fiscais."""
import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

UFS = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS",
    "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC",
    "SP", "SE", "TO",
}

CSOSN_VALIDOS = {
    "101", "102", "103", "201", "202", "203", "300", "400", "500", "900",
}

FORMAS_PAGAMENTO = {
    "01", "02", "03", "04", "05", "10", "11", "13", "15", "16", "17", "18",
    "19", "90", "99",
}

RE_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


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

    @field_validator("tipo")
    @classmethod
    def _tipo(cls, v: str) -> str:
        v = (v or "").strip().upper()
        if v not in ("PF", "PJ"):
            raise ValueError("Tipo deve ser PF ou PJ.")
        return v

    @field_validator("nome")
    @classmethod
    def _nome(cls, v: str) -> str:
        v = (v or "").strip()
        if len(v) < 2:
            raise ValueError("Informe o nome do cliente (mínimo 2 caracteres).")
        return v

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = (v or "").strip()
        if v and not RE_EMAIL.match(v):
            raise ValueError("E-mail inválido.")
        return v

    @field_validator("uf")
    @classmethod
    def _uf(cls, v: str) -> str:
        v = (v or "").strip().upper()
        if v and v not in UFS:
            raise ValueError("UF inválida.")
        return v

    @field_validator("cep")
    @classmethod
    def _cep(cls, v: str) -> str:
        digitos = "".join(c for c in (v or "") if c.isdigit())
        if digitos and len(digitos) != 8:
            raise ValueError("CEP deve ter 8 dígitos.")
        return digitos


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
    preco: float = Field(default=0.0, ge=0)
    ativo: int = 1

    @field_validator("descricao")
    @classmethod
    def _descricao(cls, v: str) -> str:
        v = (v or "").strip()
        if len(v) < 2:
            raise ValueError("Informe a descrição do produto (mínimo 2 caracteres).")
        return v

    @field_validator("ncm")
    @classmethod
    def _ncm(cls, v: str) -> str:
        digitos = "".join(c for c in (v or "") if c.isdigit())
        if len(digitos) != 8:
            raise ValueError("NCM deve ter 8 dígitos.")
        return digitos

    @field_validator("cfop")
    @classmethod
    def _cfop(cls, v: str) -> str:
        digitos = "".join(c for c in (v or "") if c.isdigit())
        if len(digitos) != 4 or digitos[0] not in "123567":
            raise ValueError("CFOP deve ter 4 dígitos válidos (ex.: 5102).")
        return digitos

    @field_validator("csosn")
    @classmethod
    def _csosn(cls, v: str) -> str:
        v = "".join(c for c in (v or "") if c.isdigit())
        if v not in CSOSN_VALIDOS:
            raise ValueError(
                "CSOSN inválido. Use um dos códigos do Simples Nacional (ex.: 102, 500)."
            )
        return v

    @field_validator("unidade")
    @classmethod
    def _unidade(cls, v: str) -> str:
        v = (v or "").strip().upper()
        if not v:
            raise ValueError("Informe a unidade (ex.: UN, KG).")
        return v


class ProdutoOut(ProdutoIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class ItemIn(BaseModel):
    produto_id: int
    quantidade: float = Field(default=1.0, gt=0)
    preco_unitario: float | None = Field(default=None, ge=0)  # None = preço do cadastro


class NotaIn(BaseModel):
    cliente_id: int | None = None
    itens: list[ItemIn] = Field(min_length=1)
    desconto: float = Field(default=0.0, ge=0)
    observacoes: str = ""
    emitir_agora: bool = True  # False = salva como rascunho
    modelo: int = 55  # 55 NF-e, 65 NFC-e
    consumidor_cpf: str = ""
    forma_pagamento: str = "01"

    @field_validator("forma_pagamento")
    @classmethod
    def _forma(cls, v: str) -> str:
        v = (v or "01").strip()
        if v not in FORMAS_PAGAMENTO:
            raise ValueError("Forma de pagamento inválida.")
        return v


class ItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    descricao: str
    ncm: str
    cfop: str
    csosn: str = "102"
    unidade: str
    quantidade: float
    preco_unitario: float
    total: float


class NotaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    numero: int
    serie: int
    cliente_id: int | None
    status: str
    total: float
    desconto: float
    observacoes: str
    modelo: int = 55
    consumidor_cpf: str = ""
    forma_pagamento: str = "01"
    qrcode_url: str = ""
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


class InutilizacaoIn(BaseModel):
    modelo: int = 55
    serie: int = Field(default=1, ge=1)
    numero_inicial: int = Field(ge=1)
    numero_final: int = Field(ge=1)
    justificativa: str = Field(min_length=15, max_length=255)
    ano: int | None = None


class InutilizacaoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    modelo: int
    serie: int
    ano: int
    numero_inicial: int
    numero_final: int
    justificativa: str
    status: str
    protocolo: str
    xml_path: str = ""
    tentativas: int
    ultimo_erro: str
    motivo_rejeicao: str
    criado_em: datetime
    processada_em: datetime | None


class LoginIn(BaseModel):
    usuario: str
    senha: str


class SenhaIn(BaseModel):
    nova: str = Field(min_length=6)
    atual: str = ""


NotaOut.model_rebuild()
