from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..database import BACKUP_DIR, get_db
from ..models import Cliente, Nota, NotaEvento, Produto, StatusEvento, StatusNota
from ..services import backup as svc_backup
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
    eventos_pendentes = (
        db.query(NotaEvento)
        .filter(NotaEvento.status.in_((StatusEvento.PENDENTE, StatusEvento.PROCESSANDO)))
        .count()
    )
    recente = svc_backup.ultimo()
    return {
        "online": esta_online(),
        "notas": contagem,
        "eventos_pendentes": eventos_pendentes,
        "clientes": db.query(Cliente).count(),
        "produtos": db.query(Produto).filter(Produto.ativo == 1).count(),
        "provedor": cfg.obter(db, "emissao_provedor"),
        "ambiente": cfg.obter(db, "emissao_ambiente"),
        "ultimo_backup": recente.name if recente else None,
        "nfce_autorizadas": db.query(Nota).filter(Nota.modelo == 65, Nota.status == StatusNota.AUTORIZADA).count(),
    }


@router.get("/backups")
def listar_backups():
    return svc_backup.listar()


@router.post("/backups")
def criar_backup():
    caminho = svc_backup.criar()
    return {"nome": caminho.name, "tamanho": caminho.stat().st_size}


@router.get("/backups/{nome}")
def baixar_backup(nome: str):
    if "/" in nome or "\\" in nome or not nome.startswith("nf-backup-") or not nome.endswith(".zip"):
        raise HTTPException(400, "Nome de backup inválido.")
    caminho = BACKUP_DIR / nome
    if not caminho.exists():
        raise HTTPException(404, "Backup não encontrado.")
    return FileResponse(caminho, media_type="application/zip", filename=nome)
