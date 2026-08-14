from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Cliente, Nota
from ..schemas import ClienteIn, ClienteOut
from ..services.documentos import validar_cpf_cnpj

router = APIRouter(prefix="/api/clientes", tags=["clientes"])


def _dados_cliente(dados: ClienteIn) -> dict:
    valores = dados.model_dump()
    try:
        valores["cpf_cnpj"] = validar_cpf_cnpj(valores.get("cpf_cnpj") or "")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    valores["uf"] = (valores.get("uf") or "").upper()
    return valores


@router.get("", response_model=list[ClienteOut])
def listar(busca: str = "", db: Session = Depends(get_db)):
    consulta = db.query(Cliente).order_by(Cliente.nome)
    if busca:
        filtro = f"%{busca}%"
        consulta = consulta.filter(
            Cliente.nome.ilike(filtro) | Cliente.cpf_cnpj.ilike(filtro)
        )
    return consulta.all()


@router.post("", response_model=ClienteOut, status_code=201)
def criar(dados: ClienteIn, db: Session = Depends(get_db)):
    cliente = Cliente(**_dados_cliente(dados))
    db.add(cliente)
    db.commit()
    return cliente


@router.put("/{cliente_id}", response_model=ClienteOut)
def atualizar(cliente_id: int, dados: ClienteIn, db: Session = Depends(get_db)):
    cliente = db.get(Cliente, cliente_id)
    if cliente is None:
        raise HTTPException(404, "Cliente não encontrado")
    for campo, valor in _dados_cliente(dados).items():
        setattr(cliente, campo, valor)
    db.commit()
    return cliente


@router.delete("/{cliente_id}", status_code=204)
def excluir(cliente_id: int, db: Session = Depends(get_db)):
    cliente = db.get(Cliente, cliente_id)
    if cliente is None:
        raise HTTPException(404, "Cliente não encontrado")
    if db.query(Nota).filter(Nota.cliente_id == cliente_id).first():
        raise HTTPException(409, "Cliente possui notas emitidas e não pode ser excluído.")
    db.delete(cliente)
    db.commit()
