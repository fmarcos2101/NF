from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..database import BACKUP_DIR, get_db
from ..models import Cliente, Inutilizacao, Nota, NotaEvento, Produto, StatusEvento, StatusInutilizacao, StatusNota
from ..services import auth
from ..services import backup as svc_backup
from ..services import config as cfg
from ..services.documentos import validar_cpf_cnpj
from ..services.fila import esta_online

router = APIRouter(prefix="/api", tags=["configuracoes"])


@router.get("/configuracoes")
def obter(db: Session = Depends(get_db)):
    valores = cfg.obter_todas(db)
    for chave in ("smtp_senha", "focus_nfe_token", "whatsapp_token"):
        if valores.get(chave):
            valores[chave] = "********"
    valores.pop("auth_senha_hash", None)
    valores.pop("auth_sessao_versao", None)
    valores["auth_configurada"] = bool(cfg.obter(db, "auth_senha_hash"))
    return valores


@router.put("/configuracoes")
def gravar(valores: dict[str, str], request: Request, db: Session = Depends(get_db)):
    for chave in ("smtp_senha", "focus_nfe_token", "whatsapp_token"):
        if valores.get(chave) == "********":
            valores.pop(chave)
    valores.pop("auth_senha_hash", None)
    valores.pop("auth_sessao_versao", None)
    nova = (valores.pop("auth_senha_nova", None) or "").strip()
    atual = valores.pop("auth_senha_atual", None) or ""
    cnpj = valores.get("emitente_cnpj")
    if cnpj is not None:
        try:
            valores["emitente_cnpj"] = validar_cpf_cnpj(cnpj)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    # Tudo é validado ANTES de gravar qualquer coisa: se a troca de senha
    # falhar, nenhuma outra configuração é aplicada.
    if nova:
        try:
            if len(nova) < 6:
                raise ValueError("A senha deve ter no mínimo 6 caracteres.")
            auth.validar_senha_atual(db, atual)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    cfg.gravar(db, valores)
    if nova:
        auth.definir_senha(db, nova, atual)
        if request.session.get("usuario"):
            request.session["versao"] = auth.sessao_versao(db)
    return {"ok": True}


@router.get("/status")
def status(request: Request, db: Session = Depends(get_db)):
    contagem = {
        s.value.lower(): db.query(Nota).filter(Nota.status == s).count()
        for s in StatusNota
    }
    eventos_pendentes = (
        db.query(NotaEvento)
        .filter(NotaEvento.status.in_((StatusEvento.PENDENTE, StatusEvento.PROCESSANDO)))
        .count()
    )
    inutilizacoes_pendentes = (
        db.query(Inutilizacao)
        .filter(Inutilizacao.status.in_((StatusInutilizacao.PENDENTE, StatusInutilizacao.PROCESSANDO)))
        .count()
    )
    recente = svc_backup.ultimo()
    return {
        "online": esta_online(),
        "notas": contagem,
        "eventos_pendentes": eventos_pendentes,
        "inutilizacoes_pendentes": inutilizacoes_pendentes,
        "clientes": db.query(Cliente).count(),
        "produtos": db.query(Produto).filter(Produto.ativo == 1).count(),
        "provedor": cfg.obter(db, "emissao_provedor"),
        "ambiente": cfg.obter(db, "emissao_ambiente"),
        "ultimo_backup": recente.name if recente else None,
        "nfce_autorizadas": db.query(Nota).filter(Nota.modelo == 65, Nota.status == StatusNota.AUTORIZADA).count(),
        "auth_ativa": auth.auth_ativa(db),
        "usuario": request.session.get("usuario") or "",
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
