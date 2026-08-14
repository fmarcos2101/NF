"""Autenticação local: um usuário, senha com PBKDF2, sessão em cookie."""
import hashlib
import hmac
import os
import secrets

from sqlalchemy.orm import Session

from ..database import DATA_DIR
from . import config as cfg

ITERACOES = 120_000


def hash_senha(senha: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    derivado = hashlib.pbkdf2_hmac("sha256", senha.encode(), salt.encode(), ITERACOES)
    return f"{salt}${derivado.hex()}"


def verificar_senha(senha: str, armazenado: str) -> bool:
    if not armazenado or "$" not in armazenado:
        return False
    salt, _ = armazenado.split("$", 1)
    return hmac.compare_digest(hash_senha(senha, salt), armazenado)


def auth_ativa(db: Session) -> bool:
    if os.environ.get("NF_AUTH_DISABLED") == "1":
        return False
    return bool(cfg.obter(db, "auth_senha_hash"))


def autenticar(db: Session, usuario: str, senha: str) -> bool:
    esperado = cfg.obter(db, "auth_usuario") or "admin"
    if usuario != esperado:
        return False
    return verificar_senha(senha, cfg.obter(db, "auth_senha_hash"))


def sessao_versao(db: Session) -> str:
    return cfg.obter(db, "auth_sessao_versao") or "1"


def _invalidar_sessoes(db: Session) -> dict[str, str]:
    versao = int(sessao_versao(db)) + 1
    return {"auth_sessao_versao": str(versao)}


def validar_senha_atual(db: Session, atual: str) -> None:
    """Confere a senha atual sem gravar nada (para validar antes de salvar)."""
    hash_atual = cfg.obter(db, "auth_senha_hash")
    if hash_atual and not verificar_senha(atual, hash_atual):
        raise ValueError("Senha atual incorreta.")


def definir_senha(db: Session, nova: str, atual: str = "") -> None:
    if len(nova) < 6:
        raise ValueError("A senha deve ter no mínimo 6 caracteres.")
    validar_senha_atual(db, atual)
    # Sessões abertas antes da troca deixam de valer.
    cfg.gravar(db, {"auth_senha_hash": hash_senha(nova), **_invalidar_sessoes(db)})


def remover_senha(db: Session) -> None:
    cfg.gravar(db, {"auth_senha_hash": "", **_invalidar_sessoes(db)})


def chave_sessao() -> str:
    caminho = DATA_DIR / "session.key"
    if caminho.exists():
        return caminho.read_text(encoding="utf-8").strip()
    chave = secrets.token_hex(32)
    caminho.write_text(chave, encoding="utf-8")
    return chave
