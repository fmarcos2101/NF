from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import NotaItem, Produto
from ..schemas import ProdutoIn, ProdutoOut

router = APIRouter(prefix="/api/produtos", tags=["produtos"])


@router.get("", response_model=list[ProdutoOut])
def listar(busca: str = "", incluir_inativos: bool = False, db: Session = Depends(get_db)):
    consulta = db.query(Produto).order_by(Produto.descricao)
    if not incluir_inativos:
        consulta = consulta.filter(Produto.ativo == 1)
    if busca:
        filtro = f"%{busca}%"
        consulta = consulta.filter(
            Produto.descricao.ilike(filtro) | Produto.codigo.ilike(filtro)
        )
    return consulta.all()


@router.post("", response_model=ProdutoOut, status_code=201)
def criar(dados: ProdutoIn, db: Session = Depends(get_db)):
    produto = Produto(**dados.model_dump())
    db.add(produto)
    db.commit()
    return produto


@router.put("/{produto_id}", response_model=ProdutoOut)
def atualizar(produto_id: int, dados: ProdutoIn, db: Session = Depends(get_db)):
    produto = db.get(Produto, produto_id)
    if produto is None:
        raise HTTPException(404, "Produto não encontrado")
    for campo, valor in dados.model_dump().items():
        setattr(produto, campo, valor)
    db.commit()
    return produto


@router.delete("/{produto_id}", status_code=204)
def excluir(produto_id: int, db: Session = Depends(get_db)):
    produto = db.get(Produto, produto_id)
    if produto is None:
        raise HTTPException(404, "Produto não encontrado")
    if db.query(NotaItem).filter(NotaItem.produto_id == produto_id).first():
        # Já foi usado em notas: apenas desativa, preservando o histórico
        produto.ativo = 0
        db.commit()
        return
    db.delete(produto)
    db.commit()
