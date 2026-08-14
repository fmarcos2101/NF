"""Modelos do sistema: configurações, clientes, produtos e notas fiscais."""
import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class Configuracao(Base):
    """Armazenamento chave-valor para dados do emitente, SMTP e provedor."""

    __tablename__ = "configuracoes"

    chave: Mapped[str] = mapped_column(String(80), primary_key=True)
    valor: Mapped[str] = mapped_column(Text, default="")


class Cliente(Base):
    __tablename__ = "clientes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tipo: Mapped[str] = mapped_column(String(2), default="PF")  # PF ou PJ
    nome: Mapped[str] = mapped_column(String(120))
    cpf_cnpj: Mapped[str] = mapped_column(String(18), default="")
    ie: Mapped[str] = mapped_column(String(20), default="")
    email: Mapped[str] = mapped_column(String(120), default="")
    whatsapp: Mapped[str] = mapped_column(String(20), default="")
    logradouro: Mapped[str] = mapped_column(String(120), default="")
    numero: Mapped[str] = mapped_column(String(20), default="")
    complemento: Mapped[str] = mapped_column(String(60), default="")
    bairro: Mapped[str] = mapped_column(String(60), default="")
    municipio: Mapped[str] = mapped_column(String(60), default="")
    uf: Mapped[str] = mapped_column(String(2), default="")
    cep: Mapped[str] = mapped_column(String(10), default="")
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    notas: Mapped[list["Nota"]] = relationship(back_populates="cliente")


class Produto(Base):
    __tablename__ = "produtos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    codigo: Mapped[str] = mapped_column(String(30), default="")
    descricao: Mapped[str] = mapped_column(String(200))
    ncm: Mapped[str] = mapped_column(String(8), default="00000000")
    cfop: Mapped[str] = mapped_column(String(4), default="5102")
    csosn: Mapped[str] = mapped_column(String(4), default="102")
    unidade: Mapped[str] = mapped_column(String(6), default="UN")
    preco: Mapped[float] = mapped_column(Float, default=0.0)
    ativo: Mapped[int] = mapped_column(Integer, default=1)
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class StatusNota(str, enum.Enum):
    RASCUNHO = "RASCUNHO"
    PENDENTE = "PENDENTE"        # na fila, aguardando internet/emissão
    PROCESSANDO = "PROCESSANDO"  # sendo transmitida agora
    AUTORIZADA = "AUTORIZADA"
    REJEITADA = "REJEITADA"
    CANCELADA = "CANCELADA"


class Nota(Base):
    __tablename__ = "notas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    numero: Mapped[int] = mapped_column(Integer, default=0)
    serie: Mapped[int] = mapped_column(Integer, default=1)
    cliente_id: Mapped[int] = mapped_column(ForeignKey("clientes.id"))
    status: Mapped[StatusNota] = mapped_column(
        Enum(StatusNota), default=StatusNota.RASCUNHO
    )
    total: Mapped[float] = mapped_column(Float, default=0.0)
    desconto: Mapped[float] = mapped_column(Float, default=0.0)
    observacoes: Mapped[str] = mapped_column(Text, default="")

    # Resultado da emissão
    chave_acesso: Mapped[str] = mapped_column(String(44), default="")
    protocolo: Mapped[str] = mapped_column(String(30), default="")
    motivo_rejeicao: Mapped[str] = mapped_column(Text, default="")
    tentativas: Mapped[int] = mapped_column(Integer, default=0)
    ultimo_erro: Mapped[str] = mapped_column(Text, default="")
    xml_path: Mapped[str] = mapped_column(String(255), default="")
    pdf_path: Mapped[str] = mapped_column(String(255), default="")

    criado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    autorizada_em: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    email_enviado_em: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    cliente: Mapped["Cliente"] = relationship(back_populates="notas")
    itens: Mapped[list["NotaItem"]] = relationship(
        back_populates="nota", cascade="all, delete-orphan"
    )


class NotaItem(Base):
    __tablename__ = "nota_itens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nota_id: Mapped[int] = mapped_column(ForeignKey("notas.id"))
    produto_id: Mapped[int | None] = mapped_column(
        ForeignKey("produtos.id"), nullable=True
    )
    # Snapshot dos dados do produto no momento da emissão
    descricao: Mapped[str] = mapped_column(String(200))
    ncm: Mapped[str] = mapped_column(String(8), default="00000000")
    cfop: Mapped[str] = mapped_column(String(4), default="5102")
    unidade: Mapped[str] = mapped_column(String(6), default="UN")
    quantidade: Mapped[float] = mapped_column(Float, default=1.0)
    preco_unitario: Mapped[float] = mapped_column(Float, default=0.0)
    total: Mapped[float] = mapped_column(Float, default=0.0)

    nota: Mapped["Nota"] = relationship(back_populates="itens")
