from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Cliente, Nota, Produto, StatusNota
from ..services import config as cfg
from ..services.fila import esta_online

router = APIRouter(prefix="/api", tags=["configuracoes"])


@router.get("/configuracoes")
def obter(db: Session = Depends(get_db)):
    valores = cfg.obter_todas(db)
    if valores.get("smtp_senha"):
        valores["smtp_senha"] = "********"
    if valores.get("focus_nfe_token"):
        valores["focus_nfe_token"] = "********"
    return valores


@router.put("/configuracoes")
def gravar(valores: dict[str, str], db: Session = Depends(get_db)):
    # Não sobrescreve segredos com o placeholder de exibição
    for chave in ("smtp_senha", "focus_nfe_token"):
        if valores.get(chave) == "********":
            valores.pop(chave)
    cfg.gravar(db, valores)
    return {"ok": True}


@router.get("/status")
def status(db: Session = Depends(get_db)):
    contagem = {
        s.value.lower(): db.query(Nota).filter(Nota.status == s).count()
        for s in StatusNota
    }
    return {
        "online": esta_online(),
        "notas": contagem,
        "clientes": db.query(Cliente).count(),
        "produtos": db.query(Produto).filter(Produto.ativo == 1).count(),
        "provedor": cfg.obter(db, "emissao_provedor"),
        "ambiente": cfg.obter(db, "emissao_ambiente"),
    }
