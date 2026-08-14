from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Cliente, Nota, NotaItem, Produto, StatusNota
from ..schemas import NotaIn, NotaOut
from ..services import config as cfg
from ..services.email_sender import enviar_nota_por_email
from ..services.fila import esta_online, processar_fila
from ..services.whatsapp import montar_link

router = APIRouter(prefix="/api/notas", tags=["notas"])


def _buscar_nota(db: Session, nota_id: int) -> Nota:
    nota = db.get(Nota, nota_id)
    if nota is None:
        raise HTTPException(404, "Nota não encontrada")
    return nota


@router.get("", response_model=list[NotaOut])
def listar(status: str = "", db: Session = Depends(get_db)):
    consulta = db.query(Nota).order_by(Nota.id.desc())
    if status:
        consulta = consulta.filter(Nota.status == status)
    return consulta.all()


@router.get("/{nota_id}", response_model=NotaOut)
def detalhar(nota_id: int, db: Session = Depends(get_db)):
    return _buscar_nota(db, nota_id)


@router.post("", response_model=NotaOut, status_code=201)
def criar(dados: NotaIn, db: Session = Depends(get_db)):
    cliente = db.get(Cliente, dados.cliente_id)
    if cliente is None:
        raise HTTPException(400, "Cliente não encontrado")

    nota = Nota(
        cliente_id=cliente.id,
        serie=int(cfg.obter(db, "nota_serie") or "1"),
        numero=cfg.proximo_numero_nota(db),
        desconto=dados.desconto,
        observacoes=dados.observacoes,
        status=StatusNota.PENDENTE if dados.emitir_agora else StatusNota.RASCUNHO,
    )

    total = 0.0
    for item_in in dados.itens:
        produto = db.get(Produto, item_in.produto_id)
        if produto is None:
            raise HTTPException(400, f"Produto {item_in.produto_id} não encontrado")
        preco = item_in.preco_unitario if item_in.preco_unitario is not None else produto.preco
        subtotal = round(preco * item_in.quantidade, 2)
        total += subtotal
        nota.itens.append(NotaItem(
            produto_id=produto.id,
            descricao=produto.descricao,
            ncm=produto.ncm,
            cfop=produto.cfop,
            unidade=produto.unidade,
            quantidade=item_in.quantidade,
            preco_unitario=preco,
            total=subtotal,
        ))

    nota.total = round(max(total - dados.desconto, 0), 2)
    db.add(nota)
    db.commit()
    return nota


@router.post("/{nota_id}/emitir", response_model=NotaOut)
def emitir(nota_id: int, db: Session = Depends(get_db)):
    """Coloca um rascunho (ou nota rejeitada corrigida) na fila de emissão."""
    nota = _buscar_nota(db, nota_id)
    if nota.status not in (StatusNota.RASCUNHO, StatusNota.REJEITADA):
        raise HTTPException(409, f"Nota com status {nota.status.value} não pode ser emitida.")
    nota.status = StatusNota.PENDENTE
    nota.motivo_rejeicao = ""
    db.commit()
    return nota


@router.delete("/{nota_id}", status_code=204)
def excluir_rascunho(nota_id: int, db: Session = Depends(get_db)):
    nota = _buscar_nota(db, nota_id)
    if nota.status not in (StatusNota.RASCUNHO, StatusNota.REJEITADA):
        raise HTTPException(409, "Somente rascunhos e notas rejeitadas podem ser excluídos.")
    db.delete(nota)
    db.commit()


@router.post("/processar-fila")
def processar_fila_agora():
    """Força uma passada na fila (o worker também roda sozinho a cada 10s)."""
    processadas = processar_fila()
    return {"processadas": processadas, "online": esta_online()}


@router.get("/{nota_id}/danfe")
def baixar_danfe(nota_id: int, db: Session = Depends(get_db)):
    nota = _buscar_nota(db, nota_id)
    if not nota.pdf_path or not Path(nota.pdf_path).exists():
        raise HTTPException(404, "DANFE ainda não gerado.")
    return FileResponse(
        nota.pdf_path, media_type="application/pdf",
        filename=f"NF-{nota.numero:09d}.pdf",
    )


@router.get("/{nota_id}/xml")
def baixar_xml(nota_id: int, db: Session = Depends(get_db)):
    nota = _buscar_nota(db, nota_id)
    if not nota.xml_path or not Path(nota.xml_path).exists():
        raise HTTPException(404, "XML ainda não disponível.")
    return FileResponse(
        nota.xml_path, media_type="application/xml",
        filename=f"NF-{nota.numero:09d}.xml",
    )


@router.post("/{nota_id}/enviar-email")
def enviar_email(nota_id: int, db: Session = Depends(get_db)):
    from datetime import datetime

    nota = _buscar_nota(db, nota_id)
    if nota.status != StatusNota.AUTORIZADA:
        raise HTTPException(409, "Somente notas autorizadas podem ser enviadas.")
    try:
        enviar_nota_por_email(nota, cfg.obter_todas(db))
    except Exception as exc:
        raise HTTPException(502, f"Falha no envio: {exc}")
    nota.email_enviado_em = datetime.now()
    db.commit()
    return {"ok": True}


@router.get("/{nota_id}/whatsapp")
def link_whatsapp(nota_id: int, db: Session = Depends(get_db)):
    nota = _buscar_nota(db, nota_id)
    if nota.status != StatusNota.AUTORIZADA:
        raise HTTPException(409, "Somente notas autorizadas podem ser enviadas.")
    return montar_link(nota, cfg.obter_todas(db))
