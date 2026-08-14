"""Banco de dados local (SQLite) — funciona 100% off-line."""
import os
from pathlib import Path

from sqlalchemy import create_engine, text
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


class Base(DeclarativeBase):
    pass


def garantir_schema() -> None:
    """Cria tabelas novas e adiciona colunas em bancos já existentes."""
    Base.metadata.create_all(bind=engine)
    alteracoes = {
        "notas": {
            "cancelada_em": "DATETIME",
            "justificativa_cancelamento": "TEXT DEFAULT ''",
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


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
