from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Inutilizacao, StatusInutilizacao
from ..schemas import InutilizacaoIn, InutilizacaoOut
from ..services.contabilidade import montar_zip_xml
from ..services.fila import processar_fila

router = APIRouter(prefix="/api", tags=["contabilidade"])

TEXTO_MINIMO = 15


@router.get("/contabilidade/xml")
def baixar_xml_mes(ano: int, mes: int, db: Session = Depends(get_db)):
    if mes < 1 or mes > 12 or ano < 2000 or ano > 2100:
        raise HTTPException(400, "Informe um ano e um mês válidos.")
    conteudo, quantidade = montar_zip_xml(db, ano, mes)
    if quantidade == 0:
        raise HTTPException(404, "Nenhum XML autorizado neste mês.")
    nome = f"xml-{ano:04d}-{mes:02d}.zip"
    return Response(
        content=conteudo,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{nome}"'},
    )


@router.get("/inutilizacoes", response_model=list[InutilizacaoOut])
def listar_inutilizacoes(db: Session = Depends(get_db)):
    return db.query(Inutilizacao).order_by(Inutilizacao.id.desc()).all()


@router.post("/inutilizacoes", response_model=InutilizacaoOut, status_code=201)
def criar_inutilizacao(dados: InutilizacaoIn, db: Session = Depends(get_db)):
    modelo = 65 if dados.modelo == 65 else 55
    if dados.numero_final < dados.numero_inicial:
        raise HTTPException(400, "O número final deve ser maior ou igual ao inicial.")
    texto = dados.justificativa.strip()
    if len(texto) < TEXTO_MINIMO:
        raise HTTPException(400, "A justificativa deve ter no mínimo 15 caracteres (exigência da SEFAZ).")
    ano = dados.ano or datetime.now().year
    item = Inutilizacao(
        modelo=modelo,
        serie=dados.serie,
        ano=ano,
        numero_inicial=dados.numero_inicial,
        numero_final=dados.numero_final,
        justificativa=texto,
        status=StatusInutilizacao.PENDENTE,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("/inutilizacoes/{item_id}/xml")
def baixar_xml_inutilizacao(item_id: int, db: Session = Depends(get_db)):
    item = db.get(Inutilizacao, item_id)
    if item is None or not item.xml_path or not Path(item.xml_path).exists():
        raise HTTPException(404, "XML da inutilização ainda não disponível.")
    return FileResponse(
        item.xml_path,
        media_type="application/xml",
        filename=f"inut-{item.modelo}-{item.serie}-{item.numero_inicial}-{item.numero_final}.xml",
    )


@router.post("/inutilizacoes/processar-fila")
def processar_inutilizacoes():
    resultado = processar_fila()
    return resultado
