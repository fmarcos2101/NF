"""Banco de dados local (SQLite) — funciona 100% off-line."""
import os
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATA_DIR = Path(os.environ.get("NF_DATA_DIR", Path(__file__).resolve().parent.parent / "dados"))
DATA_DIR.mkdir(exist_ok=True)
ARQUIVOS_DIR = DATA_DIR / "arquivos"
ARQUIVOS_DIR.mkdir(exist_ok=True)
BACKUP_DIR = DATA_DIR / "backups"
BACKUP_DIR.mkdir(exist_ok=True)

DB_PATH = DATA_DIR / "nf.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@event.listens_for(engine, "connect")
def _ativar_foreign_keys(dbapi_conn, _record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


class Base(DeclarativeBase):
    pass


def garantir_schema() -> None:
    """Cria tabelas novas e adiciona colunas em bancos já existentes."""
    Base.metadata.create_all(bind=engine)
    alteracoes = {
        "notas": {
            "cancelada_em": "DATETIME",
            "justificativa_cancelamento": "TEXT DEFAULT ''",
            "modelo": "INTEGER DEFAULT 55",
            "consumidor_cpf": "TEXT DEFAULT ''",
            "forma_pagamento": "TEXT DEFAULT '01'",
            "qrcode_url": "TEXT DEFAULT ''",
            "referencia": "TEXT DEFAULT ''",
        },
        "nota_itens": {
            "csosn": "TEXT DEFAULT '102'",
        },
    }
    with engine.begin() as conn:
        for tabela, colunas in alteracoes.items():
            existentes = {
                row[1] for row in conn.execute(text(f"PRAGMA table_info({tabela})"))
            }
            for nome, definicao in colunas.items():
                if nome not in existentes:
                    conn.execute(text(f"ALTER TABLE {tabela} ADD COLUMN {nome} {definicao}"))
        # Notas antigas sem referência ganham uma baseada no próprio id.
        conn.execute(text(
            "UPDATE notas SET referencia = 'nota-' || id WHERE referencia = '' OR referencia IS NULL"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_notas_status ON notas(status)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_eventos_status ON nota_eventos(status)"
        ))
        try:
            conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_notas_numeracao "
                "ON notas(modelo, serie, numero) WHERE numero > 0"
            ))
        except Exception:
            # Banco legado pode ter numeração duplicada; o índice fica de fora
            # para não travar a subida, mas a numeração nova já é atômica.
            pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
