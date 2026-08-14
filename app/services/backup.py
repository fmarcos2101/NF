"""Backup automático do banco SQLite e dos XMLs/PDFs das notas."""
import logging
import sqlite3
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

from ..database import BACKUP_DIR, DB_PATH, ARQUIVOS_DIR

log = logging.getLogger("nf.backup")

RETENCAO = 14  # quantos arquivos zip manter
INTERVALO_HORAS = 24


def listar() -> list[dict]:
    arquivos = sorted(BACKUP_DIR.glob("nf-backup-*.zip"), reverse=True)
    return [
        {
            "nome": arq.name,
            "tamanho": arq.stat().st_size,
            "criado_em": datetime.fromtimestamp(arq.stat().st_mtime).isoformat(),
        }
        for arq in arquivos
    ]


def ultimo() -> Path | None:
    arquivos = sorted(BACKUP_DIR.glob("nf-backup-*.zip"), reverse=True)
    return arquivos[0] if arquivos else None


def precisa_backup(intervalo_horas: int = INTERVALO_HORAS) -> bool:
    recente = ultimo()
    if recente is None:
        return True
    idade = datetime.now() - datetime.fromtimestamp(recente.stat().st_mtime)
    return idade >= timedelta(hours=intervalo_horas)


def criar() -> Path:
    """Copia o banco (via API de backup do SQLite) e os arquivos fiscais para um ZIP."""
    import uuid

    BACKUP_DIR.mkdir(exist_ok=True)
    # Sufixo aleatório: dois backups no mesmo segundo não colidem nem se sobrescrevem.
    sufixo = uuid.uuid4().hex[:6]
    nome = f"nf-backup-{datetime.now():%Y%m%d-%H%M%S}-{sufixo}.zip"
    destino = BACKUP_DIR / nome
    db_tmp = BACKUP_DIR / f".tmp-{nome}.db"

    origem = sqlite3.connect(str(DB_PATH))
    try:
        copia = sqlite3.connect(str(db_tmp))
        try:
            origem.backup(copia)
        finally:
            copia.close()
    finally:
        origem.close()

    with zipfile.ZipFile(destino, "w", compression=zipfile.ZIP_DEFLATED) as zipf:
        zipf.write(db_tmp, arcname="nf.db")
        if ARQUIVOS_DIR.exists():
            for arquivo in ARQUIVOS_DIR.rglob("*"):
                if arquivo.is_file():
                    zipf.write(arquivo, arcname=f"arquivos/{arquivo.relative_to(ARQUIVOS_DIR)}")
    db_tmp.unlink(missing_ok=True)
    _expurgar()
    log.info("Backup criado: %s (%s bytes)", destino.name, destino.stat().st_size)
    return destino


def talvez_criar() -> Path | None:
    if not precisa_backup():
        return None
    try:
        return criar()
    except Exception:
        log.exception("Falha ao gerar backup automático")
        return None


def _expurgar() -> None:
    arquivos = sorted(BACKUP_DIR.glob("nf-backup-*.zip"), reverse=True)
    for antigo in arquivos[RETENCAO:]:
        antigo.unlink(missing_ok=True)
