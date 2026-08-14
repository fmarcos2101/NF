"""Fila de emissão e eventos off-line.

As notas e os eventos (cancelamento, carta de correção) são gravados primeiro
no banco local. Um worker verifica a conectividade periodicamente e, quando há
internet, transmite na ordem de criação. Falhas de rede devolvem o item à fila.
Após a autorização, o DANFE é gerado e o e-mail é despachado sozinho.
"""
import asyncio
import logging
import time
from datetime import datetime

import httpx

from ..database import ARQUIVOS_DIR, SessionLocal
from ..models import (
    Nota,
    NotaEvento,
    StatusEvento,
    StatusNota,
    TipoEvento,
)
from . import backup as svc_backup
from . import config as cfg
from .danfe import gerar_danfe
from .email_sender import enviar_cancelamento_por_email, enviar_nota_por_email, smtp_configurado
from .emissores import obter_emissor
from .emissores.base import ErroComunicacao

log = logging.getLogger("nf.fila")

INTERVALO_SEGUNDOS = 10
CACHE_CONECTIVIDADE_SEGUNDOS = 15
URL_TESTE_CONEXAO = "https://www.gstatic.com/generate_204"

_estado = {"online": False, "verificado_em": 0.0}


def esta_online(forcar: bool = False) -> bool:
    """Verifica conectividade com cache curto para não custar em cada request."""
    agora = time.monotonic()
    if not forcar and agora - _estado["verificado_em"] < CACHE_CONECTIVIDADE_SEGUNDOS:
        return _estado["online"]
    try:
        httpx.head(URL_TESTE_CONEXAO, timeout=3)
        _estado["online"] = True
    except httpx.HTTPError:
        _estado["online"] = False
    _estado["verificado_em"] = agora
    return _estado["online"]


def _finalizar_autorizacao(db, nota: Nota, resultado, emitente: dict[str, str]) -> None:
    nota.status = StatusNota.AUTORIZADA
    nota.chave_acesso = resultado.chave_acesso
    nota.protocolo = resultado.protocolo
    nota.autorizada_em = datetime.now()
    nota.ultimo_erro = ""

    if resultado.xml:
        xml_path = ARQUIVOS_DIR / f"nota-{nota.id}.xml"
        xml_path.write_text(resultado.xml, encoding="utf-8")
        nota.xml_path = str(xml_path)

    pdf_path = ARQUIVOS_DIR / f"nota-{nota.id}.pdf"
    try:
        gerar_danfe(nota, emitente, str(pdf_path))
        nota.pdf_path = str(pdf_path)
    except Exception as exc:  # PDF não pode impedir a autorização
        log.exception("Falha ao gerar DANFE da nota %s", nota.id)
        nota.ultimo_erro = f"DANFE: {exc}"

    db.commit()

    if nota.cliente and nota.cliente.email and smtp_configurado(emitente):
        try:
            enviar_nota_por_email(nota, emitente)
            nota.email_enviado_em = datetime.now()
        except Exception as exc:
            log.warning("Falha ao enviar e-mail da nota %s: %s", nota.id, exc)
            nota.ultimo_erro = f"E-mail: {exc}"
        db.commit()


def processar_nota(db, nota: Nota) -> None:
    emitente = cfg.obter_todas(db)
    emissor = obter_emissor(db)

    nota.status = StatusNota.PROCESSANDO
    nota.tentativas += 1
    db.commit()

    try:
        resultado = emissor.emitir(nota, emitente)
    except ErroComunicacao as exc:
        nota.status = StatusNota.PENDENTE
        nota.ultimo_erro = str(exc)
        db.commit()
        log.info("Nota %s voltou à fila: %s", nota.id, exc)
        return
    except Exception as exc:
        nota.status = StatusNota.PENDENTE
        nota.ultimo_erro = f"Erro inesperado: {exc}"
        db.commit()
        log.exception("Erro inesperado ao emitir nota %s", nota.id)
        return

    if resultado.autorizada:
        _finalizar_autorizacao(db, nota, resultado, emitente)
        log.info("Nota %s autorizada (chave %s)", nota.id, nota.chave_acesso)
    else:
        nota.status = StatusNota.REJEITADA
        nota.motivo_rejeicao = resultado.motivo
        db.commit()
        log.info("Nota %s rejeitada: %s", nota.id, resultado.motivo)


def _salvar_xml_evento(evento: NotaEvento, xml: str) -> None:
    if not xml:
        return
    prefixo = "canc" if evento.tipo == TipoEvento.CANCELAMENTO else "cce"
    xml_path = ARQUIVOS_DIR / f"nota-{evento.nota_id}-{prefixo}-{evento.id}.xml"
    xml_path.write_text(xml, encoding="utf-8")
    evento.xml_path = str(xml_path)


def processar_evento(db, evento: NotaEvento) -> None:
    nota = evento.nota
    emitente = cfg.obter_todas(db)
    emissor = obter_emissor(db)

    evento.status = StatusEvento.PROCESSANDO
    evento.tentativas += 1
    db.commit()

    try:
        if evento.tipo == TipoEvento.CANCELAMENTO:
            resultado = emissor.cancelar(nota, evento.texto)
        else:
            resultado = emissor.carta_correcao(nota, evento.texto)
    except ErroComunicacao as exc:
        evento.status = StatusEvento.PENDENTE
        evento.ultimo_erro = str(exc)
        db.commit()
        log.info("Evento %s voltou à fila: %s", evento.id, exc)
        return
    except Exception as exc:
        evento.status = StatusEvento.PENDENTE
        evento.ultimo_erro = f"Erro inesperado: {exc}"
        db.commit()
        log.exception("Erro inesperado no evento %s", evento.id)
        return

    if not resultado.autorizado:
        evento.status = StatusEvento.REJEITADO
        evento.motivo_rejeicao = resultado.motivo
        db.commit()
        log.info("Evento %s rejeitado: %s", evento.id, resultado.motivo)
        return

    evento.status = StatusEvento.AUTORIZADO
    evento.protocolo = resultado.protocolo
    evento.sequencia = resultado.sequencia or evento.sequencia
    evento.processado_em = datetime.now()
    evento.ultimo_erro = ""
    _salvar_xml_evento(evento, resultado.xml)

    if evento.tipo == TipoEvento.CANCELAMENTO:
        nota.status = StatusNota.CANCELADA
        nota.cancelada_em = evento.processado_em
        nota.justificativa_cancelamento = evento.texto
        if nota.pdf_path:
            try:
                gerar_danfe(nota, emitente, nota.pdf_path)
            except Exception:
                log.exception("Falha ao regenerar DANFE cancelado da nota %s", nota.id)
        if nota.cliente and nota.cliente.email and smtp_configurado(emitente):
            try:
                enviar_cancelamento_por_email(nota, emitente)
            except Exception as exc:
                log.warning("Falha ao enviar e-mail de cancelamento da nota %s: %s", nota.id, exc)

    db.commit()
    log.info("Evento %s (%s) autorizado na nota %s", evento.id, evento.tipo.value, nota.id)


def processar_fila() -> dict[str, int]:
    """Emite notas e eventos pendentes (se houver internet)."""
    db = SessionLocal()
    try:
        notas = (
            db.query(Nota)
            .filter(Nota.status == StatusNota.PENDENTE)
            .order_by(Nota.criado_em)
            .all()
        )
        eventos = (
            db.query(NotaEvento)
            .filter(NotaEvento.status == StatusEvento.PENDENTE)
            .order_by(NotaEvento.criado_em)
            .all()
        )
        if not notas and not eventos:
            return {"notas": 0, "eventos": 0}
        if not esta_online():
            log.debug(
                "Off-line: %s nota(s) e %s evento(s) na fila",
                len(notas), len(eventos),
            )
            return {"notas": 0, "eventos": 0}
        for nota in notas:
            processar_nota(db, nota)
        for evento in eventos:
            processar_evento(db, evento)
        return {"notas": len(notas), "eventos": len(eventos)}
    finally:
        db.close()


async def worker_fila() -> None:
    log.info("Worker da fila de emissão iniciado")
    await asyncio.to_thread(svc_backup.talvez_criar)
    while True:
        try:
            await asyncio.to_thread(processar_fila)
            await asyncio.to_thread(svc_backup.talvez_criar)
        except Exception:
            log.exception("Erro no worker da fila")
        await asyncio.sleep(INTERVALO_SEGUNDOS)
