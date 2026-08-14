from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas import LoginIn, SenhaIn
from ..services import auth

router = APIRouter(prefix="/api", tags=["acesso"])


@router.post("/login")
def login(dados: LoginIn, request: Request, db: Session = Depends(get_db)):
    if not auth.autenticar(db, dados.usuario, dados.senha):
        raise HTTPException(401, "Usuário ou senha inválidos.")
    request.session["usuario"] = dados.usuario
    request.session["versao"] = auth.sessao_versao(db)
    return {"ok": True, "usuario": dados.usuario}


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@router.post("/senha")
def alterar_senha(dados: SenhaIn, request: Request, db: Session = Depends(get_db)):
    try:
        auth.definir_senha(db, dados.nova, dados.atual)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    # A sessão de quem trocou a senha continua valendo; as demais caem.
    if request.session.get("usuario"):
        request.session["versao"] = auth.sessao_versao(db)
    return {"ok": True}
