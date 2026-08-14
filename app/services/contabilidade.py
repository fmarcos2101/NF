"""Pacote XML do mês para o contador."""
import zipfile
from datetime import datetime
from io import BytesIO
from pathlib import Path

from sqlalchemy.orm import Session

from ..models import Inutilizacao, Nota, NotaEvento, StatusEvento, StatusInutilizacao, StatusNota, TipoEvento


def _no_mes(valor: datetime | None, inicio: datetime, fim: datetime) -> bool:
    return valor is not None and inicio <= valor < fim


def _intervalo(ano: int, mes: int) -> tuple[datetime, datetime]:
    inicio = datetime(ano, mes, 1)
    if mes == 12:
        return inicio, datetime(ano + 1, 1, 1)
    return inicio, datetime(ano, mes + 1, 1)


def montar_zip_xml(db: Session, ano: int, mes: int) -> tuple[bytes, int]:
    """Retorna (conteúdo ZIP, quantidade de arquivos)."""
    inicio, fim = _intervalo(ano, mes)
    buffer = BytesIO()
    incluidos = 0
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zipf:
        notas = (
            db.query(Nota)
            .filter(Nota.status.in_((StatusNota.AUTORIZADA, StatusNota.CANCELADA)))
            .all()
        )
        for nota in notas:
            if _no_mes(nota.autorizada_em, inicio, fim) and nota.xml_path:
                caminho = Path(nota.xml_path)
                if caminho.exists():
                    tipo = "NFCe" if nota.modelo == 65 else "NFe"
                    zipf.write(caminho, arcname=f"{tipo}-{nota.numero:09d}.xml")
                    incluidos += 1
            for evento in nota.eventos:
                if evento.status != StatusEvento.AUTORIZADO:
                    continue
                if not _no_mes(evento.processado_em, inicio, fim):
                    continue
                if not evento.xml_path:
                    continue
                caminho = Path(evento.xml_path)
                if not caminho.exists():
                    continue
                sufixo = "canc" if evento.tipo == TipoEvento.CANCELAMENTO else "cce"
                zipf.write(caminho, arcname=f"NFe-{nota.numero:09d}-{sufixo}-{evento.id}.xml")
                incluidos += 1

        inutilizacoes = (
            db.query(Inutilizacao)
            .filter(Inutilizacao.status == StatusInutilizacao.AUTORIZADA)
            .all()
        )
        for item in inutilizacoes:
            if not _no_mes(item.processada_em, inicio, fim):
                continue
            if not item.xml_path:
                continue
            caminho = Path(item.xml_path)
            if not caminho.exists():
                continue
            nome = f"Inut-{item.modelo}-{item.serie}-{item.numero_inicial}-{item.numero_final}.xml"
            zipf.write(caminho, arcname=nome)
            incluidos += 1

    return buffer.getvalue(), incluidos
