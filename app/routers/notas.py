from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from ..models import (
    Cliente,
    Nota,
    NotaEvento,
    NotaItem,
    Produto,
    StatusEvento,
    StatusNota,
    TipoEvento,
)
from ..schemas import EventoIn, EventoOut, NotaIn, NotaOut
from ..services import config as cfg
from ..services.email_sender import enviar_nota_por_email
from ..services.fila import esta_online, processar_fila
from ..services.whatsapp import montar_link

router = APIRouter(prefix="/api/notas", tags=["notas"])

TEXTO_MINIMO = 15


def _buscar_nota(db: Session, nota_id: int) -> Nota:
    nota = (
        db.query(Nota)
        .options(joinedload(Nota.itens), joinedload(Nota.cliente), joinedload(Nota.eventos))
        .filter(Nota.id == nota_id)
        .first()
    )
    if nota is None:
        raise HTTPException(404, "Nota não encontrada")
    return nota


def _montar_itens(db: Session, nota: Nota, itens_in) -> float:
    total = 0.0
    for item_in in itens_in:
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
    return total


@router.get("", response_model=list[NotaOut])
def listar(status: str = "", busca: str = "", db: Session = Depends(get_db)):
    consulta = (
        db.query(Nota)
        .options(joinedload(Nota.cliente), joinedload(Nota.itens), joinedload(Nota.eventos))
        .outerjoin(Cliente)
    )
    if status:
        consulta = consulta.filter(Nota.status == status)
    if busca:
        filtro = f"%{busca}%"
        condicoes = [
            Cliente.nome.ilike(filtro),
            Cliente.cpf_cnpj.ilike(filtro),
            Nota.chave_acesso.ilike(filtro),
            Nota.observacoes.ilike(filtro),
        ]
        if busca.isdigit():
            condicoes.append(Nota.numero == int(busca))
        consulta = consulta.filter(or_(*condicoes))
    vistos: set[int] = set()
    resultado: list[Nota] = []
    for nota in consulta.order_by(Nota.id.desc()).all():
        if nota.id in vistos:
            continue
        vistos.add(nota.id)
        resultado.append(nota)
    return resultado


@router.post("/processar-fila")
def processar_fila_agora():
    """Força uma passada na fila (o worker também roda sozinho a cada 10s)."""
    resultado = processar_fila()
    return {
        "processadas": resultado["notas"] + resultado["eventos"],
        "notas": resultado["notas"],
        "eventos": resultado["eventos"],
        "online": esta_online(),
    }


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
    total = _montar_itens(db, nota, dados.itens)
    nota.total = round(max(total - dados.desconto, 0), 2)
    db.add(nota)
    db.commit()
    return _buscar_nota(db, nota.id)


@router.get("/{nota_id}", response_model=NotaOut)
def detalhar(nota_id: int, db: Session = Depends(get_db)):
    return _buscar_nota(db, nota_id)


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


@router.post("/{nota_id}/duplicar", response_model=NotaOut, status_code=201)
def duplicar(nota_id: int, db: Session = Depends(get_db)):
    origem = _buscar_nota(db, nota_id)
    nova = Nota(
        cliente_id=origem.cliente_id,
        serie=int(cfg.obter(db, "nota_serie") or "1"),
        numero=cfg.proximo_numero_nota(db),
        desconto=origem.desconto,
        observacoes=origem.observacoes,
        status=StatusNota.RASCUNHO,
        total=origem.total,
    )
    for item in origem.itens:
        nova.itens.append(NotaItem(
            produto_id=item.produto_id,
            descricao=item.descricao,
            ncm=item.ncm,
            cfop=item.cfop,
            unidade=item.unidade,
            quantidade=item.quantidade,
            preco_unitario=item.preco_unitario,
            total=item.total,
        ))
    db.add(nova)
    db.commit()
    return _buscar_nota(db, nova.id)


@router.delete("/{nota_id}", status_code=204)
def excluir_rascunho(nota_id: int, db: Session = Depends(get_db)):
    nota = _buscar_nota(db, nota_id)
    if nota.status not in (StatusNota.RASCUNHO, StatusNota.REJEITADA):
        raise HTTPException(409, "Somente rascunhos e notas rejeitadas podem ser excluídos.")
    db.delete(nota)
    db.commit()


@router.post("/{nota_id}/cancelar", response_model=EventoOut, status_code=201)
def cancelar(nota_id: int, dados: EventoIn, db: Session = Depends(get_db)):
    nota = _buscar_nota(db, nota_id)
    if nota.status != StatusNota.AUTORIZADA:
        raise HTTPException(409, "Somente notas autorizadas podem ser canceladas.")
    if any(e.tipo == TipoEvento.CANCELAMENTO and e.status in (StatusEvento.PENDENTE, StatusEvento.PROCESSANDO, StatusEvento.AUTORIZADO) for e in nota.eventos):
        raise HTTPException(409, "Já existe um cancelamento em andamento ou autorizado para esta nota.")
    texto = dados.texto.strip()
    if len(texto) < TEXTO_MINIMO:
        raise HTTPException(400, "A justificativa deve ter no mínimo 15 caracteres (exigência da SEFAZ).")
    evento = NotaEvento(
        nota_id=nota.id,
        tipo=TipoEvento.CANCELAMENTO,
        status=StatusEvento.PENDENTE,
        texto=texto,
    )
    db.add(evento)
    db.commit()
    return evento


@router.post("/{nota_id}/carta-correcao", response_model=EventoOut, status_code=201)
def carta_correcao(nota_id: int, dados: EventoIn, db: Session = Depends(get_db)):
    nota = _buscar_nota(db, nota_id)
    if nota.status != StatusNota.AUTORIZADA:
        raise HTTPException(409, "Somente notas autorizadas aceitam carta de correção.")
    autorizadas = [e for e in nota.eventos if e.tipo == TipoEvento.CARTA_CORRECAO and e.status == StatusEvento.AUTORIZADO]
    if len(autorizadas) >= 20:
        raise HTTPException(409, "Limite de 20 cartas de correção atingido.")
    if any(e.tipo == TipoEvento.CARTA_CORRECAO and e.status in (StatusEvento.PENDENTE, StatusEvento.PROCESSANDO) for e in nota.eventos):
        raise HTTPException(409, "Já existe uma carta de correção na fila.")
    texto = dados.texto.strip()
    if len(texto) < TEXTO_MINIMO:
        raise HTTPException(400, "O texto da correção deve ter no mínimo 15 caracteres (exigência da SEFAZ).")
    evento = NotaEvento(
        nota_id=nota.id,
        tipo=TipoEvento.CARTA_CORRECAO,
        status=StatusEvento.PENDENTE,
        texto=texto,
        sequencia=len(autorizadas) + 1,
    )
    db.add(evento)
    db.commit()
    return evento


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


@router.get("/{nota_id}/eventos/{evento_id}/xml")
def baixar_xml_evento(nota_id: int, evento_id: int, db: Session = Depends(get_db)):
    nota = _buscar_nota(db, nota_id)
    evento = next((e for e in nota.eventos if e.id == evento_id), None)
    if evento is None or not evento.xml_path or not Path(evento.xml_path).exists():
        raise HTTPException(404, "XML do evento ainda não disponível.")
    sufixo = "canc" if evento.tipo == TipoEvento.CANCELAMENTO else "cce"
    return FileResponse(
        evento.xml_path, media_type="application/xml",
        filename=f"NF-{nota.numero:09d}-{sufixo}.xml",
    )


@router.post("/{nota_id}/enviar-email")
def enviar_email(nota_id: int, db: Session = Depends(get_db)):
    nota = _buscar_nota(db, nota_id)
    if nota.status not in (StatusNota.AUTORIZADA, StatusNota.CANCELADA):
        raise HTTPException(409, "Somente notas autorizadas ou canceladas podem ser enviadas.")
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
    if nota.status not in (StatusNota.AUTORIZADA, StatusNota.CANCELADA):
        raise HTTPException(409, "Somente notas autorizadas ou canceladas podem ser enviadas.")
    return montar_link(nota, cfg.obter_todas(db))
